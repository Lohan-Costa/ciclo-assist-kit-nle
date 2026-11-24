"""O piloto tira a janela do app da frente e a devolve como estava (autor, 2026-11-01).

⛔ O caso: a janela FIXADA no topo cobriu o botão Create da Select Project do Media Composer.
"""

from __future__ import annotations

import sys

import pytest

from cicloassist.piloto import espaco as E

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="SetWindowPos é do Windows")


@pytest.fixture(autouse=True)
def sem_borda(monkeypatch):
    """A borda de verdade abriria janelas na tela de quem roda a suíte."""
    import contextlib
    from cicloassist.piloto import borda
    monkeypatch.setattr(borda, "acesa", lambda *a, **k: contextlib.nullcontext())


class _U:
    def __init__(self):
        self.chamadas = []

    def SetWindowPos(self, h, depois, *_):  # noqa: N802
        self.chamadas.append((h, depois))


def test_sai_da_frente_e_volta_como_estava(monkeypatch):
    u = _U()
    monkeypatch.setattr(E, "_u", u)
    monkeypatch.setattr(E, "_nossas", lambda: [(10, True), (20, False)])
    with E.tela_livre():
        # ⚠️ NOTOPMOST sozinho deixaria a janela no alto da faixa não fixada: vai ao FUNDO
        assert u.chamadas == [(10, E._NOTOPMOST), (10, E._BOTTOM), (20, E._NOTOPMOST), (20, E._BOTTOM)]
        u.chamadas.clear()
    assert u.chamadas == [(10, E._TOPMOST), (20, E._TOP)]


def test_volta_mesmo_com_erro(monkeypatch):
    u = _U()
    monkeypatch.setattr(E, "_u", u)
    monkeypatch.setattr(E, "_nossas", lambda: [(10, True)])
    with pytest.raises(RuntimeError):
        with E.tela_livre():
            raise RuntimeError("o localizador não achou")
    assert u.chamadas[-1] == (10, E._TOPMOST)


def test_sem_app_nao_mexe_em_nada(monkeypatch):
    from cicloassist.servico import aplicativo
    monkeypatch.setattr(aplicativo, "_pai", None)
    monkeypatch.setattr(aplicativo, "_exe", None)
    assert E._nossas() == []
