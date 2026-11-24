"""O glossário da casa (`o_que_quer_dizer`) — a planilha do editor, consultada termo a termo.

⭐ Pedido do editor (2026-09-22): *"o audiovisual é muito vivo e mutável… ir colhendo os
significados e onde cada expressão entra ajuda a guiar melhor o programa"*. O que estes
testes travam: a consulta devolve SÓ o que foi perguntado, o que falta vira colheita, e o
importador lê o formato real da planilha.
"""

from __future__ import annotations

import pytest

from cicloassist.mcp.ferramentas import glossario as G


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path / "dados"))


def test_acha_por_sigla_pela_forma_e_sem_acento():
    r = G.o_que_quer_dizer(["AAF", "voice over", "a.c", "assistente de camera"])
    assert set(r["termos"]) == {"AAF", "voice over", "a.c", "assistente de camera"}
    assert r["termos"]["voice over"][0]["termo"] == "V.O (voice over)"


def test_devolve_so_o_que_foi_perguntado():
    """⚠️ 263 termos: carregar tudo para responder um gastaria a janela à toa."""
    r = G.o_que_quer_dizer(["AAF"])
    assert len(r["termos"]) == 1 and len(r["termos"]["AAF"]) <= 3


def test_o_que_falta_vira_colheita():
    """⭐ O termo que não está — e o que está SEM significado (48 na planilha medida) — vai
    para a lista que o editor completa. Achar só o NOME não é saber."""
    r = G.o_que_quer_dizer(["palavra-que-nao-existe", "barriga"])
    assert r["nao_estao_no_glossario"] == ["palavra-que-nao-existe"]
    assert r["sem_significado_ainda"] == ["barriga"]
    assert r["aviso"]
    G.o_que_quer_dizer(["palavra-que-nao-existe"])
    pend = G.pendentes()
    assert pend["palavra-que-nao-existe"]["vezes"] == 2
    assert pend["barriga"]["motivo"] == "na planilha, sem significado"


def test_claquete_traz_as_formas_entre_linguas():
    r = G.o_que_quer_dizer(["slate"])
    assert any(e.get("preferido") == "claquete" for e in r["termos"]["slate"])


def test_teto_de_termos_por_pergunta():
    r = G.o_que_quer_dizer([f"x{i}" for i in range(50)])
    assert len(r["nao_estao_no_glossario"]) == G.MAXIMO


def test_o_importador_le_o_formato_real_da_planilha():
    """⚠️ Medido: sinônimos DENTRO do termo (barra e parênteses), e parêntese que só
    qualifica (`Master (áudio)`) não vira forma."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "importar_glossario",
        Path(__file__).resolve().parents[1] / "tools" / "importar_glossario.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.formas_do_termo("V.O (voice over)") == ["V.O", "voice over"]
    assert mod.formas_do_termo("AD / Assistente de direção") == ["AD", "Assistente de direção"]
    assert mod.formas_do_termo("Master (áudio)") == ["Master"]
