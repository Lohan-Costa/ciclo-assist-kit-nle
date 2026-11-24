"""
O TAMANHO DE UMA DIÁRIA — o motor MEDE e AVISA; quem decide é o usuário.

O Premiere bloqueia a movimentação de clipes numa sequência acima de 24 h: o
editor não consegue mover, trocar de track nem copiar para outra timeline, e o
cursor vira o de "proibido", sem aviso nenhum. Uma captação que atravessa a
meia-noite produzia exatamente isso — 24,31 h, medido no material real.

⚠️ HOUVE UMA CORREÇÃO DE RUMO EM 2026-08-05. Antes, o motor RECUSAVA a diária.
Isso o impedia de entregar material que ele havia sincronizado perfeitamente, e a
decisão não é dele: quem sabe se aquilo são dois dias de trabalho ou um dia
esquisito é quem filmou. Agora ele mede, avisa, e oferece a divisão — que roda
sobre o RESULTADO, quando os pares câmera↔som já são conhecidos (ver
`sync/resultsplit.py`).

O que este teste guarda:

  1. `Daily.span_frames` mede do INÍCIO do primeiro ao FIM do último (a duração
     conta: um som que começa dentro do limite pode terminar fora).
  2. O limite é em TIMECODE, na base NOMINAL — a 23,976 non-drop são 2.073.600
     frames, e usar o fps fracionário erraria por 3,5 min na borda.
  3. Estourar as 24 h AVISA e ENTREGA. Nunca recusa.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine
import sync.tcmatch as tcmatch
from media.audio import PCM_RATE, normalize
from sync.model import (
    MAX_DAILY_SPAN_TC_HOURS,
    CameraAngle,
    CameraGroup,
    Daily,
    SoundClip,
    _nominal_base,
)

FPS = 24.0
CAM_DUR_S = 10.0
SND_DUR_S = 40.0


# ── A medida, isolada ────────────────────────────────────────────────────────


def _daily(*starts_and_durs: tuple[int, int], fps: float = FPS) -> Daily:
    cams = [
        CameraAngle(path=Path(f"/fake/cam{i}.mov"), fps=fps, duration_frames=dur,
                    timeline_start_frames=start)
        for i, (start, dur) in enumerate(starts_and_durs)
    ]
    return Daily(camera_groups=[CameraGroup(cameras=cams, name="CAM A", id="g")], fps=fps)


def test_span_vai_do_inicio_do_primeiro_ao_fim_do_ultimo():
    assert _daily((0, 100), (1000, 100)).span_frames == 1100


def test_span_conta_a_duracao_do_som():
    # O som começa DENTRO do limite e termina fora dele — é o fim que o NLE mede.
    snd = SoundClip(path=Path("/fake/s.wav"), sample_rate=48000,
                    duration_ms=60_000, timeline_start_frames=240)
    d = _daily((0, 10))
    d.orphan_sounds.append(snd)
    assert d.span_frames == 240 + 60 * int(FPS)


def test_span_de_diaria_vazia_e_zero():
    assert Daily().span_frames == 0


def test_base_nominal_igual_a_do_tcmatch():
    """`model._nominal_base` é gêmea de `tcmatch.nominal_fps` — o modelo não importa
    numpy/scipy, então a duplicação existe DE PROPÓSITO e é cobrada aqui."""
    for fps in (23.976, 24.0, 25.0, 29.97, 30.0, 47.952, 59.94, 60.0):
        assert _nominal_base(fps) == tcmatch.nominal_fps(fps), fps


def test_o_limite_e_em_timecode_nao_em_tempo_real():
    # A 23,976 non-drop, 24 h de TC = 24·3600·24 frames — 24,024 h REAIS.
    d = _daily((0, 1), fps=24000 / 1001)
    assert d.max_span_frames == 24 * 3600 * 24
    # Usar o fps fracionário daria 2 071 526 — 3,5 min a menos, exatamente na borda.
    assert d.max_span_frames != round(MAX_DAILY_SPAN_TC_HOURS * 3600 * (24000 / 1001))


# ── O aviso ──────────────────────────────────────────────────────────────────


def test_estourar_24h_avisa_nomeando_os_extremos():
    """"Passou de 24 h" não diz o que fazer; "de cam0 a cam1" diz."""
    d = _daily((0, 10), (25 * 3600 * int(FPS), 10))
    aviso = d.span_warning()
    assert aviso is not None
    assert "cam0.mov" in aviso and "cam1.mov" in aviso
    assert "25.0" in aviso


def test_encostado_na_borda_tambem_avisa():
    d = _daily((0, 10), (int(23.9 * 3600 * FPS), 10))
    assert d.span_warning() is not None


def test_diaria_curta_nao_avisa_nada():
    d = _daily((0, 10), (3600 * int(FPS), 10))
    assert d.span_warning() is None


# ── Dentro do `run()`: AVISA, e ENTREGA ──────────────────────────────────────

SND = str(Path("/fake/snd.wav"))
CAM_CEDO = str(Path("/fake/camA/cedo.mov"))     # TC 00:00:05:00
CAM_TARDE = str(Path("/fake/camA/tarde.mov"))   # TC 23:59:59:00 → o dia estoura

# ⚠️ Repare em quão APERTADO é o caso real: 00:00:05 + 23:59:59 dá 24,0025 h — nove
# segundos acima do limite.
_TC = {CAM_CEDO: "00:00:05:00", CAM_TARDE: "23:59:59:00"}


def _probe(path: str) -> dict:
    if path in _TC:
        return {
            "fps": FPS, "has_audio": True, "duration_ms": CAM_DUR_S * 1000,
            "tc_start": _TC[path], "tc_drop_frame": False,
            "size_bytes": 1000, "channels": 2,
        }
    return {
        "fps": None, "has_audio": True, "duration_ms": SND_DUR_S * 1000,
        "tc_start_sec": 0.0, "size_bytes": 1000, "channels": 2,
        "sample_rate": PCM_RATE,
    }


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(engine, "probe", _probe)
    monkeypatch.setattr(
        engine, "extract_pcm",
        lambda path, channel=0: np.zeros(int(SND_DUR_S * PCM_RATE), dtype=np.float32),
    )
    monkeypatch.setattr(engine, "normalize", normalize)


def _entries(*cams: str) -> list[dict]:
    e = [{"path": c, "group_id": "CAM A", "group_order": i} for i, c in enumerate(cams)]
    e.append({"path": SND, "group_id": None, "group_order": None})
    return e


def test_uma_diaria_grande_demais_e_ENTREGUE_com_aviso():
    """⭐ A correção de rumo. O motor sincronizou tudo certo; recusar a entrega
    por causa de um limite do NLE seria jogar fora o trabalho que ele acabou de
    fazer. Ele avisa, e o usuário decide (dividir, ou entregar assim mesmo)."""
    # `timecode` de propósito: com o som cobrindo só os primeiros 40 s, o clipe das
    # 23:59 fica ÓRFÃO e é ancorado no próprio TC — que é a topologia que estica a
    # diária. Num pareamento por onda sobre silêncio os dois cairiam na mesma ilha.
    msgs: list[str] = []
    daily = engine.run(
        _entries(CAM_CEDO, CAM_TARDE), project_name="D", sync_method="timecode",
        progress=lambda m, c, t, o=None: msgs.append(m),
    )
    assert daily.span_frames > daily.max_span_frames, "o caso é mesmo grande demais"
    assert any("24" in m and "Premiere" in m for m in msgs), "e o motor DIZ isso"
    # E o resultado existe: as câmeras estão lá, sincronizadas.
    assert len(daily.cameras) == 2


def test_uma_diaria_normal_sai_calada():
    msgs: list[str] = []
    engine.run(
        _entries(CAM_CEDO), project_name="D", sync_method="timecode",
        progress=lambda m, c, t, o=None: msgs.append(m),
    )
    assert not any("Premiere" in m for m in msgs)
