"""O serviço fala UTF-8 pelo stdout/pipe também no Windows (banco, bugs-do-mundo-real B100).

Rodar:

    .venv/bin/python tests/test_console_utf8.py        (Windows: .venv-win/Scripts/python)

Quem lê o stdout do serviço lê UTF-8: o app (`lib.rs::liberar_porta`, `from_utf8_lossy`), o
`montar_motor.py` (`--conferir-pacote`) e o `escolher.py` (`--dialogo-win`). No Windows, sem nada
fixado, o Python escreve no pipe na codepage do sistema (cp1252): MEDIDO 2026-10-09 (Win11, Python
3.12.5) — o `--liberar-porta` com "Área" saía em cp1252 (lixo no app) e com "テイク" morria com
UnicodeEncodeError. O ponto de entrada do PRODUTO (`main.main`) fixa UTF-8; o atualizar.ps1 fixar
PYTHONUTF8 não basta, porque o app instalado não passa por ele.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVICO = RAIZ / "plugins" / "media-composer" / "servico"

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


# um "serviço" de mentira: o main de verdade com o liberar_gateway trocado por um que devolve nomes
# fora do ASCII (a pasta do usuário, um processo) — o que o app lê é o stdout dele
RODAR = r"""
import sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import plataforma
plataforma.liberar_gateway = lambda todos=False: {"liberados": [{"pasta": "C:/Users/Área テイク"}]}
import main
sys.exit(main.main(["--liberar-porta"]))
"""


def main() -> int:
    amb = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    r = subprocess.run([sys.executable, "-c", RODAR, str(SERVICO), str(RAIZ / "motor")],
                       capture_output=True, env=amb, timeout=120)
    ok("o --liberar-porta termina sem erro com nome fora do cp1252", r.returncode, 0)
    linha = next((x for x in r.stdout.decode("utf-8", "replace").splitlines() if x.startswith("{")), "")
    try:
        lido = json.loads(linha)["liberados"][0]["pasta"]
    except (ValueError, KeyError, IndexError):
        lido = None
    ok("⭐ o app lê o JSON em UTF-8 com o nome inteiro (acento e japonês)", lido, "C:/Users/Área テイク")
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
