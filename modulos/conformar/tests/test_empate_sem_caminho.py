"""Empate no casamento do AAF SAI SEM CAMINHO até o editor revisar (autor, 2026-11-22).

Rodar:

    .venv/bin/python tests/test_empate_sem_caminho.py        (Windows: .venv-win/Scripts/python)

`media/matcher.match_segments` devolvia o AMBÍGUO (≥2 candidatos com o mesmo nome e a mesma duração) com o 1º candidato
em `matched_path` e `ambiguous=True` — e ninguém lia a marca: o `build_url_map` religava no 1º da lista, calado. No
laboratório BL08 (P2: `A001C004` em DIA01 e DIA02, mesmo TC e duração, imagem diferente) o plano do DIA01 ia para o DIA02.
Agora: sem caminho, `unresolved`, com os candidatos. Cópias IDÊNTICAS (P9: o backup) continuam valendo como uma.
A parte do laboratório PULA, dizendo, sem a mídia da BL08 no disco.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from media import matcher as M  # noqa: E402

LAB = Path("/Volumes/SSD/PROGRAMAS COM CLAUDE/laboratorio-de-midia/saida")
AAF = LAB / "bancadas/avid_casamento/aaf_do_mc/BL08_CASAMENTO.aaf"
ORIGINAIS = LAB / "baselight/BL08_CASAMENTO/ORIGINAIS"


def test_copias_identicas():
    with tempfile.TemporaryDirectory() as d:
        a, b, c = (os.path.join(d, n) for n in ("a.mov", "b.mov", "c.mov"))
        for p, dado in ((a, b"x" * 5000), (b, b"x" * 5000), (c, b"x" * 4999 + b"y")):
            with open(p, "wb") as f:
                f.write(dado)
        assert M._copias_identicas([a, b])
        assert not M._copias_identicas([a, c])
        assert not M._copias_identicas([a, os.path.join(d, "nao-existe.mov")])


def test_laboratorio_bl08():
    if not AAF.exists() or not ORIGINAIS.exists():
        print("PULADO — sem a mídia do laboratório BL08 neste disco")
        return
    from aaf.parser import parse_aaf
    from media.indexer import index_folder
    p = parse_aaf(str(AAF))
    # sem a confirmação pelo daily: o empate de verdade sai sem caminho
    r = M.match_segments(p["segments"], index_folder([str(ORIGINAIS)]), options={"confirmar_pelo_daily": False})
    por = {x["segment_index"]: x for x in r["results"]}
    vistos = {}
    for i, s in enumerate(p["segments"]):
        if s.get("is_audio") or s.get("is_gap") or i not in por:
            continue
        vistos.setdefault(s.get("clip_name"), []).append(por[i])
    for x in vistos["A001C004"]:                     # P2: empate de verdade → sem caminho, para a revisão
        assert x["matched_path"] is None and x["ambiguous"] and x["match_method"] == "unresolved", x
        assert len(x["candidates"]) >= 2
    for x in vistos["C001C002"]:                     # P9: cópias idênticas → um original
        assert x["matched_path"] and not x["ambiguous"], x
    for x in vistos["A001C003"]:                     # P1: a duração separa
        assert x["matched_path"] and not x["ambiguous"], x
    # COM a confirmação pelo daily (o padrão): a imagem separa o P2, cada daily no original do seu dia
    r = M.match_segments(p["segments"], index_folder([str(ORIGINAIS)]))
    for i, s in enumerate(p["segments"]):
        x = next((y for y in r["results"] if y["segment_index"] == i), None)
        if x is None or s.get("is_audio") or s.get("clip_name") != "A001C004":
            continue
        dia = "DIA01" if "/DIA01/" in s["media_ref"]["local_path"] else "DIA02"
        assert x["verified"] and f"/{dia}/" in x["matched_path"] and x["imagem"], x
        assert max(x["imagem"].values()) - min(x["imagem"].values()) >= 0.05, x["imagem"]


if __name__ == "__main__":
    for t in (test_copias_identicas, test_laboratorio_bl08):
        t()
        print("ok", t.__name__)
    sys.exit(0)
