"""Escolhe bordas de PAUSA em que o nosso alinhador e o Premiere 2026 discordam, para o editor julgar de ouvido.
    python bordas_para_ouvir.py <premiere.json> <nosso.json> <chave_saida.json> [n=20] [--semente S]
Sai: a chave (qual marcador é de quem) e as linhas `segundos<TAB>nome<TAB>comentário` para a sincMarcadores.
Os candidatos são CEGOS (A/B sorteados): quem ouve não sabe qual é qual."""
import json, random, sys, difflib
from medir_l0 import lista, norm, Q

ref = [(a, a + d, t) for a, d, t, *_ in json.load(open(sys.argv[1]))["pt"] if norm(t) and d < 5]
R = [(norm(t), a, b, t) for a, b, t in ref]
_, L = lista(sys.argv[2]); L = [(norm(t), a, b, t) for a, b, t in L if norm(t)]
n = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].isdigit() else 20
semente = int(sys.argv[sys.argv.index("--semente") + 1]) if "--semente" in sys.argv else 20261111   # 2ª rodada: outra, para o A/B não repetir
sm = difflib.SequenceMatcher(None, [x[0] for x in L], [x[0] for x in R], autojunk=False)
P = [(L[m.a + i], R[m.b + i], m.b + i) for m in sm.get_matching_blocks() for i in range(m.size)]
cand = []
for a, r, k in P:
    if k + 1 < len(R) and R[k + 1][1] - r[2] >= 0.3 and Q < abs(a[2] - r[2]) < 1.5:
        cand.append(("FIM", r[3], r[2], a[2]))
    if k > 0 and r[1] - R[k - 1][2] >= 0.3 and Q < abs(a[1] - r[1]) < 1.5:
        cand.append(("INÍCIO", r[3], r[1], a[1]))
cand.sort(key=lambda c: c[2])
rnd = random.Random(semente)
fins = [c for c in cand if c[0] == "FIM"]; inis = [c for c in cand if c[0] == "INÍCIO"]
def espalhar(xs, k):
    if len(xs) <= k: return xs
    return [xs[round(i * (len(xs) - 1) / (k - 1))] for i in range(k)]
esc = sorted(espalhar(fins, n * 6 // 10) + espalhar(inis, n - n * 6 // 10), key=lambda c: c[2])
fora = []; ult = -99
for c in esc:
    if min(c[2], c[3]) - ult < 3: continue
    fora.append(c); ult = max(c[2], c[3])
chave = []; linhas = []
for i, (tipo, palavra, tp, tn) in enumerate(fora, 1):
    a_e_premiere = rnd.random() < 0.5
    ta, tb = (tp, tn) if a_e_premiere else (tn, tp)
    pergunta = "onde a voz ACABA?" if tipo == "FIM" else "onde a voz COMEÇA?"
    for letra, t in (("A", ta), ("B", tb)):
        linhas.append(f"{t:.3f}\t{i:02d} {tipo} {letra}\t{palavra!r} — {pergunta} A, B, entre os dois ou nenhum")
    chave.append({"n": i, "tipo": tipo, "palavra": palavra, "premiere_s": tp, "nosso_s": tn,
                  "A": "premiere" if a_e_premiere else "nosso", "dif_ms": round(1000 * (tn - tp))})
json.dump({"bordas": chave, "linhas": linhas}, open(sys.argv[3], "w"), ensure_ascii=False, indent=1)
print(len(cand), "candidatas;", len(chave), "escolhidas")
for c in chave: print(f"{c['n']:02d} {c['tipo']:6s} {c['palavra']:14s} premiere {c['premiere_s']:7.2f}  nosso {c['nosso_s']:7.2f}  ({c['dif_ms']:+5d} ms)")
