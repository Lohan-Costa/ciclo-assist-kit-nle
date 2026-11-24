# O Assist operador: fluxos de ponta a ponta, o piloto embutido e a conta do editor (2026-10-31)

> **Só desenho.** Nada construído. Pedido do autor nesta data; decide-se aqui o que é de arquitetura e se lista o que
> é dele decidir. Antecessores: [2026-10-21-assist-standalone.md](2026-10-21-assist-standalone.md) (o guarda-chuva),
> [2026-10-18-app-sem-painel.md](2026-10-18-app-sem-painel.md) (a janela), banco
> `transversal/app-unico-fora-do-nle.md` e `transversal/post-producer-arquitetura.md`.

## O pedido, nas palavras do autor

> *"o usuário poder abrir o Ciclo Assist sem nenhum NLE aberto e pedir coisas como 'importe o conteúdo da pasta X
> para o Avid usando o Resolve, depois sincronize o material, faça os subclipes e organize por cena'."*

O Ciclo Assist abre o Resolve, importa, converte para OP-Atom dentro da `Avid MediaFiles`, fecha o Resolve, abre o
Media Composer, importa para uma bin, sincroniza pelo Órbita, faz os subclipes e organiza por cena. Tudo automático,
com a borda do piloto, podendo pausar ou cancelar, e o Assist como a interface de diálogo.

Mais duas coisas no mesmo pedido: **login/logout no app**, para não depender de o editor ter o `claude` instalado e
logado, e **"human first"**: sem conta, Preparar, Conformar e Entregar continuam funcionando à mão. Só o Assistir
exige conta. ⛔ A casa **não fica no meio da cobrança**: a conta é do editor, e o uso também.

## ⛔⛔ O fluxo de ficção é um ENSAIO, não a especificação (autor, 2026-10-31)

*"Esse fluxo que falei é um exemplo, um ensaio; devemos tomar cuidado para não criar regras que sirvam apenas para
esse caso."*

- **O produto são as OPERAÇÕES, não o fluxo.** `importar_pasta`, `converter`, `fechar_programa`, `abrir_projeto`,
  `trazer_para_a_bin`, `sincronizar`, `subclipar`, `organizar` — cada uma com nome, parâmetros, pré-condição e
  conferência, e cada uma vale para qualquer NLE onde houver via (a tabela de `operacoes-de-nle.md` do banco é a
  espinha). Um fluxo é só uma **composição** delas que o modelo monta a partir da frase.
- **Nada de passo com o nome de um gênero ou de um caso.** "Ingest de ficção" não existe no código; existe a
  composição que o editor pediu. Se uma operação precisa saber "é ficção", o parâmetro é o que a ficção muda
  (organizar **pela claquete**), não o gênero.
- **Teste de fumaça do desenho:** o mesmo executor tem de rodar pelo menos um segundo fluxo diferente antes da F4
  (ex.: Premiere → conformar no Resolve pelo DLPC → entregar), sem uma linha de código nova no executor.

## ⭐⭐ O desenho em uma frase

**O modelo planeja e conversa. Quem EXECUTA o fluxo é código nosso.** Cada passo é uma operação com nome, com o
mesmo contrato das ferramentas de hoje (`escreve=`, conferência antes do cartão, resposta com teto). O piloto é **um
dos três jeitos** de uma operação acontecer, e é o último da fila:

```
 o editor ──pede──▶ ASSISTIR (claude -p)  ──monta──▶  PLANO do fluxo  ──um cartão──▶ o editor aprova
                                                          │
                                                          ▼
                                   EXECUTOR (fila de fundo, servico/tarefas.py generalizado)
                                     passo a passo, cada um com:  pré-condição · ação · conferência
                                                          │
                     ┌────────────────────────────────────┼─────────────────────────────┐
                     ▼                                    ▼                             ▼
               1. API do NLE                     2. ARQUIVO (pyavb, AAF,        3. PILOTO (mouse, teclado,
               (gRPC 9100, ponte CEP,               .prproj, DRT)                  foto, diálogo do catálogo)
                Resolve externo)                                                   só onde 1 e 2 não alcançam
```

### Por que o executor não é o turno do modelo

1. **Duração.** Converter uma diária no Resolve leva de minutos a horas. Um `claude -p` vivo por uma hora reprocessa
   o contexto a cada ida (o custo é o `/clear`, medido em 12/09: 10,8×) e morre com qualquer queda.
2. **Previsibilidade.** *"Cada modelo está interpretando a sua forma de execução… precisamos ser mais previsíveis"*
   (o autor, 20/09). Um fluxo de oito passos dirigido turno a turno pelo modelo é oito chances de improviso.
3. **O portão já é assim.** ADR 0008: o cartão fica, o clique executa com os argumentos que o editor leu. Um fluxo é
   **um** cartão com o plano inteiro (como o `organizar_o_projeto` do Premiere já faz) — não oito "permitir".
4. **Parar e retomar.** A fila de hoje já para entre itens e dentro do ASR. O executor herda isso.

⇒ O modelo volta à cena só quando um passo devolve **uma pergunta** (o que fazer com 3 clipes sem claquete? qual
projeto do Avid?) — e aí é uma conversa curta, com o estado do fluxo no preâmbulo, não a conversa inteira.

⭐ **Consequência que vale ouro para o "human first":** se o fluxo é código, um fluxo **conhecido** (a receita
"ingest de ficção") pode rodar por um BOTÃO, sem modelo nenhum. O modelo serve para montar o plano a partir de uma
frase e para resolver as exceções. Isto não precisa estar na primeira entrega, mas o desenho não pode fechar a porta.

## O fluxo do exemplo, passo a passo, contra o que o banco já sabe

| # | passo | via | o que o banco tem | estado |
|---|---|---|---|---|
| 1 | abrir o Resolve e um projeto | API externa | `abrir_programa` já faz (3589d83) | ✅ |
| 2 | importar a pasta X | `MediaStorage.AddItemListToMediaPool` | `operacoes-de-nle.md` §E | ✅ medido |
| 3 | **converter para OP-Atom na `Avid MediaFiles`** | `SetRenderSettings` + `AddRenderJob` | só ProRes/MOV medidos; **render MXF OP-Atom / preset "Avid AAF" NÃO mapeado** (`api-scripting.md` l. 402) | ⬜ **medir primeiro** |
| 4 | fechar o Resolve | API (`Quit`) ou processo | — | ⬜ trivial, medir se pergunta "salvar?" |
| 5 | **abrir o MC num projeto** | ⛔ não há API antes do projeto aberto: a janela *Select Project* é GUI | piloto + catálogo `avid/` | ⬜ **primeiro passo pilotado** |
| 6 | trazer o material para uma bin | `ImportFile` do AAF do Resolve, ou `LinkFile` (gRPC) | `ImportFile`/`LinkFile` medidos (100/100 no relink) | 🟡 depende do que o passo 3 entregar |
| 7 | sincronizar | Órbita (motor dele, `sincronizar_com_o_orbita`) | rodando, hoje por HTTP para o standalone | ✅ (transição) |
| 8 | subclipes + organizar por cena | Órbita (`subclipes.py`, 52/52) + `organizar` **pela claquete do METADADO** | Avid medido; a leitura de cena/take do metadado do som (iXML/bext) **não está no banco** | 🟡 |

⭐ **Organizar segue a claquete, e a claquete vem do METADADO dos arquivos** (autor, 2026-10-31) — em geral o do
som direto: o gravador escreve cena, take e rolo no iXML (`<SCENE>`, `<TAKE>`, `<TAPE>`) e/ou no `description` do
`bext` (`sSCENE=…`). Não é a leitura visual da claquete (a decupagem): essa fica como reforço, com o aviso de
"duvidosa" que já existe. ⬜ O banco só registra o caminho do `bext` (`time_reference`) e diz que o OP-Atom do Avid
**não tem iXML** (`metadado-de-canal-do-som-direto.md`) — ⇒ a cena/take tem de ser lida **antes da conversão** (do
WAV original) ou do que o MC guarda na bin (colunas Scene/Take). Medir os dois. Organizar pelo roteiro é outra
abordagem e **fica fora** por enquanto.

⭐ **Só UM passo do exemplo precisa de piloto (o 5)**, e talvez um segundo se o render do Resolve abrir diálogo. O
resto já tem via de API ou de arquivo. É a confirmação do desenho: o piloto é a exceção, e cada uso dele é uma
pergunta para o REA ("dá para fazer isto por fora?") antes de virar clique permanente.

⚠️ O 3 é o elo desconhecido do fluxo inteiro, e tem três perguntas: o Resolve escreve OP-Atom que o MC aceita como
**gerenciado** (sem AMA)? Gera o AAF que liga os masters à mídia? O som direto multicanal sai com os canais certos
(o banco já viu o ffmpeg gravar OP-Atom que **não** se agrupa)? ⇒ **spike antes de qualquer outra coisa do fluxo.**
### ⭐⭐ A rodada da F3 (2026-10-31): o que mudou no ensaio

Medido no Resolve Studio 19.1.4.11 (banco, `plugins/resolve-scripting/api-scripting.md`), com as correções do autor:

- ⛔ **O Resolve converte os CLIPES DE CÂMERA, com o áudio deles** ("Same as source": o mesmo número de canais —
  medido 2, 4 e 8 canais, cada `_A0n` = o canal n da origem). ⛔ O que **não** passa pelo Resolve é o **WAV do som
  direto**: ele entra no Media Composer por **AMA link** e o **próprio MC consolida** para MXF — ⚠️ nunca fizemos um
  Consolidate pelo MC, e **a API gRPC não tem chamada para isso** (só `ImportFile`/`LinkFile`): investigar com o REA
  antes de virar piloto. (Correção do autor, 2026-10-31: a primeira leitura desta sessão desligou o áudio do preset.)
- ⭐ **Render: parâmetro pela API; o resto, preset NOSSO injetado.** A API faz formato (`mxf` = OP-Atom), codec e
  só-vídeo, mas **não limpa o nome** (sai `<clipe>00090000`). O preset de fábrica `AVID AAF` também não serve (prefixo
  `V1-0001_`). ⇒ `resolve/presets/CICLO-OP-ATOM.xml` (feito do preset que o autor salvou na tela, sem a pasta
  gravada, áudio "Same as source") entra por `ImportRenderPreset`, e o codec vem por cima pela API — nome limpo
  conferido. **Nunca** depender de um preset do usuário: ele muda (a mesma fragilidade dos presets do MC).
- ⛔ **A pasta da `Avid MediaFiles` é só dígitos** — o banco já dizia (`protocolos/msm/README.md`) e esta sessão
  propôs `9999_CICLO_SPIKE` sem consultar (a terceira vez registrada). O número sai da **data de gravação** (do
  caminho da mídia) por convenção do editor, e a diária termina em **0** (vídeo) e **1** (áudio). Ou o áudio vai para
  a mesma pasta do vídeo, e então o `.mdb`/`.pmr` dela saem para o MC reindexar. ⇒ **parâmetro da receita, perguntado
  ao editor** na primeira vez, nunca regra fixa no código.
- ⚠️ Abrir o Resolve: a porta 1144 responde antes da API (19 s contra ~40 s). O passo `abrir` espera a API, com prazo.

O ensaio corrigido, passo a passo (substitui os passos 3–8 da tabela acima):

| # | passo | via | estado |
|---|---|---|---|
| 3 | converter os **clipes de câmera** (com o áudio deles, mesmos canais) para OP-Atom, preset nosso + codec pela API; o WAV do som direto fica de fora | API + preset injetado | ✅ medido no sintético |
| 3b | levar o vídeo para `Avid MediaFiles\MXF\<data>0` | arquivo | ✅ `MXF\202610310` (sintético, 2026-10-31) |
| 5 | abrir/criar o projeto no MC | piloto | 🟡 pilotado à mão de modelo (Select Project → New Project → 1080p/25 → Create, 16 s); falta virar operação com nome |
| 6a | o MC reconhecer o vídeo e os masters entrarem na bin | foco no MC (o `.mdb` nasce em ~8 s) + AAF de masters (pyaaf2 `link_external_mxf`) + `ImportFile` | ✅ 4 de 4 online, sem cópia, canais certos (banco `avid-panel-sdk/windows.md`) |
| 6b | **o som direto INJETADO** na bin (nunca `LinkFile`: o diálogo "Audio Start-Time Options" volta a cada WAV) | `autorar_masters(fps, drop)` do DLPC | ✅ 2026-10-31, online; o motor corrigido para a taxa do projeto (5 gabaritos do MC) |
| 6c | **consolidar o som pelo MC**, "Delete original media files when done" LIGADO → `MXF` → mover para `MXF\<data>1` | piloto (sem RPC) | ✅ 2026-10-31: `MXF610311`, indexado, toca no Source |
| 7 | sincronizar | **Órbita do Ciclo Assist** (aba Preparar, fontes = bins) | 🟡 31/10: o sync rodou e gravou a bin; o MC 2024.6 CAIU ao abrir a timeline (`CompressionManager.c` 11276) — ver o handoff |
| 8 | subclipes + organizar pela claquete do metadado | arquivo | 🟡 |

⬜ **Depois do ciclo — o TAPE/reel** (autor, 2026-10-31): o master entrou com `Tape: Mob`. O Resolve tem uma opção de
PROJETO que grava o nome do arquivo (sem extensão) como reel name — achar e ligar pela API (`SetSetting`). E, de
reserva, gravar o tape name por programação (no AAF dos masters, antes do `ImportFile`) quando o material vier sem reel.

⭐ **É a prova de fogo do desenho**, nas palavras do autor: um fluxo com idas e vindas (render, cópia, reindexar,
link, consolidar, reindexar de novo), em que a IA orquestra e os executores frios fazem cada passo. Se o executor
aguenta este, aguenta os outros.

### ⛔⛔ Só Resolve Studio (decisão do autor, 2026-10-31)

*"Só vamos focar na Resolve Studio. Não precisamos de suporte na versão gratuita, e inclusive podemos identificar se
a versão é gratuita e recusar operações que seriam até possíveis, como cliques de mouse na tela."*

- **O piloto nunca substitui a API do Resolve.** Na versão gratuita o scripting externo não existe, e o caminho
  "possível" seria operar a GUI inteira — é exatamente o que fica proibido. Sem Studio, o passo é **recusado**, e o
  fluxo inteiro também (antes do cartão, na conferência — o editor não aprova algo para ver falhar).
- **Como se reconhece:** `resolve.GetProductName()` tem de conter `Studio` (banco, `api-scripting.md`). ⚠️ Na gratuita a
  API externa não conecta, então a resposta normal ali é **"não consegui perguntar"**, não "é a gratuita". As duas
  dão recusa, com frases diferentes: *"este fluxo exige o DaVinci Resolve Studio; o instalado é o gratuito"* só
  quando houver prova (`GetProductName` sem `Studio`, ou o instalado identificado como gratuito por fora). Sem prova:
  *"não consegui falar com o Resolve; ele é o Studio e está com External scripting: Local?"*.
- ⬜ **Identificar a gratuita SEM a API** (para dizer a frase certa antes de abrir o programa): o executável é o
  mesmo `Resolve.exe` nos dois; o que os distingue no disco/registro é `pendente` — medir numa máquina com a gratuita.
- A recusa vale para o `abrir_programa` e o `conformar_no_resolve` de hoje também, não só para os fluxos novos.

## ⭐⭐ O piloto embutido: o que muda de ferramenta de bancada para função do produto

O piloto de hoje é para o Claude daqui (terminal), que olha a foto e decide o clique. No produto isso **não** pode ser
igual, por três motivos: segurança, calibração e quem decide.

| | piloto de bancada (hoje) | piloto do produto |
|---|---|---|
| quem decide o clique | o modelo, olhando a foto | **o código do passo**; o modelo nunca recebe "clique em x,y" |
| ferramenta exposta ao modelo | mãos/olhos crus | ⛔ **nenhuma**: só operações com nome (`mc_abrir_projeto(nome)`) |
| como acha o botão | posição calibrada no notebook (1920×1080, 125 %) | **padrão** na foto, UI Automation do Windows / Acessibilidade do Mac, catálogo de diálogos |
| diálogo desconhecido | foto e parar | foto, **parar o fluxo**, e o cartão mostra a foto ao editor |
| freio | F12 para, ESPAÇO pausa, borda azul/âmbar/vermelha | **o mesmo**, mais os botões Pausar/Cancelar na janela do Assist |

- ⛔⛔ **Mouse cru na mão do modelo é o Bash do piloto.** O ADR 0005 tirou o shell do chat (`--restricted`,
  `--tools ""`); dar ao modelo "clique onde quiser" devolveria a máquina inteira por outro caminho. O Post Producer
  deixa o Bash ligado e filtra por hook — é exatamente o que o estudo de 30/10 marcou como a brecha.
- ⭐ **A forma de importar é a mesma dos módulos:** o `piloto/` continua sendo a oficina (testes, bancada, catálogos)
  e o Assist leva uma cópia versionada do pacote. Regra de lá que vale aqui: o pacote não conhece app nenhum; o que é
  do Avid (o passo "abrir projeto") mora no Assist.
- ⚠️ **Calibração é o maior risco de produto.** O piloto foi medido num ambiente só. Cada passo pilotado precisa de
  uma conferência que não dependa de posição (o projeto aberto se confere pelo gRPC; o Resolve fechado, pelo
  processo). Clique que não se confere por fora não entra no produto.
- ⚠️ **Durante um passo pilotado a máquina é do piloto.** O editor tocar no mouse = PAUSA (já é a regra nova). E o
  fluxo tem de dizer, antes do clique, **quantos passos tomam a tela** e por quanto tempo — o resto roda no fundo.

### Parar, pausar, cancelar

| gesto | o que acontece |
|---|---|
| **pausar** (ESPAÇO, toque, botão) | termina a ação atômica em curso, segura o próximo passo; borda âmbar |
| **parar** (F12, botão) | não começa passo nenhum; o render/sync em curso é **perguntado** (cancelar o render do Resolve? deixar terminar?) |
| **cancelar o fluxo** | parar + o resumo diz o que ficou feito e o que não (o material já convertido fica; nada se apaga sozinho) |
| **retomar** | do passo seguinte ao último **conferido**, nunca do último "começado" |

⛔ Cada passo grava o estado **depois da conferência**, no disco (o fluxo sobrevive a reiniciar o serviço). E todo
passo é idempotente ou recusa repetir: "importar a pasta X" de novo não pode dobrar o pool.

## ⭐⭐ A conta: o binário oficial embarcado, o login da Anthropic, a credencial que nunca tocamos

### O que a Anthropic permite (lido em 2026-10-31, `code.claude.com/docs/en/legal-and-compliance`)

- **Pode:** *"preinstalling or running Claude Code in your products"*, aceitando os **Commercial Terms** e com duas
  condições: **o binário não pode ser modificado** (*"may not remove, disable, or restrict any authentication method
  built into it"*) e **ninguém paga, revende ou intermedeia o uso** (*"Each end user must authenticate with their own
  Anthropic API key, Claude subscription plan credentials, or 3P inference provider credential"*).
- E explicitamente: *"Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their
  own Claude subscription, including where a platform hosts Claude Code"*.
- ⛔ **Não pode:** coletar, guardar ou intermediar credencial ou token de sessão do claude.ai — *"sign-in to a Claude
  account must complete through Anthropic's own flow"*. Nem oferecer um login claude.ai **nosso**.
- ⛔ **Nome:** pode dizer em texto "roda o Claude Code"; não pode usar Claude/Anthropic no nome ou logo do produto.
- ⚠️ **A tensão:** a página do Agent SDK diz *"Unless previously approved, Anthropic does not allow third party
  developers to offer claude.ai login or rate limits for their products"*. A leitura que concilia as duas: o login
  que o editor faz **é o do binário oficial**, pelo fluxo da Anthropic — nós não o oferecemos, só o deixamos
  acontecer. ⇒ **Antes de distribuir para fora da casa, confirmar com a Anthropic** (a página indica vendas). Para uso
  interno e a demo, o desenho abaixo já está do lado certo da linha.

⭐ É exatamente o oposto do Post Producer, que usa o mesmo CLI com `ANTHROPIC_BASE_URL` num gateway deles e revende o
uso. Nós ficamos com o lado permitido de graça: nada de servidor, nada de cobrança.

### O desenho

```
instalador do Ciclo Assist
  └─ claude(.exe)  oficial, versão FIXADA, sem modificação   ← deixa de ser pré-requisito
       CLAUDE_CONFIG_DIR = <pasta de dados do Assist>\claude  ← separado do claude pessoal do editor
```

| gesto na janela | o que roda | o que o Assist sabe |
|---|---|---|
| **Entrar com a conta Claude** | `claude auth login` no config dir próprio → abre o navegador no fluxo da Anthropic | só "logado / não logado", o plano e o e-mail que o próprio CLI informa (`claude auth status`) |
| **Sair** | `claude auth logout` | volta ao "sem conta" |

⭐ **Só assinatura, sem chave de API** (autor, 2026-10-31). Quem bate no limite compra crédito extra na própria
assinatura e continua — é escolha do editor, feita na conta dele, sem passar por nós. ⇒ O aviso de limite que o
painel já mostra (a janela semanal) ganha o gesto: *"o limite desta semana acabou; dá para continuar com crédito
extra na sua conta Claude"*. ⚠️ O CLI aceitaria uma `ANTHROPIC_API_KEY` no ambiente; o Assist **não oferece** esse
caminho, mas também não o bloqueia (a regra da Anthropic proíbe remover método de login do binário).

### Distribuição: estrutura primeiro, publicações de teste, nada distribuído (autor, 2026-10-31)

A F0 constrói a estrutura inteira (binário embarcado, login, trancas) e o instalador é publicado **só para testar o
fluxo**, nas máquinas da casa. Distribuir fica para quando o autor tiver o consentimento da Anthropic — ele mesmo
conduz essa conversa.

- ⛔⛔ **Nunca lemos o arquivo de credencial do CLI**, nem copiamos token para `CLAUDE_CODE_OAUTH_TOKEN`. O CLI guarda,
  o CLI usa. (Hoje o caminho do Ollama já TIRA esses tokens do ambiente — `claude.ambiente_do_modelo` — e continua
  assim.) O `claude setup-token` não serve aqui: é para CI e o editor teria de copiar o token, que é o que a regra veda.
- ⭐ **O config dir próprio resolve de quebra um defeito antigo:** hoje o `--strict-mcp-config` existe porque a
  sessão herdava os MCP da conta pessoal do usuário (Gmail, Drive). Com uma pasta do Assist, não há o que herdar.
- ⚠️ **Fixar a versão é responsabilidade nova.** Hoje cada spike mede numa versão do CLI (2.1.267, 2.1.270…); com o
  binário embarcado, a versão é nossa e se atualiza com o app. Ganho: o comportamento medido não muda debaixo de nós.
  Custo: atualizar o CLI vira release.
- ⚠️ Fallback de desenvolvimento: sem o binário embarcado, o `binarios.py` continua achando o `claude` do PATH.
- ⬜ **Não medido:** o `claude auth login` num `CLAUDE_CONFIG_DIR` próprio abre o navegador e volta sozinho, sem
  terminal visível? (No Windows ele pode querer um console.) **É o spike da F0.**

### Human first: o que cada estado da conta libera

| | sem conta | com conta |
|---|---|---|
| Preparar (Órbita) · Conformar (DLPC) · Entregar | ✅ tudo, à mão | ✅ |
| Busca, Vetores, transcrição, vetores, decupagem pelo Mac | ✅ (não gastam turno) | ✅ |
| Assistir (chat) e fluxos montados por frase | ⛔ a aba mostra "Entrar" e explica o que libera | ✅ |
| decupagem pelo Claude | ⛔ | ✅ (com o preço antes do clique, como hoje) |
| fluxo conhecido por botão (futuro) | ✅ se for código puro | ✅ |
| 🖥 Qwen no Mac (LLM local) | ✅ **libera o Assistir sem conta Claude** (autor, 2026-10-31) | ✅ |

### ⭐⭐ O motor é PLURAL (autor, 2026-10-31)

*"Ter uma LLM local que substitua o Claude é de extrema importância; o Claude é para a primeira versão, versões
futuras penso em abrir para o Codex, Gemini ou Copilot."*

- O Assistir passa a ter **"conta conectada OU modelo local configurado"** como condição, não "conta Claude".
- ⭐ O desenho do executor ajuda aqui de graça: quem EXECUTA é código nosso, e o modelo só monta o plano e responde
  exceções. Quanto menos o fluxo depende do modelo, mais fácil trocá-lo — e um modelo local de 8B (que já fecha
  `<tool_call>` sem a última `}`, medido em 16/09) aguenta "montar um plano de operações com nome" muito melhor que
  "dirigir oito passos turno a turno".
- O que já é independente do motor: o MCP (`/mcp/<segredo>`), o portão assíncrono (ADR 0008), a conferência antes do
  cartão, o teto das respostas. O que é do `claude -p` e teria de ter equivalente por motor: `--restricted` +
  `--tools ""` (a contenção), o `permission-prompt-tool` (o portão), o `stream-json` (os eventos), `--resume`.
- ⛔ **Regra para qualquer motor futuro:** só entra se der para provar a contenção (zero ferramenta nativa, só as
  nossas) e o portão — os dois spikes que o Claude passou (`o_que_o_restricted_deixa.py`, `fase3_permissao.py`)
  viram o critério de admissão de um motor novo. ⬜ Codex/Gemini/Copilot: nada medido; não é desta rodada.
- ⬜ Para a F0: o login e a tranca do Assistir são escritos já com "provedor" como parâmetro (Claude hoje, Ollama
  já existe), para não refazer quando o segundo provedor de nuvem chegar.

## ⭐ O assunto do chat é o trabalho (autor, 2026-10-31)

*"Se o editor perguntar como fazer um bolo, não é uma pergunta que permeia o trabalho; mas se perguntar como resolver
um `PMM_Insufficient_Media`, o chat usa o conhecimento da IA para tentar ajudar, e se oferece para corrigir o problema
se for possível."*

- **O critério é "toca o trabalho de pós-produção ou a máquina onde ele roda"**: material, os programas (MC,
  Premiere, Resolve), cor, som, entrega, codec, disco, mídia offline, erro de programa. Fora disso, recusa numa frase,
  sem sermão, dizendo com o que pode ajudar. **Na dúvida, ajuda** — recusar uma pergunta de trabalho custa mais caro
  que responder uma de fora.
- **Erro de programa:** responde com o que o modelo sabe, separando o que é conhecimento geral do que foi conferido
  no projeto (procedência, a regra da casa), e **oferece** o conserto quando uma operação nossa alcança (relink,
  reabrir a bin, consolidar) — pelo portão, como toda escrita.
- **Onde mora:** um parágrafo na persona (`motor/claude.PERSONA`, feito em 2026-10-31, teste
  `test_a_persona_limita_o_assunto_ao_trabalho`). Vale para o Claude e para o modelo local (os dois usam a persona).
  ⛔ Sem classificador antes do turno: seria um segundo modelo pago em toda pergunta para barrar a minoria.
- ⬜ **Não medido:** quanto o modelo local (Qwen 8B) obedece à recusa; e se o Claude recusa demais em caso de
  fronteira (ex.: "como escrever um e-mail para o produtor sobre o atraso da diária" — é trabalho).
- ⭐ O motivo de produto, além de foco: cada resposta sai da assinatura do editor.
- ⬜ Conhecimento de erro do MC é um bom candidato a skill do ofício (`consultar_o_metodo`): o banco já tem várias
  causas medidas de `FILE_OPEN_FAILURE`, que valem mais que o conhecimento geral do modelo.

## Depois do ensaio: o ofício dos erros e o relatório anônimo (autor, 2026-10-31)

⛔ **Fora da primeira versão.** O foco agora é o Ciclo Assist funcionar no ensaio; estes dois recursos entram à medida
do desenvolvimento. Ficam escritos aqui para o desenho não fechar a porta.

### O banco vira ofício

*"Passamos por diversos erros entre sessões de Media Composer, Premiere, Resolve. É um ponto de força entre o nosso
assistente e outros do mercado: o olhar por fora e o mapeamento dos problemas."*

- O `bancodedadosnles/` já é o mapa: as três causas de `FILE_OPEN_FAILURE`, a string nula da `.avb`, o carregar →
  consultar → fechar que derruba o MC, o gateway órfão, o `Some mobs was skipped.` que é sucesso num caso e erro no
  outro, o servidor de scripts do Resolve que perde a corrida na abertura…
- ⇒ Uma skill do ofício (`skills/erros-dos-programas.md` ou uma por programa), chegando por `consultar_o_metodo` como
  as outras: **sintoma → causas medidas → como distinguir → o conserto, e se há ferramenta que o faz**.
- ⛔ É **destilado** do banco, não o banco inteiro: o banco é de engenharia (versões, spikes, offsets); o ofício é o
  que um editor precisa ouvir. E vai com procedência: medido na versão X, `hipotese` quando for.
- ⚠️ Duas fontes divergem caladas: a skill precisa dizer de que página do banco saiu cada entrada, para ser
  revisada quando o banco mudar.

### O relatório anônimo (opcional, sempre)

*"Caso um problema se apresente e o programa não saiba, podemos sugerir o usuário enviar um relatório anônimo… O
relatório é opcional; não impede de um usuário corrigir o seu problema pontual sem comunicar nada. Está tudo bem e é
um direito do usuário."*

- **Quando aparece:** o erro não está no ofício, ou o conserto do ofício não resolveu. O chat **sugere**, uma vez, e
  segue ajudando do mesmo jeito se o editor disser não ou ignorar.
- ⛔⛔ **Nada sai sem o editor ver o texto exato** que vai ser enviado, e poder apagar qualquer parte antes. Nunca
  automático, nunca em segundo plano, nenhum "lembrar a minha escolha" que vire envio silencioso.
- ⛔⛔ **O que NUNCA vai:** nome de projeto, bin, clipe, sequência, pessoa ou produção; caminho de arquivo (vira
  `<volume>\<pasta>\<arquivo>.mxf`, só a extensão sobrevive); mídia, quadro, áudio, transcrição, decupagem, roteiro;
  o e-mail da conta, o nome da máquina, o usuário do Windows, IP; o texto livre da conversa.
- **O que pode ir:** o sintoma (a mensagem de erro, sanitizada), as versões (programa, sistema, Ciclo Assist), qual
  operação estava rodando e em que passo, o que já foi tentado — e só o que passar pelo sanitizador.
- ⭐ O sanitizador é **lista do que pode passar**, nunca lista do que tirar: um campo novo nasce bloqueado.
- ⬜ **Para onde vai** é decisão em aberto, e pesa no "sem servidor" da casa: um formulário de terceiros (que vê IP e
  horário), um e-mail que o próprio editor manda, ou uma issue que ele abre. A forma que não exige servidor nosso e
  deixa o editor no controle é ele **copiar o relatório pronto e mandar por onde quiser**.
- ⬜ E a lei: LGPD (dado pessoal, finalidade, consentimento). Ver antes de ter qualquer destino.

## ⭐⭐ Os testes: mídia sintética e falhas plantadas (autor, 2026-10-31)

*"Não vamos começar usando mídias reais, vamos fazer mídias sintéticas para que etapas como a conversão no Resolve
não demorem muito e possamos acompanhar os processos. Vamos precisar simular algumas falhas no caminho."*

- **A mídia sai do `laboratorio-de-midia/`** (regra da família): clipes de segundos, que dizem em cada quadro e canal o
  que são (TC queimado, nome, canal falado). A conversão no Resolve passa de horas para segundos, e cada passo do
  fluxo cabe numa rodada que se acompanha olhando.
- ⬜ **A receita que falta no laboratório:** som direto com **cena/take/rolo no iXML e no `bext`** (o laboratório já
  escreve `bext` com `time_reference`, ainda não iXML). É o que a operação `organizar` lê — sem isso o passo 8 não se
  testa no sintético. Pedir lá, não fazer aqui.
- ⭐ **Uma diária sintética de ensaio**: 3–4 cenas, 2 câmeras + som, ~10 takes de 5–10 s, um take sem claquete no
  metadado, um com cena repetida em dois rolos. Gera em menos de 2 min, como o `demo_multicam`.
- **Falhas plantadas** — cada uma é uma receita ou um gesto, e cada uma tem um comportamento esperado escrito antes:

| falha plantada | onde | o que o executor tem de fazer |
|---|---|---|
| arquivo corrompido / ilegível no meio da pasta | importar | seguir com os outros e **dizer quais** ficaram de fora |
| disco de destino sem espaço (volume pequeno) | converter | parar o passo, nada pela metade na `Avid MediaFiles`, a frase com o gesto |
| Resolve fechado à força no meio do render | converter | perceber pela porta 1144 / processo, não esperar para sempre; retomar refaz só o que faltou |
| Resolve gratuito (ou scripting desligado) | antes do cartão | recusar com a frase certa (seção do Resolve Studio) |
| diálogo inesperado (salvar? versão nova?) | fechar / abrir | foto, parar, mostrar a foto no cartão |
| MC sem o projeto pedido | abrir projeto | parar com a lista de projetos que existem, nunca criar um |
| take sem cena/take no metadado | organizar | bin "sem claquete", dito no resumo, nunca adivinhar |
| a mesma cena em dois rolos / take repetido | organizar | não fundir calado; dizer |
| o editor mexe no mouse no passo pilotado | abrir projeto | pausa (âmbar), retoma só pelo gesto dele |
| F12 / Cancelar no meio de cada passo | todos | o resumo diz o que ficou feito; retomar começa do último **conferido** |
| serviço reiniciado no meio do fluxo | todos | o fluxo volta do disco, pergunta antes de retomar |

- ⭐ Essas falhas são **as mesmas para qualquer fluxo**: o catálogo é do executor e das operações, não do ensaio.
- Mídia real entra só depois que o sintético passa inteiro, e como conferência de escala (tempo, espaço), não como
  primeira prova.

## A janela durante o fluxo: sempre à vista (autor, 2026-10-31)

*"Sempre visível, a menos que haja necessidade de print para alguma ação do piloto — similar à nossa regra de trazer
o terminal para frente quando não houver necessidade do piloto. O importante é que o editor fique de olho no que está
acontecendo para poder interromper."*

- A janela do Assist fica **à frente** o fluxo inteiro, com o andamento e os botões Pausar/Cancelar.
- Só sai da frente no instante em que um passo pilotado precisa da tela limpa (foto ou clique sobre o NLE), e
  **volta sozinha** assim que o passo termina — como o terminal na bancada.
- Enquanto está fora, a borda do piloto (azul/âmbar/vermelho) é o que diz o estado, e F12/ESPAÇO/mexer no mouse
  continuam valendo.
- ⚠️ No Windows, trazer a própria janela à frente esbarra na regra de foco do sistema (`SetForegroundWindow` só vale
  para quem tem o foco ou recebeu o último gesto) — o piloto já lida com isso; conferir na matriz de plataforma antes.

## As fases (cada uma prova um elo, fatia vertical)

| fase | entrega | prova | depende de |
|---|---|---|---|
| **F0 — a conta** | binário embarcado, `CLAUDE_CONFIG_DIR` próprio, Entrar/Sair na janela, Assistir trancado sem conta **nem modelo local**, provedor como parâmetro | um turno de verdade com a conta logada pelo app, num Windows **sem** `claude` no PATH | — |
| **F0b — o laboratório** | a diária sintética de ensaio + a receita de iXML/`bext` com cena/take + as falhas plantadas como receitas | gera em < 2 min e o `conferir` do laboratório diz o que cada arquivo é | — (no `laboratorio-de-midia`) |
| **F1 — o executor** | operações com nome; fluxo = composição; um cartão com o plano; Pausar/Cancelar; estado no disco; retomar; janela à frente | um fluxo **só de API** no sintético, cancelado no meio e retomado, **e um segundo fluxo diferente** sem código novo no executor | F0, F0b |
| **F2 — o piloto embutido** | pacote vendorizado, borda, F12/ESPAÇO, catálogo; **um** passo pilotado: `mc_abrir_projeto` | o MC fechado → projeto aberto, conferido pelo gRPC, 5 de 5, com o editor tocando no mouse no meio (pausa) | F1 |
| **F3 — o elo desconhecido** | spike Resolve → OP-Atom gerenciado + AAF → `ImportFile` no MC, **no sintético** | a bin com os masters online, o som direto com os canais certos, a cena/take ainda legível depois | F0b |
| **F4 — o ensaio inteiro** | a composição do exemplo, com o Órbita **de dentro** e `organizar` pela claquete do metadado | a diária sintética → bins por cena, subclipes conferidos, sem tocar no teclado, **e cada falha plantada com o comportamento esperado**; só então uma diária real, para escala | F1–F3 |
| **F5 — o Mac** | o mesmo, macOS (piloto já tem as funções; Resolve 21.1 medido) | — | F4 |

⭐ F3 é a de maior risco e a de menor dependência: começar por ela em paralelo com a F0 evita descobrir na F4 que o
Resolve não entrega o que o fluxo promete.

## O que é decisão do autor

Respondidas em 2026-10-31:

1. ✅ Resolve: só Studio; a gratuita é recusada mesmo onde o piloto alcançaria.
2. ✅ Regra da Anthropic: construir a estrutura, publicar só para teste, não distribuir; o autor fala com a Anthropic.
3. ✅ Só assinatura, sem chave de API (crédito extra é escolha do editor na conta dele).
4. ✅ O LLM local libera o Assistir; o motor é plural (Codex/Gemini/Copilot no futuro).
5. ✅ A janela fica sempre à vista; sai só quando um passo pilotado precisa da tela, e volta sozinha.
6. ✅ Organizar segue a claquete do METADADO (em geral do som); roteiro fica fora.

7. ✅ **O fluxo vira botão, no formato de RECEITA (uma skill nossa)** — autor, 2026-10-31: *"será que podemos criar no
   formato de skill? assim ele pode ser compartilhado com outros editores e se adaptar a diferentes condições"*.

### ⭐⭐ A receita: skill para ler, plano para executar

Um arquivo `.md` com cabeçalho no jeito do `SKILL.md` (`name`, `description` = quando usar), e duas partes:

```
---
name: preparar-diaria
description: Converte a pasta de uma diária no Resolve Studio, leva ao Media Composer, sincroniza e organiza pela claquete.
parametros: { pasta: pasta, projeto_avid: projeto, codec: [DNxHD 36, DNxHR LB] }
---
## Passos                       ← o EXECUTOR lê; só operações com nome, sem código
1. resolve.importar_pasta(pasta)
2. resolve.converter(codec, destino: avid_mediafiles)
...
## Quando as condições mudam    ← o MODELO lê, só quando algo não casa
- Som sem cena/take no metadado: bin "sem claquete", e diga quantos.
- Material já em OP-Atom: pule os passos 1–3.
```

- **Rodar como botão:** com as condições casando, o executor roda os Passos direto — sem modelo, sem gastar
  assinatura, sem conta, sempre igual. O modelo entra só quando uma pré-condição falha e a seção de condições
  precisa ser interpretada (ou para montar uma receita nova a partir de uma frase).
- ⭐⭐ **Força de produto (autor, 2026-10-31): automação conhecida roda SEM IA.** Sem modelo, sem conta, sem
  custo, sempre igual. Três condições para isso valer de verdade:
  1. **A exceção sem modelo vai para o EDITOR, não para a IA**: pré-condição que falha vira um cartão com as opções
     que a receita prevê ("3 takes sem claquete: bin à parte / parar"). Com modelo, ele pode propor saídas que a
     receita não previu; sem ele, o fluxo nunca improvisa.
  2. **O piloto do produto também não é IA**: acha o botão por padrão na foto, UI Automation, catálogo de diálogos —
     código. Diálogo que não está no catálogo = parar (a IA olhando a foto não entra no caminho sem modelo).
  3. **Operações que SÃO modelo por natureza** (decupar pelo Claude) só entram numa receita como passo que declara
     isso, e o botão diz antes do clique que aquele passo gasta assinatura. (Transcrição é ASR local e vetores são
     ONNX local — não contam como IA de conta.)
- **Compartilhar:** é um arquivo; exportar/importar pela janela. ⛔⛔ **Receita de fora é entrada não confiável**:
  ela só pode chamar as nossas operações com nome (nada de código, caminho de executável ou texto que vire comando),
  é mostrada inteira antes da primeira execução, e toda escrita continua passando pelo cartão. A seção em prosa chega
  ao modelo como DADO, com a mesma regra dos nomes de bin.
- ⛔ **Sem nada da máquina de quem fez:** caminho, nome de projeto e de pessoa viram parâmetro na hora de salvar — a
  receita compartilhada é a do ofício, não a da produção de alguém.
- ⭐ **Por que é NOSSA e não uma skill do Claude Code:** o `--restricted` bloqueia as skills do CLI (medido em
  2026-09-12), e uma skill do CLI só serviria ao Claude. A receita no nosso formato serve ao modelo local e a
  qualquer motor futuro — e chega pelo mesmo caminho do ofício (`consultar_o_metodo`). O cabeçalho no jeito do
  `SKILL.md` é só para ela ser reconhecível por quem já conhece o formato.
- ⭐ As receitas que a casa escrever (o ensaio, o conform do DLPC) são as primeiras, e servem de teste do formato:
  se o "segundo fluxo sem código novo" da F1 for escrito como receita, o formato está provado.
- ⬜ Versão da receita x versão das operações: uma receita feita para uma operação que mudou tem de ser recusada com
  a frase, não executada pela metade. Ex.: depois de rodar uma vez "importe, converta, sincronize,
   organize", o editor salva aquilo como *"Preparar diária"* e, na próxima diária, só aponta a pasta e clica — o
   executor roda as mesmas operações **sem perguntar nada ao modelo** (não gasta assinatura, funciona até sem conta,
   e é 100% previsível). É o "atalho de prompt" do menu ☰, só que guardando o PLANO em vez do texto. Entra na F1 ou
   fica para depois?

## O que NÃO foi feito

Nada construído nem medido nesta sessão. A regra da Anthropic foi lida nas páginas públicas em 2026-10-31, não é
parecer jurídico. O render OP-Atom do Resolve e o `claude auth login` num config dir próprio são os dois `⬜` que
decidem se o desenho se sustenta.
