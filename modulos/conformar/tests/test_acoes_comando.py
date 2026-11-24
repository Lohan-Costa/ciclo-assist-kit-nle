"""`Acoes.comando` espera o comando anterior do MC — travado por regressão.

O `DoCommand` volta antes de o comando acabar e o MC recusa o seguinte com o ErrorType 73 ("Can't start more than one
command on time."). Medido em 2026-10-13: o relink com os 48 vídeos reaproveitados deu dois Save a 0,3 s um do outro e
caiu. O 73 se repete até vagar (com prazo); qualquer outro erro sobe na hora.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVICO = RAIZ / "plugins" / "media-composer" / "servico"
sys.path.insert(0, str(SERVICO))
sys.path.insert(0, str(RAIZ / "motor"))

from avid.acoes import Acoes  # noqa: E402

OCUPADO = 'DoCommand falhou: UNKNOWN — {"ErrorMessage": "Can\'t start more than one command on time.", "ErrorType": 73}'


class McFalso:
    def __init__(self, erros):
        self.erros = list(erros)
        self.chamadas = 0

    def _chamar(self, metodo, **kw):
        self.chamadas += 1
        if self.erros:
            raise RuntimeError(self.erros.pop(0))
        return "ok"


def test_repete_enquanto_ocupado():
    mc = McFalso([OCUPADO, OCUPADO])
    assert Acoes(mc).comando(1004) == "ok"
    assert mc.chamadas == 3


def test_outro_erro_sobe_na_hora():
    mc = McFalso(["DoCommand falhou: Bin not found"])
    try:
        Acoes(mc).comando(1004)
    except RuntimeError as e:
        assert "Bin not found" in str(e)
    else:
        raise AssertionError("devia ter subido")
    assert mc.chamadas == 1


class Mc2024:
    """O MC 24.6: sem DoCommand; o CloseBin salva e tira a timeline do monitor (medido em 2026-10-18)."""

    def __init__(self, aberta=True):
        self.aberta = aberta
        self.feito = []

    def _chamar(self, metodo, **kw):
        from avid.mcapi import McApiNaoImplementado

        if metodo == "DoCommand":
            raise McApiNaoImplementado("DoCommand não existe nesta versão do Media Composer")
        if metodo == "GetViewerMobs":
            from types import SimpleNamespace as N
            return N(body=N(mobs=[N(mob_id="SEQ", view_type=0)]))
        raise AssertionError(metodo)

    def caminho_relativo_da_bin(self, b):
        return "B.avb"

    def itens_da_bin(self, rel, flags=()):
        from types import SimpleNamespace as N
        if not self.aberta:
            raise RuntimeError('GetListOfBinItems falhou: "Bin is not open."')
        return [N(mob_id="SEQ")]

    def fechar_bin(self, b):
        self.feito.append("fechar")

    def abrir_bin(self, b):
        self.feito.append("abrir")

    def carregar_no_monitor(self, mobs, destino):
        self.feito.append(("carregar", tuple(mobs), destino))


def test_2024_salva_fechando_e_devolve_a_timeline():
    mc = Mc2024()
    assert Acoes(mc).salvar(bin_aberta=r"C:\proj\B.avb") is True
    assert mc.feito == ["fechar", "abrir", ("carregar", ("SEQ",), "Record")]


def test_2024_bin_fechada_nao_e_tocada():
    mc = Mc2024(aberta=False)
    assert Acoes(mc).salvar(bin_aberta=r"C:\proj\B.avb") is True
    assert mc.feito == []


def test_2024_sem_bin_avisa_e_segue():
    mc = Mc2024()
    assert Acoes(mc).salvar() is False
    assert mc.feito == []


def test_desiste_no_prazo():
    mc = McFalso([OCUPADO] * 1000)
    try:
        Acoes(mc).comando(1004, prazo=0.5)
    except RuntimeError as e:
        assert "more than one command" in str(e)
    else:
        raise AssertionError("devia ter desistido")
    assert mc.chamadas < 10
