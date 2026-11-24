"""
As ILHAS do grafo clipe ↔ som, isoladas.

Uma ilha é a componente conexa: um clipe e o som dele, e todos os clipes que
casaram com esse mesmo som. Dentro dela, a posição relativa é função exclusiva dos
`offset_frames` medidos.

⚠️ POR QUE ISTO GANHOU TESTE PRÓPRIO: é aqui que mora a razão de a antiga regra de
não-sobreposição ficar inerte. Num material com um WAV longo — o caso comum de
documentário —, dezenas de clipes da MESMA câmera caem numa ilha só, e o passe que
empurra ilhas nunca compara os membros de uma ilha entre si. O teste
`dezenas_de_clipes_num_wav_longo_sao_uma_ilha_so` guarda exatamente esse fato.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine

FPS = 24.0


def _clip(nome: str, gid: str) -> engine._Clip:
    c = engine._Clip.__new__(engine._Clip)
    c.path = Path(nome)
    c.group_id = gid
    c.sound = None
    c.offset_frames = 0
    c.duration_frames = round(10 * FPS)
    c.timeline_start = 0
    return c


def _som(nome: str) -> engine._Sound:
    s = engine._Sound.__new__(engine._Sound)
    s.path = Path(nome)
    s.duration_s = 600.0
    s.clips = []
    s.timeline_start = 0
    s.placed = False
    s.group_id = "grav"
    return s


def _liga(c: engine._Clip, s: engine._Sound, offset: int) -> None:
    c.sound = s
    c.offset_frames = offset
    s.clips.append(c)


# ── _build_islands ───────────────────────────────────────────────────────────

def test_clipe_sem_som_e_uma_ilha_de_um_elemento():
    c = _clip("solto.mov", "camA")
    ilhas = engine._build_islands({"camA": [c]}, ["camA"])
    assert len(ilhas) == 1
    clips, snds = ilhas[0]
    assert clips == [c] and snds == []


def test_clipe_e_o_som_dele_ficam_na_mesma_ilha():
    c, s = _clip("a.mov", "camA"), _som("s.wav")
    _liga(c, s, 100)
    (clips, snds), = engine._build_islands({"camA": [c]}, ["camA"])
    assert clips == [c] and snds == [s]


def test_cameras_diferentes_no_mesmo_som_se_juntam():
    """É o que faz a ilha ser a unidade de posicionamento: o som costura as duas."""
    a, b, s = _clip("a.mov", "camA"), _clip("b.mov", "camB"), _som("s.wav")
    _liga(a, s, 0)
    _liga(b, s, 240)
    ilhas = engine._build_islands({"camA": [a], "camB": [b]}, ["camA", "camB"])
    assert len(ilhas) == 1
    clips, snds = ilhas[0]
    assert set(clips) == {a, b} and snds == [s]


def test_sons_diferentes_sao_ilhas_diferentes():
    a, b = _clip("a.mov", "camA"), _clip("b.mov", "camA")
    _liga(a, _som("s1.wav"), 0)
    _liga(b, _som("s2.wav"), 0)
    ilhas = engine._build_islands({"camA": [a, b]}, ["camA"])
    assert len(ilhas) == 2


def test_dezenas_de_clipes_num_wav_longo_sao_uma_ilha_so():
    """⭐ O fato que explica o bug de sobreposição.

    Um WAV de 30 min é o par de dezenas de clipes da MESMA câmera. Todos caem numa
    ilha só — e um passe que empurra ILHAS não tem como separá-los. Por isso a
    correção precisou ser INTRA-ilha (`_resolve_source_overlaps`).
    """
    s = _som("diaria.wav")
    clipes = [_clip(f"A{i:03d}.mov", "camA") for i in range(30)]
    for i, c in enumerate(clipes):
        _liga(c, s, i * 100)

    ilhas = engine._build_islands({"camA": clipes}, ["camA"])
    assert len(ilhas) == 1
    clips, _ = ilhas[0]
    assert len(clips) == 30
    assert len({c.group_id for c in clips}) == 1, "todos da MESMA câmera"


# ── _relative_positions ──────────────────────────────────────────────────────

def test_posicao_relativa_sai_dos_offsets():
    s = _som("s.wav")
    a, b = _clip("a.mov", "camA"), _clip("b.mov", "camA")
    _liga(a, s, 100)
    _liga(b, s, 400)
    rel = engine._relative_positions([a, b], [s])
    # o som fica 100 antes de `a`; `b` fica 300 depois de `a`
    assert rel[s] == rel[a] - 100
    assert rel[b] - rel[a] == 300


def test_a_origem_e_arbitraria_mas_as_distancias_nao():
    """A ilha inteira é transladada depois, então trocar a semente não pode mudar
    NADA além do zero da régua."""
    s = _som("s.wav")
    a, b = _clip("a.mov", "camA"), _clip("b.mov", "camA")
    _liga(a, s, 100)
    _liga(b, s, 400)

    r1 = engine._relative_positions([a, b], [s], seed=a)
    r2 = engine._relative_positions([a, b], [s], seed=b)
    assert r1[b] - r1[a] == r2[b] - r2[a]
    assert r1[s] - r1[a] == r2[s] - r2[a]


def test_ilha_vazia_nao_explode():
    assert engine._relative_positions([], []) == {}
