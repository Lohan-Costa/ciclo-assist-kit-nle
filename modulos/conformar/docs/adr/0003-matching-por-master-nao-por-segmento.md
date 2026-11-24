# 0003 — Matching por MASTER, não por segmento

**Status:** ativa · Data: 2026-08-10

**Contexto:** a timeline de um AAF real aponta para dezenas de segmentos por master —
num caso medido, ~1172 segmentos contra ~119 masters únicos. Casar cada segmento
individualmente multiplicaria decisões sem necessidade: um master aparece em vários
pontos da timeline, e cada aparição é a mesma pergunta ("este master é este arquivo no
disco?") feita de novo.

**Decisão:** o matcher opera sobre a lista de masters únicos do AAF, não sobre os
segmentos da timeline. Casar um master resolve todos os seus segmentos de uma vez.

**Por quê:** não é só custo computacional — é qualidade de decisão. Um master com vários
segmentos espalhados pela timeline dá **várias amostras no vídeo de referência para
confirmar uma única decisão**: mais evidência por decisão, menos decisões, menos chance
de erro humano na revisão.

**Consequência:** a estrutura de percurso do AAF (`aaf/percurso.py`, ver
[ADR 0006](0006-achatar-subclipes-antes-do-importfile.md)) existe justamente para ir do
`SourceClip` da timeline até o `MasterMob` de forma confiável — é o passo que a decisão
de "casar por master" depende para não confundir o master com o subclipe sincronizado
que o `SourceClip` costuma referenciar de fato.
