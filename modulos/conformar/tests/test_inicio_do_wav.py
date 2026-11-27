"""O início de um WAV (BWF `time_reference`) em quadros do projeto, como o Media Composer o grava.

Rodar:

    .venv/bin/python tests/test_inicio_do_wav.py        (Windows: .venv-win/Scripts/python)

⛔ Até 2026-11-25 a conta arredondava em quadros NOMINAIS (24) antes do pulldown e tirava UM quadro em metade dos WAVs
de gravador a 23,976 (achado na EDL do MC: o som da B30 do laboratório saía em 06:00:00:22, um quadro antes do Premiere).
Os números abaixo são do MC: os masters que ele mesmo linkou (bins da PRODUCAO-A, D02 e D04; os gabaritos de
2026-10-31) e o diálogo "Audio Start-Time Options".
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_export.clone_generic import inicio_exato_do_relogio  # noqa: E402

NTSC24, NTSC30 = 24000 / 1001, 30000 / 1001

# (rótulo, time_reference, taxa de amostras, edit_rate do projeto, start que o MC grava)
CASOS = [
    ("B30 do laboratório, 06:00:00:00 a 23,976 (o caso da EDL)", 1037836800, 48000, NTSC24, 518400),
    ("PRODUCAO-A 05-04 C4 P2-T001 (MC: 1040376; a conta velha dava 1040375)", 2082832752, 48000, NTSC24, 1040376),
    ("PRODUCAO-A 05-04 C4 P2-T002 (MC: 1055088)", 2112286176, 48000, NTSC24, 1055088),
    ("PRODUCAO-A 05-04 C4 P5-T001 (MC: 1151400)", 2305102800, 48000, NTSC24, 1151400),
    ("PRODUCAO-A 05-04 C4 P6-T002 (MC: 1335456)", 2673582912, 48000, NTSC24, 1335456),
    ("B31 T001, milésimo > 0,5 (MC: 1209552)", 2421523104, 48000, NTSC24, 1209552),
    ("gabarito 23,976, relógio 01:00:08 (MC: 86505)", 173184000, 48000, NTSC24, 86505),
    ("gabarito 24 (MC: 86592)", 173184000, 48000, 24.0, 86592),
    ("gabarito 25 (MC: 90200)", 173184000, 48000, 25.0, 90200),
    ("gabarito 29,97 (MC: 108131 — piso de 108131,87)", 173184000, 48000, NTSC30, 108131),
    ("diálogo do MC: relógio 10:00:00 a 23,98 → 09:59:24:00", 36000 * 48000, 48000, NTSC24, 863136),
]


def test_inicio_do_wav():
    falhas = []
    for rot, tr, sr, er, mc in CASOS:
        veio = math.floor(inicio_exato_do_relogio(tr, sr, er) + 1e-6)
        print(f"  {'✓' if veio == mc else '✗'} {rot}" + ("" if veio == mc else f"  — veio {veio}"))
        if veio != mc:
            falhas.append(rot)
    print(f"{len(CASOS) - len(falhas)}/{len(CASOS)} casos")
    assert not falhas, falhas


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        test_inicio_do_wav()
    except AssertionError:
        sys.exit(1)
