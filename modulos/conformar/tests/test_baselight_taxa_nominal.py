"""O `bl-conform` conta o `<in>` pelas taxas NOMINAIS (PRODUCAO-C pela janela do app, Baselight 7.0.3, 2026-11-23).

    .venv/bin/python tests/test_baselight_taxa_nominal.py

- Sequência 23,976 e arquivo 25: o Baselight pôs o PRJ-0006-217 no quadro 6741 (6471 × 25/24), o certo é 6747
  (6471 / 23,976 × 25) — 56 de 74 planos fora do ponto. A entrega desloca in e out pelo MESMO Δ (a duração fica).
- Os dois NTSC (29,97 numa 23,976, o BL08) ou nenhum: nada muda.
- Imagem parada ("…530x298.psd.jpg"): o Baselight dá in/out pelo número do nome; a conferência olha só o arquivo.
"""
from __future__ import annotations

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import conferencia as C  # noqa: E402
from baselight import entrega as E  # noqa: E402


def _xml(tb_seq, ntsc_seq, tb_f, ntsc_f, entra, dur, nome="PRJ-0006-217-A1-8CE2.mov"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4"><sequence id="s"><rate><timebase>{tb_seq}</timebase><ntsc>{ntsc_seq}</ntsc></rate>
<media><video><track><clipitem id="c1"><name>{nome}</name><start>0</start><end>{dur}</end><in>{entra}</in>
<out>{entra + dur}</out><file id="file-1"><name>{nome}</name><pathurl>file://localhost/x/{nome}</pathurl>
<rate><timebase>{tb_f}</timebase><ntsc>{ntsc_f}</ntsc></rate></file></clipitem></track></video></media></sequence></xmeml>"""


def _compensado(texto):
    raiz = ET.fromstring(texto)
    E._compensar_taxa_nominal(raiz)
    ci = raiz.find(".//clipitem")
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as fh:
        fh.write(ET.tostring(raiz, encoding="unicode"))
    try:
        return int(ci.findtext("in")), int(ci.findtext("out")), E.esperado(fh.name)[0]
    finally:
        os.unlink(fh.name)


def test_misto_desloca_in_e_out_pelo_mesmo_delta():
    entra, sai, esp = _compensado(_xml(24, "TRUE", 25, "FALSE", 6471, 9))
    assert (entra, sai) == (6477, 6486)                     # Δ = round(6471 × 0,001) = 6; a duração fica 9
    assert round(entra * 25 / 24) == 6747 == esp["in"]       # o Baselight (nominal) cai no quadro certo
    assert round(6471 / (24000 / 1001) * 25) == 6747         # (o quadro verdadeiro, por tempo)
    # 100 qps (o LOU_7310): dentro da tolerância do Baselight (1 quadro da timeline = 4,17 da fonte)
    entra, sai, esp = _compensado(_xml(24, "TRUE", 100, "FALSE", 2566, 17))
    assert sai - entra == 17 and abs(entra * 100 / 24 - 2566 / (24000 / 1001) * 100) <= 100 / 24


def test_os_dois_ntsc_ou_nenhum_nao_mudam():
    for args in ((24, "TRUE", 30, "TRUE"), (24, "TRUE", 24, "TRUE"), (25, "FALSE", 50, "FALSE")):
        entra, sai, esp = _compensado(_xml(*args, 287, 48))
        assert (entra, sai) == (287, 335), args


def test_imagem_parada_confere_so_o_arquivo():
    texto = _xml(24, "TRUE", 25, "FALSE", 0, 123, nome="TitleCardDisplayArt530x298.psd.jpg")
    _e, _s, esp = _compensado(texto)
    assert esp["parada"]
    tira = {"in": 298, "out": 420, "inicio": 0, "fim": 123, "arquivo": "/x/TitleCardDisplayArt530x298.psd.jpg"}
    assert C.conferir([tira], [esp])[0]["estado"] == "ok"
    # e um vídeo com o mesmo desvio continua fora do ponto
    _e, _s, esp_v = _compensado(_xml(24, "TRUE", 25, "FALSE", 0, 123, nome="A.mov"))
    assert not esp_v["parada"]
    assert C.conferir([{**tira, "arquivo": "/x/A.mov"}], [esp_v])[0]["estado"] == "fora_do_ponto"


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_") and callable(f):
            f()
            print("ok", nome)
