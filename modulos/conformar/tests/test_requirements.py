"""Os requirements decodificam no pip do Windows (banco, bugs-do-mundo-real B046).

Rodar:

    .venv/bin/python tests/test_requirements.py        (Windows: .venv-win/Scripts/python)

O pip 24.x lê o requirements pela codepage do sistema (cp1252) quando não há BOM nem linha de
codificação (PEP 263) nas 2 primeiras linhas. Medido 2026-10-09 (Win11, Python 3.12.5, pip 24.2 de
fábrica): o `requirements.txt` antigo + "# 🐍" → `pip install -r` sai 2 (charmap); com
`# -*- coding: utf-8 -*-` na 1ª linha, instala. Hoje não há emoji, mas o travessão e os acentos já
viravam lixo — um byte que o cp1252 não tem (0x81, 0x8D, 0x8F, 0x90, 0x9D) derruba a instalação.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CODING = re.compile(rb"^#.*coding[:=]\s*([-\w.]+)")

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def main() -> int:
    arquivos = sorted(p for p in RAIZ.rglob("requirements*")
                      if p.suffix in (".txt", ".lock") and not any(x.startswith(".venv") or x == "node_modules"
                                                                  for x in p.relative_to(RAIZ).parts))
    ok("há requirements para conferir", len(arquivos) >= 2, True)
    for p in arquivos:
        b = p.read_bytes()
        try:
            b.decode("ascii")
            ok(f"{p.relative_to(RAIZ)}: ASCII puro", True, True)
            continue
        except UnicodeDecodeError:
            pass
        linhas = b.splitlines()[:2]
        m = next((CODING.match(x) for x in linhas if CODING.match(x)), None)
        ok(f"{p.relative_to(RAIZ)}: não-ASCII com a linha de codificação nas 2 primeiras linhas",
           m.group(1).decode().lower() if m else None, "utf-8")
        ok(f"{p.relative_to(RAIZ)}: decodifica em UTF-8", b.decode("utf-8", "strict") is not None, True)
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
