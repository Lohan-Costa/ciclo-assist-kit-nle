"""OS AGENTES: uma função, num arquivo, com o que recebe e o que devolve declarados (fase A2 do plano `2026-11-08-agentes.md`).

```
---
name: agente-de-revisao-de-fontes
description: O que ele faz, numa frase.
tipo: conselheiro
entradas: {"diaria": "texto", "fontes": "lista"}
saida: {"coerente": "sim_nao", "motivo": "texto", "pergunta": "texto"}
---
## Instrução
```

⭐ Declarar entradas e saídas é o que vai permitir ligar um agente no outro (fase D): sem isso, cada ligação é uma combinação calada entre dois
textos. E é a defesa de agora: resposta sem o campo prometido vira falha, nunca um valor vazio que parece resposta.

Só os da casa, por enquanto (`cicloassist/agentes/`). ⛔ Agente de fora é entrada não confiável (fase B4). Só `conselheiro` roda aqui: propõe em JSON, sem
ferramenta. O `operador` espera a fase C, com o custo medido.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import turno_magro as _turno

log = logging.getLogger("cicloassist.motor.agentes")

DA_CASA = Path(__file__).resolve().parent.parent / "agentes"
TIPOS = ("conselheiro",)
#: ⛔ Os agentes de hoje são peças do programa: sem eles o piloto, o sync ou a leitura da diária param. Daí por que a janela não os exclui.
PECAS_DO_PROGRAMA = {
    "agente-do-piloto": "o piloto chama este agente quando a tela foge do previsto, e é ele quem impede um clique arriscado.",
    "agente-de-revisao-de-fontes": "o Sincronizar não roda sem a conferência dele.",
    "agente-de-metadado": "é ele quem lê os nomes e metadados do som da diária.",
}
_VERIFICA = {"texto": lambda v: isinstance(v, str), "lista": lambda v: isinstance(v, list),
             "objeto": lambda v: isinstance(v, dict), "sim_nao": lambda v: isinstance(v, bool)}


class AgenteInvalido(ValueError):
    """O arquivo do agente está errado: defeito nosso, dito ao carregar."""


class AgenteFalhou(RuntimeError):
    """O agente foi chamado errado, ou respondeu fora do que declara."""


@dataclass(frozen=True)
class Agente:
    nome: str
    descricao: str
    tipo: str
    entradas: dict[str, str]
    saida: dict[str, str]
    instrucao: str
    titulo: str = ""
    texto: str = ""     # o arquivo inteiro, para o editor da janela Fluxos e Agentes


def _campos_declarados(valor: str, rotulo: str) -> dict[str, str]:
    try:
        d = json.loads(valor or "")
    except ValueError as e:
        raise AgenteInvalido(f"'{rotulo}' não é JSON: {e}") from e
    if not isinstance(d, dict) or not d or not all(v in _VERIFICA for v in d.values()):
        raise AgenteInvalido(f"'{rotulo}' tem de ser {{campo: tipo}}, com tipo em {', '.join(_VERIFICA)}")
    return d


def ler_texto(texto: str) -> Agente:
    fim = texto.find("\n---", 3) if texto.startswith("---") else -1
    if fim < 0:
        raise AgenteInvalido("falta o cabeçalho (--- name / description / tipo / entradas / saida ---)")
    cab = {k.strip(): v.strip() for k, v in (ln.split(":", 1) for ln in texto[3:fim].strip().splitlines() if ":" in ln)}
    m = re.search(r"^##\s+Instru[cç][aã]o\s*$(.*?)(?=^##\s|\Z)", texto[fim + 4:], re.M | re.S | re.I)
    instrucao = m.group(1).strip() if m else ""
    if not cab.get("name") or not cab.get("description") or not instrucao:
        raise AgenteInvalido("falta name, description ou a seção '## Instrução'")
    if cab.get("tipo") not in TIPOS:
        raise AgenteInvalido(f"tipo {cab.get('tipo')!r}: por enquanto só {', '.join(TIPOS)}")
    return Agente(nome=cab["name"], descricao=cab["description"], tipo=cab["tipo"],
                  entradas=_campos_declarados(cab.get("entradas", ""), "entradas"),
                  saida=_campos_declarados(cab.get("saida", ""), "saida"), instrucao=instrucao,
                  titulo=cab.get("titulo") or cab["name"].replace("-", " ").capitalize(), texto=texto)


def todos() -> dict[str, Agente]:
    agentes: dict[str, Agente] = {}
    for p in sorted(DA_CASA.glob("*.md")):
        if p.name.startswith("._"):
            continue
        a = ler_texto(p.read_text(encoding="utf-8"))
        agentes[a.nome] = a
    return agentes


def buscar(nome: str) -> Agente:
    agente = todos().get(nome)
    if agente is None:
        raise AgenteFalhou(f"não existe o agente {nome!r}")
    return agente


def montar_pedido(agente: Agente, entrada: dict[str, Any]) -> str:
    """O pedido é só a entrada declarada. ⛔ O que não foi declarado não vai ao modelo: cada campo a mais é token e superfície."""
    for campo, tipo in agente.entradas.items():
        if campo not in entrada:
            raise AgenteFalhou(f"{agente.nome}: faltou a entrada {campo!r}")
        if not _VERIFICA[tipo](entrada[campo]):
            raise AgenteFalhou(f"{agente.nome}: a entrada {campo!r} tem de ser {tipo}")
    return "\n".join(f"{campo}: {entrada[campo] if isinstance(entrada[campo], str) else json.dumps(entrada[campo], ensure_ascii=False)}"
                     for campo in agente.entradas)


def conferir_saida(agente: Agente, dados: dict[str, Any]) -> None:
    """Resposta sem o campo prometido é falha, nunca um valor vazio que parece resposta."""
    for campo, tipo in agente.saida.items():
        if campo not in dados or not _VERIFICA[tipo](dados[campo]):
            raise AgenteFalhou(f"{agente.nome}: a resposta veio sem o campo {campo!r} ({tipo})")


def rodar(nome: str, entrada: dict[str, Any], modelo: str | None = None, prazo: float = _turno.PRAZO_S) -> dict[str, Any]:
    """`{resposta, uso, segundos}`. Levanta `AgenteFalhou` (ou `TurnoFalhou`, sem IA) em vez de devolver meia resposta."""
    agente = buscar(nome)
    r = _turno.chamar(agente.instrucao, montar_pedido(agente, entrada), modelo, prazo)
    dados = _turno.objeto_json(r.texto)
    conferir_saida(agente, dados)
    log.info("%s: %.1f s, uso %s", agente.nome, r.segundos, r.uso)
    return {"resposta": dados, "uso": r.uso, "segundos": r.segundos}
