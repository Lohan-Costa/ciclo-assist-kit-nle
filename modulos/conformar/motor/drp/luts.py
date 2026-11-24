"""As LUTs das camadas de ajuste do Premiere no nó do Adjustment Clip, DEPOIS do import — o gêmeo em
Python de `aplicarLuts` da casca (`plugins/resolve/casca/main.js`), para o scripting externo e os testes.

⛔ MEDIDO 2026-10-10 (Resolve Studio 19.0.0b.59, Windows, caso real R04 PRODUCAO-C): o
`TimelineItem.SetLUT(1, caminho)` com um .cube FORA da pasta de LUTs do Resolve devolve false; copiado
para a subpasta `DeLaPraCa` dela + `Project.RefreshLUTList()` → true pelo caminho relativo. O efeito da
LUT no Resolve = o da Lumetri no Premiere (por canal, 1–2 níveis de 255). Banco: matriz de plataforma
("pasta de LUTs do Resolve") e `prproj/estruturas.md` §"Lumetri: a LUT EMBUTIDA".
"""
from __future__ import annotations

import os
import shutil
import sys


def pasta_de_luts() -> str:
    if os.name == "nt":
        return os.path.join(os.environ.get("ProgramData") or r"C:\ProgramData",
                            "Blackmagic Design", "DaVinci Resolve", "Support", "LUT")
    if sys.platform == "darwin":
        return "/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT"   # pendente
    return os.path.expanduser("~/.local/share/DaVinciResolve/LUT")                      # não alvo


def aplicar_luts(projeto, timeline, relatorio: dict) -> list[dict]:
    """Cada entrada de `relatorio["luts"]` ({trilha, quadro, arquivo, cube?, saturacao?}) no nó 1 do clipe achado
    pela trilha, pelo quadro (desde o início da timeline) e pelo nome: a LUT do Adjustment Clip e/ou a saturação
    (o Black & White do Premiere)."""
    lista = relatorio.get("luts") or []
    destino = os.path.join(pasta_de_luts(), "DeLaPraCa")
    os.makedirs(destino, exist_ok=True)
    rel = {}
    for x in lista:
        if x.get("cube") and os.path.isfile(x["cube"]):
            shutil.copy2(x["cube"], os.path.join(destino, os.path.basename(x["cube"])))
            rel[x["cube"]] = "DeLaPraCa/" + os.path.basename(x["cube"])
    projeto.RefreshLUTList()
    inicio = timeline.GetStartFrame()
    out = []
    for x in lista:
        base = {k: x.get(k) for k in ("trilha", "quadro", "arquivo")}
        # a entrada traz a LUT (`cube`), a SATURAÇÃO (o Black & White do Premiere → 0; autor, 2026-10-10) ou as duas
        sat = x.get("saturacao")
        sat = float(sat) if isinstance(sat, (int, float)) and 0 <= sat <= 4 else None
        if not x.get("cube") and sat is None:
            out.append({**base, "ok": False, "erro": "nada a aplicar"})
            continue
        if x.get("cube") and x["cube"] not in rel:
            out.append({**base, "ok": False, "erro": "o arquivo da LUT não está mais lá"})
            continue
        alvo = next((it for it in timeline.GetItemListInTrack("video", x["trilha"]) or []
                     if it.GetStart() - inicio == x["quadro"] and it.GetName() == x["arquivo"]), None)
        if alvo is None:
            out.append({**base, "ok": False, "erro": "clipe não encontrado na timeline"})
            continue
        ok, feito = True, {}
        if x.get("cube"):
            ok = bool(alvo.SetLUT(1, rel[x["cube"]]))
            feito["lut"] = rel[x["cube"]]
        if ok and sat is not None:
            # nó 1: Slope/Offset/Power neutros, só a saturação (medido no Resolve 19: o poste do R04 sai cinza)
            ok = bool(alvo.SetCDL({"NodeIndex": "1", "Slope": "1.0 1.0 1.0", "Offset": "0.0 0.0 0.0",
                                   "Power": "1.0 1.0 1.0", "Saturation": str(sat)}))
            feito["saturacao"] = sat
        out.append({**base, "ok": ok, **(feito if ok else {"erro": "o Resolve não aceitou a cor (LUT/saturação)"})})
    return out
