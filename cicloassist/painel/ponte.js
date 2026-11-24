/* A ponte do Premiere (`ponte.html`), aberta pela extensão invisível. Ver o cabeçalho da página.
 *
 * O ExtendScript (`host.jsx`) vem do SERVIÇO e é avaliado ao abrir e depois de cada queda do serviço: o script
 * fica no Premiere, não no serviço, e um serviço novo com funções novas conversaria com o script velho — o erro
 * sairia como "EvalScript error" numa ferramenta que existe. */
"use strict";
var CEP = window.__adobe_cep__ || null;

/* ⚠️ Com PRAZO: a extensão sobe JUNTO com o Premiere, e um evalScript que nunca responde não pode travar o laço
 * (De Lá Pra Cá, 2026-10-19). Sem prazo no pedido normal: quem tem prazo ali é o serviço (`ponte.PRAZO_S`). */
function noPremiere(expr, prazo) {
  return new Promise(function (ok) {
    var feito = false;
    function fim(r) { if (!feito) { feito = true; ok(r); } }
    if (prazo) { setTimeout(function () { fim("EvalScript error. sem resposta"); }, prazo); }
    try { CEP.evalScript(expr, fim); } catch (e) { fim("EvalScript error. " + e); }
  });
}

function carregarOHost() {
  return fetch("/premiere/host.jsx", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.text();
    })
    .then(function (t) { return noPremiere(t, 10000); })
    .then(function (r) {
      if (String(r).indexOf("EvalScript error") === 0) { throw new Error("o host não carregou: " + r); }
    });
}

function atender() {
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
    .then(atender, function () { setTimeout(comecar, 2000); });
}

function comecar() {
  carregarOHost().then(atender, function () { setTimeout(comecar, 3000); });
}

if (CEP) { comecar(); }
