"""A conta Claude do app (`cicloassist/conta.py`, plano `docs/plano/2026-11-07-aba-conta.md`).

O que se prova sem conta nenhuma: todo `claude` do app sobe com a pasta PRÓPRIA (`CLAUDE_CONFIG_DIR`), a aba só recebe
os campos da conta (nada de pastas nem ids), o "Not logged in" vira a frase que manda à aba, e o uso das janelas que um
turno contou fica guardado para a aba mostrar.
"""
from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from cicloassist import conta as C
from cicloassist.motor import claude as M
from cicloassist.servico import config


@pytest.fixture
def cli_falso(tmp_path, monkeypatch):
    """Um `claude` de mentira que responde o `auth status` e registra com que pasta foi chamado."""
    if sys.platform == "win32":
        pytest.skip("o dublê é um script de shell")
    registro = tmp_path / "chamadas.txt"
    script = tmp_path / "claude"
    script.write_text(f"""#!/bin/sh
echo "$CLAUDE_CONFIG_DIR $*" >> "{registro}"
if [ "$1 $2" = "auth status" ]; then
  echo '{{"loggedIn": true, "authMethod": "claude.ai", "email": "editor@exemplo.com", "orgName": "Casa",
         "subscriptionType": "pro", "loginExpiresAt": "2026-12-07T16:10:44.235Z",
         "orgId": "nao-deve-sair", "configDirectory": "/nao/deve/sair"}}'
fi
""", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(C, "_cli", lambda: str(script))
    return registro


def test_todo_claude_do_app_sobe_com_a_pasta_propria():
    amb = M._ambiente_do_cli()
    assert amb["CLAUDE_CONFIG_DIR"] == str(config.pasta() / "claude")
    assert amb["MCP_TOOL_TIMEOUT"], "o prazo de ferramenta continua"
    assert (config.pasta() / "claude").is_dir()


def test_o_modelo_do_mac_tambem_usa_a_pasta_propria(monkeypatch):
    modelo, amb = M.ambiente_do_modelo("claude-sonnet-5")
    assert amb["CLAUDE_CONFIG_DIR"] == str(C.pasta())


def test_o_estado_so_traz_os_campos_da_conta(cli_falso):
    e = C.estado()
    assert e["conta"] == {"loggedIn": True, "authMethod": "claude.ai", "email": "editor@exemplo.com",
                          "orgName": "Casa", "subscriptionType": "pro", "loginExpiresAt": "2026-12-07T16:10:44.235Z"}
    assert "orgId" not in json.dumps(e) and "/nao/deve/sair" not in json.dumps(e)
    chamada = cli_falso.read_text(encoding="utf-8").strip()
    assert chamada == f"{C.pasta()} auth status --json", "o status é o da pasta do APP"


def test_sem_cli_a_aba_diz_e_nao_cai(monkeypatch):
    def sem():
        raise M.MotorIndisponivel("O Claude Code não foi encontrado nesta máquina")
    monkeypatch.setattr(C, "_cli", sem)
    e = C.estado()
    assert e["conta"] is None and "não foi encontrado" in e["erro"]


def test_sem_conta_o_erro_do_cli_vira_a_frase_da_aba():
    assert M.frase_do_erro("Not logged in · Please run /login") == M.SEM_CONTA
    assert "Configurações › Conta" in M.SEM_CONTA
    assert M.frase_do_erro("Overloaded") == "Overloaded"
    eventos = list(M._traduzir({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}))
    assert ("erro", {"mensagem": M.SEM_CONTA}) in eventos


def test_o_uso_que_o_turno_contou_fica_para_a_aba():
    assert C.ultimo_uso() is None
    evento = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
        "five_hour": {"utilization": 0.42, "resetsAt": 1794100000},
        "seven_day": {"utilization": 0.17, "resetsAt": 1794500000}}}}
    saida = list(M._traduzir(evento))
    assert saida[0][0] == "limite"
    u = C.ultimo_uso()
    assert u["uso"] == {"five_hour": 0.42, "seven_day": 0.17}
    assert u["reseta_em"]["seven_day"] == 1794500000 and u["quando"] > 0


def test_as_rotas_da_conta(cli_falso):
    from cicloassist.servico import rotas as R
    from cicloassist.servico.http import ROTAS, Pedido

    assert ROTAS[("GET", "/conta")][1] is False, "a página é navegação de topo"
    assert ROTAS[("POST", "/conta/entrar")][1] and ROTAS[("POST", "/conta/sair")][1], "quem AGE passa pelo porteiro"
    assert b"Conta" in R.rota_conta_pagina(Pedido("GET", "/conta", {}, b"")).corpo
    e = json.loads(R.rota_conta_estado(Pedido("GET", "/conta/estado", {}, b"")).corpo)
    assert e["conta"]["email"] == "editor@exemplo.com"
    r = json.loads(R.rota_conta_sair(Pedido("POST", "/conta/sair", {}, b"{}")).corpo)
    assert r["ok"] and "auth logout" in cli_falso.read_text(encoding="utf-8")


def test_a_conta_nunca_abre_a_credencial():
    """⛔ Regra da casa (banco, `transversal/operacoes.md`): o app não lê nem intermedeia credencial do Claude."""
    codigo = [l for l in open(C.__file__, encoding="utf-8").read().splitlines()
              if l.strip() and not l.strip().startswith("#")]
    corpo = "\n".join(codigo).split('"""', 2)[-1]   # sem a docstring do módulo
    for proibido in (".credentials", "security find", "Keychain", "CLAUDE_CODE_OAUTH_TOKEN"):
        assert proibido not in corpo, proibido


def test_a_pagina_e_os_estaticos_existem():
    from cicloassist.servico.http import DIR_PAINEL
    for nome in ("conta.html", "conta.js", "conta.css"):
        assert (DIR_PAINEL / nome).is_file(), nome


def test_sem_conta_a_decupagem_pelo_claude_diz_a_frase_da_aba(tmp_path, monkeypatch):
    """⭐ 2026-11-07: antes, sem conta, cada lote falhava como "o modelo não respondeu em JSON" (ele lia o
    "Not logged in" como se fosse a decupagem). Um `claude` dublê responde como o de verdade responde sem login."""
    if sys.platform == "win32":
        pytest.skip("o dublê é um script de shell")
    from cicloassist.motor import decupador as D
    script = tmp_path / "claude"
    script.write_text("""#!/bin/sh
echo '{"type":"assistant","message":{"content":[{"type":"text","text":"Not logged in · Please run /login"}]},"error":"authentication_failed"}'
echo '{"type":"result","subtype":"success","is_error":true,"result":"Not logged in · Please run /login"}'
""", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(D, "achar_o_cli", lambda: str(script))
    with pytest.raises(D.SemConta) as e:
        D.decupar([("a" * 64, "A001_C003")], "http://127.0.0.1:1/mcp/x", timeout_s=30)
    assert str(e.value) == M.SEM_CONTA


def test_sem_conta_a_fila_para_no_primeiro_lote_com_a_frase(tmp_path, monkeypatch):
    """Nenhum lote vai dar certo sem conta: a fila para e a tarefa diz onde entrar (antes: "N falharam", calado)."""
    import importlib.util
    from pathlib import Path

    from cicloassist.motor import decupador as D
    from cicloassist.servico import tarefas as T
    spec = importlib.util.spec_from_file_location("densidade", Path(__file__).with_name("test_densidade.py"))
    densidade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(densidade)
    chamadas = []

    def sem_conta(*a, **k):
        chamadas.append(1)
        raise D.SemConta(M.SEM_CONTA)

    monkeypatch.setattr(D, "decupar", sem_conta)
    vistos = {}
    original = T._terminar

    def guardar(tarefa, estado, erro=""):
        vistos.update(estado=estado, erro=erro)
        original(tarefa, estado, erro)

    monkeypatch.setattr(T, "_terminar", guardar)
    densidade._rodar_a_fila(tmp_path, monkeypatch, "macro")
    assert vistos == {"estado": "erro", "erro": M.SEM_CONTA}
    assert len(chamadas) == 1
