"""A VERDADE da B32: a sequência montada no Premiere por script (o gesto: colocar e `setSpeed`), salva e renderizada.

    .venv/bin/python spikes/velocidade/montar_b32.py        (Premiere aberto com a ponte do laboratório)

Sai o `.prproj` versionado e o render ProRes 'Match Source' na pasta da rodada (`casos.PASTA`), e o que o Premiere leu
de cada clipe (início, fim, entrada, velocidade). Depois: `medir.py` no render.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path[:0] = [str(AQUI), str(AQUI.parents[1] / "spikes"), ]
import casos as C  # noqa: E402

sys.path.insert(0, str(C.LAB))
VAZIO = AQUI.parents[1] / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj"

JS = r'''(function(proj, arqs, planos, nomeSeq, tpf){
  for (var x = app.projects.numProjects - 1; x >= 0; x--) if (app.projects[x].path != proj) app.projects[x].closeDocument(true, false);
  app.openDocument(proj, true, true, true, true);
  var pr = null; for (var i = 0; i < app.projects.numProjects; i++) if (app.projects[i].path == proj) pr = app.projects[i];
  if (!pr) return {erro: "não abriu"};
  pr.importFiles(arqs, true, pr.rootItem, false);
  var itens = {};
  function varre(b){ for (var i = 0; i < b.children.numItems; i++){ var c = b.children[i];
      if (c.type == 2) varre(c); else itens[c.name] = c; } }
  varre(pr.rootItem);
  function item(nome){ var base = nome.replace(/\.[^.]+$/, ""); return itens[nome] || itens[base]; }
  var seq = pr.createNewSequenceFromClips(nomeSeq, [item(planos[0].arq)], pr.rootItem);
  var t;
  for (t = 0; t < seq.videoTracks.numTracks; t++) while (seq.videoTracks[t].clips.numItems) seq.videoTracks[t].clips[0].remove(false, false);
  for (t = 0; t < seq.audioTracks.numTracks; t++) while (seq.audioTracks[t].clips.numItems) seq.audioTracks[t].clips[0].remove(false, false);
  seq.setZeroPoint(String(86400 * tpf));
  pr.openSequence(seq.sequenceID);
  app.enableQE();
  var q = qe.project.getActiveSequence(), log = [];
  function qeItem(qt, rec){ for (var i = 0; i < qt.numItems; i++){ var x = qt.getItemAt(i);
      if (String(x.type) !== "Clip") continue;
      var s = (x.start && x.start.secs !== undefined) ? Number(x.start.secs) : Number(x.start.seconds);
      if (Math.abs(s - rec * tpf / 254016000000) < 0.02) return x; } return null; }
  for (var k = 0; k < planos.length; k++) { var p = planos[k], it = item(p.arq);
    if (!it) { log.push("SEM ITEM " + p.arq); continue; }
    it.setInPoint(String(p.ent), 4); it.setOutPoint(String(p.ent + p.dur * tpf), 4);
    seq.videoTracks[0].overwriteClip(it, String(p.rec * tpf));
    if (p.vel !== 1) {
      var rev = p.vel < 0, v = Math.abs(p.vel);
      var iv = qeItem(q.getVideoTrackAt(0), p.rec), ia = qeItem(q.getAudioTrackAt(0), p.rec);
      try { log.push(p.rot + " V " + (iv ? iv.setSpeed(v, "", rev, p.tom, false) : "sem item")); } catch (e) { log.push(p.rot + " V ERRO " + e); }
      try { log.push(p.rot + " A " + (ia ? ia.setSpeed(v, "", rev, p.tom, false) : "sem item")); } catch (e) { log.push(p.rot + " A ERRO " + e); }
    }
  }
  pr.save();
  function lista(col){ var o = []; for (var i = 0; i < col.numTracks; i++){ var c = col[i].clips;
      for (var j = 0; j < c.numItems; j++) o.push([i + 1, c[j].name, Math.round(c[j].start.ticks / tpf), Math.round(c[j].end.ticks / tpf),
          String(c[j].inPoint.ticks), c[j].getSpeed(), c[j].isSpeedReversed ? c[j].isSpeedReversed() : null]); } return o; }
  return {log: log, id: seq.sequenceID, v: lista(seq.videoTracks), a: lista(seq.audioTracks)};
})(%s, %s, %s, %s, %s)'''


def _versao(nome: str) -> Path:
    n = 1
    while (C.PASTA / f"{nome} v{n:02d}.prproj").exists():
        n += 1
    return C.PASTA / f"{nome} v{n:02d}.prproj"


def main() -> int:
    from lab.bancadas import premiere as pr
    C.PASTA.mkdir(parents=True, exist_ok=True)
    proj = _versao("B32 VELOCIDADE PREMIERE")
    shutil.copyfile(VAZIO, proj)
    arqs = sorted({str(m[0]) for _, m, _, _ in C.CASOS})
    planos = [{"rot": rot, "arq": m[0].name, "ent": C.entrada_ticks(m[1]), "dur": C.DUR, "rec": C.gravacao(i),
               "vel": vel, "tom": tom} for i, (rot, m, vel, tom) in enumerate(C.CASOS)]
    js = JS % tuple(json.dumps(x, ensure_ascii=False) for x in (str(proj), arqs, planos, C.SEQ, C.TPF))
    r = pr.executar(js, timeout=900)
    print("projeto:", proj)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    render = C.PASTA / (proj.stem + ".mov")
    print("render:", pr.executar("""(function(){ app.project.openSequence(%s); var s=app.project.activeSequence;
          return s.exportAsMediaDirect(%s, %s, 0); })()""" % (json.dumps(r["id"]), json.dumps(str(render)),
                                                              json.dumps(pr.preset_prores("2027"))), timeout=900), render)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
