"""O andamento do "montando a timeline": uma barra REAL, não a que só gira (2026-10-04).

Rodar:

    .venv/bin/python tests/test_andamento_drt.py        (Windows: .venv-win/Scripts/python)

Pedido do autor: o "montando a timeline" do PRODB não é rápido, nem no Mac nem no Windows, e a
barra só girava. O `build_drt` agora chama `andamento(feitos, total, atual, detalhe)` a cada arquivo
do media pool (onde moram as sondagens do ffprobe) e a cada plano da timeline; o serviço o liga a
`_etapa("montando", …)`. Este teste trava o contrato: a contagem só sobe, o total não muda no meio,
termina em feitos = total, e cada passo diz o arquivo e o que está sendo escrito.
"""

from __future__ import annotations

import os
import sys
import tempfile
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


def seg(trilha, ini, dur, arquivo, audio=False):
    return {"timeline_tc_in": f"00:00:{ini // 24:02d}:{ini % 24:02d}",
            "timeline_tc_out": f"00:00:{(ini + dur) // 24:02d}:{(ini + dur) % 24:02d}",
            "duration_frames": dur, "source_start_frames": 0, "source_fps": 24.0,
            "speed_ratio": 1.0, "relative_speed": 1.0, "conform_ratio": 1.0, "effects": [],
            "track": trilha, "is_audio": audio, "is_gap": False, "is_transition": False,
            "is_effect": False, "clip_name": os.path.basename(arquivo),
            "media_ref": {"local_path": arquivo}}


def main() -> int:
    print("── o andamento do build_drt ──")
    base = "C:/x/" if os.name == "nt" else "/x/"
    a, b, w = base + "A001.mov", base + "A002.mov", base + "SOM.wav"
    # 3 planos de vídeo (2 arquivos) + 2 de som (1 arquivo): pool = 3 arquivos, timeline = 5 planos
    segs = [seg(1, 0, 48, a), seg(1, 48, 48, b), seg(1, 96, 48, a),
            seg(1000, 0, 96, w, audio=True), seg(1001, 0, 96, w, audio=True)]
    offline = {a: {"nb": 500, "fps": 24.0, "tc": "01:00:00:00"},
               b: {"nb": 500, "fps": 24.0, "tc": "02:00:00:00"},
               w: {"audio_sr": 48000, "audio_canais": 2, "nb": 500, "fps": 24.0}}
    chamadas = []
    with tempfile.TemporaryDirectory() as d:
        build_drt(segs, [{"segment_index": i, "matched_path": s["media_ref"]["local_path"]}
                         for i, s in enumerate(segs)], os.path.join(d, "a.drt"),
                  timeline_name="a", timeline_fps=24.0, offline=offline,
                  andamento=lambda *x: chamadas.append(x))
    totais = {t for _f, t, _a, _d in chamadas}
    ok("o total é um só do começo ao fim: 3 arquivos do pool + 5 planos", totais, {8})
    feitos = [f for f, _t, _a, _d in chamadas]
    ok("a contagem só sobe", feitos == sorted(feitos), True)
    ok("começa em 0 e termina em feitos = total", (feitos[0], feitos[-1]), (0, 8))
    ok("cada passo diz o arquivo e o que está sendo escrito",
       all(at and det for _f, _t, at, det in chamadas), True)
    ok("o último é a gravação do DRT", "DRT" in chamadas[-1][3], True)
    ok("o pool vem antes da timeline",
       [det.split(":")[0] for _f, _t, _a, det in chamadas[:-1]],
       ["media pool"] * 3 + ["timeline"] * 5)

    print("── sem andamento, nada muda ──")
    with tempfile.TemporaryDirectory() as d:
        build_drt(segs[:1], [{"segment_index": 0, "matched_path": a}], os.path.join(d, "b.drt"),
                  timeline_name="b", timeline_fps=24.0, offline=offline)
        ok("sem o parâmetro (o caminho do Avid antigo), o DRT é gravado do mesmo jeito",
           os.path.isfile(os.path.join(d, "b.drt")), True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
