"""O plano CONGELADO no DRT: o mesmo quadro da fonte do começo ao fim (banco, B066; 2026-10-28).

Rodar:  .venv/bin/python tests/test_congelado_drt.py        (Windows: .venv-win/Scripts/python)

Antes, o writer não tinha caminho para o congelado: a `speed_ratio` 0 virava 1,0 e o plano ANDAVA a 100 % no Resolve
(a curva saía constante, igual à do plano normal). Agora ele vai pela curva da rampa com o mapa ACHATADO.
MEDIDO no Resolve 21.1 (Mac): mídia sintética testsrc2 (todo quadro diferente), render da timeline, cada quadro
renderizado casado com o quadro da fonte mais parecido — o congelado deu o quadro 100 nos 48 quadros (diferença 0,47
contra 3,35 do 101); na mesma timeline, normal, razão 2,0 (50 %), razão 0,5 (200 %) e reverso deram exatos.
Aqui, sem o Resolve: a curva gravada, avaliada como o Resolve avalia (o piso da reta entre keyframes).
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))
sys.path.insert(0, str(RAIZ / "tests"))

from drp.writer import build_drt  # noqa: E402
from test_andamento_drt import seg  # noqa: E402
from test_rampa_exata_drt import no_resolve, pontos  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def quadros_do_congelado(mapa) -> list[int]:
    a = "/x/A001.mov"
    normal = seg(1, 0, 48, a)
    fr = seg(1, 48, 48, a)
    fr.update({"speed_ratio": 0.0, "relative_speed": 0.0, "motion_effect_type": "freeze", "source_start_frames": 100,
               "source_offset_map": mapa})
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "c.drt")
        build_drt([normal, fr], [{"segment_index": i, "matched_path": a, "offline": True} for i in range(2)], out,
                  timeline_name="C", timeline_fps=24.0, offline={a: {"nb": 1000, "fps": 24.0, "tc": "01:00:00:00"}},
                  timeline_start_frames=86400, timeline_size=(1920, 1080))
        with zipfile.ZipFile(out) as z:
            x = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
    clip = re.findall(r"<Sm2TiVideoClip.*?</Sm2TiVideoClip>", x, re.S)[1]
    em = int(re.search(r"<In>(\d+)", clip).group(1))
    pts = pontos(re.search(r"<MediaTimemapBA>([0-9a-fA-F]*)</MediaTimemapBA>", clip).group(1))
    return sorted({no_resolve(pts, em + k, 24.0) for k in range(48)})


def main() -> int:
    ok("o congelado mostra só o quadro 100 nos 48 quadros", quadros_do_congelado([(0.0, 0.0), (48.0, 0.0)]), [100])
    # o leitor de bin, num clipe de 1 quadro, monta (0, 0) → (n, n / velocidade): o congelado o força plano
    ok("o mapa inclinado do leitor também congela", quadros_do_congelado([(0.0, 0.0), (48.0, 96.0)]), [100])
    ok("sem mapa (o congelado do AAF: velocidade 0)", quadros_do_congelado(None), [100])
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
