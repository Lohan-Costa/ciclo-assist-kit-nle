"""
avid/writer.py — autora a `.avb` de uma diária sincronizada. SÓ CORTES.

## Por que um writer próprio, e por que pequeno

O writer que provou o caminho é o do RELINKER (`avb_export/translate.py`, ~1500
linhas). Ele reconstrói timelines EDITADAS: transição, velocidade com rampa,
ganho, Title+, AudioSuite, subclipe, multicam. Uma diária sincronizada não tem
NADA disso — é corte seco, clipe inteiro, a 100%. Este módulo escreve só essa
fatia, e por isso cabe aqui em vez de arrastar o outro repositório para dentro de
um app distribuído.

O que ele NÃO faz, de propósito: transição, retime, ganho, efeito, subclipe,
clipe de grupo. Se algum dia a timeline precisar disso, o caminho é o writer do
RELINKER — não engordar este.

## Os dois modos de saída

**`media_bin=None` (padrão) — SÓ A TIMELINE.** A bin sai com um único objeto: a
`CompositionMob`. Os masters já vivem nas bins do editor, e o Avid resolve
`SourceClip` → mídia pelo **MobID no banco de mídia** (`msmMMOB.mdb`), não pela
bin. É o modo do fluxo do plugin: no Media Composer, `Find in Bin` a partir da
timeline leva ao clipe na bin ORIGINAL dele. Custa ~6 KB.

**`media_bin=<caminho>` — BIN AUTOSSUFICIENTE.** Emite a composição DENTRO de uma
bin que já contém os masters, e o resultado carrega mídia e timeline juntas
(~212 KB no mesmo material). É para entregar a quem não tem o projeto.

⚠️ **Não existe rede de "leak" aqui, e é intencional.** O writer do RELINKER troca
todo `SourceClip` que aponta para um mob ausente da bin por FILLER — defesa
correta lá, onde master ausente é bug. No modo só-timeline o master está ausente
por definição: aquela rede apagaria a timeline inteira e reportaria sucesso
(aconteceu, com 15 clipes virando buraco). Aqui a checagem é a oposta: um clipe
sem `mob_id` resolvido é ERRO, e sai como erro.

## As regras estruturais que o Media Composer exige

Descobertas na engenharia reversa do RELINKER e mantidas aqui — cada uma custou
um crash ou uma timeline quebrada:

- **Toda track abrange a duração TOTAL da composição.** Uma track que termina no
  último clipe dela faz o MC estourar ao navegar além do fim (`PMM_INSUFFICIENT_MEDIA`
  + assert em `GetVideoFrameOffset`). Daí o filler de cauda.
- **`Filler(0)` na cabeça** de cada sequência, quando ela não começa com gap.
- **Clamp do OUT:** um clipe que referencia além do fim do master estoura
  `PMM_INSUFFICIENT_MEDIA` no corte. Apara-se a duração e insere-se um filler do
  tamanho aparado — a track é sequencial, e sem o filler tudo depois desloca.
- **Composição só de áudio ganha uma V1 vazia** (convenção do Avid).
- **Track de timecode** começando em uma hora, e uma track de DescriptiveMetadata.
"""

from __future__ import annotations

import os
import random
from fractions import Fraction

# `avb` é o pyavb. ⚠️ Este pacote se chama `avid` justamente para não sombreá-lo:
# um pacote local chamado `avb` faria este import resolver para ele mesmo.
import avb
from avb.mobid import MobID

from .adapter import SOUND_TRACK_BASE

# Prefixo do MobID de composição autorada (o mesmo que o Avid usa).
COMP_PREFIX = bytes.fromhex("060a2b340101010501010f1013000000")
MAXLEN = 2147483647

# (num, den) → (edit_rate, fps do TC, código de formato, rótulo de formato).
# Os códigos são os que o Media Composer grava nos próprios projetos.
RATE = {
    (24000, 1001): (23.976, 24, 9, "HD 1080p/23.976"),
    (30000, 1001): (29.97, 30, 22, "HD 1080p/29.97"),
    (25, 1): (25.0, 25, 16, "HD 1080p/25"),  # 16 MEDIDO no MC 2024.6 (sequência feita à mão, 2026-10-31); o 13 DERRUBAVA o MC (CompressionManager.c 11276)
    (24, 1): (24.0, 24, 7, "HD 1080p/24"),
}


class AvbWriteError(Exception):
    """Erro que impede a timeline de sair correta. Nunca é degradação silenciosa."""


def caminho_de_bin_livre(pasta, base: str) -> str:
    """Um caminho de `.avb` que ainda não existe: `base.avb`, `base 2.avb`, …

    ⚠️ **NUNCA sobrescreva uma bin que o Media Composer possa ter aberta.** Medido:
    o `OpenBin` de uma bin JÁ ABERTA devolve `Completed` mas **não relê o disco** —
    o MC continua servindo a cópia em memória. O sintoma é cruel: você escreve a
    timeline corrigida, manda abrir, e o MC mostra (e reprova) a versão velha. Foi
    exatamente assim que um `PMM_INSUFFICIENT_MEDIA` sobreviveu à correção que o
    resolvia, e a única prova foi comparar o MobID da composição em disco com o
    que a API reportava.

    É o mesmo problema do nome duplicado de timeline no DaVinci Resolve, e a
    solução é a mesma: entregar sempre um nome novo.
    """
    from pathlib import Path

    pasta = Path(pasta)
    alvo = pasta / f"{base}.avb"
    n = 2
    while alvo.exists():
        alvo = pasta / f"{base} {n}.avb"
        n += 1
    return str(alvo)


def _rate_pair(timeline_fps: float) -> tuple[int, int]:
    """fps → fração exata. 23,976 TEM de virar 24000/1001: arredondar para 24
    derivaria ~1,7 s numa timeline de 29 min."""
    conhecidos = {23.976: (24000, 1001), 29.97: (30000, 1001), 59.94: (60000, 1001),
                  24.0: (24, 1), 25.0: (25, 1), 30.0: (30, 1), 50.0: (50, 1),
                  60.0: (60, 1)}
    r = conhecidos.get(round(float(timeline_fps), 3))
    if r:
        return r
    fr = Fraction(float(timeline_fps)).limit_denominator(1001)
    return fr.numerator, fr.denominator


def _resolve_rate(num: int, den: int):
    if (num, den) in RATE:
        return RATE[(num, den)]
    er = num / den
    return round(er, 3), round(er), 9, "HD 1080p/%g" % round(er, 3)


def _attrs(f, **kv):
    a = f.create.Attributes()
    for k, v in kv.items():
        a[k] = v
    return a


def _filler(f, er, length: int, media: str = "picture"):
    fl = f.create.Filler(er, media)
    fl.length = length
    return fl


def _trackref(f, er, media: str):
    tr = f.create.TrackRef(er, media)
    tr.length = MAXLEN
    tr.relative_scope = 0
    tr.relative_track = -1
    return tr


def _linha(segs: list[dict], master_ids: dict, master_lengths: dict | None):
    """Uma track: [(inicio, duracao, mob_hex, canal)], ordenada e sem sobreposição.

    Clipes de uma mesma track NÃO podem se sobrepor — o motor de sync já garante
    isso (ele resolve colisão pondo a câmera em outra track), mas se chegar aqui
    sobreposto a timeline sairia com um clipe comendo o outro em silêncio.
    """
    itens = []
    for s in sorted(segs, key=lambda x: int(x["timeline_start_frames"])):
        nome = s["clip_name"]
        h = master_ids.get(nome)
        if not h:
            raise AvbWriteError(
                f"clipe sem master no Avid: {nome!r}. Sem o MobID o clipe viraria "
                f"um buraco na timeline, então a escrita para aqui."
            )
        inicio = int(s["timeline_start_frames"])
        dur = int(s["duration_frames"])
        origem = int(s.get("source_start_frames") or 0)

        # CLAMP do OUT: o master pode ser 1-2 frames mais curto que o arquivo
        # original (transcode do Avid). Referenciar além do fim estoura
        # PMM_INSUFFICIENT_MEDIA no corte.
        if master_lengths:
            ml = master_lengths.get(h)
            if ml is not None and origem + dur > ml:
                dur = max(1, ml - origem)

        if itens:
            fim_anterior = itens[-1][0] + itens[-1][1]
            if inicio < fim_anterior:
                raise AvbWriteError(
                    f"clipes sobrepostos na mesma track: {nome!r} começa em {inicio} "
                    f"e o anterior termina em {fim_anterior}."
                )
        itens.append((inicio, dur, h, int(s.get("source_slot_id") or 1), origem))
    return itens


def _sequencia(f, er, tkind: str, itens, total: int):
    """Sequence de uma track: gaps de posição + SourceClips + filler de cauda."""
    seq = f.create.Sequence(er, tkind)
    seq.components = []
    pos = 0
    if not itens or itens[0][0] > 0:
        # `Filler(0)` de cabeça é convenção do Avid quando a track não começa com
        # um gap de verdade; o gap de posição vem logo depois.
        seq.components.append(_filler(f, er, 0, tkind))
    for inicio, dur, h, canal, origem in itens:
        if inicio > pos:
            seq.components.append(_filler(f, er, inicio - pos, tkind))
            pos = inicio
        sc = f.create.SourceClip(er, tkind)
        sc.mob_id = MobID(bytes_le=bytes.fromhex(h))
        # ⭐ `track_id` é o CANAL dentro do master, 1-based — o mesmo número que o
        # adapter pôs em `source_slot_id`. O writer do RELINKER derivava isso de um
        # mapa tirado do AAF e, sem AAF, caía num fallback que colapsava o canal 2
        # no 1: um estéreo saía com o canal 1 nas DUAS tracks, e o canal 4 de uma
        # câmera de 4 canais nunca era ouvido. Medido no primeiro `.avb` gerado.
        sc.track_id = canal if tkind == "sound" else 1
        sc.start_time = origem
        sc.length = dur
        seq.components.append(sc)
        pos = inicio + dur
    # Filler de cauda: TODA track abrange a composição inteira.
    seq.components.append(_filler(f, er, max(0, total - pos), tkind))
    return seq


def write_avb(
    segments: list[dict],
    timeline_fps: float,
    output_path: str,
    timeline_name: str,
    master_ids: dict[str, str],
    master_lengths: dict[str, int] | None = None,
    media_bin: str | None = None,
) -> dict:
    """Escreve o `.avb`. Devolve um resumo (nome, duração, tracks).

    `master_ids` — `{nome do clipe: mob_id hex}`. É a ponte entre o que o Órbita
    sincronizou e os masters que já existem no projeto do Avid.
    `master_lengths` — `{mob_id hex: duração em frames}`, para o clamp do OUT.
    `media_bin` — `None` (padrão) escreve SÓ a timeline; um caminho escreve uma
    bin autossuficiente por cima da bin de mídia dada.
    """
    if not segments:
        raise AvbWriteError("nenhum segmento para escrever")

    num, den = _rate_pair(timeline_fps)
    er, tc_fps, fmt_type, fmt_str = _resolve_rate(num, den)

    por_track: dict[int, list[dict]] = {}
    for s in segments:
        por_track.setdefault(int(s["track"]), []).append(s)

    linhas = []   # (tkind, itens)
    for tnum in sorted(por_track):
        tkind = "sound" if tnum >= SOUND_TRACK_BASE else "picture"
        linhas.append((tkind, _linha(por_track[tnum], master_ids, master_lengths)))

    total = max((i[0] + i[1] for _k, itens in linhas for i in itens), default=0)

    ctx = avb.open(media_bin) if media_bin else avb.open()
    with ctx as f:
        comp = f.create.Composition(timeline_name, "CompositionMob")
        comp.name = timeline_name
        comp.mob_id = MobID(bytes_le=bytes(bytearray(COMP_PREFIX) + os.urandom(16)))
        comp.edit_rate = er
        comp.media_kind_id = 0
        comp.usage_code = 0
        comp.length = total
        comp.mc_mode = 0
        comp.num_scalars = 0
        comp.param_list = None
        a = _attrs(f, _VERSION=2)
        # ⚠️ "SEQUERNCE" com o erro de digitação é o nome REAL da chave no formato
        # do Avid. Corrigir para "SEQUENCE" faz o MC ignorar o formato.
        a["SEQUERNCE_FORMAT_TYPE"] = fmt_type
        a["SEQUERNCE_FORMAT_STRING"] = fmt_str
        a["_USER"] = f.create.Attributes()
        a["_USER_POS"] = total
        comp.attributes = a
        comp.session_attrs = _attrs(f, _VIS_START=0, _VIS_END=MAXLEN)
        comp.tracks = []

        # ⭐ QUAL TRACK DE VÍDEO SAI COM O MONITOR LIGADO.
        #
        # `_MONSTATE` no `session_attr` da track é o botão de *monitoring* da timeline
        # — o que mostra "desta track para baixo". Sem ele a timeline abria com
        # NENHUMA track de vídeo monitorada, e o editor tinha de ligar na V mais alta
        # na mão, toda vez.
        #
        # Valores MEDIDOS numa bin salva pelo próprio Media Composer 25.12 (2026-08-09,
        # `primeiro teste dentro do avid.avb`, depois de o editor ligar o monitor na V2):
        #   picture sem monitor → _MONSTATE = 0
        #   picture COM monitor → _MONSTATE = 1   ← uma só track de vídeo o tem
        #   sound               → _MONSTATE = 2   (outro estado, não é "ligado")
        #
        # A mais ALTA é a certa porque o monitor do Avid é cumulativo para baixo:
        # ligando na V do topo, tudo abaixo aparece. Numa do meio, as câmeras acima
        # dela sumiriam do Composer.
        n_picture = sum(1 for k, _ in linhas if k == "picture")

        idx = {"picture": 0, "sound": 0}   # índices independentes por media_kind
        for tkind, itens in linhas:
            seq = _sequencia(f, er, tkind, itens, total)
            idx[tkind] += 1
            t = f.create.Track()
            t.index = idx[tkind]
            t.component = seq
            t.lock_number = 0
            t.filler_proxy = _trackref(f, er, tkind)
            if tkind == "sound":
                t.session_attr = _attrs(f, _MONSTATE=2, _ENBLSTATE=1)
                # Todas as nossas tracks de som são MONO (um canal por track), então
                # nunca há `_TRACK_FORMAT`.
                t.attributes = _attrs(f, AudioMixerCompSolo=0, AudioMixerCompMute=0)
            else:
                monitorada = idx["picture"] == n_picture
                t.session_attr = _attrs(f, _ENBLSTATE=0, _MONSTATE=1 if monitorada else 0)
            comp.tracks.append(t)

        if not any(k == "picture" for k, _ in linhas):
            # Composição só de áudio ganha uma V1 vazia — convenção do Avid.
            pseq = f.create.Sequence(er, "picture")
            pseq.components = [_filler(f, er, total, "picture")]
            pt = f.create.Track()
            pt.index = 1
            pt.component = pseq
            pt.lock_number = 0
            pt.filler_proxy = _trackref(f, er, "picture")
            pt.session_attr = _attrs(f, _ENBLSTATE=1, _MONSTATE=1)
            comp.tracks.append(pt)

        tc = f.create.Timecode(er, "timecode")
        tc.length = total
        tc.flags = 0
        tc.fps = tc_fps
        tc.start = 3600 * tc_fps          # a timeline começa em 01:00:00:00
        tct = f.create.Track()
        tct.index = 1
        tct.component = tc
        tct.lock_number = 0
        tct.session_attr = _attrs(f, _ENBLSTATE=0)
        comp.tracks.append(tct)

        dseq = f.create.Sequence(er, "DescriptiveMetadata")
        dseq.components = [_filler(f, er, total, "DescriptiveMetadata")]
        dt = f.create.Track()
        dt.index = 1
        dt.component = dseq
        dt.lock_number = 0
        dt.filler_proxy = _trackref(f, er, "DescriptiveMetadata")
        comp.tracks.append(dt)

        f.content.add_mob(comp)
        f.content.uid = random.getrandbits(63)
        f.write(output_path)

    return {
        "name": timeline_name,
        "length": total,
        "tracks": len(comp.tracks),
        "picture_tracks": sum(1 for k, _ in linhas if k == "picture"),
        "sound_tracks": sum(1 for k, _ in linhas if k == "sound"),
        "clips": sum(len(itens) for _k, itens in linhas),
        "only_timeline": media_bin is None,
        "output": output_path,
    }
