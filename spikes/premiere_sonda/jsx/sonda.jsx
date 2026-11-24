/*
 * sonda.jsx — o que o Premiere diz de um item, medido num projeto NOVO e descartável.
 *
 * Roda dentro do Premiere (a página da sonda chama por evalScript). ES3: sem JSON
 * garantido, sem let, sem arrow — por isso o serializador de bolso.
 */

var TICKS = 254016000000;

function sj(v) {
  if (v === null || v === undefined) return "null";
  var t = typeof v;
  if (t === "number") return isFinite(v) ? String(v) : "null";
  if (t === "boolean") return v ? "true" : "false";
  if (t === "string") {
    return '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"')
      .replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/\t/g, "\\t") + '"';
  }
  if (v instanceof Array) {
    var a = [];
    for (var i = 0; i < v.length; i++) a.push(sj(v[i]));
    return "[" + a.join(",") + "]";
  }
  var p = [];
  for (var k in v) if (v.hasOwnProperty(k)) p.push(sj(String(k)) + ":" + sj(v[k]));
  return "{" + p.join(",") + "}";
}

function tentar(f) {
  try { return f(); } catch (e) { return "!" + String(e); }
}

function tempo(t) {
  if (!t || typeof t === "string") return t;
  return tentar(function () { return { ticks: String(t.ticks), s: t.seconds }; });
}

/** O trecho de um XMP/metadado que interessa, sem trazer o documento inteiro. */
function trechos(xml, nomes) {
  var out = {};
  if (typeof xml !== "string") return xml;
  for (var i = 0; i < nomes.length; i++) {
    var re = new RegExp("<[^>]*" + nomes[i] + "[^>]*>([^<]*)<", "i");
    var m = re.exec(xml);
    if (!m) {
      re = new RegExp(nomes[i] + '="([^"]*)"', "i");
      m = re.exec(xml);
    }
    out[nomes[i]] = m ? m[1] : null;
  }
  out._tamanho = xml.length;
  return out;
}

function descrever(it) {
  var d = {};
  d.nome = tentar(function () { return it.name; });
  d.tipo = tentar(function () { return it.type; });
  d.nodeId = tentar(function () { return it.nodeId; });
  d.treePath = tentar(function () { return it.treePath; });
  d.mediaPath = tentar(function () { return it.getMediaPath(); });
  d.canProxy = tentar(function () { return it.canProxy(); });
  d.hasProxy = tentar(function () { return it.hasProxy(); });
  d.proxyPath = tentar(function () { return it.getProxyPath(); });
  d.isOffline = tentar(function () { return it.isOffline(); });
  d.isSequence = tentar(function () { return it.isSequence(); });
  d.isMergedClip = tentar(function () { return it.isMergedClip(); });
  d.startTime = tempo(tentar(function () { return it.startTime(); }));
  d.inPoint = tempo(tentar(function () { return it.getInPoint(); }));
  d.outPoint = tempo(tentar(function () { return it.getOutPoint(); }));
  d.fps = tentar(function () {
    var fi = it.getFootageInterpretation();
    return { frameRate: fi.frameRate, fieldType: fi.fieldType, pixelAspectRatio: fi.pixelAspectRatio };
  });
  d.projeto = trechos(tentar(function () { return it.getProjectMetadata(); }),
                      ["Column.Intrinsic.MediaStart", "Column.Intrinsic.MediaDuration",
                       "Column.Intrinsic.TapeName", "Column.Intrinsic.FilePath",
                       "Column.Intrinsic.VideoInfo", "Column.PropertyText.Label"]);
  d.xmp = trechos(tentar(function () { return it.getXMPMetadata(); }),
                  ["xmpDM:startTimecode", "xmpDM:timeValue", "xmpDM:altTapeName",
                   "xmpDM:tapeName", "xmpMM:InstanceID", "xmpMM:DocumentID",
                   "xmpMM:OriginalDocumentID", "xmpDM:duration"]);
  return d;
}

function filhos(pasta) {
  var out = [];
  for (var i = 0; i < pasta.children.numItems; i++) out.push(pasta.children[i]);
  return out;
}

function achar(nome) {
  var f = filhos(app.project.rootItem);
  for (var i = 0; i < f.length; i++) if (f[i].name === nome) return f[i];
  return null;
}

/** 1. o ambiente e o projeto novo. */
function sondaAbrir(caminhoProjeto) {
  var r = { versao: tentar(function () { return app.version; }),
            build: tentar(function () { return app.build; }),
            projetoAntes: tentar(function () { return app.project ? app.project.path : null; }) };
  r.newProject = tentar(function () { return app.newProject(caminhoProjeto); });
  r.projetoDepois = tentar(function () { return app.project.path; });
  return sj(r);
}

/** 2. importar e descrever; `lista` vem separada por "|". */
function sondaImportar(lista) {
  var caminhos = lista.split("|");
  var r = { importFiles: tentar(function () {
    return app.project.importFiles(caminhos, true, app.project.rootItem, false);
  }) };
  var f = filhos(app.project.rootItem);
  r.itens = [];
  for (var i = 0; i < f.length; i++) r.itens.push(descrever(f[i]));
  return sj(r);
}

/** 3. anexar o proxy e ver o que muda no item. */
function sondaProxy(nome, proxy) {
  var it = achar(nome);
  if (!it) return sj({ erro: "sem item " + nome });
  var r = { antes: descrever(it) };
  r.attachProxy = tentar(function () { return it.attachProxy(proxy, 0); });
  r.depois = descrever(it);
  return sj(r);
}

/** 4. subclipe: o que ele aponta e em que tempo fala. */
function sondaSubclipe(nome) {
  var it = achar(nome);
  if (!it) return sj({ erro: "sem item " + nome });
  var r = {};
  var novo = tentar(function () {
    return it.createSubClip("SUB_" + nome, String(2 * TICKS), String(5 * TICKS), 0, 1, 1);
  });
  r.devolveu = typeof novo === "string" ? novo : "objeto";
  var sub = achar("SUB_" + nome);
  r.sub = sub ? descrever(sub) : null;
  return sj(r);
}

/** 5. a seleção da bin, para medir a ida e volta com algo de verdade. */
function sondaSelecao() {
  var s = tentar(function () { return app.getCurrentProjectViewSelection(); });
  var n = 0;
  try { n = s ? s.length : 0; } catch (e) { n = -1; }
  return sj({ selecao: n, itens: app.project.rootItem.children.numItems });
}

/** 6. fechar sem salvar e sair. */
function sondaSair() {
  var r = {};
  r.fechar = tentar(function () { return app.project.closeDocument(0, 0); });
  r.quit = tentar(function () { return app.quit(); });
  return sj(r);
}
