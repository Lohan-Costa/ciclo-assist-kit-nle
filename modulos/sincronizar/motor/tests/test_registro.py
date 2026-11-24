"""
O LOG — arquivo único, cabeçalho de ambiente e rotação que não derruba nada.

O que estes testes guardam:

  1. **O nome do arquivo é fixo** (`sincronizar.log`). O formato antigo — um
     `sincronizar_<timestamp>.log` por execução — fazia achar o log certo num relato de
     campo depender de acertar o horário do teste no nome do arquivo.
  2. **Toda execução abre com o cabeçalho de ambiente.** Um log que não diz qual
     Órbita, em que SO e com que ffmpeg rodou responde "o que aconteceu" e não
     responde "aqui, por quê" — e obriga uma ida e volta com quem testou.
  3. **A rotação falha CALADA.** No Windows o arquivo pode estar aberto por outro
     processo (o sidecar do app e um `tools/regua.py` ao mesmo tempo), e o rename do
     rollover levanta `PermissionError`. Derrubar o sidecar por manutenção de
     arquivo de log seria desproporcional — e perder as linhas seguintes, pior
     ainda, porque é justamente quando há muito log que se está diagnosticando algo.
  4. **`configurar` é idempotente**: chamar duas vezes não duplica handler (cada
     linha sairia em dobro) nem reescreve o cabeçalho.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import registro


@pytest.fixture
def log_limpo():
    """Estado global do `logging` restaurado — senão um teste vaza no seguinte."""
    raiz = logging.getLogger()
    antes_handlers, antes_nivel = list(raiz.handlers), raiz.level
    registro._configurado = False
    yield
    for h in list(raiz.handlers):
        if h not in antes_handlers:
            h.close()
            raiz.removeHandler(h)
    raiz.setLevel(antes_nivel)
    registro._configurado = False


def test_arquivo_tem_nome_fixo(tmp_path, log_limpo):
    alvo = registro.configurar("teste", tmp_path)
    assert alvo.name == "sincronizar.log"
    assert alvo.parent == tmp_path


def test_cabecalho_traz_o_ambiente(tmp_path, log_limpo, monkeypatch):
    monkeypatch.setenv("SINC_VERSION", "9.9.9")
    monkeypatch.setenv("SINC_FFPROBE", "/caminho/do/ffprobe")
    alvo = registro.configurar("regua", tmp_path)
    texto = alvo.read_text(encoding="utf-8")

    assert "9.9.9" in texto                    # qual Órbita
    assert "(regua)" in texto                  # quem abriu esta execução
    assert "/caminho/do/ffprobe" in texto      # "não achou mídia" já foi ffprobe ausente
    assert "Python" in texto and "PID" in texto


def test_configurar_duas_vezes_nao_duplica(tmp_path, log_limpo):
    registro.configurar("teste", tmp_path)
    registro.configurar("teste", tmp_path)
    registro.log("x").info("linha única")

    texto = (tmp_path / "sincronizar.log").read_text(encoding="utf-8")
    assert texto.count("linha única") == 1
    assert texto.count("nova execução") == 1


def test_a_execucao_seguinte_ACRESCENTA_ao_mesmo_arquivo(tmp_path, log_limpo):
    """O arquivo é um só ao longo do tempo — é o que troca "achar o log da hora
    certa" por "procurar o cabeçalho mais próximo do horário"."""
    registro.configurar("primeira", tmp_path)
    registro.log("x").info("da primeira")
    for h in list(logging.getLogger().handlers):
        h.close()
        logging.getLogger().removeHandler(h)
    registro._configurado = False

    registro.configurar("segunda", tmp_path)
    registro.log("x").info("da segunda")

    texto = (tmp_path / "sincronizar.log").read_text(encoding="utf-8")
    assert "da primeira" in texto and "da segunda" in texto
    assert texto.count("nova execução") == 2


def test_rollover_que_falha_nao_derruba_nem_emudece(tmp_path, log_limpo, monkeypatch):
    """⛔ O caso do Windows com dois processos: o rename levanta e a escrita SEGUE.

    O que se guarda aqui não é só "não levanta" — é que a linha escrita DEPOIS da
    falha ainda chega ao arquivo. `RotatingFileHandler.doRollover` fecha o stream
    antes de renomear; sem reabrir, toda linha seguinte morre em silêncio, que é o
    oposto do que um log serve.
    """
    registro.configurar("teste", tmp_path)
    handler = next(h for h in logging.getLogger().handlers
                   if isinstance(h, registro._RotativoTolerante))
    handler.maxBytes = 1          # força rollover na próxima linha

    # ⚠️ O dublê IMITA a stdlib de verdade: `doRollover` FECHA o stream e o zera
    # ANTES de tentar o rename. Um dublê que só levanta passaria com a nossa guarda
    # removida — e o defeito real (log emudecido dali em diante) escaparia.
    def falha_como_o_windows(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        raise PermissionError("arquivo em uso por outro processo")

    monkeypatch.setattr(registro.logging.handlers.RotatingFileHandler,
                        "doRollover", falha_como_o_windows)

    registro.log("x").info("depois da falha de rotação")
    handler.flush()

    texto = (tmp_path / "sincronizar.log").read_text(encoding="utf-8")
    assert "depois da falha de rotação" in texto


def test_log_de_modulo_pende_de_sincronizar(log_limpo):
    """Todos sob `sincronizar.`, para que um dia dê para calar/soltar um subsistema só."""
    assert registro.log("avid.masters").name == "sincronizar.avid.masters"
    assert registro.log("__main__").name == "sincronizar.main"
    # Já qualificado não ganha prefixo em cima do prefixo.
    assert registro.log("sincronizar.avid").name == "sincronizar.avid"
