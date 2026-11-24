"""`abrir_programa`: o Ciclo Assist abre o Resolve — só se o EDITOR o nomeou (autor, 2026-10-29)."""

from __future__ import annotations

import pytest

from cicloassist import resolve as R
from cicloassist.mcp.ferramentas import programas as P
from cicloassist.servico import turno as T


@pytest.fixture
def turno(monkeypatch):
    t = T.Turno()
    monkeypatch.setattr(T, "atual", lambda: t)
    monkeypatch.setattr(R, "instalado", lambda: True)
    return t


@pytest.mark.parametrize("texto", ["Leve este projeto para o Resolve.", "abre no DaVinci",
                                   "conforma no RESOLVE por favor"])
def test_o_editor_nomeou_passa(turno, texto):
    turno.texto_do_editor = texto
    assert P._conferir(programa="resolve", projeto="WSP-DLPC_2") == ""


@pytest.mark.parametrize("texto", ["Leve este projeto para o outro programa.", "conforma isso", ""])
def test_sem_o_nome_do_programa_manda_perguntar(turno, texto):
    """⛔ A regra do autor: sem o programa no pedido, pergunta — mesmo no automático (a
    conferência roda antes dele, `portao.py`)."""
    turno.texto_do_editor = texto
    recusa = P._conferir(programa="resolve", projeto="X")
    assert "Pergunte" in recusa and "automático" in recusa


def test_o_preambulo_do_arrasto_nao_conta_como_o_editor_ter_dito(turno):
    """O caminho arrastado pode conter 'Resolve' (uma pasta 'PREMIERE E RESOLVE'): só vale o que
    ele ESCREVEU, e é por isso que o turno guarda o texto sem o preâmbulo."""
    turno.texto_do_editor = "leva pra lá"
    assert P._conferir(programa="resolve", projeto="X")


def test_sem_nome_de_projeto_pede_um(turno):
    turno.texto_do_editor = "no Resolve"
    assert "Diga o projeto" in P._conferir(programa="resolve", projeto=" ")


def test_programa_que_nao_sei_abrir(turno):
    turno.texto_do_editor = "abre o Premiere"
    assert "Ainda não sei abrir" in P._conferir(programa="final_cut", projeto="X")


# ── o mapa dos três programas (2026-11-01) ───────────────────────────────────

@pytest.mark.parametrize("programa,texto", [
    ("media_composer", "depois abra o Media Composer"), ("media_composer", "no MC, crie o projeto"),
    ("media_composer", "leva pro avid"), ("premiere", "monta no Premiere"),
    ("resolve", "converta no DaVinci")])
def test_cada_programa_pelas_palavras_do_editor(programa, texto):
    assert P.nomeado_pelo_editor(programa, texto)


def test_mc_nao_casa_dentro_de_outra_palavra():
    """⛔ "mc" é palavra inteira: "o servidor mcp" não é o editor pedindo o Media Composer."""
    assert not P.nomeado_pelo_editor("media_composer", "confira o servidor mcp")


def test_o_nome_dito_num_turno_anterior_vale(turno, monkeypatch):
    """⭐ O teste do autor: o pedido inteiro no turno 1, e "continue" no turno 2."""
    monkeypatch.setattr(T, "_da_conversa", ["abra o resolve … depois o media composer"])
    turno.texto_do_editor = "continue"
    assert P._conferir(programa="media_composer", projeto="desktop") == ""


def test_premiere_pede_o_caminho_do_prproj(turno, monkeypatch, tmp_path):
    from cicloassist import premiere_app as PA
    monkeypatch.setattr(PA, "executavel", lambda versao="": "premiere.exe")
    turno.texto_do_editor = "abra no Premiere"
    assert "caminho completo" in P._conferir(programa="premiere", projeto="desktop")
    assert P._conferir(programa="premiere", projeto=str(tmp_path / "desktop.prproj")) == ""
    assert "não existe" in P._conferir(programa="premiere", projeto=str(tmp_path / "x" / "d.prproj"))


def test_mc_recusa_formato_que_nao_conhece_antes_da_tela(turno):
    turno.texto_do_editor = "crie no Media Composer"
    assert "não sei criar" in P._conferir(programa="media_composer", projeto="X", formato="4K/25")
    assert P._conferir(programa="media_composer", projeto="X", formato="1080p/25") == ""


def test_o_projeto_do_mc_sai_do_titulo_da_janela():
    from cicloassist.avid import abrir as A
    assert A.projeto_do_titulo("Avid Media Composer  - desktop") == "desktop"   # medido, 2 espaços
    assert A.projeto_do_titulo("Avid Media Composer") == ""
    assert A.projeto_do_titulo("AvidMediaComposer") == ""
    assert A.grupo_do_formato("1080p/23.976") == "HD 1080"


def test_o_format_ja_certo_poupa_a_lista_suspensa():
    """⭐ O MC lembra o último formato: lido no campo (ou descrito sob a cruz), pula 3 cliques."""
    from cicloassist.avid import abrir as A
    assert A._mesmo_formato("1080p/25", "1080p/25")
    assert A._mesmo_formato("O campo Format mostrando '1080p/25' com a seta", "1080p/25")
    assert not A._mesmo_formato("1080p/250", "1080p/25")
    assert not A._mesmo_formato("1080p/23.976", "1080p/23")
    assert not A._mesmo_formato("", "1080p/25")


def test_abre_e_cria_o_projeto(turno, monkeypatch):
    monkeypatch.setattr(R, "abrir", lambda relatar=None: {"ja_estava": False, "segundos": 21.0})
    monkeypatch.setattr(R, "projeto", lambda nome: {"versao": "19.1.4.11", "projeto": nome,
                                                     "como": "criado"})
    r = P.abrir_programa(programa="resolve", projeto="WSP-DLPC_2")
    assert r["projeto"] == "WSP-DLPC_2" and r["projeto_foi"] == "criado agora"
    assert r["situacao"] == "aberto em 21.0 s"


def test_resolve_que_nao_sobe_vira_erro_legivel(turno, monkeypatch):
    def nao(relatar=None):
        raise R.ResolveIndisponivel("o DaVinci Resolve não ficou pronto")
    monkeypatch.setattr(R, "abrir", nao)
    assert "não ficou pronto" in P.abrir_programa(programa="resolve", projeto="X")["erro"]


def test_fechar_salva_e_espera_sair(turno, monkeypatch):
    no_ar = iter([True, True])
    monkeypatch.setattr(R, "servidor_no_ar", lambda: next(no_ar, False))
    vivo = iter([True, True])  # a porta cai ANTES do processo sair (medido)
    monkeypatch.setattr(R, "processo_vivo", lambda: next(vivo, False))
    monkeypatch.setattr(R, "_na_api", lambda acao, nome="": {"projeto": "desktop", "salvo": True,
                                                             "versao": "19.1.4.11"})
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    r = P.fechar_programa(programa="resolve")
    assert r["projeto_salvo"] == "'desktop' salvo" and r["situacao"].startswith("fechado em")


def test_fechar_o_que_ja_esta_fechado_nao_fala_com_a_api(turno, monkeypatch):
    monkeypatch.setattr(R, "servidor_no_ar", lambda: False)
    monkeypatch.setattr(R, "_na_api", lambda *a, **k: pytest.fail("falou com um Resolve fechado"))
    assert P.fechar_programa(programa="resolve")["situacao"] == "já estava fechado"


def test_fechar_no_meio_do_render_vira_erro_legivel(turno, monkeypatch):
    monkeypatch.setattr(R, "servidor_no_ar", lambda: True)
    def renderizando(acao, nome=""):
        raise R.ResolveIndisponivel("o Resolve está renderizando; espere o render acabar")
    monkeypatch.setattr(R, "_na_api", renderizando)
    assert "renderizando" in P.fechar_programa(programa="resolve")["erro"]


def test_resolve_que_nao_sai_diz_o_porque(monkeypatch):
    monkeypatch.setattr(R, "servidor_no_ar", lambda: True)
    monkeypatch.setattr(R, "_na_api", lambda acao, nome="": {"projeto": "X", "salvo": True})
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    with pytest.raises(R.ResolveIndisponivel, match="diálogo"):
        R.fechar(prazo=0.0)


def _preso_no_desligamento(monkeypatch, resposta):
    """O Resolve do Mac (21.1) depois do Quit: porta fechada, processo vivo até alguém o forçar."""
    estado = {"vivo": True, "forcado": 0, "agora": 0.0}
    no_ar = iter([True])
    monkeypatch.setattr(R, "servidor_no_ar", lambda: next(no_ar, False))
    monkeypatch.setattr(R, "processo_vivo", lambda: estado["vivo"])
    monkeypatch.setattr(R, "_na_api", lambda acao, nome="": resposta)
    def forcar():
        estado["forcado"] += 1
        estado["vivo"] = False
    monkeypatch.setattr(R, "_forcar", forcar)
    def passar(s):
        estado["agora"] += s
    monkeypatch.setattr(R.time, "sleep", passar)
    monkeypatch.setattr(R.time, "monotonic", lambda: estado["agora"])
    return estado


def test_preso_no_desligamento_com_o_projeto_salvo_e_encerrado(monkeypatch):
    estado = _preso_no_desligamento(monkeypatch, {"projeto": "D01", "salvo": True})
    r = R.fechar()
    assert estado["forcado"] == 1 and r["salvo"] is True
    assert r["segundos"] >= R.PRESO_NO_DESLIGAMENTO_S


def test_o_rascunho_tambem_pode_ser_encerrado(monkeypatch):
    estado = _preso_no_desligamento(monkeypatch, {"projeto": "Untitled Project", "salvo": False})
    R.fechar()
    assert estado["forcado"] == 1


def test_sem_salvar_nunca_se_forca(monkeypatch):
    """⛔ O SaveProject falhou num projeto de verdade: forçar perderia o trabalho do editor."""
    estado = _preso_no_desligamento(monkeypatch, {"projeto": "D01", "salvo": False})
    with pytest.raises(R.ResolveIndisponivel, match="diálogo"):
        R.fechar()
    assert estado["forcado"] == 0


def test_fechar_nao_exige_o_nome_nesta_pergunta(turno):
    """Num fluxo de vários turnos, "pode seguir" não repete o nome do programa."""
    turno.texto_do_editor = "pode seguir"
    assert P._conferir_fechar(programa="resolve") == ""


def test_com_o_servidor_no_ar_nao_lanca_de_novo(monkeypatch):
    monkeypatch.setattr(R, "servidor_no_ar", lambda: True)
    monkeypatch.setattr(R, "_api_responde", lambda *a, **k: {"projeto": "X"})
    monkeypatch.setattr(R, "_lancar", lambda: pytest.fail("lançou o Resolve com ele aberto"))
    assert R.abrir() == {"ja_estava": True, "segundos": 0.0}


def test_falha_do_sistema_vai_ao_editor(turno, monkeypatch):
    """(autor, 2026-11-22) O programa caiu ao abrir/fechar → a resposta traz a falha e manda contar ao editor."""
    from cicloassist.piloto import falhas as F
    monkeypatch.setattr(R, "abrir", lambda relatar=None: {"ja_estava": False, "segundos": 21.0})
    monkeypatch.setattr(R, "projeto", lambda nome: {"versao": "19", "projeto": nome, "como": "criado"})
    vistos = []
    monkeypatch.setattr(F, "desde", lambda marca, apps=None: vistos.append(apps) or
                        [{"arquivo": "/x/Resolve.ips", "quando": 0.0, "app": "Resolve", "motivo": "SIGABRT", "por": None}])
    r = P.abrir_programa(programa="resolve", projeto="X")
    assert vistos == [["Resolve"]] and "SIGABRT" in r["falhas_do_sistema"][0] and "conte a ele" in r["agora"]
    monkeypatch.setattr(F, "desde", lambda marca, apps=None: [])
    assert "falhas_do_sistema" not in P.abrir_programa(programa="resolve", projeto="X")


def test_falhas_ilegiveis_nao_derrubam(turno, monkeypatch):
    from cicloassist.piloto import falhas as F
    monkeypatch.setattr(R, "abrir", lambda relatar=None: {"ja_estava": False, "segundos": 1.0})
    monkeypatch.setattr(R, "projeto", lambda nome: {"versao": "19", "projeto": nome, "como": "criado"})
    monkeypatch.setattr(F, "desde", lambda *a, **k: 1 / 0)
    assert P.abrir_programa(programa="resolve", projeto="X")["projeto"] == "X"
