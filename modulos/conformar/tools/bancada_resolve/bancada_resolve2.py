"""Bancada 2: Export da timeline NÃO-corrente, reimportação do .drt do 19.1.4, DeleteFusionCompByName fora da comp
carregada. Continua o projeto da bancada 1."""
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bancada_resolve_base as B  # noqa: E402

r, pm, p, mp, passo, res = B.abrir("DLPC BANCADA EXTERNO 1")
tl_a = p.GetTimelineByIndex(1)                                   # BANC_CLIPS
clips = mp.GetCurrentFolder().GetClipList()
tl_b = passo("CreateTimelineFromClips (BANC_B)", lambda: mp.CreateTimelineFromClips("BANC_B", clips[:2]))
passo("corrente = BANC_CLIPS", lambda: p.SetCurrentTimeline(tl_a))
passo("corrente confirmada", lambda: p.GetCurrentTimeline().GetName())
out = os.path.join(B.OUT, "banc_B.drt")
if os.path.exists(out):
    os.remove(out)
passo("Export da NÃO-corrente (BANC_B)", lambda: tl_b.Export(out, r.EXPORT_DRT) and os.path.getsize(out))


def conteudo():
    with zipfile.ZipFile(out) as z:
        txt = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist())
    return {"cita_BANC_B": "BANC_B" in txt, "cita_BANC_CLIPS": "BANC_CLIPS" in txt,
            "clipes": sum(txt.count(n.GetName()) > 0 for n in clips)}


passo("o .drt é a BANC_B?", conteudo)
tl_c = passo("ImportTimelineFromFile do .drt do 19.1.4", lambda: mp.ImportTimelineFromFile(out, {}))
passo("SetName", lambda: tl_c.SetName("BANC_REIMPORT"))
passo("itens da reimportada", lambda: len(tl_c.GetItemListInTrack("video", 1)))
passo("SetCurrentTimeline volta a BANC_CLIPS", lambda: p.SetCurrentTimeline(tl_a))
item = tl_a.GetItemListInTrack("video", 1)[0]
passo("AddFusionComp x2", lambda: (item.AddFusionComp(), item.AddFusionComp(), item.GetFusionCompNameList()))
passo("LoadFusionCompByName (a 1ª)", lambda: item.LoadFusionCompByName(item.GetFusionCompNameList()[0]))
passo("DeleteFusionCompByName (a ÚLTIMA, não carregada)",
      lambda: item.DeleteFusionCompByName(item.GetFusionCompNameList()[-1]))
passo("lista depois", lambda: item.GetFusionCompNameList())
passo("SaveProject", lambda: pm.SaveProject())
B.gravar("bancada_resolve2.json", r, res)
