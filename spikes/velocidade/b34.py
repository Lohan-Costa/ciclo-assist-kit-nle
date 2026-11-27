"""B34 — RAMPA e CONGELADO na volta inteira, pelo quadro em código de barras (a placa B30_A diz o quadro).

    .venv/bin/python spikes/velocidade/b34.py montar               (Premiere aberto, ponte do laboratório) → a VERDADE
    .venv/bin/python spikes/velocidade/b34.py medir <arquivo>      → <arquivo>.b34.json + o resumo
    .venv/bin/python spikes/velocidade/b34.py comparar <a.json> <b.json>

Sequência 23,976 a partir de 01:00:00:00; três planos de 48 quadros (só imagem), 24 de vazio entre eles. O Time Remapping
vai escrito no XML pela peça do app (`modulos/conformar/motor/prproj/remap.py`, a forma provada no B22): monta pela API,
salva, fecha, escreve a curva, reabre e renderiza.

  R1 — 12 quadros a 100 %, 12 acelerando até 200 %, 24 a 200 %          (entrada 48)
  R2 — começa DENTRO da curva: 200 % → 60 % nos quadros 0–20, depois 60 %  (entrada 60)
  R3 — congelado no quadro 120 da mídia
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
APP = AQUI.parents[1]
sys.path[:0] = [str(AQUI), str(APP)]
import casos as C  # noqa: E402

sys.path.insert(0, str(C.LAB))
PASTA = C.PASTA.parent / "2026-11-26 RAMPAS B34"
SEQ, TPS = "B34 RAMPAS", 254016000000
TPF = TPS * 1001 // 24000
Q = 1001 / 24000
N, VAO = 48, 24
MIDIA = C.A[0]


def _pos_r1():
    p = [48.0 + k for k in range(13)]
    for k in range(1, 13):
        p.append(p[-1] + 1 + k / 12)
    while len(p) < N:
        p.append(p[-1] + 2)
    return p[:N]


def _pos_r2():
    p = [60.0]
    for k in range(1, N):
        v = 2.0 - (2.0 - 0.6) * min(k, 20) / 20
        p.append(p[-1] + v)
    return p


CASOS = [("R1 rampa 100-200", _pos_r1()), ("R2 comeca na curva", _pos_r2()), ("R3 congelado", [120.0] * N)]


def gravacao(i: int) -> int:
    return i * (N + VAO)


def _remap():
    arq = APP / "modulos" / "conformar" / "motor" / "prproj" / "remap.py"
    spec = importlib.util.spec_from_file_location("b34_remap", arq)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


JS = r'''(function(proj, arq, planos, nomeSeq, tpf){
  for (var x = app.projects.numProjects - 1; x >= 0; x--) app.projects[x].closeDocument(true, false);
  app.openDocument(proj, true, true, true, true);
  var pr = null; for (var i = 0; i < app.projects.numProjects; i++) if (app.projects[i].path == proj) pr = app.projects[i];
  if (!pr) return {erro: "não abriu"};
  pr.importFiles([arq], true, pr.rootItem, false);
  var it = null; for (i = 0; i < pr.rootItem.children.numItems; i++) if (pr.rootItem.children[i].type != 2) it = pr.rootItem.children[i];
  var seq = pr.createNewSequenceFromClips(nomeSeq, [it], pr.rootItem), t;
  for (t = 0; t < seq.videoTracks.numTracks; t++) while (seq.videoTracks[t].clips.numItems) seq.videoTracks[t].clips[0].remove(false, false);
  for (t = 0; t < seq.audioTracks.numTracks; t++) while (seq.audioTracks[t].clips.numItems) seq.audioTracks[t].clips[0].remove(false, false);
  seq.setZeroPoint(String(86400 * tpf));
  for (var k = 0; k < planos.length; k++) { var p = planos[k];
    it.setInPoint(String(p.ent * tpf), 4); it.setOutPoint(String((p.ent + 48) * tpf), 4);
    seq.videoTracks[0].overwriteClip(it, String(p.rec * tpf)); }
  for (t = 0; t < seq.audioTracks.numTracks; t++) while (seq.audioTracks[t].clips.numItems) seq.audioTracks[t].clips[0].remove(false, false);
  pr.save();
  var r = pr.path; pr.closeDocument(true, false); return {ok: r, id: seq.sequenceID};
})(%s, %s, %s, %s, %s)'''


def montar() -> None:
    from lab.bancadas import premiere as pr
    from cicloassist.carta import entrega_prproj as EP
    rm = _remap()
    PASTA.mkdir(parents=True, exist_ok=True)
    n = 1
    while (PASTA / f"B34 RAMPAS PREMIERE v{n:02d}.prproj").exists():
        n += 1
    proj = PASTA / f"B34 RAMPAS PREMIERE v{n:02d}.prproj"
    shutil.copyfile(AQUI.parents[1] / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj", proj)
    planos = [{"ent": int(p[0]), "rec": gravacao(i)} for i, (_, p) in enumerate(CASOS)]
    print(pr.executar(JS % tuple(json.dumps(x, ensure_ascii=False) for x in (str(proj), str(MIDIA), planos, SEQ, TPF)),
                      timeout=600))
    R = EP._ler_prproj(str(proj))
    por = {EP._chave(e): e for e in R if EP._chave(e)}
    prox = [max(int(e.get("ObjectID")) for e in R if (e.get("ObjectID") or "").isdigit())]

    def novo():
        prox[0] += 1
        return str(prox[0])
    tis = sorted((e for e in R if e.tag == "VideoClipTrackItem"),
                 key=lambda e: int(e.findtext("./ClipTrackItem/TrackItem/Start") or 0))
    assert len(tis) == len(CASOS), len(tis)
    feitos = []
    for ti, (rot, pos) in zip(tis, CASOS):
        sub = por[ti.find("./ClipTrackItem/SubClip").get("ObjectRef")]
        vc = por[sub.find("Clip").get("ObjectRef")]
        cl = vc.find("Clip")
        cur = rm.de_posicoes([x * Q for x in pos], Q)
        for x in cl.findall("PlaybackSpeed"):
            cl.remove(x)
        cl.find("InPoint").text = str(round(cur["in_s"] * TPS))
        cl.find("OutPoint").text = str(round(cur["in_s"] * TPS) + N * TPF)
        id_r, id_p = novo(), novo()
        objs = rm.objetos(id_r, id_p, cur["remap"], 240 * Q)
        rm.pendurar(cl, id_r)
        i = list(R).index(vc)
        for k, o in enumerate(objs):
            R.insert(i + k, o)
        feitos.append((rot, cur["keyframes"], cur["in_s"] / Q))
    EP._gravar_prproj(R, str(proj))
    print("curvas:", feitos)
    r = pr.executar("""(function(p){ app.openDocument(p, true, true, true, true); var pr = app.project;
        for (var i = 0; i < app.projects.numProjects; i++) if (app.projects[i].path == p) pr = app.projects[i];
        var s = pr.sequences[0]; pr.openSequence(s.sequenceID); return s.sequenceID; })(%s)""" % json.dumps(str(proj)),
                    timeout=300)
    out = PASTA / (proj.stem + ".mov")
    print(pr.executar("""(function(){ var s = app.project.activeSequence;
        return s.exportAsMediaDirect(%s, %s, 0); })()""" % (json.dumps(str(out)), json.dumps(pr.preset_prores("2026"))),
                      timeout=900), out, r)


def medir(arq: str, inicio: int = 0) -> dict:
    from lab import ler
    import medir as M
    w, h = M._tamanho(arq)
    total = M._total(arq)
    out = {"arquivo": arq, "casos": []}
    for i, (rot, pos) in enumerate(CASOS):
        idx = [q for q in range(inicio + gravacao(i), inicio + gravacao(i) + N) if q < total]
        imgs = ler.quadros_cinza(arq, idx, w, h)
        lidos = [ler.ler_faixas(imgs[q], w, h)[0] for q in idx]
        out["casos"].append({"rot": rot, "quadros": lidos, "esperado": [int(p) for p in pos]})
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "montar":
        montar()
    elif sys.argv[1] == "medir":
        ini = int(sys.argv[sys.argv.index("--inicio") + 1]) if "--inicio" in sys.argv else 0
        r = medir(sys.argv[2], ini)
        Path(sys.argv[2] + ".b34.json").write_text(json.dumps(r, ensure_ascii=False))
        for c in r["casos"]:
            iguais = sum(a == b for a, b in zip(c["quadros"], c["esperado"]))
            print(f"{c['rot']:<20} piso(posição) {iguais}/{N}  {c['quadros'][:6]}…{c['quadros'][-3:]}")
    elif sys.argv[1] == "comparar":
        a, b = (json.loads(Path(x).read_text()) for x in sys.argv[2:4])
        for x, y in zip(a["casos"], b["casos"]):
            dif = [k for k, (p, q) in enumerate(zip(x["quadros"], y["quadros"])) if p != q]
            print(f"{x['rot']:<20} {N - len(dif)}/{N}" + (f"  1ª diferença q{dif[0]}: {x['quadros'][dif[0]]} × "
                                                         f"{y['quadros'][dif[0]]}" if dif else ""))
