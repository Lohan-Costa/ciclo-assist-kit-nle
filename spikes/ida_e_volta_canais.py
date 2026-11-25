"""IDA E VOLTA dos canais: Avid → Premiere → Avid (decisão do autor, 2026-11-25: tudo MONO no Avid).

Parte da sequência que a rota Premiere → Avid escreveu (`<bin>_SEQ.avb`, a B03 a 23,976: mono + estéreo na mesma
trilha, uma trilha vazia, estéreo, 5 canais) e:

    premiere <bin_SEQ.avb> [sequência]  — lê a sequência da bin como o Conformar (`segmentos.ler_timeline_de_arquivo` + `montar_midia`), monta no
                Premiere pela `dlpcMontar` REAL (ponte do laboratório) num projeto novo e salva
    trilhas   — imprime as trilhas de som (arquivo e canal) da bin do Avid e da sequência do Premiere

A volta ao Avid é a bancada `modulos/conformar/tools/bancada_avid/e2e_prproj_avid.py` sobre o .prproj salvo.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FAMILIA = RAIZ.parents[1]
SERV = RAIZ / "modulos" / "conformar" / "plugins" / "media-composer" / "servico"
sys.path[:0] = [str(RAIZ), str(SERV), str(RAIZ / "modulos" / "conformar" / "motor"), str(FAMILIA / "laboratorio-de-midia")]

PASTA = FAMILIA.parent / "MIDIAS DE TESTES" / "9 SAIDAS DOS APPS" / "_CICLO ASSIST" / "2026-11-25 PREMIERE AVID CANAIS"
VAZIO = RAIZ / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj"
JSX = SERV / "ui" / "premiere_host.jsx"
SEQ = "CANAIS PARA O AVID"


def _versao(nome: str) -> Path:
    n = 1
    while (PASTA / f"{nome} v{n:02d}.prproj").exists():
        n += 1
    return PASTA / f"{nome} v{n:02d}.prproj"


def trilhas_do_avid(avb: str, seq: str = SEQ) -> dict:
    from avb_bin import segmentos
    r = segmentos.ler_timeline_de_arquivo(avb, nome=seq)
    out: dict = {}
    for s in r["segments"]:
        if s.get("is_audio") and not (s.get("is_gap") or s.get("is_transition")):
            out.setdefault(s["track"], []).append((s.get("timeline_tc_in"), s.get("clip_name"),
                                                   s.get("canal_arquivo") or s.get("source_slot_id")))
    return dict(sorted(out.items()))


def premiere(avb: str, seq: str = SEQ) -> str:
    from avb_bin import segmentos
    import premiere_montagem as PM
    r = segmentos.ler_timeline_de_arquivo(avb, nome=seq)
    arquivos = {k: m["caminho_na_bin"] for k, m in (r.get("masters") or {}).items()
                if m.get("caminho_na_bin") and os.path.isfile(m["caminho_na_bin"])}
    segs, casados, metas = segmentos.montar_midia(r, arquivos, str(PASTA))
    pl = PM.plano(segs, casados, float(r.get("timeline_fps") or 23.976), seq + " VOLTA",
                  inicio=r.get("timeline_start_frames"), metas=metas)
    print("plano:", pl["conta"], "\n midias:", [Path(m).name for m in pl["midias"]])
    from lab.bancadas import premiere as pr
    pr.esperar_ponte(ate_s=120, vigia=True)
    v = _versao("LAB AVID PREMIERE VOLTA")
    shutil.copyfile(VAZIO, v)
    js = r'''(function(proj, jsx, pl){
        app.openDocument(proj, true, true, true, true);
        var p=null; for (var i=0;i<app.projects.numProjects;i++) if (app.projects[i].path==proj) p=app.projects[i];
        if (!p) return "ERRO não abriu";
        $.evalFile(jsx); var r = dlpcMontar(pl); p.save(); return r;
    })(%s, %s, %s)''' % (json.dumps(str(v)), json.dumps(str(JSX)), json.dumps(pl))
    print(pr.executar(js, timeout=900))
    return str(v)


def trilhas_do_premiere(prproj: str, seq: str) -> dict:
    from tools.prproj_para_drt import analisar
    a = analisar(prproj, seq, [])
    out: dict = {}
    for s in a["leitura"]["segmentos"]:
        if s.get("is_audio") and not (s.get("is_gap") or s.get("is_transition")):
            out.setdefault(s["track"], []).append((s.get("timeline_tc_in"), s.get("clip_name"), s.get("canal_arquivo")))
    return dict(sorted(out.items()))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "premiere":
        print(premiere(sys.argv[2], *sys.argv[3:4]))
    elif sys.argv[1] == "avid":
        for t, x in trilhas_do_avid(sys.argv[2], *sys.argv[3:4]).items():
            print(t, x)
    elif sys.argv[1] == "prproj":
        for t, x in trilhas_do_premiere(sys.argv[2], sys.argv[3]).items():
            print(t, x)
