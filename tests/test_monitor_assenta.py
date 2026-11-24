"""Carregar → consultar → fechar, colados, derruba o Media Composer: a ponte espera.

⛔⛔ MEDIDO em 2026-09-13 (`spikes/fechar_bin_com_monitor.py`): `LoadMobsIntoViewer` →
`GetViewerMobs` → `CloseBin` sem pausa deu `ACCESS_VIOLATION` 5 vezes em 5; com 3 s depois
do carregar, 0 em 6. O teste não fala com Media Composer nenhum: confere que a ponte
segura as duas chamadas perigosas pelo tempo certo, e só elas.
"""

from __future__ import annotations

import pytest

from cicloassist.avid import mcapi as M


class _Relogio:
    def __init__(self):
        self.agora = 1000.0
        self.dormiu: list[float] = []

    def monotonic(self):
        return self.agora

    def sleep(self, s):
        self.dormiu.append(round(s, 2))
        self.agora += s


@pytest.fixture
def relogio(monkeypatch):
    r = _Relogio()
    monkeypatch.setattr(M.time, "monotonic", r.monotonic)
    monkeypatch.setattr(M.time, "sleep", r.sleep)
    monkeypatch.setattr(M, "_carregou_em", None)
    monkeypatch.setattr(M, "_carregando", 0)
    return r


@pytest.fixture
def mc(monkeypatch):
    chamadas: list[str] = []

    class _Stub:
        def __init__(self, metodo):
            self.metodo = metodo

        def __call__(self, req, timeout=None):
            chamadas.append(self.metodo)
            return object()

    m = M.MediaComposer()
    monkeypatch.setattr(m, "_pedido", lambda metodo, **_: object())
    monkeypatch.setattr(m, "_stub", lambda metodo, req, fluxo: _Stub(metodo))
    m.chamadas = chamadas
    return m


@pytest.mark.parametrize("perigosa", ["GetViewerMobs", "CloseBin"])
def test_logo_depois_de_carregar_a_chamada_perigosa_espera(relogio, mc, perigosa):
    mc._chamar("LoadMobsIntoViewer")
    relogio.agora += 0.5
    mc._chamar(perigosa)
    assert relogio.dormiu == [2.5]
    assert mc.chamadas == ["LoadMobsIntoViewer", perigosa]


def test_depois_de_assentar_nao_espera_nada(relogio, mc):
    mc._chamar("LoadMobsIntoViewer")
    relogio.agora += 5
    mc._chamar("GetViewerMobs")
    mc._chamar("CloseBin")
    assert relogio.dormiu == []


def test_sem_carregar_ninguem_espera(relogio, mc):
    """⭐ O montar_corte fecha bin o tempo todo: sem monitor carregado, a trava não pode
    custar nem um milissegundo."""
    mc._chamar("CloseBin")
    mc._chamar("GetViewerMobs")
    assert relogio.dormiu == []


def test_consulta_que_nao_mexe_no_monitor_nao_espera(relogio, mc):
    mc._chamar("LoadMobsIntoViewer")
    mc._chamar("OpenBin")
    mc._chamar("GetOpenProjectInfo")
    assert relogio.dormiu == []


def test_a_espera_cruza_sessoes(relogio, mc):
    """O serviço abre uma `MediaComposer` por ferramenta: carregar numa e fechar noutra é
    a mesma sequência perigosa."""
    mc._chamar("LoadMobsIntoViewer")
    outra = M.MediaComposer()
    outra._pedido = mc._pedido
    outra._stub = mc._stub
    outra._chamar("CloseBin")
    assert relogio.dormiu == [3.0]


def test_fechar_durante_um_carregar_em_curso_espera_ele_voltar():
    """⛔ Revisão de 2026-11-07: com o núcleo, o `CloseBin` de OUTRO módulo pode chegar enquanto o
    `LoadMobsIntoViewer` ainda está dentro do MC. A pausa contava só do fim do carregar, e o fechar
    passava sem esperar nada. Relógio de verdade aqui: são duas threads."""
    import threading
    import time as _t

    M._carregou_em = None
    M._carregando = 0
    ordem: list[str] = []
    dentro_do_mc = threading.Event()
    soltar = threading.Event()

    def carregar():
        M._esperar_o_monitor("LoadMobsIntoViewer")
        dentro_do_mc.set()
        soltar.wait(5)
        ordem.append("carregou")
        M._marcar_carregamento("LoadMobsIntoViewer")

    def fechar():
        dentro_do_mc.wait(5)
        M._esperar_o_monitor("CloseBin")
        ordem.append("fechou")

    antigo = M.ASSENTAR_DEPOIS_DE_CARREGAR_S
    M.ASSENTAR_DEPOIS_DE_CARREGAR_S = 0.2
    try:
        a = threading.Thread(target=carregar)
        b = threading.Thread(target=fechar)
        a.start(); b.start()
        dentro_do_mc.wait(5)
        _t.sleep(0.3)  # o fechar já chegou e tem de estar parado
        assert ordem == []
        inicio = _t.monotonic()
        soltar.set()
        a.join(5); b.join(5)
        assert ordem == ["carregou", "fechou"]
        assert _t.monotonic() - inicio >= 0.15  # e ainda esperou o monitor assentar
        assert M._carregando == 0
    finally:
        M.ASSENTAR_DEPOIS_DE_CARREGAR_S = antigo
        M._carregou_em = None
