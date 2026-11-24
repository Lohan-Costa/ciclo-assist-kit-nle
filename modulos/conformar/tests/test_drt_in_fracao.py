"""O In com FRAÇÃO no DRT e o trecho do original no caminho Premiere → Resolve (BL09, Resolve 21.1, 2026-11-23).

    .venv/bin/python tests/test_drt_in_fracao.py

- Fonte de OUTRA taxa: o quadro 364 de um 29,97 numa timeline de 23,976 = In 291,2. Inteiro, o Resolve mostrava
  floor(291 × 1,25) = 363 (medido pela imagem). O DRT nativo grava `291|<f64 LE da fração>` — o writer também.
- Mesma taxa: o In continua inteiro.
- `prproj_para_drt._deslocar_trecho`: o In do render anda o deslocamento na unidade do segmento.
"""
from __future__ import annotations

import math
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


def _ins() -> list[str]:
    a, b = "/x/A002C001.mov", "/x/B001C007.mov"
    outra = seg(1, 0, 40, a)
    outra.update({"source_start_frames": 364, "source_fps": 30000 / 1001, "speed_ratio": 0.8,
                  "relative_speed": 1.0, "conform_ratio": 0.8})
    mesma = seg(1, 40, 40, b)
    mesma["source_start_frames"] = 47
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "f.drt")
        build_drt([outra, mesma], [{"segment_index": i, "matched_path": p, "offline": True}
                                   for i, p in enumerate((a, b))], out,
                  timeline_name="F", timeline_fps=24000 / 1001,
                  offline={a: {"nb": 599, "fps": 30000 / 1001, "tc": "16:58:50;00"},
                           b: {"nb": 288, "fps": 24000 / 1001, "tc": "13:00:00:00"}},
                  timeline_start_frames=86400, timeline_size=(1920, 1080))
        with zipfile.ZipFile(out) as z:
            x = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
    return [re.search(r"<In>([^<]*)</In>", c).group(1) for c in re.findall(r"<Sm2TiVideoClip.*?</Sm2TiVideoClip>", x, re.S)]


def main() -> int:
    print("── o In com fração ──")
    ins = _ins()
    inteiro, _, fr = ins[0].partition("|")
    valor = int(inteiro) + (struct.unpack("<d", bytes.fromhex(fr))[0] if fr else 0.0)
    ok("outra taxa: o In leva a fração (291|…)", (inteiro, bool(fr)), ("291", True))
    ok("o Resolve mostra floor(In × 1,25) = 364", math.floor(valor * 1.25), 364)
    ok("mesma taxa: In inteiro", ins[1], "47")

    print("── o trecho no caminho Premiere → Resolve ──")
    from tools.prproj_para_drt import _deslocar_trecho
    s = {"source_start_frames": 5, "source_fps": 30000 / 1001}
    ok("relido na taxa do original: anda 359", (_deslocar_trecho(s, {"desloc_s": 359 * 1001 / 30000}),
                                                s["source_start_frames"]), (True, 364))
    s = {"source_start_frames": 4, "source_fps": 24000 / 1001}
    ok("mesma taxa: anda 60", (_deslocar_trecho(s, {"desloc_s": 2.5025}), s["source_start_frames"]), (True, 64))
    ok("sem trecho: nada", _deslocar_trecho({"source_start_frames": 4}, None), False)
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
