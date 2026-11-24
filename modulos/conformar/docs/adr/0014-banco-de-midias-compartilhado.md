# ADR 0014 — Um banco de mídias por produção, chaveado por NOME

## O problema

Numa novela o mesmo acervo é relinkado dezenas de vezes, por várias pessoas, durante
meses — e cada relink recomeçava do zero: varrer as pastas, ler o metadado de cada
arquivo, casar tudo de novo. Medido: **~61 ms por arquivo** contra **0,04 s** do
casamento inteiro. Praticamente toda a espera é leitura de metadado.

## A decisão

Um **banco por PRODUÇÃO**, em arquivo neutro na rede, alimentado pelos relinks que já
aconteceram e consultado antes da varredura. Ele é **guia, nunca regra**: entrega um
candidato já confirmado por um humano, que passa por **revalidação 1:1** antes de valer.

## ⚠️⚠️ A chave é o NOME, não o `mob_id`

Era a chave óbvia, e falharia **em silêncio**. Em mídia **AMA** o Avid casa por arquivo e
o `mob_id` é **gerado fresco a cada link** — medido no banco de NLEs: **83 de 118 masters
ganharam `mob_id` novo** depois de um relink. Como quase toda a mídia de câmera é AMA, um
banco chaveado por `mob_id` nunca teria um acerto na segunda vez, e não daria erro nenhum.

A chave é o **nome normalizado** (`matcher._normalize_name`), que atravessa projetos e
episódios. `mob_id` e UMID entram como pistas secundárias.

⚠️ Nome colide (cartão reaproveitado entre diárias, `Take 1.wav`). Por isso o banco
guarda **todas** as entradas de um nome e desempata pela **duração**, com o portão do
próprio matcher — duas réguas para a mesma pergunta seria o banco discordando da
varredura em silêncio. Sem desempate possível, ele devolve `ambiguo` e **se cala**.

## Onde encaixa

`master.caminho_conhecido` — estágio 1 da cascata do `casar_masters`, confiança 1.00 —
existia e **nunca era preenchido por ninguém**. O banco não muda o cérebro do casamento:
chega antes com uma resposta já conferida.

## O ganho, medido (2026-08-16)

AAF real de 118 masters, acervo de três pastas, MC 25.6 / Windows 11, cache do sistema de
arquivos aquecido nos dois casos e a rodada **sem** banco por último (a posição mais
favorável a ela):

| | tempo | resolvidos |
|---|---|---|
| sem banco | 2729 ms | 98/118 |
| com banco | 2150 ms | 98/118 (43 vieram do banco) |

**579 ms, 21% — sem perder um acerto sequer.**

⭐⭐ **E a primeira medição mediu a coisa errada, o que ensinou mais que o resultado:**
rodando as duas no MESMO processo, o banco saía **15% mais LENTO**. O motivo é o
`_META_CACHE` do indexer, que é em memória e vive no processo: `index.meta` custou
**7957 ms na primeira rodada e 1 ms na segunda**. Como o serviço é um processo longo, **o
segundo relink da mesma sessão já era rápido antes de o banco existir**.

Daí a régua de expectativa, que vale mais que o percentual:

- **cache de metadado quente** (relinks seguidos na mesma sessão): o banco **custa**
  ~230 ms — leitura do mapa, decisão de 118 masters, revalidação de 43 arquivos em rede;
- **cache frio** (serviço reiniciado, outro dia, outra máquina, outro editor): o banco
  **economiza** ~580 ms, e a economia cresce com o tamanho do acervo, porque o que ele
  corta é metadado por arquivo.

O caso frio é o do fluxo diário. A troca é claramente favorável — mas quem for otimizar
isto de novo precisa saber que "rodei duas vezes e ficou mais rápido" **não mede o
banco**, mede o cache.

## ⛔ O que foi tentado e revertido: dispensar a pasta de mídia

Com o banco conectado, apontar a pasta virou opcional (2026-08-16) — e **voltou atrás no
dia seguinte**, depois do primeiro uso real: o `LinkFile` levou **3m49s** onde antes eram
segundos, com a mesma mídia.

⭐ **A hipótese que explica, e que vale mais que a reversão: a varredura fazia DOIS
trabalhos.** Além de casar, ela lê o metadado de cada candidato — e isso puxa o cabeçalho
de cada arquivo para o cache do sistema operacional. O `LinkFile` do Avid abre os mesmos
arquivos logo depois e encontrava tudo **quente**. Sem varredura, o `LinkFile` virou o
primeiro leitor e passou a pagar a leitura **fria**, dentro do Media Composer — onde é
mais caro e ainda bloqueia a API.

⚠️ Ou seja: o atalho **não economizava, mudava o custo de lugar** — e para um lugar pior.

⚠️ É hipótese, não fato: falta medir `LinkFile` com e sem varredura prévia, com o cache do
SO frio nos dois. Enquanto não houver medida, vale a decisão de quem pagou os 3m49s. Ver
`modelagens/pos-producao/delapraca-mc/ameacas.yaml` T-11.

⭐⭐ **A lição é geral: uma etapa pode estar pagando um custo que ninguém contabilizou
nela.** Antes de remover um passo "redundante", pergunte o que mais ele estava fazendo.

O ganho de 21% medido acima **continua valendo** — ele foi apurado com as pastas
apontadas, e o banco segue acelerando o casamento.

## Consequências

- **Escrita sem trava**: cada máquina só escreve o seu fragmento (`fragmentos/*.jsonl`,
  append-only); a leitura junta pelo carimbo. É a regra do `_PRODUCAO-V`, escrita para SMB
  onde lock não é confiável. O `mapa.json` consolidado é o arquivo neutro de leitura, e
  consolidar **nunca apaga fragmento**.
- **A configuração vive na pasta do PROJETO** (`.delapraca.json`, só o caminho). Daí saem
  de graça: abrir o projeto traz o banco; trocar de projeto desconecta; a equipe que
  compartilha a pasta compartilha o banco.
- **Só entra o que foi confirmado na tela e sobreviveu ao relink** — e o que o Media
  Composer recusou fica de fora, porque seria gravar o erro.
- **Nada disto pode derrubar um relink.** Banco inalcançável é "desconectado" com motivo;
  falha ao gravar é aviso no log.
- ⚠️ Caminho vindo do banco é **entrada de rede**: passa pelo `safepath.ensure_local_file`
  antes de qualquer uso.

## Alternativas descartadas

- **SQLite** (o padrão do MSYNC/MC SINC, WAL + `busy_timeout`): resolveria a concorrência,
  mas o pedido era um arquivo **neutro**, legível e trocável entre ferramentas — e um
  `.db` binário em share SMB troca um problema conhecido por outro.
- **Chavear por `mob_id`**: ver acima. Falha silenciosa.
- **Um arquivo único com trava**: lock em SMB não é confiável; duas gravações simultâneas
  podem perder dados, e aí some o conhecimento de todo mundo.
