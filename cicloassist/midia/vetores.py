"""O vetor visual de um master — e a busca por "planos parecidos com este".

É o que dá nome à aba. O editor pediu: *"arrastar uma imagem e pedir para localizar o
personagem, ou planos parecidos, para match cut"*.

## O motor, e por que este e não o famoso

`spikes/busca_visual.py` mediu os candidatos na bin C07 em 2026-09-11, com o gabarito de
graça que a cena dá (três planos, vários takes cada; o vizinho mais parecido devia ser do
mesmo plano, **excluindo os quadros do próprio take** — senão a medida vira "acha o mesmo
arquivo"):

```
ao acaso  38%   ·   pHash  93% (0 MB, 2 ms)   ·   MobileNetV2 em ONNX  99% (14 MB, 5 ms)
```

⇒ **Não precisa de CLIP de 350 MB**, e nada de torch: o `onnxruntime` já é dependência —
é o runtime do `sherpa-onnx`. O que entra de novo é um arquivo de modelo de 14 MB, baixado
uma vez.

⚠️ Medido em cena fechada — mesma luz, mesmo cenário. *"Ache a Personagem F em OUTRA cena"* é
mais difícil e continua **por medir**. A ferramenta diz o que é: parecença de
enquadramento e conteúdo, não reconhecimento de pessoa.

## ⛔ Sem Pillow

Decodificar e redimensionar o JPEG pediria Pillow, que não é dependência nossa. O ffmpeg
já é pré-requisito e faz as duas coisas numa chamada, entregando **RGB cru** que o numpy
lê direto — o mesmo truque que evita `-pix_fmt` errado e conversão de cor na mão.

## Onde mora

```
%LOCALAPPDATA%\\CicloAssist\\midia\\<umid>\\vetores.npy    ← N × 1000, float32, normalizado
                                          \\vetores.json   ← as posições, em tempo do MASTER
                                          \\gerador.vetores.json
%LOCALAPPDATA%\\CicloAssist\\modelos\\mobilenetv2-12.onnx  ← 14 MB, baixado uma vez
```

⭐ Endereçado pelo UMID do master, como todo o resto: vetorizou uma vez, e qualquer take
daquela mídia — subclipe, groupclipe — acha pronto.
"""

from __future__ import annotations

import json
import logging
import subprocess
import urllib.error
import urllib.request
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from . import cache as _cache
from . import frames as _frames

log = logging.getLogger("cicloassist.midia.vetores")

#: O lado da entrada do MobileNetV2.
LADO = 224

#: Quantos quadros por master. ⚠️ Poucos e espalhados: o que se quer é cobrir o material,
#: não colher quadros quase idênticos — quatro quadros vizinhos do mesmo plano dizem a
#: mesma coisa e só engordam a busca.
QUANTOS = 12

#: Vai no `gerador.vetores.json`. Mudou aqui, os vetores antigos deixam de servir sozinhos.
ASSINATURA = {"modelo": "mobilenetv2-12", "lado": LADO, "quadros": QUANTOS}

NOME_DO_MODELO = "mobilenetv2-12.onnx"

#: ⚠️ O zoológico oficial do ONNX. O modelo é um CLASSIFICADOR usado como extrator: o
#: vetor é a saída final (o grafo não expõe a penúltima camada). Para SEMELHANÇA ele
#: serve — é o que o spike mediu, e é onde vieram os 99%.
URL_DO_MODELO = ("https://github.com/onnx/models/raw/main/validated/vision/"
                 "classification/mobilenet/model/mobilenetv2-12.onnx")

#: Normalização do ImageNet, que é como o modelo foi treinado.
_MEDIA = (0.485, 0.456, 0.406)
_DESVIO = (0.229, 0.224, 0.225)

_sessao = None


class ModeloIndisponivel(RuntimeError):
    """Não há como vetorizar: o modelo não está em disco e não deu para baixar."""


def pasta_dos_modelos() -> Path:
    """Na pasta de dados do produto, e não dentro do cache de mídia.

    ⚠️ O botão "apagar tudo" do painel apaga a pasta de mídia inteira. O modelo não é
    cache do material do cliente — é peça do produto, e rebaixá-lo custaria 14 MB de
    download a cada limpeza.

    ⚠️ Na pasta de dados, e não `cache.raiz().parent`: com o cache na raiz de um volume do
    Mac, o pai é `/Volumes` (do root), e a falha de gravar virava "não consegui extrair
    nenhum quadro" (2026-09-14).
    """
    from ..servico.config import pasta
    return pasta() / "modelos"


def caminho_do_modelo() -> Path:
    return pasta_dos_modelos() / NOME_DO_MODELO


def temos_o_modelo() -> bool:
    alvo = caminho_do_modelo()
    try:
        return alvo.is_file() and alvo.stat().st_size > 1_000_000
    except OSError:
        return False


def baixar_o_modelo(aviso: Callable[[str], None] | None = None) -> Path:
    """Traz o modelo, uma vez. ⭐ É a ÚNICA coisa neste produto que precisa de internet.

    ⚠️ Baixa para um temporário e só então renomeia: um download interrompido deixaria um
    arquivo pela metade que o onnxruntime tentaria abrir para sempre.
    """
    alvo = caminho_do_modelo()
    if temos_o_modelo():
        return alvo

    alvo.parent.mkdir(parents=True, exist_ok=True)
    if aviso:
        aviso("baixando o modelo de imagem (14 MB, uma vez)")
    log.info("baixando %s → %s", URL_DO_MODELO, alvo)
    try:
        with urllib.request.urlopen(URL_DO_MODELO, timeout=120) as resposta:
            dados = resposta.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ModeloIndisponivel(
            "não consegui baixar o modelo de imagem (14 MB). "
            "É a única parte do produto que precisa de internet."
        ) from e
    if len(dados) < 1_000_000:
        raise ModeloIndisponivel("o modelo baixado veio pela metade")
    _cache.escrever_atomico(alvo, dados)
    return alvo


def sessao():
    """A sessão do onnxruntime, uma por processo.

    ⚠️ Carregar o modelo custa décimos de segundo e memória; uma sessão por quadro faria
    a vetorização de um acervo parecer travamento.
    """
    global _sessao
    if _sessao is not None:
        return _sessao
    try:
        import onnxruntime as ort
    except ImportError as e:                                   # pragma: no cover
        raise ModeloIndisponivel("o onnxruntime não está instalado") from e

    caminho = baixar_o_modelo()
    _sessao = ort.InferenceSession(str(caminho), providers=["CPUExecutionProvider"])
    return _sessao


def _rgb_do_jpeg(jpeg: bytes):
    """JPEG → `numpy` de forma `(3, LADO, LADO)`, já normalizado.

    ⛔ Sem Pillow: o ffmpeg decodifica, redimensiona e entrega **RGB cru**, que o numpy lê
    direto do buffer. Uma dependência a menos para o PyInstaller empacotar.
    """
    import numpy as np

    ffmpeg = _frames.achar_ffmpeg()
    comando = [
        ffmpeg, "-v", "error",
        "-f", "image2pipe", "-i", "pipe:0",
        "-vf", f"scale={LADO}:{LADO}",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]
    r = subprocess.run(comando, input=jpeg, capture_output=True, timeout=60)
    esperado = LADO * LADO * 3
    if r.returncode != 0 or len(r.stdout) < esperado:
        raise ModeloIndisponivel("não consegui decodificar o quadro para o modelo")

    bruto = np.frombuffer(r.stdout[:esperado], dtype=np.uint8)
    a = bruto.reshape(LADO, LADO, 3).transpose(2, 0, 1).astype(np.float32) / 255.0
    media = np.array(_MEDIA, dtype=np.float32).reshape(3, 1, 1)
    desvio = np.array(_DESVIO, dtype=np.float32).reshape(3, 1, 1)
    return (a - media) / desvio


def de_jpeg(jpeg: bytes):
    """O vetor de UM quadro, normalizado para que o produto escalar seja a parecença."""
    import numpy as np

    s = sessao()
    entrada = s.get_inputs()[0].name
    saida = s.get_outputs()[0].name
    a = _rgb_do_jpeg(jpeg)
    v = s.run([saida], {entrada: a[None, ...]})[0].flatten().astype("float32")
    return v / (float(np.linalg.norm(v)) + 1e-9)


# ── o que fica em disco ──────────────────────────────────────────────────────


def _npy(midia: _cache.Midia) -> Path:
    # ⚠️ `arquivo`, e não `pasta`: perguntar se há vetor não pode fazer a pasta nascer.
    return midia.arquivo("vetores.npy")


def _posicoes(midia: _cache.Midia) -> Path:
    return midia.arquivo("vetores.json")


def tem(midia: _cache.Midia) -> bool:
    try:
        return _npy(midia).is_file() and _npy(midia).stat().st_size > 0
    except OSError:
        return False


def quantos(midia: _cache.Midia) -> int:
    """Quantos quadros foram vetorizados. ⭐ Lê só o JSON das posições — a tabela da aba
    percorre o cache inteiro e não pode carregar numpy nem abrir um `.npy` por linha."""
    try:
        if not tem(midia):
            return 0
        dados = json.loads(_posicoes(midia).read_text(encoding="utf-8"))
        return len(dados.get("posicoes") or [])
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return 0


def ler(midia: _cache.Midia):
    """`(matriz N×D, posições)` do que está guardado. `(None, [])` quando não há.

    ⚠️ Leitura defensiva, como todo o resto do cache: `.npy` truncado por queda no meio da
    escrita vira "não tenho isto", nunca exceção.
    """
    import numpy as np

    try:
        if not tem(midia):
            return None, []
        matriz = np.load(_npy(midia))
        dados = json.loads(_posicoes(midia).read_text(encoding="utf-8"))
        posicoes = dados.get("posicoes") or []
        if len(posicoes) != len(matriz):
            log.warning("vetores e posições discordam em %s; ignorando", midia.chave)
            return None, []
        return matriz, posicoes
    except (OSError, ValueError, json.JSONDecodeError) as e:
        log.warning("vetores ilegíveis em %s (%s)", midia.chave, e)
        return None, []


def guardar(midia: _cache.Midia, matriz, posicoes: list[int]) -> None:
    import io

    import numpy as np

    buffer = io.BytesIO()
    np.save(buffer, np.asarray(matriz, dtype="float32"))
    _cache.escrever_atomico(midia.pasta / "vetores.npy", buffer.getvalue())
    _cache.escrever_atomico(
        midia.pasta / "vetores.json",
        json.dumps({"posicoes": list(posicoes)}, ensure_ascii=False).encode("utf-8"),
    )


# ── vetorizar um master ──────────────────────────────────────────────────────


def vetorizar_master(
    midia: _cache.Midia,
    video: str,
    taxa: Fraction,
    duracao_frames: int,
    nome: str = "",
    aviso: Callable[[str, float | None, str], None] | None = None,
    forcar: bool = False,
) -> dict[str, Any]:
    """Amostra o master, extrai os quadros e guarda um vetor por quadro.

    ⭐ Os quadros são numerados em tempo do MASTER e ficam no cache de quadros — o mesmo
    que a conversa usa. Vetorizar deixa o material pronto para a busca **e** adianta a
    imagem para quem perguntar depois.
    """
    import numpy as np

    from . import estagios as _estagios

    receita = _estagios.assinatura(_estagios.VETORES)
    if tem(midia) and not midia.precisa_refazer(_estagios.VETORES, receita) \
            and not forcar:
        matriz, posicoes = ler(midia)
        if matriz is not None:
            return {"quantos": len(posicoes), "do_cache": True}

    posicoes = _frames.distribuir(0, max(1, duracao_frames), QUANTOS)
    if not posicoes:
        raise ModeloIndisponivel("essa mídia não tem duração para amostrar")

    faltam = [p for p in posicoes if not midia.tem_quadro(p)]
    try:
        novos = _frames.extrair_varios(video, faltam, taxa) if faltam else {}
    except (OSError, RuntimeError) as e:
        log.warning("não consegui extrair os quadros de %s (%s)", nome or midia.chave, e)
        novos = {}

    vetores = []
    guardados = []
    for i, posicao in enumerate(posicoes):
        if aviso:
            aviso("olhando", i / len(posicoes), nome)
        try:
            if midia.tem_quadro(posicao):
                jpeg = midia.caminho_do_quadro(posicao).read_bytes()
            else:
                jpeg = novos.get(posicao) or _frames.extrair(video, posicao, taxa)
                midia.guardar_quadro(posicao, jpeg)
            vetores.append(de_jpeg(jpeg))
            guardados.append(posicao)
        except (OSError, RuntimeError) as e:
            # ⚠️ Um quadro que não sai não invalida o master: material do Avid tem trecho
            #    ilegível, e onze vetores servem tão bem quanto doze.
            log.warning("não consegui vetorizar %s@%d (%s)", nome or midia.chave,
                        posicao, e)

    if not vetores:
        raise ModeloIndisponivel("não consegui extrair nenhum quadro dessa mídia")

    guardar(midia, np.vstack(vetores), guardados)
    midia.registrar_gerador(_estagios.VETORES, receita)
    if nome:
        midia.anotar_fonte({"master": nome, "arquivo": str(video)})
    return {"quantos": len(guardados), "do_cache": False}


# ── a busca ──────────────────────────────────────────────────────────────────


#: ⭐⭐ Quantos PLANOS da mesma mídia podem aparecer na resposta (F4 da micro).
#:
#: A regra antiga era UMA linha por mídia, e ela existe por um motivo bom: doze quadros
#: vizinhos do mesmo plano tomariam a lista inteira. ⚠️ Mas numa peça MONTADA os planos são
#: conteúdos diferentes — devolver só o melhor esconde os outros cinco momentos parecidos da
#: mesma peça, que é justamente o que o editor procura num arquivo.
PLANOS_POR_MIDIA = 3


def _por_plano(midia: _cache.Midia, posicoes: list[int]) -> dict[int, int] | None:
    """Para cada posição, a que TRECHO (plano) ela pertence — ou `None` sem `cortes.json`.

    ⚠️ Import tardio: `cortes` importa `cache`, e no topo os dois se cruzariam na partida.
    """
    from . import cortes as _cortes

    dados = _cortes.ler(midia)
    if not dados:
        return None
    # ⚠️ Os limites são os do PLANO, não os do trecho: num montado, um trecho junta até 8
    #    planos (o agrupamento que a micro faz para o modelo), e agrupar por trecho diria
    #    "plano 5 de 11" numa peça de 73 planos.
    limites = []
    for t in dados.get("trechos") or []:
        inicios = list(t.get("planos") or [t["inicio"]])
        for a, b in zip(inicios, [*inicios[1:], t["fim"]]):
            if b > a:
                limites.append((a, b))
    if len(limites) < 2:
        return None
    saida = {}
    for p in posicoes:
        for i, (a, b) in enumerate(limites):
            if a <= p < b:
                saida[p] = i
                break
    return saida or None


def vetorizar_planos(midia: _cache.Midia, video: str, taxa: Fraction,
                     trechos: list[dict[str, Any]], nome: str = "",
                     teto: int = 400) -> dict[str, Any]:
    """⭐ Um vetor por PLANO, ACRESCENTADO aos que já existem.

    ⛔⛔ Acrescentar, e não refazer: a receita (`ASSINATURA`) fica igual de propósito —
    mudá-la invalidaria os vetores de TODO o cache (332 mídias × ~1,6 s), para um ganho que
    só existe em material montado. Quem já tem os 12 quadros espalhados continua com eles.

    ⚠️ O quadro de cada plano é o do MEIO dele (`frames.distribuir` com 1), que é a mesma
    escolha do representativo do plano no resto da casa.
    """
    import numpy as np

    if not trechos:
        return {"acrescentados": 0}
    matriz, posicoes = ler(midia)
    tinha = list(posicoes or [])
    alvos = []
    for t in trechos:
        for plano_ini, plano_fim in zip(t.get("planos") or [t["inicio"]],
                                        [*(t.get("planos") or [])[1:], t["fim"]]):
            meio = (plano_ini + plano_fim) // 2
            # ⚠️ Perto de um quadro que já tem vetor não acrescenta nada: o objetivo é
            #   cobrir os planos que ninguém amostrou.
            if all(abs(meio - p) > 6 for p in tinha) and all(abs(meio - a) > 6 for a in alvos):
                alvos.append(meio)
    # ⚠️ O teto existe (uma peça longa tem centenas de planos), mas ele é DITO: cortar
    #   calado deixaria o fim de uma peça sem vetor nenhum, e a busca responderia "não há
    #   nada parecido" sobre material que ninguém indexou. ⛔ E o corte é do FIM em ordem
    #   de tempo, então é sempre o fim da peça que fica de fora — quem for elevar o teto
    #   precisa saber disso.
    alvos = sorted(alvos)
    cortados = max(0, len(alvos) - teto)
    alvos = alvos[:teto]
    if cortados:
        log.warning("vetores por plano em %s: %d plano(s) acima do teto de %d ficaram sem "
                    "vetor (o FIM da peça)", nome or midia.chave[:12], cortados, teto)
    if not alvos:
        return {"acrescentados": 0, "cortados": cortados}

    faltam = [p for p in alvos if not midia.tem_quadro(p)]
    try:
        novos = _frames.extrair_varios(video, faltam, taxa) if faltam else {}
    except (OSError, RuntimeError) as e:
        log.warning("não consegui extrair quadros de plano de %s (%s)", nome, e)
        novos = {}
    vetores, guardados = [], []
    for p in alvos:
        jpeg = (midia.caminho_do_quadro(p).read_bytes() if midia.tem_quadro(p)
                else novos.get(p))
        if not jpeg:
            continue
        if not midia.tem_quadro(p):
            midia.guardar_quadro(p, jpeg)
        try:
            vetores.append(de_jpeg(jpeg))
        except (ModeloIndisponivel, OSError, ValueError) as e:
            log.warning("vetor do plano %d de %s falhou (%s)", p, nome, e)
            continue
        guardados.append(p)
    if not guardados:
        return {"acrescentados": 0, "cortados": cortados}
    junto = np.asarray(vetores, dtype="float32")
    if matriz is not None and len(tinha):
        junto = np.concatenate([matriz, junto], axis=0)
        guardados = [*tinha, *guardados]
    ordem = sorted(range(len(guardados)), key=lambda i: guardados[i])
    guardar(midia, junto[ordem], [guardados[i] for i in ordem])
    log.info("vetores por plano em %s: +%d (total %d)", nome or midia.chave[:12],
             len(vetores), len(guardados))
    return {"acrescentados": len(vetores), "total": len(guardados), "cortados": cortados}


def procurar(alvo, limite: int = 8, exceto: str = "",
             raiz: Path | None = None,
             chaves: "frozenset[str] | set[str] | None" = None,
             exceto_frame: int | None = None) -> list[dict[str, Any]]:
    """Os quadros mais parecidos com `alvo` em todo o cache.

    `alvo` é um vetor já normalizado (de `de_jpeg`). `exceto` é uma chave a ignorar —
    ⭐ e ela importa: procurar "parecido com este plano" trazendo o próprio plano de volta
    é o erro que o spike cometeu na primeira versão, e que fazia qualquer motor acertar
    100%. Quem pergunta quer saber ONDE MAIS existe algo assim.

    `chaves` estreita a busca a esses masters — ⭐ o escopo do projeto aberto
    (`avid/escopo.py`). `None` é **sem filtro**, e não "nenhum": o índice é global de
    propósito; quem recorta é quem chama.

    ⚠️ Varre o cache inteiro em memória. Com 358 mídias × 12 quadros são 4.296 vetores de
    1.000 floats — 17 MB e uns milissegundos. Se um dia o acervo for dez vezes maior, é
    aqui que entra um índice; até lá, índice seria complexidade sem medida que a peça.
    """
    import numpy as np

    achados: list[dict[str, Any]] = []
    for midia in _cache.todas(raiz):
        so_o_plano = None
        if midia.chave == exceto:
            # ⭐⭐ Em material MONTADO, excluir a peça inteira esconde o que o editor está
            #   perguntando ("onde MAIS nesta peça?"). Sai só o PLANO de origem — e só
            #   quando dá para saber qual é (há planos detectados e o quadro de origem).
            planos_da_fonte = (_por_plano(midia, list(ler(midia)[1] or []))
                               if exceto_frame is not None else None)
            if not planos_da_fonte:
                continue
            so_o_plano = min(planos_da_fonte.items(),
                             key=lambda kv: abs(kv[0] - int(exceto_frame)))[1]
        if chaves is not None and midia.chave not in chaves:
            continue
        matriz, posicoes = ler(midia)
        if matriz is None:
            continue
        parecencas = matriz @ np.asarray(alvo, dtype="float32")
        # ⭐ UMA linha por mídia, a do melhor quadro — senão os doze quadros de um plano
        #   tomam a lista inteira e o editor vê um resultado só, doze vezes.
        # ⭐⭐ Mas quando a mídia tem PLANOS detectados (material montado), cada plano é
        #   outro conteúdo: sai o melhor quadro de cada um, até `PLANOS_POR_MIDIA`.
        planos = _por_plano(midia, list(posicoes))
        if planos:
            melhor_do_plano: dict[int, int] = {}
            for i, p in enumerate(posicoes):
                plano = planos.get(p)
                if plano is None or plano == so_o_plano:
                    continue
                if plano not in melhor_do_plano or parecencas[i] > parecencas[melhor_do_plano[plano]]:
                    melhor_do_plano[plano] = i
            escolhidos = sorted(melhor_do_plano.values(),
                                key=lambda i: -float(parecencas[i]))[:PLANOS_POR_MIDIA]
        else:
            escolhidos = [int(np.argmax(parecencas))]
        if not escolhidos:
            continue
        for i in escolhidos:
            achados.append({
                "chave": midia.chave,
                "nome": midia.nome,
                "frame_no_master": posicoes[i],
                "parecenca": round(float(parecencas[i]), 4),
                **({"plano": planos[posicoes[i]] + 1, "de_planos": len(set(planos.values()))}
                   if planos else {}),
            })

    achados.sort(key=lambda a: a["parecenca"], reverse=True)
    return achados[:limite]
