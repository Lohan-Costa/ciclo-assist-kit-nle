"""As máscaras de opacidade do Premiere no Baselight (`baselight/mascaras.py`; estudo PRODUCAO-C: pelo produto
128 → 130 de 133 pontos, 2026-11-23 — o BLG de cada plano mascarado igual ao do estudo, menos o nº do evento).

    .venv/bin/python tests/test_baselight_mascaras.py

- A composição do molde (fundo, shape, camada) entra na pilha: 3 faixas novas, as velhas sobem 3, ids únicos.
- O fundo: o `GR_SequenceRop` do clipe de baixo com o deslocamento no MEIO do quadro e o passo (60 qps a 50 %: 1,25).
- A shape: o contorno recuado para dentro; fora do trecho, a caixa gigante; a curva com um keyframe por quadro.
- Nada embaixo = sem composição; o fundo vira NATIVO no `efeitos.planejar`.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import efeitos as EF  # noqa: E402
from baselight import mascaras as M  # noqa: E402

TL = 24000 / 1001
MOLDE_R = Path(EF.MOLDE_RETIME).read_text(encoding="latin1")
MOLDE_T = Path(EF.MOLDE_TRANSFORM).read_text(encoding="latin1")


def _quadrado(x0, y0, x1, y1):
    return [[i, (x, y), (x, y), (x, y)] for i, (x, y) in enumerate(((x0, y0), (x1, y0), (x1, y1), (x0, y1)))]


def _seg(n, track, ini, dur, nome, fps=TL, ent=0, vel_rel=1.0, mascara=None):
    efeitos = [{"name": "Máscara de opacidade (Fusion)", "params": {"mascaras": [mascara], "fonte_px": [1920, 1080]}}] \
        if mascara else []
    return {"n": n, "track": track, "ini": ini, "duration_frames": dur, "clip_name": nome, "effects": efeitos,
            "timeline_tc_in": f"00:00:{ini // 24:02d}:{ini % 24:02d}", "original": f"/o/{nome}", "fps_original": fps,
            "desloc_s": 0.0, "_premiere": {"ent": ent, "fps": fps, "vel": TL / fps / vel_rel},
            "media_ref": {"local_path": f"/d/{nome}"}}


MK = {"vertices": _quadrado(0.25, 0.25, 0.75, 0.75), "invertida": False, "suave_px": 20.0, "expansao_px": 0.0,
      "quadros": [{"vertices": _quadrado(0.25, 0.25, 0.75, 0.75)}]}


def _objs_fundo(nome):
    est = (f"9 d s12:HD 1920x1080 d s{len('/o/' + nome)}:/o/{nome} d f0x0p+0 d f0x1p+0 d i1 d Z z d Z d Z 2:40 "
           "42ca0000 3f800000 3f800000 2 0 0 0 0 Z 7 7:AT_NONE ")
    return {500: ("GR_SequenceRop", "gr_sequence", 5, [501], est), 501: ("GM_ConformData", "gm", 4, [], "t 0 t 0 ")}


def test_montar_poe_tres_faixas_e_sobe_as_velhas():
    mo = M.molde()
    base = EF.blg({"q": None, "motion": None}, 0, 10, TL, 1920, 1080, MOLDE_R, MOLDE_T)
    antes = re.findall(r'8:GM_Strip 2:gm \d+ 1 \d+ 1 o 0 \S+ \S+ (\d+) f f 0', base)
    t = M.montar(base, mo)
    depois = re.findall(r'8:GM_Strip 2:gm \d+ 1 \d+ 1 o 0 \S+ \S+ (\d+) f f 0', t)
    assert len(depois) == len(antes) + 3
    assert sorted(int(x) for x in depois) == sorted([int(x) + 3 for x in antes] + [0, 1, 2])
    ids = re.findall(r'^\s*\((\d+)\)=', t, re.M)
    assert len(ids) == len(set(ids)) and EF.ler(EF.gravar(t)) == t


def test_fundo_no_meio_do_quadro_e_o_passo():
    mo = M.molde()
    L = _seg(1, 1, 0, 48, "A.mp4", fps=60.0, ent=100, vel_rel=0.5)
    tr, arq = M.troca_do_fundo(L, 8, _objs_fundo("A.mp4"), mo, TL)
    assert arq == "A.mp4"
    est = tr[mo["seq"]][4]
    off, passo = re.search(r" d f(\S+) d f(\S+) ", est).groups()
    # 60 qps a 50 % numa 23,976: 1,25125 quadro do arquivo por quadro; no quadro 8: 100 + 10,01 → o quadro 110
    assert abs(float.fromhex(passo) - 60 / TL * 0.5) < 1e-9
    assert abs(float.fromhex(off) - (110 + 0.5) / TL) < 1e-12
    assert tr[mo["seq"]][3] == [mo["cd"]] and tr[mo["cd"]] == _objs_fundo("A.mp4")[501]
    assert M.troca_do_fundo(L, 0, _objs_fundo("OUTRO.mp4"), mo, TL)[0] is None


def test_shape_recuada_caixa_fora_do_trecho():
    s = _seg(2, 2, 0, 6, "B.mov", mascara=MK)
    series, F = M.serie_da_shape(s, 0, 6, (0, 3), 1920, 1080)
    assert len(series) == 24 and all(len(v) == 6 for v in series) and abs(F - 20.0) < 1e-9
    # dentro do trecho: o 1º vértice (canto de cima à esquerda, 480 px) recuado b·F para DENTRO (x e y crescem)
    x0 = series[0][0] * 1920
    assert x0 > 480 and abs((x0 - 480) - M.MODO["b"] * 20) < 1e-6   # o miter: d em x e em y
    # fora do trecho: a caixa gigante (bem fora do quadro)
    assert series[0][4] * 1920 < -1920


def test_composicao_e_nada_embaixo():
    mo = M.molde()
    ctx = {"molde": mo, "molde_t": MOLDE_T, "w": 1920, "h": 1080, "fps": TL}
    L = _seg(1, 1, 0, 24, "A.mp4")
    F_ = _seg(2, 2, 4, 6, "B.mov", mascara=MK)
    frente = EF.blg({"q": None, "motion": None}, 0, 6, TL, 1920, 1080, MOLDE_R, MOLDE_T)
    t, info = M.composicao(F_, 4, 10, [L, F_], _objs_fundo("A.mp4"), frente, ctx)
    assert t is not None and info["fundo"] == "A.mp4" and not info["aviso"]
    assert "Z 3 t f t" in t                                   # a shape invertida (a frente DENTRO)
    assert "s8:/o/A.mp4 d f" in t and t.count("BEZ_Bezier2dInterp") >= 1
    assert EF.ler(EF.gravar(t)) == t
    sozinho = _seg(3, 2, 30, 6, "C.mov", mascara=MK)
    assert M.composicao(sozinho, 30, 36, [L, sozinho], _objs_fundo("A.mp4"), frente, ctx)[0] is None


def test_o_fundo_vira_nativo():
    lt = {"timeline_fps": TL, "segments": [
        {**_seg(0, 1, 0, 24, "A.mp4", fps=60.0, ent=10), "effects": []},
        _seg(1, 2, 0, 12, "B.mov", mascara=MK)]}   # o A aparece depois (o coberto INTEIRO o conform deixa fora)
    dec = {"/d/A.mp4": {"caminho": "/o/A.mp4", "fps": 60.0}, "/d/B.mov": {"caminho": "/o/B.mov", "fps": TL}}
    p = {x["clip"]: x for x in EF.planejar(lt, dec, lambda s: s["media_ref"]["local_path"])}
    assert p["A.mp4"]["nativo"] and p["A.mp4"]["q"][:3] == [10, 12, 15]
    pl = M.planejar(lt, dec, lambda s: s["media_ref"]["local_path"])
    assert [m["clip_name"] for m in pl["mascarados"]] == ["B.mov"]
    pd = M.pedacos(pl, [{"n": 2, "shot_id": 9, "a": 0, "b": 12, "clip": "B.mov"}], list(p.values()))
    assert len(pd) == 1 and pd[0]["ef"]["inicio"] == 0


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_") and callable(f):
            f()
            print("ok", nome)
