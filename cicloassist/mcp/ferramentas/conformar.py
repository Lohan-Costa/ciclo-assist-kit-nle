"""Levar uma timeline ao DaVinci Resolve — pelo De Lá Pra Cá, que é quem sabe fazer isso.

⭐⭐ **O mesmo desenho do Sincronizar** (`sincronizar.py` desta pasta), decisão do autor em 2026-10-29:
o Ciclo Assist orquestra, o De Lá Pra Cá processa. O editor arrasta para o chat o projeto
(`.prproj`), o vídeo de referência e a pasta das mídias, e pede "leva para o Resolve".

⭐⭐ **Quem diz o que é cada arrasto é o CÓDIGO, não o modelo** (`separar_os_arrastos`): a
extensão diz a timeline, o vídeo diz a referência, a pasta diz onde estão as mídias. É
regra fixa e barata — pedir ao modelo para classificar seria um turno gasto numa conta que
não muda, e uma escolha que muda de um modelo para outro.

⛔ **Só o que foi arrastado** (ADR 0005): caminho que o modelo escreve e o editor não
arrastou é recusado. A PASTA arrastada aqui é dada ao De Lá Pra Cá para ele procurar as
mídias nela — é o pedido do editor ("as mídias estão aqui"); o Ciclo Assist não lê o
conteúdo dela.

⚠️ O De Lá Pra Cá **não abre o Resolve**: a conferência antes do cartão pergunta a ele se o
Studio está aberto e com projeto, e recusa com a frase dele — descobrir depois de analisar
oitenta planos seria fazer o editor esperar por nada.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ... import delapraca as _dlpc
from ...servico import arrastados as _arrastados
from ...servico import pendencias as _pendencias
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.conformar")

#: O que o De Lá Pra Cá abre como timeline (`/receber/abrir`).
TIMELINES = {".prproj", ".aaf", ".avb"}

#: O que vale como vídeo de referência (o export do corte, para a conferência quadro a quadro).
VIDEOS = {".mov", ".mp4", ".mxf", ".m4v", ".avi", ".mkv"}

#: Quantos avisos do De Lá Pra Cá vão ao modelo — o resto é contado, não listado.
AVISOS_NA_RESPOSTA = 8


def separar_os_arrastos(caminhos: list[str]) -> dict[str, list[str]]:
    """Cada caminho arrastado no seu papel: timeline, referência, pasta das mídias, ou outro."""
    papeis: dict[str, list[str]] = {"timeline": [], "referencia": [], "pastas": [], "outros": []}
    for c in caminhos:
        p = Path(c)
        if p.is_dir():
            papeis["pastas"].append(c)
        elif p.suffix.lower() in TIMELINES:
            papeis["timeline"].append(c)
        elif p.suffix.lower() in VIDEOS:
            papeis["referencia"].append(c)
        else:
            papeis["outros"].append(c)
    return papeis


def e_timeline(caminho: str) -> bool:
    return Path(caminho).suffix.lower() in TIMELINES


def _o_material(projeto: str = "", referencia: str = "", pastas: list[str] | None = None) -> dict[str, object]:
    """O que vai ao De Lá Pra Cá: o que o modelo passou (se arrastado) ou o que os arrastos dizem."""
    pedidos = [c for c in [projeto, referencia, *(pastas or [])] if c]
    for c in pedidos:
        if not _arrastados.autorizado(c):
            return {"erro": _arrastados.recusa(c)}
    papeis = separar_os_arrastos(_arrastados.arquivos())
    timeline = projeto or (papeis["timeline"][0] if papeis["timeline"] else "")
    ref = referencia or (papeis["referencia"][0] if papeis["referencia"] else "")
    return {"timeline": timeline, "referencia": ref, "pastas": list(pastas or papeis["pastas"]),
            "papeis": papeis}


def _conferir(projeto: str = "", referencia: str = "", pastas: list[str] | None = None, **_) -> str:
    """Roda ANTES do cartão: sem timeline, sem De Lá Pra Cá ou sem Resolve, nem mostra."""
    m = _o_material(projeto, referencia, pastas)
    if m.get("erro"):
        return str(m["erro"])
    if not m["timeline"]:
        return ("Não chegou o arquivo da timeline. Peça ao editor para arrastar o projeto "
                "(.prproj, .aaf ou .avb) para o chat junto com a referência e a pasta das mídias.")
    try:
        _dlpc.saude()
    except (_dlpc.DelaPracaIndisponivel, _dlpc.DelaPracaFalhou) as e:
        return str(e)
    try:
        _dlpc.resolve_aberto()
    except (_dlpc.DelaPracaIndisponivel, _dlpc.DelaPracaFalhou) as e:
        # ⭐ O Resolve fechado não é beco: o Ciclo Assist sabe abri-lo (`abrir_programa`) —
        #   desde que o editor tenha dito "Resolve" (a regra mora lá, e vale no automático).
        return (f"{e}. Se o editor pediu o Resolve, chame abrir_programa(programa='resolve', "
                f"projeto='{Path(m['timeline']).stem}') e depois conformar_no_resolve de novo; "
                f"se ele não disse para qual programa levar, pergunte.")
    return ""


def _escolher_a_sequencia(sequencias: list[dict], pedida: str) -> tuple[dict | None, str]:
    """A pedida pelo nome; sem nome, a de MAIS planos — e a escolha é dita."""
    if not sequencias:
        return None, "o projeto não tem sequência"
    if pedida:
        for s in sequencias:
            if str(s.get("nome") or "").casefold() == pedida.casefold():
                return s, ""
        nomes = ", ".join(str(s.get("nome")) for s in sequencias)
        return None, f"não há sequência '{pedida}' no projeto; há: {nomes}"
    # ⭐ Um .prproj real traz o aninhado ao lado do corte (MEDIDO no PRODC: `transicao-pesoa`,
    #   0 s e 3 planos, junto do `PRODC_CORTE02`, 1:06 e 88). O corte é o de mais planos.
    return max(sequencias, key=lambda s: int(s.get("planos") or 0)), ""


def _resumo(seq: dict, outras: list[str], m: dict, r: dict) -> dict[str, object]:
    """O que o modelo precisa para responder ao editor — números, não as listas do DLPC."""
    an, p, imp = r.get("analisar") or {}, r.get("preparar") or {}, r.get("importar") or {}
    conf = r.get("conferencia") or {}
    avisos = [str(a) for a in p.get("avisos") or []]
    saida: dict[str, object] = {
        "sequencia": seq.get("nome"),
        "outras_sequencias_do_projeto": outras,
        "timeline_no_resolve": imp.get("nome"),
        "importou": bool(imp.get("ok")),
        "planos": an.get("planos"),
        "midias": {"no_original": an.get("no_original"), "arquivos": an.get("arquivos"),
                   "faltam": an.get("faltam") or [], "offline": p.get("offline")},
        "pastas_das_midias": m["pastas"] or an.get("pastas"),
        "efeitos_lidos": an.get("efeitos"),
        "no_resolve": {
            "fusion": (r.get("fusion") or {}).get("criadas"),
            "luts": (r.get("luts") or {}).get("aplicadas"),
            "compostos": (r.get("compostos") or {}).get("criados"),
            "reescalados": p.get("reescalados"),
            "marcadores": p.get("marcadores"),
        },
        "audio": {k: (an.get("audio") or {}).get(k) for k in ("clipes", "trilhas")},
        "avisos": avisos[:AVISOS_NA_RESPOSTA],
        "tempos_s": r.get("tempos"),
    }
    if len(avisos) > AVISOS_NA_RESPOSTA:
        saida["avisos_a_mais"] = len(avisos) - AVISOS_NA_RESPOSTA
    if m["referencia"]:
        saida["referencia"] = Path(m["referencia"]).name
        if conf.get("erro"):
            saida["conferencia"] = {"erro": conf["erro"]}
        elif conf:
            saida["conferencia"] = {"pontos": conf.get("total"), "conferem": conf.get("conferem"),
                                    "nao_conferem": conf.get("nao_conferem")}
    else:
        saida["conferencia"] = "sem vídeo de referência, nada foi conferido"
    if m["papeis"]["outros"]:
        saida["arrastos_sem_papel"] = [Path(c).name for c in m["papeis"]["outros"]]
    # ⭐ A MANCHETE primeiro (pilotado em 2026-10-29): a resposta era longa e o "144 de 144" rolava para
    #   fora da tela — o único número que diz se o conform deu certo. Quem a monta é o código, não o
    #   modelo: ela sai igual em todo modelo, e o modelo só acrescenta o que precisa de atenção.
    return {"manchete": _manchete(saida), "como_responder": COMO_RESPONDER, **saida}


#: O que o modelo faz com o resultado. Curto de propósito: cada frase aqui vai em todo conform.
COMO_RESPONDER = ("Comece a resposta pela manchete, como está. Depois, no máximo três linhas: só o que "
                  "pede atenção do editor (mídia faltando, ponto que não confere, aviso). Não repita os "
                  "números de efeitos e tempos se nada falhou.")


def _manchete(r: dict) -> str:
    """'144 de 144 pontos conferem · PRODC_CORTE02 no Resolve · 80 planos, nada faltando'."""
    partes = []
    conf = r.get("conferencia")
    if isinstance(conf, dict) and "erro" in conf:
        partes.append("a conferência falhou")
    elif isinstance(conf, dict) and conf.get("pontos"):
        partes.append(f"{conf.get('conferem') or 0} de {conf['pontos']} pontos conferem")
    else:
        partes.append("sem conferência (não veio vídeo de referência)")
    partes.append(f"{r.get('timeline_no_resolve') or r.get('sequencia')} no Resolve" if r.get("importou")
                  else "a timeline NÃO foi importada")
    faltam = len((r.get("midias") or {}).get("faltam") or [])
    planos = f"{r['planos']} planos, " if r.get("planos") else ""
    partes.append(planos + (f"{faltam} mídia(s) faltando" if faltam else "nada faltando"))
    return " · ".join(partes)


@ferramenta(
    nome="conformar_no_resolve",
    descricao=(
        "Leva uma timeline ao DaVinci Resolve pelo De Lá Pra Cá: lê o projeto (.prproj, .aaf "
        "ou .avb), acha as mídias, importa a timeline num projeto do Resolve com os efeitos "
        "traduzidos (velocidade, Fusion, LUTs, compostos, áudio) e confere quadro a quadro "
        "contra o vídeo de referência. Use SEMPRE que o editor arrastar um projeto para o chat "
        "e pedir para levá-lo ao Resolve (conformar, importar, abrir no Resolve). Chame SEM "
        "argumentos: a ferramenta separa sozinha o que foi arrastado (o projeto é a timeline, "
        "o vídeo é a referência, a pasta é onde estão as mídias) e escolhe a sequência de mais "
        "planos. Passe sequencia só se o editor nomear uma. Leva minutos. O Resolve Studio "
        "precisa estar aberto com um projeto."
    ),
    esquema={
        "type": "object",
        "properties": {
            "sequencia": {"type": "string",
                          "description": "Nome da sequência, se o editor nomeou uma. Vazio = a de mais planos."},
            "projeto": {"type": "string", "description": "Opcional: o arquivo da timeline arrastado."},
            "referencia": {"type": "string", "description": "Opcional: o vídeo de referência arrastado."},
            "pastas": {"type": "array", "items": {"type": "string"},
                       "description": "Opcional: pastas arrastadas onde estão as mídias."},
            "ajustar_escalas": {"type": "boolean", "default": True,
                                "description": "Refazer pela regra do Resolve a escala digitada para outra mídia (o 'Ajustar todos' do De Lá Pra Cá)."},
        },
    },
    escreve=True,
    conferir=_conferir,
    nles=AMBOS,
)
def conformar_no_resolve(sequencia: str = "", projeto: str = "", referencia: str = "",
                         pastas: list[str] | None = None,
                         ajustar_escalas: bool = True) -> dict[str, object]:
    m = _o_material(projeto, referencia, pastas)
    if m.get("erro"):
        return {"erro": m["erro"]}
    if not m["timeline"]:
        return {"erro": "não chegou o arquivo da timeline (.prproj, .aaf ou .avb)"}

    def contando(etapa: str, fracao: float | None, detalhe: str = "") -> None:
        # ⭐ Cancelar no meio (autor, 2026-11-04): o relato do De Lá Pra Cá chega entre um ponto e outro
        #   do conform — é onde parar de esperar é seguro (a timeline fica pela metade NO RESOLVE, e o
        #   passo diz isso).
        _pendencias.conferir_cancelamento("o conform do De Lá Pra Cá")
        _turno.avisar(etapa, fracao, detalhe)

    try:
        contando("o De Lá Pra Cá está abrindo o projeto", None, Path(m["timeline"]).name)
        aberto = _dlpc.abrir(m["timeline"])
        seqs = aberto.get("sequencias") or []
        seq, porque = _escolher_a_sequencia(seqs, sequencia)
        if not seq:
            return {"erro": porque}
        outras = [str(s.get("nome")) for s in seqs if s is not seq]
        # ⭐ Sem pasta arrastada, a que o próprio De Lá Pra Cá deduziu do projeto.
        pastas_finais = m["pastas"] or list(aberto.get("pastas") or [])
        resultado = _dlpc.conformar(aberto["chave"], str(seq["mob_id"]), pastas_finais,
                                    referencia=m["referencia"], aceitar_escalas=ajustar_escalas,
                                    relatar=contando)
    except (_dlpc.DelaPracaIndisponivel, _dlpc.DelaPracaFalhou) as e:
        return {"erro": str(e)}

    saida = _resumo(seq, outras, {**m, "pastas": pastas_finais}, resultado)
    if saida["importou"]:
        saida["agora"] = (f"A timeline '{saida['timeline_no_resolve']}' está no projeto aberto do "
                          f"Resolve, na pasta 'De Lá Pra Cá' do Media Pool. Diga ao editor o que foi "
                          f"traduzido e o que a conferência achou.")
    return saida


# ── o BASELIGHT (proposta 2026-11-22-baselight-no-app, etapa 4) ──────────────────────────────────────────────────────

#: o que o De Lá Pra Cá conforma no Baselight por aqui: o projeto do Premiere e o xmeml da Carta Aberta (o AAF e a bin
#: do MC passam pelo relink por master, que pede a revisão no painel — ⬜ no fluxo automatizado)
TIMELINES_BASELIGHT = {".prproj", ".xml"}


def _conferir_baselight(projeto: str = "", pastas: list[str] | None = None, **_) -> str:
    m = _o_material(projeto, "", pastas)
    if m.get("erro"):
        return str(m["erro"])
    tl = m["timeline"] or next((c for c in _arrastados.arquivos() if Path(c).suffix.lower() == ".xml"), "")
    if not tl:
        return "Não chegou o arquivo da timeline. Peça ao editor para arrastar o projeto (.prproj) ou o xmeml da Carta."
    if Path(tl).suffix.lower() not in TIMELINES_BASELIGHT:
        return ("Para o Baselight, por aqui, vão o projeto do Premiere (.prproj) e a timeline da Carta Aberta (.xml). "
                "O AAF e a bin do Media Composer passam pelo De Lá Pra Cá na aba Conformar (o relink pede a revisão).")
    try:
        _dlpc.saude()
    except (_dlpc.DelaPracaIndisponivel, _dlpc.DelaPracaFalhou) as e:
        return str(e)
    from ...carta import entrega_baselight as _bl
    ok, porque = _bl._motor().disponivel()
    return "" if ok else porque


@ferramenta(
    nome="conformar_no_baselight",
    descricao=(
        "Conforma uma timeline no Baselight pelo De Lá Pra Cá: casa cada plano com o ORIGINAL de câmera nas pastas, "
        "conforma numa scene NOVA do job da produção (nunca por cima: 'import 02'), confere cada plano (o arquivo, o 1º e "
        "o último quadro visível), corrige o que o Baselight casou sozinho e marca o que não se corrige. Use quando o "
        "editor pedir para levar ao Baselight / à cor. ⭐ O job é o da PRODUÇÃO: passe o que o pedido ou o fluxo trouxer; "
        "sem ele, o nome da produção que o editor disse; nunca pergunte o job no meio de um fluxo automatizado. "
        "Timeline: .prproj ou o .xml da Carta Aberta (o AAF do MC vai pela aba Conformar). Leva minutos. "
        "ATUALIZAR um corte que o colorista já corrigiu: passe `atualizar` = a scene dele (no mesmo job); a cor vem "
        "plano a plano e a resposta diz os planos sem cor e os markers dele que ficaram para trás — conte isso."
    ),
    esquema={
        "type": "object",
        "properties": {
            "job": {"type": "string", "description": "O job do Baselight (a produção). Um nome novo cria o job."},
            "sequencia": {"type": "string", "description": "Nome da sequência, se o editor nomeou uma."},
            "projeto": {"type": "string", "description": "Opcional: o arquivo da timeline arrastado."},
            "pastas": {"type": "array", "items": {"type": "string"},
                       "description": "Opcional: as pastas arrastadas onde estão os originais."},
            "markers": {"type": "boolean", "default": True,
                        "description": "Marcar na scene os planos com problema ([Ciclo] + o motivo)."},
            "atualizar": {"type": "string",
                          "description": "ATUALIZAR CORTE: a scene do colorista (no mesmo job) cuja cor vai para a "
                                         "scene nova — Multi-Paste + a conferência do Ciclo; o plano que ele dividiu é "
                                         "dividido igual; os markers dele vão pela fonte. Vazio = timeline nova, sem cor."},
        },
        "required": ["job"],
    },
    escreve=True,
    conferir=_conferir_baselight,
    nles=AMBOS,
)
def conformar_no_baselight(job: str, sequencia: str = "", projeto: str = "", pastas: list[str] | None = None,
                           markers: bool = True, atualizar: str = "") -> dict[str, object]:
    m = _o_material(projeto, "", pastas)
    if m.get("erro"):
        return {"erro": m["erro"]}
    tl = m["timeline"] or next((c for c in _arrastados.arquivos() if Path(c).suffix.lower() == ".xml"), "")
    if not tl or Path(tl).suffix.lower() not in TIMELINES_BASELIGHT:
        return {"erro": "não chegou o projeto do Premiere (.prproj) nem a timeline da Carta (.xml)"}

    def contando(etapa: str, fracao: float | None, detalhe: str = "") -> None:
        _pendencias.conferir_cancelamento("o conform no Baselight")
        _turno.avisar(etapa, fracao, detalhe)

    try:
        contando("o De Lá Pra Cá está abrindo a timeline", None, Path(tl).name)
        aberto = _dlpc.abrir(tl)
        seqs = aberto.get("sequencias") or []
        seq, porque = _escolher_a_sequencia(seqs, sequencia)
        if not seq:
            return {"erro": porque}
        pastas_finais = m["pastas"] or list(aberto.get("pastas") or [])
        r = _dlpc.conformar_no_baselight(aberto["chave"], str(seq["mob_id"]), pastas_finais, job=job,
                                         markers=markers, relatar=contando, atualizar=atualizar)
    except (_dlpc.DelaPracaIndisponivel, _dlpc.DelaPracaFalhou) as e:
        return {"erro": str(e)}
    b = r["baselight"]
    c = b.get("contagem") or {}
    problemas = b.get("problemas") or []
    return {"sequencia": seq.get("nome"), "job": b.get("job"), "job_criado": b.get("job_criado"),
            "scene": b.get("scene"), "planos": b.get("planos"), "certos": c.get("ok", 0),
            "corrigidos": b.get("trocados"), "markers": b.get("markers"),
            "a_conferir": problemas[:AVISOS_NA_RESPOSTA],
            "a_conferir_fora_da_lista": max(0, len(problemas) - AVISOS_NA_RESPOSTA),
            "pastas": pastas_finais, "tempos": r.get("tempos"),
            **({"cor_do_colorista": {k: (b.get("atualizar") or {}).get(k) for k in
                                     ("colorista", "conferidos", "de", "divididos", "marcas_movidas", "marcas_perdidas",
                                      "grupos")},
                "planos_sem_cor": [p for p in (b.get("atualizar") or {}).get("planos", [])
                                   if p.get("estado") in ("sem cor", "limpa")][:AVISOS_NA_RESPOSTA],
                "planos_so_com_o_look": [p for p in (b.get("atualizar") or {}).get("planos", [])
                                         if p.get("estado") == "só o look"][:AVISOS_NA_RESPOSTA]}
               if b.get("atualizar") else {}),
            "agora": (f"A scene '{b.get('scene')}' está no job '{b.get('job')}' do Baselight. Diga ao editor quantos "
                      f"planos ficaram certos, quais foram corrigidos e quais pedem conferência (com o motivo).")}
