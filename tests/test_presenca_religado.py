"""⭐⭐ O serviço que CAIU e o supervisor religou continua a conversa (2026-11-04).

A borda do piloto derrubou o serviço no meio de um `organizar_bins`; religado, ele começou visita nova e a
conversa do editor sumiu. Cair não é gesto dele — fechar e abrir o app continua sendo começar do zero.
"""

from __future__ import annotations

import time

import pytest

from cicloassist.servico import presenca


@pytest.fixture(autouse=True)
def limpo():
    presenca.esquecer()
    presenca._fios.clear()
    yield
    presenca.esquecer()
    presenca._fios.clear()


def _gravar_uma_visita(ha_s: float = 5.0) -> str:
    visita = presenca.bater()
    presenca.guardar_fios({"conversa-x": visita})
    presenca._visto_em = time.time() - ha_s
    presenca._gravar()
    presenca.esquecer()                      # o processo morreu: a memória se foi
    return visita


def test_religado_retoma_a_visita_recente(monkeypatch):
    visita = _gravar_uma_visita(5)
    monkeypatch.setenv("CICLOASSIST_RELIGADO", "1")
    assert presenca.retomar() == {"conversa-x": visita}
    assert presenca.atual() == visita
    assert presenca.bater() == visita        # o painel recarregado bate na MESMA visita


def test_religado_depois_do_silencio_e_conversa_nova(monkeypatch):
    _gravar_uma_visita(presenca.SILENCIO_S + 5)
    monkeypatch.setenv("CICLOASSIST_RELIGADO", "1")
    assert presenca.retomar() == {}
    assert presenca.atual() == ""


def test_o_app_abrindo_nunca_retoma(monkeypatch):
    _gravar_uma_visita(5)
    monkeypatch.delenv("CICLOASSIST_RELIGADO", raising=False)
    assert presenca.retomar() == {}          # "reiniciei o Ciclo Assist" é começar de novo
