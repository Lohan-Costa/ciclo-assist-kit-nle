"""A taxa de quadros por VOTAÇÃO em todo leitor do ffprobe (banco, bugs-do-mundo-real B074; 2026-10-28).

Rodar:  .venv/bin/python tests/test_taxa_votacao.py        (Windows: .venv-win/Scripts/python)

O `r_frame_rate` do MXF de vídeo do Avid é a METADE da taxa (medido em `Avid MediaFiles`: `12000/1001` num V01 de
23,976; `15000/1001` num de 29,97). Quatro leitores ainda liam o campo cru — o DRT (`MediaFrameRate`), o descritor de
vídeo do AVB, o TC do AAF e a duração "como o MC" do `clone_generic`. E a votação, sem acordo, ficava com o inverso do
`time_base`: 90000 fps num MP4 de celular de taxa variável. Os streams aqui são os medidos (dicionários do ffprobe).
"""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from media.opatom import _video_rate  # noqa: E402

casos, falhas = 0, []

#: o V01.mxf do Avid (Avid MediaFiles/MXF/PRODE), o MP4 normal, o celular de taxa variável
AVID = {"codec_type": "video", "r_frame_rate": "12000/1001", "avg_frame_rate": "24000/1001", "time_base": "1001/24000"}
AVID_SEM_MEDIA = {**AVID, "avg_frame_rate": "0/0"}
AVID_SEM_TB = {k: v for k, v in AVID.items() if k != "time_base"}
MP4 = {"codec_type": "video", "r_frame_rate": "25/1", "avg_frame_rate": "25/1", "time_base": "1/12800"}
CELULAR = {"codec_type": "video", "r_frame_rate": "30/1", "avg_frame_rate": "2950/100", "time_base": "1/600"}


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def main() -> int:
    print("a votação:")
    ok("MXF do Avid → 23,976 (não 11,988)", _video_rate(AVID), (24000, 1001))
    ok("MXF do Avid sem média (0/0) → pelo time_base", _video_rate(AVID_SEM_MEDIA), (24000, 1001))
    ok("MXF do Avid sem time_base → a média (acima do cabeçalho)", _video_rate(AVID_SEM_TB), (24000, 1001))
    ok("MP4 normal → 25", _video_rate(MP4), (25, 1))
    ok("celular de taxa variável → o cabeçalho (30), nunca 600", _video_rate(CELULAR), (30, 1))

    print("os leitores:")
    from drp import writer as drp_writer
    drp_writer._sonda.ler = lambda caminho: {"streams": [{**AVID, "nb_frames": "240"}], "format": {}}
    drp_writer._META_CACHE.clear()
    ok("DRT: MediaFrameRate do MXF do Avid", round(drp_writer._media_meta("/x/V01.mxf")[1], 3), 23.976)

    from avb_export import video_descriptor as vd
    vd.subprocess.check_output = lambda *a, **k: json.dumps(
        {"streams": [{**AVID, "width": 1920, "height": 1080, "codec_name": "dnxhd"}]}).encode()
    ok("AVB: descritor de vídeo do MXF do Avid", vd.probe_video("/x/V01.mxf")["fps"], (24000, 1001))

    from aaf import writer as aaf_writer
    aaf_writer._ffprobe_meta = lambda caminho: {"streams": [{**AVID, "nb_frames": "240"}],
                                               "format": {"tags": {"timecode": "01:00:00:00"}}}
    r = aaf_writer._probe_online_tc("/x/V01.mxf")
    ok("AAF: TC do MXF do Avid na base 24 (não 12)", (r[1], r[3]), (24, Fraction(24000, 1001)))

    from avb_export import clone_generic as cg

    class Saida:
        def __init__(self, texto):
            self.stdout = texto

    def falso_run(cmd, **k):
        if "v:0" in cmd:
            return Saida("nb_frames=240\nr_frame_rate=12000/1001\navg_frame_rate=24000/1001\ntime_base=1001/24000\n")
        return Saida("nb_frames=500\ncodec_name=aac\nsample_rate=48000\n")
    cg.subprocess.run = falso_run
    # 500 pacotes AAC = 10,67 s → 256 quadros a 23,976 (a 11,988 dariam 128 e venceria o vídeo, 240)
    ok("clone_generic: duração do AAC mais longo em quadros de 23,976", cg._quadros_como_o_mc("/x/a.mp4"), 256)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
