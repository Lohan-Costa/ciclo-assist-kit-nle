"""Etapa 1 do handoff (2026-10-13): quanto custa varrer TODAS as bins de um projeto atrás de masters AMA e do
arquivo de origem de cada um. Só lê (topen), nada escreve. Uso: python varrer_projeto.py <pasta do projeto>"""
import os, sys, time
_APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(_APP, "motor"), os.path.join(_APP, "plugins", "media-composer", "servico")]
from avb_export.reader import topen
from avb_export import nle_model as NM
from avb_bin.masters import _atributos
from avb_bin.segmentos import caminho_do_locator

raiz = sys.argv[1]
bins = [os.path.join(d, n) for d, _, ns in os.walk(raiz) for n in ns if n.lower().endswith(".avb")]
t0 = time.time(); total_mb = 0; ama = {}; erros = 0; por_bin = []
for b in bins:
    t = time.time(); total_mb += os.path.getsize(b) / 1e6
    try:
        with topen(b) as f:
            n = 0
            idx = {NM._mobid(x.mob_id): x for x in f.content.mobs}
            for m in f.content.mastermobs():
                at = _atributos(m)
                if at and "_IMPORTED_AMA" in at:
                    cam = next((c for c in (caminho_do_locator(sm) for sm in NM.reachable_sources(m, idx)) if c), "")
                    if cam:
                        ama.setdefault(cam, []).append((os.path.basename(b), str(m.mob_id)))
                        n += 1
    except Exception as e:
        erros += 1; print("ERRO", os.path.basename(b), str(e)[:120])
    por_bin.append((time.time() - t, os.path.getsize(b) / 1e6, os.path.basename(b)))
dt = time.time() - t0
print(f"{len(bins)} bins, {total_mb:.1f} MB em {dt:.2f}s; {len(ama)} arquivos com master AMA "
      f"({sum(len(v) for v in ama.values())} masters); erros {erros}")
for t, mb, n in sorted(por_bin, reverse=True)[:5]:
    print(f"  {t:.2f}s  {mb:.2f} MB  {n}")
