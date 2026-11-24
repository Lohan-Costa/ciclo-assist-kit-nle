"""O chat da janela Fluxos e Agentes (fase N2 do plano `2026-11-08-janela-de-nodes.md`): o modelo PROPÕE, e o editor aceita na tela.

⭐ As duas ferramentas não escrevem nada: elas mostram a proposta. Aceitar muda o desenho como uma edição não salva, e quem grava é o botão Salvar. Por isso
não passam pelo portão: não há o que aprovar antes de o editor olhar.
⛔ A conferência é a mesma do executor, ANTES de mostrar: proposta que não roda volta ao modelo com o motivo, e o editor nunca a vê.
"""

from __future__ import annotations

from typing import Any

from ...servico import catalogo_de_pecas as _catalogo
from ...servico import receitas as _receitas
from ...servico import turno as _turno
from ..registro import AMBOS, FERRAMENTAS, ferramenta

MOSTRADA = ("A proposta está na tela do editor, com Aceitar e Recusar. Diga em uma linha o que ela faz, com o nome do node ou do fluxo, "
            "e pare: não repita os passos em texto.")


def _turno_da_janela() -> _turno.Turno | None:
    t = _turno.atual()
    return t if t is not None and t.conversa == "oficina" else None


def _agentes_para_o_grafo() -> dict[str, dict[str, Any]]:
    from ...motor import agentes as _agentes
    try:
        return {a.nome: {"titulo": a.titulo, "saidas": list(a.saida)} for a in _agentes.todos().values()}
    except _agentes.AgenteInvalido:
        return {}


@ferramenta(
    nome="perguntar_ao_editor",
    descricao="Peça de fluxo: para o fluxo e faz perguntas ao editor. perguntas: lista de textos, ou a saída de um agente. Devolve `respostas`.",
    esquema={"type": "object", "properties": {"perguntas": {"type": "array", "description": "As perguntas, ou {passo.perguntas}."}, "titulo": {"type": "string"}}, "required": ["perguntas"]},
    escreve=False,
    nles=AMBOS,
)
def perguntar_ao_editor(perguntas: list | None = None, titulo: str = "") -> dict:
    """⛔ Quem responde por esta peça é o executor (`fluxo._perguntar`): ela existe aqui pelo esquema, e o modelo nunca a chama."""
    return {"erro": "esta peça só existe dentro de um fluxo"}


@ferramenta(
    nome="confirmar_na_memoria",
    descricao=("Peça de fluxo: para o fluxo, mostra ao editor as regras aprovadas pelo agente de metadado e só grava na memória da produção com o clique dele. "
               "regras: {passo.regras_aprovadas}. producao: {passo.producao}. pasta, ou bin e programa: as mesmas da leitura. respostas: {passo.respostas} do node Perguntar, opcional (o que ele respondeu não saber). Devolve gravou, producao, regras."),
    esquema={"type": "object", "properties": {
        "regras": {"type": "array", "description": "As regras aprovadas: {passo.regras_aprovadas}."},
        "producao": {"description": "A produção: {passo.producao}. Sem memória achada, o cartão pergunta o nome."},
        "pasta": {"type": "string", "description": "A pasta dos WAV, a mesma da leitura."},
        "bin": {"type": "string", "description": "A bin, a mesma da leitura."},
        "programa": {"type": "string", "description": "De que programa é a bin."},
        "respostas": {"type": "array", "description": "As respostas do node Perguntar, opcional: o que ele respondeu não saber entra junto."},
    }, "required": ["regras", "producao"]},
    escreve=True,
    nles=AMBOS,
)
def confirmar_na_memoria(**_: Any) -> dict:
    """⛔ Quem responde por esta peça é o executor (`fluxo._confirmar`) e o clique do editor (`fluxo.confirmar`): o modelo nunca a chama."""
    return {"erro": "esta peça só existe dentro de um fluxo"}


@ferramenta(
    nome="propor_fluxo",
    descricao=(
        "Mostra ao editor um fluxo INTEIRO como nodes, para ele aceitar ou recusar na tela. Use para criar um fluxo ou para mudar a estrutura do que está aberto. "
        "`novo=true` para um fluxo novo; `false` substitui o fluxo aberto. passos: [{id, op, args}], com \"{param}\" e \"{id.campo}\"; cada passo depende do anterior, ou de quem disser em depois_de: [ids]; se: {campo: \"id.campo\", e: sim|nao|igual, valor} faz o passo rodar só naquele caso (a condição exige que ele tenha uma única chegada); volta: {para: id anterior, teto: 1 a 5} repete daquele passo até este, e só pode repetir passo que não grava; as operações e o que cada uma aceita "
        "estão em listar_receitas (`operacoes`). parametros: {nome: {tipo: texto|pasta|arquivo|escolha|numero|sim_nao, rotulo, padrao?, opcoes?}}: o que muda de uma vez para "
        "outra é parâmetro, nunca o valor de hoje. resumo: uma frase, com o nome do fluxo."
    ),
    esquema={
        "type": "object",
        "properties": {
            "resumo": {"type": "string"}, "titulo": {"type": "string"}, "parametros": {"type": "object"},
            "passos": {"type": "array", "items": {"type": "object"}}, "novo": {"type": "boolean"},
        },
        "required": ["resumo", "titulo", "parametros", "passos"],
    },
    escreve=False,
    nles=AMBOS,
)
def propor_fluxo(resumo: str, titulo: str, parametros: dict, passos: list, novo: bool = False) -> dict:
    from ...servico import grafo_do_fluxo as _grafo

    turno = _turno_da_janela()
    if turno is None:
        return {"erro": "esta ferramenta só existe no chat da janela Fluxos e Agentes"}
    try:
        problemas = _receitas.ler_texto(_receitas.texto_de("rascunho", resumo, parametros, passos, titulo), "editor").problemas
    except _receitas.ReceitaInvalida as e:
        problemas = [str(e)]
    if problemas:
        return {"erro": "a proposta não passa, e o editor não a viu:\n- " + "\n- ".join(problemas), "agora": "Corrija e proponha de novo."}
    turno.emitir("proposta_fluxo", {"resumo": resumo, "titulo": titulo, "parametros": parametros, "novo": bool(novo),
                                    **_grafo.da_receita(passos, parametros, _agentes_para_o_grafo())})
    return {"mostrada": True, "agora": MOSTRADA}


@ferramenta(
    nome="propor_mudanca_no_node",
    descricao=(
        "Mostra ao editor a mudança de argumentos de UM node do fluxo aberto, para ele aceitar ou recusar. node: o id. mudancas: {argumento: valor novo}; null tira o argumento. "
        "parametros_novos: os {param} que a mudança passa a usar e que o fluxo ainda não tem. resumo: uma frase que diz o NOME do node. "
        "O que a operação não aceita não dá para mudar: diga isso ao editor em vez de chamar esta ferramenta."
    ),
    esquema={
        "type": "object",
        "properties": {"node": {"type": "string"}, "mudancas": {"type": "object"}, "parametros_novos": {"type": "object"}, "resumo": {"type": "string"}},
        "required": ["node", "mudancas", "resumo"],
    },
    escreve=False,
    nles=AMBOS,
)
def propor_mudanca_no_node(node: str, mudancas: dict, resumo: str, parametros_novos: dict | None = None) -> dict:
    turno = _turno_da_janela()
    if turno is None:
        return {"erro": "esta ferramenta só existe no chat da janela Fluxos e Agentes"}
    alvo = next((n for n in (turno.janela or {}).get("nos") or [] if n.get("id") == node), None)
    if alvo is None or alvo.get("tipo") == "agente":
        return {"erro": f"não há um node de passo {node!r} no fluxo aberto"}
    op = str(alvo.get("op") or "")
    peca = _catalogo.CATALOGO.get(op)
    if not mudancas or op not in FERRAMENTAS or peca is None:
        return {"erro": "nada a mudar neste node, ou a operação dele não tem ficha"}
    props = (FERRAMENTAS[op].esquema or {}).get("properties") or {}
    fora = _catalogo.SEMPRE_OCULTOS | set(peca.ocultos)
    problemas = []
    for campo, valor in mudancas.items():
        if campo not in props or campo in fora:
            problemas.append(f"{op} não deixa mudar {campo!r} (aceita: {', '.join(sorted(set(props) - fora)) or 'nada'})")
            continue
        opcoes = props[campo].get("enum")
        if opcoes and isinstance(valor, str) and "{" not in valor and valor not in opcoes:
            problemas.append(f"{campo!r} = {valor!r} não existe (use um de: {', '.join(map(str, opcoes))})")
    if problemas:
        return {"erro": "a mudança não passa, e o editor não a viu:\n- " + "\n- ".join(problemas), "agora": "Diga ao editor o que não dá para mudar."}
    turno.emitir("proposta_node", {"node": node, "rotulo": alvo.get("rotulo") or node, "resumo": resumo, "mudancas": mudancas, "parametros": parametros_novos or {}})
    return {"mostrada": True, "agora": MOSTRADA}
