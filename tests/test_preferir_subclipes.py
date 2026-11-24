"""Preferir subclipes: três faixas, e é ORDEM — nada some da lista.

⭐⭐ **Pedido do editor (2026-09-21):** *"em um trabalho real, os editores trabalham com
subclipe ou groupclipe, recorrendo ao bruto só quando não há esses tipos de arquivos. O
filtro que digo deve ser preferência e não exclusão."*

| faixa | o que é |
|---|---|
| 1 | subclipe / group clip que casou |
| 2 | master que casou e cujo material **ainda não apareceu** acima |
| 3 | master que é a origem de um recorte já mostrado — redundante |

⛔⛔ **E um recorte casa por CONTER, quando há tempo para conferir.** A fala tem segundo; a
decupagem de MÍDIA não tem posição nenhuma (ela descreve o master inteiro) e o recorte só
pode HERDÁ-LA — a tela diz qual dos dois foi.

⚠️⚠️ **A janela é por MASTER.** Um subclipe sincronizado mistura dois, com in-points
diferentes (medido no `C04_P01-T002`: imagem em 0, som em **214** frames). A fala está no
tempo do master de SOM; conferi-la contra o offset da imagem dessincroniza em 9 s, calado.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.avid import subclipes as S
from cicloassist.midia import busca as B
from cicloassist.midia import cache as C

from .test_inventario import IMAGEM, SOM, midia_de_imagem

VIZINHA = ("urn:smpte:umid:060a2b34.01010105.01010d43.13000000.99999999.1dc80000."
           "060e2b34.7f7f2a80")


def recorte(nome, chave, inicio, fim, bin="CENAS/C07.avb", especie="subclipe", fps=23.976):
    r = S.Recorte(nome=nome, bin=bin, especie=especie, duracao_s=fim - inicio,
                  fps_aprox=fps)
    r.janelas[chave] = S.Janela(inicio, fim)
    return r


@pytest.fixture
def cache_com_falas(tmp_path, monkeypatch):
    """Um master de som com três falas espalhadas, e um master de imagem decupado."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    S.esquecer()
    som = C.Midia(SOM, raiz_do_cache=tmp_path)
    som.anotar_fonte({"master_de_som": "C07_SOM"})
    som.guardar_transcricao([
        {"inicio": 10.0, "fim": 11.0, "texto": "Personagem F, bom dia.", "certeza": 0.9},
        {"inicio": 60.0, "fim": 61.0, "texto": "A Personagem F saiu.", "certeza": 0.9},
        {"inicio": 480.0, "fim": 481.0, "texto": "Cadê a Personagem F?", "certeza": 0.9},
    ])
    return tmp_path


# ── conter, e não herdar, quando há tempo ────────────────────────────────────

def test_o_recorte_so_entra_se_COBRIR_a_fala(cache_com_falas):
    """⛔ Um subclipe de 58 s de um master de 9 min não contém uma fala de 08:00. Oferecê-lo
    é um resultado errado com cara de certo — o editor carrega e não está lá."""
    chave = C.de_umid(SOM)
    recortes = {chave: [recorte("SÓ O COMEÇO", chave, 0.0, 58.0)]}

    achados = B.procurar(["personagem f"], raiz=cache_com_falas, recortes=recortes)
    do_recorte = [a for a in achados if a.item]

    assert len(do_recorte) == 1
    assert [f["texto"] for f in do_recorte[0].falas] == ["Personagem F, bom dia."], (
        "as falas de 01:00 e 08:00 estão FORA da janela"
    )
    assert do_recorte[0].herdado is False


def test_a_janela_e_do_MASTER_daquela_fonte(cache_com_falas):
    """⚠️⚠️ Um recorte que não tem janela para ESTE master não entra por ele — é a trava
    contra usar o offset da imagem para conferir uma fala."""
    chave = C.de_umid(SOM)
    so_da_imagem = recorte("OUTRO MASTER", C.de_umid(IMAGEM), 0.0, 600.0)
    achados = B.procurar(["personagem f"], raiz=cache_com_falas,
                         recortes={chave: [so_da_imagem]})
    assert [a.item for a in achados] == [""], "só o master, porque a janela não é deste"


def test_a_decupagem_de_midia_e_HERDADA_e_a_tela_diz(tmp_path, monkeypatch):
    """⭐ Ela descreve o material inteiro e não tem `inicio_frames` (medido: `None` em
    todas). Exigir posição faria a camada de imagem parar de propor subclipe nenhum."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    m = midia_de_imagem(tmp_path, nome="C07_P01")
    m.anotar({"trecho": "C07_P01", "escopo": "midia", "descricao": "close no consultório",
              "confianca": "inferido", "fonte": "visual"})
    chave = C.de_umid(IMAGEM)

    achados = B.procurar(["consultorio"], raiz=tmp_path,
                         recortes={chave: [recorte("UM PEDAÇO", chave, 0.0, 12.0)]})
    (do_recorte,) = [a for a in achados if a.item]
    assert do_recorte.herdado is True, "sem posição, o recorte herdou — e isso é dito"
    assert do_recorte.como_dicionario()["herdado"] is True


# ── as três faixas ───────────────────────────────────────────────────────────

def test_as_tres_faixas_na_ordem_que_o_editor_pediu(cache_com_falas, monkeypatch):
    """⭐⭐ O exemplo dele: subclipes primeiro, depois o master que ainda não apareceu, e
    por fim o master que é a origem de um subclipe já mostrado."""
    chave_som = C.de_umid(SOM)
    sem_recorte = C.Midia(VIZINHA, raiz_do_cache=cache_com_falas)
    sem_recorte.anotar_fonte({"master_de_som": "SEM SUBCLIPE"})
    sem_recorte.guardar_transcricao(
        [{"inicio": 5.0, "fim": 6.0, "texto": "Personagem F!", "certeza": 0.9}])

    # Um recorte que cobre TODAS as três falas do primeiro master.
    recortes = {chave_som: [recorte("C07_P01-T001", chave_som, 0.0, 600.0)]}
    achados = B.procurar(["personagem f"], raiz=cache_com_falas, recortes=recortes)

    assert [a.faixa for a in achados] == [B.FAIXA_RECORTE, B.FAIXA_NOVO, B.FAIXA_REPETIDO]
    assert achados[0].item == "C07_P01-T001", "1ª: o subclipe"
    assert achados[1].midia == "SEM SUBCLIPE", "2ª: o master que ainda não apareceu"
    assert achados[2].midia == "C07_SOM", "3ª: o master cujo recorte já apareceu"


def test_preferencia_NAO_e_exclusao(cache_com_falas):
    """⛔ O master fica na lista sempre. Foi a palavra do editor: *"deve ser preferência e
    não exclusão"*."""
    chave = C.de_umid(SOM)
    achados = B.procurar(["personagem f"], raiz=cache_com_falas,
                         recortes={chave: [recorte("TUDO", chave, 0.0, 600.0)]})
    assert any(a.item == "" and a.chave == chave for a in achados)


def test_master_com_fala_que_nenhum_recorte_alcanca_NAO_e_repetido(cache_com_falas):
    """⛔⛔ Uma fala em 08:00 que nenhum subclipe cobre é material que só existe no master.
    Mandá-lo para o fim por "já apareceu" enterraria a única linha que a tem."""
    chave = C.de_umid(SOM)
    achados = B.procurar(["personagem f"], raiz=cache_com_falas,
                         recortes={chave: [recorte("SÓ O COMEÇO", chave, 0.0, 58.0)]})
    (master,) = [a for a in achados if a.item == ""]
    assert master.faixa == B.FAIXA_NOVO
    assert master.quantas_falas == 3, "o master continua com TODAS as falas"


def test_sem_indice_de_recortes_a_ordem_e_a_de_antes(cache_com_falas):
    """⚠️ Desligar a preferência não pode mudar mais nada: é o comportamento até 20/09."""
    achados = B.procurar(["personagem f"], raiz=cache_com_falas, recortes=None)
    assert all(a.item == "" and a.faixa == B.FAIXA_NOVO for a in achados)


# ── as cópias do mesmo subclipe entre bins ───────────────────────────────────

def test_o_mesmo_recorte_em_varias_bins_e_UMA_linha(cache_com_falas):
    """⛔⛔ MEDIDO no projeto do editor: **290 pares (master, recorte) são 130 recortes
    distintos** — ele copia o subclipe entre as bins de trabalho, e um está em 6. Sem
    juntar, "personagem f" mostrava o mesmo `C04_P06-T002` cinco vezes antes de qualquer outro
    material."""
    chave = C.de_umid(SOM)
    copias = [recorte("C07_P01-T001", chave, 0.0, 600.0, bin=b)
              for b in ("ANTIGOS/C07_FALAS.avb", "CENAS/C07.avb", "ANTIGOS/C07 NOVO.avb")]
    achados = B.procurar(["personagem f"], raiz=cache_com_falas, recortes={chave: copias})

    do_recorte = [a for a in achados if a.item]
    assert len(do_recorte) == 1, "uma linha, não três"
    assert do_recorte[0].bins == ["ANTIGOS/C07 NOVO.avb", "ANTIGOS/C07_FALAS.avb",
                                  "CENAS/C07.avb"]
    assert do_recorte[0].bin == do_recorte[0].bins[0], "a linha aponta uma, e conta todas"


def test_recortes_de_nomes_diferentes_nao_se_juntam(cache_com_falas):
    """⚠️ A identidade é nome + janela. Dois subclipes podem coincidir no recorte (um take
    inteiro aparado igual), e juntá-los perderia um nome que o editor reconhece."""
    chave = C.de_umid(SOM)
    iguais_na_janela = [recorte("TAKE 01", chave, 0.0, 600.0, bin="A.avb"),
                        recorte("TAKE 01 COPIA", chave, 0.0, 600.0, bin="B.avb")]
    achados = B.procurar(["personagem f"], raiz=cache_com_falas,
                         recortes={chave: iguais_na_janela})
    assert sorted(a.item for a in achados if a.item) == ["TAKE 01", "TAKE 01 COPIA"]


# ── a janela ─────────────────────────────────────────────────────────────────

def test_a_janela_cobre_as_bordas_e_recusa_o_desconhecido():
    j = S.Janela(10.0, 20.0)
    assert j.cobre(10.0) and j.cobre(20.0) and j.cobre(15.0)
    assert not j.cobre(9.9) and not j.cobre(20.1)
    # ⚠️ `None` não é "cobre": é "não dá para saber", e quem chama decide.
    assert not j.cobre(None)


# ── pela rota, como a tela vê ────────────────────────────────────────────────

def test_a_rota_diz_quantos_ficaram_abaixo_do_corte(cache_com_falas, monkeypatch):
    """⛔⛔ Com 1.093 masters no projeto, reordenar sem contar empurraria a 3ª faixa para
    fora — a preferência viraria exclusão CALADA, o oposto do que o editor pediu."""
    from cicloassist.servico import rotas as R
    from cicloassist.servico.http import Pedido

    chave = C.de_umid(SOM)
    monkeypatch.setattr(R, "_recortes_do_projeto",
                        lambda **_: {chave: [recorte("TUDO", chave, 0.0, 600.0)]})

    def frase(corpo):
        r = R.ROTAS[("POST", "/busca/frase")][0](
            Pedido("POST", "/busca/frase", {}, json.dumps(corpo).encode("utf-8")))
        return json.loads(r.corpo.decode("utf-8"))

    tudo = frase({"termos": "personagem f"})
    assert tudo["preferir_subclipes"] is True, "ligado por padrão"
    assert tudo["fora_do_corte"] == 0
    assert tudo["achados"][0]["especie"] == "subclipe"

    apertado = frase({"termos": "personagem f", "quantos": 1})
    assert apertado["quantos"] == 1 and apertado["fora_do_corte"] == 1

    desligado = frase({"termos": "personagem f", "preferir_subclipes": False})
    assert desligado["preferir_subclipes"] is False
    assert all(a["especie"] == "master" for a in desligado["achados"])
