"""
Orbita — resolve os binários do ffmpeg e do ffprobe.

POR QUE EXISTE: chamar `ffmpeg` pelo nome conta com ele estar no PATH. Na máquina
de desenvolvimento (brew/winget) está; na de um usuário que só baixou o instalador,
não — e o sync morria com `[Errno 2] No such file or directory: 'ffmpeg'`. O app
NÃO pode exigir dependência externa.

COMO FUNCIONA: em release o app EMBARCA o ffmpeg e o ffprobe (externalBin do Tauri,
ao lado do executável). O Rust, ao subir o sidecar, passa o caminho absoluto de
cada um em `ORBITA_FFMPEG` / `ORBITA_FFPROBE`. Aqui a gente lê essas envs primeiro.

FALLBACK: rodando o sidecar direto (dev, testes), as envs não vêm — cai-se no
`shutil.which`, que acha o binário do PATH. Só então, em último caso, devolve-se o
nome cru, para o erro de execução dizer com todas as letras o que falta, em vez de
falhar em silêncio.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _empacotado() -> bool:
    """Estamos rodando dentro do binário do PyInstaller (ou seja, num app instalado)?"""
    return getattr(sys, "frozen", False)


def _resolve(env_var: str, name: str) -> str | None:
    # `DLPC_FFMPEG`/`DLPC_FFPROBE`: o binário EMBARCADO que o app do De Lá Pra Cá injeta (regra do autor,
    # 2026-10-04: a versão instalada traz ffmpeg/ffprobe na versão do desenvolvimento, mesmo que a
    # máquina tenha outros). `ORBITA_*` é o nome herdado do Orbita, aceito como reserva.
    for var in (env_var.replace("ORBITA_", "DLPC_"), env_var):
        embedded = os.environ.get(var)
        if embedded and os.path.isfile(embedded):
            return embedded

    # ⚠️ NUNCA cair no PATH num app instalado.
    #
    # `shutil.which` no Windows inclui o DIRETÓRIO DE TRABALHO ATUAL na busca. Se o
    # sidecar for iniciado com o CWD numa pasta onde outra pessoa escreve, um
    # `ffmpeg.exe` plantado ali é executado no lugar do nosso — binary planting.
    # Em release o Rust SEMPRE injeta `ORBITA_FFMPEG`/`ORBITA_FFPROBE` apontando para
    # o binário embarcado; se a env não veio, a instalação está quebrada, e procurar
    # por aí é a pior resposta possível. Em desenvolvimento o PATH continua valendo —
    # é o que permite rodar o sidecar solto num terminal.
    if _empacotado():
        # O motor instalado é uma PASTA (`tools/montar_motor.py`) e o ffmpeg/ffprobe vêm DENTRO
        # dela, ao lado do executável: a pasta de instalação do app, nunca o CWD nem o PATH.
        ao_lado = os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                               name + (".exe" if sys.platform == "win32" else ""))
        return ao_lado if os.path.isfile(ao_lado) else None
    return shutil.which(name)


def ffmpeg() -> str:
    """Caminho do ffmpeg. Nunca None: sem embarcado nem PATH, devolve o nome cru
    para o erro apontar exatamente o que falta."""
    return _resolve("ORBITA_FFMPEG", "ffmpeg") or "ffmpeg"


def ffprobe() -> str | None:
    """Caminho do ffprobe, ou None se não houver — quem chama já trata a ausência
    de forma graciosa (segue sem o TC do WAV)."""
    return _resolve("ORBITA_FFPROBE", "ffprobe")


def ffprobe_exe() -> str:
    """O ffprobe para pôr na linha de comando: o embarcado, o do PATH, ou o nome cru (o erro de
    execução diz o que falta). ⛔ Nunca escrever `"ffprobe"` direto num `subprocess` do motor: era assim
    em 16 lugares, e o serviço subido pela casca do Resolve (PATH mínimo de `.app`) não o achava — a
    timeline do PRODB entrou inteira offline (2026-10-04)."""
    return ffprobe() or "ffprobe"


# ⚠️ **`CREATE_NO_WINDOW` (0x08000000) — sem isto o Windows pisca.**
#
# Todo `subprocess` no Windows abre uma janela de console. Aqui não é um piscar: uma
# varredura de acervo dispara **um `ffprobe` por arquivo** — 540 numa medição real — e
# a tela do editor fica estroboscópica enquanto o plugin trabalha, por cima da janela
# do Media Composer. Não quebra nada, e é o tipo de coisa que faz um profissional
# desinstalar o plugin.
#
# É `dict` para entrar por `**` em qualquer `subprocess.run`, e a flag fica **só** no
# Windows — ela não existe nos outros SOs e passá-la levantaria `ValueError`.
#
# ⛔ E o stdin FECHADO, nas duas plataformas (banco, bugs-do-mundo-real B020): o ffmpeg lê o stdin (as teclas `q`/`?`)
# e herdaria o do serviço — no Promo Entrega, o cano da guarda de órfão. Quem precisar mandar dados ao filho passa o
# próprio `stdin=` sem o `**SEM_JANELA`.
SEM_JANELA: dict = ({"creationflags": 0x08000000} if sys.platform == "win32" else {}) | {"stdin": subprocess.DEVNULL}
