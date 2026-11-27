"""EDL para o som, lado PREMIERE (plano `docs/plano/2026-11-25-edl-para-o-som.md`): o que roda pela ponte do laboratório.

    python3 spikes/edl_som_premiere/ponte.py preparar        # projeto novo + bins + imports + subclipe
    python3 spikes/edl_som_premiere/ponte.py importar <bin> <arq…> [--in arq=quadro …]   # deixa SELECIONADOS (p/ o menu)
    python3 spikes/edl_som_premiere/ponte.py js '<código>'

Premiere 26.0.2 Mac com a ponte do laboratório (`laboratorio-de-midia/lab/bancadas/premiere.py`), sem vigia (alguém olha).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FAMILIA = RAIZ.parents[1]
sys.path.insert(0, str(FAMILIA / "laboratorio-de-midia"))
from lab.bancadas import premiere as pr  # noqa: E402

B31 = FAMILIA / "laboratorio-de-midia" / "saida" / "base" / "B31_EDL_SOM"
PASTA = FAMILIA.parent / "MIDIAS DE TESTES" / "9 SAIDAS DOS APPS" / "_CICLO ASSIST" / "2026-11-25 EDL SOM PREMIERE"
VAZIO = RAIZ / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj"
TPF = 254016000000 * 1001 // 24000
CAMA, CAMB, CAMA2 = "A001C003_MOV-PRORES.mov", "B001C007_MOV-PRORES.mov", "A001C004_MOV-PRORES.mov"
SOM1, SOM2 = "26Y11M25_T001_WAV-BWF.wav", "26Y11M25_T002_WAV-BWF.wav"
BINS = ["S1 SUBCLIPE", "S2 MERGED TC", "S3 MERGED IN", "S4 MULTICAM", "S5 NEST", "S10 CANAIS", "S11 ROLO"]

COMUM = r'''
function bin(nome){ var r = app.project.rootItem; for (var i = 0; i < r.children.numItems; i++)
    if (r.children[i].type == 2 && r.children[i].name == nome) return r.children[i]; return null; }
function itens(b, o){ o = o || []; for (var i = 0; i < b.children.numItems; i++){ var c = b.children[i];
    if (c.type == 2) itens(c, o); else o.push(c); } return o; }
function acha(b, nome){ var l = itens(b); for (var i = 0; i < l.length; i++) if (l[i].name == nome) return l[i]; return null; }
'''


def js(codigo: str, timeout: float = 600):
    return pr.executar(COMUM + codigo, timeout=timeout)


MONTAR = r"""(function(nomeSeq, eventos, soAudio, tpf){
  var pr = app.project, prim = acha(bin(eventos[0][0]), eventos[0][1]);
  var seq = pr.createNewSequenceFromClips(nomeSeq, [prim], pr.rootItem);
  var t;
  for (t = 0; t < seq.videoTracks.numTracks; t++) while (seq.videoTracks[t].clips.numItems) seq.videoTracks[t].clips[0].remove(false, false);
  for (t = 0; t < seq.audioTracks.numTracks; t++) while (seq.audioTracks[t].clips.numItems) seq.audioTracks[t].clips[0].remove(false, false);
  seq.setZeroPoint(String(86400 * tpf));
  pr.openSequence(seq.sequenceID);
  app.enableQE();
  var faltam = 8 - seq.audioTracks.numTracks;
  if (faltam > 0) qe.project.getActiveSequence().addTracks(0, seq.videoTracks.numTracks, faltam, 1, seq.audioTracks.numTracks, 0, 0, 0);
  var log = [];
  for (var k = 0; k < eventos.length; k++){ var e = eventos[k], it = acha(bin(e[0]), e[1]);
    if (!it){ log.push("SEM " + e[1]); continue; }
    it.setInPoint(String(e[2] * tpf), 4); it.setOutPoint(String((e[2] + e[3]) * tpf), 4);
    (soAudio ? seq.audioTracks[0] : seq.videoTracks[0]).overwriteClip(it, String(e[4] * tpf));
    // ⚠️ MERGED (26.0.2 Mac): o overwriteClip põe o ZERO do merged no tempo pedido — o trecho cai em posição + entrada.
    //    O move() leva só o item em que é chamado: anda-se com cada trilha. E na trilha de ÁUDIO o merged traz o vídeo
    //    junto: na variante só de áudio, o vídeo do evento sai.
    var desl = it.isMergedClip() ? e[2] : 0, ini = e[4] + desl;
    function ajusta(col, tira){ for (var i = 0; i < col.numTracks; i++){ var c = col[i].clips;
        for (var j = c.numItems - 1; j >= 0; j--){ var x = c[j];
          if (Math.round(x.start.ticks / tpf) != ini || x.name != it.name) continue;
          if (tira){ x.remove(false, false); continue; }
          if (desl){ var tm = new Time(); tm.ticks = String(-desl * tpf); x.move(tm); } } } }
    ajusta(seq.videoTracks, soAudio); ajusta(seq.audioTracks, false); }
  if (soAudio) for (t = 0; t < seq.videoTracks.numTracks; t++)
    for (var j2 = seq.videoTracks[t].clips.numItems - 1; j2 >= 0; j2--) seq.videoTracks[t].clips[j2].remove(false, false);
  pr.save();
  function trilhas(col){ var o = []; for (var i = 0; i < col.numTracks; i++){ var c = col[i].clips, l2 = [];
      for (var j = 0; j < c.numItems; j++) l2.push([c[j].name, Math.round(c[j].start.ticks / tpf),
          Math.round(c[j].end.ticks / tpf), Math.round(c[j].inPoint.ticks / tpf)]);
      if (l2.length) o.push([i + 1, l2]); } return o; }
  return {seq: seq.name, log: log, v: trilhas(seq.videoTracks), a: trilhas(seq.audioTracks)};
})(%s, %s, %s, %s)"""


def montar(nome: str, eventos: list, so_audio: bool) -> dict:
    """`eventos` = [[bin, item, entrada no item (quadros), duração, posição na sequência]] — um atrás do outro na V1
    (com o áudio ligado), ou SÓ na A1 (`so_audio`: nenhum segmento de vídeo)."""
    return js(MONTAR % (json.dumps(nome + (" SO AUDIO" if so_audio else "")), json.dumps(eventos, ensure_ascii=False),
                        "true" if so_audio else "false", TPF))


def preparar() -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    n = 1
    while (PASTA / f"B31 EDL SOM PREMIERE v{n:02d}.prproj").exists():
        n += 1
    proj = PASTA / f"B31 EDL SOM PREMIERE v{n:02d}.prproj"
    shutil.copyfile(VAZIO, proj)
    arq = {k: str(B31 / k) for k in (CAMA, CAMB, CAMA2, SOM1, SOM2)}
    r = js(r'''(function(proj, bins, arq, tpf){
      while (app.projects.numProjects) app.projects[0].closeDocument(0, 0);
      app.openDocument(proj, true, true, true, true);
      var r = app.project.rootItem;
      for (var i = 0; i < bins.length; i++) r.createBin(bins[i]);
      function imp(b, l){ var x = []; for (var i = 0; i < l.length; i++) x.push(arq[l[i]]);
          app.project.importFiles(x, true, bin(b), false); }
      imp("S1 SUBCLIPE", ["%s", "%s"]);
      imp("S5 NEST", ["%s", "%s"]);
      imp("S10 CANAIS", ["%s", "%s", "%s"]);
      imp("S11 ROLO", ["%s", "%s", "%s", "%s"]);
      var b1 = bin("S1 SUBCLIPE");
      var a = acha(b1, "%s"), b = acha(b1, "%s");
      a.createSubClip("A001C003.sub.01", String(120 * tpf), String(480 * tpf), 0, 1, 1);
      b.createSubClip("B001C007.sub.01", String(200 * tpf), String(440 * tpf), 0, 1, 1);
      // ⚠️ o subclipe nasce na RAIZ (banco) e o getInPoint dele lê 0–719 (o master inteiro) — o recorte vale: na
      //    timeline entra 120–480 / 200–440 (medido 2026-11-25, 26.0.2 Mac)
      var r0 = app.project.rootItem, sub = [];
      for (var i = 0; i < r0.children.numItems; i++) if (/\.sub\./.test(r0.children[i].name)) sub.push(r0.children[i]);
      for (var j = 0; j < sub.length; j++) sub[j].moveBin(b1);
      app.project.save();
      var o = {}; for (var k = 0; k < bins.length; k++){ var l = itens(bin(bins[k])), n = [];
          for (var j = 0; j < l.length; j++) n.push(l[j].name); o[bins[k]] = n; }
      return {projeto: app.project.path, bins: o};
    })(%s, %s, %s, %s)''' % (CAMA, CAMB, CAMA, SOM1, CAMA, CAMB, SOM1, CAMA, CAMA2, SOM1, SOM2, CAMA, CAMB,
                             json.dumps(str(proj)), json.dumps(BINS), json.dumps(arq), TPF))
    print(json.dumps(r, ensure_ascii=False, indent=1))


def importar(b: str, arqs: list[str], ins: dict[str, int]) -> None:
    """Importa na bin e deixa SELECIONADOS (o Premiere seleciona o que acabou de importar) — o menu age na seleção.
    `ins` = {arquivo: quadro} põe o ponto de ENTRADA (para o merged/multicâmera por ponto de entrada)."""
    r = js(r'''(function(b, arqs, ins, tpf){
      // ⚠️ importar DENTRO de uma bin não seleciona; na RAIZ os importados ficam selecionados (o menu age neles); o
      //    `ProjectItem.select()` SUBSTITUI a seleção (não soma). `mover` leva tudo à bin do caso depois do menu.
      app.project.importFiles(arqs, true, app.project.rootItem, false);
      // ⛔ a entrada vai nos SELECIONADOS (os recém-importados): pelo nome, a busca achava o item ANTIGO de mesmo nome
      //    noutra bin, e o merged "por ponto de entrada" saiu com as duas entradas em 0 (48 quadros fora, 2026-11-25)
      var s = app.getCurrentProjectViewSelection(), n = [];
      for (var q = 0; s && q < s.length; q++) if (ins[s[q].name] !== undefined) s[q].setInPoint(String(ins[s[q].name] * tpf), 4);
      for (var i = 0; s && i < s.length; i++) n.push(s[i].name);
      for (var q2 = 0; s && q2 < s.length; q2++) n[n.length] = s[q2].name + " in=" + Math.round(s[q2].getInPoint().ticks / tpf);
      return {selecionados: n};
    })(%s, %s, %s, %s)''' % (json.dumps(b), json.dumps([str(B31 / a) for a in arqs]), json.dumps(ins), TPF))
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    pr.esperar_ponte(ate_s=30, vigia=False)
    a = sys.argv[1:]
    if a[0] == "preparar":
        preparar()
    elif a[0] == "importar":
        ins = {}
        if "--in" in a:
            i = a.index("--in")
            ins = {x.split("=")[0]: int(x.split("=")[1]) for x in a[i + 1:]}
            a = a[:i]
        importar(a[1], a[2:], ins)
    elif a[0] == "mover":     # mover <bin>: tudo que estiver solto na raiz vai para a bin do caso
        print(json.dumps(js(r'''(function(b){ var r = app.project.rootItem, l = [], n = [];
          for (var i = 0; i < r.children.numItems; i++) if (r.children[i].type != 2) l.push(r.children[i]);
          for (var j = 0; j < l.length; j++){ l[j].moveBin(bin(b)); n.push(l[j].name); } app.project.save(); return n; })(%s)'''
          % json.dumps(a[1])), ensure_ascii=False))
    elif a[0] == "montar":    # montar <nome> '<eventos json>' [--so-audio]
        print(json.dumps(montar(a[1], json.loads(a[2]), "--so-audio" in a), ensure_ascii=False))
    elif a[0] == "js":
        print(json.dumps(js(a[1]), ensure_ascii=False, indent=1))
