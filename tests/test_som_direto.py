"""`montar_som_direto` — a operação 6 do ensaio (sem MC: pasta, cópias, o motor do DLPC, a entrega)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cicloassist.avid import som_direto as S
from cicloassist.mcp import registro
from cicloassist.mcp.ferramentas import som_direto as F

DLPC = S.raiz_do_dlpc()


def test_audios_da_pasta_pula_trabalho_e_video(tmp_path):
    for f in ["SOM DIRETO/a.wav", "SOM DIRETO/b.WAV", "CAM 1/x.mov", "_para_consolidar/a.wav", "SOM DIRETO/._a.wav"]:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"x")
    assert [p.name for p in S.audios_da_pasta(tmp_path)] == ["a.wav", "b.WAV"]


def test_copia_reaproveita_a_que_ja_existe(tmp_path):
    a = tmp_path / "a.wav"
    a.write_bytes(b"123")
    destino = tmp_path / "_para_consolidar"
    [c] = S.copiar([a], destino)
    c.write_bytes(b"XYZ")                      # mesmo tamanho: não copia de novo
    S.copiar([a], destino)
    assert c.read_bytes() == b"XYZ" and a.read_bytes() == b"123"


def test_ferramenta_so_no_avid_e_escreve():
    f = registro.FERRAMENTAS["montar_som_direto"]
    assert f.escreve is True and f.nles == ("avid",)


def test_pasta_nao_arrastada_e_recusada(tmp_path, monkeypatch):
    monkeypatch.setattr(F._lab, "na_saida", lambda p: False)
    (tmp_path / "a.wav").write_bytes(b"x")
    assert "arrast" in F._conferir(pasta=str(tmp_path), bin="SOM").lower()


class _Item:
    def __init__(self, n): self.nome = n


class _MC:
    def __init__(self, projeto: Path):
        self.p, self.chamadas = projeto, []

    def projeto(self, recarregar=False):
        return {"caminho": str(self.p), "fps_aprox": 25.0, "drop_frame": False}

    def caminho_relativo_da_bin(self, absoluto): return Path(absoluto).name

    def _chamar(self, metodo, **kw): self.chamadas.append((metodo, kw))

    def itens_da_bin(self, rel): return [_Item("a"), _Item("b")]


def test_nunca_regrava_bin_que_existe(tmp_path):
    (tmp_path / "SOM.avb").write_bytes(b"x")
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "a.wav").write_bytes(b"x")
    with pytest.raises(S.SomDiretoFalhou, match="já existe"):
        S.montar(_MC(tmp_path), tmp_path / "w", "SOM")


def test_entrega_bin_nova_com_a_taxa_do_projeto_e_diz_a_variante(tmp_path, monkeypatch):
    (tmp_path / "w").mkdir()
    for n in "ab":
        (tmp_path / "w" / f"{n}.wav").write_bytes(b"x")
    pedidos = []

    def autorar(arquivos, saida, fps, drop):
        pedidos.append((fps, drop, [a.parent.name for a in arquivos]))
        saida.write_bytes(b"avb")
        return {"clipes": 2, "pulados": [], "variante_trocada": ["a.wav", "b.wav"]}
    monkeypatch.setattr(S, "autorar", autorar)
    mc = _MC(tmp_path)
    r = S.montar(mc, tmp_path / "w", "SOM")
    assert pedidos == [(25.0, False, ["_para_consolidar", "_para_consolidar"])]   # as CÓPIAS
    assert (tmp_path / "SOM.avb").is_file() and not (tmp_path / "SOM.avb.novo").exists()
    assert mc.chamadas[0][0] == "OpenBin" and r["avisos"]


@pytest.mark.skipif(DLPC is None or S.python_do_dlpc(DLPC) is None or not shutil.which("ffmpeg"),
                    reason="sem o De Lá Pra Cá ou o ffmpeg")
def test_o_motor_do_dlpc_de_verdade(tmp_path):
    """O `autorar_masters` pelo Python do DLPC, num WAV com bext a 10:00:03:00, projeto 25."""
    w = tmp_path / "T01.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=2:r=48000", "-ac", "2", "-c:a", "pcm_s24le",
                    "-write_bext", "1", "-metadata", f"time_reference={(10 * 3600 + 3) * 48000}", str(w)], check=True)
    r = S.autorar([w], tmp_path / "SOM.avb", 25.0, False)
    assert r["clipes"] == 1 and (tmp_path / "SOM.avb").is_file(), json.dumps(r, default=str)[:400]


# ── som_direto_gerenciado ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("plataforma,presente,achou", [
    ("win32", ".venv/bin/python", False),                     # WinError 193 era o que saía daqui
    ("win32", ".venv-win/Scripts/python.exe", True),
    ("darwin", ".venv-win/Scripts/python.exe", False),
    ("darwin", ".venv/bin/python", True),
])
def test_a_venv_do_outro_sistema_nao_conta(tmp_path, monkeypatch, plataforma, presente, achou):
    (tmp_path / presente).parent.mkdir(parents=True)
    (tmp_path / presente).write_bytes(b"")
    monkeypatch.setattr(S.sys, "platform", plataforma)
    assert (S.python_do_dlpc(tmp_path) is not None) is achou


import datetime as _dt
from fractions import Fraction

from cicloassist.avid import importar_opatom as I
from cicloassist.avid import som_gerenciado as G


def test_tc_do_bext_na_base_do_projeto():
    assert G.tc_de((10 * 3600 + 3) * 48000, 48000, Fraction(25)) == (900075, "10:00:03:00")
    assert G.tc_de(0, 48000, Fraction(24000, 1001))[1] == "00:00:00:00"


def test_pasta_de_audio_termina_em_1_e_nunca_reusa(tmp_path):
    dia = _dt.date(2026, 11, 1)
    assert G.pasta_nova_de_audio(tmp_path, dia).name == "202611011"
    (tmp_path / "202611011").mkdir()
    assert G.pasta_nova_de_audio(tmp_path, dia).name == "2026110111"


def test_ferramenta_gerenciado_so_no_avid_e_escreve():
    f = registro.FERRAMENTAS["som_direto_gerenciado"]
    assert f.escreve is True and f.nles == ("avid",)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_wav_vira_um_clipe_costurado_com_fita_no_aaf(tmp_path):
    """Ponta a ponta sem MC: WAV estéreo com bext → 2 OP-Atom com UMA identidade → AAF com 1 master e a fita."""
    import aaf2
    w = tmp_path / "C1 P1-T001.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=2:r=48000", "-ac", "2", "-c:a", "pcm_s24le",
                    "-write_bext", "1", "-metadata", f"time_reference={(10 * 3600 + 3) * 48000}", str(w)], check=True)
    destino = tmp_path / "MXF" / "202611011"
    destino.mkdir(parents=True)
    nome, quadros = G.gerar(w, destino, Fraction(25))
    assert (nome, quadros) == ("C1 P1-T001", 900075)
    mxfs = I.mxfs_da_pasta(destino)
    assert len(mxfs) == 2
    _, masters, fitas = I.escrever_aaf(mxfs, "", {nome: (quadros, Fraction(25))})
    assert [m["nome"] for m in masters] == [nome]                  # costurados: UM clipe, não dois
    assert fitas == [(nome, nome)]
