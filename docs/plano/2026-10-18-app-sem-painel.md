# Media Composer sem painel encaixável — o Assist pela janela do app (decisão do autor, 2026-10-18)

## A decisão

**No Avid, o painel encaixável (`.avpi`) sai.** O Assist passa a ser uma janela do app, operando o MC por fora
(gRPC 9100), como o De Lá Pra Cá provou em 2026-10-18 (relink do PRODUCAO-A e o PRODUCAO-C pela janela do app,
MC 2024.6). Por quê:

- painel não-assinado só aparece no MC 25.6 → 25.12.0; o 24.6 e o 25.12.2 o escondem (filtro do host; a assinatura
  é criptográfica — banco `plugins/avid-panel-sdk/ativar-no-2021-ftf.md`);
- o 9100 responde de fora sem token nem painel (Teste B, 24.6 Windows; 25.12.0 Mac 60/60 RPC);
- a janela do app não tem as amarras do painel (Chrome do hospedeiro, tamanho, repintura do QtWebEngine).

## A hipótese a provar: a IA responde igual dentro e fora

Conferido no código em 2026-10-18: **as ferramentas do Assist operam o MC pelo serviço** (`servico/rotas.py` →
`avid/mcapi.py`, 9100), não pelo painel; e **o painel não ouve eventos do MC** (nenhum `onEvent` /
`BinRowSelectionChanged` em `painel/painel.js`). ⇒ o modelo enxerga e age igual — a tela só muda de lugar.

## O que o painel fazia além de ser tela — portar ANTES do teste

1. **O arrasto é a AUTORIZAÇÃO de leitura** (`servico/arrastados.py`, ADR 0005: só é legível o que o editor
   arrastou). Na janela do app, o drop da webview NÃO serve — medido no De Lá Pra Cá (2026-10-18, MC 24.6/Windows):
   - soltar uma sequência do MC num WebView2 faz o **MC EXPORTAR** o `.aaf` virtual do arrasto (diálogo modal
     "contains offline media. Continue exporting or abort?", que trava até o Explorer);
   - o arquivo do Explorer chega **sem caminho**.
   ⇒ portar o alvo nativo do De Lá Pra Cá: `_DeLaPraCa/app/src-tauri/src/arrasto_win.rs` (IDropTarget próprio;
   `SetAllowExternalDrop(false)`; lê SÓ `text/x.avid.mc-api-asset-list+json`, ou `CF_HDROP` do Explorer; bin do painel
   lateral = aviso) + a ponte `window.delapracaArrasto` do `painel.js` de lá (vira o MESMO `dataTransfer`). O
   `CF_HDROP` também diz pasta × arquivo — a regra "pasta não autoriza o conteúdo" fica mais firme. Banco:
   `avid-panel-sdk/arrastar.md` §"Soltar timeline do MC numa WEBVIEW comum". ⏳ Mac: medir.
2. **MC 2024 (24.6) pela API** — não é do painel, é da versão; portar os contornos do De Lá Pra Cá (`avid/mcapi.py`,
   `avid/acoes.py` de lá): `GetViewerMobs` sem `view_type` (o Record vem como 0 — critério: o mob do monitor que é
   sequência), sem `DoCommand` (Save = `CloseBin` + reabrir + devolver a timeline ao Record), `rpcs()`/`tem()` pela
   reflection, `LinkFile` não aceita caminho com acento e Broadcast WAV abre modal (injetar o áudio).
3. A janela do app ganha o **pino** (sempre na frente) — o editor clica na bin e o app não some.

## O teste (depois de 1 e 2)

Texto de modelo varia; comparar o que ele **FEZ**, não o que escreveu:

- 8–10 pedidos fixos do dia a dia (buscar plano, montar subclipe, ler uma bin, ler um roteiro arrastado, levar à
  Record…), MESMO projeto e MESMO estado do MC;
- cada pedido 3× DENTRO do painel (num MC que o mostre: 25.6 ou 25.12.0) e 3× na JANELA do app;
- pelo `servico/diario.py`: ferramentas chamadas, argumentos, e o resultado no MC (bin/monitor). Iguais = hipótese
  provada; diferentes = o diário diz onde.

## Fora do Avid (mesma análise, 2026-10-18)

Resolve Studio (só a versão paga importa) também opera de fora (`fuscript`) — mesmo grupo do MC; o Premiere não tem API
externa: precisa de ponte fina (painel invisível que suba sozinho — a medir). Registro: handoff do De Lá Pra Cá.

## 🎯 Prazo: demonstração na sexta, 2026-10-23 (pedido do autor, 2026-10-21)

O autor vai demonstrar os apps; o mínimo aqui é o **agente (aba Claude) pela janela do app**, no formato do De Lá Pra
Cá. O que falta além dos itens 1–3 acima: o Assist **não tem janela própria** (é serviço + painel servido em 7824) ⇒
precisa da casca do DLPC (`_DeLaPraCa/app/src-tauri`: janela única que navega para o painel quando a porta atende +
`arrasto_win.rs`). No Premiere, trocar o `painel_cep` pela extensão invisível do DLPC (`plugins/premiere/cep/`).
⚠️ `iniciar.vbs` aponta para o caminho antigo (`PROGRAMAS COM CLAUDE\_CICLO ASSIST`, antes de `2 ATIVOS`). Ordem: depois do Órbita.

➡️ O mapa inteiro (o guarda-chuva de quatro abas, a unificação de tecnologia, F0–F4): [2026-10-21-assist-standalone.md](2026-10-21-assist-standalone.md).

## ✅ F0, parte 1 — a janela existe (2026-10-21, noite, Windows 11; sem MC aberto)

`ABRIR-APP.bat` (→ `app/abrir.ps1`: compila com `CARGO_TARGET_DIR` em `%LOCALAPPDATA%\CicloAssist-build`, e abre).

| peça | onde | medido |
|---|---|---|
| a casca (a do DLPC enxugada: janela única, geometria lembrada, `single_instance`) | `app/src-tauri/src/lib.rs` | `cargo build` sem aviso; `cargo test` 1/1 |
| sobe o serviço `-m cicloassist.servico --app <exe> --pai <pid>` | `lib.rs` + `servico/aplicativo.py` | porta em **1,4 s**; os DOIS processos (lançador do venv + Python real) |
| vai ao painel (`/painel?casca=app`) | `lib.rs::ir_para_o_painel` | ✅ visto na foto: painel inteiro, ponto verde, o pino no topo |
| o pino | `/app/fixar` → `--fixar`/`--soltar` | `WS_EX_TOPMOST` liga e desliga |
| fechar | `/app/fechar` ou `--encerrar` | app + serviço fora em 0,4 s, porta livre |
| app morto à força (Gerenciador de Tarefas) | `aplicativo.vigiar` | serviço sai sozinho em **1,5 s**, zero órfãos |
| o arrasto nativo | `app/src-tauri/src/arrasto_win.rs` (a versão do Órbita) + `window.cicloArrasto` no `painel.js` | ⬜ **NÃO visto**: precisa do MC/Explorer na tela. A conversão caminho → `uri-list` → caminho tem teste (acento, `#`, `%`, UNC) |
| o ícone | `tools/gerar_icone_do_app.py` (Chrome headless; ⚠️ o ffmpeg daqui não decodifica SVG, e o headless sem `--force-device-scale-factor=1` cortava a borda) | visto |

Testes: `tests/test_aplicativo.py` (9). Suíte: 1203 passed, 4 skipped.

### ✅ Pilotado com o MC 24.6 aberto (2026-10-21, tarde; projeto DLPC PRODUCAO-A 2024)

- **Conversa pela janela**: "Que bins existem neste projeto?" → as 29 bins, 8,6 s. Com anexos: "quem fala no roteiro
  e quantas trilhas tem a sequência" → *Personagem F e Eduardo*; *4 trilhas de vídeo (V5 e V6 vazias)* — bate com a tela. 11 s.
- **O arrasto nativo, os três**: MASTERCLIP (verde-água), SEQUENCE (verde-água, **sem o export de AAF**) e ARQUIVO do
  Explorer (violeta, acento intacto). Arrasto SINTÉTICO pelo piloto — o banco dizia que não chegava; para alvo
  nativo chega (registrado em `avid-panel-sdk/arrastar.md` §7c).
- **Carregar no Source (o duplo clique da Busca) no 24.6**: entra, mas o MC pendura ~30 s; com o prazo de 20 s a
  Busca dizia "não consegui" e carregava DE NOVO. ⇒ `TEMPO_DE_CARREGAR_S = 90`. Conferido: `True` em 30,5 s.

### Falta para sexta

1. ✅ (`c4990b5`, visto ao vivo: "já está" em 1,0 s, 2º clique 0,8 s) **"Já está no Source" no 24.6**: o `GetViewerMobs` devolve para o Source um mob que não é o master (banco,
   `ativar-no-2021-ftf.md`). Clicar duas vezes no mesmo clipe cai em "abrir a bin e carregar de novo" (mais 30 s de
   MC pendurado). Medir o que é esse mob antes de mexer.
2. ✅ (`c4990b5`) A tela de "carregando no Source" fica 30 s sem dizer por quê — avisar que o MC está abrindo a mídia.
3. ✅ (`c4990b5`) O espaço que falta entre dois blocos de texto da resposta ("os dois.No roteiro") — do turno, não da janela.
4. ✅ **Premiere pela ponte invisível** (2026-10-21, Premiere 23.6, pilotado, projeto ORBITA PAINEL DEMO):
   `ponte_cep/` (extensão SEM tela, sobe com o Premiere) → `/premiere/ponte` (`painel/ponte.html` + `ponte.js`);
   `tools/instalar_cep.py` põe a ponte e tira o painel antigo (`--painel` faz o contrário — as duas juntas
   disputariam o long-poll). A janela pergunta à `/conexao` e troca sozinha para o Premiere (seletor no topo com os
   dois ligados). Visto: bins do projeto pela conversa; a pasta D02 ARRASTADA do Premiere virou chip `BIN D02` e
   "26 clipes de câmera e 24 de som" (os números do Órbita); a ponte volta sozinha depois de o serviço reiniciar.
   No painel: `CEP` = tenho evalScript; `NO_PREMIERE` = falo do Premiere.
   ⬜ Não exercitado na janela: o duplo clique da Busca no Premiere (`openProjectItem`, `hipotese` no banco).
5b. ✅ O aviso "esta conversa continua de antes" mentia depois de reiniciar o app (visita nova = conversa nova) e
   ao trocar de NLE (fio do outro editor) — `_fio()` e `mostrarOFio`.
5. ⬜ Fechar no meio de um turno: o DLPC pergunta antes (`dlpcAoFechar`) — trazer se o autor quiser.
6. ⚠️ Este MC mostra `std::exception` no lugar da imagem nos monitores (erro de hardware de vídeo na partida) — é da
   máquina, mas vale ver antes da demo.
