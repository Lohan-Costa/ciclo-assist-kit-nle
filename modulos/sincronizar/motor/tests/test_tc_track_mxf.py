"""
O TIMECODE DE SISTEMA DO MXF, QUE RESPONDE `00:00:00:00` PARA TODO ARQUIVO.

Existe porque custou um bug (2026-08-14): uma diária inteira de MXF OP-Atom
(mídia do Avid, e o que o Resolve exporta para ele) empilhou no mesmo instante da
timeline. O MediaInfo achava um track de timecode em cada arquivo e devolvia
`00:00:00:00` em todos — não por falha de leitura, mas porque o track que ele
acha é o timecode de SISTEMA do MXF: uma faixa sintética de 120 h que existe em
todo arquivo e não descreve nenhum. O TC de fonte estava lá o tempo todo, nas
tags de stream do ffprobe.

O que este teste guarda: **a distinção não pode ser feita pelo VALOR do TC.**
`00:00:00:00` é um timecode legítimo — há material real começando nele (um MXF
XDCAM drop-frame do acervo de testes). Descartar todo zero curaria o sintoma e
cegaria o app para material bom. O que denuncia a faixa sintética é a EXTENSÃO:
120 h de timecode num arquivo de 98 s.

Os números daqui são REAIS, medidos no material de teste.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media.inspector import _primeiro_int, _tc_track_e_do_clipe


class _Track:
    """O mínimo de um track do MediaInfo: só o `frame_count` importa aqui."""

    def __init__(self, frame_count=None):
        self.frame_count = frame_count


# ── O caso que quebrou ───────────────────────────────────────────────────────


def test_faixa_sintetica_de_120h_nao_e_do_clipe():
    """`A_0001C001_260101_100000_h1DF4.mxf`: 98,833 s a 24 fps = 2372 frames, e um
    TC track de 10.368.000 (as 120 h). 4371× o clipe — não descreve este arquivo."""
    assert _tc_track_e_do_clipe(_Track(10_368_000), 2372) is False


def test_faixa_sintetica_num_arquivo_de_audio():
    """No arquivo só de áudio o MediaInfo junta as duas contagens do track numa
    string (`"10368000 / 5664000"`). A primeira ainda é a faixa de 120 h."""
    assert _tc_track_e_do_clipe(_Track("10368000 / 5664000"), 2832) is False


# ── O material que já funcionava, e não pode regredir ────────────────────────


def test_tc_track_que_cobre_o_clipe_passa():
    """Medido: em .mov, .mp4 e MXF XDCAM o `frame_count` do TC track bate 1,00× com
    o do clipe. É o formato normal, e ele tem de continuar valendo."""
    assert _tc_track_e_do_clipe(_Track(12_844), 12_844) is True   # MXF XDCAM, 23,976
    assert _tc_track_e_do_clipe(_Track(952), 952) is True         # MXF XDCAM, 29,97 drop-frame
    assert _tc_track_e_do_clipe(_Track(38_133), 38_133) is True   # .mov, 23,976


def test_folga_absorve_arredondamento():
    """A duração vem de `duration_ms`, então o número de frames é aproximado. Uma
    diferença de alguns frames é ruído de arredondamento, não faixa sintética."""
    assert _tc_track_e_do_clipe(_Track(12_847), 12_844) is True


def test_sem_dado_para_comparar_o_track_passa():
    """Sem `frame_count` ou sem duração não há o que medir. Na dúvida vale o
    comportamento de sempre — descartar um TC bom é pior que manter a suspeita."""
    assert _tc_track_e_do_clipe(_Track(None), 2372) is True
    assert _tc_track_e_do_clipe(_Track(10_368_000), None) is True


# ── O valor do TC não entra na decisão ───────────────────────────────────────


def test_zero_legitimo_nao_e_julgado_aqui():
    """Há material no acervo que começa em `00:00:00;00` de verdade. A função não
    recebe o VALOR do TC de propósito: é a extensão que decide, e material que
    legitimamente começa no zero passa igual a qualquer outro."""
    assert _tc_track_e_do_clipe(_Track(9_496), 9_496) is True


# ── O parser tolerante de `frame_count` ──────────────────────────────────────


def test_primeiro_int_cobre_as_duas_formas_do_mediainfo():
    """`int` no arquivo de vídeo, string com barra no de áudio."""
    assert _primeiro_int(10_368_000) == 10_368_000
    assert _primeiro_int("10368000 / 5664000") == 10_368_000
    assert _primeiro_int(None) is None
    assert _primeiro_int("") is None


# ── A volta do dia depende de ONDE o relógio do som veio ─────────────────────


def test_som_de_bwf_da_a_volta_pelo_dia_real():
    """`tc_start_sec` de um BWF conta AMOSTRAS desde a meia-noite real — não passa
    por frames, então não herda o 0,1 % do NTSC. A volta é 86 400 s exatos."""
    from sync.engine import _Sound
    from pathlib import Path

    s = _Sound(Path("/x/som.wav"), {"tc_start_sec": 100.0, "duration_ms": 1000})
    s.day_index = 1
    assert s.tc_abs_sec == 100.0 + 86_400.0


def test_som_de_op_atom_da_a_volta_pelo_dia_do_timecode():
    """A track de áudio de um MXF OP-Atom não é BWF: o relógio dela é um TIMECODE,
    e a 23,976 uma volta dura 86 486 s reais, não 86 400. Usar a volta errada
    descolaria o som da câmera em 86 s por dia — e a câmera, no `_Clip`, já dá a
    volta pela do timecode."""
    from sync.engine import _Sound
    from sync.daycycle import tc_day_seconds
    from pathlib import Path

    s = _Sound(Path("/x/A01.mxf"), {"tc_start_sec": 100.0, "duration_ms": 1000,
                                    "tc_sec_fps": 24000 / 1001})
    s.day_index = 1
    esperado = 100.0 + tc_day_seconds(24000 / 1001)
    assert s.tc_abs_sec == esperado
    assert abs(esperado - (100.0 + 86_400.0)) > 80   # a diferença é real, não ruído


def test_a_24_cravado_as_duas_voltas_coincidem():
    """Sem NTSC não há 0,1 %, e a distinção acima não muda nada — é o caso do
    material de 24 fps, onde o conserto do OP-Atom foi medido."""
    from sync.engine import _Sound
    from pathlib import Path

    bwf = _Sound(Path("/x/s.wav"), {"tc_start_sec": 0.0, "duration_ms": 1})
    mxf = _Sound(Path("/x/s.mxf"), {"tc_start_sec": 0.0, "duration_ms": 1, "tc_sec_fps": 24.0})
    bwf.day_index = mxf.day_index = 1
    assert bwf.tc_abs_sec == mxf.tc_abs_sec
