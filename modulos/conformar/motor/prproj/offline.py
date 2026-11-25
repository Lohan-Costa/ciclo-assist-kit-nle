"""MÍDIA OFFLINE no `.prproj`: o mesmo item que o Premiere cria em Arquivo ▸ Novo ▸ Arquivo offline… (2026-11-25).

O plano sem mídia nesta máquina não pode sumir da timeline (regra do autor). Nem o ExtendScript nem o QE criam mídia
offline; o que o Premiere GRAVA para ela é pequeno e foi medido no 26.0.2 (Mac), pilotando o diálogo com um plano do
PRODUCAO-A (A/V) e o room tone (só som) — banco `protocolos/prproj/escrita.md` §11o; projetos de referência em
`MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/SAIDAS/LAB OFFLINE PREMIERE/`:

    ClipProjectItem → MasterClip (Properties `MZ.offlineclip.*`) → ClipLoggingInfo + AudioComponentChain
      + VideoClip/AudioClip → Video/AudioMediaSource → <Media> só com Start (o TC), TapeName, Title (o NOME DO
      ARQUIVO) e OfflineReason 5 — SEM caminho, sem FileKey, sem ImporterPrefs — + Video/AudioStream.

Este módulo escreve esses objetos (texto, na forma exata do Premiere) com ids novos; `projeto_com_offline` os enxerta
numa cópia de um projeto e devolve o `.prproj` pronto (gzip com o cabeçalho do Premiere, §0). Enxertados assim, o
Premiere abriu sem diálogo e `changeMediaPath` religou com a mesma entrada, duração e TC (medido).

Canais: 1 (mono: `channellabel` 0, `ChannelType` 0 — como os sons-molde do app) e 2 (estéreo: 100/101, `ChannelType` 1 —
o do diálogo). Mais de 2 (o som direto polifônico): N canais MONO, na forma que o 26.0.2 grava para um WAV de 5 canais
importado (2026-11-25, `LAB OFFLINE MULTICANAL v01`): um `Media` por canal (`StreamNumber` 1…N−1 a partir do 2º), cada um
com o seu `AudioMediaSource`, `AudioClip` mono, cadeia, vetor e `ClipChannelSerializer` (`SourceClipIndex` k, canal 0) —
`_item_multicanal`.
"""
from __future__ import annotations

import gzip
import re
import struct
import uuid
import zlib
from fractions import Fraction
from xml.sax.saxutils import escape

TICKS_POR_SEGUNDO = 254016000000
#: a taxa do áudio que o Premiere grava (ticks por amostra a 48 kHz)
TICKS_AUDIO_48K = 5292000

_CLASSE = {
    "ClipProjectItem": "cb4e0ed7-aca1-4171-8525-e3658dec06dd",
    "MasterClip": "fb11c33a-b0a9-4465-aa94-b6d5db2628cf",
    "ClipLoggingInfo": "77ab7fdd-dcdf-465d-9906-7a330ca1e738",
    "AudioComponentChain": "3cb131d1-d3c0-47ae-a19a-bdf75ea11674",
    "VideoClip": "9308dbef-2440-4acb-9ab2-953b9a4e82ec",
    "AudioClip": "b8830d03-de02-41ee-84ec-fe566dc70cd9",
    "ClipChannelGroupVectorSerializer": "a3127a8c-95d4-456e-a7f5-171b3f922426",
    "VideoMediaSource": "e64ddf74-8fac-4682-8aa8-0e0ca2248949",
    "AudioMediaSource": "f588da05-fc2a-4fbc-9383-74d653b379e3",
    "SecondaryContent": "f9d004b5-cb04-4e2f-af6f-64fadc2c4be9",
    "ClipChannelVectorSerializer": "333d203b-3a53-4195-8894-fc7523ff3dc7",
    "Media": "7a5c103e-f3ac-4391-b6b4-7cc3d2f9a7ff",
    "ClipChannelSerializer": "5c89aa7a-89a6-4483-becd-f2b1def42316",
    "AudioStream": "0b5cf52f-2b85-4863-890b-8844b64ecfe9",
    "VideoStream": "a36e4719-3ec6-4a0c-ab11-8b4aab377aa5",
}
_VERSAO = {"ClipProjectItem": 1, "MasterClip": 12, "ClipLoggingInfo": 10, "AudioComponentChain": 4, "VideoClip": 11,
           "AudioClip": 8, "ClipChannelGroupVectorSerializer": 1, "VideoMediaSource": 2, "AudioMediaSource": 2,
           "SecondaryContent": 1, "ClipChannelVectorSerializer": 1, "Media": 30, "ClipChannelSerializer": 1,
           "AudioStream": 8, "VideoStream": 22}
_ROTULO = "BE.Prefs.LabelColors.1"


def ticks_por_quadro(fps: float) -> int:
    """23.976 → 24000/1001 exato (10594584000 ticks, o que o Premiere grava)."""
    for n in (24, 30, 48, 60, 120):
        if abs(fps - n * 1000 / 1001) < 0.002:
            return round(Fraction(TICKS_POR_SEGUNDO) / Fraction(n * 1000, 1001))
    return round(Fraction(TICKS_POR_SEGUNDO) / Fraction(fps).limit_denominator(1001))


def _layout(canais: int) -> tuple[str, int, int]:
    """(AudioChannelLayout, ChannelType, nº de canais do item)."""
    if canais == 2:
        return '[{"channellabel":100},{"channellabel":101}]', 1, 2
    return '[{"channellabel":0}]', 0, 1


def _abre(tag: str, oid) -> str:
    chave = "ObjectUID" if isinstance(oid, str) else "ObjectID"
    return f'\t<{tag} {chave}="{oid}" ClassID="{_CLASSE[tag]}" Version="{_VERSAO[tag]}">'


def item(nome: str, dur_ticks: int, proximo_id: int, *, fita: str = "", inicio_ticks: int = 0,
         video: dict | None = None, canais: int = 2, fps_video: float | None = None,
         mono: bool = False) -> tuple[str, str, int]:
    """Os objetos de UM item offline: `(xml, uid do ClipProjectItem, próximo ObjectID livre)`.

    `nome`: o nome do ARQUIVO original (vira o nome do item e o `Title` da mídia — é por ele que o editor religa).
    `video`: `{"largura", "altura", "par": (n, d)}` ou None (só som). `fps_video`: a taxa do original (a do MasterClip
    mesmo no só de som, como o diálogo grava). `inicio_ticks`: o TC de início em ticks; 0 = sem TC (não se grava).
    `mono`: 2 canais como 2 MONO (a forma do multicanal), não estéreo. ⛔ O offline ESTÉREO religado a um arquivo de
    MAIS de 2 canais deixa o canal 2 sem fonte (`ChannelIndex` −1, mudo) — medido no 26.0.2 nos três de 8 canais da B03
    (`spikes/offline_premiere_matriz.py`, variante parcial); em N mono, com menos canais que o arquivo, religa certo."""
    if dur_ticks <= 0:
        raise ValueError(f"duração inválida para {nome!r}")
    if canais > 2 or (mono and canais == 2):
        return _item_multicanal(nome, dur_ticks, proximo_id, fita=fita, inicio_ticks=inicio_ticks, video=video,
                                canais=canais, fps_video=fps_video)
    fps_t = ticks_por_quadro(fps_video or 24000 / 1001)
    layout, tipo_canal, n = _layout(canais)
    nome_x, fita_x = escape(nome), escape(fita)
    uid_cpi, uid_mc, uid_media = (str(uuid.uuid4()) for _ in range(3))
    ids = iter(range(proximo_id, proximo_id + 64))
    i_log, i_chain = next(ids), next(ids)
    i_vclip = next(ids) if video else None
    i_aclip, i_grupo = next(ids), next(ids)
    i_vsrc = next(ids) if video else None
    i_asrc = next(ids)
    i_sec = [next(ids) for _ in range(n)]
    i_vetor = next(ids)
    i_canal = [next(ids) for _ in range(n)]
    i_astream = next(ids)
    i_vstream = next(ids) if video else None
    proximo = next(ids)
    w, h = (video or {}).get("largura", 1920), (video or {}).get("altura", 1080)
    par = (video or {}).get("par") or (1, 1)
    L = []
    L += [_abre("ClipProjectItem", uid_cpi), "\t\t<ProjectItem Version=\"1\">", "\t\t\t<Node Version=\"1\">",
          "\t\t\t\t<Properties Version=\"1\">", "\t\t\t\t\t<project.icon.view.grid.order>0</project.icon.view.grid.order>"]
    if video:     # o rótulo de cor só vem no item com vídeo (o só de som não o grava)
        L += [f"\t\t\t\t\t<Column.PropertyText.Label>{_ROTULO}</Column.PropertyText.Label>"]
    L += ["\t\t\t\t</Properties>", "\t\t\t</Node>", f"\t\t\t<Name>{nome_x}</Name>", "\t\t</ProjectItem>",
          f'\t\t<MasterClip ObjectURef="{uid_mc}"/>', "\t</ClipProjectItem>"]
    L += [_abre("MasterClip", uid_mc), "\t\t<Node Version=\"1\">", "\t\t\t<Properties Version=\"1\">",
          f"\t\t\t\t<MZ.offlineclip.AudioFrameRate>{TICKS_AUDIO_48K}</MZ.offlineclip.AudioFrameRate>",
          f"\t\t\t\t<MZ.offlineclip.VideoFrameRate>{fps_t}</MZ.offlineclip.VideoFrameRate>",
          f"\t\t\t\t<MZ.offlineclip.VideoFrameRect.Width>{w}</MZ.offlineclip.VideoFrameRect.Width>",
          f"\t\t\t\t<MZ.offlineclip.VideoFrameRect.Height>{h}</MZ.offlineclip.VideoFrameRect.Height>",
          f"\t\t\t\t<MZ.offlineclip.VideoPAR.num>{par[0]}</MZ.offlineclip.VideoPAR.num>",
          f"\t\t\t\t<MZ.offlineclip.VideoPAR.den>{par[1]}</MZ.offlineclip.VideoPAR.den>",
          "\t\t\t</Properties>", "\t\t</Node>", f'\t\t<LoggingInfo ObjectRef="{i_log}"/>',
          "\t\t<AudioComponentChains Version=\"1\">", f'\t\t\t<AudioComponentChain Index="0" ObjectRef="{i_chain}"/>',
          "\t\t</AudioComponentChains>", "\t\t<Clips Version=\"1\">"]
    clips = ([i_vclip] if video else []) + [i_aclip]
    L += [f'\t\t\t<Clip Index="{k}" ObjectRef="{c}"/>' for k, c in enumerate(clips)]
    L += ["\t\t</Clips>", f'\t\t<AudioClipChannelGroups ObjectRef="{i_grupo}"/>', f"\t\t<Name>{nome_x}</Name>",
          f"\t\t<DefMappingID>{uuid.uuid4()}</DefMappingID>", "\t\t<MasterClipChangeVersion>0</MasterClipChangeVersion>",
          "\t</MasterClip>"]
    taxa_log = fps_t if video else TICKS_AUDIO_48K
    L += [_abre("ClipLoggingInfo", i_log)]
    if not video:
        L += ["\t\t<CaptureMode>1</CaptureMode>"]
    if fita:
        L += [f"\t\t<TapeName>{fita_x}</TapeName>"]
    L += [f"\t\t<ClipName>{nome_x}</ClipName>", "\t\t<TimecodeFormat>110</TimecodeFormat>",
          f"\t\t<MediaInPoint>{inicio_ticks}</MediaInPoint>", f"\t\t<MediaOutPoint>{inicio_ticks + dur_ticks}</MediaOutPoint>",
          f"\t\t<MediaFrameRate>{taxa_log}</MediaFrameRate>", "\t</ClipLoggingInfo>"]
    L += [_abre("AudioComponentChain", i_chain), "\t\t<DefaultVol>true</DefaultVol>",
          "\t\t<DefaultVolumeComponentID>1</DefaultVolumeComponentID>",
          "\t\t<DefaultChannelVolumeComponentID>2</DefaultChannelVolumeComponentID>", "\t\t<ComponentChain Version=\"3\">",
          "\t\t</ComponentChain>", f"\t\t<AudioChannelLayout>{layout}</AudioChannelLayout>",
          f"\t\t<ChannelType>{tipo_canal}</ChannelType>", "\t</AudioComponentChain>"]

    def clipe(tag, oid, fonte, extra):
        rot = ["\t\t\t<Node Version=\"1\">", "\t\t\t\t<Properties Version=\"1\">",
               f"\t\t\t\t\t<asl.clip.label.name>{_ROTULO}</asl.clip.label.name>",
               "\t\t\t\t\t<asl.clip.label.color>13408882</asl.clip.label.color>", "\t\t\t\t</Properties>",
               "\t\t\t</Node>"] if video else []
        return ([_abre(tag, oid), "\t\t<Clip Version=\"18\">"] + rot +
                [f'\t\t\t<Source ObjectRef="{fonte}"/>', f"\t\t\t<ClipID>{uuid.uuid4()}</ClipID>",
                 "\t\t\t<InUse>false</InUse>", "\t\t</Clip>"] + extra + [f"\t</{tag}>"])

    if video:
        L += clipe("VideoClip", i_vclip, i_vsrc, [])
    L += clipe("AudioClip", i_aclip, i_asrc, ["\t\t<SecondaryContents Version=\"1\">"] +
               [f'\t\t\t<SecondaryContentItem Index="{k}" ObjectRef="{s}"/>' for k, s in enumerate(i_sec)] +
               ["\t\t</SecondaryContents>", f"\t\t<AudioChannelLayout>{layout}</AudioChannelLayout>"])
    L += [_abre("ClipChannelGroupVectorSerializer", i_grupo), "\t\t<ClipChannelVectors Version=\"1\">",
          f'\t\t\t<ClipChannelVectorItem Index="0" ObjectRef="{i_vetor}"/>', "\t\t</ClipChannelVectors>",
          "\t</ClipChannelGroupVectorSerializer>"]

    def fonte(tag, oid):
        return [_abre(tag, oid), "\t\t<MediaSource Version=\"4\">", "\t\t\t<Content Version=\"10\">",
                "\t\t\t</Content>", f'\t\t\t<Media ObjectURef="{uid_media}"/>', "\t\t</MediaSource>",
                f"\t\t<OriginalDuration>{dur_ticks}</OriginalDuration>", f"\t</{tag}>"]

    if video:
        L += fonte("VideoMediaSource", i_vsrc)
    L += fonte("AudioMediaSource", i_asrc)
    for k, s in enumerate(i_sec):
        L += [_abre("SecondaryContent", s), f'\t\t<Content ObjectRef="{i_asrc}"/>', f"\t\t<ChannelIndex>{k}</ChannelIndex>",
              "\t</SecondaryContent>"]
    L += [_abre("ClipChannelVectorSerializer", i_vetor), "\t\t<ClipChannels Version=\"1\">"]
    L += [f'\t\t\t<ClipChannelItem Index="{k}" ObjectRef="{c}"/>' for k, c in enumerate(i_canal)]
    L += ["\t\t</ClipChannels>", f"\t\t<ChannelType>{tipo_canal}</ChannelType>", "\t</ClipChannelVectorSerializer>"]
    L += [_abre("Media", uid_media), f'\t\t<AudioStream ObjectRef="{i_astream}"/>']
    if video:
        L += [f'\t\t<VideoStream ObjectRef="{i_vstream}"/>']
    if inicio_ticks:
        L += [f"\t\t<Start>{inicio_ticks}</Start>"]
    if fita:
        L += [f"\t\t<TapeName>{fita_x}</TapeName>"]
    L += ["\t\t<ImplementationID>00000000-0000-0000-0000-000000000000</ImplementationID>", f"\t\t<Title>{nome_x}</Title>",
          "\t\t<OfflineReason>5</OfflineReason>", "\t</Media>"]
    for k, c in enumerate(i_canal):
        L += [_abre("ClipChannelSerializer", c), "\t\t<SourceClipIndex>0</SourceClipIndex>",
              f"\t\t<mSourceChannelIndex>{k}</mSourceChannelIndex>", "\t</ClipChannelSerializer>"]
    L += [_abre("AudioStream", i_astream), f"\t\t<AudioChannelLayout>{layout}</AudioChannelLayout>",
          f"\t\t<Duration>{dur_ticks}</Duration>", "\t\t<SampleType>3</SampleType>",
          f"\t\t<FrameRate>{TICKS_AUDIO_48K}</FrameRate>", "\t</AudioStream>"]
    if video:
        L += [_abre("VideoStream", i_vstream), f"\t\t<Duration>{dur_ticks}</Duration>",
              "\t\t<CodecType>1061109567</CodecType>", f"\t\t<FrameRect>0,0,{w},{h}</FrameRect>",
              '\t\t<OriginalColorSpace>{"baseColorProfile":{"colorProfileName":"BT.709 RGB Full"},"baseProfileType":1}'
              "</OriginalColorSpace>", "\t\t<OriginalFieldType>-1</OriginalFieldType>",
              f"\t\t<FrameRate>{fps_t}</FrameRate>", "\t</VideoStream>"]
    return "\n" + "\n".join(L), uid_cpi, proximo


def _item_multicanal(nome: str, dur_ticks: int, proximo_id: int, *, fita: str, inicio_ticks: int, video: dict | None,
                     canais: int, fps_video: float | None) -> tuple[str, str, int]:
    """O item offline de N > 2 canais: N canais MONO, cada um com a sua mídia (`StreamNumber`), como o Premiere guarda
    o WAV polifônico importado. O resto (ClipProjectItem, MasterClip com `MZ.offlineclip.*`, ClipLoggingInfo, o vídeo)
    é o do item de 1/2 canais."""
    fps_t = ticks_por_quadro(fps_video or 24000 / 1001)
    nome_x, fita_x = escape(nome), escape(fita)
    mono = '[{"channellabel":0}]'
    uid_cpi, uid_mc = str(uuid.uuid4()), str(uuid.uuid4())
    uid_med = [str(uuid.uuid4()) for _ in range(canais)]
    ids = iter(range(proximo_id, proximo_id + 16 + 9 * canais))
    i_log = next(ids)
    i_chain = [next(ids) for _ in range(canais)]
    i_vclip = next(ids) if video else None
    i_aclip = [next(ids) for _ in range(canais)]
    i_grupo = next(ids)
    i_vsrc = next(ids) if video else None
    i_asrc = [next(ids) for _ in range(canais)]
    i_sec = [next(ids) for _ in range(canais)]
    i_vetor = [next(ids) for _ in range(canais)]
    i_canal = [next(ids) for _ in range(canais)]
    i_astream = [next(ids) for _ in range(canais)]
    i_vstream = next(ids) if video else None
    proximo = next(ids)
    w, h = (video or {}).get("largura", 1920), (video or {}).get("altura", 1080)
    par = (video or {}).get("par") or (1, 1)
    L = [_abre("ClipProjectItem", uid_cpi), "\t\t<ProjectItem Version=\"1\">", "\t\t\t<Node Version=\"1\">",
         "\t\t\t\t<Properties Version=\"1\">", "\t\t\t\t\t<project.icon.view.grid.order>0</project.icon.view.grid.order>"]
    if video:
        L += [f"\t\t\t\t\t<Column.PropertyText.Label>{_ROTULO}</Column.PropertyText.Label>"]
    L += ["\t\t\t\t</Properties>", "\t\t\t</Node>", f"\t\t\t<Name>{nome_x}</Name>", "\t\t</ProjectItem>",
          f'\t\t<MasterClip ObjectURef="{uid_mc}"/>', "\t</ClipProjectItem>"]
    L += [_abre("MasterClip", uid_mc), "\t\t<Node Version=\"1\">", "\t\t\t<Properties Version=\"1\">",
          f"\t\t\t\t<MZ.offlineclip.AudioFrameRate>{TICKS_AUDIO_48K}</MZ.offlineclip.AudioFrameRate>",
          f"\t\t\t\t<MZ.offlineclip.VideoFrameRate>{fps_t}</MZ.offlineclip.VideoFrameRate>",
          f"\t\t\t\t<MZ.offlineclip.VideoFrameRect.Width>{w}</MZ.offlineclip.VideoFrameRect.Width>",
          f"\t\t\t\t<MZ.offlineclip.VideoFrameRect.Height>{h}</MZ.offlineclip.VideoFrameRect.Height>",
          f"\t\t\t\t<MZ.offlineclip.VideoPAR.num>{par[0]}</MZ.offlineclip.VideoPAR.num>",
          f"\t\t\t\t<MZ.offlineclip.VideoPAR.den>{par[1]}</MZ.offlineclip.VideoPAR.den>",
          "\t\t\t</Properties>", "\t\t</Node>", f'\t\t<LoggingInfo ObjectRef="{i_log}"/>',
          "\t\t<AudioComponentChains Version=\"1\">"]
    L += [f'\t\t\t<AudioComponentChain Index="{k}" ObjectRef="{c}"/>' for k, c in enumerate(i_chain)]
    L += ["\t\t</AudioComponentChains>", "\t\t<Clips Version=\"1\">"]
    clips = ([i_vclip] if video else []) + i_aclip
    L += [f'\t\t\t<Clip Index="{k}" ObjectRef="{c}"/>' for k, c in enumerate(clips)]
    L += ["\t\t</Clips>", f'\t\t<AudioClipChannelGroups ObjectRef="{i_grupo}"/>', f"\t\t<Name>{nome_x}</Name>",
          f"\t\t<DefMappingID>{uuid.uuid4()}</DefMappingID>", "\t\t<MasterClipChangeVersion>0</MasterClipChangeVersion>",
          "\t</MasterClip>"]
    L += [_abre("ClipLoggingInfo", i_log)]
    if not video:
        L += ["\t\t<CaptureMode>1</CaptureMode>"]
    if fita:
        L += [f"\t\t<TapeName>{fita_x}</TapeName>"]
    L += [f"\t\t<ClipName>{nome_x}</ClipName>", "\t\t<TimecodeFormat>110</TimecodeFormat>",
          f"\t\t<MediaInPoint>{inicio_ticks}</MediaInPoint>", f"\t\t<MediaOutPoint>{inicio_ticks + dur_ticks}</MediaOutPoint>",
          f"\t\t<MediaFrameRate>{fps_t if video else TICKS_AUDIO_48K}</MediaFrameRate>", "\t</ClipLoggingInfo>"]
    for c in i_chain:
        L += [_abre("AudioComponentChain", c), "\t\t<DefaultVol>true</DefaultVol>",
              "\t\t<DefaultVolumeComponentID>1</DefaultVolumeComponentID>",
              "\t\t<DefaultChannelVolumeComponentID>2</DefaultChannelVolumeComponentID>", "\t\t<ComponentChain Version=\"3\">",
              "\t\t</ComponentChain>", f"\t\t<AudioChannelLayout>{mono}</AudioChannelLayout>",
              "\t\t<ChannelType>0</ChannelType>", "\t</AudioComponentChain>"]

    def clipe(tag, oid, fonte, extra):
        rot = ["\t\t\t<Node Version=\"1\">", "\t\t\t\t<Properties Version=\"1\">",
               f"\t\t\t\t\t<asl.clip.label.name>{_ROTULO}</asl.clip.label.name>",
               "\t\t\t\t\t<asl.clip.label.color>13408882</asl.clip.label.color>", "\t\t\t\t</Properties>",
               "\t\t\t</Node>"] if video else []
        return ([_abre(tag, oid), "\t\t<Clip Version=\"18\">"] + rot +
                [f'\t\t\t<Source ObjectRef="{fonte}"/>', f"\t\t\t<ClipID>{uuid.uuid4()}</ClipID>",
                 "\t\t\t<InUse>false</InUse>", "\t\t</Clip>"] + extra + [f"\t</{tag}>"])

    if video:
        L += clipe("VideoClip", i_vclip, i_vsrc, [])
    for k in range(canais):
        L += clipe("AudioClip", i_aclip[k], i_asrc[k], ["\t\t<SecondaryContents Version=\"1\">",
                   f'\t\t\t<SecondaryContentItem Index="0" ObjectRef="{i_sec[k]}"/>', "\t\t</SecondaryContents>",
                   f"\t\t<AudioChannelLayout>{mono}</AudioChannelLayout>"])
    L += [_abre("ClipChannelGroupVectorSerializer", i_grupo), "\t\t<ClipChannelVectors Version=\"1\">"]
    L += [f'\t\t\t<ClipChannelVectorItem Index="{k}" ObjectRef="{v}"/>' for k, v in enumerate(i_vetor)]
    L += ["\t\t</ClipChannelVectors>", "\t</ClipChannelGroupVectorSerializer>"]

    def fonte(tag, oid, uid):
        return [_abre(tag, oid), "\t\t<MediaSource Version=\"4\">", "\t\t\t<Content Version=\"10\">",
                "\t\t\t</Content>", f'\t\t\t<Media ObjectURef="{uid}"/>', "\t\t</MediaSource>",
                f"\t\t<OriginalDuration>{dur_ticks}</OriginalDuration>", f"\t</{tag}>"]

    if video:
        L += fonte("VideoMediaSource", i_vsrc, uid_med[0])
    for k in range(canais):
        L += fonte("AudioMediaSource", i_asrc[k], uid_med[k])
    for k in range(canais):          # os ObjectID em ordem crescente no arquivo (banco §0.1)
        L += [_abre("SecondaryContent", i_sec[k]), f'\t\t<Content ObjectRef="{i_asrc[k]}"/>',
              "\t\t<ChannelIndex>0</ChannelIndex>", "\t</SecondaryContent>"]
    for k in range(canais):
        L += [_abre("ClipChannelVectorSerializer", i_vetor[k]), "\t\t<ClipChannels Version=\"1\">",
              f'\t\t\t<ClipChannelItem Index="0" ObjectRef="{i_canal[k]}"/>', "\t\t</ClipChannels>",
              "\t\t<ChannelType>0</ChannelType>", "\t</ClipChannelVectorSerializer>"]
    for k in range(canais):
        L += [_abre("Media", uid_med[k]), f'\t\t<AudioStream ObjectRef="{i_astream[k]}"/>']
        if video and k == 0:
            L += [f'\t\t<VideoStream ObjectRef="{i_vstream}"/>']
        if inicio_ticks:
            L += [f"\t\t<Start>{inicio_ticks}</Start>"]
        if fita:
            L += [f"\t\t<TapeName>{fita_x}</TapeName>"]
        L += ["\t\t<ImplementationID>00000000-0000-0000-0000-000000000000</ImplementationID>",
              f"\t\t<Title>{nome_x}</Title>"]
        if k:
            L += [f"\t\t<StreamNumber>{k}</StreamNumber>"]
        L += ["\t\t<OfflineReason>5</OfflineReason>", "\t</Media>"]
    for k, c in enumerate(i_canal):
        L += [_abre("ClipChannelSerializer", c), f"\t\t<SourceClipIndex>{k}</SourceClipIndex>",
              "\t\t<mSourceChannelIndex>0</mSourceChannelIndex>", "\t</ClipChannelSerializer>"]
    for a in i_astream:
        L += [_abre("AudioStream", a), f"\t\t<AudioChannelLayout>{mono}</AudioChannelLayout>",
              f"\t\t<Duration>{dur_ticks}</Duration>", "\t\t<SampleType>3</SampleType>",
              f"\t\t<FrameRate>{TICKS_AUDIO_48K}</FrameRate>", "\t</AudioStream>"]
    if video:
        L += [_abre("VideoStream", i_vstream), f"\t\t<Duration>{dur_ticks}</Duration>",
              "\t\t<CodecType>1061109567</CodecType>", f"\t\t<FrameRect>0,0,{w},{h}</FrameRect>",
              '\t\t<OriginalColorSpace>{"baseColorProfile":{"colorProfileName":"BT.709 RGB Full"},"baseProfileType":1}'
              "</OriginalColorSpace>", "\t\t<OriginalFieldType>-1</OriginalFieldType>",
              f"\t\t<FrameRate>{fps_t}</FrameRate>", "\t</VideoStream>"]
    return "\n" + "\n".join(L), uid_cpi, proximo


def _gravar(xml: str, saida: str) -> None:
    """O gzip com o cabeçalho que o PRÓPRIO Premiere escreve (FLG=0, OS 0x13): com o nome do arquivo no cabeçalho
    (o `gzip` do Python com caminho) ele recusa o projeto (banco `prproj/relink-e-geometria.md` §0)."""
    dados = xml.encode("utf-8")
    c = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    corpo = c.compress(dados) + c.flush()
    with open(saida, "wb") as fh:
        fh.write(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x13" + corpo +
                 struct.pack("<II", zlib.crc32(dados) & 0xFFFFFFFF, len(dados) & 0xFFFFFFFF))


def enxertar(xml: str, itens: list[dict]) -> tuple[str, list[str]]:
    """Os itens offline no XML de um projeto: os objetos no FIM, com `ObjectID` acima do maior e em ordem crescente
    (§0.1), e cada `ClipProjectItem` na bin raiz. `itens`: os argumentos de `item` (com `nome` e `dur_ticks`).
    Devolve (xml, [uid do ClipProjectItem de cada item, na ordem])."""
    proximo = max(int(x) for x in re.findall(r'ObjectID="(\d+)"', xml)) + 1
    blocos, uids = [], []
    for it in itens:
        texto, uid, proximo = item(proximo_id=proximo, **it)
        blocos.append(texto)
        uids.append(uid)
    raiz = re.search(r'<RootProjectItem ObjectUID="[^"]+".*?</RootProjectItem>', xml, re.S)
    if not raiz:
        raise ValueError("o projeto não tem a bin raiz")
    r = raiz.group(0)
    n = len(re.findall(r"<Item Index=", r))
    novos = "".join(f'\t\t\t\t<Item Index="{n + k}" ObjectURef="{u}"/>\n' for k, u in enumerate(uids))
    if "\t\t\t</Items>" in r:
        r2 = r.replace("\t\t\t</Items>", novos + "\t\t\t</Items>", 1)
    elif "\t\t<ProjectItemContainer Version=\"1\">" in r:
        r2 = r.replace("\t\t<ProjectItemContainer Version=\"1\">", "\t\t<ProjectItemContainer Version=\"1\">\n"
                       "\t\t\t<Items Version=\"1\">\n" + novos + "\t\t\t</Items>", 1)
    else:
        raise ValueError("a bin raiz não tem onde pôr os itens")
    xml = xml.replace(r, r2, 1)
    fim = xml.rindex("\n</PremiereData>")
    return xml[:fim] + "".join(blocos) + xml[fim:], uids


def projeto_com_offline(molde_prproj: str, saida: str, itens: list[dict]) -> list[str]:
    """Uma cópia de `molde_prproj` com os itens offline na bin raiz, gravada em `saida`. Devolve os uids."""
    with open(molde_prproj, "rb") as fh:
        xml = gzip.decompress(fh.read()).decode("utf-8")
    xml, uids = enxertar(xml, itens)
    _gravar(xml, saida)
    return uids
