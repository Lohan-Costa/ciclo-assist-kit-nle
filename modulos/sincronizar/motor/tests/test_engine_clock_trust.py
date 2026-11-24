"""
RELÓGIO CORROBORADO NÃO NAGA (`_corroborate_by_delta`).

Quando a forma de onda não confirma um clipe mas o RELÓGIO do regime o posiciona,
o que decide se ele ainda pede revisão é QUÃO forte é esse relógio:

  - Regime corroborado por VÁRIAS âncoras que concordam apertado → o clipe cai no
    relógio, vira ARDÓSIA (`sync_source="timecode"`) e NÃO é sinalizado. Pintar de
    duvidoso um clipe que várias âncoras colocam a frações de frame do lugar ensina
    o usuário a ignorar o aviso quando ele importa. (No material real: os planos de
    abertura do D03, sem sinal de onda, caem certos no relógio da manhã — 6 âncoras
    a ±0,05 s.)
  - Poucas âncoras, ou âncoras que DISCORDAM entre si → sem aval; segue `tc_only`,
    sinalizado. (O 2º gravador da tarde do D03, sem âncora nenhuma.)

Sem mídia: a re-medição (`sync_camera_to_wav`) é monkeypatchada para SEMPRE devolver
um offset que continua discordando do regime — é o que força o caminho de fallback
onde a decisão acima acontece. Constrói-se `_Clip`/`_Sound` à mão para isolar a
lógica de corroboração da correlação.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine
from media.audio import PCM_RATE

FPS = 24.0
REGIME_DELTA = 100.0   # Δ de relógio (câmera adiantada 100 s sobre o gravador)


def _snd(path: str, tc_sec: float) -> "engine._Sound":
    s = engine._Sound(Path(path), {
        "duration_ms": 40_000, "sample_rate": PCM_RATE, "channels": 2,
        "tc_start_sec": tc_sec,
    })
    s.pcm = np.zeros(int(40.0 * PCM_RATE), dtype=np.float32)  # evita ler disco
    return s


def _clip(path: str, tc_sec: float, snd, *, confidence: float, implied: float) -> "engine._Clip":
    c = engine._Clip(Path(path), {
        "duration_ms": 10_000, "has_audio": True, "fps": FPS,
        "tc_start": None, "tc_drop_frame": False, "size_bytes": 1000, "channels": 2,
    }, "g", 0, FPS)
    c.tc_sec = tc_sec
    c.tc_frames = round(tc_sec * FPS)
    c.sound = snd
    c.confidence = confidence
    c.implied_delta = implied
    c.sync_source = "waveform"   # foi pareado pela onda; a corroboração pode rebaixar
    return c


@pytest.fixture(autouse=True)
def force_disagreeing_remeasure(monkeypatch):
    # A re-medição SEMPRE volta um offset cujo Δ implícito segue longe do regime —
    # é o que leva `_corroborate_by_delta` ao fallback do relógio (onde a decisão
    # ardósia-vs-flag mora). Ratio baixo: nada aqui vira âncora por acidente.
    def fake_sync(*, wav_path, camera_path, fps, ref_pcm, cam_pcm,
                  min_offset_frames=None, max_offset_frames=None):
        return round((REGIME_DELTA + 60.0) * fps), 1.0   # implied ≈ regime + 60 s

    monkeypatch.setattr(engine, "sync_camera_to_wav", fake_sync)
    monkeypatch.setattr(engine, "extract_pcm", lambda p, channel=0: np.zeros(1, np.float32))
    monkeypatch.setattr(engine, "normalize", lambda x: x)


def _run(anchors_implied: list[float]):
    """Um alvo (onda fraca, Δ fora do regime) cercado de âncoras com os Δ dados.

    Devolve o `_Clip` alvo depois de `_corroborate_by_delta`.
    """
    snd = _snd("/fake/snd.wav", tc_sec=0.0)
    # Âncoras próximas no tempo (todas dentro de ANCHOR_REACH_S do alvo em tc=50 s).
    anchors = [
        _clip(f"/fake/a{i}.mov", tc_sec=40.0 + i, snd=snd,
              confidence=5.0, implied=d)
        for i, d in enumerate(anchors_implied)
    ]
    target = _clip("/fake/target.mov", tc_sec=50.0, snd=snd,
                   confidence=1.0, implied=REGIME_DELTA + 60.0)
    engine._corroborate_by_delta([target, *anchors], FPS, on_clip=None)
    return target


def test_relogio_bem_corroborado_vira_ardosia_sem_flag():
    # 3 âncoras concordando apertado (Δ = 100 s): relógio sólido.
    target = _run([REGIME_DELTA, REGIME_DELTA, REGIME_DELTA])

    assert target.flagged is False
    assert target.sync_source == "timecode"        # ardósia, não âmbar
    # E ficou onde o relógio manda: predicted = (Δ − snd_tc + cam_tc)·fps.
    assert target.offset_frames == round((REGIME_DELTA - 0.0 + 50.0) * FPS)


def test_poucas_ancoras_segue_sinalizado():
    # Só 2 âncoras (< CLOCK_TRUST_MIN_ANCHORS): mediana frágil, sem aval.
    target = _run([REGIME_DELTA, REGIME_DELTA])

    assert target.flagged is True
    assert target.flag_reason == "tc_only"


def test_ancoras_que_discordam_seguem_sinalizadas():
    # 3 âncoras, mas espalhadas por mais que TC_AGREEMENT_S: relógio não é confiável.
    target = _run([REGIME_DELTA, REGIME_DELTA, REGIME_DELTA + engine.TC_AGREEMENT_S + 2.0])

    assert target.flagged is True
    assert target.flag_reason == "tc_only"


# ─────────────────────────────────────────────────────────────────────────────
# SEM ÂNCORA NENHUMA: o par é DESFEITO, não guardado com um aviso.
#
# ⛔ O DEFEITO QUE ISTO TRANCA (medido em 2026-08-22, D03 de `PROJETO EXEMPLO`):
# os 11 clipes dos cartões a006/a007 ficaram do outro lado de um intervalo de
# 2h06 (o almoço) — fora do alcance de qualquer âncora. O ramo `len(near) < 2`
# mantinha o palpite da correlação e só marcava `unverified`, então eles foram
# ENTREGUES montados na timeline com confiança de 1,01 a 1,28, quando a
# calibração do próprio `TRUST_RATIO` diz que ambíguo é ~1,06.
#
# O editor via uma sequência sincronizada. Não era.
#
# ⚠️ E alargar `ANCHOR_REACH_S` não é o conserto — foi medido e é PIOR: com
# alcance de um dia, o Δ do cartão anterior põe esses clipes a ~514 400 frames
# (5h57) do lugar, agora com `sync_source: timecode` e sem aviso nenhum. Erro
# marcado vira erro confiante.
# ─────────────────────────────────────────────────────────────────────────────

def _run_sem_ancora(confianca_do_alvo: float):
    """Um clipe longe de tudo: nenhuma âncora dentro de `ANCHOR_REACH_S`.

    As âncoras existem (senão a função devolve cedo), mas ficam a mais de uma
    hora dele — exatamente o caso do cartão depois do almoço.
    """
    snd = _snd("/fake/snd.wav", tc_sec=0.0)
    longe = engine.ANCHOR_REACH_S + 600.0
    anchors = [
        _clip(f"/fake/a{i}.mov", tc_sec=40.0 + i, snd=snd,
              confidence=5.0, implied=REGIME_DELTA)
        for i in range(3)
    ]
    alvo = _clip("/fake/orfao.mov", tc_sec=longe, snd=snd,
                 confidence=confianca_do_alvo, implied=REGIME_DELTA + 3600.0)
    snd.clips = [alvo, *anchors]      # o som guarda quem o usa — ver `_desfazer_par`
    engine._corroborate_by_delta([alvo, *anchors], FPS, on_clip=None)
    return alvo, snd


def test_sem_ancora_o_par_FICA__sinalizado():
    """⛔⛔ AQUI JÁ SE TENTOU DESFAZER O PAR, E FOI PIOR (2026-08-22).

    O raciocínio parecia bom: um par de confiança 1,0 é ruído com aparência de
    dado, então melhor entregar sem som. Medido na D03 de `PROJETO EXEMPLO`, isso
    levou a diária de **34 tomadas e 2 órfãos** para **23 e 13**, e o autor viu a
    diferença abrindo o alpha 0.1.20 lado a lado.

    ⭐ O erro foi tratar a escolha como BINÁRIA. A terceira via é sincronizar **e
    marcar**: um clipe posicionado e sinalizado é conferência de segundos, com os
    vizinhos delimitando onde ele pode estar; um bloco de órfãos no fim é trabalho
    manual do zero.

    ⚠️ O par PODE estar errado — o alpha erra igual. O que este teste crava é que
    a resposta para o erro de pareamento **não é apagar o par**.
    """
    c, snd = _run_sem_ancora(confianca_do_alvo=1.0)
    assert c.sound is snd, (
        "o par foi desfeito — foi exatamente esta 'correção' que derrubou a D03 "
        "de 34 tomadas para 23"
    )
    assert c in snd.clips, "e o som tem de continuar sabendo que este clipe o usa"
    assert c.flagged and c.flag_reason == "unverified", (
        "mas ele TEM de ir sinalizado: sincronizar sem avisar é que seria mentir"
    )


def test_sem_ancora_mas_com_onda_forte_nao_e_sinalizado():
    """A correlação que se garante sozinha não precisa de âncora nem de aviso.

    Contrapeso: sinalizar tudo que está longe ensina o editor a ignorar o aviso
    quando ele importa.
    """
    c, snd = _run_sem_ancora(confianca_do_alvo=engine.TRUST_RATIO + 0.5)
    assert c.sound is snd
    assert c in snd.clips
    assert not c.flagged


def test_um_som_pode_servir_VARIOS_clipes_de_camera():
    """⚠️ NÃO existe exclusividade, e não pode passar a existir.

    O caso real (apontado pelo autor em 2026-08-22): numa entrevista o gravador
    roda contínuo enquanto a câmera dá rec/stop — um som legítimo serve muitos
    clipes. Uma versão anterior desta correção chegou a propor 'um som serve um
    clipe', e teria quebrado exatamente esse material.
    """
    snd = _snd("/fake/entrevista.wav", tc_sec=0.0)
    clips = [
        _clip(f"/fake/cam{i}.mov", tc_sec=40.0 + i, snd=snd,
              confidence=5.0, implied=REGIME_DELTA)
        for i in range(4)
    ]
    engine._corroborate_by_delta(clips, FPS, on_clip=None)
    assert all(c.sound is snd for c in clips), (
        "clipes de câmera perderam o som contínuo que compartilhavam"
    )
