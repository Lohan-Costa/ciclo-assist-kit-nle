"""Uma conversa por VISITA À JANELA: abrir o Ciclo Assist é começar do zero.

⭐⭐ Decisão do editor (2026-09-14): *"é melhor o usuário pedir um `--resume` para voltar a
uma sessão anterior do que abrir o Media Composer, fazer um pedido e só depois perceber que
está gastando com uma sessão que não é zerada."* Revista em 2026-11-01: o app saiu de dentro
do NLE, e a conversa é da JANELA — trocar de projeto ou de programa a CONTINUA.

⛔⛔ O caso que isto fecha foi medido em 2026-09-12: ele fechou o MC sem `/clear`, reabriu,
viu a tela em branco — e a conversa seguia inteira. A mesma tarefa leu 10,8× mais contexto
no fio velho que numa conversa limpa. **Avisar não era impedir.**

O que estes testes travam são as duas bordas opostas, porque cada uma estraga de um jeito:
zerar de menos cobra token do editor; zerar de mais joga fora o trabalho dele no meio.
"""

from __future__ import annotations

import json
import time

import pytest

from cicloassist.avid import escopo as ESC
from cicloassist.motor import sessao as S
from cicloassist.servico import presenca as P
from cicloassist.servico import rotas as R

JANELA = R.CONVERSA_DA_JANELA


@pytest.fixture(autouse=True)
def sem_visita():
    P.esquecer()
    R._visita_do_fio.clear()
    R._onde_o_editor_esta.clear()
    yield
    P.esquecer()
    R._visita_do_fio.clear()
    R._onde_o_editor_esta.clear()


# ── o que conta como outra visita ────────────────────────────────────────────

def test_a_primeira_fala_abre_uma_visita():
    assert P.atual() == ""
    visita = P.bater()
    assert visita and P.atual() == visita


def test_falar_de_novo_continua_na_mesma_visita():
    """⚠️ Reload do painel, trocar de aba, mandar outra pergunta: tudo é a mesma visita.
    Zerar aqui jogaria fora a conversa de quem só recarregou a tela."""
    primeira = P.bater()
    assert P.bater() == primeira


def test_o_silencio_longo_abre_outra_visita(monkeypatch):
    primeira = P.bater()
    monkeypatch.setattr(P, "_visto_em", time.time() - P.SILENCIO_S - 1)
    assert P.bater() != primeira


def test_o_limite_cabe_em_tres_pulsos_estrangulados():
    """⚠️ Webview estrangula timer de página escondida para ~1 por minuto, e o painel
    passa o dia atrás da janela do Media Composer. Se o limite não couber vários pulsos,
    a conversa do editor morre enquanto ele monta."""
    assert P.SILENCIO_S >= 3 * 60


# ── a conversa que nasce com a visita ────────────────────────────────────────

def limpezas(monkeypatch):
    """Registra os `recomecar` em vez de mexer numa sessão de verdade."""
    feitas = []
    monkeypatch.setattr(S, "recomecar", lambda caminho: feitas.append(caminho) or True)
    monkeypatch.setattr(R._sessao, "recomecar", lambda caminho: feitas.append(caminho) or True)
    return feitas


def test_o_primeiro_turno_da_visita_limpa_a_conversa(monkeypatch):
    feitas = limpezas(monkeypatch)
    P.bater()
    assert R._conversa_desta_visita() is True
    assert feitas == [JANELA]


def test_o_segundo_turno_da_mesma_visita_nao_limpa(monkeypatch):
    """⛔ Limpar a cada turno seria pior que não limpar: o editor perderia o fio no meio
    de um trabalho, que é justamente onde o contexto vale."""
    feitas = limpezas(monkeypatch)
    P.bater()
    R._conversa_desta_visita()
    assert R._conversa_desta_visita() is False
    assert feitas == [JANELA]


def test_o_app_reaberto_limpa_de_novo(monkeypatch):
    feitas = limpezas(monkeypatch)
    P.bater()
    R._conversa_desta_visita()

    # A janela morreu e voltou depois — outra visita.
    monkeypatch.setattr(P, "_visto_em", time.time() - P.SILENCIO_S - 1)
    P.bater()
    assert R._conversa_desta_visita() is True
    assert feitas == [JANELA, JANELA]


# ── a conversa é da janela, não do projeto (2026-11-01) ──────────────────────

def test_a_chave_da_conversa_nao_depende_do_projeto():
    """⛔⛔ O teste do autor: turno 1 com o MC fechado, turno 2 com o projeto criado — e a
    conversa sumia, porque a chave saía do caminho do projeto."""
    assert S.id_do_projeto(R.CONVERSA_DA_JANELA) == S.id_do_projeto(JANELA)
    fonte = (R.__file__)
    texto = open(fonte, encoding="utf-8").read()
    assert "_sessao.do_projeto(\n                _chave_da_conversa(qual)" in texto
    # ⭐ 2026-11-03: a chave é a da JANELA para o chat e a dos FLUXOS para a aba Fluxos — nenhuma do projeto.
    assert R._chave_da_conversa("chat") == R.CONVERSA_DA_JANELA
    assert R._chave_da_conversa("fluxos") == R.CONVERSA_DOS_FLUXOS


def test_o_primeiro_turno_nao_leva_recado_de_onde():
    assert R._recado_de_onde("avid", "") == ""


def test_trocar_de_projeto_leva_recado_e_nao_limpa():
    R._recado_de_onde("avid", "")
    recado = R._recado_de_onde("avid", "D:/proj/desktop")
    assert "projeto 'desktop'" in recado and "sem projeto aberto" in recado
    assert "continua" in recado


def test_trocar_de_programa_leva_recado():
    R._recado_de_onde("avid", "D:/proj/desktop")
    recado = R._recado_de_onde("premiere", "D:/x/desktop.prproj")
    assert "no Premiere" in recado and "era o Media Composer" in recado


def test_mesmo_lugar_nao_repete_o_recado():
    R._recado_de_onde("avid", "D:/proj/desktop")
    assert R._recado_de_onde("avid", "D:/proj/desktop") == ""


def test_limpar_esquece_onde_ele_estava(monkeypatch):
    limpezas(monkeypatch)
    R._recado_de_onde("avid", "D:/proj/desktop")
    P.bater()
    R._conversa_desta_visita()
    assert R._recado_de_onde("premiere", "X.prproj") == ""


def test_a_visita_nao_sobrevive_ao_reinicio_do_servico():
    """⭐ De propósito: "reiniciei o Ciclo Assist" é o gesto mais parecido com "quero
    começar de novo" que existe aqui. Por isso a visita mora na memória do processo."""
    P.bater()
    P.esquecer()           # é o que acontece quando o processo morre
    assert P.atual() == ""


# ── trocar de projeto ────────────────────────────────────────────────────────

def test_trocar_de_projeto_nao_limpa_mais_a_conversa(monkeypatch, tmp_path):
    """⭐⭐ Revisto em 2026-11-01: a conversa é da janela. O índice do projeto anterior cai
    (a busca muda de recorte), a conversa fica."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    feitas = limpezas(monkeypatch)
    aberto = ["D:/proj/UM"]
    monkeypatch.setattr(ESC, "projeto_aberto", lambda recarregar=False: aberto[0])
    monkeypatch.setattr(ESC._bins, "varrer", lambda p, *a, **k: {"chave": {}})
    P.bater()
    ESC.agora()

    aberto[0] = "D:/proj/DOIS"
    d = json.loads(R.rota_projeto(None).corpo.decode("utf-8"))
    assert d["mudou"] is True
    assert d["conversa_limpa"] is False
    assert feitas == []


def test_sem_troca_a_conversa_fica_de_pe(monkeypatch, tmp_path):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    feitas = limpezas(monkeypatch)
    monkeypatch.setattr(ESC, "projeto_aberto", lambda recarregar=False: "D:/proj/UM")
    monkeypatch.setattr(ESC._bins, "varrer", lambda p, *a, **k: {"chave": {}})
    P.bater()
    ESC.agora()

    d = json.loads(R.rota_projeto(None).corpo.decode("utf-8"))
    assert d["mudou"] is False and d["conversa_limpa"] is False
    assert feitas == []
