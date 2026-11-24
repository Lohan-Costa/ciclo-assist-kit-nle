"""O conselho magro do fluxo (`motor/conselho.py`): o modelo decide, o código age."""

from __future__ import annotations

import json
import subprocess

import pytest

from cicloassist.motor import conselho as C
from cicloassist.motor import turno_magro as T


def test_acao_inventada_vira_esperar():
    r = C.ler_resposta({"explicacao": "x", "acao": "formatar_o_disco", "args": {"a": 1}})
    assert r["acao"] == "esperar" and r["args"] == {} and "não existe" in r["explicacao"]


def test_args_so_com_tentar_de_novo():
    assert C.ler_resposta({"acao": "pular", "args": {"x": 1}})["args"] == {}
    assert C.ler_resposta({"acao": "tentar_de_novo", "args": {"x": 1}})["args"] == {"x": 1}


def test_o_turno_e_magro(monkeypatch):
    """⛔ Sem ferramenta, sem MCP, prompt de sistema próprio — e o `--tools ""` junto do `--restricted`."""
    visto = {}

    def run(cmd, **kw):
        visto["cmd"] = cmd
        res = {"type": "result", "result": '```json\n{"explicacao":"ok","acao":"pular","args":{}}\n```',
               "modelUsage": {"m": {"inputTokens": 1800, "outputTokens": 60}}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(res) + "\n", "")

    monkeypatch.setattr(T.subprocess, "run", run)
    monkeypatch.setattr(T, "achar_o_cli", lambda: "claude")
    monkeypatch.setattr(T, "ambiente_do_modelo", lambda m: ("", {}))

    class P:
        id, op, args, tentativas, motivo, estado, avisos = "salvar", "salvar_tudo", {}, 1, "falhou", "falhou", []

    class F:
        id, nome, estado, atual, passos, origem = "f1", "X", "esperando", 0, [P()], "modelo"

    r = C.aconselhar(F(), modelo="")
    cmd = visto["cmd"]
    assert r["acao"] == "pular" and r["uso"]["tokens"] == 1860
    assert "--system-prompt" in cmd and "--strict-mcp-config" in cmd and "--mcp-config" not in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and "--allowedTools" not in cmd


def test_sem_result_diz_o_stderr(monkeypatch):
    monkeypatch.setattr(T.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "login expirado\n"))
    monkeypatch.setattr(T, "achar_o_cli", lambda: "claude")
    monkeypatch.setattr(T, "ambiente_do_modelo", lambda m: ("", {}))

    class F:
        id, nome, estado, atual, passos, origem = "f1", "X", "esperando", 0, [], "modelo"

    with pytest.raises(C.ConselhoFalhou, match="login expirado"):
        C.aconselhar(F(), modelo="")
