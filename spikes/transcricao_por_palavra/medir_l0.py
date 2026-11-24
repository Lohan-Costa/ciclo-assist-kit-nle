"""Mede um resultado (alinhar_l0.py, ou os JSONs dos NLEs) contra o gabarito sintético, com a régua do avaliar.py.
    python medir_l0.py <gabarito.json> <resultado.json> [mais resultados...]"""
import json, re, sys, unicodedata, difflib
import numpy as np
Q = 1001 / 24000
norm = lambda w: re.sub(r"[^\w]", "", unicodedata.normalize("NFC", w.lower()))

def lista(arq):
    d = json.load(open(arq))
    if isinstance(d, dict) and "palavras" in d: return d.get("modelo", arq), [(w["t"], w["fim"], w["palavra"]) for w in d["palavras"]]
    if isinstance(d, dict) and "falas" in d: return "nosso ASR", [(w["t"], w["fim"], w["palavra"]) for f in d["falas"] for w in f["palavras"]]
    if isinstance(d, dict) and "pt" in d: return "premiere 26", [(a, a + du, t) for a, du, t, *_ in d["pt"]]
    raise SystemExit(f"formato desconhecido: {arq}")

def medir(nome, L, gab):
    L = [(norm(t), a, b) for a, b, t in L if norm(t)]
    G = [(norm(g["palavra"]), g["t"], g["fim"], g["frase"]) for g in gab]
    sm = difflib.SequenceMatcher(None, [x[0] for x in L], [x[0] for x in G], autojunk=False)
    P = [(L[b.a + i], G[b.b + i]) for b in sm.get_matching_blocks() for i in range(b.size)]
    di = np.array([a[1] - g[1] for a, g in P]); df = np.array([a[2] - g[2] for a, g in P])
    ult = {}; pri = {}
    for a, g in P: ult[g[3]] = (a, g); pri.setdefault(g[3], (a, g))
    dff = np.array([a[2] - g[2] for a, g in ult.values()]); dif = np.array([a[1] - g[1] for a, g in pri.values()])
    c = np.median(di)
    print(f"{nome:28s} casadas {len(P):2d}/{len(G)} | início ≤1q {np.mean(abs(di)<=Q)*100:3.0f}% "
          f"(med {np.median(di)*1000:+4.0f} ms, sem o desvio {np.mean(abs(di-c)<=Q)*100:3.0f}%, |p90| {np.percentile(abs(di),90)*1000:3.0f}) | "
          f"fim ≤1q {np.mean(abs(df)<=Q)*100:3.0f}% (med {np.median(df)*1000:+4.0f}) | "
          f"fim de frase corta a voz {(dff<-Q).sum()}/{len(dff)} | ataque cortado {(dif>Q).sum()}/{len(dif)}")

if __name__ == "__main__":
  gab = json.load(open(sys.argv[1]))
  for arq in sys.argv[2:]:
    n, L = lista(arq); medir(n + (" " + json.load(open(arq)).get("modo", "") if isinstance(json.load(open(arq)), dict) and "modo" in json.load(open(arq)) else ""), L, gab)
