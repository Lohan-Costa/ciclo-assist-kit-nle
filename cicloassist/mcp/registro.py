"""O registro de ferramentas MCP: um decorador, um dicionário, nada mais.

⚠️ **Poucas ferramentas, boas.** Os concorrentes anunciam centenas de tools geradas
automaticamente; isso estoura contexto e não é vantagem — é ruído que degrada a escolha
do modelo. Aqui cada ferramenta é um verbo do ofício, escrito à mão.

⚠️ **Recusa registrar nome repetido.** Sobrescrita silenciosa é o modo de falha mais caro
que existe: tudo sobe e a ferramenta errada responde. Lição herdada do roteador HTTP do
Assist anterior, onde dois módulos declararam `/mc/info`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    esquema: dict[str, Any]
    funcao: Callable[..., Any]
    escreve: bool
    #: ⭐ Só para quem escreve: `conferir(**entrada) -> str`, vazio quando o pedido passa.
    #: O portão chama ANTES de desenhar o cartão — um pedido que a própria ferramenta
    #: recusaria volta ao modelo com o motivo, e o editor nunca aprova algo para ver falhar.
    conferir: Callable[..., str] | None = None
    #: Em que editor a ferramenta existe (`nle.AVID`, `nle.PREMIERE`). Quem só sabe falar
    #: com o Media Composer não aparece numa conversa do Premiere: o modelo chamaria, e o
    #: editor leria "o Media Composer não está respondendo" dentro do Premiere.
    nles: tuple[str, ...] = ("avid",)
    #: ⛔ O modo automático não dispensa o cartão: para o que só vale se o editor tiver dito (a memória da produção).
    sempre_pergunta: bool = False
    #: ⭐ `previa(**entrada) -> str`: o que dá para saber ANTES de o fluxo começar, sem programa aberto (a pasta tem a mídia?). Vale para qualquer passo do plano.
    previa: Callable[..., str] | None = None

    def como_mcp(self) -> dict[str, Any]:
        return {
            "name": self.nome,
            "description": self.descricao,
            "inputSchema": self.esquema,
        }


FERRAMENTAS: dict[str, Ferramenta] = {}


def ferramenta(
    nome: str,
    descricao: str,
    esquema: dict[str, Any] | None = None,
    *,
    escreve: bool,
    conferir: Callable[..., str] | None = None,
    nles: tuple[str, ...] = ("avid",),
    sempre_pergunta: bool = False,
    previa: Callable[..., str] | None = None,
):
    """Registra uma ferramenta MCP.

    `escreve` é obrigatório e não tem padrão de propósito. Ele decide se a ferramenta
    entra na allowlist (leitura, nunca pergunta) ou passa pelo portão de confirmação no
    painel (escrita, sempre pergunta) — ver ADR 0003. Deixar isso implícito seria deixar
    implícito o que o editor aprova, e é justamente o que não pode ser implícito.
    """

    def registrar(fn: Callable[..., Any]) -> Callable[..., Any]:
        if nome in FERRAMENTAS:
            anterior = FERRAMENTAS[nome].funcao
            raise ValueError(
                f"ferramenta {nome!r} já registrada por "
                f"{anterior.__module__}.{anterior.__qualname__}"
            )
        FERRAMENTAS[nome] = Ferramenta(
            nome=nome,
            descricao=descricao,
            esquema=esquema or {"type": "object", "properties": {}},
            funcao=fn,
            escreve=escreve,
            conferir=conferir,
            nles=tuple(nles),
            sempre_pergunta=sempre_pergunta,
            previa=previa,
        )
        return fn

    return registrar


#: As que servem aos dois editores: não tocam no projeto, só no material e no cache.
AMBOS = ("avid", "premiere")


def do_nle(nle: str) -> list[Ferramenta]:
    """As ferramentas que existem numa conversa daquele editor."""
    return [f for f in FERRAMENTAS.values() if nle in f.nles]


def somente_leitura(nle: str = "avid") -> list[str]:
    """Os nomes que entram no `--allowedTools`, já com o prefixo que o CLI usa."""
    return [f"mcp__ciclo__{f.nome}" for f in do_nle(nle) if not f.escreve]


def assinatura() -> str:
    """Um resumo do que as ferramentas SÃO hoje — nomes e esquemas.

    ⭐⭐ Serve para um problema que só aparece com a conversa que dura (ADR 0004): o
    `--resume` traz de volta um fio em que o modelo já formou opinião sobre o que as
    ferramentas sabem fazer. Quando um esquema muda, aquela opinião fica **errada e
    convicta** — e ele repete para o editor o que aprendeu na versão anterior.

    Aconteceu em 2026-09-11: `montar_corte` ganhou `corte_de_som`, e o modelo, retomando a
    conversa, seguiu explicando que "a ferramenta não separa vídeo e áudio" e que corte em
    L/J era inviável. O dado novo estava lá; a crença velha é que falava mais alto.
    """
    import hashlib
    import json as _json

    corpo = _json.dumps(
        [[f.nome, f.escreve, f.esquema] for f in sorted(FERRAMENTAS.values(),
                                                        key=lambda f: f.nome)],
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:16]
