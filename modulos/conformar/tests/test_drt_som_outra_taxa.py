"""O SOM de uma fonte de OUTRA TAXA leva o `<In>` com FRAÇÃO, como o vídeo (2026-11-23, Resolve 21.1 Mac).

    .venv/bin/python tests/test_drt_som_outra_taxa.py

O DRT nativo do Resolve (A002C001, 29,97, do quadro 364 numa timeline de 23,976) grava `<In>291|<fração>` no vídeo E no
áudio. Com o áudio inteiro (291) o bipe do laboratório saiu 8,34 ms (0,2 quadro) atrasado no render; com a fração,
0,01 ms (igual ao nativo) — `laboratorio-de-midia/lab/bancadas/som_outra_taxa.py`.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp.writer import build_drt, ler_in  # noqa: E402
from media import fftools  # noqa: E402


def _video(destino: str, taxa: str) -> None:
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s=160x90:r={taxa}:d=20",
                    "-f", "lavfi", "-i", "sine=f=1000:d=20", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", destino], check=True, **fftools.SEM_JANELA)


def _ins(arquivo: str, fps_f: float, q: int) -> tuple[str, str]:
    tl = 24000 / 1001

    def seg(audio):
        return {"timeline_tc_in": "00:00:00:00", "timeline_tc_out": "00:00:02:00", "duration_frames": 48,
                "source_start_frames": q, "source_fps": fps_f, "clip_name": "x", "track": 1, "is_gap": False,
                "is_transition": False, "is_effect": False, "is_audio": audio, "speed_ratio": tl / fps_f,
                "conform_ratio": 1.0, "relative_speed": 1.0, "motion_class": "native", "effects": [], "disabled": False,
                "media_ref": {"local_path": arquivo, "descriptor_type": "prproj", "source_fps": fps_f}}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.drt")
        build_drt([seg(False), seg(True)], [{"segment_index": 0, "matched_path": arquivo},
                                            {"segment_index": 1, "matched_path": arquivo}], p, timeline_name="x",
                  timeline_fps=tl, timeline_start_frames=0, timeline_size=(1920, 1080))
        with zipfile.ZipFile(p) as z:
            txt = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if "SeqContainer" in n)
    v = re.search(r"<Sm2TiVideoClip\b.*?<In>([^<]*)</In>", txt, re.S).group(1)
    a = re.search(r"<Sm2TiAudioClip\b.*?<In>([^<]*)</In>", txt, re.S).group(1)
    return v, a


def test_som_de_outra_taxa_com_fracao_igual_ao_video():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "v2997.mov")
        _video(f, "30000/1001")
        v, a = _ins(f, 30000 / 1001, 364)
        assert a == v and a.startswith("291|"), (v, a)
        assert abs(ler_in(a) - 291.2) < 1e-6


def test_mesma_taxa_continua_inteiro():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "v2398.mov")
        _video(f, "24000/1001")
        v, a = _ins(f, 24000 / 1001, 47)
        assert a == "47" and "|" not in v, (v, a)


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print("ok", nome)
