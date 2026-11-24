"""O Baselight (FilmLight) como programa do fluxo: reconhecer que ele está aberto (proposta 2026-11-22-baselight-no-app,
etapa 1; o autor: "o programa deve reconhecer que quem está aberto é o Baselight, assim como reconhecemos Premiere,
Resolve e Media Composer").

⚠️ "Aberto" é a INTERFACE (`…/Baselight-<versão>.app/Contents/MacOS/Baselight`), não os serviços: o `flapid`, o banco e
o supervisor ficam no ar com a interface fechada (medido no Mac mini, 7.0.3, 2026-11-22). E é a interface que anda a
fila de render da FLAPI (banco, `plugins/baselight/README.md`).

Plataforma: o Baselight roda no macOS e no Linux; no Windows não há Baselight — `aberto()` devolve `False` lá, sem
procurar nada.
"""
from __future__ import annotations

import re
import subprocess
import sys

#: o processo da INTERFACE (o nome do .app traz a versão: `Baselight-7.0.3.26500.app`)
_PADRAO = r"Baselight-[0-9.]+\.app/Contents/MacOS/Baselight$"


def _linha_do_processo() -> str:
    if sys.platform != "darwin":
        return ""
    try:
        r = subprocess.run(["pgrep", "-fl", _PADRAO], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""


def aberto() -> bool:
    """A interface do Baselight está aberta nesta máquina."""
    return bool(_linha_do_processo())


def detalhe() -> dict:
    """`{versao}` do Baselight aberto (do nome do .app), ou `{}`. O job e a scene abertos virão pela FLAPI (etapa 2)."""
    linha = _linha_do_processo()
    m = re.search(r"Baselight-([0-9]+\.[0-9]+\.[0-9]+)", linha)
    return {"versao": m.group(1)} if m else {}
