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
        # (2026-11-25) a A2 do par juntado continua A2 (B051): vazia se o item é estéreo, com o canal 2 se é um polifônico
        # de vários mono (a ponte põe cada canal na sua trilha) — a referência vai logo abaixo, na A3, nunca em cima dele
        ok("as trilhas de áudio de 1 a n (a referência logo abaixo, depois da A2 do par)", sorted(x["t"] for x in au), [1, 3])
        ok("o som da referência é marcado como referência", [x["ref"] for x in au if x["t"] == 3], [True])
        ok("⭐ o plano de som leva o CANAL do arquivo, e o juntado vai junto (trilha e canal)",
           [(x["c"], x.get("juntos")) for x in au if x["t"] == 1], [(1, [{"t": 2, "c": 2}])])
        # B051: com a A2 vazia, o som da A3 fica na A3 (antes descia para a A2) e a referência vai abaixo dela
        au3 = PM.plano([{**s, "track": 3} if s.get("is_audio") and int(s.get("track") or 0) < 1000 else s for s in segs],
                       casados, 23.976, "CORTE")["planos"]
        ok("B051: a A3 continua A3 com a A2 vazia; a referência logo abaixo (A4)",
           sorted({x["t"] for x in au3 if not x["v"]}), [3, 4])

        # ⛔ (2026-11-25) da BIN do Avid o som vem 1000 + trilha (A1 = 1000): é som, não referência — A1 e A3 (a A2 vazia
        #   fica vazia, B051); antes TUDO virava "referência" e era renumerado em sequência (a vazia sumia)
        bin_ = [{**s, "track": 1000 + (0 if s.get("canal_arquivo") == 1 else 2)}
                if s.get("is_audio") and int(s.get("track") or 0) < 1000 else s for s in segs]
        ab = [x for x in PM.plano(bin_, casados, 23.976, "CORTE")["planos"] if not x["v"]]
        ok("⭐ da bin (1000+): o som volta a ser A1/A3, a vazia fica, a referência logo abaixo",
           sorted((x["t"], x["ref"]) for x in ab), [(1, False), (4, True)])
        ok("…e o canal juntado guarda a trilha dele (A3)", [x.get("juntos") for x in ab if x["t"] == 1], [[{"t": 3, "c": 2}]])

        # B015/B108: o VÍDEO desligado no Avid (Mute Clips → disabled) não entra no Premiere — entrava LIGADO; o SOM
        # desligado entra como clipe desligado, como no Resolve (autor, 2026-10-29)
        # (desligados: o vídeo A e os DOIS mono do par A1/A2)
        pd = PM.plano([dict(s, disabled=True) if i in (0, 2, 3) else s for i, s in enumerate(segs)], casados, 23.976,
                      "CORTE")
        ok("⭐ B015: o vídeo desligado não entra e é contado; o som desligado entra",
           (pd["conta"]["desligados"], pd["conta"]["audio_desligado"], len(pd["planos"]), len(p["planos"])), (1, 1, 3, 4))
        ok("⭐ …o som desligado vai marcado `desligado` (o dlpcMontar faz `c.disabled = true`); o ligado, sem a chave",
           sorted((x["t"], x.get("desligado", False)) for x in pd["planos"] if not x["v"]), [(1, True), (3, False)])
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

        print("\n── 4. o offline NO LUGAR (2026-11-25: com os dados do Avid, o plano entra de um item offline) ──")
        nao = str(Path(tmp) / "nao.mov")
        metas = {nao: {"nb": 14578, "fps": 23.976, "fps_tc": 23.976, "tc": "04:53:47:11", "audio_canais": 2,
                       "reel": "A001_03170454_C013"}}
        po = PM.plano(segs, casados, 23.976, "CORTE", metas=metas)
        ok("⭐ o offline entra como PLANO no lugar (V1, quadro 48, 24 quadros), e não como marcador",
           ([(x["o"], x["v"], x["t"], x["rec"], x["dur"]) for x in po["planos"] if "o" in x],
            [m["nome"] for m in po["marcas"] if m["nome"] == "OFFLINE"]), ([(0, True, 1, 48, 24)], []))
        it = po["offline"][0]
        ok("…o item: o NOME do arquivo, a fita, o TC em ticks (como o diálogo do Premiere grava) e a duração",
           (it["nome"], it["fita"], it["inicio_ticks"], it["dur_ticks"], it["video"]),
           ("nao.mov", "A001_03170454_C013", 4482134112456000, 154447845552000, True))
        aux = PM.escrever_offline(po["offline"], tmp)
        import gzip
        import re
        x = gzip.decompress(Path(aux).read_bytes()).decode("utf-8")
        ok("⭐ o .prproj auxiliar: o cabeçalho do Premiere (FLG 0, OS 0x13) e o item OFFLINE na bin raiz",
           (Path(aux).read_bytes()[:10].hex(), len(re.findall(r"<OfflineReason>5</OfflineReason>", x)),
            "<Title>nao.mov</Title>" in x, len(re.findall(r"<Item Index=", x))),
           ("1f8b0800000000000013", 1, True, 1))
        # ⛔ o som direto de 8 canais: o item offline com os 8 canais MONO (um <Media> por canal), não estéreo — o offline
        #   estéreo religado a um arquivo de mais canais deixa o canal 2 mudo (medido no 26.0.2, a matriz da B03)
        m8 = PM._item_offline(nao, {**metas[nao], "audio_canais": 8})
        x8 = gzip.decompress(Path(PM.escrever_offline([m8], tmp)).read_bytes()).decode("utf-8")
        ok("⭐ o offline de 8 canais: 8 canais mono, cada um na sua mídia (StreamNumber 1…7)",
           (m8["canais"], len(re.findall(r"<OfflineReason>5</OfflineReason>", x8)), len(re.findall(r"<StreamNumber>", x8))),
           (8, 8, 7))
        ids = [int(n) for n in re.findall(r'^\t<\w+ ObjectID="(\d+)"', x, re.M)]   # os de TOPO
        ok("…os ObjectID em ordem crescente, sem repetir (§0.1 do banco)", (ids == sorted(ids), len(ids) == len(set(ids))),
           (True, True))
        sem = PM.plano(segs, casados, 23.976, "CORTE", metas={nao: {"nb": 0}})
        ok("sem a duração do Avid, o marcador de antes (nada inventado)", [m["nome"] for m in sem["marcas"]].count("OFFLINE"), 1)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
