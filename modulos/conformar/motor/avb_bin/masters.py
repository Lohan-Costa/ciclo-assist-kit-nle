"""Os masters de uma timeline dentro de uma `.avb` — a unidade de trabalho do relink.

Irmão de `aaf/masters.py`, e devolve **os mesmos objetos `Master`**. Isso não é
coincidência de estilo: `media/matcher_masters.casar_masters` consome `nome`, `mob_id`,
`segmentos`, `duracao_frames`, `edit_rate` e `e_audio` — e **nada nele é de AAF**. A
metade de casamento do motor já era agnóstica de formato; o que muda entre a rota AAF e a
rota `.avb` é só o **leitor**.

## A cadeia, que é a mesma do AAF

Medido na bin de um curta real (2026-08-16): **877 SourceClips → 83 mobs referenciados →
80 MasterMobs**, e a timeline nunca aponta direto para um master de câmera:

    Sequence → SourceClip → Composition [usage=subclip] → SourceClip → MasterMob

⚠️ Repontar o **subclipe** em vez do master é o erro silencioso do
[ADR 0003](../../docs/adr/0003-matching-por-master-nao-por-segmento.md): o Media Composer
aceita e traz tudo offline sem reclamar de nada.

⭐ **Toda bin do Avid é um banco autossuficiente**: basta a timeline existir nela para que
tudo que ela referencia viva ali dentro, oculto (visível em *Set Bin Display → itens
referenciados*). Por isso este módulo resolve a cadeia inteira sem abrir outra bin — e por
isso "o mob está noutra bin" nunca é explicação para uma referência que não resolve.
"""

from __future__ import annotations

import logging

from aaf.masters import Master, chave_mob   # ⭐ o MESMO dataclass da rota AAF
from .percurso import (e_master, e_subclipe, por_mob_id, source_clips, timeline,
                       track_de)

log = logging.getLogger("delapraca.avb_bin.masters")


def _duracao(mob) -> int | None:
    """Duração do master em frames, da primeira track que tiver comprimento."""
    for tr in list(getattr(mob, "tracks", []) or []):
        comp = getattr(tr, "component", None)
        n = getattr(comp, "length", None)
        if n:
            return int(n)
    return None


def _atributos(mob) -> dict:
    a = getattr(mob, "attributes", None)
    try:
        return dict(a) if a else {}
    except Exception:  # noqa: BLE001
        return {}


def classificar(mob) -> tuple[bool | None, bool | None]:
    """`(e_ama, esta_offline)` de um master, lido da bin. `None` = **não dá para saber**.

    Serve ao relink PARCIAL: o editor pode querer relinkar só o que foi *importado*
    (deixando de fora o que já está AMA-linkado) e/ou só o que está *offline*.

    **Como se distingue:**

    - `e_ama` — o atributo **`_IMPORTED_AMA`** no master. Medido: presente nos masters
      criados por `LinkFile` e nos que autoramos; ausente nos masters de mídia gerenciada
      (o transcode que o Avid importou).
    - `esta_offline` — só para AMA, e pelo caminho: o arquivo existe no disco e o `mtime`
      bate com `_AMA_FILE_DATE_TIME`? São as duas condições que o banco de NLEs registra
      para o AMA vir online. Para mídia **gerenciada** a resposta não está na bin (mora no
      `msmMMOB.mdb`), então devolve `None`.

    ⚠️⚠️ **`None` não é `False`.** Quem filtra tem de deixar passar o que não sabe — a
    mesma regra da degradação do ADR 0011: *o caminho degradado nunca pode ser mais
    RESTRITIVO que o completo*. Tratar "não sei" como "está online" faria o filtro
    descartar em silêncio material que o editor precisava relinkar.
    """
    import os

    from avb_export import nle_model as NM

    from .segmentos import caminho_do_locator

    attrs = _atributos(mob)
    e_ama = "_IMPORTED_AMA" in attrs if attrs else None

    offline: bool | None = None
    if e_ama:
        try:
            # ⛔ CORRIGE (2026-10-13): era `reachable_sources(mob, {})` (índice VAZIO: nenhuma fonte achada) e o
            # `online_verdict`, que só lê `path_posix` (Mac) — no Windows o caminho nunca vinha e o "só offline" não
            # sabia de master AMA nenhum. Agora o índice da própria bin e o leitor das duas plataformas.
            fontes = NM.reachable_sources(mob, _indice_da_bin(mob))
            caminho = next((c for c in (caminho_do_locator(sm) for sm in fontes) if c), "")
            if caminho:
                data = next((d for d in (NM._attr(sm, "_AMA_FILE_DATE_TIME") for sm in fontes) if d is not None), None)
                existe = os.path.exists(caminho)
                mtime_ok = None
                if existe and data is not None:
                    mtime_ok = int(os.path.getmtime(caminho)) == int(data)
                # `mtime_ok is False` é offline com certeza; `None` só diz que não deu
                # para conferir — e aí vale o que o arquivo existir.
                offline = (not existe) or (mtime_ok is False)
        except Exception:  # noqa: BLE001
            offline = None
    return e_ama, offline


_INDICES: dict[int, tuple[object, dict]] = {}


def _indice_da_bin(mob) -> dict:
    """`{mob_id → mob}` da bin do `mob`, no formato do `nle_model` — montado uma vez por bin aberta."""
    from avb_export import nle_model as NM

    raiz = getattr(mob, "root", None)
    if raiz is None:
        return {}
    guardado = _INDICES.get(id(raiz))
    if guardado is None or guardado[0] is not raiz:
        guardado = (raiz, {NM._mobid(x.mob_id): x for x in raiz.content.mobs})
        _INDICES.clear()                      # uma bin por vez: não segura bins velhas na memória
        _INDICES[id(raiz)] = guardado
    return guardado[1]


def _origem(mob) -> str:
    """O caminho que a bin grava para a mídia do master (o locator das fontes que ele alcança) — ou `""`. A coluna
    "De onde veio" da lista de mídias; mídia gerenciada não tem caminho e fica vazia."""
    from avb_export import nle_model as NM

    from .segmentos import caminho_do_locator

    try:
        fontes = NM.reachable_sources(mob, _indice_da_bin(mob))
        return next((c for c in (caminho_do_locator(sm) for sm in fontes) if c), "")
    except Exception:  # noqa: BLE001 — acessório
        return ""


def _edit_rate(mob) -> float | None:
    for tr in list(getattr(mob, "tracks", []) or []):
        comp = getattr(tr, "component", None)
        er = getattr(comp, "edit_rate", None)
        if er:
            return float(er)
    return None


def _tc_de_origem(mob, por_id) -> tuple[int | None, int | None]:
    """O TC de origem do 1º quadro do master, como a cor o usa para religar (`segmentos.identidade_na_bin`). Acessório:
    o que não se lê fica `None` e o casamento segue sem a prova do TC."""
    try:
        from .segmentos import identidade_na_bin
        ident = identidade_na_bin(mob, por_id)
    except Exception:  # noqa: BLE001
        return None, None
    tc, fps = ident.get("tc_inicio"), ident.get("tc_fps")
    return (int(tc), int(fps)) if tc is not None and fps else (None, None)


def masters_em_uso(f, alvo=None) -> list[Master]:
    """Os masters que a timeline de fato usa, do que mais aparece para o que menos.

    Args:
        f: uma bin já aberta (use `avb_export.reader.topen`, que tolera o PCMA que
           estoura o pyavb em bins com áudio real).
        alvo: a `CompositionMob` da timeline; sem ela, a de mais tracks.

    ⚠️ `e_audio` sai do `media_kind` do **SourceClip da timeline**, não do master: um
    master de câmera é referenciado pela trilha de imagem E pelas de som, e classificá-lo
    pelo próprio mob marcaria o acervo inteiro de um jeito só.
    """
    alvo = alvo if alvo is not None else timeline(f)
    if alvo is None:
        return []

    por_id = por_mob_id(f)
    achados: dict[str, Master] = {}

    def registrar(mob, quero_audio: bool, trilha, canal=None, fim=None) -> None:
        chave = chave_mob(mob.mob_id)
        m = achados.get(chave)
        if m is None:
            e_ama, offline = classificar(mob)
            m = Master(
                nome=mob.name or "",
                mob_id=chave,
                mob_id_urn=str(mob.mob_id),
                e_audio=quero_audio,
                duracao_frames=_duracao(mob),
                edit_rate=_edit_rate(mob),
                e_ama=e_ama,
                esta_offline=offline,
                origem=_origem(mob),
            )
            m.tc_quadros, m.tc_fps = _tc_de_origem(mob, por_id)
            achados[chave] = m
        m.segmentos += 1
        if trilha is not None and trilha not in m.slots:
            m.slots.append(trilha)
        # Para o relink manual: o que a timeline usa deste master. `canal` é a track DO MASTER (as de som contam
        # 1..n entre si); `fim` = start + length na base do master.
        if quero_audio:
            if canal:
                m.canais_som = max(m.canais_som, int(canal))
        else:
            m.usa_imagem = True
        if fim is not None:
            m.uso_frames = max(m.uso_frames or 0, int(fim))

    for sc in source_clips(alvo):
        referenciado = por_id.get(str(sc.mob_id))
        if referenciado is None:
            continue
        kind = str(getattr(sc, "media_kind", "") or "").lower()
        e_audio = kind.startswith("sound")
        trilha = getattr(sc, "track_id", None)

        fim_sc = (getattr(sc, "start_time", 0) or 0) + (getattr(sc, "length", 0) or 0)
        if e_master(referenciado):
            # A timeline aponta direto para o master (música, SFX, efeito importado).
            registrar(referenciado, e_audio, trilha, canal=trilha, fim=fim_sc)
            continue

        if not e_subclipe(referenciado):
            continue

        # Desce ao subclipe pela track que o SourceClip pediu — índice E tipo de mídia.
        tr = track_de(referenciado, trilha, getattr(sc, "media_kind", None))
        internos = source_clips(getattr(tr, "component", None)) if tr is not None else []
        if not internos:
            # Sem track casando, vale qualquer SourceClip do subclipe: é melhor casar o
            # master por outro caminho do que perdê-lo da lista de trabalho.
            internos = source_clips(referenciado)
        for interno in internos:
            destino = por_id.get(str(interno.mob_id))
            if destino is not None and e_master(destino):
                # No subclipe, o clipe interno começa no master em `interno.start_time`; o da timeline conta a partir
                # do começo do subclipe. Somados, o fim do trecho no master.
                registrar(destino, e_audio, trilha, canal=getattr(interno, "track_id", None),
                          fim=(getattr(interno, "start_time", 0) or 0) + fim_sc)
                break

    log.info("%d masters em uso na timeline %r", len(achados), getattr(alvo, "name", ""))
    return sorted(achados.values(), key=lambda m: (-m.segmentos, m.nome))


def uso_maximo(f, alvo=None) -> dict[str, int]:
    """`{chave_mob do master → maior (start + length) que a timeline pede dele}`.

    ⭐ É o que permite autorar um master de áudio com a duração **certa** sem adivinhar a
    fórmula do Avid. Medido em 56 masters de um projeto real (2026-08-16): `ceil(duração
    real)` explica 33, `ceil(real)+1` explica 4, e **16 não casam com nenhuma candidata** —
    o Avid às vezes declara um frame de guarda, preenchido com silêncio, e às vezes não.
    Perseguir a fórmula seria adivinhar; o que a timeline PEDE é exato.

    ⚠️ **Chame DEPOIS de achatar.** Antes do achatamento a timeline aponta para subclipes,
    e o `start` do clipe ainda não incorporou o offset do subclipe — o número sairia
    pequeno demais e o master nasceria curto do mesmo jeito.

    ⚠️ Um master mais curto que este número **não é para ser preenchido em silêncio**: até
    1 ou 2 frames é o arredondamento do Avid; muito além disso é mídia diferente da que o
    editor usou, e aí a resposta certa é recusar e contar, não maquiar.
    """
    alvo = alvo if alvo is not None else timeline(f)
    if alvo is None:
        return {}
    por_id = por_mob_id(f)
    fora: dict[str, int] = {}
    for sc in source_clips(alvo):
        mob = por_id.get(str(sc.mob_id))
        if mob is None or not e_master(mob):
            continue
        fim = (getattr(sc, "start_time", 0) or 0) + (getattr(sc, "length", 0) or 0)
        chave = chave_mob(mob.mob_id)
        if fim > fora.get(chave, 0):
            fora[chave] = int(fim)
    return fora


def masters_de_arquivo(caminho_avb: str, alvo=None, mob_id: str | None = None) -> list[Master]:
    """`masters_em_uso` a partir de um caminho de `.avb` — da sequência `mob_id` (qualquer forma do MobID).

    ⛔ Sem `mob_id`, vale "a composição de mais trilhas" (`percurso.timeline`) — numa bin com VÁRIAS timelines é
    outra qualquer (medido 2026-10-12: na bin do laboratório, 92 sequências, ela escolhia `O01_MARCADO`, e a
    `LAB_ANIMATTE` pedida usa outros masters). Com `mob_id` que não está na bin: `ValueError`, nunca outra.
    """
    from avb_export.reader import topen

    with topen(caminho_avb) as f:
        if alvo is None and mob_id:
            from .segmentos import escolher_sequencia
            alvo = escolher_sequencia(f, mob_id=mob_id)
            if alvo is None:
                raise ValueError(f"a sequência {mob_id} não está em {caminho_avb}")
        return masters_em_uso(f, alvo)
