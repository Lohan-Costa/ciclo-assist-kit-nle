"""
O MERGED COM PROXY — o proxy anexado também na mídia PRÓPRIA do merged (Ciclo Assist, P4, 2026-11-07).

Medido no Premiere 25.6.5: o merged gerado por arquivo apontava a câmera SEM proxy e mostrava a alta com
o botão de proxy ligado; o merged feito pelo MENU herda o proxy. Lido do .prproj salvo, o nativo traz
`Content › ProxyMedia` na VideoMediaSource e `AudioProxies › AudioProxy` na AudioMediaSource, apontando um
`Media` com `IsProxy` true (banco `plugins/premiere-cep/subclipe-e-merged-clip.md` §3c). É o que se confere.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prproj.builder import ExportOptions, _B
from prproj.validate import validate_root
from sync.model import CameraAngle, CameraGroup, Daily, Project, SoundClip, Take


def _arq(tmp: Path, nome: str) -> Path:
    p = tmp / nome
    p.write_bytes(b"x")
    return p


def _projeto(tmp: Path, com_proxy: bool) -> Project:
    cam = CameraAngle(path=_arq(tmp, "A001.mov"), fps=24.0, duration_frames=240, sync_offset_frames=30,
                      audio_channels=2, alternate_start_ticks=12345)
    if com_proxy:
        cam.proxy_path = _arq(tmp, "PROXY_A001.mov")
        cam.proxy_size = (2048, 1080)
    snd = SoundClip(path=_arq(tmp, "T01.wav"), sample_rate=48000, duration_ms=15000, channels=2)
    d = Daily(camera_groups=[CameraGroup(cameras=[cam], name="CAM A", id="a")],
              takes=[Take(sound=snd, cameras=[cam])], name="D", fps=24.0)
    return Project(name="D", groups=[d])


def _raiz(p: Project) -> ET.Element:
    xml = _B(p, ExportOptions(merged_clips=True)).build()
    return ET.fromstring(xml.split("?>", 1)[1])


def test_sem_proxy_nada_muda(tmp_path):
    r = _raiz(_projeto(tmp_path, False))
    assert not list(r.iter("ProxyMedia")) and not list(r.iter("AudioProxy"))


def test_com_proxy_a_midia_do_merged_aponta_o_proxy(tmp_path):
    r = _raiz(_projeto(tmp_path, True))
    proxies = [m for m in r.iter("Media") if m.findtext("IsProxy") == "true"]
    assert proxies and all(m.findtext("FilePath").endswith("PROXY_A001.mov") for m in proxies)
    uids = {m.get("ObjectUID") for m in proxies}
    vms = [v for v in r.iter("VideoMediaSource") if v.find("./MediaSource/Content/ProxyMedia") is not None]
    assert vms and {v.find("./MediaSource/Content/ProxyMedia").get("ObjectURef") for v in vms} <= uids
    # a mídia continua sendo o ORIGINAL
    originais = {m.get("ObjectUID") for m in r.iter("Media") if Path(m.findtext("FilePath") or "").name == "A001.mov"}
    assert all(v.find("./MediaSource/Media").get("ObjectURef") in originais for v in vms)
    # o som da câmera também (AudioProxies › AudioProxy › ProxyMedia)
    aps = {a.get("ObjectID"): a for a in r.iter("AudioProxy")}
    itens = [i.get("ObjectRef") for i in r.iter("AudioProxyItem")]
    assert itens and all(aps[i].find("ProxyMedia").get("ObjectURef") in uids for i in itens)
    # o tamanho e o TC do proxy
    assert any(v.findtext("FrameRect") == "0,0,2048,1080" for v in r.iter("VideoStream"))
    assert all(m.findtext("AlternateStart") == "12345" for m in proxies)


def test_com_proxy_o_arquivo_continua_valido(tmp_path):
    problemas = validate_root(_raiz(_projeto(tmp_path, True)))
    assert not problemas, problemas
