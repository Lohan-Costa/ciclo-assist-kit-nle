"""A COR do Media Composer no Premiere (2026-11-20; autor: controles EDITÁVEIS, LUT de reserva) — as contas.

O que o laboratório provou na carta B24 (Premiere 26.5.2 e 27.0.0 idênticos; `laboratorio-de-midia/resultados/B24_COR_MC/
PREMIERE.md`; o CC real da PRODA: 0,45 / 1,46 e 0,54 / 2,57 código dentro de 16–235):

    Mas Sat S (%)              → ProcAmp › Saturation = S (preserva o Y' BT.601; o MC, o 709 — é o resíduo)
    Curves › Master do MC      → Lumetri › RGB Curves: a MESMA curva nos canais R, G e B (blocos 1–3 do param 39),
                                 a mestra neutra — ⛔ a mestra da Lumetri PRESERVA O MATIZ e o MC é canal a canal

A curva da Lumetri: eixo = a faixa de VÍDEO (u = (código − 16)/219, nos dois eixos), SPLINE NATURAL, plana fora das
pontas. A Catmull-Rom do MC (t = código/255) não passa sem perda: os nós do MC + pontos a mais onde o erro é maior, até
≤ 0,25 código no papel (o blob guarda 32). Porte em Python puro de `lab/bancadas/premiere_cor_mc.curva_lumetri_do_mc`.

⛔ A Saturation da Lumetri NÃO serve (preserva a luminância LINEAR: 2,8 / 27,5 contra o MC) — por isso o ProcAmp.
"""
from __future__ import annotations

import struct


# ── as duas curvas, em Python puro e SEM importar o motor do Conformar ────────────────────────────────────────────────
# ⛔ Importar o motor põe o caminho dele no `sys.path`, e o `tools/` dele (um pacote) passa a sombrear o `tools/` do app
#   (uma pasta solta) — 2 testes do app caíram assim (2026-11-20). As MESMAS contas de `drp/cor_mc.py` (a curva do MC)
#   e de `prproj/leitura.py::_spline_natural` (a da Lumetri); conferidas contra a bancada do lab (≤ 1e-16).
def _tangentes(xs, ys) -> list[float]:
    """Catmull-Rom (secante dos vizinhos); nas pontas, a secante do segmento — a curva do MC."""
    if len(xs) == 2:
        s = (ys[1] - ys[0]) / (xs[1] - xs[0])
        return [s, s]
    return ([(ys[1] - ys[0]) / (xs[1] - xs[0])]
            + [(ys[i + 1] - ys[i - 1]) / (xs[i + 1] - xs[i - 1]) for i in range(1, len(xs) - 1)]
            + [(ys[-1] - ys[-2]) / (xs[-1] - xs[-2])])


def _mc(xs, ys, ms, t: float, j: int | None) -> float:
    if j is None:                                  # fora das pontas: plana
        return ys[0] if t <= xs[0] else ys[-1]
    h = xs[j + 1] - xs[j]
    s = (t - xs[j]) / h
    return ((2 * s**3 - 3 * s**2 + 1) * ys[j] + (s**3 - 2 * s**2 + s) * h * ms[j]
            + (-2 * s**3 + 3 * s**2) * ys[j + 1] + (s**3 - s**2) * h * ms[j + 1])


def _spline_natural(pts):
    """A curva da Lumetri: spline cúbica natural; plana fora das pontas."""
    unicos: dict[float, float] = {}
    for x_, y_ in sorted(pts):
        unicos[round(x_, 9)] = y_
    xs, ys = list(unicos), list(unicos.values())
    n = len(xs)
    if n == 1:
        return lambda v, y=ys[0]: y
    m = [0.0] * n
    if n > 2:
        h = [xs[i + 1] - xs[i] for i in range(n - 1)]
        a, b, c, r = [0.0] * n, [1.0] * n, [0.0] * n, [0.0] * n
        for i in range(1, n - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            r[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
        for i in range(1, n):
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
        return (m[i] * t ** 3 + m[i + 1] * u ** 3) * h * h / 6 + (ys[i] - m[i] * h * h / 6) * t             + (ys[i + 1] - m[i + 1] * h * h / 6) * u
    return f


#: o blob da curva da Lumetri (ParameterID 39): 4 blocos de 520 bytes — mestra, R, G, B; cada um `u32 tipo, u32 n` + 32
#: pares (x, y) em double (0–1). O bloco 0 fica como está (neutro).
PARAM_CURVA, TAM_BLOCO, BLOCOS_RGB, MAX_PONTOS = "39", 520, (1, 2, 3), 32


def _alvo(pontos):
    """A curva do MC no eixo da Lumetri: G(u), u e G em (código − 16)/219."""
    P = sorted((float(x), float(y)) for x, y in pontos)
    xs, ys = [x for x, _ in P], [y for _, y in P]
    ms = _tangentes(xs, ys)

    def G(u: float) -> float:
        t = min(max((16 + 219 * u) / 255, 0.0), 1.0)
        j = None if t < xs[0] or t > xs[-1] else next(i for i in range(len(xs) - 1) if xs[i] <= t <= xs[i + 1])
        return (255 * _mc(xs, ys, ms, t, j) - 16) / 219
    return G


def curva_lumetri_do_mc(pontos, maximo: int = MAX_PONTOS, tolerancia: float = 0.25) -> tuple[list[tuple[float, float]], float]:
    """(os pontos da curva da Lumetri, o erro máximo no papel em códigos de 8 bits)."""
    G = _alvo(pontos)
    us = [i / 2000 for i in range(2001)]
    alvo = [G(u) for u in us]
    xs = sorted({0.0, 1.0} | {round((255 * x - 16) / 219, 6) for x, _ in pontos if 0 < (255 * x - 16) / 219 < 1})
    while True:
        P = [(x, G(x)) for x in xs]
        f = _spline_natural(P)
        erros = [abs(f(u) - a) * 219 for u, a in zip(us, alvo)]
        pior = max(erros)
        if pior <= tolerancia or len(xs) >= maximo:
            return P, pior
        novo = us[erros.index(pior)]
        if any(abs(novo - x) < 1e-4 for x in xs):
            return P, pior
        xs = sorted(xs + [novo])


def bloco(pontos, tipo: int = 0) -> bytes:
    b = struct.pack("<II", tipo, len(pontos)) + b"".join(struct.pack("<dd", x, y) for x, y in pontos)
    return b + b"\0" * (TAM_BLOCO - len(b))


def blob_com_a_curva(velho: bytes, pontos) -> bytes:
    """O blob do param 39 com `pontos` nos canais R, G e B (o tipo de cada bloco mantido); a mestra intacta."""
    if len(velho) < TAM_BLOCO * 4:
        raise ValueError(f"o blob da curva da Lumetri tem {len(velho)} bytes (esperado {TAM_BLOCO * 4})")
    novo = bytearray(velho)
    for bl in BLOCOS_RGB:
        tipo = struct.unpack("<I", velho[bl * TAM_BLOCO:bl * TAM_BLOCO + 4])[0]
        novo[bl * TAM_BLOCO:(bl + 1) * TAM_BLOCO] = bloco(pontos, tipo)
    return bytes(novo)


def cor_do_efeito(e: dict) -> dict | None:
    """O `params.cor_mc` (`{sat, curva}`) de um efeito da Carta (o leitor de bin do Conformar o põe no CC que se traduz
    INTEIRO) — ou None."""
    cc = (e.get("params") or {}).get("cor_mc")
    return cc if isinstance(cc, dict) and (cc.get("sat") is not None or cc.get("curva")) else None
