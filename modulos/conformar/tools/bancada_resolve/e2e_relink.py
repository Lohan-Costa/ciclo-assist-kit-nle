"""Ponta a ponta pela API do painel (o mesmo roteiro dos botões): bin de fora → sequência → Ler → Relinkar."""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:7823"
H = {"Origin": BASE, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}


def chamar(metodo, rota, corpo=None, prazo=60):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(BASE + rota, data=dados, headers=H, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=prazo) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{rota}: {e.code} {e.read().decode('utf-8', 'replace')[:300]}") from None


def esperar(prazo_s, rotulo):
    fim = time.time() + prazo_s
    ultimo = ""
    while time.time() < fim:
        e = chamar("GET", "/trabalho")
        txt = f'{e.get("etapa")} {e.get("feito")}/{e.get("total")} {e.get("detalhe") or ""}'
        if txt != ultimo:
            print(f"  [{rotulo}] {txt}", flush=True)
            ultimo = txt
        if not e.get("ocupada"):
            return e
        time.sleep(1)
    raise RuntimeError(f"{rotulo}: passou do prazo de {prazo_s}s")


bin_fora, seq_nome, pasta, nome_bin = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
r = chamar("POST", "/mc/bin/ler", {"caminho": bin_fora})
seq = next(s for s in r["sequencias"] if s["nome"] == seq_nome)
carregada = chamar("POST", "/mc/bin/sequencia", {"caminho": r.get("bin") or bin_fora, "mob_id": seq["mob_id"]})
print("sequência:", carregada.get("nome"), carregada.get("duracao"), carregada.get("trilhas"))
corpo = {"pastas": [pasta], "achatar_subclipes": True, "achatar_group_clips": True,
         "bin_externa": r.get("bin") or bin_fora, "sequence_mob_id": carregada.get("mob_id") or seq["mob_id"],
         "sequence": carregada.get("nome") or seq_nome, "so_importados": False, "so_offline": False}
t = time.time()
chamar("POST", "/trabalho/preparar", dict(corpo, previa=True))
e = esperar(300, "ler")
if e.get("fase") != "pronto":
    raise SystemExit(f"a leitura falhou: {e}")
m = chamar("GET", "/trabalho/masters")["masters"]
from collections import Counter
print("leitura:", round(time.time() - t, 1), "s", Counter(x.get("situacao") or x.get("estado") for x in m))
chamar("POST", "/trabalho/assumir", {})
chamar("POST", "/trabalho/opcoes", {"achatar_subclipes": True})
chamar("POST", "/trabalho/opcoes", {"achatar_group_clips": True})
t = time.time()
chamar("POST", "/trabalho/aplicar", {"nome_bin": nome_bin})
e = esperar(1200, "relink")
print("relink:", round(time.time() - t, 1), "s, fase", e.get("fase"))
res = e.get("resultado") or {}
print(json.dumps({k: v for k, v in res.items() if k != "falhas"}, ensure_ascii=False, indent=1))
for f in res.get("falhas") or []:
    print("FALHA", f)
