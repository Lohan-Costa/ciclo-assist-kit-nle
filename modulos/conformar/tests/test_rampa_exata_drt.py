"""Rampa de velocidade no DRT: o quadro que o Resolve mostra tem de ser o da origem (2026-10-12, laboratório B22).

Rodar:

    .venv/bin/python tests/test_rampa_exata_drt.py        (Windows: .venv-win/Scripts/python)

O Resolve mostra o PISO da curva (`MediaTimemapBA`, keyframes lineares) no instante de cada quadro — medido render ×
render pelo código de barras da placa B02. O `build_adaptive_ramp_timemap` simplificava a curva por Douglas-Peucker com
meio quadro de tolerância: Avid → Resolve e Premiere → Resolve davam 43/48 (constante → curva → constante) e 39/48
(começa dentro da curva). Agora: só os quadros inteiros, só colineares se juntam e +0,001 quadro no Y — 48/48 nos dois
sentidos. Aqui, sem o Resolve: a curva gravada, lida de volta e avaliada como o Resolve avalia, dá o piso da origem em
todo quadro — inclusive nas posições INTEIRAS exatas de um trecho constante (o caso que caía no quadro de baixo).
"""
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from tools.inspect_drp import build_adaptive_ramp_timemap, timemap_decode  # noqa: E402

casos = 0
falhas: list[str] = []
F = 24000 / 1001


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    passou = obtido == esperado
    print(f"  {'✓' if passou else '✗'} {nome}" + ("" if passou else f": {obtido!r} ≠ {esperado!r}"))
    if not passou:
        falhas.append(nome)


def pontos(hexstr: str) -> list[tuple[float, float]]:
    d = timemap_decode(hexstr)
    kb = next(it for it in d["items"] if it["key"] == "KeyframesBA")["value"]["entries"]
    pts = []
    for k in kb:
        e = {x["key"]: x["value"] for x in k["value"]["entries"]}
        pts.append((e["X"]["dbl"], e["Y"]["dbl"]))
    return sorted(pts)


def no_resolve(pts, k: int, fps: float) -> int:
    """O quadro que o Resolve mostra no quadro `k` do plano: piso da reta entre keyframes (interp 0)."""
    x = k / fps
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return math.floor((y0 + (y1 - y0) * (x - x0) / (x1 - x0)) * fps + 1e-9)
    raise ValueError(k)


def mapa_meio_quadro(pos) -> list[tuple[float, float]]:
    """Como o mapa do Avid chega: de meio em meio quadro (o meio é a média — só os inteiros valem)."""
    out = []
    for k, p in enumerate(pos):
        out.append((float(k), p))
        if k + 1 < len(pos):
            out.append((k + 0.5, (p + pos[k + 1]) / 2 + 0.3))      # o meio "errado" de propósito: tem de ser ignorado
    return out


def caso(nome, pos, nb=240):
    tm = build_adaptive_ramp_timemap(nb, F, mapa_meio_quadro(pos), 0, F)
    pts = pontos(tm)
    vistos = [no_resolve(pts, k, F) for k in range(len(pos))]
    ok(f"{nome}: o piso da origem em todo quadro ({len(pts)} keyframes)", vistos,
       [math.floor(p + 1e-9) for p in pos])
    return pts


def main() -> int:
    # A: 1,2× → transição (quadros 12–30) → 1,9× (posições do Premiere: a reta da velocidade)
    a = []
    for k in range(48):
        if k <= 12:
            a.append(1.2 * k)
        elif k <= 30:
            u = k - 12
            a.append(14.4 + 1.2 * u + 0.7 * u * u / 36)
        else:
            a.append(a[30] + 1.9 * (k - 30))
    caso("A — constante → curva → constante", a)
    # B: desacelera nos 14 primeiros quadros e fica em 0,6× — as posições 14,0, 17,0, 20,0… são INTEIRAS
    b = [k * 1.4 - 0.4 * k * k / 28 for k in range(15)]
    b = [x * 14 / b[14] for x in b]
    b += [14 + 0.6 * (k - 14) for k in range(15, 48)]
    pts = caso("B — começa na curva, constante a 0,6× com posições inteiras", b)
    ok("B: o trecho constante fica com as pontas (colineares juntados)", len(pts) < 48 + 2, True)
    # constante pura: dois pontos bastam
    c = [0.5 * k for k in range(48)]
    caso("C — 50 % constante", c)
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
