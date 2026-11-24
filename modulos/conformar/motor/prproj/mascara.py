"""Máscara do Premiere (`AE.ADBE AEMask2`) → Polygon do Fusion.

O contorno (`Path`) vem em base64 por keyframe. Estrutura `inferido` (PRODB, Premiere 26.0.2,
2026-10-03): 17 bytes de cabeçalho; `u32` nº de vértices; por vértice `u32` (1 = suave, 0 = canto)
+ 3 pontos `f32` (x, y): o VÉRTICE, a tangente de ENTRADA e a de SAÍDA, normalizados (0–1) no
quadro da FONTE do clipe, com Y para baixo.

A receita sai em JSON (`receita`) e vira Polygon do Fusion em `drp/fusion_clipe.py`, que roda
dentro do Resolve depois do import.
"""
from __future__ import annotations

import base64
import math
import re
import struct

from .projeto import Projeto, Obj


def _vertices(b64: str) -> list[tuple[bool, tuple, tuple, tuple]]:
    raw = base64.b64decode(b64)
    if raw[:4] == b"2cin":
        # A máscara de OPACIDADE do Premiere 22/23 (`AE.ADBE AEMask`, R04 PRODUCAO-C, 2026-10-10):
        # `2cin` + u32 2 + u32 0 + u32 N; por vértice 32 bytes: u32 (1 = suave, 0 = canto), o vértice e
        # as alças de entrada e de saída (6 f32, 0–1 no quadro da FONTE, Y para baixo; fora de 0–1 =
        # fora do quadro, normal num wipe) e um u32 de fechamento. Conferido pela referência: o contorno
        # do C0296 (wipe do véu) cobre 99,3 % da área visível no quadro em que ele já fechou.
        n = struct.unpack_from("<I", raw, 12)[0]
        out = []
        for v in range(n):
            f = struct.unpack_from("<I6f", raw, 16 + 32 * v)
            out.append((bool(f[0]), (f[1], f[2]), (f[3], f[4]), (f[5], f[6])))
        return out
    n = struct.unpack("<I", raw[17:21])[0]
    out = []
    for v in range(n):
        f = struct.unpack("<I6f", raw[21 + 28 * v:21 + 28 * (v + 1)])
        out.append((bool(f[0]), (f[1], f[2]), (f[3], f[4]), (f[5], f[6])))
    return out


def _pontos(proj: Projeto, prm: Obj) -> list[tuple[int | None, list]]:
    """[(tempo em ticks ou None, vértices)] do parâmetro `Path`."""
    kfs = proj.campo(prm, "Keyframes")
    if kfs:
        out = []
        for k in kfs.strip(";").split(";"):
            partes = k.split(",")
            if len(partes) >= 2:
                out.append((int(partes[0]), _vertices(partes[1])))
        return out
    b64 = proj.valor_inicial(prm)                    # resolve o BinaryHash (projeto.py)
    return [(None, _vertices(b64))] if b64 else []


def ler_mascaras(proj: Projeto, componente: Obj) -> list[dict]:
    """As máscaras (`SubComponent`) de um efeito: contorno, transformação, invertida, suavidade."""
    out = []
    for sub in proj.refs(componente, "SubComponent"):
        tipo = proj.campo(sub, "MatchName")
        if tipo not in ("AE.ADBE AEMask2", "AE.ADBE AEMask"):
            continue
        params = proj.refs(sub, "Param")
        d: dict = {"contornos": [], "invertida": False}
        for i, prm in enumerate(params):
            nome = proj.campo(prm, "Name")
            if tipo == "AE.ADBE AEMask":
                # a máscara de opacidade do 22/23: os nomes com "Mask " na frente; o "Inverted" é o
                # booleano sem nome de ParameterID 10 (`hipotese`: falso nas 12 do R04, que não são invertidas)
                if proj.campo(prm, "ParameterID") == "10":
                    sk10 = (proj.campo(prm, "StartKeyframe") or "").split(",")
                    d["invertida"] = (sk10[1] if len(sk10) > 1 else "").lower() == "true"
                    continue
                nome = {"Mask Path": "Path", "Mask Feather": "Feather", "Mask Opacity": "Opacity",
                        "Mask Expansion": "Expansion"}.get(nome, nome)
            sk = (proj.campo(prm, "StartKeyframe") or "").split(",")
            kfs = proj.campo(prm, "Keyframes")
            valor = (kfs.strip(";").split(";")[-1].split(",")[1] if kfs else (sk[1] if len(sk) > 1 else None))
            if nome == "Path":
                d["contornos"] = _pontos(proj, prm)
            elif nome in ("Position", "Anchor Point", "Rotation", "Scale Height", "Scale Width",
                          "Feather", "Opacity", "Expansion"):
                d[nome] = valor
            elif nome is None and i == 22:
                # `hipotese`: o booleano sem nome na posição 22 é o "Inverted" (ligado no insert do
                # interfone, onde o export mostra só o de DENTRO do contorno).
                d["invertida"] = (valor or "").lower() == "true"
        if d["contornos"]:
            out.append(d)
    return out


def _transformada(vertices: list, m: dict, fonte: tuple[int, int]) -> list:
    """Aplica a transformação da própria máscara (Position, Anchor Point, Scale Height/Width,
    Rotation — tudo no quadro da FONTE, normalizado) aos vértices. Identidade no PRODB."""
    from .leitura import _float, _ponto      # import tardio: leitura importa este módulo
    px, py = _ponto(m.get("Position"), (0.0, 0.0))
    ax, ay = _ponto(m.get("Anchor Point"), (px, py))
    sx = (_float(m.get("Scale Width"), 100.0) or 0.0) / 100.0
    sy = (_float(m.get("Scale Height"), 100.0) or 0.0) / 100.0
    rot = _float(m.get("Rotation"), 0.0) or 0.0
    if abs(px - ax) < 1e-9 and abs(py - ay) < 1e-9 and sx == sy == 1.0 and rot == 0.0:
        return vertices
    fw, fh = fonte if fonte[0] and fonte[1] else (1, 1)
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))

    def ponto(x, y):                          # em px da fonte, a partir da âncora; Y para baixo
        dx, dy = (x - ax) * fw * sx, (y - ay) * fh * sy
        return (px + (c * dx - s * dy) / fw, py + (s * dx + c * dy) / fh)
    return [(su, ponto(*v), ponto(*i), ponto(*o)) for su, v, i, o in vertices]


def para_fonte_de_dentro(vertices: list, g, quadro_take: tuple[int, int],
                         fonte: tuple[int, int]) -> list:
    """Máscara num plano que aponta para um take aninhado: o contorno está no QUADRO do take
    (normalizado); a composição do Fusion fica na FONTE do clipe de dentro. Volta pela inversa
    da geometria de dentro do take (`g`: fonte → take, px centrados, Y para baixo)."""
    qw, qh = quadro_take
    fw, fh = fonte
    c, s = math.cos(math.radians(-g.rot)), math.sin(math.radians(-g.rot))

    def ponto(x, y):
        X, Y = (x - 0.5) * qw - g.tx, (y - 0.5) * qh - g.ty
        X, Y = (c * X - s * Y) / (g.esc * getattr(g, "asp", 1.0)), (s * X + c * Y) / g.esc
        return (X / fw + 0.5, Y / fh + 0.5)
    return [(su, ponto(*v), ponto(*i), ponto(*o)) for su, v, i, o in vertices]


def receita(efeito: str, mascaras: list[dict], fonte: tuple[int, int], avisos: list,
            **extra) -> dict:
    """O que a composição do Fusion precisa, em JSON: o efeito (`recorte` = Crop com máscara,
    `desfoque` = Gaussian Blur), e por máscara o contorno (vértices na FONTE, normalizados, Y
    para baixo), se é invertida e a suavidade em px."""
    from .leitura import _float
    out = []
    for m in mascaras:
        verts = _transformada(m["contornos"][0][1], m, fonte)
        expansao = _float(m.get("Expansion"), 0.0) or 0.0
        if expansao:
            avisos.append("máscara com Expansion: traduzida como Border Width do Polygon, conferir")
        if (_float(m.get("Opacity"), 100.0) or 100.0) < 100.0:
            avisos.append("máscara com Opacity < 100: não traduzido")
        d = {"vertices": [[su, list(v), list(i), list(o)] for su, v, i, o in verts],
             "invertida": m["invertida"], "suave_px": _float(m.get("Feather"), 0.0) or 0.0,
             "expansao_px": expansao}
        if len(m["contornos"]) > 1:
            # CONTORNO ANIMADO: um contorno por keyframe, no tempo da MÍDIA do item (ticks); o
            # `_segmento` o leva a quadros da FONTE — o tempo da composição do Fusion de um clipe
            # (medido no Resolve 19: a composição vai de 0 ao fim do ARQUIVO, na taxa dele).
            d["quadros"] = [{"t": t, "vertices": [[su, list(v), list(i), list(o)]
                                                  for su, v, i, o in _transformada(vs, m, fonte)]}
                            for t, vs in m["contornos"] if t is not None]
        out.append(d)
    return {"efeito": efeito, "mascaras": out, "fonte_px": list(fonte), **extra}
