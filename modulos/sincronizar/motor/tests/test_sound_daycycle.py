"""
DE QUE DIA É ESTE SOM? — a leitura do chunk bext do BWF.

O som não tem ordem confiável no nome: no material real, `LOCAL-2-005` é o quinto
arquivo e foi gravado 20 h DEPOIS do quarto. E o timecode do gravador também volta
a zero à meia-noite. Sem uma data, um som da madrugada seguinte é indistinguível
de um som da véspera.

O BWF resolve: `OriginationDate`/`OriginationTime` são escritos pelo gravador no
instante da gravação, vivem DENTRO do arquivo e sobrevivem a cópia, renomeação e
troca de disco. É o único metadado de data que o material real tem — o vídeo chega
transcodado, sem data nenhuma.

⚠️ A HORA DE PAREDE NÃO É O TIMECODE. Medido: parede 23:57:02 com TC 23:16:57 —
~40 min de distância, porque o TC vem de um jam sync e a parede do relógio interno
do gravador. A meia-noite do TC e a meia-noite real acontecem em momentos
DIFERENTES, e é por isso que a conta extrai só o número inteiro de dias.

Os blocos de texto abaixo são a saída REAL do `ffprobe -show_entries format_tags
-of default` dos arquivos do material.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine
from media.inspector import _bwf_origination, _bwf_start_seconds, _scene_take, _tape
from sync.daycycle import DAY_S

SAMPLE_RATE = 48000

# ── Saída real do ffprobe, arquivo por arquivo ───────────────────────────────

SP3_TORE_001 = """[FORMAT]
TAG:comment=sSPEED=023.976-ND
sTAKE=001
sUBITS=$00000000
sSWVER=9.01.9781
sSCENE=SP3-TORE
sFILENAME=SP3-TORE-001.WAV
sTAPE=250516
sCIRCLED=FALSE
sTRK6=LAP4
sNOTE=

TAG:encoded_by=SoundDev: MixPre-10 II TJ0421280
TAG:originator_reference=USSDVTJ0421280030250516Nv1000001
TAG:date=2025-05-16
TAG:creation_time=23:57:02
TAG:time_reference=4023241703
TAG:coding_history=A=PCM,F=48000,W=32,M=mono,R=48000,T=1 Ch;Ambisonics=off

[/FORMAT]
"""

LOCAL-2_001 = """[FORMAT]
TAG:comment=sSPEED=023.976-ND
sTAKE=001
sTAPE=250517
sSCENE=D1-LOCAL-2
sTRK2=BOOM

TAG:date=2025-05-17
TAG:creation_time=00:07:50
TAG:time_reference=4054350781
[/FORMAT]
"""

LOCAL-2_004 = """[FORMAT]
TAG:comment=sTAKE=004
sTAPE=250517

TAG:date=2025-05-17
TAG:creation_time=01:51:48
TAG:time_reference=202406685
[/FORMAT]
"""

LOCAL-2_005 = """[FORMAT]
TAG:comment=sTAKE=005
sTAPE=250517

TAG:date=2025-05-17
TAG:creation_time=22:03:42
TAG:time_reference=3696873600
[/FORMAT]
"""

# Um contêiner que NÃO é BWF: o `creation_time` aqui é um ISO completo, herdado do
# sistema de arquivos. Não vale nada como data de gravação.
M4A_QUALQUER = """[FORMAT]
TAG:major_brand=M4A
TAG:creation_time=2026-07-09T17:22:30.000000Z
[/FORMAT]
"""


# ── A leitura ────────────────────────────────────────────────────────────────


def test_le_data_hora_e_tape_do_bext():
    assert _bwf_origination(SP3_TORE_001) == ("2025-05-16", "23:57:02")
    assert _tape(SP3_TORE_001) == "250516"
    # E o que já se lia continua se lendo, do mesmo texto e sem subprocesso a mais.
    assert _scene_take(SP3_TORE_001) == ("SP3-TORE", "001")
    assert _bwf_start_seconds(SP3_TORE_001, SAMPLE_RATE) == pytest.approx(83817.5, abs=0.1)


def test_o_dia_do_gravador_pode_ter_virado_sem_o_tc_virar():
    """`LOCAL-2-001` foi gravado às 00:07 do dia 17 — a DATA já virou. Mas o TC
    dele marca 23:27, ainda do dia anterior no relógio jam-syncado. Os dois sinais
    contam coisas diferentes, e é por isso que a conta não pode confiar em um só."""
    assert _bwf_origination(LOCAL-2_001) == ("2025-05-17", "00:07:50")
    assert _bwf_start_seconds(LOCAL-2_001, SAMPLE_RATE) == pytest.approx(84465.6, abs=0.1)


def test_creation_time_que_nao_e_hora_pura_e_ignorado():
    """⭐ A regra "só metadado interno e confiável", virada em código. Em m4a/mp3 a
    mesma tag é um ISO completo — e no material real ela traz a data do TRANSCODE
    (2026-07-09 para uma filmagem de maio de 2025). Aceitar isso seria pior que não
    ler nada."""
    assert _bwf_origination(M4A_QUALQUER) == (None, None)
    assert _tape(M4A_QUALQUER) is None


def test_arquivo_sem_bext_nao_inventa_data():
    assert _bwf_origination("") == (None, None)
    assert _tape("") is None


# ── O desdobramento do conjunto ──────────────────────────────────────────────


def _sound(name: str, tags: str, dur_s: float = 60.0) -> "engine._Sound":
    meta = {
        "duration_ms": dur_s * 1000,
        "tc_start_sec": _bwf_start_seconds(tags, SAMPLE_RATE),
        "sample_rate": SAMPLE_RATE, "channels": 2,
    }
    meta["bwf_date"], meta["bwf_time"] = _bwf_origination(tags)
    return engine._Sound(Path(f"/fake/{name}"), meta)


def _camera_window(lo_h: float, hi_h: float):
    """Um grupo de câmera JÁ desdobrado, cobrindo `[lo_h, hi_h]` no eixo do dia."""
    def clip(t_h):
        c = engine._Clip.__new__(engine._Clip)
        c.path = Path("/fake/cam.mov")
        c.tc_sec = (t_h % 24) * 3600
        c.day_index = int(t_h // 24)
        c._tc_fps = 24.0
        c._fps = 24.0
        c.duration_s = 1.0
        c.tc_frames = round(c.tc_sec * 24.0)
        return c
    return [clip(lo_h), clip(hi_h)]


def test_o_bwf_mantem_a_distancia_real_entre_os_sons():
    """⭐ O caso que a janela sozinha erra. `LOCAL-2-005` foi gravado 20 h depois do
    resto; o TC dele (21:23) cairia confortavelmente dentro da janela das câmeras se
    alguém só perguntasse "que dia aproxima mais". O BWF sabe que não é o mesmo dia.
    """
    sons = [
        _sound("sp3.wav", SP3_TORE_001),
        _sound("b001.wav", LOCAL-2_001),
        _sound("b004.wav", LOCAL-2_004),
        _sound("b005.wav", LOCAL-2_005),
    ]
    cams = _camera_window(23.1, 25.3)
    engine._unwrap_sounds(sons, {"CAM A": cams}, ["CAM A"])

    eixo = {s.path.name: s.tc_abs_sec / 3600 for s in sons}
    # Os três da noite ficam colados nas câmeras…
    assert 23.0 < eixo["sp3.wav"] < 23.5
    assert 23.0 < eixo["b001.wav"] < 23.6
    assert 25.0 < eixo["b004.wav"] < 25.4
    # …e o da noite SEGUINTE fica 20 h à frente, onde ele de fato está.
    assert eixo["b005.wav"] - eixo["b004.wav"] == pytest.approx(20.2, abs=0.2)


def test_som_sem_data_cai_na_janela_das_cameras():
    """Sem BWF não há como saber o dia sozinho — e aí a janela das câmeras é a
    melhor resposta disponível. É o comportamento de quem não tem metadado."""
    sem_data = engine._Sound(Path("/fake/mudo.wav"), {
        "duration_ms": 60_000, "tc_start_sec": 0.5 * 3600,  # 00:30, sem data
        "sample_rate": SAMPLE_RATE, "channels": 2,
    })
    cams = _camera_window(23.0, 25.0)
    engine._unwrap_sounds([sem_data], {"CAM A": cams}, ["CAM A"])
    assert sem_data.day_index == 1, "24:30 cai dentro da janela; 00:30 ficaria a 22 h dela"


def test_sem_camera_com_relogio_nenhum_som_se_move():
    """Sem janela não há a que ancorar. Todo mundo fica no dia 0 — exatamente o
    comportamento de antes de o desdobramento existir."""
    sons = [_sound("b005.wav", LOCAL-2_005)]
    engine._unwrap_sounds(sons, {}, [])
    assert sons[0].day_index == 0
    assert sons[0].tc_abs_sec == sons[0].tc_sec


def test_o_som_nao_herda_o_dia_de_timecode_da_camera():
    """Uma volta do TC dura 86 486 s a 23,976 fps; para o som ela dura 86 400 s
    exatos, porque `TimeReference` conta AMOSTRAS, não frames. Confundir as duas
    custaria 86 s por virada."""
    s = _sound("b004.wav", LOCAL-2_004)
    s.day_index = 1
    assert s.tc_abs_sec - s.tc_sec == pytest.approx(DAY_S)
