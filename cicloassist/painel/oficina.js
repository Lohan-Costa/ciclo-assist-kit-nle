"use strict";

/* A janela Fluxos e Agentes: a tela de nodes das receitas, sem biblioteca. Referência: `docs/plano/prototipos/janela-de-nodes.html`.
 * ⛔ `textContent` sempre: nomes e descrições vêm de arquivos, e os do editor são dele.
 * ⛔ Arrastar com pointer events, nunca com o drag-and-drop HTML: o soltar difere entre WebView2 e WebKit.
 * ⚠️ Mesmo piso de navegador do painel: sem `??` e sem `?.`. */

var NO_A = 64, NO_L_MIN = 150, VAO_X = 54, VAO_Y = 60, ZOOM_MIN = 0.3, ZOOM_MAX = 2, ZOOM_INICIAL = 0.9;
var SVG = "http://www.w3.org/2000/svg", DIR = { n: [0, -1], s: [0, 1], e: [1, 0], w: [-1, 0] };
var ORIGENS = { fixo: "valor fixo", perguntar: "perguntar ao executar", node: "de outro node", travado: "fixo nesta operação" };
var EM_BREVE = "Ainda não disponível";
var REF_INTEIRA_PARAM = /^\{[a-zA-Z_][a-zA-Z0-9_]*\}$/, REF_INTEIRA_NODE = /^\{[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+\}$/;

var dados = { fluxos: [], agentes: [], erro_nos_agentes: "", pecas: [], programas: {} };
var selecionado = null, aberto = null, quadro = null, abaDireita = "chat", noAberto = null;
/* O chat da janela. `mensagens`: `{de: "eu"|"ele"|"erro"|"proposta", texto, proposta}`. ⭐ É uma lista: trocar de aba redesenha, e nada se perde. */
var respostasDoFormulario = { chave: "", valores: {} }, chaveDaPergunta = "";
var execucao = null, execucaoDispensada = "", relogioDaExecucao = null, chaveDosBotoes = "", fioAberto = null, formExec = null;
var mensagens = [], ocupado = false, atividade = "", noNoChat = null, ultimaDecisao = "", rascunho = "";
var cartoesAbertos = { entrada: true, saida: true };     // recolher vale para os próximos nodes
var centro = document.getElementById("centro"), direita = document.getElementById("direita");

function el(tag, classe, texto) {
  var e = document.createElement(tag);
  if (classe) { e.className = classe; }
  if (texto !== undefined) { e.textContent = texto; }
  return e;
}
function botao(rotulo, classe, acao) {
  var b = el("button", classe, rotulo);
  b.type = "button";
  if (acao) { b.addEventListener("click", acao); } else { b.disabled = true; b.title = EM_BREVE; }
  return b;
}
function eAgente(item) { return dados.agentes.indexOf(item) >= 0; }
function tituloDe(item) { return eAgente(item) ? item.titulo : item.titulo.replace(/\{[^}]*\}\s*/g, "").replace(/\s+/g, " ").trim() || item.nome || "Novo fluxo"; }
function limitar(v, a, b) { return Math.max(a, Math.min(b, v)); }
function pecaDe(op) { return dados.pecas.filter(function (p) { return p.op === op; })[0]; }
function copia(x) { return JSON.parse(JSON.stringify(x)); }

/* ── as listas ── */

function preencherLista(idDaLista, itens, vazio) {
  var caixa = document.getElementById(idDaLista);
  caixa.textContent = "";
  if (!itens.length) { caixa.appendChild(el("div", "vazio", vazio)); return; }
  itens.forEach(function (i) {
    var b = botao(tituloDe(i), "item", function () { selecionado = i; marcarListas(); });
    b.dataItem = i;
    if (i.distintivo) { b.appendChild(el("small", "", i.distintivo)); }
    // ⛔ O clique só troca a classe: redesenhar a lista aqui destruiria o botão antes do segundo clique.
    b.addEventListener("dblclick", function () { abrir(i); });
    caixa.appendChild(b);
  });
}
function desenharListas() {
  preencherLista("listaFluxos", dados.fluxos, "Ainda não há fluxos salvos.");
  preencherLista("listaAgentes", dados.agentes, dados.erro_nos_agentes || "Nenhum agente disponível.");
  marcarListas();
  var restaurar = document.getElementById("restaurarFluxos"), n = dados.excluidos_do_programa || 0;
  restaurar.hidden = !n;
  restaurar.textContent = "Restaurar fluxos do programa (" + n + ")";
}
function marcarListas() {
  Array.prototype.forEach.call(document.querySelectorAll(".item"), function (b) {
    b.className = "item" + (b.dataItem === aberto ? " aberto" : b.dataItem === selecionado ? " selecionado" : "");
  });
}
function abrir(item) {
  aberto = item; selecionado = item; noAberto = null; noNoChat = null; fioAberto = null; formExec = null; abaDireita = "chat";
  marcarListas(); desenharCentro(); desenharDireita();
}

/* ── o grafo em memória ── */

/* ⭐ Com posição gravada de todos os passos, vale a do editor (o gerente de um sync recém-salvo entra perto dele); senão, a organização automática. */
function grafoDe(fluxo) {
  if (!fluxo.grafo) {
    var salvas = fluxo.posicoes;
    var temTodas = !!salvas && fluxo.nos.length > 0 && fluxo.nos.every(function (n) { return salvas.nos[n.id] || n.tipo === "agente"; });
    var nos = fluxo.nos.map(function (n) {
      var p = temTodas && salvas.nos[n.id];
      return { d: copia(n), id: n.id, x: p ? p[0] : 0, y: p ? p[1] : 0, l: NO_L_MIN, semPosicao: temTodas && !p };
    });
    nos.forEach(function (n) {
      if (!n.semPosicao) { return; }
      var alvo = nos.filter(function (o) { return n.id === "agente_" + o.id; })[0];
      if (alvo) { n.x = alvo.x; n.y = alvo.y - NO_A - 40; }
    });
    fluxo.grafo = { fluxo: fluxo, temPosicoes: temTodas, titulo: fluxo.titulo, parametros: copia(fluxo.parametros || {}), nos: nos,
                    fios: fluxo.ligacoes.map(function (f) { return { de: f.de, para: f.para, tipo: f.tipo, campo: f.campo, se: f.se || null, teto: f.teto || 0 }; }),
                    vista: temTodas && salvas.vista ? { x: salvas.vista.x, y: salvas.vista.y, z: salvas.vista.z } : { x: 0, y: 0, z: fluxo.nos.length ? 1 : ZOOM_INICIAL },
                    temVista: temTodas && !!salvas.vista, sel: null, selFio: null, enquadrado: false, timer: null, sujo: false, problemas: null };
  }
  return fluxo.grafo;
}
function noPorId(g, id) { return g.nos.filter(function (n) { return n.id === id; })[0]; }

function posicoesDe(g) {
  var nos = {};
  g.nos.forEach(function (n) { nos[n.id] = [n.x, n.y]; });
  return { fluxo: g.fluxo.nome, nos: nos, vista: g.vista };
}
function postar(url, corpo) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
}
/* Grava um pouco depois do gesto: uma sequência de cliques no zoom vira uma gravação só. ⭐ O relógio é de cada fluxo: abrir outro não cancela esta. */
function guardarPosicoes(g) {
  clearTimeout(g.timer);
  if (!g.fluxo.nome || !g.nos.length) { return; }      // fluxo novo: as posições vão junto do primeiro Salvar
  g.timer = setTimeout(function () {
    postar("/oficina/posicoes", posicoesDe(g))
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } avisarNoQuadro(""); })
      .catch(function () { avisarNoQuadro("Não consegui guardar a posição dos nodes."); });
  }, 300);
}
function avisarNoQuadro(texto) {
  if (!quadro) { return; }
  quadro.andamento.hidden = !texto;
  quadro.andamento.textContent = texto;
}
function marcarSujo() {
  var q = quadro;
  q.g.sujo = true; q.g.problemas = null;
  q.selo.hidden = false; q.btnSalvar.disabled = false; q.btnSalvar.removeAttribute("title");
  desenharProblemas();
  pintarBotaoExecutar();
}

/* ── as linhas ── */

function pontoDe(n, lado) {
  return { n: [n.x + n.l / 2, n.y], s: [n.x + n.l / 2, n.y + NO_A], e: [n.x + n.l, n.y + NO_A / 2], w: [n.x, n.y + NO_A / 2] }[lado];
}
function ladosDe(a, b) {
  if (b.x >= a.x + a.l) { return ["e", "w"]; }
  if (b.y >= a.y + NO_A) { return ["s", "n"]; }
  if (a.y >= b.y + NO_A) { return ["n", "s"]; }
  return ["w", "e"];
}
function curva(p1, l1, p2, l2) {
  var dist = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
  var d = l1 === l2 ? Math.max(90, dist / 3) : Math.max(24, Math.min(80, dist / 2));
  return "M" + p1[0] + " " + p1[1] + " C" + (p1[0] + DIR[l1][0] * d) + " " + (p1[1] + DIR[l1][1] * d) + " " + (p2[0] + DIR[l2][0] * d) + " " + (p2[1] + DIR[l2][1] * d) + " " + p2[0] + " " + p2[1];
}
function fiosAvante(g) { return g.fios.filter(function (f) { return f.tipo === "ordem" && !f.volta; }); }
/* A linha que chega a um node ainda em aberto no caminho é uma volta. A mesma conta do `para_passos`. */
function marcarVoltas(g) {
  var ordem = g.fios.filter(function (f) { return f.tipo === "ordem"; }), abertos = {}, vistos = {};
  ordem.forEach(function (f) { f.volta = false; });
  function visitar(id) {
    vistos[id] = abertos[id] = true;
    ordem.forEach(function (f) {
      if (f.de !== id) { return; }
      if (abertos[f.para]) { f.volta = true; if (!f.teto) { f.teto = 2; } } else if (!vistos[f.para]) { visitar(f.para); }
    });
    abertos[id] = false;
  }
  var inicios = g.nos.filter(function (n) { return !ordem.some(function (f) { return f.para === n.id; }); });
  (inicios.length ? inicios : g.nos.slice(0, 1)).forEach(function (n) { visitar(n.id); });     // ⭐ a volta chega ao começo: o começo é o primeiro node
}
function corDoFio(f) { return quadro.g.selFio === f ? "#ffffff" : f.se || f.volta ? "#d9a95a" : f.tipo === "dado" ? "#4cc4b8" : "#7a7a7a"; }
function rotuloDoSe(se) {
  var campo = se.campo.split(".").slice(1).join(" ").replace(/_/g, " ");
  return se.e === "sim" ? "se " + campo : se.e === "nao" ? "se sem " + campo : "se " + campo + " = " + se.valor;
}

/* ⭐ Só refaz o `d` da linha: ao arrastar, é chamado apenas para as linhas do node que se move. */
function atualizarFio(f) {
  var q = quadro, a = noPorId(q.g, f.de), b = noPorId(q.g, f.para);
  var l = f.volta ? ["s", "s"] : ladosDe(a, b), p1 = pontoDe(a, l[0]), p2 = pontoDe(b, l[1]), d = curva(p1, l[0], p2, l[1]);
  f.caminho.setAttribute("d", d);
  f.pega.setAttribute("d", d);
  if (f.etiqueta) { f.etiqueta.style.left = (p1[0] + p2[0]) / 2 + "px"; f.etiqueta.style.top = (p1[1] + p2[1]) / 2 + (f.volta ? 72 : 0) + "px"; }
}
function criarFios() {
  var q = quadro;
  q.svg.textContent = ""; q.rotulos.textContent = "";
  marcarVoltas(q.g);
  q.g.fios.forEach(function (f) {
    if (!noPorId(q.g, f.de) || !noPorId(q.g, f.para)) { f.caminho = null; return; }
    f.caminho = document.createElementNS(SVG, "path");
    f.caminho.setAttribute("fill", "none"); f.caminho.setAttribute("stroke-width", "1.6");
    f.caminho.setAttribute("stroke", corDoFio(f));
    if (f.se || f.volta) { f.caminho.setAttribute("stroke-dasharray", "5 4"); }
    q.svg.appendChild(f.caminho);
    // A linha visível é fina demais para o mouse: uma cópia larga e invisível recebe o clique.
    f.pega = document.createElementNS(SVG, "path");
    f.pega.setAttribute("fill", "none"); f.pega.setAttribute("stroke", "transparent"); f.pega.setAttribute("stroke-width", "14");
    f.pega.style.pointerEvents = "stroke"; f.pega.style.cursor = "pointer";
    f.pega.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      q.g.sel = null; q.g.selFio = f; fecharMenu(); marcarSel(); pintarFios();
    });
    f.pega.addEventListener("dblclick", function () { fioAberto = f; noAberto = null; formExec = null; abaDireita = "props"; desenharDireita(); });
    q.svg.appendChild(f.pega);
    var etiqueta = [f.volta ? "volta, até " + f.teto + "x" : "", f.se ? rotuloDoSe(f.se) : "", f.se ? "" : f.campo].filter(Boolean).join(" · ");
    f.etiqueta = etiqueta ? el("div", "rotulo", etiqueta) : null;
    if (f.etiqueta) { q.rotulos.appendChild(f.etiqueta); }
    atualizarFio(f);
  });
  marcarPontas();
}
function pintarFios() {
  quadro.g.fios.forEach(function (f) {
    if (!f.caminho) { return; }
    f.caminho.setAttribute("stroke", corDoFio(f));
    f.caminho.setAttribute("stroke-width", quadro.g.selFio === f ? "2.4" : "1.6");
  });
}
/* O primeiro e o último node do caminho, pelas ligações de ordem. Enquanto o fluxo está sendo montado, mais de um pode estar sem ligação, e isso é o que o editor precisa ver. */
function marcarPontas() {
  var q = quadro, ordem = fiosAvante(q.g);
  q.g.nos.forEach(function (n) {
    // ⭐ Quem só tem a linha de volta saindo não encerra o caminho: o fluxo segue por ele.
    var chega = ordem.some(function (f) { return f.para === n.id; }), sai = q.g.fios.some(function (f) { return f.tipo === "ordem" && f.de === n.id; });
    q.els[n.id].classList.toggle("inicio", !chega);
    q.els[n.id].classList.toggle("fim", chega && !sai);
  });
}
/* As linhas de dado saem do que os campos dizem: `{passo.campo}`. */
function refazerLinhasDeDado() {
  var q = quadro, g = q.g;
  g.fios = g.fios.filter(function (f) { return f.tipo === "ordem"; });
  g.fios.forEach(function (f) { f.campo = ""; });
  g.nos.forEach(function (n) {
    var vistos = {}, m, re = /\{([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_]+)[^}]*\}/g, texto = JSON.stringify(n.d.args || {});
    while ((m = re.exec(texto))) {
      var chave = m[1] + "." + m[2];
      if (vistos[chave] || !noPorId(g, m[1])) { continue; }
      vistos[chave] = true;
      var campo = m[2].replace(/_/g, " ");
      var colada = g.fios.filter(function (f) { return f.tipo === "ordem" && f.de === m[1] && f.para === n.id; })[0];
      if (colada) { colada.campo = colada.campo ? colada.campo + ", " + campo : campo; }
      else { g.fios.push({ de: m[1], para: n.id, tipo: "dado", campo: campo }); }
    }
  });
  g.selFio = null;
  criarFios();
}

/* ── o quadro ── */

function aplicarVista() {
  var q = quadro, v = q.g.vista;
  q.plano.style.transform = "translate(" + v.x + "px," + v.y + "px) scale(" + v.z + ")";
  q.tela.style.backgroundSize = 18 * v.z + "px " + 18 * v.z + "px";
  q.tela.style.backgroundPosition = v.x + "px " + v.y + "px";
  q.nivel.textContent = Math.round(v.z * 100) + "%";
}
function mudarZoom(passo) {
  var q = quadro, v = q.g.vista, z = limitar(Math.round((v.z + passo) * 10) / 10, ZOOM_MIN, ZOOM_MAX);
  var cx = q.tela.clientWidth / 2, cy = q.tela.clientHeight / 2;
  v.x = cx - (cx - v.x) * z / v.z; v.y = cy - (cy - v.y) * z / v.z; v.z = z;
  aplicarVista();
  guardarPosicoes(q.g);
}
function marcarSel() {
  var q = quadro;
  Object.keys(q.els).forEach(function (id) { q.els[id].classList.toggle("sel", id === q.g.sel); });
}
function noPlano(e) {
  var r = quadro.tela.getBoundingClientRect(), v = quadro.g.vista;
  return [(e.clientX - r.left - v.x) / v.z, (e.clientY - r.top - v.y) / v.z];
}
function seguir(elemento, e, mover, soltar) {
  elemento.setPointerCapture(e.pointerId);
  function fim(ev) {
    elemento.removeEventListener("pointermove", mover);
    elemento.removeEventListener("pointerup", fim);
    elemento.removeEventListener("pointercancel", fim);
    if (soltar) { soltar(ev); }
  }
  elemento.addEventListener("pointermove", mover);
  elemento.addEventListener("pointerup", fim);
  elemento.addEventListener("pointercancel", fim);
}
function posicionar(n) { var d = quadro.els[n.id]; d.style.left = n.x + "px"; d.style.top = n.y + "px"; }
function fecharMenu() { if (quadro) { quadro.menu.hidden = true; } }

function puxarLigacao(n, lado, porta, e) {
  var q = quadro, inicio = pontoDe(n, lado), oposto = { e: "w", w: "e", n: "s", s: "n" }[lado];
  var linha = document.createElementNS(SVG, "path");
  linha.setAttribute("fill", "none"); linha.setAttribute("stroke", "#4cc4b8"); linha.setAttribute("stroke-width", "1.6");
  q.svg.appendChild(linha);
  function alvoEm(ev) {
    var a = document.elementFromPoint(ev.clientX, ev.clientY);
    a = a && a.closest ? a.closest(".node") : null;
    return a && a !== q.els[n.id] ? a : null;
  }
  function limparAlvo() { Object.keys(q.els).forEach(function (id) { q.els[id].classList.remove("alvo"); }); }
  seguir(porta, e, function (ev) {
    linha.setAttribute("d", curva(inicio, lado, noPlano(ev), oposto));
    limparAlvo();
    var a = alvoEm(ev);
    if (a) { a.classList.add("alvo"); }
  }, function (ev) {
    limparAlvo();
    linha.remove();
    var a = alvoEm(ev), id = a ? a.dataset.id : null;
    if (id && !q.g.fios.some(function (f) { return f.tipo === "ordem" && f.de === n.id && f.para === id; })) {
      q.g.fios.push({ de: n.id, para: id, tipo: "ordem", campo: "" });
      refazerLinhasDeDado();
      marcarSujo();
      if (abaDireita === "props") { desenharDireita(); }
    }
  });
}
// ⛔ A mesma regra de `opera_a_tela` (`grafo_do_fluxo.py`), que faz o preço: aqui porque o node muda na hora em que o editor troca o programa.
function usoDoPiloto(d) {
  if (d.piloto === "so_foco") { return "foco"; }
  if (d.piloto !== "sempre" && d.piloto !== "no_mc") { return ""; }
  var talvez = false;
  if (d.piloto === "no_mc") {
    if (d.programa && d.programa !== "Media Composer") { return ""; }
    talvez = !d.programa;
  }
  if (d.piloto_se) {
    var valor = (d.args || {})[d.piloto_se[0]];
    if (typeof valor === "string" && /\{[^}]+\}/.test(valor)) { talvez = true; } else if (valor !== d.piloto_se[1]) { return ""; }
  }
  return talvez ? "talvez" : "sim";
}
var MARCA_DO_PILOTO = { sim: "piloto", talvez: "piloto, se for o MC", foco: "muda o foco" };
function pintarDetalhe(det, d) {
  var uso = usoDoPiloto(d);
  det.textContent = d.detalhe || "";
  if (uso) {
    if (d.detalhe) { det.appendChild(document.createTextNode(" · ")); }
    det.appendChild(el("span", "marca-piloto " + uso, MARCA_DO_PILOTO[uso]));
  }
  det.hidden = !d.detalhe && !uso;
}
function criarNo(n) {
  var q = quadro, d = el("div", "node" + (n.d.tipo === "agente" || n.d.estilo === "ia" ? " agente" : n.d.estilo === "pergunta" ? " duvida" : ""));
  d.dataset.id = n.id;
  d.appendChild(el("b", "", n.d.rotulo));
  var det = el("small", "");
  d.appendChild(det);
  pintarDetalhe(det, n.d);
  ["n", "e", "s", "w"].forEach(function (lado) {
    var p = el("span", "porta " + lado);
    p.addEventListener("pointerdown", function (e) { e.stopPropagation(); e.preventDefault(); puxarLigacao(n, lado, p, e); });
    d.appendChild(p);
  });
  d.addEventListener("pointerdown", function (e) {
    e.preventDefault();
    q.g.sel = n.id; q.g.selFio = null; marcarSel(); pintarFios(); fecharMenu();
    var ini = noPlano(e), x0 = n.x, y0 = n.y;
    var seus = q.g.fios.filter(function (f) { return f.caminho && (f.de === n.id || f.para === n.id); });
    seguir(d, e, function (ev) {
      var p = noPlano(ev);
      n.x = x0 + p[0] - ini[0]; n.y = y0 + p[1] - ini[1];
      posicionar(n);
      seus.forEach(atualizarFio);
    }, function () {
      if (n.x !== x0 || n.y !== y0) { guardarPosicoes(q.g); }
    });
  });
  d.addEventListener("dblclick", function () { noAberto = n; fioAberto = null; formExec = null; abaDireita = "props"; desenharDireita(); });
  q.els[n.id] = d;
  q.nos.appendChild(d);
}
function idNovo(g, op) {
  var base = op.replace(/[^a-z0-9_]/g, "_").slice(0, 26), id = base, n = 2;
  while (noPorId(g, id) || (g.parametros && g.parametros[id])) { id = base + "_" + n; n++; }
  return id;
}
/* ⭐ Ao lado do último, e nunca em cima de outro: empilhados a 24 px, as alças de um ficavam atrás do outro e a ligação não pegava (teste pilotado, 2026-11-09). */
function lugarDoNovo(g, largura) {
  var q = quadro, v = g.vista, ultimo = g.nos[g.nos.length - 1];
  var x = ultimo ? ultimo.x + ultimo.l + VAO_X : (q.tela.clientWidth / 2 - v.x) / v.z - largura / 2;
  var y = ultimo ? ultimo.y : (q.tela.clientHeight / 2 - v.y) / v.z - NO_A / 2;
  function ocupado() { return g.nos.some(function (o) { return x < o.x + o.l + VAO_X && o.x < x + largura + VAO_X && y < o.y + NO_A + 20 && o.y < y + NO_A + 20; }); }
  while (ocupado()) { y += NO_A + VAO_Y; }
  return [x, y];
}
function adicionarNo(peca) {
  var q = quadro, g = q.g;
  var n = { d: { id: "", tipo: "passo", op: peca.op, rotulo: peca.rotulo, detalhe: "", campos: [], args: {}, programa: peca.programa, saidas: peca.saidas, catalogada: true, estilo: peca.estilo, agente: peca.agente, piloto: peca.piloto, piloto_se: peca.piloto_se, piloto_faz: peca.piloto_faz },
            id: idNovo(g, peca.op), x: 0, y: 0, l: NO_L_MIN };
  n.d.id = n.id;
  g.enquadrado = true;
  criarNo(n);
  n.l = q.els[n.id].offsetWidth;
  var lugar = lugarDoNovo(g, n.l);
  n.x = lugar[0]; n.y = lugar[1];
  g.nos.push(n);
  posicionar(n);
  trazerParaVista(n);
  g.sel = n.id; g.selFio = null; noAberto = n; abaDireita = "props";
  fecharMenu(); marcarSel(); marcarPontas(); marcarSujo(); desenharDireita();
}
function apagarSelecionado() {
  var q = quadro, g = q.g, f = g.selFio;
  if (f) {
    if (f.tipo === "dado") { avisarNoQuadro("Esta linha vem de um campo: mude o campo nas Propriedades do node que recebe."); return; }
    g.fios = g.fios.filter(function (o) { return o !== f; });
    if (fioAberto === f) { fioAberto = null; }
    refazerLinhasDeDado(); marcarSujo();
    if (noAberto) { desenharDireita(); }
    return;
  }
  var id = g.sel;
  if (!id) { return; }
  var n = noPorId(g, id);
  if (n.d.tipo === "agente") { avisarNoQuadro("O agente gerente confere antes do sync e só sai se você pedir um fluxo sem supervisão."); return; }
  [id, "agente_" + id].forEach(function (i) {
    if (!q.els[i]) { return; }
    q.els[i].remove(); delete q.els[i];
    g.nos = g.nos.filter(function (o) { return o.id !== i; });
    g.fios = g.fios.filter(function (o) { return o.de !== i && o.para !== i; });
    if (noAberto && noAberto.id === i) { noAberto = null; }
    if (noNoChat && noNoChat.id === i) { noNoChat = null; }
  });
  g.sel = null;
  refazerLinhasDeDado(); marcarSujo(); marcarSel();
  if (abaDireita === "props") { desenharDireita(); }
}
/* ⭐ O último clique diz do que o editor está falando: com um node marcado no quadro e um fluxo clicado na lista, Delete é sobre a lista. */
var ultimoClique = "";
document.addEventListener("pointerdown", function (e) { ultimoClique = e.target.closest && e.target.closest(".item") ? "lista" : ""; }, true);
document.addEventListener("keydown", function (e) {
  if (e.key !== "Delete" && e.key !== "Backspace") { return; }
  var a = e.target;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable || document.querySelector(".conf-fundo")) { return; }
  if (ultimoClique === "lista" && selecionado) { e.preventDefault(); pedirExclusao(selecionado); return; }
  if (!quadro || !quadro.tela.isConnected || !(quadro.g.sel || quadro.g.selFio)) { return; }
  e.preventDefault();
  apagarSelecionado();
});

/* ── excluir ── */

function fecharJanelaPequena() {
  var f = document.querySelector(".conf-fundo");
  if (f) { f.remove(); }
}
/* `botoes`: `[[rótulo, classe, ação]]`. ⭐ O foco nasce no último, que é sempre o caminho seguro: Enter por reflexo não exclui nada. */
function janelaPequena(titulo, texto, botoes) {
  fecharJanelaPequena();
  var fundo = el("div", "conf-fundo"), j = el("div", "conf-janela"), fila = el("div", "botoes");
  j.setAttribute("role", "alertdialog"); j.setAttribute("aria-modal", "true"); j.setAttribute("aria-label", titulo);
  j.appendChild(el("h2", "", titulo));
  if (texto) { j.appendChild(el("p", "", texto)); }
  var bs = botoes.map(function (b) {
    var x = botao(b[0], "botao " + b[1], function () { fecharJanelaPequena(); if (b[2]) { b[2](); } });
    fila.appendChild(x);
    return x;
  });
  j.appendChild(fila); fundo.appendChild(j);
  fundo.addEventListener("keydown", function (e) {
    e.stopPropagation();
    if (e.key === "Escape") { fecharJanelaPequena(); }
    if (e.key === "Tab") { e.preventDefault(); bs[(bs.indexOf(document.activeElement) + 1) % bs.length].focus(); }
  });
  document.body.appendChild(fundo);
  bs[bs.length - 1].focus();
}
function tirarDaLista(item) {
  var i = dados.fluxos.indexOf(item);
  if (i >= 0) { dados.fluxos.splice(i, 1); }
  if (item.grafo) { clearTimeout(item.grafo.timer); }
  if (selecionado === item) { selecionado = null; }
  if (aberto !== item) { desenharListas(); return; }
  aberto = dados.fluxos[Math.min(i, dados.fluxos.length - 1)] || dados.agentes[0] || null;
  selecionado = aberto; noAberto = null; noNoChat = null; fioAberto = null; formExec = null; abaDireita = "chat";
  desenharListas(); desenharCentro(); desenharDireita();
}
function excluirFluxo(item) {
  if (!item.nome) { tirarDaLista(item); return; }     // nunca foi salvo: só existe na tela
  postar("/oficina/excluir", { nome: item.nome }).then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) { janelaPequena("Não deu para excluir", d.motivo || "O serviço recusou.", [["Entendi", "principal"]]); return; }
    dados.excluidos_do_programa = d.excluidos_do_programa;
    tirarDaLista(item);
  }).catch(function () { janelaPequena("Não deu para excluir", "Não consegui falar com o serviço do Ciclo Assist.", [["Entendi", "principal"]]); });
}
function pedirExclusao(item) {
  if (eAgente(item)) {
    janelaPequena("Este agente não pode ser excluído", item.preso ? tituloDe(item) + " faz parte do programa: " + item.preso : "Por enquanto os agentes só vêm com o programa.", [["Entendi", "principal"]]);
    return;
  }
  janelaPequena("Tem certeza que quer excluir “" + tituloDe(item) + "”?",
    item.origem === "casa" ? "Ele vem com o programa: sai desta lista, e dá para restaurar depois." : "Esta ação não pode ser desfeita.",
    [["Sim", "perigo", function () { excluirFluxo(item); }], ["Cancelar", "", null]]);
}
function iconeLixeira() {
  var s = document.createElementNS(SVG, "svg"), p = document.createElementNS(SVG, "path");
  s.setAttribute("width", "14"); s.setAttribute("height", "14"); s.setAttribute("viewBox", "0 0 16 16"); s.setAttribute("aria-hidden", "true");
  p.setAttribute("d", "M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4M6.7 6.5v4.5M9.3 6.5v4.5");
  p.setAttribute("fill", "none"); p.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-width", "1.3"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round");
  s.appendChild(p);
  return s;
}
function botaoLixeira(item) {
  var rotulo = eAgente(item) ? "Excluir este agente" : "Excluir este fluxo", b = botao("", "botao lixeira", function () { pedirExclusao(item); });
  b.title = rotulo; b.setAttribute("aria-label", rotulo);
  b.appendChild(iconeLixeira());
  return b;
}

function telaDeNodes(g) {
  var tela = el("div", "tela-nodes"), plano = el("div", "plano");
  var svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("width", "1"); svg.setAttribute("height", "1"); svg.setAttribute("aria-hidden", "true");
  var rotulos = el("div"), nos = el("div");
  plano.appendChild(svg); plano.appendChild(rotulos); plano.appendChild(nos);
  tela.appendChild(plano);

  var esq = el("div", "canto esq"), menu = el("div", "menu-mais");
  menu.hidden = true;
  var mais = botao("+", "quadrado", function () { if (menu.hidden) { menuPrincipal(); } menu.hidden = !menu.hidden; });
  mais.setAttribute("aria-label", "Adicionar");
  esq.appendChild(menu); esq.appendChild(mais); tela.appendChild(esq);

  var dir = el("div", "canto dir"), nivel = el("span", "nivel");
  var menos = botao("−", "quadrado", function () { mudarZoom(-0.1); }); menos.setAttribute("aria-label", "Diminuir zoom");
  var maisZ = botao("+", "quadrado", function () { mudarZoom(0.1); }); maisZ.setAttribute("aria-label", "Aumentar zoom");
  dir.appendChild(menos); dir.appendChild(nivel); dir.appendChild(maisZ); tela.appendChild(dir);

  var andamento = el("div", "andamento");
  andamento.hidden = true; tela.appendChild(andamento);
  quadro = { g: g, tela: tela, plano: plano, svg: svg, rotulos: rotulos, nos: nos, nivel: nivel, menu: menu, andamento: andamento, els: {}, selo: null, btnSalvar: null, caixaProblemas: null };
  function menuPrincipal() {
    menu.textContent = "";
    menu.appendChild(botao("Adicionar Node", "", function () {
      menu.textContent = "";
      dados.pecas.forEach(function (p) { menu.appendChild(botao(p.rotulo, "", function () { adicionarNo(p); })); });
    }));
    menu.appendChild(botao("Organizar", "", function () { fecharMenu(); organizarDeNovo(); }));
  }
  g.nos.forEach(criarNo);
  g.nos.forEach(posicionar);

  tela.addEventListener("pointerdown", function (e) {
    if (e.target !== tela && e.target !== plano) { return; }
    e.preventDefault();
    var ini = [e.clientX, e.clientY], x0 = g.vista.x, y0 = g.vista.y, moveu = false;
    tela.classList.add("movendo"); menu.hidden = true;
    seguir(tela, e, function (ev) {
      if (Math.abs(ev.clientX - ini[0]) + Math.abs(ev.clientY - ini[1]) > 3) { moveu = true; }
      g.vista.x = x0 + ev.clientX - ini[0]; g.vista.y = y0 + ev.clientY - ini[1];
      aplicarVista();
    }, function () {
      tela.classList.remove("movendo");
      if (moveu) { guardarPosicoes(g); } else { g.sel = null; g.selFio = null; marcarSel(); pintarFios(); }
    });
  });
  aplicarVista(); marcarSel();
  return tela;
}

/* Na ordem do caminho, quando há um; os soltos vão por último. */
function naOrdemDoCaminho(g) {
  var ordem = fiosAvante(g), saida = [], atual;
  g.nos.filter(function (n) { return !ordem.some(function (f) { return f.para === n.id; }); }).forEach(function (inicio) {
    atual = inicio;
    while (atual && saida.indexOf(atual) < 0) {
      saida.push(atual);
      var f = ordem.filter(function (o) { return o.de === atual.id; })[0];
      atual = f ? noPorId(g, f.para) : null;
    }
  });
  return saida.concat(g.nos.filter(function (n) { return saida.indexOf(n) < 0; }));
}

/* ⭐ Em linhas, da esquerda para a direita, com o número de colunas que dá o maior zoom. Depende da largura real de cada node. */
function organizarEmColunas(g, lista, ordem) {
  // ⭐ A coluna é o caminho mais longo até o node: o último de um ramo fica sempre à direita de quem vem antes dele.
  var nivel = {}, colunas = [], volta, x = 0;
  lista.forEach(function (n) { nivel[n.id] = 0; });
  for (volta = 0; volta < lista.length; volta++) {     // o teto: um fluxo em edição pode ter volta
    ordem.forEach(function (f) { if (nivel[f.para] <= nivel[f.de]) { nivel[f.para] = nivel[f.de] + 1; } });
  }
  lista.forEach(function (n) { (colunas[nivel[n.id]] = colunas[nivel[n.id]] || []).push(n); });
  var maisAlta = colunas.reduce(function (m, c) { return Math.max(m, c ? c.length : 0); }, 0);
  colunas.forEach(function (c) {
    var topo = (maisAlta - c.length) * (NO_A + VAO_Y) / 2;
    c.forEach(function (n, i) { n.x = x; n.y = topo + i * (NO_A + VAO_Y); });
    x += Math.max.apply(null, c.map(function (n) { return n.l; })) + 104;     // mais que o VAO_X: a etiqueta da condição mora neste vão
  });
}
function organizar(g, largura, altura) {
  var lista = naOrdemDoCaminho(g), ordem = fiosAvante(g);
  if (lista.some(function (n) { return ordem.filter(function (f) { return f.de === n.id; }).length > 1 || ordem.filter(function (f) { return f.para === n.id; }).length > 1; })) {
    organizarEmColunas(g, lista, ordem);
    return;
  }
  function colunas(c) {
    var ls = [];
    lista.forEach(function (n, i) { ls[i % c] = Math.max(ls[i % c] || 0, n.l); });
    return ls;
  }
  function medida(c) {
    var w = colunas(c).reduce(function (s, l) { return s + l; }, 0) + (Math.min(c, lista.length) - 1) * VAO_X;
    var h = Math.ceil(lista.length / c) * (NO_A + VAO_Y) - VAO_Y;
    return Math.min(largura / w, altura / h);
  }
  // ⭐ Acima do zoom inicial não há ganho, e o fluxo se lê melhor deitado: entre zooms quase iguais, mais colunas (medido: 2 colunas por 2% de zoom jogavam a linha de dado por trás de um node).
  var maior = 0, melhor = 1, c;
  for (c = 1; c <= lista.length; c++) { maior = Math.max(maior, Math.min(ZOOM_INICIAL, medida(c))); }
  for (c = 1; c <= lista.length; c++) { if (Math.min(ZOOM_INICIAL, medida(c)) >= maior * 0.9) { melhor = c; } }
  var ls = colunas(melhor), xs = [0];
  ls.forEach(function (l, i) { xs[i + 1] = xs[i] + l + VAO_X; });
  lista.forEach(function (n, i) { n.x = xs[i % melhor]; n.y = Math.floor(i / melhor) * (NO_A + VAO_Y); });
}
function enquadrar(organizando) {
  var q = quadro, g = q.g, folga = 24, baixo = 50;
  var W = q.tela.clientWidth - folga * 2, H = q.tela.clientHeight - folga - baixo;
  marcarVoltas(g);     // ⚠️ antes de organizar: a linha de volta não conta para a coluna
  if (organizando) { organizar(g, W, H); g.nos.forEach(posicionar); }
  var x0 = Math.min.apply(null, g.nos.map(function (n) { return n.x; })), y0 = Math.min.apply(null, g.nos.map(function (n) { return n.y; }));
  var x1 = Math.max.apply(null, g.nos.map(function (n) { return n.x + n.l; })), y1 = Math.max.apply(null, g.nos.map(function (n) { return n.y + NO_A; }));
  var z = limitar(Math.floor(Math.min(W / (x1 - x0), H / (y1 - y0)) * 10) / 10, ZOOM_MIN, ZOOM_INICIAL);
  g.vista = { x: (q.tela.clientWidth - (x1 - x0) * z) / 2 - x0 * z, y: (q.tela.clientHeight - baixo - (y1 - y0) * z) / 2 + folga / 4 - y0 * z, z: z };
  aplicarVista();
}
function organizarDeNovo() {
  if (!quadro.g.nos.length) { return; }
  enquadrar(true);
  criarFios();
  guardarPosicoes(quadro.g);
}
/* Na primeira abertura, o fluxo inteiro cabe na tela; depois vale o zoom e a posição que o editor deixou. */
function enquadrarNaPrimeiraVez() {
  var q = quadro, g = q.g;
  g.nos.forEach(function (n) { n.l = q.els[n.id].offsetWidth; });
  if (g.enquadrado || !g.nos.length) { return; }
  g.enquadrado = true;
  if (!g.temVista) { enquadrar(!g.temPosicoes); }
}

function editorDeTexto(agente) {
  var ed = el("div", "editor");
  agente.texto.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n").forEach(function (t, i) {
    var l = el("div", "linha");
    l.appendChild(el("span", "num", String(i + 1)));
    l.appendChild(el("span", "txt", t));
    ed.appendChild(l);
  });
  return ed;
}

/* ── o cabeçalho, Conferir e Salvar ── */

function editarTitulo(g, h1) {
  var campo = document.createElement("input");
  campo.className = "titulo-input"; campo.value = g.titulo; campo.setAttribute("aria-label", "Nome do fluxo");
  h1.replaceWith(campo);
  campo.focus(); campo.select();
  var feito = false;
  function fim(gravar) {
    if (feito) { return; }
    feito = true;
    if (gravar && campo.value.trim() && campo.value.trim() !== g.titulo) {
      g.titulo = g.fluxo.titulo = campo.value.trim();
      marcarSujo();
      desenharListas();
    }
    h1.textContent = tituloDe(g.fluxo); h1.title = tituloDe(g.fluxo);
    campo.replaceWith(h1);
  }
  campo.addEventListener("keydown", function (e) {
    e.stopPropagation();
    if (e.key === "Enter") { fim(true); } else if (e.key === "Escape") { fim(false); }
  });
  campo.addEventListener("blur", function () { fim(true); });
}
function pedidoDe(g) {
  return { nome: g.fluxo.nome, titulo: g.titulo, parametros: g.parametros,
           nos: g.nos.map(function (n) { return { id: n.id, tipo: n.d.tipo, op: n.d.op, rotulo: n.d.rotulo, args: n.d.args }; }),
           ligacoes: g.fios.filter(function (f) { return f.tipo === "ordem"; }).map(function (f) { var x = { de: f.de, para: f.para }; if (f.se) { x.se = f.se; } if (f.volta) { x.teto = f.teto; } return x; }) };
}
function desenharProblemas() {
  var q = quadro, p = q.g.problemas, caixa = q.caixaProblemas;
  caixa.textContent = "";
  caixa.hidden = p === null;
  if (p === null) { return; }
  var avisos = q.g.avisos || [];
  caixa.className = "problemas" + (p.length || avisos.length ? "" : " certo");
  if (!p.length) { caixa.appendChild(el("div", "", avisos.length ? "Pode ser salvo, mas confira:" : "Tudo certo: este fluxo pode ser salvo.")); }
  p.concat(avisos).forEach(function (t) { caixa.appendChild(el("div", "", t)); });
}
function conferir() {
  var g = quadro.g;
  postar("/oficina/conferir", pedidoDe(g))
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(function (d) { g.problemas = d.problemas; g.avisos = d.avisos || []; if (quadro && quadro.g === g) { desenharProblemas(); } })
    .catch(function (e) { g.problemas = ["Não consegui conferir (" + e.message + ")."]; if (quadro && quadro.g === g) { desenharProblemas(); } });
}
function salvar() {
  var g = quadro.g;
  clearTimeout(g.timer);
  postar("/oficina/salvar", pedidoDe(g))
    .then(function (r) { return r.json().then(function (d) { return { http: r.status, d: d }; }); })
    .then(function (res) {
      if (!res.d.ok) { throw { problemas: res.d.problemas || ["HTTP " + res.http] }; }
      var pos = posicoesDe(g);
      pos.fluxo = res.d.nome;
      return postar("/oficina/posicoes", pos).then(function () { return carregar(res.d.nome); });
    })
    .catch(function (e) {
      g.problemas = e.problemas || ["Não consegui salvar (" + e.message + ")."];
      if (quadro && quadro.g === g) { desenharProblemas(); }
    });
}

function desenharCentro() {
  quadro = null;
  centro.textContent = "";
  if (!aberto) { centro.appendChild(el("div", "vazio", "Nada para abrir ainda.")); return; }
  var cab = el("div", "cabeca"), ag = eAgente(aberto), g = ag ? null : grafoDe(aberto);
  var titulo = el("h1", "", tituloDe(aberto));
  titulo.title = ag ? tituloDe(aberto) : tituloDe(aberto) + " · clique duas vezes para renomear";
  cab.appendChild(titulo);
  if (ag) { cab.appendChild(el("span", "selo", "somente leitura")); }
  var selo = el("span", "selo sujo", "não salvo");
  selo.hidden = ag || !g.sujo;
  if (!ag) { cab.appendChild(selo); }
  cab.appendChild(el("span", "espaco"));
  var salvarBtn = null;
  if (ag) {
    cab.appendChild(botao("Editar", "botao principal"));
  } else {
    cab.appendChild(botao("Conferir", "botao", conferir));
    var executarBtn = botao("Executar fluxo", "botao", abrirFormulario);
    cab.appendChild(executarBtn);
    var compartilhar = botao("Compartilhar", "botao", exportarFluxo);
    compartilhar.disabled = g.sujo || !g.fluxo.nome;
    compartilhar.title = compartilhar.disabled ? "Salve o fluxo antes de compartilhar" : "Grava o fluxo num arquivo, para levar a outra máquina";
    cab.appendChild(compartilhar);
    salvarBtn = botao("Salvar fluxo", "botao principal", salvar);
    salvarBtn.disabled = !g.sujo;
    cab.appendChild(salvarBtn);
  }
  cab.appendChild(botaoLixeira(aberto));
  centro.appendChild(cab);
  (aberto.problemas || []).forEach(function (p) { centro.appendChild(el("div", "aviso", p)); });
  if (ag) { centro.appendChild(editorDeTexto(aberto)); return; }
  titulo.addEventListener("dblclick", function () { editarTitulo(g, titulo); });
  var caixa = el("div", "problemas");
  caixa.hidden = true;
  centro.appendChild(caixa);
  var faixa = el("div", "execucao");
  faixa.hidden = true;
  centro.appendChild(faixa);
  chaveDosBotoes = "";
  centro.appendChild(telaDeNodes(g));
  quadro.selo = selo; quadro.btnSalvar = salvarBtn; quadro.caixaProblemas = caixa; quadro.btnExecutar = executarBtn; quadro.faixa = faixa;
  enquadrarNaPrimeiraVez();     // ⚠️ depois de estar no DOM: é preciso medir os nodes e a tela
  criarFios();
  desenharProblemas();
  pintarExecucao();
}

/* ── o painel direito ── */

function trazerParaVista(alvo) {
  var q = quadro, v = q.g.vista;
  var x = alvo.x * v.z + v.x, y = alvo.y * v.z + v.y, W = q.tela.clientWidth, H = q.tela.clientHeight;
  var dx = x < 20 ? 20 - x : Math.min(0, W - 20 - x - alvo.l * v.z), dy = y < 20 ? 20 - y : Math.min(0, H - 70 - y - NO_A * v.z);
  // ⭐ Anda só o que falta: centrar no alvo tirava da tela os nodes que o editor acabou de pôr.
  if (dx || dy) { v.x += dx; v.y += dy; aplicarVista(); }
}
function irParaNo(alvo) {
  noAberto = alvo; quadro.g.sel = alvo.id; marcarSel();
  trazerParaVista(alvo);
  desenharDireita();
}
function setaDoCartao() {
  var seta = document.createElementNS(SVG, "svg"), ponta = document.createElementNS(SVG, "path");
  seta.setAttribute("width", "9"); seta.setAttribute("height", "9"); seta.setAttribute("viewBox", "0 0 9 9"); seta.setAttribute("aria-hidden", "true");
  ponta.setAttribute("d", "M2.5 1 7 4.5 2.5 8"); ponta.setAttribute("fill", "none"); ponta.setAttribute("stroke", "#b8b8b8"); ponta.setAttribute("stroke-width", "1.5");
  seta.appendChild(ponta);
  return seta;
}
function cartaoDeLigacoes(tipo, n) {
  var entra = tipo === "entrada", g = quadro.g, caixa = el("div", "cartao-lig");
  var fios = g.fios.filter(function (f) { return (entra ? f.para : f.de) === n.id && noPorId(g, entra ? f.de : f.para); });
  var cab = botao("", "", function () { cartoesAbertos[tipo] = !cartoesAbertos[tipo]; desenharDireita(); });
  cab.appendChild(setaDoCartao());
  cab.appendChild(el("span", "", entra ? "Recebe" : "Entrega"));
  cab.appendChild(el("span", "conta", fios.length ? fios.length + (fios.length > 1 ? " ligações" : " ligação") : "nenhuma"));
  cab.setAttribute("aria-expanded", cartoesAbertos[tipo] ? "true" : "false");
  caixa.appendChild(cab);
  if (cartoesAbertos[tipo]) {
    var corpo = el("div", "lig-corpo");
    if (!entra && n.d.saidas.length) { corpo.appendChild(el("div", "lig-nota", "Entrega: " + n.d.saidas.join(", "))); }
    if (!fios.length) { corpo.appendChild(el("div", "lig-nota", entra ? "Nada chega aqui: este node inicia o caminho." : "Nada sai daqui: este node encerra o caminho.")); }
    fios.forEach(function (f) {
      var outro = noPorId(g, entra ? f.de : f.para), b = botao("", "ligacao", function () {});
      b.title = "Clique duas vezes para ir até este node";
      b.appendChild(el("b", "", outro.d.rotulo));
      b.appendChild(el("small", "", f.campo || (entra ? "vem antes" : "vem depois")));
      b.addEventListener("dblclick", function () { irParaNo(outro); });
      corpo.appendChild(b);
    });
    caixa.appendChild(corpo);
  }
  return caixa;
}
function campoSoLeitura(c) {
  var caixa = el("div", "campo"), topo = el("div", "campo-topo");
  topo.appendChild(el("span", "", c.nome));
  topo.appendChild(el("span", "origem", ORIGENS[c.origem] || ""));
  caixa.appendChild(topo);
  caixa.appendChild(el("div", "valor", c.texto));
  return caixa;
}
function origemDe(valor) {
  if (valor === undefined) { return "nao"; }
  if (typeof valor === "string" && REF_INTEIRA_NODE.test(valor)) { return "node"; }
  if (typeof valor === "string" && REF_INTEIRA_PARAM.test(valor)) { return "perguntar"; }
  return "fixo";
}
function tipoDoParametro(c) {
  if (c.opcoes.length) { return { tipo: "escolha", opcoes: c.opcoes }; }
  if (c.tipo === "boolean") { return { tipo: "sim_nao" }; }
  if (c.tipo === "number" || c.tipo === "integer") { return { tipo: "numero" }; }
  if (/pasta|destino|diretor/i.test(c.nome)) { return { tipo: "pasta" }; }
  if (/arquivo|timeline|referencia/i.test(c.nome)) { return { tipo: "arquivo" }; }
  return { tipo: "texto" };
}
function fontesDeDado(g, n) {
  var saida = [];
  naOrdemDoCaminho(g).forEach(function (o) {
    if (o === n || o.d.tipo === "agente") { return; }
    var peca = pecaDe(o.d.op);
    (peca ? peca.saidas : []).forEach(function (campo) { saida.push({ valor: "{" + o.id + "." + campo + "}", rotulo: o.d.rotulo + " · " + campo.replace(/_/g, " ") }); });
  });
  return saida;
}
function opcao(sel, valor, rotulo) { var o = el("option", "", rotulo); o.value = valor; sel.appendChild(o); }
function aoMudarCampo(n, c, valor) {
  if (valor === undefined) { delete n.d.args[c.nome]; } else { n.d.args[c.nome] = valor; }
  var peca = pecaDe(n.d.op);
  if (peca && peca.programa_vem_do_argumento && c.nome === "programa") {
    n.d.detalhe = n.d.programa = dados.programas[String(valor || "").toLowerCase()] || "";
  }
  if (n.d.piloto) {
    pintarDetalhe(quadro.els[n.id].querySelector("small"), n.d);
    n.l = quadro.els[n.id].offsetWidth;
  }
  refazerLinhasDeDado();
  marcarSujo();
}
function entradaDoValorFixo(n, c, valor) {
  var entrada;
  if (c.opcoes.length || c.tipo === "boolean") {
    entrada = document.createElement("select"); entrada.className = "entrada";
    if (c.tipo === "boolean") { opcao(entrada, "true", "sim"); opcao(entrada, "false", "não"); entrada.value = String(valor === true); }
    else {
      opcao(entrada, "", "Escolha…");
      c.opcoes.forEach(function (o) { opcao(entrada, String(o), dados.programas[o] || String(o)); });
      entrada.value = valor === undefined ? "" : String(valor);
    }
    entrada.addEventListener("change", function () { aoMudarCampo(n, c, c.tipo === "boolean" ? entrada.value === "true" : entrada.value); });
    return entrada;
  }
  if (c.tipo === "array" || c.tipo === "object") {
    entrada = document.createElement("textarea"); entrada.className = "entrada"; entrada.spellcheck = false;
    entrada.value = valor === undefined || valor === "" ? "" : JSON.stringify(valor, null, 1);
    entrada.addEventListener("change", function () {
      if (!entrada.value.trim()) { entrada.classList.remove("ruim"); aoMudarCampo(n, c, undefined); return; }
      try { var v = JSON.parse(entrada.value); entrada.classList.remove("ruim"); aoMudarCampo(n, c, v); }
      catch (e) { entrada.classList.add("ruim"); }
    });
    return entrada;
  }
  entrada = document.createElement("input"); entrada.className = "entrada"; entrada.spellcheck = false;
  entrada.value = valor === undefined ? "" : String(valor);
  if (c.tipo === "number" || c.tipo === "integer") { entrada.type = "number"; }
  entrada.addEventListener("change", function () {
    var v = entrada.value;
    if (v === "" && !c.obrigatorio) { aoMudarCampo(n, c, undefined); return; }
    aoMudarCampo(n, c, entrada.type === "number" && v !== "" ? Number(v) : v);
  });
  return entrada;
}
function parametroNovo(g, c) {
  var base = c.nome.replace(/[^a-z0-9_]/g, "_"), k = base, i = 2;
  while (g.parametros[k] || noPorId(g, k)) { k = base + "_" + i; i++; }
  g.parametros[k] = Object.assign({ rotulo: c.rotulo }, tipoDoParametro(c));
  return k;
}
function campoEditavel(n, c) {
  var g = quadro.g, caixa = el("div", "campo"), topo = el("div", "campo-topo"), valor = n.d.args[c.nome], origem = origemDe(valor);
  var rotulo = el("span", "", c.rotulo + (c.obrigatorio ? " *" : ""));
  rotulo.title = c.descricao;
  topo.appendChild(rotulo);
  var sel = document.createElement("select");
  sel.setAttribute("aria-label", "De onde vem: " + c.rotulo);
  if (!c.obrigatorio) { opcao(sel, "nao", "Não usar"); }
  opcao(sel, "fixo", "Valor fixo"); opcao(sel, "perguntar", "Perguntar ao executar"); opcao(sel, "node", "De outro node");
  sel.value = origem === "nao" && c.obrigatorio ? "fixo" : origem;
  sel.addEventListener("change", function () {
    var v;
    if (sel.value === "fixo") { v = c.tipo === "boolean" ? false : c.tipo === "array" || c.tipo === "object" ? undefined : ""; }
    else if (sel.value === "perguntar") { v = "{" + parametroNovo(g, c) + "}"; }
    else if (sel.value === "node") { var f = fontesDeDado(g, n)[0]; v = f ? f.valor : undefined; if (!f) { sel.value = "fixo"; v = ""; } }
    aoMudarCampo(n, c, v);
    desenharDireita();
  });
  topo.appendChild(sel);
  caixa.appendChild(topo);
  if (sel.value === "fixo") {
    caixa.appendChild(entradaDoValorFixo(n, c, valor));
    if (typeof valor === "string" && valor.indexOf("{") >= 0) { caixa.appendChild(el("p", "nota", "O que está entre chaves é preenchido ao executar.")); }
  } else if (sel.value === "perguntar") {
    var chave = String(valor).slice(1, -1), spec = g.parametros[chave] || {};
    var qual = document.createElement("select"); qual.className = "entrada"; qual.setAttribute("aria-label", "Qual pergunta");
    Object.keys(g.parametros).forEach(function (k) { opcao(qual, k, g.parametros[k].rotulo || k); });
    if (!g.parametros[chave]) { opcao(qual, chave, chave.replace(/_/g, " ")); }
    qual.value = chave;
    qual.addEventListener("change", function () { aoMudarCampo(n, c, "{" + qual.value + "}"); desenharDireita(); });
    caixa.appendChild(qual);
    var texto = document.createElement("input"); texto.className = "entrada"; texto.value = spec.rotulo || ""; texto.placeholder = "O que perguntar"; texto.setAttribute("aria-label", "O que perguntar");
    texto.addEventListener("change", function () {
      if (!g.parametros[chave]) { g.parametros[chave] = { tipo: "texto" }; }
      g.parametros[chave].rotulo = texto.value; marcarSujo();
    });
    caixa.appendChild(texto);
  } else if (sel.value === "node") {
    var fontes = fontesDeDado(g, n), s2 = document.createElement("select"); s2.className = "entrada"; s2.setAttribute("aria-label", "Vem de qual node");
    fontes.forEach(function (f) { opcao(s2, f.valor, f.rotulo); });
    if (!fontes.some(function (f) { return f.valor === valor; })) { opcao(s2, String(valor), String(valor).slice(1, -1).replace(/_/g, " ")); }
    s2.value = valor;
    s2.addEventListener("change", function () { aoMudarCampo(n, c, s2.value); });
    caixa.appendChild(s2);
  }
  return caixa;
}
function painelDoNo() {
  var p = el("div", "props"), n = noAberto;
  if (fioAberto) { return painelDaLinha(fioAberto); }
  if (!n) { p.appendChild(el("p", "vazio", "Clique duas vezes em um node para ver os parâmetros dele.")); return p; }
  var peca = pecaDe(n.d.op);
  p.appendChild(cartaoDeLigacoes("entrada", n));
  p.appendChild(el("h3", "", n.d.rotulo));
  if (n.d.programa) { p.appendChild(el("p", "nota", "Ocupa o " + n.d.programa + " enquanto roda.")); }
  var usoPiloto = usoDoPiloto(n.d);
  if (usoPiloto) { p.appendChild(el("p", "nota nota-piloto", n.d.piloto_faz)); }
  if (usoPiloto === "sim" || usoPiloto === "talvez") {
    var doPiloto = dados.agentes.filter(function (a) { return a.nome === "agente-do-piloto"; })[0];
    if (doPiloto) {
      p.appendChild(el("p", "nota", doPiloto.descricao));
      p.appendChild(botao("Abrir agente do piloto", "botao", function () { abrir(doPiloto); }));
    }
  }
  if (n.d.tipo === "agente") {
    var agente = dados.agentes.filter(function (a) { return a.nome === n.d.agente; })[0];
    if (agente) {
      p.appendChild(el("p", "nota", agente.descricao));
      p.appendChild(botao("Abrir agente", "botao", function () { abrir(agente); }));
    }
  } else if (peca) {
    if (n.d.agente) {
      var deste = dados.agentes.filter(function (a) { return a.nome === n.d.agente; })[0];
      if (deste) { p.appendChild(botao("Abrir agente", "botao", function () { abrir(deste); })); }
    }
    peca.campos.forEach(function (c) { p.appendChild(campoEditavel(n, c)); });
    peca.travados.forEach(function (c) { p.appendChild(campoSoLeitura({ nome: c.nome, texto: c.texto, origem: "travado" })); });
    if (!peca.campos.length && !peca.travados.length) { p.appendChild(el("p", "nota", "Este node não tem parâmetros.")); }
  } else {
    p.appendChild(el("p", "nota", "Esta operação ainda não tem ficha: o programa que ela ocupa e o que ela entrega não estão declarados."));
    n.d.campos.forEach(function (c) { p.appendChild(campoSoLeitura(c)); });
  }
  if (n.d.tipo !== "agente") {
    p.appendChild(botao("Ajustar no chat", "botao", function () {
      noNoChat = n; abaDireita = "chat"; desenharDireita();
      var e = document.getElementById("mensagem");
      if (e) { e.focus(); }
    }));
  }
  p.appendChild(cartaoDeLigacoes("saida", n));
  return p;
}
function painelDaLinha(f) {
  var g = quadro.g, p = el("div", "props"), a = noPorId(g, f.de), b = noPorId(g, f.para);
  p.appendChild(el("h3", "", (a ? a.d.rotulo : f.de) + " → " + (b ? b.d.rotulo : f.para)));
  if (f.tipo === "dado") { p.appendChild(el("p", "nota", "Esta linha leva o dado " + f.campo + ". Ela vem do campo do node que recebe.")); return p; }
  if (f.volta) {
    var caixaTeto = el("div", "campo"), topoTeto = el("div", "campo-topo"), teto = document.createElement("select");
    topoTeto.appendChild(el("span", "", "Voltar no máximo"));
    teto.setAttribute("aria-label", "Voltar no máximo");
    [1, 2, 3, 4, 5].forEach(function (n) { opcao(teto, String(n), n + (n > 1 ? " vezes" : " vez")); });
    teto.value = String(f.teto);
    teto.addEventListener("change", function () { f.teto = Number(teto.value); criarFios(); marcarSujo(); });
    topoTeto.appendChild(teto); caixaTeto.appendChild(topoTeto); p.appendChild(caixaTeto);
    p.appendChild(el("p", "nota", "Repete daquele node até este. Na última vez sem resolver, o fluxo para e pergunta o que fazer."));
  }
  var peca = a ? pecaDe(a.d.op) : null, saidas = peca ? peca.saidas : [];
  if (!saidas.length) {
    p.appendChild(el("p", "nota", a && a.d.tipo === "agente" ? "A linha que sai do agente gerente sempre segue." : "Este node não declara o que entrega, então a linha sempre segue."));
    return p;
  }
  var campo = el("div", "campo"), topo = el("div", "campo-topo"), sel = document.createElement("select");
  topo.appendChild(el("span", "", "Quando seguir"));
  sel.setAttribute("aria-label", "Quando seguir");
  opcao(sel, "sempre", "Sempre"); opcao(sel, "se", "Só quando…");
  sel.value = f.se ? "se" : "sempre";
  topo.appendChild(sel); campo.appendChild(topo); p.appendChild(campo);
  function aplicar() { criarFios(); marcarSujo(); }
  sel.addEventListener("change", function () {
    f.se = sel.value === "se" ? { campo: a.id + "." + saidas[0], e: "sim" } : null;
    aplicar(); desenharDireita();
  });
  if (f.se) {
    var qual = document.createElement("select"); qual.className = "entrada"; qual.setAttribute("aria-label", "Qual saída");
    saidas.forEach(function (s) { opcao(qual, a.id + "." + s, s.replace(/_/g, " ")); });
    qual.value = f.se.campo;
    qual.addEventListener("change", function () { f.se.campo = qual.value; aplicar(); });
    campo.appendChild(qual);
    var como = document.createElement("select"); como.className = "entrada"; como.setAttribute("aria-label", "Como comparar");
    opcao(como, "sim", "tem conteúdo ou é verdadeiro"); opcao(como, "nao", "está vazio ou é falso"); opcao(como, "igual", "é igual a");
    como.value = f.se.e;
    como.addEventListener("change", function () { f.se.e = como.value; if (como.value === "igual") { f.se.valor = f.se.valor || ""; } else { delete f.se.valor; } aplicar(); desenharDireita(); });
    campo.appendChild(como);
    if (f.se.e === "igual") {
      var valor = document.createElement("input"); valor.className = "entrada"; valor.value = f.se.valor; valor.setAttribute("aria-label", "Valor");
      valor.addEventListener("change", function () { f.se.valor = valor.value; aplicar(); });
      campo.appendChild(valor);
    }
    p.appendChild(el("p", "nota", "Se não for assim, este caminho fica de fora e o fluxo segue pelos outros."));
  }
  return p;
}
function desenharRespostas(passo) {
  var r = respostasDoFormulario, chave = execucao.id + "/" + passo.id + "/" + passo.tentativas, caixa = el("div", "form-exec");
  if (r.chave !== chave) { r.chave = chave; r.valores = {}; r.erro = ""; }
  caixa.appendChild(el("h3", "", passo.saida.titulo || "O fluxo precisa de uma resposta"));
  (passo.saida.perguntas || []).forEach(function (p, i) {
    var item = el("div", "perg"), area = document.createElement("textarea");
    item.appendChild(el("span", "", p.texto));
    area.value = r.valores[i] || ""; area.setAttribute("aria-label", p.texto);
    area.addEventListener("input", function () { r.valores[i] = area.value; });
    area.addEventListener("keydown", function (e) { e.stopPropagation(); });
    item.appendChild(area);
    var chips = el("div", "chips");
    p.opcoes.concat(["não sei"]).forEach(function (o) { chips.appendChild(botao(o, "", function () { area.value = o; r.valores[i] = o; })); });
    item.appendChild(chips);
    caixa.appendChild(item);
  });
  if (r.erro) { caixa.appendChild(el("p", "erro", r.erro)); }
  var bs = el("div", "botoes");
  bs.appendChild(botao("Responder", "botao principal", function () {
    var lista = (passo.saida.perguntas || []).map(function (p, i) { return { pergunta: p.texto, resposta: r.valores[i] || "" }; });
    postar("/fluxo/responder", { respostas: lista }).then(function (x) { return x.json(); }).then(function (d) {
      if (d.ok) { execucao = d.fluxo; pintarExecucao(); acompanhar(); return; }
      r.erro = d.motivo || "não deu"; desenharDireita();
    }).catch(function () { r.erro = "não consegui falar com o serviço"; desenharDireita(); });
  }));
  caixa.appendChild(bs);
  direita.appendChild(caixa);
}
var confirmacaoDoFormulario = { chave: "", producao: "", apelido: false, erro: "", enviando: false };
// ⛔ Daqui só saem "sim ou não", o nome e o apelido: as regras que gravam estão guardadas no passo, no serviço.
function desenharConfirmacao(passo) {
  // ⛔ A chave leva o id da execução: com só `passo/tentativas`, o nome digitado no cartão de uma execução aparecia no da seguinte, e ia parar na memória.
  var c = confirmacaoDoFormulario, dados_ = passo.saida.confirmar, chave = execucao.id + "/" + passo.id + "/" + passo.tentativas, caixa = el("div", "form-exec");
  if (c.chave !== chave) { c.chave = chave; c.producao = ""; c.apelido = false; c.erro = ""; c.enviando = false; }
  caixa.appendChild(el("h3", "", "Confirmar na memória da produção"));
  caixa.appendChild(el("p", "nota", "Valem daqui em diante, sem IA, para ler os nomes do som. Só o seu clique grava."));
  dados_.regras.forEach(function (r) {
    var item = el("div", "regra-conf");
    item.appendChild(el("b", "", r.forma));
    item.appendChild(el("span", "", r.molde + (r.arquivos ? " · " + r.arquivos + " arquivo" + (r.arquivos > 1 ? "s" : "") : "")));
    if (r.exemplo) { item.appendChild(el("small", "", r.exemplo)); }
    caixa.appendChild(item);
  });
  if (dados_.nao_se_sabe.length) { caixa.appendChild(el("p", "nota", "Você disse não saber (não volta a ser perguntado): " + dados_.nao_se_sabe.join(", "))); }
  var nome = dados_.memoria || c.producao;
  if (dados_.memoria) {
    caixa.appendChild(el("p", "nota", "Produção: " + dados_.memoria));
  } else {
    var perg = el("div", "perg"), entrada = document.createElement("input");
    entrada.className = "entrada"; entrada.value = c.producao; entrada.setAttribute("aria-label", "Nome da produção");
    entrada.addEventListener("input", function () { c.producao = entrada.value; });
    entrada.addEventListener("keydown", function (e) { e.stopPropagation(); });
    perg.appendChild(el("span", "", "De que produção é esta diária? Se for nova, escreva o nome dela."));
    perg.appendChild(entrada);
    var chips = el("div", "chips");
    dados_.sugestoes.forEach(function (o) { chips.appendChild(botao(o, "", function () { c.producao = o; desenharDireita(); })); });
    perg.appendChild(chips);
    caixa.appendChild(perg);
  }
  if (dados_.projeto_aberto && dados_.projeto_aberto !== nome) {
    var rot = document.createElement("label"), marca = document.createElement("input");
    rot.className = "marca-conf"; marca.type = "checkbox"; marca.checked = c.apelido;
    marca.addEventListener("change", function () { c.apelido = marca.checked; });
    rot.appendChild(marca);
    rot.appendChild(document.createTextNode(" O projeto aberto (" + dados_.projeto_aberto + ") é desta produção"));
    caixa.appendChild(rot);
  }
  if (c.erro) { caixa.appendChild(el("p", "erro", c.erro)); }
  function responder(gravar) {
    c.enviando = true; c.erro = ""; desenharDireita();
    postar("/fluxo/confirmar", { gravar: gravar, producao: c.producao, apelido: c.apelido }).then(function (x) { return x.json(); }).then(function (d) {
      c.enviando = false;
      if (d.ok) { execucao = d.fluxo; pintarExecucao(); acompanhar(); return; }
      c.erro = d.motivo || "não deu"; desenharDireita();
    }).catch(function () { c.enviando = false; c.erro = "não consegui falar com o serviço"; desenharDireita(); });
  }
  var bs = el("div", "botoes"), gravar = botao(c.enviando ? "Conferindo…" : "Gravar na memória", "botao principal", function () { responder(true); }), nao = botao("Não gravar", "botao", function () { responder(false); });
  gravar.disabled = nao.disabled = c.enviando;
  bs.appendChild(gravar); bs.appendChild(nao);
  caixa.appendChild(bs);
  direita.appendChild(caixa);
}
function desenharDireita() {
  direita.textContent = "";
  var pendente = perguntaPendente();
  if (pendente) { if (pendente.saida.confirmar) { desenharConfirmacao(pendente); } else { desenharRespostas(pendente); } return; }
  if (!aberto) { return; }
  if (formExec && !eAgente(aberto)) { desenharFormulario(); return; }
  if (eAgente(aberto)) {
    direita.appendChild(el("header", "", "Alterar com o chat"));
  } else {
    var abas = el("div", "abas");
    [["chat", "Chat"], ["props", "Propriedades"]].forEach(function (a) {
      abas.appendChild(botao(a[1], abaDireita === a[0] ? "ativa" : "", function () { abaDireita = a[0]; desenharDireita(); }));
    });
    direita.appendChild(abas);
    if (abaDireita === "props") { direita.appendChild(painelDoNo()); return; }
  }
  if (eAgente(aberto)) {
    // ⚠️ Os agentes são da casa, na pasta do programa: alterar pede um lugar para a versão do editor (fase B4 do plano de agentes).
    direita.appendChild(el("div", "espera", "Alterar agentes pelo chat ainda não está disponível."));
    return;
  }
  desenharConversa();
}

/* ── executar ── */

function finalizado(f) { return f.estado === "pronto" || f.estado === "cancelado"; }
function pintarBotaoExecutar() {
  var q = quadro;
  if (!q || !q.btnExecutar) { return; }
  var aberta = execucao && !finalizado(execucao);
  q.btnExecutar.disabled = q.g.sujo || !q.g.fluxo.nome || !!aberta;
  q.btnExecutar.title = aberta ? "Há um fluxo em andamento" : q.g.sujo || !q.g.fluxo.nome ? "Salve o fluxo antes de executar" : "";
}
function acompanhar() {
  clearTimeout(relogioDaExecucao);
  return fetch("/fluxo", { cache: "no-store" })
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(function (d) {
      execucao = d.fluxo;
      pintarExecucao();
      if (execucao && execucao.estado === "correndo") { relogioDaExecucao = setTimeout(acompanhar, 1000); }
    })
    .catch(function () { relogioDaExecucao = setTimeout(acompanhar, 3000); });
}
function gestoNaExecucao(acao) {
  postar("/fluxo/" + acao, {}).then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok && d.motivo) { avisarNoQuadro(d.motivo); }
    return acompanhar();
  }).catch(function () { avisarNoQuadro("Não consegui falar com o serviço."); });
}
function perguntaPendente() { return execucao && execucao.estado === "perguntando" ? execucao.passos[execucao.atual] : null; }
function classeDoEstado(e) { return { correndo: "correndo", perguntando: "correndo", feito: "pronto", falhou: "falhou", cancelado: "falhou", fora: "fora" }[e] || ""; }
function marcarNode(q, id, classe) {
  var d = q.els[id];
  if (!d) { return; }
  ["correndo", "pronto", "falhou", "fora"].forEach(function (c) { d.classList.toggle(c, c === classe); });
}
function pintarExecucao() {
  var q = quadro, pendente = perguntaPendente(), chaveP = pendente ? pendente.id + "/" + pendente.tentativas : "";
  if (chaveP !== chaveDaPergunta) { chaveDaPergunta = chaveP; desenharDireita(); }
  if (!q || !q.faixa) { return; }
  pintarBotaoExecutar();
  var f = execucao, nosso = f && f.origem === "receita:" + q.g.fluxo.nome && f.id !== execucaoDispensada;
  if (!nosso) {
    q.g.nos.forEach(function (n) { marcarNode(q, n.id, ""); });
    q.faixa.hidden = true; chaveDosBotoes = "";
    return;
  }
  // ⭐ O gerente roda dentro do passo que ele confere: `revisado` separa os dois na tela.
  var gerente = {};
  f.passos.forEach(function (p) {
    var temGerente = !!q.els["agente_" + p.id], antes = temGerente && !p.revisado;
    if (temGerente) { gerente["agente_" + p.id] = p.estado === "correndo" || p.estado === "falhou" ? (antes ? classeDoEstado(p.estado) : "pronto") : classeDoEstado(p.estado); }
    marcarNode(q, p.id, antes && (p.estado === "correndo" || p.estado === "falhou") ? "" : classeDoEstado(p.estado));
  });
  Object.keys(gerente).forEach(function (id) { marcarNode(q, id, gerente[id]); });
  var atual = f.passos[f.atual], nome = "";
  if (atual) { var n = noPorId(q.g, atual.id); nome = n ? n.d.rotulo : atual.id; }
  var fora = f.passos.filter(function (p) { return p.estado === "fora"; }).length, feitos = f.passos.filter(function (p) { return p.estado === "feito"; }).length;
  var texto = f.estado === "correndo" ? "Executando: " + nome + (f.andamento && f.andamento.etapa ? " · " + f.andamento.etapa : "") + (f.pedido === "pausar" ? " · pausa ao fim deste node" : f.pedido === "cancelar" ? " · cancelando" : "")
    : f.estado === "esperando" ? "Parou em " + nome + ": " + ((atual && atual.motivo) || "")
    : f.estado === "perguntando" ? "Esperando sua resposta em " + nome + ", no painel à direita."
    : f.estado === "pausado" ? "Pausado antes de " + nome + "."
    : f.estado === "interrompido" ? "O serviço reiniciou no meio do fluxo. Vai retomar em " + nome + "."
    : f.estado === "cancelado" ? "Cancelado."
    : "Concluído: " + feitos + (feitos === 1 ? " node executado" : " nodes executados") + (fora ? ", " + fora + " fora do caminho" : "") + ".";
  q.faixa.hidden = false;
  q.faixa.className = "execucao" + (f.estado === "esperando" || f.estado === "interrompido" ? " ruim" : "");
  // ⛔ Com o relógio de 1 s, refazer os botões a cada volta mataria o clique entre apertar e soltar: só mudam quando o estado muda.
  var chave = f.estado + "|" + f.pedido + "|" + (atual && atual.teto_atingido ? "t" : "");
  if (chave === chaveDosBotoes) { q.faixa.querySelector(".texto").textContent = texto; return; }
  chaveDosBotoes = chave;
  q.faixa.textContent = "";
  q.faixa.appendChild(el("span", "texto", texto));
  function b(rotulo, acao) { q.faixa.appendChild(botao(rotulo, "botao", function () { gestoNaExecucao(acao); })); }
  if (f.estado === "correndo") { if (!f.pedido) { b("Pausar", "pausar"); b("Cancelar", "cancelar"); } }
  else if (f.estado === "perguntando") { b("Cancelar", "cancelar"); }
  else if (f.estado === "esperando") { if (!(atual && atual.teto_atingido)) { b("Tentar de novo", "retomar"); } b("Pular este node", "pular"); b("Cancelar", "cancelar"); }
  else if (f.estado === "pausado" || f.estado === "interrompido") { b("Retomar", "retomar"); b("Cancelar", "cancelar"); }
  else { q.faixa.appendChild(botao("Fechar", "botao", function () { execucaoDispensada = f.id; pintarExecucao(); })); }
}

function abrirFormulario() {
  formExec = { valores: {}, erro: "", enviando: false, timelines: {} };
  var ps = quadro.g.parametros;
  Object.keys(ps).forEach(function (k) { if (ps[k].padrao !== undefined) { formExec.valores[k] = ps[k].padrao; } });
  noAberto = null; fioAberto = null;
  desenharDireita();
}
function campoDoFormulario(k, spec) {
  var f = formExec, caixa = el("div", "campo"), entrada;
  caixa.appendChild(el("span", "", (spec.rotulo || k.replace(/_/g, " ")) + (spec.opcional ? " (opcional)" : "")));
  if (spec.tipo === "pasta" || spec.tipo === "arquivo") {
    // ⛔ Caminho nunca é digitado: o diálogo do sistema é o gesto que autoriza (ADR 0005).
    var atual = f.valores[k], lista = Array.isArray(atual) ? atual : atual ? [atual] : [];
    caixa.appendChild(botao(lista.length ? "Trocar…" : (spec.tipo === "pasta" ? "Escolher a pasta…" : "Escolher o arquivo…"), "botao", function () {
      postar("/receitas/escolher", { tipo: spec.tipo, multiplos: !!spec.multiplos, extensoes: spec.extensoes || [], titulo: spec.rotulo || "" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.ok && d.caminhos.length) { f.valores[k] = spec.multiplos ? d.caminhos : d.caminhos[0]; f.erro = ""; }
          else if (!d.ok) { f.erro = d.erro || "não consegui abrir o seletor"; }
          desenharDireita();
        }).catch(function () { f.erro = "não consegui falar com o serviço"; desenharDireita(); });
    }));
    lista.forEach(function (c) { caixa.appendChild(el("div", "caminho", c)); });
    return caixa;
  }
  if (spec.tipo === "timeline") {
    var arquivo = f.valores[spec.de], chave = String(arquivo || "");
    if (!arquivo) { caixa.appendChild(el("div", "caminho", "Escolha o arquivo primeiro.")); return caixa; }
    var lido = f.timelines[chave];
    if (!lido) {
      f.timelines[chave] = { carregando: true };
      caixa.appendChild(el("div", "caminho", "Lendo as timelines…"));
      postar("/receitas/timelines", { arquivo: arquivo }).then(function (r) { return r.json(); }).then(function (d) {
        f.timelines[chave] = d.ok ? { nomes: d.timelines.map(function (x) { return x.nome; }) } : { erro: d.motivo || "não consegui ler" };
        desenharDireita();
      }).catch(function () { f.timelines[chave] = { erro: "não consegui falar com o serviço" }; desenharDireita(); });
      return caixa;
    }
    if (lido.carregando || lido.erro) { caixa.appendChild(el("div", "caminho", lido.erro || "Lendo as timelines…")); return caixa; }
    entrada = document.createElement("select"); entrada.className = "entrada";
    opcao(entrada, "", "Escolha…");
    lido.nomes.forEach(function (n) { opcao(entrada, n, n); });
    entrada.value = f.valores[k] || "";
  } else if (spec.tipo === "escolha" || spec.tipo === "sim_nao") {
    entrada = document.createElement("select"); entrada.className = "entrada";
    if (spec.tipo === "sim_nao") { opcao(entrada, "true", "sim"); opcao(entrada, "false", "não"); entrada.value = String(f.valores[k] === true); }
    else { (spec.opcoes || []).forEach(function (o) { opcao(entrada, String(o), String(o)); }); if (f.valores[k] === undefined) { f.valores[k] = (spec.opcoes || [""])[0]; } entrada.value = String(f.valores[k]); }
  } else {
    entrada = document.createElement("input"); entrada.className = "entrada";
    if (spec.tipo === "numero") { entrada.type = "number"; }
    entrada.value = f.valores[k] === undefined ? "" : f.valores[k];
  }
  entrada.setAttribute("aria-label", spec.rotulo || k);
  entrada.addEventListener("change", function () { f.valores[k] = spec.tipo === "sim_nao" ? entrada.value === "true" : spec.tipo === "numero" ? Number(entrada.value) : entrada.value; });
  caixa.appendChild(entrada);
  return caixa;
}
function desenharFormulario() {
  var f = formExec, g = quadro.g, caixa = el("div", "form-exec");
  caixa.appendChild(el("h3", "", "Executar: " + tituloDe(g.fluxo)));
  var nomes = Object.keys(g.parametros);
  if (!nomes.length) { caixa.appendChild(el("p", "nota", "Este fluxo não pergunta nada. Ele vai rodar todos os nodes, de verdade.")); }
  if (g.fluxo.ia) { caixa.appendChild(el("p", "nota", g.fluxo.ia.texto)); }
  nomes.forEach(function (k) { caixa.appendChild(campoDoFormulario(k, g.parametros[k])); });
  if (f.erro) { caixa.appendChild(el("p", "erro", f.erro)); }
  var bs = el("div", "botoes");
  bs.appendChild(botao("Cancelar", "botao", function () { formExec = null; desenharDireita(); }));
  var ir = botao(f.enviando ? "Começando…" : "Executar", "botao principal", function () {
    if (f.enviando) { return; }
    f.enviando = true; f.erro = ""; desenharDireita();
    postar("/oficina/executar", { nome: g.fluxo.nome, parametros: f.valores }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.ok) { formExec = null; execucaoDispensada = ""; execucao = d.fluxo; desenharDireita(); pintarExecucao(); acompanhar(); return; }
      f.enviando = false; f.erro = d.motivo || "não deu para executar"; desenharDireita();
    }).catch(function () { f.enviando = false; f.erro = "não consegui falar com o serviço"; desenharDireita(); });
  });
  bs.appendChild(ir);
  caixa.appendChild(bs);
  direita.appendChild(caixa);
}

/* ── o chat ── */

function blocoDaMensagem(m) {
  if (m.de === "proposta") { return blocoDaProposta(m); }
  var b = el("div", m.de === "eu" ? "minha" : m.de === "erro" ? "dele de-erro" : "dele", m.texto);
  m.el = b;
  return b;
}
function rolarConversa() {
  var c = document.getElementById("conversaDaJanela");
  if (c) { c.scrollTop = c.scrollHeight; }
}
function pintarAtividade() {
  var a = document.getElementById("atividade");
  if (a) { a.hidden = !atividade; a.textContent = atividade; }
}
function desenharConversa() {
  var c = el("div", "conversa");
  c.id = "conversaDaJanela";
  if (!mensagens.length) { c.appendChild(el("p", "nota", "Descreva o fluxo que você quer, ou clique duas vezes num node e use Ajustar no chat.")); }
  mensagens.forEach(function (m) { c.appendChild(blocoDaMensagem(m)); });
  var a = el("div", "atividade");
  a.id = "atividade";
  c.appendChild(a);
  direita.appendChild(c);
  pintarAtividade();
  if (noNoChat) {
    var chip = el("div", "chip-no");
    chip.appendChild(el("span", "", "node: " + noNoChat.d.rotulo));
    var tirar = botao("×", "", function () { noNoChat = null; desenharDireita(); });
    tirar.setAttribute("aria-label", "Tirar o node do chat");
    chip.appendChild(tirar);
    direita.appendChild(chip);
  }
  var f = el("div", "compositor"), ent = document.createElement("textarea");
  ent.id = "mensagem"; ent.rows = 1; ent.value = rascunho; ent.setAttribute("aria-label", "Mensagem");
  ent.placeholder = noNoChat ? "O que mudar neste node?" : "Descreva o fluxo...";
  function crescer() {
    ent.style.height = "auto";
    var h = Math.min(ent.scrollHeight + 2, 120);
    ent.style.height = h + "px";
    ent.style.overflowY = ent.scrollHeight + 2 > 120 ? "auto" : "hidden";
  }
  ent.addEventListener("input", function () { rascunho = ent.value; crescer(); });
  ent.addEventListener("keydown", function (e) {
    e.stopPropagation();
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarMensagem(); }
  });
  f.appendChild(ent);
  var env = botao(ocupado ? "■" : "→", "", function () { if (ocupado) { pararTurno(); } else { enviarMensagem(); } });
  env.id = "enviarMensagem"; env.setAttribute("aria-label", ocupado ? "Parar" : "Enviar");
  f.appendChild(env);
  direita.appendChild(f);
  crescer();
  rolarConversa();
}
function aoMudarOcupado() {
  var env = document.getElementById("enviarMensagem");
  if (env) { env.textContent = ocupado ? "■" : "→"; env.setAttribute("aria-label", ocupado ? "Parar" : "Enviar"); }
}
function acrescentar(m) {
  mensagens.push(m);
  var c = document.getElementById("conversaDaJanela"), a = document.getElementById("atividade");
  if (c && a) {
    var nota = c.querySelector(":scope > .nota");
    if (nota) { nota.remove(); }
    c.insertBefore(blocoDaMensagem(m), a);
    rolarConversa();
  }
  return m;
}
function contextoDaJanela() {
  if (!quadro) { return { titulo: null, nos: [], ligacoes: [], parametros: {} }; }
  var g = quadro.g, p = pedidoDe(g);
  p.node = noNoChat ? noNoChat.d.rotulo + " (id " + noNoChat.id + ")" : "";
  p.decisao = ultimaDecisao;
  return p;
}
/* Corta os eventos à mão: `EventSource` só faz GET, e a pergunta vai no corpo. A mesma leitura do `lerFluxo` do painel. */
function lerEventos(corpoDaResposta, aoEvento) {
  var leitor = corpoDaResposta.getReader(), dec = new TextDecoder("utf-8"), sobra = "";
  function passo() {
    return leitor.read().then(function (r) {
      if (r.done) { return; }
      sobra += dec.decode(r.value, { stream: true });
      var partes = sobra.split("\n\n");
      sobra = partes.pop();
      partes.forEach(function (bruto) {
        var tipo = null, d = null;
        bruto.split("\n").forEach(function (l) {
          if (l.indexOf("event: ") === 0) { tipo = l.slice(7); } else if (l.indexOf("data: ") === 0) { d = l.slice(6); }
        });
        if (!tipo || d === null) { return; }
        try { aoEvento(tipo, JSON.parse(d)); } catch (e) { /* evento malformado não derruba o turno */ }
      });
      return passo();
    });
  }
  return passo();
}
function enviarMensagem() {
  var ent = document.getElementById("mensagem"), texto = ent ? ent.value.trim() : "";
  if (!texto || ocupado) { return; }
  rascunho = ""; ent.value = ""; ent.style.height = "";
  acrescentar({ de: "eu", texto: texto });
  ocupado = true; atividade = "Pensando"; aoMudarOcupado(); pintarAtividade();
  var janela = contextoDaJanela(), resposta = null, fluxoDoTurno = aberto;
  ultimaDecisao = "";
  function emFalha(t) { acrescentar({ de: "erro", texto: t }); }
  fetch("/conversar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pergunta: texto, conversa: "oficina", janela: janela }) })
    .then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return lerEventos(r.body, function (tipo, d) {
        if (tipo === "texto") {
          if (!resposta) { resposta = acrescentar({ de: "ele", texto: "" }); }
          resposta.texto += d.texto;
          if (resposta.el) { resposta.el.textContent = resposta.texto; }     // com a aba Propriedades aberta, o texto espera na lista
          atividade = ""; pintarAtividade(); rolarConversa();
        } else if (tipo === "ferramenta") {
          atividade = "Consultando"; pintarAtividade();
        } else if (tipo === "proposta_fluxo" || tipo === "proposta_node") {
          resposta = null;
          acrescentar({ de: "proposta", proposta: { tipo: tipo, d: d, fluxo: fluxoDoTurno, estado: "" } });
        } else if (tipo === "aprovacao" || tipo === "perguntas") {
          emFalha("O modelo pediu algo que esta janela não mostra. Tente pedir de outro jeito.");
        } else if (tipo === "erro") {
          emFalha(d.mensagem);
        }
      });
    })
    .catch(function (e) { emFalha("Não consegui falar com o serviço do Ciclo Assist (" + e.message + ")."); })
    .then(function () { ocupado = false; atividade = ""; aoMudarOcupado(); pintarAtividade(); });
}
function pararTurno() {
  postar("/conversar/parar", { conversa: "oficina" }).catch(function () { atividade = "Não consegui parar."; pintarAtividade(); });
}

function legivel(v) { return v === null || v === undefined ? "(sem valor)" : typeof v === "string" ? v : JSON.stringify(v); }
function textoDaProposta(p) {
  var d = p.d;
  if (p.tipo === "proposta_fluxo") {
    var nome = tituloDe({ titulo: d.titulo, nome: "" });
    return p.estado === "aceita" ? "O fluxo " + nome + " está na tela, com " + d.nos.length + " nodes. Falta salvar."
      : p.estado === "recusada" ? "Proposta recusada. O fluxo " + nome + " não foi criado."
      : d.resumo + " (" + (d.novo ? "fluxo novo" : "substitui o que está aberto") + ", " + d.nos.length + " nodes)";
  }
  var mud = Object.keys(d.mudancas).map(function (k) { return k.replace(/_/g, " ") + " para " + legivel(d.mudancas[k]); }).join("; ");
  return p.estado === "aceita" ? "No node " + d.rotulo + ", mudou: " + mud + ". Falta salvar."
    : p.estado === "recusada" ? "Mudança recusada. O node " + d.rotulo + " não foi alterado."
    : p.estado === "sumiu" ? "O node " + d.rotulo + " não existe mais neste fluxo."
    : (d.resumo.indexOf(d.rotulo) >= 0 ? "" : "No node " + d.rotulo + ": ") + d.resumo + " (" + mud + ")";     // ⭐ o nome do node sempre aparece, uma vez
}
function aceitarFluxo(p) {
  var d = p.d, alvo = p.fluxo, tela = alvo && !eAgente(alvo) && dados.fluxos.indexOf(alvo) >= 0, vazio = tela && !grafoDe(alvo).nos.length;
  var substitui = tela && (!d.novo || vazio);     // um "Novo fluxo" ainda vazio é o próprio lugar da proposta
  // ⭐ O nome que o editor digitou ao criar vale mais que o que o modelo sugeriu ("Benchmark da noite" era salvo como "preparar-a-diaria-…-2").
  if (substitui && vazio && !alvo.nome && alvo.titulo !== "Novo fluxo") { d.titulo = alvo.titulo; }
  var f = { nome: substitui ? alvo.nome : "", titulo: d.titulo, descricao: "", parametros: d.parametros, origem: substitui ? alvo.origem : "novo", nos: d.nos, ligacoes: d.ligacoes, posicoes: null, problemas: [] };
  if (substitui) { dados.fluxos[dados.fluxos.indexOf(alvo)] = f; } else { dados.fluxos.push(f); }
  grafoDe(f).sujo = true;
  aberto = f; selecionado = f; noAberto = null; noNoChat = null;
  desenharListas(); desenharCentro();
  p.estado = "aceita";
}
function aceitarNo(p) {
  var d = p.d;
  if (dados.fluxos.indexOf(p.fluxo) < 0) { p.estado = "sumiu"; return; }     // excluído enquanto a proposta esperava
  if (aberto !== p.fluxo) { abrir(p.fluxo); }
  var n = quadro ? noPorId(quadro.g, d.node) : null;
  if (!n) { p.estado = "sumiu"; return; }
  Object.keys(d.parametros || {}).forEach(function (k) { quadro.g.parametros[k] = d.parametros[k]; });
  Object.keys(d.mudancas).forEach(function (k) {
    var v = d.mudancas[k], c = { nome: k };
    aoMudarCampo(n, c, v === null ? undefined : v);
  });
  p.estado = "aceita";
}
function decidirProposta(p, aceitou) {
  if (aceitou) { if (p.tipo === "proposta_fluxo") { aceitarFluxo(p); } else { aceitarNo(p); } } else { p.estado = "recusada"; }
  ultimaDecisao = (p.estado === "aceita" ? "aceita: " : "recusada: ") + p.d.resumo;
  desenharDireita();
}
function blocoDaProposta(m) {
  var p = m.proposta, b = el("div", "proposta" + (p.estado ? " decidida" : ""));
  b.appendChild(el("div", "", textoDaProposta(p)));
  if (!p.estado) {
    var f = el("div", "botoes");
    f.appendChild(botao("Aceitar", "botao principal", function () { decidirProposta(p, true); }));
    f.appendChild(botao("Recusar", "botao", function () { decidirProposta(p, false); }));
    b.appendChild(f);
  }
  return b;
}

/* ── as alças ── */

function arrastar(alca, mover) {
  alca.addEventListener("pointerdown", function (e) { e.preventDefault(); seguir(alca, e, mover); });
}
var raiz = document.documentElement, corpo = document.getElementById("corpo");
arrastar(document.getElementById("alcaLateral"), function (e) { raiz.style.setProperty("--lateral", limitar(e.clientX - corpo.getBoundingClientRect().left, 190, 420) + "px"); });
arrastar(document.getElementById("alcaDireita"), function (e) { raiz.style.setProperty("--direita", limitar(corpo.getBoundingClientRect().right - e.clientX, 240, 520) + "px"); });
arrastar(document.getElementById("alcaMetades"), function (e) { var r = corpo.getBoundingClientRect(); raiz.style.setProperty("--fluxos", limitar((e.clientY - r.top) / r.height * 100, 28, 72) + "%"); });

function exportarFluxo() {
  postar("/oficina/exportar", { nome: quadro.g.fluxo.nome }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.cancelado) { return; }
    avisarNoQuadro(d.ok ? "Fluxo gravado em " + d.caminho : d.motivo || "Não consegui gravar.");
  }).catch(function () { avisarNoQuadro("Não consegui falar com o serviço."); });
}
document.getElementById("importarFluxo").addEventListener("click", function () {
  postar("/oficina/importar", {}).then(function (r) { return r.json(); }).then(function (d) {
    if (d.cancelado) { return; }
    if (!d.ok) { if (quadro) { avisarNoQuadro(d.motivo || "Não consegui importar."); } return; }
    return Promise.resolve(carregar(d.nome)).then(function () {
      if (d.avisos && d.avisos.length) { setTimeout(function () { avisarNoQuadro(d.avisos.join(" ")); }, 200); }
    });
  }).catch(function () { if (quadro) { avisarNoQuadro("Não consegui falar com o serviço."); } });
});
document.getElementById("restaurarFluxos").addEventListener("click", function () {
  // ⭐ Só acrescenta: recarregar tudo perderia o que está sem salvar no fluxo aberto.
  postar("/oficina/restaurar", {}).then(function () { return fetch("/oficina/dados", { cache: "no-store" }); }).then(function (r) { return r.json(); }).then(function (d) {
    var tem = dados.fluxos.map(function (f) { return f.nome; });
    d.fluxos.forEach(function (f) { if (tem.indexOf(f.nome) < 0) { dados.fluxos.push(f); } });
    dados.excluidos_do_programa = d.excluidos_do_programa;
    desenharListas();
  }).catch(function () { janelaPequena("Não deu para restaurar", "Não consegui falar com o serviço do Ciclo Assist.", [["Entendi", "principal"]]); });
});
document.getElementById("criarFluxo").addEventListener("click", function () {
  var novo = { nome: "", titulo: "Novo fluxo", descricao: "", parametros: {}, origem: "novo", nos: [], ligacoes: [], posicoes: null, problemas: [] };
  dados.fluxos.push(novo);
  aberto = novo; selecionado = novo; noAberto = null; noNoChat = null; abaDireita = "chat";
  desenharListas(); desenharCentro(); desenharDireita();
  editarTitulo(quadro.g, centro.querySelector("h1"));
});

/* ⭐ Ao salvar um fluxo, recarrega tudo sem perder o que está em edição nos outros. */
function carregar(nomeParaAbrir) {
  return fetch("/oficina/dados", { cache: "no-store" })
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(function (d) {
      var antes = dados.fluxos;
      antes.forEach(function (f) {
        if (!f.grafo || !f.grafo.sujo || f.nome === nomeParaAbrir || aberto === f && nomeParaAbrir) { return; }
        var mesmo = d.fluxos.filter(function (o) { return f.nome && o.nome === f.nome; })[0];
        if (mesmo) { mesmo.grafo = f.grafo; f.grafo.fluxo = mesmo; } else if (!f.nome) { d.fluxos.push(f); }
      });
      dados = d;
      aberto = dados.fluxos.filter(function (f) { return f.nome === nomeParaAbrir; })[0] || dados.fluxos[0] || dados.agentes[0] || null;
      selecionado = aberto; noAberto = null; noNoChat = null; fioAberto = null; formExec = null; abaDireita = "chat";
      desenharListas(); desenharCentro(); desenharDireita();
    });
}
carregar("").then(acompanhar).catch(function (e) { centro.textContent = ""; centro.appendChild(el("div", "aviso", "Não consegui falar com o serviço do Ciclo Assist (" + e.message + ").")); });
