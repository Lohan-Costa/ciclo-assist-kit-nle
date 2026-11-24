"""
As regras de relógio, agora num lugar só.

Estavam triplicadas (`engine._tc_usable`, `engine._wall_clock_abs`,
`dailysplit._wall_clock`, `dailysplit._clock_stopped`) — duas delas idênticas byte a
byte. Regra duplicada é regra que diverge, e esta decide onde cada clipe pousa.
Os testes guardam os CASOS REAIS que ensinaram cada uma.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync import chronology
from sync.chronology import clock_stopped, tc_usable, wall_clock_abs


# ── tc_usable ────────────────────────────────────────────────────────────────

def test_relogio_que_anda_serve():
    assert tc_usable([1.0, 2.0, 3.0], [24, 48, 72])


def test_o_drone_que_grava_tudo_em_zero_nao_serve():
    """Caso real: 8 arquivos com `00:00:00:00`. Um relógio parado empilharia a
    fonte inteira na origem."""
    assert not tc_usable([0.0] * 8, [0] * 8)


def test_um_clipe_sem_tc_derruba_a_fonte_inteira():
    """A exigência é 'TODOS têm TC' — meio relógio não é relógio."""
    assert not tc_usable([1.0, None, 3.0], [24, None, 72])


def test_sem_clipe_nenhum_nao_serve():
    assert not tc_usable([], [])


# ── clock_stopped ────────────────────────────────────────────────────────────

def test_o_iphone_com_102_arquivos_iguais_esta_parado():
    """Caso real: 102 transcodados a `00:00:00:00` viraram ÂNCORA FALSA e puxaram
    140 arquivos para uma diária só."""
    assert clock_stopped([0.0] * 102)


def test_um_arquivo_so_nunca_e_relogio_parado():
    """Com um arquivo não há como saber se o relógio anda — e acusar seria pior."""
    assert not clock_stopped([0.0])


def test_relogio_que_avanca_nao_esta_parado():
    assert not clock_stopped([1.0, 2.0])


# ── wall_clock_abs ───────────────────────────────────────────────────────────

def test_bwf_completo_vira_instante():
    t = wall_clock_abs({"bwf_date": "2024-10-25", "bwf_time": "08:37:20"})
    assert t is not None
    outro = wall_clock_abs({"bwf_date": "2024-10-25", "bwf_time": "08:37:21"})
    assert outro - t == 1.0


def test_data_do_NOME_serve_quando_nao_ha_bwf():
    assert wall_clock_abs({"name_date": "2024-10-25", "name_time": "08:37:20"}) is not None


def test_o_bwf_ganha_do_nome():
    """O que o gravador escreveu dentro do arquivo vale mais que o nome dele."""
    so_bwf = wall_clock_abs({"bwf_date": "2024-10-25", "bwf_time": "08:00:00"})
    ambos = wall_clock_abs({
        "bwf_date": "2024-10-25", "bwf_time": "08:00:00",
        "name_date": "2020-01-01", "name_time": "00:00:00",
    })
    assert ambos == so_bwf


def test_data_PARCIAL_da_RED_nao_serve():
    """A RED escreve `05-17`, sem ano. Mês/dia sozinho não atravessa a virada do
    ano — melhor `None` e cair na janela das câmeras do que fingir uma reta."""
    assert wall_clock_abs({"name_date": "05-17", "name_time": "12:00:00"}) is None


def test_sem_hora_nao_serve():
    assert wall_clock_abs({"bwf_date": "2024-10-25"}) is None


def test_lixo_nao_explode():
    assert wall_clock_abs({}) is None
    assert wall_clock_abs({"bwf_date": "nao-e-data", "bwf_time": "25:99:99"}) is None


# ── as bases oferecidas ──────────────────────────────────────────────────────

def test_camera_nunca_ordena_por_bwf_e_som_nunca_por_nome():
    """A assimetria medida em material real: o nome de um gravador segue cena e
    tomada, não o relógio (`LOCAL-2-005` foi gravado 20 h depois do `-004`)."""
    assert "bwf" not in chronology.BASES_CAMERA
    assert "name" not in chronology.BASES_SOM
    assert "free" in chronology.BASES_CAMERA and "free" in chronology.BASES_SOM


def test_data_de_criacao_nao_e_uma_base():
    """`recorded_at` foi testada e REJEITADA: relógio não-monotônico, e em PROXY
    traz a data do transcode. Não pode reaparecer como opção por descuido."""
    for base in chronology.BASES_CAMERA + chronology.BASES_SOM:
        assert "record" not in base and "creat" not in base
