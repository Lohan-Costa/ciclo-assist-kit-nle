"""A Carta Aberta e o Baselight (etapa 3 da proposta do Ciclo Assist 2026-11-22-baselight-no-app), sem o Baselight:

    .venv/bin/python -m pytest tests/test_baselight_carta.py        (Windows: .venv-win/Scripts/python)

- o xmeml da Carta lido só no que o casamento precisa: um plano por clipitem de VÍDEO com arquivo, o `<in>` na taxa da
  timeline, o desligado marcado; o que não é xmeml é recusado;
- "Importar timeline" (a Carta não é conform): cada arquivo descrito como É; o que não está aqui vai offline;
- o pedido "Conformar com De Lá Pra Cá" é consumido UMA vez e o velho (> 15 min) é ignorado.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

from baselight import enviar, xmeml  # noqa: E402

XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4"><sequence id="sequence-1"><name>CENA 7</name><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>
<media><video><format><samplecharacteristics><width>1920</width><height>1080</height></samplecharacteristics></format>
<track>
 <clipitem id="c1"><name>A</name><enabled>TRUE</enabled><start>0</start><end>48</end><in>287</in><out>335</out>
  <file id="f1"><name>a.mov</name><pathurl>file://localhost{a}</pathurl><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate></file></clipitem>
 <clipitem id="c2"><name>B</name><enabled>FALSE</enabled><start>48</start><end>96</end><in>0</in><out>48</out>
  <file id="f2"><name>b.mov</name><pathurl>file://localhost{b}</pathurl></file></clipitem>
 <clipitem id="c3"><name>A de novo</name><enabled>TRUE</enabled><start>96</start><end>120</end><in>10</in><out>34</out>
  <file id="f1"/></clipitem>
</track></video><audio><track><clipitem id="a1"><start>0</start><end>48</end><in>0</in><out>48</out>
  <file id="f9"><name>som.wav</name><pathurl>file://localhost/x/som.wav</pathurl></file></clipitem></track></audio>
</media></sequence></xmeml>
"""


def _xml(d: str) -> tuple[str, str, str]:
    a, b = os.path.join(d, "a.mov"), os.path.join(d, "nao existe.mov")
    open(a, "wb").close()
    caminho = os.path.join(d, "t.xml")
    Path(caminho).write_text(XML.replace("{a}", a.replace(" ", "%20")).replace("{b}", b.replace(" ", "%20")),
                             encoding="utf-8")
    return caminho, a, b


def test_ler_o_xmeml_da_carta():
    with tempfile.TemporaryDirectory() as d:
        caminho, a, b = _xml(d)
        assert xmeml.e_xmeml(caminho)
        le = xmeml.ler(caminho)
        assert le["nome"] == "CENA 7" and abs(le["fps"] - 24000 / 1001) < 1e-9 and le["largura"] == 1920
        segs = le["segmentos"]
        assert [s["media_ref"]["local_path"] for s in segs] == [a, b, a]        # o som fica de fora
        assert segs[0]["source_start_frames"] == 287 and segs[0]["timeline_tc_in"] == "00:00:00:00"
        assert segs[1]["disabled"] and segs[2]["timeline_tc_in"] == "00:00:04:00"
        assert xmeml.arquivos(caminho) == sorted({a, b})
        sem = os.path.join(d, "x.xml")
        Path(sem).write_text("<fcpxml/>", encoding="utf-8")
        assert not xmeml.e_xmeml(sem)


def test_importar_como_esta(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        caminho, a, b = _xml(d)
        monkeypatch.setattr(enviar, "_sondar", lambda c: {"fps": 25.0, "dur_s": 10.0, "tc": "10:00:00:00",
                                                           "w": 3840, "h": 2160})
        dec = enviar.decisao_como_esta(caminho)
        assert dec[b] is None                                          # não está aqui: offline de propósito
        assert dec[a]["fps"] == 25.0 and dec[a]["tc"] == "10:00:00:00"  # o arquivo como É, não a taxa da timeline


def test_pedido_da_carta_uma_vez(monkeypatch):
    import plataforma
    from api import rotas

    with tempfile.TemporaryDirectory() as d:
        caminho, _a, _b = _xml(d)
        monkeypatch.setattr(plataforma, "pasta_do_ciclo_assist", lambda: Path(d))
        (Path(d) / "conformar").mkdir()
        arq = Path(d) / "conformar" / "a-conformar.json"

        class Ctx:
            class servico:
                ultimo_uso_receptor = 0

        arq.write_text(json.dumps({"xml": caminho, "nome": "CENA 7", "job": "FILME", "quando": time.time()}),
                       encoding="utf-8")
        codigo, r = rotas.receber_a_conformar(Ctx())
        assert codigo == 200 and os.path.samefile(r["xml"], caminho) and r["job"] == "FILME"
        assert rotas.receber_a_conformar(Ctx())[1] == {}                # consumido: a 2ª batida não reabre
        arq.write_text(json.dumps({"xml": caminho, "quando": time.time() - 3600}), encoding="utf-8")
        assert rotas.receber_a_conformar(Ctx())[1] == {}                # velho: ignorado


# ── etapa 4: o job ABERTO e a PRODUÇÃO na Carta ──────────────────────────────────────────────────────────────────────

def test_ler_locks_do_lsscenes():
    """A scene aberta na interface (mesmo só leitura) tem lock no `bl-lsscenes -k`; as outras, não (7.0.3, 22/11)."""
    texto = ("localhost:LAB_BASELIGHT:BL08 CARTA IMPORTAR Read\n"
             "localhost:LAB_BASELIGHT:BL08 CASAMENTO · import 02\n"
             "localhost:LAB_BASELIGHT:C07 v2 Write\n"
             "localhost:OUTRO:X Write\n")
    assert enviar.ler_locks(texto, "LAB_BASELIGHT") == {"BL08 CARTA IMPORTAR": "Read", "C07 v2": "Write"}


def test_job_aberto_pula_a_galeria(monkeypatch):
    class R:
        def __init__(self, s): self.stdout = s
    saidas = {"baselight_gallery": "localhost:baselight_gallery:LAB_BASELIGHT Write\n",
              "VAZIO": "localhost:VAZIO:A\n",
              "LAB_BASELIGHT": "localhost:LAB_BASELIGHT:BL08 CARTA IMPORTAR Read\n"}
    monkeypatch.setattr(enviar, "jobs", lambda: list(saidas))
    monkeypatch.setattr(enviar, "_bl", lambda *a, **k: R(saidas[a[-1].split(":", 1)[1]]))
    assert enviar.job_aberto() == {"job": "LAB_BASELIGHT", "scene": "BL08 CARTA IMPORTAR", "lock": "Read"}
    # duas abertas: vale a de ESCRITA (a do colorista), mesmo vindo depois
    saidas["LAB_BL09"] = "localhost:LAB_BL09:BL09 V1 dividida Write\n"
    assert enviar.job_aberto() == {"job": "LAB_BL09", "scene": "BL09 V1 dividida", "lock": "Write"}
    saidas.pop("LAB_BASELIGHT")
    saidas.pop("LAB_BL09")
    assert enviar.job_aberto() is None


def test_producao_vai_na_carta():
    from carta_aberta.writer import montar
    base = {"timeline": {"name": "T", "fps": 24, "start_tc": "01:00:00:00", "tracks": []}, "clips": []}
    try:
        com = montar(base, [], "T", producao="PRODUCAO-A")
        sem = montar(base, [], "T")
    except (KeyError, TypeError) as e:          # o formato do `resultado` mudou: o teste diz, não esconde
        raise AssertionError(f"montar() não aceitou o resultado mínimo: {e}")
    assert com["producao"] == "PRODUCAO-A"
    assert "producao" not in sem


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
