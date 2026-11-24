# ADR 0009 — O modo automático, e por que ele é um botão e não um padrão

**Data:** 2026-09-11 · **Estado:** aceito · **Altera:** [ADR 0003](0003-modelo-de-permissao.md), [ADR 0008](0008-aprovacao-sem-relogio.md)

## Decisão

Um **toggle na barra de status** do painel. Ligado, `pedir_confirmacao` responde `allow`
na hora: a ferramenta roda dentro do turno, o modelo vê o resultado e segue — sem cartão,
sem pendência, sem clique.

Desligado (o padrão), nada muda: o pedido vira cartão e espera o editor pelo tempo que for
(ADR 0008).

```
auto desligado   modelo pede → cartão na tela → clique do editor → o serviço executa
auto ligado      modelo pede → allow imediato → o CLI executa → o modelo continua
```

## O que o editor pediu

> *"O auto mode é um botão toggle que ao estar ligado aceita sozinho a sugestão de ação,
> como por exemplo a cena que estamos montando: ao invés dele perguntar ele entregaria
> logo a bin com a montagem. Opções para o usuário só aparecem em casos de escolha ou A ou
> B, de resto, é para seguir sem perguntar."*

Ele tinha acabado de viver o caso que justifica: pediu um corte, foi escrever uma mensagem,
e quando voltou o cartão estava na tela esperando por ele. Numa montagem que ele já sabe
que quer, a confirmação não protege nada — **atrasa**.

## Por que isso não contradiz os ADRs 0003 e 0008

O que aqueles ADRs protegem é **o editor não ser surpreendido por uma escrita que ele não
pediu**. O automático não fura essa regra: ele é o editor dizendo, antes e explicitamente,
que aquele tipo de surpresa não existe para ele naquele momento.

⛔ **O que continua valendo, ligado ou desligado:**

- **Sem perguntar não é sem contar.** Toda ação liberada assim aparece na conversa com a
  marca do automático, e o log registra. Quem volta ao painel precisa poder ler o que foi
  feito enquanto não estava olhando.
- **O estado é lido a cada pedido**, nunca guardado na partida: desligar vale para a
  próxima ação, não para a próxima vez que o serviço subir.
- **`escreve=` continua decidindo tudo** (`mcp/registro.py`). O automático muda quem
  responde ao portão, não quem passa por ele.
- **Nasce desligado.** Um produto que instala com a confirmação já dispensada decide pelo
  editor exatamente a coisa que ele deveria decidir.

## Por que `allow`, e não "abrir a pendência e executar sozinho"

A alternativa era manter o caminho da pendência e dispensar só o clique. Seria menos
código novo e **pior**: a ferramenta rodaria fora do turno, e o modelo receberia um `deny`
seguido de um recado no turno seguinte — ou seja, ele terminaria a resposta dizendo "estou
aguardando" enquanto a bin já estava pronta.

Com `allow`, o resultado volta para dentro do turno: o modelo vê o que aconteceu, confere
e comenta na mesma resposta. É o que faz *"ao invés dele perguntar, ele entregaria logo a
bin"* ser verdade, e não só mais rápido.

## Consequências

- **O modo automático é o único caminho em que uma escrita acontece sem clique humano.**
  Isso está escrito no topo de `mcp/ferramentas/portao.py`, e qualquer terceiro caminho
  que apareça no futuro é bug até prova em contrário.
- **A persona passa a pedir menos confirmação em prosa.** O editor foi explícito: pergunta
  só quando há escolha real entre A e B. Perguntar "posso seguir?" a cada passo é o mesmo
  defeito do portão que pergunta para ler (ADR 0003), só que em texto.
- ⛔⛔ **Corrigido em 2026-09-13: a promessa não era cumprida.** O portão respondia `allow`
  a QUALQUER `tool_name`, e o `--restricted` deixa 29 ferramentas nativas do CLI, com
  `Write` e `Edit` (`spikes/o_que_o_restricted_deixa.py`). Com o automático ligado, o
  modelo gravaria em caminho que ninguém arrastou, sem cartão. Duas trancas agora: o
  motor sobe com `--tools ""` (zero nativas), e o portão recusa por nome o que não for
  `mcp__ciclo__*` — ligado ou desligado, e sem virar cartão.
- ⚠️ **Por medir:** o comportamento do automático numa sequência longa de escritas — dez
  `montar_corte` seguidos, por exemplo. Hoje nada limita quantas ações um turno dispara.
