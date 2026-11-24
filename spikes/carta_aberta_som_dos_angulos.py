"""Spike — Carta Aberta: o SOM de cada ângulo do group clip escrito por nós, medido no que o MC EXPORTA.

    python spikes/carta_aberta_som_dos_angulos.py <export .mxf> [<export .mxf> ...] [--lab <pasta G01_GRUPO_23976>]

Cada export é o `ExportFile` (preset do laboratório, MXF DNxHR LB com áudio) de um group clip G01 com um ângulo
escolhido. Para cada trilha de som do export:
- o TOM PILOTO diz de que fonte veio (laboratório: CAM 1 300 Hz, CAM 2 2000, CAM 3 3700, som direto 5400);
- a CORRELAÇÃO com a cena (`_cena.wav`) diz em que instante da cena o export começa; o certo, para a câmera k, é
  `início do grupo na cena − atraso_k` (o grupo começa no 1º quadro da fonte mais cedo — a CAM 1, 5,0 s).
O desvio em ms é o erro de sincronia do som daquele ângulo (1 quadro a 23,976 = 41,7 ms).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 48000
TONS = {"CAM 1": 300, "CAM 2": 2000, "CAM 3": 3700, "SOM DIRETO": 5400}
JANELA = (10.0, 20.0)  # segundos do grupo em que as três câmeras e o som têm material


def ler_trilhas(arquivo: str) -> list[np.ndarray]:
    sonda = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", arquivo],
                                      capture_output=True, text=True, check=True).stdout)
    trilhas = []
    for s in sonda["streams"]:
        if s["codec_type"] != "audio":
            continue
        bruto = subprocess.run(["ffmpeg", "-v", "error", "-i", arquivo, "-map", f"0:{s['index']}", "-ac", "1",
                                "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
        trilhas.append(np.frombuffer(bruto, dtype=np.float32))
    return trilhas


def ler_wav(arquivo: str) -> np.ndarray:
    bruto = subprocess.run(["ffmpeg", "-v", "error", "-i", arquivo, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                           capture_output=True, check=True).stdout
    return np.frombuffer(bruto, dtype=np.float32)


def tom(x: np.ndarray) -> dict[str, float]:
    """Energia (dB) de cada tom piloto, numa FFT da janela."""
    esp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return {n: round(20 * np.log10(esp[(f > hz - 3) & (f < hz + 3)].max() + 1e-12), 1) for n, hz in TONS.items()}


def onde_na_cena(x: np.ndarray, cena: np.ndarray, palpite_s: float, busca_s: float = 2.0) -> float:
    """Instante da cena (s) que casa com o começo de `x` (correlação por FFT perto do palpite)."""
    a = max(0, int((palpite_s - busca_s) * SR))
    b = min(len(cena), int((palpite_s + busca_s) * SR) + len(x))
    trecho = cena[a:b].astype(np.float64)
    xx = (x - x.mean()).astype(np.float64)
    n = 1 << int(np.ceil(np.log2(len(trecho) + len(xx))))
    c = np.fft.irfft(np.fft.rfft(trecho, n) * np.conj(np.fft.rfft(xx, n)), n)[: len(trecho) - len(xx) + 1]
    return (a + int(np.argmax(c))) / SR


def main(argv: list[str]) -> int:
    lab = Path("/Volumes/SSD/MIDIAS DE TESTES/3 CONJUNTOS DOS APPS/_CICLO ASSIST/carta_aberta/G01_GRUPO_23976")
    if "--lab" in argv:
        i = argv.index("--lab"); lab = Path(argv[i + 1]); del argv[i:i + 2]
    verdade = json.loads((lab / "verdade.json").read_text(encoding="utf-8"))
    atraso = {a["fonte"]: (a.get("atraso_ms") or 0) / 1000 for a in verdade["arquivos"]}
    inicio_do_grupo = min(a["inicio_na_cena_s"] for a in verdade["arquivos"] if not a["som"])
    cena = ler_wav(str(lab / "_cena.wav"))
    for arq in argv:
        print(f"== {Path(arq).name}")
        for k, x in enumerate(ler_trilhas(arq), 1):
            j = x[int(JANELA[0] * SR): int(JANELA[1] * SR)]
            energias = tom(j)
            fonte = max(energias, key=energias.get)
            achado = onde_na_cena(j, cena, inicio_do_grupo + JANELA[0]) - JANELA[0]
            certo = inicio_do_grupo - atraso.get(fonte, 0)
            print(f"  A{k}: tom de {fonte:10} ({energias})  começa na cena em {achado:.4f} s, o certo {certo:.4f} s"
                  f" → desvio {1000 * (achado - certo):+.1f} ms")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))


def sequencia_do_grupo(bin_do_grupo: str, saida: str, nome: str) -> str:
    """Bin NOVA com uma sequência de UM segmento apontando o group clip inteiro (V1 + os sons dele) e o grupo no fecho,
    oculto. ⚠️ `ExportFile` de um group clip responde "Completed" e não grava nada (MC 25.12 Mac, 2026-11-12) — a
    sequência é o que se exporta."""
    import avb
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import cicloassist.avid  # noqa: F401
    from cicloassist.avid import timeline as T
    with avb.open(bin_do_grupo) as f:
        g = next(i.mob for i in f.content.items if i.user_placed and getattr(i.mob, "usage", None) == "group")
        trilhas = tuple((t.component.media_kind, t.index) for t in g.tracks)
        dur, taxa, mob = g.tracks[0].component.length, g.tracks[0].component.edit_rate, str(g.mob_id)
    T.escrever_bin(saida, [(nome, [T.Entrada(mob_id=mob, duracao=dur, trilhas=trilhas, start_time=0)])],
                   float(taxa), base=bin_do_grupo)
    return saida
