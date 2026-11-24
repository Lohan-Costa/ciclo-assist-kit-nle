"""O FLUXO COMO NODES E LIGAÇÕES, para a janela Fluxos e Agentes (fase N0 do plano `2026-11-08-janela-de-nodes.md`).

⭐ Sai da receita como ela é: nenhuma linha muda. A ligação de ORDEM vem da sequência dos passos; a de DADO, de `{passo.campo}`.
⭐ O agente gerente vira node porque o executor o chama de verdade antes de cada passo revisado (`fluxo._revisar_antes_do_sync`): a tela mostra o que acontece.
⛔ Sem posição aqui: quem organiza é a página, que sabe a largura de cada node.
"""

from __future__ import annotations

from typing import Any

from ..mcp.ferramentas.portao import rotulo as _rotulo
from ..motor.revisor_do_sync import AGENTE as _GERENTE
from ..piloto.auxilio import MAX_CONSULTAS as _MAX_CONSULTAS_DO_AGENTE
from . import catalogo_de_pecas as _catalogo
from . import fluxo as _fluxo
from . import receitas as _receitas

PROGRAMAS = {"resolve": "DaVinci Resolve", "premiere": "Premiere", "avid": "Media Composer", "media_composer": "Media Composer", "mc": "Media Composer"}


_NOMES_PROPRIOS = {"opatom": "OP-Atom", "premiere": "Premiere", "resolve": "Resolve"}


def _maiuscula(texto: str) -> str:
    return texto[:1].upper() + texto[1:]


#: Os nomes de argumento são ASCII; a tela, não.
_ACENTOS = {"versao": "versão", "metodo": "método", "referencia": "referência", "operacoes": "operações", "diaria": "diária"}


def _rotulo_do_campo(nome: str) -> str:
    return _maiuscula(" ".join(_ACENTOS.get(p, p) for p in nome.split("_")))


def _titulo_do_passo(op: str) -> str:
    return _maiuscula(" ".join(_NOMES_PROPRIOS.get(p, p) for p in _rotulo(op).split(" ")))


def _legivel(valor: Any, referencia) -> str:
    if isinstance(valor, str):
        return _fluxo._REF.sub(lambda m: f"‹{referencia(m.group(1))}›", valor)
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, list):
        return ", ".join(_legivel(v, referencia) for v in valor)
    if isinstance(valor, dict):
        if "nome" in valor:      # as `fontes` do sync: o nome de cada uma diz o bastante no painel
            return _legivel(valor["nome"], referencia)
        return ", ".join(f"{k}: {_legivel(v, referencia)}" for k, v in valor.items())
    return str(valor)


def _origem(valor: Any) -> str:
    refs = _fluxo._referencias(valor)
    return "node" if any("." in r for r in refs) else "perguntar" if refs else "fixo"


def _campos(args: dict[str, Any], referencia, peca: _catalogo.Peca | None) -> list[dict[str, str]]:
    campos = []
    for nome, valor in args.items():
        texto = PROGRAMAS.get(str(valor).lower(), str(valor)) if nome == "programa" else _legivel(valor, referencia)
        campos.append({"nome": _rotulo_do_campo(nome), "texto": texto, "origem": _origem(valor)})
    return campos + [{"nome": rotulo, "texto": valor, "origem": "travado"} for rotulo, valor in (peca.travados if peca else ())]


def _estilo(op: str, peca: _catalogo.Peca | None) -> str:
    return "ia" if peca and peca.agente else "pergunta" if op in (_fluxo.OP_PERGUNTAR, _fluxo.OP_CONFIRMAR) else ""


def _programa_da_peca(peca: _catalogo.Peca | None, args: dict[str, Any], nle_aberto: str) -> str:
    """A chave do programa que o passo ocupa, ou "" quando só se sabe ao rodar (um `{parametro}`) ou a peça não tem ficha."""
    if peca is None:
        return ""
    if peca.programa == _catalogo.DO_ARGUMENTO:
        programa = str(args.get("programa") or "").lower()
        return {"avid": _catalogo.MEDIA_COMPOSER, "mc": _catalogo.MEDIA_COMPOSER}.get(programa, programa if programa in PROGRAMAS else "")
    return nle_aberto if peca.programa == _catalogo.O_NLE_ABERTO else peca.programa


def _campos_do_piloto(peca: _catalogo.Peca | None) -> dict[str, Any]:
    if peca is None or not peca.piloto:
        return {"piloto": "", "piloto_se": None, "piloto_faz": ""}
    return {"piloto": peca.piloto, "piloto_se": list(peca.piloto_se) if peca.piloto_se else None, "piloto_faz": peca.piloto_faz}


def opera_a_tela(peca: _catalogo.Peca | None, programa: str, args: dict[str, Any]) -> bool:
    """O piloto pode operar a tela neste passo? ⭐ Pior caso: programa ou argumento que só se sabe ao rodar contam como sim, porque isto vira preço."""
    if peca is None or peca.piloto not in (_catalogo.PILOTO_SEMPRE, _catalogo.PILOTO_NO_MC):
        return False
    if peca.piloto == _catalogo.PILOTO_NO_MC and programa and programa != _catalogo.MEDIA_COMPOSER:
        return False
    if peca.piloto_se:
        campo, valor = peca.piloto_se
        atual = args.get(campo)
        return atual == valor or bool(_fluxo._referencias(atual))
    return True


def da_receita(passos: list[dict[str, Any]], parametros: dict[str, Any], agentes: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """`{nos, ligacoes}` de uma receita. Ligação: `{de, para, tipo: ordem|dado, campo}`. `agentes`: `{nome: {titulo, saidas}}`."""
    # ⛔ `op_atual`: receita gravada antes de uma renomeação traz o nome velho (`sincronizar_com_o_orbita`).
    rotulos = {str(p.get("id")): _titulo_do_passo(_fluxo.op_atual(str(p.get("op") or ""))) for p in passos}

    def referencia(ref: str) -> str:
        raiz, _, campo = ref.partition(".")
        if campo:
            return f"{rotulos.get(raiz, raiz)} · {campo.replace('_', ' ')}"
        return str((parametros.get(ref) or {}).get("rotulo") or ref.replace("_", " "))

    nos: list[dict[str, Any]] = []
    nle_aberto = ""
    for p in passos:
        pid, op, args = str(p.get("id")), _fluxo.op_atual(str(p.get("op") or "")), p.get("args") or {}
        if op in _fluxo.PASSOS_REVISADOS and not args.get("sem_supervisao"):
            gerente = agentes.get(_GERENTE) or {}
            nos.append({"id": f"agente_{pid}", "tipo": "agente", "agente": _GERENTE, "rotulo": gerente.get("titulo") or _GERENTE,
                        "detalhe": "usa IA", "campos": [], "args": {}, "programa": "", "saidas": [s.replace("_", " ") for s in gerente.get("saidas") or []], "catalogada": True})
        peca = _catalogo.CATALOGO.get(op)
        programa = _programa_da_peca(peca, args, nle_aberto)
        if op == "abrir_programa" and programa in (_catalogo.PREMIERE, _catalogo.MEDIA_COMPOSER):
            nle_aberto = programa
        nos.append({"id": pid, "tipo": "passo", "op": op, "rotulo": rotulos[pid],
                    "detalhe": PROGRAMAS.get(str(args.get("programa") or "").lower(), ""), "campos": _campos(args, referencia, peca), "args": args,
                    "programa": PROGRAMAS.get(programa, ""), "saidas": [s.replace("_", " ") for s in (peca.saidas if peca else ())], "catalogada": peca is not None,
                    "estilo": _estilo(op, peca), "agente": peca.agente if peca else "", **_campos_do_piloto(peca)})

    ligacoes: list[dict[str, Any]] = []
    com_gerente = {n["id"].removeprefix("agente_") for n in nos if n["tipo"] == "agente"}
    anterior = ""
    for p in passos:
        pid = str(p.get("id"))
        deps = p.get("depois_de") if isinstance(p.get("depois_de"), list) else ([anterior] if anterior else [])
        chega_em = f"agente_{pid}" if pid in com_gerente else pid
        for d in deps:      # ⭐ a condição desenha na linha que chega ao passo (ou ao gerente dele)
            ligacoes.append({"de": str(d), "para": chega_em, "tipo": "ordem", "campo": "", **({"se": p["se"]} if p.get("se") else {})})
        if pid in com_gerente:
            ligacoes.append({"de": chega_em, "para": pid, "tipo": "ordem", "campo": ""})
        v = p.get("volta")
        if isinstance(v, dict):
            ligacoes.append({"de": pid, "para": str(v.get("para")), "tipo": "ordem", "campo": "", "volta": True, "teto": v.get("teto", 2), **({"se": v["se"]} if v.get("se") else {})})
        anterior = pid
    for p in passos:
        for ref in dict.fromkeys(_fluxo._referencias(p.get("args") or {})):
            raiz, _, campo = ref.partition(".")
            if not campo or raiz not in rotulos:
                continue
            legivel = campo.replace("_", " ")
            colada = next((x for x in ligacoes if x["de"] == raiz and x["para"] == p.get("id")), None)
            if colada:      # o dado vem do node logo antes: uma linha só, senão seriam duas sobrepostas
                colada["campo"] = ", ".join(filter(None, (colada["campo"], legivel)))
            else:
                ligacoes.append({"de": raiz, "para": str(p.get("id")), "tipo": "dado", "campo": legivel})
    return {"nos": nos, "ligacoes": ligacoes, "ia": custo_de_ia(passos)}


def custo_de_ia(passos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """O preço antes do clique: o pior caso, com todas as voltas. `None` quando o fluxo não usa IA."""
    ids = [str(p.get("id")) for p in passos]
    vezes = {i: 1 for i in ids}
    for i, p in enumerate(passos):
        v = p.get("volta")
        if isinstance(v, dict) and v.get("para") in ids[:i]:
            for j in range(ids.index(v["para"]), i + 1):
                vezes[ids[j]] = 1 + int(v.get("teto") or 0)
    chamadas = tokens = segundos = gerentes = piloto = 0
    nle_aberto = ""
    for p in passos:
        op, args = _fluxo.op_atual(str(p.get("op") or "")), p.get("args") or {}
        if op in _fluxo.PASSOS_REVISADOS and not args.get("sem_supervisao"):
            chamadas, segundos, gerentes = chamadas + 1, segundos + _catalogo.SEGUNDOS_DO_GERENTE, gerentes + 1
        peca = _catalogo.CATALOGO.get(op)
        if peca and peca.agente:
            n = vezes[str(p.get("id"))]
            chamadas, tokens, segundos = chamadas + n, tokens + n * _catalogo.CUSTO_DO_AGENTE_DE_METADADO[0], segundos + n * _catalogo.CUSTO_DO_AGENTE_DE_METADADO[1]
        programa = _programa_da_peca(peca, args, nle_aberto)
        if op == "abrir_programa" and programa in (_catalogo.PREMIERE, _catalogo.MEDIA_COMPOSER):
            nle_aberto = programa
        if opera_a_tela(peca, programa, args):
            piloto += vezes[str(p.get("id"))]
    if not chamadas and not piloto:
        return None
    frases = []
    if chamadas:
        partes = [f"Usa IA em até {chamadas} chamada{'s' if chamadas > 1 else ''}, da sua assinatura"]
        if tokens:
            partes.append(f"cerca de {round(tokens / 1000)} mil tokens")
        partes.append(f"perto de {max(1, round(segundos / 60))} min de espera" if segundos >= 60 else f"perto de {segundos} s de espera")
        frases.append(", ".join(partes) + ".")
        frases.append("Estimado pelo que já foi medido." + (" O agente que confere as fontes não tem tokens medidos." if gerentes else ""))
    if piloto:
        frases.append(f"O piloto opera a tela em até {piloto} node{'s' if piloto > 1 else ''}: {_catalogo.CUSTO_DO_PILOTO} cada, da sua assinatura, medidos no Media Composer. Se o script travar, o agente do piloto olha a tela: {_catalogo.CUSTO_DO_AGENTE_DO_PILOTO} por consulta, até {_MAX_CONSULTAS_DO_AGENTE} por node.")
    return {"chamadas": chamadas, "piloto": piloto, "texto": " ".join(frases)}


def pecas() -> list[dict[str, Any]]:
    """O que o "Adicionar Node" oferece, com os campos do esquema de cada ferramenta."""
    from ..mcp import ferramentas as _registrar  # noqa: F401 — o import registra
    from ..mcp.registro import FERRAMENTAS

    saida = []
    for op, peca in _catalogo.CATALOGO.items():
        esquema = FERRAMENTAS[op].esquema or {}
        obrigatorios = set(esquema.get("required") or [])
        escondidos = _catalogo.SEMPRE_OCULTOS | set(peca.ocultos)
        campos = [{"nome": k, "rotulo": _rotulo_do_campo(k), "tipo": s.get("type") or "string", "obrigatorio": k in obrigatorios,
                   "opcoes": s.get("enum") or [], "descricao": s.get("description") or ""}
                  for k, s in (esquema.get("properties") or {}).items() if k not in escondidos]
        saida.append({"op": op, "rotulo": _titulo_do_passo(op), "programa": PROGRAMAS.get(peca.programa, ""), "programa_vem_do_argumento": peca.programa == _catalogo.DO_ARGUMENTO,
                      "saidas": list(peca.saidas), "campos": campos, "travados": [{"nome": r, "texto": v} for r, v in peca.travados], "estilo": _estilo(op, peca), "agente": peca.agente, **_campos_do_piloto(peca)})
    return saida


class GrafoInvalido(ValueError):
    def __init__(self, problemas: list[str]) -> None:
        super().__init__("; ".join(problemas))
        self.problemas = problemas


def para_passos(nos: Any, ligacoes: Any) -> list[dict[str, Any]]:
    """A lista de passos que o executor roda, em ordem topológica. ⭐ O gerente não é passo: o programa o põe de volta antes de cada sync.

    ⭐ `depois_de` só aparece quando difere de "depende do passo anterior": fluxo em linha continua sendo a mesma lista de sempre.
    ⛔ Volta ainda não existe (fase N4): é recusada com a frase, em vez de virar um fluxo que roda outra coisa."""
    if not isinstance(nos, list) or not isinstance(ligacoes, list) or not all(isinstance(n, dict) for n in nos) or not all(isinstance(x, dict) for x in ligacoes):
        raise GrafoInvalido(["o pedido não é um fluxo"])
    arestas = {(str(x.get("de")), str(x.get("para"))): {"se": x.get("se") or None, "teto": x.get("teto")} for x in ligacoes if x.get("de") != x.get("para")}
    for agente in [str(n.get("id")) for n in nos if n.get("tipo") == "agente"]:
        chegam = [(a, atr) for (a, b), atr in arestas.items() if b == agente]
        saem = [b for (a, b) in arestas if a == agente]
        arestas = {(a, b): atr for (a, b), atr in arestas.items() if agente not in (a, b)}
        arestas.update({(a, b): atr for a, atr in chegam for b in saem if a != b})
    passos = {str(n.get("id")): n for n in nos if n.get("tipo") != "agente"}
    if not passos:
        raise GrafoInvalido(["o fluxo não tem nenhum node"])
    arestas = {(a, b): atr for (a, b), atr in arestas.items() if a in passos and b in passos}
    nome = lambda i: str(passos[i].get("rotulo") or i)     # noqa: E731
    # ⭐ Se todo node tem linha chegando, a volta chega ao começo: o começo é o primeiro node do desenho.
    inicios = [i for i in passos if not any(b == i for _, b in arestas)] or list(passos)[:1]
    if len(inicios) > 1:
        raise GrafoInvalido(["o fluxo precisa de um node só no começo; estes estão sem nada chegando: " + ", ".join(nome(i) for i in inicios)])
    # A volta é a linha que chega a quem ainda está em aberto no caminho.
    seguintes = {i: [b for (a, b) in arestas if a == i] for i in passos}
    voltas: set[tuple[str, str]] = set()
    em_aberto: set[str] = set()
    vistos: set[str] = set()

    def visitar(i: str) -> None:
        vistos.add(i)
        em_aberto.add(i)
        for b in seguintes[i]:
            if b in em_aberto:
                voltas.add((i, b))
            elif b not in vistos:
                visitar(b)
        em_aberto.discard(i)

    visitar(inicios[0])
    avante = {k: v for k, v in arestas.items() if k not in voltas}
    pais = {i: [a for (a, b) in avante if b == i] for i in passos}
    condicoes = {i: [avante[(a, i)]["se"] for a in pais[i] if avante[(a, i)]["se"]] for i in passos}
    problemas = [f"{nome(i)} tem condição numa linha e recebe outra linha: a condição precisa ser a única chegada do node"
                 for i in passos if condicoes[i] and len(pais[i]) > 1]
    origens = [a for a, _ in voltas]
    problemas += [f"{nome(a)} tem mais de uma volta: cada node volta para um lugar só" for a in dict.fromkeys(origens) if origens.count(a) > 1]
    if problemas:
        raise GrafoInvalido(problemas)

    def alcance(de: str, mapa: dict[str, list[str]]) -> set[str]:
        achados, pilha = {de}, [de]
        while pilha:
            for b in mapa[pilha.pop()]:
                if b not in achados:
                    achados.add(b)
                    pilha.append(b)
        return achados

    para_frente = {i: [b for (a, b) in avante if a == i] for i in passos}
    para_tras = {i: [a for (a, b) in avante if b == i] for i in passos}
    no_laco = {n for a, b in voltas for n in alcance(b, para_frente) & alcance(a, para_tras)}
    ordem: list[str] = []
    while len(ordem) < len(passos):
        prontos = [i for i in passos if i not in ordem and all(a in ordem for a in pais[i])]
        if not prontos:
            fora = [nome(i) for i in passos if i not in ordem]
            raise GrafoInvalido(["estes nodes estão presos num círculo, fora do caminho: " + ", ".join(fora)])
        # ⭐ Quem está na volta vem antes: ela repete um trecho contínuo da lista, e nada de fora pode cair no meio.
        ordem.append(next((i for i in prontos if i in no_laco), prontos[0]))
    saida = []
    for n, i in enumerate(ordem):
        passo: dict[str, Any] = {"id": i, "op": str(passos[i].get("op") or ""), "args": passos[i].get("args") if isinstance(passos[i].get("args"), dict) else {}}
        if pais[i] != ([ordem[n - 1]] if n else []):
            passo["depois_de"] = pais[i]
        if condicoes[i]:
            passo["se"] = condicoes[i][0]
        for (a, b) in voltas:
            if a == i:
                atr = arestas[(a, b)]
                passo["volta"] = {"para": b, "teto": atr["teto"] if atr["teto"] is not None else 2, **({"se": atr["se"]} if atr["se"] else {})}
        saida.append(passo)
    return saida


#: Quem cria uma bin que um sync depois procura.
_CRIAM_BIN = ("importar_masters_opatom", "som_direto_gerenciado", "importar_no_premiere")


def avisos(corpo: dict[str, Any]) -> list[str]:
    """O que passa nas regras e provavelmente vai dar errado ao rodar. ⭐ Só avisa: a bin pode já existir no projeto."""
    try:
        passos = para_passos(corpo.get("nos"), corpo.get("ligacoes"))
    except GrafoInvalido:
        return []
    saida: list[str] = []
    criadas: list[Any] = []
    rotulos = {str(n.get("id")): str(n.get("rotulo") or n.get("id")) for n in corpo.get("nos") or []}
    for p in passos:
        if p["op"] in _CRIAM_BIN:
            criadas.append(p["args"].get("bin"))
        elif p["op"] in _fluxo.PASSOS_REVISADOS and criadas and all(isinstance(b, str) and "." not in b for b in criadas):
            fontes = p["args"].get("fontes")
            for f in fontes if isinstance(fontes, list) else []:
                for b in (f.get("bins") or []) if isinstance(f, dict) else []:
                    if isinstance(b, str) and "." not in b and b not in criadas:
                        saida.append(f"{rotulos.get(p['id'], p['id'])} procura a bin {b}, que nenhum node anterior cria.")
    return saida


def receita_da_janela(corpo: dict[str, Any]) -> tuple[str, list[str]]:
    """`(texto do .md, problemas)`. ⭐ O texto sai pelo mesmo escritor e passa pelo mesmo leitor das receitas de sempre."""
    titulo = " ".join(str(corpo.get("titulo") or "").split())
    if not titulo:
        return "", ["dê um nome ao fluxo"]
    parametros = corpo.get("parametros") if isinstance(corpo.get("parametros"), dict) else {}
    conhecidos = set(parametros) | set(_receitas.derivados({k: v for k, v in parametros.items() if isinstance(v, dict)}))
    desconhecidos = [r for r in _fluxo._REF.findall(titulo) if r not in conhecidos]
    if desconhecidos:
        return "", [f"o nome do fluxo usa {{{r}}}, que não é uma pergunta deste fluxo" for r in desconhecidos]
    try:
        passos = para_passos(corpo.get("nos"), corpo.get("ligacoes"))
    except GrafoInvalido as e:
        return "", e.problemas
    usados = {r.split(".", 1)[0] for r in _fluxo._REF.findall(titulo) + _fluxo._referencias([p["args"] for p in passos])}
    parametros = {k: v for k, v in parametros.items() if k in usados or f"{k}_nome" in usados}      # o que sobrou de um campo que o editor mudou não vira pergunta
    atual = _receitas.buscar(str(corpo.get("nome") or ""))
    if atual:
        nome = atual.nome
    else:
        base = _receitas._slug(_fluxo._REF.sub(" ", titulo))
        existentes, nome, n = set(_receitas.todas()), base, 2
        while nome in existentes:
            nome, n = f"{base}-{n}", n + 1
    texto = _receitas.texto_de(nome, atual.descricao if atual else "Criado na janela Fluxos e Agentes.", parametros, passos, titulo, atual.condicoes if atual else "")
    try:
        return texto, _receitas.ler_texto(texto, "editor").problemas
    except _receitas.ReceitaInvalida as e:
        return "", [str(e)]
