/* A espera de cada aba. Quem leva a aba ao painel do módulo é o Rust, quando o motor atende; aqui só o estado. */
"use strict";
var aba = (location.search.match(/[?&]m=([a-z]+)/) || [])[1] || "";
var el = function (id) { return document.getElementById(id); };

var MODULOS = {
  preparar: { nome: "Preparar", sub: "Sincronizar — sincronizar câmeras e som", motor: "o Sincronizar (porta 7817)" },
  assistir: { nome: "Assistir", sub: "O assistente: conversa com o agente", motor: "o serviço do Assist (porta 7824)" },
  conformar: { nome: "Conformar", sub: "De Lá Pra Cá — relink e travessia entre NLEs", motor: "o De Lá Pra Cá (porta 7823)" },
  entregar: { nome: "Entregar", sub: "Promo Entrega — a sequência no padrão de entrega, com QC" }
};
var m = MODULOS[aba] || { nome: "?", sub: "" };
el("nome").textContent = m.nome;
el("sub").textContent = m.sub;

if (aba === "entregar") {
  // Só a frase (autor, 2026-11-08). `style.display`, não `hidden`: o CSS destes elementos ganharia do atributo.
  ["nome", "sub", "ponto", "detalhe"].forEach(function (id) { el(id).style.display = "none"; });
  el("titulo").textContent = "em desenvolvimento";
} else {
  /* ⭐ Quem decide o estado é o SUPERVISOR do app (`src/supervisor.rs`): subindo, religando, ou desistiu — com o
   * motivo e o botão. Esta página só mostra; sem a ponte (página fora do app), cai na espera simples de antes. */
  var ponte = window.__TAURI__ && window.__TAURI__.core;
  var inicio = Date.now();
  var tentar = el("tentar");
  tentar.addEventListener("click", function () {
    tentar.disabled = true;
    ponte.invoke("religar_motor", { modulo: aba }).finally(function () { setTimeout(function () { tentar.disabled = false; }, 3000); });
  });
  var pintar = function (s) {
    tentar.hidden = true;
    if (!s) {
      var seg = Math.round((Date.now() - inicio) / 1000);
      el("detalhe").textContent = "esperando " + m.motor + (seg > 3 ? " — " + seg + " s" : "");
      return;
    }
    if (s.situacao === "falhou") {
      el("ponto").className = "ponto parado";
      el("titulo").textContent = "não subiu";
      el("detalhe").textContent = m.motor + " não ficou no ar: " + (s.motivo || "sem motivo") +
        ". Ele precisa estar compilado (ou com o ambiente Python) na pasta do app dele, ao lado do Ciclo Assist.";
      tentar.hidden = !ponte;
    } else if (s.situacao === "religando") {
      el("ponto").className = "ponto parado";
      el("titulo").textContent = "religando…";
      el("detalhe").textContent = m.motor + " " + (s.motivo || "caiu") + " — tentativa " + s.tentativas + " de " +
        s.maximo + " (" + s.segundos + " s)";
    } else {
      el("ponto").className = "ponto";
      el("titulo").textContent = "ligando…";
      el("detalhe").textContent = "esperando " + m.motor + (s.segundos > 3 ? " — " + s.segundos + " s" : "");
    }
  };
  var olhar = function () {
    if (!ponte) { pintar(null); setTimeout(olhar, 1000); return; }
    ponte.invoke("estado_dos_motores").then(function (lista) {
      pintar((lista || []).filter(function (x) { return x.modulo === aba; })[0] || null);
    }, function () { pintar(null); }).finally(function () { setTimeout(olhar, 1000); });
  };
  olhar();
}
