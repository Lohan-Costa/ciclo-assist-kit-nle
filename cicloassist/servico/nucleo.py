"""O NÚCLEO: o que o Ciclo Assist faz pelos outros módulos — hoje, a PONTE ÚNICA do Premiere.

⭐ Fase 4 do plano um app só (`docs/plano/2026-11-06-um-app-so.md` §4e, 2026-11-07): as três extensões do Premiere
(Assist, Sincronizar, De Lá Pra Cá) viram UMA — a do Assist, que carrega o ExtendScript dos três
(`nle/premiere::host_jsx_inteiro`). O Sincronizar (7817) e o Conformar (7823) não têm mais ponte: pedem aqui
(`POST /nucleo/premiere/chamar`), na MESMA fila do chat, com a mesma regra de gesto × fundo.

⛔ Quem chama é OUTRO PROCESSO, não a página: o porteiro é um segredo sorteado a cada arranque e publicado num arquivo
do usuário (0600) — o mesmo desenho do `plugin-token` do Sincronizar. E cada módulo só chama funções do PRÓPRIO
prefixo: o Sincronizar não roda `ciclo*` nem `dlpc*`.
"""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from . import config

HEADER = "X-Ciclo-Token"
#: ⭐ Passo 2 da fase 4: o token ÚNICO do Ciclo Assist — os módulos conferem este (o Sincronizar deixou de sortear o
#: dele), e quem fala com eles (o cliente do Assist, a ponte do Conformar) apresenta este.
ARQUIVO = "plugin-token"
#: o módulo → o prefixo das funções dele no ExtendScript
PREFIXOS = {"sincronizar": "sinc", "conformar": "dlpc"}

_token: str | None = None


def caminho(pasta: Path | None = None) -> Path:
    return (pasta or config.pasta()) / ARQUIVO


def token() -> str:
    global _token
    if _token is None:
        _token = secrets.token_hex(32)
    return _token


def publicar(pasta: Path | None = None) -> Path:
    """Grava o token (0600). Apaga o que houver antes — inclusive um atalho plantado — e cria com O_EXCL."""
    p = caminho(pasta)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token())
    return p


def confere(valor: str | None) -> bool:
    return bool(valor) and hmac.compare_digest(str(valor).encode(), token().encode())


def funcao_do_modulo(modulo: str, funcao: str) -> bool:
    prefixo = PREFIXOS.get(modulo)
    return bool(prefixo) and funcao.startswith(prefixo) and funcao[len(prefixo):len(prefixo) + 1].isalpha()
