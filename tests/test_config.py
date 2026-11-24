"""As configurações do editor, e a pasta do cache que ele pode mudar.

⚠️ **O que se protege aqui é a promessa da tela.** Um campo que aceita o valor, responde
"salvo" e não muda nada é pior que um campo que não existe: o editor passa a desconfiar do
painel inteiro. Por isso os testes conferem que o cache OBEDECE, e não só que o arquivo
foi escrito.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.midia import cache as C
from cicloassist.servico import config as K


@pytest.fixture(autouse=True)
def config_descartavel(tmp_path, monkeypatch):
    """Cada teste com a sua pasta de dados (`tests/conftest.py` a aponta para
    `tmp_path/CicloAssist`), e sem a variável de ambiente por perto."""
    monkeypatch.delenv("CICLOASSIST_CACHE", raising=False)
    yield


# ── o arquivo ────────────────────────────────────────────────────────────────

def test_sem_arquivo_a_config_e_vazia():
    assert K.ler() == {}


def test_gravar_e_ler_de_volta(tmp_path):
    K.gravar({"cache": str(tmp_path / "m")})
    assert K.ler()["cache"] == str(tmp_path / "m")


def test_grava_mesclando_e_nao_substituindo(tmp_path):
    """⚠️ O painel manda só o que o editor mexeu. Um POST que trouxesse o objeto inteiro
    apagaria em silêncio o que outra versão tivesse acrescentado do outro lado."""
    K.gravar({"cache": str(tmp_path / "m")})
    K.gravar({})
    assert K.ler()["cache"] == str(tmp_path / "m")


def test_apagar_a_escolha_volta_ao_padrao(tmp_path):
    K.gravar({"cache": str(tmp_path / "m")})
    K.gravar({"cache": None})
    assert "cache" not in K.ler()


def test_modelo_que_saiu_da_lista_cai_no_padrao():
    """⛔ O Sonnet 5 deu lugar ao 5.5 (2026-10-29): quem o tinha escolhido não pode continuar
    mandando um `--model` que o seletor nem oferece."""
    K.gravar({"modelo": "claude-sonnet-5"})
    assert K.modelo_guardado() == K.PADRAO == "claude-sonnet-5-5"
    K.gravar({"modelo": "claude-opus-5"})
    assert K.modelo_guardado() == "claude-opus-5"


def test_chave_desconhecida_nao_entra(tmp_path):
    """⛔ Lista fechada: o corpo do POST vem da página, e aceitar chave qualquer faria da
    configuração um saco de coisas que ninguém lê."""
    K.gravar({"cache": str(tmp_path / "m"), "qualquer": "coisa"})
    assert "qualquer" not in K.ler()


def test_arquivo_corrompido_vira_config_vazia():
    """⚠️ Um JSON truncado por queda de energia não pode impedir o serviço de subir."""
    K.arquivo().parent.mkdir(parents=True, exist_ok=True)
    K.arquivo().write_text("{ isto não é json", encoding="utf-8")
    assert K.ler() == {}


def test_config_que_nao_e_objeto_vira_vazia():
    K.arquivo().parent.mkdir(parents=True, exist_ok=True)
    K.arquivo().write_text(json.dumps(["uma", "lista"]), encoding="utf-8")
    assert K.ler() == {}


# ── e o cache obedece ────────────────────────────────────────────────────────

def test_o_cache_segue_a_escolha_do_editor(tmp_path):
    escolhida = tmp_path / "outro lugar"
    K.gravar({"cache": str(escolhida)})
    assert C.raiz() == escolhida


def test_o_ambiente_ganha_do_editor(tmp_path, monkeypatch):
    """⭐ Deliberado: é o que o desenvolvimento e os testes usam para não encostar no cache
    de quem está trabalhando na máquina. Quem exporta a variável sabe o que faz."""
    K.gravar({"cache": str(tmp_path / "escolhida")})
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "do ambiente"))
    assert C.raiz() == tmp_path / "do ambiente"


def test_sem_escolha_nenhuma_cai_no_padrao(tmp_path):
    assert C.raiz() == tmp_path / "CicloAssist" / "midia"


def test_config_quebrada_nao_esconde_o_cache(tmp_path):
    """⛔ Cair no padrão custa reprocessar; estourar derruba toda ferramenta que toca em
    mídia."""
    K.arquivo().parent.mkdir(parents=True, exist_ok=True)
    K.arquivo().write_text("{{{", encoding="utf-8")
    assert C.raiz() == tmp_path / "CicloAssist" / "midia"


def test_a_pasta_de_dados_e_a_mesma_do_log(tmp_path):
    """⛔ Uma conta só. No projeto anterior ela existia em três lugares e as cópias
    divergiram no macOS: log numa pasta, transcrição em outra, sem nada acusar."""
    from cicloassist.servico import diario
    assert K.pasta() == diario.pasta().parent
    assert K.pasta() == C.raiz().parent


# ── o modelo e o automático ──────────────────────────────────────────────────

def test_o_modelo_escolhido_chega_ao_comando_do_cli():
    """⭐ De nada adianta o dropdown se a flag não sai daqui."""
    from cicloassist.motor.sessao import Sessao
    from pathlib import Path

    s = Sessao("abc", "http://x", ["mcp__ciclo__listar_bins"], "claude-opus-5")
    comando = s._comando("claude", Path("mcp.json"), retomar=False)
    assert "--model" in comando
    assert comando[comando.index("--model") + 1] == "claude-opus-5"


def test_sem_escolha_o_cli_usa_o_padrao_da_conta():
    """⛔ Nunca fixar um modelo às costas do editor: sem escolha, sem flag."""
    from cicloassist.motor.sessao import Sessao
    from pathlib import Path

    s = Sessao("abc", "http://x", [])
    assert "--model" not in s._comando("claude", Path("mcp.json"), retomar=False)


def test_o_esforco_escolhido_chega_ao_comando_so_no_claude():
    """⭐ Ensaio da C07 (2026-10-22): o pensamento foi a maior parte da saída do turno."""
    from cicloassist.motor.sessao import Sessao
    from pathlib import Path

    s = Sessao("abc", "http://x", [], "claude-sonnet-5")
    assert "--effort" not in s._comando("claude", Path("mcp.json"), retomar=False)
    K.gravar({"esforco": "low"})
    comando = s._comando("claude", Path("mcp.json"), retomar=False)
    assert comando[comando.index("--effort") + 1] == "low"
    # O Ollama não pensa por orçamento: a flag não vai para o modelo do Mac.
    local = Sessao("abc", "http://x", [], K.LOCAL + "qwen3-vl:8b-instruct")
    assert "--effort" not in local._comando("claude", Path("mcp.json"), False, "qwen3-vl")
    # ⛔ Lista fechada: vira argumento de linha de comando.
    K.gravar({"esforco": "--dangerously"})
    assert "--effort" not in s._comando("claude", Path("mcp.json"), retomar=False)
    K.gravar({"esforco": None})


def test_trocar_de_modelo_derruba_o_processo(monkeypatch):
    """⚠️ O modelo é escolhido na PARTIDA do `claude -p`. Sem reiniciar, o painel mostraria
    um nome que não corresponde a quem está respondendo."""
    from cicloassist.motor import sessao as S

    S.encerrar_todas()
    s1 = S.do_projeto("C:/p", "http://x", [], "claude-sonnet-5")
    matou = {"sim": False}
    monkeypatch.setattr(s1, "_matar", lambda: matou.__setitem__("sim", True))

    s2 = S.do_projeto("C:/p", "http://x", [], "claude-opus-5")
    assert s2 is s1                 # a MESMA sessão: o fio da conversa não se perde
    assert s2.modelo == "claude-opus-5"
    assert matou["sim"], "o processo tinha de cair para o modelo novo valer"
    S.encerrar_todas()


def test_o_mesmo_modelo_nao_derruba_nada(monkeypatch):
    from cicloassist.motor import sessao as S

    S.encerrar_todas()
    s1 = S.do_projeto("C:/p", "http://x", [], "claude-sonnet-5")
    matou = {"sim": False}
    monkeypatch.setattr(s1, "_matar", lambda: matou.__setitem__("sim", True))
    S.do_projeto("C:/p", "http://x", [], "claude-sonnet-5")
    assert not matou["sim"]
    S.encerrar_todas()


def test_o_automatico_nasce_desligado():
    assert K.ler().get("auto") is None


# ── a assinatura das ferramentas ─────────────────────────────────────────────

def test_a_assinatura_muda_quando_um_esquema_muda(monkeypatch):
    """⭐ É o que avisa o modelo de que a opinião dele sobre as ferramentas envelheceu.

    Em 2026-09-11 `montar_corte` ganhou `corte_de_som` e o modelo, retomando a conversa,
    seguiu dizendo ao editor que corte em L/J era inviável — com a capacidade já no ar.
    """
    from cicloassist.mcp import registro

    antes = registro.assinatura()
    monkeypatch.setitem(
        registro.FERRAMENTAS, "montar_corte",
        registro.Ferramenta("montar_corte", "", {"campo": "novo"}, lambda: None, True))
    assert registro.assinatura() != antes


def test_a_assinatura_nao_muda_a_toa():
    from cicloassist.mcp import registro
    assert registro.assinatura() == registro.assinatura()


def test_o_estado_interno_nao_se_mistura_com_o_do_editor():
    """⚠️ `config.json` é o que o EDITOR escolheu — ele pode abrir e apagar. O estado do
    serviço mora ao lado, para a tela de configurações não mostrar coisa que não é dele."""
    K.gravar_estado({"ferramentas": "abc123"})
    assert K.ler_estado()["ferramentas"] == "abc123"
    assert "ferramentas" not in K.ler()
    assert K.arquivo() != K.arquivo_de_estado()
