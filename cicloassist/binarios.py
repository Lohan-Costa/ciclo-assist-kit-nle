"""Onde estão os binários que são pré-requisito: `claude`, `ffmpeg`, `ffprobe`.

⛔⛔ **O PATH do serviço não é o do terminal.** MEDIDO no macOS (2026-09-14): um processo
lançado pelo Finder, por um `.app` ou pelo launchd recebe `PATH=/usr/bin:/bin:/usr/sbin:/sbin`,
e `shutil.which` não acha nada instalado pelo Homebrew (`/opt/homebrew/bin`) nem pelo
instalador do Claude Code (`~/.local/bin`). O editor lia "o ffmpeg não foi encontrado
nesta máquina" com o ffmpeg instalado — a frase manda reinstalar o que está lá.

⇒ Uma conta só, usada pelos três: primeiro o PATH (quem configurou sabe o que quer), depois
os lugares onde os instaladores do Mac põem as coisas, NESTA ordem — `~/.local/bin` antes
do Homebrew, porque o `claude` do Homebrew/npm costuma ser o velho (medido aqui: 2.1.150,
que recusa `--restricted`, ao lado do 2.1.270 do instalador).

No Windows nada muda: o `shutil.which` já resolve `claude.cmd` e `ffmpeg.exe` pelo PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def lugares_extras() -> list[Path]:
    """Onde procurar quando o PATH não acha. Vazio no Windows."""
    if os.name == "nt":
        return []
    return [Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]


def achar(nome: str) -> str | None:
    """O caminho do executável, ou `None`."""
    achado = shutil.which(nome)
    if achado:
        return achado
    extras = lugares_extras()
    if not extras:
        return None
    return shutil.which(nome, path=os.pathsep.join(str(p) for p in extras))


def onde_procurei() -> str:
    """Para a mensagem de ausência: dizer ONDE, e não só "não está nesta máquina"."""
    extras = lugares_extras()
    return "no PATH" + (" e em " + ", ".join(str(p) for p in extras) if extras else "")
