"""O par ESTÉREO do Avid no DRT: canal 1 à esquerda, canal 2 à direita (banco, B016; 2026-10-28).

Rodar:  .venv/bin/python tests/test_pan_estereo_drt.py        (Windows: .venv-win/Scripts/python)

O Avid entrega um WAV estéreo em duas trilhas mono (A1 = canal 1, A2 = canal 2). No DRT elas iam ao CENTRO e o estéreo
saía L = R. MEDIDO no Resolve 21.1 (Mac): WAV L 440 Hz / R 1000 Hz, render da timeline — antes os dois tons nos dois
lados; com o pan, esquerda 440 e direita 1000 (>100 dB de separação), igual ao gabarito do próprio Resolve
(`AudioPan` −100/+100 pela API + Export DRT: o pan mora no `EffectFiltersBA`, double LE no fim). ⛔ A forma do molde
já traz um `<EffectFiltersBA/>` vazio, que vencia o nosso se ficasse ao lado. Dual mono (o mesmo canal nas duas
trilhas) e arquivo mono seguem no centro.
"""
from __future__ import annotations

import os
import re
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))
sys.path.insert(0, str(RAIZ / "tests"))

from drp.writer import build_drt  # noqa: E402
from test_andamento_drt import seg  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def pans(canais: tuple[int, int], n_canais: int) -> list:
    v, w = "/x/V.mov", "/x/SOM.wav"
    vid = seg(1, 0, 48, v)
    a1 = seg(1, 0, 48, w, audio=True)
    a1.update({"track": 1, "canal_arquivo": canais[0]})
    a2 = seg(2, 0, 48, w, audio=True)
    a2.update({"track": 2, "canal_arquivo": canais[1]})
    off = {v: {"nb": 500, "fps": 24.0, "tc": "01:00:00:00"},
           w: {"audio_sr": 48000, "audio_canais": n_canais, "nb": 500, "fps": 24.0}}
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "p.drt")
        build_drt([vid, a1, a2], [{"segment_index": i, "matched_path": p, "offline": True} for i, p in enumerate((v, w, w))],
                  out, timeline_name="P", timeline_fps=24.0, offline=off, timeline_start_frames=86400,
                  timeline_size=(1920, 1080))
        with zipfile.ZipFile(out) as z:
            x = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
    fora = []
    for b in re.findall(r"<Sm2TiAudioClip.*?</Sm2TiAudioClip>", x, re.S):
        cheios = re.findall(r"<EffectFiltersBA>([0-9a-fA-F]+)</EffectFiltersBA>", b)
        vazios = len(re.findall(r"<EffectFiltersBA\s*/>", b))
        fora.append((struct.unpack("<d", bytes.fromhex(cheios[0])[-8:])[0] if cheios else None, vazios))
    return fora


def main() -> int:
    ok("estéreo (A1 = canal 1, A2 = canal 2): −100 e +100, sem o vazio do molde ao lado",
       pans((1, 2), 2), [(-100.0, 0), (100.0, 0)])
    ok("dual mono (o canal 1 nas duas): no centro", [p for p, _ in pans((1, 1), 2)], [None, None])
    ok("arquivo mono: no centro", [p for p, _ in pans((1, 1), 1)], [None, None])
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
