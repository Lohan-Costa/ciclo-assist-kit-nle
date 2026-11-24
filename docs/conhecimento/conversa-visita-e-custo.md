# A conversa por visita e o custo do /clear

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐⭐ Uma conversa por VISITA À JANELA: abrir o Ciclo Assist é começar do zero

⭐⭐⭐ **Revista pelo autor em 2026-11-01: a conversa é da JANELA DO APP, não do projeto**
(`rotas.CONVERSA_DA_JANELA`). Era chaveada pelo caminho do projeto aberto — coerente com o painel
DENTRO do NLE; fora deles, cortava o fluxo no meio (turno 1 com o MC fechado converteu no Resolve,
o autor criou o projeto, pediu "continue" e caiu numa conversa vazia). Hoje trocar de projeto ou
de NLE **continua** a conversa, e o turno leva o recado de onde o editor está agora
(`_recado_de_onde`); trocar de NLE reinicia o processo com `--resume` (persona e ferramentas
mudam, o fio fica). Zera por "Limpar conversa" ou visita nova. *"O piloto pode mudar de projeto
sozinho, e o contexto não deve mais ser limitado."* A tabela abaixo é a de antes, menos a linha
"trocar de projeto".

**Decisão do editor (2026-09-14):** *"é melhor o usuário pedir um `--resume` para voltar a
uma sessão anterior do que abrir o Media Composer, fazer um pedido e só depois perceber que
está gastando com uma sessão que não é zerada."* A assistência aqui é pontual por operação
e não precisa segurar memória entre sessões. ⚠️ Se a vida real mostrar que precisa, a
decisão volta atrás — está dito assim de propósito.

⛔⛔ **O aviso não bastava.** O painel já dizia "continuando de onde parou" com o tamanho do
contexto (2026-09-12), e o caso que gerou o aviso — fechar o MC sem `/clear`, reabrir, tela
em branco, 582 mil tokens vivos — continuava possível. **Avisar não é impedir.**

`servico/presenca.py` conta o que é uma visita, pelo SILÊNCIO do painel:

| aconteceu | visita nova? | por quê |
|---|---|---|
| Reload no painel (dev) | **não** | volta em ~1 s |
| painel atrás da janela do MC o dia todo | **não** | o pulso continua (20 s) |
| fechar o painel, ou o Media Composer | sim | ninguém bate |
| reiniciar o serviço | sim | a visita mora na MEMÓRIA |
| trocar de projeto ou de NLE | **não** (desde 2026-11-01) | o turno seguinte leva o recado |

- ⭐ **A visita não vai para o disco de propósito:** "reiniciei o Ciclo Assist" é o gesto
  mais parecido com "quero começar de novo" que existe neste produto.
- ⛔ **A limpeza acontece ANTES de subir o CLI** — depois já seria tarde, porque o
  `--resume` do `do_projeto()` é exatamente o que traz a conversa velha de volta.
- ⚠️ **O pulso do painel não para quando a página está escondida**, que é onde ela passa o
  dia. Webview estrangula timer escondido para ~1/min, daí `SILENCIO_S = 180` contra
  `PULSO_MS = 20000`: mesmo estrangulado o pulso chega três vezes.
- ⬜ **Falta a válvula:** não há como pedir a conversa anterior de volta pelo painel (o
  `--resume` existe no CLI e o id do fio ainda está gravado). Enquanto não houver, limpar
  é definitivo do ponto de vista de quem usa.

### ⭐⭐ O custo é o `/clear`, não o modelo

**MEDIDO em 2026-09-12**, a mesma cena montada duas vezes:

```
                          contexto inicial   chamadas   TOTAL de tokens
Sonnet  (conversa de 2 dias atrás)  505.397      12        6.574.840
Haiku   (depois do /clear)           13.833      13          690.727
```

⇒ **10,8× mais contexto lido para a mesma tarefa**, em 4 minutos de trabalho. O que o
editor leu como "Sonnet é caro" era conversa velha sendo recobrada em cada uma das 12 idas
ao modelo.

⭐ Daí o aviso de fio continuado no painel (`_fio()` em `servico/rotas.py`, gravado no
disco a cada turno): ele fechou o Media Composer sem `/clear`, reabriu, viu a tela em
branco e não tinha como saber que a conversa seguia inteira. **Tela em branco, contexto
cheio** — é o conserto de custo mais barato do produto.

⚠️ **`--effort` existe e nunca foi usado** (`low|medium|high|xhigh|max`; medido
`perTurnEffort: null`). ~70% dos tokens de SAÍDA são pensamento, mas a saída é **0,3% dos
tokens totais** — esforço é alavanca de QUALIDADE, não de custo. O CLI também tem
`--max-budget-usd` (só com `--print`) e `--autocompact`.

## ⚠️ Ferramenta mudada + conversa RETOMADA = a conclusão velha do modelo (2026-11-22, medido pelo chat)

O `conformar_no_baselight` ganhou o `atualizar` e o serviço do Assist foi reiniciado (o endpoint MCP já devolvia o
parâmetro), mas a conversa da janela voltou retomada (`--resume`), com o turno em que o modelo tinha concluído "a
ferramenta não tem opção para trazer a cor" — e ele repetiu a conclusão ("reconferi… continua sem opção") sem chamar a
ferramenta. Com `/clear`, o mesmo pedido passou o `atualizar` de primeira. ⇒ Depois de mudar o esquema de uma
ferramenta, teste em conversa ZERADA; e reiniciar o serviço do Conformar (7823) não muda as ferramentas do chat — elas
vivem no processo do Assist (7824).
