"""A MATRIZ do offline no Premiere: cada layout de áudio (e vídeo com N canais) entra offline e religa no canal certo?

Pedido do autor (2026-11-25): "testes com mídias sintéticas gerando diferentes combinações de áudios para testar como
elas chegam quando não existem no HD e precisam entrar offline — inclusive vídeos com mais de 2 canais".

A mídia é a do laboratório (`laboratorio-de-midia`, caso B03 LAYOUTS DE ÁUDIO: 1, 2, 4, 5, 8 e 16 canais; MOV ProRes
com o som polifônico, MOV com um mono por trilha e WAV BWF; um tom por canal). O passo a passo:

    escrever   — Carta de laboratório com os 18 arquivos SEM forma nesta máquina (offline) + uma timeline com um trecho
                 por arquivo (V1 se houver vídeo, A1…AN cada uma no seu canal) → `escrever_timeline` → MATRIZ v01
    premiere   — (Premiere aberto, ponte do laboratório) a REFERÊNCIA: os 18 importados online num projeto à parte;
                 a MATRIZ: aberta, cada item offline religado ao arquivo (`changeMediaPath`), salva como v02
    conferir   — por clipe: online? mesmo lugar (início, fim, entrada, saída)? o canal (mídia `StreamNumber` +
                 `ChannelIndex`) é o MESMO que o Premiere usa para aquele canal no item importado online?

Sai 0 se tudo passou. Rodar com o Python do app: `.venv/bin/python spikes/offline_premiere_matriz.py <passo>`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

FAMILIA = RAIZ.parents[1]
LAB = FAMILIA / "laboratorio-de-midia"
MIDIA = LAB / "saida" / "base" / "B03_LAYOUTS_DE_AUDIO"
SSD = FAMILIA.parent
PASTA = SSD / "MIDIAS DE TESTES" / "9 SAIDAS DOS APPS" / "_CICLO ASSIST" / "2026-11-25 OFFLINE MATRIZ"
CARTA = PASTA / "CARTA"
MOLDE = (SSD / "MIDIAS DE TESTES" / "9 SAIDAS DOS APPS" / "_CICLO ASSIST" / "2026-11-20 CARTA COR MC" / ".carta" / "premiere"
         / "EDITOR SEM MOLDES v06 OFFLINE - PRODA_CORTE.00.2 TRABALHO v02.prproj")
VAZIO = RAIZ / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj"
ESTADO = PASTA / "estado.json"
PASSO_Q, DUR_Q, ENTRADA_Q = 120, 50, 25
#: a variante PARCIAL (`... parcial`): a referência sem o nº de canais (como a do Avid, que só sabe o que a bin diz) e a
#: timeline usando só ALGUNS canais — o offline sai com o maior canal usado, menos canais que o arquivo
PARCIAL = {1: [1], 2: [2], 4: [2, 4], 5: [3], 8: [1, 2], 16: [1, 2, 9, 16]}
NOME = "LAB OFFLINE MATRIZ"


def _variante(rotulo: str) -> None:
    """`parcial`, `parcial2`, `completa2`…: cada rodada na sua Carta e no seu estado (nada é refeito por cima); o
    rótulo que começa por `parcial` é a variante parcial."""
    global CARTA, ESTADO, NOME
    if rotulo:
        CARTA, ESTADO = PASTA / f"CARTA {rotulo.upper()}", PASTA / f"estado-{rotulo}.json"
        NOME = f"LAB OFFLINE MATRIZ {rotulo.upper()}"


def _arquivos() -> list[Path]:
    return sorted(p for p in MIDIA.iterdir() if p.suffix.lower() in (".mov", ".wav") and not p.name.startswith("._"))


def _sonda(arq: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(arq)], capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"]
    return {"video": any(s["codec_type"] == "video" for s in st),
            "pistas": [int(s["channels"]) for s in st if s["codec_type"] == "audio"]}


def _versao(nome: str) -> Path:
    n = 1
    while (PASTA / f"{nome} v{n:02d}.prproj").exists():
        n += 1
    return PASTA / f"{nome} v{n:02d}.prproj"


def escrever(parcial: bool = False) -> dict:
    from cicloassist.carta import entrega_prproj as EP, moldes_prproj as MO, projeto, referencias
    PASTA.mkdir(parents=True, exist_ok=True)
    if (CARTA / ".carta").exists():
        raise SystemExit(f"a Carta de laboratório já existe: {CARTA} (versione a pasta antes de refazer)")
    CARTA.mkdir()
    p = projeto.novo(CARTA, "Offline matriz", "25")
    (CARTA / "D").mkdir()
    trilhas: dict[tuple[str, int], list] = {}
    casos = []
    for i, arq in enumerate(_arquivos()):
        s = _sonda(arq)
        n = sum(s["pistas"])
        ident = {"nome_da_fonte": arq.name, "tipo": "video" if s["video"] else "audio", "fps": "25", "quadros": 250,
                 "tc": "01:00:00:00"}
        if not parcial:
            ident["canais_de_som"] = s["pistas"]
        usados = PARCIAL[n] if parcial else list(range(1, n + 1))
        _, ref = referencias.criar(p, "D", arq.stem, ident, {"nle": "avid", "offline": True})
        ini = i * PASSO_Q
        clipe = {"midia": ref["id"], "inicio_q": ini, "entrada_q": ENTRADA_Q, "fim_q": ini + DUR_Q}
        if s["video"]:
            trilhas.setdefault(("V", 1), []).append(dict(clipe))
        for j, k in enumerate(usados, 1):
            trilhas.setdefault(("A", j), []).append({**clipe, "canal": k})
        casos.append({"arquivo": str(arq), "nome": arq.name, "video": s["video"], "pistas": s["pistas"], "canais": n,
                      "usados": usados, "inicio_q": ini})
    item = {"tipo": "sequencia", "timeline": True, "nome": "MATRIZ OFFLINE", "fps": "25", "tc_inicio_q": 90000,
            "trilhas": [{"tipo": t, "k": k, "transicoes": [], "sem_clipe": [], "clipes": c}
                        for (t, k), c in sorted(trilhas.items(), key=lambda x: (x[0][0] != "V", x[0][1]))]}
    saida = _versao(NOME)
    rel = EP.escrever_timeline(p, item, str(MOLDE), str(saida), MO.NOME_DOS_MOLDES, "MATRIZ OFFLINE", None,
                               quadro=(1920, 1080))
    est = {"matriz": str(saida), "uid": rel["uid"], "casos": casos,
           "escrita": {k: rel[k] for k in ("clipes", "offline", "offline_no_lugar", "fora", "itens_offline")}}
    ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(est["escrita"], ensure_ascii=False, indent=1))
    return est


def _ponte():
    sys.path.insert(0, str(LAB))
    from lab.bancadas import premiere as pr
    pr.esperar_ponte(ate_s=120, vigia=True)      # o vigia morre com ESTE processo
    return pr


def premiere() -> None:
    est = json.loads(ESTADO.read_text(encoding="utf-8"))
    pr = _ponte()
    ref = _versao(NOME + " REF")
    shutil.copyfile(VAZIO, ref)
    arquivos = [c["arquivo"] for c in est["casos"]]
    js_ref = r'''(function(proj, arqs){
        app.openDocument(proj, true, true, true, true);
        var pr=null; for (var i=0;i<app.projects.numProjects;i++) if (app.projects[i].path==proj) pr=app.projects[i];
        if (!pr) return "não abriu";
        pr.importFiles(arqs, true, pr.rootItem, false); pr.save(); return "itens " + pr.rootItem.children.numItems;
    })(%s, %s)''' % (json.dumps(str(ref)), json.dumps(arquivos))
    print("referência:", pr.executar(js_ref, timeout=600))
    v2 = _versao(NOME)
    alvos = {c["nome"]: c["arquivo"] for c in est["casos"]}
    # ⛔ o ExtendScript do Premiere é ES3: sem `JSON` (medido 2026-11-25). Antes e depois saem dos .prproj (v01, v2).
    js = r'''(function(proj, uid, alvos, v2){
        app.openDocument(proj, true, true, true, true);
        var pr=null; for (var i=0;i<app.projects.numProjects;i++) if (app.projects[i].path==proj) pr=app.projects[i];
        if (!pr) return "ERRO não abriu";
        var seq=null; for (var i=0;i<pr.sequences.numSequences;i++) if (pr.sequences[i].sequenceID==uid) seq=pr.sequences[i];
        if (!seq) return "ERRO sem a sequência";
        var feitos=[], vistos={};
        function religar(tracks){ for (var t=0;t<tracks.numTracks;t++){ var tr=tracks[t];
          for (var c=0;c<tr.clips.numItems;c++){ var pi=tr.clips[c].projectItem;
            if (pi && alvos[pi.name]!==undefined && !vistos[pi.nodeId]) { vistos[pi.nodeId]=1;
              var ok; try { ok=pi.changeMediaPath(alvos[pi.name], true); } catch(e) { ok="erro "+e; }
              feitos.push(pi.name+"="+ok); } } } }
        religar(seq.videoTracks); religar(seq.audioTracks);
        pr.saveAs(v2);
        return feitos.join("; ");
    })(%s, %s, %s, %s)''' % (json.dumps(est["matriz"]), json.dumps(est["uid"]), json.dumps(alvos), json.dumps(str(v2)))
    r = pr.executar(js, timeout=900)
    if str(r).startswith("ERRO"):
        raise SystemExit(r)
    est.update({"referencia": str(ref), "religada": str(v2), "religar": r})
    ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    print("religados:", r)


def _canais_do_item(R, por, cpi) -> list[tuple[str, str]]:
    """Os canais de um item, na ordem: [(StreamNumber da mídia, ChannelIndex)], como o Premiere os montou."""
    mc = por[cpi.find(".//MasterClip").get("ObjectURef")]
    out = []
    for c in mc.findall("./Clips/Clip"):
        cl = por[c.get("ObjectRef")]
        if cl.tag != "AudioClip":
            continue
        out += _canais_do_clipe(por, cl)
    return out


def _canais_do_clipe(por, ac) -> list[tuple[str, str]]:
    out = []
    for sci in ac.findall("./SecondaryContents/SecondaryContentItem"):
        sc = por[sci.get("ObjectRef")]
        if sc.find("Content") is None:          # ⛔ canal SEM fonte (ChannelIndex −1): o clipe ficou mudo
            out.append(("SEM FONTE", sc.findtext("ChannelIndex") or ""))
            continue
        src = por[sc.find("Content").get("ObjectRef")]
        med = por[src.find("./MediaSource/Media").get("ObjectURef")]
        out.append((med.findtext("StreamNumber") or "0", sc.findtext("ChannelIndex") or "0"))
    return out


def conferir() -> int:
    from cicloassist.carta import entrega_prproj as EP
    est = json.loads(ESTADO.read_text(encoding="utf-8"))
    tpf = 254016000000 // 25
    # a referência: o canal k de cada arquivo, como o Premiere o importa online
    R = EP._ler_prproj(est["referencia"])
    por = {EP._chave(e): e for e in R if EP._chave(e)}
    ref = {}
    for cpi in R.iter("ClipProjectItem"):
        nome = cpi.findtext("./ProjectItem/Name") or ""
        if cpi.find(".//MasterClip") is not None:
            ref[nome] = _canais_do_item(R, por, cpi)
    # a religada: o canal de cada clipe da sequência
    R2 = EP._ler_prproj(est["religada"])
    por2 = {EP._chave(e): e for e in R2 if EP._chave(e)}
    seq = next(e for e in R2 if e.tag == "Sequence" and e.get("ObjectUID") == est["uid"])
    grupos = {}
    for tg in seq.iter("TrackGroup"):
        s = tg.find("Second")
        if s is not None and s.get("ObjectRef") in por2:
            grupos[por2[s.get("ObjectRef")].tag] = por2[s.get("ObjectRef")]
    def da_sequencia(R2, por2) -> dict:
        """{(trilha, início em quadros): {fim, ent, sai, online, canal}} da sequência da matriz."""
        seq = next(e for e in R2 if e.tag == "Sequence" and e.get("ObjectUID") == est["uid"])
        grupos = {}
        for tg in seq.iter("TrackGroup"):
            s = tg.find("Second")
            if s is not None and s.get("ObjectRef") in por2:
                grupos[por2[s.get("ObjectRef")].tag] = por2[s.get("ObjectRef")]
        out = {}
        for g, rot in (("VideoTrackGroup", "V"), ("AudioTrackGroup", "A")):
            for k, t in enumerate(grupos[g].find("./TrackGroup/Tracks"), 1):
                tis = por2[t.get("ObjectURef")].find("./ClipTrack/ClipItems/TrackItems")
                for x in (list(tis) if tis is not None else []):
                    ti = por2[x.get("ObjectRef")]
                    ini = int(ti.findtext("./ClipTrackItem/TrackItem/Start") or 0) // tpf
                    cl = por2[por2[ti.find("./ClipTrackItem/SubClip").get("ObjectRef")].find("Clip").get("ObjectRef")]
                    med = por2[por2[cl.find("./Clip/Source").get("ObjectRef")].find("./MediaSource/Media").get("ObjectURef")]
                    can = _canais_do_clipe(por2, cl) if rot == "A" else []
                    out[(f"{rot}{k}", ini)] = {"fim": ti.findtext("./ClipTrackItem/TrackItem/End"),
                                               "ent": cl.findtext("./Clip/InPoint"), "sai": cl.findtext("./Clip/OutPoint"),
                                               "online": not med.findtext("OfflineReason"),
                                               "canal": can[0] if len(can) == 1 else tuple(can)}
        return out

    R1 = EP._ler_prproj(est["matriz"])
    antes = da_sequencia(R1, {EP._chave(e): e for e in R1 if EP._chave(e)})
    R2 = EP._ler_prproj(est["religada"])
    depois = da_sequencia(R2, {EP._chave(e): e for e in R2 if EP._chave(e)})
    mesmo_lugar = sum(1 for k, a in antes.items() if k in depois and all(a[x] == depois[k][x] for x in ("fim", "ent", "sai")))
    linhas, falhas = [], 0
    for c in est["casos"]:
        esperado = ref.get(c["nome"]) or []
        usados = c.get("usados") or list(range(1, c["canais"] + 1))
        achados = [depois.get((f"A{j}", c["inicio_q"])) for j in range(1, len(usados) + 1)]
        certos = sum(1 for a, k in zip(achados, usados)
                     if a and k <= len(esperado) and a["canal"] == esperado[k - 1] and a["online"])
        v_ok = None
        if c["video"]:
            v = depois.get(("V1", c["inicio_q"]))
            v_ok = bool(v) and v["online"]
        ok = certos == len(usados) and v_ok in (None, True)
        falhas += not ok
        linhas.append(f"{'ok ' if ok else 'XX '} {c['nome']:<28} pistas {str(c['pistas']):<18} canais certos "
                      f"{certos}/{len(usados)} (usados {usados})" + ("" if v_ok is None else f"  vídeo {'online' if v_ok else 'OFFLINE'}")
                      + ("" if ok else f"\n      esperado {[esperado[k - 1] for k in usados if k <= len(esperado)]}\n      achado   {[a and a['canal'] for a in achados]}"))
    print("\n".join(linhas))
    print(f"\nclipes no mesmo lugar depois de religar: {mesmo_lugar}/{len(antes)}; "
          f"offline antes: {sum(1 for c in antes.values() if not c['online'])}, depois: {sum(1 for c in depois.values() if not c['online'])}")
    print(f"casos: {len(est['casos']) - falhas}/{len(est['casos'])} certos")
    est["conferido"] = linhas
    ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    passo = sys.argv[1] if len(sys.argv) > 1 else ""
    _variante(sys.argv[2] if len(sys.argv) > 2 else "")      # `completa2`, `parcial`, `parcial2`…
    if passo == "escrever":
        escrever(any(a.startswith("parcial") for a in sys.argv[2:]))
    elif passo == "premiere":
        premiere()
    elif passo == "conferir":
        sys.exit(conferir())
    else:
        print(__doc__)
        sys.exit(2)
