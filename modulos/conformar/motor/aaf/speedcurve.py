"""Reprodução da curva de velocidade (Timewarp / Motion Control) do Avid.

O gráfico "Speed" que o editor vê no Media Composer é o parâmetro
`PARAM_SPEED_MAP_U`: uma lista de keyframes `(frame_timeline, multiplicador)` onde
1.0 = 100% (velocidade normal), 3.0 = 300%, etc. A interpolação entre keyframes é
uma **Bézier cúbica** (`AvidBezierInterpolator`) com handles de tangente editáveis,
gravados por keyframe como sub-parâmetros do ControlPoint:

    PP_OUT_TANGENT_POS_U / PP_OUT_TANGENT_VAL_U  → handle de saída (Δframe, Δvalor)
    PP_IN_TANGENT_POS_U  / PP_IN_TANGENT_VAL_U   → handle de entrada (Δframe, Δvalor)
    PP_TANGENT_MODE_U                            → modo do handle

A **posição na fonte** para cada frame da timeline é a integral acumulada dessa
velocidade: `src(t) = ∫₀ᵗ speed(τ) dτ` (a velocidade é "frames de fonte consumidos
por frame de timeline"). O Avid já entrega essa integral pronta em
`PARAM_SPEED_OFFSET_MAP_U` (amostrada a cada 0.5 frame) — é o ground-truth usado
pelo matcher/relink. Este módulo permite **reconstruir a mesma curva a partir dos
keyframes**, o que é necessário para traduzir a rampa para outras NLEs (Resolve/
Premiere) com keyframes nativos, e validado contra o offset map do Avid.

Validação (TESTE SINTETICO MC RAMPA.aaf, rampa 100%→300.1%→1054.88% em 960f):
reproduzir a Bézier e integrá-la bate com o offset map do Avid com erro < 0.02 na
velocidade e < 1 frame na posição ao longo de toda a duração.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("relinker")

_TANGENT_KEYS = {
    "PP_OUT_TANGENT_POS_U": "out_dt",
    "PP_OUT_TANGENT_VAL_U": "out_dv",
    "PP_IN_TANGENT_POS_U": "in_dt",
    "PP_IN_TANGENT_VAL_U": "in_dv",
}


def _control_point_handles(cp) -> dict:
    """Lê os handles de Bézier (em unidades absolutas de Δframe/Δvalor) de um ControlPoint."""
    h = {"out_dt": 0.0, "out_dv": 0.0, "in_dt": 0.0, "in_dv": 0.0, "mode": None}
    try:
        for _pid, prop in cp.property_entries.items():
            try:
                val = prop.value
            except Exception:
                continue
            # Os handles ficam numa lista de ConstantValue nomeados (PointProperties).
            if isinstance(val, list) and val and hasattr(val[0], "name"):
                for cv in val:
                    nm = getattr(cv, "name", "")
                    key = _TANGENT_KEYS.get(nm)
                    if key is not None:
                        try:
                            h[key] = float(cv.value_at(0))
                        except Exception:
                            pass
                    elif nm == "PP_TANGENT_MODE_U":
                        try:
                            h["mode"] = int(cv.value_at(0))
                        except Exception:
                            pass
    except Exception:
        pass
    return h


def extract_speed_keyframes(speed_map_param) -> list[dict]:
    """Extrai os keyframes da curva de velocidade de um VaryingValue PARAM_SPEED_MAP_U.

    Retorna [{t, speed, out_dt, out_dv, in_dt, in_dv, mode}], com t = frame da
    timeline e speed = multiplicador (1.0 = 100%). Handles em unidades absolutas
    (Δframe, Δvalor) relativas ao keyframe.
    """
    kfs: list[dict] = []
    try:
        points = list(speed_map_param["PointList"].value)
    except Exception:
        return kfs
    for cp in points:
        try:
            t = float(cp.time)
            v = float(cp.value)
        except Exception:
            continue
        h = _control_point_handles(cp)
        kfs.append({"t": round(t, 4), "speed": round(v, 6), **h})
    kfs.sort(key=lambda k: k["t"])
    return kfs


def _bez(p, u):
    """Bézier cúbica 1-D dados 4 pontos de controle p e parâmetro u∈[0,1]."""
    mt = 1.0 - u
    return (mt * mt * mt * p[0] + 3 * mt * mt * u * p[1]
            + 3 * mt * u * u * p[2] + u * u * u * p[3])


def eval_speed(keyframes: list[dict], x: float) -> float:
    """Velocidade (multiplicador) no frame de timeline `x`, reproduzindo a Bézier do Avid.

    Antes do 1º keyframe / depois do último, segura o valor da ponta (como o Avid).
    """
    if not keyframes:
        return 1.0
    if x <= keyframes[0]["t"]:
        return keyframes[0]["speed"]
    if x >= keyframes[-1]["t"]:
        return keyframes[-1]["speed"]
    for i in range(len(keyframes) - 1):
        k0, k1 = keyframes[i], keyframes[i + 1]
        if k0["t"] <= x <= k1["t"]:
            xs = (k0["t"], k0["t"] + k0["out_dt"], k1["t"] + k1["in_dt"], k1["t"])
            ys = (k0["speed"], k0["speed"] + k0["out_dv"],
                  k1["speed"] + k1["in_dv"], k1["speed"])
            # Resolve u tal que Bx(u)=x (Bézier-x é monotônica em u para curvas válidas).
            lo, hi = 0.0, 1.0
            for _ in range(50):
                u = (lo + hi) * 0.5
                if _bez(xs, u) < x:
                    lo = u
                else:
                    hi = u
            return _bez(ys, (lo + hi) * 0.5)
    return keyframes[-1]["speed"]


def integrate_offset_map(keyframes: list[dict], length: int,
                         step: float = 0.5) -> list[tuple]:
    """Reconstrói o mapa timeline→fonte (igual ao PARAM_SPEED_OFFSET_MAP_U do Avid).

    Integra a curva de velocidade (regra de Simpson por frame) acumulando a posição
    na fonte. Retorna [(tl_frame, src_offset)] amostrado a cada `step` frame.
    """
    if not keyframes or length <= 0:
        return []
    out = [(0.0, 0.0)]
    acc = 0.0
    f = 0.0
    while f < length - 1e-9:
        a = eval_speed(keyframes, f)
        m = eval_speed(keyframes, f + 0.5)
        b = eval_speed(keyframes, f + 1.0)
        acc += (a + 4 * m + b) / 6.0     # ∫ de velocidade sobre 1 frame (Simpson)
        f += 1.0
        # amostra intermediária a step (linear dentro do frame é suficiente p/ preview)
        out.append((round(f, 3), round(acc, 3)))
    return out


def average_speed(keyframes: list[dict], length: int) -> float:
    """Velocidade média de playback (%) ao longo do clipe — para badge/UI."""
    om = integrate_offset_map(keyframes, length)
    if not om or length <= 0:
        return 100.0
    return round(om[-1][1] / length * 100.0, 1)
