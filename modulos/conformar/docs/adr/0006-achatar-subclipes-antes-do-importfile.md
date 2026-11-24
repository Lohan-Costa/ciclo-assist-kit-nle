# 0006 — Achatar subclipes e group clips antes do `ImportFile`

**Status:** ativa · Data: 2026-08-10

**Contexto:** ao importar um AAF cujos subclipes já existem no projeto, o Media Composer
abre um diálogo modal de conflito ("Sub clip conflict found…") que **trava a API
gRPC inteira** enquanto espera clique humano. O conflito não é exceção — é o caso comum:
o fluxo do plugin é justamente reimportar (relinkar, revisar, corrigir, aplicar de novo),
e da segunda aplicação em diante o diálogo aparece sempre.

**Decisão:** achatar a timeline — remover subclipes e group clips, entregando os clipes
originais direto na timeline — antes do `ImportFile`. Sem subclipes no AAF, não há o que
conflitar, e o diálogo não tem por que aparecer. Duas opções independentes, ligadas por
padrão (`achatar_subclipes`, `achatar_group_clips`), que o editor desmarca se quiser
preservar a estrutura.

**Medido:** 738 repontamentos, 44 subclipes removidos, zero restantes, timeline
idêntica na saída (1172 segmentos, mesma fps). O ciclo completo (`LinkFile` → achatar →
remapear → `ImportFile`) rodou sem diálogo nenhum; o import caiu de 4,1 s para 1,9 s.

## Decisão menor: o percurso da timeline é um módulo só (`aaf/percurso.py`)

Achatar expôs que **o percurso da timeline foi escrito três vezes**, e cada cópia
esqueceu um ramo diferente da estrutura recursiva — sempre sem erro, só um número menor
do que devia, num relatório que dizia "concluído":

| módulo | ramo esquecido | sintoma |
|---|---|---|
| `masters.py` | `NestedScope` (`.slots`) | zero SourceClips na trilha de imagem |
| `denest.py` | `Selector.Alternates` | 7 subclipes de som nunca visitados, sem falha registrada |
| `remap.py` | os dois acima | zero referências trocadas depois do achatamento |

Extraído para `aaf/percurso.py`, um lugar só, com os ramos e o motivo de cada um
tabelados. Depois: 40 referências trocadas onde antes eram 0.

**A lição, que vale além deste caso:** três funções "parecidas" que descem numa
estrutura recursiva não são duplicação inofensiva — são três chances de esquecer um
ramo diferente, e o esquecimento não levanta exceção. Quando o resultado de um percurso
é uma contagem, um número plausível não é evidência de que ele passou por tudo.

**Pendência consciente:** o caminho de *group clip* do achatamento não foi exercitado —
o material de teste não tem multicam (`AppCode` nulo nas composições). O código veio do
RELINKER, que o validou lá; aqui ainda não passou por teste com material real.
