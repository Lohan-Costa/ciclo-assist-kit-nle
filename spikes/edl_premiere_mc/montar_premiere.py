"""A EDL do Premiere × a do Media Composer — passo 1: a MESMA sequência de laboratório, montada no Premiere por script.

Mídia: `laboratorio-de-midia/receitas/base/B30_EDL.json` (cada fonte com TC próprio: A 01h, B 02h com 5 canais, LONGO
03h com nome de 51 caracteres, ACENTO 04h "AÇÃO", T25 05h a 25 fps, SOM 06h WAV de 4 canais). A sequência, 23,976 a
partir de 01:00:00:00 (quadros da sequência):

    V1  A 0–72 · B 72–144 (dissolve de 24 centrado no corte) · ACENTO 144–216 · T25 216–288 · vazio 288–312
        A outra vez 312–360 (outro trecho) · LONGO 384–456 (a 50 %: 36 quadros da fonte)
    A6  SOM 0–144 (4 canais: espalham para A6…A9)

O áudio dos clipes de vídeo vai junto (A1…; o B de 5 canais espalha para A1…A5). Saída: o `.prproj` na pasta da rodada
(`MIDIAS DE TESTES/9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-25 EDL PREMIERE MC/`). Premiere aberto com a ponte do
laboratório. `python3 spikes/edl_premiere_mc/montar_premiere.py` — sai 0 se a sequência ficou como o plano.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FAMILIA = RAIZ.parents[1]
sys.path.insert(0, str(FAMILIA / "laboratorio-de-midia"))

B30 = FAMILIA / "laboratorio-de-midia" / "saida" / "base" / "B30_EDL"
PASTA = FAMILIA.parent / "MIDIAS DE TESTES" / "9 SAIDAS DOS APPS" / "_CICLO ASSIST" / "2026-11-25 EDL PREMIERE MC"
VAZIO = RAIZ / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj"
SEQ = "B30 EDL LAB"
TICKS = 254016000000
TPF = TICKS * 1001 // 24000           # 23,976

A, B, LONGO = "B30_A_MOV-PRORES.mov", "B30_B_MOV-PRORES.mov", "B30_NOME_DE_FONTE_COMPRIDO_PASSA_DOS_32_CARACTERES_MOV-PRORES.mov"
ACENTO, T25, SOM = "B30_CENA_AÇÃO_MOV-PRORES.mov", "B30_T25_MOV-PRORES.mov", "B30_SOM_WAV-BWF.wav"

# (arquivo, entrada em quadros de 23,976 desde o início da mídia, duração, gravação)
PLANOS = [(A, 48, 72, 0), (B, 48, 72, 72), (ACENTO, 48, 72, 144), (T25, 48, 72, 216),
          (A, 240, 48, 312), (LONGO, 48, 72, 384)]   # LONGO: 72 na sequência, a 50 % (36 da fonte)
SOM_PLANO = (SOM, 24, 144, 0, 6)       # … e a trilha (A6)


def _versao(nome: str) -> Path:
    n = 1
    while (PASTA / f"{nome} v{n:02d}.prproj").exists():
        n += 1
    return PASTA / f"{nome} v{n:02d}.prproj"


JS = r'''(function(proj, arqs, planos, som, nomeSeq, tpf){
  app.openDocument(proj, true, true, true, true);
  var pr = null; for (var i = 0; i < app.projects.numProjects; i++) if (app.projects[i].path == proj) pr = app.projects[i];
  if (!pr) return "ERRO não abriu";
  pr.importFiles(arqs, true, pr.rootItem, false);
  var itens = {};
  function varre(b){ for (var i = 0; i < b.children.numItems; i++){ var c = b.children[i];
      if (c.type == 2) varre(c); else itens[c.name] = c; } }
  varre(pr.rootItem);
  function item(nome){ var base = nome.replace(/\.[^.]+$/, ""); return itens[nome] || itens[base]; }
  var seq = pr.createNewSequenceFromClips(nomeSeq, [item(planos[0][0])], pr.rootItem);
  var t;
  for (t = 0; t < seq.videoTracks.numTracks; t++) while (seq.videoTracks[t].clips.numItems) seq.videoTracks[t].clips[0].remove(false, false);
  for (t = 0; t < seq.audioTracks.numTracks; t++) while (seq.audioTracks[t].clips.numItems) seq.audioTracks[t].clips[0].remove(false, false);
  seq.setZeroPoint(String(86400 * tpf));
  pr.openSequence(seq.sequenceID);
  app.enableQE();
  var faltam = 9 - seq.audioTracks.numTracks;
  if (faltam > 0) qe.project.getActiveSequence().addTracks(0, seq.videoTracks.numTracks, faltam, 1, seq.audioTracks.numTracks, 0, 0, 0);
  var log = [];
  function por(it, ent, dur, rec, trilha){
    it.setInPoint(String(ent * tpf), 4); it.setOutPoint(String((ent + dur) * tpf), 4);
    trilha.overwriteClip(it, String(rec * tpf)); }
  for (var k = 0; k < planos.length; k++) { var p = planos[k];
    var it = item(p[0]); if (!it) { log.push("SEM ITEM " + p[0]); continue; }
    por(it, p[1], p[2], p[3], seq.videoTracks[0]); }
  var s = item(som[0]); if (s) por(s, som[1], som[2], som[3], seq.audioTracks[som[4] - 1]); else log.push("SEM SOM");
  var q = qe.project.getActiveSequence();
  // QE conta os vazios como itens: acha pelo nome e pelo início
  function qeItem(tr, nome){ for (var i = 0; i < tr.numItems; i++){ var x = tr.getItemAt(i);
      if (x && x.name && x.name.indexOf(nome.replace(/\.[^.]+$/, "")) == 0) return x; } return null; }
  // a velocidade (metade) no LONGO
  // o setSpeed do QE MANTÉM a duração na sequência e encolhe a fonte (com ripple ou sem; 26.0.2): põe-se 72 e vira 36 da fonte
  try { log.push("speed=" + qeItem(q.getVideoTrackAt(0), planos[5][0]).setSpeed(0.5, "", false, true, false)); }
  catch (e) { log.push("speed ERRO " + e); }
  try { log.push("speed som=" + qeItem(q.getAudioTrackAt(0), planos[5][0]).setSpeed(0.5, "", false, true, false)); }
  catch (e) { log.push("speed som ERRO " + e); }
  // o dissolve de 24 quadros centrado no corte A|B (vídeo) e o de som no A1
  try { var b = qeItem(q.getVideoTrackAt(0), planos[1][0]);
        log.push("dissolve=" + b.addTransition(qe.project.getVideoTransitionByName("Cross Dissolve"), true, "00:00:01:00", "00:00:00:00", 0.5, false, true)); }
  catch (e) { log.push("dissolve ERRO " + e); }
  try { var ba = qeItem(q.getAudioTrackAt(0), planos[1][0]);
        log.push("audio=" + ba.addTransition(qe.project.getAudioTransitionByName("Potência constante"), true, "00:00:01:00", "00:00:00:00", 0.5, false, true)); }
  catch (e) { log.push("audio ERRO " + e); }
  pr.save();
  function trilhas(col){ var o = []; for (var i = 0; i < col.numTracks; i++){ var c = col[i].clips, l2 = [];
      for (var j = 0; j < c.numItems; j++) l2.push([c[j].name, Math.round(c[j].start.ticks / tpf),
          Math.round(c[j].end.ticks / tpf), Math.round(c[j].inPoint.ticks / tpf)]);
      var tr = col[i].transitions, l3 = [];
      for (var j2 = 0; tr && j2 < tr.numItems; j2++) l3.push([Math.round(tr[j2].start.ticks / tpf), Math.round(tr[j2].end.ticks / tpf)]);
      o.push({clipes: l2, transicoes: l3}); } return o; }
  return {log: log, v: trilhas(seq.videoTracks), a: trilhas(seq.audioTracks)};
})(%s, %s, %s, %s, %s, %s)'''


def main() -> int:
    from lab.bancadas import premiere as pr
    PASTA.mkdir(parents=True, exist_ok=True)
    proj = _versao("B30 EDL PREMIERE")
    shutil.copyfile(VAZIO, proj)
    arqs = [str(B30 / n) for n in (A, B, LONGO, ACENTO, T25, SOM)]
    pr.esperar_ponte(ate_s=120, vigia=True)
    js = JS % tuple(json.dumps(x, ensure_ascii=False) for x in (str(proj), arqs, PLANOS, SOM_PLANO, SEQ, TPF))
    r = pr.executar(js, timeout=600)
    print("projeto:", proj)
    print("log:", r["log"])
    for nome, col in (("V", r["v"]), ("A", r["a"])):
        for i, t in enumerate(col, 1):
            if t["clipes"] or t["transicoes"]:
                print(f"{nome}{i}: {t['clipes']}  transições {t['transicoes']}")
    v1 = [(c[1], c[2]) for c in r["v"][0]["clipes"]]
    esperado = [(0, 72), (72, 144), (144, 216), (216, 288), (312, 360), (384, 456)]
    ok = v1 == esperado and r["v"][0]["transicoes"]
    print("V1 como o plano" if v1 == esperado else f"V1 DIFERENTE: {v1}\n   esperado {esperado}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
