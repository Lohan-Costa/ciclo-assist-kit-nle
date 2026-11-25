"""O "ouvido" do corte: junta o som real dos planos, transcreve o resultado e procura palavra repetida em cada emenda.

    python spikes/edicao_de_cena/ouvir_o_corte.py "<pasta da saída>"

Foi o autor assistindo que achou "…fissional" e "comigo" repetidos (2026-11-09). Só lê; usa o mesmo ASR do produto.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unicodedata
import wave
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import cicloassist.avid  # noqa: E402,F401
from cicloassist.avid.take import resolver  # noqa: E402
from cicloassist.midia import asr as _asr, audio as _audio  # noqa: E402

BIN = r"%USERPROFILE%\Documents\Avid Projects\PRODUCAO-A_CURTA\CENAS\C07.avb"
JANELA_S = 3.0


def normal(p: str) -> str:
    return re.sub(r"\W", "", unicodedata.normalize("NFD", p.lower()).encode("ascii", "ignore").decode())


def montar_som(planos: list[dict], pasta: Path) -> tuple[Path, list[float]]:
    wavs: dict[str, Path] = {}
    saida = pasta / "corte.wav"
    emendas, total = [], 0.0
    with wave.open(str(saida), "wb") as out:
        parametros = False
        for p in planos:
            t = resolver(BIN, p["take"])
            if p["take"] not in wavs:
                wavs[p["take"]] = _audio.mixar([str(a) for a in t.som.arquivos], pasta / f"{p['take']}.wav")
            taxa = Fraction(t.fps["num"], t.fps["den"])
            with wave.open(str(wavs[p["take"]]), "rb") as w:
                if not parametros:
                    out.setparams(w.getparams())
                    parametros = True
                sr = w.getframerate()
                a = int((t.som.inicio_s + float(p["som_ini"] / taxa)) * sr)
                n = int(float((p["som_fim"] - p["som_ini"]) / taxa) * sr)
                w.setpos(a)
                out.writeframes(w.readframes(n))
            total += n / sr
            emendas.append(total)
    return saida, emendas[:-1]


def main() -> int:
    final = json.loads((Path(sys.argv[1]) / "corte_final.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="ouvir_") as d:
        wav, emendas = montar_som(final["planos"], Path(d))
        segmentos, _ = _asr.carregar().transcribe(str(wav), language="pt", word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
        palavras = [(w.start, w.end, w.word.strip()) for s in segmentos for w in (s.words or [])]
    repeticoes = 0
    for n, e in enumerate(emendas, 1):
        antes = [w for w in palavras if e - JANELA_S <= w[1] <= e + 0.05]
        depois = [w for w in palavras if e - 0.05 <= w[0] <= e + JANELA_S]
        fim = [normal(w[2]) for w in antes][-4:]
        comeco = [normal(w[2]) for w in depois][:4]
        repetidas = [x for x in comeco[:3] if len(x) >= 3 and x in fim]
        repeticoes += bool(repetidas)
        print(f"emenda {n} em {e:6.1f} s | … {' '.join(w[2] for w in antes[-5:])}  ||  {' '.join(w[2] for w in depois[:5])} …" + (f"   ⛔ REPETE: {repetidas}" if repetidas else ""))
    print(f"\n{repeticoes} emenda(s) com repetição, de {len(emendas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
