"""A transição cujo vizinho NÃO encosta nela é fade, não dissolve — mesmo sem o segmento de vazio (2026-10-19).

Rodar:

    .venv/bin/python tests/test_transicao_sem_vazio.py        (Windows: .venv-win/Scripts/python)

O caso: PRODUCAO-A (`PRODA_RELINKER_ALTA.aaf`) pela janela do app no Resolve 19.1.4. O AAF do Avid não traz o filler
da V3; o título com fade-out (00:00:30:15–00:00:41:20) e o próximo plano da V3 (00:06:37:23, 86 quadros) viravam um
cross-dissolve, e o `start_ovr` puxava o plano para o corte: 8.643 quadros cobrindo a V1 e a V2 (conferência de
bancada: 67 de 110, tudo errado de 01:00:59 a 01:06:37).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from drp.writer import _transition_overrides  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: veio {obtido!r}, esperava {esperado!r}")


def seg(tc, dur, **k):
    return {"track": 3, "timeline_tc_in": tc, "duration_frames": dur, **k}


def main() -> int:
    print("── PRODUCAO-A: título com fade-out e o próximo plano seis minutos depois ──")
    segs = [seg("00:00:30:15", 40, is_transition=True, cutpoint=10),
            seg("00:00:30:15", 269, is_effect=True, clip_name="Avid Titler+ Legacy"),
            seg("00:00:40:04", 40, is_transition=True, cutpoint=30),
            seg("00:06:37:23", 86, clip_name="a001_03170334_C004")]
    dur, ini, entrada, depois, fade_antes, fade_depois = _transition_overrides(segs, {1: {}, 3: {}})
    ok("⭐ o plano distante NÃO ganha início nem duração novos", (ini.get(3), dur.get(3), entrada.get(3)), (None, None, None))
    ok("…não há dissolve título → plano", depois, {})
    ok("o fim do título vira fade-out", sorted(fade_depois), [1])
    ok("o começo do título vira fade-in", sorted(fade_antes), [1])

    print("── o dissolve de verdade continua dissolve ──")
    segs = [seg("00:00:00:00", 100, clip_name="A"),
            seg("00:00:03:18", 20, is_transition=True, cutpoint=10),
            seg("00:00:04:04", 100, clip_name="B")]
    dur, ini, entrada, depois, _fa, _fd = _transition_overrides(segs, {0: {}, 2: {}})
    ok("A e B encostados no corte: dissolve", (sorted(depois), ini.get(2)), ([0], 100))
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
