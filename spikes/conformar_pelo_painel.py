"""Uso: .venv/bin/python spikes/conformar_pelo_painel.py <bin_SEQ.avb> <sequência>  (serviço do Conformar 7823 e núcleo no ar; monta no projeto ABERTO do Premiere).
O caminho do PAINEL do Conformar, pelas mesmas rotas e cabeçalho (Sec-Fetch-Site: same-origin):
/receber/abrir {caminho} → /receber/preparar {avulso, mob_id, destino: premiere} → /premiere/montar {plano}."""
import json, sys, urllib.request
def post(rota, corpo, prazo=1800):
    r = urllib.request.Request("http://127.0.0.1:7823" + rota, json.dumps(corpo).encode(),
                               {"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin", "Origin": "http://127.0.0.1:7823"})
    try:
        return json.loads(urllib.request.urlopen(r, timeout=prazo).read())
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, "corpo": e.read()[:500].decode("utf-8", "replace")}
bin_, seq = sys.argv[1], sys.argv[2]
a = post("/receber/abrir", {"caminho": bin_})
print("abrir:", {k: (v if not isinstance(v, (list, dict)) else str(v)[:300]) for k, v in a.items()})
seqs = a.get("sequencias") or a.get("timelines") or []
mob = next((s.get("mob_id") for s in seqs if s.get("nome") == seq or s.get("name") == seq), None)
print("mob:", mob)
p = post("/receber/preparar", {"avulso": a.get("chave"), "mob_id": mob, "destino": "premiere"})
print("preparar:", json.dumps({k: p.get(k) for k in ("nome", "clipes", "offline", "erro", "HTTP", "corpo")}, ensure_ascii=False),
      "carta_id:", (p.get("premiere") or {}).get("carta_id"))
m = post("/premiere/montar", {"plano": p.get("premiere")})
print("montar:", json.dumps(m, ensure_ascii=False)[:1500])
