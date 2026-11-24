# O mesmo produto no Premiere

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

## ⭐⭐ O mesmo produto no Premiere (plano `docs/plano/2026-09-17-premiere.md`)

Decisão do editor (2026-09-17): painel CEP próprio, o mesmo serviço na 7824, **na mesma
máquina do Avid**; primeira entrega **só de leitura**. O produto quase não depende de NLE — o
cache, o ASR, os quadros, os vetores, a decupagem e o motor são os mesmos. O que depende mora
em `cicloassist/nle/`.

```
Premiere ─ extensão CEP (só o loader) ─navega→ http://127.0.0.1:7824/painel
                                                   │ a MESMA página do Avid, e nela
                                                   │ `window.__adobe_cep__` continua vivo
   serviço ──GET /premiere/pedido (long-poll)──────┤   (medido no 23.2)
           ←─POST /premiere/resposta───────────────┘ evalScript do host.jsx SERVIDO
```

⭐ **Quem diz qual é o editor é o PAINEL** (`nle: "premiere"` em toda pergunta), e o serviço
guarda o do turno em andamento — funciona porque **é um turno por vez**. Disso saem três
coisas: a persona (`claude.persona`), o filtro de ferramentas (`registro.ferramenta(nles=…)`)
e para quem se pergunta o projeto aberto.

### ⛔⛔ Cada editor tem o SEU banco, e eles só se cruzam ao PROCESSAR (2026-09-21)

**Decisão do editor, depois de usar a busca dentro do Premiere.** Nas palavras dele: *"o
banco do Premiere nunca pré-carrega o material de cache do Avid… a busca no Premiere nunca
deve mostrar ou se referenciar a alguma coisa do Media Composer, e nenhum arquivo da Avid
MediaFiles pode ser exibido na lista"*.

⛔⛔ **E filtro nenhum resolvia isso.** O casamento por conteúdo criava um **apelido** — as
duas mídias viravam UMA pasta. MEDIDO no projeto dele: `B001_03150112_C001.mp4` resolvia
para a entrada `B001_03150112_C001`, cujo **nome é o da bin do Avid** e cujos **arquivos
são três OP-Atom** em `D:/Avid MediaFiles/…`. A entrada ERA a do Avid; recortar por projeto
nunca mudaria o que a lista mostra.

⇒ **O casamento continua valendo; mudou a consequência dele.** Hoje:

| | |
|---|---|
| a entrada declara o editor | `midia.json` → `origem: "avid"` ou `"premiere"` |
| a busca é limitada pelo banco | `cache.chaves_da_origem(origem)` |
| o cruzamento acontece **uma vez, ao processar** | `identidade.aproveitar(arquivo, origem)` |
| e ele **copia** em vez de apelidar | `Midia.copiar_de` |

⭐⭐ **E o preço da separação é 4%, que é o número que decidiu.** Medido neste cache:
`audio.wav` é **1.994 MB de 2.079 (96%)** e é arquivo de TRABALHO, regenerável. O que a
cópia leva — quadros, vetores, transcrição, notas — são **85 MB para 332 mídias**, ~256 KB
por entrada. ⛔ O `audio.wav` fica de fora (`Midia.COPIAVEIS`), e o `midia.json` também:
a identidade é de quem copia, e é justamente ela que separa os bancos.

⭐ **A prova de que é a mesma mídia já existia e já estava medida** (§8/§8b do banco):
candidato por nome + taxa + nº de quadros + TC, decisão por CONTEÚDO — Pearson de 5 quadros
32×32, ⭐ indiferente a nível e ganho, que é boa parte do que um LUT faz. ⚠️ **Burn-in não
foi medido**: uma tarja ocupa região e pode derrubar a correlação abaixo do piso; se
derrubar, o material é reprocessado, que é a falha segura.

⛔⛔ **Só o MASTER atravessa, nunca o subclipe ou o multicam** (decisão do editor,
2026-09-22: *"são elementos que cada software fará diferente e não coexistirão em outra
plataforma"*). A cópia levava o `notas.json` inteiro, e a busca do Premiere mostrou
`C07_P03-T001` — uma nota de take escrita numa conversa do Avid sobre um SUBCLIPE dele —
com o duplo clique abrindo a diária inteira. E a nota do master trazia no `trecho` o nome
da bin do Avid (`a002_03170703_C003`), que vira título do cartão. ⇒ `copiar_de` leva só
as notas `escopo: midia`, com o `trecho` trocado pelo nome deste banco e `copiada_de`.
Limpeza do que já tinha atravessado: `tools/limpar_notas_cruzadas.py [--fazer]` — feita
no cache real, **3 notas de subclipe removidas, 118 renomeadas**.

⭐⭐ **E a nota de TRECHO atravessa** (2026-09-22, revisão). Ela é a decupagem MICRO, e cada
uma custou de 50 a 87 s de Mac: sem ela na lista, a entrada do Premiere refazia HORAS em
silêncio e o mesmo material ganhava duas leituras diferentes. Ela descreve um pedaço do
MASTER, em quadros do master — o mesmo motivo que deixa quadros e vetores atravessarem.
⛔ O `cortes.json` e a receita dele vão junto (sem a receita, `precisa_refazer` compara
contra `{}` e a fila refaz tudo), e a chave é reescrita no formato de
`micro.chave_do_trecho`: com o nome do outro banco, uma micro refeita deste lado gravaria
uma SEGUNDA nota do mesmo trecho em vez de substituí-la.

⛔⛔ **A receita vai junto com a cópia.** Sem os `gerador.<estagio>.json`,
`precisa_refazer()` compara contra `{}` e a fila refaz tudo na primeira passada — a cópia
não teria servido para nada.

⚠️⚠️ **Apelido não atravessa banco, e em TODO caminho.** A primeira versão só tratava o
`__init__`; `_Indice.achar` continuava resolvendo pelo apelido, a entrada "nova" caía na
pasta do Avid e `copiar_de` copiava a pasta **sobre si mesma** — `WinError 32` em cada
quadro, com a entrada respondendo `origem=avid`. Hoje quem decide é `_Indice.dona(chave,
banco)`, e `achada`, `_nascer` e `primaria` passam por ela.

⚠️ **A regra "não sei ≠ nenhuma" ganhou um TETO.** Ela existe para que desconhecer o
projeto não esconda o acervo do editor; ela nunca autorizou mostrar o acervo de OUTRO
editor. No Premiere, sem projeto, a resposta é o **banco dele inteiro** (que pode ser
vazio), nunca o do Avid — `nle/premiere._so_o_banco`. ⛔ E banco vazio **não** é "não
achei": é *"ainda não analisei nada aqui; importe a mídia e mande processar"*.

**Migração:** `python tools/separar_bancos.py [--fazer]` tira os apelidos da era anterior.
Medido neste cache: **207 removidos**, todos apontando para `.mp4`/`.WAV`/`.BRAW` — nenhum
para `Avid MediaFiles`. ⚠️ Nada de mídia é apagado; o casamento volta a acontecer sozinho.

✅ **Conferido no cache real:** Avid **332** entradas, Premiere **3**; a busca do Premiere
cobre só as dela e **diz quantas são**; a do Avid, intacta.
✅ **E a aba Vetores lista e processa a mídia do Premiere** (2026-09-22) — é por ali que o
editor "importa e manda processar", o gesto que dispara o cruzamento. Ver abaixo.

⭐⭐ **A premissa do porte, medida:** o item do Premiere aponta o ARQUIVO; o cache é do master.
`midia/identidade.py` responde "que mídia é este arquivo?" — pela chave dele (UMID, ou a
impressão do conteúdo), por um apelido, ou **pelo convertido**: candidato por nome + TC + taxa
+ quadros, decidido por conteúdo (pixel na imagem, amostra no som). Medido no 23.2 com quatro
arquivos reais: todos acharam o que o Avid já tinha processado, em 0,2 a 2,2 s na primeira vez
e instantâneo depois. ⛔ O embedding do produto **não** serve de juiz aqui (deu 0,909 a um
impostor): "é o mesmo quadro" é pergunta de pixel, não de parecença.

⭐ **O cache ganhou APELIDOS** — uma pasta, várias chaves. É o que faz o `mob_id` do AMA (que o
Avid gera a cada link), a impressão do arquivo e o original de um convertido levarem à mesma
mídia. `cache.com_apelidos()` traduz isso para o recorte por projeto.

### ⭐⭐ Vetores no Premiere: NÃO se reprocessa nada — 202 de 203, medido (2026-09-21)

**A pergunta do editor:** *"precisamos reprocessar os dados de mídia bruta, ou conseguimos
embutir o conteúdo da mídia já processada em OP-Atom nas variantes originais, mp4 ou outras
conversões?"* — **não se reprocessa**, e isto é a P1 do plano, agora medida no projeto real
de Premiere dele contra o cache que o Avid montou.

O cache é uma pasta com VÁRIAS chaves (apelidos): `identidade.achar()` casa o `.mp4`/`.wav`
que o Premiere aponta com o OP-Atom que o Avid processou — candidato por metadado, decisão
por CONTEÚDO —, e grava o apelido. A partir daí é instantâneo, para sempre.

⭐⭐ **E frame N é frame N**, que é o que faz quadros e vetores serem reaproveitáveis sem
conta nenhuma: `e_candidato` exige **mesma taxa, mesmo TC de início e mesmo número de
quadros (±1)**. Par que não garante isso não é par.

**Medido nos 203 arquivos do `CICLO ASSIST TESTE.prproj`** (118 `.mp4` + 85 `.wav`):

| | casaram |
|---|---|
| só pela chave (sem ler conteúdo) | 1 de 203 |
| a régua do porte (P1, medida em dois pares de IMAGEM) | 180 |
| **+ os quatro consertos abaixo** | **202 de 203** |

O único que sobra é honesto: o cache tem OUTRO material com o mesmo nome (46,7 s contra
108,1 s, correlação 0,018). ⭐ Dos 202, o Avid já tinha **194 transcrições, 118 conjuntos de
quadros e 118 vetores**. Primeira passada **51 s**; a segunda, **2 s**.

⛔⛔ **Os quatro defeitos eram todos do SOM**, e a causa é comum: os pares medidos no porte
(banco, §8) eram os dois de imagem, e o som direto de cena — a camada MAIOR do acervo, a
transcrita — nunca passou por aquela régua. O banco tem a página inteira em
`transversal/banco-de-midias-compartilhado.md` §8b.

1. **O `reel_name` do som traz o rolo grudado:** `…C14 P1-T010.WAV:2023-04-06` contra
   `…C14 P1-T010.WAV`. O `.wav` deixava de ser o fim do nome, a extensão não saía, e o par
   nem virava candidato — com as durações idênticas. **36 das 332 mídias** do cache.
2. ⛔⛔ **A MISTURA dos dois lados não prova nada em som multipista.** O WAV do gravador é
   1 pista com 5 canais; o Avid guarda 5 OP-Atom de 1 pista. Somando cada lado: **0,876**,
   abaixo do piso. É o mesmo som **em outra ordem e com uma pista duplicada**. ⇒ `mesmo_som`
   compara **canal a canal**: toda pista de um lado acha a sua no outro, o veredito é o
   PIOR par, e vale o melhor dos dois sentidos (o editor importa 2 das 8 pistas, ou aponta
   um WAV mono que é uma das 5). Verdadeiro **1,000**, impostor (take vizinho da mesma cena)
   **0,024**. ⚠️ **Pista não é canal:** o ffprobe conta *streams*, e um WAV de 5 canais é UM
   stream — daí `canais_de_som` na sonda (v2).
3. **O editor RENOMEIA o take na bin:** arquivo `…C14 P1-T010.WAV`, bin `…C14 P1/010`. O
   pré-filtro barato usa o nome da BIN (e está certo: OP-Atom sem `reel_name` responde
   `A01.E69C….mxf`). ⇒ Quando ele não acha NADA, `candidatos(ampliar=True)` refaz pelo nome
   que está DENTRO do arquivo: **10 s na primeira vez, 0,2 s depois**, contra ~1 min de
   reprocesso.
4. **Clipe mais curto que `POSICOES`** (4 quadros): posição repetida, e o `select` do ffmpeg
   entrega cada quadro uma vez — voltavam menos quadros que posições e saía `-1`, que se lê
   como "não é o mesmo material". Sem repetir: **0,998** (impostor 0,526).

⚠️ **O que continua NÃO casando, por desenho:** convertido que é um RECORTE do meio do
original (consolidate com alças) — `e_candidato` exige o mesmo número de quadros, e a
comparação só olha o primeiro minuto.


#### ⭐⭐ A aba Vetores no Premiere: a terceira fonte, e o cruzamento no clique (2026-09-22)

Até aqui a aba era do Avid mesmo dentro do Premiere: `_clipes_conhecidos()` junta a
`Avid MediaFiles` com as bins do Media Composer, e nenhuma das duas conhece um `.mp4` na
pasta do editor. Hoje, com `nle=premiere` (query no `GET /vetores`, corpo no
`POST /vetores/analisar`):

| | Avid | Premiere |
|---|---|---|
| as linhas do "o que falta" | acervo + bins (`_clipes_conhecidos`) | o projeto aberto (`premiere.clipes_do_projeto`, `cicloMidias`) |
| o banco listado | `origem=avid` | `origem=premiere` |
| o recorte da fila | as bins do projeto (`escopo.agora`) | nenhum: a lista JÁ é o projeto |
| antes de processar | — | `identidade.aproveitar()` — copia o que o outro banco tem |

- ⛔⛔ **A linha de um arquivo novo tem chave PROVISÓRIA** (`premiere.chave_provisoria`,
  hash do caminho), e ela nunca vira pasta. A chave de verdade custaria 8 MB lidos por
  arquivo só para MOSTRAR a lista; e uma chave já conhecida pode ser a de uma entrada do
  OUTRO banco — a fila olharia o trabalho do Avid e responderia "já está pronto" sem
  entrada nenhuma no Premiere. Quem acha a chave é o `aproveitar`, dentro da tarefa.
- ⭐ A fila conta `aproveitadas` à parte: *"1 de 2 vetorizadas · 1 já estava analisada"* —
  sem o número, "1 de 2" se leria como uma falha.
- ⛔ A separação vale nos DOIS sentidos: a aba do Avid também deixou de listar o banco do
  Premiere. E no Premiere a resposta não traz nem a lista de `Avid MediaFiles` do seletor
  de pastas (o spike achou esse único rastro).
- ⚠️ O `host.jsx` passou a mandar `itens` (nome e bins de cada arquivo) ao lado de
  `arquivos`; painel sem Reload continua funcionando só com os caminhos.
- ⚠️ **O item importado se chama como o ARQUIVO, com a extensão** (medido, banco
  `painel-servido-e-identidade.md` §7b): a pasta do cache nasce `A001_…_C001.mp4_23.976_…`.

✅ **MEDIDO no Premiere 23.2** (`spikes/vetores_no_premiere.py`, 14 de 14, sem ninguém na
frente): três arquivos importados numa bin — um convertido que o Avid processou, um `.wav`
que o Avid transcreveu e um `.mp4` gerado na hora. A lista em **0,3 s**, as três como falta
na bin `CENAS`, nada do Avid; vetorizar: **2 na fila, 1 aproveitado (cópia), 1 feito, 6,7 s**;
transcrever: o `.wav` aproveitado em **0,6 s**, sem ASR. Depois: Premiere 3 entradas, Avid 2
intactas.
⬜ Falta ver o painel de produto (aberto pelo menu) com a aba na tela, num projeto real.

#### ⭐⭐ No Premiere a fala LEVA A AGULHA, e a decupagem vai para a coluna "Descrição" (2026-09-22)

Dois pedidos do editor, os dois medidos antes (banco `api-extendscript.md`):

- ⭐⭐ **O Source no ponto da fala — o que o Media Composer 2025.6 não deixa.**
  `app.sourceMonitor` não posiciona; o QE sim: `qe.source.player.scrubTo('HH:MM:SS:FF')`.
  ⛔⛔ **O TC é TEMPO DESDE O INÍCIO DO CLIPE, nunca o TC dele**: num clipe de
  `01:00:00:00`, `scrubTo('01:00:04:00')` foi para 3604 s — ACEITO num clipe de 10 s, sem
  erro. `premiere.tc_no_source` monta o TC (base 24 a 23,976; fração exata, não float) e
  limita ao último quadro; a posição é LIDA DE VOLTA e a tela diz onde a agulha parou.
  ⚠️ **Só no master**: no subclipe do Premiere o zero do `scrubTo` não foi medido (as duas
  leituras estão no mesmo referencial) — abre sem posicionar, e diz.
- ⭐⭐ **A decupagem na coluna "Descrição"** (`Column.PropertyText.Description`, o mesmo
  nome em qualquer idioma). Decisão do editor: **sozinho, sem nunca escrever por cima do
  texto dele** — `cicloDescrever` faz compare-and-set (grava só com o campo vazio ou igual
  ao que NÓS gravamos da última vez, guardado no manifesto em `descricao_no_premiere`).
  Roda ao abrir a lista da aba Vetores no Premiere (no fundo) e no fim de toda tarefa da
  fila do Premiere (e portanto da vigia). Só o MASTER; subclipe é do editor.
  ⚠️ `setProperty(…, "")` não apaga (quem apaga é `deleteProperty`), e `createSubClip`
  copia a Descrição do master para o subclipe.
- ✅ **Conferido no Premiere 23.2 pelo código de produto** (`spikes/source_e_descricao_no_premiere.py`,
  8 de 8): a fala em 4,48 s pôs a agulha em 4,48 s; a coluna escrita, a segunda passada
  sem reescrever, o texto do editor respeitado, apagado → preenchido de novo, subclipe intocado.
- ⭐ E a descrição no cartão da Busca ganhou a setinha (ver a aba Busca).

#### ⭐⭐ A vigia: importou no Premiere, processa sozinho (2026-09-22)

Pedido do editor: *"um botão toggle de watchfolder"*. Não é pasta vigiada, é o PROJETO:
arquivo que cai na pasta e ninguém importa não é material dele. Interruptor na aba Vetores
(só no Premiere), gravado em `estado.json` (`vigia_premiere`); `servico/vigia.py`.

⭐⭐ **O Premiere AVISA do import, e isso era `pendente` no banco** (medido,
`spikes/o_premiere_avisa_import.py`, banco `api-extendscript.md`):
`onItemsAddedToProjectSuccess` dispara no `importFiles`, AGRUPADO (60 arquivos = 2 avisos).
⛔⛔ **`app.bind` devolve `true` para QUALQUER nome, inventado ou não** — só disparar prova;
um nome errado no `host.jsx` não daria erro, a vigia só nunca acordaria (há teste com o nome).

| | custo medido |
|---|---|
| ler o contador de imports (`cicloVigia`), a cada 3 s | ~3 ms |
| varrer o projeto (`cicloMidias`), só quando o contador anda | ~0,5 ms por item |
| do import à fila começar | **2,4 s** (`spikes/vigia_no_premiere.py`) |

- ⚠️ **Varredura de segurança a cada 60 s**, de propósito: import pelo MENU ou arrasto na
  janela de projeto **não foi medido**, e outra extensão pode registrar o mesmo evento
  (substituir o nosso? não medido). Sem ela, "ligada e não fez nada".
- ⭐ **Ligar FOTOGRAFA o projeto**: o que já estava lá não é processado (ligar num projeto
  de 200 clipes não pode virar horas de ASR que ninguém pediu). Trocar de projeto também
  fotografa. O que já estava tem os botões.
- ⛔⛔ **Nunca decupa**: gasta a assinatura, e o preço vem antes do clique. Só vetores
  (primeiro, segundos) e transcrição (depois, ~1 min por take).
- ⛔ Uma tentativa por arquivo e estágio; com tarefa correndo, espera a vez; o resumo leva
  `vigia: true` e a tela diz *"importadas, a vigia mandou"*.
- ⚠️ A vigia só vê o projeto com o painel VIVO (a ponte depende dele).
- ⛔⛔ **E ela RECUA sozinha, porque a ponte é a mesma do chat** (2026-09-23). MEDIDO no
  Premiere do editor: `cicloVigia` — que só lê um contador, e que o banco registra em
  **3 ms** — levou **5,20 s e 5,03 s** dentro do Premiere. Não é o trabalho dele: é o
  Premiere não atendendo o `evalScript`. Com pulso FIXO de 3 s e chamadas de 5 s a fila
  nunca esvazia, e um pedido do painel esperou **12,94 s só para entrar**. ⇒ O próximo
  pulso sai da MEDIÇÃO do anterior (`OCUPACAO_MAXIMA = 10%`): com o Premiere saudável o
  freio não existe, com ele ocupado ela recua para ~45 s **e diz no log que recuou**.
  ⭐ Recuar é a resposta CERTA, não um mal menor: Premiere ocupado é exatamente quando
  processar o que acabou de ser importado importa menos que não atrapalhar.
  ⚠️ **A causa dos 5 s continua desconhecida** — o que foi consertado é o entupimento.
- ⭐⭐ **E o gesto do editor passa NA FRENTE do trabalho de fundo** (`ponte.enfileirar`).
  Entre iguais a ordem de chegada manda. ⚠️ Só reordena o que ainda NÃO foi entregue: o
  que o Premiere já está rodando não dá para interromper. ⭐ E quem é de fundo é a
  **THREAD**, não a chamada (`ponte.marcar_de_fundo`): a vigia e a sincronização de
  descrições passam por cinco camadas antes de chegar à ponte, e levar um parâmetro por
  toda a corrente significaria esquecer uma delas — um pedido de fundo se passando por
  gesto do editor.
- ⛔⛔ **E a varredura de segurança é a ÚNICA que se repete** (revisão de 2026-09-22).
  Enquanto a condição era *"ainda não sei o projeto"*, uma leitura que FALHA deixava o
  projeto vazio e a vigia lia o projeto inteiro a cada `PULSO_S` — para sempre, na MESMA
  fila de um pedido por vez que o chat usa. O sintoma seria *"o painel ficou lento"*, sem
  erro nenhum apontando para cá. Só a PRIMEIRA olhada fura o relógio; depois dela, manda o
  intervalo. ⚠️ E a sondagem do painel também passou a parar com a aba fora da tela:
  `document.hidden` é a JANELA escondida, a aba do painel é outra coisa.
- ⚠️ Com o interruptor ligado e a aba à vista, o painel pergunta pelo andamento a cada 5 s:
  trabalho que começa sem clique e não aparece na tela parece defeito.

⛔⛔ **Um `--` dentro de COMENTÁRIO do `manifest.xml` mata a extensão em silêncio** (XML
inválido): ela some do menu, nada aparece na tela, e o motivo só sai em
`%TEMP%\CEP11-PPRO.log`. O sintoma é igual ao de PlayerDebugMode desligado. Há teste.

⛔ **Sem `--enable-nodejs` no manifesto**, e de propósito: a página vem por HTTP e renderiza
texto que o modelo escreveu. O `__adobe_cep__` não precisa de Node (medido).

⛔ **O texto que vai ao `evalScript` é montado pelo serviço**, nunca pelo modelo:
`ponte.chamar("cicloItem", …)` só aceita nome de função do nosso `host.jsx` e argumentos que
viram literais JSON. Texto livre virando ExtendScript seria um shell no Premiere do editor.

⚠️ **O arrasto da bin do Premiere não entrega nada** (banco): o painel usa o gesto e lê a
SELEÇÃO no drop. Escrito, **ainda não exercitado na GUI**.

⛔⛔ **E o arrasto de FORA (Explorer/Finder) no CEP não traz caminho**: sem `text/uri-list` e
sem `File.path` (que exigiria Node). O painel manda o **conteúdo**
(`POST /arrastados/conteudo` → `arrastados.guardar_conteudo`), e o que fica autorizado é a
CÓPIA na pasta de dados — o gesto continua autorizando um arquivo, não a pasta dele. No
Media Composer nada muda: lá o `uri-list` funciona, e o arrasto de uma bin traz um `.aaf`
FALSO que não pode virar anexo.

⭐⭐ **Escrever no projeto do Premiere: `organizar_o_projeto`** — criar bin, mover e renomear,
o plano inteiro num cartão só (ADR 0008). A conferência roda ANTES do cartão e pega id que
não existe, bin indo para dentro de si mesma (o Premiere aceita, e a bin some da árvore do
editor), nome vazio e lote acima de `MAXIMO_DE_OPERACOES`. ⛔ O plano viaja ao ExtendScript
como TEXTO TABULADO, nunca como código: nome de bin com aspas ou vírgula não quebra nada.

⚠️ **O que o editor pediu e não é nosso:** criar merged clip **não tem via de API** (banco,
`subclipe-e-merged-clip.md`). Quem faz é o Órbita, escrevendo `.prproj` — a ponte planejada
em `DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md`.

⚠️⚠️ **O preâmbulo do arrasto é POR EDITOR.** MEDIDO em 2026-09-17 com o Qwen: o preâmbulo
citava `resolver_take` e "mídia do Avid" numa conversa do Premiere, e o modelo respondeu
"você não anexou nada" — usando o anexo na frase seguinte. Instrução para a ferramenta
errada é pior que instrução nenhuma.

⚠️ **O subclipe:** `getInPoint/getOutPoint` devolvem o master inteiro. O recorte está em
`Column.Intrinsic.SubclipStart`/`SubclipDuration`, e a base é o TC do ARQUIVO (com hard
boundaries o `MediaStart` passa a ser o do subclipe). O Premiere arredonda para baixo.

⬜ Falta: o painel aberto pelo menu numa conversa de verdade; merged clip real; escrita (P6)
e macOS (P7).

**Três invariantes que a revisão de 2026-09-17 cravou** (ver o plano para os onze achados):

- ⛔⛔ **`/vetores/bins` é do AVID** (a LISTA e a fila da aba falam com os dois desde
  2026-09-22; a leitura de bins, não). Ela pergunta o projeto ao Media Composer
  EXPLICITAMENTE: com o painel no Premiere, `_projeto_aberto()` devolve o `.prproj`, a
  varredura acha zero e gravaria uma foto VAZIA por cima da última boa — cegando a busca do
  Avid. E varredura sem masterclipe nenhum nunca sobrescreve a anterior.
- ⛔⛔ **Sem projeto aberto, os dois editores caem na MESMA chave de sessão.** Por isso
  `sessao.do_projeto` reinicia o processo quando o editor da conversa muda: senão o turno do
  Premiere herda a persona e a lista de ferramentas do Avid.
- ⛔ **`/limpar` e `/conversar/parar` usam o projeto do TURNO**, guardado, e nunca uma
  pergunta nova ao NLE: no Premiere isso é ida à ponte, e um painel recém-recarregado
  responde "sem projeto" — o que limparia a conversa de outra chave e deixaria o editor com a
  tela em branco e o fio inteiro vivo do outro lado.
