"""L1: o CÓDIGO DO PRODUTO (midia/alinhamento.py + midia/voz.py) sobre um WAV e uma transcrição do nosso ASR.

    PYTHONPATH=. python medir_l1.py <wav multicanal ou mono> <nosso.json> <saida.json> [--chave CHAVE.json]

Mistura como o produto (`audio.mixar`, num temporário), alinha (Omnilingual, `CICLOASSIST_ALINHADOR` aponta o modelo),
mede a voz nas lapelas do iXML e grava as palavras no formato do `medir_l0.py`/`medir_real.py`: o início é o do alinhador
(ou a borda medida na pausa) e o fim é a borda medida (`voz_fim`) quando a palavra encosta numa pausa.
Com `--chave`, imprime as bordas que o autor julgou de ouvido (o valor de cada lado e o nosso de hoje).
"""
import json, resource, sys, tempfile, time
from pathlib import Path

import numpy as np

from cicloassist.midia import alinhamento as al, audio, canais, falantes, voz


def main():
    wav, fonte, saida = sys.argv[1:4]
    falas = json.load(open(fonte))["falas"]
    t = time.time()
    with tempfile.TemporaryDirectory() as d:
        mono = audio.mixar([wav], Path(d) / "audio.wav")
        x = al.carregar_som(mono)
    t_mix = time.time() - t
    t = time.time(); m = al.Modelo(); t_carga = time.time() - t
    t = time.time(); cru = al.alinhar(falas, x, m); t_al = time.time() - t
    del m
    alinhadas = al.bordas({"palavras": cru}, falas)
    tr = canais.de_ixml(wav)
    envs = {c: np.asarray(e, np.float32) for c, e in falantes.envelopes([wav], voz.JANELA_S).items()}
    lap = voz.lapelas_por_nome(tr, envs) or voz.lapelas_por_correlacao(envs)
    med = voz.medir(falas, voz.mascaras(envs, lap), [None] * len(falas), alinhadas, voz.niveis(envs, lap))
    pal = []
    for f, mf in zip(falas, med["falas"]):
        for w, p in zip(f["palavras"], mf.get("palavras") or [{}] * len(f["palavras"])):
            a = p.get("voz_t", p.get("t_alinhado", w["t"]))
            b = p.get("voz_fim", p.get("fim_alinhado", w["fim"]))
            pal.append({"t": a, "fim": b, "palavra": w["palavra"]})
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 if sys.platform == "darwin" else 1 / 1024) / 1e6
    feitas = sum(1 for p in cru for w in p if w)
    json.dump({"modelo": "L1 produto", "audio_s": len(x) / al.SR, "mix_s": t_mix, "carga_s": t_carga, "alinhar_s": t_al,
               "pico_mb": rss, "lapelas": lap, "alinhadas": feitas, "palavras": pal},
              open(saida, "w"), ensure_ascii=False, indent=1)
    print(f"L1: {feitas}/{len(pal)} palavras alinhadas, lapelas {lap}, áudio {len(x)/al.SR:.0f} s, mix {t_mix:.1f} s, "
          f"carga {t_carga:.1f} s, alinhar {t_al:.1f} s, pico {rss:.0f} MB")
    if "--chave" in sys.argv:
        chave = json.load(open(sys.argv[sys.argv.index("--chave") + 1]))["bordas"]
        for b in chave:
            alvo = b["premiere_s"]
            campo = "t" if b["tipo"] == "INÍCIO" else "fim"
            perto = min(pal, key=lambda w: abs(w[campo] - alvo) + (0 if w["palavra"] == b["palavra"] else 5))
            print(f"{b['n']:02d} {b['tipo']:6s} {b['palavra']:14s} premiere {alvo:9.3f}  L0 {b['nosso_s']:9.3f}  "
                  f"L1 {perto[campo]:9.3f}  (L1−premiere {1000*(perto[campo]-alvo):+5.0f} ms)")


if __name__ == "__main__":
    main()
