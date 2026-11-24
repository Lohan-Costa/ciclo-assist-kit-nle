"""A PÁGINA COLOR do Premiere 2027 (27.0.0) no `.prproj` — ler a árvore e levar o que se sabe traduzir.

A página Color NÃO é a Lumetri: ela grava na cadeia do clipe um componente `CompoundComponent` (classe
`250b3605-8b7a-4687-bf33-f54e312a510e`) SEM `MatchName`, dono de uma árvore de outros (`ComponentOwner/Components` → a
`VideoComponentChain` de dentro). Antes desta peça o leitor via um componente de `MatchName` vazio — que está no
`_NAO_EFEITO` — e a grade inteira passava CALADA (banco `protocolos/prproj/estruturas.md` §Premiere 2027).

    65537 contêiner da página (ID 3)
      65541 nível Clip              → 65538 camada Adjustment ("Adjust 1") → Color And Contrast, Color Shift,
      65542 grupo ("Group 01")        (a CÓPIA da camada de cada membro)      65539 Detail → Color Texture, Unsharp Mask2

O que vai: o Color And Contrast GLOBAL (Exposure, Contrast/Pivot, Black, Temperature/Tint, Saturation) como uma etapa da
LUT do nó do clipe (`leitura.lut_composta`), pelo MODELO EXATO do kernel medido no laboratório
(`laboratorio-de-midia/lab/bancadas/premiere_pagina_cor.py::color_and_contrast`, carta B24, 29 casos, 0,09–1,25 código
de média; Temperature/Tint pela lei Bradford, 0,19 código) — aqui em Python puro, conferido contra aquele. O que não vai
(as zonas, a roda Balance, Color Shift, Detail, módulo de Style desconhecido, keyframes) vira AVISO com o nome.

⚠️ O espaço de trabalho medido é só o da sequência Rec. 709 (linear = v², v = (código − 16)/219 — o domínio 0–1 da LUT
do Resolve num clipe de vídeo); HLG/PQ/ACEScct `pendente`.
"""
from __future__ import annotations

import hashlib
import math

COMPOUND = "250b3605-8b7a-4687-bf33-f54e312a510e"
#: o papel de cada `CompoundComponentType` (o que foi visto no 27.0.0; outro número = camada desconhecida → aviso)
CONTEINER, NIVEL_CLIP, CAMADA_AJUSTE, DETAIL, GRUPO = 65537, 65541, 65538, 65539, 65542
#: o nível SEQUENCE (pilotado, 27.0.0, 2026-11-20): Sequence → VideoTrackGroup › ComponentOwner/Components → 65543 (o
#: contêiner da sequência) → 65540 "Sequence Style 1" + 65538 "Sequence Adjust 1"… Nada disso existe no arquivo até o 1º "+".
CONTEINER_SEQ, ESTILO = 65543, 65540

#: Color And Contrast: os controles GLOBAIS por `ParameterID` (o nome se repete nas zonas) e o padrão
_GLOBAL = {"2": ("Exposure", 0.0), "3": ("Saturation", 1.0), "4": ("Contrast", 1.0), "5": ("Pivot", -3.0),
           "6": ("Black", 0.0), "7": ("Temperature", 0.0), "8": ("Tint", 0.0)}
#: o blob da roda Balance neutra (o mesmo nas 9: a global, ID 9, e a de cada zona) — md5 do base64
_BALANCE_NEUTRA = "038cbae3df2ac596e2fe7b72c2616fd3"
#: as 8 zonas do Color And Contrast: o 1º ParameterID de cada bloco de 12 (o nome vem do parâmetro seguinte)
_ZONAS = range(10, 107, 12)
#: Color Shift neutro (medido em 36 camadas recém-gravadas, 2026-11-20): os valores ou o md5 dos blobs. ⚠️ SEM o param 1
#: (`inferido`: estado da interface — muda com o gesto que não grada e na camada nova do "+", com as curvas 4/9/14 e as
#: chaves 2/7/12 neutras; os floats dele parecem o matiz da amostra selecionada) nem o 18.
_COLOR_SHIFT_NEUTRO = {"2": "false", "4": "md5:c56e40cba097fe411b72a8d2be817b66",
                       "5": "md5:65844d8870b3860960e31b4264da8fe0", "7": "false", "9": "md5:e2a4ff40f9e159b0be15dc429068585b",
                       "10": "md5:65844d8870b3860960e31b4264da8fe0", "12": "false",
                       "14": "md5:d9c434405e249ad36e27e781378953ae", "15": "md5:65844d8870b3860960e31b4264da8fe0",
                       "17": "md5:c10b0fdd8ebdc939d9abb4b256a8a458"}
_TEXTURE_NEUTRO = {"2": "0.", "4": "0.", "5": "0.", "6": "0.", "7": "0.", "8": "0."}
_NITIDEZ_NEUTRO = {"1": "0."}
#: o módulo "Contrast Kit" de uma Style (27.0.0, 2026-11-20): `AE.ADBE Contrast`, cartão Compression/Range/Highlights;
#: no arquivo Contrast, Midpoint, Range, Pivot, Rolloff, Highlight Adjust — o neutro recém-escolhido (a escala `pendente`)
_CONTRAST_KIT_NEUTRO = {"1": "0.", "2": "0.5", "3": "1.", "4": "0.5", "5": "0.", "6": "0."}
#: os outros módulos da Style que nascem NEUTROS (escolhidos todos de uma vez pelo autor, 27.0.0, `LAB COR 27 STYLE C`):
#: o MatchName → (o nome no aviso, o neutro recém-escolhido). ⚠️ O Film Color (`AE.ADBE Color Film`, Negative/Print 0
#: com força 1) e o Vignette (`AE.Impact_Vignette_FX`, Vignette 100) já mudam a imagem ao entrar: SEMPRE avisam.
#: o Film Color (`AE.ADBE Color Film`, módulo da Style; 27.0.0, 2026-11-20): o kernel `ColorFilmKernel` MODIFICA a LUT
#: do estoque Negativo_Print, que vai EMBUTIDA no projeto (param 18, ITX3 21³ = a `.cube` de `LUTs\FilmEmulation`,
#: conferida pelo Frida byte a byte; param 19 = o nome). Com os controles abaixo no padrão o kernel devolve o estoque
#: e o render É a LUT no sinal (`lab/premiere27_film_color.py`: 0,29 código). Fora do padrão = aviso (o kernel `pendente`).
_FILM_PADRAO = {"3": "1.", "4": "0.", "6": "1.", "7": "0.", "8": "md5:" + _BALANCE_NEUTRA, "9": "1.", "10": "0.",
                "11": "md5:" + _BALANCE_NEUTRA, "12": "0.", "13": "0.", "14": "0.", "16": "0.", "17": "0."}
#: a VIGNETTE (`AE.Impact_Vignette_FX`, plugin FilmImpact nativo — sem a fonte do shader no binário) na forma PADRÃO
#: (os params por ParameterID, 27.0.0) ≈ uma janela circular INVERTIDA no Resolve com Gain 0 (ajustada ao render do
#: quadro branco, `laboratorio-de-midia/lab/premiere27_vignette.py` + `resolve_janela.py`: 1,08 código de média onde a
#: vinheta age, p95 3, máx 10 no canto). Medidas em px de uma sequência 1920×1080 (quem escreve escala pela altura).
#: Fora do padrão = aviso: a lei de cada controle `pendente` (Vignette/Master 50 já mudam a FORMA, não só a força).
_VINHETA_PADRAO = {"2": "100.", "3": "80.", "4": "80.", "5": "100.", "6": "0.", "7": "0.5:0.5", "8": "100.",
                   "9": "50.", "14": "100.", "12": "100.", "16": "18374686479671623680"}
VINHETA_JANELA = {"raio_px": 1136.0, "borda_px": 360.0, "gain": 0.0}
_MODULOS_NEUTROS = {
    "AE.ADBE Contrast": ("Contrast Kit", _CONTRAST_KIT_NEUTRO),
    "AE.ADBE Flare": ("Flare", {"1": "0."}),
    "AE.ADBE Midtones": ("Midtones", {"1": "0."}),
    "AE.ADBE Variable Vibrance": ("Variable Vibrance", {"1": "0."}),
}


def eh_pagina_cor(comp) -> bool:
    return comp.tag == "CompoundComponent"


def _params(proj, comp) -> dict[str, tuple[str | None, bool]]:
    """ParameterID → (valor inicial, animado)."""
    out = {}
    for prm in proj.refs(comp, "Param"):
        sk = proj.campo(prm, "StartKeyframe")
        v = sk.split(",")[1] if sk and "," in sk else proj.valor_inicial(prm)
        out[proj.campo(prm, "ParameterID") or ""] = (v, bool(proj.campo(prm, "Keyframes")))
    return out


def _fora_do_padrao(v: str | None, padrao: str) -> bool:
    if v is None:
        return False
    if padrao.startswith("md5:"):
        return hashlib.md5(v.encode()).hexdigest() != padrao[4:]
    try:
        return abs(float(v) - float(padrao)) > 1e-9
    except ValueError:
        return v.strip().lower() != padrao


def _num(v, padrao: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return padrao


def _color_and_contrast(proj, comp, nao: list[str]) -> dict | None:
    """Os controles globais fora do padrão (`{nome: valor}`, None se neutro) + o que não vai em `nao`."""
    prm = _params(proj, comp)
    if any(a for _, a in prm.values()):
        nao.append("página Color: controle animado (usado o valor inicial)")
    g = {}
    for pid, (nome, padrao) in _GLOBAL.items():
        v = _num(prm.get(pid, (None, False))[0], padrao)
        if abs(v - padrao) > 1e-9:
            g[nome] = v
    # o Pivot só age com o Contrast fora de 1 — e a camada nova do "+" da interface nasce com Pivot 0 (a 1ª, com −3;
    # Premiere 27.0.0, pilotado 2026-11-20): sem isto ela viraria uma etapa de LUT neutra e um aviso falso
    if "Contrast" not in g:
        g.pop("Pivot", None)
    if _fora_do_padrao(prm.get("9", (None, False))[0], "md5:" + _BALANCE_NEUTRA):
        nao.append("página Color: Color Balance (roda)")
    for s in _ZONAS:
        valores = [(s + 4, "0."), (s + 5, "1."), (s + 9, "0."), (s + 10, "0."), (s + 11, "md5:" + _BALANCE_NEUTRA)]
        if any(_fora_do_padrao(prm.get(str(i), (None, False))[0], p) for i, p in valores):
            nome = next((proj.campo(x, "Name") for x in proj.refs(comp, "Param")
                         if proj.campo(x, "ParameterID") == str(s + 1)), None) or f"zona {s}"
            nao.append(f"página Color: zona {nome}")
    return g or None


def _neutro(proj, comp, tabela: dict) -> bool:
    prm = _params(proj, comp)
    return not any(_fora_do_padrao(prm.get(pid, (None, False))[0], p) for pid, p in tabela.items())


def ler_pagina_cor(proj, comp) -> dict:
    """A grade da página Color de UM componente da cadeia do clipe: `{"pagina_cor": [controles globais de cada camada,
    em ordem], "nao": [o que não vai]}`. A ordem é a do contêiner (Clip → grupo), a de quem grava."""
    etapas: list[dict] = []
    nao: list[str] = []
    vinhetas: list[dict] = []

    def descer(no, prof=0):
        if prof > 8 or proj.campo(no, "Bypass") == "true":
            return
        if no.tag == "CompoundComponent":
            tipo = int(proj.campo(no, "CompoundComponentType") or 0)
            # a Style (65540) é um CONTÊINER de efeitos comuns: escolher um módulo ("Color / Contrast"…) grava nela o
            # mesmo `AE.ADBE Color And Contrast` da camada Adjustment, e ele RENDERIZA como ela, na ordem do arquivo
            # (27.0.0, `lab/premiere27_style.py`: 0,09 código × 22,9 na inversa). Vazia = a "Sequence Style 1" que a
            # interface sempre mostra. Módulo de efeito desconhecido (Film Color, Flare…) cai no aviso pelo nome.
            if tipo not in (CONTEINER, CONTEINER_SEQ, NIVEL_CLIP, CAMADA_AJUSTE, DETAIL, GRUPO, ESTILO):
                nao.append(f"página Color: camada {proj.campo(no, 'InstanceName') or tipo} (tipo desconhecido)")
                return
            dono = proj.ref(no, "Components")
            for filho in (proj.refs(dono, "Component") if dono is not None else []):
                descer(filho, prof + 1)
            return
        mn = proj.campo(no, "MatchName")
        if mn == "AE.ADBE Color And Contrast":
            g = _color_and_contrast(proj, no, nao)
            if g:
                etapas.append(g)
        elif mn == "AE.ADBE LUT Transform":
            # a camada LUT ("Add Clip/Sequence LUT", pilotado no 27, 2026-11-20): um efeito comum, a tabela INTEIRA no
            # "LUT Blob" (ITX3, o formato do look da Lumetri) + Intensity → uma etapa da LUT do nó, na ordem do arquivo
            prm = _params(proj, no)
            blob, inten = prm.get("3", (None, False))[0], _num(prm.get("7", (None, False))[0], 100.0)
            if blob and blob.startswith("SVRYM"):           # "ITX3" em base64
                etapas.append({"lut": {"itx3_b64": blob, "intensidade": inten}})
                if prm.get("6", ("1", False))[0] not in ("1", None):
                    nao.append("página Color: LUT com Data Range diferente do medido (conferir)")
            elif prm.get("1", ("0", False))[0] not in ("0", None):
                nao.append("página Color: LUT (tabela ilegível)")
        elif mn == "AE.ADBE Color Shift":
            if not _neutro(proj, no, _COLOR_SHIFT_NEUTRO):
                nao.append("página Color: Color Shift")
        elif mn == "AE.ADBE Color Texture":
            if not _neutro(proj, no, _TEXTURE_NEUTRO):
                nao.append("página Color: Texture")
        elif mn == "AE.ADBE Color Film":
            prm = _params(proj, no)
            blob = prm.get("18", (None, False))[0]
            nome = prm.get("19", (None, False))[0]
            if not (blob and blob.startswith("SVRYM")):
                nao.append("página Color: Film Color (estoque ilegível)")
            elif not _neutro(proj, no, _FILM_PADRAO):
                nao.append("página Color: Film Color com ajustes além do estoque")
            else:
                etapas.append({"lut": {"itx3_b64": blob, "intensidade": 100.0}})
                if any(a for _, a in prm.values()):
                    nao.append("página Color: Film Color animado (usado o valor inicial)")
        elif mn == "AE.Impact_Vignette_FX":
            prm = _params(proj, no)
            if any(a for _, a in prm.values()):
                nao.append("página Color: Vignette animada (não traduzida)")
            elif not _neutro(proj, no, _VINHETA_PADRAO):
                nao.append("página Color: Vignette com ajustes (só a padrão se traduz)")
            else:
                vinhetas.append(dict(VINHETA_JANELA))
                if _fora_do_padrao(prm.get("10", (None, False))[0], "0."):
                    nao.append("página Color: Vignette — o desfoque da borda (Softness)")
                if _fora_do_padrao(prm.get("11", (None, False))[0], "0."):
                    nao.append("página Color: Vignette — a aberração cromática")
        elif mn in _MODULOS_NEUTROS:
            nome, tabela = _MODULOS_NEUTROS[mn]
            if not _neutro(proj, no, tabela):
                nao.append(f"página Color: {nome}")
        elif mn == "AE.ADBE Unsharp Mask2":
            if not _neutro(proj, no, _NITIDEZ_NEUTRO):
                nao.append("página Color: Sharpness")
        else:
            nao.append(f"página Color: {proj.campo(no, 'DisplayName') or mn or 'efeito desconhecido'}")

    descer(comp)
    return {"pagina_cor": etapas, "nao": list(dict.fromkeys(nao)), "vinheta": vinhetas}


# ── o MODELO do Color And Contrast (o kernel do Premiere 27.0.0), em Python puro ─────────────────────────────────────
_W709 = (0.2126, 0.7152, 0.0722)
_M709_XYZ = ((0.4124, 0.3576, 0.1805), (0.2126, 0.7152, 0.0722), (0.0193, 0.1192, 0.9505))
_BRADFORD = ((0.8951, 0.2664, -0.1614), (-0.7502, 1.7135, 0.0367), (0.0389, -0.0685, 1.0296))


def _mm(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _mv(a, v):
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))


def _inv(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return ((( e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
            ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
            ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det))


def _bradford_d65_para(w_xyz):
    d65 = _mv(_M709_XYZ, (1.0, 1.0, 1.0))
    bw, bd = _mv(_BRADFORD, w_xyz), _mv(_BRADFORD, d65)
    diag = tuple(tuple((bw[i] / bd[i]) if i == j else 0.0 for j in range(3)) for i in range(3))
    return _mm(_mm(_mm(_mm(_inv(_M709_XYZ), _inv(_BRADFORD)), diag), _BRADFORD), _M709_XYZ)


def _branco_temperatura(t: float):
    cct = 6487.6 * 2 ** (-0.0083875 * t) if t >= 0 else 6453.3 * 2 ** (-0.022085 * t)
    if cct <= 7000:
        x = -4.6070e9 / cct ** 3 + 2.9678e6 / cct ** 2 + 0.09911e3 / cct + 0.244063
    else:
        x = -2.0064e9 / cct ** 3 + 1.9018e6 / cct ** 2 + 0.24748e3 / cct + 0.237040
    y = -3.0 * x * x + 2.870 * x - 0.275
    return (x / y, 1.0, (1 - x - y) / y)


def _branco_tint(ti: float):
    d65 = _mv(_M709_XYZ, (1.0, 1.0, 1.0))
    den = d65[0] + 15 * d65[1] + 3 * d65[2]
    u, v = 4 * d65[0] / den, 6 * d65[1] / den
    passo = 0.001155 if ti >= 0 else 0.000681
    a = math.radians(-17.56)
    u, v = u + ti * passo * math.cos(a), v + ti * passo * math.sin(a)
    x, y = 3 * u / (2 * u - 8 * v + 4), 2 * v / (2 * u - 8 * v + 4)
    return (x / y, 1.0, (1 - x - y) / y)


def matriz_temperatura_tint(temperatura: float = 0.0, tint: float = 0.0):
    """A `mColorShiftMatrix` que o Premiere 27 manda ao kernel (3×3, Rec. 709 linear): Bradford D65 → o branco no locus
    da luz do dia (Temperature) × a reta no uv (Tint)."""
    m = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    if temperatura:
        m = _mm(_bradford_d65_para(_branco_temperatura(temperatura)), m)
    if tint:
        m = _mm(_bradford_d65_para(_branco_tint(tint)), m)
    return m


def _do_host(nome: str, valor: float) -> float:
    if nome == "Contrast" and valor > 1:
        return 3 * valor - 2
    if nome == "Saturation" and valor > 1:
        return 1 + 1.75 * (valor - 1)
    return valor


def funcao(p: dict):
    """f(r, g, b) do Color And Contrast global com os controles `p` — R'G'B' de vídeo 0–1 → R'G'B' (sem corte; quem
    escreve a LUT corta). Ordem do kernel: Exposure → Contrast/Pivot → Black → matriz de cor → Saturation."""
    ganho = 2 ** p.get("Exposure", 0.0)
    c, piv = _do_host("Contrast", p.get("Contrast", 1.0)), p.get("Pivot", -3.0)
    preto = p.get("Black", 0.0)
    m = matriz_temperatura_tint(p.get("Temperature", 0.0), p.get("Tint", 0.0)) \
        if (p.get("Temperature") or p.get("Tint")) else None
    s = _do_host("Saturation", p.get("Saturation", 1.0))

    def f(r, g, b):
        x = [math.copysign(v * v, v) * ganho for v in (r, g, b)]
        if c != 1:
            k = max(abs(sum(w * v for w, v in zip(_W709, x)) / (0.18 * 2 ** piv)), 1e-8) ** (c - 1)
            x = [v * k for v in x]
        if preto:
            mx, rol = max(x), 0.18
            if mx <= 0:
                sl = 0.5
            elif mx <= rol / 2:
                sl = 1 - 0.5 * (mx * 2 / rol) ** 2
            elif mx <= rol:
                sl = 0.5 * (1 - (mx * 2 / rol - 1)) ** 2
            else:
                sl = 0.0
            off = 0.01 * preto * sl
            bs = 0.5 * min(max(mx, 0.0) / 0.01, 1.0)
            x = [v + off for v in x] if mx == 0 else [bs * v * (off + mx) / mx + (1 - bs) * (off + v) for v in x]
        if m is not None:
            x = list(_mv(m, x))
        if s != 1:
            y = sum(w * abs(v) for w, v in zip(_W709, x))
            meio = (max(x) + min(x)) / 2
            o = [v * s + (1 - s) * meio for v in x]
            yo = sum(w * abs(v) for w, v in zip(_W709, o))
            k = min(max(max(1e-8, y) / max(1e-8, yo), 1 / 1.5), 2.5)
            x = [v * k for v in o]
        return tuple(math.copysign(abs(v) ** 0.5, v) for v in x)
    return f
