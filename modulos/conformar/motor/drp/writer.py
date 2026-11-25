"""
drp/writer.py — gera um .drt do DaVinci Resolve a partir dos segmentos+matches do app.

TEMPLATELESS: o usuário NÃO fornece template. Usa o esqueleto sanitizado interno
(`drp/skeleton_r19.drt`, gerado por `tools/make_skeleton.py` de um DRT nativo do Resolve
19 — ver `ESQUELETO_PADRAO`) só como CASCA (project.xml, pasta do media pool, estrutura de
tracks) + formas (shapes) de clipe para clonar, e GERA o media pool a partir dos arquivos.

Cobre vídeo e áudio: cortes + relink + timecode + velocidade + transições; clipes offline
(o original está com quem recebe) e clipes desligados no Avid.

Mapeamento Segment → Sm2TiVideoClip (validado contra o DRT de referência):
    Start (frame)    = frames(timeline_tc_in) + 86400   (Resolve começa em 01:00:00:00)
    Duration (frame) = duration_frames
    In (frame)       = round(source_start_frames × speed_ratio)
    Name             = clip_name
    MediaRef         = DbId do clipe gerado no pool (cross-link)
    MediaFilePath    = caminho ABSOLUTO do arquivo casado (relink)
    MediaReelNumber  = stem do arquivo casado
    MediaFrameRate   = blob (ffprobe, por votação r/avg/time_base — B074)
    MediaStartTime   = TC embutido do arquivo (frames; ffprobe)
    MediaTimemapBA   = constante (100%) ou velocidade linear
    FieldsBlob       = forma + patch do varint Start (f1.f1.f21)

Os blobs (FieldsBlob protobuf, MediaFrameRate, MediaTimemapBA) usam os codecs já
validados por round-trip em tools/inspect_drp.py.

Uso programático:
    from drp.writer import build_drt
    build_drt(segments, match_results, output_drt)
"""
from __future__ import annotations

import ntpath
import os
import re
import struct
import subprocess as _sp
import sys
import time
import uuid
import zipfile
from pathlib import Path

from tools.inspect_drp import (fieldsblob_decode, fieldsblob_encode, timemap_encode,
                               build_speed_timemap, build_ramp_timemap,
                               build_adaptive_ramp_timemap, build_effect_filters_ba,
                               framerate_encode, build_reverse_timemap, reverso_y0,
                               build_audio_speed_timemap)
# ⚠️ Os `ffprobe` daqui rodam uma vez por mídia. Sem `CREATE_NO_WINDOW`, o serviço ligado
# pelo script do Resolve (`pythonw`, sem console para herdar) abria uma janela por arquivo:
# ~1200 piscadas roubando o foco ao trazer a PRODA_CORTE (medido 2026-09-25).
from media.fftools import SEM_JANELA

# Modo de tradução da RAMPA de velocidade Avid→Resolve (ver docs/resolve-speed-ramp.md):
#   "adaptive" (default) = poucos keyframes lineares (Douglas-Peucker), frame-exato e editável;
#   "dense"              = N=159 fixo, fidelidade máxima, mais keyframes.
# Definido por build_drt(ramp_mode=...) na hora do export (escolha do usuário no pop-up).
_RAMP_MODE = "adaptive"

# Resolve numera a timeline a partir de 01:00:00:00.
_TIMELINE_OFFSET_FRAMES = 86400  # 3600 s * 24
_NOMINAL_FPS = 24                # contagem de TC nominal (non-drop), como no parser

# Formato de PLAYBACK da timeline (Sm2MpTimelineClip): (FrameRate double-blob, Body protobuf).
# O esqueleto trazia o formato 23.976 → a timeline REPRODUZIA em 24 mesmo mostrando 29 (o
# rótulo FrameRate sozinho não basta; o Body carrega um "format id" em f4/f1.f12 que muda com
# rate E interlace). Blobs colhidos de DRTs NATIVOS do Resolve (1920x1080). Chave:
# (nominal_fps, ntsc_fracionário, interlaced). NTSC = 23.976/29.97; redondo = 24/30.
_TL_FORMATS = {
    (24, True,  False): ("872211b5dcf937400000000000000000",
        "800a2c10011a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f60f6bde8bf4b100120f6bde8bf4b"),
    (24, False, False): ("00000000000038400000000000000000",
        "800a2c10011a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f60b08889ca4b100120b08889ca4b"),
    (30, True,  False): ("286b55e253f83d400000000000000000",
        "800a2c10011a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f60c4ecaba214100120c4ecaba214"),
    (30, True,  True):  ("286b55e253f84d400000000000000000",
        "800a2c10011a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f60d8b3fe9914100120d8b3fe9914"),
}


from drp import sinais as _sn  # noqa: E402 — os Sinais do Import (marcador e cor local)
from media import fftools  # noqa: E402 — binários embarcados (versao-instalada-embarca-tudo)
from media import sonda as _sonda  # noqa: E402 — a leitura única do ffprobe por arquivo
from media.opatom import _video_rate  # noqa: E402 — a taxa por votação, nunca um campo cru (B074)

def _tl_format(fps: float, interlaced: bool = False):
    """(FrameRate-blob, Body-hex) do formato de timeline p/ `fps`/interlace, ou None se não
    catalogado (colhido de DRTs nativos a 1920x1080). NTSC = fps fracionária (23.976/29.97)."""
    nominal = max(1, round(float(fps or 24.0)))
    ntsc = abs(float(fps or 0) - nominal) > 1e-3
    return _TL_FORMATS.get((nominal, ntsc, bool(interlaced)))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _tc_to_frames(tc: str, nominal: int | None = None) -> int:
    """'HH:MM:SS:FF' → frames nominais (non-drop). `nominal` = base de contagem; o default é
    `_NOMINAL_FPS` (a da TIMELINE, p/ posições). Para o TC EMBUTIDO de um ARQUIVO, passe a base
    do ARQUIVO (round(fps_do_arquivo)) — senão um arquivo 23.976 numa TL 29.97 teria o TC lido
    na base 30 e o MediaStartTime sairia deslocado (clipe fora do alcance → congela no Resolve)."""
    n = int(nominal) if nominal else _NOMINAL_FPS
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * n + f


from media.safepath import forma_windows as _forma_windows  # noqa: E402 — a regra é uma só


def _abs(caminho: str) -> str:
    r"""Caminho absoluto da mídia, decidido pela FORMA do caminho, não pelo SO que roda.

    ⚠️ `os.path.abspath(r"F:\CARTAO\x.braw")` no macOS devolve `<cwd>/F:\CARTAO\x.braw`:
    para o POSIX aquilo é um nome relativo. Acontece de verdade — o original OFFLINE está
    no disco do colorista no Windows e o DRT é gerado no Mac (medido 2026-10-01,
    `tests/test_drp_windows.py`; matriz de plataforma, regra 3). Forma Windows (`X:\…` ou
    UNC) é normalizada pelo `ntpath` em qualquer máquina e NUNCA toca o disco.
    """
    if _forma_windows(caminho):
        return ntpath.normpath(caminho)
    return os.path.abspath(caminho)


def _nome(caminho: str) -> str:
    """Nome do arquivo, com o separador da FORMA do caminho (ver `_abs`)."""
    if _forma_windows(caminho):
        return ntpath.basename(caminho)
    return os.path.basename(caminho)


def _pasta(caminho: str) -> str:
    """Pasta do arquivo, com o separador da FORMA do caminho (ver `_abs`)."""
    if _forma_windows(caminho):
        return ntpath.dirname(ntpath.normpath(caminho))
    return os.path.dirname(os.path.abspath(caminho))


def _reel(name: str) -> str:
    """Reel base de um nome de clipe/arquivo (sem extensão)."""
    return Path(_nome(name)).stem if name else name


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _xml_field(block: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.DOTALL)
    return m.group(1) if m else None


def ler_in(texto: str | None) -> float:
    """O `<In>` de um clipe do DRT: inteiro (`291`), decimal, ou o formato do Resolve com FRAÇÃO (`291|<f64 LE hex>`:
    a fonte de outra taxa; o nosso writer também o grava desde 2026-11-23). Vazio = 0."""
    texto = (texto or "").strip()
    if not texto:
        return 0.0
    inteiro, _, fr = texto.partition("|")
    valor = float(inteiro)
    if fr:
        valor += struct.unpack("<d", bytes.fromhex(fr.strip()))[0]
    return valor


def _set_field(block: str, tag: str, value: str) -> str:
    """Substitui o conteúdo de <tag>…</tag> (ou expande <tag/>).

    ⚠️⚠️ A substituição vai por `lambda`, NUNCA como string: o `re` interpreta `\\` na
    string de substituição, e um caminho do Windows (`D:\\MIDIAS\\x.mov`) estourava
    `re.error: bad escape \\M` — o writer nasceu no macOS e nunca tinha visto uma barra
    invertida. Medido em 2026-09-24, primeiro DRT gerado no Windows.
    """
    novo = f"<{tag}>{value}</{tag}>"
    if re.search(rf"<{tag}>.*?</{tag}>", block, re.DOTALL):
        return re.sub(rf"<{tag}>.*?</{tag}>", lambda _m: novo, block,
                      count=1, flags=re.DOTALL)
    if re.search(rf"<{tag}/>", block):
        return re.sub(rf"<{tag}/>", lambda _m: novo, block, count=1)
    return block


_META_CACHE: dict[str, tuple] = {}
#: Arquivos cuja sondagem ESTOUROU O TEMPO (disco frio e disputado): não vão para o cache — lento
#: não é ilegível. ⛔ Medido 2026-10-04 (PRODB frio, 8 simultâneas): 5 ARRIRAW passaram de 60 s
#: e eram tratados como ilegíveis. `_sondar_em_paralelo` os refaz em série.
_SONDA_LENTA: set[str] = set()
#: Taxa da TIMELINE da geração em curso (ver `_build_drt`).
_TL_FPS: float = 24.0
#: Caminhos OFFLINE da geração em curso (ver `build_drt(offline=…)`): nunca tocados no disco.
_META_CACHE_OFFLINE: set[str] = set()


def _media_meta(media_path: str) -> tuple:
    """(nb_frames, fps, tc_str) do arquivo via ffprobe (cacheado). tc_str = TC embutido
    'HH:MM:SS:FF' ou None. nb_frames cai p/ duração×fps se nb_frames vier ausente."""
    if media_path in _META_CACHE:
        return _META_CACHE[media_path]
    nb = fps = tc = None
    try:
        j = _sonda.ler(media_path)             # a leitura única (`media/sonda.py`)
        st = _sonda.primeiro(j, "video")       # o `-select_streams v:0` de antes
        # a taxa por VOTAÇÃO (B074): o `r_frame_rate` do MXF de vídeo do Avid é a METADE (11,988 em 23,976)
        num, den = _video_rate(st)
        fps = num / den if num and den else None
        if st.get("nb_frames") and str(st["nb_frames"]).isdigit():
            nb = int(st["nb_frames"])
        elif fps and st.get("duration"):
            try:
                nb = int(round(float(st["duration"]) * fps))
            except Exception:
                pass
        tc = (st.get("tags", {}) or {}).get("timecode") \
            or ((j.get("format", {}).get("tags", {}) or {}).get("timecode"))
        if not tc and not st:
            # ⚠️ Arquivo SÓ de áudio (a `.mxf` mono de um canal gerenciado do Avid): o TC mora
            # nas tags do STREAM DE ÁUDIO — nem no formato, nem num stream de vídeo que não
            # existe. Sem isto o TC saía vazio e o clipe caía em 00:00:00:00 (medido
            # 2026-09-24, `…_A01.mxf` com `11:42:00:00`).
            tc = (_sonda.primeiro(j, "audio").get("tags", {}) or {}).get("timecode")
        if not tc and st:
            # ⛔ Vídeo SEM timecode (o .MOV do drone DJI): o Resolve o conta de 00:00:00:00. Sem
            # isto o item herdava o TC da forma (03:44:58:12) e o clipe o da timeline-modelo, e
            # a timeline pedia um trecho que "não existe" → Media Offline (medido 2026-09-26).
            tc = "00:00:00:00"
    except _sp.TimeoutExpired:
        _SONDA_LENTA.add(media_path)
        return (None, None, None)          # LENTO não é ilegível: sem cache (`_SONDA_LENTA`)
    except Exception:
        pass
    _META_CACHE[media_path] = (nb, fps, tc)
    return _META_CACHE[media_path]


def _inicio_da_rampa(seg: dict) -> float:
    """Onde o plano começa na mídia, em quadros da fonte: o in do clipe + a 1ª posição do mapa da rampa."""
    off = _curva_de_posicao(seg) or seg.get("source_offset_map") or []
    v0 = float(min(off)[1]) if off else 0.0
    return int(seg.get("source_start_frames") or 0) + v0


def _curva_de_posicao(seg: dict | None) -> list | None:
    """O mapa (tempo do plano, posição na fonte) quando a velocidade é uma CURVA: a rampa — ou o CONGELADO, que é o
    mapa ACHATADO (o mesmo quadro do começo ao fim). ⛔ Antes (até 2026-10-28) o congelado não tinha caminho no writer:
    a `speed_ratio` 0 virava 1,0 e o plano ANDAVA a 100 % no Resolve (banco, B066). O achatado vai pela curva da rampa,
    medida quadro a quadro (laboratório B22, 48/48). O mapa do leitor é forçado plano no 1º valor: no clipe de 1
    quadro o leitor de bin monta (0, 0) → (n, n / velocidade), que não é congelado."""
    if not seg:
        return None
    tipo = seg.get("motion_effect_type")
    if tipo == "ramp":
        return seg.get("source_offset_map") or None
    if tipo == "freeze":
        dur = float(seg.get("duration_frames") or 0)
        off = seg.get("source_offset_map") or []
        v0 = float(off[0][1]) if off else 0.0
        return [(0.0, v0), (dur, v0)] if dur > 0 else None
    return None


def _media_timemap(media_path: str, speed_ratio: float, seg: dict | None = None,
                   tl_fps: float | None = None, entrada: int = 0) -> str | None:
    """MediaTimemapBA do clipe: constante (100%), velocidade linear, ou RAMPA (curva).

    Se `seg` tem motion_effect_type='ramp' + source_offset_map, emite a curva real
    (keyframes lineares densos via build_ramp_timemap). Senão, constante/linear.
    """
    nb, fps, _ = _media_meta(media_path)
    if nb is None or not fps:
        return None
    curva = _curva_de_posicao(seg)
    if curva:
        # só os quadros INTEIROS do plano (o mapa do Avid vem de meio em meio quadro): é no quadro que o Resolve
        # amostra — antes do deslocamento da entrada, que pode ser fracionário (fonte de outra taxa)
        off = [(t, v) for t, v in curva if abs(float(t) - round(float(t))) < 1e-9]             or curva
        ss = int(seg.get("source_start_frames") or 0)
        f = float(tl_fps or fps)
        if entrada:
            # a entrada a 100 % (0, 0) → (entrada, ss): a rampa do Premiere vem com o eixo do plano
            off = [(0, -ss)] + [(entrada + k, v) for k, v in off]
        if _RAMP_MODE == "dense":
            # Denso fixo (N=159): fidelidade máxima, header validado, porém muitos keyframes.
            return build_ramp_timemap(nb, fps, off, ss, f)
        # Linear ADAPTATIVO (default): keyframes mínimos (Douglas-Peucker), frame-exato e editável.
        # interp0 é honrado ao frame pelo Resolve; encaixa num header QHash conhecido.
        return build_adaptive_ramp_timemap(nb, fps, off, ss, f, so_inteiros=False)
    if abs(speed_ratio - 1.0) < 1e-3:
        return timemap_encode({"kind": "const", "tag": 0x02, "value": (nb - 1) / fps})
    return build_speed_timemap(nb, fps, speed_ratio)


def _regen_time_blob(hexstr: str, tc_str: str | None, nb_frames: int | None) -> str:
    """Patcha o blob `<Time>` (BA) do pool clip com Timecode (Start TC) e NumFrames
    (Duration) do arquivo casado. TC é sempre 'HH:MM:SS:FF' (22B UTF-16BE) e NumFrames
    é i32 → patch byte-a-byte, sem re-encode. Conserta Start TC + Duration + End TC."""
    raw = bytearray.fromhex(hexstr)

    def _vpos(key: str):
        kb = key.encode("utf-16-be")
        i = raw.find(kb)
        return (i + len(kb)) if i >= 0 else None

    if tc_str:
        p = _vpos("Timecode")
        if p is not None and int.from_bytes(raw[p:p + 4], "big") == 10:
            ln = int.from_bytes(raw[p + 5:p + 9], "big")
            new = tc_str.encode("utf-16-be")
            if len(new) == ln:
                raw[p + 9:p + 9 + ln] = new
    if nb_frames:
        p = _vpos("NumFrames")
        if p is not None and int.from_bytes(raw[p:p + 4], "big") == 2:
            raw[p + 5:p + 9] = int(nb_frames).to_bytes(4, "big")
    return bytes(raw).hex()


def _patch_fieldsblob_start(fb_hex: str, start: int) -> str:
    """Reescreve o varint Start (f1 → f1 → f21) do FieldsBlob protobuf do clipe."""
    dec = fieldsblob_decode(fb_hex)
    for f1 in dec["fields"]:
        if f1["field"] == 1 and f1["wire"] == 2 and isinstance(f1["value"], list):
            for f1b in f1["value"]:
                if f1b["field"] == 1 and isinstance(f1b["value"], list):
                    for f in f1b["value"]:
                        if f["field"] == 21 and f["wire"] == 0:
                            f["value"] = start
    return fieldsblob_encode(dec)


# Sm2TiTransition (Cross Dissolve) — colhido de DRT NATIVO do Resolve. O esqueleto não tem
# transição; clonamos este molde, setamos DbId/Start/Duration/AlignmentType e patchamos o
# Start no FieldsBlob (f1.f21). EffectFiltersBA = parâmetros padrão do cross-dissolve.
_TRANSITION_TEMPLATE = (
    '<Sm2TiTransition DbId="{dbid}">'
    '<FieldsBlob>{fieldsblob}</FieldsBlob>'
    '<PrettyType>{prettytype}</PrettyType>'
    '<Name>Transition</Name>'
    '<Start>{start}</Start>'
    '<Duration>{duration}</Duration>'
    '<LinkedItemSync/>'
    '<WasDisbanded>false</WasDisbanded>'
    '<MarkersBA/>'
    '<UiMemento>0</UiMemento>'
    '<Flags>0</Flags>'
    '<PriorityIndex>0</PriorityIndex>'
    '{effectfilters}'
    '<ImportExportMetadataBA/>'
    '<RenderTextEnabled>true</RenderTextEnabled>'
    '<RenderTextGanged>true</RenderTextGanged>'
    '<RenderTextPrefixed>true</RenderTextPrefixed>'
    '<AlignmentType>{align}</AlignmentType>'
    '<Position>{pos}</Position>'
    '</Sm2TiTransition>'
)
# FieldsBlob base (Start=5651) do molde — o Start é patchado por transição.
_TRANSITION_FB_BASE = ("0000000200000024800a0d1a07080410a689c857a801932c12120000002c"
                       "789c636660642016000000da0005")


def _patch_transition_start(fb_hex: str, start: int) -> str:
    """Reescreve o Start (f1 → f21) do FieldsBlob da transição."""
    dec = fieldsblob_decode(fb_hex)
    for f1 in dec["fields"]:
        if f1["field"] == 1 and f1["wire"] == 2 and isinstance(f1["value"], list):
            for f in f1["value"]:
                if f["field"] == 21 and f["wire"] == 0:
                    f["value"] = start
    return fieldsblob_encode(dec)


# EffectFiltersBA do cross-dissolve de VÍDEO (parâmetros padrão, colhido do DRT nativo).
# O áudio (Cross Fade 0DB) NÃO traz esse blob — o elemento sai self-closing (igual ao nativo).
_DISSOLVE_EFFECT_FILTERS = (
    "<EffectFiltersBA>000000020000003a800a37081238024a004a004a004a004a29088b015224ffffffe0"
    "0000000000000c000000000000000000d800000000000c00000000000000f03f</EffectFiltersBA>")


def _make_transition(start: int, duration: int, align: int = 2, kind: str = "video") -> str:
    """Item Sm2TiTransition p/ a timeline. `start` = frame absoluto na timeline (já com offset
    01:00:00:00); `align` 2=centrado/1=começa no corte/3=termina. `kind`: 'video' = Cross
    Dissolve (com EffectFiltersBA do dissolve); 'audio' = Cross Fade 0DB (sem EffectFiltersBA) —
    é o que o Resolve escreve nativamente para transições em track de áudio (cross-fade E fade)."""
    audio = kind == "audio"
    return _TRANSITION_TEMPLATE.format(
        dbid=_new_id(),
        fieldsblob=_patch_transition_start(_TRANSITION_FB_BASE, int(start)),
        prettytype="Cross Fade 0DB" if audio else "Cross Dissolve",
        effectfilters="<EffectFiltersBA/>" if audio else _DISSOLVE_EFFECT_FILTERS,
        start=int(start), duration=int(duration), align=int(align), pos=int(align),
    )


#: ⭐ O esqueleto decide a VERSÃO do DRT gerado. Medido em 2026-09-24: sobre o esqueleto do
#: Resolve 20.3 (`DbPrjVer="15"`) o DRT é RECUSADO pelo Resolve 19 ("feito numa versão mais
#: nova"). O padrão é o da versão MAIS ANTIGA que se atende — as novas abrem as antigas.
#: Gerado de um DRT nativo por `tools/make_skeleton.py` (banco, `protocolos/drt-drp`).
ESQUELETO_PADRAO = "skeleton_r19.drt"


def _skeleton_path() -> str:
    """Caminho do esqueleto bundled. Dev: ao lado deste módulo; PyInstaller: _MEIPASS."""
    here = Path(__file__).resolve().parent / ESQUELETO_PADRAO
    if here.exists():
        return str(here)
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cand = Path(base) / "drp" / ESQUELETO_PADRAO
        if cand.exists():
            return str(cand)
    return str(here)


def _new_id() -> str:
    return str(uuid.uuid4())


_UUID_RE = re.compile(r'DbId="([0-9a-fA-F-]{36})"')


def _regen_zstd_blob(hexstr: str, remap: dict[str, str]) -> str:
    """Reescreve um FieldsBlob zstd (flag 0x81) remapeando UUIDs internos (UTF-16BE).
    UUIDs têm 36 chars fixos → replace byte-a-byte preserva tamanhos; só re-comprime."""
    try:
        import zstandard
    except Exception:
        return hexstr
    raw = bytes.fromhex(hexstr)
    if len(raw) < 13 or raw[9:13].hex() != "28b52ffd":   # não é zstd
        return hexstr
    ver, flag, z = raw[0:4], raw[8:9], raw[9:]
    try:
        dec = zstandard.ZstdDecompressor().decompress(z)
    except Exception:
        return hexstr
    for old, new in remap.items():
        dec = dec.replace(old.encode("utf-16-be"), new.encode("utf-16-be"))
    comp = zstandard.ZstdCompressor().compress(dec)
    payload = flag + comp
    return (ver + len(payload).to_bytes(4, "big") + payload).hex()


def _regen_clip_blob(hexstr: str, abspath: str) -> str:
    """Reescreve um blob `<Clip>` (zstd→protobuf) do pool clip com a identidade do
    arquivo CASADO: f1=diretório, f2/f6=nome, f3/f13=mtime, f7=novo uuid. É AQUI que
    mora o caminho/nome real da mídia (o Resolve liga por isto) — sem trocar, todos os
    pool clips herdam o arquivo da forma do esqueleto (ex.: A001_03170256_C002.mp4)."""
    try:
        import zstandard
        from tools.inspect_drp import pb_decode, pb_encode
    except Exception:
        return hexstr
    raw = bytes.fromhex(hexstr)
    if len(raw) < 13 or raw[9:13].hex() != "28b52ffd":
        return hexstr
    ver, flag = raw[0:4], raw[8:9]
    try:
        d = zstandard.ZstdDecompressor().decompress(raw[9:])
        fields = pb_decode(d)
    except Exception:
        return hexstr
    dirp = _pasta(abspath).encode("utf-8")
    name = _nome(abspath).encode("utf-8")
    mstr = mus = None
    try:
        # ⛔ Arquivo OFFLINE não existe aqui — e o caminho pode ser de rede (UNC, vindo das
        # colunas do Avid): um stat nele abriria sessão SMB. Não se toca o disco.
        if _abs(abspath) in _META_CACHE_OFFLINE:
            raise OSError("offline")
        mt = os.path.getmtime(abspath)
        mstr = time.ctime(mt).encode("utf-8")
        mus = int(mt) * 1_000_000
    except Exception:
        pass
    for f in fields:
        if f["wire"] == 2 and f["field"] == 1:
            f["value"] = dirp
        elif f["wire"] == 2 and f["field"] in (2, 6):
            f["value"] = name
        elif f["wire"] == 2 and f["field"] == 7:
            f["value"] = _new_id().encode("utf-8")
        elif f["wire"] == 2 and f["field"] == 3 and mstr:
            f["value"] = mstr
        elif f["wire"] == 0 and f["field"] == 13 and mus:
            f["value"] = mus
    try:
        comp = zstandard.ZstdCompressor().compress(pb_encode(fields))
    except Exception:
        return hexstr
    payload = flag + comp
    return (ver + len(payload).to_bytes(4, "big") + payload).hex()


def _uniquify(block: str, top_db_id: str | None = None) -> str:
    """Dá IDENTIDADE ÚNICA a um clipe clonado: remapeia TODOS os DbId aninhados p/
    novos UUIDs (e as referências dentro do FieldsBlob zstd), evitando que o Resolve
    conforme/dedup todos os clipes à mídia da forma (ex.: o A001 do esqueleto). Se
    `top_db_id` for dado, o 1º DbId (o do próprio clipe) recebe esse valor — usado
    para casar com o `MediaRef` do clipe da timeline (cross-link pool↔timeline)."""
    ids = []
    for m in _UUID_RE.finditer(block):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    if not ids:
        return block
    remap = {old: _new_id() for old in ids}
    if top_db_id is not None:
        remap[ids[0]] = top_db_id
    block = _UUID_RE.sub(lambda m: f'DbId="{remap.get(m.group(1), m.group(1))}"', block)
    block = re.sub(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>",
                   lambda m: "<FieldsBlob>" + _regen_zstd_blob(m.group(1), remap) + "</FieldsBlob>",
                   block)
    return block


# --------------------------------------------------------------------------- #
# Geração de clipes (pool + timeline) a partir dos arquivos casados
# --------------------------------------------------------------------------- #
def _make_pool_clip(shape: str, name: str, db_id: str, uniq_id: str, matched_path: str) -> str:
    """Clona a forma de Sm2MpVideoClip dando identidade ÚNICA (DbIds aninhados +
    refs no FieldsBlob remapeados) e reescrevendo os blobs `<Clip>` com o CAMINHO/NOME
    do arquivo casado → o Resolve liga cada pool clip ao SEU arquivo (não à forma).
    Top DbId = db_id (casa o MediaRef da timeline); novo UniqueMediaPoolItemId + Name."""
    b = _uniquify(shape, top_db_id=db_id)
    b = re.sub(r"<Clip>([0-9a-fA-F]{40,})</Clip>",
               lambda m: "<Clip>" + _regen_clip_blob(m.group(1), matched_path) + "</Clip>", b)
    # Start TC + Duration (End = Start+Dur) do arquivo casado → blob <Time>
    nb, fps, tc = _media_meta(matched_path)
    b = re.sub(r"<Time>([0-9a-fA-F]{20,})</Time>",
               lambda m: "<Time>" + _regen_time_blob(m.group(1), tc, nb) + "</Time>", b)
    # ⛔ A forma da MXF gerenciada veio de uma mídia a 23,976 e declarava essa taxa para TODA MXF: a
    # gerenciada de um projeto 24 do Avid ficava "could not be decoded" no render (laboratório A01,
    # 2026-10-11, Resolve 19 Windows). A taxa do item é a do ARQUIVO (o não-MXF já fazia isso em
    # `_ajustar_formato_nativo`).
    if fps and _e_mxf(matched_path) and not _e_arriraw(matched_path):
        b = re.sub(r"<Time>([0-9a-fA-F]+)</Time>",
                   lambda t: "<Time>" + _patch_time_fps(t.group(1), fps) + "</Time>", b)
    b = _set_field(b, "Name", _xml_escape(name))
    b = _set_field(b, "UniqueMediaPoolItemId", uniq_id)
    if _e_still(matched_path):
        meta = _formato_meta(matched_path)
        if meta.get("w"):
            b = re.sub(r"<Geometry>([0-9a-fA-F]+)</Geometry>",
                       lambda g: "<Geometry>" + _patch_geometry(g.group(1), meta["w"], meta["h"])
                       + "</Geometry>", b)
        for tag in ("Time", "Geometry", "Proxy", "VideoMetadata"):
            b = re.sub(rf"<{tag}>([0-9a-fA-F]+)</{tag}>",
                       lambda m, t=tag: f"<{t}>" + _novos_unique_ids(m.group(1)) + f"</{t}>", b)
    elif not _e_mxf(matched_path) or _e_arriraw(matched_path):
        b = _ajustar_formato_nativo(b, matched_path)
    return b


# --------------------------------------------------------------------------- #
# Formato do arquivo no pool: a forma do esqueleto é MXF; o resto usa a NATIVA
# --------------------------------------------------------------------------- #
# ⛔ Medido em 2026-09-26 (relink aos originais, ADR 0020; banco `drt-drp/estruturas.md`
# §"FORMATO do arquivo"): o Resolve escolhe o DECODIFICADOR pelo que o item do pool declara,
# não pelo arquivo. A forma do esqueleto veio de uma MXF gerenciada do Avid, e todo item
# clonado dela dizia "MXF OP-Atom" (campo 15 = 4 do blob `<Clip>`), `dnxhd_lb`, 2048×1080 e
# duas trilhas PCM com metadado MXF. Com a gerenciada isso é verdade; com um .mp4 original o
# log do Resolve dá "can not decode file … of type MXF OP-Atom" e o clipe fica Media Offline.
# Os mp4 de 2048×1080 abriam e os de 1920×1080 não — foi o que despistou.
#
# Gabarito: DRT exportado pelo Resolve Studio 19.0.0b com os mesmos arquivos
# (`formas_r19.xml`). Campo 15 do `<Clip>`: 4 = MXF OP-Atom, 2 = os demais (mp4 e WAV).
# Campo 18: 16388 MXF, 16384 item de vídeo, 32768 item de áudio puro. Campo 5 = codec
# (`avc1`, `AAC`, `Linear PCM`, `dnxhd_lb`).
#
# ⛔ BRAW (2º gabarito, 2026-09-26): com a forma do mp4 o Resolve abria o .braw mas recusava os
# quadros ("Requested position is outside of track bound"). O Resolve grava o BRAW com codec
# `BRAW` (não o fourcc `brst`), flag 16406, áudio PCM, a resolução ÚTIL do `crop_size` do
# arquivo (4096×2160; o ffprobe dá a gravada, 4128×2176) e um `Radiometry` com os metadados
# RAW da câmera. Por isso cada família tem a SUA forma, e a forma manda no formato e na flag.
FORMATO_MXF, FORMATO_OUTRO = 4, 2
FLAG_VIDEO, FLAG_AUDIO = 16384, 32768
FORMAS_NATIVAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "formas_r19.xml")
#: ARRIRAW (MXF OP1a): gabarito do Resolve 21.1 (2026-10-02, PRODB). Ver `_e_arriraw`.
FORMA_ARRIRAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "formas_r21_arriraw.xml")
#: Imagem parada (PNG/JPG/TIFF…): gabarito do Resolve 21.1 (2026-10-02). Ver `_e_still`.
FORMA_STILL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "formas_r21_still.xml")
_EXT_STILL = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".psd", ".tga"}
_FORMAS_NATIVAS: dict[str, str] = {}
_FORMATO_CACHE: dict[str, dict] = {}
#: codec de áudio do ffprobe → nome que o Resolve grava no campo 5 (medido no gabarito).
_CODEC_AUDIO = {"aac": b"AAC"}


def _arquivo_de_video(caminho: str) -> bool:
    """O arquivo tem trilha de VÍDEO (um .mp4/.mov/.mxf de câmera, de música com capa, de efeito
    sonoro exportado como vídeo) — não um WAV/AIF/MP3/M4A."""
    if os.path.splitext(caminho or "")[1].lower() not in (".mp4", ".mov", ".m4v", ".mxf"):
        return False
    return bool(_formato_meta(caminho).get("w")) or _e_arriraw(caminho)


def _e_mxf(caminho: str) -> bool:
    return os.path.splitext(caminho or "")[1].lower() == ".mxf"


def _formas_nativas() -> dict[str, str]:
    """`{"video": …, "braw": …, "audio": …}` — as formas nativas do Resolve 19, por família:
    QuickTime/mp4 com áudio embutido, Blackmagic RAW e áudio puro (WAV/AIF: uma trilha com
    os N canais, montada por `_mapa_de_canais`). A MXF gerenciada fica na do esqueleto."""
    if not _FORMAS_NATIVAS:
        with open(FORMAS_NATIVAS, encoding="utf-8") as f:
            x = f.read()
        for b in re.findall(r"<Sm2MpVideoClip\b.*?</Sm2MpVideoClip>", x, re.DOTALL):
            nome = re.search(r"<Name>([^<]*)</Name>", b).group(1)
            _FORMAS_NATIVAS["braw" if nome.lower().endswith(".braw") else "video"] = b
        _FORMAS_NATIVAS["audio"] = re.search(r"<Sm2MpAudioClip\b.*?</Sm2MpAudioClip>",
                                             x, re.DOTALL).group(0)
        with open(FORMA_ARRIRAW, encoding="utf-8") as f:
            _FORMAS_NATIVAS["arriraw"] = re.search(r"<Sm2MpVideoClip\b.*?</Sm2MpVideoClip>",
                                                   f.read(), re.DOTALL).group(0)
        with open(FORMA_STILL, encoding="utf-8") as f:
            x = f.read()
        _FORMAS_NATIVAS["still"] = re.search(r"<Sm2MpVideoClip\b.*?</Sm2MpVideoClip>",
                                             x, re.DOTALL).group(0)
        _FORMAS_NATIVAS["timemap_still"] = re.search(r"<TimemapStill>([0-9a-f]+)<", x).group(1)
    return _FORMAS_NATIVAS


def _familia(caminho: str) -> str:
    """Qual forma nativa serve a este arquivo de vídeo (não-MXF, ou MXF ARRIRAW)."""
    if _e_still(caminho):
        return "still"
    if _e_arriraw(caminho):
        return "arriraw"
    return "braw" if os.path.splitext(caminho or "")[1].lower() == ".braw" else "video"


_ARRIRAW_CACHE: dict[str, tuple[int, int] | None] = {}
#: Operational Pattern OP1a no cabeçalho MXF (o gerenciado do Avid é OP-Atom: `…0d01020101 10…`).
#: SMPTE 378: `06 0e 2b 34 04 01 01 vv 0d 01 02 01 01 01 qq 00` — `vv` = versão do registro e `qq` =
#: os qualificadores (a ALEXA Mini do PRODB grava 0x09). Antes só o 0x09 valia, e um ARRIRAW de
#: outra câmera ou firmware com outro qualificador passava como vídeo comum (revisão, 2026-10-03).
_UL_OP1A = re.compile(rb"\x06\x0e\x2b\x34\x04\x01\x01[\x01-\x0f]\x0d\x01\x02\x01\x01\x01[\x00-\xff]\x00")


def _raster_arriraw(caminho: str) -> tuple[int, int] | None:
    """(largura, altura) de um MXF ARRIRAW, ou None se não for. Três marcas juntas (banco,
    `protocolos/mxf/codecs-proprietarios.md`, 2026-10-02): OP1a, "ARRI" na identificação e
    raster lido dos local tags do descritor (StoredWidth 3203 / StoredHeight 3202) — o ffprobe
    dá 0×0 no ARRIRAW. Um MXF ProRes de câmera ARRI tem as duas primeiras e é decodificado
    pelo ffprobe: esse fica fora (`_formato_meta` com largura)."""
    if caminho in _ARRIRAW_CACHE:
        return _ARRIRAW_CACHE[caminho]
    r = None
    if _e_mxf(caminho) and _abs(caminho) not in _META_CACHE_OFFLINE:
        try:
            import struct
            with open(caminho, "rb") as f:
                cab = f.read(200_000)
            if _UL_OP1A.search(cab) and b"ARRI" in cab and not _formato_meta(caminho).get("w"):
                w = cab.find(bytes.fromhex("32030004"))
                h = cab.find(bytes.fromhex("32020004"))
                if w >= 0 and h >= 0:
                    r = (struct.unpack(">I", cab[w + 4:w + 8])[0],
                         struct.unpack(">I", cab[h + 4:h + 8])[0])
            if caminho in _SONDA_LENTA:
                return None              # o formato não veio (lento): decidir depois, sem cache
        except OSError:
            # disco desmontado, rede caída: NÃO guardar — um "não é ARRIRAW" no cache do serviço,
            # que fica no ar dias, valeria até reiniciar (revisão de código, 2026-10-03)
            return None
    _ARRIRAW_CACHE[caminho] = r
    return r


def _e_still(caminho: str) -> bool:
    return os.path.splitext(caminho or "")[1].lower() in _EXT_STILL


def _e_arriraw(caminho: str) -> bool:
    return _raster_arriraw(caminho) is not None


def _braw_crop(caminho: str) -> tuple[int, int] | None:
    """A resolução ÚTIL de um .braw: a chave `crop_size` (2 × float32 BE) dos metadados
    QuickTime (`moov/meta`, chaves `mdta`). É a que o Resolve grava no `<Geometry>`."""
    import struct
    try:
        with open(caminho, "rb") as f:
            tam = os.fstat(f.fileno()).st_size

            def filhos(ini, fim):
                while ini < fim - 8:
                    f.seek(ini)
                    sz, tipo = struct.unpack(">I4s", f.read(8))
                    cab = 8
                    if sz == 1:
                        sz, cab = struct.unpack(">Q", f.read(8))[0], 16
                    if sz < cab:
                        return
                    yield tipo, ini + cab, ini + sz
                    ini += sz

            moov = next((a, b) for t, a, b in filhos(0, tam) if t == b"moov")
            meta = next((a, b) for t, a, b in filhos(*moov) if t == b"meta")
            chaves: list[str] = []
            for t, a, b in filhos(meta[0], meta[1]):
                if t == b"keys":
                    f.seek(a + 4)
                    n = struct.unpack(">I", f.read(4))[0]
                    o = a + 8
                    for _ in range(min(n, 500)):
                        f.seek(o)
                        ks = struct.unpack(">I", f.read(4))[0]
                        f.read(4)
                        chaves.append(f.read(max(0, ks - 8)).decode("utf-8", "replace"))
                        o += ks
                elif t == b"ilst":
                    for it, ia, ib in filhos(a, b):
                        idx = struct.unpack(">I", it)[0]
                        if not 0 < idx <= len(chaves) or chaves[idx - 1] != "crop_size":
                            continue
                        for dt, da, _db in filhos(ia, ib):
                            if dt == b"data":
                                f.seek(da + 8)
                                w, h = struct.unpack(">ff", f.read(8))
                                return (int(w), int(h)) if w > 0 and h > 0 else None
    except Exception:
        return None
    return None


def _formato_meta(caminho: str) -> dict:
    """`{vtag, w, h, acodec}` do arquivo pelo ffprobe (cacheado). Vazio se offline ou falhar:
    aí fica o que a forma declara (o Resolve religa depois)."""
    if caminho in _FORMATO_CACHE:
        return _FORMATO_CACHE[caminho]
    meta: dict = {}
    if _abs(caminho) not in _META_CACHE_OFFLINE:
        try:
            for st in _sonda.ler(caminho).get("streams") or []:
                if st.get("codec_type") == "video" and "w" not in meta:
                    tag = str(st.get("codec_tag_string") or "")
                    if re.fullmatch(r"[A-Za-z0-9]{4}", tag):
                        meta["vtag"] = tag.encode("ascii")
                    if st.get("width") and st.get("height"):
                        meta["w"], meta["h"] = int(st["width"]), int(st["height"])
                elif st.get("codec_type") == "audio" and "acodec" not in meta:
                    nome = str(st.get("codec_name") or "")
                    meta["acodec"] = (b"Linear PCM" if nome.startswith("pcm_")
                                      else _CODEC_AUDIO.get(nome))
                    # `BitDepth` do Resolve (medido no banco do projeto, 2026-09-26):
                    # 16 bits → 1, 24 → 2, 32 float → 3.
                    bits = {"16": 1, "24": 2, "32": 3}.get(re.sub(r"\D", "", nome[5:8]))
                    if bits:
                        meta["abits"] = bits
        except _sp.TimeoutExpired:
            _SONDA_LENTA.add(caminho)
            return {}                      # LENTO não é ilegível: sem cache (`_SONDA_LENTA`)
        except Exception:
            meta = {}
    _FORMATO_CACHE[caminho] = meta
    return meta


def _patch_formato_clip(hexstr: str, formato: int | None, flag: int | None,
                        codec: bytes | None) -> str:
    """Campo 15 (formato), 18 (flag) e 5 (codec) de um blob `<Clip>` (zstd→protobuf).
    `None` deixa o valor da forma."""
    try:
        import zstandard
        from tools.inspect_drp import pb_decode, pb_encode
    except Exception:
        return hexstr
    raw = bytes.fromhex(hexstr)
    if len(raw) < 13 or raw[9:13].hex() != "28b52ffd":
        return hexstr
    ver, fl = raw[0:4], raw[8:9]
    try:
        campos = pb_decode(zstandard.ZstdDecompressor().decompress(raw[9:]))
    except Exception:
        return hexstr
    for f in campos:
        if f["field"] == 15 and f["wire"] == 0 and formato is not None:
            f["value"] = formato
        elif f["field"] == 18 and f["wire"] == 0 and flag is not None:
            f["value"] = flag
        elif f["field"] == 5 and f["wire"] == 2 and codec:
            f["value"] = codec   # bytes: o pb_decode pode ter lido `avc1` como submensagem
    comp = zstandard.ZstdCompressor().compress(pb_encode(campos))
    payload = fl + comp
    return (ver + len(payload).to_bytes(4, "big") + payload).hex()


_UUID16 = re.compile(rb"(?:\x00[0-9a-f]){8}\x00-(?:(?:\x00[0-9a-f]){4}\x00-){3}(?:\x00[0-9a-f]){12}")


def _novos_unique_ids(hexstr: str) -> str:
    """Troca os `UniqueId` (uuid em UTF-16BE, mesmo tamanho) de um blob QVariant cru.

    O `_uniquify` só remapeia os `DbId` e o `FieldsBlob`: os `UniqueId` de `<Time>`,
    `<Geometry>`, `<Proxy>`, `<VideoMetadata>` e `<TracksBA>` saíam IGUAIS em todo item
    clonado da mesma forma."""
    raw = bytes.fromhex(hexstr)
    novo = _UUID16.sub(lambda _m: _new_id().encode("utf-16-be"), raw)
    return novo.hex() if len(novo) == len(raw) else hexstr


def _patch_geometry(hexstr: str, w: int, h: int) -> str:
    """`Resolution` (2 × u64) e `FrameSize` (i32, proporcional aos pixels: 12182 em 1920×1080
    e 13000 em 2048×1080 no gabarito) do blob `<Geometry>`."""
    raw = bytearray.fromhex(hexstr)
    k = "Resolution".encode("utf-16-be")
    i = raw.find(k)
    if i < 0:
        return hexstr
    i += len(k)
    if raw[i:i + 4] != b"\x00\x00\x00\x0c" or raw[i + 5:i + 9] != b"\x00\x00\x00\x10":
        return hexstr
    w0 = int.from_bytes(raw[i + 9:i + 17], "big")
    h0 = int.from_bytes(raw[i + 17:i + 25], "big")
    raw[i + 9:i + 17] = int(w).to_bytes(8, "big")
    raw[i + 17:i + 25] = int(h).to_bytes(8, "big")
    k = "FrameSize".encode("utf-16-be")
    j = raw.find(k)
    if j >= 0 and w0 and h0:
        j += len(k)
        if raw[j:j + 4] == b"\x00\x00\x00\x02":
            fs0 = int.from_bytes(raw[j + 5:j + 9], "big")
            raw[j + 5:j + 9] = round(fs0 * w * h / (w0 * h0)).to_bytes(4, "big")
    return bytes(raw).hex()


def _patch_time_fps(hexstr: str, fps: float) -> str:
    """`FrameRate` do blob `<Time>`: [u32 12][u8][u32 16][f64 LE][8 zeros]."""
    import struct
    raw = bytearray.fromhex(hexstr)
    k = "FrameRate".encode("utf-16-be")
    i = raw.find(k)
    if i < 0 or not fps:
        return hexstr
    i += len(k)
    if raw[i:i + 4] != b"\x00\x00\x00\x0c" or raw[i + 5:i + 9] != b"\x00\x00\x00\x10":
        return hexstr
    raw[i + 9:i + 17] = struct.pack("<d", float(fps))
    return bytes(raw).hex()


#: `Radiometry` do item BRAW: "forma" = o da forma (metadados RAW da câmera do gabarito);
#: "generica" = o do item não-RAW. Em medição (2026-09-26): qual o Resolve aceita, e se ele
#: relê o balanço de branco e o ISO do arquivo.
RADIOMETRIA_BRAW = "forma"


def _ajustar_formato_nativo(b: str, caminho: str) -> str:
    """Item de VÍDEO não-MXF (forma nativa da família): resolução, taxa, UniqueIds, o áudio
    embutido do arquivo e, no mp4/mov, o codec. O formato e a flag são os da forma.
    Identidade, TC e duração já vieram do `_make_pool_clip`."""
    meta = _formato_meta(caminho)
    _nb, fps, tc = _media_meta(caminho)
    familia = _familia(caminho)
    braw = familia == "braw"
    # BRAW: a resolução útil (o ffprobe dá a gravada) e o codec da forma (`BRAW`, não `brst`).
    # ARRIRAW: o raster do cabeçalho MXF e o codec da forma (o ffprobe não o conhece).
    tamanho = (_braw_crop(caminho) if braw and _abs(caminho) not in _META_CACHE_OFFLINE
               else None) or (_raster_arriraw(caminho) if familia == "arriraw" else None) \
        or ((meta["w"], meta["h"]) if meta.get("w") else None)
    codec_video = None if familia in ("braw", "arriraw") else meta.get("vtag")

    def _video(m):
        blk = m.group(0)
        blk = re.sub(r"<Clip>([0-9a-fA-F]{40,})</Clip>",
                     lambda c: "<Clip>" + _patch_formato_clip(c.group(1), None, None, codec_video)
                     + "</Clip>", blk)
        if tamanho:
            blk = re.sub(r"<Geometry>([0-9a-fA-F]+)</Geometry>",
                         lambda g: "<Geometry>" + _patch_geometry(g.group(1), *tamanho)
                         + "</Geometry>", blk)
        if braw and RADIOMETRIA_BRAW == "generica":
            generica = re.search(r"<Radiometry>([0-9a-fA-F]*)</Radiometry>",
                                 _formas_nativas()["video"]).group(1)
            blk = re.sub(r"<Radiometry>[0-9a-fA-F]*</Radiometry>",
                         lambda _r: f"<Radiometry>{generica}</Radiometry>", blk)
        if fps:
            blk = re.sub(r"<Time>([0-9a-fA-F]+)</Time>",
                         lambda t: "<Time>" + _patch_time_fps(t.group(1), fps) + "</Time>", blk)
        return blk

    b = re.sub(r"<BtVideoInfo\b.*?</BtVideoInfo>", _video, b, count=1, flags=re.DOTALL)
    # Áudio embutido: o do arquivo, começando no TC do VÍDEO (o mp4 não tem time_reference).
    _mst, dur_sec, sr, ch, dts = _audio_meta(caminho)
    inicio = _tc_to_frames(tc, round(fps)) / fps if tc and fps else 0.0

    def _audio(m):
        blk = m.group(0)
        blk = re.sub(r"<Clip>([0-9a-fA-F]{40,})</Clip>",
                     lambda c: "<Clip>" + _patch_formato_clip(c.group(1), None, None,
                                                              meta.get("acodec")) + "</Clip>", blk)
        return re.sub(r"<TracksBA>([0-9a-fA-F]+)</TracksBA>",
                      lambda t: "<TracksBA>" + _regen_audio_tracks_ba(t.group(1), sr, ch, dts, inicio)
                      + "</TracksBA>", blk)

    b = re.sub(r"<BtAudioInfo\b.*?</BtAudioInfo>", _audio, b, flags=re.DOTALL)
    if dur_sec:
        b = re.sub(r"<FieldsBlob>([0-9a-fA-F]{40,})</FieldsBlob>",
                   lambda f: "<FieldsBlob>" + _patch_media_extents(f.group(1), inicio, dur_sec)
                   + "</FieldsBlob>", b, count=1)
    for tag in ("Time", "Geometry", "Proxy", "VideoMetadata", "TracksBA"):
        b = re.sub(rf"<{tag}>([0-9a-fA-F]+)</{tag}>",
                   lambda m, t=tag: f"<{t}>" + _novos_unique_ids(m.group(1)) + f"</{t}>", b)
    return b


def _effect_filters_ba_for(seg: dict, desloc_kf: int = 0) -> str | None:
    """Traduz o efeito geométrico do segmento (Avid) → `EffectFiltersBA` do Resolve.

    Modelo neutro = fração do raster (ver docs/effect-translation.md). Conversão Avid→Resolve:
    pos (milésimos) /1000 = fração (Resolve guarda px/1920, px/1080 = mesma fração; +Y cima nos
    dois); scale (já fator no parser) = zoom; rot_z = graus. Posição/escala validados; sinal de
    rotação a confirmar. Crop/opacity ainda não emitidos (filtros separados — a fazer).

    O REFORMAT do FrameFlex (o encaixe de mídia com outro aspecto) vira o Scaling POR CLIPE do
    Resolve, o mesmo conceito: Pillarbox → Fit, Center Crop → Fill, Keep Size → Crop (1:1),
    Stretch → Stretch (medido no `TL ULTRAHD.drt`, caso E06, 2026-09-27).

    `desloc_kf`: quanto o `In` do clipe andou depois da leitura (taxa variável, correção de
    offset) — os keyframes vivem no domínio do `In` e andam junto."""
    escala = _ESCALA_DO_REFORMAT.get(seg.get("reframe_mode") or "")
    retime = seg.get("retime")             # nearest|frame_blend|optical_flow (Premiere; None = projeto)
    for e in (seg.get("effects") or []):
        if e.get("category") != "geometric" or not e.get("reproducible"):
            continue
        p = e.get("params") or {}
        kw = {"escala": escala, "retime": retime}
        if "pos_x" in p: kw["pos_x"] = p["pos_x"] / 1000.0
        if "pos_y" in p: kw["pos_y"] = p["pos_y"] / 1000.0
        if "scale_x" in p: kw["zoom_x"] = p["scale_x"]
        if "scale_y" in p: kw["zoom_y"] = p["scale_y"]
        if "rot_z" in p: kw["rotation"] = p["rot_z"]
        if p.get("pitch"): kw["pitch"] = p["pitch"]              # Basic 3D do Premiere
        if p.get("yaw"): kw["yaw"] = p["yaw"]
        if "opacity" in p: kw["opacity"] = p["opacity"]          # Avid 0–100 = Resolve 0–100
        if p.get("flip_x"): kw["flip_x"] = True
        if p.get("flip_y"): kw["flip_y"] = True
        if p.get("composite"): kw["composite"] = p["composite"]
        if p.get("crop_frac"):
            # Premiere: já em FRAÇÃO cortada por borda (o que o Resolve guarda).
            c = p["crop_frac"]
            kw.update(crop_l=c.get("l"), crop_r=c.get("r"), crop_t=c.get("t"), crop_b=c.get("b"))
            if p.get("crop_suave"):
                kw["crop_suave"] = p["crop_suave"]
        if p.get("kf"):
            # keyframes já no domínio do Resolve (zoom fator; pos FRAÇÃO, +Y cima; graus) —
            # `prproj/leitura.py`. Tempo = quadro da fonte.
            k = {nome: [(q + desloc_kf, v) for q, v in pts] if pts else pts
                 for nome, pts in p["kf"].items()}
            kw["animado"] = {"zoom_x": k.get("zoom"), "zoom_y": k.get("zoom_y") or k.get("zoom"),
                             "pos_x": k.get("pos_x"), "pos_y": k.get("pos_y"),
                             "rotation": k.get("rot")}
        # CROP — Avid guarda a POSIÇÃO da borda em ±999 (0 = 50% cropado); +X dir, +Y cima.
        # Resolve guarda a FRAÇÃO cropada por borda. Confirmado (CROP CONFIRMACAO.aaf):
        #   esquerda/baixo = (v+999)/1998 ; direita/topo = (999-v)/1998 (invertidos).
        if "crop_l" in p: kw["crop_l"] = (p["crop_l"] + 999.0) / 1998.0
        if "crop_b" in p: kw["crop_b"] = (p["crop_b"] + 999.0) / 1998.0
        if "crop_r" in p: kw["crop_r"] = (999.0 - p["crop_r"]) / 1998.0
        if "crop_t" in p: kw["crop_t"] = (999.0 - p["crop_t"]) / 1998.0
        if len(kw) > 2 or escala or retime:
            return build_effect_filters_ba(**kw)
    return build_effect_filters_ba(escala=escala, retime=retime) if (escala or retime) else None


#: `Segment.reframe_mode` (o AFX_SPATIAL_REFORMAT do Avid) → o Scaling por clipe do Resolve.
_ESCALA_DO_REFORMAT = {"pillarbox": "fit", "center_crop": "fill", "keep_size": "crop",
                       "stretch": "stretch"}


#: `Flags` do clipe da timeline: 0 = ligado, 2 = DESLIGADO. Medido em 2026-09-24 no DRT
#: nativo do Resolve 19 importando o AAF da mesma timeline: o som de câmera que o editor
#: desligou no Avid chega com `Flags=2`, o vídeo do mesmo take com `Flags=0`.
FLAG_DESLIGADO = "2"


def _flags_de(block: str, seg: dict) -> str:
    """Clipe desabilitado no Avid sai DESLIGADO no Resolve — não sumido, não ligado."""
    return _set_field(block, "Flags", FLAG_DESLIGADO) if seg.get("disabled") else block


def _make_timeline_clip(shape: str, seg: dict, db_id: str, matched_path: str,
                        offset_corr: int = 0, start_override: int | None = None,
                        dur_override: int | None = None, in_extra: int = 0) -> str:
    """Clona a forma de Sm2TiVideoClip e preenche a partir do segmento + arquivo casado.

    fps/velocidade (camada de tradução p/ o Resolve): In e timemap usam o RELATIVE_SPEED
    (o que o editor mudou), não o speed_ratio TOTAL do Avid. O Resolve conforma a fps da mídia
    sozinho (MediaFrameRate = fps do arquivo) → herdar a velocidade de conform aplicava a fps
    duas vezes e jogava o OUT fora. Em clipe de MESMA fps, relative_speed == speed_ratio, então
    o comportamento validado é preservado; em conform puro relative≈1.0 → In sem fator e timemap
    100%. Soma-se também a correção de offset visual (source_offset_correction) ao In.
    """
    # start_override/dur_override/in_extra: ajustes p/ ENCOSTAR o clipe num corte com transição
    # (o vizinho é cortado no ponto do corte; o dissolve usa os handles além do corte).
    base_start = start_override if start_override is not None else _tc_to_frames(seg["timeline_tc_in"])
    start = base_start + _TIMELINE_OFFSET_FRAMES
    dur = int(dur_override) if dur_override is not None else int(seg["duration_frames"])
    sr = float(seg.get("speed_ratio") or 1.0) or 1.0
    sr_leitura = sr
    rel = float(seg.get("relative_speed") or sr) or sr
    is_ramp = _curva_de_posicao(seg)          # a rampa, ou o congelado (o mapa achatado)
    reverso = seg.get("motion_effect_type") == "reverse"
    if (seg.get("media_ref") or {}).get("descriptor_type") == "prproj" and not is_ramp and not reverso:
        # ⛔ MEDIDO 2026-10-05 (Resolve 19, sintéticos com o número do quadro em código de barras): o
        # Resolve mostra o quadro floor(In × taxa_do_ARQUIVO / taxa_da_timeline), com a taxa que ELE
        # lê do cabeçalho (a do ffprobe, `r_frame_rate`). O `speed_ratio` do Premiere usa a taxa que o
        # PREMIERE calcula — iguais num arquivo normal, diferentes num de taxa VARIÁVEL (celular: 25 no
        # cabeçalho, 24,0118 no Premiere, os mesmos 1.387 quadros). O insert do interfone do PRODB
        # entrava 27 quadros adiantado. A entrada passa a ser convertida pela taxa do Resolve.
        _nb_a, fps_arq, _tc_a = _media_meta(matched_path)
        fps_premiere = float(seg.get("source_fps") or 0)
        if fps_arq and fps_premiere and abs(fps_premiere / fps_arq - 1) > 1e-3:
            sr *= fps_premiere / fps_arq
    # In no domínio de frames da TIMELINE (o Resolve interpreta o In na taxa da timeline e
    # conforma a mídia internamente). `source_start_frames` vive na fps NATIVA do AAF; o Avid
    # SpeedRatio = timeline_fps/nat_fps → In = fonte × speed_ratio leva ao domínio da timeline.
    # Robusto inclusive quando o AAF rotula a nativa errada (C004: nat=29.97 mas arquivo 23.976):
    # fonte e speed_ratio ficam ambos no mesmo domínio (29.97) e o produto cai no da timeline.
    # A VELOCIDADE de CONFORM não entra aqui (vai zerada no timemap via relative_speed).
    # `in_extra` (frames de timeline) avança o In quando o clipe começa depois do corte.
    in_pt = 0 if is_ramp else round((int(seg.get("source_start_frames") or 0)
                                     + int(offset_corr or 0)) * sr) + int(in_extra or 0)
    # ⭐ O In com FRAÇÃO (BL09, Resolve 21.1, 2026-11-23): a fonte de OUTRA taxa cai num In fracionário da timeline (o quadro
    # 364 de um 29,97 numa timeline de 23,976 = 291,2). Inteiro, o Resolve converte 291 × 1,25 = 363,75 e ARREDONDA PARA
    # BAIXO — um quadro antes, calado (medido pela imagem: 363 e 127 em vez de 364 e 128). O DRT nativo grava
    # `291|<f64 LE da fração>` (0,2000000000477: um fio ACIMA, para o piso não cair no quadro anterior).
    in_fracao = 0.0
    if not is_ramp and abs(sr - 1.0) > 1e-9:
        exato = (int(seg.get("source_start_frames") or 0) + int(offset_corr or 0)) * sr + int(in_extra or 0)
        if abs(exato - round(exato)) > 1e-6:
            in_fracao = exato                     # o campo grava piso + fração; o `in_pt` segue arredondado (keyframes)
    rampa_prproj = bool(is_ramp) and (seg.get("media_ref") or {}).get("descriptor_type") == "prproj"
    if rampa_prproj:
        # ⛔ MEDIDO 2026-10-10 (Resolve 19, R04): a curva de tempo é forçada a começar em (0, 0) — a
        # fonte no segundo zero. A rampa do Premiere começa no MEIO do arquivo: com o `In` 0 o plano
        # saía do começo do arquivo (a claquete). A curva ganha uma entrada a 100 % de (0, 0) até a
        # entrada da fonte, e o clipe começa ali (`In`); os keyframes de Motion contam do plano
        # (`prproj/leitura.py`) e andam o mesmo `In` (`desloc_kf`).
        _nb_r, fps_r, _ = _media_meta(matched_path)
        if fps_r:
            in_pt = round(int(seg.get("source_start_frames") or 0) / fps_r * _TL_FPS) + int(in_extra or 0)
    elif is_ramp and not reverso and _inicio_da_rampa(seg) > 0:
        # ⛔ MEDIDO 2026-10-12 (laboratório B22/N1, Resolve 19): a MESMA entrada vale para a rampa do Avid. Com o
        # `In` 0 e o clipe começando no quadro 80 da mídia, o trecho de (0, 0) ao 1º ponto da curva saía errado —
        # 28/48 quadros (o 1º quadro mostrava o 0 da mídia em vez do 80). Com a entrada: o plano começa no `In`.
        # O início é o in do clipe de dentro MAIS a 1ª posição do mapa (no gráfico de posição o plano pode começar
        # no meio da curva com o clipe de dentro no 0 — o 1º quadro saía errado, 47/48).
        _nb_r, fps_r, _ = _media_meta(matched_path)
        if fps_r:
            in_pt = round(_inicio_da_rampa(seg) / fps_r * _TL_FPS)
    # o `In` sem a correção de taxa variável: é nele que a leitura contou os keyframes
    in_leitura = 0 if is_ramp else round((int(seg.get("source_start_frames") or 0)
                                          + int(offset_corr or 0)) * sr_leitura) + int(in_extra or 0)
    if reverso:
        # Para trás (Premiere `PlayBackwards`): a curva do Resolve desce de Y0 no fim da mídia
        # (`build_reverse_timemap`); o In é o X em que ela passa pelo 1º quadro do plano.
        _nb, _fps_m, _ = _media_meta(matched_path)
        v = abs(float(seg.get("velocidade_fonte") or 1.0)) or 1.0
        if _nb and _fps_m:
            y_ini = float(seg.get("source_start_exato") or seg.get("source_start_frames") or 0) / _fps_m
            in_pt = round((reverso_y0(_nb, _fps_m, v) - y_ini) / v * _TL_FPS) + int(in_extra or 0)
    # Nome = arquivo ONLINE reconectado (não o nome do offline do AAF, que vem com .new.NN);
    # casa com o nome do clipe no media pool e é o que o editor espera ver na timeline.
    name = _nome(matched_path)
    reel = _reel(_nome(matched_path))

    block = _uniquify(shape)   # DbIds próprios por clipe da timeline
    block = _set_field(block, "Name", _xml_escape(name))
    block = _set_field(block, "Start", str(start))
    block = _set_field(block, "Duration", str(dur))
    if in_fracao:
        piso = int(in_fracao // 1)
        block = _set_field(block, "In", f"{piso}|{struct.pack('<d', in_fracao - piso + 1e-9).hex()}")
    elif in_pt == 0:
        block = re.sub(r"<In>.*?</In>", "<In/>", block, count=1, flags=re.DOTALL)
    else:
        block = _set_field(block, "In", str(in_pt))
    block = _set_field(block, "MediaRef", db_id)
    block = _set_field(block, "MediaFilePath", _xml_escape(_abs(matched_path)))
    block = _set_field(block, "MediaReelNumber", _xml_escape(reel))
    block = _flags_de(block, seg)

    _nb, fps, tc = _media_meta(matched_path)
    if tc and fps:
        # MediaStartTime é em SEGUNDOS = TC(frames nominais) / fps_real (o Resolve
        # multiplica por fps p/ obter o frame). Ex.: 02:56:44:17 → 254513/23.976 =
        # 10615.313… (validado vs DRT de referência). Setar frames dá TC absurdo (×fps).
        # O TC é do ARQUIVO → conta na base do ARQUIVO (round(fps)), NÃO na da timeline.
        block = _set_field(block, "MediaStartTime", repr(_tc_to_frames(tc, round(fps)) / fps))
    if fps:
        block = _set_field(block, "MediaFrameRate", framerate_encode(fps))
    # Envia só a velocidade RELATIVA (criativa). Conform puro (rel≈1.0) → 100% (sem retime),
    # o Resolve conforma a fps sozinho. Rampa ignora `rel` (usa o offset_map nativo do seg).
    if reverso:
        _nb, _fps_m, _ = _media_meta(matched_path)
        tm = build_reverse_timemap(_nb, _fps_m, abs(float(seg.get("velocidade_fonte") or 1.0))) \
            if (_nb and _fps_m) else None
    else:
        # A rampa do Premiere vem com o eixo X em quadros da TIMELINE (`prproj/leitura.py`, quadro a
        # quadro); a do Avid, na taxa da fonte (validado assim). Não trocar a do Avid.
        _f_avid = float(seg.get("source_fps") or 0) or None
        # a entrada vai no domínio de X de cada caminho: quadros da timeline (Premiere) ou da fonte (Avid)
        _entrada = in_pt if rampa_prproj else (in_pt * _f_avid / _TL_FPS if (is_ramp and in_pt and _f_avid) else 0)
        tm = _media_timemap(matched_path, rel, seg=seg, entrada=_entrada,
                            tl_fps=_TL_FPS if rampa_prproj else _f_avid)
    if tm:
        block = _set_field(block, "MediaTimemapBA", tm)

    if _e_still(matched_path):
        # Imagem parada: o Resolve grava a taxa da TIMELINE e um mapa constante (gabarito 21.1).
        block = _set_field(block, "MediaFrameRate", framerate_encode(_TL_FPS))
        block = _set_field(block, "MediaTimemapBA",
                           _novos_unique_ids(_formas_nativas()["timemap_still"]))
        block = _set_field(block, "MediaStartTime", "0")
        block = re.sub(r"<In>.*?</In>", "<In/>", block, count=1, flags=re.DOTALL)

    # Keyframe do Premiere = `In` da leitura (fonte × speed_ratio) + quadro dentro do plano
    # (`prproj/leitura.py::_segmento`). Se o `In` mudou aqui (taxa variável), os keyframes andam
    # o mesmo tanto. ⛔ MEDIDO 2026-10-08 (Resolve 21.1, PRODB, insert do interfone em
    # 01:22:49): o `In` foi a 650 pela taxa do arquivo e o rastreamento ficou em 677 — o insert
    # parado por 27 quadros, a placa andando e a borda escura da tela aparecendo.
    desloc_kf = 0 if (reverso or _e_still(matched_path)) else in_pt - in_leitura
    efb = _effect_filters_ba_for(seg, desloc_kf)
    if efb:
        if "<EffectFiltersBA>" in block:
            block = _set_field(block, "EffectFiltersBA", efb)
        else:
            # forma do esqueleto não tem o campo — inserir na posição do Resolve
            # (logo antes de UseOppositeSrcForLeftEye, onde ele aparece nos exports reais)
            block = block.replace(
                "<UseOppositeSrcForLeftEye>",
                f"<EffectFiltersBA>{efb}</EffectFiltersBA><UseOppositeSrcForLeftEye>", 1)

    fb = _xml_field(block, "FieldsBlob")
    if fb:
        block = _set_field(block, "FieldsBlob", _patch_fieldsblob_start(fb, start))
    return block


def _make_video_track(track_shape: str, clips_xml: list[str]) -> str:
    """Clona uma Sm2TiTrack (novo DbId) com os Items dos clipes gerados."""
    tr = re.sub(r'(<Sm2TiTrack\s+DbId=")[^"]+(")',
                lambda m: m.group(1) + _new_id() + m.group(2), track_shape, count=1)
    items = "<Items>" + "".join(f"<Element>{c}</Element>" for c in clips_xml) + "</Items>"
    # `lambda`: os clipes carregam caminhos, e `\` na string de substituição é escape
    # para o `re` (ver `_set_field`).
    return re.sub(r"<Items>.*?</Items>", lambda _m: items, tr, count=1, flags=re.DOTALL)


def _empty_all_items(vec_xml: str) -> str:
    """Esvazia os <Items> de todas as tracks de um *TrackVec."""
    return re.sub(r"<Items>.*?</Items>", "<Items></Items>", vec_xml, flags=re.DOTALL)


# --------------------------------------------------------------------------- #
# Áudio (pool Sm2MpAudioClip + timeline Sm2TiAudioClip)
# --------------------------------------------------------------------------- #
_META_CACHE_A: dict[str, tuple] = {}


def _audio_meta(path: str) -> tuple:
    """(media_start_seconds, duration_seconds, sample_rate, channels, duration_ts).
    Start do áudio = BWF `time_reference`(samples)/sample_rate → segundos. duration_ts =
    nº de samples (p/ o Duration do pool)."""
    if path in _META_CACHE_A:
        return _META_CACHE_A[path]
    sr = dur = ch = dts = None
    mst = 0.0
    try:
        j = _sonda.ler(path)
        st = _sonda.primeiro(j, "audio")       # o `-select_streams a:0` de antes
        if st.get("sample_rate") and str(st["sample_rate"]).isdigit():
            sr = int(st["sample_rate"])
        # canais = a SOMA de todos os streams de áudio (banco, B098): a câmera com 4 streams mono tem 4 canais, não 1
        ch = sum(int(s.get("channels") or 0) for s in (j.get("streams") or [])
                 if s.get("codec_type") == "audio") or None
        if st.get("duration_ts") and str(st["duration_ts"]).isdigit():
            dts = int(st["duration_ts"])
        if sr and dts:
            dur = dts / sr
        elif j.get("format", {}).get("duration"):
            dur = float(j["format"]["duration"])
            if sr and dur:
                dts = int(round(dur * sr))
        tr = (j.get("format", {}).get("tags", {}) or {}).get("time_reference")
        if tr and str(tr).isdigit() and sr:
            mst = int(tr) / sr
    except _sp.TimeoutExpired:
        _SONDA_LENTA.add(path)
        return (mst, dur, sr, ch, dts)     # LENTO não é ilegível: sem cache (`_SONDA_LENTA`)
    except Exception:
        pass
    _META_CACHE_A[path] = (mst, dur, sr, ch, dts)
    return _META_CACHE_A[path]


def _regen_audio_tracks_ba(hexstr: str, sr: int | None, ch: int | None,
                           dts: int | None, start_sec: float) -> str:
    """Patcha o blob `<TracksBA>` (BA) do pool clip de áudio com SampleRate (type3 u32),
    NumChannels (type2 i32), Duration (type4 u64 = samples) e StartTime (type6 double =
    segundos) do arquivo casado. Sem isso, o áudio herda os specs da forma (ex.: 96000Hz
    → toca acelerado/agudo). Valores de tamanho fixo → patch byte-a-byte."""
    import struct
    raw = bytearray.fromhex(hexstr)

    def voff(key: str):
        i = raw.find(key.encode("utf-16-be"))
        return (i + len(key.encode("utf-16-be")) + 5) if i >= 0 else None  # após [u32 type][u8 flag]

    if sr:
        p = voff("SampleRate")
        if p is not None:
            raw[p:p + 4] = int(sr).to_bytes(4, "big")
    if ch:
        p = voff("NumChannels")
        if p is not None:
            raw[p:p + 4] = int(ch).to_bytes(4, "big")
    if dts:
        p = voff("Duration")
        if p is not None:
            raw[p:p + 8] = int(dts).to_bytes(8, "big")
    if start_sec:
        p = voff("StartTime")
        if p is not None:
            raw[p:p + 8] = struct.pack(">d", float(start_sec))
    return bytes(raw).hex()


def _patch_media_extents(hexstr: str, start_sec: float, dur_sec: float) -> str:
    """Patcha o `MediaExtents` (chave UTF-16BE no BA `f1.f5` do FieldsBlob zstd) com
    [start_seg, duração_seg] como 2 doubles LITTLE-ENDIAN do arquivo casado.

    É DAQUI que o Resolve lê Duration/Start TC/End TC do media pool quando o clipe NÃO
    tem blob `<Time>` (caso do ÁUDIO — o vídeo usa o `<Time>` e ignora o MediaExtents).
    Sem este patch todos os áudios herdam o extent da FORMA (ex.: [3600.0, 52.65]) → no
    media pool aparecem com a MESMA duração/TC, mesmo tocando certo na timeline.
    Layout após a chave: [u32 type=12][u32 a][u8 tag][f64 d1=start][f64 d2=dur]."""
    import struct
    try:
        import zstandard
    except Exception:
        return hexstr
    raw = bytes.fromhex(hexstr)
    if len(raw) < 13 or raw[9:13].hex() != "28b52ffd":
        return hexstr
    ver, flag = raw[0:4], raw[8:9]
    try:
        dec = bytearray(zstandard.ZstdDecompressor().decompress(raw[9:]))
    except Exception:
        return hexstr
    # ⛔ TODAS as ocorrências: a forma de áudio do esqueleto tem 5 trilhas, uma entrada por
    # trilha. Trocar só a 1ª deixava as outras 4 com o TC e a duração da forma (11:42:42,
    # 8m43s), e o Resolve mostrava ESSES no pool — e, com a mídia pré-importada, não reconhecia
    # o item como o mesmo arquivo: o áudio duplicava no pool (medido 2026-09-26, 54 WAV).
    key = "MediaExtents".encode("utf-16-be")
    trocou = False
    k = dec.find(key)
    while k >= 0:
        p = k + len(key)
        if dec[p:p + 4] == (12).to_bytes(4, "big"):   # confirma type=12 (obj de doubles)
            if start_sec is not None:
                dec[p + 9:p + 17] = struct.pack("<d", float(start_sec))
            if dur_sec:
                dec[p + 17:p + 25] = struct.pack("<d", float(dur_sec))
            trocou = True
        k = dec.find(key, p)
    if not trocou:
        return hexstr
    comp = zstandard.ZstdCompressor().compress(bytes(dec))
    payload = flag + comp
    return (ver + len(payload).to_bytes(4, "big") + payload).hex()


def _patch_channel_vec(hexstr: str, num_channels: int) -> str:
    """Garante N-1 entradas ChannelIdx no ChannelVecBA do FieldsBlob zstd, com valores
    [N-1, N-2, …, 1] (canal 0 é implícito — Resolve exibe Audio Ch = entries+1 = N).

    Sem este patch o pool clip herda 1 entrada da forma → Audio Ch=2 independente do
    arquivo. Cada entrada é o bloco entre 'ChannelIdx' key e fim da chave 'BitDepth'
    seguinte (template medido em runtime a partir da entrada já existente)."""
    import struct
    if num_channels <= 1:
        return hexstr
    try:
        import zstandard
    except Exception:
        return hexstr
    raw = bytes.fromhex(hexstr)
    if len(raw) < 13 or raw[9:13].hex() != "28b52ffd":
        return hexstr
    ver, flag = raw[0:4], raw[8:9]
    try:
        dec = bytearray(zstandard.ZstdDecompressor().decompress(raw[9:]))
    except Exception:
        return hexstr
    KEY_CI = "ChannelIdx".encode("utf-16-be")
    KEY_BD = "BitDepth".encode("utf-16-be")
    ci = bytes(dec).find(KEY_CI)
    if ci < 0:
        return hexstr
    bd = bytes(dec).find(KEY_BD, ci)
    if bd < 0:
        return hexstr
    # entry = [keylen(4)] + KEY_CI(20) + [type(4)+flag(1)+i32(4)] → BitDepth end
    entry_start = ci - 4
    entry_end = (bd - 4) + 4 + len(KEY_BD) + 4 + 1 + 4
    if entry_start < 0 or entry_end > len(dec):
        return hexstr
    entry_template = bytes(dec[entry_start:entry_end])
    ci_val_off = 4 + len(KEY_CI) + 4 + 1  # offset do i32 dentro do template
    # Constrói N-1 entradas com ChannelIdx = N-1 downto 1 (descending como referência)
    new_entries = bytearray()
    for ch in range(num_channels - 1, 0, -1):
        entry = bytearray(entry_template)
        struct.pack_into(">i", entry, ci_val_off, ch)
        new_entries.extend(entry)
    new_dec = bytearray(dec[:entry_start]) + new_entries + bytearray(dec[entry_end:])
    comp = zstandard.ZstdCompressor().compress(bytes(new_dec))
    payload = flag + comp
    return (ver + len(payload).to_bytes(4, "big") + payload).hex()


def _mapa_de_canais(hexstr: str, n: int, inicio: float | None, dur: float | None,
                    trilha: str, sr: int | None, bits: int | None) -> str:
    """`FieldsBlob` do item de áudio NATIVO com `n` canais, na estrutura que o Resolve 19 grava
    ao importar o arquivo (medido no banco do projeto, 2026-09-26):

    - **1 canal:** um registro "0" com `SampleRate`; o canal 0 sem `ChannelIdx`;
    - **2 canais:** UM registro "0" com `Type`=0 e `SampleRate`, e os DOIS canais dentro do
      `ChannelVecBA` ("1" com `ChannelIdx` 1, "0" sem);
    - **3 ou mais:** um registro por canal (n-1…0), cada um com um canal; o "0" sem `ChannelIdx`.

    ⛔ Com a mídia pré-importada, o Resolve só reaproveita o item do DRT se a estrutura for a
    dele: o item com uma entrada por canal para um estéreo duplicava no pool (17 efeitos e
    trilhas mono/estéreo; o som direto de 3–5 canais já batia)."""
    import copy
    import struct

    import zstandard
    from drp.ba_mapa import QBYTEARRAY, escrever_mapa, ler_mapa, valor
    from tools.inspect_drp import pb_decode, pb_encode

    raw = bytes.fromhex(hexstr)
    if n < 1 or len(raw) < 13 or raw[9:13].hex() != "28b52ffd":
        return hexstr
    campos = pb_decode(zstandard.ZstdDecompressor().decompress(raw[9:]))
    ba = campos[0]["value"][0]["value"]
    ver, itens, resto = ler_mapa(bytes(ba))
    _mv, modelo, mresto = ler_mapa(itens[0][1][2])
    _cv, cv_modelo, cv_resto = ler_mapa(valor(modelo, "ChannelVecBA")[2])
    c_ver, c_modelo, c_resto = ler_mapa(cv_modelo[0][1][2])

    def canal(k: int) -> list:
        c = [(key, copy.deepcopy(x)) for key, x in c_modelo if key != "ChannelIdx"]
        valor(c, "MediaRef")[2] = trilha
        if k:
            c.append(("ChannelIdx", [2, 0, k]))
        return [QBYTEARRAY, 0, escrever_mapa(c_ver, c, c_resto)]

    def registro(canais: list[tuple[str, int]], cabeca: list) -> list:
        reg = []
        for key, x in modelo:
            x = copy.deepcopy(x)
            if key == "MediaExtents" and inicio is not None and dur:
                x[2] = struct.pack("<dd", float(inicio), float(dur))
            elif key == "ChannelVecBA":
                x[2] = escrever_mapa(_cv, [(chave, canal(k)) for chave, k in canais], cv_resto)
            elif key == "BitDepth":
                if bits == 3:
                    continue   # 32 bits float: o Resolve não grava BitDepth no registro (medido)
                if bits:
                    x[2] = bits
            reg.append((key, x))
        return [QBYTEARRAY, 0, escrever_mapa(_mv, cabeca + reg, mresto)]

    # `SampleRate` só quando a taxa NÃO é 48 kHz (medido: 44,1 e 96 kHz têm; 48 kHz não —
    # provavelmente a taxa do projeto; só projetos de 48 kHz foram medidos).
    taxa = [("SampleRate", [3, 0, int(sr)])] if sr and int(sr) != 48000 else []
    if n == 1:
        novos = [("0", registro([("0", 0)], taxa))]
    elif n == 2:
        novos = [("0", registro([("1", 1), ("0", 0)], [("Type", [3, 0, 0])] + taxa))]
    else:
        # Cada registro tem UM canal, sempre sob a chave "0" (o índice vai no ChannelIdx).
        novos = [(str(k), registro([("0", k)], [])) for k in range(n - 1, -1, -1)]
    campos[0]["value"][0]["value"] = escrever_mapa(ver, novos, resto)
    comp = zstandard.ZstdCompressor().compress(pb_encode(campos))
    payload = raw[8:9] + comp
    return (raw[0:4] + len(payload).to_bytes(4, "big") + payload).hex()


def _trilha_nativa(hexstr: str, sr, ch, dts, inicio, bits, layout) -> str:
    """`<TracksBA>` do item de áudio nativo, pelo mapa: `StartTime` (também 0 — sem bext, o
    arquivo começa em 00:00:00:00, e o writer antigo deixava o da forma), `SampleRate`,
    `NumChannels`, `Duration`, `BitDepth` e, no mono e no AIF, `ChannelLayout` (medido)."""
    from drp.ba_mapa import QBYTEARRAY, escrever_mapa, ler_mapa, valor

    ver, itens, resto = ler_mapa(bytes.fromhex(hexstr))
    t_ver, trk, t_resto = ler_mapa(itens[0][1][2])
    for key, novo in (("StartTime", float(inicio or 0.0)), ("SampleRate", sr),
                      ("NumChannels", ch), ("Duration", dts), ("BitDepth", bits)):
        x = valor(trk, key)
        if x is not None and novo is not None:
            x[2] = novo
    trk = [(k, x) for k, x in trk if k != "ChannelLayout"]
    if layout:
        i = next((j for j, (k, _x) in enumerate(trk) if k == "BitDepth"), len(trk))
        trk.insert(i, ("ChannelLayout", [2, 0, int(layout)]))
    itens[0] = (itens[0][0], [QBYTEARRAY, 0, escrever_mapa(t_ver, trk, t_resto)])
    return _novos_unique_ids(escrever_mapa(ver, itens, resto).hex())


def _make_audio_pool_clip_nativo(name: str, db_id: str, uniq_id: str, matched_path: str) -> str:
    """Sm2MpAudioClip de WAV/AIF na forma NATIVA do Resolve 19: UMA trilha com os N canais
    do arquivo (a do esqueleto tem 5 trilhas mono, a de uma MXF gerenciada)."""
    meta = _formato_meta(matched_path)
    aiff = os.path.splitext(matched_path)[1].lower() in (".aif", ".aiff")
    mst, dur_sec, sr, ch, dts = _audio_meta(matched_path)
    b = _uniquify(_formas_nativas()["audio"], top_db_id=db_id)
    # Flag do campo 18 carrega o container: WAV 32768, AIFF 32770 (medido no banco).
    b = re.sub(r"<Clip>([0-9a-fA-F]{40,})</Clip>",
               lambda m: "<Clip>" + _patch_formato_clip(
                   _regen_clip_blob(m.group(1), matched_path), None,
                   FLAG_AUDIO + 2 if aiff else None, meta.get("acodec")) + "</Clip>", b)
    layout = ch if ch and (ch == 1 or aiff) else None
    b = re.sub(r"<TracksBA>([0-9a-fA-F]+)</TracksBA>",
               lambda m: "<TracksBA>" + _trilha_nativa(m.group(1), sr, ch, dts, mst,
                                                       meta.get("abits"), layout) + "</TracksBA>", b)
    trilha = re.search(r'<BtAudioInfo DbId="([^"]+)"', b).group(1)
    if ch:
        b = re.sub(r"<FieldsBlob>([0-9a-fA-F]{40,})</FieldsBlob>",
                   lambda m: "<FieldsBlob>" + _mapa_de_canais(m.group(1), ch, mst, dur_sec, trilha,
                                                              sr, meta.get("abits"))
                   + "</FieldsBlob>", b, count=1)
    if ch == 2:
        # O clipe que vem do Avid é MONO (lê um canal só). O Resolve só grava um clipe mono
        # do canal 2 (`MediaTrackIdx` 1) com o item em DUAL MONO; com o item estéreo, ele não
        # existe no Resolve, e o item duplicava no pool (medido 2026-09-27).
        b = _set_field(b, "VirtualAudioTracksBA", VIRTUAL_DUAL_MONO)
    b = _set_field(b, "Name", _xml_escape(name))
    b = _set_field(b, "UniqueMediaPoolItemId", uniq_id)
    return b


#: `VirtualAudioTracksBA` do item de um arquivo estéreo em dual mono, como o Resolve 19 o grava
#: quando o editor escolhe "Mono" × 2 nos atributos do clipe. Mapa Qt {"1": [`1:2`], "0": [`1:1`]},
#: com `AudioType` 1 em cada um. É o mesmo em qualquer arquivo de 2 canais: medido igual, byte a
#: byte, em dois WAV do projeto `_DELAPRACA - testes/stereo e dual mono` (2026-09-27, banco
#: `resolve-scripting/README.md` §"Áudio: o reaproveitamento…").
VIRTUAL_DUAL_MONO = (
    "00000001000000020000000200310000000c0000000054000000010000000200000014004300680061006e006e"
    "0065006c0073004200410000000c000000000c000000020000000100004002000000120041007500640069006f"
    "00540079007000650000000200000000010000000200300000000c000000005400000001000000020000001400"
    "4300680061006e006e0065006c0073004200410000000c000000000c0000000200000001000040010000001200"
    "41007500640069006f0054007900700065000000020000000001")


def _make_audio_pool_clip(shape: str, name: str, db_id: str, uniq_id: str, matched_path: str) -> str:
    """Sm2MpAudioClip por arquivo: identidade única + caminho no `<Clip>` + specs
    (SampleRate/NumChannels/Duration/StartTime) do arquivo no `<TracksBA>` (e troca a
    sample rate da forma no FieldsBlob), senão herda os specs da forma (ex.: 96000Hz).
    A forma é a do esqueleto (MXF gerenciada); WAV/AIF vão para `_make_audio_pool_clip_nativo`."""
    if not _e_mxf(matched_path):
        return _make_audio_pool_clip_nativo(name, db_id, uniq_id, matched_path)
    b = _uniquify(shape, top_db_id=db_id)
    b = re.sub(r"<Clip>([0-9a-fA-F]{40,})</Clip>",
               lambda m: "<Clip>" + _regen_clip_blob(m.group(1), matched_path) + "</Clip>", b)
    mst, dur_sec, sr, ch, dts = _audio_meta(matched_path)
    b = re.sub(r"<TracksBA>([0-9a-fA-F]+)</TracksBA>",
               lambda m: "<TracksBA>" + _regen_audio_tracks_ba(m.group(1), sr, ch, dts, mst) + "</TracksBA>", b)
    # ⛔ Aqui havia a troca da taxa antiga pela nova em TODO o FieldsBlob, procurando pelo VALOR (48000 → 44100) — o
    # padrão de B067. Medido em 2026-10-28: nenhum molde (formas_r19, skeleton_r19) tem a taxa no FieldsBlob do clipe de
    # áudio; a troca não fazia nada, e com um molde novo acertaria qualquer campo de mesmo valor. A taxa vai pelo
    # TracksBA, por posição (depois da chave `SampleRate`).
    # Duration/Start TC/End TC do media pool (áudio não tem <Time> → lê do MediaExtents)
    # ChannelVecBA: N-1 entradas (vals N-1..1) → Resolve exibe Audio Ch = N
    if dur_sec or ch:
        def _patch_fb(hexstr):
            h = hexstr
            if dur_sec:
                h = _patch_media_extents(h, mst, dur_sec)
            if ch and ch > 1:
                h = _patch_channel_vec(h, ch)
            return h
        b = re.sub(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>",
                   lambda m: "<FieldsBlob>" + _patch_fb(m.group(1)) + "</FieldsBlob>", b)
    b = _set_field(b, "Name", _xml_escape(name))
    b = _set_field(b, "UniqueMediaPoolItemId", uniq_id)
    return b


def _volume_ba(db: float) -> str:
    """O `EffectFiltersBA` de um clipe de ÁUDIO com o volume (Inspector › Volume), em dB. Medido
    2026-10-04 no Resolve 21.1 (`SetProperty("AudioVolume", −6 / +3,5)` + Export DRT): um filtro
    tipo 0x7c, 5 slots, o volume no slot 0, paramID 0x5f, double = o valor em dB."""
    import struct as _st
    fc = bytes([0x08, 0x7C, 0x4A, 0x0F, 0x08, 0x5F, 0x1A, 0x0B, 0x0A, 0x09, 0x11]) \
        + _st.pack("<d", db) + bytes([0x4A, 0x00] * 4)
    payload = bytes([0x80, 0x0A, len(fc)]) + fc
    return (_st.pack(">I", 2) + _st.pack(">I", len(payload)) + payload).hex()


def _volume_ba_kf(pontos: list) -> str:
    """O `EffectFiltersBA` de um clipe de ÁUDIO com o volume ANIMADO: `pontos` = [(quadro, dB)].

    Gabarito do Resolve 19.0.0b.59 (Windows, 2026-10-03: 5 keyframes de volume num WAV, exportado em
    DRT): o mesmo filtro 0x7c / slot 0 / paramID 0x5f do volume fixo, com o bloco de keyframes da
    POSIÇÃO do vídeo no lugar do valor (`_efb_slot_animado`: cabeçalho −16·N, registros
    `[u32 quadro][u16 0][u16 0x0C][f64 dB]`). O 19 grava o payload comprimido (0x81 + zstd); o
    descomprimido com 0x80 é igual byte a byte ao nosso (teste `test_drt_formato`)."""
    import struct as _st

    from tools.inspect_drp import _efb_slot_animado, _write_varint
    fc = bytes([0x08, 0x7C]) + _efb_slot_animado(0x5F, pontos) + bytes([0x4A, 0x00] * 4)
    payload = bytes([0x80, 0x0A]) + _write_varint(len(fc)) + fc
    return (_st.pack(">I", 2) + _st.pack(">I", len(payload)) + payload).hex()


def _make_audio_timeline_clip(shape: str, seg: dict, db_id: str, matched_path: str,
                              channel: int = 1, start_override: int | None = None,
                              dur_override: int | None = None, in_extra: int = 0,
                              pan: float | None = None) -> str:
    """Sm2TiAudioClip a partir do segmento de áudio + arquivo casado (som direto/etc).

    `channel` = canal EMBARCADO (1-based) que este segmento lê do arquivo — distinto
    do índice da track na timeline (MediaTrackIdx). É calculado pelo caller a partir do
    layout por arquivo (ver build_drt). NÃO usar o índice da track como canal: arquivos
    de 3ch numa track A7 leriam o "canal 7", que não existe → silêncio."""
    base_start = start_override if start_override is not None else _tc_to_frames(seg["timeline_tc_in"])
    start = base_start + _TIMELINE_OFFSET_FRAMES
    dur = int(dur_override) if dur_override is not None else int(seg["duration_frames"])
    # In no domínio de frames da TIMELINE (igual ao vídeo): fonte × speed_ratio (+ in_extra
    # quando o clipe começa depois do corte numa transição).
    sr = float(seg.get("speed_ratio") or 1.0) or 1.0
    in_pt = round(int(seg.get("source_start_frames") or 0) * sr) + int(in_extra or 0)
    reel = _reel(_nome(matched_path))
    mst, mdur, _sr, _ch, _dts = _audio_meta(matched_path)
    # MediaStartTime: áudio EMBUTIDO em VÍDEO (.mp4/.mov) usa o TC do VÍDEO (igual ao clipe de
    # vídeo — o áudio da câmera vive no mesmo arquivo/origem); áudio PURO (WAV) usa o BWF
    # time_reference (mst). Sem isso o áudio da câmera saía com MediaStartTime=0 → fora do ponto.
    _nbV, _fpsV, _tcV = _media_meta(matched_path)
    if _tcV and _fpsV:
        mst = _tc_to_frames(_tcV, round(_fpsV)) / _fpsV
    elif _tcV:
        # ⚠️ Arquivo SÓ de áudio com TC (a `.mxf` mono de um canal gerenciado: `11:42:00:00`)
        # não tem taxa de vídeo para converter — e caía em 0, desalinhando o TC do clipe. O
        # Resolve 19 converte na taxa EXATA da timeline: 11:42:00:00 → 42162,12 s (medido
        # no DRT nativo da mesma timeline, 2026-09-24).
        taxa = _taxa_exata(_TL_FPS)
        mst = _tc_to_frames(_tcV, round(taxa)) / taxa

    block = _uniquify(shape)
    block = _set_field(block, "Name", _xml_escape(_nome(matched_path)))
    block = _set_field(block, "Start", str(start))
    block = _set_field(block, "Duration", str(dur))
    # ⭐ O SOM também leva a FRAÇÃO (2026-11-23, Resolve 21.1 Mac): o DRT nativo do A002C001 (29,97) posto do quadro 364
    # numa timeline de 23,976 grava `<In>291|00d0b3999999c93f</In>` no vídeo E no áudio (`GetLeftOffset(True)` = 291,2 nos
    # dois). Arredondado, o som começava até 1 quadro da timeline (42 ms) fora do vídeo.
    exato = int(seg.get("source_start_frames") or 0) * sr + int(in_extra or 0)
    if abs(sr - 1.0) > 1e-9 and abs(exato - round(exato)) > 1e-6 and exato > 0:
        piso = int(exato // 1)
        block = _set_field(block, "In", f"{piso}|{struct.pack('<d', exato - piso + 1e-9).hex()}")
    elif in_pt == 0:
        block = re.sub(r"<In>.*?</In>", "<In/>", block, count=1, flags=re.DOTALL)
    else:
        block = _set_field(block, "In", str(in_pt))
    block = _set_field(block, "MediaRef", db_id)
    block = _set_field(block, "MediaFilePath", _xml_escape(_abs(matched_path)))
    block = _set_field(block, "MediaReelNumber", _xml_escape(reel))
    block = _set_field(block, "MediaStartTime", repr(mst))   # segundos (BWF time_reference/sr)
    # ⛔ MediaFrameRate NÃO é informativo: o Resolve TOCA o áudio por ela. O molde trazia 23,976 e o
    # writer não a trocava — MEDIDO 2026-10-08 (Resolve 21.1, PRODB): o som da referência (mp4 a
    # 24) ia 0,1% mais lento, ~5 s fora no fim de 88 min, sem nada no Inspector; o mesmo arquivo
    # posto à mão na timeline vinha com 24. A taxa que o Resolve dá ao importar: a do VÍDEO do
    # arquivo; arquivo só de áudio (WAV) = a do projeto (medido: um WAV num projeto a 24 → FPS 24).
    block = _set_field(block, "MediaFrameRate",
                       framerate_encode(_fpsV if _fpsV else _taxa_exata(_TL_FPS)))
    block = _flags_de(block, seg)
    # MediaTrackIdx = o CANAL DE CONTEÚDO 0-based que este clipe LÊ do arquivo — o mesmo
    # `channel` (1-based) do ch_word abaixo, menos 1. NÃO é o índice da track na timeline:
    # num DRT de referência feito no Resolve, o áudio da câmera (numa track) e o canal 0 do
    # som direto (noutra) têm AMBOS MediaTrackIdx=0 (banco, `protocolos/drt-drp/
    # estruturas.md` §3, `confirmado`). Era `track - 1000`, herdado do RELINKER — o DRAMASYNC
    # já tinha corrigido; esta cópia não. Portado em 2026-09-24.
    ch_idx = max(0, int(channel) - 1)
    block = _set_field(block, "MediaTrackIdx", str(ch_idx))
    if seg.get("volume_kf"):
        # quadro da keyframe no domínio do `In` (como o Motion) — `prproj/leitura.py::_volume_no_trecho`
        block = _set_field(block, "EffectFiltersBA", _volume_ba_kf(seg["volume_kf"]))
    elif seg.get("volume_db"):
        block = _set_field(block, "EffectFiltersBA", _volume_ba(float(seg["volume_db"])))
    # VirtualAudioTrackBA: ChannelsBA entry = ch_word por tipo de arquivo, usando o canal
    # EMBARCADO (`channel`, 1..fileCh) — NÃO o índice da track:
    #   STEREO (2ch): 0x4000 | n  → ch1=0x4001, ch2=0x4002  ("Embedded Channel")
    #   POLICANAL (3+ch): n * 0x4000 | 0x01 → ch1=0x4001, ch2=0x8001, … ("1-1/2-2/3-3")
    # Validado byte-a-byte vs DRT de referência "TUDO MONO" (canais selecionados à mão).
    ch_1based = channel
    ch_word = (0x4000 | ch_1based) if (_ch == 2) else (ch_1based * 0x4000 | 0x01)
    vatba = re.search(r"<VirtualAudioTrackBA>([0-9a-fA-F]+)</VirtualAudioTrackBA>", block)
    if vatba:
        old_ba = vatba.group(1)
        old_bytes = bytes.fromhex(old_ba)
        KEY_CHAN = "ChannelsBA".encode("utf-16-be")
        ci = old_bytes.find(KEY_CHAN)
        if ci >= 0:
            import struct as _s
            entry_off = ci + len(KEY_CHAN) + 17
            if entry_off + 4 <= len(old_bytes):
                new_bytes = bytearray(old_bytes)
                _s.pack_into(">I", new_bytes, entry_off, ch_word)
                block = block.replace(
                    f"<VirtualAudioTrackBA>{old_ba}</VirtualAudioTrackBA>",
                    f"<VirtualAudioTrackBA>{bytes(new_bytes).hex()}</VirtualAudioTrackBA>",
                    1,
                )
    if mdur and abs(sr - 1.0) > 1e-6 and (seg.get("prproj") or {}).get("audio"):
        # velocidade constante: o mapa do Resolve 19 (`build_audio_speed_timemap`, gabarito 2026-10-03).
        # Só no áudio do Premiere (o caso medido: velocidade constante, sem reverso nem conform). O
        # áudio do Avid segue como era — lá o speed_ratio pode levar conform e reverso, sem medida
        # (revisão de código 2026-10-03).
        block = _set_field(block, "MediaTimemapBA",
                           build_audio_speed_timemap(mdur, _taxa_exata(_TL_FPS), sr))
    elif mdur:
        block = _set_field(block, "MediaTimemapBA",
                           timemap_encode({"kind": "const", "tag": 0x02, "value": mdur}))
    fb = _xml_field(block, "FieldsBlob")
    if fb:
        block = _set_field(block, "FieldsBlob", _patch_fieldsblob_start(fb, start))
    if pan:
        block = _com_pan(block, pan)
    return block


#: o `EffectFiltersBA` do pan do clipe de áudio, como o Resolve 21.1 o grava (`AudioPan` pela API + Export DRT,
#: 2026-10-28): 23 bytes fixos e o pan em double LE no fim (−100 = esquerda, +100 = direita).
_PAN_CABECA = bytes.fromhex("0000000200000017800a140890014a0f08601a0b0a0911")


def _com_pan(block: str, pan: float) -> str:
    """O clipe com o pan (−100…100) no `EffectFiltersBA`, logo depois do `PriorityIndex` (onde o Resolve o põe)."""
    import struct
    campo = "<EffectFiltersBA>" + (_PAN_CABECA + struct.pack("<d", float(pan))).hex() + "</EffectFiltersBA>"
    # ⛔ a forma do molde já traz um `<EffectFiltersBA/>` VAZIO: acrescentar outro ao lado deixava o vazio por último, e
    # o Resolve ficava com ele (pan 0 — medido 2026-10-28). Troca-se o que existir, aberto ou vazio.
    if re.search(r"<EffectFiltersBA\s*/>|<EffectFiltersBA>", block):
        return re.sub(r"<EffectFiltersBA\s*/>|<EffectFiltersBA>[0-9a-fA-F]*</EffectFiltersBA>", lambda m: campo, block, count=1)
    return re.sub(r"(<PriorityIndex>[^<]*</PriorityIndex>)(\s*)", lambda m: m.group(1) + m.group(2) + campo + m.group(2),
                  block, count=1)


# --------------------------------------------------------------------------- #
# Transições
# --------------------------------------------------------------------------- #
def _transition_overrides(segments: list, matched: dict):
    """Traduz transições do AAF (overlap + cutpoint) → modelo do Resolve. Dois casos:

    • CROSS-DISSOLVE (clipe↔clipe): clipes ENCOSTADOS no corte + item Sm2TiTransition entre eles.
      A encurta p/ terminar no corte, B começa no corte (start/in/dur override).
    • FADE (clipe↔gap/borda): só UM clipe real; ele fica INTACTO e a transição SOBREPÕE a borda.
      Fade-IN (gap→trans→clipe) = item ANTES do clipe, Start=início do clipe, Align=1.
      Fade-OUT (clipe→trans→gap) = item DEPOIS do clipe, Start=fim−L, Align=3.
      O `timeline_tc_in` do segmento de transição AAF já é o Start correto nos dois casos
      (fade-in: =início do clipe; fade-out: =fim_do_clipe−L, pela contabilidade de overlap).

    Devolve mapas por índice de segmento:
      dur_ovr/start_ovr/in_ovr : overrides de geometria do clipe (só cross-dissolve)
      trans_after  : {idx_A: (start_abs, dur, align)} — cross-dissolve após o clipe A
      fade_before  : {idx_clipe: (start_abs, L)} — fade-IN, item ANTES do clipe (align=1)
      fade_after   : {idx_clipe: (start_abs, L)} — fade-OUT, item DEPOIS do clipe (align=3)
    """
    by_tr: dict[int, list] = {}
    for i, s in enumerate(segments or []):
        if not s:
            continue
        by_tr.setdefault(int(s.get("track") or 1), []).append((i, s))
    def _tf(s):
        return _tc_to_frames(s.get("timeline_tc_in") or "00:00:00:00")
    seg_by_idx = {i: s for i, s in enumerate(segments or [])}
    left_cut: dict[int, int] = {}    # clipe → frame do corte na borda ESQUERDA (é B de uma trans)
    right_cut: dict[int, int] = {}   # clipe → frame do corte na borda DIREITA (é A de uma trans)
    trans_after: dict[int, tuple] = {}
    fade_before: dict[int, tuple] = {}
    fade_after: dict[int, tuple] = {}
    for lst in by_tr.values():
        lst = sorted(lst, key=lambda x: _tf(x[1]))
        for pos, (i, s) in enumerate(lst):
            if not s.get("is_transition"):
                continue
            L = int(s.get("duration_frames") or 0)
            if L <= 0:
                continue
            C = int(s.get("cutpoint") if s.get("cutpoint") is not None else (L // 2))
            T_in = _tf(s)
            cut = T_in + C
            start_abs = T_in + _TIMELINE_OFFSET_FRAMES
            # Vizinho ADJACENTE (pula só outras transições). Classifica o lado:
            #   ("clip", j) = clipe real casado (cross-dissolve)
            #   ("empty", None) = gap ou borda da timeline → lado vazio (FADE)
            #   ("unmatched", None) = clipe sem match → não renderizável (ignora a transição)
            # NÃO pular gaps: um gap entre dois clipes não é parceiro de dissolve; emparelhar
            # através dele juntaria um fade-out + fade-in num cross-dissolve FALSO.
            # ⛔ E o vazio pode não vir como segmento: o AAF do Avid não traz o filler de uma trilha de cima (PRODUCAO-A,
            # 2026-10-19: o título da V3 com fade-out e o próximo plano da V3 SEIS minutos depois viraram um dissolve, e o
            # plano esticou para trás até o corte, cobrindo a V1 e a V2). Parceiro só o que ENCOSTA na transição no tempo.
            def _adj(seq, antes):
                for j, sj in seq:
                    if sj.get("is_transition"):
                        continue
                    if sj.get("is_gap"):
                        return ("empty", None)
                    ini_j = _tf(sj)
                    if (ini_j + int(sj.get("duration_frames") or 0) < T_in) if antes else (ini_j > T_in + L):
                        return ("empty", None)
                    if j not in matched:
                        return ("unmatched", None)
                    return ("clip", j)
                return ("empty", None)   # borda da timeline = vazio
            ak, aj = _adj(list(reversed(lst[:pos])), True)
            bk, bj = _adj(lst[pos + 1:], False)
            if ak == "clip" and bk == "clip":
                # CROSS-DISSOLVE entre dois clipes reais.
                right_cut[aj] = cut       # A termina no corte
                left_cut[bj] = cut        # B começa no corte
                # AlignmentType (confirmado em DRT nativo): o Resolve HONRA o Start explícito → o
                # alinhamento é só rótulo. 1 = toda DEPOIS do corte (cutpoint=0); 3 = toda ANTES
                # (cutpoint=L); 2 = qualquer outra (centrada OU assimétrica — assimetria no Start).
                align = 1 if C <= 0 else (3 if C >= L else 2)
                trans_after[aj] = (start_abs, L, align)
            elif ak == "clip" and bk == "empty":
                fade_after[aj] = (start_abs, L)     # clipe→vazio = fade-OUT (align=3)
            elif ak == "empty" and bk == "clip":
                fade_before[bj] = (start_abs, L)    # vazio→clipe = fade-IN (align=1)
            # else: vizinho sem match dos dois lados, ou vazio↔vazio → ignora.

    # Deriva os overrides por clipe combinando os cortes esquerdo/direito (lida com transição
    # nos dois lados do mesmo clipe). Fades NÃO mexem na geometria do clipe.
    dur_ovr, start_ovr, in_ovr = {}, {}, {}
    for i in set(left_cut) | set(right_cut):
        s = seg_by_idx.get(i) or {}
        orig_start = _tf(s)
        orig_end = orig_start + int(s.get("duration_frames") or 0)
        new_start = left_cut.get(i, orig_start)
        new_end = right_cut.get(i, orig_end)
        if i in left_cut:
            start_ovr[i] = new_start
            in_ovr[i] = new_start - orig_start    # frames de timeline que o início avançou
        dur_ovr[i] = max(1, new_end - new_start)
    return dur_ovr, start_ovr, in_ovr, trans_after, fade_before, fade_after


def _sem_sobra(segments: list, matched: dict, trans_after: dict, start_ovr: dict, dur_ovr: dict,
               in_ovr: dict, timeline_fps: float) -> list[tuple[int, int]]:
    """Os cross-dissolves de vídeo cujo plano A NÃO tem mídia depois do fim: `[(índice de A, quadros que faltam)]`.

    ⛔ MEDIDO no Resolve 19.1.4.11 (Windows, 2026-10-29, banco drt-drp/estruturas.md): a cauda de A além do último quadro
    do arquivo importa normal, mas o RENDER falha no corte ("Full resolution media not found") — o editor só descobre na
    entrega. Sem sobra em B o Resolve segura o 1º quadro: não quebra, não entra aqui. A edição NÃO muda (memória
    `nao-alterar-frames-da-edicao`): o plano ganha marcador e a tela conta (decisão do autor, 2026-10-29). Só velocidade
    100 %: com velocidade o ponto na fonte é outra conta, e o caso não foi medido."""
    faltam = []
    for i, (st, L, _al) in trans_after.items():
        s = segments[i] if 0 <= i < len(segments) else {}
        p = matched.get(i)
        if not p or s.get("is_audio") or s.get("has_motion_effect") \
                or abs(float(s.get("speed_ratio") or 1.0) - 1.0) > 1e-6:
            continue
        nb, fps, _tc = _media_meta(p)
        if not nb:
            continue
        razao = (fps / timeline_fps) if fps and timeline_fps else 1.0
        fim_tl = start_ovr.get(i, _tc_to_frames(s.get("timeline_tc_in") or "00:00:00:00")) + dur_ovr.get(
            i, int(s.get("duration_frames") or 0)) + _TIMELINE_OFFSET_FRAMES
        cauda = st + L - fim_tl                      # quadros de A que a transição usa DEPOIS do fim do plano
        usado = int(s.get("source_start_frames") or 0) + round((in_ovr.get(i, 0) + dur_ovr.get(
            i, int(s.get("duration_frames") or 0))) * razao)
        falta = usado + round(cauda * razao) - int(nb)
        if cauda > 0 and falta > 0:
            faltam.append((i, falta))
    return faltam


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_drt(segments: list, match_results: list, output_drt: str,
              skeleton_path: str | None = None, timeline_name: str | None = None,
              ramp_mode: str = "adaptive", timeline_fps: float = 24.0,
              interlaced: bool = False, offline: dict | None = None,
              notas: list | None = None, sinais: list | None = None,
              marcar: bool = False, colorir: bool = False,
              codigo_de_cores: dict | None = None,
              timeline_size: tuple[int, int] | None = None,
              timeline_start_frames: int | None = None, andamento=None) -> dict:
    """Gera `output_drt` a partir de `segments` + `match_results` do app, SEM template
    do usuário. Regenera o media pool (1 clipe por arquivo casado) e as tracks de
    VÍDEO e ÁUDIO (cortes + TC + In + velocidade + relink) a partir dos matches.

    `ramp_mode`: "adaptive" (poucos keyframes lineares, frame-exato — default) ou "dense"
    (N=159 fixo). Ver docs/resolve-speed-ramp.md.
    `timeline_fps`: fps da TIMELINE do AAF (ex.: 29.97). A contagem de posição/TC e o
    offset de 01:00:00:00 dependem da taxa NOMINAL da timeline (parser gera o TC non-drop
    nessa base) — antes era fixo em 24, o que escalava errado timelines 29.97/25/30/etc.

    `offline`: `{caminho: {nb, fps, tc, audio_sr, audio_canais}}` para arquivos que NÃO
    estão neste disco — o caso normal de quem edita offline com mídia gerenciada e manda a
    timeline para o colorista, que tem os originais. O clipe entra no DRT apontando para o
    arquivo original (que o Resolve mostra offline até religar), e os metadados que viriam
    do `ffprobe` vêm do Avid: TC de origem, duração, fps. Sem isto o clipe sumia do DRT.

    `andamento(feitos, total, atual, detalhe)`: chamado a cada arquivo do pool e a cada plano da
    timeline (pedido do autor, 2026-10-04: o "montando a timeline" do PRODB não é rápido, nem no
    Mac nem no Windows, e a barra só girava). `atual` = o arquivo, `detalhe` = o que está sendo escrito.
    """
    _semear_offline(offline)
    try:
        return _build_drt(segments, match_results, output_drt, skeleton_path, timeline_name,
                          ramp_mode, timeline_fps, interlaced, notas, sinais, marcar, colorir,
                          codigo_de_cores, timeline_size, timeline_start_frames, andamento)
    finally:
        for p in (offline or {}):
            _META_CACHE.pop(p, None)
            _META_CACHE_A.pop(p, None)
            _META_CACHE_OFFLINE.discard(_abs(p))


#: A mesa do Fairlight (`FLStudioModelBA`, no `FieldsBlob` da `Sm2Sequence`): o Resolve RESPEITA a
#: que vem no DRT (medido 2026-10-03, Resolve 21.1). A do esqueleto (Resolve 19) é de 16 trilhas:
#: da 17ª em diante as trilhas entravam sem saída — no Bus Assign, sem nada (ou "B1s", que também
#: não chega ao master). A de 99 é a de uma timeline criada no próprio Resolve com 99 trilhas
#: (todas "B1o"); uma mesa MAIOR que a timeline serve (12 trilhas com ela: as 12 em B1o).
#: ⭐ A mesa é a do Resolve 19 (o piso; regra do autor: formato que muda entre versões = o do 19, que o
#: 21 atualiza ao abrir). Colhida 2026-10-03 no 19.0.0b.59 (Windows): timeline vazia + 99 trilhas mono
#: pela API (`AddTrack`), exportada em DRT. Conferida pelo autor no filme do PRODB (38 trilhas):
#: todas em Bus 1 e o som chega ao master. A do 21 (`fairlight_r21_mesa99.bin`, d49b7ee) saiu.
TRILHAS_NA_MESA_DO_ESQUELETO = 16
MESA_99 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fairlight_r19_mesa99.bin")
_CHAVE_MESA = "FLStudioModelBA".encode("utf-16-be")


def _mesa_de_99(blob: bytes) -> bytes | None:
    """O `FieldsBlob` da sequência (QVariantMap, sem compressão) com a mesa de 99 trilhas no lugar
    da do esqueleto. `None` se a chave não estiver lá."""
    import struct as _st
    j = blob.find(_CHAVE_MESA)
    if j < 0:
        return None
    j += len(_CHAVE_MESA)
    if _st.unpack(">I", blob[j:j + 4])[0] != 12:          # QVariant QByteArray
        return None
    n = _st.unpack(">I", blob[j + 5:j + 9])[0]
    with open(MESA_99, "rb") as f:
        mesa = f.read()                                    # qCompress: u32 tamanho + zlib
    return blob[:j + 5] + _st.pack(">I", len(mesa)) + mesa + blob[j + 9 + n:]


#: Código de taxa no `SequenceSetup` = a PARTE INTEIRA da taxa. Medido 2026-10-03 no Resolve
#: 21.1: timelines vazias em cada taxa exportadas em DRT (as fracionárias de um projeto novo, porque
#: a API não aceita taxa fracionária numa timeline de projeto existente): 23,976 → 23, 24, 25,
#: 29,97 → 29, 30, 47,952 → 47, 48, 50, 59,94 → 59, 60. Fora da tabela: o código fica o do
#: esqueleto (23,976) e o `_build_drt` AVISA — antes o aviso era descartado e uma sequência a 25
#: abria a 23,976 sem ninguém saber (revisão de código, 2026-10-03).
_CODIGO_TAXA_SETUP = {(24, True): 23, (24, False): 24, (25, False): 25, (30, True): 29,
                      (30, False): 30, (48, True): 47, (48, False): 48, (50, False): 50,
                      (60, True): 59, (60, False): 60}


def _patch_sequence_setup(raw: bytes, w: int | None, h: int | None,
                          fps: float | None) -> tuple[bytes, bool]:
    """Resolução e taxa da TIMELINE no `SequenceSetup` (QVariantMap do `FieldsBlob` do
    `Sm2Sequence`, dentro do clipe da timeline). É daqui que o Resolve tira a configuração
    própria da timeline ao importar o DRT — NÃO do `Body` (medido 2026-10-02, bissecção em 13
    variantes no Resolve 21.1; banco `drt-drp/estruturas.md`). O esqueleto é 1920×1080 a
    23,976: sem isto, toda timeline importada nasce assim, qualquer que seja a origem.
    Largura/altura aparecem DUAS vezes (u64 BE, em par); a taxa é um u64 20 bytes depois do 1º
    par. O tamanho do blob não muda. Devolve (blob, taxa_conhecida)."""
    import struct
    k = "SequenceSetup".encode("utf-16-be")
    i = raw.find(k)
    if i < 0 or not (w and h):
        return raw, False
    i += len(k)
    if raw[i:i + 4] != b"\x00\x00\x00\x0c":
        return raw, False
    n = struct.unpack(">I", raw[i + 5:i + 9])[0]
    ini = i + 9
    ss = bytearray(raw[ini:ini + n])
    alvo = struct.pack(">QQ", 1920, 1080)        # o par do esqueleto
    primeiro, j = None, 0
    while (j := ss.find(alvo, j)) >= 0:
        primeiro = j if primeiro is None else primeiro
        ss[j:j + 16] = struct.pack(">QQ", int(w), int(h))
        j += 16
    conhecida = False
    if primeiro is not None and fps:
        cod = _CODIGO_TAXA_SETUP.get((max(1, round(fps)), abs(fps - round(fps)) > 1e-3))
        if cod is not None:
            p = primeiro + 16 + 20
            ss[p:p + 8] = struct.pack(">Q", cod)
            conhecida = True
    return raw[:ini] + bytes(ss) + raw[ini + n:], conhecida


def _taxa_exata(fps: float) -> float:
    """23.976 → 24000/1001 (e as demais NTSC). A bin do Avid guarda a taxa ARREDONDADA; o
    Resolve grava a exata. Medido no DRT nativo do Resolve 19 da mesma timeline: 132203
    frames de TC viram `MediaStartTime` 5513,9668 s (÷ 24000/1001), contra 5513,9723 s
    (÷ 23,976) — 0,13 frame, o bastante para um arredondamento cair no frame vizinho."""
    f = float(fps or 0)
    nominal = round(f)
    if nominal and abs(f - nominal) > 1e-3 and abs(f - nominal * 1000 / 1001) < 5e-3:
        return nominal * 1000 / 1001
    return f


def _semear_offline(offline: dict | None) -> None:
    """Põe os metadados do Avid nos caches que o `ffprobe` preencheria.

    ⚠️ É o único ponto de entrada: `_media_meta`/`_audio_meta` consultam o cache ANTES de
    rodar o `ffprobe`, então todo o resto do writer trata o clipe offline exatamente como
    trataria o online — o que não pode é o `ffprobe` falhar num arquivo que não existe e o
    clipe sair com TC e duração da forma do esqueleto.
    """
    for p, m in (offline or {}).items():
        _META_CACHE_OFFLINE.add(_abs(p))
        fps = _taxa_exata(m.get("fps") or 0) or None
        nb = int(m.get("nb") or 0) or None
        _META_CACHE[p] = (nb, fps, m.get("tc"))
        sr = int(m.get("audio_sr") or 48000)
        dur = (nb / fps) if (nb and fps) else None
        # Segundos na taxa EXATA — o mesmo cálculo que o vídeo faz a partir do TC. ⭐ `fps_tc` (de `referencia_offline`):
        # o TC de um master SÓ DE SOM conta na taxa do PROJETO — o `PATÃO DRONE` (24 qps num projeto 23,976) chegava ao
        # Resolve 22 s antes, 06:13:49:02 em vez de 06:14:11:13 (PRODUCAO-A, 2026-11-24).
        fps_tc = _taxa_exata(m.get("fps_tc") or 0) or fps
        inicio = (_tc_to_frames(m["tc"], round(fps_tc)) / fps_tc) if (m.get("tc") and fps_tc) else 0.0
        _META_CACHE_A[p] = (inicio, dur, sr, int(m.get("audio_canais") or 1) or 1,
                            int(round(dur * sr)) if dur else None)


_MARCADORES_DA_TIMELINE = re.compile(
    r"\s*<Element>\s*<Sm2SequenceLockableBlob\b.*?</Sm2SequenceLockableBlob>\s*</Element>", re.DOTALL)


def sem_marcadores_da_timeline(project_xml: str) -> str:
    """Tira do `project.xml` os MARCADORES DE TIMELINE herdados do esqueleto.

    ⛔ Medido em 2026-09-25 (Resolve Studio 19.0.0b.59; o autor, no Windows e num Mac pela rede):
    TODA timeline que o De Lá Pra Cá gerava chegava com os 23 marcadores da PRODA_CORTE ("pn - usuario-c", "sonorizar cena"…), até num projeto zerado. Eles NÃO moram na sequência
    (`SeqContainer`) nem no clipe da timeline: moram num `Sm2SequenceLockableBlob` do
    `project.xml` (`BlobOwner` = o `Sm2Sequence`), com um `BlobData` comprimido em **zstd** e
    o texto em UTF-8 lá dentro. Por isso a busca por texto, hex e zlib não achava nada. O
    esqueleto foi feito de uma PRODA_CORTE nativa, e o writer copiava esse `project.xml`
    inteiro. Sem o item, o Resolve abre o DRT normalmente e a timeline vem sem marcadores
    (variação F, conferida pelo autor).
    """
    return _MARCADORES_DA_TIMELINE.sub("", project_xml)


#: Sondagens simultâneas (processos do ffprobe esperando disco).
#: ⭐ MEDIDO 2026-10-04 (Windows, filme de 588 planos, originais ARRIRAW num HD USB, disco frio = HDs
#: ejetados e replugados): análise em série 301 s; 4 simultâneas 267 s, nenhum estouro; 8 simultâneas
#: 233 s, mas 5 ARRIRAW passaram do limite de 60 s (refeitos em série). 4: o disco não engasga.
SONDAGENS_SIMULTANEAS = 4


def _sondar_em_paralelo(caminhos: list[str], aviso=None) -> list[str]:
    """Enche os caches (`_media_meta`, `_formato_meta`, `_raster_arriraw`, `_audio_meta`) de cada
    arquivo — as mesmas sondagens que o laço do pool faria em série. `aviso(caminho)` a cada arquivo
    pronto, na thread de quem chamou: se ele LANÇA (o editor cancelou), as que faltam são descartadas
    e o erro sobe. Quem estoura o tempo é refeito em série no fim; devolve os que nem assim
    responderam (viram aviso: o disco não respondeu)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def sondar(p: str) -> str:
        _media_meta(p)
        _formato_meta(p)
        _raster_arriraw(p)
        _audio_meta(p)
        return p

    if not caminhos:
        return []
    _SONDA_LENTA.difference_update(caminhos)     # lento numa importação antiga não vale nesta
    ex = ThreadPoolExecutor(max_workers=min(SONDAGENS_SIMULTANEAS, len(caminhos)))
    lentos: list[str] = []
    try:
        for fut in as_completed([ex.submit(sondar, p) for p in caminhos]):
            p = fut.result()
            if p in _SONDA_LENTA:
                lentos.append(p)
                continue
            if aviso is not None:
                aviso(p)
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    # Os que estouraram o tempo, de novo, UM POR VEZ (sem disputa pelo disco)
    for p in lentos:
        _SONDA_LENTA.discard(p)
        sondar(p)
        if aviso is not None:
            aviso(p)
    return [p for p in lentos if p in _SONDA_LENTA]


def _build_drt(segments: list, match_results: list, output_drt: str,
               skeleton_path: str | None, timeline_name: str | None,
               ramp_mode: str, timeline_fps: float, interlaced: bool,
               notas: list | None = None, sinais: list | None = None,
               marcar: bool = False, colorir: bool = False,
               codigo_de_cores: dict | None = None,
               timeline_size: tuple[int, int] | None = None,
               timeline_start_frames: int | None = None, andamento=None) -> dict:
    global _RAMP_MODE, _NOMINAL_FPS, _TIMELINE_OFFSET_FRAMES, _TL_FPS
    _RAMP_MODE = ramp_mode if ramp_mode in ("adaptive", "dense") else "adaptive"
    _TL_FPS = float(timeline_fps or 24.0)
    # Base NOMINAL non-drop da timeline (24, 25, 30, 50, 60…) e offset de 01:00:00:00.
    _NOMINAL_FPS = max(1, round(float(timeline_fps or 24.0)))
    _TIMELINE_OFFSET_FRAMES = 3600 * _NOMINAL_FPS
    if timeline_start_frames is not None:
        # O TC de início que VEIO DA ORIGEM (o `MZ.ZeroPoint` da sequência do Premiere; ausente = 0).
        # Antes, toda timeline nascia em 01:00:00:00 e a referência do PRODB, com burn-in desde
        # 00:00:00:00, ficava uma hora fora — o manual da CASA-POS-1 pede o MESMO TC. Ele vale no `Start`
        # dos clipes e no `MediaExtents` da timeline (o gabarito do R02, do Resolve, que começa em 0:
        # MediaExtents (0,0, dur) e clipes em 0). Desde 2026-10-28 (autor) também o TC da sequência do
        # AVID — antes ela nascia sempre em 01:00:00:00: o mesmo clipe com dois TCs (banco, B041/B062).
        _TIMELINE_OFFSET_FRAMES = max(0, int(timeline_start_frames))
    skeleton_path = skeleton_path or _skeleton_path()
    with zipfile.ZipFile(skeleton_path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    seq_name = next(n for n in files if "SeqContainer" in n)
    # MpFolder que contém os clipes do pool (pode ser Master/MpFolder.xml ou um
    # subfolder, conforme o export do esqueleto)
    pool_name = next((n for n in files
                      if "MpFolder.xml" in n and b"Sm2MpVideoClip" in files[n]),
                     next(n for n in files if "MpFolder.xml" in n))
    seq = files[seq_name].decode("utf-8", "replace")
    pool = files[pool_name].decode("utf-8", "replace")

    # Formas (shapes)
    tl_v_shape = re.search(r"<Sm2TiVideoClip\b.*?</Sm2TiVideoClip>", seq, re.DOTALL).group(0)
    vtv = re.search(r"<VideoTrackVec>.*?</VideoTrackVec>", seq, re.DOTALL).group(0)
    track_shape = re.search(r"<Sm2TiTrack\b.*?</Sm2TiTrack>", vtv, re.DOTALL).group(0)
    track_shape = re.sub(r"<Items>.*?</Items>", "<Items></Items>", track_shape,
                         count=1, flags=re.DOTALL)
    pool_v_shape = re.search(r"<Sm2MpVideoClip\b.*?</Sm2MpVideoClip>", pool, re.DOTALL).group(0)
    # Formas de ÁUDIO
    pool_a_m = re.search(r"<Sm2MpAudioClip\b.*?</Sm2MpAudioClip>", pool, re.DOTALL)
    tl_a_m = re.search(r"<Sm2TiAudioClip\b.*?</Sm2TiAudioClip>", seq, re.DOTALL)
    atv = re.search(r"<AudioTrackVec>.*?</AudioTrackVec>", seq, re.DOTALL).group(0)
    a_track_shape = re.search(r"<Sm2TiTrack\b.*?</Sm2TiTrack>", atv, re.DOTALL).group(0)
    a_track_shape = re.sub(r"<Items>.*?</Items>", "<Items></Items>", a_track_shape,
                           count=1, flags=re.DOTALL)

    # matched_path por segment_index (ignora rejeitados)
    matched: dict[int, str] = {}
    # correção de offset de fonte (frames, domínio nativo) achada pelo match visual
    offc_by_index: dict[int, int] = {}
    for r in (match_results or []):
        if r and r.get("matched_path") and not r.get("rejected"):
            matched[r.get("segment_index")] = r["matched_path"]
            offc_by_index[r.get("segment_index")] = int(r.get("source_offset_correction") or 0)

    # Segmentos de VÍDEO casados
    vsegs = []
    for i, s in enumerate(segments or []):
        if not s or s.get("is_audio") or s.get("is_gap") or s.get("is_transition"):
            continue
        nm = (s.get("clip_name") or "").strip()
        if not nm or nm.startswith("("):
            continue
        # ⚠️ Vídeo DESLIGADO no Avid não entra — é o que o Resolve 19 faz importando o AAF da
        # mesma timeline (medido 2026-09-24: o V2 desligado não vem; o SOM desligado vem, com
        # `Flags=2`). Um clipe de vídeo numa trilha de cima "aceso por engano" mudaria a
        # imagem da edição, e isso não se arrisca. A Carta Aberta continua levando os dois.
        if s.get("disabled"):
            continue
        if matched.get(i):
            vsegs.append((i, s))

    # Segmentos de ÁUDIO casados (antes do pool: o andamento precisa do total)
    asegs = []
    for i, s in enumerate(segments or []):
        if not s or not s.get("is_audio") or s.get("is_gap") or s.get("is_transition"):
            continue
        nm = (s.get("clip_name") or "").strip()
        if not nm or nm.startswith("("):
            continue
        if matched.get(i):
            asegs.append((i, s))

    # O andamento: um contador só para os arquivos do pool (onde mora o custo, as sondagens do
    # ffprobe) e os planos da timeline.
    n_pool = len({matched[i] for i, _s in vsegs} | {matched[i] for i, _s in asegs})
    passos = {"feitos": 0, "total": n_pool + len(vsegs) + len(asegs)}

    def passo(atual: str = "", detalhe: str = "") -> None:
        if andamento is not None:
            andamento(passos["feitos"], passos["total"], atual, detalhe)
        passos["feitos"] += 1

    # As sondagens do pool EM PARALELO (o laço abaixo só lê os caches): medido 2026-10-04 no
    # PRODB (Windows), 39 de 40 s do "montando" eram 923 ffprobe em série, ~37 ms cada.
    sem_resposta = _sondar_em_paralelo(list(dict.fromkeys([matched[i] for i, _s in vsegs] + [matched[i] for i, _s in asegs])),
                        lambda p: passo(p, "media pool: o formato, o timecode, a duração e o som do arquivo"))

    # Pool: 1 clipe por arquivo único
    path_to_db: dict[str, str] = {}
    pool_elems = []
    for i, _s in vsegs:
        p = matched[i]
        if p in path_to_db:
            continue
        db = _new_id()
        path_to_db[p] = db
        # A forma do esqueleto é MXF: só serve à .mxf. O resto nasce da forma NATIVA do
        # Resolve 19 para mp4/mov (ver `_ajustar_formato_nativo`).
        forma = pool_v_shape if (_e_mxf(p) and not _e_arriraw(p)) \
            else _formas_nativas()[_familia(p)]
        pool_elems.append("<Element>" + _make_pool_clip(
            forma, _nome(p), db, _new_id(), p) + "</Element>")

    # Pool de áudio (1 clipe por arquivo único)
    apath_to_db: dict[str, str] = {}
    apool_elems = []
    if pool_a_m:
        for i, _s in asegs:
            p = matched[i]
            # Áudio EMBUTIDO em arquivo de VÍDEO (.mp4/.mov): o Resolve usa o MESMO pool clip
            # do VÍDEO (Sm2MpVideoClip) p/ vídeo E áudio — o clipe de áudio da timeline aponta
            # o DbId do vídeo (confirmado num DRT nativo: A1/A2 da câmera → Sm2MpVideoClip). Um
            # Sm2MpAudioClip separado p/ o .mp4 não tem essência de áudio → mudo. Só arquivo de
            # ÁUDIO PURO (WAV/etc.) ganha Sm2MpAudioClip próprio.
            if p in path_to_db or p in apath_to_db:
                continue
            db = _new_id()
            if _arquivo_de_video(p):
                # Arquivo de VÍDEO usado SÓ no áudio (MP4 de música/efeito sonoro, comum no
                # Premiere — 18 no PRODB): ganha o item de VÍDEO do pool, como o Resolve faz; um
                # Sm2MpAudioClip para ele não tem essência de áudio e o clipe fica MUDO (medido
                # 2026-10-04: a "Obra Y" do Artista X, A11/A12, não tocava).
                path_to_db[p] = db
                forma = pool_v_shape if (_e_mxf(p) and not _e_arriraw(p)) \
                    else _formas_nativas()[_familia(p)]
                pool_elems.append("<Element>" + _make_pool_clip(
                    forma, _nome(p), db, _new_id(), p) + "</Element>")
                continue
            apath_to_db[p] = db
            apool_elems.append("<Element>" + _make_audio_pool_clip(
                pool_a_m.group(0), _nome(p), db, _new_id(), p) + "</Element>")

    # ⚠️⚠️ O clipe da TIMELINE (`Sm2MpTimelineClip`) pode morar neste MESMO `MediaVec`: num
    # `.drt` do Resolve 19 o pool é uma pasta só (`Master`). Trocar o vetor inteiro apagava a
    # timeline e o DRT não importava nada — a nota do `make_skeleton` do RELINKER registra
    # "os .drt como esqueleto NÃO importavam a timeline". Ele fica, depois dos clipes.
    antigo = re.search(r"<MediaVec>.*?</MediaVec>", pool, re.DOTALL)
    timelines = re.findall(r"<Element>\s*<Sm2MpTimelineClip\b.*?</Sm2MpTimelineClip>\s*</Element>",
                           antigo.group(0) if antigo else "", re.DOTALL)
    new_vec = ("<MediaVec>" + "".join(pool_elems) + "".join(apool_elems) + "".join(timelines)
               + "</MediaVec>")
    pool_new = re.sub(r"<MediaVec>.*?</MediaVec>", lambda _m: new_vec, pool, count=1,
                      flags=re.DOTALL)   # `lambda`: caminhos do Windows (ver `_set_field`)

    # Timeline: clipes por track
    # Transições: encosta os vizinhos no corte e insere o item Sm2TiTransition entre eles.
    # O TÍTULO também é vizinho de verdade: o "PRODUCAO-A" da PRODA tem dissolve de 40 quadros
    # na entrada e na saída (V3). Sem ele aqui, o fade sumia e o título entrava a seco.
    com_titulo = dict(matched)
    com_titulo.update({i: "" for i, s in enumerate(segments or []) if _titulo_do_segmento(s)})
    dur_ovr, start_ovr, in_ovr, trans_after, fade_before, fade_after = \
        _transition_overrides(segments, com_titulo)
    sem_sobra = _sem_sobra(segments, matched, trans_after, start_ovr, dur_ovr, in_ovr, timeline_fps)
    if sem_sobra:
        from notas import _nota
        sinais = list(sinais or []) + [
            _nota(_tc_to_frames(segments[i].get("timeline_tc_in") or "00:00:00:00"),
                  int(segments[i].get("duration_frames") or 1),
                  [[(f"TRANSIÇÃO SEM MÍDIA DEPOIS DO FIM · faltam {q} quadros de "
                     f"{os.path.basename(matched[i])}: o render do Resolve falha no corte", None)]],
                  "refazer", segmento=i)
            for i, q in sem_sobra]
    aviso_sem_sobra = ([f"{len(sem_sobra)} transição(ões) sem mídia depois do fim do plano de saída: o render do "
                        "Resolve falha nesse corte — cada uma tem marcador vermelho; estenda a mídia ou mude a "
                        "transição"] if sem_sobra else [])

    by_track: dict[int, list[str]] = {}
    generated = []
    estabilizar = []                            # o Stabilize do Avid → o estabilizador do Resolve, depois do import
    cor_mc = []                                 # o Color Correction do Avid → os 2 nós do Resolve, depois do import
    clipe_do_segmento: dict[int, str] = {}      # índice do segmento → DbId do clipe (cor local)
    for i, s in vsegs:
        p = matched[i]
        passo(p, f"timeline: o plano na V{int(s.get('track') or 1)}, em {s.get('timeline_tc_in') or ''}"
                 " (corte, velocidade, efeitos)")
        clip = _make_timeline_clip(tl_v_shape, s, path_to_db[p], p,
                                   offset_corr=offc_by_index.get(i, 0),
                                   start_override=start_ovr.get(i),
                                   dur_override=dur_ovr.get(i), in_extra=in_ovr.get(i, 0))
        clipe_do_segmento[i] = re.search(r'DbId="([^"]+)"', clip).group(1)
        t = int(s.get("track") or 1)
        lane = by_track.setdefault(t, [])
        if i in fade_before:                     # fade-IN: item ANTES do clipe
            st, L = fade_before[i]
            lane.append(_make_transition(st, L, align=1, kind="video"))
        lane.append(clip)
        if i in fade_after:                      # fade-OUT: item DEPOIS do clipe
            st, L = fade_after[i]
            lane.append(_make_transition(st, L, align=3, kind="video"))
        if i in trans_after:                     # cross-dissolve: item entre A e B
            st, L, al = trans_after[i]
            lane.append(_make_transition(st, L, al, kind="video"))
        generated.append({
            "name": s["clip_name"],
            "track": int(s.get("track") or 1),
            "start": _tc_to_frames(s["timeline_tc_in"]) + _TIMELINE_OFFSET_FRAMES,
            "duration": int(s["duration_frames"]),
            "path": p,
        })
        plano = _plano_de_estabilizacao(s, clip, p)
        if plano:
            estabilizar.append(plano)
        plano = _plano_de_cor_mc(s, clip, p)
        if plano:
            cor_mc.append(plano)

    titulos, avisos_titulos = _titulos_na_timeline(
        segments, by_track, (dur_ovr, start_ovr, trans_after, fade_before, fade_after))
    burnins = _burnins_na_timeline(segments, by_track, timeline_size or (1920, 1080))
    ajustes = _ajustes_na_timeline(segments, by_track)
    # A cabeça da nota leva o nome do ARQUIVO que o clipe usa na timeline do Resolve (autor, 2026-10-23: o subclipe e o
    # multicam do Avid se desfazem na viagem; o nome deles não serve a quem procura o plano no Resolve).
    arquivo_do_segmento = {i: os.path.basename(str(matched[i]).replace("\\", "/")) for i, _s in vsegs if matched.get(i)}
    # e o clipe de DENTRO de um compound entra recuado na nota do compound (V2.1, V2.2…; `notas_textplus.aninhar`)
    from drp import notas_textplus as _nt
    # e o TC source em TODO segmento (autor, 2026-10-23): o que a leitura não sabia (o .prproj sem o TC do arquivo) sai
    # do TC que o pool recebe do próprio arquivo — o mesmo que o Resolve mostra; sem TC no arquivo, 00:00:00:00.
    tc_do_segmento = {i: _media_meta(matched[i])[1:] for i, _s in vsegs if matched.get(i)}
    # o arquivo casado que NÃO está no disco é offline no Resolve também (o .prproj sem os originais aponta para o
    # caminho antigo; MEDIDO 2026-10-24, PRODC no Mac: 79 vídeos offline e o nome saía branco)
    ausentes = {i for i, _s in vsegs if matched.get(i) and not os.path.isfile(str(matched[i]))}
    trilhas_de_notas = _notas_na_timeline(_nt.aninhar(_com_nome_do_arquivo(notas or [], arquivo_do_segmento,
                                                                        tc_do_segmento, segments, ausentes),
                                                      segments),
                                          by_track, timeline_fps, timeline_size or (1920, 1080))
    n_notas = len(notas or [])
    # Trilha que o chamador pede DESLIGADA (o vídeo de referência, 2026-10-04): a mesma forma da
    # trilha de notas — `<Flags>2`, os clipes ligados.
    trilhas_desligadas = {int(s.get("track") or 1) for s in segments or []
                          if s and s.get("trilha_desligada") and not s.get("is_audio")}

    # A NUMERAÇÃO da origem fica: a trilha vazia (ou só com clipes desligados) entra vazia, em vez
    # de sumir e descer as de cima. ⛔ VISTO 2026-10-04 (PRODB `…ROLO03_COM_REF`, Resolve 19): a
    # V7 do Premiere não tinha clipe que entrasse e a referência (V8) virou V7 — a conferência, o
    # Fusion e os compounds acham o clipe pelo número da trilha da origem, e o editor perde o layout.
    for t in range(1, max((k for k in by_track if k >= 1), default=0)):
        by_track.setdefault(t, [])

    # Reconstrói o VideoTrackVec: 1 track por número de track (ascendente)
    track_elems = []
    for t in sorted(by_track):
        trilha = _make_video_track(track_shape, by_track[t])
        if t in trilhas_de_notas or t in trilhas_desligadas:
            # A TRILHA desligada (medido: o `<Flags>` da trilha vem antes dos `<Items>`).
            trilha = re.sub(r"<Flags>\d+</Flags>", "<Flags>2</Flags>", trilha, count=1)
        track_elems.append("<Element>" + trilha + "</Element>")
    new_vtv = "<VideoTrackVec>" + "".join(track_elems) + "</VideoTrackVec>"
    seq_new = seq.replace(vtv, new_vtv, 1)

    # Canal EMBARCADO por (arquivo, track): cada arquivo distribui seus N canais físicos
    # pelas tracks que ocupa, da track mais baixa p/ a mais alta (track mais baixa = ch1).
    # Reproduz o layout do Avid e bate com o DRT de referência "TUDO MONO". O índice da
    # track NÃO serve como canal — A7 não significa "ler o canal 7" do arquivo.
    apath_tracks: dict[str, list[int]] = {}
    for i, s in asegs:
        p = matched[i]
        tr = int(s.get("track") or 1000)
        apath_tracks.setdefault(p, [])
        if tr not in apath_tracks[p]:
            apath_tracks[p].append(tr)
    for p in apath_tracks:
        apath_tracks[p].sort()
    apath_nch: dict[str, int] = {p: (_audio_meta(p)[3] or 1) for p in apath_tracks}

    def _embedded_channel(path: str, track: int) -> int:
        tracks = apath_tracks.get(path) or [track]
        nch = apath_nch.get(path) or 1
        rank = tracks.index(track) if track in tracks else 0
        return (rank % nch) + 1   # 1-based, cicla se houver mais tracks que canais

    # os canais de cada arquivo que a timeline toca (o par estéreo ganha pan, ver abaixo)
    canais_usados: dict[str, set[int]] = {}
    for i, s in asegs:
        canais_usados.setdefault(matched[i], set()).add(
            int(s.get("canal_arquivo") or 0) or _embedded_channel(matched[i], int(s.get("track") or 1000)))

    # Tracks de ÁUDIO (A1..An por número de track; track fictícia 1000+ → A1 ascendente)
    a_by_track: dict[int, list[str]] = {}
    if asegs and tl_a_m:
        for i, s in asegs:
            p = matched[i]
            passo(p, f"timeline: o som em {s.get('timeline_tc_in') or ''} (canal, volume, fades)")
            tr = int(s.get("track") or 1000)
            # Áudio embutido → DbId do pool de VÍDEO; áudio puro (WAV) → DbId do pool de áudio.
            a_db = path_to_db.get(p) or apath_to_db.get(p)
            # ⭐ Quem SABE o canal ganha do palpite: o leitor de `.avb` lê do `SourceClip` qual
            # trilha do master este clipe toca (`canal_arquivo`). O palpite pela ordem das
            # tracks erra quando o editor usa só alguns canais (2 e 4 em A1/A2 viravam 1 e 2).
            canal = int(s.get("canal_arquivo") or 0) or _embedded_channel(p, tr)
            # ⭐ O par ESTÉREO de um arquivo de 2 canais, com os DOIS na timeline: canal 1 à esquerda, 2 à direita (o
            # layout do próprio arquivo). Sem isto as duas trilhas mono ficavam no CENTRO e o estéreo saía L = R
            # (medido no Resolve 21.1, 2026-10-28, banco B016). Dual mono (o mesmo canal nas duas) e o som direto de
            # 3+ canais seguem no centro.
            pan = ({1: -100.0, 2: 100.0}.get(canal) if apath_nch.get(p) == 2 and canais_usados.get(p) == {1, 2}
                   else None)
            clip = _make_audio_timeline_clip(tl_a_m.group(0), s, a_db, p,
                                             channel=canal,
                                             start_override=start_ovr.get(i),
                                             dur_override=dur_ovr.get(i), in_extra=in_ovr.get(i, 0),
                                             pan=pan)
            lane = a_by_track.setdefault(tr, [])
            if i in fade_before:                 # fade-IN de áudio (Cross Fade 0DB, align=1)
                st, L = fade_before[i]
                lane.append(_make_transition(st, L, align=1, kind="audio"))
            lane.append(clip)
            if i in fade_after:                  # fade-OUT de áudio (align=3)
                st, L = fade_after[i]
                lane.append(_make_transition(st, L, align=3, kind="audio"))
            if i in trans_after:                 # cross-fade entre dois clipes de áudio
                st, L, al = trans_after[i]
                lane.append(_make_transition(st, L, al, kind="audio"))
        # SOLO na trilha (o som da referência, opção A — 2026-10-04): `<Flags>32` na trilha de
        # áudio. Medido no Resolve 21.1: o mesmo DRT exportado antes/depois de apertar o "S" da A2
        # só muda o `<Flags>` dela, de 0 para 32 (a API não expõe solo nem mudo).
        solo = {int(s.get("track") or 1000) for _i, s in asegs if s.get("solo")}

        def _trilha_a(t: int) -> str:
            tr = _make_video_track(a_track_shape, a_by_track[t])
            if t in solo:
                tr = re.sub(r"<Flags>\d+</Flags>", "<Flags>32</Flags>", tr, count=1)
            return tr
        a_track_elems = ["<Element>" + _trilha_a(t) + "</Element>" for t in sorted(a_by_track)]
        new_atv = "<AudioTrackVec>" + "".join(a_track_elems) + "</AudioTrackVec>"
        seq_new = seq_new.replace(atv, new_atv, 1)
    else:
        seq_new = seq_new.replace(atv, _empty_all_items(atv), 1)

    out_files = dict(files)
    blocos, n_marcadores, n_cores = _sinais(sinais or [], clipe_do_segmento, pool_new, marcar, colorir,
                                              codigo_de_cores)
    for n in out_files:
        if n.endswith("project.xml"):
            # Tira os marcadores herdados do esqueleto e põe os NOSSOS (Sinais do Import).
            px = sem_marcadores_da_timeline(out_files[n].decode("utf-8"))
            out_files[n] = _sn.no_project_xml(px, blocos).encode("utf-8")
    out_files[seq_name] = seq_new.encode("utf-8")
    # ⚠️ O pool ANTES do ajuste do Master: no esqueleto do Resolve 19 eles são o MESMO arquivo,
    # e gravar o pool depois apagaria o ajuste do clipe da timeline.
    out_files[pool_name] = pool_new.encode("utf-8")

    # Master/MpFolder.xml = pasta-raiz do media pool; o Sm2MpTimelineClip carrega o FORMATO da
    # timeline (FrameRate + Body), que governa o PLAYBACK. O esqueleto era 23.976 → a timeline
    # reproduzia em 24. Reescreve com os blobs do formato-alvo (catalogados de DRTs nativos);
    # sem catálogo, ao menos atualiza o rótulo FrameRate (display) via framerate_encode.
    fmt = _tl_format(timeline_fps, interlaced)
    tl_rate_blob = fmt[0] if fmt else framerate_encode(_taxa_exata(timeline_fps or 24.0))
    for n in list(out_files):
        if not n.endswith("Master/MpFolder.xml"):
            continue
        txt = out_files[n].decode("utf-8", "replace")

        def _ajustar(m) -> str:
            # ⚠️⚠️ SÓ dentro do clipe da timeline: com o pool na mesma pasta (Resolve 19), o
            # primeiro `<FrameRate>` do arquivo é o de um clipe de mídia, não o da timeline.
            bloco = m.group(0)
            if timeline_name:
                bloco = re.sub(r"<Name>.*?</Name>",
                               lambda _n: "<Name>" + _xml_escape(timeline_name) + "</Name>",
                               bloco, count=1, flags=re.DOTALL)
            # Taxa já igual à do esqueleto → não mexe no formato: os blobs do catálogo foram
            # colhidos no Resolve 20 e não se põem num arquivo de outra versão sem precisar.
            if _xml_field(bloco, "FrameRate") != tl_rate_blob:
                bloco = _set_field(bloco, "FrameRate", tl_rate_blob)
                if fmt:
                    bloco = _set_field(bloco, "Body", fmt[1])
            # O DRT NATIVO do Resolve (que reproduz na fps certa) NÃO tem estes campos no
            # Sm2MpTimelineClip: `IsCustom` (flag de "configurações de timeline customizadas"
            # → faz o Resolve ignorar a fps do formato e cair na do projeto/esqueleto = 24) e
            # `ImportExportMetadataBA` (metadado de import HERDADO do esqueleto → leak: aponta
            # p/ outro .aaf). Remove ambos p/ a timeline-clip ficar igual à nativa.
            # `MediaExtents` do clipe da timeline = (início, duração) em SEGUNDOS, double LE. O
            # início vira o TC inicial na taxa da timeline: o do esqueleto (3603,6 s) é
            # 01:00:00:00 a 23,976 e 01:00:03:14 a 24 (medido 2026-10-02, Resolve 21.1).
            # Em todo caminho que informa o início (Premiere desde 2026-10-02; Avid desde 2026-10-28). Sem
            # ele fica o do esqueleto — que a 24 fps cai 86 quadros adiante (01:00:03:14).
            if timeline_size or timeline_start_frames is not None:
                import struct
                taxa = _taxa_exata(timeline_fps or 24.0)
                fim = max((g["start"] + g["duration"] for g in generated),
                          default=_TIMELINE_OFFSET_FRAMES) - _TIMELINE_OFFSET_FRAMES
                bloco = _set_field(bloco, "MediaExtents", struct.pack(
                    "<dd", _TIMELINE_OFFSET_FRAMES / taxa, max(fim, 0) / taxa).hex())
            fbs_ = re.findall(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", bloco)
            if len(fbs_) > 1 and len(a_by_track) > TRILHAS_NA_MESA_DO_ESQUELETO:
                # Mais de 16 trilhas de áudio: a mesa do Fairlight do esqueleto só roteia 16 — da
                # 17ª em diante o Resolve deixava as trilhas SEM saída (mudas; o medidor anda, o
                # master não). Vai a mesa de 99 trilhas, todas no Bus 1 (ver `_mesa_de_99`).
                novo = _mesa_de_99(bytes.fromhex(fbs_[1]))
                if novo is not None:
                    bloco = bloco.replace(fbs_[1], novo.hex(), 1)
                elif len(a_by_track) > 16:
                    avisos_titulos.append("mais de 16 trilhas de áudio: confira o Bus Assign no Fairlight")
            if len(a_by_track) > 99:
                avisos_titulos.append(f"{len(a_by_track)} trilhas de áudio: a partir da 100ª, sem "
                                      "saída no Bus 1 (Bus Assign › Assign All)")
            if timeline_size:
                fbs = re.findall(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", bloco)
                if len(fbs) > 1:
                    novo, ok = _patch_sequence_setup(bytes.fromhex(fbs[1]), *timeline_size,
                                                     timeline_fps)
                    bloco = bloco.replace(fbs[1], novo.hex(), 1)
                    if not ok:
                        avisos_titulos.append(
                            f"a taxa da timeline ({timeline_fps:g} fps) não é das medidas: o Resolve "
                            "pode abrir a timeline a 23,976 — confira em Timeline Settings")
            bloco = re.sub(r"\s*<IsCustom>.*?</IsCustom>", "", bloco, flags=re.DOTALL)
            bloco = re.sub(r"\s*<ImportExportMetadataBA>.*?</ImportExportMetadataBA>", "",
                           bloco, flags=re.DOTALL)
            return bloco

        txt = re.sub(r"<Sm2MpTimelineClip\b.*?</Sm2MpTimelineClip>", _ajustar, txt, count=1,
                     flags=re.DOTALL)
        out_files[n] = txt.encode("utf-8")

    if andamento is not None:
        andamento(passos["total"], passos["total"], output_drt, "gravando o arquivo da timeline (DRT)")
    Path(output_drt).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_drt, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in out_files.items():
            z.writestr(n, data)

    return {
        "output": output_drt,
        "clips_generated": len(generated),
        "pool_clips": len(path_to_db) + len(apath_to_db),
        "video_tracks": len(by_track),
        "audio_clips": sum(len(v) for v in a_by_track.values()),
        "audio_tracks": len(a_by_track),
        "timeline_name": timeline_name,
        "clips": generated,
        "titulos": titulos,
        "burnins": burnins,
        "ajustes": ajustes,
        "notas": n_notas,
        "marcadores": n_marcadores,
        "segmentos_coloridos": n_cores,
        "transicoes_sem_sobra": len(sem_sobra),
        # o que o painel aplica DEPOIS do import, como as LUTs: `drp.estabilizador` (a casca ainda não)
        "estabilizar": estabilizar,
        "cor_mc": cor_mc,                       # `drp.cor_mc.aplicar_cor_mc`, ANTES das LUTs e da estabilização
        "avisos": [f"o disco não respondeu a tempo ao ler {os.path.basename(p)}: confira o clipe "
                   "(timecode e duração podem ter saído errados)" for p in sem_resposta] + aviso_sem_sobra
                  + avisos_titulos,
    }


def _plano_de_estabilizacao(seg: dict, clip: str, caminho: str) -> dict | None:
    """O Stabilize do Avid de um segmento → `{trilha, quadro, arquivo, inicio, zoom, u}` para `drp.estabilizador`
    (autor, 2026-10-24: chega PRONTA e LIGADA). `quadro` = onde o clipe começa na timeline (é por ele que se acha o
    item); `inicio` = onde o SEGMENTO do Avid começa (a transição pode estender o clipe para trás); `u` = a correção
    do Avid por quadro do segmento, em fração do quadro (`estabilizacao.correcao`). Só sem mudança de velocidade: o
    quadro k do Avid é o quadro k do clipe."""
    from estabilizacao import correcao, dados_do_segmento, traduzivel

    dados = dados_do_segmento(seg)
    if not dados or not traduzivel(seg):
        return None
    try:
        u = correcao(dados)
        start = int(re.search(r"<Start>(-?\d+)</Start>", clip).group(1)) - _TIMELINE_OFFSET_FRAMES
    except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError):
        return None
    return {"trilha": int(seg.get("track") or 1), "quadro": start, "arquivo": _nome(caminho),
            "inicio": _tc_to_frames(seg["timeline_tc_in"]), "zoom": dados["zoom"],
            "u": [[round(x, 7), round(y, 7)] for x, y in u]}


def _plano_de_cor_mc(seg: dict, clip: str, caminho: str) -> dict | None:
    """O Color Correction do Avid que se traduz inteiro (`params.cor_mc`, do AAF ou da bin) → `{trilha, quadro,
    arquivo, sat, curva}` para `drp.cor_mc` (2026-11-20: editável, os 2 nós). Mais de um CC no segmento: só o 1º vai
    (a ordem entre eles não foi medida) — o 2º fica na nota como não traduzido."""
    ccs = [e for e in (seg.get("effects") or []) if isinstance((e.get("params") or {}).get("cor_mc"), dict)]
    if not ccs:
        return None
    try:
        start = int(re.search(r"<Start>(-?\d+)</Start>", clip).group(1)) - _TIMELINE_OFFSET_FRAMES
    except (TypeError, ValueError, AttributeError):
        return None
    for e in ccs[1:]:
        e["reproducible"] = False
    cc = ccs[0]["params"]["cor_mc"]
    return {"trilha": int(seg.get("track") or 1), "quadro": start, "arquivo": _nome(caminho),
            "sat": cc.get("sat"), "curva": cc.get("curva")}


#: As observações de um marcador, uma por linha (a nota do Resolve aceita quebra de linha).
_NOTA_SEP, _NOTA_MAX = "\n", 1000


def _sinais(sinais: list, clipe_do_segmento: dict, pool_xml: str, marcar: bool,
            colorir: bool, codigo: dict | None = None) -> tuple[list[str], int, int]:
    """Os blocos do `project.xml` dos Sinais do Import: UM marcador de timeline por segmento que
    pede atenção (no início dele, com a nota e a palavra-chave DLPC) e a cor LOCAL do clipe desse
    segmento. Só o que tem `cor` (refazer/conferir): o efeito traduzido fica só na trilha de notas.
    `marcar` da nota (a estabilização traduzida) dá o marcador SEM pintar o clipe (autor, 2026-10-24).
    `codigo` = o código de cores da equipe (Ajustes; `sinais.validar_codigo`); sem ele, o de
    fábrica. Devolve (blocos, quantos marcadores, quantos segmentos coloridos)."""
    codigo = _sn.validar_codigo(codigo)
    cores = codigo["cores"]
    vistos: dict[int, dict] = {}
    for n in sinais:
        seg = n.get("segmento")
        if seg is None or seg in vistos:
            continue                             # o 1º pedaço do segmento (a nota pode ser cortada)
        if n.get("cor") in cores:
            vistos[seg] = n
        elif n.get("marcar") in cores:           # só marca: a cor do marcador, o clipe sem cor
            vistos[seg] = dict(n, cor=n["marcar"], so_marcar=True)
    blocos: list[str] = []
    n_cores = 0
    if colorir:
        for seg, n in vistos.items():
            if seg in clipe_do_segmento and not n.get("so_marcar"):   # sem clipe (sem mídia) não há o que pintar
                blocos.append(_sn.cor_local(clipe_do_segmento[seg], cores[n["cor"]]["clipe"]))
                n_cores += 1
    lista = []
    if marcar and vistos:
        # ⚠️ MEDIDO 2026-10-03 (Resolve 21.1, caso R02): o Resolve guarda UM marcador de timeline
        # por quadro — o DRT levou 14 marcadores em 6 quadros e a timeline ficou com 6, perdendo
        # em silêncio os avisos dos planos que começam juntos em outras trilhas. Então os segmentos
        # do mesmo quadro viram UM marcador: a cor mais forte (a ordem do código: distorção,
        # refazer, conferir), o nome dela, e as notas de todos na nota.
        ordem = list(cores)
        por_quadro: dict[int, list] = {}
        for n in vistos.values():
            por_quadro.setdefault(int(n["inicio"]), []).append(n)
        # NOME = o TIPO do problema mais forte (+ quantos outros no quadro); NOTES = todas as
        # observações, uma por linha (autor, 2026-10-04: nome e notas repetiam a mesma coisa).
        for quadro in sorted(por_quadro):
            grupo = sorted(por_quadro[quadro], key=lambda x: ordem.index(x["cor"]))
            linhas = [x for n in grupo for x in ("".join(t for t, _d in linha) for linha in n["linhas"])]
            # O nome é a 1ª linha da DESCRIÇÃO: a cabeça "V01 <clipe>" (notas, 2026-10-06) fica no texto.
            desc = ["".join(t for t, _d in linha) for linha in grupo[0]["linhas"][int(grupo[0].get("cabeca") or 0):]]
            tipo = grupo[0].get("tipo") or (desc[0] if desc else linhas[0] if linhas else _sn.CATEGORIAS.get(
                grupo[0]["cor"], {}).get("rotulo", ""))
            if len(grupo) > 1:
                tipo += f" (+{len(grupo) - 1})"
            lista.append({"quadro": quadro, "cor": cores[grupo[0]["cor"]]["marcador"],
                          "nome": tipo[:120], "nota": _NOTA_SEP.join(linhas)[:_NOTA_MAX],
                          "duracao": 1, "palavras": [codigo["palavra"]]})
        dono = re.search(r'<Sm2Sequence DbId="([^"]+)"', pool_xml)
        if dono:
            blocos.append(_sn.marcadores(dono.group(1), lista))
    return blocos, len(lista), n_cores


#: A trilha de notas (`motor/notas.py`). ⭐ Desde 2026-10-23 em Text+ (`drp/notas_textplus.py`, variante B do lab,
#: decisões do autor): UMA trilha, as notas que se tocam num clipe só, cada nota uma camada. Antes era um Text por nota e
#: uma trilha nova a cada sobreposição (o Anchor "esquerda + topo" medido em 2026-09-27 continua valendo lá dentro).
#: A TRILHA vai desligada (`<Flags>2`), com os clipes ligados: ligar a trilha mostra tudo.
def _com_nome_do_arquivo(notas: list, arquivo_do_segmento: dict, tc_do_segmento: dict | None = None,
                         segmentos: list | None = None, ausentes: set | None = None) -> list:
    """As notas com o NOME da cabeça trocado pelo arquivo do segmento e, quando a leitura não trouxe o TC source, com
    o TC do arquivo (`(fps, tc)` do `_media_meta`) + o ponto de entrada. Cópias: a mesma lista vai aos Sinais."""
    from notas import _src, _tc_para_quadros

    fora = []
    for n in notas:
        i = n.get("segmento")
        info = n.get("cabeca_info")
        if info:
            novo = dict(info)
            if arquivo_do_segmento.get(i):
                # sem a extensão (autor, 2026-10-24): o nome basta para achar o plano
                novo["nome"] = os.path.splitext(arquivo_do_segmento[i])[0]
            s = segmentos[i] if segmentos and isinstance(i, int) and 0 <= i < len(segmentos) else None
            if (s and (s.get("media_ref") or {}).get("local_path") and not arquivo_do_segmento.get(i)) \
                    or i in (ausentes or ()):
                novo["offline"] = True                    # o nome sai VERMELHO na cabeça (autor, 2026-10-24)
            fps, tc = (tc_do_segmento or {}).get(i) or (None, None)
            if not novo.get("src") and s and fps:          # sem o arquivo lido (offline), nada se inventa
                nominal = int(round(float(fps or s.get("source_fps") or 24)))
                ident = {"tc_inicio": _tc_para_quadros(tc, nominal) if tc else 0, "tc_fps": nominal}
                novo["src"] = _src(s, int(s.get("duration_frames") or 0), {"identidade": ident})
            n = {**n, "cabeca_info": novo}
        fora.append(n)
    return fora


def _notas_na_timeline(notas: list, by_track: dict, fps: float = 24.0,
                       quadro: tuple[int, int] = (1920, 1080)) -> set:
    """Uma trilha NOVA acima da mais alta, com um Text+ por grupo de notas que se tocam no tempo; devolve a trilha de
    notas (que o writer desliga). O nome do clipe é o texto corrido: é o que a timeline mostra."""
    if not notas:
        return set()
    from drp import notas_textplus as NT

    trilha = max(by_track or {0: None}) + 1
    lane = by_track.setdefault(trilha, [])
    for g in NT.grupos(notas):
        lane.append(_uniquify(NT.clipe(g, fps, quadro, _TIMELINE_OFFSET_FRAMES)))
    return {trilha}


def _titulo_do_segmento(s: dict | None) -> dict | None:
    """O bloco `titulo` (Carta 1.2) de um segmento de vídeo ligado e com texto; senão `None`."""
    if not s or s.get("is_audio") or s.get("disabled") or not s.get("is_effect"):
        return None
    titulo = next((e.get("params", {}).get("titulo") for e in (s.get("effects") or [])
                   if e.get("category") == "title" and (e.get("params") or {}).get("titulo")), None)
    if not titulo or not any((c.get("texto") or "").strip() for c in titulo.get("caixas") or []):
        return None
    return titulo


def _titulos_na_timeline(segments: list, by_track: dict, transicoes: tuple) -> tuple[int, list[str]]:
    """Cada segmento com um título do Avid (bloco `titulo` do efeito, Carta 1.2) vira um
    gerador "Text" na MESMA trilha e no MESMO trecho (`motor/titulos/resolve.py`), com as
    transições dele (fade e dissolve, como um clipe). O título não tem mídia: não entra no
    pool nem no casamento. Devolve (quantos, avisos)."""
    from titulos import resolve as texto

    dur_ovr, start_ovr, trans_after, fade_before, fade_after = transicoes
    n, avisos = 0, []
    for i, s in enumerate(segments or []):
        titulo = _titulo_do_segmento(s)
        if not titulo:
            # ⛔ Um título do Avid que não pode entrar AVISA (U03, 2026-10-01: pelo AAF ele sumia calado).
            ef = next((e for e in (s or {}).get("effects") or [] if e.get("category") == "title"), None)
            if ef and not s.get("is_audio") and not s.get("disabled"):
                avisos.append(f"título do Avid ({ef.get('label') or ef.get('name') or 'Titler'}) em "
                              f"{s.get('timeline_tc_in')}: sem texto legível — não entrou; conferir")
            continue
        efb, avs = texto.efeitos_do_texto(titulo)
        start = (start_ovr.get(i) if i in start_ovr else _tc_to_frames(s["timeline_tc_in"])) \
            + _TIMELINE_OFFSET_FRAMES
        bloco = _uniquify(texto.forma())
        bloco = _set_field(bloco, "Start", str(start))
        bloco = _set_field(bloco, "Duration", str(int(dur_ovr.get(i, s["duration_frames"]))))
        bloco = _set_field(bloco, "EffectFiltersBA", efb.hex())
        grupo = []
        if i in fade_before:
            grupo.append(_make_transition(*fade_before[i], align=1, kind="video"))
        grupo.append(bloco)
        if i in fade_after:
            grupo.append(_make_transition(*fade_after[i], align=3, kind="video"))
        if i in trans_after:
            st, L, al = trans_after[i]
            grupo.append(_make_transition(st, L, al, kind="video"))
        lane = by_track.setdefault(int(s.get("track") or 1), [])
        # Em ordem de Start: a trilha pode já ter clipes (título sobre imagem na mesma V).
        depois = next((k for k, it in enumerate(lane)
                       if int(_xml_field(it, "Start") or 0) > start), len(lane))
        lane[depois:depois] = grupo
        rotulo = (titulo.get("caixas") or [{}])[0].get("texto", "").replace("\n", " ")[:40]
        avisos += [f"título “{rotulo}”: {a}" for a in avs]
        n += 1
    return n, avisos


_FORMA_AJUSTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ajuste_r19.xml")


def _ajustes_na_timeline(segments: list, by_track: dict) -> int:
    """Cada camada de AJUSTE do Premiere (segmento com `ajuste`, `prproj/leitura.py`) vira um
    "Adjustment Clip" do Resolve na MESMA trilha e no MESMO trecho — a forma nativa do caso U01
    (`ajuste_r19.xml`: um Sm2TiVideoClip sem MediaRef). Sem mídia: não entra no pool nem no
    casamento. A LUT da Lumetri vai no nó DEPOIS do import (o relatório leva o .cube). Devolve quantos."""
    with open(_FORMA_AJUSTE, encoding="utf-8") as f:
        forma = re.search(r"<Sm2TiVideoClip\b.*?</Sm2TiVideoClip>", f.read(), re.DOTALL).group(0)
    n = 0
    for s in segments or []:
        if not s or s.get("is_audio") or s.get("disabled") or not s.get("ajuste"):
            continue
        start = _tc_to_frames(s["timeline_tc_in"]) + _TIMELINE_OFFSET_FRAMES
        bloco = _uniquify(forma)
        bloco = _set_field(bloco, "Start", str(start))
        bloco = _set_field(bloco, "Duration", str(int(s["duration_frames"])))
        # ⚠️ a forma veio de uma timeline de 23,976 (a MediaTimemapBA dela fica); outra taxa: conferir
        bloco = _set_field(bloco, "MediaFrameRate", framerate_encode(_TL_FPS))
        fb = _xml_field(bloco, "FieldsBlob")
        if fb:
            bloco = _set_field(bloco, "FieldsBlob", _patch_fieldsblob_start(fb, start))
        lane = by_track.setdefault(int(s.get("track") or 1), [])
        depois = next((k for k, it in enumerate(lane)
                       if int(_xml_field(it, "Start") or 0) > start), len(lane))
        lane[depois:depois] = [bloco]
        n += 1
    return n


def _burnins_na_timeline(segments: list, by_track: dict, quadro: tuple[int, int]) -> int:
    """Cada linha de TC de um burn-in do Premiere (efeito `burnin` do segmento, `prproj/leitura.py`)
    vira um Text+ ("Fusion Title") na MESMA trilha e no MESMO trecho, com o TC da timeline vivo
    (`titulos/textplus.py`). Devolve quantos."""
    from titulos import textplus

    n = 0
    for s in segments or []:
        if s.get("is_audio") or s.get("disabled"):
            continue
        ef = next((e for e in s.get("effects") or [] if e.get("category") == "burnin"), None)
        if not ef:
            continue
        p = ef["params"]
        start = _tc_to_frames(s["timeline_tc_in"]) + _TIMELINE_OFFSET_FRAMES
        lane = by_track.setdefault(int(s.get("track") or 1), [])
        for ln in p.get("linhas") or []:
            bloco = _uniquify(textplus.clipe_tc(
                start=start, duracao=int(s["duration_frames"]), fps=_TL_FPS, quadro=tuple(quadro),
                posicao=tuple(ln["posicao"]), size=float(p["size"]), size_linha=float(ln["size"]),
                opacidade_fundo=float(p.get("opacidade") or 0.0)))
            depois = next((k for k, it in enumerate(lane)
                           if int(_xml_field(it, "Start") or 0) > start), len(lane))
            lane[depois:depois] = [bloco]
            n += 1
    return n


if __name__ == "__main__":
    import json
    from aaf.parser import parse_aaf
    if len(sys.argv) < 3:
        print("uso: python -m drp.writer <aaf> <saida.drt> [timeline_name]\n"
              "(teste: casa cada segmento consigo mesmo via clip_name como matched_path)")
        raise SystemExit(1)
    parsed = parse_aaf(sys.argv[1])
    segs = parsed["segments"]
    # match fake p/ teste: usa o próprio clip_name como 'arquivo' (sem relink real)
    mr = [{"segment_index": i, "matched_path": f"/tmp/{s.get('clip_name')}.mp4"}
          for i, s in enumerate(segs) if s.get("clip_name")]
    res = build_drt(segs, mr, sys.argv[2],
                    timeline_name=sys.argv[3] if len(sys.argv) > 3 else None)
    print(json.dumps({k: v for k, v in res.items() if k != "clips"}, indent=2))
