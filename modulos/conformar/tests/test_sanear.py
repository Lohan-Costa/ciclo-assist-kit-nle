"""O `sanear.py` (regra do autor, 2026-10-05: o público recebe só código, sem comentário nem docstring).

Rodar:

    .venv/bin/python tests/test_sanear.py        (Windows: .venv-win/Scripts/python)

Os casos que enganam um removedor de comentários: `//` dentro de string, de URL, de regex e de
template literal (com `${}` aninhado); `#` dentro de aspas no shell e no TOML; strings cruas e
lifetimes no Rust; a docstring que é o corpo inteiro (vira `pass`); e o que NÃO pode sair (shebang,
linha de codificação, linha em branco dentro de string de várias linhas). E as travas: tipo
desconhecido e programa alterado falham.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
if not (RAIZ / "sanear.py").is_file():
    print("PULADO — este é o artefato público (o sanear.py não vai nele)")
    raise SystemExit(0)

import sanear as S  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def _erro(f):
    try:
        f()
    except S.FalhaAoSanear:
        return "FalhaAoSanear"
    return None


def main() -> int:
    print("Python")
    py = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Módulo: o porquê de tudo."""

import os  # o sistema


def so_doc():
    """Só a docstring."""


class C:
    """Classe."""

    x = 1  # um

    def f(self):
        """Método."""
        # comentário sozinho

        texto = """linha 1

linha 3 # não é comentário"""
        return texto
'''
    r = S.sanear_python(py)
    ok("shebang e codificação ficam; comentário e docstring saem",
       ([x for x in r.splitlines() if x][:3]), ["#!/usr/bin/env python3", "# -*- coding: utf-8 -*-", "import os"])
    ok("⭐ função que era SÓ docstring ganha `pass`", "def so_doc():\n    pass" in r, True)
    ok("comentário no fim da linha sai, sem deixar espaço", "    x = 1\n" in r, True)
    ok("⭐ o `#` e a linha em branco DENTRO da string ficam",
       '"""linha 1\n\nlinha 3 # não é comentário"""' in r, True)
    ok("nada de docstring nem comentário sobrou",
       ("Classe" in r, "Método" in r, "porquê" in r, "sozinho" in r), (False, False, False, False))
    ok("idempotente", S.sanear_python(r), r)

    print("JavaScript")
    js = '''// cabeçalho
const url = "http://127.0.0.1:7823"; // a porta
const re = /^[\\\\/]{2}/.test(x) ? a / b : c; /* bloco */
const t = `a // b ${ x ? "//" : `${y} /* z */` } c`;
const d = (n / 2) / 3;
/* várias
   linhas */
function f() { return /\\/\\//g; }
'''
    r = S.sanear_codigo(js, "js")
    ok("⭐ `//` em string, regex e template literal (com ${} aninhado) fica", r, '''const url = "http://127.0.0.1:7823";
const re = /^[\\\\/]{2}/.test(x) ? a / b : c;
const t = `a // b ${ x ? "//" : `${y} /* z */` } c`;
const d = (n / 2) / 3;
function f() { return /\\/\\//g; }
''')

    print("CSS, Rust, HTML, XML")
    ok("CSS: `//` de URL não é comentário", S.sanear_codigo("a{b:url(http://x/y)} /* c */\n", "css"),
       "a{b:url(http://x/y)}\n")
    rs = '''//! módulo
/// doc
fn f<'a>(s: &'a str) -> char { let r = r#"a // b "x" "#; let c = '/'; /* um /* aninhado */ dois */ '"' }
'''
    ok("Rust: string crua, lifetime, char e bloco aninhado", S.sanear_codigo(rs, "rs"),
       '''fn f<'a>(s: &'a str) -> char { let r = r#"a // b "x" "#; let c = '/';  '"' }\n''')
    html = '<!-- topo -->\n<p>a</p>\n<script>\n// js\nconst a = "<!-- não -->";\n</script>\n'
    r = S.sanear_html(html)
    ok("HTML: comentário sai; o `<!--` dentro de string do script fica",
       ("topo" in r, "// js" in r, '"<!-- não -->"' in r), (False, False, True))
    ok("XML: comentário sai, árvore igual",
       S.sanear_xml('<?xml version="1.0"?>\n<!-- x -->\n<a b="1"><!-- y --><c/></a>\n'),
       '<?xml version="1.0"?>\n<a b="1"><c/></a>\n')

    print("shell, TOML, requirements")
    sh = '#!/bin/bash\n# topo\necho "a # b" # fim\necho ${#x} $#\n'
    ok("shell: `#` em aspas, `${#x}` e `$#` ficam", S.sanear_hash(sh, "sh"),
       '#!/bin/bash\necho "a # b"\necho ${#x} $#\n')
    ok("TOML: `#` em string fica", S.sanear_hash('# c\na = "x # y" # z\n', "toml"), 'a = "x # y"\n')

    print("as travas")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "x.weird").write_text("// segredo", encoding="utf-8")
        ok("⛔ tipo de arquivo desconhecido FALHA (allowlist de tipos)", _erro(lambda: S.sanear(d)),
           "FalhaAoSanear")
        (d / "x.weird").unlink()
        (d / "y.py").write_text('x = 1  # c\n', encoding="utf-8")
        S.sanear(d)
        ok("o artefato saneado passa na conferência", (d / "y.py").read_text(encoding="utf-8"), "x = 1\n")
        (d / "z.py").write_text("y = 2  # sobrou\n", encoding="utf-8")
        ok("⛔ comentário que sobrar FALHA na conferência", _erro(lambda: S.conferir(d)), "FalhaAoSanear")
    ok("⛔ regex sem fim FALHA (em vez de engolir código)",
       _erro(lambda: S.sanear_codigo("a = (/x\nb = 1;\n", "js")), "FalhaAoSanear")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
