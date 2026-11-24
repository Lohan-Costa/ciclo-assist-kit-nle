"""O ORIGINAL de TC zerado com a CONVERSÃO carimbada com TC (autor, 2026-11-22; laboratório BL08, P12).

Rodar:

    .venv/bin/python tests/test_original_tc_zerado_maior.py        (Windows: .venv-win/Scripts/python)

A regra de 31/10 recusa o candidato de TC zerado quando o arquivo do projeto tem TC real e está no disco (a conversão que
perdeu o TC ao lado do original que a timeline já usa). No P12 é o contrário: o projeto usa o daily (960×540, TC
21:00:00:00) e o original de câmera tem TC zerado — e ficava "sem original". Agora: MAIOR nas duas medidas = o original,
com a dúvida à vista; menor = recusado como antes. As sondagens são fingidas (o que importa é a decisão).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from prproj import originais as O  # noqa: E402

PROXY = "/proj/A006C002.mov"
SONDA_PROXY = {"ok": True, "w": 960, "h": 540, "codec": "prores", "fps": 24000 / 1001, "dur_s": 12.0,
               "tc": "21:00:00:00"}


def _casar(candidato: str, sonda_cand: dict) -> dict:
    sondas = {PROXY: SONDA_PROXY, candidato: sonda_cand}
    with mock.patch.object(O, "sondar", lambda c: sondas.get(c, {"ok": False})), \
         mock.patch.object(O.os.path, "exists", lambda c: c in sondas):
        return O.casar_um(PROXY, {"a006c002": [candidato]})


def test_maior_de_tc_zerado_entra_com_duvida():
    r = _casar("/orig/A006C002.mov", {"ok": True, "w": 1920, "h": 1080, "codec": "prores", "fps": 24000 / 1001,
                                      "dur_s": 12.0, "tc": "00:00:00:00"})
    assert r["estado"] == "original" and r["original"] == "/orig/A006C002.mov", r
    assert "maior que o arquivo do projeto" in r.get("duvida", ""), r


def test_menor_de_tc_zerado_segue_recusado():
    r = _casar("/conv/A006C002.mov", {"ok": True, "w": 480, "h": 270, "codec": "h264", "fps": 24000 / 1001,
                                      "dur_s": 12.0, "tc": "00:00:00:00"})
    assert r["estado"] != "original" and not r["original"], r


if __name__ == "__main__":
    for t in (test_maior_de_tc_zerado_entra_com_duvida, test_menor_de_tc_zerado_segue_recusado):
        t()
        print("ok", t.__name__)
    sys.exit(0)
