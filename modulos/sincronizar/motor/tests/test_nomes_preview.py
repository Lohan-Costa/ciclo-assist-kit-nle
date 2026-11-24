"""O preview: a resposta única que desenha a tela das duas abas.

⭐⭐ Uma implementação só da gramática. O espelho colorido da caixa de padrão podia ser
calculado no JS — era o plano —, mas aí existiriam duas implementações da mesma regra, e a
que divergisse seria a do PREVIEW contra a do APLICAR. Mandando os tokens prontos, o que o
editor vê pintado é literalmente o que o motor entendeu.

⚠️ Portados do Assist anterior, onde nasceram como parte de `tests/preparar/test_renomear.py`.
Aqui eles medem o NÚCLEO — `nomes/preview.py` não sabe o que é Avid, bin nem subclipe —, e
por isso a costura com o Media Composer não aparece em lugar nenhum deste arquivo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nomes import preview as R



def test_preview_marca_o_campo_vazio_sem_bloquear():
    """⭐ A decisão do autor: campo presente e vazio RENDERIZA e MARCA; não bloqueia.
    É o caso do `AMB` da D04 e de todo o Projeto C."""
    fichas = [{"cena": "15", "take2": "01"}, {"cena": "", "take2": "01"}]
    r = R.prever("C%cena_T%take2", fichas)
    assert r["bloqueado"] is False
    assert [l["nome"] for l in r["linhas"]] == ["C15_T01", "C_T01"]
    assert r["linhas"][0]["vazios"] == []
    assert r["linhas"][1]["vazios"] == ["cena"]


def test_preview_marca_a_COLISAO_dos_dois_lados():
    fichas = [{"cena": "15"}, {"cena": "15"}, {"cena": "16"}]
    r = R.prever("C%cena", fichas)
    assert [l["repetido"] for l in r["linhas"]] == [True, True, False]
    assert r["bloqueado"] is False


def test_preview_BLOQUEIA_no_campo_desconhecido():
    r = R.prever("C%xyz", [{"cena": "15"}])
    assert r["bloqueado"] is True
    assert r["invalidos"][0]["bruto"] == "%xyz"
    assert r["invalidos"][0]["inicio"] == 1
    assert r["linhas"] == [], "não se mostra preview de padrão inválido"


def test_nome_que_sai_vazio_MANTEM_o_nome_de_agora():
    """⭐ Decisão do autor, 2026-09-17 (Premiere, e no mesmo dia o Avid): o metadado
    vazio não trava o lote — o item fica como está, marcado."""
    r = R.prever("%cena", [{"cena": "15", "name": "A"}, {"cena": " ", "name": "B"}])
    assert r["bloqueado"] is False
    assert [(l["nome"], l["de_origem"]) for l in r["linhas"]] == [("15", False),
                                                                  ("B", True)]
    assert r["linhas"][1]["vazios"] == ["cena"]
    assert r["linhas"][1]["vazio_total"] is False


def test_preview_BLOQUEIA_quando_nem_o_nome_de_agora_existe():
    """⚠️ Um clipe não pode se chamar nada. Sem nome para manter, basta UM item vazio
    para bloquear o lote — aplicar metade é pior que não aplicar."""
    r = R.prever("%cena", [{"cena": "15"}, {"cena": ""}])
    assert r["bloqueado"] is True
    assert r["linhas"][1]["vazio_total"] is True


def test_preview_devolve_os_TOKENS_para_o_painel_pintar():
    """⭐⭐ Uma implementação só da gramática.

    O espelho colorido da caixa de texto podia ser calculado no JS — era o plano —, mas
    aí existiriam duas implementações da mesma regra, e a que divergisse seria a do
    PREVIEW contra a do APLICAR. Mandando os tokens prontos, o que o editor vê pintado
    é literalmente o que o motor entendeu.
    """
    r = R.prever("C%cena_P%plano", [{"cena": "15", "plano": "02"}])
    campos = [(t["campo"], t["inicio"], t["fim"], t["cauda"]) for t in r["tokens"]]
    #                                        ↓ o recuo devolveu `_P` ao literal
    assert campos == [("cena", 1, 6, "_P"), ("plano", 8, 14, "")]


def test_o_token_invalido_tambem_vem_nos_tokens():
    """O espelho pinta de vermelho a partir da MESMA lista — sem uma segunda passagem
    que pudesse discordar de `invalidos`."""
    r = R.prever("C%xyz", [{"cena": "15"}])
    assert [t["campo"] for t in r["tokens"]] == [None]
    assert r["tokens"] == r["invalidos"]


def test_preview_de_padrao_vazio_bloqueia():
    assert R.prever("", [{"cena": "15"}])["bloqueado"] is True


def test_preview_sem_item_nenhum_bloqueia_sem_estourar():
    r = R.prever("C%cena", [])
    assert r["bloqueado"] is True and r["linhas"] == []
