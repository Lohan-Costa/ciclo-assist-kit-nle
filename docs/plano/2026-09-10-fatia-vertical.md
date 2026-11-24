# Plano de arranque — fatia vertical, uma fase por vez

**Data:** 2026-09-10 · **Alvo:** Avid Media Composer 25.6 / Windows 11

A ordem existe por um motivo: **cada fase só começa quando a anterior provou o elo mais
arriscado**. Nada de painel bonito antes de saber que o subprocesso responde.

O produto são três funções, e só elas. Nada de aba Preparar, Conformar ou Entregar — o
guarda-chuva do `_ASSIST ANTERIOR` foi abandonado de propósito.

| função | o que o Claude faz | o que roda local |
|---|---|---|
| identificar material visualmente | **olha os frames** e descreve o plano | extração de frame (ffmpeg) |
| separar falas de uma cena | raciocina sobre o texto e agrupa por fala/take | ASR whisper.cpp + diarização onnx |
| corte zero | escolhe take e in/out, monta o plano | validação e autoração de AAF |

⭐ **A identificação visual é o lugar onde a decisão de arquitetura se paga sozinha.** Não
existe modelo de visão local no produto: o Claude *é* o modelo de visão, e o frame chega a
ele como conteúdo de imagem no resultado da ferramenta MCP.

---

## Fase 0 — spike do subprocesso ✅ CONCLUÍDA 2026-09-10

Subir `claude -p` com `--output-format stream-json` e imprimir os eventos. Sem painel, sem
MCP, sem Avid.

**Pronto quando:** os chunks aparecem em tempo real e o processo morre limpo.

**Resultado medido** (Windows 11, CLI 2.1.267): primeiro token em **2,12 s**, turno
completo em 2,14 s, `returncode 0`, `apiKeySource: "none"` — assinatura, sem chave.
Código em `spikes/fase0_subprocesso.py`.

Três achados, e os três viraram código ou regra:

| achado | consequência |
|---|---|
| Sem `--strict-mcp-config` a sessão herdou 3 MCP servers e 35 ferramentas da conta pessoal do usuário | ADR 0002 |
| Sem `stdin=DEVNULL` o CLI espera 3 s por stdin inexistente: 4,84 s contra 2,12 s de primeiro token, e o aviso só sai no stderr | comentado no spike; vale para o motor de produção |
| Console do Windows é cp1252 e qualquer acento derruba o processo com `UnicodeEncodeError` no meio da execução | `sys.stdout.reconfigure` no topo de todo entry point |

⚠️ **Achado que NÃO foi medido e continua aberto:** a validade do `setup-token` (ADR 0006).
Só se mede esperando. **Iniciar o relógio agora** para a resposta existir na fase 6.

## Fase 1 — uma ferramenta MCP de verdade ✅ CONCLUÍDA 2026-09-10

Servidor MCP em HTTP local, ligado ao gRPC do Media Composer em `[::1]:9100`. Registrado
com `--mcp-config` + `--strict-mcp-config`.

**Pronto quando:** o Claude responde uma pergunta que **só o projeto aberto sabe responder**.

Não é "a ferramenta foi chamada". É o editor perguntando *"quantos masterclipes tem a bin
de som da diária 2?"* e a resposta estar certa.

### ✅ Metade feita — o transporte (2026-09-10)

`spikes/fase1_mcp.py`. O servidor sobe em `127.0.0.1:7824`, o CLI conecta, o modelo chama
a ferramenta e o valor volta ao editor.

O teste usa um **carimbo sorteado quando o serviço sobe**, de propósito: uma ferramenta
que devolvesse algo derivável (a hora, uma conta) seria respondida certo sem chamar
ninguém, e o teste passaria sem provar nada.

```
mcp servers ..... [{'name': 'ciclo', 'status': 'connected'}]   ← exatamente 1, o nosso
ferramentas ..... ['mcp__ciclo__carimbo_do_servico']
resposta ........ '7762472c' == carimbo sorteado                ✓
turno ........... 6,05 s
```

Dois achados:

| achado | estado |
|---|---|
| `ThreadingHTTPServer` cospe traceback de `ConnectionResetError` (WinError 10054) a cada turno — o CLI fecha a conexão ao terminar, e isso é o fim NORMAL de uma conversa. Um traceback por turno treina o operador a ignorar o log | resolvido: `handle_one_request` engole só queda de conexão |
| O modelo chamou `ToolSearch` **antes** da nossa ferramenta: ela chegou diferida, não no prompt inicial. Custa uma ida e volta a mais em toda conversa | ⚠️ **por investigar** — importa mais quando forem 6 ferramentas |

### ✅ Metade da ponte — o Avid (2026-09-10)

`spikes/fase1_ponte.py`, contra o Media Composer **2025.6.58781** com um projeto real
aberto (1080p/23.976, 27 bins vivas + 1 na lixeira).

O gabarito é lido por nós direto do MC **antes** de perguntar, e a resposta é comparada
por conjunto. Um teste que aceitasse resposta plausível passaria com o modelo inventando
nomes de subclipe — e nome de subclipe é exatamente o que um modelo inventa bem.

```
pergunta ... liste TODOS os itens da bin C07 (não a C07_FALAS)
chamadas ... listar_bins → listar_itens_da_bin
resposta ... os 10 nomes, 0 faltando, 0 inventados        ✓
tempo ...... 13,9 s
```

⭐ **Uma previsão de desenho se confirmou na primeira execução:** o modelo passou o
caminho **absoluto** da bin — que é o que `listar_bins` tinha acabado de mostrar a ele.
E absoluto é justamente uma das três formas que o `GetListOfBinItems` recusa, com a
mensagem `"Bin is not open."` que manda depurar o estado da bin em vez do caminho. A
normalização dentro da ferramenta absorveu isso sem um turno perdido.

A lição generaliza: **o modelo passa de volta o que a ferramenta anterior lhe mostrou.**
Toda ferramenta que aceita um identificador precisa aceitar a forma que a nossa própria
saída ensinou — não a forma que a API de baixo nível prefere.

Armadilhas do banco respeitadas de saída, em `cicloassist/avid/mcapi.py`:

- piso de **~500 ms por chamada** — `projeto()` é cacheado na sessão; sem isso, ler 13
  bins gastava 6,5 s só reperguntando onde fica um projeto que não mudou
- `bin_relative_path` relativo à pasta do PROJETO, com subpasta
- lixeira filtrada por caminho (o `GetBins` não sabe filtrar), e `Trash` é em inglês
  mesmo num MC em português
- dois tetos separados: consulta 20 s, operação de arquivo 300 s
- `frame_rate` chega como `{num, den}` — guardado como fração exata **e** decimal;
  arredondar cedo é como se perde um frame a cada 1001

⚠️ **Não é achado novo, e vale dizer por quê:** errei o enum como `subClips`; o valor é
`subclips`, minúsculo — e o `.proto` do banco já registrava isso. O que funcionou foi a
mensagem de erro do nosso `_enum` **listar os válidos**, resolvendo em uma tentativa o
que uma mensagem genérica teria mandado investigar. Erro de quem chama merece a lista;
é barato de escrever e paga em toda chamada errada futura, inclusive as do modelo.

## Fase 2 — o painel ✅ CONCLUÍDA 2026-09-10

Chat em HTML, SSE até o serviço, resposta pintando token a token.

**Pronto quando:** o editor faz a pergunta da fase 1 **sem tocar em terminal**. É a
validação do produto inteiro, não de uma peça — e só o editor pode dá-la.

### O que já está de pé e medido (2026-09-10)

Um serviço só, acumulando os três papéis: serve o painel, expõe o MCP, orquestra o
Claude. Verificado por HTTP direto:

```
GET  /saude                    200  {"ok":true,"ui":"/painel","versao":"0.2.0"}
GET  /painel                   200  a página do chat
GET  /static/painel.css        200  6.484 bytes
GET  /static/../../VERSION     404  travessia de caminho recusada
POST /conversar (sem cabeçalho) 403  porteiro recusa quem não é o painel
POST /conversar (do painel)    200  SSE: inicio → limite → ferramenta ×3 → texto…
```

O turno completo pela rota do painel respondeu a pergunta da C07 com os 10 subclipes,
pintando token a token, com as chamadas de ferramenta visíveis enquanto aconteciam.

### ⚠️⚠️ A correção que quase virou código errado

O ADR 0005 original dizia "autenticar o painel pela origem `avpi://`". **Está errado
para o nosso desenho**, e o banco já tinha medido por quê (2026-08-09, MC 25.12).

Com o painel **servido pelo próprio serviço** (ADR 0007), ele é same-origin — e **um GET
same-origin não manda `Origin` nenhum**: o navegador só o envia em CORS e em POST.

⭐ **O modo de falha é desenhado para enganar quem depura:** o painel **carrega
normalmente**, os POSTs **funcionam**, e todo GET volta 401. O sintoma manda investigar
o serviço, quando o problema é o cabeçalho.

O cabeçalho certo é `Sec-Fetch-Site: same-origin` — *forbidden header* igual ao `Origin`,
então nenhuma página forja, e um site qualquer chega com `cross-site`. Corrigido no ADR
0005 antes de virar código, e fixado em teste para não voltar.

### O segundo porteiro, que o desenho anterior não previa

O subprocesso do Claude **não é navegador**: não manda `Sec-Fetch-Site` nem `Origin`. Se
a rota do MCP fosse `/mcp` e aceitasse qualquer POST em loopback, **uma página web aberta
no navegador do editor chamaria as nossas ferramentas** — hoje só de leitura, amanhã não.

Por isso a rota é `/mcp/<segredo>`, com o segredo sorteado a cada arranque e entregue só
ao subprocesso, dentro do `--mcp-config`.

### O `.avpi`, e o que a pasta de plugins ensinou

Três arquivos, 3.231 bytes: manifesto, loader e ícone. A interface não vai dentro do
pacote — ela é servida, então muda sem reinstalar nada (ADR 0007).

⚠️ **Achado da máquina:** os plugins instalados são nomeados **pelo id**
(`com.ciclomedia.delapraca.mc.avpi`, `com.orbita.sync.avpi`), não por um nome livre. O
empacotador passou a seguir isso — um nome diferente instalaria uma segunda cópia.

⚠️ E `com.ciclomedia.assist_anterior.mc.avpi` **continua instalado**, apontando para a porta
7823 que ninguém mais serve. Vai aparecer no menu Tools como entrada morta ao lado da
nossa. O empacotador avisa e **não apaga**: mexer em plugin instalado é decisão de quem
opera a máquina.

### ✅ Fechada dentro do Media Composer

O editor abriu Tools → Ciclo Assist, perguntou pelos subclipes da C07 e recebeu os 10,
com as chamadas de ferramenta aparecendo enquanto aconteciam. **Sem tocar em terminal.**

O modelo ainda avisou por conta própria que existem outras duas bins `C07_FALAS`, caso
fosse uma delas — comportamento que não foi programado e que vem da persona pedir para
dizer o que o editor precisa saber.

### As duas armadilhas que separaram "instalado" de "funcionando"

Nenhuma das duas estava no nosso código, e **as duas acusam a peça errada**. Vale registrar
o formato: *o mecanismo de proteção falha em silêncio e o sintoma aponta para o vizinho.*

**1. O gateway órfão servindo lista velha.** O painel não apareceu no menu Tools. Os
outros quatro apareceram — o que descarta a falha documentada no banco, em que o menu
inteiro some. O relógio explicou:

```
gateway subiu ....... 15:20:26      ← 30 min ANTES da instalação
plugin instalado .... 15:50:10
MC reiniciou ........ 15:52:38      ← PID novo (18060 → 18480)
gateway depois ...... MESMO PID 19564, ainda de pé
```

O órfão serviu a lista de plugins de 15:20. Tudo parecia normal, só o nosso faltava — e
por isso gastei tempo comparando manifesto, ZIP e schema, todos corretos. **A regra segura
de instalação passou a ser: fechar o MC → matar o gateway → instalar → abrir.**

⚠️ Isso contradiz a timeline que o banco mediu no macOS (o órfão morreria em 5–8 s). Aqui
sobreviveu 32 minutos e um restart, continuando o único gateway do sistema. Registrado lá,
com a ressalva de que **não foi instrumentado** se é diferença de plataforma ou de versão.

**2. CORS no `GET` do loader.** O painel abriu e disse *"o serviço não está rodando"* —
com o serviço rodando e respondendo `curl`. As conexões do painel apareciam em `TIME_WAIT`
do lado do serviço: o TCP acontecia, o servidor respondia 200, e **o browser recusava
entregar a resposta à página** por faltar `Access-Control-Allow-Origin`.

⭐ O `fetch` rejeita igual para *não conectei* e para *conectei e não pude ler*, e o
loader tem um `catch` só. Ele exibiu a única mensagem que tinha, e ela mandava procurar no
lugar errado.

Corrigido ecoando a origem exata `avpi://` — **nunca `*`**, que abriria o serviço local
para qualquer aba do navegador do editor. Fixado em teste, e registrado no banco.

### Dois acertos de acabamento, depois de ver na tela

- **`ToolSearch` sumiu da lista de ferramentas.** É ferramenta interna do CLI procurando
  as nossas; mostrá-la dizia ao editor que algo aconteceu no projeto dele quando não
  aconteceu. O painel relata ação sobre o material, não a mecânica do motor.
- **Markdown renderizado.** O modelo escrevia `**CENAS\C07.avb**` e tabelas que não
  cabem em 400 px. A persona passou a dizer a largura do painel e a proibir tabela; o
  renderizador é a rede de proteção, construído com `createElement`/`textContent` —
  **nunca `innerHTML`**, porque o texto carrega nome de arquivo do cliente (ADR 0005).

⭐ **Para iterar na interface:** botão direito numa área vazia do painel → **Reload**.
Fechar e reabrir pelo menu Tools **não** recarrega — a página fica em cache, e foi isso
que travou um ciclo de teste inteiro no projeto anterior.

## Fase 3 — aprovação dentro do painel ✅ CONCLUÍDA 2026-09-10

**Pronto quando:** uma ação destrutiva vira botão no painel e o **não** é respeitado.
Verificado nas duas direções, pelo caminho real do painel (`spikes/fase3_painel.py`).

### O contrato, medido e não presumido

O `--help` não diz o que a ferramenta de permissão recebe nem o que deve devolver.
`spikes/fase3_permissao.py` descobriu (CLI 2.1.267):

```
chega   {"tool_name": "mcp__ciclo__…", "input": {…}, "tool_use_id": "toolu_…"}
espera  {"behavior": "allow", "updatedInput": {…}}
   ou   {"behavior": "deny",  "message": "…"}
```

No `deny` a ferramenta **não roda** e a recusa aparece em `permission_denials` do evento
`result`. O modelo explica ao editor em vez de tentar contornar.

### A arquitetura que o portão obrigou

O pedido chega por um caminho e a resposta vem por outro:

```
claude -p  ──POST /mcp/<segredo>──→  pedir_confirmacao   (thread A, BLOQUEIA)
                                            │ empurra na fila
painel     ←──SSE de /conversar──────  fila de eventos   (thread B)
   │
   └────────POST /responder────────→  destrava a thread A
```

⚠️ **É por isso que o motor deixou de ser consumido como gerador direto pela rota SSE.**
Do jeito anterior não havia por onde injetar o pedido no meio da resposta — ele chega de
outra thread, disparado pelo subprocesso. Agora o motor roda numa thread e escreve numa
fila; a rota drena a fila; o portão escreve na mesma fila.

⚠️ **Um turno por vez, e isso virou regra explícita.** A chamada de `pedir_confirmacao`
**não diz de que turno ela é** — o CLI manda `tool_name`, `input` e `tool_use_id`, e nada
mais. Com dois turnos vivos, uma aprovação poderia ser roteada para o painel errado e o
editor aprovaria uma ação que não viu. Recusar o segundo turno é mais honesto que
adivinhar.

### As duas metades da regra

- **A leitura nunca pergunta.** Sete ferramentas na allowlist. Um editor que clica
  "permitir" quinze vezes para listar uma bin para de ler o que clica — e aí a pergunta
  que importava passa batido.
- **A escrita sempre pergunta.** Hoje uma só: `anotar_o_que_vi`.

### O que não pode virar "sim" por descuido

Cada um destes é um caminho que poderia liberar sem alguém ter clicado, e cada um tem
teste:

| caminho | resposta |
|---|---|
| ninguém respondeu no prazo | **recusa** — silêncio não é consentimento |
| o editor fechou o painel no meio | **recusa**, e solta a thread |
| não há turno ativo (sem painel escutando) | **recusa** — ação sem dono não acontece |
| clicar duas vezes | a primeira decisão vale |

### O cartão

Mostra o que **vai acontecer**, não a mecânica: *"Posso guardar a descrição de um take?"*,
com os argumentos legíveis, e não `mcp__ciclo__anotar_o_que_vi` com JSON. O botão **Não**
vem antes na ordem do DOM — quem navega por teclado alcança primeiro o gesto de menor
consequência.

### E o mapa do material ficou completo

O portão destravou o que faltava para *"mapear tudo o que acontece no vídeo"*: além dos
quadros, o cache agora guarda **o que o Claude viu**. Duas ferramentas novas:

- `anotar_o_que_vi` (escreve, passa pelo portão) — grava descrição e etiquetas
- `ler_o_que_ja_sabemos` (lê, livre) — devolve o que já se sabe **e o que se sabe de
  outros trechos do mesmo material**, que é justamente a pergunta de um assistente

⭐ A nota mora no cache do **master**, pela mesma regra dos quadros: um groupclipe de
multicam montado depois encontra a descrição pronta, e refazer um subclipe não apaga o
que já se sabia daquela mídia.

⚠️ Reanotar o mesmo trecho **substitui** em vez de acumular: guardar as duas faria o
Claude ler descrições contraditórias do mesmo material sem saber qual vale.

## Fase 4 — conversa que dura ✅ CONCLUÍDA 2026-09-10

**Pronto quando:** fechar e reabrir o projeto recupera o fio da conversa. ✅ Verificado
matando o serviço e subindo outro — a pergunta seguinte retomou o fio, sem ferramenta
nenhuma.

### O ganho, medido

| | antes | agora |
|---|---|---|
| 2º turno seguido | processo novo, ~2 s só de partida | **1,24 s** |
| ferramentas no 2º turno | repetia a consulta ao Avid | **zero** — ele lembrava |

O segundo turno (*"e quantos deles são do plano 3?"*) não disse qual bin, não chamou
ferramenta nenhuma, e acertou. A conversa poupa latência **e** idas ao Media Composer.

### ⚠️⚠️ `--session-id` e `--resume` não são intercambiáveis, e errar é silencioso

Medido:

| | id que JÁ existe | id que NÃO existe |
|---|---|---|
| `--session-id` | ⛔ **começa conversa nova, sem erro** — o fio some calado | cria |
| `--resume` | retoma | falha limpo: `No conversation found with session ID` |

⇒ **Sempre `--resume` primeiro, com queda para `--session-id`.** O erro do `--resume` é
honesto e barato; o do `--session-id` é invisível e custa a conversa inteira do editor.

⭐ **E assim não guardamos estado nenhum:** quem sabe se a sessão existe é o próprio CLI.
Uma fonte de verdade, não duas.

### O id é derivado, não sorteado

`uuid5` do caminho do projeto, normalizado (minúsculas, sem barra final). Abrir o mesmo
projeto amanhã dá o mesmo id — e no teste isso se provou sozinho: a sessão lembrou de um
número guardado pelo **spike**, horas antes, porque o spike derivou o mesmo id do mesmo
caminho.

⚠️ A normalização não é zelo: no Windows `C:\X` e `c:\x\` são a
MESMA pasta, e sem ela o editor ganharia duas conversas para um projeto só, sem nada
indicando por quê.

### ⭐ A medição que o ADR 0004 pedia deixou de ser necessária

Ele pedia medir **quanto tempo o CLI aguenta ocioso** antes de encerrar. Não é preciso:
tratar a morte do processo como **rotina** e ressuscitar com `--resume` cobre o ocioso, o
travamento do MC e o reinício do serviço **com o mesmo código**.

Um desenho que não depende do número é melhor que o número — e não envelhece quando o CLI
mudar o timeout.

## Fase 5 — as três funções

Só agora. As quatro fases anteriores são encanamento; esta é o produto.

### 5.0 · `resolver_take` — a camada de tradução ✅ 2026-09-10

Spec e medições: [`../spec/2026-09-10-resolver-take.md`](../spec/2026-09-10-resolver-take.md).

A peça de que 5a e 5b dependem. Traduz um subclipe do Avid no endereço físico do take:
arquivo de vídeo, canais do som direto, ponto de entrada **de cada master**, e cena/plano/
take partidos da claquete. Os 10 takes da C07 resolvem em **0,12 s** — contra ~500 ms de
uma única chamada de API.

⭐ **A regra que saiu daqui e vale para o produto todo:** *para LER, o arquivo; para saber
o que está aberto ou para ESCREVER, a API.* Ler o `.avb` com pyavb é instantâneo e
invisível; a alternativa custa o piso de latência e **abre a bin na tela do editor**.

Três defeitos achados e travados em teste:

| defeito | por que passaria despercebido |
|---|---|
| `_` é caractere de PALAVRA, então `\b` não dispara entre `C07` e `_P02` | casava no nome do som (espaço) e falhava no do subclipe: **9 de 10 takes passavam** e o décimo caía em "não reconhecido" sem explicação |
| `Fraction` atravessando até a saída | `round(frames/Fraction)` é exato e **não serializável**; derruba o `json.dumps` do resultado da ferramenta |
| `json.loads` sobre BYTES levanta `UnicodeDecodeError`, que **não é** `JSONDecodeError` | o `except` óbvio não pega, e o serviço respondia **500 "falha interna"** para entrada torta do cliente — culpando a si mesmo |

E dois achados sobre o material, que o produto passou a dizer sozinho:

- **Cada take tem um offset de som diferente** (182, 177, 230, 237, 299, 234, 180, 176,
  164 frames nos nove sincronizados). Não existe "o offset do take" — por isso `imagem` e
  `som` são blocos separados, cada um com o seu.
- **O `C07_P02-T001.1` não tem som direto:** o áudio vem do scratch da câmera, 2 canais, e
  o clipe tem 8 frames. O `resolver_take` detecta e avisa, porque transcrever scratch dá
  texto ruim e uma consumidora que não soubesse apresentaria com a mesma confiança.

⭐ **Validado de ponta a ponta pelo painel:** perguntado "resuma o que existe na bin C07",
o Claude chamou `resolver_take` dez vezes e respondeu com os três planos, os dez takes, e
*"a exceção é C07_P02-T001.1 … provavelmente sobra de corte"*. É o comportamento que a
camada de tradução existe para permitir.

⚠️ **Otimização já visível:** dez takes = dez idas e voltas ao MCP. Uma `resolver_bin` que
resolva a bin inteira de uma vez cabe, e o modelo pediria naturalmente por ela.

### 5a · Identificar material visualmente ✅ 2026-09-10

`ver_frames(bin, item, quantos)` extrai quadros e os devolve como **imagem** no resultado
MCP. Não há modelo de visão no produto: **o Claude é o modelo de visão**. É a decisão que
tornou desnecessária a LLM local que o projeto anterior perseguia.

⭐ **Validado pelo painel.** Perguntado "olhe o take C07_P02-T004 e descreva o que
acontece", o Claude pediu 8 quadros por conta própria e devolveu uma decupagem de verdade:
meio-close em contra-plongée, ator deslocado à esquerda, cadeira de palhinha à direita,
cortina branca, luz baixa e quente. E o arco da interpretação ao longo do take — aponta
argumentando, franze a testa, leva a mão ao peito, termina encarando fora de quadro.

Custo: **0,25 s** na primeira vez, **0,05 s** na segunda. 768 px, ~20 KB por quadro.

#### ⭐⭐ O cache é endereçado pelo UMID do MASTER

A regra veio de um módulo que já rodou em produção
(`_ASSIST ANTERIOR/assist_anterior/transcricao/store.py`) e vale igual para quadros:

> O hash do arquivo exige ter o arquivo; **o UMID vem de dentro do clipe**. Processou uma
> vez, e qualquer clipe que use aquele material acha pronto — masterclipe, subclipe,
> **groupclipe (multicam)**, e subclipe criado DEPOIS do processamento.

⭐ **E há um segundo lado, para quadros: o número do quadro é contado no tempo do
MASTER**, nunca no do subclipe. Dois recortes vizinhos da mesma diária compartilham a
sobreposição. Numerar em tempo de subclipe faria o mesmo quadro ser extraído uma vez por
recorte — e o cache *pareceria* funcionar sem nunca acertar.

Confirmado em disco: a pasta é o UMID do **mastermob** (`…01010d43…`), não o do subclipe
(`…01010f20…`), e os quadros saem numerados `00001357`, `00002715`, `00004072`.

```
%LOCALAPPDATA%\CicloAssist\midia\<umid-64hex>    fonte.json              ← master, arquivo, taxa: o diretório legível por humano
    gerador.quadros.json    ← com que receita foi feito
    quadros\00001357.jpg    ← posição em tempo do MASTER
```

Três propriedades herdadas do sidecar do Decupador, cada uma paga por um defeito medido:
**um diretório por mídia** (sem banco central — o compartilhamento é SMB, onde lock não é
confiável), **escrita atômica** (temporário + `os.replace`), e **leitura defensiva** —
cache corrompido vira "não tenho isso", nunca exceção. Reprocessar custa segundos;
estourar custa a conversa do editor.

⛔ **E o cache NÃO mora ao lado da mídia.** Mídia gerenciada pelo Avid não tem "lado".

#### Duas decisões de amostragem

- **768 px, não 4K.** O Chat Video Pro manda PNG 3840×2160 ao modelo (medido pelo banco,
  `CVP_PNG_Preset`). Não copiamos: 4K estoura contexto e custo sem melhorar a resposta a
  *"o que há neste plano"*. É comparável se um dia houver dúvida.
- **Nunca as pontas do take.** O primeiro quadro costuma ser claquete ou resto do plano
  anterior; o último pega o corte. Amostrar as pontas faz o modelo descrever o que o take
  **não é** — e com confiança, porque a imagem é real.

⚠️ **Fora de escopo, e de propósito:** busca semântica visual por texto. O MC 2025 já
embarca isso (`AvidSemVisV1.onnx`) — não é diferencial nosso.

⬜ **O que falta para "mapear tudo o que acontece no vídeo":** guardar no cache **o que o
Claude viu**, não só os quadros. A pasta já tem lugar para isso. Mas gravar a descrição é
uma ESCRITA, e escrita passa pelo portão de aprovação — ou seja, depende da fase 3.

### 5b · Separar falas de uma cena 🔶 TRANSCRIÇÃO FEITA 2026-09-10

`transcrever(bin, item)` roda ASR local sobre o **som direto** — é ele que tem claquete.

**Motor:** `faster-whisper`, modelo `small`, `int8` na CPU. Roda em CTranslate2, **não em
torch** (a regra da stack), e é o **mesmo motor que o Media Composer 2025 embarca** — o
que é validação independente de que dá conta deste material.

```
1ª vez  19,4 s   (mixagem dos 5 canais + ASR de um take de 3min46)
2ª vez   0,03 s  ← 627× mais rápido, do cache
```

⭐ **A transcrição é do MASTER inteiro, em tempo do MASTER**, pela mesma regra dos
quadros. O recorte da janela do subclipe é conta de lista.

#### ⭐⭐ A claquete está no ÁUDIO — terceira fonte, de graça

O ASR capturou o técnico de som cantando a claquete:

```
 3,12 →  5,12   Atenção, silêncio!
 6,66 → 10,94   Cena 7, plano 2, tomada 4.
```

O design de 25/08 previa duas fontes para a Camada 1 — o **nome do arquivo** do som e o
**roteiro**. Esta é uma terceira, independente das duas, e ela chega sem custo nenhum:
já está no áudio que se transcreve de qualquer jeito.

⚠️ **E ela explica o offset.** O som entra em 234 frames (9,76 s) porque o master começa
antes, na claquete. A fala "Cena 7, plano 2, tomada 4" vai de 6,66 s a 10,94 s — ou seja,
**atravessa o in-point do take**. É exatamente por isso que `recortar` inclui quem cruza a
borda: descartá-la jogaria fora a confirmação de qual take é aquele.

#### Os dois relógios, e por que ambos

Cada fala volta com `inicio_no_take` **e** `inicio_no_master`. O do take é o que o editor
lê e o que casa com o monitor; o do master é o que casa com a transcrição guardada e com
qualquer outro recorte da mesma mídia. Entregar só um obrigaria o modelo a converter — e
converter taxa fracionária é onde se perde frame.

#### ⭐ Validado pelo painel, e além do previsto

Perguntado "compare os takes C07_P03-T001 e T002: o que se fala em cada um, e qual está
mais completo?", o Claude transcreveu os dois e respondeu com uma decupagem de verdade —
a cena é uma sessão de terapia, quem são, o que se discute. E então:

> *"O T002 começa igual, mas cai cedo. Aí a gravação trava: alguém no set fala «não dá,
> tem um homem gritando aí». O take é abortado por barulho externo. Pouco mais de 1 minuto
> aproveitável."*

⭐ **Isso é a Camada 3 acontecendo sozinha, e melhor do que o design previa.** O spec de
25/08 escolhia take por heurística — duração coerente com a mediana, transcrição não
vazia. Aqui o modelo **leu o motivo** do descarte na própria gravação. Heurística chuta;
isto sabe.

#### 🔶 A bin de falas — construída em 2026-09-13

`separar_falas`: uma timeline por fala (`C07_FALA03`, `.02` para variante), trecho de cada
take, com ou sem roteiro, conferida contra as transcrições ANTES do cartão. Medida na C07
real: honesto 0 reprovado, degenerados todos pegos. Ver CLAUDE.md, "Separar falas".
⬜ Falta o teste pelo chat com o Media Composer aberto.

O alinhamento take contra take ficou com o **modelo**, não com código (a inversão do
repo): ele lê as transcrições e propõe a espinha; o código confere. O `espinha.py` do
`_ASSIST ANTERIOR` fica como referência se a conferência mostrar que o modelo não dá conta.

#### ⬜ O que falta para fechar a 5b

- **Transcrição por canal.** Com lapelas, cada canal é uma pessoa — transcrever por canal
  **já é** a separação de falantes, sem diarização nenhuma. Decidido em 2026-09-10 fazer a
  mixagem primeiro e os canais depois.
- **Alinhamento por região** (design de 25/08): trecho que casa, trecho que diverge, e a
  distância como marcador de improviso. Sem roteiro, take contra take.
- **O plano da bin de falas** — que é escrita, e portanto passa pelo portão.

⚠️ **O metadado de canal desta produção é a "condição C" do banco**, e ele previu a
armadilha: a bin não tem nomes `TRK`, mas tem uma coluna própria
`GA Personagem: "MIC2=Personagem F; MIC3=Eduardo"` — um mapa que **aponta para nomes que a bin
não tem**. Sem outra fonte, não dá para saber qual posição é MIC2. A transcrição por canal
vai precisar resolver isso, e o banco já diz como: gravar também a POSIÇÃO.

### 5c · Corte zero ✅ 2026-09-10

Spec em [`../spec/2026-09-10-corte-zero.md`](../spec/2026-09-10-corte-zero.md).
`montar_corte` recebe um plano, valida, passa pelo portão, autora a `.avb` e abre a bin.

⛔ **A rota de `ExportFile`/`ImportFile` foi DESCARTADA pelo autor**, e a razão vale além
desta fase: ela depende de **preset**, que é configuração do usuário — e o nome do preset
mente (um chamado "AAF" exportava WAVE e fez o MC renderizar 26 minutos de áudio). Um
produto instalado na estação de um cliente não pode ter o resultado decidido por uma
preferência que ele não controla.

A rota é **autorar a `.avb`**, idioma portado de `sequencia.py`/`translate.py`, com
round-trip contra o Media Composer confirmado pelo autor: a timeline abre, toca, a V1 vem
ligada, e o recorte parcial cai no frame certo.

⛔⛔ **A lição que o porte quase perdeu:** o trail `Filler` é **incondicional e
ESTRUTURAL**, não uma questão de duração. O Avid afirma
`Assertion failed: CompIsFiller(last)`, e sem ele o MC recusou **sete** timelines em
2026-08-29. A invariante de duração já é satisfeita por construção — foi confundir as duas
e podar o que parecia sobrar que custou a bin inteira. Copiei sem podar.

#### O plano é a fronteira, e a recusa é atômica

Item malformado derruba o plano **inteiro**, e a mensagem diz **qual** corte e **o quê**.
O validador recusa duração fracionária como erro de unidade (segundo no lugar de frame),
vocabulário de procedência fora da lista, e — a que mais importa — **corte sem `porque`**.

⭐ `hipotese/heuristica` diz o **grau** da incerteza, não o **motivo** da escolha. O editor
aprova corte a corte e decide pelo motivo.

#### ⭐ Validado pelo painel, e o resultado mostra a arquitetura se compondo

Pedido *"monte um corte zero curto da cena 7 com dois takes do plano 3"*, o Claude
encadeou sozinho: `resolver_take` → `ler_o_que_ja_sabemos` → `transcrever` →
`ver_frames` → `anotar_o_que_vi` (pelo portão) → `montar_corte` (pelo portão).

O plano que ele propôs:

```
1. C07_P03-T001 · in 180 · 192 frames · confirmado/claquete
   "Começo em 180 frames = 7,5s, logo depois da claquete «7, 3, tomada 1»
    (que fecha em ~5,4s) e do «Silêncio!», já na primeira fala."
2. C07_P03-T003 · in 168 · 192 frames · confirmado/claquete
   "Deixei o T002 de fora: tem só 65s e a tomada foi abortada por barulho
    no set («tem um homem gritando aí»)."
```

⭐⭐ **Ele usou a claquete CANTADA NO ÁUDIO — o achado da fase 5b — para posicionar o
in-point depois dela.** Nada no produto manda fazer isso; caiu da composição das peças. E a
conversão de 8 s para 192 frames a 23,976 saiu certa.

#### ⬜ As skills ficam para depois

`.claude-plugin/` + `skills/` carregadas com `--plugin-dir` é onde a convenção de nome de
cada produção vira conhecimento editável. Entra quando houver uma skill real para carregar
— hoje seria andaime sem nada dentro.

## Fase 6 — instalação para não-técnico 🔶 CONSTRUÍDA, falta alguém de fora

**Pronto quando:** alguém de fora instala sozinho. Só uma pessoa que não seja o autor
fecha esta fase.

`INSTALAR.bat` (duplo clique) → `instalar.ps1`, seis passos com o padrão da casa: `.bat`
sem acento nenhum porque o `cmd.exe` lê na codepage do console, `.ps1` em UTF-8 com BOM,
e **nunca um `exit` seco** — a janela fecharia levando a mensagem de erro junto.

### ⭐ O login é `claude auth`, não `setup-token`

Correção do ADR 0006, medida:

```
claude auth status  → JSON: loggedIn, authMethod, subscriptionType, email
claude auth login   → conduz o login
```

O `auth status` é **instantâneo e não gasta nada da assinatura** — a alternativa óbvia
era mandar uma pergunta qualquer só para descobrir se há login, e ela custa um turno do
editor. De quebra ele diz o plano, o que permite avisar quem paga por token.

⚠️ E isso **apagou um risco em aberto**: a validade do `setup-token`, que o ADR 0006
mandava medir antes desta fase, deixou de importar — não é mais o mecanismo.

### Os três estados do Claude, que o instalador distingue

| estado | o que ele diz |
|---|---|
| nenhum Claude | o que é, e que o produto não tem inteligência própria |
| **app sem CLI** | *"a sua conta já serve — falta este segundo programa"* |
| CLI sem login | abre o `claude auth login` ali mesmo |

⭐ O do meio é o que mais vai acontecer, e é o que menos parece erro: quem instalou o app
tem o Claude aberto na tela e paga a assinatura.

### ⛔⛔ A ordem de instalação do painel virou passo do instalador

Ele **exige o Media Composer fechado** e mata o `avid-api-gateway` antes de instalar. Sem
isso o gateway serve uma lista de plugins velha: o menu Tools aparece completo, com todos
os painéis MENOS o recém-instalado, e nada acusa erro. Custou uma depuração inteira em
2026-09-10, e agora está na mão do instalador em vez de na memória de quem instala.

### O serviço sobe sozinho

Um atalho na Inicialização, apontando para um `.vbs` de uma linha.

⚠️ `.vbs` e não `.bat` porque um atalho para `.bat` **pisca uma janela preta a cada
logon** — e um serviço que assusta no primeiro dia não sobrevive ao segundo. Reversível:
apagar o atalho.

Sem isso o editor abre o MC, clica em Tools > Ciclo Assist, e o painel diz *"o serviço
não está rodando"* — que é verdade, e é culpa nossa por não ter subido.

### ⬜ O que falta

- **Alguém de fora rodando.** É o critério, e ele não se cumpre sozinho.
- ✅ **O fluxo de primeira vez do login** — exercitado em 2026-09-10 com
  `CLAUDE_CONFIG_DIR` apontado para pasta temporária, o que dá um `loggedIn: false`
  verdadeiro **sem deslogar ninguém**. Os dois estados conferidos por
  `instalar.ps1 -Conferir`. Só a tela de login em si (do próprio Claude Code) segue sem
  exercício.
- **Python como pré-requisito.** Hoje o instalador exige que o editor instale o Python.
  O `requirements.txt` já diz que a stack é stdlib pensando no PyInstaller — empacotar um
  `.exe` tira esse passo, e é o maior salto que falta para o não-técnico.
- **Fallback de chave de API** para quem não tem assinatura (ADR 0001).

## Fase 7 — endurecimento ✅ CONCLUÍDA 2026-09-10

**Pronto quando:** existe um documento de ameaças e as escolhas estão registradas.
→ [`../ameacas.md`](../ameacas.md), e **32 testes** travando as defesas que ele descreve.

⭐ Um documento de ameaças que descreve proteções sem testá-las é prosa. Cada seção dele
tem caso de teste, e dois achados vieram de escrevê-lo.

### ⭐⭐ O item nº 1 não é técnico: o material do cliente SAI da máquina

Não há modelo local. O Claude **é** o modelo, e para responder sobre o material ele
precisa recebê-lo. Medido: uma chamada de `ver_frames` com 2 quadros manda **52 KB de
imagem do material** no corpo da conversa; `transcrever` manda a transcrição inteira.

Vai para a Anthropic, pela conta do **próprio editor**. Não passa por servidor nosso —
não temos servidor. O arquivo de mídia, a bin e o projeto **não** saem.

✅ **Virou a primeira tela do instalador**, antes de qualquer passo, com sim explícito e
saída limpa no não. Consentimento depois de instalado não é consentimento.

⬜ Falta na página de vendas — obrigação de quem for vender.

### Dois defeitos achados na auditoria

| achado | por que passaria |
|---|---|
| **`CON`, `NUL`, `COM1`… viravam nome de arquivo** | não são arquivos no Windows: `CON.avb` vai para o console, `NUL.avb` some — **sem erro na escrita**. O nome vem do modelo, que pode propor "CON" para uma cena de conversa |
| teste-placeholder quebrado no próprio arquivo de segurança | teria ficado como ruído verde |

⚠️ O conserto do `CON` confere o NOME, não o prefixo — senão `CONVERSA` e `CONTATO`
ganhariam underline na frente.

### O que a auditoria confirmou que já estava certo

- painel sem `innerHTML` com dado externo; sem `eval`, sem `shell=True`, sem `pickle`
- serviço só em `127.0.0.1`, nunca `0.0.0.0`
- MobID hostil (`../..`, 63 ou 65 dígitos, não-hex) **recusado** antes de virar diretório
- `/static/../../VERSION` → **404**
- nenhuma ferramenta de escrita na allowlist (teste trava a volta)

### O que o documento diz que NÃO cobre

Dito em voz alta, porque a ausência é a parte que se esquece: auditoria de terceiros,
cadeia de suprimentos (não há `requirements.lock` — tudo `>=`), os modelos baixados do
Hugging Face, e o macOS. Mais o backend gRPC do Media Composer, que **não valida token** —
propriedade do produto da Avid, não escolha nossa.

---

## Roadmap — pedido pelo autor em 2026-09-10, fora do caminho crítico

Nenhum destes bloqueia as fases; todos melhoram o controle do editor sobre o que ele
gasta e como.

### R1 · Escolher o modelo

Sonnet ou Opus, nas versões disponíveis no momento. O CLI já aceita `--model`, então o
custo é de interface e de persistência da escolha, não de motor.

⚠️ **A lista não pode ser cravada no código.** Nome de modelo muda, e um seletor com
opções obsoletas é pior que nenhum seletor — oferece o que não existe mais. Descobrir os
disponíveis em tempo de execução, ou degradar para "o padrão da conta".

⭐ E há uma ligação com R2: modelos custam diferente, e a escolha só é informada se o
editor vir o gasto ao lado.

### R2 · Quanto se gastou, e quanto resta

⭐ **O dado JÁ CHEGA e está sendo descartado.** Dois eventos do CLI carregam tudo:

| evento | traz |
|---|---|
| `rate_limit_event` | `utilization` das janelas de 5 h e 7 dias, **antes do primeiro token** |
| `result` | `usage` completo (entrada, saída, cache lido, cache criado), `modelUsage` por modelo e `total_cost_usd` |

O painel hoje só usa o `rate_limit_event`, e só para avisar acima de 80%. O resto é
descartado no `_traduzir` do motor.

O que fazer com isso, em ordem de utilidade:

1. **Gasto por turno**, ao pé da resposta. É o que ensina o editor a perceber que uma
   pergunta ampla custa mais que uma específica.
2. **Indicador de contexto** da conversa, para ele saber quando o fio está ficando longo.
3. **O que o cache POUPOU.** ⭐ É a métrica que justifica a arquitetura: a segunda
   pergunta sobre o mesmo material não gasta token de visão nenhum. Sem mostrar isso, o
   cache é invisível — funciona e ninguém sabe.

⚠️ **Cuidado com a unidade.** `total_cost_usd` aparece no evento mesmo em conta de
assinatura, onde **não há cobrança por token**. Mostrar dólar para quem paga plano mensal
informa errado. O que importa para o editor é a **fração da janela** e a comparação entre
turnos — não um preço que ele não paga.

## O que este plano recusa

- **Não** construir as três funções em paralelo. Uma fatia vertical de cada vez.
- **Não** começar pela função mais bonita de demonstrar (a visual) antes de o encanamento
  aguentar. A fase 5 é a quinta por decisão.
- **Não** repetir o erro do guarda-chuva: se aparecer a vontade de somar Preparar ou
  Entregar aqui dentro, a resposta é outro plugin.
