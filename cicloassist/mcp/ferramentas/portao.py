"""`pedir_confirmacao` — o portão de aprovação, desenhado dentro do painel (ADR 0003).

O CLI chama esta ferramenta antes de deixar o modelo usar qualquer ferramenta que não
esteja na allowlist. O contrato foi **medido**, não presumido (`spikes/fase3_permissao.py`,
2026-09-10, CLI 2.1.267):

```
chega   {"tool_name": "mcp__ciclo__…", "input": {…}, "tool_use_id": "toolu_…"}
espera  {"behavior": "allow", "updatedInput": {…}}
   ou   {"behavior": "deny",  "message": "…"}
```

## ⭐⭐ Esta ferramenta responde NA HORA, e sempre `deny` (ADR 0008)

Ela **não espera o editor**. Abre uma pendência, manda desenhar o cartão no painel e
devolve `deny` imediatamente — o turno termina, a caixa de texto destrava, e o cartão fica
na tela pelo tempo que for preciso. Quando o editor clicar, **o serviço executa a
ferramenta** com os argumentos que ele viu (`servico/pendencias.py`).

⚠️ **`deny` aqui não quer dizer "recusado".** Quer dizer "não é o modelo quem faz isso".
A mensagem que volta precisa deixar isso claro, senão o modelo lê uma recusa, pede
desculpa ao editor e tenta outro caminho — ou, pior, refaz o pedido e empilha cartões.

⛔ **Nunca voltar a bloquear esperando o clique.** A versão que bloqueava dava ao editor o
prazo do CLI para responder — medido em **60 s** (`spikes/portao_espera.py`). Quem saísse
da mesa perdia o trabalho, e o modelo recebia `"The operation timed out."` sem saber que a
causa era uma permissão pendente. Esticar o prazo não resolvia: o erro era ter prazo.

⛔ E a regra que não mudou: **a ação só acontece por clique**. Sem painel, sem pendência,
sem clique — nada é escrito. Silêncio nunca vira consentimento.

## ⭐ A exceção declarada: o modo automático (ADR 0009)

Com o **automático ligado** no painel, este portão responde `allow` na hora e a ferramenta
roda dentro do turno. É o único caminho em que uma escrita acontece sem clique — e ele
existe porque o editor ligou um botão que diz exatamente isso.

⚠️ **Sem perguntar não é sem contar.** Toda ação liberada assim aparece na conversa com a
marca do automático. O editor que volta ao painel precisa conseguir ler o que foi feito
enquanto ele não estava olhando.
"""

from __future__ import annotations

import logging
from typing import Any

from ...servico import config as _config
from ...servico import pendencias as _pendencias
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.portao")

#: ⚠️ O que o modelo lê quando pede ferramenta que não é do Ciclo Assist. Diz o que fazer,
#: senão ele tenta de novo com outro nome da mesma família.
FORA_DO_PRODUTO = (
    "Essa ferramenta não existe neste produto. Use só as ferramentas do Ciclo Assist; "
    "para ler um arquivo que o editor arrastou, use ler_arquivo."
)

#: Ferramentas cujo nome o editor não deveria ver como jargão. O painel mostra isto.
NOMES = {
    "escrever_nota": "gravar uma nota",
    "anotar_o_que_vi": "guardar a descrição de um take",
    "montar_corte": "montar este corte",
    "editar_timeline": "editar uma cópia desta timeline",
    "separar_falas": "separar as falas desta cena numa bin de falas",
}


def _plano_da_receita(curto: str, entrada: dict[str, Any]) -> dict[str, Any]:
    """⭐ Um `executar_fluxo` por RECEITA (`receita` + `parametros`) chega ao cartão como o PLANO inteiro
    (2026-11-04): o cartão mostrava `PARAMETROS {"pasta":"C:\\\\Users…"}` em JSON cru — o editor
    aprovaria um fluxo sem ler os passos. Vira `{plano, receita_de}`, a mesma forma do botão da receita
    na janela, e o `executar_fluxo` aceita as duas. Receita que não monta fica como veio (a ferramenta
    recusa com o motivo)."""
    if curto != "executar_fluxo" or not entrada.get("receita") or entrada.get("plano"):
        return entrada
    from . import fluxo as _ferramenta_fluxo
    try:
        plano = _ferramenta_fluxo._plano_de(None, str(entrada["receita"]), entrada.get("parametros") or {})
    except Exception:  # noqa: BLE001 — sem plano, o cartão mostra o pedido como chegou
        return entrada
    return {"plano": plano, "receita_de": str(entrada["receita"])}


def rotulo(ferramenta_nome: str) -> str:
    curto = ferramenta_nome.removeprefix("mcp__ciclo__")
    return NOMES.get(curto, curto.replace("_", " "))


#: O que o modelo lê quando um pedido vai para a tela do editor.
#:
#: ⭐ **Escrito para o modelo, e cada frase evita um erro visto em campo.** "Não tente de
#: novo" evita a pilha de cartões repetidos; "pode demorar" evita que ele trate a demora
#: como falha; "termine sua resposta" evita que ele fique tentando conversar sozinho
#: enquanto o editor está no Avid conferindo o material.
AGUARDANDO = (
    "Mostrei este pedido ao editor, no painel. Ele responde quando puder — pode ser "
    "daqui a pouco ou só amanhã, e isso é normal: nada expira e nada se perde. Quando "
    "ele autorizar, a ação acontece sozinha e você fica sabendo no próximo turno. "
    "NÃO tente de novo, não mude o pedido e não procure outro caminho: termine sua "
    "resposta dizendo, em uma linha, o que está esperando a confirmação dele."
)


#: O que o modelo lê quando o pedido NÃO passou na conferência da própria ferramenta.
#:
#: ⚠️ É o contrário do `AGUARDANDO`, e tem de dizer isso com todas as letras: lá "não tente
#: de novo" evita a pilha de cartões; aqui pedir de novo, consertado, é exatamente o certo.
NAO_MOSTRADO = (
    "Este pedido NÃO foi mostrado ao editor, porque não passou na conferência:\n{motivo}\n"
    "Conserte o que foi apontado e peça de novo. Se não der para consertar, explique ao "
    "editor o que impede."
)


def _motivo_para_nao_mostrar(curto: str, entrada: dict) -> str:
    """A conferência da ferramenta, quando ela tem uma. Vazio: pode seguir.

    ⚠️ A conferência que QUEBRA não barra o pedido: o cartão aparece, e a ferramenta
    confere de novo ao executar. Barrar por defeito nosso pareceria ao modelo um pedido
    errado, e ele sairia consertando o que não está quebrado.
    """
    from ..registro import FERRAMENTAS

    registrada = FERRAMENTAS.get(curto)
    if registrada is None or registrada.conferir is None:
        return ""
    try:
        return str(registrada.conferir(**entrada) or "")
    except Exception:  # noqa: BLE001
        log.exception("a conferência de %s quebrou; o pedido segue para o editor", curto)
        return ""


@ferramenta(
    nome="pedir_confirmacao",
    descricao=(
        "Uso interno do Ciclo Assist: pergunta ao editor se uma ação pode acontecer. "
        "Você não chama esta ferramenta diretamente."
    ),
    esquema={"type": "object", "properties": {}, "additionalProperties": True},
    escreve=False,
    nles=AMBOS,
)
def pedir_confirmacao(**pedido: Any) -> dict[str, Any]:
    nome = str(pedido.get("tool_name") or "")
    entrada = pedido.get("input") or {}
    curto = nome.removeprefix("mcp__ciclo__")

    # ⛔⛔ **Só as ferramentas do PRODUTO passam por aqui.** MEDIDO no CLI 2.1.270
    #    (`spikes/o_que_o_restricted_deixa.py`): o `--restricted` deixa 29 ferramentas do
    #    próprio CLI, com `Write` e `Edit`, e o automático respondia `allow` para qualquer
    #    nome — o modelo gravaria em caminho que ninguém arrastou, sem cartão. O motor já
    #    sobe com `--tools ""`; isto é a segunda tranca, para o dia em que alguém tirar a
    #    flag. E nem cartão: a pendência só sabe executar ferramenta NOSSA.
    if not nome.startswith("mcp__ciclo__"):
        log.warning("portão recusou ferramenta fora do produto: %s", nome)
        return {"behavior": "deny", "message": FORA_DO_PRODUTO}

    # ⭐ Antes do automático E antes do cartão: nos dois caminhos, um pedido que a
    #   ferramenta recusaria não deve rodar nem ser mostrado.
    motivo = _motivo_para_nao_mostrar(curto, entrada)
    if motivo:
        log.info("pedido de %s não passou na conferência", curto)
        return {"behavior": "deny", "message": NAO_MOSTRADO.format(motivo=motivo)}

    # ⭐⭐ **Modo automático: o editor dispensou a pergunta** (ADR 0009). Aqui o `allow`
    #    é imediato, e a ferramenta roda dentro do turno — o modelo vê o resultado e
    #    segue, sem o desvio da pendência. É o único caminho em que uma escrita acontece
    #    sem um clique, e ele só existe porque o editor ligou um botão que diz isso.
    #
    # ⛔ Lido a CADA pedido, nunca guardado: desligar o automático tem de valer para a
    #    próxima ação, e não para a próxima vez que o serviço subir.
    from ..registro import FERRAMENTAS

    registrada = FERRAMENTAS.get(curto)
    if _config.ler().get("auto") and not (registrada and registrada.sempre_pergunta):
        log.info("modo automático: %s liberada sem perguntar", curto)
        turno = _turno.atual()
        if turno is not None:
            # O editor não é consultado, mas continua VENDO: a linha aparece na conversa
            # com a marca do automático. "Sem perguntar" não é "sem contar".
            turno.emitir("automatico", {"ferramenta": rotulo(nome), "entrada": entrada})
        return {"behavior": "allow", "updatedInput": entrada}

    entrada = _plano_da_receita(curto, entrada)
    pendencia = _pendencias.abrir(curto, rotulo(nome), entrada)

    # O cartão aparece na hora se houver um turno no ar. Se não houver — painel fechado,
    # serviço reiniciado —, ele aparece quando o painel carregar: a pendência já está
    # gravada, e é o `GET /pendencias` que a traz de volta.
    turno = _turno.atual()
    if turno is not None:
        turno.emitir("aprovacao", {
            "id": pendencia.id,
            "ferramenta": pendencia.rotulo,
            "entrada": entrada,
        })
    else:
        log.info("pendência %s aberta sem turno vivo; espera o painel", pendencia.id)

    return {"behavior": "deny", "message": AGUARDANDO}
