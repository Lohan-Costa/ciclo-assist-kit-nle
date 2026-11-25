# A aba Busca

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐⭐ A aba Busca: as duas buscas SEM gastar um turno do modelo

**Feita em 2026-09-20.** As duas buscas já existiam; o que faltava era o editor
alcançá-las. Até aqui `procurar_no_material` e `planos_parecidos` eram só ferramentas MCP:
para achar um plano, ele escrevia uma pergunta e pagava um turno. O motor é o mesmo
(`midia/decupagem.py` e `midia/vetores.py`) — o que muda é quem pergunta, e aqui a resposta
custa uma leitura de disco.

| rota | responde | motor |
|---|---|---|
| `POST /busca/frase` | *"onde tem close noturno no consultório?"* | `decupagem.procurar` |
| `POST /busca/parecidos` | *"onde MAIS eu tenho um plano assim?"* | `vetores.procurar` |
| `GET /busca/quadro` | a miniatura, do cache | — |
| `GET /busca/vocabulario` | os cinco campos fechados, para os filtros | `decupagem.CAMPOS` |
| `POST /busca/carregar` | põe a mídia no monitor **Source** (abrindo a bin se precisar) | `LoadMobsIntoViewer` |
| `GET /busca/recortes` | quantos subclipes o projeto tem — e AQUECE o índice | `avid/subclipes.py` |

⚠️⚠️ **O tamanho do que a busca alcança fica SEMPRE na tela** ("40 mídias · procurei em
168 com decupagem e 315 com fala, de 323 no cache — o projeto tem 423 masterclipes"). No chat quem diz isso é o modelo; aqui não há modelo nenhum, e sem a frase
*"não achei"* se lê como *"meu material não tem isso"*. Vale inclusive quando ACHOU, e o
recorte do projeto vai junto pelo mesmo motivo — filtro calado é pior que filtro nenhum.

⛔ **O vocabulário vem do SERVIÇO** (`/busca/vocabulario`), e não de uma cópia no
JavaScript: dois literais iguais em dois arquivos divergem calados, e a tela ofereceria um
valor que nota nenhuma usa. Os sinônimos (`primeiro plano` → `close`) valem aqui como
valem para o modelo, e valor inventado volta **200** com a lista — um 4xx viraria "não
consegui falar com o serviço", que é o sintoma errado.

⭐ **Cartões, e não a tabela da aba Vetores.** A Vetores responde "o que falta processar",
que é comparar números em muitas colunas; esta responde "é este o plano?", que é OLHAR. Sem
miniatura o editor carrega cada clipe no Avid para saber se acertou.

⛔⛔ **A chave do quadro é validada por `cache.e_chave` antes de virar caminho.** Ela chega
na URL, e URL é entrada não confiável como qualquer outra: sem a checagem, um `..` levaria
uma tag `<img>` a ler a máquina do editor por dentro. E a rota nunca EXTRAI — rolar uma
lista dispararia dezenas de ffmpeg.

⚠️ **`/busca/quadro` tem três respostas, e a diferença é de propósito:** sem `frame`, o
quadro do MEIO dos guardados; com `frame=N`, exatamente aquele (404 se não houver); com
`&perto=1`, o guardado mais próximo. O `perto` é EXPLÍCITO porque a lista de parecidos pede
posições exatas, e um "mais próximo" calado ali mostraria um quadro dizendo ser outro.
⭐ Sem ele, a primeira tela com o acervo real saiu **sem miniatura nenhuma**: a nota de
escopo `midia` não tem `inicio_frames` (é do material inteiro), e a de take aponta um frame
do master que quase nunca é um dos 12 amostrados.

**Medido no acervo desta máquina (2026-09-20):** a busca por frase leva **0,1 s** em 172
mídias decupadas. A de parecença, **~5 s na primeira do dia** e **~260 ms depois** (200 ms
de busca + 63 ms de vetorização) — é o cache de disco do sistema, o mesmo efeito de 8× já
medido na identidade do porte para o Premiere, não regressão.

✅ **Conferido na tela**, a 400 px, com 8 mídias reais do cache: a aba, o vocabulário, os
achados com miniatura, os cinco filtros, o aviso do recorte, e os parecidos abrindo DENTRO
do cartão que os pediu. ⬜ **Falta ver dentro do Media Composer** — o QtWebEngine não é o
Chrome, e o painel precisa ser recarregado (Reload) depois de reiniciar o serviço.

⚠️ Duas armadilhas de layout, as duas medidas no print: `.bus-achado` precisa de
`flex-wrap` (senão os parecidos abrem AO LADO do texto) e `.bus-corpo` precisa de
`flex-basis: 0` (com `auto`, num cartão que pode quebrar, o texto desce para baixo da
miniatura em 400 px).

#### ⭐⭐ A rodada de 2026-09-21: o que o primeiro uso real mostrou

A aba rodou no Media Composer do editor e as quatro coisas que ele achou viraram as quatro
mudanças abaixo. **A lição comum:** cada uma é uma promessa que a tela fazia e não cumpria.

**1. ⛔⛔ A busca não alcançava a FALA — e a fala é a camada MAIOR.** Ele procurou `Personagem F`,
recebeu 4 resultados e disse *"há mais informações com esse indicador"*. Medido no cache:
`personagem f` em **2** decupagens e em **241 falas de 86 mídias**; e o acervo tem **319 mídias
transcritas contra 168 decupadas**. A busca cobria a menor das duas.
⇒ `midia/busca.py` varre as duas, numa **linha por MÍDIA** com as falas dentro (uma linha
por fala daria 241 linhas). Toda linha diz `achado_por` — *imagem* (alguém OLHOU) ou *fala*
(alguém DISSE) —, porque as duas se conferem de jeitos diferentes.
⭐ **Nome próprio prova a regra:** "Personagem F" vem do roteiro ou da claquete, e quem a diz em
voz alta é o diálogo. Nunca o rosto.
⚠️ **A fala se localiza em mm:ss do MASTER, não em timecode:** só **10 de 306** transcritas
têm a taxa gravada no cache, e inventar 25 fps erraria todo material 23,976. ⛔ E é "onde
ouvir", nunca "onde cortar" — quem monta passa por `transcrever`, que dá o respiro medido.

**2. ⛔⛔ A busca casava no MEIO da palavra, e ninguém tinha notado.** Era `termo in texto`,
substring puro. Com `cão` sem acento virando `cao`, casava **toda palavra terminada em
-ção** (`ação`, `alimentação`, `apresentação`): "cachorro" devolvia **200 de 332 mídias**.
`sol` casava `absolutamente`; `mar` casava `amar` e `câmara`. Só apareceu ao varrer a
transcrição, onde o vocabulário é muito maior que o das decupagens.
⇒ `decupagem.casa_termo` casa no **começo da palavra** — e não em palavra inteira, porque o
português flexiona (`carro`→`carros`, `aérea`→`aéreas`, `conversa`→`conversam`). Vale para
as DUAS buscas: `procurar_no_material` e a aba têm de responder o mesmo.

**3. ⭐⭐ O dicionário de intenção (`midia/intencao.py`).** Ele procurou `drone` e recebeu
zero, com material de drone no projeto: a decupagem escreveu *"Vista aérea de uma
rodovia…"* e os clipes se chamam `DJI_0311`. No cache: **`drone` 0, `aérea` 4, `voo` 2**.
⇒ `drone` é uma INTENÇÃO, satisfeita por um conjunto de palavras (PT e EN — o ofício é
bilíngue e o modelo escreve em português). **Medido:** `drone` 0→13, `wide` 0→90,
`personagem f` 4→86.
⭐ **OU dentro do termo, E entre termos** — expandir para OU entre termos devolveria o
acervo.
⛔⛔ **A expansão é DITA na tela.** Busca que se alarga calada é a irmã do filtro calado: o
editor leria "13 achados" para "drone" sem saber que nenhum tem a palavra que ele escreveu.
⛔ **E expansão genérica não estreita nada:** `mar` sozinho cobre **36% do acervo** (casa
"Pessoa U", "marido", "marcar") — saiu de "praia", e um teste barra expansão curta demais.

**4. ⭐⭐ O resultado agora FAZ alguma coisa: duplo clique → monitor Source.** *"Ao listar o
clipe, não é possível fazer nada"* — uma lista de achados em que nada acontece é uma lista
que ele lê e depois vai procurar o nome na bin à mão.
⛔⛔ **E a bin precisa estar ABERTA — MEDIDO em 2026-09-21, uma variável só:** com a bin
fechada o `LoadMobsIntoViewer` devolve `Some mobs was skipped.`; abrindo a bin e repetindo,
carrega. No MC do editor **nenhuma bin estava aberta** (`GetBins` veio vazio), então sem a
segunda tentativa o duplo clique "não faria nada" em quase todo resultado. ⇒ O serviço acha
a bin lendo a `.avb` (instantâneo, sem tocar no MC), dá `OpenBin` e repete — e **diz** que
abriu, porque a bin apareceu na tela sem ele ter pedido. Medido: 1,1 s abrindo, 0,1 s quando
já estava aberta.
⛔ **Não passa pelo portão**, e é a régua da casa: o portão separa quem LÊ de quem ESCREVE, e
carregar no Source não muda o projeto — muda o que está na tela, que é o que o duplo clique
pediu. Pedir confirmação aqui seria o editor clicando "permitir" para ver um clipe.

**E o "solte aqui" que acendia era defeito nosso.** Arrastando um resultado, o painel
acendia o realce de anexo no rodapé — prometendo receber o que ele mesmo tinha mostrado. A
miniatura é um `<img>`, e `<img>` é arrastável por padrão: o arrasto carrega `Files`, que é
o que o realce procura. ⇒ Duas travas: as miniaturas deixam de ser arrastáveis, e todo
arrasto **iniciado dentro da página** fica marcado (pega o texto selecionado e o que vier
depois). ⚠️ Conferido por CDP que de fora **volta** a acender — marca pendurada deixaria o
painel surdo ao arrasto seguinte, que é o defeito oposto e pior.

**⛔⛔ E o rótulo dos números FALHOU, literalmente.** Vendo *"168 de 323 mídias decupadas"*
ele perguntou: *"168 seriam as mídias do projeto e 323 o total do banco?"* Não — os dois
eram do recorte, faltava o terceiro (o projeto tem **423** masterclipes, dos quais o cache
só conhece 323), e a conta estava **inflada**: ela contava quem tem ARQUIVO `notas.json`, e
**4 dos 172 estavam vazios** (os que o `consertar_quadros.py` esvaziou). ⇒ `busca.Alcance`
tem os quatro números, cada um com o seu nome, e `decupadas` conta decupagem, não arquivo:
*"40 mídias · procurei em 168 com decupagem e 315 com fala, de 323 no cache (o projeto tem
423 masterclipes)"*.

✅ **Conferido no Chrome a 400 px** com o cache e o projeto REAIS: `personagem f` 40 mídias com as
falas em mm:ss, `drone` 13 com a linha da expansão, e o duplo clique carregando `DJI_0310`
no Source depois de abrir `O PRODUCAO-A\D04\D04_DRONE.avb`.
⭐⭐ **Os termos entre línguas: `midia/termos.json`, um dicionário ABERTO** (2026-09-22).
O editor procurou `claquete` e não achou nada: a decupagem tinha escrito `clapperboard` —
**39 notas contra 2**. Pedido dele: *"um dicionário de termos para não limitar as opções…
em aberto, para ir completando"*. Diferente de `INTENCOES` (mão única), cada grupo vale nos
DOIS sentidos, e tem um `preferido` em português que entra na instrução do decupador
(`PERSONA`, Claude e Mac) — o dicionário conserta o que já foi escrito, a instrução, o que
vem. ⚠️ `evitar` ≠ `tambem`: "lapela" é português legítimo e a busca aceita, mas não pode
entrar como proibida. Medido depois: `claquete` 0 → **41** mídias, as mesmas de `clapperboard`.
⚠️ As decupagens JÁ escritas continuam com `clapperboard` (e é isso que vai para a coluna
Descrição do Premiere) — reescrevê-las é decisão do editor, não foi feito.
⛔ **E "aberto" de verdade: ele é RELIDO quando muda** (revisão de 2026-09-22). O mapa era
montado no import do módulo — o editor acrescentaria um grupo, procuraria, nada mudaria, e
nada na tela diria por quê. Hoje a assinatura do arquivo (mtime + tamanho) decide, com um
**piso de tempo de 2 s**: `equivalentes` é chamada uma vez por (fala × termo) — dezenas de
milhares de vezes numa busca —, e um `stat` por chamada somaria ~0,1 s numa busca de 0,3 s.
⚠️ Arquivo que some não zera as intenções: fica o que havia, e a busca volta a ser exata.

⛔⛔ **E uma peça em trechos não ocupa mais a lista do chat.** `procurar_no_material`
devolve NOTAS, e com a micro uma peça montada tem uma por PLANO — 600 numa peça de meia
hora. Sem teto ela preenchia sozinha os 20 resultados e empurrava para fora justamente o que
responde *"onde MAIS?"*. Até **3 por mídia** (a mesma régua de `planos_parecidos`), em ordem
de tempo, e o que ficou de fora é DITO — senão o modelo leria "achei 3 nesta peça" como "só
há 3" e contaria isso ao editor com a confiança de quem varreu tudo.

⭐ **O duplo clique vai ao PONTO** (Premiere): o quadro da nota quando há, senão o INÍCIO do
clipe — nunca "onde o editor parou" (o Premiere lembra por clipe). ⚠️ A decupagem do
master não tem posição: "ir à claquete" de verdade é a camada MICRO (nota por segmento),
o plano parado. E o sucesso ficou CALADO (o "no Source" verde-água saiu, pedido dele).

⭐ **A setinha da descrição** (2026-09-22): o cartão mostra o pedaço em volta do termo
(o porquê de ter casado) e a seta à esquerda abre a descrição inteira. A inteira vem só na
resposta da ABA (`busca.py`), nunca no `formatar` do chat — parágrafos por resultado
encheriam o contexto do modelo. Conferida no Chrome a 400 px.
⬜ **Falta**: arrastar do painel para a timeline (**não medido, e o banco não tem uma linha
sobre arrasto SAINDO do painel**); arrastar uma imagem de referência para a aba; e posicionar
o Source na fala clicada (⚠️ `SetPosition` não existe no MC 2025.6 — banco).

#### ⭐⭐ Preferir subclipes: três faixas, e é ORDEM (2026-09-21)

**Pedido do editor:** *"em um trabalho real, os editores trabalham com subclipe ou
groupclipe, recorrendo ao bruto só quando não há esses tipos de arquivos. O filtro que digo
deve ser preferência e não exclusão."*

| faixa | o que é | por quê |
|---|---|---|
| **1** | subclipe / group clip que casou | é com isto que ele monta |
| **2** | master que casou e cujo material **ainda não apareceu** acima | notícia nova |
| **3** | master que é a origem de um recorte já mostrado (`já acima`) | redundante |

⛔ **Nada some.** Interruptor "preferir subclipes" no topo da aba, **ligado por padrão**, e
o corte é dito: *"20 resultados · 149 abaixo do corte"*. Com 1.093 masters, reordenar sem
contar transformaria a preferência em exclusão calada — o oposto do pedido.

⛔⛔ **O cache não tem subclipe, e nem deveria.** Ele é endereçado pelo UMID do MASTER;
processar um recorte seria reprocessar o que o master já tem pronto. Quem sabe de subclipe é
a BIN — `avid/subclipes.py` a lê e monta `{chave do master: [Recorte]}`, com a janela **por
master**.

⚠️⚠️ **Por master, e isto é a armadilha.** Um subclipe sincronizado mistura dois, com
in-points diferentes — medido no `C04_P01-T002`: **imagem em 0, som em 214 frames**. A fala
está no tempo do master de SOM; conferi-la contra o offset da imagem dessincroniza em 9 s,
calado. Não existe lugar aqui de onde pegar "o offset do take", pela mesma razão de
`avid/take.py`.

⭐⭐ **Um recorte casa por CONTER, quando há tempo para conferir:**

| o que casou | tem posição? | como o recorte entra |
|---|---|---|
| fala | sim (`inicio`, em segundos do master) | só se a janela **cobrir** aquele segundo |
| decupagem de MÍDIA | não — descreve o master inteiro | **herdando**, com o selo `do master` |

⛔ **E o master só cai para a 3ª faixa se os recortes cobrirem TUDO o que ele casou.** Uma
fala em 08:00 que nenhum subclipe alcança é material que só existe no master: mandá-lo para
o fim por "já apareceu" enterraria a única linha que a tem.

⛔⛔ **O editor COPIA o subclipe entre as bins de trabalho.** MEDIDO no `_ASSIST ANTERIOR`:
**290 pares (master, recorte) são 130 recortes distintos**, e um está em **6 bins**
(`C04_FALAS`, `C04_FALAS NOVO`, `C04_FALAS NOVO 5`, `CENAS/C04`…). Sem juntar, "personagem f"
mostrava o mesmo `C04_P06-T002` cinco vezes antes de qualquer outro material — a lista
inteira gasta em cópias. A identidade é **nome + janela**, não só a janela: dois subclipes
podem coincidir no recorte, e juntá-los perderia um nome que o editor reconhece.

**Medido no projeto dele (37 bins):** 1.093 masters visíveis, **150 subclipes** cobrindo 108
masters, **0 group clips**, 80 sequências. Listar 0,4 s; resolver os 150 (master + recorte)
**3,1 s**, 150 de 150.

⭐ **O índice é guardado e invalidado pela ASSINATURA das bins** (nome, mtime, tamanho —
**0 ms** para as 37), nunca por relógio: relógio erra nos dois sentidos, refazendo o que não
mudou e servindo o que mudou. Salvar uma bin no MC refaz o índice na busca seguinte.

⭐ **E ele é AQUECIDO quando a aba abre** (`GET /busca/recortes`, que de quebra conta
*"150 no projeto"*): pago dentro da primeira busca, o custo se lê como "a busca é lenta";
pago na troca de aba, cabe no gesto. Depois de quente: **0,3–0,4 s** por busca, 2,1 s no
termo mais largo (`personagem f`, 325 achados antes do corte).

⚠️ **Group clip entra na ordem, mas `take.resolver` ainda o recusa** (`take.RECUSAS`) — e o
projeto do editor tem zero. A preferência por groupclipe precisa de um projeto que os tenha
para sair de `hipotese`.

⛔⛔ **E os dois defeitos que o primeiro uso com subclipes revelou (2026-09-21).**

**1. Clicar duas vezes no mesmo clipe dizia que a mídia podia estar offline.** MEDIDO com
uma variável só: carregar A → **OK**; A de novo → **FALHA**; carregar B → OK; A de novo →
**OK**. O Media Composer recusa o mob que **já é o carregado naquele viewer**, e usa a
MESMA frase de "a bin está fechada" (`Some mobs was skipped.`) — a mensagem que significa
erro num caso significa *sucesso* no outro. O editor lia *"não consegui carregar X, nem
depois de abrir a bin Y. A mídia pode estar offline"*: três afirmações, as três falsas,
sobre um clipe que estava na tela dele. ⇒ Depois da falha, `GetViewerMobs` decide qual das
duas é. ⚠️ **Só depois da falha:** ele custa ~1,1 s mais a pausa de 3 s do monitor, e o
caminho normal (clipe novo) não paga nada — medido: 1,0 s o clique que carrega, 5,1 s o que
descobre que já estava. ⚠️ Corrigi o banco, que eu tinha registrado incompleto horas antes.

**2. A busca ficava "procurando…" para sempre.** O índice de recortes era construído DENTRO
da chamada: a aba (que aquece) e a busca entravam nele **ao mesmo tempo**, cada build
deixava o outro dez vezes mais lento (3,6 s → mais de 30 s), e o seguinte começava por
cima. No log dele: **quatro builds em um minuto**, e nenhuma resposta. ⇒ Duas travas:

- ⭐⭐ **UM build por projeto.** Quem chega depois espera aquele, nunca começa outro.
- ⭐⭐ **A busca NUNCA espera** (`esperar=0`): pega o índice que houver — inclusive o
  **velho**, que erra só no que mudou — e o build corre no fundo. Só o aquecimento espera,
  porque ali ninguém está olhando o relógio.

⚠️ **E "pedi a preferência e ela ainda não valeu" é dito na tela**, porque é um resultado
DIFERENTE de não pedir: a lista sai só com masters, e sem a frase parece que o projeto não
tem subclipe nenhum. ⛔ A vaga do build sai num `finally`: não devolvida, o índice trava
para sempre e o sintoma é "os subclipes nunca ficam prontos", sem erro.

✅ Conferido na tela: busca logo depois de abrir a aba volta em **4,4 s** com 13 resultados
e o aviso do índice; a seguinte traz os 40 subclipes e o aviso some.

✅ **Conferido na tela** com o projeto real: `personagem f` 20 resultados todos de 1ª faixa;
`drone` 13 todos de 2ª (não há subclipe de drone, então o master é notícia nova);
`blusa vermelha` 9 de 1ª e 6 marcados `já acima`.

#### ⭐⭐ A rodada de 2026-09-21 (tarde): o subclipe é UMA linha, com TC e timeline

**1. ⛔⛔ O mesmo subclipe saía duas vezes.** O editor: *"a lista retornou o mesmo subclipe
separando como se fosse só o áudio primeiro, e depois o mesmo subclipe com o vídeo"*.
MEDIDO: **140 dos 150 recortes têm DOIS masters** (imagem e som), e a busca emitia um achado
por *(master, recorte)*. ⇒ `busca._fundir` junta as duas metades: a **imagem** manda no que
se olha (miniatura, decupagem, `chave` do cache) e o **som** traz as falas.
⚠️ A regra *"uma linha é um MASTER"* vale na aba **Vetores**, onde a pergunta é "o que falta
processar" e o master é a unidade de processamento. Aqui a unidade é o que o editor arrasta.

**2. ⭐⭐ O timecode completo da fala** (`07:00:59:13` em vez de `00:29`). O TC de fonte vem
das tags de STREAM do `ffprobe` — conhecimento do banco (`protocolos/mxf/timecode.md`, 3/3
exato), conferido na mídia dele: `15:02:29:00`, `01:31:32:00`.
⚠️⚠️ **A taxa NÃO vem do arquivo de som** (medido: `time_base = 1/48000`, e o acervo não
guarda `fps` para áudio): a conta usa a do **projeto aberto**, que é a taxa em que o Media
Composer exibe aquele master. ⇒ **o segundo é exato, o quadro é aproximado**, e a tela diz
isso. ⛔ Sem projeto aberto não se inventa taxa — chutar 25 fps erraria todo material
23,976, que é este acervo inteiro.
⛔⛔ **E o TC é lido DEPOIS do corte:** dentro da busca custava **17,4 s** (um `ffprobe` por
master, 172 ms frio, nas 86 mídias que "personagem f" casa, para mostrar 40). Depois do corte:
**3,4 s**, e **1,7 s** com o cache quente. Guardado para sempre em `timecodes.json` — o TC
de fonte de um arquivo não muda.
⛔⛔ **E ele sai do master DA FALA, nunca do master do achado** (revisão de 2026-09-22).
Numa linha FUNDIDA a chave do achado é a da IMAGEM — e está certo, é ela que endereça a
miniatura —, enquanto as falas vieram do SOM. MEDIDO no `_ASSIST ANTERIOR`: **59 de 59** pares
imagem+som têm TC de fonte DIFERENTE, e a diferença é de HORAS (a câmera em `03:14:14:17`,
o gravador em `11:42:00:00` — TC de rolo contra hora do dia). O TC mostrado errava por 8 h e
meia, e é um número para o editor DIGITAR no Avid. Hoje cada fala carrega o master de onde
veio (`chave_do_master`).

**3. ⭐ A linha da fala é um BOTÃO** e carrega no Source o item que a contém — o subclipe,
quando a linha é de um. ⛔⛔ **Não dá para POSICIONAR a agulha: `SetPosition` não existe
nesta build** (medido no MC do editor: `McApiNaoImplementado`; o banco tem a medição no
25.12, onde existe). O caminho alternativo do banco é teclado simulado (~1,5 s, frame
exato), que **rouba o foco** do painel — decisão do editor: fica para depois, e o timecode
escrito ao lado é o que leva ao quadro.
⭐ **E "no Source" carrega o RECORTE**, não o master dele (medido: `LoadMobsIntoViewer`
aceita o mob de um subclipe). Carregar o master de um resultado que é subclipe põe uma
diária inteira no lugar do trecho que ele clicou.

**4. ⭐⭐ A etiqueta da timeline.** Cada item diz em que timelines do projeto é usado. O
índice sai da MESMA varredura de bins (80 sequências, ~1 s), e o build inteiro passou de
3,6 s para **4,1 s**.
⛔⛔ **`Selector`: só o ramo ESCOLHIDO.** Ele guarda o que toca e as ALTERNATIVAS que não
tocam — medido um com `selected = 0` apontando um **`Filler`** (nada toca ali). É
literalmente o pedido: *"conteúdo de timeline só deve entrar o que de fato foi usado"*.

⚠️⚠️ **E uma medição minha que estava ERRADA, corrigida no mesmo dia.** Eu disse ao editor
que a timeline da `relink.avb` usava **9 dos 44** subclipes da bin. Era artefato do
instrumento: `timeline_do_editor.ler` corta a saída por `ORCAMENTO_CHARS` (mostrou 242 de
641 segmentos), e eu contei nomes na saída truncada. A varredura recursiva da árvore diz
**44 de 44**. ⇒ Aqueles subclipes **não** são lixo de bin: são material montado. E
⛔ **eles estão VISÍVEIS** (`user_placed=True`), não ocultos — a hipótese de que o filtro de
ocultos estava falhando não se confirmou.

✅ Conferido na tela com o projeto real: 40 cartões, **zero títulos repetidos**, 60
etiquetas de timeline, 233 falas clicáveis e o TC completo em cada uma.
⬜ A faixa de etiquetas ficou cheia (espécie + timeline + origem + cinco campos) — o editor
já disse que vai retrabalhar a área de filtro, e isso entra junto.

#### ⛔⛔ A aba Busca respondia pelo AVID dentro do Premiere (2026-09-21)

**Primeiro teste real da aba dentro do Premiere, e ele viu três coisas.** Num projeto
`CICLO ASSIST TESTE.prproj` aberto na frente dele: os resultados vinham recortados pelo
`_ASSIST ANTERIOR` — projeto do **Media Composer**, **fechado**, servido pela FOTO da última
varredura de bins —, a conta dizia "**masterclipes**", e o duplo clique respondia *"o Media
Composer não está aberto"*.

⭐⭐ **A causa é de calendário, e vale como regra.** A aba nasceu em **20/09**, três dias
DEPOIS do porte (17/09), e passou inteira ao largo de `cicloassist/nle/`: chamava
`avid/escopo.py` direto. O CHAT já era NLE-ciente desde o porte
(`ferramentas/parecidos.py`, `mapa.py` → `nle.escopo_agora()`). ⇒ **Tela nova construída
depois de um porte não herda o porte** — e o sintoma não é erro, é resposta plausível do
projeto errado.

⛔⛔ **E a causa raiz era o painel não DIZER quem ele é.** `nle` ia em três chamadas
(`/conversar`, `/conversar/parar`, a batida da ponte) e em nenhuma da busca: o serviço não
tinha como saber. Agora vai em todas — no corpo (POST) e na query (GET).

⚠️⚠️ **Ler o editor de um pedido NÃO pode defini-lo** (`_nle_da_tela` contra `_qual_nle`).
O global é o editor do TURNO, e dele dependem a persona e o filtro de ferramentas: uma busca
na aba do Premiere virando esse valor no meio de um turno do Avid entregaria ao modelo as
ferramentas do editor errado.

| o quê | Avid | Premiere |
|---|---|---|
| recorte da busca | as bins do projeto (`avid/escopo.py`) | os arquivos do projeto (`nle/premiere.escopo_agora`) |
| índice de subclipes | `usage_code` da `.avb` | `Column.Intrinsic.SubclipStart` (`nle/premiere/recortes.py`) |
| a taxa do TC da fala | `mcapi.projeto()` | a **sequência ativa** (`timebase`) |
| duplo clique | `LoadMobsIntoViewer` (+ `OpenBin`) | `app.sourceMonitor.openProjectItem` |
| as palavras | masterclipe · Media Composer | clipe · Premiere (`PALAVRAS` no `painel.js`) |

⛔ **`openProjectItem`, nunca `openFilePath`:** o segundo IMPORTA o arquivo no projeto do
editor, e isto é um gesto de LEITURA que de propósito não passa pelo portão. ⛔ E "Record"
no Premiere é recusado com a frase: o equivalente é a sequência aberta, e pôr clipe nela é
escrita — virar um Source calado faria o editor achar que clicou errado.

⭐ **O Premiere não tem taxa de PROJETO; quem tem é a SEQUÊNCIA.** `fps = 254016000000 /
timebase` (o tick do Premiere), os dois como TEXTO — 254 bilhões não cabe em 32 bits. ⛔ Sem
sequência ativa, `None`: chutar 25 fps erraria todo material 23,976.

⛔⛔ **A janela do subclipe do Premiere NÃO sai do `getInPoint()`** (banco), que devolve o
master inteiro: sai de `SubclipStart`/`SubclipDuration` menos o TC do ARQUIVO. Quem usar o
in-point põe todo subclipe cobrindo a diária — e aí toda fala "cabe" em todo recorte, o
mesmo degenerado que o checker do mapa de corte já pagou para aprender. ⛔ E a chave é a
**já conhecida** (`identidade.chave_conhecida`), nunca a impressão medida na hora: 150
recortes seriam 150 decodificações de um minuto.

⛔ **O aquecimento do índice espera 20 s no Premiere contra 45 s no Avid**, e é de
arquitetura: lá o índice sai da PONTE, que é fila de um pedido por vez e é a MESMA do chat.
45 s segurariam a pergunta seguinte do editor atrás dele, e o sintoma seria "o painel
travou". ⚠️ **NÃO MEDIDO**: quanto `cicloRecortes` custa no Premiere de verdade — ele lê
`getProjectMetadata()` item a item, na thread principal dele, então o custo é congelamento
de UI. O host devolve `olhados` para o número aparecer no log.

⛔⛔ **E a tela MENTIA nos dois editores, achado ao dirigir o painel por CDP:** *"ainda
estou lendo os subclipes… procure de novo em alguns segundos"* saía sempre que não havia
índice — **inclusive sem projeto aberto**, quando ninguém estava lendo nada e procurar de
novo nunca mudaria a resposta. `recortes_possiveis` separa "ainda não" de "não há o que".

✅ **Conferido na tela**, a 400 px, com o painel dirigido por CDP fingindo estar no Premiere
(`__adobe_cep__` injetado antes dos scripts) e depois no Avid, com o cache e o projeto
REAIS: `drone` → 13 resultados dizendo *"a busca cobre TODO o cache"* e a dica *"monitor
Source do **Premiere**"*; no Avid, 10 resultados *"nas bins do projeto aberto (demonstracao,
203 masterclipe(s))"*.
⬜ **Falta o Premiere de verdade**: `app.sourceMonitor.openProjectItem` está no banco como
`hipotese`, e o índice de recortes nunca rodou contra um projeto com subclipes.
✅ A aba **Vetores** também passou a falar com o Premiere (2026-09-22) — ver
"Vetores no Premiere" mais abaixo.
