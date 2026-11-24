"""`ver_quadros_da_midia` e o `quadros_de` por baixo dele — o caminho da fila de decupagem.

O que estes testes travam são dois defeitos achados na revisão de 2026-09-22:

- ⛔⛔ `quadros_de` devolvia, na falha do ffmpeg, a forma de resposta da FERRAMENTA (uma
  lista de blocos) em vez da tupla que ela promete. Quem chama desempacota três valores:
  no chat isso virava `not enough values to unpack` no lugar do motivo, e na fila do Mac
  (`percepcao.decupar`) o `ValueError` não é tratado por ninguém e derrubava a TAREFA.
- ⛔ Os quadros da CABEÇA (os da claquete) iam no FIM do pedido. MEDIDO no outro motor:
  com eles no fim, o modelo narrou "a claquete é mostrada novamente no final".
"""

from __future__ import annotations

import pytest

from cicloassist.midia import acervo as A
from cicloassist.midia import cache as C
from cicloassist.midia import frames as F
from cicloassist.mcp.ferramentas import midia as M

CHAVE = "c" * 64
JPEG = b"\xff\xd8corpo"


@pytest.fixture
def acervo(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    video = tmp_path / "A001_C003.mxf"
    video.write_bytes(b"x" * 32)
    A.guardar("D:/mídia/A001", [A.Clipe(
        CHAVE, "A001_C003", [str(video)], {"video": 1}, fps="24000/1001",
        duracao_s=20.0, por_tipo={"video": [str(video)]})], raiz=tmp_path / "cache")
    return C.Midia(CHAVE)


def test_midia_ilegivel_levanta_em_vez_de_devolver_blocos(acervo, monkeypatch):
    """⛔⛔ O defeito que derrubava a fila inteira numa mídia só."""
    def nao_le(*a, **k):
        raise F.ExtracaoFalhou("o ffmpeg não produziu quadro")

    monkeypatch.setattr(F, "extrair_varios", nao_le)

    with pytest.raises(F.ExtracaoFalhou):
        M.quadros_de(CHAVE, 3)

    # E a ferramenta do chat diz o MOTIVO, não um erro de desempacotamento.
    (bloco,) = M.ver_quadros_da_midia(chave=CHAVE, quantos=3)
    assert "não produziu quadro" in bloco["text"]
    assert "unpack" not in bloco["text"]


def test_a_cabeca_vai_primeiro(acervo, monkeypatch):
    """⛔ A ordem das imagens É a ordem do material para o modelo: a claquete no fim vira
    "a claquete aparece de novo no final"."""
    monkeypatch.setattr(F, "extrair_varios",
                        lambda arq, pos, taxa, **k: {p: JPEG for p in pos})
    monkeypatch.setattr(M, "quadros_da_cabeca", lambda chave: ([b"\xff\xd8cab"], [1.0]))

    blocos = M.ver_quadros_da_midia(chave=CHAVE, quantos=2, claquete=True)

    tipos = [b["type"] for b in blocos]
    assert tipos == ["text", "image", "text", "image", "image"]
    assert "CABEÇA" in blocos[0]["text"]
    assert "em ordem, nos segundos" in blocos[2]["text"]


def test_sem_claquete_a_resposta_nao_muda(acervo, monkeypatch):
    monkeypatch.setattr(F, "extrair_varios",
                        lambda arq, pos, taxa, **k: {p: JPEG for p in pos})
    blocos = M.ver_quadros_da_midia(chave=CHAVE, quantos=2)
    assert [b["type"] for b in blocos] == ["text", "image", "image"]
