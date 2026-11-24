"""A timeline do editor no Premiere SEM o MCP nativo (2025/2026), pela ponte CEP — F7.

A ponte é falsa: `ponte.chamar` responde como o `host.jsx` respondeu no 26.0.2 (2026-11-07). O
Premiere de verdade foi medido à parte (o roteiro está no plano, §16).
"""
from __future__ import annotations

import pytest

from cicloassist import nle
from cicloassist.mcp.ferramentas import edicao as F
from cicloassist.mcp.ferramentas import monitor
from cicloassist.nle.premiere import edicao_cep as C
from cicloassist.nle.premiere import ponte

Q = 10160640000          # ticks de um quadro a 25 fps


def _it(tipo, trilha, ini, inp, dur, clipe="A.mov", node=None, extra=0):
    return {"tipo": tipo, "trilha": trilha, "clipe": clipe, "node": node or f"{tipo}{trilha}{ini}",
            "ini": str(ini * Q + extra), "inp": str(inp * Q), "dur": str(dur * Q)}


BASE = {"sequencia": "CENA", "id": "seq-1", "quadro": str(Q), "fim": str(100 * Q),
        "itens": [_it("video", 0, 0, 50, 50), _it("video", 0, 50, 200, 50),
                  _it("audio", 0, 0, 50, 50), _it("audio", 0, 50, 200, 50)]}


@pytest.fixture
def premiere(monkeypatch):
    nle.definir("premiere")
    monkeypatch.setattr(ponte, "painel_vivo", lambda: True)
    yield
    nle.definir("avid")


def _ponte(monkeypatch, respostas: dict):
    chamadas = []

    def chamar(funcao, *args, prazo=0):
        chamadas.append((funcao, args))
        r = respostas[funcao]
        return r(*args) if callable(r) else r
    monkeypatch.setattr(ponte, "chamar", chamar)
    return chamadas


def test_ler_converte_ticks_em_quadros_e_timecode(premiere, monkeypatch):
    _ponte(monkeypatch, {"cicloLerSequencia": BASE})
    r = F.ler_timeline(sequencia="CENA")
    assert r["fps"] == 25.0 and r["duracao"] == "00:00:04:00"
    v1 = next(t for t in r["trilhas"] if t["trilha"] == "V1")["clipes"]
    assert v1[1] == {"de": "00:00:02:00", "ate": "00:00:04:00", "de_quadro": 50, "ate_quadro": 100,
                     "clipe": "A.mov", "in_no_clipe": 200,
                     "duracao_frames": 50}


def test_23976_tem_taxa_exata():
    assert C._fps("10594584000") == pytest.approx(24000 / 1001)
    assert C._t(1, C._fps("10594584000")) == "10594584000"


def test_conferir_recusa_som_em_trilhas_salteadas(premiere, monkeypatch):
    _ponte(monkeypatch, {"cicloLerSequencia": BASE, "cicloTemClipe": {"ok": True}})
    r = F.conferir_a_edicao(sequencia="CENA", operacoes=[
        {"tipo": "inserir", "em": "00:00:01:00", "duracao_frames": 5, "clipe": "B.wav", "som_em": ["A3", "A5"]}])
    assert r["pode"] is False and "SEGUIDAS" in r["motivo"]


def test_conferir_recusa_clipe_que_nao_existe(premiere, monkeypatch):
    _ponte(monkeypatch, {"cicloLerSequencia": BASE, "cicloTemClipe": {"ok": False}})
    r = F.conferir_a_edicao(sequencia="CENA", operacoes=[
        {"tipo": "inserir", "em": "00:00:01:00", "duracao_frames": 5, "clipe": "X.mov", "imagem_em": "V2"}])
    assert r["pode"] is False and "X.mov" in r["motivo"]


def test_conferencia_sem_ponte_nao_barra_o_cartao(premiere, monkeypatch):
    def caiu(*a, **k):
        raise ponte.PremiereIndisponivel("painel fechado")
    monkeypatch.setattr(ponte, "chamar", caiu)
    assert C.conferir("CENA", [{"tipo": "extrair", "de": "00:00:00:10", "ate": "00:00:00:20"}]) == ""


def test_editar_manda_ticks_exatos_da_ultima_para_a_primeira(premiere, monkeypatch):
    feito = {"copia": "CENA ED", "id": "seq-2", "anterior": "seq-1", "quadro": str(Q), "itens": [
        _it("video", 0, 0, 50, 10), _it("video", 0, 10, 70, 30), _it("video", 0, 40, 200, 10),
        _it("video", 0, 55, 210, 40),
        _it("audio", 0, 0, 50, 10), _it("audio", 0, 10, 70, 30), _it("audio", 0, 40, 200, 10),
        _it("audio", 0, 55, 210, 40)]}
    ch = _ponte(monkeypatch, {"cicloLerSequencia": BASE, "cicloEditar": feito})
    r = F.editar_timeline(sequencia="CENA", nome_da_copia="CENA ED", operacoes=[
        {"tipo": "extrair", "de": "00:00:00:10", "ate": "00:00:00:20"},
        {"tipo": "abrir_espaco", "em": "00:00:02:10", "duracao_frames": 5}])
    assert r["ok"] is True, r
    plano = next(a[0] for f, a in ch if f == "cicloEditar").split("\n")
    assert plano[0] == "seq\tseq-1\tCENA ED"
    assert plano[1] == f"e\t{60 * Q}\t{5 * Q}"          # a de 00:00:02:10 vem primeiro
    assert plano[2] == f"x\t{10 * Q}\t{20 * Q}"


def test_prova_que_falha_apaga_a_copia_e_reabre_a_original(premiere, monkeypatch):
    feito = {"copia": "CENA ED", "id": "seq-2", "anterior": "seq-1", "quadro": str(Q),
             "itens": [_it("video", 0, 0, 50, 10)]}           # sumiu tudo o que não foi tocado
    ch = _ponte(monkeypatch, {"cicloLerSequencia": BASE, "cicloEditar": feito,
                              "cicloApagarSequencia": {"ok": True}})
    r = F.editar_timeline(sequencia="CENA", operacoes=[{"tipo": "extrair", "de": "00:00:00:10", "ate": "00:00:00:20"}])
    assert "NÃO passou na prova e foi apagada" in r["erro"]
    assert ("cicloApagarSequencia", ("seq-2", "seq-1")) in ch


def test_item_um_tick_fora_do_quadro_reprova(premiere, monkeypatch):
    """⛔⛔ O defeito medido em 2026-11-07: o `move` por segundos deixava o item 1 tick depois do quadro,
    a prova (que arredonda) aprovava, e o Premiere mostrava o quadro ANTERIOR à entrada."""
    itens = [dict(x) for x in BASE["itens"]]
    feito = {"copia": "CENA ED", "id": "seq-2", "anterior": "seq-1", "quadro": str(Q),
             "itens": [_it("video", 0, 0, 50, 50), _it("video", 0, 55, 200, 50, extra=1),
                       _it("audio", 0, 0, 50, 50), _it("audio", 0, 55, 200, 50)]}
    _ponte(monkeypatch, {"cicloLerSequencia": dict(BASE, itens=itens), "cicloEditar": feito,
                         "cicloApagarSequencia": {"ok": True}})
    r = F.editar_timeline(sequencia="CENA", operacoes=[{"tipo": "abrir_espaco", "em": "00:00:02:00",
                                                         "duracao_frames": 5}])
    assert "fora da grade" in r["erro"]


def test_inserir_leva_as_trilhas_como_indices(premiere, monkeypatch):
    feito = {"copia": "C", "id": "s2", "quadro": str(Q), "itens": BASE["itens"]}
    ch = _ponte(monkeypatch, {"cicloLerSequencia": BASE, "cicloEditar": feito, "cicloTemClipe": {"ok": True}})
    F.editar_timeline(sequencia="CENA", operacoes=[
        {"tipo": "inserir", "em": "00:00:04:00", "duracao_frames": 10, "clipe": "B.wav", "in_no_clipe": 250,
         "som_em": ["A3", "A4", "A5"]}])
    linha = next(a[0] for f, a in ch if f == "cicloEditar").split("\n")[1].split("\t")
    assert linha == ["i", str(100 * Q), str(10 * Q), "B.wav", str(250 * Q), str(260 * Q), "-1", "2", "3"]


def test_a_tela_pela_ponte(premiere, monkeypatch):
    _ponte(monkeypatch, {"cicloTela": {
        "program": {"nome": "CENA", "id": "seq-1", "quadro": str(Q), "agulha": str(30 * Q),
                    "entrada": "-101606400000000000", "saida": None, "selecionados": 2},
        "source": {"nome": "A.mov", "id": "000f", "agulha": str(12 * Q)}}})
    r = monitor.o_que_esta_na_tela()
    prog = next(m for m in r["monitores"] if m["monitor"] == "program")
    assert prog["timecode"] == "00:00:01:05" and "entrada" not in prog
    assert r["selecionados_na_timeline"] == 2
    src = next(m for m in r["monitores"] if m["monitor"] == "source")
    assert src["segundos"] == pytest.approx(0.48)


def test_sem_mcp_e_sem_ponte_diz_o_gesto(premiere, monkeypatch):
    monkeypatch.setattr(ponte, "painel_vivo", lambda: False)
    assert "abrir o Premiere com o Ciclo Assist" in F.ler_timeline(sequencia="CENA")["erro"]
    assert "abrir o Premiere com o Ciclo Assist" in monitor.o_que_esta_na_tela()["erro"]


def test_acrescentar_falas_le_a_bin_pela_via_que_existe(monkeypatch):
    """⛔ Pelo chat no 2026 (2026-11-07): o `acrescentar_em` lia a bin de falas SÓ pelo MCP, passava no
    cartão e falhava depois do clique. Agora pela árvore que escolhe a via."""
    from cicloassist.mcp.ferramentas import falas
    from cicloassist.nle import premiere as P
    monkeypatch.setattr(P, "arvore", lambda: [
        {"nome": "C04 FALAS", "id": "1", "especie": "bin", "bin": ""},
        {"nome": "C04_FALA01 - Eu sou Personagem F.", "id": "2", "especie": "sequencia", "bin": "C04 FALAS"},
        {"nome": "C04_FALA02.02 - Ah, então…", "id": "3", "especie": "sequencia", "bin": "C04 FALAS"},
        {"nome": "C05_FALA01 - Outra cena", "id": "4", "especie": "sequencia", "bin": "C04 FALAS"}])
    assert falas._ja_na_bin_no_premiere("C04 FALAS", "C04") == {(1, 1): "Eu sou Personagem F.", (2, 2): "Ah, então…"}
    with pytest.raises(Exception, match="não achei a bin"):
        falas._ja_na_bin_no_premiere("NAO HA", "C04")
