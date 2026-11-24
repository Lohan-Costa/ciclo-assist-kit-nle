"""A via MCP nativa do Premiere (27.1+) — plano `docs/plano/2026-11-06-mcp-do-premiere.md` F1.

Um servidor MCP FALSO (stdlib, SSE como o do Premiere) responde às ações; o Premiere de verdade
nunca é tocado (ver `sem_mcp_do_premiere` no conftest).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cicloassist.nle import premiere
from cicloassist.nle.premiere import mcp_nativo, ponte


class Falso:
    """O estado do servidor falso: as ações que ele tem e o que cada uma responde."""

    def __init__(self) -> None:
        self.acoes: dict[str, object] = {}
        self.pedidos: list[tuple[str, dict]] = []
        self.exige_token = ""


def _servidor(falso: Falso):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silêncio na suíte
            pass

        def do_POST(self):  # noqa: N802
            corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            if falso.exige_token and self.headers.get("Authorization") != f"Bearer {falso.exige_token}":
                self.send_response(401); self.end_headers(); return
            metodo, rid = corpo.get("method"), corpo.get("id")
            if rid is None:  # notificação
                self.send_response(202); self.end_headers(); return
            if metodo == "initialize":
                res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                       "serverInfo": {"name": "Premiere MCP Server", "version": "falso"}}
            elif metodo == "tools/list":
                res = {"tools": [{"name": n, "inputSchema": {"type": "object"}} for n in falso.acoes]}
            elif metodo == "tools/call":
                nome, args = corpo["params"]["name"], corpo["params"].get("arguments") or {}
                falso.pedidos.append((nome, args))
                r = falso.acoes[nome]
                r = r(args) if callable(r) else r
                res = {"content": [{"type": "text", "text": json.dumps(r)}], "structuredContent": r}
            else:
                res = {}
            dados = f"data: {json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': res})}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("mcp-session-id", "sessao-falsa")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
    return H


@pytest.fixture
def mcp(monkeypatch):
    falso = Falso()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _servidor(falso))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("CICLOASSIST_PREMIERE_MCP", f"http://127.0.0.1:{srv.server_address[1]}/premiere/mcp")
    monkeypatch.setenv("CICLOASSIST_PREMIERE_VIA", "auto")
    mcp_nativo.esquecer()
    premiere.esquecer()
    yield falso
    srv.shutdown()


PROJETO = {"projects": [{"agentProjectId": "p1", "isActive": True, "name": "X.prproj", "path": "/p/X.prproj"},
                        {"agentProjectId": "p2", "isActive": False, "name": "Y.prproj", "path": "/p/Y.prproj"}]}


def _projeto_completo(falso: Falso) -> None:
    falso.acoes.update({
        "getOpenProjects": PROJETO,
        "getEditingContext": {"programMonitor": {"agentProjectId": "p1", "sequenceId": "s1", "name": "SEQ"}},
        "getSequenceStructure": {"videoFrameRate": 23.976, "tracks": []},
        "getProjectItems": lambda a: (
            {"items": [{"itemId": "b", "name": "CENAS", "path": "CENAS", "type": "bin"},
                       {"itemId": "c1", "name": "A.mp4", "path": "CENAS/A.mp4", "type": "clip"}],
             "hasMore": True, "nextCursor": "2"} if not a.get("cursor") else
            {"items": [{"itemId": "c2", "name": "A sub", "path": "OUTRA/A sub", "type": "clip"},
                       {"itemId": "m", "name": "M - Merged", "path": "M - Merged", "type": "sequence"},
                       {"itemId": "c3", "name": "B.wav", "path": "B.wav", "type": "clip"}], "hasMore": False}),
        "getClipMetadata": lambda a: {"results": [
            {"itemId": i, "values": [{"field": "filePath",
                                      "value": {"c1": "/m/A.mp4", "c2": "/m/A.mp4", "c3": "/m/B.wav"}[i]}]}
            for i in a["itemIds"]], "hasMore": False},
    })


def test_sem_servidor_a_via_e_a_cep(monkeypatch):
    monkeypatch.setenv("CICLOASSIST_PREMIERE_VIA", "auto")
    mcp_nativo.esquecer()
    assert mcp_nativo.disponivel() is False
    assert mcp_nativo.via("midias") == "cep"
    assert set(mcp_nativo.situacao()["vias"].values()) == {"cep"}


def test_sem_servidor_a_sonda_espera_mais(monkeypatch):
    """No Windows cada sonda sem servidor custa o prazo inteiro (1,5 s): não pode acontecer a cada `/conexao`."""
    from types import SimpleNamespace
    relogio, sondas = [1000.0], []
    monkeypatch.setattr(mcp_nativo, "time", SimpleNamespace(monotonic=lambda: relogio[0]))
    monkeypatch.setattr(mcp_nativo, "_sondar", lambda: sondas.append(relogio[0]))
    mcp_nativo.esquecer()
    mcp_nativo.acoes()
    relogio[0] += 15
    mcp_nativo.acoes()
    assert len(sondas) == 1                    # o painel pergunta a cada 15 s: esta não sonda
    relogio[0] += 45
    mcp_nativo.acoes()
    assert len(sondas) == 2
    mcp_nativo._e.acoes = frozenset({"x"})     # com servidor no ar, vale a validade curta
    relogio[0] += 15
    mcp_nativo.acoes()
    assert len(sondas) == 3
    mcp_nativo.esquecer()


def test_a_via_e_por_capacidade_nao_por_versao(mcp):
    """Faltou UMA ação da operação, ela fica na CEP — e a outra operação pode ir pelo MCP."""
    _projeto_completo(mcp)
    del mcp.acoes["getClipMetadata"]
    mcp_nativo.esquecer()
    assert mcp_nativo.via("projeto") == "mcp"
    assert mcp_nativo.via("midias") == "cep"


def test_estado_no_formato_do_cicloProjeto_com_a_taxa_exata(mcp):
    _projeto_completo(mcp)
    e = premiere.estado()
    assert e["caminho"] == "/p/X.prproj" and e["nome"] == "X.prproj"
    assert e["sequencia_ativa"] == {"nome": "SEQ", "id": "s1"}
    # ⛔ 23,976 é 24000/1001, nunca 23976/1000 (erraria o TC em ~3,6 s por hora)
    assert e["fps"] == {"num": "24000", "den": "1001"}
    from cicloassist.midia import timecode
    assert timecode.taxa_do_projeto(e) == __import__("fractions").Fraction(24000, 1001)


def test_projeto_aberto_pelo_mcp_sem_painel_cep(mcp, monkeypatch):
    _projeto_completo(mcp)
    monkeypatch.setattr(ponte, "painel_vivo", lambda: False)
    assert premiere.projeto_aberto() == "/p/X.prproj"
    assert premiere.alcancavel() is True


def test_midias_juntam_as_paginas_e_as_bins_e_deixam_merged_de_fora(mcp):
    _projeto_completo(mcp)
    r = premiere._midias()
    assert r["arquivos"] == ["/m/A.mp4", "/m/B.wav"]
    a = r["itens"][0]
    # o master e o subclipe são o MESMO arquivo: uma linha, as duas bins
    assert a["arquivo"] == "/m/A.mp4" and a["bins"] == ["CENAS", "OUTRA"]
    assert r["itens"][1]["bins"] == [""]      # na raiz
    # o merged (type sequence) não foi nem perguntado
    pedidos = [args for nome, args in mcp.pedidos if nome == "getClipMetadata"]
    assert "m" not in pedidos[0]["itemIds"]


def test_falha_do_mcp_cai_para_a_cep_sem_erro_para_o_editor(mcp, monkeypatch):
    _projeto_completo(mcp)
    mcp.acoes["getProjectItems"] = lambda a: (_ for _ in ()).throw(RuntimeError("quebrou"))
    chamadas = []
    monkeypatch.setattr(ponte, "chamar", lambda f, *a, **k: chamadas.append(f) or {"arquivos": ["/cep.mov"]})
    assert premiere._midias()["arquivos"] == ["/cep.mov"]
    assert chamadas == ["cicloMidias"]


def test_via_forcada_cep_nunca_fala_com_o_mcp(mcp, monkeypatch):
    _projeto_completo(mcp)
    monkeypatch.setenv("CICLOASSIST_PREMIERE_VIA", "cep")
    monkeypatch.setattr(ponte, "chamar", lambda f, *a, **k: {"caminho": "/cep/Z.prproj"})
    assert premiere.estado()["caminho"] == "/cep/Z.prproj"
    assert mcp.pedidos == []


def test_contador_da_vigia_muda_quando_entra_clipe(mcp):
    _projeto_completo(mcp)
    antes = premiere.contador_da_vigia()
    velho = mcp.acoes["getProjectItems"]
    mcp.acoes["getProjectItems"] = lambda a: (lambda r: {**r, "items": r["items"] + (
        [{"itemId": "c9", "name": "N.mp4", "path": "N.mp4", "type": "clip"}] if not r.get("hasMore") else [])})(velho(a))
    assert premiere.contador_da_vigia() != antes


def test_senha_vai_no_cabecalho_e_nunca_falta_em_silencio(mcp, monkeypatch):
    _projeto_completo(mcp)
    mcp.exige_token = "segredo"
    mcp_nativo.esquecer()
    assert mcp_nativo.disponivel() is False            # sem token: pediu senha → CEP
    assert "senha" in mcp_nativo.situacao()["erro"]
    monkeypatch.setenv("CICLOASSIST_PREMIERE_MCP_TOKEN", "segredo")
    mcp_nativo.esquecer()
    assert mcp_nativo.via("projeto") == "mcp"
    assert "segredo" not in json.dumps(mcp_nativo.situacao())


@pytest.mark.parametrize("fps,par", [(23.976, (24000, 1001)), (29.97, (30000, 1001)), (59.94, (60000, 1001)),
                                     (25, (25, 1)), (24.0, (24, 1)), (None, None), (0, None)])
def test_taxa_exata(fps, par):
    assert mcp_nativo.taxa_exata(fps) == par


def test_montagem_sem_mcp_e_sem_ponte_diz_o_gesto(monkeypatch):
    """Sem o MCP (versão antiga) E sem a ponte do painel: a frase diz o que falta."""
    from cicloassist import nle
    from cicloassist.mcp.ferramentas import corte
    monkeypatch.setattr(nle, "_atual", "premiere")
    monkeypatch.setattr(ponte, "painel_vivo", lambda: False)
    r = corte.montar_corte(bin="B", nome="X", cortes=[{"take": "a", "duracao_frames": 10,
                           "confianca": "inferido", "fonte": "visual", "porque": "t"}])
    assert "27.1" in r["erro"] and "ponte" in r["erro"]


def _take_falso(nome, imagem=True, som=True):
    from types import SimpleNamespace
    return SimpleNamespace(nome=nome, mob_id=f"id-{nome}", imagem=object() if imagem else None,
                           som=object() if som else None, fps={"num": 25, "den": 1})


def test_montagem_pela_ponte_nas_versoes_antigas(monkeypatch):
    """F6: sem MCP, o plano vai ao `cicloMontar` como TEXTO tabulado e volta conferido pelos ticks."""
    from cicloassist import nle
    from cicloassist.mcp.ferramentas import corte
    from cicloassist.nle import premiere as P
    monkeypatch.setattr(nle, "_atual", "premiere")
    monkeypatch.setattr(ponte, "painel_vivo", lambda: True)
    monkeypatch.setattr(P, "resolver_take", lambda b, n: _take_falso(n))
    T = 254016000000 // 25    # ticks por quadro a 25 fps
    pedidos = []

    def chamar(funcao, texto, prazo=0):
        pedidos.append((funcao, texto))
        return {"sequencia": "X", "id": "s1", "itens": [
            {"tipo": "v", "trilha": 0, "nome": "a", "ini": "0", "inp": str(50 * T), "dur": str(10 * T)},
            {"tipo": "a", "trilha": 0, "nome": "a", "ini": "0", "inp": str(50 * T), "dur": str(10 * T)},
            {"tipo": "a", "trilha": 1, "nome": "a", "ini": "0", "inp": str(50 * T), "dur": str(10 * T)}]}
    monkeypatch.setattr(ponte, "chamar", chamar)
    r = corte.montar_corte(bin="CENAS", nome="X", bin_da_sequencia="CORTES", cortes=[
        {"take": "a", "inicio_no_take": 50, "duracao_frames": 10, "confianca": "inferido", "fonte": "visual", "porque": "t"}])
    assert r["ok"] and "ponte" in r["via"] and r["conferidos"].startswith("3 de 3")
    funcao, texto = pedidos[0]
    assert funcao == "cicloMontar"
    linhas = texto.split("\n")
    assert linhas[0] == "seq\tX\tCORTES"
    campos = linhas[1].split("\t")
    assert campos[0] == "p" and campos[1] == "id-a" and campos[5] == "1"
    assert abs(float(campos[2]) - (2.0 + 1e-6)) < 1e-7      # quadro 50 a 25 fps, +1 µs


def test_montagem_pela_ponte_recusa_l_e_j(monkeypatch):
    """⛔ Autor, 2026-11-06: L/J fica com o editor — o caminho novo não monta."""
    from cicloassist import nle
    from cicloassist.mcp.ferramentas import corte
    from cicloassist.nle import premiere as P
    monkeypatch.setattr(nle, "_atual", "premiere")
    monkeypatch.setattr(ponte, "painel_vivo", lambda: True)
    monkeypatch.setattr(P, "resolver_take", lambda b, n: _take_falso(n))
    r = corte.montar_corte(bin="B", nome="X", cortes=[
        {"take": "a", "duracao_frames": 20, "confianca": "inferido", "fonte": "visual", "porque": "t"},
        {"take": "b", "inicio_no_take": 30, "duracao_frames": 20, "corte_de_som": "antes", "som_frames": 4,
         "confianca": "inferido", "fonte": "visual", "porque": "t"}])
    assert "L/J" in r["erro"] and "editor" in r["erro"]


def test_montagem_pela_ponte_diz_o_pedaco_fora_do_quadro(monkeypatch):
    from cicloassist.nle.premiere import montagem as G
    from cicloassist.nle.premiere import montagem_cep as C
    T = 254016000000 // 25
    monkeypatch.setattr(ponte, "chamar", lambda f, t, prazo=0: {"id": "s", "itens": [
        {"tipo": "v", "trilha": 0, "nome": "a", "ini": "0", "inp": str(49 * T), "dur": str(10 * T)}]})
    r = C.montar("X", [G.Pedaco("a", "a", 50, 10, 50, 10, 0, 0)], __import__("fractions").Fraction(25))
    assert r.divergencias and "esperava entrada 50" in r.divergencias[0]


def test_pedacos_do_plano_mesma_conta_de_l_e_j_do_avid():
    """A maquinaria de L/J ficou de pé (sem caminho de entrada desde 2026-11-07): a conta continua certa."""
    from cicloassist.mcp.ferramentas import corte
    from cicloassist.plano import esquema
    plano = esquema.Plano(bin="B", nome="N", cortes=[
        esquema.Corte(take="a", inicio_no_take=100, duracao_frames=40, porque="x"),
        esquema.Corte(take="b", inicio_no_take=10, duracao_frames=30, porque="y", corte_de_som="antes", som_frames=6)])
    p = corte.pedacos_do_plano(plano, lambda nome: (nome, True, True))
    a, b = p
    # J: o som de b entra 6 quadros ANTES da imagem dele, e o som de a encurta 6
    assert (a.pos_v, a.v_in, a.v_dur, a.pos_a, a.a_in, a.a_dur) == (0, 100, 40, 0, 100, 34)
    assert (b.pos_v, b.v_in, b.v_dur, b.pos_a, b.a_in, b.a_dur) == (40, 10, 30, 34, 4, 36)


def test_arvore_e_organizar_pelo_mcp_com_ids_do_mcp(mcp):
    """F2: a árvore mostra ids do MCP, e o organizar aceita esses ids — o fluxo inteiro numa via."""
    estado = {"items": [{"itemId": "B1", "name": "CENAS", "path": "CENAS", "type": "bin"},
                        {"itemId": "C1", "name": "A.mp4", "path": "CENAS/A.mp4", "type": "clip"}]}
    mcp.acoes.update({
        "getOpenProjects": PROJETO,
        "getEditingContext": {"projectPanelSelection": [{"agentProjectId": "p1", "itemId": "C1"}]},
        "getSequenceStructure": {"items": []},
        "getProjectItems": lambda a: {"items": estado["items"], "hasMore": False},
        "getClipMetadata": lambda a: {"results": [{"itemId": "C1", "values": [{"field": "filePath", "value": "/m/A.mp4"}]}],
                                      "hasMore": False},
        "createBins": lambda a: estado["items"].append(
            {"itemId": "B2", "name": a["names"][0], "path": "CENAS/" + a["names"][0], "type": "bin"}) or {"errorCount": 0},
        "moveOrCopyProjectItems": lambda a: [i.update(path="CENAS/NOVA/A.mp4") for i in estado["items"]
                                             if i["itemId"] == a["items"][0]["itemId"]] and {"errorCount": 0},
        "renameProjectItems": lambda a: {"errorCount": 0},
        "deleteProjectItems": lambda a: {"errorCount": 0},
    })
    mcp_nativo.esquecer()
    arv = premiere.arvore()
    assert {(i["id"], i["especie"], i["bin"]) for i in arv} == {("B1", "bin", ""), ("C1", "clipe", "CENAS")}
    assert [i["nome"] for i in premiere.selecao()] == ["A.mp4"]
    r = premiere.organizar([{"acao": "criar_bin", "nome": "NOVA", "dentro_de": "CENAS"},
                            {"acao": "mover", "item": "C1", "para": "CENAS/NOVA"}])
    assert r["falharam"] == [] and r["feitas"] == 2
    mover = [a for n, a in mcp.pedidos if n == "moveOrCopyProjectItems"][0]
    assert mover["items"][0] == {"itemId": "C1", "parentId": "B2"}
