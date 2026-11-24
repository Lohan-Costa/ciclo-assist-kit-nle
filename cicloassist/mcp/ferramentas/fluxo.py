"""O fluxo no chat: o modelo MONTA o plano, o editor aprova UM cartão, o executor roda (F1).

`executar_fluxo` é o caminho do modelo; o botão de uma receita (`/receitas/preparar`) abre a
MESMA pendência, então o cartão e a execução são um só, venha o plano de onde vier.

⭐ O modelo volta à cena só quando um passo falha: o fluxo para em `esperando`, o painel abre um
turno curto com o estado no preâmbulo (`fluxo.recado`), e a saída que o modelo propuser passa
por `continuar_fluxo` — outro cartão.
"""

from __future__ import annotations

from typing import Any

from ...servico import fluxo as _fluxo
from ...servico import receitas as _receitas
from ..registro import AMBOS, ferramenta


def _plano_de(plano: dict | None, receita: str, parametros: dict | None) -> dict[str, Any]:
    if receita:
        r = _receitas.buscar(receita)
        if r is None:
            raise _receitas.ReceitaInvalida(
                f"não há a receita {receita!r}; há: {', '.join(sorted(_receitas.todas())) or 'nenhuma'}")
        return r.plano(parametros or {})
    if not isinstance(plano, dict):
        raise _fluxo.PlanoInvalido("mande `plano` (nome, parametros, passos) ou `receita` + `parametros`")
    return plano


def _conferir(plano: dict | None = None, receita: str = "", parametros: dict | None = None, **_: Any) -> str:
    try:
        p = _plano_de(plano, receita, parametros)
    except (_fluxo.PlanoInvalido, _receitas.ReceitaInvalida) as e:
        return str(e)
    problemas = _fluxo.validar(p)
    if problemas:
        return "O plano não passa:\n- " + "\n- ".join(problemas)
    aberto = _fluxo.em_aberto()
    if aberto is not None:
        return (f"Já há o fluxo '{aberto.nome}' {aberto.estado}. Um fluxo de cada vez: termine-o com "
                "continuar_fluxo (tentar_de_novo, pular ou cancelar) antes de montar outro.")
    # ⭐ MEDIDO no teste pilotado (2026-11-09): a pasta vazia só aparecia depois de 14,5 s abrindo o Resolve.
    for passo in p["passos"]:
        registrada = _fluxo._ferramentas().get(passo["op"])
        args = passo.get("args") or {}
        if registrada is None or registrada.previa is None or any("." in r for r in _fluxo._referencias(args)):
            continue
        try:
            motivo = registrada.previa(**_fluxo.resolver(args, p.get("parametros") or {}, {}))
        except _fluxo.PlanoInvalido:
            continue    # o que falta aqui a conferência de estrutura já disse
        if motivo:
            return f"O passo {passo['id']} não vai dar certo: {motivo}"
    # ⚠️ Só o PRIMEIRO passo se confere agora: os outros dependem do mundo que os anteriores
    #   vão deixar (a pasta MXF que o converter cria, as bins que o importar cria) — esses são
    #   conferidos logo antes de rodar.
    primeiro = p["passos"][0]
    registrada = _fluxo._ferramentas().get(primeiro["op"])
    args = primeiro.get("args") or {}
    if registrada is not None and registrada.conferir is not None and not any(
            "." in r for r in _fluxo._referencias(args)):
        try:
            motivo = registrada.conferir(**_fluxo.resolver(args, p.get("parametros") or {}, {}))
        except _fluxo.PlanoInvalido as e:
            motivo = str(e)
        if motivo:
            return f"O primeiro passo ({primeiro['id']}) não passa:\n{motivo}"
    return ""


@ferramenta(
    nome="executar_fluxo",
    descricao=(
        "Roda VÁRIAS operações em sequência, como um fluxo, com UM cartão para o editor aprovar o plano "
        "inteiro — use quando o pedido tem mais de um passo (ex.: converter no Resolve, fechar, abrir o "
        "Media Composer, importar, sincronizar). Quem executa é o Ciclo Assist, passo a passo, no fundo; "
        "você NÃO chama as operações uma a uma. plano = {nome, parametros: {nome: valor}, passos: "
        "[{id, op, args}]}; op é o nome de uma ferramenta (converter_para_opatom, converter_para_proxy, importar_no_premiere, fechar_programa, "
        "abrir_programa, importar_masters_opatom, som_direto_gerenciado, sincronizar, "
        "salvar_tudo, organizar_bins, conformar_no_resolve…); em args, \"{nome}\" puxa um parâmetro e "
        "\"{id.campo}\" a SAÍDA de um passo anterior (ex.: a pasta que o converter criou: \"{conv.pasta}\", e o "
        "formato do Media Composer da mídia convertida: \"{conv.formato}\"); lista é lista JSON (ex.: bins: "
        "[\"{camera.bin}\", \"{som.bin}\"]). "
        "Ou, para um fluxo conhecido: receita (o nome, ver listar_receitas) + parametros. Se um passo "
        "falhar, o fluxo para e você é chamado com o estado."
    ),
    esquema={
        "type": "object",
        "properties": {
            "plano": {"type": "object", "description": "{nome, parametros, passos: [{id, op, args}]}"},
            "receita": {"type": "string", "description": "O nome de uma receita, em vez de plano."},
            "parametros": {"type": "object", "description": "Com receita: os valores dos parâmetros dela."},
        },
    },
    escreve=True,
    conferir=_conferir,
    nles=AMBOS,
)
def executar_fluxo(plano: dict | None = None, receita: str = "", parametros: dict | None = None,
                   receita_de: str = "") -> dict:
    # `receita_de`: só o botão da janela manda (o plano já veio resolvido da receita).
    try:
        p = _plano_de(plano, receita, parametros)
        de = receita or receita_de
        f = _fluxo.criar(p, origem=f"receita:{de}" if de else "modelo")
    except (_fluxo.PlanoInvalido, _fluxo.FluxoOcupado, _receitas.ReceitaInvalida) as e:
        return {"erro": str(e)}
    try:
        _fluxo.iniciar(f.id)
    except _fluxo.FluxoOcupado as e:
        # ⛔ Não começou (outra tarefa de fundo correndo): o fluxo some, senão ficaria "pausado"
        #   bloqueando o próximo pedido sem ninguém saber que existe.
        _fluxo.descartar(f.id)
        return {"erro": f"{e}. Nada foi feito; peça de novo quando a outra tarefa terminar."}
    return {"fluxo": f.id, "nome": f.nome, "passos": len(f.passos),
            "manchete": f"o fluxo '{f.nome}' começou ({len(f.passos)} passos); a janela mostra o andamento",
            "agora": "O fluxo roda sozinho. Termine a resposta em uma linha; você será chamado se um passo falhar."}


ACOES = ("tentar_de_novo", "pular", "cancelar", "retomar")


def _conferir_continuar(acao: str = "", args: dict | None = None, **_) -> str:
    f = _fluxo.em_aberto()
    if f is None:
        return "Não há fluxo parado para continuar."
    if acao not in ACOES:
        return f"acao tem de ser uma de: {', '.join(ACOES)}"
    if f.estado == "correndo":
        return f"O fluxo '{f.nome}' está correndo; espere ele parar."
    if acao == "pular" and f.estado not in ("esperando", "interrompido"):
        return f"Só se pula o passo que parou o fluxo; ele está {f.estado} (use retomar)."
    if args and acao != "tentar_de_novo":
        return "args só vale com tentar_de_novo (os argumentos corrigidos do passo que falhou)."
    if args:
        p = f.passos[f.atual] if f.atual < len(f.passos) else None
        if p is None:
            return "O fluxo não tem passo a corrigir."
        teste = {"parametros": f.parametros,
                 "passos": [{"id": q.id, "op": q.op, "args": ({**q.args, **args} if q is p else q.args)}
                            for q in f.passos]}
        problemas = _fluxo.validar(teste)
        if problemas:
            return "Os argumentos corrigidos não passam:\n- " + "\n- ".join(problemas)
    return ""


@ferramenta(
    nome="continuar_fluxo",
    descricao=(
        "Decide o que fazer com o fluxo PARADO (um passo falhou, o editor pausou, ou o serviço reiniciou): "
        "tentar_de_novo o passo que parou (com args = os argumentos corrigidos dele, se for o caso), "
        "pular esse passo, cancelar o fluxo, ou retomar (do passo seguinte ao último feito). Os passos "
        "feitos não se refazem."
    ),
    esquema={
        "type": "object",
        "properties": {
            "acao": {"type": "string", "enum": list(ACOES)},
            "args": {"type": "object", "description": "Só com tentar_de_novo: os argumentos a trocar no passo."},
        },
        "required": ["acao"],
    },
    escreve=True,
    conferir=_conferir_continuar,
    nles=AMBOS,
)
def continuar_fluxo(acao: str = "", args: dict | None = None) -> dict:
    f = _fluxo.em_aberto()
    if f is None:
        return {"erro": "não há fluxo parado"}
    try:
        _fluxo.decidir(acao, args)
    except (_fluxo.PlanoInvalido, _fluxo.FluxoOcupado, KeyError) as e:
        return {"erro": str(e)}
    if acao == "cancelar":
        return {"fluxo": f.id, "manchete": f"o fluxo '{f.nome}' foi cancelado", **_fluxo.resumo(f)}
    return {"fluxo": f.id, "manchete": f"o fluxo '{f.nome}' seguiu do passo {f.atual + 1}",
            "agora": "O fluxo roda sozinho. Termine a resposta em uma linha."}


@ferramenta(
    nome="listar_receitas",
    descricao=("As receitas de fluxo que existem (da casa e do editor): nome, quando usar, os parâmetros e "
               "os passos. ⛔ No chat você NÃO roda receita: quando o pedido bater com uma, diga ao editor "
               "numa linha que ela existe e que roda na aba Fluxos (o editor pode sair da ilha enquanto "
               "ela roda) — e, se ele quiser agora, faça o pedido aqui, passo a passo."),
    escreve=False,
    nles=AMBOS,
)
def listar_receitas() -> dict:
    """⭐⭐ Com os passos INTEIROS e os argumentos de cada operação (prova da F3, 2026-11-04): a lista
    mostrava só `id` e `op`, e o modelo — que via QUE existe um `abrir_programa`, mas não COMO se chama —
    inventou `criar` e `diaria` no primeiro plano; a conferência barrou, e o editor esperou uma volta."""
    rs = _receitas.todas()
    return {"receitas": [
        {**r.para_a_janela(), "passos": r.passos, "quando_as_condicoes_mudam": r.condicoes[:1500]}
        for r in rs.values()],
        "operacoes": operacoes_dos_fluxos(rs.values())}


#: As operações que um plano costuma usar além das que as receitas já usam.
_OUTRAS_OPERACOES = ("organizar_bins", "conformar_no_resolve", "entender_metadados_da_diaria", "perguntar_ao_editor", "confirmar_na_memoria")


def operacoes_dos_fluxos(receitas) -> dict[str, str]:
    """`{op: "programa* (resolve|premiere|media_composer) · projeto* · formato · versao"}` — o que cada
    operação aceita, em uma linha (`*` = obrigatório; `[lista]` = lista JSON). Curto de propósito: vai
    em toda listagem, e o esquema inteiro de nove ferramentas seria contexto que ninguém lê."""
    ops = {p.get("op") for r in receitas for p in r.passos} | set(_OUTRAS_OPERACOES)
    registradas = _fluxo._ferramentas()
    saida: dict[str, str] = {}
    for op in sorted(o for o in ops if o in registradas and o not in _fluxo.PROIBIDAS):
        esquema = registradas[op].esquema or {}
        obrigatorios = set(esquema.get("required") or [])
        partes = []
        for nome, spec in (esquema.get("properties") or {}).items():
            texto = nome + ("*" if nome in obrigatorios else "")
            if spec.get("enum"):
                texto += " (" + "|".join(map(str, spec["enum"])) + ")"
            elif spec.get("type") == "array":
                texto += " [lista]"
            partes.append(texto)
        saida[op] = " · ".join(partes) or "(sem argumentos)"
    return saida


# ── salvar_receita: o fluxo que se repete vira receita (F3, aba Fluxos, 2026-11-03) ──


def _texto(nome: str = "", descricao: str = "", parametros: dict | None = None, passos: list | None = None,
           titulo: str = "", condicoes: str = "", **_) -> str:
    return _receitas.texto_de(nome, descricao, parametros or {}, passos or [], titulo, condicoes)


def _conferir_receita(**entrada) -> str:
    """⭐ Roda ANTES do cartão: receita que não passa nunca chega ao editor para ele aprovar e ver falhar."""
    try:
        _receitas.conferir_texto(_texto(**entrada))
    except _receitas.ReceitaInvalida as e:
        return f"A receita não passa: {e}"
    return ""


@ferramenta(
    nome="salvar_receita",
    descricao=(
        "Guarda um fluxo como RECEITA do editor, para rodar de novo pela aba Fluxos (botão Preparar, sem "
        "modelo). Use quando o pedido se repete (a diária de cada dia). O que muda de uma vez para outra é "
        "PARÂMETRO — nunca o valor de hoje dentro dos passos. nome: minúsculas, dígitos e - (o mesmo de uma "
        "receita existente a substitui pela versão do editor). parametros: {nome: {tipo: texto|pasta|arquivo|"
        "escolha|numero|sim_nao, rotulo, padrao?, opcoes? (escolha)}}; passos: a MESMA lista do executar_fluxo "
        "([{id, op, args}], com \"{param}\" e \"{id.campo}\"); titulo pode usar {param}; condicoes: o que fazer "
        "quando um passo falha (texto curto, uma linha por caso). Para cada pasta/arquivo, \"{param_nome}\" é o "
        "nome dele sem extensão."
    ),
    esquema={
        "type": "object",
        "properties": {
            "nome": {"type": "string"},
            "titulo": {"type": "string"},
            "descricao": {"type": "string"},
            "parametros": {"type": "object"},
            "passos": {"type": "array", "items": {"type": "object"}},
            "condicoes": {"type": "string"},
        },
        "required": ["nome", "descricao", "parametros", "passos"],
    },
    escreve=True,
    conferir=_conferir_receita,
    nles=AMBOS,
)
def salvar_receita(nome: str, descricao: str, parametros: dict, passos: list, titulo: str = "",
                   condicoes: str = "") -> dict:
    try:
        destino = _receitas.salvar(_texto(nome, descricao, parametros, passos, titulo, condicoes))
    except (_receitas.ReceitaInvalida, OSError) as e:
        return {"erro": str(e)}
    return {"receita": nome, "arquivo": str(destino),
            "manchete": f"a receita '{nome}' foi guardada; ela aparece em Fluxos prontos",
            "agora": "Diga ao editor em uma linha que a receita está na lista da aba Fluxos."}
