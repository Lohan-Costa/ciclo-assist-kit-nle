r"""Regera o `requirements.lock` a partir do ambiente que roda hoje.

    .venv-win\Scripts\python tools/lock.py      (Windows)
    .venv/bin/python tools/lock.py              (macOS)

⚠️⚠️ **Existe para o lock NÃO ser gerado por redirecionamento do shell**, e as duas
razões foram pagas com defeito real (2026-08-16):

1. **PowerShell 5.1 grava BOM e comeu um caractere.** O `>` do PowerShell produziu um
   `\r` solto no meio de um comentário, que engoliu a letra seguinte: a linha deixou de
   começar por `#`, o pip tentou lê-la como requisito e o arquivo virou **não-instalável**.
   O defeito só apareceu quando alguém tentou usá-lo — o arquivo *parecia* certo.

2. **O `pip` decodifica requirements com a CODEPAGE DO SISTEMA**, não UTF-8, quando não
   há BOM. Um `⚠️` em comentário carrega o byte `0x8F`, que é **indefinido em cp1252** →
   `UnicodeDecodeError` e nenhuma instalação. (Um `é` sobrevive porque em cp1252 vira
   mojibake em vez de erro — ou seja, `requirements.txt` funciona **por sorte**.)

⭐ Por isso o cabeçalho gerado aqui é **ASCII puro**. É a mesma regra que este projeto já
aplica ao `.ps1` gerado, e pela mesma razão: arquivo lido por máquina não carrega prosa
acentuada. A explicação vive aqui, no código que o gera.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

CABECALHO = """\
# requirements.lock - versoes EXATAS do ambiente que roda hoje.
#
# ASCII PURO de proposito: o pip decodifica este arquivo com a codepage do sistema
# quando nao ha BOM, e um caractere fora do ASCII pode torna-lo ILEGIVEL no Windows.
# A explicacao completa esta em tools/lock.py, que gera este arquivo.
#
# Instalar:  pip install -r requirements.lock
# Regerar :  python tools/lock.py     (NUNCA com `>` do PowerShell - ver tools/lock.py)
#
# Guia de Desenvolvimento Seguro, secao 4: lockfile e' obrigatorio, e nenhuma versao
# publicada ha menos de 3 dias deve ser adotada (quarentena de cadeia de suprimentos).
#
# requirements.txt continua sendo a lista LEGIVEL (o que se pediu e por que);
# este e' o que se INSTALA.
"""


def main() -> int:
    congelado = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
        capture_output=True, text=True, check=True).stdout
    linhas = sorted(l.strip() for l in congelado.splitlines() if l.strip())

    fora = [l for l in linhas if not l.isascii()]
    if fora:                      # nome de pacote nao-ASCII nao existe, mas nao custa
        print("nomes nao-ASCII no freeze:", fora, file=sys.stderr)
        return 1

    alvo = RAIZ / "requirements.lock"
    with open(alvo, "w", encoding="ascii", newline="\n") as fh:
        fh.write(CABECALHO + "\n".join(linhas) + "\n")
    print(f"{alvo.name}: {len(linhas)} pacotes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
