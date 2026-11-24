"""O que dá para testar sem o Avid aberto e sem gastar um turno do modelo.

A suíte cobre o protocolo e as regras; os spikes cobrem a integração. Manter os dois
separados é o que permite rodar isto num CI que não tem Media Composer nem assinatura.
"""

from __future__ import annotations

import pytest

from cicloassist.mcp import ferramentas  # noqa: F401  (registra por import)
from cicloassist.mcp import registro, servidor
from cicloassist.servico import http, rotas


# ── o registro ───────────────────────────────────────────────────────────────

def test_registro_recusa_nome_repetido():
    """Sobrescrita silenciosa é o pior modo de falha: tudo sobe, a errada responde."""
    with pytest.raises(ValueError, match="já registrada"):

        @registro.ferramenta(nome="listar_bins", descricao="colidente", escreve=False)
        def _colidente():  # pragma: no cover
            return {}


def test_allowlist_traz_so_leitura_com_o_prefixo_do_cli():
    nomes = registro.somente_leitura()
    assert "mcp__ciclo__listar_bins" in nomes
    escritoras = {f.nome for f in registro.FERRAMENTAS.values() if f.escreve}
    assert not [n for n in nomes if n.removeprefix("mcp__ciclo__") in escritoras]


def test_toda_ferramenta_tem_descricao_util():
    """Descrição é o que o modelo lê para decidir chamar. Curta demais é bug."""
    for f in registro.FERRAMENTAS.values():
        assert len(f.descricao) > 40, f"{f.nome} tem descrição curta demais"
        assert f.esquema["type"] == "object"


# ── o protocolo ──────────────────────────────────────────────────────────────

def test_initialize_devolve_capacidade_de_ferramentas():
    r = servidor.responder({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r["result"]["protocolVersion"] == servidor.PROTOCOLO
    assert "tools" in r["result"]["capabilities"]


def test_notificacao_nao_tem_resposta():
    """Responder uma notificação quebra o cliente. Sem `id`, sem resposta."""
    assert servidor.responder({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_expoe_o_registro_do_editor_da_conversa(monkeypatch):
    """Cada editor vê as suas; as de mídia estão nos dois (P2 do Premiere)."""
    from cicloassist import nle

    listas = {}
    for editor in nle.TODOS:
        monkeypatch.setattr(nle, "_atual", editor)
        r = servidor.responder({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listas[editor] = {t["name"] for t in r["result"]["tools"]}
    # ⚠️ Menos as de FLUXO, que são da aba Fluxos e não do chat (2026-11-03).
    assert listas["avid"] | listas["premiere"] == set(registro.FERRAMENTAS) - servidor.FORA_DO_CHAT
    comuns = {"ver_frames", "transcrever", "planos_parecidos", "procurar_no_material",
              "consultar_o_metodo", "pedir_confirmacao"}
    assert comuns <= listas["avid"] & listas["premiere"]
    # ⭐ F3 do plano 2026-11-06-mcp-do-premiere: montar e separar falas nos dois editores
    #   (no Premiere pelo MCP nativo); ler/editar a timeline do editor continua só do Avid.
    assert {"montar_corte", "separar_falas"} <= listas["avid"] & listas["premiere"]
    assert {"ler_timeline", "editar_timeline", "o_que_esta_na_tela"} <= listas["premiere"]   # F4
    assert "listar_bins_do_premiere" not in listas["avid"]


def test_ferramenta_do_outro_editor_e_recusada(monkeypatch):
    from cicloassist import nle

    monkeypatch.setattr(nle, "_atual", "premiere")
    r = servidor.responder({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "listar_bins", "arguments": {}}})
    assert r["result"]["isError"]
    assert "Premiere" in r["result"]["content"][0]["text"]


def test_metodo_desconhecido_com_id_vira_erro():
    r = servidor.responder({"jsonrpc": "2.0", "id": 3, "method": "inventado"})
    assert r["error"]["code"] == -32601


def test_metodo_desconhecido_sem_id_e_ignorado():
    assert servidor.responder({"jsonrpc": "2.0", "method": "inventado"}) is None


def test_ferramenta_inexistente_vira_erro_de_parametro():
    r = servidor.responder({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "nao_existe", "arguments": {}},
    })
    assert r["error"]["code"] == -32602


def test_argumento_errado_volta_como_isError_e_nao_como_erro_de_protocolo():
    """O modelo consegue se corrigir se souber o que faltou — mas só se a resposta
    chegar como resultado da ferramenta, não como falha de transporte."""
    r = servidor.responder({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "listar_bins", "arguments": {"parametro_inventado": 1}},
    })
    assert r["result"]["isError"] is True
    assert "argumentos inválidos" in r["result"]["content"][0]["text"]


def test_chamada_boa_devolve_conteudo(tmp_path):
    """Uma bin que não existe ainda é uma CHAMADA bem-sucedida: a ferramenta rodou e
    explicou. `isError` marca falha de execução, não resposta negativa — e a distinção
    importa porque o modelo age diferente nos dois casos."""
    r = servidor.responder({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "resolver_take",
                   "arguments": {"bin": str(tmp_path / "nao" / "existe.avb"),
                                     "item": "qualquer"}},
    })
    assert r["result"]["isError"] is False
    assert "não achei a bin" in r["result"]["content"][0]["text"]


# ── a normalização de conteúdo ───────────────────────────────────────────────

def test_texto_vira_bloco_de_texto():
    assert servidor.normalizar("oi") == [{"type": "text", "text": "oi"}]


def test_dicionario_comum_vira_json_legivel():
    blocos = servidor.normalizar({"quantidade": 2})
    assert blocos[0]["type"] == "text"
    assert "quantidade" in blocos[0]["text"]


def test_bloco_de_imagem_atravessa_intacto():
    """⭐ É por aqui que a identificação visual funciona: o frame chega ao modelo como
    IMAGEM no resultado da ferramenta. Se `normalizar` embrulhasse isso em JSON, o
    Claude receberia a descrição de uma imagem em vez da imagem."""
    imagem = {"type": "image", "data": "iVBOR...", "mimeType": "image/png"}
    assert servidor.normalizar(imagem) == [imagem]
    assert servidor.normalizar([imagem, imagem]) == [imagem, imagem]


# ── o endereço que vai para o CLI ────────────────────────────────────────────

def test_url_do_mcp_aponta_para_loopback():
    """Nunca 0.0.0.0: este serviço dispara ações no projeto do editor."""
    url = rotas.url_do_mcp()
    assert url.startswith("http://127.0.0.1:")


def test_url_do_mcp_carrega_o_segredo_no_caminho():
    """ADR 0005: o subprocesso do Claude não manda Sec-Fetch-Site nem Origin, então o
    porteiro dele é o segredo do caminho. Sem isso, uma página web aberta no navegador
    do editor chamaria as nossas ferramentas."""
    assert http.SEGREDO_DO_MCP in rotas.url_do_mcp()
    assert len(http.SEGREDO_DO_MCP) >= 24


def test_porta_nao_e_a_do_projeto_antigo():
    """7823 era a do Assist anterior E a do De Lá Pra Cá — e o painel de um conversava
    com o serviço do outro. Um produto, uma porta."""
    assert http.PORTA != 7823


# ── a rede contra laço (medida em campo, 2026-09-17) ─────────────────────────

def _chamar(nome, **argumentos):
    return servidor.responder({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                               "params": {"name": nome, "arguments": argumentos}})


def test_a_mesma_leitura_repetida_vira_aviso_em_vez_da_mesma_resposta(monkeypatch):
    """⛔⛔ Em campo: 46 chamadas iguais, 20 minutos, nenhuma resposta ao editor."""
    servidor._repeticoes.clear()
    monkeypatch.setattr(servidor, "_turno_das_repeticoes", "")
    chamadas = []
    monkeypatch.setitem(registro.FERRAMENTAS, "so_leitura", registro.Ferramenta(
        nome="so_leitura", descricao="", esquema={}, escreve=False,
        funcao=lambda **k: chamadas.append(k) or {"quantidade": 0},
        nles=("avid", "premiere")))

    for _ in range(servidor.REPETICOES_ATE_AVISAR - 1):
        assert not _chamar("so_leitura", bin="X")["result"]["isError"]
    barrada = _chamar("so_leitura", bin="X")["result"]
    assert barrada["isError"] and "Pare de repetir" in barrada["content"][0]["text"]
    assert len(chamadas) == servidor.REPETICOES_ATE_AVISAR - 1  # a terceira nem rodou

    # ⭐ Outro argumento é outra pergunta: não é laço.
    assert not _chamar("so_leitura", bin="Y")["result"]["isError"]


def test_pedidos_longos_que_so_diferem_no_fim_nao_sao_laco(monkeypatch):
    """⛔⛔ Ensaio da C07 (2026-10-22): três pedidos de `separar_falas`, cada um corrigido
    depois da conferência, chegaram ao portão com os mesmos 2.000 primeiros caracteres. O
    guarda comparava só esse prefixo, barrou o terceiro como laço, e o modelo passou a
    cortar falas para escapar."""
    servidor._repeticoes.clear()
    monkeypatch.setattr(servidor, "_turno_das_repeticoes", "")
    monkeypatch.setitem(registro.FERRAMENTAS, "portao_falso", registro.Ferramenta(
        nome="portao_falso", descricao="", esquema={}, escreve=False,
        funcao=lambda **k: {"ok": True}, nles=("avid", "premiere")))
    comeco = "x" * 5000
    for n in range(servidor.REPETICOES_ATE_AVISAR + 2):
        assert not _chamar("portao_falso", input=comeco + str(n))["result"]["isError"]


def test_escrita_repetida_nao_e_barrada(monkeypatch):
    """⛔ O portão já segura escrita, e um lote legítimo repete argumentos iguais."""
    servidor._repeticoes.clear()
    monkeypatch.setattr(servidor, "_turno_das_repeticoes", "")
    monkeypatch.setitem(registro.FERRAMENTAS, "escreve_algo", registro.Ferramenta(
        nome="escreve_algo", descricao="", esquema={}, escreve=True,
        funcao=lambda **k: {"ok": True}, nles=("avid", "premiere")))
    for _ in range(servidor.REPETICOES_ATE_AVISAR + 2):
        assert not _chamar("escreve_algo", x=1)["result"]["isError"]


def test_sem_turno_a_conta_zera_com_o_tempo(monkeypatch):
    """⛔ MEDIDO (2026-11-19, o app do Claude pela ponte stdio): sem turno a marca era sempre "" e, depois de 3 chamadas
    iguais na sessão inteira, `estado_do_projeto` ficava recusada até reiniciar o serviço."""
    servidor._repeticoes.clear()
    monkeypatch.setattr(servidor, "_turno_das_repeticoes", "")
    monkeypatch.setitem(registro.FERRAMENTAS, "so_leitura", registro.Ferramenta(
        nome="so_leitura", descricao="", esquema={}, escreve=False,
        funcao=lambda **k: {"ok": True}, nles=("avid", "premiere")))
    agora = [1000.0]
    monkeypatch.setattr(servidor.time, "monotonic", lambda: agora[0])
    for _ in range(servidor.REPETICOES_ATE_AVISAR - 1):
        assert not _chamar("so_leitura")["result"]["isError"]
    assert _chamar("so_leitura")["result"]["isError"]          # laço dentro da janela
    agora[0] += servidor.JANELA_SEM_TURNO_S
    assert not _chamar("so_leitura")["result"]["isError"]      # passou a janela: pergunta nova
