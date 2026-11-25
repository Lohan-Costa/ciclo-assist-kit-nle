"""Os CANAIS na rota Premiere → Avid e na ida e volta (autor, 2026-11-25: "tudo mono no Avid").

Rodar:

    .venv/bin/python tests/test_canais_ida_e_volta.py        (Windows: .venv-win/Scripts/python)

Dois `.prproj` reais do Premiere 26.0.2 (`04 SINTETICOS/CANAIS IDA E VOLTA/`, LEIA-ME lá), lidos pelo leitor do Conformar
(`prproj.leitura` via `tools.prproj_para_drt.analisar`) — a trilha do Avid (1000 = A1) e o canal do arquivo de cada clipe:
- o estéreo do Premiere vira DOIS mono (L e R) em trilhas vizinhas; o mono na mesma trilha fica na 1ª;
- o WAV de 5 canais ("N Mono": uma mídia por canal) lê os canais 1…5 (antes, todos o 1 — o `StreamNumber` era ignorado);
- a VOLTA (o Avid montado no Premiere, com o R do par numa trilha vazia) dá as MESMAS trilhas da ida: a vazia logo
  abaixo de um estéreo é o lugar do R (antes: +1 trilha vazia por estéreo);
- o MOV de PARES estéreo (`B03_PARES_2398`): o fluxo começa na soma dos canais dos anteriores (`AudioChannelLayout`), o
  canal mudo não vira trilha, e a volta (o par num clipe estéreo pelo subclipe remapeado) dá as trilhas da ida.
Medido no MC 25.12 Mac: ida e volta idênticas na bin (`spikes/ida_e_volta_canais.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor"), str(Path(__file__).parent)]

import casos  # noqa: E402

falhas = 0


def ok(nome, veio, esperado):
    global falhas
    bom = veio == esperado
    falhas += not bom
    print(f"  {'ok' if bom else '✗ '}   {nome}" + ("" if bom else f": veio {veio}, esperava {esperado}"))


def trilhas(prproj: Path, seq: str) -> dict:
    from tools.prproj_para_drt import analisar
    out: dict = {}
    for s in analisar(str(prproj), seq, [])["leitura"]["segmentos"]:
        if s.get("is_audio") and not (s.get("is_gap") or s.get("is_transition")):
            out.setdefault(s["track"], []).append((s.get("timeline_tc_in"), s.get("clip_name"), s.get("canal_arquivo")))
    return dict(sorted(out.items()))


M, E, C = "B03_1CH_WAV-BWF.wav", "B03_2CH_WAV-BWF.wav", "B03_5CH_WAV-BWF.wav"
P4, P5 = "B03_4CH_MOV-PRORES-PARES.mov", "B03_5CH_MOV-PRORES-PARES.mov"
#: a sequência do Avid (ida): A1 mono + L, A2 R, A3 vazia, A4/A5 o estéreo, A6–A10 os 5 canais
AVID = {1000: [("00:00:00:00", M, 1), ("00:00:03:00", E, 1)], 1001: [("00:00:03:00", E, 2)],
        1003: [("00:00:00:00", E, 1)], 1004: [("00:00:00:00", E, 2)],
        **{1004 + k: [("00:00:00:00", C, k)] for k in range(1, 6)}}


def main() -> int:
    base = casos.amostras()
    pasta = base / "04 SINTETICOS" / "CANAIS IDA E VOLTA" if base else None
    if not pasta or not pasta.is_dir():
        print(f"PULADO — sem a pasta de amostras ({pasta or casos.raiz_das_amostras()})")
        return 0
    print("── a VOLTA (o Avid montado no Premiere) dá as trilhas da ida ──")
    ok("trilhas e canais iguais aos do Avid", trilhas(pasta / "VOLTA DO AVID.prproj", "CANAIS PARA O AVID VOLTA"), AVID)
    print("\n── o projeto NATIVO do Premiere ──")
    t = trilhas(pasta / "PREMIERE NATIVO.prproj", "CANAIS PARA O AVID")
    ok("A1 misturada: o mono e o L na 1ª, o R na 2ª", (t.get(1000), t.get(1001)),
       ([("00:00:00:00", M, 1), ("00:00:03:00", E, 1)], [("00:00:03:00", E, 2)]))
    ok("⭐ os 5 canais do WAV lêem 1…5 (o StreamNumber de cada mídia)",
       [x[0][2] for k, x in t.items() if x[0][1] == C], [1, 2, 3, 4, 5])
    ok("a A2 vazia logo abaixo do estéreo é o lugar do R (não ganha trilha)", sorted(t), list(range(1000, 1009)))
    print("\n── MOV com MAIS DE UMA trilha estéreo dentro (B03_PARES) ──")
    t = trilhas(pasta / "PREMIERE PARES.prproj", "PARES PARA O AVID")
    ok("⭐ o 2º par é o canal 3-4 (o fluxo começa na SOMA dos anteriores; antes, 1, 2, 2, 3)",
       [x[0][2] for k, x in t.items() if x[0][1] == P4], [1, 2, 3, 4])
    ok("⭐ 2 pares + 1 mono: 1…5, e o lado MUDO do mono não vira trilha (antes, 6 trilhas)",
       [x[0][2] for k, x in t.items() if x[0][1] == P5], [1, 2, 3, 4, 5])
    ok("a volta do Avid (cada par num clipe estéreo, o mono com o 2º lado mudo) dá as trilhas da ida",
       trilhas(pasta / "VOLTA PARES DO AVID.prproj", "PARES PARA O AVID VOLTA"), t)
    print(f"\n{'TUDO CERTO' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
