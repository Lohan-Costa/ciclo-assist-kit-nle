"""O De Lá Pra Cá com o Baselight (proposta do Ciclo Assist 2026-11-22-baselight-no-app, etapa 2), sem o Baselight:

    .venv/bin/python -m pytest tests/test_baselight_enviar.py        (Windows: .venv-win/Scripts/python)

- nunca sobrescrever, sem "V02": a importação repetida leva " · import 02", 03… (autor, 2026-11-22);
- o nome que o Baselight recebe não leva ":" (separa host:job:scene) nem "/" (vira pasta);
- a leitura do `.prproj` na forma da do AAF: o `<in>` na taxa da TIMELINE (29,97 numa 23,976: o quadro 359 da fonte =
  287, o mesmo que o AAF do MC traz no BL08); a velocidade de verdade é `relative_speed`; desligado e referência fora;
- a entrega CRIA o `<duration>` quando falta (sem ele a sequência DPX entrou como imagem parada: P10 pelo MC no app);
- o caminho do MC parte do DAILY e troca para o original decidido; o que não tem decisão vai offline (nenhum se perde);
- no Windows não há Baselight: `disponivel()` diz por quê.
"""
from __future__ import annotations

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

from baselight import do_prproj, enviar, entrega  # noqa: E402


def test_nome_livre_nunca_sobrescreve():
    assert enviar.nome_livre("C07 v2", []) == "C07 v2"
    assert enviar.nome_livre("C07 v2", ["C07 v2"]) == "C07 v2 · import 02"
    assert enviar.nome_livre("C07 v2", ["C07 v2", "C07 v2 · import 02"]) == "C07 v2 · import 03"


def test_limpar_nome():
    assert enviar.limpar_nome("A:B/C  d") == "A B C d"
    assert enviar.limpar_nome("  ") == "Ciclo Assist"


def test_windows_sem_baselight(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    ok, porque = enviar.disponivel()
    assert not ok and "Windows" in porque
    assert enviar.bin_dir() is None


def test_prproj_como_aaf():
    leitura = {"nome": "S", "fps": 24000 / 1001, "inicio": 0, "segmentos": [
        {"track": 1, "timeline_tc_in": "00:00:22:00", "duration_frames": 48, "source_start_frames": 359,
         "source_fps": 30000 / 1001, "speed_ratio": 0.8, "relative_speed": 1.0, "clip_name": "A002C001",
         "effects": [{"name": "Motion", "params": {"scale_x": 1.0, "scale_y": 1.0, "pos_x": 0.0, "pos_y": -0.0}}],
         "media_ref": {"local_path": "/x/A002C001.mov", "source_duration_frames": 480}},
        {"track": 1, "timeline_tc_in": "00:00:24:00", "duration_frames": 48, "source_start_frames": 10,
         "source_fps": 24000 / 1001, "relative_speed": 0.5, "media_ref": {"local_path": "/x/b.mov"}},
        {"track": 1, "timeline_tc_in": "00:00:26:00", "duration_frames": 48, "disabled": True,
         "media_ref": {"local_path": "/x/desligado.mov"}},
        {"track": 2, "timeline_tc_in": "00:00:00:00", "duration_frames": 960, "referencia": "ref",
         "media_ref": {"local_path": "/x/ref.mov"}},
    ]}
    a = do_prproj.como_aaf(leitura)
    assert a["timeline_fps"] == 24000 / 1001 and a["composition_name"] == "S"
    segs = a["segments"]
    assert len(segs) == 2                                      # o desligado e a referência ficaram de fora
    assert segs[0]["source_start_frames"] == 287               # 359 × 23,976 / 29,97
    assert segs[0]["speed_ratio"] == 1.0 and not segs[0]["has_reframe"]
    assert "source_duration_frames" not in segs[0]["media_ref"]
    assert segs[1]["speed_ratio"] == 0.5                       # velocidade de verdade → nao_traduzido no do_aaf


def _xmeml(caminho_daily: str, com_duracao: bool) -> str:
    dur = "<duration>480</duration>" if com_duracao else ""
    return ('<?xml version="1.0" encoding="UTF-8"?><xmeml version="4"><sequence><rate><timebase>24</timebase>'
            '<ntsc>TRUE</ntsc></rate><media><video><track><clipitem id="c1"><start>0</start><end>48</end><in>23</in>'
            f'<out>71</out><file id="f1"><name>d.mov</name><pathurl>file://localhost{caminho_daily}</pathurl>'
            f'<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>{dur}<timecode><rate><timebase>24</timebase>'
            '<ntsc>TRUE</ntsc></rate><string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat>'
            '</timecode></file></clipitem></track></video></media></sequence></xmeml>')


def test_entrega_cria_a_duracao_que_falta():
    with tempfile.TemporaryDirectory() as d:
        pasta = os.path.join(d, "A003C001")
        os.mkdir(pasta)
        for q in range(1641600, 1641744):
            open(os.path.join(pasta, f"A003C001.{q:07d}.dpx"), "wb").close()
        original = os.path.join(pasta, "A003C001.1641600.dpx")
        entrada, saida = os.path.join(d, "e.xml"), os.path.join(d, "s.xml")
        Path(entrada).write_text(_xmeml("/x/d.mov", com_duracao=False), encoding="utf-8")
        o = entrega.descrever(original, {"fps": 25.0}, fps_sequencia=24000 / 1001)
        entrega.reescrever(entrada, saida, {"/x/d.mov": o}, os.path.join(d, "OFF"))
        f = ET.parse(saida).getroot().find(".//file")
        assert f.findtext("duration") == "144"
        assert f.findtext("pathurl").endswith("A003C001.%25.7F.dpx")


def test_da_carta_parte_do_daily(monkeypatch):
    import baselight_conform as BC

    with tempfile.TemporaryDirectory() as d:
        daily, original = os.path.join(d, "daily.mov"), os.path.join(d, "ORIG.mov")
        for p in (daily, original):
            open(p, "wb").close()
        visto = {}

        def entregar(leitura, achar, decisao, sinais, pastas, nome, andamento, notas=None):
            visto["achar"] = [achar(s) for s in leitura["segments"]]
            visto["decisao"] = decisao
            return {}

        monkeypatch.setattr(BC, "_entregar", entregar)
        monkeypatch.setattr(BC, "_sondar", lambda c: {"fps": 24000 / 1001, "dur_s": 10.0, "tc": "01:00:00:00"})
        monkeypatch.setattr(BC, "_pasta_offline", lambda: os.path.join(d, "OFF"))
        segs = [{"track": 1, "clip_name": "A", "media_ref": {"local_path": daily}},
                {"track": 1, "clip_name": "B", "media_ref": {"local_path": os.path.join(d, "nao_existe.mov")}},
                {"is_audio": True, "media_ref": {"local_path": daily}}]
        casados = [{"segment_index": 0, "matched_path": original}, {"segment_index": 1, "matched_path": None,
                                                                    "offline": True}]
        BC.da_carta({"timeline_fps": 24000 / 1001}, segs, casados, {"m1": original}, {}, [d], "T", lambda *a: None)
        assert visto["achar"][0] == daily                                   # o <file> de partida é o daily
        assert visto["decisao"][daily]["caminho"].endswith("ORIG.mov")      # … trocado para o original decidido
        offline = visto["achar"][1]
        assert offline.startswith(os.path.join(d, "OFF")) and visto["decisao"][offline] is None   # não se perde


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
