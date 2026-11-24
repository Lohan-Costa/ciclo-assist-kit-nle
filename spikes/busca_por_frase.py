r"""Buscar plano por FRASE neste notebook: o SigLIP 2 aguenta ao lado do Media Composer?

    python spikes/busca_por_frase.py                 # mede tudo, 4 threads
    python spikes/busca_por_frase.py --threads 8
    python spikes/busca_por_frase.py --midias 10     # só as 10 primeiras decupadas

A pergunta do editor (2026-09-13): o Premiere 26 e o Resolve 21 embarcam CLIP/SigLIP na
máquina; o Qwen/Gemma derrubou este notebook, mas um par imagem-texto é outra classe de peso.
*"Se não aguentar, migramos para o Mac de vez."* Este spike dá o número das duas metades
dessa frase: **aguenta?** (memória, tempo) e **serve?** (acerto).

## ⛔⛔ Por que isto NÃO é o que deu tela azul

As telas azuis vieram com o Ollama carregando modelo na **GPU** (RTX 4050, 6 GB) ao lado do
Media Composer. Aqui é **onnxruntime só na CPU** — o mesmo caminho do MobileNetV2 que já
roda em produção —, com threads LIMITADAS para o MC não ficar sem núcleo.

⚠️ Mas a memória é o risco real, e MEDIDO antes de escrever isto: **1,45 GB disponíveis de
15,7**, com o `AvidMediaComposer` segurando 11,3 GB privados (quase tudo paginado). O spike
imprime a RAM do processo e a do sistema a cada passo, e carrega um codificador de cada vez.

## O modelo, e de onde ele veio

`onnx-community/siglip2-base-patch16-256-ONNX`, já baixado neste notebook por um projeto
anterior (`_PRODUCAO-V`). ⚠️ Os `snapshots\` do cache do Hugging Face são atalhos do macOS
(`XSym`, 1.067 bytes) que o Windows não segue; os `blobs\` têm o conteúdo, e os nomes abaixo
foram casados pelo TAMANHO registrado no `manifesto.json` daquele projeto.

Pré-processamento (do `preprocessor_config.json`): 256×256 bicúbico **sem preservar
proporção**, `/255`, média e desvio 0,5. Texto: tokenizer Gemma (256 mil tokens,
multilíngue), minúsculas, `<eos>` no fim, preenchido até 64 com `<pad>` — o `tokenizers`
já vem no ambiente pelo faster-whisper, então **não entra dependência nova**.

## O gabarito, e o que ele aguenta

As decupagens do cache (Haiku 4.5 e, desde 2026-09-13, `qwen3-vl:8b-instruct` no Mac, 90%
na M1). Para cada valor dos campos fechados — `close`, `noite`, `exterior`… — a frase vira
vetor, cada mídia recebe a nota do seu MELHOR quadro, e o placar é a **AUC**: a chance de uma
mídia que TEM o atributo ficar acima de uma que não tem. 0,5 é moeda; 1,0 é perfeito.

⚠️ O gabarito é de modelo, não de gente, e erra ~10%: uma AUC de 0,9 aqui pode ser 1,0 de
verdade, ou o contrário. ⚠️ E com poucas mídias a AUC é ruído — o `n` sai do lado.
⛔ **Nada é gravado no cache.** Os quadros lidos já estão lá (vetorização ou decupagem).
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from cicloassist.midia import cache as _cache  # noqa: E402
from cicloassist.midia import frames as _frames  # noqa: E402

BLOBS = (Path(os.environ.get("LOCALAPPDATA", "")) / "CicloAssist" / "modelos" / "hf" / "hub"
         / "models--onnx-community--siglip2-base-patch16-256-ONNX" / "blobs")
VISAO = BLOBS / "f5cb16728a704703f05516ded628397e11dbca4de2eb5db04b0c0bcee988aa7a"  # 354,8 MB
TEXTO = BLOBS / "80954edffdc689599e5d5bc6a1738380bc9e8139a18e5c8892485f248b6b4890"  # 538,7 MB fp16
TOKENIZER = BLOBS / "cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322"

#: ⭐ A variante int8, baixada em 2026-09-13 com o SHA-256 conferido contra o que o Hugging Face
#: publica: texto 270 MB (o fp16 tem 539 e ocupava 835 MB de RAM), imagem 90 MB (o fp32, 355).
INT8 = BLOBS.parents[3] / "siglip2-base-256"
VARIANTES = {
    "fp": (VISAO, TEXTO, TOKENIZER),
    "int8": (INT8 / "vision_model_int8.onnx", INT8 / "text_model_int8.onnx",
             INT8 / "tokenizer.json"),
    # Os mistos dizem QUAL metade a quantização estraga.
    "imagem-int8": (INT8 / "vision_model_int8.onnx", TEXTO, TOKENIZER),
    "texto-int8": (VISAO, INT8 / "text_model_int8.onnx", TOKENIZER),
}

LADO = 256
TOKENS = 64
QUADROS_POR_MIDIA = 12

#: Uma frase por valor de campo fechado, em PORTUGUÊS (o editor digita assim) e em INGLÊS (o
#: Claude pode traduzir antes de chamar a ferramenta). ⚠️ `camera` fica de fora: movimento
#: não existe num quadro parado.
FRASES = {
    ("enquadramento", "geral"): ("um plano geral, bem aberto, mostrando o ambiente inteiro",
                                 "a very wide shot showing the whole place"),
    ("enquadramento", "conjunto"): ("um plano de conjunto, pessoas de corpo inteiro",
                                    "a full shot of people from head to toe"),
    ("enquadramento", "médio"): ("um plano médio, uma pessoa da cintura para cima",
                                 "a medium shot of a person from the waist up"),
    ("enquadramento", "close"): ("um close no rosto de uma pessoa",
                                 "a close-up of a person's face"),
    ("enquadramento", "detalhe"): ("um plano detalhe de um objeto",
                                   "an extreme close-up detail of an object"),
    ("angulo", "plongée"): ("câmera alta, olhando de cima para baixo",
                            "a high angle shot looking down"),
    ("angulo", "contra-plongée"): ("câmera baixa, olhando de baixo para cima",
                                   "a low angle shot looking up"),
    ("local", "interior"): ("uma cena em ambiente interno", "an indoor scene"),
    ("local", "exterior"): ("uma cena ao ar livre", "an outdoor scene"),
    ("momento", "dia"): ("uma cena de dia, com luz do dia", "a daytime scene in daylight"),
    ("momento", "noite"): ("uma cena à noite, no escuro", "a scene at night, in the dark"),
}


# ── memória: o número que decide ─────────────────────────────────────────────

class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


class _MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memoria(rotulo: str) -> None:
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    # ⚠️ Sem `restype`, o HANDLE de 64 bits vinha truncado e a leitura devolvia ZERO.
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    ms = _MEMSTAT()
    ms.dwLength = ctypes.sizeof(_MEMSTAT)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
    print(f"   [mem] {rotulo:28s} processo: {pmc.WorkingSetSize / 2**20:6.0f} MB na RAM "
          f"(pico {pmc.PeakWorkingSetSize / 2**20:.0f}) · sistema: "
          f"{ms.ullAvailPhys / 2**20:5.0f} MB disponíveis, carga {ms.dwMemoryLoad}%")


# ── os dois codificadores ────────────────────────────────────────────────────

def sessao(caminho: Path, threads: int):
    import onnxruntime as ort
    opcoes = ort.SessionOptions()
    opcoes.intra_op_num_threads = threads
    opcoes.inter_op_num_threads = 1
    t0 = time.monotonic()
    # ⛔ Só CPU, dito explicitamente: nada de GPU neste notebook.
    s = ort.InferenceSession(str(caminho), opcoes, providers=["CPUExecutionProvider"])
    print(f"   carregou {caminho.name[:8]}… em {time.monotonic() - t0:.1f} s · "
          f"entradas {[(i.name, i.type) for i in s.get_inputs()]} · "
          f"saídas {[o.name for o in s.get_outputs()]}")
    return s


def pixels(jpeg_path: Path) -> np.ndarray:
    """JPEG → (3, 256, 256) em [-1, 1]. ⛔ Sem Pillow: o ffmpeg decodifica e redimensiona."""
    r = subprocess.run(
        [_frames.achar_ffmpeg(), "-v", "error", "-i", str(jpeg_path),
         "-vf", f"scale={LADO}:{LADO}:flags=bicubic", "-pix_fmt", "rgb24",
         "-f", "rawvideo", "pipe:1"],
        capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    esperado = LADO * LADO * 3
    if r.returncode != 0 or len(r.stdout) < esperado:
        raise RuntimeError(f"não decodifiquei {jpeg_path.name}")
    a = np.frombuffer(r.stdout[:esperado], dtype=np.uint8).reshape(LADO, LADO, 3)
    return (a.transpose(2, 0, 1).astype(np.float32) / 255.0 - 0.5) / 0.5


def normalizar(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32)
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


def saida_pooled(s, feed: dict) -> np.ndarray:
    nomes = [o.name for o in s.get_outputs()]
    alvo = "pooler_output" if "pooler_output" in nomes else nomes[-1]
    return s.run([alvo], feed)[0]


# ── o gabarito ───────────────────────────────────────────────────────────────

def midias_com_gabarito(limite: int) -> list[tuple[_cache.Midia, dict, list[Path]]]:
    """`(mídia, nota, quadros)` de quem tem decupagem com campo fechado E quadro no disco."""
    saida = []
    for midia in _cache.todas():
        notas = [n for n in midia.ler_notas()
                 if any(n.get(c) for c, _ in FRASES)]
        if not notas:
            continue
        # A nota da mídia inteira manda; nota de take é recorte.
        nota = next((n for n in notas if n.get("escopo") == "midia"), notas[0])
        posicoes = midia.quadros_guardados()
        if not posicoes:
            continue
        passo = max(1, len(posicoes) // QUADROS_POR_MIDIA)
        quadros = [midia.caminho_do_quadro(p) for p in posicoes[::passo][:QUADROS_POR_MIDIA]]
        saida.append((midia, nota, quadros))
    return saida[:limite] if limite else saida


def auc(positivos: list[float], negativos: list[float]) -> float:
    """Chance de um positivo ficar acima de um negativo (empate vale meio)."""
    ganhos = sum((p > n) + 0.5 * (p == n) for p in positivos for n in negativos)
    return ganhos / (len(positivos) * len(negativos))


def pelo_mac(url: str, alvo) -> tuple[list[np.ndarray], dict]:
    """Os mesmos vetores, calculados pelo servidor do Mac (`servidor_mac/siglip_servidor.py`).

    ⭐ É a ACEITAÇÃO da mudança para o Mac: mesmo gabarito, mesmas frases, o placar tem de
    sair perto do medido no notebook (0,79 pt / 0,84 en com 172 mídias, 2026-09-14). Longe
    disso, o pré-processamento de lá não é o daqui.
    ⚠️ Manda o JPEG do CACHE (768 px); quem redimensiona para 256 é o Mac.
    """
    import base64
    import json as _json
    import urllib.request

    def post(caminho, corpo):
        req = urllib.request.Request(url.rstrip("/") + caminho,
                                     data=_json.dumps(corpo).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            d = _json.loads(r.read())
        return np.frombuffer(base64.b64decode(d["vetores"]), dtype="<f4").reshape(
            d["quantos"], d["dim"]), d

    print("1. IMAGEM pelo Mac")
    t0 = time.monotonic()
    vetores, total, receita = [], 0, None
    for _, _, quadros in alvo:
        jpegs = [base64.b64encode(q.read_bytes()).decode("ascii") for q in quadros]
        partes = []
        for k in range(0, len(jpegs), 16):
            v, d = post("/imagens", {"imagens": jpegs[k:k + 16]})
            partes.append(v)
            receita = d.get("receita")
        vetores.append(np.concatenate(partes))
        total += len(jpegs)
    print(f"   {total} quadros em {time.monotonic() - t0:.0f} s "
          f"({1000 * (time.monotonic() - t0) / max(1, total):.0f} ms/quadro com a rede)")
    print(f"   receita do servidor: {receita}")

    print("2. TEXTO pelo Mac")
    chaves = [(chave, lingua) for chave in FRASES for lingua in ("pt", "en")]
    textos = [FRASES[c][0 if l == "pt" else 1] for c, l in chaves]
    t0 = time.monotonic()
    v, _ = post("/frases", {"frases": textos})
    print(f"   {len(textos)} frases em {1000 * (time.monotonic() - t0):.0f} ms")
    memoria("depois do Mac")
    return vetores, {c: v[i] for i, c in enumerate(chaves)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--threads", type=int, default=4,
                   help="núcleos da CPU para o modelo (o MC precisa dos outros)")
    p.add_argument("--midias", type=int, default=0, help="limita quantas (0 = todas)")
    p.add_argument("--variante", choices=sorted(VARIANTES), default="fp",
                   help="fp = imagem fp32 + texto fp16 · int8 = as duas quantizadas")
    p.add_argument("--mac", default="",
                   help="URL do servidor SigLIP do Mac (http://192.168.1.4:7825): os vetores "
                        "vêm de lá, e o placar mede o servidor em vez do notebook")
    args = p.parse_args()
    visao_arq, texto_arq, tok_arq = VARIANTES[args.variante]

    for arq in (() if args.mac else (visao_arq, texto_arq, tok_arq)):
        if not arq.exists():
            sys.exit(f"não achei {arq}")

    memoria("antes de tudo")
    alvo = midias_com_gabarito(args.midias)
    if not alvo:
        sys.exit("não há mídia decupada com quadros no cache")
    total_quadros = sum(len(q) for _, _, q in alvo)
    print(f"gabarito .... {len(alvo)} mídias decupadas, {total_quadros} quadros · "
          f"threads={args.threads} · CPU só · variante {args.variante}")
    print("=" * 78)

    if args.mac:
        vetores, frases = pelo_mac(args.mac, alvo)
    else:
        # ── 1. imagem ──
        print("1. codificador de IMAGEM")
        visao = sessao(visao_arq, args.threads)
        memoria("imagem carregada")
        entrada = visao.get_inputs()[0].name
        vetores: list[np.ndarray] = []
        t_decod = t_mod = 0.0
        for i, (midia, _, quadros) in enumerate(alvo):
            t0 = time.monotonic()
            lote = np.stack([pixels(q) for q in quadros])
            t1 = time.monotonic()
            # ⚠️ Um quadro por vez: lote maior é arena de memória maior, e memória é o que falta.
            v = np.concatenate([saida_pooled(visao, {entrada: lote[j:j + 1]})
                                for j in range(len(lote))])
            t2 = time.monotonic()
            t_decod += t1 - t0
            t_mod += t2 - t1
            vetores.append(normalizar(v))
            if i == 0:
                memoria("depois da 1ª mídia")
        ms_quadro = 1000 * t_mod / total_quadros
        print(f"   {total_quadros} quadros: modelo {ms_quadro:.0f} ms/quadro · "
              f"ffmpeg {1000 * t_decod / total_quadros:.0f} ms/quadro · dim {vetores[0].shape[1]}")
        memoria("imagem terminada")
        del visao
        gc.collect()
        memoria("imagem descarregada")

        # ── 2. texto ──
        print("2. codificador de TEXTO")
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(tok_arq))
        tok.enable_padding(length=TOKENS, pad_id=0, pad_token="<pad>")
        tok.enable_truncation(max_length=TOKENS)
        texto = sessao(texto_arq, args.threads)
        memoria("texto carregado")
        tipo_ids = texto.get_inputs()[0].type
        dtype_ids = np.int64 if "int64" in tipo_ids else np.int32

        frases = {}
        tempos = []
        for chave, (pt, en) in FRASES.items():
            for lingua, frase in (("pt", pt), ("en", en)):
                ids = np.array([tok.encode(frase.lower()).ids], dtype=dtype_ids)
                t0 = time.monotonic()
                frases[(chave, lingua)] = normalizar(
                    saida_pooled(texto, {texto.get_inputs()[0].name: ids}))[0]
                tempos.append(time.monotonic() - t0)
        print(f"   {len(tempos)} frases: {1000 * sorted(tempos)[len(tempos) // 2]:.0f} ms/frase "
              f"(mediana; a 1ª {1000 * tempos[0]:.0f} ms)")
        memoria("texto terminado")

    # ── 3. o placar ──
    print("=" * 78)
    print(f"{'atributo':28s} {'n+':>3s} {'n-':>3s}   {'AUC pt':>6s}  {'AUC en':>6s}")
    medias = {"pt": [], "en": []}
    for (campo, valor), _ in FRASES.items():
        rotulos = [nota.get(campo) for _, nota, _ in alvo]
        conhecidos = [i for i, r in enumerate(rotulos) if r]
        pos = [i for i in conhecidos if rotulos[i] == valor]
        neg = [i for i in conhecidos if rotulos[i] != valor]
        if not pos or not neg:
            continue
        linha = f"{campo + '=' + valor:28s} {len(pos):3d} {len(neg):3d}  "
        for lingua in ("pt", "en"):
            q = frases[((campo, valor), lingua)]
            nota_midia = [float((v @ q).max()) for v in vetores]
            a = auc([nota_midia[i] for i in pos], [nota_midia[i] for i in neg])
            medias[lingua].append(a)
            linha += f"  {a:6.2f}"
        print(linha)
    for lingua, lista in medias.items():
        if lista:
            print(f"AUC média ({lingua}) ...... {sum(lista) / len(lista):.2f} "
                  f"em {len(lista)} atributos  (0,5 = moeda)")

    print("\n⚠️ Leia com o n do lado: com poucas mídias a AUC é ruído. O gabarito é de modelo")
    print("   (Haiku / qwen3-vl), não de gente. Critério para levar ao produto, combinado")
    print("   ANTES do número: AUC média ≥ 0,80 em pt e o sistema sem cair abaixo de ~500 MB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
