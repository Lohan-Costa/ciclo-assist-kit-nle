"""Sobe o serviço do Ciclo Assist e fica de pé.

    python -m cicloassist.servico [--app <exe> --pai <pid>]

Normalmente quem sobe o serviço é a janela do app (o Ciclo Assist não tem painel dentro dos editores desde a
fase 4 do plano um app só, 2026-11-07). Quem passa `--app`/`--pai` é a janela do app (`app/`), que sobe o
serviço sozinha — ver `aplicativo.py`.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading

# ⚠️ Windows: o console herda cp1252 e QUALQUER acento derruba o processo com
# UnicodeEncodeError — no meio da execução, não na partida. Isto vale para todo entry
# point nosso, e por isso mora antes de qualquer import que possa logar.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from . import diario  # noqa: E402
from .http import PORTA, subir  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cicloassist.servico")
    ap.add_argument("--app", default=None,
                    help="caminho do executável do aplicativo que subiu este serviço")
    ap.add_argument("--pai", type=int, default=None,
                    help="PID do aplicativo: ele fechou, o serviço encerra")
    args = ap.parse_args(argv)

    # `CICLOASSIST_LOG=debug` liga o log detalhado. É o que o `dev.ps1 -Verboso` usa —
    # variável de ambiente em vez de argumento porque o serviço também é iniciado por
    # atalho e por instalador, onde não há linha de comando para passar flag.
    arquivo_de_log = diario.configurar(os.environ.get("CICLOASSIST_LOG", "info"))

    try:
        servidor = subir()
    except OSError as e:
        # ⚠️ Porta ocupada quase sempre significa "já há um Ciclo Assist rodando", e não
        # "o sistema está quebrado". Subir um segundo seria pior que recusar: o painel
        # acharia um dos dois, sem dizer qual.
        print(f"\nNão consegui subir na porta {PORTA}: {e}")
        print("Já há um Ciclo Assist rodando? Feche-o antes de abrir outro.")
        return 1

    # ⭐ Fase 4: o segredo com que o Sincronizar e o Conformar pedem a ponte do Premiere (`servico/nucleo.py`)
    from . import nucleo
    try:
        nucleo.publicar()
    except OSError as e:
        print(f"  ⚠️ não consegui publicar o token do núcleo ({e}): os módulos não alcançam o Premiere")

    from .rotas import VERSAO  # importado depois de `subir` registrar as rotas
    from . import aplicativo, vigia

    parar_evento = threading.Event()
    aplicativo.apresentar(args.app)
    aplicativo.lembrar_pai(args.pai)
    if args.pai:
        aplicativo.vigiar(args.pai, parar_evento)
        # ⭐ E se a janela dele RESPONDE: travada, grava onde parou (`travamento.py`).
        from . import travamento
        travamento.vigiar(args.pai, parar_evento)

    # ⭐ A vigia do Premiere volta como o editor a deixou (ligada ou não). Desligada, a
    #   thread só dorme: nem pergunta ao Premiere.
    vigia.iniciar()

    print(f"\n  Ciclo Assist v{VERSAO}")
    print(f"  serviço ... http://127.0.0.1:{PORTA}")
    print(f"  painel .... http://127.0.0.1:{PORTA}/painel")
    print("\n  A janela do Ciclo Assist (ABRIR-APP) usa este serviço; nada se abre dentro dos editores.")
    print("  Ctrl+C para parar.\n")

    # ⚠️ `SIGTERM` (logout, `kill`, launchd) matava o processo sem passar pelo `shutdown`.
    #    Tratado como o Ctrl+C, que já sabe parar direito.
    sinais: list[str] = []

    def parar(sinal, _quadro=None):
        # ⭐ Dito no log (revisão de 2026-11-07): o supervisor via "o processo saiu (código 0)" e nada contava por quê.
        sinais.append(signal.Signals(sinal).name)
        logging.getLogger("cicloassist.servico").info("sinal %s recebido — encerrando", sinais[-1])
        raise KeyboardInterrupt

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, parar)

    # ⭐ Um evento em vez de `sleep(3600)`: a vigia do app (`aplicativo.vigiar`) precisa
    #   poder encerrar o processo. O `wait` com prazo deixa o Ctrl+C chegar no Windows.
    try:
        while not parar_evento.wait(1.0):
            pass
    except KeyboardInterrupt:
        if not sinais:
            logging.getLogger("cicloassist.servico").info("Ctrl+C — encerrando")
    print("\n  parando…")
    servidor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
