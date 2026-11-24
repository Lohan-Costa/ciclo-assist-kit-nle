"""Reel/tape name como CRITÉRIO e o empate resolvido SÓ com confirmação visual (autor, 2026-11-22).

Rodar:

    .venv/bin/python tests/test_reel_e_imagem.py        (Windows: .venv-win/Scripts/python)

- Sem arquivo com o nome do daily, o casador do Premiere (`prproj/originais.casar_um`) casa pelo REEL dele (BL08, P4: o
  daily `CENA12_T3` com reel `B001C007`), com as provas de sempre.
- Empate (≥2 originais diferentes) com o daily no disco: o quadro do daily × o de cada candidato (`_confirmar_pela_imagem`).
  Um bate e os outros não → ele; dois parecidos → continua empate (nunca decidimos sozinhos sem confirmação visual).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from prproj import originais as O  # noqa: E402

SONDA = {"ok": True, "codec": "prores", "fps": 24000 / 1001, "dur_s": 12.0, "tc": "13:00:00:00"}


def test_casa_pelo_reel():
    sondas = {"/d/CENA12_T3.mov": {**SONDA, "w": 960, "h": 540, "reel": "B001C007"},
              "/o/B001C007.mov": {**SONDA, "w": 1920, "h": 1080, "reel": "B001C007"}}
    with mock.patch.object(O, "sondar", lambda c: sondas.get(c, {"ok": False})), \
         mock.patch.object(O.os.path, "exists", lambda c: c in sondas):
        r = O.casar_um("/d/CENA12_T3.mov", {"b001c007": ["/o/B001C007.mov"]})
    assert r["estado"] == "original" and r["original"] == "/o/B001C007.mov" and r.get("por_reel") == "B001C007", r


def test_o_render_da_cor_e_um_trecho_do_original():
    """BL09 (2026-11-22): o render do Baselight volta à montagem com o TC de FONTE e o reel do original — mais curto e
    com outro TC de início. Casa no original COM o deslocamento; o daily inteiro de TC errado continua recusado."""
    rnd = {**SONDA, "codec": "prores", "w": 1920, "h": 1080, "reel": "C001C003", "tc": "17:00:02:12",
           "dur_s": 47 * 1001 / 24000, "fps": 24000 / 1001}
    org = {**SONDA, "codec": "prores", "w": 1920, "h": 1080, "reel": "C001C003", "tc": "17:00:00:00",
           "dur_s": 240 * 1001 / 24000, "fps": 24000 / 1001}
    sondas = {"/r/C001C003_COR.mov": rnd, "/o/C001C003.mov": org}
    with mock.patch.object(O, "sondar", lambda c: sondas.get(c, {"ok": False})), \
         mock.patch.object(O.os.path, "exists", lambda c: c in sondas):
        r = O.casar_um("/r/C001C003_COR.mov", {"c001c003": ["/o/C001C003.mov"]})
        assert r["estado"] == "original" and r["original"] == "/o/C001C003.mov", r
        assert r["trecho"]["desloc_quadros"] == 60 and "render da cor" in r["trecho"]["motivo"], r
        # fora do original (o fim passa do último quadro): não é trecho
        sondas["/r/C001C003_COR.mov"] = {**rnd, "tc": "17:00:09:00"}
        assert O.casar_um("/r/C001C003_COR.mov", {"c001c003": ["/o/C001C003.mov"]})["estado"] != "original"
        # TC zerado não prova nada
        sondas["/r/C001C003_COR.mov"] = {**rnd, "tc": "00:00:00:00"}
        assert "trecho" not in O.casar_um("/r/C001C003_COR.mov", {"c001c003": ["/o/C001C003.mov"]})
        # outra taxa: não
        sondas["/r/C001C003_COR.mov"] = {**rnd, "fps": 25.0, "dur_s": 47 / 25}
        assert "trecho" not in O.casar_um("/r/C001C003_COR.mov", {"c001c003": ["/o/C001C003.mov"]})


def test_o_render_de_outra_taxa():
    """BL08 (2026-11-23): o render de um plano de 29,97 DF numa timeline de 23,976 sai em 23,976 com o TC de fonte no
    contador CRU do `tmcd`, na base do original (30, DF) — o ffprobe não dá TC nenhum — e o reel com a extensão. Casa
    pelo reel, com o deslocamento EM QUADROS DO ORIGINAL (359) e em segundos; sem a base do original, recusa."""
    rnd = {**SONDA, "codec": "prores", "w": 1920, "h": 1080, "reel": "A002C001.mov", "tc": None,
           "dur_s": 48 * 1001 / 24000, "fps": 24000 / 1001,
           "tmcd": {"quadro": 1832425, "base": 30, "df": True, "taxa": 24000 / 1001}}
    org = {**SONDA, "codec": "prores", "w": 1920, "h": 1080, "reel": "A002C001", "tc": "16:58:50;00",
           "dur_s": 599 * 1001 / 30000, "fps": 30000 / 1001}
    sondas = {"/r/A002C001_COR.mov": rnd, "/o/A002C001.mov": org}
    with mock.patch.object(O, "sondar", lambda c: sondas.get(c, {"ok": False})), \
         mock.patch.object(O.os.path, "exists", lambda c: c in sondas):
        r = O.casar_um("/r/A002C001_COR.mov", {"a002c001": ["/o/A002C001.mov"]})
        assert r["estado"] == "original" and r["trecho"]["desloc_quadros"] == 359, r
        assert abs(r["trecho"]["desloc_s"] - 359 * 1001 / 30000) < 1e-9 and "29,970" in r["trecho"]["motivo"], r
        sondas["/r/A002C001_COR.mov"] = {**rnd, "tmcd": {**rnd["tmcd"], "base": 24}}     # base de outra taxa: não prova
        assert "trecho" not in O.casar_um("/r/A002C001_COR.mov", {"a002c001": ["/o/A002C001.mov"]})


def test_trecho_em_copias_identicas():
    """Premiere → Resolve (2026-11-23): os originais do BL09 são cópias dos do BL08 — o C001C003 empatava consigo mesmo.
    Cópias idênticas valem como um só (a regra de sempre), com o trecho; diferentes, continua empate."""
    rnd = {**SONDA, "reel": "C001C003", "tc": "17:00:02:12", "dur_s": 47 * 1001 / 24000, "fps": 24000 / 1001}
    org = {**SONDA, "reel": "C001C003", "tc": "17:00:00:00", "dur_s": 240 * 1001 / 24000, "fps": 24000 / 1001}
    sondas = {"/r/C001C003_COR.mov": rnd, "/a/C001C003.mov": org, "/b/C001C003.mov": org}
    idx = {"c001c003": ["/a/C001C003.mov", "/b/C001C003.mov"]}
    with mock.patch.object(O, "sondar", lambda c: sondas.get(c, {"ok": False})), \
         mock.patch.object(O.os.path, "exists", lambda c: c in sondas):
        with mock.patch.object(O, "_impressao", lambda c: (1, "igual")):
            r = O.casar_um("/r/C001C003_COR.mov", idx)
        assert r["estado"] == "original" and r["trecho"]["desloc_quadros"] == 60 and r["copias"], r
        with mock.patch.object(O, "_impressao", lambda c: (1, c)):
            assert O.casar_um("/r/C001C003_COR.mov", idx)["estado"] == "ambiguo"


def test_tmcd_cru():
    """O leitor do `tmcd` sobre um QuickTime mínimo: flags DF, timescale 24000/1001, nframes 30, contador 1832425."""
    import os
    import struct
    import tempfile

    def atom(t, corpo):
        return struct.pack(">I4s", 8 + len(corpo), t) + corpo
    entrada = atom(b"tmcd", b"\0" * 6 + struct.pack(">H", 1) + b"\0" * 4
                   + struct.pack(">IIIBB", 1, 24000, 1001, 30, 0))
    stsd = atom(b"stsd", struct.pack(">II", 0, 1) + entrada)
    ftyp = atom(b"ftyp", b"qt  " + b"\0" * 4)
    mdat = atom(b"mdat", struct.pack(">I", 1832425))
    def moov(off):
        stco = atom(b"stco", struct.pack(">III", 0, 1, off))
        return atom(b"moov", atom(b"trak", atom(b"mdia", atom(b"minf", atom(b"stbl", stsd + stco)))))
    off = len(ftyp) + 8
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "x.mov")
        open(f, "wb").write(ftyp + mdat + moov(off))
        t = O.tmcd_cru(f)
    assert t == {"quadro": 1832425, "base": 30, "df": True, "taxa": 24000 / 1001}, t


def _quadros(mapa):
    return lambda caminho, t: mapa[caminho]


def test_imagem_confirma_um():
    daily, a, b = bytes([100] * 6912), bytes([100] * 6912), bytes([160] * 6912)     # b: outra cor
    with mock.patch.object(O, "_quadro_rgb", _quadros({"/d": daily, "/a": a, "/b": b})):
        escolhido, notas = O._confirmar_pela_imagem("/d", ["/a", "/b"], {"dur_s": 10.0})
    assert escolhido == "/a" and notas["/a"] == 1.0, notas


def test_imagem_sem_confirmacao_nao_decide():
    daily, a, b = bytes([100] * 6912), bytes([101] * 6912), bytes([102] * 6912)     # os dois quase iguais ao daily
    with mock.patch.object(O, "_quadro_rgb", _quadros({"/d": daily, "/a": a, "/b": b})):
        escolhido, notas = O._confirmar_pela_imagem("/d", ["/a", "/b"], {"dur_s": 10.0})
    assert escolhido is None, notas                                                 # empate: para o editor


if __name__ == "__main__":
    for t in (test_casa_pelo_reel, test_o_render_da_cor_e_um_trecho_do_original, test_o_render_de_outra_taxa, test_trecho_em_copias_identicas, test_tmcd_cru,
              test_imagem_confirma_um, test_imagem_sem_confirmacao_nao_decide):
        t()
        print("ok", t.__name__)
    sys.exit(0)
