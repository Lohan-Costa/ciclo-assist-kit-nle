"""A lista "A DECIDIR" da Carta Aberta (plano, C2 item 6 e resposta 2 do autor, 2026-11-12).

Empates e homônimos do "mandar" são do EDITOR (decisão do autor): o programa não escolhe, e também não pode só contar e
esquecer. Cada caso vira um fato `pendente` no diário — sobrevive a fechar a janela, e os outros editores o veem — e a
resposta vira um fato `resolvido` (só se acrescenta; nada se apaga):

    {"fato": "pendente", "caso": "empate"|"homonimo", "nome", "pasta", "visivel", "identidade", "entrou_por", "forma",
     "arquivo"/"volume"/"relativo" (onde, nesta máquina), "arquivos" (a OP-Atom: um por trilha),
     "candidatos": [{"id", "nome", "medida"}], "porque"}
    {"fato": "resolvido", "pendente": <id>, "resposta": "mesma"|"outra", "ref": <id da referência>}

- **é a mesma (que X):** o arquivo vira uma forma da referência X (e X volta à pasta, se estava fora da vista).
- **é outra:** uma referência NOVA (`referencias.criar(…, distinta=True)`), com o arquivo como forma.
⭐ E a TIMELINE com o mesmo nome e outro conteúdo (autor, 2026-11-20; `itens.registrar`): `caso: "timeline"`, com o
item novo guardado em `.carta/pendentes/` (uma timeline tem centenas de clipes: não cabe numa linha do diário) e as
respostas "atualizar" | "versionar" | "cancelar".

⛔ Só responde quem ALCANÇA o arquivo: a forma diz onde a mídia está NESTA máquina; sem o arquivo aqui, a resposta é
recusada dizendo em que máquina ele foi visto.
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from pathlib import Path

from . import diario, referencias
from .projeto import CartaErro, Projeto, gravar_json

PENDENTES = "pendentes"          # dentro da `.carta/`: o item de uma timeline que espera a resposta do editor
SUBSTITUIDOS = "substituidos"    # dentro da `.carta/`: o conteúdo de antes de cada "atualizar" (nada se apaga)
RESPOSTAS_DA_TIMELINE = ("atualizar", "versionar", "cancelar")


def guardar(proj: Projeto, caso: str, nome: str, pasta: str, visivel: bool, ident: dict, entrou_por: dict,
            arquivo: Path, arquivos: list[str] | None, candidatos: list[dict], porque: str) -> dict:
    """Guarda o caso (um só por arquivo enquanto não for respondido)."""
    lugar = referencias.onde(arquivo)
    for p in pendentes(proj):
        if p.get("arquivo") == lugar["arquivo"] and p.get("maquina") == diario.maquina():
            return p
    return diario.acrescentar(proj, {
        "fato": "pendente", "caso": caso, "nome": nome, "pasta": pasta, "visivel": visivel, "identidade": ident,
        "entrou_por": entrou_por, "forma": entrou_por.get("forma", "trabalho"), **lugar,
        "arquivos": list(arquivos or []), "candidatos": candidatos, "porque": porque})


def guardar_timeline(proj: Projeto, nome: str, pasta: str, item: dict, entrou_por: dict,
                     caminho_existente: Path, existente: dict) -> dict:
    """A pergunta "atualizar, versionar ou cancelar?" para a timeline `nome`. Uma por timeline: mandar de novo antes
    de responder troca o conteúdo guardado pelo mais recente (vale o último "mandar")."""
    from . import itens
    pasta_p = proj.interna / PENDENTES
    pasta_p.mkdir(parents=True, exist_ok=True)
    for p in pendentes(proj):
        if p.get("caso") == "timeline" and p.get("existente") == existente["id"]:
            gravar_json(pasta_p / p["guardado"], {"item": item, "entrou_por": entrou_por})
            return p
    guardado = f"{uuid.uuid4().hex}.json"
    gravar_json(pasta_p / guardado, {"item": item, "entrou_por": entrou_por})
    return diario.acrescentar(proj, {
        "fato": "pendente", "caso": "timeline", "nome": nome, "pasta": pasta, "existente": existente["id"],
        "onde": itens.onde_esta(proj, caminho_existente), "guardado": guardado, "entrou_por": entrou_por,
        "versao": itens.proximo_nome(proj, nome),
        "antes": itens.resumo(existente), "agora": itens.resumo(item),
        "porque": "já há uma timeline com este nome na Carta, com outro conteúdo"})


def _responder_timeline(proj: Projeto, caso: dict, resposta: str) -> dict:
    from . import itens
    if resposta not in RESPOSTAS_DA_TIMELINE:
        raise CartaErro(f"resposta desconhecida para a timeline: {resposta!r}")
    arq = proj.interna / PENDENTES / str(caso.get("guardado") or "")
    out = {"nome": caso["nome"], "resposta": resposta, "pasta": caso.get("pasta") or ""}
    if resposta == "cancelar":
        diario.acrescentar(proj, {"fato": "resolvido", "pendente": caso["id"], "resposta": "cancelar"})
        arq.unlink(missing_ok=True)
        return {**out, "mensagem": f"{caso['nome']}: cancelado, a timeline da Carta ficou como estava"}
    try:
        guardado = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise CartaErro(f"o conteúdo novo de {caso['nome']} não está mais guardado: mande a timeline de novo") from None
    item, entrou_por = guardado["item"], guardado.get("entrou_por") or caso.get("entrou_por") or {}
    if resposta == "atualizar":
        achado = next(((c, d) for c, d in itens.todos(proj) if d["id"] == caso.get("existente")), None)
        if achado is None:
            raise CartaErro(f"a timeline {caso['nome']} que existia saiu do projeto: escolha versionar")
        c, _ = achado
        antes = itens.ler(c) or {}
        copia = proj.interna / SUBSTITUIDOS
        copia.mkdir(parents=True, exist_ok=True)
        carimbo = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        gravar_json(copia / f"{antes.get('id', 'item')}-{carimbo}{itens.SUFIXO}", antes)
        gravar_json(c, {"carta_aberta": itens.FORMATO, "id": antes["id"], "nome": antes.get("nome") or caso["nome"],
                        **item, "entrou_por": entrou_por})
        diario.acrescentar(proj, {"fato": "atualizado", "item": antes["id"], "nle": entrou_por.get("nle", ""),
                                  "antes": caso.get("antes"), "agora": caso.get("agora")})
        msg, item_id = f"{caso['nome']}: atualizada ({caso.get('onde', '')}); a versão anterior foi guardada", antes["id"]
    else:
        nome = itens.proximo_nome(proj, caso["nome"])
        pasta = caso.get("pasta") or ""
        if not (proj.raiz / pasta).is_dir():
            pasta = ""
        _, dados, novo = itens.criar(proj, pasta, nome, item, entrou_por)
        msg = (f"{caso['nome']}: versionada como {dados['nome']}" if novo
               else f"{caso['nome']}: este conteúdo já estava na Carta como {dados['nome']}")
        item_id = dados["id"]
    diario.acrescentar(proj, {"fato": "resolvido", "pendente": caso["id"], "resposta": resposta, "item": item_id})
    arq.unlink(missing_ok=True)
    return {**out, "item": item_id, "mensagem": msg}


def pendentes(proj: Projeto) -> list[dict]:
    """Os casos ainda sem resposta, em ordem de chegada."""
    fatos = diario.fatos(proj)
    resolvidos = {f.get("pendente") for f in fatos if f["fato"] == "resolvido"}
    return [f for f in fatos if f["fato"] == "pendente" and f["id"] not in resolvidos]


def responder(proj: Projeto, pendente: str, resposta: str) -> dict:
    """`resposta` = o id de uma referência candidata ("é a mesma que…") ou "outra". Devolve {ref, nome, resposta}."""
    from . import anexar, vitrine
    from .vista import pasta_do_projeto, traduzir
    caso = next((p for p in pendentes(proj) if p["id"] == pendente), None)
    if caso is None:
        raise CartaErro("este caso já foi respondido (talvez por outro editor) ou não existe mais")
    if caso.get("caso") == "timeline":
        return _responder_timeline(proj, caso, resposta)
    arquivo = traduzir(caso)
    if not arquivo or not os.path.exists(arquivo):
        raise CartaErro(f"o arquivo {Path(str(caso.get('arquivo'))).name} não está acessível nesta máquina "
                        f"(foi visto em {caso.get('maquina')}): responda de lá, ou monte o disco")
    conta = anexar.Conta()
    pasta = caso.get("pasta") or ""
    try:
        destino = pasta_do_projeto(proj, pasta)
        if not destino.is_dir():
            raise CartaErro("")
    except CartaErro:
        pasta, destino = "", proj.raiz.resolve()               # a pasta do caso sumiu: a raiz, e é dito na resposta
    todas = {d["id"]: (c, d) for c, d in referencias.todas(proj)}
    arquivos = caso.get("arquivos") or None
    if resposta == "outra":
        if caso.get("visivel", True):
            _, ref = referencias.criar(proj, pasta, caso["nome"], caso.get("identidade") or {}, caso.get("entrou_por") or {},
                                       distinta=True)
        else:
            proj.ocultas.mkdir(parents=True, exist_ok=True)
            c, ref = referencias.criar(proj, proj.ocultas, caso["nome"], caso.get("identidade") or {},
                                       caso.get("entrou_por") or {}, distinta=True)
            vitrine.esconder(proj, c, ref, referencias.SUFIXO)
        por = "o editor disse: é outra mídia"
    else:
        if resposta not in {c.get("id") for c in caso.get("candidatos", [])} or resposta not in todas:
            raise CartaErro("essa referência não é um dos candidatos deste caso")
        c, ref = todas[resposta]
        if caso.get("visivel", True) and vitrine.oculta(proj, c):
            vitrine.mostrar_em(proj, c, ref, referencias.SUFIXO, destino)
        por = "o editor disse: é a mesma mídia"
    anexar._vincular(proj, ref["id"], caso.get("forma") or "trabalho", Path(arquivo), por, conta, arquivos=arquivos)
    diario.acrescentar(proj, {"fato": "resolvido", "pendente": pendente, "resposta": "outra" if resposta == "outra" else "mesma",
                              "ref": ref["id"]})
    return {"ref": ref["id"], "nome": ref["nome"], "resposta": resposta, "pasta": pasta}
