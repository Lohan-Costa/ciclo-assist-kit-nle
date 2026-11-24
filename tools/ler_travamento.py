"""Ler um dump de travamento da janela: a pilha de cada thread, com os nomes das funções.

    python tools/ler_travamento.py              # o dump mais recente de logs/travamentos/
    python tools/ler_travamento.py X.dmp        # um dump escolhido
    python tools/ler_travamento.py --tudo       # todas as threads (o padrão é a da janela, a 0)
    python tools/ler_travamento.py --pendentes  # os que ninguém leu (o painel avisa deles ao abrir)

Ler um dump o marca como LIDO (`<dump>.lido`), e ele sai do aviso do painel.

O dump é gravado pelo vigia do serviço (`cicloassist/servico/travamento.py`) quando a janela
do app fica presa > 8 s; ao lado dele, numa pasta com o mesmo nome, vão o `.exe` e o `.pdb`
que estavam rodando — sem eles, as funções do app saem como `cicloassist+0x1ef190`.

Precisa do WinDbg (`winget install Microsoft.WinDbg`): usa o `cdb.exe` que vem nele. Os
símbolos do Windows vêm do servidor da Microsoft e ficam guardados em
`%LOCALAPPDATA%\\simbolos` (a primeira leitura demora; as seguintes, não).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def cdb() -> str:
    # ⚠️ `WindowsApps` não se deixa LISTAR (glob vazio), mas o caminho do pacote se pergunta.
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(Get-AppxPackage Microsoft.WinDbg).InstallLocation"],
                       capture_output=True, text=True)
    pasta = (r.stdout or "").strip().splitlines()[-1:] or [""]
    exe = Path(pasta[0]) / "amd64" / "cdb.exe"
    if not pasta[0] or not exe.exists():
        sys.exit("não achei o cdb.exe — instale o WinDbg: winget install Microsoft.WinDbg")
    return str(exe)


def main() -> int:
    from cicloassist.servico.travamento import marcar_lido, nao_lidos, pasta_dos_dumps

    if "--pendentes" in sys.argv:
        import time
        lista = nao_lidos()
        for t in lista:
            print(time.strftime("%d/%m %H:%M:%S", time.localtime(t["quando"])), t["arquivo"])
        print(f"{len(lista)} travamento(s) não lido(s) em {pasta_dos_dumps()}")
        return 0

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tudo = "--tudo" in sys.argv
    if args:
        dump = Path(args[0])
    else:
        dumps = sorted(pasta_dos_dumps().glob("*.dmp"), key=lambda p: p.stat().st_mtime)
        if not dumps:
            print(f"nenhum dump em {pasta_dos_dumps()}")
            return 1
        dump = dumps[-1]
    simbolos = Path(os.environ.get("LOCALAPPDATA", ".")) / "simbolos"
    caminho_dos_simbolos = f"srv*{simbolos}*https://msdl.microsoft.com/download/symbols"
    junto = dump.with_suffix("")
    if junto.is_dir():
        caminho_dos_simbolos += f";{junto}"
    else:
        print(f"⚠️ sem a pasta {junto.name}: as funções do app podem sair sem nome")
    comandos = ".lines -e; " + ("~*k 40" if tudo else "~0k 40") + "; q"
    print(f"dump: {dump}\n")
    r = subprocess.run([cdb(), "-z", str(dump), "-y", caminho_dos_simbolos, "-i", str(junto),
                        "-c", comandos], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600)
    saida = r.stdout.splitlines()
    # O que interessa começa no primeiro "Child-SP" (a pilha); o resto é o cabeçalho do cdb.
    inicio = next((i for i, l in enumerate(saida) if "Child-SP" in l), 0)
    print("\n".join(l for l in saida[max(inicio - 1, 0):]
                    if l.strip() and not l.startswith("quit") and "WARNING: Unable to verify" not in l))
    if r.returncode == 0 and inicio:
        marcar_lido(dump)
    return 0


if __name__ == "__main__":
    sys.exit(main())
