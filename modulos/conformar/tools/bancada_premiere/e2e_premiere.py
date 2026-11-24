"""Ponta a ponta de um protocolo MONTADO NO PREMIERE pela ponte (modo Premiere, organograma de 2026-10-19): abrir,
analisar, casar com as pastas, preparar com `destino: premiere` (o plano de montagem) e `/premiere/montar`. Depois lê a
sequência montada pela ponte (planos por trilha) para conferir contra o plano.
Uso: py e2e_premiere.py <arquivo> [--seq <nome>] [--saida <x.json>] <pastas…>   (Premiere aberto com um projeto)"""
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
seq, saida = opcao(args, "--seq"), opcao(args, "--saida")
arquivo, pastas = args[0], args[1:]
saida = saida or os.path.splitext(os.path.basename(arquivo))[0] + "_premiere.json"
print("premiere:", chamar("/premiere/estado", metodo="GET"), flush=True)
a = chamar("/receber/abrir", {"caminho": arquivo})
seqs = a.get("sequencias") or []
mob = ""
if seqs:
    alvo = next((s for s in seqs if s.get("nome") == seq), None) if seq else (seqs[0] if len(seqs) == 1 else None)
    if not alvo:
        raise SystemExit(f"escolha a sequência com --seq: {[s.get('nome') for s in seqs]}")
    mob = alvo["mob_id"]
pedido = {"avulso": a["chave"], "mob_id": mob}
print("abrir:", a.get("tipo"), a.get("arquivo"), flush=True)
an = chamar("/receber/analisar", pedido)
casou = False
if pastas:
    chamar("/receber/originais", dict(pedido, pastas=pastas))
    for _ in range(1200):
        e = chamar("/trabalho", metodo="GET")
        if not e.get("ocupada") and e.get("fase") in ("pronto", "erro", "ocioso"):
            break
        time.sleep(0.5)
    casou = e.get("fase") == "pronto"
    print("casamento:", e.get("fase"), {k: v for k, v in (e.get("trabalho") or {}).items()
                                       if k in ("total", "resolvidos", "nao_resolvidos", "segmentos_resolvidos")}, flush=True)
corpo = dict(pedido, marcar=True, colorir=False, notas=False, destino="premiere", **({"originais": True} if casou else {}))
t = time.time()
p = chamar("/receber/preparar", corpo, prazo=1800)
pl = p.get("premiere") or {}
print("preparar: %.1f s" % (time.time() - t), {"planos": len(pl.get("planos") or []), "midias": len(pl.get("midias") or []),
      "conta": pl.get("conta"), "tpf": pl.get("tpf")}, flush=True)
t = time.time()
r = chamar("/premiere/montar", {"plano": pl}, prazo=1800)
print("montar: %.1f s" % (time.time() - t), r, flush=True)
json.dump({"arquivo": os.path.basename(arquivo), "plano": pl, "montar": r}, open(saida, "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("gravado:", saida)
