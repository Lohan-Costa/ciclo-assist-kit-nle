"""Mede o tom de cada trilha de som do export do MC, trecho a trecho, e compara com o canal que a trilha deveria tocar
(lab: verdade.json, hz por canal). Uso: ouvido_medir.py <export.mxf> <_SEQ.avb> <nome da sequência>"""
import json, subprocess, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, "motor")
from avb_export.reader import topen
LAB = Path("/Volumes/SSD/PROGRAMAS COM CLAUDE/laboratorio-de-midia/saida/base")
HZ = {}
for v in LAB.glob("B03*/verdade.json"):
    for a in json.load(open(v))["arquivos"]:
        hz = [c["hz"] for t in a.get("audio", []) for c in t["canais"]]
        for k in (a["arquivo"], Path(a["arquivo"]).stem):
            if k in HZ and HZ[k] != hz:
                HZ[k] = None                      # ambíguo entre receitas
            else:
                HZ.setdefault(k, hz)
mxf, avb, nome = sys.argv[1:4]
SPF = 48000 * 1001 / 24000                       # amostras por quadro a 23,976
with topen(avb) as f:
    mobs = {str(m.mob_id): m for m in f.content.mobs}
    seq = next(m for m in f.content.mobs if getattr(m, "mob_type", "") == "CompositionMob" and m.name == nome)
    trilhas = []
    for t in seq.tracks:
        if getattr(t.component, "media_kind", "") != "sound":
            continue
        pos, segs = 0, []
        for c in getattr(t.component, "components", [t.component]):
            L = int(getattr(c, "length", 0) or 0)
            if type(c).__name__ == "SourceClip" and str(getattr(c, "mob_id", "")) in mobs:
                segs.append((pos, L, mobs[str(c.mob_id)].name, c.track_id))
            elif type(c).__name__ != "Filler":
                segs.append((pos, L, type(c).__name__, None))
            pos += L
        trilhas.append((t.index, pos, segs))
info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", mxf], capture_output=True, text=True).stdout)
auds = [s for s in info["streams"] if s["codec_type"] == "audio"]
print(f"{Path(mxf).name}: {len(auds)} trilhas de som no export, {len(trilhas)} na sequência")
def ler(i):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mxf, "-map", f"0:a:{i}", "-ac", "1", "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)
def tom(x):
    if len(x) < 2048:
        return None, -200
    db = 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)
    w = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / 48000)[int(np.argmax(w))]), db
falhas = 0
x = ler(0)                                         # a mistura (as duas trilhas do export saem iguais, no centro)
cortes = sorted({0, int(len(x) / SPF)} | {p for _, _, segs in trilhas for (p, L, _, _) in segs} |
                {p + L for _, _, segs in trilhas for (p, L, _, _) in segs})
for a0, b0 in zip(cortes, cortes[1:]):
    if b0 - a0 < 4:
        continue
    esperado = {}
    for idx, _, segs in trilhas:
        for (p, L, n, slot) in segs:
            if p <= a0 and b0 <= p + L and n:
                lista = HZ.get(n) or HZ.get(Path(n).stem)
                esperado[f"A{idx}"] = (lista[slot - 1] if lista and slot and slot <= len(lista) else None, n, slot)
    a, b = int((a0 + (b0 - a0) * 0.2) * SPF), int((a0 + (b0 - a0) * 0.8) * SPF)
    seg = x[a:b].astype(np.float64)
    # as CLAQUES do lab (1 ms por segundo de TC) sujam o espectro: o maior trecho sem salto brusco entre amostras
    salto = np.flatnonzero(np.abs(np.diff(seg)) > 0.12)
    bordas = [0] + [int(i) for i in salto] + [len(seg)]
    i0, i1 = max(zip(bordas, bordas[1:]), key=lambda ab: ab[1] - ab[0])
    seg = seg[i0 + 240:i1 - 240] if i1 - i0 > 4800 else seg[i0:i1]
    N = len(seg)
    mag = np.abs(np.fft.rfft(seg * np.hanning(N))) * 4 / N
    fr = np.fft.rfftfreq(N, 1 / 48000)
    db = 20 * np.log10(mag + 1e-12)
    picos = [(round(float(fr[i])), round(float(db[i]), 1)) for i in range(1, len(db) - 1)
             if db[i] > -45 and db[i] >= db[i - 1] and db[i] >= db[i + 1]]
    achados = {h for h, _ in picos}
    alvos = {h for h, _, _ in esperado.values() if h}
    faltam = {h for h in alvos if not any(abs(h - f) <= 5 for f in achados)}
    sobram = {f for f in achados if not any(abs(h - f) <= 5 for h in alvos)}
    ok = not faltam and not sobram and all(h for h, _, _ in esperado.values())
    falhas += not ok
    desc = ", ".join(f"{k}={h or '?'}Hz(c{s})" for k, (h, n, s) in sorted(esperado.items(), key=lambda kv: int(kv[0][1:]))) or "silêncio"
    print(f"  {'ok' if ok else 'XX'}  q{a0:>4}-{b0:<4} esperado {desc}")
    print(f"        medido ({N/48000:.2f} s limpos) {sorted(picos)}" + (f"  FALTAM {sorted(faltam)}" if faltam else "") + (f"  SOBRAM {sorted(sobram)}" if sobram else ""))
print("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)
