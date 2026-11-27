"""A verdade dos casos do Premiere (o que a TIMELINE toca, conferido no monitor Programa: o quadro e o TC queimados na
imagem do laboratório) → `plano_premiere.json`, no formato do conferidor (`motor/edl/conferir.py`).

    python3 spikes/edl_som_premiere/plano.py

O som segue a sincronia VERDADEIRA da cena (TC em jam): o quadro `a` da CAM A é o `a + 48` do som 1. Na multicâmera e no
nest só entram a V1 e a A1 (o que o Premiere põe nas outras trilhas — "Todas as câmeras", a mistura do nest — não é o
que se mede aqui: basta que a EDL não leve à fonte).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "edl_som_mc"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import montar_casos as M  # noqa: E402
import ponte  # noqa: E402

CA, CB, S1 = M.CAMA, M.CAMB, M.SOM1


def caso(nome, eventos):
    """eventos = [(dur, {trilha: (fonte, quadro, canal)})]"""
    ev = [{"dur": d, "trilhas": {}} for d, _ in eventos]
    return M._verdade(nome, ev, [t for _, t in eventos])


def sinc(a, dur, canais=range(1, 7), cam=CA):
    return (dur, {"V1": (cam, a, None), **{f"A{c}": (S1, a + 48 if cam == CA else a + 96, c) for c in canais}})


CASOS = [
    ("P S1 SUBCLIPE", [(96, {"V1": (CA, 144, None), "A1": (CA, 144, 1), "A2": (CA, 144, 2)}),
                       (72, {"V1": (CB, 248, None), "A1": (CB, 248, 1), "A2": (CB, 248, 2)})]),
    ("P S2 MERGED TC", [sinc(72, 120), sinc(312, 72)]),
    ("P S3B MERGED IN", [sinc(72, 120)]),
    ("P S4 MULTICAM", [(72, {"V1": (CA, 152, None), "A1": (S1, 200, 1)}),
                       (72, {"V1": (CA, 224, None), "A1": (S1, 272, 1)})]),
    ("P S5 NEST", [(96, {"V1": (CA, 96, None), "A1": (S1, 144, 1)}),
                   (72, {"V1": (CA, 272, None), "A1": (S1, 320, 1)})]),
]

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    out = []
    for nome, evs in CASOS:
        out.append(caso(nome, evs))
        out.append(caso(nome + " SO AUDIO", [(d, {k: v for k, v in t.items() if k != "V1"}) for d, t in evs]))
    p = ponte.PASTA / "plano_premiere.json"
    p.write_text(json.dumps({"receita": "B31_EDL_SOM", "fps": "23.976", "fontes": M.FONTES, "canais": M.CANAIS,
                             "casos": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(p, len(out), "casos")
