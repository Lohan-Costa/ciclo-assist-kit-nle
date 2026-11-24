# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **A inversão que define este repo:** não é o plugin que chama o Claude. É o Claude que
> chama o plugin. Nosso código não é cliente de IA nenhuma — ele **expõe ferramentas MCP**
> e espera ser chamado. Quem paga o modelo é a assinatura logada na máquina do editor.

Plugin do Avid Media Composer para três funções: **identificar material visualmente**,
**separar falas de uma cena** e **corte zero**. O que ele não é: chat genérico, wrapper de
API, LLM local.

Documentação em português. Decisões em `docs/adr/`, fases em `docs/plano/`, desenhos em
`docs/spec/`.

## Comandos

```bash
.\dev.ps1                                # confere tudo e sobe o serviço (o caminho normal)
python -m cicloassist.servico            # só o serviço, sem as conferências

python -m pytest                         # ~720 testes, sem Avid e sem gastar turno do modelo
python -m pytest tests/test_take.py      # um arquivo
python -m pytest -k claquete -v          # um teste

python tools/gerar_stubs.py              # stubs do protobuf, gerados do banco (uma vez)
python tools/integracoes.py [--fazer]    # a ponte do Premiere + tira as integrações antigas (o mesmo da ⚙ › Integrações)
python tools/consertar_quadros.py        # joga fora quadro extraído por busca não confiável
.\decodificadores\braw\construir.ps1      # o decodificador de BRAW (exige o SDK da Blackmagic)
python tools/conferir_braw.py <X.braw>   # confere o decodificador COM OS OLHOS
python tools/separar_bancos.py [--fazer] # tira os apelidos que juntavam Avid e Premiere
python tools/limpar_claquete_chutada.py  # tira dos filtros a claquete que o modelo chutou
python tools/ler_travamento.py --pendentes  # travamentos da janela que ninguém leu (o painel avisa)
python tools/ler_travamento.py           # a pilha do dump mais recente (precisa do WinDbg); marca como lido
python tools/olhar_painel.py --aba busca --termo drone  # VER o painel a 400 px, sem o Avid
python tools/olhar_painel.py --aba busca --termo x --premiere  # …e a tela do Premiere, sem o Premiere
.venv-win\Scripts\python tools\lock.py    # regera o requirements.lock
```

`INSTALAR.bat` é a porta de entrada de quem **usa** — duplo clique, seis passos.

**Abrir a janela do app:** `ABRIR-APP.bat` (Windows) · `ABRIR-APP.command` (Mac, duplo clique no Finder; compila em
`~/Library/Caches/CicloAssist-build`, espera a 7824 liberar e abre). Os dois fecham a janela anterior antes.

⭐⭐ **Abrir e fechar os programas do fluxo** (2026-11-01): `abrir_programa`/`fechar_programa` para **Resolve** (API,
`resolve.py`), **Premiere** (ponte CEP, `premiere_app.py` — `spikes/abrir_e_fechar_o_premiere.py`) e **Media Composer**
(PILOTO, `avid/abrir.py` — `spikes/abrir_e_fechar_o_mc.py`, mexe o mouse). O mapa está no docstring de
`mcp/ferramentas/programas.py`. Todos provados na máquina em 01/11; ⬜ ainda não pelo CHAT.

⭐⭐ **O GUARDA-CHUVA** (2026-10-21): a janela do app tem as abas **Preparar** (Sincronizar, o ex-Órbita: servidor Python `modulos/sincronizar/servidor`, o Rust aposentado em 2026-11-07) ·
**Assistir** (este repo) · **Conformar** (De Lá Pra Cá) · **Entregar** (em breve), cada uma mostrando o painel do motor
do módulo (`app/src-tauri/src/lib.rs`). ⭐⭐ **Desde 2026-11-07 é UM app só** (autor, reafirmado em 2026-11-20): o De Lá
Pra Cá é `modulos/conformar` e o Órbita é `modulos/sincronizar`, com o histórico DENTRO deste repo; os apps standalone
foram aposentados e arquivados (`CATALOGO.md`). **Desenvolve-se aqui, direto nos módulos** — não há repo de módulo nem
"mudanças a incorporar". (Histórico: o plano `docs/plano/2026-10-21-assist-standalone.md` e a pasta `MUDANCAS DOS APPS/`
eram da fase de transição de 21–29/10 e não regem mais o trabalho.)

⭐⭐ **O agente de metadado e a memória da produção** (2026-11-08): `entender_metadados_da_diaria` propõe, `gravar_na_memoria_da_producao` grava só o que o editor confirmou (`<dados>/producoes/<produção>/memoria.md`). ⛔ O agente devolve MOLDE (`{cena}-{plano}T{take}`), e a regex quem faz é o código. ⛔ A gravação tem `sempre_pergunta`: nem o modo automático nem um fluxo a dispensam. ⛔ Regra que faria dois takes diferentes virarem o mesmo é reprovada (medido: `18-1T01` × `18-2T01`). ⭐ O caminho da mídia vem do próprio programa (Premiere, Resolve, Avid linkado); pedir a pasta ao editor só na mídia gerenciada do Avid (autor). Plano `docs/plano/2026-11-08-agentes.md`.

⭐⭐ **O supervisor** (2026-11-02, autor): com o app aberto, todos os motores do conjunto ficam no ar —
`app/src-tauri/src/supervisor.rs` religa quem cai (3 em 10 min, depois avisa no topo com "tentar de novo") e grava
`<dados>/motores.json`, que o serviço lê em `servico/conjunto.py` (o conselho do fluxo usa). Módulo novo com motor em
`Modulo::motor` entra na vigia sem código a mais.

⭐ **A janela do app** (2026-10-21, o formato do De Lá Pra Cá): `ABRIR-APP.bat` compila `app/src-tauri` (o `target`
fica em `%LOCALAPPDATA%\CicloAssist-build`) e abre. O app sobe o serviço com `--app`/`--pai`, vai ao
`/painel?casca=app` e leva o serviço junto ao fechar — inclusive morto à força. Estado e o que falta:
`docs/plano/2026-10-18-app-sem-painel.md`. No Premiere, a ⚙ › Integrações (ou `python tools/integracoes.py --fazer`) põe a PONTE invisível (`ponte_cep/` →
`/premiere/ponte`) e a janela troca sozinha para ele (`/conexao`). ⛔ Nenhum painel DENTRO dos NLEs (autor, 2026-11-07):
o `.avpi` do MC e o painel CEP saíram — o MC fala pelo gRPC 9100 sem painel instalado (medido no 25.12 do Mac).

Spikes — cada um prova o elo de uma fase e sai `0` se passou: a lista inteira, com o que cada um exige (MC aberto, serviço
no ar, editor na tela), está em `docs/conhecimento/spikes-e-servico.md`.

⛔⛔ **Modelo local NUNCA neste notebook** — nem LLM, nem VLM, nem SigLIP (telas azuis com o MC aberto; SigLIP reprovado por
RAM em 2026-09-14). A busca por frase e o Ollama moram no Mac mini na rede; o spike recusa `localhost` de propósito.

⛔⛔ **"Reinicie o serviço" podia não reiniciar nada:** no Windows o `allow_reuse_address` deixa um segundo processo bindar a
7824 por cima, calado, e o VELHO responde tudo. Hoje o segundo morre falando. Sintoma = painel desatualizado.

⚠️ **O painel vem do DISCO; as rotas, da MEMÓRIA do processo:** mexeu em rota, reinicie o serviço; só HTML/CSS/JS, Reload
basta (o serviço manda `Cache-Control: no-store`; `/saude` declara `capacidades` e a tela avisa). Detalhes e a história do
`.avpi`/gateway: `docs/conhecimento/spikes-e-servico.md`.

## Arquitetura

Um processo acumula três papéis de propósito — é o que faz o servidor MCP já ter a ponte
gRPC viva quando o modelo chama uma ferramenta:

```
┌─ Media Composer ─────────────────────────────────────────────────┐
│  .avpi = manifesto + loader + ícone   (só isso; a UI vem do serviço) │
└───────────────────────┬──────────────────────────────────────────┘
                        │ HTTP + SSE em 127.0.0.1:7824
┌───────────────────────▼──────────────────────────────────────────┐
│  servico/   serve o painel · expõe o MCP · orquestra o subprocesso │
│  avid/      ponte gRPC com o MC em [::1]:9100 (backend, sem token) │
│  midia/     quadros, áudio, ASR, VETORES, acervo e o CACHE         │
│  mcp/       registro de ferramentas + protocolo JSON-RPC           │
│  motor/     sobe o `claude -p` e traduz os eventos                 │
└───────────────────────┬──────────────────────────────────────────┘
                        │ spawn, stream-json
                   ┌────▼──────┐
                   │ claude -p │  credencial da ASSINATURA do editor
                   └───────────┘
```

### O turno é uma fila, e isso não é detalhe

O pedido de aprovação chega por um caminho e a resposta vem por outro:

```
claude -p ──POST /mcp/<segredo>──→ pedir_confirmacao  (thread A)
                                          │ abre a PENDÊNCIA, responde `deny` na hora
                                          │ empurra o cartão na fila
painel    ←──SSE de /conversar──── fila de eventos    (thread B)
   └───────POST /responder───────→ pendências: EXECUTA a ferramenta
```

Por isso `motor.conversar()` **não** é consumido direto pela rota SSE: ele roda numa
thread e escreve numa fila (`servico/turno.py`), a rota drena a fila, e o portão escreve na
mesma fila. Sem isso não há por onde injetar o cartão no meio da resposta.

**Um turno por vez, e é regra.** A chamada de `pedir_confirmacao` não diz de que turno ela
é — o CLI manda só `tool_name`, `input` e `tool_use_id`. Com dois turnos vivos, um cartão
iria para o painel errado.

### ⛔⛔ O editor NÃO tem prazo para responder (ADR 0008)

O portão **não bloqueia**: ele mostra, responde `deny` na hora e o turno acaba. O cartão
fica na tela — um minuto, ou até amanhã — e é o **clique** que executa a ferramenta, pelo
`servico/pendencias.py`, com os argumentos que o editor leu.

A versão que bloqueava dava ao editor **60 s medidos** (`spikes/portao_sem_relogio.py`,
CLI 2.1.267) para ler um plano de catorze cortes: o prazo era do CLI, não nosso. Quem saía
da mesa perdia o trabalho, e o modelo lia `"The operation timed out."` — sem uma palavra
sobre permissão — e saía caçando um defeito que não existia.

⚠️ **`deny` não quer dizer "recusado"**, quer dizer "não é o modelo quem faz isso". Quem
mexer no texto de `portao.AGUARDANDO` está mexendo em comportamento: cada frase dele
impede um erro que já aconteceu em campo.

⭐⭐ **E o cartão diz O QUE está sendo feito** (achado no Assist anterior, 2026-09-19). Como a
ação roda FORA do turno, o `turno.avisar` das ferramentas não tinha a quem contar: o cartão
dizia "fazendo…" do primeiro ao último minuto, e um `separar_falas` assim é indistinguível
de travado. Sem turno vivo, `avisar` escreve no andamento da pendência em execução
(`pendencias.relatar`, thread-local) e o painel pergunta a cada segundo por `GET /andamento`
enquanto o `/responder` não volta. ⭐ Nenhuma ferramenta mudou. ⚠️ Sem fração NÃO se mostra
0% — porcentagem parada em zero é a própria imagem de travamento; o relógio anda sempre.

> ⚠️ O desenho acima é o da era do painel DENTRO do MC; desde 2026-11-07 não há `.avpi`: a janela do app é a casca e o MC
> fala pelo gRPC 9100 (ver Comandos). O resto do fluxo — serviço, MCP, motor, a fila do turno e o portão — vale igual.

## ⛔ Os transversais — uma linha cada; o porquê medido está no arquivo do assunto

- **Rotas:** `Sec-Fetch-Site: same-origin`, NUNCA `Origin` (GET same-origin não manda `Origin`); `/mcp/<segredo>` pelo
  segredo no caminho. → `porteiros-e-ferramentas.md`
- **Ferramentas:** `escreve=` obrigatório e sem padrão — leitura nunca pergunta, escrita sempre pergunta; só existe o que
  `mcp/ferramentas/__init__.py` importa. → `porteiros-e-ferramentas.md`
- **O que a ferramenta devolve é orçamento:** toda lista tem teto e paginação, e o que ficou de fora é DITO. →
  `oficio-e-orcamento.md`
- **O ofício** vem por `consultar_o_metodo` (`skills/*.md`), não por skill do CLI (`--restricted` as bloqueia). →
  `oficio-e-orcamento.md`
- **Conferência antes do cartão** (`registro.ferramenta(conferir=…)`) nas que escrevem no projeto; conferência que quebra não
  barra. → `mapa-de-corte-e-falas.md`
- **Cache pelo UMID do MASTER**, posição em tempo do master; o nome da pasta é rótulo, a identidade é o `midia.json`; ler
  nunca cria pasta; quem grava, grava por `Midia`. → `cache.md`
- **Cada editor tem o SEU banco** (`origem` avid/premiere); só se cruzam ao PROCESSAR, copiando. → `premiere.md`
- **Busca só no projeto aberto**; "não sei o projeto" é sem filtro (mas nunca o banco do OUTRO editor); filtro calado é pior
  que filtro nenhum. → `escopo-e-vetor-visual.md`
- **Tela nova depois de um porte não herda o porte:** toda chamada do painel diz o `nle`. → `aba-busca.md`
- **Bin do editor:** `CloseBin` → escrever ao lado (UID preservado) → `OpenBin`; bin nova leva o FECHO oculto; carregar →
  consultar → fechar colados derruba o MC (3 s de pausa). → `bins-e-timeline-do-editor.md`
- **A conversa é da JANELA**, zera por visita; o custo é o `/clear`, não o modelo. → `conversa-visita-e-custo.md`
- **O modelo copia qualquer literal do prompt** e inventa claquete onde não há; a rede é a conferência, não a instrução. →
  `decupagem.md`

## Regras da casa

- **Python stdlib para o HTTP.** `ThreadingHTTPServer`, sem framework: menos dependência
  para o PyInstaller empacotar, e SSE sai da stdlib. Não adicionar FastAPI/Flask sem um ADR.
- **NADA de torch.** O ASR é `faster-whisper` (CTranslate2) — o mesmo motor que o Media
  Composer 2025 embarca. `openai-whisper` levaria o pacote de ~2 GB para ~6 GB.
- **Rota é caminho EXATO, nunca prefixo.** Com prefixo, `/saudeX` cai em `/saude` e a ordem
  de registro vira lógica.
- **Binários são pré-requisito, não dependência Python:** `claude`, `ffmpeg`, `ffprobe`.
- ⚠️⚠️ **Mexeu no `painel.js`, rode os testes.** Um erro de sintaxe ali não aparece como
  erro: aparece como **painel que não faz nada** — nenhuma aba troca, o modelo some da
  barra, o ponto fica cinza, e o serviço está bem. `node --check` pega a classe inteira em
  50 ms e já está na suíte (pulando quando não houver node, que **não** é pré-requisito do
  produto: o painel roda no QtWebEngine).
- ⚠️⚠️ **`requirements.txt` e `requirements.lock` são ASCII PURO.** O pip os decodifica com
  a codepage do sistema quando não há BOM, e um emoji carrega o byte `0x8F`, indefinido em
  cp1252 → `UnicodeDecodeError` e **nenhuma instalação**. Prosa acentuada fica aqui, não
  lá. Instalar é pelo **lock**, que traz o SHA-256 de cada pacote; regerar é
  `.venv-win\Scripts\python tools\lock.py`, nunca com `>` do PowerShell.
  ⛔ Hash **parcial** é pior que nenhum: o pip recusa tudo que não tiver.

### Ao chamar o `claude -p`

Nunca sem estas, e cada uma tem motivo medido:

- `--strict-mcp-config` — sem ela a sessão herdou **3 MCP servers e 35 ferramentas** da
  conta pessoal do usuário (Gmail, Drive, Adobe). Não é higiene, é contenção.
- `--restricted` — sem ela, a caixa de chat é um shell na estação do cliente.
- ⛔⛔ `--tools ""` — **o `--restricted` não basta.** MEDIDO no CLI 2.1.270
  (`spikes/o_que_o_restricted_deixa.py`, lendo o `system/init` sem pagar turno): ele tira
  só Bash, PowerShell, WebFetch, LSP, Monitor e dois de agendamento; **sobram 29 nativas**,
  com `Write`, `Edit`, `Read`, `Task` e `WebSearch`. Com `--tools ""` sobram zero e as
  nossas 18 continuam; o portão segue de pé (`fase3_permissao.py`, sim e não). E o portão
  recusa por nome o que não for `mcp__ciclo__*` — o automático liberava qualquer um.
  Um teste confere que todo `"--restricted"` em `motor/` vem com o `--tools ""`.
- `--permission-prompts host` + `--permission-prompt-tool` — o portão (ADR 0003).
- `--output-format stream-json --verbose` — o `--verbose` é exigido junto do stream-json.
- `stdin=DEVNULL` no `Popen` — sem isso o CLI espera 3 s por stdin que nunca vem, **antes**
  de começar o turno. Parece lentidão do modelo e o aviso só sai no stderr.
- ⛔⛔ **O `stderr` DRENADO numa thread**, nos três caminhos (`sessao`, `decupador` e
  `claude.conversar`). Com `stderr=PIPE` e ninguém lendo, o buffer do sistema (~64 KB) enche
  e o CLI **bloqueia ao escrever**: o stdout para de sair e o turno congela sem nada
  acusando. Travou o painel por cinco minutos em 2026-09-12 no caminho de sessão; o de turno
  solto ficou aberto até 2026-09-19 (achado no Assist anterior). `deque(maxlen=50)` guarda só o
  fim, e `join(2 s)` antes de ler — o EOF do stdout chega antes da última linha do stderr.
  ⛔ Nunca um `read()` sem tamanho ali: num processo vivo ele espera o EOF para sempre.

### Procedência em todo item

| campo | valores |
|---|---|
| `confianca` | `confirmado` · `inferido` · `hipotese` |
| `fonte` | `claquete` · `roteiro` · `transcricao` · `visual` · `heuristica` |
| `medida` | o número que sustenta, ou vazio — ⚠️ vazio é **não medido**, nunca "zero" |

**Item sem procedência é bug, não item.**

### Windows

`sys.stdout.reconfigure(encoding="utf-8")` no topo de todo entry point: o console herda
cp1252 e qualquer acento derruba o processo com `UnicodeEncodeError` **no meio** da
execução.

## Índice — assunto → arquivo (`docs/conhecimento/`)

⭐⭐ **Regra (autor, 2026-11-20):** descoberta nova vai ao arquivo do ASSUNTO (ou a um arquivo novo nesta pasta); o
`CLAUDE.md` só ganha uma linha aqui. Fato de FORMATO de NLE vai ao banco. Nada de `@import` (carregaria tudo de novo).

| assunto | arquivo |
|---|---|
| a lista de spikes; modelo local; a porta 7824 dupla; instalar/Reload do painel | `spikes-e-servico.md` |
| arrastar para o chat (MC e Explorer, as cores, `arrastados.py`); as abas; o menu ☰ | `painel-arrasto-e-abas.md` |
| aba Vetores: inventário, a leitura de 66 s → 0,6 s, acervo, bins, a fila, reconectar | `aba-vetores.md` |
| aba Busca: frase e fala, intenção e `termos.json`, subclipes em faixas, TC da fala, Premiere | `aba-busca.md` |
| decupagem: as duas camadas, o lote e o preço, a densidade, a micro, a claquete, o glossário, o chat pelo Mac | `decupagem.md` |
| a busca só no projeto aberto (`avid/escopo.py`); o vetor visual (MobileNetV2) | `escopo-e-vetor-visual.md` |
| os dois porteiros; `escreve` decide tudo | `porteiros-e-ferramentas.md` |
| o ofício em `skills/` (ADR 0010); o teto do que a ferramenta devolve | `oficio-e-orcamento.md` |
| mapa de corte e âncora; separar falas; o checker que premiava o degenerado | `mapa-de-corte-e-falas.md` |
| uma conversa por visita; o custo é o `/clear` | `conversa-visita-e-custo.md` |
| a borda de 0,000 s do ASR | `asr-borda.md` |
| o cache (UMID, nome legível, manifesto, layout em disco); o quadro N/2 do MPEG-2 | `cache.md` |
| atualizar a bin; editar a timeline do editor (cópia provada); o trio que derruba o MC; `take.py`; AMA, matte key, drop-frame | `bins-e-timeline-do-editor.md` |
| o Premiere: bancos separados, vetores 202 de 203, a aba Vetores lá, a agulha e a Descrição, a vigia, CEP, `organizar_o_projeto` | `premiere.md` |
| BRAW pelo som; o decodificador de BRAW para Windows; R3D/ARRI | `raw-de-camera.md` |
| a ponte com o Órbita (`sincronizar`) | `orbita-sincronizar.md` |
| macOS: dados, PATH, Avid MediaFiles nos volumes, NFD, xattr das bins | `macos.md` |

Decisões em `docs/adr/`, fases em `docs/plano/`, desenhos em `docs/spec/`; o estado vivo em `.dev/HANDOFF.md`.

## Onde mora o conhecimento

⭐ **`../bancodedadosnles/` é a memória de engenharia reversa dos formatos de NLE. Consulte
ANTES de investigar; registre DEPOIS de descobrir**, com nível de confiança e a versão do MC
em que foi medido (ver `CONVENCOES.md` de lá). Este repo guarda implementação; o banco
guarda o conhecimento do formato.

| pergunta | arquivo do banco |
|---|---|
| ⭐⭐⭐ **Qualquer caminho, pasta do sistema, PATH, processo ou diálogo — o que vale no OUTRO sistema** | `transversal/matriz-de-plataforma.md` (regra master) |
| Painel do MC, gateway órfão, `.avpi` | `plugins/avid-panel-sdk/README.md` |
| O Panel SDK no Windows | `plugins/avid-panel-sdk/windows.md` |
| O que os concorrentes fazem, CORS do painel | `plugins/avid-panel-sdk/paineis-de-terceiros.md` |
| Como a decisão do agente vira timeline | `transversal/modelo-de-execucao-de-agente.md` |
| Achar a mídia; por que a chave é o nome | `transversal/banco-de-midias-compartilhado.md` |
| De quem é cada canal do som direto | `transversal/metadado-de-canal-do-som-direto.md` |
| Subclipe, timecode de OP-Atom | `protocolos/avb/`, `protocolos/mxf/`, `protocolos/msm/` |

`../_ASSIST ANTERIOR/` foi o plugin guarda-chuva anterior, **abandonado como produto único** mas
cheio de solução paga com erro. Escreva tudo novo; consulte quando um problema já tiver sido
resolvido lá: `assist_anterior/falas/`, `assist_anterior/alinhamento/`, `assist_anterior/montagem/`,
`assist_anterior/avid/mcapi.py`, `motores/decupador/`, e o design da aba em
`docs/superpowers/specs/2026-08-25-assistir-design.md`.

## Ciclo Media: o banco primeiro

Este app é da família Ciclo Media. A regra comum mora em `../CLAUDE.md`, que o Claude Code
carrega sozinho dentro do SSD. Fora dele (um clone em outra pasta), valem as mesmas duas regras:
consulte `../bancodedadosnles` antes de investigar ou implementar (skill `/ciclo-media-dev`), e
`../bancodedadosnles/transversal/matriz-de-plataforma.md` antes de mexer em caminho, processo,
disco ou diálogo do sistema — Windows e macOS lado a lado.
