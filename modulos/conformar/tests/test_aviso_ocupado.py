"""O aviso "vou ficar mudo" ao supervisor do app (`aviso_ocupado.py`, 2026-11-23).

A chamada ao Resolve segura o GIL: o supervisor só sabe esperar se o aviso estiver no disco ANTES dela e sumir
DEPOIS — inclusive quando ela levanta erro. Fora do app (sem a variável), nada se grava.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico")]

import aviso_ocupado  # noqa: E402


def test_grava_durante_e_apaga_depois(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        aviso = os.path.join(d, "ocupado-conformar.json")
        monkeypatch.setenv("CICLOASSIST_OCUPADO", aviso)
        with aviso_ocupado.mudo("esperando o DaVinci Resolve (importar)", segundos=60):
            dados = json.loads(Path(aviso).read_text(encoding="utf-8"))
            assert dados["motivo"] == "esperando o DaVinci Resolve (importar)"
            assert dados["pid"] == os.getpid()
            assert 0 < dados["ate"] - __import__("time").time() <= 61
        assert not os.path.exists(aviso)


def test_apaga_mesmo_quando_a_chamada_falha(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        aviso = os.path.join(d, "ocupado-conformar.json")
        monkeypatch.setenv("CICLOASSIST_OCUPADO", aviso)
        with pytest.raises(RuntimeError):
            with aviso_ocupado.mudo("x"):
                raise RuntimeError("o Resolve recusou")
        assert not os.path.exists(aviso)


def test_duas_chamadas_ao_mesmo_tempo_vale_a_mais_longa(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        aviso = os.path.join(d, "ocupado-conformar.json")
        monkeypatch.setenv("CICLOASSIST_OCUPADO", aviso)
        with aviso_ocupado.mudo("longa", segundos=600):
            with aviso_ocupado.mudo("curta", segundos=10):
                assert json.loads(Path(aviso).read_text(encoding="utf-8"))["motivo"] == "longa"
            assert os.path.exists(aviso), "a longa continua"
        assert not os.path.exists(aviso)


def test_fora_do_app_nao_grava_nada(monkeypatch):
    monkeypatch.delenv("CICLOASSIST_OCUPADO", raising=False)
    with aviso_ocupado.mudo("x"):
        pass
