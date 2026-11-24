"""Rampa entre NLEs: o leitor do Resolve e o escritor do Avid pelo gráfico de POSIÇÃO (`motor/rampa.py`,
`avb_export/translate.py`).

Rodar:

    .venv-win/Scripts/python tests/test_rampa_entre_nles.py

## Por que este teste existe

Regra do autor (2026-10-12, organograma "Rampas entre os três"): entre programas diferentes a rampa vai QUADRO A
QUADRO — a posição exata da fonte em cada quadro, que os três mostram pelo piso —, e a curva nativa só de Avid para
Avid. O laboratório provou os seis sentidos 48/48 (B22, casos A = constante → curva → constante e B = começa dentro da
curva); aqui o app é conferido contra o que foi MEDIDO lá (render × render), no caso
`03 CASOS/TEMPO/V02 B22 RAMPAS ENTRE NLES`:

- `B22_RESOLVE_ORIGEM.drt` — a rampa NATIVA do Resolve 19.0 (keyframe `interp 1`), e em `B22_gabarito.json` o quadro
  lido no render dela. O leitor tem de dar o MESMO quadro: o Resolve ARREDONDA O CANTO (a hipótese "Bézier entre
  keyframes" errava até 2 quadros — 45/48 e 42/48);
- o Timewarp de posição que o MC 25.6 renderizou 48/48 (`avid_hibrido`): o escritor do app tem de levar o MC ao mesmo
  quadro — a interpolação linear entre os keyframes que ele grava cai na posição exata de todo quadro.

As regras de escolha (Avid → Avid = curva nativa; fonte de outra taxa = o caminho antigo) rodam sempre.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "plugins" / "media-composer" / "servico")]
logging.disable(logging.WARNING)

from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
CASO = Path(raiz_das_amostras()) / "03 CASOS" / "TEMPO" / "V02 B22 RAMPAS ENTRE NLES"
F = 24000 / 1001


def _linear(pontos: list[tuple[float, float]], x: float) -> float:
    for (x0, y0), (x1, y1) in zip(pontos, pontos[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pontos[-1][1]


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 60 else f"{repr(obtido)[:57]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    import rampa as RP
    from avb_export import translate as T

    print("── as peças neutras ──")
    pos = [0.0, 1.0, 2.0, 3.5, 5.0, 6.5, 7.0, 7.5]
    ok("keyframes só onde a velocidade muda (+ 1º e último)", RP.keyframes_hibridos(pos), [0, 2, 5, 7])
    ok("constante não é curva", RP.e_curva([0.0, 0.5, 1.0, 1.5]), False)
    ok("Optical Flow → FluidMotion (6); Frame Blend → quadro inteiro (2)",
       (RP.render_avid("optical_flow"), RP.render_avid("frame_blend"), RP.render_avid(None)), (6, 2, 2))

    def seg(**k):
        s = {"motion_effect_type": "ramp", "duration_frames": len(pos), "source_start_frames": 100,
             "source_offset_map": [(float(i), v) for i, v in enumerate(pos)], "source_fps": 23.976,
             "clip_name": "x", "speed_keyframes": [{"t": 0.0, "speed": 1.0}], "retime": None}
        s.update(k)
        return s

    print("\n── a escolha do escritor do Avid ──")
    T.set_origem("premiere", 23.976)
    e = T._motion_entry_from_seg(seg(), "00" * 32)
    ok("do Premiere → gráfico de posição", e[1][0] if e else None, "pos")
    ok("…clipe de dentro = in + piso(máx) + 2", e[2][1:], (100, 9))
    T.set_origem("avid", 23.976)
    e = T._motion_entry_from_seg(seg(), "00" * 32)
    ok("⭐ Avid → Avid com a curva dele → a curva NATIVA", e[1][0] != "pos", True)
    T.set_origem(None, 23.976)
    e = T._motion_entry_from_seg(seg(speed_keyframes=[]), "00" * 32)
    ok("sem curva do Avid (origem não dita) → gráfico de posição", e[1][0], "pos")
    T.set_origem("resolve", 23.976)
    e = T._motion_entry_from_seg(seg(source_fps=25.0), "00" * 32)
    ok("fonte de OUTRA taxa → o caminho antigo (não medido)", e[1][0] != "pos", True)
    T.set_origem(None, None)

    if not CASO.is_dir():
        print(f"  PULADO — {CASO} não está neste disco")
        print(f"\n{casos - len(falhas)}/{casos} casos")
        return 1 if falhas else 0
    gab = json.loads((CASO / "B22_gabarito.json").read_text(encoding="utf-8"))

    print("\n── o leitor do Resolve contra o render do Resolve ──")
    with zipfile.ZipFile(CASO / "B22_RESOLVE_ORIGEM.drt") as z:
        x = z.read(next(n for n in z.namelist() if n.startswith("SeqContainer"))).decode("utf-8")
    clipes = sorted(re.findall(r"<Sm2TiVideoClip DbId=.*?</Sm2TiVideoClip>", x, re.S),
                    key=lambda b: int(re.search(r"<Start>(\d+)</Start>", b).group(1)))
    for nome, b in zip(("RAMPA_A", "RAMPA_B"), clipes):
        kfs = RP.keyframes_do_timemap(re.search(r"<MediaTimemapBA>([0-9a-fA-F]+)</MediaTimemapBA>", b).group(1), F)
        m = re.search(r"<In>([^<]*)</In>", b)
        entrada = float(m.group(1)) if m else 0.0
        lido = gab["resolve_lido"][nome]
        pos_r = RP.posicoes_do_timemap(kfs, entrada, len(lido))
        ok(f"{nome}: o piso das posições = o quadro do render (48)", sum(a == b for a, b in zip(RP.piso(pos_r), lido)), 48)

    print("\n── o escritor do Avid contra o Timewarp que o MC renderizou 48/48 ──")
    import avb
    tpl = T.capture_templates()
    ok("o molde do gráfico de posição está embutido", "EFF_TIMEWARP_POSICAO" in tpl, True)
    bin_qualquer = next(CASO.parent.parent.rglob("*.avb"), None)
    T.set_origem("premiere", F)
    for nome in ("RAMPA_A", "RAMPA_B"):
        g = gab["avid_hibrido"][nome]
        s = seg(duration_frames=48, source_start_frames=0, retime=None,
                source_offset_map=[(float(k), v) for k, v in enumerate(g["posicoes"])])
        e = T._motion_entry_from_seg(s, "00" * 32)
        _, p, keys, render = e[1]
        ok(f"{nome}: Both Fields (2), como o medido", render, g["render"])
        ok(f"{nome}: clipe de dentro = o do medido", e[2][2], g["dentro"])
        lin = [_linear([(k, p[k]) for k in keys], float(k)) for k in range(48)]
        ok(f"{nome}: linear entre os keyframes = a posição exata em todo quadro",
           all(abs(a - b) < 1e-9 for a, b in zip(lin, g["posicoes"])), True)
        ok(f"{nome}: …e o piso dela = o quadro do render do MC (48)",
           sum(a == b for a, b in zip(RP.piso(lin), g["lido"])), 48)
        ok(f"{nome}: keyframes ⊂ os do medido (só se tiram os colineares)",
           set(keys) <= {int(round(q[0])) for q in g["pontos"]}, True)
        if bin_qualquer is not None:
            with avb.open(str(bin_qualquer)) as f:
                T.ER = 24
                me = T._build_one(f, e, "picture", tpl)
                ct = me.param_list[0].control_track
                ok(f"{nome}: o MotionEffect gravado — gráfico de posição, linear",
                   (me.attributes.get("_MFX_GRAPH_ENABLED"), ct.interp_kind, me.attributes.get("_SFX_RENDER")),
                   (2, 3, 2))
                ok(f"{nome}: …os pontos são as posições exatas",
                   [(cp.offset[0], cp.value) for cp in ct.control_points], [(k, p[k]) for k in keys])
                ok(f"{nome}: …speed_ratio = o do medido", list(me.speed_ratio), g["speed_ratio"])
    T.set_origem(None, None)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
