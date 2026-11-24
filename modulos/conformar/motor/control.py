"""
Relinker — Cancelamento cooperativo de comandos longos.

O sidecar é síncrono: enquanto processa um comando (ex.: index_folder), NÃO lê o
stdin, então não dá para mandar "cancela" pelo canal normal. A solução é um SINAL
(SIGUSR1): o Rust manda o sinal direto ao PID do processo (fora do stdin ocupado) e o
handler aqui seta um Event. Os loops longos (scan/metadados/match) chamam `check()`
periodicamente e abortam com `Cancelled` no próximo ponto de checagem.

O handler só roda na thread principal (limitação do `signal`), que é onde o comando é
processado — então o flag é visto entre arquivos/segmentos (granularidade fina o
suficiente; um arquivo já em leitura termina antes de abortar).
"""

import signal
import threading

_evt = threading.Event()


class Cancelled(Exception):
    """Levantada quando o usuário cancela um comando longo em andamento."""


def install() -> None:
    """Registra o handler de SIGUSR1 (chamar uma vez, na thread principal)."""
    try:
        signal.signal(signal.SIGUSR1, lambda *_: _evt.set())
    except (ValueError, OSError, AttributeError):
        # SIGUSR1 não existe (Windows) ou não estamos na thread principal — sem cancel.
        pass


def begin() -> None:
    """Limpa o flag no início de cada comando."""
    _evt.clear()


def cancelled() -> bool:
    return _evt.is_set()


def check() -> None:
    """Aborta (raise Cancelled) se o cancelamento foi pedido."""
    if _evt.is_set():
        raise Cancelled()
