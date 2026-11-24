"""
Dois clipes da MESMA câmera, no MESMO som, sobrepostos.

⭐ O BURACO QUE ISTO FECHA: `_resolve_track_overlaps` empurra ILHAS e compara cada
uma só contra as já posicionadas — nunca contra os membros dela mesma. Como a ilha é
a componente conexa do grafo clipe↔som, um WAV de 30 min põe dezenas de clipes da
mesma câmera numa ilha só, e a regra ficava inerte justamente no caso mais comum de
documentário. Uma diária real veio com a câmera empilhada por causa disso.

A leitura que organiza estes testes: uma sobreposição dessas **não é um problema de
arrumação — é a prova de que um dos dois casou errado**. Por isso o passe mantém
aquele em que se confia e RE-MEDE o outro; e quando não dá, SINALIZA em vez de
esconder.

⚠️ E corrige em `offset_frames`, nunca em `timeline_start`: dentro da ilha a posição
é função dos offsets, e mexer na posição faria o `.prproj` sair com o sync mentindo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine

FPS = 24.0
DUR = round(10 * FPS)          # 10 s por clipe


def _som(nome="diaria.wav"):
    s = engine._Sound.__new__(engine._Sound)
    s.path = Path(nome)
    s.duration_s = 1800.0
    s.clips = []
    s.timeline_start = 0
    s.placed = False
    s.group_id = "grav"
    s.pcm = None
    return s


def _clip(nome, gid, offset, *, conf=2.0, dur=DUR, pinned=False, delta=None):
    c = engine._Clip.__new__(engine._Clip)
    c.path = Path(nome)
    c.group_id = gid
    c.duration_frames = dur
    c.duration_s = dur / FPS
    c.offset_frames = offset
    c.confidence = conf
    c.flagged = False
    c.flag_reason = None
    c.sync_source = "waveform"
    c.pinned = pinned
    c.implied_delta = delta
    c.timeline_start = 0
    c.pcm = None
    c.sound = None
    c.has_audio = True
    return c


def _monta(clipes, som):
    for c in clipes:
        c.sound = som
        som.clips.append(c)
    gid = clipes[0].group_id
    return {gid: list(clipes)}, [gid]


def _roda(groups, order, monkeypatch, medicao=None, metodo="hybrid"):
    """Roda o passe com a re-medição controlada pelo teste (sem tocar em disco)."""
    chamadas = []

    def falso_measure(c, snd, fps, near_frames=None, half_frames=0):
        chamadas.append((c.path.name, near_frames, half_frames))
        return medicao(c) if callable(medicao) else medicao

    monkeypatch.setattr(engine, "_measure_window", falso_measure)
    engine._resolve_source_overlaps(
        groups, order, FPS, lambda *a, **k: None, None, metodo
    )
    return chamadas


def _posicoes(clipes, som):
    """Onde cada clipe cai, um em relação ao outro (o som na origem)."""
    return {c.path.name: c.offset_frames for c in clipes}


def _ha_sobreposicao(clipes):
    ivs = sorted((c.offset_frames, c.offset_frames + c.duration_frames) for c in clipes)
    return any(ivs[i][1] > ivs[i + 1][0] for i in range(len(ivs) - 1))


# ── O caso central ───────────────────────────────────────────────────────────

def test_o_de_maior_confianca_fica_e_o_outro_e_remedido(monkeypatch):
    som = _som()
    bom = _clip("bom.mov", "camA", 0, conf=4.0)
    ruim = _clip("ruim.mov", "camA", 100, conf=1.6)     # invade o `bom`
    groups, order = _monta([bom, ruim], som)

    # A re-medição acha lugar logo depois do `bom`, com confiança boa.
    _roda(groups, order, monkeypatch, medicao=(DUR + 5, 3.0))

    assert bom.offset_frames == 0, "o clipe confiável não pode sair do lugar"
    assert ruim.offset_frames == DUR + 5
    assert not ruim.flagged, "a re-medição convenceu — não há o que sinalizar"
    assert not _ha_sobreposicao([bom, ruim])


def test_sem_espaco_encosta_e_sinaliza(monkeypatch):
    """Quando não sobra vão, a resposta honesta é encostar E avisar."""
    som = _som()
    bom = _clip("bom.mov", "camA", 0, conf=4.0)
    ruim = _clip("ruim.mov", "camA", 50, conf=1.6)
    groups, order = _monta([bom, ruim], som)

    _roda(groups, order, monkeypatch, medicao=None)      # a medição não achou nada

    assert ruim.flagged and ruim.flag_reason == "overlap_pushed"
    assert ruim.offset_frames == DUR, "encostado logo depois do confiável"
    assert not _ha_sobreposicao([bom, ruim])


def test_remedicao_fraca_e_recusada(monkeypatch):
    """Abaixo de FLAG_RATIO a medição não vale mais que o encaixe — e o clipe
    precisa ficar marcado para revisão."""
    som = _som()
    bom = _clip("bom.mov", "camA", 0, conf=4.0)
    ruim = _clip("ruim.mov", "camA", 100, conf=1.6)
    groups, order = _monta([bom, ruim], som)

    _roda(groups, order, monkeypatch, medicao=(9999, engine.FLAG_RATIO - 0.01))

    assert ruim.flagged and ruim.flag_reason == "overlap_pushed"
    assert ruim.offset_frames == DUR
    assert ruim.offset_frames != 9999, "posição de medição fraca não pode ser usada"


# ── Quem é âncora ────────────────────────────────────────────────────────────

def test_o_clipe_fixado_pelo_usuario_NUNCA_se_move(monkeypatch):
    """A única verdade humana no conjunto. Mover o que uma pessoa confirmou é pior
    que o sintoma que se está consertando."""
    som = _som()
    fixado = _clip("fixado.mov", "camA", 100, conf=engine.PINNED_CONFIDENCE, pinned=True)
    outro = _clip("outro.mov", "camA", 0, conf=99.0)     # confiança de saturação
    groups, order = _monta([fixado, outro], som)

    chamadas = _roda(groups, order, monkeypatch, medicao=(500, 3.0))

    assert fixado.offset_frames == 100, "o clipe fixado saiu do lugar"
    assert not fixado.flagged
    assert "fixado.mov" not in [n for n, _, _ in chamadas], "nem re-medir o fixado"
    assert not _ha_sobreposicao([fixado, outro])


def test_a_saturacao_99_nao_ganha_de_uma_confianca_real(monkeypatch):
    """99 é 'não havia concorrente', não uma nota alta. Tratado como platô, o
    desempate vai para o critério seguinte em vez de premiar a saturação."""
    som = _som()
    # Sem `implied_delta` nos dois, a regra do relógio empata e a decisão desce para
    # a duração (regra 4) — que é o que se quer isolar aqui.
    saturado = _clip("saturado.mov", "camA", 100, conf=99.0, dur=DUR)
    solido = _clip("solido.mov", "camA", 0, conf=99.0, dur=DUR * 2)
    groups, order = _monta([saturado, solido], som)
    _roda(groups, order, monkeypatch, medicao=None)

    assert solido.offset_frames == 0, "o mais longo tinha de ser a âncora"
    assert saturado.flagged


def test_o_relogio_do_conjunto_desempata_antes_da_duracao(monkeypatch):
    """Entre dois clipes igualmente (in)confiáveis, ganha o que concorda com o Δ
    típico das âncoras — mesmo sendo o mais curto."""
    som = _som()
    # a âncora confiável define o Δ típico do conjunto: 10.0
    ancora = _clip("ancora.mov", "camA", -DUR * 3, conf=4.0, delta=10.0)
    concorda = _clip("concorda.mov", "camA", 0, conf=2.0, delta=10.0, dur=DUR)
    discorda = _clip("discorda.mov", "camA", 50, conf=2.0, delta=900.0, dur=DUR * 2)
    groups, order = _monta([ancora, concorda, discorda], som)

    _roda(groups, order, monkeypatch, medicao=None)

    assert concorda.offset_frames == 0, "quem concorda com o relógio devia ficar"
    assert discorda.flagged


def test_modo_timecode_puro_nao_le_audio(monkeypatch):
    """O modo TC tem contrato de não tocar no áudio da câmera. Ali a correção é só
    encaixe — e o flag conta a história."""
    som = _som()
    a = _clip("a.mov", "camA", 0, conf=engine.PINNED_CONFIDENCE)
    b = _clip("b.mov", "camA", 100, conf=engine.PINNED_CONFIDENCE)
    groups, order = _monta([a, b], som)

    chamadas = _roda(groups, order, monkeypatch, medicao=(500, 5.0), metodo="timecode")

    assert chamadas == [], "o modo timecode não pode ler áudio de câmera"
    assert not _ha_sobreposicao([a, b])
    assert b.flagged and b.flag_reason == "overlap_pushed"


# ── Invariantes ──────────────────────────────────────────────────────────────

def test_cameras_DIFERENTES_podem_se_sobrepor(monkeypatch):
    """Duas câmeras filmando a mesma cena se sobrepõem o tempo todo — é o ponto do
    multicâmera. O passe não pode encostar nelas."""
    som = _som()
    a = _clip("a.mov", "camA", 0, conf=3.0)
    b = _clip("b.mov", "camB", 0, conf=3.0)
    a.sound = b.sound = som
    som.clips.extend([a, b])
    groups, order = {"camA": [a], "camB": [b]}, ["camA", "camB"]

    _roda(groups, order, monkeypatch, medicao=(999, 9.0))

    assert a.offset_frames == 0 and b.offset_frames == 0
    assert not a.flagged and not b.flagged


def test_e_idempotente(monkeypatch):
    """Rodar duas vezes não pode continuar mexendo — senão o resultado depende de
    quantas vezes o motor rodou."""
    som = _som()
    bom = _clip("bom.mov", "camA", 0, conf=4.0)
    ruim = _clip("ruim.mov", "camA", 100, conf=1.6)
    groups, order = _monta([bom, ruim], som)

    _roda(groups, order, monkeypatch, medicao=None)
    depois_da_1a = _posicoes([bom, ruim], som)
    _roda(groups, order, monkeypatch, medicao=None)
    assert _posicoes([bom, ruim], som) == depois_da_1a


def test_uma_fila_inteira_se_desempilha(monkeypatch):
    """O caso do material real: vários clipes da mesma câmera num WAV longo, todos
    caídos por cima uns dos outros."""
    som = _som()
    clipes = [_clip(f"A{i}.mov", "camA", i * 5, conf=2.0 + i * 0.1) for i in range(6)]
    groups, order = _monta(clipes, som)

    _roda(groups, order, monkeypatch, medicao=None)

    assert not _ha_sobreposicao(clipes), "sobrou sobreposição na mesma câmera"
    assert sum(1 for c in clipes if c.flagged) >= 1, "o motor tem de avisar"


def test_a_correcao_e_no_offset_e_nao_na_posicao(monkeypatch):
    """⚠️ O invariante do módulo. `timeline_start` é derivado depois; mexer nele
    aqui faria o export sair com `sync_offset_frames` inconsistente."""
    som = _som()
    bom = _clip("bom.mov", "camA", 0, conf=4.0)
    ruim = _clip("ruim.mov", "camA", 100, conf=1.6)
    ruim.timeline_start = 777
    groups, order = _monta([bom, ruim], som)

    _roda(groups, order, monkeypatch, medicao=None)

    assert ruim.offset_frames != 100, "o offset é que devia ter mudado"
    assert ruim.timeline_start == 777, "o passe não pode tocar em timeline_start"


def test_clipe_sozinho_na_camera_nao_e_tocado(monkeypatch):
    som = _som()
    a = _clip("a.mov", "camA", 42, conf=1.0)
    groups, order = _monta([a], som)
    _roda(groups, order, monkeypatch, medicao=(0, 9.0))
    assert a.offset_frames == 42 and not a.flagged


def test_vao_ABERTO_nao_vira_NaN(monkeypatch):
    """⚠️ Regressão vinda do material real, não de teste sintético.

    O vão antes do primeiro clipe (e depois do último) é ABERTO — `±infinito`. Ao
    virar janela de busca, `(-inf + inf)` dá NaN e o `_measure_window` estoura com
    `cannot convert float NaN to integer`. Quem fecha o vão é o próprio som: o
    clipe tem de caber dentro dele.
    """
    som = _som()
    som.duration_s = 60.0
    ancora = _clip("ancora.mov", "camA", 0, conf=9.0)
    solto = _clip("solto.mov", "camA", 10, conf=1.6)     # cai no vão aberto à esquerda
    groups, order = _monta([ancora, solto], som)

    vistos = []

    def medicao(c):
        return None

    def falso(c, snd, fps, near_frames=None, half_frames=0):
        # o que o `_measure_window` real faria: converter para int
        vistos.append((near_frames, half_frames))
        int(near_frames), int(half_frames)          # explode se vier NaN/inf
        return None

    monkeypatch.setattr(engine, "_measure_window", falso)
    engine._resolve_source_overlaps(
        groups, order, FPS, lambda *a, **k: None, None, "hybrid"
    )
    assert vistos, "a re-medição precisava ter sido tentada"
    assert not _ha_sobreposicao([ancora, solto])
