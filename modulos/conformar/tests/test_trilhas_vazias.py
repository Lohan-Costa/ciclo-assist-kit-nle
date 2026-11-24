"""A numeração das trilhas da origem fica no DRT, inclusive as vazias (2026-10-04).

Rodar:

    .venv/bin/python tests/test_trilhas_vazias.py        (Windows: .venv-win/Scripts/python)

⛔ Visto no Resolve 19 (PRODB `…ROLO03_COM_REF`): a V7 do Premiere não tinha clipe que entrasse
no DRT e o writer só criava trilha para os números com clipe — a referência (V8) virou V7. A
conferência (`trilha_referencia`), o Fusion e os Compound Clips acham o clipe pelo NÚMERO da trilha
da origem; e o editor perdia o layout. Agora a trilha vazia entra vazia.
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

from drp.writer import build_drt  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def seg(trilha, arquivo, **extra):
    return {"timeline_tc_in": "00:00:00:00", "timeline_tc_out": "00:00:02:00", "duration_frames": 48,
            "source_start_frames": 0, "source_fps": 24.0, "speed_ratio": 1.0, "relative_speed": 1.0,
            "conform_ratio": 1.0, "effects": [], "track": trilha, "is_audio": False, "is_gap": False,
            "is_transition": False, "is_effect": False, "clip_name": os.path.basename(arquivo),
            "media_ref": {"local_path": arquivo}, **extra}


def trilhas(drt: str) -> list[tuple[int, int]]:
    """[(nº de clipes, Flags)] de cada trilha de vídeo, de baixo para cima."""
    with zipfile.ZipFile(drt) as z:
        seq = next(z.read(n).decode("utf-8") for n in z.namelist() if "SeqContainer" in n)
    vtv = re.search(r"<VideoTrackVec>.*?</VideoTrackVec>", seq, re.S).group(0)
    fora = []
    for t in re.findall(r"<Sm2TiTrack\b.*?</Sm2TiTrack>", vtv, re.S):
        itens = re.search(r"<Items>(.*?)</Items>", t, re.S).group(1)
        flags = re.search(r"<Flags>(\d+)</Flags>", re.sub(r"<Items>.*?</Items>", "", t, flags=re.S))
        fora.append((itens.count("<Sm2TiVideoClip"), int(flags.group(1)) if flags else 0))
    return fora


def main() -> int:
    print("── a trilha vazia no meio não some ──")
    base = "C:/x/" if os.name == "nt" else "/x/"
    a, ref = base + "A001.mov", base + "REF.mp4"
    offline = {a: {"nb": 500, "fps": 24.0, "tc": "01:00:00:00"}, ref: {"nb": 500, "fps": 24.0, "tc": "00:00:00:00"}}
    # V1 com plano, V2 só com um clipe DESLIGADO (não entra), V3 vazia, V4 = referência desligada
    segs = [seg(1, a), seg(2, a, disabled=True), seg(4, ref, referencia=True, trilha_desligada=True)]
    with tempfile.TemporaryDirectory() as d:
        drt = os.path.join(d, "t.drt")
        build_drt(segs, [{"segment_index": 0, "matched_path": a}, {"segment_index": 1, "matched_path": a},
                         {"segment_index": 2, "matched_path": ref}],
                  drt, timeline_name="t", timeline_fps=24.0, offline=offline)
        t = trilhas(drt)
    ok("quatro trilhas de vídeo, como na origem (antes: duas)", len(t), 4)
    ok("V2 e V3 entram vazias", (t[1][0], t[2][0]), (0, 0))
    ok("a referência continua na V4, com o clipe, desligada (Flags 2)", t[3], (1, 2))
    ok("a V1 com o plano", t[0][0], 1)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
