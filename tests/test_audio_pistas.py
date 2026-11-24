"""Arquivo AMA com várias pistas de áudio: todas entram na mixagem.

⛔⛔ MEDIDO em 2026-09-13: o `.mov` do RED tem QUATRO streams de áudio mono, e sem `-map`
o ffmpeg pega só a primeira. Ali passaria por acaso (pistas 3 e 4 em -90 dB); com a
lapela na pista 3 da câmera, a fala some da transcrição sem erro nenhum.
"""

from __future__ import annotations

from types import SimpleNamespace

from cicloassist.midia import audio as A


def _comando_de(monkeypatch, tmp_path, arquivos, pistas):
    visto = {}

    def rodar(comando, **_):
        visto["comando"] = comando
        destino = tmp_path / "saida.wav"
        destino.write_bytes(b"RIFF")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(A, "achar_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(A, "_pistas_de_audio", lambda _a: pistas)
    monkeypatch.setattr(A.subprocess, "run", rodar)
    A.mixar(arquivos, tmp_path / "saida.wav")
    return visto["comando"]


def _filtro(comando):
    return comando[comando.index("-filter_complex") + 1]


def test_um_arquivo_com_quatro_pistas_soma_as_quatro(monkeypatch, tmp_path):
    filtro = _filtro(_comando_de(monkeypatch, tmp_path, ["x.mov"], pistas=4))
    assert "[0:a:0][0:a:1][0:a:2][0:a:3]amix=inputs=4" in filtro
    # A mesma regra dos canais OP-Atom: somar, e não dividir pelo número de entradas.
    assert "normalize=0" in filtro


def test_um_arquivo_de_uma_pista_segue_como_antes(monkeypatch, tmp_path):
    filtro = _filtro(_comando_de(monkeypatch, tmp_path, ["x.wav"], pistas=1))
    assert "amix" not in filtro


def test_op_atom_de_cinco_arquivos_nao_muda(monkeypatch, tmp_path):
    """⭐ O caminho gerenciado é o do cache de 120 MB: a saída dele não pode mudar."""
    arquivos = [f"t_A0{i}.mxf" for i in range(1, 6)]
    filtro = _filtro(_comando_de(monkeypatch, tmp_path, arquivos, pistas=1))
    assert filtro.startswith("amix=inputs=5:")


def test_o_path_curto_do_launcher_ainda_acha_os_binarios(monkeypatch, tmp_path):
    """⛔⛔ MEDIDO no macOS (2026-09-14): lançado pelo Finder/launchd o serviço recebe
    `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, e o ffmpeg do Homebrew "não foi encontrado nesta
    máquina" com ele instalado. `binarios.achar` procura também onde os instaladores põem."""
    import os
    import stat

    from cicloassist import binarios

    falso = tmp_path / "bin"
    falso.mkdir()
    exe = falso / "ffprobe"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setenv("PATH", str(tmp_path / "vazio"))
    monkeypatch.setattr(binarios, "lugares_extras", lambda: [falso])
    assert binarios.achar("ffprobe") == str(exe)
    assert binarios.achar("nao-existe-mesmo") is None
    assert str(falso) in binarios.onde_procurei() or os.name == "nt"
