"""O percurso da timeline dentro de uma `.avb` — **um lugar só**.

Irmão de `aaf/percurso.py`, e existe pela mesma razão registrada no
[ADR 0006](../../docs/adr/0006-achatar-subclipes-antes-do-importfile.md): o percurso do
AAF chegou a ser escrito **três vezes**, e cada cópia esqueceu um ramo diferente da
estrutura recursiva — sempre sem erro, só um número menor do que devia.

Aqui as armadilhas são outras, porque a biblioteca é outra:

⚠️⚠️ **No pyavb NÃO existe classe `MasterMob`.** Todo mob é `Composition`; quem distingue
é o **atributo** `mob_type` (`MasterMob` | `SourceMob` | `CompositionMob`). No pyaaf2 são
classes distintas e `type(m).__name__ == "MasterMob"` funciona — portar esse teste devolve
**zero masters sem erro nenhum**: a varredura roda inteira, atravessa toda a timeline e
reporta `0/0`, como se o acervo estivesse vazio. Medido em 2026-08-16.

⚠️ **`tracks` é propriedade em `Composition` e MÉTODO noutras classes** do pyavb. Iterar
sem checar `callable` levanta `TypeError: 'method' object is not iterable` **no meio** do
percurso, depois de já ter contado parte da timeline.

⚠️⚠️ **`track_id` sozinho não identifica a track de um mob.** Um mob tem `index=1` de
imagem **e** `index=1` de som (medido: o subclipe `04-02-01` tem picture idx=1, sound idx=1
e sound idx=2). Casar só pelo índice põe um `SourceClip` de SOM na track de IMAGEM — e
isso não levanta erro: vira mídia errada, ou offline, calado.
"""

from __future__ import annotations

# Atributos que podem conter filhos numa árvore de componentes do pyavb.
# `alternates` e `input_segments` cobrem Selector e OperationGroup/Transition — os mesmos
# ramos que, esquecidos no lado AAF, deixaram sete subclipes de som para trás.
_RAMOS = ("components", "tracks", "input_segments", "alternates")

PROFUNDIDADE_MAX = 12


def tipo(o) -> str:
    return type(o).__name__


def e_master(mob) -> bool:
    """É um MasterMob? (Pelo `mob_type`, nunca pela classe — ver o topo do módulo.)"""
    return str(getattr(mob, "mob_type", "")) == "MasterMob"


def e_composicao(mob) -> bool:
    return str(getattr(mob, "mob_type", "")) == "CompositionMob"


def e_subclipe(mob) -> bool:
    """Uma `CompositionMob` com `usage` de subclipe.

    O `usage` do pyavb vem em minúsculas (`'subclip'`), diferente do AAF
    (`'Usage_SubClip'`) — por isso a comparação é frouxa e por conteúdo.
    """
    return (mob is not None and e_composicao(mob)
            and "subclip" in str(getattr(mob, "usage", "") or "").lower())


def filhos(componente) -> list:
    """Os filhos de um componente, por todos os ramos, sem estourar em método."""
    fora = []
    for atributo in _RAMOS:
        valor = getattr(componente, atributo, None)
        if valor is None or callable(valor):
            continue
        try:
            itens = list(valor)
        except TypeError:
            continue
        for item in itens:
            # Uma `Track` embrulha o componente; um componente é ele mesmo.
            fora.append(getattr(item, "component", item))
    return fora


def source_clips(componente, _profundidade: int = 0, _fora: list | None = None) -> list:
    """Todo `SourceClip` abaixo de um componente, em qualquer profundidade."""
    if _fora is None:
        _fora = []
    if componente is None or _profundidade > PROFUNDIDADE_MAX:
        return _fora
    if tipo(componente) == "SourceClip":
        _fora.append(componente)
        return _fora
    for filho in filhos(componente):
        source_clips(filho, _profundidade + 1, _fora)
    return _fora


def timeline(f):
    """A `CompositionMob` que é a timeline: a de mais tracks.

    ⚠️ Filtra por `mob_type == "CompositionMob"` **antes** de comparar — sem isso um
    MasterMob com muitas trilhas de som venceria a disputa.
    """
    composicoes = [m for m in f.content.mobs if e_composicao(m)]
    if not composicoes:
        return None
    return max(composicoes, key=lambda c: len(list(getattr(c, "tracks", []) or [])))


def por_mob_id(f) -> dict[str, object]:
    """`{str(mob_id) → mob}` de toda a bin. A bin é autossuficiente (ver `masters.py`)."""
    return {str(m.mob_id): m for m in f.content.mobs}


def track_de(mob, track_id, media_kind):
    """A track de `mob` que um `SourceClip` pede — por `index` **E** `media_kind`.

    ⚠️ Ver o aviso no topo: `index=1` existe para imagem e para som. Quando o índice não
    casa, o tipo de mídia desempata — é o que faz a trilha de áudio cair no som direto em
    vez do áudio da câmera.
    """
    alvo = str(media_kind or "").lower()
    tracks = list(getattr(mob, "tracks", []) or [])
    for tr in tracks:
        if (getattr(tr, "index", None) == track_id
                and str(getattr(tr, "media_kind", "")).lower() == alvo):
            return tr
    for tr in tracks:
        if str(getattr(tr, "media_kind", "")).lower() == alvo:
            return tr
    return None
