"""Uma sequência do Premiere → segmentos no modelo neutro do motor (`Segment.to_dict()`).

Desce de cada plano da timeline até o ARQUIVO, atravessando sequência aninhada e multicam (o
take da 1ª leva do PRODUCAO_B é uma multicam de UMA câmera usada como subclipe), e compõe pelo
caminho as três coisas que cada camada pode mudar:

  • tempo      — `InPoint` + (t − `Start`) × `PlaybackSpeed`, camada por camada;
  • velocidade — o produto das `PlaybackSpeed`;
  • enquadramento — o Motion do plano composto com o Motion de dentro do take.

Fatos do formato (banco `protocolos/prproj/relink-e-geometria.md`):
  §1  `Scale` é relativo aos PIXELS NATIVOS da fonte (100 = 1:1), salvo
  §10.1 `ScaleToFramePolicy=1` no `VideoClip`: "Scale to Frame Size" → 100 = encaixada no quadro;
  §10.2 `PlaybackSpeed` no `<Clip>` do `VideoClip` (ausente = 1);
  `Position` normalizada no quadro do CONTÊINER (0.5:0.5 = centro, +Y para baixo);
  `Anchor Point` normalizado no quadro da FONTE.

Saída da geometria no modelo neutro do writer (`drp/writer.py::_effect_filters_ba_for`): zoom
em fator RELATIVO AO ENCAIXE (o clipe vai com Scaling = Fit), posição em milésimos da fração do
quadro com +Y para CIMA, rotação em graus.
"""
from __future__ import annotations

import math
import re
import struct

from .mascara import ler_mascaras, para_fonte_de_dentro, receita
from .pagina_cor import eh_pagina_cor, ler_pagina_cor
from .pagina_cor import funcao as _funcao_pagina_cor
from .projeto import TPS, Obj, Projeto

#: Componentes que não são efeito de imagem (configuração de fonte, intrínsecos). O Text e o
#: Graphic Group (Vector Motion) são o próprio título: viram o bloco `titulo`, não aviso.
_NAO_EFEITO = {"AE.ADBE Motion", "AE.ADBE Opacity", "AE.ADBE MPEG.SourceSettings",
               "AE.ADBE Text", "AE.ADBE Graphic Group", None}


def _texto_do_blob(b64: str) -> tuple[str | None, str | None]:
    """(texto, fonte PostScript) do `Source Text` do Premiere (FlatBuffers em base64).

    `inferido` (PRODUCAO_B, Premiere 26.0.2, 4 títulos): as strings vêm com prefixo u32 LE de
    tamanho; a fonte é a que tem forma PostScript (`Optima-Regular`) e o texto é a ÚLTIMA."""
    import base64
    import struct
    try:
        b = base64.b64decode(b64)
    except ValueError:
        return None, None
    achadas, i = [], 0
    while i + 4 <= len(b):
        n = struct.unpack("<I", b[i:i + 4])[0]
        if 1 <= n <= 4000 and i + 4 + n <= len(b):
            s = b[i + 4:i + 4 + n]
            try:
                txt = s.decode("utf-8")
                # ⚠️ A QUEBRA DE LINHA vale (o Premiere grava `\r`): a claquete do rolo do PRODUCAO_B
                # é "PRODUCAO-B\rRolo Único", e o `isprintable` cru a recusava — sobrava o nome da fonte
                # ("Monaco") como texto (medido 2026-10-04).
                limpo = txt.replace("\r\n", "\n").replace("\r", "\n")
                if limpo.replace("\n", "").replace("\t", " ").isprintable() \
                        and any(c.isalpha() for c in limpo):
                    achadas.append(limpo)
                    i += 4 + n
                    continue
            except UnicodeDecodeError:
                pass
        i += 1
    # A fonte é o nome PostScript: uma palavra só, com ou sem hífen (`Optima-Regular`, `Monaco`), e
    # vem ANTES do texto no blob. O texto é a última das outras.
    fonte = next((s for s in achadas[:-1] if re.fullmatch(r"[A-Za-z0-9][\w.-]*", s)), None)
    textos = [s for s in achadas if s != fonte]
    return (textos[-1] if textos else None), fonte
def _corpo_do_blob(b64: str) -> float | None:
    """O corpo (px) do 1º trecho do `Source Text`, ou `None` = o padrão (100).

    O blob é FlatBuffers depois de 12 bytes de cabeçalho: raiz → tabela do documento → campo 0
    (vetor de trechos) → trecho[0] campo 1 (estilo) → campo 1 = float32. `inferido` (PRODUCAO_B,
    Premiere 26.0.2, 2026-10-04): 160 nos títulos em ArialMT; AUSENTE nos de corpo padrão (o
    FlatBuffers não grava o valor padrão), e esses medem 100 px na imagem."""
    import base64
    try:
        b = base64.b64decode(b64)[12:]

        def u32(o):
            return struct.unpack_from("<I", b, o)[0]

        def campo(t, i):
            v = t - struct.unpack_from("<i", b, t)[0]
            n = (struct.unpack_from("<H", b, v)[0] - 4) // 2
            return t + struct.unpack_from("<H", b, v + 4 + 2 * i)[0] if i < n else t
        raiz = u32(0)
        doc = campo(raiz, 0)
        doc += u32(doc)
        vec = campo(doc, 0)
        vec += u32(vec)
        trecho = vec + 4 + u32(vec + 4)
        estilo = campo(trecho, 1)
        if estilo == trecho:
            return None
        estilo += u32(estilo)
        o = campo(estilo, 1)
        if o == estilo:
            return None
        v = struct.unpack_from("<f", b, o)[0]
        return v if 1.0 <= v <= 2000.0 else None
    except (ValueError, struct.error, IndexError):
        return None


#: Justificação do parágrafo no `Source Text` → o alinhamento do Text do Resolve.
_JUSTIFICA = {0: "esquerda", 1: "direita", 2: "centro"}


def _alinhamento_do_blob(b64: str) -> str:
    """O alinhamento do parágrafo do `Source Text`: o campo 4 da tabela do documento (o FlatBuffers de `_corpo_do_blob`),
    ausente = 0. MEDIDO (2026-10-10, Premiere 23.2, projeto do autor com 3 títulos iguais — esquerda, centro, direita —
    `03 CASOS/TITULOS/T_ALINHAMENTO_PREMIERE23`): ausente / 2 / 1, o enum de justificação do motor de texto da Adobe
    (0 esquerda, 1 direita, 2 centro). Os campos 26 e 43 repetem a informação dentro de valores maiores. Outro valor
    (justificado…) ou blob ilegível → "esquerda", como antes."""
    import base64
    try:
        b = base64.b64decode(b64)[12:]

        def campo(t_, i):
            v = t_ - struct.unpack_from("<i", b, t_)[0]
            n = (struct.unpack_from("<H", b, v)[0] - 4) // 2
            return t_ + struct.unpack_from("<H", b, v + 4 + 2 * i)[0] if i < n else t_
        raiz = struct.unpack_from("<I", b, 0)[0]
        doc = campo(raiz, 0)
        doc += struct.unpack_from("<I", b, doc)[0]
        o = campo(doc, 4)
        valor = 0 if o == doc else b[o]
        return _JUSTIFICA.get(valor, "esquerda")
    except (ValueError, struct.error, IndexError):
        return "esquerda"


#: `TimeInterpolationType` do `VideoClip` (Premiere › Time Interpolation) → retime do Resolve.
#: 2 = Optical Flow `confirmado` pela imagem (laboratório B22, 2026-10-12); ausente = Frame Sampling e 1 = Frame
#: Blending seguem `hipotese`. ⭐ Decisão do autor (2026-10-12): só o Optical Flow se correlaciona (FluidMotion no
#: Avid); o Frame Blending "dificilmente gera bons resultados" no Premiere e no Resolve — vai o quadro inteiro, o
#: padrão de todos (None = o do projeto).
RETIME = {None: None, "0": None, "1": None, "2": "optical_flow"}
#: Rotação: o Premiere gira no sentido horário com valor positivo (tela, +Y para baixo).
#: O Resolve, no anti-horário. `hipotese` até a comparação com o export (só o 180° do
#: PRODUCAO_B é indiferente ao sinal).
SINAL_ROTACAO_RESOLVE = -1.0


# ── tempo ──────────────────────────────────────────────────────────────────

def _int(v, padrao=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return padrao


def _float(v, padrao=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return padrao


def frames_para_tc(f: int, fps_nominal: int) -> str:
    f = max(0, int(f))
    s, q = divmod(f, fps_nominal)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{q:02d}"


# ── geometria (afim sem cisalhamento: escala uniforme, rotação, translação em px) ──

class Geo:
    """Mapeia pixels do conteúdo (centrados no centro do conteúdo) para pixels do contêiner
    (centrados no centro do contêiner): p' = R(rot)·(esc·asp·x, esc·y) + (tx, ty). Eixo Y para BAIXO.
    `esc` é a escala da ALTURA; `asp` = largura ÷ altura (1 = uniforme; o Scale Width do Premiere com
    o Uniform Scale desligado — o proxy 1024×540 de um UHD pede largura × 3,75 e altura × 4)."""
    __slots__ = ("esc", "rot", "tx", "ty", "asp")

    def __init__(self, esc=1.0, rot=0.0, tx=0.0, ty=0.0, asp=1.0):
        self.esc, self.rot, self.tx, self.ty, self.asp = esc, rot, tx, ty, asp

    def apos(self, dentro: "Geo") -> "Geo":
        """Composição: primeiro `dentro`, depois `self`. Com escala não uniforme E rotação na camada
        de fora a composição exata teria cisalhamento: as proporções se multiplicam (aproximação)."""
        c, s = math.cos(math.radians(self.rot)), math.sin(math.radians(self.rot))
        x, y = dentro.tx * self.esc * self.asp, dentro.ty * self.esc
        return Geo(self.esc * dentro.esc, self.rot + dentro.rot,
                   c * x - s * y + self.tx, s * x + c * y + self.ty, self.asp * dentro.asp)


def _valor(proj: Projeto, prm: Obj, t_midia: int | None):
    """Valor de um parâmetro no instante `t_midia` (ticks da mídia do item). Devolve
    (valor_texto, animado). Keyframe: interpolação linear entre os vizinhos (a curva do
    Premiere pode ser Bézier — o valor do instante é o que a primeira passada precisa)."""
    kfs = proj.campo(prm, "Keyframes")
    if kfs and t_midia is not None:
        pts = []
        for k in kfs.split(";"):
            partes = k.split(",")
            if len(partes) >= 2 and partes[0].lstrip("-").isdigit():
                pts.append((int(partes[0]), partes[1]))
        if pts:
            pts.sort()
            if t_midia <= pts[0][0]:
                return pts[0][1], True
            if t_midia >= pts[-1][0]:
                return pts[-1][1], True
            for (ta, va), (tb, vb) in zip(pts, pts[1:]):
                if ta <= t_midia <= tb:
                    f = (t_midia - ta) / (tb - ta) if tb > ta else 0.0
                    return _interp(va, vb, f), True
    # SEM keyframe vale o `StartKeyframe`: o `CurrentValue` pode ficar velho (8 escalas do PRODUCAO-C, 1 do PRODUCAO_B — 28 e 54,7 no CurrentValue, 50 no StartKeyframe; a API do Premiere e a
    # imagem dão o StartKeyframe; R04, 2026-10-10). COM keyframe (e sem instante) fica o CurrentValue.
    sk = proj.campo(prm, "StartKeyframe")
    if sk and not kfs:
        p = sk.split(",")
        if len(p) >= 2:
            return p[1], False
    cv = proj.campo(prm, "CurrentValue")
    if cv is not None:
        return cv, bool(kfs)
    if sk:
        p = sk.split(",")
        if len(p) >= 2:
            return p[1], bool(kfs)
    return None, bool(kfs)


def _bezier_trecho(ta: int, va: str, pa, tb: int, vb: str, pb, t: float) -> str | None:
    """O valor de um parâmetro do Motion entre dois keyframes com curva TEMPORAL Bézier (o modelo do After Effects), ou
    None se o trecho é linear. Campos do keyframe no XML (Premiere 22/23, decifrado no R04 em 2026-10-10):
    `tempo, valor, tipo_entrada, ?, vel_entrada, influência_entrada, vel_saída, influência_saída, tipo_saída, ?,
    tangente espacial de entrada (x, y), de saída (x, y)` — tipo 0 = linear, 5 = Bézier; velocidade em unidades do valor
    por SEGUNDO (Position: fração do quadro), influência em fração da duração do trecho. A distância percorrida no tempo
    é uma Bézier cúbica no plano (tempo, distância) com controles (infl_saída·D, vel_saída·infl_saída·D) e
    (D − infl_entrada·D, S − vel_entrada·infl_entrada·D); na Position, a distância anda sobre o caminho espacial (a Bézier
    dos dois pontos com as tangentes). CONFERIDO: o JUL_7504 do R04 (Position x, ease) — o modelo põe a imagem 31,6/31,9/
    31,7/30,9/29,4/27,1 px (de 960) à esquerda do linear nos quadros 531–536; medido contra o Premiere: 32/32/32/30/30/28.
    Na Position a distância é a do valor NORMALIZADO (√(dx² + dy²), sem corrigir a proporção do quadro): medida em
    largura do quadro (y × 9/16), um movimento VERTICAL com influência de 100 % (LOU_7217, quadros 157–162) passava do
    fim e piorava a imagem (0,88 → 0,70); em unidades normalizadas a curva fica coerente com as velocidades gravadas.
    Índices 8–9 = o tipo ESPACIAL (só nos parâmetros 2D); o temporal é o índice 2."""
    # 8 campos num parâmetro de um eixo (Scale, Rotation…), 14 na Position — com `< 9` a Scale do R04 (LOU_7237) ficava
    # linear (laboratório B17 + R04, 2026-10-10)
    if not pa or not pb or len(pa) < 8 or len(pb) < 8:
        return None
    if pa[2] in ("4", "7"):
        # HOLD (MEDIDO no laboratório B17, Premiere 23.2: tipos 4 e 7 pela API) — o valor fica até o próximo keyframe
        return vb if t >= tb else va
    try:
        # trecho linear: o keyframe de saída e o de chegada com o tipo TEMPORAL 0 (índice 2) e sem curva espacial
        if pa[2] in ("0", "") and pb[2] in ("0", "") and (len(pa) < 9 or pa[8] in ("0", "")):
            return None
        vel_s, infl_s = float(pa[6]), float(pa[7])
        vel_e, infl_e = float(pb[4]), float(pb[5])
    except ValueError:
        return None
    D = (tb - ta) / TPS
    if D <= 0:
        return None
    if ":" in va and ":" in vb:
        (ax, ay), (bx, by) = (tuple(map(float, va.split(":"))), tuple(map(float, vb.split(":"))))

        def tan(p, i):
            # tangente espacial só num keyframe de tipo ESPACIAL Bézier (índice 8 ≠ 0): no linear ela fica gravada mas não
            # vale — usada, o LOU_7217 (157, tangente −0,019 em y) fazia uma laçada no caminho e piorava 151–155
            if len(p) < 9 or p[8] in ("0", ""):
                return 0.0, 0.0
            try:
                return float(p[i]), float(p[i + 1])
            except (IndexError, ValueError):
                return 0.0, 0.0
        sx, sy = tan(pa, 12)            # tangente de SAÍDA do 1º
        ex, ey = tan(pb, 10)            # tangente de ENTRADA do 2º
        Q = [(ax, ay), (ax + sx, ay + sy), (bx + ex, by + ey), (bx, by)]

        def ponto(u):
            return tuple((1 - u) ** 3 * Q[0][i] + 3 * (1 - u) ** 2 * u * Q[1][i] + 3 * (1 - u) * u * u * Q[2][i]
                         + u ** 3 * Q[3][i] for i in (0, 1))
        N = 64                          # comprimento do caminho por tabela
        us = [i / N for i in range(N + 1)]
        ps = [ponto(u) for u in us]
        acum = [0.0]
        for p0, p1 in zip(ps, ps[1:]):
            acum.append(acum[-1] + math.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        S = acum[-1]
    else:
        S = float(vb) - float(va)
    if abs(S) < 1e-12:
        return va
    P1 = (infl_s * D, vel_s * infl_s * D)
    P2 = (D - infl_e * D, S - vel_e * infl_e * D)

    def bz(u, i):
        return 3 * (1 - u) ** 2 * u * P1[i] + 3 * (1 - u) * u * u * P2[i] + u ** 3 * (D if i == 0 else S)
    tt = (t - ta) / TPS
    lo, hi = 0.0, 1.0
    for _ in range(50):                 # o tempo da Bézier cresce: bisseção
        m = (lo + hi) / 2
        if bz(m, 0) < tt:
            lo = m
        else:
            hi = m
    s = bz(lo, 1)
    if ":" not in va:
        return str(float(va) + s)
    alvo = max(0.0, min(S, s))
    for i in range(N):
        if acum[i + 1] >= alvo:
            f = (alvo - acum[i]) / (acum[i + 1] - acum[i]) if acum[i + 1] > acum[i] else 0.0
            x, y = ps[i][0] + (ps[i + 1][0] - ps[i][0]) * f, ps[i][1] + (ps[i + 1][1] - ps[i][1]) * f
            return f"{x}:{y}"
    return vb


def _interp(a: str, b: str, f: float) -> str:
    if ":" in a and ":" in b:
        (ax, ay), (bx, by) = (map(float, a.split(":")), map(float, b.split(":")))
        return f"{ax + (bx - ax) * f}:{ay + (by - ay) * f}"
    return str(float(a) + (float(b) - float(a)) * f)


#: `Metadata` de uma linha do burn-in que é o TC da TIMELINE — o único medido (o burn-in do
#: PRODUCAO_B bate com o TC da referência em 01:00:59:02 e 01:22:49:07). 0 = linha vazia; os outros
#: valores (nome do clipe, TC da fonte…) estão `pendente`.
BURNIN_TC_TIMELINE = 4
#: Os 13 parâmetros de cada uma das 5 linhas do "Metadata & Timecode Burn-in", a partir do 2
#: (0 = Size do efeito, 1 = Opacity do fundo). Premiere 26.0.2, PRODUCAO_B (2026-10-08).
_BURNIN_LINHA = ("aberta", "metadado", "posicao", "size", "rotulo", "trilha", "rotulo_trilha",
                 "campo", "formato", "exibicao", "offset", "tc_inicio", "usar_tc_inicio")


def _lut_da_lumetri(proj: Projeto, comp: Obj) -> dict | None:
    """A LUT do look CRIATIVO de uma Lumetri, se ela estiver EMBUTIDA no projeto (banco
    `prproj/estruturas.md` §"Lumetri: a LUT EMBUTIDA", R04 PRODUCAO-C, 2026-10-10). Pelo
    `ParameterID` (o nome se repete): 23 = Creative ligado, 24 = caminho do .cube (UTF-16LE), 26 =
    Intensity (%), 98 = "Embedded LUTs" (blob `ITX3`). A intensidade mistura em GAMA (medido pela
    imagem). Devolve `{preset, intensidade, itx3_b64}` ou None (sem LUT embutida ou Creative desligado)."""
    import base64
    por_id = {proj.campo(prm, "ParameterID"): prm for prm in proj.refs(comp, "Param")}

    def inicial(pid):
        prm = por_id.get(pid)
        if prm is None:
            return None
        sk = proj.campo(prm, "StartKeyframe")
        return sk.split(",")[1] if sk and "," in sk else proj.valor_inicial(prm)
    def ligado(pid):
        return (inicial(pid) or "").strip().lower() in ("true", "1")

    def caminho(pid):
        try:
            s = base64.b64decode(inicial(pid) or "").decode("utf-16le", "replace")
        except ValueError:
            return ""
        # vazio é "/v4=" (FE FF): sobra uma marca de ordem de bytes, que não é caminho
        return "".join(ch for ch in s if ch.isprintable() and ch not in "﻿￾﻾�").strip()
    blob = inicial("98")
    try:
        cru = base64.b64decode(blob or "")
    except ValueError:
        return None
    if cru[20:24] != b"ITX3":
        return None
    criativa = caminho("24") if ligado("23") else ""
    # INPUT LUT da Correção Básica (3 = ligada, 4 = caminho do .cube): a LUT de câmera (log → Rec.709), a 100 % — o
    # "Intensity" 123 do mesmo efeito NÃO é dela (medido 2026-10-10, R04: a Lumetri do master clip do PRJ-0006-252 com
    # KC_NEUTM.cube; a 100 % a cor bate com o render do Premiere a 2,3/255, a 50 % fica a 9,2). O blob 98 traz a LUT.
    entrada = caminho("4") if ligado("3") else ""
    if criativa or (ligado("23") and not entrada):
        return {"preset": criativa, "intensidade": _float(inicial("26"), 100.0), "itx3_b64": blob,
                "tambem_entrada": bool(entrada)}
    if entrada:
        return {"preset": entrada, "intensidade": 100.0, "itx3_b64": blob, "tipo": "entrada"}
    return None


def _lut_do_master(proj: Projeto, item: Obj) -> dict | None:
    """A LUT da Lumetri do MASTER CLIP do item (o "Source Clip Effect" do painel de projeto: vale para toda instância do
    clipe, em qualquer sequência) — `TrackItem → SubClip → MasterClip (ObjectURef) → VideoComponentChain`. MEDIDO
    2026-10-10 (R04): os 16 master clips da câmera em log (PRJ-*) têm uma Lumetri com a Input LUT KC_NEUTM; sem ela o
    plano sai cinza e lavado no Resolve (saturação 0,11 × 0,26 do Premiere). Lumetri desligada (Bypass) não conta."""
    sub = proj.ref(item, "SubClip")
    mc = proj.ref(sub, "MasterClip") if sub is not None else None
    cad = proj.ref(mc, "VideoComponentChain") if mc is not None else None
    for comp in (proj.refs(cad, "Component") if cad is not None else []):
        if proj.campo(comp, "MatchName") == "AE.ADBE Lumetri" and proj.campo(comp, "Bypass") != "true":
            return _lut_da_lumetri(proj, comp)
    return None


def _cor_do_master(proj: Projeto, item: Obj) -> list[dict]:
    """A Lumetri do MASTER CLIP inteira (`_lumetri_cor`: LUT, balanço, curvas e o que não traduz), uma por efeito ligado.
    Antes só a LUT da 1ª ia — curvas/temperatura da Lumetri do master clip sumiam caladas (revisão de código, 2026-10-10)."""
    sub = proj.ref(item, "SubClip")
    mc = proj.ref(sub, "MasterClip") if sub is not None else None
    cad = proj.ref(mc, "VideoComponentChain") if mc is not None else None
    return [_lumetri_cor(proj, comp) for comp in (proj.refs(cad, "Component") if cad is not None else [])
            if proj.campo(comp, "MatchName") == "AE.ADBE Lumetri" and proj.campo(comp, "Bypass") != "true"]


def _remap_do_clipe(proj: Projeto, vc: Obj) -> list[tuple[float, float, str]] | None:
    """A curva do Time Remapping do `VideoClip`: `[(tempo do clipe s, tempo da fonte s, tipo)]`, ou None
    quando não há rampa (ausente, um ponto só, ou a identidade 0→0 … D→D). Formato do keyframe
    (`TimeComponentParam`, medido no R04 PRODUCAO-C, 2026-10-10): `ticks,fonte_s,tipo,…` — tipo 6 =
    canto (a velocidade muda de uma vez); o par 7 → 8 = transição SUAVIZADA (a velocidade muda em reta)."""
    tr = proj.ref(vc, "TimeRemapping")
    k = proj.ref(tr, "Keyframes") if tr is not None else None
    kfs = proj.campo(k, "Keyframes") if k is not None else None
    if not kfs:
        return None
    pts = []
    for x in kfs.split(";"):
        partes = x.split(",")
        if len(partes) >= 3 and partes[0].lstrip("-").isdigit():
            pt = (int(partes[0]) / TPS, float(partes[1]), partes[2].strip())
            # tipo 7 com INFLUÊNCIA (campos 4 e 6, em %; "7,0,48.5,0.0001,48.5,0"): a transição é uma Bézier na
            # velocidade (`_remap_fonte`); zerados ("7,0,0,0,0,0"), a reta. Vai como 4º elemento: (saída, entrada).
            infl = [_float(partes[k], 0.0) / 100 if len(partes) > k else 0.0 for k in (4, 6)]
            pts.append(pt + (tuple(infl),) if pt[2] == "7" and any(infl) else pt)
    pts.sort()
    if len(pts) < 2:
        return None
    if all(abs(x[0] - x[1]) < 1e-4 for x in pts) and all(x[2] == "6" for x in pts):
        return None
    return pts


# Gauss-Legendre de 3 pontos em [0, 1]: exata para polinômio até o grau 5 — o integrando da Bézier (velocidade
# cúbica × derivada quadrática do tempo).
_GL3 = ((0.5 - math.sqrt(0.15), 5 / 18), (0.5, 8 / 18), (0.5 + math.sqrt(0.15), 5 / 18))


def _bezier_velocidade(u: float, T: float, v1: float, v2: float, i1: float, i2: float) -> float:
    """Fonte andada (s) até `u` numa transição de duração `T` em que a VELOCIDADE é uma Bézier cúbica no plano
    (tempo, velocidade): P0 = (0, v1), P1 = (i1·T, v1), P2 = (T − i2·T, v2), P3 = (T, v2) — as alças horizontais do
    gráfico de velocidade do Premiere, com o comprimento da INFLUÊNCIA. MEDIDO 2026-10-10 (R04 contra a referência
    fechada, cada quadro casado com o da mídia): A030_C026 (44,5 %) 13/13 quadros exatos; A030_C062 (48,5 %) 14/15 e o
    outro a 0,05 quadro da borda — a velocidade em reta errava até 8 quadros da fonte no meio da transição."""
    def x(p):
        return 3 * (1 - p) ** 2 * p * i1 * T + 3 * (1 - p) * p * p * (T - i2 * T) + p ** 3 * T
    lo, hi = 0.0, 1.0
    for _ in range(50):                  # x(p) é monótono (alças dentro do trecho): bissecção
        m = (lo + hi) / 2
        lo, hi = (m, hi) if x(m) < u else (lo, m)
    pf = (lo + hi) / 2

    def v(p):
        return ((1 - p) ** 3 + 3 * (1 - p) ** 2 * p) * v1 + (3 * (1 - p) * p * p + p ** 3) * v2

    def dx(p):
        return 3 * (1 - p) ** 2 * i1 * T + 6 * (1 - p) * p * (T - i2 * T - i1 * T) + 3 * p * p * (T - (T - i2 * T))
    return pf * sum(w * v(pf * n) * dx(pf * n) for n, w in _GL3)


def _remap_fonte(pts: list[tuple[float, float, str]], t: float) -> float:
    """Tempo da FONTE (s) no tempo do CLIPE `t` (s). Entre dois cantos, a reta; num trecho 7 → 8, a
    velocidade vai em reta da do trecho de antes (v1) à do de depois (v2): s = s7 + v1·u + (v2 − v1)·u²/2T
    — confere com o projeto (s8 − s7 = T·(v1 + v2)/2 em todas as rampas do R04) e com a imagem do
    Premiere (3 planos, a ±0,05 s de fonte, o deslocamento fixo do proxy de 60 qps)."""
    def incl(i):                       # velocidade do trecho i → i+1
        (ta, sa), (tb, sb) = pts[i][:2], pts[i + 1][:2]
        return (sb - sa) / (tb - ta) if tb > ta else 0.0
    if t <= pts[0][0]:
        return pts[0][1] + incl(0) * (t - pts[0][0])
    for i in range(len(pts) - 1):
        (ta, sa, tpa), (tb, sb, tpb) = pts[i][:3], pts[i + 1][:3]
        if t <= tb:
            u, T = t - ta, tb - ta
            if tpa == "7" and tpb == "8" and T > 0 and 0 < i and i + 2 < len(pts):
                v1, v2 = incl(i - 1), incl(i + 1)
                if len(pts[i]) > 3:        # com influência: a Bézier na velocidade
                    # com influências DESIGUAIS a área da Bézier não é T·(v1+v2)/2: escala para fechar em s8, sem salto
                    # no keyframe 8 (revisão de código, 2026-10-10; no R04 são todas simétricas — não medido)
                    i1, i2 = pts[i][3]
                    ds = _bezier_velocidade(u, T, v1, v2, i1, i2)
                    if abs(i1 - i2) > 1e-9:
                        cheio = _bezier_velocidade(T, T, v1, v2, i1, i2)
                        ds = ds * (sb - sa) / cheio if cheio else ds
                    return sa + ds
                return sa + v1 * u + (v2 - v1) * u * u / (2 * T)
            return sa + (sb - sa) * (u / T if T else 0.0)
    return pts[-1][1] + incl(len(pts) - 2) * (t - pts[-1][0])


def _espelhar(r: dict, flip) -> dict:
    """Máscara de OPACIDADE num clipe com Flip: no Premiere o Flip (efeito) vem ANTES da Opacidade — a imagem é
    espelhada e a máscara cai no quadro já espelhado; no Resolve a máscara vai no Fusion e o Flip da Edit vem DEPOIS,
    espelhando a máscara junto. Então o contorno vai espelhado (x → 1 − x; y → 1 − y no vertical) para os dois se
    anularem. MEDIDO no R04 (2026-10-10, JUL_7644 com Flip horizontal, 4:23): a rua abria à DIREITA (0,30–0,72 da tela)
    onde o Premiere a abre à esquerda, atrás da moça desfocada — parecia o wipe "se antecipando". Só a opacidade: a
    máscara de um efeito (Crop, Blur) depende da ordem dele na pilha em relação ao Flip (não medido)."""
    fx, fy = bool(flip and flip[0]), bool(flip and flip[1])
    if r.get("efeito") != "opacidade" or not (fx or fy):
        return r

    def pt(p):
        return [1 - p[0] if fx else p[0], 1 - p[1] if fy else p[1]]

    def vs(lista):
        return [[su, pt(v), pt(i), pt(o)] for su, v, i, o in lista]
    for m in r.get("mascaras") or []:
        m["vertices"] = vs(m["vertices"])
        for qd in m.get("quadros") or []:
            qd["vertices"] = vs(qd["vertices"])
    return r


def _assar_contorno(qds: list, tempo, fonte_em, t0: float, n: int, tpf_tl: float, tpf_m: float) -> list:
    """O contorno animado assado quadro a quadro: para cada quadro k do plano, a forma no tempo em que o Premiere avalia a
    máscara (`tempo(T)`, interpolação linear entre os keyframes dele; antes do 1º e depois do último, segura) no tempo da
    composição do Fusion que o Resolve usa (o PISO da fonte mostrada, `fonte_em(T)` em quadros do arquivo). Dois quadros
    no mesmo tempo da composição (câmera lenta) ficam com o primeiro. Os vértices de keyframes com contagens diferentes
    são igualados antes (`drp.fusion_clipe.igualar_vertices`)."""
    from drp.fusion_clipe import igualar_vertices          # import tardio: só quem assa precisa
    qs = sorted(qds, key=lambda q: q["t"])
    ts = [q["t"] for q in qs]
    vs = igualar_vertices([q["vertices"] for q in qs])

    def forma(tm):
        if tm <= ts[0]:
            return vs[0]
        if tm >= ts[-1]:
            return vs[-1]
        i = max(j for j in range(len(ts) - 1) if ts[j] <= tm)
        a = (tm - ts[i]) / (ts[i + 1] - ts[i]) if ts[i + 1] > ts[i] else 0.0

        def lerp(p0, p1):
            return [p0[0] + (p1[0] - p0[0]) * a, p0[1] + (p1[1] - p0[1]) * a]
        return [[v0[0], lerp(v0[1], v1[1]), lerp(v0[2], v1[2]), lerp(v0[3], v1[3])] for v0, v1 in zip(vs[i], vs[i + 1])]
    out, vistos = [], set()
    for k in range(max(1, n)):
        T = t0 + k * tpf_tl
        c = math.floor(fonte_em(T) / tpf_m + 1e-4)
        if c in vistos:
            continue
        vistos.add(c)
        out.append({"quadro": c, "vertices": forma(tempo(T))})
    return out


def lut_itx3_para_cube(itx3_b64: str, intensidade: float, titulo: str = "") -> str:
    """O blob `ITX3` da Lumetri → texto `.cube` (R varia mais rápido, como no blob), já na
    intensidade: (1 − i)·identidade + i·LUT nos pontos da grade — exato também na interpolação."""
    import base64
    cru = base64.b64decode(itx3_b64)
    n, canais = struct.unpack("<II", cru[24:32])
    if not (2 <= n <= 256 and canais in (3, 4)) or n ** 3 * canais * 4 > len(cru):
        n, canais = struct.unpack("<II", cru[4:12])     # a forma da camada LUT da página Color (Premiere 27)
    corpo = len(cru) - n ** 3 * canais * 4
    vals = struct.unpack(f"<{n ** 3 * canais}f", cru[corpo:])
    i = max(0.0, min(1.0, intensidade / 100.0))
    linhas = [f'TITLE "{titulo or "Lumetri"}"', f"LUT_3D_SIZE {n}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    passo = 1.0 / (n - 1)
    k = 0
    for b in range(n):
        for g in range(n):
            for r in range(n):
                ident = (r * passo, g * passo, b * passo)
                v = vals[k * canais:k * canais + 3]
                linhas.append(" ".join(f"{(1 - i) * a + i * c:.6f}" for a, c in zip(ident, v)))
                k += 1
    return "\n".join(linhas) + "\n"


def _curvas_rgb(b64: str) -> list[list[tuple[float, float]]] | None:
    """As curvas RGB da Lumetri (ParameterID 39): 4 blocos de 520 bytes — mestra, R, G, B —, cada um `u32 ?, u32 n` +
    32 pares (x, y) em double (0–1). Medido 2026-10-10 (R04, 69 Lumetri de plano). None se ilegível."""
    import base64
    try:
        d = base64.b64decode(b64 or "")
    except ValueError:
        return None
    if len(d) < 4 * 520:
        return None
    out = []
    for k in range(4):
        b = d[k * 520:(k + 1) * 520]
        n = struct.unpack("<I", b[4:8])[0]
        if not 2 <= n <= 32:
            return None
        out.append(sorted(struct.unpack("<dd", b[8 + 16 * i:24 + 16 * i]) for i in range(n)))
    return out


def _curva_identidade(pts) -> bool:
    return all(abs(x - y) < 1e-6 for x, y in pts) and pts[0][0] < 1e-6 and pts[-1][0] > 1 - 1e-6


def _spline_natural(pts):
    """A curva da Lumetri entre os pontos: SPLINE CÚBICA NATURAL; fora do primeiro/último ponto, plana. MEDIDO 2026-10-10
    (R04, PRJ-0006-147, curva de 3 pontos, Premiere 23.2 × o mesmo plano sem a curva no Resolve, pixel a pixel): natural
    1,4/255, PCHIP 2,9, reta 4,6, sem curva 22,7 (o piso da medição é ~1–2)."""
    # dois pontos no mesmo x (revisão de código, 2026-10-10: dividiria por zero e derrubaria a conversão): fica o último
    unicos: dict[float, float] = {}
    for x_, y_ in sorted(pts):
        unicos[round(x_, 9)] = y_
    xs, ys = list(unicos), list(unicos.values())
    if len(xs) == 1:
        return lambda v, y=ys[0]: y
    n = len(xs)
    m = [0.0] * n                        # segundas derivadas (natural: 0 nas pontas)
    if n > 2:
        h = [xs[i + 1] - xs[i] for i in range(n - 1)]
        a, b, c, r = [0.0] * n, [1.0] * n, [0.0] * n, [0.0] * n
        for i in range(1, n - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            r[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
        for i in range(1, n):            # Thomas
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            r[i] -= w * r[i - 1]
        m[n - 1] = r[n - 1] / b[n - 1]
        for i in range(n - 2, -1, -1):
            m[i] = (r[i] - c[i] * m[i + 1]) / b[i]
        m[0] = m[n - 1] = 0.0

    def f(v):
        if v <= xs[0]:
            return ys[0]
        if v >= xs[-1]:
            return ys[-1]
        i = max(j for j in range(n - 1) if xs[j] <= v)
        h = xs[i + 1] - xs[i]
        t, u = (xs[i + 1] - v) / h, (v - xs[i]) / h
        return (m[i] * t ** 3 + m[i + 1] * u ** 3) * h * h / 6 + (ys[i] - m[i] * h * h / 6) * t \
            + (ys[i + 1] - m[i + 1] * h * h / 6) * u
    return f


def _lumetri_cor(proj: Projeto, comp: Obj) -> dict:
    """O que a Lumetri de um plano faz na cor e o De Lá Pra Cá leva: as curvas RGB (`curvas`, None se identidade) e o look
    (`lut`); `nao` = o que ela tem e ainda NÃO vai (vira aviso). Visto no R04: quase só a curva mestra; 3 com temperatura/
    tint (7/8) e ~20 com as curvas de saturação (110 Luma vs Sat, 112 Sat vs Sat)."""
    import base64
    por_id = {proj.campo(prm, "ParameterID"): prm for prm in proj.refs(comp, "Param")}

    def inicial(pid):
        prm = por_id.get(pid)
        if prm is None:
            return None
        sk = proj.campo(prm, "StartKeyframe")
        return sk.split(",")[1] if sk and "," in sk else proj.valor_inicial(prm)
    nao = []
    curvas = None
    if (inicial("37") or "").strip().lower() in ("true", "1"):          # a seção Curves ligada
        cv = _curvas_rgb(inicial("39") or "")
        if cv is None:
            nao.append("curvas RGB (ilegíveis)")
        elif not all(_curva_identidade(c) for c in cv):
            curvas = cv
    wb = None
    basica = (inicial("3") or "true").strip().lower() in ("true", "1")
    temp, tint = (_float(inicial("7"), 0.0), _float(inicial("8"), 0.0)) if basica else (0.0, 0.0)
    if temp or tint:
        # BALANÇO DE BRANCO: ganho por canal no domínio GAMA, antes das curvas. MEDIDO 2026-10-10 (R04, A030_C062, render do
        # Premiere × o plano sem ele): temperatura −17,25 e tint +10,59 → R 0,9834, G 0,9990, B 1,0933 (erro 7,1 → 1,25/255).
        # Um ponto só: fora dele, escala LINEAR (temperatura em R/B opostos, tint em G) — aproximação, com aviso.
        wb = [1 - 0.000962 * -temp, 1 - 0.0000944 * tint, 1 + 0.005409 * -temp]
        if abs(temp + 17.25) > 0.5 or abs(tint - 10.59) > 0.5:
            nao.append("temperatura/tint (aproximados: medidos num ponto só)")
    hsl = {}
    for pid, nome in (("110", "Luma vs Sat"), ("112", "Sat vs Sat"), ("42", "Hue vs Sat"),
                      ("106", "Hue vs Hue"), ("108", "Hue vs Luma")):
        # bloco de 520 bytes `u32 tipo, u32 n` + n pares (x, y) em double; n = 0 é a curva padrão (sem efeito)
        try:
            d = base64.b64decode(inicial(pid) or "")
        except ValueError:
            d = b""
        n = struct.unpack("<I", d[4:8])[0] if len(d) >= 8 else 0
        if not n:
            continue
        if pid in ("110", "112") and 2 <= n <= 32 and len(d) >= 8 + 16 * n:
            hsl[nome] = sorted(struct.unpack("<dd", d[8 + 16 * i:24 + 16 * i]) for i in range(n))
        else:
            nao.append(nome)
    lut = _lut_da_lumetri(proj, comp)
    if lut and lut.get("tambem_entrada"):
        # o blob 98 traz as duas LUTs e o leitor só sabe tirar uma (revisão de código, 2026-10-10): a Input LUT não vai
        nao.append("Input LUT (junto com o look criativo)")
    nao += _lumetri_resto(inicial)
    return {"curvas": curvas, "lut": lut, "wb": wb,
            "luma_sat": hsl.get("Luma vs Sat"), "sat_sat": hsl.get("Sat vs Sat"), "nao": nao}


#: O que a Lumetri faz e o De Lá Pra Cá ainda NÃO traduz: (ParameterID, nome, padrão, chave da seção). O padrão é o de uma
#: Lumetri recém-aplicada no Premiere 23.2 (2026-10-10; os blobs pela impressão md5). Fora do padrão, com a seção ligada,
#: vira aviso — antes ia calado (revisão de código, 2026-10-10: "sem perda").
_LUMETRI_RESTO = [
    ("11", "Exposure", "0.", "3"), ("12", "Contrast", "0.", "3"), ("13", "Highlights", "0.", "3"),
    ("14", "Shadows", "0.", "3"), ("15", "Whites", "0.", "3"), ("16", "Blacks", "0.", "3"), ("20", "Saturation", "100.", "3"),
    ("28", "Faded Film", "0.", "23"), ("29", "Sharpen", "0.", "23"), ("30", "Vibrance", "0.", "23"),
    ("31", "Saturation (Creative)", "100.", "23"), ("33", "Tint Balance", "0.", "23"),
    ("32", "Shadow/Highlight Tint", "md5:c10b0fdd8ebdc939d9abb4b256a8a458", "23"),
    ("47", "Color Wheels", "md5:58b2dfcc57085348e5c3110bdb7ab825", "46"),
    ("51", "Vignette", "0.", "50"),
    ("73", "HSL Secondary (key)", "md5:a83bf17213efde077bd5e30fdf255767", "68"),
    ("85", "HSL Secondary (cor)", "md5:8ade1a605bc1ee87af3a9b9d3d4974af", "68"),
    ("86", "HSL Secondary (Temperature)", "0.", "68"), ("87", "HSL Secondary (Tint)", "0.", "68"),
    ("88", "HSL Secondary (Contrast)", "0.", "68"), ("89", "HSL Secondary (Sharpen)", "0.", "68"),
    ("90", "HSL Secondary (Saturation)", "100.", "68"), ("81", "Denoise", "0.", "68"), ("82", "Blur", "0.", "68"),
]


def _lumetri_resto(inicial) -> list[str]:
    import hashlib
    out = []
    for pid, nome, padrao, secao in _LUMETRI_RESTO:
        v = inicial(pid)
        if v is None or (inicial(secao) or "true").strip().lower() not in ("true", "1"):
            continue
        if padrao.startswith("md5:"):
            if hashlib.md5(v.encode()).hexdigest() != padrao[4:]:
                out.append(nome)
        elif abs(_float(v, _float(padrao, 0.0)) - _float(padrao, 0.0)) > 1e-9:
            out.append(nome)
    return out


def _amostrador_itx3(itx3_b64: str, intensidade: float):
    """f(r, g, b) da LUT `ITX3` (trilinear, na intensidade — mistura em gama, como no `.cube`)."""
    import base64
    cru = base64.b64decode(itx3_b64)
    n, canais = struct.unpack("<II", cru[24:32])
    if not (2 <= n <= 256 and canais in (3, 4)) or n ** 3 * canais * 4 > len(cru):
        # a OUTRA forma: a camada LUT da página Color do Premiere 27 (`AE.ADBE LUT Transform`, 2026-11-20) — o tamanho
        # no byte 4 e os canais no 8, 40 bytes de cabeçalho (393 256 = 40 + 32³·3·4)
        n, canais = struct.unpack("<II", cru[4:12])
    vals = struct.unpack(f"<{n ** 3 * canais}f", cru[len(cru) - n ** 3 * canais * 4:])
    i = max(0.0, min(1.0, intensidade / 100.0))

    def at(r, g, b):
        k = ((b * n + g) * n + r) * canais
        return vals[k:k + 3]

    def f(r, g, b):
        p = [min(max(c, 0.0), 1.0) * (n - 1) for c in (r, g, b)]
        q = [min(int(x), n - 2) for x in p]
        t = [x - y for x, y in zip(p, q)]
        out = [0.0, 0.0, 0.0]
        for dr in (0, 1):
            for dg in (0, 1):
                for db in (0, 1):
                    w = (t[0] if dr else 1 - t[0]) * (t[1] if dg else 1 - t[1]) * (t[2] if db else 1 - t[2])
                    if w:
                        v = at(q[0] + dr, q[1] + dg, q[2] + db)
                        out = [o + w * c for o, c in zip(out, v)]
        return tuple((1 - i) * a + i * c for a, c in zip((r, g, b), out))
    return f


def _saturacao_por_curva(curva, pela_luma: bool):
    """As curvas de saturação da Lumetri (Luma vs Sat, Sat vs Sat): y é um DESLOCAMENTO sobre a linha neutra e o ganho de
    saturação é 1 + y(x), com x = a luma Rec.709 (Luma vs Sat) ou a saturação HSL (Sat vs Sat); a cor se afasta da MÉDIA
    RGB. MEDIDO 2026-10-10 (R04, render do Premiere × o plano sem a curva, pixel a pixel): PRJ-0006-271 (Luma vs Sat)
    2,03 → 1,35/255; A030_C026 (Sat vs Sat) 1,64 → 1,19. `parcial`: o centro (média × luma) ficou perto do piso da medida."""
    def f(r, g, b):
        if pela_luma:
            x = 0.2126 * r + 0.7152 * g + 0.0722 * b
        else:
            mx, mn = max(r, g, b), min(r, g, b)
            x = (mx - mn) / max(1 - abs(mx + mn - 1), 1e-9) if mx > mn else 0.0
        k = 1 + curva(min(max(x, 0.0), 1.0))
        c = (r + g + b) / 3
        return (c + (r - c) * k, c + (g - c) * k, c + (b - c) * k)
    return f


def _tamanho_itx3(itx3_b64: str) -> int | None:
    import base64
    cru = base64.b64decode(itx3_b64[:64] + "=" * (-len(itx3_b64[:64]) % 4))
    for ini in (24, 4):
        k = struct.unpack("<I", cru[ini:ini + 4])[0] if len(cru) >= ini + 4 else 0
        if 2 <= k <= 256:
            return k
    return None


def _tamanho_da_composta(etapas: list[dict]) -> int:
    """33, ou o menor n de 33 a 41 cuja grade CONTÉM a de cada ITX3 da composição ((n − 1) múltiplo de (m − 1)): aí a
    trilinear da LUT original é reproduzida EXATA. Medido (Film Color, estoque 21³, Premiere 27, 2026-11-20): em 33³ a
    reamostragem dava 0,42 / máx 4,07 códigos contra o render; em 41³ (alinhada) volta ao 0,30 / 1,77 da tabela crua."""
    ms = [m for m in (_tamanho_itx3(e["itx3_b64"]) for e in etapas if e.get("itx3_b64")) if m]
    for n in range(33, 42):
        if all((n - 1) % (m - 1) == 0 for m in ms):
            return n
    return 33


def lut_composta(etapas: list[dict], titulo: str = "", n: int | None = None) -> str:
    """Um `.cube` com as etapas de cor EM ORDEM: `{"itx3_b64", "intensidade"}` (uma LUT da Lumetri) ou `{"curvas": [mestra,
    R, G, B]}` (cada canal pela sua curva, depois a mestra nos três — a ordem entre as duas não foi medida: no R04 os canais
    são identidade). Para o plano com a Input LUT do master clip E a curva da Lumetri dele (o Resolve só aceita uma LUT
    por nó pela API)."""
    fs = []
    for e in etapas:
        if e.get("itx3_b64"):
            fs.append(_amostrador_itx3(e["itx3_b64"], float(e.get("intensidade") or 100.0)))
        elif e.get("curvas"):
            mestra, *canais = [_spline_natural(c) for c in e["curvas"]]
            fs.append(lambda r, g, b, mestra=mestra, canais=canais:
                      tuple(mestra(c(v)) for c, v in zip(canais, (r, g, b))))
        elif e.get("wb"):
            fs.append(lambda r, g, b, k=e["wb"]: (r * k[0], g * k[1], b * k[2]))
        elif e.get("luma_sat") or e.get("sat_sat"):
            fs.append(_saturacao_por_curva(_spline_natural(e.get("luma_sat") or e["sat_sat"]), bool(e.get("luma_sat"))))
        elif e.get("pagina_cor"):
            # o Color And Contrast da página Color do Premiere 2027 (o modelo do kernel, `pagina_cor.funcao`)
            fs.append(_funcao_pagina_cor(e["pagina_cor"]))
    n = n or _tamanho_da_composta(etapas)
    linhas = [f'TITLE "{titulo or "Lumetri"}"', f"LUT_3D_SIZE {n}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    passo = 1.0 / (n - 1)
    for b in range(n):
        for g in range(n):
            for r in range(n):
                v = (r * passo, g * passo, b * passo)
                for f in fs:
                    v = f(*v)
                linhas.append(" ".join(f"{min(max(c, 0.0), 1.0):.6f}" for c in v))
    return "\n".join(linhas) + "\n"


def _ler_burnin(proj: Projeto, comp: Obj, avisos: list) -> dict:
    """O burn-in do Premiere: `{size, opacidade (0–1), linhas: [{metadado, posicao, size, …}]}`.
    O nome dos parâmetros se repete por linha: a leitura é pela POSIÇÃO."""
    prm = proj.refs(comp, "Param")
    vals = []
    for x in prm:
        v, animado = _valor(proj, x, None)
        if animado:
            avisos.append(f"burn-in com {proj.campo(x, 'Name')} animado: usado o valor fixo")
        vals.append(v)
    out = {"size": _float(vals[0] if vals else None, 10.0) or 10.0,
           "opacidade": (_float(vals[1] if len(vals) > 1 else None, 0.0) or 0.0) / 100.0,
           "linhas": []}
    for k in range(5):
        bloco = vals[2 + 13 * k: 2 + 13 * (k + 1)]
        if len(bloco) < 13:
            break
        d = dict(zip(_BURNIN_LINHA, bloco))
        meta = _int(d["metadado"])
        if not meta:
            continue
        out["linhas"].append({"linha": k + 1, "metadado": meta,
                              "posicao": _ponto(d["posicao"], (0.5, 0.5)),
                              "size": _float(d["size"], 100.0) or 100.0,
                              "rotulo": (d["rotulo"] or "").lower() == "true",
                              "formato": _int(d["formato"]), "exibicao": _int(d["exibicao"]),
                              "offset": _int(d["offset"]),
                              "tc_inicio": _int(d["tc_inicio"]) if (d["usar_tc_inicio"] or "").lower() == "true" else None})
    return out


def _mascaras_ou_nada(proj: Projeto, comp: Obj) -> list[dict] | None:
    """As máscaras do efeito; `None` quando há máscara mas ela não se lê. O formato do `Path` foi
    deduzido de UM projeto (Premiere 26.0.2): o de outra versão ou de outra produtora pode ter outro
    cabeçalho, e um `struct.error` aqui derrubava a sequência inteira (revisão de código,
    2026-10-03). Agora só aquele efeito vira "refazer". O mapeamento por versão está na lista de
    testes sintéticos (HANDOFF)."""
    import binascii
    import struct as _struct
    try:
        return ler_mascaras(proj, comp)
    except (_struct.error, binascii.Error, ValueError, IndexError, TypeError):
        return None


class Motion:
    """O Motion de UM item, avaliável em qualquer instante da mídia do item.

    Keyframe do Premiere (`<Keyframes>`): `tempo,valor,interp,…;` com o tempo em ticks da MÍDIA
    do item (o mesmo domínio do `InPoint`). `interp` 0 = linear (medido: o zoom do ovo frito,
    PRODUCAO_B 01:14:13:21, é `0`); outro código = curva, aproximada aqui como linear e avisada."""

    def __init__(self, proj: Projeto, item: Obj):
        self.estatico: dict = {}
        self.pontos: dict[str, list[tuple[int, str]]] = {}
        self.efeitos: list[str] = []
        self.curva = False
        self.campos: dict[str, dict[int, list[str]]] = {}   # nome → {tempo: campos do keyframe} (a curva Bézier)
        #: Crop por borda, em FRAÇÃO da fonte (o Premiere guarda %). Soma o efeito Crop
        #: (`AE.ADBE AECrop`: Left/Top/Right/Bottom) e o crop do próprio Motion; vale o maior.
        self.crop = {"l": 0.0, "t": 0.0, "r": 0.0, "b": 0.0}
        self.crop_aviso: list[str] = []
        self.crop_suave = 0.0
        self.flip = [False, False]          # horizontal, vertical (efeitos de Flip)
        self.luma_key = False
        self.pb = False                     # Black & White → saturação 0 no nó de cor do Resolve
        #: Efeitos que viram composição do Fusion (Crop com máscara, Gaussian Blur com ou sem
        #: máscara): `(efeito, máscaras cruas de `ler_mascaras`, parâmetros)`. A receita final
        #: (vértices na fonte do clipe de DENTRO) sai na folha, que conhece a fonte.
        self.fusion: list[tuple[str, list[dict], dict]] = []
        #: Título (`AE.ADBE Text`): texto, fonte, posição e escala do texto; `grupo` = a escala
        #: do Graphic Group (Vector Motion) por cima.
        self.texto: dict | None = None
        self.grupo_escala_kf: list[tuple[int, float]] = []
        self.grupo_curva = False
        #: "Metadata & Timecode Burn-in" (`AE.ADBE PPro Metadata`): `{size, opacidade, linhas}`;
        #: vira Text+ no Resolve (`titulos/textplus.py`). Só as linhas com metadado (≠ 0).
        self.burnin: dict | None = None
        #: a LUT CRIATIVA da Lumetri (`_lut_da_lumetri`): `{preset, intensidade, itx3_b64}` ou None
        self.lut: dict | None = None
        self.cor: list[dict] = []           # a Lumetri de cada efeito do item, em ordem (`_lumetri_cor`)
        cadeia = proj.ref(item, "Components")
        if cadeia is None:
            return
        for comp in proj.refs(cadeia, "Component"):
            mn = proj.campo(comp, "MatchName")
            if proj.campo(comp, "Bypass") == "true":
                # EFEITO DESLIGADO (o "fx" apagado no Effect Controls): não existe na imagem — nem a máscara da Opacidade.
                # MEDIDO 2026-10-10 (R04, render do Premiere só com a V2): o JUL_7504 tem a Opacidade com máscara animada e
                # `<Bypass>true</Bypass>` — o Premiere mostra o quadro inteiro; traduzida, a máscara abria o Pão de Açúcar
                # da trilha de baixo na borda direita (528–530, 0,59). O R04 tem 8 componentes assim (Opacidade, Lumetri, EQ).
                continue
            if eh_pagina_cor(comp):
                # A PÁGINA COLOR do Premiere 2027: componente SEM MatchName (o `None` do `_NAO_EFEITO`), dono de uma árvore.
                # Antes passava CALADA (banco `prproj/estruturas.md` §Premiere 2027). O Color And Contrast global vai na LUT
                # do nó, como a Lumetri; o resto vira aviso (`pagina_cor.py`).
                pc = ler_pagina_cor(proj, comp)
                if pc["pagina_cor"] or pc["nao"] or pc["vinheta"]:
                    self.cor.append({"curvas": None, "lut": None, "wb": None, "luma_sat": None, "sat_sat": None,
                                     "pagina_cor": pc["pagina_cor"], "nao": pc["nao"], "vinheta": pc["vinheta"]})
                continue
            if mn == "AE.ADBE Text":
                tx: dict = {"animado": False}
                for prm in proj.refs(comp, "Param"):
                    nome = proj.campo(prm, "Name")
                    if nome == "Source Text":
                        b64 = proj.valor_inicial(prm)        # resolve o BinaryHash (projeto.py)
                        if b64:
                            tx["texto"], tx["fonte"] = _texto_do_blob(b64)
                            tx["corpo_px"] = _corpo_do_blob(b64)
                            tx["alinhamento"] = _alinhamento_do_blob(b64)
                    elif nome in ("Position", "Scale", "Opacity", "Anchor Point") \
                            and nome not in tx:
                        tx[nome], a = _valor(proj, prm, None)
                        tx["animado"] = tx["animado"] or a
                self.texto = tx
                continue
            if mn == "AE.ADBE Graphic Group":
                # O Vector Motion: transforma a camada inteira em volta do SEU ponto de âncora
                # (0,5:0,5 = o centro do quadro) — a escala mexe no corpo E na posição do texto.
                for prm in proj.refs(comp, "Param"):
                    nome = proj.campo(prm, "Name")
                    if nome not in ("Scale", "Position", "Anchor Point"):
                        continue
                    v, a = _valor(proj, prm, None)
                    kfs = proj.campo(prm, "Keyframes")
                    if kfs:          # o valor do 1º keyframe é o do início do título
                        v = kfs.split(";")[0].split(",")[1]
                    chave = {"Scale": "__grupo_escala", "Position": "__grupo_posicao",
                             "Anchor Point": "__grupo_ancora"}[nome]
                    self.estatico[chave] = v
                    if nome == "Scale" and kfs:
                        # a escala animada vira o Zoom animado do clipe (`_titulo_resolve`):
                        # `[(ticks da MÍDIA do item, %)]`, o domínio do `InPoint`
                        self.grupo_escala_kf = sorted(
                            (int(k.split(",")[0]), float(k.split(",")[1])) for k in kfs.split(";")
                            if k.count(",") >= 1 and k.split(",")[0].lstrip("-").isdigit())
                        self.grupo_curva = any(len(k.split(",")) > 2 and k.split(",")[2] not in ("0", "")
                                               for k in kfs.split(";"))
                    elif kfs:
                        self.estatico["__grupo_animado"] = True
                continue
            if mn == "AE.ADBE PPro Metadata":
                self.burnin = _ler_burnin(proj, comp, self.crop_aviso)
                continue
            if mn == "AE.ADBE Horizontal Flip":
                self.flip[0] = not self.flip[0]
                continue
            if mn == "AE.ADBE Vertical Flip":
                self.flip[1] = not self.flip[1]
                continue
            if mn == "AE.ADBE Black & White":
                # Black & White → um nó de cor com SATURAÇÃO 0 (`SetCDL` depois do import, junto das LUTs). Decisão do
                # autor (2026-10-10): "ao menos temporariamente" — a fórmula de luminância do Premiere não foi medida.
                self.pb = True
                continue
            if mn == "AE.ADBE Legacy Key Luma":
                # chave de luminância sobre fundo preto (VFX de disparo): o Resolve não tem a
                # chave na Edit; a composição Screen dá o mesmo efeito visual nesse caso.
                self.luma_key = True
                continue
            if mn == "AE.ADBE Opacity" and proj.refs(comp, "SubComponent"):
                # MÁSCARA DE OPACIDADE (`AE.ADBE AEMask` no 22/23): o plano só aparece dentro do
                # contorno (o wipe do véu, as composições). Antes ia CALADA para o lixo (a Opacidade
                # está em `_NAO_EFEITO`) — R04 PRODUCAO-C, 12 máscaras, 2026-10-10. Vira Polygon
                # no EffectMask do MediaIn no Fusion, como o Crop com máscara, contorno animado.
                ms = _mascaras_ou_nada(proj, comp)
                if ms:
                    self.fusion.append(("opacidade", ms, {}))
                else:
                    self.crop_aviso.append("máscara de opacidade ilegível: não traduzida, refazer")
                    self.efeitos.append("máscara de opacidade (ilegível)")
                continue
            if mn == "AE.ADBE AECrop" and proj.refs(comp, "SubComponent"):
                # Crop com MÁSCARA (`AE.ADBE AEMask2`): é composição — o crop sozinho esconderia
                # o plano inteiro. Vira Polygon como EffectMask do MediaIn no Fusion, aplicado
                # depois do import (`drp/fusion_clipe.py`). O Motion fica na Edit.
                ms = _mascaras_ou_nada(proj, comp)
                if ms:
                    self.fusion.append(("recorte", ms, {}))
                else:
                    self.crop_aviso.append("crop com máscara ilegível: não traduzido, refazer")
                    self.efeitos.append("crop com máscara (ilegível)")
                continue
            if mn == "AE.ADBE Basic 3D":
                # Swivel (giro no eixo vertical) e Tilt (no horizontal), graus. Vira Corner
                # Positioner no Fusion (`drp/fusion_clipe.py`), na ordem da pilha de efeitos.
                prm = {}
                for x in proj.refs(comp, "Param"):
                    v, animado = _valor(proj, x, None)
                    prm[proj.campo(x, "Name")] = v
                    if animado:
                        self.crop_aviso.append(f"Basic 3D com {proj.campo(x, 'Name')} animado: "
                                               "usado o valor fixo")
                if (_float(prm.get("Distance to Image"), 0.0) or 0.0) != 0.0:
                    # a distância da câmera muda a perspectiva; só a padrão (0) foi medida
                    self.crop_aviso.append("Basic 3D com Distance to Image: perspectiva não calibrada")
                if (prm.get("Specular Highlight") or "").lower() == "true":
                    self.crop_aviso.append("Basic 3D com Specular Highlight: brilho não traduzido")
                sw = _float(prm.get("Swivel"), 0.0) or 0.0
                ti = _float(prm.get("Tilt"), 0.0) or 0.0
                if sw or ti:
                    self.fusion.append(("basic3d", [], {"swivel": sw, "tilt": ti}))
                continue
            if mn == "AE.ADBE Gaussian Blur 2":
                # Gaussian Blur (Legacy): Blurriness (px), Blur Dimensions (0 = as duas, 1 =
                # horizontal, 2 = vertical), Repeat Edge Pixels. Com máscara = só dentro dela.
                prm = {}
                for i, x in enumerate(proj.refs(comp, "Param")):
                    v, animado = _valor(proj, x, None)
                    nome = "Repeat Edge Pixels" if i == 2 else proj.campo(x, "Name")  # sem nome
                    prm[nome] = v
                    if animado:
                        self.crop_aviso.append(f"blur com {nome} animado: usado o valor fixo")
                ms = _mascaras_ou_nada(proj, comp)
                if ms is None:
                    # máscara que não se lê: desfocar o quadro INTEIRO seria pior que não desfocar
                    self.crop_aviso.append("blur com máscara ilegível: não traduzido, refazer")
                    self.efeitos.append("Gaussian Blur com máscara (ilegível)")
                    continue
                self.fusion.append(("desfoque", ms, {
                    "px": _float(prm.get("Blurriness"), 0.0) or 0.0,
                    "direcao": _int(prm.get("Blur Dimensions"), 0),
                    "repetir_bordas": (prm.get("Repeat Edge Pixels") or "").lower() == "true"}))
                continue
            if mn == "AE.ADBE AECrop":
                for prm in proj.refs(comp, "Param"):
                    nome = proj.campo(prm, "Name")
                    v, animado = _valor(proj, prm, None)
                    lado = {"Left": "l", "Top": "t", "Right": "r", "Bottom": "b"}.get(nome)
                    if lado:
                        self.crop[lado] = max(self.crop[lado], (_float(v, 0.0) or 0.0) / 100.0)
                        if animado:
                            self.crop_aviso.append("crop animado: usado o valor fixo")
                    elif nome == " " and (v or "").lower() == "true":
                        self.crop_aviso.append("crop com Zoom ligado: não traduzido")
                    elif nome == "Edge Feather" and (_float(v, 0.0) or 0.0) > 0:
                        # borda suave em PIXELS do quadro do item → Softness do Cropping
                        self.crop_suave = max(getattr(self, "crop_suave", 0.0), _float(v, 0.0))
                continue
            if mn == "AE.ADBE Lumetri":
                # a cor da Lumetri vai como LUT no nó do clipe (`lut_composta`): curvas RGB + o look; o que não traduz
                # (temperatura, curvas de saturação) segue como aviso. Na camada de AJUSTE, só o look (`self.lut`).
                cor = _lumetri_cor(proj, comp)
                self.lut = cor["lut"] or self.lut
                self.cor.append(cor)
                continue
            if mn == "AE.ADBE Motion":
                for prm in proj.refs(comp, "Param"):
                    nome = proj.campo(prm, "Name")
                    # o parâmetro 2 se chama "Scale" com a escala uniforme e "Scale Height" com o
                    # Uniform Scale desligado (o 23.2 renomeia ao salvar — R04, 2026-10-10)
                    if nome == "Scale Height":
                        nome = "Scale"
                    self.estatico[nome], _ = _valor(proj, prm, None)
                    lado = {"Crop Left": "l", "Crop Top": "t", "Crop Right": "r",
                            "Crop Bottom": "b"}.get(nome)
                    if lado:
                        self.crop[lado] = max(self.crop[lado],
                                              (_float(self.estatico[nome], 0.0) or 0.0) / 100.0)
                    kfs = proj.campo(prm, "Keyframes")
                    pts = []
                    for k in (kfs or "").split(";"):
                        partes = k.split(",")
                        if len(partes) >= 2 and partes[0].lstrip("-").isdigit():
                            pts.append((int(partes[0]), partes[1]))
                            self.campos.setdefault(nome, {})[int(partes[0])] = partes
                            if len(partes) > 2 and partes[2] not in ("0", ""):
                                self.curva = True
                    if pts:
                        self.pontos[nome] = sorted(pts)
            elif mn not in _NAO_EFEITO:
                self.efeitos.append(proj.campo(comp, "DisplayName") or mn)
        # ⛔⛔ O Premiere RENDERIZA a cadeia do ÚLTIMO índice do arquivo para o PRIMEIRO. MEDIDO 2026-11-20 (carta B24,
        # 26.5.2, `laboratorio-de-midia/lab/cor_b24_premiere_duas_lumetri.py`): duas Lumetris com curvas que não comutam,
        # prever na ordem do arquivo erra 24 códigos, na inversa 0,16–0,19; ProcAmp + Lumetri, o mesmo. A cor do item
        # (Lumetri, página Color) é composta na ordem do RENDER.
        self.cor.reverse()
        # E o FUSION, que encadeia os nós na ordem da lista (`drp/fusion_clipe.plano`): MEDIDO 2026-11-20 (26.5.2,
        # `laboratorio-de-midia/lab/premiere_ordem_fusion.py`): Gaussian Blur + Basic 3D (Swivel 65°) — arquivo [Basic 3D,
        # Blur] sai nítido (desfocou ANTES de girar), [Blur, Basic 3D] sai borrado (girou antes). A Opacidade é à parte
        # (o `plano` a põe sempre no fim).
        self.fusion.reverse()

    @property
    def animado(self) -> bool:
        return bool(self.pontos)

    def tempos(self) -> list[int]:
        return sorted({t for pts in self.pontos.values() for t, _v in pts})

    def em(self, t_midia: float) -> dict:
        out = dict(self.estatico)
        for nome, pts in self.pontos.items():
            if t_midia <= pts[0][0]:
                out[nome] = pts[0][1]
            elif t_midia >= pts[-1][0]:
                out[nome] = pts[-1][1]
            else:
                for (ta, va), (tb, vb) in zip(pts, pts[1:]):
                    if ta <= t_midia <= tb:
                        cs = self.campos.get(nome) or {}
                        bz = _bezier_trecho(ta, va, cs.get(ta), tb, vb, cs.get(tb), t_midia)
                        out[nome] = bz if bz is not None else _interp(va, vb, (t_midia - ta) / (tb - ta) if tb > ta else 0.0)
                        break
        return out


def _geo_do_item(params: dict, fonte: tuple[int, int], quadro: tuple[int, int],
                 escalar_ao_quadro: bool) -> Geo:
    """Motion de UM item → Geo da fonte (px) no quadro do contêiner (px)."""
    fw, fh = fonte
    qw, qh = quadro
    base = min(qw / fw, qh / fh) if (escalar_ao_quadro and fw and fh) else 1.0
    esc = (_float(params.get("Scale"), 100.0) or 0.0) / 100.0
    asp = 1.0
    if (params.get(" ") or "").strip().lower() in ("false", "0") and params.get("Scale Width"):
        # escala NÃO uniforme (Uniform Scale desligado): o Scale é a ALTURA e o Scale Width a largura
        larg = (_float(params.get("Scale Width"), 100.0) or 0.0) / 100.0
        asp = larg / esc if esc else 1.0
    esc *= base
    rot = _float(params.get("Rotation"), 0.0) or 0.0
    px, py = _ponto(params.get("Position"), (0.5, 0.5))
    ax, ay = _ponto(params.get("Anchor Point"), (0.5, 0.5))
    # centro da fonte relativo à âncora, em px da fonte, escalado e girado
    dx, dy = (0.5 - ax) * fw * esc * asp, (0.5 - ay) * fh * esc
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    tx = (px - 0.5) * qw + c * dx - s * dy
    ty = (py - 0.5) * qh + s * dx + c * dy
    return Geo(esc, rot, tx, ty, asp)


def _crop_para_fonte(crop: dict, g: "Geo", quadro_take: tuple[int, int],
                     fonte: tuple[int, int], crop_fonte: dict) -> tuple[dict, str | None]:
    """Retângulo de crop no quadro do TAKE (frações por borda) → frações na FONTE do clipe, pela
    inversa da geometria de dentro do take (`g`: fonte → take). Somado ao crop da própria fonte
    (vale o maior por borda). Rotação dentro do take não é invertida (aviso)."""
    qw, qh = quadro_take
    fw, fh = fonte
    if not (qw and qh and fw and fh and g.esc):
        return dict(crop_fonte), "crop num plano aninhado: quadro desconhecido, não traduzido"
    # bordas do retângulo visível no take, em px a partir do centro (Y para baixo)
    xl = (crop["l"] - 0.5) * qw
    xr = (0.5 - crop["r"]) * qw
    yt = (crop["t"] - 0.5) * qh
    yb = (0.5 - crop["b"]) * qh
    # para a fonte: (p − t) / esc, em px a partir do centro da fonte (a largura com a proporção)
    fl, fr = (xl - g.tx) / (g.esc * g.asp), (xr - g.tx) / (g.esc * g.asp)
    ft, fb = (yt - g.ty) / g.esc, (yb - g.ty) / g.esc
    novo = {"l": fl / fw + 0.5, "r": 0.5 - fr / fw, "t": ft / fh + 0.5, "b": 0.5 - fb / fh}
    out = {k: min(1.0, max(0.0, max(novo[k], crop_fonte.get(k, 0.0)))) for k in novo}
    return out, ("crop num plano aninhado com rotação dentro do take: aproximado"
                 if abs(g.rot) > 1e-3 else None)


def _ponto(v: str | None, padrao: tuple[float, float]) -> tuple[float, float]:
    if not v or ":" not in v:
        return padrao
    try:
        x, y = v.split(":")[:2]
        return float(x), float(y)
    except ValueError:
        return padrao


def _retangulo(v: str | None) -> tuple[int, int]:
    if not v:
        return (0, 0)
    p = [_int(x) for x in v.split(",")]
    return (p[2] - p[0], p[3] - p[1]) if len(p) == 4 else (0, 0)


# ── a sequência ────────────────────────────────────────────────────────────

class Leitor:
    def __init__(self, proj: Projeto, taxas: dict[str, float] | None = None):
        self.p = proj
        # {FilePath do projeto: taxa do arquivo que a timeline vai APONTAR}: o projeto conta a fonte em ticks
        # (tempo); a taxa só converte tempo em quadro, e tem de ser a do arquivo de verdade. R04, 2026-10-18: o
        # .prproj de 2023 declara os MP4 de 100p da Sony e a pasta tem os proxies de 60p — a entrada em quadros
        # de 100 num arquivo de 60 punha 40 planos fora do ponto (o mesmo corte, em segundos, do resgatado).
        self.taxas = dict(taxas or {})
        # ⚠️ O Premiere aceita sequências com o MESMO nome (em bins diferentes, ou uma montagem com o
        # nome de um take). Um dicionário por nome ficava com a última e escondia as outras (revisão
        # de código, 2026-10-03): a identidade é o `ObjectUID`; o nome é só para mostrar.
        self._todas = list(proj.de_tipo("Sequence"))
        self._por_uid = {s.uid: s for s in self._todas if s.uid}

    # -- inventário ---------------------------------------------------------
    def eh_multicam(self, s: Obj) -> bool:
        """Sequência MULTICAM (a fonte de ângulos), não nest. O `<IsMulticam>` do clipe NÃO serve:
        o multicam desligado vem sem ele (505 takes do PRODUCAO_B). A chave abaixo existe nas 280
        sequências multicam e em nenhum nest, merged ou timeline de montagem (medido 2026-10-04,
        Premiere 26.0.2 — banco `protocolos/prproj/relink-e-geometria.md` §10.5)."""
        return "<Source.Monitor.Multicam.SwitchOnMulticamName>" in self.p.corpo(s)

    def nest_do_item(self, item: Obj) -> Obj | None:
        """A sequência de um item que é NEST de verdade (composição do editor): nem multicam (o
        take, achatado na câmera escolhida) nem merged clip. Nest vira Compound Clip no Resolve
        (decisão do autor, 2026-10-04)."""
        p = self.p
        vc = self._clip(item)
        fonte = p.ref(vc, "Source") if vc is not None else None
        if fonte is None or fonte.tag != "VideoSequenceSource" or p.campo(vc, "IsMulticam") == "true":
            return None
        seq = p.ref(fonte, "Sequence")
        if seq is None or self.eh_multicam(seq) or self.eh_merged(seq):
            return None
        return seq

    def escalar_ao_quadro_por_midia(self) -> dict[str, tuple[int, int]]:
        """`{FilePath: (usos com "Scale to Frame Size", usos sem)}` em TODAS as sequências. Com a política
        (`ScaleToFramePolicy=1` no `VideoClip`), o Premiere reencaixa sozinho o arquivo novo quando o relink troca o
        raster; sem ela (nenhum, "Fit to frame", "Fill frame"), o número fica e vale nos pixels do arquivo novo.
        Medido no laboratório B24 (Premiere 26.5.2 Windows, 2026-10-29, `changeMediaPath`): HD → UHD com a política
        fica igual (0,997) e sem ela muda (0,009); 2K scope → HD com a política passa a cobrir o quadro."""
        p, fora = self.p, {}
        for s in self._todas:
            for _t, itens in self.trilhas(s, "Video"):
                for it in itens:
                    sc = p.ref(it, "SubClip") if it.tag == "VideoClipTrackItem" else None
                    vc = p.ref(sc, "Clip") if sc is not None else None
                    fonte = p.ref(vc, "Source") if vc is not None else None
                    media = p.ref(fonte, "Media") if fonte is not None and fonte.tag == "VideoMediaSource" else None
                    caminho = p.campo(media, "FilePath") if media is not None else None
                    if not caminho:
                        continue
                    com, sem = fora.get(caminho, (0, 0))
                    fora[caminho] = (com + 1, sem) if p.campo(vc, "ScaleToFramePolicy") == "1" else (com, sem + 1)
        return fora

    def eh_merged(self, s: Obj) -> bool:
        return "<BE.Sequence.IsMergedClip>true</BE.Sequence.IsMergedClip>" in self.p.corpo(s)

    def trilhas(self, s: Obj, tipo: str = "Video") -> list[tuple[Obj, list[Obj]]]:
        for g in self.p.refs(s, "Second"):
            if g.tag == tipo + "TrackGroup":
                return [(t, self.p.refs(t, "TrackItem")) for t in self.p.refs(g, "Track")]
        return []

    def quadro(self, s: Obj) -> tuple[tuple[int, int], int]:
        """((largura, altura), ticks por quadro) da sequência."""
        for g in self.p.refs(s, "Second"):
            if g.tag == "VideoTrackGroup":
                return _retangulo(self.p.campo(g, "FrameRect")), _int(self.p.campo(g, "FrameRate"))
        return (0, 0), 0

    def sequencias_de_montagem(self) -> list[dict]:
        """As sequências que um editor escolheria: sem merged e sem take (sequência com um só
        plano de vídeo, como as multicam de uma câmera usadas como subclipe)."""
        out = []
        for s in self._todas:
            nome = self.p.nome_da_sequencia(s)
            if self.eh_merged(s):
                continue
            n = sum(1 for _t, its in self.trilhas(s) for i in its if i.tag == "VideoClipTrackItem")
            if n <= 1:
                continue
            (w, h), tpf = self.quadro(s)
            fim = max((_int(self.p.campo(i, "End")) for _t, its in self.trilhas(s) for i in its),
                      default=0)
            out.append({"uid": s.uid, "nome": nome, "planos": n, "largura": w, "altura": h,
                        "fps": TPS / tpf if tpf else None,
                        "duracao_s": fim / TPS})
        return sorted(out, key=lambda d: d["nome"].lower())

    # -- descida até o arquivo ----------------------------------------------
    def _clip(self, item: Obj) -> Obj | None:
        sc = self.p.ref(item, "SubClip")
        return self.p.ref(sc, "Clip") if sc else None

    def _folhas(self, item: Obj, t0: int, t1: int, quadro: tuple[int, int], prof: int,
                avisos: list, tpf_c: int = 0) -> list[dict]:
        """Folhas (arquivo) de `item` no intervalo [t0, t1) do CONTÊINER do item. Tempos e
        geometria devolvidos no domínio do contêiner."""
        p = self.p
        vc = self._clip(item)
        if vc is None:
            return []
        ini = _int(p.campo(item, "Start"))
        entrada = _int(p.campo(vc, "InPoint"))
        vel = _float(p.campo(vc, "PlaybackSpeed"), 1.0) or 1.0
        if vel < 0:
            avisos.append("velocidade reversa: lida como direta")
            vel = abs(vel)
        # RAMPA (Time Remapping): o InPoint e o tempo do item passam a ser o tempo do CLIPE; a FONTE vem da
        # curva (`_remap_fonte`). A `PlaybackSpeed` VALE: o tempo do clipe anda a `vel` por quadro da timeline.
        # ⛔ CORRIGE (2026-10-10, R04 contra a referência fechada, cada quadro casado com o da mídia): o LOU_7292
        # (1,2× E rampa, trecho de inclinação 1) anda 3,003 quadros da fonte de 60 qps por quadro = 1,2 × 2,5025, e
        # começa no piso do In (abaixo). A leitura antiga ("o Premiere mostra a curva pura") veio de stills a olho.
        remap = _remap_do_clipe(p, vc)
        # REVERSO: `<PlayBackwards>true</PlayBackwards>` no `<Clip>`, com a velocidade POSITIVA.
        # Medido 2026-10-02 (PRODUCAO_B, abertura, M002C022 a 0,7× para trás) contra o export: a
        # fonte no instante t é (duração − 1 quadro) − InPoint − (t − Start) × velocidade, ou
        # seja, o InPoint/OutPoint do Premiere contam a partir do FIM da mídia.
        para_tras = p.campo(vc, "PlayBackwards") == "true"

        # ENCAIXE DO IN (2026-10-10, laboratório B16 + R04): o clipe começa num quadro INTEIRO do tempo do clipe.
        # ⭐ DENTRO de um nest: pelo PISO — (piso(In ÷ (v × quadro)) + k) × v. Medido pelo número do quadro desenhado (clipe a
        # 466,67 % com In ÷ v = 5,14 dentro de nest a 1×: o Premiere toca de 5 quadros de clipe) e confirmado no R04: o
        # "poste" (LOU_7310 a 466,67 % dentro do nest, In ÷ v = 273,43) 0,69/0,82/0,59 → 0,87/0,89/0,73, nada piorou.
        # ⭐ Clipe SOLTO (na timeline de cima): também pelo PISO (2026-10-10, R04 contra a referência fechada, cada quadro
        # casado com o quadro da MÍDIA): 8 clipes acelerados de 1,1× a 10× com In ÷ passo fracionário (0,08–0,79) — o
        # Premiere mostra piso(In ÷ passo) × passo em todos. O Resolve ARREDONDA o In ÷ passo: com fração ≥ 0,5 saía um
        # quadro de saída adiantado (147, 158, 271, LOU_7308). O teto, tentado antes, piorou 19 pontos.
        if tpf_c and vel > 0 and p.campo(vc, "PlayBackwards") != "true":
            passo = vel * tpf_c
            entrada = math.floor(entrada / passo + 1e-6) * passo

        def u(t):                       # tempo da fonte do item no instante t do contêiner
            return entrada + (t - ini) * vel
        fonte = p.ref(vc, "Source")
        if fonte is None:
            return []
        stf = p.campo(vc, "ScaleToFramePolicy") == "1"
        mo = Motion(p, item)
        efeitos = mo.efeitos
        if mo.curva:
            avisos.append("keyframe com curva (Bézier): aproximado como linear")
        avisos.extend(mo.crop_aviso)
        # keyframes deste item, levados ao tempo do CONTÊINER
        kf_c = [ini + (km - entrada) / vel for km in mo.tempos()]
        if remap and mo.animado:
            # ⛔ MEDIDO 2026-10-10 (R04, drone A031 com rampa e rotação): num clipe com Time Remapping o
            # keyframe de EFEITO está no tempo da FONTE (Rotation em 40,1 s e 45,9 s, dentro do trecho
            # 39,9–45,8 s da fonte que o plano mostra). O Motion é avaliado na fonte de cada instante e
            # o `_segmento` amostra quadro a quadro (a marca abaixo só diz "tem animação").
            kf_c = [t0, t1]

        if fonte.tag == "VideoMediaSource":
            media = p.ref(fonte, "Media")
            if media is None:
                return []
            vs = p.ref(media, "VideoStream")
            tam = _retangulo(p.campo(vs, "FrameRect")) if vs else (0, 0)
            tpf_m = _int(p.campo(vs, "FrameRate")) if vs else 0
            taxa_real = self.taxas.get(p.campo(media, "FilePath") or "")
            if taxa_real:
                tpf_m = round(TPS / taxa_real)
            # `MediaSource › Content › ProxyMedia`: o proxy que o Premiere anexou a este original
            anexado = p.ref(fonte, "ProxyMedia")
            vs_anexado = p.ref(anexado, "VideoStream") if anexado is not None else None
            anexado_px = _retangulo(p.campo(vs_anexado, "FrameRect")) if vs_anexado is not None else None
            def u_mo(t, u=u):          # o tempo em que o Motion é avaliado (a FONTE, numa rampa)
                return _remap_fonte(remap, u(t) / TPS) * TPS if remap else u(t)

            def geo_fn(t, mo=mo, tam=tam, quadro=quadro, stf=stf, u_mo=u_mo):
                return _geo_do_item(mo.em(u_mo(t)), tam, quadro, stf)
            sentido, src0 = 1, u(t0)
            if para_tras:
                dur_m = _int(p.campo(vs, "Duration")) if vs else 0
                sentido = -1
                src0 = (dur_m - tpf_m) - entrada - (t0 - ini) * vel
                if mo.animado:
                    avisos.append("plano reverso com keyframe: tempo dos keyframes a conferir")
            return [{"t0": t0, "t1": t1, "media": media, "src_in": round(src0), "vel": vel,
                     "sentido": sentido,
                     "geo": geo_fn(t0), "geo_fn": geo_fn, "kf": kf_c, "curva": mo.curva,
                     "fonte_px": tam, "tpf_midia": tpf_m, "anexado_px": anexado_px,
                     "parado": bool(vs) and p.campo(vs, "IsStill") == "true"
                               and p.campo(media, "FilePath", ) is not None
                               and not _e_video(p.campo(media, "FilePath")),
                     "efeitos": efeitos, "escalar_ao_quadro": stf, "crop": dict(mo.crop),
                     "crop_suave": mo.crop_suave,
                     "flip": list(mo.flip), "luma_key": mo.luma_key, "pb": mo.pb,
                     "fusion": [_espelhar(receita(ef, ms, tam, avisos, **prm), mo.flip) for ef, ms, prm in mo.fusion],
                     # a FONTE (ticks da mídia) no instante T do contêiner, e, por receita do Fusion, o tempo em
                     # que o Premiere avalia a máscara (no domínio dos keyframes dela). Um nest por cima as
                     # recompõe (a grade de quadros do nest); o `_segmento` amostra quadro a quadro.
                     "fonte_em": u_mo, "tempo_fusion": [u_mo] * len(mo.fusion),
                     "texto": mo.texto, "burnin": mo.burnin,
                     "grupo_escala": mo.estatico.get("__grupo_escala"),
                     "grupo_posicao": mo.estatico.get("__grupo_posicao"),
                     "grupo_ancora": mo.estatico.get("__grupo_ancora"),
                     # no tempo do CONTÊINER, como o `kf`
                     "grupo_escala_kf": [(ini + (km - entrada) / vel, v)
                                         for km, v in mo.grupo_escala_kf],
                     "grupo_curva": mo.grupo_curva,
                     "grupo_animado": mo.estatico.get("__grupo_animado"),
                     # camada de AJUSTE (Black Video com `<AdjustmentLayer>true` no VideoClip):
                     # vira Adjustment Clip no Resolve; a LUT criativa da Lumetri vai no nó dele
                     "ajuste": p.campo(vc, "AdjustmentLayer") == "true", "lut": mo.lut,
                     "cor_master": _cor_do_master(p, item),
                     "cor": list(mo.cor),
                     # a curva do Time Remapping: [(tempo do clipe s, fonte s, tipo)] ou None
                     "remap": remap,
                     "retime": RETIME.get(p.campo(vc, "TimeInterpolationType"))}]

        if fonte.tag != "VideoSequenceSource":
            avisos.append(f"fonte de tipo {fonte.tag} ignorada")
            return []
        if remap:
            avisos.append("rampa de velocidade (Time Remapping) num nest: não traduzida, conferir")
        seq = p.ref(fonte, "Sequence")
        if seq is None or prof > 8:
            return []
        tam_q, _tpf = self.quadro(seq)
        trilhas = [(t, its) for t, its in self.trilhas(seq)]
        if p.campo(vc, "IsMulticam") == "true":
            k = _int(p.campo(vc, "SelectedTrackIndex"))
            trilhas = trilhas[k:k + 1]
        # Aninhamento de COMPOSIÇÃO (não multicam): TODAS as trilhas internas valem, cada uma
        # numa CAMADA (0 = a de baixo). O `ler` dá a cada camada a mais uma trilha própria no
        # Resolve, logo acima — a ordem de empilhamento do Premiere fica. Medido 2026-10-02:
        # C87_COMP_INTERFONE_2 do PRODUCAO_B (placa do interfone + insert por cima); antes só a
        # trilha de cima era lida e a placa sumia.
        multicam = p.campo(vc, "IsMulticam") == "true"
        if para_tras:
            avisos.append("sequência aninhada tocada para trás: não traduzido (lida como direta)")
        u0, u1 = u(t0), u(t1)
        out = []
        camada_base = 0
        for t, its in trilhas:
            if "<IsMuted>true</IsMuted>" in p.corpo(t):
                continue
            usou = 0
            for it in its:
                if it.tag != "VideoClipTrackItem" or "<IsMuted>true</IsMuted>" in p.corpo(it):
                    continue
                s_i = _int(p.campo(it, "Start"))
                e_i = _int(p.campo(it, "End"))
                a, b = max(u0, s_i), min(u1, e_i)
                if b <= a:
                    continue
                # de volta ao contêiner: t = ini + (u − entrada)/vel
                ta = round(ini + (a - entrada) / vel)
                tb = round(ini + (b - entrada) / vel)
                for f in self._folhas(it, a, b, tam_q, prof + 1, avisos, _tpf):
                    # tempos da folha estão no domínio do aninhado: traz para o contêiner
                    fa = round(ini + (f["t0"] - entrada) / vel)
                    fb = round(ini + (f["t1"] - entrada) / vel)
                    if f.get("retime") is None:
                        f["retime"] = RETIME.get(p.campo(vc, "TimeInterpolationType"))

                    # GRADE DO NEST (MEDIDO no laboratório, B16_NEST_MASCARA, 2026-10-10): o Premiere renderiza o
                    # conteúdo do nest nos quadros DELE — no instante T o nest está em u(T) e o de dentro anda pelo
                    # PISO na grade do nest, com a velocidade em float32 como no XML (3 × 4,6666665 = 13,99999 → o
                    # quadro 13: placa de 100 qps num nest a 466,67 % mostra 16/37/54/75…, não 19/38/58/77). A
                    # máscara do clipe de DENTRO vai junto (o tempo dele sai da grade); a do clipe do NEST, não.
                    def na_grade(T, u=u, tpf=_tpf):
                        n = u(T)
                        return math.floor(n / tpf + 1e-9) * tpf if tpf else n
                    if f.get("fonte_em") is not None:
                        f["fonte_em"] = lambda T, g=f["fonte_em"], q=na_grade: g(q(T))
                    f["tempo_fusion"] = [(lambda T, g=g, q=na_grade: g(q(T))) for g in f.get("tempo_fusion") or []]
                    if abs(vel - 1) > 1e-9 or (_tpf and abs(entrada / _tpf - round(entrada / _tpf)) > 1e-6):
                        # a fonte de cada quadro deixa de ser uma reta: vai pelo caminho da rampa (`_segmento`)
                        f["grade_nest"] = True

                    def tempo_do_nest(T, u=u, s0=f["src_in"], t0f=f["t0"], vf=f["vel"], rm=f.get("remap")):
                        # máscara no clipe do NEST: o Premiere a avalia no tempo CONTÍNUO do nest (B16: a imagem
                        # pelo piso, a máscara não), levado à mídia da folha como os keyframes dela
                        tf = s0 + (u(T) - t0f) * vf
                        return _remap_fonte(rm, tf / TPS) * TPS if rm else tf

                    def geo_c(t, dentro=f["geo_fn"], mo=mo, tam_q=tam_q, quadro=quadro,
                              stf=stf, u=u):
                        return _geo_do_item(mo.em(u(t)), tam_q, quadro, stf).apos(dentro(u(t)))
                    kf = kf_c + [ini + (k - entrada) / vel for k in f["kf"]]
                    f["curva"] = f.get("curva") or mo.curva
                    if any(v > 0 for v in mo.crop.values()):
                        # Crop no plano que aponta para o take: corta o QUADRO do take. O Cropping
                        # do Resolve corta a FONTE do clipe, então o retângulo volta para a fonte
                        # pela geometria de dentro do take (inversa). PRODUCAO_B 66-1-9 (2026-10-03).
                        f["crop"], aviso = _crop_para_fonte(mo.crop, f["geo_fn"](a), tam_q,
                                                            f["fonte_px"], f.get("crop") or {})
                        f["crop_suave"] = max(f.get("crop_suave") or 0.0, mo.crop_suave)
                        if aviso:
                            avisos.append(aviso)
                    f["flip"] = [f.get("flip", [False, False])[k] != mo.flip[k] for k in (0, 1)]
                    f["luma_key"] = f.get("luma_key") or mo.luma_key
                    f["pb"] = f.get("pb") or mo.pb          # Black & White no clipe do nest vale para o de dentro
                    for ef, ms, prm in mo.fusion:
                        if ef == "basic3d":
                            # a perspectiva vale para o QUADRO do take; só coincide com a da fonte
                            # de dentro quando o take mostra a fonte inteira, sem geometria
                            g = f["geo_fn"](a)
                            fw_d = f["fonte_px"][0]
                            if (abs(g.rot) < 1e-3 and abs(g.tx) < 0.5 and abs(g.ty) < 0.5
                                    and fw_d and abs(g.esc * g.asp * fw_d - tam_q[0]) < 1):
                                f["fusion"] = (f.get("fusion") or []) + [
                                    receita(ef, ms, f["fonte_px"], avisos, **prm)]
                                f["tempo_fusion"].append(tempo_do_nest)
                            else:
                                avisos.append("Basic 3D num plano aninhado: não traduzido, refazer")
                            continue
                        # Efeito no plano que aponta para o take: a máscara está no QUADRO do
                        # take; o Fusion trabalha na fonte de dentro (regra da casca: o efeito vale
                        # para a imagem vista, memória `efeito-vale-para-a-imagem-vista`).
                        r = receita(ef, ms, tam_q, avisos, **prm)
                        g = f["geo_fn"](a)

                        def dentro(vs, g=g):
                            return [[su, *map(list, x)] for su, *x in para_fonte_de_dentro(
                                [(su, tuple(v), tuple(i), tuple(o)) for su, v, i, o in vs],
                                g, tam_q, f["fonte_px"])]

                        def na_midia_de_dentro(tn, f=f):
                            # o tempo do NEST (o da mídia do clipe de fora) → o da mídia da folha
                            t_folha = f["src_in"] + (tn - f["t0"]) * f["vel"]
                            if f.get("remap"):
                                return _remap_fonte(f["remap"], t_folha / TPS) * TPS
                            return t_folha
                        for m in r["mascaras"]:
                            m["vertices"] = dentro(m["vertices"])
                            for qd in m.get("quadros") or []:
                                qd["vertices"] = dentro(qd["vertices"])
                                qd["t"] = na_midia_de_dentro(qd["t"])
                            m["suave_px"] /= g.esc or 1.0
                            m["expansao_px"] = m.get("expansao_px", 0.0) / (g.esc or 1.0)
                        if ef == "desfoque":
                            r["px"] /= g.esc or 1.0
                        r["fonte_px"] = list(f["fonte_px"])
                        # o flip de dentro E o deste clipe vêm ANTES desta máscara no Premiere (`_espelhar`)
                        _espelhar(r, f["flip"])
                        f["fusion"] = (f.get("fusion") or []) + [r]
                        f["tempo_fusion"].append(tempo_do_nest)
                    f.update(t0=max(ta, fa), t1=min(tb, fb), vel=f["vel"] * vel,
                             geo_fn=geo_c, geo=geo_c(max(ta, fa)), kf=kf,
                             efeitos=efeitos + f["efeitos"],
                             cor=(f.get("cor") or []) + mo.cor)      # a Lumetri do nest vem DEPOIS da de dentro
                    if not multicam:
                        f["camada"] = camada_base + f.get("camada", 0)
                        usou = max(usou, f.get("camada", 0) - camada_base + 1)
                    out.append(f)
            camada_base += usou
        return out

    # -- o ÁUDIO (2026-10-04) --------------------------------------------------
    def _canais(self, clip: Obj) -> list[int]:
        """Os canais do arquivo (0-based) que este clipe toca: `SecondaryContents ›
        SecondaryContentItem › SecondaryContent › ChannelIndex` (medido no PRODUCAO_B: 2.243 clipes
        mono, 293 estéreo). Sem a lista, o canal 0.
        ⛔ Mais o `StreamNumber` da mídia que o canal aponta (`Content › *MediaSource › Media`): o arquivo de 3+ canais
        ("N Mono") vira UMA mídia por canal, cada uma com o `ChannelIndex` 0 — sem somar o fluxo, os 5 canais de um WAV
        de 5 liam todos o canal 1 (medido no 26.0.2, 2026-11-25, B03 a 23,976; banco `prproj/escrita.md` §11o).
        ⛔ O fluxo começa na SOMA dos canais dos fluxos anteriores (`_inicio_do_fluxo`), não no número dele: num MOV com
        dois pares estéreo o 2º par é o canal 3-4 (contando o número, saía 2-3 — B03_PARES, 2026-11-25).
        ⛔ Canal SEM FONTE (`ChannelIndex` 2⁶⁴−1, ou sem `Content`) não toca nada e não vira trilha: o mono que sobra num
        MOV de pares o Premiere abre como clipe de 2 canais com o 2º mudo (medido no 26.0.2). Todos mudos = lista vazia."""
        p = self.p
        out, itens = [], re.findall(r'<SecondaryContentItem Index="\d+" ObjectRef="(\d+)"/>', p.corpo(clip))
        for oid in itens:
            sc = p.obj(oid)
            ci = _int(p.campo(sc, "ChannelIndex"), 0) if sc is not None else 0
            src = p.ref(sc, "Content") if sc is not None else None
            if src is None or ci >= 2 ** 32:
                continue
            m = re.search(r'<Media ObjectURef="([^"]+)"', p.corpo(src))
            med = p.obj(m.group(1)) if m else None
            out.append((self._inicio_do_fluxo(med) if med is not None else 0) + ci)
        return out if itens else [0]

    def _inicio_do_fluxo(self, med: Obj) -> int:
        """O canal (0-based) do ARQUIVO em que começa o fluxo de som desta mídia: a soma dos canais dos fluxos anteriores
        do mesmo arquivo (`FileKey`; cada fluxo é uma `Media` com o `StreamNumber`, e os canais dele são o
        `AudioStream › AudioChannelLayout`). Sem o layout de algum fluxo anterior (o offline que o Conformar escreve):
        um canal por fluxo — o "N Mono"."""
        p = self.p
        fluxo = _int(p.campo(med, "StreamNumber"), 0)
        if fluxo <= 0:
            return 0
        if getattr(self, "_fluxos", None) is None:
            self._fluxos: dict[str, dict[int, int]] = {}
            for m in p.de_tipo("Media"):
                au = p.ref(m, "AudioStream")
                lay = p.campo(au, "AudioChannelLayout") if au is not None else None
                if lay:
                    chave = p.campo(m, "FileKey") or p.campo(m, "FilePath") or ""
                    self._fluxos.setdefault(chave, {})[_int(p.campo(m, "StreamNumber"), 0)] = \
                        lay.count("channellabel") or 1
        larg = self._fluxos.get(p.campo(med, "FileKey") or p.campo(med, "FilePath") or "", {})
        if all(k in larg for k in range(fluxo)):
            return sum(larg[k] for k in range(fluxo))
        return fluxo

    def _folhas_audio(self, item: Obj, t0: int, t1: int, prof: int, avisos: list) -> list[dict]:
        """Folhas de áudio de `item` em [t0, t1) do contêiner: `{t0, t1, media, src_in, canais}`,
        com `canais` = os canais do ARQUIVO, um por canal do clipe. Num take aninhado
        (`AudioSequenceSource`), o canal N do clipe de fora é a trilha N de dentro — o áudio
        adaptativo do take (banco, `prproj/audio-adaptativo.md`): `inferido`."""
        p = self.p
        sc = p.ref(item, "SubClip")
        clip = p.ref(sc, "Clip") if sc else None
        if clip is None:
            return []
        ini = _int(p.campo(item, "Start"))
        entrada = _int(p.campo(clip, "InPoint"))
        vel = _float(p.campo(clip, "PlaybackSpeed"), 1.0) or 1.0
        fonte = p.ref(clip, "Source")
        # Velocidade CONSTANTE num arquivo de áudio: traduzida (o mapa de tempo do Resolve 19,
        # medido 2026-10-03). Num take aninhado ou negativa (reverso): não medido — 100% + aviso.
        aninhado = fonte is not None and fonte.tag != "AudioMediaSource"
        if abs(vel - 1.0) > 1e-6 and (vel < 0 or aninhado):
            avisos.append("áudio com velocidade mudada: entrou a 100%")
            vel = 1.0

        def u(t):
            return entrada + (t - ini) * vel
        canais = self._canais(clip)
        if fonte is None:
            return []
        if fonte.tag == "AudioMediaSource":
            media = p.ref(fonte, "Media")
            if media is None:
                return []
            return [{"t0": t0, "t1": t1, "media": media, "src_in": u(t0), "canais": canais, "vel": vel}]
        if fonte.tag != "AudioSequenceSource" or prof > 8:
            avisos.append(f"fonte de áudio {fonte.tag} ignorada")
            return []
        seq = p.ref(fonte, "Sequence")
        if seq is None:
            return []
        trilhas = self.trilhas(seq, "Audio")
        u0, u1 = u(t0), u(t1)
        out = []
        for k, c in enumerate(canais):
            if c >= len(trilhas):
                avisos.append("canal de take aninhado sem trilha correspondente: ignorado")
                continue
            trilha, its = trilhas[c]
            if "<IsMuted>true</IsMuted>" in p.corpo(trilha):
                continue
            for it in its:
                if it.tag != "AudioClipTrackItem" or "<IsMuted>true</IsMuted>" in p.corpo(it):
                    continue
                a, b = max(u0, _int(p.campo(it, "Start"))), min(u1, _int(p.campo(it, "End")))
                if b <= a:
                    continue
                for f in self._folhas_audio(it, a, b, prof + 1, avisos):
                    # tempos da folha no domínio do aninhado → contêiner; um canal por folha
                    f.update(t0=round(ini + (f["t0"] - entrada) / vel),
                             t1=round(ini + (f["t1"] - entrada) / vel), canais=f["canais"][:1],
                             pos=k)               # o k-ésimo canal do clipe de fora → sub-trilha k
                    out.append(f)
        return out

    def _audio(self, s: Obj, q, nominal: int, fps: float, avisos: dict) -> list[dict]:
        """Os segmentos de ÁUDIO da sequência. Trilha do Resolve = 1000 + índice (a convenção do
        caminho do Avid, que o writer já monta). Um clipe ESTÉREO do Premiere vira dois clipes
        mono em trilhas vizinhas (L e R), como no Avid: a trilha estéreo nativa do Resolve fica
        para medir. Efeitos de áudio não traduzem e NÃO viram marcador (decisão do autor,
        2026-10-04): vão para o resumo."""
        p = self.p
        trilhas = self.trilhas(s, "Audio")
        brutos, largura = [], {}
        for n, (trilha, itens) in enumerate(trilhas, start=1):
            desligada = "<IsMuted>true</IsMuted>" in p.corpo(trilha)
            for it in itens:
                if it.tag != "AudioClipTrackItem":
                    continue
                av: list[str] = []
                folhas = self._folhas_audio(it, _int(p.campo(it, "Start")), _int(p.campo(it, "End")),
                                            0, av)
                for x in av:
                    avisos[x] = avisos.get(x, 0) + 1
                sc = p.ref(it, "SubClip")
                clip = p.ref(sc, "Clip") if sc else None
                nc = len(self._canais(clip)) if clip is not None else 1
                largura[n] = max(largura.get(n, 1), nc)
                brutos.append((n, it, folhas, desligada or "<IsMuted>true</IsMuted>" in p.corpo(it)))
        # ⭐ IDA E VOLTA (autor, 2026-11-25: "tudo mono no Avid"): o par A1/A2 do Avid vira UM estéreo na A1 do Premiere e
        #   a A2 fica VAZIA (o lugar do R). Na volta, a trilha larga (estéreo = 2) já ocupa duas trilhas do Avid: a trilha
        #   inteiramente vazia logo abaixo dela é esse lugar, e não ganha outra (antes a volta tinha +1 trilha vazia por
        #   estéreo e empurrava as de baixo — medido na B03 a 23,976: 12 trilhas em vez de 10). A vazia que não segue um
        #   estéreo continua vazia (B051).
        base, prox, absorver = {}, 1000, 0
        for n, (_trilha, itens) in enumerate(trilhas, start=1):
            if not itens and absorver > 0:
                base[n] = prox - absorver
                absorver -= 1
                continue
            base[n] = prox
            prox += largura.get(n, 1)
            absorver = largura.get(n, 1) - 1
        tpf_tl = TPS / fps
        segs: list[dict] = []
        ocupado: dict[int, list] = {}
        for n, it, folhas, desligado in brutos:
            efeitos = []
            volume_db, volume_kf = None, []
            cad = p.ref(it, "Components")
            for c in (p.refs(cad, "Component") if cad is not None else []):
                mn = p.campo(c, "MatchName") or ""
                nome = p.campo(c, "DisplayName") or mn
                if p.campo(c, "Bypass") == "true":     # efeito desligado: não toca (como no vídeo, `Motion`)
                    continue
                if nome == "Volume":
                    volume_db = _volume_db(p, c, avisos)
                    volume_kf = _volume_kf(p, c)
                if mn and nome:
                    efeitos.append({"name": nome, "category": "audio", "reproducible": False,
                                    "params": {}})
            for f in folhas:
                a, b = q(f["t0"]), q(f["t1"])
                if b <= a:
                    continue
                caminho = p.campo(f["media"], "FilePath") or ""
                canais = f["canais"]
                for k, canal in enumerate(canais):
                    trilha = base[n] + (f["pos"] if "pos" in f else k)
                    segs.append({
                        "timeline_tc_in": frames_para_tc(a, nominal),
                        "timeline_tc_out": frames_para_tc(b, nominal), "duration_frames": b - a,
                        "source_start_frames": round(f["src_in"] / tpf_tl), "source_fps": fps,
                        "clip_name": caminho.rsplit("/", 1)[-1] or "?", "track": trilha,
                        "canal_arquivo": canal + 1,
                        "media_ref": {"mob_name": caminho.rsplit("/", 1)[-1], "url": "",
                                      "local_path": caminho, "descriptor_type": "prproj",
                                      # a duração que o PROJETO declara (`AudioStream › Duration`): a prova de que o
                                      # arquivo de mesmo nome achado noutra pasta é o mesmo som (B024, 2026-10-18)
                                      "dur_s": self._duracao_do_som(f["media"])},
                        "is_gap": False, "is_transition": False, "is_effect": False,
                        "is_audio": True, "disabled": desligado, "effects": efeitos,
                        # speed_ratio = timeline/fonte (50% → 2,0), a convenção do vídeo e do writer
                        "speed_ratio": 1.0 / f.get("vel", 1.0), "relative_speed": 1.0 / f.get("vel", 1.0),
                        "conform_ratio": 1.0, "phase_offset": 0, "motion_effect_type": None,
                        "has_motion_effect": abs(f.get("vel", 1.0) - 1.0) > 1e-6,
                        "source_offset_map": [], "speed_curve": [], "speed_keyframes": [],
                        **_volume_no_trecho(volume_db, volume_kf, f, a, b, tpf_tl, avisos),
                        "prproj": {"audio": True, "trilha_premiere": n}})
                    ocupado.setdefault(trilha, []).append((a, b))
        for n, (trilha, itens) in enumerate(trilhas, start=1):
            for it in itens:
                if "Transition" not in it.tag:
                    continue
                t = self._transicao(it, base[n], itens, q, nominal)
                for k in range(largura.get(n, 1)):
                    segs.append({**t, "track": base[n] + k, "is_audio": True})
        for trilha in sorted(ocupado):
            for g in _lacunas(ocupado[trilha], trilha, nominal, fps):
                segs.append({**g, "is_audio": True})
        return segs

    # -- a timeline ----------------------------------------------------------
    def sequencia(self, chave: str) -> Obj:
        """A sequência pelo `ObjectUID` (o que o painel manda) ou pelo NOME (a linha de comando).
        Nome repetido: vale a única de montagem entre elas; se ainda houver mais de uma, recusa —
        escolher uma ao acaso montaria a timeline errada."""
        if chave in self._por_uid:
            return self._por_uid[chave]
        mesmas = [s for s in self._todas if self.p.nome_da_sequencia(s) == chave]
        if len(mesmas) > 1:
            montagem = {x["uid"] for x in self.sequencias_de_montagem()}
            mesmas = [s for s in mesmas if s.uid in montagem] or mesmas
        if not mesmas:
            raise KeyError(f"sequência não encontrada: {chave}")
        if len(mesmas) > 1:
            raise ValueError(f"há {len(mesmas)} sequências de montagem chamadas {chave!r}: escolha "
                             "pela lista do painel")
        return mesmas[0]

    def ler(self, nome: str, audio: bool = True) -> dict:
        p = self.p
        s = self.sequencia(nome)
        nome = p.nome_da_sequencia(s)
        quadro, tpf = self.quadro(s)
        fps = TPS / tpf if tpf else 24.0
        nominal = round(fps)
        avisos: dict[str, int] = {}
        segs: list[dict] = []
        # ⛔ a página Color no nível SEQUENCE (Premiere 2027) mora no grupo de trilhas de vídeo, FORA dos clipes (sem isto a
        #   grade da sequência inteira sumia calada). Vai na LUT de CADA clipe, DEPOIS da grade do clipe — a ordem medida
        #   pelo pixel (Clip → Sequence, `lab/premiere27_ordem_sequence.py`). Decisão do autor (2026-11-20): nada de nó de
        #   timeline no Resolve enquanto a API não o criar (19.1.4: só com gesto na interface) — processo automatizado não
        #   depende do usuário.
        self._cor_da_sequencia = {"pagina_cor": [], "nao": [], "vinheta": []}
        for g in p.refs(s, "Second"):
            if g.tag != "VideoTrackGroup":
                continue
            cad = p.ref(g, "Components")
            for comp in (p.refs(cad, "Component") if cad is not None else []):
                if eh_pagina_cor(comp):
                    pc = ler_pagina_cor(p, comp)
                    self._cor_da_sequencia["pagina_cor"] += pc["pagina_cor"]
                    self._cor_da_sequencia["nao"] += [f"{x} (nível Sequence)" for x in pc["nao"]]
                    self._cor_da_sequencia["vinheta"] += pc["vinheta"]
        if self._cor_da_sequencia["pagina_cor"]:
            avisos["página Color no nível SEQUENCE: a grade da sequência inteira vai na LUT de cada clipe, depois da do "
                   "clipe (o Resolve não cria nó de timeline pela API): conferir"] = 1

        def q(t):                       # ticks → quadro da timeline
            return round(t / tpf)

        brutos = []                              # (trilha do Premiere, item, folhas, avisos)
        for n_trilha, (trilha, itens) in enumerate(self.trilhas(s), start=1):
            for it in itens:
                if it.tag == "VideoClipTrackItem":
                    av: list[str] = []
                    brutos.append((n_trilha, it, self._folhas(it, _int(p.campo(it, "Start")),
                                                              _int(p.campo(it, "End")),
                                                              quadro, 0, av, tpf), av))
        camadas: dict[int, int] = {}
        for n_trilha, _it, folhas, _av in brutos:
            for f in folhas:
                camadas[n_trilha] = max(camadas.get(n_trilha, 0), f.get("camada", 0))
        base, prox = {}, 1
        for n in range(1, len(self.trilhas(s)) + 1):
            base[n] = prox
            prox += camadas.get(n, 0) + 1
        if any(camadas.values()):
            avisos["aninhamento com várias trilhas: cada camada ganhou uma trilha própria"] = \
                sum(1 for v in camadas.values() if v)
        folhas_do = {id(it): (folhas, av) for _n, it, folhas, av in brutos}

        for n_trilha, (trilha, itens) in enumerate(self.trilhas(s), start=1):
            desligada = "<IsMuted>true</IsMuted>" in p.corpo(trilha)
            ocupado: dict[int, list] = {}
            for it in itens:
                ini, fim = _int(p.campo(it, "Start")), _int(p.campo(it, "End"))
                if it.tag == "VideoTransitionTrackItem":
                    segs.append(self._transicao(it, base[n_trilha], itens, q, nominal))
                    continue
                if it.tag != "VideoClipTrackItem":
                    continue
                folhas, av = folhas_do[id(it)]
                # Clipe DESLIGADO (Enable desmarcado): `<IsMuted>true</IsMuted>` no
                # ClipTrackItem — não só a trilha. Medido no PRODUCAO_B (30B-2-2, 8 quadros).
                item_desligado = "<IsMuted>true</IsMuted>" in p.corpo(it)
                sc = p.ref(it, "SubClip")
                nome_plano = (p.campo(sc, "Name") if sc else None) or "?"
                # NEST (não multicam): as folhas dele, já achatadas em camadas, levam a marca do
                # item de fora — a casca as junta num Compound Clip DEPOIS do Fusion (a API não
                # alcança clipe dentro de compound; medido 2026-10-04, Resolve 21.1).
                nest = self.nest_do_item(it)
                composto = ({"id": f"{n_trilha}:{ini}", "nome": p.nome_da_sequencia(nest)}
                            if nest is not None else None)
                for f in folhas:
                    a, b = q(f["t0"]), q(f["t1"])
                    if b <= a:
                        continue
                    destino = base[n_trilha] + f.get("camada", 0)
                    seg = self._segmento(f, a, b, destino, nome_plano, nominal, fps, quadro, av)
                    seg["disabled"] = desligada or item_desligado
                    if composto:
                        seg["composto"] = dict(composto)
                    segs.append(seg)
                    ocupado.setdefault(destino, []).append((a, b))
                for x in av:
                    avisos[x] = avisos.get(x, 0) + 1
            for destino in sorted(set(ocupado) | {base[n_trilha]}):
                segs.extend(_lacunas(ocupado.get(destino, []), destino, nominal, fps))

        if audio:
            segs.extend(self._audio(s, q, nominal, fps, avisos))
        ref = _referencia_na_timeline(segs, nominal)
        if ref is not None:
            avisos[f"vídeo de referência achado na V{ref['track']}: {ref['clip_name']}"] = 1
        segs.sort(key=lambda d: (d["track"], d["timeline_tc_in"], not d["is_transition"]))
        # O TC de INÍCIO da sequência: `MZ.ZeroPoint` = o TC exibido na posição 0, em ticks (banco
        # `protocolos/prproj/escrita.md` §11). Ausente = 00:00:00:00 — o caso das timelines finais do
        # PRODUCAO_B, conferido pelo burn-in da referência (o quadro 119.280 mostra 01:22:50:00). O
        # Resolve começa a timeline nele: "respeitar o TC que veio da origem" (autor, 2026-10-04).
        m = re.search(r"<MZ\.ZeroPoint>(-?\d+)</MZ\.ZeroPoint>", p.corpo(s))
        inicio = max(0, round(int(m.group(1)) / tpf)) if (m and tpf) else 0
        # o `uid` (ObjectUID) é o que o `importSequences` do Premiere aceita; quem chamou pode ter pedido pelo NOME
        return {"nome": nome, "uid": s.uid, "fps": fps, "largura": quadro[0], "altura": quadro[1],
                "inicio": inicio,
                "premiere": p.versao(), "segmentos": segs,
                "avisos": [{"texto": k, "vezes": v} for k, v in sorted(avisos.items())]}

    def _duracao_do_som(self, media: Obj) -> float | None:
        aud = self.p.ref(media, "AudioStream")
        d = _int(self.p.campo(aud, "Duration")) if aud is not None else 0
        return d / TPS if d > 0 else None

    def _midia_no_projeto(self, media: Obj, fps_m: float, fw: int, fh: int) -> dict:
        """O que o PROJETO sabe do arquivo do proxy, sem abri-lo: a prova de identidade do casamento
        com o original quando o proxy não está nesta máquina (o colorista recebe o .prproj e os
        originais). `{dur_s, tc_quadros, fps, w, h, fourcc}`; o que não houver vem None.

        - `dur_s`: `Duration` do `VideoStream`, em ticks.
        - `tc_quadros`: o TC de início da mídia — `AlternateStart` ou `Start` do `Media`, em ticks de
          tempo REAL (banco, `prproj/relink-e-geometria.md` §6) → × a taxa da mídia = os quadros do TC.
          MEDIDO 2026-10-09 (Premiere 26, PRODUCAO_B A044C013): `Start` 56048,25 s × 24 = 1.345.158 =
          15:34:08:06, o TC do original. Sem TC (celular), não há o campo.
        - `fourcc`: `CodecType` do `VideoStream` (1212503619 = "HEVC", o celular; 1634755439 = "apco",
          o ProRes Proxy dos proxies ALEXA do PRODUCAO_B)."""
        p = self.p
        vs = p.ref(media, "VideoStream")
        dur = _int(p.campo(vs, "Duration")) if vs is not None else 0
        ini = p.campo(media, "AlternateStart") or p.campo(media, "Start")
        cod = _int(p.campo(vs, "CodecType")) if vs is not None else 0
        try:
            fourcc = cod.to_bytes(4, "big").decode("latin-1") if 0 < cod < 1 << 32 else None
        except (OverflowError, ValueError):
            fourcc = None
        return {"dur_s": dur / TPS if dur > 0 else None,
                "tc_quadros": round(_int(ini) / TPS * fps_m) if ini and str(ini).lstrip("-").isdigit() else None,
                "fps": fps_m, "w": fw or None, "h": fh or None, "fourcc": fourcc}

    def _segmento(self, f: dict, a: int, b: int, trilha: int, nome_plano: str, nominal: int,
                  fps_tl: float, quadro: tuple[int, int], av: list) -> dict:
        p = self.p
        media = f["media"]
        caminho = p.campo(media, "FilePath") or ""
        titulo = p.campo(media, "Title") or caminho.rsplit("/", 1)[-1]
        tpf_m = f["tpf_midia"] or round(TPS / fps_tl)
        fps_m = TPS / tpf_m
        sintetico = caminho.isdigit()            # Graphic, Black Video, Bars: sem arquivo
        geo: Geo = f["geo"]
        fw, fh = f["fonte_px"]
        qw, qh = quadro
        encaixe = min(qw / fw, qh / fh) if fw and fh else 1.0
        zoom = geo.esc / encaixe if encaixe else geo.esc
        # FONTE QUE NÃO ENCHE A ALTURA (letterbox no encaixe: o proxy 1024×540 num quadro 1920×1080 ocupa 1012,5 px): o Tilt
        # do Resolve anda em unidades da imagem ENCAIXADA, não do quadro. MEDIDO 2026-10-10 (R04, LOU_7254, render do Premiere
        # × o do Resolve, correlação de fase): Tilt 109 e 171 saíam 7 e 11 px abaixo — os dois 1080 ÷ 1012,5 = 1,0667 curtos.
        # ⏳ O caso espelhado (fonte mais estreita: Pan) não foi medido — não se aplica.
        fy = qh / (fh * encaixe) if fw and fh and qh and fh * encaixe < qh - 0.5 else 1.0

        def resolve_de(g: Geo) -> tuple[float, float, float, float, float]:
            """(zoom da largura, posX, posY, rotação, zoom da altura) do Resolve: zoom relativo ao
            encaixe, posição em FRAÇÃO do quadro com +Y para cima, rotação no sentido do Resolve."""
            zy = g.esc / encaixe if encaixe else g.esc
            return (zy * g.asp, g.tx / qw if qw else 0.0, -g.ty / qh * fy if qh else 0.0,
                    SINAL_ROTACAO_RESOLVE * g.rot, zy)
        params = {"scale_x": zoom * geo.asp, "scale_y": zoom,
                  "pos_x": geo.tx / qw * 1000.0 if qw else 0.0,
                  "pos_y": -geo.ty / qh * fy * 1000.0 if qh else 0.0,      # +Y para cima
                  "rot_z": SINAL_ROTACAO_RESOLVE * geo.rot}
        if any(f.get("flip") or []):
            params["flip_x"], params["flip_y"] = bool(f["flip"][0]), bool(f["flip"][1])
        if f.get("luma_key"):
            params["composite"] = "screen"
            av.append("Luma Key traduzido como composição Screen: conferir")
        crop = f.get("crop") or {}
        if any(v > 0 for v in crop.values()):
            params["crop_frac"] = {k: min(1.0, v) for k, v in crop.items()}
            if f.get("crop_suave"):
                # Edge Feather do Premiere (px do quadro do item) → Softness do Resolve.
                # `hipotese` de escala até a calibração pela imagem.
                params["crop_suave"] = f["crop_suave"] * SOFTNESS_POR_PX
        # ENQUADRAMENTO ANIMADO: um keyframe do Resolve em cada instante em que qualquer camada
        # (o plano, o take) tem keyframe, mais as duas pontas do plano.
        tempos = sorted({x for x in f.get("kf", []) if f["t0"] <= x <= f["t1"]})
        if tempos:
            tpf_tl = TPS / fps_tl
            razao = (fps_tl / fps_m) / f["vel"] if f["vel"] else 1.0     # = speed_ratio do writer
            pontos = sorted({f["t0"], *tempos, max(f["t0"], f["t1"] - tpf_tl)})
            if f.get("remap") or f.get("grade_nest") or f.get("curva"):
                # rampa com animação: um keyframe por QUADRO (o Motion anda no tempo da fonte)
                pontos = [f["t0"] + k * tpf_tl for k in range(max(1, round((f["t1"] - f["t0"]) / tpf_tl)))]
            elif any(abs((t - f["t0"]) / tpf_tl - round((t - f["t0"]) / tpf_tl)) > 1e-3 for t in tempos):
                # KEYFRAME FORA DA GRADE da timeline (in fora da grade, velocidade ≠ 1): o valor do instante exato ia para o
                # quadro ARREDONDADO e a animação saía adiantada/atrasada. MEDIDO 2026-10-11 (R04, JUL_7644 a 1,1× com in na
                # fração 0,09, Position andando ~128 px/quadro): +12 px no 121–123 = 0,09 quadro. Agora o valor de CADA
                # quadro, no trecho animado (do quadro antes do 1º keyframe ao depois do último) e nas pontas.
                n = max(1, round((f["t1"] - f["t0"]) / tpf_tl))
                k0 = max(0, math.floor((tempos[0] - f["t0"]) / tpf_tl) - 1)
                k1 = min(n - 1, math.ceil((tempos[-1] - f["t0"]) / tpf_tl) + 1)
                pontos = sorted({f["t0"], max(f["t0"], f["t1"] - tpf_tl)} | {f["t0"] + k * tpf_tl for k in range(k0, k1 + 1)})
            # "zoom" = a LARGURA e "zoom_y" = a altura (o writer: zoom_y ausente = o mesmo zoom)
            kf: dict[str, list] = {"zoom": [], "pos_x": [], "pos_y": [], "rot": [], "zoom_y": []}
            vistos = set()
            for t in pontos:
                # Tempo do keyframe do Resolve = o domínio do `In` do clipe: quadro da FONTE
                # (velocidade 1) ou fonte × razão de velocidade (o `In` do writer). Medido
                # 2026-10-02 com gabarito de 2 clipes (In 200, keyframes 0→100 × 200→300): só o de
                # 200→300 anima. ⚠️ Uma tentativa intermediária com "quadros desde o início do
                # clipe" estava ERRADA — o zoom do ovo foi para o valor final já no 1º quadro.
                # RAMPA (Time Remapping): o keyframe conta do INÍCIO do plano (quadro 0); o writer soma
                # o `In` do clipe na curva de tempo (a entrada da rampa, `_media_timemap`).
                base = 0 if (f.get("remap") or f.get("grade_nest")) else round(f["src_in"] / tpf_m * razao)
                q_src = base + round((t - f["t0"]) / tpf_tl)
                if q_src in vistos:
                    continue
                vistos.add(q_src)
                z, x, y, r, zy = resolve_de(f["geo_fn"](t))
                for nome, v in (("zoom", z), ("pos_x", x), ("pos_y", y), ("rot", r), ("zoom_y", zy)):
                    kf[nome].append((q_src, v))
            uniforme = all(abs(a[1] - b[1]) < 1e-9 for a, b in zip(kf["zoom"], kf["zoom_y"]))
            medidos = dict(kf)
            kf = {k: v for k, v in kf.items() if len(v) > 1
                  and max(x for _q, x in v) - min(x for _q, x in v) > 1e-6}
            if uniforme:
                kf.pop("zoom_y", None)
            elif "zoom" in kf or "zoom_y" in kf:
                # um eixo animado e o outro parado: os dois vão como keyframes (o writer anima X e Y)
                kf.setdefault("zoom", medidos["zoom"])
                kf.setdefault("zoom_y", medidos["zoom_y"])
            if kf:
                params["kf"] = kf
        efeitos = [{"name": "Motion", "category": "geometric", "reproducible": True,
                    "params": params}]
        tempos_fx = f.get("tempo_fusion") or []
        for i_r, r in enumerate(f.get("fusion") or []):
            # aplicado DEPOIS do import, pela API do Fusion (`drp/fusion_clipe.py`)
            tempo = tempos_fx[i_r] if i_r < len(tempos_fx) else None
            for m in r.get("mascaras") or []:
                qds = m.get("quadros") or []
                if (len(qds) > 1 and tempo is not None and f.get("fonte_em") is not None and tpf_m
                        and all("t" in q for q in qds)):
                    # CONTORNO ASSADO quadro a quadro (a regra do Avid; laboratório B16, 2026-10-10): em cada
                    # quadro da timeline, a forma que o Premiere mostra — interpolada entre os keyframes dele
                    # no tempo em que ELE avalia a máscara — vai no tempo da composição que o Resolve usa
                    # naquele quadro (o piso da fonte mostrada). Sem isto: velocidade quebrada, nest acelerado
                    # e in fora da grade erravam até 1 quadro da fonte de animação.
                    m["quadros"] = _assar_contorno(qds, tempo, f["fonte_em"], f["t0"], b - a, TPS / fps_tl, tpf_m)
                    m["vertices"] = m["quadros"][0]["vertices"] if m["quadros"] else m["vertices"]
                    continue
                for qd in qds:
                    if "quadro" not in qd:
                        # o tempo da composição do Fusion = quadro da FONTE, na taxa do arquivo, por
                        # PISO: o Resolve mostra no quadro k da timeline a composição em
                        # floor((In + k) × fps do arquivo ÷ fps da timeline), e o keyframe do Premiere
                        # fica no instante exato. MEDIDO (relógio no Polygon, R04 LOU_7310 100 qps
                        # em tempo real na timeline de 23,976, Resolve 19, 2026-10-10): 10685/10689/10694/10698 ×
                        # keyframes 10685,67/10689,85/10694,02/10698,19 — com `round` o 2º caía em
                        # 10690 e o Resolve mostrava a forma ANTES dele.
                        qd["quadro"] = math.floor(qd.pop("t") / TPS * fps_m + 1e-4)
            efeitos.append({"name": {"recorte": "Crop com máscara", "desfoque": "Gaussian Blur",
                                     "basic3d": "Basic 3D", "opacidade": "Máscara de opacidade"}[r["efeito"]] + " (Fusion)",
                            "category": "fusion", "reproducible": True, "params": r})
            av.append(f"{efeitos[-1]['name']}: composição do Fusion, conferir")
        if f.get("pb"):
            # nó de cor com saturação 0 no clipe, aplicado depois do import (o caminho das LUTs: `relatorio["luts"]`)
            efeitos.append({"name": "Black & White", "category": "cor", "reproducible": True,
                            "params": {"saturacao": 0.0}})
            av.append("Black & White → nó de cor com saturação 0 (aproximação): conferir")
        # A COR em uma LUT no nó 1 do clipe, depois do import (`relatorio["luts"]`, `lut_composta`), em ordem: a Input LUT da
        # Lumetri do MASTER CLIP (vale antes de tudo), depois cada Lumetri do item — o look e as curvas RGB. Na camada de
        # AJUSTE vai só o look dela (o caminho do Adjustment Clip, abaixo).
        etapas, nao, cor_ajuste, pagina_cor, vinhetas = [], [], False, False, []
        # o master clip vale ANTES do item (Source Clip Effect); numa camada de ajuste não há master clip de mídia
        for c in (f.get("cor_master") or []) + (f.get("cor") or []):
            if f.get("ajuste"):
                cor_ajuste = cor_ajuste or bool(c["curvas"] or c["nao"] or c.get("wb") or c.get("luma_sat") or c.get("sat_sat")
                                                or c.get("pagina_cor"))
                continue
            # a ordem DENTRO da Lumetri: Correção Básica (Input LUT, balanço de branco) → Creative (look) → Curvas → as
            # curvas de saturação
            entrada = c["lut"] if c["lut"] and c["lut"].get("tipo") == "entrada" else None
            if entrada:
                etapas.append(dict(entrada))
            if c.get("wb"):
                etapas.append({"wb": c["wb"]})
            if c["lut"] and not entrada:
                etapas.append(dict(c["lut"]))
            if c["curvas"]:
                etapas.append({"curvas": c["curvas"]})
            for k in ("luma_sat", "sat_sat"):
                if c.get(k):
                    etapas.append({k: c[k]})
            for g in c.get("pagina_cor") or []:
                etapas.append(g["lut"] if "lut" in g else {"pagina_cor": g})     # a camada LUT da página: o ITX3
                pagina_cor = True
            nao += [x for x in c["nao"] if x not in nao]
            vinhetas += c.get("vinheta") or []
        seq = getattr(self, "_cor_da_sequencia", None) or {}
        if not f.get("ajuste"):
            vinhetas += seq.get("vinheta") or []
        if not f.get("ajuste") and (seq.get("pagina_cor") or seq.get("nao")):
            # a grade do nível SEQUENCE, DEPOIS da do clipe (Clip → Sequence, medido)
            for g in seq.get("pagina_cor") or []:
                etapas.append(g["lut"] if "lut" in g else {"pagina_cor": g})     # a camada LUT da página: o ITX3
                pagina_cor = True
            nao += [x for x in seq.get("nao") or [] if x not in nao]
        if pagina_cor:
            av.append("página Color (Premiere 2027): o Color And Contrast vai na LUT do nó pelo modelo medido "
                      "(sequência Rec. 709): conferir")
        if etapas:
            nome = "LUT do master clip" if len(etapas) == 1 and etapas[0].get("itx3_b64") else                 "Página Color (LUT no nó)" if all(e.get("pagina_cor") for e in etapas) else "Lumetri (LUT no nó)"
            efeitos.append({"name": nome, "category": "lut", "reproducible": True, "params": {"etapas": etapas}})
            av.append("Lumetri: a LUT (Input LUT do master clip / look / curvas RGB) vai no nó do clipe: conferir")
        if vinhetas:
            # a VIGNETTE da página Color → o nó "Vinheta" (janela circular invertida + Gain) DEPOIS da LUT, no `.drx` do
            # clipe (`drp.cor_mc`, o pedido `vinheta`); mais de uma (clipe e sequência) = a última vai, com aviso
            efeitos.append({"name": "Vignette (Power Window)", "category": "vinheta", "reproducible": True,
                            "params": {"vinheta": vinhetas[-1]}})
            av.append("página Color: a Vignette vai num nó Vinheta (janela circular) do Resolve: conferir")
            if len(vinhetas) > 1:
                nao.append("página Color: mais de uma Vignette (só a última vai)")
        if nao:
            # o que vem da página Color já diz "página Color: …"; o resto é da Lumetri
            rotulo = "Cor" if all(x.startswith("página Color") for x in nao) else "Lumetri"
            efeitos.append({"name": f"{rotulo}: " + ", ".join(nao), "category": "other", "reproducible": False, "params": {}})
            av.append(f"{rotulo} sem tradução: " + ", ".join(nao))
        if cor_ajuste:
            av.append("camada de ajuste: as curvas/temperatura da Lumetri dela não vão (só o look)")
        lut = f.get("lut") if f.get("ajuste") else None
        if f.get("ajuste"):
            # CAMADA DE AJUSTE → Adjustment Clip do Resolve (`drp/writer.py::_ajustes_na_timeline`);
            # a LUT criativa da Lumetri vai no nó dele DEPOIS do import (o relatório leva o .cube)
            efeitos.append({"name": "Adjustment Clip", "category": "ajuste", "reproducible": True,
                            "params": {"lut": lut} if lut else {}})
            if lut:
                av.append("camada de ajuste com LUT da Lumetri: Adjustment Clip + a LUT no nó "
                          "(só o look criativo; o resto da Lumetri não vai)")
        for e in f["efeitos"]:
            efeitos.append({"name": e, "category": "other", "reproducible": False, "params": {}})
            av.append(f"efeito sem tradução: {e}")
        if f.get("burnin"):
            linhas_tc, outras = [], []
            for ln in f["burnin"]["linhas"]:
                simples = (ln["metadado"] == BURNIN_TC_TIMELINE and not ln["rotulo"]
                           and not ln["formato"] and not ln["exibicao"] and not ln["offset"]
                           and ln["tc_inicio"] is None)
                (linhas_tc if simples else outras).append(ln)
            if linhas_tc:
                efeitos.append({"name": "Metadata & Timecode Burn-in (Text+)", "category": "burnin",
                                "reproducible": True,
                                "params": {"size": f["burnin"]["size"], "opacidade": f["burnin"]["opacidade"],
                                           "linhas": linhas_tc}})
                av.append("burn-in do Premiere: TC da timeline em Text+ (vivo), conferir a posição")
            for ln in outras:
                efeitos.append({"name": "Metadata & Timecode Burn-in", "category": "other",
                                "reproducible": False, "params": {}})
                av.append(f"burn-in do Premiere, linha {ln['linha']} (metadado {ln['metadado']}): "
                          "só o TC da timeline é traduzido — refazer")
        if sintetico and (f.get("texto") or {}).get("texto"):
            efeitos.append({"name": "Text", "category": "title", "reproducible": True,
                            "params": {"titulo": _titulo_resolve(f, quadro, av, TPS / fps_tl)}})
        vel = f["vel"]
        conform = fps_tl / fps_m if fps_m else 1.0
        speed_ratio = conform / vel if vel else conform
        criativo = abs(vel - 1.0) > 1e-6
        reverso = f.get("sentido", 1) < 0
        classe = ("creative" if abs(conform - 1) < 1e-4 else "conform+creative") if criativo \
            else ("native" if abs(conform - 1) < 1e-4 else "conform")
        dur_fonte = None
        vs = p.ref(media, "VideoStream")
        if vs is not None and p.campo(vs, "Duration"):
            dur_fonte = round(_int(p.campo(vs, "Duration")) / tpf_m)
        seg = {
            "timeline_tc_in": frames_para_tc(a, nominal),
            "timeline_tc_out": frames_para_tc(b, nominal),
            "duration_frames": b - a,
            "source_start_frames": 0 if f.get("parado") else round(f["src_in"] / tpf_m),
            "source_fps": fps_m,
            "clip_name": ("Adjustment Clip" if f.get("ajuste") else "Graphic") if sintetico else titulo,
            "ajuste": bool(f.get("ajuste")),
            "track": trilha,
            "mob_id": None,
            "source_slot_id": None,
            "media_ref": None if sintetico else {
                "mob_name": titulo, "url": "", "local_path": caminho,
                "descriptor_type": "prproj", "source_duration_frames": dur_fonte,
                "source_duration_secs": (dur_fonte / fps_m) if dur_fonte else None,
                "source_fps": fps_m},
            "is_gap": False, "is_transition": False, "is_effect": sintetico, "is_audio": False,
            "cutpoint": 0,
            "has_motion_effect": criativo or reverso,
            # Reverso tem forma PRÓPRIA no Resolve (`build_reverse_timemap`); uma rampa de
            # inclinação negativa ele toca PARA FRENTE (medido 2026-10-02, a abertura do PRODUCAO_B).
            "motion_effect_type": "reverse" if reverso else ("constant" if criativo else None),
            "source_offset_map": [],
            # inclinação da curva do Resolve = segundos de fonte por segundo de timeline = a
            # PlaybackSpeed do Premiere (que é em tempo real).
            "velocidade_fonte": vel if reverso else None,
            "source_start_exato": f["src_in"] / tpf_m if reverso else None,
            "speed_ratio": speed_ratio, "phase_offset": 0, "motion_class": classe,
            "conform_ratio": conform, "relative_speed": speed_ratio / conform,
            "speed_curve": [], "speed_keyframes": [],
            "effects": efeitos,
            "has_reframe": True, "reframe_mode": "pillarbox",      # Scaling do clipe = Fit
            "retime": f.get("retime") if criativo else None,
            "has_graphic_overlay": False, "is_never_visible": False, "disabled": False,
            "visible_tc_in": None, "visible_tc_out": None,
            "is_group_clip": False, "group_clip_name": None, "selector_alternates": [],
            "prproj": {"plano": nome_plano, "proxy": caminho, "proxy_px": [fw, fh],
                       # o PROXY anexado pelo Premiere a este arquivo (`ProxyMedia`): o raster dele diz como o
                       # Premiere encaixa o convertido — esticado sobre o raster do original (R04, 2026-10-18)
                       "anexado_px": list(f["anexado_px"]) if f.get("anexado_px") else None,
                       # o principal foi RELIGADO a outro arquivo (o histórico aponta outro caminho): no R04 de 2023, o
                       # MP4 da câmera em `M4ROOT\CLIP` virou um `Proxies\…mp4` esticado de 1024×540 (2026-10-18)
                       "principal_religado": _religado(caminho, [v for k, v in p.campos_numerados(media,
                                                                                               "MediaFileHistory")]),
                       "escalar_ao_quadro": f["escalar_ao_quadro"], "velocidade": vel,
                       "alternate_start": p.campo(media, "AlternateStart"),
                       "midia": None if sintetico else self._midia_no_projeto(media, fps_m, fw, fh),
                       "sintetico": sintetico},
        }
        grade = f.get("grade_nest") and f.get("fonte_em") is not None
        if (f.get("remap") or grade) and not sintetico and not reverso:
            # RAMPA: a fonte em CADA quadro do plano (a regra do Avid: amostrar quadro a quadro, porque
            # cada programa interpreta a curva do seu jeito) → o `source_offset_map` que o writer já
            # escreve como rampa (`drp/writer.py::_media_timemap`, keyframes lineares frame-exatos).
            # Também o plano dentro de um nest acelerado (a GRADE do nest: a fonte anda aos degraus).
            tpf_tl = TPS / fps_tl
            if f.get("remap"):
                fontes = [_remap_fonte(f["remap"], (f["src_in"] + k * tpf_tl * vel) / TPS) for k in range(b - a + 1)]
            else:
                fontes = [f["fonte_em"](f["t0"] + k * tpf_tl) / TPS for k in range(b - a + 1)]
            ss0 = round(fontes[0] * fps_m)
            media_vel = ((fontes[-1] - fontes[0]) * fps_tl / (b - a)) if b > a else 1.0
            seg.update({
                "source_start_frames": ss0,
                "has_motion_effect": True, "motion_effect_type": "ramp",
                "source_offset_map": [(k, x * fps_m - ss0) for k, x in enumerate(fontes)],
                "speed_ratio": conform / media_vel if media_vel else conform,
                "relative_speed": 1.0 / media_vel if media_vel else 1.0,
                "motion_class": "conform+creative" if abs(conform - 1) >= 1e-4 else "creative",
                "speed_curve": [(k, round((fontes[k + 1] - fontes[k]) * fps_tl, 4)) for k in range(b - a)],
            })
            seg["prproj"]["rampa"] = [list(x) for x in f["remap"]] if f.get("remap") else "grade do nest"
        return seg

    def _transicao(self, it: Obj, trilha: int, itens: list[Obj], q, nominal: int) -> dict:
        p = self.p
        ini, fim = _int(p.campo(it, "Start")), _int(p.campo(it, "End"))
        corte = None
        # o corte é a borda de plano dentro da transição (o Premiere não sobrepõe os planos)
        for x in itens:
            if x.tag not in ("VideoClipTrackItem", "AudioClipTrackItem"):
                continue
            s_x = _int(p.campo(x, "Start"))
            if ini < s_x <= fim:
                corte = s_x
                break
        if corte is None:
            corte = ini if p.campo(it, "HasOutgoingClip") == "false" else fim
        a, b = q(ini), q(fim)
        return {"timeline_tc_in": frames_para_tc(a, nominal),
                "timeline_tc_out": frames_para_tc(b, nominal),
                "duration_frames": b - a, "source_start_frames": 0, "source_fps": None,
                "clip_name": "(transition)", "track": trilha, "is_transition": True,
                "is_gap": False, "is_audio": False, "is_effect": False,
                "cutpoint": q(corte) - a, "effects": [],
                "transicao": p.campo(it, "MatchName")}


#: Edge Feather do Premiere (px) → Softness do Cropping do Resolve. `inferido` — UMA calibração
#: pela imagem (2026-10-03, PRODUCAO_B 66-1-9, Feather 43, timeline 2880): varredura de Softness
#: 0–80 contra o export, pico em 4–5 (correlação 0,9983; 43 dava 0,9487).
SOFTNESS_POR_PX = 0.105

#: Corpo do Text do Premiere quando o blob não diz: 100 (o padrão do Essential Graphics; o
#: `0x64` do blob do PRODUCAO_B). Altura útil da letra sobre a linha de base, em corpos. `hipotese`.
#: Corpo do texto do Premiere em px do quadro (o padrão do Essential Graphics). Conferido em
#: 2026-10-04 pela imagem: a claquete em Monaco com Scale 100 tem 100 px de corpo num quadro de
#: 1620 (largura de "PRODUCAO-B" e entrelinha automática de 120% = 120 px).
CORPO_PREMIERE = 100.0
#: Entrelinha automática do Premiere: 120% do corpo (medido 2026-10-04: 120 px entre as linhas da
#: claquete de 100 px).
ENTRELINHA_PREMIERE = 1.2
#: O "Size" do Text do Resolve está em px de um quadro de 1080 linhas: num quadro de 1620 o corpo
#: 66,7 desenha 100 px. Medido 2026-10-04 (Mac, Resolve 21.1, Monaco: 71,1 → 106,7 px).
ALTURA_DO_SIZE_RESOLVE = 1080.0


def _titulo_resolve(f: dict, quadro: tuple[int, int], av: list, tpf_tl: float = 0.0) -> dict:
    """O bloco `titulo` (o do caminho do Avid, `titulos/resolve.py`) de um título do Premiere.

    Posição do Premiere = linha de base à esquerda, normalizada no quadro (Anchor 0:0). A do
    Resolve, com âncora topo-esquerda = canto de cima da caixa, Y medido de BAIXO: o topo fica a
    `ascendente da fonte × corpo` acima da linha de base (`titulos/fontes.py`).

    Por cima, o Graphic Group (Vector Motion) transforma a camada INTEIRA em volta do ponto de
    âncora dele. Com a âncora no centro do quadro (o padrão), ele é o Transform do clipe do
    Resolve — Zoom em volta do centro, inclusive ANIMADO (o título final do PRODUCAO_B cresce de
    80% a 100%; medido 2026-10-04: as keyframes de Zoom valem dentro do gerador do Text, em
    quadros desde o início do clipe). Âncora fora do centro: a escala do início vai embutida no
    corpo e na posição do texto."""
    from titulos import fontes

    tx = f["texto"]
    qw, qh = quadro
    g = (_float(f.get("grupo_escala"), 100.0) or 100.0) / 100.0
    gx, gy = _ponto(f.get("grupo_posicao"), (0.5, 0.5))
    ax, ay = _ponto(f.get("grupo_ancora"), (0.5, 0.5))
    transform = None
    if abs(ax - 0.5) < 1e-6 and abs(ay - 0.5) < 1e-6 and (abs(g - 1) > 1e-6 or f.get("grupo_escala_kf")
                                                          or abs(gx - ax) > 1e-6 or abs(gy - ay) > 1e-6):
        transform = {"zoom": g, "pos": (gx - ax, ay - gy)}          # fração, +Y para cima
        kfs = f.get("grupo_escala_kf") or []
        if len(kfs) > 1 and tpf_tl:
            transform["kf_zoom"] = [(max(0, round((t - f["t0"]) / tpf_tl)), v / 100.0) for t, v in kfs]
            if f.get("grupo_curva"):
                av.append("zoom do título com curva (Bézier): levado como linear")
        g, gx, gy = 1.0, ax, ay                                     # o texto, sem o grupo
    corpo_px = (tx.get("corpo_px") or CORPO_PREMIERE) * (_float(tx.get("Scale"), 100.0) or 100.0) / 100.0 * g
    px, py = _ponto(tx.get("Position"), (0.5, 0.5))
    px, py = gx + (px - ax) * g, gy + (py - ay) * g
    ps = tx.get("fonte") or ""
    fonte = fontes.traduzir(ps)
    topo = py - fonte["ascendente"] * corpo_px / qh if qh else py
    if ps and not fonte["instalada"]:
        av.append(f"fonte “{ps}” não está instalada nesta máquina: usada a família "
                  f"“{fonte['familia']}” ({fonte['face']}) pelo nome; conferir")
    elif ps and fonte.get("adobe"):
        av.append(f"fonte “{fonte['familia']} {fonte['face']}” é do Adobe Fonts: na máquina que abre o "
                  "Resolve, o Creative Cloud tem de estar logado com ela ATIVADA (o arquivo não pode ser "
                  "copiado); sem isso o Resolve troca a fonte")
    elif ps:
        av.append(f"fonte “{fonte['familia']} {fonte['face']}”: precisa estar instalada na máquina "
                  "que abre o Resolve")
    av.append("título do Premiere: cor (branco) suposta; conferir")
    # Line Spacing do Resolve = px de 1080 SOMADOS à linha natural da fonte (titulos/resolve.py):
    # para dar os 120% do Premiere, a diferença — negativa nas fontes de linha alta (Monaco).
    entrelinha = None
    if "\n" in (tx.get("texto") or "").strip() and qh:
        entrelinha = round((ENTRELINHA_PREMIERE - fonte["linha"]) * corpo_px
                           * ALTURA_DO_SIZE_RESOLVE / qh, 3) or None
    if f.get("grupo_animado") or tx.get("animado") or (f.get("grupo_escala_kf") and not transform):
        av.append("título animado (escala/posição): usado o valor do início")
    return {"estilo_lido": True, "fundo": None, "transform": transform, "caixas": [{
        "texto": tx["texto"], "fonte": {"familia": fonte["familia"] or "Open Sans",
                                       "estilo": fonte["face"] if ps else ""},
        "corpo": corpo_px / qh if qh else 0.08,
        "corpo_resolve": corpo_px * ALTURA_DO_SIZE_RESOLVE / qh if qh else None,
        # a Position do Premiere é a ORIGEM do alinhamento (o começo da linha na esquerda, o meio no centro, o fim na
        # direita): a âncora do Text do Resolve vai no mesmo lado (`titulos/resolve.py`, ANCORA topo_*)
        "cor": [1, 1, 1], "alinhamento": tx.get("alinhamento") or "esquerda", "entrelinha": entrelinha,
        "ancora": "topo_" + (tx.get("alinhamento") or "esquerda"), "posicao_resolve": (px, 1.0 - topo)}]}


def _volume_kf(p: Projeto, comp: Obj) -> list[tuple[int, float]]:
    """Keyframes do Volume do clipe: `[(ticks da MÍDIA, dB)]` (o tempo no domínio do `InPoint`, como
    o do Motion). Formato medido no PRODUCAO_B (2026-10-03): `ticks,valor,0,0,<alça>,0.166…,<alça>,0.166…;`
    com o valor linear (1,0 = +15 dB). Alças de curva ignoradas: o Resolve recebe linear."""
    for prm in p.refs(comp, "Param"):
        if p.campo(prm, "Name") != "Level":
            continue
        out = [(t, _db_do_level(v)) for t, v in _kfs_do_level(p, prm)]
        return out if len(out) > 1 else []
    return []


def _kfs_do_level(p: Projeto, prm: Obj) -> list[tuple[int, float]]:
    """As keyframes VÁLIDAS do `Level`: `[(ticks, valor linear)]`, em ordem. Uma só regra para o
    volume fixo e o animado — contar entradas cruas num e válidas no outro deixava um clipe com uma
    keyframe malformada sem volume nenhum, calado (revisão de código 2026-10-03)."""
    out = []
    for k in (p.campo(prm, "Keyframes") or "").split(";"):
        partes = k.split(",")
        if len(partes) >= 2 and _float(partes[1], None) is not None and partes[0].strip().isdigit():
            out.append((int(partes[0]), _float(partes[1], 0.0)))
    return sorted(out)


def _db_do_level(v: float) -> float:
    """`Level` linear do Premiere (1,0 = +15 dB) → dB, com o piso de −100."""
    import math
    return round(max(-100.0, 20 * math.log10(v) + 15.0), 3) if v > 0 else -100.0


def _volume_no_trecho(volume_db, volume_kf: list, f: dict, a: int, b: int, tpf_tl: float,
                      avisos: dict) -> dict:
    """`{volume_db, volume_kf}` de UM clipe do Resolve: a curva do Premiere AVALIADA no trecho dele.

    As keyframes ficam no tempo da MÍDIA, e um corte de lâmina copia todas para cada pedaço (no
    PRODUCAO_B, 5 pedaços do 17B-18-1T04 com as mesmas 4, nenhuma dentro de nenhum). Antes da 1ª vale
    o valor dela; depois da última, o da última; entre, linear na AMPLITUDE (o `Level` do Premiere).
    Saem: o valor nas duas pontas do clipe + as keyframes de dentro; curva constante no trecho vira
    volume FIXO. Tempo no domínio do `In` do writer (fonte × speed_ratio, quadros da timeline), como o
    Motion. Num take aninhado a keyframe é do clipe de fora e a mídia é a de dentro: aviso."""
    if not volume_kf:
        return {"volume_db": volume_db, "volume_kf": []}
    if "pos" in f:
        chave = "volume com keyframes em take aninhado: não traduzido (fica 0 dB)"
        avisos[chave] = avisos.get(chave, 0) + 1
        return {"volume_db": None, "volume_kf": []}
    vel = f.get("vel", 1.0) or 1.0
    pts = [(t / tpf_tl / vel, 10 ** ((db - 15.0) / 20)) for t, db in volume_kf]   # (quadro, amplitude)

    def amp(q):
        if q <= pts[0][0]:
            return pts[0][1]
        for (q0, v0), (q1, v1) in zip(pts, pts[1:]):
            if q <= q1:
                return v0 + (v1 - v0) * (q - q0) / (q1 - q0) if q1 > q0 else v1
        return pts[-1][1]

    db = _db_do_level
    i0 = f["src_in"] / tpf_tl / vel
    i1 = i0 + (b - a) - 1
    saida = [(round(i0), db(amp(i0)))] + [(round(q), db(v)) for q, v in pts if i0 < q < i1] \
        + [(round(i1), db(amp(i1)))]
    vals = [d for _q, d in saida]
    if max(vals) - min(vals) < 0.01:                     # constante no trecho: volume fixo
        return {"volume_db": vals[0] if abs(vals[0]) > 0.01 else None, "volume_kf": []}
    unicos = []
    for q, d in saida:
        if not unicos or q > unicos[-1][0]:
            unicos.append((q, d))
    return {"volume_db": None, "volume_kf": unicos}


def _volume_db(p: Projeto, comp: Obj, avisos: dict) -> float | None:
    """O ganho FIXO do Volume do clipe, em dB. O Premiere guarda o `Level` como amplitude linear
    com 1,0 = +15 dB (o máximo dele): o padrão 0,177828 = 10^(−15/20) = 0 dB (medido no PRODUCAO_B:
    6.150 parâmetros de Channel Volume nesse valor). dB = 20·log10(v) + 15. Com keyframes: não
    traduzido, com aviso (decisão do autor, 2026-10-04: keyframes só depois de medir)."""
    for prm in p.refs(comp, "Param"):
        if p.campo(prm, "Name") != "Level":
            continue
        kfs = _kfs_do_level(p, prm)
        if len(kfs) > 1:
            return None                 # as keyframes vão por `_volume_kf`
        if not kfs and (p.campo(prm, "Keyframes") or "").strip(";").strip():
            chave = "volume do clipe com keyframes ilegíveis: usado o valor fixo"
            avisos[chave] = avisos.get(chave, 0) + 1
        # UM keyframe só (`tempo,valor,…`) vale o clipe inteiro: é volume fixo (3 no PRODUCAO_B)
        x = kfs[0][1] if kfs else _float(_valor(p, prm, None)[0], None)
        if x is None or x <= 0:
            return None
        db = _db_do_level(x)
        return db if abs(db) > 0.01 else None
    return None


def _quadro(tc: str, nominal: int) -> int:
    h, m, s_, f = (int(x) for x in tc.split(":"))
    return ((h * 60 + m) * 60 + s_) * nominal + f


def _referencia_na_timeline(segs: list[dict], nominal: int, tolerancia: int = 2) -> dict | None:
    """O vídeo de REFERÊNCIA que o editor deixou na timeline (regra de ofício do autor, banco
    `operacoes-de-nle.md` J.3b): na trilha de vídeo MAIS ALTA, UM clipe de vídeo (imagem parada não
    conta — a máscara 1.85 em PNG fica de fora) do começo ao fim da timeline (± `tolerancia`
    quadros). Achado, o segmento ganha `referencia` (o montar o separa da tradução: sem casamento,
    sem marcador) e `trilha_desligada` (entra desligado). O som dele (os clipes de áudio do MESMO
    arquivo) ganha `referencia` também."""
    video = [s for s in segs if not s.get("is_audio") and not s.get("is_gap")
             and not s.get("is_transition")]
    if not video:
        return None
    fim = max(_quadro(s["timeline_tc_in"], nominal) + s["duration_frames"] for s in segs
              if not s.get("is_gap") and not s.get("is_transition"))
    topo = max(s["track"] for s in video)
    nela = [s for s in video if s["track"] == topo]
    if len(nela) != 1:
        return None
    s = nela[0]
    caminho = (s.get("media_ref") or {}).get("local_path") or ""
    ini = _quadro(s["timeline_tc_in"], nominal)
    if (s.get("is_effect") or not _e_video(caminho) or ini > tolerancia
            or ini + s["duration_frames"] < fim - tolerancia):
        return None
    s["referencia"], s["trilha_desligada"] = True, True
    for a in segs:
        if a.get("is_audio") and (a.get("media_ref") or {}).get("local_path") == caminho:
            a["referencia"] = True
    return s


def _lacunas(ocupado: list, trilha: int, nominal: int, fps: float) -> list[dict]:
    """Segmentos `is_gap` nos buracos da trilha: o writer só reconhece um FADE (transição de
    um lado só) quando o vizinho é lacuna; sem ela, emparelharia planos distantes."""
    out, pos = [], 0
    for a, b in sorted(ocupado):
        if a > pos:
            out.append({"timeline_tc_in": frames_para_tc(pos, nominal),
                        "timeline_tc_out": frames_para_tc(a, nominal), "duration_frames": a - pos,
                        "source_start_frames": 0, "source_fps": fps, "clip_name": "(gap)",
                        "track": trilha, "is_gap": True, "is_transition": False,
                        "is_audio": False, "is_effect": False, "effects": []})
        pos = max(pos, b)
    return out


def _religado(caminho: str, historico: list[str]) -> bool:
    """O `Media` já apontou para OUTRO arquivo: a pasta de cima ou o nome diferentes (sem contar caixa nem barra). A
    letra do disco e o resto do caminho não contam — mudar de HD (`J:` → `I:`) não troca o arquivo."""
    def norma(c):
        return "/".join((c or "").replace("\\", "/").rstrip("/").lower().split("/")[-2:])
    return bool(caminho) and any(h and norma(h) != norma(caminho) for h in historico)


def _e_video(caminho: str | None) -> bool:
    return bool(caminho) and not re.search(r"\.(png|jpe?g|tiff?|psd|bmp|gif|exr|dpx)$",
                                           caminho, re.I)


def ler_sequencia(caminho_prproj: str, nome: str) -> dict:
    return Leitor(Projeto(caminho_prproj)).ler(nome)
