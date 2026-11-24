"""Achatar a timeline dentro da `.avb`: o `SourceClip` passa a apontar direto ao master.

Porte de `aaf/denest.py` para o AVB. A regra de ordem é a mesma do
[ADR 0006](../../docs/adr/0006-achatar-subclipes-antes-do-importfile.md):

    ⚠️ ACHATAR ANTES DE REPONTAR. Depois do achatamento a timeline aponta direto para os
    MasterMobs, e o repontamento vira uma troca direta — sem atravessar subclipe, que é
    onde mora o erro silencioso do ADR 0003.

## O que o achatamento faz

    timeline: SourceClip → subclipe (track_id=T, start=S)
    subclipe: track T    → SourceClip → master (track_id=t, start=s)
    ────────────────────────────────────────────────────────────
    resultado: SourceClip → master, track_id=t, start = S + s

## ⭐ Aqui achatar é REQUISITO do relink, não só profilaxia de diálogo

O ADR 0006 justifica o achatamento pelo modal *"Sub clip conflict found"* no reimport.
Medido em 2026-08-16, há um segundo motivo, independente e mais duro: **repontar o master
DENTRO do subclipe não traz a timeline online.** Foram 60 SourceClips apontando para
masters AMA comprovadamente online (o editor via imagem no Source monitor) e a timeline
seguiu 100% vermelha. Só depois de desfazer os subclipes o vídeo veio.

⭐ **Prova do porte por contagem cruzada:** nesta timeline o achatamento em AVB deu
**738 repontamentos / 44 subclipes** — exatamente o que o ADR 0006 registra pela rota AAF
no mesmo material. Dois caminhos independentes, o mesmo número.
"""

from __future__ import annotations

import logging
from collections import Counter

from .percurso import e_subclipe, por_mob_id, source_clips, timeline, track_de

log = logging.getLogger("delapraca.avb_bin.denest")


def achatar(f, alvo=None) -> dict:
    """Desfaz os subclipes da timeline, in-place, na bin já aberta.

    Returns:
        `{"achatados": n, "sem_track": n, "sem_source_clip": n, "subclipes_restantes": n}`

    ⚠️ Não remove as `CompositionMob` de subclipe da bin — só deixa de referenciá-las.
    Na rota AAF removê-las era necessário porque o `ImportFile` inspeciona o arquivo e
    abre diálogo de conflito; aqui não há import, então elas ficam como itens órfãos da
    bin, sem efeito sobre a timeline.
    """
    alvo = alvo if alvo is not None else timeline(f)
    if alvo is None:
        return {"achatados": 0, "sem_track": 0, "sem_source_clip": 0,
                "subclipes_restantes": 0}

    por_id = por_mob_id(f)
    cont: Counter[str] = Counter()

    for sc in source_clips(alvo):
        sub = por_id.get(str(sc.mob_id))
        if not e_subclipe(sub):
            continue

        tr = track_de(sub, getattr(sc, "track_id", None), getattr(sc, "media_kind", None))
        if tr is None:
            cont["sem_track"] += 1
            continue
        internos = source_clips(getattr(tr, "component", None))
        if not internos:
            cont["sem_source_clip"] += 1
            continue

        interno = internos[0]
        sc.mob_id = interno.mob_id
        track_interna = getattr(interno, "track_id", None)
        if track_interna is not None:
            sc.track_id = track_interna
        # O offset do clipe dentro do subclipe soma ao offset do subclipe na fonte.
        sc.start_time = ((getattr(sc, "start_time", 0) or 0)
                         + (getattr(interno, "start_time", 0) or 0))
        cont["achatados"] += 1

    restantes = sum(1 for s in source_clips(alvo)
                    if e_subclipe(por_id.get(str(s.mob_id))))
    resultado = {
        "achatados": cont["achatados"],
        "sem_track": cont["sem_track"],
        "sem_source_clip": cont["sem_source_clip"],
        "subclipes_restantes": restantes,
    }
    log.info("achatado: %s", resultado)
    return resultado
