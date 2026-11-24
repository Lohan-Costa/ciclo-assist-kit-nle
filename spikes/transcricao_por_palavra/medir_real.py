"""Fala HUMANA: concordância de cada variante com o Premiere 2026 (a referência combinada com o autor) no mesmo take.
    python medir_real.py <premiere.json> <resultado.json> [mais...]
Casamento pelo texto (difflib). "Borda de pausa" = fim de palavra seguido de >= 0,3 s sem fala no Premiere,
ou início precedido disso: é onde o corte cai."""
import json, re, sys, unicodedata, difflib
import numpy as np
from medir_l0 import lista, norm, Q

ref = [(a, a + d, t) for a, d, t, *_ in json.load(open(sys.argv[1]))["pt"] if norm(t) and d < 5]
R = [(norm(t), a, b) for a, b, t in ref]
for arq in sys.argv[2:]:
    nome, L = lista(arq); L = [(norm(t), a, b) for a, b, t in L if norm(t)]
    sm = difflib.SequenceMatcher(None, [x[0] for x in L], [x[0] for x in R], autojunk=False)
    P = [(L[m.a + i], R[m.b + i], m.b + i) for m in sm.get_matching_blocks() for i in range(m.size)]
    di = np.array([a[1] - r[1] for a, r, _ in P]); df = np.array([a[2] - r[2] for a, r, _ in P])
    pf = np.array([(k + 1 == len(R)) or (R[k + 1][1] - R[k][2] >= 0.3) for *_, k in P])
    pi = np.array([(k == 0) or (R[k][1] - R[k - 1][2] >= 0.3) for *_, k in P])
    c = np.median(di)
    print(f"{nome:26s} casadas {len(P)}/{len(R)} | início ≤1q {np.mean(abs(di)<=Q)*100:3.0f}% (med {np.median(di)*1000:+4.0f}, sem desvio {np.mean(abs(di-c)<=Q)*100:3.0f}%) "
          f"| fim ≤1q {np.mean(abs(df)<=Q)*100:3.0f}% (med {np.median(df)*1000:+4.0f}) "
          f"| PAUSA: fim ≤1q {np.mean(abs(df[pf])<=Q)*100:3.0f}% antes do Premiere >1q {np.mean(df[pf]<-Q)*100:3.0f}% depois {np.mean(df[pf]>Q)*100:3.0f}% (n={pf.sum()}) "
          f"· início ≤1q {np.mean(abs(di[pi])<=Q)*100:3.0f}% depois do Premiere >1q {np.mean(di[pi]>Q)*100:3.0f}% (n={pi.sum()})")
