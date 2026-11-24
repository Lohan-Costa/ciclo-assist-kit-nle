"""Rodar um roteiro de teste DENTRO do serviço — com a ponte CEP do Premiere ligada nele.

A ponte do Premiere fala com o processo que escuta a 7824; uma ferramenta chamada de um Python
avulso não a alcança (o `premiere_app.abrir` "sem prazo" de 2026-11-06 era isso). Este arranjo
para o serviço que estiver na 7824, sobe o serviço NESTE processo, espera a ponte bater e roda o
roteiro (que pode chamar ferramentas direto, sem modelo e sem portão).

    .venv/bin/python spikes/no_servico.py roteiro.py [--nle premiere]

⚠️ É ferramenta de DESENVOLVIMENTO: chama ferramentas que escrevem sem passar pelo cartão do editor.
O serviço normal NÃO é religado no fim (quem roda decide).
"""
from __future__ import annotations

import argparse
import os
import runpy
import signal
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("roteiro")
    ap.add_argument("--nle", default="premiere")
    ap.add_argument("--espera", type=float, default=40.0)
    a = ap.parse_args()

    dono = subprocess.run(["lsof", "-tiTCP:7824", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    for pid in dono:
        os.kill(int(pid), signal.SIGTERM)
    for _ in range(40):
        if not subprocess.run(["lsof", "-tiTCP:7824", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.strip():
            break
        time.sleep(0.25)

    from cicloassist import nle
    from cicloassist.nle.premiere import ponte
    from cicloassist.servico import diario
    from cicloassist.servico.http import subir

    diario.configurar("info")
    servidor = subir()
    nle.definir(a.nle)
    t0 = time.monotonic()
    while a.nle == "premiere" and not ponte.painel_vivo() and time.monotonic() - t0 < a.espera:
        time.sleep(0.5)
    print(f"serviço neste processo; ponte CEP {'viva' if ponte.painel_vivo() else 'MORTA'} "
          f"({time.monotonic() - t0:.1f} s)")
    try:
        runpy.run_path(a.roteiro, run_name="__main__")
    finally:
        servidor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
