"""A claquete de um subclipe cujo NOME não parseia — ela vem do master.

⛔⛔ Medido em 2026-08-29 sobre a `CENAS/C04.avb` do autor: os 16 clipes voltavam
com `cena=None`, `plano=None`, `take=None`. O nome deles é `C04_P06-T003`, com
hífen antes do T, e nem `_de_nome_de_subclipe` nem `claquete.ler` o resolvem — mas
o nome do master, `PROJETO A - 05-04 C4 P6-T003`, resolve inteiro. E
`takes_de_subclipes` **já calcula** esse nome, em `nome_do_som`; só não o usava.

⚠️ Sem isto, `montador._chave_do_take` ordena por três campos vazios, e a regra do
"último take da série" — que é a regra de escolha do produto — degenera em silêncio.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pathlib import Path

import avb

from avid import subclipes as _subclipes
from avid import takes as _takes


def _bin_com_subclipe_de_nome_ilegivel(bin_de_origem: Path, destino: Path,
                                       nome_do_subclipe: str) -> Path:
    """Uma bin com UM subclipe cujo nome não parseia, sobre masters que parseiam.

    ⭐ Usa `subclipes.montar_mob`, o código de PRODUÇÃO, e só troca o nome do mob
    depois — que é exatamente a situação da bin real do autor: os subclipes
    existem, os masters estão junto, e o nome do subclipe não é o canônico.
    """
    lidos, _forma = _takes.ler(str(bin_de_origem))
    take = next(t for t in lidos if t.trechos)

    with avb.open(str(bin_de_origem)) as f:
        mob, _ = _subclipes.montar_mob(f, take)
        mob.name = nome_do_subclipe
        f.content.uid = 7
        f.write(str(destino))
    return destino


def test_subclipe_com_nome_ilegivel_herda_a_claquete_do_MASTER(
        bin_sincronizada, tmp_path):
    caminho = _bin_com_subclipe_de_nome_ilegivel(
        bin_sincronizada, tmp_path / "cena.avb", "C04_P06-T003")

    lidos, forma = _takes.ler(str(caminho))

    assert forma == "subclipe"
    assert len(lidos) == 1
    # ⛔ Antes desta mudança os três saíam `None`.
    assert lidos[0].cena is not None, "a claquete do master não foi herdada"
    assert lidos[0].plano is not None
    assert lidos[0].take is not None

    # ⛔⛔ `convencao` é a GRAMÁTICA que casou, não o degrau que resolveu.
    #
    # A mutação cobrou este `assert`: trocar `convencao=ident.convencao` por
    # `ident.origem` sobrevivia a tudo, porque a convenção só era testada dentro
    # de `clipes/identidade.py` e nunca na LIGAÇÃO, que é aqui. E o painel lê
    # `convencao == "posicao"` para mostrar *"cena presumida"* ao editor — com a
    # troca, esse aviso sumiria da tela sem quebrar teste nenhum.
    assert lidos[0].convencao == "rotulada", (
        "a convenção da claquete foi trocada pelo degrau da identidade")


def test_o_nome_CANONICO_do_subclipe_continua_ganhando_do_master(
        bin_sincronizada, tmp_path):
    """⚠️⚠️ A PRECEDÊNCIA INVERTEU em 2026-09-05, e a decisão é do autor:

    > *"O nome e a identidade da cena deve vir da coluna cena dos sons diretos.
    > Tentar resolver pelo nome não é uma boa abordagem, pois tem a variação do
    > técnico de som que coloca a convenção que quiser."*

    Até aqui o NOME do subclipe ganhava — *"a renomeação é declaração"*. Agora
    ganha a COLUNA que o próprio subclipe carrega (`Scene`/`Take` no `_USER`,
    gravadas por `subclipes.montar_mob`).

    ⭐ E a inversão fica coerente com o produto: a coluna é o campo que o editor
    **edita na tabela** da aba Subclipar. Fazer o nome vencer o que ele acabou de
    digitar na coluna seria ignorar a correção dele.

    ⚠️ O que se perde: renomear o subclipe à mão deixou de mudar a identidade
    dele. Quem quiser corrigir a cena, corrige a cena.
    """
    caminho = _bin_com_subclipe_de_nome_ilegivel(
        bin_sincronizada, tmp_path / "cena.avb", "C09_P09_T009")

    lidos, _ = _takes.ler(str(caminho))

    assert (lidos[0].cena, lidos[0].plano, lidos[0].take) == ("C04", "P01", "T001"),         "a coluna do próprio subclipe tem de ganhar do nome dele"


def test_nem_o_clipe_nem_o_master_legiveis_deixa_o_take_SEM_POSICAO(
        bin_sincronizada, tmp_path):
    """⛔ A afirmação de ausência que o §3.2 exige: o clipe **continua na lista**,
    com os campos vazios. Sumir seria pior — ele ainda pode conter a fala; o que
    ele não pode é vencer a corrida do 'mais tardio'."""
    caminho = _bin_com_subclipe_de_nome_ilegivel(
        bin_sincronizada, tmp_path / "cena.avb", "gravação de ambiente")

    lidos, _ = _takes.ler(str(caminho))

    assert len(lidos) == 1, "o clipe ilegível sumiu da lista"
    assert lidos[0].nome == "gravação de ambiente"
