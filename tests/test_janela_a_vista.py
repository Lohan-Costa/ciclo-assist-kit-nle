"""A janela do app À VISTA durante o fluxo (plano, autor 2026-10-31), e de volta ao que o editor quer."""

from __future__ import annotations

import sys
import types

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="SetWindowPos é do Windows")

from cicloassist.piloto import espaco as E  # noqa: E402
from cicloassist.servico import aplicativo as A  # noqa: E402


@pytest.fixture
def janelas(monkeypatch):
    estado = {"fixada": False}
    chamadas: list[int] = []

    def pos(h, depois, *_):
        chamadas.append(depois)
        if depois == E._TOPMOST:
            estado["fixada"] = True
        elif depois == E._NOTOPMOST:
            estado["fixada"] = False
        return 1

    monkeypatch.setattr(E, "_u", types.SimpleNamespace(SetWindowPos=pos))
    monkeypatch.setattr(E, "_nossas", lambda: [(42, estado["fixada"])])
    monkeypatch.setattr(A, "_pino", None)
    monkeypatch.setattr(E, "_a_vista", 0)
    return estado, chamadas


def test_fixa_durante_e_solta_no_fim(janelas):
    estado, _ = janelas
    with E.a_vista():
        assert estado["fixada"]
    assert not estado["fixada"]


def test_o_editor_ja_tinha_fixado_fica_fixada(janelas):
    estado, _ = janelas
    estado["fixada"] = True
    with E.a_vista():
        pass
    assert estado["fixada"]


def test_o_pino_apertado_no_meio_vale_no_fim(janelas):
    estado, _ = janelas
    with E.a_vista():
        A.lembrar_pino(True)
    assert estado["fixada"]


def test_reafirmar_so_dentro_de_um_fluxo(janelas):
    _, chamadas = janelas
    E.reafirmar()
    assert chamadas == []
    with E.a_vista():
        n = len(chamadas)
        E.reafirmar()
        assert chamadas[n:] == [E._TOPMOST]


def test_passo_pilotado_devolve_fixada_dentro_do_fluxo(janelas, monkeypatch):
    estado, _ = janelas
    with E.a_vista():
        with E._tela_livre():
            assert not estado["fixada"]
        assert estado["fixada"]
