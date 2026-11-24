"""Ponta a ponta da cópia PREMIERE → PREMIERE pela rota do painel (analisar → preparar com destino premiere →
/premiere/copia) e, com --ref, a conferência pela referência (as rotas /premiere/conferir*), como o e2e_prproj do Resolve.
Uso: py e2e_copia.py <projeto.prproj> <sequência> [--ref <vídeo de referência>] <pastas…>   (Premiere aberto com um projeto)
As ofertas de escala e proporção vão aceitas (o editor que marca "Ajustar todos"). Medido 2026-10-29: R04 2023 → 14/143."""
import json, sys, time, urllib.request, urllib.error
sys.stdout.reconfigure(encoding="utf-8")
BASE="http://127.0.0.1:7823"; H={"Origin":BASE,"Sec-Fetch-Site":"same-origin","Content-Type":"application/json"}
def post(rota, corpo=None, prazo=900):
    r=urllib.request.Request(BASE+rota,data=json.dumps(corpo or {}).encode(),headers=H,method="POST")
    try:
        return json.loads(urllib.request.urlopen(r,timeout=prazo).read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{rota}: {e.code} {e.read().decode('utf-8','replace')[:400]}") from None
args=sys.argv[1:]; ref=None
if "--ref" in args:
    i=args.index("--ref"); ref=args[i+1]; del args[i:i+2]
arquivo, sequencia, pastas = args[0], args[1], args[2:]
a=post("/receber/abrir",{"caminho":arquivo}); print("abrir:", a.get("tipo"), a.get("arquivo"))
pedido={"avulso":a["chave"],"mob_id":sequencia,"marcar":True,"colorir":False,"notas":False}
an=post("/receber/prproj/analisar",dict(pedido,pastas=pastas),prazo=1800)
print("analisar:", {k:an.get(k) for k in ("planos","no_original","arquivos","faltam")})
pedido["reescalar"]={x["caminho"]:x["fator"] for x in an.get("escala_de_outra_midia") or []}
pedido["proporcao"]=[x["caminho"] for x in an.get("proporcao_de_outra_midia") or []]
print("escalas aceitas:", len(pedido["reescalar"]), "| proporções:", len(pedido["proporcao"]))
if ref: pedido["referencia"]=ref
p=post("/receber/preparar",dict(pedido,destino="premiere"),prazo=1800)
print("preparar:", json.dumps({k:v for k,v in p.items() if k!="midias"},ensure_ascii=False,default=str)[:800])
t=time.time(); r=post("/premiere/copia",{"id":p["premiere_copia"]["id"]},prazo=1800)
print("copia: %.1f s"%(time.time()-t), json.dumps(r,ensure_ascii=False)[:1500])

conf=p.get("conferencia")
if r.get("ok") and conf:
    t=time.time()
    ini=post("/conferencia/iniciar",{"id":conf["id"],"do_comeco":True})
    s=post("/premiere/conferirInicio",{"uid":r["id"],"trilhaReferencia":ini.get("trilha_referencia")})
    print("conferirInicio:",s,"| pontos:",ini.get("total"),flush=True)
    if s.get("ok"):
        try:
            faltam=ini.get("faltam") or []
            for i in range(0,len(faltam),6):
                lote=faltam[i:i+6]
                q=post("/premiere/conferirQuadros",{"pontos":lote})
                ruins=[x for x in q.get("quadros") or [] if not x.get("ok")]
                if ruins: print("  quadros que não saíram:",ruins[:3],flush=True)
                post("/conferencia/quadros",{"id":conf["id"],"quadros":[x["quadro"] for x in lote]})
        finally:
            for _ in range(600):
                est=post("/conferencia/estado",{"id":conf["id"]})
                if not est.get("na_fila"): break
                time.sleep(0.5)
            marcas=post("/conferencia/marcas",{"id":conf["id"]})
            fim=post("/premiere/conferirFim",marcas)
        print("conferencia: %.1f s"%(time.time()-t),{k:v for k,v in est.items() if not isinstance(v,(list,dict))},"| fim:",fim)
        ruins=[x for x in est.get("pontos") or est.get("resultados") or [] if isinstance(x,dict) and x.get("confere") is False]
        print("não conferem:", json.dumps(ruins[:20],ensure_ascii=False)[:2500])
