"""⭐⭐ A conversa que continua volta à tela (2026-11-04).

Religado o serviço (ou dado um Reload), a página recomeçava com "esta conversa continua de antes" sobre um
chat vazio: o editor não via o que pediu nem onde o turno parou. `historico.py` guarda o que a tela mostrava.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cicloassist.servico import historico, rotas

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def limpo():
    historico.esquecer()
    yield
    historico.esquecer()


def test_o_turno_e_gravado_ao_comecar_e_a_cada_ferramenta():
    r = historico.Registro("t1", "organize as bins")
    assert historico.ler()[-1]["editor"] == "organize as bins"
    assert historico.ler()[-1]["estado"] == "correndo"
    r.evento("texto", {"texto": "Vou olhar."})
    r.evento("ferramenta", {"nome": "organizar_bins", "resumo": "Organiza as bins"})
    gravado = historico.ler()[-1]
    assert gravado["ferramentas"] == ["Organiza as bins"]
    assert gravado["resposta"] == "Vou olhar."           # a ferramenta grava o texto que veio antes
    r.evento("texto", {"texto": "Pronto."})
    r.terminar()
    fim = historico.ler()[-1]
    assert fim["resposta"] == "Vou olhar.\n\nPronto."     # texto depois de ferramenta é parágrafo novo
    assert fim["estado"] == "pronto"


def test_o_turno_que_morreu_com_o_processo_e_caiu():
    r = historico.Registro("t1", "renomeie as bins")
    r.evento("ferramenta", {"nome": "organizar_bins", "resumo": "Renomeia 3 bins"})
    # o processo morreu aqui: ninguém chamou terminar()
    assert historico.para_a_tela(vivo="")[-1]["estado"] == "caiu"
    # ⚠️ e um Reload no meio de um turno VIVO não o dá por morto
    assert historico.para_a_tela(vivo="t1")[-1]["estado"] == "correndo"


def test_cancelado_e_erro():
    a = historico.Registro("a", "x")
    a.evento("cancelado", {})
    a.terminar()
    b = historico.Registro("b", "y")
    b.evento("erro", {"mensagem": "deu ruim"})
    b.terminar()
    estados = {t["id"]: (t["estado"], t["erro"]) for t in historico.ler()}
    assert estados == {"a": ("interrompido", ""), "b": ("erro", "deu ruim")}


def test_teto_de_turnos():
    for i in range(historico.TETO_DE_TURNOS + 5):
        historico.Registro(f"t{i}", str(i)).terminar()
    turnos = historico.ler()
    assert len(turnos) == historico.TETO_DE_TURNOS
    assert turnos[-1]["id"] == f"t{historico.TETO_DE_TURNOS + 4}"


def test_arquivo_ruim_e_lista_vazia():
    historico._arquivo().parent.mkdir(parents=True, exist_ok=True)
    historico._arquivo().write_text("{nao é json", encoding="utf-8")
    assert historico.ler() == []


def test_a_rota_so_mostra_com_o_fio_continuando(monkeypatch):
    historico.Registro("t1", "oi").terminar()
    import json
    monkeypatch.setattr(rotas, "_fio", lambda: {"novo": True})
    assert json.loads(rotas.rota_historico(None).corpo)["turnos"] == []   # conversa que vai recomeçar
    monkeypatch.setattr(rotas, "_fio", lambda: {"novo": False, "turnos": 1})
    corpo = json.loads(rotas.rota_historico(None).corpo)
    assert [t["editor"] for t in corpo["turnos"]] == ["oi"]


def test_limpar_e_visita_nova_esquecem_o_historico():
    fonte = (RAIZ / "cicloassist" / "servico" / "rotas.py").read_text(encoding="utf-8")
    # nos dois lugares em que a conversa do chat morre
    assert fonte.count("_historico.esquecer()") == 2


def test_o_painel_redesenha_quando_o_fio_continua():
    js = (RAIZ / "cicloassist" / "painel" / "painel.js").read_text(encoding="utf-8")
    assert "if (s.fio && !s.fio.novo) { redesenharAConversa(); }" in js
    assert 'fetch("/conversa/historico"' in js
    assert 't.estado === "caiu"' in js
