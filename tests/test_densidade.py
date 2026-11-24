"""A DENSIDADE da decupagem — quantos quadros o modelo olha por mídia (F3 do plano).

Pedido do editor: *"manual e/ou automático"*. O automático já existe e mora na MICRO
(`micro.posicoes_do_trecho` dá de 3 a 8 quadros por trecho conforme o movimento medido);
isto é a escolha manual da macro, onde seis quadros descrevem bem um plano e descrevem mal
um master de quatro minutos que vai do geral ao close.

O que estes testes travam:

- o nível escolhido chega aos DOIS motores (o Claude e o Mac);
- o teto do que o chat aceita não fica ABAIXO do que a fila pede — senão o editor paga por
  24 quadros e o modelo olha 12, em silêncio;
- o preço muda com o nível, e só o nível medido se diz medido;
- nome desconhecido cai no padrão em vez de virar erro.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.mcp.ferramentas import midia as FM
from cicloassist.mcp.ferramentas import visual as FV
from cicloassist.motor import decupador as D
from cicloassist.servico import rotas as R
from cicloassist.servico.http import Pedido


def test_o_teto_do_chat_cobre_o_que_a_fila_pede():
    """⛔⛔ O nível `exaustivo` pede 24 quadros, e `ver_quadros_da_midia` cortava em 12: o
    editor pagaria por 24 e o modelo olharia 12, sem nada na tela dizendo."""
    maior = max(D.DENSIDADES.values())
    assert FM.MAXIMO >= maior
    assert FV.MAXIMO >= maior


def test_nome_desconhecido_cai_no_padrao():
    """⚠️ É escolha de TELA: um 400 aqui viraria "o botão não faz nada" por uma palavra."""
    padrao = D.DENSIDADES[D.DENSIDADE_PADRAO]
    assert D.quadros_da_densidade(None) == padrao
    assert D.quadros_da_densidade("") == padrao
    assert D.quadros_da_densidade("exuberante") == padrao
    assert D.quadros_da_densidade("FINO") == D.DENSIDADES["fino"]


def test_o_preco_cresce_com_a_densidade_e_so_um_nivel_e_medido():
    """⛔ Preço estimado apresentado como medido é a mentira que este produto mais promete
    não contar — a tela lê `medido` para escolher entre "medido em" e "estimado em"."""
    p = D.preco_por_densidade()

    assert p["macro"]["tokens_por_midia"] == D.TOKENS_POR_MIDIA
    assert p["macro"]["medido"] is True
    assert p["fino"]["medido"] is False and p["exaustivo"]["medido"] is False
    assert p["fino"]["tokens_por_midia"] > p["macro"]["tokens_por_midia"]
    assert p["exaustivo"]["custo_por_midia_usd"] > p["fino"]["custo_por_midia_usd"]
    # O acréscimo é o tamanho dos quadros a mais, não um número solto.
    assert (p["fino"]["tokens_por_midia"] - p["macro"]["tokens_por_midia"]
            == (D.DENSIDADES["fino"] - D.DENSIDADES["macro"]) * D.TOKENS_POR_QUADRO)


def test_a_conta_do_tempo_e_do_MOTOR_que_vai_rodar():
    """⛔⛔ Pelo Claude o tempo mal muda — o custo é do TURNO. Pelo Mac ele É a inferência,
    e cresce com as imagens.

    VISTO NA TELA em 2026-09-22, antes deste conserto: com a régua do Claude aplicada ao
    Mac, o painel anunciou **20 min** para um trabalho de **3 horas** (118 mídias × 95 s).
    """
    claude = D.preco_por_densidade()
    mac = D.preco_por_densidade(segundos_base=95, teto_de_quadros=22)

    assert claude["exaustivo"]["segundos_por_midia"] < 2 * claude["macro"]["segundos_por_midia"]
    assert mac["macro"]["segundos_por_midia"] == 95
    assert mac["fino"]["segundos_por_midia"] == 190           # 95 × 12/6
    # ⛔ E o teto do motor aparece como `quadros_efetivos`, sem o nível sumir da lista: o
    #   editor precisa ver que pediu 24 e vai receber 22.
    assert mac["exaustivo"]["quadros"] == 24
    assert mac["exaustivo"]["quadros_efetivos"] == 22
    assert mac["exaustivo"]["segundos_por_midia"] == round(95 * 22 / 6)
    assert claude["exaustivo"]["quadros_efetivos"] == 24


def test_a_rota_publica_os_niveis(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    monkeypatch.setattr("cicloassist.motor.percepcao.endereco", lambda: "")
    d = json.loads(R.rota_vetores(Pedido("GET", "/vetores", {}, b"", {})).corpo)

    assert d["densidade"]["padrao"] == D.DENSIDADE_PADRAO
    assert set(d["densidade"]["niveis"]) == set(D.DENSIDADES)
    assert d["densidade"]["niveis"]["exaustivo"]["quadros"] == 24


def test_o_contexto_do_ollama_acompanha_o_pedido():
    """⛔⛔ O que passa do `num_ctx` o Ollama corta CALADO: o pedido não falha, o modelo é
    que vê menos do que foi mandado — e a tela continuaria dizendo o número cheio.

    Com a densidade da aba são até 24 quadros por mídia, e seis já são ~6,2 mil tokens:
    o contexto fixo de 12.288 entregaria uma parte deles sem nada acusando.
    """
    from cicloassist.motor import percepcao as P

    assert P.contexto_para(6, 2) >= P.CONTEXTO
    assert P.contexto_para(24, 2) > P.contexto_para(6, 2)
    assert P.contexto_para(24, 2) <= P.CONTEXTO_MAXIMO
    # ⛔ E o que não cabe nem no maior contexto é cortado AQUI, onde dá para contar.
    cabem = P.quadros_que_cabem(2)
    assert 6 <= cabem < 100
    assert P.contexto_para(cabem, 2) <= P.CONTEXTO_MAXIMO


def test_o_mac_diz_quantos_quadros_olhou_de_verdade(tmp_path, monkeypatch):
    """⚠️ A nota grava o que ele OLHOU, não o que foi pedido: no Mac o teto do contexto
    pode ter levado menos, e a procedência não pode prometer o número da tela."""
    from cicloassist.motor import percepcao as P

    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    vistos = []
    monkeypatch.setattr("cicloassist.mcp.ferramentas.midia.quadros_de",
                        lambda chave, quantos: (vistos.append(quantos) or
                                                ([b"\xff\xd8x"] * quantos, [0] * quantos,
                                                 {"fps": "25"})))
    monkeypatch.setattr("cicloassist.mcp.ferramentas.midia.quadros_da_cabeca",
                        lambda chave: ([], []))
    monkeypatch.setattr(P, "pedir", lambda *a, **k: {
        "message": {"content": json.dumps({"descricao": "um plano qualquer"})}})

    feito = P.decupar("http://192.168.1.4:11434", "a" * 64, quadros=1000)

    assert vistos == [P.quadros_que_cabem(2)], "o pedido é cortado no que cabe"
    assert feito["quadros"] == P.quadros_que_cabem(2)


@pytest.mark.parametrize("nivel,esperado", [("macro", 6), ("fino", 12), ("exaustivo", 24)])
def test_o_nivel_chega_ao_motor_do_claude(tmp_path, monkeypatch, nivel, esperado):
    """⭐ O que a fila manda olhar é o que o editor escolheu — e o pedido ao modelo diz o
    número, porque é ele quem chama a ferramenta."""
    pedidos = []

    def falso_decupar(itens, url_do_mcp, quadros=D.QUADROS, modelo="", timeout_s=480.0):
        pedidos.append(quadros)
        return {"notas": {}, "uso": {}, "segundos": 0.0}

    monkeypatch.setattr(D, "decupar", falso_decupar)
    _rodar_a_fila(tmp_path, monkeypatch, nivel)
    assert pedidos == [esperado]


def test_o_nivel_chega_ao_motor_do_mac(tmp_path, monkeypatch):
    """⭐ O Mac não cobra dólar, mas cobra TEMPO — e "olhei 24 quadros" é a mesma decisão
    do editor dos dois lados."""
    from cicloassist.motor import percepcao as P
    pedidos = []

    def falso_decupar(url, chave, modelo=P.MODELO, prazo=P.PRAZO_S, quadros=0):
        pedidos.append(quadros)
        return {"notas": {}, "uso": {}, "segundos": 0.0}

    monkeypatch.setattr(P, "endereco", lambda: "http://192.168.1.4:11434")
    monkeypatch.setattr(P, "conferir", lambda url: None)
    monkeypatch.setattr(P, "decupar", falso_decupar)
    _rodar_a_fila(tmp_path, monkeypatch, "fino")
    assert pedidos == [12]


def _rodar_a_fila(tmp_path, monkeypatch, nivel: str) -> None:
    """Uma mídia de imagem no acervo, e a fila de decupagem correndo até o fim."""
    import time as _time

    from cicloassist.midia import acervo as A
    from cicloassist.midia import cache as C
    from cicloassist.servico import tarefas as T

    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    chave = C.de_umid(
        "0x060A2B340101010101010F0013000000C6D91F0BB8ABB1C7ABEE2FFBA70D1E05")
    video = tmp_path / "v.mxf"
    video.write_bytes(b"x")
    A.guardar("D:/mídia/x", [A.Clipe(chave, "A001_C003", [str(video)], {"video": 1},
                                     fps="24000/1001", duracao_s=10.0,
                                     por_tipo={"video": [str(video)]})], raiz=tmp_path)
    T.esquecer()
    try:
        r = R.rota_analisar(Pedido("POST", "/vetores/analisar", {}, json.dumps(
            {"estagio": "decupagem", "densidade": nivel}).encode("utf-8")))
        assert json.loads(r.corpo)["ok"], r.corpo
        limite = _time.time() + 5
        while T.ha_tarefa_viva() and _time.time() < limite:
            _time.sleep(0.01)
        assert not T.ha_tarefa_viva(), "a tarefa não terminou"
    finally:
        T.parar()
        T.esquecer()
