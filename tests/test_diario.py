"""O arquivo de log — a retenção, e o que NÃO entra nele.

⛔ **A decisão que estes testes protegem:** caminho de mídia e nome de bin ENTRAM no log
(são o que torna um defeito de campo diagnosticável — a casa já pagou por não registrar),
mas o **texto da conversa** fica de fora. Ele não ajuda a diagnosticar e é o que mais expõe
o trabalho de quem edita.
"""

from __future__ import annotations

import logging
import os
import time

import pytest

from cicloassist.servico import diario


@pytest.fixture
def pasta_limpa(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_LOGS", str(tmp_path))
    yield tmp_path
    # Solta o arquivo antes do tmp_path ser removido: no Windows um handler aberto
    # impede a exclusão, e o teste seguinte herdaria o erro.
    for h in list(logging.getLogger().handlers):
        h.close()
        logging.getLogger().removeHandler(h)


# ── onde ─────────────────────────────────────────────────────────────────────

def test_o_log_nao_mora_na_pasta_do_projeto(pasta_limpa):
    """⛔ O projeto é do editor. Nosso arquivo de diagnóstico não se hospeda lá."""
    assert diario.pasta() == pasta_limpa


def test_variavel_de_ambiente_manda():
    anterior = os.environ.get("CICLOASSIST_LOGS")
    os.environ["CICLOASSIST_LOGS"] = r"Z:\qualquer"
    try:
        assert str(diario.pasta()).startswith("Z:")
    finally:
        if anterior is None:
            del os.environ["CICLOASSIST_LOGS"]
        else:
            os.environ["CICLOASSIST_LOGS"] = anterior


# ── o que grava ──────────────────────────────────────────────────────────────

def test_grava_mesmo_de_pe(pasta_limpa):
    arquivo = diario.configurar("info")
    logging.getLogger("cicloassist.teste").info("bin CENAS/C07.avb nao encontrada")
    for h in logging.getLogger().handlers:
        h.flush()
    assert arquivo is not None and arquivo.is_file()
    # ⭐ Caminho de bin ENTRA: é o que responde "que caminho o Avid disse" num relato de
    #    campo, sem ninguém por perto.
    assert "CENAS/C07.avb" in arquivo.read_text(encoding="utf-8")


def test_o_texto_da_conversa_nao_entra_no_nivel_normal(pasta_limpa):
    """⛔ A pergunta carrega a intenção criativa de quem edita, não só o nome do arquivo.
    E ela não é necessária para diagnosticar."""
    arquivo = diario.configurar("info")
    log = logging.getLogger("cicloassist.servico.rotas")
    log.info("turno abc123 começou (42 caracteres)")
    log.debug("turno abc123: monte um corte da cena do beijo")
    for h in logging.getLogger().handlers:
        h.flush()
    texto = arquivo.read_text(encoding="utf-8")
    assert "42 caracteres" in texto
    assert "cena do beijo" not in texto


def test_no_debug_o_texto_entra_e_o_editor_e_avisado(pasta_limpa):
    """⚠️ Ligar o debug muda o que se grava. Quem liga tem de ver isso na cara."""
    arquivo = diario.configurar("debug")
    logging.getLogger("cicloassist.servico.rotas").debug("turno abc: corte da cena do beijo")
    for h in logging.getLogger().handlers:
        h.flush()
    texto = arquivo.read_text(encoding="utf-8")
    assert "cena do beijo" in texto
    assert "TEXTO das conversas" in texto      # o aviso da partida


# ── retenção ─────────────────────────────────────────────────────────────────

def test_apaga_o_que_passou_da_retencao(pasta_limpa):
    """⚠️⚠️ **A rotação sozinha NÃO cumpre a promessa.** Ela só acontece com o processo de
    pé; um serviço desligado por um mês guardaria o log do mês passado intacto. A varredura
    no arranque é o que faz "7 dias" ser verdade, e não intenção."""
    velho = pasta_limpa / "cicloassist.log.2026-01-01"
    velho.write_text("material antigo do cliente", encoding="utf-8")
    antigo = time.time() - (diario.DIAS + 2) * 86400
    os.utime(velho, (antigo, antigo))

    recente = pasta_limpa / "cicloassist.log.2026-09-09"
    recente.write_text("de ontem", encoding="utf-8")

    diario.configurar("info")
    assert not velho.exists(), "log fora da retenção sobreviveu"
    assert recente.exists(), "log dentro da retenção foi apagado"


def test_a_retencao_e_de_uma_semana():
    """O número é o compromisso escrito em `docs/ameacas.md`. Mudá-lo aqui sem mudar lá
    faria o documento mentir."""
    assert diario.DIAS == 7


def test_nao_apaga_arquivo_que_nao_e_nosso(pasta_limpa):
    """A pasta é nossa, mas apagar por data sem olhar o nome é como se destrói o que
    alguém pôs ali."""
    alheio = pasta_limpa / "outra-coisa.txt"
    alheio.write_text("nao e nosso", encoding="utf-8")
    antigo = time.time() - 400 * 86400
    os.utime(alheio, (antigo, antigo))
    diario.configurar("info")
    assert alheio.exists()


# ── nunca derruba o serviço ──────────────────────────────────────────────────

def test_sem_poder_escrever_o_servico_continua(monkeypatch, tmp_path):
    """⚠️ Disco cheio, pasta sem permissão, antivírus segurando o arquivo — nada disso
    pode impedir o editor de trabalhar."""
    monkeypatch.setenv("CICLOASSIST_LOGS", str(tmp_path / "logs"))

    def recusar(*a, **k):
        raise OSError("sem permissão")

    monkeypatch.setattr("pathlib.Path.mkdir", recusar)
    assert diario.configurar("info") is None
    logging.getLogger("cicloassist.teste").info("ainda registro no console")
