"""INSERT PARA COR/VFX: a seleção a partir da cópia do editor e a timeline só com ela.

Rodar:

    .venv-win/Scripts/python tests/test_insert.py

Trava as regras de `motor/carta_aberta/insert.py` (decididas com o autor em 2026-09-24):
posição e TC preservados, clipe não escolhido vira vazio, transição só entre escolhidos (ou
fade de um escolhido), aparar no corte/trecho, e clipe com velocidade NUNCA aparado.

Com `DLPC_BIN_REAL` (uma ou mais `.avb`, separadas por `;`), toda sequência real passa por
uma "cópia" simulada de um trecho e vira um DRT de insert de verdade (mídia offline, sem
`ffprobe`).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from carta_aberta import insert as I  # noqa: E402

M = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.{:08x}.1bb20000.060e2b34.7f7f2a80"


def mid(n: int) -> str:
    return M.format(n)


def tc(f: int, fps: int = 25) -> str:
    return "%02d:%02d:%02d:%02d" % (f // (3600 * fps), f // (60 * fps) % 60, f // fps % 60, f % fps)


def clipe(track, ini, fim, n, src=0, **extra):
    s = {"track": track, "timeline_tc_in": tc(ini), "timeline_tc_out": tc(fim),
         "duration_frames": fim - ini, "mob_id": mid(n), "clip_name": f"C{n}",
         "source_start_frames": src, "source_fps": 25.0, "is_gap": False, "is_transition": False,
         "is_audio": track >= 1000, "has_motion_effect": False, "effects": [], "cutpoint": None,
         "media_ref": {"mob_name": f"C{n}", "local_path": ""}}
    s.update(extra)
    return s


def vazio(track, ini, fim):
    return {"track": track, "timeline_tc_in": tc(ini), "timeline_tc_out": tc(fim),
            "duration_frames": fim - ini, "mob_id": None, "clip_name": "(gap)", "is_gap": True,
            "is_transition": False, "is_audio": track >= 1000, "media_ref": None}


def trans(track, ini, fim, corte):
    return {"track": track, "timeline_tc_in": tc(ini), "timeline_tc_out": tc(fim),
            "duration_frames": fim - ini, "mob_id": None, "clip_name": "(transition)",
            "is_gap": False, "is_transition": True, "cutpoint": corte, "is_audio": track >= 1000,
            "media_ref": None}


def sequencia(segs, inicio=90000):
    return {"segments": segs, "timeline_fps": 25.0, "timeline_start_frames": inicio,
            "timeline_start_tc": tc(inicio), "masters": {}, "avisos": []}


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 58 else f"{repr(obtido)[:55]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<64} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    # V1: C1 [0,100) · C2 [100,200) com dissolve C2→C3 de 10 (corte em 205) · C3 [195,300)
    #     · vazio [300,350) · C4 [350,400) com fade-out [390,400)
    # V2: C5 [120,180)
    seq = sequencia([
        clipe(1, 0, 100, 1, src=500),
        clipe(1, 100, 205, 2, src=0),
        trans(1, 195, 205, 10 // 2),
        clipe(1, 195, 300, 3, src=1000),
        vazio(1, 300, 350),
        clipe(1, 350, 400, 4),
        trans(1, 390, 400, 10),
        clipe(2, 120, 180, 5, src=40),
        clipe(1000, 0, 100, 1, src=500),
    ])

    print("── 1. a cópia do editor vira itens casados com a sequência ──")
    # A cópia começa em 90000+100 (onde C2 começa) e traz C2 inteiro e C5 da V2.
    copia = sequencia([clipe(1, 0, 105, 2, src=0, clip_name="C2.sub.01"),
                       clipe(2, 20, 80, 5, src=40, clip_name="C5.sub.01")], inicio=90100)
    itens, avisos = I.selecao_da_copia(copia, seq)
    ok("dois itens, sem aviso", (len(itens), avisos), (2, []))
    ok("posição na SEQUÊNCIA (início da cópia + deslocamento)",
       [(i["track"], i["timeline_tc_in"], i["timeline_tc_out"]) for i in itens],
       [(1, tc(100), tc(205)), (2, tc(120), tc(180))])
    ok("⭐ o nome vem da sequência, não do subclipe", [i["clip_name"] for i in itens], ["C2", "C5"])
    ok("inteiros", [i["inteiro"] for i in itens], [True, True])
    ok("várias trilhas → o painel pede confirmação", I.trilhas_da_selecao(itens), ["V1", "V2"])

    parcial = sequencia([clipe(1, 0, 40, 3, src=1010)], inicio=90205)
    itens_p, _ = I.selecao_da_copia(parcial, seq)
    ok("trecho de um clipe (IN/OUT) → item parcial",
       [(i["timeline_tc_in"], i["timeline_tc_out"], i["inteiro"]) for i in itens_p],
       [(tc(205), tc(245), False)])

    errada = sequencia([clipe(1, 0, 105, 2, src=777)], inicio=90100)
    it_e, av_e = I.selecao_da_copia(errada, seq)
    ok("mesmo master com OUTRO ponto na fonte não casa", (it_e, len(av_e)), ([], 1))
    outra = sequencia([clipe(1, 0, 50, 99)], inicio=90100)
    it_o, av_o = I.selecao_da_copia(outra, seq)
    ok("clipe de outra sequência → aviso, nunca item", (it_o, "não está nesta sequência" in av_o[0]),
       ([], True))
    ok("taxa diferente → recusa inteira", I.selecao_da_copia({**copia, "timeline_fps": 24.0}, seq)[0], [])
    ok("impressão digital igual ⇔ mesma seleção",
       I.impressao_digital(itens) == I.impressao_digital(list(reversed(itens))), True)
    ok("e diferente para outra seleção", I.impressao_digital(itens) == I.impressao_digital(itens_p), False)

    print("\n── 2. a timeline só com o insert ──")

    def clipes(r):
        return [(s["track"], s["timeline_tc_in"], s["timeline_tc_out"], s["clip_name"],
                 s.get("source_start_frames")) for s in r["segments"] if s.get("mob_id")]

    def transicoes(r):
        return [(s["track"], s["timeline_tc_in"]) for s in r["segments"] if s.get("is_transition")]

    r = I.filtrar_insert(seq, itens)
    ok("só C2 e C5 ficam como clipe", [c[3] for c in clipes(r)], ["C2", "C5"])
    ok("⭐ C5 no MESMO lugar (V2 120–180)", [c for c in clipes(r) if c[3] == "C5"][0][:3],
       (2, tc(120), tc(180)))
    ok("C1, C3, C4 e o som viram vazio, no mesmo lugar",
       sorted((s["track"], s["timeline_tc_in"]) for s in r["segments"] if s.get("is_gap")
              and s["timeline_tc_in"] in (tc(0), tc(195), tc(350))),
       [(1, tc(0)), (1, tc(195)), (1, tc(350)), (1000, tc(0))])
    ok("dissolve C2→C3 com C3 fora: a transição sai", transicoes(r), [])
    ok("⭐ …e C2 é aparado no corte (205 → 200)", [c for c in clipes(r) if c[3] == "C2"][0][:3],
       (1, tc(100), tc(200)))
    ok("a leitura original não mudou", len(seq["segments"]), 9)

    ambos = I.filtrar_insert(seq, [{"track": 1, "timeline_tc_in": tc(100), "timeline_tc_out": tc(205),
                                    "mob_id": mid(2)},
                                   {"track": 1, "timeline_tc_in": tc(195), "timeline_tc_out": tc(300),
                                    "mob_id": mid(3)}])
    ok("dissolve entre DOIS escolhidos fica", transicoes(ambos), [(1, tc(195))])
    ok("…e ninguém é aparado", [c[1:3] for c in clipes(ambos)], [(tc(100), tc(205)), (tc(195), tc(300))])

    so_b = I.filtrar_insert(seq, [{"track": 1, "timeline_tc_in": tc(195), "timeline_tc_out": tc(300),
                                   "mob_id": mid(3)}])
    ok("só o lado B: entra no corte (195 → 200) e a FONTE anda 5",
       clipes(so_b), [(1, tc(200), tc(300), "C3", 1005)])

    fade = I.filtrar_insert(seq, [{"track": 1, "timeline_tc_in": tc(350), "timeline_tc_out": tc(400),
                                   "mob_id": mid(4)}])
    ok("⭐ fade-out do editor num escolhido FICA", transicoes(fade), [(1, tc(390))])

    pr = I.filtrar_insert(seq, itens_p)
    ok("trecho parcial: aparado ao trecho, fonte anda 10", clipes(pr), [(1, tc(205), tc(245), "C3", 1010)])

    veloz = sequencia([clipe(1, 0, 100, 7, has_motion_effect=True, speed_ratio=2.0)])
    rv = I.filtrar_insert(veloz, [{"track": 1, "timeline_tc_in": tc(10), "timeline_tc_out": tc(50),
                                   "mob_id": mid(7)}])
    ok("⛔ clipe com velocidade NÃO é aparado", clipes(rv)[0][1:3], (tc(0), tc(100)))
    ok("…e isso vira aviso", any("velocidade" in a["texto"] for a in rv["avisos"]), True)

    print("\n── 3. bins reais → DRT de insert (opcional) ──")
    reais = [p for p in (os.environ.get("DLPC_BIN_REAL") or "").split(";") if p.strip()]
    if not reais:
        print("  PULADO — defina DLPC_BIN_REAL=<.avb>[;<.avb>…]")
    else:
        from avb_bin import segmentos as S
        from avb_export.reader import topen
        from drp.writer import build_drt

        for caminho in reais:
            with topen(caminho.strip()) as f:
                leituras = [S.ler_timeline(f, sq) for sq in S.sequencias(f)]
            for leitura in leituras:
                clps = [s for s in leitura["segments"] if s.get("mob_id") and not s.get("is_gap")
                        and not s.get("is_transition") and not s.get("is_audio")]
                if len(clps) < 6:
                    continue
                fps = leitura["timeline_fps"]
                # "cópia" de três clipes da V1 espalhados: cada um vira um pedaço, deslocado
                # como a do Avid (a cópia começa no primeiro).
                escolha = [clps[1], clps[len(clps) // 2], clps[-2]]
                base = I._tc(escolha[0]["timeline_tc_in"], fps)
                copia_r = {"timeline_fps": fps,
                           "timeline_start_frames": leitura["timeline_start_frames"] + base,
                           "segments": [{**s, "timeline_tc_in": I.frames_to_tc(I._tc(s["timeline_tc_in"], fps) - base, fps),
                                         "timeline_tc_out": I.frames_to_tc(I._tc(s["timeline_tc_out"], fps) - base, fps)}
                                        for s in escolha]}
                sel, avs = I.selecao_da_copia(copia_r, leitura)
                nome = leitura["composition_name"][:26]
                ok(f"{nome}: os 3 pedaços casam", (len(sel), avs), (3, []))
                ins = I.filtrar_insert(leitura, sel)
                ficam = [s for s in ins["segments"] if s.get("mob_id") and not s.get("is_gap")]
                ok(f"{nome}: só 3 clipes no insert", len(ficam), 3)
                # Pode haver aparo no corte de uma transição: o fim/início muda, mas cada clipe
                # continua DENTRO do seu lugar original, na mesma trilha.
                dentro = all(any(e["track"] == s["track"] and e["mob_id"] == s["mob_id"]
                                 and I._tc(e["timeline_tc_in"], fps) <= I._tc(s["timeline_tc_in"], fps)
                                 and I._tc(s["timeline_tc_out"], fps) <= I._tc(e["timeline_tc_out"], fps)
                                 for e in escolha) for s in ficam)
                ok(f"{nome}: cada clipe dentro do seu lugar original", dentro, True)
                segs, casados, metas = S.montar_offline(ins, {}, r"E:\INSERT")
                with tempfile.TemporaryDirectory() as tmp:
                    saida = Path(tmp) / "insert.drt"
                    build_drt(segs, casados, str(saida), timeline_name=f"INSERT PARA VFX — {nome}",
                              timeline_fps=fps, offline=metas)
                    ok(f"{nome}: DRT de insert gerado", saida.is_file() and saida.stat().st_size > 0, True)
                break

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
