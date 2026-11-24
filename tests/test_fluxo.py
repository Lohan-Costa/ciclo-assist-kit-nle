"""O executor de fluxos (F1): o plano é dado, a execução é nossa, e parar/retomar não refaz nada."""

from __future__ import annotations

import dataclasses
import json
import sys
from types import SimpleNamespace

import pytest

from cicloassist.mcp import ferramentas as _todas  # noqa: F401 — registra as reais
from cicloassist.mcp.registro import FERRAMENTAS, Ferramenta
from cicloassist.servico import fluxo, pendencias, tarefas


@pytest.fixture(autouse=True)
def limpo():
    fluxo.esquecer()
    tarefas.esquecer()
    yield
    _esperar()
    fluxo.esquecer()
    tarefas.esquecer()


def _esperar():
    t = tarefas._thread
    if t is not None:
        t.join(10)


@pytest.fixture
def ops(monkeypatch):
    """Três operações de mentira, que contam quantas vezes rodaram."""
    chamadas: list[tuple[str, dict]] = []
    comportamento: dict[str, object] = {}

    def fazer(nome):
        def fn(**args):
            chamadas.append((nome, args))
            acao = comportamento.get(nome)
            if callable(acao):
                return acao(**args)
            if isinstance(acao, dict):
                return acao
            return {"pasta": f"/saida/{nome}", "ok": True}
        return fn

    def conf_b(pasta="", **_):
        return "" if pasta else "falta a pasta"

    for nome, conf in (("op_a", None), ("op_b", conf_b), ("op_c", None)):
        monkeypatch.setitem(FERRAMENTAS, nome, Ferramenta(
            nome=nome, descricao="", escreve=True, funcao=fazer(nome), conferir=conf,
            esquema={"type": "object", "properties": {"pasta": {}, "bin": {}, "lista": {}},
                     "required": ["pasta"] if nome == "op_b" else []}))
    return chamadas, comportamento


def _plano(**extra):
    p = {"nome": "teste {d}", "parametros": {"d": "D01", "p": "/m"},
         "passos": [{"id": "a", "op": "op_a", "args": {"pasta": "{p}"}},
                    {"id": "b", "op": "op_b", "args": {"pasta": "{a.pasta}", "bin": "{d} CAMERA"}},
                    {"id": "c", "op": "op_c", "args": {"lista": ["{d} CAMERA", "{d} SOM"]}}]}
    p.update(extra)
    return p


# ── a estrutura ──────────────────────────────────────────────────────────────


def test_plano_bom_passa(ops):
    assert fluxo.validar(_plano()) == []


@pytest.mark.parametrize("passos, trecho", [
    ([{"id": "a", "op": "nao_existe", "args": {}}], "não existe a operação"),
    ([{"id": "a", "op": "executar_fluxo", "args": {}}], "não pode ser passo"),
    ([{"id": "a", "op": "op_b", "args": {"pasta": "{b.pasta}"}},
      {"id": "b", "op": "op_a", "args": {}}], "não vem ANTES"),
    ([{"id": "a", "op": "op_a", "args": {"pasta": "{inventado}"}}], "não é um parâmetro"),
    ([{"id": "a", "op": "op_b", "args": {}}], "falta 'pasta'"),
    ([{"id": "a", "op": "op_a", "args": {"comando": "rm"}}], "não aceita 'comando'"),
    ([{"id": "a", "op": "op_a"}, {"id": "a", "op": "op_a"}], "id repetido"),
    ([{"id": "A B", "op": "op_a"}], "'id' tem de ser"),
])
def test_plano_ruim_diz_o_que_consertar(ops, passos, trecho):
    problemas = fluxo.validar({"parametros": {"d": "x"}, "passos": passos})
    assert any(trecho in p for p in problemas), problemas


def test_referencia_sozinha_mantem_o_tipo():
    saidas = {"a": {"bins": ["X", "Y"], "n": 3}}
    assert fluxo.resolver("{a.bins}", {}, saidas) == ["X", "Y"]
    assert fluxo.resolver("{a.n} clipes de {d}", {"d": "D01"}, saidas) == "3 clipes de D01"
    with pytest.raises(fluxo.PlanoInvalido, match="não devolveu"):
        fluxo.resolver("{a.pasta}", {}, saidas)


# ── a execução ───────────────────────────────────────────────────────────────


def test_roda_inteiro_e_a_saida_de_um_passo_alimenta_o_seguinte(ops):
    chamadas, _ = ops
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    assert fluxo.ultimo().estado == "pronto"
    assert chamadas == [("op_a", {"pasta": "/m"}),
                        ("op_b", {"pasta": "/saida/op_a", "bin": "D01 CAMERA"}),
                        ("op_c", {"lista": ["D01 CAMERA", "D01 SOM"]})]
    assert f.nome == "teste {d}" or f.nome  # o título é dado do plano


def test_erro_da_operacao_para_o_fluxo_e_retomar_nao_refaz_o_feito(ops):
    chamadas, comportamento = ops
    comportamento["op_b"] = {"erro": "o Media Composer recusou"}
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    f = fluxo.ultimo()
    assert f.estado == "esperando"
    assert f.passos[1].estado == "falhou" and "recusou" in f.passos[1].motivo
    assert "esperando" in fluxo.recado() and "continuar_fluxo" in fluxo.recado()

    comportamento.pop("op_b")
    fluxo.iniciar(f.id)
    _esperar()
    assert fluxo.ultimo().estado == "pronto"
    assert [c[0] for c in chamadas] == ["op_a", "op_b", "op_b", "op_c"]


def test_conferencia_do_passo_roda_logo_antes_dele(ops):
    _, comportamento = ops
    comportamento["op_a"] = {"pasta": ""}            # o passo a não entrega a pasta
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    f = fluxo.ultimo()
    assert f.passos[1].estado == "falhou" and f.passos[1].motivo == "falta a pasta"


def test_problemas_viram_aviso_e_o_fluxo_segue(ops):
    _, comportamento = ops
    comportamento["op_a"] = {"pasta": "/x", "problemas": ["B002.mov ilegível"]}
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    r = fluxo.resumo(fluxo.ultimo())
    assert r["estado"] == "pronto" and r["avisos"] == ["a: B002.mov ilegível"]


def test_pausar_vale_entre_passos_e_retomar_segue_do_proximo(ops):
    chamadas, comportamento = ops

    def a_e_pausa(**_):
        fluxo.pedir("pausar")                       # o editor aperta Pausar durante o passo a
        return {"pasta": "/p"}
    comportamento["op_a"] = a_e_pausa
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    f = fluxo.ultimo()
    assert f.estado == "pausado" and f.passos[0].estado == "feito" and f.atual == 1

    fluxo.iniciar(f.id)
    _esperar()
    assert fluxo.ultimo().estado == "pronto"
    assert [c[0] for c in chamadas] == ["op_a", "op_b", "op_c"]


def test_cancelar_parado_e_imediato_e_libera_outro_fluxo(ops):
    _, comportamento = ops
    comportamento["op_a"] = {"erro": "x"}
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    with pytest.raises(fluxo.FluxoOcupado):
        fluxo.criar(_plano())
    fluxo.pedir("cancelar")
    assert fluxo.ultimo().estado == "cancelado"
    assert fluxo.criar(_plano()).estado == "pausado"


def test_pular_e_corrigir(ops):
    chamadas, comportamento = ops
    comportamento["op_b"] = lambda pasta="", bin="": {"erro": "bin errada"} if bin != "OK" else {"pasta": pasta}
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    fluxo.corrigir(f.id, {"bin": "OK"})
    fluxo.iniciar(f.id)
    _esperar()
    assert fluxo.ultimo().estado == "pronto"
    assert chamadas[-2] == ("op_b", {"pasta": "/saida/op_a", "bin": "OK"})


def test_estado_vai_ao_disco_e_o_reinicio_vira_interrompido(ops):
    f = fluxo.criar(_plano())
    d = json.loads(fluxo._arquivo(f.id).read_text(encoding="utf-8"))
    d["estado"] = "correndo"
    d["passos"][0]["estado"] = "feito"
    d["passos"][0]["saida"] = {"pasta": "/do/disco"}
    d["passos"][1]["estado"] = "correndo"
    fluxo._arquivo(f.id).write_text(json.dumps(d), encoding="utf-8")

    fluxo.esquecer()                                # o serviço reiniciou
    g = fluxo.em_aberto()
    assert g.estado == "interrompido" and g.atual == 1
    assert g.passos[1].estado == "a_fazer" and "reiniciou" in g.passos[1].motivo

    chamadas, _ = ops
    fluxo.iniciar(g.id)
    _esperar()
    assert fluxo.ultimo().estado == "pronto"
    assert chamadas[0] == ("op_b", {"pasta": "/do/disco", "bin": "D01 CAMERA"})


def test_o_relato_da_operacao_chega_ao_fluxo(ops):
    _, comportamento = ops
    vistos = []

    def a(**_):
        pendencias.relatar("renderizando", 0.5, "C001")
        vistos.append(dict(fluxo.ultimo().andamento))
        return {"pasta": "/p"}
    comportamento["op_a"] = a
    fluxo.iniciar(fluxo.criar(_plano()).id)
    _esperar()
    assert vistos[0]["etapa"] == "renderizando" and vistos[0]["fracao"] == 0.5


def test_dentro_do_fluxo_aprovado_o_programa_conta_como_nomeado(ops):
    from cicloassist.mcp.ferramentas import programas
    _, comportamento = ops
    visto = []
    comportamento["op_a"] = lambda **_: visto.append(programas.nomeado_pelo_editor("resolve")) or {"pasta": "/"}
    assert programas.nomeado_pelo_editor("resolve") is False
    fluxo.iniciar(fluxo.criar(_plano()).id)
    _esperar()
    assert visto == [True]


# ── as ferramentas do chat ───────────────────────────────────────────────────


def test_executar_fluxo_confere_o_primeiro_passo_e_a_estrutura(ops):
    from cicloassist.mcp.ferramentas import fluxo as ferr
    ruim = _plano()
    ruim["passos"][0] = {"id": "a", "op": "op_b", "args": {"pasta": ""}}
    assert "falta a pasta" in ferr._conferir(plano=ruim)
    assert "não existe" in ferr._conferir(plano={"passos": [{"id": "a", "op": "x"}]})
    assert ferr._conferir(plano=_plano()) == ""


def test_continuar_fluxo_com_args_corrigidos(ops):
    from cicloassist.mcp.ferramentas import fluxo as ferr
    _, comportamento = ops
    comportamento["op_b"] = lambda pasta="", bin="": {"erro": "x"} if bin != "OK" else {}
    ferr.executar_fluxo(plano=_plano())
    _esperar()
    assert "não aceita" in ferr._conferir_continuar(acao="tentar_de_novo", args={"zzz": 1})
    assert ferr._conferir_continuar(acao="tentar_de_novo", args={"bin": "OK"}) == ""
    ferr.continuar_fluxo(acao="tentar_de_novo", args={"bin": "OK"})
    _esperar()
    assert fluxo.ultimo().estado == "pronto"


# ── a revisão de 2026-11-01 ──────────────────────────────────────────────────


def test_erro_entre_os_passos_nao_deixa_o_fluxo_correndo(ops, monkeypatch):
    original = fluxo._gravar
    vezes = {"n": 0}

    def gravar(f):
        vezes["n"] += 1
        if vezes["n"] == 4:                      # depois do 1º passo feito: o disco falha
            raise OSError("disco cheio")
        original(f)
    monkeypatch.setattr(fluxo, "_gravar", gravar)
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    g = fluxo.ultimo()
    assert g.estado == "esperando"
    assert "entre os passos" in g.passos[g.atual].motivo


def test_inicio_recusado_nao_deixa_fluxo_fantasma(ops, monkeypatch):
    from cicloassist.mcp.ferramentas import fluxo as ferr
    monkeypatch.setattr(tarefas, "comecar", lambda *a, **k: (_ for _ in ()).throw(tarefas.TarefaEmCurso("varredura")))
    r = ferr.executar_fluxo(plano=_plano())
    assert "erro" in r and "Nada foi feito" in r["erro"]
    assert fluxo.em_aberto() is None
    assert not list(fluxo.pasta().glob("*.json"))


def test_so_se_pula_o_passo_que_parou(ops):
    _, comportamento = ops

    def a_e_pausa(**_):
        fluxo.pedir("pausar")
        return {"pasta": "/p"}
    comportamento["op_a"] = a_e_pausa
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    assert fluxo.ultimo().estado == "pausado"
    with pytest.raises(fluxo.PlanoInvalido, match="só se pula"):
        fluxo.pular(f.id)
    from cicloassist.mcp.ferramentas import fluxo as ferr
    assert "Só se pula" in ferr._conferir_continuar(acao="pular")


def test_fluxo_pausado_nao_pesa_no_turno(ops):
    _, comportamento = ops
    comportamento["op_a"] = lambda **_: (fluxo.pedir("pausar"), {"pasta": "/p"})[1]
    fluxo.iniciar(fluxo.criar(_plano()).id)
    _esperar()
    assert fluxo.ultimo().estado == "pausado" and fluxo.recado() == ""


def test_passo_que_usa_a_saida_de_um_pulado_diz_isso(ops):
    _, comportamento = ops
    comportamento["op_a"] = {"erro": "x"}
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    fluxo.pular(f.id)
    fluxo.iniciar(f.id)
    _esperar()
    g = fluxo.ultimo()
    assert g.passos[1].estado == "falhou" and "PULADO" in g.passos[1].motivo


def test_retomar_depois_do_reinicio_reautoriza_os_caminhos_aprovados(ops, tmp_path):
    """⛔ MEDIDO em 2026-11-02: o app reaberto no meio do conform, e o "Tentar de novo" recusou o
    `.prproj` do próprio plano — a autorização do arrasto morava só na memória do serviço."""
    from cicloassist.servico import arrastados
    chamadas, comportamento = ops
    arq = tmp_path / "corte.prproj"
    arq.write_text("x")
    estranho = str(tmp_path / "outro.prproj")
    arrastados.esquecer_tudo()
    arrastados.autorizar(arq)
    vistos: list[bool] = []
    comportamento["op_a"] = lambda **a: (vistos.append(arrastados.autorizado(a["pasta"])),
                                         {"erro": "caiu"})[1]
    f = fluxo.criar(_plano(parametros={"d": "D01", "p": str(arq), "x": estranho}))
    assert f.autorizados == [str(arq)]                  # o não autorizado não entra
    fluxo.iniciar(f.id)
    _esperar()

    arrastados.esquecer_tudo()                          # o serviço reiniciou
    fluxo.esquecer()
    comportamento.pop("op_a")
    fluxo.iniciar(f.id)
    _esperar()
    assert arrastados.autorizado(arq) and not arrastados.autorizado(estranho)
    assert fluxo.ultimo().estado == "pronto"


def test_corrigir_o_parametro_do_titulo_muda_o_nome(ops):
    _, comportamento = ops
    comportamento["op_a"] = {"erro": "não há essa diária"}
    f = fluxo.criar(_plano(nome="Preparar D01"))   # o nome vem resolvido (a receita faz isso)
    f.passos[0].args = {"pasta": "{d}"}
    fluxo.iniciar(f.id)
    _esperar()
    assert fluxo.ultimo().nome == "Preparar D01"
    comportamento.pop("op_a")
    fluxo.corrigir(f.id, {"pasta": "D02"})
    assert fluxo.ultimo().nome == "Preparar D02"


def test_depois_do_reinicio_o_ultimo_terminado_aparece(ops):
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    assert fluxo.ultimo().estado == "pronto"
    fluxo.esquecer()                             # o serviço reiniciou
    u = fluxo.ultimo()
    assert u is not None and u.id == f.id and u.estado == "pronto"
    assert fluxo.em_aberto() is None and fluxo.recado() == ""


def test_janela_do_app_cortada_para_antes_do_passo_e_retomar_segue(ops, monkeypatch):
    """Decisão do autor (2026-11-02): o layout é do editor — cortada, o passo NÃO roda, o fluxo diz por quê."""
    from cicloassist.piloto import espaco
    chamadas, _ = ops
    estado = {"cortada": False}
    monkeypatch.setattr(espaco, "janela_do_app_cortada",
                        lambda: espaco.FRASE_CORTADA if estado["cortada"] else "")
    original = fluxo._rodar_passo

    def rodar(f, passo):
        original(f, passo)
        estado["cortada"] = True                 # depois do 1º passo o editor arrastou a janela
    monkeypatch.setattr(fluxo, "_rodar_passo", rodar)
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    _esperar()
    g = fluxo.ultimo()
    assert g.estado == "esperando" and g.passos[1].estado == "falhou"
    assert "não mexo no seu layout" in g.passos[1].motivo
    assert [c[0] for c in chamadas] == ["op_a"]  # o passo b NÃO rodou

    monkeypatch.setattr(fluxo, "_rodar_passo", original)
    estado["cortada"] = False                    # arrumou a janela
    fluxo.iniciar(f.id)
    _esperar()
    assert fluxo.ultimo().estado == "pronto"
    assert [c[0] for c in chamadas] == ["op_a", "op_b", "op_c"]


def test_janela_do_app_minimizada_ou_auxiliar_nao_conta_como_cortada(monkeypatch):
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows")
    from cicloassist.piloto import espaco, tela
    monkeypatch.setattr(espaco, "_nossas", lambda: [(1, False), (2, False), (3, False)])
    rets = {1: (-32000, -32000, -31840, -31972), 2: (0, 0, 18, 18), 3: (1700, 60, 2318, 1080)}
    monkeypatch.setattr(espaco._u, "IsIconic", lambda h: h.value == 1 if hasattr(h, "value") else h == 1)

    def ret(h, p):
        e, t, d, b = rets[h.value if hasattr(h, "value") else h]
        p._obj.left, p._obj.top, p._obj.right, p._obj.bottom = e, t, d, b
        return 1
    monkeypatch.setattr(espaco._u, "GetWindowRect", ret)
    monkeypatch.setattr(tela, "monitores", lambda: [(0, 0, 1920, 1080), (1920, -549, 3840, 531)])
    assert "não mexo no seu layout" in espaco.janela_do_app_cortada()       # a 3 desce na faixa morta
    rets[3] = (1298, 7, 1916, 1027)
    assert espaco.janela_do_app_cortada() == ""


# ── a bancada do modelo mínimo (2026-11-02): as alavancas que não dependem do modelo ──────────


def test_conselho_leva_os_fatos_e_marca_as_condicoes_como_regras(ops, tmp_path, monkeypatch):
    from cicloassist.motor import conselho
    (tmp_path / "CAM").mkdir()
    for n in ("a.mov", "b.mov", "CAM/c.mov", "._lixo.mov"):
        (tmp_path / n).write_bytes(b"")
    f = fluxo.criar(_plano(parametros={"d": "D01", "p": str(tmp_path)}))
    pedido = conselho._pedido(f, "- A pasta já é OP-Atom: pule a conversão.")
    assert "FATOS medidos agora" in pedido and "3 .mov" in pedido          # o `._` do macOS fica fora
    assert "só vale SE a condição" in pedido and "NÃO se aplica" in pedido
    assert pedido.index("FATOS") < pedido.index("REGRAS CONDICIONAIS")


def test_conselho_de_modelo_local_vai_direto_ao_ollama_sem_raciocinio(ops, monkeypatch):
    import io
    from cicloassist.motor import conselho, percepcao
    monkeypatch.setattr(percepcao, "endereco", lambda: "http://192.168.1.4:11434")
    pedidos = []

    def urlopen(req, timeout=0):
        pedidos.append(json.loads(req.data))
        return io.BytesIO(json.dumps({"message": {"content": '{"explicacao": "x", "acao": "esperar", "args": {}}'},
                                      "prompt_eval_count": 900, "eval_count": 40}).encode())
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(conselho._turno, "achar_o_cli", lambda: pytest.fail("o local não sobe o CLI"))
    f = fluxo.criar(_plano())
    c = conselho.aconselhar(f, "", modelo="ollama:qwen3.5:4b")
    assert c["acao"] == "esperar" and c["uso"]["custo_usd"] == 0.0
    assert pedidos[0]["think"] is False and pedidos[0]["format"] == "json" and pedidos[0]["model"] == "qwen3.5:4b"


def test_modelo_local_ve_so_as_ferramentas_de_fluxo(monkeypatch):
    from cicloassist.mcp import servidor
    from cicloassist.servico import config
    monkeypatch.setattr(config, "modelo_guardado", lambda: "claude-sonnet-5-5")
    todas = {f.nome for f in servidor.visiveis()}
    monkeypatch.setattr(config, "modelo_guardado", lambda: "ollama:qwen3.5:4b")
    locais = {f.nome for f in servidor.visiveis()}
    assert locais == servidor.ESSENCIAIS_DO_LOCAL & todas and "pedir_confirmacao" in locais
    assert len(todas) > len(locais)


def test_o_chat_nao_dispara_fluxo_mas_ve_as_receitas(monkeypatch):
    """⭐⭐ Autor, 2026-11-03: o chat é o pedido imediato, feito ferramenta a ferramenta; o fluxo é
    da aba Fluxos. Com `executar_fluxo` à vista, o chat procurava receita para tudo e travava no
    pedido que nenhuma cobria. `listar_receitas` fica: o chat pode SUGERIR o fluxo pronto."""
    from cicloassist.mcp import servidor
    from cicloassist.servico import config
    monkeypatch.setattr(config, "modelo_guardado", lambda: "claude-sonnet-5-5")
    nomes = {f.nome for f in servidor.visiveis()}
    assert not (nomes & {"executar_fluxo", "continuar_fluxo", "gerar_midia_de_teste"})
    assert {"listar_receitas", "abrir_programa", "converter_para_opatom",
            "sincronizar", "salvar_tudo"} <= nomes


def test_fio_velho_que_chama_executar_fluxo_no_chat_ouve_o_porque():
    from cicloassist.mcp import servidor
    r = servidor.responder({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "executar_fluxo", "arguments": {"receita": "x"}}})
    texto = r["result"]["content"][0]["text"]
    assert r["result"]["isError"] and "aba Fluxos" in texto


def test_o_fluxo_parado_vai_para_a_aba_fluxos_e_nunca_para_o_chat(monkeypatch):
    """⭐ 2026-11-03: quem tem `continuar_fluxo` é a conversa da aba Fluxos."""
    from cicloassist.servico import rotas as R
    monkeypatch.setattr(R._fluxo, "recado", lambda: "O fluxo X parou no passo 3.")
    monkeypatch.setattr(R._pendencias, "recados", lambda qual="chat": [])
    assert "parou no passo 3" in R._com_recados("p", "t", "fluxos")
    assert "parou no passo 3" not in R._com_recados("p", "t", "chat")


def test_nenhuma_descricao_do_chat_aponta_a_midia_de_teste():
    """⛔ Autor, 2026-11-03: a mídia de teste é do PILOTO. As descrições de converter e do som citavam
    `gerar_midia_de_teste`, e o chat a chamou sem ninguém pedir no teste da D01."""
    from cicloassist.mcp import servidor
    for f in servidor.visiveis():
        assert "gerar_midia_de_teste" not in f.descricao, f.nome


def test_a_aba_fluxos_tem_as_receitas_o_cartao_e_o_quadro():
    """⭐⭐ F2 (autor, 2026-11-03): receitas, cartão do plano e quadro do andamento moram na aba Fluxos,
    não no chat. O menu ☰ do chat volta a ser só de atalhos."""
    from pathlib import Path
    painel = Path(__file__).resolve().parents[1] / "cicloassist" / "painel"
    html = (painel / "index.html").read_text(encoding="utf-8")
    fluxo = (painel / "fluxo.js").read_text(encoding="utf-8")
    js = (painel / "painel.js").read_text(encoding="utf-8")
    assert 'data-tela="fluxos"' not in html and 'id="fluxosQuadro"' in html  # N5: a aba saiu, e o quadro fica na conversa
    assert "menuReceitas" not in html and "menuReceitas" not in fluxo
    assert "compositor.parentNode.insertBefore(quadro" not in fluxo     # o quadro saiu do pé do chat
    assert "areaFluxos.appendChild(forma)" in fluxo                     # o formulário nasce na aba
    assert "window.destinoDoFluxo()" in js                              # e o cartão do plano também


def test_a_aba_fluxos_mostra_o_andamento_e_esquece_o_fluxo_de_outra_sessao():
    """⭐⭐ Autor, 2026-11-04: o andamento sumia de vista (quadro no alto de uma tela que rola), não havia
    barra no sync do Sincronizar, e um fluxo terminado ontem ficava preso na aba como memória."""
    from pathlib import Path
    painel = Path(__file__).resolve().parents[1] / "cicloassist" / "painel"
    css = (painel / "painel.css").read_text(encoding="utf-8")
    fluxo = (painel / "fluxo.js").read_text(encoding="utf-8")
    js = (painel / "painel.js").read_text(encoding="utf-8")
    assert ".fluxos-quadro-lugar { flex: none;" in css                        # N5: acima da conversa, fora da rolagem dela
    assert 'el("div", "fluxo-barra")' in fluxo                                # a barra, com fração
    assert "!vistosVivos[f.id]" in fluxo                                      # terminado de antes: escondido
    assert "window.acompanharFluxo(r.fluxo);" in js and "cartao.remove();" in js  # o cartão dá lugar ao quadro


# ── cancelar NO MEIO de um passo (autor, 2026-11-04) ─────────────────────────


def test_cancelar_para_na_hora_um_passo_que_espera(ops):
    """⭐⭐ "Se o usuário quiser interromper não tem como": um passo que ESPERA um programa de fora (o
    sync do Sincronizar) confere o pedido a cada volta e para na hora; o fluxo termina cancelado e o passo diz
    o que ficou (o programa de fora pode terminar do lado dele)."""
    import threading
    import time as _t
    _, comportamento = ops
    esperando = threading.Event()
    voltas = []

    def espera_longa(**_):
        esperando.set()
        for _ in range(200):                       # ~10 s se ninguém cancelar
            pendencias.conferir_cancelamento("o sync de mentira")
            voltas.append(1)
            _t.sleep(0.05)
        return {"ok": True}

    comportamento["op_b"] = espera_longa
    f = fluxo.criar(_plano())
    fluxo.iniciar(f.id)
    assert esperando.wait(5)
    inicio = _t.monotonic()
    fluxo.pedir("cancelar")
    _esperar()
    f = fluxo.ultimo()
    assert _t.monotonic() - inicio < 2                 # parou na hora, não ao fim dos 10 s
    assert f.estado == "cancelado" and len(voltas) < 200
    assert [p.estado for p in f.passos] == ["feito", "cancelado", "a_fazer"]
    assert "cancelado no meio" in f.passos[1].motivo


def test_fora_de_um_fluxo_conferir_cancelamento_nao_faz_nada():
    pendencias.conferir_cancelamento("qualquer coisa")     # sem fluxo: nada levanta


def test_a_lista_de_quem_para_no_meio_e_a_mesma_na_tela_e_no_servico():
    from pathlib import Path
    js = (Path(fluxo.__file__).parent.parent / "painel" / "fluxo.js").read_text(encoding="utf-8")
    for op in fluxo._O_QUE_FICA:
        assert f"{op}: true" in js, op


def test_o_esperar_do_sincronizar_confere_a_cada_volta(monkeypatch):
    """A etapa do sync muda pouco (minutos na mesma); a conferência não pode depender dela."""
    from cicloassist import sincronizar as sinc
    monkeypatch.setattr(sinc, "andamento", lambda job: {"state": "running", "stage": "mesma", "fraction": 0.1})
    monkeypatch.setattr(sinc, "INTERVALO_S", 0.01)
    voltas = []

    def conferir():
        voltas.append(1)
        if len(voltas) >= 5:
            raise pendencias.PassoCancelado("o sync")

    with pytest.raises(pendencias.PassoCancelado):
        sinc.esperar("job", conferir=conferir)
    assert len(voltas) == 5


def test_fluxo_gravado_com_o_nome_antigo_da_ferramenta_ainda_roda():
    # ⭐ Fase 3 (2026-11-07): `sincronizar_com_o_orbita` → `sincronizar`; o que já estava gravado vale como o novo
    from cicloassist.servico import fluxo as F
    assert F.Passo(id="sync", op="sincronizar_com_o_" + "orbita", args={}).op == "sincronizar"
    assert F.op_atual("merged_pelo_" + "orbita") == "criar_merged" and F.op_atual("salvar_tudo") == "salvar_tudo"


# ── os ramos (N3) ─────────────────────────────────────────────────────────────


def _ramo(passos, **extra):
    return {"nome": "ramo", "parametros": {}, "passos": passos, **extra}


def _rodar_ate_parar(f):
    fluxo.iniciar(f.id)
    _esperar()
    return fluxo.ler(f.id)


DIAMANTE = [{"id": "a", "op": "op_a", "args": {}},
            {"id": "b", "op": "op_a", "args": {}, "se": {"campo": "a.ok", "e": "sim"}},
            {"id": "c", "op": "op_c", "args": {}, "depois_de": ["a"], "se": {"campo": "a.ok", "e": "nao"}},
            {"id": "d", "op": "op_c", "args": {}, "depois_de": ["b", "c"]}]


def test_lista_sem_ramo_continua_igual_no_validar(ops):
    assert fluxo.validar(_plano()) == []


def test_ramo_verdadeiro_roda_o_seu_e_o_outro_fica_fora_e_a_juncao_roda(ops):
    f = _rodar_ate_parar(fluxo.criar(_ramo(DIAMANTE)))
    assert {p.id: p.estado for p in f.passos} == {"a": "feito", "b": "feito", "c": "fora", "d": "feito"}
    assert f.estado == "pronto"


def test_ramo_falso_escolhe_o_outro(ops):
    chamadas, comportamento = ops
    comportamento["op_a"] = {"ok": False}
    p = [dict(x) for x in DIAMANTE]
    p[1] = {**p[1], "op": "op_c"}
    f = _rodar_ate_parar(fluxo.criar(_ramo(p)))
    assert {q.id: q.estado for q in f.passos} == {"a": "feito", "b": "fora", "c": "feito", "d": "feito"}


def test_se_todos_os_pais_ficam_fora_o_filho_tambem_fica(ops):
    p = [{"id": "a", "op": "op_a", "args": {}}, {"id": "b", "op": "op_c", "args": {}, "se": {"campo": "a.ok", "e": "nao"}},
         {"id": "c", "op": "op_c", "args": {}}]
    f = _rodar_ate_parar(fluxo.criar(_ramo(p)))
    assert f.passos[1].estado == "fora" and f.passos[2].estado == "fora" and f.estado == "pronto"
    assert "não foi seguido" in f.passos[2].motivo


@pytest.mark.parametrize("valor,e,alvo,roda", [("X", "igual", "X", True), ("X", "igual", "Y", False), ([], "sim", None, False), ([], "nao", None, True), (["a"], "sim", None, True), (0, "igual", "0", True)])
def test_cada_condicao(ops, valor, e, alvo, roda):
    _, comportamento = ops
    comportamento["op_a"] = {"v": valor}
    se = {"campo": "a.v", "e": e, **({"valor": alvo} if alvo is not None else {})}
    f = _rodar_ate_parar(fluxo.criar(_ramo([{"id": "a", "op": "op_a", "args": {}}, {"id": "b", "op": "op_c", "args": {}, "se": se}])))
    assert f.passos[1].estado == ("feito" if roda else "fora")


def test_campo_que_a_peca_nao_devolveu_para_e_diz_em_vez_de_escolher_um_caminho(ops):
    f = _rodar_ate_parar(fluxo.criar(_ramo([{"id": "a", "op": "op_a", "args": {}}, {"id": "b", "op": "op_c", "args": {}, "se": {"campo": "a.nao_ha", "e": "sim"}}])))
    assert f.estado == "esperando" and f.passos[1].estado == "falhou" and "não devolveu" in f.passos[1].motivo


def test_ramo_para_e_retoma_sem_refazer_nem_mudar_o_caminho(ops):
    chamadas, comportamento = ops
    falhas = []

    def falha_uma_vez(**_):
        if not falhas:
            falhas.append(1)
            return {"erro": "disco cheio"}
        return {"pasta": "x"}

    comportamento["op_c"] = falha_uma_vez
    f = _rodar_ate_parar(fluxo.criar(_ramo(DIAMANTE)))
    assert f.estado == "esperando" and {p.id: p.estado for p in f.passos} == {"a": "feito", "b": "feito", "c": "fora", "d": "falhou"}
    fluxo.esquecer()                    # o serviço reiniciou: só o disco sobrou
    d = _rodar_ate_parar(fluxo.ler(f.id))
    assert d.estado == "pronto" and {p.id: p.estado for p in d.passos} == {"a": "feito", "b": "feito", "c": "fora", "d": "feito"}
    assert [c[0] for c in chamadas] == ["op_a", "op_a", "op_c", "op_c"]


def test_dado_de_um_ramo_que_ficou_fora_para_e_diz(ops):
    p = [dict(x) for x in DIAMANTE]
    p[3] = {**p[3], "args": {"pasta": "{c.pasta}"}}
    f = _rodar_ate_parar(fluxo.criar(_ramo(p)))
    assert f.estado == "esperando" and f.passos[3].estado == "falhou" and "PULADO" in f.passos[3].motivo


@pytest.mark.parametrize("extra,trecho", [
    ({"depois_de": "a"}, "lista de ids"), ({"depois_de": ["z"]}, "não vem ANTES"),
    ({"se": {"campo": "a.x", "e": "talvez"}}, "'se' tem de ser"), ({"se": {"campo": "z.x", "e": "sim"}}, "não vem ANTES"),
    ({"se": {"campo": "a", "e": "sim"}}, "não vem ANTES"), ({"se": {"campo": "a.x", "e": "igual"}}, "precisa de 'valor'"),
])
def test_ramo_malformado_e_recusado(ops, extra, trecho):
    problemas = fluxo.validar(_ramo([{"id": "a", "op": "op_a", "args": {}}, {"id": "b", "op": "op_c", "args": {}, **extra}]))
    assert any(trecho in x for x in problemas), problemas


def test_ramo_sobrevive_ao_estado_no_disco(ops):
    f = fluxo.criar(_ramo(DIAMANTE))
    lido = fluxo.ler(f.id)
    assert lido.passos[2].depois_de == ["a"] and lido.passos[2].se == {"campo": "a.ok", "e": "nao"}


# ── as voltas e as perguntas (N4) ─────────────────────────────────────────────


@pytest.fixture
def leitura(monkeypatch):
    """Uma operação que não grava, como o agente, que pergunta enquanto não tiver resposta."""
    rodadas = []

    def agente(respostas="", **_):
        rodadas.append(respostas)
        return {"perguntas": [] if respostas else ["De que câmera é?"]}
    monkeypatch.setitem(FERRAMENTAS, "ag", Ferramenta(nome="ag", descricao="", escreve=False, funcao=agente, esquema={"type": "object", "properties": {"respostas": {}}}))
    return rodadas


def _com_volta(teto=2, **volta):
    return _ramo([
        {"id": "m", "op": "ag", "args": {"respostas": "{p.respostas}"}},
        {"id": "p", "op": fluxo.OP_PERGUNTAR, "args": {"perguntas": "{m.perguntas}"}, "se": {"campo": "m.perguntas", "e": "sim"}, "volta": {"para": "m", "teto": teto, **volta}},
        {"id": "s", "op": "op_c", "args": {}, "depois_de": ["m"], "se": {"campo": "m.perguntas", "e": "nao"}}])


# ── confirmar na memória (N4b) ────────────────────────────────────────────────


APROVADA = {"forma": "#-#T#", "molde": "{cena}-{plano}T{take}", "aprovada": True, "exemplo": "18-1T01.WAV → 18 · 1 · 01", "arquivos": 31}
REPROVADA = {"forma": "#X#", "molde": "{cena}X{take}", "aprovada": False}


@pytest.fixture
def memoria(monkeypatch):
    """A leitura devolve regras, e a gravação de verdade é trocada por uma que anota."""
    gravou, leitura_diz = [], {"regras_aprovadas": [APROVADA, REPROVADA], "producao": {"memoria": None, "projeto_aberto": "D01", "no_ixml": ["FILME"], "memorias_existentes": []}, "perguntas": []}

    def gravar(**k):
        gravou.append(k)
        return gravar.resposta
    gravar.resposta = {"producao": "FILME", "regras": 1, "arquivo": "x.md", "manchete": "ok"}
    monkeypatch.setitem(FERRAMENTAS, "ag", Ferramenta(nome="ag", descricao="", escreve=False, funcao=lambda **_: leitura_diz, esquema={"type": "object", "properties": {"respostas": {}}}))
    monkeypatch.setitem(FERRAMENTAS, fluxo.OP_GRAVAR_NA_MEMORIA, dataclasses.replace(FERRAMENTAS[fluxo.OP_GRAVAR_NA_MEMORIA], funcao=gravar))
    return type("M", (), {"gravou": gravou, "gravar": gravar, "leitura": leitura_diz})


def _com_confirmar(**extra):
    return _ramo([{"id": "m", "op": "ag", "args": {}},
                  {"id": "c", "op": fluxo.OP_CONFIRMAR, "args": {"regras": "{m.regras_aprovadas}", "producao": "{m.producao}", "pasta": "/d", **extra}},
                  {"id": "s", "op": "op_c", "args": {}}])


def test_confirmar_para_e_nada_grava_sem_o_clique(ops, memoria):
    f = _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    assert f.estado == "perguntando" and memoria.gravou == [] and not tarefas._thread.is_alive()
    cartao = f.passos[1].saida["confirmar"]
    assert [r["forma"] for r in cartao["regras"]] == ["#-#T#"]              # a reprovada não entra
    assert cartao["sugestoes"] == ["FILME", "D01"] and cartao["origem"]["pasta"] == "/d"


def test_o_modo_automatico_nao_responde_pelo_editor(ops, memoria, monkeypatch):
    from cicloassist.servico import config
    monkeypatch.setattr(config, "ler", lambda: {"auto": True})
    f = _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    assert f.estado == "perguntando" and memoria.gravou == []


def test_o_clique_grava_o_que_esta_no_passo_e_segue(ops, memoria):
    chamadas, _ = ops
    f = _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    fluxo.confirmar(True, "FILME", True)
    _esperar()
    d = fluxo.ler(f.id)
    assert d.estado == "pronto" and [c[0] for c in chamadas] == ["op_c"] and d.passos[1].saida["gravou"] is True
    assert memoria.gravou == [{"producao": "FILME", "regras": [{"forma": "#-#T#", "molde": "{cena}-{plano}T{take}"}], "nao_se_sabe": [], "apelidos": ["D01"], "pasta": "/d", "bin": "", "programa": ""}]


def test_nao_gravar_segue_sem_gravar(ops, memoria):
    f = _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    fluxo.confirmar(False)
    _esperar()
    d = fluxo.ler(f.id)
    assert d.estado == "pronto" and memoria.gravou == [] and d.passos[1].saida["gravou"] is False


def test_sem_nome_de_producao_nao_grava_e_fica_esperando(ops, memoria):
    f = _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    with pytest.raises(fluxo.PlanoInvalido, match="produção"):
        fluxo.confirmar(True, "   ")
    assert memoria.gravou == [] and fluxo.ler(f.id).estado == "perguntando"


def test_a_conferencia_que_reprova_deixa_o_cartao_na_tela(ops, memoria):
    f = _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    memoria.gravar.resposta = {"erro": "Estas regras não passaram na conferência"}
    with pytest.raises(fluxo.PlanoInvalido, match="conferência"):
        fluxo.confirmar(True, "FILME")
    assert fluxo.ler(f.id).estado == "perguntando" and fluxo.ler(f.id).passos[1].confirmacao is None


def test_memoria_conhecida_nao_pergunta_o_nome(ops, memoria):
    memoria.leitura["producao"] = {"memoria": "PRODUCAO-A", "projeto_aberto": "PRODUCAO-A"}
    _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    fluxo.confirmar(True)
    _esperar()
    assert memoria.gravou[0]["producao"] == "PRODUCAO-A" and memoria.gravou[0]["apelidos"] == []


def test_sem_regra_aprovada_ninguem_e_interrompido(ops, memoria):
    memoria.leitura["regras_aprovadas"] = [REPROVADA]
    f = _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    assert f.estado == "pronto" and memoria.gravou == [] and f.passos[1].saida == {"gravou": False, "regras": 0, "motivo": "não havia nada a confirmar"}


def test_nao_sei_entra_pelo_trecho_e_pergunta_sem_resposta_nao(ops, memoria, monkeypatch):
    memoria.leitura["regras_aprovadas"] = []
    memoria.leitura["perguntas"] = [{"texto": "O que é ct?", "sobre": "ct"}, {"texto": "O que é xz?", "sobre": "xz"}]
    p = _ramo([{"id": "m", "op": "ag", "args": {}},
               {"id": "p", "op": fluxo.OP_PERGUNTAR, "args": {"perguntas": "{m.perguntas}"}},
               {"id": "c", "op": fluxo.OP_CONFIRMAR, "args": {"regras": "{m.regras_aprovadas}", "producao": "{m.producao}", "respostas": "{p.respostas}"}}])
    _rodar_ate_parar(fluxo.criar(p))
    fluxo.responder([{"pergunta": "O que é ct?", "resposta": "Não sei", "sobre": "forjado"}, {"pergunta": "O que é xz?", "resposta": "take"}])
    _esperar()
    f = fluxo.em_aberto()
    assert f.estado == "perguntando" and f.passos[2].saida["confirmar"]["nao_se_sabe"] == ["ct"]


def test_perguntar_de_fora_do_caminho_nao_derruba_o_confirmar(ops, memoria):
    p = _ramo([{"id": "m", "op": "ag", "args": {}},
               {"id": "p", "op": fluxo.OP_PERGUNTAR, "args": {"perguntas": "{m.perguntas}"}, "se": {"campo": "m.perguntas", "e": "sim"}},
               {"id": "c", "op": fluxo.OP_CONFIRMAR, "args": {"regras": "{m.regras_aprovadas}", "producao": "{m.producao}", "respostas": "{p.respostas}"}, "depois_de": ["m"]}])
    f = _rodar_ate_parar(fluxo.criar(p))
    assert f.estado == "perguntando" and f.passos[2].op == fluxo.OP_CONFIRMAR


def test_confirmar_sobrevive_ao_reinicio_do_servico(ops, memoria):
    f = _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    fluxo.esquecer()
    fluxo.confirmar(True, "FILME")
    _esperar()
    assert fluxo.ler(f.id).estado == "pronto" and len(memoria.gravou) == 1


def test_responder_nao_atende_o_cartao_de_confirmar(ops, memoria):
    _rodar_ate_parar(fluxo.criar(_com_confirmar()))
    with pytest.raises(fluxo.PlanoInvalido):
        fluxo.responder([{"pergunta": "x", "resposta": "y"}])
    assert memoria.gravou == []


def test_a_volta_nao_repete_o_confirmar():
    problemas = fluxo.validar({"passos": [{"id": "a", "op": "entender_metadados_da_diaria", "args": {}},
                                          {"id": "c", "op": fluxo.OP_CONFIRMAR, "args": {"regras": "{a.regras_aprovadas}", "producao": "{a.producao}"}, "volta": {"para": "a", "teto": 1}}], "parametros": {}})
    assert any("só repete quem não grava" in p for p in problemas)


def test_a_gravacao_continua_fora_dos_passos():
    problemas = fluxo.validar({"passos": [{"id": "g", "op": fluxo.OP_GRAVAR_NA_MEMORIA, "args": {"producao": "X"}}], "parametros": {}})
    assert any("não pode ser passo" in p for p in problemas)


def test_a_pergunta_para_e_nao_segura_a_fila(ops, leitura):
    f = _rodar_ate_parar(fluxo.criar(_com_volta()))
    assert f.estado == "perguntando" and f.passos[1].estado == "perguntando" and f.passos[1].saida["perguntas"][0]["texto"] == "De que câmera é?"
    assert not tarefas._thread.is_alive()       # a fila fica livre enquanto ele pensa, mesmo que leve um dia


def test_a_resposta_volta_ao_agente_e_o_caminho_certo_segue(ops, leitura):
    chamadas, _ = ops
    f = _rodar_ate_parar(fluxo.criar(_com_volta()))
    fluxo.responder([{"pergunta": "De que câmera é?", "resposta": "A"}])
    _esperar()
    d = fluxo.ler(f.id)
    assert d.estado == "pronto" and leitura[0] == "" and leitura[1] == [{"pergunta": "De que câmera é?", "resposta": "A"}]
    assert {p.id: p.estado for p in d.passos} == {"m": "feito", "p": "fora", "s": "feito"} and [c[0] for c in chamadas] == ["op_c"]
    assert d.voltas == {"p": 1}


def test_a_pergunta_sobrevive_ao_reinicio_do_servico(ops, leitura):
    f = _rodar_ate_parar(fluxo.criar(_com_volta()))
    fluxo.esquecer()
    assert fluxo.em_aberto().estado == "perguntando"
    fluxo.responder([{"pergunta": "x", "resposta": "A"}])
    _esperar()
    assert fluxo.ler(f.id).estado == "pronto"


def test_para_no_teto_e_diz_e_pular_segue(ops, leitura, monkeypatch):
    FERRAMENTAS["ag"] = FERRAMENTAS["ag"].__class__(nome="ag", descricao="", escreve=False, esquema=FERRAMENTAS["ag"].esquema,
                                                    funcao=lambda **_: (leitura.append(1) or {"perguntas": ["De novo?"]}))
    f = _rodar_ate_parar(fluxo.criar(_com_volta(teto=2)))
    for _ in range(3):
        fluxo.responder([{"pergunta": "x", "resposta": "y"}])
        _esperar()
        d = fluxo.ler(f.id)
    assert d.estado == "esperando" and d.passos[1].teto_atingido and "teto de 2" in d.passos[1].motivo and len(leitura) == 3
    fluxo.pular(d.id)
    fluxo.iniciar(d.id)
    _esperar()
    assert fluxo.ler(f.id).passos[1].estado == "pulado"


def test_responder_sem_nada_e_recusado(ops, leitura):
    _rodar_ate_parar(fluxo.criar(_com_volta()))
    with pytest.raises(fluxo.PlanoInvalido):
        fluxo.responder([{"pergunta": "x", "resposta": "  "}])
    with pytest.raises(fluxo.PlanoInvalido):
        fluxo.responder("texto")


def test_sem_perguntas_o_node_nao_interrompe_e_nao_volta(ops, leitura):
    p = _ramo([{"id": "m", "op": "ag", "args": {"respostas": "ja"}},
               {"id": "q", "op": fluxo.OP_PERGUNTAR, "args": {"perguntas": "{m.perguntas}"}, "volta": {"para": "m", "teto": 2}}])
    f = _rodar_ate_parar(fluxo.criar(p))
    assert f.estado == "pronto" and f.voltas == {} and len(leitura) == 1


@pytest.mark.parametrize("volta,trecho", [
    ({"para": "z", "teto": 2}, "ANTES dele"), ({"para": "a"}, "tem teto"), ({"para": "a", "teto": 9}, "tem teto"), ({"para": "a", "teto": True}, "tem teto"), ("a", "ANTES dele"),
])
def test_volta_malformada_e_recusada(ops, leitura, volta, trecho):
    problemas = fluxo.validar(_ramo([{"id": "a", "op": "ag", "args": {}}, {"id": "b", "op": "ag", "args": {}, "volta": volta}]))
    assert any(trecho in x for x in problemas), problemas


def test_volta_nao_repete_quem_grava(ops, leitura):
    problemas = fluxo.validar(_ramo([{"id": "a", "op": "op_a", "args": {}}, {"id": "b", "op": "ag", "args": {}, "volta": {"para": "a", "teto": 2}}]))
    assert any("que grava algo" in x for x in problemas), problemas


def test_ler_adiante_so_vale_dentro_da_volta(ops, leitura):
    fora = _ramo([{"id": "a", "op": "ag", "args": {"respostas": "{b.x}"}}, {"id": "b", "op": "ag", "args": {}}])
    assert any("não vem ANTES" in x for x in fluxo.validar(fora))
    assert fluxo.validar(_com_volta()) == []


# ── o que se sabe antes de começar, e o diálogo no caminho (teste pilotado de 2026-11-09) ──


def test_a_pasta_sem_midia_recusa_antes_de_abrir_programa(tmp_path):
    from cicloassist.mcp.ferramentas import fluxo as FF
    from cicloassist.mcp import ferramentas  # noqa: F401
    plano = {"nome": "x", "parametros": {"pasta": str(tmp_path)}, "passos": [
        {"id": "abrir", "op": "abrir_programa", "args": {"programa": "resolve", "projeto": "P"}},
        {"id": "conv", "op": "converter_para_opatom", "args": {"projeto": "P", "pasta": "{pasta}"}}]}
    motivo = FF._conferir(plano=plano)
    assert motivo.startswith("O passo conv não vai dar certo")


def test_a_previa_nao_olha_o_que_um_passo_anterior_vai_criar():
    from cicloassist.mcp.ferramentas import fluxo as FF
    from cicloassist.servico import fluxo as F
    from cicloassist.mcp import ferramentas  # noqa: F401
    plano = {"nome": "x", "parametros": {}, "passos": [
        {"id": "a", "op": "converter_para_opatom", "args": {"projeto": "P", "pasta": "C:/nao-existe"}},
        {"id": "b", "op": "som_direto_gerenciado", "args": {"pasta": "{a.pasta}", "bin": "B"}}]}
    assert "passo b" not in FF._conferir(plano=plano) and "passo a" in FF._conferir(plano=plano) and F.validar(plano) == []


@pytest.mark.skipif(sys.platform != "win32", reason="o socorro do MC só existe no Windows")
def test_dialogo_no_caminho_de_um_passo_do_mc_chama_o_agente(monkeypatch):
    from cicloassist.avid import socorro as S
    from cicloassist.servico import fluxo as F
    visto = {"n": 0}
    monkeypatch.setattr(S, "inesperada", lambda: visto["n"] == 0)

    def com_agente(objetivo, tentar, falha, relatar):
        with pytest.raises(falha):
            tentar()
        visto["n"] += 1
        tentar()
    monkeypatch.setattr(S, "com_agente", com_agente)
    F._sem_dialogo_no_mc(SimpleNamespace(op="importar_masters_opatom", id="camera"))
    assert visto["n"] == 1


@pytest.mark.skipif(sys.platform != "win32", reason="o socorro do MC só existe no Windows")
@pytest.mark.parametrize("op", ["abrir_programa", "fechar_programa", "salvar_tudo", "converter_para_opatom", "perguntar_ao_editor"])
def test_quem_tem_socorro_proprio_ou_nao_fala_com_o_mc_nao_passa_por_ali(monkeypatch, op):
    from cicloassist.avid import socorro as S
    from cicloassist.servico import fluxo as F
    monkeypatch.setattr(S, "inesperada", lambda: pytest.fail("não devia olhar"))
    F._sem_dialogo_no_mc(SimpleNamespace(op=op, id="p"))


def test_a_api_muda_com_dialogo_na_tela_diz_o_que_e(monkeypatch):
    import grpc
    from cicloassist.avid import mcapi as M, socorro as S

    class Erro(grpc.RpcError):
        def code(self): return grpc.StatusCode.DEADLINE_EXCEEDED
        def details(self): return ""
    assert "pode estar ocupado" in str(M.MediaComposer._traduzir(Erro(), "GetAppInfo"))
    monkeypatch.setattr(S, "inesperada", lambda: True)
    assert "diálogo" in str(M.MediaComposer._traduzir(Erro(), "GetAppInfo"))
