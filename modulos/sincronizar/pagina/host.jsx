/*
 * host.jsx — ExtendScript que roda DENTRO do Premiere (o painel CEP chama via
 * evalScript). Nenhuma lógica de sync mora aqui; só o que exige estar dentro do host:
 *   1. ler a seleção — da BIN (sincGetSelectionPaths) ou da TIMELINE ativa
 *      (sincGetTimelineSelection), com as versões "só contar" para o feedback ao vivo;
 *   2. montar a sequência nativa a partir do mapa do Órbita (sincBuildSequence);
 *   3. mover clipes que já estão na timeline (sincMoveTimelineClips, sincCloseGaps).
 *
 * ExtendScript é ES3 e o `JSON` global não é garantido aqui — por isso a seleção
 * volta como texto: paths separados por "\n" (o painel dá split). Caminho de arquivo
 * com "\n" no meio não existe na prática.
 */

// ProjectItemType.CLIP = 1, BIN = 2 (constantes do Premiere; fixadas para não
// depender do enum estar exposto em toda versão).
var SINC_TYPE_CLIP = 1;
var SINC_TYPE_BIN = 2;

// Extensões de mídia — ESPELHO de `MEDIA_EXTENSIONS` em `src-tauri/src/fs_expand.rs`.
// `plugins/tests/premiere-selecao.cjs` reprova se as duas listas divergirem.
//
// Por que um espelho e não só o `/sources` do servidor: o "Adicionar à fonte" e a
// contagem ao vivo do botão não passam por ele, e a bin do Premiere aceita still,
// PSD, LUT e legenda — todos com `getMediaPath()` preenchido.
var SINC_MEDIA_EXT = ["mp4", "mxf", "mov", "avi", "mkv", "mts", "m2ts", "m2t", "r3d",
                        "braw", "wav", "aac", "mp3", "aiff"];

/**
 * O caminho de mídia de um item da bin, ou "" se ele não for câmera/som.
 *
 * ⛔ `type` não serve: sequência e camada de ajuste se declaram CLIP. Os dois são
 * recusados pelos predicados, antes de tudo (medido na bin do Premiere, 2026-09-06);
 * o resto passa pela extensão.
 */
function sincMediaPath(item) {
  try { if (item.isSequence && item.isSequence()) return ""; } catch (e) { /* segue */ }
  try { if (item.isAdjustmentLayer && item.isAdjustmentLayer()) return ""; } catch (e) { /* segue */ }
  var path = "";
  try { path = String(item.getMediaPath() || ""); } catch (e) { return ""; }
  // O `._arquivo` do macOS (AppleDouble) tem a extensão do arquivo de verdade e não é
  // mídia: um SSD que passou pelo Mac o traz para a bin (autor, 2026-10-21).
  if (/(^|[\\\/])\._[^\\\/]*$/.test(path)) return "";
  var m = /\.([^.\\\/]+)$/.exec(path);
  if (!m) return "";
  var ext = m[1].toLowerCase();
  for (var i = 0; i < SINC_MEDIA_EXT.length; i++) {
    if (SINC_MEDIA_EXT[i] === ext) return path;
  }
  return "";
}

/**
 * Caminhos de mídia dos clipes SELECIONADOS na bin, um por linha. Se um BIN estiver
 * selecionado, desce recursivamente. Ignora o que não é câmera/som (sincMediaPath).
 *
 * NÃO agrupa por bin pai: no modelo do painel, é o USUÁRIO que declara a fonte
 * ("Adicionar Câmera"/"Adicionar Som Direto"), e o servidor classifica a seleção pela
 * heurística do esqueleto de nome (reúne os cartões). Por isso aqui é só a lista de paths
 * — barato, sem varrer o projeto inteiro.
 */
function sincGetSelectionPaths() {
  if (!app.project) return "";
  var out = [], seen = {};
  function pushClip(item) {
    var path = sincMediaPath(item);
    if (path && !seen[path]) { seen[path] = true; out.push(path); }
  }
  function walk(item) {
    if (!item) return;
    if (item.type === SINC_TYPE_BIN) {
      var kids = item.children;
      if (kids) for (var i = 0; i < kids.numItems; i++) walk(kids[i]);
    } else {
      pushClip(item);
    }
  }

  var sel = sincSelection();
  for (var i = 0; i < sel.length; i++) walk(sel[i]);
  return out.join("\n");
}

/** A seleção do painel Project, tolerante a versão. */
function sincSelection() {
  var sel = [];
  try {
    // É método de Application, não de Project. `app.project.getSelection` fica
    // só como defesa (não existe no 25.6.5).
    if (typeof app.getCurrentProjectViewSelection === "function") {
      sel = app.getCurrentProjectViewSelection() || [];
    } else if (app.project && typeof app.project.getSelection === "function") {
      sel = app.project.getSelection() || [];
    }
  } catch (e) { sel = []; }
  return sel;
}

/** Nome limpo de um item (o painel recebe campos separados por TAB). */
function sincCleanName(item) {
  var n = "";
  try { n = item && item.name ? String(item.name) : ""; } catch (e) { n = ""; }
  return n.replace(/[\t\r\n]+/g, " ");
}

/**
 * Feedback ao vivo do que "Adicionar" vai capturar: `contagem\tnome`.
 *
 * A contagem é de itens COM MÍDIA (expandindo bins), sem varrer o projeto inteiro.
 * O NOME é o rótulo que vai no botão ("Adicionar CAM A"): o bin selecionado quando é
 * um bin, ou o bin PAI quando são clipes soltos — e só se for o MESMO para todos,
 * senão volta vazio e o painel usa um rótulo genérico. O pai vem de `item.parent`,
 * que nem toda versão expõe; sem ele o painel não fica pior do que era.
 */
function sincGetSelectionInfo() {
  if (!app.project) return "0\t";
  var n = 0, seen = {};
  function count(item) {
    if (!item) return;
    if (item.type === SINC_TYPE_BIN) {
      var kids = item.children;
      if (kids) for (var i = 0; i < kids.numItems; i++) count(kids[i]);
    } else {
      var path = sincMediaPath(item);
      if (path && !seen[path]) { seen[path] = true; n++; }
    }
  }
  var sel = sincSelection();
  var name = null, mixed = false;
  for (var s = 0; s < sel.length; s++) {
    count(sel[s]);
    var here = "";
    if (sel[s] && sel[s].type === SINC_TYPE_BIN) here = sincCleanName(sel[s]);
    else {
      try {
        // `parent` não é garantido; quando falta, o rótulo genérico resolve. A raiz
        // do projeto não conta como bin (o nome dela é o do PROJETO, não da fonte).
        var par = sel[s] ? sel[s].parent : null;
        if (par && par !== app.project.rootItem) here = sincCleanName(par);
      } catch (e) { here = ""; }
    }
    if (!here) { mixed = true; continue; }
    if (name === null) name = here;
    else if (name !== here) mixed = true;
  }
  return String(n) + "\t" + (mixed || name === null ? "" : name);
}

/**
 * Importa o .prproj gerado pelo Órbita no projeto aberto. Importar um .prproj traz as
 * SEQUÊNCIAS dele (a timeline sincronizada) para o projeto atual, com a mídia religada.
 * Devolve "ok" ou "erro: <mensagem>". (Caminho LEGADO — reimporta mídia; ver
 * sincBuildSequence para a montagem nativa.)
 */
function sincImport(prprojPath) {
  try {
    if (!app.project) return "erro: nenhum projeto aberto";
    var root = app.project.rootItem;
    // importFiles(paths, suppressUI, targetBin, importAsNumberedStills)
    var ok = app.project.importFiles([prprojPath], true, root, false);
    return ok ? "ok" : "erro: importFiles retornou false";
  } catch (e) {
    return "erro: " + e.toString();
  }
}

// ── Montagem NATIVA da sequência (Órbita como "mapa" de sync) ────────────────────
// Em vez de importar um .prproj (que RE-IMPORTA a mídia e vira "escadinha"), montamos
// a sequência com os ProjectItems que JÁ estão na bin, colocando cada clipe no seu TC.
// O painel manda o mapa já com a track de cada clipe (o packing é feito lá, em JS
// moderno); aqui só posicionamos. Zero reimportação; tracks compartilhadas.

/** Indexa TODO o projeto por caminho de mídia em disco → ProjectItem. */
function sincIndexProject() {
  var idx = {};
  function walk(item) {
    if (!item) return;
    var kids = item.children;
    var n = kids ? kids.numItems : 0;
    for (var i = 0; i < n; i++) walk(kids[i]);
    var p = "";
    try { p = item.getMediaPath(); } catch (e) { p = ""; }
    if (p && !idx[p]) idx[p] = item;
  }
  walk(app.project.rootItem);
  return idx;
}

/** Acha um bin filho pelo nome, ou cria. Devolve o pai se não conseguir criar —
 *  importar na raiz é pior que não importar? Não: é melhor que falhar. */
function sincFindOrCreateBin(parent, name) {
  if (!name) return parent;
  var kids = parent.children, n = kids ? kids.numItems : 0, i;
  for (i = 0; i < n; i++) {
    if (kids[i] && kids[i].type === SINC_TYPE_BIN && String(kids[i].name) === name) {
      return kids[i];
    }
  }
  try { parent.createBin(name); } catch (e) { return parent; }
  kids = parent.children; n = kids ? kids.numItems : 0;
  for (i = 0; i < n; i++) {
    if (kids[i] && kids[i].type === SINC_TYPE_BIN && String(kids[i].name) === name) {
      return kids[i];
    }
  }
  return parent;
}

/**
 * Importa para o projeto os arquivos do mapa que AINDA NÃO ESTÃO nele.
 *
 * A montagem nativa posiciona ProjectItems que já existem na bin — se o material foi
 * organizado no Órbita e nunca entrou no Premiere, não há o que posicionar (era o
 * "nenhum ProjectItem casou com o mapa"). Então, antes de montar, o que falta entra:
 * numa bin com o nome da diária e, dentro dela, uma sub-bin por fonte (CAM A, SOM
 * DIRETO…). O que JÁ está no projeto não é tocado — nada de mídia duplicada, e a
 * organização de pastas de quem já tinha o material continua como estava.
 *
 * `paths` e `labels` chegam como texto (ES3 não garante JSON aqui): um caminho por
 * linha, e "caminho<TAB>rótulo" por linha.
 */
function sincImportMissing(pathsStr, binName, labelsStr) {
  try {
    if (!app.project) return "err|nenhum projeto aberto";
    var paths = String(pathsStr || "").split("\n");
    var label = {}, lines = String(labelsStr || "").split("\n"), i;
    for (i = 0; i < lines.length; i++) {
      if (!lines[i]) continue;
      var tab = lines[i].indexOf("\t");
      if (tab > 0) label[lines[i].substring(0, tab)] = lines[i].substring(tab + 1);
    }

    var idx = sincIndexProject();
    var missing = [], byLabel = {}, order = [];
    for (i = 0; i < paths.length; i++) {
      var p = paths[i];
      if (!p || idx[p]) continue;
      missing.push(p);
      var lab = label[p] || "";
      if (!byLabel[lab]) { byLabel[lab] = []; order.push(lab); }
      byLabel[lab].push(p);
    }
    if (missing.length === 0) return "ok|imported=0|failed=0";

    var bin = sincFindOrCreateBin(app.project.rootItem, binName);
    for (i = 0; i < order.length; i++) {
      var target = sincFindOrCreateBin(bin, order[i]);
      // importFiles(paths, suppressUI, targetBin, importAsNumberedStills)
      try { app.project.importFiles(byLabel[order[i]], true, target, false); } catch (e) { /* conta abaixo */ }
    }

    // Quem manda no resultado é o PROJETO, não o retorno do importFiles: reindexa e
    // conta quantos passaram a existir de verdade.
    var after = sincIndexProject(), ok = 0;
    for (i = 0; i < missing.length; i++) if (after[missing[i]]) ok++;
    return "ok|imported=" + ok + "|failed=" + (missing.length - ok);
  } catch (e) {
    return "err|" + e.toString();
  }
}

/** Cria uma sequência com as configurações do primeiro clipe e a deixa VAZIA. */
function sincNewEmptySequence(name, firstItem) {
  var seq = null;
  // createNewSequenceFromClips herda as settings do clipe (resolução/fps) — bem melhor
  // que a default SD. Ele adiciona o clipe; limpamos depois.
  try {
    if (firstItem && typeof app.project.createNewSequenceFromClips === "function") {
      app.project.createNewSequenceFromClips(name, [firstItem], app.project.rootItem);
      seq = app.project.activeSequence;
    }
  } catch (e) { seq = null; }
  if (!seq) {
    try { app.project.createNewSequence(name, ""); seq = app.project.activeSequence; }
    catch (e2) { return null; }
  }
  // Esvazia todas as tracks (o createFromClips deixou o 1º clipe posto).
  function clearTracks(tracks) {
    if (!tracks) return;
    for (var t = 0; t < tracks.numTracks; t++) {
      var clips = tracks[t].clips;
      for (var c = clips.numItems - 1; c >= 0; c--) {
        try { clips[c].remove(false, false); } catch (e) {}
      }
    }
  }
  clearTracks(seq.videoTracks);
  clearTracks(seq.audioTracks);
  return seq;
}

/** Garante ao menos `needV`/`needA` tracks de vídeo/áudio (adiciona via QE se faltar). */
function sincEnsureTracks(seq, needV, needA) {
  var haveV = seq.videoTracks.numTracks;
  var haveA = seq.audioTracks.numTracks;
  var addV = needV > haveV ? needV - haveV : 0;
  var addA = needA > haveA ? needA - haveA : 0;
  if (addV === 0 && addA === 0) return "";
  try {
    app.enableQE();
    var qeSeq = qe.project.getActiveSequence();
    // Assinatura do QE varia entre versões; a tentativa comum: (numV, vAfter, numA, aAfter).
    qeSeq.addTracks(addV, haveV, addA, haveA);
    return "";
  } catch (e) {
    return " (aviso: faltaram tracks e o QE.addTracks falhou: " + e + ")";
  }
}

/** Nomeia uma track (DOM `setName` quando existe; senão QE). Best-effort. */
function sincNameTrack(track, qeGetter, i, name) {
  if (!name) return;
  try { if (typeof track.setName === "function") { track.setName(name); return; } } catch (e) {}
  try {
    app.enableQE();
    var qt = qeGetter(i);
    if (qt && typeof qt.setName === "function") qt.setName(name);
  } catch (e2) {}
}

/**
 * Apaga as tracks VAZIAS ao final (o layout de áudio força tracks de vídeo vazias entre
 * as câmeras). Equivale ao "Delete Empty Tracks" do Premiere. Não há método no DOM
 * oficial; o QE DOM (não-documentado) expõe `removeEmptyVideoTracks()` /
 * `removeEmptyAudioTracks()` na sequência ativa. Deve rodar DEPOIS de nomear/posicionar
 * (as tracks nomeadas têm clipes, então sobrevivem). Devolve um CÓDIGO (string):
 * "1" apagou, "0" falhou, "-1" sem QE — o painel formata a mensagem localizada.
 */
function sincDeleteEmptyTracks(seq) {
  var qeSeq = null;
  try { app.enableQE(); qeSeq = qe.project.getActiveSequence(); } catch (e) {}
  if (!qeSeq) return "-1";
  var ok = false;
  try {
    if (typeof qeSeq.removeEmptyVideoTracks === "function") { qeSeq.removeEmptyVideoTracks(); ok = true; }
    if (typeof qeSeq.removeEmptyAudioTracks === "function") { qeSeq.removeEmptyAudioTracks(); ok = true; }
  } catch (e1) { ok = false; }
  return ok ? "1" : "0";
}

// ── Sync NA TIMELINE ATIVA + fechar gaps ─────────────────────────────────────────
// Aqui nada é reimportado nem recriado: os clipes que JÁ estão na sequência mudam de
// lugar. Três regras do Premiere governam este bloco:
//   • `clip.start = t` APARA o clipe (mexe no ponto de entrada); mover é `TrackItem.move(Time)`.
//   • mover um clipe com áudio VINCULADO arrasta o par junto — por isso todo alvo aqui é
//     ABSOLUTO e o delta é relido na hora: se o par já veio junto, o delta dá ~0 e ele fica.
//   • não há API de "close gap"; ela é reconstruída a partir do mesmo primitivo de mover.

var SINC_EPS = 0.0005;   // ruído de ponto flutuante em segundos
var SINC_MIN_GAP = 0.005; // buraco menor que isto não é buraco

/** ES3 não tem Array.indexOf. */
function sincHas(arr, v) {
  for (var i = 0; i < arr.length; i++) if (arr[i] === v) return true;
  return false;
}

/** Segundos de um objeto Time, tolerante a versão. */
function sincSecs(time) {
  try { return Number(time.seconds); } catch (e) { return 0; }
}

/** Percorre TODOS os trackItems da sequência: fn(tipo "V"|"A", track, índice, clip). */
function sincEachTrackItem(seq, fn) {
  var groups = [["V", seq.videoTracks], ["A", seq.audioTracks]];
  for (var g = 0; g < groups.length; g++) {
    var kind = groups[g][0], tracks = groups[g][1];
    if (!tracks) continue;
    for (var t = 0; t < tracks.numTracks; t++) {
      var clips = null;
      try { clips = tracks[t].clips; } catch (e) { clips = null; }
      var n = clips ? clips.numItems : 0;
      for (var c = 0; c < n; c++) {
        var clip = null;
        try { clip = clips[c]; } catch (e2) { clip = null; }
        if (clip) fn(kind, t, c, clip);
      }
    }
  }
}

function sincClipPath(clip) {
  try { return clip.projectItem ? clip.projectItem.getMediaPath() : ""; } catch (e) { return ""; }
}

function sincIsSelected(clip) {
  try { return !!clip.isSelected(); } catch (e) { return false; }
}

/**
 * Fotografia da sequência ativa: TODOS os clipes, um por linha, com a marca de quem
 * está selecionado — `tipo\ttrack\tíndice\tstart\tinPoint\tduração\tsel\tpath`
 * (segundos; path por último, que é o único campo que poderia conter separador).
 *
 * Vem tudo, não só a seleção, porque para NÃO SOBRESCREVER é preciso saber o que já
 * ocupa cada track. O índice serve para reencontrar o clipe na hora de mover — e o
 * path é reconferido lá, caso a timeline mude no meio do caminho.
 */
function sincGetTimelineSelection(seqDada) {
  try {
    var seq = seqDada || (app.project ? app.project.activeSequence : null);
    if (!seq) return "err|nosequence"; // código: o painel localiza a mensagem
    var out = [];
    sincEachTrackItem(seq, function (kind, t, c, clip) {
      var path = sincClipPath(clip);
      if (!path) return;
      out.push(kind + "\t" + t + "\t" + c + "\t" + sincSecs(clip.start) + "\t" +
               sincSecs(clip.inPoint) + "\t" + sincSecs(clip.duration) + "\t" +
               (sincIsSelected(clip) ? "1" : "0") + "\t" + path);
    });
    return out.join("\n");
  } catch (e) {
    return "err|" + e.toString();
  }
}

/**
 * A sequência ativa para a aba de merged: `fps\t<n>` e `nome\t<nome>` no topo, e
 * depois as linhas de `sincGetTimelineSelection` (o leitor do sidecar ignora o que
 * não começa com V/A). O fps sai do `timebase` (ticks por frame).
 */
function sincGetSequenceForMerged(nodeId) {
  var seq = nodeId ? sincSequenciaPorNode(nodeId)
                   : (app.project ? app.project.activeSequence : null);
  if (!seq) return "err|nosequence";
  var tb = 0;
  try { tb = Number(seq.timebase); } catch (e) { tb = 0; }
  var fps = tb > 0 ? 254016000000 / tb : 0;
  var corpo = sincGetTimelineSelection(seq);
  if (corpo.indexOf("err|") === 0) return corpo;
  return "fps\t" + String(fps) + "\nnome\t" + sincCleanName(seq) + "\n" + corpo;
}

/** A sequência cujo item de bin tem este nodeId (merged clips também estão na lista). */
function sincSequenciaPorNode(nodeId) {
  var seqs = app.project ? app.project.sequences : null;
  for (var i = 0; seqs && i < seqs.numSequences; i++) {
    try {
      if (String(seqs[i].projectItem.nodeId) === String(nodeId)) return seqs[i];
    } catch (e) { /* segue */ }
  }
  return null;
}

/**
 * ARRASTO DA BIN (2026-09-17): o painel não recebe dado nenhum de um arrasto do Premiere
 * (medido nos dois SOs) — mas no Premiere todo arrasto É a seleção (o clique que começa
 * o arrasto seleciona o item; visto pelo autor). Então, no drop, a seleção diz o que veio.
 * Devolve o nodeId da ÚNICA sequência selecionada (merged clip não conta), ou `err|…`.
 */
function sincSelectedSequenceNode() {
  var sel = sincSelection(), achadas = [];
  for (var i = 0; i < sel.length; i++) {
    var it = sel[i], eSeq = false, eMerged = false;
    try { eSeq = !!(it.isSequence && it.isSequence()); } catch (e) { eSeq = false; }
    try { eMerged = !!(it.isMergedClip && it.isMergedClip()); } catch (e2) { eMerged = false; }
    if (eSeq && !eMerged) achadas.push(String(it.nodeId));
  }
  if (!achadas.length) return "err|notsequence";
  if (achadas.length > 1) return "err|manysequences";
  return achadas[0];
}

/** A versão do Premiere ("23.2.0"), para o painel escolher o formato do .prproj. */
function sincAppVersion() {
  try { return String(app.version || ""); } catch (e) { return ""; }
}

/** Todos os itens do projeto, por nodeId (bins inclusive). */
function sincFotoDoProjeto() {
  var vistos = {};
  function andar(it) {
    if (!it) return;
    var id = "";
    try { id = String(it.nodeId); } catch (e) { id = ""; }
    if (id) vistos[id] = it;
    var filhos = null;
    try { filhos = it.children; } catch (e2) { filhos = null; }
    if (filhos) for (var i = 0; i < filhos.numItems; i++) andar(filhos[i]);
  }
  andar(app.project.rootItem);
  return vistos;
}

/** Aplica in/out (segundos) num item da bin, tentando as formas que a API aceita. */
function sincAparar(item, entrada, saida) {
  var formas = [
    ["time", function (s) { var t = new Time(); t.seconds = s; return t; }],
    ["seconds", function (s) { return s; }],
    ["ticks", function (s) { return String(Math.round(s * 254016000000)); }]
  ];
  for (var f = 0; f < formas.length; f++) {
    try {
      item.setInPoint(formas[f][1](entrada), 4);   // 4 = vídeo e áudio
      item.setOutPoint(formas[f][1](saida), 4);
      var lido = Number(item.getOutPoint().seconds);
      if (Math.abs(lido - saida) < 0.5) return formas[f][0];
    } catch (e) { /* próxima forma */ }
  }
  return "";
}

/**
 * Importa o .prproj só-merged, RENOMEIA e apara cada merged novo. `aparos`: uma linha
 * por merged, `chega_como\tnome\tin\tout` (segundos). Devolve `chave\tvalor` por linha.
 *
 * ⚠️ O Premiere ignora o nome da linha da bin ao importar: o merged chega como
 * `<arquivo> - Merged` (medido no 23.2). Por isso ele é achado por ESSE nome e renomeado
 * depois — `item.name = x` funciona e preserva o nodeId (sonda §6). Dois merged da mesma
 * câmera chegam com o mesmo nome: a fila por nome os distribui na ordem.
 *
 * ⚠️ O Premiere DEDUPLICA a importação de projeto por conteúdo (observado no 23.2): um
 * merged que já existe no projeto não volta — `novos 0` não é necessariamente falha.
 */
function sincImportMerged(caminho, aparos) {
  if (!app.project) return "erro\tnenhum projeto aberto";
  var porNome = {};
  var linhas = String(aparos || "").split("\n");
  for (var i = 0; i < linhas.length; i++) {
    var c = linhas[i].split("\t");
    if (c.length < 4) continue;
    if (!porNome[c[0]]) porNome[c[0]] = [];
    porNome[c[0]].push([c[1], Number(c[2]), Number(c[3])]);
  }
  var antes = sincFotoDoProjeto();
  var ok;
  try {
    ok = app.project.importFiles([caminho], true, app.project.rootItem, false);
  } catch (e) {
    return "erro\t" + String(e);
  }
  var depois = sincFotoDoProjeto();
  var novos = 0, merged = 0, aparados = 0, renomeados = 0, forma = "";
  var semAparo = [], falhas = [], bins = [];
  for (var k in depois) {
    if (antes[k]) continue;
    novos++;
    var it = depois[k];
    var tipo = 0;
    try { tipo = Number(it.type); } catch (e3) { tipo = 0; }
    if (tipo === SINC_TYPE_BIN) { bins.push(sincCleanName(it)); continue; }
    var eMerged = false;
    try { eMerged = !!it.isMergedClip(); } catch (e4) { eMerged = false; }
    if (!eMerged) continue;
    merged++;
    var fila = porNome[String(it.name)];
    if (!fila || !fila.length) { semAparo.push(sincCleanName(it)); continue; }
    var a = fila.shift();
    if (a[0] && a[0] !== String(it.name)) {
      try { it.name = a[0]; renomeados++; } catch (e5) { falhas.push(sincCleanName(it)); }
    }
    var f = sincAparar(it, a[1], a[2]);
    if (f) { aparados++; forma = f; } else { falhas.push(sincCleanName(it)); }
  }
  return ["importFiles\t" + String(ok), "novos\t" + novos, "merged\t" + merged,
          "aparados\t" + aparados, "renomeados\t" + renomeados, "forma\t" + forma, "bins\t" + bins.join("|"),
          "semAparo\t" + semAparo.join("|"), "falhas\t" + falhas.join("|")].join("\n");
}

/** Acha a bin pelo nome em qualquer nível; sem ela, cria na raiz. */
function sincBinPorNome(nome) {
  var achada = null;
  function andar(item) {
    var kids = item.children, n = kids ? kids.numItems : 0;
    for (var i = 0; i < n && !achada; i++) {
      var tipo = 0;
      try { tipo = Number(kids[i].type); } catch (e) { tipo = 0; }
      if (tipo !== SINC_TYPE_BIN) continue;
      if (String(kids[i].name) === nome) { achada = kids[i]; return; }
      andar(kids[i]);
    }
  }
  andar(app.project.rootItem);
  return achada || app.project.rootItem.createBin(nome);
}

/**
 * Os clipes da sequência sem som direto viram SUBCLIPE, na bin dos merged: não há com que fundir, e o material continua na
 * entrega, como o órfão do Avid. `linhas`: `caminho \t nome \t in \t out`, em segundos do arquivo.
 * ⚠️ `createSubClip` nasce na RAIZ, daí o `moveBin` (banco, painel-servido-e-identidade.md). Refazer não duplica: quem já
 * está na bin com o mesmo nome fica como está.
 */
function sincCriarSoltos(nomeBin, linhas) {
  if (!app.project) return "erro\tnenhum projeto aberto";
  var idx = sincIndexProject(), bin = sincBinPorNome(String(nomeBin)), criados = 0, falhas = [];
  var existentes = {}, kids = bin.children;
  for (var k = 0; kids && k < kids.numItems; k++) existentes[String(kids[k].name)] = true;
  var ls = String(linhas || "").split("\n");
  for (var i = 0; i < ls.length; i++) {
    var c = ls[i].split("\t");
    if (c.length < 4 || existentes[c[1]]) continue;
    var item = idx[c[0]];
    if (!item) { falhas.push(c[1]); continue; }
    try {
      var entrada = String(Math.round(Number(c[2]) * 254016000000));
      var saida = String(Math.round(Number(c[3]) * 254016000000));
      var novo = item.createSubClip(c[1], entrada, saida, 0, 1, 1);
      if (!novo) { falhas.push(c[1]); continue; }
      novo.moveBin(bin);
      criados++;
    } catch (e) {
      falhas.push(c[1]);
    }
  }
  return "criados\t" + criados + "\nfalhas\t" + falhas.join("|");
}

/* ── Aba RENOMEAR ─────────────────────────────────────────────────────────────
 * Medido no 23.2 (sonda §6): `item.name = x` grava e o nodeId não muda; o nodeId é
 * o <ID> do Node gravado no .prproj, então sobrevive a fechar e reabrir o projeto.
 */

function sincProjectPath() {
  try { return app.project ? String(app.project.path || "") : ""; } catch (e) { return ""; }
}

function sincXmlTexto(s) {
  return String(s || "")
    .replace(/&#xD;|&#xA;|&#13;|&#10;/gi, "|")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
    .replace(/&apos;/g, "'").replace(/&amp;/g, "&");
}

function sincXmpCampo(xmp, tag) {
  var m = new RegExp("<" + tag + ">([\\s\\S]*?)</" + tag + ">").exec(xmp);
  return m ? sincXmlTexto(m[1]) : "";
}

/** Um campo numa linha de TAB: sem TAB e sem quebra dentro. */
function sincCampo(s) {
  return String(s == null ? "" : s).replace(/[\t\r\n]+/g, " ");
}

/**
 * Os itens selecionados na bin (pastas abertas por dentro), um por linha:
 * `nodeId\ttipo\tnome\tcolunasJSON\tscene\ttake\tbext`. A 1ª linha é `projeto\t<caminho>`.
 * O TAKE só existe no XMP do arquivo (bext `TAKE=`, `xmpDM:shotNumber`) — nenhuma coluna
 * do Premiere o traz (medido).
 */
function sincRenameScan() {
  if (!app.project) return "err|noproject";
  var out = ["projeto\t" + sincCampo(sincProjectPath())], vistos = {};
  function tipoDe(it) {
    try { if (it.isSequence && it.isSequence()) return "sequence"; } catch (e) { /* segue */ }
    try { if (it.isMergedClip && it.isMergedClip()) return "merged"; } catch (e2) { /* segue */ }
    try { if (it.isMulticamClip && it.isMulticamClip()) return "multicam"; } catch (e3) { /* segue */ }
    return "clip";
  }
  function andar(it) {
    if (!it) return;
    var tipo = 0;
    try { tipo = Number(it.type); } catch (e) { tipo = 0; }
    if (tipo === SINC_TYPE_BIN) {
      var filhos = it.children;
      if (filhos) for (var i = 0; i < filhos.numItems; i++) andar(filhos[i]);
      return;
    }
    var id = "";
    try { id = String(it.nodeId); } catch (e4) { id = ""; }
    if (!id || vistos[id]) return;
    vistos[id] = true;
    var colunas = "", xmp = "";
    try { colunas = String(it.getProjectColumnsMetadata() || ""); } catch (e5) { colunas = ""; }
    try { xmp = String(it.getXMPMetadata() || ""); } catch (e6) { xmp = ""; }
    var take = sincXmpCampo(xmp, "xmpDM:takeNumber") || sincXmpCampo(xmp, "xmpDM:shotNumber");
    out.push([sincCampo(id), tipoDe(it), sincCampo(it.name), sincCampo(colunas),
              sincCampo(sincXmpCampo(xmp, "xmpDM:scene")), sincCampo(take),
              sincCampo(sincXmpCampo(xmp, "bext:description"))].join("\t"));
  }
  var sel = sincSelection();
  for (var s = 0; s < sel.length; s++) andar(sel[s]);
  return out.join("\n");
}

/**
 * Aplica nomes: `nodeId\tnomeAtual\tnomeNovo` por linha. Um item só muda se o nome
 * de AGORA for o `nomeAtual` — se alguém renomeou por cima, ele não é tocado.
 * Devolve `ok|igual|diverge|ausente|falha \t nodeId [\t detalhe]` por linha.
 */
function sincRenameApply(plano) {
  if (!app.project) return "erro\tnenhum projeto aberto";
  var foto = sincFotoDoProjeto();
  var linhas = String(plano || "").split("\n"), out = [];
  for (var i = 0; i < linhas.length; i++) {
    var c = linhas[i].split("\t");
    if (c.length < 3 || !c[0]) continue;
    var it = foto[c[0]];
    if (!it) { out.push("ausente\t" + c[0]); continue; }
    var agora = String(it.name);
    if (agora === c[2]) { out.push("igual\t" + c[0]); continue; }
    if (agora !== c[1]) { out.push("diverge\t" + c[0] + "\t" + sincCampo(agora)); continue; }
    try {
      it.name = c[2];
      out.push(String(it.name) === c[2] ? "ok\t" + c[0] : "falha\t" + c[0] + "\tnão gravou");
    } catch (e) {
      out.push("falha\t" + c[0] + "\t" + sincCampo(e));
    }
  }
  return out.join("\n");
}

/** Quantos clipes estão selecionados na sequência ativa (feedback ao vivo). */
function sincCountTimelineSelection() {
  try {
    var seq = app.project ? app.project.activeSequence : null;
    if (!seq) return "-1"; // sem sequência aberta ≠ nada selecionado
    var n = 0;
    sincEachTrackItem(seq, function (kind, t, c, clip) {
      if (sincIsSelected(clip) && sincClipPath(clip)) n++;
    });
    return String(n);
  } catch (e) {
    return "-1";
  }
}

/**
 * Força o painel Timeline a se redesenhar.
 *
 * Depois de mudar clipes por script, o Premiere NÃO invalida o desenho do painel: os
 * clipes existem mas só aparecem quando o mouse passa por cima. No fluxo "pela bin"
 * isso não se nota porque o `removeEmptyVideoTracks` do QE, no fim, faz o painel
 * reconstruir tudo — aqui não há nada estrutural, então provocamos o redesenho.
 *
 * Duas provocações inofensivas, das mais brandas para as mais fortes; devolve quais
 * funcionaram (entra no diagnóstico, porque o que vale nesta versão só a GUI diz).
 */
function sincRefreshTimeline(seq) {
  var tried = [];

  // NÃO piscamos a seleção (setSelected em todos os clipes): testado na GUI, o Cmd+A
  // manual PIORA o sintoma — some até clipe que não estava na seleção. Selecionar não
  // invalida o desenho; o que invalida é a estrutura mudar ou o painel ser reconstruído.

  // 1) Cutucar o playhead: sai e volta para a mesma posição. O tick do Premiere é
  //    254016000000 por segundo; um segundo de ida e volta não muda nada para o usuário.
  try {
    var pos = seq.getPlayerPosition();
    var ticks = String(pos.ticks);
    var away = String(Number(ticks) + 254016000000);
    seq.setPlayerPosition(away);
    seq.setPlayerPosition(ticks);
    tried.push("playhead");
  } catch (e) {}

  // 2) Reatribuir a sequência ativa — faz o painel reconstruir o desenho a partir do
  //    modelo. NÃO alterno para outra sequência e volto (seria mais forte, mas abriria
  //    abas na Timeline do usuário — efeito colateral pior que o sintoma).
  try {
    app.project.activeSequence = seq;
    tried.push("reassign");
  } catch (e2) {}

  // 3) Travar e destravar cada track pelo QE. É ESTRUTURAL como o
  //    removeEmptyVideoTracks (que é por que o fluxo "pela bin" nunca teve o sintoma):
  //    a tarja de bloqueio cobre a track inteira, então o painel é obrigado a repintá-la.
  //    O `finally` garante que nenhuma track fique trancada se algo falhar no meio.
  try {
    app.enableQE();
    var qeSeq = qe.project.getActiveSequence();
    if (qeSeq) {
      // No QE, contagem tanto pode ser propriedade quanto método, e o setter de trava
      // muda de nome entre versões — nada aqui pode assumir uma forma só.
      var count = function (v) { return typeof v === "function" ? Number(v.call(qeSeq)) : Number(v); };
      var lock = function (qt, on) {
        if (typeof qt.setLock === "function") qt.setLock(on);
        else if (typeof qt.setLocked === "function") qt.setLocked(on);
        else return false;
        return true;
      };
      var getters = [[count(qeSeq.numVideoTracks), function (i) { return qeSeq.getVideoTrackAt(i); }],
                     [count(qeSeq.numAudioTracks), function (i) { return qeSeq.getAudioTrackAt(i); }]];
      var toggled = 0;
      for (var g = 0; g < getters.length; g++) {
        var n = getters[g][0], at = getters[g][1];
        for (var k = 0; k < n; k++) {
          var qt = at(k);
          if (!qt) continue;
          try { if (lock(qt, true)) toggled++; } finally { lock(qt, false); }
        }
      }
      if (toggled) tried.push("locktoggle");
    }
  } catch (e3) {}

  // 4) O martelo: FECHAR e reabrir a sequência. É o equivalente a fechar a aba da
  //    Timeline e abrir de novo — o painel é destruído e reconstruído, então não há
  //    desenho velho para sobrar. Custo: a aba perde zoom/rolagem. Fica por último
  //    justamente por isso, e só entra se as provocações mais brandas não existirem
  //    nesta versão (se `locktoggle` rodou, o painel já foi obrigado a repintar).
  if (tried.length === 0 || !sincHas(tried, "locktoggle")) {
    try {
      var id = seq.sequenceID;
      if (id && typeof seq.close === "function" && typeof app.project.openSequence === "function") {
        seq.close();
        app.project.openSequence(id);
        tried.push("reopen");
      }
    } catch (e4) {}
  }

  return tried.length ? tried.join("+") : "none";
}

/** O redesenho como AÇÃO do usuário (botão do painel), quando o automático não bastar. */
function sincRefreshActiveTimeline() {
  try {
    var seq = app.project ? app.project.activeSequence : null;
    if (!seq) return "err|nosequence";
    return "ok|refresh=" + sincRefreshTimeline(seq);
  } catch (e) {
    return "err|" + e.toString();
  }
}

/**
 * Move um clipe pelo DOM. `amount` é RELATIVO ou ABSOLUTO conforme a semântica desta
 * versão; `form` é COMO o número chega ao Premiere ("time" quando omitido).
 *
 * ⚠️ A FORMA importa, e a Adobe não documenta qual é a certa. O nosso primitivo sempre
 * passou um `Time`; o relato de campo mais comum passa um Number cru de segundos
 * (`clip.move(2)`). Numa versão em que a outra forma é a aceita, `move` NÃO LANÇA — ele
 * simplesmente não faz nada, que é o pior jeito de falhar, porque `true` aqui passaria a
 * significar "não deu erro" e não "o clipe andou". Por isso quem chama não escolhe a
 * forma no escuro: ela é DESCOBERTA por `sincDomMoveProbe`, do mesmo jeito que já se
 * fazia com o `move` do QE.
 */
function sincMoveClip(clip, amount, form) {
  if (typeof clip.move !== "function") return false;
  try {
    if (form === "num") clip.move(amount);
    else if (form === "str") clip.move(String(amount));
    else { var t = new Time(); t.seconds = amount; clip.move(t); }
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Devolve o clipe a `want` depois de uma tentativa que saiu errado. A semântica ainda é
 * desconhecida aqui (é justamente o que estava sendo descoberto), então tenta o delta e,
 * se não bastar, a posição final — medindo as duas.
 */
function sincRestoreClip(clip, want, form) {
  var cur = sincSecs(clip.start);
  if (Math.abs(cur - want) < SINC_EPS) return true;
  sincMoveClip(clip, want - cur, form);
  if (Math.abs(sincSecs(clip.start) - want) < SINC_EPS) return true;
  sincMoveClip(clip, want, form);
  return Math.abs(sincSecs(clip.start) - want) < SINC_EPS;
}

/**
 * Descobre COMO o `move` do DOM funciona nesta versão: a forma do argumento e a
 * semântica (delta ou posição final), de uma vez só. Move de verdade — é o primeiro
 * movimento da leva — e devolve "forma:semântica" (`"time:rel"`, `"num:abs"`, …), ou
 * null se NENHUMA forma tirar o clipe do lugar.
 *
 * Espelha o `sincQeMoveProbe`. A diferença é o modo de falhar: no QE a forma errada
 * costuma lançar, no DOM ela costuma ser ignorada em silêncio — então aqui o critério
 * não pode ser "não deu erro", tem de ser onde o clipe PAROU.
 */
function sincDomMoveProbe(clip, orig, target) {
  if (typeof clip.move !== "function") return null;
  var delta = target - orig;
  var durBefore = sincSecs(clip.duration);
  var forms = ["time", "num", "str"];

  /** A duração mudou ⇒ não foi movimento, foi APARO. */
  function aparou() {
    return Math.abs(sincSecs(clip.duration) - durBefore) > SINC_EPS;
  }

  for (var i = 0; i < forms.length; i++) {
    var before = sincSecs(clip.start);
    if (!sincMoveClip(clip, delta, forms[i])) continue;

    // Aparar não é "a forma não serve" — é dano. Não adianta tentar a próxima forma: quem
    // chama tem de parar a leva antes que o resto da timeline vá junto.
    if (aparou()) return "trim";

    var after = sincSecs(clip.start);
    if (Math.abs(after - target) < SINC_EPS) {
      // Chegou ao alvo — a FORMA está descoberta. A semântica, nem sempre: um clipe que
      // sai da posição ZERO tem delta IGUAL ao alvo, então as duas semânticas mandam o
      // mesmo número e produzem o mesmo resultado. Concluir dali é chutar e carregar o
      // chute pela leva inteira; melhor devolver "?" e medir no próximo clipe.
      return forms[i] + ":" + (Math.abs(orig) < SINC_EPS ? "?" : "rel");
    }
    if (Math.abs(after - delta) < SINC_EPS) {
      // Semântica absoluta: repete com o alvo e confere.
      sincMoveClip(clip, target, forms[i]);
      if (aparou()) return "trim";
      if (Math.abs(sincSecs(clip.start) - target) < SINC_EPS) return forms[i] + ":abs";
    }
    // Não saiu do lugar, ou parou num lugar que não explica nada: desfaz e tenta a próxima.
    sincRestoreClip(clip, before, forms[i]);
    if (aparou()) return "trim";
  }
  return null;
}

/**
 * Reencontra o clipe. Duas tentativas, nesta ordem:
 *
 *  1. pelo ÍNDICE (o caso comum, barato);
 *  2. varrendo a track por caminho + start esperado.
 *
 * A segunda existe porque a coleção `clips` de uma track é ORDENADA POR TEMPO: assim que
 * um clipe passa por outro, os índices seguintes escorregam. Como agora os movimentos são
 * ordenados de propósito para clipes cruzarem, confiar só no índice faria metade da leva
 * virar "stale" — o clipe está lá, só não está mais naquela gaveta.
 */
function sincResolveClip(seq, kind, track, index, path, expectStart) {
  var tracks = kind === "A" ? seq.audioTracks : seq.videoTracks;
  if (!tracks || track >= tracks.numTracks) return null;
  var clips = null;
  try { clips = tracks[track].clips; } catch (e) { return null; }
  if (!clips) return null;

  if (index < clips.numItems) {
    var clip = null;
    try { clip = clips[index]; } catch (e2) { clip = null; }
    if (clip && sincClipPath(clip) === path) return clip;
  }

  // Escorregou: procura na track o mesmo arquivo no start esperado. Sem o start (chamada
  // antiga), o primeiro do mesmo arquivo serve — é o que dava para fazer antes.
  var best = null;
  for (var i = 0; i < clips.numItems; i++) {
    var c = null;
    try { c = clips[i]; } catch (e3) { continue; }
    if (!c || sincClipPath(c) !== path) continue;
    if (expectStart === undefined || expectStart === null) return c;
    if (Math.abs(sincSecs(c.start) - expectStart) < SINC_EPS) return c;
    if (!best) best = c;
  }
  return null;
}

// ── O primitivo de deslocamento ──────────────────────────────────────────────────
// `TrackItem.move()` (DOM) funciona, mas NÃO é estrutural — e o painel Timeline do
// Premiere só invalida o próprio desenho quando a estrutura muda, o que é a raiz dos
// clipes que somem até o mouse passar. O QE é de onde vem o `removeEmptyVideoTracks`,
// a única operação que sabidamente força o painel a reconstruir; se o `move` dele passa
// pelo mesmo caminho, o sintoma morre sem provocação nenhuma. Como nada disso é
// documentado pela Adobe, o painel PERGUNTA à versão instalada em vez de supor.

/** O item de track do QE equivalente a (tipo, track, índice), ou null. */
function sincQeItem(kind, track, index) {
  try {
    app.enableQE();
    var qeSeq = qe.project.getActiveSequence();
    if (!qeSeq) return null;
    var qt = kind === "A" ? qeSeq.getAudioTrackAt(track) : qeSeq.getVideoTrackAt(track);
    if (!qt || typeof qt.getItemAt !== "function") return null;
    return qt.getItemAt(index) || null;
  } catch (e) {
    return null;
  }
}

/** Que comandos de deslocamento existem NESTA versão? Só leitura — nada se move. */
function sincProbeMoveApis() {
  var out = [];
  try {
    var seq = app.project ? app.project.activeSequence : null;
    if (!seq) return "err|nosequence";

    var domClip = null, kind = "V", track = 0, index = 0;
    sincEachTrackItem(seq, function (k, t, c, clip) {
      if (domClip) return;
      domClip = clip; kind = k; track = t; index = c;
    });
    out.push("dom.move=" + (domClip && typeof domClip.move === "function" ? "1" : "0"));
    out.push("dom.components=" + (domClip && domClip.components ? "1" : "0"));

    var hasQe = false;
    try { app.enableQE(); hasQe = !!(qe && qe.project && qe.project.getActiveSequence()); }
    catch (e) { hasQe = false; }
    out.push("qe=" + (hasQe ? "1" : "0"));

    if (hasQe && domClip) {
      var qi = sincQeItem(kind, track, index);
      out.push("qe.item=" + (qi ? "1" : "0"));
      if (qi) {
        var names = ["move", "remove", "setStart", "slip", "slide", "roll",
                     "addVideoEffect", "setSpeed"];
        for (var i = 0; i < names.length; i++) {
          out.push("qe." + names[i] + "=" + (typeof qi[names[i]] === "function" ? "1" : "0"));
        }
      }
    }
    return "ok|" + out.join(",");
  } catch (e2) {
    return "err|" + e2.toString();
  }
}

/**
 * Tenta mover pelo QE, medindo o resultado. Devolve a forma que funcionou ("num", "str",
 * "time", cada uma com sufixo de semântica) ou null — e, se algo saiu do lugar errado,
 * DESFAZ pelo `move` do DOM antes de desistir. Só é chamada no PRIMEIRO movimento da
 * leva: uma vez descoberta a forma, o resto usa ela.
 */
function sincQeMoveProbe(seq, kind, track, index, path, orig, target) {
  var qi = sincQeItem(kind, track, index);
  if (!qi || typeof qi.move !== "function") return null;

  var delta = target - orig;
  var forms = [
    ["num", function (v) { qi.move(v); }],
    ["str", function (v) { qi.move(String(v)); }],
    ["time", function (v) { var t = new Time(); t.seconds = v; qi.move(t); }],
  ];
  var here = function () {
    var c = sincResolveClip(seq, kind, track, index, path, null);
    return c ? sincSecs(c.start) : null;
  };

  for (var i = 0; i < forms.length; i++) {
    var before = here();
    if (before === null) return null;
    try { forms[i][1](delta); } catch (e) { continue; }
    var after = here();
    if (after === null) return null;
    if (Math.abs(after - target) < SINC_EPS) return forms[i][0] + ":rel";
    if (Math.abs(after - delta) < SINC_EPS) {
      // Semântica absoluta: repete com o alvo e confere.
      try { forms[i][1](target); } catch (e2) { /* volta abaixo */ }
      if (Math.abs(here() - target) < SINC_EPS) return forms[i][0] + ":abs";
    }
    // Não caiu onde devia: devolve o clipe ao lugar antes de tentar a próxima forma.
    var cur = here();
    if (cur !== null && Math.abs(cur - before) > SINC_EPS) {
      var back = sincResolveClip(seq, kind, track, index, path, null);
      if (back) sincMoveClip(back, before - cur);
    }
  }
  return null;
}

/** Move pelo QE usando a forma já descoberta. */
function sincMoveClipQE(kind, track, index, orig, target, via) {
  var qi = sincQeItem(kind, track, index);
  if (!qi || typeof qi.move !== "function") return false;
  var parts = via.split(":");
  var amount = parts[1] === "abs" ? target : target - orig;
  try {
    if (parts[0] === "num") qi.move(amount);
    else if (parts[0] === "str") qi.move(String(amount));
    else { var t = new Time(); t.seconds = amount; qi.move(t); }
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Move clipes para posições ABSOLUTAS.
 * `recordsStr`: `tipo\ttrack\tíndice\talvo\tstartAtual\tpath`, JÁ NA ORDEM em que devem
 * acontecer — o painel ordena de forma que nenhum clipe bloqueie outro.
 *
 * Nem a FORMA do argumento do `move()` nem a sua SEMÂNTICA (delta ou posição final)
 * estão documentadas, e as duas variam entre versões — então o primeiro movimento é
 * MEDIDO: aplica-se o deslocamento, lê-se onde o clipe parou e daí se concluem as duas
 * coisas; o resto da leva usa o que funcionou. Antes disso, tenta-se o `move` do QE (que
 * pode ser estrutural, e aí o painel se redesenha sozinho); se ele não existir ou não
 * acertar o alvo, a leva inteira vai pelo DOM. Se a DURAÇÃO mudar, o clipe foi aparado
 * em vez de movido: aborta na hora em vez de estragar o resto da timeline.
 *
 * Devolve "ok|moved=..|skipped=..|mismatch=..|failed=..|stale=..|trimmed=..|sem=..|via=..".
 */
function sincMoveTimelineClips(recordsStr) {
  try {
    var seq = app.project ? app.project.activeSequence : null;
    if (!seq) return "err|nosequence"; // código: o painel localiza a mensagem
    var lines = (recordsStr || "").split("\n");
    var moved = 0, skipped = 0, mismatch = 0, failed = 0, stale = 0, trimmed = 0;
    var sem = "";      // "rel" | "abs" — descoberta no primeiro movimento
    var probe = "";
    var via = "";      // forma do QE que funcionou, ou "dom:<forma>"
    var domForm = "";  // forma do argumento do `move` do DOM, quando a leva vai por ele

    // Só provoca o redesenho se algo de fato mudou de lugar.
    function summary() {
      return "ok|moved=" + moved + "|skipped=" + skipped + "|mismatch=" + mismatch +
             "|failed=" + failed + "|stale=" + stale + "|trimmed=" + trimmed +
             "|sem=" + (sem || "none") + "|via=" + (via || "none") +
             "|refresh=" + (moved > 0 ? sincRefreshTimeline(seq) : "skip") +
             "|probe=" + probe;
    }

    for (var i = 0; i < lines.length; i++) {
      if (!lines[i]) continue;
      var f = lines[i].split("\t");
      if (f.length < 6) continue;
      var kind = f[0], track = parseInt(f[1], 10), index = parseInt(f[2], 10);
      var target = parseFloat(f[3]), expect = parseFloat(f[4]), path = f.slice(5).join("\t");

      var clip = sincResolveClip(seq, kind, track, index, path, expect);
      if (!clip) { stale++; continue; }

      var cur = sincSecs(clip.start);
      var delta = target - cur;
      if (Math.abs(delta) < SINC_EPS) { skipped++; continue; } // já está no lugar
      var durBefore = sincSecs(clip.duration);

      // Primeiro movimento da leva: o QE tem preferência (pode ser estrutural, e aí o
      // painel se redesenha sozinho). Se não acertar o alvo, ele mesmo desfaz e a leva
      // inteira segue pelo DOM.
      if (!via) {
        var qeForm = sincQeMoveProbe(seq, kind, track, index, path, cur, target);
        if (qeForm) {
          via = qeForm;
          sem = qeForm.split(":")[1];
          probe = "qe " + qeForm;
          clip = sincResolveClip(seq, kind, track, index, path, target);
          if (!clip) { stale++; continue; }
          if (Math.abs(sincSecs(clip.duration) - durBefore) > SINC_EPS) {
            trimmed++;
            return summary();
          }
          moved++;
          continue;
        }
        via = "dom";
      }

      // Primeiro movimento pelo DOM: descobre FORMA e semântica de uma vez. Antes daqui a
      // forma era suposta (`Time`) e só a semântica era medida — numa versão que aceitasse
      // apenas Number, todo `move` seria ignorado em silêncio e a leva inteira voltaria
      // como `mismatch`, sem nunca dizer que o problema era o TIPO do argumento.
      if (via === "dom" && !domForm) {
        var domFound = sincDomMoveProbe(clip, cur, target);
        if (domFound === "trim") {
          trimmed++;
          return summary(); // aparou: para aqui, antes de estragar o resto
        }
        if (!domFound) {
          failed++;
          probe = "dom: nenhuma forma de move tirou o clipe do lugar";
          sem = "none";
          continue; // o próximo clipe ainda ganha a sua chance (a track deste pode estar travada)
        }
        domForm = domFound.split(":")[0];
        var domSem = domFound.split(":")[1];
        if (domSem !== "?") sem = domSem; // "?" = o clipe saiu do zero e não distinguiu nada
        via = "dom:" + domForm;
        probe = "dom " + domFound;
        moved++; // a sonda já conferiu que parou no alvo, e que a duração não mudou
        continue;
      }

      var ok = domForm
        ? sincMoveClip(clip, sem === "abs" ? target : delta, domForm)
        : sincMoveClipQE(kind, track, index, cur, target, via);
      if (!ok) { failed++; if (!sem) { probe = "move indisponível"; sem = "none"; } continue; }

      var after = sincSecs(clip.start);
      if (!sem) {
        // A sonda descobriu a forma mas não a semântica (o primeiro clipe saía do zero).
        // Aqui há um delta diferente do alvo, então dá para concluir.
        if (Math.abs(after - target) < SINC_EPS) {
          sem = "rel";
        } else if (Math.abs(after - delta) < SINC_EPS) {
          sem = "abs";
          sincMoveClip(clip, target, domForm); // corrige este
          after = sincSecs(clip.start);
        }
        probe += " · alvo=" + target + " parou=" + after;
      }

      if (Math.abs(sincSecs(clip.duration) - durBefore) > SINC_EPS) {
        trimmed++;
        return summary(); // aparou: para aqui, antes de estragar o resto
      }
      if (Math.abs(after - target) < SINC_EPS) moved++; else mismatch++;
    }

    return summary();
  } catch (e) {
    return "err|" + e.toString();
  }
}

/**
 * ⚠️ SEM BOTÃO NO PAINEL hoje: o Premiere já tem "Close Gap" nativo, e o usuário prefere
 * acionar o dele. Mantido porque o PRINCÍPIO aqui — achar os buracos GLOBAIS em vez de
 * compactar track a track — é o que uma futura "timeline sincronizada sem buracos" vai
 * precisar, e ele está coberto por testes.
 *
 * Fecha os buracos da sequência ATIVA, como o "Close Gap" do Premiere: procura os
 * intervalos em que NENHUMA track tem clipe e puxa para a esquerda tudo o que vem
 * depois, de uma vez — é isso que preserva a sincronia (compactar track a track a
 * destruiria). O espaço ANTES do primeiro clipe fica como está.
 *
 * Devolve "ok|gaps=..|moved=..|skipped=..|mismatch=..|failed=..|sem=..".
 */
function sincCloseGaps() {
  try {
    var seq = app.project ? app.project.activeSequence : null;
    if (!seq) return "err|nosequence"; // código: o painel localiza a mensagem

    // 1) Fotografia de tudo que ocupa tempo na sequência.
    var items = [];
    sincEachTrackItem(seq, function (kind, t, c, clip) {
      items.push({ kind: kind, track: t, index: c, path: sincClipPath(clip),
                   start: sincSecs(clip.start), end: sincSecs(clip.end) });
    });
    if (items.length < 2) return "ok|gaps=0|moved=0|skipped=0|mismatch=0|failed=0|sem=none";

    // 2) Blocos OCUPADOS: os intervalos, ordenados e fundidos quando se tocam.
    var byStart = items.slice().sort(function (a, b) { return a.start - b.start; });
    var blocks = [];
    for (var i = 0; i < byStart.length; i++) {
      var it = byStart[i];
      var last = blocks.length ? blocks[blocks.length - 1] : null;
      if (!last || it.start > last.e + SINC_MIN_GAP) blocks.push({ s: it.start, e: it.end });
      else if (it.end > last.e) last.e = it.end;
    }
    if (blocks.length < 2) return "ok|gaps=0|moved=0|skipped=0|mismatch=0|failed=0|sem=none";

    // 3) Deslocamento acumulado: um clipe que começa depois do k-ésimo buraco anda a
    //    soma de todos os buracos anteriores a ele.
    var gaps = [];
    var acc = 0;
    for (var b = 1; b < blocks.length; b++) {
      acc += blocks[b].s - blocks[b - 1].e;
      gaps.push({ from: blocks[b].s, shift: acc });
    }
    function shiftAt(start) {
      var s = 0;
      for (var g = 0; g < gaps.length; g++) if (start >= gaps[g].from - SINC_EPS) s = gaps[g].shift;
      return s;
    }

    // 4) Aplica da esquerda para a direita (o espaço à frente já foi liberado). O alvo
    //    vem da FOTOGRAFIA, mas o delta é relido — o áudio vinculado que já veio junto
    //    com o vídeo cai no caso "já está no lugar".
    var records = [];
    for (var k = 0; k < byStart.length; k++) {
      var itk = byStart[k];
      var shift = shiftAt(itk.start);
      if (shift < SINC_MIN_GAP || !itk.path) continue;
      records.push(itk.kind + "\t" + itk.track + "\t" + itk.index + "\t" +
                   (itk.start - shift) + "\t" + itk.start + "\t" + itk.path);
    }
    if (!records.length) return "ok|gaps=" + gaps.length + "|moved=0|skipped=0|mismatch=0|failed=0|sem=none";

    var res = sincMoveTimelineClips(records.join("\n"));
    if (res.indexOf("err|") === 0) return res;
    return "ok|gaps=" + gaps.length + "|" + res.slice(3);
  } catch (e) {
    return "err|" + e.toString();
  }
}

/**
 * Monta a sequência nativa a partir do mapa. `recordsStr`: um registro por linha,
 * campos por TAB — `tipo\tpath\tstartSeg\ttrack` (tipo = "V" ou "A"). `numV`/`numA`:
 * quantas tracks o packing usou. `vNames`/`aNames`: nomes das tracks (por TAB, um por
 * track) — CAM A / CAM B / SOM DIRETO. Devolve um resumo ESTRUTURADO que o painel
 * localiza: "ok|placed=..|audio=..|missing=..|failed=..|warn=0|1|cleaned=-1|0|1" ou,
 * em falha, "err|<mensagem>".
 */
/** O formato escolhido na aba Sincronizar: tamanho do quadro e taxa, em TICKS exatos do Premiere (254016000000 por segundo). */
var SINC_TICKS_POR_QUADRO = { "23.976": 10594584000, "24": 10584000000, "25": 10160640000, "29.97": 8475667200,
                              "30": 8467200000, "50": 5080320000, "59.94": 4237833600, "60": 4233600000 };

function sincAplicarFormato(seq, largura, altura, taxa) {
  var s = seq.getSettings();
  if (!s) return "não consegui ler as configurações da sequência";
  s.videoFrameWidth = Number(largura);
  s.videoFrameHeight = Number(altura);
  if (taxa && SINC_TICKS_POR_QUADRO[taxa]) {
    var quadro = new Time();
    quadro.ticks = String(SINC_TICKS_POR_QUADRO[taxa]);
    s.videoFrameRate = quadro;
  }
  seq.setSettings(s);
  var lido = seq.getSettings();
  if (!lido || Number(lido.videoFrameWidth) !== Number(largura) || Number(lido.videoFrameHeight) !== Number(altura)) {
    return "o Premiere não aceitou o tamanho " + largura + "x" + altura;
  }
  return "";
}

function sincBuildSequence(recordsStr, seqName, numV, numA, vNames, aNames, largura, altura, taxa) {
  try {
    if (!app.project) return "err|nenhum projeto aberto";
    var lines = (recordsStr || "").split("\n");
    var video = [], audio = [];
    for (var i = 0; i < lines.length; i++) {
      if (!lines[i]) continue;
      var f = lines[i].split("\t");
      if (f.length < 4) continue;
      var rec = { path: f[1], start: parseFloat(f[2]), track: parseInt(f[3], 10) };
      if (f[0] === "A") audio.push(rec); else video.push(rec);
    }
    if (video.length === 0 && audio.length === 0) return "err|mapa vazio";

    var idx = sincIndexProject();
    var firstItem = video.length ? idx[video[0].path] : (audio.length ? idx[audio[0].path] : null);
    if (!firstItem) return "err|nenhum ProjectItem casou com o mapa (a mídia está no projeto?)";

    var seq = sincNewEmptySequence(seqName || "SINCRONIZAR", firstItem);
    if (!seq) return "err|não consegui criar a sequência";
    // ⛔ Formato pedido e não aplicado é erro, não aviso: a sequência sairia no formato errado sem ninguém ver.
    if (largura && altura) {
      var semFormato = sincAplicarFormato(seq, largura, altura, taxa);
      if (semFormato) return "err|" + semFormato;
    }
    var warn = sincEnsureTracks(seq, numV || 1, numA || 1);

    // Nomeia as tracks pela câmera/som (CAM A / CAM B / SOM DIRETO).
    var vn = (vNames || "").split("\t");
    var an = (aNames || "").split("\t");
    var qeSeq = null; try { app.enableQE(); qeSeq = qe.project.getActiveSequence(); } catch (e) {}
    for (var vi = 0; vi < vn.length && vi < seq.videoTracks.numTracks; vi++) {
      sincNameTrack(seq.videoTracks[vi],
        function (k) { return qeSeq ? qeSeq.getVideoTrackAt(k) : null; }, vi, vn[vi]);
    }
    for (var ai = 0; ai < an.length && ai < seq.audioTracks.numTracks; ai++) {
      sincNameTrack(seq.audioTracks[ai],
        function (k) { return qeSeq ? qeSeq.getAudioTrackAt(k) : null; }, ai, an[ai]);
    }

    var placed = 0, missing = 0, failed = 0, audioPlaced = 0;
    // 1) SOM DIRETO — áudio puro (WAV), vai só para a track de áudio (sem vídeo).
    for (var a = 0; a < audio.length; a++) {
      var ra = audio[a], ia = idx[ra.path];
      if (!ia) { missing++; continue; }
      if (ra.track >= seq.audioTracks.numTracks) { failed++; continue; }
      try { seq.audioTracks[ra.track].overwriteClip(ia, ra.start); audioPlaced++; }
      catch (e) { failed++; }
    }
    // 2) VÍDEO das câmeras — UMA colocação por clipe, na track de vídeo = bloco de áudio
    //    da câmera. Pela regra do Premiere, o áudio embutido cai no MESMO índice → o
    //    vídeo e o áudio da câmera ficam alinhados no bloco, sem duplicar.
    for (var v = 0; v < video.length; v++) {
      var rv = video[v], iv = idx[rv.path];
      if (!iv) { missing++; continue; }
      if (rv.track >= seq.videoTracks.numTracks) { failed++; continue; }
      try { seq.videoTracks[rv.track].overwriteClip(iv, rv.start); placed++; }
      catch (e) { failed++; }
    }

    // ⭐ Formato pedido: o Premiere põe o clipe em tamanho real (HD numa timeline UHD ocupa um quarto). "Scale to Frame
    //    Size" encaixa sem cortar; só existe no QE, e pede a sequência ativa (banco, api-extendscript.md, 25.6 a 26.5).
    var escala = 0;
    if (largura && altura && qeSeq) {
      for (var tv = 0; tv < seq.videoTracks.numTracks; tv++) {
        var qt = null;
        try { qt = qeSeq.getVideoTrackAt(tv); } catch (eq) { qt = null; }
        if (!qt) continue;
        for (var ci = 0; ci < qt.numItems; ci++) {
          try {
            var qi = qt.getItemAt(ci);
            if (qi && String(qi.type) !== "Empty") { qi.setScaleToFrameSize(true); escala++; }
          } catch (eq2) { /* um item vazio não tem o método: a conta do fim diz se faltou algum */ }
        }
      }
    }

    // Passo final: apaga as tracks vazias (posições finais corretas para entregar).
    var cleaned = sincDeleteEmptyTracks(seq); // "1"/"0"/"-1"
    // Se o QE não rodou, nada mexeu na ESTRUTURA e o painel pode ficar com o desenho
    // velho (o mesmo sintoma do modo timeline) — provoca o redesenho por garantia.
    if (cleaned !== "1") sincRefreshTimeline(seq);

    return "ok|placed=" + placed + "|audio=" + audioPlaced +
      "|missing=" + missing + "|failed=" + failed +
      "|warn=" + (warn ? 1 : 0) + "|cleaned=" + cleaned + "|escala=" + escala;
  } catch (e) {
    return "err|" + e.toString();
  }
}

/* ── A PONTE do Órbita Painel (2026-10-21) ─────────────────────────────────────
 * Este arquivo também é avaliado pela ponte invisível (`plugins/premiere-ponte`).
 * O painel na janela do app pergunta o estado a cada batida: versão e projeto.
 * Devolve TEXTO no formato `versao	caminho do projeto` (sem JSON garantido em ES3).
 */
function sincEstado() {
  return sincAppVersion() + "	" + sincProjectPath();
}

/* ── BANCADA: preparar um projeto de teste pela ponte (2026-10-21) ──────────────
 * O piloto cria o projeto da demo sem o diálogo de arquivo (digitar caminho com o
 * teclado ABNT2 já falhou; banco, skill piloto). Banco: `app.newProject` NÃO cria a
 * pasta (devolve false) — quem chama a cria antes. Já aberto = não faz nada.
 * Devolve o caminho do projeto aberto depois (vazio = falhou).
 */
function sincNovoProjeto(caminho) {
  try {
    if (app.project && String(app.project.path || "") === caminho) return caminho;
    var r = app.newProject(caminho);
    var p = app.project ? String(app.project.path || "") : "";
    return p || ("err|newProject=" + r);
  } catch (e) { return "err|" + e; }
}

/* BANCADA: o projeto aberto passa a morar em `caminho` (a pasta precisa existir).
 * Medido 2026-10-21 (23.6, Windows): `app.newProject` lança "Unknown error exception"
 * em qualquer caminho; o piloto cria pela tela (só o nome) e isto o leva ao lugar. */
function sincSalvarComo(caminho) {
  try {
    if (!app.project) return "err|sem projeto";
    app.project.saveAs(caminho);
    return String(app.project.path || "");
  } catch (e) { return "err|" + e; }
}

/* BANCADA: o que a sequência ATIVA tem, trilha a trilha — para conferir uma montagem sem
 * ler a timeline pela tela. Uma linha por clipe: `V|A <trilha>\t<nome>\t<início s>\t<fim s>`. */
function sincResumoDaSequencia() {
  try {
    var seq = app.project ? app.project.activeSequence : null;
    if (!seq) return "err|sem sequência ativa";
    var out = ["SEQ\t" + seq.name];
    function trilhas(lista, letra) {
      for (var i = 0; i < lista.numTracks; i++) {
        var tr = lista[i];
        for (var k = 0; k < tr.clips.numItems; k++) {
          var c = tr.clips[k];
          out.push(letra + (i + 1) + "\t" + c.name + "\t" + c.start.seconds.toFixed(3) + "\t" + c.end.seconds.toFixed(3));
        }
      }
    }
    trilhas(seq.videoTracks, "V");
    trilhas(seq.audioTracks, "A");
    return out.join("\n");
  } catch (e) { return "err|" + e; }
}

/**
 * A seleção da bin COM A BIN de cada clipe: uma linha `<bin>\t<caminho>` por mídia (2026-10-21).
 *
 * ⭐ A PASTA é a informação mais confiável que o editor dá sobre "o que é uma câmera". Só pelo esqueleto do nome
 * (`/sources`), câmeras de nomes no mesmo padrão viram UMA fonte: o caso M01 do laboratório (CAM 1…CAM 4, arquivos
 * `M01_CAM1_T01…`, `M01_CAM2_T01…`) chegou como "CAM A · 8 clipes". O painel agrupa por esta bin primeiro.
 * Clipe selecionado solto (fora de bin selecionada) vem com a bin vazia.
 */
function sincGetSelectionPorBin() {
  if (!app.project) return "";
  var out = [], seen = {};
  function walk(item, bin) {
    if (!item) return;
    if (item.type === SINC_TYPE_BIN) {
      var kids = item.children, nome = sincCleanName(item);
      if (kids) for (var i = 0; i < kids.numItems; i++) walk(kids[i], nome);
    } else {
      var path = sincMediaPath(item);
      if (path && !seen[path]) { seen[path] = true; out.push(bin + "\t" + path); }
    }
  }
  var sel = sincSelection();
  for (var i = 0; i < sel.length; i++) walk(sel[i], "");
  return out.join("\n");
}

/* BANCADA: seleciona no painel Project a bin da RAIZ com este nome (o piloto não clica numa lista que rola). */
function sincSelecionarBin(nome) {
  try {
    var raiz = app.project.rootItem;
    for (var i = 0; i < raiz.children.numItems; i++) {
      var it = raiz.children[i];
      if (it.type === SINC_TYPE_BIN && it.name === nome) {
        if (typeof it.select !== "function") return "err|select() não existe nesta versão";
        it.select();
        return "ok";
      }
    }
    return "err|bin não achada: " + nome;
  } catch (e) { return "err|" + e; }
}

/**
 * Marcadores de REVISÃO na sequência ativa (2026-10-21): uma linha `<segundos>\t<nome>\t<comentário>` por marcador.
 * Usado para os clipes que o motor marcou `overlap_cut` — a tomada seguinte da mesma câmera ficou no TC dela, por
 * cima do fim deste (câmera lenta invade o TC do próximo). Devolve `ok|marcadores=N`.
 */
function sincMarcadores(linhas) {
  try {
    var seq = app.project ? app.project.activeSequence : null;
    if (!seq) return "err|sem sequência ativa";
    var n = 0, ls = String(linhas || "").split("\n");
    for (var i = 0; i < ls.length; i++) {
      var p = ls[i].split("\t");
      if (p.length < 2) continue;
      var m = seq.markers.createMarker(parseFloat(p[0]));
      m.name = p[1];
      if (p[2]) m.comments = p[2];
      try { if (typeof m.setColorByIndex === "function") m.setColorByIndex(3); } catch (e) { /* cor é enfeite */ }
      n++;
    }
    return "ok|marcadores=" + n;
  } catch (e) { return "err|" + e; }
}
