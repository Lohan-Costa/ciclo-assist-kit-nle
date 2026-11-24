"""
drp/writer.py — gera um .drt do DaVinci Resolve a partir dos segmentos+matches do app.

TEMPLATELESS: o usuário NÃO fornece template. Usa o esqueleto sanitizado interno
(`drp/skeleton.drp`, gerado por `tools/make_skeleton.py`) só como CASCA (project.xml,
pastas do media pool, estrutura de tracks) + formas (shapes) de clipe para clonar, e
GERA o media pool a partir dos arquivos casados.

Fase atual: VÍDEO (todas as tracks de vídeo) — cortes + relink + timecode + velocidade
(linear). Áudio é a próxima fase. O áudio é esvaziado no DRT gerado.

Mapeamento Segment → Sm2TiVideoClip (validado contra o DRT de referência):
    Start (frame)    = frames(timeline_tc_in) + 86400   (Resolve começa em 01:00:00:00)
    Duration (frame) = duration_frames
    In (frame)       = round(source_start_frames × speed_ratio)
    Name             = clip_name
    MediaRef         = DbId do clipe gerado no pool (cross-link)
    MediaFilePath    = caminho ABSOLUTO do arquivo casado (relink)
    MediaReelNumber  = stem do arquivo casado
    MediaFrameRate   = blob (ffprobe r_frame_rate)
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

import os
import re
import sys
import time
import uuid
import zipfile
from pathlib import Path

from drt.blobs import (fieldsblob_decode, fieldsblob_encode, timemap_encode,
                               build_speed_timemap, build_ramp_timemap,
                               build_adaptive_ramp_timemap, build_effect_filters_ba,
                               framerate_encode)


def _ffprobe_bin() -> str:
    """O ffprobe EMBARCADO do Órbita (ver media/fftools.py) — o app não pode
    exigir ffprobe no PATH do usuário. Cai em "ffprobe" só como último recurso."""
    try:
        from media import fftools
        return fftools.ffprobe() or "ffprobe"
    except Exception:
        return "ffprobe"

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


def _reel(name: str) -> str:
    """Reel base de um nome de clipe/arquivo (sem extensão)."""
    return Path(name).stem if name else name


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _xml_field(block: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.DOTALL)
    return m.group(1) if m else None


def _set_field(block: str, tag: str, value: str) -> str:
    """
    Substitui o conteúdo de <tag>…</tag> (ou expande <tag/>).

    ⚠️ O `lambda` NÃO é estilo — é a correção de um bug com duas caras.
    O `re.sub` trata o terceiro argumento como TEMPLATE DE SUBSTITUIÇÃO, e um
    template é reprocessado: `\\1`, `\\g<0>` e escapes de barra invertida são
    expandidos DEPOIS de o valor já ter passado pelo `_xml_escape`. Consequências
    medidas, as duas com o mesmo `re.sub` literal:

    1. **O export de DRT quebrava sempre no Windows.** `MediaFilePath` recebe um
       caminho absoluto, e todo caminho do Windows começa por `C:\\Users\\…` →
       `re.error: bad escape \\U`. Nenhum editor no Windows conseguia exportar um
       `.drt`, e nada no macOS mostrava isso.
    2. **Furava o escape de XML.** Um arquivo chamado `A\\g<0>B.mov` fazia o `\\g<0>`
       reinjetar as tags cruas que o `_xml_escape` tinha acabado de neutralizar —
       ou seja, o nome de um arquivo conseguia emendar elementos no documento que
       o Resolve vai abrir.

    Com a função, o valor é literal: nada dentro dele é interpretado.
    """
    alvo = f"<{tag}>{value}</{tag}>"
    if re.search(rf"<{tag}>.*?</{tag}>", block, re.DOTALL):
        return re.sub(rf"<{tag}>.*?</{tag}>", lambda _m: alvo, block,
                      count=1, flags=re.DOTALL)
    if re.search(rf"<{tag}/>", block):
        return re.sub(rf"<{tag}/>", lambda _m: alvo, block, count=1)
    return block


_META_CACHE: dict[str, tuple] = {}


def _media_meta(media_path: str) -> tuple:
    """(nb_frames, fps, tc_str) do arquivo via ffprobe (cacheado). tc_str = TC embutido
    'HH:MM:SS:FF' ou None. nb_frames cai p/ duração×fps se nb_frames vier ausente."""
    if media_path in _META_CACHE:
        return _META_CACHE[media_path]
    nb = fps = tc = None
    try:
        import json
        import subprocess
        out = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries",
             "stream=r_frame_rate,nb_frames,duration:stream_tags=timecode:format_tags=timecode",
             "-of", "json", media_path],
            capture_output=True, text=True, timeout=30).stdout
        j = json.loads(out)
        st = (j.get("streams") or [{}])[0]
        rfr = st.get("r_frame_rate")
        if rfr and "/" in rfr:
            num, den = (int(x) for x in rfr.split("/"))
            fps = num / den if den else None
        if st.get("nb_frames") and str(st["nb_frames"]).isdigit():
            nb = int(st["nb_frames"])
        elif fps and st.get("duration"):
            try:
                nb = int(round(float(st["duration"]) * fps))
            except Exception:
                pass
        tc = (st.get("tags", {}) or {}).get("timecode") \
            or ((j.get("format", {}).get("tags", {}) or {}).get("timecode"))
    except Exception:
        pass
    _META_CACHE[media_path] = (nb, fps, tc)
    return _META_CACHE[media_path]


def _media_timemap(media_path: str, speed_ratio: float, seg: dict | None = None,
                   tl_fps: float | None = None) -> str | None:
    """MediaTimemapBA do clipe: constante (100%), velocidade linear, ou RAMPA (curva).

    Se `seg` tem motion_effect_type='ramp' + source_offset_map, emite a curva real
    (keyframes lineares densos via build_ramp_timemap). Senão, constante/linear.
    """
    nb, fps, _ = _media_meta(media_path)
    if nb is None or not fps:
        return None
    if seg and seg.get("motion_effect_type") == "ramp" and seg.get("source_offset_map"):
        off = seg["source_offset_map"]
        ss = int(seg.get("source_start_frames") or 0)
        f = float(tl_fps or fps)
        if _RAMP_MODE == "dense":
            # Denso fixo (N=159): fidelidade máxima, header validado, porém muitos keyframes.
            return build_ramp_timemap(nb, fps, off, ss, f)
        # Linear ADAPTATIVO (default): keyframes mínimos (Douglas-Peucker), frame-exato e editável.
        # interp0 é honrado ao frame pelo Resolve; encaixa num header QHash conhecido.
        return build_adaptive_ramp_timemap(nb, fps, off, ss, f)
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


def _skeleton_path() -> str:
    """Caminho do esqueleto bundled. Dev: ao lado deste módulo; PyInstaller: _MEIPASS."""
    here = Path(__file__).resolve().parent / "skeleton.drp"
    if here.exists():
        return str(here)
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cand = Path(base) / "drt" / "skeleton.drp"
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
        from drt.blobs import pb_decode, pb_encode
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
    dirp = os.path.dirname(os.path.abspath(abspath)).encode("utf-8")
    name = os.path.basename(abspath).encode("utf-8")
    mstr = mus = None
    try:
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
    nb, _fps, tc = _media_meta(matched_path)
    b = re.sub(r"<Time>([0-9a-fA-F]{20,})</Time>",
               lambda m: "<Time>" + _regen_time_blob(m.group(1), tc, nb) + "</Time>", b)
    b = _set_field(b, "Name", _xml_escape(name))
    b = _set_field(b, "UniqueMediaPoolItemId", uniq_id)
    return b


def _effect_filters_ba_for(seg: dict) -> str | None:
    """Traduz o efeito geométrico do segmento (Avid) → `EffectFiltersBA` do Resolve.

    Modelo neutro = fração do raster (ver docs/effect-translation.md). Conversão Avid→Resolve:
    pos (milésimos) /1000 = fração (Resolve guarda px/1920, px/1080 = mesma fração; +Y cima nos
    dois); scale (já fator no parser) = zoom; rot_z = graus. Posição/escala validados; sinal de
    rotação a confirmar. Crop/opacity ainda não emitidos (filtros separados — a fazer)."""
    for e in (seg.get("effects") or []):
        if e.get("category") != "geometric" or not e.get("reproducible"):
            continue
        p = e.get("params") or {}
        kw = {}
        if "pos_x" in p: kw["pos_x"] = p["pos_x"] / 1000.0
        if "pos_y" in p: kw["pos_y"] = p["pos_y"] / 1000.0
        if "scale_x" in p: kw["zoom_x"] = p["scale_x"]
        if "scale_y" in p: kw["zoom_y"] = p["scale_y"]
        if "rot_z" in p: kw["rotation"] = p["rot_z"]
        if "opacity" in p: kw["opacity"] = p["opacity"]          # Avid 0–100 = Resolve 0–100
        # CROP — Avid guarda a POSIÇÃO da borda em ±999 (0 = 50% cropado); +X dir, +Y cima.
        # Resolve guarda a FRAÇÃO cropada por borda. Confirmado (CROP CONFIRMACAO.aaf):
        #   esquerda/baixo = (v+999)/1998 ; direita/topo = (999-v)/1998 (invertidos).
        if "crop_l" in p: kw["crop_l"] = (p["crop_l"] + 999.0) / 1998.0
        if "crop_b" in p: kw["crop_b"] = (p["crop_b"] + 999.0) / 1998.0
        if "crop_r" in p: kw["crop_r"] = (999.0 - p["crop_r"]) / 1998.0
        if "crop_t" in p: kw["crop_t"] = (999.0 - p["crop_t"]) / 1998.0
        if kw:
            return build_effect_filters_ba(**kw)
    return None


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
    rel = float(seg.get("relative_speed") or sr) or sr
    is_ramp = seg.get("motion_effect_type") == "ramp" and seg.get("source_offset_map")
    # In no domínio de frames da TIMELINE (o Resolve interpreta o In na taxa da timeline e
    # conforma a mídia internamente). `source_start_frames` vive na fps NATIVA do AAF; o Avid
    # SpeedRatio = timeline_fps/nat_fps → In = fonte × speed_ratio leva ao domínio da timeline.
    # Robusto inclusive quando o AAF rotula a nativa errada (C004: nat=29.97 mas arquivo 23.976):
    # fonte e speed_ratio ficam ambos no mesmo domínio (29.97) e o produto cai no da timeline.
    # A VELOCIDADE de CONFORM não entra aqui (vai zerada no timemap via relative_speed).
    # `in_extra` (frames de timeline) avança o In quando o clipe começa depois do corte.
    in_pt = 0 if is_ramp else round((int(seg.get("source_start_frames") or 0)
                                     + int(offset_corr or 0)) * sr) + int(in_extra or 0)
    # Nome = arquivo ONLINE reconectado (não o nome do offline do AAF, que vem com .new.NN);
    # casa com o nome do clipe no media pool e é o que o editor espera ver na timeline.
    name = os.path.basename(matched_path)
    reel = _reel(os.path.basename(matched_path))

    block = _uniquify(shape)   # DbIds próprios por clipe da timeline
    block = _set_field(block, "Name", _xml_escape(name))
    block = _set_field(block, "Start", str(start))
    block = _set_field(block, "Duration", str(dur))
    if in_pt == 0:
        block = re.sub(r"<In>.*?</In>", "<In/>", block, count=1, flags=re.DOTALL)
    else:
        block = _set_field(block, "In", str(in_pt))
    block = _set_field(block, "MediaRef", db_id)
    block = _set_field(block, "MediaFilePath", _xml_escape(os.path.abspath(matched_path)))
    block = _set_field(block, "MediaReelNumber", _xml_escape(reel))

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
    tm = _media_timemap(matched_path, rel, seg=seg,
                        tl_fps=float(seg.get("source_fps") or 0) or None)
    if tm:
        block = _set_field(block, "MediaTimemapBA", tm)

    efb = _effect_filters_ba_for(seg)
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
    # `lambda` obrigatório: `items` carrega nome e CAMINHO de arquivo, e como template
    # de substituição um `C:\Users\…` do Windows explode em `re.error: bad escape \U`.
    # Mesmo bug de `_set_field` — ver a explicação longa lá.
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
        import json
        import subprocess
        out = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-select_streams", "a:0",
             "-show_entries",
             "stream=sample_rate,channels,duration_ts:format=duration:format_tags=time_reference",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30).stdout
        j = json.loads(out)
        st = (j.get("streams") or [{}])[0]
        if st.get("sample_rate") and str(st["sample_rate"]).isdigit():
            sr = int(st["sample_rate"])
        if st.get("channels"):
            ch = int(st["channels"])
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


def _replace_in_zstd(hexstr: str, old: bytes, new: bytes) -> str:
    """Substitui `old`→`new` (mesmo tamanho) dentro de um blob zstd (flag 0x81)."""
    if len(old) != len(new):
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
        dec = zstandard.ZstdDecompressor().decompress(raw[9:])
    except Exception:
        return hexstr
    if old not in dec:
        return hexstr
    comp = zstandard.ZstdCompressor().compress(dec.replace(old, new))
    payload = flag + comp
    return (ver + len(payload).to_bytes(4, "big") + payload).hex()


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
    key = "MediaExtents".encode("utf-16-be")
    k = dec.find(key)
    if k < 0:
        return hexstr
    p = k + len(key)
    if dec[p:p + 4] != (12).to_bytes(4, "big"):   # confirma type=12 (obj de doubles)
        return hexstr
    if start_sec is not None:
        dec[p + 9:p + 17] = struct.pack("<d", float(start_sec))
    if dur_sec:
        dec[p + 17:p + 25] = struct.pack("<d", float(dur_sec))
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


def _make_audio_pool_clip(shape: str, name: str, db_id: str, uniq_id: str, matched_path: str) -> str:
    """Sm2MpAudioClip por arquivo: identidade única + caminho no `<Clip>` + specs
    (SampleRate/NumChannels/Duration/StartTime) do arquivo no `<TracksBA>` (e troca a
    sample rate da forma no FieldsBlob), senão herda os specs da forma (ex.: 96000Hz)."""
    b = _uniquify(shape, top_db_id=db_id)
    b = re.sub(r"<Clip>([0-9a-fA-F]{40,})</Clip>",
               lambda m: "<Clip>" + _regen_clip_blob(m.group(1), matched_path) + "</Clip>", b)
    mst, dur_sec, sr, ch, dts = _audio_meta(matched_path)
    # sample rate antiga da forma (p/ trocar no FieldsBlob zstd)
    old_sr = None
    m = re.search(r"<TracksBA>([0-9a-fA-F]+)</TracksBA>", b)
    if m:
        rb = bytes.fromhex(m.group(1))
        i = rb.find("SampleRate".encode("utf-16-be"))
        if i >= 0:
            p = i + len("SampleRate".encode("utf-16-be")) + 5
            old_sr = int.from_bytes(rb[p:p + 4], "big")
    b = re.sub(r"<TracksBA>([0-9a-fA-F]+)</TracksBA>",
               lambda m: "<TracksBA>" + _regen_audio_tracks_ba(m.group(1), sr, ch, dts, mst) + "</TracksBA>", b)
    if sr and old_sr and old_sr != sr:
        b = re.sub(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>",
                   lambda m: "<FieldsBlob>" + _replace_in_zstd(
                       m.group(1), int(old_sr).to_bytes(4, "big"), int(sr).to_bytes(4, "big")) + "</FieldsBlob>", b)
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


def _make_audio_timeline_clip(shape: str, seg: dict, db_id: str, matched_path: str,
                              channel: int = 1, start_override: int | None = None,
                              dur_override: int | None = None, in_extra: int = 0) -> str:
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
    reel = _reel(os.path.basename(matched_path))
    mst, mdur, _sr, _ch, _dts = _audio_meta(matched_path)
    # MediaStartTime: áudio EMBUTIDO em VÍDEO (.mp4/.mov) usa o TC do VÍDEO (igual ao clipe de
    # vídeo — o áudio da câmera vive no mesmo arquivo/origem); áudio PURO (WAV) usa o BWF
    # time_reference (mst). Sem isso o áudio da câmera saía com MediaStartTime=0 → fora do ponto.
    _nbV, _fpsV, _tcV = _media_meta(matched_path)
    if _tcV and _fpsV:
        mst = _tc_to_frames(_tcV, round(_fpsV)) / _fpsV

    block = _uniquify(shape)
    block = _set_field(block, "Name", _xml_escape(os.path.basename(matched_path)))
    block = _set_field(block, "Start", str(start))
    block = _set_field(block, "Duration", str(dur))
    if in_pt == 0:
        block = re.sub(r"<In>.*?</In>", "<In/>", block, count=1, flags=re.DOTALL)
    else:
        block = _set_field(block, "In", str(in_pt))
    block = _set_field(block, "MediaRef", db_id)
    block = _set_field(block, "MediaFilePath", _xml_escape(os.path.abspath(matched_path)))
    block = _set_field(block, "MediaReelNumber", _xml_escape(reel))
    block = _set_field(block, "MediaStartTime", repr(mst))   # segundos (BWF time_reference/sr)
    # MediaTrackIdx = o CANAL DE CONTEÚDO 0-based que este clipe LÊ do arquivo — o
    # mesmo `channel` (1-based) do ch_word abaixo, menos 1. NÃO é o índice da track
    # na timeline: num DRT de referência feito no Resolve, o áudio da câmera (numa
    # track) e o canal 0 do som direto (noutra) têm AMBOS MediaTrackIdx=0. Antes
    # era `track - 1000` (convenção de track fictícia 1000+ do RELINKER) — com
    # tracks pequenas (1,2,3…) isso dava -999, -998… (canal absurdo → mudo).
    ch_idx = max(0, int(channel) - 1)
    block = _set_field(block, "MediaTrackIdx", str(ch_idx))
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
    if mdur:
        block = _set_field(block, "MediaTimemapBA",
                           timemap_encode({"kind": "const", "tag": 0x02, "value": mdur}))
    fb = _xml_field(block, "FieldsBlob")
    if fb:
        block = _set_field(block, "FieldsBlob", _patch_fieldsblob_start(fb, start))
    return block


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
            def _adj(seq):
                for j, sj in seq:
                    if sj.get("is_transition"):
                        continue
                    if sj.get("is_gap"):
                        return ("empty", None)
                    if j not in matched:
                        return ("unmatched", None)
                    return ("clip", j)
                return ("empty", None)   # borda da timeline = vazio
            ak, aj = _adj(list(reversed(lst[:pos])))
            bk, bj = _adj(lst[pos + 1:])
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


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_drt(segments: list, match_results: list, output_drt: str,
              skeleton_path: str | None = None, timeline_name: str | None = None,
              ramp_mode: str = "adaptive", timeline_fps: float = 24.0,
              interlaced: bool = False) -> dict:
    """Gera `output_drt` a partir de `segments` + `match_results` do app, SEM template
    do usuário. Regenera o media pool (1 clipe por arquivo casado) e as tracks de
    VÍDEO e ÁUDIO (cortes + TC + In + velocidade + relink) a partir dos matches.

    `ramp_mode`: "adaptive" (poucos keyframes lineares, frame-exato — default) ou "dense"
    (N=159 fixo). Ver docs/resolve-speed-ramp.md.
    `timeline_fps`: fps da TIMELINE do AAF (ex.: 29.97). A contagem de posição/TC e o
    offset de 01:00:00:00 dependem da taxa NOMINAL da timeline (parser gera o TC non-drop
    nessa base) — antes era fixo em 24, o que escalava errado timelines 29.97/25/30/etc.
    """
    global _RAMP_MODE, _NOMINAL_FPS, _TIMELINE_OFFSET_FRAMES
    _RAMP_MODE = ramp_mode if ramp_mode in ("adaptive", "dense") else "adaptive"
    # Base NOMINAL non-drop da timeline (24, 25, 30, 50, 60…) e offset de 01:00:00:00.
    _NOMINAL_FPS = max(1, round(float(timeline_fps or 24.0)))
    _TIMELINE_OFFSET_FRAMES = 3600 * _NOMINAL_FPS
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
        if matched.get(i):
            vsegs.append((i, s))

    # Pool: 1 clipe por arquivo único
    path_to_db: dict[str, str] = {}
    pool_elems = []
    for i, _s in vsegs:
        p = matched[i]
        if p in path_to_db:
            continue
        db = _new_id()
        path_to_db[p] = db
        pool_elems.append("<Element>" + _make_pool_clip(
            pool_v_shape, os.path.basename(p), db, _new_id(), p) + "</Element>")

    # Segmentos de ÁUDIO casados + pool de áudio (1 clipe por arquivo único)
    asegs = []
    for i, s in enumerate(segments or []):
        if not s or not s.get("is_audio") or s.get("is_gap") or s.get("is_transition"):
            continue
        nm = (s.get("clip_name") or "").strip()
        if not nm or nm.startswith("("):
            continue
        if matched.get(i):
            asegs.append((i, s))
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
            apath_to_db[p] = db
            apool_elems.append("<Element>" + _make_audio_pool_clip(
                pool_a_m.group(0), os.path.basename(p), db, _new_id(), p) + "</Element>")

    new_vec = "<MediaVec>" + "".join(pool_elems) + "".join(apool_elems) + "</MediaVec>"
    # `lambda` obrigatório: `new_vec` contém os `MediaFilePath` absolutos (no Windows,
    # `C:\Users\…`), que como template de substituição viram escapes inválidos.
    pool_new = re.sub(r"<MediaVec>.*?</MediaVec>", lambda _m: new_vec, pool,
                      count=1, flags=re.DOTALL)

    # Timeline: clipes por track
    # Transições: encosta os vizinhos no corte e insere o item Sm2TiTransition entre eles.
    dur_ovr, start_ovr, in_ovr, trans_after, fade_before, fade_after = \
        _transition_overrides(segments, matched)

    by_track: dict[int, list[str]] = {}
    generated = []
    for i, s in vsegs:
        p = matched[i]
        clip = _make_timeline_clip(tl_v_shape, s, path_to_db[p], p,
                                   offset_corr=offc_by_index.get(i, 0),
                                   start_override=start_ovr.get(i),
                                   dur_override=dur_ovr.get(i), in_extra=in_ovr.get(i, 0))
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

    # Reconstrói o VideoTrackVec: 1 track por número de track (ascendente)
    track_elems = []
    for t in sorted(by_track):
        track_elems.append("<Element>" + _make_video_track(track_shape, by_track[t]) + "</Element>")
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

    # Tracks de ÁUDIO (A1..An por número de track; track fictícia 1000+ → A1 ascendente)
    a_by_track: dict[int, list[str]] = {}
    if asegs and tl_a_m:
        for i, s in asegs:
            p = matched[i]
            tr = int(s.get("track") or 1000)
            # Áudio embutido → DbId do pool de VÍDEO; áudio puro (WAV) → DbId do pool de áudio.
            a_db = path_to_db.get(p) or apath_to_db.get(p)
            clip = _make_audio_timeline_clip(tl_a_m.group(0), s, a_db, p,
                                             channel=_embedded_channel(p, tr),
                                             start_override=start_ovr.get(i),
                                             dur_override=dur_ovr.get(i), in_extra=in_ovr.get(i, 0))
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
        a_track_elems = ["<Element>" + _make_video_track(a_track_shape, a_by_track[t]) + "</Element>"
                         for t in sorted(a_by_track)]
        new_atv = "<AudioTrackVec>" + "".join(a_track_elems) + "</AudioTrackVec>"
        seq_new = seq_new.replace(atv, new_atv, 1)
    else:
        seq_new = seq_new.replace(atv, _empty_all_items(atv), 1)

    # Renomeia a timeline (clipe de timeline no Master pool) p/ distinguir o import.
    out_files = dict(files)
    # Master/MpFolder.xml = pasta-raiz do media pool; o Sm2MpTimelineClip carrega o FORMATO da
    # timeline (FrameRate + Body), que governa o PLAYBACK. O esqueleto era 23.976 → a timeline
    # reproduzia em 24. Reescreve com os blobs do formato-alvo (catalogados de DRTs nativos);
    # sem catálogo, ao menos atualiza o rótulo FrameRate (display) via framerate_encode.
    fmt = _tl_format(timeline_fps, interlaced)
    tl_rate_blob = fmt[0] if fmt else framerate_encode(float(timeline_fps or 24.0))
    for n in list(out_files):
        if n.endswith("Master/MpFolder.xml"):
            txt = out_files[n].decode("utf-8", "replace")
            if timeline_name:
                txt = re.sub(r"(<Sm2MpTimelineClip\b.*?<Name>).*?(</Name>)",
                             lambda m: m.group(1) + _xml_escape(timeline_name) + m.group(2),
                             txt, count=1, flags=re.DOTALL)
            txt = _set_field(txt, "FrameRate", tl_rate_blob)
            if fmt:
                txt = _set_field(txt, "Body", fmt[1])
            # O DRT NATIVO do Resolve (que reproduz na fps certa) NÃO tem estes campos no
            # Sm2MpTimelineClip: `IsCustom` (flag de "configurações de timeline customizadas"
            # → faz o Resolve ignorar a fps do formato e cair na do projeto/esqueleto = 24) e
            # `ImportExportMetadataBA` (metadado de import HERDADO do esqueleto → leak: aponta
            # p/ outro .aaf). Remove ambos p/ a timeline-clip ficar igual à nativa.
            txt = re.sub(r"\s*<IsCustom>.*?</IsCustom>", "", txt, flags=re.DOTALL)
            txt = re.sub(r"\s*<ImportExportMetadataBA>.*?</ImportExportMetadataBA>", "",
                         txt, flags=re.DOTALL)
            out_files[n] = txt.encode("utf-8")

    out_files[seq_name] = seq_new.encode("utf-8")
    out_files[pool_name] = pool_new.encode("utf-8")

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
    }
