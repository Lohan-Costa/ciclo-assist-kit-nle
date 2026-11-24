# A borda que o ASR não mediu

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⛔⛔ A borda que o ASR não mediu

**MEDIDO em 2026-09-12: 169 de 715 bordas do cache (23,6%) são exatamente `0,000 s`.** Fala
humana não faz isso um quarto das vezes — é o faster-whisper encadeando segmentos, e a
borda é artefato dele.

Acreditar nelas custava caro: `min(fim + RESPIRO, proxima - VAO_MINIMO)` dava número menor
que `fim`, o `max(..., fim)` colava o corte, e **176 de 727 falas (24%) ficavam com respiro
ZERO** — entre elas todas as "Sobe comigo." que o editor viu virar "sobe co…" em campo,
**em dois pareceres seguidos**. Não era calibragem: `RESPIRO_DEPOIS_S = 0,40` já cobria o
pior caso medido (310 ms). Era o vizinho zerando o respiro.

⇒ `VAO_NAO_MEDIDO_S` separa borda medida de borda encadeada. Depois: **0,8%**.
