/* O topo do guarda-chuva: a conexão com o NLE, o pino, as abas e a engrenagem única.
 * ⚠️ A ponte com o Rust só existe com `withGlobalTauri` no `tauri.conf.json`: sem ela, tudo aqui fica mudo — por isso
 * a falta é dita na linha da conexão, em vez de calada. */
"use strict";
var ponte = window.__TAURI__ && window.__TAURI__.core;
var el = function (id) { return document.getElementById(id); };
var botoes = document.querySelectorAll("[data-aba]");

window.marcarAba = function (aba) {
  Array.prototype.forEach.call(botoes, function (b) {
    b.setAttribute("aria-selected", b.dataset.aba === aba ? "true" : "false");
  });
};
window.marcarPino = function (sim) { el("pino").setAttribute("aria-pressed", sim ? "true" : "false"); };

function chamar(comando, args) {
  if (!ponte) { return Promise.reject(new Error("sem ponte")); }
  return ponte.invoke(comando, args || {});
}

Array.prototype.forEach.call(botoes, function (b) {
  b.addEventListener("click", function () {
    window.marcarAba(b.dataset.aba);
    chamar("trocar_aba", { aba: b.dataset.aba });
  });
});
el("engrenagem").addEventListener("click", function () { chamar("engrenagem"); });
el("pino").addEventListener("click", function () {
  chamar("fixar_janela", { sim: el("pino").getAttribute("aria-pressed") !== "true" });
});

/* "Premiere Pro 23.6 · ORBITA PAINEL DEMO". A versão vai até o segundo número: é o que o editor reconhece. */
function rotulo(nome, d) {
  var v = String((d && d.versao) || "").split(".").slice(0, 2).join(".");
  return nome + (v ? " " + v : "") + (d && d.projeto ? " · " + d.projeto : "");
}

function pintarConexao(c) {
  var texto = el("conexao"), ponto = el("ponto");
  if (!c) {
    ponto.className = "ponto fora";
    texto.className = "texto";
    texto.textContent = ponte ? "o serviço do Ciclo Assist não respondeu" : "a ponte com o aplicativo não carregou";
    return;
  }
  var d = c.detalhe || {}, partes = [];
  if (c.avid) { partes.push(rotulo("Media Composer", d.avid)); }
  if (c.premiere) { partes.push(rotulo("Premiere Pro", d.premiere)); }
  if (c.resolve) { partes.push(rotulo("DaVinci Resolve", d.resolve)); }
  if (c.baselight) { partes.push(rotulo("Baselight", d.baselight)); }   // só recebe (proposta 2026-11-22)
  ponto.className = "ponto " + (partes.length ? "no-ar" : "fora");
  texto.className = "texto" + (partes.length ? " no-ar" : "");
  texto.textContent = partes.length ? partes.join("  +  ") : "nenhum editor aberto";
  texto.title = texto.textContent;
}

/* ⭐ Os motores do conjunto (o supervisor, `src/supervisor.rs`): com o Assist aberto, todos estão no ar. Caiu, ele
 * religa sozinho e a aba diz "religando…"; desistiu (3 vezes em 10 min), o TOPO avisa — é o que o editor vê de
 * qualquer aba — e o aviso é o próprio botão de tentar de novo. Quem tem problema ganha um ponto na aba. */
var falho = null;
function pintarMotores(lista) {
  var aviso = el("aviso");
  var porAba = {};
  (lista || []).forEach(function (s) { porAba[s.modulo] = s; });
  Array.prototype.forEach.call(botoes, function (b) {
    var s = porAba[b.dataset.aba];
    b.dataset.saude = s && (s.situacao === "falhou" || s.situacao === "religando") ? s.situacao : "";
  });
  var caidos = (lista || []).filter(function (s) { return s.situacao === "falhou"; });
  var religando = (lista || []).filter(function (s) { return s.situacao === "religando"; });
  falho = caidos[0] || null;
  if (falho) {
    aviso.hidden = false;
    aviso.className = "aviso falhou";
    aviso.textContent = falho.nome.charAt(0).toUpperCase() + falho.nome.slice(1) + " não subiu — tentar de novo";
    aviso.title = falho.motivo || "";
  } else if (religando.length) {
    aviso.hidden = false;
    aviso.className = "aviso";
    aviso.textContent = "religando " + religando.map(function (s) { return s.nome; }).join(" e ") + "…";
    aviso.title = religando[0].motivo || "";
  } else {
    aviso.hidden = true;
  }
}
el("aviso").addEventListener("click", function () {
  if (!falho) { return; }
  chamar("religar_motor", { modulo: falho.modulo });
  el("aviso").textContent = "religando " + falho.nome + "…";
});

function olhar() {
  chamar("conexao").then(pintarConexao, function () { pintarConexao(null); });
  chamar("estado_dos_motores").then(pintarMotores, function () { /* sem ponte: a linha da conexão já diz */ });
}

chamar("estado_do_topo").then(function (e) {
  if (e.aba) { window.marcarAba(e.aba); }
  window.marcarPino(!!e.fixada);
}, function () { pintarConexao(null); });
olhar();
setInterval(olhar, 5000);
