"""⭐⭐ F4 — "transformar em fluxo" a partir do chat (plano 2026-11-03, feito em 2026-11-04).

O chat fez o trabalho passo a passo; o serviço anotou cada ESCRITA que rodou (automático ou cartão), e o
botão as liga numa receita do editor — sem turno do modelo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cicloassist.servico import fluxo, historico, receitas, rotas

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def limpo():
    historico.esquecer()
    yield
    historico.esquecer()


def _diaria(tmp_path, d="D05"):
    pasta = tmp_path / "diaria"
    pasta.mkdir()
    mxf = tmp_path / "MXF"
    mxf.mkdir()
    return [
        ("abrir_programa", {"programa": "resolve", "projeto": d}, {"ok": True}),
        ("converter_para_opatom", {"projeto": d, "pasta": str(pasta)}, {"pasta": str(mxf), "clipes": 4}),
        ("importar_masters_opatom", {"pasta": str(mxf), "bin": f"CAMERA {d}"}, {"bin": f"CAMERA {d}"}),
        ("som_direto_gerenciado", {"pasta": str(pasta), "bin": f"SOM {d}"}, {"bin": f"SOM {d}"}),
        ("sincronizar", {"bins": [f"CAMERA {d}", f"SOM {d}"], "nome": d, "subclipes": "uma_bin"},
         {"ok": True}),
    ]


def test_as_escritas_viram_um_plano_ligado_pelas_saidas(tmp_path):
    for op, args, saida in _diaria(tmp_path):
        historico.anotar_feito(op, args, saida)
    plano = receitas.do_chat(historico.feitos(), "Prepare a diária D05")
    assert fluxo.validar(plano) == []
    por_op = {p["op"]: p for p in plano["passos"]}
    # ⭐ a pasta MXF que a conversão devolveu é a que a importação usa: vira a saída do passo
    assert por_op["importar_masters_opatom"]["args"]["pasta"] == "{converter_para_opatom.pasta}"
    # a mesma pasta da diária é UM parâmetro, nos dois passos que a usam
    assert por_op["converter_para_opatom"]["args"]["pasta"] == por_op["som_direto_gerenciado"]["args"]["pasta"]
    # valor da lista fechada fica fixo
    assert por_op["abrir_programa"]["args"]["programa"] == "resolve"
    assert por_op["sincronizar"]["args"]["subclipes"] == "uma_bin"


def test_a_receita_nasce_parametrizada_pela_diaria(tmp_path):
    for op, args, saida in _diaria(tmp_path):
        historico.anotar_feito(op, args, saida)
    texto = receitas.do_plano(receitas.do_chat(historico.feitos(), "Prepare a diária D05"), "04/11/2026",
                              de="um trabalho feito no chat")
    r = receitas.conferir_texto(texto)
    assert "D05" not in json.dumps(r.passos)               # a diária de hoje virou parâmetro…
    assert "CAMERA {" in json.dumps(r.passos, ensure_ascii=False)   # …e "CAMERA D05" segue ela
    assert any(s.get("tipo") == "pasta" for s in r.parametros.values())
    assert "D05" not in r.titulo and "{" in r.titulo
    assert "trabalho feito no chat" in r.descricao


def test_falha_nao_entra(tmp_path):
    historico.anotar_feito("salvar_tudo", {}, {"ok": False, "motivo": "MC fechado"})
    historico.anotar_feito("salvar_tudo", {}, {"erro": "x"})
    assert historico.feitos() == []


def test_a_rota_grava_a_receita_do_editor(tmp_path, monkeypatch):
    monkeypatch.setattr(receitas, "pasta_do_editor", lambda: tmp_path / "receitas")
    for op, args, saida in _diaria(tmp_path):
        historico.anotar_feito(op, args, saida)
    historico.Registro("t1", "Prepare a diária D05 no Media Composer").terminar()
    r = json.loads(rotas.rota_receitas_do_chat(None).corpo)
    assert r["ok"], r
    assert r["passos"] == 5
    assert (tmp_path / "receitas" / f"{r['receita']}.md").exists()
    assert json.loads(rotas.rota_chat_feitos(None).corpo)["feitos"][0]["op"] == "abrir_programa"


def test_sem_nada_feito_a_rota_diz():
    assert json.loads(rotas.rota_receitas_do_chat(None).corpo)["ok"] is False


def test_os_dois_caminhos_anotam():
    serv = (RAIZ / "cicloassist" / "mcp" / "servidor.py").read_text(encoding="utf-8")
    pend = (RAIZ / "cicloassist" / "servico" / "pendencias.py").read_text(encoding="utf-8")
    assert 'if ferramenta.escreve and papel() == "chat":' in serv
    assert "_historico.anotar_feito(p.ferramenta" in pend


def test_o_painel_oferece_no_fim_do_turno_e_do_cartao():
    js = (RAIZ / "cicloassist" / "painel" / "painel.js").read_text(encoding="utf-8")
    assert 'if (daConversa === "chat") { oferecerFluxo(); }' in js
    assert "if (conversaDoChat.contains(cartao)) { oferecerFluxo(); }" in js
    assert 'fetch("/receitas/do-chat"' in js


def test_parametro_com_sufixo_volta_ao_nome_base_quando_livre(tmp_path):
    """D05 pelo chat (04/11): o projeto do Resolve dobrou em "TESTE SIMULADO DR {nome}" e o do MC ficou
    "projeto_2" — "Projeto 2" no formulário, sem "Projeto" nenhum."""
    feitos = [
        {"op": "abrir_programa", "args": {"programa": "resolve", "projeto": "TESTE DR D05"}, "saida": {}},
        {"op": "abrir_programa", "args": {"programa": "media_composer", "projeto": "TESTE MC"}, "saida": {}},
        {"op": "sincronizar", "args": {"bins": ["CAM D05"], "nome": "D05"}, "saida": {}},
    ]
    r = receitas.conferir_texto(receitas.do_plano(receitas.do_chat(feitos, "x"), ""))
    assert "projeto" in r.parametros and "projeto_2" not in r.parametros
    assert r.parametros["projeto"]["rotulo"] == "Projeto"
    assert '"{projeto}"' in json.dumps(r.passos)


def test_o_titulo_e_o_primeiro_pedido_da_conversa(monkeypatch):
    historico.Registro("a", "Esta pasta tem a mídia bruta da diária de hoje: vídeos e som.").terminar()
    historico.Registro("b", "O Media Composer já fechou. Continue.").terminar()
    assert rotas._titulo_do_chat() == "Esta pasta tem a mídia bruta da diária de hoje"
