/* A seção Conta (2026-11-07): o estado (`/conta/estado`), Entrar (o login oficial no navegador) e Sair.
 * ⛔ Nada de `confirm()` (trava a webview): o Sair pergunta no próprio botão e desarma sozinho. */
"use strict";
var el = function (id) { return document.getElementById(id); };
var PLANOS = { pro: "Pro", max: "Max", team: "Team", enterprise: "Enterprise", free: "Gratuito" };
var JANELAS = { five_hour: "Janela de 5 horas", seven_day: "Semana", seven_day_opus: "Semana · Opus",
                seven_day_sonnet: "Semana · Sonnet" };
var sondando = null;
var sairArmado = null;

function pedir(metodo, rota) {
  return fetch(rota, { method: metodo, cache: "no-store", headers: { "Content-Type": "application/json" },
                       body: metodo === "POST" ? "{}" : undefined })
    .then(function (r) { return r.json().catch(function () { return { ok: false, erro: "HTTP " + r.status }; }); });
}

function recado(texto, erro) {
  var r = el("recado");
  r.hidden = !texto;
  r.className = "recado" + (erro ? " erro" : "");
  r.textContent = texto || "";
}

function fato(lista, sim, texto) {
  var li = document.createElement("li");
  li.className = sim === null ? "" : (sim ? "sim" : "nao");
  li.textContent = texto;
  lista.appendChild(li);
}

function data(iso) {
  var d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function quandoVira(epoch) {
  if (!epoch) { return ""; }
  var minutos = Math.round(Math.max(0, epoch * 1000 - Date.now()) / 60000);
  if (minutos < 1) { return "virando agora"; }
  if (minutos < 60) { return "vira em " + minutos + " min"; }
  if (minutos < 48 * 60) { return "vira em " + Math.floor(minutos / 60) + "h" + String(minutos % 60).padStart(2, "0"); }
  return "vira " + new Date(epoch * 1000).toLocaleDateString("pt-BR", { weekday: "long", hour: "2-digit",
                                                                         minute: "2-digit" });
}

function pintarConta(e) {
  var c = e.conta || {};
  var logado = !!c.loggedIn;
  var selo = el("selo"), lista = el("fatos");
  lista.textContent = "";
  selo.className = "selo " + (logado ? "ok" : "alerta");
  selo.textContent = e.entrando ? "entrando…" : logado ? "conectada" : "sem conta";
  if (e.erro) {
    fato(lista, false, e.erro);
  } else if (logado) {
    fato(lista, true, c.email || "conta conectada");
    var plano = PLANOS[String(c.subscriptionType || "").toLowerCase()] || c.subscriptionType;
    if (plano) { fato(lista, null, "Plano " + plano + (c.orgName ? " · " + c.orgName : "")); }
    if (c.loginExpiresAt) { fato(lista, null, "O login vale até " + data(c.loginExpiresAt) + "."); }
  } else if (e.entrando) {
    fato(lista, null, "O login abriu no seu navegador. Entre por lá; esta tela se atualiza sozinha.");
  } else {
    fato(lista, false, "O Ciclo Assist não está conectado a uma conta Claude: o chat e a decupagem pelo Claude não "
         + "funcionam até você entrar. O resto do app funciona sem conta.");
  }
  el("entrar").hidden = logado || !!e.erro;
  el("entrar").disabled = !!e.entrando;
  el("entrar").textContent = e.entrando ? "Esperando o navegador…" : "Entrar com a conta Claude";
  el("sair").hidden = !logado;
  if (e.login_falhou && !logado) {
    recado(e.login_falhou === "prazo" ? "O login esperou 10 minutos e foi encerrado. Clique em Entrar de novo."
           : "O login não terminou. Clique em Entrar de novo.", true);
  }
}

function pintarUso(e) {
  var u = e.uso, caixa = el("janelas");
  caixa.textContent = "";
  if (!u || !u.uso || !Object.keys(u.uso).length) {
    el("quando").textContent = "Ainda não há número: ele aparece depois da primeira resposta do Claude no chat.";
    return;
  }
  Object.keys(JANELAS).concat(Object.keys(u.uso)).filter(function (k, i, todos) {
    return todos.indexOf(k) === i && u.uso[k] !== null && u.uso[k] !== undefined;
  }).forEach(function (k) {
    var frac = Math.max(0, Math.min(1, Number(u.uso[k]) || 0));
    var bloco = document.createElement("div");
    bloco.className = "janela";
    var titulo = document.createElement("div");
    titulo.className = "titulo";
    var b = document.createElement("b");
    b.textContent = (JANELAS[k] || k) + " — " + Math.round(frac * 100) + "%";
    var vira = document.createElement("span");
    vira.textContent = quandoVira((u.reseta_em || {})[k]);
    titulo.appendChild(b);
    titulo.appendChild(vira);
    var barra = document.createElement("div");
    barra.className = "barra" + (frac >= 0.8 ? " alto" : "");
    var i = document.createElement("i");
    i.style.width = Math.round(frac * 100) + "%";
    barra.appendChild(i);
    bloco.appendChild(titulo);
    bloco.appendChild(barra);
    caixa.appendChild(bloco);
  });
  var quando = new Date((u.quando || 0) * 1000);
  el("quando").textContent = "Medido na resposta de " + quando.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit" }) + ". O número muda a cada resposta; entre uma e outra, ele não é atualizado.";
}

function carregar() {
  return pedir("GET", "/conta/estado").then(function (e) {
    pintarConta(e);
    pintarUso(e);
    // ⭐ Enquanto o editor está no navegador, pergunta a cada 2 s; parou de entrar, para.
    if (e.entrando && !sondando) { sondando = setInterval(carregar, 2000); }
    if (!e.entrando && sondando) {
      clearInterval(sondando);
      sondando = null;
      if (e.conta && e.conta.loggedIn) { recado("Conta conectada. Pode voltar ao chat."); }
    }
    return e;
  }).catch(function () { recado("O serviço do Ciclo Assist não respondeu.", true); });
}

el("entrar").addEventListener("click", function () {
  el("entrar").disabled = true;
  recado("");
  pedir("POST", "/conta/entrar").then(function (r) {
    if (r.erro) { recado(r.erro, true); }
    carregar();
  });
});

el("sair").addEventListener("click", function () {
  var b = el("sair");
  if (!sairArmado) {
    b.textContent = "Sair mesmo?";
    b.className = "botao perigo";
    sairArmado = setTimeout(function () { sairArmado = null; b.textContent = "Sair"; b.className = "botao"; }, 4000);
    return;
  }
  clearTimeout(sairArmado);
  sairArmado = null;
  b.disabled = true;
  pedir("POST", "/conta/sair").then(function (r) {
    b.disabled = false;
    b.textContent = "Sair";
    b.className = "botao";
    if (r.estado) { pintarConta(r.estado); pintarUso(r.estado); }
    recado(r.ok ? "Você saiu da conta. Para usar o chat de novo, entre outra vez." : (r.erro || "não consegui sair"),
           !r.ok);
  });
});

carregar();
