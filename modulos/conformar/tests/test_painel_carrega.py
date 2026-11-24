"""O painel CARREGA sem erro de JavaScript, no Media Composer e no Resolve.

Rodar:

    .venv-win/Scripts/python tests/test_painel_carrega.py

## Por que este teste existe

Nenhum outro teste EXECUTA o `painel.js`: o `test_painel_chrome80` e o `test_xss_painel` leem o
texto. Na revisão de 2026-09-28, uma variável (`atComparando`) lida pelo `irParaModo` do boot mas
declarada com `let` mais abaixo no arquivo faria o painel do Resolve quebrar AO ABRIR
("Cannot access before initialization") — `node --check` não pega isso. Aqui o arquivo roda num
DOM falso (`painel_boot.js`) que aceita tudo; o que sobra são os erros do próprio JavaScript.
Precisa do `node` no PATH (sem ele, o teste diz que pulou e sai 0).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PAINEL = RAIZ / "plugins" / "media-composer" / "servico" / "ui" / "painel.js"
BOOT = Path(__file__).resolve().parent / "painel_boot.js"


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("node não encontrado — teste pulado")
        return 0
    falhas = []
    for nle in ("mc", "resolve"):
        r = subprocess.run([node, str(BOOT), str(PAINEL), nle], capture_output=True, encoding="utf-8",
                           timeout=60)
        saida = (r.stdout or "") + (r.stderr or "")
        certo = "carregou" in saida and "sem erros" in saida
        print(f"  {'ok  ' if certo else 'FALHA'} o painel carrega com nle={nle}")
        if not certo:
            falhas.append(f"nle={nle}: {saida.strip()[:400]}")
    print(f"\n{2 - len(falhas)}/2 casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
