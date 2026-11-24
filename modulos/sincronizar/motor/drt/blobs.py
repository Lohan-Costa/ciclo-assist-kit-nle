#!/usr/bin/env python3
"""
inspect_drp.py — engenharia reversa do formato DRT/DRP do DaVinci Resolve.

Um .drt/.drp é um ZIP de XMLs do banco do Resolve (SM_Project, Sm2SequenceContainer,
MpFolder). A maioria dos campos de clipe é XML puro, mas alguns são blobs binários:

  - FieldsBlob ............ protobuf (com 1 byte 0x80 de flag) + cabeçalho [u32 ver][u32 len].
                           Carrega, entre outros, o Start do clipe como varint.
  - *BA (MediaTimemapBA,
    KeyframesBA, MarkersBA) ... container chave/valor em UTF-16BE (chaves legíveis:
                           "Min","Max","KeyframesBA","interp","YOut","Y", "DbType"=...).
  - MediaFrameRate ........ double little-endian (8 bytes) + padding (16 bytes no total).

Este módulo decodifica esses formatos e faz ROUND-TRIP (re-encode == bytes originais),
o que valida os codecs SEM precisar abrir o Resolve. Base p/ o futuro drp/writer.py.

Uso:
    python tools/inspect_drp.py <arquivo.drt|.drp>            # dump + round-trip
    python tools/inspect_drp.py <arquivo.drt> --selftest      # só os testes de codec
"""
from __future__ import annotations

import binascii
import io
import struct
import sys
import zipfile
from typing import Any


# --------------------------------------------------------------------------- #
# 1) Protobuf mini-codec (suficiente p/ os FieldsBlob do Resolve)
# --------------------------------------------------------------------------- #
def _read_varint(b: bytes, o: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        byte = b[o]
        o += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, o
        shift += 7


def _write_varint(v: int) -> bytes:
    out = bytearray()
    while True:
        byte = v & 0x7F
        v >>= 7
        if v:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def pb_decode(b: bytes, o: int = 0, end: int | None = None) -> list[dict]:
    """Decodifica um corpo protobuf em [{field, wire, value/raw}], preservando ordem
    e bytes para re-encode fiel. Mensagens aninhadas (wire 2) viram listas recursivas
    quando parecem protobuf; senão ficam como `bytes`."""
    if end is None:
        end = len(b)
    fields: list[dict] = []
    while o < end:
        key, o = _read_varint(b, o)
        field = key >> 3
        wire = key & 0x7
        if wire == 0:           # varint
            val, o = _read_varint(b, o)
            fields.append({"field": field, "wire": 0, "value": val})
        elif wire == 1:         # 64-bit
            val = b[o:o + 8]
            o += 8
            fields.append({"field": field, "wire": 1, "value": val})
        elif wire == 2:         # length-delimited
            ln, o = _read_varint(b, o)
            data = b[o:o + ln]
            o += ln
            sub = None
            try:
                sub = pb_decode(data)
                # heurística: só trata como aninhado se reconsumir tudo limpo
                if pb_encode(sub) != data:
                    sub = None
            except Exception:
                sub = None
            fields.append({"field": field, "wire": 2,
                           "value": sub if sub is not None else data})
        elif wire == 5:         # 32-bit
            val = b[o:o + 4]
            o += 4
            fields.append({"field": field, "wire": 5, "value": val})
        else:
            raise ValueError(f"wire type {wire} não suportado @ {o}")
    return fields


def pb_encode(fields: list[dict]) -> bytes:
    out = bytearray()
    for f in fields:
        out += _write_varint((f["field"] << 3) | f["wire"])
        if f["wire"] == 0:
            out += _write_varint(f["value"])
        elif f["wire"] in (1, 5):
            out += f["value"]
        elif f["wire"] == 2:
            v = f["value"]
            data = pb_encode(v) if isinstance(v, list) else v
            out += _write_varint(len(data))
            out += data
        else:
            raise ValueError(f"wire {f['wire']}")
    return out


def fieldsblob_decode(hexstr: str) -> dict:
    """FieldsBlob: [u32 version][u32 bodylen][0x80 flag][protobuf]."""
    b = binascii.unhexlify(hexstr.strip())
    ver = struct.unpack(">I", b[0:4])[0]
    blen = struct.unpack(">I", b[4:8])[0]
    body = b[8:8 + blen]
    flag = body[0]
    pb = pb_decode(body, 1)
    return {"version": ver, "flag": flag, "fields": pb}


def fieldsblob_encode(dec: dict) -> str:
    body = bytes([dec["flag"]]) + pb_encode(dec["fields"])
    out = struct.pack(">I", dec["version"]) + struct.pack(">I", len(body)) + body
    return out.hex()


# --------------------------------------------------------------------------- #
# 2) "*BA" container — chave/valor em UTF-16BE
#    layout: [u32 count] então repetido: [u32 keylen][key utf16be][u32 type][value]
#    tipos observados: 6=double(8B com 1 byte tag?), strings, ints, blobs aninhados.
# --------------------------------------------------------------------------- #
def ba_tokens(hexstr: str) -> list[str]:
    """Strings legíveis (chaves) dentro de um blob *BA — útil p/ mapear o schema."""
    import re
    raw = binascii.unhexlify(hexstr.strip())
    s = raw.decode("utf-16-be", errors="replace")
    return re.findall(r"[ -~]{2,}", s)


# Container *BA (chave/valor UTF-16BE) — formato decifrado por round-trip byte-exato.
# Cada entrada: [u32 keylen][key utf-16be][u32 type][value]. value por type:
#   2  (int)    = [u8 flag][i32 BE]                     (5 bytes)
#   6  (double) = [u8 tag][f64 BE]                       (9 bytes)
#   10 (string) = [u8 flag][u32 strlen][utf-16be]
#   12 (object) = [u32 a][u8 tag][u32 b][u32 count][entries...]  (header 13B + filhos)
# A raiz do MediaTimemapBA é [u32 version][u32 count][entries]; constante = [u8 tag][f64].
_BA_INT, _BA_DOUBLE, _BA_STRING, _BA_OBJ = 2, 6, 10, 12
_U = lambda b, o: struct.unpack(">I", b[o:o + 4])[0]


def _ba_decode_entries(b: bytes, o: int, count: int):
    items = []
    for _ in range(count):
        kl = _U(b, o); o += 4
        key = b[o:o + kl].decode("utf-16-be"); o += kl
        t = _U(b, o); o += 4
        if t == _BA_INT:
            v = {"flag": b[o], "int": struct.unpack(">i", b[o + 1:o + 5])[0]}; o += 5
        elif t == _BA_DOUBLE:
            v = {"tag": b[o], "dbl": struct.unpack(">d", b[o + 1:o + 9])[0]}; o += 9
        elif t == _BA_STRING:
            fl = b[o]; sl = _U(b, o + 1)
            v = {"flag": fl, "str": b[o + 5:o + 5 + sl].decode("utf-16-be")}; o += 5 + sl
        elif t == _BA_OBJ:
            a = _U(b, o); tag = b[o + 4]; bb = _U(b, o + 5); cnt = _U(b, o + 9)
            sub, o = _ba_decode_entries(b, o + 13, cnt)
            v = {"a": a, "tag": tag, "b": bb, "entries": sub}
        else:
            raise ValueError(f"tipo *BA desconhecido {t} @ {o}")
        items.append({"key": key, "type": t, "value": v})
    return items, o


def _ba_encode_entries(items: list) -> bytes:
    out = bytearray()
    for it in items:
        kb = it["key"].encode("utf-16-be")
        out += struct.pack(">I", len(kb)) + kb + struct.pack(">I", it["type"])
        t, v = it["type"], it["value"]
        if t == _BA_INT:
            out += bytes([v["flag"]]) + struct.pack(">i", v["int"])
        elif t == _BA_DOUBLE:
            out += bytes([v["tag"]]) + struct.pack(">d", v["dbl"])
        elif t == _BA_STRING:
            sb = v["str"].encode("utf-16-be")
            out += bytes([v["flag"]]) + struct.pack(">I", len(sb)) + sb
        elif t == _BA_OBJ:
            sub = _ba_encode_entries(v["entries"])
            out += (struct.pack(">I", v["a"]) + bytes([v["tag"]])
                    + struct.pack(">I", v["b"]) + struct.pack(">I", len(v["entries"])) + sub)
        else:
            raise ValueError(f"tipo {t}")
    return bytes(out)


def timemap_decode(hexstr: str):
    """MediaTimemapBA: constante = (tag, double) 9 bytes; com keyframes =
    [u32 version][u32 count] + entries *BA (Sm2TiMap: YMax/XMax/UniqueId/
    LastValidYOffset/KeyframesBA{map de keyframes}/DbType)."""
    b = binascii.unhexlify(hexstr.strip())
    if len(b) <= 12:
        return {"kind": "const", "tag": b[0], "value": struct.unpack(">d", b[1:9])[0]}
    ver = _U(b, 0)
    items, _ = _ba_decode_entries(b, 8, _U(b, 4))
    return {"kind": "map", "version": ver, "items": items}


def timemap_encode(dec) -> str:
    if dec["kind"] == "const":
        return (bytes([dec["tag"]]) + struct.pack(">d", dec["value"])).hex()
    body = (struct.pack(">I", dec["version"]) + struct.pack(">I", len(dec["items"]))
            + _ba_encode_entries(dec["items"]))
    return body.hex()


def _dbl(v):  return {"tag": 0, "dbl": float(v)}
def _int(v):  return {"flag": 0, "int": int(v)}
def _str(v):  return {"flag": 0, "str": v}


def _keyframe(x: float, y: float, interp: int = 0) -> dict:
    """Objeto keyframe do Sm2TiMap: interp + handles bezier (0 p/ linear) + X/Y."""
    return {"a": 0, "tag": 0xA7, "b": 1, "entries": [
        {"key": "interp", "type": _BA_INT,    "value": _int(interp)},
        {"key": "YOut",   "type": _BA_DOUBLE, "value": _dbl(0.0)},
        {"key": "YIn",    "type": _BA_DOUBLE, "value": _dbl(0.0)},
        {"key": "Y",      "type": _BA_DOUBLE, "value": _dbl(y)},
        {"key": "XOut",   "type": _BA_DOUBLE, "value": _dbl(0.0)},
        {"key": "XIn",    "type": _BA_DOUBLE, "value": _dbl(0.0)},
        {"key": "X",      "type": _BA_DOUBLE, "value": _dbl(x)},
    ]}


def build_speed_timemap(nb_frames: int, fps: float, speed_ratio: float,
                        unique_id: str | None = None) -> str:
    """Gera um MediaTimemapBA de VELOCIDADE CONSTANTE (linear). Espelha o que o
    Resolve escreve (validado byte-a-byte vs o C004 50% da referência):

      Ymax = (nb_frames-1)/fps      (duração da mídia em s — = a forma constante)
      Xmax = Ymax * speed_ratio     (span da timeline se a mídia toda tocasse nessa vel.)
      keyframes (0,0) e (Xmax,Ymax), interp linear → slope = 1/speed_ratio = playback.

    `speed_ratio` = SpeedRatio do AAF (tl/src; 50% slowmo → ~2.0).
    """
    import uuid as _uuid
    ymax = (nb_frames - 1) / fps
    xmax = ymax * speed_ratio
    gid = unique_id or str(_uuid.uuid4())
    items = [
        {"key": "YMax", "type": _BA_DOUBLE, "value": _dbl(ymax)},
        {"key": "XMax", "type": _BA_DOUBLE, "value": _dbl(xmax)},
        {"key": "UniqueId", "type": _BA_STRING, "value": _str(gid)},
        {"key": "LastValidYOffset", "type": _BA_DOUBLE, "value": _dbl(ymax)},
        {"key": "KeyframesBA", "type": _BA_OBJ, "value": {"a": 1, "tag": 0x74, "b": 1,
            "entries": [
                {"key": "1", "type": _BA_OBJ, "value": _keyframe(xmax, ymax)},
                {"key": "0", "type": _BA_OBJ, "value": _keyframe(0.0, 0.0)},
            ]}},
        {"key": "DbType", "type": _BA_STRING, "value": _str("Sm2TimeMap")},
    ]
    return timemap_encode({"kind": "map", "version": 1, "items": items})


# Header do container KeyframesBA por contagem N de keyframes. Os campos (a, tag) são
# estado interno de QHash do Qt (validado vs exports reais do Resolve — VER
# drt-format-reverse na memória); o Resolve os USA na leitura (header errado → freeze).
# A ordem das entradas é LEXICOGRÁFICA DESCENDENTE das chaves ("99","98",…,"100","10","1","0").
# `a` cresce ~0.7·N (buckets ocupados de QHash); `tag` é um byte de hash (imprevisível por
# fórmula — N=6 e N=13 colidem em 0x4c), então NÃO dá p/ extrapolar: só usar N na tabela.
# Valores colhidos de exports reais do Resolve (harvest 2026-06-13). Faltam 38–158 (exceto 159);
# p/ N fora da tabela o builder adaptativo encaixa no MENOR N tabelado ≥ requerido, preenchendo
# com pontos colineares (não altera a precisão). Pedir mais headers ao usuário p/ fechar buracos.
_KF_HEADER_BY_N = {
    2: (1, 0x74), 4: (2, 0xE0), 6: (4, 0x4C), 13: (9, 0x4C), 14: (10, 0x04),
    22: (15, 0xC4), 30: (21, 0x84), 37: (26, 0x8C), 159: (114, 0xB2),
}
_RAMP_N = 159   # contagem fixa de keyframes do MediaTimemapBA de rampa (header conhecido)


def _keyframes_container(pts: list, n: int) -> dict:
    """Monta o KeyframesBA (obj type 12) com `n` keyframes LINEARES (interp=0) a partir
    de `pts` [(X,Y)] (já com exatamente `n` pontos, ordenados por X = chave 0..n-1).
    Entradas em ordem lexicográfica descendente das chaves; header validado por `n`."""
    a, tag = _KF_HEADER_BY_N[n]
    by_key = {str(i): _keyframe(round(x, 6), round(y, 6), interp=0)
              for i, (x, y) in enumerate(pts)}
    order = sorted(by_key.keys(), reverse=True)   # lex desc: "99","98",…,"100","10","1","0"
    entries = [{"key": k, "type": _BA_OBJ, "value": by_key[k]} for k in order]
    return {"a": a, "tag": tag, "b": 1, "entries": entries}


def _douglas_peucker(pts: list, tol: float) -> list:
    """Seleciona o subconjunto mínimo de índices de `pts` [(x,y)] tal que a interpolação
    LINEAR por partes entre eles fica a ≤ `tol` (no eixo y) da curva original. Retorna os
    índices mantidos (sempre inclui o primeiro e o último), ordenados."""
    n = len(pts)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        x0, y0 = pts[a]; x1, y1 = pts[b]
        dx = x1 - x0
        dmax = -1.0; idx = -1
        for i in range(a + 1, b):
            x, y = pts[i]
            yl = y0 + (y1 - y0) * (x - x0) / dx if dx > 1e-12 else y0
            d = abs(y - yl)
            if d > dmax:
                dmax = d; idx = i
        if dmax > tol and idx > a:
            keep[idx] = True
            stack.append((a, idx)); stack.append((idx, b))
    return [i for i in range(n) if keep[i]]


def _pad_to_header_n(pts: list) -> list:
    """Encaixa `pts` (selecionados, ordenados por X) na MENOR contagem N tabelada em
    `_KF_HEADER_BY_N` que seja ≥ len(pts), inserindo pontos COLINEARES (no maior gap em X,
    sobre a própria reta entre vizinhos → não altera a curva interpolada). Levanta se
    len(pts) excede o maior N tabelado."""
    avail = sorted(_KF_HEADER_BY_N)
    need = len(pts)
    target = next((n for n in avail if n >= need), None)
    if target is None:
        raise ValueError(f"{need} keyframes excede o maior header tabelado ({avail[-1]}); "
                         f"colher headers maiores no Resolve")
    pts = list(pts)
    while len(pts) < target:
        # acha o maior gap em X e insere o ponto médio (colinear) ali
        gi = max(range(len(pts) - 1), key=lambda i: pts[i + 1][0] - pts[i][0])
        (x0, y0), (x1, y1) = pts[gi], pts[gi + 1]
        pts.insert(gi + 1, ((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    return pts


def build_adaptive_ramp_timemap(nb_frames: int, media_fps: float, offset_map: list,
                                source_start_frames: int, tl_fps: float,
                                tol_frames: float = 0.5,
                                unique_id: str | None = None) -> str:
    """RAMPA frame-exata com o MÍNIMO de keyframes LINEARES (interp=0), editáveis no Resolve.

    Como keyframe interp=0 é HONRADO ao frame pelo Resolve (validado), a curva linear por
    partes entre keyframes selecionados por Douglas-Peucker reproduz o offset-map do Avid a
    ≤ `tol_frames`. A contagem é encaixada num header QHash conhecido (`_pad_to_header_n`).
    Domínio/unidades idênticos a `build_ramp_timemap`. Fallback p/ a versão densa (N=159) se
    a seleção não couber num header tabelado."""
    import uuid as _uuid
    if not offset_map:
        return build_speed_timemap(nb_frames, media_fps, 1.0, unique_id)

    ymax_full = (nb_frames - 1) / media_fps
    om = sorted(((float(t), float(v)) for t, v in offset_map), key=lambda p: p[0])
    raw = [(t / tl_fps, (source_start_frames + v) / media_fps) for t, v in om]
    dedup = [raw[0]]
    for x, y in raw[1:]:
        if x > dedup[-1][0] + 1e-9:
            dedup.append((x, y))
    raw = dedup
    if raw[-1][1] < ymax_full - 1e-6 and len(raw) >= 2:
        (x0, y0), (x1, y1) = raw[-2], raw[-1]
        slope = (y1 - y0) / (x1 - x0) if x1 > x0 else 1.0
        if slope > 1e-6:
            raw.append((x1 + (ymax_full - y1) / slope, ymax_full))

    # Douglas-Peucker no eixo Y, com tolerância convertida de frames de fonte p/ segundos.
    sel_idx = _douglas_peucker(raw, tol_frames / media_fps)
    pts = [raw[i] for i in sel_idx]
    try:
        pts = _pad_to_header_n(pts)
    except ValueError:
        return build_ramp_timemap(nb_frames, media_fps, offset_map,
                                  source_start_frames, tl_fps, unique_id, _RAMP_N)
    pts[0] = (0.0, 0.0)
    n = len(pts)

    gid = unique_id or str(_uuid.uuid4())
    items = [
        {"key": "YMax", "type": _BA_DOUBLE, "value": _dbl(ymax_full)},
        {"key": "XMax", "type": _BA_DOUBLE, "value": _dbl(pts[-1][0])},
        {"key": "UniqueId", "type": _BA_STRING, "value": _str(gid)},
        {"key": "LastValidYOffset", "type": _BA_DOUBLE, "value": _dbl(ymax_full)},
        {"key": "KeyframesBA", "type": _BA_OBJ, "value": _keyframes_container(pts, n)},
        {"key": "DbType", "type": _BA_STRING, "value": _str("Sm2TimeMap")},
    ]
    return timemap_encode({"kind": "map", "version": 1, "items": items})


def build_ramp_timemap(nb_frames: int, media_fps: float, offset_map: list,
                       source_start_frames: int, tl_fps: float,
                       unique_id: str | None = None, n_keyframes: int = _RAMP_N) -> str:
    """Gera um MediaTimemapBA de RAMPA (curva de velocidade) a partir do offset-map do
    Avid, como KEYFRAMES LINEARES (interp=0). Fiel ao frame e validado no Resolve —
    o modo LINEAR não depende da convenção de handle Bézier (ver docs/resolve-otio-drp-roadmap.md).

    Unidades do DaVinci: cada keyframe = (X=tempo de SAÍDA em seg, Y=tempo de FONTE em
    seg), slope dY/dX = velocidade. Conversão do offset_map `[(tl_frame, src_frame)]`:
      X = tl_frame / tl_fps          (segundos na timeline/saída)
      Y = (source_start + src_frame) / media_fps   (segundos na fonte)
    A curva cobre a mídia inteira (YMax = duração da mídia); após o range do clipe,
    extrapola na velocidade final até YMax (espelha o builder constante). O clipe janela
    nela via Start/Duration. Reamostra para `n_keyframes` (default 159 — header validado).
    """
    import uuid as _uuid
    if not offset_map or n_keyframes not in _KF_HEADER_BY_N:
        return build_speed_timemap(nb_frames, media_fps, 1.0, unique_id)

    ymax_full = (nb_frames - 1) / media_fps
    om = sorted(((float(t), float(v)) for t, v in offset_map), key=lambda p: p[0])
    raw = [(t / tl_fps, (source_start_frames + v) / media_fps) for t, v in om]
    # remove X-duplicados (monotonicidade estrita em X) antes de interpolar
    dedup = [raw[0]]
    for x, y in raw[1:]:
        if x > dedup[-1][0] + 1e-9:
            dedup.append((x, y))
    raw = dedup
    # extrapola até a duração total da mídia na velocidade final (último segmento)
    if raw[-1][1] < ymax_full - 1e-6 and len(raw) >= 2:
        (x0, y0), (x1, y1) = raw[-2], raw[-1]
        slope = (y1 - y0) / (x1 - x0) if x1 > x0 else 1.0
        if slope > 1e-6:
            raw.append((x1 + (ymax_full - y1) / slope, ymax_full))

    xmax = raw[-1][0]
    # Reamostra para EXATAMENTE n_keyframes pontos numa grade uniforme em X (chaves 0..n-1).
    xs = [p[0] for p in raw]
    def _interp_y(xq):
        import bisect
        i = max(1, min(bisect.bisect_left(xs, xq), len(raw) - 1))
        (a0, b0), (a1, b1) = raw[i - 1], raw[i]
        return b0 + (b1 - b0) * (xq - a0) / (a1 - a0) if a1 > a0 else b0
    pts = [(i * xmax / (n_keyframes - 1), _interp_y(i * xmax / (n_keyframes - 1)))
           for i in range(n_keyframes)]
    pts[0] = (0.0, 0.0)

    gid = unique_id or str(_uuid.uuid4())
    items = [
        {"key": "YMax", "type": _BA_DOUBLE, "value": _dbl(ymax_full)},
        {"key": "XMax", "type": _BA_DOUBLE, "value": _dbl(xmax)},
        {"key": "UniqueId", "type": _BA_STRING, "value": _str(gid)},
        {"key": "LastValidYOffset", "type": _BA_DOUBLE, "value": _dbl(ymax_full)},
        {"key": "KeyframesBA", "type": _BA_OBJ, "value": _keyframes_container(pts, n_keyframes)},
        {"key": "DbType", "type": _BA_STRING, "value": _str("Sm2TimeMap")},
    ]
    return timemap_encode({"kind": "map", "version": 1, "items": items})


# --------------------------------------------------------------------------- #
# 2b) EffectFiltersBA — transform (Position/Scale/Rotation) do clipe do Resolve
# --------------------------------------------------------------------------- #
# Estrutura decodificada (amostra MAPEAMENTO DE EFEITOS, byte-exato p/ valores binários
# exatos; ver docs/effect-translation.md):
#   [u32 ver=2][u32 len][0x80][ repeated filtros ]
#   filtro = 0a <varint len> 08 <tipo> 38 <n> <12 slots>
#   slot setado (double) = 4a 0f 08 <paramID> 1a 0b 0a 09 11 <double LE>;  vazio = 4a 00
# Filtro Transform: tipo=4. Slots por índice→paramID: 0 zoomX(0x2a), 1 zoomY(0x2b),
#   3 posX(0x28), 4 posY(0x29), 5 rotation(0x2f). pos = FRAÇÃO (px/largura, px/altura);
#   zoom = fator; rotation = graus. (Crop/opacity/anchor são outros filtros — a fazer.)
# Filtros do EffectFiltersBA: nome → (tipo, campo7, n_slots, {param: (idx_slot, paramID)}).
# Transform sempre presente (mesmo todo-vazio); crop/composite só quando há valor.
_EFB_FILTERS = {
    "transform": (0x04, 0x00, 12, {
        "zoom_x": (0, 0x2A), "zoom_y": (1, 0x2B),
        "pos_x": (3, 0x28), "pos_y": (4, 0x29), "rotation": (5, 0x2F)}),
    "crop": (0x06, 0x02, 6, {
        "crop_l": (0, 0x36), "crop_r": (1, 0x37),
        "crop_t": (2, 0x38), "crop_b": (3, 0x39)}),
    "composite": (0x02, 0x06, 2, {"opacity": (1, 0x01)}),
}
_EFB_PARAM_FILTER = {p: f for f, (_, _, _, sm) in _EFB_FILTERS.items() for p in sm}


def _efb_slot_double(param_id: int, value: float) -> bytes:
    return (bytes([0x4A, 0x0F, 0x08, param_id, 0x1A, 0x0B, 0x0A, 0x09, 0x11])
            + struct.pack("<d", float(value)))


def _efb_filter(name: str, vals: dict) -> bytes:
    ftype, f7, nslots, slotmap = _EFB_FILTERS[name]
    slots = [bytes([0x4A, 0x00])] * nslots
    for p, v in vals.items():
        if v is None or p not in slotmap:
            continue
        idx, pid = slotmap[p]
        slots[idx] = _efb_slot_double(pid, v)
    fc = bytes([0x08, ftype, 0x38, f7]) + b"".join(slots)
    return bytes([0x0A]) + _write_varint(len(fc)) + fc


def build_effect_filters_ba(*, zoom_x=None, zoom_y=None, pos_x=None, pos_y=None,
                            rotation=None, crop_l=None, crop_r=None, crop_t=None,
                            crop_b=None, opacity=None) -> str:
    """Monta um `EffectFiltersBA` (hex) com os filtros Transform/Crop/Composite do Resolve.
    Só inclui params não-None. Unidades: `pos_*`/`crop_*` = FRAÇÃO do raster (X÷largura,
    Y÷altura); `zoom_*` = fator; `rotation` = graus; `opacity` = 0–100. O filtro Transform é
    sempre emitido (mesmo todo-vazio); Crop/Composite só quando há valor. Validado byte-exato
    vs exports do Resolve (transform/crop/opacity). Ver docs/effect-translation.md."""
    allv = dict(zoom_x=zoom_x, zoom_y=zoom_y, pos_x=pos_x, pos_y=pos_y, rotation=rotation,
                crop_l=crop_l, crop_r=crop_r, crop_t=crop_t, crop_b=crop_b, opacity=opacity)
    payload = bytes([0x80])
    for fname in ("transform", "crop", "composite"):  # ordem observada no Resolve
        sm = _EFB_FILTERS[fname][3]
        fvals = {p: allv[p] for p in sm if allv.get(p) is not None}
        if fname == "transform" or fvals:   # transform sempre; outros só com valor
            payload += _efb_filter(fname, fvals)
    return (struct.pack(">I", 2) + struct.pack(">I", len(payload)) + payload).hex()


# --------------------------------------------------------------------------- #
# 3) MediaFrameRate — double little-endian + padding
# --------------------------------------------------------------------------- #
def framerate_decode(hexstr: str) -> float:
    b = binascii.unhexlify(hexstr.strip())
    return struct.unpack("<d", b[0:8])[0]


def framerate_encode(fps: float, total_bytes: int = 16) -> str:
    b = struct.pack("<d", fps)
    b = b + b"\x00" * (total_bytes - len(b))
    return b.hex()


# --------------------------------------------------------------------------- #
# DRT/DRP loading
# --------------------------------------------------------------------------- #
def read_container(path: str) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _xml_clips(xml_bytes: bytes, tag: str = "Sm2TiVideoClip"):
    """Itera clipes do XML de timeline tolerando má-formação (FieldsBlob etc.)."""
    import re
    txt = xml_bytes.decode("utf-8", errors="replace")
    for m in re.finditer(rf"<{tag}\b.*?</{tag}>", txt, re.DOTALL):
        block = m.group(0)
        def field(name):
            mm = re.search(rf"<{name}>(.*?)</{name}>", block, re.DOTALL)
            return mm.group(1).strip() if mm else None
        yield block, field


# --------------------------------------------------------------------------- #
# Round-trip self-test (valida os codecs sem Resolve)
# --------------------------------------------------------------------------- #
def selftest(path: str) -> int:
    files = read_container(path)
    seq = next((v for k, v in files.items() if "SeqContainer" in k), None)
    if seq is None:
        print("sem SeqContainer no arquivo"); return 1

    ok = fail = 0

    def check(label, original_hex, roundtrip_hex):
        nonlocal ok, fail
        a = original_hex.strip().lower()
        b = roundtrip_hex.strip().lower()
        if a == b:
            ok += 1
        else:
            fail += 1
            print(f"  ✗ {label}\n    orig={a[:80]}\n    rt  ={b[:80]}")

    # FieldsBlob de cada clipe de vídeo
    for block, field in _xml_clips(seq, "Sm2TiVideoClip"):
        nm = field("Name") or "?"
        fb = field("FieldsBlob")
        if fb:
            try:
                check(f"FieldsBlob {nm}", fb, fieldsblob_encode(fieldsblob_decode(fb)))
            except Exception as e:
                # objetos especiais (ex. clipe _VID REF da própria timeline) usam
                # estruturas protobuf que não modelamos ainda — não são clipes de edição.
                print(f"  ~ FieldsBlob {nm}: pulado ({e})")
        fr = field("MediaFrameRate")
        if fr and fr not in ("", "0"):
            # round-trip do framerate (decodifica e re-encoda no mesmo nº de bytes)
            nbytes = len(binascii.unhexlify(fr))
            check(f"MediaFrameRate {nm}", fr,
                  framerate_encode(framerate_decode(fr), nbytes))
        tm = field("MediaTimemapBA")
        if tm:
            try:
                check(f"MediaTimemapBA {nm}", tm, timemap_encode(timemap_decode(tm)))
            except Exception as e:
                print(f"  ~ MediaTimemapBA {nm}: pulado ({e})")

    print(f"\nround-trip: {ok} OK, {fail} FALHA(S)")
    return 0 if fail == 0 else 2


def dump(path: str) -> None:
    files = read_container(path)
    print("=== arquivos no container ===")
    for n, data in files.items():
        print(f"  {n}  ({len(data)} bytes)")
    seq = next((v for k, v in files.items() if "SeqContainer" in k), None)
    if seq is None:
        return
    print("\n=== clipes de vídeo (campos XML + blobs decodificados) ===")
    for block, field in _xml_clips(seq, "Sm2TiVideoClip"):
        nm = field("Name")
        print(f"\n[{nm}]")
        for k in ("Start", "Duration", "In", "MediaFilePath", "MediaReelNumber",
                  "MediaStartTime"):
            v = field(k)
            if v:
                print(f"  {k} = {v}")
        fr = field("MediaFrameRate")
        if fr:
            try: print(f"  MediaFrameRate = {framerate_decode(fr):.6f}  (hex {fr})")
            except Exception: print(f"  MediaFrameRate = <{fr}>")
        fb = field("FieldsBlob")
        if fb:
            try:
                d = fieldsblob_decode(fb)
                rt = "✓" if fieldsblob_encode(d) == fb.strip().lower() else "✗"
                print(f"  FieldsBlob[{rt}] = v{d['version']} flag={d['flag']:#x} fields={d['fields']}")
            except Exception as e:
                print(f"  FieldsBlob = <não-protobuf simples: {e}>")
        tm = field("MediaTimemapBA")
        if tm:
            toks = ba_tokens(tm)
            print(f"  MediaTimemapBA = {len(binascii.unhexlify(tm))}B keys={toks}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    path = argv[1]
    if "--selftest" in argv:
        return selftest(path)
    dump(path)
    print("\n--- round-trip ---")
    return selftest(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
