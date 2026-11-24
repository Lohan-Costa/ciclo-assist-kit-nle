"""O carimbo da receita nos quadros guardados sem ela (`tools/carimbar_receita_quadros.py`).

⛔ Carimbar é afirmar com que receita o quadro foi feito. O que se protege aqui é não afirmar
errado: quem já tem receita fica com a dela, e largura diferente da de hoje fica de fora.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import frames as F

_spec = importlib.util.spec_from_file_location(
    "carimbar", Path(__file__).resolve().parents[1] / "tools" / "carimbar_receita_quadros.py")
carimbar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(carimbar)

CHAVE = C.de_umid("0x060A2B340101010101010F0013000000C6D91F0BB8ABB1C7ABEE2FFBA70D1E05")


def jpeg(largura: int, altura: int = 432) -> bytes:
    """O mínimo que o leitor precisa: SOI, um APP0 para pular, e o SOF0 com as medidas."""
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x00" * 9
    sof0 = (b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
            + altura.to_bytes(2, "big") + largura.to_bytes(2, "big") + b"\x03" + b"\x00" * 9)
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


@pytest.fixture(autouse=True)
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))


def test_le_a_largura_do_sof():
    assert carimbar.largura_do_jpeg(jpeg(768)) == 768
    assert carimbar.largura_do_jpeg(b"nao e jpeg") is None


def test_quadros_da_receita_de_hoje_sao_carimbados():
    m = C.Midia(CHAVE)
    for p in (10, 20):
        m.guardar_quadro(p, jpeg(F.ASSINATURA["largura"]))
    assert carimbar.avaliar(m)[0] == "carimbar"


def test_largura_diferente_fica_de_fora():
    """⚠️ Basta UM quadro de outra largura: a mídia pode ter quadros de duas origens."""
    m = C.Midia(CHAVE)
    m.guardar_quadro(10, jpeg(F.ASSINATURA["largura"]))
    m.guardar_quadro(20, jpeg(512))
    veredito, detalhe = carimbar.avaliar(m)
    assert veredito == "largura" and "512" in detalhe


def test_quem_tem_receita_fica_com_a_dela():
    m = C.Midia(CHAVE)
    m.guardar_quadro(10, jpeg(F.ASSINATURA["largura"]))
    m.registrar_gerador("quadros", {"largura": 1})
    assert carimbar.avaliar(m)[0] == "tem_receita"
