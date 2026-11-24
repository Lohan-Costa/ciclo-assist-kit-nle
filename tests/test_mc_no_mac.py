"""O Media Composer no macOS sem o piloto da Select Project (medido no Mac mini, MC 25.12, 2026-11-05).

- salvar: File → Save All Bins pelo NOME (acessibilidade), sem foco nem tecla;
- abrir: o projeto já aberto se confere pela ponte gRPC; outro projeto é recusado dizendo o gesto.
"""

from __future__ import annotations

import subprocess

import pytest

from cicloassist.avid import abrir as A
from cicloassist.avid import salvar as S


def _menu(monkeypatch, habilitado: str, clique_rc: int = 0):
    chamadas = []

    def no_menu(acao):
        chamadas.append(acao)
        if acao.startswith("get enabled"):
            return subprocess.CompletedProcess([], 0, habilitado + "\n", "")
        return subprocess.CompletedProcess([], clique_rc, "", "" if clique_rc == 0 else "recusado")

    monkeypatch.setattr(S, "_no_menu", no_menu)
    return chamadas


def _projeto(tmp_path):
    (tmp_path / "P.avp").write_bytes(b"x")
    return tmp_path


def test_com_nada_modificado_nao_clica_e_diz(monkeypatch, tmp_path):
    chamadas = _menu(monkeypatch, "false")
    r = S._salvar_pelo_menu(_projeto(tmp_path))
    assert r["salvou"] is False and "cinza" in r["nota"]
    assert chamadas == ["get enabled of"]


def test_com_bin_suja_clica_e_confere_o_avp(monkeypatch, tmp_path):
    chamadas = _menu(monkeypatch, "true")
    monkeypatch.setattr(S, "esperar_mudar", lambda arq, antes, prazo: True)
    r = S._salvar_pelo_menu(_projeto(tmp_path))
    assert r["salvou"] is True and chamadas == ["get enabled of", "click"]


def test_menu_que_nao_existe_e_falha_legivel(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "_no_menu", lambda acao: subprocess.CompletedProcess([], 1, "", "não achei o processo"))
    with pytest.raises(S.SalvarFalhou, match="Save All Bins"):
        S._salvar_pelo_menu(_projeto(tmp_path))


def test_abrir_no_mac_aceita_o_projeto_ja_aberto(monkeypatch):
    monkeypatch.setattr(A.sys, "platform", "darwin")
    monkeypatch.setattr(A, "_projeto_pela_api", lambda: "D01")
    assert A._abrir("D01")["como"] == "ja_aberto"


def test_abrir_no_mac_outro_projeto_diz_o_gesto(monkeypatch):
    monkeypatch.setattr(A.sys, "platform", "darwin")
    monkeypatch.setattr(A, "_projeto_pela_api", lambda: "D01")
    with pytest.raises(A.McNaoAbre, match="abra o projeto 'D02'"):
        A._abrir("D02")
