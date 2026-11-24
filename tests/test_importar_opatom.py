"""`importar_masters_opatom` — a operação 5 do ensaio (sem MC: pasta, indexação, AAF)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from cicloassist.avid import importar_opatom as I
from cicloassist.mcp import registro
from cicloassist.mcp.ferramentas import masters as F


def _diaria(tmp_path, nome="202611010") -> Path:
    p = tmp_path / "Avid MediaFiles" / "MXF" / nome
    p.mkdir(parents=True)
    (p / "A.mxf").write_bytes(b"x")
    return p


def test_pasta_valida(tmp_path):
    assert I.pasta_valida(_diaria(tmp_path)) == ""
    assert "só de dígitos" in I.pasta_valida(_diaria(tmp_path, "9999_CICLO_SPIKE"))
    outra = tmp_path / "x" / "202611010"
    outra.mkdir(parents=True)
    assert "Avid MediaFiles" in I.pasta_valida(outra)
    vazia = tmp_path / "Avid MediaFiles" / "MXF" / "123"
    vazia.mkdir()
    assert "não há MXF" in I.pasta_valida(vazia)


def test_nao_indexado_sem_mdb_ou_mxf_mais_novo(tmp_path):
    p = _diaria(tmp_path)
    mxfs = I.mxfs_da_pasta(p)
    assert I.nao_indexados(mxfs) == mxfs
    (p / "msmMMOB.mdb").write_bytes(b"")
    velho = time.time() - 100
    os.utime(mxfs[0], (velho, velho))
    assert I.nao_indexados(mxfs) == []
    os.utime(p / "msmMMOB.mdb", (velho - 50, velho - 50))       # copiado DEPOIS do índice: o 31/10
    assert I.nao_indexados(mxfs) == mxfs


def test_no_mac_o_activate_indexa_e_a_frente_volta(tmp_path, monkeypatch):
    """macOS (medido 2026-11-05): índice 0,3 s depois do `activate` do MC; a frente volta ao Terminal."""
    p = _diaria(tmp_path)
    mxfs = I.mxfs_da_pasta(p)
    monkeypatch.setattr(I, "_no_mac", lambda: True)
    monkeypatch.setattr(I._janela, "focar", lambda h: pytest.fail("no Mac não se usa o janela.py"))
    frente = ["com.apple.Terminal"]
    ativados = []
    def ativar(bundle):
        ativados.append(bundle)
        frente[0] = bundle
        if bundle == I._MC_NO_MAC:
            (p / "msmMMOB.mdb").write_bytes(b"x")
    monkeypatch.setattr(I, "_app_da_frente_no_mac", lambda: frente[0])
    monkeypatch.setattr(I, "_ativar_no_mac", ativar)
    monkeypatch.setattr(I.time, "sleep", lambda s: None)
    I.esperar_indexar(mxfs, lambda *a: None)
    assert not I.nao_indexados(mxfs)
    assert ativados == [I._MC_NO_MAC, "com.apple.Terminal"]

def test_espera_o_indice_nascer_e_devolve_o_foco(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_no_mac", lambda: False)   # o caminho do Windows (foco)
    p = _diaria(tmp_path)
    mxfs = I.mxfs_da_pasta(p)
    focos = []
    monkeypatch.setattr(I._janela, "da_frente", lambda: 111)
    monkeypatch.setattr(I._janela, "janela_principal", lambda exe, titulo="": 222)
    monkeypatch.setattr(I._janela, "existe_aviso", lambda t: False)

    def focar(h):
        focos.append(h)
        if h == 222:                                  # o MC ganhou o foco: indexa
            (p / "msmMMOB.mdb").write_bytes(b"")
        return True
    monkeypatch.setattr(I._janela, "focar", focar)
    I.esperar_indexar(mxfs, lambda *a: None, prazo=5)
    assert focos[0] == 222 and focos[-1] == 111


def test_com_o_mc_ja_na_frente_ele_sai_e_volta_para_ganhar_o_foco(tmp_path, monkeypatch):
    """⛔⛔ O teste do autor (2026-11-01): o piloto tinha acabado de criar o projeto, o MC JÁ estava na
    frente, e "tirar e pôr" alternava MC com MC — nenhum GANHO de foco, 60 s em vão."""
    monkeypatch.setattr(I, "_no_mac", lambda: False)   # o caminho do Windows (foco)
    p = _diaria(tmp_path)
    mxfs = I.mxfs_da_pasta(p)
    frente = [222]
    monkeypatch.setattr(I._janela, "da_frente", lambda: frente[0])
    monkeypatch.setattr(I._janela, "janela_principal", lambda exe, titulo="": 222)
    monkeypatch.setattr(I._janela, "existe_aviso", lambda t: False)
    monkeypatch.setattr(I._janela, "exe_da_janela", lambda h: "AvidMediaComposer.exe" if h == 222 else "x.exe")
    monkeypatch.setattr(I, "_janela_de_fora", lambda antes, mc: 333)
    monkeypatch.setattr(I.time, "sleep", lambda s: None)

    def focar(h):
        if h == 222 and frente[0] != 222:             # só o GANHO indexa
            (p / "msmMMOB.mdb").write_bytes(b"")
        frente[0] = h
        return True
    monkeypatch.setattr(I._janela, "focar", focar)
    I.esperar_indexar(mxfs, lambda *a: None, prazo=5)
    assert not I.nao_indexados(mxfs)


def test_sem_janela_do_mc_diz_o_gesto(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_no_mac", lambda: False)   # o caminho do Windows (foco)
    monkeypatch.setattr(I._janela, "da_frente", lambda: None)
    monkeypatch.setattr(I._janela, "janela_principal", lambda exe, titulo="": None)
    with pytest.raises(I.ImportacaoFalhou, match="clicar"):
        I.esperar_indexar(I.mxfs_da_pasta(_diaria(tmp_path)), lambda *a: None)


def test_o_aviso_de_teclado_para_tudo(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_no_mac", lambda: False)   # o caminho do Windows (foco)
    monkeypatch.setattr(I._janela, "da_frente", lambda: 1)
    monkeypatch.setattr(I._janela, "janela_principal", lambda exe, titulo="": 2)
    monkeypatch.setattr(I._janela, "focar", lambda h: True)
    monkeypatch.setattr(I._janela, "existe_aviso", lambda t: t == "AvidMediaComposer")
    with pytest.raises(I.ImportacaoFalhou, match="Don't warn me again"):
        I.esperar_indexar(I.mxfs_da_pasta(_diaria(tmp_path)), lambda *a: None, prazo=3)


def test_ferramenta_so_no_avid_e_escreve():
    f = registro.FERRAMENTAS["importar_masters_opatom"]
    assert f.escreve is True and f.nles == ("avid",)


def test_conferir_recusa_pasta_errada_antes_do_mc(tmp_path):
    assert "só de dígitos" in F._conferir(pasta=str(_diaria(tmp_path, "abc")), bin="X")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_aaf_junta_video_e_som_num_master_e_da_nome_a_fita(tmp_path):
    """V e A do mesmo clipe (mesmo material package) viram UM master; a fita sem nome ganha o do clipe."""
    p = _diaria(tmp_path)
    (p / "A.mxf").unlink()
    v, a = p / "CLIPE.mxf", p / "CLIPE_A01.mxf"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=1920x1080:r=25:d=0.4",
                    "-c:v", "dnxhd", "-b:v", "36M", "-pix_fmt", "yuv422p", "-metadata", "material_package_name=CLIPE",
                    "-f", "mxf_opatom", str(v)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=0.4:r=48000", "-c:a", "pcm_s24le",
                    "-metadata", "material_package_name=CLIPE", "-f", "mxf_opatom", "-mxf_audio_edit_rate", "25",
                    str(a)], check=True)
    aaf, masters, fitas = I.escrever_aaf(I.mxfs_da_pasta(p))
    assert aaf.is_file() and len(masters) >= 1
    assert all(t for _, t in fitas)


def test_umid_em_qualquer_grafia():
    h = "060a2b340101010501010f1013000000" + "a9b9c2d3e4f5a6b7c8d9e0f1a2b3c4d5"
    assert I.hex_do_umid("urn:smpte:umid:060a2b34.01010105.01010f10.13000000.a9b9c2d3.e4f5a6b7.c8d9e0f1.a2b3c4d5") == h
    assert I.hex_do_umid("060a2b34010101050101 0f10-13-000000-a9b9c2d3e4f5a6b7c8d9e0f1a2b3c4d5") == h


class _Item:
    def __init__(self, u): self.mob_id = u


def test_espera_os_masters_chegarem_antes_de_fechar(monkeypatch):
    """⛔ ImportFile é assíncrono (banco): só fecha a bin depois de todos os masters aparecerem."""
    monkeypatch.setattr(I.time, "sleep", lambda s: None)
    respostas = iter([[], [_Item("a" * 64)], [_Item("a" * 64), _Item("b" * 64)]])

    class M:
        def itens_da_bin(self, rel): return next(respostas)
    I.esperar_masters(M(), "X.avb", {"a" * 64, "b" * 64}, lambda *a: None, prazo=30)


def test_master_que_nao_chega_e_erro_e_nao_fecha(monkeypatch):
    class M:
        def itens_da_bin(self, rel): return []
    with pytest.raises(I.ImportacaoFalhou, match="0 de 1"):
        I.esperar_masters(M(), "X.avb", {"a" * 64}, lambda *a: None, prazo=0.01)
