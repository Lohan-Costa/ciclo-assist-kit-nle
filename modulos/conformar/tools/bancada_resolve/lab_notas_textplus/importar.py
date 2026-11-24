"""Importa os DRTs de uma pasta no projeto do lab, liga as trilhas e exporta stills nos quadros pedidos.
Uso: python importar.py <pasta drt> <pasta stills> q1,q2,..."""
import os
import sys
import time

from conexao import r

PASTA, STILLS, QS = sys.argv[1], sys.argv[2], [int(q) for q in sys.argv[3].split(",")]
os.makedirs(STILLS, exist_ok=True)
pm = r.GetProjectManager()
p = pm.LoadProject("DLPC LAB TEXTPLUS NOTAS") or pm.GetCurrentProject()
mp = p.GetMediaPool()


def tc(q):
    q += 86400
    return f"{q // 86400:02d}:{q // 1440 % 60:02d}:{q // 24 % 60:02d}:{q % 24:02d}"


for arq in sorted(os.listdir(PASTA)):
    if not arq.endswith(".drt"):
        continue
    t0 = time.time()
    tl = mp.ImportTimelineFromFile(os.path.join(PASTA, arq), {"timelineName": arq[:-4] + time.strftime(" %H%M%S")})
    print(arq, "importou" if tl else "FALHOU", round(time.time() - t0, 1), "s")
    if not tl:
        continue
    p.SetCurrentTimeline(tl)
    n = tl.GetTrackCount("video")
    for t in range(1, n + 1):
        tl.SetTrackEnable("video", t, True)
        itens = tl.GetItemListInTrack("video", t) or []
        print("  V%d" % t, len(itens), [(i.GetName()[:50], i.GetStart(), i.GetDuration()) for i in itens][:8])
    r.OpenPage("color")
    time.sleep(1)
    for q in QS:
        for _ in range(5):
            tl.SetCurrentTimecode(tc(q))
            time.sleep(0.4)
            if tl.GetCurrentTimecode() == tc(q):
                break
        time.sleep(0.8)
        destino = os.path.join(STILLS, f"{arq[:-4]}_{q:04d}.png")
        ok = p.ExportCurrentFrameAsStill(destino)
        print("  still", q, tl.GetCurrentTimecode(), ok)
