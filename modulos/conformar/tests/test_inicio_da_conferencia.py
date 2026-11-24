"""A conferência começa onde o DRT começa a timeline (regressão de 2026-11-19).

Rodar:

    .venv-win/Scripts/python tests/test_inicio_da_conferencia.py

Desde f8f80c8 o `build_drt` põe a timeline no TC da ORIGEM (`timeline_start_frames`); o plano da conferência dos
protocolos Avid/AAF/Carta continuava fixo em 01:00:00:00. O AAF do Premiere 23.2 do B22 começa em 0: a timeline nasceu
em 00:00:00:00 e os 6 pontos pediam a agulha em 01:00:00:01 — 0/6, "o programa não exportou o quadro" (era 6/6).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import sessao_receber as SR  # noqa: E402
from conferencia import _tc  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {obtido!r}"[:150])
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── a mesma regra do drp.writer ──")
    ok("origem em 0 (AAF do Premiere) começa em 0", SR._inicio_da_timeline({"timeline_start_frames": 0}, 24), 0)
    ok("sem TC da origem, 01:00:00:00", SR._inicio_da_timeline({}, 24), 86400)
    ok("sem TC da origem a 25, 01:00:00:00", SR._inicio_da_timeline({"timeline_start_frames": None}, 25), 90000)
    ok("o TC da sequência do Avid vale como veio", SR._inicio_da_timeline({"timeline_start_frames": 90010}, 25), 90010)
    ok("o 1º ponto do B22 cai em 00:00:00:01", _tc(SR._inicio_da_timeline({"timeline_start_frames": 0}, 24) + 1, 24),
       "00:00:00:01")

    print("── ninguém volta a fixar 01:00:00:00 no plano ──")
    fonte = (RAIZ / "plugins" / "media-composer" / "servico" / "sessao_receber.py").read_text(encoding="utf-8")
    ok("o plano usa _inicio_da_timeline", '{"inicio": inicio,' in fonte and '"inicio": 3600 * nominal' not in fonte,
       True)
    escritor = (RAIZ / "motor" / "drp" / "writer.py").read_text(encoding="utf-8")
    ok("o writer segue com a regra que o plano imita",
       "_TIMELINE_OFFSET_FRAMES = max(0, int(timeline_start_frames))" in escritor, True)

    print(f"\n{casos - len(falhas)}/{casos} casos ok")
    for f in falhas:
        print("  ✗", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
