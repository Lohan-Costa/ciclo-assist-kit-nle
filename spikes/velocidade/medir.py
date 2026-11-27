"""Mede uma saída da B32 (o render do Premiere, o export do MC) caso a caso: o QUADRO da mídia em cada quadro da
sequência (o código de barras do laboratório), o TOM do som e as CLAQUES; e compara duas medidas.

    .venv/bin/python spikes/velocidade/medir.py <saida.mov|.mxf> [--inicio Q]       → grava <saida>.medida.json
    .venv/bin/python spikes/velocidade/medir.py --comparar <verdade.medida.json> <outra.medida.json>

`--inicio`: o quadro do arquivo onde a sequência começa (0 no render do Premiere e no export do MC da sequência).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import casos as C  # noqa: E402

sys.path.insert(0, str(C.LAB))
from lab import ler  # noqa: E402

SR = 48000


def _tamanho(arq: str) -> tuple[int, int]:
    s = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "json", arq], capture_output=True, text=True).stdout)
    return int(s["streams"][0]["width"]), int(s["streams"][0]["height"])


def _total(arq: str) -> int:
    s = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                                   "stream=nb_read_packets", "-of", "json", arq], capture_output=True, text=True).stdout)
    return int(s["streams"][0]["nb_read_packets"])


def _som(arq: str) -> np.ndarray:
    """A mistura de TODAS as trilhas de som, mono, 48 kHz."""
    n = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                   "-of", "json", arq], capture_output=True, text=True).stdout)["streams"]
    if not n:
        return np.zeros(0, np.float32)
    filtro = (f"{''.join(f'[0:a:{i}]' for i in range(len(n)))}amix=inputs={len(n)}:normalize=0[m]"
              if len(n) > 1 else "[0:a:0]anull[m]")
    bruto = subprocess.run(["ffmpeg", "-v", "error", "-i", arq, "-filter_complex", filtro, "-map", "[m]", "-ac", "1",
                            "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(bruto, np.float32)


def _tons(x: np.ndarray) -> list[int]:
    x = x.copy()
    x[np.abs(x) > 0.5] = 0                         # sem as claques
    if len(x) < 2048:
        return []
    f = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    hz = np.fft.rfftfreq(len(x), 1 / SR)
    picos = [int(round(hz[i] / 10) * 10) for i in np.argsort(f)[-12:] if f[i] > f.max() * 0.25]
    return sorted(set(picos))


def _claques(x: np.ndarray) -> list[float]:
    alto = np.flatnonzero(np.abs(x) > 0.5)
    fora: list[float] = []
    for i in alto:
        t = i / SR
        if not fora or t - fora[-1] > 0.05:
            fora.append(round(t, 3))
    return fora


def medir(arq: str, inicio: int = 0) -> dict:
    try:
        w, h = _tamanho(arq)
        total = _total(arq)
    except (IndexError, KeyError):                  # só som (o MC exporta as trilhas SELECIONADAS no patching)
        w = h = total = 0
    tpf_s = 1001 / 24000
    som = _som(arq)
    saida = {"arquivo": arq, "casos": []}
    for i, (rot, m, vel, tom) in enumerate(C.CASOS):
        rec = inicio + C.gravacao(i)
        idx = [q for q in range(rec, rec + C.DUR) if q < total]
        imgs = ler.quadros_cinza(arq, idx, w, h) if idx else {}
        quadros = [ler.ler_faixas(imgs[q], w, h)[0] for q in idx] + [None] * (C.DUR - len(idx))
        a, b = round(C.gravacao(i) * tpf_s * SR), round((C.gravacao(i) + C.DUR) * tpf_s * SR)
        trecho = som[a:b] if len(som) else som
        saida["casos"].append({"rot": rot, "quadros": quadros, "tons": _tons(trecho), "claques": _claques(trecho)})
    return saida


def comparar(v: dict, o: dict) -> list[dict]:
    fora = []
    for cv, co in zip(v["casos"], o["casos"]):
        q1, q2 = cv["quadros"], co["quadros"]
        dif = [k for k, (x, y) in enumerate(zip(q1, q2)) if x != y]
        fora.append({"caso": cv["rot"], "quadros_iguais": f"{len(q1) - len(dif)}/{len(q1)}",
                     "1a_diferenca": (dif[0], q1[dif[0]], q2[dif[0]]) if dif else None,
                     "verdade": f"{q1[0]}→{q1[-1]}", "outra": f"{q2[0]}→{q2[-1]}",
                     "tons": (cv["tons"], co["tons"]), "claques": (cv["claques"], co["claques"])})
    return fora


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "--comparar":
        v, o = (json.loads(Path(p).read_text()) for p in sys.argv[2:4])
        for linha in comparar(v, o):
            print(json.dumps(linha, ensure_ascii=False))
    else:
        ini = int(sys.argv[sys.argv.index("--inicio") + 1]) if "--inicio" in sys.argv else 0
        r = medir(sys.argv[1], ini)
        Path(sys.argv[1] + ".medida.json").write_text(json.dumps(r, ensure_ascii=False))
        for c in r["casos"]:
            q = c["quadros"]
            print(f"{c['rot']:<14} {q[0]}→{q[-1]} passos {sorted(set(b - a for a, b in zip(q, q[1:]) if a is not None and b is not None))}  "
                  f"tons {c['tons']}  claques {c['claques']}")
