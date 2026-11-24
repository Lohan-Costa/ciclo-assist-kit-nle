"""
QUANTAS DIÁRIAS HÁ NESTA PASTA?

Uma pasta que o editor recebe raramente é uma diária. A do material real tem três:
dois clipes da noite anterior, a captação principal que atravessa a meia-noite, e
dois sons gravados na noite SEGUINTE, 20 h depois. Juntas, ocupam 26 h de timeline
— e acima de 24 h o Premiere trava a movimentação dos clipes.

⭐ O QUE ESTE TESTE EXISTE PARA GUARDAR, acima de tudo: **quem separa é o BURACO,
não a data.** No material real, `SP3-TORE-001.WAV` tem `OriginationDate
2025-05-16` e está cercado, no tempo, por clipes RED chamados `0517` — porque o
gravador e a câmera viram a data em momentos diferentes. Agrupar por data
colocaria o som e a câmera do MESMO instante em diárias diferentes.

Sem mídia real: `probe` monkeypatchado devolve metadados sintéticos com a mesma
TOPOLOGIA do material (dois vãos de ~21 h e ~20 h).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.dailysplit as dailysplit
from sync.dailysplit import DAILY_GAP_S, plan_dailies

FPS = 24.0
H = 3600.0
_META: dict[str, dict] = {}


@pytest.fixture(autouse=True)
def fake_probe(monkeypatch):
    monkeypatch.setattr(dailysplit, "probe", lambda p: _META[str(p)])
    _META.clear()


def _cam(name: str, tc_h: float, dur_s: float = 60.0, name_date: str | None = None):
    """Um clipe de câmera: tem fps, e o TC vem como string `HH:MM:SS:FF`."""
    t = int(tc_h * H) % 86400
    _META[name] = {
        "fps": FPS, "has_audio": True, "duration_ms": dur_s * 1000,
        "tc_start": f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}:00",
        "tc_drop_frame": False, "size_bytes": 1000, "channels": 2,
        "name_date": name_date, "bwf_date": None, "bwf_time": None, "name_time": None,
    }
    return name


def _snd(name: str, tc_h: float, dur_s: float = 600.0,
         bwf_date: str | None = None, bwf_time: str | None = None):
    """Um som: sem fps, TC em segundos desde a meia-noite (o `bext` do BWF)."""
    _META[name] = {
        "fps": None, "has_audio": True, "duration_ms": dur_s * 1000,
        "tc_start_sec": (tc_h * H) % 86400, "size_bytes": 1000,
        "channels": 2, "sample_rate": 48000,
        "bwf_date": bwf_date, "bwf_time": bwf_time,
        "name_date": None, "name_time": None,
    }
    return name


def _entradas(cams=(), snds=()):
    e = [{"path": p, "group_id": "CAM A", "group_order": i, "source_name": "CAM A"}
         for i, p in enumerate(cams)]
    e += [{"path": p, "group_id": "SOM", "group_order": i, "kind": "sound",
           "source_name": "SOM DIRETO"} for i, p in enumerate(snds)]
    return e


# ── A topologia real ─────────────────────────────────────────────────────────


def test_a_pasta_do_material_real_tem_tres_diarias():
    """Reproduz a topologia medida: 2 clipes de outra noite, a captação principal
    atravessando a meia-noite, e 2 sons da noite seguinte."""
    cams = [
        _cam("A001.mov", 0.66), _cam("A002.mov", 1.23),          # noite anterior
        # 21,9 h de vão
        _cam("A003.mov", 23.11), _cam("A033.mov", 23.97),        # antes da meia-noite
        _cam("A034.mov", 0.05), _cam("A077.mov", 1.24),          # depois dela
    ]
    snds = [
        _snd("sp3.wav", 23.28, bwf_date="2025-05-16", bwf_time="23:57:02"),
        _snd("b004.wav", 25.17 - 24, bwf_date="2025-05-17", bwf_time="01:51:48"),
        # 20,2 h de vão
        _snd("b005.wav", 45.39 - 24, bwf_date="2025-05-17", bwf_time="22:03:42"),
    ]
    r = plan_dailies(_entradas(cams, snds))

    assert len(r["dailies"]) == 3
    tamanhos = [d["file_count"] for d in r["dailies"]]
    assert tamanhos == [2, 6, 1], "2 da noite anterior · 4 câmeras + 2 sons · 1 da seguinte"
    # E nenhuma delas estoura o limite que originou tudo isto.
    assert all(d["span_seconds"] < 24 * H for d in r["dailies"])


def test_a_data_que_discorda_nao_separa_o_que_o_tempo_junta():
    """⭐ O Fato 3, explícito. O som diz 16 de maio; as câmeras ao redor dele, no
    MESMO instante, se chamam `0517`. Uma diária só."""
    cams = [
        _cam("c1.mov", 23.1, name_date="05-17"),
        _cam("c2.mov", 23.5, name_date="05-17"),
    ]
    snds = [_snd("s1.wav", 23.3, bwf_date="2025-05-16", bwf_time="23:57:02")]

    r = plan_dailies(_entradas(cams, snds))

    assert len(r["dailies"]) == 1, "tokens de data diferentes, mesmo momento — uma diária"
    assert r["dailies"][0]["file_count"] == 3


def test_uma_captacao_que_atravessa_a_meia_noite_nao_e_cortada():
    """O vão entre 23:57 e 00:01 é de quatro minutos. Só o timecode volta a zero."""
    cams = [_cam("c1.mov", 23.9), _cam("c2.mov", 23.97), _cam("c3.mov", 0.03),
            _cam("c4.mov", 0.2)]
    r = plan_dailies(_entradas(cams))
    assert len(r["dailies"]) == 1
    assert r["dailies"][0]["span_seconds"] < 1.5 * H


def test_um_vao_menor_que_o_limiar_nao_corta():
    """Um almoço, uma troca de locação, uma pausa de madrugada — nada disso é um
    dia novo. O limiar tem folga de horas para os dois lados."""
    cams = [_cam("c1.mov", 9.0), _cam("c2.mov", 9.1),
            _cam("c3.mov", 9.1 + (DAILY_GAP_S - 3600) / H)]
    r = plan_dailies(_entradas(cams))
    assert len(r["dailies"]) == 1


# ── O que ele não pode fazer ─────────────────────────────────────────────────


def test_fonte_sem_relogio_nunca_e_partida():
    """Sem timecode não há vão que se possa medir, e partir um cartão sem evidência
    é pior que deixá-lo inteiro."""
    for n in ("m1.MTS", "m2.MTS", "m3.MTS"):
        _META[n] = {"fps": FPS, "has_audio": True, "duration_ms": 30_000,
                    "tc_start": None, "size_bytes": 1000, "channels": 2,
                    "name_date": None, "bwf_date": None, "bwf_time": None,
                    "name_time": None}
    r = plan_dailies(_entradas(("m1.MTS", "m2.MTS", "m3.MTS")))
    assert len(r["dailies"]) == 1
    assert r["dailies"][0]["file_count"] == 3


def test_o_bwf_manda_quando_a_ORDEM_do_nome_mente():
    """⭐ Por que o som não pode ser desdobrado pela ordem do nome.

    Um gravador nomeia por CENA e TOMADA, não por hora. Aqui a `001` foi gravada às
    23:40 e a `002` às 05:40 da MANHÃ ANTERIOR — a numeração corre ao contrário do
    relógio, e é assim que material de dias diferentes chega numa pasta só.

    Pela ordem, a queda de 21 h no timecode seria lida como "virou a meia-noite" e
    as duas cairiam na mesma noite. O `bext` sabe que não: são 18 h de distância, e
    duas diárias.
    """
    snds = [
        _snd("CENA-001.wav", 23.0, bwf_date="2025-05-16", bwf_time="23:40:00"),
        _snd("CENA-002.wav", 2.0, bwf_date="2025-05-16", bwf_time="02:40:00"),
    ]
    r = plan_dailies(_entradas((), snds))
    assert len(r["dailies"]) == 2, "18 h separam as duas — a numeração é que engana"
    assert r["dailies"][0]["start_tc"] == "02:00", "a 002 foi gravada PRIMEIRO"


def test_o_som_sem_camera_alguma_vira_a_sua_propria_diaria():
    snds = [_snd("s1.wav", 10.0, bwf_date="2025-05-16", bwf_time="10:40:00"),
            _snd("s2.wav", 10.2, bwf_date="2025-05-16", bwf_time="10:52:00")]
    r = plan_dailies(_entradas((), snds))
    assert len(r["dailies"]) == 1
    assert r["dailies"][0]["file_count"] == 2


def test_lista_vazia_nao_explode():
    r = plan_dailies([])
    assert r["dailies"] == [] and r["warnings"]


# ── O formato de saída ───────────────────────────────────────────────────────


def test_os_arquivos_saem_prontos_para_o_comando_sync():
    """A resposta confirmada volta sem tradução: `files` já é o que o `sync` espera
    em `groups[].files`, com os dicts ORIGINAIS (group_id, group_order, kind…)."""
    entradas = _entradas([_cam("c1.mov", 10.0)], [_snd("s1.wav", 10.0)])
    r = plan_dailies(entradas)
    saida = r["dailies"][0]["files"]
    assert saida == entradas or sorted(map(id, saida)) == sorted(map(id, entradas))
    assert all("group_id" in f for f in saida)
    assert any(f.get("kind") == "sound" for f in saida)


def test_duas_captacoes_no_mesmo_dia_recebem_nomes_distintos():
    """Acontece: no material real uma capta às 00:39 e outra às 23:06 do mesmo 16
    de maio. Dois nomes iguais na tela seriam ilegíveis."""
    # Os dois sons carregam a MESMA data, e estão a 22,5 h um do outro: as duas
    # diárias resolvem para "2025-05-16" e o nome tem de desempatar sozinho.
    snds = [_snd("a.wav", 0.6, bwf_date="2025-05-16", bwf_time="00:36:00"),
            _snd("b.wav", 23.1, bwf_date="2025-05-16", bwf_time="23:06:00")]
    r = plan_dailies(_entradas((), snds))
    nomes = [d["name"] for d in r["dailies"]]
    assert len(r["dailies"]) == 2
    assert nomes[0] == "2025-05-16"
    assert len(set(nomes)) == 2, nomes
    assert [d["start_tc"] for d in r["dailies"]] == ["00:36", "23:06"]


# ── O que o material real do usuário ensinou (2026-08-04) ────────────────────


def test_uma_fonte_SEM_relogio_nenhum_nao_derruba_a_analise():
    """A pasta real tem 5 fontes e DUAS sem timecode (handcam AVCHD e um iPhone
    transcodado). Perguntar onde um bloco desses "começa" é uma pergunta sem
    resposta — e um `min()` sobre lista vazia levantava, derrubando a análise da
    pasta inteira em vez de analisar o que dava."""
    for n in ("m1.MTS", "m2.MTS"):
        _META[n] = {"fps": FPS, "has_audio": True, "duration_ms": 30_000,
                    "tc_start": None, "size_bytes": 1000, "channels": 2,
                    "name_date": None, "bwf_date": None, "bwf_time": None,
                    "name_time": None}
    entradas = [
        {"path": "m1.MTS", "group_id": "HAND", "group_order": 0, "source_name": "HAND"},
        {"path": "m2.MTS", "group_id": "HAND", "group_order": 1, "source_name": "HAND"},
    ] + _entradas([_cam("c1.mov", 10.0), _cam("c2.mov", 10.5)])

    r = plan_dailies(entradas)   # não levanta

    assert len(r["dailies"]) == 1
    assert r["dailies"][0]["file_count"] == 4, "a fonte sem relógio acompanha a diária"


def test_relogio_PARADO_nao_vira_ancora():
    """⭐ O iPhone do material real grava `00:00:00:00` em 102 arquivos. Ter campo
    de TC não basta — ele precisa ANDAR. Um relógio parado empilha a fonte na
    origem e puxa as diárias de verdade para junto de um ponto que não significa
    nada: na primeira análise, 140 dos 217 arquivos caíram numa diária só e as
    outras duas saíram invertidas."""
    for n in ("i1.mov", "i2.mov", "i3.mov"):
        _cam(n, 0.0)   # todos com TC 00:00:00:00
    cams = [_cam("r1.mov", 23.1), _cam("r2.mov", 23.5)]
    entradas = [
        {"path": n, "group_id": "IPHONE", "group_order": i, "source_name": "IPHONE"}
        for i, n in enumerate(("i1.mov", "i2.mov", "i3.mov"))
    ] + _entradas(cams)

    r = plan_dailies(entradas)

    assert len(r["dailies"]) == 1, "o relógio parado não pode inventar uma diária às 00:00"
    assert r["dailies"][0]["file_count"] == 5
