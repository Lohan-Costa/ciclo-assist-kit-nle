"""O que vale para a suíte inteira: nenhum teste encosta na máquina de quem roda.

⛔⛔ MEDIDO no macOS (2026-09-14): os testes isolavam a pasta de dados por `LOCALAPPDATA`,
que só o Windows lê. No Mac a suíte gravou `config.json` na pasta REAL do usuário — e um
teste passou a falhar porque o anterior tinha deixado lá um endereço do Ollama. Teste que
depende do estado da máquina reporta o humor dela, não o código.

Por isso a pasta de dados vem de `CICLOASSIST_DADOS`, que `servico/config.pasta()` lê em
qualquer sistema, e as variáveis que o desenvolvimento exporta saem de cena.
"""

from __future__ import annotations

import pytest

from cicloassist.avid import escopo as _escopo


@pytest.fixture(autouse=True)
def sem_borda_do_piloto(monkeypatch):
    """⛔ A borda verde-água de verdade abriria janelas na tela de quem roda a suíte."""
    import contextlib

    from cicloassist.piloto import borda
    monkeypatch.setattr(borda, "acesa", lambda *a, **k: contextlib.nullcontext())


@pytest.fixture(autouse=True)
def sem_dialogo_do_mc(monkeypatch):
    """⛔ Olha as janelas de verdade: com o Media Composer aberto num diálogo, 6 testes do salvar falhavam (medido em 2026-11-09)."""
    from cicloassist.avid import socorro
    monkeypatch.setattr(socorro, "inesperada", lambda: False)


@pytest.fixture(autouse=True)
def sem_mcp_do_premiere(monkeypatch):
    """⛔⛔ O servidor MCP nativo do Premiere (27.1+) é estado da MÁQUINA, como o Media Composer.

    Com ele ligado (o Mac mini de desenvolvimento, 2026-11-06), toda leitura do Premiere iria ao
    Premiere REAL em vez da ponte falsa do teste. Padrão: porta fechada e via CEP; quem testa o MCP
    sobe o servidor falso de `tests/test_mcp_do_premiere.py` e aponta a variável para ele.
    """
    from cicloassist.nle.premiere import mcp_nativo
    monkeypatch.setenv("CICLOASSIST_PREMIERE_MCP", "http://127.0.0.1:9/premiere/mcp")
    monkeypatch.setenv("CICLOASSIST_PREMIERE_VIA", "cep")
    monkeypatch.delenv("CICLOASSIST_PREMIERE_MCP_TOKEN", raising=False)
    mcp_nativo.esquecer()
    yield
    mcp_nativo.esquecer()


@pytest.fixture(autouse=True)
def maquina_descartavel(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path / "CicloAssist"))
    for variavel in ("CICLOASSIST_CACHE", "CICLOASSIST_LOGS", "CICLOASSIST_OLLAMA"):
        monkeypatch.delenv(variavel, raising=False)

    # ⛔⛔ E o MEDIA COMPOSER da máquina também é estado dela. MEDIDO em 2026-09-14, ao
    #    pôr o escopo de projeto na fila de análise: com o MC aberto aqui, `escopo.agora()`
    #    perguntava a ele o projeto e varria 42 bins REAIS — a suíte foi de 12 s para 40 s e
    #    um teste passou a falhar porque a fila do teste foi filtrada pelo projeto do
    #    editor. Sem MC aberto o mesmo teste passava: o pior tipo de teste, o que depende
    #    de o autor ter ou não um programa aberto.
    #
    # ⭐ Quem quiser exercitar o escopo o injeta (`monkeypatch.setattr(escopo, ...)`); o
    #   padrão é "nenhum projeto aberto", que cai na varredura guardada no cache isolado.
    _escopo.esquecer()
    monkeypatch.setattr(_escopo, "projeto_aberto",
                        lambda *a, **k: _escopo.SEM_PROJETO)
    yield
    _escopo.esquecer()
