"""Bancada do Resolve Studio por script EXTERNO: as chamadas que a casca (Workflow Integration) faz por dentro,
feitas de fora, cada uma com tempo, retorno e a conferência do efeito. Saída: bancada_resolve.json."""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, r"D:\PROGRAMAS COM CLAUDE\laboratorio-de-midia")
from lab.bancadas import resolve as b

S = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(S, "bancada_out")
os.makedirs(OUT, exist_ok=True)
CHARTS = r"D:\MIDIAS DE TESTES\3 CONJUNTOS DOS APPS\_CICLO ASSIST\conformar\01 MIDIAS\CHARTS"
DRT = r"D:\MIDIAS DE TESTES\3 CONJUNTOS DOS APPS\_CICLO ASSIST\conformar\03 CASOS\EFEITOS\E01 POSICAO 150 E ESCALA 2X\TL-FULLHD_POSICAO-ESCALA.drt"
LUT = r"Blackmagic Design\Blackmagic 4.6K Film to Rec709.cube"
NOME = sys.argv[1] if len(sys.argv) > 1 else "DLPC BANCADA EXTERNO 1"

res = []


def passo(nome, fn):
    t = time.time()
    try:
        r = fn()
        ok = r is not None and r is not False
        res.append({"passo": nome, "ok": ok, "s": round(time.time() - t, 2), "ret": repr(r)[:200]})
    except Exception as e:  # noqa: BLE001
        r = None
        res.append({"passo": nome, "ok": False, "s": round(time.time() - t, 2),
                    "erro": f"{type(e).__name__}: {e}"[:300], "tb": traceback.format_exc()[-400:]})
    print(("OK " if res[-1]["ok"] else "-- ") + nome, res[-1].get("ret", res[-1].get("erro")), flush=True)
    return r


r = b.conectar()
pm = r.GetProjectManager()
p = passo("CreateProject", lambda: pm.CreateProject(NOME))
if not p:
    p = passo("LoadProject (já existia)", lambda: pm.LoadProject(NOME))
passo("projeto corrente = o criado", lambda: (pm.GetCurrentProject().GetName() == NOME) or None)
passo("SetSetting fps 23.976 antes de importar",
      lambda: p.SetSetting("timelineFrameRate", "23.976") or None)
mp = p.GetMediaPool()
raiz = mp.GetRootFolder()
pasta = passo("AddSubFolder", lambda: mp.AddSubFolder(raiz, "DLPC"))
passo("SetCurrentFolder", lambda: mp.SetCurrentFolder(pasta))
arqs = [os.path.join(CHARTS, n) for n in sorted(os.listdir(CHARTS)) if n.lower().endswith((".mov", ".mp4"))]
clips = passo("ImportMedia", lambda: mp.ImportMedia(arqs))
passo("GetClipProperty (Resolution)", lambda: [c.GetClipProperty("Resolution") for c in clips])
passo("SetClipColor", lambda: clips[0].SetClipColor("Orange"))

tl_drt = passo("ImportTimelineFromFile (.drt do E01)", lambda: mp.ImportTimelineFromFile(DRT, {}))
passo("SetName da importada", lambda: tl_drt.SetName("BANC_DRT"))
passo("GetName/GetTrackCount", lambda: (tl_drt.GetName(), tl_drt.GetTrackCount("video"), tl_drt.GetTrackCount("audio")))

tl = passo("CreateTimelineFromClips", lambda: mp.CreateTimelineFromClips("BANC_CLIPS", clips))
passo("SetCurrentTimeline", lambda: p.SetCurrentTimeline(tl))
itens = passo("GetItemListInTrack", lambda: tl.GetItemListInTrack("video", 1))
passo("item: GetStart/GetDuration/GetUniqueId", lambda: [(i.GetStart(), i.GetDuration(), i.GetUniqueId()) for i in itens[:2]])
passo("AddTrack video", lambda: tl.AddTrack("video"))
passo("SetTrackEnable / GetIsTrackEnabled",
      lambda: (tl.SetTrackEnable("video", 2, False), tl.GetIsTrackEnabled("video", 2)))
passo("AddMarker (DLPC)", lambda: tl.AddMarker(10, "Yellow", "DLPC", "conferir", 1, "dlpc-banc"))
passo("DeleteMarkerByCustomData", lambda: tl.DeleteMarkerByCustomData("dlpc-banc"))
passo("RefreshLUTList", lambda: p.RefreshLUTList())
passo("SetLUT no item", lambda: itens[0].SetLUT(1, LUT))
passo("SetCDL no item", lambda: itens[0].SetCDL({"NodeIndex": "1", "Slope": "1.1 1.0 0.9", "Offset": "0 0 0",
                                                  "Power": "1 1 1", "Saturation": "1.2"}))
comp = passo("AddFusionComp", lambda: itens[1].AddFusionComp())
passo("GetFusionCompNameList", lambda: itens[1].GetFusionCompNameList())
arq_comp = os.path.join(OUT, "banc.comp")
passo("ExportFusionComp", lambda: itens[1].ExportFusionComp(arq_comp, 1) and os.path.getsize(arq_comp))
passo("ImportFusionComp (no item 3)", lambda: itens[2].ImportFusionComp(arq_comp))
passo("LoadFusionCompByName", lambda: itens[2].LoadFusionCompByName(itens[2].GetFusionCompNameList()[-1]))
passo("DeleteFusionCompByName", lambda: itens[2].DeleteFusionCompByName(itens[2].GetFusionCompNameList()[-1]))

passo("OpenPage color", lambda: r.OpenPage("color"))
passo("SetCurrentTimecode", lambda: tl.SetCurrentTimecode(tl.GetStartTimecode()))
passo("GetCurrentTimecode", lambda: tl.GetCurrentTimecode())
still = os.path.join(OUT, "banc_still.png")
passo("ExportCurrentFrameAsStill", lambda: p.ExportCurrentFrameAsStill(still) and os.path.getsize(still))
passo("OpenPage edit", lambda: r.OpenPage("edit"))

passo("CreateCompoundClip", lambda: tl.CreateCompoundClip(itens[3:5], {"name": "BANC_COMPOSTO"}))

# Timeline:Export — o conflito do banco: a corrente é BANC_CLIPS; exporta a OUTRA (BANC_DRT) e confere o nome
passo("SetCurrentTimeline BANC_CLIPS (a corrente)", lambda: p.SetCurrentTimeline(tl))
drt_out = os.path.join(OUT, "banc_export.drt")
passo("Export da NÃO-corrente (BANC_DRT)", lambda: tl_drt.Export(drt_out, r.EXPORT_DRT) and os.path.getsize(drt_out))


def nome_no_drt():
    import zipfile
    with zipfile.ZipFile(drt_out) as z:
        txt = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith((".xml", ".txt")))
    return {"tem_BANC_DRT": "BANC_DRT" in txt, "tem_BANC_CLIPS": "BANC_CLIPS" in txt}


passo("o .drt exportado é o pedido?", nome_no_drt)
passo("GetTimelineCount/ByIndex", lambda: [p.GetTimelineByIndex(i + 1).GetName() for i in range(p.GetTimelineCount())])
passo("GetCurrentProject.GetName (o cabeçalho)", lambda: pm.GetCurrentProject().GetName())
passo("SaveProject", lambda: pm.SaveProject())

json.dump({"resolve": r.GetVersionString(), "projeto": NOME, "passos": res},
          open(os.path.join(S, "bancada_resolve.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(sum(x["ok"] for x in res), "de", len(res), "passos ok")
