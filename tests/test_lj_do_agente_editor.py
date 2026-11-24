"""L/J é característica do agente Editor do fluxo de edição de cena (autor, 2026-11-09); o chat continua no corte seco."""

import threading

import pytest

from cicloassist.plano import esquema as E


def _plano(corte_de_som="depois", som_frames=10):
    base = {"confianca": "inferido", "fonte": "transcricao", "porque": "teste"}
    return {"bin": "b", "nome": "n", "cortes": [
        {"take": "A", "duracao_frames": 100, "inicio_no_take": 100, **base},
        {"take": "B", "duracao_frames": 100, "inicio_no_take": 100, "corte_de_som": corte_de_som, "som_frames": som_frames, **base},
    ]}


def test_fora_do_fluxo_o_lj_e_recusado():
    with pytest.raises(E.PlanoInvalido, match="L/J"):
        E.validar(_plano())


def test_dentro_do_fluxo_o_lj_passa():
    with E.com_lj_do_agente_editor():
        assert E.validar(_plano()).cortes[1].desloca == 10


def test_a_marca_nao_vaza_depois_do_bloco_nem_com_erro():
    with pytest.raises(RuntimeError):
        with E.com_lj_do_agente_editor():
            raise RuntimeError
    with pytest.raises(E.PlanoInvalido, match="L/J"):
        E.validar(_plano())


def test_a_marca_e_da_thread():
    """Um turno do chat rodando ao lado não herda a liberação do fluxo."""
    resultado = []

    def no_chat():
        try:
            E.validar(_plano())
            resultado.append("passou")
        except E.PlanoInvalido:
            resultado.append("recusou")

    with E.com_lj_do_agente_editor():
        t = threading.Thread(target=no_chat)
        t.start()
        t.join()
    assert resultado == ["recusou"]
