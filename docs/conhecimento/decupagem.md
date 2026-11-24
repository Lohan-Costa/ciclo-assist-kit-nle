# Decupagem: as duas camadas, o lote, a micro, a claquete

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐⭐ Duas camadas visuais, e elas respondem perguntas diferentes

| camada | responde | onde |
|---|---|---|
| **vetor** (MobileNetV2) | *"parecido com este quadro"* | `midia/vetores.py` |
| **decupagem** (o Claude olhando) | *"onde tem close noturno no consultório?"* | `midia/decupagem.py` |

⭐ **A decupagem é a camada rica, e ela já existe desde a fase 2** — o que faltava era
poder PROCURAR nela. Uma nota real do cache desta máquina cobre enquadramento (*close, do
peito para cima, leve contra-plongée*), figurino (*blusa vermelha de babados*), cenário
(*consultório, quadros ao fundo, abajur*), luz (*noite, luz baixa e quente*), câmera
(*parada*), o que a pessoa faz (*escuta · fala ativa*) e até a função do plano na cena
(*"cobertura de Personagem F na conversa com Eduardo"*).

⛔ **Prosa não filtra**, e por isso a nota tem cinco campos FECHADOS — `enquadramento`,
`angulo`, `camera`, `local`, `momento` — com sinônimos aceitos (`primeiro plano` → `close`,
`tripé` → `parada`) e valor inventado recusado com a lista na mensagem. O resto continua
prosa livre de propósito: emoção e intenção não cabem em enum.

⭐ **Nota SEM o campo cai para o texto.** Os campos nasceram depois das primeiras
decupagens; exigi-los teria feito o filtro devolver zero no dia em que nasceu, com o
material descrito bem ali. Quem tem o campo é comparado por ele; quem não tem, pelo que
escreveu.

⚠️⚠️ **A busca só alcança o que alguém JÁ OLHOU**, e toda resposta carrega o tamanho
disso ("3 mídias decupadas de 23"). Sem esse número, *"não achei"* vira *"seu material não
tem isso"* — e o editor acredita. ⚠️ E isso vale em dobro na **aba Busca** (acima): lá não
há modelo nenhum para dizer a frase.

⚠️ E "Personagem F" vem do roteiro ou da claquete, **nunca do rosto**. Não há reconhecimento
facial neste produto.

### ⭐⭐ Decupar em lote: o único gasto da assinatura do editor

`motor/decupador.py` põe o Claude para olhar quadros e escrever decupagem **fora da
conversa**, pela fila de fundo. Tudo o mais no produto responde a um pedido do editor;
isto trabalha enquanto ele monta — e por isso o preço é medido, mostrado antes do clique,
e a fila é interrompível.

**MEDIDO em 2026-09-11**, mídia real, Haiku 4.5, 6 quadros por mídia:

| | tokens/mídia | US$/mídia | s/mídia |
|---|---|---|---|
| 1 mídia por turno | 42.205 | 0,0254 | ~20 |
| **3 mídias por turno** | **16.818** | **0,0153** | **~10** |

⭐⭐ **O custo é do TURNO, não do conteúdo.** ~40 mil tokens são o piso de um `claude -p`
— prompt de sistema e maquinaria do CLI —, e só ~2,5 mil são os seis quadros e a resposta;
nosso catálogo inteiro de ferramentas é 3,4 mil. Daí `POR_TURNO = 3`: amortizar o piso é o
único lugar onde havia dinheiro a economizar. Para o projeto desta máquina (165 mídias com
imagem): **US$ 2,48 e 28 minutos**, dito na tela antes do clique.

⛔ **O modelo NÃO escreve a nota.** Ele poderia chamar `anotar_o_que_vi` sozinho — e aí
cada mídia acordaria o portão pedindo aprovação a quem está montando. Ele responde JSON, e
quem grava é o serviço, validando pelo vocabulário. Um par de olhos, não um agente com
permissão: `--allowedTools` tem **uma** ferramenta, e ela só lê.

⛔⛔ **Chave que ninguém pediu não vira nota.** Gravaria decupagem em cima da mídia errada,
e ninguém descobriria — a descrição seria plausível e a busca apontaria o plano errado
para sempre.

⚠️ E a decupagem de MÍDIA é mais grossa que a de TAKE: um master de quatro minutos pode ir
do geral ao close, e aí o modelo corretamente deixa `enquadramento` de fora. A nota de take
(escrita na conversa) continua sendo a precisa; `escopo: "midia"` distingue as duas.

⭐⭐ **A DENSIDADE: quantos quadros ele olha, e quem escolhe é o editor** (F3, 2026-09-22).
Seis quadros descrevem bem um plano e descrevem MAL um master de quatro minutos — e é o
editor quem sabe qual dos dois está mandando analisar. Três níveis na aba Vetores (6 · 12 ·
24), que valem nos DOIS motores e vão para a procedência da nota (`quadros_vistos`).
⚠️ O automático já existia e mora na MICRO (`micro.posicoes_do_trecho`, 3 a 8 quadros por
trecho conforme o movimento medido).

- ⛔⛔ **A conta do tempo é do MOTOR**, e confundi-los custou um número na tela: pelo Claude
  o custo é do TURNO (12 quadros em vez de 6 não dobram nada), pelo Mac o tempo É a
  inferência e cresce com as imagens. Aplicando a régua do Claude ao Mac, o painel anunciou
  **20 min para um trabalho de 3,1 h** — visto no print, invisível para teste de texto.
- ⛔⛔ **E o contexto do Ollama ACOMPANHA o pedido.** O que passa do `num_ctx` ele corta
  **calado**: o pedido não falha, o modelo é que vê menos do que foi mandado. Com 12.288
  fixo, 24 quadros (seis já são ~6,2 mil tokens) entregariam uma parte deles. O contexto
  cresce até 40.960 (o `num_ctx` do chat naquele Mac, medido) e o que não couber é cortado
  **aqui**, com o número real voltando na resposta e indo para a nota — e a tela diz
  *"22 quadros por mídia (o teto do Mac; você pediu 24)"*. Cortar aqui é uma decisão que se
  conta; cortar lá dentro, ninguém vê.
- ⚠️ **Só o nível padrão é MEDIDO.** Os outros são a conta do medido mais o tamanho de cada
  quadro a mais (~450 tokens por JPEG de 768 px, aritmética da fórmula de imagem — não
  medição nossa), e a tela escreve *"estimado em"* em vez de *"medido em"*. Medir com uma
  fila curta em `fino`, como o preço da claquete também espera.
- ⭐ O teto do chat subiu junto (12 → 24 em `ver_frames` e `ver_quadros_da_midia`): abaixo do
  que a fila pede, o editor pagaria por 24 e o modelo olharia 12, calado. O PADRÃO do chat
  continua 3 — lá cada quadro é contexto do turno de quem está esperando.
✅ **VISTO na tela** (Chrome a 400 px, cache real, 118 mídias): 3,1 h · 6,2 h · 11,4 h.

⚠️⚠️ Dois defeitos medidos ao construir: o CLI manda a resposta **duas vezes** (nos blocos
`assistant` e de novo no `result`), e concatenar as duas produz `{...}{...}` — 2 de 3
mídias falharam assim com "Extra data" numa resposta perfeita. E o gasto só é acionável
**aberto por tipo**: entrada fresca, cache lido e cache escrito não custam igual.

⛔⛔ **E uma mídia ilegível derrubava a FILA INTEIRA** (achado na revisão de 2026-09-22, e é
a mesma regressão que a revisão de 13/09 dizia ter consertado). `midia.quadros_de` devolvia,
na falha do ffmpeg, a forma de resposta da FERRAMENTA — uma lista de blocos MCP — em vez da
tupla `(jpegs, posições, clipe)` que ela promete. Quem chama desempacota três valores: no
chat o modelo recebia *"not enough values to unpack"* no lugar do motivo, e na fila do Mac
(`percepcao.decupar`, que desempacota igual) o `ValueError` não é nenhuma das exceções
tratadas em `decupar_em_lotes` e a **tarefa inteira morria**. O conserto de 13/09 cobriu o
caminho de um quadro por vez; o de `extrair_varios` ficou. ⭐ `extrair_varios` já levanta —
deixar subir é o conserto, e os dois caminhos que chamam tratam as três exceções.

⭐⭐⭐ **A decupagem MICRO: uma nota por TRECHO, com entrada e saída** (2026-09-22; plano
`~/.claude/plans/sobre-a-decupagem-hoje-luminous-rocket.md`, F0–F2 feitas).
⛔ **Complementa a macro, nunca a substitui** (decisão do editor: *"a macro é mais rápida"*).
A nota `escopo: midia` continua; a micro acrescenta `escopo: trecho` (`inicio_frames`,
`inicio_s`/`fim_s`, `planos`). Botão **"Decupar em trechos"** na aba Vetores; roda SÓ no Mac.
- **Onde cortar** (`midia/cortes.py`, estágio de cache `cortes`, `cortes.json`): a UNIÃO
  scdet ∪ pixel 64×36 medida na F0 (banco `transversal/deteccao-de-corte.md`): validação 12 de
  12, take contínuo de 12 min com 0 fronteiras em 14,5 s. Uma passada de ffmpeg (o scdet no
  stderr, a miniatura no stdout), EM FLUXO. ⛔ Centro do gradual: extensão pela escala de
  maior D, centro pela menor (fade: o quadro mais escuro); corte do scdet dentro de um
  gradual é a mesma transição.
  ⛔⛔ **E ele tem PRAZO** (revisão de 2026-09-22): era o único ffmpeg da casa sem nenhum —
  todos os outros rodam por `subprocess.run(timeout=…)`, este lê em FLUXO e esperava para
  sempre. O preço de um travamento aqui não é a mídia: a fila é **uma tarefa por vez**, e o
  editor ficaria sem poder analisar nada, com a barra em "correndo", até reiniciar o
  serviço. ⭐ O cão de guarda é de PARADA, não de duração (um arquivo de três horas leva
  minutos legitimamente, mas entrega quadro o tempo todo), e a conferência dele vem ANTES
  do teste de "nenhum quadro": morto no meio, `n` é maior que zero e a série está pela
  metade — aceitá-la gravaria fronteiras plausíveis de meia mídia como se fossem a mídia
  inteira, e ninguém as refaria.
- **Os trechos, montado E bruto** (decisão do editor): montado = um trecho por plano;
  bruto (zero corte seco) = "mudanças" (oclusão, a câmera que vai da porta à atriz) e a
  divisão pela AÇÃO (`MOVIMENTO_POR_TRECHO`, 10–60 s); trechos < 4 s são JUNTADOS (a Copa
  dava 77 trechos em 60 s). O primeiro trecho do bruto é a CABEÇA: lê a claquete.
- **A nota** (`motor/micro.py`): no montado, um quadro de cada plano e "descreva a sequência";
  no bruto, 3–8 quadros pelo movimento. `format: "json"` no Ollama (MEDIDO: 8 planos deram
  JSON quebrado sem ele). ⛔ Os quadros da cabeça vão PRIMEIRO (no fim, o modelo narrou "a
  claquete é mostrada de novo no final"). ⛔⛔ **Só a cabeça lê claquete**: um trecho do meio
  "leu" o EXEMPLO da instrução. E o exemplo não pode ser claquete do acervo (era A02·4·6·2, a
  do take medido — a medida não media nada; hoje X07·31·8·5).
- A claquete da cabeça **sobe para a nota macro** (onde a busca e o cartão a mostram), se
  lá não houver uma legível. A busca prefere a nota de trecho (tem POSIÇÃO: o duplo clique
  leva a agulha ao começo do trecho), e o cartão diz "trecho 00:18–00:47".
- ✅ MEDIDO no Mac (qwen3-vl): bruto ~50 s por trecho (~2,5 min de Mac por min de take);
  montado ~87 s por trecho de 8 planos (~16 min por min de peça). Claquetes lidas certo nas
  3 cabeças conferidas (A02·4·6·2, A01·4·4·1, A05·11·3·03).
- ⭐⭐ **F4 — a trama no chat: `o_que_acontece`** (`mcp/ferramentas/trama.py`). Pergunta do
  editor: *"o que está acontecendo neste material?"* → a linha do tempo do take, os trechos
  em ordem com as falas ditas em cada um. ⛔⛔ Tudo convertido para o **tempo do TAKE**: o
  offset do som NÃO é o da imagem (medido na C07: 0 contra 234 quadros). ⭐ O `segmento` de
  cada fala é o MESMO que `transcrever` numera e que `separar_falas` aceita — o modelo lê a
  trama e pede a fala sem converter nada. ⚠️ Não é resumo gravado (envelheceria calado); é
  composto na resposta, com o teto de saída do `transcrever` e `a_partir` para continuar.
  Sem micro feita, devolve a fala e diz o GESTO que falta. ✅ Conferido num take real do
  acervo: 2 trechos, 13 falas, claquete cena 11/plano 3/take 03.
- ⭐⭐ **Um vetor por PLANO** (2026-09-22): sem isto uma peça de 600 planos é representada
  pelos 12 quadros espalhados da amostragem, e `planos_parecidos` quase não alcança material
  de arquivo. A micro vetoriza o quadro do meio de CADA plano (só no montado) e
  ⛔ **ACRESCENTA** aos vetores existentes — a `ASSINATURA` não muda de propósito: mudá-la
  invalidaria os vetores das 332 mídias do cache por um ganho que só existe no montado.
  ⭐ A busca passa a devolver até 3 PLANOS diferentes da mesma peça (a regra de uma linha por
  mídia existia contra quadros vizinhos iguais, não contra planos), cada um dizendo
  "plano 38/74". ⭐⭐ E apontando um quadro de uma peça, sai só o PLANO de origem, não a peça
  inteira — "onde MAIS nesta peça?" é a pergunta. ⚠️ Sem o quadro de origem (o caminho
  antigo), a mídia inteira continua fora. ✅ MEDIDO na promo da Copa: 74 planos vetorizados
  em 14,4 s, e a busca devolvendo três momentos distintos dela.
- ⭐⭐ **O TEMPO antes do clique** (2026-09-22). A micro não gasta a assinatura, e por isso é
  fácil achar que é de graça: ela é a coisa MAIS LENTA do produto, e o notebook tem de ficar
  acordado o tempo todo (os quadros saem daqui). Duas populações na mesma lista: quem já tem
  `cortes.json` entra pelo número REAL de trechos, com bruto/montado gravado; quem não tem
  entra pela DURAÇÃO — e aí ⛔ **a tela mostra uma FAIXA, nunca um número**, porque bruto
  (50 s × ~3 trechos/min) e montado (87 s × ~11) diferem em 6×. Escolher um seria acertar
  por sorte, e errar para BAIXO faria o editor começar às 18 h um trabalho de nove horas
  achando que eram noventa minutos. ⚠️ Quem não tem duração medida fica FORA da conta e é
  contado à parte — somar zero por ele encolheria o total em silêncio.
  ✅ **VISTO na tela** (Chrome a 400 px, cache real): *"118 mídia(s) em trechos no Mac ·
  ≈ 14 h a 91 h · estimativa: 118 ainda sem cortes procurados…"*.
- ⬜ Falta: claquete de cauda, e ver a aba dentro do Media Composer.

⭐⭐ **A decupagem LÊ A CLAQUETE** (pedido do editor, 2026-09-22): rolo(s), cena, plano,
take, série e marcas (PICKUP) — ou `{"legivel": false}`, dito. `ler_claquete` valida (texto
do modelo é entrada não confiável) e grava com `fonte: claquete`; cena/plano/take lidos
valem nos filtros; o cartão da busca mostra "claquete A02 · C4 P6 T2" ou "claquete ilegível".
- ⛔ A amostragem normal EVITA as pontas (`frames.distribuir`) — é onde a claquete está.
  ⇒ 2 quadros da CABEÇA (1 s e 3 s) a **1568 px** (`midia.quadros_da_cabeca`, fora do cache
  de quadros), nos dois motores. Medido: a 768 px a claquete longe da câmera vira mancha.
- ⛔⛔ **O modelo copia o exemplo** (medido no qwen3-vl): "PICKUP" em 4 de 4 e, na claquete
  pequena, o exemplo INTEIRO em vez de "ilegível". E campo fora da lista da resposta não é
  respondido (`null` 4 de 4). ⇒ exemplo sem marca, campo na lista, e
  `conferir_a_claquete`: o rolo lido contra o do NOME do arquivo (`A009_…`) — não bateu,
  `hipotese` com aviso. Final: 3 de 3 legíveis certas, o chute pego.

#### ⛔⛔ E na fila grande o chute virou FATO: 44 notas (2026-09-23)

A primeira fila de verdade (537 mídias no cache, 100 leituras de claquete) mostrou o que 4
takes não mostram. **30 de 50 mídias com micro feita** devolveram o `31 · 8 · 5` do
EXEMPLO, e **44 notas** ficaram com a claquete em `hipotese` — **as 44 com cena/plano/take
no TOPO da nota**, que é onde a busca filtra e ordena, sem marca de dúvida nenhuma.

⇒ Eram duas falhas somadas, e nenhuma era a leitura:

- `_uma_nota` promovia os campos **antes** da conferência, que depois escrevia a dúvida só
  dentro do objeto `claquete` — onde nenhum filtro olha. ⇒ Hoje a promoção mora DENTRO de
  `conferir_a_claquete` e só acontece quando a leitura sobrevive: caminho que esquecer de
  conferir perde a promoção, que é a falha segura.
- `micro._subir_claquete` levava a leitura para a nota MACRO checando só `legivel` —
  **22 das 44** —, ou seja, subia justamente a que a conferência acabara de reprovar.

⛔⛔ **E conferir o rolo é necessário e INSUFICIENTE:** em **8 notas de 4 mídias** o modelo
leu o rolo CERTO (`A002_…` → `A002`) e copiou só o resto, passando por ela como fato.
⇒ `_ecoou_o_exemplo` compara a resposta com o próprio texto da instrução — e os valores
saem de `CLAQUETE` por regex, nunca copiados para uma constante ao lado: dois literais em
dois lugares divergem calados, e a conferência passaria a procurar o exemplo de ontem.

⭐⭐ **E o diagnóstico mudou ao ABRIR OS QUADROS** (`spikes/o_exemplo_que_o_modelo_copia.py`,
8 mídias no Mac). As 4 que "copiaram o exemplo" **não têm claquete nenhuma** — plano de
sala, ninguém com prancheta —, e as 4 de controle, com a claquete enchendo o quadro, foram
lidas **certas 4 de 4**. ⇒ **Ele não lê mal: ele inventa na AUSÊNCIA**, e o que inventa é o
que está escrito no prompt. `Sem claquete, omita. Nunca chute.` já estava lá e não bastou.
- ⛔ **`texto` é o campo mais contaminado:** o exemplo traz `"texto": "como está"`, e essa
  string voltou **inclusive nas leituras certas** — quem a usar como evidência do que foi
  lido está lendo o prompt de volta.
- ⛔⛔ **O eco não se limita ao bloco de exemplo.** Com os valores trocados por `‹cena›`, o
  eco de `31 · 8 · 5` foi a zero — e em **3 de 4** o modelo passou a devolver
  `rolo ["01-2"] · cena 01 · plano 2`, que é a FRASE SEGUINTE da instrução, escrita ali
  como explicação de notação. **Todo literal do prompt é material de cópia.**
- ⭐ O cartão da busca diz **"duvidosa"** (cor de alerta, motivo no title) na leitura
  reprovada: antes o chute tinha a mesma cara de uma leitura conferida.
- ⭐ Limpeza do que já foi escrito: `python tools/limpar_claquete_chutada.py [--fazer]`,
  **feita em 2026-09-23** — 26 mídias, 52 notas, **156 campos** fora dos filtros. Ela usa a
  função do PRODUTO como critério, e por isso é idempotente de verdade (a lição do
  `consertar_quadros`). ⛔ Nada é apagado: a claquete lida fica, com o aviso.
- ⛔⛔ **E o que JÁ foi reprovado continua reprovado**, mesmo que o critério de hoje o
  aprove: a instrução muda (o `31 · 8 · 5` saiu dela horas depois), e sem essa trava a
  passada seguinte devolveria aos filtros o chute que a limpeza tirou. É a armadilha do
  `consertar_quadros` de novo — critério que muda com o código.

#### ⭐⭐ A INSTRUÇÃO, refeita com medida (2026-09-23)

Três rodadas no Mac (8 mídias — 4 com claquete, 4 sem — `qwen3-vl:8b`), e cada pedaço do
texto de hoje é uma delas:

| instrução | eco do prompt | inventou onde não há | leitura perdida |
|---|---|---|---|
| a de 22/09 (`X07 · 31 · 8 · 5`) | **7** | 4 de 4 | 0 |
| sem exemplo nenhum, campos em prosa | 0 | 3 de 4 | ⛔ **4 de 4** |
| **a de hoje** (`‹cena›`, sem literal na prosa) | **0** | 4 de 4 | **0** |

- ⛔⛔ **Os campos não saem da ESTRUTURA JSON.** Descrevendo-os em prosa, as 4 claquetes
  legíveis voltaram VAZIAS — e não por não ver: o `texto` trouxe *"PRODUCAO-A / A01 ROLO
  4 CENA 2 PLANO 2 TOMADA / LOCAL-1…"*, a claquete inteira e certa, sem um campo preenchido.
  O banco já media isso em 22/09: campo fora da lista de campos não é respondido.
- ⭐ **O valor vira o LUGAR do valor** (`‹cena›`): copiar passa a ser uma resposta que se
  denuncia, e `_ecoou_a_instrucao` a pega sem depender do nome do arquivo.
- ⛔ **Nenhum literal na prosa:** a versão com `‹…›` que ainda explicava `"01-2"/"12A"`
  fez o modelo devolver `rolo ["01-2"] · cena 01 · plano 2` em 3 de 4.
- ⭐ E o `texto` virou TRANSCRIÇÃO (era `"como está"`, o placeholder, em toda leitura —
  inclusive nas certas). ⬜ Isso abre uma conferência que ainda não existe: cena/plano/take
  têm de aparecer no texto lido. Não foi feita — n=2 não calibra.
- ⚠️⚠️ **O que NÃO melhorou: ele continua inventando onde não há claquete** (4 de 4). O que
  mudou é a natureza do erro — de um mesmo valor plausível repetido em dezenas de mídias
  (30 no cache) para chute aleatório, que a conferência do rolo pega. ⬜ Fazer o modelo
  dizer *"não há"* continua em aberto; a rede é a conferência, não o prompt.
- ⚠️ A `PERSONA` passou de 2.200 para 2.425 caracteres (teto novo: 2.500) — ~60 tokens,
  0,15% do piso de um turno.

#### ⭐⭐ A fila rodada em 5 mídias reais com a instrução nova (2026-09-23)

O teste que fechou o dia, com os quadros conferidos A OLHO um a um. Duas coisas certas,
dois defeitos nossos achados aqui, e um limite assumido:

| mídia | tem claquete? | o que saiu |
|---|---|---|
| `…C005` | sim | ✅ `A01 · 4 · 2 · 2`, promovida, com o texto transcrito inteiro |
| `…C006` | sim (`A01 · 4 · 3 · 1`) | ⛔→✅ reprovada por OCR, aprovada depois do conserto |
| `…C002` | sim | ⛔→✅ `"CENA 1"` no lugar de `"1"` |
| `…C004` | sim (`4 · 2 · 1`) | ⚠️ leitura CERTA, reprovada: o rolo está coberto pela mão |
| `…C001` | **não** | ✅ inventou, e a conferência pegou |

- ⛔⛔ **O rótulo IMPRESSO na prancheta virava valor.** `"cena": "CENA 1", "plano":
  "PLANO 1", "take": "TOMADA 1"` — ele lê o que vê, e o rótulo está escrito embaixo de cada
  campo. Passou a conferência (o rolo batia) e foi para os filtros, onde procurar cena `1`
  não casa `CENA 1`. `_sem_rotulo` roda na entrada **e** na conferência, para a limpeza
  consertar o que já está gravado.
- ⛔ **E a confusão de OCR no rolo reprovava leitura certa:** a claquete escrita à mão diz
  `A01` (o zero parece um O), o modelo devolveu `AO1`, e a leitura INTEIRA caiu — com
  cena/plano/tomada certos. A comparação passou a desfazer `O`→`0` e `I`→`1` nos dígitos;
  o rolo LIDO fica como ele escreveu, e câmera errada continua reprovada.
- ⚠️⚠️ **O que ficou de fora de propósito:** com o rolo ILEGÍVEL no quadro (coberto), o
  modelo põe qualquer coisa ali e a leitura boa é reprovada. Tratar "rolo que não parece
  rolo" como *não li* aprovaria junto a invenção de `…C001` (`rolo 01 · cena 01 · plano
  geral`), que é o erro caro. ⇒ Fica conservador: a leitura é gravada e visível com o
  aviso, só não manda nos filtros.

#### ⭐⭐ O SEGUNDO acervo (*PRODUCAO-F*) quebrou tudo em volta da leitura

Claquete **digital, com timecode em LED e campos em INGLÊS** (`ROLL # A02 · SCENE 25 ·
SHOT 6 · TAKE 5`), material OP-Atom em `D:/Avid MediaFiles/MXF/010020260629`. Com luz boa
o modelo leu **os quatro campos exatos**; o que quebrou foi o nosso lado:

- ⛔⛔ **`A_0002C016_…` não casava com `_ROLO_NO_NOME`** — e sem referência no nome a
  conferência **não tem com que comparar e aprova o que vier**. O acervo novo chegava
  desprotegido justamente por ser novo. Hoje o padrão cobre `letra + `_`? + 3 a 4 dígitos`.
- ⛔⛔ **O modelo devolve o NOME DO ARQUIVO repartido nos campos** quando não consegue ler
  (claquete no escuro: `cena 260629 · plano 083016 · take h1DF4`, a data, a hora e o sufixo
  — com o TC do LED lido certo no `texto`). O nome vai no **cabeçalho do nosso pedido**,
  então é material de cópia como a instrução. `_ecoou_o_nome_do_arquivo` compara por TOKEN
  inteiro (a cena `4` está "dentro" de `03170345`), e ⛔ **o `rolo` fica de fora**: ele
  coincide com o nome por definição — a primeira versão reprovou `rolo A001` em
  `A001_0317…` e `rolo A02` num OP-Atom cujo sufixo de trilha é `_A02`.
- ⚠️ Rótulo impresso vira valor (`"SHOT 6"`), agora em PT e EN, e o `#` do `ROLL #`.
- ⚠️ Caligrafia: `A01`→`AO1` (o zero parece O) é perdoado na comparação; `A05`→`AuS`
  **não** — medido, perdoar o `U` aprovaria uma leitura cujos números estavam errados
  (`4 · 4 · 4` onde a claquete diz `11 · 1 · 1`).
- ⬜⬜ **E o achado que ainda precisa de material:** o rolo da CLAQUETE **não é** o cartão
  do ARQUIVO. Mesmo cartão `A_0002`, no mesmo dia: `C002` tem claquete `ROLL # A01` e
  `C016` tem `A02`. ⇒ "não bate" é dúvida legítima, não prova de erro — e neste acervo
  pode reprovar leitura certa. Nada mudado: decisão do editor, com mais amostras.

⚠️ **A dificuldade do QUADRO prediz o erro melhor que qualquer outra variável observada:**
claquete nítida → leitura exata; contraluz → colunas deslocadas (leu o SHOT no lugar da
cena); escuro → invenção.
- ⚠️ Preço: Mac medido, **~95 s por mídia** (era 62). Claude **ESTIMADO** em 20,5 mil
  tokens / US$ 0,019 por mídia (+2 imagens grandes) — **não medido**; é o preço que a tela
  mostra antes do clique, medir com uma fila curta.
- ⚠️ Claquete de CAUDA (no fim, de ponta-cabeça) não é olhada. E o que "série" significa na
  claquete ainda precisa do editor dizer como se marca.

⭐⭐ **O glossário da casa: `o_que_quer_dizer`** (2026-09-22). A planilha em que o editor
mapeia termos do audiovisual é a FONTE viva (`tools/importar_glossario.py --gravar` gera
`skills/glossario.json`); o chat consulta termo a termo (263 termos — carregar tudo gastaria
a janela). ⭐ A colheita: o que o modelo procurou e não achou, ou achou SEM significado (48
na planilha, entre eles "barriga", "kill de entrada", "sobe som"), fica em
`glossario_pendentes.json` na pasta de dados — `--pendentes` lista. ⚠️ As descrições vêm de
um dicionário da Bamboo Stock (dito na planilha): revisar antes de distribuir.

⭐⭐ **E o CHAT pode responder do Mac** (M2, 2026-09-16, em AVALIAÇÃO): `🖥 Qwen3-VL (Mac)`
no seletor de modelo, só com o endereço do Mac configurado. É o MESMO `claude -p` — portão,
MCP, `--restricted` —, com `ANTHROPIC_BASE_URL` no `/v1/messages` do Ollama
(`claude.ambiente_do_modelo`). Medido: tool call e portão funcionam; turno de ~11 mil tokens
contra 40.960 carregados; 135 s frio, ~10 s quente.
- ⛔⛔ `ANTHROPIC_API_KEY=ollama` e sem `ANTHROPIC_AUTH_TOKEN`/`CLAUDE_CODE_OAUTH_TOKEN`:
  senão o token da ASSINATURA do editor vai para o Mac.
- ⛔ Mac escolhido e sem endereço é `MotorIndisponivel`, nunca queda calada para o Claude.
- ⛔ Trocar entre Claude e Mac é conversa NOVA: o Ollama corta calado o que passar de 40.960.
- ⛔ O CLI inventa `contextWindow: 200000` e `costUSD` para o local: a janela vem do `/api/ps`
  e o dólar some. E a fila da decupagem pelo Claude nunca recebe o `ollama:…`.
- ⚠️ O 8B diz "a nota foi salva" depois de um `deny`: a mecânica segura, o texto engana.
- ⛔⛔ Na tarefa real (separar falas da C07) o Ollama devolveu `500 unexpected end of JSON input`
  depois de ~4 min, e o CLI repete até 10×. O painel agora mostra o pedido sendo escrito,
  a falha e "sem sinal há N" — antes era "pensando…" por 10 min. ⚠️ Com o Ollama a linha
  "escrevendo o pedido" NÃO aparece: ele retém o `tool_use` inteiro até o `</tool_call>`.
- ⭐ Causa da 500 (`spikes/o_500_do_ollama.py`, código do Ollama 0.33.3): o parser do Qwen
  faz `json.Unmarshal` no fechamento da marca e a falha cancela o pedido — o 8B fecha o
  `<tool_call>` sem a última `}`. E a ~8,8 tok/s um `separar_falas` leva 5 min sem byte:
  `API_TIMEOUT_MS=1800000` e `API_FORCE_IDLE_TIMEOUT=0` no ambiente do local, senão o CLI
  corta o pedido certo e repete.

⭐⭐ **Com o Mac configurado, a mesma fila decupa no Ollama dele** (`motor/percepcao.py`,
2026-09-13). `config.json` → `"ollama": "http://192.168.1.4:11434"` (ou
`CICLOASSIST_OLLAMA`); sem isso, tudo segue pelo Claude. Uma mídia por pedido,
`qwen3-vl:8b-instruct`, a MESMA `notas_da_resposta`, e a nota ganha `modelo` na
procedência. **Medido pelo serviço:** 68 s na primeira mídia (modelo frio, quadros
extraídos), ~6,9 mil tokens, zero assinatura; a tela diz tempo em vez de dólar.
- ⛔ Endereço só da rede local, e loopback recusado na rota E na leitura (tela azul).
- ⚠️ `conferir` antes da fila (responde? vê imagem?), e **3 mídias seguidas sem resposta
  encerram a tarefa** — Mac dormindo não pode virar a noite esperando 300 s por mídia.
- ⚠️ Os quadros saem do NOTEBOOK: ele tem de ficar acordado e com a mídia montada.
- ⬜ Falta o campo do endereço na engrenagem (hoje é o `config.json` na mão).
- ⛔ Revisão de 2026-09-13, com a primeira fila real correndo: (1) `ExtracaoFalhou` do
  ffmpeg não era capturada e UMA mídia ilegível derrubava a fila — pelo Claude a falha
  ficava dentro da ferramenta MCP, pelo Mac a extração é do notebook; (2) resposta não-JSON
  (proxy, roteador) escapava como `JSONDecodeError`; (3) `quadros_de` guardava quadros SEM
  a receita, e toda mídia decupada aparecia "↻ a refazer" na aba Vetores (100 de 108 na
  primeira noite). As três com teste; a (3) só vale para quadros extraídos depois do
  conserto — os da primeira noite precisam do carimbo (ver handoff).
