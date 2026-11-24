"""Todo id que o `painel.js` pede existe — no `painel.html` ou num `id="…"` que o próprio JS monta (banco, B048).

Rodar:  .venv/bin/python tests/test_painel_ids.py        (Windows: .venv-win/Scripts/python)

O `test_painel_carrega` roda o painel num DOM falso que ACEITA TUDO: um `el("x")` cujo `x` sumiu do HTML passa verde
e, na tela, o `null.addEventListener` mata o painel inteiro (foi assim no Ciclo Assist). Esta guarda lê o texto: as
três formas de acesso do código — `el("x")`, `getElementById("x")`, `querySelector("#x")` — contra os ids declarados.
O mesmo painel serve o MC, o Resolve (a casca carrega o `painel.html` servido) e o Premiere. Provada por mutação: um
id plantado tem de reprovar (2026-10-28: 296 ids pedidos, nenhum faltando).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "plugins" / "media-composer" / "servico" / "ui"

_DECLARA = re.compile(r"""\bid\s*=\s*\\?["']([A-Za-z_][\w-]*)""")
_DECLARA_JS = re.compile(r"""\.id\s*=\s*["']([\w-]+)""")
_PEDE = (re.compile(r"""(?:\bel|getElementById)\(\s*["']([\w-]+)["']\s*\)"""),
         re.compile(r"""querySelector(?:All)?\(\s*["']#([\w-]+)"""))


def faltando(js: str, html: str) -> list[str]:
    declarados = set(_DECLARA.findall(html + js)) | set(_DECLARA_JS.findall(js))
    pedidos = {i for rx in _PEDE for i in rx.findall(js)}
    return sorted(pedidos - declarados)


def main() -> int:
    js = (UI / "painel.js").read_text(encoding="utf-8")
    html = (UI / "painel.html").read_text(encoding="utf-8")
    falhas = []
    f = faltando(js, html)
    print(f"  {'ok  ' if not f else 'FALHA'} todo id pedido pelo painel.js existe" + (f": faltam {f}" if f else ""))
    if f:
        falhas.append(f"ids sem declaração: {f}")
    for plantado in ('el("idPlantadoNoTeste")', 'document.querySelector("#idPlantadoNoTeste")'):
        pega = faltando(js + f"\n{plantado};\n", html) == sorted(set(f) | {"idPlantadoNoTeste"})
        print(f"  {'ok  ' if pega else 'FALHA'} a guarda reprova o id plantado: {plantado}")
        if not pega:
            falhas.append(f"a guarda não pegou {plantado}")
    print(f"\n{3 - len(falhas)}/3 casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
