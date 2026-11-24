# O ofício em skills/ e o orçamento do que a ferramenta devolve

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐⭐ O ofício mora em `skills/`, e chega por ferramenta (ADR 0010)

O conhecimento de montagem — casar roteiro com material, onde cortar, o que nunca emendar —
fica em `.md` versionado (`cicloassist/skills/`) e chega ao modelo por `consultar_o_metodo`.

⛔ **Não por `.claude/skills/SKILL.md`**, e isso é medido: `spikes/o_cli_carrega_skill.py`
(2026-09-12) mostrou que **`--restricted` bloqueia as skills do CLI** — sem a flag a skill
carrega, com ela nunca, nas três variantes testadas. E `--restricted` é o ADR 0005.

⭐ O que se ganha mesmo assim é o essencial da skill: **carregar por condição**. A
descrição da ferramenta (~90 tokens) vai em todo turno; o método (~1.000 tokens) só quando
o trabalho pede. A persona voltou a ser o que vale SEMPRE.

⚠️ O preço é o disparo: a skill do CLI carrega sozinha pela descrição, a nossa depende de o
modelo lembrar de chamar — por isso a persona manda consultar antes de montar.

### ⭐⭐ O que a ferramenta DEVOLVE é orçamento, e tem teto

⚠️⚠️ **MEDIDO em 2026-09-12**, montando a C07: **12 de 14 transcrições estouraram o limite
de saída do CLI.** O modelo recebia `Error: result (61.559 characters) exceeds maximum
allowed tokens` mais um caminho de arquivo, via as duas primeiras falas de cinquenta, e
remontava o resto com **13 Greps — 118 KB, o maior consumidor de saída da sessão**. Foi daí
que saiu o erro de aplicar o timestamp de um take em outro.

Três coisas mudaram em `transcrever`, e cada uma tem teste:

- ⭐ **O array `palavras` saiu do padrão** (`por_palavra=true` o traz de volta). O ASR
  continua medindo por palavra e o cache continua guardando — muda só o que SAI. Por isso
  a `ASSINATURA` não mudou e **o cache de 120 MB sobreviveu**.
- ⭐ **Cada fala vem em segundos E em frames**, com os nomes de `montar_corte`
  (`inicio_no_take_frames`, `duracao_frames`). Antes o modelo multiplicava por 23,976 de
  cabeça, duas vezes por corte, quinze cortes por cena.
- ⛔⛔ **Paginação, porque enxugar campo não põe teto.** Reduzir campo divide por um fator;
  lista sem limite não tem teto — uma diária de 257 falas estoura mesmo no formato magro.
  `ORCAMENTO_CHARS` corta a página e a resposta **diz quantas ficaram de fora**: truncar
  calado faria o modelo montar a cena com metade do diálogo achando que viu tudo.

⛔ E o tempo CRU do reconhecedor (`inicio_no_take`/`fim_no_take`) **saiu da resposta**. Ele
só existia para NÃO ser usado, a regra escrita mandava ignorá-lo, e ele virava ponto de
corte assim mesmo. Campo que existe para não ser usado um dia é usado.
