import json, os, sys, urllib.request
sys.path.insert(0, sys.argv[1]); import fontes
raiz = "/Volumes/SSD/MIDIAS DE TESTES"
tok = open(os.path.expanduser("~/Library/Application Support/Orbita/plugin-token")).read().strip()
lotes, atual = [], []
for d, _, fs in os.walk(raiz):
    cam = [os.path.join(d, f) for f in fs]
    if cam: lotes.append(cam)
iguais = dif = total = 0
for lote in lotes:
    corpo = {"paths": lote}
    req = urllib.request.Request("http://127.0.0.1:7817/sources", json.dumps(corpo).encode(), {"X-Sincronizar-Token": tok, "Content-Type": "application/json"})
    rust = json.loads(urllib.request.urlopen(req, timeout=30).read())
    py = fontes.rota_sources(corpo); total += len(lote)
    if rust == py: iguais += 1
    else:
        dif += 1
        if dif <= 3: print("DIFERENTE:", os.path.dirname(lote[0]), json.dumps(rust)[:300], "|", json.dumps(py)[:300])
print(f"pastas: {len(lotes)} · arquivos: {total} · iguais: {iguais} · diferentes: {dif}")
