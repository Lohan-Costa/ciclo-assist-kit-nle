"""Conferir a sequência que está no RECORD do Media Composer contra um vídeo de referência, ponto a ponto.

Rodar (o MC aberto com a sequência no Record, NA FRENTE, e a tela sem nada por cima do monitor):

    .venv/bin/python tools/bancada_avid/conferir_record.py <projeto.prproj> <sequência> <referência.mov> <pasta saída> \\
        [--caixa x0,y0,x1,y1] [--pastas <pasta>...]

Os pontos são os do resto do app (`tools.conferir_conform.pontos_visiveis`: 1º e último quadro VISÍVEIS de cada
plano), lidos do .prproj. Para cada um: `SetPosition` na sequência do Record (o MC 25.12 tem; o 24.6 NÃO — banco
`avid-panel-sdk/ativar-no-2021-ftf.md`), a foto da tela recortada na `--caixa` (a imagem do Record, em pontos; medir na
foto DESTA abertura) e `comparar_um` contra o quadro da referência. Saída: `conferencia.json` + as fotos.
⚠️ A foto é do MONITOR (a imagem que o MC desenha, reduzida): serve para o "confere / não confere" da correlação a
160×90, não para medir pixel.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]


def _piloto():
    p = RAIZ
    while not (p / "piloto" / "piloto").is_dir():
        if p.parent == p:
            raise SystemExit("não achei a pasta do piloto subindo de pasta")
        p = p.parent
    sys.path.insert(0, str(p / "piloto"))
    from piloto import olhos

    return olhos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prproj")
    ap.add_argument("sequencia")
    ap.add_argument("referencia")
    ap.add_argument("saida")
    ap.add_argument("--caixa", default="1296,127,1845,436")
    ap.add_argument("--pastas", nargs="*", default=[])
    ap.add_argument("--espera", type=float, default=0.8)
    a = ap.parse_args()
    olhos = _piloto()
    from PIL import Image

    from avid.mcapi import MediaComposer
    from tools.conferir_conform import comparar_um, pontos_visiveis
    from tools.prproj_para_drt import analisar

    analise = analisar(a.prproj, a.sequencia, a.pastas)
    fps = analise["leitura"]["fps"]
    pontos = pontos_visiveis(analise["leitura"]["segmentos"], round(fps))
    caixa = tuple(int(x) for x in a.caixa.split(","))
    os.makedirs(a.saida, exist_ok=True)
    res = []
    with MediaComposer() as mc:
        seq = mc.sequencia_no_record()
        if not seq:
            print("não há sequência no Record")
            return 1
        mob = seq.get("mob_id")
        for i, pt in enumerate(pontos):
            q = int(pt["quadro"])
            mc._chamar("SetPosition", mob_id=mob, offset=q)
            time.sleep(a.espera)
            tela = olhos.foto_da_tela(a.saida, f"tela_{q}")
            img = os.path.join(a.saida, f"{q}.png")
            with Image.open(tela) as t:
                esc = olhos.escala()                       # a caixa em pontos, a foto em pixels
                t.crop(tuple(int(v * esc) for v in caixa)).save(img)
            os.remove(tela)
            r = {**pt, **comparar_um(img, a.referencia, q, fps)}
            res.append(r)
            print(f"{i + 1:3d}/{len(pontos)} q{q:5d} {r.get('corr')} {pt['ponta']:7s} {pt['plano']}", flush=True)
    with open(os.path.join(a.saida, "conferencia.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    bons = sum(1 for r in res if (r.get("corr") or 0) >= 0.75)
    print(f"{bons}/{len(res)} conferem")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
