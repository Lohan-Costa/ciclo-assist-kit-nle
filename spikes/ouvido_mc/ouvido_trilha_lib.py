import subprocess
import numpy as np
def tons(arq):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", arq, "-map", "0:a:0", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).astype(float)
    SPF = 2002
    out = []
    for q in range(0, int(len(x) / SPF) - 12, 24):          # meio segundo por vez
        seg = x[q * SPF:(q + 24) * SPF]
        salto = np.flatnonzero(np.abs(np.diff(seg)) > 0.12)
        b = [0] + [int(i) for i in salto] + [len(seg)]
        i0, i1 = max(zip(b, b[1:]), key=lambda ab: ab[1] - ab[0])
        seg = seg[i0 + 120:i1 - 120]
        if len(seg) < 4800:
            continue
        mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) * 4 / len(seg)
        fr = np.fft.rfftfreq(len(seg), 1 / 48000); db = 20 * np.log10(mag + 1e-12)
        pk = sorted({(round(float(fr[i]) / 10) * 10, round(float(db[i]))) for i in range(1, len(db) - 1)
                     if db[i] > -45 and db[i] >= db[i - 1] and db[i] >= db[i + 1]})
        out.append((q, pk))
    return out

