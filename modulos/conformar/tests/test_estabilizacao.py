"""O Stabilize do Avid → o estabilizador do Resolve (autor, 2026-10-24: chega PRONTA e LIGADA).

Rodar:

    .venv/bin/python tests/test_estabilizacao.py

1. a conta do Avid (`motor/estabilizacao.py`): a gaussiana "nearest" sem o scipy, o deslocamento fixo com o SINAL dos
   números medidos (X troca, Y não), o raster dos `settings`;
2. o AAF real da PRODA (`03 CASOS/REAL/R01 PRODA_CORTE`): os 2 Stabilize_2 com o tracker, a nota "ESTABILIZAÇÃO
   TRADUZIDA" sem cor, e o plano do writer;
3. o lado do Resolve (`motor/drp/estabilizador.py`) sobre a análise REAL de um `Stabilize()` do Resolve 21.1
   (`03 CASOS/EFEITOS/E07 ESTABILIZADOR/resolve/`): os blocos `0x10300015` trocados, o clipe aparado contando pela
   mídia, e o `.drx` mínimo. Sem a pasta de testes: PULADO.
O ponta a ponta pela imagem (0,999 contra o render do MC) é do laboratório: `drp/estabilizador.py`, docstring.
"""

from __future__ import annotations

import math
import re
import struct
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import estabilizacao as E  # noqa: E402
from drp import estabilizador as R  # noqa: E402

from casos import amostras  # noqa: E402

falhas: list[str] = []
casos = 0


def ok(rotulo: str, obtido, esperado) -> None:
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}")


def perto(a, b, tol=1e-6) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b)) and len(a) == len(b)


def gauss_referencia(v, sigma):
    """`gaussian_filter1d(mode="nearest", truncate=4)`, escrita de outro jeito (borda repetida + convolução)."""
    r = int(4 * sigma + 0.5)
    pad = [v[0]] * r + list(v) + [v[-1]] * r
    k = [math.exp(-0.5 * (i / sigma) ** 2) for i in range(-r, r + 1)]
    s = sum(k)
    return [sum(pad[j + i] * k[i] for i in range(len(k))) / s for j in range(len(v))]


def conta() -> None:
    print("1. a conta do Avid")
    v = [math.sin(k / 7.0) * 0.01 + 0.4 + (0.003 if k % 5 == 0 else 0) for k in range(120)]
    ok("a gaussiana 'nearest' (σ 15) = a de referência", perto(E._gauss_nearest(v, 15.0), gauss_referencia(v, 15.0),
                                                              1e-12), True)
    # trilha PARADA: só o deslocamento fixo fica — e com o sinal dos números medidos (23,976: POS_X −2,02, zoom 1,0604
    # → +3,64 px de fonte; POS_Y +0,062 → +0,04)
    d = {"filtro": 0.5, "zoom": 1.0604, "pos": [-2.02, 0.062], "x": [0.4] * 50, "y": [0.5] * 50}
    u = E.correcao(d)
    ok("⭐ POS_X −2,02 vira +3,66 px (o X troca de sinal)", round(u[10][0] * 1920, 2), 3.66)
    ok("⭐ POS_Y +0,062 vira +0,06 px (o Y não)", round(u[10][1] * 1080, 2), 0.06)
    # um degrau no rastreio: a correção puxa de volta (u = p − G(p)), e é zero longe do degrau
    d = {"filtro": 0.2, "zoom": 1.0, "pos": [0, 0], "x": [0.4] * 40 + [0.41] * 40, "y": [0.5] * 80}
    u = E.correcao(d)
    ok("degrau: zero longe dele", (round(u[0][0], 6), round(u[79][0], 6)), (0.0, 0.0))
    ok("degrau: depois dele a imagem anda para o lado do salto", u[40][0] > 0 and u[39][0] < 0, True)
    ok("o raster dos settings (80 07 38 04 no byte 14)",
       E._raster(bytes(14) + bytes.fromhex("80073804") + bytes(38)), (1920, 1080))
    ok("amostrar: linear entre os pontos, a ponta fora deles",
       [round(x, 3) for x in E._amostrar([(1, 0.0), (3, 1.0)], 5)], [0.0, 0.0, 0.5, 1.0, 1.0])
    seg = {"effects": [{"name": "Stabilize_2", "params": {"estabilizacao": {"x": [0.4]}}}], "relative_speed": 1.0}
    ok("traduzível: com o tracker e sem velocidade", E.traduzivel(seg), True)
    ok("com velocidade não (o quadro do Avid ≠ o do clipe)", E.traduzivel({**seg, "relative_speed": 0.5}), False)
    ok("sem o tracker não", E.traduzivel({"effects": [{"name": "Stabilize_2", "params": {}}]}), False)
    ok("modo suavizar (não medido): não vira tradução",
       E._montar([0.4], [0.5], 0.5, True, True, None, 0, 0, 100), None)


def cruz() -> None:
    print("2. a PRODA (AAF do MC)")
    a = amostras()
    aaf = a / "03 CASOS" / "REAL" / "R01 PRODA_CORTE" / "avid" / "PRODA_RELINKER_ALTA.aaf" if a else None
    if not aaf or not aaf.is_file():
        print(f"  PULADO — não achei {aaf}")
        return
    from aaf.leitura import ler_timeline_aaf
    from drp.writer import _plano_de_estabilizacao
    from notas import das_notas

    leitura = ler_timeline_aaf(str(aaf))
    est = [(i, s) for i, s in enumerate(leitura["segments"]) if E.dados_do_segmento(s)]
    ok("⭐ os 2 Stabilize_2 da PRODA com o tracker", [(s["duration_frames"], len(E.dados_do_segmento(s)["x"]))
                                                   for _i, s in est], [(393, 393), (203, 203)])
    d = E.dados_do_segmento(est[1][1])
    ok("o 2º: filtro 0,5, zoom 104,28 %, 1920×1080", (d["filtro"], round(d["zoom"] * 100, 2), d["raster"]),
       (0.5, 104.28, [1920, 1080]))
    notas = das_notas(leitura)
    da = [n for n in notas if n.get("segmento") in {i for i, _s in est}]
    linhas = ["".join(t for t, _d in linha) for n in da for linha in n["linhas"]]
    ok("⭐ a nota diz ESTABILIZAÇÃO TRADUZIDA (com o zoom)", sorted(t for t in linhas if "ESTABILIZ" in t),
       ["ESTABILIZAÇÃO TRADUZIDA · Stabilize_2 · zoom 101,2%", "ESTABILIZAÇÃO TRADUZIDA · Stabilize_2 · zoom 104,3%"])
    ok("⭐ e sem cor (como as outras traduções)", [n.get("cor") for n in da], [None, None])
    i, s = est[1]
    plano = _plano_de_estabilizacao(s, "<Start>%d</Start>" % (86400 + 5000), "/x/A001_03170454_C013.mov")
    ok("o plano do writer: trilha, quadro, arquivo, quadros", (plano["trilha"], plano["quadro"], plano["arquivo"],
                                                              len(plano["u"])),
       (s["track"], 5000, "A001_03170454_C013.mov", 203))
    ok("a correção do plano é pequena (fração do quadro)", max(abs(c) for p in plano["u"] for c in p) < 0.05, True)


def resolve() -> None:
    print("3. o lado do Resolve (análise real do 21.1)")
    a = amostras()
    pasta = a / "03 CASOS" / "EFEITOS" / "E07 ESTABILIZADOR" / "resolve" if a else None
    inteiro = pasta / "B19_TREMIDO_STABILIZE_R21.drt" if pasta else None
    if not inteiro or not inteiro.is_file():
        print(f"  PULADO — não achei {inteiro}")
        return
    corpos = R.corpos_do_drt(str(inteiro))
    ok("o DRT exportado: 1 clipe com a análise, na V1", [(k[0], v[0], v[1]) for k, v in corpos.items()],
       [(1, "B19_TREMIDO.mov", 0)])
    (_nome, fonte_in, hexa), = corpos.values()
    corpo = R._dec(hexa)
    u = [[0.01, -0.02]] * 144
    novo, n = R.injetar(corpo, u, 1.06, fonte_in, 0)
    ok("144 quadros trocados", n, 144)
    blocos = [struct.unpack("<20f", b) for b in _blocos(novo)]
    ok("⭐ palavra 10 = 1/zoom; a translação × a ANÁLISE (1280 × 720)",
       perto(blocos[5][10:20], [1 / 1.06, 1, 0, 12.8, 0, 1, -14.4, 0, 0, 1], 1e-5), True)
    ok("o cabeçalho do bloco fica como veio", all(b[:40] == _blocos(corpo)[0][:40] for b in _blocos(novo)), True)
    ok("o resto do Body também (só os 40 bytes da correção mudam)", len(novo), len(corpo))

    aparado = pasta / "B19_TREMIDO_APARADO_30_STABILIZE_R21.drt"
    (_n2, in2, hexa2), = R.corpos_do_drt(str(aparado)).values()
    ok("clipe aparado: o In da mídia é 30", in2, 30)
    u = [[k / 10000.0, 0.0] for k in range(80)]
    novo, n = R.injetar(R._dec(hexa2), u, 1.0, in2, 0)
    tx = [round(struct.unpack("<20f", b)[13] / 1280 * 10000) for b in _blocos(novo)]
    ok("⭐ as entradas contam pela MÍDIA (q/2 − In = o quadro do segmento)", (n, tx[:3], tx[-1]), (80, [0, 1, 2], 79))
    novo, _n = R.injetar(R._dec(hexa2), u, 1.0, in2, -10)
    tx = [round(struct.unpack("<20f", b)[13] / 1280 * 10000) for b in _blocos(novo)]
    ok("clipe estendido pela transição: antes do segmento vale a ponta", tx[:12], [0] * 11 + [1])

    x = R.drx(novo)
    volta = R._dec(re.search(r"<Body>([0-9a-f]+)</Body>", x).group(1))
    ok("o .drx mínimo leva o Body inteiro", (x.count("<pClipFullVer>"), volta == novo), (1, True))

    # Mídia OFFLINE (2026-10-24): o molde dá os MESMOS blocos de correção da análise real, inteiro e aparado. Provado
    # pela imagem no Resolve 21.1 (Mac, "DLPC LAB ESTAB 21", B19 aparado em 30 e offline ao aplicar, religado depois):
    # 0,999 contra o render do MC nos 5 quadros, pelo `Stabilize()` (que no 21.1 aceita o offline com movimento zero)
    # e pelo molde.
    u = [[k / 10000.0, -k / 20000.0] for k in range(144)]
    for rot, fonte, f_in, n_q in (("inteiro", hexa, 0, 144), ("aparado", hexa2, 30, 80)):
        real, _n = R.injetar(R._dec(fonte), u, 1.05, f_in, 0)
        molde, n = R.injetar(R.corpo_do_molde(f_in, n_q), u, 1.05, f_in, 0)
        ok(f"⭐ molde = análise real ({rot}): os mesmos blocos de correção, quadro a quadro",
           (n, _blocos(molde) == _blocos(real)), (n_q, True))


def _blocos(body: bytes) -> list[bytes]:
    """Os 80 bytes do `0x10300015` de cada quadro, na ordem."""
    from tools.inspect_drp import pb_decode

    fora = []
    for e in R._entradas(pb_decode(body)):
        for p in R._filhos(e, 2):
            if next((x["value"] for x in p if x["field"] == 1), None) == R.CORRECAO:
                fora += [x["value"] for v in R._filhos(p, 2) for x in v if x["field"] == 5]
    return fora


def plano_invalido() -> None:
    print("4. o pedido do painel")
    bom = {"trilha": 1, "quadro": 0, "inicio": 0, "arquivo": "a.mov", "zoom": 1.04, "u": [[0.01, 0.0]]}
    ok("o plano do writer passa", R._plano_valido(bom), True)
    ok("correção absurda (≥ 1 quadro) não", R._plano_valido({**bom, "u": [[1.5, 0]]}), False)
    ok("zoom absurdo não", R._plano_valido({**bom, "zoom": 0}), False)
    tl = SimpleNamespace(GetStartFrame=lambda: 0, GetItemListInTrack=lambda *_a: [])
    ok("clipe que não está na timeline: registrado, os outros seguem",
       R.aplicar_estabilizacao(None, tl, {"estabilizar": [bom, {"trilha": "x"}]}, "/nao/usa"),
       [{"trilha": 1, "quadro": 0, "arquivo": "a.mov", "ok": False, "erro": "clipe não encontrado na timeline"},
        {"trilha": "x", "quadro": None, "arquivo": None, "ok": False, "erro": "pedido inválido"}])


def offline() -> None:
    print("5. mídia offline: o molde")
    from tools.inspect_drp import pb_decode

    corpo = R.corpo_do_molde(0, 3)
    qs = [next((x["value"] for x in e if x["field"] == 1 and x["wire"] == 0), None)
          for e in R._entradas(pb_decode(corpo))]
    ok("o molde está no Git e dá uma entrada por quadro (o quadro 0 sem o campo, como o Stabilize)", qs, [None, 2, 4])
    bom = {"trilha": 1, "quadro": 0, "inicio": 0, "arquivo": "a.mov", "zoom": 1.04, "u": [[0.01, 0.0]] * 5}
    item = SimpleNamespace(GetStart=lambda: 0, GetName=lambda: "a.mov", Stabilize=lambda: False,
                           GetLeftOffset=lambda: 0, GetDuration=lambda: 5)

    def tl(w, h):
        return SimpleNamespace(GetStartFrame=lambda: 0, GetItemListInTrack=lambda *_a: [item],
                               GetSetting=lambda k: {"timelineResolutionWidth": w, "timelineResolutionHeight": h}[k])
    with tempfile.TemporaryDirectory() as d:
        r = R.aplicar_estabilizacao(None, tl("3840", "2160"), {"estabilizar": [bom]}, d)
        ok("Stabilize recusado numa UHD: avisa (o molde só foi medido a 1080)", (r[0]["ok"], "1920×1080" in r[0]["erro"]),
           (False, True))
        visto = []
        R._aplicar_drx, antes = (lambda _t, _i, c: visto.append(c) or True), R._aplicar_drx
        try:
            r = R.aplicar_estabilizacao(None, tl("1920", "1080"), {"estabilizar": [bom]}, d)
        finally:
            R._aplicar_drx = antes
        ok("⭐ Stabilize recusado a 1080: aplica pelo molde", (r[0]["ok"], r[0].get("molde"), r[0].get("quadros"),
                                                              len(visto)), (True, True, 5, 1))


def main() -> int:
    conta()
    cruz()
    resolve()
    plano_invalido()
    offline()
    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
