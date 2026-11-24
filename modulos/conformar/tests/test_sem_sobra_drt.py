"""Transição sem mídia depois do fim do plano A: o DRT avisa e marca (decisão do autor, 2026-10-29; banco, B058).

Rodar:  .venv/bin/python tests/test_sem_sobra_drt.py        (Windows: .venv-win/Scripts/python)

MEDIDO no Resolve Studio 19.1.4.11 (Windows, render): um dissolve de 20 quadros no corte cuja cauda de A passa do
último quadro do arquivo importa normal, mas o RENDER falha no corte ("Full resolution media not found"). Sem sobra em B
o Resolve segura o 1º quadro de B e renderiza. A edição não muda: o plano A ganha marcador vermelho e a tela conta.
Os três casos da bancada, sem o Resolve: A e B de 500 quadros, dissolve de 20 com o corte no meio.
"""
from __future__ import annotations

import os
import sys
import tempfile
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
        falhas.append(rotulo)
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def montar(a_src: int, b_src: int, marcar: bool = True) -> dict:
    base = "C:/x/" if os.name == "nt" else "/x/"
    a, b = base + "A.mov", base + "B.mov"
    sa = seg(1, 0, 48, a)
    sa["source_start_frames"] = a_src
    t = seg(1, 38, 20, a)
    t.update({"is_transition": True, "cutpoint": 10, "clip_name": "Dissolve", "media_ref": {}})
    sb = seg(1, 48, 48, b)
    sb["source_start_frames"] = b_src
    off = {a: {"nb": 500, "fps": 24.0, "tc": "01:00:00:00"}, b: {"nb": 500, "fps": 24.0, "tc": "02:00:00:00"}}
    casados = [{"segment_index": 0, "matched_path": a, "offline": True},
               {"segment_index": 2, "matched_path": b, "offline": True}]
    with tempfile.TemporaryDirectory() as d:
        return build_drt([sa, t, sb], casados, os.path.join(d, "t.drt"), timeline_name="T", timeline_fps=24.0,
                         offline=off, marcar=marcar, timeline_size=(1920, 1080))


def main() -> int:
    print("── transição sem sobra no DRT ──")
    r = montar(100, 100)
    ok("com sobra nos dois lados: nada a avisar", (r["transicoes_sem_sobra"], r["marcadores"]), (0, 0))
    r = montar(100, 0)
    ok("sem sobra em B: o Resolve segura o 1º quadro — não avisa", r["transicoes_sem_sobra"], 0)
    r = montar(452, 100)
    ok("sem sobra em A (o plano acaba no último quadro): conta 1 e marca o plano", (r["transicoes_sem_sobra"],
                                                                                   r["marcadores"]), (1, 1))
    ok("o aviso diz o que acontece e o que fazer", any("render do Resolve falha" in a for a in r["avisos"]), True)
    r = montar(445, 100)
    ok("sobra de 3 quando a transição pede 10: avisa", r["transicoes_sem_sobra"], 1)
    r = montar(442, 100)
    ok("sobra exata de 10: não avisa", r["transicoes_sem_sobra"], 0)
    r = montar(452, 100, marcar=False)
    ok("com os marcadores desligados nas opções: a tela ainda conta", (r["transicoes_sem_sobra"], r["marcadores"]),
       (1, 0))
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
