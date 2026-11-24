/* A janela da Carta Aberta (C2). Página REMOTA, sem IPC: fala com o serviço (/carta/*) e recebe o arrasto do NLE pelo
   Rust (`arrasto_mac`/`arrasto_win` chamam `window.cartaArrasto`). Comportamento: o protótipo aprovado
   (docs/plano/prototipos/janela-carta-aberta.html) e o plano, "C2 — proposta".

   ⛔ Puxar uma LINHA para uma pasta (mover, a parte 2) é movimento do mouse DENTRO da página, nunca o arrasto HTML:
      no Mac a webview registra `public.data` para o Premiere, e um arrasto HTML passaria pelo mesmo alvo do sistema. */
"use strict";

var TAXAS = [["24000/1001", "23,976"], ["24", "24"], ["25", "25"], ["30000/1001", "29,97"], ["30", "30"]];
var ST = { warn: "a decidir: um arquivo que chegou pode ser esta mídia", ok: "encontrada nesta máquina", err: "sem mídia nesta máquina", item: "item: aponta mídias do projeto" };
var RANK = { err: 0, warn: 1, ok: 2, item: 3 };
var ATUALIZAR_MS = 10000;

var projeto = null;          // {raiz, nome, taxa}
var recentes = [];
var pastas = [];             // [{caminho, nome, nivel, n}] em ordem de árvore
var fechadas = {};           // caminho → true: o ramo recolhido
var abertas = [];            // a pasta virtual: as pastas selecionadas, na ordem da árvore
var ancora = null;
var vista = [];              // as linhas das pastas abertas
var selecionadas = {};       // id → true
var ordem = null;            // {col, dir}
var lidoEm = 0;
var ultimaLista = "", ultimaArvore = "", ultimosCasos = "";   // o que foi desenhado por último (o piscar)

function $(id) { return document.getElementById(id); }
function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
function postar(url, corpo) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo || {}) })
    .then(function (r) { return r.json(); });
}
function comProjeto(corpo) { corpo = corpo || {}; corpo.raiz = projeto && projeto.raiz; return corpo; }
function taxaLegivel(t) { for (var i = 0; i < TAXAS.length; i++) { if (TAXAS[i][0] === t) { return TAXAS[i][1] + " qps"; } } return t ? t + " qps" : ""; }
function nomeDaPasta(c) { for (var i = 0; i < pastas.length; i++) { if (pastas[i].caminho === c) { return pastas[i].nome; } } return c || (projeto ? projeto.nome : ""); }
function caminhoLegivel(c) { return c ? c.split("/").join(" / ") : (projeto ? projeto.nome : ""); }

/* ── o projeto ─────────────────────────────────────────────────────────── */

function carregarRecentes() {
  return fetch("/carta/projetos", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
    recentes = d.projetos || [];
  }, function () { recentes = []; });
}

function abrirProjeto(p, abrindo) {
  projeto = p;
  try { localStorage.setItem("carta.raiz", p.raiz); } catch (e) { /* sem armazenamento: só não lembra */ }
  abertas = []; selecionadas = {}; ordem = null;
  return lerArvore(abrindo).then(function () {
    if (!abertas.length && pastas.length) {
      var primeira = pastas.length > 1 ? pastas[1].caminho : pastas[0].caminho;
      abertas = [primeira]; ancora = primeira;
      desenharArvore();                                // a árvore foi desenhada antes da escolha: marcar a aberta
    }
    return lerConteudo().then(lerDecidir);
  });
}

function mostrarSemProjeto(motivo) {
  projeto = null;
  $("corpo").hidden = true; $("semProjeto").hidden = false;
  $("botaoProjeto").textContent = "Projeto ▾";
  $("caminhoProjeto").textContent = "";
  $("vazioErro").hidden = !motivo; $("vazioErro").textContent = motivo || "";
}

function lerArvore(abrindo) {
  return postar("/carta/arvore", comProjeto({ abrindo: !!abrindo })).then(function (d) {
    if (!d.ok) { mostrarSemProjeto(d.motivo); return Promise.reject(d.motivo); }
    projeto = d.projeto;
    var arvoreNova = JSON.stringify(d.pastas || []) + "|" + abertas.join("\n");
    var mudou = arvoreNova !== ultimaArvore || abrindo;
    ultimaArvore = arvoreNova;
    pastas = d.pastas || [];
    var existem = {};
    pastas.forEach(function (p) { existem[p.caminho] = true; });
    abertas = abertas.filter(function (c) { return existem[c]; });     // outro editor pode ter mudado a pasta
    $("semProjeto").hidden = true; $("corpo").hidden = false;
    $("botaoProjeto").textContent = projeto.nome + " ▾";
    $("caminhoProjeto").textContent = projeto.raiz + (projeto.taxa ? " · " + taxaLegivel(projeto.taxa) : "");
    if (abrindo) {
      var q = d.quarentena || [];
      $("quarentena").hidden = !q.length;
      $("quarentena").textContent = q.length ? "Quarentena: " + q.length + " arquivo(s) que não eram da Carta foram para lá ao abrir" : "";
      $("quarentena").title = q.join("\n");
    }
    if (mudou) { desenharArvore(); }
  });
}

function lerConteudo() {
  if (!projeto) { return Promise.resolve(); }
  if (!abertas.length) { vista = []; ultimaLista = ""; desenharLista(); return Promise.resolve(); }
  var pedidas = abertas.slice();
  return postar("/carta/conteudo", comProjeto({ pastas: pedidas, referenciados: $("mostrarReferenciados").checked })).then(function (d) {
    if (pedidas.join("\n") !== abertas.join("\n")) { return; }        // o editor já clicou em outra pasta
    if (!d.ok) { vista = []; ultimaLista = ""; desenharLista(d.motivo); return; }
    var nova = JSON.stringify(d.linhas || []);
    if (nova === ultimaLista) { lidoEm = Date.now(); return; }     // nada mudou: não redesenhar (as miniaturas piscavam)
    ultimaLista = nova;
    vista = d.linhas || [];
    var vivas = {};
    vista.forEach(function (l) { vivas[l.id] = true; });
    Object.keys(selecionadas).forEach(function (id) { if (!vivas[id]) { delete selecionadas[id]; } });
    lidoEm = Date.now();
    if (selecionarAoLer && vivas[selecionarAoLer]) { selecionadas = {}; selecionadas[selecionarAoLer] = true; }
    var rolar = selecionarAoLer; selecionarAoLer = null;
    desenharLista();
    if (rolar) { rolarAte(rolar); }
  });
}

function atualizar() {
  if (!projeto || document.hidden) { return; }
  lerArvore(false).then(lerConteudo).then(lerDecidir, function () {});
}

/* ── a árvore ──────────────────────────────────────────────────────────── */

function temFilhos(i) { return i + 1 < pastas.length && pastas[i + 1].nivel > pastas[i].nivel; }
function visivelNaArvore(i) {
  var nivel = pastas[i].nivel;
  for (var k = i - 1; k >= 0 && nivel > 0; k--) {
    if (pastas[k].nivel < nivel) {
      if (fechadas[pastas[k].caminho]) { return false; }
      nivel = pastas[k].nivel;
    }
  }
  return true;
}

function desenharArvore() {
  $("arvore").innerHTML = pastas.map(function (p, i) {
    if (!visivelNaArvore(i)) { return ""; }
    var aberta = abertas.indexOf(p.caminho) >= 0;
    var tri = temFilhos(i) ? (fechadas[p.caminho] ? "▸" : "▾") : "";
    return '<button type="button" class="pasta' + (aberta ? " aberta" : "") + '" data-caminho="' + esc(p.caminho) + '" role="treeitem" aria-selected="' + aberta +
      '" style="padding-left:' + (8 + p.nivel * 14) + 'px"><span class="tri" data-tri="1">' + tri + '</span><span class="ic"></span>' +
      '<span class="nome">' + esc(p.nome) + "</span>" + (p.n ? '<span class="n">' + p.n + "</span>" : "") + "</button>";
  }).join("");
  var um = abertas.length === 1;
  $("novaPasta").disabled = !um;
  $("novaPasta").title = um ? "Criar uma pasta dentro de " + nomeDaPasta(abertas[0]) : abertas.length ? "Selecione uma pasta só para criar dentro dela" : "Selecione a pasta onde criar";
}

$("arvore").addEventListener("click", function (e) {
  var b = e.target.closest(".pasta"); if (!b) { return; }
  var c = b.dataset.caminho;
  if (e.target.closest("[data-tri]") && e.target.closest("[data-tri]").textContent) {
    fechadas[c] = !fechadas[c]; desenharArvore(); return;
  }
  var ordemArvore = pastas.map(function (p) { return p.caminho; });
  if (e.shiftKey && ancora !== null) {                 // o intervalo, na ordem da árvore, a partir da última clicada
    var a = ordemArvore.indexOf(ancora), z = ordemArvore.indexOf(c);
    abertas = ordemArvore.slice(Math.min(a, z), Math.max(a, z) + 1).filter(function (x, k) { return visivelNaArvore(ordemArvore.indexOf(x)); });
  } else if (e.ctrlKey || e.metaKey) {                 // soma ou tira; pode ficar sem NENHUMA (autor): aí a lista fica vazia
    abertas = abertas.indexOf(c) >= 0 ? abertas.filter(function (x) { return x !== c; }) : abertas.concat([c]);
    abertas.sort(function (x, y) { return ordemArvore.indexOf(x) - ordemArvore.indexOf(y); });
    ancora = c;
  } else { abertas = [c]; ancora = c; }
  selecionadas = {};
  desenharArvore(); vista = []; ultimaLista = ""; desenharLista(); lerConteudo();
});

/* ── a lista ───────────────────────────────────────────────────────────── */

var ICONE = {
  "vídeo": '<rect x="1" y="2" width="18" height="10" rx="1" fill="none" stroke="currentColor"/><path d="M4 2v10M16 2v10" stroke="currentColor"/>',
  "som": '<path d="M2 7h2M5 4v6M8 2v10M11 5v4M14 3v8M17 6v2" stroke="currentColor" stroke-width="1.4"/>',
  "subclipe (V)": '<rect x="1" y="2" width="18" height="10" rx="1" fill="none" stroke="currentColor" stroke-dasharray="2 1.5"/><path d="M7 4v6M13 4v6" stroke="currentColor"/>',
  "subclipe (A)": '<rect x="1" y="2" width="18" height="10" rx="1" fill="none" stroke="currentColor" stroke-dasharray="2 1.5"/><path d="M5 7h1M8 5v4M11 4v6M14 6v2" stroke="currentColor"/>',
  "subclipe (A\\V)": '<rect x="1" y="1" width="18" height="5" rx="1" fill="none" stroke="currentColor"/><path d="M2 10h2M5 8v4M8 9v2M11 8v4M14 9v2M17 10h1" stroke="currentColor"/>',
  "multicam": '<rect x="1" y="1" width="8" height="5" fill="none" stroke="currentColor"/><rect x="11" y="1" width="8" height="5" fill="none" stroke="currentColor"/><rect x="1" y="8" width="8" height="5" fill="none" stroke="currentColor"/><rect x="11" y="8" width="8" height="5" fill="currentColor"/>',
  "timeline": '<rect x="1" y="2" width="18" height="10" rx="1" fill="none" stroke="currentColor"/><path d="M3 5h7M7 9h9" stroke="currentColor" stroke-width="2"/>',
  "nest": '<rect x="1" y="1" width="18" height="12" rx="1" fill="none" stroke="currentColor"/><rect x="5" y="4" width="10" height="6" rx="1" fill="none" stroke="currentColor"/>'
};
function icone(t) { return '<svg class="ti-ic" viewBox="0 0 20 14" role="img" aria-label="' + esc(t) + '"><title>' + esc(t) + "</title>" + (ICONE[t] || "") + "</svg>"; }
function ponto(v) { return '<i class="ponto ' + v + '" title="' + esc(ST[v] || v) + '"></i>'; }

function chaveDe(l, col) {
  if (col === "status") { return RANK[l.status]; }
  if (col === "duracao_s") { return l.duracao_s || 0; }
  if (col === "fps") { return parseFloat(String(l.fps || "0").replace(",", ".")) || 0; }
  return String(l[col] || "").toLowerCase();
}
function ordenada() {
  var v = vista.slice();
  if (ordem) {
    v.sort(function (a, b) { var x = chaveDe(a, ordem.col), y = chaveDe(b, ordem.col); return (x < y ? -1 : x > y ? 1 : 0) * ordem.dir; });
  }
  return v;
}

function desenharTitulos() {
  document.querySelectorAll("#titulos th").forEach(function (th) {
    var c = th.dataset.col;
    th.classList.toggle("ordenada", !!ordem && ordem.col === c);
    var s = th.querySelector(".seta"); if (s) { s.remove(); }
    if (ordem && ordem.col === c) { th.insertAdjacentHTML("beforeend", '<span class="seta">' + (ordem.dir > 0 ? "▲" : "▼") + "</span>"); }
    if (!th.querySelector(".alca")) { th.insertAdjacentHTML("beforeend", '<span class="alca" title="arraste para mudar a largura"></span>'); }
  });
}

var linhasNaTela = [];
function desenharLista(erro) {
  desenharTitulos();
  var varias = abertas.length > 1, nenhuma = !abertas.length;
  var total = abertas.reduce(function (n, c) { for (var i = 0; i < pastas.length; i++) { if (pastas[i].caminho === c) { return n + pastas[i].n; } } return n; }, 0);
  $("tituloPasta").innerHTML = nenhuma ? "Nenhuma pasta selecionada" : varias
    ? abertas.length + " pastas juntas <small>" + abertas.map(function (c) { return esc(nomeDaPasta(c)); }).join(" + ") + " · " + total + " mídias e itens</small>"
    : esc(caminhoLegivel(abertas[0])) + " <small>" + total + " mídias e itens</small>";
  linhasNaTela = ordenada();
  if (!linhasNaTela.length) {
    var msg = erro ? esc(erro) : nenhuma ? "Selecione uma ou mais pastas na árvore." : varias ? "As pastas selecionadas estão vazias."
      : "Pasta vazia. Arraste para cá o que estiver na bin do Media Composer ou do Premiere.";
    $("linhas").innerHTML = '<tr><td colspan="8" style="padding:40px;text-align:center;color:var(--tinta-2);background:var(--bg-1);white-space:normal">' + msg + "</td></tr>";
    desenharDetalhe();
    return;
  }
  $("linhas").innerHTML = linhasNaTela.map(function (l, i) {
    var mora = l.revelada ? '<span class="mora">' + (l.mora_em === null ? "oculta" : "mora em " + esc(nomeDaPasta(l.mora_em))) + "</span>" : "";
    return '<tr class="linha' + (selecionadas[l.id] ? " sel" : "") + (l.revelada ? " revelada" : "") + '" data-i="' + i + '">' +
      '<td class="st">' + ponto(emCaso(l.id) && l.status === "ok" ? "warn" : l.status) + "</td>" +
      '<td class="mini"><img class="mini-q" alt="" draggable="false" loading="lazy" src="/carta/miniatura?raiz=' + encodeURIComponent(projeto.raiz) + "&id=" + encodeURIComponent(l.id) + '"></td>' +
      '<td class="ti">' + icone(l.tipo) + "</td>" +
      '<td class="nome" title="' + esc(l.nome) + " · em " + esc(nomeDaPasta(l.pasta)) + '">' + esc(l.nome) +
      (emCaso(l.id) ? '<span class="pend">a decidir</span>' : "") +
      (varias ? '<span class="de-pasta">' + esc(nomeDaPasta(l.pasta)) + "</span>" : "") + mora + "</td>" +
      '<td class="tc">' + esc(l.tc) + '</td><td class="tc">' + esc(l.duracao) + '</td><td class="tc">' + esc(l.fps || "—") + "</td>" +
      '<td class="codec">' + esc(l.codec || (l.item ? "—" : "")) + "</td></tr>";
  }).join("");
  desenharDetalhe();
}

var abaAtiva = {};          // id da linha → a aba dos "Caminhos conhecidos" que o editor escolheu
var ICONE_PEQUENO = {
  video: '<svg class="ic-ref" viewBox="0 0 20 14" aria-label="vídeo"><title>vídeo</title><rect x="1" y="2" width="18" height="10" rx="1" fill="none" stroke="currentColor"/><path d="M4 2v10M16 2v10" stroke="currentColor"/></svg>',
  audio: '<svg class="ic-ref" viewBox="0 0 20 14" aria-label="áudio"><title>áudio</title><path d="M2 7h2M5 4v6M8 2v10M11 5v4M14 3v8M17 6v2" stroke="currentColor" stroke-width="1.4"/></svg>'
};

function tabelaDeCaminhos(caminhos, item) {
  if (!caminhos || !caminhos.length) {
    return '<p class="falta">' + (item ? "Nenhum: um item não tem arquivo próprio, aponta as mídias do projeto." : "Nenhum caminho conhecido.") + "</p>";
  }
  return '<table class="conhecidos"><tbody>' + caminhos.map(function (c) {
    var n = (c.arquivos || []).length;
    return '<tr data-arquivos="' + esc(JSON.stringify(c.arquivos && c.arquivos.length ? c.arquivos : [c.arquivo])) + '" class="' + (c.existe ? "" : "ausente") +
      '" title="' + (c.existe ? "duplo clique: abrir a pasta com " + (n > 1 ? "os " + n + " arquivos marcados" : "o arquivo marcado") : "") + '"><td><code>' + esc(c.arquivo) + "</code>" +
      (n > 1 ? ' <span class="mais">+' + (n - 1) + " arquivo" + (n > 2 ? "s" : "") + " da mesma mídia</span>" : "") + "</td></tr>";
  }).join("") + "</tbody></table>";
}

function desenharDetalhe() {
  desenharImportar();
  var sel = linhasNaTela.filter(function (l) { return selecionadas[l.id]; });
  if (sel.length !== 1) {
    $("detalhe").innerHTML = '<div class="meta"><h3>' + (sel.length ? sel.length + " selecionadas" : "Nada selecionado") + "</h3></div>";
    return;
  }
  var l = sel[0];
  var ondeMora = l.revelada ? (l.mora_em === null ? "oculta (removida da vista)" : caminhoLegivel(l.mora_em)) + " · revelada por " + caminhoLegivel(l.pasta) : caminhoLegivel(l.pasta);
  var dl = [["Pasta", ondeMora], ["Tipo", l.tipo], ["Codec", l.codec], ["TC início", l.tc], ["Duração", l.duracao], ["FPS", l.fps],
            ["Status", ST[emCaso(l.id) && l.status === "ok" ? "warn" : l.status]], ["Origem", l.quem]]
    .filter(function (x) { return x[1]; })
    .map(function (x) { return "<dt>" + x[0] + "</dt><dd>" + esc(x[1]) + "</dd>"; }).join("");
  // ⭐ "Itens referenciados" (autor, 13/11): lista simples, ícone de vídeo/áudio, vídeo antes do som; o clique leva ao item
  var refsHtml = "";
  if ((l.referenciados || []).length) {
    refsHtml = '<h4 class="sub-titulo">Itens referenciados</h4><ul class="referenciados">' + l.referenciados.map(function (r) {
      var clicavel = !!r.id && r.existe !== false;
      return "<li" + (clicavel ? ' class="ir" data-ir="' + esc(r.id) + '" data-mora="' + esc(r.mora_em === null || r.mora_em === undefined ? "" : r.mora_em) +
        '" data-oculta="' + (r.mora_em === null ? "1" : "") + '" title="ir para ' + esc(r.nome) + '"' : "") + ">" +
        (ICONE_PEQUENO[r.tipo] || ICONE_PEQUENO.video) + "<span>" + esc(r.nome) + "</span></li>";
    }).join("") + "</ul>";
  }
  // "Caminhos conhecidos": no subclipe e na multicam, uma ABA por mídia; no OP-Atom, aba só com arquivos em lugares diferentes
  var direita;
  if (l.abas && l.abas.length) {
    var k = Math.min(abaAtiva[l.id] || 0, l.abas.length - 1);
    direita = '<div class="abas-caminhos">' + l.abas.map(function (a, i) {
      return '<button type="button" class="aba-c' + (i === k ? " ativa" : "") + '" data-aba="' + i + '" title="' + esc(a.titulo) + '">' + esc(a.titulo) + "</button>";
    }).join("") + "</div>" + tabelaDeCaminhos(l.abas[k].caminhos, false);
  } else {
    direita = tabelaDeCaminhos(l.caminhos, l.item);
  }
  $("detalhe").innerHTML = '<div class="meta"><h3>' + esc(l.nome) + "</h3><dl>" + dl + "</dl>" + refsHtml + "</div>" +
    '<div class="caminhos"><h4>Caminhos conhecidos</h4>' + direita + "</div>";
}

$("detalhe").addEventListener("click", function (e) {
  var aba = e.target.closest("[data-aba]");
  if (aba) {
    var id = Object.keys(selecionadas)[0];
    abaAtiva[id] = +aba.dataset.aba; desenharDetalhe(); return;
  }
  var ir = e.target.closest("[data-ir]");
  if (ir) { irPara(ir.dataset.ir, ir.dataset.mora, ir.dataset.oculta === "1"); }
});

/* Ir ao item referenciado: se ele já está À VISTA (na mesma pasta, ou revelado pelo interruptor), é ali; senão, a pasta
   onde ele mora. Removido da vista e sem o interruptor: dito, nunca um clique que não faz nada. */
var selecionarAoLer = null;
function irPara(id, mora, oculta) {
  if (linhasNaTela.some(function (x) { return x.id === id; })) {
    selecionadas = {}; selecionadas[id] = true; desenharLista(); rolarAte(id); return;
  }
  if (oculta) { faixa("", "Carta", "Esse item foi removido da vista: ligue Mostrar clipes referenciados para vê-lo aqui."); return; }
  abertas = [mora]; ancora = mora; selecionadas = {}; selecionarAoLer = id;
  desenharArvore(); vista = []; ultimaLista = ""; desenharLista(); lerConteudo();
}
function rolarAte(id) {
  var i = linhasNaTela.findIndex(function (x) { return x.id === id; });
  var tr = document.querySelector('tr.linha[data-i="' + i + '"]');
  if (tr) { tr.scrollIntoView({ block: "nearest" }); }
}

$("linhas").addEventListener("click", function (e) {
  var tr = e.target.closest("tr.linha"); if (!tr) { return; }
  var i = +tr.dataset.i, id = linhasNaTela[i].id;
  if (e.metaKey || e.ctrlKey) {
    if (selecionadas[id]) { delete selecionadas[id]; } else { selecionadas[id] = true; }
  } else if (e.shiftKey && Object.keys(selecionadas).length) {
    var marcadas = linhasNaTela.map(function (l, k) { return selecionadas[l.id] ? k : -1; }).filter(function (k) { return k >= 0; });
    var a = Math.min.apply(null, marcadas.concat([i])), b = Math.max.apply(null, marcadas.concat([i]));
    selecionadas = {};
    for (var k = a; k <= b; k++) { selecionadas[linhasNaTela[k].id] = true; }
  } else { selecionadas = {}; selecionadas[id] = true; }
  desenharLista();
});

$("titulos").addEventListener("dblclick", function (e) {
  if (e.target.closest(".alca")) { return; }
  var th = e.target.closest("th"); if (!th || !th.dataset.col) { return; }
  ordem = ordem && ordem.col === th.dataset.col ? { col: ordem.col, dir: -ordem.dir } : { col: th.dataset.col, dir: 1 };
  desenharLista();
});

$("titulos").addEventListener("mousedown", function (e) {
  var alca = e.target.closest(".alca"); if (!alca) { return; }
  e.preventDefault();
  var th = alca.parentElement, idx = Array.prototype.indexOf.call(th.parentElement.children, th);
  var tabela = th.closest("table"), cols = tabela.querySelectorAll("col"), ths = tabela.querySelectorAll("th");
  var x0 = e.clientX, w0 = th.getBoundingClientRect().width;
  // a primeira puxada congela as larguras em px: daí cada coluna muda sozinha e a tabela cresce (rola de lado)
  cols.forEach(function (c, i) { c.style.width = ths[i].getBoundingClientRect().width + "px"; });
  tabela.style.width = "max-content";
  alca.classList.add("puxando");
  function mover(ev) { cols[idx].style.width = Math.max(36, w0 + ev.clientX - x0) + "px"; }
  function soltar() { alca.classList.remove("puxando"); removeEventListener("mousemove", mover); removeEventListener("mouseup", soltar); }
  addEventListener("mousemove", mover); addEventListener("mouseup", soltar);
});

// duplo clique num caminho conhecido: a pasta no Finder/Explorer com o arquivo marcado (o serviço confere o caminho)
$("detalhe").addEventListener("dblclick", function (e) {
  var tr = e.target.closest("tr[data-arquivos]"); if (!tr || tr.classList.contains("ausente")) { return; }
  postar("/carta/revelar", comProjeto({ arquivos: JSON.parse(tr.dataset.arquivos) })).then(function (d) {
    if (!d.ok) { faixa("erro", "Não abri", esc(d.motivo)); }
  });
});

/* ── Ctrl/Cmd+A: tudo do painel que o editor clicou por último (autor, 13/11) ──
   Na árvore, todas as pastas (as visíveis, na ordem: vira a pasta virtual); na lista, todas as linhas. ⛔ Num campo de
   texto o atalho é do campo (selecionar o texto), e com diálogo aberto não mexe em nada atrás dele. */

var painelAtivo = "lista";
$("arvore").closest(".arvore").addEventListener("mousedown", function () { painelAtivo = "arvore"; });
$("caixa").addEventListener("mousedown", function () { painelAtivo = "lista"; });
$("detalhe").addEventListener("mousedown", function () { painelAtivo = "lista"; });

function selecionarTudo() {
  if (!$("dialogoFundo").hidden || !projeto || $("corpo").hidden) { return false; }
  if (painelAtivo === "arvore") {
    abertas = pastas.filter(function (p, i) { return visivelNaArvore(i); }).map(function (p) { return p.caminho; });
    ancora = abertas.length ? abertas[0] : null;
    selecionadas = {};
    desenharArvore(); vista = []; ultimaLista = ""; desenharLista(); lerConteudo();
  } else {
    selecionadas = {};
    linhasNaTela.forEach(function (l) { selecionadas[l.id] = true; });
    desenharLista();
  }
  return true;
}
function emCampo(alvo) { return !!(alvo && alvo.closest && alvo.closest("input, textarea, select, [contenteditable]")); }

// Windows (WebView2) e navegador: a tecla chega à página.
document.addEventListener("keydown", function (e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || String(e.key).toLowerCase() !== "a" || emCampo(e.target)) { return; }
  e.preventDefault();
  selecionarTudo();
});
// ⛔⛔ Mac (MEDIDO 2026-11-13, macOS 15.6, Tauri 2.12.5): o Cmd+A NÃO chega como tecla — o menu Edit › Select All do app o
//    pega e manda um "selecionar tudo" à webview, que só aparece como `selectstart`. Sem botão do mouse apertado, um
//    `selectstart` é esse gesto (o arrasto do mouse que seleciona texto vem com o botão apertado).
var botaoApertado = false;
document.addEventListener("mousedown", function () { botaoApertado = true; }, true);
document.addEventListener("mouseup", function () { botaoApertado = false; }, true);
document.addEventListener("selectstart", function (e) {
  if (botaoApertado || emCampo(e.target)) { return; }
  e.preventDefault();
  selecionarTudo();
}, true);

/* ── "Importar para X" (autor, 2026-11-14) ─────────────────────────────────
   X = o NLE aberto e conectado (`/conexao`), nunca "Importar" sozinho. Leva a seleção ao projeto aberto nele, para a
   bin selecionada (ou a aberta por último), DIRETO: sem resumo nem confirmação, e só o ERRO aparece (o que ficou de fora
   vai para o diário do projeto). Hoje: UMA timeline, para o Premiere (`/carta/premiere/importar`). */

var NOME_DO_NLE = { premiere: "o Premiere", avid: "o Media Composer", resolve: "o Resolve", baselight: "o Baselight" };
var nleConectado = "";       // "premiere" · "avid" · "resolve" · "baselight" · ""
var importando = false;

function lerConexao() {
  if (document.hidden) { return Promise.resolve(); }
  return fetch("/conexao", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (c) {
    var n = c.premiere ? "premiere" : c.avid ? "avid" : c.resolve ? "resolve" : c.baselight ? "baselight" : "";
    if (n !== nleConectado) { nleConectado = n; desenharImportar(); }
  }, function () {});
}

/* null = pode; senão a frase que diz por que não */
function porQueNaoImporta() {
  if (!nleConectado) { return "Nenhum NLE aberto e conectado."; }
  if (nleConectado !== "premiere" && nleConectado !== "baselight") {
    return "Importar para " + NOME_DO_NLE[nleConectado] + " ainda não existe: hoje só para o Premiere e o Baselight.";
  }
  var sel = linhasNaTela.filter(function (l) { return selecionadas[l.id]; });
  if (!sel.length) { return "Selecione uma timeline."; }
  if (sel.length > 1 || !sel[0].timeline) { return "Por enquanto vai UMA timeline por vez (mídia, subclipe e multicam ainda não)."; }
  if (sel[0].status === "err") { return "Esta timeline usa mídia que não está nesta máquina."; }
  return null;
}

function desenharImportar() {
  var b = $("botaoImportar");
  b.hidden = !nleConectado;
  if (!nleConectado) { return; }
  var alvo = NOME_DO_NLE[nleConectado];
  b.textContent = importando ? "Importando para " + alvo + "…" : "Importar para " + alvo;
  var nao = importando ? "" : porQueNaoImporta();
  b.disabled = importando || !!nao;
  b.title = nao || (importando ? "" : "Leva a timeline selecionada ao projeto aberto, na bin selecionada (ou na aberta por último)");
  b.classList.toggle("trabalhando", importando);
}

function importar() {
  if (importando || porQueNaoImporta()) { return; }
  var l = linhasNaTela.filter(function (x) { return selecionadas[x.id]; })[0];
  if (nleConectado === "baselight") { perguntarBaselight(l); return; }
  importando = true; desenharImportar();
  postar("/carta/premiere/importar", comProjeto({ id: l.id })).then(function (r) {
    importando = false; desenharImportar();
    if (!r.ok) { faixa("erro", "Premiere", "Não importei " + esc(l.nome) + ": " + esc(r.motivo)); }
  }, function () {
    importando = false; desenharImportar();
    faixa("erro", "Premiere", "Não consegui falar com o serviço do Ciclo Assist.");
  });
}
$("botaoImportar").addEventListener("click", importar);

/* ── o Baselight (proposta 2026-11-22-baselight-no-app, etapa 3) ──────────
   O Baselight só RECEBE, então o Importar pergunta (autor): "Importar timeline" (as mídias da Carta, sem casar: a Carta
   não é conform) ou "Conformar com De Lá Pra Cá" (casa com os originais e confere — o app abre a aba Conformar com a
   timeline carregada; lá o colorista aponta as pastas dos originais e o vid ref). O job é o da PRODUÇÃO: o nome do
   projeto da Carta, ou outro da lista; cada importação é uma scene nova ("… · import 02"), nunca por cima. */
function perguntarBaselight(l) {
  postar("/carta/baselight/jobs", comProjeto({})).then(function (j) {
    var lista = (j.jobs || []).map(function (x) { return '<option value="' + esc(x) + '"></option>'; }).join("");
    // a etapa 4 (autor): com uma scene ABERTA no Baselight num job que não é o da produção, pergunta em qual importar,
    // com "não perguntar novamente" (lembrado nesta máquina)
    var aberto = j.aberto && j.aberto.job && j.aberto.job !== j.sugerido ? j.aberto : null;
    var lembrado = localStorage.getItem("carta.baselight.semPerguntarJob");
    var perguntaJob = aberto && !lembrado
      ? '<p class="nota-job">O Baselight está com o job “' + esc(aberto.job) + '” aberto (scene “' + esc(aberto.scene) + '”).</p>' +
        '<label class="opcao"><input type="radio" name="qualJobBl" value="aberto"> No job aberto (' + esc(aberto.job) + ")</label>" +
        '<label class="opcao"><input type="radio" name="qualJobBl" value="meu" checked> No job da produção, abaixo</label>' +
        '<label class="opcao"><input type="checkbox" id="campoSemPerguntaBl"> Não perguntar novamente</label>'
      : "";
    var sugerido = aberto && lembrado === "aberto" ? aberto.job : (j.sugerido || "");
    dialogo("Levar " + l.nome + " ao Baselight",
      (j.disponivel === false ? j.motivo + ". " : "") + "Importar leva a timeline como está, com as mídias da Carta. " +
      "Conformar abre o De Lá Pra Cá: ele casa cada plano com o original de câmera e confere.",
      "Continuar",
      '<label class="opcao"><input type="radio" name="comoBl" value="importar" checked> Importar timeline</label>' +
      '<label class="opcao"><input type="radio" name="comoBl" value="conformar"> Conformar com De Lá Pra Cá</label>' +
      perguntaJob +
      '<label>Job da produção<input id="campoJobBl" list="listaJobsBl" autocomplete="off" value="' +
      esc(sugerido) + '"><datalist id="listaJobsBl">' + lista + "</datalist></label>" +
      '<label class="opcao"><input type="checkbox" id="campoMarkersBl" checked> Marcar os planos com problema</label>',
      function () {
        var como = (document.querySelector('input[name="comoBl"]:checked') || {}).value;
        var job = $("campoJobBl").value.trim();
        var qual = (document.querySelector('input[name="qualJobBl"]:checked') || {}).value;
        if (qual === "aberto") { job = aberto.job; }
        if (qual && $("campoSemPerguntaBl").checked) {
          try { localStorage.setItem("carta.baselight.semPerguntarJob", qual); } catch (e) { /* segue */ }
        }
        if (como === "conformar") {
          return postar("/carta/baselight/conformar", comProjeto({ id: l.id, job: job })).then(function (r) {
            if (!r.ok) { return Promise.reject(r.motivo); }
            faixa("", "Baselight", esc(r.nome) + " foi para o De Lá Pra Cá (aba Conformar): aponte as pastas dos originais e leia a timeline.");
          });
        }
        fecharDialogo();
        importando = true; desenharImportar();
        return postar("/carta/baselight/importar", comProjeto({ id: l.id, job: job,
                                                               markers: $("campoMarkersBl").checked })).then(function (r) {
          importando = false; desenharImportar();
          if (!r.ok) { faixa("erro", "Baselight", "Não importei " + esc(l.nome) + ": " + esc(r.motivo)); return; }
          var c = r.contagem || {}, prob = (r.problemas || []).length;
          faixa(prob ? "aviso" : "", "Baselight", "“" + esc(r.scene) + "” no job " + esc(r.job) + ": " + (c.ok || 0) + " de " +
                r.planos + " planos certos" + (r.trocados ? " · " + r.trocados + " corrigidos" : "") +
                (prob ? " · " + prob + " a conferir" + (r.markers ? " (marker [Ciclo] em cada um)" : "") : "") +
                (prob ? ' <span class="detalhes">— ' + (r.problemas || []).slice(0, 6).map(function (x) {
                  return esc(x.arquivo) + ": " + esc(x.motivo); }).join(" · ") + "</span>" : ""));
        }, function () {
          importando = false; desenharImportar();
          faixa("erro", "Baselight", "Não consegui falar com o serviço do Ciclo Assist.");
        });
      });
  });
}

/* ── a faixa: a conta do que aconteceu ─────────────────────────────────── */

function faixa(classe, origem, html) {
  var f = $("faixa");
  f.className = "faixa " + (classe || "");
  f.querySelector(".origem").textContent = origem;
  f.querySelector(".conta").innerHTML = html;
  f.hidden = false;
}
$("fecharFaixa").addEventListener("click", function () { $("faixa").hidden = true; });

function nomes(lista) { return lista.slice(0, 6).map(esc).join(", ") + (lista.length > 6 ? " e mais " + (lista.length - 6) : ""); }
function contaDoMandar(d, pasta) {
  var c = d.conta || {}, it = d.itens || {};
  var partes = [], depois = [];
  function n(x) { return (x || []).length; }
  if (n(c.novas)) { partes.push(n(c.novas) + (n(c.novas) === 1 ? " nova" : " novas")); }
  if (n(c.ja_estavam)) { partes.push(n(c.ja_estavam) + " já estava" + (n(c.ja_estavam) === 1 ? "" : "m")); }
  if (n(it.novos)) { partes.push(n(it.novos) + (n(it.novos) === 1 ? " item novo" : " itens novos")); }
  if (n(it.ja_estavam)) { partes.push(n(it.ja_estavam) + (n(it.ja_estavam) === 1 ? " item já estava" : " itens já estavam")); }
  if (n(it.angulos)) { partes.push("ângulo atualizado em " + nomes(it.angulos)); }
  if (Object.keys(it.repetidas || {}).length) { partes.push(Object.keys(it.repetidas).length + (Object.keys(it.repetidas).length === 1 ? " timeline já salva, igual" : " timelines já salvas, iguais")); }
  var decidir = Object.keys(c.empates || {}).length + Object.keys(c.homonimos || {}).length + Object.keys(it.a_decidir || {}).length;
  if (decidir) { partes.push("<em>" + decidir + " a decidir</em>"); }
  Object.keys(c.homonimos || {}).forEach(function (k) { depois.push(esc(k) + ": " + esc(c.homonimos[k])); });
  Object.keys(c.empates || {}).forEach(function (k) { depois.push(esc(k) + ": mais de um arquivo serve (" + (c.empates[k] || []).length + ")"); });
  Object.keys(c.ilegiveis || {}).forEach(function (k) { depois.push(esc(k) + ": " + esc(c.ilegiveis[k])); });
  Object.keys(it.recusados || {}).forEach(function (k) { depois.push(esc(k) + ": " + esc(it.recusados[k])); });
  Object.keys(it.avisos || {}).forEach(function (k) { depois.push(esc(k) + ": " + esc(it.avisos[k])); });
  Object.keys(it.repetidas || {}).forEach(function (k) { depois.push(esc(k) + ": " + esc(it.repetidas[k])); });
  Object.keys(it.a_decidir || {}).forEach(function (k) { depois.push(esc(k) + ": " + esc(it.a_decidir[k])); });
  Object.keys(it.sem_referencia || {}).forEach(function (k) { depois.push(esc(k) + ": a mídia dele não está no projeto"); });
  (d.sem_arquivo || []).forEach(function (k) { depois.push(esc(k) + ": ficou de fora (não é uma mídia)"); });
  var hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return "Mandado para " + esc(nomeDaPasta(pasta)) + " às " + hora + ": " + (partes.join(" · ") || "nada novo") +
    (depois.length ? ' <span class="detalhes">— ' + depois.join(" · ") + "</span>" : "");
}

/* ── o arrasto do NLE (o Rust avisa: sobre, soltou, saiu) ──────────────── */

var ORIGEM = { avid: "Media Composer", premiere: "Premiere", premiere_item: "Premiere" };

function destinoEm(x, y) {
  var el = document.elementFromPoint(x, y);
  var p = el && el.closest(".pasta");
  if (p) { return { pasta: p.dataset.caminho, el: p }; }
  if (el && el.closest(".direita")) { return abertas.length === 1 ? { pasta: abertas[0], lista: true } : { varias: true, lista: true }; }
  return null;
}

function apagarRealce() {
  document.querySelectorAll(".pasta.alvo").forEach(function (p) { p.classList.remove("alvo"); });
  $("solte").hidden = true;
}

function mobIdsDe(n) {
  if (n.mob_ids && n.mob_ids.length) { return n.mob_ids; }
  try {                                                // Windows: o MIME do MC, `[{id, type, …}]`
    var lista = JSON.parse(n.dados || "[]");
    return (Array.isArray(lista) ? lista : []).map(function (x) { return x && x.id; }).filter(Boolean);
  } catch (e) { return []; }
}

window.cartaArrasto = function (n) {
  if (!n || n.fase === "saiu") { apagarRealce(); return; }
  var origem = ORIGEM[n.tipo];
  var d = projeto && !$("corpo").hidden ? destinoEm(n.x, n.y) : null;
  if (n.fase === "sobre") {
    apagarRealce();
    if (!origem || !d) { return; }
    if (d.el) { d.el.classList.add("alvo"); return; }
    var s = $("solte"); s.hidden = false; s.className = "solte" + (n.tipo === "avid" ? "" : " externo");
    s.innerHTML = d.varias ? "Várias pastas na vista: solte sobre <b>&nbsp;uma pasta da árvore&nbsp;</b> para escolher o destino"
      : "Solte para mandar para <b>&nbsp;" + esc(nomeDaPasta(d.pasta)) + "</b><br><small>do " + origem + "</small>";
    return;
  }
  if (n.fase !== "soltou") { return; }
  apagarRealce();
  if (!projeto) { return; }
  if (n.tipo === "arquivos") { faixa("erro", "Finder", "A Carta recebe da bin do Media Composer ou do Premiere; arquivo solto do Finder/Explorer não entra por aqui."); return; }
  if (!origem || !d) { return; }
  if (d.varias) { faixa("erro", origem, "Várias pastas na vista: solte sobre uma pasta da árvore para escolher o destino."); return; }
  var corpo = comProjeto({ pasta: d.pasta, nle: n.tipo === "avid" ? "avid" : "premiere" });
  if (n.tipo === "avid") {
    corpo.mob_ids = mobIdsDe(n);
    if (!corpo.mob_ids.length) { faixa("erro", origem, "O arrasto do Media Composer chegou sem nenhum clipe."); return; }
  }
  var classe = n.tipo === "avid" ? "avid" : "premiere";
  faixa(classe, origem, "Mandando para " + esc(nomeDaPasta(d.pasta)) + '<span class="reticencias">…</span>');
  postar("/carta/mandar", corpo).then(function (r) {
    if (!r.ok) { faixa("erro", origem, esc(r.motivo) + (r.sem_arquivo && r.sem_arquivo.length ? " (" + nomes(r.sem_arquivo) + ")" : "")); return; }
    faixa(classe, origem, contaDoMandar(r, d.pasta));
    /* a timeline com o mesmo nome e outro conteúdo PERGUNTA: a gaveta abre sozinha (autor, 2026-11-20) */
    var pergunta = r.itens && Object.keys(r.itens.a_decidir || {}).length;
    lerArvore(false).then(lerConteudo).then(lerDecidir).then(function () {
      if (pergunta && casos.length) { desenharCasos(); $("gaveta").hidden = false; }
    });
  }, function () { faixa("erro", origem, "Não consegui falar com o serviço do Ciclo Assist."); });
};

/* ── menus e diálogos ──────────────────────────────────────────────────── */

function fecharMenus() { ["menuProjeto", "menuContexto"].forEach(function (m) { $(m).hidden = true; }); }

function desenharMenuProjeto() {
  var r = recentes.filter(function (p) { return !projeto || p.raiz !== projeto.raiz; });
  $("menuProjeto").innerHTML = '<button type="button" data-acao="novo">Novo projeto…<small>nome e taxa; o local você escolhe</small></button>' +
    '<button type="button" data-acao="abrir">Abrir projeto…<small>aponte a pasta de um projeto que existe</small></button>' +
    (r.length ? '<hr><div class="rot">Recentes</div>' + r.map(function (p) {
      return '<button type="button" data-raiz="' + esc(p.raiz) + '"' + (p.erro ? " disabled" : "") + ">" + esc(p.nome || p.raiz.split(/[\\/]/).pop()) +
        "<small>" + esc(p.erro || p.raiz) + "</small></button>";
    }).join("") : "");
}

$("botaoProjeto").addEventListener("click", function (e) {
  e.stopPropagation();
  var m = $("menuProjeto"), estava = m.hidden;
  fecharMenus();
  if (!estava) { return; }
  carregarRecentes().then(function () { desenharMenuProjeto(); m.hidden = false; });
});
$("menuProjeto").addEventListener("click", function (e) {
  var b = e.target.closest("button"); if (!b) { return; }
  fecharMenus();
  if (b.dataset.acao === "novo") { dialogoNovo(); }
  else if (b.dataset.acao === "abrir") { pedirAbrir(); }
  else if (b.dataset.raiz) {
    var p = recentes.filter(function (x) { return x.raiz === b.dataset.raiz; })[0];
    if (p) { abrirProjeto(p, true); }
  }
});
document.addEventListener("click", function (e) { if (!e.target.closest(".menu")) { fecharMenus(); } });
document.addEventListener("keydown", function (e) { if (e.key === "Escape") { fecharMenus(); fecharDialogo(); } });

var aoConfirmar = null;
function dialogo(titulo, texto, ok, campos, confirmar) {
  $("dTitulo").textContent = titulo; $("dTexto").textContent = texto; $("dOk").textContent = ok; $("dOk").className = "botao principal";
  $("dCampos").innerHTML = campos || "";
  $("dErro").hidden = true;
  $("dialogoFundo").hidden = false;
  aoConfirmar = confirmar;
  var primeiro = $("dCampos").querySelector("input");
  if (primeiro) { primeiro.focus(); } else { $("dOk").focus(); }
}
function fecharDialogo() { $("dialogoFundo").hidden = true; aoConfirmar = null; }
function erroNoDialogo(t) { $("dErro").textContent = t; $("dErro").hidden = false; $("dOk").disabled = false; }
$("dCancelar").addEventListener("click", fecharDialogo);
$("dialogo").addEventListener("submit", function (e) {
  e.preventDefault();
  if (!aoConfirmar) { fecharDialogo(); return; }
  $("dOk").disabled = true;
  Promise.resolve(aoConfirmar()).then(function (fechar) { $("dOk").disabled = false; if (fechar !== false) { fecharDialogo(); } },
    function (t) { erroNoDialogo(String(t || "não deu certo")); });
});

function dialogoNovo() {
  var opcoes = TAXAS.map(function (t) { return '<option value="' + t[0] + '">' + t[1] + "</option>"; }).join("");
  dialogo("Novo projeto", "Depois de Criar, escolha a pasta (em rede) que vai ser o projeto. O programa não cria pastas sozinho: ele só acrescenta a .carta dentro da que você escolher.",
    "Criar e escolher a pasta…",
    '<label>Nome<input id="campoNome" required autocomplete="off"></label><label>Taxa<select id="campoTaxa">' + opcoes + "</select></label>",
    function () {
      var nome = $("campoNome").value.trim();
      if (!nome) { return Promise.reject("o projeto precisa de um nome"); }
      return postar("/carta/novo", { nome: nome, taxa: $("campoTaxa").value }).then(function (d) {
        if (d.cancelado) { return false; }
        if (!d.ok) { return Promise.reject(d.motivo); }
        return abrirProjeto(d.projeto, true);
      });
    });
}

function pedirAbrir() {
  postar("/carta/abrir", {}).then(function (d) {
    if (d.cancelado) { return; }
    if (!d.ok) { if (projeto) { faixa("erro", "Abrir", esc(d.motivo)); } else { mostrarSemProjeto(d.motivo); } return; }
    abrirProjeto(d.projeto, true);
  });
}
$("vazioNovo").addEventListener("click", dialogoNovo);
$("vazioAbrir").addEventListener("click", pedirAbrir);

$("novaPasta").addEventListener("click", function () {
  if (abertas.length === 1) { dialogoNovaPasta(abertas[0]); }
});

/* ── C2 parte 2: Selecionar ›, remover, mover, as pastas (decisões do autor de 2026-11-13, no plano) ── */

try { $("mostrarReferenciados").checked = localStorage.getItem("carta.referenciados") === "1"; } catch (e) { /* sem armazenamento */ }

// ⭐ Recolher o detalhe (autor, 2026-11-14): a lista ganha a altura toda; o estado fica lembrado entre aberturas.
function detalheAberto(aberto) {
  $("detalhe").hidden = !aberto;
  $("abaDetalhe").setAttribute("aria-expanded", aberto ? "true" : "false");
  $("abaDetalhe").textContent = aberto ? "Ocultar detalhes" : "Mostrar detalhes";
  try { localStorage.setItem("carta.detalhe", aberto ? "1" : "0"); } catch (e) { /* só não lembra */ }
}
try { detalheAberto(localStorage.getItem("carta.detalhe") !== "0"); } catch (e) { detalheAberto(true); }
$("abaDetalhe").addEventListener("click", function () { detalheAberto($("detalhe").hidden); });
$("mostrarReferenciados").addEventListener("change", function () {
  try { localStorage.setItem("carta.referenciados", this.checked ? "1" : "0"); } catch (e) { /* só não lembra */ }
  lerConteudo();
});

function idsSelecionados() { return Object.keys(selecionadas); }
function marcar(ids) { selecionadas = {}; ids.forEach(function (i) { selecionadas[i] = true; }); desenharLista(); }

/* O "Select Relatives" do Avid: entre as linhas VISÍVEIS, o que compõe as selecionadas — só o PRIMEIRO nível (autor). */
var SELECIONAR = {
  tudo: function () { return linhasNaTela.map(function (l) { return l.id; }); },
  nenhum: function () { return []; },
  inverter: function () { return linhasNaTela.filter(function (l) { return !selecionadas[l.id]; }).map(function (l) { return l.id; }); },
  sem_midia: function () { return linhasNaTela.filter(function (l) { return l.status === "err"; }).map(function (l) { return l.id; }); },
  referenciados: function () {
    var quer = {};
    linhasNaTela.forEach(function (l) { if (selecionadas[l.id]) { (l.partes || []).forEach(function (p) { quer[p] = true; }); } });
    var visiveis = linhasNaTela.filter(function (l) { return quer[l.id]; }).map(function (l) { return l.id; });
    var fora = Object.keys(quer).filter(function (p) { return visiveis.indexOf(p) < 0; }).length;
    if (fora) { faixa("", "Selecionar", fora + " referenciado(s) não estão à vista" + ($("mostrarReferenciados").checked ? "" : ": ligue Mostrar clipes referenciados para vê-los")); }
    return visiveis;
  },
  quem_usa: function () {
    return linhasNaTela.filter(function (l) {
      return (l.partes || []).some(function (p) { return selecionadas[p]; });
    }).map(function (l) { return l.id; });
  }
};

function abrirMenuEm(menu, ev, html) {
  var j = $("janela").getBoundingClientRect();
  menu.innerHTML = html; menu.hidden = false;
  var w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = Math.max(4, Math.min(ev.clientX - j.left, j.width - w - 230)) + "px";
  menu.style.top = Math.max(4, Math.min(ev.clientY - j.top, j.height - h - 4)) + "px";
}

$("linhas").addEventListener("contextmenu", function (e) {
  var tr = e.target.closest("tr.linha"); if (!tr) { return; }
  e.preventDefault();
  painelAtivo = "lista";
  var l = linhasNaTela[+tr.dataset.i];
  if (!selecionadas[l.id]) { selecionadas = {}; selecionadas[l.id] = true; desenharLista(); }
  var n = idsSelecionados().length;
  var temItem = linhasNaTela.some(function (x) { return selecionadas[x.id] && x.item; });
  abrirMenuEm($("menuContexto"), e, '<div class="rot">' + (n === 1 ? esc(l.nome) : n + " selecionadas") + "</div>" +
    '<div class="sub"><button type="button">Selecionar</button><div class="menu">' +
      '<button type="button" data-sel="tudo">Tudo</button><button type="button" data-sel="nenhum">Nenhum</button>' +
      '<button type="button" data-sel="inverter">Inverter</button><button type="button" data-sel="sem_midia">Sem mídia nesta máquina</button><hr>' +
      '<button type="button" data-sel="referenciados"' + (temItem ? "" : " disabled") + '>Referenciados<small>o que compõe o selecionado (um nível)</small></button>' +
      '<button type="button" data-sel="quem_usa">Quem usa<small>os subclipes, multicams e nests que usam o selecionado</small></button>' +
    "</div></div>" +
    (nleConectado ? '<button type="button" data-acao="importar"' + (porQueNaoImporta() ? " disabled" : "") + ">Importar para " + NOME_DO_NLE[nleConectado] +
      "<small>" + esc(porQueNaoImporta() || "na bin selecionada, ou na aberta por último") + "</small></button><hr>" : "") +
    '<button type="button" data-acao="mover">Mover para…<small>ou puxe para uma pasta da árvore</small></button><hr>' +
    '<button type="button" class="perigo" data-acao="remover">Remover da vista<small>nenhum arquivo é tocado; quem usa continua usando</small></button>');
});

$("arvore").addEventListener("contextmenu", function (e) {
  var b = e.target.closest(".pasta"); if (!b) { return; }
  e.preventDefault();
  painelAtivo = "arvore";
  var c = b.dataset.caminho;
  abrirMenuEm($("menuContexto"), e, '<div class="rot">' + esc(nomeDaPasta(c)) + "</div>" +
    '<button type="button" data-pasta="nova" data-caminho="' + esc(c) + '">Nova pasta dentro…</button>' +
    (c ? '<button type="button" data-pasta="renomear" data-caminho="' + esc(c) + '">Renomear…</button>' +
         '<button type="button" data-pasta="mover" data-caminho="' + esc(c) + '">Mover para…<small>ou puxe para outra pasta</small></button><hr>' +
         '<button type="button" class="perigo" data-pasta="remover" data-caminho="' + esc(c) + '">Remover pasta<small>o que ela mostra sai da vista; a pasta vai para a Quarentena</small></button>' : ""));
});

$("menuContexto").addEventListener("click", function (e) {
  var b = e.target.closest("button"); if (!b || b.disabled) { return; }
  if (b.parentElement.classList.contains("sub")) { b.parentElement.classList.toggle("aberta"); return; }
  fecharMenus();
  if (b.dataset.sel) { marcar(SELECIONAR[b.dataset.sel]()); return; }
  if (b.dataset.acao === "remover") { pedirRemover(idsSelecionados()); return; }
  if (b.dataset.acao === "mover") { pedirMover(idsSelecionados()); return; }
  if (b.dataset.acao === "importar") { importar(); return; }
  var c = b.dataset.caminho;
  if (b.dataset.pasta === "nova") { dialogoNovaPasta(c); }
  else if (b.dataset.pasta === "renomear") { dialogoRenomearPasta(c); }
  else if (b.dataset.pasta === "mover") { dialogoMoverPasta(c); }
  else if (b.dataset.pasta === "remover") { dialogoRemoverPasta(c); }
});

function depoisDoGesto(texto) {
  if (texto) { faixa("", "Carta", texto); }
  return lerArvore(false).then(lerConteudo);
}

function pedirRemover(ids) {
  if (!ids.length) { return; }
  dialogo("Remover da vista?", ids.length + " item(ns) saem da vista. Nenhum arquivo do disco é tocado, e o que usa estes itens continua usando: com Mostrar clipes referenciados ligado, eles aparecem. Para trazer de volta, mande de novo ou mova a linha revelada para uma pasta.",
    "Remover", "", function () {
      return postar("/carta/remover", comProjeto({ ids: ids })).then(function (d) {
        if (!d.ok) { return Promise.reject(d.motivo); }
        selecionadas = {};
        return depoisDoGesto("Removidos da vista: " + nomes(d.removidos));
      });
    });
  $("dOk").className = "botao perigo";
}

function opcoesDePasta(menos) {
  return pastas.filter(function (p) { return !menos || (p.caminho !== menos && p.caminho.indexOf(menos + "/") !== 0); })
    .map(function (p) { return '<option value="' + esc(p.caminho) + '">' + "  ".repeat(p.nivel) + esc(p.nome) + "</option>"; }).join("");
}

function mover(ids, pasta) {
  return postar("/carta/mover", comProjeto({ ids: ids, pasta: pasta })).then(function (d) {
    if (!d.ok) { return Promise.reject(d.motivo); }
    return depoisDoGesto(d.movidos.length ? "Movidos para " + esc(nomeDaPasta(pasta)) + ": " + nomes(d.movidos) : "Já estavam em " + esc(nomeDaPasta(pasta)));
  });
}

function pedirMover(ids) {
  if (!ids.length) { return; }
  dialogo("Mover para…", "As referências mudam de pasta; a mídia no disco não muda de lugar.", "Mover",
    '<label>Pasta<select id="campoDestino">' + opcoesDePasta() + "</select></label>",
    function () { return mover(ids, $("campoDestino").value); });
}

function trocarCaminho(velho, novo) {
  function troca(c) { return c === velho ? novo : c.indexOf(velho + "/") === 0 ? novo + c.slice(velho.length) : c; }
  abertas = abertas.map(troca);
  ancora = ancora === null ? null : troca(ancora);
}

function dialogoNovaPasta(dentro) {
  dialogo("Nova pasta", "Dentro de " + nomeDaPasta(dentro) + ". O nome é seu; o programa só confere que fica dentro do projeto.", "Criar",
    '<label>Nome<input id="campoPasta" required autocomplete="off"></label>',
    function () {
      return postar("/carta/pasta", comProjeto({ dentro: dentro, nome: $("campoPasta").value })).then(function (d) {
        if (!d.ok) { return Promise.reject(d.motivo); }
        fechadas[dentro] = false;
        abertas = [d.pasta]; ancora = d.pasta; selecionadas = {};
        return lerArvore(false).then(lerConteudo);
      });
    });
}

function dialogoRenomearPasta(c) {
  dialogo("Renomear pasta", "Só a pasta da Carta muda de nome; a mídia e os programas não são tocados.", "Renomear",
    '<label>Nome<input id="campoPasta" required autocomplete="off" value="' + esc(nomeDaPasta(c)) + '"></label>',
    function () {
      return postar("/carta/pasta/renomear", comProjeto({ pasta: c, nome: $("campoPasta").value })).then(function (d) {
        if (!d.ok) { return Promise.reject(d.motivo); }
        trocarCaminho(c, d.pasta);
        return depoisDoGesto("");
      });
    });
  var campo = $("campoPasta"); if (campo) { campo.select(); }
}

function moverPasta(c, para) {
  return postar("/carta/pasta/mover", comProjeto({ pasta: c, para: para })).then(function (d) {
    if (!d.ok) { return Promise.reject(d.motivo); }
    trocarCaminho(c, d.pasta);
    return depoisDoGesto("");
  });
}

function dialogoMoverPasta(c) {
  dialogo("Mover pasta para…", "A pasta vai com tudo o que tem dentro.", "Mover",
    '<label>Para dentro de<select id="campoDestino">' + opcoesDePasta(c) + "</select></label>",
    function () { return moverPasta(c, $("campoDestino").value); });
}

function dialogoRemoverPasta(c) {
  dialogo("Remover a pasta " + nomeDaPasta(c) + "?", "O que ela mostra (e as pastas de dentro) sai da vista, e quem usa continua usando. A pasta vai para a Quarentena do projeto; nenhum arquivo de mídia é tocado.",
    "Remover", "", function () {
      return postar("/carta/pasta/remover", comProjeto({ pasta: c })).then(function (d) {
        if (!d.ok) { return Promise.reject(d.motivo); }
        abertas = abertas.filter(function (x) { return x !== c && x.indexOf(c + "/") !== 0; });
        return depoisDoGesto("Pasta removida: " + esc(nomeDaPasta(c)) + (d.removidos.length ? " · fora da vista: " + nomes(d.removidos) : ""));
      });
    });
  $("dOk").className = "botao perigo";
}

/* ── puxar uma LINHA ou uma PASTA até uma pasta da árvore: movimento do mouse DENTRO da página (nunca o arrasto HTML,
      que no Mac passaria pelo alvo do sistema que recebe o Premiere) ── */
var puxe = null, acabouDePuxar = false;
document.addEventListener("mousedown", function (e) {
  if (e.button !== 0 || e.shiftKey || e.metaKey || e.ctrlKey || !projeto) { return; }
  var tr = e.target.closest("tr.linha"), b = e.target.closest(".pasta");
  if (tr) { puxe = { tipo: "linhas", i: +tr.dataset.i, x: e.clientX, y: e.clientY, ativo: false }; }
  else if (b && b.dataset.caminho && !e.target.closest("[data-tri]")) { puxe = { tipo: "pasta", caminho: b.dataset.caminho, x: e.clientX, y: e.clientY, ativo: false }; }
});
document.addEventListener("mousemove", function (e) {
  if (!puxe) { return; }
  if (!puxe.ativo) {
    if (Math.abs(e.clientX - puxe.x) + Math.abs(e.clientY - puxe.y) < 6) { return; }
    puxe.ativo = true;
    if (puxe.tipo === "linhas") {
      var l = linhasNaTela[puxe.i];
      if (!selecionadas[l.id]) { selecionadas = {}; selecionadas[l.id] = true; desenharLista(); }
      puxe.ids = idsSelecionados();
      puxe.rotulo = puxe.ids.length === 1 ? l.nome : puxe.ids.length + " itens";
    } else { puxe.rotulo = nomeDaPasta(puxe.caminho); }
    var g = document.createElement("div"); g.className = "fantasma"; g.id = "fantasma"; g.textContent = puxe.rotulo;
    document.body.appendChild(g); document.body.classList.add("puxando");
  }
  var fan = $("fantasma"); fan.style.left = (e.clientX + 12) + "px"; fan.style.top = (e.clientY + 10) + "px";
  document.querySelectorAll(".pasta.alvo").forEach(function (p) { p.classList.remove("alvo"); });
  var alvo = document.elementFromPoint(e.clientX, e.clientY);
  var pasta = alvo && alvo.closest(".pasta");
  if (pasta && !(puxe.tipo === "pasta" && (pasta.dataset.caminho === puxe.caminho || pasta.dataset.caminho.indexOf(puxe.caminho + "/") === 0))) {
    pasta.classList.add("alvo"); puxe.destino = pasta.dataset.caminho;
  } else { puxe.destino = null; }
});
document.addEventListener("mouseup", function () {
  if (!puxe) { return; }
  var p = puxe; puxe = null;
  if (!p.ativo) { return; }
  acabouDePuxar = true; setTimeout(function () { acabouDePuxar = false; }, 0);
  var fan = $("fantasma"); if (fan) { fan.remove(); }
  document.body.classList.remove("puxando");
  document.querySelectorAll(".pasta.alvo").forEach(function (x) { x.classList.remove("alvo"); });
  if (p.destino === null || p.destino === undefined) { return; }
  var feito = p.tipo === "linhas" ? mover(p.ids, p.destino) : moverPasta(p.caminho, p.destino);
  feito.catch(function (m) { faixa("erro", "Mover", esc(m)); });
});
// o clique que encerra um puxão não é um clique de seleção
document.addEventListener("click", function (e) { if (acabouDePuxar) { e.stopPropagation(); e.preventDefault(); } }, true);

/* sem miniatura (nada alcança a mídia nesta máquina): a célula fica vazia, sem o ícone de imagem quebrada */
document.addEventListener("error", function (e) { if (e.target && e.target.classList && e.target.classList.contains("mini-q")) { e.target.remove(); } }, true);

/* ── A DECIDIR: empates e homônimos guardados no projeto (`carta/decidir.py`); os outros editores também veem ── */

var casos = [];
function lerDecidir() {
  if (!projeto) { return Promise.resolve(); }
  return postar("/carta/decidir", comProjeto({})).then(function (d) {
    var novos = JSON.stringify(d.ok ? d.casos : []);
    if (novos === ultimosCasos) { return; }
    ultimosCasos = novos;
    casos = d.ok ? d.casos : [];
    $("botaoDecidir").hidden = !casos.length;
    $("nDecidir").textContent = casos.length;
    if (!$("gaveta").hidden) { desenharCasos(); }
    desenharLista();
  }, function () {});
}
/* as referências envolvidas num caso: a bolinha âmbar e a pílula "a decidir" na lista */
function emCaso(id) { return casos.some(function (c) { return (c.candidatos || []).some(function (x) { return x.id === id; }); }); }

function desenharCasos() {
  $("casos").innerHTML = casos.length
    ? "<p>Casos em que o programa não decide sozinho. Ficam guardados no projeto até alguém responder; os outros editores também veem esta lista.</p>" +
      casos.map(function (c) {
        if (c.caso === "timeline") { return casoDeTimeline(c); }
        var cands = (c.candidatos || []).map(function (x) {
          return '<div class="cand">já no projeto: ' + esc(x.nome) + (x.medida !== null && x.medida !== undefined ? " (" + (x.medida > 0 ? "+" : "") + x.medida + ")" : "") + "</div>";
        }).join("");
        var botoes = (c.candidatos || []).map(function (x, k) {
          return '<button type="button" class="botao' + (k === 0 ? " principal" : "") + '" data-caso="' + esc(c.id) + '" data-r="' + esc(x.id) + '">' +
            ((c.candidatos.length === 1) ? "É a mesma" : "É a mesma que " + esc(x.nome)) + "</button>";
        }).join("") + '<button type="button" class="botao" data-caso="' + esc(c.id) + '" data-r="outra">É outra</button>';
        return '<div class="caso"><h4>' + esc(c.nome) + "</h4>" +
          '<div class="porque">' + esc(c.porque) + "</div>" + cands +
          '<div class="cand">chegou: ' + esc(c.arquivo) + "</div>" +
          '<div class="quem">' + esc(c.maquina || "") + " · " + esc((c.ts || "").slice(0, 16).replace("T", " ")) + " · pasta " + esc(caminhoLegivel(c.pasta)) + "</div>" +
          '<div class="acoes">' + botoes + "</div></div>";
      }).join("")
    : "<p>Nada a decidir.</p>";
}

/* a timeline com o mesmo nome e outro conteúdo: atualizar, versionar ou cancelar (`decidir._responder_timeline`) */
function resumoDeTimeline(r) {
  if (!r) { return ""; }
  return r.trilhas + (r.trilhas === 1 ? " trilha · " : " trilhas · ") + r.clipes + (r.clipes === 1 ? " clipe" : " clipes") +
    (r.duracao_q ? " · " + r.duracao_q + " quadros" : "");
}
function casoDeTimeline(c) {
  var b = function (r, rotulo, principal) {
    return '<button type="button" class="botao' + (principal ? " principal" : "") + '" data-caso="' + esc(c.id) + '" data-r="' + r + '">' + rotulo + "</button>";
  };
  return '<div class="caso"><h4>' + esc(c.nome) + "</h4>" +
    '<div class="porque">' + esc(c.porque) + "</div>" +
    '<div class="cand">na Carta (' + esc(c.onde || "") + "): " + esc(resumoDeTimeline(c.antes)) + "</div>" +
    '<div class="cand">chegou: ' + esc(resumoDeTimeline(c.agora)) + "</div>" +
    '<div class="quem">' + esc(c.maquina || "") + " · " + esc((c.ts || "").slice(0, 16).replace("T", " ")) + "</div>" +
    '<div class="acoes">' + b("atualizar", "Atualizar", true) + b("versionar", "Versionar como " + esc(c.versao || "nova versão")) +
    b("cancelar", "Cancelar") + "</div></div>";
}

$("botaoDecidir").addEventListener("click", function () { desenharCasos(); $("gaveta").hidden = false; });
$("fecharGaveta").addEventListener("click", function () { $("gaveta").hidden = true; });
$("casos").addEventListener("click", function (e) {
  var b = e.target.closest("button[data-caso]"); if (!b) { return; }
  b.disabled = true;
  postar("/carta/decidir/responder", comProjeto({ pendente: b.dataset.caso, resposta: b.dataset.r })).then(function (d) {
    if (!d.ok) { b.disabled = false; faixa("erro", "A decidir", esc(d.motivo)); return; }
    faixa("", "A decidir", d.mensagem ? esc(d.mensagem)
      : esc(d.nome) + (d.resposta === "outra" ? ": registrada como outra mídia" : ": ligada à referência que já existia"));
    return lerArvore(false).then(lerConteudo).then(lerDecidir);
  });
});

/* ── o relógio: reler ao voltar à janela e a cada ~10 s com ela à vista (o outro editor manda pela rede) ── */

setInterval(atualizar, ATUALIZAR_MS);
setInterval(lerConexao, 5000);
lerConexao();
window.addEventListener("focus", atualizar);

/* ── a partida ─────────────────────────────────────────────────────────── */

fetch("/saude", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (s) { if (s.versao) { $("versao").textContent = "v" + s.versao; } }, function () {});
carregarRecentes().then(function () {
  var ultima = null;
  try { ultima = localStorage.getItem("carta.raiz"); } catch (e) { ultima = null; }
  var p = recentes.filter(function (x) { return x.raiz === ultima && !x.erro; })[0] || recentes.filter(function (x) { return !x.erro; })[0];
  if (p) { abrirProjeto(p, true); } else { mostrarSemProjeto(""); }
});
