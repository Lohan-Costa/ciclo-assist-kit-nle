"""O CONJUNTO agora: os motores da família (Sincronizar, De Lá Pra Cá, o próprio Assist…) e os programas abertos.

⭐ Decisão do autor (2026-11-02): com o Ciclo Assist aberto, todos os apps do conjunto ficam no ar; quem cai é
religado sozinho pelo SUPERVISOR do app (`app/src-tauri/src/supervisor.rs`), e quem não sobe é avisado no topo.
Este módulo é o lado do serviço: lê o que o supervisor grava em `<dados>/motores.json` e acrescenta os NLEs.

Para quê: o CONSELHO do fluxo (`motor/conselho.py`) decidia só pelo texto da falha — na prova de 2026-11-02 o De Lá
Pra Cá já tinha voltado e ele pediu ao editor para "abrir a aba Conformar". Com o estado de AGORA no pedido, um
"não respondeu" de um serviço que está no ar é motivo passageiro: tentar de novo.

⚠️ `motores.json` mais velho que `VALIDADE_S` (o app não está rodando: a bancada, o `dev.ps1`) não vale: aí a porta
de cada motor é sondada direto — sem o motivo nem as tentativas, que só o supervisor sabe.
⚠️ Tudo aqui é barato e sem efeito: sonda de socket (≤ 0,3 s cada), nunca uma chamada que acorde um programa.
"""

from __future__ import annotations

import json
import socket
import time
from typing import Any

from . import config as _config

VALIDADE_S = 15.0

#: As portas dos motores (as mesmas de `Modulo::motor` no `lib.rs`), para quando o supervisor não está.
MOTORES = (("preparar", "o Sincronizar", 7817), ("assistir", "o serviço do Assist", 7824),
           ("conformar", "o De Lá Pra Cá", 7823))

SITUACOES = {"no_ar": "no ar", "subindo": "subindo", "religando": "religando", "falhou": "NÃO subiu"}


def _escuta(porta: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, porta), timeout=0.3):
            return True
    except OSError:
        return False


def motores() -> list[dict[str, Any]]:
    """`[{modulo, nome, porta, situacao, motivo, tentativas}]` — do supervisor, ou sondado."""
    try:
        d = json.loads((_config.pasta() / "motores.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("atualizado") or 0) <= VALIDADE_S and isinstance(d.get("motores"), list):
            return [m for m in d["motores"] if isinstance(m, dict)]
    except (OSError, ValueError, TypeError):
        pass
    return [{"modulo": mod, "nome": nome, "porta": porta, "situacao": "no_ar" if _escuta(porta) else "fora",
             "motivo": "", "tentativas": 0} for mod, nome, porta in MOTORES]


def programas() -> dict[str, bool]:
    """Os NLEs abertos agora, pela sonda mais barata de cada um."""
    from .. import resolve as _resolve
    from ..nle.premiere import ponte as _ponte
    try:
        premiere = bool(_ponte.painel_vivo())
    except Exception:  # noqa: BLE001 — sonda: na dúvida, "não sei" vira fechado
        premiere = False
    return {"Media Composer": _escuta(9100, "::1") or _escuta(9100), "DaVinci Resolve": _resolve.servidor_no_ar(),
            "Premiere Pro": premiere}


def frase() -> str:
    """O conjunto em duas linhas, para o modelo."""
    partes = []
    for m in motores():
        s = SITUACOES.get(str(m.get("situacao")), "fora do ar")
        extra = f" ({m['motivo']})" if m.get("motivo") and m.get("situacao") in ("falhou", "religando") else ""
        partes.append(f"{m.get('nome')}: {s}{extra}")
    abertos = [n for n, sim in programas().items() if sim]
    return ("Os serviços do conjunto AGORA: " + "; ".join(partes) + ".\n"
            "Programas abertos agora: " + (", ".join(abertos) if abertos else "nenhum") + ".")
