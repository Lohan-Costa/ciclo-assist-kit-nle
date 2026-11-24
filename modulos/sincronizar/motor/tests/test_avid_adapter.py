"""
O adapter Diária → segments do `.avb` (Avid Media Composer).

Guarda o mapeamento sem tocar em arquivo nenhum. O que ele protege são as três
coisas que, se saírem erradas, **não dão erro** — a timeline só sai errada:

1. track de áudio abaixo de 1000 vira track de VÍDEO no writer;
2. segmento sem `mob_id` vira GAP em silêncio (um buraco no lugar do clipe);
3. `source_slot_id` errado põe o canal na track errada.

Os números do caso real (`TestOCasoReal`) vieram do primeiro `.avb` que abriu de
verdade no Media Composer do usuário — 13 câmeras + 1 som do MULTCAM, validado na
GUI. Eles ficam aqui para que uma mudança no adapter tenha de explicar por que
mexeu numa timeline que já foi conferida por olho humano.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avid.adapter import SOUND_TRACK_BASE, daily_to_avb_segments, frames_to_tc
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


def _video(segs):
    return [s for s in segs if not s["is_audio"]]


def _audio(segs):
    return [s for s in segs if s["is_audio"]]


class TestOVideo:
    def test_uma_track_por_camera_fisica(self):
        segs, _ = daily_to_avb_segments(_diaria())
        assert {s["clip_name"]: s["track"] for s in _video(segs)} == {
            "a1.mov": 1, "a2.mov": 1, "b1.mov": 2}

    def test_o_clipe_entra_inteiro_a_100_por_cento(self):
        segs, _ = daily_to_avb_segments(_diaria())
        for s in _video(segs):
            assert s["source_start_frames"] == 0
            assert s["has_motion_effect"] is False

    def test_a_posicao_e_o_start_da_timeline(self):
        segs, _ = daily_to_avb_segments(_diaria())
        pos = {s["clip_name"]: s["timeline_tc_in"] for s in _video(segs)}
        assert pos["a1.mov"] == "00:00:00:00"
        assert pos["a2.mov"] == "00:00:30:00"   # 720 frames a 24 = 30 s
        assert pos["b1.mov"] == "00:00:01:06"   # 30 frames = 1 s + 6


class TestOAudio:
    def test_o_som_direto_abre_uma_track_MONO_por_canal(self):
        """Estéreo vira A1 e A2 — duas tracks mono, não uma estéreo."""
        segs, _ = daily_to_avb_segments(_diaria())
        aud = _audio(segs)
        assert len(aud) == 2
        assert [s["track"] for s in aud] == [SOUND_TRACK_BASE, SOUND_TRACK_BASE + 1]

    def test_o_canal_vai_no_source_slot_id_e_NAO_no_numero_da_track(self):
        """⭐ A track diz ONDE o áudio cai; o slot diz QUAL canal da fonte é. Trocar
        os dois põe o canal certo na track errada — e nada acusa."""
        segs, _ = daily_to_avb_segments(_diaria())
        assert [s["source_slot_id"] for s in _audio(segs)] == [1, 2]

    def test_seis_canais_abrem_seis_tracks(self):
        d = _diaria()
        d.takes[0].sound.channels = 6
        segs, _ = daily_to_avb_segments(d)
        aud = _audio(segs)
        assert len(aud) == 6
        assert [s["track"] for s in aud] == [SOUND_TRACK_BASE + i for i in range(6)]
        assert [s["source_slot_id"] for s in aud] == [1, 2, 3, 4, 5, 6]

    def test_a_duracao_do_som_vem_em_frames_a_partir_dos_ms(self):
        segs, _ = daily_to_avb_segments(_diaria())
        assert _audio(segs)[0]["duration_frames"] == 240   # 10 s a 24 fps

    def test_a_duracao_usa_a_taxa_REAL_e_nao_a_nominal(self):
        """⭐ 23,976 e 24 são duas taxas diferentes, e converter milissegundos pela
        NOMINAL estica o clipe. Medido no material: um som de 5700 s saía 137
        quadros — 5,7 s — mais longo do que é. O clamp do writer escondia o erro
        enquanto o som fosse o clipe mais longo da timeline."""
        d = _diaria()
        d.fps = 23.976
        d.takes[0].sound.duration_ms = 5700300.0
        segs, _ = daily_to_avb_segments(d)
        assert _audio(segs)[0]["duration_frames"] == 136670    # e não 136807


class TestOAudioDaCamera:
    def test_desligado_por_padrao(self):
        segs, _ = daily_to_avb_segments(_diaria())
        assert len(_audio(segs)) == 2   # só o som direto

    def test_cada_camera_ganha_um_BLOCO_do_tamanho_da_sua_estrutura(self):
        """Som direto ocupa A1-A2 (2 canais); CAM A (2 canais) fica em A3-A4 e
        CAM B (2 canais) em A5-A6. Nenhum canal se perde."""
        segs, _ = daily_to_avb_segments(_diaria(), include_camera_audio=True)
        cam_aud = [s for s in _audio(segs) if s["clip_name"] != "s1.wav"]
        por_clipe: dict[str, list[int]] = {}
        for s in cam_aud:
            por_clipe.setdefault(s["clip_name"], []).append(s["track"])
        assert por_clipe == {
            "a1.mov": [SOUND_TRACK_BASE + 2, SOUND_TRACK_BASE + 3],
            "a2.mov": [SOUND_TRACK_BASE + 2, SOUND_TRACK_BASE + 3],
            "b1.mov": [SOUND_TRACK_BASE + 4, SOUND_TRACK_BASE + 5],
        }

    def test_o_canal_da_camera_vai_no_slot_e_a_track_e_a_do_bloco(self):
        """⭐ O mesmo canal 1 cai em tracks DIFERENTES conforme a fonte: A1 no som
        direto, A3 na CAM A, A5 na CAM B. É o caso que impede traduzir a saída do
        adapter do DRT — lá os dois tipos de áudio são indistinguíveis."""
        segs, _ = daily_to_avb_segments(_diaria(), include_camera_audio=True)
        canal1 = {(s["clip_name"], s["track"]) for s in _audio(segs)
                  if s["source_slot_id"] == 1}
        assert canal1 == {
            ("s1.wav", SOUND_TRACK_BASE),          # som direto, canal 1 → A1
            ("a1.mov", SOUND_TRACK_BASE + 2),      # CAM A,     canal 1 → A3
            ("a2.mov", SOUND_TRACK_BASE + 2),
            ("b1.mov", SOUND_TRACK_BASE + 4),      # CAM B,     canal 1 → A5
        }

    def test_blocos_de_TAMANHOS_DIFERENTES_nao_se_sobrepoem(self):
        """⭐ A armadilha da alocação: com uma câmera de 2 canais e outra de 4, um
        `base + índice_do_grupo` poria a segunda em cima da primeira. O bloco
        desloca o seguinte pelo TAMANHO dele, não por um lugar na fila."""
        d = _diaria()
        for c in d.camera_groups[1].cameras:
            c.audio_channels = 4
        segs, _ = daily_to_avb_segments(d, include_camera_audio=True)
        cam_aud = [s for s in _audio(segs) if s["clip_name"] != "s1.wav"]
        tracks_a = sorted({s["track"] for s in cam_aud if s["clip_name"].startswith("a")})
        tracks_b = sorted({s["track"] for s in cam_aud if s["clip_name"].startswith("b")})
        assert tracks_a == [SOUND_TRACK_BASE + 2, SOUND_TRACK_BASE + 3]
        assert tracks_b == [SOUND_TRACK_BASE + 4, SOUND_TRACK_BASE + 5,
                            SOUND_TRACK_BASE + 6, SOUND_TRACK_BASE + 7]
        assert not set(tracks_a) & set(tracks_b)

    def test_camera_muda_nao_ocupa_track_nenhuma(self):
        d = _diaria()
        for c in d.camera_groups[0].cameras:
            c.audio_channels = 0
        segs, _ = daily_to_avb_segments(d, include_camera_audio=True)
        cam_aud = [s for s in _audio(segs) if s["clip_name"] != "s1.wav"]
        assert {s["clip_name"] for s in cam_aud} == {"b1.mov"}
        # E a câmera seguinte sobe para o lugar vago, em vez de deixar um buraco.
        assert {s["track"] for s in cam_aud} == {SOUND_TRACK_BASE + 2,
                                                SOUND_TRACK_BASE + 3}

    def test_clipe_com_menos_canais_que_o_bloco_preenche_so_o_que_tem(self):
        """Emitir um canal que não existe na fonte criaria um segmento apontando
        para um slot vazio."""
        d = _diaria()
        d.camera_groups[0].cameras[0].audio_channels = 4   # a1 é mais rica
        d.camera_groups[0].cameras[1].audio_channels = 1   # a2 é mono
        segs, _ = daily_to_avb_segments(d, include_camera_audio=True)
        a2 = [s for s in _audio(segs) if s["clip_name"] == "a2.mov"]
        assert [s["source_slot_id"] for s in a2] == [1]
        # mas o BLOCO continua do tamanho da câmera (4), então CAM B não invade
        b = [s for s in _audio(segs) if s["clip_name"] == "b1.mov"]
        assert min(s["track"] for s in b) == SOUND_TRACK_BASE + 6


class TestAFormaQueOWriterExige:
    def test_todo_segmento_tem_mob_id_NAO_VAZIO(self):
        """⭐ Segmento sem `mob_id` vira GAP no writer — a timeline sai com buracos
        no lugar dos clipes, sem erro nenhum."""
        segs, _ = daily_to_avb_segments(_diaria(), include_camera_audio=True)
        assert segs, "nenhum segmento gerado"
        for s in segs:
            assert s.get("mob_id"), s

    def test_nenhum_segmento_e_gap_transicao_ou_efeito(self):
        """Uma diária sincronizada é corte seco. Os campos existem escritos como
        False de propósito: ausente o writer teria de adivinhar."""
        segs, _ = daily_to_avb_segments(_diaria(), include_camera_audio=True)
        for s in segs:
            assert s["is_gap"] is False
            assert s["is_transition"] is False
            assert s["is_effect"] is False
            assert s["disabled"] is False

    def test_video_nao_carrega_source_slot_id(self):
        segs, _ = daily_to_avb_segments(_diaria())
        assert all("source_slot_id" not in s for s in _video(segs))

    def test_toda_track_de_audio_fica_acima_do_limite_e_a_de_video_abaixo(self):
        """⭐ É o `1000` que separa som de vídeo no writer. Uma track de áudio
        numerada abaixo dele vira uma track de VÍDEO."""
        segs, _ = daily_to_avb_segments(_diaria(), include_camera_audio=True)
        for s in segs:
            if s["is_audio"]:
                assert s["track"] >= SOUND_TRACK_BASE, s
            else:
                assert s["track"] < SOUND_TRACK_BASE, s

    def test_matches_apontam_para_o_arquivo_de_cada_segmento(self):
        segs, matches = daily_to_avb_segments(_diaria(), include_camera_audio=True)
        assert len(matches) == len(segs)
        for m in matches:
            alvo = segs[m["segment_index"]]
            assert Path(m["matched_path"]).name == alvo["clip_name"]


class TestAPosicao:
    def test_o_campo_autoritativo_e_frames_e_o_tc_concorda_com_ele(self):
        """⭐ Dois campos para a mesma posição é a receita clássica de bug. Este
        teste é o que torna a redundância segura: o `timeline_tc_in` existe só para
        o writer do RELINKER, e tem de ser SEMPRE derivável do campo em frames."""
        def ler(tc: str) -> int:
            h, m, s, f = (int(x) for x in tc.split(":"))
            return ((h * 60 + m) * 60 + s) * NOMINAL + f

        segs, _ = daily_to_avb_segments(_diaria(), include_camera_audio=True)
        for s in segs:
            assert ler(s["timeline_tc_in"]) == s["timeline_start_frames"], s


class TestOTimecode:
    def test_round_trip_exato_contra_a_leitura_do_writer(self):
        """O writer posiciona lendo o TC de volta. Se as duas contas divergirem, o
        clipe cai no frame errado — e é a classe de erro que ninguém vê no código."""
        def ler(tc: str) -> int:
            h, m, s, f = (int(x) for x in tc.split(":"))
            return ((h * 60 + m) * 60 + s) * NOMINAL + f

        for frames in (0, 1, 23, 24, 30, 720, 5675, 41713, 57574, 136670):
            assert ler(frames_to_tc(frames, NOMINAL)) == frames

    def test_negativo_nao_vira_timecode_absurdo(self):
        assert frames_to_tc(-5, NOMINAL) == "00:00:00:00"


class TestOCasoReal:
    """Os números do primeiro `.avb` que abriu no Media Composer do usuário
    (MULTCAM: CAM A com 2 clipes, CAM B com 11, ZOOM estéreo). Validado na GUI."""

    def _multcam(self) -> Daily:
        cam_a = [_cam("20260101_C0076-040.mov", 5675, 36000),
                 _cam("20260101_C0077-039.mov", 41713, 14544)]
        posicoes = [(11110, 1237), (15084, 2712), (18263, 1632), (20564, 1813),
                    (23340, 1440), (24899, 1704), (29042, 4453), (34140, 469),
                    (34871, 5568), (43417, 12864), (57574, 4093)]
        cam_b = [_cam(f"20260101_CAM{2774 + i}.mov", st, du)
                 for i, (st, du) in enumerate(posicoes)]
        som = _snd("20260101_REC0034_Tr12.WAV", 0, channels=2,
                   dur_ms=136670 / 23.976 * 1000)
        return Daily(
            camera_groups=[CameraGroup(cameras=cam_a, name="CAM A", id="a"),
                           CameraGroup(cameras=cam_b, name="CAM B", id="b")],
            takes=[Take(sound=som, cameras=[cam_a[0]])],
            fps=23.976, name="SYNC DIA 1",
        )

    def test_duas_tracks_de_video_e_duas_de_som(self):
        segs, _ = daily_to_avb_segments(self._multcam())
        assert sorted({s["track"] for s in _video(segs)}) == [1, 2]
        assert sorted({s["track"] for s in _audio(segs)}) == [1000, 1001]

    def test_treze_cameras_e_um_som_em_dois_canais(self):
        segs, _ = daily_to_avb_segments(self._multcam())
        assert len(_video(segs)) == 13
        assert len(_audio(segs)) == 2

    def test_as_posicoes_batem_com_a_timeline_conferida_no_MC(self):
        """23,976 é NOMINAL 24 no timecode — e é assim que o writer leu ao montar
        a timeline que o usuário conferiu."""
        segs, _ = daily_to_avb_segments(self._multcam())
        pos = {s["clip_name"]: s["timeline_tc_in"] for s in _video(segs)}
        assert pos["20260101_C0076-040.mov"] == "00:03:56:11"    # frame 5675
        assert pos["20260101_CAM2774.mov"] == "00:07:42:22"     # frame 11110
        assert pos["20260101_CAM2784.mov"] == "00:39:58:22"     # frame 57574

    def test_cam_b_entra_em_ordem_cronologica_na_track_2(self):
        """A cronologia é o que impede a câmera de embaralhar — foi ela que o sync
        travou, e o adapter não pode desfazer isso na tradução."""
        segs, _ = daily_to_avb_segments(self._multcam())
        b = [s for s in _video(segs) if s["track"] == 2]
        tcs = [s["timeline_tc_in"] for s in b]
        assert tcs == sorted(tcs)
        assert len(b) == 11
