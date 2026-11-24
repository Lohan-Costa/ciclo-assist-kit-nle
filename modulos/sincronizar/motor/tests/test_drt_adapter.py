"""
O adapter Diária → segments do DRT (DaVinci Resolve).

Guarda o mapeamento SEM tocar em arquivo nenhum (o build de verdade precisa de
ffprobe e é exercitado à parte): uma track por câmera, o som direto multicanal
em N tracks mono, e o round-trip de timecode EXATO contra o parser do writer —
se o TC que o adapter escreve não voltar ao mesmo frame no writer, o clipe cai
no lugar errado da timeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from drt.adapter import daily_to_segments, frames_to_tc
from drt.writer import _tc_to_frames
from sync.model import CameraAngle, CameraGroup, Daily, SoundClip, Take

FPS = 24.0
NOMINAL = 24


def _cam(name: str, start: int, dur: int = 240) -> CameraAngle:
    return CameraAngle(path=Path(f"/m/{name}"), fps=FPS, duration_frames=dur,
                       timeline_start_frames=start, audio_channels=2)


def _snd(name: str, start: int, channels: int = 2, dur_ms: float = 10000) -> SoundClip:
    return SoundClip(path=Path(f"/m/{name}"), sample_rate=48000, duration_ms=dur_ms,
                     channels=channels, timeline_start_frames=start)


def _diaria() -> Daily:
    """Duas câmeras (uma com 2 clipes), um som estéreo — o caso comum."""
    a1, a2 = _cam("a1.mov", 0), _cam("a2.mov", 720)
    b1 = _cam("b1.mov", 30)
    s1 = _snd("s1.wav", 0, channels=2)
    return Daily(
        camera_groups=[
            CameraGroup(cameras=[a1, a2], name="CAM A", id="camA"),
            CameraGroup(cameras=[b1], name="CAM B", id="camB"),
        ],
        takes=[Take(sound=s1, cameras=[a1, b1])],
        fps=FPS, name="D01",
    )


class TestOMapeamentoDeVideo:
    def test_uma_track_por_camera_fisica(self):
        segs, _ = daily_to_segments(_diaria())
        vid = [s for s in segs if not s["is_audio"]]
        # CAM A (grupo 0) → track 1 (dois clipes); CAM B (grupo 1) → track 2.
        tracks = {s["clip_name"]: s["track"] for s in vid}
        assert tracks == {"a1.mov": 1, "a2.mov": 1, "b1.mov": 2}

    def test_o_clipe_entra_inteiro_a_100_por_cento(self):
        segs, _ = daily_to_segments(_diaria())
        for s in (x for x in segs if not x["is_audio"]):
            assert s["source_start_frames"] == 0
            assert s.get("speed_ratio", 1.0) in (None, 1.0)


class TestOMapeamentoDeAudio:
    def test_som_multicanal_vira_N_tracks_mono(self):
        segs, _ = daily_to_segments(_diaria())
        aud = [s for s in segs if s["is_audio"]]
        # 1 som estéreo → 2 segmentos, tracks 1 e 2, mesmo arquivo e mesma posição.
        assert len(aud) == 2
        assert sorted(s["track"] for s in aud) == [1, 2]
        assert {s["clip_name"] for s in aud} == {"s1.wav"}
        assert {s["timeline_tc_in"] for s in aud} == {"00:00:00:00"}

    def test_um_som_de_5_canais_ocupa_A1_a_A5(self):
        d = _diaria()
        d.takes[0].sound.channels = 5
        segs, _ = daily_to_segments(d)
        aud = [s for s in segs if s["is_audio"]]
        assert sorted(s["track"] for s in aud) == [1, 2, 3, 4, 5]


class TestAudioDaCamera:
    def test_desligado_por_default_so_o_som_direto(self):
        segs, _ = daily_to_segments(_diaria())
        aud = [s for s in segs if s["is_audio"]]
        # Só o som direto (estéreo → 2 segmentos, tracks 1 e 2). Nada de câmera.
        assert {s["clip_name"] for s in aud} == {"s1.wav"}
        assert sorted(s["track"] for s in aud) == [1, 2]

    def test_ligado_a_camera_fica_ABAIXO_do_som_direto(self):
        # No Resolve vec[0]=A1 (topo): som direto nas PRIMEIRAS tracks (A1..), a
        # câmera nas de baixo. Uma track MONO por câmera física, canal 0.
        segs, _ = daily_to_segments(_diaria(), include_camera_audio=True)
        # O som direto (estéreo) fica em A1/A2.
        snd = sorted(s["track"] for s in segs if s["is_audio"] and s["clip_name"].endswith(".wav"))
        assert snd == [1, 2]
        # A câmera fica ABAIXO: CAM A (grupo 0) → track 3; CAM B (grupo 1) → track 4.
        cam = {}
        for s in segs:
            if s["is_audio"] and s["clip_name"].endswith(".mov"):
                cam.setdefault(s["clip_name"], []).append(s["track"])
        assert cam["a1.mov"] == [3]
        assert cam["a2.mov"] == [3]
        assert cam["b1.mov"] == [4]


class TestOMatchEhTrivial:
    def test_cada_segmento_casa_com_o_proprio_arquivo(self):
        segs, matches = daily_to_segments(_diaria())
        assert len(matches) == len(segs)
        # match_result[i] aponta para o arquivo do segmento[i].
        for m in matches:
            i = m["segment_index"]
            assert m["matched_path"].endswith(segs[i]["clip_name"])


class TestOTimecodeVoltaExato:
    def test_round_trip_com_o_parser_do_writer(self):
        # O adapter ESCREVE o TC; o writer o LÊ de volta. Se os dois discordarem
        # de um frame, o clipe cai deslocado na timeline do Resolve.
        for frames in (0, 1, 23, 24, 25, 719, 720, 86399, 123457):
            tc = frames_to_tc(frames, NOMINAL)
            assert _tc_to_frames(tc, NOMINAL) == frames, f"{frames} → {tc}"

    def test_a_posicao_do_clipe_vira_o_TC_certo(self):
        segs, _ = daily_to_segments(_diaria())
        by_name = {s["clip_name"]: s for s in segs}
        # a2 começa em 720 frames = 30 s a 24 fps → 00:00:30:00.
        assert by_name["a2.mov"]["timeline_tc_in"] == "00:00:30:00"
        # b1 em 30 frames = 1 s + 6 frames → 00:00:01:06.
        assert by_name["b1.mov"]["timeline_tc_in"] == "00:00:01:06"
