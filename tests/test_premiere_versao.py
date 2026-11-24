"""Qual Premiere abrir: o pedido pelo ano, senão o mais novo — e nunca o beta (autor, 2026-11-01)."""

from __future__ import annotations

import os

from cicloassist import premiere_app


def _instalados(monkeypatch, pastas):
    base = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    achados = [os.path.join(base, "Adobe", p, premiere_app.EXE_WINDOWS) for p in pastas]
    monkeypatch.setattr(premiere_app.sys, "platform", "win32")
    monkeypatch.setattr(premiere_app.glob, "glob", lambda *_a, **_k: achados)


def test_o_mais_novo_sem_o_beta(monkeypatch):
    _instalados(monkeypatch, ["Adobe Premiere Pro 2023", "Adobe Premiere Pro 2026",
                              "Adobe Premiere Pro (Beta)", "Adobe Premiere Pro 2027 Beta"])
    assert sorted(premiere_app.instalados()) == [2023, 2026]
    assert "2026" in premiere_app.executavel()
    assert "2023" in premiere_app.executavel("2023")
    assert premiere_app.executavel("2025") == ""


def test_so_o_beta_e_como_nao_ter(monkeypatch):
    _instalados(monkeypatch, ["Adobe Premiere Pro (Beta)"])
    assert premiere_app.executavel() == ""


def test_a_conferencia_diz_as_versoes_que_ha(monkeypatch):
    from cicloassist.mcp.ferramentas import programas
    _instalados(monkeypatch, ["Adobe Premiere Pro 2023", "Adobe Premiere Pro 2026"])
    monkeypatch.setattr(programas, "nomeado_pelo_editor", lambda *_a, **_k: True)
    m = programas._conferir("premiere", "C:/x/p.prproj", versao="2024")
    assert "2024 não está instalado" in m and "2023, 2026" in m
    assert "só vale para o Premiere" in programas._conferir("resolve", "R", versao="2026")


def test_o_beta_so_quando_pedido(monkeypatch):
    """Autor, 2026-11-06: o produto abre o Beta quando PEDIDO; sem pedido, segue o de produção."""
    _instalados(monkeypatch, ["Adobe Premiere Pro 2026", "Adobe Premiere Pro (Beta)"])
    assert "2026" in premiere_app.executavel()
    assert "(Beta)" in premiere_app.executavel("beta")
    assert "(Beta)" in premiere_app.executavel("Beta")


def test_pedir_o_beta_sem_ele_instalado(monkeypatch):
    from cicloassist.mcp.ferramentas import programas
    _instalados(monkeypatch, ["Adobe Premiere Pro 2026"])
    monkeypatch.setattr(programas, "nomeado_pelo_editor", lambda *_a, **_k: True)
    assert premiere_app.executavel("beta") == ""
    assert "beta não está instalado" in programas._conferir("premiere", "C:/x/p.prproj", versao="beta")
