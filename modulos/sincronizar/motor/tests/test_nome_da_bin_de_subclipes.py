"""A bin de subclipes leva o NOME QUE O EDITOR PEDIU (Ciclo Assist, 2026-11-01).

"uma bin chamada subclipes" saía `D01 SUBCLIPES` — o `<sync> SUBCLIPES` era o único
nome possível. Vazio continua sendo o de sempre.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import main as M
from avid.takes import Tomada


@pytest.fixture
def ambiente(monkeypatch, tmp_path):
    linhas: list[dict] = []
    monkeypatch.setattr(M, "_write_line", lambda s: linhas.append(json.loads(s)))
    take = Tomada(nome="M06_CAM1_T01", cena=None, plano=None, take=None, edit_rate=25.0,
                  duracao=100, trechos=(), origem="sequencia", nome_do_som="",
                  convencao="", duracao_bruta=100)
    monkeypatch.setattr(M, "_ULTIMAS_TOMADAS", {
        "id": "L", "tomadas": [take], "bin": str(tmp_path / "D01.avb"),
        "colunas": {}, "nomes": {}})
    escritas: list[str] = []
    import avid.subclipes as S
    monkeypatch.setattr(S, "autorar", lambda t, saida, base=None: (
        escritas.append(saida) or {"saida": saida, "total": len(t)}))
    import avid.mcapi as MC

    class SemMC:
        def __enter__(self):
            raise MC.McApiError("sem MC no teste")

        def __exit__(self, *_):
            return False
    monkeypatch.setattr(MC, "MediaComposer", SemMC)
    return linhas, escritas


def _pedir(params):
    M.handle_command({"id": "W", "command": "avid_subclips_write",
                      "params": {"leitura_id": "L", "padrao": "", **params}})


def test_o_nome_pedido_e_o_nome_da_bin(ambiente):
    linhas, escritas = ambiente
    _pedir({"nome": "subclipes"})
    assert Path(escritas[0]).name == "subclipes.avb"


def test_sem_nome_continua_o_de_sempre(ambiente):
    linhas, escritas = ambiente
    _pedir({})
    assert Path(escritas[0]).name == "D01 SUBCLIPES.avb"


@pytest.mark.parametrize("ruim", ["../fora", "a/b", "a" + chr(92) + "b", ".."])
def test_nome_com_caminho_e_recusado(ambiente, ruim):
    linhas, escritas = ambiente
    _pedir({"nome": ruim})
    assert not escritas
    assert [l for l in linhas if "event" not in l][-1]["ok"] is False
