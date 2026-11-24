"""O que aparece na bin entregue — e o que fica oculto.

⭐ Uma bin de relink tem dezenas ou centenas de mobs: a timeline, os masters novos, os
masters offline antigos, os subclipes que o achatamento deixou órfãos e as fontes de
essência. Despejar tudo na cara do editor é ruído.

⭐⭐ **A regra é a que o RELINKER já tinha aprendido, e ela é informativa, não estética:**

    online   → OCULTO   (deu certo; não precisa de atenção)
    offline  → VISÍVEL  (é o que ainda falta linkar)

Assim a bin entregue é, ela mesma, o relatório do que ficou de fora — o editor abre e vê
exatamente o que não resolveu, sem procurar.

## Como se oculta

O `BinItem` tem `user_placed`: `True` = item colocado pelo usuário (aparece na bin);
`False` = item apenas REFERENCIADO (existe na bin, resolve a timeline, e só aparece com
*Set Bin Display → mostrar itens referenciados* ligado). É o mesmo mecanismo que faz uma
timeline arrastada para uma bin nova trazer consigo, oculto, tudo que ela referencia.
"""

from __future__ import annotations

import logging

from .masters import classificar
from .percurso import e_composicao, e_master

log = logging.getLogger("delapraca.avb_bin.visibilidade")


def ajustar(f, timeline_mob=None, online: set[str] | None = None) -> dict:
    """Oculta o que está online; deixa visível o que está offline e a timeline.

    Args:
        timeline_mob: a composição entregue — sempre visível.
        online: `str(mob_id)` dos masters que ACABAMOS de deixar online. Eles são
            ocultados sem consultar a bin: o `_AMA_FILE_DATE_TIME` e o caminho já foram
            escritos por nós, e reclassificar aqui só repetiria trabalho.

    Returns:
        `{"visiveis": n, "ocultos": n}`
    """
    online = online or set()
    itens = f.content.property_data.get("items") or []
    id_timeline = str(getattr(timeline_mob, "mob_id", "")) if timeline_mob else ""
    visiveis = ocultos = 0

    for item in itens:
        mob = getattr(item, "mob", None)
        if mob is None:
            continue
        mob_id = str(getattr(mob, "mob_id", ""))

        if id_timeline and mob_id == id_timeline:
            mostrar = True                      # a timeline é o produto
        elif not e_master(mob):
            # Subclipes órfãos do achatamento, fontes de essência, precomputes: ruído.
            # ⚠️ Ocultar NÃO remove — a timeline segue resolvendo por eles.
            mostrar = False
        elif mob_id in online:
            mostrar = False                     # acabou de ficar online
        else:
            _ama, offline = classificar(mob)
            # ⚠️ `None` = não dá para saber (mídia gerenciada não diz pela bin). Na
            # dúvida, MOSTRA: esconder um clipe que talvez esteja offline apagaria da
            # vista justamente o que o editor precisa ver.
            mostrar = offline is not False

        item.property_data["user_placed"] = mostrar
        visiveis += mostrar
        ocultos += not mostrar

    # Composições sem BinItem não existem para a bin; nada a fazer por elas aqui.
    resultado = {"visiveis": visiveis, "ocultos": ocultos}
    log.info("visibilidade da bin: %s", resultado)
    return resultado


def garantir_monitor(f, timeline_mob) -> int | None:
    """Liga o MONITOR de vídeo da timeline entregue, se nenhuma trilha o tiver. Devolve o índice ligado (ou None).

    ⭐ Sem monitor o Media Composer não mostra imagem NENHUMA — o Composer fica preto e parece mídia offline (autor,
    2026-10-18: a `INJ 1_SEQ` do relink saiu assim com os 71 segmentos resolvidos). O estado é `session_attr`
    `_MONSTATE=1` em UMA trilha de imagem; o monitor é cumulativo para baixo, então vai na de MAIOR índice (banco,
    `protocolos/avb/dados/track-session-attrs.json`). Uma timeline do editor que já tem monitor fica como está — é
    escolha dele. O `_ENBLSTATE` que já existe não se toca (é do editor); faltando, vai 1 — o que o MC 25.12 grava numa
    sequência nova (medido 2026-10-24, Mac).
    """
    imagens = [t for t in (timeline_mob.property_data.get("tracks") or [])
               if getattr(t, "media_kind", "") == "picture"]
    if not imagens:
        return None
    def estado(t):
        sa = t.property_data.get("session_attr")
        try:
            return int(sa.get("_MONSTATE", 0)) if sa is not None else 0
        except (TypeError, ValueError, AttributeError):
            return 0
    if any(estado(t) == 1 for t in imagens):
        return None
    topo = max(imagens, key=lambda t: t.property_data.get("index") or 0)
    sa = topo.property_data.get("session_attr")
    if sa is None:
        sa = f.create.Attributes()
        topo.property_data["session_attr"] = sa
    sa["_MONSTATE"] = 1
    if "_ENBLSTATE" not in sa:
        sa["_ENBLSTATE"] = 1
    return topo.property_data.get("index")
