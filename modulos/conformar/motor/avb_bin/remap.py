"""Repontar a timeline da `.avb` para os masters novos.

Irmão de `aaf/remap.py`. Roda **depois** do achatamento (ver `denest.py` e o ADR 0006):
com a timeline já apontando direto para os MasterMobs, repontar é uma troca de `mob_id`,
sem atravessar subclipe.

⚠️⚠️ **Case por IDENTIDADE, nunca por nome.** O master AMA criado a partir do original tem
**exatamente o mesmo nome** do master offline que ele substitui — e, num acervo do Avid,
até a caixa pode diferir (`a001_…` offline contra `A001_…` no AMA, que herda o nome do
arquivo). Um mapa `{nome → mob_id}` construído sobre a bin inteira devolve um dos dois
conforme a ordem de iteração; quando devolve o velho, a troca vira **no-op silencioso**.
Medido em 2026-08-16: 44 masters presentes, **0 SourceClips repontados**, sem erro nenhum.

Por isso a assinatura recebe um mapa **de MobID para MobID**, montado por quem sabe qual é
qual — e nunca deduzido aqui.
"""

from __future__ import annotations

import logging
from collections import Counter

from aaf.masters import chave_mob
from .percurso import e_master, por_mob_id, source_clips, timeline, track_de

log = logging.getLogger("delapraca.avb_bin.remap")


def repontar(f, mapa: dict[str, object], alvo=None) -> dict:
    """Troca o `mob_id` dos `SourceClip` da timeline conforme `mapa`.

    Args:
        mapa: `{chave_mob do master VELHO → MobID novo}`. A chave é a forma normalizada
            de `aaf.masters.chave_mob` (32 bytes em hex), a mesma do resto do motor.

    Returns:
        `{"repontados": n, "sem_destino": n, "masters_trocados": n}`
    """
    alvo = alvo if alvo is not None else timeline(f)
    if alvo is None:
        return {"repontados": 0, "sem_destino": 0, "masters_trocados": 0}

    por_id = por_mob_id(f)
    cont: Counter[str] = Counter()
    trocados: set[str] = set()

    for sc in source_clips(alvo):
        referenciado = por_id.get(str(sc.mob_id))
        if referenciado is None or not e_master(referenciado):
            continue
        chave = chave_mob(referenciado.mob_id)
        novo = mapa.get(chave)
        if novo is None:
            cont["sem_destino"] += 1
            continue
        sc.mob_id = novo
        trocados.add(chave)
        cont["repontados"] += 1

    resultado = {"repontados": cont["repontados"],
                 "sem_destino": cont["sem_destino"],
                 "masters_trocados": len(trocados)}
    log.info("repontado: %s", resultado)
    return resultado


def clampar(f, alvo=None) -> dict:
    """Garante que todo `SourceClip` cabe no master que ele aponta.

    ⚠️⚠️ **`PMM_INSUFFICIENT_MEDIA` não é caso de borda.** O master original quase nunca
    tem exatamente o mesmo comprimento do transcode offline que ele substitui — costuma
    diferir de 1 frame —, e **um único** clipe que passe do fim faz o Media Composer
    recusar a timeline inteira com essa exceção. Medido em 2026-08-16, depois de um
    relink em que 97 de 98 mídias vieram online e a timeline mesmo assim não abriu.

    ⭐ **Corrige puxando o START para trás, não cortando a duração.** Encurtar o clipe
    mudaria o tempo da edição e desalinharia a `Sequence` (os componentes somam o
    comprimento da track); recuar o início mantém a duração e só troca **quais** frames
    são usados. Um recuo de 1 frame é imperceptível; uma timeline que não abre, não.

    Returns:
        `{"ajustados": n, "irreparaveis": n, "maior_excedente": n}` — `irreparaveis` são
        os clipes mais LONGOS que o master inteiro, que nenhum recuo resolve.
    """
    alvo = alvo if alvo is not None else timeline(f)
    if alvo is None:
        return {"ajustados": 0, "irreparaveis": 0, "maior_excedente": 0}

    por_id = por_mob_id(f)
    cont: Counter[str] = Counter()
    maior = 0

    for sc in source_clips(alvo):
        mob = por_id.get(str(sc.mob_id))
        if mob is None or not e_master(mob):
            continue
        tr = track_de(mob, getattr(sc, "track_id", None), getattr(sc, "media_kind", None))
        comp = getattr(tr, "component", None) if tr is not None else None
        limite = getattr(comp, "length", None)
        if not limite:
            continue

        inicio = getattr(sc, "start_time", 0) or 0
        duracao = getattr(sc, "length", 0) or 0
        excedente = (inicio + duracao) - int(limite)
        if excedente <= 0:
            continue
        maior = max(maior, excedente)

        novo_inicio = inicio - excedente
        if novo_inicio >= 0:
            sc.start_time = novo_inicio
            cont["ajustados"] += 1
        else:
            # Mais longo que o master inteiro: recuar não resolve. Não se encurta em
            # silêncio — quem chama precisa saber para poder contar ao editor.
            cont["irreparaveis"] += 1
            log.warning("clipe de %d frames não cabe no master %r (%s frames)",
                        duracao, getattr(mob, "name", ""), limite)

    resultado = {"ajustados": cont["ajustados"],
                 "irreparaveis": cont["irreparaveis"],
                 "maior_excedente": maior}
    log.info("clamp: %s", resultado)
    return resultado
