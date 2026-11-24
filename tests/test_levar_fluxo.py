"""N6: um fluxo vai de uma máquina à outra, e o que chega de fora não roda nem substitui nada."""
from __future__ import annotations

import pytest

from cicloassist.mcp import ferramentas as _todas  # noqa: F401 — registra as reais
from cicloassist.servico import receitas as R
from cicloassist.servico import rotas


PASSOS = [{"id": "a", "op": "salvar_tudo", "args": {}}]
PARAM = {"diaria": {"tipo": "texto", "rotulo": "Diária"}}


def _texto(nome="meu-fluxo", passos=PASSOS):
    return R.texto_de(nome, "um fluxo", PARAM, passos, "Meu fluxo")


def test_o_que_viaja_volta_igual_com_as_posicoes():
    r = R.ler_texto(_texto(), "editor")
    posicoes = {"nos": {"a": [10, 20]}, "vista": {"x": 0, "y": 0, "z": 1}}
    lida, pos, avisos = R.importar(R.para_exportar(r, posicoes))
    assert lida.nome == "meu-fluxo" and lida.passos == PASSOS and lida.parametros == PARAM and lida.origem == "editor"
    assert pos == posicoes and avisos == []


def test_as_posicoes_nao_atrapalham_quem_le_a_receita():
    r = R.ler_texto(_texto(), "editor")
    assert R.ler_texto(R.para_exportar(r, {"nos": {}, "vista": {}}), "editor").passos == PASSOS


def test_importar_nao_substitui_um_fluxo_daqui():
    R.salvar(_texto())
    outra = _texto(passos=[{"id": "b", "op": "salvar_tudo", "args": {}}])
    r, _p, avisos = R.importar(outra)
    assert r.nome == "meu-fluxo-2" and "meu-fluxo-2" in avisos[0]
    assert R.buscar("meu-fluxo").passos == PASSOS


def test_importar_o_mesmo_nao_duplica():
    R.salvar(_texto())
    r, _p, avisos = R.importar(_texto())
    assert r.nome == "meu-fluxo" and "já estava" in avisos[0] and "meu-fluxo-2" not in R.todas()


def test_operacao_proibida_nao_entra():
    texto = _texto(passos=[{"id": "g", "op": "gravar_na_memoria_da_producao", "args": {"producao": "X"}}])
    with pytest.raises(R.ReceitaInvalida, match="não pode ser passo"):
        R.importar(texto)
    assert "meu-fluxo" not in R.todas()


def test_operacao_que_nao_existe_diz_qual():
    with pytest.raises(R.ReceitaInvalida, match="apagar_tudo"):
        R.importar(_texto(passos=[{"id": "x", "op": "apagar_tudo", "args": {}}]))


def test_arquivo_que_nao_e_fluxo_e_recusado():
    with pytest.raises(R.ReceitaInvalida):
        R.importar("# uma nota qualquer\n")


def test_arquivo_gigante_e_recusado():
    with pytest.raises(R.ReceitaInvalida, match="grande demais"):
        R.importar(_texto() + "x" * (R.TETO_DO_ARQUIVO + 1))


def test_caminho_de_outra_maquina_e_avisado():
    passos = [{"id": "a", "op": "abrir_programa", "args": {"programa": "premiere", "projeto": "D:\\PROJETOS\\X.prproj"}}]
    _r, _p, avisos = R.importar(_texto(passos=passos))
    assert "D:\\PROJETOS\\X.prproj" in avisos[0]


def test_exportar_nao_escreve_por_cima(tmp_path):
    (tmp_path / "f.md").write_text("meu", encoding="utf-8")
    assert R.nome_de_arquivo_livre(tmp_path, "f").name == "f (2).md"


def _pedido(corpo):
    return type("P", (), {"json": lambda self: corpo})()


def test_a_rota_grava_na_pasta_escolhida_e_cancelar_nao_faz_nada(tmp_path, monkeypatch):
    from cicloassist.servico import seletor

    R.salvar(_texto())
    destino = tmp_path / "escolhida"
    destino.mkdir()
    monkeypatch.setattr(seletor, "escolher", lambda *a, **k: [])
    assert b'"cancelado"' in rotas.rota_oficina_exportar(_pedido({"nome": "meu-fluxo"})).corpo
    assert list(destino.iterdir()) == []
    monkeypatch.setattr(seletor, "escolher", lambda *a, **k: [str(destino)])
    assert b'"ok": true' in rotas.rota_oficina_exportar(_pedido({"nome": "meu-fluxo"})).corpo
    assert (destino / "meu-fluxo.md").exists()


def test_a_rota_de_importar_diz_o_motivo(tmp_path, monkeypatch):
    from cicloassist.servico import seletor

    ruim = tmp_path / "x.md"
    ruim.write_text("nada", encoding="utf-8")
    monkeypatch.setattr(seletor, "escolher", lambda *a, **k: [str(ruim)])
    assert "não é um fluxo" in rotas.rota_oficina_importar(_pedido({})).corpo.decode("utf-8")
