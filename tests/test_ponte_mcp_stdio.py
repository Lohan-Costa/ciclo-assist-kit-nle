"""A ponte stdio → MCP HTTP do serviço sem janela (o app do Claude na aula de 2026-11-20)."""
from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest

_ARQ = Path(__file__).resolve().parent.parent / "tools" / "ponte_mcp_stdio.py"


@pytest.fixture
def ponte(monkeypatch):
    spec = importlib.util.spec_from_file_location("ponte_mcp_stdio", _ARQ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    saidas: list[dict] = []
    monkeypatch.setattr(m, "_escrever", saidas.append)
    monkeypatch.setattr(m, "LIMITE_S", 0.2)
    m.saidas = saidas
    return m


def _call(nome, args=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": {"name": nome, "arguments": args or {}}}


def test_ferramenta_rapida_responde_direto(ponte, monkeypatch):
    monkeypatch.setattr(ponte, "_post", lambda msg: {"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [
        {"type": "text", "text": "pronto"}], "isError": False}})
    ponte._atender(_call("listar_bins"), None)
    assert ponte.saidas[-1]["result"]["content"][0]["text"] == "pronto"


def test_ferramenta_longa_vira_operacao_e_o_aguardar_entrega(ponte, monkeypatch):
    """⛔ MEDIDO 2026-11-19: o app do Claude desiste em ~1 min; abrir o MC levou 358 s."""
    solta = threading.Event()

    def lento(msg):
        solta.wait(5)
        return {"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": "aberto"}],
                                                              "isError": False}}
    monkeypatch.setattr(ponte, "_post", lento)
    ponte._atender(_call("abrir_programa", id_=7), None)
    texto = ponte.saidas[-1]["result"]["content"][0]["text"]
    assert ponte.saidas[-1]["id"] == 7 and "continua rodando" in texto and not ponte.saidas[-1]["result"]["isError"]
    op = texto.split('operacao="')[1].split('"')[0]
    ponte._atender(_call("aguardar_operacao", {"operacao": op}, id_=8), None)
    assert "continua rodando" in ponte.saidas[-1]["result"]["content"][0]["text"]     # ainda não acabou
    solta.set()
    ponte._atender(_call("aguardar_operacao", {"operacao": op}, id_=9), None)
    assert ponte.saidas[-1]["id"] == 9 and ponte.saidas[-1]["result"]["content"][0]["text"] == "aberto"
    ponte._atender(_call("aguardar_operacao", {"operacao": op}, id_=10), None)
    assert ponte.saidas[-1]["result"]["isError"]                                       # entregue uma vez só


def test_lista_esconde_o_portao_filtra_e_acrescenta_o_aguardar(ponte, monkeypatch):
    monkeypatch.setattr(ponte, "_post", lambda msg: {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [
        {"name": n} for n in ("pedir_confirmacao", "listar_bins", "montar_corte")]}})
    ponte._atender({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"listar_bins", "pedir_confirmacao"})
    nomes = [t["name"] for t in ponte.saidas[-1]["result"]["tools"]]
    assert nomes == ["listar_bins", "aguardar_operacao"]


def test_fora_da_lista_e_recusada_sem_ir_ao_servico(ponte, monkeypatch):
    monkeypatch.setattr(ponte, "_post", lambda msg: pytest.fail("não devia chamar o serviço"))
    ponte._atender(_call("montar_corte"), {"listar_bins"})
    ponte._atender(_call("pedir_confirmacao"), None)
    assert all(s["result"]["isError"] for s in ponte.saidas)


def test_servico_fora_do_ar_vira_erro_legivel(ponte, monkeypatch):
    monkeypatch.setattr(ponte, "_url", lambda: None)
    ponte._atender(_call("listar_bins"), None)
    assert "servico_sem_janela.py iniciar" in ponte.saidas[-1]["result"]["content"][0]["text"]


def test_initialize_anuncia_o_nome_da_configuracao(ponte, monkeypatch):
    monkeypatch.setattr(ponte, "_post", lambda msg: {"jsonrpc": "2.0", "id": 0, "result": {
        "serverInfo": {"name": "ciclo", "version": "0"}}})
    ponte._atender({"jsonrpc": "2.0", "id": 0, "method": "initialize"}, None)
    assert ponte.saidas[-1]["result"]["serverInfo"]["name"] == "edicao"
