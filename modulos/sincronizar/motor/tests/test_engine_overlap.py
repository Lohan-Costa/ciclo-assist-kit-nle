"""
A REGRA: dois clipes da MESMA câmera (nem dois sons) não se sobrepõem na timeline.

Uma câmera não grava dois arquivos ao mesmo tempo; o gravador não grava dois sons
ao mesmo tempo. Na timeline isso é uma track só, e uma track não tem dois clipes no
mesmo instante. Quando o TC (ou o sync) os põe sobrepostos, o passe
`_resolve_track_overlaps` empurra a tomada de trás para a frente — a UNIDADE inteira
(clipe + som), então o sync se preserva.

⭐ Exceção (2026-10-21): quando o conflito é só entre clipes de câmera COM TC, o TC
vence — o seguinte fica por cima e o de antes é marcado `overlap_cut` (câmera lenta
invade o TC da tomada seguinte; caso M05 do laboratório).

Sem mídia real: `probe` sintético, `extract_pcm` só para o som (modo TC não lê
câmera).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine
from media.audio import PCM_RATE, normalize

FPS = 24.0
# Mesma câmera física (mesmo group_id), dois arquivos com TC que se sobrepõe:
# A [00:05, 00:15]s, B [00:10, 00:20]s → invasão de [10, 15]s.
# str(Path(...)) (não a literal crua): o engine guarda `c.path` como Path e
# compara via str(c.path) — no Windows isso normaliza "/" para "\", então a
# constante do teste precisa passar pela mesma normalização pra continuar
# batendo com o que o engine devolve.
CAM_A = str(Path("/fake/camA/a1.mov"))
CAM_B = str(Path("/fake/camA/a2.mov"))
SND_A = str(Path("/fake/snd_a.wav"))   # TC 5 s — cobre A
SND_B = str(Path("/fake/snd_b.wav"))   # TC 10 s — cobre B
DUR_S = 10.0

_TC = {CAM_A: "00:00:05:00", CAM_B: "00:00:10:00"}
_SND_TC = {SND_A: 5.0, SND_B: 10.0}


def _probe(path: str) -> dict:
    if path in _TC:
        return {
            "fps": FPS, "has_audio": True, "duration_ms": DUR_S * 1000,
            "tc_start": _TC[path], "tc_drop_frame": False,
            "size_bytes": 1000, "channels": 2,
        }
    return {
        "fps": None, "has_audio": True, "duration_ms": DUR_S * 1000,
        "tc_start_sec": _SND_TC[path], "size_bytes": 1000,
        "channels": 2, "sample_rate": PCM_RATE,
    }


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(engine, "probe", _probe)
    monkeypatch.setattr(
        engine, "extract_pcm",
        lambda p, channel=0: np.zeros(int(DUR_S * PCM_RATE), dtype=np.float32),
    )
    monkeypatch.setattr(engine, "normalize", normalize)


def _entries():
    # Os dois clipes de câmera na MESMA fonte ("camA"); dois sons soltos.
    return [
        {"path": CAM_A, "group_id": "camA", "group_order": 0},
        {"path": CAM_B, "group_id": "camA", "group_order": 1},
        {"path": SND_A, "group_id": None, "group_order": None},
        {"path": SND_B, "group_id": None, "group_order": None},
    ]


def _cam(daily, path):
    return next(c for g in daily.camera_groups for c in g.cameras if str(c.path) == path)


def test_dois_clipes_com_tc_ficam_no_tc_e_o_cortado_e_marcado():
    """Era "a mesma câmera não se sobrepõe" (B empurrado para o fim de A). Desde
    2026-10-21 (decisão do autor, caso M05 do laboratório) o TC vence: B fica no TC
    dele, por cima do fim de A, e A sai MARCADO para o editor revisar o corte."""
    daily = engine.run(_entries(), fps=FPS, sync_method="timecode")

    a = _cam(daily, CAM_A)
    b = _cam(daily, CAM_B)

    assert b.timeline_start_frames - a.timeline_start_frames == round(5 * FPS), "5 s de TC entre os dois"
    assert a.flagged and a.flag_reason == "overlap_cut"
    assert b.sync_offset_frames == 0


def _clip(name: str, start_s: float, dur_s: float, track: str = "camA"):
    """Um `_Clip` pronto para o passe de sobreposição, sem passar pelo motor."""
    c = engine._Clip.__new__(engine._Clip)
    c.path = Path(name)
    c.group_id = track
    c.duration_s = dur_s
    c.duration_frames = round(dur_s * FPS)
    c.timeline_start = round(start_s * FPS)
    return c


def test_o_que_cabe_num_buraco_fica_no_buraco():
    """⭐ O bug medido na BOLIVIA (2026-08-04): `A002_A041` (3,5 s, órfão por ser
    curto demais para sincronizar) cabia entre `A040` e `A042` e ia parar 53 min à
    frente.

    A causa era guardar só o ÚLTIMO FIM de cada track. Uma tomada longa deixa
    BURACOS entre os seus clipes, e quem chegava depois na fila era empurrado para
    além da tomada inteira — mesmo com o buraco livre bem na frente dele.
    """
    # Uma tomada de três clipes com buracos de ~2 min entre eles…
    longa = [_clip("a.mov", 0, 60), _clip("b.mov", 200, 60), _clip("c.mov", 400, 60)]
    # …e um clipe curto que cabe FOLGADO no primeiro buraco.
    curto = _clip("orfao.mov", 110, 5)

    engine._resolve_track_overlaps([(longa, []), ([curto], [])], [], FPS)

    assert curto.timeline_start == round(110 * FPS), "cabia — não podia sair do lugar"
    assert [c.timeline_start for c in longa] == [0, round(200 * FPS), round(400 * FPS)]


def test_o_que_nao_cabe_no_buraco_pula_para_o_proximo():
    """Empurrar continua sendo o comportamento — só que para o MENOR lugar livre,
    não para depois de tudo."""
    longa = [_clip("a.mov", 0, 60), _clip("b.mov", 100, 60), _clip("c.mov", 400, 60)]
    # 50 s não cabem no buraco de 40 s entre `a` e `b`; cabem no seguinte.
    grande = _clip("g.mov", 70, 50)

    engine._resolve_track_overlaps([(longa, []), ([grande], [])], [], FPS)

    assert grande.timeline_start == round(160 * FPS), "encostou no fim de `b`"


def test_o_empurrao_repete_ate_parar_de_colidir():
    """Um empurrão pode criar uma colisão NOVA, que não existia na posição original.

    A tomada já posicionada tem DOIS clipes com um buraco de 10 s entre eles
    (0→60 e 70→130). O invasor (50→65) só encosta no primeiro. Empurrado o mínimo,
    ele cai em 60→75 — em cima do SEGUNDO, que antes ele nem tocava. Uma passada só
    entregaria a sobreposição de volta.
    """
    tomada = [_clip("o1.mov", 0, 60), _clip("o2.mov", 70, 60)]
    invasor = _clip("i.mov", 50, 15)

    engine._resolve_track_overlaps([(tomada, []), ([invasor], [])], [], FPS)

    assert invasor.timeline_start == round(130 * FPS), "passou dos DOIS clipes"


def test_tracks_diferentes_nao_disputam_espaco():
    """Duas câmeras FÍSICAS diferentes são duas tracks — elas gravam ao mesmo tempo,
    e é para isso que existe o multicâmera."""
    cam_a = _clip("a.mov", 0, 60, track="camA")
    cam_b = _clip("b.mov", 10, 60, track="camB")

    engine._resolve_track_overlaps([([cam_a], []), ([cam_b], [])], [], FPS)

    assert cam_b.timeline_start == round(10 * FPS), "outra câmera, outra track"


def test_a_unidade_anda_inteira_e_o_sync_interno_se_preserva():
    """Empurrar uma tomada move o clipe E o som pelo mesmo Δ — senão o passe que
    resolve a track destruiria a sincronia que o motor acabou de medir."""
    ocupante = _clip("ocupa.mov", 0, 60)
    invasor = _clip("invade.mov", 30, 60)
    som = engine._Sound.__new__(engine._Sound)
    som.path = Path("som.wav")
    som.duration_s = 60.0
    som.timeline_start = round(25 * FPS)   # 5 s antes do clipe da tomada
    # A track do som é POR GRAVADOR (dois gravadores podem rodar ao mesmo tempo),
    # então o `_Sound` carrega a fonte de onde veio. Este fixture pula o `__init__`,
    # daí precisar declarar aqui.
    som.group_id = "gravador"

    antes = invasor.timeline_start - som.timeline_start
    engine._resolve_track_overlaps([([ocupante], []), ([invasor], [som])], [], FPS)

    assert invasor.timeline_start == round(60 * FPS)
    assert invasor.timeline_start - som.timeline_start == antes, "o Δ interno é sagrado"


def test_o_som_de_cada_tomada_acompanha_o_seu_clipe():
    """Com o TC vencendo, cada som fica com a SUA tomada (aqui cada WAV é um gravador
    próprio — `group_id` = o arquivo —, então eles não disputam trilha)."""
    daily = engine.run(_entries(), fps=FPS, sync_method="timecode")

    sounds = sorted(
        (t.sound for t in daily.takes), key=lambda s: s.timeline_start_frames
    )
    assert len(sounds) == 2
    first, second = sounds
    assert second.timeline_start_frames - first.timeline_start_frames == round(5 * FPS)


def test_dois_clipes_com_tc_o_tc_vence_e_o_cortado_e_marcado():
    """⭐ Decisão do autor (2026-10-21), medida no caso M05 do laboratório: uma câmera
    lenta dura mais no arquivo do que na cena e INVADE o TC da tomada seguinte. Com TC
    nos dois, o seguinte fica no TC dele e o de antes é marcado para revisão."""
    lento = _clip("lento.mov", 0, 40)        # 10 s de cena a 4× = 40 s de arquivo
    seguinte = _clip("seguinte.mov", 30, 8)  # TC 30 s depois do primeiro
    for c in (lento, seguinte):
        c.tc_sec, c.flagged, c.flag_reason = 1.0, False, None

    engine._resolve_track_overlaps([([lento], []), ([seguinte], [])], [], FPS)

    assert seguinte.timeline_start == round(30 * FPS), "o TC vence: não empurra"
    assert lento.flagged and lento.flag_reason == "overlap_cut"
    assert not seguinte.flagged


def test_sem_tc_continua_empurrando():
    a, b = _clip("a.mov", 0, 40), _clip("b.mov", 30, 8)
    for c in (a, b):
        c.tc_sec, c.flagged, c.flag_reason = None, False, None
    engine._resolve_track_overlaps([([a], []), ([b], [])], [], FPS)
    assert b.timeline_start == round(40 * FPS)
    assert not a.flagged
