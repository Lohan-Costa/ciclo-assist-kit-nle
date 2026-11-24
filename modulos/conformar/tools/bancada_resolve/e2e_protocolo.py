"""Ponta a ponta de QUALQUER protocolo no Resolve pela janela do app (organograma de 2026-10-19: um fluxo para todo
protocolo): o roteiro do painel — abrir, escolher a sequência, analisar (o resumo), casar com as pastas, a lista de
mídias, preparar com o vídeo de referência, pré-importar, importar, conferir. Grava um resumo COMPARÁVEL entre
protocolos do mesmo corte (`<saída>.json`).
Uso: py e2e_protocolo.py <arquivo> [--seq <nome>] [--ref <vídeo>] [--saida <x.json>] <pastas…>"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:7823"
H = {"Origin": BASE, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}


def chamar(rota, corpo=None, prazo=600, metodo="POST"):
    dados = json.dumps(corpo or {}).encode() if metodo == "POST" else None
    req = urllib.request.Request(BASE + rota, data=dados, headers=H, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=prazo) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{rota}: {e.code} {e.read().decode('utf-8', 'replace')[:400]}") from None


def opcao(args, nome):
    if nome in args:
        i = args.index(nome)
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return None


args = sys.argv[1:]
seq, ref, saida = opcao(args, "--seq"), opcao(args, "--ref"), opcao(args, "--saida")
arquivo, pastas = args[0], args[1:]
saida = saida or os.path.splitext(os.path.basename(arquivo))[0] + "_e2e.json"
res = {"arquivo": os.path.basename(arquivo), "pastas": pastas, "ref": os.path.basename(ref) if ref else None}
print("projeto:", chamar("/resolve/projeto"), flush=True)
a = chamar("/receber/abrir", {"caminho": arquivo})
tipo = a.get("tipo")
seqs = a.get("sequencias") or []
mob = ""
if seqs:
    alvo = next((s for s in seqs if s.get("nome") == seq), None) if seq else (seqs[0] if len(seqs) == 1 else None)
    if not alvo:
        raise SystemExit(f"escolha a sequência com --seq: {[s.get('nome') for s in seqs]}")
    mob = alvo["mob_id"]
print("abrir:", tipo, a.get("arquivo"), a.get("nome") or seq, flush=True)
res["tipo"] = tipo
pedido = {"avulso": a["chave"], "mob_id": mob}
t = time.time()
if tipo == "prproj":
    an = chamar("/receber/prproj/analisar", dict(pedido, pastas=pastas), prazo=1800)
    lista = [{"nome": m["nome"], "situacao": m["estado"], "encontrado": os.path.basename(m.get("arquivo") or "")}
             for m in an.get("midias") or []]
    casou = bool(pastas)
else:
    an = chamar("/receber/analisar", pedido)
    lista, casou = [], False
    if pastas:
        chamar("/receber/originais", dict(pedido, pastas=pastas))
        for _ in range(1200):
            e = chamar("/trabalho", metodo="GET")
            if not e.get("ocupada") and e.get("fase") in ("pronto", "erro", "ocioso"):
                break
            time.sleep(0.5)
        if e.get("fase") != "pronto":
            raise SystemExit(f"o casamento não terminou: {e.get('fase')} {e.get('erro')}")
        casou = True
        an["placar"] = {k: v for k, v in (e.get("trabalho") or {}).items() if not isinstance(v, (list, dict))}
        for m in chamar("/trabalho/masters", metodo="GET").get("masters") or []:
            s = ("ign" if m.get("ignorado") else "manual" if m.get("metodo") == "manual"
                 else "encontrada" if m.get("arquivo") and not m.get("precisa_de_revisao")
                 else "a conferir" if (m.get("arquivo") or m.get("sugestao") or m.get("candidatos")) else "sem mídia")
            lista.append({"nome": m["nome"], "situacao": s, "som": bool(m.get("e_audio")),
                          "encontrado": os.path.basename(m.get("arquivo") or m.get("sugestao") or "")})
print("analisar: %.1f s" % (time.time() - t), json.dumps({k: v for k, v in an.items() if k != "midias"},
                                                       ensure_ascii=False)[:1200], flush=True)
print("lista:", json.dumps(lista, ensure_ascii=False)[:1500], flush=True)
res.update(resumo={k: an.get(k) for k in ("planos", "efeitos", "sem_traducao", "audio", "conferencia", "placar")},
           lista=sorted(lista, key=lambda x: x["nome"]))
corpo = dict(pedido, marcar=True, colorir=False, notas=False, som_referencia="A")
if ref:
    corpo["referencia"] = ref
if casou and tipo != "prproj":
    corpo["originais"] = True
t = time.time()
p = chamar("/receber/preparar", corpo, prazo=1800)
print("preparar: %.1f s" % (time.time() - t), {k: v for k, v in p.items() if k in
      ("clipes", "offline", "midias", "nos_originais", "referencia", "trilha_referencia", "avisos")}, flush=True)
m = chamar("/resolve/midias", {"drt": p["drt"], "nome": p.get("nome")})
r = chamar("/resolve/importar", {"drt": p["drt"], "pasta": p.get("pasta_no_resolve"), "nome": p.get("nome")})
print("midias:", m, "| importar:", r, flush=True)
res["preparar"] = {k: p.get(k) for k in ("nome", "clipes", "offline", "midias", "nos_originais", "referencia",
                                         "trilha_referencia")}
res["importar"] = {"ok": r.get("ok"), "nome": r.get("nome"), "erro": r.get("erro")}
for etapa, chave, campo in (("fusion", "fusion", "clipes"), ("luts", "luts", "clipes"),
                            ("compostos", "compostos", "grupos")):   # a ordem do painel (`trazerPedido`)
    if r.get("ok") and p.get(chave):
        x = chamar(f"/resolve/{etapa}", {"nome": r["nome"], "uid": r.get("uid", ""), campo: p[chave]}, prazo=1800)
        res[etapa] = {k: v for k, v in x.items() if k != campo}
        print(f"{etapa}:", res[etapa], "falhas:", [y for y in x.get(campo) or [] if not y.get("ok")][:5], flush=True)
conf = p.get("conferencia")
if r.get("ok") and conf:
    t = time.time()
    ini = chamar("/conferencia/iniciar", {"id": conf["id"], "do_comeco": True})
    s = chamar("/resolve/conferirInicio", {"nome": r["nome"], "uid": r.get("uid", ""),
                                           "trilhaReferencia": ini.get("trilha_referencia")})
    est, fim = {}, {}
    if s.get("ok"):
        try:
            faltam = ini.get("faltam") or []
            for i in range(0, len(faltam), 6):
                lote = faltam[i:i + 6]
                chamar("/resolve/conferirQuadros", {"pontos": lote})
                chamar("/conferencia/quadros", {"id": conf["id"], "quadros": [x["quadro"] for x in lote]})
        finally:
            for _ in range(600):
                est = chamar("/conferencia/estado", {"id": conf["id"]})
                if not est.get("na_fila"):
                    break
                time.sleep(0.5)
            fim = chamar("/resolve/conferirFim", chamar("/conferencia/marcas", {"id": conf["id"]}))
    res["conferencia"] = {k: v for k, v in est.items() if not isinstance(v, (list, dict))}
    print("conferencia: %.1f s" % (time.time() - t), res["conferencia"], "| fim:", fim, flush=True)
elif ref:
    res["conferencia"] = {"erro": "o preparar não devolveu o plano da conferência"}
    print("⚠ sem plano da conferência", flush=True)
json.dump(res, open(saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("resumo:", saida, flush=True)
