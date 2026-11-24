"""Composições do Fusion que o DRT não leva — máscara, blur e Basic 3D —, criadas DEPOIS do import.

Duas metades:

  • `plano(receitas)` — TODA a conta (cantos do Basic 3D, pontos do Polygon, tamanho do blur), no
    serviço: devolve os nós a criar (só números) e as ligações. `tools/prproj_para_drt.py` grava um
    plano por clipe no `.relatorio.json` (chave `fusion`).
  • executar o plano DENTRO do Resolve: `executar` aqui (Python, pelo scripting) e `aplicarFusion`
    na casca (`plugins/resolve/casca/main.js`, pela ponte JS), que monta o MESMO texto de `.setting`
    a partir dos números — nunca recebe texto pronto (um `.setting` pode levar código Lua).

UMA composição por clipe, os efeitos em cadeia na ordem da pilha do Premiere:

    item.AddFusionComp() → LoadFusionCompByName(nova)      (a do usuário, se houver, fica)
    recorte:  Polygon (AddTool + LoadSettings) no EffectMask do MediaIn
    desfoque: Blur, com o Polygon no EffectMask dele
    basic3d:  CornerPositioner com os 4 cantos da rotação do Premiere
    opacidade: a máscara da Opacidade do Premiere — sozinha, no EffectMask do MediaIn; com outros nós, no FIM da
              cadeia: Merge (Background transparente + a cadeia) com o Polygon no EffectMask dele
    … → MediaOut

Medido no Resolve Studio 21.1 (Mac), 2026-10-03: o caminho pela API dispensa o molde (a sessão
anterior montava sobre uma composição do autor); `ImportFusionComp` não é usado — ele SUBSTITUI a
composição ativa (banco, `plugins/resolve-scripting/api-scripting.md`).

Convenções (banco, `protocolos/prproj/relink-e-geometria.md` §10.6–10.8): vértices do Premiere na
FONTE, normalizados 0–1, Y para baixo → Polygon do Fusion a partir do centro, Y para cima. Máscara
INVERTIDA no Crop do Premiere = mostrar só o de dentro = Polygon normal no MediaIn; não invertida no
Crop = Polygon invertido. No Blur, não invertida = desfoca só o de dentro.
"""
from __future__ import annotations

import os
import tempfile

#: Suavidade da máscara: Feather do Premiere (px da fonte) → SoftEdge do Polygon = fator × px ÷ largura.
#: MEDIDO no laboratório (B14_MASCARA, 2026-10-10: borda reta conhecida, render do Premiere 23.2 × Resolve 19,
#: Windows): o Feather é a largura TOTAL da transição, centrada no contorno (10–90 % = 0,915 × Feather, em px da
#: FONTE — com Zoom 200 % dobra na tela); com o fator 1 o Resolve saía 17–20 % mais largo (F25…F500, com e sem
#: zoom: Premiere ÷ Resolve = 0,83–0,86). A calibração anterior (fator 1, PRODB, 1 caso por correlação) não
#: separava isso.
SOFTEDGE_POR_PX = 0.845
#: Desfoque: Blurriness do Gaussian Blur do Premiere (`AE.ADBE Gaussian Blur 2`) → XBlurSize do Blur do Fusion:
#: XBlurSize = BLUR_POR_PX × Blurriness + BLUR_DESLOCAMENTO. MEDIDO no laboratório (B20_DESFOQUE, 2026-10-11: degrau nítido,
#: largura 10–90 % no render — Premiere 23.2 em ProRes 4444: 0,7209·B + 0,09 px; Resolve 19, o Blur do Fusion: 2,8602·X +
#: 0,83 px; Blurriness 5…100, XBlurSize 1…24, as duas retas exatas). A estimativa anterior (0,2, um caso só, por
#: correlação) desfocava ~20 % a menos.
BLUR_POR_PX = 0.2521
BLUR_DESLOCAMENTO = -0.259


def _f(x: float) -> str:
    """6 casas, sem zeros à direita e sem notação científica — o MESMO formato de `num()` na
    casca (o teste de paridade compara os dois textos byte a byte)."""
    t = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return "0" if t in ("-0", "") else t


def cantos_basic3d(swivel: float, tilt: float, fonte_px: list) -> dict:
    """Os 4 cantos da fonte depois do Basic 3D do Premiere, no formato do CornerPositioner
    (0–1, origem embaixo à esquerda, Y para cima).

    Medido 2026-10-03 pela imagem (caso R02, Swivel = Tilt = 20, homografia por pontos casados
    contra o export do Premiere): rotação R = Ry(Swivel)·Rx(Tilt) em torno do centro da camada,
    câmera a UMA LARGURA da camada de distância ("Distance to Image" 0) — o ajuste deu 20,10° /
    19,94°, erro 0,65 px. Com estes cantos, o Resolve bateu 0,9993 contra o export (cantos a ≤ 2,3
    px). O Pitch/Yaw do Inspector NÃO serve: é perspectiva pura (sem encurtar nem inclinar) e, num
    clipe com composição do Fusion, gira em torno do centro do QUADRO, não do clipe."""
    import math
    s, t = math.radians(swivel), math.radians(tilt)
    w, h = float(fonte_px[0]) or 1920.0, float(fonte_px[1]) or 1080.0
    out = {}
    for nome, (x, y) in (("TopLeft", (-w / 2, -h / 2)), ("TopRight", (w / 2, -h / 2)),
                         ("BottomLeft", (-w / 2, h / 2)), ("BottomRight", (w / 2, h / 2))):
        qx = math.cos(s) * x + math.sin(s) * math.sin(t) * y
        qy = math.cos(t) * y
        qz = -math.sin(s) * x + math.cos(s) * math.sin(t) * y
        k = w / (w + qz)
        out[nome] = (qx * k / w + 0.5, 0.5 - qy * k / h)
    return out


def _pontos_polygon(vertices: list) -> list[dict]:
    """Vértices da receita (`[suave, [x, y], [entrada], [saída]]`, normalizados na fonte, Y para
    baixo) → pontos do Polygon do Fusion (a partir do centro, Y para cima, alças relativas)."""
    out = []
    for suave, (x, y), (ix, iy), (ox, oy) in vertices:
        if suave:
            out.append({"linear": False, "x": x - 0.5, "y": 0.5 - y, "lx": ix - x, "ly": y - iy,
                        "rx": ox - x, "ry": y - oy})
        else:
            out.append({"linear": True, "x": x - 0.5, "y": 0.5 - y})
    return out


def _dividir(vertices: list, i: int) -> list:
    """Parte ao meio (de Casteljau, t = 0,5) o segmento do vértice `i` ao seguinte (contorno
    fechado): a forma fica a mesma, com um vértice a mais. Segmento entre dois cantos = reta."""
    n = len(vertices)
    s0, p0, i0, o0 = vertices[i]
    s3, p3, i3, o3 = vertices[(i + 1) % n]
    if not s0 and not s3:
        meio = [(p0[0] + p3[0]) / 2, (p0[1] + p3[1]) / 2]
        return vertices[:i + 1] + [[False, meio, list(meio), list(meio)]] + vertices[i + 1:]

    def med(a, b):
        return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
    # no Fusion um canto é `Linear` (alças recalculadas): o trecho curvo usa só as alças do lado suave
    p1 = o0 if s0 else p0
    p2 = i3 if s3 else p3
    a, b, c = med(p0, p1), med(p1, p2), med(p2, p3)
    d, e = med(a, b), med(b, c)
    m = med(d, e)
    out = [list(v) for v in vertices]
    out[i] = [s0, p0, i0, a if s0 else o0]
    out[(i + 1) % n] = [s3, p3, c if s3 else i3, o3]
    return out[:i + 1] + [[True, m, d, e]] + out[i + 1:]


def igualar_vertices(contornos: list[list]) -> list[list]:
    """O Polyline animado do Fusion interpola ponto a ponto, pelo índice: keyframes com números
    DIFERENTES de vértices (o Premiere guarda cada keyframe como um contorno independente) saem
    errados. MEDIDO no R04 (LOU_7310, V2, 2026-10-10): contornos de 5, 6, 6 e 5 vértices — o Resolve
    mostrava o wipe pela metade onde o Premiere ainda não mostrava nada. Iguala dividindo o maior
    segmento (corda) dos contornos curtos: em cada keyframe a forma continua a mesma."""
    alvo = max(len(c) for c in contornos)
    out = []
    for c in contornos:
        c = [list(v) for v in c]
        while len(c) < alvo:
            n = len(c)
            i = max(range(n), key=lambda k: math.dist(c[k][1], c[(k + 1) % n][1]))
            c = _dividir(c, i)
        out.append(c)
    return out


def _no_polygon(receita: dict, inverter_se_normal: bool, n: int) -> dict | None:
    m = (receita.get("mascaras") or [None])[0]
    if m is None:
        return None
    # o Premiere soma as máscaras de um efeito; aqui só a 1ª (nenhum caso no PRODB)
    w, h = (int(receita["fonte_px"][0]) or 1920, int(receita["fonte_px"][1]) or 1080)
    no = {"id": f"Polygon{n}", "tipo": "PolylineMask", "largura": w, "altura": h,
          "suave": m.get("suave_px", 0.0) * SOFTEDGE_POR_PX / w,
          "inverter": (not m["invertida"]) if inverter_se_normal else m["invertida"],
          "pontos": _pontos_polygon(m["vertices"])}
    if m.get("expansao_px"):
        # Mask Expansion do Premiere (px da fonte) → Border Width do Polygon (fração da largura, como o
        # SoftEdge) × 2. MEDIDO (B14, 2026-10-10): a Expansion empurra a borda exatamente N px (±16, +50) sem
        # mudar a suavidade; Border Width = px ÷ largura empurrava só a METADE (8 e 25 px).
        no["borda"] = 2 * m["expansao_px"] / w
    qds = [q for q in (m.get("quadros") or []) if "quadro" in q]
    if len(qds) > 1:
        # CONTORNO ANIMADO: um keyframe por keyframe do Premiere, no tempo da composição do Fusion =
        # quadro da FONTE (medido no Resolve 19, R04, 2026-10-10)
        no["quadros"] = [int(q["quadro"]) for q in qds]
        no["pontos_quadros"] = [_pontos_polygon(vs) for vs in igualar_vertices([q["vertices"] for q in qds])]
        no["pontos"] = no["pontos_quadros"][0]
    return no


def plano(receitas: list[dict]) -> dict:
    """Os nós e as ligações da composição de UM clipe. `ValueError` se a cadeia não se monta."""
    nos, ligacoes = [], []
    atual, n_poly, n_blur, n_cp, n_merge = "MediaIn1", 0, 0, 0, 0
    opacidade = None

    def recortar_depois(poly):
        """A cadeia até aqui DENTRO do contorno, transparente fora: Merge (Background transparente + a cadeia) com o
        Polygon no EffectMask — o mesmo desenho da máscara de opacidade no fim."""
        nonlocal n_merge
        n_merge += 1
        fundo = {"id": f"Background{n_merge}", "tipo": "Background", "largura": poly["largura"], "altura": poly["altura"]}
        mescla = {"id": f"Merge{n_merge}", "tipo": "Merge"}
        nos.extend([fundo, mescla])
        ligacoes.extend([[mescla["id"], "Background", fundo["id"]], [mescla["id"], "Foreground", atual],
                         [mescla["id"], "EffectMask", poly["id"]]])
        return mescla["id"]
    for r in receitas:
        efeito = r["efeito"]
        if efeito == "recorte":
            n_poly += 1
            poly = _no_polygon(r, True, n_poly)
            if poly is None:
                raise ValueError("Crop com máscara sem contorno")
            nos.append(poly)
            if atual == "MediaIn1":
                ligacoes.append(["MediaIn1", "EffectMask", poly["id"]])
            else:
                # ⭐ o recorte DEPOIS de outro efeito (2026-11-20): o Premiere aplica a cadeia do último índice do arquivo
                #   para o primeiro — o insert do PRODB ([Crop com máscara, Basic 3D] no arquivo) GIRA primeiro e
                #   recorta depois, com a máscara reta. Antes: raise (e a leitura em ordem de arquivo escondia o caso).
                atual = recortar_depois(poly)
        elif efeito == "opacidade":
            # MÁSCARA DE OPACIDADE: o plano só aparece dentro do contorno (não invertida). A Opacidade é efeito FIXO
            # do Premiere: roda DEPOIS dos efeitos comuns — ele desfoca a imagem inteira e só então recorta. Então ela
            # vai no FIM da cadeia (abaixo, depois do laço), não no MediaIn. MEDIDO 2026-10-10 (R04, a pessoa desfocada
            # do nest transicao-pesoa, render do Premiere só com a V3): recortando no MediaIn e desfocando depois, a
            # área saía maior (1772 × 1660 px); desfoque → Merge com o Polygon, 1665.
            if opacidade is not None:
                raise ValueError("duas máscaras de opacidade no mesmo clipe: refazer")
            n_poly += 1
            opacidade = _no_polygon(r, False, n_poly)
            if opacidade is None:
                raise ValueError("máscara de opacidade sem contorno")
            nos.append(opacidade)
        elif efeito == "desfoque":
            n_blur += 1
            tam = max(0.0, r.get("px", 0.0) * BLUR_POR_PX + BLUR_DESLOCAMENTO) if r.get("px") else 0.0
            entradas = {"XBlurSize": tam}
            if r.get("direcao") in (1, 2):              # 1 = só horizontal, 2 = só vertical
                entradas = {"LockXY": 0, "XBlurSize": tam if r["direcao"] == 1 else 0.0,
                            "YBlurSize": tam if r["direcao"] == 2 else 0.0}
            blur = {"id": f"Blur{n_blur}", "tipo": "Blur", "entradas": entradas}
            nos.append(blur)
            ligacoes.append([blur["id"], "Input", atual])
            n_poly += 1
            poly = _no_polygon(r, False, n_poly)
            if poly is not None:
                nos.append(poly)
                ligacoes.append([blur["id"], "EffectMask", poly["id"]])
            atual = blur["id"]
        elif efeito == "basic3d":
            n_cp += 1
            cp = {"id": f"CornerPositioner{n_cp}", "tipo": "CornerPositioner",
                  "cantos": {k: list(v) for k, v in
                             cantos_basic3d(r["swivel"], r["tilt"], r["fonte_px"]).items()}}
            nos.append(cp)
            ligacoes.append([cp["id"], "Input", atual])
            atual = cp["id"]
        else:
            raise ValueError(f"efeito desconhecido: {efeito}")
    if opacidade is not None:
        if atual == "MediaIn1":
            # sozinha: o alfa do MediaIn (validado no B14/B16 e no R04)
            if any(l[0] == "MediaIn1" and l[1] == "EffectMask" for l in ligacoes):
                raise ValueError("duas máscaras no mesmo clipe (Crop e Opacidade): refazer")
            ligacoes.append(["MediaIn1", "EffectMask", opacidade["id"]])
        else:
            # depois da cadeia: o Merge mostra a cadeia DENTRO do contorno e o Background transparente fora (o efeito
            # com máscara do Fusion mistura o resultado com a entrada de fundo). O Background no tamanho da FONTE.
            atual = recortar_depois(opacidade)
    if atual != "MediaIn1":
        ligacoes.append(["MediaOut1", "Input", atual])
    return {"nos": nos, "ligacoes": ligacoes}


import math
import re

#: As MESMAS listas fechadas da casca (`FUSION_TIPOS`, `FUSION_ENTRADAS`, `FUSION_LIGACOES`,
#: `FUSION_IDS` no main.js). O plano pode vir de um `.relatorio.json` em disco; sem esta conferência,
#: um id ou uma chave com Lua iria literal para a composição (revisão de código, 2026-10-03).
_TIPOS = {"PolylineMask", "Blur", "CornerPositioner", "Background", "Merge"}
_ENTRADAS_BLUR = {"XBlurSize", "YBlurSize", "LockXY"}
_LIGACOES = {"Input", "EffectMask", "Background", "Foreground"}
_IDS = re.compile(r"^(MediaIn1|MediaOut1|(Polygon|Blur|CornerPositioner|Background|Merge)\d{1,3})$")
_CANTOS = ("TopLeft", "TopRight", "BottomLeft", "BottomRight")


def _numero(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError("número inválido no plano do Fusion")
    return float(v)


def validar(pl: dict) -> dict:
    """Confere o plano inteiro (só números, só os tipos, ids e ligações conhecidos). `ValueError`."""
    nos = (pl or {}).get("nos") or []
    ids = {"MediaIn1", "MediaOut1"}
    for no in nos:
        if not isinstance(no, dict) or no.get("tipo") not in _TIPOS or not _IDS.match(str(no.get("id") or "")):
            raise ValueError("nó inválido no plano")
        ids.add(no["id"])
        if no["tipo"] == "PolylineMask":
            for k in ("largura", "altura", "suave"):
                _numero(no.get(k))
            if not no.get("pontos"):
                raise ValueError("Polygon sem pontos")
            for lista in [no["pontos"]] + list(no.get("pontos_quadros") or []):
                for p_ in lista:
                    for k in (("x", "y") if p_.get("linear") else ("x", "y", "lx", "ly", "rx", "ry")):
                        _numero(p_.get(k))
            if "borda" in no:
                _numero(no["borda"])
            if no.get("quadros") is not None:
                qs = no["quadros"]
                if (not isinstance(qs, list) or len(qs) != len(no.get("pontos_quadros") or [])
                        or any(isinstance(q, bool) or not isinstance(q, int) for q in qs)):
                    raise ValueError("quadros do Polygon inválidos")
        elif no["tipo"] == "Background":
            for k in ("largura", "altura"):
                _numero(no.get(k))
        elif no["tipo"] == "Merge":
            pass
        elif no["tipo"] == "CornerPositioner":
            for k in _CANTOS:
                c = (no.get("cantos") or {}).get(k)
                if not isinstance(c, (list, tuple)) or len(c) != 2:
                    raise ValueError(f"CornerPositioner sem {k}")
                _numero(c[0]), _numero(c[1])
        else:
            for k, v in (no.get("entradas") or {}).items():
                if k not in _ENTRADAS_BLUR:
                    raise ValueError(f"entrada {k} recusada")
                _numero(v)
    for l_ in (pl or {}).get("ligacoes") or []:
        if (not isinstance(l_, (list, tuple)) or len(l_) != 3 or l_[1] not in _LIGACOES
                or l_[0] not in ids or l_[2] not in ids or l_[2] == "MediaOut1"):
            raise ValueError("ligação inválida no plano")
    return pl


#: A saída de cada tipo de nó, para ligar no texto da composição.
_SAIDA = {"PolylineMask": "Mask", "Blur": "Output", "CornerPositioner": "Output", "Loader": "Output",
          "Background": "Output", "Merge": "Output"}


def _polyline(pontos: list[dict]) -> str:
    pts = []
    for p in pontos:
        if p["linear"]:
            pts.append(f"{{ Linear = true, X = {_f(p['x'])}, Y = {_f(p['y'])} }}")
        else:
            pts.append(f"{{ X = {_f(p['x'])}, Y = {_f(p['y'])}, LX = {_f(p['lx'])}, "
                       f"LY = {_f(p['ly'])}, RX = {_f(p['rx'])}, RY = {_f(p['ry'])} }}")
    return "Polyline { Closed = true, Points = { " + ", ".join(pts) + " } }"


def _spline(no: dict) -> str | None:
    """O `BezierSpline` do contorno ANIMADO de um Polygon (a ferramenta que o Polyline dele lê), ou
    None. ⚠️ O MESMO molde está em `splineFusion` da casca (main.js)."""
    if not no.get("quadros"):
        return None
    # O número antes de `Flags` é o DESLOCAMENTO do keyframe no caminho: 0, 1, 2… MEDIDO no laboratório (B14, Resolve 19,
    # 2026-10-10): com todos 0 a forma SEGURA até o próximo keyframe (degrau onde o Premiere interpola) e o último quadro
    # do clipe fica no penúltimo keyframe; com o índice, as duas coisas batem com o render do Premiere.
    kfs = ", ".join("[" + str(int(q)) + "] = { " + str(i) + ", Flags = { Linear = true, LockedY = true }, Value = "
                    + _polyline(pts) + " }" for i, (q, pts) in enumerate(zip(no["quadros"], no["pontos_quadros"])))
    return (no["id"] + "Polyline = BezierSpline { SplineColor = { Red = 173, Green = 255, Blue = 47 }, "
            "NameSet = true, KeyFrames = { " + kfs + ", }, },")


def _entradas(no: dict) -> list[str]:
    """As `Inputs` de um nó em texto do Fusion. ⚠️ O MESMO molde está em `entradasFusion` da casca
    (main.js): mudou aqui, mude lá — o teste de paridade compara os dois byte a byte."""
    if no["tipo"] == "PolylineMask":
        if no.get("quadros"):
            contorno = "Polyline = Input { SourceOp = \"" + no["id"] + "Polyline\", Source = \"Value\", }"
        else:
            contorno = "Polyline = Input { Value = " + _polyline(no["pontos"]) + ", }"
        return (["Invert = Input { Value = 1, }"] if no["inverter"] else []) + [
            f"MaskWidth = Input {{ Value = {int(no['largura'])}, }}",
            f"MaskHeight = Input {{ Value = {int(no['altura'])}, }}",
            "UseFrameFormatSettings = Input { Value = 0, }",
            f"SoftEdge = Input {{ Value = {_f(no['suave'])}, }}"] + (
            [f"BorderWidth = Input {{ Value = {_f(no['borda'])}, }}"] if "borda" in no else []) + [contorno]
    if no["tipo"] == "CornerPositioner":
        return [f"{k} = Input {{ Value = {{ {_f(no['cantos'][k][0])}, {_f(no['cantos'][k][1])} }}, }}"
                for k in ("TopLeft", "TopRight", "BottomLeft", "BottomRight")]
    if no["tipo"] == "Blur":
        return [f"{k} = Input {{ Value = {_f(v)}, }}" for k, v in (no.get("entradas") or {}).items()]
    if no["tipo"] == "Background":
        # transparente (o padrão do Background é preto OPACO), no tamanho da fonte
        return [f"Width = Input {{ Value = {int(no['largura'])}, }}", f"Height = Input {{ Value = {int(no['altura'])}, }}",
                "UseFrameFormatSettings = Input { Value = 0, }", "TopLeftAlpha = Input { Value = 0, }"]
    if no["tipo"] == "Merge":
        return []
    raise ValueError(f"tipo de nó desconhecido: {no['tipo']}")


def compor(texto: str, pl: dict) -> str:
    """O texto de uma composição NOVA (exportada com `ExportFusionComp`: MediaIn1 → MediaOut1) com
    os nós do plano escritos e ligados. É o caminho que serve à casca: pela ponte JS do Resolve 21.1
    o `AddTool` cria o nó, mas a ferramenta vem SEM `LoadSettings`/`SetInput`/`ConnectInput`
    (medido 2026-10-03) — os métodos do TimelineItem (`Export`/`ImportFusionComp`) vêm inteiros."""
    validar(pl)
    tipos = {"MediaIn1": "Loader"} | {n["id"]: n["tipo"] for n in pl["nos"]}
    ligar: dict[str, list[str]] = {}
    for destino, entrada, origem in pl["ligacoes"]:
        ligar.setdefault(destino, []).append(
            f'{entrada} = Input {{ SourceOp = "{origem}", Source = "{_SAIDA[tipos[origem]]}", }}')
    defs = []
    for k, no in enumerate(pl["nos"]):
        sp = _spline(no) if no["tipo"] == "PolylineMask" else None
        if sp:
            defs.append(sp)
        corpo = ", ".join(_entradas(no) + ligar.get(no["id"], []))
        defs.append(f"{no['id']} = {no['tipo']} {{ Inputs = {{ {corpo}, }}, "
                    f"ViewInfo = OperatorInfo {{ Pos = {{ {110 * (k + 1)}, 115 }} }}, }},")
    i_out = texto.find("MediaOut1 = Saver {")
    i_in = texto.find("MediaIn1 = Loader {")
    if i_out < 0 or i_in < 0:
        raise ValueError("composição exportada sem MediaIn1/MediaOut1")
    # MediaOut1: a entrada passa a vir do último nó da cadeia
    fim_out = texto.find("ViewInfo", i_out)
    trecho = texto[i_out:fim_out]
    for linha in ligar.get("MediaOut1", []):
        origem = linha.split('"')[1]
        novo = trecho.replace('SourceOp = "MediaIn1"', f'SourceOp = "{origem}"', 1)
        if novo == trecho:
            raise ValueError("MediaOut1 sem a entrada do MediaIn1")
        trecho = novo
    texto = texto[:i_out] + trecho + texto[fim_out:]
    # MediaIn1: a máscara do recorte no EffectMask
    if ligar.get("MediaIn1"):
        j = texto.find("Inputs = {", i_in)
        if j < 0 or j > texto.find("MediaOut1 = Saver {"):
            raise ValueError("MediaIn1 sem Inputs")
        j += len("Inputs = {")
        texto = texto[:j] + "".join(f"\n\t\t\t\t{x}," for x in ligar["MediaIn1"]) + texto[j:]
    # os nós, logo antes do MediaOut1
    i_out = texto.find("MediaOut1 = Saver {")
    return texto[:i_out] + "\n\t\t".join(defs) + "\n\t\t" + texto[i_out:]


def setting(no: dict) -> str:
    """O `.setting` de UM nó (o que `Tool.LoadSettings` lê) — usado pelo caminho do scripting."""
    validar({"nos": [no], "ligacoes": []})
    sp = _spline(no) if no["tipo"] == "PolylineMask" else None
    return ("{ Tools = ordered() { " + (sp + " " if sp else "") + no["id"] + " = " + no["tipo"] + " { Inputs = { "
            + ", ".join(_entradas(no)) + ", }, }, }, }\n")


#: Composição mínima: no clipe SEM composição o Resolve religa o MediaIn1 à mídia do clipe (o MESMO
#: `FUSION_MODELO` da casca).
MODELO = ('Composition { Tools = { MediaIn1 = Loader { Inputs = { }, ViewInfo = OperatorInfo { }, }, '
          'MediaOut1 = Saver { Inputs = { Input = Input { SourceOp = "MediaIn1", Source = "Output", }, }, '
          'ViewInfo = OperatorInfo { }, }, }, }')


def _arquivo_comp() -> str:
    fd, arq = tempfile.mkstemp(suffix=".comp", prefix="dlpc_")
    os.close(fd)
    return arq


def _montada(item, indice: int, pl: dict) -> bool:
    """A composição `indice` tem os nós do plano E o MediaIn ligado à mídia? Pelo que o Resolve
    EXPORTA de volta — o retorno do `ImportFusionComp` não prova nada no 19 (ver `executar`)."""
    arq = _arquivo_comp()
    try:
        if not item.ExportFusionComp(arq, indice):
            return False
        # `errors="replace"`: um caminho com acento gravado noutra codificação não pode derrubar a
        # conferência (revisão de código 2026-10-03) — só os nomes dos nós e a chave importam aqui
        with open(arq, encoding="utf-8", errors="replace") as f:
            t = f.read()
        return "MEDIA_PATH" in t and all(f"{no['id']} = {no['tipo']} {{" in t for no in pl.get("nos") or [])
    except (OSError, ValueError):
        return False
    finally:
        try:
            os.remove(arq)
        except OSError:
            pass


def _inicio_da_comp(item, indice: int) -> float:
    """`COMPN_GlobalStart` da composição `indice`: 0 no Resolve 19 (o tempo da composição É o quadro da fonte); no
    21.1 a composição começa a contar no `In` do clipe e isto vale −(quadro da fonte do `In`, truncado)."""
    try:
        c = item.GetFusionCompByIndex(indice)
        return float((c.GetAttrs() or {}).get("COMPN_GlobalStart") or 0) if c else 0.0
    except Exception:  # noqa: BLE001 — sem a leitura, fica o tempo da fonte (o comportamento medido no 19)
        return 0.0


def no_tempo_da_comp(pl: dict, inicio: float) -> dict:
    """O plano com os keyframes do contorno levados do quadro da FONTE para o tempo da composição.

    ⛔ MEDIDO 2026-11-24 (Resolve Studio 21.1, Mac, PRODC R04): a composição de clipe nasce com `GlobalStart` =
    −(quadro da fonte do In) e `RenderStart` 0 — o tempo dela começa no In, não no quadro 0 do arquivo como no 19
    (banco, drt-drp/estruturas.md §Composição do Fusion). Keyframes no quadro da fonte (477…) caíam FORA da faixa da
    composição (0–122) e a máscara tirava o plano inteiro (LOU_7237: preto; o wipe do C0296 sumia)."""
    if not inicio:
        return pl
    novo = {**pl, "nos": []}
    for no in pl.get("nos") or []:
        if no.get("quadros"):
            no = {**no, "quadros": [int(q + round(inicio)) for q in no["quadros"]]}
        novo["nos"].append(no)
    return novo


def _tem_animacao(pl: dict) -> bool:
    return any(no.get("quadros") for no in pl.get("nos") or [])


def executar(item, pl: dict) -> dict:
    """Cria UMA composição no `TimelineItem` com o plano. O MESMO caminho da casca (`executarPlano`).

    ⚠️ MEDIDO 2026-10-03 (Resolve 19.0.0b.59, Windows, caso R02): `ImportFusionComp` num clipe que
    JÁ tem composição devolve um objeto e NÃO muda nada; num clipe SEM composição cria a composição
    e religa o MediaIn à mídia do clipe. No 21.1 (Mac), substitui a ATIVA. Então: A) clipe sem
    composição → importa direto `compor(MODELO)`; B) senão, ou se A não pegou → `AddFusionComp` →
    `ExportFusionComp` → `compor` → `ImportFusionComp`. Os dois conferidos pelo export de volta.
    `{ok, comp, erro}`."""
    try:
        direto = compor(MODELO, pl)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}
    if not (item.GetFusionCompNameList() or []):
        arq = _arquivo_comp()
        try:
            with open(arq, "w", encoding="utf-8") as f:
                f.write(direto)
            item.ImportFusionComp(arq)
        finally:
            try:
                os.remove(arq)
            except OSError:
                pass
        nomes = item.GetFusionCompNameList() or []
        if nomes and _montada(item, len(nomes), pl):
            inicio = _inicio_da_comp(item, len(nomes)) if _tem_animacao(pl) else 0.0
            if not inicio:
                return {"ok": True, "comp": nomes[-1]}
            # ⛔ Resolve 21: o tempo da composição começa no In — remonta com o contorno no tempo dela (o 21.1
            #    substitui a composição ATIVA no `ImportFusionComp`).
            arq = _arquivo_comp()
            try:
                with open(arq, "w", encoding="utf-8") as f:
                    f.write(compor(MODELO, no_tempo_da_comp(pl, inicio)))
                item.ImportFusionComp(arq)
            finally:
                try:
                    os.remove(arq)
                except OSError:
                    pass
            nomes = item.GetFusionCompNameList() or []
            if nomes and _montada(item, len(nomes), pl):
                return {"ok": True, "comp": nomes[-1], "inicio": inicio}
            return {"ok": False, "comp": nomes[-1] if nomes else None,
                    "erro": "o Resolve não remontou a máscara no tempo da composição — refazer à mão no Fusion"}
        if nomes and not item.DeleteFusionCompByName(nomes[-1]):
            # o import criou uma composição que não confere e o Resolve não a apaga (o 19 não apaga a
            # única): o caminho B ia empilhar outra por cima — melhor parar e dizer (revisão 2026-10-03)
            return {"ok": False, "comp": nomes[-1],
                    "erro": "o Resolve não montou a composição — refazer à mão no Fusion"}
    item.AddFusionComp()
    nomes = item.GetFusionCompNameList() or []
    if not nomes:
        return {"ok": False, "erro": "AddFusionComp falhou"}
    nome = nomes[-1]
    item.LoadFusionCompByName(nome)
    arq = _arquivo_comp()
    try:
        if not item.ExportFusionComp(arq, len(nomes)):
            return {"ok": False, "comp": nome, "erro": "ExportFusionComp falhou"}
        with open(arq, encoding="utf-8") as f:
            texto = f.read()
        inicio = _inicio_da_comp(item, len(nomes)) if _tem_animacao(pl) else 0.0
        try:
            texto = compor(texto, no_tempo_da_comp(pl, inicio))
        except ValueError as e:
            return {"ok": False, "comp": nome, "erro": str(e)}
        with open(arq, "w", encoding="utf-8") as f:
            f.write(texto)
        item.ImportFusionComp(arq)
    finally:
        try:
            os.remove(arq)
        except OSError:
            pass
    if not _montada(item, len(nomes), pl):
        try:
            item.DeleteFusionCompByName(nome)
        except Exception:  # noqa: BLE001 — a vazia fica; o erro diz o que fazer
            pass
        return {"ok": False, "comp": nome, "erro": "o Resolve não montou a composição — refazer à mão no Fusion"}
    return {"ok": True, "comp": nome}


def aplicar(item, receitas) -> dict:
    """`executar(item, plano(receitas))`; aceita uma receita só (dict)."""
    if isinstance(receitas, dict):
        receitas = [receitas]
    try:
        pl = plano(receitas)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}
    return executar(item, pl)


def agrupar(entradas: list[dict]) -> list[dict]:
    """Uma entrada por CLIPE (trilha, quadro, arquivo), com as receitas na ordem e o plano."""
    por: dict[tuple, dict] = {}
    for e in entradas:
        k = (e["trilha"], e["quadro"], e["arquivo"])
        g = por.setdefault(k, {"trilha": e["trilha"], "quadro": e["quadro"], "arquivo": e["arquivo"],
                               "duracao": e.get("duracao"), "segmento": e.get("segmento"),
                               "nomes": [], "receitas": []})
        g["nomes"].append(e["nome"])
        g["receitas"].append(e["receita"])
    out = []
    for g in por.values():
        try:
            g["plano"] = plano(g["receitas"])
        except ValueError as e:
            g["plano"], g["erro"] = None, str(e)
        out.append(g)
    return out


def aplicar_relatorio(timeline, relatorio: dict) -> list[dict]:
    """Executa os planos do relatório na `timeline` recém-importada. O item é achado pela trilha,
    pelo quadro de início (contado do início da timeline) e pelo nome do arquivo."""
    inicio = timeline.GetStartFrame()
    out = []
    for g in relatorio.get("fusion") or []:
        base = {k: g[k] for k in ("trilha", "quadro", "arquivo")} | {"nome": " + ".join(g["nomes"])}
        if not g.get("plano"):
            out.append({**base, "ok": False, "erro": g.get("erro") or "sem plano"})
            continue
        alvo = None
        for it in timeline.GetItemListInTrack("video", g["trilha"]) or []:
            if it.GetStart() - inicio == g["quadro"] and it.GetName() == g["arquivo"]:
                alvo = it
                break
        if alvo is None:
            out.append({**base, "ok": False, "erro": "item não encontrado na timeline"})
            continue
        try:
            res = executar(alvo, g["plano"])
        except Exception as e:                       # noqa: BLE001 — registra e segue
            res = {"ok": False, "erro": f"{type(e).__name__}: {e}"}
        out.append({**base, **res})
    return out
