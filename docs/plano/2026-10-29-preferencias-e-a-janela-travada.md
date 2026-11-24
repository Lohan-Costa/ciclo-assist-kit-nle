# Preferências do editor e a janela que travou (2026-10-29)

Dois assuntos que saíram do teste do PRODUCAO-C → Resolve pelo chat. O primeiro é PROPOSTA (autor: "só anote,
não implemente"); o segundo é um ESTUDO em aberto.

---

## 1. Proposta: as preferências do editor (não implementado)

### O que o autor disse

- A regra "MC e Resolve nunca abertos juntos" é **do nosso ambiente** (este notebook), não do produto. O produto não a
  deve ter. ⇒ Ela não entra no código do Ciclo Assist; se um dia valer para alguém, é uma preferência DELE.
- *"Leve este projeto para a cor"* pode ter, nas configurações, um **app preferido para cor** (aqui, o Resolve). Quando
  o pedido não diz o programa **e** o contexto não diz, a preferência decide.

### Como a regra de hoje fica com isso

Hoje (`abrir_programa`, `3589d83`): sem o nome do programa no texto do editor, a conferência manda perguntar — mesmo
no automático. Com preferências, a ordem de decisão passa a ser:

1. **O editor disse** o programa na pergunta → vale o que ele disse.
2. **O contexto diz** → vale o contexto. Exemplos: a conversa já está em um programa (o Resolve aberto e conectado);
   o editor respondeu a uma pergunta nossa no turno anterior ("Sim, no DaVinci Resolve").
3. **A preferência diz** → vale a preferência, e a resposta **conta** que usou ("abri o Resolve, o seu programa de cor
   nas preferências"). Preferência calada vira a mesma surpresa que o palpite.
4. **Nada disse** → pergunta (o comportamento de hoje), e a pergunta oferece gravar a resposta como preferência.

⚠️ O passo 2 precisa de cuidado: "contexto" não é o tipo do arquivo arrastado (um `.prproj` não quer dizer
"Premiere"). Contexto é o que o EDITOR já fez ou disse nesta conversa.

### O que a tela de preferências teria (rascunho)

| preferência | exemplo | usada por |
|---|---|---|
| programa por **papel** | cor → DaVinci Resolve · montagem → Media Composer · finalização → … | `abrir_programa`, `conformar_no_resolve` |
| nome do projeto novo | "o nome da sequência" · "o nome do arquivo" · "perguntar" | `abrir_programa` |
| programas que **não convivem** nesta máquina | MC × Resolve (o caso do autor) | `abrir_programa`: oferece fechar o outro, nunca fecha sozinho |
| ajustar escalas de outra mídia | sim / perguntar | `conformar_no_resolve` (hoje sempre sim) |
| conferir pela referência | sempre / só quando houver vídeo | `conformar_no_resolve` |

Moraria no `config.json` (a engrenagem do Assistir), com a mesma regra das outras escolhas: lista fechada, porque vira
argumento de ferramenta. ⬜ Desenhar a tela e decidir onde o "papel" de um pedido é reconhecido (vocabulário fixo
— "cor", "color", "grade", "finalizar" — ou o modelo classifica e o código confere).

---

## 2. Estudo: a janela do Ciclo Assist travou (em aberto)

### O que aconteceu (sessão de 18:29, pid 3900)

- 18:31–18:33 o conform rodou e terminou bem (log do DLPC: conferência fechou às 18:33:04).
- 18:34 o piloto tirou o TOPMOST da janela (`SetWindowPos`, devolveu 1) e devolveu o foco ao terminal.
- ~40 min parada. Logs do serviço do Assist e do DLPC **mudos** nesse intervalo.
- 19:14:5x o Resolve foi encerrado pela API (`Quit`) e, logo em seguida, o piloto mandou `WM_CLOSE` à janela.
- 19:15 a janela **não fechou**; `IsHungAppWindow` = **verdadeiro**; o X ficou vermelho ao passar o mouse e não fechou.
- 19:16 o `abrir.ps1` a matou (é o que ele faz por desenho).

### O que a evidência já diz

- ⭐ **O fechamento nunca foi processado.** O `Destroyed` chama `parar_motores`, que encerra PRIMEIRO o Órbita
  (`Modulo::TODOS` começa por Preparar). O motor do Órbita daquela sessão (pid 1532, de 18:29) **sobreviveu** — está
  vivo até agora. ⇒ A thread da janela já estava presa antes do `WM_CLOSE`, ou presa no caminho do fechamento ANTES
  do `Destroyed` (a destruição das quatro webviews filhas).
- O Windows **não registrou** nada (Application log sem 1000/1001/1002 de `cicloassist.exe` nem do WebView2).
- Descartados no código: os comandos síncronos do Tauri são triviais (`estado_do_topo` só lê estado); o `conexao`
  é `async`; as travas do `EstadoApp` são soltas antes de mexer na janela (sem deadlock por `Mutex`).

### O que NÃO reproduziu (sessão de 19:16, pid 15012, a mesma sequência)

| tentativa | resultado |
|---|---|
| conform + TOPMOST posto e tirado + foco devolvido + 1 h parada | respondendo (`WM_NULL` em 0 ms, 20:22) |
| encerrar o Resolve pela API com a janela aberta, vigiando 3 min | respondendo o tempo todo |
| `WM_CLOSE` com vigia | fechou em < 10 s; motores Python saíram junto |

⚠️ Uma diferença entre as sessões: na de 18:29 o motor do Órbita era FILHO do app; na de 19:16 o app achou a 7817
ocupada (o órfão) e não o subiu. O caminho de fechamento não foi o mesmo.

### Hipóteses abertas, da mais provável para a menos

1. A destruição das webviews (WebView2) prendeu a thread no fechamento — com o Órbita filho, ou com uma das páginas
   (Conformar, depois da conferência) em algum estado.
2. Algo durante os 40 min parados prendeu a thread (sem nenhuma atividade nos logs, nada apontou).
3. Interação do piloto (TOPMOST de outro processo, `SetForegroundWindow`/`AttachThreadInput` do `devolver_ao_terminal`).

### O que fazer para pegar o próximo no ato (⬜, nada implementado)

- **Log em arquivo do app Rust** (hoje é `eprintln!`, que sem console some): `CloseRequested`, `Destroyed`, cada
  `parar_motores` (quem, kill, wait, quanto levou), troca de aba, pino. Sem isso não há como saber onde parou.
- **Vigia de travamento** no serviço do Assist (ele já vigia o pai pelo `--pai`): a cada ~10 s um
  `SendMessageTimeout(WM_NULL)` à janela do app; travada por > 15 s → gravar um **minidump** do app
  (`MiniDumpWriteDump` com as pilhas das threads) e dizer no log. O dump mostra onde a thread da janela está presa.
  O roteiro do vigia usado hoje está no scratchpad da sessão (`vigia_trava.py`): `WM_NULL` + `IsHungAppWindow`.
- **Repetir com o Órbita filho**: abrir o app com a 7817 livre, conform, fechar — a combinação que não foi testada.
- **O órfão do Órbita:** o app morto à força deixa o `orbita.exe --motor` vivo (ele não vigia o pai). Já se sabia;
  agora causou uma diferença de estado entre duas sessões. Vale dar a ele o mesmo `--pai` dos motores Python.

### ✅ 2026-10-30 — a instrumentação está no ar (`f7f4f73`)

- **`logs/app.log`** (o app Rust, `app/src-tauri/src/registro.rs`): hora local e thread em cada linha; abrir, motor
  subido (pid), `CloseRequested`, `Destroyed`, cada motor encerrado (kill, wait, ms), aba, pino, reinvocações.
- **O pulso da thread da janela** (no app): a cada 5 s pede à thread da janela para anotar a hora; > 15 s sem anotar
  → "⛔ a thread da JANELA não atende há N s"; ao voltar, quando a trava começou.
- **O vigia do serviço** (`cicloassist/servico/travamento.py`): `WM_NULL` com `SMTO_ABORTIFHUNG` a cada 10 s; presa
  > 15 s → **minidump** (`MiniDumpWriteDump`, pilhas de todas as threads) em `logs/travamentos/`; ao voltar, quanto
  tempo ficou presa. Um dump por episódio.
- **Provado** suspendendo a thread da janela por 35 s (07:25:18 → 07:25:53): o vigia disse "não respondeu" em 3 s,
  "TRAVADA há 26 s" com o dump (928 KB) e "voltou depois de 36 s"; o pulso disse "presa" aos 15 s e "voltou".

⬜ **Ler o dump** precisa de um depurador (WinDbg, da Microsoft Store, ou o Visual Studio): `~*k` mostra a pilha de cada
thread; a da janela é a `main`. Nenhum está instalado nesta máquina.
⬜ **O Órbita órfão confirmado de novo** (2026-10-30 07:26): o app morto pelo `abrir.ps1` deixou o `orbita.exe --motor`
vivo, e o app novo não subiu o seu ("motor de preparar" ausente no `app.log`). Dar ao Órbita o `--pai`.
⬜ Repetir o fechamento com o Órbita FILHO do app (a combinação que não foi testada), agora com tudo gravando.

## ✅ 2026-10-30 — A CAUSA, pega no ato: deadlock de reentrada no `tao` 0.35.3

Repetida a sequência original (conform pelo chat, Órbita FILHO do app), a janela travou às **07:35:52**, ~9 s depois de
o piloto tirar o TOPMOST e devolver o foco ao terminal. O vigia gravou o dump às 07:36:12; `tools/ler_travamento.py`
(cdb do WinDbg) leu a pilha da thread da janela:

```
DispatchMessageW → tao public_window_callback (mensagem de TECLADO)
  → KEY_EVENT_BUILDERS.lock()  ← a trava é pega AQUI (event_loop.rs ~976)
  → KeyEventBuilder::process_message → PeekMessageW
      → o Windows entrega ali uma mensagem ENVIADA por outra thread (troca de foco)
      → tao public_window_callback de novo → KEY_EVENT_BUILDERS.lock()  ← a MESMA thread espera a si mesma
```

- O gatilho: o `frente()` do piloto solta um ALT antes do `SetForegroundWindow` (o truque que libera a troca de foco);
  com o Assist na frente, o ALT é tratado por ELE no instante em que o foco sai. É a sequência de um **Alt+Tab do
  editor** — o defeito é do produto, não só do piloto.
- Não reproduziu por estresse sintético (150 voltas de foco/TOPMOST; 300 voltas de ALT + troca de foco com atraso
  0–30 ms): nos dois casos reais um turno do chat tinha ACABADO de terminar (a webview redesenhando), ingrediente que
  o estresse não tem. A prova é o dump.
- **O conserto é do `tao`:** no 0.37 a trava global saiu (o construtor de teclado é da janela) e `keyboard.rs` ganhou a
  fila `PendingEventQueue`, cujo comentário descreve este caso ("PeekMessageW can also call the event handler").
  `cargo update -p tauri --precise 2.12.5` traz `tao` 0.37.2 + `wry` 0.57 + `windows` 0.62; o nosso `Cargo.toml`
  sobe junto (`webview2-com` 0.39, `windows`/`windows-core` 0.62) e `tauri-plugin-opener`/`single-instance` para uma
  cópia só do `windows`. Compila, testes 3/3. O patch está em `docs/plano/2026-10-30-tauri-2.12-tao-0.37.patch`.

### ⛔ E o que impediu aplicar: o Smart App Control do Windows

O executável da build nova foi **barrado** ("An Application Control policy has blocked this file"; CodeIntegrity
3077/3033, política `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`, `VerifiedAndReputablePolicyState = 1` = LIGADO). A
build com as dependências antigas roda (o mesmo código nosso). O SAC decide por reputação na nuvem: binário novo,
sem assinatura, cai. ⇒ As dependências voltaram às que rodam; o patch espera a decisão do autor:
desligar o SAC (Segurança do Windows → Controle de aplicativos e do navegador), assinar as builds, ou tentar de novo
(a reputação pode mudar). ⬜ Também não foi possível ver a build nova rodando: o conserto está provado no CÓDIGO do
`tao`, não na tela.
