"""As ferramentas que leem o Premiere aberto — o par de `avid.py`, pela ponte do painel.

Só LEITURA (plano `docs/plano/2026-09-17-premiere.md`, primeira entrega). Existem só numa
conversa do Premiere (`nles`); as de mídia (`ver_frames`, `transcrever`,
`planos_parecidos`…) são as mesmas dos dois editores e recebem `bin` + `item` daqui.
"""

from __future__ import annotations

from ...avid.take import TakeErro
from ...midia import cache as _cache
from ...nle import premiere as _premiere
from ...nle.premiere import ponte as _ponte
from ..registro import ferramenta

SO_PREMIERE = ("premiere",)


def _falha(e: Exception) -> dict[str, object]:
    return {"erro": str(e)}


@ferramenta(
    nome="projeto_do_premiere",
    descricao=(
        "O projeto aberto agora no Adobe Premiere Pro: caminho, nome, a sequência ativa e a "
        "versão do Premiere. Use isto primeiro para saber com o que se está trabalhando."
    ),
    escreve=False,
    nles=SO_PREMIERE,
)
def projeto_do_premiere() -> dict[str, object]:
    try:
        return _premiere.estado()
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return _falha(e)


@ferramenta(
    nome="listar_bins_do_premiere",
    descricao=(
        "Lista as bins (pastas) do projeto aberto no Premiere, pelo caminho de nomes "
        "(\"DIARIA 01/CAM A\"), com quantos itens cada uma tem."
    ),
    escreve=False,
    nles=SO_PREMIERE,
)
def listar_bins_do_premiere() -> dict[str, object]:
    try:
        bins = _premiere.bins()
        return {"quantidade": len(bins), "bins": bins}
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return _falha(e)


@ferramenta(
    nome="listar_itens_do_premiere",
    descricao=(
        "Lista o que há numa bin do Premiere: nome, id, espécie (clipe, merged, sequencia, "
        "bin…) e o arquivo de cada clipe. Sem bin, lista a raiz do projeto. Passe o id do "
        "item às ferramentas de mídia (ver_frames, transcrever, planos_parecidos) junto "
        "com a bin."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string",
                    "description": "Caminho da bin como listar_bins_do_premiere devolveu; vazio = raiz."},
            "apenas_selecionados": {"type": "boolean", "default": False,
                                    "description": "Só o que o editor selecionou."},
        },
    },
    escreve=False,
    nles=SO_PREMIERE,
)
def listar_itens_do_premiere(bin: str = "", apenas_selecionados: bool = False) -> dict[str, object]:
    try:
        d = _premiere.itens(bin, apenas_selecionados)
        itens = d.get("itens") or []
        resposta = {"bin": d.get("bin", bin), "quantidade": len(itens), "itens": itens}
        # ⛔⛔ MEDIDO em 2026-09-17, em campo: com `apenas_selecionados`, toda bin voltava
        #    `quantidade: 0` — porque o editor não tinha nada selecionado — e o modelo
        #    repetiu as MESMAS onze bins quatro vezes, 46 chamadas, 20 minutos. Zero sem
        #    explicação é indistinguível de "bin vazia": a resposta tem de dizer qual dos
        #    dois é, e o que fazer.
        if apenas_selecionados and not itens:
            todos = (_premiere.itens(bin, False).get("itens") or [])
            resposta["aviso"] = (
                f"Não há NADA selecionado nessa bin no Premiere agora; ela tem "
                f"{len(todos)} item(ns). Chame de novo sem apenas_selecionados — a "
                f"seleção é do mouse do editor, e pedir de novo não vai mudá-la."
                if todos else
                "Essa bin está vazia (com ou sem seleção).")
            resposta["itens_na_bin"] = len(todos)
        return resposta
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return _falha(e)


@ferramenta(
    nome="selecao_do_premiere",
    descricao=(
        "O que o editor tem selecionado agora no painel Project do Premiere, com a bin e o "
        "id de cada item. Use quando ele disser \"este clipe\", \"os selecionados\"."
    ),
    escreve=False,
    nles=SO_PREMIERE,
)
def selecao_do_premiere() -> dict[str, object]:
    try:
        itens = _premiere.selecao()
        return {"quantidade": len(itens), "itens": itens}
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return _falha(e)


@ferramenta(
    nome="resolver_item_do_premiere",
    descricao=(
        "Traduz um clipe do Premiere — clipe comum ou merged clip — no que o Ciclo Assist "
        "sabe dele: o arquivo de imagem, o de som, a entrada de cada um, cena/plano/take, e "
        "se a mídia já foi analisada (inclusive no Media Composer, quando o arquivo é o "
        "original de uma mídia convertida lá)."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string", "description": "A bin do item, como a listagem mostrou."},
            "item": {"type": "string", "description": "O id do item (ou o nome)."},
        },
        "required": ["item"],
    },
    escreve=False,
    nles=SO_PREMIERE,
)
def resolver_item_do_premiere(item: str, bin: str = "") -> dict[str, object]:
    try:
        take = _premiere.resolver_take(bin, item)
    except TakeErro as e:
        return _falha(e)
    d = take.como_dicionario()
    for lado in ("imagem", "som"):
        fonte = getattr(take, lado)
        if fonte is None or not d.get(lado):
            continue
        # ⛔ Clipe OFFLINE (mídia num volume desmontado, ou relinkada) não tem chave de
        #   conteúdo: sem arquivo, `Fonte.chave` cai no nome do item e `Midia(nome)` estoura
        #   com `ChaveInvalida`. O take continua bom — o aviso já diz que o arquivo sumiu —,
        #   e recusar o take inteiro por isso seria trocar uma informação por um erro.
        try:
            midia = fonte.midia() if fonte.arquivos else None
            d[lado]["ja_analisada"] = bool(midia and midia.existe)
        except _cache.ChaveInvalida:
            d[lado]["ja_analisada"] = False
        d[lado].pop("apelidos", None)
    return d


@ferramenta(
    nome="organizar_o_projeto",
    descricao=(
        "ESCREVE no projeto do Premiere: cria bins (pastas), move itens e bins para dentro "
        "de uma bin, renomeia, e apaga bin VAZIA. Mande o plano inteiro de uma vez — o "
        "editor vê a lista e aprova (ou não) num clique só; monte-o a partir de "
        "arvore_do_premiere, que dá o projeto inteiro numa chamada. Use os ids que a árvore "
        "devolveu; para a raiz do projeto, deixe o destino vazio. Uma bin criada no mesmo "
        "plano pode receber itens logo depois, pelo nome dela, e uma bin que o plano acabou "
        "de esvaziar pode ser apagada na mesma lista. Nunca apaga mídia nem mexe em "
        "timeline."
    ),
    esquema={
        "type": "object",
        "properties": {
            "operacoes": {
                "type": "array",
                "description": "Na ordem em que devem acontecer.",
                "items": {
                    "type": "object",
                    "properties": {
                        "acao": {"type": "string", "enum": list(_premiere.ACOES)},
                        "nome": {"type": "string",
                                 "description": "criar_bin: o nome da bin. renomear: o nome novo."},
                        "dentro_de": {"type": "string",
                                      "description": "criar_bin: id, caminho da bin mãe, ou vazio para a raiz."},
                        "item": {"type": "string",
                                 "description": "mover/renomear: o id (ou o caminho da bin)."},
                        "para": {"type": "string",
                                 "description": "mover: id ou caminho da bin de destino; vazio = raiz."},
                    },
                    "required": ["acao"],
                },
            },
        },
        "required": ["operacoes"],
    },
    escreve=True,
    conferir=lambda operacoes=None, **_: _premiere.conferir_organizacao(operacoes),
    nles=SO_PREMIERE,
)
def organizar_o_projeto(operacoes: list[dict] | None = None) -> dict[str, object]:
    # ⛔⛔ O cartão pode ter esperado horas (ADR 0008): entre a aprovação e o clique o editor
    #    pode ter arrastado uma bin para dentro de outra, e o "mova A para B" aprovado
    #    passaria a aninhar A dentro dela mesma — que o ExtendScript aceita calado. As três
    #    que escrevem no Avid conferem de novo aqui pelo mesmo motivo.
    try:
        problema = _premiere.conferir_organizacao(operacoes or [])
        if problema:
            return {"erro": f"o projeto mudou desde que você aprovou: {problema}",
                    "nada_foi_feito": True}
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou):
        pass  # sem ponte não há o que conferir — a execução falha com a frase certa
    try:
        feito = _premiere.organizar(operacoes or [])
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return _falha(e)
    # ⭐ A árvore depois, para o modelo dizer ao editor como o projeto ficou — e não
    #   prometer o que pediu. São dois estados diferentes quando uma operação falha.
    try:
        bins = [b["caminho"] for b in _premiere.bins()]
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou):
        bins = []
    feito["bins_agora"] = bins
    return feito


#: Teto de itens numa árvore. ⚠️ O que a ferramenta DEVOLVE é orçamento do turno (regra da
#: casa): um projeto de 2.000 clipes não cabe numa resposta, e truncar calado faria o modelo
#: organizar metade do projeto achando que viu tudo.
ITENS_NA_ARVORE = 400


@ferramenta(
    nome="arvore_do_premiere",
    descricao=(
        "O projeto INTEIRO numa chamada só: cada bin e cada item, com id, espécie e a bin "
        "em que está. Use isto antes de organizar — é o que evita uma chamada por pasta. "
        "Dá para pedir só um galho (bin) e só as bins (sem_clipes)."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string",
                    "description": "Só o que está dentro desta bin (e das filhas). Vazio = o projeto todo."},
            "sem_clipes": {"type": "boolean", "default": False,
                           "description": "Só as pastas, para ver a estrutura."},
        },
    },
    escreve=False,
    nles=SO_PREMIERE,
)
def arvore_do_premiere(bin: str = "", sem_clipes: bool = False) -> dict[str, object]:
    try:
        itens = _premiere.arvore()
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return _falha(e)
    if bin:
        itens = [i for i in itens
                 if i.get("bin") == bin or str(i.get("bin") or "").startswith(bin + "/")]
    if sem_clipes:
        itens = [i for i in itens if i.get("especie") == "bin"]
    resposta: dict[str, object] = {"bin": bin or "(projeto todo)", "total": len(itens)}
    if len(itens) > ITENS_NA_ARVORE:
        resposta["itens"] = itens[:ITENS_NA_ARVORE]
        resposta["ficaram_de_fora"] = len(itens) - ITENS_NA_ARVORE
        resposta["aviso"] = (
            f"São {len(itens)} itens e a resposta leva {ITENS_NA_ARVORE}. Peça por bin "
            f"(o parâmetro bin) ou só as pastas (sem_clipes) para ver o resto.")
    else:
        resposta["itens"] = itens
    return resposta
