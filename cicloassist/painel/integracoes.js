/* A seção Integrações (2026-11-07): o estado (`/integracoes/estado`), a conexão (`/conexao`) e as duas ações. */
"use strict";
var el = function (id) { return document.getElementById(id); };
var NOMES = { premiere: "Premiere", media_composer: "Media Composer", resolve: "Resolve" };

function pedir(metodo, rota) {
  return fetch(rota, { method: metodo, cache: "no-store", headers: { "Content-Type": "application/json" },
                       body: metodo === "POST" ? "{}" : undefined })
    .then(function (r) { return r.json().catch(function () { return { ok: false, erro: "HTTP " + r.status }; }); });
}

function fato(id, sim, texto) {
  var li = el(id);
  li.className = sim === null ? "" : (sim ? "sim" : "nao");
  li.textContent = texto;
}

function pintarEstado(e) {
  var p = e.ponte || {};
  var selo = el("prSelo"), botao = el("instalar");
  var tudoCerto = p.situacao === "instalada" && p.modo_depuracao;
  selo.className = "selo " + (tudoCerto ? "ok" : "alerta");
  selo.textContent = tudoCerto ? "instalada" : p.situacao === "ausente" ? "não instalada" : "precisa atualizar";
  fato("prPonte", p.situacao === "instalada",
       p.situacao === "instalada" ? "A ponte instalada é a desta versão do app."
       : p.situacao === "ausente" ? "A ponte não está instalada neste computador."
       : "A ponte instalada é de outra versão do app.");
  fato("prDepuracao", !!p.modo_depuracao, p.modo_depuracao
       ? "O Premiere aceita extensões sem assinatura (modo de desenvolvedor do CEP ligado)."
       : "O modo de desenvolvedor do CEP está desligado: sem ele o Premiere recusa a ponte, sem avisar.");
  botao.hidden = false;
  botao.className = "botao" + (tudoCerto ? "" : " principal");
  botao.textContent = p.situacao === "ausente" ? "Instalar a ponte" : tudoCerto ? "Reinstalar a ponte" : "Atualizar a ponte";

  var antigas = e.antigas || [];
  el("blocoAntigas").hidden = !antigas.length && el("recadoTirar").hidden;
  el("antigasSelo").textContent = antigas.length ? antigas.length + " instalada(s)" : "nenhuma";
  el("antigasSelo").className = "selo " + (antigas.length ? "alerta" : "ok");
  el("tirar").hidden = !antigas.length;
  var lista = el("antigas");
  lista.textContent = "";
  antigas.forEach(function (a) {
    var li = document.createElement("li"), b = document.createElement("b");
    b.textContent = NOMES[a.nle] || a.nle;
    li.appendChild(b);
    li.appendChild(document.createTextNode(a.caminho + (a.atalho ? "  (atalho)" : "")));
    lista.appendChild(li);
  });
}

function rotulo(d) {
  d = d || {};
  var v = String(d.versao || "").split(".").slice(0, 2).join(".");
  return (v ? " " + v : "") + (d.projeto ? " · " + d.projeto : "");
}

function pintarConexao(c) {
  var d = (c && c.detalhe) || {};
  fato("prConexao", !!(c && c.premiere), c && c.premiere
       ? "Conectada agora: Premiere Pro" + rotulo(d.premiere) + "."
       : "Sem conexão agora — o Premiere está fechado, ou foi aberto antes da ponte ser instalada (feche e abra).");
  fato("mcConexao", !!(c && c.avid), c && c.avid ? "Conectado agora: Media Composer" + rotulo(d.avid) + "."
       : "O Media Composer não está aberto.");
  fato("rsConexao", !!(c && c.resolve), c && c.resolve ? "Conectado agora: DaVinci Resolve" + rotulo(d.resolve) + "."
       : "O Resolve não está aberto (ou não é o Studio, que é o que tem a API externa).");
}

function carregar() {
  pedir("GET", "/integracoes/estado").then(pintarEstado).catch(function () {});
  pedir("GET", "/conexao").then(pintarConexao).catch(function () { pintarConexao(null); });
}

function recado(id, texto, erro) {
  var r = el(id);
  r.hidden = !texto;
  r.className = "recado" + (erro ? " erro" : "");
  r.textContent = texto || "";
}

el("instalar").addEventListener("click", function () {
  var b = el("instalar");
  b.disabled = true;
  recado("recadoInstalar", "instalando…");
  pedir("POST", "/integracoes/instalar").then(function (r) {
    if (r.estado) { pintarEstado(r.estado); }
    if (r.erro) { recado("recadoInstalar", r.erro, true); return; }
    recado("recadoInstalar", (r.falhas || []).length
      ? "A ponte foi copiada, mas o modo de desenvolvedor não ligou: " + r.falhas.join("; ")
      : "Pronto. Se o Premiere estiver aberto, feche e abra: ele só carrega extensões ao começar.",
      (r.falhas || []).length > 0);
  }).catch(function (e) { recado("recadoInstalar", "O serviço não respondeu: " + e.message, true); })
    .then(function () { b.disabled = false; });
});

el("tirar").addEventListener("click", function () {
  var b = el("tirar");
  b.disabled = true;
  recado("recadoTirar", "tirando…");
  pedir("POST", "/integracoes/tirar-antigas").then(function (r) {
    if (r.estado) { pintarEstado(r.estado); }
    if (r.erro) { recado("recadoTirar", r.erro, true); return; }
    recado("recadoTirar", (r.tirados || []).length
      ? "Tirei " + r.tirados.length + ". A cópia ficou em " + r.copia
        + ". Feche e abra os editores que estavam abertos."
      : "Não havia nada para tirar.");
    if (r.estado) { pintarEstado(r.estado); }
  }).catch(function (e) { recado("recadoTirar", "O serviço não respondeu: " + e.message, true); })
    .then(function () { b.disabled = false; });
});

carregar();
setInterval(function () { if (!document.hidden) { pedir("GET", "/conexao").then(pintarConexao).catch(function () {}); } },
            5000);
