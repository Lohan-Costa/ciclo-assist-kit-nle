"""B33 — o SOM com velocidade e em reverso, medido pela POSIÇÃO da fonte (a varredura: 500 Hz + 100 Hz por segundo).

A mídia do laboratório (B30/B02) repete a mesma claque e o mesmo tom a cada segundo: o som de OUTRO trecho, ou de trás
para a frente, soa igual (foi assim que o som do reverso saiu do quadro 336 sem ninguém ouvir, 2026-11-26). Aqui a
frequência instantânea diz o segundo da fonte: f = 500 + 100·t → t = (f − 500) / 100.

    .venv/bin/python spikes/velocidade/b33.py montar                 (Premiere aberto, ponte do laboratório)
    .venv/bin/python spikes/velocidade/b33.py medir <arquivo>        → <arquivo>.som.json + o resumo
    .venv/bin/python spikes/velocidade/b33.py comparar <a.som.json> <b.som.json>

Sequência 23,976 a partir de 01:00:00:00; cada caso 96 quadros (4 s) com 24 de vazio; entrada no quadro 48 (2 s) da
fonte. A/V na V1+A1/A2; o WAV (só som) na A3. A velocidade pelo QE `setSpeed(v, "", ao_contrário, manter_tom, false)`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
FAMILIA = AQUI.parents[3]
sys.path.insert(0, str(FAMILIA / "laboratorio-de-midia"))
PASTA = FAMILIA.parent / "MIDIAS DE TESTES" / "9 SAIDAS DOS APPS" / "_CICLO ASSIST" / "2026-11-26 VELOCIDADE B33"
MIDIA = PASTA / "MIDIA"
AV, WAV = MIDIA / "B33_AV_VARREDURA.mov", MIDIA / "B33_VARREDURA.wav"
VAZIO = AQUI.parents[1] / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj"
SEQ, TICKS = "B33 SOM", 254016000000
TPF = TICKS * 1001 // 24000
DUR, VAO, ENTRADA = 96, 24, 48
SR = 48000

# (rótulo, arquivo, trilha: "av" | "wav", velocidade, ao contrário)
CASOS = [
    ("AV 100%", AV, "av", 1.0, False),
    ("AV 50%", AV, "av", 0.5, False),
    ("AV 200%", AV, "av", 2.0, False),
    ("AV reverso", AV, "av", 1.0, True),
    ("AV reverso 50%", AV, "av", 0.5, True),
    ("WAV 100%", WAV, "wav", 1.0, False),
    ("WAV 50%", WAV, "wav", 0.5, False),
    ("WAV reverso", WAV, "wav", 1.0, True),
]


def gravacao(i: int) -> int:
    return i * (DUR + VAO)


JS = r'''(function(proj, av, wav, planos, nomeSeq, tpf){
  for (var x = app.projects.numProjects - 1; x >= 0; x--) app.projects[x].closeDocument(true, false);
  app.openDocument(proj, true, true, true, true);
  var pr = null; for (var i = 0; i < app.projects.numProjects; i++) if (app.projects[i].path == proj) pr = app.projects[i];
  if (!pr) return {erro: "não abriu"};
  pr.importFiles([av, wav], true, pr.rootItem, false);
  var itens = {};
  for (i = 0; i < pr.rootItem.children.numItems; i++) itens[pr.rootItem.children[i].name] = pr.rootItem.children[i];
  function item(c){ var n = c.split("/").pop(); return itens[n] || itens[n.replace(/\.[^.]+$/, "")]; }
  var seq = pr.createNewSequenceFromClips(nomeSeq, [item(av)], pr.rootItem), t;
  for (t = 0; t < seq.videoTracks.numTracks; t++) while (seq.videoTracks[t].clips.numItems) seq.videoTracks[t].clips[0].remove(false, false);
  for (t = 0; t < seq.audioTracks.numTracks; t++) while (seq.audioTracks[t].clips.numItems) seq.audioTracks[t].clips[0].remove(false, false);
  seq.setZeroPoint(String(86400 * tpf));
  pr.openSequence(seq.sequenceID);
  app.enableQE();
  var q = qe.project.getActiveSequence(), log = [];
  if (seq.audioTracks.numTracks < 3) q.addTracks(0, seq.videoTracks.numTracks, 3 - seq.audioTracks.numTracks, 1, seq.audioTracks.numTracks, 0, 0, 0);
  function qeItem(qt, rec){ for (var i = 0; i < qt.numItems; i++){ var x = qt.getItemAt(i);
      if (String(x.type) !== "Clip") continue;
      var s = (x.start && x.start.secs !== undefined) ? Number(x.start.secs) : Number(x.start.seconds);
      if (Math.abs(s - rec * tpf / 254016000000) < 0.02) return x; } return null; }
  for (var k = 0; k < planos.length; k++) { var p = planos[k], it = item(p.arq);
    it.setInPoint(String(p.ent), 4); it.setOutPoint(String(p.ent + p.dur * tpf), 4);
    if (p.trilha == "av") seq.videoTracks[0].overwriteClip(it, String(p.rec * tpf));
    else seq.audioTracks[2].overwriteClip(it, String(p.rec * tpf));
    if (p.vel !== 1 || p.rev) {
      var alvos = p.trilha == "av" ? [q.getVideoTrackAt(0), q.getAudioTrackAt(0)] : [q.getAudioTrackAt(2)];
      for (var a = 0; a < alvos.length; a++) { var x = qeItem(alvos[a], p.rec);
        try { log.push(p.rot + " " + a + " " + (x ? x.setSpeed(p.vel, "", p.rev, true, false) : "sem item")); }
        catch (e) { log.push(p.rot + " ERRO " + e); } }
    }
  }
  pr.save();
  return {log: log, id: seq.sequenceID};
})(%s, %s, %s, %s, %s, %s)'''


def montar() -> None:
    from lab.bancadas import premiere as pr
    n = 1
    while (PASTA / f"B33 SOM PREMIERE v{n:02d}.prproj").exists():
        n += 1
    proj = PASTA / f"B33 SOM PREMIERE v{n:02d}.prproj"
    shutil.copyfile(VAZIO, proj)
    planos = [{"rot": rot, "arq": str(arq), "trilha": tr, "ent": ENTRADA * TPF, "dur": DUR, "rec": gravacao(i),
               "vel": vel, "rev": rev} for i, (rot, arq, tr, vel, rev) in enumerate(CASOS)]
    r = pr.executar(JS % tuple(json.dumps(x, ensure_ascii=False) for x in (str(proj), str(AV), str(WAV), planos, SEQ,
                                                                           TPF)), timeout=900)
    print(proj, json.dumps(r, ensure_ascii=False))
    out = PASTA / (proj.stem + ".mov")
    print(pr.executar("""(function(){ app.project.openSequence(%s);
        return app.project.activeSequence.exportAsMediaDirect(%s, %s, 0); })()""" % (
        json.dumps(r["id"]), json.dumps(str(out)), json.dumps(pr.preset_prores("2026"))), timeout=900), out)


def _som(arq: str) -> np.ndarray:
    n = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                   "-of", "json", arq], capture_output=True, text=True).stdout)["streams"]
    filtro = (f"{''.join(f'[0:a:{i}]' for i in range(len(n)))}amix=inputs={len(n)}:normalize=0[m]"
              if len(n) > 1 else "[0:a:0]anull[m]")
    return np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", arq, "-filter_complex", filtro, "-map", "[m]",
                                         "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout,
                         np.float32)


def _posicoes(x: np.ndarray) -> np.ndarray:
    """A posição da FONTE (s) a cada 10 ms, pela frequência instantânea (a fase do sinal analítico)."""
    if len(x) < SR // 10 or np.abs(x).max() < 1e-3:
        return np.array([])
    n = len(x)
    X = np.fft.fft(x)
    h = np.zeros(n)
    h[0] = 1
    h[1:(n + 1) // 2] = 2
    if n % 2 == 0:
        h[n // 2] = 1
    fase = np.unwrap(np.angle(np.fft.ifft(X * h)))
    passo = SR // 100
    f = np.diff(fase[::passo]) * SR / passo / (2 * np.pi)
    return (np.abs(f) - 500.0) / 100.0


def medir(arq: str) -> dict:
    som = _som(arq)
    tpf_s = 1001 / 24000
    out = {"arquivo": arq, "casos": []}
    for i, c in enumerate(CASOS):
        a, b = round(gravacao(i) * tpf_s * SR), round((gravacao(i) + DUR) * tpf_s * SR)
        p = _posicoes(som[a + SR // 20: b - SR // 20])        # sem as bordas (o corte borra a fase)
        if not len(p):
            out["casos"].append({"rot": c[0], "silencio": True})
            continue
        t = np.arange(len(p)) * 0.01 + 0.05
        k = 7                                                  # mediana de 15 pontos: tira os picos da fase
        p = np.array([np.median(p[max(0, j - k): j + k + 1]) for j in range(len(p))])
        ok = np.ones(len(p), bool)
        for _ in range(3):                                     # o ajuste sem os pontos fora da reta (as emendas)
            incl, ini = np.polyfit(t[ok], p[ok], 1)
            res = np.abs(p - (ini + incl * t))
            ok = res < max(0.02, 3 * np.median(res[ok]))
        out["casos"].append({"rot": c[0], "inicio_s": round(float(ini), 3), "fim_s": round(float(ini + incl * 4.004), 3),
                             "velocidade": round(float(incl), 3), "erro_ms": round(float(np.std((p - (ini + incl * t))[ok]) * 1000), 1),
                             "fora": int((~ok).sum())})
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "montar":
        montar()
    elif sys.argv[1] == "medir":
        r = medir(sys.argv[2])
        Path(sys.argv[2] + ".som.json").write_text(json.dumps(r, ensure_ascii=False))
        for c in r["casos"]:
            print(c)
    elif sys.argv[1] == "comparar":
        a, b = (json.loads(Path(x).read_text()) for x in sys.argv[2:4])
        for x, y in zip(a["casos"], b["casos"]):
            print(f"{x['rot']:<16} verdade {x.get('inicio_s')}→{x.get('fim_s')} v{x.get('velocidade')}   "
                  f"outra {y.get('inicio_s')}→{y.get('fim_s')} v{y.get('velocidade')} (erro {y.get('erro_ms')} ms)")
