"""Os efeitos de ENQUADRAMENTO lidos direto da bin: 3D Warp, Resize, PIP, Pan&Scan e FrameFlex.

⭐ Medido em 2026-09-27 (banco `protocolos/avb/dados/efeitos-na-bin.json`): o uuid de cada
parâmetro no `param_list` do `TrackEffect` é o AUID do ParameterDef do AAF, e a pyavb traz o
dicionário (`avb.parameter_uuids.PARAMETER_UUIDS`). Logo os nomes são os mesmos do AAF
(`DVE_POS_X_U`, `AFX_SPATIAL_FRAMING_WID`…) e as fórmulas medidas no RELINKER valem sem
mudança: este módulo só LÊ; a conta é a do `aaf/parser.py` (`PARAMS_GEOMETRICOS`,
`frameflex_neutro`), e a saída é o MESMO `params` que o writer do DRT já consome.

Keyframes: o `value` solto do parâmetro NÃO é o valor do início do clipe (medido no E06: diz
58,3 e o primeiro ponto diz 100 no quadro 46). Enquanto o writer não anima, vale o valor do
PRIMEIRO QUADRO, e os pontos vão todos em `keyframes_avid` (a Carta é sem perdas).
"""

from __future__ import annotations

from avb.parameter_uuids import PARAMETER_UUIDS

from aaf.parser import PARAMS_GEOMETRICOS, _categorize_effect, frameflex_neutro

#: FrameFlex (AFX_SPATIAL_REFORMAT): o encaixe da mídia na timeline. RELINKER
#: `docs/effect-translation.md` §modos de REFORMAT (triplo-confirmado).
MODOS_REFORMAT = {1: "pillarbox", 2: "center_crop", 3: "keep_size", -1: "stretch"}


#: `ParamClip.interp_kind` → o nome no Media Composer. Um por PARÂMETRO, não por keyframe
#: (tabela da pyavb, `avb/components.py::INTERPOLATION_MAP`; banco `efeitos-na-bin.json`).
INTERPOLACAO = {2: "Shelf", 3: "Linear", 5: "Bezier", 6: "Spline"}


def _interpolacao(pd: dict) -> str:
    ct = pd.get("control_track")
    k = (getattr(ct, "property_data", {}) or {}).get("interp_kind")
    return INTERPOLACAO.get(k, "") if isinstance(k, int) else ""


def _pontos(pd: dict) -> list:
    """[(quadro no clipe, valor)] do `control_track` de um parâmetro animado."""
    ct = pd.get("control_track")
    fora = []
    for cp in (getattr(ct, "property_data", {}) or {}).get("control_points") or []:
        d = getattr(cp, "property_data", {}) or {}
        off = d.get("offset")
        try:
            quadro = off[0] / off[1] if isinstance(off, (list, tuple)) else float(off)
            fora.append((quadro, float(d.get("value"))))
        except (TypeError, ValueError, ZeroDivisionError, IndexError):
            continue
    return sorted(fora)


def parametros(te, interp: dict | None = None) -> dict:
    """{nome do AAF: (valor no primeiro quadro, pontos)} — `pontos` vazio se não anima.
    `interp`, se vier, recebe {nome: "Linear"|"Bezier"|…} dos parâmetros animados."""
    fora = {}
    for p in te.property_data.get("param_list") or []:
        pd = getattr(p, "property_data", {}) or {}
        nome = PARAMETER_UUIDS.get(str(pd.get("uuid")))
        if not nome:
            continue
        v = pd.get("value")
        pontos = _pontos(pd) if pd.get("control_track") else []
        if pontos:
            v = pontos[0][1]      # antes do 1º ponto o valor é constante (o do 1º ponto)
            if interp is not None:
                interp[nome] = _interpolacao(pd)
        if isinstance(v, (int, float)):
            fora[nome] = (float(v), pontos)
    return fora


def e_frameflex(eid: str) -> bool:
    return "SPATIAL_ADAPTER" in (eid or "").upper()


#: os interruptores de GRUPO do 3D Warp: posição/escala/rotação só valem com o grupo ligado (=1). Sem o interruptor o
#: MC IGNORA o valor (laboratório A01, 2026-10-11: DVE_POS_X/Y escritos sem DVE_POS_ENABLED_U não moveram a imagem;
#: com ele = 1, moveram). Um 3D Warp real traz o interruptor junto de cada grupo usado.
_GRUPOS_DVE = {"DVE_POS_": "DVE_POS_ENABLED_U", "DVE_SCALE_": "DVE_SCALE_ENABLED_U", "DVE_ROT_": "DVE_ROT_ENABLED_U"}


#: os padrões dos efeitos que o MC não grava na bin e que MUDAM a imagem (medidos no laboratório)
_PADROES = {"EFF2_BLEND_PIP": {"AFX_SCALE_X_U": 50.0, "AFX_SCALE_Y_U": 50.0}}


def _grupo_desligado(nome: str, val) -> bool:
    for prefixo, chave in _GRUPOS_DVE.items():
        if nome.startswith(prefixo) and nome != chave:
            return not val(chave)
    return False


def e_pan_scan(eid: str) -> bool:
    e = (eid or "").upper().replace("_", "").replace("&", "")
    return "PANSCAN" in e or "PANANDSCAN" in e


def enquadramento(te) -> tuple[dict | None, str | None, list[str]]:
    """(efeito para `Segment.effects` ou None, modo de reformat ou None, avisos).

    O efeito sai no formato do parser de AAF: `category: "geometric"`, `reproducible`,
    `params` com `pos_*` em milésimos, `scale_*` em fator, `rot_z` em graus, `crop_*` e
    `opacity`. Um FrameFlex só de REFORMAT (sem enquadramento mudado) não vira efeito: o
    encaixe é outra coisa, que volta no modo (`pillarbox`, `stretch`…)."""
    eid = str(getattr(te, "effect_id", "") or "")
    categoria, reproduzivel = _categorize_effect(eid)
    if e_frameflex(eid):
        categoria, reproduzivel = "geometric", True
    if categoria != "geometric":
        return None, None, []
    interps: dict = {}
    ps = parametros(te, interps)
    val = lambda n: ps[n][0] if n in ps else None  # noqa: E731
    animados = sorted(n for n, (_v, pts) in ps.items() if pts)
    avisos: list[str] = []
    modo = None

    if e_frameflex(eid):
        r = val("AFX_SPATIAL_REFORMAT")
        modo = MODOS_REFORMAT.get(int(round(r))) if r is not None else None
        # O escalar AFX_SPATIAL_FRAMING_WID só existe quando o editor mexeu no FrameFlex; com
        # tudo em 100 % e posição 0, é identidade — não se escreve nada (medido no E06:
        # "MUDANDO ATRIBUTOS" tem o escalar em 100 nos clipes que não animam).
        if val("AFX_SPATIAL_FRAMING_WID") is None:
            return None, modo, []
        # ⛔ FrameFlex ANIMADO: não se escreve. Medido no E06 (2026-09-27): com a proporção
        # travada, a bin guarda a altura com pontos (56,2 → 100) e a largura com UM ponto no
        # quadro 46 e um `value` solto de 58,3 — o acoplamento largura↔altura não está
        # decifrado, e a conta daria zoom diferente em X e Y (imagem distorcida). Um zoom
        # errado é pior que nenhum: o colorista confia no que vê.
        if any(n.startswith(("AFX_SPATIAL_FRAMING_", "DVE_ROT_Z")) for n in animados):
            # Vai na Carta como NÃO reproduzível (o writer do DRT só usa os reproduzíveis).
            guardado = {"name": eid, "category": "geometric", "reproducible": False,
                        "params": {"animated": True,
                                   "keyframes_avid": {n: ps[n][1] for n in animados},
                                   "interp_avid": interps}}
            return guardado, modo, ["FrameFlex animado: o enquadramento NÃO foi traduzido "
                                    "(a animação fica na Carta) — ajuste no Resolve"]
        wid, hei = val("AFX_SPATIAL_FRAMING_WID"), val("AFX_SPATIAL_FRAMING_HEI")
        px, py = val("AFX_SPATIAL_FRAMING_POSX"), val("AFX_SPATIAL_FRAMING_POSY")
        rot = val("DVE_ROT_Z_U")
        if (wid or 100) == 100 and (hei or wid or 100) == 100 and not px and not py and not rot:
            return None, modo, []
        params = frameflex_neutro(wid, hei, px, py, rot)
    else:
        params = {}
        for nome, chave in PARAMS_GEOMETRICOS.items():
            v = val(nome)
            if v is not None and not _grupo_desligado(nome, val):
                params[chave] = v / 100.0 if chave.startswith("scale") else v
        # ⛔ No esquema AFX (Resize, Picture-in-Picture) +Y DESCE; no DVE (3D Warp) +Y SOBE, que é o modelo neutro
        # (medido no laboratório A01, 2026-10-11: Y +50 → 54 px para baixo no Resize e no PIP, para cima no 3D Warp).
        # O padrão que o MC NÃO grava (a bin só guarda o que saiu do padrão): o Picture-in-Picture sem escala é 50 %
        # (laboratório A01, 2026-10-11: PIP só com posição renderizou 960×542 no MC).
        for nome, chave in PARAMS_GEOMETRICOS.items():
            if chave not in params and nome in _PADROES.get(eid, {}):
                params[chave] = _PADROES[eid][nome] / 100.0 if chave.startswith("scale") else _PADROES[eid][nome]
        if "pos_y" in params and val("AFX_POS_Y_U") is not None and not e_pan_scan(eid):
            params["pos_y"] = -params["pos_y"]
        if e_pan_scan(eid):
            for k in ("pos_x", "pos_y"):          # move a JANELA (RELINKER: 150 → −0,15)
                if k in params:
                    params[k] = -params[k]

    if animados:
        params["animated"] = True
        params["keyframes_avid"] = {n: ps[n][1] for n in animados}
        params["interp_avid"] = interps
        avisos.append("efeito animado: veio o valor do primeiro quadro (a animação fica na Carta)")
    return ({"name": eid, "category": "geometric", "reproducible": reproduzivel,
             "params": params}, modo, avisos)


def informativo(te) -> dict:
    """Os números de um efeito que a nota precisa contar (o `params` do efeito na Carta). Hoje: o
    estabilizador — um 3D Warp rastreado. O Auto-Zoom (104,28 % na PRODA) diz quanto a imagem foi
    cortada, e o tracker (`trackman`), quando é o modo medido, vai em `estabilizacao`: a
    estabilização chega PRONTA ao Resolve (`motor/estabilizacao.py`; autor, 2026-10-24)."""
    eid = str(getattr(te, "effect_id", "") or "").upper()
    if eid == "EFF2_RGB_COLOR_CORRECTION":
        return cor_mc(te)
    if "STABIL" not in eid:
        return {}
    ps = parametros(te)
    zoom = ps.get("DVE_SCALE_X_U", (None, []))[0]
    fora = {"zoom_pct": round(zoom, 2) if zoom else None,
            "auto_zoom": bool(ps.get("Auto-Zoom", (0, []))[0]),
            "rastreado": bool(ps.get("DVE_POS_TRACK_U", (0, []))[0])}
    from estabilizacao import da_bin
    try:
        dados = da_bin(te, ps)
    except Exception:  # noqa: BLE001 — o tracker que não se lê fica a nota de antes
        dados = None
    if dados:
        fora["estabilizacao"] = dados
    return fora


def cor_mc(te) -> dict:
    """O Color Correction da bin → `{"cor_mc": {sat, curva}}` (traduzível: os 2 nós do Resolve, `drp/cor_mc.py`) ou
    `{"cor_mc_nao": [...]}`; o mesmo `ler_cc` do AAF. O blob da curva é um `CFUserParam` (`.data` = os 256 bytes)."""
    from drp.cor_mc import ler_cc
    brutos = {}
    for p in te.property_data.get("param_list") or []:
        pd = getattr(p, "property_data", {}) or {}
        nome = PARAMETER_UUIDS.get(str(pd.get("uuid")))
        if not nome:
            continue
        v = pd.get("value")
        dados = getattr(v, "data", None)
        brutos[nome] = (None if dados is not None else v, bool(pd.get("control_track")),
                        bytes(dados) if dados is not None else None)
    try:
        cc = ler_cc(brutos)
    except Exception:  # noqa: BLE001 — o CC que não se lê fica a nota de antes
        return {}
    if not cc["nao"] and (cc["sat"] is not None or cc["curva"]):
        return {"cor_mc": {"sat": cc["sat"], "curva": [[round(x, 6), round(y, 6)] for x, y in cc["curva"] or []] or None}}
    return {"cor_mc_nao": cc["nao"]} if cc["nao"] else {}


def nome_do_plugin(te) -> str:
    """O nome que um efeito AVX declara na bin (`_EFFECT_PLUGIN_NAME`): os plugins têm um GUID
    como effect_id (ex.: 169317AB… = "Timecode Burn-In"), e o nome é o que o editor reconhece."""
    try:
        return str(dict(te.property_data.get("attributes") or {}).get("_EFFECT_PLUGIN_NAME") or "")
    except Exception:  # noqa: BLE001 — atributo ilegível: sem nome, segue o id
        return ""
