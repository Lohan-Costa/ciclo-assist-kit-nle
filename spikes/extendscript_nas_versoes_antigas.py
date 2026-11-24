"""O ExtendScript monta uma timeline nas versões SEM o MCP nativo (Premiere 2025/2026)?

Roteiro para `spikes/no_servico.py` (a ponte CEP fala com o processo do serviço):

    CICLO_ANO=2026 CICLO_MIDIA=<pasta com sint_*.mov e tons5.wav> CICLO_SAIDA=<pasta> \
        .venv/bin/python spikes/no_servico.py spikes/extendscript_nas_versoes_antigas.py

Mede, com os clipes sintéticos (nº do quadro em barras; um tom por canal):
  A. inserção de 3 pontos (`setInPoint`/`setOutPoint` + `overwriteClip`) — o quadro que ENTRA, por
     leitura de volta (ticks) e na IMAGEM (`exportFramePNG` do QE);
  B. quantos CANAIS de um WAV 5.0 chegam (insert numa sequência de vídeo; sequência a partir do clipe);
  C. a navalha do QE (`razor`) — onde corta;
  D. inserir na trilha 2 (trilha alvo) e o `insertClip` (ripple).

⛔ DESENVOLVIMENTO: entrega expressão CRUA à ponte (o produto só chama funções do `host.jsx`).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from fractions import Fraction
from pathlib import Path

from cicloassist import premiere_app
from cicloassist.nle.premiere import ponte

ANO = os.environ.get("CICLO_ANO", "2026")
MIDIA = Path(os.environ["CICLO_MIDIA"])
SAIDA = Path(os.environ["CICLO_SAIDA"]); SAIDA.mkdir(parents=True, exist_ok=True)
TICKS = 254016000000


def cru(expr: str, prazo: float = 120) -> object:
    """Roda uma expressão ExtendScript que DEVOLVE texto JSON (use `cicloJ`)."""
    p = ponte._Pedido(id=f"cru{time.monotonic_ns()}", expr=expr)
    with ponte._trava:
        ponte.enfileirar(p); ponte._esperando[p.id] = p; ponte._trava.notify_all()
    if not p.pronto.wait(prazo):
        raise RuntimeError(f"sem resposta: {expr[:80]}")
    with ponte._trava:
        ponte._esperando.pop(p.id, None)
    try:
        return json.loads(p.resposta or "null")
    except ValueError:
        return p.resposta


def js(corpo: str, prazo: float = 120) -> object:
    """Corpo de função ExtendScript; o `return` dele volta como JSON."""
    return cru("cicloJ((function(){try{" + corpo + "}catch(e){return {erro: String(e), linha: e.line};}})())", prazo)


rel: dict = {"ano": ANO}

# ── abrir o Premiere da versão pedida, com um projeto NOVO ─────────────────────────────────────
projeto = SAIDA / f"ANTIGAS {ANO}.prproj"
t = time.monotonic()
r = premiere_app.abrir(str(projeto), versao=ANO, prazo=240)
rel["abrir"] = {**r, "s": round(time.monotonic() - t, 1)}
print("abrir:", rel["abrir"])
rel["versao"] = js("return String(app.version);")
print("versão:", rel["versao"])

arquivos = [str(MIDIA / n) for n in ("sint_23976.mov", "sint_25.mov", "sint_2997df.mov", "tons5.wav")]
js("app.project.importFiles(" + json.dumps(arquivos) + ", true, app.project.rootItem, false); return 1;")
js('''
  $.global.cicloF = {};
  var r = app.project.rootItem;
  for (var i = 0; i < r.children.numItems; i++) { var c = r.children[i]; $.global.cicloF[c.name] = c; }
  return 1;''')

PNG = str(SAIDA / "q_%s_%d")   # ⚠️ o exportFramePNG do QE ACRESCENTA ".png" sozinho


def quadro_png(caminho: str) -> int | None:
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return None
    im = Image.open(caminho).convert("L"); w, h = im.size
    n = 0
    for k in range(12):
        if im.getpixel((int((k + 0.5) * w / 12), h // 2)) > 128:
            n |= 1 << k
    return n


# ── A. 3 pontos: entrada/saída no clipe + overwriteClip, lidos de volta e na imagem ─────────────
rel["insercao"] = []
for nome, fps in (("sint_23976.mov", Fraction(24000, 1001)), ("sint_25.mov", Fraction(25)),
                  ("sint_2997df.mov", Fraction(30000, 1001))):
    seq = f"ES {nome}"
    js(f'''
      var it = $.global.cicloF["{nome}"];
      var s = app.project.createNewSequenceFromClips("{seq}", [it], app.project.rootItem);
      // esvazia: a sequência nasce com o clipe inteiro
      for (var t = 0; t < s.videoTracks.numTracks; t++) {{ var tr = s.videoTracks[t];
        for (var c = tr.clips.numItems - 1; c >= 0; c--) tr.clips[c].remove(false, false); }}
      for (var t = 0; t < s.audioTracks.numTracks; t++) {{ var tr = s.audioTracks[t];
        for (var c = tr.clips.numItems - 1; c >= 0; c--) tr.clips[c].remove(false, false); }}
      $.global.cicloSeq = s; app.project.activeSequence = s; return 1;''')
    pos = 0
    for forma in ("exato", "exato+1us", "meio_quadro"):
        for n in (1, 47, 48, 121):
            base = Fraction(n) / fps
            seg = {"exato": float(base), "exato+1us": float(base) + 1e-6,
                   "meio_quadro": float((Fraction(n) + Fraction(1, 2)) / fps)}[forma]
            seg_fim = seg + float(Fraction(12) / fps)
            posicao = float(Fraction(pos) / fps) + (1e-6 if forma != "exato" else 0)
            d = js(f'''
              var it = $.global.cicloF["{nome}"], s = $.global.cicloSeq;
              it.setInPoint({seg!r}, 4); it.setOutPoint({seg_fim!r}, 4);
              s.videoTracks[0].overwriteClip(it, {posicao!r});
              var tr = s.videoTracks[0], achado = null;
              for (var c = 0; c < tr.clips.numItems; c++) {{
                var k = tr.clips[c]; if (Math.abs(k.start.seconds - {posicao!r}) < 0.02) achado = k; }}
              if (!achado) return {{erro: "não achei o pedaço"}};
              return {{in_ticks: String(achado.inPoint.ticks), start_ticks: String(achado.start.ticks),
                       dur_ticks: String(achado.duration.ticks)}};''')
            if "erro" in d:
                rel["insercao"].append({"clipe": nome, "forma": forma, "n": n, "erro": d}); pos += 12; continue
            entrou = Fraction(int(d["in_ticks"]), TICKS) * fps
            png = PNG % (nome[5:-4] + forma, n)
            tc_pos = float(Fraction(pos) / fps + Fraction(1, 4) / fps)
            js(f'''
              app.enableQE(); var q = qe.project.getActiveSequence();
              var t = new Time(); t.seconds = {tc_pos!r};
              q.exportFramePNG(t.getFormatted($.global.cicloSeq.getSettings().videoFrameRate, $.global.cicloSeq.getSettings().videoDisplayFormat), "{png}");
              return 1;''', prazo=60)
            time.sleep(0.6)
            visto = quadro_png(png + ".png") if Path(png + ".png").exists() else None
            rel["insercao"].append({"clipe": nome, "forma": forma, "n": n, "in_lido": round(float(entrou), 3),
                                    "dur_lida": round(float(Fraction(int(d["dur_ticks"]), TICKS) * fps), 3),
                                    "na_imagem": visto})
            pos += 12
certos: dict = {}
for x in rel["insercao"]:
    if "in_lido" in x:
        certos.setdefault((x["clipe"], x["forma"]), []).append((abs(x["in_lido"] - x["n"]) < 0.01,
                                                                x["na_imagem"] == x["n"] if x["na_imagem"] is not None else None))
for (c, f), v in certos.items():
    print(f"A {c:16s} {f:12s} lido {sum(1 for a, _ in v if a)}/{len(v)}  imagem "
          f"{sum(1 for _, b in v if b)}/{len([1 for _, b in v if b is not None])}")

# ── B. os canais do WAV 5.0 ─────────────────────────────────────────────────────────────────────
preset = next(Path(f"/Applications/Adobe Premiere Pro {ANO}").glob("**/EncoderPresets/Wave48mono16.epr"), None)
rel["canais"] = {}
for caso in ("insert_em_seq_de_video", "seq_do_clipe"):
    out = str(SAIDA / f"{caso}.wav")
    if caso == "insert_em_seq_de_video":
        corpo = '''
          var s = app.project.createNewSequenceFromClips("ES WAV INSERT", [$.global.cicloF["sint_25.mov"]], app.project.rootItem);
          for (var t = 0; t < s.audioTracks.numTracks; t++) { var tr = s.audioTracks[t];
            for (var c = tr.clips.numItems - 1; c >= 0; c--) tr.clips[c].remove(false, false); }
          var w = $.global.cicloF["tons5.wav"];
          s.audioTracks[0].overwriteClip(w, 0);'''
    else:
        corpo = '''
          var w = $.global.cicloF["tons5.wav"];
          var s = app.project.createNewSequenceFromClips("ES WAV SEQ", [w], app.project.rootItem);'''
    d = js(corpo + f'''
          var itens = [];
          for (var t = 0; t < s.audioTracks.numTracks; t++)
            itens.push(s.audioTracks[t].clips.numItems);
          app.project.activeSequence = s;
          var ok = s.exportAsMediaDirect("{out}", "{preset}", 0);
          return {{trilhas_com_clipe: itens, export: String(ok)}};''', prazo=180)
    time.sleep(1)
    tons = None
    if Path(out).exists():
        import numpy as np  # noqa: PLC0415
        x = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                                         capture_output=True).stdout, dtype=np.float32)[24000:72000]
        if len(x):
            s_ = np.abs(np.fft.rfft(x)); f_ = np.fft.rfftfreq(len(x), 1 / 48000)
            tons = {hz: round(float(s_[(abs(f_ - hz)).argmin()] / s_.max()), 2) for hz in (100, 200, 300, 400, 440, 500)}
    rel["canais"][caso] = {**(d if isinstance(d, dict) else {"r": d}), "tons": tons}
    print("B", caso, rel["canais"][caso])

# ── C. a navalha do QE ─────────────────────────────────────────────────────────────────────────
d = js('''
  var it = $.global.cicloF["sint_25.mov"]; it.clearInPoint(); it.clearOutPoint();
  var s = app.project.createNewSequenceFromClips("ES NAVALHA", [it], app.project.rootItem);
  app.project.activeSequence = s; app.enableQE();
  var q = qe.project.getActiveSequence();
  var fr = s.getSettings().videoFrameRate, fmt = s.getSettings().videoDisplayFormat;
  var t1 = new Time(); t1.seconds = 2.0; var t2 = new Time(); t2.seconds = 4.0 + 0.5/25;
  q.getVideoTrackAt(0).razor(t1.getFormatted(fr, fmt));
  q.getAudioTrackAt(0).razor(t2.getFormatted(fr, fmt));
  var v = [], a = [];
  for (var c = 0; c < s.videoTracks[0].clips.numItems; c++) v.push(s.videoTracks[0].clips[c].start.seconds);
  for (var c = 0; c < s.audioTracks[0].clips.numItems; c++) a.push(s.audioTracks[0].clips[c].start.seconds);
  return {video: v, audio: a, tc_meio: t2.getFormatted(fr, fmt)};''')
rel["navalha"] = d
print("C navalha:", d)

# ── D. trilha alvo e insertClip (ripple) ─────────────────────────────────────────────────────────
d = js('''
  var it = $.global.cicloF["sint_25.mov"]; it.setInPoint(4.0 + 1e-6, 4); it.setOutPoint(5.0 + 1e-6, 4);
  var s = $.global.cicloSeq;
  var antes = s.videoTracks[0].clips.numItems;
  s.videoTracks[1].overwriteClip(it, 0.000001);
  var v2 = s.videoTracks[1].clips.numItems;
  s.videoTracks[0].insertClip(it, 0.000001);
  var depois = s.videoTracks[0].clips.numItems, primeiro = s.videoTracks[0].clips[1].start.seconds;
  var a = []; for (var t = 0; t < s.audioTracks.numTracks; t++) a.push(s.audioTracks[t].clips.numItems);
  return {v1_antes: antes, v1_depois: depois, v2: v2, segundo_pedaco_v1_em: primeiro, audio_por_trilha: a};''')
rel["trilha_e_insert"] = d
print("D:", d)

(SAIDA / f"relatorio_{ANO}.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1, default=str))
js("app.project.save(); return 1;")
print("relatório:", SAIDA / f"relatorio_{ANO}.json")
