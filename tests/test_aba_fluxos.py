"""A conversa da aba FLUXOS (F3, autor 2026-11-03, `docs/plano/2026-11-03-chat-e-fluxos.md`).

O chat é o pedido imediato, feito ferramenta a ferramenta; a aba Fluxos é o planejador — escolhe ou
monta a receita, o editor aprova um cartão, o executor roda no fundo. Um motor, duas conversas: cada uma
com a sua persona, as suas ferramentas e os seus recados.
"""

from __future__ import annotations

import pytest

from cicloassist.mcp import servidor
from cicloassist.motor import claude
from cicloassist.servico import pendencias as _pend
from cicloassist.servico import receitas
from cicloassist.servico import rotas as R


@pytest.fixture(autouse=True)
def claude_na_config(monkeypatch):
    from cicloassist.servico import config
    monkeypatch.setattr(config, "modelo_guardado", lambda: "claude-sonnet-5-5")


def _nomes(papel):
    return {f.nome for f in servidor.visiveis(papel)}


def test_cada_conversa_ve_as_suas_ferramentas():
    chat, fluxos = _nomes("chat"), _nomes("fluxos")
    assert {"executar_fluxo", "continuar_fluxo", "salvar_receita", "listar_receitas"} <= fluxos
    assert fluxos <= servidor.DOS_FLUXOS
    # ⛔ Nenhuma escrita solta na aba Fluxos: quem executa é o executor, pelo plano aprovado.
    assert not (fluxos & {"abrir_programa", "converter_para_opatom", "montar_corte", "separar_falas"})
    assert not (chat & {"executar_fluxo", "continuar_fluxo", "gerar_midia_de_teste"})
    assert {"abrir_programa", "separar_falas", "listar_receitas"} <= chat


def test_o_endereco_diz_o_papel_e_a_chamada_fora_do_papel_e_recusada():
    assert R.url_do_mcp(papel="fluxos").endswith(R.ROTA_DO_MCP_DOS_FLUXOS)
    assert R.url_do_mcp().endswith(R.ROTA_DO_MCP)
    assert any(c == R.ROTA_DO_MCP_DOS_FLUXOS for (_, c) in R.ROTAS)
    chamada = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "abrir_programa", "arguments": {}}}
    with servidor.com_papel("fluxos"):
        r = servidor.responder(chamada)
        lista = servidor.responder({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert r["result"]["isError"] and "aba Assistir" in r["result"]["content"][0]["text"]
    assert {t["name"] for t in lista["result"]["tools"]} == _nomes("fluxos")
    assert servidor.papel() == "chat"            # o papel não vaza para o pedido seguinte


def test_a_persona_de_cada_conversa():
    assert claude.persona("avid", "fluxos") is claude.PERSONA_DOS_FLUXOS
    assert claude.persona("premiere", "fluxos") is claude.PERSONA_DOS_FLUXOS
    assert claude.persona("avid") is claude.PERSONA
    assert "listar_receitas" in claude.PERSONA_DOS_FLUXOS and "salvar_receita" in claude.PERSONA_DOS_FLUXOS
    assert "botão Salvar" in claude.PERSONA_DOS_FLUXOS


def test_o_recado_volta_so_para_a_conversa_de_origem():
    _pend.esquecer_tudo()
    a = _pend.abrir("executar_fluxo", "rodar o fluxo X", {"plano": {"nome": "X"}}, conversa="fluxos")
    b = _pend.abrir("montar_corte", "montar este corte", {"c": 1}, conversa="chat")
    a.recado, b.recado = "fluxo X feito", "corte feito"
    assert _pend.recados("chat") == ["corte feito"]
    assert _pend.recados("fluxos") == ["fluxo X feito"]
    a.recado = "de novo"
    assert _pend.descartar_recados("chat") == 0 and _pend.descartar_recados("fluxos") == 1
    _pend.esquecer_tudo()


def test_o_botao_da_receita_abre_a_pendencia_na_conversa_de_fluxos():
    texto = open(R.__file__, encoding="utf-8").read()
    assert '{"plano": plano, "receita_de": r.nome}, conversa="fluxos")' in texto


RECEITA = dict(
    nome="diaria-teste",
    titulo="Diária {diaria}",
    descricao="Converte e leva ao MC.",
    parametros={"pasta": {"tipo": "pasta", "rotulo": "A pasta"}, "diaria": {"tipo": "texto", "padrao": "D01"}},
    passos=[{"id": "conv", "op": "converter_para_opatom", "args": {"projeto": "{diaria} DR", "pasta": "{pasta}"}},
            {"id": "salvar", "op": "salvar_tudo", "args": {}}],
    condicoes="- A pasta já é OP-Atom: pule conv.",
)


def test_receita_que_nao_passa_e_barrada_antes_do_cartao():
    from cicloassist.mcp import registro
    f = registro.FERRAMENTAS["salvar_receita"]
    assert f.escreve and f.conferir is not None
    assert f.conferir(**RECEITA) == ""
    ruim = {**RECEITA, "passos": [{"id": "x", "op": "nao_existe", "args": {}}]}
    assert "não passa" in f.conferir(**ruim)
    assert "name inválido" in f.conferir(**{**RECEITA, "nome": "Com Espaço"})


def test_a_receita_salva_aparece_na_lista_como_do_editor():
    from cicloassist.mcp import registro
    saida = registro.FERRAMENTAS["salvar_receita"].funcao(**RECEITA)
    assert "erro" not in saida, saida
    r = receitas.todas()["diaria-teste"]
    assert r.origem == "editor" and not r.problemas
    assert r.passos[0]["args"]["projeto"] == "{diaria} DR"     # parâmetro, não o valor de hoje
    assert "OP-Atom" in r.condicoes
    plano = r.plano({"pasta": "C:/x", "diaria": "D02"})       # o executor substitui na hora de rodar
    assert plano["parametros"]["diaria"] == "D02" and plano["parametros"]["pasta"] == "C:/x"
    assert str(receitas.pasta_do_editor()) in r.arquivo          # a da casa nunca se escreve


def test_a_conferencia_pega_o_valor_que_falharia_ao_rodar():
    """⛔⛔ A prova da F3 (2026-11-03): estes dois erros chegaram ao cartão e falhariam no passo 4."""
    from cicloassist.servico import fluxo
    plano = {"parametros": {"projeto_mc": "X"}, "passos": [
        {"id": "abrir_mc", "op": "abrir_programa", "args": {"programa": "media composer", "projeto": "{projeto_mc}"}},
        {"id": "sync", "op": "sincronizar", "args": {"bins": "{abrir_mc.bin},{abrir_mc.bin}"}},
    ]}
    problemas = " | ".join(fluxo.validar(plano))
    assert "'media composer' não existe" in problemas and "media_composer" in problemas
    assert "tem de ser uma LISTA" in problemas
    # O que só se conhece ao rodar continua passando: marcador sozinho, e lista de marcadores.
    bom = {"parametros": {"projeto_mc": "X", "bins": ["A", "B"]}, "passos": [
        {"id": "abrir_mc", "op": "abrir_programa", "args": {"programa": "media_composer", "projeto": "{projeto_mc}"}},
        {"id": "sync", "op": "sincronizar", "args": {"bins": "{bins}"}},
        {"id": "sync2", "op": "sincronizar", "args": {"bins": ["{abrir_mc.bin}"]}},
    ]}
    assert fluxo.validar(bom) == []


def test_as_receitas_da_casa_continuam_passando():
    assert all(not r.problemas for r in receitas.todas().values())


# ── o botão "Salvar" do cartão do plano (autor, 2026-11-04) ──

#: O plano que a prova da F3 de 04/11 levou ao cartão (Sonnet, o prompt da D01), com a pasta trocada.
def _plano_da_prova(pasta):
    return {"nome": "Preparar a diária D01 no Media Composer",
            "parametros": {"pasta": str(pasta), "projeto_resolve": "TESTE SIMULADO DR",
                           "projeto_mc": "TESTE SIMULADO MC", "bin_camera": "CAMERA D01",
                           "bin_som": "SOM D01", "bin_subclipes": "subclipes", "diaria": "D01"},
            "passos": [
                {"id": "conv", "op": "converter_para_opatom", "args": {"pasta": "{pasta}", "projeto": "{projeto_resolve}"}},
                {"id": "abrir_mc", "op": "abrir_programa",
                 "args": {"programa": "media_composer", "projeto": "{projeto_mc}", "formato": "{conv.formato}"}},
                {"id": "camera", "op": "importar_masters_opatom", "args": {"pasta": "{conv.pasta}", "bin": "{bin_camera}"}},
                {"id": "som", "op": "som_direto_gerenciado", "args": {"pasta": "{pasta}", "bin": "{bin_som}"}},
                {"id": "sync", "op": "sincronizar",
                 "args": {"bins": ["{camera.bin}", "{som.bin}"], "nome": "{diaria}", "subclipes": "uma_bin",
                          "bin_dos_subclipes": "{bin_subclipes}"}},
                {"id": "salvar", "op": "salvar_tudo", "args": {}}]}


def test_o_plano_do_cartao_vira_receita_sem_o_valor_de_hoje_nos_caminhos(tmp_path):
    texto = receitas.do_plano(_plano_da_prova(tmp_path), "04/11/2026")
    r = receitas.conferir_texto(texto)
    assert r.titulo == "Preparar a diária {diaria} no Media Composer"
    assert r.parametros["pasta"] == {"tipo": "pasta", "rotulo": "A pasta da diária (vídeos e WAV)"}
    assert r.parametros["diaria"]["padrao"] == "D01" and r.parametros["projeto_mc"]["tipo"] == "texto"
    assert r.passos[0]["args"]["pasta"] == "{pasta}"
    # ⭐ A bin que contém o nome da diária SEGUE a diária (o campo sai; o passo diz "CAMERA {diaria}").
    assert "bin_camera" not in r.parametros and "bin_som" not in r.parametros
    assert r.passos[2]["args"]["bin"] == "CAMERA {diaria}" and r.passos[3]["args"]["bin"] == "SOM {diaria}"
    assert r.parametros["bin_subclipes"]["padrao"] == "subclipes"   # não contém outro valor: fica
    assert "04/11/2026" in r.descricao
    assert r.nome == "preparar-a-diaria-no-media-composer"      # sem o "d01" de hoje no nome
    plano = r.plano({"pasta": str(tmp_path), "diaria": "D02"})
    assert plano["nome"] == "Preparar a diária D02 no Media Composer"


def test_o_derivado_de_caminho_nao_vira_campo(tmp_path):
    p = _plano_da_prova(tmp_path)
    p["parametros"]["pasta_nome"] = tmp_path.name
    assert "pasta_nome" not in receitas.conferir_texto(receitas.do_plano(p)).parametros


def test_salvar_nunca_substitui_uma_receita_existente(tmp_path):
    p = _plano_da_prova(tmp_path)
    p["nome"] = "Preparar diária no MC"          # vira o slug da receita da casa
    p["parametros"].pop("diaria")
    texto = receitas.do_plano(p)
    assert "name: preparar-diaria-no-mc-2" in texto


def test_a_rota_guarda_o_plano_da_pendencia(tmp_path):
    import json
    from cicloassist.servico.http import Pedido
    _pend.esquecer_tudo()
    p = _pend.abrir("executar_fluxo", "x", {"plano": _plano_da_prova(tmp_path)}, conversa="fluxos")
    fn = R.rota_receitas_salvar_plano
    r = json.loads(fn(Pedido("POST", "/receitas/salvar-plano", {"sec-fetch-site": "same-origin"},
                             json.dumps({"id": p.id}).encode())).corpo)
    assert r["ok"] and r["titulo"] == "Preparar a diária ‹diaria› no Media Composer"
    assert receitas.todas()[r["receita"]].origem == "editor"
    assert _pend.buscar(p.id).aberta                     # salvar NÃO decide o cartão
    ruim = json.loads(fn(Pedido("POST", "/receitas/salvar-plano", {"sec-fetch-site": "same-origin"},
                                json.dumps({"id": "nao-existe"}).encode())).corpo)
    assert not ruim["ok"]
    _pend.esquecer_tudo()


def test_o_cartao_so_mostra_salvar_em_plano_feito_a_mao():
    import pathlib
    js = (pathlib.Path(R.__file__).parent.parent / "painel" / "painel.js").read_text(encoding="utf-8")
    assert "entrada.plano && !entrada.receita_de" in js and '"/receitas/salvar-plano"' in js


def test_listar_receitas_diz_como_chamar_cada_operacao():
    """⭐⭐ Prova da F3 (04/11): sem os argumentos, o 1º plano inventou `criar` e `diaria`."""
    from cicloassist.mcp import registro
    saida = registro.FERRAMENTAS["listar_receitas"].funcao()
    ops = saida["operacoes"]
    assert ops["abrir_programa"].startswith("programa* (resolve|premiere|media_composer)")
    assert "projeto*" in ops["abrir_programa"] and "formato" in ops["abrir_programa"]
    assert "bins [lista]" in ops["sincronizar"]
    assert "subclipes (nao|uma_bin|por_cena)" in ops["sincronizar"]
    assert ops["salvar_tudo"] == "(sem argumentos)"
    assert "executar_fluxo" not in ops
    casa = next(r for r in saida["receitas"] if r["nome"] == "preparar-diaria-no-mc")
    assert casa["passos"][0]["args"] == {"programa": "resolve", "projeto": "{diaria}"}   # passos INTEIROS
    assert len(str(ops)) < 1500                                                           # e curto


def test_executar_por_receita_chega_ao_cartao_como_o_plano_inteiro(tmp_path):
    """⭐ Prova de 04/11: o modelo usou a receita salva (bom!) e o cartão mostrou os parâmetros em JSON cru."""
    from cicloassist.mcp.ferramentas import portao
    pedido = {"receita": "preparar-diaria-no-mc",
              "parametros": {"pasta": str(tmp_path), "diaria": "D09", "projeto": "X", "formato": "1080p/25",
                             "subclipes": "por_cena"}}
    e = portao._plano_da_receita("executar_fluxo", pedido)
    assert e["receita_de"] == "preparar-diaria-no-mc"
    assert e["plano"]["nome"] == "Preparar a diária D09 no Media Composer"
    assert len(e["plano"]["passos"]) == 8
    # o que não é receita, ou não monta, fica como veio
    assert portao._plano_da_receita("montar_corte", pedido) is pedido
    ruim = {"receita": "nao-existe", "parametros": {}}
    assert portao._plano_da_receita("executar_fluxo", ruim) is ruim


def test_a_aba_fluxos_saiu_e_o_menu_carrega_na_conversa():
    """N5, 2026-11-08: um leigo roda um fluxo pelo menu, e responde na própria conversa."""
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1] / "cicloassist" / "painel"
    fluxo = " ".join((raiz / "fluxo.js").read_text(encoding="utf-8").split())
    painel = " ".join((raiz / "painel.js").read_text(encoding="utf-8").split())
    html = (raiz / "index.html").read_text(encoding="utf-8")
    assert 'data-tela="fluxos"' not in html and 'id="abaFluxos"' not in html
    assert 'id="menuFluxos"' in html and "window.carregarReceita(r)" in painel
    assert 'abaVista === "conversa" && !!window.carregarReceita' in painel
    assert 'postar("/oficina/executar"' in fluxo and "formularioDeConfirmacao" in fluxo and "/fluxo/confirmar" in fluxo
