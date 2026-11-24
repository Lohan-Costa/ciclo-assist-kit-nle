"""O `mob_id` do PRÓPRIO clipe — para onde uma timeline pode apontar.

⛔⛔ Até 2026-08-30 o `Tomada` guardava só o `mob_id` do MASTER, dentro dos
trechos. O clipe que o take É — o subclipe ou o masterclipe — não tinha
identidade registrada, e por isso o emissor não tinha para onde apontar: ele
cunhava um subclipe novo por fala.

⚠️ **Um take lido de uma SEQUÊNCIA não tem clipe próprio**, e aí o campo sai
vazio. Isso não é falha do leitor: uma região de timeline não é um objeto da
bin. É a razão de o emissor por referência exigir bin de clipes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import avb

from avid import subclipes as _subclipes
from avid import takes as _takes


def test_o_take_de_MASTERCLIPE_guarda_o_mob_id_do_master(bin_de_masters):
    lidos, forma = _takes.ler(str(bin_de_masters))

    assert forma == "masterclipe"
    assert all(t.mob_id for t in lidos), "algum take saiu sem mob_id"
    # ⭐ E o mob_id é o do PRÓPRIO clipe: aqui o clipe É o master, então ele
    # coincide com o `mob_id` dos trechos.
    for take in lidos:
        assert {tr.mob_id for tr in take.trechos} == {take.mob_id}


def test_o_take_de_SUBCLIPE_guarda_o_mob_id_do_SUBCLIPE_e_nao_do_master(
        bin_sincronizada, tmp_path):
    """⛔ A distinção que faz a diferença: o `mob_id` do take tem de ser o do
    subclipe, NÃO o do master que ele referencia. Apontar a timeline para o
    master traria o arquivo inteiro em vez do recorte."""
    lidos, _ = _takes.ler(str(bin_sincronizada))
    take = next(t for t in lidos if t.trechos)

    destino = tmp_path / "sub.avb"
    with avb.open(str(bin_sincronizada)) as f:
        mob, _ = _subclipes.montar_mob(f, take)
        esperado = str(mob.mob_id)
        f.content.uid = 21
        f.write(str(destino))

    relidos, forma = _takes.ler(str(destino))

    assert forma == "subclipe"
    assert relidos[0].mob_id == esperado
    # ⛔ E é DIFERENTE do mob_id dos trechos, que são os masters.
    assert relidos[0].mob_id not in {tr.mob_id for tr in relidos[0].trechos}


def test_o_take_de_SEQUENCIA_sai_SEM_mob_id_e_isso_e_a_resposta_certa(
        bin_sincronizada):
    """⚠️ Uma região de timeline não é um objeto da bin — não há clipe para
    referenciar. Vazio é honesto; inventar um id seria apontar para nada.

    ⭐ É esta ausência que faz o emissor por referência EXIGIR bin de clipes, e
    dizê-lo em vez de cunhar subclipes por baixo do pano."""
    lidos, forma = _takes.ler(str(bin_sincronizada))

    assert forma == "sequencia"
    assert all(t.mob_id == "" for t in lidos)
