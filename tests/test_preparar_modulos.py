"""As venvs dos módulos: sem elas a Preparar e o Conformar não sobem (fase 5, 2026-11-08). Sem rede e sem pip."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("preparar_modulos", RAIZ / "tools" / "preparar_modulos.py")
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)


@pytest.fixture
def modulo(tmp_path):
    m = tmp_path / "conformar"
    m.mkdir()
    (m / "requirements.lock").write_text("x==1\n", encoding="ascii")
    return m


@pytest.fixture
def maquina(monkeypatch):
    """Um `_rodar` de mentira: `venv` faz nascer o python; `quebrados` guarda os que não executam."""
    estado = type("E", (), {"chamadas": [], "quebrados": set()})()

    def rodar(cmd):
        estado.chamadas.append(cmd)
        if "venv" in cmd:
            py = P.python_da(Path(cmd[-1]))
            py.parent.mkdir(parents=True)
            py.write_bytes(b"")
            return 0
        return 1 if cmd[0] in estado.quebrados else 0

    monkeypatch.setattr(P, "_rodar", rodar)
    return estado


def _pips(maquina):
    return [c for c in maquina.chamadas if "pip" in c]


def test_cria_instala_e_carimba(modulo, maquina):
    assert P.preparar(modulo, "requirements.lock") is True
    assert len(_pips(maquina)) == 1 and (P.pasta_da_venv(modulo) / P.CARIMBO).is_file()


def test_a_segunda_passada_nao_mexe(modulo, maquina):
    P.preparar(modulo, "requirements.lock")
    assert P.preparar(modulo, "requirements.lock") is False
    assert len(_pips(maquina)) == 1


def test_lista_mais_nova_que_o_carimbo_reinstala(modulo, maquina):
    P.preparar(modulo, "requirements.lock")
    carimbo = P.pasta_da_venv(modulo) / P.CARIMBO
    os.utime(carimbo, (1, 1))
    assert P.preparar(modulo, "requirements.lock") is True
    assert len(_pips(maquina)) == 2


def test_venv_que_existe_e_nao_executa_e_refeita(modulo, maquina):
    P.preparar(modulo, "requirements.lock")
    py = P.python_da(P.pasta_da_venv(modulo))
    maquina.quebrados.add(str(py))
    with pytest.raises(P.Falhou):            # continua quebrada depois de criar: diz, não finge
        P.preparar(modulo, "requirements.lock")
    assert sum("venv" in c for c in maquina.chamadas) == 2


def test_nunca_atualiza_o_pip(modulo, maquina):
    P.preparar(modulo, "requirements.lock")
    assert not any("--upgrade" in c or "-U" in c for c in maquina.chamadas)


def test_sem_a_lista_diz_qual_modulo(modulo, maquina):
    with pytest.raises(P.Falhou, match="conformar"):
        P.preparar(modulo, "nao-existe.lock")


def test_a_venv_e_a_que_o_app_procura():
    """O `lib.rs` monta o caminho por conta própria: os dois têm de falar da mesma pasta."""
    lib = (RAIZ / "app" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert ".venv-win/Scripts/python.exe" in lib and ".venv/bin/python" in lib
    esperado = ".venv-win" if sys.platform == "win32" else ".venv"
    assert P.pasta_da_venv(Path("m")).name == esperado


@pytest.mark.parametrize("script", ["instalar.ps1", "dev.ps1"])
def test_os_instaladores_chamam(script):
    assert "preparar_modulos.py" in (RAIZ / script).read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("modulo,lista", P.MODULOS.items())
def test_as_listas_existem(modulo, lista):
    assert (RAIZ / "modulos" / modulo / lista).is_file()
