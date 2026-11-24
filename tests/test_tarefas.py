"""O trabalho que acontece fora de um turno do modelo.

⭐ O que a aba Vetores pediu: *"deixa a análise correndo enquanto eu faço outra coisa"*.
Estes testes travam as três promessas que isso implica — uma tarefa por vez, cancelar
aproveita o que já foi feito, e nada aqui derruba o serviço.
"""

from __future__ import annotations

import threading
import time

import pytest

from cicloassist.servico import tarefas as T


@pytest.fixture(autouse=True)
def limpo():
    T.esquecer()
    yield
    T.parar()
    T.esquecer()


def esperar(ate=3.0):
    """Espera a tarefa viva terminar. ⚠️ Com teto: um teste que trava é pior que um que
    falha, porque ninguém sabe onde ele parou."""
    limite = time.time() + ate
    while T.ha_tarefa_viva() and time.time() < limite:
        time.sleep(0.01)
    return not T.ha_tarefa_viva()


def test_a_tarefa_corre_e_devolve_o_resumo():
    T.comecar("varredura", "D:/um", lambda avisar, parar: {"clipes": 7})
    assert esperar()

    t = T.atual()
    assert t.estado == "pronta"
    assert t.fracao == 1.0
    assert t.resumo == {"clipes": 7}
    assert t.como_dicionario()["segundos"] >= 0


def test_o_progresso_chega_na_tela():
    solta = threading.Event()

    def trabalho(avisar, parar):
        avisar(0.5, "meio do caminho")
        solta.wait(2)
        return {}

    T.comecar("varredura", "x", trabalho)
    time.sleep(0.05)
    t = T.atual()
    assert t.fracao == 0.5 and t.texto == "meio do caminho"
    solta.set()
    assert esperar()


def test_uma_tarefa_por_vez():
    """⚠️ Não é simplificação: o que roda no fundo disputa a MÁQUINA com o turno. Duas em
    paralelo não terminam mais cedo — terminam as duas devagar, com o editor conversando
    no meio."""
    solta = threading.Event()
    T.comecar("varredura", "x", lambda a, p: solta.wait(2) and {})

    with pytest.raises(T.TarefaEmCurso):
        T.comecar("varredura", "y", lambda a, p: {})

    solta.set()
    assert esperar()


def test_depois_de_terminar_aceita_outra():
    T.comecar("varredura", "x", lambda a, p: {})
    assert esperar()
    T.comecar("varredura", "y", lambda a, p: {})
    assert esperar()
    assert T.atual().alvo == "y"


def test_parar_pede_e_a_tarefa_sai_com_o_parcial():
    """⭐ Pede, não mata: a thread confere o sinal entre os passos. Matar no meio deixaria
    a sondagem pela metade."""
    passos = []

    def trabalho(avisar, parar):
        for i in range(100):
            if parar.is_set():
                break
            passos.append(i)
            time.sleep(0.005)
        return {"passos": len(passos)}

    T.comecar("varredura", "x", trabalho)
    time.sleep(0.05)
    assert T.parar()
    assert esperar()

    t = T.atual()
    assert t.estado == "parada"
    assert 0 < t.resumo["passos"] < 100


def test_parar_sem_tarefa_nao_e_erro():
    assert T.parar() is False


def test_tarefa_que_estoura_vira_estado_e_nao_derruba():
    """⛔ Uma varredura que falha não pode deixar o painel esperando para sempre por um
    andamento que nunca mais muda."""
    def trabalho(avisar, parar):
        raise RuntimeError("o disco sumiu")

    T.comecar("varredura", "x", trabalho)
    assert esperar()

    t = T.atual()
    assert t.estado == "erro"
    assert "disco sumiu" in t.erro
    assert not t.viva


def test_a_ultima_tarefa_fica_guardada():
    """⭐ É o que permite ao painel abrir DEPOIS e ainda ver o resultado: quem trocou de
    aba no meio volta para uma tela que sabe que houve varredura."""
    T.comecar("varredura", "D:/um", lambda a, p: {"clipes": 3})
    assert esperar()
    assert T.atual().resumo["clipes"] == 3


def test_o_dicionario_leva_o_que_a_tela_pinta():
    T.comecar("varredura", "D:/um", lambda a, p: {})
    assert esperar()
    d = T.atual().como_dicionario()
    for campo in ("id", "tipo", "alvo", "estado", "fracao", "texto", "viva", "segundos"):
        assert campo in d, campo
