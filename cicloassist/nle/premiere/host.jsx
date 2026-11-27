/*
 * host.jsx — o que o Ciclo Assist lê do Premiere. LEITURA, organizar, montar e editar a timeline (estes, nas versões sem o MCP nativo).
 *
 * Não mora na extensão: o painel servido o busca em /premiere/host.jsx e o avalia com
 * evalScript. Mudar este arquivo é Reload no painel, sem reinstalar nada.
 *
 * Toda função devolve TEXTO JSON (o evalScript só transporta texto) e, em falha,
 * {"erro": "..."} — nunca lança: exceção vira "EvalScript error." sem dizer qual.
 *
 * ES3: sem JSON garantido, sem let, sem arrow, sem Array.forEach.
 */

var CICLO_TICKS = 254016000000;
var CICLO_CLIP = 1, CICLO_BIN = 2, CICLO_ROOT = 3, CICLO_FILE = 4;

function cicloJ(v) {
  if (v === null || v === undefined) return "null";
  var t = typeof v;
  if (t === "number") return isFinite(v) ? String(v) : "null";
  if (t === "boolean") return v ? "true" : "false";
  if (t === "string") {
    var s = "";
    for (var i = 0; i < v.length; i++) {
      var c = v.charCodeAt(i);
      if (c === 34) s += '\\"';
      else if (c === 92) s += "\\\\";
      else if (c < 32 || c > 126) {
        var h = c.toString(16);
        while (h.length < 4) h = "0" + h;
        s += "\\u" + h;
      } else s += v.charAt(i);
    }
    return '"' + s + '"';
  }
  if (v instanceof Array) {
    var a = [];
    for (var k = 0; k < v.length; k++) a.push(cicloJ(v[k]));
    return "[" + a.join(",") + "]";
  }
  var p = [];
  for (var n in v) if (v.hasOwnProperty(n)) p.push(cicloJ(String(n)) + ":" + cicloJ(v[n]));
  return "{" + p.join(",") + "}";
}

function cicloTentar(f, padrao) {
  try { return f(); } catch (e) { return padrao; }
}

function cicloErro(e) { return cicloJ({ erro: String(e) }); }

function cicloTicks(t) {
  if (!t || typeof t === "string") return null;
  return cicloTentar(function () { return String(t.ticks); }, null);
}

/** O tipo que o Ciclo Assist entende — `type` sozinho mente (banco, arrastar-e-selecao §3). */
function cicloEspecie(it) {
  var tipo = cicloTentar(function () { return it.type; }, 0);
  if (tipo === CICLO_BIN || tipo === CICLO_ROOT) return "bin";
  if (cicloTentar(function () { return it.isMergedClip(); }, false)) return "merged";
  if (cicloTentar(function () { return it.isSequence(); }, false)) return "sequencia";
  if (cicloTentar(function () { return it.isAdjustmentLayer(); }, false)) return "ajuste";
  if (cicloTentar(function () { return it.isMulticamClip(); }, false)) return "multicam";
  var midia = cicloTentar(function () { return it.getMediaPath(); }, "");
  if (tipo === CICLO_CLIP && midia) return "clipe";
  if (tipo === CICLO_FILE) return "arquivo";
  return "outro";
}

/** O "Media Type" que o Premiere mostra na coluna (Movie = vídeo com som, Video = sem som, Audio, Still Image…), lido
 * do metadado do item — o Premiere CALCULA, não está no .prproj. "" quando não há. */
function cicloTipoDeMidia(it) {
  var meta = cicloTentar(function () { return String(it.getProjectMetadata()); }, "");
  var m = /Column\.Intrinsic\.MediaType>([^<]*)</.exec(meta);
  return m ? m[1] : "";
}

/** Bancada: o Media Type de cada item de uma bin (`caminho` "A/B"; "" = o projeto inteiro). */
function cicloTiposDeMidia(caminho) {
  try {
    var r = [];
    cicloAndar(app.project.rootItem, "", function (it, c) {
      if (caminho && c.indexOf(String(caminho)) !== 0) return;
      var e = cicloEspecie(it);
      if (e === "bin") return;
      r.push({ nome: String(it.name), bin: c, especie: e, tipo: cicloTipoDeMidia(it) });
    });
    return cicloJ({ itens: r });
  } catch (e) { return cicloErro(e); }
}

function cicloFilhos(pasta) {
  var out = [];
  var n = cicloTentar(function () { return pasta.children.numItems; }, 0);
  for (var i = 0; i < n; i++) out.push(pasta.children[i]);
  return out;
}

/** Caminho legível de uma bin: nomes separados por "/", a raiz vazia. */
function cicloAndar(pasta, caminho, visita) {
  var f = cicloFilhos(pasta);
  for (var i = 0; i < f.length; i++) {
    var it = f[i];
    var parar = visita(it, caminho);
    if (parar === true) return true;
    if (cicloEspecie(it) === "bin") {
      if (cicloAndar(it, caminho ? caminho + "/" + it.name : it.name, visita) === true) return true;
    }
  }
  return false;
}

function cicloProjeto() {
  try {
    var r = { versao: String(app.version) };
    r.caminho = cicloTentar(function () { return String(app.project.path); }, "");
    r.nome = cicloTentar(function () { return String(app.project.name); }, "");
    r.sequencia_ativa = cicloTentar(function () {
      var s = app.project.activeSequence;
      return s ? { nome: String(s.name), id: String(s.sequenceID) } : null;
    }, null);
    /* ⭐ A taxa em que o editor VÊ o material, na forma {num, den} que o
     * `midia/timecode.taxa_do_projeto` já lê do Avid — é o que dá o timecode completo da
     * fala na aba Busca.
     *
     * ⛔⛔ O Premiere não tem taxa de PROJETO: quem tem taxa é a SEQUÊNCIA. `timebase` é
     * o número de ticks por quadro, e um tick é 1/254.016.000.000 de segundo (a constante
     * do Premiere) — daí fps = 254016000000 / timebase. Sem sequência aberta não se
     * inventa taxa nenhuma: chutar 25 fps erraria todo material 23,976.
     *
     * ⚠️ Os dois vão como TEXTO: 254.016.000.000 não cabe num inteiro de 32 bits, e
     * arredondar aqui é errar a taxa por inteiro. */
    r.fps = cicloTentar(function () {
      var s = app.project.activeSequence;
      var tb = s ? String(s.timebase) : "";
      return tb && tb !== "0" ? { num: "254016000000", den: tb } : null;
    }, null);
    return cicloJ(r);
  } catch (e) { return cicloErro(e); }
}

function cicloBins() {
  try {
    var bins = [];
    cicloAndar(app.project.rootItem, "", function (it, caminho) {
      if (cicloEspecie(it) === "bin") {
        bins.push({ caminho: caminho ? caminho + "/" + it.name : it.name,
                    id: String(it.nodeId), itens: cicloFilhos(it).length });
      }
    });
    return cicloJ({ bins: bins });
  } catch (e) { return cicloErro(e); }
}

function cicloResumo(it, caminho, selecionados) {
  var r = { nome: String(it.name), id: String(it.nodeId), especie: cicloEspecie(it),
            bin: caminho };
  var midia = cicloTentar(function () { return String(it.getMediaPath()); }, "");
  if (midia) r.arquivo = midia;
  if (selecionados && selecionados[r.id]) r.selecionado = true;
  return r;
}

function cicloIdsSelecionados() {
  var ids = {};
  var sel = cicloTentar(function () { return app.getCurrentProjectViewSelection(); }, null);
  if (sel) for (var i = 0; i < sel.length; i++) ids[String(sel[i].nodeId)] = true;
  return ids;
}

/** Os itens de UMA bin ("" = a raiz). Pastas entram como itens da espécie "bin". */
function cicloItens(caminhoDaBin, soSelecionados) {
  try {
    var alvo = null, nomeAchado = "";
    if (!caminhoDaBin) alvo = app.project.rootItem;
    else cicloAndar(app.project.rootItem, "", function (it, caminho) {
      var este = caminho ? caminho + "/" + it.name : it.name;
      if (cicloEspecie(it) === "bin" && (este === caminhoDaBin || String(it.nodeId) === caminhoDaBin)) {
        alvo = it; nomeAchado = este; return true;
      }
    });
    if (!alvo) return cicloErro("não achei a bin " + caminhoDaBin);
    var sel = cicloIdsSelecionados();
    var nome = caminhoDaBin ? (nomeAchado || caminhoDaBin) : "";
    var itens = [];
    var f = cicloFilhos(alvo);
    for (var i = 0; i < f.length; i++) {
      var r = cicloResumo(f[i], nome, sel);
      if (!soSelecionados || r.selecionado) itens.push(r);
    }
    return cicloJ({ bin: nome, itens: itens });
  } catch (e) { return cicloErro(e); }
}

function cicloSelecao() {
  try {
    var sel = cicloTentar(function () { return app.getCurrentProjectViewSelection(); }, null);
    var ids = cicloIdsSelecionados();
    var itens = [];
    if (sel && sel.length) {
      cicloAndar(app.project.rootItem, "", function (it, caminho) {
        if (ids[String(it.nodeId)]) itens.push(cicloResumo(it, caminho, ids));
      });
    }
    return cicloJ({ itens: itens });
  } catch (e) { return cicloErro(e); }
}

function cicloAchar(ref, caminhoDaBin) {
  var achado = null, porCaminho = null, porNome = null;
  cicloAndar(app.project.rootItem, "", function (it, caminho) {
    if (String(it.nodeId) === ref) { achado = { item: it, bin: caminho }; return true; }
    // ⚠️ Pelo CAMINHO também ("D01_230403/B01"): é a forma que `cicloBins` mostra e que a
    //    conferência do `organizar` aceita. Sem isto, um plano com caminho de bin passava
    //    na conferência e falhava aqui com "não achei o item" — depois de o editor aprovar.
    var este = caminho ? caminho + "/" + it.name : it.name;
    if (!porCaminho && este === ref) { porCaminho = { item: it, bin: caminho }; }
    if (!porNome && it.name === ref && (!caminhoDaBin || caminho === caminhoDaBin)
        && cicloEspecie(it) !== "bin") {
      porNome = { item: it, bin: caminho };
    }
  });
  return achado || porCaminho || porNome;
}

/** Os pedaços de uma sequência (merged clip ou timeline) que apontam mídia. */
function cicloTrilhas(seq) {
  var out = [];
  function trilhas(lista, especie) {
    var n = cicloTentar(function () { return lista.numTracks; }, 0);
    for (var t = 0; t < n; t++) {
      var tr = lista[t];
      var m = cicloTentar(function () { return tr.clips.numItems; }, 0);
      for (var c = 0; c < m; c++) {
        var cl = tr.clips[c];
        var pi = cicloTentar(function () { return cl.projectItem; }, null);
        out.push({
          especie: especie, trilha: t,
          arquivo: pi ? cicloTentar(function () { return String(pi.getMediaPath()); }, "") : "",
          nome: pi ? String(pi.name) : "",
          id: pi ? String(pi.nodeId) : "",
          inicio_na_seq: cicloTicks(cicloTentar(function () { return cl.start; }, null)),
          fim_na_seq: cicloTicks(cicloTentar(function () { return cl.end; }, null)),
          entrada_na_midia: cicloTicks(cicloTentar(function () { return cl.inPoint; }, null)),
          saida_na_midia: cicloTicks(cicloTentar(function () { return cl.outPoint; }, null)),
          inicio_da_midia: pi ? cicloTicks(cicloTentar(function () { return pi.startTime(); }, null)) : null
        });
      }
    }
  }
  trilhas(seq.videoTracks, "imagem");
  trilhas(seq.audioTracks, "som");
  return out;
}

function cicloSequenciaDe(it) {
  var n = cicloTentar(function () { return app.project.sequences.numSequences; }, 0);
  for (var i = 0; i < n; i++) {
    var s = app.project.sequences[i];
    var pi = cicloTentar(function () { return s.projectItem; }, null);
    if (pi && String(pi.nodeId) === String(it.nodeId)) return s;
  }
  return null;
}

/** Um item por inteiro: o que o serviço precisa para montar o take. */
function cicloItem(ref, caminhoDaBin) {
  try {
    var a = cicloAchar(ref, caminhoDaBin || "");
    if (!a) return cicloErro("não achei o item " + ref);
    var it = a.item;
    var r = cicloResumo(it, a.bin, null);
    r.inicio_da_midia = cicloTicks(cicloTentar(function () { return it.startTime(); }, null));
    r.entrada = cicloTicks(cicloTentar(function () { return it.getInPoint(); }, null));
    r.saida = cicloTicks(cicloTentar(function () { return it.getOutPoint(); }, null));
    r.fps = cicloTentar(function () { return it.getFootageInterpretation().frameRate; }, null);
    r.proxy = cicloTentar(function () { return it.hasProxy() ? String(it.getProxyPath()) : ""; }, "");
    r.metadados = cicloTentar(function () { return String(it.getProjectMetadata()); }, "");
    if (r.especie === "merged" || r.especie === "sequencia") {
      var s = cicloSequenciaDe(it);
      if (s) {
        r.sequencia = { id: String(s.sequenceID),
                        fps_ticks: cicloTentar(function () { return String(s.timebase); }, null) };
        r.pedacos = cicloTrilhas(s);
      }
    }
    return cicloJ(r);
  } catch (e) { return cicloErro(e); }
}

/**
 * Todo arquivo de mídia que o projeto usa — o recorte das buscas e as linhas da aba
 * Vetores.
 *
 * `arquivos` continua sendo a lista crua (quem só quer o recorte lê isso); `itens` traz,
 * para cada arquivo, o nome do PRIMEIRO item que o aponta e as bins em que ele aparece —
 * a coluna "bin" da aba Vetores. ⚠️ Um arquivo pode estar em várias bins (o editor
 * duplica o clipe), e a linha é uma só: é a mídia que se processa, não o item.
 */
function cicloMidias() {
  try {
    var vistos = {}, lista = [], itens = [];
    cicloAndar(app.project.rootItem, "", function (it, caminho) {
      var m = cicloTentar(function () { return String(it.getMediaPath()); }, "");
      if (!m) return;
      var bin = caminho || "";
      if (!vistos[m]) {
        vistos[m] = { arquivo: m, nome: String(it.name), bins: [] };
        lista.push(m);
        itens.push(vistos[m]);
      }
      var ja = false;
      for (var k = 0; k < vistos[m].bins.length; k++) if (vistos[m].bins[k] === bin) ja = true;
      if (!ja) vistos[m].bins.push(bin);
    });
    return cicloJ({ arquivos: lista, itens: itens });
  } catch (e) { return cicloErro(e); }
}

/**
 * Quantas vezes o Premiere avisou que algo foi importado — a vigia da aba Vetores lê isto
 * a cada poucos segundos e só percorre o projeto quando o número ANDA.
 *
 * MEDIDO no 23.2 (`spikes/o_premiere_avisa_import.py`): `onItemsAddedToProjectSuccess`
 * dispara no import, AGRUPADO (um `importFiles` de 60 arquivos = 2 avisos). ⛔ E
 * `app.bind` devolve `true` para QUALQUER nome, inventado ou não: só disparar prova.
 *
 * ⚠️ O registro é feito uma vez por motor de ExtendScript (`$.global` sobrevive ao Reload
 * do painel? não medido — registrar de novo só soma um handler que conta igual).
 */
function cicloVigia() {
  try {
    if (!$.global.cicloVigiaLigada) {
      $.global.cicloImportados = 0;
      app.bind("onItemsAddedToProjectSuccess", function () { $.global.cicloImportados++; });
      $.global.cicloVigiaLigada = true;
    }
    return cicloJ($.global.cicloImportados);
  } catch (e) { return cicloErro(e); }
}

/**
 * Em que sequências cada item do projeto é usado: `{nodeId: [nome da sequência, …]}`.
 *
 * ⛔ Só o que REALMENTE toca: `track.clips` já é o que está montado. É o equivalente da
 * regra do `Selector` do Avid (só o ramo escolhido) — etiqueta de timeline que conta
 * alternativa não-tocada diz ao editor que o plano está na montagem quando não está.
 */
function cicloUsosEmSequencias() {
  var usos = {};
  var n = cicloTentar(function () { return app.project.sequences.numSequences; }, 0);
  for (var i = 0; i < n; i++) {
    var s = app.project.sequences[i];
    var nome = cicloTentar(function () { return String(s.name); }, "");
    if (!nome) continue;
    var pedacos = cicloTrilhas(s);
    for (var p = 0; p < pedacos.length; p++) {
      var id = pedacos[p].id;
      if (!id) continue;
      if (!usos[id]) usos[id] = [];
      var visto = false;
      for (var k = 0; k < usos[id].length; k++) if (usos[id][k] === nome) visto = true;
      if (!visto) usos[id].push(nome);
    }
  }
  return usos;
}

/**
 * Os RECORTES do projeto: subclipes, merged e multicam, com o que o serviço precisa para
 * montar a janela de cada um (`nle/premiere/recortes.py`).
 *
 * ⚠️ `getProjectMetadata()` é a parte cara e não tem como ser evitada: o recorte de um
 * subclipe mora em `Column.Intrinsic.SubclipStart`/`SubclipDuration` e `getInPoint()`
 * devolve o master inteiro (banco, `subclipe-e-merged-clip.md`). Por isso o resultado diz
 * quantos itens foram olhados — quem chama registra o custo em vez de adivinhar.
 */
function cicloRecortes() {
  try {
    var usos = cicloUsosEmSequencias();
    var itens = [], olhados = 0;
    cicloAndar(app.project.rootItem, "", function (it, caminho) {
      var especie = cicloEspecie(it);
      if (especie !== "clipe" && especie !== "merged" && especie !== "multicam") return;
      olhados++;
      var meta = cicloTentar(function () { return String(it.getProjectMetadata()); }, "");
      // ⛔ Um clipe COMUM não é recorte: sem `SubclipStart` ele é o master inteiro, e
      //    pô-lo na 1ª faixa da preferência afundaria os subclipes de verdade.
      if (especie === "clipe" && meta.indexOf("Column.Intrinsic.SubclipStart") < 0) return;
      var id = String(it.nodeId);
      itens.push({
        nome: String(it.name), id: id, bin: caminho, especie: especie,
        arquivo: cicloTentar(function () { return String(it.getMediaPath()); }, ""),
        metadados: meta,
        fps: cicloTentar(function () { return it.getFootageInterpretation().frameRate; }, null),
        entrada: cicloTicks(cicloTentar(function () { return it.getInPoint(); }, null)),
        saida: cicloTicks(cicloTentar(function () { return it.getOutPoint(); }, null)),
        timelines: usos[id] || []
      });
    });
    return cicloJ({ itens: itens, olhados: olhados });
  } catch (e) { return cicloErro(e); }
}

/**
 * Põe um item no monitor **Source** — o duplo clique de um resultado da aba Busca.
 *
 * ⛔ `openProjectItem`, e não `openFilePath`: o segundo IMPORTA o arquivo no projeto do
 * editor, o que é escrita — e isto é um gesto de leitura que não passa pelo portão.
 *
 * ⚠️ `ref` é id, caminho de bin ou nome (a mesma resolução do `cicloItem`); `arquivo` é a
 * saída alternativa, para quando o serviço só sabe o caminho da mídia. Nada é importado:
 * o que não estiver no projeto aberto volta como "não achei".
 */
/**
 * Põe o item no monitor Source e, com `tc`, a agulha nesse ponto.
 *
 * ⭐⭐ `tc` é TEMPO DESDE O INÍCIO DO CLIPE em `HH:MM:SS:FF`, NUNCA o TC do clipe (medido no
 * 23.2, `spikes/o_source_no_tc.py`): num clipe que começa em 01:00:00:00,
 * `scrubTo('01:00:04:00')` vai para 3604 s — e é aceito num clipe de 10 s, sem erro. Quem
 * monta o `tc` é o serviço, que também o limita à duração.
 * ⛔ `app.sourceMonitor` não posiciona (não há `setPosition`); quem posiciona é o QE.
 * ⭐ A posição é LIDA DE VOLTA (`getPosition`): a tela diz onde a agulha parou de fato.
 *
 * ⚠️ Pelo ARQUIVO, o item que conta é o MASTER: um subclipe aponta o mesmo arquivo, e
 * abri-lo no lugar do master poria no Source um recorte que o editor não clicou.
 */
function cicloCarregarNoSource(ref, arquivo, tc) {
  try {
    var alvo = ref ? cicloAchar(String(ref), "") : null;
    if (!alvo && arquivo) {
      var procurado = String(arquivo).toLowerCase().replace(/\\/g, "/");
      cicloAndar(app.project.rootItem, "", function (it, caminho) {
        if (cicloEspecie(it) === "bin") return;
        var m = cicloTentar(function () { return String(it.getMediaPath()); }, "");
        if (m && m.toLowerCase().replace(/\\/g, "/") === procurado) {
          var meta = cicloTentar(function () { return String(it.getProjectMetadata()); }, "");
          if (meta.indexOf("Column.Intrinsic.SubclipStart") >= 0) return;
          alvo = { item: it, bin: caminho }; return true;
        }
      });
    }
    if (!alvo) return cicloJ({ ok: false, erro: "não achei esse clipe no projeto aberto" });
    if (!app.sourceMonitor) {
      return cicloJ({ ok: false, erro: "esta versão do Premiere não expõe o monitor Source" });
    }
    app.sourceMonitor.openProjectItem(alvo.item);
    var r = { ok: true, nome: String(alvo.item.name), bin: alvo.bin };
    if (tc) {
      try {
        app.enableQE();
        r.posicionado = qe.source.player.scrubTo(String(tc)) ? true : false;
        r.posicao_s = Number(app.sourceMonitor.getPosition().seconds);
      } catch (e2) {
        r.posicionado = false;
        r.erro_posicao = String(e2);
      }
    }
    return cicloJ(r);
  } catch (e) { return cicloErro(e); }
}

/**
 * A decupagem na coluna "Descrição" do painel de projeto — sem nunca apagar o texto do
 * editor. `plano` = `[{arquivo, esperado, novo}]` (literal JSON montado pelo serviço).
 *
 * MEDIDO no 23.2 (`spikes/o_source_e_a_descricao.py`): a coluna é
 * `Column.PropertyText.Description` do metadado PRIVADO do projeto, com o mesmo nome
 * interno em qualquer idioma da interface; `setProjectMetadata` recebe DOIS argumentos.
 *
 * ⛔⛔ Compare-and-set: grava só se o campo está VAZIO ou ainda é exatamente o `esperado`
 * (o que o Ciclo Assist gravou da última vez). Texto do editor é resposta `do_editor`.
 * ⚠️ Só no MASTER: um subclipe aponta o mesmo arquivo, e é do editor.
 */
function cicloDescrever(plano) {
  try {
    if (ExternalObject.AdobeXMPScript === undefined) {
      ExternalObject.AdobeXMPScript = new ExternalObject("lib:AdobeXMPScript");
    }
    var NS = "http://ns.adobe.com/premierePrivateProjectMetaData/1.0/";
    var CAMPO = "Column.PropertyText.Description";
    var porArquivo = {};
    for (var i = 0; i < plano.length; i++) {
      porArquivo[String(plano[i].arquivo).toLowerCase().replace(/\\/g, "/")] = plano[i];
    }
    var r = { escritos: [], do_editor: [], iguais: 0 };
    cicloAndar(app.project.rootItem, "", function (it) {
      if (cicloEspecie(it) !== "clipe") return;
      var m = cicloTentar(function () { return String(it.getMediaPath()); }, "");
      var p = m ? porArquivo[m.toLowerCase().replace(/\\/g, "/")] : null;
      if (!p) return;
      var meta = String(it.getProjectMetadata());
      if (meta.indexOf("Column.Intrinsic.SubclipStart") >= 0) return;
      var x = new XMPMeta(meta);
      var atual = x.doesPropertyExist(NS, CAMPO) ? String(x.getProperty(NS, CAMPO)) : "";
      if (atual === p.novo) { r.iguais++; return; }
      if (atual !== "" && atual !== p.esperado) { r.do_editor.push(p.arquivo); return; }
      x.setProperty(NS, CAMPO, p.novo);
      it.setProjectMetadata(x.serialize(), [CAMPO]);
      r.escritos.push(p.arquivo);
    });
    return cicloJ(r);
  } catch (e) { return cicloErro(e); }
}

"ciclo host carregado";

/* ── escrita: organizar o projeto (bins, mover, renomear) ──────────────────
 *
 * Só o que o editor aprovou no portão chega aqui: o serviço monta o plano, o cartão mostra
 * cada linha, e o clique executa (ADR 0008).
 */

function cicloArvore() {
  try {
    var itens = [];
    cicloAndar(app.project.rootItem, "", function (it, caminho) {
      // ⛔ Com o `arquivo` (como a via do MCP): sem ele o sincronizar juntava ZERO arquivos
      //   nas versões sem o MCP nativo ("o Sincronizar não reconheceu nenhuma fonte", 25.6.5, 2026-11-07).
      itens.push(cicloResumo(it, caminho, null));
    });
    return cicloJ({ itens: itens });
  } catch (e) { return cicloErro(e); }
}

/** A bin de destino: "" é a raiz; senão um id ou um caminho de nomes. */
function cicloBinAlvo(ref) {
  if (!ref) return app.project.rootItem;
  var achado = null;
  cicloAndar(app.project.rootItem, "", function (it, caminho) {
    var este = caminho ? caminho + "/" + it.name : it.name;
    if (cicloEspecie(it) === "bin" && (String(it.nodeId) === ref || este === ref)) {
      achado = it; return true;
    }
  });
  return achado;
}

/**
 * `plano` é JSON: [{acao:"criar_bin", nome, dentro_de}, {acao:"mover", item, para},
 * {acao:"renomear", item, nome}]. Devolve o que aconteceu, operação a operação.
 *
 * ⚠️ ES3 sem JSON.parse: o serviço manda o plano já como ARGUMENTOS de chamada, não texto.
 * Aqui cada operação chega como três strings, e a lista vem separada por "\n" / "\t" —
 * formato burro de propósito: nome de bin com vírgula ou aspas não quebra nada.
 */
function cicloOrganizar(plano) {
  try {
    var linhas = String(plano).split("\n");
    var feitos = [];
    for (var i = 0; i < linhas.length; i++) {
      if (!linhas[i]) continue;
      var p = linhas[i].split("\t");
      var acao = p[0], a = p[1] || "", b = p[2] || "";
      var r = { acao: acao };
      if (acao === "criar_bin") {
        var mae = cicloBinAlvo(b);
        if (!mae) { r.erro = "não achei a bin " + b; }
        else {
          var nova = mae.createBin(a);
          r.nome = a; r.dentro_de = b || "(raiz)";
          r.id = nova ? String(nova.nodeId) : "";
        }
      } else if (acao === "mover") {
        var item = cicloAchar(a, "");
        var destino = cicloBinAlvo(b);
        if (!item) { r.erro = "não achei o item " + a; }
        else if (!destino) { r.erro = "não achei a bin " + b; }
        else {
          r.nome = String(item.item.name);
          r.de = item.bin || "(raiz)";
          r.para = b || "(raiz)";
          item.item.moveBin(destino);
        }
      } else if (acao === "renomear") {
        var alvo = cicloAchar(a, "");
        if (!alvo) { r.erro = "não achei o item " + a; }
        else {
          r.de = String(alvo.item.name);
          r.para = b;
          // ⚠️ Bin renomeia por `renameBin`; clipe, por `name`. Trocar um pelo outro
          //    falha em silêncio (o nome fica o mesmo e nada acusa).
          if (cicloEspecie(alvo.item) === "bin") alvo.item.renameBin(b);
          else alvo.item.name = b;
          r.ficou = String(alvo.item.name);
        }
      } else if (acao === "apagar_bin_vazia") {
        var apagada = cicloApagarBinVazia(a);
        for (var k in apagada) if (apagada.hasOwnProperty(k)) r[k] = apagada[k];
      } else {
        r.erro = "ação desconhecida: " + acao;
      }
      feitos.push(r);
    }
    return cicloJ({ feitos: feitos });
  } catch (e) { return cicloErro(e); }
}

/** Apaga uma bin VAZIA. ⛔ Só vazia: quem apaga mídia é o editor, no Premiere. */
function cicloApagarBinVazia(ref) {
  var alvo = cicloBinAlvo(ref);
  if (!alvo) return { erro: "não achei a bin " + ref };
  var quantos = cicloTentar(function () { return alvo.children.numItems; }, -1);
  if (quantos !== 0) return { erro: "a bin " + ref + " não está vazia (" + quantos + ")" };
  var r = { nome: String(alvo.name) };
  try { alvo.deleteBin(); } catch (e) { r.erro = String(e); }
  return r;
}

/* ── abrir, salvar e sair: o Premiere como um dos programas do fluxo (2026-11-01) ──────────
 * Quem chama é `cicloassist/premiere_app.py`. O CAMINHO vem com `\` no Windows (matriz §G2:
 * há chamada do ExtendScript que recusa `/` calada). `app.project.path` SEM projeto lança
 * (banco), daí o cicloTentar. */

function cicloCaminhoAberto() {
  return cicloTentar(function () { return String(app.project.path); }, "");
}

function cicloMesmo(a, b) {
  var n = function (s) { return String(s).replace(/\//g, "\\").toLowerCase(); };
  return a !== "" && n(a) === n(b);
}

/** Abre o .prproj, ou o CRIA se não existir. `como`: ja_aberto · aberto · criado. */
function cicloAbrirProjeto(caminho) {
  try {
    var r = {};
    if (cicloMesmo(cicloCaminhoAberto(), caminho)) {
      r.como = "ja_aberto";
    } else if (new File(caminho).exists) {
      r.ok = app.openDocument(caminho, true, true, true);
      r.como = "aberto";
    } else {
      r.ok = app.newProject(caminho);
      r.como = "criado";
    }
    r.caminho = cicloCaminhoAberto();
    return cicloJ(r);
  } catch (e) { return cicloErro(e); }
}

/** Salva o projeto aberto (ou o `caminho`, aberto, à frente ou não). Sem projeto, `salvo: false` e nenhum erro. */
function cicloSalvar(caminho) {
  try {
    var P = caminho ? cicloProjetoAberto(caminho) : app.project;
    if (!P || !String(P.path)) return cicloJ({ salvo: false, caminho: "" });
    P.save();
    return cicloJ({ salvo: true, caminho: String(P.path) });
  } catch (e) { return cicloErro(e); }
}

/** Pede para o Premiere sair. ⚠️ Pode não sair, e a ponte morre junto (banco, 2026-10-10):
 * quem chama confere o PROCESSO, nunca esta resposta. */
function cicloSair() {
  try { app.quit(); return cicloJ({ pedido: true }); } catch (e) { return cicloErro(e); }
}

/* ── montar uma sequência (versões SEM o MCP nativo: 2025/2026 — F6, 2026-11-06) ─────────────────
 * MEDIDO no 25.6.5 e no 26.0.2 (banco `plugins/premiere-cep/api-extendscript.md`): `setInPoint/OutPoint`
 * + `overwriteClip` com o tempo `n/fps + 1 µs` cai no quadro (12/12, na imagem) e leva o som multicanal
 * INTEIRO (5/5 canais) — o que o `insertClipsToSequence` do MCP não faz.
 *
 * `plano` é TEXTO tabulado, uma linha por coisa (⛔ nunca código):
 *   seq<TAB>nome<TAB>bin            (a bin por caminho "A/B"; criada se faltar)
 *   p<TAB>ref<TAB>in_s<TAB>out_s<TAB>pos_s<TAB>imagem(1/0)
 * ⛔ As MARCAS de entrada/saída do clipe do editor são mudadas para inserir — e DEVOLVIDAS no fim.
 */
function cicloGarantirBin(caminho) {
  if (!caminho) return app.project.rootItem;
  var achada = cicloBinAlvo(caminho);
  if (achada) return achada;
  var partes = String(caminho).split("/"), mae = app.project.rootItem, feito = "";
  for (var i = 0; i < partes.length; i++) {
    feito = feito ? feito + "/" + partes[i] : partes[i];
    var b = cicloBinAlvo(feito);
    if (!b) { mae.createBin(partes[i]); b = cicloBinAlvo(feito); }
    if (!b) return null;
    mae = b;
  }
  return mae;
}

/** A bin `caminho` ("A/B") no projeto `P` (aberto, à frente ou não), criada se faltar. ⭐ Pelo objeto do projeto, não
 * pelo `app.project` (o `cicloGarantirBin` acima é do ATIVO). */
function cicloGarantirBinEm(P, caminho) {
  var mae = P.rootItem;
  if (!caminho) return mae;
  var partes = String(caminho).split("/");
  for (var i = 0; i < partes.length; i++) {
    var achou = null, f = cicloFilhos(mae);
    for (var k = 0; k < f.length; k++)
      if (cicloEspecie(f[k]) === "bin" && String(f[k].name) === partes[i]) { achou = f[k]; break; }
    if (!achou) { mae.createBin(partes[i]); f = cicloFilhos(mae);
      for (k = 0; k < f.length; k++)
        if (cicloEspecie(f[k]) === "bin" && String(f[k].name) === partes[i]) { achou = f[k]; break; } }
    if (!achou) return null;
    mae = achou;
  }
  return mae;
}

function cicloESubclipe(it) {
  return cicloTentar(function () { return String(it.getProjectMetadata()); }, "").indexOf("Column.Intrinsic.SubclipStart") >= 0;
}

/** A pasta de cada mídia pelo "Media Type" do Premiere (autor, 2026-11-15): Movie (vídeo com som) e Video (sem som) →
 * "Video"; Audio → "Audio"; Still Image → "Fotos"; o resto, "" (fica onde está). */
function cicloPastaDoTipo(tipo) {
  return { "Movie": "Video", "Video": "Video", "Audio": "Audio", "Still Image": "Fotos" }[String(tipo)] || "";
}

/** Reparte o que está SOLTO em `binMidias` (o que a importação acabou de pôr ali) nas subpastas Video/Audio/Fotos —
 * cada uma criada só se houver o que pôr nela. `projeto`: o caminho do projeto do editor ("" = o ativo). */
function cicloArrumarMidias(projeto, binMidias) {
  try {
    var P = projeto ? cicloProjetoAberto(projeto) : app.project;
    if (!P) return cicloErro("o projeto " + projeto + " não está aberto no Premiere");
    var raiz = cicloGarantirBinEm(P, binMidias), r = { Video: 0, Audio: 0, Fotos: 0, ficaram: 0 };
    if (!raiz) return cicloErro("não consegui criar a bin " + binMidias);
    var f = cicloFilhos(raiz);
    for (var i = 0; i < f.length; i++) {
      var e = cicloEspecie(f[i]);
      if (e === "bin") continue;
      var pasta = e === "clipe" && !cicloESubclipe(f[i]) ? cicloPastaDoTipo(cicloTipoDeMidia(f[i])) : "";
      if (!pasta) { r.ficaram++; continue; }
      var alvo = cicloGarantirBinEm(P, binMidias + "/" + pasta);
      if (alvo) { f[i].moveBin(alvo); r[pasta]++; } else r.ficaram++;
    }
    return cicloJ(r);
  } catch (e) { return cicloErro(e); }
}

function cicloMarcas(it) {
  var m = {};
  m.iv = cicloTentar(function () { return it.getInPoint(1).seconds; }, null);
  m.ov = cicloTentar(function () { return it.getOutPoint(1).seconds; }, null);
  m.ia = cicloTentar(function () { return it.getInPoint(2).seconds; }, null);
  m.oa = cicloTentar(function () { return it.getOutPoint(2).seconds; }, null);
  return m;
}

function cicloDevolverMarcas(it, m) {
  cicloTentar(function () { if (m.iv !== null) it.setInPoint(m.iv, 1); return 1; }, 0);
  cicloTentar(function () { if (m.ov !== null) it.setOutPoint(m.ov, 1); return 1; }, 0);
  cicloTentar(function () { if (m.ia !== null) it.setInPoint(m.ia, 2); return 1; }, 0);
  cicloTentar(function () { if (m.oa !== null) it.setOutPoint(m.oa, 2); return 1; }, 0);
}

function cicloPedacosDa(seq) {
  var itens = [];
  var grupos = [["v", seq.videoTracks], ["a", seq.audioTracks]];
  for (var g = 0; g < grupos.length; g++) {
    var trs = grupos[g][1];
    for (var t = 0; t < trs.numTracks; t++) {
      var tr = trs[t];
      for (var c = 0; c < tr.clips.numItems; c++) {
        var k = tr.clips[c];
        itens.push({ tipo: grupos[g][0], trilha: t, nome: String(k.name),
                     ini: String(k.start.ticks), inp: String(k.inPoint.ticks), dur: String(k.duration.ticks) });
      }
    }
  }
  return itens;
}

/* ===== A timeline do editor nas versões SEM o MCP nativo (2025/2026) — F7 do plano 2026-11-06 =====
 * Medido no 26.0.2 (2026-11-07): `sequence.clone()` devolve true e põe "Cópia de <nome>" na RAIZ (e a
 * deixa ativa); `activeSequence =` é recusado (é `openSequence`); a navalha do QE trilha a trilha corta
 * no quadro; `remove(false,false)` e `move(Time)` (RELATIVO, devolve null) agem só no item — o vinculado
 * fica, como o `linked:false` do MCP; `overwriteClip` na trilha de índice k põe a imagem em V(k) E o
 * som a partir de A(k), criando as trilhas de som que faltarem.
 */
function cicloAcharSequencia(ref) {
  var n = app.project.sequences.numSequences, porId = null, porNome = [];
  for (var i = 0; i < n; i++) {
    var s = app.project.sequences[i];
    if (String(s.sequenceID) === ref || String(s.projectItem.nodeId) === ref) porId = s;
    else if (String(s.name) === ref) porNome.push(s);
  }
  if (porId) return { seq: porId };
  if (porNome.length > 1) return { erro: "há " + porNome.length + " sequências chamadas " + ref + "; use o id (o_que_esta_na_tela)" };
  if (porNome.length === 1) return { seq: porNome[0] };
  return { erro: "não achei a sequência " + ref + " no projeto do Premiere" };
}

function cicloNivelDoVolume(k) {
  for (var j = 0; j < k.components.numItems; j++) {
    var co = k.components[j], nomes = String(co.displayName) + "|" + String(co.matchName);
    if (!/volume/i.test(nomes) || /channel|canal/i.test(nomes)) continue;
    for (var q = 0; q < co.properties.numItems; q++)
      if (/level|n[ií]vel/i.test(String(co.properties[q].displayName))) return co.properties[q].getValue();
  }
  return null;
}

function cicloItensDa(seq, detalhe) {
  var itens = [];
  var grupos = [["video", seq.videoTracks], ["audio", seq.audioTracks]];
  for (var g = 0; g < grupos.length; g++) {
    var trs = grupos[g][1];
    for (var t = 0; t < trs.numTracks; t++) {
      var tr = trs[t];
      for (var c = 0; c < tr.clips.numItems; c++) {
        var k = tr.clips[c];
        itens.push({ tipo: grupos[g][0], trilha: t, clipe: String(k.name), node: String(k.nodeId),
                     ini: String(k.start.ticks), inp: String(k.inPoint.ticks), dur: String(k.duration.ticks) });
        // `detalhe`: o arquivo (o canal do OP-Atom) e o Nível CRU do volume — a conferência da Carta (2026-11-14)
        if (detalhe) {
          var it = itens[itens.length - 1];
          it.midia = cicloTentar(function () { return String(k.projectItem.getMediaPath()); }, "");
          it.desligado = cicloTentar(function () { return !!k.disabled; }, null);
          if (g === 1) it.nivel = cicloTentar(function () { return cicloNivelDoVolume(k); }, null);
        }
      }
    }
  }
  return itens;
}

/** Abre a sequência `ref` (id, nodeId ou nome único) na Timeline do projeto ativo — bancada: ver a timeline que a
 * importação trouxe (o `importSequences` não a abre). */
function cicloAbrirSequencia(ref) {
  try {
    var a = cicloAcharSequencia(String(ref));
    if (a.erro) return cicloErro(a.erro);
    var ok = app.project.openSequence(String(a.seq.sequenceID));
    return cicloJ({ ok: ok ? true : false, sequencia: String(a.seq.name), id: String(a.seq.sequenceID) });
  } catch (e) { return cicloErro(e); }
}

function cicloLerSequencia(ref, detalhe) {
  try {
    var a = cicloAcharSequencia(String(ref));
    if (a.erro) return cicloErro(a.erro);
    var s = a.seq;
    var st = s.getSettings();
    return cicloJ({ sequencia: String(s.name), id: String(s.sequenceID),
                    quadro: String(st.videoFrameRate.ticks), fim: String(s.end), itens: cicloItensDa(s, detalhe === "1") });
  } catch (e) { return cicloErro(e); }
}

function cicloTemClipe(ref) {
  try {
    var achado = cicloAchar(String(ref), "");
    if (!achado || cicloEspecie(achado.item) === "bin") return cicloJ({ ok: false });
    return cicloJ({ ok: true, nome: String(achado.item.name) });
  } catch (e) { return cicloErro(e); }
}

function cicloApagarSequencia(id, reabrir) {
  try {
    var a = cicloAcharSequencia(String(id));
    if (a.erro) return cicloJ({ ok: false, motivo: a.erro });
    var ok = app.project.deleteSequence(a.seq);
    if (reabrir) cicloTentar(function () { app.project.openSequence(String(reabrir)); return 1; }, 0);
    return cicloJ({ ok: !!ok });
  } catch (e) { return cicloErro(e); }
}

/**
 * `plano` é TEXTO tabulado (⛔ nunca código), as operações JÁ da última posição para a primeira:
 *   seq<TAB>ref<TAB>nome da cópia
 *   x<TAB>de<TAB>ate                                     (extrair)
 *   e<TAB>em<TAB>dur                                     (abrir espaço)
 *   i<TAB>em<TAB>dur<TAB>clipe<TAB>in<TAB>out<TAB>v<TAB>a<TAB>na   (inserir; v/a = índice ou -1)
 * Todos os tempos em TICKS inteiros (o serviço faz a conta exata).
 * ⛔⛔ Medido no 26.0.2 (2026-11-07): `move` com `Time.seconds` deixava o item 1 TICK depois do quadro
 * (10,0000000001), e o Premiere mostrava o quadro ANTERIOR à entrada em todo pedaço movido — a leitura
 * arredondada não via, a imagem sim. Com o `Time` montado por `.ticks`, sem float, fica exato.
 * Devolve a cópia e os itens dela; a PROVA é do serviço (e ele apaga a cópia se não passar).
 */
function cicloEditar(plano) {
  var marcas = null, clipe = null, copia = null, anterior = null;
  var EPS = 0.0005, TK = 254016000000;
  function T(ticks) { var t = new Time(); t.ticks = String(ticks); return t; }
  function S(ticks) { return Number(ticks) / TK; }
  function itens() {
    var o = [], g = [["video", copia.videoTracks], ["audio", copia.audioTracks]];
    for (var j = 0; j < 2; j++) for (var t = 0; t < g[j][1].numTracks; t++) {
      var tr = g[j][1][t];
      for (var c = 0; c < tr.clips.numItems; c++) o.push({ tipo: g[j][0], trilha: t, k: tr.clips[c], node: String(tr.clips[c].nodeId) });
    }
    return o;
  }
  function nodes() { var m = {}, l = itens(); for (var i = 0; i < l.length; i++) m[l[i].node] = 1; return m; }
  function navalha(ticks) {
    if (S(ticks) <= EPS) return;
    var tm = T(ticks);
    var st = copia.getSettings();
    var tc = tm.getFormatted(st.videoFrameRate, st.videoDisplayFormat);
    var q = qe.project.getActiveSequence();
    for (var i = 0; i < q.numVideoTracks; i++) q.getVideoTrackAt(i).razor(tc);
    for (var i = 0; i < q.numAudioTracks; i++) q.getAudioTrackAt(i).razor(tc);
  }
  function empurrar(a, d) {
    var l = itens(), alvo = [];
    for (var i = 0; i < l.length; i++) if (l[i].k.start.seconds >= S(a) - EPS) alvo.push(l[i]);
    alvo.sort(function (x, y) { return d > 0 ? y.k.start.seconds - x.k.start.seconds : x.k.start.seconds - y.k.start.seconds; });
    for (var i = 0; i < alvo.length; i++) alvo[i].k.move(T(d));
  }
  function tirarNovos(antes, manter) {
    var l = itens();
    for (var i = l.length - 1; i >= 0; i--) if (!antes[l[i].node] && !manter(l[i])) l[i].k.remove(false, false);
  }
  try {
    var linhas = String(plano).split("\n"), ops = [], ref = "", nome = "";
    for (var i = 0; i < linhas.length; i++) {
      var p = linhas[i].split("\t");
      if (p[0] === "seq") { ref = p[1]; nome = p[2]; }
      else if (p[0] === "x" || p[0] === "e") ops.push({ t: p[0], a: Number(p[1]), b: Number(p[2]) });
      else if (p[0] === "i") ops.push({ t: "i", a: Number(p[1]), b: Number(p[2]), clipe: p[3], ini: Number(p[4]),
                                        fim: Number(p[5]), v: parseInt(p[6], 10), au: parseInt(p[7], 10), na: parseInt(p[8], 10) });
    }
    var achada = cicloAcharSequencia(ref);
    if (achada.erro) return cicloErro(achada.erro);
    var orig = achada.seq;
    anterior = cicloTentar(function () { return String(app.project.activeSequence.sequenceID); }, null);
    var ids = {};
    for (var i = 0; i < app.project.sequences.numSequences; i++) ids[String(app.project.sequences[i].sequenceID)] = 1;
    if (!orig.clone()) return cicloErro("o Premiere não clonou a sequência " + ref);
    for (var i = 0; i < app.project.sequences.numSequences; i++)
      if (!ids[String(app.project.sequences[i].sequenceID)]) copia = app.project.sequences[i];
    if (!copia) return cicloErro("o Premiere disse que clonou, mas a cópia não apareceu");
    copia.name = nome;
    var caminho = String(orig.projectItem.treePath).split("\\");
    var bin = cicloBinAlvo(caminho.slice(2, caminho.length - 1).join("/"));
    if (bin && caminho.length > 3) copia.projectItem.moveBin(bin);
    app.project.openSequence(String(copia.sequenceID));
    app.enableQE();
    for (var o = 0; o < ops.length; o++) {
      var op = ops[o];
      if (op.t === "x") {
        navalha(op.a); navalha(op.b);
        var l = itens();
        for (var i = l.length - 1; i >= 0; i--) {
          var k = l[i].k;
          if (k.start.seconds >= S(op.a) - EPS && k.end.seconds <= S(op.b) + EPS) k.remove(false, false);
        }
        empurrar(op.b, -(op.b - op.a));
        continue;
      }
      navalha(op.a);
      empurrar(op.a, op.b);
      if (op.t !== "i") continue;
      var ach = cicloAchar(op.clipe, "");
      if (!ach) throw new Error("não achei o clipe " + op.clipe);
      clipe = ach.item; marcas = cicloMarcas(clipe);
      clipe.setInPoint(S(op.ini) + 0.000001, 4); clipe.setOutPoint(S(op.fim) + 0.000001, 4);
      var junto = op.v >= 0 && op.au === op.v;
      if (op.v >= 0) {
        if (op.v >= copia.videoTracks.numTracks) throw new Error("a sequência não tem a trilha V" + (op.v + 1));
        var antes = nodes();
        copia.videoTracks[op.v].overwriteClip(clipe, S(op.a) + 0.000001);
        var veio = false, l = itens();
        for (var i = 0; i < l.length; i++) if (!antes[l[i].node] && l[i].tipo === "video") veio = true;
        tirarNovos(antes, function (x) {
          return x.tipo === "video" || (junto && x.trilha >= op.au && x.trilha < op.au + op.na);
        });
        if (!veio) throw new Error("o clipe " + op.clipe + " não tem imagem: diga só som_em");
      }
      if (op.au >= 0 && !junto) {
        if (op.au >= copia.audioTracks.numTracks) throw new Error("a sequência não tem a trilha A" + (op.au + 1));
        var antes = nodes();
        copia.audioTracks[op.au].overwriteClip(clipe, S(op.a) + 0.000001);
        tirarNovos(antes, function (x) { return x.tipo === "audio" && x.trilha >= op.au && x.trilha < op.au + op.na; });
      }
      cicloAcertarEntrada(copia, S(op.a), op.ini, op.fim, true);
      cicloDevolverMarcas(clipe, marcas); marcas = null;
    }
    return cicloJ({ copia: String(copia.name), id: String(copia.sequenceID), anterior: anterior,
                    quadro: String(copia.getSettings().videoFrameRate.ticks), itens: cicloItensDa(copia) });
  } catch (e) {
    if (marcas && clipe) cicloDevolverMarcas(clipe, marcas);
    if (copia) {
      cicloTentar(function () { app.project.deleteSequence(copia); return 1; }, 0);
      if (anterior) cicloTentar(function () { app.project.openSequence(anterior); return 1; }, 0);
    }
    return cicloErro(e);
  }
}

/** O que está na tela: a sequência ativa (Program) e o Source, com a agulha de cada um. */
function cicloTela() {
  try {
    var o = { program: null, source: null };
    var s = cicloTentar(function () { return app.project.activeSequence; }, null);
    if (s) {
      var st = s.getSettings();
      o.program = { nome: String(s.name), id: String(s.sequenceID), quadro: String(st.videoFrameRate.ticks),
                    agulha: String(s.getPlayerPosition().ticks),
                    entrada: cicloTentar(function () { return String(s.getInPointAsTime().ticks); }, null),
                    saida: cicloTentar(function () { return String(s.getOutPointAsTime().ticks); }, null),
                    selecionados: cicloTentar(function () { return s.getSelection().length; }, 0) };
    }
    var pi = cicloTentar(function () { return app.sourceMonitor.getProjectItem(); }, null);
    if (pi) {
      o.source = { nome: String(pi.name), id: String(pi.nodeId),
                   agulha: cicloTentar(function () { return String(app.sourceMonitor.getPosition().ticks); }, null) };
    }
    return cicloJ(o);
  } catch (e) { return cicloErro(e); }
}

/**
 * ⛔⛔ O `setInPoint` do CLIPE arredonda para a grade de quadros DELE, não a da sequência (medido no
 * 26.0.2, 2026-11-07): um WAV de gravador com TC próprio (13:04:19,012) pedido em 10 s entrou em 9,968 s,
 * e na sequência de 25 fps o trecho ficou UM QUADRO antes (3 de 4 trechos). O conserto é o "slip" no
 * ITEM da timeline, que aceita o tempo exato e mantém posição e duração: `inPoint`/`outPoint` atribuídos.
 * Vale para todas as trilhas que começam em `pos` (a imagem e os canais de som do mesmo pedaço).
 */
function cicloAcertarEntrada(seq, pos, ini, fim, emTicks) {
  // `emTicks`: ini/fim já são ticks inteiros (cicloEditar); senão segundos (cicloMontar, com +1 µs).
  var grupos = [seq.videoTracks, seq.audioTracks];
  for (var g = 0; g < 2; g++) for (var t = 0; t < grupos[g].numTracks; t++) {
    var tr = grupos[g][t];
    for (var c = 0; c < tr.clips.numItems; c++) {
      var k = tr.clips[c];
      if (Math.abs(k.start.seconds - pos) > 0.005) continue;
      if (!emTicks && Math.abs(k.inPoint.seconds - ini) < 0.0005 && Math.abs(k.outPoint.seconds - fim) < 0.0005) continue;
      var ti = new Time(), to = new Time();
      if (emTicks) { ti.ticks = String(ini); to.ticks = String(fim); }
      else { ti.seconds = ini; to.seconds = fim; }
      if (String(k.inPoint.ticks) === String(ti.ticks) && String(k.outPoint.ticks) === String(to.ticks)) continue;
      k.inPoint = ti;
      k.outPoint = to;
    }
  }
}

function cicloMontar(plano) {
  // ⛔ Da ÚLTIMA guardada para a primeira, e uma vez por item (pelo nodeId: o ExtendScript dá um
  //   objeto NOVO a cada acesso, e `===` não reconhece o mesmo item — medido no 26.0.2: as marcas
  //   voltavam como as do 1º pedaço).
  var marcas = [], devolver = function () {
    for (var i = marcas.length - 1; i >= 0; i--) cicloDevolverMarcas(marcas[i].it, marcas[i].m);
  };
  try {
    var linhas = String(plano).split("\n"), nome = "", binRef = "", pedacos = [], ajustes = [], trs = [], outros = [], subs = [], esticar = [], cores = [];
    for (var i = 0; i < linhas.length; i++) {
      var p = linhas[i].split("\t");
      if (p[0] === "seq") { nome = p[1]; binRef = p[2] || ""; }
      else if (p[0] === "p") {
        var achado = cicloAchar(p[1], "");
        if (!achado) return cicloErro("não achei o take " + p[1]);
        pedacos.push({ it: achado.item, ini: parseFloat(p[2]), fim: parseFloat(p[3]),
                       pos: parseFloat(p[4]), imagem: p[5] === "1", trilha: parseInt(p[6] || "0", 10) || 0,
                       nivel: (p[7] === undefined || p[7] === "") ? null : parseFloat(p[7]) });
      }
      // tr<TAB>imagem<TAB>trilha<TAB>segundos<TAB>quadros<TAB>alinhamento<TAB>ini|fim — o MOLDE da transição da
      // Carta (2026-11-14): pelo QE, na cabeça (ini) ou na cauda (fim) do clipe que começa/acaba em `segundos`.
      // vel<TAB>imagem<TAB>trilha<TAB>segundos<TAB>velocidade e ds<TAB>imagem<TAB>trilha<TAB>segundos — os MOLDES de
      // velocidade (QE `setSpeed`, sem ripple) e de clipe desligado (DOM `disabled`), 2026-11-14.
      else if (p[0] === "vel" || p[0] === "ds") outros.push({ t: p[0], imagem: p[1] === "1", trilha: parseInt(p[2], 10) || 0,
                                                              s: parseFloat(p[3]), v: parseFloat(p[4]) });
      // sub<TAB>item de origem<TAB>nome do subclipe<TAB>ticks de entrada<TAB>ticks de saída — o MOLDE do SUBCLIPE
      // (2026-11-14): criado ANTES dos pedaços, que podem citá-lo pelo nome. Limites fixos, como o subclipe do Avid.
      else if (p[0] === "sub") {
        var org = cicloAchar(p[1], "");
        if (!org) return cicloErro("não achei o item " + p[1]);
        var t1 = new Time(), t2 = new Time();
        t1.ticks = String(p[3]); t2.ticks = String(p[4]);
        var novo = org.item.createSubClip(p[2], t1, t2, 1, 1, 1);
        if (!novo) return cicloErro("o Premiere não criou o subclipe " + p[2]);
        subs.push(String(novo.name));
      }
      // esc<TAB>imagem<TAB>trilha<TAB>segundos<TAB>largura %<TAB>altura % — o MOLDE do STRETCH (2026-11-20): o Motion do
      // clipe que começa em `segundos` com a escala NÃO uniforme (Uniform Scale desligado, Scale = altura).
      else if (p[0] === "esc") esticar.push({ imagem: p[1] === "1", trilha: parseInt(p[2], 10) || 0, s: parseFloat(p[3]),
                                             w: parseFloat(p[4]), h: parseFloat(p[5]) });
      // cor<TAB>imagem<TAB>trilha<TAB>segundos — o MOLDE da COR do Avid (2026-11-20): ProcAmp e depois Lumetri no clipe
      // que começa em `segundos`, pelas MESMAS chamadas da bancada medida (`lab/bancadas/premiere_cor_mc.py`).
      else if (p[0] === "cor") cores.push({ imagem: true, trilha: parseInt(p[2], 10) || 0, s: parseFloat(p[3]) });
      else if (p[0] === "tr") trs.push({ imagem: p[1] === "1", trilha: parseInt(p[2], 10) || 0, s: parseFloat(p[3]),
                                         q: parseInt(p[4], 10), al: parseFloat(p[5]), cabeca: p[6] !== "fim" });
    }
    if (!pedacos.length) return cicloErro("plano sem pedaços");
    var bin = cicloGarantirBin(binRef);
    if (!bin) return cicloErro("não consegui criar a bin " + binRef);
    var molde = pedacos[0].it;
    for (var i = 0; i < pedacos.length; i++) if (pedacos[i].imagem) { molde = pedacos[i].it; break; }
    var seq = app.project.createNewSequenceFromClips(nome, [molde], bin);
    if (!seq) return cicloErro("o Premiere não criou a sequência " + nome);
    var grupos = [seq.videoTracks, seq.audioTracks];
    for (var g = 0; g < 2; g++) for (var t = 0; t < grupos[g].numTracks; t++) {
      var tr = grupos[g][t];
      for (var c = tr.clips.numItems - 1; c >= 0; c--) tr.clips[c].remove(false, false);
    }
    for (var i = 0; i < pedacos.length; i++) {
      var pc = pedacos[i], ja = false;
      var idDoItem = String(pc.it.nodeId);
      for (var k = 0; k < marcas.length; k++) if (marcas[k].id === idDoItem) ja = true;
      if (!ja) marcas.push({ id: idDoItem, it: pc.it, m: cicloMarcas(pc.it) });
      pc.it.setInPoint(pc.ini, 4);
      pc.it.setOutPoint(pc.fim, 4);
      // 7º campo (opcional): a trilha, contada de 0 — o MOLDE de som da Carta (2026-11-14) põe cada canal na sua.
      var grupo = pc.imagem ? seq.videoTracks : seq.audioTracks;
      if (pc.trilha >= grupo.numTracks) return cicloErro("a sequência não tem a trilha " + (pc.trilha + 1));
      grupo[pc.trilha].overwriteClip(pc.it, pc.pos);
      // 8º campo (opcional, só som): o valor CRU do Level do Volume do clipe (o MOLDE do ganho, lido no .prproj).
      if (!pc.imagem && pc.nivel !== null) ajustes.push(cicloPorNivel(grupo[pc.trilha], pc.pos, pc.nivel));
      cicloAcertarEntrada(seq, pc.pos, pc.ini, pc.fim);
    }
    devolver();
    var transicoes = trs.length ? cicloTransicionar(seq, trs) : [];
    var mudancas = outros.length ? cicloVelEDesliga(seq, outros) : [];
    var esticados = esticar.length ? cicloEsticar(seq, esticar) : [];
    var corados = cores.length ? cicloCorDoAvid(seq, cores) : [];
    return cicloJ({ sequencia: String(seq.name), id: String(seq.sequenceID), itens: cicloPedacosDa(seq),
                    ajustes: ajustes, transicoes: transicoes, mudancas: mudancas, esticados: esticados,
                    cores: corados });
  } catch (e) { devolver(); return cicloErro(e); }
}

// ⚠️ O nome da transição sai no IDIOMA do app (banco, api-extendscript.md) e o QE devolve objeto até para nome que
// não existe (com `name` vazio): tenta os nomes conhecidos e diz a lista quando nenhum serve.
function cicloTransicaoQE(imagem) {
  var nomes = imagem ? ["Cross Dissolve", "Dissolução cruzada", "Dissolução Cruzada", "Dissolver cruzado"]
                     : ["Constant Power", "Potência constante", "Potência Constante", "Energia constante"];
  for (var i = 0; i < nomes.length; i++) {
    var t = imagem ? qe.project.getVideoTransitionByName(nomes[i]) : qe.project.getAudioTransitionByName(nomes[i]);
    if (t && String(t.name)) return t;
  }
  return null;
}

function cicloTransicionar(seq, trs) {
  var out = [];
  try {
    app.enableQE();
    app.project.openSequence(seq.sequenceID);
    var q = qe.project.getActiveSequence();
    var tpf = Number(seq.timebase);
    for (var i = 0; i < trs.length; i++) {
      var t = trs[i], r = { pedido: t };
      var tr = cicloTransicaoQE(t.imagem);
      if (!tr) {
        var l = t.imagem ? qe.project.getVideoTransitionList() : qe.project.getAudioTransitionList();
        r.erro = "transição não achada"; r.lista = String(l).substring(0, 3000); out.push(r); continue;
      }
      var qt = t.imagem ? q.getVideoTrackAt(t.trilha) : q.getAudioTrackAt(t.trilha), achou = null;
      for (var k = 0; k < qt.numItems; k++) {
        var it = qt.getItemAt(k);
        if (String(it.type) !== "Clip") continue;
        var ss = t.cabeca ? it.start : it.end;
        var seg = (ss && ss.secs !== undefined) ? Number(ss.secs) : Number(ss.seconds);
        if (Math.abs(seg - t.s) < 0.02) { achou = it; break; }
      }
      if (!achou) { r.erro = "não achei o clipe em " + t.s; out.push(r); continue; }
      // a duração como TC de quadros da sequência (o QE quer texto)
      var st = seq.getSettings(), dur = new Time();
      dur.ticks = String(t.q * tpf);
      var tc = dur.getFormatted(st.videoFrameRate, st.videoDisplayFormat);
      r.nome = String(tr.name); r.tc = tc;
      r.ok = achou.addTransition(tr, t.cabeca, tc, "00:00:00:00", t.al, false, true);
      out.push(r);
    }
  } catch (e) { out.push({ erro: String(e) }); }
  return out;
}

// ⚠️ O nome do efeito sai no IDIOMA do app, e o QE devolve objeto até para nome que não existe (com `name` vazio).
function cicloEfeitoQE(nomes, contem) {
  for (var i = 0; i < nomes.length; i++) {
    var e = qe.project.getVideoEffectByName(nomes[i]);
    if (e && String(e.name)) return e;
  }
  // ⛔ o nome muda com o IDIOMA do Premiere (2026-11-26, 26.0.2 em português: "Cor de Lumetri" — nenhum dos nomes da lista
  //   existia, o molde da cor nunca era montado e os Color Correction do Avid ficavam de fora): a reserva procura na lista
  //   de efeitos o nome que CONTÉM a marca (`contem`, minúsculas), em qualquer idioma
  if (contem) {
    var lista = String(qe.project.getVideoEffectList()).split(",");
    for (var j = 0; j < lista.length; j++) {
      if (lista[j].toLowerCase().indexOf(contem) >= 0) {
        var x = qe.project.getVideoEffectByName(lista[j]);
        if (x && String(x.name)) return x;
      }
    }
  }
  return null;
}

/** O MOLDE da cor do Avid (2026-11-20): ProcAmp → Lumetri no clipe (a ordem e as chamadas da bancada medida).
 * O Premiere grava todos os parâmetros dos dois; a Carta põe a Saturation e a curva de cada clipe. */
function cicloCorDoAvid(seq, pedidos) {
  var out = [];
  try {
    app.enableQE();
    app.project.openSequence(seq.sequenceID);
    var q = qe.project.getActiveSequence();
    var pa = cicloEfeitoQE(["ProcAmp", "Amplificador de processo", "Proc Amp"], "procamp");
    var lu = cicloEfeitoQE(["Lumetri Color", "Cor de Lumetri", "Cor Lumetri", "Lumetri"], "lumetri");
    for (var i = 0; i < pedidos.length; i++) {
      var pd = pedidos[i], r = { pedido: pd };
      if (!pa || !lu) {
        r.erro = "efeito não achado: " + (!pa ? "ProcAmp " : "") + (!lu ? "Lumetri" : "");
        r.lista = String(qe.project.getVideoEffectList()).substring(0, 3000); out.push(r); continue;
      }
      var qt = q.getVideoTrackAt(pd.trilha), achou = null;
      for (var k = 0; k < qt.numItems; k++) {
        var it = qt.getItemAt(k);
        if (String(it.type) !== "Clip") continue;
        var seg = (it.start && it.start.secs !== undefined) ? Number(it.start.secs) : Number(it.start.seconds);
        if (Math.abs(seg - pd.s) < 0.05) { achou = it; break; }
      }
      if (!achou) { r.erro = "não achei o clipe em " + pd.s; out.push(r); continue; }
      achou.addVideoEffect(pa);
      achou.addVideoEffect(lu);
      var tr = seq.videoTracks[pd.trilha], kk = null;
      for (var c = 0; c < tr.clips.numItems; c++)
        if (Math.abs(tr.clips[c].start.seconds - pd.s) < 0.05) { kk = tr.clips[c]; break; }
      var nomes = [];
      if (kk) for (var j = 0; j < kk.components.numItems; j++) {
        nomes.push(String(kk.components[j].matchName));
      }
      r.componentes = nomes;
      r.ok = nomes.join(",").indexOf("AE.ADBE ProcAmp") >= 0 && nomes.join(",").indexOf("AE.ADBE Lumetri") >= 0;
      out.push(r);
    }
  } catch (e) { out.push({ erro: String(e) }); }
  return out;
}

/** O MOLDE do stretch: no Motion do clipe, Uniform Scale desligado, Scale (que vira "Scale Height") = altura e Scale
 * Width = largura. Pelos ÍNDICES (1 Scale, 2 Scale Width, 3 Uniform Scale): o nome do Uniform Scale vem em branco
 * (banco `prproj/estruturas.md`). */
function cicloEsticar(seq, pedidos) {
  var out = [];
  try {
    for (var i = 0; i < pedidos.length; i++) {
      var pd = pedidos[i], r = { pedido: pd }, k = null;
      var tr = (pd.imagem ? seq.videoTracks : seq.audioTracks)[pd.trilha];
      for (var c = 0; c < tr.clips.numItems; c++)
        if (Math.abs(tr.clips[c].start.seconds - pd.s) < 0.05) { k = tr.clips[c]; break; }
      if (!k) { r.erro = "não achei o clipe em " + pd.s; out.push(r); continue; }
      var mov = null;
      for (var j = 0; j < k.components.numItems; j++) if (k.components[j].matchName === "AE.ADBE Motion") mov = k.components[j];
      if (!mov) { r.erro = "o clipe não tem o Motion"; out.push(r); continue; }
      var pr = mov.properties;
      pr[3].setValue(false, true);
      pr[1].setValue(pd.h, true);
      pr[2].setValue(pd.w, true);
      r.valores = [pr[1].getValue(), pr[2].getValue(), pr[3].getValue()];
      out.push(r);
    }
  } catch (e) { out.push({ erro: String(e) }); }
  return out;
}

function cicloVelEDesliga(seq, pedidos) {
  var out = [];
  try {
    app.enableQE();
    app.project.openSequence(seq.sequenceID);
    var q = qe.project.getActiveSequence();
    for (var i = 0; i < pedidos.length; i++) {
      var pd = pedidos[i], r = { pedido: pd };
      if (pd.t === "ds") {
        var tr = (pd.imagem ? seq.videoTracks : seq.audioTracks)[pd.trilha], k = null;
        for (var c = 0; c < tr.clips.numItems; c++)
          if (Math.abs(tr.clips[c].start.seconds - pd.s) < 0.05) { k = tr.clips[c]; break; }
        if (!k) { r.erro = "não achei o clipe em " + pd.s; out.push(r); continue; }
        k.disabled = true;
        r.disabled = k.disabled;
      } else {
        var qt = pd.imagem ? q.getVideoTrackAt(pd.trilha) : q.getAudioTrackAt(pd.trilha), achou = null;
        for (var j = 0; j < qt.numItems; j++) {
          var it = qt.getItemAt(j);
          if (String(it.type) !== "Clip") continue;
          var seg = (it.start && it.start.secs !== undefined) ? Number(it.start.secs) : Number(it.start.seconds);
          if (Math.abs(seg - pd.s) < 0.05) { achou = it; break; }
        }
        if (!achou) { r.erro = "não achei o clipe em " + pd.s; out.push(r); continue; }
        r.ok = achou.setSpeed(pd.v, "", false, false, false);
      }
      out.push(r);
    }
  } catch (e) { out.push({ erro: String(e) }); }
  return out;
}

// O DESTINO do "Importar" da Carta (autor, 2026-11-14: "a bin selecionada, ou a aberta por último"): a bin em que o
// próprio Premiere poria um item novo. Devolve o caminho dela a partir da raiz ("" = a raiz).
function cicloBinDeInsercao(caminhoDoProjeto) {
  try {
    var P = caminhoDoProjeto ? cicloProjetoAberto(caminhoDoProjeto) : app.project;
    if (!P) return cicloErro("o projeto não está aberto");
    var b = P.getInsertionBin(), raiz = P.rootItem;
    if (!b || String(b.nodeId) === String(raiz.nodeId))
      return cicloJ({ caminho: "", nome: "", nodeId: String(raiz.nodeId), raiz: true });
    // ⚠️ o 26.0.2 não tem `getParentItem`: o caminho sai de percorrer a árvore (medido, 2026-11-14)
    var caminho = String(b.name), alvo = String(b.nodeId);
    cicloAndar(raiz, "", function (it, c) {
      if (String(it.nodeId) === alvo) { caminho = c ? c + "/" + it.name : String(it.name); return true; }
      return false;
    });
    return cicloJ({ caminho: caminho, nome: String(b.name), nodeId: alvo, raiz: false });
  } catch (e) { return cicloErro(e); }
}

// Traz sequências de outro .prproj para o projeto ABERTO (o enxerto, §11g) e CONTA o projeto antes e depois — a prova de
// que a mídia não duplicou e de que os merged/subclipes vieram junto. `uids`: os ObjectUID separados por vírgula.
function cicloContarProjeto(proj) {
  var c = {};
  cicloAndar((proj || app.project).rootItem, "", function (it) {
    var e = cicloEspecie(it);
    c[e] = (c[e] || 0) + 1;
    return false;
  });
  return c;
}

function cicloIdsDeSequencias(proj) {
  var r = {}, p = proj || app.project;
  for (var i = 0; i < p.sequences.numSequences; i++) {
    var s = p.sequences[i];
    r[String(s.sequenceID)] = { id: String(s.sequenceID), nome: String(s.projectItem.name), no: String(s.projectItem.nodeId) };
  }
  return r;
}

/** Importa um `.prproj` INTEIRO no projeto aberto, dentro da bin `caminhoDaBin` (criada se faltar) — a CALIBRAGEM do
 * "Importar para o Premiere" (2026-11-14): o projeto-modelo do app, com um merged de mídia sintética, entra na CÓPIA de
 * trabalho para servir de molde. ⭐ O import junta bins pelo NOME e não cria a bin do arquivo (banco
 * `subclipe-e-merged-clip.md` §3d): a bin própria isola o que veio. Conta o projeto antes e depois. */
function cicloImportarProjeto(prproj, caminhoDaBin) {
  try {
    var bin = cicloGarantirBin(caminhoDaBin || "");
    if (!bin) return cicloErro("não consegui criar a bin " + caminhoDaBin);
    var antes = cicloContarProjeto();
    var ok = app.project.importFiles([String(prproj)], true, bin, false);
    return cicloJ({ ok: ok ? true : false, antes: antes, depois: cicloContarProjeto() });
  } catch (e) { return cicloErro(e); }
}

/** Importa VÁRIOS arquivos numa chamada só (uma linha por caminho) na raiz — o Premiere deixa os importados
 * SELECIONADOS (banco, multicâmera no Mac, 2026-11-12), que é o que o menu "Mesclar clipes" pede. */
function cicloImportarJuntos(lista) {
  try {
    var arqs = String(lista).split("\n"), v = [];
    for (var i = 0; i < arqs.length; i++) if (arqs[i]) v.push(arqs[i]);
    var ok = app.project.importFiles(v, true, app.project.rootItem, false);
    var sel = cicloTentar(function () { return app.getCurrentProjectViewSelection(); }, null);
    return cicloJ({ ok: ok ? true : false, pedidos: v.length, selecionados: sel ? sel.length : 0 });
  } catch (e) { return cicloErro(e); }
}

function cicloNosDaRaiz(proj) {
  var r = {}, f = cicloFilhos((proj || app.project).rootItem);
  for (var i = 0; i < f.length; i++) r[String(f[i].nodeId)] = f[i];
  return r;
}

/** `destino`: o nodeId da bin para onde vai TUDO o que a importação pôs na raiz (a sequência e os subclipes que vieram
 * com ela); "" = fica onde o Premiere pôs. `projeto`: o caminho do projeto que RECEBE (aberto, à frente ou não); ""
 * = o ativo. ⭐ Pelo objeto do projeto, não pelo `app.project`: pôr um projeto à frente pela API não é confiável
 * (medido, 26.0.2 Mac, 2026-11-14: `openDocument` falhou 4 vezes seguidas a partir de um projeto e pegou de outro). */
function cicloImportarSequencias(prproj, uids, destino, projeto, binSubclipes) {
  try {
    var P = projeto ? cicloProjetoAberto(projeto) : app.project;
    if (!P) return cicloErro("o projeto " + projeto + " não está aberto no Premiere");
    var antes = cicloContarProjeto(P), ja = cicloIdsDeSequencias(P), raizAntes = cicloNosDaRaiz(P);
    var ok = P.importSequences(String(prproj), String(uids).split(","));
    var depois = cicloContarProjeto(P), agora = cicloIdsDeSequencias(P), novas = [];
    // ⭐ o id que o Premiere dá à sequência importada NÃO é o ObjectUID do arquivo (medido, 2026-11-14): as novas saem
    //   da diferença antes/depois
    for (var k in agora) if (agora.hasOwnProperty(k) && !ja.hasOwnProperty(k)) novas.push(agora[k]);
    var movidos = 0, naRaiz = 0, raiz = cicloNosDaRaiz(P), alvo = null;
    if (destino && String(destino) !== String(P.rootItem.nodeId))
      cicloAndar(P.rootItem, "", function (it) {
        if (String(it.nodeId) === String(destino)) { alvo = it; return true; }
        return false;
      });
    var subclipes = 0;
    for (var n in raiz) if (raiz.hasOwnProperty(n) && !raizAntes.hasOwnProperty(n)) {
      naRaiz++;
      // ⭐ o subclipe que veio com a timeline vai para a pasta dos subclipes (autor, 2026-11-15), o resto para o destino
      if (binSubclipes && cicloEspecie(raiz[n]) === "clipe" && cicloESubclipe(raiz[n])) {
        var bs = cicloGarantirBinEm(P, String(binSubclipes));
        if (bs) { raiz[n].moveBin(bs); subclipes++; continue; }
      }
      if (alvo) { raiz[n].moveBin(alvo); movidos++; }
    }
    return cicloJ({ ok: ok ? true : false, antes: antes, depois: depois, novas: novas, na_raiz: naRaiz,
                    movidos: movidos, subclipes: subclipes, destino: alvo ? String(alvo.name) : "" });
  } catch (e) { return cicloErro(e); }
}

/** Os MARKERS da timeline do Avid na sequência `seqId` do projeto `projeto` ("" = o ativo) — completar a troca (autor,
 * 2026-11-15). `plano` é TEXTO tabulado (⛔ nunca código), uma linha por marker:
 *   início em SEGUNDOS<TAB>duração em segundos<TAB>cor 0..7<TAB>nome<TAB>comentário
 * (`createMarker` conta em SEGUNDOS, não em ticks — banco api-extendscript.md "Marcadores"). No comentário, "\n" vira
 * quebra de linha. Devolve quantos foram criados. */
/** O Stabilize do Avid → o WARP STABILIZER do Premiere (decisão do autor, 2026-11-20: estabilizador → estabilizador),
 * na sequência que acabou de entrar no projeto do editor. Uma linha por clipe: trilha de vídeo (do 0) TAB segundos (o
 * MEIO do segmento do Avid: uma transição pode mover o começo) TAB Method TAB Result TAB Smoothness TAB Framing (os
 * índices do menu). O efeito vai pelo QE, que só enxerga a sequência ATIVA do projeto ATIVO: o projeto do editor tem de
 * estar à frente. A análise roda sozinha, em segundo plano no Premiere. */
function cicloEstabilizar(seqId, projeto, plano) {
  try {
    var P = projeto ? cicloProjetoAberto(projeto) : app.project;
    if (!P) return cicloErro("o projeto " + projeto + " não está aberto no Premiere");
    var s = null;
    for (var i = 0; i < P.sequences.numSequences; i++)
      if (String(P.sequences[i].sequenceID) === String(seqId)) { s = P.sequences[i]; break; }
    if (!s) return cicloErro("não achei a sequência " + seqId);
    P.openSequence(s.sequenceID);
    app.enableQE(); qe.project.init();
    var q = qe.project.getActiveSequence(), efeito = null;
    var nomes = ["Warp Stabilizer", "Estabilizador de distorção", "Estabilizador de deformação"];
    for (var n = 0; n < nomes.length && !efeito; n++) {
      var e = qe.project.getVideoEffectByName(nomes[n]);
      if (e && e.name) efeito = e;          // ⛔ o QE devolve objeto até para nome que não existe (com `name` vazio)
    }
    if (!efeito) return cicloErro("o Premiere não tem o Warp Stabilizer com nenhum destes nomes: " + nomes.join(", "));
    var linhas = String(plano).split("\n"), feitos = [], falhas = [];
    for (var k = 0; k < linhas.length; k++) {
      if (!linhas[k]) continue;
      var c = linhas[k].split("\t"), tr = parseInt(c[0], 10), seg = parseFloat(c[1]);
      try {
        var qt = q.getVideoTrackAt(tr), alvo = null;
        for (var j = 0; j < qt.numItems; j++) {
          var it = qt.getItemAt(j);
          if (String(it.type) !== "Clip") continue;
          if (Number(it.start.secs) <= seg && seg < Number(it.end.secs)) { alvo = it; break; }
        }
        if (!alvo) { falhas.push(k + ": não achei o clipe em " + seg + " s na V" + (tr + 1)); continue; }
        alvo.addVideoEffect(efeito);
        var dc = s.videoTracks[tr].clips, clipe = null, comp = null;
        for (var d = 0; d < dc.numItems; d++)
          if (dc[d].start.seconds <= seg && seg < dc[d].end.seconds) { clipe = dc[d]; break; }
        if (clipe) for (var m = 0; m < clipe.components.numItems; m++)
          if (clipe.components[m].matchName === "AE.ADBE SubspaceStabilizer") comp = clipe.components[m];
        if (!comp) { falhas.push(k + ": o efeito não apareceu no clipe"); continue; }
        var pr = comp.properties;
        pr[5].setValue(parseInt(c[2], 10), true);      // Method
        pr[3].setValue(parseInt(c[3], 10), true);      // Result
        pr[4].setValue(parseFloat(c[4]), true);        // Smoothness
        pr[9].setValue(parseInt(c[5], 10), true);      // Framing
        feitos.push({ clipe: String(clipe.name), v: [pr[5].getValue(), pr[3].getValue(), pr[4].getValue(), pr[9].getValue()] });
      } catch (e2) { falhas.push(k + ": " + e2); }
    }
    return cicloJ({ aplicados: feitos.length, feitos: feitos, falhas: falhas });
  } catch (e) { return cicloErro(e); }
}

function cicloMarcarSequencia(seqId, projeto, plano) {
  try {
    var P = projeto ? cicloProjetoAberto(projeto) : app.project;
    if (!P) return cicloErro("o projeto " + projeto + " não está aberto no Premiere");
    var s = null;
    for (var i = 0; i < P.sequences.numSequences; i++)
      if (String(P.sequences[i].sequenceID) === String(seqId)) { s = P.sequences[i]; break; }
    if (!s) return cicloErro("não achei a sequência " + seqId);
    var linhas = String(plano).split("\n"), criados = 0, falhas = [];
    for (var k = 0; k < linhas.length; k++) {
      if (!linhas[k]) continue;
      var c = linhas[k].split("\t");
      try {
        var m = s.markers.createMarker(parseFloat(c[0]), String(c[3] || ""), parseFloat(c[1] || "0"));
        if (c[4]) m.comments = String(c[4]).replace(/\\n/g, "\n");
        m.setColorByIndex(parseInt(c[2] || "0", 10));
        criados++;
      } catch (e) { falhas.push(k + ": " + e); }
    }
    return cicloJ({ criados: criados, falhas: falhas });
  } catch (e) { return cicloErro(e); }
}

// ── os projetos ABERTOS (o 26 tem vários) — o "Importar para o Premiere" abre a CÓPIA de trabalho ao lado do projeto do
// editor, monta nela os moldes que faltam, fecha-a e volta ao dele (2026-11-14). `app.project` é o ATIVO (a aba à frente).
function cicloProjetosAbertos() {
  try {
    var r = [];
    for (var i = 0; i < app.projects.numProjects; i++) r.push(String(app.projects[i].path));
    return cicloJ({ abertos: r, ativo: cicloCaminhoAberto() });
  } catch (e) { return cicloErro(e); }
}

function cicloProjetoAberto(caminho) {
  for (var i = 0; i < app.projects.numProjects; i++)
    if (cicloMesmo(String(app.projects[i].path), caminho)) return app.projects[i];
  return null;
}

/** Põe `caminho` (já aberto) À FRENTE e CONFERE: `openDocument` de um projeto aberto só o ativa (não abre de novo, não
 * pergunta, devolve `false` mesmo ativando — 26.0.2 Mac, 2026-11-14). ⛔ Às vezes o `app.project` continua o antigo logo
 * depois (medido: 1 vez em ~10, com o Premiere recém-ocupado) — espera e tenta de novo, até 4 vezes. */
function cicloFrente(caminho) {
  for (var t = 0; t < 4; t++) {
    if (cicloMesmo(cicloCaminhoAberto(), caminho)) return t;
    app.openDocument(caminho, true, true, true);
    for (var w = 0; w < 10 && !cicloMesmo(cicloCaminhoAberto(), caminho); w++) $.sleep(100);
  }
  return cicloMesmo(cicloCaminhoAberto(), caminho) ? 4 : -1;
}

/** Fecha o projeto `caminho` (aberto, ativo ou não) SEM salvar e sem perguntar, e põe `voltarPara` à frente.
 * ⛔ MEDIDO (26.0.2 Mac, 2026-11-14): fechar um projeto que está ATRÁS põe OUTRO à frente (não o que estava). */
function cicloFecharProjeto(caminho, voltarPara) {
  try {
    var p = cicloProjetoAberto(caminho);
    if (!p) return cicloJ({ fechado: false, motivo: "não está aberto", ativo: cicloCaminhoAberto() });
    var volta = voltarPara || cicloCaminhoAberto();
    var ok = p.closeDocument(0, 0), tentativas = null;
    if (volta && !cicloMesmo(volta, caminho) && cicloProjetoAberto(volta)) tentativas = cicloFrente(volta);
    return cicloJ({ fechado: ok ? true : false, ativo: cicloCaminhoAberto(), tentativas: tentativas });
  } catch (e) { return cicloErro(e); }
}

/** Põe o projeto `caminho` (já aberto) À FRENTE (`cicloFrente`). */
function cicloAtivarProjeto(caminho) {
  try {
    if (!cicloProjetoAberto(caminho)) return cicloJ({ como: "nao_aberto", ativo: cicloCaminhoAberto() });
    var t = cicloFrente(caminho);
    return cicloJ({ como: t === 0 ? "ja_ativo" : "ativado", tentativas: t, ativo: cicloCaminhoAberto() });
  } catch (e) { return cicloErro(e); }
}

function cicloPorNivel(trilha, pos, nivel) {
  for (var c = 0; c < trilha.clips.numItems; c++) {
    var k = trilha.clips[c];
    if (Math.abs(k.start.seconds - pos) > 0.05) continue;
    for (var j = 0; j < k.components.numItems; j++) {
      var co = k.components[j], nomes = String(co.displayName) + "|" + String(co.matchName);
      if (!/volume/i.test(nomes) || /channel|canal/i.test(nomes)) continue;
      for (var q = 0; q < co.properties.numItems; q++) {
        var pr = co.properties[q], dn = String(pr.displayName);
        if (!/level|n[ií]vel/i.test(dn)) continue;
        var antes = pr.getValue();
        pr.setValue(nivel, true);
        return { componente: nomes, parametro: dn, antes: antes, depois: pr.getValue() };
      }
    }
    return { erro: "não achei o Level do Volume", componentes: k.components.numItems };
  }
  return { erro: "não achei o clipe em " + pos };
}

/* ── importar a diária, com ou sem o proxy anexado (P2 da diária no Premiere, 2026-11-07) ─────────────
 * `plano` é TEXTO tabulado (⛔ nunca código):
 *   bin<TAB>caminho "A/B"            (criada se faltar; vale para as linhas seguintes)
 *   arq<TAB>caminho do arquivo<TAB>caminho do proxy (vazio = sem proxy)
 * O arquivo que JÁ está no projeto (mesmo caminho de mídia) não é importado de novo: reimportar
 * cria um segundo item da mesma mídia. O proxy, quando pedido, é anexado a ele.
 * ⛔ O `attachProxy` só confere o número de canais (banco, painel-servido-e-identidade §4): quem
 * chama já conferiu o par — aqui só se anexa e se LÊ DE VOLTA. */
function cicloNormal(c) { return String(c || "").replace(/\\/g, "/").toLowerCase(); }
function cicloSombra(c) { return /(^|[\\\/])\._[^\\\/]*$/.test(String(c || "")); }
/** A extensão que NUNCA é mídia, ou "" (autor, 2026-11-15: um PDF na lista abre "File Import Failure", que SEGURA o
 * script até alguém clicar em OK — medido no 27.0). Só o que com certeza não é mídia: um formato de mídia que falta
 * plugin (BRAW sem o da Blackmagic) passa daqui, e é o Premiere quem recusa. */
function cicloNaoMidia(c) {
  var m = /\.([A-Za-z0-9_]+)$/.exec(String(c || ""));   // com o "_": o ".DS_Store" do Finder
  var e = m ? m[1].toLowerCase() : "";
  var docs = { pdf: 1, doc: 1, docx: 1, rtf: 1, txt: 1, md: 1, pages: 1, odt: 1, xls: 1, xlsx: 1, csv: 1, numbers: 1,
               ods: 1, ppt: 1, pptx: 1, key: 1, zip: 1, rar: 1, "7z": 1, dmg: 1, pkg: 1, exe: 1, html: 1, htm: 1,
               json: 1, log: 1, lnk: 1, url: 1, webloc: 1, ds_store: 1, db: 1 };
  return docs[e] ? e : "";
}

function cicloImportar(plano) {
  try {
    var porMidia = {};
    cicloAndar(app.project.rootItem, "", function (it, caminho) {
      var m = cicloTentar(function () { return it.getMediaPath(); }, "");
      if (m && cicloEspecie(it) === "clipe" && !porMidia[cicloNormal(m)])
        porMidia[cicloNormal(m)] = { item: it, bin: caminho };
    });
    // 1ª passada: o plano lido, e o que FALTA agrupado por bin. ⭐ Uma chamada de importFiles por bin, com a lista
    //   inteira (autor, 2026-11-15: um importFiles por arquivo fazia a janela de importar piscar centenas de vezes)
    var linhas = String(plano).split("\n"), bin = app.project.rootItem, nomeBin = "", feitos = [], pedidos = [];
    var lotes = [], lote = null, naFila = {};
    for (var i = 0; i < linhas.length; i++) {
      if (!linhas[i]) continue;
      var p = linhas[i].split("\t");
      if (p[0] === "bin") {
        nomeBin = p[1] || "";
        bin = cicloGarantirBin(nomeBin);
        if (!bin) return cicloJ({ erro: "não consegui criar a bin " + nomeBin });
        lote = null;
        continue;
      }
      if (p[0] !== "arq") continue;
      var arq0 = p[1] || "";
      pedidos.push({ arq: arq0, prox: p[2] || "", nomeBin: nomeBin, bin: bin });
      // ⛔ a sombra `._` do macOS no exFAT nunca é mídia: o Premiere a recusa calado (medido, 27.0, 2026-11-15)
      if (cicloSombra(arq0) || cicloNaoMidia(arq0)) continue;
      if (porMidia[cicloNormal(arq0)] || naFila[cicloNormal(arq0)]) continue;
      if (!lote) { lote = { bin: bin, nomeBin: nomeBin, arqs: [] }; lotes.push(lote); }
      lote.arqs.push(arq0);
      naFila[cicloNormal(arq0)] = lote;
    }
    for (var l = 0; l < lotes.length; l++) {
      var L = lotes[l];
      L.ok = cicloTentar(function () { return app.project.importFiles(L.arqs, true, L.bin, false); }, false);
      // o que entrou se CONFERE pelo caminho de mídia dos filhos da bin (nunca pelo retorno do importFiles)
      var f = cicloFilhos(L.bin);
      for (var k = 0; k < f.length; k++) {
        var mk = cicloNormal(cicloTentar(function () { return f[k].getMediaPath(); }, ""));
        if (mk && naFila[mk] === L && !porMidia[mk]) porMidia[mk] = { item: f[k], bin: L.nomeBin, novo: true };
      }
    }
    // 2ª passada: arquivo a arquivo, na ordem do plano — o que entrou, o que já estava e o proxy
    for (var j = 0; j < pedidos.length; j++) {
      var arq = pedidos[j].arq, prox = pedidos[j].prox, r = { arquivo: arq, bin: pedidos[j].nomeBin };
      if (cicloSombra(arq)) { r.ignorado = "sombra do macOS (._), não é mídia"; feitos.push(r); continue; }
      if (cicloNaoMidia(arq)) {
        r.erro = "não é mídia (." + cicloNaoMidia(arq) + "): não foi enviado ao Premiere";
        feitos.push(r);
        continue;
      }
      var ach = porMidia[cicloNormal(arq)];
      if (ach && !ach.novo) { r.ja_estava = true; r.bin = ach.bin; }
      if (ach && ach.novo) ach.novo = false;          // um 2º pedido do mesmo arquivo já o encontra no projeto
      if (!ach) {
        var lt = naFila[cicloNormal(arq)];
        r.erro = "o Premiere não importou o arquivo" + (lt && !lt.ok ? " (importFiles recusou)" : "");
        feitos.push(r);
        continue;
      }
      var it = ach.item;
      r.id = String(it.nodeId); r.nome = String(it.name);
      if (prox) {
        r.proxy_pedido = prox;
        var jaTem = cicloTentar(function () { return it.hasProxy() ? String(it.getProxyPath()) : ""; }, "");
        if (cicloNormal(jaTem) === cicloNormal(prox)) r.anexou = true;
        else if (!cicloTentar(function () { return it.canProxy(); }, false)) r.erro = "este item não aceita proxy (canProxy falso)";
        else {
          var ret = cicloTentar(function () { return it.attachProxy(prox, 0); }, false);
          var lido = cicloTentar(function () { return it.hasProxy() ? String(it.getProxyPath()) : ""; }, "");
          r.anexou = (cicloNormal(lido) === cicloNormal(prox));
          if (!r.anexou) r.erro = "o Premiere recusou o proxy" + (ret ? " (devolveu true, mas não ficou)" : "") +
                                    " — ele recusa quando o número de canais de som difere";
        }
        r.proxy = cicloTentar(function () { return it.hasProxy() ? String(it.getProxyPath()) : ""; }, "");
      }
      r.midia = cicloTentar(function () { return String(it.getMediaPath()); }, "");
      feitos.push(r);
    }
    return cicloJ({ feitos: feitos });
  } catch (e) { return cicloErro(e); }
}
// A Carta Aberta: PUXAR TIMELINE (cicloassist/carta/entrega_premiere.py). O XML de timeline (FCP7 xmeml) importado
// numa bin; devolve as sequências NOVAS (as que não existiam antes) com o que cada trilha tem. Contar, nunca confiar
// no retorno do importFiles (banco api-extendscript.md: ele devolve true e às vezes não traz nada).
function cicloImportarTimeline(caminho, nomeDaBin) {
  try {
    var antes = {}, i, k;
    for (i = 0; i < app.project.sequences.numSequences; i++) antes[String(app.project.sequences[i].sequenceID)] = true;
    var bin = cicloGarantirBin(nomeDaBin || "");
    if (!bin) return cicloJ({ erro: "não consegui criar a bin " + nomeDaBin });
    var t0 = new Date().getTime();
    var ok = cicloTentar(function () { return app.project.importFiles([caminho], true, bin, false); }, false);
    var novas = [];
    for (i = 0; i < app.project.sequences.numSequences; i++) {
      var s = app.project.sequences[i];
      if (antes[String(s.sequenceID)]) continue;
      var v = [], a = [];
      for (k = 0; k < s.videoTracks.numTracks; k++) v.push(s.videoTracks[k].clips.numItems);
      for (k = 0; k < s.audioTracks.numTracks; k++) a.push(s.audioTracks[k].clips.numItems);
      novas.push({ nome: String(s.name), id: String(s.sequenceID), video: v, audio: a,
                   inicio: cicloTentar(function () { return String(s.getZeroPoint()); }, ""),
                   fim: cicloTentar(function () { return String(s.end); }, "") });
    }
    return cicloJ({ ok: ok, novas: novas, itens_na_bin: cicloFilhos(bin).length,
                    ms: new Date().getTime() - t0 });
  } catch (e) { return cicloErro(e); }
}
// As sequências do projeto (id e nome) e o que há na bin `nomeDaBin`: a conferência do PUXAR TIMELINE.
function cicloSequencias(nomeDaBin) {
  try {
    var out = [], i, nomes = [];
    for (i = 0; i < app.project.sequences.numSequences; i++)
      out.push({ nome: String(app.project.sequences[i].name), id: String(app.project.sequences[i].sequenceID) });
    var bin = nomeDaBin ? cicloBinAlvo(nomeDaBin) : null, f = bin ? cicloFilhos(bin) : [];
    for (i = 0; i < f.length && i < 50; i++) nomes.push(String(f[i].name));
    var raiz = cicloFilhos(app.project.rootItem), r = [];
    for (i = 0; i < raiz.length && i < 80; i++) r.push(String(raiz[i].name));
    return cicloJ({ sequencias: out, bin: nomes, raiz: r, projeto: String(app.project.path) });
  } catch (e) { return cicloErro(e); }
}
