"""Os merged de um SYNC em bins por cena (`POST /api/v1/merge`, Ciclo Assist P4, 2026-11-06).

A cena é a da claquete do som, com a regra do Avid: descarte → cena → NAO RESOLVIDO.
"""

from __future__ import annotations

import gzip
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from premiere import merged_cenas
from prproj.builder import ExportOptions, build_merged_por_cena
from prproj.validate import validate
from sync.model import CameraAngle, CameraGroup, Daily, Project, SoundClip, Take


def _arq(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def _take(tmp: Path, som: str, cam: str) -> Take:
    c = CameraAngle(path=_arq(tmp / cam), fps=24.0, duration_frames=240, sync_offset_frames=0,
                    audio_channels=2)
    s = SoundClip(path=_arq(tmp / som), sample_rate=48000, duration_ms=10000, channels=2)
    return Take(sound=s, cameras=[c])


def _projeto(tmp: Path) -> Project:
    takes = [
        _take(tmp, "PROJ - C4 P1-T002.WAV", "A002.mov"),
        _take(tmp, "PROJ - C4 P1-T001.WAV", "A001.mov"),
        _take(tmp, "PROJ - C10 P2-T001.WAV", "A003.mov"),
        _take(tmp, "ZOOM0034.WAV", "A004.mov"),
        _take(tmp, "FALSE TAKE/PROJ - C4 P1-T003.WAV", "A005.mov"),
    ]
    cams = [c for t in takes for c in t.cameras]
    d = Daily(camera_groups=[CameraGroup(cameras=cams, name="CAM A", id="a")],
              takes=takes, name="D01", fps=24.0)
    return Project(name="D01", groups=[d])


def test_a_ordem_das_bins_e_a_das_tomadas(tmp_path):
    g = merged_cenas.agrupar(_projeto(tmp_path).groups[0].takes)
    assert [k for k, _ in g] == ["C04", "C10", "NAO RESOLVIDO", "DESCARTE"]
    c04 = dict(g)["C04"]
    assert [t.sound.path.name for t in c04] == ["PROJ - C4 P1-T001.WAV", "PROJ - C4 P1-T002.WAV"]


def test_o_prproj_tem_CENAS_com_uma_bin_por_cena(tmp_path):
    out = tmp_path / "saida" / "D01 MERGED.prproj"
    out.parent.mkdir()
    bins = build_merged_por_cena(_projeto(tmp_path), out, "CENAS", ExportOptions(merged_clips=True))
    assert bins == {"C04": 2, "C10": 1, "NAO RESOLVIDO": 1, "DESCARTE": 1}
    assert not validate(out)
    r = ET.fromstring(gzip.open(out, "rt", encoding="utf-8").read())
    nome = {b.get("ObjectUID"): b.findtext(".//Name") for b in r.iter("BinProjectItem")}
    assert set(nome.values()) == {"CENAS", "C04", "C10", "NAO RESOLVIDO", "DESCARTE"}
    # CENAS é a única bin na raiz, e as cenas são filhas dela
    raiz = next(e for e in r.iter("RootProjectItem") if e.get("ObjectUID"))
    filhos_raiz = [i.get("ObjectURef") for i in raiz.iter("Item")]
    assert [nome.get(u) for u in filhos_raiz] == ["CENAS"]


def test_proxies_conferidos_entram_e_o_que_falta_e_dito(tmp_path):
    p = _projeto(tmp_path)
    t = p.groups[0].takes
    px = _arq(tmp_path / "PROXY" / "A001.mov")
    falta = merged_cenas.anexar_proxies(p, {
        str(t[1].cameras[0].path): str(px),
        str(t[0].cameras[0].path): str(tmp_path / "PROXY" / "sumiu.mov"),
    })
    assert t[1].cameras[0].proxy_path == px
    assert t[0].cameras[0].proxy_path is None
    assert falta["proxy_ausente"] == [str(tmp_path / "PROXY" / "sumiu.mov")]
    assert len(falta["sem_proxy"]) == 3
