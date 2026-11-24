"""O quadro que sai é o quadro pedido — mesmo quando a busca do arquivo mente.

⛔⛔ MEDIDO em 2026-09-17 (banco, `protocolos/mxf/README.md`): no OP-Atom MPEG-2 do transcode
do Media Composer, `ffmpeg -ss t` entrega o quadro **N/2**. 17 mídias deste cache tinham
quadros da primeira metade do clipe guardados na posição errada.
"""

from __future__ import annotations

import shutil
import subprocess
from fractions import Fraction

import pytest

from cicloassist.midia import frames as F
from cicloassist.midia import identidade as I

tem_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="sem ffmpeg nesta máquina")
TAXA = Fraction(24000, 1001)


@pytest.fixture
def clipe(tmp_path):
    """Um clipe em que cada quadro é visivelmente diferente do vizinho."""
    destino = tmp_path / "contagem.mov"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=size=160x90:rate=24000/1001", "-t", "4",
                    "-c:v", "prores_ks", str(destino)], check=True, timeout=120)
    return destino


def _bytes_do_quadro(arquivo, n: int) -> bytes:
    """O gabarito: decodificado em ordem, sem busca."""
    return F._em_ordem(arquivo, [n], F.LARGURA, F.QUALIDADE)[n]


@tem_ffmpeg
def test_busca_suspeita_cai_para_a_decodificacao_em_ordem(clipe, monkeypatch):
    monkeypatch.setattr(I, "sondar", lambda a: {"busca_suspeita": True})
    assert not F.busca_confiavel(clipe)
    for n in (0, 17, 60):
        assert F.extrair(clipe, n, TAXA) == _bytes_do_quadro(clipe, n)


@tem_ffmpeg
def test_varios_quadros_numa_passada_so_saem_na_ordem_certa(clipe, monkeypatch):
    monkeypatch.setattr(I, "sondar", lambda a: {"busca_suspeita": True})
    pedidos = [3, 41, 70]
    saiu = F.extrair_varios(clipe, pedidos, TAXA)
    assert sorted(saiu) == pedidos
    for n in pedidos:
        assert saiu[n] == _bytes_do_quadro(clipe, n)


@tem_ffmpeg
def test_arquivo_normal_continua_pela_busca_rapida(clipe, monkeypatch):
    """⚠️ A busca rápida é o caminho normal: 3 quadros em 0,38 s (medido em 2026-09-10)."""
    monkeypatch.setattr(I, "sondar", lambda a: {"busca_suspeita": False})
    chamadas = []
    original = subprocess.run

    def espiar(comando, *a, **k):
        chamadas.append(comando)
        return original(comando, *a, **k)

    monkeypatch.setattr(subprocess, "run", espiar)
    F.extrair_varios(clipe, [10, 20], TAXA)
    assert len(chamadas) == 2 and all("-ss" in c for c in chamadas)


def test_sem_ffprobe_a_busca_segue_confiavel(monkeypatch, tmp_path):
    """⚠️ Degradar para o comportamento de sempre, nunca estourar: o produto já rodou anos
    assim, e a mídia com índice quebrado é a exceção."""
    def explodir(_):
        raise I.IdentidadeErro("sem ffprobe")

    monkeypatch.setattr(I, "sondar", explodir)
    assert F.busca_confiavel(tmp_path / "x.mov")


@tem_ffmpeg
def test_quadro_a_menos_na_passada_nao_desloca_as_posicoes(clipe, monkeypatch):
    """⛔ Sem a conferência, um JPEG a menos faria o quadro 70 virar o 41 — o mesmo tipo de
    erro silencioso que esta correção existe para acabar."""
    monkeypatch.setattr(I, "sondar", lambda a: {"busca_suspeita": True})
    inteiro = F._em_ordem(clipe, [3, 41, 70], F.LARGURA, F.QUALIDADE)
    assert len(inteiro) == 3

    original = subprocess.run

    def cortando(comando, *a, **k):
        r = original(comando, *a, **k)
        if "-vf" in comando:  # devolve só o primeiro JPEG
            corte = r.stdout.find(b"\xff\xd9") + 2
            return subprocess.CompletedProcess(comando, 0, r.stdout[:corte], r.stderr)
        return r

    monkeypatch.setattr(subprocess, "run", cortando)
    # ⭐ Nada de "o que veio, na ordem que veio", e nada de tentar posição a posição (cada
    #   tentativa decodificaria o clipe outra vez): estoura com o motivo.
    with pytest.raises(F.ExtracaoFalhou, match="vieram 1"):
        F.extrair_varios(clipe, [3, 41, 70], TAXA)
    # Um quadro só continua saindo certo — a passada tem o tamanho que pediu.
    assert F.extrair(clipe, 41, TAXA) == inteiro[41]
