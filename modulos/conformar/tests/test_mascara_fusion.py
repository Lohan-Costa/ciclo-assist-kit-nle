"""Máscara, blur e Basic 3D do Premiere → composição do Fusion criada depois do import (2026-10-03).

Rodar:

    .venv/bin/python tests/test_mascara_fusion.py        (Windows: .venv-win/Scripts/python)

O critério forte foi o da imagem, no Resolve 21.1 (Mac), contra o export do PRODUCAO_B: o blur do
A055C012 (01:01:42:06), o insert do interfone (01:00:49:14) e o Basic 3D 20/20 do caso R02
(0,9993 contra o export do Premiere). Aqui fica o que não precisa do
Resolve: a receita que a leitura tira do PRPROJ, o texto do Polygon, as regras de inversão e a
montagem dos nós (com uma composição de mentira), e o casamento que trata cópias idênticas de um
original em dois HDs como UM original.

Com o caso `03 CASOS/REAL/R02 PRODUCAO_B EXEMPLOS` no disco (`DLPC_AMOSTRAS`), a leitura
real também é conferida; sem ele, essa parte é PULADA.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp import fusion_clipe as fm  # noqa: E402
from prproj import originais  # noqa: E402
from prproj.leitura import Geo  # noqa: E402
from prproj.mascara import para_fonte_de_dentro  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def perto(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ── um item da timeline de mentira, só o que `executar` usa ─────────────────

def _religar(texto: str) -> str:
    """O que o Resolve faz no import em clipe sem composição: o MediaIn1 passa a ler a mídia do clipe."""
    return texto.replace("MediaIn1 = Loader {", 'MediaIn1 = Loader { CustomData = { MediaProps = { MEDIA_PATH = "x.mov", }, },', 1)


class Item:
    """Um TimelineItem como o MEDIDO (2026-10-03): no 19, `ImportFusionComp` só vale num clipe sem
    composição (e religa o MediaIn); com composição devolve "ok" e não muda nada, e a única composição
    não se apaga. No 21, substitui a ativa (a última). O import em clipe vazio no 21 é `pendente`
    (aqui suposto igual ao 19)."""

    def __init__(self, versao=19, comps=0, religa=True):
        self.versao, self.comps, self.importados = versao, [MODELO_COMP] * comps, []
        self.religa = religa

    def AddFusionComp(self):
        self.comps.append(MODELO_COMP)
        return object()

    def GetFusionCompNameList(self):
        return [f"Composition {i + 1}" for i in range(len(self.comps))]

    def LoadFusionCompByName(self, n):
        return object()

    def DeleteFusionCompByName(self, n):
        if len(self.comps) < 2:
            return False
        self.comps.pop(int(n.split()[-1]) - 1)
        return True

    def ExportFusionComp(self, arq, indice):
        with open(arq, "w", encoding="utf-8") as f:
            f.write(self.comps[indice - 1])
        return True

    def ImportFusionComp(self, arq):
        with open(arq, encoding="utf-8") as f:
            texto = f.read()
        self.importados.append(texto)
        if not self.comps:
            self.comps.append(_religar(texto) if self.religa else texto)
        elif self.versao >= 21:
            self.comps[-1] = texto
        return object()


#: O começo de uma composição nova como o Resolve 21.1 a exporta (MediaIn1 → MediaOut1), enxugado.
MODELO_COMP = """Composition {
\tTools = {
\t\tMediaIn1 = Loader {
\t\t\tCustomData = { MediaProps = { MEDIA_PATH = "F:\\INSERT.MOV", MEDIA_WIDTH = 3840, }, },
\t\t\tInputs = {
\t\t\t\tGlobalIn = Input { Value = -379, },
\t\t\t},
\t\t\tViewInfo = OperatorInfo { Pos = { 55, 50 } },
\t\t},
\t\tMediaOut1 = Saver {
\t\t\tInputs = {
\t\t\t\tIndex = Input { Value = "0", },
\t\t\t\tInput = Input {
\t\t\t\t\tSourceOp = "MediaIn1",
\t\t\t\t\tSource = "Output",
\t\t\t\t}
\t\t\t},
\t\t\tViewInfo = OperatorInfo { Pos = { 605, 49 } },
\t\t},
\t},
}
"""

QUADRADO = [[False, [0.25, 0.25], [0.25, 0.25], [0.25, 0.25]],
            [True, [0.75, 0.25], [0.70, 0.25], [0.80, 0.25]],
            [False, [0.75, 0.75], [0.75, 0.75], [0.75, 0.75]],
            [False, [0.25, 0.75], [0.25, 0.75], [0.25, 0.75]]]


def main() -> int:
    print("Polygon do Fusion")
    no = fm.plano([{"efeito": "desfoque", "px": 10.0, "fonte_px": [2880, 1620],
                    "mascaras": [{"vertices": QUADRADO, "invertida": False, "suave_px": 27.5}]}])["nos"][1]
    st = fm.setting(no)
    ok("canto vira ponto Linear, a partir do centro, Y para cima",
       "{ Linear = true, X = -0.25, Y = 0.25 }" in st, True)
    ok("ponto suave leva as alças relativas (Y invertido)",
       "{ X = 0.25, Y = 0.25, LX = -0.05, LY = 0, RX = 0.05, RY = 0 }" in st, True)
    ok("máscara do tamanho da FONTE (o Polygon nasce com 320×240)",
       ("MaskWidth = Input { Value = 2880, }" in st, "MaskHeight = Input { Value = 1620, }" in st),
       (True, True))
    ok("Feather 27,5 px numa fonte de 2880 → SoftEdge 0,845 × 27,5 ÷ 2880 (B14)", "SoftEdge = Input { Value = 0.008069, }" in st, True)
    ok("sem Invert quando não pedido", "Invert" in st, False)

    print("O plano (os nós e as ligações)")
    rec = {"efeito": "recorte", "fonte_px": [3840, 2160],
           "mascaras": [{"vertices": QUADRADO, "invertida": True, "suave_px": 0.0}]}
    pl = fm.plano([rec])
    ok("recorte: Polygon no EffectMask do MediaIn, sem nó na cadeia",
       pl["ligacoes"], [["MediaIn1", "EffectMask", "Polygon1"]])
    ok("recorte com máscara INVERTIDA no Premiere = Polygon normal (mostra o de dentro)",
       pl["nos"][0]["inverter"], False)
    ok("recorte com máscara normal = Polygon invertido",
       fm.plano([{**rec, "mascaras": [{**rec["mascaras"][0], "invertida": False}]}])["nos"][0]["inverter"], True)
    pl = fm.plano([{"efeito": "desfoque", "px": 57.3, "direcao": 0, "fonte_px": [2880, 1620],
                    "mascaras": [{"vertices": QUADRADO, "invertida": False, "suave_px": 27.5}]}])
    ok("desfoque: MediaIn → Blur → MediaOut, Polygon no EffectMask do Blur", pl["ligacoes"],
       [["Blur1", "Input", "MediaIn1"], ["Blur1", "EffectMask", "Polygon1"], ["MediaOut1", "Input", "Blur1"]])
    # laboratório B20 (2026-10-11): XBlurSize = 0,2521·Blurriness − 0,259 (as duas larguras medidas no degrau, retas exatas)
    ok("desfoque: Blurriness 57,3 → XBlurSize 14,19 (B20: largura 10–90 % igual no Premiere e no Fusion)",
       round(pl["nos"][0]["entradas"]["XBlurSize"], 2), 14.19)
    ok("desfoque com máscara normal desfoca o de DENTRO (Polygon sem Invert)", pl["nos"][1]["inverter"], False)
    e = fm.plano([{"efeito": "desfoque", "px": 10.0, "direcao": 1, "fonte_px": [1920, 1080],
                   "mascaras": []}])["nos"][0]["entradas"]
    ok("desfoque só horizontal: XY destravado, Y = 0", (e["LockXY"], e["YBlurSize"]), (0, 0.0))

    print("Basic 3D")
    c = fm.cantos_basic3d(20, 20, [3840, 2160])
    ok("20/20: canto de cima à esquerda onde o export do Premiere o mostra (0,035 × 0,935)",
       (round(c["TopLeft"][0], 3), round(c["TopLeft"][1], 3)), (0.035, 0.935))
    ok("sem giro, os cantos ficam nos cantos", fm.cantos_basic3d(0, 0, [1920, 1080]),
       {"TopLeft": (0.0, 1.0), "TopRight": (1.0, 1.0), "BottomLeft": (0.0, 0.0), "BottomRight": (1.0, 0.0)})
    b3 = {"efeito": "basic3d", "swivel": 1.8, "tilt": -1.9, "fonte_px": [3840, 2160], "mascaras": []}
    ok("recorte + Basic 3D numa composição SÓ: Polygon no MediaIn → CornerPositioner → MediaOut",
       fm.plano([rec, b3])["ligacoes"],
       [["MediaIn1", "EffectMask", "Polygon1"], ["CornerPositioner1", "Input", "MediaIn1"],
        ["MediaOut1", "Input", "CornerPositioner1"]])
    # ⭐ (2026-11-20) o Premiere aplica do último índice do arquivo para o primeiro: o recorte pode vir DEPOIS de outro
    #   efeito (o insert do PRODUCAO_B gira e depois recorta). Antes era recusado; agora é Merge sobre fundo transparente
    #   com o Polygon no EffectMask — o mesmo desenho da máscara de opacidade no fim.
    ok("Basic 3D → recorte: CornerPositioner → Merge (Background transparente) com o Polygon → MediaOut",
       fm.plano([b3, rec])["ligacoes"],
       [["CornerPositioner1", "Input", "MediaIn1"], ["Merge1", "Background", "Background1"],
        ["Merge1", "Foreground", "CornerPositioner1"], ["Merge1", "EffectMask", "Polygon1"],
        ["MediaOut1", "Input", "Merge1"]])

    print("Executar: o import CONFERIDO pelo export de volta (Resolve 19 e 21 medidos)")
    it = Item(19)
    r = fm.aplicar(it, [rec, b3])
    ok("⭐ 19, clipe sem composição: importa direto o molde composto, UMA composição",
       (r, len(it.importados), len(it.comps)), ({"ok": True, "comp": "Composition 1"}, 1, 1))
    ok("…o texto importado é o molde mínimo composto (o MediaIn o Resolve religa)",
       it.importados[0], fm.compor(fm.MODELO, fm.plano([rec, b3])))
    ok("o texto importado tem o Polygon e o CornerPositioner configurados",
       ("Polygon1 = PolylineMask { Inputs = {" in it.importados[0],
        "CornerPositioner1 = CornerPositioner { Inputs = { TopLeft" in it.importados[0]), (True, True))
    it = Item(19, comps=1)
    r = fm.aplicar(it, [rec, b3])
    ok("⛔ 19, clipe que JÁ tem composição: o 'ok' do import não engana — falha avisada",
       (r["ok"], "refazer à mão" in r.get("erro", "")), (False, True))
    ok("…e a composição vazia que a tentativa criou sai (a do usuário fica)", len(it.comps), 1)
    it = Item(19, religa=False)
    r = fm.aplicar(it, [rec, b3])
    ok("⛔ 19, o import direto cria uma composição que não confere e ela não se apaga: para e avisa",
       (r["ok"], "refazer à mão" in r.get("erro", "")), (False, True))
    ok("…sem empilhar outra por cima (nenhum AddFusionComp)", len(it.comps), 1)
    it = Item(21, comps=1)
    r = fm.aplicar(it, [rec, b3])
    ok("21, clipe com a composição do usuário: uma NOVA, montada sobre o export",
       (r, len(it.comps), it.comps[0] == MODELO_COMP), ({"ok": True, "comp": "Composition 2"}, 2, True))
    ok("…com o texto composto sobre o que o Resolve exportou",
       it.importados[-1], fm.compor(MODELO_COMP, fm.plano([rec, b3])))

    # ⭐ Fase 4 do plano um app só (2026-11-07): a casca do Resolve (`plugins/resolve/casca`, a ponte `dlpc:fusion` em
    # JavaScript) saiu — nenhum painel dentro dos NLEs. Ficam as conferências do lado Python, que é quem compõe.
    print("A composição do Fusion (o lado Python)")
    receitas = [{"efeito": "recorte", "fonte_px": [3840, 2160],
                 "mascaras": [{"vertices": QUADRADO, "invertida": True, "suave_px": 3.0}]},
                {"efeito": "basic3d", "swivel": 1.8, "tilt": -1.9, "fonte_px": [3840, 2160],
                 "mascaras": []}]
    pl = fm.plano(receitas)
    # ⭐ R04 (2026-10-10): máscara de OPACIDADE + Gaussian Blur — o Premiere desfoca e SÓ ENTÃO recorta (a
    # Opacidade é efeito fixo): o Polygon vai no Merge do FIM da cadeia, não no MediaIn
    op_blur = [{"efeito": "opacidade", "fonte_px": [1920, 1080],
                "mascaras": [{"vertices": QUADRADO, "invertida": False, "suave_px": 20.0}]},
               {"efeito": "desfoque", "fonte_px": [1920, 1080], "px": 87.0, "direcao": 0}]
    pl_ob = fm.plano(op_blur)
    ok("…a ordem do Premiere: MediaIn → Blur → Merge (Background transparente, Polygon no EffectMask) → MediaOut",
       pl_ob["ligacoes"], [["Blur1", "Input", "MediaIn1"], ["Merge1", "Background", "Background1"],
                           ["Merge1", "Foreground", "Blur1"], ["Merge1", "EffectMask", "Polygon1"],
                           ["MediaOut1", "Input", "Merge1"]])
    ok("…sem desfoque, a máscara de opacidade continua no MediaIn (o caminho já validado)",
       fm.plano(op_blur[:1])["ligacoes"], [["MediaIn1", "EffectMask", "Polygon1"]])
    texto = fm.compor(MODELO_COMP, pl)
    ok("composição: Polygon no EffectMask do MediaIn, MediaOut1 vindo do CornerPositioner",
       ('EffectMask = Input { SourceOp = "Polygon1", Source = "Mask", },' in texto,
        'SourceOp = "CornerPositioner1"' in texto[texto.index("MediaOut1 = Saver"):],
        'Input = Input { SourceOp = "MediaIn1", Source = "Output", }' in texto), (True, True, True))

    print("Contorno animado com números de vértices diferentes por keyframe (R04, LOU_7310)")
    # o Fusion interpola o Polyline pelo índice do ponto: 4 → 5 → 4 vértices saía torto no Resolve
    def bez(vs, t):
        """Pontos do contorno (receita) amostrados — para provar que a forma não mudou."""
        pts = []
        for k in range(len(vs)):
            s0, p0, _, o0 = vs[k]
            s3, p3, i3, _ = vs[(k + 1) % len(vs)]
            p1, p2 = (o0 if s0 else p0), (i3 if s3 else p3)
            for u in t:
                pts.append(tuple(round((1 - u) ** 3 * a + 3 * (1 - u) ** 2 * u * b + 3 * (1 - u) * u * u * c + u ** 3 * d, 6)
                                 for a, b, c, d in zip(p0, p1, p2, p3)))
        return pts
    CINCO = QUADRADO[:2] + [[True, [0.8, 0.5], [0.8, 0.4], [0.8, 0.6]]] + QUADRADO[2:]
    igual = fm.igualar_vertices([QUADRADO, CINCO, QUADRADO])
    ok("igualados: todos com 5 vértices", [len(c) for c in igual], [5, 5, 5])
    ok("o do meio (já com 5) fica intacto", igual[1], CINCO)
    import math as _m
    longe = max(min(_m.dist(p, q) for q in bez(igual[0], [i / 200 for i in range(200)]))
                for p in bez(QUADRADO, [i / 50 for i in range(50)]))
    ok("o de 4 dividido continua com a MESMA forma (curva e retas)", longe < 0.002, True)
    pl_desigual = fm.plano([{"efeito": "opacidade", "fonte_px": [1920, 1080], "mascaras": [{
        "vertices": QUADRADO, "invertida": False, "suave_px": 0.0,
        "quadros": [{"quadro": 10, "vertices": QUADRADO}, {"quadro": 14, "vertices": CINCO},
                    {"quadro": 18, "vertices": QUADRADO}]}]}])
    poly = pl_desigual["nos"][0]
    ok("no plano: o BezierSpline recebe keyframes de 5 pontos e o estático = o 1º keyframe",
       ([len(p) for p in poly["pontos_quadros"]], poly["pontos"] == poly["pontos_quadros"][0]), ([5, 5, 5], True))

    print("Contorno assado quadro a quadro (laboratório B16, 2026-10-10)")
    from prproj.leitura import _assar_contorno
    TQ = 10594584000                                   # um quadro de 23,976 em ticks
    QUAD_B = [[s, [x + .2, y], [i[0] + .2, i[1]], [o[0] + .2, o[1]]] for s, (x, y), i, o in QUADRADO]
    kfs = [{"t": 0, "vertices": QUADRADO}, {"t": 4 * TQ, "vertices": QUAD_B}]
    # clipe a 1×, mídia na taxa da timeline: o quadro k mostra a fonte k e a máscara no tempo k
    assado = _assar_contorno(kfs, lambda T: T, lambda T: T, 0, 6, TQ, TQ)
    ok("um keyframe por quadro, no tempo da composição = a fonte mostrada",
       [q["quadro"] for q in assado], [0, 1, 2, 3, 4, 5])
    ok("…a forma interpolada em linha reta entre os keyframes do Premiere (k = 2: metade do caminho)",
       round(assado[2]["vertices"][1][1][0], 6), round(0.75 + 0.1, 6))
    ok("…e segura depois do último keyframe", assado[5]["vertices"], QUAD_B)
    # nest acelerado: a máscara anda no tempo do Premiere (0, 2.5, 5…), a composição no PISO da fonte mostrada
    vel = 2.5
    assado = _assar_contorno(kfs, lambda T: T * vel, lambda T: T * vel, 0, 3, TQ, TQ)
    ok("velocidade 2,5: composição em 0, 2, 5 (piso), forma no tempo exato 0 / 2,5 / 5",
       ([q["quadro"] for q in assado], round(assado[1]["vertices"][1][1][0], 6)), ([0, 2, 5], round(0.75 + 0.2 * 2.5 / 4, 6)))
    # câmera lenta: dois quadros na mesma fonte ficam com o primeiro
    assado = _assar_contorno(kfs, lambda T: T * 0.5, lambda T: T * 0.5, 0, 4, TQ, TQ)
    ok("câmera lenta 0,5×: sem tempo da composição repetido", [q["quadro"] for q in assado], [0, 1])

    print("Máscara de opacidade num clipe com Flip (R04, JUL_7644 em 4:23, 2026-10-10)")
    from prproj.leitura import _espelhar
    r = {"efeito": "opacidade", "mascaras": [{"vertices": QUADRADO, "quadros": [{"t": 0, "vertices": QUADRADO}]}]}
    _espelhar(r, [True, False])
    def arred(v):
        return [v[0]] + [[round(c, 6) for c in p] for p in v[1:]]
    ok("Flip horizontal: o contorno vai espelhado (x → 1 − x), alças inclusive; y fica",
       (arred(r["mascaras"][0]["vertices"][1]), arred(r["mascaras"][0]["quadros"][0]["vertices"][1])),
       ([True, [0.25, 0.25], [0.3, 0.25], [0.2, 0.25]],) * 2)
    r2 = {"efeito": "desfoque", "mascaras": [{"vertices": QUADRADO}]}
    ok("…só a opacidade (a máscara de um efeito depende da ordem na pilha — não medido)",
       _espelhar(r2, [True, False])["mascaras"][0]["vertices"], QUADRADO)

    print("Keyframe Bézier do Motion (R04, JUL_7504 na transição da perna, 2026-10-10)")
    from prproj.leitura import _bezier_trecho
    TPS_ = 254016000000
    ta, tb = 656864208000, 911134224000
    pa = "656864208000,0.18593749403953552:0.5,0,0,0,0.16666666666666666,0.31374875720326123,0.16666666666666666,5,4,0,0,0.052343750993410744,0".split(",")
    pb = "911134224000,0.5:0.5,5,0,0.53785501234844779,0.33333333333333331,0.53785501234844779,0.33333333333333331,5,4,-0.052343750993410744,-0,0,0".split(",")
    t531 = 752215464000 + 5 * TPS_ * 1001 // 24000           # o quadro 531 (o clipe começa no 526, a 1×)
    x = float(_bezier_trecho(ta, pa[1], pa, tb, pb[1], pb, t531).split(":")[0])
    lin = 0.18593749403953552 + (0.5 - 0.18593749403953552) * (t531 - ta) / (tb - ta)
    ok("⭐ a curva põe a imagem ~32 px (de 960) à esquerda do linear no 531 — o medido contra o Premiere",
       round((x - lin) * 960), -32)
    lin_a = pa[:2] + ["0"] * 7
    ok("trecho linear (tipo temporal 0 nos dois, sem curva espacial) → None (o linear de sempre)",
       _bezier_trecho(ta, "1.", lin_a, tb, "2.", lin_a, t531), None)

    # o laboratório B17 (Premiere 23.2, a borda da placa mede a escala): parâmetro de UM eixo (8 campos) e o hold
    TQ_ = 10594584000
    k0 = ["0", "90.", "0", "0", "0", "0.16666666666666666", "-89.910089910089908", "0.16666666666666666"]
    k8 = [str(8 * TQ_), "60.", "5", "0", "30.0", "1.0", "0", "0.16666666666666666"]
    ok("⭐ Scale com overshoot (vel. de entrada +30, influência 1): a curva medida no Premiere (58,27 no quadro 5)",
       round(float(_bezier_trecho(0, "90.", k0, 8 * TQ_, "60.", k8, 5 * TQ_)), 1), 58.3)
    h0 = ["0", "90.", "4", "0", "0", "0.16666666666666666", "0", "0.33333333333333331"]
    h8 = [str(8 * TQ_), "60.", "4", "0", "-89.9", "0.16666666666666666", "0", "0.33333333333333331"]
    ok("hold (tipo 4): segura até o próximo keyframe e chega nele",
       (_bezier_trecho(0, "90.", h0, 8 * TQ_, "60.", h8, 7 * TQ_), _bezier_trecho(0, "90.", h0, 8 * TQ_, "60.", h8, 8 * TQ_)),
       ("90.", "60."))

    print("O lado Python confere o plano como a casca")
    pl = fm.plano([rec, b3])

    def recusa(mexer):
        import copy
        x = copy.deepcopy(pl)
        mexer(x)
        try:
            fm.compor(MODELO_COMP, x)
            return "passou"
        except ValueError as e:
            return str(e)
    ok("⛔ id com código Lua é recusado",
       recusa(lambda x: x["nos"][0].update(id='x = 1 } os.execute("y") --')), "nó inválido no plano")
    ok("⛔ texto no lugar de número é recusado",
       recusa(lambda x: x["nos"][0].update(suave="0) os.execute('x') --")), "número inválido no plano do Fusion")
    ok("⛔ ligação para nó que não existe é recusada",
       recusa(lambda x: x["ligacoes"].append(["MediaOut1", "Input", "Blur9"])), "ligação inválida no plano")
    ok("o plano legítimo passa", recusa(lambda x: None), "passou")

    print("Máscara num plano que aponta para um take aninhado")
    g = Geo(esc=0.5, rot=0.0, tx=100.0, ty=-50.0)        # fonte 2000×1000 no take 1000×500
    v = para_fonte_de_dentro([(False, (0.6, 0.4), (0.6, 0.4), (0.6, 0.4))], g, (1000, 500), (2000, 1000))
    # take: (0,6−0,5)·1000 − 100 = 0 ; (0,4−0,5)·500 + 50 = 0 → centro da fonte
    ok("o ponto do take volta à fonte pela inversa da geometria", perto(v[0][1], (0.5, 0.5)), True)
    g = Geo(esc=1.0, rot=90.0, tx=0.0, ty=0.0)
    v = para_fonte_de_dentro([(False, (0.5, 0.75), (0.5, 0.75), (0.5, 0.75))], g, (1000, 1000), (1000, 1000))
    ok("rotação dentro do take também é desfeita", perto(v[0][1], (0.75, 0.5)), True)

    print("Originais em dois HDs")
    with tempfile.TemporaryDirectory() as d:
        a, b, c_ = (os.path.join(d, x, "A001C001.mxf") for x in ("hd1", "hd2", "hd3"))
        for caminho, conteudo in ((a, b"x" * 3000), (b, b"x" * 3000), (c_, b"y" * 3000)):
            os.makedirs(os.path.dirname(caminho))
            with open(caminho, "wb") as f:
                f.write(conteudo)
        sonda = originais.sondar
        originais.sondar = lambda p: {"ok": True, "w": 2880, "h": 1620, "codec": "arri",
                                      "dur_s": 1.0, "tc": None}
        completo = originais.mxf_completo
        originais.mxf_completo = lambda p: True
        try:
            idx = originais.indexar([os.path.join(d, "hd1"), os.path.join(d, "hd2")])
            r = originais.casar_um("/proxy/A001C001.mov", idx)
            ok("cópia idêntica nos dois HDs = UM original, no caminho do 1º HD",
               (r["estado"], r["original"], r["copias"]), ("original", a, [b]))
            idx = originais.indexar([os.path.join(d, "hd1"), os.path.join(d, "hd3")])
            r = originais.casar_um("/proxy/A001C001.mov", idx)
            ok("arquivos DIFERENTES com o mesmo nome continuam ambíguos (empate é do editor)",
               (r["estado"], r["original"]), ("ambiguo", None))
        finally:
            originais.sondar, originais.mxf_completo = sonda, completo

    caso = None
    from casos import CANDIDATAS_AMOSTRAS  # noqa: E402 (a pasta de testes, nas duas máquinas)
    for raiz in CANDIDATAS_AMOSTRAS:
        p = os.path.join(raiz or "", "03 CASOS", "REAL", "R02 PRODUCAO_B EXEMPLOS", "premiere",
                         "DU exemplos especificos.prproj")
        if raiz and os.path.exists(p):
            caso = p
            break
    if caso is None:
        print("Leitura do projeto de casos: PULADA (R02 PRODUCAO_B EXEMPLOS não está no disco)")
    else:
        print("Leitura do projeto de casos")
        from prproj.leitura import Leitor
        from prproj.projeto import Projeto
        segs = Leitor(Projeto(caso)).ler("DU exemplos especificos")["segmentos"]
        rec: dict = {}
        for s_ in segs:
            for e in s_.get("effects") or []:
                if e.get("category") == "fusion":
                    rec.setdefault((s_["timeline_tc_in"], s_["track"]), []).append(e["params"])
        ok("três clipes com composição: o insert (V3, 0), o blur (V3, 10:15), o Basic 3D (V1, 15:12)",
           sorted(rec), [("00:00:00:00", 3), ("00:00:10:15", 3), ("00:00:15:12", 1)])
        # ⭐ na ordem do RENDER (2026-11-20): o arquivo diz [Crop com máscara, Basic 3D] e o Premiere aplica do último
        #   índice para o primeiro (medido: `laboratorio-de-midia/lab/premiere_ordem_fusion.py`) — gira, depois recorta
        ok("o insert leva Basic 3D e depois o recorte (a ordem do render do Premiere)",
           [r["efeito"] for r in rec[("00:00:00:00", 3)]], ["basic3d", "recorte"])
        b3 = rec[("00:00:15:12", 1)][0]
        ok("o clipe de calibração: Swivel 20, Tilt 20, na fonte de 3840×2160",
           (b3["efeito"], b3["swivel"], b3["tilt"], b3["fonte_px"]), ("basic3d", 20.0, 20.0, [3840, 2160]))
        ins = next(r for r in rec[("00:00:00:00", 3)] if r["efeito"] == "recorte")
        blur = rec[("00:00:10:15", 3)][0]
        # Máscara de outra versão do Premiere que não se lê: só aquele efeito vira "refazer" (antes
        # um struct.error derrubava a sequência inteira — revisão de código, 2026-10-03).
        import struct
        from unittest import mock

        import prproj.leitura as L
        with mock.patch.object(L, "ler_mascaras", side_effect=struct.error("cabeçalho diferente")):
            segs2 = Leitor(Projeto(caso)).ler("DU exemplos especificos")["segmentos"]
        nomes = {e["name"] for s_ in segs2 for e in s_.get("effects") or [] if not e.get("reproducible")}
        ok("máscara ilegível: a sequência é lida inteira e os dois efeitos viram 'refazer'",
           {"crop com máscara (ilegível)", "Gaussian Blur com máscara (ilegível)"} <= nomes, True)
        ok("máscara ilegível: nenhuma composição do Fusion de máscara é criada",
           [e["params"]["efeito"] for s_ in segs2 for e in s_.get("effects") or []
            if e.get("category") == "fusion" and e["params"]["efeito"] != "basic3d"], [])
        ok("insert: recorte, 12 vértices, máscara invertida, sem suavidade",
           (ins["efeito"], len(ins["mascaras"][0]["vertices"]), ins["mascaras"][0]["invertida"],
            ins["mascaras"][0]["suave_px"]), ("recorte", 12, True, 0.0))
        ok("blur: 57,3 px nas duas direções, Repeat Edge Pixels, máscara de 6 pontos com feather",
           (blur["efeito"], round(blur["px"], 1), blur["direcao"], blur["repetir_bordas"],
            len(blur["mascaras"][0]["vertices"]), round(blur["mascaras"][0]["suave_px"], 1)),
           ("desfoque", 57.3, 0, True, 6, 27.5))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
