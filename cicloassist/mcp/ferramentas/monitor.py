"""`o_que_esta_na_tela` — o que o editor está OLHANDO agora, e em que frame.

⭐⭐ É a pergunta que ele não deveria precisar responder digitando. O Media Composer sabe
o que está carregado no Source, no Record e no Center, **e onde o playhead está em cada
um** — então "o plano que estou vendo" vira um dado, não uma descrição.

MEDIDO (MC 2025.6.58781, 2026-09-11) e registrado no banco
(`plugins/avid-panel-sdk/dados/mcapi-grpc.json`):

```
GetViewerMobs   sem argumento nenhum  →  os três viewers de uma vez
MobInViewer     mob_id · view_type · current_frame · current_timecode · active
```

⚠️⚠️ **`view_type` AUSENTE significa `Source`.** É o valor 0 do enum, e o protobuf omite
o default — ler "sem view_type" como "desconhecido" perde justamente o monitor de origem,
que é o mais usado para comparar material.
"""

from __future__ import annotations

import logging

from ...avid.mcapi import McApiErro, MediaComposer
from ... import nle as _nle
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.monitor")

#: `view_type` → o nome que o editor usa. A ausência do campo é o Source (ver docstring).
MONITORES = {0: "source", 1: "record", 2: "popup", 3: "center"}


@ferramenta(
    nome="o_que_esta_na_tela",
    descricao=(
        "Diz o que está carregado nos monitores do Avid ou do Premiere agora — no Source, no "
        "Record/Program — e "
        "em que frame o editor parou em cada um. Use quando ele falar de 'este plano', "
        "'o que estou vendo', 'esta sequência', sem dizer o nome; e antes de procurar "
        "material parecido com o que está na tela."
    ),
    esquema={"type": "object", "properties": {}},
    escreve=False,
    nles=AMBOS,
)
def o_que_esta_na_tela() -> dict[str, object]:
    if _nle.qual() == _nle.PREMIERE:
        return _na_tela_do_premiere()
    monitores = []
    try:
        with MediaComposer() as mc:
            resposta = mc._chamar("GetViewerMobs")
            for m in resposta.body.mobs:
                # ⭐ O NOME, e não só o id. Custa uma chamada por monitor (são até três)
                #   e é a diferença entre "o mob 060a2b34…" e "C07_P02-T002" na resposta
                #   que o editor lê.
                try:
                    colunas = mc.colunas_do_mob(m.mob_id)
                except McApiErro:
                    colunas = {}
                monitores.append({
                    # ⚠️ `getattr` com 0: campo ausente é Source, não "faltando".
                    "monitor": MONITORES.get(int(getattr(m, "view_type", 0) or 0), "?"),
                    "nome": colunas.get("Name", ""),
                    "trilhas": colunas.get("Tracks", ""),
                    "mob_id": m.mob_id,
                    "frame_atual": int(getattr(m, "current_frame", 0) or 0),
                    "timecode": getattr(m, "current_timecode", "") or "",
                    "ativo": bool(getattr(m, "active", False)),
                })
    except McApiErro as e:
        return {"erro": f"o Media Composer não respondeu: {e}"}

    if not monitores:
        return {"monitores": [], "aviso": "não há nada carregado nos monitores agora"}

    log.info("monitores: %s", ", ".join(
        f"{m['monitor']}@{m['frame_atual']}" for m in monitores))
    return {
        "monitores": monitores,
        # ⚠️ O MobID sozinho não diz o NOME do clipe. Quem quiser o nome usa
        #    `resolver_take` ou `listar_itens_da_bin` — dizer isso aqui evita o modelo
        #    inventar um nome a partir do id.
        "como_usar": (
            "O mob_id identifica o clipe ou a sequência. Para o nome e os arquivos de "
            "mídia, passe este mob_id para resolver_take ou ver_frames."
        ),
        "confianca": "confirmado",
        "fonte": "visual",
    }


def _na_tela_pela_ponte() -> dict[str, object]:
    """⭐ F7: sem o MCP nativo (2025/2026), `cicloTela` do host.jsx — a sequência ativa (Program) e o
    Source, com a agulha. ⚠️ Não diz qual monitor o editor tocou por último (o ExtendScript não sabe)."""
    from fractions import Fraction

    from ...midia import timecode as _tc
    from ...nle.premiere import edicao as E
    from ...nle.premiere import edicao_cep as C
    from ...nle.premiere import ponte
    if not ponte.painel_vivo():
        return {"erro": ("o Premiere não está ligado ao Ciclo Assist: nem o servidor MCP (27.1+) nem a ponte "
                         "do painel respondem. Diga ao editor para abrir o Premiere com o Ciclo Assist.")}
    try:
        t = C.tela()
    except E.EdicaoRecusada as e:
        return {"erro": str(e)}
    prog = t.get("program") or {}
    fps = C._fps(prog["quadro"]) if prog.get("quadro") else None
    monitores = []

    def _seg(ticks) -> float | None:
        try:
            v = Fraction(int(ticks), C.TICKS)
        except (TypeError, ValueError):
            return None
        return None if v < 0 else float(v)   # o Premiere devolve −400000 s para "sem marca"

    for nome, m in (("source", t.get("source")), ("program", prog or None)):
        if not m:
            continue
        seg = _seg(m.get("agulha"))
        d: dict[str, object] = {"monitor": nome, "nome": m.get("nome", ""), "id": m.get("id", "")}
        if seg is not None:
            d["segundos"] = round(seg, 3)
            if fps:
                quadro = int(Fraction(seg).limit_denominator(10**9) * fps)
                d["frame_atual"] = quadro
                d["timecode"] = _tc.de_quadros(quadro, fps)
        for marca, rot in (("entrada", "entrada"), ("saida", "saida")):
            v = _seg(m.get(marca))
            if v is not None:
                d[rot] = round(v, 3)
        d["tipo"] = "sequência" if nome == "program" else "clipe"
        monitores.append(d)
    if not monitores:
        return {"monitores": [], "aviso": "não há nada carregado nos monitores do Premiere agora"}
    r: dict[str, object] = {"monitores": monitores,
                            "como_usar": ("O id serve a resolver_item_do_premiere (clipe) e a ler_timeline "
                                          "(sequência). Os segundos são desde o início do item."),
                            "aviso": "nesta versão do Premiere não sei qual monitor você tocou por último"}
    if prog.get("selecionados"):
        r["selecionados_na_timeline"] = prog["selecionados"]
    return r


def _na_tela_do_premiere() -> dict[str, object]:
    """⭐ F4 do plano 2026-11-06-mcp-do-premiere: `getEditingContext` (35 ms) — o Source, o
    Program (a sequência ativa), a agulha de cada um e o monitor que o editor tocou por último."""
    from fractions import Fraction

    from ...midia import timecode as _tc
    from ...nle.premiere import mcp_nativo as M
    if M.via("tela") != "mcp":
        return _na_tela_pela_ponte()
    try:
        ctx = M.chamar("getEditingContext") or {}
        estado = M.estado()
    except (M.McpIndisponivel, M.McpFalhou) as e:
        return {"erro": f"o Premiere não respondeu: {e}"}
    taxa = _tc.taxa_do_projeto(estado)
    ativo = ctx.get("activeMonitor") or ""
    monitores = []
    for chave, nome in (("sourceMonitor", "source"), ("programMonitor", "program")):
        m = ctx.get(chave)
        if not m:
            continue
        seg = float((m.get("playheadSeconds") or {}).get("seconds") or 0.0)
        d = {"monitor": nome, "nome": m.get("name", ""), "id": m.get("itemId") or m.get("sequenceId", ""),
             "segundos": round(seg, 3), "ativo": ativo == nome}
        if taxa:
            quadro = int(Fraction(seg).limit_denominator(10**9) * taxa)
            d["frame_atual"] = quadro
            d["timecode"] = _tc.de_quadros(quadro, taxa)
        for marca in ("inPoint", "outPoint"):
            if m.get(marca):
                d["entrada" if marca == "inPoint" else "saida"] = round(float(m[marca]["seconds"]), 3)
        if m.get("kind"):
            d["tipo"] = "sequência" if m["kind"] == "sequence" else "clipe"
        monitores.append(d)
    selecao = (ctx.get("timeline") or {}).get("selection") or []
    if not monitores:
        return {"monitores": [], "aviso": "não há nada carregado nos monitores do Premiere agora"}
    r: dict[str, object] = {"monitores": monitores,
                            "como_usar": ("O id serve a resolver_item_do_premiere (clipe) e a ler_timeline "
                                          "(sequência). Os segundos são desde o início do item.")}
    if selecao:
        r["selecionados_na_timeline"] = len(selecao)
    return r
