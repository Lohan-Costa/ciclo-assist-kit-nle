"""Ponta a ponta do Importar do Resolve pela JANELA DO APP (o gêmeo HTTP da ponte): o mesmo roteiro do
`trazerPedido` do painel — abrir o arquivo, preparar o .drt, /resolve/midias, /resolve/importar e, se o DRT trouxe o
Stabilize do Avid, /resolve/estabilizar (o painel o chama depois da cor, antes dos compounds).

    e2e_resolve.py ARQUIVO [PASTA_DE_ORIGINAIS…]        (DLPC_NOTAS=1: com a trilha de notas; DLPC_MARCAR=1: marcadores e cor local)"""
import os
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:7823"
H = {"Origin": BASE, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}


def post(rota, corpo=None, prazo=600):
    req = urllib.request.Request(BASE + rota, data=json.dumps(corpo or {}).encode(), headers=H, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=prazo) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{rota}: {e.code} {e.read().decode('utf-8', 'replace')[:400]}") from None


arquivo = sys.argv[1]
print("projeto:", post("/resolve/projeto"), flush=True)
a = post("/receber/abrir", {"caminho": arquivo})
print("abrir:", {k: a.get(k) for k in ("tipo", "arquivo", "nome", "duracao", "planos")}, flush=True)
pedido = {"avulso": a["chave"], "notas": os.environ.get("DLPC_NOTAS") == "1", "marcar": os.environ.get("DLPC_MARCAR") == "1", "colorir": os.environ.get("DLPC_MARCAR") == "1"}
if len(sys.argv) > 2:                          # com as pastas: o casamento com os originais ANTES (o painel faz igual)
    post("/receber/originais", dict(pedido, pastas=sys.argv[2:]))
    while True:
        req = urllib.request.Request(BASE + "/trabalho", headers=H)
        e = json.loads(urllib.request.urlopen(req, timeout=30).read())
        if not e.get("ocupada"):
            break
        time.sleep(1)
    print("casamento:", e.get("fase"), {k: e.get(k) for k in ("contagem", "resumo") if e.get(k)}, flush=True)
    pedido["originais"] = True
t = time.time()
p = post("/receber/preparar", pedido)
print("preparar: %.1f s" % (time.time() - t), {k: (v if not isinstance(v, (list, dict)) else len(v))
                                              for k, v in p.items()}, flush=True)
t = time.time()
m = post("/resolve/midias", {"drt": p["drt"], "nome": p.get("nome")})
print("midias: %.1f s" % (time.time() - t), m, flush=True)
t = time.time()
r = post("/resolve/importar", {"drt": p["drt"], "pasta": p.get("pasta_no_resolve"), "nome": p.get("nome")})
print("importar: %.1f s" % (time.time() - t), r, flush=True)
if r.get("ok") and p.get("fusion"):            # as composições do Fusion (máscara, desfoque, Basic 3D), como o painel
    t = time.time()
    fu = post("/resolve/fusion", {"nome": r.get("nome"), "uid": r.get("uid") or "", "clipes": p["fusion"]})
    print("fusion: %.1f s" % (time.time() - t), fu, flush=True)
if r.get("ok") and p.get("cor_mc"):            # o Color Correction do Avid: ANTES das LUTs e da estabilização
    t = time.time()
    c = post("/resolve/cor_mc", {"nome": r.get("nome"), "uid": r.get("uid") or "", "clipes": p["cor_mc"]})
    print("cor_mc: %.1f s" % (time.time() - t), c, flush=True)
if r.get("ok") and p.get("estabilizar"):
    t = time.time()
    e = post("/resolve/estabilizar", {"nome": r.get("nome"), "uid": r.get("uid") or "", "clipes": p["estabilizar"]})
    print("estabilizar: %.1f s" % (time.time() - t), e, flush=True)
print("timelines:", post("/resolve/timelines"), flush=True)
