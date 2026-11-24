"""O revisor de IA antes do sync num fluxo (decisão 6 do plano de 2026-11-08)."""
from __future__ import annotations

import pytest

from cicloassist.motor import revisor_do_sync as R
from cicloassist.servico import fluxo as F


def test_so_um_true_de_verdade_aprova():
    assert R.ler_resposta({"coerente": True, "motivo": "ok"})["coerente"] is True
    assert R.ler_resposta({"coerente": "true"})["coerente"] is False
    assert R.ler_resposta({})["coerente"] is False


@pytest.fixture
def sem_ia(monkeypatch):
    from cicloassist.mcp.ferramentas import sincronizar as FO
    monkeypatch.setattr(FO, "resumo_para_o_revisor", lambda **k: [{"tipo": "camera"}])


def test_incoerente_para_o_fluxo_e_pergunta(sem_ia, monkeypatch):
    monkeypatch.setattr(R, "revisar", lambda n, f: {"coerente": False, "motivo": "duas câmeras juntas.", "pergunta": "Separo?"})
    with pytest.raises(F.PlanoInvalido, match="Separo"):
        F._revisar_antes_do_sync("sincronizar", {"nome": "D1", "fontes": []})


def test_sem_ia_o_sync_nao_roda_e_diz_o_motivo(sem_ia, monkeypatch):
    def falha(n, f):
        raise R.RevisorFalhou("sem conta")
    monkeypatch.setattr(R, "revisar", falha)
    with pytest.raises(F.PlanoInvalido, match="sem conta"):
        F._revisar_antes_do_sync("sincronizar", {"fontes": []})


def test_coerente_segue_e_sem_supervisao_nem_pergunta(sem_ia, monkeypatch):
    chamadas = []
    monkeypatch.setattr(R, "revisar", lambda n, f: chamadas.append(n) or {"coerente": True, "motivo": "", "pergunta": ""})
    F._revisar_antes_do_sync("sincronizar", {"nome": "D1"})
    F._revisar_antes_do_sync("sincronizar", {"nome": "D2", "sem_supervisao": True})
    F._revisar_antes_do_sync("importar_no_premiere", {"nome": "D3"})
    assert chamadas == ["D1"]
