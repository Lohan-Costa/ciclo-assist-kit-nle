"""F0 — o login do editor lançado pelo APP, sem console, numa pasta de configuração própria.

Pergunta: `claude auth login`, lançado como o serviço lança (sem janela, sem stdin), conclui
SOZINHO depois que o editor entra no navegador? Se precisar colar um código, o desenho muda:
a regra da Anthropic proíbe o app de intermediar credencial (plano 2026-10-31).

Medido antes (2026-10-31, CLI 2.1.316): sem console ele abre o navegador em 0,18 s, imprime a
URL de reserva e fica esperando.

Uso:  python spikes/a_conta_do_app.py [--prazo 300] [--manter]
      (abre o navegador; entre com a sua conta. Nada toca na credencial real: a pasta é
       descartável, e sem --manter o spike faz logout e apaga a pasta no fim.)
Sai 0 se o login concluiu sozinho e o status disse loggedIn.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")

SEM_JANELA = 0x08000000 if os.name == "nt" else 0


def ambiente(pasta: str) -> dict[str, str]:
    amb = dict(os.environ, CLAUDE_CONFIG_DIR=pasta)
    for chave in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        amb.pop(chave, None)
    return amb


def status(cli: str, amb: dict[str, str]) -> dict:
    r = subprocess.run([cli, "auth", "status", "--json"], env=amb, capture_output=True,
                       text=True, encoding="utf-8", stdin=subprocess.DEVNULL,
                       creationflags=SEM_JANELA, timeout=30)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"bruto": r.stdout[:300], "erro": r.stderr[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prazo", type=int, default=300)
    ap.add_argument("--manter", action="store_true")
    a = ap.parse_args()

    cli = shutil.which("claude")
    if not cli:
        print("⛔ claude não está no PATH")
        return 2
    pasta = tempfile.mkdtemp(prefix="cicloassist_conta_")
    amb = ambiente(pasta)
    antes = status(cli, amb)
    print(f"pasta descartável: {pasta}")
    print(f"antes: loggedIn={antes.get('loggedIn')}")

    t0 = time.time()
    p = subprocess.Popen([cli, "auth", "login", "--claudeai"], env=amb,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=SEM_JANELA,
                         text=True, encoding="utf-8", errors="replace")
    saida: list[str] = []

    def ler() -> None:
        for linha in p.stdout:  # type: ignore[union-attr]
            saida.append(f"{time.time() - t0:6.1f}s  {linha.rstrip()[:160]}")

    threading.Thread(target=ler, daemon=True).start()
    print(f"⏳ entre com a sua conta no navegador (prazo {a.prazo} s)…")
    try:
        p.wait(timeout=a.prazo)
    except subprocess.TimeoutExpired:
        p.kill()
    dur = time.time() - t0
    time.sleep(0.5)
    for linha in saida:
        print("   " + linha)
    depois = status(cli, amb)
    ok = bool(depois.get("loggedIn"))
    print(f"processo: rc={p.returncode} em {dur:.1f} s")
    print(f"depois: loggedIn={depois.get('loggedIn')} authMethod={depois.get('authMethod')} "
          f"plano={depois.get('subscriptionType')}")
    print(f"arquivos na pasta: {sorted(os.listdir(pasta))}")

    if not a.manter:
        subprocess.run([cli, "auth", "logout"], env=amb, capture_output=True,
                       stdin=subprocess.DEVNULL, creationflags=SEM_JANELA, timeout=30)
        shutil.rmtree(pasta, ignore_errors=True)
        print("limpo: logout na pasta descartável e pasta apagada")
    print("✅ concluiu sozinho" if ok else "⛔ não concluiu")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
