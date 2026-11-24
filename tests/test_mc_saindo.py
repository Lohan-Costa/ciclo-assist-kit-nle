"""⛔⛔ O MC que demora a SAIR (2026-11-04, a diária D05 pelo chat).

Depois do Leave ele ficou ~3,5 min "Not Responding" gravando o projeto; o fechar desistia aos 120 s, o modelo
tentava de novo e o File → Exit caía numa janela travada. Com o Leave dado, a saída está em curso: esperar.
"""

from __future__ import annotations

import sys

import pytest

from cicloassist.avid import abrir

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="o fechar do MC é só Windows")


def _vivo_por(n):
    estado = {"n": n}

    def vivo():
        estado["n"] -= 1
        return estado["n"] >= 0
    return vivo


def test_ja_saindo_so_espera_o_processo(monkeypatch):
    monkeypatch.setattr(abrir, "projeto_aberto", lambda: "X")
    monkeypatch.setattr(abrir._janela, "janelas", lambda exe: [(1, "Avid Media Composer  - X", (0, 0, 9, 9))])
    monkeypatch.setattr(abrir._janela, "janela_principal", lambda exe, t="": 1)
    monkeypatch.setattr(abrir._janela, "travada", lambda h: True)
    monkeypatch.setattr(abrir, "_processo_vivo", _vivo_por(3))
    monkeypatch.setattr(abrir.time, "sleep", lambda s: None)
    monkeypatch.setattr(abrir, "_Piloto", lambda *a: pytest.fail("não pode mexer no menu de um MC travado"))
    frases = []
    r = abrir._fechar(lambda f, *_: frases.append(f))
    assert r["ja_estava_fechado"] is False
    assert "o Media Composer já está saindo" in frases


def test_leave_dado_e_saida_longa_nao_e_falha(monkeypatch):
    relogio = {"t": 0.0}
    monkeypatch.setattr(abrir.time, "monotonic", lambda: relogio["t"])
    monkeypatch.setattr(abrir.time, "sleep", lambda s: relogio.__setitem__("t", relogio["t"] + s))
    vivo = {"ate": abrir.PRAZO_DE_SAIR_S + 90}           # sai DEPOIS do prazo de 120 s
    monkeypatch.setattr(abrir, "_processo_vivo", lambda: relogio["t"] < vivo["ate"])
    r = abrir._esperar_sair(lambda *a: None, 0.0, "X", 0.0, ["leave"], "saindo")
    assert r["segundos"] >= abrir.PRAZO_DE_SAIR_S


def test_leave_dado_e_nunca_sai_diz_o_que_fazer(monkeypatch):
    relogio = {"t": 0.0}
    monkeypatch.setattr(abrir.time, "monotonic", lambda: relogio["t"])
    monkeypatch.setattr(abrir.time, "sleep", lambda s: relogio.__setitem__("t", relogio["t"] + s))
    monkeypatch.setattr(abrir, "_processo_vivo", lambda: True)
    with pytest.raises(abrir.McNaoAbre, match="não force"):
        abrir._esperar_sair(lambda *a: None, 0.0, "X", 0.0, [], "saindo")
