"""
PROGRESSO HONESTO — a barra do sync não pode andar para trás, e nenhuma fase pode
ficar muda.

Contexto (2026-08-04): num material real de 77 proxies RED + 7 WAVs, medido em
95 s, a fase de corroboração levava 28 s — quase um terço — sem emitir NADA,
depois de a barra do pareamento já ter chegado a 100%. Somado a isso, cada troca
de fase zerava a barra. O usuário leu as duas coisas juntas como travamento,
pediu o mesmo sync 6 vezes e esperou 9 minutos.

Estes testes fixam as duas garantias:
  1. `_corroborate_by_delta` FALA (recebe e usa o `emit`);
  2. `_PHASE_BANDS` é uma partição crescente de 0..1, que é o que faz a fração
     geral ser monotônica mesmo com cada fase contando do seu próprio zero.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine
from media.audio import PCM_RATE

FPS = 24.0
REGIME_DELTA = 100.0


def _snd(path: str, tc_sec: float) -> "engine._Sound":
    s = engine._Sound(Path(path), {
        "duration_ms": 40_000, "sample_rate": PCM_RATE, "channels": 2,
        "tc_start_sec": tc_sec,
    })
    s.pcm = np.zeros(int(40.0 * PCM_RATE), dtype=np.float32)  # evita ler disco
    return s


def _clip(path: str, tc_sec: float, snd, *, confidence: float, implied: float):
    c = engine._Clip(Path(path), {
        "duration_ms": 10_000, "has_audio": True, "fps": FPS,
        "tc_start": None, "tc_drop_frame": False, "size_bytes": 1000, "channels": 2,
    }, "g", 0, FPS)
    c.tc_sec = tc_sec
    c.tc_frames = round(tc_sec * FPS)
    c.sound = snd
    c.confidence = confidence
    c.implied_delta = implied
    c.sync_source = "waveform"
    return c


@pytest.fixture(autouse=True)
def sem_disco(monkeypatch):
    """A re-medição não pode tocar em arquivo nenhum — aqui só interessa quem FALA."""
    def fake_sync(*, wav_path, camera_path, fps, ref_pcm, cam_pcm,
                  min_offset_frames=None, max_offset_frames=None):
        return round((REGIME_DELTA + 60.0) * fps), 1.0

    monkeypatch.setattr(engine, "sync_camera_to_wav", fake_sync)
    monkeypatch.setattr(engine, "extract_pcm", lambda p, channel=0: np.zeros(1, np.float32))
    monkeypatch.setattr(engine, "normalize", lambda x: x)


def _cena():
    """Um alvo fora do regime cercado de 3 âncoras que concordam."""
    snd = _snd("/fake/snd.wav", tc_sec=0.0)
    anchors = [
        _clip(f"/fake/a{i}.mov", tc_sec=40.0 + i, snd=snd, confidence=5.0,
              implied=REGIME_DELTA)
        for i in range(3)
    ]
    target = _clip("/fake/target.mov", tc_sec=50.0, snd=snd, confidence=1.0,
                   implied=REGIME_DELTA + 60.0)
    return target, anchors


def test_a_corroboracao_nao_e_muda():
    """A fase que levava 28 s em silêncio agora relata cada clipe conferido."""
    target, anchors = _cena()

    eventos = []
    engine._corroborate_by_delta(
        [target, *anchors], FPS, on_clip=None,
        emit=lambda msg, cur, tot, phase="pair": eventos.append((msg, cur, tot, phase)),
    )

    assert eventos, "a corroboração precisa relatar progresso — era o trecho mudo"
    assert all(e[3] == "verify" for e in eventos), "tudo nesta fase é da faixa 'verify'"
    # O contador cobre TODOS os clipes pareados, não só os que foram re-medidos:
    # uma barra que só andasse nos caros ficaria parada quase a fase inteira.
    assert eventos[-1][1] == eventos[-1][2] == 4
    # E o clipe que exige nova medição — o caro — se anuncia ANTES de custar.
    assert any("Reconferindo" in e[0] and "target.mov" in e[0] for e in eventos)


def test_sem_emit_a_corroboracao_segue_funcionando():
    """`emit` é opcional: o motor não pode depender de quem o observa."""
    target, anchors = _cena()

    engine._corroborate_by_delta([target, *anchors], FPS, on_clip=None)  # sem emit

    assert target.sync_source == "timecode"  # a decisão de sempre, intacta


def test_as_faixas_de_fase_cobrem_0_a_1_sem_buraco_nem_recuo():
    """A partição é o que garante a barra monotônica — cada fase tem o seu trecho.

    Se duas faixas se sobrepusessem, ou se uma começasse antes do fim da anterior,
    a barra voltaria para trás na troca de fase — que é exatamente o defeito que
    `_PHASE_BANDS` existe para matar.
    """
    faixas = list(engine._PHASE_BANDS.values())

    assert faixas[0][0] == 0.0, "a primeira fase começa no zero"
    assert faixas[-1][1] == 1.0, "a última termina em 100%"
    for (lo, hi) in faixas:
        assert lo < hi, "uma fase sem largura não teria como mostrar progresso"
    for (_, hi), (lo_seg, _) in zip(faixas, faixas[1:]):
        assert hi == lo_seg, "a fase seguinte começa exatamente onde a anterior acabou"


def test_a_ordem_das_fases_e_a_ordem_do_sync():
    """As chaves estão na ordem em que o sync as percorre — é o que se lê no código."""
    assert list(engine._PHASE_BANDS) == ["probe", "pair", "verify", "final"]
