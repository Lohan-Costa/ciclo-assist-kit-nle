"""A taxa (`MediaFrameRate`) do clipe de ÁUDIO no DRT (2026-10-08).

Rodar:

    .venv/bin/python tests/test_audio_taxa.py        (Windows: .venv-win/Scripts/python)

⛔ O Resolve TOCA o áudio pela `MediaFrameRate` do clipe. O writer herdava 23,976 do molde: o som
da referência do PRODUCAO_B (mp4 a 24) ia 0,1% mais lento — começava junto, terminava ~5 s antes do
bipe final, e nada no Inspector mostrava. O mesmo arquivo posto à mão vinha com 24 (DRT exportado
da timeline, Resolve 21.1). A regra é a do import do Resolve: a taxa do VÍDEO do arquivo; arquivo
só de áudio (WAV) = a do projeto (um WAV importado num projeto a 24 ganha FPS 24).

Os arquivos do teste são gerados aqui (ffmpeg), pequenos.
"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp.writer import build_drt  # noqa: E402
from media import fftools  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def gerar_video(destino: str, taxa: str) -> None:
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s=160x90:r={taxa}:d=2",
                    "-f", "lavfi", "-i", "sine=f=1000:d=2", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", destino], check=True, **fftools.SEM_JANELA)


def gerar_wav(destino: str) -> None:
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=1000:d=2",
                    "-ar", "48000", "-ac", "2", destino], check=True, **fftools.SEM_JANELA)


def taxa_do_audio(arquivo: str, taxa_timeline: float) -> float:
    seg = {"timeline_tc_in": "00:00:00:00", "timeline_tc_out": "00:00:01:00", "duration_frames": 24,
           "source_start_frames": 0, "source_fps": taxa_timeline, "clip_name": os.path.basename(arquivo),
           "track": 1, "is_gap": False, "is_transition": False, "is_effect": False, "is_audio": True,
           "speed_ratio": 1.0, "conform_ratio": 1.0, "relative_speed": 1.0, "motion_class": "native",
           "effects": [], "disabled": False,
           "media_ref": {"local_path": arquivo, "descriptor_type": "prproj", "source_fps": taxa_timeline}}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.drt")
        build_drt([seg], [{"segment_index": 0, "matched_path": arquivo}], p, timeline_name="x",
                  timeline_fps=taxa_timeline, timeline_start_frames=0, timeline_size=(1920, 1080))
        with zipfile.ZipFile(p) as z:
            txt = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if "SeqContainer" in n)
    m = re.search(r"<Sm2TiAudioClip\b.*?<MediaFrameRate>([0-9a-f]+)</MediaFrameRate>", txt, re.S)
    return round(struct.unpack("<d", bytes.fromhex(m.group(1))[:8])[0], 3) if m else None


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        v24, v25, wav = (os.path.join(d, n) for n in ("v24.mp4", "v25.mp4", "som.wav"))
        gerar_video(v24, "24")
        gerar_video(v25, "25")
        gerar_wav(wav)
        print("── áudio dentro de vídeo: a taxa do vídeo do arquivo ──")
        ok("mp4 a 24 numa timeline a 24 (o som da referência do PRODUCAO_B): 24, não o 23,976 do molde",
           taxa_do_audio(v24, 24.0), 24.0)
        ok("mp4 a 24 numa timeline a 23,976: continua 24 (é a taxa do ARQUIVO)", taxa_do_audio(v24, 24000 / 1001), 24.0)
        ok("mp4 a 25 numa timeline a 24: 25", taxa_do_audio(v25, 24.0), 25.0)
        print("── só áudio (WAV): a taxa da timeline ──")
        ok("WAV numa timeline a 24: 24", taxa_do_audio(wav, 24.0), 24.0)
        ok("WAV numa timeline a 23,976: 23,976 (a exata, 24000/1001)", taxa_do_audio(wav, 24000 / 1001), 23.976)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
