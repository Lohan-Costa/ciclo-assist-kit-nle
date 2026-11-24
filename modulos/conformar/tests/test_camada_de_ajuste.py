"""Camada de ajuste do Premiere → Adjustment Clip do Resolve, com a LUT da Lumetri (2026-10-10, caso R04).

Rodar:

    .venv/bin/python tests/test_camada_de_ajuste.py        (Windows: .venv-win/Scripts/python)

A camada "LUT-teal and orange" do PRODUCAO-C (V6, a peça inteira) tem uma Lumetri com o look criativo
de um .cube EXTERNO que não existe mais — e o projeto carrega a LUT (blob `ITX3`, banco
`prproj/estruturas.md` §"Lumetri: a LUT EMBUTIDA"). Medido pela imagem: a LUT a 50 % misturada em gama
= o quadro do Premiere (0,52/255); no Resolve 19, o mesmo efeito por canal (1–2 níveis). Aqui:
1. o `.cube` sai do blob, na ordem certa e na intensidade (mistura com a identidade nos pontos da grade);
2. o leitor marca as 2 camadas de ajuste e acha a LUT só na da V6;
3. o writer escreve os 2 "Adjustment Clip" (a forma nativa do caso U01, sem MediaRef) e o relatório
   leva a LUT para a casca aplicar no nó depois do import.
As partes do projeto real PULAM sem o caso no disco.
"""

from __future__ import annotations

import base64
import os
import struct
import sys
import tempfile
import zipfile
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


def _blob(n: int, valores) -> str:
    """Um blob `ITX3` como o da Lumetri: 20 bytes de hash + ITX3 + N + 3 + 32 bytes + N³×3 floats."""
    cab = b"\x00" * 20 + b"ITX3" + struct.pack("<II", n, 3) + b"\x00" * 20 + struct.pack("<fff", 1, 1, 1)
    return base64.b64encode(cab + struct.pack(f"<{len(valores)}f", *valores)).decode()


def main() -> int:
    print("── a LUT embutida → .cube ──")
    n = 2
    # uma LUT que INVERTE (1 − x) em cada canal, R mais rápido
    inv = []
    for b in range(n):
        for g in range(n):
            for r in range(n):
                inv += [1 - r, 1 - g, 1 - b]
    linhas = [l for l in L.lut_itx3_para_cube(_blob(n, inv), 100).splitlines() if l[:1].isdigit()]
    ok("100 %: a LUT como veio, R mais rápido", (linhas[0], linhas[1], linhas[2]),
       ("1.000000 1.000000 1.000000", "0.000000 1.000000 1.000000", "1.000000 0.000000 1.000000"))
    meia = [l for l in L.lut_itx3_para_cube(_blob(n, inv), 50).splitlines() if l[:1].isdigit()]
    ok("50 %: meio caminho entre a identidade e a LUT", meia[0], "0.500000 0.500000 0.500000")
    ok("…e o cabeçalho do .cube", "LUT_3D_SIZE 2" in L.lut_itx3_para_cube(_blob(n, inv), 50), True)

    print("── as curvas da Lumetri (spline cúbica natural) → LUT ──")
    curva = [(0.089, 0.0), (0.565, 0.693), (1.0, 1.0)]            # a do PRJ-0006-147 no R04 (medida contra o Premiere)
    f = L._spline_natural(curva)
    ok("a curva passa pelos pontos", [round(f(x), 6) for x, _ in curva], [0.0, 0.693, 1.0])
    ok("abaixo do 1º ponto, plana (o preto esmagado)", f(0.03), 0.0)
    ok("spline NATURAL: no meio do 1º trecho fica acima da reta (a curva do Premiere: 1,4/255 contra 4,6 da reta)",
       (round(f(0.327), 3), f(0.327) > (0.327 - 0.089) / (0.565 - 0.089) * 0.693), (0.381, True))
    ident = [(0.0, 0.0), (1.0, 1.0)]
    cubo = [l for l in L.lut_composta([{"curvas": [curva, ident, ident, ident]}], "t", n=3).splitlines() if l[:1].isdigit()]
    ok("LUT só com a curva mestra: o meio da grade (0,5 cinza) vai a f(0,5) nos três canais",
       cubo[13], " ".join([f"{f(0.5):.6f}"] * 3))

    print("── curvas de saturação e balanço de branco (medidos contra o Premiere no R04) ──")
    sat = L._saturacao_por_curva(L._spline_natural([(0.0, 0.26), (1.0, 0.0)]), pela_luma=False)
    ok("cinza não muda (saturação 0 → só o ganho, sobre nada)", tuple(round(v, 6) for v in sat(0.4, 0.4, 0.4)), (0.4, 0.4, 0.4))
    r_, g_, b_ = sat(0.5, 0.4, 0.3)
    ok("cor: se afasta da média RGB pelo ganho 1 + y(saturação HSL)",
       round((r_ - 0.4) / 0.1, 4), round(1 + L._spline_natural([(0.0, 0.26), (1.0, 0.0)])(0.2 / 0.8), 4))
    cubo = [l for l in L.lut_composta([{"wb": [0.9834, 0.999, 1.0933]}], "t", n=2).splitlines() if l[:1].isdigit()]
    ok("balanço de branco: ganho por canal (o branco da grade)", cubo[-1], "0.983400 0.999000 1.000000")

    print("── revisão de código (2026-10-10): sem perda calada, sem divisão por zero ──")
    padrao = {"3": "true", "11": "0.", "12": "0.", "20": "100.", "23": "true", "28": "0.", "46": "true", "50": "true"}
    ok("Lumetri só com controles no padrão: nada a avisar", L._lumetri_resto(padrao.get), [])
    mexida = dict(padrao, **{"11": "0.75", "20": "130.", "28": "12."})
    ok("⭐ Exposure / Saturation / Faded Film fora do padrão viram aviso (antes sumiam calados)",
       L._lumetri_resto(mexida.get), ["Exposure", "Saturation", "Faded Film"])
    ok("…mas não com a Correção Básica desligada (o Premiere não os aplica)",
       L._lumetri_resto(dict(mexida, **{"3": "false"}).get), ["Faded Film"])
    f2 = L._spline_natural([(0.0, 0.0), (0.0, 0.1), (0.5, 0.6), (1.0, 1.0)])
    ok("curva com dois pontos no mesmo x: não divide por zero (fica o último)", round(f2(0.5), 6), 0.6)
    assim = [(0.0, 0.0, "6"), (1.0, 30.0, "7", (0.2, 0.6)), (1.25, 34.0, "8"), (3.25, 36.0, "6")]
    ok("rampa com influências DESIGUAIS fecha no keyframe 8 (sem salto)",
       round(L._remap_fonte(assim, 1.25), 6), 34.0)

    print("── o caso real R04 ──")
    raiz = C.amostras()
    caso = raiz / "03 CASOS" / "REAL" / "R04 PRODUCAO-C" if raiz else None
    prproj = caso / "ISOLADO" / "PROJETO" / "PRODC_FINAL_isolado.prproj" if caso else None
    if not prproj or not prproj.exists():
        print(f"  — PULA: {prproj or 'pasta de testes'} não está nesta máquina")
    else:
        r = L.ler_sequencia(str(prproj), "PRODC_Trailer_v02_RESGATE")
        aj = [s for s in r["segmentos"] if s.get("ajuste")]
        ok("⭐ as 2 camadas de ajuste (V4 e V6)", sorted((s["track"], s["timeline_tc_in"]) for s in aj),
           [(4, "00:00:06:18"), (6, "00:00:00:00")])
        luts = [e["params"].get("lut") for s in aj for e in s["effects"] if e["category"] == "ajuste"]
        ok("⭐ a LUT só na da V6: o .cube do disco Z: a 50 %",
           [(os.path.basename(x["preset"].replace("\\", "/")), x["intensidade"]) for x in luts if x],
           [("MARVEL_TEAL_AND_ORANGE_LUT004.cube", 50.0)])
        conferida = caso / "ISOLADO" / "LUT" / "MARVEL_TEAL_AND_ORANGE_LUT004_50pct.cube"
        if conferida.exists():
            a = [l for l in L.lut_itx3_para_cube(next(x for x in luts if x)["itx3_b64"], 50).splitlines() if l[:1].isdigit()]
            b = [l for l in conferida.read_text().splitlines() if l[:1].isdigit()]
            ok("⭐ o .cube = o conferido pela imagem contra o Premiere (0,52/255)", a == b, True)
        from prproj.projeto import Projeto
        from prproj.leitura import _lut_do_master
        pj = Projeto(str(prproj))
        mc252 = next(o for o in pj.objetos if o.tag == "VideoClipTrackItem"
                     and "PRJ-0006-252" in (pj.campo(pj.ref(o, "SubClip"), "Name") or ""))
        l252 = _lut_do_master(pj, mc252)
        ok("⭐ a Lumetri do master clip: a INPUT LUT (Correção Básica) a 100 %, o Creative vazio não vira caminho",
           (l252["tipo"], os.path.basename(l252["preset"].replace("\\", "/")), l252["intensidade"]),
           ("entrada", "KC_NEUTM.cube", 100.0))
        ok("a Lumetri da camada não conta como \"sem tradução\" (a LUT vai)",
           any("Lumetri" in e["name"] and not e["reproducible"] for s in aj for e in s["effects"]), False)

        from tools.prproj_para_drt import montar
        with tempfile.TemporaryDirectory() as tmp:
            saida = os.path.join(tmp, "r04.drt")
            rel = montar(str(prproj), "PRODC_Trailer_v02_RESGATE", saida, [str(caso / "ISOLADO" / "MIDIA")])
            with zipfile.ZipFile(saida) as z:      # fechado antes de apagar a pasta (Windows trava)
                seq = "".join(z.read(x).decode("utf-8", "replace") for x in z.namelist() if x.startswith("SeqContainer"))
            ok("⭐ o DRT traz os 2 Adjustment Clip", seq.count("<PrettyType>Adjustment Clip</PrettyType>"), 2)
            ok("o relatório leva a LUT da V6, com o .cube gravado ao lado",
               [(x["trilha"], x["quadro"], x["arquivo"], os.path.exists(x["cube"])) for x in rel["luts"]
                if x.get("cube") and x["arquivo"] == "Adjustment Clip"],
               [(6, 0, "Adjustment Clip", True)])
            # a Lumetri do MASTER CLIP (Source Clip Effect): a Input LUT KC_NEUTM dos 16 PRJ-* (câmera em log) vai no nó
            # de cada plano — medido 2026-10-10: a 100 % a cor bate com o Premiere (2,3/255; sem ela 18,5)
            mestre = [x for x in rel["luts"] if x.get("cube") and x["arquivo"] != "Adjustment Clip"]
            prj = [x for x in mestre if x["arquivo"].startswith("PRJ-")]
            ok("⭐ a Input LUT do master clip em todos os planos PRJ ligados (23; o desligado de 192 não entra), antes da curva",
               (len(prj), all(x["preset"].startswith("KC_NEUTM.cube") for x in prj)), (23, True))
            ok("…nenhum pedido para o plano desligado", any(x["quadro"] == 192 for x in mestre), False)
            # a Lumetri do PLANO (curvas RGB, spline natural) também vai na LUT: 72 planos ligados com cor no R04
            ok("⭐ a Lumetri do plano vira LUT (curvas) — 72 planos; a Lumetri não é mais \"sem tradução\"",
               (len(mestre), any(a.get("texto") == "efeito sem tradução: Lumetri Color" for a in rel.get("avisos") or [])),
               (72, False))
            ok("⭐ as curvas de saturação e o balanço de branco também vão: nenhuma Lumetri \"sem tradução\"",
               [a["texto"] for a in rel.get("avisos") or [] if "Lumetri sem tradução" in a["texto"]], [])
            # o Black & White do nest "transicao-poste" (2 usos) → saturação 0 no clipe de dentro (autor, 2026-10-10)
            ok("⭐ o Black & White do poste vai como saturação 0 nos 2 clipes de dentro",
               sorted((x["arquivo"], x["saturacao"]) for x in rel["luts"] if "saturacao" in x),
               [("LOU_7310.mov", 0.0), ("LOU_7310.mov", 0.0)])
            ok("…e não é mais \"efeito sem tradução\"",
               any("Black & White" in (a.get("texto") or "") and "sem tradução" in (a.get("texto") or "")
                   for a in rel.get("avisos") or []), False)

    print("── a cor no nó do clipe, depois do import (o gêmeo Python da casca) ──")
    from drp import luts as LU

    class Item:
        def __init__(self, nome, ini):
            self.nome, self.ini, self.cdl, self.lut = nome, ini, None, None

        def GetStart(self):
            return self.ini

        def GetName(self):
            return self.nome

        def SetCDL(self, m):
            self.cdl = m
            return True

        def SetLUT(self, n, c):
            self.lut = (n, c)
            return True

    class Timeline:
        def __init__(self, itens):
            self.itens = itens

        def GetStartFrame(self):
            return 1000

        def GetItemListInTrack(self, tipo, n):
            return self.itens.get(n, [])

    class Projeto:
        def RefreshLUTList(self):
            return True
    poste = Item("LOU_7310.mov", 1074)
    res = LU.aplicar_luts(Projeto(), Timeline({3: [poste]}), {"luts": [
        {"trilha": 3, "quadro": 74, "arquivo": "LOU_7310.mov", "saturacao": 0.0},
        {"trilha": 3, "quadro": 80, "arquivo": "LOU_7310.mov", "saturacao": 0.0},
        {"trilha": 3, "quadro": 74, "arquivo": "LOU_7310.mov", "saturacao": "0; rm"}]})
    ok("saturação 0 → SetCDL no nó 1 com Slope/Offset/Power neutros",
       (res[0]["ok"], poste.cdl), (True, {"NodeIndex": "1", "Slope": "1.0 1.0 1.0", "Offset": "0.0 0.0 0.0",
                                          "Power": "1.0 1.0 1.0", "Saturation": "0.0"}))
    ok("clipe que não está na timeline é registrado e segue", (res[1]["ok"], res[1]["erro"]),
       (False, "clipe não encontrado na timeline"))
    ok("⛔ saturação que não é número não chega ao Resolve", (res[2]["ok"], res[2]["erro"]), (False, "nada a aplicar"))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print("  ✗", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
