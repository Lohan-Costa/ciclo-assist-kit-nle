"""O cartão mostra o QUE está sendo feito, e não só "fazendo…".

⭐ A ação aprovada roda FORA do turno (ADR 0008), e era por isso que o relato das
ferramentas (`turno.avisar`) sumia: sem turno vivo, não havia a quem contar. Agora ele cai
no andamento da pendência em execução, e o painel pergunta (`GET /andamento`). Medido em
19/09 com o primeiro `sincronizar_diaria` de verdade: minutos de "fazendo…" parado.
"""

from __future__ import annotations

import threading

import pytest

from cicloassist.mcp.registro import FERRAMENTAS, Ferramenta
from cicloassist.servico import pendencias as P
from cicloassist.servico import turno as T


@pytest.fixture(autouse=True)
def _limpo():
    P.esquecer_tudo()
    P._andamento.clear()
    P._executando.pendencia = ""
    yield
    P.esquecer_tudo()
    P._andamento.clear()


def _registrar(monkeypatch, nome, funcao) -> str:
    """⚠️ Por `monkeypatch.setitem`: o registro de ferramentas é GLOBAL do processo, e uma
    ferramenta de teste que ficasse lá apareceria no `tools/list` dos vizinhos."""
    monkeypatch.setitem(FERRAMENTAS, nome,
                        Ferramenta(nome=nome, descricao="", esquema={}, funcao=funcao,
                                   escreve=True))
    return nome


def test_sem_acao_em_curso_o_andamento_e_vazio():
    assert P.andamento() == {}
    T.avisar("etapa perdida")          # não levanta, e não inventa andamento
    assert P.andamento() == {}


def test_o_relato_da_ferramenta_chega_ao_cartao(monkeypatch):
    visto = {}

    def ferramenta_lenta():
        # É o MESMO `turno.avisar` que as ferramentas já chamam — nenhuma mudou.
        T.avisar("o Sincronizar está sincronizando", 0.5, "CAM A")
        visto["durante"] = P.andamento()
        return {"feito": "sim"}

    nome = _registrar(monkeypatch, "teste_lenta", ferramenta_lenta)
    p = P.abrir(nome, "sincronizar esta diária", {})
    r = P.decidir(p.id, True)

    assert r["ok"] and r["estado"] == "feita"
    assert visto["durante"]["etapa"] == "o Sincronizar está sincronizando"
    assert visto["durante"]["fracao"] == 0.5
    assert visto["durante"]["detalhe"] == "CAM A"
    assert visto["durante"]["decorrido"] >= 0
    # ⚠️ E some no fim: um andamento esquecido apareceria no cartão seguinte como se a
    #    ação de antes ainda estivesse rodando.
    assert P.andamento() == {}


def test_a_acao_que_falha_tambem_limpa(monkeypatch):
    def explode():
        T.avisar("quase lá", 0.9)
        raise RuntimeError("o Media Composer fechou")

    nome = _registrar(monkeypatch, "teste_explode", explode)
    p = P.abrir(nome, "fazer algo", {})
    r = P.decidir(p.id, True)

    assert r["ok"] is False and r["estado"] == "falhou"
    assert P.andamento() == {}


def test_o_relato_de_OUTRA_thread_nao_se_mistura(monkeypatch):
    """⚠️ Thread-local: duas ações ao mesmo tempo (dois painéis, um turno e um cartão)
    não podem contar uma a história da outra."""
    def devagar():
        T.avisar("minha etapa", 0.1)
        outra = threading.Thread(target=lambda: T.avisar("etapa de ninguém", 0.9))
        outra.start()
        outra.join()
        return {"andamento": P.andamento()}

    nome = _registrar(monkeypatch, "teste_threads", devagar)
    p = P.abrir(nome, "fazer", {})
    r = P.decidir(p.id, True)

    assert r["resultado"]["andamento"]["etapa"] == "minha etapa"


def test_o_turno_vivo_continua_ganhando(monkeypatch):
    """⛔ Quem tem turno vivo emite NO TURNO, como sempre — o cartão é o caso de exceção."""
    emitidos = []
    turno = T.comecar()
    monkeypatch.setattr(turno, "emitir", lambda tipo, dado: emitidos.append((tipo, dado)))
    try:
        T.avisar("transcrevendo", 0.3)
    finally:
        T.terminar(turno)

    assert emitidos and emitidos[0][0] == "progresso"
    assert P.andamento() == {}
