"""A sequência gravada no Avid: começa no TC da ORIGEM (B062) e a trilha vazia entra vazia (B051) — 2026-10-28.

Rodar:  .venv/bin/python tests/test_inicio_avb.py        (Windows: .venv-win/Scripts/python)

O Premiere → Avid gravava a trilha de TC SEMPRE em 01:00:00:00 (`tc.start = 3600 × fps`), embora o leitor do .prproj
traga o início (`MZ.ZeroPoint`, ausente = 00:00:00:00): o mesmo clipe com dois TCs. Agora `build_avb(inicio=…)`; sem
início, 01:00:00:00 como antes. E só as trilhas com plano entravam, numeradas em sequência: com a V2 vazia a V3
descia para a V2. Sobre o molde de vídeo embarcado (a bin de mídia), sem o MC.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import avb  # noqa: E402
from avb_export import media_bin, translate  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def gravar(trilhas=(1,), inicio=None):
    """A sequência montada (um plano de 48 quadros em cada trilha pedida): `(starts do TC, [(V, componentes)])`."""
    arq, clip, _ = media_bin.load_bundled_templates()[("video", "h264")]
    with avb.open(arq) as f:
        hx = next(x for x in f.content.mobs if x.mob_type == "MasterMob" and x.name == clip).mob_id.bytes_le.hex()
    segs = [{"track": tr, "timeline_tc_in": "00:00:00:00", "timeline_tc_out": "00:00:02:00", "duration_frames": 48,
             "disabled": False, "source_start_frames": 0, "source_fps": 23.976, "speed_ratio": 1.0,
             "relative_speed": 1.0, "effects": [], "is_audio": False, "is_gap": False, "is_transition": False,
             "is_effect": False, "clip_name": clip, "mob_id": "k"} for tr in trilhas]
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "s.avb")
        translate.build_avb(segs, 23.976, arq, out, "SEQ", origem="premiere", mob_hex={"k": hx}, inicio=inicio)
        with avb.open(out) as f:
            comp = next(x for x in f.content.mobs if x.name == "SEQ")
            tc = [t.component.start for t in comp.tracks if type(t.component).__name__ == "Timecode"]
            v = [(t.index, "SourceClip" in [type(c).__name__ for c in t.component.components])
                 for t in comp.tracks if t.media_kind == "picture"]
            return tc, v


def inicio_gravado(inicio) -> list:
    return gravar(inicio=inicio)[0]


def main() -> int:
    ok("sem início: 01:00:00:00 (86.400 a 24)", inicio_gravado(None), [86400])
    ok("o início da origem 10:00:00:00 vai à trilha de TC", inicio_gravado(10 * 3600 * 24), [864000])
    ok("00:00:00:00 (ZeroPoint ausente no Premiere) é início válido", inicio_gravado(0), [0])
    ok("o plano entra na V1", gravar()[1], [(1, True)])
    ok("B051: com a V2 vazia, a V3 continua V3 (e a V2 entra vazia)", gravar((1, 3))[1], [(1, True), (2, False), (3, True)])
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
