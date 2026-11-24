/*
 * premiere_host.jsx — o que o De Lá Pra Cá pede ao Premiere. A conexão preliminar (2026-10-19): ler o estado.
 *
 * Não mora na extensão: a ponte servida o busca em /premiere/host.jsx e o avalia com evalScript.
 * Toda função devolve TEXTO JSON (o evalScript só transporta texto) e, em falha, {"erro": "..."}:
 * nunca lança (exceção vira "EvalScript error." sem dizer qual).
 *
 * ES3: sem JSON garantido, sem let, sem arrow, sem Array.forEach. O serviço só chama funções daqui pelo
 * nome, com argumentos que viram literais JSON (`premiere_ponte.expressao`).
 */

function dlpcJ(v) {
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
    for (var k = 0; k < v.length; k++) a.push(dlpcJ(v[k]));
    return "[" + a.join(",") + "]";
  }
  var p = [];
  for (var n in v) if (v.hasOwnProperty(n)) p.push(dlpcJ(String(n)) + ":" + dlpcJ(v[n]));
  return "{" + p.join(",") + "}";
}

function dlpcTentar(f, padrao) {
  try { return f(); } catch (e) { return padrao; }
}

/* ⚠️ `app.project.path` SEM projeto aberto lança "Unknown error exception" (banco, §1): na tela inicial o
   projeto é null, não vazio. */
function dlpcEstado() {
  try {
    var caminho = dlpcTentar(function () { return app.project ? app.project.path : ""; }, "");
    var seqs = caminho ? dlpcTentar(function () { return app.project.sequences.numSequences; }, null) : null;
    var ativa = caminho ? dlpcTentar(function () {
      return app.project.activeSequence ? app.project.activeSequence.name : "";
    }, "") : "";
    return dlpcJ({ versao: String(app.version), build: dlpcTentar(function () { return String(app.build); }, ""),
                   projeto: caminho || null, sequencias: seqs, sequencia_ativa: ativa || null });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

function dlpcSequencias() {
  try {
    if (!dlpcTentar(function () { return app.project.path; }, "")) return dlpcJ({ erro: "nenhum projeto aberto" });
    var fora = [];
    var lista = app.project.sequences;
    for (var i = 0; i < lista.numSequences; i++) {
      var s = lista[i];
      fora.push({ nome: s.name, id: s.sequenceID,
                  ativa: !!(app.project.activeSequence && app.project.activeSequence.sequenceID === s.sequenceID) });
    }
    return dlpcJ({ sequencias: fora });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

/* Abrir um .prproj: o gesto mais simples de "controlar pelo app". `app.openDocument(caminho)` abre sem
   diálogo quando o projeto é da mesma versão (o de outra versão pede conversão: diálogo, prazo no serviço). */
function dlpcAbrirProjeto(caminho) {
  try {
    // (caminho, sem o diálogo de conversão, sem o de localizar mídia, sem avisos): quem religa a mídia é o app — o
    // diálogo "Link Media" travaria a ponte. Medido sem diálogo no 23.2 (projeto do 22.6, 1.646 itens offline) e no
    // 26.5.2 (R04 com a mídia num disco inexistente: 69 offline, 1,3 s) — banco, api-extendscript.md.
    var ok = app.openDocument(caminho, true, true, true);
    return dlpcJ({ ok: !!ok, projeto: dlpcTentar(function () { return app.project.path; }, "") });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

/* ── MONTAR no Premiere (organograma do modo Premiere, aprovado em 2026-10-19: decisão A) ─────────────────────────
   O plano vem do serviço (`premiere_montagem.plano`): mídias, planos {m, v, t, rec, dur, src, ref} e marcas {q, nome,
   nota}. Tudo em TICKS exatos (o in/out em segundos arredonda no 23.2: banco, laboratório B14/B16).
   ⭐ O áudio vinculado: `overwriteClip` de um clipe A/V põe o áudio na trilha de MESMO número do vídeo (banco,
   api-extendscript.md). Por isso cada mídia ganha um subclipe SÓ DE VÍDEO e outro SÓ DE ÁUDIO (`createSubClip` com
   takeVideo/takeAudio), numa bin "planos": o vídeo cai só no V, o áudio só no A. */
function dlpcBin(pai, nome) {
  for (var i = 0; i < pai.children.numItems; i++) {
    var c = pai.children[i];
    if (c.type === 2 && c.name === nome) return c;
  }
  return pai.createBin(nome);
}
function dlpcNorm(p) { return String(p || "").replace(/\//g, "\\").toLowerCase(); }
function dlpcTempo(ticks) { var t = new Time(); t.ticks = String(ticks); return t; }
function dlpcMapa(bin) {
  var m = {};
  for (var i = 0; i < bin.children.numItems; i++) {
    var c = bin.children[i];
    var p = dlpcTentar(function () { return c.getMediaPath(); }, "");
    if (p) m[dlpcNorm(p)] = c;
  }
  return m;
}

function dlpcMontar(pl) {
  try {
    if (!dlpcTentar(function () { return app.project.path; }, "")) return dlpcJ({ erro: "nenhum projeto aberto no Premiere" });
    var casa = dlpcBin(app.project.rootItem, "De Lá Pra Cá");
    var bin = dlpcBin(dlpcBin(casa, "Mídia"), pl.nome);
    var binPlanos = dlpcBin(bin, "planos");
    var mapa = dlpcMapa(bin), faltam = [], k;
    for (k = 0; k < pl.midias.length; k++) if (!mapa[dlpcNorm(pl.midias[k])]) faltam.push(pl.midias[k]);
    if (faltam.length) app.project.importFiles(faltam, true, bin, false);
    mapa = dlpcMapa(bin);
    var itens = [], semItem = 0;
    for (k = 0; k < pl.midias.length; k++) { itens[k] = mapa[dlpcNorm(pl.midias[k])] || null; if (!itens[k]) semItem++; }
    var subV = {}, subA = {};
    function sub(i, video) {
      var cache = video ? subV : subA;
      if (cache[i] !== undefined) return cache[i];
      var it = itens[i], s = null;
      if (it) {
        var fim = dlpcTentar(function () { return it.getOutPoint(4).ticks; }, null) ||
                  dlpcTentar(function () { return it.getOutPoint().ticks; }, null);
        s = dlpcTentar(function () {
          return it.createSubClip(it.name + (video ? " · V" : " · A"), "0", String(fim), 0, video ? 1 : 0, video ? 0 : 1);
        }, null);
        if (s) dlpcTentar(function () { s.moveBin(binPlanos); return true; }, false);
      }
      cache[i] = s;
      return s;
    }
    // a sequência: com as configurações do 1º vídeo (taxa e tamanho), esvaziada
    var primeiro = null;
    for (k = 0; k < pl.planos.length && !primeiro; k++) if (pl.planos[k].v && itens[pl.planos[k].m]) primeiro = itens[pl.planos[k].m];
    if (!primeiro) for (k = 0; k < itens.length && !primeiro; k++) primeiro = itens[k];
    if (!primeiro) return dlpcJ({ erro: "nenhuma mídia entrou no projeto (o Premiere não importou os arquivos)" });
    var seq = app.project.createNewSequenceFromClips(pl.nome, [primeiro], bin);
    if (!seq) return dlpcJ({ erro: "o Premiere não criou a sequência" });
    // o nome que a bin MOSTRA é o do item (banco: o nome da Sequence sozinho não chega ao item); a tela diz o que ficou
    dlpcTentar(function () { if (seq.projectItem.name !== pl.nome) seq.projectItem.name = pl.nome; return 1; }, 0);
    var nomeNaBin = dlpcTentar(function () { return seq.projectItem.name; }, "") || seq.name;
    var t, n;
    for (t = 0; t < seq.videoTracks.numTracks; t++) while (seq.videoTracks[t].clips.numItems) seq.videoTracks[t].clips[0].remove(false, false);
    for (t = 0; t < seq.audioTracks.numTracks; t++) while (seq.audioTracks[t].clips.numItems) seq.audioTracks[t].clips[0].remove(false, false);
    dlpcTentar(function () { seq.setZeroPoint(String(pl.inicio * pl.tpf)); return true; }, false);
    var aviso = [];
    var tb = dlpcTentar(function () { return Number(seq.timebase); }, 0);
    if (tb && Math.abs(tb - pl.tpf) > 1) aviso.push("a sequência nasceu em outra taxa que a timeline (a do 1º arquivo): confira");
    // trilhas que faltam (QE, não documentado: se falhar, os planos de trilha inexistente vão para a lista de falhas)
    var maxV = 0, maxA = 0;
    for (k = 0; k < pl.planos.length; k++) { var q0 = pl.planos[k]; if (q0.v) maxV = Math.max(maxV, q0.t); else maxA = Math.max(maxA, q0.t); }
    app.project.openSequence(seq.sequenceID);
    var addV = maxV - seq.videoTracks.numTracks, addA = maxA - seq.audioTracks.numTracks;
    if (addV > 0 || addA > 0) {
      dlpcTentar(function () {
        app.enableQE();
        qe.project.getActiveSequence().addTracks(Math.max(addV, 0), seq.videoTracks.numTracks, Math.max(addA, 0), 1,
                                                 seq.audioTracks.numTracks, 0, 0, 0);
        return true;
      }, false);
    }
    var colocados = 0, falhas = [], mudas = {};
    for (k = 0; k < pl.planos.length; k++) {
      var p = pl.planos[k];
      var trilha = p.v ? seq.videoTracks[p.t - 1] : seq.audioTracks[p.t - 1];
      var s = sub(p.m, p.v);
      if (!trilha || !s) { falhas.push((p.v ? "V" : "A") + p.t + " @" + p.rec + (trilha ? " (subclipe)" : " (trilha)")); continue; }
      try {
        // ⛔ MEDIDO (23.6, 2026-10-19): no ÁUDIO o Premiere arredonda a entrada PARA BAIXO depois de passar a amostras, e
        // um quadro exato às vezes cai uma fração abaixo — 498 virava 497 (o vídeo não: 109/109 exatos no PRODUCAO-A).
        // Medido no room tone do PRODUCAO-A (WAV 48 kHz): +0,25 q ainda dá 497; +0,5 e +0,75 dão 498. A folga fica no meio
        // dessa janela: 0,6 de quadro.
        var folga = p.v ? 0 : Math.floor(pl.tpf * 0.6);
        s.setInPoint(dlpcTempo(p.src + folga), 4);
        s.setOutPoint(dlpcTempo(p.src + folga + p.dur * pl.tpf), 4);
        var rec = p.rec * pl.tpf;
        trilha.overwriteClip(s, dlpcTempo(rec));
        for (n = trilha.clips.numItems - 1; n >= 0; n--) {
          var c = trilha.clips[n];
          if (Math.abs(Number(c.start.ticks) - rec) < pl.tpf / 2) {
            c.end = dlpcTempo(rec + p.dur * pl.tpf);
            // o som DESLIGADO no Avid entra desligado (como o Flags=2 do Resolve; autor, 2026-10-29)
            if (p.desligado && !dlpcTentar(function () { c.disabled = true; return c.disabled === true; }, false))
              falhas.push("A" + p.t + " @" + p.rec + " (não desligou)");
            break;
          }
        }
        colocados++;
        if (p.ref && p.v) mudas[p.t] = true;
      } catch (e) {
        falhas.push((p.v ? "V" : "A") + p.t + " @" + p.rec + " (" + e + ")");
      }
    }
    for (var vt in mudas) if (mudas.hasOwnProperty(vt)) dlpcTentar(function () { seq.videoTracks[Number(vt) - 1].setMute(1); return true; }, false);
    var marcadas = 0;
    for (k = 0; k < pl.marcas.length; k++) {
      var mk = pl.marcas[k];
      var ok = dlpcTentar(function () {
        var m = seq.markers.createMarker(mk.q * pl.tpf / 254016000000);
        m.name = mk.nome; m.comments = mk.nota;
        return true;
      }, false);
      if (ok) marcadas++;
    }
    return dlpcJ({ ok: true, sequencia: nomeNaBin, id: seq.sequenceID, colocados: colocados, planos: pl.planos.length,
                   falhas: falhas.slice(0, 30), nfalhas: falhas.length, sem_item: semItem, marcas: marcadas,
                   trilhas: [seq.videoTracks.numTracks, seq.audioTracks.numTracks], aviso: aviso });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

/* Ler uma sequência pelo id (ou a ativa): cada clipe com início, fim e entrada em TICKS e o arquivo — a conferência da
   montagem e, depois, o Daqui Pra Lá a partir da sequência aberta. */
function dlpcLerSequencia(id) {
  try {
    var seq = null, i, t, k;
    if (id) { for (i = 0; i < app.project.sequences.numSequences; i++) if (app.project.sequences[i].sequenceID === id) seq = app.project.sequences[i]; }
    else seq = app.project.activeSequence;
    if (!seq) return dlpcJ({ erro: "sequência não encontrada" });
    function trilhas(lista, letra) {
      var fora = [];
      for (t = 0; t < lista.numTracks; t++) {
        var tr = lista[t], clipes = [];
        for (k = 0; k < tr.clips.numItems; k++) {
          var c = tr.clips[k];
          clipes.push({ nome: c.name, inicio: String(c.start.ticks), fim: String(c.end.ticks), entrada: String(c.inPoint.ticks),
                        arquivo: dlpcTentar(function () { return c.projectItem.getMediaPath(); }, ""),
                        desligado: dlpcTentar(function () { return c.disabled; }, null) });
        }
        fora.push({ trilha: letra + (t + 1), clipes: clipes, mudo: dlpcTentar(function () { return tr.isMuted(); }, null) });
      }
      return fora;
    }
    return dlpcJ({ nome: seq.name, id: seq.sequenceID, timebase: String(seq.timebase),
                   zero: dlpcTentar(function () { return String(seq.zeroPoint); }, ""),
                   video: trilhas(seq.videoTracks, "V"), audio: trilhas(seq.audioTracks, "A"),
                   marcas: dlpcTentar(function () { return seq.markers.numMarkers; }, null) });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

/* ── PREMIERE → PREMIERE (organograma aprovado pelo autor em 2026-10-22) ──────────────────────────────────────────────
   O serviço grava a CÓPIA relinkada do .prproj (`motor/prproj/copia.py`); aqui ela entra no projeto ABERTO pelo
   `importSequences` — só a sequência pedida e o que ela usa, como sequência NOVA com clipes novos; a original fica
   intacta. Medido no 26.5.2 (banco, api-extendscript.md "PREMIERE → PREMIERE NO 26.5.2"): corte idêntico em ticks.
   ⛔ O `importSequences` devolve true e às vezes não cria nada (23.2): conta-se o que surgiu. ⛔ Ele também RELIGA
   sozinho, calado: o serviço confere o caminho de cada clipe contra a decisão do casamento. */
function dlpcTodos(pasta, saida) {
  saida = saida || [];
  for (var i = 0; i < pasta.children.numItems; i++) {
    var c = pasta.children[i];
    saida.push(c);
    if (c.type === 2) dlpcTodos(c, saida);
  }
  return saida;
}
function dlpcSeqPorId(id) {
  var l = app.project.sequences;
  for (var i = 0; i < l.numSequences; i++) if (l[i].sequenceID === id) return l[i];
  return null;
}
/* A propriedade do Motion pelo nome em inglês, ou pela posição (o nome muda com o idioma do Premiere). */
function dlpcMotionProp(clipe, nome, indice) {
  for (var i = 0; i < clipe.components.numItems; i++) {
    var c = clipe.components[i];
    if (c.matchName !== "AE.ADBE Motion") continue;
    for (var k = 0; k < c.properties.numItems; k++) if (c.properties[k].displayName === nome) return c.properties[k];
    return c.properties.numItems > indice ? c.properties[indice] : null;
  }
  return null;
}

function dlpcImportarCopia(p) {
  try {
    if (!dlpcTentar(function () { return app.project.path; }, "")) return dlpcJ({ erro: "nenhum projeto aberto no Premiere" });
    var i, k, t, l = app.project.sequences, antes = {}, raiz = app.project.rootItem, itensAntes = {};
    for (i = 0; i < l.numSequences; i++) antes[l[i].sequenceID] = 1;
    var velhos = dlpcTodos(raiz);
    for (i = 0; i < velhos.length; i++) itensAntes[velhos[i].nodeId] = 1;
    var ok = app.project.importSequences(p.copia, [p.seq]);
    var novas = [];
    l = app.project.sequences;
    for (i = 0; i < l.numSequences; i++) if (!antes[l[i].sequenceID]) novas.push(l[i]);
    /* B071: a cópia religada EXISTE — dizer onde, para o editor importá-la à mão (ES3: sem template) */
    if (!novas.length) return dlpcJ({ ok: false, importou: !!ok, copia: p.copia,
                                      erro: "o Premiere não criou a sequência — a cópia religada está em " + p.copia + " (File > Import para tentar à mão)" });
    var princ = null;
    for (i = 0; i < novas.length; i++) if (novas[i].name === p.original) princ = novas[i];
    if (!princ) princ = novas[0];
    // tudo o que entrou vai para De Lá Pra Cá › <nome da cópia>. ⛔ MEDIDO no 26.5.2 (2026-10-22): a bin da cópia com o MESMO
    // UID de uma bin do projeto (01_Footage…) não vem nova — os clipes novos caem DENTRO da bin do editor, ao lado dos
    // antigos. Por isso o que é novo se procura em todo o projeto: o item novo dentro de bin ANTIGA (ou da raiz) se move;
    // a bin nova vai inteira.
    var dlpc = dlpcBin(raiz, p.bin), pasta = dlpcBin(dlpc, p.nome), mover = [], novosItens = [];
    itensAntes[dlpc.nodeId] = 1;
    itensAntes[pasta.nodeId] = 1;
    function varrer(bin) {
      for (var a = 0; a < bin.children.numItems; a++) {
        var c = bin.children[a];
        if (!itensAntes[c.nodeId]) mover.push(c);
        else if (c.type === 2 && c.nodeId !== dlpc.nodeId) varrer(c);
      }
    }
    varrer(raiz);
    for (i = 0; i < mover.length; i++) dlpcTentar(function () { mover[i].moveBin(pasta); return 1; }, 0);
    // renomear o ITEM renomeia a sequência (banco: o nome da Sequence sozinho não chega ao item)
    dlpcTentar(function () { princ.projectItem.name = p.nome; return 1; }, 0);
    // a escala do arquivo de outro raster (o Premiere não a acompanha): Scale × fator, keyframes inclusive
    var escalas = 0;
    for (i = 0; i < novas.length; i++) {
      var vt = novas[i].videoTracks;
      for (t = 0; t < vt.numTracks; t++) {
        for (k = 0; k < vt[t].clips.numItems; k++) {
          var c = vt[t].clips[k];
          var mp = dlpcNorm(dlpcTentar(function () { return c.projectItem.getMediaPath(); }, ""));
          var f = mp && p.escalas ? p.escalas[mp] : null;
          if (!f) continue;
          var sc = dlpcMotionProp(c, "Scale", 1);
          if (!sc) continue;
          if (f instanceof Array) {
            // o ESTICADO (a regra do Resolve para o proxy anexado de outra proporção): Uniform Scale desligado, Scale =
            // altura e Scale Width = largura (banco, api-extendscript, laboratório B11). Com ele já desligado, cada um × o seu.
            var sw = dlpcMotionProp(c, "Scale Width", 2), un = dlpcMotionProp(c, "Uniform Scale", 3);
            if (!sw || !un) continue;
            var uniforme = dlpcTentar(function () { return !!un.getValue(); }, true);
            if (uniforme) dlpcTentar(function () { un.setValue(false, true); return 1; }, 0);
            if (sc.isTimeVarying()) {
              var ks2 = sc.getKeys();
              if (uniforme) dlpcTentar(function () { sw.setTimeVarying(true); return 1; }, 0);
              for (var j2 = 0; j2 < ks2.length; j2++) {
                var v2 = sc.getValueAtKey(ks2[j2]);
                var w2 = uniforme ? v2 : sw.getValueAtKey(ks2[j2]);
                if (uniforme) sw.addKey(ks2[j2]);
                sw.setValueAtKey(ks2[j2], w2 * f[0], true);
                sc.setValueAtKey(ks2[j2], v2 * f[1], true);
              }
            } else {
              var v = sc.getValue(), w = uniforme ? v : sw.getValue();
              sw.setValue(w * f[0], true);
              sc.setValue(v * f[1], true);
            }
            escalas++;
            continue;
          }
          if (sc.isTimeVarying()) {
            var ks = sc.getKeys();
            for (var j = 0; j < ks.length; j++) sc.setValueAtKey(ks[j], sc.getValueAtKey(ks[j]) * f, true);
          } else sc.setValue(sc.getValue() * f, true);
          // já esticado no projeto (Uniform Scale desligado): a largura vai junto, ou o plano achata
          var sw1 = dlpcMotionProp(c, "Scale Width", 2), un1 = dlpcMotionProp(c, "Uniform Scale", 3);
          if (sw1 && un1 && !dlpcTentar(function () { return !!un1.getValue(); }, true)) {
            if (sw1.isTimeVarying()) {
              var ks1 = sw1.getKeys();
              for (var j1 = 0; j1 < ks1.length; j1++) sw1.setValueAtKey(ks1[j1], sw1.getValueAtKey(ks1[j1]) * f, true);
            } else sw1.setValue(sw1.getValue() * f, true);
          }
          escalas++;
        }
      }
    }
    // cada CLIPE DAS SEQUÊNCIAS DA CÓPIA (não "os itens novos"): ⛔ MEDIDO no 26.5.2 (2026-10-22) — o Premiere DEDUPLICA:
    // se o projeto já tem um item com o mesmo arquivo (uma cópia anterior), a sequência nova usa o item que já existe e
    // nenhum item novo nasce. O caminho e o offline vêm do item de cada clipe, uma vez por item. O offline com o arquivo
    // no lugar se religa no mesmo caminho (23.2: 2 itens offline com o arquivo existindo; `changeMediaPath` religou).
    var itens = [], vistos = {}, religados = 0;
    for (i = 0; i < novas.length; i++) {
      var listas = [novas[i].videoTracks, novas[i].audioTracks];
      for (var L = 0; L < 2; L++) {
        for (t = 0; t < listas[L].numTracks; t++) {
          for (k = 0; k < listas[L][t].clips.numItems; k++) {
            var it = dlpcTentar(function () { return listas[L][t].clips[k].projectItem; }, null);
            if (!it || vistos[it.nodeId] || dlpcTentar(function () { return it.isSequence(); }, false)) continue;
            vistos[it.nodeId] = 1;
            var cam = dlpcTentar(function () { return it.getMediaPath(); }, "");
            var off = dlpcTentar(function () { return it.isOffline(); }, false);
            if (off && cam && new File(cam).exists) {
              dlpcTentar(function () { it.changeMediaPath(cam, true); return 1; }, 0);
              off = dlpcTentar(function () { return it.isOffline(); }, true);
              if (!off) religados++;
            }
            itens.push({ nome: it.name, caminho: cam, offline: !!off });
          }
        }
      }
    }
    // a cópia ABERTA no fim: o editor a vê sem procurar (memória "entrega organizada": o resultado à vista)
    dlpcTentar(function () { app.project.openSequence(princ.sequenceID); return 1; }, 0);
    return dlpcJ({ ok: true, importou: !!ok, id: princ.sequenceID, sequencia: princ.name, novas: novas.length,
                   itens: itens, religados_no_lugar: religados, escalas: escalas, movidos: mover.length });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

/* Marcadores numa sequência: `{id, marcas: [{t (ticks), nome, nota, cor}], dado}`. Os nossos levam `#dado` no fim do
   comentário: marcar de novo apaga só os nossos (o Premiere não tem o customData do Resolve). */
function dlpcMarcar(p) {
  try {
    var s = dlpcSeqPorId(p.id);
    if (!s) return dlpcJ({ erro: "a sequência não está mais no projeto" });
    var ms = s.markers, apagar = [], m = ms.getFirstMarker(), i, n = 0;
    var cores = { Green: 0, Red: 1, Purple: 2, Orange: 3, Yellow: 4, White: 5, Blue: 6, Cyan: 7 };
    while (m) {
      if (String(m.comments || "").indexOf("#" + p.dado) >= 0) apagar.push(m);
      m = ms.getNextMarker(m);
    }
    for (i = 0; i < apagar.length; i++) ms.deleteMarker(apagar[i]);
    for (i = 0; i < p.marcas.length; i++) {
      var x = p.marcas[i];
      var mk = ms.createMarker(Number(x.t) / 254016000000);
      if (!mk) continue;
      mk.name = String(x.nome || "DLPC");
      mk.comments = String(x.nota || "") + "  #" + p.dado;
      if (x.cor && cores[x.cor] !== undefined) dlpcTentar(function () { mk.setColorByIndex(cores[x.cor]); return 1; }, 0);
      n++;
    }
    return dlpcJ({ ok: true, marcadores: n, apagados: apagar.length });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

/* A conferência pela referência: abrir a sequência; depois, quadro a quadro, a agulha no ponto e o PNG (o `exportFramePNG`
   do QE). ⛔ Ele devolve false e grava DEPOIS (banco, 23.2): quem espera o arquivo é o serviço. */
function dlpcConfInicio(id) {
  try {
    var s = dlpcSeqPorId(id);
    if (!s) return dlpcJ({ erro: "a sequência não está mais no projeto" });
    app.project.openSequence(id);
    app.enableQE();
    qe.project.init();
    return dlpcJ({ ok: true, nome: s.name });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}
function dlpcExportarQuadros(p) {
  try {
    var s = dlpcSeqPorId(p.id);
    if (!s) return dlpcJ({ erro: "a sequência não está mais no projeto" });
    if (!app.project.activeSequence || app.project.activeSequence.sequenceID !== p.id) app.project.openSequence(p.id);
    app.enableQE();
    var q = qe.project.getActiveSequence(), n = 0;
    for (var i = 0; i < p.pontos.length; i++) {
      s.setPlayerPosition(String(p.pontos[i].t));
      q.exportFramePNG(q.CTI.timecode, p.pontos[i].arquivo);
      n++;
    }
    return dlpcJ({ ok: true, pedidos: n });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

/* "Carregar a sequência aberta" no modo Premiere: o projeto e a sequência ativa (o app lê o projeto SALVO). */
/* A SELEÇÃO da timeline aberta (2026-10-24, sonda do arrasto de clipes: o arrasto só traz um ponteiro — o gesto vem do
   arrasto, o dado vem daqui; banco premiere-cep/arrastar-e-selecao.md §6e). Só lê. Cada item: o que ele é (nest,
   multicam, camada de ajuste, offline), onde está, os efeitos e os vínculos — as variáveis do laboratório. */
function dlpcSelecaoDaTimeline() {
  try {
    var seq = app.project.activeSequence;
    if (!seq) return dlpcJ({ erro: "nenhuma sequência aberta no Premiere" });
    var itens = [], t, k, i;
    function ler(lista, letra) {
      for (t = 0; t < lista.numTracks; t++) {
        var tr = lista[t];
        for (k = 0; k < tr.clips.numItems; k++) {
          var c = tr.clips[k];
          if (!dlpcTentar(function () { return c.isSelected(); }, false)) continue;
          var pi = dlpcTentar(function () { return c.projectItem; }, null), efeitos = [];
          for (i = 0; i < dlpcTentar(function () { return c.components.numItems; }, 0); i++)
            efeitos.push(dlpcTentar(function () { return c.components[i].displayName; }, "?"));
          itens.push({ trilha: letra + (t + 1), nome: c.name, inicio: String(c.start.ticks), fim: String(c.end.ticks),
                       entrada: String(c.inPoint.ticks), tipo: dlpcTentar(function () { return c.mediaType; }, ""),
                       item: pi ? dlpcTentar(function () { return pi.name; }, "") : "",
                       arquivo: pi ? dlpcTentar(function () { return pi.getMediaPath(); }, "") : "",
                       offline: pi ? dlpcTentar(function () { return pi.isOffline(); }, null) : null,
                       nest: pi ? dlpcTentar(function () { return pi.isSequence(); }, null) : null,
                       multicam: pi ? dlpcTentar(function () { return pi.isMulticamClip(); }, null) : null,
                       ajuste: dlpcTentar(function () { return c.isAdjustmentLayer(); }, null),
                       desligado: dlpcTentar(function () { return c.disabled; }, null),
                       velocidade: dlpcTentar(function () { return c.getSpeed(); }, null),
                       vinculados: dlpcTentar(function () { return c.getLinkedItems().numItems; }, null),
                       // o layout do áudio do ITEM (0 mono, 1 estéreo, 2 5.1, 3 adaptativo…) e em quantos clipes ele entra
                       canais: pi ? dlpcTentar(function () { var m = pi.getAudioChannelMapping;
                         if (typeof m === "function") m = pi.getAudioChannelMapping();   // propriedade no PProPanel da Adobe
                         return { tipo: m.audioChannelsType, clipes: m.audioClipsNumber }; }, null) : null,
                       efeitos: efeitos });
        }
      }
    }
    ler(seq.videoTracks, "V");
    ler(seq.audioTracks, "A");
    return dlpcJ({ sequencia: seq.name, id: seq.sequenceID, itens: itens,
                   selecao: dlpcTentar(function () { return seq.getSelection().length; }, null) });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}

function dlpcSequenciaAtiva() {
  try {
    var caminho = dlpcTentar(function () { return app.project.path; }, "");
    if (!caminho) return dlpcJ({ erro: "nenhum projeto aberto no Premiere" });
    var s = app.project.activeSequence;
    if (!s) return dlpcJ({ erro: "nenhuma sequência aberta no Premiere" });
    return dlpcJ({ projeto: caminho, id: s.sequenceID, nome: s.name });
  } catch (e) {
    return dlpcJ({ erro: String(e) });
  }
}
