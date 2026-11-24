"""O CLI falante não pode travar o turno.

⛔⛔ Com `stderr=subprocess.PIPE` e ninguém lendo, o buffer do sistema (~64 KB) enche e o
processo filho **bloqueia ao escrever** — o stdout para de sair e o turno congela sem nada
acusando. Foi o que travou o painel por cinco minutos em 2026-09-12 no caminho de SESSÃO
(`sessao._drenar_stderr` guarda a lição); o caminho de TURNO SOLTO (`motor/claude.py`)
ainda lia o stderr só no fim.

⭐ Aqui o CLI é um Python de mentira: escreve muito no stderr, responde no stdout e sai.
Não há modelo, não há rede, e o teste falha por TEMPO — que é como o defeito se manifesta.
"""

from __future__ import annotations

import sys
import textwrap
import threading
import time

import pytest

from cicloassist.motor import claude as C

#: Bem acima do buffer do sistema (~64 KB), e ainda rápido de escrever.
BARULHO_KB = 512


@pytest.fixture
def cli_falante(tmp_path, monkeypatch):
    """Um `claude` de mentira: N KB de aviso no stderr + uma resposta no stdout."""
    script = tmp_path / "cli_falante.py"
    script.write_text(textwrap.dedent(f"""
        import json, sys
        linha = "x" * 1023 + "\\n"
        for _ in range({BARULHO_KB}):
            sys.stderr.write(linha)
        sys.stderr.flush()
        eventos = [
            {{"type": "system", "subtype": "init", "tools": [], "mcp_servers": []}},
            {{"type": "assistant", "message": {{"content": [
                {{"type": "text", "text": "ok"}}]}}}},
            {{"type": "result", "subtype": "success", "num_turns": 1}},
        ]
        for e in eventos:
            sys.stdout.write(json.dumps(e) + "\\n")
            sys.stdout.flush()
    """), encoding="utf-8")

    falso = tmp_path / "claude.cmd"
    falso.write_text(f'@echo off\n"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    monkeypatch.setattr(C, "achar_o_cli", lambda: str(falso))
    # ⚠️ O CLI é chamado com as flags do produto; o script ignora todas.
    monkeypatch.setattr(C, "_ambiente_do_cli", lambda: None)
    return falso


@pytest.mark.skipif(sys.platform != "win32", reason="o `.cmd` do dublê é do Windows")
def test_o_cli_que_fala_muito_no_stderr_nao_trava_o_turno(cli_falante):
    tipos: list[str] = []
    erro: list[BaseException] = []

    def moer():
        try:
            for tipo, _dado in C.conversar("oi", url_do_mcp="http://127.0.0.1:9/mcp/x",
                                           ferramentas_de_leitura=[], timeout_s=30):
                tipos.append(tipo)
        except BaseException as e:  # noqa: BLE001
            erro.append(e)

    t = threading.Thread(target=moer, daemon=True)
    comeco = time.monotonic()
    t.start()
    t.join(timeout=30)

    assert not t.is_alive(), (
        f"o turno ficou preso com {BARULHO_KB} KB de stderr — é o buffer cheio, e o "
        f"sintoma em produção é o painel parado sem erro nenhum")
    assert not erro, erro
    assert "fim" in tipos, f"o turno não chegou ao fim ({tipos})"
    assert time.monotonic() - comeco < 25
