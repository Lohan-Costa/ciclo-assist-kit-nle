"""O órfão batizado pela POSIÇÃO (`T001.1`) não pode perder o ponto em lugar nenhum.

Pilotado em 2026-10-21 (MC 24.6, D02 da PRODUCAO-A): o Subclipar gravou `Take = 0011`, e o
Renomear com `C%cena_P%plano_T%take2` deu `C07_P02_T0011` — um take 11 que não existe. Com o
ponto cortado em outro lugar, o órfão colidiria com o take 1 real.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avid import renomear as R
from media import identidade as I


def test_take2_guarda_o_sufixo_do_presumido():
    assert R.derivador_de_take2({"take": "001.1"}) == {"take2": "001.1"}
    assert R.derivador_de_take2({"take": "1.2"}) == {"take2": "01.2"}
    # o caso comum não muda
    assert R.derivador_de_take2({"take": "003"}) == {"take2": "003"}
    assert R.derivador_de_take2({"take": "7"}) == {"take2": "07"}


def test_a_claquete_da_coluna_guarda_o_sufixo():
    d = R.derivador_de_claquete({"scene": "C07 P02", "take": "001.1"})
    assert d == {"cena": "07", "plano": "02", "take": "1.1"}
    # ⛔ e nunca vira o take 1 real
    assert d["take"] != R.derivador_de_claquete({"scene": "C07 P02", "take": "001"})["take"]


def test_a_releitura_da_bin_guarda_o_sufixo():
    real = I._da_coluna({"Scene": "C07 P02", "Take": "001"})
    orfao = I._da_coluna({"Scene": "C07 P02", "Take": "001.1"})
    assert orfao.take == real.take + ".1"
