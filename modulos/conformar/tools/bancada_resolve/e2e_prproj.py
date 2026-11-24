"""Ponta a ponta do Importar de um .prproj no Resolve pela JANELA DO APP (o gêmeo HTTP da ponte): o roteiro do
painel — abrir o projeto, analisar a sequência com as pastas, preparar o .drt, /resolve/midias, /resolve/importar.
Uso: py e2e_prproj.py <projeto.prproj> <sequência> [--ref <vídeo de referência>] [--aceitar-escalas] <pastas…>"""
import json
import os
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


args = sys.argv[1:]
ref = None
aceitar = "--aceitar-escalas" in args          # o editor que marca "Ajustar todos" na escala de outra mídia
args = [x for x in args if x != "--aceitar-escalas"]
if "--ref" in args:
    i = args.index("--ref")
    ref = args[i + 1]
    del args[i:i + 2]
arquivo, sequencia, pastas = args[0], args[1], args[2:]
print("projeto:", post("/resolve/projeto"), flush=True)
a = post("/receber/abrir", {"caminho": arquivo})
print("abrir:", {k: a.get(k) for k in ("tipo", "arquivo", "nome")},
      [s.get("nome") for s in a.get("sequencias") or []], flush=True)
pedido = {"avulso": a["chave"], "mob_id": sequencia, "notas": os.environ.get("DLPC_NOTAS") == "1", "marcar": True, "colorir": False}
t = time.time()
an = post("/receber/prproj/analisar", dict(pedido, pastas=pastas), prazo=1800)
print("analisar: %.1f s" % (time.time() - t),
      json.dumps({k: v for k, v in an.items() if k not in ("midias", "audio")}, ensure_ascii=False)[:1500], flush=True)
if ref:
    pedido["referencia"] = ref
if aceitar:
    pedido["reescalar"] = {x["caminho"]: x["fator"] for x in an.get("escala_de_outra_midia") or []}
    pedido["proporcao"] = [x["caminho"] for x in an.get("proporcao_de_outra_midia") or []]
    print("escalas aceitas:", len(pedido["reescalar"]), "| proporções aceitas:", len(pedido["proporcao"]), flush=True)
t = time.time()
p = post("/receber/preparar", pedido, prazo=1800)
print("preparar: %.1f s" % (time.time() - t), json.dumps(p, ensure_ascii=False, default=str)[:3000], flush=True)
t = time.time()
m = post("/resolve/midias", {"drt": p["drt"], "nome": p.get("nome")})
print("midias: %.1f s" % (time.time() - t), m, flush=True)
t = time.time()
r = post("/resolve/importar", {"drt": p["drt"], "pasta": p.get("pasta_no_resolve"), "nome": p.get("nome")})
print("importar: %.1f s" % (time.time() - t), r, flush=True)
pos = {}
for etapa, chave, campo in (("fusion", "fusion", "clipes"), ("luts", "luts", "clipes"),
                            ("compostos", "compostos", "grupos")):   # a ordem do painel (`trazerPedido`)
    if r.get("ok") and p.get(chave):
        t = time.time()
        pos[etapa] = post(f"/resolve/{etapa}", {"nome": r["nome"], "uid": r.get("uid", ""), campo: p[chave]},
                          prazo=1800)
        falhas = [x for x in pos[etapa].get(campo) or [] if not x.get("ok")]
        print(f"{etapa}: %.1f s" % (time.time() - t), {k: v for k, v in pos[etapa].items() if k != campo},
              "falhas:", falhas[:10], flush=True)
conf = p.get("conferencia")
if r.get("ok") and conf:
    # a conferência pela referência, o roteiro do `conferir()` do painel: lotes de 6 pontos
    t = time.time()
    ini = post("/conferencia/iniciar", {"id": conf["id"], "do_comeco": True})
    s = post("/resolve/conferirInicio", {"nome": r["nome"], "uid": r.get("uid", ""),
                                         "trilhaReferencia": ini.get("trilha_referencia")})
    print("conferirInicio:", s, "| pontos:", ini.get("total"), flush=True)
    if s.get("ok"):
        try:
            faltam = ini.get("faltam") or []
            for i in range(0, len(faltam), 6):
                lote = faltam[i:i + 6]
                q = post("/resolve/conferirQuadros", {"pontos": lote})
                ruins = [x for x in q.get("quadros") or [] if not x.get("ok")]
                if ruins:
                    print("  quadros que não saíram:", ruins, flush=True)
                post("/conferencia/quadros", {"id": conf["id"], "quadros": [x["quadro"] for x in lote]})
        finally:
            for _ in range(600):
                est = post("/conferencia/estado", {"id": conf["id"]})
                if not est.get("na_fila"):
                    break
                time.sleep(0.5)
            marcas = post("/conferencia/marcas", {"id": conf["id"]})
            fim = post("/resolve/conferirFim", marcas)
        pos["conferencia"] = est
        print("conferencia: %.1f s" % (time.time() - t),
              {k: v for k, v in est.items() if not isinstance(v, (list, dict))}, "| fim:", fim, flush=True)
json.dump({"analisar": an, "preparar": p, "midias": m, "importar": r, **pos},
          open("e2e_prproj_out.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
