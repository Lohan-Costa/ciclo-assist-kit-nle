"""Servidor de vetores SigLIP 2 no Mac mini — quadro → vetor e frase → vetor.

    python3 siglip_servidor.py --baixar            # baixa e confere os três arquivos
    python3 siglip_servidor.py                     # escuta em 0.0.0.0:7825

⭐ Decisão do editor (2026-09-14): a busca por FRASE mora inteira no Mac. MEDIDO no notebook
com o Media Composer aberto: carregar o codificador de imagem levou o sistema a **169 MB
livres, 98% de carga** — o terreno das telas azuis. O notebook manda JPEG e frases pela
rede; nenhum modelo é carregado lá.

## O que este programa é, e o que NÃO é (spec `docs/spec/2026-09-14-siglip-no-mac.md`)

- É um BACKEND HTTP do serviço do notebook, como o Ollama. ⛔ Não é servidor MCP: o Claude
  não sabe que ele existe.
- Não guarda nada: o índice (os vetores de cada mídia) mora no cache do notebook, endereçado
  pelo UMID do master. Aqui entra quadro, sai vetor, e o quadro é esquecido.
- Não fala com o notebook: só responde.

## ⛔⛔ O pré-processamento É o modelo

Um quadro redimensionado de outro jeito dá outro vetor, e o placar medido deixa de valer.
Tudo abaixo vem do `preprocessor_config.json` e do `tokenizer_config.json` do repositório:
256×256 bicúbico SEM preservar proporção, `/255`, média e desvio 0,5; texto em minúsculas,
`<eos>` no fim, preenchido com `<pad>` (id 0) até 64 tokens; saída `pooler_output`, e o
vetor sai NORMALIZADO (produto escalar = parecença).

Dependências (só no Mac): `numpy onnxruntime tokenizers pillow`.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import logging
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol

log = logging.getLogger("siglip")

REPOSITORIO = "onnx-community/siglip2-base-patch16-256-ONNX"

#: ⛔ Os três arquivos, com o SHA-256 que o Hugging Face publica (conferido em 2026-09-13).
#: Arquivo com outro hash não carrega: seria outro modelo com o mesmo nome.
ARQUIVOS = {
    "vision_model.onnx": ("onnx/vision_model.onnx",
                          "f5cb16728a704703f05516ded628397e11dbca4de2eb5db04b0c0bcee988aa7a"),
    "text_model_fp16.onnx": ("onnx/text_model_fp16.onnx",
                             "80954edffdc689599e5d5bc6a1738380bc9e8139a18e5c8892485f248b6b4890"),
    "tokenizer.json": ("tokenizer.json",
                       "cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322"),
}

LADO = 256
TOKENS = 64
DIM = 768
PORTA = 7825

#: ⚠️ Tetos por pedido. Um master tem 12 quadros amostrados; 16 cobre com folga e deixa o
#: pedido em ~2 MB. Frase é barata, mas uma lista sem teto é um pedido sem prazo.
MAX_IMAGENS = 16
MAX_FRASES = 32
MAX_CORPO = 16 * 1024 * 1024
MAX_CHARS_FRASE = 500

#: ⭐ A RECEITA que o notebook grava junto dos vetores (`gerador.siglip.json`). Mudou aqui —
#: outro modelo, outro lado, outro pré-processamento —, o índice velho cai sozinho lá.
RECEITA = {
    "modelo": REPOSITORIO,
    "visao_sha256": ARQUIVOS["vision_model.onnx"][1][:16],
    "texto_sha256": ARQUIVOS["text_model_fp16.onnx"][1][:16],
    "lado": LADO,
    "tokens": TOKENS,
    "dim": DIM,
    "normalizado": True,
}


class Codificador(Protocol):
    def imagens(self, jpegs: list[bytes]) -> "list[list[float]] | object": ...
    def frases(self, frases: list[str]) -> "list[list[float]] | object": ...


def conferir_arquivo(caminho: Path, sha: str) -> bool:
    if not caminho.exists():
        return False
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest() == sha


def baixar(pasta: Path) -> None:
    """Baixa o que falta e confere o hash de tudo. ⚠️ Arquivo com hash errado é APAGADO."""
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, (caminho, sha) in ARQUIVOS.items():
        destino = pasta / nome
        if conferir_arquivo(destino, sha):
            print(f"ok ........ {nome}")
            continue
        url = f"https://huggingface.co/{REPOSITORIO}/resolve/main/{caminho}"
        print(f"baixando .. {nome} ({url})")
        parcial = destino.with_suffix(destino.suffix + ".parcial")
        with urllib.request.urlopen(url, timeout=600) as r, parcial.open("wb") as f:
            while bloco := r.read(1 << 20):
                f.write(bloco)
        if not conferir_arquivo(parcial, sha):
            parcial.unlink(missing_ok=True)
            raise SystemExit(f"⛔ {nome}: o hash não confere. Nada foi guardado.")
        parcial.replace(destino)
        print(f"ok ........ {nome}")


class SigLIP:
    """O codificador de verdade: onnxruntime na CPU do Mac.

    ⚠️ CPU, não CoreML: medido no projeto anterior (`_PRODUCAO-V`), o provider do CoreML aceita
    542 de 719 nós e FALHA na execução. O M4 na CPU é mais rápido que o notebook.
    """

    def __init__(self, pasta: Path, threads: int = 4) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        for nome, (_, sha) in ARQUIVOS.items():
            if not conferir_arquivo(pasta / nome, sha):
                raise SystemExit(f"⛔ {pasta / nome} falta ou tem outro hash — rode --baixar")

        self._np = np
        opcoes = ort.SessionOptions()
        opcoes.intra_op_num_threads = threads
        opcoes.inter_op_num_threads = 1
        cpu = ["CPUExecutionProvider"]
        self._visao = ort.InferenceSession(str(pasta / "vision_model.onnx"), opcoes, providers=cpu)
        self._texto = ort.InferenceSession(str(pasta / "text_model_fp16.onnx"), opcoes,
                                           providers=cpu)
        self._tok = Tokenizer.from_file(str(pasta / "tokenizer.json"))
        self._tok.enable_padding(length=TOKENS, pad_id=0, pad_token="<pad>")
        self._tok.enable_truncation(max_length=TOKENS)
        # ⛔ Um pedido por vez no modelo: duas sessões simultâneas dobram a memória de
        #    ativação e não andam mais rápido na mesma CPU.
        self._trava = threading.Lock()

    def _normalizar(self, v):
        v = v.astype(self._np.float32)
        return v / (self._np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)

    def _pixels(self, jpeg: bytes):
        import io

        from PIL import Image
        np = self._np
        # ⛔ BICUBIC e SEM preservar proporção: é o `resample: 2` do preprocessor_config.
        img = Image.open(io.BytesIO(jpeg)).convert("RGB").resize((LADO, LADO), Image.BICUBIC)
        a = np.asarray(img, dtype=np.float32) / 255.0
        return ((a - 0.5) / 0.5).transpose(2, 0, 1)

    def _pooled(self, sessao, feed):
        nomes = [o.name for o in sessao.get_outputs()]
        return sessao.run(["pooler_output" if "pooler_output" in nomes else nomes[-1]], feed)[0]

    def imagens(self, jpegs):
        lote = self._np.stack([self._pixels(j) for j in jpegs])
        with self._trava:
            v = self._pooled(self._visao, {self._visao.get_inputs()[0].name: lote})
        return self._normalizar(v)

    def frases(self, frases):
        entrada = self._texto.get_inputs()[0]
        tipo = self._np.int64 if "int64" in entrada.type else self._np.int32
        ids = self._np.array([self._tok.encode(f.lower()).ids for f in frases], dtype=tipo)
        with self._trava:
            v = self._pooled(self._texto, {entrada.name: ids})
        return self._normalizar(v)


class PedidoRuim(ValueError):
    """O pedido não serve; vira 400 com a frase."""


def vetores_em_base64(matriz) -> str:
    """⭐ float32 little-endian, linha a linha. Base64 de binário é ~4× menor que JSON de
    768 números por quadro, e o notebook lê direto com `numpy.frombuffer`."""
    import numpy as np
    return base64.b64encode(np.ascontiguousarray(matriz, dtype="<f4").tobytes()).decode("ascii")


def responder_imagens(codificador: Codificador, corpo: dict) -> dict:
    lista = corpo.get("imagens")
    if not isinstance(lista, list) or not lista:
        raise PedidoRuim("mande 'imagens': uma lista de JPEG em base64")
    if len(lista) > MAX_IMAGENS:
        raise PedidoRuim(f"no máximo {MAX_IMAGENS} imagens por pedido")
    try:
        jpegs = [base64.b64decode(s, validate=True) for s in lista]
    except (ValueError, TypeError):
        raise PedidoRuim("uma das imagens não é base64 válido") from None
    if any(j[:2] != b"\xff\xd8" for j in jpegs):
        raise PedidoRuim("só JPEG")
    t0 = time.monotonic()
    matriz = codificador.imagens(jpegs)
    return {"dim": DIM, "quantos": len(jpegs), "vetores": vetores_em_base64(matriz),
            "ms": round((time.monotonic() - t0) * 1000), "receita": RECEITA}


def responder_frases(codificador: Codificador, corpo: dict) -> dict:
    lista = corpo.get("frases")
    if not isinstance(lista, list) or not lista:
        raise PedidoRuim("mande 'frases': uma lista de textos")
    if len(lista) > MAX_FRASES:
        raise PedidoRuim(f"no máximo {MAX_FRASES} frases por pedido")
    if any(not isinstance(f, str) or not f.strip() or len(f) > MAX_CHARS_FRASE for f in lista):
        raise PedidoRuim(f"cada frase é um texto de 1 a {MAX_CHARS_FRASE} caracteres")
    t0 = time.monotonic()
    matriz = codificador.frases([f.strip() for f in lista])
    return {"dim": DIM, "quantos": len(lista), "vetores": vetores_em_base64(matriz),
            "ms": round((time.monotonic() - t0) * 1000), "receita": RECEITA}


def cliente_aceito(endereco: str) -> bool:
    """⛔ Só a rede local. O serviço não tem senha — a mesma regra do Ollama (spec §6)."""
    try:
        ip = ipaddress.ip_address(endereco)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def fabricar_manipulador(codificador: Codificador):
    class Manipulador(BaseHTTPRequestHandler):
        server_version = "siglip-ciclo/1"

        def log_message(self, formato, *args):  # noqa: N802 — nome da stdlib
            log.info("%s %s", self.address_string(), formato % args)

        def _json(self, status: int, dados: dict) -> None:
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _porteiro(self) -> bool:
            if not cliente_aceito(self.client_address[0]):
                self._drenar()
                self._json(403, {"ok": False, "erro": "só rede local"})
                return False
            return True

        def _drenar(self) -> None:
            """Lê o corpo antes de RECUSAR o pedido.

            ⛔⛔ Sem isto o servidor responde e fecha com o cliente ainda escrevendo, e no
            Windows ele recebe `ConnectionAbortedError [WinError 10053]` em vez do 404 que
            o servidor mandou. MEDIDO: `test_rota_e_caminho_exato` falhava assim em 1 de
            cada 3 ou 4 rodadas da suíte — o pior tipo de teste, o que se aprende a ignorar.
            ⚠️ Com teto: um corpo gigante não vira leitura gigante só para ser recusado.
            """
            try:
                falta = min(int(self.headers.get("Content-Length") or 0), MAX_CORPO)
            except (TypeError, ValueError):
                return
            while falta > 0:
                pedaco = self.rfile.read(min(falta, 64 * 1024))
                if not pedaco:
                    return
                falta -= len(pedaco)

        def do_GET(self):  # noqa: N802
            if not self._porteiro():
                return
            if self.path == "/saude":
                self._json(200, {"ok": True, "receita": RECEITA,
                                 "limites": {"imagens": MAX_IMAGENS, "frases": MAX_FRASES}})
            else:
                self._json(404, {"ok": False, "erro": "rota desconhecida"})

        def do_POST(self):  # noqa: N802
            if not self._porteiro():
                return
            rotas = {"/imagens": responder_imagens, "/frases": responder_frases}
            # ⛔ Caminho EXATO, nunca prefixo — regra da casa.
            if self.path not in rotas:
                self._drenar()
                self._json(404, {"ok": False, "erro": "rota desconhecida"})
                return
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho <= 0 or tamanho > MAX_CORPO:
                self._drenar()
                self._json(413 if tamanho > MAX_CORPO else 400,
                           {"ok": False, "erro": f"corpo de 1 byte a {MAX_CORPO} bytes"})
                return
            try:
                corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
                if not isinstance(corpo, dict):
                    raise PedidoRuim("o corpo é um objeto JSON")
                self._json(200, {"ok": True, **rotas[self.path](codificador, corpo)})
            except (PedidoRuim, ValueError) as e:
                self._json(400, {"ok": False, "erro": str(e)})
            except Exception as e:  # noqa: BLE001 — erro do modelo não derruba o serviço
                log.exception("falhou em %s", self.path)
                self._json(500, {"ok": False, "erro": f"{type(e).__name__}: {e}"})

    return Manipulador


class Servidor(ThreadingHTTPServer):
    # ⛔ Medido no notebook (2026-09-12): com reuse, um segundo processo binda por cima em
    #    silêncio. No macOS o bind falha de verdade, mas desligado é o certo nos dois.
    allow_reuse_address = False
    daemon_threads = True


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--modelos", default=os.environ.get("SIGLIP_MODELOS",
                                                       str(Path.home() / "siglip-modelos")))
    p.add_argument("--baixar", action="store_true")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--porta", type=int, default=PORTA)
    p.add_argument("--threads", type=int, default=4)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

    pasta = Path(args.modelos).expanduser()
    if args.baixar:
        baixar(pasta)
        return 0

    t0 = time.monotonic()
    codificador = SigLIP(pasta, threads=args.threads)
    log.info("modelos carregados em %.1f s de %s", time.monotonic() - t0, pasta)
    try:
        servidor = Servidor((args.host, args.porta), fabricar_manipulador(codificador))
    except OSError as e:
        raise SystemExit(f"⛔ não consegui escutar em {args.host}:{args.porta}: {e}") from None
    log.info("escutando em http://%s:%d  (receita %s)", args.host, args.porta, RECEITA)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
