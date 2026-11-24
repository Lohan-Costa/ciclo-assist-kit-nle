"""
A DATA QUE O NOME DO ARQUIVO CARREGA.

Existe porque o material de câmera chega transcodado e o transcode apaga a data de
dentro do container: os proxies RED de maio de 2025 dizem `creation_time
2026-07-09`. O nome sobrevive, e as câmeras profissionais escrevem a data nele.

O que este teste guarda, acima de tudo: **o parser NÃO INVENTA**. Uma data errada
é pior que data nenhuma — sem data, a separação em diárias cai no buraco no eixo
do tempo, que é o sinal forte; com data errada, ela corta onde não devia.

Os nomes daqui são REAIS, tirados do material de teste.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media.nameconv import parse_folder_date, parse_name_date


# ── As convenções que existem no material ────────────────────────────────────


def test_red_da_mes_e_dia_sem_ano():
    """`A002_A034_0517QN` — MMDD + 2 caracteres de unicidade. A RED não escreve o
    ano, e a data volta PARCIAL: inventar o ano a partir do relógio do computador
    seria adivinhar sobre material de arquivo."""
    assert parse_name_date("/x/A002_A034_0517QN.mov") == ("05-17", None, "filename")
    assert parse_name_date("/x/A002_A001_0516SW.mov") == ("05-16", None, "filename")


def test_gravador_de_campo_da_data_e_hora():
    """Hollyland: a pasta é o dia e o arquivo é o horário. É a pista mais completa
    que existe no material — e as duas foram escritas pelo aparelho."""
    assert parse_name_date("/x/250516_HOLLY/hl-2025-05-16/23-57-29.wav") == (
        "2025-05-16", "23:57:29", "path")


def test_arri_da_a_data_inteira():
    assert parse_name_date("/x/A001C001_250516_R1AB.mxf") == (
        "2025-05-16", None, "filename")


# ── O que ele NÃO pode inventar ──────────────────────────────────────────────


def test_contador_de_6_digitos_nao_e_data():
    """O nome do ADR 0007. `03190217` é numeração de câmera, não 19/02."""
    assert parse_name_date("/x/A008_03190217_C001.mp4") == (None, None, None)


def test_mes_ou_dia_impossiveis_sao_recusados():
    assert parse_name_date("/x/CAM_9932AB.mov") == (None, None, None)   # mês 99
    assert parse_name_date("/x/CAM_0500AB.mov") == (None, None, None)   # dia 00
    assert parse_name_date("/x/A001C001_251340_R1AB.mxf") == (None, None, None)  # mês 13


def test_nome_sem_nada_devolve_nada():
    assert parse_name_date("/x/MVI_1234.MOV") == (None, None, None)
    assert parse_name_date("/x/gravacao final.wav") == (None, None, None)


def test_pasta_com_data_no_meio_do_caminho_nao_vira_hora_do_arquivo():
    """A hora só vem quando o NOME é um horário. Um arquivo qualquer dentro de uma
    pasta datada herda a data, não uma hora inventada."""
    data, hora, fonte = parse_name_date("/x/hl-2025-05-16/gravacao.wav")
    assert (data, hora, fonte) == ("2025-05-16", None, "path")


def test_horario_impossivel_no_nome_e_ignorado():
    data, hora, _ = parse_name_date("/x/hl-2025-05-16/99-99-99.wav")
    assert data == "2025-05-16" and hora is None


# ── A pista fraca: a pasta que uma PESSOA nomeou ─────────────────────────────


def test_pasta_datada_e_pista_fraca_e_separada():
    """`250516_BOLIVIA` foi nomeada por alguém DEPOIS da filmagem, e contém
    legitimamente material da madrugada do 17. Serve para dar NOME a uma diária,
    nunca para decidir onde ela começa e termina — por isso mora numa função
    própria, e não se mistura com a data do aparelho."""
    assert parse_folder_date("/x/250516_BOLIVIA/250516_SOM/a.wav") == "2025-05-16"
    # E ela NÃO vaza para a data do arquivo.
    assert parse_name_date("/x/250516_BOLIVIA/250516_SOM/a.wav") == (None, None, None)


def test_pasta_sem_data_devolve_nada():
    assert parse_folder_date("/x/MIDIAS/CAM A/a.mov") is None
