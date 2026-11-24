"""
Sincronizar — resolve os binários do ffmpeg e do ffprobe.

POR QUE EXISTE: chamar `ffmpeg` pelo nome conta com ele estar no PATH. Na máquina
de desenvolvimento (brew/winget) está; na de um usuário que só baixou o instalador,
não — e o sync morria com `[Errno 2] No such file or directory: 'ffmpeg'`. O app
NÃO pode exigir dependência externa.

COMO FUNCIONA: em release o app EMBARCA o ffmpeg e o ffprobe (externalBin do Tauri,
ao lado do executável). O Rust, ao subir o sidecar, passa o caminho absoluto de
cada um em `SINC_FFMPEG` / `SINC_FFPROBE`. Aqui a gente lê essas envs primeiro.

FALLBACK: rodando o sidecar direto (dev, testes), as envs não vêm — cai-se no
`shutil.which`, que acha o binário do PATH. Só então, em último caso, devolve-se o
nome cru, para o erro de execução dizer com todas as letras o que falta, em vez de
falhar em silêncio.
"""

from __future__ import annotations

import os
import shutil
import sys


def _empacotado() -> bool:
    """Estamos rodando dentro do binário do PyInstaller (ou seja, num app instalado)?"""
    return getattr(sys, "frozen", False)


def _resolve(env_var: str, name: str) -> str | None:
    embedded = os.environ.get(env_var)
    if embedded and os.path.isfile(embedded):
        return embedded

    # ⚠️ NUNCA cair no PATH num app instalado.
    #
    # `shutil.which` no Windows inclui o DIRETÓRIO DE TRABALHO ATUAL na busca. Se o
    # sidecar for iniciado com o CWD numa pasta onde outra pessoa escreve, um
    # `ffmpeg.exe` plantado ali é executado no lugar do nosso — binary planting.
    # Em release o Rust SEMPRE injeta `SINC_FFMPEG`/`SINC_FFPROBE` apontando para
    # o binário embarcado; se a env não veio, a instalação está quebrada, e procurar
    # por aí é a pior resposta possível. Em desenvolvimento o PATH continua valendo —
    # é o que permite rodar o sidecar solto num terminal.
    if _empacotado():
        return None
    return shutil.which(name)


def ffmpeg() -> str:
    """Caminho do ffmpeg. Nunca None: sem embarcado nem PATH, devolve o nome cru
    para o erro apontar exatamente o que falta."""
    return _resolve("SINC_FFMPEG", "ffmpeg") or "ffmpeg"


def ffprobe() -> str | None:
    """Caminho do ffprobe, ou None se não houver — quem chama já trata a ausência
    de forma graciosa (segue sem o TC do WAV)."""
    return _resolve("SINC_FFPROBE", "ffprobe")
