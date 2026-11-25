/* De Lá Pra Cá — painel do Media Composer.
 *
 * Esta página é servida pelo próprio serviço (`GET /painel`), então é SAME-ORIGIN com
 * a API: sem CORS, sem preflight, sem token. Ver `api/portao.py`.
 */
"use strict";

/* O painel do MC não tem console à vista: erro de script e promessa rejeitada sem dono vão para o log do serviço
   (`/diag/erro`). Sem isto, um botão que "não faz nada" não diz por quê (2026-10-12, o "Carregar sequência"). */
function reportarErro(msg, onde, pilha) {
  try {
    fetch("/diag/erro", { method: "POST", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ msg: String(msg || ""), onde: onde || "", pilha: pilha || "" }) })
      .catch(() => {});
  } catch (_) { /* nada a fazer */ }
}
window.addEventListener("error", (e) =>
  reportarErro(e.message, `${e.filename || ""}:${e.lineno || ""}:${e.colno || ""}`, e.error && e.error.stack));
window.addEventListener("unhandledrejection", (e) =>
  reportarErro(e.reason && e.reason.message || e.reason, "promessa", e.reason && e.reason.stack));

const ABAS = ["deLaPraCa", "daquiPraLa", "ajustes"];
const CHAVE_ABA = "delapraca.mc.aba";
const CHAVE_PASTAS = "delapraca.mc.pastas";

/* `?vista=revisao` vem do SEGUNDO uiItem do manifesto: uma janela própria, mais
   larga, só para resolver pendências. A lista de conflitos precisa mostrar dois nomes
   de arquivo lado a lado, e a janela principal é estreita de propósito.
   ⚠️ Declarado aqui, no topo: `const` tem zona morta temporal, e `carregarRevisao()`
   o lê — deixá-lo no fim do arquivo funcionava só pela ordem em que as coisas são
   chamadas hoje. */
const VISTA_REVISAO =
  new URLSearchParams(location.search).get("vista") === "revisao";
/* `?vista=configuracoes`: a janela ⚙ Configurações do APLICATIVO (cache e logs — organograma de
   2026-10-05). Mesma página, só o `#paneConfig`. */
const VISTA_CONFIG =
  new URLSearchParams(location.search).get("vista") === "configuracoes";
/* `?ajustes=1`: os Ajustes deste módulo na JANELA DE CONFIGURAÇÕES do Ciclo Assist (autor, 2026-11-07: a engrenagem
   abre uma janela própria, com uma seção por módulo). Mesma página, só o `#paneAjustes`, e nada de trabalho: quem
   trabalha é a aba Conformar da janela principal. */
const VISTA_AJUSTES = new URLSearchParams(location.search).get("ajustes") === "1";
/* ⭐ Na janela de configurações também entram os blocos do `#paneConfig` (o LOCAL e o TETO do cache, o diagnóstico, os
   logs): a janela ⚙ da casca antiga, que os mostrava, saiu na fase 2 — e o local do cache ficou sem lugar (2026-11-07). */
const CONFIG_VISIVEL = VISTA_CONFIG || VISTA_AJUSTES;
/* A revisão de mídias DENTRO da janela única do app (organograma aprovado em 2026-10-19): `{passo}` de onde se veio,
   ou `null` fora dela. Na casca do Resolve e no painel do Avid a revisão continua sendo a janela larga separada. */
let revisaoNaJanela = null;

/* ⭐ Em que NLE este painel está aberto. O MESMO painel serve a todos: o `.avpi` do Media
   Composer abre `/painel` (sem parâmetro = "mc", o de sempre) e a casca do Resolve abre
   `/painel?nle=resolve`. O que só um NLE sabe fazer é marcado `data-so` no HTML e some nos
   outros; o que o NLE precisa EXECUTAR lá dentro (importar a timeline) vai pela ponte que a
   casca expõe em `window.delapraca`. Lista fechada: um valor desconhecido vira "mc". */
const NLE = ["mc", "resolve", "premiere", "baselight"].includes(new URLSearchParams(location.search).get("nle"))
  ? new URLSearchParams(location.search).get("nle") : "mc";
document.body.dataset.nle = NLE;
/* ⭐ O modo Premiere (organograma aprovado pelo autor, 2026-10-19) tem o layout de QUEM RECEBE do Resolve; o que é do
   Resolve mesmo (a casca, o DRT, a conferência) continua testando `NLE === "resolve"`. */
const RECEBE = NLE === "resolve" || NLE === "premiere" || NLE === "baselight";
/* ⭐ O Baselight (proposta 2026-11-22-baselight-no-app, etapa 2): o colorista RECEBE — a timeline + as pastas dos
   originais, e o Importar conforma numa scene nova do job da produção (`baselight_conform.py` no serviço). */
const BASELIGHT = NLE === "baselight";

/* ⚠️ O Resolve 19 hospeda o painel no Chrome 80, que não tem `gap` em flex (Chrome 84): a
   declaração some calada. Detecta-se pelo efeito, não pela versão, e o CSS liga a reserva
   de margens (`html.sem-flex-gap`, fim do painel.css). */
(function detectarFlexGap() {
  const d = document.createElement("div");
  d.style.cssText = "display:flex;flex-direction:column;row-gap:1px;position:absolute;visibility:hidden";
  d.appendChild(document.createElement("div"));
  d.appendChild(document.createElement("div"));
  document.body.appendChild(d);
  const tem = d.scrollHeight === 1;
  d.parentNode.removeChild(d);
  if (!tem) document.documentElement.classList.add("sem-flex-gap");
})();

/* O que o editor arrastou da bin: `{itens: [{mob_id, nome}], escolhido: mob_id}`.
   É uma LISTA porque arrastar várias timelines de uma vez é o gesto que substitui
   arrastar a bin (que o Media Composer não entrega — ver a seção do arrasto).
   ⚠️ Declarada AQUI, no topo, pelo mesmo motivo do `VISTA_REVISAO` acima: `let` tem zona
   morta temporal, e quem a lê é `carregarSequences()`, que aparece antes no arquivo.
   Deixá-la junto das próprias funções funcionaria só pela ordem em que as coisas são
   chamadas hoje — e essa ordem não é contrato. Ver `aplicarArrastada`. */
let arrastada = null;
/* A bin de FORA (outra máquina, Magic Link): `{caminho, sequencias, escolhido}` — `/mc/bin/ler`. Modo interno `bin`. */
let binExterna = null;

const el = (id) => document.getElementById(id);
const nomeDe = (c) => String(c).split("/").pop();

/* ── Conversa com o serviço ────────────────────────────────────────────────────
   `fetch` só rejeita em falha de rede: um 401 ou 409 chega como resposta "bem
   sucedida", e um `.then(r => r.json())` ingênuo entrega o corpo do erro como se
   fosse resultado. Por isso o status é conferido aqui, num lugar só. */
async function api(caminho, opcoes) {
  const r = await fetch(caminho, opcoes);
  const corpo = await r.json().catch(() => ({}));
  if (!r.ok) {
    const erro = new Error(corpo.erro || `HTTP ${r.status}`);
    // O status vai junto: há chamador que precisa distinguir "não deu" de "não existe"
    // — um 404 no `/mc/mob` significa que o mob sumiu do projeto, e aí seguir em frente
    // levaria a exportar coisa nenhuma.
    erro.status = r.status;
    erro.corpo = corpo;
    throw erro;
  }
  return corpo;
}

/* ⛔ O painel do MC às vezes NÃO LEVA À TELA o que mudou (MC 25.6, Windows, painel solto, 2026-10-12): o DOM e o
   quadro da página estão certos (`visibilityState` "visible", `requestAnimationFrame` em 7 ms), mas a janela do MC
   segue mostrando o quadro velho — passar o mouse ou clicar num vazio não resolve; trocar de aba resolve. Visto em
   ~1 de 5 "Carregar sequência" logo depois de abrir a bin (o editor via o botão "não fazer nada"). Remédio: a cada
   mudança no DOM, um quadro com a página INTEIRA marcada como alterada (opacidade que não se vê, ida e volta). */
if (NLE === "mc" && "MutationObserver" in window) {
  let pedido = false;
  const repintar = () => {
    if (pedido) return;
    pedido = true;
    requestAnimationFrame(() => {
      document.documentElement.style.opacity = "0.999";
      requestAnimationFrame(() => { document.documentElement.style.opacity = ""; pedido = false; });
    });
  };
  new MutationObserver(repintar).observe(document.body || document.documentElement,
    { childList: true, subtree: true, attributes: true, characterData: true });
}

const post = (caminho, dados) => api(caminho, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(dados || {}),
});

/* Nome de clipe e caminho são texto que alguém escolheu — um master chamado
   `<img onerror=…>` não deve virar markup só porque o exibimos. */
/* Texto arbitrário → seguro para HTML, **inclusive dentro de atributo**.

   ⚠️⚠️ `textContent → innerHTML` escapa `&`, `<` e `>` e **NÃO escapa aspas** — e este
   painel usa o resultado dentro de atributos (`data-arquivo="${escapar(caminho)}"`).
   Um arquivo chamado `a".onerror="alert(1)` fecharia o atributo e injetaria um handler.

   ⚠️ E não é hipótese de laboratório: no **macOS aspas são LEGAIS em nome de arquivo**
   (no Windows não), o painel roda nos dois, e o acervo vive em storage compartilhado de
   produção — o nome do arquivo é entrada de terceiro, não dado nosso.

   Guia de Desenvolvimento Seguro, §6 (XSS): sanitizar entrada **e saída**. */
function escapar(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function dizer(texto, ok) {
  const m = el("msg");
  m.textContent = texto || "";
  m.className = "msg" + (texto ? (ok ? " ok" : " er") : "");
}

/* ── Abas ─────────────────────────────────────────────────────────────────────
   "ajustes" nunca é a aba restaurada: quem reabre o painel quer trabalhar. */
function lerAba() {
  try {
    const salva = localStorage.getItem(CHAVE_ABA);
    // Fora do Media Composer o Daqui Pra Lá ainda diz "em breve": quem reabre quer trabalhar.
    if (NLE !== "mc" && salva === "daquiPraLa") return "deLaPraCa";
    if (ABAS.includes(salva) && salva !== "ajustes") return salva;
  } catch (_) { /* localStorage pode estar indisponível; o default resolve */ }
  return "deLaPraCa";
}

function irPara(aba) {
  const nome = (a) => a[0].toUpperCase() + a.slice(1);
  for (const a of ABAS) {
    el("tab" + nome(a)).classList.toggle("on", a === aba);
    el("pane" + nome(a)).classList.toggle("on", a === aba);
  }
  // ⛔ A janela de configurações não grava a aba: o localStorage é o MESMO da aba Conformar, e ela reabriria nos ajustes
  if (!VISTA_AJUSTES) {
    try { localStorage.setItem(CHAVE_ABA, aba); } catch (_) { /* idem */ }
  }
  if (aba === "ajustes") carregarAjustes();
  pintarBarraMC();
}

/* ── Passos ───────────────────────────────────────────────────────────────── */
const PASSOS = ["passoOrigem", "passoRevisao", "passoProgresso", "passoFeito"];
function mostrarPasso(id) {
  for (const p of PASSOS) el(p).hidden = p !== id;
  pintarBarraMC();
}

/* As ações do MC no rodapé fixo: só no passo de origem, na aba De Lá Pra Cá, fora do Atualizar. */
function pintarBarraMC() {
  const caixa = el("mcAcoesBarra");
  if (!caixa) return;
  const aba = el("paneDeLaPraCa") && el("paneDeLaPraCa").classList.contains("on");
  caixa.hidden = NLE !== "mc" || !aba || el("passoOrigem").hidden || modoOrigem === "atualizar";
  ajustarBarra();
}

/* ── Pastas de mídia ──────────────────────────────────────────────────────────

   ⛔ **A lista NÃO sobrevive ao fechamento nem ao Reload do painel** (decisão do
   usuário, 2026-08-16). Ela ficava no `localStorage` com a intenção certa — o editor
   relinka a mesma novela por semanas — e o efeito era outro: pastas de ontem
   reaparecendo hoje, inclusive depois de um Reload feito só para carregar build nova.
   Uma lista que o editor não pôs ali é pior que uma lista vazia, porque ele relinka
   **contra um acervo que não escolheu** e nada na tela denuncia isso.

   ⭐ E a intenção original não se perde: quem tem de lembrar do acervo é o **banco de
   mídia**, que é por PRODUÇÃO e viaja com o projeto — não o navegador de uma máquina.
   O lugar certo para essa memória existe agora; esta aqui era um substituto pobre. */
let pastas = [];

function lerPastas() {
  // Limpa o que versões anteriores gravaram: sem isto a lista velha ressuscitaria uma
  // única vez, no primeiro Reload depois da atualização — o pior momento para confundir.
  try { localStorage.removeItem(CHAVE_PASTAS); } catch (_) { /* sem storage, tudo bem */ }
  return [];
}

function gravarPastas() { /* em memória: some com o painel, de propósito */ }

/* A raiz de um caminho — a unidade (`D:\`), o compartilhamento (`\\SERVIDOR\share\`) ou o volume do Mac
   (`/Volumes/X/`). Ela fica sempre à vista na lista de pastas (autor, 2026-10-18: "o início e o fim"); o que corta
   é o meio. */
function raizDoCaminho(p) {
  const m = /^(\\\\[^\\]+\\[^\\]+\\|[A-Za-z]:\\|\/Volumes\/[^/]+\/|\/)/.exec(p);
  return m ? m[0] : "";
}

/* A Avid MediaFiles indicada (autor, 2026-10-25, organograma Premiere → Avid): ela e as MXF/UME de dentro = mídia
   GERENCIADA (marca própria; nunca vira link); outra pasta dentro dela (`MXF-desconectar`) = mídia que o editor tirou do
   Avid de propósito, FORA (o serviço a descarta); o resto = pasta de link. A mesma regra de `media/pmr.tipo_da_pasta`. */
function tipoDaPasta(p) {
  const partes = String(p || "").replace(/\\/g, "/").split("/").filter(Boolean);
  const i = partes.findIndex((x) => x.toLowerCase() === "avid mediafiles");
  if (i < 0) return "link";
  const sub = (partes[i + 1] || "").toUpperCase();
  return !sub || sub === "MXF" || sub === "UME" ? "avid" : "fora";
}
const MARCA_DA_PASTA = { avid: ["avid", "AVID · MXF + UME", "mídia gerenciada do Avid: procurada pelo índice, nunca linkada"],
                         fora: ["fora", "FORA · desconectada", "pasta tirada do Avid de propósito — fica de fora"] };

function renderPastas() {
  el("listaPastas").innerHTML = pastas.map((p, i) => {
    const raiz = raizDoCaminho(p);
    const marca = NLE === "mc" ? MARCA_DA_PASTA[tipoDaPasta(p)] : null;
    return `<div class="pasta" title="${escapar(p)}"><span class="caminho-dupla">` +
    `<span class="caminho-raiz">${escapar(raiz)}</span>` +
    `<span class="caminho"><bdi>${escapar(p.slice(raiz.length))}</bdi></span></span>` +
    (marca ? `<span class="pasta-tag ${marca[0]}" title="${escapar(marca[2])}">${escapar(marca[1])}</span>` : "") +
    `<button class="x" data-i="${i}" title="remover">✕</button></div>`;
  }).join("");
  if (RECEBE) reanalisarSePreciso();
  agendarPrevia();
}

/* Aceita uma pasta ou várias — as duas vias de entrada convergem aqui, e é de propósito:
   o diálogo (que devolve lista, com multisseleção) e o arrasto do Explorer. Uma só função
   para normalizar, deduplicar e gravar significa que nenhuma via ganha tratamento que a
   outra não tem. */
function addPasta(caminhos) {
  const lista = (Array.isArray(caminhos) ? caminhos : [caminhos])
    .map((c) => String(c || "").trim())
    .filter(Boolean);
  // ⛔ Havia aqui um passo que tirava aspas do começo e do fim ("Copiar como caminho" do
  // Explorer as põe). Saiu com o campo de colar: nenhuma das duas vias restantes produz
  // aspas — o diálogo devolve o caminho limpo e o arrasto vem de uma URI. Se um dia
  // voltar a existir entrada digitada, é aqui que a normalização volta.
  if (!lista.length) return;
  let novas = 0;
  for (const v of lista) if (!pastas.includes(v)) { pastas.push(v); novas++; }
  gravarPastas(); renderPastas();
  dizer(novas ? "" : "essa pasta já está na lista", novas ? true : false);
}

/* O seletor de arquivo/pasta é aberto pelo SERVIÇO, não pelo painel: um
   `<input type=file>` na webview entrega só o NOME do arquivo, e o caminho absoluto é
   exatamente o que precisamos. Ver `escolher.py`. */
async function escolherNativo(rota, aoReceber) {
  try {
    const r = await post(rota);
    // O seletor de PASTA devolve `caminhos` (aceita várias de uma vez); o de arquivo
    // devolve `caminho`. Lista vazia ou ausente = o editor cancelou.
    if (r.aviso) dizer(r.aviso, false);
    if (Array.isArray(r.caminhos) && r.caminhos.length) aoReceber(r.caminhos);
    else if (r.caminho) aoReceber(r.caminho);
  } catch (e) { dizer(e.message, false); }
}

/* ── Origem: sequence do MC ou AAF em disco ───────────────────────────────── */
let modoOrigem = "mc";
/* O que está CARREGADO no bloco 1 do Resolve (redesenho de 2026-10-05: carregar não é importar):
   `{arquivo: <o que o /receber/abrir devolveu>}` ou `{envio: <um envio do Magic Link>}`. Numa bin ou
   num projeto do Premiere, `rcSeqEscolhida` é o `mob_id` da sequência marcada. Ver `pintarCarga`. */
let rcCarga = null;
let rcSeqEscolhida = null;

/* A troca das duas abas do passo 1, num lugar só. Três gestos chegam aqui — o clique, a
   timeline arrastada da bin e o arquivo de timeline solto do Explorer —, e antes cada um
   repetia a sequência de `hidden`. Duas cópias de uma troca de estado é onde uma delas
   esquece um campo e a interface fica meio trocada, sem erro nenhum. */
function irParaModo(modo) {
  // ⭐ O botão "Importar / relinkar" é UMA caixa (organograma "Um painel, três NLEs", 2026-10-12): por dentro o
  // painel continua sabendo se o que chegou é uma sequência (`mc`, relink da bin) ou um arquivo (`aaf`); quem
  // escolhe é o gesto (`adotarSequence` → mc, o arquivo → aaf). Clicar no botão só volta para a caixa.
  if (modo === "importar") modo = RECEBE ? "aaf" : (modoOrigem === "atualizar" ? "mc" : modoOrigem);
  if (!modo || modo === modoOrigem) return;
  modoOrigem = modo;
  const botao = modo === "atualizar" ? "atualizar" : "importar";
  for (const x of el("modoOrigem").children) x.classList.toggle("on", x.dataset.modo === botao);
  el("origemMC").hidden = RECEBE || modo === "atualizar";
  el("origemAAF").hidden = modo === "atualizar";
  el("origemAtualizar").hidden = modo !== "atualizar";
  if (NLE === "mc") mostrarEscolhidoMC();
  if (RECEBE) pintarCarga();   // opções avançadas e o Importar dependem da aba
  // o resumo é de uma comparação; trocar de aba o fecha — mas NUNCA no meio da execução, que
  // escreve o andamento e o resultado nele (revisão 2026-09-28)
  if (!rcOcupado && !atComparando) el("rcAtualizar").hidden = true;
  if (modo === "atualizar") abaAtualizar();
  // O preset só importa quando a timeline vem do MC — vindo de um arquivo, não há export.
  el("campoPreset").hidden = modo !== "mc";
  if (modo === "mc") verificarPreset();
  // O Magic Link mora embaixo do arquivo: ao abrir "Importar timeline", as caixas se atualizam.
  if (modo === "aaf") procurarNovos(true);
}

/* ⛔ `carregarSequences()` FOI REMOVIDA (2026-08-16, decisão do usuário).
   Ela listava as sequences das bins abertas e pré-escolhia a que estivesse SELECIONADA —
   e era aí que morava o erro: uma seleção esquecida numa bin qualquer fazia o plugin
   relinkar a timeline errada, sem o editor ter como perceber. O arrasto é 1:1: o que ele
   solta é o que vai. Some com a lista, com o "recarregar" e com a chamada ~500 ms × nº
   de bins que a montava. */

/* ── Arrastar do Media Composer ───────────────────────────────────────────────

   ⭐ O CAMINHO MAIS BARATO PARA DIZER "É ESTA TIMELINE", e ele não é da API.

   O Media Composer entrega o arrasto à webview do painel como um **MIME customizado**
   — não há rpc, não há evento, e nada disso é declarado no manifesto. Um `ondrop` de
   DOM comum recebe o payload. Descoberto dissecando o painel do ESION Studio
   (Acclaim Audio), em `bancodedadosnles/plugins/avid-panel-sdk/esion-arquitetura.md`.

   ⚠️⚠️ Isto **corrige** o que o banco de NLEs afirmava como `confirmado`: que o drop
   era de mão única (painel → MC) e que o substituto era `BinRowSelectionChanged`. A
   conclusão veio de enumerar símbolos `Drop*` no binário do MC — busca correta, com um
   pressuposto invisível: *"se existe, é um rpc"*. Metade da superfície de um painel é a
   do navegador, e essa metade não aparece em `strings`.

   ## Por que vale mais que o seletor de sequences

   `/mc/sequences` precisa enumerar bins, e no MC 25.6 — que não tem `GetListOfWindows`
   — pergunta a **todas** as do projeto, a ~500 ms cada. O arrasto entrega o MobID
   **instantaneamente e sem chamada nenhuma**, funciona com bin que o painel nem sabia
   que existia, e ainda traz `in`/`out`, que a seleção não carrega.

   ## ⚠️ O que NÃO foi medido

   Esta página é **servida por HTTP** (`http://127.0.0.1:7823/painel`), não pelo esquema
   `avpi://` do pacote — o ESION, de onde o mecanismo foi lido, roda em `avpi://`. Se o
   Qt entrega o MIME depois da navegação, **não sabemos**: é o mesmo `pendente` que já
   existe para a ponte de eventos do QWebChannel.

   Por isso o fracasso aqui é **falante, não silencioso**: se cair um drop sem os nossos
   MIMEs, o painel MOSTRA os tipos que chegaram. É a diferença entre "não funciona" e
   uma linha que diz exatamente o que o Media Composer entregou. */

/* Os tipos que o Media Composer põe num arrasto. Enumerados do binário do MC 25.6
   (`strings` sobre `AvidMediaComposer.exe`), então esta é a lista COMPLETA do que ele
   sabe emitir — não o que vimos por acaso:

     text/x.avid.asset-list+json                    (não observado)
     text/x.avid.asset-list-extended                (não observado)
     text/x.avid.asset-list-extended+json           ⬅ vem junto, conteúdo não decifrado
     text/x.avid.location-item-list                 (não observado)
     text/x.avid.location-item-list+json            ⬅ BIN — "location item"
     text/x.avid.mc-api-asset-list+json             ⬅ o que sabemos ler
     text/x.avid.panel-sdk-plugin-asset-list+json   (saída: painel → MC)

   ⭐ Um arrasto de CLIPE/TIMELINE chega com cinco tipos de uma vez (medido):
   `text/plain`, `text/uri-list`, `asset-list-extended+json`, `mc-api-asset-list+json` e
   `Files`. Lemos o `mc-api-asset-list+json` porque é o único cujo formato conhecemos. */
const MIME_MC_ASSETS = "text/x.avid.mc-api-asset-list+json";
const MIME_PLUGIN_ASSETS = "text/x.avid.panel-sdk-plugin-asset-list+json";
const PREFIXO_AVID = "text/x.avid.";

/* `dragenter`/`dragleave` disparam também ao cruzar cada FILHO do elemento, então um
   booleano pisca sem parar. O contador é o remédio conhecido: só o zero significa que
   o ponteiro saiu de verdade. */
let profundidadeArrasto = 0;

/* Os tipos vistos no último `dragenter`. Ver o comentário no listener. */
let tiposNoEnter = [];

/* ⭐ `dataTransfer.items` é a ÚNICA coisa além de `types` que responde durante o
   arrasto: em *protected mode* o conteúdo é bloqueado, mas `kind` e `type` de cada item
   continuam legíveis. É por aqui — se é que dá — que se descobre ANTES do drop quantos
   itens vêm e se um deles é pasta. Guardado para o diagnóstico responder isso com
   medição em vez de suposição. */
let itensNoEnter = [];

function itensDoArrasto(dt) {
  const itens = dt && dt.items ? Array.from(dt.items) : [];
  return itens.map((i) => ({ kind: i.kind, type: i.type }));
}

/* As áreas que aceitam soltura. Cada bloco declara no HTML o que recebe
   (`data-solta="timeline"` / `data-solta="midia"`), e o realce acende no bloco, não na
   página inteira: o overlay É a explicação de onde soltar. */
const ZONA = "[data-solta]";

function zonasQueAceitam(especie) {
  if (!especie) return [];
  // ⚠️ Só as VISÍVEIS. O passo 1 fica escondido durante a revisão e o progresso, e uma
  // zona invisível não pode ser alvo — realçá-la acenderia nada e a recusa mandaria o
  // editor "soltar no bloco 1" com o bloco 1 fora da tela.
  const todas = Array.from(document.querySelectorAll(ZONA)).filter((z) => z.offsetParent);
  // ⚠️ Um caminho de disco acende as DUAS: antes do drop não dá para saber se é pasta ou
  // arquivo de timeline (`getData` só responde no `drop`). Realçar uma só seria chute.
  // A zona de EXPORT só recebe timeline da bin: um arquivo do disco não tem o que fazer lá.
  if (especie === "caminho") return todas.filter((z) => z.dataset.solta !== "exportTimeline");
  if (especie === "nle") return todas.filter((z) => z.dataset.solta === "timeline");
  return todas.filter((z) => z.dataset.solta === "timeline" || z.dataset.solta === "exportTimeline");
}

/* O que ESTA zona fará com ESTE arrasto — o texto do véu.

   ⚠️ Repare no rótulo do bloco 1 quando vem um caminho de disco: ele promete AAF, não
   "esta timeline". É a forma honesta de acender uma zona cujo conteúdo ainda não
   conhecemos: se o editor estiver arrastando uma pasta, o próprio texto já avisa que ali
   não é o lugar, ANTES de ele soltar e levar uma recusa. */
function rotuloDaZona(zona, especie) {
  if (zona.dataset.solta === "midia") return "solte para adicionar as pastas";
  if (zona.dataset.solta === "exportTimeline") return "solte para exportar esta timeline";
  if (zona.dataset.solta === "referencia" || zona.dataset.solta === "referenciaDepois") return "solte para usar como vídeo de referência";
  if (zona.dataset.solta === "midiaManual") return "solte sobre a linha: relink manual desta mídia";
  return especie === "timeline" || especie === "nle" ? "solte para usar esta timeline"
    : "solte para carregar a timeline";
}

/* ⭐ DOIS NÍVEIS de realce, e a diferença entre eles é o que resolve a ambiguidade.
   `pode-soltar` (contorno discreto) marca TODAS as zonas que aceitam a espécie — é o
   mapa: "dá para soltar aqui ou ali". `solta-aqui` (véu azul, com texto) fica só na zona
   **sob o cursor** — é a promessa: "soltando agora, acontece isto".

   ⚠️⚠️ Houve aqui uma versão que punha o véu cheio em todas as zonas aceitantes ao mesmo
   tempo. Como um caminho de disco pode ser pasta OU timeline, as duas acendiam iguais e o
   editor via dois convites igualmente enfáticos para um gesto que só podia ir a um lugar
   — o realce virou pergunta em vez de resposta. Ele não sabia *menos* que nós; ele sabia
   MAIS (ele está olhando o que arrastou), e a interface é que insistia em não perguntar
   ao cursor dele. */
function realcar(especie, alvo) {
  const aceitantes = new Set(zonasQueAceitam(especie));
  // ⚠️ A zona MAIS INTERNA sob o cursor, a mesma que o `drop` usa (`closest`): a do vídeo de referência
  // mora dentro do bloco 1 (2026-10-06), e com `contains` as duas acendiam juntas, cada uma prometendo
  // uma coisa.
  const sob = alvo && alvo.closest ? alvo.closest(ZONA) : null;
  for (const z of document.querySelectorAll(ZONA)) {
    const aceita = aceitantes.has(z);
    z.classList.toggle("pode-soltar", aceita);
    const sobOCursor = aceita && z === sob;
    if (sobOCursor) z.dataset.rotulo = rotuloDaZona(z, especie);
    z.classList.toggle("solta-aqui", !!sobOCursor);
  }
}

function limparRealce() {
  for (const z of document.querySelectorAll(ZONA)) {
    z.classList.remove("solta-aqui", "pode-soltar");
  }
}

/* ⚠️ A linha de mensagem (`#msg`) mora no RODAPÉ da página, depois de todas as seções.
   Numa janela de 500px de altura ela está **fora da área visível** — e o editor solta a
   timeline, o painel responde, e ele não vê resposta nenhuma. "Nada aconteceu" e "a
   resposta apareceu onde você não olha" são indistinguíveis para quem está usando.
   Toda resposta ao arrasto se traz para a vista. */
function dizerNoArrasto(texto, ok) {
  // ⛔ NÃO rolar a página até a linha do rodapé (autor, 2026-10-12: "o painel pula pro fim… tira a atenção e
  // confunde"). A resposta aparece DENTRO do bloco do gesto (`ultimoBloco`: o da zona solta; o bloco 1 para os
  // botões dele), onde o editor já está olhando.
  const bloco = (ultimoBloco && document.body.contains(ultimoBloco)) ? ultimoBloco : el("blocoTimeline");
  // ⭐ Bloco 1 (autor, 2026-10-13): o sucesso NÃO se anuncia — "timeline … recebida/carregada" repetia o cartão e,
  // embaixo do Magic Link, parecia vir dele. Ficam o erro (vermelho), o aviso (`ok === "aviso"`: o que o cartão não
  // diz, como itens ignorados) e o andamento ("lendo…"), numa linha LOGO ABAIXO do cartão, acima do Magic Link.
  const doBloco1 = bloco.id === "blocoTimeline";
  if (doBloco1 && ok === true && !/…$/.test(texto || "")) texto = "";
  let linha = bloco.querySelector(".msg-bloco");
  if (!linha) {
    linha = document.createElement("p");
    linha.className = "msg-bloco";
    const ml = doBloco1 && el("mlAcordeao");          // acima do divisor do Magic Link, abaixo do cartão
    if (ml && bloco.contains(ml)) ml.parentNode.insertBefore(linha, ml);
    else bloco.appendChild(linha);
  }
  linha.textContent = texto || "";
  linha.classList.toggle("erro", ok === false);
  linha.hidden = !texto;
  ultimoBloco = null;
}
let ultimoBloco = null;

/* ⚠️⚠️ NÃO force `dropEffect = "copy"`. **Medido: o Media Composer arrasta com
   `effectAllowed = "move"`**, e um `dropEffect` fora do que a origem permite CANCELA o
   drop — silenciosamente. Foi exatamente esta linha que fez o realce aparecer e soltar
   não produzir nada, na primeira tentativa dentro do MC 25.6.

   Quem manda é a origem: escolhemos um efeito compatível com o que ela declarou.
   (O `"move"` do Avid é rótulo do protocolo de arrasto, não uma promessa de que algo
   sai do lugar — nada é removido do projeto do editor.) */
function efeitoCompativel(dt) {
  const permitido = (dt && dt.effectAllowed) || "all";
  if (permitido === "none") return null;
  if (permitido === "all" || permitido === "uninitialized") return "copy";
  const p = permitido.toLowerCase();
  if (p.includes("copy")) return "copy";
  if (p.includes("link")) return "link";
  if (p.includes("move")) return "move";
  return "copy";
}

function tiposDoArrasto(dt) {
  // `dt.types` é um DOMStringList em navegadores antigos; normalizamos.
  return Array.from(dt && dt.types ? dt.types : []);
}

function temNossoMime(dt) {
  const t = tiposDoArrasto(dt);
  return t.includes(MIME_MC_ASSETS) || t.includes(MIME_PLUGIN_ASSETS);
}

/* Guarda o último arrasto CRU, para os Ajustes.
   ⚠️ Só o evento `drop` entrega dados: durante `dragenter`/`dragover` o navegador está em
   *protected mode* e `getData` devolve string vazia, mesmo com o tipo listado em `types`.
   Por isso a captura acontece aqui, e não no realce. */
function capturarArrasto(dt) {
  const linhas = [];
  const tipos = tiposDoArrasto(dt);
  // Vai também para o SERVIÇO. Assim a pergunta "o que chegou?" se responde consultando
  // `/diag/arrasto`, sem depender de a pessoa abrir a aba certa e fotografar a tela.
  const paraOServico = {
    efeito: (dt && dt.effectAllowed) || "",
    tipos,
    tipos_no_enter: tiposNoEnter,
    // ⭐ Os dois lados da mesma pergunta: o que dava para saber ANTES do drop
    // (`itens_no_enter`, lido em protected mode) contra o que se sabe DEPOIS.
    itens_no_enter: itensNoEnter,
    itens_no_drop: itensDoArrasto(dt),
    arquivos: (dt && dt.files && dt.files.length) || 0,
    dados: {},
  };
  linhas.push("efeito permitido: " + ((dt && dt.effectAllowed) || "—"));
  linhas.push("arquivos: " + ((dt && dt.files && dt.files.length) || 0));
  linhas.push("tipos no drop (" + tipos.length + "):");
  for (const t of tipos) linhas.push("  " + t);
  linhas.push("tipos no enter (" + tiposNoEnter.length + "):");
  for (const t of tiposNoEnter) linhas.push("  " + t);

  for (const t of tipos) {
    if (t.indexOf(PREFIXO_AVID) !== 0 && t !== "text/uri-list" && t !== "text/plain") continue;
    let bruto = "";
    try { bruto = dt.getData(t) || ""; } catch (e) { bruto = "(getData falhou: " + e.message + ")"; }
    paraOServico.dados[t] = bruto;
    linhas.push("");
    linhas.push("── " + t + " (" + bruto.length + " chars)");
    // JSON legível quando for JSON; cru quando não for. O objetivo é LER numa foto.
    try { linhas.push(JSON.stringify(JSON.parse(bruto), null, 1)); }
    catch (_) { linhas.push(bruto || "(vazio)"); }
  }

  /* ⛔ Os arquivos anexos ao arrasto NÃO servem — medido, não suposto.
     O `text/uri-list` de um arrasto de timeline aponta para um `.aaf` no Temp, o que
     parecia dispensar todo o `ExportFile` + preset (e o pior atrito do plugin: instalar
     setting com o Media Composer fechado). Mas o `File` do evento tem **0 bytes**, e uma
     vigia NATIVA provou que **o arquivo nunca chega a existir no disco** — 40 amostras em
     10 s, nenhuma o encontrou. O Chromium sintetiza o `File` a partir do descritor do
     arrasto; o conteúdo só sairia para um alvo que o pedisse pelo mecanismo do shell.
     Guardamos só nome e tamanho, que é o que denunciaria isso mudar num MC futuro. */
  const arquivos = dt && dt.files ? Array.from(dt.files) : [];
  // o ponto que o alvo NATIVO do app mandou e o que ele atingiu (o desvio do Mac, 2026-10-24)
  if (pontoNativo) paraOServico.ponto_nativo = pontoNativo;
  paraOServico.arquivos_detalhe = arquivos.map((f) => ({ nome: f.name, tamanho: f.size }));
  for (const f of arquivos) {
    linhas.push("");
    linhas.push(`── arquivo: ${f.name} (${f.size} bytes)`);
  }

  const alvo = el("ajArrasto");
  if (alvo) alvo.textContent = new Date().toLocaleTimeString() + "\n" + linhas.join("\n");
  // Melhor esforço: o diagnóstico jamais atrapalha o arrasto.
  post("/diag/arrasto", paraOServico).catch(() => {});

  // ⚠️ ZERAR é obrigatório, e foi o defeito da primeira versão deste diagnóstico: sem
  // isto, a lista de tipos do arrasto ANTERIOR sobrevive e aparece como se fosse deste.
  // Foi o que fez uma bin (que chegou sem tipo nenhum) parecer trazer os MIMEs do Avid,
  // e a leitura errada quase virou conclusão. O drop encerra o arrasto: limpa aqui.
  tiposNoEnter = [];
  itensNoEnter = [];
}

/* O payload é um ARRAY JSON, um objeto por item arrastado. Medido:

     [{ "head": "0", "id": "<MobID>", "type": "sequence",
        "systemID": "mc-api", "systemType": "mediacomposer" }]

   ⚠️ **NÃO vêm `in`/`out`.** O painel do ESION os lê (`element["in"]`), e foi de lá que
   a suposição saiu — mas ler um campo não prova que ele exista: *o código de um produto
   diz o que ele ESPERA, não o que a plataforma ENTREGA.*

   `systemID`/`systemType` são o SISTEMA DE ORIGEM, não a bin — é o que distingue este
   MIME do `asset-list-extended`, que é a mesma lista na variante Interplay/PAM. `head`
   veio `"0"` e segue não decifrado. Nenhum dos três é usado. */
function lerPayload(dt) {
  const tipos = tiposDoArrasto(dt);
  const mime = tipos.includes(MIME_MC_ASSETS) ? MIME_MC_ASSETS : MIME_PLUGIN_ASSETS;
  const cru = dt.getData(mime);
  if (!cru) return [];
  const dados = JSON.parse(cru);
  return Array.isArray(dados) ? dados : [dados];
}

/* As espécies que o Media Composer entrega num arrasto, **medidas** (2026-08-15, num
   único arrasto misto — o payload é lista, então uma seleção com um de cada responde
   tudo de uma vez):

     "sequence"    timeline
     "masterclip"  master — ⚠️ o MESMO valor para AMA-linkado e para mídia gerenciada
     "subclip"     recorte; é a ÚNICA espécie que traz `in`/`out` no payload
     "group"       group clip (multicam)
     ""            EFEITO — string VAZIA, não um nome

   ⚠️ O efeito vir com `type` vazio é a armadilha aqui: quem escrever `if (!tipo)` para
   "não sei o que é" vai confundi-lo com payload defeituoso.

   ⚠️ E o `type` **não separa AMA de gerenciado**. Quem separa é a coluna do `GetMobInfo`:
   `Source File`/`Source Path` presentes = há arquivo externo de origem. Ver
   `bancodedadosnles/plugins/avid-panel-sdk/windows.md`. */
const ESPECIES = {
  sequence: ["timeline", "timelines"],
  masterclip: ["master clip", "master clips"],
  subclip: ["subclip", "subclips"],
  group: ["group clip", "group clips"],
  "": ["efeito", "efeitos"],
};

/* "2 master clips, 1 subclip e 1 efeito" — o que veio, na língua do editor. */
function descreverEspecies(itens) {
  const conta = new Map();
  for (const i of itens) {
    const t = (i && i.type) || "";
    conta.set(t, (conta.get(t) || 0) + 1);
  }
  const partes = [...conta].map(([tipo, n]) => {
    const rotulo = ESPECIES[tipo] || [tipo || "item desconhecido", tipo || "itens desconhecidos"];
    return `${n} ${rotulo[n > 1 ? 1 : 0]}`;
  });
  if (partes.length === 1) return partes[0];
  return partes.slice(0, -1).join(", ") + " e " + partes[partes.length - 1];
}

/* ── Arrastar do EXPLORER (a pasta de mídia) ──────────────────────────────────

   ⭐ **MEDIDO 2026-08-16** (MC 25.6 / Windows 11, painel servido em
   `http://127.0.0.1:7823/painel`): soltar uma PASTA do Explorer entrega o caminho
   absoluto, e é tudo de que precisamos.

       efeito permitido : "all"
       tipos            : text/plain, text/uri-list, Files
       text/uri-list    : file:///E:/MIDIAS%20DE%20TESTES/.../MIDIAS%20VALENDO
       Files[0]         : { nome: "MIDIAS VALENDO", tamanho: 0 }

   ⚠️⚠️ Isto **CORRIGE** o que estava escrito no antigo tratador de drop: que "o
   navegador esconde o caminho absoluto de um arquivo solto". Vale para uma página web
   comum; **não vale nesta webview**, que expõe `text/uri-list` com o caminho inteiro. A
   afirmação tinha sido **inferida** do comportamento padrão do Chromium, não medida
   aqui — e por causa dela o gesto mais natural para apontar uma diária ficou anos-luz
   mais longe do que precisava.

   ⚠️ **Não confunda com o `Files` do arrasto DO MEDIA COMPOSER.** Lá o `.aaf` anexo tem
   0 bytes e o arquivo **nunca chega a existir** no disco (medido com vigia nativa, 40
   amostras). Aqui `tamanho: 0` é só uma pasta não ter tamanho — quem vale é o CAMINHO,
   nunca o objeto `File`. Foi essa confusão que fez o `.aaf` sintético parecer um atalho.

   ⭐ E a recursão nas subpastas não muda nada: quem varre é o `media/indexer`, igual ao
   que já acontece com pasta escolhida no diálogo ou colada no campo. */
function uriParaCaminho(uri) {
  const cru = String(uri || "").trim();
  if (!/^file:\/\//i.test(cru)) return "";
  let resto = cru.slice("file://".length);
  let host = "";
  const barra = resto.indexOf("/");
  if (barra === -1) return "";
  if (barra > 0) { host = resto.slice(0, barra); resto = resto.slice(barra); }

  let caminho;
  // Um `%` solto (raro, mas possível num nome de arquivo) faz `decodeURIComponent`
  // levantar. Cair para o texto cru é melhor que perder o arrasto inteiro.
  try { caminho = decodeURIComponent(resto); } catch (_) { caminho = resto; }

  // Windows local: "/E:/a/b" → "E:\a\b". A barra da frente é da URL, não do caminho.
  if (/^\/[A-Za-z]:/.test(caminho)) return caminho.slice(1).replace(/\//g, "\\");
  // ⭐ UNC: "file://SERVIDOR/share/x" → "\\SERVIDOR\share\x". Não é caso de borda —
  // diária em share de rede é a regra neste ramo.
  if (host && host.toLowerCase() !== "localhost") {
    return ("\\\\" + host + caminho).replace(/\//g, "\\");
  }
  return caminho;   // POSIX (macOS)
}

function _lerTipo(dt, tipo) {
  try { return (dt && dt.getData(tipo)) || ""; } catch (_) { return ""; }
}

function _urisDe(bruto) {
  return String(bruto || "").split(/\r?\n/)
    .map((l) => l.trim())
    // RFC 2483: numa `text/uri-list`, linha começada em `#` é comentário.
    .filter((l) => l && l[0] !== "#")
    .map(uriParaCaminho)
    .filter(Boolean);
}

/* ⚠️⚠️ LÊ OS DOIS TIPOS E UNE — e a razão é uma armadilha medida, não zelo.
   **Numa seleção de VÁRIAS pastas o QtWebEngine trunca o `text/uri-list` na PRIMEIRA
   URI**, enquanto o `text/plain` traz a seleção inteira. Medido 2026-08-16, arrastando
   `SFX` + `TRILHAS` juntas:

       text/uri-list : file:///E:/.../SFX                          (1 de 2)
       text/plain    : file:///E:/.../SFX \n file:///E:/.../TRILHAS  (2 de 2)

   Ou seja: **o tipo canônico é o incompleto**, e o "reserva" é o que está certo. Preferir
   o `uri-list` — que é o que a especificação manda — fazia o editor selecionar cinco
   diárias, arrastar, e o painel adicionar UMA, sem erro nenhum. Ele só descobriria pelo
   resultado do relink, longe daqui.

   Unir em vez de trocar a preferência: assim nenhum dos dois precisa estar certo sempre.
   A ordem começa pelo `uri-list` porque ele vem com percent-encoding decodificado do
   jeito certo; o `text/plain` só acrescenta o que faltou. */
function caminhosDoArrasto(dt) {
  const vistos = new Set();
  const saida = [];
  for (const c of _urisDe(_lerTipo(dt, "text/uri-list"))
                    .concat(_urisDe(_lerTipo(dt, "text/plain")))) {
    if (!vistos.has(c)) { vistos.add(c); saida.push(c); }
  }
  // ⭐ No Resolve (Electron), o arquivo solto do Explorer chega SÓ como `Files`, sem uri-list nem texto
  // (autor, 2026-10-05, Resolve 19 no Windows: "esse arrasto não trouxe caminho"). O caminho está no
  // próprio File: `File.path` até o Electron 31 (o 8 do Resolve 19), e `webUtils.getPathForFile` pelo
  // preload da casca do 32 em diante (o 36 do Resolve 21), onde `File.path` deixou de existir.
  if (!saida.length && dt && dt.files) {
    for (const f of Array.from(dt.files)) {
      let c = "";
      try { c = f.path || ""; } catch (_) { /* segue */ }
      if (!c && ponte() && typeof ponte().caminhoDoArquivo === "function") {
        try { c = ponte().caminhoDoArquivo(f) || ""; } catch (_) { /* casca antiga */ }
      }
      if (c && !vistos.has(c)) { vistos.add(c); saida.push(c); }
    }
  }
  return saida;
}


/* ── O despacho: QUEM veio × ONDE caiu ────────────────────────────────────────

   ⭐ A área decide a ação, e é por isso que ela existe. Uma timeline e uma pasta de
   mídia chegam à webview como arrastos parecidos — e vão chegar mais parecidos ainda
   quando "Importar timeline" aceitar `.aaf`/`.xml`/`.drt` soltos, que são **arquivos**,
   como a mídia. Adivinhar pelo conteúdo daria um palpite bom na maioria das vezes e um
   erro calado no resto (a timeline entrando no acervo, ou a diária virando timeline).
   Com zonas, quem decide é o editor, no gesto, sem ambiguidade nenhuma.

   ⚠️ **E há um limite da plataforma que torna a zona necessária, não só elegante:**
   durante `dragenter`/`dragover` o navegador está em *protected mode* e `getData`
   devolve vazio — só `types` está disponível. Ou seja, **antes do drop não dá para
   saber se o caminho arrastado é uma pasta ou um `.aaf`**. Realçar "a zona certa" seria
   chutar; realçar as duas e deixar o pouso decidir é honesto. */

/* O que a webview consegue dizer ANTES do drop, só pelos tipos. */
function especieDoArrasto(dt) {
  if (temNossoMime(dt)) return "timeline";        // veio da bin do Media Composer
  const t = tiposDoArrasto(dt);
  // ⚠️ Nesta ordem: o arrasto do MC TAMBÉM traz `text/uri-list` e `Files` (apontando
  // para o `.aaf` de zero bytes). Testar o MIME da Avid primeiro é o que impede um
  // arrasto de timeline de ser lido como arquivo de disco.
  if (t.includes("text/uri-list") || t.includes("Files")) return "caminho";
  // ⚠️ Os PRIMEIROS eventos de um arrasto vindo do Explorer chegam ao QtWebEngine ainda SEM tipos (autor,
  // 2026-10-12: o realce só acendia "depois"). O Explorer arrasta com `all`; a bin do MC e o Media Pool do Resolve,
  // quando chegam vazios, com `move` — então vazio + `all` já é um arquivo de fora.
  if (!t.length && dt && dt.effectAllowed === "all") return "caminho";
  return "";
}

/* Extensões de timeline. `LEIO_HOJE` é o que o serviço realmente abre; as outras são
   reconhecidas só para poder RECUSAR com precisão — "ainda não leio .drt" ensina, e
   "não reconheci o que foi solto" manda o editor procurar defeito onde não há. */
const EXT_LEIO_HOJE = /\.(aaf|avb|prproj)$/i;   // a bin de fora (.avb) desde 2026-10-12; o .prproj no MC desde 2026-10-25
const EXT_TIMELINE_FUTURA = /\.(xml|fcpxml|drt|otio|edl|prproj)$/i;

function eArquivoDeTimeline(c) {
  return EXT_LEIO_HOJE.test(c) || EXT_TIMELINE_FUTURA.test(c);
}

async function aoSoltar(ev) {
  ev.preventDefault();
  profundidadeArrasto = 0;
  limparRealce();

  const dt = ev.dataTransfer;
  // Antes de qualquer decisão: guardar o que chegou. Se o arrasto for de um tipo que
  // ainda não sabemos ler, é este despejo (nos Ajustes) que vai nos ensinar o formato.
  try { capturarArrasto(dt); } catch (_) { /* diagnóstico nunca derruba o fluxo */ }

  const zonaDoGesto = (ev.target && ev.target.closest) ? ev.target.closest(ZONA) : null;
  ultimoBloco = zonaDoGesto ? (zonaDoGesto.closest(".bloco") || zonaDoGesto) : null;
  const especie = especieDoArrasto(dt);
  if (!especie) {
    // ⚠️ NÃO engolir. Este é o caso que decide se o mecanismo funciona nesta origem, e
    // um "nada aconteceu" mandaria depurar o painel quando o problema é a plataforma.
    const tipos = tiposDoArrasto(dt);
    dizerNoArrasto(tipos.length
      ? `não reconheci o que foi solto (chegou como: ${tipos.join(", ")})`
      : "não reconheci o que foi solto — o arrasto chegou sem dados", false);
    return;
  }

  const zona = (ev.target && ev.target.closest) ? ev.target.closest(ZONA) : null;
  if (!zona) {
    // ⚠️ Antes de mandar o editor "soltar no bloco 1", conferir se o bloco 1 está NA
    // TELA: durante a revisão e o progresso o passo 1 fica escondido, e a instrução
    // apontaria para algo que ele não vê — a pior forma de recusa que existe.
    if (!zonasQueAceitam(especie).length) {
      dizerNoArrasto("esta etapa não recebe arrasto — volte ao começo para trocar a "
        + "timeline ou as pastas", false);
      return;
    }
    // Soltou no painel, mas fora das áreas. Dizer PARA ONDE, não que falhou.
    dizerNoArrasto(especie === "timeline"
      ? "solte a timeline dentro do bloco “1 · a timeline”"
      : "solte no bloco “1” (arquivo de timeline) ou no “2” (pastas de mídia)", false);
    return;
  }

  if (especie === "timeline") {
    // ⭐ O MESMO arrasto serve às duas abas; é a ZONA que decide se ele entra (relink) ou
    // sai (export). `soltarTimelineDaBin` não serve aqui: ele troca o modo da aba de
    // relink e guarda a escolha dela.
    if (zona.dataset.solta === "exportTimeline") return soltarTimelineParaExportar(dt);
    if (zona.dataset.solta !== "timeline") {
      dizerNoArrasto("isso é uma timeline — solte no bloco “1 · a timeline”", false);
      return;
    }
    return soltarTimelineDaBin(dt);
  }

  if (zona.dataset.solta === "exportTimeline") {
    dizerNoArrasto("aqui entra a timeline arrastada da bin do Media Composer", false);
    return;
  }

  const caminhos = caminhosDoArrasto(dt);
  if (!caminhos.length) {
    // Chegou `Files` sem caminho legível: é o `.aaf` sintético que o próprio MC anexa.
    dizerNoArrasto(RECEBE
      ? "esse arrasto não trouxe o caminho do arquivo — clique na área para escolher"
      : "esse arrasto não trouxe caminho, só o nome — use “Escolher…”", false);
    return;
  }
  if (zona.dataset.solta === "referencia") return soltarReferencia(caminhos);
  if (zona.dataset.solta === "referenciaDepois") return soltarReferenciaDepois(caminhos);
  if (zona.dataset.solta === "midiaManual") return soltarMidiaManual(caminhos, ev.target);
  return zona.dataset.solta === "timeline"
    ? soltarArquivoDeTimeline(caminhos)
    : soltarPastasDeMidia(caminhos);
}

/* ── Bloco 2: pastas de mídia ─────────────────────────────────────────────── */
function soltarPastasDeMidia(caminhos) {
  // ⚠️ Um arquivo de timeline aqui viraria "pasta de mídia" e o acervo entraria com a
  // timeline dentro. Recusar dizendo para onde ir é melhor que aceitar errado.
  const midias = caminhos.filter((c) => !eArquivoDeTimeline(c));
  if (!midias.length) {
    dizerNoArrasto("isso é uma timeline — solte no bloco “1 · a timeline”", false);
    return;
  }
  const antes = pastas.length;
  addPasta(midias);
  const novas = pastas.length - antes;
  const sobrou = caminhos.length - midias.length;
  // ⭐ Sucesso NÃO se anuncia (autor, 2026-10-18): o editor vê a pasta entrar na lista. Só o que deu errado fala,
  // em vermelho — a repetida (o gesto não mudou nada) e a timeline solta no lugar das pastas.
  const problemas = [];
  if (!novas) problemas.push(midias.length === 1 ? "essa pasta já está na lista" : "essas pastas já estão na lista");
  if (sobrou) problemas.push(`${sobrou} timeline(s) ficaram de fora — elas vão no bloco 1`);
  dizerNoArrasto(problemas.join(" · "), false);
}

/* ── Bloco 1: arquivo de timeline vindo do disco ──────────────────────────── */
/* No Resolve, o que o `/receber/abrir` lê hoje (redesenho de 2026-10-05: soltar na área = escolher). */
const EXT_RESOLVE_ABRE = /\.(aaf|json|avb|prproj)$/i;

function soltarArquivoDeTimeline(caminhos) {
  if (RECEBE) {
    const abre = caminhos.filter((c) => EXT_RESOLVE_ABRE.test(c) || eArquivoDeTimeline(c));
    if (abre.length !== 1) {
      dizerNoArrasto(abre.length ? "uma timeline por vez — você soltou " + abre.length
        : "isso não parece uma timeline — pastas de mídia vão no bloco 2", false);
      return;
    }
    irParaModo("aaf");
    abrirArquivo(abre[0]);   // o serviço recusa, com o motivo, o formato que ainda não lê
    return;
  }
  const arquivos = caminhos.filter(eArquivoDeTimeline);
  if (!arquivos.length) {
    dizerNoArrasto("isso não parece uma timeline — pastas de mídia vão no bloco 2", false);
    return;
  }
  // ⚠️ Um só. Diferente das pastas (que acumulam), timeline é escolha ÚNICA: aceitar
  // várias e ficar com uma faria o editor achar que escolheu outra coisa.
  if (arquivos.length > 1) {
    dizerNoArrasto("uma timeline por vez — você soltou " + arquivos.length, false);
    return;
  }
  const arquivo = arquivos[0];
  if (/\.avb$/i.test(arquivo)) { carregarBinExterna(arquivo); return; }
  // ⭐ Premiere → Avid (organograma do autor, 2026-10-25): o MC está aberto e só RECEBE o projeto — o mesmo cartão da
  // bin de fora (marcar a sequência, carregar), a mesma lista de mídias e o mesmo Relinkar, que monta no MC.
  if (/\.prproj$/i.test(arquivo)) { carregarBinExterna(arquivo, "prproj"); return; }
  if (!EXT_LEIO_HOJE.test(arquivo)) {
    const ext = (arquivo.match(/\.[^.\\/]+$/) || [""])[0];
    dizerNoArrasto(`ainda não leio ${ext} — hoje a importação é de AAF`, false);
    return;
  }
  // O gesto é inequívoco, então ele manda — mesma regra da timeline arrastada da bin.
  el("campoAaf").value = arquivo;
  irParaModo("aaf");
  mostrarEscolhidoMC();
  dizerNoArrasto("timeline escolhida: " + (arquivo.split(/[\\/]/).pop() || arquivo), true);
}

/* ── Bloco 1: timeline arrastada da bin do Media Composer ─────────────────── */
async function soltarTimelineDaBin(dt) {
  let itens;
  try {
    itens = lerPayload(dt);
  } catch (e) {
    dizerNoArrasto("o Media Composer mandou algo que não consegui ler: " + e.message, false);
    return;
  }

  const sequences = itens.filter((i) => i && i.type === "sequence" && i.id);
  if (!sequences.length) {
    // Recusa que ENSINA: dizer o que veio, no vocabulário do editor, é o que faz a
    // pessoa entender o gesto certo — e é o que prepara as ações por espécie.
    dizerNoArrasto(itens.length
      ? `por enquanto só timeline — você soltou ${descreverEspecies(itens)}`
      : "o arrasto veio vazio", false);
    return;
  }

  // ⛔ UMA timeline por arrasto (autor, 2026-10-13). Várias soltas juntas eram aceitas e "valia a última" — o editor
  // não escolheu nada e o relink podia sair na errada. Várias timelines só entram por um ARQUIVO que as traz em lista
  // (bin .avb, projeto .prproj, .drp), onde o editor marca qual; arrastadas da bin, recusa e pede uma só.
  if (sequences.length > 1) {
    dizerNoArrasto(`uma timeline por vez — você soltou ${sequences.length}. Arraste só uma (várias timelines entram `
      + "por uma bin .avb, um projeto .prproj ou um .drp, com a lista para escolher)", false);
    return;
  }
  await adotarSequence(sequences[0], itens.length - 1);
}

/* ⛔ NÃO HÁ SUPORTE A ARRASTAR UMA BIN, e isso foi MEDIDO — não é omissão.
   Uma bin solta no painel chega assim:

       {"efeito": "move", "tipos": [], "tipos_no_enter": [], "arquivos": 0}

   O Media Composer INICIA um arrasto de verdade (tem `effectAllowed`), mas ele não
   carrega dado nenhum que o Chromium saiba expor — provavelmente um formato interno do
   Qt que o QtWebEngine não traduz. O `text/x.avid.location-item-list+json` existe no
   binário do MC e **não é entregue a um painel**.

   ⭐ O gesto que ocupa esse lugar: o ARQUIVO da bin (.avb) solto ou escolhido, que abre a lista para marcar qual
   (a bin de fora). Várias timelines arrastadas da bin são recusadas — uma por arrasto (autor, 2026-10-13). */

/* Põe a sequence arrastada no lugar em que o resto do fluxo já sabe procurá-la. */
async function adotarSequence(item, ignorados, origem) {
  // O arrasto pode chegar com a aba em "Importar timeline": o gesto é inequívoco, então ele
  // manda — trocar de modo é o que o editor esperaria.
  irParaModo("mc");

  // ⚠️ O segundo argumento não é opcional na prática: sem ele `dizer` pinta de VERMELHO,
  // e uma mensagem de progresso passaria por erro.
  dizerNoArrasto("lendo a timeline arrastada…", true);

  // O payload traz o MobID, não o NOME — e o nome vira o arquivo do export e o nome da
  // bin. Uma chamada resolve, e ela é justa: é um gesto deliberado, não um laço.
  let nome = "";
  let colunas = null;
  try {
    const r = await post("/mc/mob", { mob_id: item.id });
    nome = r.nome || "";
    colunas = r.colunas || null;
  } catch (e) {
    // ⚠️ 404 é OUTRA COISA: o Media Composer não conhece esse mob. Seguir em frente
    // marcaria como escolhida uma timeline que não existe, e o erro só apareceria no
    // export — longe da causa, e parecendo defeito do relink.
    if (e.status === 404) { dizerNoArrasto(e.message, false); return; }
    // Qualquer outra falha custa só o RÓTULO: quem identifica o mob no export é o
    // MobID, que já temos. Recusar o arrasto por causa do nome seria pior.
    dizerNoArrasto("não consegui ler o nome dela (" + e.message + ") — sigo pelo MobID", false);
  }

  const rotulo = nome || "timeline arrastada";

  // ⭐ A opção fica IGUAL a uma que veio da lista — sem ícone, sem sufixo "arrastada".
  // Para quem usa, escolher no botão e arrastar da bin são o mesmo ato, e o resultado
  // tem de ser o mesmo: a timeline escolhida. Marcar a origem seria contar ao editor um
  // detalhe da nossa implementação que não muda nada para ele.
  guardarArrastada([{ mob_id: item.id, nome: rotulo, colunas, de: origem || "arrastada da bin" }]);
  aplicarArrastada();

  dizerNoArrasto(`timeline “${rotulo}” recebida${ignorados > 0
      ? ` — ignorei mais ${ignorados} item(ns) soltos junto` : ""}`, ignorados > 0 ? "aviso" : true);
}

/* A timeline escolhida vive só aqui — não há mais lista para ela sobreviver. */
function guardarArrastada(itens, escolhido) {
  arrastada = { itens, escolhido: escolhido || (itens[0] && itens[0].mob_id) || "" };
}

function aplicarArrastada() {
  mostrarEscolhidoMC();
}

/* O AAF no cartão do MC: `{caminho, fatos}` da última leitura rápida (`/receber/abrir`). */
let leituraAaf = { caminho: "", fatos: [] };
async function lerAafParaOCartao(caminho) {
  leituraAaf = { caminho, fatos: [] };
  let r = null;
  try { r = await post("/receber/abrir", { caminho }); } catch (_) { return; }
  if (leituraAaf.caminho !== caminho || !r) return;   // outro AAF entrou no meio
  leituraAaf.fatos = fatosDe(r);
  if (leituraAaf.fatos.length && modoOrigem === "aaf" && el("campoAaf").value.trim() === caminho) mostrarEscolhidoMC();
}

/* O que está na caixa do Media Composer — a sequência (da bin ou do Record) ou o arquivo, o que valer pelo modo —, no
   MESMO cartão do Resolve: ele ocupa o lugar do alvo e do botão, e o × volta à seleção (autor, 2026-10-12). */
function mostrarEscolhidoMC() {
  let nome = "", de = "", fatos = [];
  let seqs = [];
  if (modoOrigem === "bin" && binExterna) {
    const arquivo = binExterna.caminho.split(/[\\/]/).pop() || binExterna.caminho;
    const c = binExterna.carregada;
    if (c) {
      // carregada: o MESMO cartão da sequência arrastada da bin (autor, 2026-10-12)
      nome = c.nome || "(sem nome)";
      de = (binExterna.envio ? "sequência · Magic Link · "
        : binExterna.tipo === "prproj" ? "sequência · projeto do Premiere · " : "sequência · bin de fora · ") + arquivo;
      fatos = [["duração", c.duracao || ""], ["taxa", taxaLegivel(c.fps)], ["trilhas", c.trilhas || ""],
               ["planos", c.planos ? String(c.planos) : ""], ["formato", c.raster || ""],
               ["início", c.inicio || ""]].filter(([, v]) => v);
    } else {
      seqs = binExterna.sequencias || [];
      nome = arquivo;
      de = `${binExterna.tipo === "prproj" ? "projeto do Premiere" : "bin de fora"} · ${seqs.length} `
        + `${seqs.length === 1 ? "sequência" : "sequências"} — marque e carregue`;
    }
  } else if (modoOrigem === "aaf") {
    const c = el("campoAaf").value.trim();
    if (c) {
      nome = c.split(/[\\/]/).pop() || c;
      de = "AAF · " + c;
      // A leitura rápida do serviço, a mesma do cartão do Resolve (duração, taxa, trilhas, planos). Acessória: se
      // falhar, o cartão fica só com o nome — o Ler sequência é quem diz se o AAF serve.
      if (leituraAaf.caminho === c) fatos = leituraAaf.fatos;
      else lerAafParaOCartao(c);
    }
  } else {
    const item = arrastada && arrastada.itens.find((x) => x.mob_id === arrastada.escolhido);
    if (item) {
      nome = item.nome;
      de = ["sequência", item.de || ""].filter(Boolean).join(" · ");
      const c = item.colunas || {};
      const s = item.selecao;
      // a seleção da timeline: o cartão fala DELA (trecho, trilhas, clipes, arquivos), não da sequência inteira
      fatos = s ? [["trecho", s.trecho], ["trilhas", s.trilhas], ["clipes", String(s.clipes)],
                   ["arquivos", `${s.arquivos}: ${s.nomes.slice(0, 6).join(", ")}${s.nomes.length > 6 ? "…" : ""}`]]
                   .filter(([, v]) => v)
        : [["duração", (c.Duration || "").trim()], ["taxa", taxaLegivel(c.FPS)], ["trilhas", trilhasVA(c.Tracks)],
           ["início", (c.Start || "").trim()], ["formato", (c.Format || "").trim()]].filter(([, v]) => v);
    }
  }
  const carregado = !!nome;
  agendarPrevia();
  el("btnSeqAberta").hidden = carregado;
  el("btnSelecaoTL").hidden = carregado;
  el("btnAlvoEscolher").hidden = carregado;
  el("mcCarga").hidden = !carregado;
  if (!carregado) return;
  el("mcCargaNome").textContent = nome;
  el("mcCargaDe").textContent = de;
  el("mcCargaFatos").innerHTML = fatos.map(([k, v]) => `<div><dt>${escapar(k)}</dt><dd>${escapar(v)}</dd></div>`).join("");
  const lista = el("mcSequencias");
  const busca = el("mcSeqBusca");
  // Escondida com a sequência carregada, a busca GUARDA o texto: o × volta à lista filtrada como estava (2026-10-12:
  // limpar aqui fazia o × voltar à lista inteira, sem a marcada à vista). Bin nova limpa em `carregarBinExterna`.
  busca.hidden = seqs.length < 7;
  // sem acento e sem caixa: "anim" acha "LAB_ANIMATTE"; "seq" acha "Sequência 1"
  const sem = (t) => (t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const q = sem(busca.value.trim());
  const vistas = q ? seqs.filter((s) => sem(s.nome).includes(q)) : seqs;
  lista.hidden = seqs.length < 2;
  lista.innerHTML = seqs.length < 2 ? "" : !vistas.length
    ? `<p class="dica">nenhuma timeline com “${escapar(busca.value.trim())}”</p>` : vistas.map((s) => {
    const marcada = s.mob_id === binExterna.escolhido;
    return `<label class="seq${marcada ? " sel" : ""}">
      <input type="radio" name="mcSeq" value="${escapar(s.mob_id)}"${marcada ? " checked" : ""}>
      <span class="seq-texto"><span class="seq-nome">${escapar(s.nome || "(sem nome)")}</span>
        <span class="seq-info">${escapar([s.duracao || "", s.trilhas || "", s.planos ? s.planos + " planos" : ""]
          .filter(Boolean).join(" · "))}</span></span></label>`;
  }).join("");
  const botao = el("mcSeqCarregar");
  botao.hidden = !seqs.length;
  botao.disabled = !binExterna || !binExterna.escolhido;
}

/* A bin de fora: lida no serviço (sem abrir no MC); uma sequência só já vem marcada. `tipo` "prproj" = o projeto do
   Premiere (`/mc/prproj/ler`), que entra pelo mesmo cartão e devolve também as pastas que ele usou da última vez. */
async function carregarBinExterna(caminho, tipo) {
  const prproj = tipo === "prproj";
  dizerNoArrasto(prproj ? "lendo o projeto do Premiere…" : "lendo a bin…", true);
  let r;
  try { r = await post(prproj ? "/mc/prproj/ler" : "/mc/bin/ler", { caminho }); }
  catch (e) { dizerNoArrasto(e.message, false); return; }
  const seqs = r.sequencias || [];
  binExterna = { caminho: r.bin || r.prproj || caminho, sequencias: seqs, carregada: null, tipo: prproj ? "prproj" : "avb",
                 escolhido: seqs.length === 1 ? seqs[0].mob_id : "" };
  // o mesmo projeto volta com as mesmas pastas (autor, 2026-10-03), se o editor ainda não apontou nenhuma
  if (prproj && !pastas.length && (r.pastas || []).length) addPasta(r.pastas);
  el("mcSeqBusca").value = "";
  irParaModo("bin");
  mostrarEscolhidoMC();
  if (seqs.length === 1) { await carregarSequenciaDaBin(); return; }   // uma só: não há o que marcar
  dizerNoArrasto(seqs.length === 1 ? `bin recebida: “${seqs[0].nome}”`
    : `bin com ${seqs.length} sequências — marque qual relinkar`, true);
}

el("mcSeqBusca").addEventListener("input", () => mostrarEscolhidoMC());

el("mcSequencias").addEventListener("change", (ev) => {
  if (!binExterna || !ev.target || ev.target.name !== "mcSeq") return;
  binExterna.escolhido = ev.target.value;
  mostrarEscolhidoMC();
});

/* "Carregar sequência": lê a marcada (`/mc/bin/sequencia`) e o cartão vira o da timeline da bin. */
async function carregarSequenciaDaBin() {
  if (!binExterna || !binExterna.escolhido) return;
  if (binExterna.tipo === "prproj") {
    // o projeto do Premiere: os fatos já vieram na lista; a leitura de verdade é o "Ler sequência" (a análise)
    const s = (binExterna.sequencias || []).find((x) => x.mob_id === binExterna.escolhido);
    binExterna.carregada = s ? Object.assign({}, s) : null;
    if (s) dizerNoArrasto(`timeline “${s.nome}” carregada`, true);
    mostrarEscolhidoMC();
    return;
  }
  const botao = el("mcSeqCarregar");
  botao.disabled = true;
  try {
    binExterna.carregada = await post("/mc/bin/sequencia", { caminho: binExterna.caminho, mob_id: binExterna.escolhido });
    dizerNoArrasto(`timeline “${binExterna.carregada.nome}” carregada`, true);
  } catch (e) {
    dizerNoArrasto(e.message, false);
  }
  mostrarEscolhidoMC();
}
el("mcSeqCarregar").onclick = carregarSequenciaDaBin;

/* Magic Link Avid → Avid (autor, 2026-10-12): o envio traz a bin ANEXA à Carta. "Carregar" a abre como a bin de fora,
   marca a sequência DO ENVIO (pelo MobID da Carta; o nome, se o MobID não estiver lá) e a carrega. Depois do relink, o
   envio desce para "importado" (`/receber/trazido`, em `mostrarFeito`). */
async function carregarEnvioMC(id) {
  const e = ((rcCaixa && rcCaixa.envios) || []).find((x) => x.id === id);
  if (!e || !e.bin_anexa) return;
  await carregarBinExterna(e.bin_anexa);
  if (!binExterna) return;
  binExterna.envio = id;
  if (binExterna.carregada) return;                       // uma sequência só: já veio carregada
  const seqs = binExterna.sequencias || [];
  const s = seqs.find((x) => x.mob_id === e.mob_id) || seqs.find((x) => x.nome === (e.sequencia || e.nome));
  if (s) { binExterna.escolhido = s.mob_id; await carregarSequenciaDaBin(); }
  else mostrarEscolhidoMC();
}

el("mcCargaTirar").onclick = () => {
  // Da sequência carregada de uma bin com várias, o × volta à LISTA (a seleção); da lista, à área de soltar.
  if (modoOrigem === "bin" && binExterna && binExterna.carregada && (binExterna.sequencias || []).length > 1) {
    binExterna.carregada = null;
    mostrarEscolhidoMC();
    return;
  }
  arrastada = null;
  binExterna = null;
  el("campoAaf").value = "";
  if (modoOrigem === "aaf" || modoOrigem === "bin") irParaModo("mc");
  mostrarEscolhidoMC();
  dizerNoArrasto("");   // a resposta do que saiu ("timeline … carregada") não fica sobrando (2026-10-13)
};

/* "Carregar a sequência aberta": a do monitor Record (`/mc/record`) — termina no mesmo `adotarSequence` do arrasto. */
async function carregarSequenciaAberta() {
  dizerNoArrasto("lendo a sequência aberta no Record…", true);
  let r;
  try { r = await api("/mc/record"); }
  catch (e) { dizerNoArrasto("o Media Composer não respondeu: " + e.message, false); return; }
  if (!r || r.vazio || !r.mob_id) {
    dizerNoArrasto("o monitor Record está vazio — abra a sequência na timeline e tente de novo", false);
    return;
  }
  await adotarSequence({ id: r.mob_id, type: "sequence" }, 0, "aberta no Record");
}

/* "Carregar a seleção da timeline" (autor, 2026-10-25): os clipes selecionados na timeline do MC → a sequência do
   Record, com o relink limitado aos masters deles (`so_masters`).

   DOIS caminhos. 1º o ARO (`/mc/selecao-aro`): a dylib lê a seleção POR DENTRO do MC — sem piscar, sem bin temporária —
   e dá o MobID da fonte de cada segmento (banco, arrastar.md §"IDENTIDADE pelo GetSrcMobID"). Com ele indisponível ou
   não validado (versão do MC não conferida, nada selecionado), cai no 2º, a CÓPIA do editor (`/mc/selecao`: o serviço
   traz o MC à frente e dá Cmd+0 → Cmd+C) — que pisca, mas sempre funciona. */
async function carregarSelecaoDaTimeline() {
  dizerNoArrasto("lendo a seleção da timeline…", true);
  let r = null, viaAro = false;
  // 1º caminho: o ARO, sem piscar. Erro/indisponível/não-validado → tenta o Cmd+C.
  try {
    const a = await post("/mc/selecao-aro", {});
    if (a && a.ok) { r = a; viaAro = true; }
    // MC fechado: o Cmd+C também não teria a quem copiar — diz a causa e para
    else if (a && a.mc_fechado) { dizerNoArrasto(a.erro, false); return; }
  } catch (e) { /* ignora — cai no Cmd+C */ }
  if (!r) {
    dizerNoArrasto("copiando a seleção da timeline…", true);
    try { r = await post("/mc/selecao", {}); }
    catch (e) { dizerNoArrasto("o Media Composer não respondeu: " + e.message, false); return; }
    if (!r || !r.ok) { dizerNoArrasto((r && r.erro) || "não consegui ler a seleção da timeline", false); return; }
  }
  irParaModo("mc");
  const arquivos = r.masters.length;
  const temTrecho = r.entrada != null && r.saida != null;
  guardarArrastada([{ mob_id: r.mob_id, nome: r.nome || "timeline", colunas: r.colunas || null,
                      de: "seleção da timeline · só estes clipes serão relinkados", so_masters: r.masters,
                      selecao: { clipes: r.clipes, arquivos, nomes: r.nomes || [],
                                 trecho: temTrecho ? `${r.entrada} → ${r.saida}` : "",
                                 trilhas: (r.trilhas || []).join(" ") } }]);
  aplicarArrastada();
  // ⚠️ pela cópia (Cmd+C), o que vem é o TRECHO (1º ao último selecionado em cada trilha); pelo ARO, é a seleção EXATA
  const lista = (r.nomes || []).slice(0, 4).join(", ") + ((r.nomes || []).length > 4 ? "…" : "");
  const porDentro = viaAro ? " (lidos por dentro, sem piscar)" : "";
  dizerNoArrasto(`só estes serão relinkados${porDentro}: ${lista || arquivos + " clipe(s)"} — o resto da timeline fica como está`,
                 true);
}

/* ── Preset de export ─────────────────────────────────────────────────────────
   ⚠️ O editor NÃO escolhe. O formato do export é requisito do plugin: um preset
   errado faz o MC renderizar a timeline inteira no formato dele — medido, 26 minutos
   de WAVE. O que ele pode fazer é instalar o nosso, e isso exige o MC fechado, porque
   o Media Composer reescreve as settings ao sair. */
async function verificarPreset() {
  const alvo = el("estadoPreset");
  const botao = el("btnInstalarPreset");
  const aviso = el("avisoPreset");
  try {
    const d = await api("/mc/preset");
    const texto = {
      ok: `“${d.preset}” instalado e correto`,
      ausente: `“${d.preset}” não está instalado`,
      divergente: `“${d.preset}” está diferente do esperado`,
      sem_settings: "não achei as settings do Media Composer",
    }[d.situacao] || d.situacao;

    alvo.textContent = texto;
    alvo.className = "estado-preset " + (d.situacao === "ok" ? "ok" : "pendente");
    botao.hidden = d.situacao === "ok" || d.situacao === "sem_settings";
    presetOk = d.situacao === "ok";

    if (d.situacao !== "ok" && d.mc_aberto) {
      aviso.textContent = "feche o Media Composer para instalar — ele reescreve as " +
                          "settings ao sair, e desfaria o que fizermos agora.";
      aviso.hidden = false;
    } else if (d.motivo && d.situacao !== "ok") {
      aviso.textContent = d.motivo; aviso.hidden = false;
    } else {
      aviso.hidden = true;
    }
  } catch (_) {
    alvo.textContent = "—"; botao.hidden = true; aviso.hidden = true;
  }
}
let presetOk = true;
/* Qual rota a última preparação usou. `avb` dispensa o preset por completo. */
let rotaEmUso = "";

/* O bloco do preset some quando ele não é mais requisito — em vez de ficar cobrando
   uma instalação que o fluxo não usa. Foi o atrito que abriu a conversa do ADR 0013. */
function aplicarVisibilidadeDoPreset() {
  const bloco = el("campoPreset");
  if (!bloco) return;
  const dispensavel = rotaEmUso === "avb";
  bloco.hidden = dispensavel;
  const nota = el("notaRotaAvb");
  if (nota) nota.hidden = !dispensavel;
}

/* ── Preparar ─────────────────────────────────────────────────────────────── */
/* O corpo do `/trabalho/preparar` para o que está na caixa agora: `{corpo}` ou `{erro}`. A PRÉVIA da lista de mídias
   usa o mesmo — é o que garante que o "Relinkar" possa aproveitá-la (mesma chave = mesmo pedido). */
function corpoDoPreparar() {
  // ⛔ A pasta voltou a ser obrigatória mesmo com banco (2026-08-17): dispensá-la fazia o
  // `LinkFile` do Avid ficar muito mais lento — a varredura também aquecia o cache dos
  // arquivos, e sem ela o custo migrava para dentro do Media Composer. Ver `rotas.py`.
  if (!pastas.length) return { erro: "aponte ao menos uma pasta de mídia" };
  const corpo = {
    pastas: pastas.slice(),
    achatar_subclipes: el("optSubclipes").checked,
    achatar_group_clips: el("optGrupos").checked,
  };
  if (modoOrigem === "bin") {
    const s = binExterna && binExterna.carregada;
    if (!s) return { erro: "marque a sequência da bin e clique em “Carregar sequência”" };
    if (binExterna.tipo === "prproj") corpo.prproj = binExterna.caminho;
    else corpo.bin_externa = binExterna.caminho;
    corpo.sequence_mob_id = s.mob_id;
    corpo.sequence = s.nome || "";
  } else if (modoOrigem === "aaf") {
    corpo.aaf = el("campoAaf").value.trim();
    if (!corpo.aaf) return { erro: "informe o caminho do AAF" };
  } else {
    const item = arrastada && arrastada.itens.find((x) => x.mob_id === arrastada.escolhido);
    if (!item) return { erro: "arraste a timeline da bin para cá" };
    corpo.sequence_mob_id = item.mob_id;
    corpo.sequence = item.nome || "";
    if (item.so_masters && item.so_masters.length) corpo.so_masters = item.so_masters;
  }
  // Relink parcial: os dois filtros são independentes e se somam.
  corpo.so_importados = el("optSoImportados").checked;
  corpo.so_offline = el("optSoOffline").checked;
  return { corpo };
}

/* A chave de um pedido: o que decide o CASAMENTO (os achatamentos só valem no aplicar e vão por `/trabalho/opcoes`). */
function chaveDoPedido(corpo) {
  if (!corpo) return "";
  const resto = Object.assign({}, corpo);
  delete resto.achatar_subclipes;
  delete resto.achatar_group_clips;
  return JSON.stringify(resto);
}

/* O botão principal do relink (organograma "Ler Sequência e Relink Manual", 2026-10-13): UM botão que muda de função.
   Sem leitura válida deste pedido → "Ler sequência" (lê e casa: `rodarPrevia`). Lida → "Relinkar sequência": assume a
   leitura e relinka DIRETO (a antiga tela intermediária "95 de 99 prontos" saiu — a lista já mostrou tudo). */
async function preparar() {
  const { corpo, erro } = corpoDoPreparar();
  if (erro) { dizer(erro, false); return; }
  dizer("");
  if (previaMC.estado === "pronta" && previaMC.chave === chaveDoPedido(corpo)) return relinkarMC();
  return rodarPrevia();
}

async function relinkarMC() {
  try {
    await post("/trabalho/assumir");
    for (const [campo, id] of [["achatar_subclipes", "optSubclipes"], ["achatar_group_clips", "optGrupos"]])
      await post("/trabalho/opcoes", { [campo]: el(id).checked });
    rotaEmUso = previaMC.rota || "avb";
    aplicarVisibilidadeDoPreset();
    // Vazio deixa o serviço usar o padrão; ele é quem resolve colisão de nome — e o nome que VOLTA é o que vale.
    const r = await post("/trabalho/aplicar", { nome_bin: el("nomeBin").value.trim(),
                                                reescalar: Array.from(mcEscalasAceitas) });
    previaMC = { chave: "", estado: "", masters: [] };   // assumida e aplicada: um próximo pedido lê de novo
    avisarSobreABin(r && r.bin);
    mostrarPasso("passoProgresso");
    acompanhar();
    // ⛔ CORRIGE (autor, 2026-10-25: "a opção relinkar sequência não fez nada"): com tudo ignorado o serviço recusa
    // ("nada decidido") e o `dizer` escrevia fora da vista — a recusa vai para o bloco da lista, onde está o botão
  } catch (e) { dizerManual(e.message, false); }
}

/* ── Tabela de mídias (organograma "Ler Sequência e Relink Manual", aprovado em 2026-10-13) ──────────────────────
   A 1ª coluna é a situação (a bola colorida), FIXA: a bola branca do título ordena por situação (de novo, inverte;
   na terceira, volta à ordem natural). Duplo clique no título de uma coluna ordena por ela, A→Z (de novo, Z→A); a bola
   desfaz. As outras mudam de LARGURA pela borda direita do título e de LUGAR arrastando o
   título para os lados; as duas coisas ficam lembradas nesta máquina (`localStorage`, por tabela). A caixa rola para
   os dois lados (autor: "sempre falta a barra de scroll horizontal"). Seleção como no Explorer: clique = só ela,
   Ctrl = soma/tira, Shift = intervalo. Os filtros são as etiquetas de contagem acima da tabela.
   ⚠️ Chrome 80 (Resolve 19): nada de `inset`, `:is`, campo privado de classe; eventos de ponteiro existem. */
const SITUACAO = {
  amb: { classe: "warn", rotulo: "a conferir", plural: "a conferir", rank: 0 },
  bad: { classe: "err", rotulo: "sem mídia", plural: "sem mídia", rank: 1 },
  man: { classe: "man", rotulo: "manual", plural: "manual", rank: 2 },
  ign: { classe: "ign", rotulo: "ignorada", plural: "ignoradas", rank: 3 },
  /* não casou com nada, mas já está online no MC (Avid MediaFiles ou link AMA do projeto; autor, 2026-10-13) */
  onl: { classe: "onl", rotulo: "já online", plural: "já online", rank: 4 },
  ok: { classe: "ok", rotulo: "encontrada", plural: "encontradas", rank: 5 },
};

function criarTabela(op) {
  /* op: { tabela, caixa, filtros?, chave, colunas: [{id, titulo, largura}], celula(linha, id) → html,
          titulo(linha, id) → texto do `title`, aoMudar() } — `linhas` = [{k, s, ...}] (k: chave; s: situação) */
  const t = { linhas: [], sel: new Set(), ancora: null, filtro: "", ordem: 0, ordemCol: null };
  const CHAVE = `delapraca.tabela.${op.chave}`;
  let guardado = {};
  try { guardado = JSON.parse(localStorage.getItem(CHAVE) || "{}") || {}; } catch (_) { guardado = {}; }
  const ids = op.colunas.map((c) => c.id);
  t.cols = (Array.isArray(guardado.cols) ? guardado.cols.filter((i) => ids.indexOf(i) >= 0) : []);
  for (const i of ids) if (t.cols.indexOf(i) < 0) t.cols.push(i);
  t.larg = Object.assign({}, ...op.colunas.map((c) => ({ [c.id]: c.largura })), guardado.larg || {});
  const guardar = () => {
    try { localStorage.setItem(CHAVE, JSON.stringify({ cols: t.cols, larg: t.larg })); } catch (_) { /* preferência */ }
  };
  const col = (id) => op.colunas.find((c) => c.id === id) || { titulo: id };

  t.visiveis = () => {
    const l = t.linhas.filter((x) => !t.filtro || x.s === t.filtro);
    if (t.ordemCol) {
      const { id, desc } = t.ordemCol;
      const txt = (x) => String(x[id] == null ? "" : x[id]);
      const cmp = (a, b) => txt(a).localeCompare(txt(b), "pt-BR", { numeric: true, sensitivity: "base" }) * (desc ? -1 : 1);
      return l.map((x, i) => [x, i]).sort((a, b) => cmp(a[0], b[0]) || a[1] - b[1]).map((p) => p[0]);
    }
    if (t.ordem) {
      const cmp = (a, b) => ((SITUACAO[a.s] || {}).rank - (SITUACAO[b.s] || {}).rank) * t.ordem;
      return l.map((x, i) => [x, i]).sort((a, b) => cmp(a[0], b[0]) || a[1] - b[1]).map((p) => p[0]);
    }
    return l;
  };
  t.selecionadas = () => t.linhas.filter((x) => t.sel.has(x.k));

  t.pintar = () => {
    const vis = t.visiveis();
    const ks = new Set(vis.map((x) => x.k));
    for (const k of Array.from(t.sel)) if (!ks.has(k)) t.sel.delete(k);     // o filtro esconde
    const largura = 26 + t.cols.reduce((s, i) => s + (t.larg[i] || 120), 0);
    op.tabela.style.width = `${largura}px`;
    op.tabela.innerHTML =
      `<colgroup><col style="width:26px">${t.cols.map((i) => `<col style="width:${t.larg[i] || 120}px">`).join("")}</colgroup>` +
      `<thead><tr><th class="st" title="ordenar por situação"><button type="button" class="bola${t.ordem ? " on" : ""}"
         aria-label="ordenar por situação"></button></th>${t.cols.map((i) =>
        `<th data-col="${i}" title="duplo clique para ordenar; arraste para mudar de lugar"${t.ordemCol && t.ordemCol.id === i
          ? ` aria-sort="${t.ordemCol.desc ? "descending" : "ascending"}"` : ""}>${escapar(col(i).titulo)}${t.ordemCol && t.ordemCol.id === i
          ? `<span class="seta">${t.ordemCol.desc ? "▾" : "▴"}</span>` : ""}<span class="alca"
           title="arraste para mudar a largura"></span></th>`).join("")}</tr></thead>` +
      `<tbody>${vis.map((x) => {
        const s = SITUACAO[x.s] || SITUACAO.bad;
        return `<tr data-k="${escapar(x.k)}" class="${[t.sel.has(x.k) ? "sel" : "", x.s === "ign" ? "ign" : ""].join(" ").trim()}"
                   aria-selected="${t.sel.has(x.k)}"><td class="st" title="${escapar(s.rotulo)}"><span class="midia-ponto ${s.classe}"></span></td>${
          t.cols.map((i) => `<td data-col="${i}" title="${escapar(op.titulo ? op.titulo(x, i) : "")}">${op.celula(x, i)}</td>`).join("")}</tr>`;
      }).join("") || `<tr class="vazia"><td colspan="${t.cols.length + 1}">${escapar(t.vazio || "nada a mostrar com este filtro")}</td></tr>`}</tbody>`;
    if (op.filtros) {
      const conta = {};
      for (const x of t.linhas) conta[x.s] = (conta[x.s] || 0) + 1;
      if (t.filtro && !conta[t.filtro]) t.filtro = "";
      op.filtros.innerHTML = !t.linhas.length ? "" :
        `<button type="button" class="pill todas${t.filtro ? "" : " on"}" data-f="">Todas ${t.linhas.length}</button>` +
        Object.keys(SITUACAO).filter((s) => conta[s]).map((s) =>
          `<button type="button" class="pill ${SITUACAO[s].classe}${t.filtro === s ? " on" : ""}" data-f="${s}">${conta[s]} ${
            escapar(conta[s] === 1 ? SITUACAO[s].rotulo : SITUACAO[s].plural)}</button>`).join("");
    }
    if (op.aoMudar) op.aoMudar();
  };

  if (op.filtros) op.filtros.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-f]");
    if (!b) return;
    t.filtro = b.dataset.f && t.filtro !== b.dataset.f ? b.dataset.f : "";
    t.pintar();
  });

  op.tabela.addEventListener("click", (ev) => {
    if (ev.target.closest("th")) {
      if (ev.target.closest(".bola")) { t.ordemCol = null; t.ordem = t.ordem === 0 ? 1 : t.ordem === 1 ? -1 : 0; t.pintar(); }
      return;
    }
    const tr = ev.target.closest("tr[data-k]");
    if (!tr) return;
    const k = tr.dataset.k;
    const ordem = t.visiveis().map((x) => x.k);
    const somar = ev.ctrlKey || ev.metaKey;
    if (ev.shiftKey && t.ancora && ordem.indexOf(t.ancora) >= 0) {
      const par = [ordem.indexOf(t.ancora), ordem.indexOf(k)].sort((p, q) => p - q);
      if (!somar) t.sel = new Set();
      for (const x of ordem.slice(par[0], par[1] + 1)) t.sel.add(x);
    } else if (somar) {
      if (t.sel.has(k)) t.sel.delete(k); else t.sel.add(k);
      t.ancora = k;
    } else {
      t.sel = t.sel.size === 1 && t.sel.has(k) ? new Set() : new Set([k]);   // de novo: desmarca
      t.ancora = k;
    }
    t.pintar();
  });

  // Largura (a alça da borda) e posição (arrastar o título): ponteiro capturado no próprio título.
  op.tabela.addEventListener("pointerdown", (ev) => {
    const th = ev.target.closest("th[data-col]");
    if (!th || ev.button !== 0) return;
    ev.preventDefault();
    const id = th.dataset.col;
    const x0 = ev.clientX;
    th.setPointerCapture(ev.pointerId);
    if (ev.target.classList.contains("alca")) {
      const w0 = t.larg[id] || th.getBoundingClientRect().width;
      const colEl = op.tabela.querySelectorAll("col")[1 + t.cols.indexOf(id)];
      const mover = (e) => {
        t.larg[id] = Math.max(48, Math.min(900, Math.round(w0 + e.clientX - x0)));
        if (colEl) colEl.style.width = `${t.larg[id]}px`;
        op.tabela.style.width = `${26 + t.cols.reduce((s, i) => s + (t.larg[i] || 120), 0)}px`;
      };
      const soltar = () => { th.removeEventListener("pointermove", mover); th.removeEventListener("pointerup", soltar); guardar(); };
      th.addEventListener("pointermove", mover);
      th.addEventListener("pointerup", soltar);
      return;
    }
    let alvo = null, depois = false, andou = false;
    const ths = () => Array.from(op.tabela.querySelectorAll("th[data-col]"));
    const limpar = () => { for (const h of ths()) h.classList.remove("alvo-esq", "alvo-dir"); };
    const mover = (e) => {
      if (!andou && Math.abs(e.clientX - x0) < 4) return;
      andou = true;
      th.classList.add("arrastando");
      limpar();
      alvo = null;
      for (const h of ths()) {
        const r = h.getBoundingClientRect();
        if (e.clientX >= r.left && e.clientX < r.right) {
          alvo = h.dataset.col;
          depois = e.clientX >= r.left + r.width / 2;
          h.classList.add(depois ? "alvo-dir" : "alvo-esq");
        }
      }
    };
    const soltar = () => {
      th.removeEventListener("pointermove", mover);
      th.removeEventListener("pointerup", soltar);
      th.classList.remove("arrastando");
      limpar();
      if (!andou || !alvo || alvo === id) return;
      const sem = t.cols.filter((i) => i !== id);
      const pos = sem.indexOf(alvo) + (depois ? 1 : 0);
      sem.splice(pos, 0, id);
      t.cols = sem;
      guardar();
      t.pintar();
    };
    th.addEventListener("pointermove", mover);
    th.addEventListener("pointerup", soltar);
  });

  op.tabela.addEventListener("dblclick", (ev) => {
    const th = ev.target.closest("th[data-col]");
    if (!th || ev.target.classList.contains("alca")) return;
    const id = th.dataset.col;
    t.ordemCol = t.ordemCol && t.ordemCol.id === id ? { id, desc: !t.ordemCol.desc } : { id, desc: false };
    t.ordem = 0;
    t.pintar();
  });

  // Ctrl+A seleciona as visíveis; Esc limpa (com o foco na caixa).
  if (op.caixa) op.caixa.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && (ev.key === "a" || ev.key === "A")) {
      ev.preventDefault();
      t.sel = new Set(t.visiveis().map((x) => x.k));
      t.pintar();
    } else if (ev.key === "Escape" && t.sel.size) {
      t.sel = new Set();
      t.pintar();
    }
  });
  return t;
}

const nomeDoCaminho = (c) => String(c || "").split(/[\\/]/).pop();
const extDoCaminho = (c) => ((String(c || "").match(/\.([A-Za-z0-9]{2,5})$/) || [])[1] || "").toUpperCase();

/* ── Lista de mídias do Media Composer: LER, conferir, corrigir ─────────────────
   Organograma "Ler Sequência e Relink Manual" (aprovado pelo autor em 2026-10-13). ⛔ NADA casa sozinho: o editor pode
   querer apontar várias pastas, e um casamento disparado a cada pasta o interrompia. Indicar timeline ou pasta só
   INVALIDA a leitura anterior (o botão volta a "Ler sequência"); quem lê é o botão. A leitura é o mesmo
   `/trabalho/preparar` com `previa: true` (o serviço só lê e casa; ⛔ sem a bin da timeline recusa em vez de
   exportar), acompanhada por `/trabalho` (não pelo SSE, que troca de tela). */
let previaMC = { chave: "", estado: "", masters: [] };
let mcEscalasAceitas = new Set();      // a escala de outra mídia que o editor aceitou (`pintarEscalasMC`)
let previaTimer = 0;
let tabelaMC = null;
let mcCodecManual = {};          // {mob_id → codec que a sondagem do relink manual leu}

function agendarPrevia() {
  if (NLE !== "mc") return;
  clearTimeout(previaTimer);
  previaTimer = setTimeout(atualizarLeituraMC, 30);
}

/* Timeline ou pastas mudaram: a leitura de OUTRO pedido não vale mais (e uma em andamento é cancelada). */
function atualizarLeituraMC() {
  const { corpo } = corpoDoPreparar();
  const chave = corpo ? chaveDoPedido(corpo) : "";
  if (previaMC.estado && previaMC.chave !== chave) {
    if (previaMC.estado === "rodando") post("/trabalho/cancelar").catch(() => {});
    previaMC = { chave: "", estado: "", masters: [] };
    mcCodecManual = {};
    el("mcManualMsg").hidden = true;
  }
  pintarListaMC();
}

/* O master casado → a linha da tabela. `s` é a situação (ver `SITUACAO`); a chave é o MobID. */
const ONDE_ONLINE = { gerenciada: "online na Avid MediaFiles", ama: "online por um link do projeto" };

function linhaDaMidiaMC(m) {
  const s = m.ignorado ? "ign" : m.metodo === "manual" ? "man"
    : m.arquivo && !m.precisa_de_revisao ? "ok"
    : (m.arquivo || m.sugestao || (m.candidatos || []).length) ? "amb"
    : m.ja_online ? "onl" : "bad";
  const arq = m.arquivo || "";
  let encontrado = arq ? nomeDoCaminho(arq) : "";
  if (s === "amb") {
    const n = (m.candidatos || []).length;
    encontrado = n > 1 ? `${n} candidatos · escolha em Revisar`
      : m.sugestao ? `sugerido: ${nomeDoCaminho(m.sugestao)}` : `${nomeDoCaminho(arq)} · conferir`;
  }
  if (s === "ign") encontrado = "mantém o link atual";
  if (s === "onl") encontrado = `não casou · ${ONDE_ONLINE[m.ja_online] || "já online"}`;
  return { k: m.mob_id, s, nome: m.nome, arquivo: arq, encontrado, origem: m.origem || "",
           codec: mcCodecManual[m.mob_id] || extDoCaminho(arq || m.sugestao), m };
}

function tabelaDaListaMC() {
  if (tabelaMC) return tabelaMC;
  tabelaMC = criarTabela({
    tabela: el("mcListaTabela"), caixa: el("mcListaCaixa"), filtros: el("mcListaFiltros"), chave: "mc.lista",
    colunas: [{ id: "nome", titulo: "Na timeline", largura: 190 }, { id: "codec", titulo: "Codec", largura: 80 },
              { id: "encontrado", titulo: "Encontrado", largura: 210 }, { id: "origem", titulo: "De onde veio", largura: 280 }],
    celula: (x, id) => id === "origem" ? `<span class="mono"><bdi>${escapar(x.origem || "—")}</bdi></span>`
      : `<bdi>${escapar(x[id] || (id === "encontrado" || id === "codec" ? "—" : ""))}</bdi>`,
    titulo: (x, id) => id === "encontrado" ? (x.arquivo || x.encontrado) : id === "origem" ? x.origem : x[id] || "",
    aoMudar: pintarAcoesMC,
  });
  return tabelaMC;
}

/* O bloco da lista: aparece com timeline e ao menos uma pasta (antes de ler, "aguardando a leitura"). */
function pintarListaMC() {
  if (NLE !== "mc") return;
  const { corpo } = corpoDoPreparar();
  const t = tabelaDaListaMC();
  el("mcLista").hidden = !corpo;
  pintarEscalasMC();
  const lida = previaMC.estado === "pronta";
  el("campoNomeBin").hidden = !lida;
  t.linhas = lida ? previaMC.masters.map(linhaDaMidiaMC) : [];
  t.vazio = previaMC.estado === "rodando" ? "lendo a sequência e casando com as pastas…"
    : previaMC.estado === "erro" ? (previaMC.erro || "a leitura falhou")
    : "aguardando a leitura — indique todas as pastas e clique em “Ler sequência”";
  t.pintar();
  const ok = t.linhas.filter((x) => x.s === "ok" || x.s === "man").length;
  el("mcListaConta").textContent = lida ? `${ok} de ${t.linhas.length} prontas` : "";
  pintarBotaoPrincipalMC();
}

function pintarAcoesMC() {
  if (!tabelaMC) return;
  const sel = tabelaMC.selecionadas();
  const lida = previaMC.estado === "pronta";
  const conferir = tabelaMC.linhas.filter((x) => x.s === "amb").length;
  el("mcRevisar").textContent = conferir ? `Revisar mídias (${conferir} a conferir)` : "Revisar mídias";
  el("mcRevisar").disabled = !lida;
  const todasIgn = sel.length && sel.every((x) => x.s === "ign");
  el("mcIgnorar").textContent = todasIgn ? "Não ignorar" : sel.length > 1 ? `Ignorar (${sel.length})` : "Ignorar";
  el("mcIgnorar").disabled = !lida || !sel.length;
  el("mcManual").disabled = !lida || sel.length !== 1;
  el("mcManual").title = sel.length === 1 ? "escolher o arquivo para esta mídia" : "marque UMA linha da lista";
}

function pintarBotaoPrincipalMC() {
  const b = el("btnPreparar");
  const { corpo } = corpoDoPreparar();
  const lida = previaMC.estado === "pronta" && corpo && previaMC.chave === chaveDoPedido(corpo);
  b.disabled = !corpo || previaMC.estado === "rodando";
  b.textContent = previaMC.estado === "rodando" ? "Lendo a sequência…" : lida ? "Relinkar sequência" : "Ler sequência";
}

async function recarregarMastersMC() {
  const m = await api("/trabalho/masters");
  previaMC.masters = m.masters || [];
  pintarListaMC();
}

async function rodarPrevia() {
  const { corpo } = corpoDoPreparar();
  if (!corpo) return;
  if (el("passoOrigem").hidden) return;                 // no meio de um relink, a leitura não toca na sessão
  const chave = chaveDoPedido(corpo);
  if (chave === previaMC.chave && previaMC.estado === "rodando") return;
  let concluir = () => {};
  const minha = { chave, estado: "rodando", masters: [] };
  minha.promessa = new Promise((r) => { concluir = r; });
  previaMC = minha;
  mcCodecManual = {};
  el("mcManualMsg").hidden = true;
  pintarListaMC();
  const inicio = Date.now();
  pintarPreviaMC({ etapa: "começando", feito: 0, total: 0, detalhe: "" }, inicio);
  try {
    const r = await post("/trabalho/preparar", Object.assign({}, corpo, { previa: true }));
    minha.rota = r && r.rota;
    for (let i = 0; i < 600; i++) {                       // prazo: 5 min (uma varredura grande de pastas)
      await new Promise((ok) => setTimeout(ok, 500));
      if (previaMC !== minha) return;                      // o pedido mudou no meio: esta não vale mais
      const e = await api("/trabalho");
      if (e.ocupada) { pintarPreviaMC(e, inicio); continue; }
      if (e.fase === "erro") throw new Error(e.erro || "a leitura falhou");
      if (e.fase !== "pronto") throw new Error("a leitura foi interrompida");
      const m = await api("/trabalho/masters");
      if (previaMC !== minha) return;
      minha.masters = m.masters || [];
      minha.escalas = (e.trabalho || {}).escala_de_outra_midia || [];
      minha.estado = "pronta";
      tabelaDaListaMC().sel = new Set();
      pintarListaMC();
      return;
    }
    throw new Error("a leitura passou do prazo (5 min)");
  } catch (e) {
    if (previaMC !== minha) return;
    minha.estado = "erro";
    minha.erro = e.message;
    pintarListaMC();
  } finally {
    if (previaMC === minha) el("mcPreviaProg").hidden = true;
    concluir();
  }
}

/* ── A escala digitada para OUTRA mídia no .prproj (autor, 2026-10-29: "como o Resolve") ────────────────────────────
   A oferta da leitura (`escala_de_outra_midia`: {caminho, nome, fator, planos}). Marcado = o Relinkar multiplica a
   escala dos planos desse arquivo pelo fator; desmarcado = entra como o projeto diz. Os dois com marcador amarelo.
   O que o editor marcou sobrevive a uma releitura (pelo caminho). */

function pintarEscalasMC() {
  const ofertas = previaMC.estado === "pronta" ? previaMC.escalas || [] : [];
  const presentes = new Set(ofertas.map((x) => x.caminho));
  mcEscalasAceitas = new Set(Array.from(mcEscalasAceitas).filter((c) => presentes.has(c)));
  el("mcEscalas").hidden = !ofertas.length;
  // o índice, não o caminho, no atributo (como no `pintarEscalas`)
  el("mcEscalasLista").innerHTML = ofertas.map((x, i) => {
    const id = `mcEsc_${i}`;
    return `<label class="item rc-item" for="${id}"><input type="checkbox" id="${id}" data-esc="${i}"
        ${mcEscalasAceitas.has(x.caminho) ? "checked" : ""}>
      <div class="rc-texto"><span class="item-nome"><bdi>${escapar(x.nome)}</bdi></span></div>
      <span class="pill warn">× ${escapar(String(x.fator).replace(".", ","))} · ${x.planos} ${x.planos === 1 ? "plano" : "planos"}</span></label>`;
  }).join("");
  const todas = ofertas.length && ofertas.every((x) => mcEscalasAceitas.has(x.caminho));
  el("mcEscalasTodas").textContent = todas ? "Não ajustar nenhum" : "Ajustar todos";
}
el("mcEscalasLista").addEventListener("change", (ev) => {
  const c = ev.target.closest("input[data-esc]");
  const x = c && (previaMC.escalas || [])[Number(c.dataset.esc)];
  if (!x) return;
  if (c.checked) mcEscalasAceitas.add(x.caminho); else mcEscalasAceitas.delete(x.caminho);
  pintarEscalasMC();
});
el("mcEscalasTodas").onclick = () => {
  const ofertas = previaMC.escalas || [];
  const todas = ofertas.every((x) => mcEscalasAceitas.has(x.caminho));
  mcEscalasAceitas = todas ? new Set() : new Set(ofertas.map((x) => x.caminho));
  pintarEscalasMC();
};

/* O andamento da leitura (`/trabalho`: etapa, feito, total e o arquivo da vez em `detalhe`), como o `pintarAndamento`
   do Resolve: sem contagem (a varredura das pastas não sabe o total antes de acabar), a barra se move sozinha. */
function pintarPreviaMC(e, inicio) {
  const conta = !!e.total;
  el("mcPreviaProg").hidden = false;
  el("mcPreviaEtapa").textContent = e.etapa ? e.etapa.charAt(0).toUpperCase() + e.etapa.slice(1) : "—";
  el("mcPreviaBarraFundo").classList.toggle("indeterminada", !conta);
  el("mcPreviaBarra").style.width = conta ? `${Math.round(100 * Math.min(1, e.feito / e.total))}%` : "";
  el("mcPreviaConta").textContent = conta ? `${e.feito} de ${e.total}` : "";
  el("mcPreviaAtual").textContent = e.detalhe || "";
  el("mcPreviaTempo").textContent = relogio(Math.round((Date.now() - inicio) / 1000));
}

/* ── As ações da lista: Ignorar, Relink manual, Revisar ── */
el("mcIgnorar").onclick = async () => {
  const sel = tabelaMC ? tabelaMC.selecionadas() : [];
  if (!sel.length) return;
  const ignorar = !sel.every((x) => x.s === "ign");
  try {
    await post("/trabalho/ignorar", { mob_ids: sel.map((x) => x.k), ignorar });
    await recarregarMastersMC();
  } catch (e) { dizerManual(e.message, false); }
};

/* A resposta do relink manual, DENTRO do bloco da lista (sem pular o painel): aceito em azul, recusado em vermelho. */
const dizerManualMC = (...a) => dizerManual(...a);
function dizerManual(texto, ok, titulo) {
  const p = el("mcManualMsg");
  p.innerHTML = (titulo ? `<strong><bdi>${escapar(titulo)}</bdi></strong><br>` : "") + escapar(texto || "");
  p.className = "mc-manual " + (ok ? "aceito" : "recusado");
  p.hidden = !texto;
}

/* Relink manual de UMA mídia: o diálogo do Windows (ou um arquivo solto do Explorer sobre a linha). A escolha do
   editor vence toda regra automática; o serviço só recusa o impossível (`relink_manual.validar`). */
async function relinkManual(linha, arquivo, dizerManual = dizerManualMC) {
  if (!linha) { dizerManual("marque uma linha da lista", false); return false; }
  if (!arquivo) {
    try {
      const r = await post("/escolher/midia", { nome: linha.nome });
      arquivo = r.caminho;
    } catch (e) { dizerManual(e.message, false); return false; }
    if (!arquivo) return false;                           // cancelou o diálogo
  }
  const titulo = `${linha.nome} → ${nomeDoCaminho(arquivo)}`;
  try {
    const r = await post("/trabalho/manual", { mob_id: linha.k, arquivo });
    if (r.codec) mcCodecManual[linha.k] = String(r.codec).toUpperCase();
    dizerManual(`manual · ${r.texto || "aceito"}`, true, titulo);
    return true;
  } catch (e) {
    dizerManual(e.corpo && e.corpo.recusa ? e.corpo.recusa : e.message, false,
                e.corpo && e.corpo.recusa ? `${titulo}: não dá` : titulo);
    return false;
  }
}

el("mcManual").onclick = async () => {
  const sel = tabelaMC ? tabelaMC.selecionadas() : [];
  if (sel.length !== 1) return;
  if (await relinkManual(sel[0])) await recarregarMastersMC().catch(() => {});
};

/* Um arquivo solto sobre a lista: relink manual da linha sob o cursor (ou da marcada). Uma PASTA solta aqui vai para
   o bloco 2, como se tivesse sido solta lá: é o engano mais provável, e recusar seria pior. */
async function soltarMidiaManual(caminhos, alvo) {
  const arquivo = caminhos.find((c) => /\.[A-Za-z0-9]{2,5}$/.test(c) && !eArquivoDeTimeline(c));
  if (!arquivo) return soltarPastasDeMidia(caminhos);
  if (previaMC.estado !== "pronta") { dizerNoArrasto("leia a sequência primeiro (“Ler sequência”)", false); return; }
  const tr = alvo && alvo.closest ? alvo.closest("#mcListaTabela tr[data-k]") : null;
  const t = tabelaDaListaMC();
  const linha = tr ? t.linhas.find((x) => x.k === tr.dataset.k) : (t.selecionadas().length === 1 ? t.selecionadas()[0] : null);
  if (!linha) { dizerManual("solte o arquivo sobre a linha da mídia que ele substitui", false); return; }
  t.sel = new Set([linha.k]);
  if (await relinkManual(linha, arquivo)) await recarregarMastersMC().catch(() => {});
  else t.pintar();
}

/* "Revisar mídias": a janela larga do aplicativo (empates, sugestões). Enquanto ela estiver aberta, a lista daqui relê
   o serviço a cada 3 s — cada decisão de lá já foi gravada no clique. */
let revisaoTimer = 0;
el("mcRevisar").onclick = async () => {
  await abrirJanelaRevisao(el("mcRevisar"), (texto) => dizerManual(texto, false));
  clearInterval(revisaoTimer);
  let vezes = 0;
  revisaoTimer = setInterval(async () => {
    vezes++;
    if (vezes > 200 || previaMC.estado !== "pronta" || el("passoOrigem").hidden) { clearInterval(revisaoTimer); return; }
    try {
      const m = await api("/trabalho/masters");
      if (JSON.stringify(m.masters || []) !== JSON.stringify(previaMC.masters)) {
        previaMC.masters = m.masters || [];
        pintarListaMC();
      }
    } catch (_) { /* o serviço volta; a próxima volta tenta de novo */ }
  }, 3000);
};

for (const id of ["optSoImportados", "optSoOffline"]) el(id).addEventListener("change", () => agendarPrevia());
el("campoAaf").addEventListener("change", () => agendarPrevia());

/* ── Revisão ──────────────────────────────────────────────────────────────── */
let filtro = "revisao";
/* a janela de conflito já se abriu sozinha nesta preparação (volta a `false` quando uma preparação nova começa) */
let conflitoJaAberto = false;

function pill(texto, classe) {
  return `<span class="pill ${classe || ""}">${escapar(texto)}</span>`;
}

async function carregarRevisao() {
  const estado = await api("/trabalho");
  const t = estado.trabalho || {};
  el("placar").innerHTML =
    pill(`${t.resolvidos || 0} de ${t.total || 0} prontos`, "ok") +
    ((t.sugeridos) ? pill(`${t.sugeridos} sugerido${t.sugeridos > 1 ? "s" : ""}`, "warn") : "") +
    ((t.ambiguos) ? pill(`${t.ambiguos} ambíguo${t.ambiguos > 1 ? "s" : ""}`, "warn") : "") +
    ((t.nao_resolvidos) ? pill(`${t.nao_resolvidos} sem mídia`, "err") : "") +
    pill(`${t.segmentos_resolvidos || 0}/${t.segmentos_total || 0} clipes na timeline`) +
    // ⭐ O banco só aparece quando ATUOU. Uma pílula "0 do banco" em todo relink seria
    // ruído permanente para informar um não-evento.
    ((t.do_banco) ? pill(`${t.do_banco} do banco`, "ok") : "");

  const r = await api("/trabalho/masters" + (filtro === "revisao" ? "?revisao=1" : ""));
  const itens = r.masters || [];
  el("listaMasters").innerHTML = itens.length
    ? itens.map(desenharMaster).join("")
    : '<div class="vazio">nada a decidir aqui</div>';

  // ⚠️⚠️ O RISCO DO ATALHO: um relink parcial que pareça completo. Sem pasta apontada, o
  // que o banco não conhecia volta como "sem mídia" — e o editor pode aplicar assim,
  // deixando a maior parte da timeline offline sem perceber. O placar já mostra o número
  // em vermelho; o que faltava era dizer o MOTIVO e a correção, que aqui é uma só.
  if (!pastas.length && (t.nao_resolvidos || 0) > 0) {
    dizer(`${t.nao_resolvidos} master(s) não estão no banco. Aponte a pasta de mídia no `
          + "bloco 2 e prepare de novo — ou siga assim e relinke só o resto.", false);
  }

  // ⭐ JANELA PRÓPRIA QUE ABRE QUANDO HÁ CONFLITO (autor, 2026-11-22): empate a decidir → a vista larga se abre
  // sozinha, uma vez por preparação (fechada pelo editor, não volta a se abrir até a próxima).
  if ((t.ambiguos || 0) > 0 && !VISTA_REVISAO && !revisaoNaJanela && !conflitoJaAberto) {
    conflitoJaAberto = true;
    abrirJanelaRevisao(el("btnJanelaRevisao"), () => {}).catch(() => {});
  }

  const decididos = t.decididos || 0;
  const b = el("btnAplicar");
  if (NLE === "resolve") {
    // No Resolve importar SEMPRE pode: o que não casou entra como hoje (mídia do Avid ou
    // offline). O número diz quantos originais vão junto.
    b.disabled = false;
    b.textContent = decididos ? `Importar no Resolve · ${decididos} nos originais`
                              : "Importar no Resolve · sem originais";
  } else {
    b.disabled = !decididos;
    b.textContent = decididos
      ? `Relinkar ${decididos} no Media Composer`
      : "Nada decidido ainda";
  }

  /* O resumo que substitui a lista no painel estreito.

     ⭐ "Divergência" é o que o editor ainda não confirmou: sugestão por semelhança,
     empate entre candidatos, e master sem arquivo. O que casou com segurança não é
     divergência — mas continua revisável na janela larga, porque é lá que mora o falso
     positivo. */
  const divergencias =
    (t.sugeridos || 0) + (t.ambiguos || 0) + (t.nao_resolvidos || 0);
  const prontos = t.resolvidos || 0;

  el("resumoRevisao").textContent = divergencias
    ? `${divergencias} ${divergencias > 1 ? "divergências encontradas" : "divergência encontrada"}.`
    : "Nenhuma divergência: todos os clipes casaram.";

  /* ⚠️ A nota muda de conteúdo conforme o caso, e isso não é enfeite: com divergência ela
     precisa dizer que dá para seguir SEM resolver (senão o botão em destaque parece um
     portão); sem divergência ela precisa dizer que revisar ainda vale (senão "está tudo
     certo" convida a pular justamente a conferência do falso positivo). */
  el("notaRevisao").textContent = divergencias
    ? (NLE === "resolve"
      ? `A revisão é opcional — você pode importar com os ${prontos} que casaram com segurança; o resto entra como hoje.`
      : `A revisão é opcional — você pode relinkar só os ${prontos} que casaram com segurança.`)
    : "A revisão é opcional, mas é onde um casamento errado apareceria antes do relink.";

  /* O atalho para a janela larga fica SEMPRE disponível — só não dentro dela mesma.

     ⚠️ Ele já foi condicionado a "três ou mais pendências", e isso estava errado por dois
     motivos independentes. O primeiro foi medido na tela em 2026-08-17: a conta somava só
     `sugeridos + ambiguos`, e um relink real deu "1 sugerido · 1 ambíguo · 20 sem mídia" —
     2 pela conta antiga, abaixo do corte, com 22 itens na lista.

     ⭐ O segundo é de produto, e é maior: a janela não serve só para RESOLVER pendência,
     serve para CONFERIR. Um casamento confiante e errado — o falso positivo — é o defeito
     que ninguém vai procurar, porque não se anuncia: a lista diz "pronto", o relink roda,
     e o erro só aparece na tela do editor depois. Esconder a conferência justamente
     quando está tudo verde é esconder a revisão do único caso em que ela é a última
     defesa. Revisar é opcional; a oportunidade de revisar, não. */
  el("conviteRevisao").hidden = VISTA_REVISAO || !!revisaoNaJanela;
}

function desenharMaster(m) {
  const classe = m.arquivo ? "resolvido" : (m.sugestao ? "sugerido" : "aberto");
  const tipo = m.e_audio ? "som" : "img";
  let alvo = "";
  if (m.arquivo) alvo = `<div class="item-alvo">→ ${escapar(nomeDe(m.arquivo))}</div>`;
  else if (m.sugestao) alvo = `<div class="item-alvo">? ${escapar(nomeDe(m.sugestao))}</div>`;

  let acoes = "";
  if (m.sugestao && !m.arquivo) {
    acoes = `<button data-aceitar="${escapar(m.mob_id)}" data-arquivo="${escapar(m.sugestao)}">usar esta</button>`;
  } else if (m.arquivo && m.metodo === "manual") {
    acoes = `<button class="ghost" data-limpar="${escapar(m.mob_id)}">desfazer</button>`;
  }
  // ⭐ A JANELA DE CONFLITO (autor, 2026-11-22): na vista larga, cada candidato com o porquê e o quadro dele ao lado
  // do quadro do daily. No painel estreito ficam os botões de sempre.
  const conflito = (m.candidatos || []).length > 1 && (VISTA_REVISAO || revisaoNaJanela);
  if (m.candidatos && m.candidatos.length > 1 && !conflito) {
    acoes += m.candidatos.slice(0, 4).map((c) =>
      `<button data-aceitar="${escapar(m.mob_id)}" data-arquivo="${escapar(c.path)}">` +
      `${escapar(nomeDe(c.path))}</button>`).join("");
  }

  return `<div class="item ${classe}">
    <div class="item-topo">
      <span class="item-nome">${escapar(m.nome)}</span>
      <span class="item-seg">${tipo} · ${m.segmentos}×</span>
    </div>
    ${alvo}
    ${m.motivo ? `<div class="item-motivo${m.arquivo && !m.precisa_de_revisao ? " motivo-casado" : ""}">${escapar(m.motivo)}</div>` : ""}
    ${conflito ? desenharConflito(m) : ""}
    ${acoes ? `<div class="item-acoes">${acoes}</div>` : ""}
  </div>`;
}

/* O cartão do conflito: o quadro do DAILY (o que está na montagem) à esquerda e, ao lado, cada candidato com o quadro
   do MESMO instante (a ponte pelo original: daily e original começam juntos) e o que bateu e o que não bateu, com o
   número. "Usar este" grava a escolha (a palavra do editor vence qualquer regra). Nenhum candidato é pré-escolhido
   por palpite: o destaque só aparece quando a imagem confirmou (autor, 2026-11-22). */
function desenharConflito(m) {
  const t = m.duracao_s ? (m.duracao_s / 2).toFixed(2) : "0";
  const quadro = (arq) => `/trabalho/quadro?arquivo=${encodeURIComponent(arq)}&t=${t}`;
  const curto = (p) => { const x = String(p || "").split(/[\\/]/); return "…/" + x.slice(-4).join("/"); };
  const chip = (texto, v) => `<span class="prova ${v === true ? "sim" : v === false ? "nao" : "talvez"}">`
    + `${escapar(texto)} ${v === true ? "✓" : v === false ? "✗" : "?"}</span>`;
  const daily = m.daily
    ? `<figure class="conf-daily"><img loading="lazy" alt="" src="${quadro(m.daily)}">`
      + `<figcaption>Daily na montagem<br><bdi>${escapar(curto(m.daily))}</bdi></figcaption></figure>`
    : `<div class="conf-daily vazio">o daily não está nesta máquina: sem imagem para comparar</div>`;
  // o candidato em uso primeiro; os outros na ordem do casador
  const ordem = [...m.candidatos].sort((a, b) => (b.path === m.arquivo) - (a.path === m.arquivo));
  const cands = ordem.map((c) => {
    const p = c.provas || {};
    const dur = c.duration_ms ? `duração ${(c.duration_ms / 1000).toFixed(1).replace(".", ",")} s` : "duração";
    const ras = c.largura && c.altura ? `<span class="prova neutra">${c.largura}×${c.altura}</span>` : "";
    const img = p.imagem != null
      ? `<span class="prova ${p.imagem >= 0.95 ? "sim" : "nao"}">imagem ${String(p.imagem.toFixed(2)).replace(".", ",")}</span>` : "";
    const usado = m.arquivo === c.path;
    return `<figure class="conf-cand${usado ? " usado" : ""}">
      ${m.daily ? `<img loading="lazy" alt="" src="${quadro(c.path)}">` : ""}
      <figcaption><bdi>${escapar(curto(c.path))}</bdi>
        <div class="provas">${chip("nome", true)}${chip(dur, p.duracao)}`
        + `${chip(p.tc_duvida ? "TC a conferir" : "TC" + (c.tc ? " " + c.tc : ""), p.tc_duvida ? null : p.tc)}${ras}${img}</div>
        ${usado ? '<div class="conf-usado">em uso</div>'
          : `<button data-aceitar="${escapar(m.mob_id)}" data-arquivo="${escapar(c.path)}">Usar este</button>`}
      </figcaption></figure>`;
  }).join("");
  return `<div class="conflito">${daily}<div class="conf-cands">${cands}</div></div>`;
}

/* ── Progresso, por SSE ───────────────────────────────────────────────────────
   O evento traz o estado INTEIRO, não um delta: se a conexão cair no meio de uma
   aplicação de 80 s, a próxima reencontra a situação. */
let fonte = null;

function acompanhar() {
  if (fonte) fonte.close();
  fonte = new EventSource("/progresso");
  fonte.onmessage = (ev) => {
    let e; try { e = JSON.parse(ev.data); } catch (_) { return; }
    pintarProgresso(e);
  };
  fonte.onerror = () => { fonte.close(); fonte = null; sincronizar(); };
}

/* O aviso que fica na tela enquanto o trabalho corre.

   ⭐ Por que ele existe, e por que é AVISO e não trava: boa parte do trabalho (áudio,
   achatamento, remap) roda FORA do Media Composer — só o `LinkFile` fala com ele. Nessas
   etapas a interface do Avid fica livre, e nada nela indica que a bin ainda está sendo
   montada. Abri-la no meio é o gesto natural de quem está ansioso.

   ⚠️ E não dá para impedir de verdade: quem manda na janela do Avid é o Avid, e o SDK não
   tem "bloqueie a interface". O que existe é o inverso — um modal do MC trava a API
   INTEIRA —, então tentar prender a interface dele seria trocar um risco por um pior.
   Sobra dizer, com o nome certo, enquanto durar. */
function avisarSobreABin(nome) {
  const alvo = el("avisoTrabalho");
  if (!alvo) return;
  if (!nome) { alvo.hidden = true; return; }
  alvo.innerHTML = "Enquanto isto roda, <strong>não abra nem edite a bin "
    + `<bdi>${escapar(nome)}</bdi></strong> — ela ainda está sendo montada.`;
  alvo.hidden = false;
}

function pintarProgresso(e) {
  if (e.fase === "preparando") conflitoJaAberto = false;
  const pct = e.total ? Math.round(100 * e.feito / e.total) : 0;
  el("progEtapa").textContent = e.etapa || e.fase || "trabalhando";
  el("progBarra").style.width = pct + "%";
  el("progPct").textContent = pct + "%";
  el("progDetalhe").innerHTML = `<bdi>${escapar(e.detalhe || "")}</bdi>`;
  el("progTempo").textContent = e.decorrido ? relogio(e.decorrido) : "";

  // O aviso vale só enquanto o trabalho corre — em qualquer desfecho ele sai, senão
  // continuaria pedindo cuidado com uma bin que já está pronta (ou que nem existe).
  if (e.fase !== "aplicando") avisarSobreABin("");

  if (e.fase === "pronto" && RECEBE && rcCartaAnalise && rcPendente) {
    fecharFonte(); mostrarPasso("passoOrigem"); rcCartaAnalise.casou = true; abrirAntesCarta();
  } else if (e.fase === "pronto") { fecharFonte(); mostrarPasso("passoRevisao"); carregarRevisao(); }
  else if (e.fase === "feito") { fecharFonte(); mostrarFeito(e.resultado || {}); }
  else if (e.fase === "erro") { fecharFonte(); mostrarPasso("passoOrigem"); dizer(e.erro, false); }
  else if (e.fase === "ocioso" && e.etapa === "cancelado") {
    fecharFonte(); mostrarPasso("passoOrigem"); dizer("cancelado", false);
  }
}

function fecharFonte() { if (fonte) { fonte.close(); fonte = null; } }

function relogio(s) {
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m ? `${m}m ${String(r).padStart(2, "0")}s` : `${r}s`;
}

function mostrarFeito(r) {
  // O relink de um envio do Magic Link (bin anexa): o envio desce para "importado" do canal. Acessório — a bin já
  // está no Media Composer; se a rede recusar, a Carta fica na fila e só aparece de novo como novo.
  if (NLE === "mc" && modoOrigem === "bin" && binExterna && binExterna.envio && r.masters_online) {
    const id = binExterna.envio;
    binExterna.envio = null;
    post("/receber/trazido", { id, ok: true, detalhe: `relinkado no Media Composer: ${r.bin || ""}` })
      .then(() => procurarNovos(true)).catch(() => {});
  }
  // ⚠️ `aberta_no_mc: false` = a bin FOI GRAVADA e só não abriu sozinha. Dizer "aberta
  // no Media Composer" nesse caso mandaria o editor procurar na tela uma bin que não
  // está lá, e concluir que o trabalho se perdeu — quando ele está inteiro, em disco.
  // O caminho vai junto para poder ser aberto à mão.
  const abriu = r.aberta_no_mc !== false;
  el("resumoFinal").innerHTML =
    (abriu && r.bin_midias
      ? `<div>pasta <strong>${escapar(r.pasta || "")}</strong>: <strong>${escapar(r.bin || "")}</strong> (a timeline, `
        + `aberta no Media Composer), <strong>${escapar(r.bin_midias)}</strong> (as mídias)`
        + (r.bin_importada ? ` e <strong>${escapar(r.bin_importada)}</strong> (o AAF recebido, como chegou)` : "")
        + `</div>`
        // A API do MC não tem refresh do projeto (banco, avid-panel-sdk/copia-da-timeline.md): a pasta nova só
        // aparece no painel de Bins depois que o editor pede (autor, 2026-10-13: um lembrete na entrega).
        + `<div class="dica">Para ver a pasta nova no painel de Bins: ☰ do painel (ou botão direito) ▸ Refresh</div>`
      : abriu
      ? `<div><strong>${escapar(r.bin || "")}</strong> aberta no Media Composer</div>`
      : `<div><strong>${escapar(r.bin || "")}</strong> foi gravada, mas não abriu ` +
        `sozinha — abra por File ▸ Open Bin:</div>` +
        `<div class="caminho">${escapar(r.avb || "")}</div>`) +
    `<div class="dica">${r.masters_online || 0} de ${r.masters_pedidos || 0} mídias online · ` +
    `${r.segmentos_cobertos || 0} clipes na timeline` +
    // o que o projeto já tinha linkado entra sem novo link (autor, 2026-10-13: o LinkFile repetido é ~10× mais lento)
    (r.video_reaproveitado > 1 ? ` · ${r.video_reaproveitado} vídeos já estavam no projeto (reaproveitados)`
      : r.video_reaproveitado ? ` · 1 vídeo já estava no projeto (reaproveitado)` : "") +
    (r.subclipes_achatados ? ` · ${r.subclipes_achatados} subclipes desfeitos` : "") +
    (r.group_clips_achatados ? ` · ${r.group_clips_achatados} group clips desfeitos` : "") +
    `</div>` +
    // B009 do banco: plano cujo master não chegou à bin vira vazio na timeline — contado, nunca calado
    ((r.sequencia || {}).leaks_filled ? `<div class="dica aviso-leve">⚠ ${r.sequencia.leaks_filled} plano(s) sem master `
      + `na bin ficaram VAZIOS na timeline — confira os buracos antes de editar</div>` : "") +
    // B009: efeito do Premiere que o Avid não recebe — com o nome e a conta, nunca calado
    (Object.keys(r.efeitos_fora || {}).length ? `<div class="dica aviso-leve">⚠ não foram para o Avid: `
      + Object.entries(r.efeitos_fora).map(([n, q]) => `${escapar(n)} (${Number(q) || 0})`).join(" · ")
      + ` — refaça no Media Composer se precisar</div>` : "") +
    // B109: a escala digitada para outra mídia vai como está (nunca ajustada calada) — o editor confere
    (((r.de_outra_midia || {}).escala || 0) + ((r.de_outra_midia || {}).proporcao || 0)
      ? `<div class="dica aviso-leve">⚠ confira o enquadramento: `
        + [r.de_outra_midia.escala ? `${Number(r.de_outra_midia.escala)} plano(s) com escala que parece digitada para outra mídia` : "",
           r.de_outra_midia.proporcao ? `${Number(r.de_outra_midia.proporcao)} plano(s) com arquivo de outra proporção que a do projeto` : ""]
          .filter(Boolean).join(" · ") + `</div>` : "") +
    (r.no_record ? `<div class="dica">a timeline está no Record</div>` : "") +
    // MC 2024: a API não alcança o Record (autor, 2026-10-18) — a timeline fica no Source, com a imagem à vista
    (r.no_source ? `<div class="dica">no Media Composer 2024 a timeline abre no Source: dê duplo clique na sequência
       da bin “${escapar(r.bin || "")}” para editá-la no Record</div>` : "") +
    `<div id="foraDoRelink"></div>`;
  pintarForaDoRelink(r);
  mostrarPasso("passoFeito");
  dizer("");
  // ⚠️ O relink que acabou é EXATAMENTE o que muda o tamanho do banco — ele acabou de
  // aprender. Sem reler aqui, o bloco 3 seguia dizendo "ainda vazio" com o mapa já
  // gravado no disco: a tela desmentindo o próprio trabalho que ela reportou.
  carregarBanco();
}

/* O que ficou DE FORA do relink, numa lista como a de mídias (autor, 2026-10-13: "2 arquivo(s) não puderam ser
   abertos" sem dizer quais não serve): o que o MC recusou, o áudio que não pôde ser injetado e o que nem foi achado
   nas pastas. Nome · motivo; o caminho inteiro no `title`. */
function motivoDaFalha(erro) {
  const e = String(erro || "");
  // ⭐ Texto do autor (2026-10-18): RAW de câmera sem o plugin do fabricante (os 43 BRAW do PRODUCAO-A no MC 24.6).
  if (/falta o plugin AMA/i.test(e)) return "o Media Composer não tem o AMA adequado para essa mídia";
  if (/acento ou cedilha/i.test(e)) return "caminho com acento ou cedilha: esta versão do Media Composer não linka";
  if (/cannot be linked/i.test(e)) return "o Media Composer não tem o AMA adequado para essa mídia";
  if (/não respondeu no prazo/i.test(e)) return "o Media Composer não respondeu";
  const m = e.match(/"ErrorMessage":\s*"([^"]+)"/);
  return (m ? m[1] : e).slice(0, 140);
}
/* A tabela de "Ficaram de fora" (organograma de 2026-10-13): Nome · Motivo · De onde veio (o caminho do AAF/da bin, se
   houver), o mesmo componente da lista, com o Relink manual no pé. Uma escolha manual aqui não mexe na entrega que já
   está no MC (ele guarda as bins abertas na memória): "Relinkar de novo" faz uma entrega NOVA com as escolhas,
   reaproveitando o que o projeto já linkou (≈ 1 min no PRODUCAO-A). A mídia IGNORADA não entra: foi escolha, não falha. */
let tabelaFora = null;
let foraEscolhas = 0;

function tabelaDoFora() {
  if (tabelaFora) return tabelaFora;
  tabelaFora = criarTabela({
    tabela: el("foraTabela"), caixa: el("foraCaixa"), chave: "mc.fora",
    // Codec (autor, 2026-10-18): o formato diz ao editor o que precisa ir atrás (.BRAW → o AMA da Blackmagic).
    colunas: [{ id: "nome", titulo: "Nome", largura: 190 }, { id: "codec", titulo: "Codec", largura: 80 },
              { id: "motivo", titulo: "Motivo", largura: 250 }, { id: "origem", titulo: "De onde veio", largura: 280 }],
    celula: (x, id) => id === "origem" ? `<span class="mono"><bdi>${escapar(x.origem || "—")}</bdi></span>`
      : `<bdi>${escapar(x[id] || (id === "codec" ? "—" : ""))}</bdi>`,
    titulo: (x, id) => id === "nome" ? (x.caminho || x.nome) : x[id] || "",
    aoMudar: () => {
      const sel = tabelaFora.selecionadas();
      el("foraManual").disabled = sel.length !== 1 || !sel[0].mob;
      el("foraManual").title = sel.length !== 1 ? "marque UMA linha" : !sel[0].mob ? "esta linha não aponta uma mídia da timeline" : "";
      el("foraRelinkar").hidden = !foraEscolhas;
      el("foraRelinkar").textContent = `Relinkar de novo com ${foraEscolhas === 1 ? "a escolha" : `as ${foraEscolhas} escolhas`}`;
    },
  });
  return tabelaFora;
}

async function pintarForaDoRelink(r) {
  let masters = [];
  try { masters = (await api("/trabalho/masters")).masters || []; } catch (_) { /* acessório: as falhas já estão em `r` */ }
  const porArquivo = {};
  for (const m of masters) if (m.arquivo) porArquivo[m.arquivo] = m;
  const linhas = [];
  const juntar = (m, caminho, motivo, s) => linhas.push({
    k: m ? m.mob_id : `x:${linhas.length}`, s: s || "bad", nome: m ? m.nome : nomeDoCaminho(caminho), caminho: caminho || "",
    motivo, origem: m ? m.origem || "" : "", mob: m ? m.mob_id : "",
    codec: extDoCaminho(caminho || (m && m.sugestao) || "") });
  for (const f of r.falhas || []) juntar(porArquivo[f.arquivo], f.arquivo, motivoDaFalha(f.erro));
  const doArquivo = (n) => masters.find((m) => m.arquivo && String(n).indexOf(nomeDoCaminho(m.arquivo)) === 0);
  for (const n of r.audio_sem_template || []) juntar(doArquivo(n), String(n).split(" ")[0], "áudio num formato que ainda não injeto");
  for (const n of r.audio_curto_demais || []) {
    const c = Array.isArray(n) ? n[0] : n;
    juntar(doArquivo(c), c, "áudio mais curto que o trecho usado na timeline");
  }
  for (const x of masters) {
    if (x.arquivo || x.ignorado) continue;
    const empate = x.sugestao || (x.candidatos || []).length > 1;
    if (!empate && x.ja_online) {
      juntar(x, "", `não casou, mas está ${ONDE_ONLINE[x.ja_online] || "online"}: ficou como estava`, "onl");
      continue;
    }
    juntar(x, "", empate ? "mais de um original possível (empate): ficou como estava"
                         : "não encontrado nas pastas: ficou como estava");
  }
  const alvo = el("foraDoRelink");
  if (!alvo || !linhas.length) return;
  alvo.innerHTML = `<div class="mc-lista fora">
      <div class="mc-lista-topo"><p class="bloco-titulo">ficaram de fora</p><span class="midias-conta">${linhas.length} ${linhas.length === 1 ? "mídia" : "mídias"}</span></div>
      <div class="tab-caixa" id="foraCaixa" tabindex="0" aria-label="Ficaram de fora"><table class="tab-midias" id="foraTabela"></table></div>
      <p class="mc-manual" id="foraMsg" hidden></p>
      <div class="mc-lista-acoes"><button type="button" class="sm" id="foraManual" disabled>Relink manual</button>
        <button type="button" class="sm" id="foraRelinkar" hidden>Relinkar de novo</button></div>
    </div>`;
  tabelaFora = null;
  foraEscolhas = 0;
  const t = tabelaDoFora();
  t.linhas = linhas;
  t.pintar();
  el("foraManual").onclick = async () => {
    const sel = t.selecionadas();
    if (sel.length !== 1 || !sel[0].mob) return;
    const msg = (texto, ok, titulo) => {
      const p = el("foraMsg");
      p.innerHTML = (titulo ? `<strong><bdi>${escapar(titulo)}</bdi></strong><br>` : "") + escapar(texto || "");
      p.className = "mc-manual " + (ok ? "aceito" : "recusado");
      p.hidden = !texto;
    };
    let arquivo = "";
    try { arquivo = (await post("/escolher/midia", { nome: sel[0].nome })).caminho; } catch (e) { msg(e.message, false); return; }
    if (!arquivo) return;
    const titulo = `${sel[0].nome} → ${nomeDoCaminho(arquivo)}`;
    try {
      const res = await post("/trabalho/manual", { mob_id: sel[0].mob, arquivo });
      sel[0].s = "man";
      sel[0].motivo = `manual: ${nomeDoCaminho(arquivo)} (entra no “Relinkar de novo”)`;
      foraEscolhas = t.linhas.filter((x) => x.s === "man").length;
      msg(`manual · ${res.texto || "aceito"}`, true, titulo);
      t.pintar();
    } catch (e) {
      msg(e.corpo && e.corpo.recusa ? e.corpo.recusa : e.message, false, e.corpo && e.corpo.recusa ? `${titulo}: não dá` : titulo);
    }
  };
  el("foraRelinkar").onclick = async () => {
    try {
      const res = await post("/trabalho/aplicar", { nome_bin: el("nomeBin").value.trim() });
      avisarSobreABin(res && res.bin);
      mostrarPasso("passoProgresso");
      acompanhar();
    } catch (e) { dizer(e.message, false); }
  };
}

/* Ao abrir (ou reabrir) o painel, reencontra o que estiver rodando. */
async function sincronizar() {
  try {
    const e = await api("/trabalho");
    if (e.ocupada) { mostrarPasso("passoProgresso"); pintarProgresso(e); acompanhar(); }
    else if (e.fase === "pronto" && !e.previa) { mostrarPasso("passoRevisao"); carregarRevisao(); }
    else if (e.fase === "feito") mostrarFeito(e.resultado || {});
    else mostrarPasso("passoOrigem");
  } catch (_) { mostrarPasso("passoOrigem"); }
}

/* ── O registro do que chegou ao Resolve (`/receber/trazido`) ─────────────────────────────
   ⚠️ MEDIDO 2026-09-28: o serviço caiu no meio de um Atualizar; o Resolve terminou, mas o
   registro falhou em silêncio. A Carta nova continuou em "Novos" e a partida seguiu apontando a
   timeline que tinha ido para o Backup — a próxima atualização partiria DELA. Agora o registro
   que falha fica guardado neste painel e é reenviado, na ordem, quando o serviço volta. */
const CHAVE_REGISTROS = "dlpc.registrosPendentes";

function registrosPendentes() {
  try { return JSON.parse(localStorage.getItem(CHAVE_REGISTROS) || "[]") || []; } catch (_) { return []; }
}

function guardarPendentes(lista) {
  try {
    if (lista.length) localStorage.setItem(CHAVE_REGISTROS, JSON.stringify(lista));
    else localStorage.removeItem(CHAVE_REGISTROS);
  } catch (_) { /* sem storage: o aviso na tela já disse o que fazer */ }
}

/* `rota`: o `/receber/trazido` do Importar ou o `/receber/atualizada` do Atualizar. Devolve:
   - a resposta do serviço;
   - `null` se o serviço NÃO RESPONDEU (fora do ar): o registro fica pendente e é reenviado;
   - `{recusado: motivo}` se o serviço respondeu com erro. ⚠️ Esse NÃO fica pendente: um pedido
     recusado é recusado de novo a cada reenvio, e a fila travava todo Atualizar seguinte (revisão
     2026-09-28). */
async function registrar(rota, corpo) {
  try { return await post(rota, corpo); } catch (e) {
    if (e && e.status) {
      console.warn("[registro] recusado:", e.message);
      return { recusado: e.message };
    }
    console.warn("[registro] ficou pendente:", e && e.message);
    guardarPendentes(registrosPendentes().concat([{ rota, corpo }]));
    return null;
  }
}

const registrarTrazido = (corpo) => registrar("/receber/trazido", corpo);

async function reenviarPendentes() {
  const lista = registrosPendentes();
  while (lista.length) {
    // os guardados antes de 2026-09-28 (noite) eram só o corpo do `/receber/trazido`
    const item = lista[0] && lista[0].rota ? lista[0] : { rota: "/receber/trazido", corpo: lista[0] };
    try { await post(item.rota, item.corpo); } catch (e) {
      if (!(e && e.status)) break;            // ainda fora do ar: tenta na próxima volta
      console.warn("[registro] pendente recusado, descartado:", e.message);
    }
    lista.shift();
  }
  guardarPendentes(lista);
}

const avisoRecusado = (motivo) => `A timeline entrou, mas esta máquina não anotou de onde ela veio (${motivo}). `
  + "Na próxima atualização dela, escolha a versão antiga com Escolher….";

const AVISO_PENDENTE = "O serviço do De Lá Pra Cá caiu antes de anotar esta timeline. O registro "
  + "fica guardado e é gravado quando ele voltar (o painel religa em alguns segundos). Até lá, "
  + "não atualize de novo.";

/* ── Estado do serviço ────────────────────────────────────────────────────── */
let servicoOk = false;

/* ── Prontidão (autor, 2026-10-04) ────────────────────────────────────────────
   As opções só aparecem com o motor PRONTO (`/prontidao`: ffprobe e ffmpeg RODAM, a pasta grava),
   não só no ar — o Importar inteiro do PRODUCAO_B foi feito com o motor sem ffprobe, e a timeline
   saiu toda offline no fim. Sem motor: "abra o De Lá Pra Cá"; conecta sozinha quando ele abre (a
   batida de 4 s), qualquer que seja a ordem (memória `app-obrigatorio-ordem-nao-importa`). */
let falhasSeguidas = 0;
function bloquear(sim) { document.body.classList.toggle("sem-motor", !!sim); }

function pintarForaDoAr() {
  // No Resolve, a MESMA tela de espera de quando o plugin abre sem o app (autor, 2026-10-04): a casca
  // troca a janela por ela e volta ao painel sozinha quando o motor responder.
  if (ponte() && typeof ponte().esperarMotor === "function") {
    ponte().esperarMotor().catch(() => { /* sem casca nova: fica o aviso abaixo */ });
  }
  bloquear(true);
  el("prTitulo").textContent = "serviço não encontrado";
  el("prTexto").textContent = "Abra o aplicativo De Lá Pra Cá. Esta tela conecta sozinha quando ele abrir"
    + " — não precisa fechar nada.";
  el("prItens").innerHTML = "";
  el("prAbrirApp").hidden = !(ponte() && typeof ponte().abrirApp === "function");
}

function pintarProntidao(pr) {
  // As Configurações do app ficam de pé mesmo com o motor "não pronto": a pasta do cache é
  // justamente uma das coisas que se conserta lá.
  if ((pr && pr.ok) || VISTA_CONFIG || VISTA_AJUSTES) { bloquear(false); return; }
  bloquear(true);
  el("prTitulo").textContent = "o motor do De Lá Pra Cá não está pronto";
  el("prTexto").textContent = "Antes de trabalhar, isto precisa estar resolvido — senão a timeline "
    + "sairia errada (ou offline) só no fim.";
  el("prItens").innerHTML = ((pr && pr.itens) || []).map((i) =>
    `<div class="pr-item ${i.ok ? "ok" : "err"}"><span class="marca-pr">${i.ok ? "✓" : "✗"}</span>` +
    `<span>${escapar(i.nome)}${i.ok ? "" : `: ${escapar(i.erro || "falhou")}` +
      (i.gesto ? `<span class="gesto">${escapar(i.gesto)}</span>` : "")}</span></div>`).join("");
  // motor sem app (o órfão de uma casca antiga): o gesto é abrir o app, que assume a porta sozinho
  const semApp = ((pr && pr.itens) || []).some((i) => i.id === "aplicativo" && !i.ok);
  el("prAbrirApp").hidden = !(semApp && ponte() && typeof ponte().abrirApp === "function");
}

async function conferirProntidao(forcar) {
  try {
    const pr = await api("/prontidao" + (forcar ? "?forcar=1" : ""));
    if (!(pr && pr.ok) && rcOcupado) return;       // no meio de um trabalho: avisa depois, não esconde
    pintarProntidao(pr);
  }
  catch (e) { console.warn("[prontidão]", e && e.message); }
}
el("prConferir").onclick = () => (servicoOk ? conferirProntidao(true) : baterNoServico());
el("prAbrirApp").onclick = async () => {
  try {
    const r = await ponte().abrirApp();
    el("prTexto").textContent = r && r.ok ? "Abrindo o aplicativo… esta tela conecta sozinha em seguida."
      : (r && r.erro) || "não consegui abrir o aplicativo: abra pelo Finder/Iniciar";
  } catch (e) { el("prTexto").textContent = e.message; }
};
bloquear(true);

/* ⭐ Na janela do APP o painel segue o programa CONECTADO (organograma do app unificado, 2026-10-18): o topo diz qual
   e o PROJETO em foco (destaque discreto — o Premiere e o Resolve com a troca dinâmica abrem vários), e o modo do painel
   (`nle`) vira o dele. A troca recarrega a página, então NUNCA no meio de um trabalho: espera a próxima batida. */
async function seguirConexao() {
  let c;
  try { c = await api("/conexao"); } catch (_) { return; }
  const NOMES = { mc: "Media Composer", resolve: "DaVinci Resolve", premiere: "Premiere Pro", baselight: "Baselight" };
  if (!c || !NOMES[c.programa]) {
    el("conn").className = "conn";
    el("connTexto").textContent = "nenhum programa conectado";
    return;
  }
  el("connTexto").innerHTML = `${escapar(NOMES[c.programa])} ${escapar(c.versao || "")}`.trim() +
    (c.projeto ? ` · <span class="conn-projeto">${escapar(c.projeto)}</span>` : "");
  // O programa ABERTO mas sem atender (o Resolve que abriu sem o servidor de scripts, 2026-10-23): bolinha amarela e o
  // gesto que resolve, em vez do verde de antes; o motivo inteiro no title. Some sozinho na batida em que ele atende.
  el("connTexto").title = c.erro || "";
  el("conn").className = "conn ok";
  // O MC ABERTO mas sem responder (um diálogo modal nele, ou abrindo um projeto — 2026-10-24): continua o MC, amarelo
  if (c.ocupado && !c.erro) {
    el("conn").className = "conn warn";
    el("connTexto").insertAdjacentHTML("beforeend", ` · <span class="conn-erro">ocupado — há um diálogo aberto nele?</span>`);
  }
  if (c.erro) {
    el("conn").className = "conn warn";
    el("connTexto").insertAdjacentHTML("beforeend", ` · <span class="conn-erro">${escapar(c.programa === "resolve"
      ? "sem conexão: feche e abra o Resolve" : c.erro)}</span>`);
  }
  const ocupado = (typeof rcOcupado !== "undefined" && rcOcupado) ||
    (el("passoProgresso") && !el("passoProgresso").hidden);
  if (c.tambem) el("connTexto").insertAdjacentHTML("beforeend", ` <span class="conn-tambem">· também: ${escapar(c.tambem)}</span>`);
  if (c.programa !== NLE && !ocupado) {
    const u = new URL(location.href);
    u.searchParams.set("nle", c.programa);
    location.replace(u.toString());
  }
}

async function baterNoServico() {
  try {
    // Fora do Media Composer o serviço roda como RECEPTOR e se desliga depois de 30 min sem
    // uso de `/receber/*` — então é por lá que o painel diz "estou aberto".
    const s = await api(NLE === "mc" ? "/health" : `/receber/estado?nle=${NLE}`);
    const voltou = !servicoOk;
    servicoOk = true;
    el("versao").textContent = "v" + s.versao;
    // Na janela do app o texto é o da `/conexao` (programa · projeto): reescrever "conectado" a cada batida o fazia
    // PISCAR entre os dois (autor, 2026-10-18). Lá, só a `/conexao` escreve — o texto E a cor (o amarelo do "ocupado").
    const naJanelaDoApp = new URLSearchParams(location.search).get("casca") === "app";
    if (!naJanelaDoApp || voltou) el("conn").className = "conn ok";
    if (!naJanelaDoApp || voltou) el("connTexto").textContent = "conectado";
    falhasSeguidas = 0;
    // ⭐ Na JANELA DE CONFIGURAÇÕES a conexão não segura a tela (autor, 2026-11-07: "fica procurando o De Lá Pra Cá
    //    por algum tempo antes de mostrar as opções"). O `/conexao` pergunta ao MC programa e projeto — MEDIDO ~2 s com
    //    ele aberto, até 3 s ocupado —, e a seção é recarregada a cada clique na aba. Os ajustes não dependem do NLE para
    //    aparecer: a conexão é conferida em paralelo (e, se o NLE for outro, a página troca como sempre).
    // …e só UMA vez, ao abrir: a seção fica viva escondida, e a batida de 4 s perguntaria ao MC duas vezes por batida
    if (naJanelaDoApp && VISTA_AJUSTES) { if (voltou) seguirConexao(); }
    else if (naJanelaDoApp) await seguirConexao();
    // a cada batida (o serviço guarda o resultado 60 s): um motor que perde o ffprobe no meio volta a
    // bloquear; um que ganha, libera
    await conferirProntidao(false);
    if (voltou && NLE !== "mc") { await reenviarPendentes(); procurarNovos(true); }
    if (voltou && NLE === "mc" && !VISTA_AJUSTES) {
      sincronizar();
      // ⚠️ Relido na RECONEXÃO, e não só no boot: o editor pode ter trocado de projeto
      // com o painel aberto, e o banco do projeto anterior não vale para este.
      carregarBanco();
      if (modoOrigem === "mc") { verificarPreset(); }
    }
  } catch (e) {
    console.warn("[serviço] a batida falhou:", e && e.message);
    servicoOk = false;
    el("conn").className = "conn err";
    el("connTexto").textContent = "serviço fora do ar";
    // ⚠️ Duas batidas seguidas, e nunca no meio de um trabalho: um serviço ocupado pode perder UMA
    // batida, e esconder a tela de andamento no meio de uma importação seria pior que o aviso.
    // A casca do Resolve NÃO sobe mais o motor (memória `app-obrigatorio-ordem-nao-importa`): quem
    // sobe é o app, como no Media Composer e no Premiere.
    falhasSeguidas += 1;
    if (falhasSeguidas >= 2 && !rcOcupado) pintarForaDoAr();
  }
}

/* ── Ajustes ──────────────────────────────────────────────────────────────── */
function carregarAjustes() {
  el("ajServico").textContent = location.origin;
  carregarCanais();
  carregarCache();
  if (NLE === "resolve") { consultarResolve(); carregarCodigoDeCores(); }
}

async function consultarResolve() {
  const alvo = el("dvEstado");
  if (!ponte()) { alvo.textContent = "aberto fora do Resolve"; return; }
  try {
    const r = await ponte().projeto();
    alvo.innerHTML = [`DaVinci Resolve ${escapar(r.versao || "")}`.trim(),
      r.projeto ? `Projeto: ${escapar(r.projeto)}` : "sem projeto aberto"].join("<br>");
  } catch (e) { alvo.textContent = "—"; dizer(e.message, false); }
}

async function consultarMC() {
  const alvo = el("mcEstado");
  alvo.textContent = "consultando…";
  try {
    const r = await api("/mc/info");
    if (!r.aberto) { alvo.textContent = "Media Composer não respondeu. Ele está aberto?"; return; }
    const app = r.app || {}, proj = r.projeto || {};
    alvo.innerHTML = [
      `${escapar(app.name || "Media Composer")} ${escapar(app.version || "")}`.trim(),
      proj.name ? `Projeto: ${escapar(proj.name)}` : "",
      proj.path ? `<span class="caminho"><bdi>${escapar(proj.path)}</bdi></span>` : "",
    ].filter(Boolean).join("<br>");
  } catch (e) { alvo.textContent = "—"; dizer(e.message, false); }
}

/* ── Ligações ─────────────────────────────────────────────────────────────── */
el("tabDeLaPraCa").onclick = () => irPara("deLaPraCa");
el("tabDaquiPraLa").onclick = () => irPara("daquiPraLa");
el("tabAjustes").onclick = () => irPara("ajustes");
el("btnConsultar").onclick = consultarMC;

el("modoOrigem").onclick = (ev) => {
  const b = ev.target.closest("button[data-modo]");
  if (b && !b.disabled) irParaModo(b.dataset.modo);
};

el("btnInstalarPreset").onclick = async () => {
  dizer("");
  try {
    const r = await post("/mc/preset/instalar");
    dizer(`preset ${r.acao} — cópia de segurança guardada`, true);
    verificarPreset();
  } catch (e) { dizer(e.message, false); }
};
el("btnEscolherPasta").onclick = () => escolherNativo("/escolher/pasta", addPasta);

/* ── Banco de mídias ──────────────────────────────────────────────────────────
   Dois estados e nada entre eles: sem banco (criar/conectar) ou com banco (o nome e um
   ✕). ⭐ Conectar É a opção — não há interruptor separado, que criaria o estado sem
   sentido de "ligado, mas sem banco".

   ⚠️ O estado NÃO mora aqui. Ele vem da pasta do projeto aberto no Media Composer, e é
   por isso que trocar de projeto desconecta sozinho. Guardar no `localStorage` faria o
   painel afirmar "conectado" depois de o editor abrir outro projeto — mentira que só
   apareceria no resultado do relink. Ver `banco.py`. */
/* Se há banco conectado, a pasta de mídia deixa de ser obrigatória — ver `preparar`. */
let bancoConectado = false;

function pintarBanco(e) {
  const ligado = !!(e && e.conectado);
  bancoConectado = ligado;
  el("bancoDesligado").hidden = ligado;
  el("bancoLigado").hidden = !ligado;
  // ⛔ O "(opcional)" saiu junto com a dispensa da pasta — anunciar um atalho que não
  // existe mais seria pior que não ter anunciado nunca.
  el("pastasOpcional").hidden = true;
  if (ligado) {
    el("bancoNome").textContent = e.nome || "";
    // O resumo é o que torna o banco crível: dizer quanto ele já sabe.
    const n = e.casamentos || 0;
    el("bancoResumo").textContent = n
      ? `${n} mídia(s) já confirmada(s) — os próximos relinks usam isto`
      : "ainda vazio — o primeiro relink o alimenta";
  }
  const aviso = el("bancoAviso");
  aviso.textContent = (e && e.aviso) || "";
  aviso.hidden = !aviso.textContent;
}

async function acaoDoBanco(rota) {
  dizer("");
  try {
    pintarBanco(await post(rota));
  } catch (err) { dizer(err.message, false); }
}

/* Lê o estado do projeto ABERTO agora. ⚠️ Custa uma chamada ao Media Composer (~500 ms),
   então roda no boot e na reconexão — nunca na sondagem de 4 s, que é o caminho por onde
   um custo pequeno vira lentidão permanente. Falhar aqui é silencioso de propósito: sem
   o MC no ar não há projeto, e "sem banco" já é a resposta certa. */
async function carregarBanco() {
  try {
    pintarBanco(await api("/banco"));
  } catch (_) {
    pintarBanco({ conectado: false });
  }
}

el("btnCriarBanco").onclick = () => acaoDoBanco("/banco/criar");
el("btnConectarBanco").onclick = () => acaoDoBanco("/banco/conectar");
el("btnDesconectarBanco").onclick = () => acaoDoBanco("/banco/desconectar");
/* ⛔ Havia aqui um `campoPasta` (colar caminho + Enter). Saiu junto com o campo no HTML,
   onde está registrado por que ele nunca deveria ter existido. */

el("btnEscolherAaf").onclick = () =>
  escolherNativo("/escolher/timeline", (c) => {
    if (/\.prproj$/i.test(c)) { carregarBinExterna(c, "prproj"); return; }   // o mesmo caminho do soltar
    if (/\.avb$/i.test(c)) { carregarBinExterna(c); return; }
    binExterna = null;
    el("campoAaf").value = c; irParaModo("aaf"); mostrarEscolhidoMC(); dizer("");
  });
el("btnAlvoEscolher").onclick = () => el("btnEscolherAaf").onclick();
el("btnSeqAberta").onclick = carregarSequenciaAberta;
el("btnSelecaoTL").onclick = carregarSelecaoDaTimeline;
el("listaPastas").onclick = (ev) => {
  const b = ev.target.closest("button[data-i]");
  if (!b) return;
  pastas.splice(Number(b.dataset.i), 1);
  gravarPastas(); renderPastas();
};

el("btnPreparar").onclick = preparar;
el("btnVoltar").onclick = () => { mostrarPasso("passoOrigem"); dizer(""); };
/* "Voltar" (autor, 2026-10-13): a tela principal SEM timeline no bloco 1 e com as pastas mantidas; a leitura anterior
   não vale para a próxima timeline. */
el("btnNovo").onclick = () => {
  mostrarPasso("passoOrigem");
  dizer("");
  arrastada = null;
  binExterna = null;
  el("campoAaf").value = "";
  if (modoOrigem === "aaf" || modoOrigem === "bin") irParaModo("mc");
  previaMC = { chave: "", estado: "", masters: [] };
  el("mcManualMsg").hidden = true;
  mostrarEscolhidoMC();
  dizerNoArrasto("");
};
el("btnCancelar").onclick = () => post("/trabalho/cancelar").catch(() => {});

/* Pede ao APLICATIVO a janela larga de revisão. Quem a hospeda é ele, não o manifesto do
   painel — ver a justificativa em `rotas.app_revisao`.

   ⚠️ O botão nunca "falha": sem aplicativo, a revisão continua aqui mesmo, e o que muda é
   só o aviso. Este passo é onde o editor conclui um trabalho que já custou minutos; ele
   não pode virar um beco porque uma janela acessória não existe nesta instalação. */
/* O caminho de volta, e ele é o simétrico da ida: a página pede ao serviço, o serviço
   reinvoca o app, o `single_instance` entrega à instância viva. Nenhum protocolo novo.

   ⭐ Não há "enviar as aprovações": cada decisão já foi gravada no serviço no instante do
   clique, e o painel dentro do Media Composer relê o estado sozinho. Um botão "salvar"
   aqui seria mentira — sugeriria que fechar a janela sem clicar perderia o trabalho. */
el("btnConcluirRevisao").onclick = async () => {
  if (revisaoNaJanela) { await sairRevisaoNaJanela(); return; }
  const b = el("btnConcluirRevisao");
  b.disabled = true;
  b.textContent = "fechando…";
  try {
    // No Resolve, a janela larga é da casca (`dlpc:revisao`), não do aplicativo.
    if (NLE === "resolve" && ponte() && ponte().fecharJanela) await ponte().fecharJanela();
    else await post("/app/revisao/fechar");
  } catch (e) {
    // A janela não fechou: dizer, e devolver o botão. Nunca deixar o editor num botão
    // morto achando que o programa travou.
    b.disabled = false;
    b.textContent = "Concluir revisão";
    dizer("não consegui fechar a janela — pode fechá-la no X.", "err");
  }
};

/* `avisar(texto)`: onde dizer que a janela não abriu ("" = abriu). O botão volta ao fim, abrindo ou não. */
async function abrirJanelaRevisao(b, avisar) {
  if (CASCA_APP) { await entrarRevisaoNaJanela(); avisar(""); return; }
  b.disabled = true;
  try {
    // No Resolve não há o aplicativo: quem abre a janela larga é a casca.
    const r = NLE === "resolve" && ponte() && ponte().abrirRevisao
      ? await ponte().abrirRevisao() : await post("/app/revisao");
    avisar(r.janela ? "" : "o aplicativo não está aberto: abra o De Lá Pra Cá para revisar na janela larga");
  } catch (e) {
    avisar("não consegui chamar o aplicativo para a janela de revisão");
  } finally {
    b.disabled = false;
  }
}

/* ⭐ Na janela única do app a revisão é uma VISTA da mesma janela (decisão 1 do organograma de 2026-10-19): ela
   alarga para a esquerda (`/app/janela`), mostra a lista larga em "tudo" e o "Concluir revisão" volta ao passo de
   onde se veio, ao tamanho de antes, e relê a lista. As decisões continuam gravadas no clique. */
function passoVisivel() {
  const p = document.querySelector(".passo:not([hidden])");
  return p ? p.id : "passoOrigem";
}
async function entrarRevisaoNaJanela() {
  if (revisaoNaJanela) return;
  revisaoNaJanela = { passo: passoVisivel() };
  document.body.classList.add("vista-revisao");
  irPara("deLaPraCa");
  mostrarPasso("passoRevisao");
  filtro = "tudo";
  for (const x of el("filtro").children) x.classList.toggle("on", x.dataset.filtro === "tudo");
  el("btnConcluirRevisao").hidden = false;
  el("btnVoltar").hidden = true;
  el("btnAplicar").parentElement.hidden = true;
  if (el("barraAcoes")) el("barraAcoes").hidden = true;
  ajustarBarra();
  try { await post("/app/janela", { larga: true }); } catch (_) { /* sem app: a vista vale na largura que houver */ }
  carregarRevisao().catch(() => {});
}
async function sairRevisaoNaJanela() {
  const r = revisaoNaJanela;
  revisaoNaJanela = null;
  document.body.classList.remove("vista-revisao");
  el("btnConcluirRevisao").hidden = true;
  el("btnVoltar").hidden = false;
  el("btnAplicar").parentElement.hidden = false;
  mostrarPasso((r && r.passo) || "passoOrigem");
  if (el("barraAcoes")) el("barraAcoes").hidden = false;
  try { await post("/app/janela", { larga: false }); } catch (_) { /* idem */ }
  if (NLE === "mc") recarregarMastersMC().catch(() => {});
  else if (rcAntes && rcAntes.carta) aposDecidirCarta();
  pintarCarga();
}

el("btnJanelaRevisao").onclick = () => abrirJanelaRevisao(el("btnJanelaRevisao"), (texto) => {
  const aviso = el("avisoJanelaRevisao");
  aviso.textContent = texto ? `— ${texto}; a revisão continua aqui.` : "";
  aviso.hidden = !texto;
});

el("filtro").onclick = (ev) => {
  const b = ev.target.closest("button[data-filtro]");
  if (!b) return;
  filtro = b.dataset.filtro;
  for (const x of el("filtro").children) x.classList.toggle("on", x === b);
  carregarRevisao();
};

el("listaMasters").onclick = async (ev) => {
  const b = ev.target.closest("button[data-aceitar], button[data-limpar]");
  if (!b) return;
  try {
    if (b.dataset.limpar) await post("/trabalho/escolher", { mob_id: b.dataset.limpar });
    else await post("/trabalho/escolher", { mob_id: b.dataset.aceitar, arquivo: b.dataset.arquivo });
    carregarRevisao();
  } catch (e) { dizer(e.message, false); }
};

el("btnAplicar").onclick = async () => {
  dizer("");
  // No Resolve, "aplicar" é importar a timeline já apontada para os originais decididos.
  if (RECEBE) { await importarComOriginais(); return; }
  try {
    // Vazio deixa o serviço usar o padrão; ele é quem resolve colisão de nome.
    const r = await post("/trabalho/aplicar", { nome_bin: el("nomeBin").value.trim() });
    // ⚠️ O nome VEM DE VOLTA, e não é o mesmo que foi enviado: quem resolve colisão e
    // numeração é o serviço. Avisar sobre "a bin X" usando o texto digitado nomearia
    // uma bin que não existe — pior que não avisar.
    avisarSobreABin(r && r.bin);
    mostrarPasso("passoProgresso");
    acompanhar();
  } catch (e) { dizer(e.message, false); }
};

for (const [id, campo] of [["optSubclipes", "achatar_subclipes"],
                           ["optGrupos", "achatar_group_clips"]]) {
  el(id).onchange = () => post("/trabalho/opcoes", { [campo]: el(id).checked }).catch(() => {});
}

el("autor").onclick = () => post("/link/abrir", { qual: "autor" }).catch(() => {});

/* O arrasto é ouvido no DOCUMENTO INTEIRO, não numa caixinha.
   Mirar um alvo pequeno com o mouse segurando um clipe é trabalho; e o painel tem
   400px de largura, onde qualquer zona dedicada roubaria espaço do que já está lá.
   A janela toda aceita, e o realce diz que aceita.

   ⚠️ `dragover` PRECISA de `preventDefault()`. Sem ele o navegador cancela o drop e o
   `drop` nunca dispara — a falha clássica de drag-and-drop em HTML, e ela é silenciosa:
   o cursor mostra "proibido" e nenhum log aparece. */
/* ⚠️⚠️ O `preventDefault` é INCONDICIONAL, e não só quando o MIME é o nosso.
   Sem ele, soltar um ARQUIVO sobre o painel faz a webview **navegar para o arquivo** —
   a UI desaparece e o editor fica olhando um AAF cru, sem entender o que fez. O filtro
   de MIME decide o REALCE (só destacamos o que sabemos receber), nunca se o navegador
   pode assumir o controle. */
/* ⚠️⚠️ FASE DE CAPTURA (`true` no fim), e não a de bolha.
   Um `<select>` ou um `<input type=text>` têm tratamento PRÓPRIO de drop, e um arrasto
   solto em cima deles pode ser consumido antes de chegar ao documento. Na captura o
   documento vê o evento PRIMEIRO, então o alvo do arrasto é a janela inteira de verdade
   — e não "a janela inteira, menos os campos". */
/* ⚠️ E o `preventDefault` continua no DOCUMENTO inteiro, embora só as ZONAS aceitem.
   São coisas separadas: limitar onde o arrasto TEM EFEITO é decisão de interface;
   impedir a webview de navegar para o arquivo é defesa, e vale em cada pixel do painel.
   Um `preventDefault` restrito às zonas devolveria o pior dos dois mundos — soltar
   fora da área faria a UI sumir. */
document.addEventListener("dragenter", (ev) => {
  ev.preventDefault();
  // ⭐ Registrar os tipos AQUI responde a pergunta que o `drop` sozinho não responde:
  // *este arrasto chegou a expor tipos em algum momento?* Durante `dragenter` o
  // navegador está em **protected mode** — `getData` devolve vazio —, mas `types` já
  // está disponível. Se um arrasto exibe tipos no enter e nenhum no drop, o problema é
  // outro; se não exibe em nenhum dos dois, a plataforma não entregou nada.
  const t = tiposDoArrasto(ev.dataTransfer);
  if (t.length) tiposNoEnter = t;
  const itens = itensDoArrasto(ev.dataTransfer);
  if (itens.length) itensNoEnter = itens;
  profundidadeArrasto++;
  realcar(especieDoArrasto(ev.dataTransfer), ev.target);
}, true);

document.addEventListener("dragover", (ev) => {
  ev.preventDefault();
  const especie = especieDoArrasto(ev.dataTransfer);
  if (!especie) return;
  const efeito = efeitoCompativel(ev.dataTransfer);
  // `null` = a origem não permite nada; não insistimos.
  if (efeito) ev.dataTransfer.dropEffect = efeito;
  // ⭐ `dragover` repete enquanto o arrasto está sobre a página (inclusive parado), e é
  // ELE quem faz o véu seguir o cursor entre as zonas — `dragenter` sozinho perderia a
  // travessia. Também é a rede contra um `dragenter` engolido por um filho.
  realcar(especie, ev.target);
}, true);

document.addEventListener("dragleave", (ev) => {
  profundidadeArrasto = Math.max(0, profundidadeArrasto - 1);
  if (profundidadeArrasto === 0) limparRealce();
}, true);

/* Soltar em qualquer lugar apaga o realce — inclusive fora das zonas, onde o drop só
   produz mensagem. E `dragend` cobre o arrasto abandonado (tecla Esc, ou soltar fora da
   janela), que não dispara `drop` nenhum e deixaria o overlay aceso para sempre. */
document.addEventListener("dragend", limparRealce, true);

/* O `drop` é ouvido no documento e SEM filtro de MIME: um arrasto que chegue com outros
   tipos — ou na área errada — tem de produzir uma MENSAGEM, não um silêncio. É `aoSoltar`
   quem decide pela zona; ver o comentário do despacho. */
document.addEventListener("drop", (ev) => {
  aoSoltar(ev).catch((e) => dizerNoArrasto(e.message, false));
}, true);

/* ── Na janela do APLICATIVO (`casca=app`, 2026-10-18): o arrasto vem do alvo NATIVO ────────────────────────────

   ⛔ Medido no Windows (MC 24.6, autor): numa webview comum, soltar uma timeline do MC fez o AVID começar um EXPORT
   — o arrasto da sequência anuncia também um `.aaf` virtual que só é gerado quando o alvo o pede, e o WebView2 pede
   (deu "contains offline media. Continue exporting or abort?", que trava o Explorer até fechar). E a pasta do
   Explorer chegou SEM caminho ("esse arrasto não trouxe caminho"). Por isso, nessa janela, o drop do WebView2 é
   desligado e quem recebe é um `IDropTarget` do app (`app/src-tauri/src/arrasto_win.rs`): ele lê SÓ o formato do
   Avid (nunca o arquivo) ou os caminhos do Explorer, e chama `delapracaArrasto` com as fases. Aqui ele vira o MESMO
   `dataTransfer` que o painel sempre leu — o realce e o despacho por zona são os de sempre. */
const CASCA_APP = new URLSearchParams(location.search).get("casca") === "app";

/* ⭐ EMBUTIDO no guarda-chuva do Ciclo Assist (`?embutido=1`, 2026-10-21): a moldura é dele — o estado da conexão e o
   pino no topo, uma engrenagem à direita das abas Preparar · Assistir · Conformar · Entregar, a assinatura no rodapé.
   Aqui somem o cabeçalho, a engrenagem e a linha da assinatura (`painel.css`, `.embutido`), e a engrenagem de lá chama
   `cicloEmbutido.configuracoes()`, que vai aos Ajustes e volta à aba de antes. O mesmo contrato nos três apps. */
const EMBUTIDO = new URLSearchParams(location.search).get("embutido") === "1";
if (EMBUTIDO) document.documentElement.classList.add("embutido");
let abaAntesDosAjustes = "deLaPraCa";
// `configuracoes()` alterna; `configuracoes(false)` FECHA e volta à aba de antes — o guarda-chuva chama assim quando
// esta aba sai de vista (senão ela voltava nos Ajustes no lugar do trabalho, visto pelo autor em 2026-10-21).
window.cicloEmbutido = {
  configuracoes(abrir) {
    const atual = ABAS.find((a) => el("tab" + a[0].toUpperCase() + a.slice(1)).classList.contains("on")) || "deLaPraCa";
    const aberta = atual === "ajustes";
    const querer = abrir === undefined ? !aberta : !!abrir;
    if (querer === aberta) return;
    if (!querer) { irPara(abaAntesDosAjustes); return; }
    abaAntesDosAjustes = atual;
    irPara("ajustes");
  },
};

function dtDoApp(n) {
  const dados = {};
  if (n.tipo === "avid") dados[MIME_MC_ASSETS] = n.dados || "";
  if (n.tipo === "arquivos") {
    const caminhos = n.caminhos || [];
    // POSIX (o Mac, 2026-10-24): "/Volumes/x" → "file:///Volumes/x" — com o "file:///" do Windows saía "file:////…",
    // que volta como "//Volumes/x" e o serviço o recusa como UNC
    const uri = (c) => (/^\\\\/.test(c)
      ? "file:" + c.replace(/\\/g, "/").split("/").map(encodeURIComponent).join("/")
      : c.startsWith("/") ? "file://" + c.split("/").map(encodeURIComponent).join("/")
      : "file:///" + c.replace(/\\/g, "/").split("/").map((p, i) => (i ? encodeURIComponent(p) : p)).join("/"));
    dados["text/uri-list"] = caminhos.map(uri).join("\r\n");
    dados["Files"] = "";
  }
  const tipos = Object.keys(dados);
  return {
    types: tipos, items: tipos.map((t) => ({ kind: "string", type: t })), files: [],
    effectAllowed: n.tipo === "avid" ? "move" : "copy", dropEffect: "copy",
    getData: (t) => (n.fase === "soltou" ? dados[t] || "" : ""),
  };
}

let pontoNativo = null;
window.delapracaArrasto = (n) => {
  if (!n || n.fase === "saiu") { limparRealce(); return; }
  // Mac: o ponto conta do topo da MOLDURA (a barra de título, 28 pontos medidos em 2026-10-24) — `arrasto_mac.rs`
  // manda a altura da janela e aqui sai a diferença para a área da página. O Windows não manda `altura`.
  if (n.altura && n.altura > innerHeight) n = { ...n, y: n.y - (n.altura - innerHeight), y_bruto: n.y };
  const alvo = document.elementFromPoint(n.x, n.y) || document.body;
  if (n.fase === "soltou") {
    const bloco = alvo.closest ? alvo.closest(".bloco") : null;
    pontoNativo = { x: n.x, y: n.y, y_bruto: n.y_bruto, altura: n.altura, alvo: (alvo.id || alvo.className || alvo.tagName || "").toString().slice(0, 60),
                    bloco: bloco ? (bloco.id || "").slice(0, 40) : "", janela: [innerWidth, innerHeight] };
  }
  if (n.tipo === "bin") {
    if (n.fase === "soltou") {
      limparRealce();
      ultimoBloco = alvo.closest ? (alvo.closest(".bloco") || null) : null;
      dizerNoArrasto("a bin do painel lateral não viaja no arrasto — abra a bin e arraste a timeline de dentro dela", false);
    }
    return;
  }
  // ⭐ De DENTRO do Resolve (Media Pool) ou do Premiere (projeto): o alvo nativo já leu a identidade (2026-10-19)
  if (n.tipo === "resolve" || n.tipo === "premiere" || n.tipo === "premiere_item") {
    if (n.fase === "sobre") { realcar("nle", alvo); return; }
    if (n.fase === "soltou") {
      limparRealce();
      soltarDoNle(n, alvo).catch((e) => dizerNoArrasto(e.message, false));
    }
    return;
  }
  // ⭐ Mac (2026-10-25): o MC entrega só os MobIDs (o XML do Qt; `arrasto_mac.rs`) — a espécie vem do serviço, e daí
  // o arrasto segue igual ao do Windows
  if (n.tipo === "avid" && n.fase === "soltou" && !n.dados && (n.mob_ids || []).length) {
    limparRealce();
    dizerNoArrasto("lendo o que veio do Media Composer…", true);
    post("/arrasto/mc", { mob_ids: n.mob_ids })
      .then((r) => {
        if (!r.ok) { dizerNoArrasto(r.erro || "não reconheci o que veio do Media Composer", false); return; }
        return aoSoltar({ preventDefault() {}, dataTransfer: dtDoApp({ ...n, dados: JSON.stringify(r.itens) }),
                          target: alvo });
      })
      .catch((e) => dizerNoArrasto(e.message, false));
    return;
  }
  const dt = dtDoApp(n);
  if (n.fase === "sobre") { realcar(especieDoArrasto(dt), alvo); return; }
  if (n.fase === "soltou") {
    aoSoltar({ preventDefault() {}, dataTransfer: dt, target: alvo })
      .catch((e) => dizerNoArrasto(e.message, false));
  }
};

/* ── O arrasto de DENTRO do Resolve e do Premiere (2026-10-19) ──────────────────────────────────────────────────────
   O alvo nativo do app lê o que o painel web nunca viu (banco: resolve-scripting/api-scripting.md §"Arrastar do Media
   Pool"; premiere-cep/arrastar-e-selecao.md §6b) e o serviço o resolve (`/arrasto/nle`):
   - uma TIMELINE do Resolve → a conferência pela referência sobre ela (autor, 2026-10-19: "se o usuário duplicar a TL
     para organizar, basta ele trazer essa TL para o nosso programa e rodar com o vid ref indicado");
   - uma SEQUÊNCIA do Premiere → o projeto dela, já com a sequência marcada (o mesmo fluxo do .prproj solto). */
async function soltarDoNle(n, alvo) {
  ultimoBloco = alvo && alvo.closest ? alvo.closest(".bloco") : null;
  const r = await post("/arrasto/nle", { tipo: n.tipo, media_id: n.media_id || "", dados: n.dados || "" });
  if (!r.ok) { dizerNoArrasto(r.erro || "não reconheci o que foi arrastado", false); return; }
  if (r.programa === "resolve") {
    if (NLE !== "resolve") { dizerNoArrasto(`timeline “${r.nome}” do Resolve: conecte o Resolve para usá-la aqui`, false); return; }
    mostrarTimelineDoResolve(r);
    return;
  }
  // Premiere: o projeto SALVO (o arrasto diz o .prproj; o que não foi salvo não está nele)
  if (!r.existe) { dizerNoArrasto("o projeto do Premiere não está salvo neste computador — salve e arraste de novo", false); return; }
  if (!RECEBE) {
    dizerNoArrasto(`sequência “${r.nome || "?"}” do Premiere reconhecida — levá-la ao Media Composer ainda não existe`, false);
    return;
  }
  await carregarSequenciaDoPremiere(r);
}

/* Uma sequência do Premiere (arrastada de dentro dele, ou a aberta nele) → o projeto SALVO, com ela marcada. No modo
   Premiere é o Premiere → Premiere (organograma aprovado em 2026-10-22): o "Montar" cria uma cópia relinkada dela. O app
   lê o arquivo, não a memória do Premiere: a hora do último salvamento fica à vista (decisão B do organograma). */
async function carregarSequenciaDoPremiere(r) {
  irParaModo("aaf");
  await abrirArquivo(r.prproj);
  const seq = sequenciasDaCarga().find((s) => s.nome === r.nome);
  if (seq) { rcSeqEscolhida = seq.mob_id; pintarCarga(); }
  const hora = r.salvo ? new Date(r.salvo * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "";
  dizerNoArrasto(seq ? `sequência “${r.nome}” — lida do projeto SALVO${hora ? ` às ${hora}` : ""}` + (r.alterado
      ? ": o Premiere tem mudanças NÃO salvas neste projeto — se mexeu na sequência, salve no Premiere (Ctrl+S) e carregue de novo"
      : ": se mudou algo depois, salve no Premiere e carregue de novo")
    : `não achei a sequência “${r.nome || "?"}” no projeto salvo — salve no Premiere e carregue de novo`, seq ? "aviso" : false);
  // a sequência foi indicada de propósito (o botão ou o arrasto de dentro do Premiere): direto à tela de montar, sem a
  // lista de sequências do projeto (autor, 2026-10-24)
  if (seq) await importarCarga();
}

if (el("rcBtnSeqAberta")) {
  el("rcBtnSeqAberta").onclick = async () => {
    ultimoBloco = el("blocoTimeline");
    if (NLE === "premiere") {
      try {
        const r = await post("/premiere/sequencia-ativa", {});
        if (!r.ok) { dizerNoArrasto(r.erro || "não achei a sequência aberta no Premiere", false); return; }
        if (!r.existe) { dizerNoArrasto("o projeto do Premiere não está salvo neste computador — salve e carregue de novo", false); return; }
        await carregarSequenciaDoPremiere(r);
      } catch (e) { dizerNoArrasto(e.message, false); }
      return;
    }
    try {
      const r = await post("/resolve/timeline-aberta", {});
      if (!r.ok) { dizerNoArrasto(r.erro || "não achei a timeline aberta", false); return; }
      mostrarTimelineDoResolve(r);
    } catch (e) { dizerNoArrasto(e.message, false); }
  };
}

/* "Carregar a seleção da timeline" no Resolve (igualar as funções do MC/Premiere, 2026-10-25): só os clipes
   SELECIONADOS na timeline do Resolve (`GetSelectedClips`) → a conferência roda só neles. Resolve antigo sem a
   seleção, ou nada selecionado → avisa; o editor usa "Carregar a sequência aberta" para a timeline inteira. */
if (el("rcBtnSelecaoTL")) {
  el("rcBtnSelecaoTL").onclick = async () => {
    ultimoBloco = el("blocoTimeline");
    if (NLE !== "resolve") { dizerNoArrasto("conecte o Resolve para carregar a seleção da timeline dele", false); return; }
    try {
      const r = await post("/resolve/selecao-da-timeline", {});
      if (!r.ok) {
        dizerNoArrasto(r.erro || "não consegui ler a seleção da timeline do Resolve"
          + (r.selecao_indisponivel ? " — use “Carregar a sequência aberta”" : ""), false);
        return;
      }
      mostrarTimelineDoResolve(r);
    } catch (e) { dizerNoArrasto(e.message, false); }
  };
}

function mostrarTimelineDoResolve(r) {
  rcFeitoTl = { nome: r.nome, uid: r.uid || "", drt: "", so_selecionados: !!r.so_selecionados };
  rcConf = null;
  rcConfAviso = "";
  rcRefDepois = { caminho: "", som: true };
  const sel = r.so_selecionados ? ` · só a seleção (${r.clipes || "?"} clipe${r.clipes === 1 ? "" : "s"})` : "";
  el("rcFeito").innerHTML = `<p class="bloco-titulo">timeline do Resolve</p>
    <p class="previa-ok">“${escapar(r.nome)}”${r.projeto ? ` · ${escapar(r.projeto)}` : ""}${sel}</p><div id="rcConferencia"></div>`;
  pintarConferencia();
  el("rcFeito").hidden = false;
}

/* O pino: a janela do app fica na frente do Media Composer enquanto o editor pega coisas na bin. Quem mexe na janela
   é o executável (`/app/fixar` → `--fixar-mc`); lembrado por janela, como a aba. */
const CHAVE_PINO = "delapraca.mc.pino";
async function aplicarPino(fixar) {
  const b = el("pino");
  b.setAttribute("aria-pressed", fixar ? "true" : "false");
  b.title = fixar ? "Fixada na frente — clique para soltar" : "Manter esta janela na frente das outras";
  try { localStorage.setItem(CHAVE_PINO, fixar ? "1" : ""); } catch (_) { /* só conveniência */ }
  try { await post("/app/fixar", { fixar }); } catch (_) { /* sem app, o botão nem aparece */ }
}
if (CASCA_APP && el("pino")) {
  el("pino").hidden = false;
  el("pino").onclick = () => aplicarPino(el("pino").getAttribute("aria-pressed") !== "true");
  let lembrado = false;
  try { lembrado = localStorage.getItem(CHAVE_PINO) === "1"; } catch (_) { /* idem */ }
  if (lembrado) aplicarPino(true);
}

/* ── Aba Daqui Pra Lá: a timeline sai ──────────────────────────────────────────
   ⛔⛔ Nada aqui pede `ExportFile`: o serviço lê a timeline direto da BIN (ADR 0015).

   O fluxo: arrastar → o serviço acha a bin, SALVA, lê e resolve os arquivos (SSE) →
   o editor escolhe formato, pasta e nome → Exportar (SSE de novo). */

/* ⭐ Lembrar o formato É o pedido do autor, e é seguro pelo mesmo motivo que lembrar a
   aba é: preferência de interface, que não envelhece nem aponta para nada no disco. O
   oposto das PASTAS DE MÍDIA (que saíram do `localStorage` em 2026-08-16 por reaparecerem
   erradas) — ver o comentário de `pastas`. A pasta de destino, por isso, NÃO é lembrada: o
   Exportar… a pergunta a cada vez (organograma de 2026-09-25: o botão decide o destino). */
const CHAVE_FORMATO_EXPORT = "delapraca.daquiprala.formato";
const EXT_EXPORT = { carta_aberta: ".json", drt: ".drt" };

let exPronto = false;      // a timeline foi lida e dá para exportar
let exRodando = false;
let exNomeOk = false;
let exFonte = null;
let exTimer = null;
let exCamposDesenhados = false;
let mlCanais = [];         // os canais do Magic Link desta ilha (`GET /magic`, ver `canais.py`)

function lerFormatoExport() {
  try {
    const salvo = localStorage.getItem(CHAVE_FORMATO_EXPORT);
    // Só um formato que EXISTE e está LIGADO: um valor antigo de outra build, ou um
    // formato que voltou a "em breve", não pode deixar o seletor num estado inválido.
    const op = Array.from(el("exFormato").options).find((o) => o.value === salvo);
    if (op && !op.disabled) return salvo;
  } catch (_) { /* localStorage indisponível: o padrão resolve */ }
  return "carta_aberta";
}

function gravarFormatoExport(v) {
  try { localStorage.setItem(CHAVE_FORMATO_EXPORT, v); } catch (_) { /* idem */ }
}

function atualizarBotaoExport() {
  const pode = exPronto && exNomeOk && !exRodando;
  el("exBtnExportar").disabled = !pode;
  // Os botões do Magic Link não pedem pasta (é a do canal), mas usam o NOME do campo: é o
  // nome da timeline do outro lado.
  for (const b of el("mlEnviarTimeline").querySelectorAll("button[data-canal]")) {
    b.disabled = !(pode && b.dataset.conectado === "1");
  }
  const f = el("exFormato").value;
  el("exNotaComentario").hidden = f !== "drt";
}

async function soltarTimelineParaExportar(dt) {
  let itens;
  try {
    itens = lerPayload(dt);
  } catch (e) {
    dizerNoArrasto("o Media Composer mandou algo que não consegui ler: " + e.message, false);
    return;
  }
  const seqs = itens.filter((i) => i && i.type === "sequence" && i.id);
  if (!seqs.length) {
    dizerNoArrasto(itens.length
      ? `aqui entra timeline — você soltou ${descreverEspecies(itens)}`
      : "o arrasto veio vazio", false);
    return;
  }
  // ⚠️ Uma por vez, e RECUSANDO: exportar tem alvo único, e ficar calado com uma de várias
  // faria o editor achar que exportou outra.
  if (seqs.length > 1) {
    dizerNoArrasto(`uma timeline por vez — você soltou ${seqs.length}`, false);
    return;
  }
  if (exRodando) {
    dizerNoArrasto("espere a exportação em andamento terminar", false);
    return;
  }
  const item = seqs[0];
  dizerNoArrasto("lendo a timeline arrastada…", true);

  let nome = "";
  try {
    nome = (await post("/mc/mob", { mob_id: item.id })).nome || "";
  } catch (e) {
    if (e.status === 404) { dizerNoArrasto(e.message, false); return; }
  }

  exPronto = false;
  el("exSequencia").textContent = nome || "timeline arrastada";
  el("exSequencia").hidden = false;
  el("exDica").hidden = true;
  el("exResumo").hidden = true;
  el("exFeito").hidden = true;
  // ⚠️ `%` DOBRADO: uma sequência chamada `CORTE 50%` entraria crua no campo e o `%`
  // viraria tag desconhecida — o botão travaria sem o editor ter escrito nada.
  // Se a equipe já usa um padrão (`%sequencia_%data`…), ele volta; senão, o nome cru.
  el("exNome").value = lerPadrao("timeline") || nome.replace(/%/g, "%%");
  previaDoNome();
  atualizarBotaoExport();
  try {
    await post("/export/preparar", { mob_id: item.id, sequence: nome });
    acompanharExport();
  } catch (e) {
    dizerNoArrasto(e.message, false);
  }
}

function acompanharExport() {
  if (exFonte) exFonte.close();
  exFonte = new EventSource("/export/progresso");
  exFonte.onmessage = (ev) => {
    let e; try { e = JSON.parse(ev.data); } catch (_) { return; }
    pintarExport(e);
  };
  exFonte.onerror = () => { if (exFonte) exFonte.close(); exFonte = null; exRodando = false;
                            atualizarBotaoExport(); };
}

function fecharFonteExport() { if (exFonte) { exFonte.close(); exFonte = null; } }

function pintarExport(e) {
  exRodando = e.fase === "preparando" || e.fase === "gerando";
  el("exProgresso").hidden = !exRodando;
  el("exBtnCancelar").hidden = !exRodando;
  if (exRodando) {
    const pct = e.total ? Math.round(100 * e.feito / e.total) : 0;
    el("exEtapa").textContent = e.etapa || e.fase;
    el("exBarra").style.width = (e.total ? pct : 100) + "%";
    el("exPct").textContent = e.total ? `${e.feito}/${e.total}` : "";
    el("exDetalhe").innerHTML = `<bdi>${escapar(e.detalhe || "")}</bdi>`;
  }
  const leu = !!(e.resultado && e.resultado.sequencia);
  if (e.fase === "pronto") {
    fecharFonteExport(); exPronto = true; pintarResumoExport(e.resultado);
    dizer("timeline lida — exporte ou envie pelo Magic Link", true);
  } else if (e.fase === "feito") {
    fecharFonteExport(); exPronto = true; pintarResumoExport(e.resultado);
    pintarFeitoExport(e.resultado);
  } else if (e.fase === "erro") {
    // Um erro ao GRAVAR não desfaz a leitura: dá para trocar a pasta e tentar de novo.
    fecharFonteExport(); exPronto = leu; dizer(e.erro, false);
  } else if (e.fase === "ocioso" && e.etapa === "cancelado") {
    fecharFonteExport(); exPronto = leu; dizer("cancelado", false);
  }
  atualizarBotaoExport();
}

function pintarResumoExport(r) {
  const alvo = el("exResumo");
  if (!r || !r.sequencia) { alvo.hidden = true; return; }
  let h = '<div class="placar">'
    + pill(`${r.eventos} eventos`, "")
    + pill(`V${r.trilhas_video} · A${r.trilhas_audio}`, "")
    + pill(`${r.masters_com_arquivo} online`, "ok")
    + (r.masters_offline_total ? pill(`${r.masters_offline_total} offline`, "") : "")
    + pill(`${r.fps} fps · ${r.tc_inicial}`, "")   // `pill` já escapa
    + "</div>";
  // ⭐ Offline NÃO é falha: quem edita com mídia gerenciada não tem os originais, e quem
  // recebe (o colorista) tem. O clipe chega ao Resolve com o nome de câmera e o TC de
  // origem, e ele religa lá. O que o painel precisa dizer é QUEM vai assim — e alertar só
  // quando falta o que o colorista usaria para religar.
  if (r.masters_offline_total) {
    h += `<details class="avancado"><summary>${r.masters_offline_total} chegam offline ao `
      + "Resolve, para religar aos originais</summary><div class=\"avancado-corpo\">"
      + r.masters_offline.map((m) => `<div class="dica"><strong>${escapar(m.arquivo || m.reel || m.nome)}</strong>`
        + (m.tem_tc ? "" : " — <em>sem TC de origem</em>") + "</div>").join("")
      + (r.masters_offline_total > r.masters_offline.length
        ? `<div class="dica">… e mais ${r.masters_offline_total - r.masters_offline.length}</div>`
        : "")
      + "</div></details>";
    if (r.pastas_sem_indice) {
      // ⚠️ Pasta de mídia SEM o índice do Avid (medido em storage de rede): o que estiver
      // lá sai offline, calado, se ninguém disser. Banco, `protocolos/msm/pmr-fmid.md` §5.
      h += `<p class="aviso">${r.pastas_sem_indice} pasta(s) de mídia do Avid sem índice `
        + "(storage de rede?) — clipes que estejam só nelas saem offline.</p>";
    }
    if (r.offline_sem_tc) {
      h += `<p class="aviso">${r.offline_sem_tc} original(is) sem TC de origem na bin — `
        + "o colorista terá de religar esses pelo nome.</p>";
    }
  }
  for (const a of (r.avisos || [])) {
    h += `<p class="aviso">${escapar(a.texto)}${a.vezes > 1 ? ` (×${a.vezes})` : ""}</p>`;
  }
  alvo.innerHTML = h;
  alvo.hidden = false;
}

function pintarFeitoExport(r) {
  const s = r.saida || {};
  let h = `<div class="bloco"><p class="bloco-titulo">pronto</p>`
    + `<div class="caminho"><bdi>${escapar(r.arquivo || "")}</bdi></div>`;
  if (r.formato === "drt") {
    h += `<p class="dica">${escapar(s.clips_generated)} clipes de vídeo, `
      + `${escapar(s.audio_clips)} de áudio, ${escapar(s.pool_clips)} arquivos no media pool</p>`;
    if (s.clipes_offline) {
      h += `<p class="dica">${escapar(s.clipes_offline)} eventos apontam para originais que `
        + "não estão nesta máquina — no Resolve, selecione-os e use <em>Relink</em> na "
        + "pasta dos originais.</p>";
    }
    if (s.comentario_ignorado) {
      h += '<p class="aviso">o comentário não virou marcador — no DRT isso ainda não é '
        + "escrito. Exporte também a Carta Aberta para guardá-lo.</p>";
    }
  } else {
    h += `<p class="dica">${escapar(s.segmentos)} eventos, ${escapar(s.com_arquivo)} online, `
      + `${escapar(s.offline || 0)} offline</p>`;
  }
  el("exFeito").innerHTML = h + "</div>";
  el("exFeito").hidden = false;
  dizer("exportado", true);
}

/* O nome é renderizado NO SERVIÇO, com a mesma gramática que grava o arquivo: um preview
   que calcula diferente do que grava é mentira com boa aparência. */
function previaDoNome() {
  clearTimeout(exTimer);
  exTimer = setTimeout(async () => {
    const alvo = el("exPrevia");
    try {
      const r = await post("/export/nome", { padrao: el("exNome").value });
      if (!exCamposDesenhados && r.campos) desenharCampos(r.campos);
      exNomeOk = !!r.nome;
      alvo.className = "dica " + (r.nome ? "previa-ok" : "previa-er");
      alvo.textContent = r.nome
        ? "→ " + r.nome + (EXT_EXPORT[el("exFormato").value] || "")
        : (r.erro || "");
    } catch (e) {
      exNomeOk = false;
      alvo.className = "dica previa-er";
      alvo.textContent = e.message;
    }
    atualizarBotaoExport();
  }, 180);
}

function desenharCampos(campos) {
  el("exCampos").innerHTML = campos.map((c) =>
    `<button type="button" data-campo="${escapar(c.campo)}" title="${escapar(c.valor)}">`
    + `${escapar(c.rotulo)}</button>`).join("");
  exCamposDesenhados = true;
}

/* O botão insere a TAG FECHADA `%{campo}` onde está o cursor: é a forma sem ambiguidade
   (`C%{cena}P` funciona; `C%cenaP` não), a mesma decisão do Órbita. */
el("exCampos").onclick = (ev) => {
  const b = ev.target.closest("button[data-campo]");
  if (!b) return;
  const campo = el("exNome");
  const tag = `%{${b.dataset.campo}}`;
  const ini = campo.selectionStart ?? campo.value.length;
  const fim = campo.selectionEnd ?? campo.value.length;
  campo.value = campo.value.slice(0, ini) + tag + campo.value.slice(fim);
  campo.focus();
  campo.setSelectionRange(ini + tag.length, ini + tag.length);
  previaDoNome();
};

el("exNome").oninput = () => { gravarPadrao("timeline", el("exNome").value); previaDoNome(); };
el("exFormato").onchange = () => {
  gravarFormatoExport(el("exFormato").value);
  previaDoNome();
  atualizarBotaoExport();
};
el("exBtnCancelar").onclick = () => post("/export/cancelar").catch(() => {});
/* Exportar… pergunta a pasta NA HORA (seletor nativo do serviço) e grava ali. */
el("exBtnExportar").onclick = async () => {
  dizer("");
  el("exFeito").hidden = true;
  let pasta = "";
  try {
    pasta = (await post("/escolher/destino")).caminho || "";
  } catch (e) { dizer(e.message, false); return; }
  if (!pasta) return;                      // o editor cancelou o seletor
  try {
    await post("/export/gerar", {
      formato: el("exFormato").value,
      pasta,
      padrao: el("exNome").value,
      comentario: el("exComentario").value,
      producao: el("exProducao").value,
    });
    exRodando = true;
    atualizarBotaoExport();
    acompanharExport();
  } catch (e) { dizer(e.message, false); }
};

el("exFormato").value = lerFormatoExport();
previaDoNome();

/* ── Magic Link: enviar por um CANAL ───────────────────────────────────────────
   Timeline completa ou INSERT. O destino é o BOTÃO: "Enviar para a Cor", "Enviar para o
   VFX"… (um por canal que esta ilha usa, `canais.py`) ou Exportar… (onde o editor quiser). As
   pastas dos canais são do PROJETO (guardadas pelo serviço na .delapraca.json) — nada disso vai
   para o localStorage. O Avid envia sempre como Edição. O insert pega o tipo do canal.

   O botão Coletar é um coletor do que estiver selecionado na timeline: por dentro o serviço
   foca a timeline e copia (Ctrl+0, Ctrl+C), grava a cópia numa bin descartável e a lê. Leva
   ~8 s; a timeline pisca e volta no mesmo ponto (medido em 2026-09-24). */

const CHAVE_MODO_EXPORT = "delapraca.daquiprala.modo";
let insItens = [];
let insOcupado = false;

function trilhaDe(t) { return t < 1000 ? `V${t}` : `A${t - 999}`; }

/* Os botões "Enviar para…" de um modo (timeline ou insert), um por canal. */
function desenharBotoesCanal(alvo, dica) {
  el(alvo).innerHTML = mlCanais.map((c) =>
    `<button class="primary" data-canal="${escapar(c.setor)}" data-conectado="${c.conectado ? 1 : 0}"
       title="${escapar(c.conectado ? c.pasta : "canal não conectado — veja em Ajustes")}" disabled>`
    + `Enviar ${escapar(c.para)}</button>`).join("");
  const faltam = mlCanais.filter((c) => !c.conectado).map((c) => c.rotulo);
  el(dica).textContent = faltam.length === mlCanais.length
    ? "Nenhum canal conectado. Conecte em ⚙ Ajustes."
    : faltam.length ? `${faltam.join(" e ")}: não conectado (⚙ Ajustes).` : "";
}

function pintarCanaisEnvio(r) {
  mlCanais = (r && r.canais) || [];
  desenharBotoesCanal("mlEnviarTimeline", "mlDicaTimeline");
  desenharBotoesCanal("mlEnviarInsert", "mlDicaInsert");
}

function pintarMagic(r) {
  if (!r) return;
  if (r.canais) pintarCanaisEnvio(r);
  const c = r.coleta || {};
  insItens = c.itens || [];
  el("insLista").innerHTML = insItens.map((i) =>
    `<div class="item"><div class="item-topo">`
    + `<span class="item-seg">${escapar(trilhaDe(i.track))}</span>`
    + `<span class="item-nome">${escapar(i.clip_name || "?")}</span>`
    + `<span class="item-seg">${escapar(i.timeline_tc_in)}–${escapar(i.timeline_tc_out)}</span>`
    + `<button class="x" title="tirar da lista" data-chave="${escapar(JSON.stringify(
        [i.track, i.timeline_tc_in, i.mob_id]))}">✕</button>`
    + `</div></div>`).join("");
  el("insVazia").hidden = insItens.length > 0;
  el("insBtnLimpar").hidden = insItens.length === 0;
  el("insResumo").textContent = insItens.length
    ? `${insItens.length} clipe(s) · ${(c.trilhas || []).join(" ")}`
      + (c.sequencia && c.sequencia.nome ? ` · ${c.sequencia.nome}` : "")
    : "";
  const p = c.pendente;
  el("insConfirmar").hidden = !p;
  if (p) {
    el("insConfirmarTexto").textContent = p.troca
      ? "A lista é de outra sequência. Trocar pela seleção desta?"
      : `A seleção pega ${p.trilhas.length} trilhas (${p.trilhas.join(", ")}) — `
        + `${p.itens.length} clipe(s). É isso?`;
  }
  previaDoInsert();   // a coleta pode ter trocado de sequência: o `%sequencia` mudou
  atualizarBotoesMagic();
  atualizarBotaoExport();
}

function atualizarBotoesMagic() {
  el("insBtnColetar").disabled = insOcupado;
  const pode = !insOcupado && insItens.length > 0 && el("insConfirmar").hidden && insNomeOk;
  for (const b of el("mlEnviarInsert").querySelectorAll("button[data-canal]")) {
    b.disabled = !(pode && b.dataset.conectado === "1");
  }
  el("insBtnExportar").disabled = !pode;
}

/* ── O nome do envio ──────────────────────────────────────────────────────────
   ⭐ O nome é do EDITOR (autor, 2026-09-25: "nomes são convenções da equipe, não é
   inteligente definirmos como regra do programa"). O painel oferece os campos (`%sequencia`,
   `%tipo`…) e alguns prefixos, e LEMBRA o último padrão de cada modo nesta máquina — a
   convenção da equipe fica depois do primeiro uso. A prévia é renderizada pelo serviço, com a
   mesma gramática que grava (`/export/nome`). */
const CHAVE_PADRAO = { timeline: "delapraca.nome.timeline", insert: "delapraca.nome.insert" };
let insNomeOk = true;
let insCamposDesenhados = false;
let insTimer = null;

/* Só um padrão de verdade é lembrado: um nome literal ("PRODA_CORTE_v2") guardado viraria o
   nome de TODA sequência seguinte. */
const temCampo = (p) => /%(\{?[a-z])/i.test(String(p || "").replace(/%%/g, ""));

function lerPadrao(modo) {
  try { const p = localStorage.getItem(CHAVE_PADRAO[modo]); return temCampo(p) ? p : ""; }
  catch (_) { return ""; }
}
function gravarPadrao(modo, p) {
  try { if (temCampo(p)) localStorage.setItem(CHAVE_PADRAO[modo], p); } catch (_) { /* conveniência */ }
}

function inserirNoCampo(campo, texto, noComeco) {
  if (noComeco) {
    if (!campo.value.startsWith(texto)) campo.value = texto + campo.value;
  } else {
    const ini = campo.selectionStart == null ? campo.value.length : campo.selectionStart;
    const fim = campo.selectionEnd == null ? campo.value.length : campo.selectionEnd;
    campo.value = campo.value.slice(0, ini) + texto + campo.value.slice(fim);
  }
  campo.focus();
  campo.dispatchEvent(new Event("input"));
}

/* ⚠️ `%tipo` vale o rótulo do CANAL pelo qual o insert vai, e isso só se sabe no clique. A
   prévia mostra o do primeiro canal conectado — e a dica diz que muda com o botão. */
function canalDaPrevia() {
  const c = mlCanais.find((x) => x.conectado) || mlCanais[0];
  return c ? c.setor : "";
}

function previaDoInsert() {
  clearTimeout(insTimer);
  insTimer = setTimeout(async () => {
    const alvo = el("insPrevia");
    try {
      const r = await post("/export/nome", { padrao: el("insNome").value, modo: "insert",
                                              tipo: canalDaPrevia() });
      if (!insCamposDesenhados && r.campos) {
        el("insCampos").innerHTML = r.campos.map((c) =>
          `<button type="button" data-campo="${escapar(c.campo)}" title="${escapar(c.valor)}">`
          + `${escapar(c.rotulo)}</button>`).join("");
        insCamposDesenhados = true;
      }
      insNomeOk = !!r.nome;
      alvo.className = "dica " + (r.nome ? "previa-ok" : "previa-er");
      const muda = temCampo(el("insNome").value) && /%\{?tipo/.test(el("insNome").value)
        && mlCanais.length > 1 ? " (o %tipo muda com o botão)" : "";
      alvo.textContent = r.nome ? "→ " + r.nome + muda : (r.erro || "");
    } catch (e) {
      insNomeOk = false;
      alvo.className = "dica previa-er";
      alvo.textContent = e.message;
    }
    atualizarBotoesMagic();
  }, 180);
}

async function carregarMagic() {
  try { pintarMagic(await api("/magic")); } catch (_) { /* sem serviço */ }
}

function mostrarModo(modo) {
  for (const b of el("exModo").children) b.classList.toggle("on", b.dataset.modo === modo);
  el("exModoInsert").hidden = modo !== "insert";
  el("exModoTimeline").hidden = modo !== "timeline";
  try { localStorage.setItem(CHAVE_MODO_EXPORT, modo); } catch (_) { /* preferência */ }
}

el("exModo").onclick = (ev) => {
  const b = ev.target.closest("button[data-modo]");
  if (b) mostrarModo(b.dataset.modo);
};

el("insNome").oninput = () => { gravarPadrao("insert", el("insNome").value); previaDoInsert(); };
el("insCampos").onclick = (ev) => {
  const b = ev.target.closest("button[data-campo]");
  if (b) inserirNoCampo(el("insNome"), `%{${b.dataset.campo}}`, false);
};
el("insPrefixos").onclick = (ev) => {
  const b = ev.target.closest("button[data-prefixo]");
  if (b) inserirNoCampo(el("insNome"), b.dataset.prefixo, true);
};
if (lerPadrao("insert")) el("insNome").value = lerPadrao("insert");
if (NLE === "mc") previaDoInsert();

/* A resposta da coleta fica no bloco do botão (memória `painel-sem-saltos-marcar-nao-e-carregar`): o `#msg`
   mora no fim da página e, medido no MC 24.6 (2026-10-29), a recusa "precisa do Media Composer 2025" caía
   fora da vista — o editor via o botão voltar a "Coletar seleção" e nada mais. */
function dizerNoInsert(texto, ok) {
  const m = el("insMsg");
  m.textContent = texto || "";
  m.className = "msg" + (texto ? (ok ? " ok" : " er") : "");
}

function dizerDecisao(d) {
  if (!d) return;
  // "adicionado" é boa notícia; o resto é informação que pede um gesto do editor.
  dizerNoInsert(d.texto || "", d.status === "adicionado");
  for (const a of (d.avisos || []).slice(0, 3)) console.warn("[magic link]", a);
}

el("insBtnColetar").onclick = async () => {
  insOcupado = true;
  atualizarBotoesMagic();
  el("insBtnColetar").textContent = "coletando…";
  dizerNoInsert("coletando a seleção — a timeline pisca e volta", true);
  try {
    const r = await post("/insert/coletar");
    pintarMagic(r);
    dizerDecisao(r.decisao);
  } catch (e) {
    dizerNoInsert(e.message, false);
  } finally {
    insOcupado = false;
    el("insBtnColetar").textContent = "Coletar seleção";
    atualizarBotoesMagic();
  }
};

async function responderConfirmacao(sim) {
  try {
    const r = await post("/insert/confirmar", { ok: sim });
    pintarMagic(r);
    dizerDecisao(r.decisao);
  } catch (e) { dizerNoInsert(e.message, false); }
}
el("insBtnOk").onclick = () => responderConfirmacao(true);
el("insBtnCancelarColeta").onclick = () => responderConfirmacao(false);

el("insLista").onclick = async (ev) => {
  const b = ev.target.closest("button[data-chave]");
  if (!b) return;
  try { pintarMagic(await post("/insert/remover", { chave: JSON.parse(b.dataset.chave) })); }
  catch (e) { dizer(e.message, false); }
};
el("insBtnLimpar").onclick = async () => {
  try { pintarMagic(await post("/insert/limpar")); dizer("lista limpa", true); }
  catch (e) { dizer(e.message, false); }
};

/* Enviar o insert por um canal, ou exportá-lo (`canal` nulo). Os dois mostram o mesmo
   resumo — e o que mudou na timeline depois da coleta, que NÃO foi. */
async function enviarInsert(canal) {
  const c = mlCanais.find((x) => x.setor === canal);
  insOcupado = true;
  atualizarBotoesMagic();
  dizer(canal ? "enviando o insert…" : "", true);
  el("insFeito").hidden = true;
  const corpo = { padrao: el("insNome").value, comentario: el("insComentario").value,
                  so_video: el("insSoVideo").checked };
  let r;
  try {
    r = canal ? await post("/magic/enviar", { ...corpo, tipo: "insert", canal })
              : await post("/insert/exportar", corpo);
  } catch (e) {
    dizer(e.message, false);
    insOcupado = false;
    atualizarBotoesMagic();
    return;
  }
  insOcupado = false;
  atualizarBotoesMagic();
  if (r.cancelado) { dizer(""); return; }
  let h = `<div class="bloco"><p class="bloco-titulo">${canal
      ? `enviado ${escapar(c ? c.para : canal)}` : "exportado"}</p>`
    + `<div class="caminho"><bdi>${escapar(r.arquivo || "")}</bdi></div>`
    + `<p class="dica">${escapar(r.clipes)} clipe(s).`
    + (canal ? ` Do outro lado: Procurar novos → Importar.` : "") + "</p>";
  // ⚠️ O que mudou na timeline depois da coleta NÃO foi: dizer, senão o editor acha que foi.
  if ((r.mudaram || []).length) {
    h += `<p class="aviso">${r.mudaram.length} clipe(s) da lista mudaram na timeline e `
      + "ficaram de fora — colete de novo: "
      + r.mudaram.map((i) => escapar(`${trilhaDe(i.track)} ${i.timeline_tc_in}`)).join(", ")
      + "</p>";
  }
  el("insFeito").innerHTML = h + "</div>";
  el("insFeito").hidden = false;
  dizer(canal ? "insert enviado" : "insert exportado", true);
}

el("mlEnviarInsert").onclick = (ev) => {
  const b = ev.target.closest("button[data-canal]");
  if (b && !b.disabled) enviarInsert(b.dataset.canal);
};
el("insBtnExportar").onclick = () => enviarInsert(null);

el("mlEnviarTimeline").onclick = async (ev) => {
  const b = ev.target.closest("button[data-canal]");
  if (!b || b.disabled) return;
  dizer("");
  el("exFeito").hidden = true;
  try {
    await post("/magic/enviar", { tipo: "timeline", canal: b.dataset.canal,
                                  padrao: el("exNome").value, comentario: el("exComentario").value,
                                  producao: el("exProducao").value });
    exRodando = true;
    atualizarBotaoExport();
    acompanharExport();
  } catch (e) { dizer(e.message, false); }
};

try { mostrarModo(localStorage.getItem(CHAVE_MODO_EXPORT) === "insert" ? "insert" : "timeline"); }
catch (_) { mostrarModo("timeline"); }
if (NLE === "mc") carregarMagic();

/* ── Receber: arquivo e Magic Link (De Lá Pra Cá › Importar timeline) ─────────────
   Dois caminhos embaixo do mesmo "Importar timeline":
     • o ARQUIVO (no Resolve: uma Carta ou uma bin do Avid) — `abrirArquivo`;
     • o MAGIC LINK, um bloco por CANAL que esta ilha usa (`GET /receber/caixa`): a edição vê
       "da Cor" e "do VFX"; a cor vê só "da Edição". Pendentes em cima; o que já entrou fica
       em "já importados", com o "De novo".
   O serviço transforma a Carta num DRT com a mídia desta máquina (`POST /receber/preparar`,
   que conta o andamento em `/receber/progresso`) e a CASCA do NLE a importa — só ela fala com
   a API do Resolve (`window.delapraca`, ver `plugins/resolve/casca/preload.js`). Depois do
   Trazer, `POST /receber/trazido` desce a Carta para `importado` do canal. No Media Composer
   as listas aparecem, mas trazer para o Avid é a entrega 4. */

/* A ponte do Resolve. Dentro do Resolve, a da casca (`window.delapraca`); na janela do app (organograma do app
   unificado, passo 1, 2026-10-18), o GÊMEO HTTP: as mesmas funções, com os mesmos nomes e retornos, que o serviço
   executa pela API externa (`resolve_externo.py`). Só as já portadas — o resto segue na casca, e quem chama já
   confere `typeof ponte().x === "function"`. */
const PONTE_APP = {
  projeto: () => post("/resolve/projeto", {}),
  timelines: () => post("/resolve/timelines", {}),
  midias: (pedido) => post("/resolve/midias", pedido),
  importar: (pedido) => post("/resolve/importar", pedido),
  fusion: (pedido) => post("/resolve/fusion", pedido),
  luts: (pedido) => post("/resolve/luts", pedido),
  estabilizar: (pedido) => post("/resolve/estabilizar", pedido),
  cor_mc: (pedido) => post("/resolve/cor_mc", pedido),
  compostos: (pedido) => post("/resolve/compostos", pedido),
  efeitosNoMonitor: (pedido) => post("/resolve/efeitosNoMonitor", pedido),
  conferirInicio: (pedido) => post("/resolve/conferirInicio", pedido),
  conferirQuadros: (pedido) => post("/resolve/conferirQuadros", pedido),
  conferirFim: (pedido) => post("/resolve/conferirFim", pedido),
};
/* No modo Premiere, a conferência pela referência com o MESMO contrato (o Premiere exporta PNG pela ponte; o serviço
   o converte no JPEG que a conferência espera — `premiere_copia.py`). */
const PONTE_PREMIERE = {
  conferirInicio: (pedido) => post("/premiere/conferirInicio", pedido),
  conferirQuadros: (pedido) => post("/premiere/conferirQuadros", pedido),
  conferirFim: (pedido) => post("/premiere/conferirFim", pedido),
};
function ponte() {
  return window.delapraca || (NLE === "resolve" ? PONTE_APP : NLE === "premiere" ? PONTE_PREMIERE : null);
}

/* Nomes das etapas, na ordem do serviço (`sessao_receber.ETAPAS`) mais a da casca. O peso
   é a fatia da barra, pelo MEDIDO (PRODA_CORTE, 877 clipes, 2026-09-25): mídia 207 arquivos
   em ~10 s, montar a timeline ~12 s, indexar ~0,2 s com o índice quente (~40 s frio). */
const ETAPAS_RC = {
  lendo:      { nome: "Lendo a Carta",                     peso: 2 },
  indexando:  { nome: "Procurando a mídia desta máquina",  peso: 13 },
  casando:    { nome: "Casando os clipes",                 peso: 3 },
  midia:      { nome: "Lendo os arquivos de mídia",        peso: 40 },
  montando:   { nome: "Montando a timeline",               peso: 31 },
  /* Mídia primeiro, timeline depois (2026-09-26): a casca importa os arquivos no Media Pool
     pelo import normal do Resolve, e o DRT se liga a eles. MEDIDO: 100 arquivos (BRAW, WAV,
     MOV) em 0,3 s; a timeline depois, 6,4 s. */
  trazendo:   { nome: "Trazendo a mídia para o Resolve",   peso: 1 },
  importando: { nome: NLE === "premiere" ? "Montando no Premiere" : `Importando no ${NLE === "resolve" ? "Resolve" : "programa"}`, peso: 10 },
  /* Projeto do Premiere (2026-10-03): máscara, blur e Basic 3D viram composição do Fusion nos
     clipes, pela casca, logo depois da importação. */
  fusion:     { nome: "Criando as composições do Fusion",  peso: 2 },
  luts:       { nome: "Aplicando a cor (LUTs e preto e branco)", peso: 1 },
  /* O Stabilize do Avid no estabilizador do Resolve (autor, 2026-10-24): analisa, troca a correção, aplica. */
  estabilizando: { nome: "Estabilizando como no Avid",     peso: 1 },
  compostos:  { nome: "Juntando os nests em Compound Clip", peso: 1 },
  /* A conferência pela referência (organograma de 2026-10-04): última etapa, se escolhida antes. */
  conferindo: { nome: "Conferindo pela referência",       peso: 0 },
  /* O Baselight (2026-11-22): job, bl-conform, a conferência de cada plano e os markers — tudo no serviço. */
  baselight:  { nome: "Conformando no Baselight",         peso: 10 },
};
/* As etapas em que o app USA o Resolve: o alerta "não mexa no Resolve" fica visível. Nas outras,
   só o app trabalha e o editor pode seguir usando o Resolve. */
const RESOLVE_OCUPADO = new Set(["trazendo", "importando", "fusion", "luts", "estabilizando", "compostos", "conferindo"]);
const ORDEM_RC = Object.keys(ETAPAS_RC);
/* Trazer para dentro do Media Composer ainda não existe (entrega 4). */
const TRAZ_AQUI = RECEBE;

let rcOcupado = false;
// o Comparar do Atualizar em curso (declarado aqui: o `irParaModo` do boot já o lê)
let atComparando = false;
let rcCaixa = { canais: [] };
let rcInicio = 0;

function rotuloOrigem(envio) {
  const app = String(envio.aplicativo || "").toLowerCase();
  if (app.includes("resolve")) return "RESOLVE";
  if (app.includes("premiere")) return "PREMIERE";
  return "AVID";
}

function quando(iso) {
  const m = /^(\d+)-(\d+)-(\d+)T(\d+):(\d+)/.exec(String(iso || ""));
  return m ? `${m[3]}/${m[2]} ${m[4]}:${m[5]}` : "";
}

/* O rótulo do tipo: "Timeline", ou "Insert COR" pelo tipo (`insert_cor` → COR). Setor novo
   entra sem mexer aqui. */
function rotuloTipo(tipo) {
  const t = String(tipo || "");
  if (t.indexOf("insert") !== 0) return "Timeline";
  return t.indexOf("insert_") === 0 ? `Insert ${t.slice(7).toUpperCase()}` : "Insert";
}

/* ── a tabela: filtro e ordem ──────────────────────────────────────────────────
   ⭐ Uma tabela só, com os dois sentidos de cada canal conectado (autor, 2026-09-25: sem papel,
   "uma tabela simples com colunas e linhas", ordenável pelo cabeçalho, com filtro). O filtro e
   a ordem são preferência de interface: ficam no localStorage, como a aba. */
const CHAVE_FILTRO_ML = "delapraca.magic.filtro";
const CHAVE_ORDEM_ML = "delapraca.magic.ordem";
let mlFiltro = "novos";
let mlOrdem = { campo: "enviado_em", desc: true };
try {
  mlFiltro = localStorage.getItem(CHAVE_FILTRO_ML) || "novos";
  const o = JSON.parse(localStorage.getItem(CHAVE_ORDEM_ML) || "null");
  if (o && typeof o.campo === "string") mlOrdem = { campo: o.campo, desc: !!o.desc };
} catch (_) { /* preferência: o padrão resolve */ }

function rotuloLado(lado) {
  return (rcCaixa.lados || {})[lado] || lado;
}

/* As opções do filtro vêm dos canais CONECTADOS: "Da Cor" só existe se o canal Cor existe. */
function opcoesDoFiltro() {
  const conectados = (rcCaixa.canais || []).filter((c) => c.conectado);
  const op = [["novos", "Novos (ainda não importados)"]];
  if (conectados.length) op.push(["de:edicao", `Da ${rotuloLado("edicao")}`]);
  for (const c of conectados) op.push([`de:${c.setor}`, `${c.de.charAt(0).toUpperCase()}${c.de.slice(1)}`]);
  op.push(["importados", "Já importados"], ["tudo", "Tudo"]);
  return op;
}

function passaNoFiltro(e) {
  if (mlFiltro === "tudo") return true;
  if (mlFiltro === "importados") return !!e.importado;
  if (mlFiltro.indexOf("de:") === 0) return !e.importado && e.de === mlFiltro.slice(3);
  return !e.importado;                               // "novos"
}

/* ── As colunas ─────────────────────────────────────────────────────────────────
   ⭐ Uma linha por envio, SEM quebra (autor, 2026-09-25: a linha não pode ocupar todo o
   espaço). O que antes empilhava embaixo do nome virou coluna. A tabela rola para o lado, as
   colunas se redimensionam pela divisa do cabeçalho, e só a do botão (Importar) fica fixa à
   direita. A largura de cada coluna é preferência de interface: fica no localStorage. */
const CHAVE_LARGURAS_ML = "delapraca.magic.larguras";
const LARGURA_MINIMA = 44;

function conteudoDe(e) {
  return String(e.tipo || "").indexOf("insert") === 0
    ? `${e.clipes_insert || 0} clipe(s)` : `${e.segmentos != null ? e.segmentos : "?"} eventos`;
}
function remetenteDe(e) {
  const rem = e.remetente || {};
  return [rem.maquina, rem.usuario ? `(${rem.usuario})` : ""].filter(Boolean).join(" ");
}

/* `ordem` é a chave de `valorDeOrdem`; `texto` é o conteúdo da célula (sempre texto puro).
   A ordem (autor, 2026-09-28): Data primeiro — "Enviado" era ambíguo (enviei eu ou enviaram
   para mim?) —, depois o Nome. "De" e "Para" saíram: o filtro já separa por canal. */
const COLUNAS = [
  { id: "enviado_em", rotulo: "Data",       largura: 96,  texto: (e) => quando(e.enviado_em) },
  { id: "nome",       rotulo: "Nome",       largura: 220, texto: (e) => e.nome || e.sequencia || "?" },
  { id: "tipo",       rotulo: "Tipo",       largura: 100, texto: (e) => rotuloTipo(e.tipo) },
  { id: "conteudo",   rotulo: "Conteúdo",   largura: 92,  texto: conteudoDe },
  { id: "sequencia",  rotulo: "Sequência",  largura: 160, texto: (e) => e.sequencia || "" },
  { id: "remetente",  rotulo: "Remetente",  largura: 170, texto: (e) => [rotuloOrigem(e), remetenteDe(e)].filter(Boolean).join(" · ") },
  { id: "comentario", rotulo: "Comentário", largura: 220, texto: (e) => e.comentario || "" },
  { id: "trazido_em", rotulo: "Importado",  largura: 96,  texto: (e) => quando(e.trazido_em) },
];
const LARGURA_ACAO = 96;

let mlLarguras = {};
try { mlLarguras = JSON.parse(localStorage.getItem(CHAVE_LARGURAS_ML) || "{}") || {}; }
catch (_) { mlLarguras = {}; }
const larguraDe = (c) => Math.max(LARGURA_MINIMA, Number(mlLarguras[c.id]) || c.largura);

function aplicarLarguras() {
  el("mlColunas").innerHTML = COLUNAS.map((c) => `<col style="width:${larguraDe(c)}px">`).join("")
    + `<col style="width:${LARGURA_ACAO}px">`;
  // ⚠️ Com `table-layout:fixed`, a tabela só passa da largura da caixa (e a caixa só rola) se
  // ela mesma tiver a soma das colunas como largura.
  el("mlTabela").style.width = `${COLUNAS.reduce((s, c) => s + larguraDe(c), 0) + LARGURA_ACAO}px`;
}

function desenharCabecalho() {
  el("mlCabecalho").innerHTML = COLUNAS.map((c) =>
    `<th data-ordem="${c.id}" class="col-${c.id}" title="clique para ordenar">${escapar(c.rotulo)}`
    + `<span class="alca" data-alca="${c.id}" title="arraste para mudar a largura"></span></th>`).join("")
    + `<th class="col-acao"><span class="oculto">ação</span></th>`;
  aplicarLarguras();
}

function valorDeOrdem(e, campo) {
  if (campo === "enviado_em" || campo === "trazido_em") return String(e[campo] || "");
  if (campo === "conteudo") {
    const n = String(e.tipo || "").indexOf("insert") === 0 ? e.clipes_insert : e.segmentos;
    return Number(n) || 0;
  }
  const c = COLUNAS.find((x) => x.id === campo);
  return String(c ? c.texto(e) : e[campo] || "").toLowerCase();
}

function desenharLinha(e) {
  const eInsert = String(e.tipo || "").indexOf("insert") === 0;
  const celulas = COLUNAS.map((c) => {
    const t = c.texto(e);
    if (c.id === "tipo") {
      return `<td class="col-tipo"><span class="origem ${eInsert ? (e.canal === "vfx" ? "vfx" : "cor") : "avid"}">`
        + `${escapar(t)}</span></td>`;
    }
    return `<td class="col-${c.id}" title="${escapar(t)}">${escapar(t)}</td>`;
  }).join("");
  // ⭐ Carregar, não importar (redesenho de 2026-10-05): o envio vai para o cartão do bloco 1, o editor
  // aponta os originais, e lá escolhe "Importar como nova" ou "Atualizar timeline".
  // ⭐ No Media Composer, o envio que trouxe a BIN anexa (Magic Link Avid → Avid, autor 2026-10-12) carrega como a
  // bin de fora: a sequência do envio já marcada, e o relink pela rota da bin. Sem a bin, ainda não.
  const botao = TRAZ_AQUI
    ? `<button class="sm ${e.importado ? "" : "primary"}" data-carregar="${escapar(e.id)}"
         ${rcOcupado ? "disabled" : ""}>Carregar</button>`
    : e.bin_anexa
      ? `<button class="sm ${e.importado ? "" : "primary"}" data-carregar-bin="${escapar(e.id)}"
           title="a bin do Avid veio junto: relinka pela bin">Carregar</button>`
      : `<button class="sm" disabled title="importar no Media Composer chega numa próxima etapa">`
        + `Importar <span class="em-breve">em breve</span></button>`;
  const carregado = rcCarga && rcCarga.envio && rcCarga.envio.id === e.id;
  return `<tr class="${[e.importado ? "importado" : "", carregado ? "carregado" : ""].join(" ").trim()}">`
    + `${celulas}<td class="col-acao">${botao}</td></tr>`;
}

function pintarTabela() {
  const filtro = el("mlFiltro");
  const ops = opcoesDoFiltro();
  if (!ops.some(([v]) => v === mlFiltro)) mlFiltro = "novos";
  filtro.innerHTML = ops.map(([v, r]) =>
    `<option value="${escapar(v)}"${v === mlFiltro ? " selected" : ""}>${escapar(r)}</option>`).join("");

  for (const th of el("mlTabela").querySelectorAll("th[data-ordem]")) {
    const ativo = th.dataset.ordem === mlOrdem.campo;
    th.classList.toggle("ordem-ativa", ativo);
    th.setAttribute("aria-sort", ativo ? (mlOrdem.desc ? "descending" : "ascending") : "none");
    th.dataset.seta = ativo ? (mlOrdem.desc ? "▾" : "▴") : "";
  }

  const conectados = (rcCaixa.canais || []).filter((c) => c.conectado);
  const linhas = (rcCaixa.envios || []).filter(passaNoFiltro);
  const sinal = mlOrdem.desc ? -1 : 1;
  linhas.sort((a, b) => {
    const x = valorDeOrdem(a, mlOrdem.campo);
    const y = valorDeOrdem(b, mlOrdem.campo);
    return (x < y ? -1 : x > y ? 1 : 0) * sinal
      || String(b.enviado_em || "").localeCompare(String(a.enviado_em || ""));
  });
  el("mlCorpo").innerHTML = linhas.map(desenharLinha).join("")
    || `<tr class="vazia"><td colspan="${COLUNAS.length + 1}">${conectados.length ? "nada aqui" : ""}</td></tr>`;
  el("mlTabela").parentElement.hidden = !conectados.length;
  el("mlBtnProcurar").disabled = rcOcupado || !conectados.length;
  const novos = (rcCaixa.envios || []).filter((e) => !e.importado).length;
  el("mlSelo").hidden = !novos;
  el("mlSelo").textContent = novos === 1 ? "1 novo" : `${novos} novos`;

  const problemas = (rcCaixa.canais || []).filter((c) => c.pasta && !c.conectado).map((c) => c.rotulo);
  const erros = (rcCaixa.canais || []).filter((c) => c.erro).map((c) => `${c.rotulo}: ${c.erro}`);
  const ruins = (rcCaixa.invalidas || []).length;
  el("mlDicaReceber").innerHTML = !conectados.length
    ? `Nenhum canal conectado. <button class="sm" data-ir-ajustes="1">Conectar em Ajustes</button>`
    : [problemas.length ? `canal ${problemas.join(" e ")} inacessível agora` : "",
       ...erros, ruins ? `${ruins} arquivo(s) ilegível(is)` : "",
       rcCaixa.cortado ? "pasta com arquivos demais — mostro só os mais recentes" : ""]
      .filter(Boolean).map(escapar).join(" · ");
}

async function procurarNovos(silencioso) {
  if (rcOcupado) return;
  try {
    rcCaixa = await api(`/receber/caixa?nle=${NLE}`);
    pintarTabela();
    if (!silencioso) {
      const n = (rcCaixa.envios || []).filter((e) => !e.importado).length;
      dizer(`${n} envio(s) novo(s)`, true);
    }
  } catch (e) { if (!silencioso) dizer(e.message, false); }
}

el("mlFiltro").onchange = () => {
  mlFiltro = el("mlFiltro").value;
  try { localStorage.setItem(CHAVE_FILTRO_ML, mlFiltro); } catch (_) { /* preferência */ }
  pintarTabela();
};

/* Redimensionar: arrastar a divisa (`.alca`) à direita de um cabeçalho. O clique que termina
   um arrasto NÃO ordena (senão toda mudança de largura reordenaria a tabela). */
let mlArrasto = null;
let mlAcabouDeArrastar = false;
el("mlTabela").querySelector("thead").addEventListener("mousedown", (ev) => {
  const alca = ev.target.closest("[data-alca]");
  if (!alca) return;
  ev.preventDefault();
  const c = COLUNAS.find((x) => x.id === alca.dataset.alca);
  mlArrasto = { c, x0: ev.clientX, w0: larguraDe(c) };
  document.body.classList.add("redimensionando");
});
document.addEventListener("mousemove", (ev) => {
  if (!mlArrasto) return;
  mlLarguras[mlArrasto.c.id] = Math.max(LARGURA_MINIMA, Math.round(mlArrasto.w0 + ev.clientX - mlArrasto.x0));
  aplicarLarguras();
});
document.addEventListener("mouseup", () => {
  if (!mlArrasto) return;
  mlArrasto = null;
  mlAcabouDeArrastar = true;
  setTimeout(() => { mlAcabouDeArrastar = false; }, 0);
  document.body.classList.remove("redimensionando");
  try { localStorage.setItem(CHAVE_LARGURAS_ML, JSON.stringify(mlLarguras)); } catch (_) { /* preferência */ }
});
/* Duplo clique na divisa volta a coluna à largura de fábrica. */
el("mlTabela").querySelector("thead").addEventListener("dblclick", (ev) => {
  const alca = ev.target.closest("[data-alca]");
  if (!alca) return;
  delete mlLarguras[alca.dataset.alca];
  aplicarLarguras();
  try { localStorage.setItem(CHAVE_LARGURAS_ML, JSON.stringify(mlLarguras)); } catch (_) { /* preferência */ }
});
el("mlTabela").querySelector("thead").onclick = (ev) => {
  if (mlAcabouDeArrastar || ev.target.closest("[data-alca]")) return;
  const th = ev.target.closest("th[data-ordem]");
  if (!th) return;
  const campo = th.dataset.ordem;
  // Clicar na coluna ativa inverte; numa coluna nova, as datas começam pela mais recente e o
  // texto em ordem alfabética.
  mlOrdem = campo === mlOrdem.campo ? { campo, desc: !mlOrdem.desc }
                                    : { campo, desc: campo === "enviado_em" || campo === "trazido_em" };
  try { localStorage.setItem(CHAVE_ORDEM_ML, JSON.stringify(mlOrdem)); } catch (_) { /* preferência */ }
  pintarTabela();
};
el("mlBtnProcurar").onclick = () => procurarNovos(false);
desenharCabecalho();

/* O que contar em cada etapa (a palavra depois de "12 de 207"). */
/* "montando": arquivos do media pool + planos da timeline, num contador só (o `build_drt`). */
const UNIDADE_RC = { casando: "arquivos", midia: "arquivos", trazendo: "arquivos", montando: "itens",
                     fusion: "composições", compostos: "grupos", conferindo: "quadros" };

/* A barra é a da ETAPA (pedido do autor, 2026-10-04: a barra do todo parava em ~30% na leitura dos
   arquivos e parecia faltar muito); o todo fica no "etapa 7 de 9". Sem contagem, a barra se move.
   Embaixo, o que está acontecendo: o arquivo lido (nome e pasta) ou o que está sendo escrito. */
function pintarAndamento(p) {
  const etapa = ETAPAS_RC[p.etapa] ? p.etapa : "lendo";
  const i = ORDEM_RC.indexOf(etapa);
  const conta = !!p.total;
  el("rcBarraFundo").classList.toggle("indeterminada", !conta);
  el("rcBarra").style.width = conta ? `${Math.round(100 * Math.min(1, p.feitos / p.total))}%` : "";
  el("rcEtapa").textContent = ETAPAS_RC[etapa].nome;
  el("rcEtapaN").textContent = `etapa ${i + 1} de ${ORDEM_RC.length}`;
  el("rcConta").textContent = (conta ? `${p.feitos} de ${p.total} ${UNIDADE_RC[etapa] || ""}`.trim() : "") +
    (p.sufixo ? ` · ${p.sufixo}` : "");
  el("rcAlerta").hidden = !RESOLVE_OCUPADO.has(etapa);
  el("rcAlerta").querySelector("b").textContent = `Não mexa no ${NLE === "premiere" ? "Premiere" : "Resolve"} até terminar`;
  el("rcAlertaTexto").textContent = NLE === "premiere"
    ? (etapa === "conferindo"
      ? "O De Lá Pra Cá está usando o Premiere: abre a sequência e anda a agulha para exportar cada quadro. Mexer agora pode estragar a conferência."
      : "O De Lá Pra Cá está usando o Premiere: importando a cópia no projeto aberto. Mexer agora pode cair no lugar errado.")
    : etapa === "conferindo"
    ? "O De Lá Pra Cá está usando o Resolve: troca de página, anda a agulha e liga e desliga trilhas. Mexer agora pode estragar a conferência."
    : "O De Lá Pra Cá está usando o Resolve. Mexer agora pode cair na timeline errada ou trocar a página no meio.";
  el("rcTempo").textContent = relogio(Math.round((Date.now() - rcInicio) / 1000));
  el("rcAtualOQue").textContent = p.detalhe || "";
  el("rcAtualNome").textContent = p.atual || "";
  // a pasta corta pelo COMEÇO (direction: rtl no CSS): o fim do caminho é o que identifica
  el("rcAtualPasta").textContent = p.pasta ? `\u200e${p.pasta}` : "";
  el("rcAtualPasta").title = p.pasta || "";
}

function mostrarTrazendo(sim, titulo) {
  rcOcupado = sim;
  el("rcTrazendo").hidden = !sim;
  if (!sim) el("rcAlerta").hidden = true;
  el("origemAAF").hidden = sim || modoOrigem === "atualizar";
  el("rcBtnAbrir").disabled = sim;
  if (titulo) el("rcTrazendoTitulo").textContent = titulo;
  el("rcBtnCancelar").disabled = false;
  pintarCarga();
}

async function trazer(id) {
  const envio = (rcCaixa.envios || []).find((e) => e.id === id);
  if (!envio) return;
  await trazerPedido({ id }, envio.nome || envio.sequencia || "", id);
}

/* O Trazer, venha de um canal (`{id}`) ou do arquivo (`{avulso, mob_id}`). `idEnvio` só
   existe no primeiro: é ele que desce a Carta para `importado` do canal. */
async function trazerPedido(pedido, titulo, idEnvio) {
  if (rcOcupado) return;
  if (NLE === "resolve" && !ponte()) { dizer("abra este painel pelo Resolve: Workspace › Workflow Integrations", false); return; }
  // ⭐ O projeto do Premiere passa ANTES pela análise e pela tela "antes de montar" (organograma de
  // 2026-10-02/03). O casamento é o dele (proxy → original), não a revisão do relink do Avid.
  if (rcAvulso && comAnalise(rcAvulso.tipo) && pedido.avulso === rcAvulso.chave && !pedido.analisado) {
    await analisarPrproj(pedido, titulo);
    return;
  }
  // ⭐ AAF, bin e Carta também passam pela tela "antes de montar" (organograma aprovado pelo autor em 2026-10-19: um
  // fluxo para todo protocolo): o resumo, a lista de mídias (por master, a tabela do MC), as decisões e o vídeo de
  // referência. Com pastas, o casamento é o do relink do Avid (ADR 0020); `originais: true` é a volta, já decidida.
  if (!pedido.originais && !pedido.analisado) {
    await analisarCarta(pedido, titulo, idEnvio);
    return;
  }
  // o Baselight: o job da produção × o job ABERTO na interface (etapa 4) — antes de começar
  let jobBl = "";
  if (BASELIGHT) {
    // ⭐ levando a cor de uma scene (etapa 5), o job é o DELA: a pergunta do job aberto não cabe
    jobBl = (el("rcBlAtualizar") || {}).value ? jobDoBaselight(titulo)
                                               : await escolherJobDoBaselight(jobDoBaselight(titulo));
    if (jobBl === null) return;
  }
  dizer("");
  el("rcFeito").hidden = true;
  rcInicio = Date.now();
  mostrarTrazendo(true, `Importando ${titulo}`);
  pintarAndamento({ etapa: "lendo" });
  const relogioRc = setInterval(async () => {
    try { const p = await api("/receber/progresso"); if (p.ativo) pintarAndamento(p); } catch (_) { /* segue */ }
  }, 500);

  let p;
  try {
    // A trilha de notas é uma opção do Import (Sinais do Import); desligada por padrão.
    const marcada = (id) => !!(el(id) && el(id).checked);
    const { analisado, ...base } = pedido;
    // o vídeo de referência e o som dele valem para todo protocolo; o resto é do projeto do Premiere
    const daRef = { referencia: rcRef.caminho || "", som_referencia: rcRef.som };
    const extra = rcAvulso && rcAvulso.tipo === "prproj"
      ? { ...daRef, audio: marcada("rcPrprojAudio"),
          compound: marcada("rcPrprojCompound"),
          // os IGNORADOS da lista de mídias (sem o marcador "REFAZER no original"; lembrados por projeto)
          ignorar: Array.from(rcIgnorados),
          // a escala de outra mídia que o editor ACEITOU ajustar (o serviço usa o fator da análise)
          reescalar: Object.fromEntries(rcEscalas.filter((x) => x.tipo === "escala" && rcEscalasAceitas.has(x.chave))
                                                 .map((x) => [x.caminho, x.fator])),
          proporcao: rcEscalas.filter((x) => x.tipo === "proporcao" && rcEscalasAceitas.has(x.chave))
                              .map((x) => x.caminho) } : daRef;
    p = await post("/receber/preparar", { ...base, ...extra, notas: marcada("rcNotas"),
                                          marcar: marcada("rcMarcar"), colorir: marcada("rcColorir"),
                                          ...(NLE === "premiere" ? { destino: "premiere", so_offline: soOffline(),
                                                                     nome_copia: (el("rcNomeCopia") || {}).value || "" } : {}),
                                          ...(BASELIGHT ? { destino: "baselight", job: jobBl,
                                                            markers: marcada("rcBlMarkers"),
                                                            titulos: marcada("rcBlTitulos"),
                                                            atualizar: (el("rcBlAtualizar") || {}).value || "" } : {}) });
  } catch (e) {
    clearInterval(relogioRc);
    mostrarTrazendo(false);
    dizer(e.corpo && e.corpo.cancelado ? "cancelado — nada foi importado" : e.message, !!(e.corpo && e.corpo.cancelado));
    return;
  }
  clearInterval(relogioRc);
  el("rcBtnCancelar").disabled = true;    // a importação no NLE não se interrompe
  if (BASELIGHT) { mostrarFeitoBaselight(p); return; }
  if (NLE === "premiere") {
    if (p.premiere_copia) await montarCopiaNoPremiere(p, idEnvio);
    else await montarNoPremiere(p, idEnvio);
    return;
  }
  let midias = null;
  if (ponte() && typeof ponte().midias === "function") {
    pintarAndamento({ etapa: "trazendo", feitos: 0, total: 0,
                      detalhe: `importando ${p.midias || 0} arquivos no Media Pool do Resolve, numa chamada só` });
    try { midias = await ponte().midias({ drt: p.drt, nome: p.nome }); }
    catch (e) { midias = { ok: false, erro: e.message }; }
    // Falhar aqui não impede a timeline: o DRT ainda traz a mídia pelas formas do writer.
  }
  pintarAndamento({ etapa: "importando",
                    detalhe: `o Resolve está lendo a timeline (${p.clipes || 0} planos) e religando a ` +
                             "mídia. Ele não informa o andamento: a barra se move até ele terminar." });

  let r;
  try {
    r = await ponte().importar({ drt: p.drt, pasta: p.pasta_no_resolve, nome: p.nome });
  } catch (e) {
    r = { ok: false, erro: e.message };
  }
  // As composições do Fusion (projeto do Premiere): a timeline já existe, então uma falha aqui é
  // registrada e mostrada, nunca desfaz a importação (memória "o trabalho caro não pode morrer
  // no acessório").
  let fusion = null;
  if (r.ok && (p.fusion || []).length) {
    pintarAndamento({ etapa: "fusion", detalhe: `montando ${p.fusion.length} ` +
                      (p.fusion.length === 1 ? "composição" : "composições") +
                      " do Fusion (máscara, desfoque, Basic 3D), uma por clipe, e conferindo cada uma" });
    if (typeof ponte().fusion === "function") {
      try { fusion = await ponte().fusion({ nome: r.nome, uid: r.uid || "", clipes: p.fusion }); }
      catch (e) { fusion = { ok: false, erro: e.message }; }
    } else {
      fusion = { ok: false, erro: "a casca instalada é antiga: atualize o De Lá Pra Cá" };
    }
  }
  // O COLOR CORRECTION do Avid (Sat + curva Master) nos 2 nós de cada clipe, EDITÁVEIS ("MC Master" → "MC Curva") —
  // ANTES das LUTs e da estabilização: o .drx troca a grade inteira do clipe. Falha = o clipe fica sem a cor, com aviso.
  let corMc = null;
  if (r.ok && (p.cor_mc || []).length) {
    pintarAndamento({ etapa: "cor", detalhe: `levando a cor editável a ${p.cor_mc.length} ` +
                      (p.cor_mc.length === 1 ? "clipe" : "clipes") +
                      " (nós da página Color: o Color Correction do Avid, a vinheta)" });
    if (typeof ponte().cor_mc === "function") {
      try { corMc = await ponte().cor_mc({ nome: r.nome, uid: r.uid || "", clipes: p.cor_mc }); }
      catch (e) { corMc = { ok: false, erro: e.message }; }
    } else {
      corMc = { ok: false, erro: "por enquanto só a janela do De Lá Pra Cá aplica a cor editável (Avid, vinheta)" };
    }
  }
  // As LUTs das camadas de ajuste do Premiere, no nó do Adjustment Clip — ANTES dos compounds (a
  // API não alcança clipe dentro de compound). Falha = o Adjustment Clip fica sem a LUT, com aviso.
  let luts = null;
  if (r.ok && (p.luts || []).length) {
    pintarAndamento({ etapa: "luts", detalhe: `aplicando a cor em ${p.luts.length} ` +
                      (p.luts.length === 1 ? "clipe" : "clipes") + " (LUT da camada de ajuste, preto e branco)" });
    if (typeof ponte().luts === "function") {
      try { luts = await ponte().luts({ nome: r.nome, uid: r.uid || "", clipes: p.luts }); }
      catch (e) { luts = { ok: false, erro: e.message }; }
    } else {
      luts = { ok: false, erro: "a casca instalada é antiga: atualize o De Lá Pra Cá" };
    }
  }
  // A ESTABILIZAÇÃO do Avid no estabilizador do Resolve (autor, 2026-10-24: chega pronta e ligada) — depois da cor (o
  // Body lido já a tem) e ANTES dos compounds. Falha = o clipe fica sem estabilizar, com aviso.
  let estab = null;
  if (r.ok && (p.estabilizar || []).length) {
    pintarAndamento({ etapa: "estabilizando", detalhe: `estabilizando ${p.estabilizar.length} ` +
                      (p.estabilizar.length === 1 ? "clipe" : "clipes") + " com o movimento que o Stabilize do Avid rastreou" });
    if (typeof ponte().estabilizar === "function") {
      try { estab = await ponte().estabilizar({ nome: r.nome, uid: r.uid || "", clipes: p.estabilizar }); }
      catch (e) { estab = { ok: false, erro: e.message }; }
    } else {
      estab = { ok: false, erro: "por enquanto só a janela do De Lá Pra Cá aplica a estabilização" };
    }
  }
  // Os nests do Premiere em Compound Clip, DEPOIS do Fusion (a API não alcança clipe dentro de
  // compound; a composição montada antes sobrevive — medido 2026-10-04). Falha = nest em trilhas.
  let compostos = null;
  if (r.ok && (p.compostos || []).length) {
    pintarAndamento({ etapa: "compostos", detalhe: `juntando ${p.compostos.length} ` +
                      (p.compostos.length === 1 ? "nest" : "nests") + " do Premiere em Compound Clip" });
    if (typeof ponte().compostos === "function") {
      try { compostos = await ponte().compostos({ nome: r.nome, uid: r.uid || "", grupos: p.compostos }); }
      catch (e) { compostos = { ok: false, erro: e.message }; }
    } else {
      compostos = { ok: false, erro: "a casca instalada é antiga: atualize o De Lá Pra Cá" };
    }
  }
  // Bypass de efeitos ligado no monitor: o Fusion some do monitor e de todo quadro exportado — quem
  // olhar condena o plano certo (2026-10-08). A conferência prova sozinha; sem ela, prova aqui.
  let bypass = null;
  const vaiConferir = r.ok && p.conferencia && el("rcPrprojConferir") && el("rcPrprojConferir").checked;
  if (fusion && fusion.ok && fusion.criadas && !vaiConferir && typeof ponte().efeitosNoMonitor === "function") {
    try {
      const b = await ponte().efeitosNoMonitor({ nome: r.nome, uid: r.uid || "", trilhaReferencia: p.trilha_referencia });
      bypass = b && b.ok ? b.ligado : null;
    } catch (_) { bypass = null; }
  }
  // A conferência pela referência, se o editor a escolheu ANTES de montar: a última etapa.
  const confCtx = r.ok && p.conferencia ? { id: p.conferencia.id, pontos: p.conferencia.pontos,
                                            segundos: p.conferencia.segundos, nome: r.nome || p.nome, uid: r.uid || "" } : null;
  let conf = null;
  if (confCtx && el("rcPrprojConferir") && el("rcPrprojConferir").checked) {
    conf = await conferir(confCtx, false);
  }
  rcConf = confCtx ? { ctx: confCtx, resultado: conf } : null;
  // a timeline do resultado: a conferência DEPOIS lê ela como estiver (`/conferencia/timeline`)
  rcFeitoTl = r.ok ? { nome: r.nome || p.nome, uid: r.uid || "", drt: p.drt || "" } : null;
  rcRefDepois = { caminho: "", som: true };
  rcConfAviso = "";
  let arquivo = {}, pendente = false;
  if (idEnvio) {
    const resp = await registrarTrazido({ id: idEnvio, ok: !!r.ok, detalhe: r.erro || "",
                                          timeline: r.ok ? { uid: r.uid || "", nome: r.nome || "" } : null });
    arquivo = resp || {};
    pendente = !resp && !!r.ok;
  }
  mostrarTrazendo(false);
  if (!r.ok) {
    // Primeiro a caixa, DEPOIS o erro: o `procurarNovos` escreve na mesma linha, e na ordem
    // inversa apagava o aviso (medido 2026-09-25 — o editor nunca viu o erro).
    await procurarNovos(true);
    dizer(r.erro || "o Resolve não importou a timeline", false);
    return;
  }

  const online = (p.clipes || 0) - (p.offline || 0);
  // Pré-importados + o áudio de 1–2 canais que veio do DRT e a casca moveu para a mesma pasta.
  const noPool = (midias && midias.ok ? midias.importadas || 0 : 0) + (r.movidas || 0);
  const avisos = (p.avisos || []).map((a) => `<div class="dica">⚠ ${escapar(a)}</div>`).join("");
  el("rcFeito").innerHTML =
    `<p class="previa-ok">✓ “${escapar(r.nome || p.nome)}” na pasta ${escapar(p.pasta_no_resolve)}</p>
     <div class="placar">` +
    // ⭐ De onde veio a mídia (ADR 0020): os originais em alta, a mídia do Avid ou nada.
    (p.nos_originais ? `<span class="pill ok">${p.nos_originais} nos originais</span>` : "") +
    (p.na_gerenciada ? `<span class="pill">${p.na_gerenciada} na mídia do Avid</span>` : "") +
    (!p.nos_originais && !p.na_gerenciada ? `<span class="pill ok">${online} com mídia</span>` : "") +
    (p.offline ? `<span class="pill warn">${p.offline} offline</span>` : "") +
    (p.titulos ? `<span class="pill ok">${p.titulos} ${p.titulos === 1 ? "título" : "títulos"}</span>` : "") +
    (p.notas ? `<span class="pill">${p.notas} ${p.notas === 1 ? "nota" : "notas"}</span>` : "") +
    (p.marcadores ? `<span class="pill warn">${p.marcadores} ${p.marcadores === 1 ? "marcador" : "marcadores"}</span>` : "") +
    (fusion && fusion.ok && fusion.criadas ? `<span class="pill ok">${fusion.criadas} ${fusion.criadas === 1 ? "composição" : "composições"} do Fusion</span>` : "") +
    (luts && luts.ok && luts.aplicadas ? `<span class="pill ok">${luts.aplicadas} ${luts.aplicadas === 1 ? "nó de cor" : "nós de cor"} (LUT, preto e branco)</span>` : "") +
    (estab && estab.ok && estab.aplicadas ? `<span class="pill ok">${estab.aplicadas} ${estab.aplicadas === 1 ? "estabilização" : "estabilizações"} do Avid</span>` : "") +
    (compostos && compostos.ok && compostos.criados ? `<span class="pill ok">${compostos.criados} Compound ${compostos.criados === 1 ? "Clip" : "Clips"}</span>` : "") +
    ((p.faltam || []).length ? `<span class="pill warn">${p.faltam.length} no proxy</span>` : "") +
    (p.ignorados ? `<span class="pill">${p.ignorados} ${p.ignorados === 1 ? "ignorado" : "ignorados"}</span>` : "") +
    (p.referencia ? `<span class="pill">referência: ${escapar(p.referencia)}</span>` : "") +
    (noPool ? `<span class="pill">${noPool} arquivos no Media Pool</span>` : "") +
    `<span class="pill">${relogio(Math.round((Date.now() - rcInicio) / 1000))}</span></div>` +
    (noPool ? `<div class="dica">A mídia está em De Lá Pra Cá › Mídia › ${escapar(r.nome || p.nome)}.</div>` : "") +
    (midias && !midias.ok ? `<p class="aviso">A mídia não foi importada antes (${escapar(midias.erro || "erro")}); a timeline usou o que o DRT declara.</p>` : "") +
    (midias && midias.faltaram ? `<p class="aviso">${midias.faltaram} arquivos o Resolve não importou; esses usam o que o DRT declara.</p>` : "") +
    (p.offline ? `<div class="dica">Os offline apontam para o original, com reel e TC: religue quando a mídia estiver nesta máquina.</div>` : "") +
    (fusion && !fusion.ok ? `<p class="aviso">As composições do Fusion não foram criadas (${escapar(fusion.erro || "erro")}). A timeline está completa; refaça máscara, blur e Basic 3D nos clipes com marcador amarelo.</p>` : "") +
    (fusion && fusion.ok && (fusion.clipes || []).some((c) => !c.ok) ? `<p class="aviso">Composições que não entraram: ${escapar(fusion.clipes.filter((c) => !c.ok).map((c) => `${c.arquivo} (${c.erro})`).join(" · "))}</p>` : "") +
    (bypass === true ? `<p class="aviso">O monitor do Resolve está com “Bypass Color Grades and Fusion Effects” ligado (o ícone vermelho riscado no canto do monitor, ou Shift+D): as composições do Fusion estão na timeline, mas não aparecem. Desligue antes de conferir os planos com máscara, desfoque ou Basic 3D.</p>` : "") +
    (luts && !luts.ok ? `<p class="aviso">A cor (LUT das camadas de ajuste, preto e branco) não foi aplicada (${escapar(luts.erro || "erro")}): os clipes estão na timeline sem ela (marcador amarelo).</p>` : "") +
    (luts && luts.ok && (luts.clipes || []).some((c) => !c.ok) ? `<p class="aviso">Clipes sem a cor: ${escapar(luts.clipes.filter((c) => !c.ok).map((c) => `trilha ${c.trilha} @${c.quadro} (${c.erro})`).join(" · "))}</p>` : "") +
    (corMc && !corMc.ok ? `<p class="aviso">O Color Correction do Avid não foi aplicado (${escapar(corMc.erro || "erro")}): os clipes com CC estão na timeline sem a cor (a nota diz qual era).</p>` : "") +
    (corMc && corMc.ok && (corMc.clipes || []).some((c) => !c.ok) ? `<p class="aviso">Clipes sem o Color Correction do Avid: ${escapar(corMc.clipes.filter((c) => !c.ok).map((c) => `${c.arquivo} na V${c.trilha} (${c.erro})`).join(" · "))}</p>` : "") +
    (estab && !estab.ok ? `<p class="aviso">A estabilização do Avid não foi aplicada (${escapar(estab.erro || "erro")}): os clipes com Stabilize estão sem estabilizar — use o estabilizador do Resolve neles.</p>` : "") +
    (estab && estab.ok && (estab.clipes || []).some((c) => !c.ok) ? `<p class="aviso">Clipes sem a estabilização do Avid (use o estabilizador do Resolve): ${escapar(estab.clipes.filter((c) => !c.ok).map((c) => `${c.arquivo} na V${c.trilha} (${c.erro})`).join(" · "))}</p>` : "") +
    (compostos && !compostos.ok ? `<p class="aviso">Os nests não viraram Compound Clip (${escapar(compostos.erro || "erro")}): entraram abertos em trilhas, com a imagem certa.</p>` : "") +
    (compostos && compostos.ok && (compostos.grupos || []).some((g) => !g.ok) ? `<p class="aviso">Nests que ficaram em trilhas: ${escapar(compostos.grupos.filter((g) => !g.ok).map((g) => `${g.nome} (${g.erro})`).join(" · "))}</p>` : "") +
    ((p.faltam || []).length ? `<div class="dica">Os planos no proxy têm marcador vermelho. Quando o original chegar, religue pela pasta.</div>` : "") +
    // Plano do Fusion que o serviço recusou (ex.: Crop com máscara depois de outro efeito): o clipe
    // só tem o marcador amarelo, então o aviso diz que é para REFAZER (revisão de código, 2026-10-03).
    ((p.fusion_recusadas || []).length ? `<p class="aviso">Sem composição do Fusion (refaça à mão): ${escapar(p.fusion_recusadas.join(" · "))}</p>` : "") +
    (arquivo.arquivado ? `<div class="dica">A Carta foi para “já importados”.</div>` : "") +
    (pendente ? `<div class="dica">⚠ ${escapar(AVISO_PENDENTE)}</div>` : "") +
    (arquivo.recusado ? `<div class="dica">⚠ ${escapar(avisoRecusado(arquivo.recusado))}</div>` : "") +
    (arquivo.aviso ? `<p class="aviso">${escapar(arquivo.aviso)}</p>` : "") +
    avisos + `<div id="rcConferencia"></div>`;
  pintarConferencia();
  el("rcFeito").hidden = false;
  await procurarNovos(true);
  dizer("");
}

/* ── Montar no Premiere (organograma do modo Premiere, decisão A, 2026-10-19) ─────────────────────────────────────
   O serviço devolveu o plano (`premiere_montagem`): a ponte importa a mídia na bin De Lá Pra Cá › Mídia › <nome>, cria
   a sequência e põe cada plano no lugar; o que ainda não traduz vira marcador no lugar. */
async function montarNoPremiere(p, idEnvio) {
  const pl = p.premiere || { planos: [], conta: {} };
  pintarAndamento({ etapa: "importando", detalhe: `montando ${pl.planos.length} planos no Premiere — a mídia entra na `
                    + "bin De Lá Pra Cá › Mídia; não mexa no Premiere até terminar" });
  let r;
  try { r = await post("/premiere/montar", { plano: pl }); }
  catch (e) { r = { ok: false, erro: e.message }; }
  let arquivo = {}, pendente = false;
  if (idEnvio) {
    const resp = await registrarTrazido({ id: idEnvio, ok: !!r.ok, detalhe: r.erro || "",
                                          timeline: r.ok ? { uid: r.id || "", nome: r.sequencia || "" } : null });
    arquivo = resp || {};
    pendente = !resp && !!r.ok;
  }
  mostrarTrazendo(false);
  if (!r.ok) {
    await procurarNovos(true);
    dizer(r.erro || "o Premiere não montou a timeline", false);
    return;
  }
  const c = pl.conta || {};
  const pill = (n, txt, cls) => (n ? `<span class="pill${cls ? " " + cls : ""}">${n} ${escapar(txt)}</span>` : "");
  el("rcFeito").innerHTML =
    `<p class="previa-ok">✓ “${escapar(r.sequencia)}” no Premiere, na bin De Lá Pra Cá › Mídia</p><div class="placar">` +
    `<span class="pill ok">${r.colocados} de ${r.planos} planos no lugar</span>` +
    (p.nos_originais ? pill(p.nos_originais, "nos originais", "ok") : "") +
    pill(c.offline, "offline (marcador)", "warn") + pill(c.velocidade, "com velocidade (a 100 %, marcador)", "warn") +
    pill(c.transicoes, "transições (marcador)", "warn") + pill(c.titulos, "títulos (marcador)", "warn") +
    pill(c.transicoes_audio, "transições de áudio viraram corte seco") +
    pill(c.audio_juntado, "pares de mono juntados") +
    pill(c.desligados, "vídeos desligados no Avid não entraram") +
    pill(c.audio_desligado, "sons desligados no Avid entraram desligados") +
    `<span class="pill">${relogio(Math.round((Date.now() - rcInicio) / 1000))}</span></div>` +
    (r.nfalhas ? `<p class="aviso">${r.nfalhas} ${r.nfalhas === 1 ? "plano não entrou" : "planos não entraram"}: ${escapar((r.falhas || []).join(" · "))}</p>` : "") +
    (r.sem_item ? `<p class="aviso">${r.sem_item} ${r.sem_item === 1 ? "arquivo o Premiere não importou" : "arquivos o Premiere não importou"}.</p>` : "") +
    (r.aviso || []).map((a) => `<p class="aviso">${escapar(a)}</p>`).join("") +
    `<div class="dica">Esta primeira versão monta os CORTES: velocidade, transições, títulos e efeitos ficam marcados no lugar
      para refazer. O que é do Media Composer e ainda não traduz aparece nos marcadores da sequência.</div>` +
    (arquivo.arquivado ? `<div class="dica">A Carta foi para “já importados”.</div>` : "") +
    (pendente ? `<div class="dica">⚠ ${escapar(AVISO_PENDENTE)}</div>` : "");
  el("rcFeito").hidden = false;
  await procurarNovos(true);
  dizer("");
}

/* ── Premiere → Premiere (organograma aprovado pelo autor em 2026-10-22) ──────────────────────────────────────────────
   O serviço gravou a cópia relinkada do projeto; a ponte a importa no projeto ABERTO (bin De Lá Pra Cá › <nome da
   cópia>) e o serviço confere o caminho de cada clipe contra a lista (o Premiere religa sozinho — o que ele ligou por
   conta própria ganha marcador). A original não muda. Depois, se marcada, a conferência pela referência. */
/* ── O Baselight (etapa 2, 2026-11-22): o job da produção e o resumo do conform ─────────────────────────────────────
   O job: o que o colorista escreveu (ou escolheu na lista dos jobs do Baselight); vazio = o último usado nesta máquina;
   nada = o nome da timeline. Lembrado para a próxima (um job por produção: a próxima timeline cai no mesmo). */
const CHAVE_JOB_BL = "delapraca.baselight.job";
function jobDoBaselight(titulo) {
  const escrito = ((el("rcBlJob") || {}).value || "").trim();
  const job = escrito || localStorage.getItem(CHAVE_JOB_BL) || titulo || "Ciclo Assist";
  try { localStorage.setItem(CHAVE_JOB_BL, job); } catch (_) { /* segue */ }
  return job;
}

/* A pergunta da etapa 4 (autor, 2026-11-22): o colorista importando com uma scene ABERTA no Baselight, e a produção
   não é o job dela → "importar no job aberto ou no da produção?", com "não perguntar novamente" (lembra a escolha nesta
   máquina). Sem scene aberta, ou o mesmo job, não pergunta. Devolve o job, ou `null` (fechou sem escolher). */
const CHAVE_SEM_PERGUNTA_BL = "delapraca.baselight.semPerguntarJob";
async function escolherJobDoBaselight(meu) {
  let r;
  try { r = await api("/baselight/jobs"); } catch (_) { return meu; }
  const aberto = r && r.aberto;
  if (!aberto || !aberto.job || aberto.job === meu) return meu;
  const lembrado = localStorage.getItem(CHAVE_SEM_PERGUNTA_BL);
  if (lembrado === "aberto") return aberto.job;
  if (lembrado === "meu") return meu;
  el("jobBlTexto").textContent = `O Baselight está com o job “${aberto.job}” aberto (scene “${aberto.scene}”). ` +
    `A produção desta timeline é “${meu}”${(r.jobs || []).includes(meu) ? "" : " — um job novo, que será criado"}. ` +
    "A timeline entra numa scene nova, nunca por cima de outra.";
  el("jobBlAberto").textContent = `No job aberto (${aberto.job})`;
  el("jobBlMeu").textContent = `Em “${meu}”`;
  el("jobBlNaoPerguntar").checked = false;
  el("jobBl").hidden = false;
  el("jobBlMeu").focus();
  return new Promise((fim) => {
    const fechar = (qual) => {
      el("jobBl").hidden = true;
      el("jobBlAberto").onclick = el("jobBlMeu").onclick = el("jobBl").onkeydown = null;
      if (qual && el("jobBlNaoPerguntar").checked) {
        try { localStorage.setItem(CHAVE_SEM_PERGUNTA_BL, qual); } catch (_) { /* segue */ }
      }
      fim(qual === "aberto" ? aberto.job : qual === "meu" ? meu : null);
    };
    el("jobBlAberto").onclick = () => fechar("aberto");
    el("jobBlMeu").onclick = () => fechar("meu");
    el("jobBl").onkeydown = (ev) => { if (ev.key === "Escape") fechar(null); };
  });
}

async function carregarJobsDoBaselight() {
  if (!BASELIGHT) return;
  if (el("rcBlJob") && !el("rcBlJob").value) el("rcBlJob").value = localStorage.getItem(CHAVE_JOB_BL) || "";
  let r;
  try { r = await api("/baselight/jobs"); } catch (_) { return; }
  if (!r.disponivel) { el("rcBlJobInfo").textContent = r.motivo; return; }
  el("rcBlJobs").innerHTML = r.jobs.map((j) => `<option value="${escapar(j)}"></option>`).join("");
  el("rcBlJobInfo").textContent = `um job por produção (${r.jobs.length} no Baselight): cada timeline entra numa scene ` +
    "nova dele, nunca por cima de outra; um nome novo cria o job";
  carregarScenesDoBaselight();
}

/* As scenes do job escrito, para "Levar a cor de uma scene" (atualizar corte, etapa 5). Trocar o job zera a escolha. */
async function carregarScenesDoBaselight() {
  const sel = el("rcBlAtualizar");
  if (!BASELIGHT || !sel) return;
  const job = ((el("rcBlJob") || {}).value || "").trim();
  const antes = sel.value;
  let r = { scenes: [] };
  if (job) { try { r = await api("/baselight/scenes?job=" + encodeURIComponent(job)); } catch (_) { /* segue */ } }
  sel.innerHTML = `<option value="">não — timeline nova, sem cor</option>` +
    (r.scenes || []).map((s) => `<option value="${escapar(s)}">${escapar(s)}</option>`).join("");
  sel.value = (r.scenes || []).includes(antes) ? antes : "";
}
if (el("rcBlJob")) el("rcBlJob").addEventListener("change", carregarScenesDoBaselight);
carregarJobsDoBaselight();

/* O pedido da CARTA ABERTA ("Conformar com De Lá Pra Cá", etapa 3): o serviço o entrega UMA vez; a timeline entra
   carregada e o job vem junto. Falta o colorista apontar as pastas dos originais (e o vid ref) e montar. */
async function pegarPedidoDaCarta() {
  if (!BASELIGHT || rcOcupado) return;
  let r;
  try { r = await post("/receber/a-conformar", {}); } catch (_) { return; }
  if (!r || !r.xml) return;
  await abrirArquivo(r.xml);
  if (r.job && el("rcBlJob")) el("rcBlJob").value = r.job;   // DEPOIS: o carregar põe o nome do arquivo (xmeml) no job
  dizer(`“${r.nome || "a timeline"}” chegou da Carta Aberta — ` +
        (pastas.length ? "confira as pastas dos originais e leia a timeline" : "aponte as pastas dos originais"), true);
}
if (BASELIGHT) { pegarPedidoDaCarta(); setInterval(pegarPedidoDaCarta, 3000); }

const ESTADO_BL = { offline_de_proposito: "offline de propósito", sem_midia: "o Baselight não achou",
                    arquivo_diferente: "arquivo trocado pelo Baselight", fora_do_ponto: "fora do ponto" };

function mostrarFeitoBaselight(p) {
  const b = p.baselight || {};
  const c = b.contagem || {};
  const pill = (n, txt, cls) => (n ? `<span class="pill${cls ? " " + cls : ""}">${n} ${escapar(txt)}</span>` : "");
  const probs = b.problemas || [];
  mostrarTrazendo(false);
  el("rcFeito").innerHTML =
    `<p class="previa-ok">✓ “${escapar(b.scene || p.nome)}” no Baselight, no job ${escapar(b.job || "")}` +
    `${b.job_criado ? " (criado agora)" : ""}</p>` +
    `<div class="placar"><span class="pill ok">${c.ok || 0} de ${b.planos || 0} planos certos</span>` +
    pill(b.trocados, b.trocados === 1 ? "plano corrigido (o Baselight tinha casado outro arquivo)"
                                       : "planos corrigidos (o Baselight tinha casado outro arquivo)", "ok") +
    pill(probs.length, probs.length === 1 ? "plano a conferir" : "planos a conferir", "warn") +
    pill(b.markers, b.markers === 1 ? "marker [Ciclo]" : "markers [Ciclo]", "warn") +
    pill((b.estabilizacao || {}).traduzidos, (b.estabilizacao || {}).traduzidos === 1 ? "estabilização traduzida (tracker nativo)"
                                                     : "estabilizações traduzidas (tracker nativo)", "ok") +
    pill(((b.estabilizacao || {}).falhas || []).length, "estabilização não aplicada", "warn") +
    pill((b.efeitos || {}).velocidade, (b.efeitos || {}).velocidade === 1 ? "plano com a velocidade da montagem (Retime)"
                                         : "planos com a velocidade da montagem (Retime)", "ok") +
    pill((b.efeitos || {}).motion, (b.efeitos || {}).motion === 1 ? "plano com o Motion da montagem (Transform)"
                                     : "planos com o Motion da montagem (Transform)", "ok") +
    pill(((b.efeitos || {}).falhas || []).length + ((b.efeitos || {}).sem_par || []).length,
         "plano sem a velocidade/Motion da montagem", "warn") +
    pill((b.mascaras || {}).traduzidas, (b.mascaras || {}).traduzidas === 1 ? "máscara de opacidade (composição)"
                                          : "máscaras de opacidade (composição)", "ok") +
    pill(((b.mascaras || {}).falhas || []).length, "máscara não aplicada", "warn") +
    ((b.titulos || {}).titulos ? pill(b.titulos.titulos, b.titulos.titulos === 1 ? "título trazido (camada Text)"
                                                       : "títulos trazidos (camada Text)", "ok")
      : pill(p.titulos, p.titulos === 1 ? "título da montagem num marker (o texto não vai à cor)"
                                        : "títulos da montagem em markers (o texto não vai à cor)", "")) +
    pill(p.nao_traduzido, "com efeito que não foi (velocidade, reenquadramento)", "warn") +
    `<span class="pill">${relogio(Math.round((Date.now() - rcInicio) / 1000))}</span></div>` +
    `<div class="dica">Cada plano foi conferido no Baselight: o arquivo, o 1º e o último quadro visível. A scene é ` +
    `nova — nenhuma outra do job foi tocada.</div>` +
    ((b.estabilizacao || {}).traduzidos ? `<div class="dica">A estabilização do Avid foi ao tracker do Baselight com o ` +
      `rastreio do MC: o Motion fica em 0 e o movimento lento vai nos keyframes de posição do Transform (o marker do ` +
      `plano explica ao colorista).</div>` : "") +
    ((b.efeitos || {}).traduzidos ? `<div class="dica">A velocidade da montagem foi ao Retime (Time × Time, um ` +
      `keyframe por quadro) e o Motion à camada Transform de cada plano — o mesmo quadro que a montagem mostra.</div>` : "") +
    [...((b.efeitos || {}).falhas || []), ...((b.efeitos || {}).sem_par || [])].map((x) => `<p class="aviso">` +
      `<b>velocidade/Motion não aplicados</b> · ${escapar(x.clip || "")} (quadro ${x.quadro})` +
      `${x.motivo ? ": " + escapar(x.motivo) : ": o plano não foi achado na scene"}</p>`).join("") +
    ((b.titulos || {}).erro ? `<p class="aviso"><b>os títulos não vieram</b> · ${escapar(b.titulos.erro)} — a scene ` +
      `foi entregue sem eles</p>` : "") +
    ((b.mascaras || {}).falhas || []).map((x) => `<p class="aviso"><b>máscara não aplicada</b> · ` +
      `${escapar(x.clip || "")} (quadro ${x.quadro}): ${escapar(x.motivo)}</p>`).join("") +
    ((b.estabilizacao || {}).falhas || []).map((x) => `<p class="aviso"><b>estabilização não aplicada</b> · ` +
      `${escapar(x.clip || "")} (quadro ${x.quadro}): ${escapar(x.motivo)}</p>`).join("") +
    probs.map((x) => `<p class="aviso"><b>${escapar(ESTADO_BL[x.estado] || x.estado)}</b> · ` +
      `${escapar(x.arquivo)} (quadro ${x.quadro}): ${escapar(x.motivo.replace(/^offline de propósito:\s*/, ""))}</p>`).join("") +
    resumoDaCorBaselight(b.atualizar);
  el("rcFeito").hidden = false;
  dizer("");
}

/* O "atualizar corte" (etapa 5): o que veio da scene do colorista, plano a plano. */
function resumoDaCorBaselight(a) {
  if (!a) return "";
  const planos = a.planos || [];
  const conta = (est) => planos.filter((x) => x.estado === est).length;
  const pill = (n, txt, cls) => (n ? `<span class="pill${cls ? " " + cls : ""}">${n} ${escapar(txt)}</span>` : "");
  const semCor = planos.filter((x) => x.estado === "sem cor" || x.estado === "limpa");
  const movidas = a.marcas_movidas || [], perdidas = a.marcas_perdidas || [];
  return `<p class="previa-ok">A cor de “${escapar(a.colorista)}”: ${a.conferidos} de ${a.de} planos conferidos</p>` +
    `<div class="placar">` +
    pill(conta("cor do colorista") + conta("corrigida"), "com a cor do colorista", "ok") +
    pill(conta("corrigida") + conta("limpa"), "corrigidos pela conferência (o Multi-Paste tinha errado)", "ok") +
    pill((a.divididos || []).length, "divididos como o colorista dividiu", "ok") +
    pill(conta("só o look"), conta("só o look") === 1 ? "plano novo com só o look da cena" : "planos novos com só o look da cena", "ok") +
    pill(semCor.length, semCor.length === 1 ? "plano sem cor" : "planos sem cor", "warn") +
    pill(movidas.length, movidas.length === 1 ? "marker do colorista levado" : "markers do colorista levados", "ok") +
    pill(perdidas.length, perdidas.length === 1 ? "marker do colorista ficou para trás" : "markers do colorista ficaram para trás", "warn") +
    pill((a.grupos || []).length, (a.grupos || []).length === 1 ? "grupo do colorista levado" : "grupos do colorista levados", "ok") +
    `</div>` +
    (a.grupos || []).filter((g) => (g.fora || []).length || (g.novos || []).length || g.conferido === false).map((g) =>
      `<p class="aviso"><b>grupo “${escapar(g.nome)}”</b> · ${g.planos.length} plano(s) na scene nova` +
      `${(g.novos || []).length ? "; " + g.novos.length + " novo(s) ou trocado(s) entraram no lugar de quem estava nele " +
        "(quadros " + g.novos.join(", ") + ")" : ""}` +
      `${g.fora.length ? "; " + g.fora.length + " da scene do colorista não chegaram (retirados ou trocados — quadros " +
        g.fora.join(", ") + " da scene dele)" : ""}${g.conferido === false ? "; a leitura não confere" : ""}</p>`).join("") +
    (a.erro_multipaste ? `<p class="aviso"><b>o Multi-Paste recusou</b> · ${escapar(a.erro_multipaste)} — a cor veio ` +
                         "só pela cópia do Ciclo</p>" : "") +
    semCor.map((x) => `<p class="aviso"><b>sem cor</b> · ${escapar(x.arquivo)} (quadro ${x.inicio}): ${escapar(x.motivo)}` +
                      `${x.aviso ? " — " + escapar(x.aviso) : ""}</p>`).join("") +
    planos.filter((x) => x.estado === "só o look").map((x) => `<p class="aviso"><b>só o look</b> · ${escapar(x.arquivo)} ` +
      `(quadro ${x.inicio}): ${escapar(x.motivo)} — recebeu a faixa de cor da cena; a cor do plano é do colorista</p>`).join("") +
    planos.filter((x) => x.aviso && x.estado !== "sem cor").map((x) =>
      `<p class="aviso"><b>conferir</b> · ${escapar(x.arquivo)} (quadro ${x.inicio}): ${escapar(x.aviso)}</p>`).join("") +
    perdidas.map((x) => `<p class="aviso"><b>marker do colorista</b> · ` +
                        (x.nota ? `“${escapar(x.nota)}”` : `sem nota (${escapar(x.categoria || "marca")})`) +
                        ` (quadro ${x.quadro} da scene ` +
                        `dele): ${escapar(x.motivo)}</p>`).join("");
}

async function montarCopiaNoPremiere(p, idEnvio) {
  const nome = (p.premiere_copia || {}).nome || p.nome;
  pintarAndamento({ etapa: "importando", detalhe: `criando “${nome}” no projeto aberto do Premiere — a sequência original `
                    + "não muda; não mexa no Premiere até terminar" });
  let r;
  try { r = await post("/premiere/copia", { id: p.premiere_copia.id }); }
  catch (e) { r = { ok: false, erro: e.message }; }
  const confCtx = r.ok && p.conferencia ? { id: p.conferencia.id, pontos: p.conferencia.pontos,
                                            segundos: p.conferencia.segundos, nome: r.sequencia || nome, uid: r.id } : null;
  let conf = null;
  if (confCtx && el("rcPrprojConferir") && el("rcPrprojConferir").checked) conf = await conferir(confCtx, false);
  rcConf = confCtx ? { ctx: confCtx, resultado: conf } : null;
  rcFeitoTl = r.ok ? { nome: r.sequencia || nome, uid: r.id || "", drt: "" } : null;
  rcRefDepois = { caminho: "", som: true };
  rcConfAviso = "";
  let arquivo = {}, pendente = false;
  if (idEnvio) {
    const resp = await registrarTrazido({ id: idEnvio, ok: !!r.ok, detalhe: r.erro || "",
                                          timeline: r.ok ? { uid: r.id || "", nome: r.sequencia || "" } : null });
    arquivo = resp || {};
    pendente = !resp && !!r.ok;
  }
  mostrarTrazendo(false);
  if (!r.ok) {
    await procurarNovos(true);
    dizer(r.erro || "o Premiere não criou a cópia", false);
    return;
  }
  const religados = r.religados_pelo_premiere || [], offline = r.offline || [];
  const pill = (n, txt, cls) => (n ? `<span class="pill${cls ? " " + cls : ""}">${n} ${escapar(txt)}</span>` : "");
  el("rcFeito").innerHTML =
    `<p class="previa-ok">✓ “${escapar(r.sequencia || nome)}” no Premiere, na bin ${escapar(r.bin || "De Lá Pra Cá")}</p>` +
    `<div class="placar"><span class="pill ok">${r.no_lugar} de ${r.clipes} clipes nos arquivos da lista</span>` +
    (p.nos_originais ? pill(p.nos_originais, "planos nos originais", "ok") : "") +
    pill(religados.length, religados.length === 1 ? "religado pelo Premiere (conferir)" : "religados pelo Premiere (conferir)", "warn") +
    pill(offline.length, "offline", "warn") +
    pill(r.escalas, r.escalas === 1 ? "escala corrigida (outro raster)" : "escalas corrigidas (outro raster)", "ok") +
    pill(r.marcadores, r.marcadores === 1 ? "marcador" : "marcadores", "warn") +
    pill(r.sequencias > 1 ? r.sequencias - 1 : 0, r.sequencias === 2 ? "sequência aninhada" : "sequências aninhadas") +
    (p.referencia ? `<span class="pill">referência: ${escapar(p.referencia)}</span>` : "") +
    `<span class="pill">${relogio(Math.round((Date.now() - rcInicio) / 1000))}</span></div>` +
    `<div class="dica">A sequência original não mudou. A cópia aponta para os arquivos da lista de mídias.</div>` +
    (religados.length ? `<p class="aviso">O Premiere ligou ${religados.length === 1 ? "este arquivo" : "estes arquivos"} por conta
      própria (o projeto apontava para outro lugar): ${escapar(religados.map(nomeDoCaminho).join(" · "))}. Confira o marcador amarelo.</p>` : "") +
    (offline.length ? `<p class="aviso">Offline na cópia: ${escapar(offline.join(" · "))}. Religue no Premiere quando a mídia estiver aqui.</p>` : "") +
    ((p.sem_escala || []).length ? `<p class="aviso">Escala a conferir (outra proporção): ${escapar(p.sem_escala.join(" · "))}.</p>` : "") +
    (arquivo.arquivado ? `<div class="dica">A Carta foi para “já importados”.</div>` : "") +
    (pendente ? `<div class="dica">⚠ ${escapar(AVISO_PENDENTE)}</div>` : "") +
    `<div id="rcConferencia"></div>`;
  pintarConferencia();
  el("rcFeito").hidden = false;
  await procurarNovos(true);
  dizer("");
}

/* ── A conferência pela referência (organograma aprovado pelo autor, 2026-10-04) ──────────────
   Antes (caixa na tela "antes de montar": a última etapa do Importar) ou depois (o botão no
   resultado). O painel conduz em lotes: a casca exporta os quadros, o serviço compara em segundo
   plano. Cancelar vale entre um lote e outro (segundos); o que já foi conferido fica marcado, e
   "continuar de onde parou" usa os quadros guardados. */
let rcConf = null;            // {ctx: {id, pontos, segundos, nome, uid}, resultado}
let rcFeitoTl = null;         // {nome, uid, drt}: a timeline que acabou de entrar
let rcRefDepois = { caminho: "", som: true };   // o vídeo indicado DEPOIS de montar, e se o som vem
let rcConfAviso = "";         // por que a última tentativa não começou (sem referência, trilha dividida…)
let rcConferindo = false;
let rcCancelarConf = false;
const LOTE_CONF = 6;

async function conferir(ctx, doComeco) {
  if (!ponte() || typeof ponte().conferirInicio !== "function") {
    return { erro: "a casca instalada é antiga: atualize o De Lá Pra Cá" };
  }
  rcConferindo = true;
  rcCancelarConf = false;
  el("rcBtnCancelar").disabled = false;
  const t0 = Date.now();
  let ini, iniciou = false, cancelado = false, erro = "";
  try {
    ini = await post("/conferencia/iniciar", { id: ctx.id, do_comeco: !!doComeco });
    pintarAndamento({ etapa: "conferindo", feitos: ini.comparados || 0, total: ini.total,
                      detalhe: NLE === "premiere" ? "abrindo a sequência no Premiere"
                        : "preparando o Resolve: desligando a referência e indo para a página Color" });
    const s = await ponte().conferirInicio({ nome: ctx.nome, uid: ctx.uid, trilhaReferencia: ini.trilha_referencia });
    if (!s || !s.ok) throw new Error((s && s.erro) || `o ${NLE === "premiere" ? "Premiere" : "Resolve"} não começou a conferência`);
    iniciou = true;
    const base = ini.total - ini.faltam.length;
    let feitos = 0, ruins = ini.nao_conferem || 0;
    for (let i = 0; i < ini.faltam.length; i += LOTE_CONF) {
      if (rcCancelarConf) { cancelado = true; break; }
      const lote = ini.faltam.slice(i, i + LOTE_CONF);
      const ult = lote[lote.length - 1];
      const ritmo = feitos ? (Date.now() - t0) / feitos : 500;
      const resta = Math.max(0, ini.faltam.length - feitos) * ritmo / 1000;
      pintarAndamento({ etapa: "conferindo", feitos: base + feitos, total: ini.total,
                        sufixo: `${ruins} ${ruins === 1 ? "não confere" : "não conferem"} · faltam ~${duracaoAprox(resta)}`,
                        detalhe: `exportando do ${NLE === "premiere" ? "Premiere" : "Resolve"} e comparando com o vídeo de referência`,
                        atual: `${ult.tc} · ${ult.plano || ""} (V${ult.trilha || "?"}, ${ult.ponta || ""})` });
      const q = await ponte().conferirQuadros({ pontos: lote });
      if (!q || !q.ok) throw new Error((q && q.erro) || `o ${NLE === "premiere" ? "Premiere" : "Resolve"} não exportou os quadros`);
      await post("/conferencia/quadros", { id: ctx.id, quadros: lote.map((x) => x.quadro) });
      feitos += lote.length;
      if (feitos % (LOTE_CONF * 5) === 0) {
        try { ruins = (await post("/conferencia/estado", { id: ctx.id })).nao_conferem || 0; } catch (_) { /* segue */ }
      }
    }
  } catch (e) {
    erro = e.message || String(e);
  }
  // As comparações que ainda estão na fila terminam (o Resolve já está livre do export).
  let estado = null;
  for (let k = 0; k < 600; k++) {
    try { estado = await post("/conferencia/estado", { id: ctx.id }); } catch (_) { break; }
    if (!estado.na_fila) break;
    pintarAndamento({ etapa: "conferindo", feitos: estado.comparados, total: estado.total,
                      detalhe: "terminando as últimas comparações" });
    await new Promise((ok) => setTimeout(ok, 500));
  }
  // Marcadores e devolução — SEMPRE que a casca começou (também ao cancelar ou com erro).
  let marcadores = 0, erroMarcas = "";
  if (iniciou) {
    let m = { marcas: [], cor: "Purple", dado: "dlpc-conferencia" };
    try { m = await post("/conferencia/marcas", { id: ctx.id }); } catch (_) { /* devolve assim mesmo */ }
    try {
      const f = (await ponte().conferirFim(m)) || {};
      marcadores = f.marcadores || 0;
      if (!f.ok) erroMarcas = f.erro || "a casca não respondeu";
    } catch (e) { erroMarcas = e.message || String(e); }
  }
  rcConferindo = false;
  el("rcBtnCancelar").disabled = true;
  return { estado, cancelado, erro, marcadores, erroMarcas, segundos: Math.round((Date.now() - t0) / 1000) };
}

/* O bloco da conferência no resultado do Importar: o botão (DEPOIS), o placar (feita), ou o
   cancelado com "continuar de onde parou". */
function pintarConferencia() {
  const c = el("rcConferencia");
  if (!c) return;
  const aviso = rcConfAviso ? `<p class="aviso">${escapar(rcConfAviso)}</p>` : "";
  if (!rcConf) {
    if (!rcFeitoTl || NLE === "premiere") { c.innerHTML = ""; return; }
    c.innerHTML = semReferenciaHtml(aviso);
    pintarRefDepois();
    return;
  }
  const { resultado } = rcConf;
  const est = resultado && resultado.estado;
  if (!resultado) {
    c.innerHTML = aviso + `<div class="acoes"><button class="primary sm" data-conf="comecar">Conferir pela referência</button></div>
      <div class="dica">a timeline como está agora no Resolve · dá para cancelar a qualquer momento</div>`;
    return;
  }
  const faltam = est ? est.total - est.comparados : 0;
  const pills = est ? `<span class="pill ok">${est.conferem} conferem</span>` +
    (est.nao_conferem ? `<span class="pill warn">${est.nao_conferem} não ${est.nao_conferem === 1 ? "confere" : "conferem"}</span>` : "") +
    (faltam > 0 ? `<span class="pill">${faltam} não conferidos</span>` : "") +
    `<span class="pill">${relogio(resultado.segundos || 0)}</span>` : "";
  const titulo = resultado.erro ? `<p class="aviso">A conferência parou: ${escapar(resultado.erro)}</p>`
    : (resultado.cancelado ? `<p class="bloco-titulo">Conferência cancelada</p>`
      : `<p class="previa-ok">✓ Conferido pela referência</p>`);
  c.innerHTML = aviso + titulo + `<div class="placar">${pills}</div>` +
    // o que a casca DE FATO pôs (antes o painel afirmava os marcadores sem conferir — 2026-10-04)
    (est && est.nao_conferem && resultado.marcadores ? `<div class="dica">${resultado.marcadores} ${resultado.marcadores === 1 ? "ponto marcado" : "pontos marcados"} na timeline com marcador roxo (o nome diz o tipo; as Notes, o plano, a trilha e o TC).</div>` : "") +
    (est && est.nao_conferem && !resultado.marcadores ? `<p class="aviso">Os marcadores não entraram na timeline${resultado.erroMarcas ? ` (${escapar(resultado.erroMarcas)})` : ""}. Os resultados estão guardados: “Conferir de novo” tenta outra vez.</p>` : "") +
    ((resultado.cancelado || resultado.erro) ? `<div class="dica">Trilhas, página e agulha do Resolve voltaram como estavam.</div>` : "") +
    `<div class="acoes">` +
    (faltam > 0 ? `<button class="primary sm" data-conf="continuar">Continuar de onde parou</button>` : "") +
    `<button class="ghost sm" data-conf="comeco">${faltam > 0 ? "Conferir do começo" : "Conferir de novo"}</button></div>` +
    // os quadros, nomeados pelo TC (os que não conferem primeiro) e a planilha (organograma de 2026-10-05)
    (est && est.comparados ? `<div class="acoes"><button class="sm" data-conf-pasta="1">Abrir a pasta desta conferência</button></div>` : "");
}

el("rcFeito").addEventListener("click", async (ev) => {
  if (ev.target.closest("[data-conf-pasta]") && rcConf) {
    try { await post("/pasta/abrir", { qual: "conferencia", id: rcConf.ctx.id }); dizer(""); }
    catch (e) { dizer("Não consegui abrir a pasta: " + e.message, false); }
    return;
  }
  if (ev.target.closest("[data-ref-depois=escolher]")) { escolherReferenciaDepois(); return; }
  if (ev.target.closest("[data-ref-depois=tirar]")) { rcRefDepois.caminho = ""; pintarRefDepois(); return; }
  const som = ev.target.closest("[data-ref-som]");
  if (som) { rcRefDepois.som = som.dataset.refSom === "sim"; pintarRefDepois(); return; }
  const b = ev.target.closest("[data-conf]");
  if (!b || rcConferindo || rcOcupado) return;
  const qual = b.dataset.conf;
  // ⭐ Começar ou recomeçar lê a timeline COMO ESTÁ (autor, 2026-10-19: o editor arruma a timeline e só então
  // confere); só "continuar de onde parou" segue o plano guardado
  if (qual === "anexar" || qual === "timeline" || qual === "comecar" || qual === "comeco") {
    if (!rcFeitoTl) return;
    const ref = qual === "anexar" ? rcRefDepois.caminho : rcRef.caminho || "";
    if (qual === "anexar" && !ref) return;
    await conferirTimeline(ref ? { referencia: ref, som: qual === "anexar" ? rcRefDepois.som : false } : {});
    return;
  }
  if (!rcConf) return;
  const doComeco = false;
  dizer("");
  rcInicio = Date.now();
  mostrarTrazendo(true, `Conferindo ${rcConf.ctx.nome}`);
  for (const x of el("rcFeito").querySelectorAll("[data-conf]")) x.disabled = true;
  const res = await conferir(rcConf.ctx, doComeco);
  mostrarTrazendo(false);
  rcConf.resultado = res;
  pintarConferencia();
});

/* ── A referência DEPOIS de montar (autor, 2026-10-19) ─────────────────────────────────────────────────────────────
   Dois caminhos, e os dois conferem a timeline COMO ELA ESTÁ: o editor põe a referência na timeline à mão (e arruma o
   que quiser: tira takes que não aparecem, simplifica) e pede "Conferir a timeline" — o serviço acha a referência
   (trilha mais alta do início ao fim, ou o vídeo que entrou depois da entrega); ou indica o vídeo aqui, e ele entra
   numa trilha nova acima de todas, desligada, com o som numa trilha nova se ele quiser. Nenhuma trilha de áudio do
   editor sai. Quem anexa já quer conferir: é um botão só. */
function semReferenciaHtml(aviso) {
  return `<p class="sub-titulo">conferir pela referência</p>${aviso}
    <div class="dica">Pôs o vídeo de referência na timeline (e arrumou o que quiser)? Confira a timeline como ela está
      agora. Ou indique o vídeo: ele entra numa trilha nova acima de todas, desligada.</div>
    <div class="acoes"><button class="sm" data-conf="timeline">Conferir a timeline</button></div>
    <div class="zona-ref" data-solta="referenciaDepois">
      <button type="button" class="drop-alvo drop-baixo" data-ref-depois="escolher" id="rcRefDepoisEscolher">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="5" width="15" height="14" rx="2"/>
          <path d="M17 10l5-3v10l-5-3"/></svg>
        <span class="drop-texto"><strong>Arraste o vídeo de referência</strong>
          <span>ou clique para escolher · MOV, MP4, MXF</span></span>
      </button>
      <div class="ref-cartao" id="rcRefDepoisCartao" hidden>
        <div class="carga-topo">
          <div class="carga-texto"><span class="ref-selo escolhida">escolhida</span>
            <p class="carga-nome" id="rcRefDepoisNome"></p><p class="carga-de" id="rcRefDepoisDe"></p></div>
          <button type="button" class="carga-tirar" data-ref-depois="tirar" aria-label="Tirar o vídeo escolhido">×</button>
        </div>
      </div>
    </div>
    <div class="seg" id="rcRefDepoisSom" hidden>
      <button type="button" data-ref-som="sim" title="O som da referência numa trilha nova abaixo de todo o áudio (sem solo: o Resolve não deixa ligar o solo depois de montar)">som em trilha nova</button>
      <button type="button" data-ref-som="nao">sem o som</button>
    </div>
    <div class="acoes" id="rcRefDepoisAcoes" hidden><button class="primary sm" data-conf="anexar">Anexar e conferir</button></div>`;
}
function pintarRefDepois() {
  if (!el("rcRefDepoisCartao")) return;
  const tem = !!rcRefDepois.caminho;
  el("rcRefDepoisEscolher").hidden = tem;
  el("rcRefDepoisCartao").hidden = !tem;
  el("rcRefDepoisSom").hidden = !tem;
  el("rcRefDepoisAcoes").hidden = !tem;
  if (tem) {
    el("rcRefDepoisNome").textContent = rcRefDepois.caminho.split(/[\\/]/).pop();
    el("rcRefDepoisDe").textContent = rcRefDepois.caminho;
  }
  for (const b of el("rcRefDepoisSom").children) b.classList.toggle("on", (b.dataset.refSom === "sim") === rcRefDepois.som);
}
function soltarReferenciaDepois(caminhos) {
  const videos = caminhos.filter((c) => EXT_REFERENCIA.test(c));
  if (videos.length !== 1) {
    dizerNoArrasto(videos.length ? "um vídeo de referência por vez" : "a referência é um vídeo MOV, MP4 ou MXF", false);
    return;
  }
  rcRefDepois.caminho = videos[0];
  rcConfAviso = "";
  pintarConferencia();
}
const escolherReferenciaDepois = () => escolherNativo("/escolher/referencia", (c) => {
  rcRefDepois.caminho = Array.isArray(c) ? c[0] : c;
  rcConfAviso = "";
  pintarConferencia();
});

async function conferirTimeline(extra) {
  const alvo = rcFeitoTl;
  dizer("");
  rcConfAviso = "";
  rcInicio = Date.now();
  mostrarTrazendo(true, `Conferindo ${alvo.nome}`);
  pintarAndamento({ etapa: "conferindo", feitos: 0, total: 0,
                    detalhe: extra.referencia ? "pondo a referência na timeline e lendo a timeline como está agora"
                                              : "lendo a timeline como está agora e procurando a referência" });
  let r;
  try {
    r = await post("/conferencia/timeline",
                   { uid: alvo.uid, nome: alvo.nome, drt: alvo.drt, so_selecionados: !!alvo.so_selecionados, ...extra });
  } catch (e) {
    r = { ok: false, erro: e.message };
  }
  if (!r.ok) {
    mostrarTrazendo(false);
    rcConfAviso = r.erro || "a conferência não começou";
    pintarConferencia();
    return;
  }
  if (r.anexada) rcRefDepois.caminho = "";
  const ctx = { id: r.conferencia.id, pontos: r.conferencia.pontos, segundos: r.conferencia.segundos,
                nome: r.nome, uid: r.uid };
  rcFeitoTl = { ...alvo, nome: r.nome, uid: r.uid };
  rcConf = { ctx, resultado: null };
  for (const x of el("rcFeito").querySelectorAll("[data-conf]")) x.disabled = true;
  const res = await conferir(ctx, false);
  mostrarTrazendo(false);
  rcConf.resultado = res;
  pintarConferencia();
}

/* ── Relink aos originais, ao importar (ADR 0020) ────────────────────────────────
   Importar com pastas apontadas: o serviço casa cada master com o original em alta
   (`POST /receber/originais`, o mesmo casamento do relink do Avid), o painel acompanha pelo
   mesmo progresso e mostra a mesma revisão. O botão final ("Importar no Resolve") chama o
   Trazer de sempre com `originais: true`, e o DRT nasce apontando para os originais. */
let rcPendente = null;     // {pedido, titulo, idEnvio} — o Importar à espera da revisão

async function casarOriginais(pedido, titulo, idEnvio) {
  dizer("");
  try {
    await post("/receber/originais", { ...pedido, pastas });
  } catch (e) { dizer(e.message, false); return; }
  rcPendente = { pedido, titulo, idEnvio };
  mostrarPasso("passoProgresso");
  acompanhar();
}

async function importarComOriginais() {
  if (!rcPendente) { dizer("escolha de novo o que importar", false); return; }
  const { pedido, titulo, idEnvio } = rcPendente;
  mostrarPasso("passoOrigem");
  await trazerPedido({ ...pedido, originais: true }, titulo, idEnvio);
  rcPendente = null;
}

/* ── O projeto do Premiere: analisar e a tela "antes de montar" ─────────────────
   Organograma de 2026-10-02 (atualizado em 2026-10-03): escolher a sequência, as pastas dos
   originais (lembradas por projeto, no serviço), e ANTES de montar o resumo do que casou, do que
   falta e do que cada efeito vira. "Montar timeline" segue pelo Trazer de sempre. */
let rcAntes = null;        // {pedido, titulo} — a sequência analisada, à espera do "Montar"
/* A referência: a achada na timeline (`auto`) ou a indicada à mão (`caminho`), e o som dela. */
let rcRef = { auto: null, caminho: "", som: "A" };

/* A caixa "conferir pela referência ao terminar": só com referência (escolhida ou achada na
   timeline) e com a estimativa que a leitura da sequência já deu. */
let rcConfEstimativa = null;     // {pontos, segundos} da análise
function pintarCaixaConferir() {
  const linha = el("rcPrprojConferirLinha");
  if (!linha) return;
  const temRef = !!(rcRef.caminho || rcRef.auto);
  const est = rcConfEstimativa;
  const estava = !linha.hidden;
  linha.hidden = !(temRef && est && est.pontos);
  if (linha.hidden) { el("rcPrprojConferir").checked = false; return; }
  // com referência, a conferência vem MARCADA (autor, 2026-10-19: "o check automático do vid ref"); quem desmarca
  // continua desmarcado enquanto a referência não sai
  if (!estava) el("rcPrprojConferir").checked = true;
  el("rcPrprojConferirInfo").textContent =
    `(+ cerca de ${duracaoAprox(est.segundos)}, ≈ ${est.pontos.toLocaleString("pt-BR")} quadros)`;
}
function duracaoAprox(seg) {
  const m = Math.round((seg || 0) / 60);
  return m < 1 ? "1 min" : `${m} min`;
}

/* Três estados (redesenho de 2026-10-06): nenhuma → a área de soltar; achada na timeline → o cartão com
   o selo "achada na timeline" (sem ×: ela é da própria timeline); escolhida à mão → o selo "escolhida" e
   o × (que volta à achada, se houver). "Usar outro vídeo…" abre o seletor nos dois. */
function pintarReferencia() {
  const tem = !!(rcRef.caminho || rcRef.auto);
  el("rcRefEscolher").hidden = tem;
  el("rcRefCartao").hidden = !tem;
  if (rcRef.caminho) {
    el("rcRefSelo").textContent = "escolhida";
    el("rcRefNome").textContent = rcRef.caminho.split(/[\\/]/).pop();
    el("rcRefDe").textContent = rcRef.caminho;
  } else if (rcRef.auto) {
    el("rcRefSelo").textContent = "achada na timeline";
    el("rcRefNome").textContent = rcRef.auto.arquivo || "";
    el("rcRefDe").textContent = `na trilha V${rcRef.auto.trilha} da sequência`;
  }
  el("rcRefSelo").className = `ref-selo${rcRef.caminho ? " escolhida" : ""}`;
  el("rcRefTirar").hidden = !rcRef.caminho;
  // na cópia Premiere → Premiere a referência só serve à conferência: o som dela não entra em lugar nenhum
  el("rcRefSom").hidden = !tem || (NLE === "premiere" && rcRota === "prproj");
  for (const b of el("rcRefSom").children) b.classList.toggle("on", b.dataset.som === rcRef.som);
  pintarCaixaConferir();
}
const EXT_REFERENCIA = /\.(mov|mp4|mxf)$/i;
function soltarReferencia(caminhos) {
  const videos = caminhos.filter((c) => EXT_REFERENCIA.test(c));
  if (videos.length !== 1) {
    dizerNoArrasto(videos.length ? "um vídeo de referência por vez" : "a referência é um vídeo MOV, MP4 ou MXF", false);
    return;
  }
  rcRef.caminho = videos[0];
  pintarReferencia();
  dizerNoArrasto("vídeo de referência: " + (videos[0].split(/[\\/]/).pop() || videos[0]), true);
}
const escolherReferencia = () => escolherNativo("/escolher/referencia", (c) => {
  rcRef.caminho = Array.isArray(c) ? c[0] : c;
  pintarReferencia();
});
el("rcRefEscolher").onclick = escolherReferencia;
el("rcRefTrocar").onclick = escolherReferencia;
el("rcRefTirar").onclick = () => { rcRef.caminho = ""; pintarReferencia(); };
el("rcRefSom").onclick = (ev) => {
  const b = ev.target.closest("button[data-som]");
  if (!b) return;
  rcRef.som = b.dataset.som;
  pintarReferencia();
};

async function analisarPrproj(pedido, titulo) {
  // Sem pastas a análise segue (tudo fica no proxy): quem pergunta antes é o Importar (`perguntarOriginais`).
  dizer("");
  el("rcFeito").hidden = true;
  el("rcPrproj").hidden = true;
  rcInicio = Date.now();
  mostrarTrazendo(true, `Analisando ${titulo}`);
  pintarAndamento({ etapa: "lendo" });
  const relogioRc = setInterval(async () => {
    try { const p = await api("/receber/progresso"); if (p.ativo) pintarAndamento(p); } catch (_) { /* segue */ }
  }, 500);
  let a;
  try {
    a = await post("/receber/prproj/analisar", { avulso: pedido.avulso, mob_id: pedido.mob_id, pastas });
  } catch (e) {
    clearInterval(relogioRc);
    mostrarTrazendo(false);
    dizer(e.corpo && e.corpo.cancelado ? "cancelado — nada foi importado" : e.message, !!(e.corpo && e.corpo.cancelado));
    return;
  }
  clearInterval(relogioRc);
  mostrarTrazendo(false);
  rcAntes = { pedido, titulo };
  pintarAntesDeMontar(a, titulo);
}

/* ── AAF, bin e Carta na tela "antes de montar" (organograma aprovado pelo autor, 2026-10-19) ───────────────────────
   O resumo vem de `/receber/analisar`; com pastas, o casamento é o do relink do Avid (`/receber/originais`, com o
   andamento de sempre) e a lista é a do MC: uma linha por master (`/trabalho/masters`), com Revisar mídias, Ignorar e
   Relink manual. Sem pastas, a mídia entra como a timeline aponta e a lista diz como casar. */
let rcRota = "prproj";            // "prproj" | "carta": de quem é a tela aberta
let rcCartaAnalise = null;        // {pedido, titulo, idEnvio, resumo, casou}
let rcMasters = [];
let rcPlacarCarta = null;         // o `trabalho` do casamento (resolvidos, sugeridos, ambíguos, sem mídia)
let rcRevisaoTimer = 0;

async function analisarCarta(pedido, titulo, idEnvio) {
  dizer("");
  el("rcFeito").hidden = true;
  el("rcPrproj").hidden = true;
  let a;
  try {
    a = await post("/receber/analisar", pedido);
  } catch (e) { dizer(e.message, false); return; }
  rcCartaAnalise = { pedido, titulo, idEnvio, resumo: a, casou: false };
  if (!pastas.length) { abrirAntesCarta(); return; }
  await casarOriginais(pedido, titulo, idEnvio);    // o "pronto" do andamento abre a tela (`pintarProgresso`)
}

async function recarregarCarta() {
  if (!rcCartaAnalise || !rcCartaAnalise.casou) { rcMasters = []; rcPlacarCarta = null; return; }
  const [m, t] = await Promise.all([api("/trabalho/masters"), api("/trabalho")]);
  rcMasters = m.masters || [];
  rcPlacarCarta = t.trabalho || {};
}

async function abrirAntesCarta() {
  const c = rcCartaAnalise;
  if (!c) return;
  try { await recarregarCarta(); } catch (_) { rcMasters = []; rcPlacarCarta = null; }
  rcAntes = { pedido: c.pedido, titulo: c.titulo, idEnvio: c.idEnvio, carta: true };
  pintarAntesDeMontar({ ...c.resumo, carta: true, midias: [] }, c.titulo);
}

function dizerRc(texto, ok, titulo) {
  const p = el("rcManualMsg");
  p.innerHTML = (titulo ? `<strong><bdi>${escapar(titulo)}</bdi></strong><br>` : "") + escapar(texto || "");
  p.className = "mc-manual " + (ok ? "aceito" : "recusado");
  p.hidden = !texto;
}

function pintarAcoesCarta() {
  const sel = tabelaRc ? tabelaRc.selecionadas() : [];
  const casou = !!(rcCartaAnalise && rcCartaAnalise.casou);
  const conferir = rcMasters.filter((m) => linhaDaMidiaMC(m).s === "amb").length;
  el("rcRevisar").textContent = conferir ? `Revisar mídias (${conferir} a conferir)` : "Revisar mídias";
  el("rcRevisar").disabled = !casou;
  const todasIgn = sel.length && sel.every((x) => x.s === "ign");
  el("rcIgnorarC").textContent = todasIgn ? "Não ignorar" : sel.length > 1 ? `Ignorar (${sel.length})` : "Ignorar";
  el("rcIgnorarC").disabled = !casou || !sel.length;
  el("rcManual").disabled = !casou || sel.length !== 1;
}

async function aposDecidirCarta() {
  try { await recarregarCarta(); } catch (_) { /* a próxima volta relê */ }
  pintarMidias();
}

el("rcRevisar").onclick = async () => {
  await abrirJanelaRevisao(el("rcRevisar"), (texto) => dizerRc(texto, false));
  clearInterval(rcRevisaoTimer);
  let vezes = 0;
  // enquanto a janela larga decide, a lista daqui relê o serviço (cada decisão de lá já foi gravada no clique)
  rcRevisaoTimer = setInterval(async () => {
    if (++vezes > 200 || !rcAntes || !rcAntes.carta) { clearInterval(rcRevisaoTimer); return; }
    const antes = JSON.stringify(rcMasters);
    try { await recarregarCarta(); } catch (_) { return; }
    if (JSON.stringify(rcMasters) !== antes) pintarMidias();
  }, 3000);
};
el("rcIgnorarC").onclick = async () => {
  const sel = tabelaRc ? tabelaRc.selecionadas() : [];
  if (!sel.length) return;
  try {
    await post("/trabalho/ignorar", { mob_ids: sel.map((x) => x.k), ignorar: !sel.every((x) => x.s === "ign") });
    await aposDecidirCarta();
  } catch (e) { dizerRc(e.message, false); }
};
el("rcManual").onclick = async () => {
  const sel = tabelaRc ? tabelaRc.selecionadas() : [];
  if (sel.length !== 1) return;
  if (await relinkManual(sel[0], null, dizerRc)) await aposDecidirCarta();
};

/* ── A lista de mídias da tela "antes de montar" (autor, 2026-10-06; a tabela do MC desde 2026-10-19) ─────────────
   TODO arquivo de vídeo da sequência (`lista_de_midias` no motor) na MESMA tabela do Media Composer (`criarTabela`:
   autor, 2026-10-19, "alinhar"): ● situação · Na timeline · Encontrado · Codec · De onde veio; os filtros são as
   etiquetas de contagem; duplo clique no título ordena, a alça muda a largura, arrastar o título muda o lugar;
   seleção como no Explorer/Finder. O × da linha e o botão de baixo IGNORAM ("sem versão em alta, tudo bem"): sai o
   marcador "REFAZER no original" e o arquivo entra pelo proxy como sempre. ⛔ O que nem o proxy existe continua "sem
   mídia", ignorado ou não. Os ignorados são lembrados por projeto (no serviço). */
let rcMidias = [];
let rcIgnorados = new Set();
let rcAnalisePlanos = null;          // {no_original, planos} da análise, para o placar
let tabelaRc = null;
/* sem o original, a linha entra pelo arquivo do projeto (o proxy, ou ele mesmo achado noutra pasta) */
SITUACAO.prx = { classe: "warn", rotulo: "sem original", plural: "sem original", rank: 1.5 };

function ignoravel(m) { return m.estado !== "original"; }
/* "Relinkar só as offline" (autor, 2026-10-24): ligado, o que está online no projeto fica como está */
function soOffline() { return !!(el("rcSoOffline") && el("rcSoOffline").checked && !el("rcSoOfflineLinha").hidden); }

/* A linha do motor → a da tabela. A chave é o ÍNDICE: o caminho recusado pela tranca tem NUL, que o HTML não guarda. */
function linhaDaMidiaRc(m, i) {
  const fica = soOffline() && m.online;
  const ign = !fica && ignoravel(m) && rcIgnorados.has(m.caminho);
  const s = fica ? "onl" : m.estado === "original" ? "ok" : m.estado === "nao_encontrado" ? "bad" : ign ? "ign" : "prx";
  const nome = nomeDoCaminho(m.arquivo);
  // a situação ANTES do nome (2026-10-24): na janela estreita o fim do texto corta, e o nome repete a 1ª coluna
  const encontrado = fica ? "online · fica como está"
    : s === "ign" ? `fica assim (ignorado) · ${nome}`
    : m.como === "proprio" ? "o próprio arquivo"
    : m.como === "mudou" ? `mudou de lugar · ${nome}`
    : m.como === "original" ? nome
    // o convertido de TC zerado/ausente, a única mídia (2026-10-31): entra, a conferir
    : m.duvida && m.como === "original" ? `TC a conferir · ${nome}`
    : m.como === "realocado" ? `noutra pasta, sem original · ${nome}`
    : m.como === "proxy" ? `só o proxy · ${nome}`
    : "nada no disco · entra offline";
  return { k: String(i), s, nome: m.nome, codec: m.codec || "", arquivo: m.arquivo || "", encontrado,
           // o recusado pela tranca (rede, `..`) aparece como TEXTO: mostrar não abre nada
           origem: !m.origem ? "(caminho recusado)" : m.recusado ? `${m.origem} · não aberto, por segurança` : m.origem,
           m, ign };
}

function tabelaDaListaRc() {
  if (tabelaRc) return tabelaRc;
  // a ordem nova das colunas (2026-10-24) numa chave nova: a antiga gravava a ordem junto com a largura, e a ordem
  // velha voltaria; da antiga, só as larguras que o editor ajustou
  try {
    const velha = localStorage.getItem("delapraca.tabela.rc.lista");
    if (velha && !localStorage.getItem("delapraca.tabela.rc.lista.2")) {
      localStorage.setItem("delapraca.tabela.rc.lista.2", JSON.stringify({ larg: (JSON.parse(velha) || {}).larg || {} }));
    }
  } catch (_) { /* preferência */ }
  tabelaRc = criarTabela({
    tabela: el("rcMidiasTabela"), caixa: el("rcMidiasCaixa"), filtros: el("rcMidiasFiltros"), chave: "rc.lista.2",
    // "Encontrado" logo depois do nome: na janela estreita as duas cabem sem rolar (o "mudou de lugar" ficava fora da
    // vista; 2026-10-24). Codec e origem vêm depois.
    colunas: [{ id: "nome", titulo: "Na timeline", largura: 190 }, { id: "encontrado", titulo: "Encontrado", largura: 230 },
              { id: "codec", titulo: "Codec", largura: 70 }, { id: "origem", titulo: "De onde veio", largura: 280 }],
    celula: (x, id) => {
      if (id === "origem") return `<span class="mono"><bdi>${escapar(x.origem)}</bdi></span>`;
      const txt = `<bdi>${escapar(x[id] || (id === "codec" ? "—" : ""))}</bdi>`;
      if (id !== "encontrado" || rcRota === "carta" || !ignoravel(x.m) || x.s === "onl") return txt;
      return `<button type="button" class="midia-x" data-ign="${x.k}" title="${x.ign ? "Voltar a avisar"
        : "Ignorar: sem versão em alta, tudo bem"}" aria-label="${x.ign ? "Voltar a avisar" : "Ignorar"} ${escapar(x.nome)}">${
        x.ign ? "↺" : "×"}</button>${txt}`;
    },
    titulo: (x, id) => id === "encontrado" ? (SITUACAO[x.s] || {}).rotulo + (x.arquivo ? ` · ${x.arquivo}` : "")
      + (x.ign && x.s === "bad" ? " — ignorado, mas continua avisado (não está no disco)" : "")
      : id === "origem" ? x.origem : x[id] || "",
    aoMudar: () => (rcRota === "carta" ? pintarAcoesCarta() : pintarBotaoIgnorar()),
  });
  // o × (ou ↺) da linha alterna só ela, sem mexer na seleção: pega o clique ANTES da tabela
  el("rcMidiasTabela").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-ign]");
    if (!b || rcRota === "carta") return;
    ev.stopPropagation();
    const m = rcMidias[Number(b.dataset.ign)];
    if (m) ignorar([m.caminho], !rcIgnorados.has(m.caminho));
  }, true);
  return tabelaRc;
}

/* O placar da análise, contando os ignorados: "no proxy" só os que NÃO foram ignorados. */
function pintarPlacarMidias() {
  if (rcRota === "carta") {
    const t = rcPlacarCarta;
    const amb = t ? (t.sugeridos || 0) + (t.ambiguos || 0) : 0;
    el("rcPrprojPlacar").innerHTML = !t ? pill("sem pastas dos originais: a mídia entra como a timeline aponta") :
      pill(`${t.resolvidos || 0} de ${t.total || 0} mídias nos originais`, "ok") +
      (amb ? pill(`${amb} a conferir`, "warn") : "") +
      (t.nao_resolvidos ? pill(`${t.nao_resolvidos} sem mídia`, "err") : "") +
      pill(`${t.segmentos_resolvidos || 0}/${t.segmentos_total || 0} clipes na timeline`);
    el("rcMidiasConta").textContent = t ? `${rcMasters.length} ${rcMasters.length === 1 ? "mídia" : "mídias"}`
      + (amb + (t.nao_resolvidos || 0) ? ` · ${amb + (t.nao_resolvidos || 0)} a decidir` : "") : "";
    return;
  }
  const sem = rcMidias.filter((m) => m.estado === "sem_original");
  const noProxy = sem.filter((m) => !rcIgnorados.has(m.caminho)).length;
  const nada = rcMidias.filter((m) => m.estado === "nao_encontrado").length;
  const ign = rcMidias.filter((m) => ignoravel(m) && rcIgnorados.has(m.caminho)).length;
  const p = rcAnalisePlanos || { no_original: 0, planos: 0 };
  el("rcPrprojPlacar").innerHTML =
    `<span class="pill ok">${p.no_original} de ${p.planos} planos nos originais</span>` +
    (noProxy ? `<span class="pill warn">${noProxy} ${noProxy === 1 ? "arquivo" : "arquivos"} no proxy</span>` : "") +
    (nada ? `<span class="pill err">${nada} não ${nada === 1 ? "encontrado" : "encontrados"}</span>` : "") +
    (ign ? `<span class="pill">${ign} ${ign === 1 ? "ignorado" : "ignorados"}</span>` : "");
  el("rcMidiasConta").textContent = `${rcMidias.length} ${rcMidias.length === 1 ? "arquivo" : "arquivos"}`
    + (noProxy + nada ? ` · ${noProxy + nada} sem original` : "");
}

function pintarMidias() {
  const t = tabelaDaListaRc();
  const carta = rcRota === "carta";
  el("rcCartaAcoes").hidden = !carta;
  el("rcMidiasRodape").hidden = carta;
  el("rcSoOfflineLinha").hidden = carta || NLE !== "premiere";
  if (!carta) el("rcManualMsg").hidden = true;
  t.linhas = carta ? rcMasters.map(linhaDaMidiaMC) : rcMidias.map(linhaDaMidiaRc);
  t.vazio = carta ? (rcCartaAnalise && rcCartaAnalise.casou ? "nada a mostrar com este filtro"
    : "sem pastas dos originais: a mídia entra como a timeline aponta — indique as pastas no bloco 2 para casar")
    : rcMidias.length ? "nada a mostrar com este filtro" : "nenhum arquivo de vídeo";
  t.pintar();
  pintarPlacarMidias();
}

/* "Ignorar todos" ↔ "Ignorar selecionados (n)"; e "Voltar a avisar…" quando todos os alvos já estão ignorados. */
function alvosDoBotao() {
  if (!tabelaRc) return [];
  const sel = tabelaRc.selecionadas();
  return (sel.length ? sel : tabelaRc.visiveis()).filter((x) => x.s !== "onl").map((x) => x.m).filter(ignoravel);
}
function pintarBotaoIgnorar() {
  const alvos = alvosDoBotao();
  const todosIgnorados = alvos.length && alvos.every((m) => rcIgnorados.has(m.caminho));
  const quais = tabelaRc && tabelaRc.sel.size ? `selecionados (${alvos.length})` : "todos";
  const b = el("rcMidiasIgnorar");
  b.textContent = todosIgnorados ? `Voltar a avisar ${quais}` : `Ignorar ${quais}`;
  b.disabled = !alvos.length;
}

function ignorar(caminhos, sim) {
  for (const c of caminhos) { if (sim) rcIgnorados.add(c); else rcIgnorados.delete(c); }
  pintarMidias();
}

el("rcEscalasLista").addEventListener("change", (ev) => {
  const c = ev.target.closest("input[data-esc]");
  if (!c) return;
  const x = rcEscalas[Number(c.dataset.esc)];
  if (!x) return;
  if (c.checked) rcEscalasAceitas.add(x.chave); else rcEscalasAceitas.delete(x.chave);
  pintarEscalas();
});
el("rcEscalasTodas").onclick = () => {
  const todas = rcEscalas.every((x) => rcEscalasAceitas.has(x.chave));
  rcEscalasAceitas = todas ? new Set() : new Set(rcEscalas.map((x) => x.chave));
  pintarEscalas();
};
el("rcSoOffline").addEventListener("change", pintarMidias);
el("rcMidiasIgnorar").onclick = () => {
  const alvos = alvosDoBotao();
  const todosIgnorados = alvos.every((m) => rcIgnorados.has(m.caminho));
  ignorar(alvos.map((m) => m.caminho), !todosIgnorados);
};

/* ── A escala digitada para OUTRA mídia (autor, 2026-10-18: "marcar e oferecer") ──────────────────────────────
   `escala_de_outra_midia` da análise: {caminho, nome, fator, planos}. Marcado = o import multiplica a escala dos
   planos desse arquivo pelo fator; desmarcado = entra como o projeto diz. Os dois com marcador amarelo. */
let rcEscalas = [];
let rcEscalasAceitas = new Set();

function pintarEscalas() {
  el("rcEscalas").hidden = !rcEscalas.length;
  // o índice, não o caminho, no atributo: a chave de um caminho recusado pela tranca tem NUL, que o HTML não guarda
  el("rcEscalasLista").innerHTML = rcEscalas.map((x, i) => {
    const id = `rcEsc_${i}`;
    return `<label class="item rc-item" for="${id}"><input type="checkbox" id="${id}" data-esc="${i}"
        ${rcEscalasAceitas.has(x.chave) ? "checked" : ""}>
      <div class="rc-texto"><span class="item-nome"><bdi>${escapar(x.nome)}</bdi></span></div>
      <span class="pill warn">${x.tipo === "escala" ? `× ${escapar(String(x.fator).replace(".", ","))}`
        : `proporção ${escapar(`${x.para[0]}×${x.para[1]}`)}, não ${escapar(`${x.de[0]}×${x.de[1]}`)}`} · ${x.planos} ${x.planos === 1 ? "plano" : "planos"}</span></label>`;
  }).join("");
  const todas = rcEscalas.length && rcEscalas.every((x) => rcEscalasAceitas.has(x.chave));
  el("rcEscalasTodas").textContent = todas ? "Não ajustar nenhum" : "Ajustar todos";
}

function pintarAntesDeMontar(a, titulo) {
  const linha = (rotulo, classe, valor) =>
    `<div class="item rc-item"><div class="rc-texto"><span class="item-nome">${escapar(rotulo)}</span></div>` +
    `<span class="pill ${classe}">${escapar(valor)}</span></div>`;
  const e = a.efeitos || {};
  const sem = Object.entries(a.sem_traducao || {});
  const au = a.audio || {};
  const efa = Object.entries(au.efeitos || {});
  el("rcPrprojAudioInfo").textContent = au.clipes ? `(${au.clipes} clipes, ${au.trilhas} trilhas)` : "(a sequência não tem áudio)";
  rcRota = a.carta ? "carta" : "prproj";            // antes da referência: ela depende da rota
  rcRef = { auto: a.referencia || null, caminho: "", som: "A" };
  rcConfEstimativa = a.conferencia || null;
  pintarReferencia();
  el("rcPrprojAudio").disabled = !au.clipes;
  el("rcPrprojCompoundLinha").hidden = !e.nests;
  el("rcPrprojCompoundInfo").textContent = e.nests ? `(${e.nests} ${e.nests === 1 ? "nest" : "nests"})` : "";
  // O nome da sequência vai para a linha de baixo do cartão (`pintarCarga`); aqui, o que esta seção é.
  el("rcPrprojTitulo").textContent = "sequência analisada";
  // o resumo da tradução não existe na cópia Premiere → Premiere (autor, 2026-10-24: relink de timeline interna)
  el("rcTraducao").hidden = NLE === "premiere" && rcRota === "prproj";
  rcAnalisePlanos = { no_original: a.no_original, planos: a.planos };
  if (!a.carta) rcCartaAnalise = null;
  el("rcPrprojAudioLinha").hidden = !!a.carta;     // "trazer o áudio" é opção do projeto do Premiere
  // Premiere → Premiere: o nome da cópia (decisão C do organograma de 2026-10-22), sugerido e editável
  const comCopia = NLE === "premiere" && !a.carta;
  el("rcNomeCopiaLinha").hidden = !comCopia;
  if (comCopia) {
    const d = new Date(), z = (n) => String(n).padStart(2, "0");
    el("rcNomeCopia").value = `${a.sequencia || titulo || "sequência"} · relink ${z(d.getDate())}-${z(d.getMonth() + 1)} ${z(d.getHours())}h${z(d.getMinutes())}`;
  }
  // A lista de mídias: os ignorados que o projeto lembra + os que o editor já marcou nesta tela (uma
  // reanálise, ao mudar as pastas, não desfaz o que ele acabou de marcar).
  rcMidias = a.midias || [];
  const presentes = new Set(rcMidias.map((m) => m.caminho));
  rcIgnorados = new Set((a.ignorados || []).concat(Array.from(rcIgnorados)).filter((c) => presentes.has(c)));
  if (tabelaRc) { tabelaRc.sel = new Set(); tabelaRc.ancora = null; }
  pintarMidias();
  // a escala de outra mídia: a oferta da análise; o que o editor já marcou sobrevive a uma reanálise
  // duas ofertas na mesma lista: a escala (× fator) e a proporção do próprio arquivo
  rcEscalas = (a.escala_de_outra_midia || []).map((x) => ({ ...x, tipo: "escala", chave: `e|${x.caminho}` }))
    .concat((a.proporcao_de_outra_midia || []).map((x) => ({ ...x, tipo: "proporcao", chave: `p|${x.caminho}` })));
  const ofertados = new Set(rcEscalas.map((x) => x.chave));
  rcEscalasAceitas = new Set(Array.from(rcEscalasAceitas).filter((c) => ofertados.has(c)));
  pintarEscalas();
  el("rcPrprojLinhas").innerHTML = [
    e.velocidade ? linha(`Velocidade, reverso (${e.velocidade})`, "ok", "traduz") : "",
    e.keyframes ? linha(`Zoom e posição com keyframe (${e.keyframes})`, "ok", "traduz") : "",
    e.reframe ? linha(`Reformatação, FrameFlex (${e.reframe})`, "ok", "traduz") : "",
    e.transicoes ? linha(`Transições de vídeo (${e.transicoes})`, "ok", "traduz") : "",
    e.titulos ? linha(`Títulos (${e.titulos})`, "warn", "Text · conferir") : "",
    e.crop_flip ? linha(`Crop, flip (${e.crop_flip})`, "ok", "traduz") : "",
    e.fusion ? linha(`Máscara, blur, Basic 3D (${e.fusion} ${e.fusion === 1 ? "clipe" : "clipes"})`, "ok", "Fusion") : "",
    e.luma_key ? linha(`Luma Key (${e.luma_key})`, "warn", "Screen · conferir") : "",
    e.graficos ? linha(`Gráficos e títulos (${e.graficos})`, "warn", "conferir") : "",
    sem.length ? linha(`Sem tradução: ${sem.map(([n, k]) => `${n} (${k})`).join(", ")}`, "err", "aviso") : "",
    au.clipes ? linha(`Áudio: ${au.clipes} clipes em ${au.trilhas} trilhas, ${au.transicoes} transições`, "ok", "traduz") : "",
    au.volume ? linha(`Volume do clipe, fixo e com keyframes (${au.volume})`, "ok", "traduz") : "",
    efa.length ? linha(`Efeitos de áudio: ${efa.slice(0, 4).map(([n, k]) => `${n} (${k})`).join(", ")}${efa.length > 4 ? "…" : ""}`, "err", "não traduz") : "",
  ].join("") || `<div class="dica">Só cortes: nada a traduzir além do enquadramento.</div>`;
  el("rcPrproj").hidden = false;
  pintarCarga();   // o "Montar timeline" desta tela substitui o Importar enquanto ela está aberta
}

/* A análise da tela "antes de montar" foi feita com as pastas DAQUELE momento: indicar ou tirar uma pasta
   com ela aberta a deixaria velha (o placar e o Montar mentiriam). Refaz-se, com um respiro para várias
   pastas soltas de uma vez virarem uma análise só. ⚠️ Só é chamada depois da declaração de `rcAntes`
   (`renderPastas` no topo roda no fim do arquivo). */
let reanalise = null;
function reanalisarSePreciso() {
  if (!rcAntes || rcOcupado) return;
  clearTimeout(reanalise);
  reanalise = setTimeout(() => {
    if (!rcAntes || rcOcupado) return;
    const { pedido, titulo, idEnvio, carta } = rcAntes;
    if (carta) analisarCarta(pedido, titulo, idEnvio);
    else analisarPrproj(pedido, titulo);
  }, 400);
}

el("rcPrprojMontar").onclick = async () => {
  if (!rcAntes) return;
  const { pedido, titulo, idEnvio, carta } = rcAntes;
  el("rcPrproj").hidden = true;
  rcAntes = null;
  clearInterval(rcRevisaoTimer);
  if (carta) {
    // com o casamento feito, a volta leva as decisões (`originais: true`); sem pastas, a mídia da timeline
    const casou = !!(rcCartaAnalise && rcCartaAnalise.casou);
    rcPendente = null;
    await trazerPedido({ ...pedido, analisado: true, ...(casou ? { originais: true } : {}) }, titulo, idEnvio || null);
    return;
  }
  await trazerPedido({ ...pedido, analisado: true }, titulo, null);
};
el("rcPrprojCancelar").onclick = () => {
  rcAntes = null;
  rcCartaAnalise = null;
  clearInterval(rcRevisaoTimer);
  el("rcPrproj").hidden = true;
  pintarCarga();
  dizer("nada foi importado", true);
};

/* ── O bloco 1 do Resolve: carregar, e só depois importar ──────────────────────
   Redesenho aprovado pelo autor (2026-10-05, canvas Py51N8kGcERArsuAbD8yeQ): o arquivo (escolhido no
   seletor ou solto na área) e o envio do Magic Link entram no CARTÃO com a leitura rápida do serviço
   (duração, taxa, trilhas, planos), e o Importar só aparece aí, embaixo das opções avançadas.
   ⛔ Antes, a Carta, o AAF e a bin de UMA sequência começavam a importar no instante da escolha: o
   editor não tinha como apontar os originais antes. Numa bin ou num projeto do Premiere, a sequência
   se MARCA na lista (escolher não importa). */
let rcAvulso = null;   // o arquivo aberto, como o `trazerPedido` o conhece (`chave`, `tipo`)

const ROTULO_TIPO_CARGA = { aaf: "AAF", carta: "Carta Aberta", avb: "bin do Avid", prproj: "projeto do Premiere",
                            xmeml: "timeline da Carta Aberta" };
/* O xmeml da Carta Aberta (etapa 3 da proposta Baselight no app) passa pela MESMA tela do projeto do Premiere: a análise
   (o arquivo de cada plano → o original nas pastas) e o "antes de montar". */
const comAnalise = (tipo) => tipo === "prproj" || tipo === "xmeml";

function sequenciasDaCarga() {
  return rcCarga && rcCarga.arquivo && ["avb", "prproj", "xmeml"].includes(rcCarga.arquivo.tipo)
    ? (rcCarga.arquivo.sequencias || []) : [];
}

function taxaLegivel(fps) {
  let n = Number(fps) || 0;
  // A coluna FPS do MC arredonda (23.98, 29.97 já vem certo): a MESMA timeline dizia "23,98" pelo Record e "23,976"
  // pela bin de fora (2026-10-13). As taxas NTSC voltam ao nome por que o editor as conhece.
  for (const ntsc of [23.976, 47.952, 59.94, 119.88]) if (Math.abs(n - ntsc) < 0.006) n = ntsc;
  return n ? `${String(Math.round(n * 1000) / 1000).replace(".", ",")} fps` : "";
}

/* "V1-2 TC1-8 A1-2" (coluna Tracks do MC) → "V1-2 A1-2": só imagem e som contam (autor, 2026-10-12; o mesmo que o
   serviço faz em `_faixas_av` para a bin de fora). */
function trilhasVA(s) {
  return String(s || "").trim().split(/\s+/).filter((x) => /^[VA]\d/i.test(x)).join(" ");
}

/* A leitura rápida (`_leitura_rapida` no serviço): do arquivo, do envio, ou da sequência marcada. */
function fatosDe(x) {
  if (!x) return [];
  const trilhas = x.video != null && x.audio != null ? `${x.video} de vídeo · ${x.audio} de áudio` : "";
  return [["duração", x.duracao || ""], ["taxa", taxaLegivel(x.fps)], ["trilhas", trilhas],
          ["planos", x.planos != null ? String(x.planos) : ""]].filter(([, v]) => v);
}

function pintarSequencias() {
  const seqs = sequenciasDaCarga();
  const bloco = el("rcAvulso");
  // Uma bin de UMA sequência não precisa de escolha: ela já vem marcada (`carregarArquivo`).
  if (!seqs.length || (rcCarga.arquivo.tipo === "avb" && seqs.length < 2)) { bloco.hidden = true; return; }
  el("rcAvulsoTitulo").textContent = `${seqs.length} ${seqs.length === 1 ? "sequência" : "sequências"} — marque qual importar`;
  el("rcSequencias").innerHTML = seqs.map((s) => {
    const marcada = s.mob_id === rcSeqEscolhida;
    const info = [s.duracao || "", s.planos ? `${s.planos} planos` : ""].filter(Boolean).join(" · ");
    return `<label class="seq${marcada ? " sel" : ""}">
      <input type="radio" name="rcSeq" value="${escapar(s.mob_id)}"${marcada ? " checked" : ""}${rcOcupado ? " disabled" : ""}>
      <span class="seq-texto"><span class="seq-nome">${escapar(s.nome || "(sem nome)")}</span>
        <span class="seq-info">${escapar(info)}</span></span></label>`;
  }).join("");
  bloco.hidden = false;
}

/* Tudo o que depende do que está carregado, num lugar só: a área × o cartão, a lista, as opções
   avançadas, e o Importar (que some durante a importação e enquanto a tela "antes de montar" do
   Premiere está aberta — ela tem o "Montar timeline" dela). */
function pintarCarga() {
  if (!RECEBE) return;
  const naAba = modoOrigem === "aaf";
  const vazio = !rcCarga;
  el("rcBtnAbrir").hidden = !vazio;
  el("rcCarga").hidden = vazio;
  el("rcAvancadas").hidden = rcOcupado || (modoOrigem !== "aaf" && modoOrigem !== "atualizar");
  el("rcAvProjeto").hidden = !((rcCarga && rcCarga.arquivo && rcCarga.arquivo.tipo === "prproj") || rcAntes);
  const antesDeMontar = !el("rcPrproj").hidden;
  el("rcAcoes").hidden = vazio || !naAba || rcOcupado || antesDeMontar;
  el("rcAcoesMontar").hidden = !antesDeMontar || rcOcupado;
  // o rodapé fixo fica (a assinatura e a versão); só os botões somem quando não há o que fazer
  el("barraAcoes").hidden = !!revisaoNaJanela;
  // Na tela "antes de montar" o cartão FICA (o cabeçalho com as informações da timeline) e a análise
  // ocupa o lugar da lista de sequências; o Magic Link e o "Trocar arquivo" saem (autor, 2026-10-06).
  el("mlAcordeao").hidden = antesDeMontar;
  ajustarBarra();
  if (vazio) return;

  const seq = sequenciasDaCarga().find((s) => s.mob_id === rcSeqEscolhida) || null;
  let nome, de, fatos;
  if (rcCarga.envio) {
    const e = rcCarga.envio;
    nome = e.nome || e.sequencia || "?";
    de = ["Magic Link", rotuloOrigem(e), quando(e.enviado_em)].filter(Boolean).join(" · ");
    fatos = fatosDe(e);
  } else {
    const r = rcCarga.arquivo;
    const seqs = r.sequencias || [];
    nome = r.tipo === "carta" || r.tipo === "aaf" ? (r.nome || r.arquivo) : r.arquivo;
    // Na análise, a sequência lida (o título da seção diz só "sequência analisada · resumo").
    de = [ROTULO_TIPO_CARGA[r.tipo] || "", r.tipo === "carta" || r.tipo === "aaf" ? r.arquivo
          : antesDeMontar && seq ? seq.nome || "(sem nome)"
          : `${seqs.length} ${seqs.length === 1 ? "sequência" : "sequências"}`].filter(Boolean).join(" · ");
    fatos = fatosDe(seq || r);
  }
  el("rcCargaNome").textContent = nome;
  el("rcCargaDe").textContent = de;
  el("rcCargaFatos").innerHTML = fatos.map(([k, v]) => `<div><dt>${escapar(k)}</dt><dd>${escapar(v)}</dd></div>`).join("");
  el("rcCargaTirar").disabled = rcOcupado;
  el("rcCargaTrocar").disabled = rcOcupado;
  el("rcCargaTrocar").hidden = !!rcCarga.envio || antesDeMontar;   // o envio se troca pela lista do Magic Link
  pintarSequencias();
  if (antesDeMontar) el("rcAvulso").hidden = true;

  const precisaSeq = !rcCarga.envio && sequenciasDaCarga().length > 0;
  el("rcImportar").disabled = precisaSeq && !seq;
  // "Ler", não "Importar" (autor, 2026-10-05): importar soava como montar, e montar é o passo seguinte.
  el("rcImportar").textContent = rcCarga.envio ? "Importar como nova" : "Ler Timeline Selecionada";
  el("rcAtualizarEnvio").hidden = !rcCarga.envio;
}

/* A barra fixa do rodapé não pode cobrir o fim da página: o `body` ganha embaixo a altura dela. */
function ajustarBarra() {
  const b = el("barraAcoes");
  if (!b) return;
  document.body.style.paddingBottom = b.hidden ? "" : `${b.offsetHeight + 28}px`;
}
window.addEventListener("resize", () => ajustarBarra());
// a barra muda de altura sozinha (botões que entram e saem, a versão nova): a margem acompanha
if (typeof ResizeObserver === "function" && el("barraAcoes")) new ResizeObserver(() => ajustarBarra()).observe(el("barraAcoes"));

function carregarArquivo(r) {
  const seqs = r.sequencias || [];
  desfazerLeitura();
  rcCarga = { arquivo: r };
  rcAvulso = r;
  rcSeqEscolhida = seqs.length === 1 ? seqs[0].mob_id : null;
  rcIgnorados = new Set();   // os de outro projeto não valem aqui (o serviço devolve os deste na análise)
  // o job: a produção da Carta (etapa 4), senão o nome do PROJETO (autor, 2026-11-23) — nunca o do envio anterior (o
  // PRODC ia para o job do PRODUCAO-A, e a pergunta dizia "a produção desta timeline é PRODUCAO-A")
  if (BASELIGHT && el("rcBlJob") && (r.producao || r.projeto)) el("rcBlJob").value = r.producao || r.projeto;
  if (comAnalise(r.tipo) && !pastas.length && (r.pastas || []).length) {
    addPasta(r.pastas);   // decisão do autor (2026-10-03): o mesmo projeto volta com as mesmas pastas
  }
  el("rcFeito").hidden = true;
  pintarCarga();
  pintarTabela();
  dizer(seqs.length > 1 ? `${seqs.length} sequências em ${r.arquivo} — marque qual importar` : "", true);
}

/* `caminho`: o arquivo solto na área; sem ele, o seletor do sistema. */
async function abrirArquivo(caminho) {
  if (rcOcupado) return;
  let r;
  try {
    r = await post("/receber/abrir", typeof caminho === "string" && caminho ? { caminho } : {});
  } catch (e) { dizer(e.message, false); return; }
  if (r.cancelado) return;
  carregarArquivo(r);
}

/* ⛔ Carregar outra coisa DEPOIS de ler a timeline desfaz a leitura (autor, 2026-10-06): antes, o cartão
   trocava e a análise da anterior ficava aberta — e o "Montar timeline" montava a sequência ANTERIOR. O
   editor que percebe pelas informações que não era o arquivo certo e solta outro volta ao passo de antes:
   o arquivo novo, a escolha da sequência e o "Ler Timeline Selecionada". */
function desfazerLeitura() {
  clearTimeout(reanalise);
  clearInterval(rcRevisaoTimer);
  rcAntes = null;
  rcCartaAnalise = null;
  rcMasters = [];
  el("rcPrproj").hidden = true;
  rcRef = { auto: null, caminho: "", som: "A" };
  rcConfEstimativa = null;
  rcMidias = [];
  if (tabelaRc) { tabelaRc.sel = new Set(); tabelaRc.ancora = null; }
}

function carregarEnvio(id) {
  const envio = (rcCaixa.envios || []).find((e) => e.id === id);
  if (!envio || rcOcupado) return;
  desfazerLeitura();
  rcCarga = { envio };
  rcAvulso = null;
  rcSeqEscolhida = null;
  el("rcFeito").hidden = true;
  pintarCarga();
  pintarTabela();
  dizer("");
  el("rcCarga").scrollIntoView({ block: "nearest" });
}

function tirarCarga() {
  if (rcOcupado) return;
  desfazerLeitura();                 // o × no meio do "antes de montar" desiste dele também
  rcCarga = null;
  rcAvulso = null;
  rcSeqEscolhida = null;
  rcIgnorados = new Set();
  pintarCarga();
  pintarTabela();
}

/* O pedido do Importar, a partir do que está carregado. */
function pedidoDaCarga() {
  if (!rcCarga) return null;
  if (rcCarga.envio) {
    const e = rcCarga.envio;
    return { pedido: { id: e.id }, titulo: e.nome || e.sequencia || "", idEnvio: e.id, fonte: "o envio" };
  }
  const r = rcCarga.arquivo;
  const fonte = { aaf: "o próprio AAF", carta: "a Carta", avb: "a bin", prproj: "o projeto do Premiere" }[r.tipo] || "o arquivo";
  if (r.tipo === "carta" || r.tipo === "aaf") return { pedido: { avulso: r.chave }, titulo: r.nome || r.arquivo, idEnvio: null, fonte };
  const seq = (r.sequencias || []).find((s) => s.mob_id === rcSeqEscolhida);
  return seq ? { pedido: { avulso: r.chave, mob_id: seq.mob_id }, titulo: seq.nome || r.arquivo, idEnvio: null, fonte } : null;
}

/* "Não perguntar de novo" vale para o PROJETO aberto no Resolve nesta sessão (autor, 2026-10-05):
   trocou de projeto, pergunta de novo; o painel recarregado também. Só em memória, de propósito. */
let originaisDispensadoEm = null;

async function projetoAberto() {
  try { return ponte() && typeof ponte().projeto === "function" ? String((await ponte().projeto()).projeto || "") : ""; }
  catch (_) { return ""; }
}

/* A pergunta dos originais: só no clique do Importar, nunca sozinha. Resolve `true` = montar assim. */
async function perguntarOriginais(fonte) {
  const projeto = await projetoAberto();
  if (originaisDispensadoEm !== null && originaisDispensadoEm === projeto) return true;
  const prproj = fonte === "o projeto do Premiere";
  el("semOriginaisTexto").textContent = "Nenhuma pasta de originais foi indicada. A timeline vai ser montada "
    + `com os arquivos que ${fonte} referencia — onde estiverem. `
    + (prproj ? "O que não tiver original entra no proxy, com marcador vermelho."
              : "O que não for encontrado entra offline.");
  el("semOriginaisProjeto").textContent = projeto
    ? `Não perguntar de novo neste projeto (${projeto})` : "Não perguntar de novo nesta sessão";
  el("semOriginaisNaoPerguntar").checked = false;
  el("semOriginais").hidden = false;
  el("semOriginaisMontar").focus();
  return new Promise((fim) => {
    const fechar = (montar) => {
      el("semOriginais").hidden = true;
      el("semOriginaisMontar").onclick = el("semOriginaisIndicar").onclick = el("semOriginais").onkeydown = null;
      if (montar && el("semOriginaisNaoPerguntar").checked) originaisDispensadoEm = projeto;
      fim(montar);
    };
    el("semOriginaisMontar").onclick = () => fechar(true);
    el("semOriginaisIndicar").onclick = () => { fechar(false); el("btnEscolherPasta").click(); };
    el("semOriginais").onkeydown = (ev) => { if (ev.key === "Escape") fechar(false); };
  });
}

async function importarCarga() {
  if (rcOcupado || !rcCarga) return;
  const alvo = pedidoDaCarga();
  if (!alvo) { dizer("marque qual sequência importar", false); return; }
  if (!pastas.length && !(await perguntarOriginais(alvo.fonte))) return;
  await trazerPedido(alvo.pedido, alvo.titulo, alvo.idEnvio);
}

/* O envio carregado como VERSÃO NOVA da aba "Atualizar timeline" (autor, 2026-10-05). */
let atNovaPedida = null;
function atualizarComEnvio() {
  if (rcOcupado || !rcCarga || !rcCarga.envio) return;
  atNovaPedida = rcCarga.envio.id;
  irParaModo("atualizar");
}

el("rcBtnAbrir").onclick = () => abrirArquivo();
el("rcCargaTrocar").onclick = () => abrirArquivo();
el("rcCargaTirar").onclick = tirarCarga;
el("rcImportar").onclick = importarCarga;
el("rcAtualizarEnvio").onclick = atualizarComEnvio;
el("rcSequencias").addEventListener("change", (ev) => {
  const r = ev.target.closest("input[name=rcSeq]");
  if (!r) return;
  rcSeqEscolhida = r.value;
  // o erro de antes ("não achei a sequência…") fica velho quando o editor escolhe outra; o aviso do projeto salvo, não
  const m = el("blocoTimeline").querySelector(".msg-bloco.erro");
  if (m) m.hidden = true;
  pintarCarga();
});
el("rcBtnCancelar").onclick = async () => {
  el("rcBtnCancelar").disabled = true;
  if (rcConferindo) { rcCancelarConf = true; return; }   // a conferência para no fim do lote
  try { await post("/receber/cancelar"); } catch (_) { /* o preparar responde */ }
};
el("origemAAF").addEventListener("click", (ev) => {
  const t = ev.target.closest("button");
  if (!t || t.disabled) return;
  if (t.dataset.carregar) carregarEnvio(t.dataset.carregar);
  else if (t.dataset.carregarBin) carregarEnvioMC(t.dataset.carregarBin);
  else if (t.dataset.procurar) procurarNovos(false);
  else if (t.dataset.irAjustes) irPara("ajustes");
});

/* ── Ajustes: o papel desta ilha e os canais ──────────────────────────────────────
   O papel é da MÁQUINA (Edição, Cor, VFX…) e decide os canais que ela vê. As pastas seguem o
   projeto do Avid; no Resolve, a máquina. Mudou aqui → as listas e os botões de enviar se
   refazem. */
function pintarAjustesCanais(r) {
  if (!r) return;
  el("ajCanais").innerHTML = (r.canais || []).map((c) =>
    `<div class="item rc-item"><div class="rc-texto"><span class="item-nome">Edição ⇄ ${escapar(c.rotulo)}</span>`
    + `<div class="item-seg"><bdi>${escapar(c.pasta || "não conectado")}</bdi>`
    + `${c.pasta && !c.conectado ? " — inacessível agora" : ""}</div></div>`
    + `<button class="sm" data-conectar="${escapar(c.setor)}">${c.pasta ? "Trocar…" : "Conectar…"}</button></div>`
  ).join("");
  el("ajCanaisDica").textContent = "Conecte só os canais do seu trabalho: a edição conecta um "
    + "para cada time; a cor, só o da Cor; o VFX, só o do VFX. Para um setor não abrir a pasta "
    + "do outro nem pelo Explorer, peça a quem cuida da rede as permissões de cada pasta.";
}

async function carregarCanais() {
  try { pintarAjustesCanais(await api(`/canais?nle=${NLE}`)); } catch (_) { /* sem serviço */ }
}

async function canaisMudaram(r) {
  pintarAjustesCanais(r);
  if (NLE === "mc") carregarMagic();
  procurarNovos(true);
}

el("ajCanais").onclick = async (ev) => {
  const b = ev.target.closest("button[data-conectar]");
  if (!b) return;
  try {
    const r = await post("/canais/conectar", { setor: b.dataset.conectar, nle: NLE });
    await canaisMudaram(r);
    if (!r.cancelado) dizer(NLE === "mc" ? "canal guardado neste projeto" : "canal guardado nesta máquina", true);
  } catch (e) { dizer(e.message, false); }
};

/* No Media Composer a caixa do Magic Link não era lida ao abrir (só no modo arquivo): abrir o acordeão a procura,
   como o "Procurar novos" (2026-10-13 — a tabela abria vazia, sem o selo dos novos). */
if (NLE === "mc") {
  el("mlAcordeao").addEventListener("toggle", () => { if (el("mlAcordeao").open) procurarNovos(true); });
}

/* ── Fechar a janela única (decisão 3 do organograma de 2026-10-19) ────────────────────────────────────────────
   O X da janela do app vem para cá (`lib.rs`, `dlpcAoFechar`): sem trabalho em andamento, fecha na hora (pelo serviço:
   `/app/fechar` → o executável encerra serviço e app); com importação, relink ou conferência em curso, pergunta
   dentro da janela. Se esta página não responder, o 2º X em 5 s fecha mesmo (o Rust garante). */
async function fecharApp() {
  try { await post("/app/fechar"); }
  catch (_) { dizer("não consegui fechar pelo serviço — clique no X de novo para fechar", false); }
}
async function haTrabalhoEmAndamento() {
  if (typeof rcOcupado !== "undefined" && rcOcupado) return true;
  try { if ((await api("/trabalho")).ocupada) return true; } catch (_) { /* sem resposta: não é prova de trabalho */ }
  try { if ((await api("/receber/progresso")).ativo) return true; } catch (_) { /* idem */ }
  return false;
}
window.dlpcAoFechar = async () => {
  if (!(await haTrabalhoEmAndamento())) { fecharApp(); return; }
  el("fecharAviso").hidden = false;
  el("fecharContinuar").focus();
};
el("fecharContinuar").onclick = () => { el("fecharAviso").hidden = true; };
el("fecharMesmo").onclick = () => { el("fecharAviso").hidden = true; fecharApp(); };

/* ⚙ › Diagnóstico: o que a janela antiga do app mostrava (porta, processo) e o "Liberar a porta do Media Composer". */
async function carregarDiagnostico() {
  try {
    const d = await api("/app/diagnostico");
    el("cfDiag").textContent = `no ar · porta ${d.porta} · processo ${d.pid}` + (d.app ? "" : " · sem o aplicativo");
  } catch (e) { el("cfDiag").textContent = "o serviço não respondeu: " + e.message; }
}
el("cfLiberar").onclick = async () => {
  const b = el("cfLiberar");
  const msg = el("cfLiberarMsg");
  b.disabled = true;
  msg.hidden = false;
  msg.textContent = "procurando o processo que segura as portas…";
  try {
    const r = await post("/app/liberar-porta");
    msg.textContent = !(r.alvos || []).length ? "nenhum processo preso — as portas já estão livres."
      : (r.restantes || []).length ? `ainda há processo segurando as portas (${r.restantes.join(", ")}). Feche o Media Composer e tente de novo.`
      : r.mc_aberto ? `liberei ${r.mortos.length} processo(s). O Media Composer está ABERTO — feche e reabra.`
      : `pronto: ${r.mortos.length} processo(s) liberados.`;
  } catch (e) { msg.textContent = e.message; }
  finally { b.disabled = false; }
};

/* ── Boot ────────────────────────────────────────────────────────────────── */
pastas = lerPastas();
renderPastas();

if (VISTA_REVISAO) {
  document.body.classList.add("vista-revisao");
  irPara("deLaPraCa");
  mostrarPasso("passoRevisao");
  /* ⭐ A janela larga abre em "tudo", não em "a decidir" — e a diferença é o propósito
     dela. No painel estreito o filtro certo é o que sobrou para resolver; aqui o editor
     veio CONFERIR, e o que ele precisa ver inclui o que o programa considera resolvido.
     Abrir filtrada esconderia justamente os casamentos confiantes, que são onde mora o
     falso positivo. */
  filtro = "tudo";
  for (const x of el("filtro").children) {
    x.classList.toggle("on", x.dataset.filtro === "tudo");
  }
  el("btnConcluirRevisao").hidden = false;
  // Nesta janela não se prepara nem se aplica: ela só resolve pendências. Quem
  // aplica é a janela principal, onde está o resto do fluxo.
  el("btnVoltar").hidden = true;
  el("btnAplicar").parentElement.hidden = true;
  carregarRevisao().catch(() => {});
} else if (VISTA_AJUSTES) {
  document.body.classList.add("vista-ajustes");
  document.title = "Conformar — Ajustes";
  irPara("ajustes");
  carregarCache();
  carregarDiagnostico();
} else if (VISTA_CONFIG) {
  document.body.classList.add("vista-config");
  document.title = "De Lá Pra Cá — Configurações";
  carregarCache();
  carregarDiagnostico();
} else {
  irPara(lerAba());
  mostrarPasso("passoOrigem");
  // A caixa "Importar / relinkar" abre inteira: no Resolve, no arquivo (a sequência aberta ainda é "em breve");
  // no Media Composer, na sequência, com o arquivo e o Magic Link na mesma caixa.
  if (RECEBE) irParaModo("aaf");
  else el("origemAAF").hidden = false;
}

if (VISTA_REVISAO || VISTA_CONFIG || VISTA_AJUSTES) {
  el("barraAcoes").hidden = true;
} else {
  if (NLE === "mc") el("mcAcoesBarra").appendChild(el("btnPreparar").parentElement);
  el("barraAcoes").hidden = false;
  pintarBarraMC();
}

baterNoServico();
setInterval(baterNoServico, 4000);
/* A janela de revisão é uma segunda vista do MESMO trabalho: se o editor decidir algo
   aqui, a principal precisa enxergar — e vice-versa. Um refresco periódico basta;
   as decisões são cliques humanos, não um fluxo.

   ⚠️ O "e vice-versa" estava só no comentário: o refresco existia apenas na vista de
   revisão. O painel dentro do Media Composer ficava com o resumo CONGELADO enquanto o
   editor aprovava na janela larga — e, como agora o painel mostra só o resumo, ele diria
   "12 divergências" com as doze já resolvidas do outro lado. Pior que desatualizado:
   parece que a revisão não teve efeito.

   Só enquanto o passo de revisão está na tela — `/trabalho` é barato (lê estado de
   sessão, não fala com o Media Composer), mas bater à toa nos outros passos é ruído. */
if (VISTA_REVISAO) {
  setInterval(() => carregarRevisao().catch(() => {}), 3000);
} else {
  setInterval(() => {
    if (!el("passoRevisao").hidden) carregarRevisao().catch(() => {});
  }, 3000);
}


/* As escolhas dos Sinais do Import ficam lembradas NESTE painel (só conveniência: sem storage,
   volta o padrão aprovado — marcador e cor ligados, trilha de notas desligada). */
for (const id of ["rcMarcar", "rcColorir", "rcNotas"]) {
  const caixa = el(id);
  if (!caixa) continue;
  try {
    const salvo = localStorage.getItem("dlpc." + id);
    if (salvo !== null) caixa.checked = salvo === "1";
  } catch (_) { /* sem storage */ }
  caixa.addEventListener("change", () => {
    try { localStorage.setItem("dlpc." + id, caixa.checked ? "1" : "0"); } catch (_) { /* idem */ }
  });
}


/* ── Código de cores dos Sinais do Import (Ajustes, só no Resolve) ─────────────────
   Aprovado pelo autor em 2026-09-27: guardado NESTA máquina (`/ajustes/sinais`), as
   categorias são fixas e a lista de cada uma é só leitura; cor repetida em duas categorias
   AVISA e deixa. Os nomes são os do menu do Resolve; as amostras são aproximadas. */
const AMOSTRA_MARCADOR = {
  Blue: "#3a7bea", Cyan: "#23c5c9", Green: "#2fae4a", Yellow: "#e8cf1c", Red: "#e03a3a",
  Pink: "#f06bc8", Purple: "#8a4fd8", Fuchsia: "#c0307a", Rose: "#f0a0bd", Lavender: "#b8a6e8",
  Sky: "#8cc6f0", Mint: "#9be0b5", Lemon: "#f3ec8a", Sand: "#d9bf8c", Cocoa: "#8a5a3c",
  Cream: "#f2ead5",
};
const AMOSTRA_CLIPE = {
  Orange: "#eb6e01", Apricot: "#ffa833", Yellow: "#d9a906", Lime: "#9fc615", Olive: "#5f9923",
  Green: "#448f65", Teal: "#00ad9f", Navy: "#1b4f8a", Blue: "#4b97d4", Purple: "#8e5fc0",
  Violet: "#b25fc0", Pink: "#e36fa8", Tan: "#b9af97", Beige: "#c4915e", Brown: "#99662f",
  Chocolate: "#7a4a2c",
};
let codigoDeCores = null;

function pintarLegendaDasCores(codigo) {
  const alvo = el("rcLegenda");
  if (!alvo || !codigo) return;
  const partes = Object.keys(codigo.cores).map(cat =>
    `${codigo.cores[cat].clipe} = ${{ distorcao: "possível distorção (Stretch)",
      refazer: "refazer", conferir: "conferir" }[cat] || cat}`);
  alvo.textContent = "cor local (só o segmento, nunca o clipe na bin): " + partes.join(", ");
}

function pintarCodigoDeCores(estado) {
  codigoDeCores = estado.codigo;
  const alvo = el("ajCores");
  const escolha = (cat, campo, tabela, amostras, rotulo) => {
    const atual = estado.codigo.cores[cat][campo];
    const opcoes = tabela.map(n =>
      `<option value="${escapar(n)}"${n === atual ? " selected" : ""}>${escapar(n)}</option>`).join("");
    return `<label class="cor-escolha"><span class="cor-rot">${rotulo}</span>
      <span class="cor-linha"><i class="cor-amostra${campo === "marcador" ? " mk" : ""}"
        style="background:${amostras[atual] || "#777"}"></i>
      <select data-cat="${escapar(cat)}" data-campo="${campo}">${opcoes}</select></span></label>`;
  };
  alvo.innerHTML = Object.keys(estado.categorias).map(cat => {
    const c = estado.categorias[cat];
    return `<div class="cor-cat">
      <p class="cor-nome">${escapar(c.rotulo)}${c.sub ? ` <em>· ${escapar(c.sub)}</em>` : ""}</p>
      <div class="cor-escolhas">
        ${escolha(cat, "marcador", estado.tabelas.marcador, AMOSTRA_MARCADOR, "marcador")}
        ${escolha(cat, "clipe", estado.tabelas.clipe, AMOSTRA_CLIPE, "segmento")}
      </div>
      <p class="dica">${c.quais.map(escapar).join(" · ")}</p></div>`;
  }).join("");
  if (document.activeElement !== el("ajPalavra")) el("ajPalavra").value = estado.codigo.palavra;
  const aviso = el("ajCoresAviso");
  aviso.hidden = !estado.avisos.length;
  aviso.textContent = estado.avisos.join(". ") + (estado.avisos.length ? "." : "");
  pintarLegendaDasCores(estado.codigo);
}

async function carregarCodigoDeCores() {
  if (NLE !== "resolve") return;
  try { pintarCodigoDeCores(await api("/ajustes/sinais")); }
  catch (e) { dizer("Não consegui ler o código de cores: " + e.message, false); }
}

async function gravarCodigoDeCores(pedido) {
  try { pintarCodigoDeCores(await post("/ajustes/sinais", pedido)); dizer("Código de cores guardado.", true); }
  catch (e) { dizer("Não consegui guardar o código de cores: " + e.message, false); }
}

el("ajCores").addEventListener("change", ev => {
  const s = ev.target;
  if (!s.matches || !s.matches("select[data-cat]") || !codigoDeCores) return;
  const codigo = JSON.parse(JSON.stringify(codigoDeCores));
  codigo.cores[s.dataset.cat][s.dataset.campo] = s.value;
  gravarCodigoDeCores({ codigo });
});
el("ajPalavra").addEventListener("change", () => {
  if (!codigoDeCores) return;
  gravarCodigoDeCores({ codigo: { ...codigoDeCores, palavra: el("ajPalavra").value } });
});
el("btnCoresFabrica").onclick = () => gravarCodigoDeCores({ fabrica: true });
carregarCodigoDeCores();


/* ── Atualizar timeline (organograma de 2026-09-28: dois arquivos) ────────────────────────
   Atualizar = a timeline de trabalho + a versão de onde ela veio + a versão nova. Não depende de
   a timeline ter entrado pelo De Lá Pra Cá, nem de quem enviou ter o programa. Cada versão é
   `{envio}` (a Carta do canal), `{partida}` (a cópia desta máquina) ou `{avulso, mob_id}` (um
   arquivo do disco). O Magic Link só preenche as escolhas.

   Comparar já lê a timeline de trabalho no Resolve (exporta, sem mudar nada): o serviço confere
   se a versão antiga BATE com ela (`encaixe`). Quando bate, a conferência não aparece; quando não
   bate, o resumo diz por quê e o botão Atualizar fica desligado. */
const FAIXA_AT = {
  atualizacao: { rotulo: "atualização", classe: "ok" },
  grande: { rotulo: "mudança grande", classe: "warn" },
  nova: { rotulo: "sugere importar como nova", classe: "err" },
};
const MOTIVO_AT = {
  desta_timeline: "de onde esta timeline veio",
  mesmo_nome_de_timeline: "importada com este nome",
  mesma_sequencia: "a mesma sequência do Avid",
  mesmo_nome: "o mesmo nome, outra versão",
  recente: "importada nesta máquina",
};
const CLASSES_AT = [
  ["igual", "iguais"], ["deslocado", "só deslocados"], ["aparado", "aparados ou esticados"],
  ["novo", "novos no corte"], ["retirado", "retirados"], ["trocado", "takes trocados (entram como novos)"],
];
const atOpcoes = { antiga: [], nova: [] };   // [{versao, rotulo}] — o índice é o `value` da lista
let atTimelines = [];
let atUltimo = null;                         // a última comparação: {antiga, nova, timeline}

const selDe = (lado) => el(lado === "antiga" ? "atAntiga" : "atNova");

function pintarOpcoes(lado, escolhido) {
  const sel = selDe(lado);
  sel.innerHTML = `<option value="">— escolha —</option>` + atOpcoes[lado].map((o, i) =>
    `<option value="${i}">${escapar(o.rotulo)}</option>`).join("");
  sel.value = escolhido != null && escolhido >= 0 ? String(escolhido) : "";
}

/* Acrescenta (ou reencontra) uma opção e devolve o índice dela. */
function opcao(lado, versao, rotulo) {
  const chave = JSON.stringify(versao);
  const i = atOpcoes[lado].findIndex((o) => JSON.stringify(o.versao) === chave);
  if (i >= 0) return i;
  atOpcoes[lado].push({ versao, rotulo });
  return atOpcoes[lado].length - 1;
}

function versaoDe(lado) {
  const o = atOpcoes[lado][Number(selDe(lado).value)];
  return selDe(lado).value === "" || !o ? null : o.versao;
}

/* A lista vai pela POSIÇÃO, não pelo id: pela ponte, duas timelines já devolveram o mesmo
   `GetUniqueId()` e a lista escolhia a primeira delas (medido 2026-09-28, ver `acharTimeline`). */
function timelineEscolhida() {
  return el("atTrabalho").value === "" ? null : atTimelines[Number(el("atTrabalho").value)] || null;
}

/* O Resolve exportou mesmo a timeline escolhida? Se não, nada segue (a mesma medição). */
function conferirExportada(t, tl) {
  if (t.ok && t.nome && t.nome !== tl.nome) {
    return { ok: false, erro: `o Resolve exportou “${t.nome}” em vez de “${tl.nome}” — nada foi alterado; `
      + "abra a timeline de trabalho no Resolve e tente de novo" };
  }
  return t;
}

function envioRotulo(e) {
  return `${e.nome || e.sequencia || "?"} · Magic Link ${quando(e.enviado_em)}${e.importado ? " · já importada" : ""}`;
}

async function carregarTimelines(preferida) {
  const r = await ponte().timelines();
  if (!r.ok) throw new Error(r.erro || "o Resolve não listou as timelines");
  atTimelines = r.timelines || [];
  const sel = el("atTrabalho");
  sel.innerHTML = atTimelines.map((t, i) =>
    `<option value="${i}">${escapar(t.nome)}${t.atual ? " · aberta agora" : ""}</option>`).join("");
  // pelo nome primeiro (único no projeto); o id só confirma
  const alvo = atTimelines.find((t) => preferida && t.nome === preferida.nome)
    || atTimelines.find((t) => t.atual) || atTimelines[0];
  if (alvo) sel.value = String(atTimelines.indexOf(alvo));
}

/* A versão ANTIGA sugerida: a partida da timeline de trabalho (esta máquina sabe de onde ela veio).
   ⚠️ Revisão 2026-09-28: um arquivo que o usuário escolheu por Escolher… vale mais que a sugestão
   (trocar a timeline o apagava), e uma resposta que chega DEPOIS de outra troca é descartada. */
let atSugestao = 0;
async function sugerirAntiga() {
  const vez = ++atSugestao;
  const tl = timelineEscolhida();
  let lista = [];
  try {
    lista = (await post("/receber/partidas", { timeline: tl ? { uid: tl.uid, nome: tl.nome } : null })).partidas || [];
  } catch (_) { /* sem sugestão: Escolher… continua valendo */ }
  if (vez !== atSugestao) return;
  const antes = versaoDe("antiga");
  atOpcoes.antiga = atOpcoes.antiga.filter((o) => !o.versao.partida);
  let escolhida = -1;
  for (const p of lista) {
    const i = opcao("antiga", { partida: p.id },
      `${p.timeline_nome || p.sequencia || p.id} · ${quando(p.trazido_em)} · ${MOTIVO_AT[p.motivo] || p.motivo}`);
    const forte = p.motivo === "desta_timeline" || p.motivo === "mesmo_nome_de_timeline";
    if (escolhida < 0 && forte) escolhida = i;
  }
  if (antes && antes.avulso) escolhida = opcao("antiga", antes, "");
  pintarOpcoes("antiga", escolhida);
}

/* Durante o Comparar e a execução, as escolhas ficam travadas: trocar a timeline no meio escondia o
   andamento e o resultado, e um segundo Comparar exportava em paralelo (revisão 2026-09-28). */
function travarEscolhas(sim) {
  for (const id of ["atTrabalho", "atAntiga", "atNova", "atBtnAntiga", "atBtnNova", "atComparar", "atAudio"]) {
    el(id).disabled = sim;
  }
}
const atOcupado = () => rcOcupado || atComparando;

/* As versões NOVAS que o canal já trouxe (timelines, não inserts), as pendentes primeiro. */
function oferecerNovasDoCanal() {
  const envios = (rcCaixa.envios || []).filter((e) => String(e.tipo || "").indexOf("insert") !== 0)
    .sort((a, b) => (a.importado - b.importado) || String(b.enviado_em).localeCompare(String(a.enviado_em)));
  atOpcoes.nova = atOpcoes.nova.filter((o) => !o.versao.envio);
  for (const e of envios) opcao("nova", { envio: e.id }, envioRotulo(e));
}

async function abaAtualizar() {
  el("rcAtualizar").hidden = true;
  if (!ponte() || typeof ponte().timelines !== "function") {
    dizer("abra este painel pelo Resolve (e rode o ATUALIZAR.bat se ele for antigo)", false);
    return;
  }
  try { await carregarTimelines(null); } catch (e) { dizer(e.message, false); return; }
  oferecerNovasDoCanal();
  // O envio carregado no bloco 1 que pediu "Atualizar timeline" já vem como a versão nova.
  const pedida = atNovaPedida;
  atNovaPedida = null;
  pintarOpcoes("nova", pedida ? atOpcoes.nova.findIndex((o) => o.versao.envio === pedida) : -1);
  await sugerirAntiga();
}

async function escolherVersao(lado) {
  if (atOcupado()) return;
  let r;
  try { r = await post("/receber/abrir"); } catch (e) { dizer(e.message, false); return; }
  if (r.cancelado) return;
  let i = -1;
  if (r.tipo === "carta" || r.tipo === "aaf") {   // uma timeline só no arquivo
    i = opcao(lado, { avulso: r.chave }, r.arquivo);
  } else {
    // Uma bin: cada sequência vira uma opção ("arquivo.avb › sequência").
    const seqs = r.sequencias || [];
    for (const s of seqs) {
      const j = opcao(lado, { avulso: r.chave, mob_id: s.mob_id }, `${r.arquivo} › ${s.nome || "(sem nome)"}`);
      if (i < 0) i = j;
    }
    if (seqs.length > 1) dizer(`${seqs.length} sequências em ${r.arquivo}: confira na lista qual é a versão ${lado}`, true);
  }
  pintarOpcoes(lado, i);
  atUltimo = null;
  el("rcAtualizar").hidden = true;
}

/* `reusar`: o "contar áudio" refaz só a conta, com a timeline que o Comparar acabou de exportar —
   cada exportação são segundos de Resolve e um arquivo a mais (revisão 2026-09-28). */
async function compararAtualizar(reusar) {
  const tl = timelineEscolhida();
  const antiga = versaoDe("antiga");
  const nova = versaoDe("nova");
  if (atOcupado()) return;
  if (!tl || !antiga || !nova) { dizer("escolha a timeline de trabalho, a versão antiga e a nova", false); return; }
  const anterior = reusar && atUltimo ? atUltimo.trabalho : null;
  dizer("");
  atUltimo = null;
  atComparando = true;
  travarEscolhas(true);
  el("atTitulo").textContent = `Atualizar “${tl.nome}”`;
  el("rcAtualizar").hidden = false;
  el("atAplicar").disabled = true;
  el("atBackup").textContent = "";
  el("atResumo").innerHTML = "";
  try {
    let t = anterior;
    if (!t) {
      el("atMotivo").textContent = "lendo a timeline de trabalho no Resolve (nada é alterado)…";
      try { t = conferirExportada(await ponte().exportarTrabalho({ uid: tl.uid, nome: tl.nome }), tl); }
      catch (e) { t = { ok: false, erro: e.message }; }
      if (!t.ok) {
        el("atMotivo").textContent = "";
        el("atResumo").innerHTML = `<p class="aviso">${escapar(t.erro || "o Resolve não exportou a timeline de trabalho")}</p>`;
        return;
      }
    }
    el("atMotivo").textContent = "comparando…";
    let r;
    try {
      r = await post("/receber/comparar", { antiga, nova, audio: el("atAudio").checked,
                                            trabalho: t.drt, contagem: t.contagem, inicio: t.inicio });
    } catch (e) {
      el("atMotivo").textContent = "";
      el("atResumo").innerHTML = `<p class="aviso">${escapar(e.message)}</p>`;
      return;
    }
    el("atMotivo").textContent = "";
    atUltimo = { antiga, nova, timeline: tl, nome: r.nome || "", trabalho: t };
    pintarAtualizar(r, tl);
  } finally {
    atComparando = false;
    travarEscolhas(false);
  }
}

function pintarAtualizar(r, tl) {
  const f = FAIXA_AT[r.faixa] || FAIXA_AT.grande;
  const faixas = r.faixas || [25, 60];
  const pct = Math.max(0, Math.min(100, Number(r.pct_imagem) || 0));
  const conta = r.contagem || {};
  const bate = !r.encaixe || r.encaixe.bate;
  const linhas = CLASSES_AT.map(([k, rotulo]) =>
    `<div class="at-linha"><span>${rotulo}</span><span>${Number(conta[k]) || 0}</span></div>`).join("");
  el("atResumo").innerHTML =
    (bate ? "" : `<p class="aviso">${escapar(r.encaixe.texto)}</p>`)
    + `<div class="placar"><span class="pill ${f.classe}">${pct.toLocaleString("pt-BR")}% da imagem mudou · ${f.rotulo}</span>`
    + (r.pct_audio != null ? `<span class="pill">${Number(r.pct_audio).toLocaleString("pt-BR")}% do áudio</span>` : "")
    + `</div>
     <div class="at-medida" aria-hidden="true"><i class="${f.classe}" style="width:${pct}%"></i>
       <b style="left:${faixas[0]}%"></b><b style="left:${faixas[1]}%"></b></div>
     <div class="at-marcas"><span>0%</span><span>${faixas[0]}%</span><span>${faixas[1]}%</span><span>100%</span></div>
     ${linhas}
     ${r.devolvidos ? `<div class="at-linha"><span>devolvidos pela cor (fora da conta)</span><span>${r.devolvidos}</span></div>` : ""}`;
  el("atBackup").textContent = bate
    ? `Ao atualizar, “${tl.nome}” vai para De Lá Pra Cá › Backup, com data e hora, e nunca é apagada.`
    : "";
  el("atAplicar").disabled = !bate || rcOcupado;    // pintado no fim do próprio Comparar
}

/* A execução (caminho B): a casca exporta a timeline de trabalho, o serviço reescreve e diz o que
   inserir, a casca importa a mídia nova e aplica. Cada etapa para ANTES de mexer se algo não bate,
   e a timeline do colorista nunca é apagada (vai para o Backup). */
async function executarAtualizar() {
  const u = atUltimo;
  if (!u || atOcupado()) return;
  if (!ponte() || typeof ponte().atualizar !== "function") {
    dizer("abra este painel pelo Resolve (e rode o ATUALIZAR.bat se ele for antigo)", false);
    return;
  }
  // Um registro pendente é a partida que mudou: atualizar antes dele partiria da timeline errada.
  await reenviarPendentes();
  if (registrosPendentes().length) { dizer(AVISO_PENDENTE, false); return; }
  const marcada = (id) => !!(el(id) && el(id).checked);
  rcOcupado = true;
  travarEscolhas(true);
  el("atAplicar").disabled = true;
  /* O passo, o que a casca disse por último e há quantos segundos (pedido do autor, 2026-09-28:
     o passo 4 ficava ~20 s parado sem dizer nada). O relógio conta desde a ÚLTIMA notícia: se
     ele sobe sem a frase mudar, é aquela sub-etapa que está demorando. */
  let rotulo = "", detalhe = "", desde = Date.now();
  const mostrar = () => {
    const s = Math.floor((Date.now() - desde) / 1000);
    el("atMotivo").textContent = rotulo
      ? `${rotulo}${detalhe ? ` — ${detalhe}` : ""}${s >= 2 ? ` · ${s} s` : ""}` : "";
  };
  const passo = (t) => { rotulo = t; detalhe = ""; desde = Date.now(); mostrar(); };
  const relogio = setInterval(mostrar, 1000);
  const ouvir = typeof ponte().aoAndamento === "function";
  if (ouvir) ponte().aoAndamento((t) => { detalhe = String(t || ""); desde = Date.now(); mostrar(); });
  try {
    passo("1 de 4 · exportando a sua timeline de trabalho…");
    const t = conferirExportada(await ponte().exportarTrabalho({ uid: u.timeline.uid, nome: u.timeline.nome }), u.timeline);
    if (!t.ok) throw new Error(t.erro || "o Resolve não exportou a timeline de trabalho");
    passo("2 de 4 · aplicando as mudanças da montagem…");
    const p = await post("/receber/atualizar", {
      antiga: u.antiga, nova: u.nova, trabalho: t.drt, contagem: t.contagem, inicio: t.inicio,
      marcar: marcada("rcMarcar"), colorir: marcada("rcColorir") });
    passo("3 de 4 · trazendo a mídia dos planos novos…");
    if (p.inserir && p.inserir.length) {
      try { await ponte().midias({ drt: p.drt, nome: u.timeline.nome }); } catch (_) { /* a casca avisa o que faltou */ }
    }
    passo("4 de 4 · montando a timeline atualizada…");
    const r = await ponte().atualizar({
      drt: p.drt, esperado: p.esperado, antiga: { uid: u.timeline.uid, nome: t.nome || u.timeline.nome },
      nome: p.nome || u.nome, inserir: p.inserir, marcas: p.marcas, marcar: p.marcar, colorir: p.colorir });
    if (!r.ok) throw new Error(r.erro || "o Resolve não montou a timeline atualizada");
    // A versão nova passa a ser a PARTIDA da timeline atualizada (a próxima atualização a sugere).
    const registrado = await registrar("/receber/atualizada", {
      nova: u.nova, substitui: u.antiga.partida || "", registro: p.registro || "",
      timeline: { uid: r.uid || "", nome: r.nome || "" } });
    const avisoRegistro = !registrado ? [AVISO_PENDENTE]
      : registrado.recusado ? [avisoRecusado(registrado.recusado)] : [];
    const avisos = avisoRegistro.concat(p.avisos || []).concat((r.faltaram || []).map((n) => `${n}: a mídia não entrou no pool — o plano não foi inserido`)).concat(r.conferir || []);
    el("atResumo").innerHTML =
      `<p class="previa-ok">✓ “${escapar(r.nome)}” atualizada. A anterior está em De Lá Pra Cá › Backup como “${escapar(r.backup)}”.</p>
       <div class="placar">
         <span class="pill ok">${Number(r.inseridos) || 0} plano(s) inserido(s)</span>
         ${r.marcadores ? `<span class="pill warn">${r.marcadores} marcador(es)</span>` : ""}
         ${r.cores ? `<span class="pill warn">${r.cores} plano(s) colorido(s)</span>` : ""}
         ${p.acoes && p.acoes.apagar ? `<span class="pill">${p.acoes.apagar} item(ns) saíram</span>` : ""}
         ${p.acoes && p.acoes.transicoes_removidas ? `<span class="pill warn">${p.acoes.transicoes_removidas} transição(ões) saíram</span>` : ""}
       </div>` + avisos.map((a) => `<div class="dica">⚠ ${escapar(a)}</div>`).join("");
    passo("");
    el("atBackup").textContent = "";
    atUltimo = null;
    // As escolhas se refazem para a PRÓXIMA atualização: a timeline nova, a versão que acabou de
    // entrar como antiga sugerida, e nenhuma versão nova.
    await procurarNovos(true);
    try { await carregarTimelines({ uid: r.uid, nome: r.nome }); } catch (_) { /* a lista fica */ }
    oferecerNovasDoCanal();
    pintarOpcoes("nova", -1);
    await sugerirAntiga();
  } catch (e) {
    passo("");
    dizer(e.message, false);
    el("atAplicar").disabled = false;
  } finally {
    clearInterval(relogio);
    if (ouvir) ponte().aoAndamento(null);
    rcOcupado = false;
    travarEscolhas(false);
  }
}

// Trocar uma escolha invalida a comparação anterior (e a exportação que ela guardava).
const escolhaMudou = () => { atUltimo = null; el("rcAtualizar").hidden = true; };
el("atTrabalho").onchange = () => { escolhaMudou(); sugerirAntiga(); };
el("atAntiga").onchange = escolhaMudou;
el("atNova").onchange = escolhaMudou;
el("atBtnAntiga").onclick = () => escolherVersao("antiga");
el("atBtnNova").onclick = () => escolherVersao("nova");
el("atComparar").onclick = () => compararAtualizar();
el("atAplicar").onclick = () => executarAtualizar();
el("atAudio").onchange = () => { if (atUltimo) compararAtualizar(true); };
el("atFechar").onclick = () => { el("rcAtualizar").hidden = true; atUltimo = null; };
/* A versão nova inteira, como timeline nova (o Importar de sempre). */
el("atComoNova").onclick = () => {
  const nova = versaoDe("nova");
  if (!nova || rcOcupado) return;
  const rotulo = (atOpcoes.nova[Number(el("atNova").value)] || {}).rotulo || "";
  el("rcAtualizar").hidden = true;
  atUltimo = null;
  irParaModo("aaf");
  if (nova.envio) trazer(nova.envio);
  else trazerPedido({ avulso: nova.avulso, mob_id: nova.mob_id || "" }, rotulo, null);
};


/* ── Cache e logs (organograma aprovado pelo autor em 2026-10-05) ──────────────────────────
   Três lugares: Dados (o app nunca apaga), Cache (conferências, timelines geradas, bins de
   trabalho — o app refaz; teto LRU) e Logs. No painel (⚙ Ajustes, MC e Resolve): abrir, limpar,
   abrir os logs. Na janela ⚙ Configurações do app (`?vista=configuracoes`): também o local e o
   teto. O motor abre pastas só pelo NOME (`/pasta/abrir {qual}`), nunca um caminho daqui. */
function tamanho(b) {
  const n = Number(b) || 0;
  const fmt = (x) => x.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  if (n >= 1e9) return `${fmt(n / 1e9)} GB`;
  if (n >= 1e6) return `${fmt(n / 1e6)} MB`;
  if (n >= 1e3) return `${fmt(n / 1e3)} KB`;
  return `${n} bytes`;
}

function textoUso(e) {
  const n = Number(e.arquivos) || 0;
  if (!n) return "Vazio. As conferências e as timelines geradas aparecem aqui conforme você usa o app.";
  return `${n.toLocaleString("pt-BR")} ${n === 1 ? "arquivo" : "arquivos"}: conferências e timelines geradas. `
    + "Apagar não perde trabalho: o app refaz quando precisar.";
}

/* O número que importa em destaque, com a barra até o limite (organograma de 2026-10-05: com o cache novo
   vazio, "0 bytes" em letra pequena lia como "o cache sumiu"). */
function pintarUso(prefixo, e) {
  const max = (Number(e.max_gb) || 0) * 1024 ** 3;
  const frac = max ? Math.min(1, (Number(e.bytes) || 0) / max) : 0;
  el(prefixo + "UsoGrande").textContent = tamanho(e.bytes);
  el(prefixo + "UsoDe").textContent = `de ${e.max_gb} GB`;
  const barra = el(prefixo + "UsoBarra");
  barra.style.width = `${(frac * 100).toFixed(1)}%`;
  barra.className = frac >= 0.9 ? "cheio" : "";
}

function textoIndisponivel(e) {
  return e.indisponivel
    ? `O local escolhido (${e.escolhida}) não está acessível agora: o app está usando o padrão.` : "";
}

function pintarAntigo(e) {
  for (const alvo of document.querySelectorAll("[data-cache-antigo]")) {
    const a = e && e.antigo;
    alvo.hidden = !a;
    alvo.innerHTML = a
      ? `<p class="aviso"><b>${escapar(tamanho(a.bytes))} das versões anteriores</b> continuam no lugar antigo `
        + `(${Number(a.arquivos).toLocaleString("pt-BR")} ${Number(a.arquivos) === 1 ? "arquivo" : "arquivos"}). `
        + "O app não usa mais esse cache; nada se perdeu com a mudança.</p>"
        + `<div class="acoes"><button class="sm" data-antigo="apagar">Apagar o antigo</button>`
        + `<button class="sm ghost" data-antigo="manter">Manter</button></div>`
      : "";
  }
}

function pintarCache(e) {
  el("ajCacheDir").textContent = e.dir;
  el("ajCacheUso").textContent = textoUso(e);
  pintarUso("aj", e);
  const aviso = textoIndisponivel(e);
  el("ajCacheAviso").hidden = !aviso;
  el("ajCacheAviso").textContent = aviso;
  pintarAntigo(e);
}

/* A janela de Configurações: `cfSalvo` é o que o motor tem; `cfDirNovo` o local escolhido e ainda
   não salvo (`undefined` = nenhum; `null` = o padrão). Trocar o local NÃO move nada (o novo começa
   vazio), e o Limpar fica bloqueado até salvar: limpar antes apagaria o do lugar anterior. */
let cfSalvo = null;
let cfDirNovo;

function cfMudouLocal() {
  return cfSalvo !== null && cfDirNovo !== undefined && cfDirNovo !== (cfSalvo.escolhida || null);
}

function pintarConfig(e) {
  if (e) { cfSalvo = e; cfDirNovo = undefined; el("cfTeto").value = e.max_gb; }
  if (!cfSalvo) return;
  const mudou = cfMudouLocal();
  el("cfDir").textContent = mudou ? (cfDirNovo || cfSalvo.padrao) : cfSalvo.dir;
  el("cfUso").textContent = mudou ? "Novo local: começa vazio. O cache atual não é movido."
    : textoUso(cfSalvo);
  pintarUso("cf", mudou ? { ...cfSalvo, bytes: 0, arquivos: 0 } : cfSalvo);
  el("cfLogs").textContent = cfSalvo.logs;
  el("cfLimpar").disabled = mudou;
  el("cfAbrir").disabled = mudou;
  el("cfPadrao").disabled = mudou ? cfDirNovo === null : !cfSalvo.escolhida;
  const aviso = mudou ? "Salve o novo local antes de limpar: limpar agora apagaria o do lugar anterior."
    : textoIndisponivel(cfSalvo);
  el("cfAviso").hidden = !aviso;
  el("cfAviso").textContent = aviso;
  pintarAntigo(cfSalvo);
}

async function carregarCache() {
  try {
    const e = await api("/cache");
    pintarCache(e);
    if (CONFIG_VISIVEL) pintarConfig(e);
  } catch (e) { dizer("Não consegui ler o cache: " + e.message, false); }
}

function depoisDoCache(r) {
  pintarCache(r);
  if (CONFIG_VISIVEL) pintarConfig(r);
}

async function limparCache(botao) {
  botao.disabled = true;
  try {
    const r = await post("/cache/limpar");
    depoisDoCache(r);
    dizer(`Cache limpo: ${tamanho(r.liberado.bytes)} liberados.`, true);
  } catch (e) { dizer(e.message, false); }
  finally { botao.disabled = CONFIG_VISIVEL && cfMudouLocal(); }
}

async function abrirPasta(qual) {
  try { await post("/pasta/abrir", { qual }); dizer(""); }
  catch (e) { dizer("Não consegui abrir a pasta: " + e.message, false); }
}

document.addEventListener("click", async (ev) => {
  const c = ev.target.closest("[data-cache]");
  if (c) {
    const acao = c.dataset.cache;
    if (acao === "abrir-cache") abrirPasta("cache");
    else if (acao === "abrir-logs") abrirPasta("logs");
    else if (acao === "limpar") limparCache(c);
    return;
  }
  const a = ev.target.closest("[data-antigo]");
  if (a) {
    a.disabled = true;
    try {
      const r = await post("/cache/antigo", { acao: a.dataset.antigo });
      depoisDoCache(r);
      dizer(r.liberado ? `Cache antigo apagado: ${tamanho(r.liberado.bytes)} liberados.` : "", true);
    } catch (e) { a.disabled = false; dizer(e.message, false); }
  }
});

el("cfEscolher").onclick = async () => {
  try {
    const r = await post("/escolher/pasta");
    if (!r.caminho) return;                           // cancelou
    cfDirNovo = r.caminho;
    pintarConfig();
  } catch (e) { dizer(e.message, false); }
};
el("cfPadrao").onclick = () => { cfDirNovo = null; pintarConfig(); };
el("cfAbrir").onclick = () => abrirPasta("cache");
el("cfAbrirLogs").onclick = () => abrirPasta("logs");
el("cfLimpar").onclick = () => limparCache(el("cfLimpar"));
el("cfCancelar").onclick = () => { dizer(""); carregarCache(); if (versaoInfo) pintarVersao(versaoInfo); };
el("cfSalvar").onclick = async () => {
  const pedido = { max_gb: Number(el("cfTeto").value) };
  if (cfMudouLocal()) pedido.dir = cfDirNovo;
  el("cfSalvar").disabled = true;
  try {
    const r = await post("/cache/configurar", pedido);
    depoisDoCache(r);
    if (versaoInfo && el("cfAvisar").checked !== versaoInfo.avisar) {
      pintarVersao(await post("/versao/avisar", { ligado: el("cfAvisar").checked }));
    }
    dizer(Number(r.max_gb) !== pedido.max_gb
      ? `Salvo. O tamanho máximo vai de 1 a 2000 GB: ficou ${r.max_gb} GB.` : "Configurações salvas.", true);
  } catch (e) { dizer(e.message, false); }
  finally { el("cfSalvar").disabled = false; }
};


/* ── Versão nova (organograma aprovado em 2026-10-05, `versao_nova.py`) ──────────────────────────
   O motor confere no GitHub (ao subir pelo app e a cada 6 h) e guarda; aqui só se lê. O link nunca sai
   desta página: "Baixar" pede ao motor, que abre a página da versão que ELE leu e conferiu. Nas
   Configurações, o bloco "Versão"; nos painéis, uma linha discreta no rodapé. */
let versaoInfo = null;
const TAG_VERSAO = { em_dia: "em dia", erro: "não consegui conferir", desligado: "aviso desligado" };

function pintarVersao(v) {
  versaoInfo = v;
  const nova = v.estado === "nova";
  const link = el("versaoNovaLink");
  link.hidden = !nova;
  if (nova) link.textContent = `versão nova: ${v.versao}`;
  if (!CONFIG_VISIVEL) return;
  el("cfVersaoAtual").textContent = `Você está na ${v.atual}`;
  const tag = el("cfVersaoTag");
  tag.className = `ver-tag ${v.estado}`;
  tag.textContent = nova ? `${v.versao} disponível` : (TAG_VERSAO[v.estado] || "");
  const texto = v.estado === "erro" ? "Sem internet ou o GitHub não respondeu. Tento de novo daqui a pouco." : "";
  el("cfVersaoTexto").hidden = !texto;
  el("cfVersaoTexto").textContent = texto;
  el("cfBaixar").hidden = !nova;
  if (nova) el("cfBaixar").textContent = `Baixar a ${v.versao}`;
  el("cfConferirVersao").hidden = v.estado !== "erro";
  el("cfVersaoAcoes").hidden = el("cfBaixar").hidden && el("cfConferirVersao").hidden;
  el("cfAvisar").checked = !!v.avisar;
}

async function carregarVersao(forcar) {
  try { pintarVersao(forcar ? await post("/versao/conferir") : await api("/versao")); }
  catch (_) { /* o aviso é cortesia: sem ele, o painel segue */ }
}

async function baixarVersao() {
  try { await post("/versao/baixar"); dizer(""); }
  catch (e) { dizer("Não consegui abrir a página da versão: " + e.message, false); }
}

el("versaoNovaLink").onclick = baixarVersao;
el("cfBaixar").onclick = baixarVersao;
el("cfConferirVersao").onclick = () => carregarVersao(true);
if (!VISTA_REVISAO) {
  carregarVersao(false);
  setInterval(() => { if (!document.hidden) carregarVersao(false); }, 30 * 60 * 1000);
}
