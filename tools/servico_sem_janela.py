"""O Ciclo Assist SEM JANELA, para um cliente MCP de fora (o app do Claude) — pedido do autor para a aula de 2026-11-20.

    .venv-win\\Scripts\\python tools\\servico_sem_janela.py iniciar   # sobe o serviço (7824) e o Sincronizar (7817)
    .venv-win\\Scripts\\python tools\\servico_sem_janela.py estado
    .venv-win\\Scripts\\python tools\\servico_sem_janela.py parar

A janela do app não abre: quem conversa é o app do Claude, pela ponte `tools/ponte_mcp_stdio.py`, que lê o endereço
do MCP em `<dados>/mcp_externo.json` (arquivo do usuário). O segredo do endereço é sorteado AQUI a cada `iniciar` e
entra no serviço por `CICLOASSIST_SEGREDO_MCP` (`servico/http.py`).

- ⛔ Com o app do Ciclo Assist aberto as portas estão ocupadas: recusa e diz por quê (dois serviços na 7824 é o defeito
  medido em 2026-09-12 — o velho responde tudo, calado).
- ⛔ Os processos sobem sem console (CREATE_NO_WINDOW) e com o log num arquivo: nada aparece na tela.
- O Conformar (7823) não sobe: o ensaio (converter, importar, sync) não passa por ele.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from cicloassist.servico import config  # noqa: E402

PORTA_SERVICO = 7824
PORTA_SINCRONIZAR = 7817
SEM_CONSOLE = 0x0800_0000 if os.name == "nt" else 0


def _python(raiz: Path) -> Path:
    return raiz / (".venv-win/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")


def arquivo() -> Path:
    return config.pasta() / "mcp_externo.json"


def _atende(porta: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
            return True
    except OSError:
        return False


def _vivo(pid: int) -> bool:
    if os.name == "nt":
        saida = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in saida
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _ler() -> dict:
    try:
        return json.loads(arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def iniciar() -> int:
    ocupadas = [p for p in (PORTA_SERVICO, PORTA_SINCRONIZAR) if _atende(p)]
    if ocupadas:
        print(f"as portas {ocupadas} já atendem: o app do Ciclo Assist (ou outro serviço sem janela) está aberto. "
              "Feche-o (ou rode `parar`) antes.")
        return 1
    segredo = secrets.token_urlsafe(32)
    logs = config.pasta() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    amb = dict(os.environ, CICLOASSIST_SEGREDO_MCP=segredo, PYTHONIOENCODING="utf-8", GRPC_ENABLE_FORK_SUPPORT="0")
    sinc = RAIZ / "modulos" / "sincronizar"
    comandos = {
        "servico": [str(_python(RAIZ)), "-m", "cicloassist.servico"],
        "sincronizar": [str(_python(sinc)), str(sinc / "servidor" / "servidor.py")],
    }
    pids = {}
    for nome, cmd in comandos.items():
        if not Path(cmd[0]).is_file():
            print(f"falta o Python de {nome}: {cmd[0]}")
            return 1
        log = open(logs / f"sem_janela_{nome}.log", "ab")
        p = subprocess.Popen(cmd, cwd=str(RAIZ), env=amb, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, creationflags=SEM_CONSOLE)
        pids[nome] = p.pid
    t = time.time()
    while time.time() - t < 90:
        if _atende(PORTA_SERVICO) and _atende(PORTA_SINCRONIZAR):
            break
        mortos = [n for n, pid in pids.items() if not _vivo(pid)]
        if mortos:
            print(f"{mortos} morreu na partida — ver {logs}\\sem_janela_*.log")
            return 1
        time.sleep(0.5)
    else:
        print(f"as portas não abriram em 90 s — ver {logs}\\sem_janela_*.log")
        return 1
    dados = {"url": f"http://127.0.0.1:{PORTA_SERVICO}/mcp/{segredo}", "pids": pids, "desde": time.time()}
    tmp = arquivo().with_suffix(".tmp")
    tmp.write_text(json.dumps(dados), encoding="utf-8")
    os.replace(tmp, arquivo())
    print(f"no ar em {time.time() - t:.1f} s: serviço {pids['servico']} (7824), Sincronizar {pids['sincronizar']} (7817)")
    return 0


def parar() -> int:
    d = _ler()
    for nome, pid in (d.get("pids") or {}).items():
        if _vivo(pid):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, 15)
            print(f"{nome} ({pid}) parado")
    try:
        arquivo().unlink()
    except FileNotFoundError:
        pass
    return 0


def estado() -> int:
    d = _ler()
    vivos = {n: _vivo(p) for n, p in (d.get("pids") or {}).items()}
    print(json.dumps({"arquivo": bool(d), "processos": vivos, "7824": _atende(PORTA_SERVICO),
                      "7817": _atende(PORTA_SINCRONIZAR)}, ensure_ascii=False))
    return 0 if d and all(vivos.values()) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    acao = sys.argv[1] if len(sys.argv) > 1 else "estado"
    raise SystemExit({"iniciar": iniciar, "parar": parar, "estado": estado}.get(acao, estado)())
