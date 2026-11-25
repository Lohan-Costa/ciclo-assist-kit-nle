"""O CANAL no Conformar (Avid → Premiere): cada trilha do Avid toca o canal dela, inclusive do polifônico offline?

Antes (até 2026-11-25) o `dlpcMontar` punha o ITEM inteiro na trilha: num polifônico de 3+ canais o `overwriteClip`
espalhava os canais para as trilhas de baixo e a trilha tocava o canal 1; o offline de 3+ canais ia estéreo. Agora cada
canal vai à sua trilha por um subclipe remapeado. Esta prova monta, pela `dlpcMontar` REAL, um plano que imita uma
timeline do Avid com a mídia do laboratório (B03):

    V1 MOV · A1+A2 o de 8 canais OFFLINE (canais 1 e 4, mesmo trecho) · A3 o de 8 canais (canal 8, outro trecho)
    A4+A5 o de 5 canais online (3 e 5) · A6+A7 o estéreo (1 e 2: um clipe estéreo na A6, como antes) · A8 o mono

e religa o offline (o item e os subclipes), salva e confere canal a canal no `.prproj`. Sai 0 se tudo certo.
Premiere aberto, a ponte do laboratório instalada. `.venv/bin/python spikes/conformar_canais_premiere.py`
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FAMILIA = RAIZ.parents[1]
sys.path[:0] = [str(RAIZ), str(RAIZ / "modulos" / "conformar" / "plugins" / "media-composer" / "servico"),
                str(RAIZ / "modulos" / "conformar" / "motor"), str(FAMILIA / "laboratorio-de-midia")]
import premiere_montagem as PM  # noqa: E402

B03 = FAMILIA / "laboratorio-de-midia" / "saida" / "base" / "B03_LAYOUTS_DE_AUDIO"
PASTA = FAMILIA.parent / "MIDIAS DE TESTES" / "9 SAIDAS DOS APPS" / "_CICLO ASSIST" / "2026-11-25 OFFLINE MATRIZ"
JSX = RAIZ / "modulos" / "conformar" / "plugins" / "media-composer" / "servico" / "ui" / "premiere_host.jsx"
VAZIO = RAIZ / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj"
OFF = "B03_8CH_WAV-BWF.wav"


def _versao(nome: str) -> Path:
    n = 1
    while (PASTA / f"{nome} v{n:02d}.prproj").exists():
        n += 1
    return PASTA / f"{nome} v{n:02d}.prproj"


def plano() -> dict:
    off = str(PASTA / "OFFLINE - religar" / OFF)              # o rótulo do Avid: não existe nesta máquina
    seg = lambda **k: {"is_gap": False, "is_transition": False, "is_effect": False, "is_audio": True,  # noqa: E731
                       "source_fps": 25.0, "duration_frames": 50, "source_start_frames": 25,
                       "timeline_tc_in": "00:00:00:00", **k}
    segs = [seg(is_audio=False, track=1, clip_name="V"),
            seg(track=1, canal_arquivo=1), seg(track=2, canal_arquivo=4),
            seg(track=3, canal_arquivo=8, timeline_tc_in="00:00:02:10"),
            seg(track=4, canal_arquivo=3), seg(track=5, canal_arquivo=5),
            seg(track=6, canal_arquivo=1), seg(track=7, canal_arquivo=2),
            seg(track=8, canal_arquivo=1)]
    arq = [str(B03 / "B03_1CH_MOV-PRORES.mov"), off, off, off, str(B03 / "B03_5CH_WAV-BWF.wav"),
           str(B03 / "B03_5CH_WAV-BWF.wav"), str(B03 / "B03_2CH_WAV-BWF.wav"), str(B03 / "B03_2CH_WAV-BWF.wav"),
           str(B03 / "B03_1CH_WAV-BWF.wav")]
    casados = [{"segment_index": i, "matched_path": a, **({"offline": True} if a == off else {})} for i, a in enumerate(arq)]
    metas = {off: {"nb": 250, "fps": 25.0, "fps_tc": 25.0, "tc": "01:00:00:00", "audio_canais": 8, "reel": ""}}
    pl = PM.plano(segs, casados, 25.0, "CANAIS DO AVID", metas=metas)
    (PASTA / "recebidos").mkdir(parents=True, exist_ok=True)
    pl["offline_prproj"] = PM.escrever_offline(pl["offline"], PASTA / "recebidos")
    return pl


def montar(pl: dict) -> dict:
    from lab.bancadas import premiere as pr
    pr.esperar_ponte(ate_s=120, vigia=True)          # o vigia morre com ESTE processo
    v1, v2 = _versao("LAB CONFORMAR CANAIS"), None
    shutil.copyfile(VAZIO, v1)
    v2 = PASTA / v1.name.replace(" v", " RELIGADO v")
    js = r'''(function(proj, jsx, pl, alvo, v2){
        app.openDocument(proj, true, true, true, true);
        var pr=null; for (var i=0;i<app.projects.numProjects;i++) if (app.projects[i].path==proj) pr=app.projects[i];
        if (!pr) return "ERRO não abriu";
        $.evalFile(jsx);
        var r = dlpcMontar(pl);
        // religar o offline: o item e os subclipes dele (o subclipe leva a própria mídia — banco §11o)
        var n=0; function varre(b){ for (var i=0;i<b.children.numItems;i++){ var c=b.children[i];
            if (c.type==2) varre(c); else if (c.name.indexOf(%s)==0 && c.isOffline()) { if (c.changeMediaPath(alvo, true)) n++; } } }
        varre(pr.rootItem);
        pr.saveAs(v2);
        return r + "\n religados " + n;
    })(%s, %s, %s, %s, %s)''' % (json.dumps(OFF), json.dumps(str(v1)), json.dumps(str(JSX)), json.dumps(pl),
                                 json.dumps(str(B03 / OFF)), json.dumps(str(v2)))
    print(pr.executar(js, timeout=900))
    return {"v2": str(v2)}


def conferir(v2: str) -> int:
    from cicloassist.carta import entrega_prproj as EP
    R = EP._ler_prproj(v2)
    por = {EP._chave(e): e for e in R if EP._chave(e)}
    seq = next(e for e in R if e.tag == "Sequence" and e.findtext("Name") == "CANAIS DO AVID")
    tpf = 254016000000 // 25
    achado: dict[str, list] = {}
    for tg in seq.iter("TrackGroup"):
        s = tg.find("Second")
        g = por.get(s.get("ObjectRef")) if s is not None else None
        if g is None or g.tag != "AudioTrackGroup":
            continue
        for k, t in enumerate(g.find("./TrackGroup/Tracks"), 1):
            tis = por[t.get("ObjectURef")].find("./ClipTrack/ClipItems/TrackItems")
            for x in (list(tis) if tis is not None else []):
                ti = por[x.get("ObjectRef")]
                ac = por[por[ti.find("./ClipTrackItem/SubClip").get("ObjectRef")].find("Clip").get("ObjectRef")]
                med = por[por[ac.find("./Clip/Source").get("ObjectRef")].find("./MediaSource/Media").get("ObjectURef")]
                can = []
                for sci in ac.findall("./SecondaryContents/SecondaryContentItem"):
                    sc = por[sci.get("ObjectRef")]
                    m = por[por[sc.find("Content").get("ObjectRef")].find("./MediaSource/Media").get("ObjectURef")] \
                        if sc.find("Content") is not None else None
                    can.append((m.findtext("StreamNumber") or "0") if m is not None else "SEM FONTE")
                arq = Path(med.findtext("FilePath") or med.findtext("Title") or "").name
                ini = int(ti.findtext("./ClipTrackItem/TrackItem/Start") or 0) // tpf
                achado.setdefault(f"A{k}", []).append((arq, ini, can, not med.findtext("OfflineReason")))
        n_a = len(g.find("./TrackGroup/Tracks"))
    esperado = {"A1": [(OFF, 0, ["0"], True)], "A2": [(OFF, 0, ["3"], True)], "A3": [(OFF, 60, ["7"], True)],
                "A4": [("B03_5CH_WAV-BWF.wav", 0, ["2"], True)], "A5": [("B03_5CH_WAV-BWF.wav", 0, ["4"], True)],
                "A6": [("B03_2CH_WAV-BWF.wav", 0, ["0", "0"], True)], "A8": [("B03_1CH_WAV-BWF.wav", 0, ["0"], True)]}
    falhas = 0
    for t in sorted(set(esperado) | set(achado), key=lambda x: int(x[1:])):
        ok = achado.get(t) == esperado.get(t)
        falhas += not ok
        print(f"{'ok ' if ok else 'XX '} {t}: {achado.get(t)}" + ("" if ok else f"   esperado {esperado.get(t)}"))
    print(f"trilhas de som na sequência: {n_a} (esperado 8)")
    falhas += n_a != 8
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 2 and sys.argv[1] == "conferir":
        sys.exit(conferir(sys.argv[2]))
    r = montar(plano())
    sys.exit(conferir(r["v2"]))
