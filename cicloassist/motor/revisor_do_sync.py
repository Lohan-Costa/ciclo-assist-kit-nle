"""O REVISOR do sync: o gerente de um fluxo autônomo confere as fontes ANTES de sincronizar cada diária.

Decisão 6 do plano `docs/plano/2026-11-08-aba-sincronizar.md`, caso da regra geral do autor (2026-11-08): todo fluxo autônomo
tem um agente que se certifica de que o proposto foi entregue como esperado. A instrução mora em
`cicloassist/agentes/agente-de-revisao-de-fontes.md`. Quem decide é o código: resposta incoerente vira parada do fluxo em `servico/fluxo.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from . import agentes as _agentes
from . import turno_magro as _turno

log = logging.getLogger("cicloassist.motor.revisor_do_sync")

PRAZO_S = 90.0
AGENTE = "agente-de-revisao-de-fontes"


class RevisorFalhou(RuntimeError):
    """Sem IA disponível, ou resposta que não dá para ler."""


def ler_resposta(dados: dict[str, Any]) -> dict[str, Any]:
    """⛔ Só um `true` de verdade aprova: o que não se lê como aprovação para o fluxo."""
    return {"coerente": dados.get("coerente") is True, "motivo": str(dados.get("motivo") or "").strip(),
            "pergunta": str(dados.get("pergunta") or "").strip()}


def revisar(nome: str, fontes: list[dict], modelo: str | None = None) -> dict[str, Any]:
    """`{coerente, motivo, pergunta}`; `RevisorFalhou` se não houver como revisar."""
    try:
        r = _agentes.rodar(AGENTE, {"diaria": nome or "sem nome", "fontes": fontes}, modelo, PRAZO_S)
    except (_agentes.AgenteFalhou, _turno.TurnoFalhou) as e:
        raise RevisorFalhou(str(e)) from e
    veredito = ler_resposta(r["resposta"])
    log.info("revisor do sync (%s): coerente=%s em %.1f s", nome, veredito["coerente"], r["segundos"])
    return veredito
