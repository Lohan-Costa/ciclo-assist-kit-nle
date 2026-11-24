"""A página embutida no Ciclo Assist: a faixa de progresso não pode alargar a página (fase 5, 2026-11-08)."""

from __future__ import annotations

import re
from pathlib import Path

PAINEL = Path(__file__).resolve().parents[2] / "pagina" / "painel.html"


def _regra(seletor: str) -> str:
    achado = re.search(re.escape(seletor) + r"\s*\{([^}]*)\}", PAINEL.read_text(encoding="utf-8"))
    assert achado, seletor
    return achado.group(1)


def test_a_margem_da_faixa_compensa_o_padding_do_corpo_embutido():
    corpo = re.search(r"padding:\s*\d+px\s+(\d+)px", _regra(".embutido body"))
    faixa = re.search(r"margin:\s*0\s+-(\d+)px", _regra(".embutido #prog"))
    assert corpo and faixa and corpo.group(1) == faixa.group(1)
