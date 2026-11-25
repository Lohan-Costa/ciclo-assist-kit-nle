"""Avid → Premiere com os MOV de PARES estéreo OFFLINE (receita `B03_PARES_2398` do laboratório): monta pela `dlpcMontar`
real um plano que imita o Avid (V1 + A1–A4 o MOV de 2 pares; A5–A9 o MOV de 2 pares + 1 mono, só som), religa o item
e os subclipes ao MOV e lê os canais pelo leitor do Conformar, antes e depois.

Medido no 26.0.2 Mac (2026-11-25): o offline "N Mono" religa CERTO a um arquivo de trilhas internas IGUAIS (2 pares,
3 pares: 1…N) e ERRADO a um de trilhas DESIGUAIS (2 pares + 1 mono: 1, 3, 5 e dois mudos) — o Premiere religa o canal k
na trilha interna k. Pelo Avid não se sabe o arranjo do arquivo ausente: limite registrado no banco
(`prproj/escrita.md` §11o). Premiere aberto, a ponte do laboratório instalada.
`.venv/bin/python spikes/offline_pares_premiere.py`
"""
import json, shutil, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FAM = RAIZ.parents[1]
SERV = RAIZ / "modulos/conformar/plugins/media-composer/servico"
sys.path[:0] = [str(RAIZ), str(SERV), str(RAIZ / "modulos/conformar/motor"), str(FAM / "laboratorio-de-midia")]
import premiere_montagem as PM  # noqa: E402

B = FAM / "laboratorio-de-midia/saida/base/B03_PARES_2398"
PASTA = FAM.parent / "MIDIAS DE TESTES/9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-25 PREMIERE AVID CANAIS"
JSX = SERV / "ui/premiere_host.jsx"
VAZIO = RAIZ / "modulos/conformar/motor/prproj/moldes/vazio 26.0.2.prproj"
F = 24000 / 1001


def versao(nome):
    n = 1
    while (PASTA / f"{nome} v{n:02d}.prproj").exists():
        n += 1
    return PASTA / f"{nome} v{n:02d}.prproj"


off4 = str(PASTA / "OFFLINE - religar" / "B03_4CH_MOV-PRORES-PARES.mov")
off5 = str(PASTA / "OFFLINE - religar" / "B03_5CH_MOV-PRORES-PARES.mov")
seg = lambda **k: {"is_gap": False, "is_transition": False, "is_effect": False, "is_audio": True, "source_fps": F,  # noqa
                   "duration_frames": 48, "source_start_frames": 24, "timeline_tc_in": "00:00:00:00", **k}
segs = [seg(is_audio=False, track=1, clip_name="V")] + [seg(track=k, canal_arquivo=k) for k in range(1, 5)] + \
       [seg(track=4 + k, canal_arquivo=k, timeline_tc_in="00:00:02:00") for k in range(1, 6)]
arqs = [off4] * 5 + [off5] * 5
casados = [{"segment_index": i, "matched_path": a, "offline": True} for i, a in enumerate(arqs)]
metas = {off4: {"nb": 240, "fps": F, "fps_tc": F, "tc": "01:00:00:00", "audio_canais": 4, "reel": ""},
         off5: {"nb": 240, "fps": F, "fps_tc": F, "tc": "01:00:00:00", "audio_canais": 5, "reel": ""}}
pl = PM.plano(segs, casados, F, "PARES OFFLINE", metas=metas)
(PASTA / "recebidos").mkdir(parents=True, exist_ok=True)
pl["offline_prproj"] = PM.escrever_offline(pl["offline"], PASTA / "recebidos")
print("plano", pl["conta"])

from lab.bancadas import premiere as pr  # noqa: E402
pr.esperar_ponte(ate_s=120, vigia=True)
v1 = versao("LAB PARES OFFLINE")
shutil.copyfile(VAZIO, v1)
v2 = PASTA / v1.name.replace(" v", " RELIGADO v")
js = r'''(function(proj, jsx, pl, pasta, v2){
    app.openDocument(proj, true, true, true, true);
    var p=null; for (var i=0;i<app.projects.numProjects;i++) if (app.projects[i].path==proj) p=app.projects[i];
    if (!p) return "ERRO nao abriu";
    $.evalFile(jsx);
    var r = dlpcMontar(pl);
    p.save();
    var n=0, nomes=["B03_4CH_MOV-PRORES-PARES.mov","B03_5CH_MOV-PRORES-PARES.mov"];
    function varre(b){ for (var i=0;i<b.children.numItems;i++){ var c=b.children[i];
        if (c.type==2) varre(c); else for (var j=0;j<nomes.length;j++) if (c.name.indexOf(nomes[j])==0 && c.isOffline()) { if (c.changeMediaPath(pasta+"/"+nomes[j], true)) n++; } } }
    varre(p.rootItem);
    p.saveAs(v2);
    return r + "\n religados " + n;
})(%s, %s, %s, %s, %s)''' % (json.dumps(str(v1)), json.dumps(str(JSX)), json.dumps(pl), json.dumps(str(B)), json.dumps(str(v2)))
print(pr.executar(js, timeout=900))

from tools.prproj_para_drt import analisar  # noqa: E402
for nome, arq in (("ANTES (offline)", v1), ("RELIGADO", v2)):
    tr = {}
    try:
        for s in analisar(str(arq), "PARES OFFLINE", [])["leitura"]["segmentos"]:
            if s.get("is_audio") and not (s.get("is_gap") or s.get("is_transition")):
                tr.setdefault(s["track"], []).append((s["timeline_tc_in"], s["clip_name"], s.get("canal_arquivo")))
    except Exception as e:  # noqa: BLE001
        tr = {"erro": str(e)}
    print(nome, arq.name)
    for t, x in sorted(tr.items(), key=lambda kv: str(kv[0])):
        print("  ", t, x)
