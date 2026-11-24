# ADR 0008 — A aprovação não tem relógio, e quem executa é o clique

**Data:** 2026-09-11 · **Estado:** aceito · **Altera:** [ADR 0003](0003-modelo-de-permissao.md)

## Decisão

`pedir_confirmacao` **responde na hora e sempre `deny`**. Ela abre uma *pendência*, manda
desenhar o cartão no painel e devolve imediatamente. O turno termina, a caixa de texto
destrava, e o cartão fica na tela **pelo tempo que for** — um minuto, ou até amanhã.

Quando o editor clica, é o **serviço** que executa a ferramenta, com os mesmos argumentos
que estavam desenhados no cartão. O modelo fica sabendo no turno seguinte, por um recado
carregado junto da próxima pergunta.

```
modelo pede montar_corte
   └→ portão abre a PENDÊNCIA e responde `deny` na hora
        └→ o modelo diz "mostrei o plano, me avise" e o turno TERMINA
             └→ o cartão fica; o editor vai ao Avid, almoça, volta amanhã
                  └→ ele clica → o SERVIÇO executa → o painel mostra o resultado
                       └→ no próximo turno, o recado conta ao modelo o que foi feito
```

## O que forçou a mudança

O desenho anterior bloqueava a chamada MCP até o clique. Parecia natural — o subprocesso
espera, o editor decide, a ferramenta roda —, e funcionou em todos os testes, porque em
todos eles havia alguém na frente da tela.

No primeiro teste de campo (2026-09-10), o editor pediu um corte de catorze planos e foi
fazer outra coisa enquanto o modelo trabalhava. `montar_corte` "deu timeout" **três vezes
seguidas**. Com ele presente, clicando assim que o cartão aparecia, a mesma chamada com o
mesmo plano passou em **5,5 s**.

### A medida

`spikes/portao_espera.py` (2026-09-10, CLI 2.1.267) — hoje `spikes/portao_sem_relogio.py`:

| | o CLI desiste em |
|---|---|
| padrão de fábrica | **60,0 s** |
| com `MCP_TOOL_TIMEOUT=20000` | **20,0 s** (exato — a variável vale) |

⇒ O editor tinha **um minuto** para ler um plano de catorze cortes e decidir. E o relógio
corria justamente enquanto ele fazia a coisa certa: ir ao Avid conferir o material.

Havia um segundo defeito, pior que a espera. Pelo caminho padrão a mensagem que chega no
modelo é `"The operation timed out."` — sem uma palavra sobre permissão. O modelo então
diagnosticava o que podia: *"talvez o plano com 14 cortes seja grande demais"*. Quebrou o
corte em dois lotes, criou três sequências de teste na bin do editor e gastou turnos da
assinatura dele caçando um defeito que não existia.

E um terceiro, silencioso: quando o CLI desistia, o cartão **continuava na tela com os
botões vivos**. Clicar nele destravava uma thread que ninguém mais escutava — o editor lia
`✓ você permitiu` e nada acontecia no Avid.

## Por que não foi só esticar o prazo

Foi a primeira correção tentada: `MCP_TOOL_TIMEOUT` em 30 minutos, com o nosso relógio um
pouco abaixo para que a mensagem de estouro fosse nossa. Resolve os três defeitos e é uma
linha.

⛔ **E ainda assim está errado**, porque mantém a premissa: que existe um prazo para uma
pessoa decidir. Com 30 minutos, quem sai para almoçar perde o trabalho em vez de quem sai
para o café — o mesmo defeito, mais raro e mais difícil de reproduzir. Pior: o painel fica
travado enquanto o cartão espera, então o editor que não quer decidir agora também não
pode conversar.

> Numa conversa, quem pergunta para de falar e espera. Não há prazo para a resposta de uma
> pessoa. O erro era ter relógio, não o tamanho dele.

## O que muda no contrato do ADR 0003

As duas metades da regra continuam de pé — leitura nunca pergunta, escrita sempre pergunta
— e a aprovação continua sendo do **plano inteiro**, item a item, com procedência.

O que muda é quem executa, e isso aperta a regra em vez de afrouxá-la:

| | antes | agora |
|---|---|---|
| quem roda a ferramenta | o CLI, depois do `allow` | **o serviço**, depois do clique |
| o que roda | o que o modelo pediu | **o que o editor leu na tela** |
| sem resposta | vira `deny` por cansaço | **fica esperando** |
| painel fechado no meio | a ação morre | a pendência espera no disco |

⚠️ **`deny` aqui não quer dizer "recusado"** — quer dizer "não é o modelo quem faz isso".
A mensagem que volta precisa ensinar o modelo a parar e esperar, senão ele lê uma recusa e
tenta outro caminho. O texto está em `portao.AGUARDANDO`, e cada frase dele evita um erro
visto em campo.

## O que o modelo faz com isso — medido

`spikes/portao_sem_relogio.py` (2026-09-11), seis critérios, todos passando:

```
✓ a chamada não bloqueou              (turno inteiro em 9,3 s)
✓ virou UMA pendência                 (sem cartões empilhados)
✓ não pediu duas vezes
✓ nada foi escrito antes do clique
✓ o clique executou de verdade        (com o turno já morto)
✓ o modelo soube sem refazer          (pelo recado, sem turno extra)
```

E o que ele disse ao editor no fim do turno 1, sem ninguém mandar:

> *"Aguardando o editor autorizar, no painel, a gravação da nota."*

## Consequências

- **O `MCP_TOOL_TIMEOUT` continua sendo setado**, mas por outro motivo: `transcrever` passa
  de um minuto num take de quatro, e com o padrão de fábrica ela morria no meio. Dez
  minutos, e nunca mais como prazo de gente (`turno.PRAZO_DO_CLI_MS`).
- **A pendência é estado que sobrevive ao processo** — primeiro estado assim no produto.
  Mora em `%LOCALAPPDATA%\CicloAssist\pendencias.json`, ao lado do cache, e volta pelo
  `GET /pendencias` quando o painel carrega.
- **O recado custa tokens na próxima pergunta do editor**, e por isso é uma linha. Sem ele,
  o modelo — que viu a própria chamada ser negada — ofereceria montar de novo.
- ⚠️ **Por medir:** o que acontece com uma pendência cujo projeto foi fechado e outro
  aberto no lugar. Hoje ela reaparece igual; o cartão devia dizer de que projeto é.
