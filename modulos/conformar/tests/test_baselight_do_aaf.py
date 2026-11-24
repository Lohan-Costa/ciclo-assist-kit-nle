"""O xmeml da montagem do MC gerado da leitura do AAF (`baselight/do_aaf.escrever`), para a mesma entrega do Premiere.

    .venv/bin/python tests/test_baselight_do_aaf.py        (Windows: .venv-win/Scripts/python)

- O `<in>` é o `source_start_frames` do AAF (já na taxa da timeline desde o início do arquivo): o plano de 29,97 do BL08
  (P7) vem com 287, e a `entrega.esperado` dá o quadro 359 do arquivo — o do vid ref do MC.
- O `<format>` da sequência existe (sem ele o `bl-conform` 7.0.3 recusa: e1624).
- Plano sem daily nesta máquina, ou com velocidade, vai para o retorno — nunca some calado.
"""
from __future__ import annotations

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import do_aaf, entrega  # noqa: E402

SONDA = {"ok": True, "fps": 30000 / 1001, "dur_s": 20.02, "tc": "00:00:00:00", "w": 960, "h": 540}


def _leitura(daily):
    seg = {"track": 1, "timeline_tc_in": "00:00:22:00", "duration_frames": 48, "source_start_frames": 287,
           "clip_name": "A002C001", "media_ref": {"local_path": daily, "source_duration_frames": 480}}
    lento = dict(seg, timeline_tc_in="00:00:24:00", speed_ratio=0.5, has_motion_effect=True)
    sem = dict(seg, timeline_tc_in="00:00:26:00", media_ref={"local_path": "/nao/existe.mov"})
    return {"timeline_fps": 24000 / 1001, "timeline_start_tc": "01:00:00:00", "timeline_start_frames": 86400,
            "composition_name": "T", "segments": [seg, {"is_gap": True}, lento, sem]}


def test_xmeml_do_aaf():
    with tempfile.TemporaryDirectory() as d:
        daily = os.path.join(d, "A002C001.mov")
        open(daily, "wb").close()
        saida = os.path.join(d, "t.xml")
        r = do_aaf.escrever(_leitura(daily), saida, lambda c: SONDA,
                            lambda s: s["media_ref"]["local_path"] if os.path.exists(s["media_ref"]["local_path"]) else None)
        assert r["planos"] == 2 and len(r["sem_daily"]) == 1 and len(r["nao_traduzido"]) == 1, r
        raiz = ET.parse(saida).getroot()
        assert raiz.find("sequence/media/video/format/samplecharacteristics/width").text == "960"
        ci = raiz.find(".//clipitem")
        assert (ci.findtext("start"), ci.findtext("end"), ci.findtext("in")) == ("528", "576", "287")
        esp = entrega.esperado(saida)[0]
        assert esp["in"] == 359 and esp["out"] == 359 + 60 - 1, esp      # 48 q a 23,976 = 60 q a 29,97


if __name__ == "__main__":
    test_xmeml_do_aaf()
    print("ok test_xmeml_do_aaf")
    sys.exit(0)
