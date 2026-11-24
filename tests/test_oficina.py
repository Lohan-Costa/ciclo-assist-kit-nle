"""A janela Fluxos e Agentes, só leitura (fase B1)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cicloassist.servico import aplicativo, rotas as R

PAINEL = Path(R.DIR_PAINEL)


def dados() -> dict:
    return json.loads(R.rota_oficina_dados(SimpleNamespace()).corpo)


def test_lista_as_receitas_e_os_agentes():
    d = dados()
    assert {"conformar-no-resolve", "preparar-a-diaria-no-media-composer"} & {f["nome"] for f in d["fluxos"]}
    agentes = {a["nome"]: a for a in d["agentes"]}
    assert agentes["agente-de-metadado"]["titulo"] == "Agente de metadado"
    assert agentes["agente-de-metadado"]["tipo"] == "conselheiro" and "regras" in agentes["agente-de-metadado"]["saidas"]
    assert all(n["rotulo"] for f in d["fluxos"] for n in f["nos"])
    assert agentes["agente-de-revisao-de-fontes"]["titulo"] == "Agente de revisão de fontes"
    abrir = next(n for f in d["fluxos"] for n in f["nos"] if n.get("op") == "abrir_programa")
    assert abrir["detalhe"]
    assert agentes["agente-de-metadado"]["texto"].startswith("---\nname: agente-de-metadado")


def fluxo_de(nome: str) -> dict:
    return next(f for f in dados()["fluxos"] if f["nome"] == nome)


def test_as_tres_receitas_viram_nodes_em_ordem_e_sem_mudar_uma_linha():
    conformar, mc, premiere = (fluxo_de(n) for n in ("conformar-no-resolve", "preparar-diaria-no-mc", "preparar-diaria-no-premiere"))
    assert [n["id"] for n in conformar["nos"]] == ["abrir_resolve", "conform"]
    assert len(mc["nos"]) == 9 and len(premiere["nos"]) == 7        # os passos e o gerente antes do sync
    ordem = [(x["de"], x["para"]) for x in mc["ligacoes"] if x["tipo"] == "ordem"]
    assert ordem == list(zip([n["id"] for n in mc["nos"]], [n["id"] for n in mc["nos"]][1:]))


def test_o_gerente_entra_antes_do_sync_como_node_de_agente():
    ids = [n["id"] for n in fluxo_de("preparar-diaria-no-mc")["nos"]]
    assert ids.index("agente_sync") == ids.index("sync") - 1
    gerente = next(n for n in fluxo_de("preparar-diaria-no-mc")["nos"] if n["id"] == "agente_sync")
    assert gerente["tipo"] == "agente" and gerente["rotulo"] == "Agente de revisão de fontes"


def test_a_referencia_a_outro_passo_vira_ligacao_de_dado():
    dado = [x for x in fluxo_de("preparar-diaria-no-mc")["ligacoes"] if x["tipo"] == "dado"]
    assert dado == [{"de": "conv", "para": "camera", "tipo": "dado", "campo": "pasta"}]


def test_dado_do_node_logo_antes_nao_desenha_segunda_linha():
    from cicloassist.servico.grafo_do_fluxo import da_receita

    g = da_receita([{"id": "a", "op": "converter_para_proxy", "args": {}},
                    {"id": "b", "op": "importar_no_premiere", "args": {"proxies": "{a.pasta}"}}], {}, {})
    assert g["ligacoes"] == [{"de": "a", "para": "b", "tipo": "ordem", "campo": "pasta"}]


def test_cada_campo_diz_de_onde_vem_o_valor():
    nos = {n["id"]: n for n in fluxo_de("preparar-diaria-no-mc")["nos"]}
    camera = {c["nome"]: c for c in nos["camera"]["campos"]}
    assert camera["Pasta"]["origem"] == "node" and camera["Pasta"]["texto"] == "‹Converter para OP-Atom · pasta›"
    assert camera["Bin"]["origem"] == "perguntar" and camera["Bin"]["texto"] == "‹Nome da diária› CAMERA"
    assert {c["nome"]: c for c in nos["abrir_resolve"]["campos"]}["Programa"] == {"nome": "Programa", "texto": "DaVinci Resolve", "origem": "fixo"}
    assert {c["nome"]: c for c in nos["sync"]["campos"]}["Fontes"]["texto"] == "CAM A, SOM DIRETO"


def test_sem_supervisao_nao_desenha_o_gerente():
    from cicloassist.servico.grafo_do_fluxo import da_receita

    g = da_receita([{"id": "s", "op": "sincronizar", "args": {"sem_supervisao": True}}], {}, {})
    assert [n["id"] for n in g["nos"]] == ["s"]


def test_receita_antiga_de_nome_velho_abre_com_o_nome_de_hoje():
    from cicloassist.servico.grafo_do_fluxo import da_receita

    g = da_receita([{"id": "s", "op": "sincronizar_com_o_orbita", "args": {}}], {}, {})
    assert g["nos"][-1]["op"] == "sincronizar" and g["nos"][-1]["rotulo"] == "Sincronizar" and g["nos"][-1]["catalogada"]


def test_todo_passo_das_receitas_da_casa_tem_ficha_e_toda_referencia_esta_declarada():
    from cicloassist.servico import catalogo_de_pecas as C
    from cicloassist.servico import fluxo as F
    from cicloassist.servico import receitas as R2

    casa = [r for r in R2.todas().values() if r.origem == "casa"]
    assert len(casa) >= 3
    for r in casa:
        por_id = {p["id"]: F.op_atual(p["op"]) for p in r.passos}
        for p in r.passos:
            assert F.op_atual(p["op"]) in C.CATALOGO, p["op"]
            for ref in F._referencias(p.get("args") or {}):
                raiz, _, campo = ref.partition(".")
                if campo:
                    assert campo.split(".")[0] in C.CATALOGO[por_id[raiz]].saidas, ref


def test_o_catalogo_so_tem_ferramentas_que_existem_e_nenhuma_que_sempre_pergunta():
    from cicloassist.mcp import ferramentas  # noqa: F401
    from cicloassist.mcp.registro import FERRAMENTAS
    from cicloassist.servico import catalogo_de_pecas as C

    assert all(op in FERRAMENTAS and not FERRAMENTAS[op].sempre_pergunta for op in C.CATALOGO)


def test_cada_node_diz_o_programa_que_ocupa():
    nos = {n["id"]: n for n in fluxo_de("preparar-diaria-no-mc")["nos"]}
    assert nos["abrir_resolve"]["programa"] == "DaVinci Resolve" and nos["conv"]["programa"] == "DaVinci Resolve"
    assert nos["sync"]["programa"] == "Media Composer" and nos["agente_sync"]["programa"] == ""
    assert {n["id"]: n for n in fluxo_de("preparar-diaria-no-premiere")["nos"]}["sync"]["programa"] == "Premiere"


def test_o_que_a_operacao_nao_deixa_mudar_aparece_travado():
    conv = next(n for n in fluxo_de("preparar-diaria-no-premiere")["nos"] if n["id"] == "conv")
    assert {"nome": "Altura", "texto": "1080", "origem": "travado"} in conv["campos"]
    assert "pasta" in conv["saidas"]


def test_peca_sem_ficha_abre_e_diz_que_nao_tem():
    from cicloassist.servico.grafo_do_fluxo import da_receita

    n = da_receita([{"id": "a", "op": "ferramenta_nova", "args": {}}], {}, {})["nos"][0]
    assert n["catalogada"] is False and n["programa"] == "" and n["saidas"] == []


def gravar_pos(corpo):
    return R.rota_oficina_posicoes(SimpleNamespace(json=lambda: corpo))


def test_sem_posicao_o_fluxo_vem_sem_nada_e_a_gravacao_volta_e_nao_toca_a_receita():
    alvo = Path(R.DIR_PAINEL).parent / "receitas" / "preparar-diaria-no-mc.md"
    antes = alvo.read_bytes()
    assert fluxo_de("preparar-diaria-no-mc")["posicoes"] is None
    r = gravar_pos({"fluxo": "preparar-diaria-no-mc", "nos": {"conv": [10, 20.26]}, "vista": {"x": 1, "y": 2, "z": 0.9}})
    assert r.status == 200
    assert fluxo_de("preparar-diaria-no-mc")["posicoes"] == {"nos": {"conv": [10.0, 20.3]}, "vista": {"x": 1.0, "y": 2.0, "z": 0.9}}
    assert alvo.read_bytes() == antes


@pytest.mark.parametrize("nos,vista", [
    ([], {"x": 0, "y": 0, "z": 1}), ({}, {"x": 0, "y": 0, "z": 1}),
    ({"a": [1]}, {"x": 0, "y": 0, "z": 1}), ({"a": ["x", 1]}, {"x": 0, "y": 0, "z": 1}),
    ({"a": [True, 1]}, {"x": 0, "y": 0, "z": 1}), ({"a": [1e9, 1]}, {"x": 0, "y": 0, "z": 1}),
    ({"a": [1, 1]}, {"x": 0, "y": 0, "z": 9}), ({"a": [1, 1]}, None),
])
def test_posicao_invalida_e_recusada(nos, vista):
    assert gravar_pos({"fluxo": "conformar-no-resolve", "nos": nos, "vista": vista}).status == 400
    assert fluxo_de("conformar-no-resolve")["posicoes"] is None


def test_fluxo_que_nao_existe_nao_vira_chave_no_arquivo():
    assert gravar_pos({"fluxo": "../../x", "nos": {"a": [1, 1]}, "vista": {"x": 0, "y": 0, "z": 1}}).status == 404


def test_arquivo_corrompido_vira_sem_posicao():
    from cicloassist.servico import posicoes_dos_fluxos as P

    P.arquivo().parent.mkdir(parents=True, exist_ok=True)
    P.arquivo().write_text("{ quebrado", encoding="utf-8")
    assert fluxo_de("conformar-no-resolve")["posicoes"] is None


def fios(*pares):
    return [{"de": a, "para": b} for a, b in pares]


def no(i, op="salvar_tudo", **k):
    return {"id": i, "op": op, "tipo": "passo", "rotulo": i.upper(), "args": {}, **k}


def test_a_linha_sai_na_ordem_das_ligacoes_e_nao_na_da_lista():
    from cicloassist.servico.grafo_do_fluxo import para_passos

    assert [p["id"] for p in para_passos([no("c"), no("a"), no("b")], fios(("a", "b"), ("b", "c")))] == ["a", "b", "c"]


def test_o_gerente_nao_vira_passo_e_a_linha_passa_por_ele():
    from cicloassist.servico.grafo_do_fluxo import para_passos

    ag = {"id": "agente_b", "tipo": "agente"}
    assert [p["id"] for p in para_passos([no("a"), ag, no("b")], fios(("a", "agente_b"), ("agente_b", "b")))] == ["a", "b"]


@pytest.mark.parametrize("nos,ligs,trecho", [
    ([], [], "nenhum node"),
    ([no("a"), no("b")], [], "um node só no começo"),
    ([no("a"), no("b"), no("c")], fios(("a", "c"), ("b", "c")), "um node só no começo"),
    ([no("a"), no("b"), no("c"), no("d")], fios(("a", "b"), ("c", "d"), ("d", "c")), "presos num círculo"),
    ([no("a"), no("b"), no("c")], [{"de": "a", "para": "c", "se": {"campo": "a.x", "e": "sim"}}, {"de": "a", "para": "b"}, {"de": "b", "para": "c"}], "única chegada"),
])
def test_o_que_o_executor_nao_roda_e_recusado_dizendo_por_que(nos, ligs, trecho):
    from cicloassist.servico.grafo_do_fluxo import GrafoInvalido, para_passos

    with pytest.raises(GrafoInvalido) as e:
        para_passos(nos, ligs)
    assert trecho in str(e.value)


def test_diamante_vira_lista_com_depois_de_e_se():
    from cicloassist.servico.grafo_do_fluxo import para_passos

    se_sim, se_nao = {"campo": "a.x", "e": "sim"}, {"campo": "a.x", "e": "nao"}
    p = para_passos([no("a"), no("b"), no("c"), no("d")], [{"de": "a", "para": "b", "se": se_sim}, {"de": "a", "para": "c", "se": se_nao}, {"de": "b", "para": "d"}, {"de": "c", "para": "d"}])
    assert [x["id"] for x in p] == ["a", "b", "c", "d"]
    assert "depois_de" not in p[1] and p[1]["se"] == se_sim and p[2]["depois_de"] == ["a"] and p[2]["se"] == se_nao and sorted(p[3]["depois_de"]) == ["b", "c"]


def test_a_ida_e_a_volta_do_desenho_nao_muda_a_receita():
    from cicloassist.servico import receitas as RX
    from cicloassist.servico.grafo_do_fluxo import para_passos

    for nome in ("conformar-no-resolve", "preparar-diaria-no-mc", "preparar-diaria-no-premiere"):
        g = fluxo_de(nome)
        assert para_passos(g["nos"], [x for x in g["ligacoes"] if x["tipo"] == "ordem"]) == RX.buscar(nome).passos, nome


def test_a_condicao_desenha_na_linha_e_passa_pelo_gerente():
    from cicloassist.servico.grafo_do_fluxo import da_receita, para_passos

    se = {"campo": "a.bin", "e": "sim"}
    g = da_receita([{"id": "a", "op": "som_direto_gerenciado", "args": {}}, {"id": "s", "op": "sincronizar", "args": {}, "se": se}], {}, {})
    assert {"de": "a", "para": "agente_s", "tipo": "ordem", "campo": "", "se": se} in g["ligacoes"]
    assert para_passos(g["nos"], [x for x in g["ligacoes"] if x["tipo"] == "ordem"])[1]["se"] == se


def bins(*nomes):
    return [{"tipo": "camera", "nome": "CAM", "bins": list(nomes)}]


def test_conferir_avisa_da_bin_que_ninguem_cria_sem_barrar():
    corpo = {"titulo": "T", "parametros": {}, "ligacoes": fios(("a", "s")),
             "nos": [no("a", "som_direto_gerenciado", args={"pasta": "/x", "bin": "RUSHES"}), no("s", "sincronizar", args={"fontes": bins("OUTRA")})]}
    d = json.loads(rota_de(R.rota_oficina_conferir, corpo).corpo)
    assert d["ok"] and "S procura a bin OUTRA" in d["avisos"][0]
    corpo["nos"][1]["args"] = {"fontes": bins("RUSHES")}
    assert json.loads(rota_de(R.rota_oficina_conferir, corpo).corpo)["avisos"] == []


def test_as_receitas_da_casa_nao_tem_aviso_de_bin():
    for nome in ("preparar-diaria-no-mc", "preparar-diaria-no-premiere"):
        g = fluxo_de(nome)
        d = json.loads(rota_de(R.rota_oficina_conferir, {"titulo": g["titulo"], "nome": g["nome"], "parametros": g["parametros"], "nos": g["nos"], "ligacoes": [x for x in g["ligacoes"] if x["tipo"] == "ordem"]}).corpo)
        assert d["ok"] and d["avisos"] == [], (nome, d)


def test_executar_recusa_fluxo_que_nao_existe_e_o_que_falta_preencher():
    assert not json.loads(rota_de(R.rota_oficina_executar, {"nome": "nao-ha"}).corpo)["ok"]
    d = json.loads(rota_de(R.rota_oficina_executar, {"nome": "preparar-diaria-no-mc", "parametros": {}}).corpo)
    assert not d["ok"] and "falta preencher" in d["motivo"]


def test_linha_para_tras_vira_volta_com_teto_e_ida_e_volta_nao_muda():
    from cicloassist.servico.grafo_do_fluxo import da_receita, para_passos

    nos = [no("a"), no("m", "entender_metadados_da_diaria"), no("p", "perguntar_ao_editor"), no("s", "criar_merged")]
    ligs = [{"de": "a", "para": "m"}, {"de": "m", "para": "s", "se": {"campo": "m.perguntas", "e": "nao"}}, {"de": "m", "para": "p", "se": {"campo": "m.perguntas", "e": "sim"}}, {"de": "p", "para": "m", "teto": 3}]
    passos = para_passos(nos, ligs)
    assert [p["id"] for p in passos] == ["a", "m", "p", "s"]         # a volta é um trecho contínuo, mesmo com o sync desenhado antes
    assert passos[2]["volta"] == {"para": "m", "teto": 3}
    g = da_receita(passos, {}, {})
    assert {"de": "p", "para": "m", "tipo": "ordem", "campo": "", "volta": True, "teto": 3} in g["ligacoes"]
    assert para_passos(g["nos"], [x for x in g["ligacoes"] if x["tipo"] == "ordem"]) == passos


def test_volta_ao_primeiro_node_faz_dele_o_comeco():
    from cicloassist.servico.grafo_do_fluxo import para_passos

    p = para_passos([no("m", "entender_metadados_da_diaria"), no("p", "perguntar_ao_editor")], [{"de": "m", "para": "p"}, {"de": "p", "para": "m", "teto": 2}])
    assert [x["id"] for x in p] == ["m", "p"] and p[1]["volta"] == {"para": "m", "teto": 2}


def test_circulo_que_repete_quem_grava_o_conferir_recusa():
    corpo = {"titulo": "T", "parametros": {}, "nos": [no("a"), no("b")], "ligacoes": fios(("a", "b"), ("b", "a"))}
    d = json.loads(rota_de(R.rota_oficina_conferir, corpo).corpo)
    assert not d["ok"] and any("que grava algo" in x for x in d["problemas"])


def test_peca_de_agente_e_de_pergunta_tem_estilo_proprio():
    pecas = {p["op"]: p for p in dados()["pecas"]}
    assert pecas["entender_metadados_da_diaria"]["estilo"] == "ia" and pecas["entender_metadados_da_diaria"]["agente"] == "agente-de-metadado"
    assert pecas["perguntar_ao_editor"]["estilo"] == "pergunta"


def test_o_preco_vem_antes_e_conta_o_pior_caso_das_voltas():
    from cicloassist.servico.grafo_do_fluxo import custo_de_ia

    assert custo_de_ia([{"id": "a", "op": "converter_para_proxy", "args": {}}]) is None
    linha = custo_de_ia([{"id": "m", "op": "entender_metadados_da_diaria", "args": {}}])
    assert linha["chamadas"] == 1 and "5 mil tokens" in linha["texto"]
    volta = custo_de_ia([{"id": "m", "op": "entender_metadados_da_diaria", "args": {}}, {"id": "p", "op": "perguntar_ao_editor", "args": {}, "volta": {"para": "m", "teto": 2}}])
    assert volta["chamadas"] == 3 and "15 mil tokens" in volta["texto"]
    assert "não tem tokens medidos" in custo_de_ia([{"id": "s", "op": "sincronizar", "args": {}}])["texto"]
    assert custo_de_ia([{"id": "s", "op": "sincronizar", "args": {"sem_supervisao": True}}]) is None


def test_o_preco_conta_o_piloto_so_onde_ele_opera_a_tela():
    from cicloassist.servico.grafo_do_fluxo import custo_de_ia

    abrir_mc = {"id": "a", "op": "abrir_programa", "args": {"programa": "media_composer"}}
    assert custo_de_ia([{"id": "a", "op": "abrir_programa", "args": {"programa": "resolve"}}]) is None
    assert custo_de_ia([abrir_mc])["piloto"] == 1
    # ⭐ O localizador é IA: o texto não pode dizer "chamadas" de agente, e o preço não pode sumir.
    salvar = custo_de_ia([{"id": "s", "op": "salvar_tudo", "args": {}}])
    assert salvar["piloto"] == 1 and salvar["chamadas"] == 0 and "O piloto opera a tela" in salvar["texto"] and "Usa IA em até 0" not in salvar["texto"]
    # Programa que só se sabe ao rodar: o pior caso.
    assert custo_de_ia([{"id": "a", "op": "abrir_programa", "args": {"programa": "{programa}"}}])["piloto"] == 1
    # Trocar o foco para indexar não é o piloto operando a tela.
    assert custo_de_ia([{"id": "m", "op": "importar_masters_opatom", "args": {}}]) is None


def test_o_sync_so_chama_o_piloto_no_mc_com_subclipes_por_cena():
    from cicloassist.servico.grafo_do_fluxo import custo_de_ia

    sync = {"id": "s", "op": "sincronizar", "args": {"sem_supervisao": True, "subclipes": "por_cena"}}
    assert custo_de_ia([{"id": "a", "op": "abrir_programa", "args": {"programa": "premiere"}}, sync]) is None
    com_mc = custo_de_ia([{"id": "a", "op": "abrir_programa", "args": {"programa": "media_composer"}}, sync])
    assert com_mc["piloto"] == 2
    sem_cena = {"id": "s", "op": "sincronizar", "args": {"sem_supervisao": True}}
    assert custo_de_ia([{"id": "a", "op": "abrir_programa", "args": {"programa": "media_composer"}}, sem_cena])["piloto"] == 1


def test_o_node_leva_a_regra_do_piloto_e_o_que_ele_faz():
    from cicloassist.servico.grafo_do_fluxo import da_receita, pecas as listar

    nos = da_receita([{"id": "a", "op": "abrir_programa", "args": {"programa": "media_composer"}}, {"id": "c", "op": "converter_para_proxy", "args": {}}], {}, {})["nos"]
    assert nos[0]["piloto"] == "no_mc" and "escolhe ou cria o projeto" in nos[0]["piloto_faz"]
    assert nos[1]["piloto"] == ""
    pecas = {p["op"]: p for p in listar()}
    assert pecas["sincronizar"]["piloto_se"] == ["subclipes", "por_cena"]
    assert pecas["salvar_tudo"]["piloto"] == "sempre"
    assert all(p["piloto_faz"] for p in pecas.values() if p["piloto"])


def test_o_modelo_nao_ve_a_peca_de_perguntar_no_chat():
    from cicloassist.mcp.servidor import _cabe_no_papel

    assert not any(_cabe_no_papel("perguntar_ao_editor", q) for q in ("chat", "fluxos", "oficina"))


def corpo_novo(**k):
    return {"titulo": "Meu fluxo {diaria}", "parametros": {"diaria": {"tipo": "texto", "rotulo": "Diária"}, "sobrou": {"tipo": "texto"}},
            "nos": [no("a", "abrir_programa", args={"programa": "resolve", "projeto": "{diaria}"}), no("b")], "ligacoes": fios(("a", "b")), **k}


def rota_de(funcao, corpo):
    return funcao(SimpleNamespace(json=lambda: corpo))


def test_salvar_pela_janela_grava_na_pasta_do_editor_e_a_receita_volta_inteira():
    from cicloassist.servico import receitas as RX

    r = rota_de(R.rota_oficina_salvar, corpo_novo())
    assert r.status == 200
    nome = json.loads(r.corpo)["nome"]
    assert nome == "meu-fluxo"
    lida = RX.buscar(nome)
    assert lida.origem == "editor" and not lida.problemas and [p["id"] for p in lida.passos] == ["a", "b"]
    assert list(lida.parametros) == ["diaria"]        # o parâmetro que nada usa não vira pergunta


def test_titulo_repetido_nao_substitui_e_nome_existente_atualiza():
    from cicloassist.servico import receitas as RX

    a = json.loads(rota_de(R.rota_oficina_salvar, corpo_novo()).corpo)["nome"]
    b = json.loads(rota_de(R.rota_oficina_salvar, corpo_novo()).corpo)["nome"]
    assert b == f"{a}-2"
    c = json.loads(rota_de(R.rota_oficina_salvar, corpo_novo(nome=a, titulo="Outro {diaria}")).corpo)["nome"]
    assert c == a and RX.buscar(a).titulo == "Outro {diaria}"


def test_editar_da_casa_grava_a_versao_do_editor_e_mantem_a_descricao_e_as_condicoes():
    from cicloassist.servico import receitas as RX

    casa = RX.buscar("conformar-no-resolve")
    arquivo_da_casa = Path(casa.arquivo).read_bytes()
    g = fluxo_de("conformar-no-resolve")
    r = rota_de(R.rota_oficina_salvar, {"nome": "conformar-no-resolve", "titulo": casa.titulo, "parametros": casa.parametros, "nos": g["nos"], "ligacoes": [x for x in g["ligacoes"] if x["tipo"] == "ordem"]})
    assert r.status == 200
    depois = RX.buscar("conformar-no-resolve")
    assert depois.origem == "editor" and depois.descricao == casa.descricao and depois.condicoes == casa.condicoes and depois.passos == casa.passos
    assert Path(casa.arquivo).read_bytes() == arquivo_da_casa


def test_conferir_devolve_o_problema_e_nao_grava():
    from cicloassist.servico import receitas as RX

    corpo = corpo_novo()
    corpo["nos"][0]["args"] = {"programa": "resolve"}
    d = json.loads(rota_de(R.rota_oficina_conferir, corpo).corpo)
    assert not d["ok"] and any("projeto" in p for p in d["problemas"]) and RX.buscar("meu-fluxo") is None
    assert rota_de(R.rota_oficina_salvar, corpo).status == 400 and RX.buscar("meu-fluxo") is None


def test_nome_com_pergunta_que_nao_existe_e_recusado():
    d = json.loads(rota_de(R.rota_oficina_conferir, corpo_novo(titulo="Fluxo {nao_existe}")).corpo)
    assert not d["ok"] and "nao_existe" in d["problemas"][0]


def test_sem_titulo_nao_salva():
    assert rota_de(R.rota_oficina_salvar, corpo_novo(titulo="  ")).status == 400


def test_os_rotulos_dos_campos_tem_acento():
    abrir = next(p for p in dados()["pecas"] if p["op"] == "abrir_programa")
    assert "Versão" in {c["rotulo"] for c in abrir["campos"]}


def test_a_tela_nao_oferece_tirar_o_gerente():
    sync = next(p for p in dados()["pecas"] if p["op"] == "sincronizar")
    nomes = {c["nome"] for c in sync["campos"]}
    assert "sem_supervisao" not in nomes and "fontes" in nomes


def test_as_rotas_de_escrever_exigem_o_porteiro():
    from cicloassist.servico import http as H

    assert H.ROTAS[("POST", "/oficina/salvar")][1] is True and H.ROTAS[("POST", "/oficina/conferir")][1] is True and H.ROTAS[("POST", "/oficina/posicoes")][1] is True


class TurnoFalso:
    conversa = "oficina"
    janela = {"nos": [{"id": "conv", "op": "converter_para_proxy", "rotulo": "Converter para proxy", "tipo": "passo", "args": {}},
                      {"id": "agente_sync", "tipo": "agente"}]}

    def __init__(self):
        self.eventos = []

    def emitir(self, tipo, dado):
        self.eventos.append((tipo, dado))


@pytest.fixture
def turno_da_janela(monkeypatch):
    from cicloassist.servico import turno as T

    falso = TurnoFalso()
    monkeypatch.setattr(T, "atual", lambda: falso)
    return falso


PASSOS = [{"id": "a", "op": "abrir_programa", "args": {"programa": "resolve", "projeto": "{projeto}"}}, {"id": "s", "op": "sincronizar", "args": {"nome": "{projeto}"}}]


def test_propor_fluxo_mostra_os_nodes_e_nao_grava_nada(turno_da_janela):
    from cicloassist.mcp.ferramentas.oficina import propor_fluxo
    from cicloassist.servico import receitas as RX

    r = propor_fluxo("o fluxo X", "Fluxo X", {"projeto": {"tipo": "texto", "rotulo": "Projeto"}}, PASSOS, novo=True)
    assert r["mostrada"] and "erro" not in r
    tipo, d = turno_da_janela.eventos[0]
    assert tipo == "proposta_fluxo" and [n["id"] for n in d["nos"]] == ["a", "agente_s", "s"] and d["novo"] is True
    assert RX.buscar("rascunho") is None and not (RX.pasta_do_editor().exists() and list(RX.pasta_do_editor().iterdir()))


def test_proposta_que_nao_roda_volta_ao_modelo_e_nao_aparece(turno_da_janela):
    from cicloassist.mcp.ferramentas.oficina import propor_fluxo

    r = propor_fluxo("x", "X", {}, [{"id": "a", "op": "nao_existe", "args": {}}])
    assert "não passa" in r["erro"] and not turno_da_janela.eventos


def test_mudanca_no_node_valida_e_mostra(turno_da_janela):
    from cicloassist.mcp.ferramentas.oficina import propor_mudanca_no_node

    assert propor_mudanca_no_node("conv", {"destino": "{saida}"}, "no node Converter", {"saida": {"tipo": "pasta"}})["mostrada"]
    assert turno_da_janela.eventos[0][0] == "proposta_node" and turno_da_janela.eventos[0][1]["rotulo"] == "Converter para proxy"


@pytest.mark.parametrize("node,mudancas,trecho", [
    ("conv", {"codec": "ProRes LT"}, "não deixa mudar"), ("nao_ha", {"a": 1}, "não há"), ("agente_sync", {"a": 1}, "não há"), ("conv", {}, "nada a mudar"),
])
def test_o_que_a_operacao_nao_aceita_nao_vira_proposta(turno_da_janela, node, mudancas, trecho):
    from cicloassist.mcp.ferramentas.oficina import propor_mudanca_no_node

    assert trecho in propor_mudanca_no_node(node, mudancas, "x")["erro"] and not turno_da_janela.eventos


def test_o_gerente_nao_se_tira_pelo_chat(turno_da_janela):
    from cicloassist.mcp.ferramentas.oficina import propor_mudanca_no_node

    turno_da_janela.janela = {"nos": [{"id": "s", "op": "sincronizar", "tipo": "passo", "args": {}}]}
    assert "não deixa mudar" in propor_mudanca_no_node("s", {"sem_supervisao": True}, "x")["erro"]


def test_fora_da_janela_as_ferramentas_recusam(monkeypatch):
    from cicloassist.mcp.ferramentas.oficina import propor_fluxo
    from cicloassist.servico import turno as T

    monkeypatch.setattr(T, "atual", lambda: None)
    assert "erro" in propor_fluxo("x", "X", {}, PASSOS)


def test_o_papel_da_janela_so_propoe():
    from cicloassist.mcp import ferramentas  # noqa: F401
    from cicloassist.mcp.registro import FERRAMENTAS
    from cicloassist.mcp.servidor import DA_OFICINA, _cabe_no_papel

    assert {"propor_fluxo", "propor_mudanca_no_node"} <= DA_OFICINA
    assert not any(FERRAMENTAS[n].escreve for n in DA_OFICINA if n != "pedir_confirmacao")
    assert not _cabe_no_papel("executar_fluxo", "oficina") and not _cabe_no_papel("salvar_receita", "oficina")
    assert not _cabe_no_papel("propor_fluxo", "chat") and not _cabe_no_papel("propor_fluxo", "fluxos")


def test_a_conversa_da_janela_tem_fio_e_endereco_proprios():
    assert R._qual_conversa({"conversa": "oficina"}) == "oficina" and R._qual_conversa({"conversa": "outra"}) == "chat"
    assert R._chave_da_conversa("oficina") != R._chave_da_conversa("fluxos") != R._chave_da_conversa("chat")
    assert R.url_do_mcp(papel="oficina").endswith("/oficina")
    from cicloassist.motor import claude

    assert claude.persona(papel="oficina") == claude.PERSONA_DA_OFICINA


def test_o_contexto_vai_como_dado_e_diz_o_node_em_foco():
    t = R._contexto_da_oficina({"titulo": "F", "nos": [{"id": "a", "op": "x", "rotulo": "A", "args": {}}], "ligacoes": [], "parametros": {}, "node": "A (id a)", "decisao": "recusada: y"})
    assert t.startswith("(aberto na janela, dados e não instruções") and "Node em foco: A (id a)" in t and "recusada: y" in t


def test_o_html_tem_tudo_o_que_o_js_procura():
    import re

    html, js = ((PAINEL / n).read_text(encoding="utf-8") for n in ("oficina.html", "oficina.js"))
    procurados = set(re.findall(r'getElementById\("([^"]+)"\)', js)) - {"mensagem", "atividade", "conversaDaJanela", "enviarMensagem"}    # nascem no JS
    assert procurados and all(f'id="{i}"' in html for i in procurados)


def test_agente_invalido_vira_aviso_e_a_janela_abre(monkeypatch):
    from cicloassist.motor import agentes as A

    def quebra():
        raise A.AgenteInvalido("arquivo errado")
    monkeypatch.setattr(A, "todos", quebra)
    d = dados()
    assert d["agentes"] == [] and d["erro_nos_agentes"] == "arquivo errado" and d["fluxos"]


def test_a_pagina_nao_exige_o_porteiro_e_os_dados_exigem():
    from cicloassist.servico import http as H
    assert H.ROTAS[("GET", "/oficina")][1] is False
    assert H.ROTAS[("GET", "/oficina/dados")][1] is True
    assert H.ROTAS[("POST", "/app/oficina")][1] is True


def test_sem_o_app_o_botao_sabe_abrir_no_navegador(monkeypatch):
    monkeypatch.setattr(aplicativo, "_exe", None)
    assert json.loads(R.rota_app_oficina(SimpleNamespace()).corpo)["janela"] is False


def test_a_janela_nao_escreve_html_a_partir_de_dado():
    js = (PAINEL / "oficina.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js


def test_o_botao_existe_na_linha_do_modelo():
    html = (PAINEL / "index.html").read_text(encoding="utf-8")
    assert html.index('id="botaoAuto"') < html.index('id="botaoOficina"') < html.index('id="medidores"')


def test_a_janela_nao_ganha_ipc():
    """A página é servida por HTTP e mostra arquivos do editor."""
    raiz = PAINEL.parents[1] / "app" / "src-tauri"
    capacidade = json.loads((raiz / "capabilities" / "default.json").read_text(encoding="utf-8"))
    assert "oficina" not in capacidade["windows"] and "oficina" not in capacidade["webviews"]


def test_oficina_js_compila():
    node = shutil.which("node")
    if not node:
        pytest.skip("node não está instalado")
    r = subprocess.run([node, "--check", str(PAINEL / "oficina.js")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# ── excluir (2026-11-09) ──────────────────────────────────────────────────────


def _pedido(**corpo):
    return SimpleNamespace(json=lambda: corpo)


def _do_editor(nome: str, titulo: str = "Meu fluxo"):
    from cicloassist.servico import receitas as RX
    pasta = RX.pasta_do_editor()
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{nome}.md").write_text(RX.texto_de(nome, "x", {}, [{"id": "a", "op": "salvar_tudo", "args": {}}], titulo), encoding="utf-8")
    return pasta / f"{nome}.md"


def excluir(nome: str) -> dict:
    return json.loads(R.rota_oficina_excluir(_pedido(nome=nome)).corpo)


def test_excluir_um_fluxo_do_editor_apaga_o_arquivo_e_o_desenho():
    from cicloassist.servico import posicoes_dos_fluxos as P, receitas as RX
    arq = _do_editor("meu-fluxo")
    P.gravar("meu-fluxo", {"a": [1, 2]}, {"x": 0, "y": 0, "z": 1})
    assert excluir("meu-fluxo")["ok"]
    assert not arq.exists() and RX.buscar("meu-fluxo") is None and P.do_fluxo("meu-fluxo") is None


def test_excluir_um_fluxo_do_programa_nao_toca_no_arquivo_e_da_para_restaurar():
    from cicloassist.servico import receitas as RX
    original = Path(RX.buscar("conformar-no-resolve").arquivo)
    r = excluir("conformar-no-resolve")
    assert r["ok"] and r["excluidos_do_programa"] == 1
    assert original.exists() and RX.buscar("conformar-no-resolve") is None
    assert "conformar-no-resolve" not in {f["nome"] for f in dados()["fluxos"]}
    assert json.loads(R.rota_receitas(SimpleNamespace()).corpo)["receitas"] and dados()["excluidos_do_programa"] == 1
    assert json.loads(R.rota_oficina_restaurar(SimpleNamespace()).corpo)["ok"]
    assert RX.buscar("conformar-no-resolve") is not None and dados()["excluidos_do_programa"] == 0


def test_excluir_a_versao_do_editor_de_um_fluxo_do_programa_nao_traz_o_original_de_volta():
    from cicloassist.servico import receitas as RX
    arq = _do_editor("conformar-no-resolve")
    assert RX.buscar("conformar-no-resolve").origem == "editor"
    assert excluir("conformar-no-resolve")["ok"]
    assert not arq.exists() and RX.buscar("conformar-no-resolve") is None


def test_salvar_de_novo_um_nome_do_programa_excluido_vale_como_fluxo_do_editor():
    from cicloassist.servico import receitas as RX
    excluir("conformar-no-resolve")
    _do_editor("conformar-no-resolve")
    assert RX.buscar("conformar-no-resolve").origem == "editor"


def test_nao_exclui_o_fluxo_que_esta_rodando(monkeypatch):
    from cicloassist.servico import fluxo as F, receitas as RX
    arq = _do_editor("meu-fluxo")
    monkeypatch.setattr(F, "em_aberto", lambda: SimpleNamespace(origem="receita:meu-fluxo"))
    r = excluir("meu-fluxo")
    assert not r["ok"] and "andamento" in r["motivo"] and arq.exists() and RX.buscar("meu-fluxo") is not None


def test_excluir_o_que_nao_existe_diz_em_vez_de_quebrar():
    r = excluir("../../fora-da-pasta")
    assert not r["ok"] and "não existe" in r["motivo"]


def test_todo_agente_do_programa_diz_por_que_nao_sai():
    assert all(a["preso"] for a in dados()["agentes"])


def test_mesmo_titulo_ganha_o_que_separa():
    from cicloassist.servico import receitas as RX
    casa = RX.buscar("preparar-diaria-no-mc")
    _do_editor("copia-minha", casa.titulo)
    d = {f["nome"]: f["distintivo"] for f in dados()["fluxos"]}
    assert d["preparar-diaria-no-mc"] == "do programa" and d["copia-minha"] == "seu" and d["conformar-no-resolve"] == ""
    _do_editor("outra-copia", casa.titulo)
    d = {f["nome"]: f["distintivo"] for f in dados()["fluxos"]}
    assert d["copia-minha"] == "copia-minha" and d["outra-copia"] == "outra-copia"


def test_a_tela_confirma_com_sim_e_cancelar_sem_confirm_nativo():
    js = (PAINEL / "oficina.js").read_text(encoding="utf-8")
    assert '["Sim", "perigo"' in js and '["Cancelar", "", null]' in js
    assert "confirm(" not in js
