"""O aplicativo que subiu este serviço — a janela do Ciclo Assist (`app/`, Tauri).

⭐ **Decisão do autor (2026-10-18/21): o Assist sai do painel encaixável e vira janela de
app**, no formato que o De Lá Pra Cá provou (`docs/plano/2026-10-18-app-sem-painel.md`).
Quem sobe o serviço passa a ser o app, e ele se apresenta com dois argumentos:

- `--app <exe>`: o caminho do próprio executável. A página do painel é REMOTA (servida
  aqui, em HTTP) e não tem ponte com o Tauri — de propósito: abrir IPC para uma origem
  HTTP daria ao texto que o modelo escreve um caminho até a janela. Quando o painel pede
  algo à janela (o pino, fechar), o pedido dá a volta: página → serviço → executável
  reinvocado com um argumento → `single_instance` do Tauri → a instância viva.
- `--pai <pid>`: o serviço encerra quando o app some, por qualquer caminho.

⚠️ Por que RECEBER o caminho e não PROCURAR o app: uma busca por Program Files /
`target/debug` apodrece a cada mudança de empacotamento e erra do jeito mais caro —
achando uma build velha, que abre e não conversa com este serviço (lição do De Lá Pra Cá,
`servico/main.py`).

Sem `--app` (a bancada: `dev.ps1`, o painel dentro do NLE), nada disto existe e as rotas
`/app/*` respondem `{"janela": false}` — 200, não erro: é o serviço sem aplicativo.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger("cicloassist.aplicativo")

#: O executável que subiu o serviço, conferido no arranque. `None` = sem aplicativo.
_exe: str | None = None
#: O PID do app (`--pai`). ⭐ O piloto precisa dele para tirar a janela do app da frente do
#: programa que vai operar (`piloto/espaco.py`).
_pai: int | None = None


#: O pino como o EDITOR o deixou (`None` = ainda não se sabe). ⭐ Um fluxo fixa a janela para ela
#: ficar à vista (`piloto/espaco.a_vista`); no fim ela volta a como o editor a quer — a do
#: começo do fluxo, ou a do último clique no pino, se ele apertou no meio.
_pino: bool | None = None


def lembrar_pino_inicial(fixada: bool) -> None:
    global _pino
    if _pino is None:
        _pino = fixada


def lembrar_pino(fixada: bool) -> None:
    global _pino
    _pino = fixada


def pino() -> bool:
    return bool(_pino)


def lembrar_pai(pid: int | None) -> None:
    global _pai
    _pai = pid or None


def pai() -> int | None:
    return _pai


def nome_do_exe() -> str:
    """O nome do executável do app (`Ciclo Assist.exe`…), ou ""."""
    return Path(_exe).name if _exe else ""


def apresentar(exe: str | None) -> str | None:
    """Guarda o `--app`, se ele aponta para um arquivo que existe AGORA.

    ⚠️ Conferido no arranque, e não na hora do clique: um caminho errado só apareceria
    quando o editor apertasse o pino — no meio do trabalho, com cara de defeito do pino."""
    global _exe
    _exe = None
    if not exe:
        return None
    if Path(exe).is_file():
        _exe = exe
        log.info("aplicativo que me subiu: %s", exe)
    else:
        log.warning("--app aponta para um arquivo que não existe: %s", exe)
    return _exe


def presente() -> bool:
    return _exe is not None


def chamar(argumento: str) -> dict:
    """Reinvoca o executável com um argumento; o `single_instance` entrega à instância viva.

    ⚠️ `Popen` e não `run`: a segunda execução só carrega o recado e morre, e quem decide
    isso é o outro lado. Esperar por ela penduraria o painel numa decisão que não é nossa."""
    if not _exe:
        return {"janela": False, "motivo": "sem aplicativo"}
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = 0x0800_0000  # CREATE_NO_WINDOW
    try:
        subprocess.Popen([_exe, argumento], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
    except OSError as e:
        log.warning("não consegui chamar o aplicativo (%s %s): %s", _exe, argumento, e)
        return {"janela": False, "motivo": str(e)}
    return {"janela": True}


def app_vivo(pid: int) -> Callable[[], bool] | None:
    """Uma função `() -> bool` que diz se o app `pid` ainda está aberto, ou None se não dá.

    Matriz de plataforma, linha "processo órfão": no Windows o órfão NÃO é readotado e o
    PID é reciclado — o HANDLE é aberto agora (ele prende a identidade do processo) e
    consultado depois. E no Windows o app mata o LANÇADOR do venv (`Scripts\\python.exe`),
    não o Python que ele abre: sem esta vigia o serviço ficaria órfão segurando a 7824.
    No macOS o órfão passa ao `launchd` (`getppid()` muda)."""
    if os.name == "nt":
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not h:
            return None
        return lambda: k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102  # WAIT_TIMEOUT = vivo
    if os.getppid() == pid:
        return lambda: os.getppid() == pid

    def vivo() -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    return vivo


def ocupado() -> bool:
    """Há trabalho que encerrar agora perderia: um turno do modelo, ou a fila de fundo."""
    from . import tarefas, turno

    return turno.atual() is not None or tarefas.ha_tarefa_viva()


def vigiar(pid: int, parar: threading.Event, intervalo_s: float = 2.0,
           vivo: Callable[[], bool] | None = None,
           ocupado_agora: Callable[[], bool] = ocupado) -> threading.Thread | None:
    """Liga `parar` quando o app `pid` fecha. ⚠️ Nunca no meio de um trabalho: espera o
    turno ou a tarefa em curso terminar (é o que o De Lá Pra Cá faz com o relink)."""
    vivo = vivo or app_vivo(pid)
    if vivo is None:
        log.warning("não consigo vigiar o aplicativo (pid %d): ele é quem me encerra", pid)
        return None

    def laco() -> None:
        while not parar.wait(intervalo_s):
            if vivo():
                continue
            if ocupado_agora():
                continue
            log.info("o aplicativo (pid %d) fechou — encerrando o serviço", pid)
            parar.set()
            return

    t = threading.Thread(target=laco, name="vigia-do-app", daemon=True)
    t.start()
    return t
