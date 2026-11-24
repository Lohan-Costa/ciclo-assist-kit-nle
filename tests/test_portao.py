"""O portão de aprovação — quem decide, quando, e o que acontece depois do clique.

⭐ **O que estes testes protegem não é o "sim", é o NÃO.** Uma aprovação que o modelo
contorna é pior que não ter aprovação nenhuma, porque dá a impressão de controle. Todo
caminho que possa acabar em "deixa passar" sem alguém ter clicado é bug de segurança, não
de conveniência.

⛔⛔ **E protegem uma segunda coisa, desde 2026-09-11: que o editor NÃO tem prazo.** Aqui
havia um relógio, e ele custou o primeiro teste de campo — ver ADR 0008 e o
`spikes/portao_espera.py`. Se um teste voltar a falar em "espera máxima", alguém
reintroduziu o defeito.

O contrato do CLI foi medido em `spikes/fase3_permissao.py` (2026-09-10, 2.1.267):
chega `{tool_name, input, tool_use_id}`; espera `{behavior: allow|deny}`.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.mcp.ferramentas import portao as P
from cicloassist.servico import pendencias as _pend
from cicloassist.servico import turno as T


@pytest.fixture(autouse=True)
def pendencias_limpas(tmp_path, monkeypatch):
    """Cada teste começa sem pendência nenhuma, e grava num disco descartável.

    ⚠️⚠️ **E com a configuração isolada da máquina.** Sem a linha do `CICLOASSIST_DADOS`, estes
    testes liam o `config.json` de quem está usando o produto — e no dia em que o editor
    deixou o **modo automático ligado**, dezoito testes do portão passaram a falhar na
    máquina dele e só nela. Teste que depende do estado do usuário não testa nada: ele
    reporta o humor da máquina.
    """
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path / "CicloAssist"))
    monkeypatch.setattr(_pend, "arquivo", lambda: tmp_path / "pendencias.json")
    # ⚠️ Estes testes usam `montar_corte` como EXEMPLO de escrita, com entrada fictícia
    #    (`{"bin": "X.avb"}`). Desde 2026-09-13 ele confere o plano antes do cartão, e essa
    #    entrada não passaria — a conferência antes do cartão é testada em `test_falas.py`.
    from dataclasses import replace

    from cicloassist.mcp import registro
    monkeypatch.setitem(registro.FERRAMENTAS, "montar_corte",
                        replace(registro.FERRAMENTAS["montar_corte"], conferir=None))
    _pend.esquecer_tudo()
    yield
    _pend.esquecer_tudo()


@pytest.fixture
def turno():
    t = T.comecar()
    yield t
    T.terminar(t)


def eventos_da_fila(turno) -> list[tuple[str, dict]]:
    saida = []
    while not turno.fila.empty():
        item = turno.fila.get_nowait()
        if isinstance(item, tuple):
            saida.append(item)
    return saida


# ── o portão responde na hora, e nunca bloqueia ──────────────────────────────

def test_o_portao_responde_sem_esperar_ninguem(turno):
    """⛔⛔ O teste que guarda a decisão inteira: a chamada volta NA HORA.

    Se um dia isto travar, é porque alguém voltou a esperar o clique dentro da chamada —
    e o editor voltou a ter o prazo do CLI (medido: 60 s) para decidir.
    """
    r = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    assert r["behavior"] == "deny"
    assert r["message"] == P.AGUARDANDO


def test_o_deny_ensina_o_modelo_a_esperar(turno):
    """A mensagem é para o modelo, e cada pedaço dela evita um erro visto em campo."""
    r = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    texto = r["message"].lower()
    assert "não tente de novo" in texto      # a pilha de cartões repetidos
    assert "amanhã" in texto or "expira" in texto  # a demora é normal, não é falha


def test_o_pedido_vira_pendencia_aberta(turno):
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    abertas = _pend.abertas()
    assert len(abertas) == 1
    assert abertas[0].ferramenta == "montar_corte"
    assert abertas[0].entrada == {"bin": "X.avb"}


def test_o_cartao_chega_ao_painel_pela_fila(turno):
    """O cartão aparece porque o pedido é emitido como evento no MESMO fluxo em que a
    resposta está sendo pintada."""
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    tipos = [t for t, _ in eventos_da_fila(turno)]
    assert "aprovacao" in tipos


def test_sem_turno_vivo_o_pedido_ainda_fica_de_pe(monkeypatch):
    """⭐ Painel fechado não perde o pedido — ele espera o `GET /pendencias`.

    Antes, sem turno a resposta era "não há painel para aprovar" e a ação morria ali. Com
    a pendência no disco, fechar o Media Composer no meio virou um contratempo, não uma
    perda.
    """
    monkeypatch.setattr(T, "_atual", None)
    r = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    assert r["behavior"] == "deny"
    assert len(_pend.abertas()) == 1


# ── o pedido sobrevive ao turno ──────────────────────────────────────────────

def test_a_pendencia_sobrevive_ao_fim_do_turno(turno):
    """⛔ O coração do ADR 0008. O turno acaba; o cartão continua valendo."""
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    T.terminar(turno)
    assert len(_pend.abertas()) == 1


def test_a_pendencia_volta_do_disco(turno, tmp_path):
    """Serviço reiniciado no meio: o editor volta amanhã e o cartão está lá."""
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    assert (tmp_path / "pendencias.json").exists()

    # Um processo novo: esquece a memória, mas o disco continua.
    _pend._tudo.clear()
    _pend._carregado = False
    voltas = _pend.abertas()
    assert len(voltas) == 1
    assert voltas[0].entrada == {"bin": "X.avb"}


def test_pedido_identico_nao_empilha_cartao(turno):
    """⭐ Em campo o modelo repetiu o mesmo `montar_corte` achando que tinha falhado, e o
    editor ficou com dois cartões iguais sem saber qual valia."""
    a = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    b = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    assert a["behavior"] == b["behavior"] == "deny"
    assert len(_pend.abertas()) == 1


def test_pedido_diferente_vira_cartao_proprio(turno):
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "Y.avb"})
    assert len(_pend.abertas()) == 2


# ── o clique, e o que ele dispara ────────────────────────────────────────────

def test_o_sim_executa_a_ferramenta(turno, monkeypatch):
    """⭐ Quem executa é o SERVIÇO, com os argumentos que o editor leu no cartão."""
    feito = {}

    def falsa(**kw):
        feito.update(kw)
        return {"ok": True, "sequencia": "C07 v2", "bin": "c.avb",
                "cortes": 14, "duracao_s": 226.7}

    from cicloassist.mcp import registro
    monkeypatch.setitem(registro.FERRAMENTAS, "montar_corte",
                        registro.Ferramenta("montar_corte", "", {}, falsa, True))

    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    id_ = _pend.abertas()[0].id

    r = _pend.decidir(id_, True)
    assert r["ok"] is True
    assert feito == {"bin": "X.avb"}       # exatamente o que estava na tela
    assert _pend.abertas() == []


def test_o_nao_nao_executa_nada(turno, monkeypatch):
    from cicloassist.mcp import registro

    def explode(**kw):  # pragma: no cover - existe para NÃO ser chamada
        raise AssertionError("o 'Não' executou a ferramenta")

    monkeypatch.setitem(registro.FERRAMENTAS, "montar_corte",
                        registro.Ferramenta("montar_corte", "", {}, explode, True))
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    id_ = _pend.abertas()[0].id

    r = _pend.decidir(id_, False)
    assert r["estado"] == "recusada"


def test_clicar_duas_vezes_nao_executa_duas_vezes(turno, monkeypatch):
    """⛔ Duas sequências iguais na bin, e a culpa parecendo do editor."""
    vezes = []
    from cicloassist.mcp import registro
    monkeypatch.setitem(
        registro.FERRAMENTAS, "montar_corte",
        registro.Ferramenta("montar_corte", "", {},
                            lambda **kw: (vezes.append(1), {"ok": True})[1], True))

    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    id_ = _pend.abertas()[0].id
    _pend.decidir(id_, True)
    segunda = _pend.decidir(id_, True)

    assert vezes == [1]
    assert segunda["ok"] is False


def test_ferramenta_que_estoura_nao_derruba_o_clique(turno, monkeypatch):
    """O editor clicou: ele tem de ver o que deu errado, não um painel mudo."""
    from cicloassist.mcp import registro

    def falha(**kw):
        raise RuntimeError("o Media Composer não respondeu")

    monkeypatch.setitem(registro.FERRAMENTAS, "montar_corte",
                        registro.Ferramenta("montar_corte", "", {}, falha, True))
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    id_ = _pend.abertas()[0].id

    r = _pend.decidir(id_, True)
    assert r["ok"] is False
    assert "não respondeu" in r["erro"]


def test_clique_em_pedido_que_nao_existe_nao_estoura():
    assert _pend.decidir("nao-existe", True)["ok"] is False


# ── o recado que volta para o modelo ─────────────────────────────────────────

def test_o_modelo_fica_sabendo_no_proximo_turno(turno, monkeypatch):
    """⚠️ Sem isto o modelo — que viu a própria chamada ser negada — ofereceria montar de
    novo, ou montaria."""
    from cicloassist.mcp import registro
    monkeypatch.setitem(
        registro.FERRAMENTAS, "montar_corte",
        registro.Ferramenta("montar_corte", "", {},
                            lambda **kw: {"ok": True, "sequencia": "C07 v2",
                                          "bin": "c.avb", "cortes": 14,
                                          "duracao_s": 226.7}, True))
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    _pend.decidir(_pend.abertas()[0].id, True)

    recados = _pend.recados()
    assert len(recados) == 1
    assert "C07 v2" in recados[0]
    assert "não monte de novo" in recados[0].lower()


def test_o_recado_e_contado_uma_vez_so(turno, monkeypatch):
    from cicloassist.mcp import registro
    monkeypatch.setitem(registro.FERRAMENTAS, "montar_corte",
                        registro.Ferramenta("montar_corte", "", {},
                                            lambda **kw: {"ok": True}, True))
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    _pend.decidir(_pend.abertas()[0].id, True)

    assert _pend.recados()
    assert _pend.recados() == []


def test_a_recusa_tambem_vira_recado(turno):
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    _pend.decidir(_pend.abertas()[0].id, False)
    assert "recusou" in " ".join(_pend.recados())



def test_a_conversa_nova_nao_herda_o_recado_da_anterior(turno, monkeypatch):
    """⛔⛔ Medido em 2026-11-03: a aprovação de um fluxo de OUTRA conversa ("rodar o fluxo
    D01 foi feito") abriu a primeira pergunta da conversa nova, e o modelo concluiu que o
    trabalho já tinha rodado — conferiu, achou o MC fechado e parou. A conversa recomeça
    (visita nova ou "Limpar conversa"), o recado vai junto; a pendência fica."""
    from cicloassist.mcp import registro
    monkeypatch.setitem(registro.FERRAMENTAS, "montar_corte",
                        registro.Ferramenta("montar_corte", "", {},
                                            lambda **kw: {"ok": True}, True))
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    _pend.decidir(_pend.abertas()[0].id, True)

    assert _pend.descartar_recados() == 1
    assert _pend.recados() == []


def test_os_recados_sao_colhidos_depois_da_limpeza_da_visita():
    """⛔ A ordem é o conserto: colher antes de `_conversa_desta_visita` leva o recado
    velho para a conversa que acabou de nascer."""
    from cicloassist.servico import rotas as R
    texto = open(R.__file__, encoding="utf-8").read()
    moer = texto[texto.index("    def moer() -> None:"):]
    assert moer.index("_conversa_desta_visita(anexos, qual)") < moer.index("_com_recados(pergunta")
    corpo = texto[texto.index("def _conversa_desta_visita"):texto.index("def _fio()")]
    assert "_pendencias.descartar_recados()" in corpo


# ── o vocabulário do editor ──────────────────────────────────────────────────

def test_nome_tecnico_vira_frase_de_gente():
    """O editor aprova o que vai acontecer, não a mecânica."""
    assert P.rotulo("mcp__ciclo__anotar_o_que_vi") == "guardar a descrição de um take"
    assert "_" not in P.rotulo("mcp__ciclo__uma_ferramenta_nova")


def test_o_cartao_leva_o_rotulo_e_nao_o_nome_tecnico(turno):
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    cartoes = [d for t, d in eventos_da_fila(turno) if t == "aprovacao"]
    assert cartoes[0]["ferramenta"] == "montar este corte"


# ── um turno por vez ─────────────────────────────────────────────────────────

def test_segundo_turno_e_recusado(turno):
    """⚠️ A chamada de `pedir_confirmacao` NÃO diz de que turno ela é — o CLI manda só
    `tool_name`, `input` e `tool_use_id`. Com dois turnos vivos, um cartão poderia ser
    desenhado no painel errado."""
    with pytest.raises(T.TurnoOcupado):
        T.comecar()


# ── o disco ──────────────────────────────────────────────────────────────────

def test_arquivo_corrompido_vira_nenhuma_pendencia(tmp_path, monkeypatch):
    """⚠️ Mesma regra do cache: perder uma pendência custa um clique; estourar na partida
    custa o painel inteiro."""
    caminho = tmp_path / "pendencias.json"
    caminho.write_text("{ isto não é json", encoding="utf-8")
    monkeypatch.setattr(_pend, "arquivo", lambda: caminho)
    _pend._tudo.clear()
    _pend._carregado = False
    assert _pend.abertas() == []


def test_o_disco_guarda_so_o_que_ainda_importa(turno, tmp_path, monkeypatch):
    """Pendência decidida e já contada ao modelo não precisa voltar amanhã."""
    from cicloassist.mcp import registro
    monkeypatch.setitem(registro.FERRAMENTAS, "montar_corte",
                        registro.Ferramenta("montar_corte", "", {},
                                            lambda **kw: {"ok": True}, True))
    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    _pend.decidir(_pend.abertas()[0].id, True)
    _pend.recados()

    guardado = json.loads((tmp_path / "pendencias.json").read_text(encoding="utf-8"))
    assert guardado["pendencias"] == []


# ── o modo automático (ADR 0009) ─────────────────────────────────────────────
#
# ⛔ É o ÚNICO caminho em que uma escrita acontece sem clique humano. Qualquer terceiro
#    caminho que apareça aqui é bug até prova em contrário.

def test_com_auto_ligado_o_portao_libera_na_hora(turno, monkeypatch):
    from cicloassist.servico import config as K
    monkeypatch.setattr(K, "ler", lambda: {"auto": True})

    r = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    assert r["behavior"] == "allow"
    assert r["updatedInput"] == {"bin": "X.avb"}


def test_o_auto_nao_abre_pendencia(turno, monkeypatch):
    """Não há o que esperar: a ferramenta roda dentro do turno, pelo próprio CLI."""
    from cicloassist.servico import config as K
    monkeypatch.setattr(K, "ler", lambda: {"auto": True})

    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    assert _pend.abertas() == []


def test_sem_perguntar_nao_e_sem_contar(turno, monkeypatch):
    """⚠️ O editor que volta ao painel precisa poder ler o que foi feito enquanto ele não
    estava olhando."""
    from cicloassist.servico import config as K
    monkeypatch.setattr(K, "ler", lambda: {"auto": True})

    P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={"bin": "X.avb"})
    eventos = eventos_da_fila(turno)
    tipos = [t for t, _ in eventos]
    assert "automatico" in tipos
    dado = [d for t, d in eventos if t == "automatico"][0]
    assert dado["ferramenta"] == "montar este corte"


def test_o_padrao_e_perguntar(turno, monkeypatch):
    """⛔ Um produto que instala com a confirmação dispensada decide pelo editor
    exatamente a coisa que ele deveria decidir."""
    from cicloassist.servico import config as K
    monkeypatch.setattr(K, "ler", lambda: {})

    r = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    assert r["behavior"] == "deny"
    assert len(_pend.abertas()) == 1


def test_desligar_vale_para_a_proxima_acao(turno, monkeypatch):
    """⛔ Lido a CADA pedido, nunca guardado na partida: desligar o automático não pode
    esperar o próximo arranque do serviço."""
    from cicloassist.servico import config as K
    estado = {"auto": True}
    monkeypatch.setattr(K, "ler", lambda: dict(estado))

    assert P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte",
                               input={"a": 1})["behavior"] == "allow"
    estado["auto"] = False
    assert P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte",
                               input={"a": 2})["behavior"] == "deny"


# ── ferramenta que não é do produto ──────────────────────────────────────────
#
# ⛔⛔ MEDIDO no CLI 2.1.270 (`spikes/o_que_o_restricted_deixa.py`): o `--restricted` deixa
#    29 ferramentas do próprio CLI, com `Write` e `Edit`, e o automático respondia `allow`
#    para qualquer nome. O ADR 0009 prometia "muda quem responde ao portão, não quem passa
#    por ele" — e não cumpria.

@pytest.mark.parametrize("nome", ["Write", "Edit", "NotebookEdit", "Task", "WebSearch",
                                  "mcp__gmail__send_message"])
def test_com_auto_ligado_ferramenta_de_fora_e_recusada(turno, monkeypatch, nome):
    from cicloassist.servico import config as K
    monkeypatch.setattr(K, "ler", lambda: {"auto": True})

    r = P.pedir_confirmacao(tool_name=nome, input={"file_path": "C:/qualquer.txt"})
    assert r["behavior"] == "deny"
    assert r["message"] == P.FORA_DO_PRODUTO
    assert "automatico" not in [t for t, _ in eventos_da_fila(turno)]


def test_sem_auto_ferramenta_de_fora_nem_vira_cartao(turno, monkeypatch):
    """A pendência só sabe executar ferramenta NOSSA: um cartão de `Write` seria um botão
    que o editor clica e que não faz nada — ou, pior, que um dia passa a fazer."""
    from cicloassist.servico import config as K
    monkeypatch.setattr(K, "ler", lambda: {})

    r = P.pedir_confirmacao(tool_name="Write", input={"file_path": "C:/x.txt"})
    assert r["behavior"] == "deny"
    assert _pend.abertas() == []
    assert "aprovacao" not in [t for t, _ in eventos_da_fila(turno)]
