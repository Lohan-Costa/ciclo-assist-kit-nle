"""rampa.py — a rampa de velocidade entre NLEs, no modelo neutro: a POSIÇÃO da fonte em cada quadro.

Regra do autor (2026-10-12; banco `transversal/tempo-e-timecode.md`, organograma "Rampas entre os três"): entre NLEs
DIFERENTES a curva não é recriada — vai a posição exata de cada quadro (os três mostram o PISO dela); a curva nativa
só de Avid para Avid. O laboratório provou os seis sentidos 48/48 (casos A e B do B22).

Aqui ficam as três peças que os escritores e leitores usam, sem saber de formato:

- `posicoes(seg)` — a posição (relativa ao `source_start_frames`) em cada quadro inteiro do plano, do
  `source_offset_map` da Carta.
- `keyframes_hibridos(pos)` — os quadros onde a velocidade MUDA (+ o primeiro e o último): com interpolação linear
  entre eles, todo quadro cai no valor exato. É o "gráfico de posição híbrido" do Avid (medido: K1 144/144).
- `posicoes_do_timemap(...)` — o leitor do Resolve: o keyframe Bézier (`interp 1`) ARREDONDA O CANTO — reta até a
  ponta da alça de entrada, Bézier cúbica com os dois controles no próprio keyframe até a ponta da alça de saída, e reta
  (medido no Resolve 19.0, B22: 48/48; a hipótese "Bézier entre keyframes" errava até 2 quadros).
"""
from __future__ import annotations

import math

#: o retime da Carta → o `_SFX_RENDER` do Timewarp do Avid (tipos LIDOS na tela do MC 25.6, 2026-10-12):
#: 2 Both Fields (o quadro inteiro — o piso, e o que os presets usam), 6 FluidMotion (= Optical Flow, autor).
#: Frame Blend NÃO se correlaciona (decisão do autor): vai o quadro inteiro.
RENDER_AVID = {"optical_flow": 6}
RENDER_AVID_PADRAO = 2

_TOL = 1e-6


def _interp(mapa: list, t: float) -> float:
    if t <= mapa[0][0]:
        return float(mapa[0][1])
    for (t0, v0), (t1, v1) in zip(mapa, mapa[1:]):
        if t0 <= t <= t1:
            return float(v0) if t1 == t0 else float(v0) + (float(v1) - float(v0)) * (t - t0) / (t1 - t0)
    return float(mapa[-1][1])


def posicoes(seg: dict) -> list[float]:
    """A posição da fonte (relativa ao in do plano) em cada quadro 0..duração-1, do `source_offset_map`."""
    mapa = sorted((float(t), float(v)) for t, v in (seg.get("source_offset_map") or []))
    n = int(seg.get("duration_frames") or 0)
    if not mapa or n <= 0:
        return []
    return [_interp(mapa, float(k)) for k in range(n)]


def keyframes_hibridos(pos: list[float], tol: float = _TOL) -> list[int]:
    """Os quadros que precisam de keyframe para a interpolação LINEAR reproduzir `pos` exatamente: o primeiro, o
    último e cada quadro em que a velocidade (a diferença entre vizinhos) muda."""
    n = len(pos)
    if n <= 2:
        return list(range(n))
    out = [0]
    for k in range(1, n - 1):
        if abs((pos[k + 1] - pos[k]) - (pos[k] - pos[k - 1])) > tol:
            out.append(k)
    out.append(n - 1)
    return out


def e_curva(pos: list[float], tol: float = _TOL) -> bool:
    """Se a velocidade muda em algum quadro (rampa) ou é a mesma do começo ao fim (constante)."""
    return len(keyframes_hibridos(pos, tol)) > 2


def render_avid(retime: str | None) -> int:
    return RENDER_AVID.get(retime or "", RENDER_AVID_PADRAO)


# ── o leitor do Resolve ───────────────────────────────────────────────────────────────────────────

def _bez(p0: float, p1: float, p2: float, p3: float, u: float) -> float:
    a = 1 - u
    return a * a * a * p0 + 3 * a * a * u * p1 + 3 * a * u * u * p2 + u * u * u * p3


def avaliar_resolve(kfs: list[dict], x: float) -> float:
    """O valor da curva de tempo do Resolve em `x` (keyframes {X, Y, XIn, YIn, XOut, YOut, interp}, na MESMA unidade
    nos dois eixos). `interp 1` = canto arredondado (ver o cabeçalho); os outros, reta até o vizinho."""
    kfs = sorted(kfs, key=lambda k: k["X"])
    for k in kfs:
        if k["interp"] == 1:
            xi, yi = k["X"] - k["XIn"], k["Y"] - k["YIn"]
            xo, yo = k["X"] + k["XOut"], k["Y"] + k["YOut"]
            if xi <= x <= xo and xo > xi:
                lo, hi = 0.0, 1.0
                for _ in range(60):
                    u = (lo + hi) / 2
                    if _bez(xi, k["X"], k["X"], xo, u) < x:
                        lo = u
                    else:
                        hi = u
                return _bez(yi, k["Y"], k["Y"], yo, (lo + hi) / 2)
    vs = []
    for k in kfs:
        if k["interp"] == 1:
            vs += [(k["X"] - k["XIn"], k["Y"] - k["YIn"]), (k["X"] + k["XOut"], k["Y"] + k["YOut"])]
        else:
            vs.append((k["X"], k["Y"]))
    vs.sort()
    if x <= vs[0][0]:
        return vs[0][1]
    for (x0, y0), (x1, y1) in zip(vs, vs[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return vs[-1][1]


def keyframes_do_timemap(hexstr: str, fps: float) -> list[dict]:
    """Os keyframes do `MediaTimemapBA` de um clipe do DRT, em QUADROS (o blob guarda segundos)."""
    from tools.inspect_drp import timemap_decode
    d = timemap_decode(hexstr)
    kb = next((it for it in d.get("items") or [] if it.get("key") == "KeyframesBA"), None)
    if kb is None:
        return []
    out = []
    for e in kb["value"]["entries"]:
        k = {}
        for c in e["value"]["entries"]:
            v = c["value"]
            k[c["key"]] = int(v["int"]) if c["key"] == "interp" else float(v["dbl"]) * fps
        out.append(k)
    return sorted(out, key=lambda k: k["X"])


def posicoes_do_timemap(kfs: list[dict], entrada: float, n: int, inicio_fonte: float = 0.0) -> list[float]:
    """As posições da fonte (relativas a `inicio_fonte`) nos quadros 0..n-1 de um plano cujo eixo do timemap começa
    `entrada` quadros antes do in (o mesmo `entrada` que o escritor usa)."""
    return [avaliar_resolve(kfs, entrada + k) - inicio_fonte for k in range(n)]


def para_offset_map(pos: list[float]) -> list[tuple[float, float]]:
    """As posições como `source_offset_map` da Carta ([(quadro, posição)])."""
    return [(float(k), float(v)) for k, v in enumerate(pos)]


def piso(pos: list[float]) -> list[int]:
    """O quadro da fonte que os três NLEs mostram (o piso, com a folga do arredondamento binário)."""
    return [math.floor(p + 1e-6) for p in pos]
