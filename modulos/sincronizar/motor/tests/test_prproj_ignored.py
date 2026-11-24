"""
Clipes IGNORADOS no export.

A regra do usuário: um clipe ignorado VAI para a bin do projeto — o arquivo está
lá, importado —, mas NÃO entra em timeline nenhuma (nem a da diária, nem a de uma
cena). É o "está aqui, mas não quero na montagem", diferente de REMOVER, que apaga
de tudo.

Estes testes guardam as duas metades: (1) o ignorado tem entrada de bin (Media +
MasterClip alcançável); (2) o ignorado não aparece em NENHUMA track de NENHUMA
sequência. O normal, ao lado, continua entrando — senão o teste passaria por ter
esvaziado o projeto inteiro.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prproj.builder import ExportOptions, _B
from prproj.validate import validate_root
from sync.model import CameraAngle, CameraGroup, Daily, Project, SoundClip, Take
from sync.serialize import daily_from_dict, daily_to_dict

FPS = 24.0
HORA = 24 * 3600


def _cam(path: Path, start: int = 0) -> CameraAngle:
    return CameraAngle(path=path, fps=FPS, duration_frames=240,
                       timeline_start_frames=start, sync_offset_frames=30,
                       audio_channels=2)


def _snd(path: Path, start: int = 0) -> SoundClip:
    return SoundClip(path=path, sample_rate=48000, duration_ms=10000, channels=2,
                     timeline_start_frames=start)


def _diaria(tmp: Path) -> Daily:
    """Uma tomada sincronizada (a1 + s1) MAIS um vídeo e um som IGNORADOS."""
    files = {}
    for n in ("a1.mov", "s1.wav", "ign.mov", "ign.wav"):
        p = tmp / n
        p.write_bytes(b"x")
        files[n] = p

    a1 = _cam(files["a1.mov"], 0)
    s1 = _snd(files["s1.wav"], 0)
    return Daily(
        camera_groups=[CameraGroup(cameras=[a1], name="CAM A", id="camA")],
        takes=[Take(sound=s1, cameras=[a1])],
        ignored_cameras=[CameraAngle(path=files["ign.mov"], fps=FPS,
                                     duration_frames=100, audio_channels=2)],
        ignored_sounds=[SoundClip(path=files["ign.wav"], sample_rate=48000,
                                  duration_ms=5000, channels=2)],
        fps=FPS, name="D01", start_tc_frames=HORA,
    )


def _build(d: Daily, options: ExportOptions | None = None) -> ET.Element:
    return ET.fromstring(_B(Project(groups=[d]), options).build())


def _names_in_any_track(root: ET.Element) -> set[str]:
    """Nomes de arquivo que aparecem como clipe em QUALQUER track (vídeo OU áudio)
    de QUALQUER sequência — seguindo TrackItem → SubClip → MasterClip → Name."""
    mc_de_subclip = {
        sc.get("ObjectID"): sc.find("MasterClip").get("ObjectURef")
        for sc in root.iter("SubClip")
        if sc.get("ObjectID") and sc.find("MasterClip") is not None
    }
    nome_de_mc = {mc.get("ObjectUID"): mc.findtext("Name")
                  for mc in root.iter("MasterClip") if mc.get("ObjectUID")}
    names: set[str] = set()
    for ti in root.iter():
        if ti.tag not in ("VideoClipTrackItem", "AudioClipTrackItem"):
            continue
        ref = ti.find(".//SubClip")
        if ref is None:
            continue
        n = nome_de_mc.get(mc_de_subclip.get(ref.get("ObjectRef")))
        if n:
            names.add(n)
    return names


def _media_filepaths(root: ET.Element) -> set[str]:
    return {m.findtext("FilePath") for m in root.iter("Media") if m.findtext("FilePath")}


class TestOIgnoradoVaiParaABin:
    def test_o_ignorado_tem_Media_na_bin(self, tmp_path: Path):
        root = _build(_diaria(tmp_path))
        fps = _media_filepaths(root)
        assert str(tmp_path / "ign.mov") in fps
        assert str(tmp_path / "ign.wav") in fps

    def test_o_ignorado_tem_entrada_de_bin_com_o_nome(self, tmp_path: Path):
        root = _build(_diaria(tmp_path))
        nomes_de_bin = {
            cpi.find("./ProjectItem/Name").text
            for cpi in root.iter("ClipProjectItem")
            if cpi.find("./ProjectItem/Name") is not None
        }
        assert "ign.mov" in nomes_de_bin
        assert "ign.wav" in nomes_de_bin


class TestOIgnoradoNaoEntraNaTimeline:
    def test_o_ignorado_nao_aparece_em_track_nenhuma(self, tmp_path: Path):
        root = _build(_diaria(tmp_path))
        in_tracks = _names_in_any_track(root)
        assert "ign.mov" not in in_tracks
        assert "ign.wav" not in in_tracks

    def test_o_normal_ao_lado_continua_entrando(self, tmp_path: Path):
        # A prova de que o teste acima não passou por ter esvaziado o projeto.
        root = _build(_diaria(tmp_path))
        in_tracks = _names_in_any_track(root)
        assert "a1.mov" in in_tracks
        assert "s1.wav" in in_tracks

    def test_o_ignorado_nao_duplica_o_arquivo(self, tmp_path: Path):
        root = _build(_diaria(tmp_path))
        ign = str(tmp_path / "ign.mov")
        assert sum(1 for m in root.iter("Media") if m.findtext("FilePath") == ign) == 1


class TestOValidadorAprova:
    def test_uma_diaria_com_ignorados_passa_no_validador(self, tmp_path: Path):
        root = _build(_diaria(tmp_path))
        assert validate_root(root) == []


class TestRoundTrip:
    def test_o_round_trip_preserva_os_ignorados(self, tmp_path: Path):
        d = _diaria(tmp_path)
        d2 = daily_from_dict(daily_to_dict(d))
        assert {str(c.path) for c in d2.ignored_cameras} == {str(tmp_path / "ign.mov")}
        assert {str(s.path) for s in d2.ignored_sounds} == {str(tmp_path / "ign.wav")}

    def test_o_payload_do_frontend_e_lido(self, tmp_path: Path):
        # O caminho REAL: o frontend manda `ignored` com kind por fonte.
        for n in ("a1.mov", "s1.wav", "ign.mov"):
            (tmp_path / n).write_bytes(b"x")
        d = daily_from_dict({
            "fps": FPS, "name": "D01", "start_tc_frames": HORA,
            "camera_groups": [{"id": "camA", "name": "CAM A", "cameras": [{
                "path": str(tmp_path / "a1.mov"), "duration_frames": 240,
            }]}],
            "takes": [], "orphan_paths": [], "orphan_sounds": [],
            "ignored": [{
                "path": str(tmp_path / "ign.mov"), "name": "ign.mov",
                "kind": "camera", "fps": FPS, "duration_frames": 100,
            }],
        })
        assert [str(c.path) for c in d.ignored_cameras] == [str(tmp_path / "ign.mov")]
