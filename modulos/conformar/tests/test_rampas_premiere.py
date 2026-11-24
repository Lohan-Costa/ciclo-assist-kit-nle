"""Rampas de velocidade do Premiere (Time Remapping) → Resolve (2026-10-10, caso real R04 PRODUCAO-C).

Rodar:

    .venv/bin/python tests/test_rampas_premiere.py        (Windows: .venv-win/Scripts/python)

Antes: o leitor ignorava o Time Remapping — o InPoint (tempo do CLIPE) ia como tempo da FONTE: o drone que
corre a 29,5× entrava no segundo 1 em vez do 29,5 ("os takes vieram com o in/out errado", o autor). Agora:
1. a curva (`_remap_fonte`): tipo 6 = canto; o par 7 → 8 = transição em que a VELOCIDADE vai em reta (ou, com
   INFLUÊNCIA no 7, numa Bézier com alças de influência × T — medido contra a referência do R04)
   (s = s7 + v1·u + (v2 − v1)·u²/2T) — confere com os números do projeto e com a imagem do Premiere;
2. com rampa, a `PlaybackSpeed` do clipe VALE: o tempo do clipe anda a 1,2× (LOU_7292, cada quadro da referência
   casado com o da mídia: 3,003 quadros de 60 qps por quadro) e o in vai pelo piso da grade (2208, não 2210);
3. o segmento leva a fonte em CADA quadro (`source_offset_map`, a regra do Avid) e o writer escreve a curva
   com a entrada a 100 % de (0, 0) até a fonte, o clipe começando ali (o Resolve força a curva a nascer em
   (0, 0): sem a entrada, o plano saía do começo do arquivo — a claquete);
4. o keyframe de efeito num clipe com rampa está no tempo da FONTE (a rotação do drone A031).
A parte do projeto real PULA sem o caso no disco.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "tests"), str(RAIZ / "plugins" / "media-composer" / "servico")]

from prproj import leitura as L  # noqa: E402
import casos as C  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: veio {obtido!r}, esperava {esperado!r}")


def main() -> int:
    print("── a curva (A030_C062, os números do projeto) ──")
    c062 = [(0.0, 0.0, "6"), (1.159, 34.201, "7"), (1.408, 37.996, "8"), (6.132, 42.72, "6")]
    ok("antes da transição: 29,5×", round(L._remap_fonte(c062, 1.0), 2), 29.51)
    ok("no meio da transição: o que o Premiere mostra (35,62 s − o desvio fixo do proxy)",
       round(L._remap_fonte(c062, 1.210), 2), 35.56)
    ok("a transição fecha no ponto do projeto (T·(v1+v2)/2; os pontos aqui têm 3 casas)", round(L._remap_fonte(c062, 1.408), 2), 38.0)
    ok("depois: 1×", round(L._remap_fonte(c062, 2.408), 3), 38.996)
    ok("identidade não é rampa", L._remap_fonte([(0, 0, "6"), (10, 10, "6")], 4.0), 4.0)

    print("── transição com INFLUÊNCIA (Bézier na velocidade), medida contra a referência do R04 ──")
    tps = L.TPS
    c026 = [(0.0, 0.0, "6"), (879607401997 / tps, 24.274250000000002, "7", (0.445, 0.445)),
            (976699085143 / tps, 25.805067708333834, "8"), (13564444766142 / tps, 75.36, "6")]
    # o quadro da mídia (25 qps) que o Premiere mostra em cada quadro do plano, casado pela imagem (2026-10-10)
    ref = [606, 613, 620, 627, 632, 637, 640, 642, 643, 644, 645, 647, 648]
    vistos = [math.floor(L._remap_fonte(c026, (83 + k) * 1001 / 24000) * 25 + 1e-6) for k in range(len(ref))]
    ok("⭐ A030_C026 (influência 44,5 %): os 13 quadros da referência", vistos, ref)
    reta = [(x[0], x[1], x[2]) for x in c026]
    ok("a mesma curva em reta erraria (até 3 quadros)",
       vistos != [math.floor(L._remap_fonte(reta, (83 + k) * 1001 / 24000) * 25 + 1e-6) for k in range(len(ref))], True)
    ok("a transição com influência fecha no mesmo ponto (a área é a da reta)",
       round(L._remap_fonte(c026, 976699085143 / tps), 4), round(25.805067708333834, 4))

    print("── o caso real R04 ──")
    raiz = C.amostras()
    prproj = raiz / "03 CASOS" / "REAL" / "R04 PRODUCAO-C" / "ISOLADO" / "PROJETO" / "PRODC_FINAL_isolado.prproj" if raiz else None
    if not prproj or not prproj.exists():
        print(f"  — PULA: {prproj or 'pasta de testes'} não está nesta máquina")
    else:
        r = L.ler_sequencia(str(prproj), "PRODC_Trailer_v02_RESGATE")
        quadro_a_quadro = [s for s in r["segmentos"] if s.get("motion_effect_type") == "ramp" and not s["is_audio"]]
        rampas = [s for s in quadro_a_quadro if isinstance(s["prproj"].get("rampa"), list)]
        ok("⭐ as 9 rampas do trailer", len(rampas), 9)
        # o plano dentro do nest ACELERADO ("transicao-perna", 228,6 %) também vai quadro a quadro: a grade do nest
        # (laboratório B16, 2026-10-10)
        ok("…e 1 plano na grade de um nest acelerado (o da transicao-perna)",
           [(s["clip_name"], s["prproj"].get("rampa")) for s in quadro_a_quadro if s not in rampas],
           [("PRJ-0006-308-A1-3A8F.mov", "grade do nest")])
        drone = next(s for s in rampas if s["timeline_tc_in"] == "00:00:20:13")
        ok("⭐ o drone A030_C062 entra na fonte em 29,5 s (antes: 1,0 s)",
           round(drone["source_start_frames"] / drone["source_fps"], 1), 29.5)
        ok("um ponto por quadro do plano", len(drone["source_offset_map"]), 30)
        lou = next(s for s in rampas if s["clip_name"].startswith("LOU_7292"))
        ok("⭐ LOU_7292: a PlaybackSpeed de 1,2× conta com a rampa (1,2× na curva)",
           round(1 / lou["relative_speed"], 2), 1.2)
        ok("⭐ LOU_7292: o in pelo piso da grade de 1,2× (a referência mostra 2208)", lou["source_start_frames"], 2208)
        a031 = next(s for s in rampas if s["clip_name"].startswith("A031"))
        rot = next(e for e in a031["effects"] if e["name"] == "Motion")["params"]["kf"]["rot"]
        ok("⭐ A031: a rotação vai quadro a quadro (keyframe no tempo da fonte)", len(rot), 26)
        # EFEITO DESLIGADO (`<Bypass>true</Bypass>`) não existe na imagem: a Opacidade com máscara do JUL_7504 (a perna,
        # 526) — o render do Premiere só com a V2 mostra o quadro inteiro (2026-10-10)
        jul = next(s for s in r["segmentos"] if s["clip_name"] == "JUL_7504.mp4" and s["timeline_tc_in"] == "00:00:21:22")
        # fonte LETTERBOX (proxy 1024×540 em 1920×1080: 1012,5 px de altura): o Tilt do Resolve anda em unidades da imagem
        # encaixada — Position y 0,34167 vira 0,15833 × 1080/1012,5 (medido 2026-10-10: sem o fator, 11 px abaixo)
        lou = next(s for s in r["segmentos"] if s["clip_name"] == "LOU_7254.mp4" and s["timeline_tc_in"] == "00:00:15:08")
        mot = next(e for e in lou["effects"] if e["name"] == "Motion")["params"]
        ok("⭐ LOU_7254 (letterbox): Tilt × 1080/1012,5, Pan como estava",
           (round(mot["pos_y"], 1), round(mot["pos_x"], 1)), (round((0.5 - 0.34166666865348816) * 1080 / 1012.5 * 1000, 1), 87.0))
        ok("⭐ JUL_7504: a máscara da Opacidade DESLIGADA não vai", any("Máscara" in e["name"] for e in jul["effects"]), False)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print("  ✗", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
