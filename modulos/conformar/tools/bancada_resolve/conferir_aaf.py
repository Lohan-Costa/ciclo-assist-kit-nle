"""Conferência de bancada para a rota do AAF (que ainda não tem a conferência no painel): o quadro do MEIO de cada plano de
vídeo da timeline aberta, exportado pelo próprio Resolve (página Color, ExportCurrentFrameAsStill) × o mesmo quadro do
vídeo de referência (`conferir_conform.comparar_um`). Uso: py conferir_aaf.py <referência> [saída.json]"""
import json
import os
import sys
import time

import bancada_resolve_base as b
from boot import S
from tools.conferir_conform import LIMIAR, comparar_um

ref = sys.argv[1]
saida = sys.argv[2] if len(sys.argv) > 2 else os.path.join(S, "conferir_aaf_out.json")
r = b._b.conectar()
p = r.GetProjectManager().GetCurrentProject()
tl = p.GetCurrentTimeline()
ini = tl.GetStartFrame()
fps = float(p.GetSetting("timelineFrameRate") or 23.976)
nominal = round(fps)


def tc(q):
    q += ini
    return "%02d:%02d:%02d:%02d" % (q // (3600 * nominal), q // (60 * nominal) % 60, q // nominal % 60, q % nominal)


pontos = {}
for t in range(1, tl.GetTrackCount("video") + 1):
    for it in tl.GetItemListInTrack("video", t) or []:
        meio = (it.GetStart() + it.GetEnd()) // 2 - ini
        pontos.setdefault(meio, (t, it.GetName()))
pontos = sorted(pontos.items())
print("timeline:", tl.GetName(), "| pontos:", len(pontos), flush=True)
r.OpenPage("color")
pasta = os.path.join(S, "bancada_out", "cruz")
os.makedirs(pasta, exist_ok=True)
res = []
for i, (q, (trilha, nome)) in enumerate(pontos):
    for _ in range(5):
        tl.SetCurrentTimecode(tc(q))
        time.sleep(0.15)
        if tl.GetCurrentTimecode() == tc(q):
            break
    png = os.path.join(pasta, "q%06d.png" % q)
    ok = p.ExportCurrentFrameAsStill(png)
    item = {"quadro": q, "tc": tc(q), "trilha": trilha, "clipe": nome,
            **(comparar_um(png, ref, q, fps) if ok else {"erro": "não exportou"})}
    res.append(item)
    if i % 10 == 0:
        print(i, item, flush=True)
r.OpenPage("edit")
ruins = [x for x in res if x.get("erro") or x.get("corr", 1) < LIMIAR]
json.dump(res, open(saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("conferem: %d de %d | média %.4f" % (len(res) - len(ruins), len(res),
                                          sum(x.get("corr", 0) for x in res) / max(1, len(res))))
for x in ruins:
    print("  ✗", x)
