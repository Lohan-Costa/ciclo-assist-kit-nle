"""
Relinker — Módulo AAF: Parser
Lê um arquivo AAF e extrai todos os segmentos de vídeo com seus
metadados, timecodes e referências às mídias originais.

Casos suportados (mapeados na exploração):
  - Sequence direta com SourceClips
  - NestedScope (flat file): V1 base + V2 efeitos
  - Selector (multcam / multi-resolução / Group Clip)
  - ScopeReference (referência entre tracks internos — herda relink de V1)
  - OperationGroup: SBlend, Motion Control, Avid Titler+, MotionEffect
  - Transition (dissolve/wipe)
  - Filler (gap)
  - Group Clip (multicam Avid): AppCode=4 no CompositionMob alvo

Dependência: pyaaf2
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

import aaf2

from .markers import read_markers
from .speedcurve import extract_speed_keyframes

log = logging.getLogger("relinker.aaf.parser")


# ── Estruturas de dados de saída ──────────────────────────────────────────

@dataclass
class MediaRef:
    """Referência a um arquivo de mídia original resolvido."""
    mob_name: str
    url: str                      # file:/// URL original do AAF
    local_path: str               # path local após decode
    descriptor_type: str          # ImportDescriptor | CDCIDescriptor
    # Duração da mídia-fonte (length do slot do SourceMob; bate com o arquivo físico).
    # Usado como portão determinístico no matcher (ver media/matcher.py).
    source_duration_frames: Optional[int] = None
    source_duration_secs: Optional[float] = None
    # fps NATIVA do SourceMob (edit rate do slot de vídeo). É a taxa em que
    # `source_start_frames` e o offset de velocidade estão expressos — o domínio da
    # FONTE. Pode diferir da timeline (clipe 23.976 numa TL 29.97) E do arquivo online
    # (offline conformado p/ 29.97, online ainda 23.976). O preview/seek converte
    # source-frame→tempo com ESTA fps; o ffmpeg busca o online por tempo (fps do arquivo
    # online é irrelevante). None = desconhecida (usar a fps da timeline).
    source_fps: Optional[float] = None


@dataclass
class Segment:
    """Um segmento de vídeo extraído da timeline."""
    # Posição na timeline
    timeline_tc_in: str           # HH:MM:SS:FF na timeline (início visível)
    timeline_tc_out: str          # HH:MM:SS:FF na timeline (fim visível)
    duration_frames: int

    # Origem na mídia fonte
    source_start_frames: int      # offset em frames dentro da mídia original
    source_fps: float

    # Identificação
    clip_name: str
    track: int                    # número do track de vídeo (1, 2, ...)
    mob_id: Optional[str] = None
    source_slot_id: Optional[int] = None   # slot_id do SourceClip da timeline (= canal p/ áudio multicanal)

    # Referência ao arquivo de mídia
    media_ref: Optional[MediaRef] = None

    # Flags de comportamento
    is_gap: bool = False
    is_transition: bool = False
    is_effect: bool = False                    # OperationGroup sem mídia (Titler+, etc) — não tem matching
    is_audio: bool = False                     # segmento de track de ÁUDIO — captado p/ match/relink/atalhos, NÃO desenhado na timeline
    cutpoint: int = 0                       # frames do lado A (clip anterior) na transição
    has_motion_effect: bool = False
    motion_effect_type: Optional[str] = None   # constant|ramp|freeze|reverse
    speed_ratio: float = 1.0                   # 1.0=normal, 0.5=50%slow, 2.0=2x, 0.0=freeze
    phase_offset: int = 0                      # offset de frames na fonte no início do efeito
    # Classificação do motion effect no modelo neutro (ver plano fps/TC). Distingue o que
    # é adaptação automática de fps (conformação/promoção do Avid) do que o editor mudou:
    #   motion_class : native | conform | creative | conform+creative | ramp | freeze | reverse
    #   conform_ratio  = timeline_fps / native_source_fps  (razão natural de adaptação de fps)
    #   relative_speed = speed_ratio / conform_ratio       (a velocidade que o editor de fato
    #                    aplicou, no domínio nativo; 1.0 = sem mudança criativa = conform puro)
    # O Resolve conforma a fps sozinho → exporta-se relative_speed (não o speed_ratio total).
    motion_class: str = "native"
    conform_ratio: float = 1.0
    relative_speed: float = 1.0
    # Mapa timeline→fonte do MotionEffect, já integrado pelo Avid e normalizado para
    # domínio de frames da timeline: [(tl_frame, src_offset_frames), ...]. Cobre rampa,
    # constante, freeze e reverse sem precisar integrar a curva de velocidade.
    source_offset_map: list = field(default_factory=list)
    speed_curve: list = field(default_factory=list)   # [(t, speed)] p/ exibição (rampas)
    # Keyframes da curva de velocidade (PARAM_SPEED_MAP_U) com handles de Bézier —
    # reproduzem o gráfico "Speed" do Avid: [{t, speed, in_dt, in_dv, out_dt, out_dv, mode}].
    # Base para traduzir a rampa em keyframes nativos de outras NLEs (ver aaf/speedcurve.py).
    speed_keyframes: list = field(default_factory=list)
    # Como o quadro do meio é feito, no vocabulário do Resolve (nearest|frame_blend|optical_flow; None = o do
    # projeto). Do Avid: FluidMotion (`_SFX_RENDER` 6/7) → optical_flow; os outros (Blended inclusive) → None — o
    # autor (2026-10-12): só o fluxo óptico se correlaciona, o Frame Blend não.
    retime: Optional[str] = None
    # Efeitos aplicados no segmento (classificados). Cada item:
    #   {name, category, reproducible, params}
    #   category: speed|geometric|transition|color|animate|mask|other
    #   reproducible: True só p/ geométricos (position/scale/crop) — replicáveis no frame
    effects: list = field(default_factory=list)
    has_reframe: bool = False
    reframe_mode: Optional[str] = None         # FrameFlex Reformat: pillarbox|center_crop|keep_size|stretch (None = sem reframe)
    has_graphic_overlay: bool = False          # Avid Titler+ acima neste TC
    is_never_visible: bool = False             # 100% enterrado sob outro clipe opaco
    disabled: bool = False                      # clipe desabilitado/mutado no Avid (_DISABLE_CLIP_FLAG=1) — não aparece no programa

    # Flags de visibilidade (calculadas pelo caller após mapear todos os tracks)
    visible_tc_in: Optional[str] = None
    visible_tc_out: Optional[str] = None

    # Group Clip / multicam Avid
    is_group_clip: bool = False           # True quando o Selector aponta para um Group Clip (AppCode=4)
    group_clip_name: Optional[str] = None # nome do CompositionMob AppCode=4 (ex: "FLATFILE.Grp.01")

    # Alternativas (para Selector multcam / Group Clip)
    selector_alternates: list[MediaRef] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timeline_tc_in": self.timeline_tc_in,
            "timeline_tc_out": self.timeline_tc_out,
            "duration_frames": self.duration_frames,
            "source_start_frames": self.source_start_frames,
            "source_fps": self.source_fps,
            "clip_name": self.clip_name,
            "track": self.track,
            "mob_id": self.mob_id,
            "source_slot_id": self.source_slot_id,
            "media_ref": {
                "mob_name": self.media_ref.mob_name,
                "url": self.media_ref.url,
                "local_path": self.media_ref.local_path,
                "descriptor_type": self.media_ref.descriptor_type,
                "source_duration_frames": self.media_ref.source_duration_frames,
                "source_duration_secs": self.media_ref.source_duration_secs,
                "source_fps": self.media_ref.source_fps,
            } if self.media_ref else None,
            "is_gap": self.is_gap,
            "is_transition": self.is_transition,
            "is_effect": self.is_effect,
            "is_audio": self.is_audio,
            "cutpoint": self.cutpoint,
            "has_motion_effect": self.has_motion_effect,
            "motion_effect_type": self.motion_effect_type,
            "speed_ratio": self.speed_ratio,
            "phase_offset": self.phase_offset,
            "motion_class": self.motion_class,
            "conform_ratio": self.conform_ratio,
            "relative_speed": self.relative_speed,
            "source_offset_map": self.source_offset_map,
            "speed_curve": self.speed_curve,
            "speed_keyframes": self.speed_keyframes,
            "retime": self.retime,
            "effects": self.effects,
            "has_reframe": self.has_reframe,
            "reframe_mode": self.reframe_mode,
            "has_graphic_overlay": self.has_graphic_overlay,
            "is_never_visible": self.is_never_visible,
            "disabled": self.disabled,
            "visible_tc_in": self.visible_tc_in,
            "visible_tc_out": self.visible_tc_out,
            "is_group_clip": self.is_group_clip,
            "group_clip_name": self.group_clip_name,
            "selector_alternates": [
                {
                    "mob_name": a.mob_name,
                    "url": a.url,
                    "local_path": a.local_path,
                    "descriptor_type": a.descriptor_type,
                    "source_duration_frames": a.source_duration_frames,
                    "source_duration_secs": a.source_duration_secs,
                }
                for a in self.selector_alternates
            ],
        }


# ── Funções utilitárias ───────────────────────────────────────────────────

def _clip_disabled(comp) -> bool:
    """True se o componente está desabilitado/mutado no Avid.

    O Avid marca um clipe desabilitado ("Disable/Enable Clip" no contexto, ou track
    mutado) como `_DISABLE_CLIP_FLAG = 1` na `ComponentAttributeList`. Nesse caso o
    `Selected` do Selector vira um ScopeReference (pass-through, mostra a track de
    baixo) e o clipe real fica em `Alternates` — ou seja, ele NÃO aparece no programa.
    """
    try:
        attrs = comp['ComponentAttributeList'].value
    except Exception:
        return False
    for tv in (attrs or []):
        try:
            if getattr(tv, 'name', '') == '_DISABLE_CLIP_FLAG' and int(tv.value) != 0:
                return True
        except Exception:
            continue
    return False


def _param_def_name(param) -> str:
    """Nome do ParameterDef (ex: 'PARAM_SPEED_OFFSET_MAP_U'); fallback p/ param.name."""
    pd = getattr(param, 'parameterdef', None)
    return (getattr(pd, 'name', '') if pd else '') or getattr(param, 'name', '') or ''


def _parse_avup_text(blob) -> Optional[str]:
    """Extrai o TEXTO de um blob AVUP ('PUVA') de parâmetro de plugin AVX (ex.: 'Text Box Text' do
    Avid Titler+). Layout: [UUID_do_CFUser 16B opcional] 'PUVA' size(4) 4949 01000000 4949 uuid_le(16)
    size1(4) size2(4) data(size2). `data` = a string (UTF-8, null-terminated). Robusto ao prefixo:
    acha o offset do 'PUVA'. None se não for AVUP ou não decodificar. (Mesmo formato do SubCap —
    ver translate._parse_avup, que assume PUVA no offset 0.)"""
    try:
        b = bytes(blob)
    except Exception:
        return None
    off = b.find(b'PUVA')
    if off < 0 or len(b) - off < 40:
        return None
    p = b[off:]
    try:
        size2 = int.from_bytes(p[36:40], "little")
        data = p[40:40 + size2]
        return data.split(b"\x00", 1)[0].decode("utf-8", "replace") or None
    except Exception:
        return None


def _avup_texto_inteiro(blob: bytes) -> Optional[str]:
    """O `data` INTEIRO de um blob AVUP (o MQP Blob do Titler+ é um DB de texto: não se corta no 1º nulo)."""
    off = blob.find(b'PUVA')
    if off < 0 or len(blob) - off < 40:
        return None
    p = blob[off:]
    size2 = int.from_bytes(p[36:40], "little")
    return p[40:40 + size2].rstrip(b"\x00").decode("utf-8", "replace") or None


def _param_raw_bytes(param):
    """bytes crus do valor de um ConstantValue de plugin (via a propriedade 'Value'), ou None."""
    try:
        d = param['Value'].data
        return bytes(d) if d is not None else None
    except Exception:
        return None


def _title_ttext(op_group) -> Optional[str]:
    """Texto do Avid Title+ ATUAL (op 'Avid Titler+'): atributo `_TTEXT` no ComponentAttributeList,
    bytes `\\x00\\x00'T+: <texto> '\\x00`. Retorna o texto limpo (sem o prefixo 'T+: ' e os nulos)."""
    try:
        for a in op_group['ComponentAttributeList'].value:
            if getattr(a, 'name', '') == '_TTEXT':
                s = bytes(a.value).decode('utf-8', 'replace').strip('\x00')
                if s.startswith('T+: '):
                    s = s[4:]
                return s.strip() or None
    except Exception:
        pass
    return None


def _extract_title_params(op_group) -> dict:
    """Texto + estilo do título Avid. DOIS efeitos distintos:
      • Title+ ATUAL (op 'Avid Titler+'): texto no attr `_TTEXT`; ESTILO+posição+fonte+cor num único
        blob `MQP Blob` (DB de texto). Guarda `mqp_hex` -> o export AVB reconstrói o TrackEffect inteiro.
      • Legacy (op 'Avid Titler+ Legacy'/'Avid Title Tool'): texto no param 'Text Box Text' (AVUP).
    Retorna {text, texts[], mqp_hex?}. `text` também serve p/ recriar título NATIVO no DaVinci/Premiere."""
    out: dict = {}
    texts: list[str] = []
    mqp_hex = None
    try:
        params = list(op_group.get('Parameters') or [])
    except Exception:
        params = []
    for p in params:
        nm = _param_def_name(p)
        if nm == 'Text Box Text':                       # Legacy
            t = _parse_avup_text(_param_raw_bytes(p))
            if t and t not in texts:
                texts.append(t)
        elif nm == 'MQP Blob':                          # Title+ atual — estilo (DB) p/ reconstrução
            rb = _param_raw_bytes(p)
            if rb:
                mqp_hex = rb.hex()
    if not texts:                                       # Title+ atual: texto no _TTEXT
        tt = _title_ttext(op_group)
        if tt:
            texts.append(tt)
    if texts:
        out["text"] = "\n".join(texts)
        out["texts"] = texts
    if mqp_hex:
        out["mqp_hex"] = mqp_hex
    return out


def _read_pointlist(param) -> list:
    """[(time, value), ...] de um VaryingValue; [] se não der."""
    pts = []
    try:
        for cp in param['PointList'].value:
            try:
                pts.append((float(cp.time), float(cp.value)))
            except Exception:
                continue
    except Exception:
        pass
    return pts


def _normalize_offset_map(pts: list, op_length: int) -> list:
    """Normaliza o domínio X do offset map para frames da timeline.

    O Avid grava o mapa de duas formas: X em frames da timeline (ex.: 0..len, via
    PARAM_SPEED_OFFSET_MAP_U) OU X normalizado 0..1 (via PARAM_OFFSET_MAP_U). Aqui
    convertemos tudo para (tl_frame, src_offset) ordenado por tl_frame.
    """
    if not pts:
        return []
    max_x = max(abs(t) for t, _ in pts)
    normalized = max_x <= 1.0 + 1e-6
    out = []
    for t, v in pts:
        tlf = t * op_length if normalized else t
        out.append((round(tlf, 3), round(v, 3)))
    out.sort(key=lambda p: p[0])
    return out


def _parse_motion_effect_params(op_group, op_length: int = 0) -> tuple:
    """
    Lê os parâmetros de velocidade de um OperationGroup (Motion Control/Timewarp).

    Retorna (speed_ratio, is_reverse, phase_offset, motion_type, source_offset_map,
    speed_curve).

    - motion_type: 'constant' | 'ramp' | 'freeze' | 'reverse'
    - speed_ratio: positivo; 1.0=normal, 0.5=50%slow, 2.0=2x, 0.0=freeze (média p/ exibição)
    - source_offset_map: [(tl_frame, src_offset)] já integrado pelo Avid (cobre rampa)
    - speed_curve: [(t, speed)] de PARAM_SPEED_MAP_U (para detectar rampa / exibir)
    """
    speed_ratio = 1.0
    is_reverse = False
    phase_offset = 0
    is_varying_speed = False
    offset_map: list = []
    speed_curve: list = []
    speed_keyframes: list = []

    try:
        params = list(op_group.get('Parameters') or [])
    except Exception:
        return (speed_ratio, is_reverse, phase_offset, 'constant',
                offset_map, speed_curve, speed_keyframes)

    for param in params:
        try:
            pname = _param_def_name(param)
            ptype = type(param).__name__

            if pname == 'SpeedRatio' or 'SpeedRatio' in pname:
                is_varying_speed = (ptype == 'VaryingValue')
                try:
                    raw = param.value_at(0)
                    speed_ratio = float(raw) if raw is not None else 1.0
                except Exception:
                    pass

            elif 'SPEED_OFFSET_MAP' in pname or pname == 'PARAM_OFFSET_MAP_U' or 'OFFSET_MAP' in pname:
                # Mapa timeline→fonte já integrado. Prefere SPEED_OFFSET_MAP se houver.
                pts = _read_pointlist(param)
                if pts and (not offset_map or 'SPEED_OFFSET_MAP' in pname):
                    offset_map = _normalize_offset_map(pts, op_length)

            elif 'SPEED_MAP' in pname:
                speed_curve = _read_pointlist(param)
                # Keyframes com handles de Bézier → reproduzir a curva (aaf/speedcurve.py)
                try:
                    speed_keyframes = extract_speed_keyframes(param)
                except Exception as e:
                    log.debug("extract_speed_keyframes falhou: %s", e)

            elif 'SMPTEReverse' in pname:
                try:
                    is_reverse = bool(param.value_at(0))
                except Exception:
                    pass

            elif 'PhaseOffset' in pname or pname == 'AvidPhase':
                try:
                    phase_offset = int(param.value_at(0) or 0)
                except Exception:
                    pass

        except Exception as e:
            log.debug("MotionEffect param error: %s", e)

    # Rampa: curva de velocidade com mais de um valor distinto, ou SpeedRatio variável.
    curve_varies = len({round(v, 4) for _, v in speed_curve}) > 1 if speed_curve else False

    if is_reverse or speed_ratio < 0:
        me_type = 'reverse'
        speed_ratio = abs(speed_ratio)
    elif speed_ratio == 0.0:
        me_type = 'freeze'
    elif curve_varies or is_varying_speed:
        me_type = 'ramp'
    else:
        me_type = 'constant'

    return (speed_ratio, is_reverse, phase_offset, me_type,
            offset_map, speed_curve, speed_keyframes)


# Tolerância relativa p/ considerar duas taxas/razões "iguais" (absorve 1.001, NTSC e
# arredondamento de 24↔23.976, 30↔29.97, etc).
_RATE_TOL = 0.012


def _classify_motion(speed_ratio: float, motion_type: Optional[str],
                     native_fps: Optional[float],
                     timeline_fps: Optional[float]) -> tuple[str, float, float]:
    """Classifica o estado de velocidade do segmento no modelo neutro.

    Separa a ADAPTAÇÃO DE FPS (conformação/promoção automática do Avid) da mudança de
    velocidade que o EDITOR aplicou:

        conform_ratio  = timeline_fps / native_fps   (razão natural; 1.0 se fps iguais/desconhecida)
        relative_speed = speed_ratio / conform_ratio  (o que o editor mudou, no domínio nativo)

    Retorna (motion_class, conform_ratio, relative_speed). Classes:
      native           — sem efeito de velocidade e fps casam.
      conform          — fps≠ e relative_speed≈1 (só a promoção de fps; ex.: 23.976→29.97).
      creative         — fps casam e speed_ratio≠1 (editor mudou a velocidade).
      conform+creative — fps≠ e relative_speed≠1 (promoção + mudança do editor).
      ramp | freeze | reverse — preservados como vêm (tratamento de velocidade especial).
    """
    sr = float(speed_ratio) if speed_ratio else 1.0
    tl = float(timeline_fps) if timeline_fps else 0.0
    nat = float(native_fps) if native_fps else 0.0
    conform_ratio = (tl / nat) if (tl > 0 and nat > 0) else 1.0
    relative_speed = (sr / conform_ratio) if conform_ratio else sr

    # Tipos especiais ficam com a própria classe (a fatoração de conform na rampa é fase
    # posterior — ver plano fps/TC).
    if motion_type in ("ramp", "freeze", "reverse"):
        return motion_type, conform_ratio, relative_speed

    fps_differ = abs(conform_ratio - 1.0) > _RATE_TOL
    rel_is_one = abs(relative_speed - 1.0) <= _RATE_TOL

    if not fps_differ:
        return ("native" if rel_is_one else "creative"), conform_ratio, relative_speed
    return ("conform" if rel_is_one else "conform+creative"), conform_ratio, relative_speed


# Classificação de efeitos por nome do OperationDef. Cada entrada: (category, reproducible).
# reproducible=True só para geométricos (position/scale/crop) — replicáveis no frame de
# comparação. Os demais são apenas informados ao editor.
_EFFECT_CATEGORY_RULES = [
    # (substrings no nome do OperationDef, category, reproducible)
    (('Audio Gain',), 'gain', True),         # ganho/volume de clip — escalar simples, reproduzível
    (('Titler', 'Title Tool', 'Avid Title'), 'title', True),   # texto/legenda — extrai o texto (AVUP)
    (('Motion Control', 'Timewarp', 'Motion Effect', 'MotionEffect'), 'speed', False),
    (('SBlend', '3DWarp', '3D Warp', 'S3D', 'Resize', 'PaintResize', 'Reformat',
      'Picture in Picture', 'Picture-In-Picture', 'PIP', 'Pan', 'Scan', 'PanScan',
      'Spin', 'Squeeze', 'Xpress 3D', 'Region Stabilize', 'FrameFlex',
      'SpatialAdapter', 'Blanking'),
     'geometric', True),
    (('Wipe', 'Dissolve', 'Fade', 'Conceal', 'Push', 'Sawtooth', 'Matrix', 'Plasma',
      'Dip', 'Edge Wipe'), 'transition', False),
    (('Color', 'CC ', 'Color Correction', 'Curves', 'Levels', 'HSL', 'RGB',
      'Saturation', 'Safe Color'), 'color', False),
    (('Paint', 'Animatte', 'Anim', 'Intraframe', 'Scratch'), 'animate', False),
    (('Mask', 'Matte', 'SpectraMatte', 'Key', 'Luma', 'Chroma'), 'mask', False),
]


def _categorize_effect(op_name: str) -> tuple[str, bool]:
    for needles, category, reproducible in _EFFECT_CATEGORY_RULES:
        if any(n.lower() in op_name.lower() for n in needles):
            return category, reproducible
    return 'other', False


# Nome amigável (como aparece no Media Composer) a partir do AvidEffectID ou do
# OperationDef. O AAF guarda o nome técnico (ex: 'SBlend_v2'); o rótulo do MC vem
# do AvidEffectID (ex: 'EFF2_SBLEND' → '3D Warp') ou de um mapa por OperationDef.
_FRIENDLY_BY_EFFECT_ID = {
    'EFF2_SBLEND': '3D Warp',
    'EFF2_BLEND_WIPE': 'SMPTE Wipe',     # prefixo (HORZ/VERT/...)
    'EFF2_BLEND_DISSOLVE': 'Dissolve',
    'EFF_BLEND_DISSOLVE': 'Dissolve',
}
_FRIENDLY_BY_OP = {
    'Motion Control': 'Timewarp',
    'Timewarp': 'Timewarp',
    'SBlend_v2': '3D Warp',
    'SMPTE Wipe': 'SMPTE Wipe',
    'SpatialAdapter': 'FrameFlex',
}

# interpolationdef (pyaaf2) → tipo de keyframe amigável.
_INTERP_FRIENDLY = {
    'ConstantInterp': 'Shelf',
    'LinearInterp': 'Linear',
    'BezierInterpolator': 'Bezier',
    'BezierInterpolation': 'Bezier',
    'CubicInterpolator': 'Spline',
    'AvidCubicInterpolator': 'Spline',
}


def _decode_avid_effect_id(op_group) -> Optional[str]:
    """Lê o AvidEffectID (array de bytes ASCII terminado em 0) → string, ou None."""
    try:
        for param in (op_group.get('Parameters') or []):
            if _param_def_name(param) == 'AvidEffectID':
                raw = param.value_at(0)
                if isinstance(raw, (list, tuple, bytes, bytearray)):
                    return bytes(b for b in raw if b).decode('ascii', 'ignore')
                if isinstance(raw, str):
                    return raw
    except Exception:
        pass
    return None


def _friendly_effect_label(op_group, op_name: str) -> str:
    """Rótulo do efeito como no Media Composer (3D Warp, Timewarp, SMPTE Wipe…)."""
    eid = _decode_avid_effect_id(op_group)
    if eid:
        for prefix, label in _FRIENDLY_BY_EFFECT_ID.items():
            if eid.startswith(prefix):
                return label
    if op_name in _FRIENDLY_BY_OP:
        return _FRIENDLY_BY_OP[op_name]
    return op_name or '(efeito)'


def _interp_friendly(param) -> Optional[str]:
    """Tipo de interpolação amigável (Shelf/Linear/Spline/Bezier) de um VaryingValue."""
    try:
        name = getattr(getattr(param, 'interpolationdef', None), 'name', None)
        if name:
            return _INTERP_FRIENDLY.get(name, name)
    except Exception:
        pass
    return None


def _const_or_first(param):
    """Valor escalar de um Parameter: const, ou 1º keyframe de um VaryingValue."""
    try:
        return float(param.value_at(0))
    except Exception:
        return None


# FrameFlex Reformat (encaixe mídia↔timeline) — enum decodificado em docs/effect-translation.md.
# Mesmo inteiro na timeline (AFX_SPATIAL_REFORMAT) e na origem (_BOUNDS_REFORMATTING_OPTION);
# Stretch = −1 na timeline / ausente na origem.
_REFORMAT_MODES = {1: 'pillarbox', 2: 'center_crop', 3: 'keep_size', -1: 'stretch'}
# Pillarbox = fit-inside (= comportamento default do "scale to fit" do Resolve) → seguro.
# Os demais precisam de ajuste manual no destino até implementarmos a tradução do reframe.
_REFORMAT_NEEDS_REVIEW = {'center_crop', 'keep_size', 'stretch'}


def _detect_reframe_mode(comp) -> Optional[str]:
    """Procura um SpatialAdapter (FrameFlex) na pilha de efeitos do segmento e devolve o
    modo de Reformat (pillarbox|center_crop|keep_size|stretch). Prioriza modos ≠ pillarbox
    (são os que precisam de aviso). Desce recursivamente nos InputSegments (FrameFlex pode
    envolver outros efeitos)."""
    seen: set = set()
    found: list = []

    def rec(o):
        if o is None or id(o) in seen:
            return
        seen.add(id(o))
        if type(o).__name__ == 'OperationGroup':
            op = getattr(o, 'operation', None)
            if getattr(op, 'name', '') == 'SpatialAdapter':
                try:
                    for p in (o.get('Parameters') or []):
                        if _param_def_name(p) == 'AFX_SPATIAL_REFORMAT':
                            v = _const_or_first(p)
                            if v is not None:
                                m = _REFORMAT_MODES.get(int(round(v)))
                                if m:
                                    found.append(m)
                except Exception:
                    pass
            try:
                for ip in list(o.get('InputSegments') or []):
                    rec(ip)
            except Exception:
                pass
        else:
            for attr in ('components', 'segments'):
                try:
                    for s in (getattr(o, attr, None) or []):
                        rec(s)
                except Exception:
                    pass
            try:
                inner = o.get('InputSegment')
                if inner is not None:
                    rec(inner.value if hasattr(inner, 'value') else inner)
            except Exception:
                pass

    rec(comp)
    if not found:
        return None
    # se algum modo precisa de revisão, reporta ele; senão pillarbox.
    for m in found:
        if m in _REFORMAT_NEEDS_REVIEW:
            return m
    return found[0]


def frameflex_neutro(size_x, size_y, pos_x, pos_y, rot_z) -> dict:
    """O FrameFlex (SpatialAdapter) no MESMO modelo neutro do 3D Warp — a conta, sem leitor.

    FrameFlex é um reframe: define uma janela sobre a fonte. Por isso Size e Position
    têm semântica invertida vs 3D Warp (ver docs/effect-translation.md §FrameFlex):
      zoom = 100/Size; frac_pos = −Position/Size; rotação = DVE_ROT_Z_U.
    Saída no formato que o writer já consome: `scale_*` em FATOR (zoom), `pos_*` em
    milésimos (frac×1000, writer faz ÷1000), `rot_z` em graus. Serve ao leitor de AAF e ao
    da bin (`avb_bin/efeitos.py`): a fórmula mora num lugar só.
    """
    out: dict = {}
    if size_y is None:
        size_y = size_x
    # Size em % da fonte (50 = janela ocupa 50% → zoom 2×). Sem Size válido → identidade.
    size_x = size_x or 100.0
    size_y = size_y or 100.0
    pos_x = pos_x or 0.0
    pos_y = pos_y or 0.0
    # zoom = 100/Size (validado: Size 50 → grade 200px = 2× o controle).
    out['scale_x'] = 100.0 / size_x
    out['scale_y'] = 100.0 / size_y
    # posição: frac = −Position/Size (move a janela). Guarda em milésimos p/ o writer ÷1000.
    # (sinal de Y por analogia ao X/Pan&Scan — confirmar com amostra POSY≠0.)
    out['pos_x'] = -(pos_x / size_x) * 1000.0
    out['pos_y'] = -(pos_y / size_y) * 1000.0
    if rot_z:
        out['rot_z'] = rot_z
    return out


def _extract_frameflex_params(pnames: dict) -> dict:
    """O FrameFlex do AAF: lê os parâmetros e passa para `frameflex_neutro`."""
    def val(name):
        p = pnames.get(name)
        return _const_or_first(p) if p is not None else None

    return frameflex_neutro(val('AFX_SPATIAL_FRAMING_WID'), val('AFX_SPATIAL_FRAMING_HEI'),
                            val('AFX_SPATIAL_FRAMING_POSX'), val('AFX_SPATIAL_FRAMING_POSY'),
                            val('DVE_ROT_Z_U'))


# Nomes reais dos params, confirmados nas amostras MAPEAMENTO DE EFEITOS (ver
# docs/effect-translation.md). Dois esquemas com a MESMA regra de valor:
#   DVE_* → 3D Warp (SBlend_v2);  AFX_POS_/AFX_SCALE_ → Resize/PIP/Pan&Scan.
# pos/axis em milésimos; scale em % (÷100); rot em graus; crop ±999; opacity 0–100.
# (Pan&Scan usa os mesmos nomes mas com SINAL de posição invertido — tratado em
# _classify_effect; FrameFlex/SpatialAdapter tem esquema próprio.) Os nomes são os mesmos
# na bin: o uuid do parâmetro no .avb É o AUID do ParameterDef (avb_bin/efeitos.py).
PARAMS_GEOMETRICOS = {
    'DVE_POS_X_U': 'pos_x', 'DVE_POS_Y_U': 'pos_y', 'DVE_POS_Z_U': 'pos_z',
    'DVE_SCALE_X_U': 'scale_x', 'DVE_SCALE_Y_U': 'scale_y',
    'DVE_ROT_X_U': 'rot_x', 'DVE_ROT_Y_U': 'rot_y', 'DVE_ROT_Z_U': 'rot_z',
    'DVE_CROP_LEFT_U': 'crop_l', 'DVE_CROP_RIGHT_U': 'crop_r',
    'DVE_CROP_TOP_U': 'crop_t', 'DVE_CROP_BOTTOM_U': 'crop_b',
    'DVE_AXIS_X_U': 'axis_x', 'DVE_AXIS_Y_U': 'axis_y',
    'DVE_FG_KEY_OPACITY_U': 'opacity',
    # Esquema AFX (Resize / Picture-in-Picture / Pan&Scan) — mesma regra de valor:
    'AFX_POS_X_U': 'pos_x', 'AFX_POS_Y_U': 'pos_y',
    'AFX_SCALE_X_U': 'scale_x', 'AFX_SCALE_Y_U': 'scale_y',
}


def _extract_geometric_params(op_group) -> dict:
    """Lê position/scale do 3DWarp/SBlend (DVE_*). Valores batem 1:1 com a UI do MC.

    scale_* normalizado (192 → 1.92); pos_* mantém a unidade Avid (calibrar contra o
    ref_video). Para efeitos animados captura também os keyframes (tempo normalizado
    0..1) em `keyframes`: [{t, scale_x, scale_y, pos_x, pos_y}].
    """
    out: dict = {}
    animated = False
    interp = None
    try:
        params = list(op_group.get('Parameters') or [])
    except Exception:
        return out

    # FrameFlex (SpatialAdapter) tem ESQUEMA PRÓPRIO (AFX_SPATIAL_FRAMING_*) — decifrado
    # em docs/effect-translation.md §FrameFlex. É um reframe (janela sobre a fonte), então
    # Size e Position têm semântica DIFERENTE do 3D Warp:
    #   • zoom    = 100 / Size      (Size=50% → janela = 50% da fonte → magnifica 2×)
    #   • frac    = −Position / Size  (Position em %, amplificada pelo zoom; sinal invertido
    #     porque move a JANELA, não a imagem — como Pan&Scan)
    #   • rotação = DVE_ROT_Z_U (reusa o param do 3D Warp)
    # Detecção: o param escalar 'AFX_SPATIAL_FRAMING_WID' só existe quando o usuário
    # promoveu/ativou o FrameFlex; os SpatialAdapter "passivos" (só reformat de raster) têm
    # apenas os *_NUM/_DEN e devem cair fora (identidade, não-reproduzível).
    pnames = {_param_def_name(p): p for p in params}
    if 'AFX_SPATIAL_FRAMING_WID' in pnames:
        return _extract_frameflex_params(pnames)
    wanted = PARAMS_GEOMETRICOS
    varying = {}            # key → param (VaryingValue) para evaluar nos tempos
    times: set = set()
    for param in params:
        pname = _param_def_name(param)
        key = wanted.get(pname)
        if not key:
            continue
        val = _const_or_first(param)
        if val is None:
            continue
        out[key] = (val / 100.0) if key.startswith('scale') else val
        if type(param).__name__ == 'VaryingValue':
            animated = True
            varying[key] = param
            interp = interp or _interp_friendly(param)
            try:
                for cp in param['PointList'].value:
                    times.add(round(float(cp.time), 4))
            except Exception:
                pass
    if animated:
        out['animated'] = True
        if interp:
            out['interp'] = interp
        # Tabela de keyframes: para cada tempo único, avalia cada param.
        kfs = []
        for t in sorted(times):
            kf = {'t': t}
            for key in ('scale_x', 'scale_y', 'pos_x', 'pos_y'):
                p = varying.get(key)
                if p is not None:
                    try:
                        v = float(p.value_at(t))
                        kf[key] = (v / 100.0) if key.startswith('scale') else v
                        continue
                    except Exception:
                        pass
                if key in out:
                    kf[key] = out[key]
            kfs.append(kf)
        if kfs:
            out['keyframes'] = kfs
    return out


def _speed_interp(op_group) -> Optional[str]:
    """Interpolação da curva de velocidade (PARAM_SPEED_MAP_U), amigável."""
    try:
        for param in (op_group.get('Parameters') or []):
            if 'SPEED_MAP' in _param_def_name(param) and type(param).__name__ == 'VaryingValue':
                return _interp_friendly(param)
    except Exception:
        pass
    return None


def _classify_effect(op_group, op_name: str,
                     speed_ratio: float = 1.0, me_type: Optional[str] = None) -> dict:
    """Classifica um OperationGroup num descritor de efeito para o editor/matcher."""
    category, reproducible = _categorize_effect(op_name)
    eff = {
        "name": op_name or "(efeito)",
        "label": _friendly_effect_label(op_group, op_name),   # nome como no MC
        "category": category,
        "reproducible": reproducible,
        "params": {},
    }
    if category == 'geometric':
        eff["params"] = _extract_geometric_params(op_group)
        # Pan&Scan move a JANELA, não a imagem → posição com sinal invertido vs
        # 3D Warp/Resize/PIP (medido em MAPEAMENTO DE EFEITOS: 150 → −0.15). Normaliza
        # aqui para que pos_* sempre signifique "imagem desloca +X p/ direita".
        if 'panscan' in (op_name or '').lower().replace(' ', '').replace('&', ''):
            for k in ('pos_x', 'pos_y'):
                if k in eff["params"]:
                    eff["params"][k] = -eff["params"][k]
        # ⛔ No esquema AFX (Resize, Picture-in-Picture) +Y DESCE; o neutro é +Y SOBE (o do DVE/3D Warp) — medido no
        # laboratório A01 (2026-10-11). FrameFlex e Pan&Scan já saem normalizados acima.
        elif 'AFX_SPATIAL_FRAMING_WID' not in {_param_def_name(p) for p in (op_group.get('Parameters') or [])}                 and 'AFX_POS_Y_U' in {_param_def_name(p) for p in (op_group.get('Parameters') or [])}:
            if 'pos_y' in eff["params"]:
                eff["params"]['pos_y'] = -eff["params"]['pos_y']
            for kf in eff["params"].get('keyframes') or []:
                if kf.get('pos_y') is not None:
                    kf['pos_y'] = -kf['pos_y']
        # Sem params geométricos legíveis → não dá pra reproduzir.
        if not eff["params"]:
            eff["reproducible"] = False
    elif category == 'speed':
        eff["params"] = {"speed_ratio": round(speed_ratio, 6), "type": me_type or 'constant'}
        interp = _speed_interp(op_group)
        if interp:
            eff["params"]["interp"] = interp
    elif category == 'title':
        eff["params"] = _extract_title_params(op_group)
        if not eff["params"].get("text"):
            eff["reproducible"] = False      # sem texto legível -> só informar
        # ⭐ O bloco `titulo` da Carta (o mesmo que a leitura da BIN dá): sem ele o writer do DRT
        # descartava o título do AAF em silêncio (U03 do autor, 2026-10-01).
        try:
            from titulos import avid as _tit
            mqp = eff["params"].get("mqp_hex")
            titulo = _tit.do_aaf(op_name, eff["params"].get("texts") or [],
                                 _avup_texto_inteiro(bytes.fromhex(mqp)) if mqp else None)
            if titulo:
                eff["params"]["titulo"] = titulo
        except Exception as e:  # noqa: BLE001 — o título que não se lê vira aviso no writer, não queda
            log.debug("titulo do AAF: %s", e)
    elif category == 'color' and _decode_avid_effect_id(op_group) == 'EFF2_RGB_COLOR_CORRECTION':
        # O COLOR CORRECTION: Mas Sat + Curves › Master vão EDITÁVEIS aos 2 nós do Resolve depois do import
        # (`drp/cor_mc.py`, 2026-11-20). O AAF traz os mesmos parâmetros da bin (medido na PRODA: os 7 CC). Traduzível só
        # quando o CC inteiro se traduz; o resto do CC (Gain, Hue, Levels…) fica como antes: nota de refazer.
        from drp.cor_mc import ler_cc
        brutos = {}
        for p in (op_group.get('Parameters') or []):
            nome = _param_def_name(p)
            animado = type(p).__name__ == 'VaryingValue'
            try:
                v = None if animado else p.value
                if type(v).__name__ == 'AAFRational':
                    v = float(v)
            except Exception:
                v = None
            brutos[nome] = (v, animado, _param_raw_bytes(p) if nome == 'Curves Master' else None)
        try:
            cc = ler_cc(brutos)
        except Exception as e:  # noqa: BLE001 — o CC que não se lê fica a nota de antes
            log.debug("Color Correction do AAF: %s", e)
            cc = None
        if cc and not cc["nao"] and (cc["sat"] is not None or cc["curva"]):
            eff["reproducible"] = True
            eff["params"] = {"cor_mc": {"sat": cc["sat"],
                                        "curva": [[round(x, 6), round(y, 6)] for x, y in cc["curva"] or []] or None}}
        elif cc and cc["nao"]:
            eff["params"] = {"cor_mc_nao": cc["nao"]}
    elif category == 'gain':
        # nível = numerador/2^29 (convenção Avid; 2^29 = unity/0dB). Guarda o numerador cru —
        # quem consome decide o que fazer com unity (ex.: pular, sem precisar re-parsear o AAF).
        level_num = None
        for p in (op_group.get('Parameters') or []):
            try:
                v = p.value
                if type(v).__name__ == 'AAFRational':
                    level_num = int(v.numerator); break
            except Exception:
                pass
        if level_num is not None:
            eff["params"] = {"level_num": level_num}
        else:
            eff["reproducible"] = False
    elif "stabiliz" in (op_name or "").lower() and "region" not in (op_name or "").lower():
        # O Stabilize do MC: o tracker viaja nas propriedades privadas do OperationGroup (`estabilizacao.do_aaf`);
        # com ele a estabilização vai PRONTA ao estabilizador do Resolve (autor, 2026-10-24). O zoom é o da nota.
        from estabilizacao import do_aaf
        zoom = None
        for p in (op_group.get('Parameters') or []):
            try:
                if _param_def_name(p) == 'DVE_SCALE_X_U':
                    zoom = float(p.value)
            except Exception:
                pass
        eff["params"] = {"zoom_pct": round(zoom, 2) if zoom else None}
        try:
            dados = do_aaf(op_group, int(op_group.length or 0))
        except Exception as e:  # noqa: BLE001 — o tracker que não se lê fica a nota de antes
            log.debug("tracker do Stabilize: %s", e)
            dados = None
        if dados:
            eff["params"]["estabilizacao"] = dados
    return eff


def frames_to_tc(frames: int, fps: float) -> str:
    """Converte frames para HH:MM:SS:FF."""
    fps_int = round(fps)
    ff = frames % fps_int
    ss = (frames // fps_int) % 60
    mm = (frames // fps_int // 60) % 60
    hh = frames // fps_int // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _find_timecode(seg):
    """Primeiro componente Timecode dentro de um segmento (desce em Sequence/Pulldown)."""
    if seg is None:
        return None
    if type(seg).__name__ == 'Timecode':
        return seg
    comps = getattr(seg, 'components', None)
    if comps is not None:
        for c in comps:
            r = _find_timecode(c)
            if r is not None:
                return r
    inp = getattr(seg, 'input_segment', None)
    if inp is not None:
        return _find_timecode(inp)
    return None


def _frames_to_tc_df(frames: int, fps: float, drop: bool) -> str:
    """Frame contínuo → TC string. DF-aware (29.97/59.94) quando drop=True (separador ';')."""
    nominal = round(fps) or 25
    if not drop or nominal not in (30, 60):
        return frames_to_tc(frames, fps)
    f = max(0, int(frames))
    dropf = 4 if nominal == 60 else 2
    frames_per_10min = nominal * 60 * 10
    frames_per_min   = nominal * 60 - dropf          # drop-adjusted
    d = f // frames_per_10min
    m = f % frames_per_10min
    if m > dropf:
        f += dropf * 9 * d + dropf * ((m - dropf) // frames_per_min)
    else:
        f += dropf * 9 * d
    ff = f % nominal; ss = (f // nominal) % 60
    mm = (f // (nominal * 60)) % 60; hh = f // (nominal * 3600)
    return f"{hh:02d}:{mm:02d}:{ss:02d};{ff:02d}"


def _read_start_tc(comp, timeline_fps: float):
    """TC inicial da timeline (StartTimecode do CompositionMob).

    Retorna (start_frames_continuos, drop_frame_bool). O offset NÃO é aplicado aos
    segmentos (que ficam 0-based — matcher/writer DRT dependem disso); é exposto p/ a
    UI exibir o TC fiel ao AAF. Para a fps que casa com a timeline, usa o `start` do
    Timecode direto (já é frame contínuo na fps certa).
    """
    nominal = round(timeline_fps) or 25
    fallback = None
    for slot in getattr(comp, 'slots', []):
        seg = getattr(slot, 'segment', None)
        if getattr(seg, 'media_kind', '') != 'Timecode':
            continue
        tc = _find_timecode(seg)
        if tc is None:
            continue
        try:
            tcfps = int(round(float(tc.fps)))
            start = int(tc.start)
            drop = bool(getattr(tc, 'drop', False))
        except Exception:
            continue
        if tcfps <= 0:
            continue
        if tcfps == nominal:
            return start, drop          # casa com a timeline → frame contínuo direto
        if fallback is None:
            # fps diferente: converte o TC p/ frames na fps nominal (aprox., non-drop).
            h = start // (3600 * tcfps); m = (start // (60 * tcfps)) % 60
            sec = (start // tcfps) % 60; fr = start % tcfps
            fallback = (((h * 60 + m) * 60 + sec) * nominal + min(fr, nominal - 1), drop)
    return fallback or (0, False)


def url_to_local_path(url: str) -> str:
    """Converte file:/// URL para path local, removendo prefixos de volume macOS."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    # macOS: "/Macintosh HD/..." → "/..."
    if path.startswith("/Macintosh HD/"):
        path = path[len("/Macintosh HD"):]
    return path


def read_url_from_descriptor(desc) -> Optional[str]:
    """Lê a URLString do locator de um descriptor."""
    try:
        locs = list(getattr(desc, 'locator', []))
        for loc in locs:
            try:
                val = loc['URLString'].value
                if val and isinstance(val, str):
                    return val
            except Exception:
                pass
    except Exception:
        pass
    return None


def _source_mob_duration(src_mob) -> tuple[Optional[int], Optional[float]]:
    """
    Lê a duração da mídia-fonte (frames + segundos) a partir dos slots do SourceMob.

    O `length` do slot do SourceMob corresponde à contagem de frames do arquivo
    físico (validado: A003=960, CAM A=1572, etc. batem com pymediainfo). A duração
    em segundos é derivada do `edit_rate` do slot.

    Considera apenas slots de taxa "de vídeo" (edit_rate < 1000) para evitar pegar
    slots de áudio (samples a 48000) em mobs com múltiplas mídias.
    """
    try:
        best_frames: Optional[int] = None
        best_secs: Optional[float] = None
        for slot in src_mob.slots:
            seg = getattr(slot, 'segment', None)
            length = getattr(seg, 'length', None)
            if not length:
                continue
            length = int(length)
            er = getattr(slot, 'edit_rate', None)
            er_f = None
            try:
                er_f = float(er) if er is not None else None
            except Exception:
                er_f = None
            # Ignora slots de áudio (taxa de amostragem alta)
            if er_f is not None and er_f >= 1000:
                continue
            secs = (length / er_f) if er_f else None
            if best_frames is None or length > best_frames:
                best_frames = length
                best_secs = secs
        return best_frames, best_secs
    except Exception as e:
        log.debug("Falha ao ler duração do SourceMob '%s': %s",
                  getattr(src_mob, 'name', '?'), e)
        return None, None


def _source_mob_fps(src_mob) -> Optional[float]:
    """Edit rate do slot de VÍDEO do SourceMob (= fps nativa em que os offsets de fonte
    estão expressos). Ignora slots de áudio (taxa ≥ 1000). Escolhe o slot de maior
    length (o de vídeo), como `_source_mob_duration`."""
    try:
        best_len, best_fps = None, None
        for slot in src_mob.slots:
            seg = getattr(slot, 'segment', None)
            length = getattr(seg, 'length', None)
            er = getattr(slot, 'edit_rate', None)
            try:
                er_f = float(er) if er is not None else None
            except Exception:
                er_f = None
            if er_f is None or er_f >= 1000:
                continue
            length = int(length) if length else 0
            if best_len is None or length > best_len:
                best_len, best_fps = length, er_f
        return best_fps
    except Exception:
        return None


def resolve_master_mob(master_mob) -> Optional[MediaRef]:
    """
    Resolve um MasterMob até o arquivo físico via SourceMob → descriptor → locator.

    Cadeia de resolução observada em AAFs do Avid:

      MasterMob → Slot → Sequence → SourceClip → SourceMob [CDCIDescriptor proxy]
                                                    → Slot → SourceClip → SourceMob [ImportDescriptor original]

    Prefere ImportDescriptor (arquivo original) sobre CDCIDescriptor (proxy Avid).
    """
    best: Optional[MediaRef] = None

    for mslot in master_mob.slots:
        seg = mslot.segment

        # Slot pode ser Sequence (com um SourceClip dentro) ou SourceClip direto
        src_clip = None
        if type(seg).__name__ == 'SourceClip':
            src_clip = seg
        elif type(seg).__name__ == 'Sequence':
            for comp in seg.components:
                if type(comp).__name__ == 'SourceClip':
                    src_clip = comp
                    break

        if src_clip is None:
            continue

        try:
            src_mob = src_clip.mob
        except Exception:
            continue
        if type(src_mob).__name__ != 'SourceMob':
            continue

        desc = getattr(src_mob, 'descriptor', None)
        if not desc:
            continue

        desc_kind = type(desc).__name__

        # Duração da mídia: lida do slot deste src_mob (o clipe consolidado que o
        # MasterMob referencia). Para clipes com proxy CDCI, este slot tem o tamanho
        # real do arquivo (ex: A003=960), enquanto o ImportDescriptor seguido aponta
        # para a FITA inteira (~48h). Por isso capturamos a duração AQUI e a aplicamos
        # ao ref final, mesmo quando seguimos para o original.
        dur_f, dur_s = _source_mob_duration(src_mob)
        src_fps = _source_mob_fps(src_mob)   # fps nativa em que os offsets de fonte vivem

        if desc_kind == 'ImportDescriptor':
            # Caminho direto para o original
            url = read_url_from_descriptor(desc)
            if url:
                return MediaRef(
                    mob_name=src_mob.name,
                    url=url,
                    local_path=url_to_local_path(url),
                    descriptor_type='ImportDescriptor',
                    source_duration_frames=dur_f,
                    source_duration_secs=dur_s,
                    source_fps=src_fps,
                )

        elif desc_kind == 'CDCIDescriptor':
            # Proxy Avid: pode ter um slot que aponta para o ImportDescriptor original.
            # Cadeia: CDCIDescriptor SourceMob → Slot → SourceClip → ImportDescriptor SourceMob
            import_ref = _follow_proxy_to_original(src_mob)
            if import_ref and best is None:
                # Usa a URL do original, mas a DURAÇÃO/fps do proxy (clipe consolidado).
                import_ref.source_duration_frames = dur_f
                import_ref.source_duration_secs = dur_s
                import_ref.source_fps = src_fps
                best = import_ref
            elif best is None:
                # Guarda o proxy como fallback se não houver original.
                url = read_url_from_descriptor(desc)
                if url:
                    best = MediaRef(
                        mob_name=src_mob.name,
                        url=url,
                        local_path=url_to_local_path(url),
                        descriptor_type='CDCIDescriptor',
                        source_duration_frames=dur_f,
                        source_duration_secs=dur_s,
                        source_fps=src_fps,
                    )

    return best


def _follow_proxy_to_original(proxy_src_mob) -> Optional[MediaRef]:
    """
    Segue os slots de um SourceMob CDCIDescriptor (proxy) para encontrar
    o SourceMob ImportDescriptor original que ele referencia.

    Padrão Avid observado:
      SourceMob 'reconstructed.N' [CDCIDescriptor]
        → Slot 1 → SourceClip → SourceMob 'CAM X' [ImportDescriptor]
    """
    try:
        for slot in proxy_src_mob.slots:
            seg = slot.segment
            src_clip = None
            if type(seg).__name__ == 'SourceClip':
                src_clip = seg
            elif type(seg).__name__ == 'Sequence':
                for comp in seg.components:
                    if type(comp).__name__ == 'SourceClip':
                        src_clip = comp
                        break
            if src_clip is None:
                continue
            try:
                inner_mob = src_clip.mob
            except Exception:
                continue
            if type(inner_mob).__name__ != 'SourceMob':
                continue
            inner_desc = getattr(inner_mob, 'descriptor', None)
            if inner_desc and type(inner_desc).__name__ == 'ImportDescriptor':
                url = read_url_from_descriptor(inner_desc)
                if url:
                    # Duração NÃO é lida daqui: o mob original aponta para a fita
                    # inteira (~48h). O caller (resolve_master_mob) aplica a duração
                    # correta a partir do slot do proxy.
                    return MediaRef(
                        mob_name=inner_mob.name,
                        url=url,
                        local_path=url_to_local_path(url),
                        descriptor_type='ImportDescriptor',
                    )
    except Exception as e:
        log.debug("Erro ao seguir proxy para original: %s", e)
    return None


def _get_app_code(mob) -> Optional[int]:
    """
    Lê o AppCode de um Mob (Avid-specific).
    Identificadores de Group Clip:
      AppCode = 4 → CompositionMob é um Group Clip (multicam container)
      AppCode = 5 → CompositionMob é a composition target da multicam
    """
    try:
        prop = mob.get('AppCode')
        if prop is None:
            return None
        val = prop.value if hasattr(prop, 'value') else prop
        return int(val) if val is not None else None
    except Exception:
        return None


def _is_group_mob(comp_mob) -> tuple[bool, str]:
    """
    Verifica se um CompositionMob é parte de um Group Clip (multicam).
    Retorna (is_group, group_name).

    AppCodes do Avid:
      4 = Group Clip container (bin-level, ex: 'FLATFILE.Grp.01')
      5 = Multicam composition target (referenciado pelos Selectors na timeline,
          ex: 'reconstructed.16')

    Critérios (qualquer um suficiente):
      1. AppCode ∈ {4, 5} — marcador explícito do Avid
      2. Múltiplos slots Picture — fallback quando AppCode não está presente
    """
    app_code = _get_app_code(comp_mob)
    if app_code in (4, 5):
        return True, getattr(comp_mob, 'name', '') or ""

    # Fallback: conta slots de vídeo — mais de um sugere multicam
    try:
        picture_slots = sum(
            1 for slot in comp_mob.slots
            if getattr(slot.segment, 'media_kind', '') in ('picture', 'Picture')
        )
        if picture_slots > 1:
            return True, getattr(comp_mob, 'name', '') or ""
    except Exception:
        pass

    return False, ""


def _resolve_subclip(sub_mob, want_slot_id=None) -> tuple[Optional[MediaRef], str, int]:
    """
    Resolve um subclipe (CompositionMob com Usage_SubClip) até o MediaRef original.

    Estrutura observada (clipes de câmera sincronizados com som direto):
      CompositionMob [Usage_SubClip]
        → slot Picture (1)   → SourceClip → MasterMob → VÍDEO da câmera
        → slot Sound  (2,3)  → SourceClip → MasterMob → SOM DIRETO (arquivo separado)

    `want_slot_id` seleciona QUAL slot resolver — é o `slot_id` do SourceClip da
    timeline que aponta para o subclipe (vídeo aponta o slot Picture; áudio aponta
    o slot Sound). Honrar isso é o que faz o áudio resolver para o SOM DIRETO em vez
    do áudio da câmera. Sem `want_slot_id`, cai no 1º slot Picture (retrocompat).

    Retorna (media_ref, nome_da_fonte, inner_offset), onde inner_offset é o
    start do SourceClip interno do subclipe (offset em frames dentro do
    MasterMob/original). O caller soma esse offset ao start do clipe na timeline.
    """
    inner_off = 0
    name = getattr(sub_mob, 'name', '') or ""
    try:
        for slot in sub_mob.slots:
            if want_slot_id is not None:
                if getattr(slot, 'slot_id', None) != want_slot_id:
                    continue
            elif getattr(slot, 'media_kind', '') not in ('Picture', 'picture'):
                continue
            seg = slot.segment
            # O slot pode ser SourceClip direto OU Sequence/OperationGroup
            # (ex.: slot Sound = Sequence → OperationGroup "Audio Gain" → SourceClip,
            # comum quando o áudio do subclipe é o próprio som da câmera). Desce até
            # o 1º SourceClip — senão o subclipe ficava sem fonte (offline).
            def _first_sc(x):
                k = type(x).__name__
                if k == 'SourceClip':
                    return x
                if k == 'OperationGroup':
                    for ip in (list(x.get('InputSegments') or [])):
                        r = _first_sc(ip)
                        if r:
                            return r
                    return None
                if k in ('Sequence', 'NestedScope'):
                    comps = list(x.segments) if hasattr(x, 'segments') else list(x.components)
                    for c in comps:
                        r = _first_sc(c)
                        if r:
                            return r
                return None
            inner_clip = _first_sc(seg)
            if inner_clip is None:
                continue
            inner_off = getattr(inner_clip, 'start', 0) or 0
            try:
                tgt = inner_clip.mob
            except Exception:
                return None, name, inner_off
            tgt_kind = type(tgt).__name__
            if tgt_kind == 'MasterMob':
                ref = resolve_master_mob(tgt)
                return ref, (getattr(tgt, 'name', '') or name), inner_off
            # Subclipe aninhado em outro subclipe (raro) — segue recursivo,
            # honrando o slot_id do clipe interno (vídeo/som).
            if tgt_kind == 'CompositionMob' and getattr(tgt, 'usage', None) == 'Usage_SubClip':
                ref, n2, off2 = _resolve_subclip(tgt, getattr(inner_clip, 'slot_id', None))
                return ref, (n2 or name), inner_off + off2
            return None, name, inner_off
    except Exception as e:
        log.debug("Erro ao resolver subclipe '%s': %s", name, e)
    return None, name, inner_off


def resolve_source_clip(sc) -> tuple[Optional[MediaRef], str, Optional[str], int]:
    """
    Resolve um SourceClip até o MediaRef.
    Retorna (media_ref, clip_name, mob_id, extra_source_offset).

    extra_source_offset é o offset adicional em frames (dentro da fonte) que o
    caller deve somar ao start do SourceClip na timeline — usado por subclipes
    (Usage_SubClip), onde a posição na fonte = clip.start (na timeline, offset no
    subclipe) + inner_clip.start (offset do subclipe na fonte). 0 nos demais casos.
    """
    try:
        mob = sc.mob
    except Exception:
        return None, "(gap)", None, 0

    mob_kind = type(mob).__name__
    mob_id = str(getattr(mob, 'mob_id', None) or "")
    mob_name = getattr(mob, 'name', '') or ""

    if mob_kind == 'MasterMob':
        ref = resolve_master_mob(mob)
        return ref, mob_name, mob_id, 0

    if mob_kind == 'CompositionMob':
        # Subclipe (Usage_SubClip): resolve até o original e devolve o offset interno.
        # Honra o slot_id do SourceClip da timeline → vídeo pega o slot Picture,
        # áudio pega o slot Sound (= SOM DIRETO, não o áudio da câmera).
        if getattr(mob, 'usage', None) == 'Usage_SubClip':
            ref, name, inner_off = _resolve_subclip(mob, getattr(sc, 'slot_id', None))
            return ref, (name or mob_name), mob_id, inner_off
        # reconstructed.N — flat file intermediário
        # O clip_name útil está no mob_name, mas a mídia real está nos slots internos
        return None, mob_name, mob_id, 0

    return None, mob_name, mob_id, 0


def _resolve_alt_segment(s) -> Optional[tuple[Optional[MediaRef], str, Optional[str], int]]:
    """Resolve um Alternate (ou o Selected) de um Selector até a fonte real,
    descendo em OperationGroup (ganho/efeito de áudio), Sequence, Selector aninhado
    e SourceClip→CompositionMob (subclipe/reconstructed). Captura o NOME mesmo sem
    ref (offline). Retorna (ref, name, mob_id, start) ou None se não houver fonte.
    Resolve o caso comum de selectors de ÁUDIO multicam: Selected=Filler e o áudio
    real fica num Alternate que é um OperationGroup."""
    sk = type(s).__name__
    base = getattr(s, 'start', 0) or 0

    def _ok(n: str) -> bool:
        return bool(n) and not n.startswith("(")

    if sk == 'SourceClip':
        r, n, mid, eoff = resolve_source_clip(s)
        if r is not None or _ok(n):
            return r, n, mid, base + eoff
        return None
    if sk == 'Selector':
        r, n, mid, _alts, _ig, _gn, ss = resolve_selector(s)
        if r is not None or _ok(n):
            return r, n, mid, ss
        return None
    if sk == 'Sequence':
        for c in s.components:
            got = _resolve_alt_segment(c)
            if got:
                return got
        return None
    if sk == 'OperationGroup':
        try:
            for ip in list(s.get('InputSegments') or []):
                got = _resolve_alt_segment(ip)
                if got:
                    return got
        except Exception:
            pass
        return None
    return None


def resolve_selector(
    sel,
) -> tuple[Optional[MediaRef], str, Optional[str], list[MediaRef], bool, str, int]:
    """
    Resolve um Selector: extrai o 'selected' e os 'alternates'.
    Para flat file / Group Clip, percorre reconstructed.N / AppCode=4 mob até a fonte real.

    Retorna:
        (media_ref, clip_name, mob_id, alternates, is_group_clip, group_clip_name, source_start)

    source_start é o offset correto em frames dentro da mídia original.
    Para Selectors que apontam para reconstructed.N:
        source_start = Selector.selected.start (offset na recon) + slot.SourceClip.start (offset na câmera)
    Para Selectors que apontam diretamente para MasterMob:
        source_start = Selector.selected.start
    """
    alternates: list[MediaRef] = []
    is_group = False
    group_name = ""

    # ── Selected ──────────────────────────────────────────────────────────
    try:
        selected_prop = sel.get('Selected')
        selected = selected_prop.value if hasattr(selected_prop, 'value') else selected_prop
    except Exception:
        return None, "(selector sem selected)", None, [], False, "", 0

    if type(selected).__name__ != 'SourceClip':
        # 'Selected' pode ser ScopeReference (ângulo que herda V1), Filler (áudio
        # multicam silencioso) ou outro tipo sem fonte direta. Tenta o próprio
        # Selected e depois cada Alternate, descendo em OperationGroup/Sequence/
        # Selector — senão o segmento ficava "(selector: tipo inesperado)" e perdido.
        try:
            for cand in [selected] + (list(sel.get('Alternates')) or []):
                got = _resolve_alt_segment(cand)
                if got:
                    r, n, mid, st = got
                    return r, n, mid, [], False, "", st
        except Exception as e:
            log.debug("Selector com Selected não-SourceClip; alternates falharam: %s", e)
        return None, "(selector: tipo inesperado)", None, [], False, "", 0

    # O selected pode apontar direto para MasterMob ou para reconstructed.N / Group Clip
    try:
        mob = selected.mob
    except Exception:
        return None, "(gap)", None, [], False, "", 0

    mob_kind = type(mob).__name__
    mob_name = getattr(mob, 'name', '') or ""
    mob_id = str(getattr(mob, 'mob_id', None) or "")
    slot_id = getattr(selected, 'slot_id', None)
    selector_start = getattr(selected, 'start', 0) or 0

    if mob_kind == 'MasterMob':
        ref = resolve_master_mob(mob)
        return ref, mob_name, mob_id, [], False, "", selector_start

    # CompositionMob (reconstructed.N ou Group Clip AppCode=4) — resolver via slot_id
    source_start = selector_start   # fallback: só o offset do Selector
    if mob_kind == 'CompositionMob' and slot_id is not None:
        ref, clip_name, is_group, group_name, slot_start, slot_offset = _resolve_recon_slot(mob, slot_id)
        # Offset real na câmera = clip.start + (posição do Selector no reconstructed
        # − posição do SourceClip dentro do slot). Subtrair slot_offset corrige o
        # multicam, onde o slot é [Filler, SourceClip(câmera), Filler].
        source_start = slot_start + max(0, selector_start - slot_offset)
    else:
        ref, clip_name, mob_id, _extra_off = resolve_source_clip(selected)
        source_start = selector_start + _extra_off

    # ── Alternates ────────────────────────────────────────────────────────
    try:
        alt_list = list(sel.get('Alternates'))
        for alt in alt_list:
            if type(alt).__name__ != 'SourceClip':
                continue
            try:
                alt_mob = alt.mob
            except Exception:
                continue
            alt_slot_id = getattr(alt, 'slot_id', None)
            if type(alt_mob).__name__ == 'CompositionMob' and alt_slot_id is not None:
                alt_ref, _, _, _, _, _ = _resolve_recon_slot(alt_mob, alt_slot_id)
            elif type(alt_mob).__name__ == 'MasterMob':
                alt_ref = resolve_master_mob(alt_mob)
            else:
                alt_ref = None
            if alt_ref:
                alternates.append(alt_ref)
    except Exception as e:
        log.debug("Erro ao resolver alternates do Selector: %s", e)

    return ref, clip_name or mob_name, mob_id, alternates, is_group, group_name, source_start


def _resolve_recon_slot(
    comp_mob, slot_id: int
) -> tuple[Optional[MediaRef], str, bool, str, int, int]:
    """
    Resolve um slot específico de um CompositionMob intermediário (reconstructed.N
    ou Group Clip AppCode=4/5).

    Retorna (media_ref, clip_name, is_group_clip, group_clip_name,
             slot_source_start, slot_seq_offset).

    - slot_source_start = atributo 'start' do SourceClip (offset dentro do MasterMob).
    - slot_seq_offset   = POSIÇÃO do SourceClip dentro da Sequence do slot, isto é,
      a soma dos Fillers que o antecedem. O offset real dentro da mídia é:
          source_start = slot_source_start + (selector.start − slot_seq_offset)
      Subtrair slot_seq_offset é essencial: no multicam, o slot é
      [Filler N, SourceClip(câmera), Filler M] e o SourceClip começa na posição N
      da timeline do reconstructed — sem subtrair N o frame extraído fica adiantado.

    Casos suportados para a estrutura do slot.segment:
      - Sequence com componentes [Filler*, SourceClip, Filler*]
        (multicam target AppCode=5, slot pode ter Fillers antes/depois)
      - SourceClip direto (sem Sequence wrapper)
      - Selector (para Group Clip AppCode=4 onde slots têm Selector)
    """
    is_group, group_name = _is_group_mob(comp_mob)

    def _resolve_clip(clip) -> tuple[Optional[MediaRef], str, int]:
        """Resolve um SourceClip ou Selector para MediaRef + name + start offset."""
        c_kind = type(clip).__name__
        c_start = getattr(clip, 'start', 0) or 0
        if c_kind == 'SourceClip':
            try:
                inner_mob = clip.mob
            except Exception:
                return None, "", 0
            inner_kind = type(inner_mob).__name__
            if inner_kind == 'MasterMob':
                ref = resolve_master_mob(inner_mob)
                return ref, getattr(inner_mob, 'name', '') or "", c_start
            elif inner_kind == 'CompositionMob':
                # Group Clip aninhado: segue o slot_id internamente
                inner_slot_id = getattr(clip, 'slot_id', None)
                if inner_slot_id is not None:
                    r, n, _, _, ss, _soff = _resolve_recon_slot(inner_mob, inner_slot_id)
                    if r:
                        return r, n, c_start + ss
        elif c_kind == 'Selector':
            try:
                selp = clip.get('Selected')
                sel = selp.value if hasattr(selp, 'value') else selp
            except Exception:
                return None, "", 0
            if type(sel).__name__ == 'SourceClip':
                return _resolve_clip(sel)
        return None, "", 0

    try:
        for slot in comp_mob.slots:
            if getattr(slot, 'slot_id', None) != slot_id:
                continue
            seg = slot.segment
            seg_kind = type(seg).__name__

            # SourceClip ou Selector direto: tenta resolver (offset 0 — sem Fillers)
            if seg_kind in ('SourceClip', 'Selector'):
                ref, name, start = _resolve_clip(seg)
                if ref:
                    return ref, name, is_group, group_name, start, 0
                continue

            # Sequence: procura o 1º SourceClip/Selector, acumulando a posição
            # (soma dos Fillers anteriores) para devolver como slot_seq_offset.
            if hasattr(seg, 'components'):
                pos = 0
                for c in seg.components:
                    c_kind = type(c).__name__
                    if c_kind in ('SourceClip', 'Selector'):
                        ref, name, start = _resolve_clip(c)
                        if ref:
                            return ref, name, is_group, group_name, start, pos
                        break  # encontrou clip mas não resolveu → desiste deste slot
                    # Filler ou outro: avança a posição e segue procurando
                    pos += getattr(c, 'length', 0) or 0
    except Exception as e:
        log.debug("Erro ao resolver slot %s de %s: %s", slot_id, comp_mob.name, e)
    return None, "", is_group, group_name, 0, 0


# ── Parser principal ──────────────────────────────────────────────────────

def parse_aaf(path: str) -> dict:
    """
    Lê um arquivo AAF e retorna a lista de segmentos de vídeo.

    Retorna:
        {
            "segments": [Segment.to_dict(), ...],
            "timeline_fps": float,
            "total_segments": int,
            "has_nested_scope": bool,
            "composition_name": str,
        }
    """
    aaf_path = Path(path)
    if not aaf_path.exists():
        raise FileNotFoundError(f"AAF não encontrado: {path}")

    log.info("Parseando AAF: %s", aaf_path.name)
    segments: list[Segment] = []

    with aaf2.open(str(aaf_path), "r") as f:
        compositions = list(f.content.toplevel())
        if not compositions:
            raise ValueError("AAF não contém nenhuma CompositionMob.")

        main_comp = compositions[0]
        comp_name = getattr(main_comp, 'name', '') or ""
        log.info("Composition: '%s'", comp_name)

        slots = list(main_comp.slots)

        # Filtra apenas tracks de vídeo (Picture)
        video_slots = [
            s for s in slots
            if s.segment and getattr(s.segment, 'media_kind', '') in ('picture', 'Picture')
        ]
        log.info("Video slots encontrados: %d", len(video_slots))

        has_nested_scope = False
        timeline_fps = 25.0

        for track_idx, slot in enumerate(video_slots):
            edit_rate = getattr(slot, 'edit_rate', None)
            fps = float(edit_rate) if edit_rate else 25.0
            timeline_fps = fps
            track_num = track_idx + 1
            seg = slot.segment
            seg_kind = type(seg).__name__

            log.info("Processando Slot %s | fps=%.4f | tipo=%s",
                     getattr(slot, 'slot_id', '?'), fps, seg_kind)

            if seg_kind == 'NestedScope':
                has_nested_scope = True
                _parse_nested_scope(seg, fps, track_num, segments)

            elif seg_kind == 'Sequence':
                _parse_sequence(seg, fps, track_num, 0, segments)

            else:
                log.warning("Tipo de segmento inesperado no video slot: %s", seg_kind)

        # ── Tracks de ÁUDIO ──────────────────────────────────────────────────
        # Captados p/ match/relink/atalhos (mesmas fontes: som direto, trilha, SFX),
        # mas NÃO desenhados na timeline (marcados is_audio; a UI filtra). Reusa o
        # mesmo processamento de Sequence/NestedScope do vídeo.
        sound_slots = [
            s for s in slots
            if s.segment and getattr(s.segment, 'media_kind', '') in ('sound', 'Sound')
        ]
        log.info("Sound slots encontrados: %d", len(sound_slots))
        audio_start = len(segments)
        for a_idx, slot in enumerate(sound_slots):
            edit_rate = getattr(slot, 'edit_rate', None)
            a_fps = float(edit_rate) if edit_rate else timeline_fps
            a_track = 1000 + a_idx        # faixa fictícia (não usada no desenho)
            seg = slot.segment
            seg_kind = type(seg).__name__
            try:
                if seg_kind == 'NestedScope':
                    _parse_nested_scope(seg, a_fps, a_track, segments)
                elif seg_kind == 'Sequence':
                    _parse_sequence(seg, a_fps, a_track, 0, segments)
            except Exception as e:
                log.warning("Falha ao parsear sound slot %s: %s",
                            getattr(slot, 'slot_id', '?'), e)
        for s in segments[audio_start:]:
            s.is_audio = True

        # TC inicial da timeline (StartTimecode do Avid, ex.: 01:00:00:00) — só p/ exibição.
        start_frames, drop_frame = _read_start_tc(main_comp, timeline_fps)

        # Marcadores/locators da timeline (EventMobSlot DescriptiveMarker).
        markers = read_markers(main_comp, timeline_fps)
        for mk in markers:
            mk["tc"] = _frames_to_tc_df(start_frames + mk["position"],
                                        timeline_fps, drop_frame)

    log.info("Parsing concluído: %d segmento(s) extraído(s) · start_tc=%s · drop=%s",
             len(segments), _frames_to_tc_df(start_frames, timeline_fps, drop_frame), drop_frame)
    return {
        "segments": [s.to_dict() for s in segments],
        "timeline_fps": timeline_fps,
        "total_segments": len(segments),
        "has_nested_scope": has_nested_scope,
        "composition_name": comp_name,
        "timeline_start_frames": start_frames,
        "timeline_drop_frame": drop_frame,
        "timeline_start_tc": _frames_to_tc_df(start_frames, timeline_fps, drop_frame),
        "markers": markers,
    }


def _parse_nested_scope(nested, fps: float, track_num: int, out: list[Segment]) -> None:
    """
    Processa um NestedScope (flat file Avid).

    Estrutura interna:
      sub-seq 0 = V1 base: Selectors, SourceClips, OperationGroups com mídia real.
      sub-seq 1 = V2 efeitos: ScopeReferences (transparentes) + OperationGroups (Motion
                  Control, Avid Titler+) com possíveis SourceClips independentes.
      sub-seq 2+ = V3, V4 ... (raro, mas possível).

    ScopeReferences são ignoradas — apenas avançam o cursor de tempo sem criar segmento.
    OperationGroups e SourceClips em V2+ geram segmentos no track correspondente.
    """
    sequences = list(nested.slots)
    if not sequences:
        log.warning("NestedScope sem slots internos.")
        return

    # Sub-seq 0 → V1 base (clipes reais)
    v1_seq = sequences[0]
    _parse_sequence(v1_seq, fps, track_num, 0, out)

    # Sub-seqs 1, 2, ... → V2, V3, ... (efeitos / overlays)
    # Cada sub-sequência é um track independente na timeline.
    for i in range(1, len(sequences)):
        sub_seq = sequences[i]
        sub_track = track_num + i      # V1+1=V2, V1+2=V3, ...
        log.info("NestedScope sub-seq %d → V%d", i, sub_track)
        # Parseia a sub-seq como track independente
        _parse_sequence(sub_seq, fps, sub_track, 0, out)
        # Também anotamos has_graphic_overlay nos segmentos de V1
        # (informa o matcher visual de que frames podem ter título/efeito sobre eles)
        _annotate_graphic_overlays(sub_seq, fps, out)


def _parse_sequence(seq, fps: float, track_num: int,
                    timeline_offset: int, out: list[Segment]) -> None:
    """
    Processa uma Sequence e adiciona os segmentos à lista out.
    timeline_offset é o frame inicial desta sequence na timeline principal.
    """
    tc_pos = timeline_offset

    # Em geral `seq` é uma Sequence; mas um sub-slot de NestedScope pode ser um
    # componente nu (ScopeReference/OperationGroup/SourceClip) sem `.components`.
    components = seq.components if hasattr(seq, 'components') else [seq]
    for comp in components:
        kind = type(comp).__name__
        length = getattr(comp, 'length', 0) or 0

        if kind == 'Filler':
            # Gap — registra para manter o mapa de tempo correto
            seg = Segment(
                timeline_tc_in=frames_to_tc(tc_pos, fps),
                timeline_tc_out=frames_to_tc(tc_pos + length, fps),
                duration_frames=length,
                source_start_frames=0,
                source_fps=fps,
                clip_name="(gap)",
                track=track_num,
                is_gap=True,
            )
            out.append(seg)
            tc_pos += length

        elif kind == 'Transition':
            # Dissolve/wipe: a transição é o OVERLAP entre o clipe anterior (A) e
            # o próximo (B). Ao chegar aqui, tc_pos == fim de A. A região de overlap
            # na timeline é [fim_A - length, fim_A], e B começa em fim_A - length.
            # (Antes registrávamos [tc_pos, tc_pos+length] — à frente de A, dentro do
            #  corpo de B — o que desenhava o marcador no lugar errado.)
            cutpoint = getattr(comp, 'cutpoint', 0) or 0
            t_in = max(0, tc_pos - length)
            seg = Segment(
                timeline_tc_in=frames_to_tc(t_in, fps),
                timeline_tc_out=frames_to_tc(tc_pos, fps),
                duration_frames=length,
                source_start_frames=0,
                source_fps=fps,
                clip_name="(transition)",
                track=track_num,
                is_transition=True,
                cutpoint=cutpoint,
            )
            out.append(seg)
            # Transição causa overlap: subtrai o length para o próximo clipe
            tc_pos -= length

        elif kind == 'SourceClip':
            ref, clip_name, mob_id, _extra_off = resolve_source_clip(comp)
            # source_start = offset do clipe na timeline + offset interno (subclipe)
            source_start = (getattr(comp, 'start', 0) or 0) + _extra_off
            seg = Segment(
                timeline_tc_in=frames_to_tc(tc_pos, fps),
                timeline_tc_out=frames_to_tc(tc_pos + length, fps),
                duration_frames=length,
                source_start_frames=source_start,
                source_fps=fps,
                clip_name=clip_name,
                track=track_num,
                mob_id=mob_id,
                media_ref=ref,
                source_slot_id=getattr(comp, 'slot_id', None),
                disabled=_clip_disabled(comp),
            )
            seg.motion_class, seg.conform_ratio, seg.relative_speed = _classify_motion(
                1.0, None, ref.source_fps if ref else None, fps)
            out.append(seg)
            tc_pos += length

        elif kind == 'Selector':
            # resolve_selector calcula o source_start correto:
            #   selector.start (offset em reconstructed.N) + slot.clip.start (offset na câmera)
            ref, clip_name, mob_id, alts, is_grp, grp_name, source_start = resolve_selector(comp)
            seg = Segment(
                timeline_tc_in=frames_to_tc(tc_pos, fps),
                timeline_tc_out=frames_to_tc(tc_pos + length, fps),
                duration_frames=length,
                source_start_frames=source_start,
                source_fps=fps,
                clip_name=clip_name,
                track=track_num,
                mob_id=mob_id,
                media_ref=ref,
                source_slot_id=getattr(comp, 'slot_id', None),
                is_group_clip=is_grp,
                group_clip_name=grp_name if is_grp else None,
                selector_alternates=alts,
                disabled=_clip_disabled(comp),
            )
            seg.motion_class, seg.conform_ratio, seg.relative_speed = _classify_motion(
                1.0, None, ref.source_fps if ref else None, fps)
            out.append(seg)
            tc_pos += length

        elif kind == 'OperationGroup':
            op = getattr(comp, 'operation', None)
            op_name = getattr(op, 'name', '') if op else ''

            # Detecta MotionEffect (velocidade). Por nome do OperationDef OU pela
            # presença de parâmetros de velocidade (alguns AAFs nomeiam 'Motion Control').
            has_me = False
            me_type = None
            speed_r = 1.0
            phase_off = 0
            offset_map: list = []
            speed_curve: list = []
            speed_kfs: list = []
            if any(k in op_name for k in ('Motion', 'Speed', 'MotionEffect', 'Timewarp')):
                has_me = True
                speed_r, _is_rev, phase_off, me_type, offset_map, speed_curve, speed_kfs = \
                    _parse_motion_effect_params(comp, op_length=length)
                log.debug(
                    "MotionEffect: op='%s' tipo='%s' speed=%.4f phase=%d offmap=%d",
                    op_name, me_type, speed_r, phase_off, len(offset_map),
                )

            # Extrai o SourceClip ou Selector dos inputs do OperationGroup.
            # Em pyaaf2, a propriedade é 'InputSegments' (não .input_segments).
            # Cada input pode ser uma Sequence que envolve o Selector/SourceClip real.
            # Estrutura observada em SBlend_v2:
            #   InputSegments[0]: Sequence → ScopeReference  (layer base, herda V1)
            #   InputSegments[1]: Sequence → Selector → SourceClip (clip sobreposto)
            inner_ref = None
            inner_name = op_name or "(operation group)"
            inner_start = 0
            inner_mob_id = None
            inner_is_grp = False
            inner_grp_name = ""
            inner_alts: list[MediaRef] = []
            found_source = False   # achou um SourceClip/Selector real sob o efeito

            def _is_real_name(n: str) -> bool:
                # Nome de fonte real (não placeholder nem o próprio nome do efeito).
                # Em AAF OFFLINE o ref vem None → o NOME é o que importa p/ o match.
                return bool(n) and not n.startswith("(") and n != op_name

            # O slot do SourceClip DENTRO do efeito = a trilha do master que o clipe lê (o canal
            # do som). Sem isto, todo clipe de som com efeito (ganho, EQ) perdia o canal (medido
            # 2026-09-29: 34 de 304 no começo da PRODA, caso U03).
            slot_dentro = [None]

            def _resolve_input(s):
                """Resolve um input do OperationGroup → (ref, name, mob_id, start, alts,
                is_grp, grp). Captura o NOME mesmo quando ref é None (offline). None se
                não houver fonte real (ex.: efeito puro como Titler+/SBlend vazio)."""
                sk = type(s).__name__
                if sk == 'SourceClip':
                    slot_dentro[0] = getattr(s, 'slot_id', None)
                    r, n, mid, eoff = resolve_source_clip(s)
                    st = (getattr(s, 'start', 0) or 0) + eoff
                    if r is None and not _is_real_name(n):
                        # SourceClip → CompositionMob (reconstructed.N): desce o slot
                        try:
                            scm = s.mob
                            sid = getattr(s, 'slot_id', None)
                            if type(scm).__name__ == 'CompositionMob' and sid is not None:
                                r2, n2, ig2, gn2, ss2, soff2 = _resolve_recon_slot(scm, sid)
                                if r2 is not None or _is_real_name(n2):
                                    return (r2, n2 or n, mid,
                                            st + max(0, ss2 - soff2), [], ig2, gn2)
                        except Exception as _e:
                            log.debug("SourceClip→CompositionMob falhou: %s", _e)
                    if r is not None or _is_real_name(n):
                        return (r, n, mid, st, [], False, "")
                    return None
                if sk == 'Selector':
                    r, n, mid, alts, ig, gn, ss = resolve_selector(s)
                    if r is not None or _is_real_name(n):
                        return (r, n, mid, ss, alts, ig, gn)
                    return None
                if sk == 'Sequence':
                    for sub in s.components:
                        got = _resolve_input(sub)
                        if got:
                            return got
                    return None
                if sk == 'OperationGroup':
                    # Efeito aninhado (ex.: SpatialAdapter/FrameFlex envolvendo um
                    # MotionEffect de velocidade que envolve o clipe). Desce nos inputs
                    # do op interno até a fonte real. Se for um motion effect, captura
                    # a velocidade p/ propagar ao segmento externo.
                    nonlocal has_me, me_type, speed_r, phase_off, offset_map, speed_curve, speed_kfs
                    inner_op = getattr(s, "operation", None)
                    inner_op_name = getattr(inner_op, "name", "") if inner_op else ""
                    if not has_me and any(k in inner_op_name
                                          for k in ('Motion', 'Speed', 'MotionEffect', 'Timewarp')):
                        try:
                            speed_r, _rev, phase_off, me_type, offset_map, speed_curve, speed_kfs = \
                                _parse_motion_effect_params(s, op_length=getattr(s, "length", 0) or 0)
                            has_me = True
                        except Exception as _e:
                            log.debug("Velocidade aninhada não lida: %s", _e)
                    try:
                        for ip in list(s.get('InputSegments')):
                            got = _resolve_input(ip)
                            if got:
                                return got
                    except Exception:
                        pass
                    return None
                return None

            try:
                for inp_seq in list(comp.get('InputSegments')):
                    got = _resolve_input(inp_seq)
                    if got:
                        (inner_ref, inner_name, inner_mob_id, inner_start,
                         inner_alts, inner_is_grp, inner_grp_name) = got
                        found_source = True
                        break
            except Exception as e:
                log.debug("Erro ao extrair inputs do OperationGroup '%s': %s", op_name, e)

            # is_effect só quando NÃO há fonte real sob o efeito (Avid Titler+, SBlend
            # vazio). Em AAF offline a fonte tem nome mas não ref → ainda assim casa por nome.
            is_effect_only = not found_source

            # Classifica o efeito (informa o editor; geométricos são reproduzíveis no frame)
            effect_desc = _classify_effect(comp, op_name, speed_r, me_type)

            seg = Segment(
                timeline_tc_in=frames_to_tc(tc_pos, fps),
                timeline_tc_out=frames_to_tc(tc_pos + length, fps),
                duration_frames=length,
                source_start_frames=inner_start,
                source_fps=fps,
                clip_name=inner_name,
                track=track_num,
                mob_id=inner_mob_id,
                media_ref=inner_ref,
                is_effect=is_effect_only,
                has_motion_effect=has_me,
                motion_effect_type=me_type,
                speed_ratio=speed_r if has_me else 1.0,
                phase_offset=phase_off if has_me else 0,
                source_offset_map=offset_map if has_me else [],
                speed_curve=speed_curve if has_me else [],
                speed_keyframes=speed_kfs if has_me else [],
                effects=[effect_desc],
                has_reframe='Motion Control' in op_name,
                reframe_mode=_detect_reframe_mode(comp),
                source_slot_id=slot_dentro[0] if found_source else None,
                is_group_clip=inner_is_grp,
                group_clip_name=inner_grp_name if inner_is_grp else None,
                selector_alternates=inner_alts,
                disabled=_clip_disabled(comp),
            )
            seg.motion_class, seg.conform_ratio, seg.relative_speed = _classify_motion(
                speed_r if has_me else 1.0, me_type if has_me else None,
                inner_ref.source_fps if inner_ref else None, fps)
            out.append(seg)
            tc_pos += length

        elif kind == 'ScopeReference':
            # Referência a outro track interno — não é um clipe independente.
            # Não gera segmento próprio; o relink é herdado de V1.
            # Apenas avança o cursor de tempo.
            tc_pos += length

        else:
            log.debug("Componente ignorado: %s (length=%d)", kind, length)
            tc_pos += length


def _annotate_graphic_overlays(v2_seq, fps: float, segments: list[Segment]) -> None:
    """
    Percorre a Sequence V2 e marca como has_graphic_overlay=True os segmentos
    de V1 que têm um OperationGroup 'Avid Titler+' (ou similar) acima deles.
    """
    tc_pos = 0
    GRAPHIC_OPS = ('Avid Titler+', 'Avid Title Tool', 'Blend')

    components = v2_seq.components if hasattr(v2_seq, 'components') else [v2_seq]
    for comp in components:
        kind = type(comp).__name__
        length = getattr(comp, 'length', 0) or 0

        if kind == 'OperationGroup':
            op = getattr(comp, 'operation', None)
            op_name = getattr(op, 'name', '') if op else ''
            is_graphic = any(g in op_name for g in GRAPHIC_OPS)

            if is_graphic:
                # Marca todos os segmentos de V1 que se sobrepõem a este TC range
                for seg in segments:
                    if seg.is_gap or seg.is_transition:
                        continue
                    seg_in  = _tc_to_frames(seg.timeline_tc_in, fps)
                    seg_out = _tc_to_frames(seg.timeline_tc_out, fps)
                    if seg_in < tc_pos + length and seg_out > tc_pos:
                        seg.has_graphic_overlay = True
                        log.debug(
                            "Gráfico '%s' sobre segmento '%s' (%s→%s)",
                            op_name, seg.clip_name, seg.timeline_tc_in, seg.timeline_tc_out
                        )

        tc_pos += length


def _tc_to_frames(tc: str, fps: float) -> int:
    """Converte HH:MM:SS:FF para frames totais."""
    parts = tc.replace(';', ':').split(':')
    if len(parts) != 4:
        return 0
    hh, mm, ss, ff = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return (hh * 3600 + mm * 60 + ss) * round(fps) + ff
