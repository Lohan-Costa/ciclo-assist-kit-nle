#!/usr/bin/env python3
"""Tradutor AAF -> composição .avb (backend AVB do Relinker).

Autora uma CompositionMob nova (timeline) numa bin de mídia AMA-online, a partir dos segmentos
do parser neutro do Relinker (aaf/parser.py) OU de um AAF direto (modo CLI/regressão). Cobre
cortes, gaps, transições (dissolve/dip/fade), efeitos geométricos, velocidade (motion, incl.
rampa Bézier), áudio (combiner/awarp/ganho/AudioSuite), múltiplas trilhas e rate.

Os templates de EFEITO são project-neutral: carregados do templates.json EMBUTIDO no pacote
(capture_templates). Os GOLD só são tocados p/ REGERAR esse JSON (`--build-templates`) — dev-only,
via env AVB_GOLD_DIR; em runtime nada depende de mídia de nenhum projeto específico."""
import sys, os, random, uuid, json, math, logging
import avb
try:
    import aaf2                                     # necessário só p/ o front-end AAF (CLI/regressão)
except Exception:                                   # noqa: BLE001 — o sidecar passa segmentos já parseados
    aaf2 = None
from avb.core import AVBObject, AVBRefList
from avb.mobid import MobID as AVBMobID

log = logging.getLogger(__name__)

# GOLD (gabaritos de efeito) — só p/ regenerar o templates.json embutido (dev). NÃO usados em runtime.
# Default vazio (project-neutral): p/ regenerar, aponte AVB_GOLD_DIR p/ a pasta de gabaritos.
_GOLD_DIR = os.environ.get("AVB_GOLD_DIR", "")
def _gold(*parts):
    return os.path.join(_GOLD_DIR, *parts)
_BUILD = "--build-templates" in sys.argv    # regenera o templates.json a partir dos gabaritos
GOLD = _gold("AMOSTRAS DE FASES", "FASE 1", "FASE 1 FADE.avb")
# tabela de rates: (num,den) -> (edit_rate float, tc_fps, SEQUENCE_FORMAT_TYPE, format_string)  [HD 1080p]
RATE = {
    (24000, 1001): (23.976, 24, 9,  'HD 1080p/23.976'),
    (30000, 1001): (29.97,  30, 22, 'HD 1080p/29.97'),
    (25, 1):       (25.0,   25, 16, 'HD 1080p/25'),  # 16 MEDIDO no MC 2024.6 (sequência feita à mão, 2026-10-31); o 13 DERRUBAVA o MC (CompressionManager.c 11276)
    (24, 1):       (24.0,   24, 7,  'HD 1080p/24'),
}
def resolve_rate(num, den):
    if (num, den) in RATE:
        return RATE[(num, den)]
    er = num / den
    fps = round(er)
    return (round(er, 3), fps, 9, 'HD 1080p/%g' % round(er, 3))  # fallback (fmt_type incerto)

ER = 29.97          # setado dinamicamente no main a partir do edit_rate do AAF
MAXLEN = 2147483647
COMP_PREFIX = bytes.fromhex("060a2b340101010501010f1013000000")

# PONTE de mob_id: {AAF_master_hex -> media_bin_master_hex}. Vazio => identidade (regressão intacta).
# Carregado do env AVB_REMAP (CLI) OU setado via set_remap() (sidecar/API). Só masters entram na
# ponte; subclip/grupo/container passam direto.
REMAP = {}
if not _BUILD and os.environ.get("AVB_REMAP"):
    REMAP = json.load(open(os.environ["AVB_REMAP"], encoding="utf-8"))
def set_remap(d):
    """define a ponte de mob_id AAF->media (dict). Usado pela API/sidecar em vez do env AVB_REMAP."""
    global REMAP
    REMAP = dict(d or {})
def _R(h):
    return REMAP.get(h, h)
# {media_hex -> comprimento do master (frames)} — p/ CLAMPAR o OUT dos clipes ao fim da mídia
# (senão a timeline referencia além do master -> PMM_INSUFFICIENT_MEDIA no Avid). Vazio = sem clamp.
_MASTER_LEN = {}
def set_master_len(d):
    global _MASTER_LEN
    _MASTER_LEN = dict(d or {})

# HANDLE p/ masters OFFLINE: uma transição precisa que o clipe ANTES dela tenha (L-cutpoint) frames de
# mídia DEPOIS do out, e o clipe DEPOIS tenha cutpoint frames ANTES do in (regra medida na bin nativa:
# handle_after_A >= L-C, handle_before_B >= C; a bin real cumpre sempre, via subclipes com handle do
# master). Masters online (arquivo de câmera real) têm handle de sobra; os OFFLINE (mídia ausente,
# autorada com comprimento = span exato) NÃO — a transição referenciava além do master offline ->
# "Range specified for Dup is outside range of component" no MC. Fix: autora o master offline com H
# frames de folga em CADA lado e desloca os clipes offline +H (centraliza). Mídia offline é sintética,
# então a folga é grátis. `_OFFLINE_HEXES`=hexes finais dos masters offline; `_OFFLINE_H`=frames.
_OFFLINE_HEXES = set()
_OFFLINE_H = 0
def offline_handle_frames(segments):
    """H = maior transição da timeline + margem (cobre L-C e C de qualquer transição). 0 se não há."""
    mx = max((int(s.get("duration_frames") or 0) for s in segments if s.get("is_transition")), default=0)
    return (mx + 12) if mx else 0
def set_offline_handles(hexes, h):
    global _OFFLINE_HEXES, _OFFLINE_H
    _OFFLINE_HEXES = set(hexes or ())
    _OFFLINE_H = int(h or 0)
DROP_UNTEMPLATED = os.environ.get("AVB_DROP_FX") == "1"   # efeito sem template -> mantém o clipe
PRIM = (int, float, str, bool, bytes, bytearray, type(None))
OP_MAP = {"VideoDissolve_2": "EFF2_BLEND_DISSOLVE", "Dip_2": "EFF2_BLEND_DIP",
          "Audio Dissolve": "BLEND_AUDIO_DISSOLVE"}
EFEITO_GOLD = _gold("AMOSTRAS DE FASES", "FASE 1", "FASE 1 EFEITO.avb")
VELOC_GOLD = _gold("AMOSTRAS DE FASES", "FASE 1", "FASE 1 VELOCIDADE.avb")
FX_MAP = {"PaintResize_v2": "EFF2_BLEND_RESIZE", "Picture-In-Picture_v2": "EFF2_BLEND_PIP", "SBlend_v2": "EFF2_SBLEND",
          "RGBColorCorrect_2": "EFF2_RGB_COLOR_CORRECTION",                 # correção de cor (multiefeito)
          "SubCap": "E4FE520A-B815-447F-A969-2D5E1C5F6C14"}                 # plugin SubCap (legenda; effect_id=GUID)
MULTIEFEITO_GOLD = _gold("BIN", "MULTIEFEITO.avb")
MOTION_OP = "Motion Control"
SPEED_DEF = "72559a80-24d7-11d3-8a50-0050040ef7d2"      # speed_ratio (ConstantValue) no AAF
SPEED_MAP_DEF = "8d56827c-847e-11d5-935a-50f857c10000"  # PARAM_SPEED_MAP_U (gráfico Speed, VaryingValue)
# ---- áudio ----
COMBINER_OP = "Audio Channel Combiner"                  # clipe estéreo: junta 2 canais
AWARP_OP = "Audio Warp"                                 # velocidade de áudio (simples: só speed_ratio)
ESTEREO_GOLD = _gold("AMOSTRAS DE FASES", "FASE 2 - AUDIO", "FASE 2 - AUDIO ESTEREO.avb")
GAIN_OP = "Audio Gain"                                  # ganho/volume de clip -> PanVolumeEffect (.avb)
GANHO_GOLD = _gold("AMOSTRAS DE FASES", "FASE 2 - AUDIO", "FASE 2 - AUDIO GANHO.avb")
FX_GOLD = _gold("AMOSTRAS DE FASES", "FASE 2 - AUDIO", "FASE 2 - AUDIO FX.avb")
ASPLUGIN_OP = "Audio Suite Plugin"                      # AudioSuite (plugin de áudio): reproduzível (não renderizado)
ASP_NAME_DEF = "76401b7f"; ASP_CHUNK_DEF = "80bcd031"; ASP_PRESET_DEF = "e735afe6"  # params AAF do AudioSuite
CHANMAP = {}                                            # {mob_hex: {aaf_slot_id: canal_rank}} (setado em read_aaf)
MCAM_CONTAINERS = set()                                 # mob_hexes de containers (groupoofter uc=5, name='')
CONTAINER_SLOT_RANK = {}                               # (container_hex, mk, slot_id) -> track_id

# ---------- serialize/materialize (capture-reuse) ----------
def serialize(o):
    if isinstance(o, AVBObject):
        return {'__class__': type(o).__name__, '__props__': {k: serialize(v) for k, v in o.property_data.items()}}
    if isinstance(o, AVBMobID):
        return {'__mobid__': o.bytes_le.hex()}
    if isinstance(o, uuid.UUID):
        return {'__uuid__': o.bytes_le.hex()}
    if isinstance(o, AVBRefList):                      # ParameterList etc (list-like AVB c/ instance_id)
        return {'__reflist__': type(o).__name__, '__items__': [serialize(x) for x in o]}
    if isinstance(o, (list, tuple)):
        return {'__list__': [serialize(x) for x in o]}
    if isinstance(o, bytearray):                        # JSON-safe (p/ templates.json embutido)
        return {'__bytearray__': bytes(o).hex()}
    if isinstance(o, bytes):
        return {'__bytes__': o.hex()}
    if isinstance(o, PRIM):
        return o
    try:
        return {'__attrs__': {k: serialize(v) for k, v in dict(o).items()}}
    except Exception:
        return {'__skip__': type(o).__name__}

def materialize(f, spec):
    if isinstance(spec, PRIM):
        return spec
    if isinstance(spec, dict):
        if '__mobid__' in spec: return AVBMobID(bytes_le=bytes.fromhex(spec['__mobid__']))
        if '__uuid__' in spec: return uuid.UUID(bytes_le=bytes.fromhex(spec['__uuid__']))
        if '__bytes__' in spec: return bytes.fromhex(spec['__bytes__'])
        if '__bytearray__' in spec: return bytearray.fromhex(spec['__bytearray__'])
        if '__reflist__' in spec:
            rl = getattr(f.create, spec['__reflist__'])()
            for x in spec['__items__']: rl.append(materialize(f, x))
            return rl
        if '__list__' in spec: return [materialize(f, x) for x in spec['__list__']]
        if '__attrs__' in spec:
            a = f.create.Attributes()
            for k, v in spec['__attrs__'].items(): a[k] = materialize(f, v)
            return a
        if '__skip__' in spec: return None
        if '__class__' in spec:
            cls = getattr(f.create, spec['__class__'])
            try: o = cls()                                # maioria (root injetado pelo factory)
            except TypeError:
                try: o = cls(25, None)                    # ex: efeitos (edit_rate, media_kind)
                except TypeError: o = cls(f)              # ex: ASPIPlugin(root) — exige root posicional
            for k, v in spec['__props__'].items():
                o.property_data[k] = materialize(f, v)
            return o
    return spec

# ---------- capturar templates do gabarito (transições + efeitos) ----------
def _pic_comps(path, media_kind="picture"):
    """varre TODAS as trilhas do media_kind (algumas podem estar vazias) e agrega os componentes."""
    specs, names, eids = [], [], []
    with avb.open(path) as f:
        comp = [m for m in f.content.mobs if getattr(m, "mob_type", None) == "CompositionMob" and getattr(m, "usage", None) is None][0]
        for t in comp.tracks:
            if getattr(t, "media_kind", None) != media_kind: continue
            if type(t.component).__name__ != "Sequence": continue
            for c in t.component.components:
                cn = type(c).__name__
                specs.append(serialize(c) if cn in ("TransitionEffect", "TrackEffect", "MotionEffect") else None)
                names.append(cn); eids.append(getattr(c, "effect_id", None))
    return specs, names, eids

TEMPLATES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates.json")

def capture_templates():
    """Templates de efeito p/ o capture-reuse. Carrega o templates.json EMBUTIDO
    (independe dos gabaritos em disco — pré-requisito p/ o export_avb no sidecar do
    relinker). Se o JSON não existir, cai p/ a captura dos gabaritos em disco.
    Regenerar o JSON: `avb_translate_aaf.py --build-templates`."""
    if os.path.exists(TEMPLATES_JSON):
        with open(TEMPLATES_JSON, encoding="utf-8") as fp:
            return json.load(fp)
    return _capture_from_gold()

def _capture_from_gold():
    tpl = {}            # effect_id -> spec
    # transições/efeitos de VÍDEO (trilha picture) + transições de ÁUDIO (trilha sound do FADE gold)
    for path, cls, mk in ((GOLD, "TransitionEffect", "picture"), (EFEITO_GOLD, "TrackEffect", "picture"),
                          (GOLD, "TransitionEffect", "sound"),
                          (ESTEREO_GOLD, "TrackEffect", "sound"),     # EFF2_AUDIO_CHANNEL_COMBINER
                          (ESTEREO_GOLD, "MotionEffect", "sound")):   # EFF_TIMEWARP.AUDIO_TIME_WARP
        specs, names, eids = _pic_comps(path, mk)
        for spec, nm, eid in zip(specs, names, eids):
            if nm == cls and spec is not None:
                tpl.setdefault(eid, spec)
    # motion: capturar um template de velocidade CONSTANTE LIMPO (1 control point, speed != 0)
    # — NÃO o freeze (cuja speed cp = 0.0, que era o bug "tudo 0%").
    with avb.open(VELOC_GOLD) as f:
        comp = [m for m in f.content.mobs if getattr(m, "mob_type", None) == "CompositionMob" and getattr(m, "usage", None) is None][0]
        for c in next(t.component.components for t in comp.tracks if getattr(t, "media_kind", None) == "picture"):
            if type(c).__name__ != "MotionEffect": continue
            cps = c.property_data["param_list"][0].property_data["control_track"].property_data["control_points"]
            if len(cps) == 1 and cps[0].property_data.get("value", 0) > 1.0:   # POSITIVO (tw200), não reverse/freeze
                tpl["EFF_ADV_MOTION_CTL"] = serialize(c); break
    # áudio: PanVolumeEffect (ganho) + Selector (seleção de canal) — busca recursiva no gold GANHO
    def _find(node, want, hit):
        cn = type(node).__name__
        if cn == want and want not in hit: hit[want] = serialize(node)
        if cn == "Sequence":
            for c in node.components: _find(c, want, hit)
        for st in getattr(node, "tracks", None) or []:
            sub = getattr(st, "component", None)
            if sub is not None: _find(sub, want, hit)
    with avb.open(GANHO_GOLD) as f:
        comp = [m for m in f.content.mobs if getattr(m, "mob_type", None) == "CompositionMob" and getattr(m, "usage", None) is None][0]
        hit = {}
        for t in comp.tracks:
            if getattr(t, "media_kind", None) == "sound" and type(t.component).__name__ == "Sequence":
                _find(t.component, "PanVolumeEffect", hit); _find(t.component, "Selector", hit)
        if "PanVolumeEffect" in hit: tpl["__panvol__"] = hit["PanVolumeEffect"]
        if "Selector" in hit: tpl["__selector__"] = hit["Selector"]
    # MULTIEFEITO: efeitos novos (color-correction, SubCap) capturados por effect_id, busca RECURSIVA
    # (vivem aninhados dentro de NestedScope + de outros efeitos).
    def _find_eid(node, wanted, hit):
        eid = getattr(node, "effect_id", None)
        if eid in wanted and eid not in hit: hit[eid] = serialize(node)
        if type(node).__name__ == "Sequence":
            for c in node.components: _find_eid(c, wanted, hit)
        for st in getattr(node, "tracks", None) or []:
            sub = getattr(st, "component", None)
            if sub is not None: _find_eid(sub, wanted, hit)
    # SBlend/3DWarp tem param_list de tamanho VARIÁVEL por instância (9/15/18); cada uma é subsequência
    # de um SUPERSET canônico de 18. O template do EFEITO só tem 15 -> não gera as de 18. Captura a
    # instância com MAIS params (o superset, ordem canônica) e sobrescreve; a poda por AAF gera qualquer caso.
    def _find_fx(node, eid, acc):
        if getattr(node, "effect_id", None) == eid and node.property_data.get("param_list") is not None:
            acc.append(node)
        if type(node).__name__ == "Sequence":
            for c in node.components: _find_fx(c, eid, acc)
        for st in getattr(node, "tracks", None) or []:
            sub = getattr(st, "component", None)
            if sub is not None: _find_fx(sub, eid, acc)
    try:
        with avb.open(MULTIEFEITO_GOLD) as f:
            comp = [m for m in f.content.mobs if getattr(m, "mob_type", None) == "CompositionMob"
                    and getattr(m, "usage", None) is None][0]
            hit = {}; wanted = {"EFF2_RGB_COLOR_CORRECTION", "E4FE520A-B815-447F-A969-2D5E1C5F6C14"}
            for t in comp.tracks: _find_eid(t.component, wanted, hit)
            tpl.update(hit)
            for eid in ("EFF2_SBLEND", "EFF2_RGB_COLOR_CORRECTION",     # efeitos de param_list VARIÁVEL
                        "E4FE520A-B815-447F-A969-2D5E1C5F6C14"):        # SubCap (superset; conteúdo vem do AAF)
                insts = []
                for t in comp.tracks: _find_fx(t.component, eid, insts)
                if insts:
                    best = max(insts, key=lambda c: len(c.property_data.get("param_list") or []))
                    tpl[eid] = serialize(best)            # superset de params (ordem canônica)
    except Exception:
        pass  # gabarito ausente -> multiefeito indisponivel, resto do tradutor segue
    # AudioSuite: template por NOME de plugin (Gain/D-Verb/Time Shift...). Reproduz o efeito (NÃO é
    # renderizado: precomputed=None, envolve o clipe-fonte). A config (chunk) vem do AAF por instância.
    def _find_asp(node, acc):
        if type(node).__name__ == "AudioSuitePluginEffect": acc.append(node)
        if type(node).__name__ == "Sequence":
            for c in node.components: _find_asp(c, acc)
        for st in getattr(node, "tracks", None) or []:
            sub = getattr(st, "component", None); sub = getattr(sub, "value", sub)
            if sub is not None: _find_asp(sub, acc)
    for gold in (FX_GOLD, MULTIEFEITO_GOLD):
        try:
            with avb.open(gold) as f:
                comp = [m for m in f.content.mobs if getattr(m, "mob_type", None) == "CompositionMob"
                        and getattr(m, "usage", None) is None][0]
                asps = []
                for t in comp.tracks:
                    cc = getattr(t.component, "value", t.component)
                    _find_asp(cc, asps)
                for c in asps:
                    nm = dict(c.property_data.get("attributes") or {}).get("_EFFECT_PLUGIN_NAME")
                    if nm: tpl.setdefault("__asp__" + str(nm), serialize(c))
        except Exception:
            pass
    return tpl

# ---------- velocidade: keyframes + integral (Bézier) ----------
_TAN = {"PP_OUT_TANGENT_POS_U": "out_dt", "PP_OUT_TANGENT_VAL_U": "out_dv",
        "PP_IN_TANGENT_POS_U": "in_dt", "PP_IN_TANGENT_VAL_U": "in_dv"}

def extract_speed_kfs(param):
    """VaryingValue PARAM_SPEED_MAP_U -> [{t, speed, in_dt,in_dv,out_dt,out_dv, mode}]."""
    kfs = []
    try: points = list(param["PointList"].value)
    except Exception: return kfs
    for cp in points:
        h = {"out_dt": 0.0, "out_dv": 0.0, "in_dt": 0.0, "in_dv": 0.0, "mode": 1}
        try:
            for _pid, prop in cp.property_entries.items():
                val = prop.value
                if isinstance(val, list) and val and hasattr(val[0], "name"):
                    for cv in val:
                        nm = getattr(cv, "name", "")
                        if nm in _TAN: h[_TAN[nm]] = float(cv.value_at(0))
                        elif nm == "PP_TANGENT_MODE_U": h["mode"] = int(cv.value_at(0))
        except Exception: pass
        try: kfs.append({"t": float(cp.time), "speed": float(cp.value), **h})
        except Exception: pass
    kfs.sort(key=lambda k: k["t"])
    return kfs

def _bez(p, u):
    mt = 1.0 - u
    return mt*mt*mt*p[0] + 3*mt*mt*u*p[1] + 3*mt*u*u*p[2] + u*u*u*p[3]

def _eval_speed(kfs, x):
    if not kfs: return 1.0
    if x <= kfs[0]["t"]: return kfs[0]["speed"]
    if x >= kfs[-1]["t"]: return kfs[-1]["speed"]
    for i in range(len(kfs)-1):
        k0, k1 = kfs[i], kfs[i+1]
        if k0["t"] <= x <= k1["t"]:
            xs = (k0["t"], k0["t"]+k0["out_dt"], k1["t"]+k1["in_dt"], k1["t"])
            ys = (k0["speed"], k0["speed"]+k0["out_dv"], k1["speed"]+k1["in_dv"], k1["speed"])
            lo, hi = 0.0, 1.0
            for _ in range(40):
                u = (lo+hi)*0.5
                if _bez(xs, u) < x: lo = u
                else: hi = u
            return _bez(ys, (lo+hi)*0.5)
    return kfs[-1]["speed"]

def _offset_map(kfs, length):
    """integral da velocidade amostrada a cada 0.5 frame -> [(frame, src_pos)]."""
    out = [(0.0, 0.0)]; acc = 0.0; f = 0.0
    while f < length - 1e-9:
        a = _eval_speed(kfs, f); m = _eval_speed(kfs, f+0.5); b = _eval_speed(kfs, f+1.0)
        half1 = (a + 4*_eval_speed(kfs, f+0.25) + m)/6.0*0.5
        acc += half1; out.append((f+0.5, acc))
        half2 = (m + 4*_eval_speed(kfs, f+0.75) + b)/6.0*0.5
        acc += half2; out.append((f+1.0, acc)); f += 1.0
    return out

# ---------- ler edit do AAF ----------
def _aaf_inner_clip(og):
    """clip dentro de um OperationGroup -> (mob_hex, start, length). Pula ScopeReference/Filler."""
    for seg in og.segments:
        comps = getattr(seg, "components", [seg])
        for cc in comps:
            if type(cc).__name__ == "SourceClip":
                st = cc['StartTime'].value if 'StartTime' in cc else 0
                return (cc.mob_id.bytes_le.hex(), st, cc.length)
    return None

def _aaf_effect_inner(og, mk=None):
    """conteudo interno de um OperationGroup como ENTRY RECURSIVA (p/ multiefeito):
      - clip normal          -> ('clip', ...)
      - efeito aninhado       -> ('fx'/'motion'/..., ...) [efeito-dentro-de-efeito]
      - camada de ajuste      -> ('gap', ...) [todos os inputs sao ScopeReference = trilha de baixo]
    Pega o input 'de conteudo' (o que NAO e so ScopeReference/background) e desce nele."""
    content = None
    for seg in og.segments:
        comps = list(getattr(seg, "components", [seg]))
        meaningful = [c for c in comps if type(c).__name__ != "ScopeReference"]
        if meaningful:
            content = (seg, meaningful)   # ultimo input com conteudo real (input1 no SBlend)
    if content is None:
        return ("gap", None, 0, og.length, None)     # adjustment layer (so ScopeReference)
    seg, meaningful = content
    if len(meaningful) == 1:
        return _seg_entry(meaningful[0], mk)          # 1 componente: clip OU efeito aninhado
    # varios componentes: Sequence com padding [Filler, X, Filler] -> pegar o X nao-Filler
    # (NAO chamar _seg_entry(Sequence) — nao suportado, crasharia)
    non_fill = [c for c in meaningful if type(c).__name__ != "Filler"]
    if len(non_fill) >= 1:
        return _seg_entry(non_fill[0], mk)
    return ("gap", None, 0, og.length, None)          # so Fillers = ajuste tambem

def _chan(mob_hex, slot_id):
    """canal (track_id AVB) = rank do slot entre os slots de som do master; fallback slot-1."""
    m = CHANMAP.get(mob_hex)
    if m and slot_id in m: return m[slot_id]
    return (slot_id - 1) if slot_id and slot_id > 1 else (slot_id or 1)

def _aaf_combiner_clips(og):
    """SourceClips dentro de um OperationGroup 'Audio Channel Combiner' -> [(mob_hex, canal, start, len)]."""
    clips = []
    for seg in og.segments:
        sub = getattr(seg, "components", [seg])
        for cc in sub:
            if type(cc).__name__ == "SourceClip":
                st = cc['StartTime'].value if 'StartTime' in cc else 0
                mh = cc.mob_id.bytes_le.hex()
                clips.append((mh, _chan(mh, cc.slot_id), st, cc.length))
    return clips

def _read_selector(sel):
    """Selector AAF (Selected + Alternates) -> ('selector', [(mob,canal,start,len)...], selected_idx, len)."""
    chans = []
    selected = sel['Selected'].value if 'Selected' in sel else None
    alts = list(sel['Alternates'].value) if 'Alternates' in sel else []
    order = ([selected] if selected is not None else []) + alts   # .avb: selecionado 1º, depois alts
    for sc in order:
        if type(sc).__name__ != "SourceClip": continue
        st = sc['StartTime'].value if 'StartTime' in sc else 0
        mh = sc.mob_id.bytes_le.hex()
        chans.append((mh, _chan(mh, sc.slot_id), st, sc.length))
    return ("selector", chans, 0, sel.length, None)

def _read_mcam_sel(sel, mk):
    """Multicam Selector inline (timeline ou track de grupo) -> ('mcam_sel', [(cont_hex, track_id, start, len)...], sel_idx, len, None).
    Os SourceClips referenciam o container (groupoofter uc=5); track_id = rank do slot no container por mk."""
    sel_sc = sel['Selected'].value if 'Selected' in sel else None
    alts   = list(sel['Alternates'].value) if 'Alternates' in sel else []
    all_sc = ([sel_sc] if sel_sc is not None else []) + alts
    clips  = []
    for i, sc in enumerate(all_sc):
        if type(sc).__name__ != "SourceClip": continue
        cont_hex = sc.mob_id.bytes_le.hex()
        slot_id  = sc.slot_id
        track_id = CONTAINER_SLOT_RANK.get((cont_hex, mk, slot_id))
        if track_id is None: continue
        st = sc['StartTime'].value if 'StartTime' in sc else 0
        clips.append((cont_hex, track_id, st, sel.length, i == 0))
    if not clips: return _read_selector(sel)                       # fallback se mapa vazio
    clips.sort(key=lambda x: x[1])                                 # ordenar por track_id
    sel_idx = next((i for i, c in enumerate(clips) if c[4]), 0)   # índice do selecionado
    return ("mcam_sel", [(c[0], c[1], c[2], c[3]) for c in clips], sel_idx, sel.length, None)

def _read_gain(og, mk=None):
    """OperationGroup 'Audio Gain' -> ('gain', level_num, inner_entry, len). level = numerador/2^29.
    mk propagado p/ o inner (senao um Selector multicam dentro do gain nao seria detectado)."""
    level = None
    for p in og.parameters:
        try:
            v = p.value
            if type(v).__name__ == "AAFRational": level = int(v.numerator); break
        except Exception: pass
    inner = next((s for s in og.segments), None)        # 1º segmento = o clipe/selector embrulhado
    return ("gain", level, _seg_entry(inner, mk) if inner is not None else None, og.length, None)

def _seg_entry(seg, mk=None):
    """1 segmento AAF -> 1 entry (recursivo p/ aninhamento gain->selector->clip)."""
    cn = type(seg).__name__
    if cn == "SourceClip":
        st = seg['StartTime'].value if 'StartTime' in seg else 0
        return ("clip", seg.mob_id.bytes_le.hex(), st, seg.length, seg.slot_id)
    if cn in ("Filler", "ScopeReference"):
        return ("gap", None, 0, seg.length, None)
    if cn == "Sequence":     # ex: inner de audio warp que envolve uma Sequence -> pega o 1º comp real
        inner = next((c for c in seg.components if type(c).__name__ != "Filler"), None)
        return _seg_entry(inner, mk) if inner is not None else ("gap", None, 0, seg.length, None)
    if cn == "Selector":
        # detectar multicam: SC referencia container (groupoofter, name='')
        sel_sc = seg['Selected'].value if 'Selected' in seg else None
        if mk is not None and sel_sc is not None and type(sel_sc).__name__ == "SourceClip":
            if sel_sc.mob_id.bytes_le.hex() in MCAM_CONTAINERS:
                return _read_mcam_sel(seg, mk)
        return _read_selector(seg)
    if cn == "OperationGroup":
        op = seg.operation.name
        inner = _aaf_inner_clip(seg)
        if op == COMBINER_OP:
            return ("combiner", _aaf_combiner_clips(seg), None, seg.length, None)
        if op == GAIN_OP:
            return _read_gain(seg, mk)
        if op == AWARP_OP:
            sr = None
            for p in seg.parameters:
                try:
                    v = p.value
                    if type(v).__name__ == "AAFRational": sr = [int(v.numerator), int(v.denominator)]; break
                except Exception: pass
            comb = next((s for s in seg.segments if type(s).__name__ == "OperationGroup"
                         and s.operation.name == COMBINER_OP), None)
            clips = _aaf_combiner_clips(comb) if comb is not None else []
            comb_len = comb.length if comb is not None else seg.length
            inner_entry = None                       # warp de CLIPE SIMPLES (não combiner): capturar o inner
            if comb is None:
                inner_seg = next((s for s in seg.segments), None)
                inner_entry = _seg_entry(inner_seg, mk) if inner_seg is not None else None
            return ("awarp", sr, (clips, comb_len, inner_entry), seg.length, None)
        if op == MOTION_OP:
            sr = None; kfs = []
            for p in seg.parameters:
                try:
                    d = str(p['Definition'].value); tn = type(p).__name__
                    if d == SPEED_DEF and tn == "ConstantValue":
                        v = p.value; sr = [int(v.numerator), int(v.denominator)]
                    elif d == SPEED_MAP_DEF and tn == "VaryingValue":
                        kfs = extract_speed_kfs(p)
                except Exception: pass
            if not kfs and sr and sr[0]:
                kfs = [{"t": 0.0, "speed": sr[1] / sr[0], "in_dt": 0.0, "in_dv": 0.0, "out_dt": 0.0, "out_dv": 0.0, "mode": 1}]
            return ("motion", (sr, kfs), inner, seg.length, None)
        if op == ASPLUGIN_OP:
            # AudioSuite REPRODUZÍVEL (não é renderizado: envolve o clipe-fonte). Lê nome do plugin +
            # chunk (config por instância) + preset. Se não houver template do plugin, dropa (mantém fonte).
            name = None; chunk = None; preset = None
            for p in seg.parameters:
                try: d = str(p['Definition'].value)
                except Exception: continue
                try: v = p.value
                except Exception: continue
                if d.startswith(ASP_NAME_DEF): name = v
                elif d.startswith(ASP_CHUNK_DEF) and isinstance(v, (list, bytes, bytearray)): chunk = bytes(v)
                elif d.startswith(ASP_PRESET_DEF) and isinstance(v, (list, bytes, bytearray)): preset = bytes(v)
            return ("asplugin", name, _aaf_effect_inner(seg, mk), seg.length, (chunk, preset))
        params = {}
        for p in seg.parameters:
            try:
                d = str(p['Definition'].value)
            except Exception:
                continue
            try: params[d] = p.value
            except Exception: params[d] = _VARYING   # VaryingValue (curva): registra PRESENÇA (poda mantém), sem valor
        # inner RECURSIVO (multiefeito: efeito aninhado ou camada de ajuste sobre Filler)
        return ("fx", FX_MAP.get(op, op), _aaf_effect_inner(seg, mk), seg.length, params)
    raise SystemExit("comp AAF não suportado: %s" % cn)

def _read_row(comps, mk=None):
    """lê os componentes de uma Sequence (de uma trilha) -> linha do edit."""
    row = []
    for c in comps:
        if type(c).__name__ == "Transition":            # transição fica entre clips (não aninha)
            cp = c['CutPoint'].value if 'CutPoint' in c else 0
            op = c['OperationGroup'].value.operation.name
            row.append(("trans", OP_MAP.get(op, op), cp, c.length, None))
        else:
            row.append(_seg_entry(c, mk))
    return row

USAGE_UC = {"Usage_SubClip": 2, "Usage_LowerLevel": 4, "None": 5}  # AAF usage -> .avb usage_code

def _read_track_payload(seg, mk=None):
    """slot.segment de um comp mob -> payload do track (Sequence vira row; senão 1 entry)."""
    if type(seg).__name__ == "Sequence":
        return ("seq", _read_row(seg.components, mk))
    return ("seg", _seg_entry(seg, mk))

def _read_comp_mobs(f):
    """TODOS os CompositionMob não-top, não-master (subclip/grupo/container) -> {hex: def} p/ autorar.
    def = {mob_id_hex, usage_code, name, length, tracks:[(media_kind, tag, payload)]}."""
    out = {}
    for m in f.content.mobs:
        if type(m).__name__ != "CompositionMob": continue
        u = str(getattr(m, "usage", None))
        if u == "Usage_TopLevel": continue
        uc = USAGE_UC.get(u)
        if uc is None: continue
        trks = []; length = 0
        for s in m.slots:
            mks = str(s.media_kind)
            mk = "picture" if mks == "Picture" else ("sound" if mks == "Sound" else None)
            if mk is None: continue
            trks.append((mk,) + _read_track_payload(s.segment, mk))
            length = max(length, getattr(s.segment, "length", 0) or 0)
        out[m.mob_id.bytes_le.hex()] = {"mob_id_hex": m.mob_id.bytes_le.hex(), "usage_code": uc,
                                        "name": m.name, "length": length, "tracks": trks}
    return out

def read_aaf(path):
    tracks = []; rate = None   # tracks = [(kind, row), ...]  kind in {'picture','sound'}
    with aaf2.open(path, "r") as f:
        CHANMAP.clear()        # {mob_hex: {slot_id: rank}} — rank por media_kind (picture/sound separados)
        MCAM_CONTAINERS.clear(); CONTAINER_SLOT_RANK.clear()
        for m in f.content.mobs:
            cm = {}
            for kind in ("Picture", "Sound"):
                slots = sorted(s.slot_id for s in m.slots if str(s.media_kind) == kind)
                for i, sid in enumerate(slots): cm[sid] = i + 1
            if cm: CHANMAP[m.mob_id.bytes_le.hex()] = cm
            # containers (groupoofter uc=5): usage=None e name='' — montar mapa de rank por mk
            if getattr(m, "usage", "X") is None and getattr(m, "name", None) == "":
                mh = m.mob_id.bytes_le.hex()
                MCAM_CONTAINERS.add(mh)
                by_mk = {}
                for s in m.slots:
                    k = "picture" if str(s.media_kind) == "Picture" else "sound"
                    by_mk.setdefault(k, []).append(s.slot_id)
                for k, sids in by_mk.items():
                    for rank, sid in enumerate(sorted(sids)):
                        CONTAINER_SLOT_RANK[(mh, k, sid)] = rank + 1
        comp_mobs = _read_comp_mobs(f)
        comp = [m for m in f.content.mobs if getattr(m, "usage", None) == 'Usage_TopLevel'][0]
        name = comp.name
        for s in comp.slots:
            mk = str(s.media_kind)
            if mk in ("Picture", "picture"):
                kind = "picture"
            elif mk in ("Sound", "sound"):
                kind = "sound"           # SoundMasterTrack/metadados ficam de fora
            else:
                continue
            er = s.edit_rate
            if rate is None: rate = (int(er.numerator), int(er.denominator))
            seg = s.segment
            if type(seg).__name__ == "NestedScope":          # multipista: cada layer = uma trilha
                for layer in seg.slots:
                    lseg = layer.segment if hasattr(layer, "segment") else layer
                    tracks.append((kind, _read_row(lseg.components, kind)))
            else:
                tracks.append((kind, _read_row(seg.components, kind)))
    return name, tracks, rate, comp_mobs

# ---------- FRONT-END VIA RELINKER (vídeo): consome os Segments do parser do Relinker ----------
def _load_media_map():
    """{nome normalizado do master -> media hex} p/ o fallback por NOME (áudio via subclipe).
    Project-neutral: vem do env AVB_MEDIA_MAP (JSON {arquivo: {name, mob_id}}) emitido pelo
    media-bin builder; vazio se ausente (o casamento por mob_id direto cobre o vídeo)."""
    name2h = {}
    p = os.environ.get("AVB_MEDIA_MAP")
    if p and os.path.exists(p):
        try:
            for v in json.load(open(p, encoding="utf-8")).values():
                if isinstance(v, dict) and v.get("name"):
                    name2h[_norm_name(v["name"])] = v["mob_id"]
        except Exception:
            pass
    return name2h

def _urn2hex_from_aaf(path):
    """{str(mob_id) URN -> bytes_le.hex()} de todos os MasterMobs do AAF."""
    m2h = {}
    with aaf2.open(path, "r") as f:
        for m in f.content.mobs:
            if type(m).__name__ == "MasterMob":
                m2h[str(m.mob_id)] = m.mob_id.bytes_le.hex()
    return m2h

def _norm_name(s):
    s = (s or "").lower().strip()
    for e in (".wav", ".aif", ".aiff", ".mp4", ".mov", ".mp3"):
        if s.endswith(e):
            return s[:-len(e)]
    return s

MOTION_OFF = os.environ.get("AVB_NO_MOTION") == "1"   # kill-switch: dropa motion (comportamento antigo)
#: De onde veio a timeline ('avid', 'premiere', 'resolve'; None = não se sabe → trata como Avid, o comportamento
#: antigo) e a taxa dela. A rampa de OUTRO programa vai QUADRO A QUADRO pelo gráfico de POSIÇÃO (regra do autor,
#: 2026-10-12: a curva nativa só de Avid para Avid; `motor/rampa.py`); a do Avid, com a curva dele.
_ORIGEM = None
_TL_FPS = None

def set_origem(nle, fps=None):
    global _ORIGEM, _TL_FPS
    _ORIGEM, _TL_FPS = nle, fps

def _rampa_por_posicao(s):
    """("pos", posições, keyframes, render) para a rampa vinda de outro programa, ou None (curva do Avid / constante /
    fonte de outra taxa — o gráfico de posição sobre o adaptador de taxa ainda não foi medido)."""
    import rampa as RP
    if s.get("motion_effect_type") != "ramp" or not s.get("source_offset_map"):
        return None
    if _ORIGEM in (None, "avid") and s.get("speed_keyframes"):
        return None                                               # Avid → Avid: a curva nativa (keyframes, alças)
    sf = s.get("source_fps")
    if _TL_FPS and sf and abs(float(sf) - float(_TL_FPS)) > 1e-3:
        log.warning("rampa de %r: fonte a %s qps numa timeline a %s — o gráfico de posição sobre o adaptador de "
                    "taxa não foi medido; vai a curva aproximada + o mapa", s.get("clip_name"), sf, _TL_FPS)
        return None
    pos = RP.posicoes(s)
    if len(pos) < 2 or not RP.e_curva(pos):
        return None
    return ("pos", pos, RP.keyframes_hibridos(pos), RP.render_avid(s.get("retime")))

# TRANSIÇÕES (dissolve) VALIDADAS no MC (2026-07-10, material de teste real: abre + toca + SALVA com
# transições + ganho). A causa do "Range specified for Dup" NÃO era left_length/precomputed/curva
# (objeto TransitionEffect é idêntico ao real) e sim HANDLE dos clipes vizinhos, faltando só nos
# masters OFFLINE — resolvido dando folga sintética a eles (ver commit do handle offline +
# avb-offline-save-bug.md). Dissolve é o PADRÃO agora. Kill-switch `AVB_NO_TRANS=1` restaura o corte
# seco (transição vira corte seco — trim exato no cutpoint, ver _position_row/_trim_tail) p/ depuração.
TRANS_OFF = os.environ.get("AVB_NO_TRANS") == "1"

def _motion_entry_from_seg(s, h):
    """Relinker motion Segment -> entry ('motion', (sr, kfs), inner_clip, timeline_len). Só velocidade
    de VÍDEO (constant/ramp/freeze/reverse). USA speed_keyframes/source_offset_map do Relinker — que já
    vêm na unidade SOURCE-POR-TIMELINE, a MESMA que o control point do AVB MotionEffect espera (0.85 =
    85% da fonte por frame de timeline). NÃO usa speed_ratio (convenção recíproca: 1.1617 no mesmo clipe).
    O source_offset_map é a integral que o próprio Avid gravou -> verdade p/ o length do inner SourceClip.
    Retorna None se não der p/ reconstruir (chamador mantém o clipe simples)."""
    from fractions import Fraction
    dur = s["duration_frames"]
    por_posicao = _rampa_por_posicao(s)
    if por_posicao is not None:
        pos = por_posicao[1]
        return ("motion", por_posicao, (h, s["source_start_frames"], int(math.floor(max(pos))) + 2), dur, None)
    if s.get("motion_effect_type") == "reverse":
        re_pos = _reverso_por_posicao(s, h)
        if re_pos is not None:
            return re_pos
    kfs = [dict(k) for k in (s.get("speed_keyframes") or [])]
    offmap = s.get("source_offset_map") or []
    if not kfs:                                                   # sem curva: sintetiza constante do offset map
        if offmap and dur:
            sp = (offmap[-1][1] - offmap[0][1]) / dur
        elif _ORIGEM == "premiere" and s.get("speed_ratio") and dur:
            # constante do .prproj: só o speed_ratio, na convenção RECÍPROCA (0,2143 = 466,67 %) — sem mapa nem curva
            sp = 1.0 / float(s["speed_ratio"])
            offmap = [(0.0, 0.0), (float(dur), sp * dur)]
        else:
            return None
        kfs = [{"t": 0.0, "speed": sp, "in_dt": 0.0, "in_dv": 0.0, "out_dt": 0.0, "out_dv": 0.0, "mode": 1}]
    if s.get("motion_effect_type") == "reverse":                 # reverse -> velocidade negativa (AVB assina no sinal)
        for k in kfs: k["speed"] = -abs(k["speed"])
    src_len = int(round(abs(offmap[-1][1] - offmap[0][1]))) if offmap else int(round(abs(kfs[-1]["speed"]) * dur))
    inner = (h, s["source_start_frames"], max(1, src_len))        # inner SourceClip: length = FONTE consumida
    avg = kfs[0]["speed"] if len(kfs) == 1 else ((offmap[-1][1] - offmap[0][1]) / dur if offmap and dur else 1.0)
    fr = Fraction(avg or 0).limit_denominator(1000)              # me.speed_ratio coerente c/ os control points
    sr = [fr.numerator, fr.denominator] if fr.denominator else None
    return ("motion", (sr, kfs), inner, dur, None)

def _reverso_por_posicao(s, h):
    """O REVERSO pelo gráfico de POSIÇÃO, um keyframe por quadro (o molde provado com "ré de 2": 48/48 exatos —
    banco avb/estruturas.md §Rampa). ⛔ CORRIGE (2026-11-21, laboratório BL04, MC 25.12 Mac): a velocidade constante
    NEGATIVA no `EFF_ADV_MOTION_CTL` levava o mapa (p1) de 0 a +|v|·n, e o MC renderiza pelo MAPA — o plano tocou PARA
    FRENTE (300 → 347 em vez de 300 → 253), e o AAF que o MC exporta dele diz o contrário da imagem.
    Convenção do segmento neutro: `source_start_frames` = o 1º quadro MOSTRADO (o mais alto), descendo; com
    `source_offset_map`, as posições vêm dele (relativas ao in). O clipe de dentro começa no quadro mais BAIXO.
    None = fonte de outra taxa (o adaptador com ré não foi medido) ou nada que ande para trás."""
    import rampa as RP
    sf = s.get("source_fps")
    if _TL_FPS and sf and abs(float(sf) - float(_TL_FPS)) > 1e-3:
        return None
    dur = int(s.get("duration_frames") or 0)
    if dur <= 0:
        return None
    pos = RP.posicoes(s) if s.get("source_offset_map") else []
    if not pos:
        v = s.get("velocidade_fonte")
        if not v and s.get("speed_ratio"):
            # a convenção do speed_ratio muda com a origem: RECÍPROCA no Premiere, direta no AAF do Avid
            v = 1.0 / float(s["speed_ratio"]) if _ORIGEM == "premiere" else float(s["speed_ratio"])
        v = abs(float(v or 1.0))
        pos = [-k * v for k in range(dur)]
    if dur > 1 and not any(b < a - 1e-6 for a, b in zip(pos, pos[1:])):
        return None
    inicio = int(s["source_start_frames"])
    base = math.floor(min(pos) + 1e-6)
    if inicio + base < 0:
        return None                                                  # antes do começo do arquivo
    pos, inicio = [p - base for p in pos], inicio + base
    # um keyframe POR QUADRO: entre dois esparsos a interpolação de uma reta descendente deixava o piso à mercê do
    # arredondamento (45,99999 → 45)
    return ("motion", ("pos", pos, list(range(dur)), RP.render_avid(s.get("retime"))),
            (h, inicio, int(math.floor(max(pos))) + 2), dur, None)


_IMAGEM_PARADA = {".png",".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".exr", ".dpx", ".bmp", ".tga", ".gif"}


def _entry_outra_taxa(s, h):
    """Clipe do PREMIERE cuja fonte tem outra taxa (o R04: 80 de 89 clipes a 25/60/100 qps numa timeline de 23,976) ->
    o ADAPTADOR de taxa do Avid (banco avb/estruturas.md §Taxa mista e §Rampa). Tempo real (sem velocidade): o
    adaptador como o MC grava (`MOTION_CTL`, `_MIXMATCH_MOTIONADAPTER 2`, `speed_ratio` = timeline ÷ fonte, a trilha de
    dentro NA TAXA DA FONTE) com `_SFX_RENDER 2` (Both Fields: quadro inteiro pelo piso, 48/48 nas três taxas). Com
    velocidade (constante, rampa ou a grade do nest): PROMOVIDO (`_MIXMATCH_MOTIONADAPTER 4`) com o gráfico de POSIÇÃO em
    quadros DA FONTE — a regra do autor para velocidade entre NLEs (quadro a quadro). None = não é o caso."""
    import rampa as RP
    sf = s.get("source_fps")
    if _ORIGEM != "premiere" or not _TL_FPS or not sf or abs(float(sf) - float(_TL_FPS)) < 1e-3:
        return None
    if os.path.splitext(str(s.get("clip_name") or ""))[1].lower() in _IMAGEM_PARADA:
        # IMAGEM PARADA: a "taxa" que o Premiere declara (25 no cartão do PRODC) não é tempo de nada. Com o adaptador o
        # MC mostrava `PGLUE_IMPOLITE_PORT_NUMBER` no lugar do cartão (2026-10-25, MC 25.12; o mesmo do quadro 119 de
        # 18/10) — vai como clipe simples
        return None
    sf, dur = float(sf), s["duration_frames"]
    pos = []
    if s.get("has_motion_effect"):
        pos = RP.posicoes(s)
        if not pos and s.get("speed_ratio"):                         # constante do .prproj: só o speed_ratio
            pos = [k / float(s["speed_ratio"]) for k in range(dur)]
    if not pos:
        need = int(math.ceil(dur * sf / float(_TL_FPS) - 1e-6))
        return ("adapter", sf, (h, s["source_start_frames"], max(1, need)), dur, None)
    if s.get("motion_effect_type") == "reverse" or any(b < a - 1e-6 for a, b in zip(pos, pos[1:])):
        return None                                                  # ré sobre o adaptador: não medido
    # ⛔ Posição NEGATIVA no começo não é ré: é a fase do Premiere (o PRODC, LOU_7231 a 60 qps num nest: o mapa começa em
    # −0,36 → o 1º quadro mostrado é o de ANTES do in). Recusar aqui mandava o clipe para o `_motion_entry_from_seg`,
    # que grava o início em quadros DA FONTE numa trilha na taxa da TIMELINE — o MC lia 2768 a 23,976 (≈ 6.927 a 60,
    # num arquivo de 3.545) e recusava a sequência inteira: CM_OFFSET_OUT_OF_RANGE (2026-10-18, MC 24.6). Desloca o
    # clipe de dentro para o quadro do piso e as posições junto: o mesmo quadro em cada ponto, tudo ≥ 0.
    inicio = s["source_start_frames"]
    base = math.floor(min(pos) + 1e-6)
    if base < 0:
        if inicio + base < 0:
            return None                                              # antes do começo do arquivo: não há o que mostrar
        pos, inicio = [p - base for p in pos], inicio + base
    return ("motion", ("pos", pos, RP.keyframes_hibridos(pos), RP.render_avid(s.get("retime")), sf),
            (h, inicio, int(math.floor(max(pos))) + 2), dur, None)

def _taxa_de_dentro(me, sf):
    """A trilha de dentro do efeito NA TAXA DA FONTE (Sequence, Fillers e o SourceClip) — o que o MC grava no
    adaptador; com a taxa da timeline ali, o start/length do clipe seriam lidos na unidade errada."""
    for tk in me.tracks:
        seq = tk.component
        objs = [seq] + list(getattr(seq, "components", None) or [])
        for o in objs:
            if "edit_rate" in o.property_data:
                o.property_data["edit_rate"] = sf

UNITY_GAIN = 1 << 29   # 2^29 = 0dB / sem alteração (convenção Avid p/ o parâmetro "level")

def _gain_level(s):
    """level_num (numerador/2^29) do 1º efeito 'Audio Gain' do segmento, ou None se não houver /
    for unity (0dB, sem alteração real -> não vale a pena embrulhar em PanVolumeEffect)."""
    for e in (s.get("effects") or []):
        if e.get("name") == "Audio Gain":
            lv = (e.get("params") or {}).get("level_num")
            if lv is not None and lv != UNITY_GAIN:
                return lv
    return None

def _trim_tail(e, amount):
    """(novo_entry, quanto_realmente_cortou) — apara a CAUDA de um entry "clip" ou "gain" (que
    embrulha um "clip" em e[2]). Usado pelo corte seco p/ acertar o cutpoint exato (ver
    _position_row) — precisa entender o wrapper de ganho, senão um clipe com automação de volume
    adjacente a uma transição fica sem o trim fino e desliza (achado 2026-07-10 na PRODA)."""
    if amount <= 0 or e[0] not in ("clip", "gain"):
        return e, 0
    if e[0] == "clip":
        k, h, ss, d, slot = e
        cut = min(d - 1, amount)
        return ((k, h, ss, d - cut, slot) if cut else e), cut
    k, lv, inner, d, slot = e
    if inner is None or inner[0] != "clip":
        return e, 0
    ik, ih, iss, idur, islot = inner
    cut = min(idur - 1, d - 1, amount)
    if not cut:
        return e, 0
    return (k, lv, (ik, ih, iss, idur - cut, islot), d - cut, slot), cut

def _trim_head(e, amount):
    """(novo_entry, quanto_realmente_cortou) — apara a CABEÇA (avança source_start_frames), mesma
    lógica de _trim_tail espelhada."""
    if amount <= 0 or e[0] not in ("clip", "gain"):
        return e, 0
    if e[0] == "clip":
        k, h, ss, d, slot = e
        cut = min(d - 1, amount)
        return ((k, h, ss + cut, d - cut, slot) if cut else e), cut
    k, lv, inner, d, slot = e
    if inner is None or inner[0] != "clip":
        return e, 0
    ik, ih, iss, idur, islot = inner
    cut = min(idur - 1, d - 1, amount)
    if not cut:
        return e, 0
    if slot:                                           # a automação conta do início do clipe: anda junto
        slot = tuple((max(0, q - cut), v) for q, v in slot)
    return (k, lv, (ik, ih, iss + cut, idur - cut, islot), d - cut, slot), cut

def _seg_to_entry(s, m2h, name2h, kind):
    """A entry do segmento (`_seg_to_entry_base`) e, para quem vem do PREMIERE, a escala e a posição do Motion por
    cima (`_geo_premiere`): o escritor descartava o reframe e o PRODC conferia 108/144 (2026-10-25, MC 25.12).

    O clipe DESLIGADO entra desligado, como o Mute Clips do MC (`"mudo"` embrulha a entrada inteira, com ganho, escala
    e máscara): virava vazio e o plano sumia calado (R04: 2 áudios; decisão do autor, 2026-10-29)."""
    desligado = bool(s.get("disabled")) and not (s.get("is_gap") or s.get("is_transition"))
    e = _seg_to_entry_base(dict(s, disabled=False) if desligado else s, m2h, name2h, kind)
    if kind == "picture" and _ORIGEM == "premiere" and not GEO_OFF and e[0] in ("clip", "motion", "adapter"):
        g = _geo_premiere(s)
        if g is not None:
            e = ("geo", g[0], e, e[3], (g[1], g[2]))
        if not MASK_OFF:
            blocos = _animatte_premiere(s)
            if blocos:
                e = ("animatte", None, e, e[3], blocos)
    if desligado and e[0] != "gap":
        e = ("mudo", None, e, e[3], None)
    return e


#: kill-switch: a escala/posição do Premiere fora (o comportamento de antes de 2026-10-25)
GEO_OFF = os.environ.get("AVB_NO_GEO") == "1"
#: kill-switch: a máscara de opacidade do Premiere → AniMatte fora
MASK_OFF = os.environ.get("AVB_NO_MASK") == "1"
#: Feathering do AniMatte em px do quadro 1920×1080 por unidade (largura 10–90 %): Hor 6,0 e Vert 4,4 (banco
#: avb/estruturas.md §AniMatte). ⚠️ hipótese: o `suave_px` do Premiere ≈ essa largura, na escala da imagem mostrada.
_FEATHER_PX_HOR, _FEATHER_PX_VERT = 6.0, 4.4


def _bzfx(formas, molde: bytes) -> bytes:
    """O bloco BZFX do AniMatte (banco avb/estruturas.md §AniMatte): "BZFX" + u32 0 + u32 nº de formas + as formas;
    forma = o cabeçalho de 276 bytes do MOLDE (o do MC) com o Feathering (+31/+39) e a contagem (+268) trocados, e os
    registros de 62 bytes (id, bandeira `01 00` curva / `01 01` reta, tipo de alça 0, x, y, alça que chega, alça que
    sai; o último sem os 4 zeros). `formas` = [(vértices [(x, y, (cx, cy), (sx, sy), curva)], hor, vert)], em
    unidades do Avid (x na escala de 720, y na de 243, centro 0, +Y desce)."""
    import struct
    cab = bytearray(molde[12:12 + 276])
    rid = struct.unpack(">I", cab[4:8])[0]
    out = bytearray(b"BZFX" + struct.pack(">I", 0) + struct.pack(">I", len(formas)))
    for verts, hor, vert in formas:
        h = bytearray(cab)
        h[4:8] = struct.pack(">I", rid)
        h[31:39] = struct.pack(">d", float(hor))
        h[39:47] = struct.pack(">d", float(vert))
        h[268:272] = struct.pack(">I", len(verts))
        out += h
        for i, (x, y, chega, sai, curva) in enumerate(verts):
            rid += 1
            out += struct.pack(">I", rid) + (b"\x01\x00" if curva else b"\x01\x01") + struct.pack(">I", 0 if curva else 2)
            out += struct.pack(">6d", x, y, chega[0], chega[1], sai[0], sai[1])
            if i < len(verts) - 1:
                out += b"\x00\x00\x00\x00"
        rid += 1
    return bytes(out)


def _valor_em(lst, k, padrao):
    """O valor de uma lista de pontos [(quadro, v)] (desde o quadro 0) no quadro `k`, linear entre eles."""
    if not lst:
        return padrao
    q0 = lst[0][0]
    pts = [(q - q0, v) for q, v in lst]
    if k <= pts[0][0]:
        return pts[0][1]
    for (a, va), (b, vb) in zip(pts, pts[1:]):
        if a <= k <= b:
            return va if b == a else va + (vb - va) * (k - a) / (b - a)
    return pts[-1][1]


def _animatte_premiere(s):
    """A máscara de opacidade do Premiere → os blocos BZFX do AniMatte, um keyframe por quadro do plano:
    `[(percent_time, bzfx)]`, ou None. O AniMatte vai POR FORA do efeito geométrico, então a forma está no quadro da
    TIMELINE: o vértice (normalizado na FONTE, +Y desce — `prproj.leitura`) passa pela transformação do Motion daquele
    quadro (encaixe × escala, espelho, rotação, posição) e vira as unidades do AniMatte (x × 720/W, y × 243/H, centro
    0). A forma animada do Premiere já vem um quadro de máscara por quadro do plano. ⏳ Não vão: máscara invertida,
    expansão, opacidade da máscara."""
    import math
    efm = next((x for x in s.get("effects") or [] if x.get("name") == "Máscara de opacidade (Fusion)"), None)
    if efm is None or not s.get("fonte_px"):
        return None
    mascaras = [m for m in (efm.get("params") or {}).get("mascaras") or [] if not m.get("invertida")]
    if not mascaras:
        return None
    W, H = 1920.0, 1080.0
    fw, fh = (float(x) for x in s["fonte_px"])
    enc = min(W / fw, H / fh)
    fy = H / (fh * enc) if fh * enc < H - 0.5 else 1.0
    mot = next((x for x in s.get("effects") or [] if x.get("name") == "Motion"), None)
    p = (mot or {}).get("params") or {}
    kf = p.get("kf") or {}
    L = max(1, int(s.get("duration_frames") or 1))

    def geo(k):
        sx = _valor_em(kf.get("zoom"), k, float(p.get("scale_x", 1.0) or 1.0))
        sy = _valor_em(kf.get("zoom_y") or (kf.get("zoom") if "zoom" in kf else None), k,
                       float(p.get("scale_y", 1.0) or 1.0))
        px = _valor_em(kf.get("pos_x"), k, None)
        px = px * 1000 if px is not None else float(p.get("pos_x", 0.0) or 0.0)
        py = _valor_em(kf.get("pos_y"), k, None)
        py = py * 1000 if py is not None else float(p.get("pos_y", 0.0) or 0.0)
        rot = _valor_em(kf.get("rot"), k, float(p.get("rot_z", 0.0) or 0.0))
        return sx, sy, px, py, rot

    def linear(dx, dy, g):
        sx, sy, _px, _py, rot = g
        x, y = dx * fw * enc * sx, dy * fh * enc * sy
        if p.get("flip_x"):
            x = -x
        if p.get("flip_y"):
            y = -y
        t = math.radians(-rot)                     # a rotação do Premiere (horária, +Y desce) = −rot_z do leitor
        return x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t)

    def ponto(u, v, g):
        x, y = linear(u - 0.5, v - 0.5, g)
        x += g[2] / 1000 * W
        y += -g[3] / 1000 * H / fy
        return x * 720 / W, y * 243 / H

    def alca(du, dv, g):
        x, y = linear(du, dv, g)
        return x * 720 / W, y * 243 / H

    def formas_em(k):
        g = geo(k)
        out = []
        for m in mascaras:
            qs = m.get("quadros") or []
            verts = qs[min(len(qs) - 1, round(k * len(qs) / L))]["vertices"] if qs else m["vertices"]
            vs = []
            for curva, pt, chega, sai in verts:
                vs.append((*ponto(pt[0], pt[1], g), alca(chega[0] - pt[0], chega[1] - pt[1], g),
                           alca(sai[0] - pt[0], sai[1] - pt[1], g), bool(curva)))
            esc = enc * max(g[0], g[1])
            suave = float(m.get("suave_px") or 0.0) * esc
            out.append((vs, suave / _FEATHER_PX_HOR, suave / _FEATHER_PX_VERT))
        return out

    molde = _ANIMATTE_BZFX()
    if molde is None:
        return None
    blocos = []
    for k in range(L):
        pt = round(k / (L - 1) * (1 << 30)) if L > 1 else 0
        blocos.append((pt, _bzfx(formas_em(k), molde)))
    if L == 1:
        blocos.append((1 << 30, blocos[0][1]))
    return blocos


_MOLDE_BZFX = []


def _ANIMATTE_BZFX():
    """O `user_param` do 1º keyframe do molde EFF_ANIMATTE (o bloco que o MC gravou), ou None."""
    if not _MOLDE_BZFX:
        tpl = capture_templates()
        spec = tpl.get("EFF_ANIMATTE")
        b = None
        try:
            kp = spec["__props__"]["keyframes"]
            itens = kp.get("__items__") or kp.get("__props__", {}).get("parameters", {}).get("__list__") or []
            b = bytes.fromhex(next(iter(itens[0]["__props__"]["user_param"].values())))
        except Exception:  # noqa: BLE001
            b = None
        _MOLDE_BZFX.append(b)
    return _MOLDE_BZFX[0]
#: Os parâmetros do Resize e do PIP do Avid (MC 25; uuid do `param_list`, casados pelos valores dos moldes
#: `templates.json`: Resize (−15, 55) 130 %, PIP (33, −87) 78 % — banco `avb/dados/efeitos-na-bin.json`, E04).
#: Posição em MILÉSIMOS do quadro (X da largura, Y da altura), +Y DESCE; escala em % (banco
#: `avb/dados/efeitos-paleta-mc25.json`). `AFX_LOCK`: o 1 dos dois moldes; hipótese = escala travada X = Y.
AFX_POS_X, AFX_POS_Y = "8d568125-847e-11d5-935a-50f857c10000", "8d568126-847e-11d5-935a-50f857c10000"
AFX_SCALE_X, AFX_SCALE_Y = "8d568129-847e-11d5-935a-50f857c10000", "8d56812a-847e-11d5-935a-50f857c10000"
AFX_LOCK = "8d56812b-847e-11d5-935a-50f857c10000"
#: os outros do molde, com o valor dele (a poda de `_override_params` tiraria o que não viesse)
_AFX_RESTO = {"8d56814d-847e-11d5-935a-50f857c10000": 0, "8d568153-847e-11d5-935a-50f857c10000": 0}
_PIP_RESTO = {"8d568137-847e-11d5-935a-50f857c10000": 255.0, "8d56813a-847e-11d5-935a-50f857c10000": 255.0,
              "8d568288-847e-11d5-935a-50f857c10000": 1}


DVE_POS_ON, DVE_POS_X, DVE_POS_Y = ("8d5681a9-847e-11d5-935a-50f857c10000", "8d5681aa-847e-11d5-935a-50f857c10000",
                                   "8d5681ab-847e-11d5-935a-50f857c10000")
DVE_SCALE_ON, DVE_SCALE_X, DVE_SCALE_Y = ("8d5681b2-847e-11d5-935a-50f857c10000", "8d5681b3-847e-11d5-935a-50f857c10000",
                                         "8d5681b4-847e-11d5-935a-50f857c10000")
DVE_ROT_ON, DVE_ROT_X, DVE_ROT_Y, DVE_ROT_Z = ("8d5681b7-847e-11d5-935a-50f857c10000",
                                              "8d5681b8-847e-11d5-935a-50f857c10000",
                                              "8d5681b9-847e-11d5-935a-50f857c10000",
                                              "8d5681ba-847e-11d5-935a-50f857c10000")
#: O sentido da rotação do 3D Warp contra a convenção do leitor (a do Resolve, `prproj.leitura.SINAL_ROTACAO_RESOLVE`).
#: MEDIDO 2026-10-25 (MC 25.12, PRODC A031_C004 girando de −246° a −181°, pela referência): com +1 o início saía girado
#: para o outro lado (corr −0,37); com −1, 0,87 (o fim, ≈180°, não distingue). E o espelho do Premiere como rotação de
#: 180° no Y (X para o vertical) confere: LOU_7254, A030_C045, JUL_7644 de 0,08–0,47 para 0,83–0,92.
SINAL_ROT_DVE = -1.0


def _geo_premiere(s):
    """(effect_id, {uuid: valor}, {uuid: [(quadro do efeito, valor)]}) do Motion do Premiere, ou None (neutro). O leitor
    entrega a escala relativa ao ENCAIXE e a posição em milésimos do quadro com +Y para CIMA (a convenção do Resolve,
    `prproj.leitura._segmento`); a animação em `kf` (zoom/zoom_y/pos_x/pos_y em FRAÇÃO/rot), um ponto por instante, o
    1º no início do plano.

    - **Resize** quando a imagem cobre o quadro e não há animação (ele é OPACO: fundo preto) — o caso mais simples;
    - **PIP** quando não cobre, ou se mexe (deixa ver a trilha de baixo);
    - **3D Warp** quando há rotação ou espelho (o único dos três que gira). Posição do DVE com +Y para cima.
    A animação vai como keyframes LINEARES em cada parâmetro (`control_track`, `interp_kind 3`)."""
    m = next((x for x in s.get("effects") or [] if x.get("name") == "Motion"), None)
    p = (m or {}).get("params") or {}
    sx, sy = float(p.get("scale_x", 1.0) or 1.0), float(p.get("scale_y", 1.0) or 1.0)
    px, py = float(p.get("pos_x", 0.0) or 0.0), float(p.get("pos_y", 0.0) or 0.0)
    rot = float(p.get("rot_z", 0.0) or 0.0)
    fx, fy = bool(p.get("flip_x")), bool(p.get("flip_y"))
    kf = p.get("kf") or {}
    if (abs(sx - 1) < 1e-3 and abs(sy - 1) < 1e-3 and abs(px) < 0.5 and abs(py) < 0.5 and abs(rot) < 1e-3
            and not (fx or fy or kf)):
        return None

    def pontos(nome, conv):
        lst = kf.get(nome) or []
        if len(lst) < 2:
            return None
        q0 = lst[0][0]
        return [(int(q) - int(q0), conv(float(v))) for q, v in lst]

    if abs(rot) > 1e-3 or fx or fy or "rot" in kf:
        params = {DVE_POS_ON: 1, DVE_POS_X: round(px, 3), DVE_POS_Y: round(py, 3),
                  DVE_SCALE_ON: 1, DVE_SCALE_X: round(sx * 100, 3), DVE_SCALE_Y: round(sy * 100, 3),
                  DVE_ROT_ON: 1, DVE_ROT_Z: round(SINAL_ROT_DVE * rot, 3),
                  AFX_LOCK: 1 if abs(sx - sy) < 1e-6 and not kf else 0}
        if fx:
            params[DVE_ROT_Y] = 180.0
        if fy:
            params[DVE_ROT_X] = 180.0
        mapa = {DVE_POS_X: ("pos_x", lambda v: v * 1000), DVE_POS_Y: ("pos_y", lambda v: v * 1000),
                DVE_SCALE_X: ("zoom", lambda v: v * 100), DVE_SCALE_Y: ("zoom_y", lambda v: v * 100),
                DVE_ROT_Z: ("rot", lambda v: SINAL_ROT_DVE * v)}
        eid = "EFF2_SBLEND"
    else:
        cobre = sx / 2 - abs(px) / 1000 >= 0.5 - 1e-3 and sy / 2 - abs(py) / 1000 >= 0.5 - 1e-3
        params = {AFX_POS_X: round(px, 3), AFX_POS_Y: round(-py, 3), AFX_SCALE_X: round(sx * 100, 3),
                  AFX_SCALE_Y: round(sy * 100, 3), AFX_LOCK: 1 if abs(sx - sy) < 1e-6 and not kf else 0,
                  **_AFX_RESTO}
        mapa = {AFX_POS_X: ("pos_x", lambda v: v * 1000), AFX_POS_Y: ("pos_y", lambda v: -v * 1000),
                AFX_SCALE_X: ("zoom", lambda v: v * 100), AFX_SCALE_Y: ("zoom_y", lambda v: v * 100)}
        eid = "EFF2_BLEND_RESIZE" if cobre and not kf else "EFF2_BLEND_PIP"
        if eid == "EFF2_BLEND_PIP":
            params.update(_PIP_RESTO)
    kfs = {}
    for u, (nome, conv) in mapa.items():
        pts = pontos(nome, conv)
        if pts is None and nome == "zoom_y" and "zoom" in kf and "zoom_y" not in kf:
            pts = pontos("zoom", conv)                     # escala uniforme animada: o Y acompanha o X
        if pts:
            kfs[u] = pts
    return eid, params, kfs


def _seg_to_entry_base(s, m2h, name2h, kind):
    """1 Segment do Relinker -> 1 entry do _build_one. VELOCIDADE de vídeo reconstruída via
    _motion_entry_from_seg (kill-switch AVB_NO_MOTION); reframe ainda dropado (mantém clipe);
    disabled/effect(Titler)/sem-mídia -> gap; transição -> dissolve (vídeo) / audio_dissolve (som).
    Bridge: mob_id via m2h (master direto -> AAF hex, _R rebridgeia); se falhar (subclipe), fallback pelo
    NOME resolvido (clip_name -> master da media bin, hex JÁ final). Áudio: canal=source_slot_id."""
    dur = s["duration_frames"]
    if s.get("colapso"):                                  # nest de outro programa -> Collapse (Submaster)
        linhas = [_position_row(c, m2h, name2h, kind, s["source_fps"]) for c in s["colapso"]]
        # Collapse só de vazios (a mídia de dentro não casou) = gap: o export do MC recusa a sequência inteira com
        # 'Sequence "" cannot be committed because it is empty' (medido 2026-10-13, MC 25.6)
        if not any(e[0] != "gap" for row in linhas for e in row):
            return ("gap", None, 0, dur, None)
        return ("collapse", linhas, 0, dur, None)
    if s["is_transition"]:
        # SEMPRE classifica como "trans" (mesmo com TRANS_OFF) — _position_row precisa do kind p/
        # aplicar a compensação de overlap (pos -= dur) na posição certa; sem isso os clipes seguintes
        # daquela trilha deslocam pra FRENTE em cada transição descartada (áudio dessincroniza,
        # acumulando a cada transição — achado pelo usuário 2026-07-10 comparando o áudio no MC).
        # TRANS_OFF decide só se o "trans" vira componente visível (dissolve) ou é omitido (corte seco),
        # em _position_row — não aqui.
        eid = "BLEND_AUDIO_DISSOLVE" if kind == "sound" else "EFF2_BLEND_DISSOLVE"
        return ("trans", eid, s["cutpoint"], dur, None)
    if kind == "picture" and not TITLE_OFF and s.get("is_effect"):           # Avid Title+ -> reconstrói
        t = _title_entry(s)
        if t is not None:
            return t
    if s["is_gap"] or s["disabled"] or s["is_effect"] or not s.get("mob_id"):
        return ("gap", None, 0, dur, None)                                  # disabled/Titler/gerador -> gap
    h = m2h.get(s["mob_id"]) or name2h.get(_norm_name(s.get("clip_name")))
    # h None (não resolvido) OU o master não está na media bin (mídia não clonada: match falhou /
    # formato pulado) -> GAP. Senão o SourceClip referencia um mob inexistente e o Avid estoura no
    # PlayPipe::DoComp() ('missing mob'). (_MASTER_LEN vazio no front-end AAF/regressão = sem checagem.)
    if h is None or (_MASTER_LEN and _R(h) not in _MASTER_LEN):
        return ("gap", None, 0, dur, None)
    if kind == "picture" and not MOTION_OFF:
        ot = _entry_outra_taxa(s, h)                        # fonte de OUTRA taxa (Premiere): adaptador do Avid
        if ot is not None: return ot
    if kind == "picture" and s.get("has_motion_effect") and not MOTION_OFF:  # velocidade de vídeo
        me = _motion_entry_from_seg(s, h)
        if me is not None: return me
    slot = s.get("source_slot_id") if kind == "sound" else 1                # canal (áudio) / trilha única (vídeo)
    src_start = s["source_start_frames"]
    if _OFFLINE_H and _R(h) in _OFFLINE_HEXES:        # master offline: desloca +H (centraliza na folga)
        src_start += _OFFLINE_H                        # -> handle nos dois lados p/ transições (ver acima)
    clip = ("clip", h, src_start, dur, slot)          # reframe dropado: mantém clipe
    if kind == "sound":
        lv = _gain_level(s)                            # ganho/volume do clipe (Audio Gain, não-unity)
        auto = s.get("volume_auto")                    # automação de VOLUME: [(quadro do clipe, level)]
        if lv is not None or auto:
            return ("gain", lv if lv is not None else UNITY_GAIN, clip, dur, tuple(auto) if auto else None)
    return clip

def _tc_frames(tc, fps):
    """'HH:MM:SS:FF' (relativo ao início da TL) -> frames. Non-drop: round(fps) frames/s."""
    p = (tc or "0:0:0:0").replace(";", ":").split(":")
    h, m, s, ff = (int(x) for x in (p + [0, 0, 0, 0])[:4])
    return (h * 3600 + m * 60 + s) * round(fps) + ff

def _position_row(segs, m2h, name2h, kind, fps):
    """Posiciona cada CLIPE pelo timeline_tc_in ABSOLUTO, inserindo gaps de preenchimento (as
    camadas V2/V3 e áudios sparsos não trazem os gaps de posição). Transição só é emitida/contada
    (overlap: pos -= dur) se estiver ENTRE dois clipes reais — senão pos se corrompe (transição
    órfã/no início) e todos os clipes seguintes deslocam. Gaps do parser: preenchimento por tc cobre."""
    ents = [(_seg_to_entry(s, m2h, name2h, kind), s) for s in segs]
    _clip_like = ("clip", "motion", "gain", "title", "collapse", "adapter", "geo", "animatte", "mudo")   # ocupam a timeline (posicionados por tc_in)
    pos = 0
    out = []
    pending_head_trim = 0    # TRANS_OFF: frames a cortar da CABEÇA do próximo clipe (ver bloco "trans")
    for i, (e, s) in enumerate(ents):
        if e[0] == "trans":
            # ADJACÊNCIA REAL: olhar o vizinho IMEDIATO na lista (ents[i-1]), não "o último clipe já
            # emitido" (out[-1]) — este ignora gaps intermediários e cola a transição num clipe que na
            # verdade está SEGUNDOS de distância na timeline original (gap real entre eles), pedindo
            # handle de um clipe errado -> "Range specified for Dup is outside range of component" no
            # MC ao editar perto dali. Diagnosticado 2026-07-10 na PRODA: transição com cutpoint=10 grudada
            # no clipe anterior apesar de 657 frames de gap real entre eles.
            prev_clip = i > 0 and ents[i - 1][0][0] in _clip_like
            next_clip = i + 1 < len(ents) and ents[i + 1][0][0] in _clip_like
            prev_gap = i > 0 and ents[i - 1][0][0] == "gap"          # filler/silêncio (fade)
            next_gap = i + 1 < len(ents) and ents[i + 1][0][0] == "gap"
            dur_t, cp = s["duration_frames"], s["cutpoint"]
            # FADE-IN (silêncio->clipe) e FADE-OUT (clipe->silêncio): transição com UM lado gap. Só no
            # modo dissolve (TRANS_OFF=corte seco deixa o clipe começar/terminar seco no tc_in, sem
            # transição). O lado filler não precisa de handle; o lado clipe já tem (online de sobra,
            # offline recebeu folga). Estrutura no MC: [Filler, Trans, SourceClip] / [SourceClip, Trans,
            # Filler] — idêntica à bin nativa (medido em 03_OC_EDIT VALENDO.avb: 27 fade-in + 19 fade-out).
            if not TRANS_OFF and prev_gap and next_clip and not prev_clip:
                # estende o filler até (clip_tc_in + L); o `pos -= dur_t` recua p/ o clip cair no tc_in
                clip_tc = _tc_frames(ents[i + 1][1]["timeline_tc_in"], fps)
                filler_end = clip_tc + dur_t
                if filler_end > pos:
                    out.append(("gap", None, 0, filler_end - pos, None)); pos = filler_end
                out.append(e); pos -= dur_t
                continue
            if not TRANS_OFF and prev_clip and next_gap and not next_clip:
                out.append(e); pos -= dur_t     # clipe já emitido; gap seguinte preenche o resto
                continue
            if prev_clip and next_clip:
                # CORTE SECO de verdade (TRANS_OFF): uma Sequence é só concatenação linear — sem um
                # componente ali, o clipe SEGUINTE encosta onde o ANTERIOR terminou (fim da transição),
                # NÃO no cutpoint (achado 2026-07-10: corte de áudio saía 2 frames à frente do vídeo,
                # exatamente cutpoint->fim — "pos -= dur" sozinho só evita um gap de preenchimento extra,
                # não move o corte real). Fix: apara a CAUDA do clipe anterior em (dur-cutpoint) e marca
                # a CABEÇA do próximo p/ perder `cutpoint` (avança source_start_frames) — o corte cai
                # exato onde a transição diria "agora é o outro clipe". Como o overlap já foi consumido
                # via os próprios comprimentos, a entry "trans" NEM ENTRA em `out` (não tem o que
                # compensar — diferente do caminho COM dissolve, onde ela é um componente real de
                # `dur_t` frames e por isso tlen() a subtrai). _trim_tail entende "clip" E "gain"
                # (clipe com automação de volume) — sem isso um clipe com ganho adjacente à transição
                # ficava sem o trim fino e desliza (achado 2026-07-10 na PRODA, depois de ligar ganho).
                # "motion" (rampa) adjacente fica sem trim (raro; cai no fallback, pos-compensation antigo).
                if TRANS_OFF and out and out[-1][0] in ("clip", "gain"):
                    trimmed, cut = _trim_tail(out[-1], max(0, dur_t - cp))
                    if cut:
                        out[-1] = trimmed
                        pos -= cut
                    pending_head_trim = cp
                else:
                    out.append(e); pos -= dur_t
            continue                             # transição órfã -> ignora (não mexe em pos)
        if e[0] not in _clip_like:               # gap/disabled/Titler -> preenchimento cuida
            continue
        seg_pos = _tc_frames(s["timeline_tc_in"], fps)
        if seg_pos > pos:
            out.append(("gap", None, 0, seg_pos - pos, None)); pos = seg_pos
        if pending_head_trim:                          # aplica o corte de cabeça pendente (ver acima)
            e, _cut = _trim_head(e, pending_head_trim)
        pending_head_trim = 0
        out.append(e); pos += e[3]
    return out

def _clean_orphans(row):
    """remove transições que não estão ENTRE dois clipes reais (evita 'transição no vazio' do Titler dropado)."""
    def is_clip(e): return e is not None and e[0] == "clip"
    out = []
    for i, e in enumerate(row):
        if e[0] == "trans":
            prev = out[-1] if out else None
            nxt = row[i + 1] if i + 1 < len(row) else None
            if not (is_clip(prev) and is_clip(nxt)):
                continue          # transição órfã -> drop
        out.append(e)
    return out

def _frames_tc(n, fps):
    """frames -> 'HH:MM:SS:FF' (o inverso de _tc_frames; non-drop)."""
    r = round(fps)
    return "%02d:%02d:%02d:%02d" % (n // (3600 * r), n // (60 * r) % 60, n // r % 60, n % r)

def _colapsar_compostos(segments, fps):
    """NEST de outro programa (segmentos com a mesma marca `composto`, a do leitor do .prproj) -> UM segmento
    `colapso` por ocorrência, na trilha MAIS BAIXA do grupo, que o _build_one escreve como Collapse do Avid.
    Decisão do autor (2026-10-12): Nest do Premiere = um Collapse por ocorrência. Forma medida no laboratório
    (B21_COLLAPSE, banco avb/estruturas.md §Collapse): Submaster com uma trilha interna por camada do nest; a
    velocidade fica DENTRO, em cada clipe (o MC recusa velocidade SOBRE o Collapse). Só vídeo: o Collapse não leva
    som. Trilha que ficou vazia ganha um gap para não sumir (as de cima desceriam)."""
    grupos = {}
    for s in segments:
        c = s.get("composto")
        if c and s["track"] < 1000 and not s.get("is_gap") and not s.get("is_transition"):
            grupos.setdefault(c["id"], []).append(s)
    if not grupos:
        return segments
    fora = {id(s) for g in grupos.values() for s in g}
    out = [s for s in segments if id(s) not in fora]
    trilhas = {s["track"] for s in out}
    for cid, g in grupos.items():
        ini = min(_tc_frames(s["timeline_tc_in"], fps) for s in g)
        fim = max(_tc_frames(s["timeline_tc_in"], fps) + s["duration_frames"] for s in g)
        camadas = []
        for t in sorted({s["track"] for s in g}):
            camadas.append([dict(s, timeline_tc_in=_frames_tc(_tc_frames(s["timeline_tc_in"], fps) - ini, fps),
                                 composto=None) for s in sorted(g, key=lambda s: _tc_frames(s["timeline_tc_in"], fps))
                            if s["track"] == t])
        base = min(s["track"] for s in g)
        out.append({"track": base, "timeline_tc_in": _frames_tc(ini, fps), "duration_frames": fim - ini,
                    "clip_name": g[0]["composto"].get("nome") or "(nest)", "source_fps": fps, "colapso": camadas,
                    "is_gap": False, "is_transition": False, "is_audio": False, "is_effect": False,
                    "disabled": False, "effects": [], "mob_id": None})
        for t in {s["track"] for s in g} - trilhas:
            out.append({"track": t, "timeline_tc_in": _frames_tc(0, fps), "duration_frames": 0, "is_gap": True,
                        "is_transition": False, "is_effect": False, "disabled": False, "clip_name": "(gap)"})
            trilhas.add(t)
    out.sort(key=lambda s: (s["track"], _tc_frames(s["timeline_tc_in"], fps), not s.get("is_transition")))
    return out

def tracks_from_segments(segments, fps, m2h, name2h):
    """(pic_tracks, snd_tracks) a partir dos SEGMENTOS já parseados do Relinker (modelo neutro).
    Vídeo E áudio RESOLVIDOS aos ORIGINAIS (sem subclipe/grupo). Áudio: track 1000+n = A(n+1);
    canal = source_slot_id. Este é o entrypoint do sidecar (segmentos vêm no params, sem reparse)."""
    from collections import defaultdict
    by_track = defaultdict(list)
    for s in _colapsar_compostos(segments, fps):
        by_track[s["track"]].append(s)
    pic, snd = [], []
    # ⛔ A numeração da origem é identidade (banco, B051): a trilha VAZIA entra vazia. Antes só as trilhas com plano
    # entravam e o `build` as numerava em sequência — com a V2 vazia, a V3 descia para a V2 (medido 2026-10-28).
    nums = set(by_track)
    v = [t for t in nums if t < 1000]
    a = [t for t in nums if t >= 1000]
    todas = (list(range(1, max(v) + 1)) if v else []) + (list(range(1000, max(a) + 1)) if a else [])
    for tnum in todas:
        kind = "sound" if tnum >= 1000 else "picture"
        row = _position_row(by_track[tnum], m2h, name2h, kind, fps) if by_track.get(tnum) else []
        (snd if kind == "sound" else pic).append((kind, row))
    return pic, snd

def tracks_from_relinker(path):
    """Wrapper CLI/regressão: parseia o AAF com o parser do Relinker e resolve os segmentos.
    O sidecar usa tracks_from_segments diretamente (segmentos já no params)."""
    _src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src-python (p/ modo script)
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from aaf.parser import parse_aaf
    r = parse_aaf(path)
    return tracks_from_segments(r["segments"], r["timeline_fps"], _urn2hex_from_aaf(path), _load_media_map())

# ---------- autorar comp mobs referenciados (subclip uc2 / grupo uc4 / container uc5) ----------
def _comp_mob_attrs(f, uc, L):
    if uc == 2:        # subclip (AutoSync)
        a = _attrs(f, _BOUNDS_REFORMATTING_OPTION=1, _START=0, _END=L, _COLOR_NONE=1, _USER_POS=L)
    elif uc == 4:      # grupo (multicam)
        a = _attrs(f, _EDIT_MODTIME=0, _IN=0, _OUT=L, _USER_POS=L)
    else:              # uc==5 container (groupoofter)
        a = _attrs(f)
    a['_USER'] = f.create.Attributes()
    return a

def _author_comp_mob(f, d, tpl):
    """autora um CompositionMob (subclip/grupo/container) espelhando os tracks lidos do AAF."""
    import datetime
    L = d["length"]
    m = f.create.Composition(d["name"] or "", "CompositionMob"); m.name = d["name"]
    m.mob_id = AVBMobID(bytes_le=bytes.fromhex(d["mob_id_hex"]))
    m.edit_rate = ER; m.media_kind_id = 0; m.usage_code = d["usage_code"]; m.mob_type_id = 1
    m.length = L; m.mc_mode = 0; m.num_scalars = 0; m.param_list = None; m.descriptor = None
    m.attributes = _comp_mob_attrs(f, d["usage_code"], L)
    now = datetime.datetime.now()
    m.property_data["creation_time"] = now; m.property_data["last_modified"] = now
    m.tracks = []
    idx = {"picture": 0, "sound": 0}
    for (mk, tag, payload) in d["tracks"]:
        if tag == "seq":
            seq = f.create.Sequence(ER, mk); seq.components = [_build_one(f, e, mk, tpl) for e in payload]
            comp = seq
        else:           # 'seg': 1 componente direto (SourceClip/Selector/...)
            comp = _build_one(f, payload, mk, tpl)
        idx[mk] += 1
        tk = f.create.Track(); tk.index = idx[mk]; tk.component = comp; tk.lock_number = 0
        m.tracks.append(tk)
    f.content.add_mob(m)
    return m

def _collect_clip_mobs(entry, acc):
    """coleta recursivamente os mob_hex de todos os SourceClips de um entry (incl. aninhados)."""
    kind, a1, a2, length, slot_id = entry
    if kind == "clip": acc.add(a1)
    elif kind == "combiner":
        for (mh, *_r) in a1: acc.add(mh)
    elif kind == "awarp":
        for (mh, *_r) in a2[0]: acc.add(mh)
    elif kind == "selector":
        for (mh, *_r) in a1: acc.add(mh)
    elif kind == "mcam_sel":
        for (mh, *_r) in a1: acc.add(mh)
    elif kind == "gain":
        if a2 is not None: _collect_clip_mobs(a2, acc)
    elif kind == "motion" and a2:
        acc.add(a2[0])                      # motion: a2 = (mob_hex, start, len) [_aaf_inner_clip]
    elif kind == "fx" and a2:
        _collect_clip_mobs(a2, acc)         # fx: a2 = ENTRY recursiva (multiefeito) -> recursar
    elif kind == "asplugin" and a2:
        _collect_clip_mobs(a2, acc)         # AudioSuite: a2 = ENTRY do clipe-fonte -> recursar
    elif kind == "adapter" and a2:
        acc.add(a2[0])
    elif kind in ("geo", "animatte", "mudo") and a2:
        _collect_clip_mobs(a2, acc)         # geo/animatte (do Premiere) e o desligado: a2 = a ENTRY de dentro
    elif kind == "collapse":
        for row in a1:                      # Collapse: a1 = as linhas das camadas
            for e in row: _collect_clip_mobs(e, acc)

def _collect_comp_mob_refs(d, acc):
    """refs de SourceClips dentro de um comp mob def (tracks)."""
    for (mk, tag, payload) in d["tracks"]:
        if tag == "seq":
            for e in payload: _collect_clip_mobs(e, acc)
        else:
            _collect_clip_mobs(payload, acc)

# ---------- autorar composição ----------
def _attrs(f, **kv):
    a = f.create.Attributes()
    for k, v in kv.items(): a[k] = v
    return a

def _filler(f, length, media="picture"):
    fl = f.create.Filler(ER, media); fl.length = length; return fl

def _trackref(f, media):
    tr = f.create.TrackRef(ER, media); tr.length = MAXLEN; tr.relative_scope = 0; tr.relative_track = -1; return tr

def _set_inner_clip(f, te, inner):
    """troca o SourceClip dentro do TrackEffect pelo clip do AAF. Trata efeitos de 1 input
    (Resize/PIP: clip em tracks[0]) E de 2 inputs (SBlend/3DWarp: fundo=ScopeReference em
    tracks[0], clip em tracks[1]) — varre TODOS os tracks e, na trilha de fundo (sem
    SourceClip), ajusta o gap ao comprimento do efeito."""
    if inner is None: return
    mob_hex, start, length = inner
    for tk in te.tracks:
        seq = getattr(tk, "component", None)
        if seq is None or type(seq).__name__ != "Sequence": continue
        sc = next((c for c in seq.components if type(c).__name__ == "SourceClip"), None)
        if sc is not None:
            sc.mob_id = AVBMobID(bytes_le=bytes.fromhex(_R(mob_hex)))
            sc.start_time = start; sc.length = length; sc.edit_rate = ER
        else:
            # trilha de fundo do efeito 2-input: o gap (ScopeReference/Filler) span = length do efeito
            for c in seq.components:
                if type(c).__name__ in ("Filler", "ScopeReference") and getattr(c, "length", 0):
                    c.length = te.length

def _achar_param_clip(o):
    """O 1º `ParamClip` (serializado) dentro de um molde — a trilha de controle que o MC já aceitou."""
    if isinstance(o, dict):
        if o.get("__class__") == "ParamClip":
            return o
        for v in o.values():
            r = _achar_param_clip(v)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _achar_param_clip(v)
            if r is not None:
                return r
    return None


def _geo_params(f, te, params, kfs, length, tpl):
    """Os valores do Motion no efeito geométrico (`_override_params`, que poda o resto) e, nos parâmetros animados,
    uma trilha de controle LINEAR (`interp_kind 3`, a forma da curva da transição e do gráfico de posição) com um
    ponto por instante. Parâmetro que o molde não tem (o `DVE_ROT_Y` do espelho) nasce de uma cópia de outro do mesmo
    tipo, com o uuid trocado."""
    import uuid as _uuid
    pl = te.property_data.get("param_list")
    if pl is not None:
        tem = {str(it.property_data.get("uuid")) for it in pl}
        for u, v in params.items():
            if u in tem:
                continue
            irmao = next((it for it in pl if it.property_data.get("value_type") == (2 if isinstance(v, float) else 1)),
                         None)
            if irmao is None:
                continue
            novo = materialize(f, serialize(irmao))
            novo.property_data["uuid"] = _uuid.UUID(u)
            novo.property_data["control_track"] = None
            pl.append(novo)
    _override_params(te, params, te.property_data.get("effect_id") or "EFF2_SBLEND")
    molde = _achar_param_clip(tpl.get("EFF2_BLEND_DISSOLVE"))
    for it in te.property_data.get("param_list") or []:
        pts = kfs.get(str(it.property_data.get("uuid")))
        if not pts or molde is None:
            continue
        pc = materialize(f, molde)
        pc.property_data["length"] = length
        pc.property_data["edit_rate"] = ER
        pc.property_data["interp_kind"] = 3                  # Linear
        pc.property_data["value_type"] = 2
        cps, vistos = [], set()
        for q, v in pts:
            q = max(0, min(int(length) - 1, int(q)))
            if q in vistos:
                continue
            vistos.add(q)
            cp = f.create.ParamControlPoint()
            cp.property_data["offset"] = [q, 1]
            cp.property_data["timescale"] = 1
            cp.property_data["value"] = float(v)
            cp.property_data["pp"] = [_mk_pp(f, c, 2, 0.0) for c in (5, 6, 7, 8)] + [_mk_pp(f, 9, 1, 1)]
            cps.append(cp)
        pc.property_data["control_points"] = cps
        it.property_data["control_track"] = pc
        it.property_data["value"] = float(pts[0][1])


def _set_inner_component(f, comp_effect, inner):
    """substitui o 1o componente NAO-Filler dentro do efeito (tracks[0].component=Sequence) pelo
    componente construido `inner` (efeito ANINHADO ou Filler de CAMADA DE AJUSTE). Multiefeito."""
    seq = comp_effect.tracks[0].component
    comps = list(seq.components)
    out = []; done = False
    for c in comps:
        if not done and type(c).__name__ != "Filler":
            out.append(inner); done = True
        else:
            out.append(c)
    if not done:                                   # template só tinha Fillers = CAMADA DE AJUSTE:
        out = [inner]                              # a Sequence interna é só o nosso gap (não somar ao do template)
    seq.property_data["components"] = out

def _set_combiner_clips(f, te, clips, length):
    """combiner = TrackEffect com N tracks; track[i].component = SourceClip do canal i.
    left_length/right_length ficam no valor do template (15, boilerplate) — NÃO setar p/ length."""
    te.length = length; te.edit_rate = ER
    for i, st in enumerate(te.tracks):
        sc = st.component
        if type(sc).__name__ != "SourceClip" or i >= len(clips): continue
        mob_hex, chan, start, clen = clips[i]
        sc.mob_id = AVBMobID(bytes_le=bytes.fromhex(_R(mob_hex))); sc.track_id = chan
        sc.start_time = start; sc.length = clen; sc.edit_rate = ER

def _mk_pp(f, code, typ, value):
    pp = f.create.ParamControlPointProperty()
    pp.property_data["code"] = code; pp.property_data["type"] = typ; pp.property_data["value"] = value
    return pp

def _mk_speed_cp(f, kf, is_first):
    cp = f.create.ParamControlPoint()
    cp.property_data["offset"] = [int(round(kf["t"])), 1]
    cp.property_data["timescale"] = 1
    cp.property_data["value"] = float(kf["speed"])
    pp = []
    if is_first: pp.append(_mk_pp(f, 14, 2, 0.0))            # PP_BASE_FRAME_U (só no 1º)
    pp.append(_mk_pp(f, 5, 2, float(kf["in_dt"])))           # in tangent pos
    pp.append(_mk_pp(f, 6, 2, float(kf["in_dv"])))           # in tangent val
    pp.append(_mk_pp(f, 7, 2, float(kf["out_dt"])))          # out tangent pos
    pp.append(_mk_pp(f, 8, 2, float(kf["out_dv"])))          # out tangent val
    pp.append(_mk_pp(f, 9, 1, int(kf["mode"])))             # tangent mode
    cp.property_data["pp"] = pp
    return cp

def _mk_offset_cp(f, t, val):
    cp = f.create.ParamControlPoint()
    num = int(round(t * 2))
    cp.property_data["offset"] = [num, 2] if num % 2 else [num // 2, 1]
    cp.property_data["timescale"] = 1
    cp.property_data["value"] = float(val)
    cp.property_data["pp"] = []
    return cp

def _set_dissolve_curve(te, length):
    """Reescala TODA curva de blend (0->1) do param_list (control_track.length + offset do último
    control point) p/ o comprimento REAL da transição. O template traz esses offsets FIXOS no
    comprimento do GOLD capturado (ex.: [0,1]->[24,1] p/ um dissolve de 24 frames) — para uma
    transição de OUTRO tamanho (ex.: 4 frames), o último ponto continua apontando pro frame 24,
    fora do range do componente (length=4) -> "Range specified for Dup is outside range of
    component" no MC ao editar (Extract) perto da transição, mesmo com adjacência/handle corretos.
    Achado 2026-07-10 comparando com transições REAIS de referência (mesma estrutura, offsets
    coerentes com o length de cada uma) — mesmo padrão já usado em _set_motion_speed p/ a curva de
    velocidade constante. O índice do param COM control_track varia por effect_id (áudio: índice 0;
    vídeo EFF2_BLEND_DISSOLVE: índice 1) -> varre TODOS os params, não só o primeiro."""
    for p in te.property_data.get("param_list") or []:
        ct = p.property_data.get("control_track")
        if ct is None:
            continue
        ct.property_data["length"] = length
        cps = ct.property_data.get("control_points") or []
        if len(cps) >= 2:
            off = cps[-1].property_data.get("offset")
            if isinstance(off, list) and off:
                cps[-1].property_data["offset"] = [length] + list(off[1:])

def _set_position_graph(f, me, pos, keys, render, length, inner):
    """Timewarp de POSIÇÃO (`_MFX_GRAPH_ENABLED 2`, molde = o preset do MC): p0 = a posição da fonte (contada do in do
    clipe de dentro) nos quadros `keys`, interpolação LINEAR — entre eles a velocidade é constante, então todo quadro
    cai no valor exato. Medido no MC 25.6 (laboratório, K1 e B22): 144/144 e 48/48 em Both Fields, Blended e
    FluidMotion. `speed_ratio` = comprimento ÷ clipe de dentro."""
    a = me.property_data.get("attributes")
    if a is not None:
        a["_SFX_RENDER"] = int(render)
        a["_SFX_IGNORE_RENDER_SETTING"] = 1
    pl = me.property_data.get("param_list") or []
    ct = pl[0].property_data.get("control_track") if pl else None
    if ct is not None:
        ct.property_data["length"] = length
        ct.property_data["interp_kind"] = 3                  # Linear
        cps = []
        for k in keys:
            cp = f.create.ParamControlPoint()
            cp.property_data["offset"] = [int(k), 1]
            cp.property_data["timescale"] = 1
            cp.property_data["value"] = float(pos[k])
            cp.property_data["pp"] = [_mk_pp(f, c, 2, 0.0) for c in (5, 6, 7, 8)] + [_mk_pp(f, 9, 1, 1)]
            cps.append(cp)
        ct.property_data["control_points"] = cps
    for p in pl[1:]:
        c2 = p.property_data.get("control_track")
        if c2 is not None:
            c2.property_data["length"] = length
    if inner is not None:
        me.property_data["speed_ratio"] = [int(length), int(inner[2])]

def _set_motion_speed(f, me, kfs, length):
    """Escreve a curva de velocidade. 1 keyframe = constante; vários = rampa (Bézier + integral)."""
    if not kfs: return
    pl = me.property_data.get("param_list")
    if not pl or len(pl) < 2: return
    sp_ct = pl[0].property_data.get("control_track")
    off_ct = pl[1].property_data.get("control_track")
    if len(kfs) == 1:                                        # CONSTANTE
        speed = kfs[0]["speed"]
        if sp_ct is not None:
            sp_ct.property_data["length"] = length
            cps = sp_ct.property_data.get("control_points") or []
            if cps:
                cps[0].property_data["value"] = float(speed)
                for pp in cps[0].property_data.get("pp", []) or []:
                    if pp.property_data.get("code") == 5: pp.property_data["value"] = -length / 10.0
                    elif pp.property_data.get("code") == 7: pp.property_data["value"] = length / 10.0
        if off_ct is not None:
            off_ct.property_data["length"] = length
            ocps = off_ct.property_data.get("control_points") or []
            if len(ocps) >= 2:
                ocps[0].property_data["value"] = 0.0
                ocps[-1].property_data["value"] = float(round(abs(speed) * length))
                off = ocps[-1].property_data.get("offset")
                if isinstance(off, list) and off: ocps[-1].property_data["offset"] = [length] + list(off[1:])
    else:                                                   # RAMPA (multi-ponto)
        if sp_ct is not None:
            sp_ct.property_data["length"] = length
            sp_ct.property_data["control_points"] = [_mk_speed_cp(f, kf, i == 0) for i, kf in enumerate(kfs)]
        if off_ct is not None:
            off_ct.property_data["length"] = length
            off_ct.property_data["control_points"] = [_mk_offset_cp(f, t, v) for t, v in _offset_map(kfs, length)]
    if len(pl) > 2:
        ct2 = pl[2].property_data.get("control_track")
        if ct2 is not None: ct2.property_data["length"] = length

# efeitos cujos params do AAF (Definition AUID) casam 1:1 com o uuid do ParameterItem do .avb ->
# seguro PODAR o param_list p/ refletir só os ajustes do edit (o template desses é o SUPERSET de
# params, ordem canônica). Plugins (SubCap) têm params CFUser cujos uuids NÃO casam -> NÃO podar.
_VARYING = object()   # sentinela: param VaryingValue (curva) presente no AAF mas sem valor escalar legível
# SubCap (E4FE520A) entra: seus params casam com o AAF (uuids GUID), e o CONTEÚDO por instância (texto da
# legenda) é reconstruído sobrescrevendo o `data` do CFUserParam (vt=4) a partir do blob AVUP do AAF.
GEOM_BLEND_FX = {"EFF2_SBLEND", "EFF2_BLEND_RESIZE", "EFF2_BLEND_PIP", "EFF2_RGB_COLOR_CORRECTION",
                 "E4FE520A-B815-447F-A969-2D5E1C5F6C14"}

def _parse_avup(blob):
    """AAF ConstantValue de param de PLUGIN (ex SubCap) = blob AVUP serializado:
    'PUVA' + size(4) + 4949 + 01000000 + 4949 + uuid_le(16) + size1(4) + size2(4) + data(size2) + 'END'.
    Extrai (uuid, data). O data carrega o CONTEÚDO por instância (ex texto da legenda 'legenda 1')."""
    try: b = bytes(blob)
    except Exception: return None
    if len(b) < 40 or b[0:4] != b'PUVA': return None
    try:
        uid = uuid.UUID(bytes_le=b[16:32])
        size2 = int.from_bytes(b[36:40], "little")
        return uid, b[40:40 + size2]
    except Exception:
        return None

# ---------- Avid Title+ (texto) ----------
TITLE_EID = "E4EEBB07-AFAA-4122-BFA8-0A838BB40A8C"            # effect_id do TrackEffect Avid Title+ (atual)
TITLE_MQP_UUID = "67a614ac-29b6-4afe-b9cc-8107a5dd3468"       # param vt=4 CFUserParam = MQP Blob (estilo)
TITLE_OFF = os.environ.get("AVB_NO_TITLE") == "1"            # kill-switch: título -> gap (comportamento antigo)

def _avup_at_puva(blob):
    """(uuid, data) de um blob AVUP cujo 'PUVA' vem APÓS um prefixo (ex.: UUID CFUser de 16B) — o MQP
    Blob do Title+ (≠ SubCap, que tem PUVA no offset 0 -> _parse_avup). `data` = o DB de estilo (texto)."""
    try: b = bytes(blob)
    except Exception: return None
    off = b.find(b'PUVA')
    if off < 0 or len(b) - off < 40: return None
    try:
        uid = uuid.UUID(bytes_le=b[off + 16:off + 32])
        size2 = int.from_bytes(b[off + 36:off + 40], "little")
        return uid, b[off + 40:off + 40 + size2]
    except Exception:
        return None

def _curvas_no_comprimento(te, length):
    """Leva toda curva do `param_list` (`control_track`) ao comprimento do efeito, na PROPORÇÃO: o `ParamClip.length` e
    o offset de cada ponto. O molde do Titler+ traz a curva do título capturado (24 quadros: o último ponto em 2304 =
    24 × 96, `timescale 4`) e, num título de outro tamanho, a bin abria mas o Save All / salvamento automático do MC
    24.6 dava "Range specified for Dup is outside range of component" (R04, 2026-10-29: um título de 26 quadros na V7,
    achado por bissecção). A mesma classe do `_set_dissolve_curve` das transições, com outra unidade de offset."""
    for p in te.property_data.get("param_list") or []:
        ct = p.property_data.get("control_track")
        if ct is None:
            continue
        antes = int(ct.property_data.get("length") or 0)
        ct.property_data["length"] = length
        if antes <= 0 or antes == length:
            continue
        for cp in ct.property_data.get("control_points") or []:
            off = cp.property_data.get("offset")
            if isinstance(off, list) and off:
                cp.property_data["offset"] = [int(round(off[0] * length / antes))] + list(off[1:])

def _build_title(f, estilo, text, length, tkind, tpl):
    """Autora o TrackEffect Avid Title+ (eid E4EEBB07) reusando o template capturado, sobrescrevendo o
    TEXTO (atributo `_TTEXT` = `\\x00\\x00'T+: <texto> '\\x00`) e o MQP Blob (param vt=4 CFUserParam uuid
    67a614ac = estilo+posição+fonte+cor+alinhamento, um DB de texto). Mesmo mecanismo do SubCap. As 2
    tracks internas (fg título + bg) viram Filler(length). Sem template -> gap (mantém a posição).

    `estilo` é um dict: `{'mqp_hex': ...}` (título vindo do AAF/Avid, o MQP pronto da origem) ou
    `{'bloco': <titulo neutro>}` (vindo do Premiere: SINTETIZA o MQP a partir do molde do template,
    `titulos/avid_escrita.py` — texto, fonte, corpo, cor, alinhamento e posição)."""
    if TITLE_EID not in tpl:
        return _filler(f, length, tkind)
    te = materialize(f, tpl[TITLE_EID]); te.length = length; te.edit_rate = ER
    _curvas_no_comprimento(te, length)
    for tk in te.tracks:                                      # tracks internas (fg/bg) = Filler(length)
        seq = getattr(tk, "component", None)
        if seq is not None:
            seq.property_data["components"] = [_filler(f, length, tkind)]
    a = te.property_data.get("attributes")
    if a is not None and text is not None:
        try: a["_TTEXT"] = bytearray(b"\x00\x00T+: " + text.encode("utf-8") + b" \x00")
        except Exception: pass
    cf = next((it.property_data.get("value") for it in te.property_data.get("param_list") or []
               if str(it.property_data.get("uuid")) == TITLE_MQP_UUID
               and type(it.property_data.get("value")).__name__ == "CFUserParam"), None)
    if cf is not None and isinstance(estilo, dict):
        if estilo.get("bloco"):                               # Premiere: sintetiza o MQP do molde
            from titulos import avid_escrita
            molde = bytes(cf.property_data.get("data") or b"").decode("utf-8", "replace")
            novo, _av = avid_escrita.sintetizar(molde, estilo["bloco"])
            cf.property_data["data"] = bytearray(novo.encode("utf-8"))
        elif estilo.get("mqp_hex"):                           # AAF: o MQP pronto da origem
            parsed = _avup_at_puva(bytes.fromhex(estilo["mqp_hex"]))
            if parsed is not None:
                cf.property_data["data"] = bytearray(parsed[1])
    return te

def _title_entry(s):
    """Segment de título -> entry ('title', estilo, texto, dur, None). `estilo` = `{'mqp_hex': …}` do
    título do Avid (AAF) ou `{'bloco': <titulo neutro>}` do Premiere (sintetiza o MQP). None se não
    houver título reconstruível."""
    for e in (s.get("effects") or []):
        if e.get("category") == "title":
            p = e.get("params") or {}
            if p.get("mqp_hex"):
                return ("title", {"mqp_hex": p["mqp_hex"]}, p.get("text"), s["duration_frames"], None)
            t = p.get("titulo")
            texto = ((t.get("caixas") or [{}])[0].get("texto")) if t else None
            if texto:
                return ("title", {"bloco": t}, texto, s["duration_frames"], None)
    return None

def _override_params(te, aaf_params, effect_id=None):
    """sobrescreve os valores do param_list casando por UUID com os params do AAF ({uuid: valor}).
    Para efeitos geométricos (GEOM_BLEND_FX) também PODA os params do template ausentes no AAF: um
    efeito sem uma dada transformação NÃO carrega o param dela (ex 3DWarp sem posição/escala = 9
    params, não os 15 do template capturado do FASE 1 EFEITO 40/32/120/120). A poda preserva a ordem
    do template = ordem do gabarito."""
    pl = te.property_data.get("param_list")
    if not pl or not aaf_params: return
    for it in pl:
        u = str(it.property_data.get("uuid"))
        if u not in aaf_params:
            continue
        val = aaf_params[u]
        if val is _VARYING:                          # curva no AAF: mantém o valor do template (poda já o preserva)
            continue
        vt = it.property_data.get("value_type")
        try:
            if vt == 2:   it.property_data["value"] = float(val)        # AAFRational -> float
            elif vt == 1: it.property_data["value"] = int(bool(val)) if isinstance(val, bool) else int(val)
            elif vt == 4:                                              # CFUserParam (plugin): data por instância
                cf = it.property_data.get("value")
                parsed = _parse_avup(val)
                if parsed is not None and type(cf).__name__ == "CFUserParam":
                    cf.property_data["uuid"] = parsed[0]               # tipo do CFUser (constante)
                    cf.property_data["data"] = bytearray(parsed[1])    # ex texto 'legenda 3'
        except (TypeError, ValueError):
            pass
    if effect_id in GEOM_BLEND_FX:
        for i in range(len(pl) - 1, -1, -1):                           # poda o que não veio do AAF
            if str(pl[i].property_data.get("uuid")) not in aaf_params:
                del pl[i]

def _build_selector(f, tpl, chans, selected, length, tkind):
    """Selector: rebuild tracks (1 SourceClip por canal alternado), selected, is_ganged, length."""
    if not chans:                        # sem canais -> Selector inválido (selected<len(tracks) falha); vira gap
        return _filler(f, length, tkind)
    sel = materialize(f, tpl["__selector__"]); sel.length = length; sel.edit_rate = ER
    selected = max(0, min(selected or 0, len(chans) - 1))   # clampar no range dos canais
    sel.property_data["selected"] = selected; sel.property_data["is_ganged"] = True
    tks = []
    for i, (mob_hex, chan, start, clen) in enumerate(chans):
        sc = f.create.SourceClip(ER, tkind)
        sc.mob_id = AVBMobID(bytes_le=bytes.fromhex(_R(mob_hex))); sc.track_id = chan
        sc.start_time = start; sc.length = length
        tk = f.create.Track(); tk.index = i + 1; tk.component = sc; tk.lock_number = 0
        tks.append(tk)
    sel.tracks = tks
    a = sel.property_data.get("attributes")
    if a is not None:
        try: a["_AAF_SELECTED"] = selected
        except Exception: pass
    return sel

def _build_mudo(f, comp, length, tkind):
    """O clipe DESLIGADO como o Mute Clips do MC grava (lido nas bins reais do PRODUCAO-A, MC 24.6/Windows): `Selector`
    com o ramo 0 = Filler (o que o programa mostra) e o ramo 1 = o clipe com os efeitos dele; `selected 0`,
    `is_ganged`, `_DISABLE_CLIP_FLAG 1`, `_AAF_SELECTED 0`; no vídeo a trilha do Filler leva o TrackRef de fundo."""
    sel = f.create.Selector(ER, tkind); sel.length = length
    sel.mc_mode = 0; sel.num_scalars = 0; sel.selected = 0; sel.is_ganged = True
    sel.attributes["_DISABLE_CLIP_FLAG"] = 1; sel.attributes["_AAF_SELECTED"] = 0
    vazio = f.create.Track(); vazio.component = _filler(f, length, tkind); vazio.lock_number = 0
    if tkind == "picture":
        vazio.filler_proxy = _trackref(f, tkind); vazio.filler_proxy.relative_scope = 1   # o do MC: 1, não 0
    clipe = f.create.Track(); clipe.component = comp; clipe.lock_number = 0
    sel.tracks = [vazio, clipe]
    return sel

def _build_collapse(f, linhas, length, tkind, tpl):
    """Collapse ESCRITO (o MC renderiza igual ao que ele mesmo faz: 0 px no B21): o Submaster do MC sem as trilhas
    + as trilhas INTERNAS. UMA camada = uma trilha interna (índice 1) cujos vazios olham a trilha de BAIXO
    (`relative_scope 1`); VÁRIAS = a 1ª interna só de FUNDO (Filler do tamanho todo, olha embaixo) e uma por camada,
    de baixo para cima (índices 2…, `relative_scope 0`). Cada camada vai completada até o fim do Collapse."""
    te = materialize(f, tpl["EFF_SUBMASTER"]); te.length = length; te.edit_rate = ER

    def interna(indice, comps, olha_embaixo):
        seq = f.create.Sequence(ER, tkind); seq.components = comps
        tk = f.create.Track(); tk.index = indice; tk.component = seq; tk.lock_number = 0
        tk.filler_proxy = _trackref(f, tkind); tk.filler_proxy.relative_scope = 1 if olha_embaixo else 0
        return tk

    def camada(row):
        comps = [_filler(f, 0, tkind)] + [_build_one(f, e, tkind, tpl) for e in row]
        usado = sum(e[3] for e in row if e[0] != "trans") - sum(e[3] for e in row if e[0] == "trans")
        return comps + [_filler(f, max(0, length - usado), tkind)]

    if len(linhas) == 1:
        te.tracks = [interna(1, camada(linhas[0]), True)]
    else:
        te.tracks = [interna(1, [_filler(f, length, tkind)], True)] + [
            interna(i + 2, camada(row), False) for i, row in enumerate(linhas)]
    return te

def _automacao_de_volume(f, pontos, length):
    """A automação de VOLUME do MC (a keyframe do Volume, separada do ganho): a 2ª trilha do `PanVolumeEffect`, SEM
    índice, `control_code 1000`, com um `ControlClip` do tamanho do clipe (`media_kind 10`, `interp_kind 3` = linear) e
    um `ControlPoint` por ponto — `offset` em quadros desde o INÍCIO DO CLIPE na timeline, `value` na escala do ganho
    (2^29 = 0 dB). Gabarito: o MC 25.12 Mac (2026-10-29, bins `VOLUME FIXO` do autor e `VOLUME KF`; banco
    `avb/escrita.md`, GANHO)."""
    cc = f.create.ControlClip(ER)
    cc.media_kind_id = 10
    cc.attributes = None
    cc.length = length
    cc.interp_kind = 3
    cc.control_points = []
    for q, v in pontos:
        cp = f.create.ControlPoint()
        cp.offset = [int(q), 1]
        cp.time_scale = 1
        cp.value = [int(v), 1]
        cp.pp = []
        cc.control_points.append(cp)
    tk = f.create.Track(); tk.component = cc; tk.control_code = 1000; tk.lock_number = 0
    return tk

def _build_one(f, entry, tkind, tpl):
    """constrói 1 componente .avb a partir de 1 entry (recursivo p/ gain->selector->clip)."""
    kind, a1, a2, length, slot_id = entry
    if kind == "clip":
        sc = f.create.SourceClip(ER, tkind)
        sc.mob_id = AVBMobID(bytes_le=bytes.fromhex(_R(a1)))
        sc.track_id = _chan(a1, slot_id) if tkind == "sound" else (slot_id or 1)
        sc.start_time = a2; sc.length = length
        return sc
    if kind == "gap":
        return _filler(f, length, tkind)
    if kind == "mudo":           # a2 = a ENTRY do clipe desligado
        return _build_mudo(f, _build_one(f, a2, tkind, tpl), length, tkind)
    if kind == "collapse":       # a1 = [linha de entries por camada do nest], de baixo para cima
        return _build_collapse(f, a1, length, tkind, tpl)
    if kind == "title":          # Avid Title+: a1=mqp_hex (estilo do AAF), a2=texto
        return _build_title(f, a1, a2, length, tkind, tpl)
    if kind == "asplugin":       # AudioSuite: a1=nome do plugin, a2=inner entry, slot_id=(chunk,preset)
        key = "__asp__" + str(a1)
        if key not in tpl:       # plugin sem template -> dropa o efeito, mantém o clipe-fonte
            return _build_one(f, a2, tkind, tpl) if a2 is not None else _filler(f, length, tkind)
        te = materialize(f, tpl[key]); te.length = length; te.edit_rate = ER
        # SEMPRE reconstruir o inner a partir do AAF e substituir o do template. O template pode
        # envolver um Selector (multicam, quando foi capturado de clipe de grupo) que referencia mobs
        # de OUTRO projeto -> _set_inner_clip não o trocaria e sobraria ref morta (missing mob). O AAF
        # diz o inner correto (SourceClip simples, selector, etc.) e _build_one já resolve canal/track_id.
        if a2 is not None:
            _set_inner_component(f, te, _build_one(f, a2, tkind, tpl))
        chunk, preset = slot_id if slot_id else (None, None)
        pls = te.property_data.get("plugins")
        if chunk is not None and pls:
            chs = pls[0].property_data.get("chunks")
            if chs: chs[0].property_data["data"] = bytearray(chunk)   # config por instância (ex ganho)
            # O PAINEL do plugin lê o estado do attr `_AUDIO_SUITE_EFFECT_N_ALL_CHUNKS` (não do chunk).
            # Formato = header fixo do plugin + o chunk NO FINAL; troca o final do template pelo chunk novo.
            attrs = te.property_data.get("attributes")
            if attrs is not None:
                for k in list(attrs.keys()):
                    if "ALL_CHUNKS" in str(k):
                        old = bytes(attrs[k])
                        if len(old) >= len(chunk):
                            attrs[k] = bytearray(old[:len(old) - len(chunk)] + chunk)
        if preset is not None:
            te.property_data["preset_path"] = bytearray(preset)
        return te
    if kind == "combiner":
        te = materialize(f, tpl["EFF2_AUDIO_CHANNEL_COMBINER"]); _set_combiner_clips(f, te, a1, length); return te
    if kind == "awarp":
        me = materialize(f, tpl["EFF_TIMEWARP.AUDIO_TIME_WARP"]); me.length = length; me.edit_rate = ER
        if a1: me.speed_ratio = a1
        comb_clips, comb_len, inner_entry = a2
        inner = me.tracks[0].component
        if type(inner).__name__ == "TrackEffect" and comb_clips:
            _set_combiner_clips(f, inner, comb_clips, comb_len)             # warp de clipe estéreo (combiner)
        elif inner_entry is not None:
            me.tracks[0].component = _build_one(f, inner_entry, tkind, tpl) # warp de CLIPE SIMPLES: troca o combiner do template
        return me
    if kind == "trans":
        te = materialize(f, tpl[a1]); te.length = length; te.cutpoint = a2; te.edit_rate = ER
        _set_dissolve_curve(te, length); return te
    if kind == "animatte":       # máscara do Premiere: a2 = a entry de dentro, slot_id = [(percent_time, bzfx)]
        if "EFF_ANIMATTE" not in tpl:
            return _build_one(f, a2, tkind, tpl)
        te = materialize(f, tpl["EFF_ANIMATTE"]); te.length = length; te.edit_rate = ER
        inner = _build_one(f, a2, tkind, tpl)
        for tk in te.tracks[:-1]:                      # o fundo (olha a trilha de baixo): o comprimento do efeito
            seq = getattr(tk, "component", None)
            for c in (seq.components if type(seq).__name__ == "Sequence" else []):
                if type(c).__name__ == "Filler":
                    c.length = length
        seq = te.tracks[-1].component
        if type(seq).__name__ == "Sequence":
            seq.property_data["components"] = [inner]
        else:
            te.tracks[-1].component = inner
        kp = te.property_data.get("keyframes")
        params = kp.property_data.get("parameters") if kp is not None else None
        if params:
            base = params[0]
            novos = []
            for pt, b in slot_id:
                q = materialize(f, serialize(base))
                q.property_data["percent_time"] = int(pt)
                q.property_data["user_param"] = bytearray(b)
                q.property_data["selected"] = False
                novos.append(q)
            kp.property_data["parameters"] = novos
            # ⚠️ hipótese (2026-10-25): no molde do MC, keyframe_size 700 = 168 + o bloco de 532 bytes; um bloco
            # maior (mais vértices, mais formas) leva o tamanho junto
            ks = kp.property_data.get("keyframe_size")
            ub = len(base.property_data.get("user_param") or b"")
            if isinstance(ks, int) and ub:
                kp.property_data["keyframe_size"] = ks - ub + max(len(b) for _pt, b in slot_id)
        return te
    if kind == "geo":            # Motion do Premiere: a1 = Resize/PIP, a2 = a entry de dentro, slot_id = params
        if a1 not in tpl:
            return _build_one(f, a2, tkind, tpl)
        te = materialize(f, tpl[a1]); te.length = length; te.edit_rate = ER
        inner = _build_one(f, a2, tkind, tpl)
        # o plano vai na ÚLTIMA trilha interna (o Resize tem uma; o PIP, duas — a 1ª é o fundo que olha embaixo,
        # banco avb/estruturas.md §PIP e Resize); as outras só acompanham o comprimento
        for tk in te.tracks[:-1]:
            seq = getattr(tk, "component", None)
            for c in (seq.components if type(seq).__name__ == "Sequence" else [seq] if seq is not None else []):
                if type(c).__name__ in ("Filler", "ScopeReference") and getattr(c, "length", 0):
                    c.length = length
        seq = te.tracks[-1].component
        if type(seq).__name__ == "Sequence":
            seq.property_data["components"] = [inner]
        else:
            te.tracks[-1].component = inner
        params, kfs = slot_id
        _geo_params(f, te, params, kfs, length, tpl)
        return te
    if kind == "adapter":        # a1 = taxa da fonte, a2 = (mob_hex, start, len) EM QUADROS DA FONTE
        from fractions import Fraction
        me = materialize(f, tpl["EFF_TIMEWARP_ADAPTADOR"]); me.length = length; me.edit_rate = ER
        tl = float(_TL_FPS or ER)
        if abs(tl - round(tl) * 1000 / 1001) < 1e-3:                    # 23,976 / 29,97 / 59,94: a fração NTSC exata
            tl = round(tl) * 1000 / 1001
        fr = Fraction(tl / a1).limit_denominator(100000)
        me.speed_ratio = [fr.numerator, fr.denominator]                 # 23,976 ÷ 100 = [240, 1001]
        attrs = me.property_data.get("attributes")
        if attrs is not None:
            attrs["_SFX_RENDER"] = 2                                     # Both Fields: quadro inteiro (piso)
        for p in me.property_data.get("param_list") or []:
            ct = p.property_data.get("control_track")
            if ct is not None:
                ct.property_data["length"] = length
        _set_inner_clip(f, me, a2); _taxa_de_dentro(me, a1); return me
    if kind == "motion" and a1 and a1[0] == "pos":          # rampa de outro programa: gráfico de POSIÇÃO
        me = materialize(f, tpl["EFF_TIMEWARP_POSICAO"]); me.length = length; me.edit_rate = ER
        _set_position_graph(f, me, a1[1], a1[2], a1[3], length, a2); _set_inner_clip(f, me, a2)
        if len(a1) > 4 and a1[4]:                            # fonte de outra taxa: o adaptador PROMOVIDO
            attrs = me.property_data.get("attributes")
            if attrs is not None:
                attrs["_MIXMATCH_MOTIONADAPTER"] = 4
                attrs["_MFX_VIEW_SPD_TOP"] = 300; attrs["_MFX_VIEW_SPD_BOTTOM"] = -100
            _taxa_de_dentro(me, a1[4])
        return me
    if kind == "motion":
        sr, kfs = a1
        me = materialize(f, tpl["EFF_ADV_MOTION_CTL"]); me.length = length; me.edit_rate = ER
        if sr: me.speed_ratio = sr
        _set_motion_speed(f, me, kfs, length); _set_inner_clip(f, me, a2); return me
    if kind == "selector":   # a1 = canais [(mob,chan,start,len)], a2 = selected idx
        return _build_selector(f, tpl, a1, a2, length, tkind)
    if kind == "mcam_sel":   # a1 = [(cont_hex, track_id, start, len)...], a2 = selected idx
        if not a1:           # sem canais -> Selector inválido; vira gap
            return _filler(f, length, tkind)
        a2 = max(0, min(a2 or 0, len(a1) - 1))     # clampar selected no range
        sel = materialize(f, tpl["__selector__"]); sel.length = length; sel.edit_rate = ER
        sel.property_data["selected"] = a2; sel.property_data["is_ganged"] = True
        sel.property_data["media_kind_id"] = 1 if tkind == "picture" else 2
        tks = []
        for i, (cont_hex, track_id, start, _cl) in enumerate(a1):
            sc = f.create.SourceClip(ER, tkind)
            sc.mob_id = AVBMobID(bytes_le=bytes.fromhex(cont_hex)); sc.track_id = track_id
            sc.start_time = start; sc.length = length
            tk = f.create.Track(); tk.index = i + 1; tk.component = sc; tk.lock_number = 0
            tks.append(tk)
        sel.tracks = tks
        a_attrs = sel.property_data.get("attributes")
        if a_attrs is not None:
            try: a_attrs["_AAF_SELECTED"] = a2
            except Exception: pass
        return sel
    if kind == "gain":       # a1 = level (num/2^29), a2 = inner entry
        pv = materialize(f, tpl["__panvol__"]); pv.length = length; pv.edit_rate = ER
        pd = pv.property_data
        # só automação (ganho unity): o MC grava `level_set` desligado (gabarito `VOLUME KF`, 2026-10-29)
        if a1 is not None: pd["level"] = a1; pd["level_set"] = a1 != UNITY_GAIN
        pd["pan"] = pd.get("pan", 16384); pd["pan_set"] = False
        inner = _build_one(f, a2, tkind, tpl) if a2 is not None else None
        if inner is not None:
            tk = f.create.Track(); tk.index = 1; tk.component = inner; tk.lock_number = 0
            pv.tracks = [tk]
            if type(inner).__name__ == "Selector":      # selector dentro do gain leva a assinatura do ganho
                ia = inner.property_data.get("attributes")
                if ia is not None and a1 is not None:
                    try: ia["_EFFECT_ANCILLARY_SIGNATURE"] = bytearray(str(a1).encode())
                    except Exception: pass
        if slot_id and inner is not None:
            pv.tracks = list(pv.tracks) + [_automacao_de_volume(f, slot_id, length)]
        return pv
    # fx: a1=effect_id, a2=inner ENTRY (clip | efeito aninhado | gap-adjustment), slot_id=params do AAF
    if a1 not in tpl:        # efeito sem template (frameflex/stabilize/titler...) -> DROP, mantém o inner
        return _build_one(f, a2, tkind, tpl) if a2 is not None else _filler(f, length, tkind)
    te = materialize(f, tpl[a1]); te.length = length; te.edit_rate = ER
    if a2 is not None and a2[0] == "clip":
        _set_inner_clip(f, te, (a2[1], a2[2], a2[3]))          # in-place (mantem comportamento 1-efeito)
    elif a2 is not None:
        _set_inner_component(f, te, _build_one(f, a2, tkind, tpl))  # aninhado ou camada de ajuste
    _override_params(te, slot_id, a1); return te

def build(f, name, tracks, tpl, tc_fps, fmt_type, fmt_str, comp_mobs=None, inicio=None):
    def tlen(tr): return sum(c[3] for c in tr if c[0] != "trans") - sum(c[3] for c in tr if c[0] == "trans")
    total = max((tlen(tr) for _k, tr in tracks), default=0)
    # autorar comp mobs (subclip uc2 / grupo uc4 / container uc5) — TODOS do AAF (grupos aparecem na bin)
    if comp_mobs:
        authored = {}
        for mh, d in comp_mobs.items():
            authored[mh] = _author_comp_mob(f, d, tpl)
        # linkage _MATCH: container(uc5)._MATCH -> grupo(uc4) cujos selectors apontam p/ ele
        for h, d in comp_mobs.items():
            if d["usage_code"] != 4: continue
            refs = set(); _collect_comp_mob_refs(d, refs)
            for c in refs:
                if c in authored and comp_mobs.get(c, {}).get("usage_code") == 5:
                    mr = f.create.MobRef()
                    mr.property_data["position"] = 0
                    mr.property_data["mob_id"] = AVBMobID(bytes_le=bytes.fromhex(h))
                    authored[c].attributes["_MATCH"] = mr
    comp = f.create.Composition(name, "CompositionMob"); comp.name = name
    comp.mob_id = AVBMobID(bytes_le=bytes(bytearray(COMP_PREFIX) + os.urandom(16)))
    comp.edit_rate = ER; comp.media_kind_id = 0; comp.usage_code = 0
    comp.length = total; comp.mc_mode = 0; comp.num_scalars = 0; comp.param_list = None
    a = _attrs(f, _VERSION=2); a['SEQUERNCE_FORMAT_TYPE'] = fmt_type; a['SEQUERNCE_FORMAT_STRING'] = fmt_str
    a['_USER'] = f.create.Attributes(); a['_USER_POS'] = total
    comp.attributes = a
    comp.session_attrs = _attrs(f, _VIS_START=0, _VIS_END=2147483647)
    comp.tracks = []
    idx = {"picture": 0, "sound": 0}        # índices independentes por media_kind
    has_picture = any(k == "picture" for k, _ in tracks)
    for tkind, tr in tracks:
        seq = f.create.Sequence(ER, tkind); seq.components = []
        if not tr or tr[0][0] != "gap":              # lead Filler(0) só se não começa com gap
            seq.components.append(_filler(f, 0, tkind))
        for entry in tr:
            if entry[0] == "trans" and TRANS_OFF:    # corte seco: PULA o componente (zero frames extras
                continue                             # aqui; tlen() já conta com essa entry subtraída)
            # CLAMP do OUT: se o clipe referencia além do fim do master (start+len > master_len), o
            # Avid estoura PMM_INSUFFICIENT_MEDIA no corte. Apara a duração ao que a mídia tem e insere
            # um filler compensatório do tamanho aparado (a timeline é sequencial: sem isso, tudo
            # depois desloca). Aparo de 1-2 frames de áudio = silêncio imperceptível. "gain" embrulha um
            # ("clip",...) em entry[2] — clampa o INNER e reflete no dur de fora também.
            pad = 0
            clampable = entry if entry[0] == "clip" else (
                entry[2] if entry[0] == "gain" and entry[2] and entry[2][0] == "clip" else None)
            if clampable is not None and _MASTER_LEN:
                ml = _MASTER_LEN.get(_R(clampable[1]))
                if ml is not None and clampable[2] + clampable[3] > ml:
                    pad = clampable[2] + clampable[3] - ml
                    new_clip = (clampable[0], clampable[1], clampable[2], max(1, clampable[3] - pad), clampable[4])
                    if entry[0] == "clip":
                        entry = new_clip
                    else:
                        entry = (entry[0], entry[1], new_clip, max(1, entry[3] - pad), entry[4])
            seq.components.append(_build_one(f, entry, tkind, tpl))
            if pad > 0:
                seq.components.append(_filler(f, pad, tkind))
        # trail Filler: PAD até o comprimento TOTAL da timeline. Sem isso a track termina no seu
        # último clipe (tlen < total) e o MC estoura ao navegar/reproduzir além do fim dela
        # (PMM_INSUFFICIENT_MEDIA + assertion GetVideoFrameOffset < GetGlobalDuration). Todas as
        # tracks precisam abranger a duração inteira do CompositionMob.
        seq.components.append(_filler(f, max(0, total - tlen(tr)), tkind))
        idx[tkind] += 1
        vt = f.create.Track(); vt.index = idx[tkind]; vt.component = seq; vt.lock_number = 0
        # ⛔ o TrackRef de fundo ("o vazio mostra a trilha de baixo") é só da IMAGEM. O MC não grava `filler_proxy` em
        # trilha de som (390 de 390 nas bins reais); com ele o VAZIO de uma trilha de som TOCAVA a de baixo — medido
        # de ouvido no export do MC 25.12 (2026-11-25): A3 vazia tocava a A2, o tom saía 3×, 6×, 9× mais alto.
        if tkind != "sound":
            vt.filler_proxy = _trackref(f, tkind)
        if tkind == "sound":
            vt.session_attr = _attrs(f, _MONSTATE=2, _ENBLSTATE=1)
            # nº de canais da trilha: combiner/awarp emitem N canais -> trilha precisa de _TRACK_FORMAT=N
            chans = 1; has_gain = has_auto = False
            for kind, a1, a2, _l, _s in tr:
                if kind == "combiner": chans = max(chans, len(a1))
                elif kind == "awarp":  chans = max(chans, len(a2[0]))
                elif kind == "gain":
                    has_gain = has_gain or a1 != UNITY_GAIN; has_auto = has_auto or bool(_s)
            if has_gain:                                             # clip gain ativo na trilha
                vt.session_attr["_TRK_CLIP_G"] = 1
            if has_auto:                                             # automação de volume na trilha (gabarito do MC)
                vt.session_attr["_TRK_AUTO_G"] = 1
            if chans > 1:
                vt.attributes = _attrs(f, _TRACK_FORMAT=chans)        # 2=estéreo
            else:
                vt.attributes = _attrs(f, AudioMixerCompSolo=0, AudioMixerCompMute=0)
        else:
            # ⭐ `_ENBLSTATE=1` = como o MC 25.12 grava a trilha de vídeo de uma sequência NOVA (medido 2026-10-24, Mac:
            # V1/A1/A2/TC todos 1). Com 0 a V1 abria desligada (autor, PRODC 2_SEQ, Windows 2026-10-18).
            vt.session_attr = _attrs(f, _ENBLSTATE=1, _MONSTATE=0)
        comp.tracks.append(vt)
    # ⭐ O MONITOR na trilha de vídeo de MAIOR índice (cumulativo para baixo): sem ele o Composer abre preto
    # (banco, track-session-attrs.json; a PRODC 2_SEQ saiu assim e o script da rodada ligava na mão, 2026-10-18).
    pics = [t for t in comp.tracks if getattr(t, "media_kind", "") == "picture"]
    if pics:
        max(pics, key=lambda t: t.index).session_attr["_MONSTATE"] = 1
    if not has_picture:                              # comp só de áudio: V1 vazia (convenção Avid)
        pseq = f.create.Sequence(ER, "picture"); pseq.components = [_filler(f, total, "picture")]
        pt = f.create.Track(); pt.index = 1; pt.component = pseq; pt.lock_number = 0
        pt.filler_proxy = _trackref(f, "picture"); pt.session_attr = _attrs(f, _ENBLSTATE=1, _MONSTATE=1)
        comp.tracks.append(pt)
    tc = f.create.Timecode(ER, "timecode"); tc.length = total; tc.flags = 0; tc.fps = tc_fps
    # o TC de início da ORIGEM (quadros na base do TC); sem ele, 01:00:00:00 (banco B062: a sequência do Premiere que
    # começa em 00:00:00:00 ou 10:00:00:00 chegava ao Avid sempre em 01:00:00:00 — o mesmo clipe com dois TCs)
    tc.start = int(inicio) if inicio is not None and int(inicio) >= 0 else 3600 * tc_fps
    tct = f.create.Track(); tct.index = 1; tct.component = tc; tct.lock_number = 0; tct.session_attr = _attrs(f, _ENBLSTATE=0)
    comp.tracks.append(tct)
    dseq = f.create.Sequence(ER, "DescriptiveMetadata"); dseq.components = [_filler(f, total, "DescriptiveMetadata")]
    dt = f.create.Track(); dt.index = 1; dt.component = dseq; dt.lock_number = 0; dt.filler_proxy = _trackref(f, "DescriptiveMetadata")
    comp.tracks.append(dt)
    f.content.add_mob(comp)
    return comp

def _fix_component(f, c, present, cnt):
    """Rede de segurança: troca SourceClip que referencia mob AUSENTE (leak de template do gabarito)
    por Filler. Preserva o placeholder do AudioSuite (7f7f2a80, UMID nulo = tratado pelo MC)."""
    cn = type(c).__name__
    if cn == "SourceClip":
        h = c.mob_id.bytes_le.hex()
        if h not in present and "7f7f2a80" not in h:
            cnt[0] += 1
            mk = str(getattr(c, "media_kind", "sound")).lower()
            return _filler(f, getattr(c, "length", 0) or 0, "picture" if "pic" in mk else "sound")
        return c
    comps = getattr(c, "components", None)
    if isinstance(comps, list):
        for i, x in enumerate(comps):
            comps[i] = _fix_component(f, x, present, cnt)
    tks = getattr(c, "tracks", None)
    if isinstance(tks, list):
        for tk in tks:
            comp = getattr(tk, "component", None)
            if comp is not None:
                tk.component = _fix_component(f, comp, present, cnt)
    return c

def _fix_leaks(f):
    present = {m.mob_id.bytes_le.hex() for m in f.content.mobs}
    cnt = [0]
    for m in f.content.mobs:
        if getattr(m, "mob_type", None) != "CompositionMob":
            continue
        for tk in getattr(m, "tracks", []) or []:
            comp = getattr(tk, "component", None)
            if comp is not None:
                tk.component = _fix_component(f, comp, present, cnt)
    return cnt[0]

# ---------------------------------------------------------------------------------------------
# API (importável) — usada pelo sidecar/CLI. NADA roda no import; o CLI fica sob __main__.
# ---------------------------------------------------------------------------------------------
def build_templates_json(out_path=None):
    """Regenera o templates.json a partir dos GOLD (dev-only, precisa AVB_GOLD_DIR/gabaritos)."""
    out_path = out_path or TEMPLATES_JSON
    tpl = _capture_from_gold()
    # moldes que NÃO vêm dos gabaritos (ex.: EFF_TIMEWARP_POSICAO, do preset do MC no laboratório) ficam
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as fp:
            for k, v in json.load(fp).items():
                tpl.setdefault(k, v)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(tpl, fp)
    return tpl

def _rate_pair(rate, timeline_fps):
    """(num,den) da timeline: usa `rate` explícito, senão deriva de timeline_fps (mapa NTSC + Fraction)."""
    if rate:
        return tuple(rate)
    from fractions import Fraction
    known = {23.976: (24000, 1001), 29.97: (30000, 1001), 59.94: (60000, 1001),
             24.0: (24, 1), 25.0: (25, 1), 30.0: (30, 1), 50.0: (50, 1), 60.0: (60, 1)}
    if timeline_fps is not None:
        r = known.get(round(float(timeline_fps), 3))
        if r:
            return r
        fr = Fraction(float(timeline_fps)).limit_denominator(1001)
        return (fr.numerator, fr.denominator)
    return (30000, 1001)

def _emit(f, tracks, rate, comp_mobs, seqname, fix_leaks, inicio=None):
    """núcleo: seta ER global, autora a comp na bin aberta `f`, aplica leaks/uid. Retorna (comp, nleak)."""
    global ER
    ER, tc_fps, fmt_type, fmt_str = resolve_rate(*rate)
    tpl = capture_templates()
    c = build(f, seqname, tracks, tpl, tc_fps, fmt_type, fmt_str, comp_mobs, inicio=inicio)
    nleak = _fix_leaks(f) if fix_leaks else 0
    f.content.uid = random.getrandbits(63)
    return c, nleak

def build_avb(segments, timeline_fps, media_bin, out, seqname,
              aaf_path=None, remap=None, media_map=None, rate=None, fix_leaks=True, origem=None, mob_hex=None,
              inicio=None):
    """API do sidecar: autora a timeline .avb a partir dos SEGMENTOS já parseados do Relinker
    (vídeo+áudio resolvidos aos originais), sobre uma bin de mídia AMA-online `media_bin`.
      remap     : ponte {AAF_master_hex -> media_hex} (do media-bin builder).
      media_map : {arquivo:{name,mob_id}} p/ o fallback por nome (áudio via subclipe).
      aaf_path  : necessário p/ converter os mob_id URN dos masters -> hex (m2h).
      origem    : o NLE de onde veio a timeline ('avid'|'premiere'|'resolve'); None = perguntar ao AAF
                  (`origem.py`, pelo IdentificationList) e, sem AAF, tratar como Avid. Decide a rampa: curva
                  nativa só de Avid para Avid; de outro programa, quadro a quadro pelo gráfico de posição.
      mob_hex   : {mob_id do segmento -> media_hex} pronto, para quem NÃO vem de AAF (o .prproj: um master
                  offline por arquivo, `avb_export/do_prproj.py`); soma-se ao que o AAF der.
    Retorna dict com nome/len/tracks/leaks."""
    set_remap(remap)
    if origem is None and aaf_path:
        try:
            from origem import origem as _origem_do_arquivo
            origem = _origem_do_arquivo(aaf_path)["nle"]
        except Exception as e:                                    # noqa: BLE001 — sem origem = o comportamento antigo
            log.warning("origem do AAF não lida (%s): a rampa vai como do Avid", e)
    set_origem(None if origem in (None, "desconhecida") else origem, timeline_fps)
    m2h = {**(_urn2hex_from_aaf(aaf_path) if aaf_path else {}), **(mob_hex or {})}
    name2h = {}
    if media_map:
        for v in media_map.values():
            if isinstance(v, dict) and v.get("name"):
                name2h[_norm_name(v["name"])] = v["mob_id"]
    # {media_hex -> comprimento do master} p/ clampar o OUT dos clipes (leitura TOLERANTE: a bin tem PCMA)
    from .reader import topen as _topen
    ml = {}
    som: dict[str, list[int]] = {}                       # {media_hex -> índices das trilhas de SOM do master}
    with _topen(media_bin) as rf:
        for m in rf.content.mobs:
            if m.property_data.get("mob_type_id") != 2:
                continue
            L = 0
            for t in m.property_data.get("tracks") or []:
                seq = t.property_data.get("component")
                if seq is not None:
                    L = max(L, sum((c.property_data.get("length", 0) or 0)
                                   for c in (seq.property_data.get("components") or [])))
                    try:
                        if getattr(seq, "media_kind", None) == "sound":
                            som.setdefault(m.mob_id.bytes_le.hex(), []).append(int(t.property_data.get("index")))
                    except Exception:                    # noqa: BLE001 — sem o índice, o canal segue a regra do AAF
                        pass
            ml[m.mob_id.bytes_le.hex()] = L
    set_master_len(ml)
    # ⛔ O CANAL de quem não vem de AAF (o .prproj): o `source_slot_id` JÁ É o canal do arquivo (1…N) = a trilha de som do
    #   master. Sem isto o `_chan` aplicava a regra do AAF ("slot − 1", o slot 1 do AAF costuma ser vídeo/TC): o R do
    #   estéreo tocava o L e os 5 canais de um WAV saíam 1, 1, 2, 3, 4 (medido 2026-11-25, B03 a 23,976, MC 25.12 Mac).
    if origem == "premiere":
        for h in set((mob_hex or {}).values()):
            if h in som:
                CHANMAP[h] = {i: i for i in som[h]}
    # HANDLE offline: masters offline (chaves "offline:*" no media_map) foram autorados com folga nos
    # 2 lados (media_bin._offline_specs) -> desloca os clipes offline +H p/ centralizar e dar handle
    # às transições adjacentes (senão "Range specified for Dup" no MC). H = maior transição + margem.
    offline_hexes = {v.get("mob_id") for k, v in (media_map or {}).items()
                     if isinstance(k, str) and k.startswith("offline:") and isinstance(v, dict) and v.get("mob_id")}
    set_offline_handles(offline_hexes, offline_handle_frames(segments) if offline_hexes else 0)
    pic, snd = tracks_from_segments(segments, timeline_fps, m2h, name2h)
    tracks = pic + snd
    with avb.open(media_bin) as f:
        c, nleak = _emit(f, tracks, _rate_pair(rate, timeline_fps), {}, seqname, fix_leaks, inicio=inicio)
        f.write(out)
    return {"name": c.name, "length": c.length, "tracks": len(c.tracks),
            "picture_tracks": len(pic), "sound_tracks": len(snd), "leaks_filled": nleak, "output": out}

def build_avb_from_aaf(aaf_in, media_bin, out, seqname, use_relinker=None, fix_leaks=None):
    """Front-end CLI/regressão: lê o AAF (parser próprio + opcional front-end do Relinker) e autora.
    use_relinker/fix_leaks default vêm dos envs AVB_RELINKER_AAF / AVB_FIX_LEAKS (retrocompat)."""
    if use_relinker is None:
        use_relinker = os.environ.get("AVB_RELINKER_AAF") == "1"
    if fix_leaks is None:
        fix_leaks = os.environ.get("AVB_FIX_LEAKS") == "1"
    name, tracks, rate, comp_mobs = read_aaf(aaf_in)
    if use_relinker:
        pic, snd = tracks_from_relinker(aaf_in)
        tracks = pic + snd
        comp_mobs = {}
        print("front-end RELINKER: %d trilhas de vídeo + %d de áudio (resolvidas aos originais)" % (len(pic), len(snd)))
    with avb.open(media_bin) as f:
        c, nleak = _emit(f, tracks, rate, comp_mobs, seqname, fix_leaks)
        f.write(out)
    print("comp: %s len=%s tracks=%d | leaks->filler=%d -> %s" % (c.name, c.length, len(c.tracks), nleak, out))
    return {"name": c.name, "length": c.length, "tracks": len(c.tracks), "leaks_filled": nleak, "output": out}

if __name__ == "__main__":
    if _BUILD:
        _t = build_templates_json()
        print("templates.json gravado: %d templates -> %s" % (len(_t), TEMPLATES_JSON))
        print("  chaves:", list(_t.keys()))
        sys.exit(0)
    build_avb_from_aaf(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
