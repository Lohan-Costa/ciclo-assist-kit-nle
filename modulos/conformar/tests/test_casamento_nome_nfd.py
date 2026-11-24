"""O nome com acento casa quando a pasta lista em NFD e o projeto grava NFC (2026-11-22).

Rodar:

    .venv/bin/python tests/test_casamento_nome_nfd.py        (Windows: .venv-win/Scripts/python)

O exFAT e o HFS+ do Mac LISTAM em NFD; o .prproj/AAF grava NFC (matriz de plataforma, "Unicode do nome"). No
laboratório BL08 (pegadinha P5) o daily `CORAÇÃO_01.mov` com o caminho em NFC dava "sem original" com o original
na pasta. O índice (`prproj/originais.indexar`) e as buscas usam a mesma chave: NFC e minúsculo. Aqui a listagem
NFD é fingida (`os.walk` trocado), para valer em qualquer disco.
"""
from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from prproj import originais as O  # noqa: E402

NFD = unicodedata.normalize("NFD", "CORAÇÃO_01")
NFC = unicodedata.normalize("NFC", "CORAÇÃO_01")


def _walk_nfd(raiz):
    yield raiz, [], [NFD + ".mov", NFD + ".png", "._" + NFD + ".mov"]


def test_indice_tem_a_chave_em_nfc():
    with mock.patch.object(O.os, "walk", _walk_nfd):
        idx = O.indexar(["/pasta"])
    assert unicodedata.normalize("NFC", "coração_01") in idx
    assert len(idx[unicodedata.normalize("NFC", "coração_01")]) == 1      # a sombra `._` fica de fora


def test_imagem_parada_em_nfc_acha_o_arquivo_listado_em_nfd():
    with mock.patch.object(O.os, "walk", _walk_nfd):
        idx = O.indexar(["/pasta"])
    bons, copias = O.pelo_nome(f"/projeto/{NFC}.png", idx)
    assert bons == [os.path.join("/pasta", NFD + ".png")] and copias == []


def test_video_em_nfc_tem_candidato():
    with mock.patch.object(O.os, "walk", _walk_nfd):
        idx = O.indexar(["/pasta"])
    sondas = {os.path.join("/pasta", NFD + ".mov"): {"ok": True, "w": 1920, "h": 1080, "codec": "prores",
                                                    "fps": 24000 / 1001, "dur_s": 10.0, "tc": "14:10:00:00"}}
    with mock.patch.object(O, "sondar", lambda c: sondas.get(c, {"ok": False})):
        r = O.casar_um(f"/proxies/{NFC}.mov", idx, {"ok": True, "w": 960, "h": 540, "codec": "prores",
                                                   "fps": 24000 / 1001, "dur_s": 10.0, "tc": "14:10:00:00"})
    assert r["candidatos"] or r["original"], r


if __name__ == "__main__":
    testes = [test_indice_tem_a_chave_em_nfc, test_imagem_parada_em_nfc_acha_o_arquivo_listado_em_nfd,
              test_video_em_nfc_tem_candidato]
    for t in testes:
        t()
        print("ok", t.__name__)
    sys.exit(0)
