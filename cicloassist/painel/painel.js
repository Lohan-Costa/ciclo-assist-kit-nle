"use strict";

/* O painel do Ciclo Assist.
 *
 * ⚠️ **Zero lógica de domínio aqui.** Este arquivo é uma janela para o serviço: manda
 * texto, pinta eventos. Nada sobre bin, take ou corte mora no navegador — se morasse,
 * teria de existir duas vezes, porque o modelo também precisa saber.
 *
 * ⚠️ QtWebEngine 6.5 / Chrome 112 no Media Composer; **Chromium 88** no CEP do Premiere
 *    23.2 (medido). Sem `??`, sem `?.`, sem top-level await — e nada de CSS depois do 88.
 */

var conversa = document.getElementById("conversa");
/* ⭐⭐ O PALCO (F3, 2026-11-03): `conversa` é onde o turno desenha — a do chat, ou a da aba Fluxos.
 * As funções de desenho escrevem em `conversa`; quem a troca é `mostrarTela`, e NUNCA durante um
 * turno (`ocupado`): um cartão que nasce no meio da resposta cairia na aba que o editor está olhando,
 * não na conversa que o pediu. */
var conversaDoChat = conversa;
// ⚠️ A aba Fluxos saiu (N5): sobra só a conversa do chat, e o palco nunca troca.
var conversaDeFluxos = null;
var telaFluxos = null;
var abaVista = "conversa";
function qualConversa() { return conversa === conversaDeFluxos ? "fluxos" : "chat"; }
function trocarPalco() {
  if (ocupado) { return; }
  var deFluxos = abaVista === "fluxos" && conversaDeFluxos;
  conversa = deFluxos ? conversaDeFluxos : conversaDoChat;
  if (typeof entrada !== "undefined" && entrada) {
    entrada.placeholder = deFluxos
      ? "Peça um fluxo…  (ex.: prepare a diária D01)"
      : "Pergunte alguma coisa…  (/clear limpa a conversa)";
  }
}
var compositor = document.getElementById("compositor");
var entrada = document.getElementById("entrada");
var enviar = document.getElementById("enviar");
var pararConversa = document.getElementById("pararConversa");
var fioAviso = document.getElementById("fioAviso");
var ponto = document.getElementById("ponto");
var aviso = document.getElementById("aviso");

var ocupado = false;
var referencias = [];

/* ⭐⭐ Premiere ou Media Composer? A MESMA página serve os dois (P2 do Premiere,
 * 2026-09-17). No Premiere ela é carregada pela extensão CEP e — medido no 23.2 — mantém o
 * `window.__adobe_cep__` mesmo servida por HTTP. É ele que diz onde estamos, e o serviço
 * recebe o nome em toda pergunta: as ferramentas e a persona dependem disso. */
var CEP = window.__adobe_cep__ || null;
/* ⭐⭐ Na JANELA do app (`?casca=app`, 2026-10-21) não há `__adobe_cep__`: a página não está em NLE
 * nenhum, e quem diz de qual editor ela fala é o `?nle=` (escolhido pela `/conexao`, ver
 * `escolherONle`). Daqui em diante há DOIS sentidos, e trocá-los é o defeito desta seção:
 * `CEP` = "tenho evalScript" (a página está DENTRO do Premiere); `NO_PREMIERE` = "falo do
 * Premiere" (as palavras, a vigia, a busca pela ponte). */
var NLE_PEDIDO = (location.search.match(/[?&]nle=(premiere|avid)(?:&|$)/) || [])[1] || "";
var NLE = CEP ? "premiere" : (NLE_PEDIDO || "avid");
var NO_PREMIERE = NLE === "premiere";
var NOME_DO_NLE = NO_PREMIERE ? "Premiere" : "Avid";
document.documentElement.setAttribute("data-nle", NLE);

/* ⭐⭐ As palavras de cada editor, num lugar só.
 *
 * ⛔⛔ MEDIDO na tela do editor em 2026-09-21, com o painel dentro do Premiere: a aba Busca
 * dizia "monitor Source do **Media Composer**" e contava "**masterclipes**" — substantivos
 * que o Premiere não tem — sobre um `.prproj` aberto na frente dele. Nomenclatura errada
 * não é enfeite: ele lê "masterclipe" e vai procurar na tela uma coisa que não existe ali.
 * Por isso as palavras ficam AQUI, e não espalhadas: duas cópias divergem caladas. */
var PALAVRAS = NO_PREMIERE
  ? { nle: "Premiere", unidade: "clipes" }
  : { nle: "Media Composer", unidade: "masterclipes" };

/* ── estado ─────────────────────────────────────────────────────────────── */

function estado(qual) {
  ponto.dataset.estado = qual;
}

/* ⭐⭐ O que ESTA tela precisa que o serviço saiba fazer.
 *
 * ⚠️⚠️ **O painel vem do disco; as rotas vivem na memória do processo.** Dar Reload no
 * painel — que é o caminho recomendado para iterar na interface — traz a tela nova para
 * dentro de um serviço velho. Aconteceu em 2026-09-11: a engrenagem respondeu "rota
 * desconhecida" e o cartão de aprovação, "não há pergunta em andamento". Nenhum dos dois
 * era bug; era um processo de ontem atendendo uma página de hoje, e o editor foi procurar
 * defeito onde não havia.
 *
 * ⇒ A tela confere na partida e diz a única coisa que resolve: reinicie o serviço. */
var PRECISO_DE = ["conversar", "conversar/parar", "responder", "pendencias", "andamento",
                  "limpar", "atalhos", "atalhos/salvar", "atalhos/tirar",
                  "configuracoes",
                  "cache/apagar", "cache/olhar", "escolher-pasta", "abrir-pasta",
                  "projeto",
                  "vetores", "vetores/varrer", "vetores/bins", "vetores/analisar",
                  "vetores/andamento", "vetores/parar", "vetores/pasta",
                  // a aba Busca (2026-09-20): as duas buscas fora do turno do modelo
                  "busca/frase", "busca/parecidos", "busca/quadro", "busca/vocabulario",
                  "busca/carregar", "busca/recortes",
                  // o anexo pelo conteúdo e a ponte do Premiere (2026-09-17)
                  "arrastados/conteudo", "premiere/pedido", "premiere/resposta",
                  "premiere/host.jsx",
                  // o executor de fluxos e as receitas (F1, 2026-11-01)
                  "fluxo", "fluxo/pausar", "fluxo/cancelar", "fluxo/retomar", "fluxo/pular",
                  "receitas", "receitas/preparar", "receitas/escolher", "receitas/timelines"];

function conferirOServico(s) {
  var tem = s.capacidades || [];
  var faltam = PRECISO_DE.filter(function (c) { return tem.indexOf(c) < 0; });
  if (!faltam.length) { return true; }

  var quando = "";
  if (s.iniciado_em) {
    var d = new Date(s.iniciado_em * 1000);
    quando = " Ele está no ar desde " +
      d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit",
                                  hour: "2-digit", minute: "2-digit" }) + ".";
  }
  aviso.hidden = false;
  aviso.className = "aviso grave";
  aviso.dataset.de = "servico";
  aviso.textContent =
    "O serviço em execução é mais antigo que esta tela, e não conhece: " +
    faltam.join(", ") + ". Feche e abra o Ciclo Assist pelo atalho para atualizá-lo." +
    quando + " Até lá, partes do painel vão responder “rota desconhecida”.";
  estado("erro");
  return false;
}

fetch("/saude", { cache: "no-store" })
  .then(function (r) { return r.json(); })
  .then(function (s) {
    document.getElementById("versao").textContent = "v" + s.versao;
    if (conferirOServico(s)) { estado("pronto"); }
    mostrarOFio(s.fio);
    if (s.fio && !s.fio.novo) { redesenharAConversa(); }
    avisarTravamentos(s.travamentos);
  })
  .catch(function () { estado("erro"); });

/* ⭐⭐ F4 — "transformar em fluxo" (plano 2026-11-03). Terminado um trabalho de vários passos no chat, o
 * painel oferece guardá-lo como fluxo: o serviço anotou cada ESCRITA que rodou (automático ou cartão), e
 * `POST /receitas/do-chat` as liga numa receita do editor, sem turno do modelo. Ela aparece na aba Fluxos,
 * primeira e aberta (Carregar · Editar). ⚠️ Um passo só não é processo: a oferta pede dois. Uma oferta por
 * vez, no fim da conversa; depois de aceita, só volta se o chat fizer mais. */
var destaqueDosFluxos = "";
var feitosJaGuardados = 0;
function oferecerFluxo() {
  fetch("/chat/feitos", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : { feitos: [] }; })
    .then(function (d) {
      var feitos = (d && d.feitos) || [];
      if (feitos.length < feitosJaGuardados) { feitosJaGuardados = 0; }   // a conversa recomeçou
      var velha = conversaDoChat.querySelector(".oferta-fluxo");
      if (velha && !velha.dataset.feita) { velha.remove(); }
      if (feitos.length < 2 || feitos.length <= feitosJaGuardados) { return; }
      var caixa = document.createElement("div");
      caixa.className = "oferta-fluxo";
      var nomes = feitos.map(function (f) { return f.rotulo; });
      var texto = document.createElement("span");
      texto.textContent = "Este trabalho teve " + feitos.length + " passos (" +
        (nomes.length > 4 ? nomes.slice(0, 4).join(", ") + "…" : nomes.join(", ")) +
        "). Quer guardá-lo como fluxo, para rodar de novo com outros arquivos?";
      var botao = document.createElement("button");
      botao.type = "button";
      botao.className = "botao compacto";
      botao.textContent = "Transformar em fluxo";
      botao.addEventListener("click", function () {
        botao.disabled = true;
        botao.textContent = "guardando…";
        fetch("/receitas/do-chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (!res || !res.ok) {
              botao.disabled = false;
              botao.textContent = "Transformar em fluxo";
              texto.textContent = "Não deu para guardar: " + ((res && res.motivo) || "o serviço não respondeu") + ".";
              return;
            }
            feitosJaGuardados = feitos.length;
            caixa.dataset.feita = "sim";
            dispensar.textContent = "Fechar";
            texto.textContent = "✓ Virou o fluxo “" + res.titulo + "” (" + res.passos +
              " passos): ele está no menu ☰, e os nodes dele, em Fluxos e Agentes.";
            botao.disabled = false;
            botao.textContent = "Abrir Fluxos e Agentes";
            botao.onclick = null;
            var novo = botao.cloneNode(true);
            botao.replaceWith(novo);
            novo.addEventListener("click", function () { document.getElementById("botaoOficina").click(); });
          })
          .catch(function () {
            botao.disabled = false;
            botao.textContent = "Transformar em fluxo";
          });
      });
      // Dispensar: some com o cartão e vale como resposta — só volta se o chat fizer mais passos.
      var dispensar = document.createElement("button");
      dispensar.type = "button";
      dispensar.className = "botao compacto perigo";
      dispensar.textContent = "Agora não";
      dispensar.addEventListener("click", function () {
        feitosJaGuardados = feitos.length;
        caixa.remove();
      });
      var acoes = document.createElement("span");
      acoes.className = "acoes";
      acoes.appendChild(botao);       // empilhados: dois lado a lado não cabem ao lado do texto
      acoes.appendChild(dispensar);
      caixa.appendChild(texto);
      caixa.appendChild(acoes);
      conversaDoChat.appendChild(caixa);
      if (conversa === conversaDoChat) { rolarParaOFim(); }
    })
    .catch(function () { /* sem a lista, sem oferta: nada se perde */ });
}

/* ⭐⭐ A conversa que continua volta à TELA (2026-11-04). O serviço caiu no meio de um `organizar_bins`, o
 * supervisor o religou e o fio sobreviveu — mas a página recarrega ao religar (e no Reload), e a tela
 * voltava com "esta conversa continua de antes" sobre um chat vazio: o editor não via o que pediu nem
 * onde o turno parou. O serviço guarda o que a tela mostrava (`servico/historico.py`); aqui se redesenha.
 * O turno que morreu com o processo (`caiu`) mostra as ferramentas ABERTAS: a última é onde parou. */
function redesenharAConversa() {
  fetch("/conversa/historico", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : { turnos: [] }; })
    .then(function (d) {
      var turnos = (d && d.turnos) || [];
      if (!turnos.length || conversa !== conversaDoChat) { return; }
      turnos.forEach(function (t, n) {
        if (t.editor) { bloco("você", "de-mim").texto.textContent = t.editor; }
        if (t.ferramentas && t.ferramentas.length) {
          var caixa = caixaDeFerramentas();
          conversa.appendChild(caixa.raiz);
          t.ferramentas.forEach(function (f) { caixa.acrescentar({ nome: f, resumo: f, entrada: {} }); });
          caixa.parar();
          if (t.estado === "caiu") { caixa.raiz.querySelector(".cabeca").click(); }
        }
        if (t.resposta) {
          var b = bloco("ciclo assist", "de-ele");
          renderizar(b.texto, t.resposta);
          if (t.estado === "interrompido") {
            var pe = document.createElement("div");
            pe.className = "rodape";
            pe.textContent = "interrompido";
            b.raiz.appendChild(pe);
          }
        }
        if (t.erro) { bloco("problema", "de-erro").texto.textContent = t.erro; }
        // ⭐ Só no último turno: se houve outro depois, as respostas já foram na mensagem dele.
        if (t.perguntas && n === turnos.length - 1) { mostrarPerguntas(t.perguntas); }
        if (t.estado === "caiu") {
          bloco("problema", "de-erro").texto.textContent =
            "Este turno parou no meio: o serviço do Ciclo Assist caiu e foi religado. A conversa " +
            "continua — confira o que ficou feito e peça “continue” para retomar.";
        } else if (t.estado === "correndo") {
          var vivo = bloco("ciclo assist", "de-ele");
          vivo.texto.className = "texto pensando reticencias";
          vivo.texto.textContent = "ainda respondendo (a tela foi recarregada no meio)";
        }
      });
      oferecerFluxo();
      var marca = document.createElement("p");
      marca.className = "historico-fim";
      marca.textContent = "— até aqui, antes de a tela recomeçar —";
      conversa.appendChild(marca);
      rolarParaOFim();
    })
    .catch(function () { /* sem histórico, a tela fica como sempre ficou: o aviso do fio basta */ });
}

/* ⭐ A janela travou e o registro foi guardado (2026-10-30). O dump (`logs/travamentos/`) só serve se
 * alguém o ler, e o travamento reproduz raramente: o painel diz ao abrir, até ele ser lido
 * (`tools/ler_travamento.py`). ⚠️ Não passa por cima de um aviso grave (serviço velho). Clicar fecha. */
function avisarTravamentos(lista) {
  if (!lista || !lista.length || !aviso.hidden) { return; }
  var ultimo = new Date(lista[lista.length - 1].quando * 1000);
  var quando = ultimo.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit",
                                                 hour: "2-digit", minute: "2-digit" });
  aviso.hidden = false;
  aviso.className = "aviso";
  aviso.dataset.de = "travamento";
  aviso.textContent = (lista.length > 1 ? lista.length + " travamentos da janela guardados (o último em " +
                       quando + ")" : "A janela travou em " + quando + " e o registro foi guardado") +
    ". Na próxima sessão de desenvolvimento, peça para lerem o travamento. (clique para fechar)";
  aviso.onclick = function () { aviso.hidden = true; aviso.onclick = null; };
}

/* ⭐ O que ficou esperando de antes. Sem isto, "responda quando quiser" valeria só
 * enquanto a página estivesse aberta — e um **Reload** do painel, ou fechar o Media
 * Composer, apagaria um pedido que o editor ainda não decidiu. */
function carregarPendencias() {
  fetch("/pendencias", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var lista = (d && d.pendencias) || [];
      if (!lista.length) { return; }
      lista.forEach(function (p) { mostrarAprovacao(p, true); });
    })
    .catch(function () { /* sem pendência é o caso normal; não alarmar o editor */ });
}

/* ⭐⭐ O PULSO: enquanto esta página estiver viva, o serviço sabe que o editor está aqui.
 *
 * ⭐ Decisão dele (2026-09-14): abrir o Media Composer é começar do zero — a conversa não
 * atravessa o fechamento do MC, porque token gasto sem pedido é pior que contexto perdido.
 * O serviço decide isso pelo SILÊNCIO desta página (`servico/presenca.py`), e o silêncio só
 * quer dizer alguma coisa se houver barulho: sem o pulso, uma pausa de dez minutos entre
 * duas perguntas seria lida como "o painel foi embora".
 *
 * ⚠️ `/pendencias` e não uma rota nova: ela já existe, custa uma leitura de memória, passa
 * pelo porteiro do painel (que é quem registra a presença) — e ainda traz de volta um
 * cartão que tenha nascido noutra aba. O limite do serviço é 75 s: cabem três pulsos, então
 * um perdido não joga a conversa fora.
 *
 * ⚠️ Um Reload demora ~1 s e não chega perto disso — iterar na tela não custa a conversa.
 *
 * ⛔⛔ E o pulso NÃO para quando a página está escondida. O painel passa a maior parte do
 * dia atrás da janela do Media Composer enquanto o editor monta — parar aí jogaria a
 * conversa dele fora no meio do trabalho. O que precisa ser detectado é o painel MORRER
 * (fechado, ou o MC fechado com ele), e aí não há timer nenhum para parar.
 *
 * ⚠️ Webview estrangula timer de página escondida (até ~1 por minuto). Por isso o limite
 * lá são 180 s contra 20 s aqui: mesmo estrangulado, o pulso chega três vezes. */
var PULSO_MS = 20000;
setInterval(function () {
  fetch("/pendencias", { cache: "no-store" }).catch(function () {});
}, PULSO_MS);

/* ── desenhar ───────────────────────────────────────────────────────────── */

function rolarParaOFim() {
  // ⚠️ A conversa de fluxos não rola sozinha: quem rola é a TELA dela (lista, quadro e conversa juntos).
  var alvo = conversa === conversaDeFluxos && telaFluxos ? telaFluxos : conversa;
  alvo.scrollTop = alvo.scrollHeight;
}

function bloco(quem, classe) {
  var div = document.createElement("div");
  div.className = "msg " + classe;
  var rotulo = document.createElement("span");
  rotulo.className = "quem";
  rotulo.textContent = quem;
  var texto = document.createElement("div");
  texto.className = "texto";
  div.appendChild(rotulo);
  div.appendChild(texto);
  conversa.appendChild(div);
  rolarParaOFim();
  return { raiz: div, texto: texto };
}

/* ── markdown, o mínimo ──────────────────────────────────────────────────────
 *
 * O modelo escreve markdown por hábito, e o painel mostrava `**CENAS\C07.avb**` cru na
 * cara do editor. Isto resolve o que de fato aparece numa resposta sobre material:
 * negrito, código e linhas de tabela.
 *
 * ⚠️ **Construído com `createElement` e `textContent`, nunca `innerHTML`.** O texto
 * carrega nome de bin e de arquivo do cliente. Um markdown-para-HTML por substituição
 * de string transformaria um clipe chamado `<img onerror=…>` em execução — e esse é
 * exatamente o vetor que o ADR 0005 descreve, chegando pelo caminho normal do produto.
 *
 * ⚠️ Tabela não cabe em 400 px, e a persona já pede para não usar. Quando escapar uma,
 * a linha vira `a · b` em vez de canos soltos: é degradação legível, não conserto. */

function pedacosComMarca(linha, alvo) {
  // Negrito e código, na ordem em que aparecem. Sem aninhamento: não vale a pena.
  var padrao = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  var ultimo = 0;
  var achado;
  while ((achado = padrao.exec(linha)) !== null) {
    if (achado.index > ultimo) {
      alvo.appendChild(document.createTextNode(linha.slice(ultimo, achado.index)));
    }
    var marca = document.createElement(achado[1] ? "strong" : "code");
    marca.textContent = achado[1] || achado[2];
    alvo.appendChild(marca);
    ultimo = padrao.lastIndex;
  }
  if (ultimo < linha.length) {
    alvo.appendChild(document.createTextNode(linha.slice(ultimo)));
  }
}

function renderizar(alvo, bruto) {
  alvo.textContent = "";
  var linhas = bruto.split("\n");
  var saida = [];

  linhas.forEach(function (linha) {
    var limpa = linha.trim();
    // A linha separadora de uma tabela markdown não carrega informação nenhuma.
    if (/^\|[\s|:-]+\|?$/.test(limpa)) { return; }
    if (limpa.indexOf("|") === 0) {
      var celulas = limpa.replace(/^\||\|$/g, "").split("|").map(function (c) {
        return c.trim();
      }).filter(function (c) { return c.length; });
      saida.push(celulas.join(" · "));
      return;
    }
    saida.push(linha);
  });

  saida.forEach(function (linha, i) {
    if (i) { alvo.appendChild(document.createElement("br")); }
    pedacosComMarca(linha, alvo);
  });
}

/* ── as ferramentas, num toggle ──────────────────────────────────────────────
 *
 * ⭐⭐ **Colapsado por padrão, e isto veio do uso.** Um pedido de corte chama trinta
 * ferramentas, e trinta linhas de `ler_o_que_ja_sabemos` empurravam a conversa inteira
 * para fora da tela: o editor rolava para achar a resposta no meio do maquinário.
 *
 * ⚠️ Mas some para o alto, NÃO da vista: enquanto o modelo trabalha, a linha de
 * atividade diz o que está acontecendo agora. Um painel que fica mudo durante quarenta
 * segundos de transcrição parece travado — e o editor fecha e reabre, que é a pior
 * coisa que ele pode fazer no meio de um turno. */

/* Os argumentos de uma chamada, numa linha legível.
 *
 * ⚠️ Uma LISTA de objetos vira a contagem dela. Sem isto sai
 * `[object Object],[object Object],…` — foi o que apareceu na tela do editor no teste de
 * campo, num `montar_corte` de catorze cortes. */
function resumoDosArgumentos(entrada) {
  return Object.keys(entrada || {}).map(function (k) {
    var v = entrada[k];
    if (Array.isArray(v)) {
      return v.length + (v.length === 1 ? " item" : " itens");
    }
    if (v && typeof v === "object") { return k; }
    return String(v);
  }).join(" · ");
}

function caixaDeFerramentas() {
  var caixa = document.createElement("div");
  caixa.className = "ferramentas";
  caixa.dataset.aberto = "nao";

  var cabeca = document.createElement("button");
  cabeca.type = "button";
  cabeca.className = "cabeca";
  // ⚠️ O resumo colapsável só aparece no FIM. Durante o turno o editor quer ver o que
  //    está acontecendo; depois, ele quer o espaço de volta.
  cabeca.hidden = true;
  var seta = document.createElement("span");
  seta.className = "seta";
  seta.textContent = "▸";
  var conta = document.createElement("span");
  conta.className = "conta";
  cabeca.appendChild(seta);
  cabeca.appendChild(conta);

  // A linha do AGORA: o que está acontecendo, quanto já foi, e há quanto tempo.
  var atividade = document.createElement("div");
  atividade.className = "atividade";

  var oQue = document.createElement("span");
  oQue.className = "o-que reticencias";
  var quanto = document.createElement("span");
  quanto.className = "quanto";
  var relogio = document.createElement("span");
  relogio.className = "relogio";
  atividade.appendChild(oQue);
  atividade.appendChild(quanto);
  atividade.appendChild(relogio);

  var barra = document.createElement("div");
  barra.className = "barra";
  var cheio = document.createElement("i");
  barra.appendChild(cheio);
  barra.hidden = true;

  // O que já foi feito, em português, visível enquanto o turno corre.
  var feitos = document.createElement("div");
  feitos.className = "feitos";

  var lista = document.createElement("div");
  lista.className = "lista";
  lista.hidden = true;

  cabeca.addEventListener("click", function () {
    var abrindo = caixa.dataset.aberto === "nao";
    caixa.dataset.aberto = abrindo ? "sim" : "nao";
    seta.textContent = abrindo ? "▾" : "▸";
    lista.hidden = !abrindo;
  });

  caixa.appendChild(cabeca);
  caixa.appendChild(feitos);
  caixa.appendChild(atividade);
  caixa.appendChild(barra);
  caixa.appendChild(lista);

  /* ⭐⭐ O relógio do turno.
   *
   * O editor perguntou por ele com todas as letras, e a razão é a mesma da barra: uma
   * espera sem número não tem tamanho. "Faz 40 s" é uma informação — ele decide se vai
   * buscar um café ou se espera olhando. "Está pensando" não é. */
  var comecou = Date.now();
  // ⭐ Quando chegou o último sinal do modelo. Pedido do editor (2026-09-16): 10 min
  //   parado sem saber se era lentidão ou travamento. Relógio andando não responde isso;
  //   "sem sinal há 4 min" responde.
  var ultimoSinal = Date.now();
  // ⭐ Desde quando o modelo pensa sem mostrar o raciocínio (o Sonnet 5 não o mostra).
  //   Nesse silêncio a frase certa é "pensando há", não "sem sinal há" (ensaio da C07,
  //   2026-10-22: 5 min de "sem sinal" lidos como transcrição travada).
  var pensandoDesde = 0;
  var tokens = 0;
  var gastoDoTurno = 0;
  function pintarRelogio() {
    var s = Math.round((Date.now() - comecou) / 1000);
    var tempo = s < 60 ? s + "s"
      : Math.floor(s / 60) + "min " + String(s % 60).padStart(2, "0") + "s";
    // ⚠️ Dois números diferentes, e a diferença importa: `↓` é o que a conversa PESA
    //    agora (a ocupação da janela), e `Σ` é o que o turno GASTOU somando todas as idas
    //    e voltas. O segundo é maior que o primeiro por desenho.
    var partes = [tempo];
    if (tokens) { partes.push("↓ " + emMil(tokens)); }
    if (gastoDoTurno) { partes.push("Σ " + emMil(gastoDoTurno)); }
    var parado = Math.round((Date.now() - ultimoSinal) / 1000);
    if (pensandoDesde) {
      var p = Math.round((Date.now() - pensandoDesde) / 1000);
      partes.push("pensando há " + (p < 60 ? p + "s"
        : Math.floor(p / 60) + "min " + String(p % 60).padStart(2, "0") + "s"));
    } else if (parado >= 30) {
      partes.push("sem sinal há " + (parado < 60 ? parado + "s"
        : Math.floor(parado / 60) + "min " + String(parado % 60).padStart(2, "0") + "s"));
    }
    relogio.textContent = partes.join(" · ");
  }
  var tique = setInterval(pintarRelogio, 1000);
  pintarRelogio();

  var quantas = 0;
  return {
    raiz: caixa,

    /* Qualquer evento do turno conta como sinal de vida. */
    sinal: function () { ultimoSinal = Date.now(); },

    /* Quanto a conversa já pesa, ao vivo. Chega no `message_start` de cada volta do
     * modelo — é o que dá número à espera, em vez de só reticências. */
    tokens: function (quantos) {
      tokens = quantos;
      pintarRelogio();
    },

    /* O que o turno inteiro consumiu, somando as idas e voltas. Chega no fim. */
    gasto: function (dado) {
      gastoDoTurno = (dado && dado.tokens) || 0;
      if (dado && dado.custo_usd) {
        relogio.title = "gasto do turno: " + emMil(gastoDoTurno) + " tokens · US$ " +
          dado.custo_usd.toFixed(3);
      }
      pintarRelogio();
    },

    /* O que a ferramenta está fazendo por dentro, e quanto já andou. */
    progresso: function (dado) {
      pensandoDesde = dado.pensando ? (pensandoDesde || Date.now()) : 0;
      oQue.textContent = dado.etapa || "";
      if (dado.fracao === null || dado.fracao === undefined) {
        // ⚠️ Sem fração NÃO se mostra 0%: é diferente de "não começou". A barra some e
        //    as reticências continuam dizendo que há movimento.
        barra.hidden = true;
        quanto.textContent = "";
      } else {
        barra.hidden = false;
        cheio.style.width = Math.round(dado.fracao * 100) + "%";
        quanto.textContent = Math.round(dado.fracao * 100) + "%";
      }
      rolarParaOFim();
    },

    vazia: function () { return quantas === 0; },
    acrescentar: function (dado) {
      quantas += 1;
      conta.textContent = quantas + (quantas === 1 ? " consulta ao projeto"
                                                   : " consultas ao projeto");
      // Ferramenta nova recomeça a contagem: o que a anterior relatou já passou.
      barra.hidden = true;
      quanto.textContent = "";

      // ⭐⭐ A LINHA QUE O EDITOR LÊ, visível na conversa enquanto acontece: um verbo e
      //    um alvo ("Ouve o take C07_P02-T002"), como as linhas do Claude Code. O nome
      //    técnico e os argumentos continuam existindo, dentro do toggle, para quando
      //    ele quiser conferir o caminho.
      var feito = document.createElement("div");
      feito.className = "feito";
      var pino = document.createElement("span");
      pino.className = "pino";
      pino.textContent = "●";
      var frase = document.createElement("span");
      frase.textContent = dado.resumo || dado.nome.replace(/_/g, " ");
      feito.appendChild(pino);
      feito.appendChild(frase);
      feitos.appendChild(feito);

      var linha = document.createElement("div");
      linha.className = "ferramenta";
      var nome = document.createElement("b");
      nome.textContent = dado.nome;
      linha.appendChild(nome);

      // ⚠️ `textContent`, nunca `innerHTML`: os argumentos carregam nome de bin e de
      // arquivo do cliente. Um clipe chamado `<img onerror=…>` é improvável e é
      // exatamente o tipo de coisa que não se descobre em teste.
      var arg = document.createElement("span");
      arg.className = "arg";
      arg.textContent = resumoDosArgumentos(dado.entrada);
      linha.appendChild(arg);
      lista.appendChild(linha);

      // A linha de atividade mostra o AGORA, na mesma língua das outras.
      oQue.textContent = dado.resumo || dado.nome.replace(/_/g, " ");
      rolarParaOFim();
    },
    parar: function () {
      // ⭐⭐ Fim do turno: as linhas do que foi feito se recolhem atrás do resumo. É a
      //    conciliação dos dois pedidos do editor — ver o que está acontecendo AGORA, e
      //    não ter trinta linhas de histórico empurrando a conversa para fora da tela.
      clearInterval(tique);
      atividade.remove();
      barra.remove();
      feitos.remove();
      cabeca.hidden = false;
    },
  };
}

/* ── o portão ────────────────────────────────────────────────────────────────
 *
 * ⭐ O editor aprova o que VAI ACONTECER, não a mecânica. Por isso o cartão mostra o
 * nome da ação em português e os argumentos legíveis — não `mcp__ciclo__…` com JSON.
 *
 * ⭐⭐ **Ninguém está esperando do outro lado, e o cartão não tem pressa** (ADR 0008). O
 * turno que gerou este pedido já terminou: a caixa de texto está livre, o editor pode
 * conversar, ir ao Avid conferir o material, sair para o almoço. O cartão fica. Quando
 * ele clicar, é o `POST /responder` que executa a ação — não o modelo.
 *
 * ⚠️ Por isso o cartão é o ÚNICO pedaço da conversa que sobrevive ao fim do turno, e o
 * único que volta sozinho quando a página recarrega (`GET /pendencias`). */

var aprovacoes = {};

/* Um item qualquer de uma lista de objetos — o caminho de qualquer ferramenta futura. */
function itemGenerico(item) {
  var li = document.createElement("li");
  var curtos = [];
  var longos = [];
  Object.keys(item || {}).forEach(function (ck) {
    var cv = item[ck];
    if (cv === null || cv === undefined || cv === "") { return; }
    var txt = String(cv);
    // Prosa vai para a própria linha; o resto se junta numa só.
    if (txt.length > 34) { longos.push(txt); } else { curtos.push(txt); }
  });
  var cab = document.createElement("div");
  cab.className = "cab";
  cab.textContent = curtos.join(" · ");
  li.appendChild(cab);
  longos.forEach(function (txt) {
    var p = document.createElement("div");
    p.className = "prosa";
    p.textContent = txt;   // ⚠️ nunca innerHTML: vem do projeto do cliente
    li.appendChild(p);
  });
  return li;
}

/* ⭐ Como o SOM corta neste plano, em uma frase de editor.
 *
 * ⚠️ "antes"/"depois" é o vocabulário do PLANO, não o da tela: sozinho, "antes" não diz
 * antes de quê. Aqui ele vira a coisa que o editor reconhece — corte em J, corte em L. */
function comoOSomCorta(item) {
  var frames = item.som_frames || 0;
  if (item.corte_de_som === "antes" && frames) {
    return "som entra " + frames + "f antes (J)";
  }
  if (item.corte_de_som === "depois" && frames) {
    return "som segura " + frames + "f (L)";
  }
  return "";
}

/* ⭐⭐ Um corte do plano, e é o que o editor lê para decidir.
 *
 * Duas colunas: à ESQUERDA por que este take, à DIREITA o que se ouve. São as duas
 * perguntas que ele faz corte a corte, e em texto corrido elas se misturavam — a
 * justificativa e a fala viravam um parágrafo só, na mesma cor.
 *
 * ⚠️ `textContent` em tudo: take, fala e justificativa vêm do projeto do cliente. */
function corteDoPlano(item) {
  var li = document.createElement("li");

  var cab = document.createElement("div");
  cab.className = "cab";
  var pedacos = [item.take];
  if (item.duracao_frames) { pedacos.push(item.duracao_frames + "f"); }
  if (item.inicio_no_take) { pedacos.push("de " + item.inicio_no_take + "f"); }
  cab.textContent = pedacos.join(" · ");

  var som = comoOSomCorta(item);
  if (som) {
    // O L/J ganha destaque próprio: é a diferença entre o que o editor pediu e o que
    // ele vai ver, e some se ficar no meio dos outros números.
    var marca = document.createElement("span");
    marca.className = "lj";
    marca.textContent = som;
    cab.appendChild(document.createTextNode(" "));
    cab.appendChild(marca);
  }
  li.appendChild(cab);

  var porque = document.createElement("div");
  porque.className = "porque";
  porque.textContent = item.porque || "";

  if (item.fala) {
    // Duas colunas só quando HÁ as duas coisas. Uma coluna vazia ao lado de um texto
    // espremido é pior que uma linha inteira: o painel tem 400 px, e metade é pouco.
    var grade = document.createElement("div");
    grade.className = "duas-colunas";
    grade.appendChild(porque);

    var fala = document.createElement("div");
    fala.className = "fala";
    fala.textContent = "“" + item.fala + "”";
    grade.appendChild(fala);
    li.appendChild(grade);
  } else {
    li.appendChild(porque);
  }

  // ⛔ Procedência sempre, e discreta: item sem ela é bug, não item — mas ela é para
  //    conferir, não para ler em cada linha.
  var proc = [item.confianca, item.fonte].filter(Boolean).join(" · ");
  if (proc) {
    var p = document.createElement("div");
    p.className = "procedencia";
    p.textContent = proc;
    li.appendChild(p);
  }
  return li;
}

/* ⭐ Uma edição na timeline do editor, em uma frase — é o que ele aprova.
 *
 * Sem isto o `itemGenerico` desenhava "inserir · 01:02:33:11 · 48 · 07-01-02 · 2600 · V2":
 * cada número sem dizer do que é, num pedido que regrava a bin dele. */
var EDICOES = { extrair: 1, abrir_espaco: 1, inserir: 1 };

function edicaoDoPlano(item) {
  var li = document.createElement("li");
  var cab = document.createElement("div");
  cab.className = "cab";
  var frase;
  if (item.tipo === "extrair") {
    frase = "tirar " + item.de + " → " + item.ate + " de todas as trilhas, e colar";
  } else if (item.tipo === "abrir_espaco") {
    frase = "abrir " + item.duracao_frames + "f de espaço em " + item.em + ", empurrando tudo";
  } else {
    var onde = [item.imagem_em].concat(item.som_em || []).filter(Boolean).join(" ");
    frase = "inserir " + item.duracao_frames + "f de " + item.clipe +
      (item.in_no_clipe ? " (a partir do " + item.in_no_clipe + "f)" : "") +
      " em " + item.em + (onde ? ", em " + onde : "") + ", empurrando tudo";
  }
  cab.textContent = frase;   // ⚠️ textContent: o nome do clipe vem do projeto do cliente
  li.appendChild(cab);
  return li;
}

/* ⭐ Uma fala separada: o número do momento, o texto, e em que takes ela está.
 *
 * ⚠️ Sem isto o `itemGenerico` desenharia "[object Object]" no lugar dos trechos — o
 *    pedido de uma bin inteira aprovado sem ler de onde vem cada fala. */
function falaSeparada(item) {
  var li = document.createElement("li");
  var cab = document.createElement("div");
  cab.className = "cab";
  var rotulo = "FALA" + String(item.fala).padStart(2, "0") +
    (item.variante > 1 ? "." + String(item.variante).padStart(2, "0") : "");
  var takes = (item.trechos || []).map(function (t) { return t.take; });
  cab.textContent = [rotulo, item.personagem, takes.length +
    (takes.length === 1 ? " take" : " takes")].filter(Boolean).join(" · ");
  li.appendChild(cab);

  var texto = document.createElement("div");
  texto.className = "fala";
  texto.textContent = "“" + (item.texto || "") + "”";
  li.appendChild(texto);

  var onde = document.createElement("div");
  onde.className = "procedencia";
  onde.textContent = takes.join(", ");
  li.appendChild(onde);
  if (item.porque) {
    var porque = document.createElement("div");
    porque.className = "porque";
    porque.textContent = item.porque;
    li.appendChild(porque);
  }
  return li;
}

/* ⭐ O que ficou de FORA de uma separação de falas, com o porquê — lido ANTES de aprovar.
 * ⛔ Tem de vir antes do `item.take` na escolha do desenho: um item com take seria
 *    desenhado como corte de montagem, e o editor leria um corte que não existe. */
function deixadaDeFora(item) {
  var li = document.createElement("li");
  var cab = document.createElement("div");
  cab.className = "cab";
  cab.textContent = [item.roteiro ? "roteiro " + item.roteiro : "", item.take]
    .filter(Boolean).join(" · ") || "de fora";
  li.appendChild(cab);
  var porque = document.createElement("div");
  porque.className = "porque";
  porque.textContent = item.porque || "";
  li.appendChild(porque);
  return li;
}

/* ⭐ Uma operação de organizar o projeto do Premiere, em uma linha que se lê de uma vez:
 * "criar bin MIDIAS · dentro da raiz". O editor aprova a LISTA inteira num clique, então
 * cada linha precisa dizer o que vai acontecer sem ele abrir nada. */
function operacaoNoProjeto(item) {
  var li = document.createElement("li");
  var cab = document.createElement("div");
  cab.className = "cab";
  var porque = document.createElement("div");
  porque.className = "porque";

  if (item.acao === "criar_bin") {
    cab.textContent = "criar bin " + (item.nome || "?");
    porque.textContent = "dentro de " + (item.dentro_de || "raiz do projeto");
  } else if (item.acao === "mover") {
    cab.textContent = "mover " + (item.item || "?");
    porque.textContent = "para " + (item.para || "raiz do projeto");
  } else {
    cab.textContent = "renomear " + (item.item || "?");
    porque.textContent = "para " + (item.nome || "?");
  }
  li.appendChild(cab);
  li.appendChild(porque);
  return li;
}

/* ⭐ As perguntas de um agente: uma caixa por pergunta (pedido do autor, 2026-11-08: uma mensagem só com todas as respostas é difícil de
 * escrever). O envio é uma mensagem normal do editor, então o modelo não precisa de caminho novo. Caixa em branco NÃO é "não sei": é dita à parte. */
var perguntasNaTela = {};
var NAO_SEI = "não sei";

function caixaDeResposta(p, aoMudar) {
  var linha = document.createElement("div");
  linha.className = "pergunta";
  var enunciado = document.createElement("div");
  enunciado.className = "enunciado";
  enunciado.textContent = p.texto;
  linha.appendChild(enunciado);
  if (p.exemplo) {
    var exemplo = document.createElement("div");
    exemplo.className = "exemplo";
    exemplo.textContent = p.exemplo;
    linha.appendChild(exemplo);
  }
  var caixa = document.createElement("textarea");
  caixa.rows = 1;
  caixa.className = "resposta";
  caixa.setAttribute("aria-label", p.texto);
  function ajustar() {
    caixa.style.height = "auto";
    caixa.style.height = Math.min(caixa.scrollHeight + 2, 72) + "px";
    aoMudar();
  }
  caixa.addEventListener("input", ajustar);
  linha.appendChild(caixa);
  var opcoes = (p.opcoes || []).concat(p.nao_sei ? [NAO_SEI] : []);
  if (opcoes.length) {
    var faixa = document.createElement("div");
    faixa.className = "opcoes";
    opcoes.forEach(function (valor) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.textContent = valor;
      chip.addEventListener("click", function () { caixa.value = valor; ajustar(); });
      faixa.appendChild(chip);
    });
    linha.appendChild(faixa);
  }
  return { raiz: linha, caixa: caixa, pergunta: p };
}

function textoDasRespostas(itens) {
  var ditas = itens.filter(function (i) { return i.caixa.value.trim(); });
  var vazias = itens.filter(function (i) { return !i.caixa.value.trim(); });
  var linhas = ["Minhas respostas:"].concat(ditas.map(function (i) {
    return "- " + i.pergunta.sobre + ": " + i.caixa.value.trim().replace(/\s+/g, " ");
  }));
  if (vazias.length) {
    linhas.push("Sem resposta por enquanto: " + vazias.map(function (i) { return i.pergunta.sobre; }).join("; "));
  }
  return linhas.join("\n");
}

function mostrarPerguntas(dado) {
  if (perguntasNaTela[dado.id]) { return; }
  var cartao = document.createElement("div");
  cartao.className = "aprovacao perguntas";
  perguntasNaTela[dado.id] = cartao;

  var titulo = document.createElement("div");
  titulo.className = "cabeca";
  titulo.textContent = dado.titulo;
  cartao.appendChild(titulo);

  var enviarRespostas = document.createElement("button");
  enviarRespostas.type = "button";
  enviarRespostas.className = "permitir";
  var nota = document.createElement("div");
  nota.className = "aviso-receita";
  var itens = [];
  function contar() {
    var n = itens.filter(function (i) { return i.caixa.value.trim(); }).length;
    enviarRespostas.disabled = !n;
    enviarRespostas.textContent = n === itens.length ? "Enviar respostas" : "Enviar " + n + " de " + itens.length;
    nota.textContent = "";
  }
  itens = (dado.perguntas || []).map(function (p) { return caixaDeResposta(p, contar); });
  itens.forEach(function (item, n) {
    cartao.appendChild(item.raiz);
    // Enter vai para a próxima caixa: quem responde a primeira não pode mandar o cartão pela metade sem querer.
    item.caixa.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        (itens[n + 1] ? itens[n + 1].caixa : enviarRespostas).focus();
      }
    });
  });

  var acoes = document.createElement("div");
  acoes.className = "acoes";
  acoes.appendChild(enviarRespostas);
  cartao.appendChild(acoes);
  cartao.appendChild(nota);
  contar();

  enviarRespostas.addEventListener("click", function () {
    // ⚠️ O cartão nasce no meio do turno: enviar agora perderia as respostas (`perguntar` ignora quando está ocupado).
    if (ocupado) { nota.textContent = "Ainda estou escrevendo. Envie assim que eu terminar."; return; }
    var texto = textoDasRespostas(itens);
    itens.forEach(function (i) { cartao.removeChild(i.raiz); });
    cartao.classList.add("decidida");
    cartao.setAttribute("data-decisao", "sim");
    acoes.className = "veredito";
    acoes.textContent = "respostas enviadas";
    nota.textContent = "";
    ultimaPergunta = texto;
    perguntar(texto);
  });

  conversa.appendChild(cartao);
  rolarParaOFim();
}

function mostrarAprovacao(dado, deAntes) {
  // ⚠️ O mesmo pedido pode chegar por dois caminhos — o evento do turno e o
  //    `GET /pendencias` do carregamento. Dois cartões para um pedido é exatamente a
  //    confusão que o teste de campo produziu; aqui ela não pode voltar pela porta nova.
  if (aprovacoes[dado.id]) { return; }

  var cartao = document.createElement("div");
  cartao.className = "aprovacao";

  var titulo = document.createElement("div");
  titulo.className = "cabeca";
  titulo.textContent = "Posso " + dado.ferramenta + "?";
  cartao.appendChild(titulo);

  // Um pedido que atravessou o fechamento do painel precisa se apresentar: o editor não
  // tem como lembrar de uma conversa que ele não está vendo na tela.
  if (deAntes) {
    var lembrete = document.createElement("div");
    lembrete.className = "de-antes";
    lembrete.textContent = "ficou esperando sua resposta";
    cartao.appendChild(lembrete);
  }

  var entrada = dado.entrada || {};
  // ⭐ Um FLUXO (`fluxo.js`): o plano inteiro, passo a passo, com os valores preenchidos.
  var chaves = Object.keys(entrada);
  if (entrada.plano && Array.isArray(entrada.plano.passos) && window.cartaoDoFluxo) {
    window.cartaoDoFluxo(cartao, entrada);
    chaves = [];
  }
  chaves.forEach(function (k) {
    var v = entrada[k];

    // ⭐ Uma LISTA de objetos é um plano — e o editor aprova **corte a corte**, não um
    // JSON. Sem isto a linha sairia `[object Object],[object Object]`, que é pedir
    // aprovação para algo ilegível: o pior jeito de ter um "sim".
    if (Array.isArray(v) && v.length && typeof v[0] === "object" && v[0] !== null) {
      var titulo = document.createElement("div");
      titulo.className = "campo";
      var rt = document.createElement("span");
      rt.className = "rot";
      rt.textContent = k;
      var qt = document.createElement("span");
      qt.textContent = v.length + (v.length === 1 ? " item" : " itens");
      titulo.appendChild(rt);
      titulo.appendChild(qt);
      cartao.appendChild(titulo);

      var lista = document.createElement("ol");
      lista.className = "itens";
      v.forEach(function (item) {
        lista.appendChild(k === "deixadas_de_fora" ? deixadaDeFora(item || {})
          : item && item.acao ? operacaoNoProjeto(item)
          : item && item.take ? corteDoPlano(item)
          : item && EDICOES[item.tipo] ? edicaoDoPlano(item)
          : item && Array.isArray(item.trechos) ? falaSeparada(item) : itemGenerico(item));
      });
      cartao.appendChild(lista);
      return;
    }

    var linha = document.createElement("div");
    linha.className = "campo";
    var rot = document.createElement("span");
    rot.className = "rot";
    rot.textContent = k;
    var val = document.createElement("span");
    // ⚠️ `textContent`: os argumentos carregam nome de bin e de arquivo do cliente.
    val.textContent = typeof v === "string" ? v : JSON.stringify(v);
    linha.appendChild(rot);
    linha.appendChild(val);
    cartao.appendChild(linha);
  });

  var acoes = document.createElement("div");
  acoes.className = "acoes";

  var nao = document.createElement("button");
  nao.type = "button";
  nao.className = "recusar";
  nao.textContent = "Não";

  var sim = document.createElement("button");
  sim.type = "button";
  sim.className = "permitir";
  sim.textContent = "Pode fazer";

  // ⭐⭐ É o clique que FAZ a coisa acontecer, não o modelo (ADR 0008). Este POST não
  //    "responde uma pergunta pendente": ele executa a ação com os argumentos que estão
  //    desenhados acima, e a resposta dele já traz o resultado. Por isso o cartão espera
  //    aqui, e não no fluxo da conversa — o turno que gerou este pedido pode ter
  //    terminado ontem.
  function decidir(permitido) {
    sim.disabled = nao.disabled = true;
    var parar = function () {};
    if (permitido) { trabalhando(acoes); parar = acompanharAcao(acoes); }

    fetch("/responder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: dado.id, permitido: permitido })
    })
      .then(function (r) { return r.json(); })
      .then(function (resposta) { parar(); concluir(cartao, acoes, permitido, resposta); })
      .catch(function () {
        parar();
        // ⚠️ Falhar aqui é diferente de recusar: a ação pode ter acontecido. Dizer
        // "não deu" seria mentir tão feio quanto dizer "pronto".
        acoes.className = "veredito";
        acoes.textContent = "Não consegui falar com o serviço. Confira no Avid.";
      });
  }

  nao.addEventListener("click", function () { decidir(false); });
  sim.addEventListener("click", function () { decidir(true); });

  // ⚠️ O "Não" vem ANTES na ordem do DOM: quem navega por teclado chega nele primeiro,
  // e o gesto de menor consequência deve ser o mais fácil de alcançar.
  acoes.appendChild(nao);
  acoes.appendChild(sim);
  cartao.appendChild(acoes);

  // ⭐⭐ "Salvar" no cartão de um plano feito na conversa (autor, 2026-11-04): quem não conhece o
  //    app não sabe que pode pedir "guarde como receita" — o botão mostra que dá. Não decide o
  //    cartão (Não / Pode fazer continuam), e o serviço guarda o plano da PENDÊNCIA, não o da página.
  //    ⚠️ Plano que já veio de uma receita (`receita_de`) não tem o que guardar: sem botão.
  if (entrada.plano && !entrada.receita_de) {
    var salvar = document.createElement("button");
    salvar.type = "button";
    salvar.className = "salvar-receita";
    salvar.textContent = "Salvar";
    salvar.title = "Guardar este plano como receita, para rodar de novo em Fluxos prontos";
    var aviso = document.createElement("div");
    aviso.className = "aviso-receita";
    aviso.hidden = true;
    salvar.addEventListener("click", function () {
      salvar.disabled = true;
      salvar.textContent = "salvando…";
      fetch("/receitas/salvar-plano", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: dado.id })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          aviso.hidden = false;
          if (d && d.ok) {
            salvar.textContent = "✓ salva";
            aviso.textContent = "Guardada como receita “" + (d.titulo || d.receita) +
              "” — está em Fluxos prontos.";
            if (window.telaDeFluxos) { window.telaDeFluxos(); }
          } else {
            salvar.disabled = false;
            salvar.textContent = "Salvar";
            aviso.textContent = "Não consegui guardar: " + ((d && d.motivo) || "sem resposta do serviço");
          }
        })
        .catch(function () {
          salvar.disabled = false;
          salvar.textContent = "Salvar";
          aviso.hidden = false;
          aviso.textContent = "Não consegui falar com o serviço.";
        });
    });
    acoes.appendChild(salvar);
    cartao.appendChild(aviso);
  }

  // ⭐ O cartão de um FLUXO vai para a aba Fluxos (2026-11-03): é lá que o editor o preparou, e é
  //   lá que o andamento aparece depois do clique.
  var doFluxo = entrada.plano && window.destinoDoFluxo && window.destinoDoFluxo();
  if (doFluxo) {
    doFluxo.appendChild(cartao);
    aprovacoes[dado.id] = cartao;
    if (deAntes) { return; }
    mostrarTela("fluxos");
    cartao.scrollIntoView({ block: "nearest" });
    sim.focus();
    return;
  }
  conversa.appendChild(cartao);
  aprovacoes[dado.id] = cartao;
  rolarParaOFim();
  sim.focus();
}

/* ⚠️ "Fazendo…" não é enfeite: escrever a bin e abrir no Avid leva segundos, e um cartão
 *    que some sem dizer nada faz o editor clicar de novo. */
function trabalhando(acoes) {
  acoes.className = "veredito trabalhando reticencias";
  acoes.textContent = "fazendo…";
}

/* ⭐⭐ O QUE está sendo feito, enquanto é feito (Assist anterior, 2026-09-19).
 *
 * A ação aprovada roda fora do turno, então o progresso que as ferramentas relatam não
 * chegava aqui: o cartão dizia "fazendo…" do começo ao fim, e um `separar_falas` ou um
 * sync levam minutos — indistinguível de travado. O serviço guarda o relato da ação em
 * execução (`servico/pendencias.relatar`) e esta função pergunta por ele enquanto o
 * `/responder` não volta.
 *
 * ⚠️ Sem fração NÃO se mostra 0%: é a mesma regra da barra da conversa — porcentagem
 * parada em zero é a própria imagem de travamento. O relógio, esse, anda sempre, e é ele
 * que diz "vivo" quando não há etapa nenhuma. */
function acompanharAcao(acoes) {
  var comecou = Date.now();
  function relogio(ms) {
    var s = Math.max(0, Math.round(ms / 1000));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }
  function tique() {
    fetch("/andamento", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (a) {
        if (!acoes.classList.contains("trabalhando")) { return; }
        var partes = [(a && a.etapa) || "fazendo"];
        if (a && a.fracao !== null && a.fracao !== undefined) {
          partes.push(Math.round(a.fracao * 100) + "%");
        }
        partes.push(relogio(Date.now() - comecou));
        // ⚠️ Sem "…" aqui: a classe `.reticencias` já anima os pontinhos, e as duas
        //    juntas davam "0:09…." na tela.
        acoes.textContent = partes.join(" · ");
        if (a && a.detalhe) { acoes.title = a.detalhe; }
      })
      .catch(function () { /* o serviço pode estar ocupado; o relógio segue no próximo */ });
  }
  tique();
  var t = setInterval(tique, 1000);
  return function () { clearInterval(t); };
}

function concluir(cartao, acoes, permitido, resposta) {
  cartao.classList.add("decidida");
  acoes.className = "veredito";

  if (!permitido) {
    cartao.dataset.decisao = "nao";
    acoes.textContent = "✕ você recusou";
    return;
  }

  // ⛔ O "✓" só aparece quando o serviço confirma que FEZ. Antes, ele aparecia assim que
  //    o clique era registrado — e num pedido cuja chamada já tinha morrido do outro lado
  //    o editor lia "você permitiu" enquanto nada acontecia no Avid.
  if (resposta && resposta.ok && resposta.estado === "feita") {
    cartao.dataset.decisao = "sim";
    var r = resposta.resultado || {};
    if (r.erro) {
      acoes.textContent = "✕ não deu: " + r.erro;
      cartao.dataset.decisao = "falhou";
    } else if (r.scene && r.job) {
      // ⭐ o Baselight (conformar_no_baselight): a scene nova, o placar e, no "atualizar corte", o que veio do colorista.
      //    Sem este ramo caía no "montado" do Resolve e dizia "undefined cortes" (medido pelo chat, 2026-11-22).
      var cor = r.cor_do_colorista;
      var semCor = r.planos_sem_cor || [];
      var perdidos = (cor && cor.marcas_perdidas) || [];
      acoes.textContent = "✓ no Baselight: scene “" + r.scene + "” no job " + r.job +
        (r.job_criado ? " (criado agora)" : "") + " — " + r.certos + " de " + r.planos + " planos certos" +
        (r.corrigidos ? ", " + r.corrigidos + " corrigidos" : "") +
        ((r.a_conferir || []).length ? ", " + r.a_conferir.length + " a conferir" : "") +
        (cor ? ". A cor de “" + cor.colorista + "”: " + cor.conferidos + " de " + cor.de + " conferidos" +
               ((cor.divididos || []).length ? ", " + cor.divididos.length + " dividido(s) como o colorista" : "") +
               (semCor.length ? ", " + semCor.length + " sem cor (" +
                  semCor.map(function (x) { return x.arquivo; }).join(", ") + ")" : "") +
               ((r.planos_so_com_o_look || []).length ? ", " + r.planos_so_com_o_look.length +
                  " plano(s) novo(s) só com o look da cena" : "") +
               ((cor.marcas_movidas || []).length ? ", " + cor.marcas_movidas.length + " marker(s) dele levado(s)" : "") +
               (perdidos.length ? ", " + perdidos.length + " marker(s) dele ficaram para trás" : "") +
               ((cor.grupos || []).length ? ", " + cor.grupos.length + " grupo(s) dele levado(s)" : "") : "") + ".";
    } else if (r.sequencia) {
      acoes.textContent = "✓ montado: " + r.sequencia +
        " (" + r.cortes + " cortes, " + r.duracao_s + "s)" +
        (r.aberta_no_avid ? " — aberto no Avid" : "");
    } else if (r.timelines && r.cena) {
      acoes.textContent = "✓ falas separadas: " + r.timelines + " timelines " +
        (r.acrescentada_a_bin_existente ? "acrescentadas à bin " : "na bin ") + r.bin +
        (r.aberta_no_avid ? " — aberta no Avid" : "") +
        (r.deixadas_de_fora && r.deixadas_de_fora.length
          ? " · " + r.deixadas_de_fora.length + " de fora" : "");
    } else if (r.fluxo) {
      acoes.textContent = "✓ " + (r.manchete || "o fluxo começou");
      // ⭐⭐ O cartão SAI e o quadro preso no topo assume (autor, 2026-11-04): com o cartão ficando, a
      //    tela descia até ele e o andamento — passo em curso, ✓, Pausar e Cancelar — sumia de vista.
      //    O quadro mostra o mesmo plano, passo a passo, e vivo.
      if (window.acompanharFluxo) {
        window.acompanharFluxo(r.fluxo);
        cartao.remove();
      }
    } else if (r.sequencia_nova) {
      acoes.textContent = "✓ cópia gravada: " + r.sequencia_nova + " (" +
        r.duracao_depois + ")" + (r.carregada_na_record ? " — na Record" : "") +
        ". A original ficou intacta.";
    } else {
      acoes.textContent = "✓ feito";
    }
    if (conversaDoChat.contains(cartao)) { oferecerFluxo(); }
    return;
  }

  cartao.dataset.decisao = "falhou";
  acoes.textContent = "✕ " + ((resposta && (resposta.erro || resposta.motivo)) ||
                              "não consegui fazer");
}

/* ── a barra de status ───────────────────────────────────────────────────────
 *
 * ⭐ Quatro coisas, e cada uma responde a uma pergunta que o editor faz antes de começar
 * um corte: quem está respondendo, quanto da conversa já foi, quanto da assinatura já
 * foi, e quando ela vira.
 *
 * ⚠️ As cores são um SEMÁFORO, não decoração: verde até 75%, amarelo até 90%, vermelho
 * daí em diante. É a mesma leitura de qualquer medidor de recurso, e o editor não
 * precisa aprender nada para entendê-la. */

/* 21600 → "21,6k". O editor não precisa do número exato; precisa da ordem de grandeza. */
function emMil(n) {
  if (!n) { return "0"; }
  if (n < 1000) { return String(n); }
  return (n / 1000).toFixed(n < 10000 ? 1 : 0).replace(".", ",") + "k";
}

function faixaDe(fracao) {
  if (fracao >= 0.9) { return "vermelho"; }
  if (fracao >= 0.75) { return "amarelo"; }
  return "verde";
}

function pintarMedidor(id, fracao) {
  var el = document.getElementById(id);
  if (!el) { return; }
  // ⛔ `null` é APAGAR, e era ignorado: o limpar chamava com null e a barra da conversa
  //    velha ficava na tela (visto em campo, 2026-10-22). `undefined` (dado que não veio)
  //    continua não mexendo em nada.
  // ⭐ A barra fica SEMPRE à vista (autor, 2026-11-04): sem valor ela mostra "—", vazia.
  //    Sumir e voltar fazia a linha de baixo do status aparecer e desaparecer.
  if (fracao === null) {
    delete el.dataset.faixa;
    el.querySelector("b").style.width = "0";
    el.querySelector("em").textContent = "—";
    return;
  }
  if (fracao === undefined) { return; }
  el.dataset.faixa = faixaDe(fracao);
  el.querySelector("b").style.width = Math.min(100, Math.round(fracao * 100)) + "%";
  el.querySelector("em").textContent = Math.round(fracao * 100) + "%";
}

/* "reseta em 4h10m" — o que transforma "você está em 90%" em algo com que dá para
 * planejar o dia, em vez de um susto. */
function quandoVira(epoch) {
  if (!epoch) { return ""; }
  var faltam = Math.max(0, epoch * 1000 - Date.now());
  var minutos = Math.round(faltam / 60000);
  if (minutos < 1) { return "virando agora"; }
  if (minutos < 60) { return "reseta em " + minutos + "min"; }
  return "reseta em " + Math.floor(minutos / 60) + "h" +
    String(minutos % 60).padStart(2, "0");
}

/* ⭐ O motor do Mac não gasta a assinatura: a barra das 5 h e o aviso de limite são do
 * Claude, e com o Qwen na barra eles diziam "81%" de uma conta que ninguém estava usando
 * (2026-10-22). Ao trocar de motor a conversa também é outra (o serviço recomeça o fio). */
var motorLocal = false;
function pintarMotor() {
  motorLocal = String(escolhaDoModelo.value || "").indexOf("ollama:") === 0;
  if (motorLocal) {
    pintarMedidor("medidorUso", null);
    document.getElementById("reset").textContent = "";
    aviso.hidden = true;
  }
}

function mostrarLimite(dado) {
  if (motorLocal) { return; }
  var uso = dado.uso || {};
  var reseta = dado.reseta_em || {};
  pintarMedidor("medidorUso", uso.five_hour);
  document.getElementById("reset").textContent = quandoVira(reseta.five_hour);

  // ⛔ A barra é da janela de 5 h, e o aviso olha as DUAS: com a semanal em 82% e a de 5 h em 24%,
  //   ele dizia "82% do limite da janela atual" ao lado de uma barra em 24% (visto em 2026-10-29)
  //   — parecia aviso velho. Agora ele nomeia a janela e diz quando ela vira.
  var semanal = (uso.seven_day || 0) > (uso.five_hour || 0);
  var pior = semanal ? uso.seven_day : (uso.five_hour || 0);
  // ⚠️ O AVISO continua aparecendo só perto do fim, mesmo agora que existe o medidor:
  // um aviso constante vira mobília e some da atenção justamente quando passa a importar.
  // ⛔ E só apaga o aviso que É dele: o mesmo lugar mostra o de travamento e o de serviço velho.
  if (pior < 0.8) {
    if (aviso.dataset.de === "limite") { aviso.hidden = true; }
    return;
  }
  if (!aviso.hidden && aviso.dataset.de !== "limite") { return; }
  aviso.hidden = false;
  aviso.className = "aviso";
  aviso.dataset.de = "limite";
  var vira = quandoVira(semanal ? reseta.seven_day : reseta.five_hour);
  aviso.textContent =
    "Sua assinatura do Claude está em " + Math.round(pior * 100) + "% do limite " +
    (semanal ? "SEMANAL (a barra mostra o de 5 h)" : "das 5 h") + (vira ? ", e " + vira : "") +
    ". Perto do fim, as respostas param até a janela virar.";
}

/* Quanto da janela de contexto o fio já ocupa. Chega no fim de cada turno — é o que o
 * CLI conta, e é melhor que o nada que havia antes. */
/* ⭐⭐ O medidor da conversa mostra OCUPAÇÃO da janela, e só isso.
 *
 * ⛔⛔ Ele já mostrou **186%, 284% e 200%** em campo (2026-09-11) porque era alimentado
 * pela soma do turno, que conta cada requisição — e um turno com dez ferramentas reenvia
 * a conversa dez vezes. Uma janela não passa de 100% por definição, e um medidor que
 * mostra 284% não está adiantado: está quebrado, e leva junto a confiança no resto da
 * barra. O número certo é o da ÚLTIMA requisição, que chega nos eventos ao vivo.
 *
 * ⚠️ E o teto existe mesmo assim, como rede: se algum dia voltar a chegar coisa errada,
 * a barra satura em 100% em vez de mentir com precisão. */
/* "3,4s" / "1min 22s" — a mesma língua do relógio que roda durante o turno. */
function emTempo(segundos) {
  var s = Math.round(segundos);
  if (s < 60) { return (segundos < 10 ? segundos.toFixed(1) : s) + "s"; }
  return Math.floor(s / 60) + "min " + String(s % 60).padStart(2, "0") + "s";
}

function mostrarUso(dado) {
  var fracao = dado.fracao;
  if (fracao > 1) { fracao = 1; }
  pintarMedidor("medidorCtx", fracao);
}

/* ── o turno ────────────────────────────────────────────────────────────── */

function perguntar(pergunta) {
  if (ocupado) { return; }
  ocupado = true;
  var daConversa = qualConversa();
  enviar.disabled = true;
  pararConversa.hidden = false;
  estado("pensando");
  if (window.fluxosComecou) { window.fluxosComecou(); }

  bloco("você", "de-mim").texto.textContent = pergunta;

  var ferramentas = caixaDeFerramentas();
  conversa.appendChild(ferramentas.raiz);

  // ⭐⭐ O "pensando" nasce com o envio, não com a primeira palavra da resposta.
  //
  // Entre apertar enter e o primeiro token há segundos — mais, se o modelo for ler o
  // projeto antes de falar. A tela ficava idêntica à de antes do envio, e o editor não
  // tinha como saber se a pergunta chegou. Quem espera sem sinal aperta de novo.
  var resposta = bloco("ciclo assist", "de-ele");
  resposta.raiz.classList.add("pintando");
  resposta.texto.className = "texto pensando reticencias";
  resposta.texto.textContent = "pensando";
  var comecou = false;
  var bruto = "";
  // ⚠️ Cada mensagem do modelo chega emendada na anterior, e entre elas houve ferramenta: o
  //   texto de antes não termina em espaço, e a tela mostrava "Vou checar os dois.No roteiro"
  //   (visto na janela do app, 2026-10-21). Texto que vem DEPOIS de ferramenta é parágrafo novo.
  var depoisDeFerramenta = false;
  var fim = null;         // o evento `fim` (ou `cancelado`): duração do turno
  var gastoDoTurno = 0;   // tokens somados do `result`
  var cancelado = false;

  function garantirResposta() {
    if (!comecou) {
      comecou = true;
      resposta.texto.className = "texto";
      resposta.texto.textContent = "";
    }
    return resposta;
  }

  function terminar(qual) {
    resposta.raiz.classList.remove("pintando");
    ferramentas.parar();
    if (ferramentas.vazia()) { ferramentas.raiz.remove(); }
    // Uma resposta que acabou sem texto nenhum não deixa "pensando" para sempre.
    if (!comecou) { resposta.raiz.remove(); }

    // ⭐⭐ O rodapé, pedido em 2026-09-12. Vai em `resposta.raiz` e NÃO na caixa de
    //    ferramentas: aquela é removida inteira no fim do turno (e some de vez quando o
    //    turno não usou ferramenta nenhuma), então os dois números morriam no instante
    //    em que passavam a ser úteis.
    if (comecou && (fim || gastoDoTurno)) {
      var pe = document.createElement("div");
      pe.className = "rodape";
      var partes = [];
      if (cancelado) { partes.push("interrompido"); }
      if (fim && fim.duracao_s) { partes.push(emTempo(fim.duracao_s)); }
      if (gastoDoTurno) { partes.push(emMil(gastoDoTurno) + " tokens"); }
      pe.textContent = partes.join(" · ");
      resposta.raiz.appendChild(pe);
    }

    ocupado = false;
    enviar.disabled = false;
    pararConversa.hidden = true;
    estado(qual);
    if (daConversa === "chat") { oferecerFluxo(); }
    trocarPalco();      // o editor pode ter mudado de aba no meio do turno
    entrada.focus();
  }

  // ⭐ As referências vão com a pergunta e SOMEM depois: elas valem para o que ele
  //   acabou de perguntar, não para a conversa inteira. Deixá-las grudadas faria a
  //   terceira pergunta carregar o roteiro que ele arrastou na primeira.
  var comigo = referencias.slice();
  referencias = [];
  pintarAnexos();

  fetch("/conversar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pergunta: pergunta, referencias: comigo, nle: NLE, conversa: daConversa })
  })
    .then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return lerFluxo(r.body, function (tipo, dado) {
        ferramentas.sinal();
        if (tipo === "texto") {
          // Re-renderiza o bloco inteiro a cada pedaço, em vez de emendar no fim: um
          // `**` pode chegar partido em dois eventos, e emendar deixaria a marcação
          // meio aberta na tela. Resposta de chat é curta; o custo não aparece.
          if (depoisDeFerramenta && bruto && !/\s$/.test(bruto)) { bruto += "\n\n"; }
          depoisDeFerramenta = false;
          bruto += dado.texto;
          renderizar(garantirResposta().texto, bruto);
          rolarParaOFim();
        } else if (tipo === "ferramenta") {
          depoisDeFerramenta = true;
          ferramentas.acrescentar(dado);
        } else if (tipo === "progresso") {
          ferramentas.progresso(dado);
        } else if (tipo === "aprovacao") {
          mostrarAprovacao(dado);
        } else if (tipo === "perguntas") {
          mostrarPerguntas(dado);
        } else if (tipo === "limite") {
          mostrarLimite(dado);
        } else if (tipo === "uso") {
          mostrarUso(dado);
          ferramentas.tokens(dado.contexto || 0);
        } else if (tipo === "fim") {
          // ⚠️ Este evento existia e não tinha ramo nenhum: `duracao_s` e `turno`
          //    chegavam a cada resposta e caíam no vazio.
          fim = dado;
        } else if (tipo === "cancelado") {
          fim = dado;
          cancelado = true;
        } else if (tipo === "gasto") {
          // ⭐⭐ GASTO do turno ≠ ocupação da janela. O gasto soma TODAS as requisições
          //    (cada ferramenta reenvia a conversa), então ele passa da janela por
          //    desenho — medido: 267 mil de gasto para 23 mil de ocupação. Ele vai para
          //    a linha do turno, nunca para o medidor.
          gastoDoTurno = dado.tokens || 0;
          ferramentas.gasto(dado);
        } else if (tipo === "automatico") {
          mostrarAutomatico(dado);
        } else if (tipo === "erro") {
          var b = bloco("problema", "de-erro");
          b.texto.textContent = dado.mensagem;
        }
      });
    })
    .then(function () { terminar("pronto"); })
    .catch(function (e) {
      var b = bloco("problema", "de-erro");
      b.texto.textContent =
        "Não consegui falar com o serviço do Ciclo Assist. (" + e.message + ")";
      terminar("erro");
    });
}

/* ── SSE por fetch ──────────────────────────────────────────────────────────
 *
 * ⚠️ Não dá para usar `EventSource`: ele só faz GET, e a pergunta vai no corpo de um
 * POST. Então lemos o corpo em pedaços e cortamos os eventos à mão.
 *
 * ⚠️ Um pedaço da rede NÃO é um evento: ele pode trazer meio evento, ou três e meio.
 * Por isso existe o `sobra` — sem ele, uma resposta longa perde texto em silêncio,
 * que é o pior jeito de falhar. */

function lerFluxo(corpo, aoEvento) {
  var leitor = corpo.getReader();
  var decodificador = new TextDecoder("utf-8");
  var sobra = "";

  function passo() {
    return leitor.read().then(function (r) {
      if (r.done) { return; }
      sobra += decodificador.decode(r.value, { stream: true });
      var partes = sobra.split("\n\n");
      sobra = partes.pop();
      partes.forEach(function (bruto) {
        var tipo = null;
        var dados = null;
        bruto.split("\n").forEach(function (linha) {
          if (linha.indexOf("event: ") === 0) { tipo = linha.slice(7); }
          else if (linha.indexOf("data: ") === 0) { dados = linha.slice(6); }
        });
        if (!tipo || dados === null) { return; }
        try { aoEvento(tipo, JSON.parse(dados)); }
        catch (e) { /* evento malformado não derruba o turno */ }
      });
      return passo();
    });
  }

  return passo();
}

/* ── entrada ────────────────────────────────────────────────────────────── */

/* ⭐⭐ `/clear` — a saída para a janela de contexto cheia.
 *
 * Pedido do editor em 2026-09-11: um fio que já montou dois cortes carrega transcrições
 * inteiras, e a partir de certo ponto o modelo passa mais tempo relendo do que
 * trabalhando. A única saída era fechar o Media Composer.
 *
 * ⚠️ **Não vira pergunta.** Comando que chega ao modelo é comando que ele interpreta — e
 * "limpe o contexto" é justamente o que ele não pode fazer sozinho. Este é interceptado
 * aqui, antes de virar turno, e nem sai do painel como texto.
 *
 * ⚠️ E o `/ clear` com espaço também vale: o editor escreveu assim no pedido, e recusar
 * por um espaço seria burocracia. */
var COMANDOS_DE_LIMPAR = /^\/\s*(clear|limpar)$/i;

function limparAConversa() {
  if (fioAviso) { fioAviso.hidden = true; }
  var qualLimpar = qualConversa();
  fetch("/limpar", { method: "POST", headers: { "Content-Type": "application/json" },
                     body: JSON.stringify({ nle: NLE, conversa: qualLimpar }) })
    .then(function (r) { return r.json(); })
    .then(function () {
      // A tela inteira volta ao começo: sem histórico, sem anexos, sem medidores de uma
      // conversa que não existe mais.
      conversa.textContent = "";
      referencias = [];
      pintarAnexos();
      if (qualLimpar === "chat") { pintarMedidor("medidorCtx", null); }
      var b = bloco("ciclo assist", "de-sistema");
      b.texto.textContent =
        "Conversa limpa. O material analisado continua guardado — transcrição, decupagem " +
        "e vetores não se perdem, só o fio da conversa.";
      entrada.focus();
    })
    .catch(function () {
      var b = bloco("problema", "de-erro");
      b.texto.textContent = "Não consegui limpar a conversa.";
    });
}

/* O botão "Fluxos e Agentes": a janela é do app, e a página não fala com o Tauri (o caminho é o do pino). No navegador, outra aba. */
document.getElementById("botaoOficina").addEventListener("click", function () {
  fetch("/app/oficina", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (r) { if (!r.janela) { window.open("/oficina", "_blank"); } })
    .catch(function () { window.open("/oficina", "_blank"); });
});

/* O botão "Carta Aberta" (C2): o mesmo caminho do de Fluxos e Agentes. */
document.getElementById("botaoCarta").addEventListener("click", function () {
  fetch("/app/carta", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (r) { if (!r.janela) { window.open("/carta", "_blank"); } })
    .catch(function () { window.open("/carta", "_blank"); });
});

function enviarAgora() {
  var texto = entrada.value.trim();
  if (!texto || ocupado) { return; }
  entrada.value = "";
  ajustarAltura();
  if (COMANDOS_DE_LIMPAR.test(texto)) { limparAConversa(); return; }
  ultimaPergunta = texto;
  perguntar(texto);
}

compositor.addEventListener("submit", function (e) {
  e.preventDefault();
  enviarAgora();
});

entrada.addEventListener("keydown", function (e) {
  // Enter manda, Shift+Enter quebra linha — a convenção que o editor já tem no dedo.
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    enviarAgora();
  }
});

function ajustarAltura() {
  entrada.style.height = "auto";
  entrada.style.height = Math.min(entrada.scrollHeight, 132) + "px";
}
entrada.addEventListener("input", ajustarAltura);

/* ── o menu ☰: atalhos de prompt ─────────────────────────────────────────────
 *
 * ⭐ Plano: docs/plano/2026-09-14-menu-do-compositor.md. O trabalho previsível ("separe as
 * falas da cena…") era redigitado toda vez — e numa apresentação, a frase redigitada é a
 * que sai diferente. O atalho é o mesmo pedido, palavra por palavra.
 *
 * ⛔ Clicar num atalho PREENCHE a caixa e NÃO envia (decisão do editor): nada é gasto até
 * ele apertar enviar, e assim ele arrasta a bin antes. Com texto já na caixa, o atalho
 * vem DEPOIS de uma linha em branco — nunca apagar o que o editor digitou.
 *
 * ⛔ O que se salva é o que o editor DIGITOU: o anexo (MobID, caminho) viaja separado, em
 * `referencias`, e é montado no serviço — nunca entra num atalho. */

//: A última pergunta enviada, para "Salvar como atalho". Só na memória: depois de um
//: Reload a conversa some da tela, e uma "última pergunta" sobrevivente apontaria para nada.
var ultimaPergunta = "";
var abrirMenu = document.getElementById("abrirMenu");
var menuPop = document.getElementById("menuPop");
var menuAtalhos = document.getElementById("menuAtalhos");
var menuSalvar = document.getElementById("menuSalvar");
var menuLimpar = document.getElementById("menuLimpar");
var menuForma = document.getElementById("menuForma");
var formaApelido = document.getElementById("formaApelido");
var formaTexto = document.getElementById("formaTexto");
var formaErro = document.getElementById("formaErro");
var desarmarLimpar = null;

function pintarAtalhos(lista) {
  menuAtalhos.textContent = "";
  if (!lista || !lista.length) {
    var vazio = document.createElement("p");
    vazio.className = "menu-vazio";
    vazio.textContent = "Nenhum atalho ainda. Escreva um pedido e use " +
      "“Salvar como atalho” para guardá-lo aqui.";
    menuAtalhos.appendChild(vazio);
    return;
  }
  lista.forEach(function (a) {
    // ⛔ O × não pode ser <button> dentro de <button> (o Chromium desmonta o aninhamento):
    //    dois botões irmãos numa linha, como o chip de anexo.
    var linha = document.createElement("div");
    linha.className = "menu-linha";
    linha.setAttribute("role", "none");
    var item = document.createElement("button");
    item.type = "button";
    item.className = "menu-item";
    item.setAttribute("role", "menuitem");
    item.textContent = a.apelido;
    item.title = a.texto;
    item.addEventListener("click", function () { usarAtalho(a); });
    var tirar = document.createElement("button");
    tirar.type = "button";
    tirar.className = "menu-tirar";
    tirar.setAttribute("aria-label", "Tirar o atalho " + a.apelido);
    tirar.title = "Tirar este atalho";
    tirar.textContent = "×";
    tirar.addEventListener("click", function (e) {
      e.stopPropagation();
      chamarAtalhos("/atalhos/tirar", { id: a.id });
    });
    linha.appendChild(item);
    linha.appendChild(tirar);
    menuAtalhos.appendChild(linha);
  });
}

function chamarAtalhos(rota, corpo) {
  var opcoes = corpo === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo) };
  return fetch(rota, opcoes)
    .then(function (r) { return r.json(); })
    .then(function (d) {
      // ⚠️ A lista volta RELIDA do disco em toda resposta, inclusive na recusa: um atalho
      //    que não aparece é o sintoma honesto de uma gravação que falhou.
      if (d && d.atalhos) { pintarAtalhos(d.atalhos); }
      return d || {};
    });
}

function usarAtalho(a) {
  fecharOMenu();
  var atual = entrada.value.replace(/\s+$/, "");
  entrada.value = atual ? atual + "\n\n" + a.texto : a.texto;
  // A ordem importa: altura antes do foco, senão o textarea fica com uma linha.
  ajustarAltura();
  entrada.focus();
  entrada.setSelectionRange(entrada.value.length, entrada.value.length);
}

function posicionarOMenu() {
  var r = abrirMenu.getBoundingClientRect();
  var largura = Math.min(400, window.innerWidth - 16);
  menuPop.style.width = largura + "px";
  menuPop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - largura - 8)) + "px";
  menuPop.style.bottom = (window.innerHeight - r.top + 6) + "px";
}

function textoParaSalvar() {
  return entrada.value.trim() || ultimaPergunta;
}

/* ⭐ Os fluxos salvos no menu ☰, na aba Fluxos (autor, 04/11): as boas-vindas somem no primeiro comando, e
 * daqui o editor carrega outro fluxo quando quiser. Um clique abre o formulário (o mesmo do Carregar). */
var menuFluxos = document.getElementById("menuFluxos");
var menuFluxosSep = document.getElementById("menuFluxosSep");
function pintarFluxosDoMenu() {
  if (!menuFluxos) { return; }
  var naAba = abaVista === "conversa" && !!window.carregarReceita;
  menuFluxos.hidden = menuFluxosSep.hidden = !naAba;
  if (!naAba) { return; }
  menuFluxos.textContent = "";
  var cab = document.createElement("p");
  cab.className = "menu-vazio";
  cab.textContent = "Fluxos salvos";
  menuFluxos.appendChild(cab);
  fetch("/receitas", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var lista = ((d && d.receitas) || []).slice().sort(function (a, b) {
        return (a.origem === "editor" ? 0 : 1) - (b.origem === "editor" ? 0 : 1);
      });
      if (!lista.length) { cab.textContent = "Nenhum fluxo salvo ainda."; return; }
      lista.forEach(function (r) {
        var item = document.createElement("button");
        item.type = "button";
        item.className = "menu-item";
        item.setAttribute("role", "menuitem");
        item.textContent = String(r.titulo || r.nome).replace(/\{[^}]*\}\s*/g, "").replace(/\s+/g, " ").trim() || r.nome;
        if (r.distintivo) {
          var qual = document.createElement("small");
          qual.className = "menu-distintivo";
          qual.textContent = r.distintivo;
          item.appendChild(qual);
        }
        item.title = r.descricao || "";
        item.disabled = !!(r.problemas && r.problemas.length);
        item.addEventListener("click", function () { fecharOMenu(); window.carregarReceita(r); });
        menuFluxos.appendChild(item);
      });
    })
    .catch(function () { cab.textContent = "Não consegui ler os fluxos salvos."; });
}

function abrirOMenu() {
  pintarFluxosDoMenu();
  menuPop.removeAttribute("data-modo");
  menuForma.hidden = true;
  menuSalvar.disabled = !textoParaSalvar();
  menuSalvar.title = menuSalvar.disabled
    ? "Escreva um pedido na caixa (ou envie um) para poder guardá-lo." : "";
  posicionarOMenu();
  menuPop.hidden = false;
  abrirMenu.setAttribute("aria-expanded", "true");
  chamarAtalhos("/atalhos").catch(function () { pintarAtalhos([]); });
}

function fecharOMenu() {
  if (menuPop.hidden) { return; }
  menuPop.hidden = true;
  abrirMenu.setAttribute("aria-expanded", "false");
  desarmarOLimpar();
}

function desarmarOLimpar() {
  if (desarmarLimpar) { clearTimeout(desarmarLimpar); desarmarLimpar = null; }
  menuLimpar.classList.remove("armado");
  menuLimpar.textContent = "Limpar conversa";
}

abrirMenu.addEventListener("click", function () {
  if (menuPop.hidden) { abrirOMenu(); } else { fecharOMenu(); }
});

// ⛔ Nada de confirm(): diálogo nativo trava a webview dentro do NLE. O primeiro clique
//    arma ("Limpar mesmo?") e desarma sozinho; o menu não fecha no primeiro.
menuLimpar.addEventListener("click", function () {
  if (!menuLimpar.classList.contains("armado")) {
    menuLimpar.classList.add("armado");
    menuLimpar.textContent = "Limpar mesmo?";
    desarmarLimpar = setTimeout(desarmarOLimpar, 6000);
    return;
  }
  fecharOMenu();
  limparAConversa();
});

menuSalvar.addEventListener("click", function () {
  var texto = textoParaSalvar();
  if (!texto) { return; }
  formaTexto.value = texto;
  formaApelido.value = "";
  formaErro.hidden = true;
  menuPop.setAttribute("data-modo", "forma");
  menuForma.hidden = false;
  posicionarOMenu();
  formaApelido.focus();
});

function salvarAForma() {
  chamarAtalhos("/atalhos/salvar",
                { apelido: formaApelido.value, texto: formaTexto.value, de: "pergunta" })
    .then(function (d) {
      if (d.ok === false) {
        formaErro.textContent = d.erro || "Não consegui salvar o atalho.";
        formaErro.hidden = false;
        return;
      }
      fecharOMenu();
      entrada.focus();
    })
    .catch(function () {
      formaErro.textContent = "Não consegui falar com o serviço para salvar o atalho.";
      formaErro.hidden = false;
    });
}

document.getElementById("formaSalvar").addEventListener("click", salvarAForma);
document.getElementById("formaCancelar").addEventListener("click", function () {
  menuPop.removeAttribute("data-modo");
  menuForma.hidden = true;
  posicionarOMenu();
});
formaApelido.addEventListener("keydown", function (e) {
  if (e.key === "Enter") { e.preventDefault(); salvarAForma(); }
});

document.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && !menuPop.hidden) {
    fecharOMenu();
    abrirMenu.focus();
  }
});
// Clique fora fecha. Na BOLHA, não na captura: a captura é do arrasto.
document.addEventListener("click", function (e) {
  if (menuPop.hidden) { return; }
  if (menuPop.contains(e.target) || abrirMenu.contains(e.target)) { return; }
  fecharOMenu();
});
window.addEventListener("resize", function () {
  if (!menuPop.hidden) { posicionarOMenu(); }
});
entrada.addEventListener("focus", fecharOMenu);

/* ── as abas ─────────────────────────────────────────────────────────────────
 *
 * ⭐ Uma aba só, e a estrutura para as próximas. O Ciclo Assist é o primeiro painel da
 * casa; os outros produtos entram como abas ao lado, sem nada aqui mudar. Acrescentar
 * uma é somar um `<button data-tela>` e um `<section data-tela>` no HTML.
 *
 * ⚠️ A engrenagem é uma tela como as outras, e não um modal: modal em painel de 400 px
 * cobre a conversa inteira e ainda precisa de um jeito de fechar. Aba já tem. */

/* ⚠️⚠️ Uma tela é feita de VÁRIOS elementos, não de um.
 *
 * A conversa são dois: a lista de mensagens e a barra de status embaixo dela. Enquanto
 * isto guardava um elemento por nome, o último `data-tela="conversa"` do HTML
 * sobrescrevia o primeiro — e abrir as configurações deixava a conversa na tela, com a
 * tela de configurações por cima. O teste de interface pegou no mesmo dia em que a barra
 * de status nasceu. */
var telas = {};
Array.prototype.forEach.call(document.querySelectorAll("[data-tela]"), function (el) {
  if (el.tagName === "BUTTON") { return; }
  (telas[el.dataset.tela] = telas[el.dataset.tela] || []).push(el);
});

//: Que tela está à vista. ⚠️ Quem sonda o serviço PRECISA disto: trabalho de relógio para
//: uma tela que ninguém está olhando é custo sem leitor, e num painel de webview dentro do
//: Media Composer ele corre o dia inteiro.
var telaAVista = "";

function mostrarTela(qual) {
  fecharOMenu();
  telaAVista = qual;
  Object.keys(telas).forEach(function (id) {
    telas[id].forEach(function (el) { el.hidden = id !== qual; });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".aba, .engrenagem"),
    function (b) {
      b.classList.toggle("ativa", b.dataset.tela === qual);
    });
  // ⚠️ A caixa de texto acompanha a tela: escrever uma pergunta enquanto se olha as
  // configurações manda a pergunta para uma conversa que não está na frente. ⭐ A aba Fluxos tem
  // conversa própria (F3) e usa a MESMA caixa: o palco troca junto (`trocarPalco`).
  abaVista = qual;
  trocarPalco();
  compositor.hidden = qual !== "conversa" && qual !== "fluxos";
  if (qual === "conversa" || qual === "fluxos") { entrada.focus(); }
  if (qual === "config") { carregarConfiguracoes(); }
  if (qual === "busca") { montarFiltrosDaBusca(); contarOsRecortes(); busFrase.focus(); }
  if (qual === "vetores") { carregarVetores(); olharOProjeto("aba"); }
  if (qual === "fluxos" && window.telaDeFluxos) { window.telaDeFluxos(destaqueDosFluxos); destaqueDosFluxos = ""; }
  // ⚠️ A sondagem só corre com a aba à vista: bater no Media Composer para atualizar
  //   uma tabela que ninguém está olhando é custo sem leitor.
  acompanharOProjeto(qual === "vetores");
  // ⚠️ A mesma regra para a vigia: o interruptor fica ligado por dias, e o relógio dele
  //   batia no serviço de 5 em 5 segundos mesmo com o editor na conversa.
  acompanharAVigia();
}

Array.prototype.forEach.call(document.querySelectorAll(".aba, .engrenagem"),
  function (b) {
    b.addEventListener("click", function () { mostrarTela(b.dataset.tela); });
  });

/* ── a aba Busca ────────────────────────────────────────────────────────────
 *
 * ⭐⭐ **As duas buscas já existiam; o que faltava era o editor alcançá-las.** No chat,
 * achar um plano custava escrever uma pergunta e pagar um turno do modelo. O motor é o
 * mesmo (`midia/decupagem.py` e `midia/vetores.py`) e aqui a resposta é leitura de disco:
 * `POST /busca/frase` (o que o Claude escreveu olhando os quadros) e
 * `POST /busca/parecidos` (imagem → imagem, pelo vetor).
 *
 * ⚠️⚠️ **O tamanho do que a busca alcança fica SEMPRE na tela.** No chat quem diz "3 de 23
 * decupadas" é o modelo; aqui não há modelo nenhum, e sem a frase "não achei" se lê como
 * "meu material não tem isso" — e o editor acredita.
 *
 * ⚠️ E o recorte do projeto aberto vai junto, pelo mesmo motivo: filtro calado é pior que
 * filtro nenhum. */

var busFrase = document.getElementById("busFrase");
var busCampos = document.getElementById("busCampos");
var busResumo = document.getElementById("busResumo");
var busEscopo = document.getElementById("busEscopo");
var busResultados = document.getElementById("busResultados");
var busVazio = document.getElementById("busVazio");
var busRecado = document.getElementById("busRecado");
var busLimpar = document.getElementById("busLimpar");
var busExpansao = document.getElementById("busExpansao");
var busPreferir = document.getElementById("busPreferir");
var busIndice = document.getElementById("busIndice");

/* O vocabulário vem do serviço uma vez por visita — `midia/decupagem.py` é quem o define,
 * e uma cópia aqui divergiria calada. */
var vocabularioPedido = false;

function montarFiltrosDaBusca() {
  if (vocabularioPedido) { return; }
  vocabularioPedido = true;
  fetch("/busca/vocabulario", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      (d.campos || []).forEach(function (c) {
        var rotulo = document.createElement("label");
        rotulo.className = "bus-campo";
        var nome = document.createElement("span");
        nome.textContent = c.campo;
        var sel = document.createElement("select");
        sel.dataset.campo = c.campo;
        sel.className = "modelo";
        // ⚠️ "qualquer" é o padrão, e é uma OPÇÃO de verdade: um select que já nasce com
        //   um valor escolhido filtra sem ninguém ter pedido.
        var vazio = document.createElement("option");
        vazio.value = "";
        vazio.textContent = "qualquer";
        sel.appendChild(vazio);
        (c.valores || []).forEach(function (v) {
          var o = document.createElement("option");
          o.value = v;
          o.textContent = v;
          sel.appendChild(o);
        });
        sel.addEventListener("change", function () { procurarPorFrase(); });
        rotulo.appendChild(nome);
        rotulo.appendChild(sel);
        busCampos.appendChild(rotulo);
      });
    })
    .catch(function () {
      vocabularioPedido = false;   // uma falha de rede não pode deixar a aba sem filtros
      busCampos.textContent = "não consegui ler os filtros; use a frase.";
    });
}

/* ⭐⭐ Quantos recortes o projeto tem — e, de quebra, o índice AQUECIDO.
 *
 * Montá-lo custa 3,6 s na primeira vez de uma sessão. Pago dentro da primeira busca, esse
 * tempo se lê como "a busca é lenta"; pago quando a aba abre, ele cabe no gesto de trocar
 * de aba. ⚠️ E o número diz ao editor se vale deixar a preferência ligada: num projeto sem
 * subclipe nenhum ela não muda nada. */
function contarOsRecortes() {
  fetch("/busca/recortes?nle=" + NLE, { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var rotulo = busPreferir.querySelector("span") || document.createElement("span");
      rotulo.className = "bus-quantos-recortes";
      // ⛔ "ainda lendo" só quando há PROJETO ABERTO para ler: com o editor fechado
      //    ninguém está lendo nada, e a reticência prometia um número que nunca vinha.
      rotulo.textContent = d.recortes
        ? "(" + d.recortes + " no projeto)"
        : (d.possivel === false ? "(sem projeto aberto)"
           : (d.pronto ? "(o projeto não tem nenhum)" : "(ainda lendo as bins…)"));
      busPreferir.appendChild(rotulo);
    })
    .catch(function () { /* contar é bônus; a preferência funciona sem o número */ });
}

function filtrosEscolhidos() {
  var escolhidos = {};
  Array.prototype.forEach.call(busCampos.querySelectorAll("select"), function (s) {
    if (s.value) { escolhidos[s.dataset.campo] = s.value; }
  });
  return escolhidos;
}

/* ⭐ Quem fala (plano 2026-11-06): clicar no nome da lapela numa fala ("MIC2") refaz a busca só com as falas dela;
 * o resumo diz o filtro e tem o ✕ — filtro calado é pior que filtro nenhum. */
var busFalante = "";

function filtrarPorFalante(nome) {
  busFalante = nome || "";
  procurarPorFrase();
}

function procurarPorFrase() {
  var termos = busFrase.value.trim();
  var campos = filtrosEscolhidos();
  var temFiltro = Object.keys(campos).length > 0 || Boolean(busFalante);
  busLimpar.hidden = !termos && !temFiltro;
  busRecado.hidden = true;
  if (!termos && !temFiltro) {
    busResultados.textContent = "";
    busVazio.hidden = true;
    busEscopo.hidden = true;
    busExpansao.hidden = true;
    busIndice.hidden = true;
    busResumo.textContent = "diga o que procurar";
    return;
  }

  // ⚠️ Silêncio parece travamento: a primeira busca do dia lê o cache do disco e leva
  //   segundos. A reticência animada é a mesma dos outros três lugares do painel.
  busResumo.className = "bus-resumo reticencias";
  busResumo.textContent = "procurando";

  var corpo = { termos: termos, quantos: 40,
                preferir_subclipes: busPreferir.checked, nle: NLE };
  if (busFalante) { corpo.falante = busFalante; }
  Object.keys(campos).forEach(function (c) { corpo[c] = campos[c]; });

  fetch("/busca/frase", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpo)
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      busResumo.className = "bus-resumo";
      if (!d.ok) {
        // ⭐ A recusa do vocabulário JÁ diz os valores aceitos — mostrá-la inteira é o
        //   conserto, e resumi-la seria tirar do editor a única coisa que resolve.
        busResumo.textContent = "";
        busRecado.textContent = d.erro || "não consegui procurar";
        busRecado.hidden = false;
        busResultados.textContent = "";
        busVazio.hidden = true;
        return;
      }
      pintarAchados(d);
    })
    .catch(function (e) {
      busResumo.className = "bus-resumo";
      busResumo.textContent = "";
      busRecado.textContent = "Não consegui falar com o serviço. (" + e.message + ")";
      busRecado.hidden = false;
    });
}

function pintarAchados(d) {
  busResultados.textContent = "";
  var al = d.alcance || {};

  // ⚠️⚠️ ESTA frase é o produto, e a primeira versão dela FALHOU. O editor leu
  //   "168 de 323 mídias decupadas" e perguntou: *"168 seriam as mídias do projeto e 323 o
  //   total do banco?"* — não, os dois eram do recorte, e faltava o terceiro número. Agora
  //   são os quatro, cada um com o seu nome, na ordem em que a pergunta se responde:
  //   o que a busca leu → o que o cache tem → o que o projeto tem.
  var camadas = [];
  if (al.decupadas !== undefined) { camadas.push(al.decupadas + " com decupagem"); }
  if (al.transcritas !== undefined) { camadas.push(al.transcritas + " com fala"); }
  var cobertura = camadas.join(" e ") + ", de " + al.no_cache + " no cache" +
    (al.no_projeto ? " (o projeto tem " + al.no_projeto + " " + PALAVRAS.unidade + ")" : "");

  // ⛔⛔ O que ficou ABAIXO do corte é dito. Preferir subclipes reordena, e com 1.093
  //   masters no projeto a 3ª faixa sai da lista: sem esta contagem, a preferência que o
  //   editor pediu viraria exclusão calada — o oposto do que ele pediu.
  var cortados = d.fora_do_corte
    ? " · " + d.fora_do_corte + " abaixo do corte"
    : "";
  busResumo.textContent = d.quantos === 0
    ? "nada encontrado — procurei em " + cobertura
    : d.quantos + (d.quantos === 1 ? " resultado" : " resultados") + cortados +
      " · procurei em " + cobertura;
  if (busFalante) {
    var tirar = document.createElement("button");
    tirar.type = "button";
    tirar.className = "bus-filtro-falante";
    tirar.textContent = "só falas de " + busFalante + " ✕";
    tirar.title = "tirar o filtro de quem fala";
    tirar.addEventListener("click", function () { filtrarPorFalante(""); });
    busResumo.insertBefore(document.createTextNode(" "), busResumo.firstChild);
    busResumo.insertBefore(tirar, busResumo.firstChild);
  }

  // ⛔⛔ O que o dicionário de intenção ACRESCENTOU, dito em voz alta. Busca que se alarga
  //   calada é a irmã do filtro calado: sem isto o editor lê "13 achados" sem saber que
  //   nenhum deles tem a palavra que ele escreveu (foi o caso de "drone").
  pintarExpansoes(d.expansoes || {});

  // ⚠️ Pedir "preferir subclipes" e ainda não ter índice é um resultado DIFERENTE de não
  //   pedir: a lista sai só com masters, e sem esta linha parece que o projeto não tem
  //   subclipe nenhum. O índice monta no fundo; a próxima busca já os traz.
  // ⛔ ...e o mesmo na linha do índice: prometer "procure de novo em alguns segundos"
  //    sem projeto aberto é mandar o editor repetir um gesto que não pode dar certo.
  var faltaIndice = d.preferir_subclipes && d.recortes_prontos === false &&
                    d.recortes_possiveis !== false;
  busIndice.textContent = faltaIndice
    ? "ainda estou lendo os subclipes das bins — esta lista saiu só com os masters. " +
      "Procure de novo em alguns segundos."
    : "";
  busIndice.hidden = !faltaIndice;

  var escopo = d.escopo || {};
  busEscopo.textContent = d.aviso || (escopo.projeto
    ? "no projeto " + escopo.projeto + " (" + escopo.masters_no_projeto + " " +
      PALAVRAS.unidade + ")"
    : "");
  busEscopo.hidden = !busEscopo.textContent;

  busVazio.hidden = d.quantos !== 0;
  if (d.quantos === 0) {
    busVazio.textContent = (al.decupadas === 0 && al.transcritas === 0)
      ? ("Nada foi analisado ainda neste recorte. A decupagem e a transcrição são o que dá " +
         "o que procurar — a aba Vetores tem os botões, com o preço antes do clique.")
      : ("Nada casou. A busca só alcança o que já foi analisado: " + cobertura + ".");
    return;
  }

  d.achados.forEach(function (a) { busResultados.appendChild(cartaoDoAchado(a)); });
}

function pintarExpansoes(expansoes) {
  busExpansao.textContent = "";
  var termos = Object.keys(expansoes);
  if (!termos.length) { busExpansao.hidden = true; return; }
  busExpansao.appendChild(document.createTextNode("procurei também por "));
  termos.forEach(function (t, i) {
    if (i) { busExpansao.appendChild(document.createTextNode("; ")); }
    var b = document.createElement("b");
    b.textContent = expansoes[t].join(", ");
    b.title = 'o que "' + t + '" costuma querer dizer';
    busExpansao.appendChild(b);
  });
  busExpansao.hidden = false;
}

/* Uma linha por MÍDIA: a miniatura, o que a imagem diz, e as falas que casaram DENTRO.
 *
 * ⭐⭐ Uma linha por FALA daria 241 linhas para "Personagem F" (medido), com a mesma mídia
 * repetida dezenas de vezes. O editor escolheu o cartão da mídia (2026-09-20). */
function cartaoDoAchado(a) {
  var cartao = document.createElement("article");
  cartao.className = "bus-achado";
  cartao.tabIndex = 0;
  cartao.title = "duplo clique carrega no monitor Source do " + PALAVRAS.nle;
  // ⭐ Duplo clique carrega no Source — o pedido do editor ao ver a primeira versão:
  //   *"ao listar o clipe, não é possível fazer nada"*. Teclado também, senão a única
  //   ação da aba fica fora do alcance de quem navega por Tab.
  cartao.addEventListener("dblclick", function () { abrirNoPonto(a, cartao); });
  cartao.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); abrirNoPonto(a, cartao); }
  });

  var img = document.createElement("img");
  img.className = "bus-quadro";
  img.loading = "lazy";
  img.alt = "";
  // ⛔ `<img>` é arrastável por padrão, e arrastar a miniatura acendia o "solte aqui" do
  //    painel. Ela não é o que se arrasta — o gesto do resultado é o duplo clique.
  img.draggable = false;
  img.title = "quadro do cache mais próximo do trecho";
  img.src = "/busca/quadro?chave=" + encodeURIComponent(a.chave) +
            (a.inicio_frames === null || a.inicio_frames === undefined
              ? ""
              : "&frame=" + encodeURIComponent(a.inicio_frames) + "&perto=1");
  img.addEventListener("error", function () { img.remove(); });
  cartao.appendChild(img);

  var corpo = document.createElement("div");
  corpo.className = "bus-corpo";

  // ⭐⭐ Num recorte o NOME é o do subclipe, que é o que o editor procura na bin — e o
  //   master vira a segunda linha, porque ele ainda importa (é dele que sai o cache).
  var titulo = document.createElement("p");
  titulo.className = "bus-titulo";
  titulo.textContent = a.item || a.take || a.midia;
  corpo.appendChild(titulo);

  if (a.item) {
    var onde = document.createElement("p");
    onde.className = "bus-onde";
    // ⚠️ "em N bins" porque o editor COPIA o subclipe entre as bins de trabalho: medido,
    //    290 pares viram 130 recortes distintos, e um deles está em 6 bins. Mostrar as
    //    cinco linhas iguais gastava a lista inteira em cópias.
    var bins = a.bins || [a.bin];
    onde.textContent = bins.length > 1
      ? bins[0] + " · em " + bins.length + " bins"
      : bins[0];
    onde.title = bins.join("\n") + "\nmaster: " + a.midia;
    corpo.appendChild(onde);
  }

  // ⭐ De ONDE veio o resultado. Sem isto o editor não sabe se aquilo apareceu porque
  //   alguém OLHOU o plano ou porque alguém DISSE a palavra — e as duas se conferem de
  //   jeitos diferentes (uma no monitor, outra ouvindo).
  var etiquetas = document.createElement("p");
  etiquetas.className = "bus-etiquetas";
  if (a.especie && a.especie !== "master") {
    var esp = document.createElement("span");
    esp.className = "bus-etiqueta bus-especie";
    esp.textContent = a.especie;
    etiquetas.appendChild(esp);
  }
  // ⭐ De que TRECHO veio o achado (decupagem micro): o duplo clique vai até lá.
  if (a.escopo === "trecho" && typeof a.inicio_s === "number") {
    var tr = document.createElement("span");
    tr.className = "bus-etiqueta bus-trecho-etq";
    var mmss = function (s) {
      s = Math.round(s);
      return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
    };
    tr.textContent = "trecho " + mmss(a.inicio_s) +
      (typeof a.fim_s === "number" ? "–" + mmss(a.fim_s) : "");
    tr.title = "achado na decupagem por trechos — duplo clique leva ao começo do trecho";
    etiquetas.appendChild(tr);
  }
  // ⭐ A claquete LIDA (pedido do editor, 2026-09-22): rolo · cena · plano · take, e as
  //   marcas (série, pickup). Ilegível é dito — achou a claquete e não leu é diferente de
  //   não ter claquete.
  if (a.claquete) {
    var cl = document.createElement("span");
    cl.className = "bus-etiqueta bus-claquete";
    var q = a.claquete;
    if (q.legivel === false) {
      cl.textContent = "claquete ilegível";
      cl.classList.add("ilegivel");
    } else {
      var partes = [];
      if (q.rolo && q.rolo.length) { partes.push(q.rolo.join("/")); }
      var cpt = (q.cena ? "C" + q.cena : "") + (q.plano ? " P" + q.plano : "") +
                (q.take ? " T" + q.take : "");
      if (cpt.trim()) { partes.push(cpt.trim()); }
      if (q.serie) { partes.push("série"); }
      (q.marcas || []).forEach(function (m) { partes.push(m.toLowerCase()); });
      cl.textContent = "claquete " + partes.join(" · ");
      // ⛔⛔ E a leitura que a conferência REPROVOU diz isso na etiqueta. Medido no cache
      //   em 2026-09-23: 44 notas com a claquete em `hipotese` (30 delas o exemplo da
      //   instrução copiado) apareciam aqui com a mesma cara de uma leitura conferida —
      //   número plausível, sem uma palavra de dúvida. O motivo vai no title.
      if (q.confianca === "hipotese") {
        cl.textContent += " · duvidosa";
        cl.classList.add("duvidosa");
      }
    }
    cl.title = (q.aviso ? "⚠️ " + q.aviso + "\n" : "") +
      (q.texto ? "lido: " + q.texto + "\n" : "") +
      "leitura de IA sobre o começo do take — confira no quadro";
    etiquetas.appendChild(cl);
  }
  // ⚠️ A 3ª faixa é dita, e não só posicionada: rolando a lista, um master no meio dela
  //   parece um resultado novo. "já acima" diz que o material dele já apareceu recortado.
  if (a.faixa === 3) {
    var rep = document.createElement("span");
    rep.className = "bus-etiqueta bus-repetido";
    rep.textContent = "já acima";
    rep.title = "este master é a origem de um subclipe que já apareceu na lista";
    etiquetas.appendChild(rep);
  }
  // ⚠️ E o que HERDOU o match sem poder conferir o tempo: a decupagem de mídia descreve o
  //   master inteiro, então o recorte pode não conter o que se procura.
  // ⭐⭐ Em que timeline este item é usado — pedido do editor (2026-09-21), para separar
  //   o que está montado do que está largado numa bin de rascunho.
  (a.timelines || []).slice(0, 2).forEach(function (nome) {
    var t = document.createElement("span");
    t.className = "bus-etiqueta bus-timeline";
    t.textContent = nome;
    t.title = "usado na timeline " + nome +
              ((a.timelines.length > 2) ? " (e mais " + (a.timelines.length - 2) + ")" : "");
    etiquetas.appendChild(t);
  });
  if (a.herdado) {
    var her = document.createElement("span");
    her.className = "bus-etiqueta bus-herdado";
    her.textContent = "do master";
    her.title = "a decupagem é do material inteiro e não tem posição — este recorte pode " +
                "não conter o que você procura";
    etiquetas.appendChild(her);
  }
  (a.achado_por || []).forEach(function (origem) {
    var e = document.createElement("span");
    e.className = "bus-etiqueta bus-origem";
    e.dataset.origem = origem;
    e.textContent = origem;
    etiquetas.appendChild(e);
  });
  ["enquadramento", "angulo", "camera", "local", "momento"].forEach(function (c) {
    if (!a[c]) { return; }
    var e = document.createElement("span");
    e.className = "bus-etiqueta";
    e.textContent = a[c];
    etiquetas.appendChild(e);
  });
  if (etiquetas.childNodes.length) { corpo.appendChild(etiquetas); }

  if (a.trecho_da_descricao) {
    var trecho = document.createElement("p");
    trecho.className = "bus-trecho";
    // ⭐ A setinha (pedido do editor, 2026-09-22): o pedaço em volta do termo é o bom
    //   padrão — mostra POR QUE casou —, e a descrição inteira fica a um clique.
    //   ⚠️ Só quando há mais para ler: uma seta que não abre nada é um botão quebrado.
    var inteira = a.descricao || "";
    var texto = document.createElement("span");
    texto.textContent = a.trecho_da_descricao;
    if (inteira && inteira !== a.trecho_da_descricao) {
      var seta = document.createElement("button");
      seta.type = "button";
      seta.className = "bus-seta";
      seta.textContent = "▸";
      seta.title = "ler a descrição inteira";
      seta.setAttribute("aria-expanded", "false");
      seta.addEventListener("click", function (ev) {
        ev.stopPropagation();   // ⚠️ o cartão tem duplo clique (Source); a seta não é ele
        var aberta = seta.getAttribute("aria-expanded") !== "true";
        seta.setAttribute("aria-expanded", aberta ? "true" : "false");
        seta.textContent = aberta ? "▾" : "▸";
        seta.title = aberta ? "voltar ao trecho" : "ler a descrição inteira";
        texto.textContent = aberta ? inteira : a.trecho_da_descricao;
        trecho.classList.toggle("aberto", aberta);
      });
      seta.addEventListener("dblclick", function (ev) { ev.stopPropagation(); });
      trecho.appendChild(seta);
    }
    trecho.appendChild(texto);
    corpo.appendChild(trecho);
  }

  if (a.quantas_falas) { corpo.appendChild(blocoDeFalas(a, cartao)); }

  var acoes = document.createElement("p");
  acoes.className = "bus-acoes";
  var abrir = document.createElement("button");
  abrir.type = "button";
  abrir.className = "botao compacto";
  abrir.textContent = "no Source";
  abrir.title = "Carregar esta mídia no monitor Source do " + PALAVRAS.nle;
  abrir.addEventListener("click", function () { abrirNoPonto(a, cartao); });
  acoes.appendChild(abrir);

  var parecidos = document.createElement("button");
  parecidos.type = "button";
  parecidos.className = "botao compacto";
  parecidos.textContent = "planos parecidos";
  parecidos.title = "Onde MAIS existe um plano assim, pela imagem";
  parecidos.addEventListener("click", function () {
    procurarParecidos(a.chave, a.inicio_frames, cartao, parecidos);
  });
  acoes.appendChild(parecidos);
  corpo.appendChild(acoes);

  cartao.appendChild(corpo);
  return cartao;
}

/* As falas que casaram, com mm:ss desde o começo do master.
 *
 * ⚠️ mm:ss, e NÃO timecode: só 10 de 306 mídias transcritas têm a taxa gravada no cache
 * (medido), e sem taxa não há conversão honesta. ⛔ E é "onde ouvir", nunca "onde cortar"
 * — quem for montar passa por `transcrever`, que dá o respiro medido. */
function blocoDeFalas(a, cartao) {
  var caixa = document.createElement("div");
  caixa.className = "bus-falas";

  var titulo = document.createElement("p");
  titulo.className = "bus-falas-titulo";
  titulo.textContent = a.quantas_falas === 1
    ? "1 fala diz isso"
    : a.quantas_falas + " falas dizem isso";
  if (a.quantas_falas > (a.falas || []).length) {
    titulo.textContent += " (mostrando " + a.falas.length + ")";
  }
  caixa.appendChild(titulo);

  (a.falas || []).forEach(function (f) {
    // ⭐⭐ A linha é um BOTÃO: clicar carrega no Source o item que contém esta fala —
    //   o subclipe, quando a linha é de um, senão o master.
    // ⛔⛔ No Media Composer não dá para POSICIONAR a agulha: `SetPosition` **não existe**
    //   nesta build (medido em 2026-09-21: `McApiNaoImplementado`) — o timecode escrito ao
    //   lado é o que leva ao quadro.
    // ⭐⭐ No PREMIERE dá (medido em 2026-09-22: `qe.source.player.scrubTo`): a linha manda
    //   os segundos da fala e o serviço põe a agulha lá — no master. No subclipe do
    //   Premiere o zero do `scrubTo` não foi medido, e ele abre sem posicionar.
    var linha = document.createElement("button");
    linha.type = "button";
    linha.className = "bus-fala";
    var posiciona = NO_PREMIERE && !a.item;
    linha.title = a.item
      ? "carregar " + a.item + " no Source (este trecho está dentro dele)"
      : "carregar " + a.midia + " no Source" + (posiciona ? ", com a agulha nesta fala" : "");
    linha.addEventListener("click", function () {
      carregarNoSource(a, cartao, NO_PREMIERE ? f.inicio : undefined, f.tc || f.quando);
    });

    var quando = document.createElement("span");
    quando.className = "bus-quando";
    // ⚠️ O TC completo quando há; o mm:ss quando não há taxa de projeto. Nunca os dois:
    //   duas medidas de tempo na mesma linha é o editor decidindo qual acreditar.
    quando.textContent = f.tc || f.quando;
    quando.classList.toggle("tc", Boolean(f.tc));
    quando.title = f.tc
      ? "timecode de fonte · o SEGUNDO é exato, o quadro é aproximado (a taxa vem do " +
        "projeto aberto, e o arquivo de som não declara a dele)"
      : "minuto e segundo desde o começo do master — sem projeto aberto não há timecode";
    linha.appendChild(quando);

    var texto = document.createElement("span");
    texto.className = "bus-fala-texto";
    texto.textContent = f.texto;
    linha.appendChild(texto);
    if (f.quem) {
      // ⭐ quem fala, pela lapela. Só o nome RESOLVIDO filtra (ambígua e equipe não são ninguém);
      //   o clique não carrega o clipe (a linha inteira é o botão do Source).
      var quem = document.createElement("span");
      quem.className = "bus-quem";
      var resolvido = !/[: ]/.test(f.quem);
      quem.classList.toggle("filtra", resolvido);
      quem.textContent = f.quem;
      quem.title = resolvido
        ? "a lapela mais forte nesta fala — clique para ver só as falas de " + f.quem
        : "quem fala: " + f.quem;
      if (resolvido) {
        quem.addEventListener("click", function (ev) {
          ev.stopPropagation();
          filtrarPorFalante(f.quem);
        });
      }
      linha.appendChild(quem);
    }
    caixa.appendChild(linha);
  });
  return caixa;
}

/* ⭐⭐ O duplo clique: a mídia no monitor Source do Media Composer.
 *
 * ⛔⛔ **A bin precisa estar ABERTA, e isto é medido** (2026-09-21, uma variável só): com a
 * bin fechada o `LoadMobsIntoViewer` devolve "Some mobs was skipped."; abrindo a bin e
 * repetindo, carrega. O serviço faz as duas coisas — e DIZ quando abriu uma bin, porque
 * ela apareceu na tela do editor sem ele ter pedido. */
/* ⭐ O duplo clique e o botão "no Source": no Premiere, a agulha vai ao PONTO do achado.
 *
 * Pedido do editor (2026-09-22): *"se eu abri um clipe que já movi pro meio, ao voltar nesse
 * clipe pela busca o monitor volta de onde estava e não na claquete, que é o foco da busca"*.
 * ⚠️ A decupagem do MASTER não tem posição — descreve o clipe inteiro —, então o ponto é
 * o quadro da nota quando há (nota de take), e senão o INÍCIO do clipe: previsível, e nunca
 * "onde você parou da última vez". No Avid, sem posicionamento (não há `SetPosition`). */
function abrirNoPonto(a, cartao) {
  if (!NO_PREMIERE) { carregarNoSource(a, cartao); return; }
  carregarNoSource(a, cartao, undefined, "", (typeof a.inicio_frames === "number")
    ? a.inicio_frames : 0);
}

function carregarNoSource(a, cartao, segundos, ondeNaFala, quadro) {
  var recado = cartao.querySelector(".bus-recado-carregar") || document.createElement("p");
  recado.className = "bus-recado-carregar reticencias";
  recado.textContent = "carregando no Source";
  cartao.appendChild(recado);
  // ⚠️ MEDIDO no MC 24.6 (2026-10-21): carregar um clipe longo PENDURA o Media Composer ~30 s
  //   antes de responder. Meio minuto de "carregando" sem motivo parece travamento nosso, e o
  //   editor clica de novo — o que pendura o MC outra vez. Passados 5 s, a frase diz de quem é
  //   a espera.
  var demora = setTimeout(function () {
    recado.textContent = "o " + PALAVRAS.nle + " está abrindo a mídia — clipe longo pode levar meio minuto";
  }, 5000);

  fetch("/busca/carregar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // ⭐ O mob do RECORTE quando a linha é de um: carregar o master de um resultado que é
    //   subclipe põe no Source a diária inteira no lugar do trecho que ele clicou.
    body: JSON.stringify({ chave: a.chave, mob: a.mob_do_item || "", nle: NLE,
                           segundos: (typeof segundos === "number") ? segundos : undefined,
                           quadro: (typeof quadro === "number") ? quadro : undefined })
  })
    .then(function (r) { clearTimeout(demora); return r.json(); })
    .then(function (d) {
      recado.className = "bus-recado-carregar";
      if (!d.ok) { recado.classList.add("ruim"); recado.textContent = d.erro; return; }
      // ⚠️ "já estava" é uma resposta DIFERENTE de "carreguei": clicar duas vezes no
      //   mesmo clipe e ler "no Source" de novo deixa o editor sem saber se aconteceu
      //   alguma coisa. (Antes deste conserto, a segunda vez dizia que a mídia podia
      //   estar offline — ver `rota_carregar_no_source`.)
      // ⭐ Sucesso CALADO (pedido do editor, 2026-09-22: o "no Source" verde-água embaixo
      //   do cartão "não é necessário" — o Source mudou na frente dele). Fica só o que ele
      //   precisa saber e não veria: uma bin que abrimos, a agulha que não foi ao ponto.
      var avisos = [];
      if (d.bin_aberta) { avisos.push("abri a bin " + d.bin_aberta); }
      if (d.tc_pedido && !d.posicionado) {
        avisos.push(ondeNaFala ? "não consegui pôr a agulha na fala; vá ao " + ondeNaFala
                               : "não consegui pôr a agulha no ponto");
        recado.classList.add("ruim");
      } else if (d.sem_posicao && ondeNaFala) {
        avisos.push("subclipe aberto no início; a fala está em " + ondeNaFala);
      }
      if (!avisos.length) { recado.remove(); return; }
      recado.textContent = avisos.join(" · ");
      // ⚠️ O aviso some sozinho: ele é confirmação de um gesto, não histórico. Mantido na
      //   tela, ele viraria ruído em cima do próximo resultado que o editor abrir.
      setTimeout(function () { recado.remove(); }, 6000);
    })
    .catch(function (e) {
      clearTimeout(demora);
      recado.className = "bus-recado-carregar ruim";
      recado.textContent = "não consegui falar com o serviço (" + e.message + ")";
    });
}

/* ⭐⭐ "Onde MAIS eu tenho um plano assim?" — e o próprio plano fica FORA da resposta.
 * Trazê-lo de volta faz qualquer motor acertar 100% (banco:
 * `transversal/busca-visual-no-acervo.md`); quem é excluído é o serviço que decide.
 *
 * ⚠️ A medida que sustenta o motor (99% contra 38% ao acaso) foi feita em CENA FECHADA.
 * "Ache a Personagem F em outra cena" continua por medir, e a tela diz isso. */
function procurarParecidos(chave, frame, cartao, botao) {
  var antigo = cartao.querySelector(".bus-parecidos");
  if (antigo) { antigo.remove(); botao.textContent = "planos parecidos"; return; }

  botao.disabled = true;
  botao.textContent = "procurando…";
  fetch("/busca/parecidos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chave: chave, frame: frame, quantos: 6, nle: NLE })
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      botao.disabled = false;
      botao.textContent = d.ok ? "esconder parecidos" : "planos parecidos";
      cartao.appendChild(d.ok ? listaDeParecidos(d) : recadoDoParecido(d.erro));
    })
    .catch(function (e) {
      botao.disabled = false;
      botao.textContent = "planos parecidos";
      cartao.appendChild(recadoDoParecido("não consegui procurar (" + e.message + ")"));
    });
}

function recadoDoParecido(texto) {
  var p = document.createElement("p");
  p.className = "bus-parecidos bus-recado-parecido";
  p.textContent = texto || "não consegui procurar";
  return p;
}

function listaDeParecidos(d) {
  var caixa = document.createElement("div");
  caixa.className = "bus-parecidos";

  var nota = document.createElement("p");
  nota.className = "bus-nota-parecidos";
  nota.textContent = d.quantos === 0
    ? "nenhum outro plano vetorizado no recorte"
    : "parecença medida na imagem; a medida que sustenta isto foi feita em cena fechada";
  caixa.appendChild(nota);

  (d.parecidos || []).forEach(function (p) {
    var linha = document.createElement("div");
    linha.className = "bus-parecido";

    var img = document.createElement("img");
    img.className = "bus-quadro pequeno";
    img.loading = "lazy";
    img.alt = "";
    img.draggable = false;
    img.src = "/busca/quadro?chave=" + encodeURIComponent(p.chave) +
              "&frame=" + encodeURIComponent(p.frame_no_master);
    img.addEventListener("error", function () { img.remove(); });
    linha.appendChild(img);

    var texto = document.createElement("div");
    var nome = document.createElement("span");
    nome.className = "bus-parecido-nome";
    // ⭐ Em material MONTADO vêm vários PLANOS da mesma peça (um vetor por plano): sem
    //   dizer qual é, três linhas com o mesmo nome parecem o mesmo resultado repetido.
    nome.textContent = (p.nome || p.chave.slice(0, 12)) +
      (p.plano ? " · plano " + p.plano + "/" + p.de_planos : "");
    texto.appendChild(nome);
    var medida = document.createElement("span");
    medida.className = "bus-parecenca";
    // ⚠️ Procedência: isto é MEDIDA de parecença visual, não observação confirmada.
    medida.textContent = Math.round(p.parecenca * 100) + "%";
    medida.title = "parecença " + p.parecenca + " · inferido, fonte visual";
    texto.appendChild(medida);
    linha.appendChild(texto);

    caixa.appendChild(linha);
  });
  return caixa;
}

document.getElementById("busProcurar")
  .addEventListener("click", function () { procurarPorFrase(); });
busFrase.addEventListener("keydown", function (e) {
  if (e.key === "Enter") { e.preventDefault(); procurarPorFrase(); }
});
busPreferir.addEventListener("change", function () { procurarPorFrase(); });
busLimpar.addEventListener("click", function () {
  busFrase.value = "";
  busFalante = "";
  Array.prototype.forEach.call(busCampos.querySelectorAll("select"),
    function (s) { s.value = ""; });
  procurarPorFrase();
  busFrase.focus();
});


/* ── a aba Vetores ──────────────────────────────────────────────────────────
 *
 * ⭐ O que já foi analisado, uma linha por MÍDIA. A tela não sabe o que é "atualizado":
 * quem compara a receita gravada com a de hoje é o serviço, e aqui só se pinta o que ele
 * respondeu — a mesma regra do resto deste arquivo (zero lógica de domínio no navegador).
 *
 * ⚠️ Cada linha é um MASTER, e um take sincronizado mistura dois: imagem da câmera, som
 * do gravador. Por isso o normal é a linha ter só UM dos dois chips preenchido, e a
 * espécie fica escrita ao lado do nome para que o vazio não se leia como pendência. */

var vetLista = document.getElementById("vetores");
var vetResumo = document.getElementById("vetResumo");
var vetVazio = document.getElementById("vetVazio");
var vetRecado = document.getElementById("vetRecado");

/* ⭐⭐ Uma célula de estágio tem QUATRO estados, e cada um se lê sem legenda:
 *   vazia   não se aplica (master de som não tem quadro)
 *   —       falta fazer
 *   12      pronto, com a receita de hoje          (verde-água)
 *   12 ↻    existe, mas feito com receita anterior (âmbar) — continua servindo
 * ⚠️ "0" pronto é "analisado, nada achado" (música, ambiente), e o título diz isso: sem ele
 * o editor lê falha e manda refazer. */
function celulaDoEstagio(dado, aplica, unidade) {
  var td = document.createElement("td");
  td.className = "num";
  if (!aplica) { td.dataset.estado = "na"; td.title = "não se aplica a esta mídia"; return td; }
  if (!dado || !dado.tem) {
    td.dataset.estado = "nao";
    td.textContent = "—";
    td.title = "ainda não";
    return td;
  }
  td.textContent = String(dado.quantos || 0);
  if (dado.atualizado) {
    td.dataset.estado = "ok";
    td.title = dado.quantos ? dado.quantos + " " + unidade : "analisado, nada achado";
  } else {
    td.dataset.estado = "refazer";
    td.textContent += " ↻";
    td.title = "feito com uma receita anterior — continua servindo até alguém refazer";
  }
  if (dado.modelo) { td.title += " · " + dado.modelo; }
  return td;
}

function tracksDe(m) {
  var t = m.tracks || {};
  // Quando a varredura ainda não passou, as tracks são desconhecidas: aí as duas colunas
  // valem, para não esconder um estágio que talvez exista.
  var sabemos = (t.video || 0) + (t.audio || 0) > 0;
  return { video: !sabemos || !!t.video, audio: !sabemos || !!t.audio };
}

function nomeDaBin(caminho) {
  return caminho.split(/[\\/]/).pop().replace(/\.avb$/i, "");
}

/* As colunas, na ordem da tela. `chave` devolve o que ORDENA — número ou texto — e é a
 * única conta de domínio aqui: "pronto" vem antes de "a refazer", que vem antes de "falta",
 * e "não se aplica" vai para o fim nos dois sentidos da ordem. */
function pesoDoEstagio(dado, aplica) {
  if (!aplica) { return null; }
  if (!dado || !dado.tem) { return -1; }
  return (dado.atualizado ? 1e6 : 0) + (dado.quantos || 0);
}

var COLUNAS = [
  { id: "nome", rotulo: "Nome",
    chave: function (m) { return (m.nome || m.chave).toLowerCase(); } },
  { id: "tipo", rotulo: "Tipo", chave: function (m) { return m.especie || ""; } },
  { id: "quadros", rotulo: "Quadros", num: true,
    chave: function (m) { return pesoDoEstagio(m.visual, tracksDe(m).video); } },
  { id: "vetor", rotulo: "Vetor", num: true,
    chave: function (m) { return pesoDoEstagio(m.vetor, tracksDe(m).video); } },
  { id: "fala", rotulo: "Fala", num: true,
    chave: function (m) { return pesoDoEstagio(m.fala, tracksDe(m).audio); } },
  { id: "decupagem", rotulo: "Decup.",
    chave: function (m) { return tracksDe(m).video ? (m.decupada ? 1 : 0) : null; } },
  { id: "bin", rotulo: "Bin",
    chave: function (m) {
      return (m.bins && m.bins.length) ? nomeDaBin(m.bins[0]).toLowerCase() : null;
    } },
  { id: "arquivo", rotulo: "Arquivo",
    chave: function (m) {
      // "sem arquivo" (numa bin, fora do disco) primeiro na ordem crescente: é o que pede
      // atenção. Só no cache fica no meio; com arquivo, por último.
      return m.no_acervo ? 2 : ((m.bins && m.bins.length) ? 0 : 1);
    } },
  { id: "tamanho", rotulo: "Tamanho", num: true,
    chave: function (m) { return m.bytes || 0; } }
];

function linhaDaMidia(m) {
  var tr = document.createElement("tr");
  var t = tracksDe(m);
  if (!m.visual.tem && !m.fala.tem) { tr.className = "sem-analise"; }

  var nome = document.createElement("td");
  nome.className = "nome" + (m.nome ? "" : " sem-nome");
  // Sem nome no cache: a chave encurtada serve de identidade, e o título traz a inteira
  // para quem for procurar a pasta no disco.
  nome.textContent = m.nome || m.chave.slice(0, 16) + "…";
  nome.title = m.nome ? m.nome + "\n" + m.chave : m.chave;
  tr.appendChild(nome);

  var tipo = document.createElement("td");
  tipo.textContent = m.especie || "";
  tr.appendChild(tipo);

  tr.appendChild(celulaDoEstagio(m.visual, t.video, "quadros"));
  tr.appendChild(celulaDoEstagio(m.vetor, t.video, "quadros"));
  tr.appendChild(celulaDoEstagio(m.fala, t.audio, "falas"));

  var dec = document.createElement("td");
  if (!t.video) {
    dec.dataset.estado = "na";
  } else if (m.decupada || (m.micro && m.micro.feitos)) {
    dec.dataset.estado = "ok";
    // ⭐ A micro aparece AO LADO da macro: "sim +3/3 trechos".
    var mi = m.micro || {};
    dec.textContent = (m.decupada ? "sim" : "—") +
      (mi.feitos ? " +" + mi.feitos + "/" + (mi.trechos || mi.feitos) + " trechos" : "");
    if (m.notas) { dec.title = m.notas === 1 ? "1 anotação" : m.notas + " anotações"; }
  } else {
    dec.dataset.estado = "nao";
    dec.textContent = "—";
  }
  tr.appendChild(dec);

  var bin = document.createElement("td");
  if (m.bins && m.bins.length) {
    // ⭐ Só o NOME da bin; o caminho dentro do projeto e as outras bins vão no título.
    bin.textContent = nomeDaBin(m.bins[0]) + (m.bins.length > 1 ? " +" + (m.bins.length - 1) : "");
    bin.title = m.bins.join("\n");
  } else {
    bin.dataset.estado = "nao";
    bin.textContent = "—";
    bin.title = "não está em nenhuma bin do projeto lido";
  }
  tr.appendChild(bin);

  var arq = document.createElement("td");
  if (m.no_acervo) {
    arq.textContent = m.arquivos === 1 ? "1 arquivo" : (m.arquivos || 0) + " arquivos";
  } else if (m.bins && m.bins.length) {
    // ⚠️ "sem arquivo", nunca "offline": a mídia pode estar num volume que ninguém mandou
    //    varrer, e chamar de offline seria afirmar o que não se mediu.
    // ⭐ A MESMA conta do `resumo` do serviço (`sem_arquivo`): está numa bin e não no disco
    //   varrido. Na revisão a etiqueta dizia 3 e o resumo 1, porque aqui contava também o que
    //   só existe no cache.
    arq.dataset.estado = "refazer";
    arq.textContent = "sem arquivo";
  } else {
    arq.dataset.estado = "nao";
    arq.textContent = "—";
    arq.title = "só no cache: nem numa bin do projeto lido, nem na pasta varrida";
  }
  tr.appendChild(arq);

  var tam = document.createElement("td");
  tam.className = "num";
  tam.textContent = m.bytes ? tamanhoLegivel(m.bytes) : "—";
  tr.appendChild(tam);

  return tr;
}


function pintarPastas(pastas, varridas) {
  var select = document.getElementById("pastaDeMidia");
  var escolhida = select.value;
  select.textContent = "";
  (pastas || []).forEach(function (p) {
    var op = document.createElement("option");
    op.value = p;
    // ⭐ O que o editor reconhece é o volume, não o caminho inteiro: "D:\ · 358 clipes".
    var quantos = (varridas && varridas[p]) ? varridas[p].clipes : 0;
    op.textContent = p + (quantos ? " · " + quantos + " clipes" : "");
    select.appendChild(op);
  });
  if (escolhida) { select.value = escolhida; }
  document.getElementById("varrerAcervo").disabled = !(pastas || []).length;
}

/* ⚠️ Um acervo de verdade tem centenas de mídias — 358 na varredura desta máquina. Linha
 * de tabela é barata, mas não de graça dentro do Media Composer: o teto continua, e o
 * corte diz que há mais em vez de escondê-lo. */
var TETO_DE_LINHAS = 400;
var midiasNaMao = [];
//: O que está na tela agora, depois do filtro — é sobre isto que os botões agem.
var naTela = [];
//: O que o serviço MEDIU sobre o custo de decupar. Fica aqui só para a tela poder somar.
var precoDaDecupagem = null;
//: O mesmo para a decupagem em trechos — onde o custo é TEMPO de Mac, não dólar.
var precoDaMicro = null;
/*: ⭐⭐ A última leitura das bins do projeto. Sem filtro na tabela, a fila do serviço
 *  trabalha SÓ no projeto aberto — então o rótulo do botão tem de contar as mesmas.
 *  ⚠️ E só quando ALGUMA bin foi lida: sem varredura, "sem bin" quer dizer "ninguém
 *  olhou", e esconder tudo faria os três botões nascerem desabilitados sem motivo. */
var projetoLido = null;

/* ⭐ As etiquetas. Na mesma FAMÍLIA elas somam (imagem OU som); entre famílias, filtram
 * (som E sem transcrição). É o que deixa "o que falta transcrever no som" ser dois cliques. */
var ETIQUETAS = [
  { id: "imagem", familia: "tipo", rotulo: "imagem",
    passa: function (m) { return !!(m.tracks || {}).video; } },
  { id: "som", familia: "tipo", rotulo: "som",
    passa: function (m) { return !!(m.tracks || {}).audio; } },
  { id: "transcrita", familia: "fala", rotulo: "transcrita",
    passa: function (m) { return m.fala.tem; } },
  { id: "sem-transcricao", familia: "fala", rotulo: "sem transcrição",
    passa: function (m) { return tracksDe(m).audio && !m.fala.tem; } },
  { id: "com-vetor", familia: "vetor", rotulo: "com vetor",
    passa: function (m) { return m.vetor.tem; } },
  { id: "sem-vetor", familia: "vetor", rotulo: "sem vetor",
    passa: function (m) { return tracksDe(m).video && !m.vetor.tem; } },
  { id: "decupada", familia: "decupagem", rotulo: "decupada",
    passa: function (m) { return !!m.decupada; } },
  { id: "sem-decupagem", familia: "decupagem", rotulo: "sem decupagem",
    passa: function (m) { return tracksDe(m).video && !m.decupada; } },
  { id: "refazer", familia: "situacao", rotulo: "a refazer",
    passa: function (m) {
      return (m.visual.tem && !m.visual.atualizado) || (m.fala.tem && !m.fala.atualizado) ||
             (m.vetor.tem && !m.vetor.atualizado);
    } },
  { id: "sem-arquivo", familia: "situacao", rotulo: "sem arquivo",
    passa: function (m) { return !m.no_acervo && !!(m.bins && m.bins.length); } },
  { id: "fora-de-bin", familia: "situacao", rotulo: "fora de bin",
    passa: function (m) { return !(m.bins && m.bins.length); } }
];
var etiquetasLigadas = {};

// ⭐ A ordem escolhida sobrevive ao Reload: é preferência de quem olha, não dado do
//   produto. ⚠️ `localStorage` pode não existir ou levantar numa webview — a tela vive sem.
var ordem = { coluna: "nome", desc: false };
try {
  var guardada = JSON.parse(localStorage.getItem("cicloassist.vetores.ordem") || "null");
  if (guardada && guardada.coluna) { ordem = guardada; }
} catch (e) { /* sem memória, ordem padrão */ }

function combina(m, procura) {
  if (procura) {
    var onde = ((m.nome || m.chave) + " " + (m.bins || []).join(" ")).toLowerCase();
    if (onde.indexOf(procura) < 0) { return false; }
  }
  var familias = {};
  ETIQUETAS.forEach(function (e) {
    if (!etiquetasLigadas[e.id]) { return; }
    familias[e.familia] = familias[e.familia] || e.passa(m);
  });
  for (var f in familias) {
    if (!familias[f]) { return false; }
  }
  return true;
}

function comparar(a, b) {
  var col = COLUNAS.filter(function (c) { return c.id === ordem.coluna; })[0] || COLUNAS[0];
  var ka = col.chave(a), kb = col.chave(b);
  // "Não se aplica" vai para o FIM nos dois sentidos: invertê-lo junto encheria o topo da
  // ordem decrescente de linhas de som vazias quando o editor ordena por quadros.
  if (ka === null && kb === null) { return 0; }
  if (ka === null) { return 1; }
  if (kb === null) { return -1; }
  var r = typeof ka === "number" ? ka - kb : String(ka).localeCompare(String(kb), "pt-BR");
  if (r === 0 && col.id !== "nome") {
    r = (a.nome || a.chave).localeCompare(b.nome || b.chave, "pt-BR");
    return r;
  }
  return ordem.desc ? -r : r;
}

function pintarCabeca() {
  var cabeca = document.getElementById("vetCabeca");
  cabeca.textContent = "";
  COLUNAS.forEach(function (c) {
    var th = document.createElement("th");
    th.scope = "col";
    if (c.num) { th.className = "num"; }
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = c.rotulo;
    if (ordem.coluna === c.id) {
      th.setAttribute("aria-sort", ordem.desc ? "descending" : "ascending");
      b.dataset.ordem = ordem.desc ? "desc" : "asc";
    }
    b.title = "Ordenar por " + c.rotulo.toLowerCase();
    b.addEventListener("click", function () {
      // Primeiro clique ordena; o segundo, na mesma coluna, inverte.
      ordem = ordem.coluna === c.id ? { coluna: c.id, desc: !ordem.desc }
                                    : { coluna: c.id, desc: !!c.num };
      try { localStorage.setItem("cicloassist.vetores.ordem", JSON.stringify(ordem)); }
      catch (e) { /* segue sem lembrar */ }
      pintarLista();
    });
    th.appendChild(b);
    cabeca.appendChild(th);
  });
}

function pintarEtiquetas() {
  var onde = document.getElementById("vetTags");
  onde.textContent = "";
  ETIQUETAS.forEach(function (e) {
    // A conta é sobre o acervo INTEIRO, e não sobre o filtrado: um número que muda a cada
    // clique não diz quanto há de cada coisa.
    var quantas = midiasNaMao.filter(e.passa).length;
    var b = document.createElement("button");
    b.type = "button";
    b.className = "vet-tag";
    b.setAttribute("aria-pressed", etiquetasLigadas[e.id] ? "true" : "false");
    b.textContent = e.rotulo;
    var n = document.createElement("b");
    n.textContent = String(quantas);
    b.appendChild(n);
    b.addEventListener("click", function () {
      etiquetasLigadas[e.id] = !etiquetasLigadas[e.id];
      pintarEtiquetas();
      pintarLista();
    });
    onde.appendChild(b);
  });
}

function pintarLista() {
  var procura = document.getElementById("vetProcura").value.trim().toLowerCase();
  var escolhidas = midiasNaMao.filter(function (m) { return combina(m, procura); });
  escolhidas.sort(comparar);

  // ⭐⭐ O que a lista MOSTRA é o que os botões fazem. Sem isto, filtrar "a refazer" e
  //   clicar em transcrever mandava a fila para o acervo inteiro — e o editor só
  //   descobriria pela barra de progresso, horas depois.
  naTela = escolhidas;

  pintarCabeca();
  vetLista.textContent = "";
  escolhidas.slice(0, TETO_DE_LINHAS).forEach(function (m) {
    vetLista.appendChild(linhaDaMidia(m));
  });

  var corte = document.getElementById("vetCorte");
  if (escolhidas.length > TETO_DE_LINHAS) {
    corte.hidden = false;
    corte.textContent = "mostrando " + TETO_DE_LINHAS + " de " + escolhidas.length +
      " — procure ou filtre para achar uma";
  } else {
    corte.hidden = true;
  }
  // O vazio da BUSCA não é o vazio do cache: quem procurou e não achou precisa saber
  // que procurou, não ler o texto de boas-vindas do primeiro dia.
  vetVazio.hidden = escolhidas.length > 0 || (midiasNaMao.length > 0);
  document.querySelector(".vet-rolagem").hidden = !escolhidas.length;
  if (!escolhidas.length && midiasNaMao.length) {
    corte.hidden = false;
    corte.textContent = "nenhuma mídia com esse filtro";
  }
  pintarAcoes();
}

document.getElementById("vetProcura").addEventListener("input", pintarLista);


function pintarVetores(d) {
  var midias = (d && d.midias) || [];
  var r = (d && d.resumo) || {};

  midiasNaMao = midias;
  pintarEtiquetas();
  pintarLista();
  pintarPastas(d && d.pastas, d && d.varridas);

  var conta = r.midias === 1 ? "1 mídia" : (r.midias || 0) + " mídias";
  var partes = [conta, (r.com_visual || 0) + " com visual",
                (r.com_fala || 0) + " com fala"];
  if (r.com_vetor) { partes.push(r.com_vetor + " com vetor"); }
  if (r.decupadas) { partes.push(r.decupadas + " decupadas"); }
  if (r.sem_arquivo) { partes.push(r.sem_arquivo + " sem arquivo"); }
  if (r.sem_analise) { partes.push(r.sem_analise + " sem análise"); }
  if (r.desatualizadas) { partes.push(r.desatualizadas + " a refazer"); }
  partes.push(tamanhoLegivel(r.bytes || 0));
  vetResumo.textContent = partes.join(" · ");
}

/*: Quando a lista foi lida com sucesso pela última vez, e por quanto ela serve.
 *
 * ⭐⭐ Sem isto, VOLTAR para a aba relia tudo — e o editor notou: *"me parece que sempre
 * que saio da aba e volto, ele tenta ler tudo novamente"*. Com 66 s isso era o problema;
 * depois do conserto de 2026-09-23 são 0,6 s, e passou a ser desperdício — mas desperdício
 * que custa duas idas à PONTE do Premiere, que é a mesma fila do chat.
 *
 * ⚠️ Trinta segundos, a mesma validade do recorte do projeto. E quem MUDA os dados não
 * espera por ela: o fim de uma tarefa, a troca de projeto, a leitura de bins e o botão
 * "Atualizar" forçam. O que a guarda evita é só a releitura de quem não mudou nada. */
var VALIDADE_DA_LISTA_MS = 30000;
var listaLidaEm = 0;

function carregarVetores(forcar) {
  if (!forcar && listaLidaEm && Date.now() - listaLidaEm < VALIDADE_DA_LISTA_MS) {
    // A tabela continua na tela: não fazer nada É a resposta certa.
    return;
  }
  vetRecado.hidden = true;
  vetResumo.textContent = "lendo o cache…";
  // ⚠️ A leitura percorre a pasta inteira e pode levar segundos com centenas de mídias.
  //    Sem esta reticência a aba fica parada e parece travada — o mesmo motivo dos
  //    outros três lugares que a usam.
  vetResumo.className = "vet-resumo reticencias";
  // ⭐⭐ O editor vai na query: cada editor lista o SEU banco, e no Premiere as linhas
  //   do "o que falta" são os arquivos do projeto dele (2026-09-22).
  fetch("/vetores?nle=" + NLE, { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      vetResumo.className = "vet-resumo";
      // ⚠️ Só depois de a resposta CHEGAR: marcando antes, uma leitura que falha deixaria
      //   a guarda ligada e a aba mostraria "não consegui ler" por trinta segundos.
      listaLidaEm = Date.now();
      pintarVetores(d);
      // Uma varredura pode ter sobrevivido à troca de aba, ao Reload, ou ter sido
      // começada antes de o painel abrir. Se ela ainda corre, a tela volta a acompanhar.
      if (d && d.tarefa) { pintarTarefa(d.tarefa); }
      projetoLido = (d && d.projeto) || null;
      pintarProjeto(d && d.projeto);
      precoDaDecupagem = (d && d.decupagem) || null;
      precoDaMicro = (d && d.micro) || null;
      densidadeDoServico = (d && d.densidade) || null;
      pintarVigia(d && d.vigia);
      pintarAcoes();
    })
    .catch(function () {
      vetResumo.className = "vet-resumo";
      vetResumo.textContent = "";
      vetRecado.hidden = false;
      vetRecado.className = "config-recado ruim";
      vetRecado.textContent = "Não consegui ler o cache. O serviço está no ar?";
    });
}

// ⭐ "Atualizar" é o gesto de quem QUER a leitura de novo: fura a guarda sempre.
document.getElementById("recarregarVetores")
  .addEventListener("click", function () { carregarVetores(true); });


/* ── procurar a mídia em disco ───────────────────────────────────────────────
 *
 * ⭐⭐ **O trabalho acontece FORA do turno**, que é o ponto do desenho: o editor manda
 * procurar e volta a montar. A tela consulta o andamento enquanto houver tarefa viva e
 * para de consultar quando acaba — nunca fica batendo à toa. */

var vetAndamento = document.getElementById("vetAndamento");
var vetAndamentoTexto = document.getElementById("vetAndamentoTexto");
var relogioDaTarefa = null;

function frasesDaTarefa(t) {
  var transcrevendo = t.tipo === "transcricao";
  var vetorizando = t.tipo === "vetores";
  var decupando = t.tipo === "decupagem" || t.tipo === "micro";
  if (t.estado === "correndo") {
    var o_que = transcrevendo ? "transcrevendo · "
              : vetorizando ? "olhando os planos · "
              : decupando ? "decupando · " : "procurando mídia · ";
    return o_que + Math.round((t.fracao || 0) * 100) + "% · " + (t.texto || "");
  }
  if (t.estado === "erro") { return "não deu certo: " + (t.erro || ""); }

  var r = t.resumo || {};
  var quantos;
  if (transcrevendo || vetorizando || decupando) {
    quantos = (r.feitas || 0) + " de " + (r.na_fila || 0) +
      (vetorizando ? " vetorizadas" : decupando ? " decupadas" : " transcritas") +
      // ⭐ O que a cópia resolveu sem processar nada (Premiere): sem o número, "2 de 10"
      //   se leria como oito que falharam.
      (r.aproveitadas ? " · " + r.aproveitadas + " já estavam analisadas (aproveitadas)" : "") +
      (r.vigia ? " · importadas, a vigia mandou" : "") +
      (r.falharam ? " · " + r.falharam + " falharam" : "");
    // ⭐ O gasto REAL, depois do trabalho: o editor compara com a estimativa que leu
    //   antes de clicar, e é assim que ele passa a confiar no número.
    if (r.custo_usd) {
      quantos += " · US$ " + r.custo_usd.toFixed(2) + " (" +
        Math.round((r.tokens || 0) / 1000) + " mil tokens)";
    }
  } else {
    quantos = r.clipes ? r.clipes + " clipes em " + r.arquivos + " arquivos"
                       : "nada encontrado";
  }
  if (t.estado === "parada") { return "parada · " + quantos + " até aqui"; }
  return "pronto · " + quantos + " em " + Math.round(t.segundos) + " s";
}

function pintarTarefa(t) {
  if (!t) {
    vetAndamento.hidden = true;
    return;
  }
  vetAndamento.hidden = false;
  vetAndamento.querySelector("b").style.width =
    Math.round((t.fracao || 0) * 100) + "%";
  vetAndamentoTexto.textContent = frasesDaTarefa(t);
  vetAndamentoTexto.className = "vet-andamento-texto" +
    (t.estado === "correndo" ? " reticencias" : "");
  document.getElementById("pararTarefa").hidden = t.estado !== "correndo";
  // ⚠️ Uma tarefa por vez: o que roda no fundo disputa a máquina com o ASR do turno.
  //    Os dois botões desabilitam juntos, para o editor ver o motivo em vez de levar um
  //    "já há uma análise em andamento" no clique.
  document.getElementById("varrerAcervo").disabled = t.estado === "correndo";
  ["transcreverFalta", "vetorizarFalta", "decuparFalta", "microFalta"].forEach(function (id) {
    document.getElementById(id).disabled = t.estado === "correndo";
  });
  // ⚠️ Terminou: os rótulos precisam recontar, senão o botão continua dizendo o número
  //    de antes do trabalho.
  if (t.estado !== "correndo") { pintarAcoes(); }

  if (t.estado === "correndo") {
    acompanharTarefa();
  } else if (relogioDaTarefa) {
    clearTimeout(relogioDaTarefa);
    relogioDaTarefa = null;
  }
}

function acompanharTarefa() {
  if (relogioDaTarefa) { return; }
  relogioDaTarefa = setTimeout(function () {
    relogioDaTarefa = null;
    fetch("/vetores/andamento", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var t = d && d.tarefa;
        pintarTarefa(t);
        // Acabou: a lista muda inteira, e relê-la é mais barato que remendá-la.
        // ⛔ FORÇA: a tarefa mexeu no cache, e a guarda de 30 s guardaria o de antes.
        if (t && t.estado !== "correndo") { carregarVetores(true); }
      })
      .catch(function () { pintarTarefa(null); });
  }, 1000);
}

function pintarProjeto(p) {
  var onde = document.getElementById("vetProjeto");
  // ⭐⭐ No Premiere a lista vem do projeto ABERTO nele (serviço de 2026-09-22 em diante).
  //   ⚠️ Serviço velho não diz `editor` — e aí a aba ainda é a do Media Composer, e a
  //   tela diz isso em vez de apresentar as bins dele como se fossem este projeto.
  var doPremiere = NO_PREMIERE && p && p.editor === "premiere";
  var doOutro = NO_PREMIERE && !doPremiere ? " (do Media Composer, não deste projeto do Premiere)" : "";
  if (doPremiere) {
    var arq = (p.caminho || "").split(/[\\/]/).filter(Boolean).pop() || "";
    onde.textContent = p.erro ? p.erro
      : (p.masters || 0) + " clipe(s) no projeto" + (arq ? " " + arq : "") +
        " · o que ainda não foi analisado aparece como falta";
    return;
  }
  if (!p || !p.masters) {
    onde.textContent = "as bins do projeto aberto no Media Composer";
    return;
  }
  // ⭐ Só o nome da pasta do projeto: o caminho inteiro não cabe em 340 px e não diz
  //   nada que o editor já não saiba.
  var nome = (p.caminho || "").split(/[\\/]/).filter(Boolean).pop() || "";
  onde.textContent = p.masters + " masterclipes lidos" + (nome ? " de " + nome : "") + doOutro;
}

/* ⭐⭐ O editor trocou de projeto — e ninguém avisa.
 *
 * ⛔ NÃO HÁ EVENTO de projeto no Media Composer: o sniffer do banco (2026-08-07) mapeou os
 * eventos do canal `general` e mediu que ampliar o `usesApi` aos cinco canais não
 * acrescenta tipo nenhum. Abrir e fechar projeto não emite nada.
 *
 * ⛔ E perguntar custa 0,5 a 0,75 s (medido 2026-09-14, com conexão nova e reaproveitada:
 * o piso é da API). Um relógio de poucos segundos batendo no MC está fora de cogitação.
 *
 * ⇒ Quem pergunta é o GESTO: a aba abriu, ou a janela voltou ao foco — que é exatamente
 * o que o editor faz depois de trocar de projeto. Mais uma sondagem lenta enquanto a aba
 * estiver à vista, para o caso de ele trocar e ficar olhando o painel. */
var PROJETO_MINIMO_MS = 8000;      // nunca duas perguntas coladas
var PROJETO_SONDAGEM_MS = 30000;   // e uma lenta, só com a aba Vetores à vista
var ultimaOlhadaNoProjeto = 0;
var sondagemDoProjeto = null;

function olharOProjeto(porque) {
  var agora = Date.now();
  if (agora - ultimaOlhadaNoProjeto < PROJETO_MINIMO_MS) { return; }
  ultimaOlhadaNoProjeto = agora;
  fetch("/projeto?nle=" + NLE, { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.mudou) { return; }
      // ⭐ Trocou: a lista inteira muda (outro recorte), e relê-la é mais barato que
      //   remendá-la — a mesma regra do fim de uma tarefa.
      vetRecado.hidden = false;
      vetRecado.className = "config-recado";
      // ⭐ Desde 2026-09-22 a fila também segue o editor no Premiere (a lista vem do
      //   projeto aberto nele). Antes esta frase prometia só a busca, de propósito.
      vetRecado.textContent = "O projeto aberto agora é " + (d.nome || "outro") +
        (NO_PREMIERE ? ". A busca e a fila passam a trabalhar nos clipes dele."
             : ". A busca e a fila passam a trabalhar nas bins dele.") +
        // ⭐ Dizer que a conversa zerou é parte do trato: o editor escolheu começar
        //   limpo para não gastar token à toa, e uma conversa que some calada assusta.
        (d.conversa_limpa ? " A conversa recomeçou do zero." : "");
      // ⛔ FORÇA: outro projeto é outra lista inteira.
      carregarVetores(true);
    })
    .catch(function () { /* sem serviço a tela já reclama noutro lugar */ });
}

/* ⚠️ `visibilitychange` cobre o painel do MC, que é uma webview escondida quando a
 * janela some; `focus` cobre voltar para ela sem que a visibilidade mude. */
document.addEventListener("visibilitychange", function () {
  if (!document.hidden) { olharOProjeto("visivel"); }
});
window.addEventListener("focus", function () { olharOProjeto("foco"); });

function acompanharOProjeto(ligado) {
  if (sondagemDoProjeto) { clearInterval(sondagemDoProjeto); sondagemDoProjeto = null; }
  if (ligado) {
    sondagemDoProjeto = setInterval(function () { olharOProjeto("sondagem"); },
                                    PROJETO_SONDAGEM_MS);
  }
}

/* ⭐ A vigia do Premiere (`servico/vigia.py`): importou, processa sozinho.
 *
 * ⚠️ O trabalho começa SEM clique, e a tela precisa notar: enquanto a vigia está ligada e a
 * aba à vista, pergunta-se pelo andamento a cada 5 s — senão a barra de progresso só
 * apareceria quando ele clicasse "Atualizar", e trabalho invisível parece defeito. */
var vigiaLigada = document.getElementById("vigiaLigada");
var vigiaEstado = document.getElementById("vigiaEstado");
var relogioDaVigia = null;
if (NO_PREMIERE) { document.getElementById("vetVigia").hidden = false; }

function pintarVigia(v) {
  if (!NO_PREMIERE) { return; }
  // ⚠️ Serviço velho não tem vigia: o interruptor some em vez de prometer o que não faz.
  document.getElementById("vetVigia").hidden = !v;
  if (!v) { return; }
  vigiaLigada.checked = !!v.ligada;
  var partes = [];
  if (!v.ligada) {
    partes.push("desligada · os botões acima continuam valendo");
  } else {
    partes.push("vigiando o projeto");
    if (v.chegaram) { partes.push(v.chegaram + " importado(s) desde que ligou"); }
    if (v.pendentes && v.pendentes.length) {
      partes.push("a processar: " + v.pendentes.slice(0, 3).join(", ") +
                  (v.pendentes.length > 3 ? "…" : ""));
    }
    if (v.erro) { partes.push(v.erro); }
  }
  vigiaEstado.textContent = partes.join(" · ");
  acompanharAVigia(!!v.ligada);
}

//: O último estado conhecido do interruptor — o relógio depende dele E da aba à vista, e
//: as duas notícias chegam por caminhos diferentes (a resposta do serviço e o clique na aba).
var vigiaEstaLigada = false;

function acompanharAVigia(ligado) {
  if (ligado !== undefined) { vigiaEstaLigada = !!ligado; }
  if (relogioDaVigia) { clearInterval(relogioDaVigia); relogioDaVigia = null; }
  // ⚠️ `document.hidden` é a JANELA escondida; a aba do painel é outra coisa. Sem as duas
  //   condições, trocar para a conversa deixava a vigia perguntando para sempre.
  if (!vigiaEstaLigada || telaAVista !== "vetores") { return; }
  relogioDaVigia = setInterval(function () {
    if (document.hidden) { return; }
    fetch("/vetores/vigia", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (v) {
        pintarVigia(v);
        return fetch("/vetores/andamento", { cache: "no-store" });
      })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var t = d && d.tarefa;
        if (t && t.estado === "correndo" && vetAndamento.hidden) { pintarTarefa(t); }
      })
      .catch(function () { /* sem serviço a tela já reclama noutro lugar */ });
  }, 5000);
}

vigiaLigada.addEventListener("change", function () {
  vigiaLigada.disabled = true;
  fetch("/vetores/vigia", { method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ ligada: vigiaLigada.checked, nle: NLE }) })
    .then(function (r) { return r.json(); })
    .then(function (v) { vigiaLigada.disabled = false; pintarVigia(v); })
    .catch(function () {
      vigiaLigada.disabled = false;
      vigiaLigada.checked = !vigiaLigada.checked;
      vetRecado.hidden = false;
      vetRecado.className = "config-recado ruim";
      vetRecado.textContent = "Não consegui falar com o serviço.";
    });
});

/* ⛔ No Premiere não há `Avid MediaFiles` a varrer nem bin do Media Composer a ler: a
 * lista vem do projeto aberto, e "Ler as bins" mandaria o serviço ao Avid — a mesma
 * armadilha que a revisão de 2026-09-17 fechou do lado do servidor. */
if (NO_PREMIERE) {
  document.getElementById("vetPastas").hidden = true;
  document.getElementById("lerBins").hidden = true;
}

document.getElementById("lerBins").addEventListener("click", function () {
  var botao = document.getElementById("lerBins");
  botao.disabled = true;
  vetRecado.hidden = true;
  fetch("/vetores/bins", { method: "POST",
                           headers: { "Content-Type": "application/json" },
                           body: "{}" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      botao.disabled = false;
      if (!d.ok) {
        vetRecado.hidden = false;
        vetRecado.className = "config-recado ruim";
        vetRecado.textContent = d.erro || "Não consegui ler as bins.";
        return;
      }
      // ⛔ FORÇA: a coluna de bins acabou de mudar, e é por ela que ele clicou.
      carregarVetores(true);
    })
    .catch(function () {
      botao.disabled = false;
      vetRecado.hidden = false;
      vetRecado.className = "config-recado ruim";
      vetRecado.textContent = "Não consegui falar com o serviço.";
    });
});

document.getElementById("varrerAcervo").addEventListener("click", function () {
  var pasta = document.getElementById("pastaDeMidia").value;
  if (!pasta) { return; }
  vetRecado.hidden = true;
  fetch("/vetores/varrer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pasta: pasta })
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) {
        vetRecado.hidden = false;
        vetRecado.className = "config-recado ruim";
        vetRecado.textContent = d.erro || "Não consegui começar.";
      }
      pintarTarefa(d.tarefa);
    })
    .catch(function () {
      vetRecado.hidden = false;
      vetRecado.className = "config-recado ruim";
      vetRecado.textContent = "Não consegui falar com o serviço.";
    });
});

function analisar(estagio) {
  vetRecado.hidden = true;
  var refazer = document.getElementById("refazerTudo").checked;
  var pedido = { estagio: estagio, refazer: refazer };

  // Filtro ligado quer dizer "é destas que eu falo". Sem filtro, manda a lista toda —
  // e aí `chaves` fica de fora, para o serviço decidir o que falta.
  if (filtrando()) {
    pedido.chaves = naTela.map(function (m) { return m.chave; });
  }

  // ⭐ A densidade vale para a decupagem (a macro): é ela que decide quantos quadros o
  //   modelo olha por mídia, e foi o preço desse nível que o editor leu antes de clicar.
  if (estagio === "decupagem") { pedido.densidade = densidadeEscolhida(); }
  pedido.nle = NLE;
  fetch("/vetores/analisar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pedido)
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) {
        vetRecado.hidden = false;
        vetRecado.className = "config-recado ruim";
        vetRecado.textContent = d.erro || "Não consegui começar.";
      } else if (d.fora_do_projeto) {
        // ⚠️ Filtro calado vira "o produto ignorou minhas mídias". A fila diz quantas
        //    ficaram de fora e como incluí-las — não é erro, é recado.
        vetRecado.hidden = false;
        vetRecado.className = "config-recado";
        vetRecado.textContent = d.fora_do_projeto + " mídia(s) fora das bins do projeto " +
          "ficaram de fora. Para incluí-las, filtre a tabela e mande de novo.";
      }
      // ⚠️ Desarma sozinho: refazer é caro, e um interruptor que fica ligado vira uma
      //    armadilha no próximo clique.
      document.getElementById("refazerTudo").checked = false;
      pintarAcoes();
      pintarTarefa(d.tarefa);
    })
    .catch(function () {
      vetRecado.hidden = false;
      vetRecado.className = "config-recado ruim";
      vetRecado.textContent = "Não consegui falar com o serviço.";
    });
}

function filtrando() {
  return !!document.getElementById("vetProcura").value.trim() ||
    Object.keys(etiquetasLigadas).some(function (k) { return etiquetasLigadas[k]; });
}

/* ⭐⭐ Quantas mídias cada botão vai pegar DE VERDADE.
 *
 * ⚠️ Não é "quantas estão na tela": transcrever só pega quem tem áudio, vetorizar e
 * decupar só pegam quem tem imagem, e decupar pula quem já foi decupada. Rotular os três
 * botões com o mesmo número (o da lista) prometia trabalho que o serviço ia filtrar de
 * novo — e a conta de custo saía inflada, que é o pior lugar para arredondar para cima. */
function alvosDe(estagio) {
  var refazer = document.getElementById("refazerTudo").checked;
  var candidatas = filtrando() ? naTela : midiasNaMao;
  // ⭐ Sem filtro, quem manda é o projeto: o serviço só enfileira o que está em alguma
  //   bin dele, e um rótulo maior que a fila é um botão que mente (e um preço inflado).
  if (!filtrando() && projetoLido && projetoLido.masters) {
    candidatas = candidatas.filter(function (m) { return (m.bins || []).length; });
  }
  return candidatas.filter(function (m) {
    // ⛔⛔ O que a FILA consegue pegar, dito pelo SERVIÇO (`inventario.pode_analisar`):
    //   arquivo da espécie certa e taxa conhecida. Enquanto esta conta era da tela, o
    //   rótulo contava mídia que a fila pulava em silêncio — o autor viu em 2026-09-20,
    //   com 100 de 106 "sem transcrição" sem arquivo em disco: clicava e nada acontecia.
    //   ⚠️ E na decupagem o PREÇO saía inflado junto.
    // ⚠️ `pode` ausente (serviço velho) não some com o botão: cai no comportamento de
    //   antes, que é contar pelas tracks.
    var pode = m.pode || {};
    if (pode[estagio] === false) { return false; }
    var tracks = m.tracks || {};
    if (estagio === "transcricao") {
      return tracks.audio && (refazer || !m.fala.tem || !m.fala.atualizado);
    }
    if (estagio === "vetores") {
      return tracks.video && (refazer || !m.vetor.tem || !m.vetor.atualizado);
    }
    if (estagio === "micro") {
      var mi = m.micro || {};
      return tracks.video && (refazer || !mi.trechos || (mi.feitos || 0) < mi.trechos);
    }
    return tracks.video && (refazer || !m.decupada);
  });
}

/* Os rótulos dizem o que vai acontecer: quantas mídias, e se é refazer ou completar. */
function pintarAcoes() {
  var refazer = document.getElementById("refazerTudo").checked;

  function rotular(id, nome, estagio) {
    var quantas = alvosDe(estagio).length;
    document.getElementById(id).textContent = nome + (quantas ? " (" + quantas + ")" : "");
    document.getElementById(id).disabled = !quantas;
  }

  rotular("vetorizarFalta", refazer ? "Refazer a imagem" : "Vetorizar a imagem", "vetores");
  rotular("transcreverFalta", refazer ? "Refazer a fala" : "Transcrever a fala",
          "transcricao");
  rotular("decuparFalta", refazer ? "Redecupar a imagem" : "Decupar a imagem", "decupagem");
  rotular("microFalta", refazer ? "Redecupar em trechos" : "Decupar em trechos", "micro");
  // ⚠️ A micro é do Mac: sem ele o botão fica desligado e DIZ por quê (a fila recusaria).
  // ⚠️ `precoDaMicro` é quem responde isto; `precoDaDecupagem` só fica como rede para um
  //   serviço velho, que não manda o campo novo (a tela não pode sumir com o botão por
  //   causa da idade do processo por trás — a régua de 2026-09-20).
  var semMac = precoDaMicro ? precoDaMicro.motor !== "mac"
    : !(precoDaDecupagem && precoDaDecupagem.motor === "mac");
  if (semMac) {
    document.getElementById("microFalta").disabled = true;
    document.getElementById("microFalta").title =
      "A decupagem em trechos roda no Mac — configure o endereço dele.";
  }

  document.querySelector(".vet-acoes").classList.toggle("armado", refazer);
  pintarPrecoDaDecupagem(alvosDe("decupagem").length);
  pintarPrecoDaMicro(alvosDe("micro"));
}

//: O que o serviço diz sobre cada nível de densidade — quadros, tokens e dólar por mídia.
var densidadeDoServico = null;

function densidadeEscolhida() {
  var el = document.getElementById("densidade");
  return (el && el.value) || (densidadeDoServico && densidadeDoServico.padrao) || "macro";
}

/* O nível escolhido, como o serviço o descreve. ⚠️ Serviço velho não manda `densidade`:
 * cai no comportamento de antes (o preço de 6 quadros, que é o medido). */
function nivelDaDensidade() {
  var niveis = (densidadeDoServico && densidadeDoServico.niveis) || null;
  return (niveis && niveis[densidadeEscolhida()]) || null;
}

/* ⭐⭐ O preço ANTES do clique. É o único trabalho do produto que consome a assinatura do
 * editor sem ele ter perguntado nada — e um número é a diferença entre ele decidir e ele
 * descobrir depois. Os valores vêm MEDIDOS do serviço; a tela só multiplica. */
function pintarPrecoDaDecupagem(alvo) {
  var onde = document.getElementById("precoDecupagem");
  if (!precoDaDecupagem || !alvo) { onde.hidden = true; return; }

  // ⭐ A densidade muda a conta: 24 quadros custam ~8 mil tokens a mais por mídia que 6.
  var nivel = nivelDaDensidade();
  var segundosPorMidia = (nivel && nivel.segundos_por_midia) ||
    precoDaDecupagem.segundos_por_midia;
  var minutos = Math.round(alvo * segundosPorMidia / 60);
  var dolar = alvo * ((nivel && nivel.custo_por_midia_usd) ||
    precoDaDecupagem.custo_por_midia_usd);
  var botao = document.getElementById("decuparFalta");
  onde.hidden = false;
  // ⭐ Com o Mac a conta é outra: tempo dele, zero assinatura — e o notebook precisa ficar
  //   acordado, porque os quadros saem daqui. Dizer o preço do Claude seria mentir.
  // ⚠️ A densidade é DITA, sempre: sem ela, o mesmo botão com o mesmo rótulo cobraria
  //   preços diferentes sem nada na tela explicando por quê.
  // ⛔ O que o motor vai olhar DE VERDADE, nunca o do nível escolhido: no Mac o contexto
  //   do Ollama tem teto, e o que passa ele corta CALADO. Quem faz essa conta é o serviço
  //   (`quadros_efetivos`), que sabe qual motor vai rodar.
  var efetivos = nivel ? (nivel.quadros_efetivos || nivel.quadros) : 0;
  var quantosQuadros = nivel ? efetivos + " quadros por mídia" : "";
  if (nivel && efetivos < nivel.quadros) {
    quantosQuadros += " (o teto do Mac; você pediu " + nivel.quadros + ")";
  }
  if (precoDaDecupagem.motor === "mac") {
    botao.title = "O Mac mini olha os quadros e escreve a decupagem — não usa a sua assinatura";
    onde.textContent = "🖥 " + alvo + " mídia(s) no Mac (" + precoDaDecupagem.modelo + ") ≈ " +
      (minutos < 60 ? minutos + " min" : (minutos / 60).toFixed(1).replace(".", ",") + " h") +
      (quantosQuadros ? " · " + quantosQuadros : "") +
      " · sem gastar a assinatura · deixe este computador acordado";
    return;
  }
  botao.title = "O Claude olha os quadros e escreve a decupagem — isto consome a sua assinatura";
  var tokens = (nivel && nivel.tokens_por_midia) || precoDaDecupagem.tokens_por_midia;
  onde.textContent = "⚠️ " + alvo + " mídia(s) ≈ US$ " + dolar.toFixed(2) + " e " +
    (minutos < 1 ? "menos de 1 min" : minutos + " min") + " da sua assinatura · " +
    // ⛔ "medido" só onde houve medição: o preço dos outros níveis é a conta do medido
    //   mais o tamanho de cada quadro a mais, e apresentá-lo como medido seria a mentira
    //   que este produto mais promete não contar.
    (nivel && !nivel.medido ? "estimado em " : "medido em ") +
    Math.round(tokens / 1000) + " mil tokens por mídia" +
    (quantosQuadros ? " · " + quantosQuadros : "");
}

/* "40 min" · "2 h 10" · "13 h" — ordem de grandeza, que é o que decide o clique. Minuto a
 * minuto numa conta de horas é precisão que a estimativa não tem. */
function emHoras(segundos) {
  var min = Math.round(segundos / 60);
  if (min < 60) { return Math.max(1, min) + " min"; }
  var h = Math.floor(min / 60);
  var resto = min % 60;
  if (h >= 10) { return h + " h"; }
  return h + " h" + (resto ? " " + String(resto).padStart(2, "0") : "");
}

/* ⭐⭐ Quanto tempo a decupagem em trechos vai levar — e por que ela é FAIXA e não número.
 *
 * Duas populações na mesma lista, e elas se contam de jeitos diferentes:
 *
 *   - mídia que já teve os cortes procurados: o número de trechos é REAL, e bruto/montado
 *     está gravado no `cortes.json`. Conta exata.
 *   - mídia que ninguém varreu: o número de trechos é estimado por minuto de material, e
 *     ⛔ bruto e montado diferem em ~6× (50 s × 3/min contra 87 s × 11/min). Escolher um
 *     seria acertar por sorte — e errar para BAIXO faria o editor começar às 18 h um
 *     trabalho de nove horas achando que eram noventa minutos. A tela mostra os dois.
 *
 * ⚠️ Quem não tem duração medida (mídia que só aparece na bin) fica FORA da conta e é
 * contada à parte: somar zero por ela encolheria o total em silêncio. */
function contaDaMicro(alvos) {
  var refazer = document.getElementById("refazerTudo").checked;
  var seg = precoDaMicro.segundos_por_trecho || {};
  var porMin = precoDaMicro.trechos_por_minuto || {};
  var conta = { trechos: 0, segBruto: 0, segMontado: 0, estimadas: 0, semConta: 0 };
  alvos.forEach(function (m) {
    var mi = m.micro || {};
    if (mi.trechos) {
      var faltam = refazer ? mi.trechos : Math.max(0, mi.trechos - (mi.feitos || 0));
      var s = faltam * (mi.bruto ? (seg.bruto || 0) : (seg.montado || 0));
      conta.trechos += faltam;
      conta.segBruto += s;
      conta.segMontado += s;
      return;
    }
    var minutos = (m.duracao_s || 0) / 60;
    if (!minutos) { conta.semConta += 1; return; }
    conta.estimadas += 1;
    // ⭐ A procura dos cortes entra na conta: ela roda no NOTEBOOK, antes de qualquer nota,
    //   e é o que o editor vê acontecer primeiro.
    var deteccao = minutos * (precoDaMicro.deteccao_s_por_minuto || 0);
    conta.segBruto += deteccao + minutos * (porMin.bruto || 0) * (seg.bruto || 0);
    conta.segMontado += deteccao + minutos * (porMin.montado || 0) * (seg.montado || 0);
  });
  return conta;
}

function pintarPrecoDaMicro(alvos) {
  var onde = document.getElementById("precoMicro");
  if (!precoDaMicro) { onde.hidden = true; return; }
  onde.hidden = false;
  // ⚠️ Sem o Mac o botão fica desabilitado, e um botão cinza sem explicação na tela é um
  //   defeito aparente. O `title` não serve: ninguém passa o mouse num painel que já está
  //   dizendo o que fazer.
  if (precoDaMicro.motor !== "mac") {
    onde.textContent = "🖥 A decupagem em trechos roda no Mac mini — configure o endereço " +
      "dele para este botão funcionar.";
    return;
  }
  if (!alvos.length) { onde.hidden = true; return; }
  var c = contaDaMicro(alvos);
  var partes = ["🖥 " + alvos.length + " mídia(s) em trechos no Mac (" +
                (precoDaMicro.modelo || "") + ")"];
  if (!c.estimadas) {
    partes.push(c.trechos + " trecho(s) ≈ " + emHoras(c.segBruto));
  } else {
    partes.push("≈ " + emHoras(c.segBruto) + " a " + emHoras(c.segMontado));
    partes.push("estimativa: " + c.estimadas + " ainda sem cortes procurados, e material " +
                "bruto ou montado muda a conta em 6×");
  }
  if (c.semConta) {
    partes.push(c.semConta + " sem duração medida, fora da conta");
  }
  // ⛔⛔ DITO aqui porque o seletor de densidade fica na mesma faixa dos botões: o editor
  //   leu "olhar 6 quadros" como a capilaridade DESTE botão e disparou 4 h de fila
  //   achando que era outra coisa (2026-09-23). A micro escolhe sozinha.
  partes.push("3 a 8 quadros por trecho, pelo movimento");
  partes.push("sem gastar a assinatura");
  partes.push("deixe este computador acordado");
  onde.textContent = partes.join(" · ");
}



document.getElementById("refazerTudo").addEventListener("change", pintarAcoes);
// ⚠️ Trocar o nível repinta o preço na hora: um preço que só muda depois do clique não é
//   preço antes do clique.
document.getElementById("densidade").addEventListener("change", pintarAcoes);

document.getElementById("transcreverFalta").addEventListener("click", function () {
  analisar("transcricao");
});
document.getElementById("vetorizarFalta").addEventListener("click", function () {
  analisar("vetores");
});
document.getElementById("microFalta").addEventListener("click", function () {
  analisar("micro");
});

document.getElementById("decuparFalta").addEventListener("click", function () {
  analisar("decupagem");
});

document.getElementById("pararTarefa").addEventListener("click", function () {
  fetch("/vetores/parar", { method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: "{}" })
    .then(function () { acompanharTarefa(); })
    .catch(function () { /* se não deu para pedir, o andamento conta o que houve */ });
});

/* ⭐ Apontar uma pasta é o MESMO gesto do arrasto: quem autoriza é o editor, na janela do
 * sistema (Windows ou Finder). A página nunca manda um caminho que ela mesma escolheu. */
document.getElementById("apontarPasta").addEventListener("click", function () {
  var botao = document.getElementById("apontarPasta");
  botao.disabled = true;
  vetRecado.hidden = false;
  vetRecado.className = "config-recado";
  vetRecado.textContent = "escolha a pasta na janela que abriu…";
  fetch("/vetores/pasta", { method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: "{}" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      botao.disabled = false;
      vetRecado.hidden = true;
      if (d.cancelado) { return; }
      if (!d.ok) {
        // ⚠️ Calar aqui era o clique que "não faz nada": o serviço explicava, a tela sumia.
        vetRecado.hidden = false;
        vetRecado.className = "config-recado ruim";
        vetRecado.textContent = d.erro || "Não consegui abrir o seletor de pastas.";
        return;
      }
      pintarPastas(d.pastas, null);
      document.getElementById("pastaDeMidia").value = d.caminho;
    })
    .catch(function () {
      botao.disabled = false;
      vetRecado.className = "config-recado ruim";
      vetRecado.textContent = "Não consegui abrir o seletor de pastas.";
    });
});


/* ── as configurações ────────────────────────────────────────────────────── */

var cacheCaminho = document.getElementById("cacheCaminho");
var cacheNota = document.getElementById("cacheNota");
var configRecado = document.getElementById("configRecado");

function tamanhoLegivel(bytes) {
  if (!bytes) { return "vazio"; }
  var unidades = ["B", "KB", "MB", "GB", "TB"];
  var i = 0;
  while (bytes >= 1024 && i < unidades.length - 1) { bytes /= 1024; i += 1; }
  return (i === 0 ? bytes : bytes.toFixed(bytes < 10 ? 1 : 0)) + " " + unidades[i];
}

function recado(texto, erro) {
  configRecado.hidden = !texto;
  configRecado.textContent = texto || "";
  configRecado.className = "config-recado" + (erro ? " ruim" : "");
}

function pintarCache(dados) {
  var c = (dados && dados.cache) || {};
  cacheCaminho.value = c.caminho || "";
  // ⚠️ "mídia", não "take": a pasta é endereçada pelo master, e um take é um recorte
  //    dele. Dizer "23 takes" numa pasta de 23 masters faz o editor procurar na bin um
  //    número que não vai bater.
  var quantos = c.midias === 1 ? "1 mídia analisada" :
                (c.midias || 0) + " mídias analisadas";
  cacheNota.textContent = quantos + ", " + tamanhoLegivel(c.bytes || 0) +
    (c.existe ? "" : " — a pasta ainda não foi criada");

  if (dados && dados.cache_travado_pelo_ambiente) {
    // ⭐ O editor precisa saber quando a escolha dele NÃO vai valer. Um campo que aceita
    //   o valor e o ignora é pior que um campo desabilitado com o motivo escrito.
    cacheCaminho.disabled = true;
    document.getElementById("salvarCache").disabled = true;
    cacheNota.textContent += " · a pasta está fixada pela variável CICLOASSIST_CACHE";
  }
  if (dados && dados.logs) {
    document.getElementById("caminhoDosLogs").textContent = dados.logs;
  }
}

function carregarConfiguracoes() {
  recado("");
  fetch("/configuracoes", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(pintarCache)
    .catch(function () { recado("Não consegui falar com o serviço.", true); });
}

/* ⭐ O seletor de pastas é do WINDOWS, aberto pelo serviço — o navegador não entrega o
 * caminho absoluto de uma pasta escolhida, por segurança, e um caminho pela metade não
 * serve para guardar mídia. Enquanto a janela está aberta, o botão diz isso. */
document.getElementById("escolherPasta").addEventListener("click", function () {
  var botao = document.getElementById("escolherPasta");
  botao.disabled = true;
  recado("escolha a pasta na janela que abriu…");
  fetch("/escolher-pasta", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}"
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      botao.disabled = false;
      if (d.cancelado) { recado(""); return; }
      if (!d.ok) { recado(d.erro || "Não consegui abrir o seletor.", true); return; }
      cacheCaminho.value = d.caminho;
      // ⚠️ Escolher NÃO salva: o editor ainda pode desistir, e um caminho que muda no
      //    disco sem ele confirmar é uma pasta trocada por engano.
      recado("Pasta escolhida. Clique em “Salvar pasta” para valer.");
      // ⭐ E dizer JÁ o que há lá: é a diferença entre reconectar com confiança e
      //   descobrir dias depois que estava apontando para uma pasta vazia.
      olharAPasta(d.caminho, "Clique em “Salvar pasta” para valer.");
    })
    .catch(function () {
      botao.disabled = false;
      recado("Não consegui falar com o serviço.", true);
    });
});

function abrirPasta(qual) {
  fetch("/abrir-pasta", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qual: qual })
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) { recado(d.erro || "Não consegui abrir a pasta.", true); }
    })
    .catch(function () { recado("Não consegui falar com o serviço.", true); });
}

document.getElementById("abrirCache").addEventListener("click", function () {
  abrirPasta("cache");
});
document.getElementById("abrirLogs").addEventListener("click", function () {
  abrirPasta("logs");
});

/* ⭐⭐ RECONECTAR: olhar a pasta ANTES de salvar.
 *
 * O editor move o cache para outro disco e quer reapontar em vez de reprocessar. Como tudo
 * é endereçado por UMID, reconectar é literalmente "aponte para lá" — mas apontar às cegas
 * é o que dá errado: a pasta pode estar vazia, ou ser a errada, e o produto passaria
 * semanas reprocessando sem nunca dizer por quê.
 *
 * ⇒ Aqui o painel conta o que há lá, com o caminho ainda por confirmar. */
function olharAPasta(caminho, depois) {
  if (!caminho) { return; }
  fetch("/cache/olhar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ caminho: caminho })
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) { recado(d.erro || "Não consegui olhar essa pasta.", true); return; }
      recado(fraseDaPasta(d) + (depois ? " " + depois : ""));
    })
    .catch(function () { /* olhar é cortesia; o salvar continua funcionando sem ela */ });
}

function fraseDaPasta(d) {
  if (!d.existe) {
    return "A pasta ainda não existe — ela será criada, e tudo será processado do zero.";
  }
  if (d.atual) { return "É a pasta que já está em uso."; }
  if (d.midias) {
    // ⭐ O caso que o reconectar existe para resolver: o material está lá, e reapontar
    //   devolve TODO o trabalho já feito.
    var frase = "Achei " + d.midias + (d.midias === 1 ? " mídia já analisada" :
                " mídias já analisadas") + " (" + tamanhoLegivel(d.bytes) +
                ") — reapontar recupera esse trabalho, sem reprocessar nada.";
    if (d.estranhas) {
      frase += " ⚠️ Há também " + d.estranhas + " pasta(s) que não são nossas; elas ficam " +
               "intactas.";
    }
    return frase;
  }
  if (d.estranhas) {
    // ⚠️ Apontar para "Documentos" é o erro fácil, e ele não falha na hora: falha em
    //    silêncio, reprocessando tudo e enchendo a pasta de quem não pediu.
    return "Essa pasta tem conteúdo que não é do Ciclo Assist e nenhuma mídia analisada. " +
           "Confira se é mesmo a pasta do cache.";
  }
  return "Pasta vazia: nada se perde, mas tudo será processado de novo aqui.";
}

/* Olhar quando o editor termina de escrever ou colar um caminho. */
cacheCaminho.addEventListener("change", function () {
  olharAPasta(cacheCaminho.value.trim(), "Clique em “Salvar pasta” para valer.");
});

document.getElementById("salvarCache").addEventListener("click", function () {
  recado("salvando…");
  fetch("/configuracoes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cache: cacheCaminho.value.trim() })
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) { recado(d.erro || "Não deu para salvar.", true); return; }
      pintarCache(d);
      // ⚠️ Dizer o que NÃO aconteceu: o que já foi processado continua na pasta antiga.
      //    Mover gigabytes por baixo de um clique é mais arriscado que reprocessar — o
      //    cache é reconstruível por desenho.
      var c = (d && d.cache) || {};
      if (c.midias) {
        // ⭐ Reconectou: o trabalho estava lá e voltou inteiro.
        recado("Pasta salva — e ela já tinha " + c.midias + " mídia(s) analisada(s) (" +
               tamanhoLegivel(c.bytes) + "). Nada será reprocessado.");
      } else {
        // ⚠️ Dizer o que NÃO aconteceu: o que já foi processado continua na pasta antiga.
        //    Mover gigabytes por baixo de um clique é mais arriscado que reprocessar — o
        //    cache é reconstruível por desenho.
        recado("Pasta salva. O que já estava processado fica onde estava e será refeito " +
               "aqui quando precisar.");
      }
    })
    .catch(function () { recado("Não consegui falar com o serviço.", true); });
});

/* ⛔ Apagar é destrutivo, então pergunta — e pergunta NO BOTÃO.
 *
 * ⚠️ Nada de `confirm()`: um diálogo nativo dentro do painel do Media Composer trava a
 * página até alguém responder, e o editor pode nem estar olhando para cá. */
var apagar = document.getElementById("apagarCache");
var armado = false;
var voltaAoNormal = null;

function desarmar() {
  armado = false;
  apagar.textContent = "Apagar tudo";
  apagar.classList.remove("armado");
  if (voltaAoNormal) { clearTimeout(voltaAoNormal); voltaAoNormal = null; }
}

apagar.addEventListener("click", function () {
  if (!armado) {
    armado = true;
    apagar.textContent = "Apagar mesmo?";
    apagar.classList.add("armado");
    // Some sozinho: um botão que fica armado é uma armadilha esperando um clique
    // distraído daqui a dez minutos.
    voltaAoNormal = setTimeout(desarmar, 6000);
    return;
  }
  desarmar();
  recado("apagando…");
  fetch("/cache/apagar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) { recado(d.erro || "Não deu para apagar.", true); return; }
      pintarCache(d);
      var a = d.apagado || {};
      recado("Apagado: " + (a.takes || 0) + " take(s), " +
             tamanhoLegivel(a.bytes || 0) + ". Tudo se refaz quando for preciso.");
    })
    .catch(function () { recado("Não consegui falar com o serviço.", true); });
});

/* ── o modelo e o automático ─────────────────────────────────────────────── */

var escolhaDoModelo = document.getElementById("escolhaDoModelo");
var botaoAuto = document.getElementById("botaoAuto");

function montarBarraDeStatus(d) {
  var modelos = (d && d.modelos) || [];
  escolhaDoModelo.textContent = "";
  // ⭐ A primeira opção é "o padrão da conta": quem nunca abriu esta lista não deve ter
  //   um modelo escolhido por nós às costas dele.
  var padrao = document.createElement("option");
  padrao.value = "";
  padrao.textContent = "modelo padrão";
  escolhaDoModelo.appendChild(padrao);
  modelos.forEach(function (m) {
    var o = document.createElement("option");
    o.value = m.id;
    o.textContent = m.nome;
    o.title = m.para;     // o "para que serve" fica no hover; o nome cabe na barra
    escolhaDoModelo.appendChild(o);
  });
  escolhaDoModelo.value = (d && d.modelo) || "";
  pintarMotor();
  pintarAuto(!!(d && d.auto));
}

function pintarAuto(ligado) {
  botaoAuto.classList.toggle("ligado", ligado);
  botaoAuto.setAttribute("aria-pressed", ligado ? "true" : "false");
}

escolhaDoModelo.addEventListener("change", function () {
  pintarMotor();
  pintarMedidor("medidorCtx", null);
  fetch("/configuracoes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ modelo: escolhaDoModelo.value })
  }).catch(function () { /* a barra volta ao certo no próximo carregamento */ });
});

/* ⛔ Ligar o automático dispensa a confirmação de TODA escrita — e por isso o botão diz
 * na conversa o que acabou de mudar, em vez de só mudar de cor. O editor tem de poder
 * reler depois o que ele mesmo autorizou. */
botaoAuto.addEventListener("click", function () {
  var ligando = !botaoAuto.classList.contains("ligado");
  pintarAuto(ligando);
  fetch("/configuracoes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto: ligando })
  })
    .then(function (r) { return r.json(); })
    .then(function () {
      var b = bloco("modo", "de-sistema");
      b.texto.textContent = ligando
        ? "Automático LIGADO: as ações passam a acontecer sem pedir confirmação. "
          + "Tudo o que for feito continua aparecendo aqui."
        : "Automático desligado: volto a pedir confirmação antes de escrever no projeto.";
    })
    .catch(function () { pintarAuto(!ligando); });
});

/* A ação que aconteceu sem perguntar. "Sem perguntar" não é "sem contar".
 *
 * ⭐ Em sequência, elas se JUNTAM num grupo que mostra só a ÚLTIMA (autor, 2026-11-01):
 * num fluxo de dez operações eram dez linhas, uma parede que empurrava o chat para fora
 * da tela. A seta à esquerda abre o histórico do grupo; nada some, só se recolhe. O
 * grupo é o da PONTA da conversa: um texto do modelo no meio começa um grupo novo. */
function mostrarAutomatico(dado) {
  var grupo = conversa.lastElementChild;
  if (!grupo || !grupo.classList.contains("automaticos")) {
    grupo = document.createElement("div");
    grupo.className = "automaticos";
    var seta = document.createElement("button");
    seta.type = "button";
    seta.className = "aut-seta";
    seta.setAttribute("aria-expanded", "false");
    seta.title = "ver as ações anteriores";
    seta.addEventListener("click", function () {
      var aberto = grupo.classList.toggle("aberto");
      seta.setAttribute("aria-expanded", aberto ? "true" : "false");
      seta.title = aberto ? "recolher" : "ver as ações anteriores";
    });
    grupo.appendChild(seta);
    var lista = document.createElement("div");
    lista.className = "aut-lista";
    grupo.appendChild(lista);
    conversa.appendChild(grupo);
  }
  var linha = document.createElement("div");
  linha.className = "automatico";
  var marca = document.createElement("b");
  marca.textContent = "automático";
  linha.appendChild(marca);
  var texto = document.createElement("span");
  texto.textContent = dado.ferramenta + " — sem perguntar, porque você pediu assim";
  linha.appendChild(texto);
  var alvo = grupo.querySelector(".aut-lista");
  alvo.appendChild(linha);
  var n = alvo.children.length;
  var botao = grupo.querySelector(".aut-seta");
  botao.textContent = n > 1 ? String(n - 1) : "";
  grupo.classList.toggle("varias", n > 1);
  rolarParaOFim();
}

fetch("/configuracoes", { cache: "no-store" })
  .then(function (r) { return r.json(); })
  .then(montarBarraDeStatus)
  .catch(function () { /* serviço velho: o aviso grave já explicou */ });

/* ── arrastar para dentro do chat ────────────────────────────────────────────
 *
 * ⭐⭐ O editor arrasta em vez de digitar: a sequência que quer mexer, o take que quer
 * comparar, o roteiro da cena que está no Explorer, uma foto de referência.
 *
 * ⚠️⚠️ **Quatro armadilhas MEDIDAS** (banco: `plugins/avid-panel-sdk/arrastar.md`), e
 * cada uma falha de um jeito que não aponta para si mesma:
 *
 * 1. `effectAllowed` do MC é **"move"** — forçar `dropEffect = "copy"` CANCELA o drop em
 *    silêncio: o realce acende e soltar não faz nada.
 * 2. Ouvir na fase de BOLHA não basta: `<textarea>` tem tratamento próprio de drop e
 *    consome o evento. Registrar na **captura**.
 * 3. `preventDefault` no `dragover` tem de ser **incondicional**: sem ele, soltar um
 *    ARQUIVO faz a webview NAVEGAR para o arquivo — e a interface do painel desaparece.
 * 4. A resposta precisa aparecer onde o editor olha, senão "não aconteceu nada" e "a
 *    resposta saiu fora da vista" são indistinguíveis para quem está usando. */

var MIME_DO_AVID = "text/x.avid.mc-api-asset-list+json";
var anexos = document.getElementById("anexos");

//: A lista de anexos começa aberta e o editor pode dobrar. ⚠️ Guardado fora do DOM para
//: sobreviver ao repintar — a lista é redesenhada a cada arrasto.
var anexosDobrados = false;

function parteDaConta(origem, texto) {
  var s = document.createElement("span");
  s.className = "anexos-conta-" + origem;
  s.textContent = texto;
  return s;
}

function pintarBarraDeAnexos() {
  var barra = document.getElementById("anexosBarra");
  barra.hidden = !referencias.length;
  if (!referencias.length) { return; }

  var arquivos = referencias.filter(function (r) { return r.tipo === "arquivo"; }).length;
  var avid = referencias.length - arquivos;
  // ⭐ A contagem herda as cores dos chips, e assim a legenda existe sem ocupar espaço:
  //   quem vê "2 do Avid · 1 arquivo" em duas cores já sabe qual chip é qual.
  var conta = document.getElementById("anexosConta");
  conta.textContent = "";
  if (avid) { conta.appendChild(parteDaConta("avid", avid + " do " + NOME_DO_NLE)); }
  if (avid && arquivos) { conta.appendChild(document.createTextNode(" · ")); }
  if (arquivos) {
    conta.appendChild(parteDaConta(
      "externo", arquivos + (arquivos === 1 ? " arquivo" : " arquivos")));
  }
  document.getElementById("dobrarAnexos")
    .setAttribute("aria-expanded", anexosDobrados ? "false" : "true");
  // ⭐ Troca o GLIFO, como o toggle das ferramentas já faz: girar um triângulo pequeno
  //   por CSS o deixa parecendo um marcador de lista, e ninguém clica num bullet.
  document.getElementById("setaDosAnexos").textContent = anexosDobrados ? "▸" : "▾";
}

function pintarAnexos() {
  anexos.textContent = "";
  pintarBarraDeAnexos();
  anexos.hidden = !referencias.length || anexosDobrados;
  referencias.forEach(function (r, i) {
    var chip = document.createElement("span");
    chip.className = "anexo" + (r.problema ? " ruim" : "");
    // ⭐ De DENTRO do Media Composer ou de FORA dele — o CSS pinta por este atributo.
    //   ⚠️ É só cor: quem diz O QUE é continua sendo o rótulo em `<b>`, porque cor
    //   sozinha não informa quem não a distingue.
    chip.dataset.origem = r.tipo === "arquivo" ? "externo" : "avid";

    var marca = document.createElement("b");
    marca.textContent = r.tipo === "arquivo" ? (r.papel || "arquivo") : (r.especie || NLE);
    chip.appendChild(marca);

    var nome = document.createElement("span");
    nome.className = "nome";
    nome.textContent = r.rotulo;
    chip.appendChild(nome);

    if (r.problema) {
      var aviso = document.createElement("i");
      aviso.textContent = r.problema;
      chip.appendChild(aviso);
    }

    var tirar = document.createElement("button");
    tirar.type = "button";
    tirar.className = "tirar";
    tirar.textContent = "×";
    tirar.setAttribute("aria-label", "tirar " + r.rotulo);
    tirar.addEventListener("click", function () {
      referencias.splice(i, 1);
      pintarAnexos();
    });
    chip.appendChild(tirar);
    anexos.appendChild(chip);
  });
}

document.getElementById("dobrarAnexos").addEventListener("click", function () {
  anexosDobrados = !anexosDobrados;
  pintarAnexos();
});

document.getElementById("limparAnexos").addEventListener("click", function () {
  referencias = [];
  pintarAnexos();
  entrada.focus();
});

/* ⚠️ O Chromium NÃO entrega o caminho absoluto pelo objeto File — mas o `text/uri-list`
 * do arrasto traz `file:///C:/…` (Explorer) ou `file:///Users/…` (Finder), e é de lá
 * que o caminho sai. */
function caminhoDaUri(uri) {
  // ⛔ Tirar só `file://` (e um `localhost`): a TERCEIRA barra é a raiz do caminho. Comer
  //    as três dava `Users/x` no Mac — relativo, "não encontrei" para todo arrasto do Finder.
  var p = decodeURIComponent(uri.replace(/^file:\/\/(localhost(?=\/))?/i, ""));
  if (/^\/[A-Za-z]:/.test(p)) { return p.slice(1).replace(/\//g, "\\"); }   // /C:/x → C:\x
  if (p.charAt(0) !== "/") { return "\\\\" + p.replace(/\//g, "\\"); }       // host/x → \\host\x
  return p;                                                                  // /Users/x
}

function caminhosDoArrasto(dt) {
  var bruto = "";
  try { bruto = dt.getData("text/uri-list") || ""; } catch (e) { bruto = ""; }
  return bruto.split("\n")
    .map(function (l) { return l.trim(); })
    .filter(function (l) { return l && l.indexOf("#") !== 0 && l.indexOf("file:") === 0; })
    .map(caminhoDaUri);
}

/* ⛔⛔ O arrasto de FORA no Premiere não traz caminho nenhum (medido em 2026-09-17, CEP
 * 23.2): sem `text/uri-list` e sem `File.path` (que exigiria Node, e este painel não liga
 * Node de propósito). O que dá para mandar é o CONTEÚDO — e é o que o produto precisa:
 * roteiro para ler, imagem para olhar. A cópia nasce na pasta de dados e é ela que fica
 * autorizada (ADR 0005: o gesto autoriza um arquivo, não a pasta).
 *
 * ⚠️ Teto de 25 MB, igual ao do serviço: arrastar um `.mxf` para o chat é engano, e o chip
 * tem de dizer isso na hora. */
var TETO_DO_ANEXO = 25 * 1024 * 1024;

function mandarConteudo(arquivos) {
  arquivos.slice(0, 5).forEach(function (f) {
    if (f.size > TETO_DO_ANEXO) {
      referencias.push({ tipo: "arquivo", caminho: "", rotulo: f.name,
                         problema: "grande demais para anexar" });
      pintarAnexos();
      return;
    }
    var leitor = new FileReader();
    leitor.onload = function () {
      fetch("/arrastados/conteudo", {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream",
                   "X-Ciclo-Nome": encodeURIComponent(f.name) },
        body: leitor.result
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var a = d.arquivo || {};
          referencias.push({ tipo: "arquivo", caminho: a.caminho || "",
                             rotulo: a.nome || f.name, papel: a.papel || "",
                             problema: d.ok ? "" : (d.erro || "não consegui anexar") });
          pintarAnexos();
          entrada.focus();
        })
        .catch(function () {
          var b = bloco("problema", "de-erro");
          b.texto.textContent = "Não consegui anexar " + f.name + ".";
        });
    };
    leitor.onerror = function () {
      var b = bloco("problema", "de-erro");
      b.texto.textContent = "Não consegui ler " + f.name + " para anexar.";
    };
    leitor.readAsArrayBuffer(f);
  });
}

function registrarArrasto(caminhos, mobs) {
  if (!caminhos.length && !mobs.length) { return; }
  fetch("/arrastados", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ caminhos: caminhos, mobs: mobs })
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      (d.arquivos || []).forEach(function (a) {
        // ⭐ O problema aparece AGORA, no chip, e não depois de um turno gasto: o editor
        //   ainda lembra por que arrastou aquilo.
        //   ⭐ E o que uma ferramenta USA não é problema: o `.prproj`, o `.mov` e a pasta das
        //   mídias levavam "não sei ler este formato"/"é uma pasta" — e eram o material do
        //   conform. Com `papel`, o chip diz o que aquilo É (projeto · referência · mídias).
        var problema = "";
        if (!a.existe) { problema = "não encontrei"; }
        else if (a.papel) { problema = ""; }
        else if (a.pasta) { problema = "é uma pasta"; }
        else if (!a.legivel && !a.visivel) { problema = "não sei ler este formato"; }
        referencias.push({ tipo: "arquivo", caminho: a.caminho, rotulo: a.nome,
                           papel: a.papel || "", problema: problema, pasta: !!a.pasta });
      });
      (d.mobs || []).forEach(function (m) {
        referencias.push({ tipo: "avid", mob_id: m.mob_id, especie: m.especie,
                           nome: m.nome, rotulo: m.nome || m.especie });
      });
      pintarAnexos();
      entrada.focus();
    })
    .catch(function () {
      var b = bloco("problema", "de-erro");
      b.texto.textContent = "Não consegui registrar o que você arrastou.";
    });
}

function tipos(dt) {
  var lista = [];
  try {
    for (var i = 0; dt && dt.types && i < dt.types.length; i++) { lista.push(String(dt.types[i])); }
  } catch (e) { /* sem tipos */ }
  return lista;
}

function apagarRealce() {
  document.body.classList.remove("recebendo");
  document.body.classList.remove("de-fora");
}

function aoSoltar(e) {
  var dt = e.dataTransfer;
  if (!dt) { return; }

  var mobs = [];
  if (Array.prototype.indexOf.call(dt.types || [], MIME_DO_AVID) >= 0) {
    try {
      var itens = JSON.parse(dt.getData(MIME_DO_AVID) || "[]");
      mobs = (itens || []).filter(function (i) { return i && i.id; });
    } catch (erro) { mobs = []; }
  }
  // ⛔⛔ Quando o arrasto vem do MEDIA COMPOSER, o `text/uri-list` que vem junto é LIXO:
  //    um `.aaf` no Temp que **nunca chega a existir**. O banco mediu — `File.size == 0`,
  //    e uma vigia nativa não o achou em 40 amostras (`plugins/avid-panel-sdk/
  //    arrastar.md`). Em campo ele apareceu como um chip laranja
  //    "FDE8B3B7-….aaf não encontrei" que o editor não tinha arrastado e não entendia.
  var caminhos = mobs.length ? [] : caminhosDoArrasto(dt);
  // ⭐⭐ Com o formulário de um fluxo ABERTO, o arquivo é dele, não do chat (autor, 2026-11-01): cada
  //    área recebe o que é dela (`fluxo.js`, `cicloFormulario`). Sem isto o arrasto virava anexo da
  //    conversa enquanto o editor tentava preencher o formulário.
  if (caminhos.length && window.cicloFormulario && window.cicloFormulario.aberto()) {
    if (e.preventDefault) { e.preventDefault(); }
    apagarRealce();
    window.cicloFormulario.receber(caminhos, e.clientX, e.clientY);
    return;
  }
  var soltos = [];
  // ⛔ Só no CEP. No Media Composer o `text/uri-list` funciona, e o arrasto de uma BIN traz
  //    junto um `.aaf` FALSO que nunca chega a existir (banco, avid-panel-sdk/arrastar.md):
  //    mandá-lo "pelo conteúdo" trocaria a mensagem certa ("bins inteiras não podem ser
  //    arrastadas") por um chip de arquivo vazio.
  if (CEP && !mobs.length && !caminhos.length && dt.files && dt.files.length) {
    soltos = Array.prototype.slice.call(dt.files);
    // Se o ambiente der o caminho (QtWebEngine, ou CEP com Node), ele vale mais: o
    // arquivo fica onde está, sem cópia.
    caminhos = soltos.map(function (f) { return f.path || ""; }).filter(function (c) { return c; });
    if (caminhos.length) { soltos = []; }
  }
  if (soltos.length) {
    e.preventDefault();
    apagarRealce();
    mandarConteudo(soltos);
    return;
  }
  if (CEP && !mobs.length && !caminhos.length && !(dt.types || []).length) {
    // ⭐⭐ Da BIN do Premiere não vem dado nenhum — `types` vazio, `copyMove` (banco,
    //   `plugins/premiere-cep/arrastar-e-selecao.md` §6b). Mas o clique que começa o
    //   arrasto SELECIONA o item: o gesto vem do arrasto, o dado vem da seleção. É a saída
    //   que o Sincronizar validou no 23.2.
    e.preventDefault();
    apagarRealce();
    soltouDoPremiere();
    return;
  }
  if (!mobs.length && !caminhos.length) {
    // ⚠️ Arrastar uma BIN do Avid não entrega dado nenhum — medido, `types` vem vazio.
    //    Dizer isso é melhor que o editor concluir que o painel está quebrado.
    var b = bloco("problema", "de-erro");
    // ⚠️ A frase é do editor em que o painel está: falar do Avid dentro do Premiere manda
    //   o editor procurar um problema que não é o dele (aconteceu em 2026-09-17).
    b.texto.textContent = CEP
      ? ("Não veio nada nesse arrasto (tipos: " + (tipos(dt).join(", ") || "nenhum") +
         "). Selecione na bin do Premiere o que quer mandar e arraste de novo; arquivos do " +
         "Explorer ou do Finder também funcionam.")
      : ("Não veio nada nesse arrasto. Bins inteiras do Avid não podem ser arrastadas — " +
         "abra a bin e arraste os clipes ou a sequência. Arquivos do Explorer ou do Finder funcionam.");
    // ⚠️ Sem isto o "solte aqui" ficava ACESO depois de um arrasto que não entregou nada
    //   — a tela dizia "ainda estou esperando" em cima de uma mensagem de erro.
    apagarRealce();
    return;
  }
  e.preventDefault();
  apagarRealce();
  registrarArrasto(caminhos, mobs);
}

/* O efeito de arrasto que a ORIGEM permite, preferindo "move" (o do Media Composer).
 *
 * ⚠️ O banco manda "escolha um efeito compatível" (`plugins/avid-panel-sdk/arrastar.md`),
 * e o literal `"move"` ignorava isso: numa origem que só permita copiar, ele CANCELA o
 * drop em silêncio. Dá "move" onde o original dava — o MC e o "all" —, e só difere onde
 * "move" cancelaria. */
function efeitoCompativel(dt) {
  var p = String((dt && dt.effectAllowed) || "all").toLowerCase();
  if (p === "none") { return null; }
  if (p === "all" || p === "uninitialized" || p.indexOf("move") !== -1) { return "move"; }
  if (p.indexOf("copy") !== -1) { return "copy"; }
  if (p.indexOf("link") !== -1) { return "link"; }
  return null;
}

/* ⛔⛔ Um arrasto que NASCEU aqui dentro não é um anexo (2026-09-21, visto pelo editor no
 * Media Composer). Arrastando um resultado da aba Busca, o painel acendia "solte aqui" no
 * rodapé — prometendo receber o que ele mesmo tinha acabado de mostrar. A miniatura é um
 * `<img>`, e `<img>` é arrastável por padrão: o arrasto carrega `Files`, que é exatamente
 * o que o realce procura.
 *
 * ⚠️ Duas travas, e as duas fazem falta: as imagens deixam de ser arrastáveis (`draggable`
 * abaixo), e QUALQUER arrasto iniciado dentro da página fica marcado — a segunda pega o
 * texto selecionado, o link, e o que vier depois. */
var arrastandoDeDentro = false;
document.addEventListener("dragstart", function () { arrastandoDeDentro = true; }, true);
document.addEventListener("dragend", function () { arrastandoDeDentro = false; }, true);
document.addEventListener("drop", function () { arrastandoDeDentro = false; }, true);

document.addEventListener("dragover", function (e) {
  // ⛔ INCONDICIONAL: sem isto, soltar um arquivo navega a webview para ele e o painel
  //    some. O filtro de MIME decide o REALCE, nunca o controle do navegador.
  e.preventDefault();
  if (arrastandoDeDentro) { return; }
  var tipos = (e.dataTransfer && e.dataTransfer.types) || [];
  // ⭐ No Premiere, "sem tipo nenhum" É o arrasto da bin — o do Explorer traz `Files`.
  var doAvid = Array.prototype.indexOf.call(tipos, MIME_DO_AVID) >= 0 ||
               (CEP !== null && tipos.length === 0);
  var nosso = doAvid || Array.prototype.indexOf.call(tipos, "Files") >= 0;
  if (nosso) {
    document.body.classList.add("recebendo");
    // ⚠️ A MESMA precedência do `aoSoltar`: havendo MIME do Avid é do Avid, porque o
    //   `text/uri-list` que o MC manda junto é lixo. Se divergissem, o realce prometeria
    //   uma origem e o chip entregaria outra.
    document.body.classList.toggle("de-fora", !doAvid);
    // ⛔ "move" porque é com ele que o MC arrasta. Forçar "copy" cancela o drop e o
    //    sintoma é o pior possível: o realce acende e soltar não faz nada.
    var efeito = efeitoCompativel(e.dataTransfer);
    if (efeito) {
      try { e.dataTransfer.dropEffect = efeito; } catch (erro) { /* nem todo alvo deixa */ }
    }
  }
}, true);

document.addEventListener("dragleave", function (e) {
  if (!e.relatedTarget) { apagarRealce(); }
}, true);

// ⛔ Fase de CAPTURA: o <textarea> consome o drop antes da bolha chegar ao documento.
document.addEventListener("drop", aoSoltar, true);

/* ── Na JANELA do app (`?casca=app`, 2026-10-21): o arrasto vem do alvo NATIVO ──────────────
 *
 * ⛔ Medido no De Lá Pra Cá (MC 24.6, Windows, 2026-10-18): numa webview comum, soltar uma
 * timeline do MC fez o AVID começar um EXPORT — o arrasto anuncia também um `.aaf` virtual
 * que só é gerado quando o alvo o pede, e o WebView2 pede ("contains offline media.
 * Continue exporting or abort?", modal que trava até o Explorer). E o arquivo do Explorer
 * chegava SEM caminho. Por isso, na janela, o drop do WebView2 é desligado e quem recebe é
 * o `IDropTarget` do app (`app/src-tauri/src/arrasto_win.rs`): ele lê SÓ o formato do Avid
 * (nunca o arquivo) ou os caminhos do Explorer, e chama `cicloArrasto` com as fases. Aqui
 * isso vira o MESMO `dataTransfer` que o `aoSoltar` sempre leu — a autorização de leitura
 * (ADR 0005) continua nascendo do gesto, pelo mesmo caminho.
 *
 * ⬜ Do Premiere (`premiere`/`premiere_item`) e do Resolve o alvo já reconhece, mas o painel
 * ainda não sabe o que fazer: diz isso em vez de calar. */
var CASCA_APP = /(?:^|[?&])casca=app(?:&|$)/.test(location.search);

/* ⭐⭐ EMBUTIDO no guarda-chuva (`?embutido=1`, autor, 2026-10-21): a moldura é UMA, do guarda-chuva — o estado da
 * conexão e o pino no topo dele, uma engrenagem só à direita das abas Preparar · Assistir · Conformar · Entregar, e
 * o rodapé com a assinatura embaixo. Aqui somem a marca, a versão, o pino e a engrenagem (o CSS, `.embutido`), e a
 * engrenagem de lá chama `cicloEmbutido.configuracoes()`, que vai e volta da tela de configurações.
 * O MESMO contrato no Sincronizar e no De Lá Pra Cá: cada app se esconde do mesmo jeito. */
var EMBUTIDO = /(?:^|[?&])embutido=1(?:&|$)/.test(location.search);
if (EMBUTIDO) { document.documentElement.classList.add("embutido"); }
/* ⭐ `?ajustes=1`: a seção Assistir da janela de configurações do app (autor, 2026-11-07: a engrenagem abre uma janela
 * própria, com uma seção por módulo). Mesma página, só a tela de configurações, sem abas e sem caixa de texto. */
var SO_AJUSTES = /(?:^|[?&])ajustes=1(?:&|$)/.test(location.search);
if (SO_AJUSTES) { document.documentElement.classList.add("so-ajustes"); }
/* `configuracoes()` alterna; `configuracoes(false)` FECHA — o guarda-chuva chama assim no app que sai de vista, senão
 * o editor voltava à aba e dava com os ajustes no lugar do trabalho (visto pelo autor, 2026-10-21). Fechar volta à
 * subaba de onde ele veio. */
var telaAntesDosAjustes = "conversa";
window.cicloEmbutido = {
  configuracoes: function (abrir) {
    var aberta = telaAVista === "config";
    var querer = abrir === undefined ? !aberta : !!abrir;
    if (querer === aberta) { return; }
    if (querer) { telaAntesDosAjustes = telaAVista || "conversa"; mostrarTela("config"); }
    else { mostrarTela(telaAntesDosAjustes); }
  }
};
/* As subabas do guarda-chuva têm o NOME do que fazem (autor, 2026-10-21: "Assistir · Buscar · Vetores"). */
if (EMBUTIDO) {
  document.querySelector('.aba[data-tela="conversa"]').textContent = "Assistir";
  document.querySelector('.aba[data-tela="busca"]').textContent = "Buscar";
}

function dtDaCasca(n) {
  var dados = {};
  if (n.tipo === "avid") {
    // ⭐ No MAC (`arrasto_mac.rs`, 2026-11-07) o MC só entrega os MobIDs, sem a espécie: vão como itens sem `type`
    //   (o serviço chama de "item" e resolve o nome pela bin, como faz com o que vem do Windows).
    dados[MIME_DO_AVID] = n.dados || ((n.mob_ids || []).length ? JSON.stringify(n.mob_ids.map(function (id) {
      return { id: id, systemID: "mc-api", systemType: "mediacomposer", type: "" };
    })) : "");
  }
  if (n.tipo === "arquivos") {
    dados["text/uri-list"] = (n.caminhos || []).map(function (c) {
      var barras = c.replace(/\\/g, "/");
      if (/^\/\//.test(barras)) {                       // \\servidor\pasta → file://servidor/pasta
        return "file:" + barras.split("/").map(encodeURIComponent).join("/");
      }
      return "file:///" + barras.split("/").map(function (p, i) {
        return i ? encodeURIComponent(p) : p;            // a letra do disco (C:) fica como está
      }).join("/");
    }).join("\r\n");
    dados.Files = "";
  }
  var tipos = Object.keys(dados);
  return {
    types: tipos, files: [], effectAllowed: n.tipo === "avid" ? "move" : "copy",
    getData: function (t) { return n.fase === "soltou" ? (dados[t] || "") : ""; }
  };
}

window.cicloArrasto = function (n) {
  if (!n || n.fase === "saiu") {
    apagarRealce();
    if (window.cicloFormulario) { window.cicloFormulario.sobre(-1, -1); }
    return;
  }
  // ⭐ Do Premiere o arrasto não traz dado (banco, `premiere-cep/arrastar-e-selecao.md` §6b): o
  //   clique que o começa SELECIONA, e a seleção vem pela ponte — o mesmo gesto do painel antigo.
  if ((n.tipo === "premiere" || n.tipo === "premiere_item") && NO_PREMIERE) {
    if (n.fase === "sobre") {
      document.body.classList.add("recebendo");
      document.body.classList.remove("de-fora");
      return;
    }
    if (n.fase === "soltou") { apagarRealce(); soltouDoPremiere(); }
    return;
  }
  if (n.tipo === "bin" || n.tipo === "resolve" || n.tipo === "premiere" || n.tipo === "premiere_item") {
    if (n.fase !== "soltou") { return; }
    apagarRealce();
    var b = bloco("problema", "de-erro");
    b.texto.textContent = n.tipo === "bin"
      ? "A bin do painel lateral não viaja no arrasto — abra a bin e arraste os clipes ou a sequência de dentro dela."
      : n.tipo === "resolve"
        ? "Ainda não sei receber o que vem do Resolve. Arquivos do Explorer e clipes do Media Composer funcionam."
        : "Isso veio do Premiere, e esta janela está falando com o Media Composer — troque para o Premiere no alto.";
    return;
  }
  var dt = dtDaCasca(n);
  // ⭐ Formulário de fluxo aberto: o realce é da ÁREA sob o cursor, e o drop vai para ela (o `x, y`
  //   da casca já vem em pixels da página — `arrasto_win.rs`, `na_pagina`).
  if (n.tipo === "arquivos" && window.cicloFormulario && window.cicloFormulario.aberto()) {
    if (n.fase === "sobre") { apagarRealce(); window.cicloFormulario.sobre(n.x, n.y); return; }
    if (n.fase === "soltou") {
      apagarRealce();
      window.cicloFormulario.sobre(-1, -1);
      window.cicloFormulario.receber(n.caminhos || [], n.x, n.y);
      return;
    }
  }
  if (n.fase === "sobre") {
    if (n.tipo === "nada") { apagarRealce(); return; }
    document.body.classList.add("recebendo");
    document.body.classList.toggle("de-fora", n.tipo !== "avid");
    return;
  }
  if (n.fase === "soltou") {
    aoSoltar({ preventDefault: function () {}, dataTransfer: dt });
  }
};

/* ⭐⭐ De qual NLE a janela fala (2026-10-21). Dentro de um NLE a página sabia; na janela, a `/conexao`
 * diz quem está ligado: o Premiere quando a ponte invisível bateu há pouco, o Media Composer quando o
 * 9100 responde. Um só ligado: é ele. Os dois: o que o editor escolheu no seletor do topo (o Media
 * Composer, se ele nunca escolheu). Nenhum: fica como está, e a sondagem volta a olhar.
 * ⚠️ Trocar recarrega a página com `?nle=` — as palavras, a vigia e a busca são decididas na partida.
 * ⛔ Nunca no meio de uma resposta: a troca espera o turno acabar. */
function escolherONle() {
  if (!CASCA_APP || CEP) { return; }
  var seletor = document.getElementById("qualNle");
  // ⭐ o NLE DE TRABALHO (autor, 2026-11-26): a escolha é UMA para todas as abas, guardada no núcleo (`/nle`)
  Promise.all([fetch("/conexao", { cache: "no-store" }).then(function (r) { return r.json(); }),
               fetch("/nle", { cache: "no-store" }).then(function (r) { return r.json(); })
                 .catch(function () { return {}; })])
    .then(function (rs) {
      var c = rs[0], escolhido = (rs[1] || {}).nle;
      var vivos = ["avid", "premiere"].filter(function (n) { return c && c[n]; });
      if (seletor) {
        // ⚠️ Embutido, só com os DOIS ligados: o topo do guarda-chuva já diz qual está aberto.
        seletor.hidden = vivos.length < 2 && (EMBUTIDO || NLE_PEDIDO === "");
        seletor.value = NLE;
        Array.prototype.forEach.call(seletor.options, function (o) {
          o.textContent = (o.value === "premiere" ? "Premiere" : "Media Composer") +
                          (vivos.indexOf(o.value) < 0 ? " (fechado)" : "");
        });
      }
      var alvo = NLE;
      if (vivos.length === 1) { alvo = vivos[0]; }
      else if (vivos.length === 2) {
        alvo = vivos.indexOf(escolhido) >= 0 ? escolhido : (NLE_PEDIDO || "avid");
      }
      if (alvo !== NLE && !ocupado) { trocarONle(alvo); }
    })
    .catch(function () { /* sem serviço, o ponto do topo já diz */ });
}

function trocarONle(alvo) {
  var q = location.search.replace(/([?&])nle=[^&]*&?/, "$1").replace(/[?&]$/, "");
  location.replace(location.pathname + (q ? q + "&" : "?") + "nle=" + alvo);
}

(function () {
  var seletor = document.getElementById("qualNle");
  // ⭐ Na janela de configurações (`?ajustes=1`), nada de sondar o NLE (autor, 2026-11-07): a tela de ajustes não
  //    depende dele, e o `/conexao` pergunta ao MC — MEDIDO 2,4 s — a cada 15 s, inclusive com a seção escondida, e
  //    podia RECARREGAR a página no meio da leitura dos ajustes.
  if (!CASCA_APP || CEP || !seletor || SO_AJUSTES) { return; }
  seletor.addEventListener("change", function () {
    var alvo = seletor.value;
    // grava a escolha para TODAS as abas (o Conformar e o Preparar seguem); a troca daqui não espera a gravação
    fetch("/nle", { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ nle: alvo }) })
      .catch(function () { /* sem serviço, o ponto do topo já diz */ })
      .then(function () { if (alvo !== NLE) { trocarONle(alvo); } });
  });
  escolherONle();
  setInterval(escolherONle, 15000);
})();

/* O pino: a página não tem ponte com o Tauri (de propósito — ela mostra texto do modelo), então
 * pede ao serviço, que reinvoca o executável do app (`servico/aplicativo.py`). */
(function () {
  var pino = document.getElementById("pino");
  if (!CASCA_APP || !pino) { return; }
  pino.hidden = false;
  pino.addEventListener("click", function () {
    var fixar = pino.getAttribute("aria-pressed") !== "true";
    fetch("/app/fixar", { method: "POST", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ fixar: fixar }) })
      .then(function (r) { return r.json(); })
      .then(function (r) {
        if (r && r.janela) { pino.setAttribute("aria-pressed", fixar ? "true" : "false"); }
      })
      .catch(function () { /* sem serviço, o ponto do topo já diz */ });
  });
})();

/* ⛔⛔ Parar mata o subprocesso do modelo. O botão desarma na hora para não haver dois
 *     pedidos, e o `terminar()` do turno é quem o esconde de vez. */
pararConversa.addEventListener("click", function () {
  pararConversa.disabled = true;
  fetch("/conversar/parar", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ nle: NLE, conversa: qualConversa() }) })
    .catch(function () { /* o turno acaba de qualquer jeito */ })
    .then(function () { pararConversa.disabled = false; });
});

/* ⭐⭐ "Esta conversa já vem de antes."
 *
 * ⛔ MEDIDO em 2026-09-12: ele fechou o Media Composer sem /clear, reabriu, e o painel
 *    voltou em branco enquanto o fio seguia inteiro do outro lado. O teste seguinte rodou
 *    sobre 505 mil tokens de anteontem e leu 10,8× mais contexto que a mesma tarefa numa
 *    conversa limpa. A tela em branco custou isso — é o conserto de custo mais barato que
 *    existe neste painel. */
function mostrarOFio(fio) {
  if (!fio || fio.novo) { return; }
  // ⭐⭐ A conversa é da JANELA (2026-11-01): o fio do Media Composer CONTINUA no Premiere e
  //   vice-versa — o serviço reinicia o processo com `--resume` e o modelo recebe o recado.
  // ⛔ O peso vem do CONTEXTO, não do contador de turnos: um turno cancelado não
  //   incrementa, e o estado pode ter `turnos: 0` apontando para uma conversa enorme.
  var peso = [];
  if (fio.turnos) { peso.push(fio.turnos + (fio.turnos === 1 ? " turno" : " turnos")); }
  if (fio.contexto) { peso.push("~" + Math.round(fio.contexto / 1000) + "k tokens"); }
  if (fio.fracao) { peso.push(Math.round(fio.fracao * 100) + "% da janela"); }
  if (!peso.length) { return; }
  // ⚠️ `textContent` + elementos, e não `innerHTML` — a regra do próprio painel, que este
  //   lugar era o único a furar. Os números vêm do serviço, mas a regra não abre exceção
  //   para dado "que parece seguro" (achado no Assist anterior, 2026-09-19).
  fioAviso.textContent = "Esta conversa continua de antes (";
  peso.forEach(function (parte, i) {
    if (i) { fioAviso.appendChild(document.createTextNode(", ")); }
    var b = document.createElement("b");
    b.textContent = parte;
    fioAviso.appendChild(b);
  });
  fioAviso.appendChild(document.createTextNode("). Tudo isso é reenviado a cada pergunta."));
  var limpar = document.createElement("button");
  limpar.type = "button";
  limpar.textContent = "começar do zero";
  limpar.addEventListener("click", function () { limparAConversa(); });
  fioAviso.appendChild(limpar);
  fioAviso.hidden = false;
}

mostrarTela(SO_AJUSTES ? "config" : "conversa");
// ⛔ Depois de TODOS os scripts: o cartão de um fluxo é desenhado pelo `fluxo.js`, que carrega
//    depois deste arquivo. Chamado aqui direto, o GET às vezes voltava antes dele e o cartão
//    saía em JSON cru (visto no print, 2026-11-01 — na primeira foto saiu certo, na segunda não).
document.addEventListener("DOMContentLoaded", carregarPendencias);


/* ── Premiere: a ponte e o arrasto ──────────────────────────────────────────
 *
 * ⭐⭐ No Premiere o serviço não alcança o projeto: `app.project` só existe aqui dentro.
 * A página segura um long-poll em /premiere/pedido, roda o pedido com `evalScript` e
 * devolve em /premiere/resposta (`nle/premiere/ponte.py`). Medido no 23.2: 2,5–4,9 ms
 * por volta.
 *
 * O ExtendScript (`host.jsx`) vem do SERVIÇO e é avaliado ao abrir: mudar o que se lê do
 * Premiere é Reload no painel, sem reinstalar a extensão. */

function noPremiere(expr) {
  return new Promise(function (ok) {
    try { CEP.evalScript(expr, function (r) { ok(r); }); }
    catch (e) { ok("EvalScript error. " + e); }
  });
}

function carregarOHost() {
  fetch("/premiere/host.jsx", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.text();
    })
    .then(noPremiere)
    .then(function () { atenderAPonte(); })
    .catch(function () { setTimeout(carregarOHost, 3000); });
}

function atenderAPonte() {
  fetch("/premiere/pedido", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.json();
    })
    .then(function (p) {
      if (!p || !p.expr) { return null; }
      return noPremiere(p.expr).then(function (r) {
        return fetch("/premiere/resposta", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: p.id, r: r })
        });
      });
    })
    // ⚠️ O serviço reiniciou (ou caiu): esperar um pouco e **recarregar o host.jsx** antes
    //    de voltar à fila. O ExtendScript fica no Premiere, não no serviço: sem isto, um
    //    serviço novo com funções novas conversaria com o script velho — e o erro sairia
    //    como "EvalScript error" numa ferramenta que existe.
    .then(atenderAPonte, function () { setTimeout(carregarOHost, 2000); });
}

/* A seleção do projeto do Premiere: por `evalScript` dentro do CEP, ou pela PONTE na janela do app
 * (`POST /premiere/selecao`) — a janela não tem `__adobe_cep__`. */
function lerSelecaoDoPremiere() {
  if (CEP) {
    return noPremiere("cicloSelecao()").then(function (texto) {
      try { return JSON.parse(texto).itens || []; } catch (e) { return []; }
    });
  }
  return fetch("/premiere/selecao", { method: "POST", headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify({ nle: NLE }) })
    .then(function (r) { return r.json(); })
    .then(function (d) { return (d && d.itens) || []; })
    .catch(function () { return []; });
}

function soltouDoPremiere() {
  lerSelecaoDoPremiere().then(function (itens) {
    if (!itens.length) {
      var b = bloco("problema", "de-erro");
      b.texto.textContent =
        "Não veio nada nesse arrasto. Selecione os clipes na bin do Premiere e arraste de novo.";
      return;
    }
    itens.forEach(function (i) {
      referencias.push({ tipo: "premiere", id: i.id, nome: i.nome, bin: i.bin,
                         especie: i.especie, arquivo: i.arquivo || "",
                         rotulo: i.nome || i.especie });
    });
    pintarAnexos();
    entrada.focus();
  });
}

if (CEP) { carregarOHost(); }
