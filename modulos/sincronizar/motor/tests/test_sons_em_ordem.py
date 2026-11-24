"""
A lista de sons precisa estar em ordem CRONOLÓGICA — e não estava.

A passada 2 do pareamento monta a janela de desambiguação com `sounds[lo:hi+1]`,
entre o som do vizinho anterior e o do próximo. Isso só faz sentido se a lista
estiver em ordem de gravação. Ela chegava na ordem do PAYLOAD, que é a ordem do
NOME — e o nome de um gravador segue cena e tomada, não relógio: no material real,
`LOCAL-2-005` foi gravado 20 h DEPOIS do `-004`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine


def _som(nome, *, tc=None, bwf=None, dia=0):
    meta = {"duration_ms": 60000.0}
    if tc is not None:
        meta["tc_start_sec"] = tc
    if bwf is not None:
        meta["bwf_date"], meta["bwf_time"] = bwf
    s = engine._Sound(Path(nome), meta)
    s.day_index = dia
    return s


def test_timecode_manda_quando_existe():
    a = _som("LOCAL-2-005.wav", tc=100.0)
    b = _som("LOCAL-2-004.wav", tc=50.0)
    sons = [a, b]                      # ordem do nome: 004 depois de 005? não — a lista vem assim
    engine._ordenar_sons(sons)
    assert [s.path.name for s in sons] == ["LOCAL-2-004.wav", "LOCAL-2-005.wav"]


def test_o_nome_NAO_manda__o_caso_LOCAL-2(monkeypatch):
    """O caso real: `-005` gravado 20 h depois do `-004`. Ordenar por nome poria
    os dois lado a lado e a janela de desambiguação pegaria o intervalo errado."""
    quarto = _som("LOCAL-2-004.wav", bwf=("2025-05-16", "08:00:00"))
    quinto = _som("LOCAL-2-005.wav", bwf=("2025-05-17", "04:00:00"))   # 20 h depois
    outro  = _som("ZOOM0001.wav",    bwf=("2025-05-16", "12:00:00"))   # no MEIO

    sons = [quarto, quinto, outro]     # ordem de nome
    engine._ordenar_sons(sons)
    assert [s.path.name for s in sons] == [
        "LOCAL-2-004.wav", "ZOOM0001.wav", "LOCAL-2-005.wav"
    ], "o relógio de parede tem de reordenar, e o `ZOOM` cai ENTRE os dois"


def test_relogio_de_parede_salva_quem_nao_tem_timecode():
    """Material real: 21 WAVs, NENHUM com timecode, mas todos com
    `hl-AAAA-MM-DD/HH-MM-SS.wav` — a data vem do caminho e a hora do nome."""
    tarde = _som("12-32-53.wav", bwf=("2024-10-25", "12:32:53"))
    cedo  = _som("00-18-57.wav", bwf=("2024-10-25", "00:18:57"))
    sons = [tarde, cedo]
    engine._ordenar_sons(sons)
    assert [s.path.name for s in sons] == ["00-18-57.wav", "12-32-53.wav"]


def test_o_timecode_ganha_do_relogio_de_parede():
    com_tc = _som("com_tc.wav", tc=10.0, bwf=("2024-10-25", "23:00:00"))
    so_parede = _som("so_parede.wav", bwf=("2024-10-25", "01:00:00"))
    sons = [so_parede, com_tc]
    engine._ordenar_sons(sons)
    assert sons[0].path.name == "com_tc.wav", "quem tem TC vem antes de quem só tem parede"


def test_sem_autoridade_nenhuma_a_ordem_de_ENTRADA_e_preservada():
    """Sem relógio, mexer seria pior que não mexer — o usuário montou a lista."""
    sons = [_som("c.wav"), _som("a.wav"), _som("b.wav")]
    engine._ordenar_sons(sons)
    assert [s.path.name for s in sons] == ["c.wav", "a.wav", "b.wav"]


def test_o_dia_desdobrado_entra_na_conta():
    """`tc_abs_sec` já inclui o `day_index` — um som do dia seguinte com TC menor
    ainda tem de vir depois."""
    dia0 = _som("tarde_do_dia_0.wav", tc=80000.0, dia=0)
    dia1 = _som("cedo_do_dia_1.wav", tc=100.0, dia=1)
    sons = [dia1, dia0]
    engine._ordenar_sons(sons)
    assert [s.path.name for s in sons] == ["tarde_do_dia_0.wav", "cedo_do_dia_1.wav"]
