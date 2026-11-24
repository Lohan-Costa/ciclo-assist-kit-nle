/* O FLUXO na janela (F1, `servico/fluxo.py`): o cartão do plano, o quadro do andamento com
 * Pausar/Cancelar/Retomar, a volta do modelo quando um passo falha, e as RECEITAS — tudo na aba
 * conversa (N5, 2026-11-08: a aba Fluxos saiu; quem desenha é a janela Fluxos e Agentes, quem roda é o menu ☰).
 *
 * Carregado DEPOIS do painel.js e usa as funções dele (`mostrarAprovacao`, `perguntar`,
 * `fecharOMenu`, `conversa`, `compositor`, `referencias`, `ocupado`).
 *
 * ⚠️ Tudo que vem do serviço entra por `textContent`: nome de bin, de pasta e motivo de erro são
 *    dado do projeto do cliente, nunca HTML. */
(function () {
  "use strict";

  var OPS = {
    converter_para_opatom: "converter em OP-Atom no Resolve",
    fechar_programa: "fechar o programa",
    abrir_programa: "abrir o programa e o projeto",
    importar_masters_opatom: "importar a câmera no Media Composer",
    som_direto_gerenciado: "pôr o som direto no Media Composer",
    sincronizar: "sincronizar pelo Sincronizar",
    salvar_tudo: "salvar tudo no Media Composer",
    organizar_bins: "organizar as bins",
    conformar_no_resolve: "conformar no Resolve",
    converter_para_proxy: "converter para proxy no Resolve",
    importar_no_premiere: "importar no Premiere",
    criar_merged: "criar os merged clips",
    entender_metadados_da_diaria: "entender os metadados do som",
    perguntar_ao_editor: "perguntar a você",
    confirmar_na_memoria: "confirmar na memória da produção"
  };
  var MARCA = { feito: "✓", correndo: "▶", falhou: "✕", pulado: "↷", fora: "–", a_fazer: "·", cancelado: "■" };
  /* ⭐ Os passos que PARAM NO MEIO quando o editor cancela (autor, 2026-11-04) — as esperas por um
   * programa de fora (`pendencias.conferir_cancelamento`). Os outros param ao fim do passo: no meio de
   * uma escrita de bin, parar deixaria a bin do editor fechada. Mesma lista de `fluxo._O_QUE_FICA`. */
  var PARAM_NO_MEIO = { sincronizar: true, conformar_no_resolve: true };
  var ESTADO = {
    correndo: "correndo", pausado: "pausado", esperando: "parou num passo", perguntando: "esperando sua resposta",
    interrompido: "interrompido (o serviço reiniciou)", pronto: "pronto", cancelado: "cancelado"
  };

  var PROGRAMA = { resolve: "DaVinci Resolve", premiere: "Premiere Pro", media_composer: "Media Composer" };

  /* "abrir o programa e o projeto" não diz QUAL: o nome do programa vai junto (visto no print). */
  function rotuloDoPasso(p) {
    var base = OPS[p.op] || p.op.replace(/_/g, " ");
    var prog = p.args && PROGRAMA[p.args.programa];
    if (!prog) { return base; }
    return p.op === "fechar_programa" ? "fechar o " + prog : p.op === "abrir_programa" ? "abrir o " + prog : base;
  }

  function el(tag, classe, texto) {
    var e = document.createElement(tag);
    if (classe) { e.className = classe; }
    if (texto !== undefined) { e.textContent = texto; }
    return e;
  }

  /* "{diaria} CAMERA" com os parâmetros → "D01 CAMERA"; "{conv.pasta}" → "(a saída de conv)". */
  function preencher(valor, params) {
    if (Array.isArray(valor)) { return valor.map(function (v) { return preencher(v, params); }).join(", "); }
    if (valor && typeof valor === "object") { return JSON.stringify(valor); }
    return String(valor === undefined || valor === null ? "" : valor).replace(
      /\{([a-zA-Z_][a-zA-Z0-9_]*)((?:\.[a-zA-Z0-9_]+)*)\}/g,
      function (_, raiz, resto) {
        if (resto) { return "(a saída de " + raiz + ")"; }
        return params && params[raiz] !== undefined ? String(params[raiz]) : "{" + raiz + "}";
      });
  }

  function linhaDoPasso(p, n, params) {
    var li = el("li", "fluxo-passo");
    var cab = el("div", "cab");
    cab.appendChild(el("span", "op", rotuloDoPasso(p)));
    li.appendChild(cab);
    var args = p.args || {};
    var partes = Object.keys(args).map(function (k) {
      var v = preencher(args[k], params);
      return v ? k + ": " + v : "";
    }).filter(Boolean);
    if (partes.length) { li.appendChild(el("div", "prosa", partes.join(" · "))); }
    return li;
  }

  /* ⭐ O cartão do plano: o editor aprova PASSO A PASSO o que vai acontecer, com os valores
   * preenchidos — não um JSON. É o "um cartão em vez de oito 'permitir'" do plano. */
  window.cartaoDoFluxo = function (cartao, entrada) {
    var plano = entrada.plano || {};
    var params = plano.parametros || {};
    var nome = el("div", "campo");
    nome.appendChild(el("span", "rot", "fluxo"));
    nome.appendChild(el("span", "", preencher(plano.nome || "", params) +
      (entrada.receita_de ? "  (receita " + entrada.receita_de + ")" : "")));
    cartao.appendChild(nome);
    var lista = el("ol", "itens");
    (plano.passos || []).forEach(function (p, i) { lista.appendChild(linhaDoPasso(p, i, params)); });
    cartao.appendChild(lista);
    cartao.appendChild(el("div", "fluxo-nota",
      "Roda sozinho, um passo depois do outro. Pausar vale ao fim do passo em curso; Cancelar para na " +
      "hora durante o sync do Sincronizar e o conform, e ao fim do passo nos outros."));
  };

  /* ── o quadro do andamento ─────────────────────────────────────────────── */

  var quadro = el("div", "fluxo-quadro");
  quadro.hidden = true;
  var lugarDoQuadro = document.getElementById("fluxosQuadro");
  if (lugarDoQuadro) { lugarDoQuadro.appendChild(quadro); }
  var abaFluxos = document.getElementById("abaFluxos");
  var areaFluxos = document.getElementById("conversa");
  /* ⭐ O cartão do plano e o formulário nascem na aba Fluxos (`mostrarAprovacao` pergunta aqui). */
  window.destinoDoFluxo = function () { return areaFluxos; };
  var ultimo = null;
  var aberto = true;           // a lista de passos à vista
  var dispensado = "";         // o id do fluxo terminado que o editor fechou
  var temporizador = null;

  function chamar(rota) {
    return fetch(rota, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.fluxo) { pintar(d.fluxo); }
        if (d && !d.ok && d.motivo) { recado(d.motivo); }
        agendar(400);
      })
      .catch(function () { recado("não consegui falar com o serviço"); });
  }

  var recadoDoQuadro = "";
  function recado(texto) { recadoDoQuadro = texto; if (ultimo) { pintar(ultimo); } }

  function botao(rotulo, rota, classe) {
    var b = el("button", "botao compacto" + (classe ? " " + classe : ""), rotulo);
    b.type = "button";
    b.addEventListener("click", function () { b.disabled = true; recadoDoQuadro = ""; chamar(rota); });
    return b;
  }

  /* ⭐ O botão da aba diz o estado do fluxo: com o editor no chat, um fluxo parado num passo
   *    não pode ficar escondido atrás de uma aba. */
  function marcarAba(f) {
    if (!abaFluxos) { return; }
    // ⚠️ Pronto e cancelado não acendem: o ponto existe para chamar o editor, e um fluxo terminado não
    //   pede nada dele (o quadro continua na aba até ele fechar).
    var e = f && ["correndo", "esperando", "perguntando", "pausado", "interrompido"].indexOf(f.estado) >= 0 ? f.estado : "";
    if (e) { abaFluxos.dataset.estado = e; } else { delete abaFluxos.dataset.estado; }
    abaFluxos.title = e ? "Fluxo: " + (ESTADO[e] || e) : "";
  }

  /* ⭐ O fluxo que TERMINOU antes desta sessão da janela não volta à tela (autor, 2026-11-04: "um card
   *    preso como memória… não devia aparecer em uma sessão nova"). Só aparece terminado o que esta
   *    janela viu vivo, ou que começou daqui. Parado num passo ou interrompido continua aparecendo,
   *    sempre: esses pedem uma decisão do editor. */
  var vistosVivos = {};
  var VIVOS = ["correndo", "esperando", "perguntando", "pausado", "interrompido"];

  function esconder() {
    quadro.hidden = true;
    if (lugarDoQuadro) { lugarDoQuadro.classList.remove("ativo"); }
  }

  /* ⭐ N5: um leigo responde aqui mesmo, sem abrir a janela de nodes. ⛔ Com o cartão à vista o quadro não se redesenha: a leitura de 10 em 10 s apagaria o que ele digita. */
  var chaveDoCartao = "";

  function formularioDePerguntas(passo) {
    var caixa = el("div", "fluxo-pergunta"), areas = [];
    caixa.appendChild(el("div", "fluxo-nota", passo.saida.titulo || "O fluxo precisa de uma resposta:"));
    (passo.saida.perguntas || []).forEach(function (p) {
      var area = el("textarea");
      area.setAttribute("aria-label", p.texto);
      caixa.appendChild(el("div", "rot", p.texto));
      caixa.appendChild(area);
      var chips = el("div", "fluxo-chips");
      (p.opcoes || []).concat(["não sei"]).forEach(function (o) {
        var b = el("button", "botao compacto", o);
        b.type = "button";
        b.addEventListener("click", function () { area.value = o; });
        chips.appendChild(b);
      });
      caixa.appendChild(chips);
      areas.push({ p: p, area: area });
    });
    var enviar = el("button", "botao compacto", "Responder");
    enviar.type = "button";
    enviar.addEventListener("click", function () {
      enviar.disabled = true;
      enviarCartao("/fluxo/responder", { respostas: areas.map(function (a) { return { pergunta: a.p.texto, resposta: a.area.value }; }) }, caixa, enviar);
    });
    caixa.appendChild(enviar);
    return caixa;
  }

  function formularioDeConfirmacao(passo) {
    var c = passo.saida.confirmar, caixa = el("div", "fluxo-pergunta"), nome = null, marca = null;
    caixa.appendChild(el("div", "fluxo-nota", "Guardar na memória da produção? Só o seu clique grava."));
    c.regras.forEach(function (r) {
      var item = el("div", "fluxo-regra");
      item.appendChild(el("b", "", r.forma));
      item.appendChild(el("div", "", r.molde + (r.arquivos ? " · " + r.arquivos + " arquivo" + (r.arquivos > 1 ? "s" : "") : "")));
      if (r.exemplo) { item.appendChild(el("div", "fluxo-nota", r.exemplo)); }
      caixa.appendChild(item);
    });
    if (c.nao_se_sabe.length) { caixa.appendChild(el("div", "fluxo-nota", "Você disse não saber: " + c.nao_se_sabe.join(", "))); }
    if (c.memoria) {
      caixa.appendChild(el("div", "fluxo-nota", "Produção: " + c.memoria));
    } else {
      nome = el("input");
      nome.type = "text";
      nome.setAttribute("aria-label", "Nome da produção");
      caixa.appendChild(el("div", "rot", "De que produção é esta diária? Se for nova, escreva o nome dela."));
      caixa.appendChild(nome);
      var chips = el("div", "fluxo-chips");
      c.sugestoes.forEach(function (o) {
        var b = el("button", "botao compacto", o);
        b.type = "button";
        b.addEventListener("click", function () { nome.value = o; });
        chips.appendChild(b);
      });
      caixa.appendChild(chips);
    }
    if (c.projeto_aberto && c.projeto_aberto !== c.memoria) {
      var rot = el("label", "fluxo-marca");
      marca = el("input");
      marca.type = "checkbox";
      rot.appendChild(marca);
      rot.appendChild(document.createTextNode(" O projeto aberto (" + c.projeto_aberto + ") é desta produção"));
      caixa.appendChild(rot);
    }
    var linha = el("div", "fluxo-chips");
    function responder(gravar, botao) {
      botao.disabled = true;
      enviarCartao("/fluxo/confirmar", { gravar: gravar, producao: nome ? nome.value : "", apelido: !!(marca && marca.checked) }, caixa, botao);
    }
    var sim = el("button", "botao compacto", "Gravar na memória"), nao = el("button", "botao compacto", "Não gravar");
    sim.type = nao.type = "button";
    sim.addEventListener("click", function () { responder(true, sim); });
    nao.addEventListener("click", function () { responder(false, nao); });
    linha.appendChild(sim);
    linha.appendChild(nao);
    caixa.appendChild(linha);
    return caixa;
  }

  function enviarCartao(rota, corpo, caixa, botao) {
    var aviso = caixa.querySelector(".fluxo-recado");
    if (aviso) { aviso.remove(); }
    function falhou(texto) { botao.disabled = false; caixa.appendChild(el("div", "fluxo-recado", texto)); }
    postar(rota, corpo).then(function (d) {
      if (d && d.ok) { chaveDoCartao = ""; if (d.fluxo) { pintar(d.fluxo); } agendar(400); return; }
      falhou((d && d.motivo) || "não deu");
    }).catch(function () { falhou("não consegui falar com o serviço"); });
  }

  function pintar(f) {
    var cartao = f && f.estado === "perguntando" ? f.id + "/" + f.atual + "/" + ((f.passos[f.atual] || {}).tentativas || 0) : "";
    if (cartao && cartao === chaveDoCartao && !quadro.hidden) { ultimo = f; return; }
    chaveDoCartao = cartao;
    ultimo = f;
    marcarAba(f);
    if (f && VIVOS.indexOf(f.estado) >= 0) { vistosVivos[f.id] = true; }
    if (!f || (VIVOS.indexOf(f.estado) < 0 && (dispensado === f.id || !vistosVivos[f.id]))) {
      esconder();
      return;
    }
    quadro.hidden = false;
    if (lugarDoQuadro) { lugarDoQuadro.classList.add("ativo"); }
    quadro.textContent = "";
    quadro.dataset.estado = f.estado;

    var cab = el("div", "fluxo-cab");
    var seta = el("button", "fluxo-seta", aberto ? "▾" : "▸");
    seta.type = "button";
    seta.title = aberto ? "Esconder os passos" : "Mostrar os passos";
    seta.addEventListener("click", function () { aberto = !aberto; pintar(ultimo); });
    cab.appendChild(seta);
    cab.appendChild(el("span", "fluxo-nome", f.nome));
    // ⭐ O node fora do caminho não conta no total: "pronto · 3/4" parecia que faltou um.
    var foraDoCaminho = f.passos.filter(function (p) { return p.estado === "fora"; }).length;
    cab.appendChild(el("span", "fluxo-estado", (ESTADO[f.estado] || f.estado) +
      " · " + f.feitos + "/" + (f.total - foraDoCaminho) + (foraDoCaminho ? " · " + foraDoCaminho + " fora do caminho" : "")));
    quadro.appendChild(cab);

    // ⭐ Os botões ficam ABAIXO da lista (autor, 2026-11-02), presos ao pé do quadro (`position: sticky`):
    //   na janela do app (prova de 2026-11-01) o quadro fica espremido e, no fim de uma lista longa, eles
    //   caíam para fora da área à vista — o sticky os mantém à vista com a lista rolando por trás.
    var acoes = el("div", "fluxo-acoes");
    if (f.estado === "correndo") {
      var emCurso = f.passos[f.atual] || {};
      var noMeio = !!PARAM_NO_MEIO[emCurso.op];
      var pausar = botao(f.pedido === "pausar" ? "pausando ao fim do passo…" : "Pausar", "/fluxo/pausar");
      pausar.title = "Para ao fim do passo em curso; Retomar segue do próximo.";
      var cancelar = botao(f.pedido === "cancelar" ? (noMeio ? "cancelando…" : "cancelando ao fim do passo…")
                                                    : "Cancelar", "/fluxo/cancelar", "perigo");
      cancelar.title = noMeio ? "Para agora: este passo espera um programa de fora, e parar de esperar é seguro."
                              : "Para ao fim deste passo: no meio dele, parar deixaria o projeto pela metade.";
      if (f.pedido) { pausar.disabled = cancelar.disabled = true; }
      acoes.appendChild(pausar);
      acoes.appendChild(cancelar);
    } else if (f.estado === "esperando") {
      acoes.appendChild(botao("Tentar de novo", "/fluxo/retomar"));
      acoes.appendChild(botao("Pular este passo", "/fluxo/pular"));
      acoes.appendChild(botao("Cancelar", "/fluxo/cancelar", "perigo"));
    } else if (f.estado === "perguntando") {
      acoes.appendChild(botao("Cancelar", "/fluxo/cancelar", "perigo"));
    } else if (f.estado === "pausado" || f.estado === "interrompido") {
      acoes.appendChild(botao(f.estado === "interrompido" ? "Retomar do passo " + (f.atual + 1) : "Retomar",
                              "/fluxo/retomar"));
      acoes.appendChild(botao("Cancelar", "/fluxo/cancelar", "perigo"));
    } else {
      var fechar = el("button", "botao compacto", "Fechar");
      fechar.type = "button";
      fechar.addEventListener("click", function () { dispensado = f.id; pintar(f); });
      acoes.appendChild(fechar);
    }

    var a = f.andamento || {};
    if (f.estado === "correndo" && f.atual < f.total) {
      var p = f.passos[f.atual];
      var linha = el("div", "fluxo-agora reticencias",
        "passo " + (f.atual + 1) + ": " + (a.etapa || rotuloDoPasso(p)) +
        (a.detalhe ? " — " + a.detalhe : "") +
        (typeof a.fracao === "number" ? " (" + Math.round(a.fracao * 100) + "%)" : ""));
      quadro.appendChild(linha);
      // ⭐ A barra (autor, 2026-11-04: "para o usuário é um feedback extremamente importante"): o sync do
      //   Sincronizar e o De Lá Pra Cá contam quanto andaram. ⚠️ Só com fração de verdade — sem ela, as
      //   reticências dizem que há movimento sem prometer um fim que ninguém mediu.
      if (typeof a.fracao === "number") {
        var barra = el("div", "fluxo-barra");
        var cheio = el("i");
        cheio.style.width = Math.round(a.fracao * 100) + "%";
        barra.appendChild(cheio);
        quadro.appendChild(barra);
      }
    }

    // ⭐ Com um cartão à espera, a lista recolhe: visto na prova, o botão de gravar ficava abaixo da dobra do quadro.
    if (aberto && f.estado !== "perguntando") {
      var lista = el("ol", "fluxo-passos");
      f.passos.forEach(function (p) {
        var li = el("li", "fluxo-p", "");
        li.dataset.estado = p.estado;
        li.appendChild(el("span", "marca", MARCA[p.estado] || "·"));
        li.appendChild(el("span", "", rotuloDoPasso(p) +
          (p.segundos && p.estado === "feito" ? "  " + p.segundos + " s" : "")));
        if (p.motivo) { li.appendChild(el("div", "motivo", p.motivo)); }
        if (p.avisos && p.avisos.length) { li.appendChild(el("div", "aviso-p", "⚠ " + p.avisos.join(" · "))); }
        lista.appendChild(li);
      });
      quadro.appendChild(lista);
    }

    if (recadoDoQuadro) { quadro.appendChild(el("div", "fluxo-recado", recadoDoQuadro)); }
    if (f.estado === "esperando" && passouDoTeto(f)) {
      quadro.appendChild(el("div", "fluxo-nota", "Este passo já falhou " + (f.passos[f.atual] || {}).tentativas +
        " vezes; o Ciclo Assist não insiste sozinho. Decida pelos botões."));
    }
    if (f.estado === "interrompido") {
      // ⚠️ O passo cortado pelo reinício pode ter rodado pela metade (uma importação, por exemplo):
      //   retomar o refaz, e quem sabe se isso é seguro é o editor, olhando o programa.
      quadro.appendChild(el("div", "fluxo-nota", "O serviço reiniciou no meio do passo " + (f.atual + 1) +
        ". Ele pode ter rodado pela metade: confira no programa antes de retomar (retomar o refaz)."));
    }
    if (f.estado === "perguntando" && f.passos[f.atual]) {
      var pendente = f.passos[f.atual];
      quadro.appendChild(pendente.saida && pendente.saida.confirmar ? formularioDeConfirmacao(pendente) : formularioDePerguntas(pendente));
    }
    quadro.appendChild(acoes);


    if (f.estado === "esperando") { chamarOModelo(f); }
  }

  /* ⭐ Decisão do autor (2026-11-01): passo que falha CHAMA O MODELO. Uma vez por falha (a chave
   * é fluxo + passo + tentativa, guardada para o Reload não perguntar de novo), e com TETO.
   * ⛔⛔ E num turno MAGRO (`POST /fluxo/conselho`, `motor/conselho.py`): antes era um turno da
   * CONVERSA — persona, todas as ferramentas, o histórico — e custou 116 mil tokens na prova para
   * pular um passo, com um conselho velho tirado do histórico. Agora o modelo só lê o fluxo e
   * responde a ação; com o automático ligado o serviço a aplica, desligado ela vira um botão. */
  function chaveDaFalha(f) {
    var p = f.passos[f.atual] || {};
    return f.id + ":" + f.atual + ":" + (p.tentativas || 0);
  }
  function jaChamei(chave) {
    try { return localStorage.getItem("fluxo.chamado") === chave; } catch (e) { return chamado === chave; }
  }
  var chamado = "";
  /* ⛔ O TETO: o conselho vem nas DUAS primeiras falhas de um passo (`tentativas`, gravado em
   * disco pelo serviço — que confere de novo: `fluxo.CONSELHOS_POR_PASSO`); da terceira em diante
   * a decisão é do editor, pelos botões. */
  var CHAMADAS_POR_PASSO = 2;
  function passouDoTeto(f) {
    var p = f.passos[f.atual] || {};
    return (p.tentativas || 0) > CHAMADAS_POR_PASSO;
  }
  var NOMES_DAS_ACOES = { tentar_de_novo: "Tentar de novo", pular: "Pular o passo", cancelar: "Cancelar o fluxo" };
  function chamarOModelo(f) {
    var chave = chaveDaFalha(f);
    if (passouDoTeto(f) || jaChamei(chave) || typeof bloco !== "function") { return; }
    chamado = chave;
    try { localStorage.setItem("fluxo.chamado", chave); } catch (e) { /* sem disco: só memória */ }
    var p = f.passos[f.atual] || {};
    var b = bloco("ciclo assist · fluxo", "de-ele");
    b.texto.className = "texto pensando reticencias";
    b.texto.textContent = "o passo " + (f.atual + 1) + " (" + rotuloDoPasso(p) + ") falhou; pensando no que fazer";
    fetch("/fluxo/conselho", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(function (r) { return r.json(); })
      .then(function (c) { mostrarConselho(b, c); agendar(400); })
      .catch(function () { b.texto.className = "texto"; b.texto.textContent = "não consegui falar com o serviço"; });
  }
  function mostrarConselho(b, c) {
    b.texto.className = "texto";
    b.texto.textContent = "";
    if (!c || !c.ok) { b.texto.textContent = (c && c.motivo) || "sem conselho"; return; }
    b.texto.appendChild(el("div", "", c.explicacao));
    var tokens = c.uso && c.uso.tokens ? " · " + Math.round(c.uso.tokens / 100) / 10 + " mil tokens" : "";
    if (c.aplicado) {
      b.texto.appendChild(el("div", "fluxo-nota", "feito sozinho (automático): " +
        (NOMES_DAS_ACOES[c.acao] || c.acao).toLowerCase() + tokens));
      return;
    }
    if (c.motivo) { b.texto.appendChild(el("div", "fluxo-nota", c.motivo)); }
    if (c.acao === "esperar" || !NOMES_DAS_ACOES[c.acao]) {
      if (tokens) { b.texto.appendChild(el("div", "fluxo-nota", tokens.slice(3))); }
      return;
    }
    var botao = el("button", "botao compacto", NOMES_DAS_ACOES[c.acao]);
    botao.type = "button";
    botao.addEventListener("click", function () {
      botao.disabled = true;
      fetch("/fluxo/decidir", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ acao: c.acao, args: c.args || {} }) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.fluxo) { pintar(d.fluxo); }
          if (d && !d.ok && d.motivo) { recado(d.motivo); botao.disabled = false; }
          agendar(400);
        })
        .catch(function () { botao.disabled = false; recado("não consegui falar com o serviço"); });
    });
    b.texto.appendChild(botao);
    if (tokens) { b.texto.appendChild(el("div", "fluxo-nota", tokens.slice(3))); }
  }

  function agendar(ms) {
    clearTimeout(temporizador);
    temporizador = setTimeout(ler, ms);
  }

  function ler() {
    fetch("/fluxo", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var f = d && d.fluxo;
        pintar(f);
        // ⚠️ Correndo, a cada 1,5 s (o andamento é o que diz "não travou"); parado, a cada 10 s
        //    — é uma leitura de memória, e um fluxo pode começar pelo cartão de outra aba.
        agendar(f && f.estado === "correndo" ? 1500 : 10000);
      })
      .catch(function () { agendar(15000); });
  }
  /* Chamada quando o editor aprova um fluxo: o próximo que aparecer é DESTA sessão, mesmo que termine
   * antes da primeira leitura (um fluxo de um passo rápido). */
  window.acompanharFluxo = function (id) {
    dispensado = "";
    if (id) { vistosVivos[id] = true; }
    agendar(300);
  };
  ler();

  /* O menu ☰ carrega um fluxo salvo (N5): o formulário nasce na conversa. */
  window.carregarReceita = function (r) { formulario(r); };

  function postar(rota, corpo) {
    return fetch(rota, { method: "POST", headers: { "Content-Type": "application/json" },
                         body: JSON.stringify(corpo || {}) }).then(function (x) { return x.json(); });
  }

  function nomeDe(c) { return String(c).split(/[\\/]/).filter(Boolean).pop() || c; }

  function casaExtensao(c, spec) {
    var exts = spec.extensoes || [];
    if (!exts.length) { return true; }
    var m = /\.([^.\\/]+)$/.exec(String(c));
    return !!m && exts.indexOf(m[1].toLowerCase()) >= 0;
  }

  /* ⭐⭐ Um campo de CAMINHO (autor, 2026-11-01): "escrever caminho na mão é a pior experiência de
   * usuário possível". Não há caixa de texto: o que vale é a LISTA do que foi escolhido — pelo botão
   * (o diálogo do sistema, `/receitas/escolher`, que AUTORIZA o que veio) ou por arrasto do
   * Explorer/Finder para cima do campo (o tratamento geral do painel autoriza o que chega). */
  function campoDeCaminho(spec) {
    var caixa = el("div", "receita-caminhos");
    var lista = el("div", "receita-itens");
    var acoes = el("div", "receita-botoes");
    var escolhidos = [];
    var ouvintes = [];
    var vazio = spec.tipo === "pasta" ? "nenhuma pasta: escolha ou arraste aqui"
                                      : "nenhum arquivo: escolha ou arraste aqui";

    function mudou() { pintar(); ouvintes.forEach(function (f) { f(escolhidos.slice()); }); }
    function pintar() {
      lista.textContent = "";
      if (!escolhidos.length) { lista.appendChild(el("span", "receita-vazio", vazio)); return; }
      escolhidos.forEach(function (c, i) {
        var item = el("span", "receita-item");
        item.title = c;
        item.appendChild(el("span", "", nomeDe(c)));
        var tirar = el("button", "receita-tirar", "×");
        tirar.type = "button";
        tirar.setAttribute("aria-label", "Tirar " + nomeDe(c));
        tirar.addEventListener("click", function () { escolhidos.splice(i, 1); mudou(); });
        item.appendChild(tirar);
        lista.appendChild(item);
      });
    }
    function por(caminhos) {
      caminhos = caminhos.filter(function (c) { return c && escolhidos.indexOf(c) < 0; });
      if (!caminhos.length) { return; }
      escolhidos = spec.multiplos ? escolhidos.concat(caminhos) : [caminhos[0]];
      mudou();
    }

    var botao = el("button", "botao compacto", spec.multiplos ? "Escolher…"
                   : (spec.tipo === "pasta" ? "Escolher a pasta…" : "Escolher o arquivo…"));
    botao.type = "button";
    botao.addEventListener("click", function () {
      botao.disabled = true;
      postar("/receitas/escolher", { tipo: spec.tipo, multiplos: !!spec.multiplos,
                                     extensoes: spec.extensoes || [], titulo: spec.rotulo || "" })
        .then(function (d) {
          if (d && d.caminhos && d.caminhos.length) { por(d.caminhos); }
          else if (d && d.erro) { lista.appendChild(el("span", "receita-erro", d.erro)); }
        })
        .catch(function () { lista.appendChild(el("span", "receita-erro", "não consegui abrir o seletor")); })
        .finally(function () { botao.disabled = false; });
    });
    acoes.appendChild(botao);

    // ⚠️ O arrasto NÃO é tratado aqui: quem o recebe é o painel (na janela do app, o alvo nativo
    //    nem dispara o `drop` do HTML), que o entrega a `cicloFormulario.receber` com o ponto.
    caixa.appendChild(lista);
    caixa.appendChild(acoes);
    pintar();
    return {
      raiz: caixa,
      spec: spec,
      valor: function () { return spec.multiplos ? escolhidos.slice() : (escolhidos[0] || ""); },
      vazio: function () { return !escolhidos.length; },
      aceita: function (item) {
        return (spec.tipo === "pasta") === !!item.pasta && (item.pasta || casaExtensao(item.caminho, spec));
      },
      por: por,
      aoMudar: function (f) { ouvintes.push(f); if (escolhidos.length) { f(escolhidos.slice()); } }
    };
  }

  /* ⭐⭐ O arrasto com o formulário ABERTO (autor, 2026-11-01): "se o usuário abrir o fluxo, o drag and
   * drop passa a ser pra cada área que precisamos indicar os itens". Solto SOBRE uma área: vai para
   * ela, se for do tipo dela. Solto em outro ponto: cada item vai para a área do seu tipo (a timeline
   * pela extensão, a pasta para as pastas). O que não serve a área nenhuma é DITO, nunca calado. */
  var formAtivo = null;

  function areaNoPonto(x, y) {
    if (!formAtivo || x < 0) { return null; }
    var el0 = document.elementFromPoint(x, y);
    var caixa = el0 && el0.closest ? el0.closest(".receita-caminhos") : null;
    if (!caixa) { return null; }
    return formAtivo.areas.filter(function (a) { return a.raiz === caixa; })[0] || null;
  }

  function distribuir(itens, alvo) {
    var sobraram = [];
    var usados = [];
    itens.forEach(function (item) {
      var area = null;
      if (alvo) { area = alvo.aceita(item) ? alvo : null; }
      else {
        var aceitam = formAtivo.areas.filter(function (a) { return a.aceita(item); });
        area = aceitam.filter(function (a) { return a.vazio() || a.spec.multiplos; })[0] || aceitam[0] || null;
      }
      if (area) { area.por([item.caminho]); usados.push(item.caminho); }
      else { sobraram.push(item); }
    });
    if (sobraram.length) {
      formAtivo.avisar(sobraram.map(function (i) { return nomeDe(i.caminho); }).join(", ") +
        (alvo ? " não serve para “" + (alvo.spec.rotulo || "esta área") + "”."
              : " não serve para nenhuma área deste fluxo."));
    }
    return usados;
  }

  window.cicloFormulario = {
    // ⛔ Só com a aba Fluxos À VISTA: o formulário fica vivo na aba escondida, e um arrasto para o
    //   chat viraria campo de receita em vez de anexo da pergunta.
    aberto: function () {
      return !!(formAtivo && document.body.contains(formAtivo.forma) && formAtivo.forma.offsetParent);
    },
    sobre: function (x, y) {
      if (!formAtivo) { return; }
      var a = areaNoPonto(x, y);
      formAtivo.areas.forEach(function (b) { b.raiz.classList.toggle("realce", b === a); });
    },
    receber: function (caminhos, x, y) {
      if (!formAtivo) { return; }
      var alvo = areaNoPonto(x, y);
      // O gesto AUTORIZA (ADR 0005), pelo mesmo caminho do chat — mas sem virar anexo da conversa.
      postar("/arrastados", { caminhos: caminhos }).then(function (d) {
        var itens = ((d && d.arquivos) || []).filter(function (a) { return a.existe !== false; })
          .map(function (a) { return { caminho: a.caminho, pasta: !!a.pasta }; });
        if (!itens.length) { formAtivo.avisar("não consegui ler o que foi arrastado"); return; }
        distribuir(itens, alvo);
      }).catch(function () { formAtivo.avisar("não consegui falar com o serviço"); });
    }
  };

  /* ⭐⭐ A TIMELINE se escolhe da LISTA do que existe no arquivo (autor, 2026-11-01): "podemos
   * pressupor que o usuário não sabe o nome exato da timeline que busca… só a lista consegue ser
   * útil". Uma só: usada e DITA. Várias: a lista, sem pré-escolha — escolher é do editor. */
  function campoDeTimeline(spec, origem) {
    var caixa = el("div", "receita-timeline");
    var escolhida = "";
    var pedido = 0;
    caixa.appendChild(el("span", "receita-vazio", "escolha antes o arquivo"));
    origem.aoMudar(function (cs) {
      var arquivo = cs[0] || "";
      escolhida = "";
      caixa.textContent = "";
      if (!arquivo) { caixa.appendChild(el("span", "receita-vazio", "escolha antes o arquivo")); return; }
      var meu = ++pedido;
      caixa.appendChild(el("span", "receita-vazio reticencias", "lendo as timelines de " + nomeDe(arquivo)));
      postar("/receitas/timelines", { arquivo: arquivo }).then(function (d) {
        if (meu !== pedido) { return; }       // o editor trocou de arquivo no meio
        caixa.textContent = "";
        var tls = (d && d.timelines) || [];
        if (!d || !d.ok) { caixa.appendChild(el("span", "receita-erro", (d && d.motivo) || "não consegui ler o arquivo")); return; }
        if (!tls.length) { caixa.appendChild(el("span", "receita-erro", "não achei timeline nenhuma nesse arquivo")); return; }
        if (tls.length === 1) {
          escolhida = tls[0].nome;
          caixa.appendChild(el("span", "", "a única do arquivo: " + tls[0].nome +
            (tls[0].planos ? " (" + tls[0].planos + " planos)" : "")));
          return;
        }
        var sel = el("select");
        var nenhuma = el("option", "", "— escolha entre as " + tls.length + " timelines do arquivo —");
        nenhuma.value = "";
        sel.appendChild(nenhuma);
        tls.forEach(function (t) {
          var o = el("option", "", t.nome + (t.planos ? "  (" + t.planos + " planos)" : ""));
          o.value = t.nome;
          sel.appendChild(o);
        });
        sel.addEventListener("change", function () { escolhida = sel.value; });
        caixa.appendChild(sel);
      }).catch(function () {
        if (meu === pedido) { caixa.textContent = ""; caixa.appendChild(el("span", "receita-erro", "não consegui falar com o serviço")); }
      });
    });
    return { raiz: caixa, valor: function () { return escolhida; } };
  }

  function formulario(r) {
    if (formAtivo && formAtivo.forma) { formAtivo.forma.remove(); }
    var forma = el("div", "aprovacao receita-forma");
    forma.appendChild(el("div", "cabeca", r.titulo.replace(/\{[^}]*\}/g, " ").replace(/\s+/g, " ").trim() || r.nome));
    forma.appendChild(el("div", "fluxo-nota", r.descricao));
    // ⭐ N5: o formulário é o consentimento, como o Executar da janela: mostra o que vai rodar e o preço antes do clique.
    var passos = el("ol", "itens");
    (r.passos || []).forEach(function (p) { passos.appendChild(el("li", "fluxo-passo", rotuloDoPasso(p))); });
    forma.appendChild(passos);
    if (r.ia && r.ia.texto) { forma.appendChild(el("div", "fluxo-nota", r.ia.texto)); }
    var campos = {};

    Object.keys(r.parametros).forEach(function (nome) {
      var spec = r.parametros[nome];
      var rotulo = el("div", "receita-campo");
      rotulo.appendChild(el("span", "rot", (spec.rotulo || nome) + (spec.opcional ? " (opcional)" : "")));
      var campo;
      if (spec.tipo === "pasta" || spec.tipo === "arquivo") {
        campo = campoDeCaminho(spec);
      } else if (spec.tipo === "timeline") {
        campo = campos[spec.de] ? campoDeTimeline(spec, campos[spec.de])
          : { raiz: el("span", "receita-erro", "a receita não diz de que arquivo ler"), valor: function () { return ""; } };
      } else if (spec.tipo === "escolha") {
        var sel = el("select");
        (spec.opcoes || []).forEach(function (op) {
          var o = el("option", "", op); o.value = op;
          if (op === spec.padrao) { o.selected = true; }
          sel.appendChild(o);
        });
        campo = { raiz: sel, valor: function () { return sel.value; } };
      } else {
        var inp = el("input");
        inp.type = "text";
        inp.value = spec.padrao || "";
        campo = { raiz: inp, valor: function () { return inp.value; } };
      }
      rotulo.appendChild(campo.raiz);
      campos[nome] = campo;
      forma.appendChild(rotulo);
    });

    var erro = el("div", "fluxo-recado");
    erro.hidden = true;
    forma.appendChild(erro);
    // ⚠️ O aviso ("falta preencher…") some quando o editor mexe em qualquer campo: parado ali depois
    //    de ele já ter escolhido, ele dizia o contrário da tela (visto na conferência de 2026-11-01).
    function limparAviso() { erro.hidden = true; }
    forma.addEventListener("change", limparAviso);
    forma.addEventListener("input", limparAviso);
    Object.keys(campos).forEach(function (k) { if (campos[k].aoMudar) { campos[k].aoMudar(limparAviso); } });
    var acoes = el("div", "acoes");
    var cancelar = el("button", "recusar", "Cancelar");
    cancelar.type = "button";
    cancelar.addEventListener("click", function () { forma.remove(); formAtivo = null; });
    var seguir = el("button", "permitir", "Executar");
    seguir.type = "button";
    seguir.addEventListener("click", function () {
      var valores = {};
      Object.keys(campos).forEach(function (k) { valores[k] = campos[k].valor(); });
      seguir.disabled = true;
      seguir.textContent = "Conferindo…";     // ⭐ Com um diálogo no Media Composer a conferência leva ~20 s (medido): sem isto o clique parece não ter pegado.
      erro.hidden = true;
      postar("/oficina/executar", { nome: r.nome, parametros: valores })
        .then(function (d) {
          if (d && d.ok) { forma.remove(); formAtivo = null; window.acompanharFluxo(d.fluxo && d.fluxo.id); return; }
          erro.hidden = false;
          erro.textContent = (d && d.motivo) || "não deu";
          seguir.textContent = "Executar";
          seguir.disabled = false;
        })
        .catch(function () { erro.hidden = false; erro.textContent = "não consegui falar com o serviço"; seguir.disabled = false; });
    });
    acoes.appendChild(cancelar);
    acoes.appendChild(seguir);
    forma.appendChild(acoes);
    areaFluxos.appendChild(forma);

    formAtivo = {
      forma: forma,
      areas: Object.keys(campos).map(function (k) { return campos[k]; }).filter(function (c) { return !!c.aceita; }),
      avisar: function (texto) { erro.hidden = false; erro.textContent = texto; }
    };
    // ⭐ O que o editor JÁ tinha anexado ao chat preenche as áreas pelo tipo (autor, 2026-11-01:
    //   "se o usuário informar os arquivos antes de ativar o fluxo, o chat já usa os arquivos
    //   anexados"). O que foi usado sai da barra de anexos: ele mudou de lugar, não se duplicou.
    var doChat = (window.referencias || referencias || [])
      .filter(function (a) { return a && a.tipo === "arquivo" && a.caminho; })
      .map(function (a) { return { caminho: a.caminho, pasta: !!a.pasta || a.papel === "mídias" }; });
    if (doChat.length) {
      var usados = [];
      doChat.forEach(function (item) {
        var area = formAtivo.areas.filter(function (a) { return a.aceita(item) && (a.vazio() || a.spec.multiplos); })[0];
        if (area) { area.por([item.caminho]); usados.push(item.caminho); }
      });
      if (usados.length) {
        referencias = referencias.filter(function (a) { return usados.indexOf(a.caminho) < 0; });
        if (typeof pintarAnexos === "function") { pintarAnexos(); }
        erro.hidden = true;
      }
    }
    forma.scrollIntoView({ block: "nearest" });
  }
})();
