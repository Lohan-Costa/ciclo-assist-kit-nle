"""Os masters de um AAF — a unidade de trabalho do relink.

## Por que masters, e não segmentos

A timeline aponta para N masters únicos. Medido no material real: **1172 segmentos para
83 masters**. Casar um master resolve todos os segmentos dele de uma vez, e o master
aparece em vários pontos da timeline — o que dá **várias amostras no vídeo de referência
para confirmar uma única decisão**. Mais evidência por decisão, menos decisões.

## A cadeia, que não é direta

⚠️ O `SourceClip` da timeline **raramente aponta para o MasterMob**. Numa montagem real
ele aponta para um **subclipe sincronizado** — uma `CompositionMob` com
`Usage_SubClip` — e é ela que aponta para os masters:

    Sequence → SourceClip → CompositionMob [Usage_SubClip] "04-02-01"
                              ├ slot 1 → MasterMob 'a001_03170334_C004'   ← a câmera
                              ├ slot 2 → MasterMob 'PROJETO - …T001'      ┐
                              ├ slot 3 → MasterMob 'PROJETO - …T001'      ├ som direto
                              └ …                                        ┘

Medido em material real. Um remap que troque o MobID do mob que o SourceClip
referencia troca o **subclipe**, não o master — e o Media Composer, ao importar, cria
tudo offline sem reclamar de nada. É um erro silencioso, e foi cometido antes de este
módulo existir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .percurso import source_clips as _source_clips

log = logging.getLogger("delapraca.aaf.masters")

_HEX = set("0123456789abcdefABCDEF")

# ⚠️ Imagem e som se distinguem por `slot.media_kind`, NÃO por `edit_rate`.
#
# A heurística "edit rate ≥ 1000 é áudio" vale para `SourceMob` — é assim que o RELINKER
# a usa — e **não vale para `MasterMob`**: medido em material real, todos os
# slots de todos os masters, imagem e som, têm `edit_rate = 24000/1001`. Classificar por
# ali marca o acervo inteiro como vídeo, calado.
_PICTURE = ("picture",)
_SOUND = ("sound",)


def chave_mob(mob_id) -> str:
    """Qualquer representação de MobID → os 32 bytes em hex, sem pontuação.

    ⚠️ O prefixo sai ANTES do filtro de hexadecimais: `urn:smpte:umid:` contribui com
    o **e** de `smpt`**e** e o **d** de `umi`**d**, e o `0x` do ffprobe contribui com o
    **0**. Nenhum dos dois estoura — só fazem duas representações do MESMO MobID
    compararem como diferentes.
    """
    s = str(mob_id).strip()
    baixo = s.lower()
    if baixo.startswith("urn:smpte:umid:"):
        s = s[len("urn:smpte:umid:"):]
    elif baixo.startswith("0x"):
        s = s[2:]
    return "".join(c for c in s if c in _HEX).lower()


@dataclass
class Master:
    """Um master referenciado pela timeline."""

    nome: str
    mob_id: str                 # chave hex normalizada
    mob_id_urn: str             # como está no AAF
    e_audio: bool = False
    segmentos: int = 0          # quantas vezes aparece na timeline
    duracao_frames: int | None = None
    edit_rate: float | None = None
    via_subclipe: bool = False  # foi alcançado atravessando um Usage_SubClip
    slots: list[int] = field(default_factory=list)
    # ⚠️ TRÊS estados, e `None` = **não dá para saber** (nunca `False`). Preenchidos só
    # pela rota `.avb`, que lê a bin; a rota AAF os deixa `None` e por isso os filtros de
    # relink parcial não descartam nada nela. Ver `avb_bin.masters.classificar`.
    e_ama: bool | None = None
    esta_offline: bool | None = None
    # ⭐ Para o RELINK MANUAL (autor, 2026-10-13: "a palavra do editor se sobrepõe a qualquer regra automática,
    # impedindo apenas se for impossível o relink"). `origem` = o caminho que o AAF/a bin grava (a coluna "De onde
    # veio"); `uso_frames` = o maior fim (start + length, frames na base de `edit_rate`) que a timeline pede deste
    # master — `None` = não deu para saber; `usa_imagem` = alguma trilha de imagem o usa; `canais_som` = o maior
    # canal de som do master que a timeline usa (0 = não se sabe ou nenhum).
    origem: str = ""
    uso_frames: int | None = None
    usa_imagem: bool = False
    canais_som: int = 0
    # O TC de origem do 1º quadro do master (`tc_quadros` na base NOMINAL `tc_fps`) — `None` = não se sabe. Para o
    # casamento não aceitar calado o convertido que perdeu o TC (B110, autor 2026-10-31): `matcher_masters._portao_tc`.
    tc_quadros: int | None = None
    tc_fps: int | None = None

    def to_dict(self) -> dict:
        return {
            "nome": self.nome, "mob_id": self.mob_id, "e_audio": self.e_audio,
            "segmentos": self.segmentos, "duracao_frames": self.duracao_frames,
            "edit_rate": self.edit_rate, "via_subclipe": self.via_subclipe,
            "e_ama": self.e_ama, "esta_offline": self.esta_offline,
            "origem": self.origem, "uso_frames": self.uso_frames,
            "usa_imagem": self.usa_imagem, "canais_som": self.canais_som,
        }


def _e_subclipe(mob) -> bool:
    return type(mob).__name__ == "CompositionMob" and \
        "subclip" in str(getattr(mob, "usage", "") or "").lower()


def _tipo_de_midia(slot) -> str:
    return str(getattr(slot, "media_kind", "") or "").strip().lower()


def _segundos_do_slot(slot) -> float | None:
    """Duração de um slot em SEGUNDOS, com `length` e `edit_rate` do MESMO slot.

    ⚠️⚠️ **Os dois têm de sair do mesmo slot, e é isso que torna a conta correta seja
    qual for a unidade.** Num AAF a trilha de som pode contar em *samples* com
    `edit_rate = 48000`, e a de imagem em frames a 23,976; cruzar o comprimento de uma
    com a taxa da outra dá um número plausível e errado por três ordens de grandeza.
    `length / edit_rate` do mesmo slot dá segundos nos dois casos, sem precisar saber
    qual deles é.

    ⭐ **Medido** (`PRODA_RELINKER_ALTA.aaf`, 303 MasterMobs, 2026-08-16): neste AAF o som
    conta em **frames@timeline** como a imagem — a mesma convenção da rota `.avb`. Mas
    apareceram `edit_rate` de **23,976 e de 24,0** entre os sons, o que já basta para
    provar que a taxa **não pode ser presumida** a partir de um slot só ou da timeline.
    """
    segmento = getattr(slot, "segment", None)
    length = getattr(segmento, "length", None)
    taxa = getattr(slot, "edit_rate", None)
    if not length or not taxa:
        return None
    try:
        return float(length) / float(taxa)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _duracao_em_frames(master_mob, quero: str, edit_rate) -> int | None:
    """Duração do master em frames NA BASE de `edit_rate` — o par que o matcher usa.

    ⭐ **Por que isto existe:** sem `duracao_frames`, `_duracao_do_master` devolve `None`
    e o **portão de duração do `casar_masters` ficava neutro na rota AAF inteira** — o
    veto que separa dois clipes de mesmo nome simplesmente não opinava. A rota `.avb` já
    preenchia; esta tinha ficado para trás sem motivo: medido, **303 de 303** MasterMobs
    do AAF real têm a duração disponível.

    Prefere o slot da mesma espécie do segmento que trouxe este master, e cai para
    qualquer um com dado. Devolve na base de `edit_rate` para manter a invariante de que
    `duracao_frames / edit_rate` são **segundos** — que é tudo de que o matcher precisa,
    e o que mantém o campo honesto ao próprio nome.
    """
    slots = list(getattr(master_mob, "slots", []) or [])
    preferidos = [s for s in slots if _tipo_de_midia(s) == (quero or "").lower()]
    for slot in preferidos + slots:
        segundos = _segundos_do_slot(slot)
        if segundos is None:
            continue
        taxa = edit_rate or getattr(slot, "edit_rate", None)
        try:
            return int(round(segundos * float(taxa))) if taxa else None
        except (TypeError, ValueError):
            return None
    return None


def _resolver(mob, slot_id, por_id, quero: str, profundidade=0):
    """Do mob que um SourceClip referencia até o MasterMob de verdade.

    Devolve `[(MasterMob, veio_de_subclipe)]`.

    `slot_id` é o do `SourceClip` da timeline e diz **qual slot do subclipe** usar —
    honrá-lo é o que faz a trilha de áudio resolver para o SOM DIRETO em vez de para o
    áudio da câmera. Quando ele não basta, `quero` (`picture`/`sound`) desempata pelo
    tipo de mídia da trilha de origem.

    ⚠️ Sem esse filtro, um subclipe sincronizado devolve **todos** os seus masters —
    a câmera e os cinco canais de som — e a contagem de segmentos passa a dizer que o
    som direto é o clipe mais usado da montagem, cinco vezes mais que a imagem.
    """
    if mob is None or profundidade > 4:
        return []

    if type(mob).__name__ == "MasterMob":
        return [(mob, profundidade > 0)]

    if not _e_subclipe(mob):
        return []

    def descer(slots):
        achados = []
        for slot in slots:
            for sc in _source_clips(slot.segment):
                destino = por_id.get(chave_mob(getattr(sc, "mob_id", "")))
                achados.extend(_resolver(destino, getattr(sc, "slot_id", None),
                                         por_id, quero, profundidade + 1))
        return achados

    slots = list(mob.slots)
    # 1) o slot que o SourceClip pediu
    if slot_id is not None:
        exatos = [s for s in slots if getattr(s, "slot_id", None) == slot_id]
        if exatos:
            return descer(exatos)
    # 2) senão, os slots do tipo de mídia da trilha
    do_tipo = [s for s in slots if _tipo_de_midia(s).startswith(quero)]
    if do_tipo:
        return descer(do_tipo)
    # 3) e, em último caso, o que houver
    return descer(slots)


def _origem_do_master(master, por_id) -> str:
    """O caminho que o AAF grava para a mídia deste master (a URL do locator do SourceMob de arquivo), como caminho
    local — ou `""`. É a coluna "De onde veio" da lista de mídias: ajuda o editor a achar o arquivo, não decide nada."""
    from .parser import read_url_from_descriptor, url_to_local_path

    # Medido no AAF do PRODUCAO-A (MC 25.6, 2026-10-13): a URL mora DOIS níveis abaixo do master — master → SourceMob
    # (PCMDescriptor, sem locator) → SourceMob (ImportDescriptor, `file:////D/02_MIDIAS/…`). Desce a cadeia toda.
    vistos = set()

    def descer(mob, prof):
        if mob is None or prof > 5 or id(mob) in vistos:
            return ""
        vistos.add(id(mob))
        desc = getattr(mob, "descriptor", None) if prof else None
        url = read_url_from_descriptor(desc) if desc is not None else None
        if url:
            return url_to_local_path(url) if url.lower().startswith("file:") else url
        for slot in mob.slots:
            for sc in _source_clips(slot.segment):
                achado = descer(por_id.get(chave_mob(getattr(sc, "mob_id", ""))), prof + 1)
                if achado:
                    return achado
        return ""

    try:
        caminho = descer(master, 0)
    except Exception:  # noqa: BLE001 — acessório: sem origem, a coluna fica vazia
        return ""
    # `file:////D/…` (o Avid no Windows) vira `//D/…`; o editor reconhece `D:/…`.
    if len(caminho) > 3 and caminho[:2] == "//" and caminho[2].isalpha() and caminho[3] == "/":
        caminho = caminho[2] + ":" + caminho[3:]
    return caminho


def _tc_do_master(master, por_id) -> tuple[int | None, int | None]:
    """O TC de origem do 1º quadro do master no AAF: a cadeia master → SourceMob(s), somando o `start` de cada
    SourceClip, e o `Timecode` do mob MAIS FUNDO que tiver um (o mesmo critério da bin, `identidade_na_bin`: o TC e o
    nome podem morar em mobs diferentes). `(None, None)` quando não acha — acessório, nunca derruba a leitura."""
    from .parser import _find_timecode

    cadeia, vistos = [(master, 0)], set()
    try:
        mob, desloc = master, 0
        while mob is not None and len(vistos) < 8 and id(mob) not in vistos:
            vistos.add(id(mob))
            prox = None
            for slot in mob.slots:
                if str(getattr(slot.segment, "media_kind", "")).lower() not in ("picture", "sound"):
                    continue
                scs = list(_source_clips(slot.segment))
                if scs:
                    prox = por_id.get(chave_mob(getattr(scs[0], "mob_id", "")))
                    desloc += int(getattr(scs[0], "start", 0) or 0)
                    break
            if prox is None:
                break
            cadeia.append((prox, desloc))
            mob = prox
        for mob, desloc in reversed(cadeia):
            for slot in mob.slots:
                tc = _find_timecode(slot.segment)
                fps = int(getattr(tc, "fps", 0) or 0) if tc is not None else 0
                if fps > 0:
                    return int(getattr(tc, "start", 0) or 0) + desloc, fps
    except Exception:  # noqa: BLE001
        pass
    return None, None


def masters_em_uso(caminho_aaf: str, segmentos=None) -> list[Master]:
    """Os masters que a timeline do AAF de fato usa, com quantos segmentos cada um.

    Ordenado do que mais aparece para o que menos: é a ordem em que valem o esforço de
    casar, e a ordem em que o editor quer revisá-los.

    ⭐ **Quem percorre a timeline é `parse_aaf`, não este módulo.** A primeira versão
    daqui varria a estrutura por conta própria e achava **zero** SourceClips no slot de
    imagem: a trilha de vídeo de uma montagem do Avid é um `NestedScope` (flat file, V1
    base + V2 de efeitos), e o percurso ingênuo não desce nele. O parser do RELINKER já
    cobre NestedScope, Selector/multicam, OperationGroup, Transition, subclipes e grupos
    — reimplementar isso aqui seria refazer, pior, 1963 linhas de estrutura já decifrada.

    O que sobra para este módulo é o passo que o parser não dá: do mob que o `SourceClip`
    referencia **até o MasterMob**, atravessando o subclipe sincronizado.

    Args:
        segmentos: o resultado de `parse_aaf(...)["segments"]`, se já estiver em mãos.
            Evita parsear o mesmo AAF duas vezes.
    """
    import aaf2

    if segmentos is None:
        from .parser import parse_aaf
        segmentos = parse_aaf(caminho_aaf)["segments"]

    achados: dict[str, Master] = {}

    with aaf2.open(caminho_aaf, "r") as f:
        por_id = {chave_mob(m.mob_id): m for m in f.content.mobs}

        for seg in segmentos:
            if seg.get("is_gap") or seg.get("is_transition"):
                continue
            mob_id = seg.get("mob_id")
            if not mob_id:
                continue
            referenciado = por_id.get(chave_mob(mob_id))
            if referenciado is None:
                continue

            quero = "sound" if seg.get("is_audio") else "picture"
            for master, via_sub in _resolver(
                    referenciado, seg.get("source_slot_id"), por_id, quero):
                k = chave_mob(master.mob_id)
                m = achados.get(k)
                if m is None:
                    taxa = seg.get("source_fps")
                    m = Master(
                        nome=master.name or "",
                        mob_id=k,
                        mob_id_urn=str(master.mob_id),
                        e_audio=bool(seg.get("is_audio")),
                        edit_rate=taxa,
                        duracao_frames=_duracao_em_frames(master, quero, taxa),
                        via_subclipe=via_sub,
                        origem=_origem_do_master(master, por_id),
                    )
                    m.tc_quadros, m.tc_fps = _tc_do_master(master, por_id)
                    achados[k] = m
                m.segmentos += 1
                if quero == "picture":
                    m.usa_imagem = True
                # O trecho usado só quando o SourceClip aponta DIRETO para o master: atravessando um subclipe, o
                # offset dele não está no segmento, e um número pequeno demais aprovaria um arquivo curto. `None`
                # = não se sabe, e o relink manual não recusa por duração (só avisa).
                if not via_sub and seg.get("duration_frames") is not None:
                    fim = int(seg.get("source_start_frames") or 0) + int(seg.get("duration_frames") or 0)
                    m.uso_frames = max(m.uso_frames or 0, fim)
                trilha = seg.get("track")
                if trilha is not None and trilha not in m.slots:
                    m.slots.append(trilha)

    return sorted(achados.values(), key=lambda m: (-m.segmentos, m.nome))
