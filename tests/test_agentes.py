"""O formato de agente e o turno magro (fase A2)."""
from __future__ import annotations

import pytest

from cicloassist.motor import agentes as A
from cicloassist.motor import revisor_do_sync as R
from cicloassist.motor import turno_magro as T
from cicloassist.servico import fluxo as F

ARQUIVO = """---
name: agente-de-teste
description: Só para o teste.
tipo: conselheiro
entradas: {"a": "texto", "b": "lista"}
saida: {"ok": "sim_nao"}
---

## Instrução

Faça.
"""


def _falso(monkeypatch, texto):
    pedidos = []

    def chamar(instrucao, pedido, modelo=None, prazo=0):
        pedidos.append((instrucao, pedido))
        return T.Resposta(texto, {"tokens": 1}, 0.1)
    monkeypatch.setattr(A._turno, "chamar", chamar)
    return pedidos


@pytest.fixture
def agente(monkeypatch):
    a = A.ler_texto(ARQUIVO)
    monkeypatch.setattr(A, "buscar", lambda nome: a)
    return a


def test_le_o_arquivo():
    a = A.ler_texto(ARQUIVO)
    assert (a.nome, a.tipo, a.saida, a.instrucao) == ("agente-de-teste", "conselheiro", {"ok": "sim_nao"}, "Faça.")


@pytest.mark.parametrize("trocar", [
    ("tipo: conselheiro", "tipo: operador"),
    ('entradas: {"a": "texto", "b": "lista"}', "entradas: nada"),
    ('saida: {"ok": "sim_nao"}', 'saida: {"ok": "inventado"}'),
    ("## Instrução", "## Outra"),
])
def test_arquivo_errado_e_dito_ao_carregar(trocar):
    with pytest.raises(A.AgenteInvalido):
        A.ler_texto(ARQUIVO.replace(*trocar))


def test_os_agentes_da_casa_carregam():
    assert R.AGENTE in A.todos()


def test_so_a_entrada_declarada_vai_ao_modelo(agente, monkeypatch):
    pedidos = _falso(monkeypatch, '{"ok": true}')
    r = A.rodar("x", {"a": "um", "b": [1], "segredo": "nao vai"})
    assert r["resposta"] == {"ok": True}
    assert pedidos == [("Faça.", 'a: um\nb: [1]')]


def test_entrada_faltando_nem_gasta_turno(agente, monkeypatch):
    pedidos = _falso(monkeypatch, '{"ok": true}')
    with pytest.raises(A.AgenteFalhou, match="faltou a entrada"):
        A.rodar("x", {"a": "um"})
    with pytest.raises(A.AgenteFalhou, match="tem de ser lista"):
        A.rodar("x", {"a": "um", "b": "nao e lista"})
    assert pedidos == []


@pytest.mark.parametrize("resposta", ['{}', '{"ok": "true"}'])
def test_resposta_fora_do_declarado_e_falha_e_nao_valor_vazio(agente, monkeypatch, resposta):
    _falso(monkeypatch, resposta)
    with pytest.raises(A.AgenteFalhou, match="sem o campo"):
        A.rodar("x", {"a": "um", "b": []})


def test_o_revisor_passa_pelo_agente(monkeypatch):
    pedidos = _falso(monkeypatch, '{"coerente": false, "motivo": "duas câmeras.", "pergunta": "Separo?"}')
    v = R.revisar("D01", [{"tipo": "camera"}])
    assert v == {"coerente": False, "motivo": "duas câmeras.", "pergunta": "Separo?"}
    assert "diaria: D01" in pedidos[0][1] and "fontes:" in pedidos[0][1]


def test_o_revisor_diz_quando_nao_ha_ia(monkeypatch):
    def sem_ia(*a, **k):
        raise T.TurnoFalhou("sem conta")
    monkeypatch.setattr(A._turno, "chamar", sem_ia)
    with pytest.raises(R.RevisorFalhou, match="sem conta"):
        R.revisar("D01", [{"tipo": "camera"}])


@pytest.mark.parametrize("campo", ["depois_de", "se"])
def test_ramificacao_malformada_e_recusada_e_dita(campo):
    """⛔ Ignorar calado rodaria em linha um fluxo que o autor desenhou com condição."""
    plano = {"passos": [{"id": "a", "op": "sincronizar", "args": {}, campo: "x"}]}
    assert any(campo in p for p in F.validar(plano))
