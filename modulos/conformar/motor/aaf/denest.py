"""Achatar a timeline: entregar os clipes ORIGINAIS, sem subclipe e sem group clip.

Era um dos diferenciais do RELINKER, e vale isolado do relink — por isso vive aqui e
não mais escondido dentro de `relink_aaf`.

## O que cada opção faz

**Subclipe** (`Usage_SubClip`) — o `SourceClip` da timeline passa a apontar direto para o
`MasterMob` original, in-place: troca-se o `mob_id`, o `SourceMobSlotID` do slot interno,
e soma-se ao `StartTime` o offset do subclipe. Equivale ao *decompose subclip* do Avid.

**Group clip / multicam** (`Selector` sobre uma `CompositionMob` com AppCode 4 ou 5) — o
`Selector` é substituído pelo `SourceClip` da **câmera selecionada**, resolvida até o
original. Equivale ao *commit multicam*.

## Por que isso também resolve o diálogo de conflito

Reimportar um AAF cujos subclipes já existem no projeto faz o Media Composer abrir um
**diálogo modal** — *"Sub clip conflict found… Do you want to replace the original?"* — e
diálogo modal **trava a API inteira**. Como o fluxo do plugin é reimportar (relinkar,
revisar, aplicar de novo), esse conflito seria o caso comum, não a exceção.

Sem subclipes na timeline, não há o que conflitar. Achatar deixou de ser só um
diferencial de entrega e virou também a saída para um bloqueador de produção.

## Ordem

⚠️ **Achatar ANTES de remapear.** Depois do achatamento os `SourceClip` apontam direto
para os `MasterMob`, e o remap deixa de precisar atravessar subclipe — fica uma troca
direta. É a mesma ordem que o `relink_aaf` já usava.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from origem import marcar_aaf

from .percurso import componentes

log = logging.getLogger("delapraca.aaf.denest")

# AppCode do Avid que marca um Group Clip (multicam). Ver `dados/appcodes` no banco.
_APPCODE_GRUPO = (4, 5)


def _primeiro_source_clip(seg):
    """Primeiro `SourceClip` alcançável dentro de um segmento.

    Desce `Selector` (Selected **e** Alternates), `OperationGroup`/InputSegments e
    `Sequence`/`NestedScope`. Cobre dois casos que quebram a busca ingênua: o áudio do
    subclipe envolto num OperationGroup "Audio Gain", e o selector de áudio multicam,
    em que `Selected` é `Filler` e a fonte real está num `Alternate`.
    """
    k = type(seg).__name__
    if k == "SourceClip":
        return seg
    if k == "Selector":
        try:
            sel = seg["Selected"].value
            if sel is not None:
                r = _primeiro_source_clip(sel)
                if r is not None:
                    return r
        except Exception:
            pass
        try:
            for alt in list(seg.get("Alternates") or []):
                r = _primeiro_source_clip(alt)
                if r is not None:
                    return r
        except Exception:
            pass
    if k == "OperationGroup":
        try:
            for ip in list(seg.get("InputSegments") or []):
                r = _primeiro_source_clip(ip)
                if r is not None:
                    return r
        except Exception:
            pass
    if hasattr(seg, "components"):
        for c in seg.components:
            r = _primeiro_source_clip(c)
            if r is not None:
                return r
    return None


def _e_subclipe(mob) -> bool:
    return (mob is not None
            and type(mob).__name__ == "CompositionMob"
            and getattr(mob, "usage", None) == "Usage_SubClip")


def _e_group_clip(selector) -> bool:
    """O `Selector` aponta para um Group Clip? (a fonte resolve a AppCode 4/5)"""
    try:
        selecionado = selector["Selected"].value
        if selecionado is None:
            return False
        sc = _primeiro_source_clip(selecionado)
        mob = getattr(sc, "mob", None) if sc is not None else None
        if mob is None or type(mob).__name__ != "CompositionMob":
            return False
        try:
            codigo = mob["AppCode"].value
        except Exception:
            codigo = getattr(mob, "application_code", None)
        return codigo in _APPCODE_GRUPO
    except Exception:
        return False


def _repontar_subclipe(sc) -> bool:
    """Faz um `SourceClip` apontar direto para o MasterMob por trás do subclipe."""
    mob = getattr(sc, "mob", None)
    if not _e_subclipe(mob):
        return False

    slot_id = getattr(sc, "slot_id", None)
    alvo = next((s for s in mob.slots if getattr(s, "slot_id", None) == slot_id), None)
    if alvo is None:
        # Sem slot_id utilizável, o tipo de mídia desempata — é o que faz a trilha de
        # áudio cair no som direto e não no áudio da câmera.
        alvo = next((s for s in mob.slots if s.media_kind == sc.media_kind), None)
    if alvo is None:
        return False

    interno = _primeiro_source_clip(alvo.segment)
    mob_interno = getattr(interno, "mob", None) if interno is not None else None
    if mob_interno is None:
        return False

    try:
        sc.mob_id = mob_interno.mob_id
        slot_interno = getattr(interno, "slot_id", None)
        if slot_interno is not None:
            sc["SourceMobSlotID"].value = slot_interno
        # O offset do clipe dentro do subclipe soma ao offset do subclipe na fonte.
        atual = sc["StartTime"].value if "StartTime" in sc else 0
        sc["StartTime"].value = (atual or 0) + (getattr(interno, "start", 0) or 0)
        return True
    except Exception as e:
        log.debug("falha ao achatar subclipe: %s", e)
        return False


def achatar_arquivo(entrada: str, saida: str, *, subclipes: bool = True,
                    group_clips: bool = True) -> dict:
    """Escreve em `saida` uma cópia de `entrada` com a timeline achatada.

    O AAF de entrada nunca é modificado.
    """
    import aaf2

    orig, dest = Path(entrada), Path(saida)
    if orig.resolve() == dest.resolve():
        raise ValueError("entrada e saída devem ser arquivos diferentes")
    if not (subclipes or group_clips):
        raise ValueError("nada a achatar: as duas opções vieram desligadas")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(orig, dest)
    with aaf2.open(str(dest), "rw") as f:
        contagem = achatar(f, subclipes=subclipes, group_clips=group_clips)
        marcar_aaf(f)   # quem tratou fica registrado (origem.py)
    contagem["saida"] = str(dest)
    return contagem


def _mobs_referenciados(f) -> set[str]:
    """Os MobIDs que alguma composição ainda referencia, em qualquer profundidade."""
    usados: set[str] = set()
    for mob in list(f.content.mobs):
        for slot in mob.slots:
            for comp in componentes(slot.segment):
                mid = getattr(comp, "mob_id", None)
                if mid is not None:
                    usados.add(str(mid))
    return usados

def remover_subclipes_orfaos(f) -> int:
    """Apaga do AAF as `CompositionMob` de subclipe que ninguém mais referencia.

    ⚠️ **Achatar as referências não basta.** Depois de repontar os `SourceClip`, as
    `CompositionMob [Usage_SubClip]` continuam no arquivo — medido: 44 delas, intactas,
    num AAF cuja timeline já apontava direto para os masters. E é o que está **no
    arquivo** que o Media Composer inspeciona ao importar: ele acha os subclipes, vê que
    já existem no projeto, e abre o diálogo modal de conflito que trava a API.

    Só se remove o que ficou órfão: um subclipe ainda referenciado por outra composição
    permanece, ou a timeline dela quebraria.
    """
    # ⚠️ `f.content.mobs` é uma VISTA de leitura (`StrongRefSetProperty`) e **não tem
    # `.remove()`**. Quem remove é a propriedade `Mobs`, por `pop(mob_id)` — a chave do
    # conjunto é o próprio MobID. Chamar `.remove()` levanta `AttributeError`, que, se
    # engolido, vira "removi 37" com zero removidos de fato.
    conjunto = f.content["Mobs"]
    removidos = 0

    # Em passes até estabilizar: um subclipe pode referenciar outro, e o de baixo só
    # fica órfão depois que o de cima sai. Numa passada só, 7 dos 44 ficavam para trás.
    for _ in range(10):
        usados = _mobs_referenciados(f)
        orfaos = [m for m in list(f.content.mobs)
                  if _e_subclipe(m) and str(m.mob_id) not in usados]
        if not orfaos:
            break
        antes = removidos
        for mob in orfaos:
            try:
                conjunto.pop(mob.mob_id)
                removidos += 1
            except Exception as e:
                log.warning("não consegui remover o subclipe %r: %s", mob.name, e)
        if removidos == antes:
            break  # ninguém saiu nesta passada; insistir não muda nada

    log.info("removidos %d subclipe(s) órfão(s) do arquivo", removidos)
    return removidos


def achatar(f, *, subclipes: bool = True, group_clips: bool = True) -> dict:
    """Achata a timeline de um AAF já aberto em modo `rw`.

    Returns:
        `{"subclipes": n, "group_clips": n, "orfaos_removidos": n}`.
    """
    contagem = {"subclipes": 0, "group_clips": 0, "orfaos_removidos": 0}

    def percorrer(seg):
        k = type(seg).__name__

        if k == "SourceClip":
            if subclipes and _repontar_subclipe(seg):
                contagem["subclipes"] += 1
            return

        if k == "Sequence":
            componentes = list(seg.components)
            novos = []
            mudou = False
            for c in componentes:
                if group_clips and type(c).__name__ == "Selector" and _e_group_clip(c):
                    sc = _primeiro_source_clip(c["Selected"].value)
                    if sc is not None:
                        # Substitui o Selector por um SourceClip da câmera escolhida,
                        # preservando a DURAÇÃO do Selector — quem manda no tempo é a
                        # timeline, não a fonte.
                        novo = f.create.SourceClip(media_kind=sc.media_kind)
                        novo.mob_id = sc.mob_id
                        novo["SourceMobSlotID"].value = getattr(sc, "slot_id", 1)
                        novo["StartTime"].value = getattr(sc, "start", 0) or 0
                        novo.length = c.length
                        if subclipes:
                            _repontar_subclipe(novo)  # a câmera pode ser um subclipe
                        novos.append(novo)
                        contagem["group_clips"] += 1
                        mudou = True
                        continue
                percorrer(c)
                novos.append(c)
            if mudou:
                seg["Components"].value = novos
            return

        if k == "NestedScope":
            for s in seg.slots:
                percorrer(s.segment if hasattr(s, "segment") else s)
            return

        if k == "OperationGroup":
            try:
                for ip in list(seg.get("InputSegments") or []):
                    percorrer(ip)
            except Exception:
                pass
            return

        if k == "Selector":
            # Selector que NÃO é group clip (multi-resolução, por exemplo): desce no
            # selecionado em vez de substituir.
            try:
                sel = seg["Selected"].value
                if sel is not None:
                    percorrer(sel)
            except Exception:
                pass
            # ⚠️ E nos ALTERNATES. No selector de áudio multicam o `Selected` é
            # `Filler` e a fonte real mora num alternate — `_primeiro_source_clip` já
            # trata esse caso, e o percurso precisa tratá-lo também. Sem isto, sete
            # subclipes de som ficavam para trás **sem nenhuma falha de repontamento
            # registrada**: os SourceClip simplesmente nunca eram visitados.
            try:
                for alt in list(seg.get("Alternates") or []):
                    percorrer(alt)
            except Exception:
                pass
            return

        if k == "Transition":
            # A transição carrega um OperationGroup com os lados do dissolve.
            try:
                for ip in list(seg.get("InputSegments") or []):
                    percorrer(ip)
            except Exception:
                pass
            try:
                op = seg["OperationGroup"].value
                if op is not None:
                    percorrer(op)
            except Exception:
                pass
            return

    try:
        for topo in list(f.content.toplevel()):
            for slot in topo.slots:
                percorrer(slot.segment)
    except Exception as e:
        log.warning("erro ao achatar a timeline: %s", e)

    # Repontar não tira os mobs do arquivo — e é o arquivo que o MC inspeciona.
    if subclipes:
        contagem["orfaos_removidos"] = remover_subclipes_orfaos(f)

    log.info("achatado: %d subclipe(s), %d group clip(s), %d órfão(s) removido(s)",
             contagem["subclipes"], contagem["group_clips"],
             contagem["orfaos_removidos"])
    return contagem
