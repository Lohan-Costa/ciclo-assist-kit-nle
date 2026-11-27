"""TIME REMAPPING no `.prproj`: a rampa e o congelado escritos para o Premiere, a partir da posição da FONTE em cada
quadro do plano (a regra do autor, 2026-11-21: curva = um keyframe por quadro; trecho constante = só as pontas).

Levado do laboratório (`laboratorio-de-midia/lab/bancadas/premiere_rampas.py::de_posicoes`, `_objetos_remap`,
`_kf_texto`), onde foi PROVADO (banco `protocolos/avb/estruturas.md` §"AVID → PREMIERE, ponta a ponta", 2026-10-12, B22):
rampa nativa do Avid → Time Remapping no Premiere 23.2, render × render do MC: A 48/48 e B 48/48 o MESMO quadro.

A forma (banco `protocolos/prproj/estruturas.md` §Time Remapping):
- No `VideoClip` (o `<Clip>` de dentro): `<TimeRemapping ObjectRef>` → `TimeRemapping` (v2) → `<Keyframes ObjectRef>` →
  `TimeComponentParam` "Speed" (v8) com `<Keyframes>ticks,FONTE_s,6,0,0,0,0,0;…</Keyframes>`: o tempo é o do CLIPE (o
  domínio do `InPoint`), o valor é o tempo da FONTE em segundos; tipo 6 = canto.
- ⛔ A curva começa em (0, 0) e o plano anda `s0` quadros INTEIROS (InPoint = s0): com o 1º keyframe fora do 0 o Premiere
  mostrou o quadro 0 da mídia; com s0 fracionário o plano andou meio quadro (B22 Resolve → Premiere).
- Sem `PlaybackSpeed` no clipe: com Time Remapping ela CONTA (o tempo do clipe andaria `vel` por quadro).

Só a stdlib: a Carta carrega este arquivo pelo caminho (como o `offline.py`).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

TICKS_POR_SEGUNDO = 254016000000
CLASSE_PARAM = "278ae1f9-ab7b-4dff-a53c-21029a399a9d"
CLASSE_REMAP = "ace5148e-9c9b-40ed-9f82-64cb67308464"


def de_posicoes(pos_s: list[float], tpf_s: float, tol: float = 1e-6) -> dict:
    """A curva do Time Remapping para um plano de `len(pos_s)` quadros da timeline; `pos_s[k]` = o tempo da FONTE
    (segundos) mostrado no quadro k; `tpf_s` = a duração de um quadro da TIMELINE. Devolve
    {"remap": [(tempo do clipe s, fonte s, "6")], "in_s": o InPoint em segundos, "keyframes": n}.

    Canto (tipo 6) só onde a velocidade muda: dentro da curva, um por quadro; no trecho constante, as pontas; no
    congelado (todas as posições iguais), uma reta deitada."""
    n = len(pos_s)
    if n == 0:
        raise ValueError("plano sem quadros")
    d = [b - a for a, b in zip(pos_s, pos_s[1:])] or [0.0]
    kfs = [0] + [k for k in range(1, n - 1) if abs(d[k] - d[k - 1]) >= tol] + ([n - 1] if n > 1 else [])
    s0 = math.ceil(pos_s[0] / tpf_s - 1e-9) if pos_s[0] > 1e-9 else 0
    pts = [((k + s0) * tpf_s, pos_s[k], "6") for k in kfs] + [((n + s0) * tpf_s, pos_s[-1] + d[-1], "6")]
    if s0:
        pts = [(0.0, 0.0, "6")] + pts
    return {"remap": pts, "in_s": s0 * tpf_s, "keyframes": len(pts)}


def texto_dos_keyframes(pts) -> str:
    """`ticks,fonte_s,tipo,0,0,0,0,0;…;` — o texto do `<Keyframes>` (a fonte com 24 casas, como o Premiere grava)."""
    out = []
    for t, s, tp in (p[:3] for p in pts):
        out.append(f"{round(t * TICKS_POR_SEGUNDO)},{max(s, 0.0):.24f},{tp},0,0,0,0,0")
    return ";".join(out) + ";"


def objetos(id_remap: str, id_param: str, pts, limite_s: float) -> list[ET.Element]:
    """Os dois objetos de topo, como o Premiere 23.2 grava (copiados do R04): o `TimeComponentParam` "Speed" e o
    `TimeRemapping` que aponta para ele. `limite_s` = a duração da mídia (o `UpperBound`)."""
    par = ET.Element("TimeComponentParam", {"ObjectID": str(id_param), "ClassID": CLASSE_PARAM, "Version": "8"})
    for tag, txt in (("Name", "Speed"), ("IsTimeVarying", "true"), ("IsLocked", "false"),
                     ("DiscontinuousInterpolate", "false"), ("ParameterControlType", "21"), ("LowerBound", "0"),
                     ("UpperBound", repr(float(limite_s))),
                     ("StartKeyframe", "-91445760000000000,0.000000000000000000000000,0,0,0,0,0,0"),
                     ("Keyframes", texto_dos_keyframes(pts)), ("CurrentValue", "0"), ("RangeLocked", "false"),
                     ("ParameterID", "-1")):
        ET.SubElement(par, tag).text = txt
    tr = ET.Element("TimeRemapping", {"ObjectID": str(id_remap), "ClassID": CLASSE_REMAP, "Version": "2"})
    ET.SubElement(tr, "Keyframes", {"ObjectRef": str(id_param)})
    return [par, tr]


def pendurar(clip: ET.Element, id_remap: str) -> None:
    """O `<TimeRemapping ObjectRef>` no `<Clip>` do `VideoClip`, antes do `ClipID` (o lugar do R04); tira o de antes."""
    for x in clip.findall("TimeRemapping"):
        clip.remove(x)
    el = ET.Element("TimeRemapping", {"ObjectRef": str(id_remap)})
    filhos = list(clip)
    i = next((k for k, x in enumerate(filhos) if x.tag == "ClipID"), len(filhos))
    clip.insert(i, el)


def fonte_no_clipe(pts, t_s: float) -> float:
    """O tempo da fonte num tempo do clipe (reta entre os cantos) — para conferir a curva escrita."""
    for (t0, s0, _), (t1, s1, _) in zip(pts, pts[1:]):
        if t0 - 1e-12 <= t_s <= t1 + 1e-12:
            return s0 if t1 == t0 else s0 + (s1 - s0) * (t_s - t0) / (t1 - t0)
    return pts[-1][1]
