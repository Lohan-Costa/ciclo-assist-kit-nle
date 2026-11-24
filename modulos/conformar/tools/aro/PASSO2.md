# ARO passo 2 — ler a SELEÇÃO da timeline do Media Composer (handoff para uma sessão dedicada)

> ✅ **MECANISMO PROVADO (2026-10-25).** `aro_servidor.c` lê a seleção por dentro, na thread principal, chamando as
> funções do MC por nome, sem `ProcessPendingRequest` e sem derrubar o MC. `PING`→`main=1`; `SELECTION` devolve a
> contagem e cada `AComponent` (tipo, is-segment, len, árvore de pais até a sequência). Detalhes e armadilhas (null de
> `GetSelComponents` = segfault 0x0; captura de SIGSEGV; retry no bind) no banco, `avid-panel-sdk/arrastar.md`
> §"PASSO 2 PROVADO".
>
> ✅ **IDENTIDADE FECHADA e VERIFICADA (2026-10-25).** O MobID da fonte do segmento vem de **`ASourceClip::GetSrcMobID`**
> (`dlsym` em libameLibrary; lê `this+0x74`, frame certo) — NÃO de `GetMobID` (esse é de AComposition, lia deslocado) nem
> de `CMGetMatchFrameSource` (só lê atributo "_MATCH", dá NullMobID). A dylib emite o MobID CRU (ordem interna = `bytes_le`
> do pyavb); `servico/aro.py` converte com `str(MobID(bytes_le=…))` → URN externa. **Verificado por 2 lados:** o SEQ do
> ARO == `mc.sequencia_no_record()` da API gRPC; o master de um clipe == o do **Caminho A** (coleta/.avb) para a mesma
> seleção. Banco §"IDENTIDADE pelo GetSrcMobID". (Eu havia dito "resolvido" com o GetMobID errado antes do e2e — corrigido.)
>
> ✅ **FUNÇÃO + PRODUTIZADO (2026-10-25, tarde 4).** (1) O botão "Carregar a seleção da timeline" do painel
> (`painel.js::carregarSelecaoDaTimeline`) tenta o `/mc/selecao-aro` primeiro (sem piscar) e CAI no Cmd+C
> (`/mc/selecao`) quando o ARO não está disponível/validado. (2) A rota faz um **AUTO-TESTE** a cada chamada (o MobID da
> sequência do ARO tem de bater com a API gRPC) → numa versão do MC não verificada, só cai no Cmd+C; nunca relinka
> errado em silêncio. (3) A dylib se **instala pelo app**: `integracoes.py` (`instalar_aro`/`remover_aro`, cria a pasta
> do sistema com admin uma vez, compila do `.c` ou usa a pronta do pacote), aparece nas **Configurações** ("Seleção da
> timeline sem piscar (ARO)"), e o `montar_motor.py` compila a dylib pro pacote nos alvos macOS arm64. Suíte 99/99.
>
> ⏭️ **O QUE FALTA (próxima sessão):** **multiversão** — MC 2021/24.6 e **Windows** (`AvidRemoteObjects364.dll`?), e
> **Intel** (x86_64): o offset `this+0x74` e os símbolos podem mudar; resolver por nome, medir por versão (o auto-teste
> já protege: onde não casar, cai no Cmd+C). ⚠️ áudio dá 1 componente nulo a mais (par estéreo).


> Escrito em 2026-10-25 (Mac, MC 25.12.0 arm64). Esta sessão é **só para isto**. Comece lendo este arquivo inteiro.
> Objetivo: o app ler quais SEGMENTOS estão selecionados na timeline do MC, SEM Cmd+C e sem bin temporária — para
> substituir o caminho "A" (`/mc/selecao`, a cópia do editor) por um que não pisca nem cria/apaga bins.

## Onde isto se encaixa (leia primeiro o banco)

- `bancodedadosnles/plugins/avid-panel-sdk/arrastar.md`, as seções **"O contrato do ARO"**, **"O contrato do ARO
  CONFIRMADO em execução"** e as `TLW_*`/`AComponent_*`. É a fonte; este arquivo é o plano de execução.
- Memórias: `projetos-de-teste-sao-descartaveis` (o lab, PRODUCAO-A e o PRODC podem quebrar em experimento),
  `o-usuario-e-editor-nao-programador`, `nao-inchar-o-app`, `terminal-na-frente-fora-do-piloto`.
- A alternativa que já funciona e fica como plano B: o caminho A, `/mc/selecao` em `plugins/media-composer/servico/
  api/rotas.py` + `coleta.capturar` (Cmd+0 → Cmd+C → Clipboard Contents → subsequência → `.avb`).

## O que JÁ está provado (não refazer)

O MC tem um servidor interno de automação de testes (**ARO**, AvidRemoteObjects). O transporte é uma dylib que a Avid
não distribui, carregada por `dlopen("/Library/Application Support/Avid Internal/AvidRemoteObjects364.dylib")` em TODA
abertura do MC (o `main` → `ConfigureAROonStartup` → `MC_AROstart(12345)` → `MC_AROserver::Start` → `dlopen`), antes da
tela de projetos. Escrevemos essa dylib (`tools/aro/aro_sonda.c`, só laboratório) e, pilotando o MC no projeto de lab:

- **Passo 1:** o MC carrega a dylib e chama `ARO_VersionNumber` (>2013), `ARO_Init`, `ARO_Release`. ✅
- **Passo 1.5:** `ARO_Init` devolvendo um servidor-escuta (vtable de 128 stubs que só logam) → o MC chamou
  `Start(12345)` e **RegisterClass de todas as classes** (`TimelineWindow`, `AComponent`, `AComposition`, `MonWindow`,
  …), estável. O ponteiro da tabela de métodos da `TimelineWindow` em runtime − o slide de ASLR = o endereço estático,
  byte a byte. ✅
- ⚠️ `ProcessPendingRequest` (o pulso do QTimer) **não disparou** na tela de projetos ociosa: `MC_AROserver::
  ProcessPendingRequest` só chama o slot do servidor quando `theBusiness == 0` **E** `StatIsActive() == 0`. É o nó da
  arquitetura "via servidor". **A arquitetura recomendada abaixo NÃO depende dele.**

Ferramenta de leitura estática (rápida, MC fechado; o binário gordo fica em `scratchpad/rea_mc/mc_arm64` — recrie com
`lipo .../AvidMediaComposer -thin arm64 -output mc_arm64`): `lldb --batch -o "target create mc_arm64" -o
"disassemble -n '<função>'"`. Tabelas de dados: ler pelo arquivo (chained fixups: alvo = 36 bits de baixo + 0x100000000).

## ⭐ A arquitetura recomendada: chamar as funções do MC por dentro, com as NOSSAS interfaces

As funções `TLW_GetSelComponents`, `MCapp_Timeline`, `AComponent_GetName`, etc. são C puras com a assinatura
`f(AROincomingInterface* in, AROserverInterface* srv, AROoutgoingInterface* out)`. Elas não usam estado global do ARO —
só essas três interfaces (que CHAMAM alguns slots do próprio vtable) e, no caso da `MCapp_Timeline`, o app global. Então:

**Nós IMPLEMENTAMOS as três interfaces** (sabemos exatamente quais slots cada função chama — tabelas abaixo) e
**chamamos a função direto**, pelo endereço (`endereço_runtime = endereço_no_arquivo + slide`, o slide a dylib já
calcula). Assim NÃO dependemos do `ProcessPendingRequest` nem de o `Start` ter sucesso.

- `ARO_Init` pode até **RECUSAR** (devolver 1): o MC segue normal (sem developer mode), e a nossa dylib continua
  carregada no processo — o `__attribute__((constructor))` já rodou e sobe o nosso canal. Menos invasivo. (Se precisar
  do developer mode por algum motivo, aceite o Start como no passo 1.5; mas a princípio não precisa.)
- ⚠️⚠️ **Tudo o que toca objetos do MC tem de rodar na THREAD PRINCIPAL** (Qt/AObject não são thread-safe). A dylib
  recebe o comando numa thread de socket e DESPACHA para a main com `dispatch_async(dispatch_get_main_queue(), ^{…})`
  (o Qt no Mac roda sobre a main run loop → o bloco executa na main). A thread de socket espera o resultado por um
  semáforo e responde. **VERIFICAR** que a main queue é bombeada (se não, usar `CFRunLoopPerformBlock(CFRunLoopGetMain(),
  kCFRunLoopCommonModes, block)` + `CFRunLoopWakeUp`). É o primeiro experimento do passo 2.

### O encadeamento (tudo na main thread, reaproveitando as funções do MC)

1. `MCapp_Timeline(in, srv, out)` → chama `srv.RegisterObject("TimelineWindow", <a janela>, &id)` e
   `out.AddObjectID(id, "objectID")`. **Guardamos `id` e `map[id] = <a janela da timeline>`.** (Não precisamos entender
   COMO ela acha a janela — `AvidGlobal_gMCApplication()` + um campo; reaproveitar resolve.)
2. `TLW_GetNumSelComponents(in{alvo=id}, srv, out)` → chama `srv.LookupObject(id, &obj)` (devolvemos `map[id]`),
   depois `obj->vtable[158]()` = a contagem, e `out.AddInt(contagem, NULL)`. **Guardamos a contagem.**
3. `TLW_GetSelComponents(in{alvo=id}, srv, out)` → para `i` de 0 a contagem−1: `obj->vtable[157](obj, i, 0)` = o i-ésimo
   componente selecionado (`AComponent*`); `srv.RegisterObject("AComponent", comp, &cid)` (guardamos `map[cid]=comp`);
   `out.AddObjectID(cid, "objectID")`. **Guardamos os `cid` na ordem.**
4. Para cada `cid`: `AComponent_GetName(in{alvo=cid}, srv, out)` → `out.AddString(nome, "name")`. Idem
   `AComponent_GetType`, `AComponent_IsSegment`, `AComponent_GetLength`, `AComponent_GetParent` para montar a
   identidade do segmento.

### As três interfaces — os slots que as funções chamam (MEDIDO; reconferir por versão)

Cada interface é `{ void* vtable; … }`; o vtable é um array de ponteiros de função. Índice = offset/8. Implemente
SÓ os slots abaixo (os demais podem apontar para um stub que loga "slot inesperado" e aborta com segurança).

**AROincomingInterface (`in`)** — o alvo e o fim da leitura:
| slot | offset | o que faz | nossa implementação |
|---|---|---|---|
| [35] | 0x118 | `int GetAlvoID()` — o id do objeto que o comando endereça | devolve o id que pusemos neste `in` |
| [38] | 0x130 | `void FimDaLeitura()` | no-op |

(Comandos COM argumentos usam mais slots de leitura; `GetSelComponents`/`GetNum`/`GetName` não têm args além do alvo.)

**AROserverInterface (`srv`)** — o registro de objetos ↔ id:
| slot | offset | assinatura | nossa implementação |
|---|---|---|---|
| [14] | 0x70 | `void RegisterObject(const char* classe, void* obj, int* outId)` | id novo, `map[id]=obj`, `*outId=id` |
| [15] | 0x78 | `void LookupObject(int id, void** outObj)` | `*outObj = map[id]` |

**AROoutgoingInterface (`out`)** — onde o resultado é escrito:
| slot | offset | assinatura | nossa implementação |
|---|---|---|---|
| [3]  | 0x18 | `void AddInt(int valor, const char* nome)` | captura |
| [11] | 0x58 | `void AddString(const char* txt, const char* nome)` | captura (⚠️ ver nota do tipo do texto) |
| [13] | 0x68 | `void AddObjectID(int id, const char* nome)` | captura |
| [17] | 0x88 | `void Finish()` | fecha a resposta atual |

⚠️ **O tipo do texto no AddString não está confirmado** — `AComponent_GetName` monta o nome com
`obj->vtable[87]()`/`obj->vtable[89]()` antes de chamar `out[11]`; o 2º arg de `out[11]` pode ser `const char*` ou um
objeto de string do MC. Verificar com uma chamada real (logar o ponteiro e tentar lê-lo como C string com guarda).

### Os endereços (MC 25.12.0 arm64; `runtime = arquivo + slide`)

Resolva por `arquivo + slide` OU, mais robusto entre versões, **por NOME nas tabelas de métodos** que o passo 1.5 já
captura no `RegisterClass` (cada tabela é pares `{const char* nome, void* fn}`; ache `"TLW_GetSelComponents"` etc.).

| função | endereço no arquivo |
|---|---|
| `AvidGlobal_gMCApplication()` | `0x10007dcb8` |
| `MCapp_Timeline` | `0x101ebd0bc` |
| `TLW_GetNumSelComponents` | `0x101eb2120` |
| `TLW_GetSelComponents` | `0x101eb21c8` |
| `AComponent_GetName` | `0x101ea5758` |
| `AComponent_GetType` | `0x101ea53f0` |
| `AComponent_IsSegment` | `0x101ea5b00` |
| `AComposition_GetMobProperty` | `0x101ea67ac` |

(Slots do objeto da timeline, já vistos nas `TLW_*`: `vtable[158]` (0x4f0) = nº de selecionados; `vtable[157]` (0x4e8)
= o i-ésimo selecionado. Confirmar em runtime.)

## A pergunta de pesquisa #1 do passo 2: a IDENTIDADE do segmento (para casar com o relink)

As `AComponent_*` dão nome, tipo, duração, pai — **não dão o MobID direto**. O relink precisa saber QUAL master cada
segmento selecionado usa. Caminhos a investigar (nesta ordem):
1. `AComponent_GetParent` + `AComposition_GetMobProperty`/`AComposition_GetMobType` — navegar do segmento até o mob de
   origem e tirar um id estável. Desmontar essas para ver o que expõem.
2. Se o ARO não der o MobID, **casar por POSIÇÃO**: já lemos a sequência inteira pelo `.avb` no relink; o ARO nos dá
   trilha + in/out (ou nome) de cada selecionado; interseccionar com os segmentos do `.avb`. ⚠️ Cuidado com o mesmo
   problema do caminho A ("o trecho, não a seleção") — mas aqui a seleção é EXATA (não a cópia), então pode ser melhor.
3. Objetivo final: produzir a MESMA lista de MobIDs que o `so_masters` do `/mc/selecao` já consome
   (`relink.filtrar_masters`). Ou seja, o passo 2 troca só a FONTE da seleção; o resto do relink não muda.

## ⭐⭐⭐ A visão maior: o ARO como canal de controle para o MC ANTIGO (≤2021) e os buracos do gRPC

Este passo 2 não é só sobre a seleção da timeline — é o **protótipo de uma tese estratégica** (autor, 2026-10-25;
banco, arrastar.md §"O ARO como canal de controle"): a API gRPC (9100, `DoCommand`…) é recente e por isso os apps
ficam presos ao MC 2024+; o **ARO é velho** (o binário exige "Version 2014 or greater") e muito provavelmente existe no
2021, 2018 e antes — e é mais rico em pontos (deu a seleção, que o gRPC nem tem; tem `ARODoTitleCommand`,
`AROSelectPopupMenuItem` = comando de menu e controles; registra Bin/Project/Monitor/Composer). ⇒ **A MESMA biblioteca
pode dar controle a versões ANTIGAS que não têm o gRPC.**

O autor está confiante porque **o custo por versão é baixo:** uma vez que temos o MAPA das funções, a diferença entre
versões custa no máximo UMA sessão de REA. Por isso, ao implementar o passo 2, **desenhe pensando em multiversão desde já**:
- Resolva as funções **por NOME** nas tabelas de `RegisterClass` (que o servidor-escuta já captura), NUNCA por endereço
  fixo — os endereços deste doc são só do 25.12.0.
- Isole o que é "por versão" (nome/caminho da dylib, offsets dos slots se mudarem) num mapa pequeno, para uma versão
  nova entrar com uma tabela, não com código novo.
- Guarde, para cada versão medida, o que a receita estática achou (nome da dylib no `dlopen`, presença do ARO, slots).
Depois do 25.12 funcionar: medir o **MC 2021** (e o 24.6) — nome/caminho da dylib pelo `GetAROserver`, se o ARO está
compilado, e reconferir o contrato. E o **Windows** (`AvidRemoteObjects364.dll`?). Encaixe: ARO como ponte/plano B para
o antigo e para os buracos; gRPC como principal no MC moderno.

## Plano de execução sugerido (incremental, cada passo com o MC pilotado no lab)

0. **Pré-requisito do teste:** abrir o MC no projeto de lab **com um PROJETO e uma TIMELINE abertos** e alguns
   segmentos selecionados (o passo 1/1.5 testou só na tela de projetos; as `TLW_*` precisam de uma timeline viva).
1. **Main thread + socket:** estender `aro_sonda.c` (ou um `aro_servidor.c` novo) para subir um listener TCP em
   `127.0.0.1` no constructor e provar o `dispatch_async(main)` — um comando "PING" que roda na main e responde. Logar
   `pthread_main_np()` para confirmar a thread. (ARO_Init pode recusar.)
2. **As três interfaces + MCapp_Timeline:** implementar in/srv/out e o comando "TIMELINE" → devolve o objectID. Provar
   que o `map` pegou a janela.
3. **A contagem e a lista:** "NUMSEL" e "SEL" → a contagem e os cids. Testar com 0 e com N selecionados.
4. **Nome/tipo:** "NAME <cid>" → resolver o AddString. Montar a identidade.
5. **A identidade estável** (pergunta #1) → a lista de MobIDs.
6. **Ligar no app:** um novo `/mc/selecao-aro` (ou uma opção dentro do `/mc/selecao`) que fala com o socket da dylib em
   vez do Cmd+C; o resto (`so_masters` → `filtrar_masters`) já existe. O botão "Carregar a seleção da timeline" passa a
   usar esse caminho quando a dylib está presente, e cai no Cmd+C quando não está.
7. **Multiversão** (a visão maior, acima): com o 25.12 funcionando, medir o **MC 2021** e o **24.6** (nome/caminho da
   dylib no `GetAROserver`, presença do ARO, slots) e o **Windows**. Resolver funções por nome; isolar o "por versão"
   num mapa. É aqui que o ARO deixa de ser "a seleção no 25.12" e vira "controle do MC em qualquer versão".

## Segurança, higiene e riscos

- ⛔ **Só no projeto de LABORATÓRIO** (LAB_ARRASTO_MAC ou um sintético). Erro no vtable/interface pode FECHAR o MC —
  aceitável no lab (memória `projetos-de-teste-sao-descartaveis`), nunca em trabalho ativo.
- **Pilotar** (o autor ausente autorizou para esta linha): abrir o MC por `apps.abrir("avid")` (tira o `LANG` que faz o
  MC abortar); foto antes/depois; se o MC cair, foto do diálogo e seguir. O servidor-escuta sobe na abertura, ANTES da
  tela de projetos — mas as `TLW_*` precisam de timeline aberta (passo 0 acima).
- **Socket só em `127.0.0.1`**, sem exposição externa (mesma regra do serviço do app). Nada de aceitar comando de fora
  da máquina.
- **Ao terminar cada teste, REMOVER a dylib** de `/Library/Application Support/Avid Internal/` (o MC volta ao normal);
  reinstalar = `tools/aro/compilar.sh`. A pasta (criada com senha uma vez) pode ficar vazia.
- O método (as interfaces, os slots, o encadeamento) vai para o **banco**; o script fica em `tools/aro/` (só lab), não
  no produto, até funcionar. Quando virar função, o app decide se é opção ligada só quando a dylib existe.
- **Atualização de versão do MC:** reconferir os endereços e os slots pela receita estática (banco, "O contrato do
  ARO"); preferir resolver as funções POR NOME nas tabelas de `RegisterClass` (robusto) a cravar endereços.

## Estado dos arquivos ao encerrar (2026-10-25)

- `tools/aro/aro_sonda.c` (passo 1.5, servidor-escuta), `tools/aro/compilar.sh` (gera `aro_stubs.h`, compila, instala),
  `tools/aro/.gitignore` (ignora a `.dylib`, o `aro_stubs.h`, `*.o`). Commits `0cac61a`, `dfa21d9`.
- Banco: `f98b2a8` (contrato confirmado em execução) + os anteriores (`87272e3`, `2b6f1cd`).
- A dylib **não está instalada** (removida ao fim do teste). O MC está no estado normal.
- Log do teste do passo 1.5 salvo em `scratchpad/aro_sonda_rodada_1_5.log` (efêmero; o essencial está no banco).
