/* A janela de configurações (autor, 2026-11-07). A coluna escolhe a seção; a de um MÓDULO o app desenha por cima
 * (`ajustes_secao` → "modulo"), e esta página só mostra o próprio conteúdo quando a resposta é "local" ou "fora". */
"use strict";
var ponte = window.__TAURI__ && window.__TAURI__.core;
var el = function (id) { return document.getElementById(id); };
var NOMES = { preparar: "Preparar", assistir: "Assistir", conformar: "Conformar", integracoes: "Integrações",
             conta: "Conta" };
var MOTORES = { preparar: "o Sincronizar", assistir: "o serviço do Assist", conformar: "o De Lá Pra Cá",
               integracoes: "o serviço do Assist", conta: "o serviço do Assist" };
var atual = null;

function chamar(comando, args) {
  if (!ponte) { return Promise.reject(new Error("a ponte com o aplicativo não carregou")); }
  return ponte.invoke(comando, args || {});
}

function mostrarConteudo(qual) {
  Array.prototype.forEach.call(document.querySelectorAll("[data-conteudo]"), function (s) {
    s.hidden = s.dataset.conteudo !== qual;
  });
}

window.irPara = function (secao) {
  if (!document.querySelector('[data-secao="' + secao + '"]')) { secao = "geral"; }
  atual = secao;
  Array.prototype.forEach.call(document.querySelectorAll("[data-secao]"), function (b) {
    b.setAttribute("aria-current", b.dataset.secao === secao ? "true" : "false");
  });
  mostrarConteudo(null);
  chamar("ajustes_secao", { secao: secao })
    .then(function (r) {
      if (secao !== atual) { return; }
      if (r === "modulo") { return; }
      if (r === "fora") {
        el("foraTitulo").textContent = NOMES[secao] || secao;
        el("foraTexto").textContent = MOTORES[secao] + " não está no ar agora, e esta seção mora nele. "
          + "O app religa os motores sozinho: tente de novo em alguns segundos.";
        mostrarConteudo("fora");
        return;
      }
      mostrarConteudo(secao);
      if (secao === "geral") { carregarGeral(); }
    })
    .catch(function (e) {
      el("foraTitulo").textContent = "Não consegui abrir esta seção";
      el("foraTexto").textContent = String(e && e.message || e);
      mostrarConteudo("fora");
    });
};

window.marcarPino = function (sim) { el("pino").checked = !!sim; };

function carregarGeral() {
  chamar("ajustes_geral").then(function (g) {
    el("versao").textContent = g.versao;
    el("pino").checked = !!g.fixada;
    el("pasta").textContent = g.pasta || "—";
    el("inicio").value = g.inicio || "assistir";
  }).catch(function () { /* a seção mostra as reticências */ });
}

Array.prototype.forEach.call(document.querySelectorAll("[data-secao]"), function (b) {
  b.addEventListener("click", function () { window.irPara(b.dataset.secao); });
});
el("pino").addEventListener("change", function () { chamar("fixar_janela", { sim: el("pino").checked }); });
el("inicio").addEventListener("change", function () {
  chamar("ajustes_inicio", { inicio: el("inicio").value })
    .then(function () { el("inicioRecado").textContent = "Guardado. Vale a partir da próxima vez que o app abrir."; })
    .catch(function (e) { el("inicioRecado").textContent = "Não consegui guardar: " + e; });
});
el("abrirPasta").addEventListener("click", function () { chamar("abrir_pasta_de_dados").catch(function () {}); });
el("foraTentar").addEventListener("click", function () { window.irPara(atual); });

window.irPara(new URLSearchParams(location.search).get("s") || "geral");
