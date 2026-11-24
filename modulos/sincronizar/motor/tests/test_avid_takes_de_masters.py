"""A bin só de MASTERCLIPES — a entrada mais crua que a assistência aceita.

⛔ Medido em 2026-08-29: `takes.ler` levantava `FormaDesconhecida` na `D02_SOM.avb`
(24 masters, 0 subclipes) e na `D03 SOM.avb` (36 masters). Pela premissa que o autor
estabeleceu, uma lista de masterclipes é **entrada legítima**, não um estado
incompleto a corrigir:

    sincronizar → subclipar → organizar bin por cena → trabalhar a cena
    e NENHUMA dessas etapas é interdependente.

⭐ A fixture `bin_de_masters` já é o caso exato, e com a mesma forma do material
real: três masters de som com claquete legível e um de câmera sem nenhuma.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avid import takes as _takes


def test_bin_so_de_masters_vira_takes_com_forma_MASTERCLIPE(bin_de_masters):
    """⛔ Antes disto, `FormaDesconhecida` — e a mensagem mandava sincronizar,
    que é justamente o passo que a premissa nova diz não ser pré-requisito."""
    lidos, forma = _takes.ler(str(bin_de_masters))

    assert forma == "masterclipe"
    assert len(lidos) == 4          # 3 de som + 1 de câmera


def test_a_claquete_sai_do_NOME_DO_MASTER(bin_de_masters):
    """⭐ O nome do master é o nome do arquivo que o gravador escreveu, e é ele
    que carrega a claquete — não há subclipe nem coluna neste estado."""
    lidos, _ = _takes.ler(str(bin_de_masters))
    por_nome = {t.nome: (t.cena, t.plano, t.take) for t in lidos}

    assert por_nome["PROJETO A - 05-04 C4 P1-T001"] == ("C04", "P01", "T001")
    assert por_nome["PROJETO A - 05-04 C4 P1-T002"] == ("C04", "P01", "T002")
    assert por_nome["PROJETO A - 05-04 C7 P3-T001"] == ("C07", "P03", "T001")


def test_master_sem_claquete_entra_SEM_POSICAO_e_NAO_some(bin_de_masters):
    """⛔⛔ A afirmação de ausência que o §3.2 exige: o clipe ilegível **continua
    na lista**.

    ⚠️ E o caso não é hipotético — é o do material real: o órfão
    `C04_P01-T000` da `CENAS/C04.avb` tira o áudio da própria câmera
    (`a001_03170214_C001`), e nome de câmera não tem claquete. Aqui a fixture
    reproduz a mesma forma com `a004_03170908_C001`."""
    lidos, _ = _takes.ler(str(bin_de_masters))

    sem_posicao = [t for t in lidos if t.cena is None]

    assert [t.nome for t in sem_posicao] == ["a004_03170908_C001"]
    assert (sem_posicao[0].plano, sem_posicao[0].take) == (None, None)


def test_cada_master_vira_UM_take_com_os_trechos_dele(bin_de_masters):
    """⭐ Sem sincronização não há imagem casada com som: o take sai com os
    trechos do PRÓPRIO master, e nada mais. Inventar um par seria exatamente o
    que o §3.1 proíbe.

    ⚠️ A câmera da fixture tem `picture 1`, `sound 1` e `sound 2` — a armadilha
    do `track_id` de propósito. O take dela tem de sair com os três."""
    lidos, _ = _takes.ler(str(bin_de_masters))
    por_nome = {t.nome: t for t in lidos}

    som = por_nome["PROJETO A - 05-04 C4 P1-T001"]
    assert [t.media_kind for t in som.trechos] == ["sound"] * 5
    assert [t.track_id for t in som.trechos] == [1, 2, 3, 4, 5]
    assert som.duracao == 2000

    camera = por_nome["a004_03170908_C001"]
    assert sorted(t.media_kind for t in camera.trechos) == [
        "picture", "sound", "sound"]

    # ⛔⛔ **O `start` é ZERO, e este `assert` não é decoração.** Um masterclipe
    # não foi recortado por ninguém: o take É o arquivo inteiro, do frame zero.
    # A mutação cobrou este teste — trocar `start=0` por `start=1` sobrevivia a
    # tudo, e o efeito seria todo corte deslocado de um frame, calado. É o §8 na
    # sua forma mais barata de evitar e mais cara de descobrir.
    assert all(t.start == 0 for take in lidos for t in take.trechos)
    assert all(t.deslocamento == 0 for take in lidos for t in take.trechos)


def test_a_CONVENCAO_da_claquete_chega_ao_take_de_master(bin_de_masters):
    """⛔ A mutação cobrou: `convencao` era afirmada no leitor de SUBCLIPES e não
    aqui, então trocá-la pela origem da identidade sobrevivia neste caminho.

    ⚠️ E o painel lê `convencao == "posicao"` para mostrar *"cena presumida"* ao
    editor — a troca apagaria esse aviso da tela sem quebrar teste nenhum."""
    lidos, _ = _takes.ler(str(bin_de_masters))
    por_nome = {t.nome: t for t in lidos}

    assert por_nome["PROJETO A - 05-04 C4 P1-T001"].convencao == "rotulada"
    # ⚠️ Sem claquete não há gramática que tenha casado: `None`, não inventado.
    assert por_nome["a004_03170908_C001"].convencao is None


def test_os_takes_saem_ORDENADOS_por_nome(tmp_path):
    """⚠️ Ordem estável, não a que o pyavb devolver. A lista alimenta o painel e
    o plano, e ordem instável faria duas leituras da MESMA bin produzirem
    relatórios diferentes — barato de garantir, caro de diagnosticar.

    ⛔⛔ **A bin é criada FORA de ordem, e é de propósito.** A primeira versão
    deste teste usava `bin_de_masters`, cujos masters já nascem em ordem
    alfabética — ali o `sort` é um no-op, e removê-lo passava despercebido. A
    mutação cobrou. Aqui a ordem de criação é o inverso da ordenada."""
    import avb

    from conftest import _master

    caminho = tmp_path / "fora-de-ordem.avb"
    with avb.open() as f:
        for nome in ["PROJETO A - 05-04 C4 P9-T003",
                     "PROJETO A - 05-04 C4 P1-T002",
                     "PROJETO A - 05-04 C4 P5-T001"]:
            _master(f, nome, [(1, "sound", 1000)])
        f.content.uid = 13
        f.write(str(caminho))

    lidos, _ = _takes.ler(str(caminho))

    assert [t.take for t in lidos] == ["T002", "T001", "T003"], \
        "a ordem não é a alfabética do NOME"
    assert [t.nome for t in lidos] == sorted(t.nome for t in lidos)


def test_a_duracao_e_a_da_trilha_MAIS_LONGA(tmp_path):
    """⛔⛔ A mutação cobrou este teste: na fixture `bin_de_masters` todas as
    trilhas de cada master têm o mesmo comprimento, então `max` e `min` dão o
    mesmo número e trocá-los passava despercebido.

    ⚠️ E a diferença importa no material de verdade: um master de câmera pode
    ter a imagem mais longa que o áudio (ou o contrário) por um punhado de
    frames. Pelo `min`, o take sairia mais curto que o clipe — e o corte não
    alcançaria o fim do material que existe."""
    import avb

    from conftest import _master

    caminho = tmp_path / "desiguais.avb"
    with avb.open() as f:
        _master(f, "PROJETO A - 05-04 C4 P1-T009",
                [(1, "picture", 4200), (1, "sound", 4000), (2, "sound", 3900)])
        f.content.uid = 11
        f.write(str(caminho))

    lidos, _ = _takes.ler(str(caminho))

    assert lidos[0].duracao == 4200, "saiu a trilha mais CURTA"
    assert sorted(t.length for t in lidos[0].trechos) == [3900, 4000, 4200]


def test_o_take_de_master_NAO_finge_que_houve_aparo(bin_de_masters):
    """⚠️ `duracao_bruta == duracao`: não houve sincronização, logo não houve
    aparo a descobrir. Um `duracao_bruta` maior faria o painel mostrar 'perdeu N
    frames de cauda' sobre material que ninguém aparou."""
    lidos, _ = _takes.ler(str(bin_de_masters))

    assert all(t.duracao_bruta == t.duracao for t in lidos)
    assert all(t.aparado == 0 for t in lidos)


def test_o_descarte_fica_NAO_AVALIADO_e_nao_False(bin_de_masters):
    """⛔ `None` não é `False` (§7). Sem o caminho do arquivo em disco não há
    como atestar que o take sobreviveu ao descarte do técnico de som, e dizer
    `False` seria afirmar o que não se mediu."""
    lidos, _ = _takes.ler(str(bin_de_masters))

    assert all(t.descartado is None for t in lidos)


def test_a_bin_SINCRONIZADA_continua_preferindo_a_sequencia(bin_sincronizada):
    """⭐⭐ A ordem de checagem não muda, e este teste é o que impede a regressão.

    A mesma bin tem os masters E a timeline. Uma bin sincronizada está mais
    adiante no fluxo, e ler os masters crus dela jogaria fora o pareamento
    som↔câmera que a sincronização produziu — entregando takes sem imagem sobre
    material que tem imagem."""
    lidos, forma = _takes.ler(str(bin_sincronizada))

    assert forma == "sequencia", "o ramo de masterclipe roubou a sequência"
    assert any(t.media_kind == "picture"
               for take in lidos for t in take.trechos), \
        "os takes saíram sem imagem — sinal de que vieram dos masters crus"
