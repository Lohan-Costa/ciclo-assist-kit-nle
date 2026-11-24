"""O .prproj → o plano do Avid (`avb_export/do_prproj.py`; organograma do autor, 2026-10-25).

Rodar:

    .venv/bin/python tests/test_do_prproj.py        (Windows: .venv-win/Scripts/python)

Uma análise FALSA (o formato de `tools.prproj_para_drt.analisar`) com arquivos de verdade num temporário:
- o plano achado vira master pela CHAVE = o caminho desta máquina; o áudio leva o canal do arquivo e o quanto a
  timeline pede; o som achado noutra pasta (`sons.realocado`) também conta;
- o não achado é `offline:<o que o projeto declara>` — nunca vazio;
- o achado que não virou master (link recusado, áudio sem molde) passa a offline (`sem_master`);
- o offline pede um master com a folga de transição nos dois lados (`specs_offline`).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_export import do_prproj as D  # noqa: E402

casos, falhas = 0, []


def ok(rotulo: str, obtido, esperado) -> None:
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def seg(ref, audio=False, ini=0, dur=10, **kw):
    s = {"media_ref": {"local_path": ref} if ref else None, "is_audio": audio, "is_gap": False,
         "is_transition": False, "is_effect": False, "disabled": False, "source_start_frames": ini,
         "duration_frames": dur, "clip_name": ref, "mob_id": None, "track": 1000 if audio else 1}
    s.update(kw)
    return s


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_do_prproj_"))
    cam, som = tmp / "A001.mp4", tmp / "musica" / "SOM.WAV"
    som.parent.mkdir()
    cam.write_bytes(b"x")
    som.write_bytes(b"x")
    analise = {
        "leitura": {"fps": 23.976, "segmentos": [
            seg("Z:\\M\\A001.mp4", ini=100, dur=20),
            seg("Z:\\M\\SOM.WAV", audio=True, ini=50, dur=30, canal_arquivo=2),
            seg("Z:\\M\\SOM.WAV", audio=True, ini=200, dur=40, canal_arquivo=1),
            seg("Z:\\M\\SUMIU.mov", ini=10, dur=24),
            seg(None, is_gap=True),
            seg(None, is_transition=True, dur=8, cutpoint=4),
        ]},
        "casamento": {"Z:\\M\\A001.mp4": {"estado": "original", "original": str(cam)},
                      "Z:\\M\\SUMIU.mov": {"estado": "nao_encontrado", "original": None}},
        "sons": {"Z:\\M\\SOM.WAV": {"realocado": str(som)}},
    }
    plano = D.planejar(analise)
    segs = plano["segmentos"]
    ok("vídeo achado: a chave é o arquivo desta máquina", (segs[0]["mob_id"], segs[0]["clip_name"]),
       (str(cam), "A001.mp4"))
    ok("som achado noutra pasta (realocado) também vira master", segs[1]["mob_id"], str(som))
    ok("áudio leva o CANAL do arquivo", (segs[1]["source_slot_id"], segs[2]["source_slot_id"]), (2, 1))
    ok("áudio: o quanto a timeline pede = o maior fim", plano["audio"], {str(som): 240})
    ok("vídeo pedido", plano["video"], {str(cam): "A001.mp4"})
    ok("⭐ não achado = offline com o caminho declarado (nunca vazio)", (segs[3]["mob_id"], segs[3]["clip_name"]),
       ("offline:Z:\\M\\SUMIU.mov", "SUMIU.mov"))
    ok("…e entra nos ausentes com o nome do arquivo", plano["ausentes"], {"offline:Z:\\M\\SUMIU.mov": "SUMIU.mov"})
    ok("vazio e transição ficam como estão", (segs[4]["mob_id"], segs[5]["mob_id"]), (None, None))
    ok("a análise original não é tocada", analise["leitura"]["segmentos"][0]["mob_id"], None)
    analise["leitura"]["segmentos"][1]["volume_db"] = 6.0
    g = [e for e in D.planejar(analise)["segmentos"][1]["effects"] if e["name"] == "Audio Gain"]
    ok("⭐ o volume fixo do Premiere entra no plano como o Audio Gain que o escritor embrulha",
       [e["params"]["level_num"] for e in g], [round((1 << 29) * 10 ** (6 / 20))])
    ok("…e o escritor o lê", __import__("avb_export.translate", fromlist=["_"])._gain_level(
        D.planejar(analise)["segmentos"][1]), round((1 << 29) * 10 ** (6 / 20)))

    n = D.sem_master(plano, [str(som)])
    ok("⭐ achado sem master (áudio sem molde) passa a offline", (n, segs[1]["mob_id"], segs[2]["mob_id"]),
       (2, "offline:Z:\\M\\SOM.WAV", "offline:Z:\\M\\SOM.WAV"))
    ok("…e sai do pedido de áudio", plano["audio"], {})

    specs, handle = D.specs_offline(plano)
    ok("a folga é a da maior transição", handle > 0, True)
    ok("um master offline por arquivo ausente", sorted(specs), ["offline:Z:\\M\\SOM.WAV", "offline:Z:\\M\\SUMIU.mov"])
    ok("o offline do vídeo: nome, tipo e duração com a folga nos dois lados",
       (specs["offline:Z:\\M\\SUMIU.mov"]["name"], specs["offline:Z:\\M\\SUMIU.mov"]["kind"],
        specs["offline:Z:\\M\\SUMIU.mov"]["master_len"]), ("SUMIU.mov", "video", 34 + 2 * handle))
    ok("o offline do áudio", (specs["offline:Z:\\M\\SOM.WAV"]["kind"], specs["offline:Z:\\M\\SOM.WAV"]["master_len"]),
       ("audio", 240 + 2 * handle))
    ok("o vídeo achado NÃO vira offline", str(cam) in specs, False)

    # ⭐ a transição do Premiere (os planos ENCOSTAM no corte) → a sobreposição do Avid (A3 Samba do PRODC, 18/10:
    # clipes 24:09–26:10 e 26:10–31:12, transição 26:06–26:14 com cutpoint 4; a 24 q/s nominais)
    def c(tc, dur, ini, **kw):
        return {"track": 1003, "timeline_tc_in": tc, "duration_frames": dur, "source_start_frames": ini,
                "mob_id": "x.wav", "is_audio": True, "source_fps": 23.976, **kw}
    a_, t_, b_ = c("00:00:24:09", 49, 100), {"track": 1003, "timeline_tc_in": "00:00:26:06", "duration_frames": 8,
                                                "cutpoint": 4, "is_transition": True}, c("00:00:26:10", 122, 500)
    trilha = [a_, t_, b_]
    ok("⭐ transição do Premiere vira sobreposição", D.sobrepor_transicoes(trilha, 23.976), 1)
    ok("a cauda do A cresce dur − cutpoint", (a_["duration_frames"], a_["source_start_frames"]), (53, 100))
    ok("a cabeça do B recua cutpoint (timeline e fonte)",
       (b_["timeline_tc_in"], b_["source_start_frames"], b_["duration_frames"]), ("00:00:26:06", 496, 126))
    ok("…o fim do B não muda", (26 * 24 + 6) + 126, (26 * 24 + 10) + 122)
    ok("já sobrepostos: não mexe de novo", D.sobrepor_transicoes(trilha, 23.976), 0)
    a_, t_, b_ = c("00:00:24:09", 49, 100, has_motion_effect=True), dict(t_, timeline_tc_in="00:00:26:06"), \
        c("00:00:26:10", 122, 500)
    D.sobrepor_transicoes([a_, t_, b_], 23.976)
    ok("o lado com velocidade fica como está; o outro lado muda", (a_["duration_frames"], b_["source_start_frames"]),
       (49, 496))
    a_, b_ = c("00:00:24:09", 49, 100), c("00:00:26:10", 122, 2)
    D.sobrepor_transicoes([a_, t_, b_], 23.976)
    ok("B sem mídia antes do início (fonte < cutpoint): só o lado do A muda",
       (a_["duration_frames"], b_["timeline_tc_in"], b_["source_start_frames"]), (53, "00:00:26:10", 2))
    # fade de entrada "termina no corte" (PRODC A3: transição 17:21–20:00, cutpoint = dur 51, o plano começa em 20:00)
    g_ = {"track": 1003, "timeline_tc_in": "00:00:17:08", "duration_frames": 64, "is_gap": True}
    t_ = {"track": 1003, "timeline_tc_in": "00:00:17:21", "duration_frames": 51, "cutpoint": 51, "is_transition": True}
    b_ = c("00:00:20:00", 105, 300)
    ok("fade de entrada: a cabeça recua para baixo do fade", (D.sobrepor_transicoes([g_, t_, b_], 23.976),
       b_["timeline_tc_in"], b_["source_start_frames"]), (1, "00:00:17:21", 249))
    # fade de saída no FIM da trilha: um vazio depois, senão o escritor descarta a transição
    a_ = c("00:01:02:08", 46, 0)
    t_ = {"track": 1003, "timeline_tc_in": "00:01:03:16", "duration_frames": 24, "cutpoint": 24, "is_transition": True}
    trilha = [a_, t_]
    D.sobrepor_transicoes(trilha, 23.976)
    ok("fade de saída no fim da trilha ganha o vazio depois", [x.get("is_gap") for x in trilha], [None, None, True])

    # ── as decisões da lista de mídias do relink (rota `prproj` do MC) ─────────────────────────────────────────
    outro = tmp / "A001_OUTRA.mp4"
    outro.write_bytes(b"x")
    plano = D.planejar(analise)
    n = D.redirecionar(plano, {str(cam): str(outro), "offline:Z:\\M\\SUMIU.mov": str(cam), str(som): None})
    sg = plano["segmentos"]
    ok("⭐ o relink manual troca o arquivo do plano", (sg[0]["mob_id"], sg[0]["clip_name"]), (str(outro), "A001_OUTRA.mp4"))
    ok("o não achado que o editor apontou deixa de ser offline", sg[3]["mob_id"], str(cam))
    ok("o ignorado (None) entra offline no lugar", (sg[1]["mob_id"], sg[2]["mob_id"]),
       ("offline:Z:\\M\\SOM.WAV", "offline:Z:\\M\\SOM.WAV"))
    ok("…e os pedidos são refeitos", (sorted(plano["video"]), plano["audio"], sorted(plano["ausentes"])),
       (sorted([str(outro), str(cam)]), {}, ["offline:Z:\\M\\SOM.WAV"]))
    ok("quantos planos mudaram", n, 4)

    # ── B009: o que o Premiere tem e o .avb não leva é CONTADO (o `reproducible` do leitor fala do Resolve) ─────
    def fx(nome, cat="other", **p):
        return {"name": nome, "category": cat, "reproducible": True, "params": p}
    planos = {"segmentos": [
        {"effects": [fx("Motion", "geometric", scale_x=1.2, crop_frac={"l": 0.1}, composite="screen")]},
        {"effects": [fx("Motion", "geometric", scale_x=1.2), fx("Lumetri", "lut"),
                     fx("Máscara de opacidade (Fusion)", "fusion", mascaras=[{"invertida": False}])]},
        {"effects": [fx("Gaussian Blur (Fusion)", "fusion"), fx("Máscara de opacidade (Fusion)", "fusion",
                                                                 mascaras=[{"invertida": True}])]},
        {"effects": [fx("Lumetri", "lut")], "disabled": True},                   # desligado não existe (B108)
        {"effects": [fx("Texto", "title")]},
        {"is_audio": True, "effects": [], "volume_db": -6.0},
        {"is_audio": True, "effects": [], "volume_db": 0.0, "volume_kf": [(0, -3.0), (10, 0.0)]},
        {"is_audio": True, "effects": [], "volume_db": 0.0},
        {"is_transition": True, "effects": [fx("Cross Dissolve")]},
        {"is_audio": True, "effects": [], "volume_db": 15.0},
    ]}
    ok("⭐ efeitos fora do Avid: contados por nome, o desligado e o traduzido de fora",
       D.efeitos_fora_do_avid(planos),
       {"Crop": 1, "Luma Key": 1, "Lumetri": 1, "Gaussian Blur (Fusion)": 1,
        "máscara de opacidade invertida": 1, "Volume do clipe acima de +12 dB (vai a +12)": 1})
    U = 1 << 29
    ok("⭐ os keyframes de volume viram automação do Avid: offset desde o início do clipe, level na escala do ganho",
       D.automacao_de_volume({"volume_kf": [(30, -3.0), (40, 0.0), (55, 20.0)]}),
       [(0, round(U * 10 ** (-3 / 20))), (10, U), (25, round(U * 10 ** (12 / 20)))])
    ok("…um ponto só (ou nenhum) não é automação", (D.automacao_de_volume({"volume_kf": [(3, -6.0)]}),
                                                   D.automacao_de_volume({})), ([], []))
    ok("⭐ acima de +12 dB vai +12: o level é int32 (2^31 = +12,04 dB; +15 estourava a bin)",
       D.ganho_de_clipe(planos["segmentos"][9])["params"]["level_num"], round((1 << 29) * 10 ** (12 / 20)))
    ok("…e cabe no int32", D.ganho_de_clipe(planos["segmentos"][9])["params"]["level_num"] < 2 ** 31, True)
    ok("o volume FIXO vai como ganho de clipe (2^29 × 10^(dB/20)); 0 dB e keyframes não", [
        (D.ganho_de_clipe(s) or {}).get("params") for s in planos["segmentos"][5:8]],
       [{"level_num": round((1 << 29) * 10 ** (-6 / 20))}, None, None])
    ok("nada fora → vazio (a tela não diz nada)", D.efeitos_fora_do_avid({"segmentos": [
        {"effects": [fx("Motion", "geometric", scale_x=2.0)]}, {"is_audio": True, "volume_db": 0.0}]}), {})

    # ── A escala de outra mídia COMO NO RESOLVE (autor, 2026-10-29): o aceito × fator; todo suspeito com marcador ────
    def mo(ref, track=1, tc="00:00:01:00", **kw):
        return {"media_ref": {"local_path": ref}, "track": track, "timeline_tc_in": tc,
                "effects": [{"name": "Motion", "params": {"scale_x": 0.5, "scale_y": 0.5}}], **kw}
    pl = {"fps": 24.0, "segmentos": [mo("A.mov", 2), mo("B.mov"), mo("C.mov"), mo("A.mov", disabled=True),
                                     mo("A.mov", is_audio=True)]}
    original = pl["segmentos"][0]["effects"]
    marcas = D.ajustar_escalas(pl, {"escalas": {"A.mov": {"fator": 2.0, "planos": 1}, "B.mov": {"fator": 3.75,
                                                                                             "planos": 1}}},
                               {"A.mov": 2.0, "C.mov": 9.0})
    ok("⭐ o aceito sai × fator; o suspeito não aceito e o fora da oferta ficam como o projeto diz",
       [s["effects"][0]["params"]["scale_x"] for s in pl["segmentos"][:3]], [1.0, 0.5, 0.5])
    ok("…a análise não é tocada (o efeito do plano é cópia)", original[0]["params"]["scale_x"], 0.5)
    ok("⭐ um marcador por suspeito ligado de vídeo, na trilha e no quadro dele",
       [(m["quadro"], m["trilha"], "ajustada" in m["nota"]) for m in marcas], [(24, 2, True), (24, 1, False)])
    ok("…o sugerido aparece na nota do não aceito", "x 3.75" in marcas[1]["nota"], True)

    # ── B109: escala digitada para outra mídia e proporção de outro arquivo → a CONTA (no Avid nada é ajustado)
    def v(ref, **kw):
        return {"media_ref": {"local_path": ref}, **kw}
    ok("⭐ planos de outra mídia contados (vídeo ligado só)", D.de_outra_midia(
        {"segmentos": [v("A.mov"), v("A.mov"), v("B.mov"), v("A.mov", disabled=True), v("A.mov", is_audio=True),
                       v("C.mov")]},
        {"escalas": {"A.mov": {"fator": 2.0, "planos": 3}}, "proporcoes": {"B.mov": {}}}),
       {"escala": 2, "proporcao": 1})

    sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
    import prproj_avid as PA

    ms, ids = PA.masters_do_prproj(analise)
    por = {ids[m.mob_id]: m for m in ms}
    ok("⭐ um master por arquivo, o MobID sintético de 32 hex", sorted(len(m.mob_id) for m in ms), [32, 32, 32])
    ok("o achado entra com o caminho conhecido (o degrau 'caminho' do casamento)",
       getattr(por[str(cam)], "caminho_conhecido", None), str(cam))
    ok("o não achado vai sem caminho, procurado pelo nome", (getattr(por["offline:Z:\\M\\SUMIU.mov"],
       "caminho_conhecido", None), por["offline:Z:\\M\\SUMIU.mov"].nome), (None, "SUMIU"))
    ok("o som: e_audio, 2 planos, o uso máximo", (por[str(som)].e_audio, por[str(som)].segmentos,
       por[str(som)].uso_frames), (True, 2, 240))
    ok("o MobID sintético é estável (a lista e o aplicar falam do mesmo)", PA.id_da_chave(str(cam)),
       PA.id_da_chave(str(cam)))

    for p in (cam, som, outro):
        os.remove(p)
    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
