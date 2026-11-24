"""drp/ba_mapa.py — o "BA" de mapa do Resolve, lido e escrito byte a byte.

Vários blobs do DRT (o `f1.f5` do `FieldsBlob` do item de áudio, por exemplo) guardam um mapa
serializado no QDataStream do Qt 5:

    mapa    = [u32 versão][u32 n] + n × (QString chave, QVariant valor)
    QString = [u32 bytes][UTF-16BE]           (0xFFFFFFFF = nulo)
    QVariant= [u32 tipo][u8 nulo][valor]      (2 int, 3 uint, 4/5 int64, 6 double,
                                               10 QString, 12 QByteArray, 8 map, 9 list)

Um valor QByteArray pode ser OUTRO mapa no mesmo formato (o `ChannelVecBA` dentro de cada canal).
Ida e volta exata medida no esqueleto e no item WAV nativo do Resolve 19 (2026-09-26).
"""
from __future__ import annotations

import struct

QBYTEARRAY = 12


def ler_variant(b: bytes, o: int):
    t = struct.unpack(">I", b[o:o + 4])[0]
    nulo = b[o + 4]
    o += 5
    if t == 1:
        v = b[o]
        o += 1
    elif t in (2, 3):
        v = struct.unpack(">i" if t == 2 else ">I", b[o:o + 4])[0]
        o += 4
    elif t in (4, 5):
        v = struct.unpack(">q" if t == 4 else ">Q", b[o:o + 8])[0]
        o += 8
    elif t == 6:
        v = struct.unpack(">d", b[o:o + 8])[0]
        o += 8
    elif t in (10, 12):
        n = struct.unpack(">I", b[o:o + 4])[0]
        o += 4
        if n == 0xFFFFFFFF:
            v = None
        else:
            v = b[o:o + n].decode("utf-16-be") if t == 10 else b[o:o + n]
            o += n
    elif t == 8:
        n = struct.unpack(">I", b[o:o + 4])[0]
        o += 4
        v = []
        for _ in range(n):
            k, o = _ler_chave(b, o)
            x, o = ler_variant(b, o)
            v.append((k, x))
    elif t == 9:
        n = struct.unpack(">I", b[o:o + 4])[0]
        o += 4
        v = []
        for _ in range(n):
            x, o = ler_variant(b, o)
            v.append(x)
    else:
        raise ValueError(f"QVariant de tipo {t} não suportado @ {o}")
    return [t, nulo, v], o


def escrever_variant(q) -> bytes:
    t, nulo, v = q
    out = struct.pack(">I", t) + bytes([nulo])
    if t == 1:
        out += bytes([v])
    elif t in (2, 3):
        out += struct.pack(">i" if t == 2 else ">I", v)
    elif t in (4, 5):
        out += struct.pack(">q" if t == 4 else ">Q", v)
    elif t == 6:
        out += struct.pack(">d", v)
    elif t in (10, 12):
        if v is None:
            out += b"\xff\xff\xff\xff"
        else:
            dados = v.encode("utf-16-be") if t == 10 else bytes(v)
            out += struct.pack(">I", len(dados)) + dados
    elif t == 8:
        out += struct.pack(">I", len(v))
        for k, x in v:
            out += _escrever_chave(k) + escrever_variant(x)
    elif t == 9:
        out += struct.pack(">I", len(v))
        for x in v:
            out += escrever_variant(x)
    else:
        raise ValueError(f"QVariant de tipo {t} não suportado")
    return out


def _ler_chave(b: bytes, o: int):
    n = struct.unpack(">I", b[o:o + 4])[0]
    o += 4
    return b[o:o + n].decode("utf-16-be"), o + n


def _escrever_chave(k: str) -> bytes:
    kb = k.encode("utf-16-be")
    return struct.pack(">I", len(kb)) + kb


def ler_mapa(b: bytes) -> tuple[int, list, bytes]:
    """`(versão, [(chave, QVariant)], resto)`."""
    ver, n = struct.unpack(">II", b[:8])
    o = 8
    itens = []
    for _ in range(n):
        k, o = _ler_chave(b, o)
        x, o = ler_variant(b, o)
        itens.append((k, x))
    return ver, itens, b[o:]


def escrever_mapa(ver: int, itens: list, resto: bytes = b"") -> bytes:
    out = struct.pack(">II", ver, len(itens))
    for k, x in itens:
        out += _escrever_chave(k) + escrever_variant(x)
    return out + resto


def valor(itens: list, chave: str):
    return next((x for k, x in itens if k == chave), None)
