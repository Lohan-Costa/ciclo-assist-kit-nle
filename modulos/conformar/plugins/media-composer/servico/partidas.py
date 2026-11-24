"""As CARTAS DE PARTIDA do "Atualizar timeline": qual envio gerou qual timeline, NESTA máquina.

Organograma aprovado pelo autor em 2026-09-27. Ao Trazer uma timeline pelo Magic Link, a Carta é
copiada para `pasta_dados()/partidas/<id>.carta` e anotada em `partidas.json` com a timeline que
ela gerou no NLE (o id e o nome que o NLE deu). Quando chega uma Carta nova, o Atualizar compara com
ESTA cópia — nunca com a timeline de trabalho (os cortes do colorista não são mudança da montagem).

Por que copiar e não apontar para `importado/` do canal: a pasta combinada é da equipe (alguém
limpa, move, a rede cai); a partida precisa estar aqui enquanto a timeline de trabalho existir.

Qual timeline a Carta nova atualiza é SUGERIDO, não decidido: o editor costuma DUPLICAR a sequência
a cada versão (PRODA_CORTE.02 → .03), e o mob id muda. A sugestão ordena por: a mesma sequência
(mob id) → o mesmo nome sem o número da versão → a mais recente. Quem escolhe é quem recebe.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import plataforma

PASTA = "partidas"
INDICE = "partidas.json"
RE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
#: "PRODA_CORTE.02", "PRODA_CORTE v3", "PRODA_CORTE_03" → "cruz_corte": o nome sem a versão.
_VERSAO = re.compile(r"[\s._-]*(v|ver|versao|versão)?[\s._-]*\d+\s*$", re.IGNORECASE)


def _pasta() -> Path:
    p = plataforma.pasta_dados() / PASTA
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ler() -> list[dict]:
    try:
        d = json.loads((_pasta() / INDICE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [x for x in d if isinstance(x, dict) and RE_ID.match(str(x.get("id") or ""))] \
        if isinstance(d, list) else []


def _gravar(lista: list[dict]) -> None:
    alvo = _pasta() / INDICE
    tmp = alvo.with_name(f"{INDICE}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, alvo)


def base_do_nome(nome: str) -> str:
    return _VERSAO.sub("", (nome or "").strip()).strip().lower()


def guardar(id_envio: str, carta_arquivo: str, resumo: dict, timeline: dict | None,
            familia: str = "avid") -> dict:
    """Copia a Carta e anota a timeline que ela gerou. `timeline` = `{uid, nome}` da casca."""
    if not RE_ID.match(id_envio or ""):
        raise ValueError("envio inválido")
    destino = _pasta() / f"{id_envio}.carta"
    shutil.copyfile(carta_arquivo, destino)
    return _anotar(id_envio, resumo, timeline, familia)


def guardar_doc(doc: dict, resumo: dict, timeline: dict | None, familia: str = "avid") -> dict:
    """Uma versão que NÃO veio pelo canal (um arquivo aberto do disco, organograma de 2026-09-28):
    a Carta que o serviço montou dele vira a partida, com um id novo. A próxima atualização desta
    timeline sugere ela sozinha."""
    import uuid

    id_novo = str(uuid.uuid4())
    alvo = _pasta() / f"{id_novo}.carta"
    tmp = alvo.with_name(f"{id_novo}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, alvo)
    return _anotar(id_novo, resumo, timeline, familia)


def _anotar(id_envio: str, resumo: dict, timeline: dict | None, familia: str) -> dict:
    t = timeline if isinstance(timeline, dict) else {}
    item = {"id": id_envio, "timeline_uid": str(t.get("uid") or "")[:80],
            "timeline_nome": str(t.get("nome") or resumo.get("nome") or "")[:200],
            "sequencia": str(resumo.get("sequencia") or "")[:200],
            "mob_id": str(resumo.get("mob_id") or "")[:200],
            "canal": str(resumo.get("canal") or "")[:40],
            "enviado_em": str(resumo.get("enviado_em") or "")[:40],
            "familia": str(familia or "avid")[:20],
            "trazido_em": datetime.now().astimezone().isoformat(timespec="microseconds")}
    lista = [x for x in _ler() if x["id"] != id_envio] + [item]
    _gravar(lista)
    return item


def aposentar(id_envio: str) -> None:
    """A partida que uma atualização SUBSTITUIU sai da lista: a timeline dela foi para o Backup, e
    oferecê-la de novo levaria a atualizar o backup (revisão 2026-09-28). A cópia da Carta fica."""
    if RE_ID.match(id_envio or ""):
        _gravar([x for x in _ler() if x["id"] != id_envio])


def listar() -> list[dict]:
    """As partidas cuja cópia da Carta ainda existe, da mais recente para a mais antiga."""
    pasta = _pasta()
    return sorted((x for x in _ler() if (pasta / f"{x['id']}.carta").is_file()),
                  key=lambda x: (x.get("trazido_em") or "", x.get("enviado_em") or ""), reverse=True)


def familia(id_envio: str) -> str:
    """O formato de origem da partida ("avid" = Carta ou bin; as antigas não anotavam: eram Cartas)."""
    return next((str(x.get("familia") or "avid") for x in _ler() if x["id"] == id_envio), "avid")


def da_timeline(uid: str, nome: str) -> list[dict]:
    """As partidas desta timeline de trabalho (pelo id que o NLE deu; sem ele, pelo nome), a mais
    recente primeiro. É como o Atualizar sugere a versão ANTIGA (organograma de 2026-09-28).

    ⚠️ O id sozinho não decide: pela ponte do Resolve, duas timelines já devolveram o MESMO id
    (medido 2026-09-28, banco `resolve-scripting/api-scripting.md` §7). Primeiro o par id + nome;
    depois o nome; o id sozinho só se nenhuma outra timeline o tiver."""
    todas = listar()
    mesmo_nome = lambda x: bool(nome) and (x.get("timeline_nome") or "").casefold() == nome.casefold()
    par = [x for x in todas if uid and x.get("timeline_uid") == uid and mesmo_nome(x)]
    if par:
        return [{**x, "motivo": "desta_timeline"} for x in par]
    pelo_nome = [x for x in todas if mesmo_nome(x)]
    if pelo_nome:
        return [{**x, "motivo": "mesmo_nome_de_timeline"} for x in pelo_nome]
    # renomeada no Resolve: o id ainda aponta, se ele não se repete entre timelines diferentes
    por_uid = [x for x in todas if uid and x.get("timeline_uid") == uid]
    if len({(x.get("timeline_nome") or "").casefold() for x in por_uid}) == 1:
        return [{**x, "motivo": "desta_timeline"} for x in por_uid]
    return []


def carta(id_envio: str) -> Path:
    if not RE_ID.match(id_envio or ""):
        raise ValueError("partida inválida")
    p = _pasta() / f"{id_envio}.carta"
    if not p.is_file():
        raise LookupError("a Carta de partida não está mais nesta máquina — traga como nova")
    return p


def sugerir(resumo_nova: dict) -> list[dict]:
    """As partidas que a Carta nova pode atualizar, da mais provável para a menos.
    Cada uma ganha `motivo`: `mesma_sequencia`, `mesmo_nome` ou `recente`."""
    mob = str(resumo_nova.get("mob_id") or "")
    base = base_do_nome(resumo_nova.get("sequencia") or resumo_nova.get("nome") or "")
    fora = []
    for x in listar():
        if x["id"] == resumo_nova.get("id"):
            continue
        if mob and x.get("mob_id") == mob:
            motivo, peso = "mesma_sequencia", 0
        elif base and base in (base_do_nome(x.get("sequencia") or ""), base_do_nome(x.get("timeline_nome") or "")):
            motivo, peso = "mesmo_nome", 1
        else:
            motivo, peso = "recente", 2
        fora.append((peso, {**x, "motivo": motivo}))
    return [x for _p, x in sorted(fora, key=lambda t: t[0])]


# ── as faixas de mudança (Ajustes; de fábrica 25% e 60%, aprovado em 2026-09-27) ─────────────

AJUSTES = "atualizar.json"
FAIXAS_DE_FABRICA = (25.0, 60.0)


def faixas() -> tuple[float, float]:
    try:
        d = json.loads((plataforma.pasta_dados() / AJUSTES).read_text(encoding="utf-8"))
        a, b = float(d["faixas"][0]), float(d["faixas"][1])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return FAIXAS_DE_FABRICA
    return (a, b) if 0 < a < b <= 100 else FAIXAS_DE_FABRICA


def gravar_faixas(a, b) -> tuple[float, float]:
    """Confere (0 < a < b ≤ 100) e grava; fora disso, volta o de fábrica."""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        a, b = FAIXAS_DE_FABRICA
    if not 0 < a < b <= 100:
        a, b = FAIXAS_DE_FABRICA
    pasta = plataforma.pasta_dados()
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / AJUSTES
    tmp = alvo.with_name(f"{AJUSTES}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"faixas": [a, b]}), encoding="utf-8")
    os.replace(tmp, alvo)
    return a, b
