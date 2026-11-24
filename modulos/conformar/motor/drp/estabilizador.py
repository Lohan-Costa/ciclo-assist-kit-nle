"""O Stabilize do Avid DENTRO do estabilizador do Resolve, depois do import — o gêmeo das LUTs (`drp/luts.py`).

Pedido do autor (2026-10-24): a estabilização chega PRONTA e LIGADA, sem keyframe no Transform (a regra de 2026-10-10
para o Warp Stabilizer do Premiere). O caminho, por clipe do relatório (`relatorio["estabilizar"]`, escrito pelo
`drp/writer.py`):

1. `TimelineItem.Stabilize()` — cria no `Body` da grade a estrutura do estabilizador (uma entrada por quadro);
2. a timeline exportada em DRT (uma vez, todos os clipes): o `Body` de cada um, sem a Gallery;
3. em cada quadro, o bloco **`0x10300015`** (a correção APLICADA: palavra 10 = 1 ÷ zoom, 11–19 = matriz 3×3) recebe a
   correção do Avid — uma translação de `u` × o tamanho da ANÁLISE (cabeçalho do bloco: 1280 × 720 num 1080p);
4. um `.drx` mínimo com esse `Body` → `Graph.ApplyGradeFromDRX` (no 21 o método saiu da Timeline para o Graph do
   clipe; no 19 é `Timeline.ApplyGradeFromDRX(drx, 0, [itens])`).

MEDIDO no Resolve Studio 21.1 (Mac, 2026-10-24, projeto "DLPC LAB ESTAB 21", lab B19 com tremor CONHECIDO) contra o
render do próprio Media Composer (`B19_MC_ESTAB_100.mxf`): correlação **0,999**, resíduo ≤ 0,2 px, também num clipe
APARADO (as entradas do estabilizador contam pelo quadro da MÍDIA × 2, não pelo do clipe). O estabilizador próprio do
Resolve deu 0,90–0,96 nos mesmos quadros. Banco `protocolos/drt-drp/estruturas.md` §ESTABILIZADOR.
⏳ Se o Resolve REESCREVE o `0x10300015` quando o colorista mexe na força/no modo do estabilizador (a UI, com o autor).

Clipe OFFLINE (autor, 2026-10-24: "reaplicar mesmo assim; a correção é um valor frio"): o `Stabilize()` precisa da
imagem, então a estrutura sai do MOLDE (`estabilizador_r21.bin`: o `Body` real do `Stabilize()` do E07 aparado, com UMA
entrada e as matrizes em identidade) — uma entrada por quadro da mídia do clipe, a correção do Avid injetada como no
clipe online. Só a 1920 × 1080 (a única timeline medida: o cabeçalho do `Body` e o tamanho da análise dependem dela).
"""
from __future__ import annotations

from .writer import ler_in as _ler_in  # noqa: E402 — o In com fração (`291|f64`)
import copy
import os
import re
import struct
import uuid
import zipfile

import zstandard

from tools.inspect_drp import pb_decode, pb_encode

#: O bloco da correção aplicada (80 bytes) e o resto da entrada de um quadro (banco, §ESTABILIZADOR).
CORRECAO = 0x10300015
#: O `Body` do molde (Resolve 21.1, 1920 × 1080): o esqueleto do `Stabilize()` com uma entrada-modelo.
MOLDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estabilizador_r21.bin")
_ITEM = re.compile(r"<Element>\s*<Sm2TiVideoClip DbId=\"[^\"]+\">(.*?)</Sm2TiVideoClip>\s*</Element>", re.S)


def _dec(hexa: str) -> bytes | None:
    b = bytes.fromhex(hexa)
    if not b or b[0] != 0x81:
        return None
    return zstandard.ZstdDecompressor().decompress(b[1:], max_output_size=1 << 28)


def corpos_do_drt(drt: str) -> dict[tuple[int, int], tuple[str, int, str]]:
    """`{(trilha de vídeo, Start absoluto): (nome, In na mídia, Body hex)}` dos clipes de vídeo do DRT exportado — o
    `Body` da versão de grade (o 1º `LmVersion` do clipe com o estabilizador)."""
    from drp.reescrever import _campo, _seq, _trilhas

    with zipfile.ZipFile(drt) as z:
        s = z.read(_seq(z)).decode("utf-8")
    fora = {}
    for letra, n, a, b in _trilhas(s):
        if letra != "V":
            continue
        for m in _ITEM.finditer(s, a, b):
            corpo = m.group(1)
            for hexa in re.findall(r"<Body>([0-9a-f]+)</Body>", corpo):
                d = _dec(hexa)
                if d is not None and _entradas(pb_decode(d)):
                    fora[(n, int(_campo(corpo, "Start") or 0))] = (_campo(corpo, "Name"),
                                                                   int(_ler_in(_campo(corpo, "In"))), hexa)
                    break
    return fora


def _filhos(fs: list, campo: int) -> list:
    return [f["value"] for f in fs if f["field"] == campo and isinstance(f["value"], list)]


def _entradas(fs: list) -> list:
    """As entradas por quadro do estabilizador no nó: `3 → 9 → 1 → 6 → 2 → 4 → 1*` (o mesmo no 19 e no 21)."""
    fora = []
    for a in _filhos(fs, 3):
        for b in _filhos(a, 9):
            for c in _filhos(b, 1):
                for d in _filhos(c, 6):
                    for e in _filhos(d, 2):
                        for lista in _filhos(e, 4):
                            fora += _filhos(lista, 1)
    return fora


def injetar(body: bytes, u: list, zoom: float, fonte_in: int, deslocamento: int) -> tuple[bytes, int]:
    """O `Body` (descomprimido) com a correção do Avid em cada quadro → (Body novo, quadros trocados).

    `u[k]` = a correção do quadro k do segmento do Avid, em fração do quadro; a entrada do Resolve diz o quadro da
    MÍDIA × 2, e o quadro k = mídia − `fonte_in` + `deslocamento` (o clipe que a transição estendeu para trás começa
    antes do segmento). Fora do segmento vale a ponta (como a borda "nearest" da conta do Avid)."""
    fs = pb_decode(body)
    trocados = 0
    for e in _entradas(fs):
        q = next((x["value"] for x in e if x["field"] == 1 and x["wire"] == 0), 0)
        for p in _filhos(e, 2):
            if next((x["value"] for x in p if x["field"] == 1 and x["wire"] == 0), None) != CORRECAO:
                continue
            for v in _filhos(p, 2):
                bloco = next((x for x in v if x["field"] == 5 and x["wire"] == 2 and isinstance(x["value"], (bytes, bytearray))
                              and len(x["value"]) == 80), None)
                if bloco is None:
                    continue
                largura, altura = struct.unpack_from(">I", bloco["value"], 12)[0], struct.unpack_from(
                    ">I", bloco["value"], 20)[0]
                if not (16 <= largura <= 16384 and 16 <= altura <= 16384):
                    largura, altura = 1280, 720            # o medido (1080p: 1280 × 720)
                k = min(len(u) - 1, max(0, q // 2 - fonte_in + deslocamento))
                ux, uy = u[k]
                bloco["value"] = bloco["value"][:40] + struct.pack(
                    "<10f", 1.0 / zoom, 1, 0, ux * largura, 0, 1, uy * altura, 0, 0, 1)
                trocados += 1
    return pb_encode(fs), trocados


def _listas(fs: list) -> list:
    """As listas de entradas do nó (o caminho de `_entradas`, sem descer nas entradas)."""
    return [lista for a in _filhos(fs, 3) for b in _filhos(a, 9) for c in _filhos(b, 1) for d in _filhos(c, 6)
            for e in _filhos(d, 2) for lista in _filhos(e, 4)]


def corpo_do_molde(fonte_in: int, quadros: int) -> bytes:
    """O `Body` de um clipe que o Resolve não pôde analisar (offline): o molde com uma entrada por quadro da mídia, de
    `fonte_in` a `fonte_in + quadros − 1` (o campo 1 = quadro × 2; o quadro 0 vem sem o campo, como no `Stabilize()`).
    A correção fica em identidade — o `injetar` a preenche."""
    with open(MOLDE, "rb") as f:
        fs = pb_decode(f.read())
    for lista in _listas(fs):
        modelo = next(x for x in lista if x["field"] == 1)
        resto = [x for x in lista if x["field"] != 1]
        novas = []
        for m in range(max(0, int(fonte_in)), max(0, int(fonte_in)) + max(1, int(quadros))):
            e = copy.deepcopy(modelo)
            e["value"] = [x for x in e["value"] if not (x["field"] == 1 and x["wire"] == 0)]
            if m:
                e["value"].insert(0, {"field": 1, "wire": 0, "value": 2 * m})
            novas.append(e)
        lista[:] = resto + novas
    return bytes(pb_encode(fs))


def drx(body: bytes) -> str:
    """O `.drx` MÍNIMO (só a versão da grade do clipe, sem a miniatura): o `ApplyGradeFromDRX` do 21 o aceita (medido)."""
    blob = (b"\x81" + zstandard.ZstdCompressor().compress(body)).hex()
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Gallery::GyStill DbId="{uuid.uuid4()}">\n <pClipFullVer>\n'
            f'  <ListMgt::LmVersion DbId="{uuid.uuid4()}">\n   <FieldsBlob/>\n   <Name/>\n'
            '   <HasCorrection>false</HasCorrection>\n   <VerType>0</VerType>\n   <ImplVersion>1</ImplVersion>\n'
            f'   <Body>{blob}</Body>\n  </ListMgt::LmVersion>\n </pClipFullVer>\n</Gallery::GyStill>\n')


def _plano_valido(x: dict) -> bool:
    u = x.get("u")
    return (isinstance(x.get("trilha"), int) and 1 <= x["trilha"] <= 999 and isinstance(x.get("quadro"), int)
            and isinstance(x.get("inicio"), int) and isinstance(x.get("arquivo"), str)
            and isinstance(x.get("zoom"), (int, float)) and 0.1 <= x["zoom"] <= 10
            and isinstance(u, list) and 0 < len(u) <= 20_000
            and all(isinstance(p, list) and len(p) == 2 and all(isinstance(c, (int, float)) and abs(c) < 1 for c in p)
                    for p in u))


def aplicar_estabilizacao(resolve, timeline, relatorio: dict, pasta: str) -> list[dict]:
    """Cada entrada de `relatorio["estabilizar"]` ({trilha, quadro, arquivo, inicio, zoom, u}) no estabilizador do
    clipe achado pela trilha, pelo quadro (desde o início da timeline) e pelo nome. `pasta`: onde ficam o DRT exportado
    e os `.drx` (descartáveis). Um clipe que falha é registrado e os outros seguem."""
    inicio = timeline.GetStartFrame()
    fora, alvos = [], []
    for x in relatorio.get("estabilizar") or []:
        base = {k: x.get(k) for k in ("trilha", "quadro", "arquivo")}
        if not _plano_valido(x):
            fora.append({**base, "ok": False, "erro": "pedido inválido"})
            continue
        item = next((it for it in timeline.GetItemListInTrack("video", x["trilha"]) or []
                     if it.GetStart() - inicio == x["quadro"] and it.GetName() == x["arquivo"]), None)
        if item is None:
            fora.append({**base, "ok": False, "erro": "clipe não encontrado na timeline"})
        elif item.Stabilize():
            alvos.append((x, base, item))
        else:
            fora.append(_pelo_molde(timeline, item, x, base, pasta))
    if not alvos:
        return fora
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, "estabilizar.drt")
    # ⚠️ o Export leva a timeline ABERTA na tela (banco, api-scripting): ela primeiro
    resolve.GetProjectManager().GetCurrentProject().SetCurrentTimeline(timeline)
    if not timeline.Export(arq, getattr(resolve, "EXPORT_DRT", 1)) or not os.path.isfile(arq):
        return fora + [{**b, "ok": False, "erro": "não consegui exportar a timeline para ler a análise"}
                       for _x, b, _i in alvos]
    corpos = corpos_do_drt(arq)
    for x, base, item in alvos:
        achado = corpos.get((x["trilha"], item.GetStart()))
        if not achado or achado[0] != x["arquivo"]:
            fora.append({**base, "ok": False, "erro": "a análise do clipe não veio no DRT exportado"})
            continue
        _nome, fonte_in, hexa = achado
        try:
            novo, n = injetar(_dec(hexa), x["u"], float(x["zoom"]), fonte_in, x["quadro"] - x["inicio"])
        except Exception as e:  # noqa: BLE001 — um Body que não se entende não derruba os outros
            fora.append({**base, "ok": False, "erro": f"a análise do Resolve veio diferente ({type(e).__name__})"})
            continue
        if not n:
            fora.append({**base, "ok": False, "erro": "a análise do Resolve veio sem os quadros"})
            continue
        caminho = os.path.join(pasta, f"estab_{x['trilha']}_{x['quadro']}.drx")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(drx(novo))
        ok = _aplicar_drx(timeline, item, caminho)
        fora.append({**base, "ok": ok, **({"quadros": n} if ok else {"erro": "o Resolve não aceitou a estabilização"})})
    return fora


def _pelo_molde(timeline, item, x: dict, base: dict, pasta: str) -> dict:
    """O clipe que o `Stabilize()` recusou (a mídia offline): a estrutura do molde, a mesma injeção e o mesmo `.drx`."""
    largura = str(timeline.GetSetting("timelineResolutionWidth") or "")
    altura = str(timeline.GetSetting("timelineResolutionHeight") or "")
    if (largura, altura) != ("1920", "1080"):
        return {**base, "ok": False, "erro": f"mídia offline numa timeline {largura}×{altura}: "
                                             "só a 1920×1080 tem o molde medido"}
    try:
        fonte_in = int(item.GetLeftOffset())
        novo, n = injetar(corpo_do_molde(fonte_in, int(item.GetDuration())), x["u"], float(x["zoom"]), fonte_in,
                          x["quadro"] - x["inicio"])
    except Exception as e:  # noqa: BLE001
        return {**base, "ok": False, "erro": f"o molde do estabilizador falhou ({type(e).__name__})"}
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"estab_{x['trilha']}_{x['quadro']}_molde.drx")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(drx(novo))
    ok = _aplicar_drx(timeline, item, caminho)
    return {**base, "ok": ok, "molde": True,
            **({"quadros": n} if ok else {"erro": "o Resolve não aceitou a estabilização (mídia offline)"})}


def _metodo(obj, nome: str):
    """⚠️ No objeto da API, `hasattr` é sempre True (MEDIDO no 21: `Timeline.ApplyGradeFromDRX` "existe" e vale None)."""
    m = getattr(obj, nome, None) if obj is not None else None
    return m if callable(m) else None


def _aplicar_drx(timeline, item, caminho: str) -> bool:
    """A grade do `.drx` no clipe: `Graph.ApplyGradeFromDRX` (21) ou `Timeline.ApplyGradeFromDRX` (19)."""
    pegar = _metodo(item, "GetNodeGraph")
    aplicar = _metodo(pegar() if pegar else None, "ApplyGradeFromDRX")
    if aplicar and aplicar(caminho, 0):
        return True
    aplicar = _metodo(timeline, "ApplyGradeFromDRX")
    return bool(aplicar and aplicar(caminho, 0, [item]))
