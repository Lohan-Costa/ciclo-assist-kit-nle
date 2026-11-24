"""
O TIMECODE É UM CÍRCULO — e a timeline é uma reta.

Uma captação que atravessa a meia-noite tem timecode DECRESCENTE no meio: o clipe
das 00:01 marca menos que o das 23:57, quatro minutos antes. Tratado como reta,
isso corta a diária ao meio e a remonta de trás para a frente — 24,31 h de
sequência no material real, acima do limite em que o Premiere trava a movimentação
dos clipes.

O que este teste guarda:

  1. A virada é detectada pela ORDEM DE GRAVAÇÃO, não pela data. (A RED escreve a
     data no nome, e ela NÃO vira junto com o TC — `A033`/TC 23:57 e `A034`/TC
     00:01 têm o mesmo token `0517` no material real.)
  2. ⭐ SEM VIRADA, o resultado é IDÊNTICO ao de antes deste módulo existir. É o
     argumento de que todo material já validado passa intocado.
  3. Uma queda PEQUENA de TC é nome fora de ordem, não dia novo — e continua sendo
     consertada pela reordenação, como sempre foi.
  4. Duas viradas não são uma diária: o desdobramento DESISTE em vez de inventar
     uma timeline de 48 h.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine
from media.audio import PCM_RATE, normalize
from sync.daycycle import (
    DAY_S,
    align_to_window,
    day_from_wall_clock,
    tc_day_seconds,
    unwrap_along_order,
)

FPS = 24.0
H = 3600.0


# ── A regra, isolada ─────────────────────────────────────────────────────────


def test_virada_detectada_ao_longo_da_ordem():
    # A topologia real: 23:00 → 23:57 → 00:01 → 01:14.
    tcs = [23 * H, 23.5 * H, 23.95 * H, 0.02 * H, 0.5 * H, 1.23 * H]
    days, wrapped = unwrap_along_order(tcs)
    assert days == [0, 0, 0, 1, 1, 1]
    assert wrapped is True
    # E o eixo desdobrado é monotônico — que é o ponto de tudo isto.
    abs_axis = [tc + d * DAY_S for tc, d in zip(tcs, days)]
    assert abs_axis == sorted(abs_axis)


def test_sem_virada_nao_muda_nada():
    tcs = [10 * H, 11 * H, 12 * H, 18 * H]
    days, wrapped = unwrap_along_order(tcs)
    assert days == [0, 0, 0, 0]
    assert wrapped is False


def test_queda_pequena_e_nome_fora_de_ordem_nao_dia_novo():
    # Dois arquivos fora de ordem no nome: o TC cai 2 h. Isso NÃO é meia-noite —
    # dois cartões misturados dão quedas dessa ordem, e chamá-las de dia novo
    # esticaria a diária em 24 h. Só uma queda acima de 12 h é virada.
    days, wrapped = unwrap_along_order([10 * H, 12 * H, 10 * H, 13 * H])
    assert days == [0, 0, 0, 0]
    assert wrapped is False


def test_arquivo_sem_tc_nao_interrompe_a_contagem():
    # O buraco na LEITURA não é buraco no TEMPO: o TC seguinte é comparado com o
    # último TC válido, e o arquivo sem TC herda o dia corrente.
    days, wrapped = unwrap_along_order([23 * H, None, 0.5 * H, None])
    assert days == [0, 0, 1, 1]
    assert wrapped is True


def test_duas_viradas_desistem():
    # Isto não é uma diária — é material de dias diferentes na mesma fonte.
    # Desdobrar às cegas daria 48 h de timeline, pior que o problema.
    days, wrapped = unwrap_along_order([23 * H, 1 * H, 23 * H, 1 * H])
    assert days == [0, 0, 0, 0], "desdobramento abortado"
    assert wrapped is False


def test_uma_volta_de_timecode_nao_tem_86400_segundos():
    """⭐ A armadilha de 0,1 % — a mesma que o `tc_to_real_seconds` documenta do
    outro lado.

    O timecode conta frames na base NOMINAL (24), e cada frame dura 1/23,976 s.
    Uma volta inteira são 24·3600·24 frames, que levam 86 486 s reais — 86 s a mais
    que um dia de parede (86 486 s). Somar 86400 numa virada pôs o clipe que atravessa a
    meia-noite 83 s por cima do seguinte, no material real, e sinalizou 17 clipes a
    mais por pareamento errado.
    """
    ntsc = 24000 / 1001
    assert tc_day_seconds(ntsc) == pytest.approx(24 * 3600 * 24 / ntsc)
    assert tc_day_seconds(ntsc) - DAY_S == pytest.approx(86.4, abs=0.01)
    # Onde o fps é inteiro, timecode e parede coincidem — e é por isso que o erro
    # passava despercebido em material a 24/25/30 fps.
    for exato in (24.0, 25.0, 30.0, 50.0, 60.0):
        assert tc_day_seconds(exato) == DAY_S
    # 29,97 drop-frame existe justamente para reaproximar as duas contagens, mas a
    # aritmética aqui é sobre a leitura non-drop: 30/29,97 continua valendo.
    assert tc_day_seconds(30000 / 1001) == pytest.approx(30 * 3600 * 24 / (30000 / 1001))


def test_a_camera_usa_a_volta_do_timecode_e_o_fps_do_ARQUIVO():
    """O eixo desdobrado de um clipe NTSC anda 86 486 s por virada, não 86 400.

    E o fps é o do ARQUIVO, não o do projeto: numa diária com câmeras de fps
    diferentes, a volta de cada uma tem o tamanho da SUA contagem de frames.
    """
    ntsc = 24000 / 1001
    meta = {"fps": ntsc, "duration_ms": 1000, "tc_start": "00:05:00:00",
            "tc_drop_frame": False, "has_audio": True, "size_bytes": 1}
    # `fps` do projeto DIFERENTE do fps do arquivo, de propósito.
    c = engine._Clip(Path("/fake/c.mov"), meta, "g", 0, 25.0)
    c.day_index = 1
    assert c.tc_abs_sec - c.tc_sec == pytest.approx(tc_day_seconds(ntsc))
    assert c.tc_abs_sec - c.tc_sec != pytest.approx(DAY_S)
    assert c.tc_abs_sec - c.tc_sec != pytest.approx(tc_day_seconds(25.0))


def test_o_som_usa_o_dia_de_parede_nao_o_de_timecode(monkeypatch):
    """O `tc_start_sec` de um BWF vem de `TimeReference / sample_rate` — AMOSTRAS
    desde a meia-noite real. Amostras não contam em frames, então não herdam o
    0,1 % do NTSC: para o som, um dia são 86400 s exatos."""
    s = engine._Sound.__new__(engine._Sound)
    s.tc_sec = 100.0
    s.day_index = 1
    assert s.tc_abs_sec == pytest.approx(100.0 + DAY_S)


# ── Puxar para a janela (o som, que não tem ordem própria) ───────────────────


def test_align_to_window_escolhe_o_dia_que_aproxima():
    # Câmeras entre 23:00 e 25:00 (já desdobradas). Um som marcando 00:30 é do
    # DIA SEGUINTE — 24:30 fica dentro da janela; 00:30 fica a 22,5 h dela.
    lo, hi = 23 * H, 25 * H
    assert align_to_window(0.5 * H, lo, hi) == 1
    # E um som marcando 23:30 já está dentro: dia 0.
    assert align_to_window(23.5 * H, lo, hi) == 0


def test_align_to_window_nao_inventa_dia_quando_ja_cabe():
    assert align_to_window(12 * H, 10 * H, 14 * H) == 0


# ── Relógio de parede (BWF) ──────────────────────────────────────────────────


def test_dia_pelo_relogio_de_parede():
    # Os números REAIS do material: parede 2025-05-16 23:57:02 (dia 0 da captação)
    # com TC 23:16:57. A parede está ~40 min à frente do TC — e mesmo assim o dia é 0.
    assert day_from_wall_clock(83817.5, 23 * H + 57 * 60 + 2) == 0
    # E o arquivo seguinte: parede 2025-05-17 00:07:50 (dia 1) com TC 23:27:45 —
    # a data já virou, mas o TC não. O dia do TC continua sendo 0.
    assert day_from_wall_clock(84465.6, DAY_S + 7 * 60 + 50) == 0
    # Já o de TC 01:10 na madrugada do 17: o TC virou, e o dia é 1.
    assert day_from_wall_clock(4216.8, DAY_S + 1 * H + 51 * 60 + 48) == 1


def test_parede_longe_demais_do_tc_nao_responde():
    # 8 h de distância entre parede e TC: perto o bastante das 12 h para a resposta
    # virar cara-ou-coroa. Admitir que não sabemos é melhor que errar o dia inteiro.
    assert day_from_wall_clock(0.0, 8 * H) is None


# ── Dentro do motor ──────────────────────────────────────────────────────────

SND = str(Path("/fake/snd.wav"))
CAMS = [str(Path(f"/fake/camA/c{i}.mov")) for i in range(6)]
# 23:00, 23:20, 23:40, 00:05, 00:25, 00:45 — a diária atravessa a meia-noite.
_TC = {
    CAMS[0]: "23:00:00:00", CAMS[1]: "23:20:00:00", CAMS[2]: "23:40:00:00",
    CAMS[3]: "00:05:00:00", CAMS[4]: "00:25:00:00", CAMS[5]: "00:45:00:00",
}
CAM_DUR_S = 60.0
# Um som direto CONTÍNUO que cobre a noite inteira, atravessando a meia-noite com
# as câmeras — é o que faz o par câmera↔som ter de existir dos dois lados da virada.
SND_TC_S = 23 * H
SND_DUR_S = 2 * H


def _probe(path: str) -> dict:
    if path in _TC:
        return {
            "fps": FPS, "has_audio": True, "duration_ms": CAM_DUR_S * 1000,
            "tc_start": _TC[path], "tc_drop_frame": False,
            "size_bytes": 1000, "channels": 2,
        }
    return {
        "fps": None, "has_audio": True, "duration_ms": SND_DUR_S * 1000,
        "tc_start_sec": SND_TC_S, "size_bytes": 1000, "channels": 2,
        "sample_rate": PCM_RATE,
    }


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    """`sync_method="timecode"` nos testes de motor daqui, e de propósito: é o
    caminho que EXERCITA a aritmética de TC que este módulo mudou
    (`_pair_by_tc_only`), sem depender de correlação sobre silêncio — que não
    responde nada e esconderia o que se quer medir."""
    monkeypatch.setattr(engine, "probe", _probe)
    monkeypatch.setattr(
        engine, "extract_pcm",
        lambda path, channel=0: np.zeros(int(SND_DUR_S * PCM_RATE), dtype=np.float32),
    )
    monkeypatch.setattr(engine, "normalize", normalize)


def _entries(cams):
    e = [{"path": c, "group_id": "CAM A", "group_order": i} for i, c in enumerate(cams)]
    e.append({"path": SND, "group_id": None, "group_order": None})
    return e


def _run(cams, **kw):
    return engine.run(_entries(cams), project_name="D", sync_method="timecode", **kw)


def test_diaria_que_cruza_a_meia_noite_e_entregue_inteira():
    msgs: list[str] = []
    daily = _run(CAMS, progress=lambda m, c, t, o=None: msgs.append(m))
    # Cabe. O span é o do som contínuo (2 h), não as 24 h de uma diária partida ao
    # meio — que é a diferença entre entregável e travado no Premiere.
    assert daily.span_frames / FPS / H <= 2.01
    # As câmeras ocupam as 1h45 reais da captação, atravessando a meia-noite.
    starts = [c.timeline_start_frames for c in daily.cameras]
    assert (max(starts) - min(starts)) / FPS / H == pytest.approx(1.75), "23:00 → 00:45"
    # E o motor DIZ que desdobrou — quem lê o registro precisa saber.
    assert any("meia-noite" in m for m in msgs)


def test_ordem_cronologica_preservada_atraves_da_virada():
    daily = _run(CAMS)
    cams = sorted(daily.cameras, key=lambda c: c.timeline_start_frames)
    assert [c.path.name for c in cams] == [Path(p).name for p in CAMS], (
        "os clipes pós-meia-noite têm de vir DEPOIS dos de antes dela"
    )


def test_o_tc_de_origem_do_arquivo_nunca_e_desdobrado():
    """O `alternate_start_ticks` é o TC que o NLE EXIBE no clipe. Desdobrá-lo daria
    `24:05:00:00`, que não existe em timecode nenhum."""
    daily = _run(CAMS)
    by = {c.path.name: c for c in daily.cameras}
    depois_da_virada = by[Path(CAMS[3]).name]
    assert depois_da_virada.tc_start_frames == round(5 * 60 * FPS), "00:05:00:00, cru"
    assert depois_da_virada.tc_start_frames < DAY_S * FPS


def test_duas_ilhas_uma_de_cada_lado_da_virada(monkeypatch):
    """⭐ O caso que só aparece com DOIS sons: uma tomada antes da meia-noite e
    outra depois.

    Com um som só, tudo vira uma ILHA e o posicionamento interno vem dos offsets —
    o TC da âncora some na normalização da origem, e um erro de 24 h ali passaria
    despercebido. Com duas ilhas, cada uma é ancorada pelo SEU timecode, e é aí que
    a diária ou fica inteira ou se parte ao meio. Ver `_place_on_timeline`.
    """
    SND_A = str(Path("/fake/sndA.wav"))   # 23:10, cobre as câmeras de antes
    SND_B = str(Path("/fake/sndB.wav"))   # 00:10, cobre as de depois
    sons = {SND_A: 23 * H + 10 * 60, SND_B: 10 * 60}

    def probe2(path: str) -> dict:
        if path in sons:
            return {
                "fps": None, "has_audio": True, "duration_ms": 40 * 60 * 1000,
                "tc_start_sec": sons[path], "size_bytes": 1000, "channels": 2,
                "sample_rate": PCM_RATE,
            }
        return _probe(path)

    monkeypatch.setattr(engine, "probe", probe2)
    entries = [
        {"path": c, "group_id": "CAM A", "group_order": i} for i, c in enumerate(CAMS)
    ] + [{"path": s, "group_id": None, "group_order": None} for s in sons]

    daily = engine.run(entries, project_name="D", sync_method="timecode")
    assert daily.span_frames <= daily.max_span_frames
    assert daily.span_frames / FPS / H < 3.0, "as duas ilhas ficam na MESMA noite"

    # E a ordem entre as ilhas se mantém: o material de antes da meia-noite vem antes.
    pos = {c.path.name: c.timeline_start_frames for c in daily.cameras}
    assert pos["c2.mov"] < pos["c3.mov"], "23:40 tem de vir antes de 00:05"
    # A distância entre eles é a real (25 min), não 24 h menos isso.
    assert (pos["c3.mov"] - pos["c2.mov"]) / FPS / 60 == pytest.approx(25.0)


def test_som_orfao_pos_meia_noite_nao_volta_para_o_dia_anterior(monkeypatch):
    """Um som que não pareou com câmera nenhuma é posicionado pelo PRÓPRIO TC — e
    se esse TC for de depois da meia-noite, o cru o jogaria 24 h para trás,
    esticando a diária exatamente como antes."""
    SND_ORF = str(Path("/fake/orfao.wav"))   # 00:50, depois de todas as câmeras

    def probe2(path: str) -> dict:
        if path == SND_ORF:
            return {
                "fps": None, "has_audio": True, "duration_ms": 60 * 1000,
                "tc_start_sec": 50 * 60, "size_bytes": 1000, "channels": 2,
                "sample_rate": PCM_RATE,
            }
        return _probe(path)

    monkeypatch.setattr(engine, "probe", probe2)
    entries = _entries(CAMS[:3])  # só as câmeras de ANTES da meia-noite
    entries.append({"path": SND_ORF, "group_id": None, "group_order": None})

    daily = engine.run(entries, project_name="D", sync_method="timecode")
    assert daily.span_frames <= daily.max_span_frames
    assert daily.span_frames / FPS / H < 3.0, "o órfão é da MESMA noite, não de 24 h antes"


def test_sem_virada_o_resultado_e_identico():
    """⭐ A não-regressão. Uma diária que não cruza a meia-noite tem de sair com as
    MESMAS posições que saía antes de o desdobramento existir — e como sem virada
    todo `day_index` é 0, `tc_abs` é literalmente `tc`."""
    normais = CAMS[:3]  # 23:00, 23:20, 23:40 — sem virada
    daily = _run(normais)
    cams = sorted(daily.cameras, key=lambda c: c.timeline_start_frames)
    assert [c.path.name for c in cams] == [Path(p).name for p in normais]
    # As distâncias entre eles são as do TC, intocadas: 20 min entre cada.
    starts = [c.timeline_start_frames for c in cams]
    assert starts[1] - starts[0] == round(20 * 60 * FPS)
    assert starts[2] - starts[1] == round(20 * 60 * FPS)
