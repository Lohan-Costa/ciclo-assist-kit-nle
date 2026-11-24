"""O plano de MONTAGEM no Premiere (modo Premiere, organograma aprovado em 2026-10-19).

Rodar:

    .venv-win/Scripts/python tests/test_premiere_montagem.py

Sem Premiere: os segmentos e o casamento sintéticos viram o plano que a ponte executa.
- tempos em TICKS exatos (23,976: 10.594.584.000 por quadro — o in/out em segundos arredonda no 23.2);
- a entrada no arquivo = `source_start_frames` + a correção do casamento, na taxa da FONTE;
- dois mono do mesmo arquivo no mesmo trecho viram UM plano de áudio (o som não dobra);
- o que não traduz (offline, velocidade, transição, título) vira marcador no lugar — nada some;
- a trilha de áudio N da origem continua N (a vazia entra vazia, B051); a referência, que mora em 1000+ no DRT,
  logo abaixo das outras.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import premiere_montagem as PM  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {obtido!r}"[:150])
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "A.mov", Path(tmp) / "B.wav"
        a.write_bytes(b"x")
        b.write_bytes(b"x")
        seg = lambda **k: {"is_gap": False, "is_transition": False, "is_effect": False, "is_audio": False,
                           "source_fps": 23.976, "track": 1, **k}
        segs = [seg(timeline_tc_in="00:00:00:00", duration_frames=48, source_start_frames=10, clip_name="A"),
                seg(timeline_tc_in="00:00:02:00", duration_frames=24, source_start_frames=0, clip_name="perdido"),
                seg(timeline_tc_in="00:00:00:00", duration_frames=48, source_start_frames=10, is_audio=True, track=1,
                    canal_arquivo=1),
                seg(timeline_tc_in="00:00:00:00", duration_frames=48, source_start_frames=10, is_audio=True, track=2,
                    canal_arquivo=2),
                seg(timeline_tc_in="00:00:01:20", duration_frames=8, is_transition=True, clip_name="Dissolve"),
                seg(timeline_tc_in="00:00:03:00", duration_frames=24, is_effect=True, clip_name="Título", track=2),
                seg(timeline_tc_in="00:00:03:00", duration_frames=24, source_start_frames=0, is_audio=True,
                    track=1000, referencia=True),
                seg(timeline_tc_in="00:00:04:00", duration_frames=24, source_start_frames=5, relative_speed=0.5,
                    clip_name="lento")]
        casados = [{"segment_index": 0, "matched_path": str(a), "source_offset_correction": 2},
                   {"segment_index": 1, "matched_path": str(Path(tmp) / "nao.mov"), "offline": True},
                   {"segment_index": 2, "matched_path": str(a)}, {"segment_index": 3, "matched_path": str(a)},
                   {"segment_index": 6, "matched_path": str(b)},
                   {"segment_index": 7, "matched_path": str(a)}]
        p = PM.plano(segs, casados, 23.976, "CORTE")

        print("── 1. tempos ──")
        ok("23,976: 10.594.584.000 ticks por quadro", p["tpf"], 10594584000)
        ok("25: 10.160.640.000", PM.ticks_por_quadro(25.0), 10160640000)
        ok("sem o início da origem: 01:00:00:00 = 86.400 quadros", p["inicio"], 86400)
        p10 = PM.plano(segs, casados, 23.976, "CORTE", inicio=10 * 3600 * 24)
        ok("B062: o início da ORIGEM (10:00:00:00) vai para o Premiere, os planos no mesmo lugar",
           (p10["inicio"], [x["rec"] for x in p10["planos"]] == [x["rec"] for x in p["planos"]]), (864000, True))
        v = [x for x in p["planos"] if x["v"]]
        ok("a entrada no arquivo: (10 + 2) quadros da fonte, em ticks", v[0]["src"], 12 * 10594584000)
        ok("rec e duração em quadros da timeline", (v[0]["rec"], v[0]["dur"]), (0, 48))

        print("\n── 2. áudio ──")
        au = [x for x in p["planos"] if not x["v"]]
        ok("⭐ os dois mono do mesmo arquivo viram UM plano", p["conta"]["audio_juntado"], 1)
        ok("as trilhas de áudio de 1 a n (a referência logo abaixo)", sorted(x["t"] for x in au), [1, 2])
        ok("o som da referência é marcado como referência", [x["ref"] for x in au if x["t"] == 2], [True])
        # B051: com a A2 vazia, o som da A3 fica na A3 (antes descia para a A2) e a referência vai abaixo dela
        au3 = PM.plano([{**s, "track": 3} if s.get("is_audio") and int(s.get("track") or 0) < 1000 else s for s in segs],
                       casados, 23.976, "CORTE")["planos"]
        ok("B051: a A3 continua A3 com a A2 vazia; a referência logo abaixo (A4)",
           sorted({x["t"] for x in au3 if not x["v"]}), [3, 4])

        # B015/B108: o VÍDEO desligado no Avid (Mute Clips → disabled) não entra no Premiere — entrava LIGADO; o SOM
        # desligado entra como clipe desligado, como no Resolve (autor, 2026-10-29)
        # (desligados: o vídeo A e os DOIS mono do par A1/A2)
        pd = PM.plano([dict(s, disabled=True) if i in (0, 2, 3) else s for i, s in enumerate(segs)], casados, 23.976,
                      "CORTE")
        ok("⭐ B015: o vídeo desligado não entra e é contado; o som desligado entra",
           (pd["conta"]["desligados"], pd["conta"]["audio_desligado"], len(pd["planos"]), len(p["planos"])), (1, 1, 3, 4))
        ok("⭐ …o som desligado vai marcado `desligado` (o dlpcMontar faz `c.disabled = true`); o ligado, sem a chave",
           sorted((x["t"], x.get("desligado", False)) for x in pd["planos"] if not x["v"]), [(1, True), (2, False)])
        par = [i for i, s in enumerate(segs) if s.get("is_audio") and int(s.get("track") or 0) == 1]
        pj = PM.plano([dict(s, disabled=True) if i == par[0] else s for i, s in enumerate(segs)], casados, 23.976, "CORTE")
        ok("…o par mono juntado com UM lado desligado entra LIGADO (o outro canal toca)",
           (pj["conta"]["audio_juntado"], pj["conta"]["audio_desligado"],
            [x.get("desligado", False) for x in pj["planos"] if not x["v"] and x["t"] == 1]), (1, 0, [False]))

        print("\n── 3. o que não traduz vira marcador ──")
        nomes = sorted(m["nome"] for m in p["marcas"])
        ok("offline, transição, título e velocidade", nomes, ["OFFLINE", "Transição", "Título / gerador", "Velocidade"])
        ok("o offline NÃO entra como plano", any(x["rec"] == 48 and x["v"] for x in p["planos"]), False)
        ok("o lento entra a 100 % (e marcado)", any(x["rec"] == 96 for x in v), True)
        ok("as mídias uma vez cada", len(p["midias"]), 2)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
