"""A velocidade e o Motion do Premiere no Baselight (`baselight/efeitos.py`; estudo PRODUCAO-C: pelo produto 68 → 128
de 133 pontos, 2026-11-23 — o que falta são as máscaras e o título).

    .venv/bin/python tests/test_baselight_efeitos.py

- O arquivo com velocidade e taxa ≠ a da timeline vira "nativo" (declarado na taxa da timeline, sem TC nem duração) e
  TODOS os planos dele levam a curva — o de 100 % com a do tempo real; o de 100 % de outro arquivo fica como está.
- A curva: piso(início + k ÷ velocidade), e no `<in>` o 1º quadro mostrado (out − in = a duração).
- O plano escondido INTEIRO por trilhas de cima fica de fora (o `bl-conform` o deixa fora: era "não achado").
- O BLG: o molde do Retime com a curva (um keyframe por quadro) + a faixa de Transform embaixo; volta pelo payload.
"""
from __future__ import annotations

import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import efeitos as EF  # noqa: E402

TL = 24000 / 1001


def _seg(tc, clip, fps, ent, vel_rel=1.0, dur=24, track=1, efeitos=None):
    return {"track": track, "timeline_tc_in": tc, "duration_frames": dur, "clip_name": clip, "relative_speed": vel_rel,
            "media_ref": {"local_path": f"/d/{clip}"}, "effects": efeitos or [],
            "_premiere": {"ent": ent, "fps": fps, "vel": TL / fps / vel_rel}}


def _leitura(*segs):
    return {"timeline_fps": TL, "segments": list(segs)}


def _dec(*nomes_fps):
    return {f"/d/{n}": {"caminho": f"/o/{n}", "fps": f} for n, f in nomes_fps}


ACHAR = lambda s: s["media_ref"]["local_path"]  # noqa: E731


def test_nativo_e_tempo_real():
    lt = _leitura(_seg("00:00:00:00", "A.mp4", 60.0, 100, vel_rel=0.5),     # 60 qps a 50 %
                  _seg("00:00:01:00", "A.mp4", 60.0, 1000),                 # o mesmo arquivo a 100 %
                  _seg("00:00:02:00", "B.mp4", 25.0, 50),                   # outro arquivo, só outra taxa
                  _seg("00:00:03:00", "C.mov", TL, 10, vel_rel=2.0))        # mesma taxa a 200 %
    p = {x["clip"]: x for x in EF.planejar(lt, _dec(("A.mp4", 60.0), ("B.mp4", 25.0), ("C.mov", TL)), ACHAR)}
    assert set(p) == {"A.mp4", "C.mov"}                                     # o B fica como está (tempo real do Baselight)
    a = [x for x in EF.planejar(lt, _dec(("A.mp4", 60.0), ("B.mp4", 25.0), ("C.mov", TL)), ACHAR) if x["clip"] == "A.mp4"]
    assert all(x["nativo"] for x in a)
    lento, real = a
    # 50 % de 60 qps numa 23,976: 1,25 quadro de fonte por quadro → piso(100 + 1,25 k)
    assert lento["q"][:5] == [100, 101, 102, 103, 105]
    # 100 % de 60 qps: 2,5 por quadro (o tempo real)
    assert real["q"][:4] == [1000, 1002, 1005, 1007]
    assert p["C.mov"]["q"][:3] == [10, 12, 14] and not p["C.mov"]["nativo"]


def test_escondido_fica_de_fora():
    lt = _leitura(_seg("00:00:00:00", "A.mp4", 60.0, 100, vel_rel=0.5, track=1),
                  _seg("00:00:00:00", "C.mov", TL, 0, dur=48, track=2))
    assert EF.planejar(lt, _dec(("A.mp4", 60.0), ("C.mov", TL)), ACHAR) == []


def test_motion_parado_animado_e_flip():
    mo = {"name": "Motion", "params": {"scale_x": 1.2, "scale_y": 1.2, "pos_x": 100.0, "pos_y": -50.0, "flip_x": True}}
    x = EF.motion({"effects": [mo]})
    assert x == (-1.2, 1.2, 0.0, 0.6, 0.55)
    assert EF.motion({"effects": [{"name": "Motion", "params": {}}]}) is None
    kf = {"name": "Motion", "params": {"scale_x": 1.0, "scale_y": 1.0, "kf": {"zoom": [[10, 1.0], [20, 2.0]]}}}
    s = EF.series_motion({"effects": [kf]}, 15, EF.motion({"effects": [kf]}))
    assert s["sx"][0] == 1.0 and abs(s["sx"][5] - 1.5) < 1e-12 and s["sx"][14] == 2.0 and s["x"] == [0.5] * 15


XML = """<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4"><sequence id="s"><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate><media><video><track>
<clipitem id="clipitem-0"><name>A.mp4</name><start>0</start><end>24</end><in>40</in><out>64</out>
<file id="file-1"><name>A.mp4</name><pathurl>file://localhost/o/A.mp4</pathurl><rate><timebase>60</timebase><ntsc>FALSE</ntsc></rate>
<duration>9000</duration><timecode><rate><timebase>60</timebase><ntsc>FALSE</ntsc></rate><string>01:00:00:00</string></timecode>
<media><video><samplecharacteristics><rate><timebase>60</timebase><ntsc>FALSE</ntsc></rate></samplecharacteristics></video></media></file></clipitem>
<clipitem id="clipitem-1"><name>A.mp4</name><start>24</start><end>48</end><in>400</in><out>424</out><file id="file-1"/></clipitem>
</track></video></media></sequence></xmeml>"""


def test_no_xmeml():
    lt = _leitura(_seg("00:00:00:00", "A.mp4", 60.0, 100, vel_rel=0.5), _seg("00:00:01:00", "A.mp4", 60.0, 1000))
    planos = EF.planejar(lt, _dec(("A.mp4", 60.0)), ACHAR)
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as fh:
        fh.write(XML)
    assert EF.no_xmeml(fh.name, planos) == {"nativos": 1, "planos": 2}
    r = ET.parse(fh.name).getroot()
    f = r.find(".//file[@id='file-1']")
    assert f.findtext("rate/timebase") == "24" and f.findtext("rate/ntsc") == "TRUE"
    assert f.find("timecode") is None and f.find("duration") is None
    assert f.findtext("media/video/samplecharacteristics/rate/timebase") == "24"
    cis = r.findall(".//clipitem")
    assert [(c.findtext("in"), c.findtext("out")) for c in cis] == [("100", "124"), ("1000", "1024")]


def test_blg_retime_e_transform():
    molde_r = Path(EF.MOLDE_RETIME).read_text(encoding="latin1")
    molde_t = Path(EF.MOLDE_TRANSFORM).read_text(encoding="latin1")
    p = {"q": [500 + 2 * k for k in range(30)], "in_bl": 500, "motion": (1.1, 1.1, 0.0, 0.55, 0.5), "series": None}
    t = EF.blg(p, 10, 20, TL, 1920, 1080, molde_r, molde_t)
    # a curva do pedaço [10, 30): relativa ao in do clipitem (como o estudo); valor = (q + 0,5)/fps
    cid = EF._curva_do_retime(t)
    linha = next(ln for ln in t.split("\n") if ln.strip().startswith(f"({cid})="))
    assert ":6 0 20 0 " in linha and EF._n((20 + 0.5) / TL) in linha
    assert "GR_TransformRop" in t and t.count("8:GM_Strip") == molde_r.count("8:GM_Strip") + 1
    ids = re.findall(r'^\s*\((\d+)\)=', t, re.M)
    assert len(ids) == len(set(ids))
    assert EF.ler(EF.gravar(t)) == t
    # sem Motion: só o Retime; sem velocidade: a identidade
    t2 = EF.blg({"q": None, "motion": None}, 0, 5, TL, 1920, 1080, molde_r, molde_t)
    assert "GR_TransformRop" not in t2 and EF._n(0.5 / TL) in t2


def test_achar_plano_pelo_pedaco():
    planos = [{"inicio": 74, "quadros": 6, "clip": "LOU_7310.mov"}, {"inicio": 74, "quadros": 6, "clip": "X.mov"}]
    p, k0 = EF.achar_plano(planos, 79, 80, "LOU_7310.mov")
    assert p is planos[0] and k0 == 5
    assert EF.achar_plano(planos, 79, 80, "outro")[0] is None              # dois candidatos sem o nome: não se adivinha


def test_titulos_viram_markers():
    tit = {"name": "Text", "params": {"titulo": {"caixas": [{"texto": "THAT’S", "corpo_resolve": 200.0,
                                                              "fonte": {"familia": "Acumin Pro", "estilo": "Semibold"}}]}}}
    lt = _leitura({"track": 3, "timeline_tc_in": "00:00:08:01", "duration_frames": 3, "effects": [tit]},
                  {"track": 3, "timeline_tc_in": "00:00:09:00", "duration_frames": 3, "effects": [tit], "disabled": True})
    t = EF.titulos(lt)
    assert [(x["inicio"], x["fim"], x["texto"]) for x in t] == [(193, 196, "THAT’S")]
    (q, nota), = EF.marcas_dos_titulos(t, TL)
    assert q == 193 and "«THAT’S»" in nota and "Acumin Pro Semibold, corpo 200" in nota and "V3, até 00:08:04" in nota


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_") and callable(f):
            f()
            print("ok", nome)
