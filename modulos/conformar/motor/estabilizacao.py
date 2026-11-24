"""O Stabilize do Media Composer → a correção que ele aplica, quadro a quadro, para o estabilizador do Resolve.

⭐ Pedido do autor (2026-10-24): a estabilização do Avid chega PRONTA e LIGADA no Resolve; a nota passa a dizer
"ESTABILIZAÇÃO TRADUZIDA". A conta é a medida no laboratório (banco `protocolos/avb/estruturas.md` §Stabilize, lab
`resultados/B19_ESTABILIZADOR/AVID.md`, MC 24.6.0, tremor CONHECIDO, resíduo 0,10/0,06 px):

    R(q) = Z( T(q + u) ),   u(k) = p(k) − G_σ(p)(k) + (−POS_X·W, +POS_Y·H)/1000/Z,   σ = 30 × filtro QUADROS

p = o ponto rastreado ("Point A", fração do quadro, origem em cima à esquerda, um ponto por quadro do SEGMENTO),
G_σ = gaussiana com a borda "nearest" (repete o 1º e o último), Z = o Auto-Zoom (`DVE_SCALE_X_U` ÷ 100) em torno do
centro. ⚠️ O sinal do deslocamento fixo é o dos NÚMEROS medidos (23,976: POS −2,02/+0,062 → +3,64/+0,04 px; 50p:
−0,116/+0,391 → +0,19/+0,38): o X troca de sinal e o Y não (no Avid +Y é para CIMA; na imagem, para baixo) — o banco
escrevia "+ (POS_X·W, POS_Y·H)". Aqui tudo sai em FRAÇÃO do quadro: o estabilizador do Resolve trabalha na própria escala de análise
(`drp/estabilizador.py` faz a ponte).

Só o modo medido vira tradução: um ponto, remover tremor (`jitter_removal`) sem `smoothing`. O resto (Region
Stabilize, vários pontos, suavizar) fica com a nota de antes ("ESTABILIZADO NO AVID", para refazer).
⏳ Os pontos rastreados ALÉM do fim do segmento (PRODA: 342 pontos num efeito de 203) ficam de fora — no lab o
rastreio era do clipe inteiro; o teste das pontas (o G usa os de fora?) está pendente.
"""

from __future__ import annotations

import math
import struct

#: Teto de quadros de um segmento estabilizado (o plano vai inteiro no relatório: 2 números por quadro).
MAX_QUADROS = 20_000


def _raster(settings) -> tuple[int, int] | None:
    """Os 56 bytes de `settings` do tracker: `u16 W, u16 H` no byte 14 (1920×1080 = `80 07 38 04`)."""
    try:
        b = bytes(bytearray(settings))
        w, h = struct.unpack_from("<HH", b, 14)
    except (TypeError, ValueError, struct.error):
        return None
    return (w, h) if 16 <= w <= 16384 and 16 <= h <= 16384 else None


def _amostrar(pontos: list, n: int) -> list[float] | None:
    """[(quadro, valor)] → um valor por quadro 0..n−1 (linear entre os pontos; fora deles, o da ponta)."""
    pts = sorted((float(q), float(v)) for q, v in pontos if math.isfinite(float(q)) and math.isfinite(float(v)))
    if not pts or n <= 0:
        return None
    fora, j = [], 0
    for k in range(n):
        while j + 1 < len(pts) and pts[j + 1][0] <= k:
            j += 1
        (q0, v0) = pts[j]
        if k <= q0 or j + 1 == len(pts):
            fora.append(v0)
        else:
            q1, v1 = pts[j + 1]
            fora.append(v0 + (v1 - v0) * (k - q0) / (q1 - q0))
    return fora


def _montar(x: list, y: list, filtro, jitter, smoothing, raster, pos_x, pos_y, zoom_pct) -> dict | None:
    if not (x and y and len(x) == len(y)) or not jitter or smoothing:
        return None
    try:
        filtro, zoom = float(filtro), float(zoom_pct or 100.0) / 100.0
        pos = [float(pos_x or 0.0), float(pos_y or 0.0)]
    except (TypeError, ValueError):
        return None
    if not (0 < filtro <= 10 and 0.1 <= zoom <= 10 and all(math.isfinite(v) for v in pos)):
        return None
    return {"filtro": round(filtro, 6), "zoom": round(zoom, 6), "pos": [round(v, 6) for v in pos],
            "raster": list(raster) if raster else None,
            "x": [round(v, 7) for v in x], "y": [round(v, 7) for v in y]}


def do_aaf(op_group, comprimento: int) -> dict | None:
    """O tracker do `OperationGroup` "Stabilize_2" (propriedades privadas `OpGrpTKMNTrackerDataAry`, que o leitor de
    parâmetros não vê). O ponto k está no tempo k/comprimento do efeito (= o quadro k do segmento)."""
    try:
        tds = list(op_group["OpGrpTKMNTrackerDataAry"].value or [])
    except Exception:  # noqa: BLE001 — sem tracker no AAF: fica a nota de antes
        return None
    n = int(comprimento or 0)
    if len(tds) != 1 or not 0 < n <= MAX_QUADROS:
        return None
    td = tds[0]

    def valor(nome, padrao=None):
        try:
            return td[nome].value
        except Exception:  # noqa: BLE001
            return padrao

    def curva(nome):
        try:
            pts = [(float(c.time) * n, float(c.value)) for c in td[nome].value["PointList"].value]
        except Exception:  # noqa: BLE001
            return None
        return _amostrar([p for p in pts if p[0] < n - 0.5], n)

    params = {}
    for p in op_group.get("Parameters") or []:
        try:
            nome = p.parameterdef.name if p.parameterdef else p.name
            params[nome] = float(p.value)
        except Exception:  # noqa: BLE001 — parâmetro animado ou ilegível: fica de fora
            continue
    return _montar(curva("TKMNTrkDataDataX"), curva("TKMNTrkDataDataY"), valor("TKMNTrkDataFilterDataAmt"),
                   valor("TKMNTrkDataJitterRemovalEnabled"), valor("TKMNTrkDataSmoothingEnabled"),
                   _raster(valor("TKMNTrkDataSettings")), params.get("DVE_POS_X_U"), params.get("DVE_POS_Y_U"),
                   params.get("DVE_SCALE_X_U"))


def da_bin(te, parametros: dict) -> dict | None:
    """O tracker do `TrackEffect` da bin (`trackman` → `data_slots` → `tracker_data`, pyavb): as curvas 0/1 são X/Y,
    um ponto por quadro do segmento. `parametros` = `avb_bin.efeitos.parametros(te)`."""
    try:
        ds = te.property_data["trackman"].property_data["data_slots"]
        tds = list(ds.property_data["tracker_data"])
    except Exception:  # noqa: BLE001
        return None
    n = int(te.property_data.get("length") or 0)
    if len(tds) != 1 or not 0 < n <= MAX_QUADROS:
        return None
    td = tds[0].property_data

    def curva(i):
        try:
            cps = list(list(td["clips"])[i].control_points)
            pts = []
            for cp in cps:
                off = cp.property_data.get("offset")
                pts.append((off[0] / off[1] if isinstance(off, (list, tuple)) else float(off), float(cp.value)))
        except Exception:  # noqa: BLE001
            return None
        return _amostrar([p for p in pts if p[0] < n - 0.5], n)

    v = lambda nome: (parametros.get(nome) or (None, []))[0]  # noqa: E731
    return _montar(curva(0), curva(1), td.get("filter_amount"), td.get("jitter_removal"), td.get("smoothing"),
                   _raster(td.get("settings")), v("DVE_POS_X_U"), v("DVE_POS_Y_U"), v("DVE_SCALE_X_U"))


def _gauss_nearest(v: list[float], sigma: float) -> list[float]:
    """`scipy.ndimage.gaussian_filter1d(v, sigma, mode="nearest")` (truncate 4σ) sem o scipy (o app não o embarca)."""
    if sigma <= 0:
        return list(v)
    r = int(4.0 * sigma + 0.5)
    pesos = [math.exp(-0.5 * (i / sigma) ** 2) for i in range(-r, r + 1)]
    s = sum(pesos)
    pesos = [p / s for p in pesos]
    n = len(v)
    return [sum(p * v[min(n - 1, max(0, k + i - r))] for i, p in enumerate(pesos)) for k in range(n)]


def correcao(dados: dict) -> list[tuple[float, float]]:
    """u(k) em FRAÇÃO do quadro, um por quadro do segmento: o quanto o Avid desloca a imagem (o quadro k mostra a fonte
    em q + u, antes do zoom)."""
    sigma = 30.0 * float(dados["filtro"])
    z = float(dados["zoom"])
    gx, gy = _gauss_nearest(dados["x"], sigma), _gauss_nearest(dados["y"], sigma)
    dx, dy = -dados["pos"][0] / 1000.0 / z, dados["pos"][1] / 1000.0 / z
    return [(x - sx + dx, y - sy + dy) for x, sx, y, sy in zip(dados["x"], gx, dados["y"], gy)]


def dados_do_segmento(seg: dict) -> dict | None:
    """O `params.estabilizacao` do 1º efeito do segmento que o tem (o AAF e a bin põem no Stabilize)."""
    return next(((e.get("params") or {}).get("estabilizacao") for e in (seg.get("effects") or [])
                 if isinstance((e.get("params") or {}).get("estabilizacao"), dict)), None)


def traduzivel(seg: dict) -> bool:
    """Com o tracker e sem velocidade (o quadro k do Avid = o quadro k do clipe no Resolve): é exatamente quando o
    writer manda o plano ao estabilizador do Resolve e a nota diz "ESTABILIZAÇÃO TRADUZIDA"."""
    if not dados_do_segmento(seg):
        return False
    try:
        rel = float(seg.get("relative_speed") or 1.0)
    except (TypeError, ValueError):
        return False
    return abs(rel - 1.0) < 1e-3 and not any(e.get("category") == "speed" for e in (seg.get("effects") or []))
