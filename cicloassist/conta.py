"""A conta Claude do Ciclo Assist: a seção Conta da janela de configurações (plano `docs/plano/2026-11-07-aba-conta.md`).

⭐ Decisão do autor (2026-11-07, confirmando o plano de 31/10): a conta é a do APP — o `claude` oficial com
`CLAUDE_CONFIG_DIR` numa pasta do Ciclo Assist (`<dados>/claude`), separada do `claude` pessoal do editor. Sair pela
aba não desloga o Claude Code do terminal, e a sessão não herda nada da conta pessoal (MCP, skills, memória).
MEDIDO 2026-11-07 (Mac, CLI 2.1.319): numa pasta vazia o `auth status` diz `loggedIn: false` — o Mac respeita a pasta.

⛔⛔ O app NUNCA lê nem intermedeia a credencial (banco, `transversal/operacoes.md`): quem entra é o `claude auth login`,
pelo fluxo da Anthropic no navegador; quem sai é o `claude auth logout`; o que o app sabe é o que o `claude auth
status` conta (e-mail, plano, organização, validade). Nada aqui abre `.credentials.json` nem o Keychain.

O USO (autor: só as janelas): o CLI conta a % das janelas de 5 h e semanal DENTRO de um turno (`rate_limit_event`);
`motor/claude.py` guarda o último em `<dados>/uso.json`, e a aba mostra com a hora em que foi medido.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .servico import config as _config

log = logging.getLogger(__name__)

#: Só estes campos do `auth status` saem daqui (o resto — pastas, ids — não é da conta do editor).
CAMPOS = ("loggedIn", "authMethod", "email", "orgName", "subscriptionType", "loginExpiresAt")
#: O login espera o editor no navegador; passado disso, o processo é encerrado (ele pode clicar de novo).
PRAZO_DO_LOGIN_S = 600.0
PRAZO_DO_STATUS_S = 15.0
PRAZO_DO_LOGOUT_S = 30.0
_SEM_JANELA = {"creationflags": 0x0800_0000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW

_login: dict = {"processo": None, "desde": 0.0, "fim": None}
_trava = threading.Lock()


def pasta() -> Path:
    """A pasta da conta do app (o `CLAUDE_CONFIG_DIR`). `CICLOASSIST_CLAUDE_CONFIG` troca (desenvolvimento)."""
    explicita = os.environ.get("CICLOASSIST_CLAUDE_CONFIG")
    return Path(explicita) if explicita else _config.pasta() / "claude"


def ambiente(base: dict[str, str] | None = None) -> dict[str, str]:
    """O ambiente de QUALQUER `claude` que o app sobe: com a pasta da conta do app."""
    amb = dict(os.environ if base is None else base)
    p = pasta()
    p.mkdir(parents=True, exist_ok=True)
    amb["CLAUDE_CONFIG_DIR"] = str(p)
    return amb


def _cli() -> str:
    from .motor.claude import achar_o_cli  # noqa: PLC0415 — evita o ciclo motor → conta → motor
    return achar_o_cli()


def _rodar(args: list[str], prazo: float) -> subprocess.CompletedProcess:
    return subprocess.run([_cli(), *args], env=ambiente(), stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=prazo, **_SEM_JANELA)


def _entrando() -> bool:
    with _trava:
        p = _login["processo"]
        if p is None:
            return False
        if p.poll() is not None:
            _login.update(processo=None, fim=p.returncode)
            return False
        if time.monotonic() - _login["desde"] > PRAZO_DO_LOGIN_S:
            log.info("conta: o login ficou %.0f min esperando o navegador — encerrado", PRAZO_DO_LOGIN_S / 60)
            p.kill()
            _login.update(processo=None, fim="prazo")
            return False
        return True


def ultimo_uso() -> dict | None:
    """O último `rate_limit_event` que um turno trouxe (`motor/claude.py` grava), ou `None`."""
    try:
        return json.loads((_config.pasta() / "uso.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def gravar_uso(dado: dict) -> None:
    """Chamado pelo motor a cada `rate_limit_event`. Nunca falha para quem chama."""
    try:
        destino = _config.pasta() / "uso.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({**dado, "quando": time.time()}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, destino)
    except OSError as e:
        log.debug("conta: não gravei o uso (%s)", e)


def estado() -> dict:
    """`{conta: {loggedIn, email, …} | None, entrando, erro, uso}` — para a aba."""
    r: dict = {"entrando": _entrando(), "uso": ultimo_uso(), "conta": None, "erro": ""}
    try:
        saida = _rodar(["auth", "status", "--json"], PRAZO_DO_STATUS_S)
        bruto = json.loads(saida.stdout or "{}")
        r["conta"] = {k: bruto.get(k) for k in CAMPOS}
    except Exception as e:  # noqa: BLE001 — CLI ausente, prazo, JSON estranho: a aba diz, não cai
        log.info("conta: o auth status falhou: %s", e)
        r["erro"] = str(e) if "não foi encontrado" in str(e) else "não consegui ler a conta do Claude agora"
    if _login["fim"] not in (None, 0) and not r["entrando"]:
        r["login_falhou"] = _login["fim"]
    return r


def entrar() -> dict:
    """Abre o login da Anthropic no navegador (`claude auth login --claudeai`, sem console) e volta na hora; a aba
    pergunta o estado até a conta aparecer. Medido no Windows (31/10): conclui sozinho, sem colar código."""
    if _entrando():
        return {"ok": True, "ja": True}
    arquivo = _config.pasta() / "logs" / "conta-login.log"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    saida = open(arquivo, "a", encoding="utf-8")  # noqa: SIM115 — vive com o processo
    saida.write(f"\n── login {time.strftime('%Y-%m-%d %H:%M:%S')} ──\n")
    saida.flush()
    p = subprocess.Popen([_cli(), "auth", "login", "--claudeai"], env=ambiente(), stdin=subprocess.DEVNULL,
                         stdout=saida, stderr=subprocess.STDOUT, **_SEM_JANELA)
    with _trava:
        _login.update(processo=p, desde=time.monotonic(), fim=None)
    log.info("conta: login aberto (pid %d) — o editor termina no navegador", p.pid)
    return {"ok": True}


def sair() -> dict:
    with _trava:
        p = _login["processo"]
        if p is not None and p.poll() is None:
            p.kill()
        _login.update(processo=None, fim=None)
    try:
        r = _rodar(["auth", "logout"], PRAZO_DO_LOGOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "erro": f"não consegui sair: {e}"}
    log.info("conta: logout (rc %s)", r.returncode)
    return {"ok": r.returncode == 0, "erro": "" if r.returncode == 0 else (r.stderr or r.stdout or "").strip()[:200]}
