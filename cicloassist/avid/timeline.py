"""Autorar a timeline `.avb` — a `CompositionMob` que o editor abre na bin.

⭐ **Idioma PORTADO, não reinventado.** Vem de
`_ASSIST ANTERIOR/assist_anterior/modulos/assistir/sequencia.py`, que por sua vez copiou
`motores/delapraca/avb_export/translate.py` — código em produção, com round-trip contra um
Media Composer real (a timeline `C04_CORTE` abriu em 2026-08-30 e validou o trail `Filler`,
o `user_placed` e o matchframe).

⛔ **Escrever estrutura nova em vez de copiar a que está em produção é o erro que o projeto
anterior cometeu TRÊS vezes**, reintroduzindo defeito já medido e documentado. Se algo aqui
parecer redundante, leia o comentário antes de podar — a poda já custou a bin inteira uma
vez (ver `_trail_filler`).

## Por que `.avb` e não AAF importado

Qualquer rota de `ExportFile`/`ImportFile` depende de **preset**, que é configuração do
usuário — e o nome do preset mente (um chamado "AAF" exportava WAVE e fez o MC renderizar
26 minutos de áudio). Um produto instalado na estação de um cliente não pode ter o
resultado decidido por uma preferência que ele não controla. Ver
`docs/spec/2026-09-10-corte-zero.md` §2.
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import avb
from avb.core import walk_references
from avb.mobid import MobID

from .atributos import copiar_atributos

log = logging.getLogger("cicloassist.avid.timeline")

#: Prefixo de MobID de composição, o mesmo do `translate.py` (`COMP_PREFIX`). É o que faz
#: este mob parecer, pelo prefixo, uma composição autorada por este pipeline; os 16 bytes
#: finais são aleatórios por mob.
PREFIXO_DE_COMPOSICAO = bytes.fromhex("060a2b340101010501010f1013000000")

#: O comprimento "infinito" do `TrackRef`, idem `translate.py::MAXLEN`.
MAXIMO = 2147483647


@dataclass(frozen=True)
class Entrada:
    """Um clipe a enfileirar na timeline.

    `trilhas` são os pares `(media_kind, índice)` que **aquele clipe** tem — campo, e não
    constante, porque um take de câmera + som tem `("picture", 1)` e `("sound", 1..n)`,
    enquanto um take órfão de imagem não tem picture nenhuma.
    """

    #: O MobID do **subclipe**, na forma URN nativa do arquivo. Ver `start_time`.
    mob_id: str
    duracao: int
    trilhas: tuple
    #: ⭐⭐ O in DENTRO do clipe referenciado, em frames DELE.
    #:
    #: Como a timeline aponta para o SUBCLIPE, este é a posição dentro do TAKE — a mesma
    #: unidade que a transcrição devolve em `inicio_no_take`. Zero significa o take
    #: inteiro, do começo.
    #:
    #: ⚠️⚠️ **NÃO é o offset do master.** Somar o offset do master aqui, apontando para o
    #: subclipe, soma o recorte duas vezes — é o achatamento ao contrário. O
    #: `resolver_take` devolve `imagem.inicio_frames`, que é offset de master, e ele
    #: **não entra aqui**.
    start_time: int = 0

    #: ⭐⭐ O som pode NÃO coincidir com a imagem — é o que faz corte em L e em J.
    #:
    #: `None` nos dois significa "som colado na imagem", que é o corte seco. Quando vêm
    #: preenchidos, a trilha de som deste clipe entra mais cedo ou sai mais tarde que a
    #: de imagem, e as duas deixam de andar em paralelo nesta entrada.
    #:
    #: ⛔ **A soma das durações de som de TODAS as entradas tem de dar o mesmo total da
    #: imagem.** Quem garante isso é o plano (`plano/esquema._validar_o_som_entre_cortes`),
    #: por telescópio: o que um clipe perde no começo, o vizinho ganhou no fim. Aqui a
    #: conta não é refeita — se as duas somas divergirem, o `_trail_filler` tapa o buraco
    #: com silêncio e ninguém vê o erro até assistir.
    duracao_som: int | None = None
    start_som: int | None = None

    def duracao_de(self, media_kind: str) -> int:
        if media_kind == "sound" and self.duracao_som is not None:
            return self.duracao_som
        return self.duracao

    def inicio_de(self, media_kind: str) -> int:
        if media_kind == "sound" and self.start_som is not None:
            return self.start_som
        return self.start_time


@dataclass(frozen=True)
class Cobertura:
    """Uma arte com alpha (clipe de matte key da bin) por cima da imagem, numa trilha alta.

    ⭐ MEDIDO em 2026-09-13 (`SEQ ANALISE`, sequência feita à mão no MC 2025.6): o matte key
    editado na V2 é, na timeline, **o mesmo `TrackEffect EFF2_BLEND_MATTE_KEY` do clipe da
    bin** — trilha 1 um vazio que olha a trilha de BAIXO (`TrackRef relative_scope=1`),
    trilhas 2 e 3 o preenchimento e o alpha do master `precompute`. O MC só acrescenta
    `_MATCH` (a volta para o clipe da bin) e caches de reprodução; nenhum dos dois é gravado
    aqui. E o MC guardou, oculto na bin da sequência, o clipe de matte key e o `precompute`.
    """

    #: O MobID do CLIPE DE MATTE KEY na bin de origem (a `CompositionMob usage=effect`).
    mob_id: str
    #: Frames desde o início da sequência.
    posicao: int
    duracao: int
    #: Frame DENTRO da arte onde o trecho começa.
    inicio: int = 0
    #: O índice da trilha de imagem: 2 é a V2.
    trilha: int = 2


def _aparar_chave(f, efeito, edit_rate, inicio: int, duracao: int):
    """Cópia do `TrackEffect` do matte key neste arquivo, aparada para `[inicio, inicio+duracao)`.

    ⛔ Só a forma medida: trilha de fundo com vazio, e preenchimento/alpha como `SourceClip`
    direto. Outra forma (efeito aninhado no preenchimento, como o `rdp AM` da referência)
    é recusada — aparar o que não se entende desliza a arte em silêncio.
    """
    if inicio < 0 or duracao < 1 or inicio + duracao > efeito.length:
        raise ValueError(f"a arte tem {efeito.length} frames; o trecho {inicio}+{duracao} "
                         f"não cabe nela")
    novo = efeito.copy(f)
    for track in novo.tracks:
        comp = track.component
        tipo = type(comp).__name__
        if tipo == "Sequence" and all(type(c).__name__ == "Filler" for c in comp.components):
            comp.components = [_filler(f, edit_rate, duracao, comp.media_kind)]
        elif tipo == "SourceClip":
            comp.start_time = (comp.start_time or 0) + inicio
            comp.length = duracao
        else:
            raise ValueError(f"matte key com {tipo} na trilha {track.index}: essa forma "
                             f"ainda não é montada")
    # ⚠️ `right_length` não é medido quando a arte é APARADA: na referência sem aparo o MC
    #    copiou o valor da bin (121 num efeito de 121, 180 num de 179). Aqui a folga entre os
    #    dois é preservada.
    folga = (efeito.right_length or efeito.length) - efeito.length
    novo.length = duracao
    novo.right_length = duracao + folga
    return novo


def _trilha_de_cobertura(f, edit_rate, coberturas, total: int, origem) -> object:
    """A `Sequence` de uma trilha de artes: vazios entre elas, e o `Filler` de rabo."""
    por_id = {str(m.mob_id): m for m in origem.content.mobs}
    from .take import efeito_de_chave, fracao_da_taxa

    seq = f.create.Sequence(edit_rate, "picture")
    seq.components = []
    cursor = 0
    for cob in sorted(coberturas, key=lambda c: c.posicao):
        if cob.posicao < cursor:
            raise ValueError(f"duas artes se sobrepõem na V{cob.trilha} no frame {cob.posicao}")
        if cob.posicao + cob.duracao > total:
            raise ValueError(f"a arte em {cob.posicao} passa do fim da sequência ({total})")
        clipe = por_id.get(str(cob.mob_id))
        efeito = efeito_de_chave(clipe) if clipe is not None else None
        if efeito is None:
            raise ValueError(f"{cob.mob_id} não é um clipe de matte key nesta bin")
        if fracao_da_taxa(efeito.edit_rate) != fracao_da_taxa(edit_rate):
            raise ValueError(f"a arte {clipe.name!r} tem taxa {float(efeito.edit_rate):.3f} e a "
                             f"sequência {float(edit_rate):.3f}; misturar taxas ainda não é feito")
        seq.components.append(_filler(f, edit_rate, cob.posicao - cursor, "picture"))
        seq.components.append(_aparar_chave(f, efeito, edit_rate, cob.inicio, cob.duracao))
        cursor = cob.posicao + cob.duracao
    seq.components.append(_trail_filler(f, edit_rate, "picture", seq.components, total))
    return seq


def trilhas_do_take(take) -> tuple:
    """Os pares `(media_kind, índice)` de um `Take` resolvido.

    O índice é sequencial por tipo de mídia, começando em 1 — a mesma convenção que o
    subclipe usa internamente, então serve sem tradução tanto para o `track_id` do
    `SourceClip` quanto para o índice da track desta timeline.
    """
    pares = []
    if take.imagem is not None:
        pares += [("picture", i + 1) for i in range(take.imagem.tracks)]
    if take.som is not None:
        pares += [("sound", i + 1) for i in range(take.som.tracks)]
    return tuple(pares)


# ── as peças ─────────────────────────────────────────────────────────────────


def _atributos(f, **kv):
    a = f.create.Attributes()
    for k, v in kv.items():
        a[k] = v
    return a


def _filler(f, edit_rate, comprimento, media_kind):
    fl = f.create.Filler(edit_rate, media_kind)
    fl.length = comprimento
    return fl


def _referencia_de_track(f, edit_rate, media_kind):
    tr = f.create.TrackRef(edit_rate, media_kind)
    tr.length = MAXIMO
    tr.relative_scope = 0
    tr.relative_track = -1
    return tr


def _fonte(f, edit_rate, media_kind, entrada: Entrada, indice: int):
    sc = f.create.SourceClip(edit_rate, media_kind)
    sc.mob_id = MobID(str(entrada.mob_id))
    sc.track_id = indice
    # ⭐ É AQUI que o corte em L/J acontece: a trilha de som pode pegar outro trecho do
    #   take, e de outro tamanho, que o da imagem da mesma entrada.
    sc.start_time = entrada.inicio_de(media_kind)
    sc.length = entrada.duracao_de(media_kind)
    return sc


def _trail_filler(f, edit_rate, media_kind, componentes, total):
    """O `Filler` de rabo — **INCONDICIONAL**, inclusive quando o comprimento dá zero.

    ⚠️⚠️ **São DUAS invariantes, e confundi-las custou a bin inteira no projeto anterior.**

    A de DURAÇÃO — *"toda track abrange a duração inteira do comp"* — já é satisfeita por
    construção: toda entrada contribui `duracao` para toda track, como `SourceClip` ou como
    `Filler`. Daí é tentador concluir que o trail é um `Filler(0)` redundante, e podá-lo.

    ⛔ **A outra invariante é ESTRUTURAL, e o Avid a afirma explicitamente:**

        Assertion failed: CompIsFiller(last) || TT_SOUND_MASTER==GetType()
        CompMan\\ASequence.c, line 1549

    O ÚLTIMO componente da lista tem de ser literalmente um `Filler`, tenha a soma fechado
    ou não. Com o trail removido, o Media Composer recusou as **sete** timelines emitidas
    em 2026-08-29 — nenhuma abria.
    """
    soma = sum(getattr(c, "length", 0) or 0 for c in componentes)
    return _filler(f, edit_rate, max(0, total - soma), media_kind)


# ── a timeline ───────────────────────────────────────────────────────────────


def montar_timeline(f, nome: str, entradas, edit_rate: float, drop_frame: bool = False,
                    coberturas=(), origem=None):
    """A `CompositionMob` de timeline (não-subclipe), já acrescentada a `f`.

    As entradas entram **na ordem**, uma atrás da outra. Onde uma entrada não tem a trilha,
    entra `Filler` do tamanho dela — é o que mantém as tracks alinhadas entre si.

    `drop_frame` só vale a 29,97/59,94, e segue o PROJETO (`mcapi.projeto()["drop_frame"]`).
    `coberturas` são artes de matte key por cima (`Cobertura`), copiadas de `origem` — o
    arquivo ABERTO da bin onde os clipes de matte key moram.
    """
    entradas = list(entradas)
    if not entradas:
        raise ValueError(
            f"timeline {nome!r} sem entrada nenhuma — uma sequência vazia é item morto na "
            f"bin do editor"
        )

    total = sum(e.duracao for e in entradas)
    presentes = sorted({t for e in entradas for t in e.trilhas})
    tem_imagem = any(k == "picture" for k, _ in presentes)

    comp = f.create.Composition(nome, "CompositionMob")
    # ⚠️⚠️ O construtor IGNORA o nome (faz `self.name = mob_type`). Sem esta linha a bin
    # sai com todas as timelines chamadas "CompositionMob".
    comp.name = nome
    comp.mob_id = MobID(bytes_le=bytes(bytearray(PREFIXO_DE_COMPOSICAO) + os.urandom(16)))
    comp.edit_rate = edit_rate
    comp.media_kind_id = 0
    comp.usage_code = 0        # 0 = composição normal (2 = subclipe, 4 = grupo)
    comp.length = total
    comp.mc_mode = 0
    comp.num_scalars = 0
    comp.param_list = None
    comp.attributes = _atributos(f, _VERSION=2)
    comp.session_attrs = _atributos(f, _VIS_START=0, _VIS_END=MAXIMO)
    comp.tracks = []

    for media_kind, indice in presentes:
        seq = f.create.Sequence(edit_rate, media_kind)
        seq.components = [_filler(f, edit_rate, 0, media_kind)]
        for entrada in entradas:
            if (media_kind, indice) in entrada.trilhas:
                seq.components.append(_fonte(f, edit_rate, media_kind, entrada, indice))
            else:
                # ⭐ Sem este filler as tracks escorregam umas contra as outras e o áudio
                # de uma fala cai por baixo da imagem de outra.
                #
                # ⚠️ E o buraco tem o tamanho DESTA trilha, não o da imagem: num corte em
                # L/J o clipe de som é mais curto ou mais longo que o de imagem, e usar a
                # duração da imagem aqui reintroduziria o escorregamento pela porta dos
                # fundos — justamente no take que não tem som direto.
                seq.components.append(
                    _filler(f, edit_rate, entrada.duracao_de(media_kind), media_kind))
        seq.components.append(_trail_filler(f, edit_rate, media_kind, seq.components, total))

        track = f.create.Track()
        track.index = indice
        track.component = seq
        track.lock_number = 0
        track.filler_proxy = _referencia_de_track(f, edit_rate, media_kind)
        if media_kind == "sound":
            track.session_attr = _atributos(f, _MONSTATE=2, _ENBLSTATE=1)
            track.attributes = _atributos(f, AudioMixerCompSolo=0, AudioMixerCompMute=0)
        else:
            # ⛔ **Desvio deliberado do `translate.py`, herdado com o motivo escrito.**
            # Lá a picture track povoada sai `0/0`, o que na prática nasce com o vídeo
            # DESLIGADO — o autor abria o corte e tinha de ligar a V1 na mão. Um corte que
            # o editor abre para CONFERIR tem de mostrar imagem sem exigir um clique.
            track.session_attr = _atributos(f, _ENBLSTATE=1, _MONSTATE=1)
        comp.tracks.append(track)

    coberturas = list(coberturas or [])
    if coberturas:
        if origem is None:
            raise ValueError("artes de cobertura precisam da bin de origem aberta")
        ocupadas = {i for k, i in presentes if k == "picture"}
        # ⚠️ Logo depois das trilhas de imagem, antes do som: é a ordem que o MC gravou na
        #    referência (V1, V2, A1…A4).
        onde = len(ocupadas)
        for indice in sorted({c.trilha for c in coberturas}):
            if indice < 2 or indice in ocupadas:
                raise ValueError(f"a V{indice} já é da imagem dos cortes; a arte vai numa "
                                 f"trilha acima")
            track = f.create.Track()
            track.index = indice
            track.component = _trilha_de_cobertura(
                f, edit_rate, [c for c in coberturas if c.trilha == indice], total, origem)
            track.lock_number = 0
            track.filler_proxy = _referencia_de_track(f, edit_rate, "picture")
            track.session_attr = _atributos(f, _ENBLSTATE=1, _MONSTATE=1)
            comp.tracks.insert(onde, track)
            onde += 1

    if not tem_imagem:
        # ⚠️ Convenção do Avid: comp só de áudio ganha uma V1 vazia.
        seq = f.create.Sequence(edit_rate, "picture")
        seq.components = [_filler(f, edit_rate, total, "picture")]
        track = f.create.Track()
        track.index = 1
        track.component = seq
        track.lock_number = 0
        track.filler_proxy = _referencia_de_track(f, edit_rate, "picture")
        track.session_attr = _atributos(f, _ENBLSTATE=1, _MONSTATE=1)
        comp.tracks.append(track)

    fps = int(round(edit_rate))
    tc = f.create.Timecode(edit_rate, "timecode")
    tc.length = total
    # ⭐ MEDIDO em 2026-09-13 (`SEQ ANALISE`, sequências feitas à mão no MC 2025.6): drop-frame
    #    é `flags = 1` com `start = 107892` — a contagem contínua de `01;00;00;00`; non-drop é
    #    `flags = 0` com `start = 108000`. Até então toda timeline daqui nascia non-drop,
    #    inclusive num projeto 1080i/59.94 drop-frame.
    df = bool(drop_frame) and fps in (30, 60)
    tc.flags = 1 if df else 0
    tc.fps = fps
    # 01:00:00:00, a convenção de início de timeline. Em DF saem da conta os rótulos pulados
    # numa hora: 2 (ou 4, a 59,94) por minuto, nos 54 minutos que não são múltiplos de dez.
    tc.start = 3600 * fps - ((2 * (fps // 30)) * 54 if df else 0)
    tct = f.create.Track()
    tct.index = 1
    tct.component = tc
    tct.lock_number = 0
    tct.session_attr = _atributos(f, _ENBLSTATE=0)
    comp.tracks.append(tct)

    dseq = f.create.Sequence(edit_rate, "DescriptiveMetadata")
    dseq.components = [_filler(f, edit_rate, total, "DescriptiveMetadata")]
    dt = f.create.Track()
    dt.index = 1
    dt.component = dseq
    dt.lock_number = 0
    dt.filler_proxy = _referencia_de_track(f, edit_rate, "DescriptiveMetadata")
    comp.tracks.append(dt)

    # ⚠️ `user_placed` é o que faz a timeline APARECER na bin. Sem isso o mob existe no
    # arquivo e o editor não o vê.
    f.content.add_mob(comp).user_placed = True
    return comp


def fecho(indice: dict, mob_ids) -> dict:
    """Todo mob de que `mob_ids` precisam, transitivamente, pelos `SourceClip`.

    ⚠️ `SourceClip` aponta por **MobID**, que é VALOR, não referência de objeto: o
    `walk_references` do pyavb não atravessa isso. Quem não resolver o MobID à mão conclui
    que a timeline não depende de nada.

    MobID que não está em `indice` fica de fora calado: é o material number todo zero que
    fecha a cadeia, ou mídia gerenciada que resolve pelo banco de mídia do Media Composer.
    """
    achados, pendentes = {}, [str(m) for m in mob_ids]
    while pendentes:
        mid = pendentes.pop()
        if mid in achados or mid not in indice:
            continue
        achados[mid] = indice[mid]
        for o in walk_references(indice[mid]):
            if type(o).__name__ == "SourceClip":
                pendentes.append(str(o.mob_id))
    return achados


def escrever_bin(saida: Path | str, timelines: list[tuple],
                 edit_rate: float, base: Path | str | None = None,
                 drop_frame: bool = False) -> Path:
    """Grava uma bin NOVA com as timelines pedidas.

    ⛔⛔ **Com `base`, a bin nova leva o FECHO junto, oculto.** A timeline aponta
    SUBCLIPES, e subclipe é objeto de bin: não está no banco de mídia e não resolve fora
    dela. Uma bin só com a timeline **abre** e lista tudo certo, e o Media Composer cai com
    `ACCESS_VIOLATION` ao CARREGAR (banco, `protocolos/avb/escrita.md`, 2026-08-30). Levar
    os mobs com `user_placed=False` é a saída validada em produção em 2026-08-31, e ocultar
    não é cosmética: o matchframe aponta a bin onde o clipe NÃO está oculto, a do editor.

    ⛔⛔ **Nunca grava sobre a bin de origem.** Medido no projeto anterior: o `topen` do
    pyavb é preguiçoso e passaria a ler offsets de um arquivo já truncado —
    `3.922 bytes → 119`, bin destruída.
    """
    saida = Path(saida)
    if base is not None and saida.resolve() == Path(base).resolve():
        raise ValueError(
            f"a bin de saída e a bin base são o mesmo arquivo ({saida}). "
            f"Gravar sobre a base destrói a bin."
        )
    if not timelines:
        raise ValueError("nenhuma timeline a escrever")

    saida.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as pilha:
        f = pilha.enter_context(avb.open())
        # ⚠️ A origem abre ANTES de montar: a arte de cobertura é copiada dela, e o pyavb lê
        #    preguiçoso — o que o `copy` não tocou seria buscado num arquivo fechado.
        origem = pilha.enter_context(avb.open(str(base))) if base is not None else None
        ids: set[str] = set()
        for item in timelines:
            nome, entradas = item[0], item[1]
            coberturas = item[2] if len(item) > 2 else ()
            montar_timeline(f, nome, entradas, edit_rate, drop_frame, coberturas, origem)
            ids |= {e.mob_id for e in entradas} | {c.mob_id for c in coberturas}
        levados = _levar_fecho(f, origem, ids, set()) if origem is not None else 0
        f.write(str(saida))

    log.info("bin escrita: %s (%d timeline(s), %d mob(s) de fecho)",
             saida, len(timelines), levados)
    return saida


def _levar_fecho(f, origem, mob_ids, ja_tem: set[str]) -> int:
    """Copia para `f`, OCULTO, o fecho de `mob_ids` que ainda não está em `f`.

    ⚠️ O que o destino JÁ TEM não entra de novo: dois `BinItem` com o mesmo MobID na mesma
    bin é dado contraditório dentro de um arquivo só (`spikes/mover_entre_bins.py`).
    ⚠️ Quem chama grava DENTRO do `with` da origem: o pyavb lê preguiçoso, e o que o `copy`
    não tiver tocado ainda seria buscado num arquivo fechado (`seek of closed file`).
    ⭐ O clipe de matte key entra no fecho pelo próprio MobID, e o `precompute` vem por ele —
    é o que o MC guardou oculto na bin da referência.
    """
    indice = {str(m.mob_id): m for m in origem.content.mobs}
    precisos = fecho(indice, {str(m) for m in mob_ids})
    novos = [m for mid, m in precisos.items() if mid not in ja_tem]
    for mob in novos:
        # ⭐ `copy(root)` recria o objeto NESTE arquivo com `instance_id` novo; o
        #   `add_mob` do objeto cru seria recusado no write ("object is from different
        #   file"). O `mob_id` viaja por valor: é o MESMO clipe.
        f.content.add_mob(mob.copy(f)).user_placed = False
    return len(novos)


def acrescentar_timeline(bin_existente: Path | str, nome: str, entradas,
                         edit_rate: float, base: Path | str | None = None,
                         drop_frame: bool = False, coberturas=()) -> Path:
    """Põe mais uma timeline numa bin que JÁ EXISTE, preservando o que estava lá.

    ⛔⛔ **A bin precisa estar FECHADA no Media Composer.** Quem garante isso é quem chama
    (`CloseBin` antes), e a razão está medida no banco de NLEs
    (`protocolos/avb/escrita.md`, 2026-08-16):

    | | bin ABERTA no MC | bin FECHADA |
    |---|---|---|
    | **UID preservado** | ⛔ `FILE_OPEN_FAILURE` | ✅ abre |
    | **UID randomizado** | ✅ abre, mas como OUTRA bin (`.AutoCopy.NN`) | ✅ abre |

    ⭐ Aqui o UID é **preservado de propósito**: é a MESMA bin do editor ganhando mais uma
    sequência, não uma cópia. Randomizar faria o Media Composer tratá-la como bin nova e
    renomear o conteúdo — que é o oposto do que o editor pediu ao mandar gravar ali.

    ⚠️⚠️ **Grava ao lado e só então substitui.** O `topen` do pyavb é PREGUIÇOSO: escrever
    no mesmo caminho que ele está lendo corrompe a bin e derruba o MC ao abri-la
    (`unpack requires a buffer of 8 bytes`, medido em 2026-08-16). O `os.replace` só
    acontece depois que o handle de leitura fechou.

    ⛔⛔ **Com `base` noutra bin, o fecho vem junto** — o mesmo motivo do `escrever_bin`:
    MEDIDO em 2026-09-13, `bin_da_sequencia` apontando uma bin que não tinha os masters do
    corte gravou a timeline pelada, e a bin abriu normalmente. Subclipe fora da bin derruba
    o Media Composer ao carregar (banco, 2026-08-30).
    """
    return acrescentar_timelines(bin_existente, [(nome, entradas, list(coberturas or []))],
                                 edit_rate, base=base, drop_frame=drop_frame)


def acrescentar_timelines(bin_existente: Path | str, timelines: list[tuple],
                          edit_rate: float, base: Path | str | None = None,
                          drop_frame: bool = False) -> Path:
    """`acrescentar_timeline` para VÁRIAS, numa gravação só — ver o docstring de lá.

    `timelines` como em `escrever_bin`: `(nome, entradas)` ou `(nome, entradas, coberturas)`.
    ⭐ Nasceu para o `separar_falas` em lotes (2026-09-15): treze timelines regravando a bin
    treze vezes seriam treze janelas em que uma falha deixa a bin pela metade.
    """
    destino = Path(bin_existente)
    if not destino.exists():
        raise ValueError(f"a bin {destino} não existe")
    outra_bin = base is not None and Path(base).resolve() != destino.resolve()

    temporario = destino.with_suffix(destino.suffix + ".novo")
    try:
        with contextlib.ExitStack() as pilha:
            f = pilha.enter_context(avb.open(str(destino)))
            origem = pilha.enter_context(avb.open(str(base))) if outra_bin else f
            quantas_antes = len(list(f.content.mobs))
            ja_tem = {str(m.mob_id) for m in f.content.mobs}
            apontados: set[str] = set()
            for item in timelines:
                nome, entradas = item[0], item[1]
                coberturas = list(item[2]) if len(item) > 2 else []
                montar_timeline(f, nome, entradas, edit_rate, drop_frame, coberturas, origem)
                apontados |= {e.mob_id for e in entradas} | {c.mob_id for c in coberturas}
            if outra_bin:
                _levar_fecho(f, origem, apontados, ja_tem)
            f.write(str(temporario))
        # ⚠️ Fora do `with`: o handle de leitura precisa estar fechado antes da troca.
        # ⚠️ E os atributos da bin do Mac vão junto, senão a troca os apaga (`atributos`).
        copiar_atributos(destino, temporario)
        os.replace(temporario, destino)
    except Exception:
        temporario.unlink(missing_ok=True)
        raise

    log.info("%d timeline(s) acrescentada(s) a %s (%d mobs antes)", len(timelines), destino,
             quantas_antes)
    return destino
