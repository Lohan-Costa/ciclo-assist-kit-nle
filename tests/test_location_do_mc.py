"""A Location da Select Project vem do MCState (MEDIDO 2026-11-19: o projeto existia e o abrir pedia formato para criar)."""
import sys

import pytest

from cicloassist.avid import abrir


@pytest.mark.skipif(sys.platform != "win32", reason="o MCState do Windows")
def test_location_e_a_pasta_de_cima_do_ultimo_projeto(tmp_path, monkeypatch):
    loc = tmp_path / "PROJETOS"
    (loc / "ENSAIO").mkdir(parents=True)
    perfil = tmp_path / "Documents" / "Avid Media Composer" / "Avid Users" / "Editor"
    perfil.mkdir(parents=True)
    letra, resto = str(loc).split(":\\", 1)
    caminho = f"{letra}//{resto.replace(chr(92), '/')}/ENSAIO/".encode()
    perfil_avid = f"C//Users/Public/Documents/Avid Media Composer/Avid Users/Editor/".encode()
    (perfil / "MCState").write_bytes(b"\x00\x02" + perfil_avid + b"\x01\x00junk\x12\x00" + caminho + b"\x01\x01LE\x00")
    monkeypatch.setenv("PUBLIC", str(tmp_path))
    assert abrir.pasta_de_projetos() == loc


def test_sem_mcstate_fica_a_padrao(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC", str(tmp_path))
    assert abrir.pasta_de_projetos().name == "Avid Projects"
