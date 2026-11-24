"""O journal de renomeação: o desfazer que mora FORA da bin do editor.

⭐⭐ Por que fora: o Assist anterior guardava o nome antigo numa coluna custom e
removeu a tentativa inteira. `CreateCustomColumn` cria uma coluna NOVA a cada
chamada — nove `GA Nome Original` lado a lado na bin de teste — e o MCAPI não tem
rpc de apagar coluna. Além disso ela guardava o nome ANTERIOR, não o original.

Os dois defeitos viram teste aqui, na direção certa: o nº 1 vira "a bin não é
tocada" (não há o que testar: não existe chamada de coluna neste caminho) e o nº 2
vira `test_o_nome_ORIGINAL_sobrevive_a_segunda_renomeacao`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import appsettings
from avid import desfazer


@pytest.fixture
def diario(monkeypatch, tmp_path):
    """O journal apontado para uma pasta descartável."""
    monkeypatch.setattr(appsettings, "app_data_dir", lambda: tmp_path)
    return tmp_path / "renomeacoes"


def _item(mob, antes, depois, bin_="C:/Proj/BIN.avb"):
    return {"mob_id": mob, "bin": bin_, "tipos": ["masterClips"],
            "nome_atual": antes, "nome_novo": depois}


def _gravar(id_, itens, padrao="C%cena"):
    return desfazer.gravar(id_do_lote=id_, projeto="C:/Proj", padrao=padrao,
                           mc_info={"app": "Media Composer", "version": "2025.6"},
                           itens=itens)


# ── gravar e reler ───────────────────────────────────────────────────────────

def test_o_lote_gravado_volta_inteiro(diario):
    _gravar("L1", [_item("a" * 64, "A001", "C04_T01")])

    d = desfazer.lote("L1")
    assert d["padrao"] == "C%cena"
    assert d["itens"][0]["nome_antes"] == "A001"
    assert d["itens"][0]["nome_depois"] == "C04_T01"
    assert d["bins"] == ["C:/Proj/BIN.avb"]


def test_o_plano_de_volta_INVERTE_o_lote(diario):
    _gravar("L1", [_item("a" * 64, "A001", "C04_T01")])

    volta = desfazer.plano_de_volta(desfazer.lote("L1"))
    assert volta[0]["nome_atual"] == "C04_T01"    # o que está no Avid agora
    assert volta[0]["nome_novo"] == "A001"        # para onde volta


def test_o_nome_ORIGINAL_sobrevive_a_segunda_renomeacao(diario):
    """⭐⭐ O defeito nº 2 da coluna `GA Nome Original`, virado teste.

    Ela guardava o nome ANTERIOR e prometia o original. Aqui os dois campos são
    separados, e é isso que permite oferecer duas coisas honestamente diferentes:
    *desfazer o último lote* e *voltar ao nome original*.
    """
    mob = "a" * 64
    _gravar("L1", [_item(mob, "A001", "C04_T01")])
    _gravar("L2", [_item(mob, "C04_T01", "CENA4_TAKE1")])

    d2 = desfazer.lote("L2")
    assert d2["itens"][0]["nome_antes"] == "C04_T01"
    assert d2["itens"][0]["nome_original"] == "A001", (
        "o original é o do PRIMEIRO lote, não o do anterior")

    # O desfazer de LOTE volta ao nome ANTERIOR — é o que ele promete.
    assert desfazer.plano_de_volta(d2)[0]["nome_novo"] == "C04_T01"
    # E o ORIGINAL continua alcançável, por outro caminho: o campo
    # `%nome_original`, cujo escopo é o que está na tela. Ver `originais_de`.
    assert desfazer.originais_de([mob])[mob] == "A001"


def test_desfazer_sem_id_pega_o_ultimo_AINDA_NAO_revertido(diario):
    """⚠️ "O último" seria errado: desfazer duas vezes seguidas tentaria reverter
    o mesmo lote de novo, e o anterior — o que o editor quer — ficaria parado
    atrás."""
    _gravar("L1", [_item("a" * 64, "A001", "X1")])
    _gravar("L2", [_item("b" * 64, "B001", "X2")])

    assert desfazer.lote()["id"] == "L2"
    desfazer.atualizar("L2", revertido=True)
    assert desfazer.lote()["id"] == "L1"


# ── robustez ─────────────────────────────────────────────────────────────────

def test_journal_corrompido_nao_derruba_a_leitura(diario):
    _gravar("L1", [_item("a" * 64, "A001", "X1")])
    (diario / "L0.json").write_text("{isto não é json", encoding="utf-8")

    # O bom continua sendo lido, e o quebrado é ignorado em silêncio.
    assert desfazer.lote("L1") is not None
    assert [h["id"] for h in desfazer.historico()] == ["L1"]


def test_lote_de_versao_FUTURA_e_ignorado_e_nao_interpretado(diario):
    """⚠️ Meio-desfazer é pior que não desfazer: um formato que não conhecemos
    não pode ser lido pela metade."""
    diario.mkdir(parents=True, exist_ok=True)
    (diario / "L9.json").write_text(
        json.dumps({"id": "L9", "versao": 999, "itens": [{"mob_id": "x"}]}),
        encoding="utf-8")
    assert desfazer.lote("L9") is None


def test_pasta_inexistente_devolve_historico_vazio(monkeypatch, tmp_path):
    monkeypatch.setattr(appsettings, "app_data_dir", lambda: tmp_path / "nao-existe")
    assert desfazer.historico() == []
    assert desfazer.lote() is None


def test_o_journal_mora_nos_DADOS_e_nao_no_cache(monkeypatch, tmp_path):
    """⚠️ O cache é purgável por política — um histórico que some quando o cache
    enche não é histórico."""
    monkeypatch.setattr(appsettings, "app_data_dir", lambda: tmp_path)
    assert appsettings.rename_journal_dir() == tmp_path / "renomeacoes"
    assert "cache" not in str(appsettings.rename_journal_dir()).lower()


# ── a poda ───────────────────────────────────────────────────────────────────

def test_a_poda_mantem_os_mais_recentes(diario):
    for n in range(desfazer.RETENCAO + 5):
        _gravar(f"L{n:03d}", [_item("a" * 64, f"N{n}", f"X{n}")])

    ids = [h["id"] for h in desfazer.historico(limite=99)]
    assert len(ids) == desfazer.RETENCAO
    assert "L000" not in ids and ids[0] == f"L{desfazer.RETENCAO + 4:03d}"


def test_a_poda_PROPAGA_o_nome_original_do_lote_que_sai(diario):
    """⚠️⚠️ Sem isto, podar apagaria em silêncio a única cópia de um nome
    original — e o "voltar ao original" passaria a mentir, devolvendo um nome
    intermediário como se fosse o primeiro."""
    mob = "a" * 64
    _gravar("L000", [_item(mob, "O_ORIGINAL", "P1")])
    for n in range(1, desfazer.RETENCAO + 1):
        _gravar(f"L{n:03d}", [_item(mob, f"P{n}", f"P{n + 1}")])

    ids = [h["id"] for h in desfazer.historico(limite=99)]
    assert "L000" not in ids, "o mais velho tinha de ter saído"

    # O lote retido MAIS ANTIGO herdou o original do que saiu.
    mais_antigo = desfazer.lote(ids[-1])
    assert mais_antigo["itens"][0]["nome_original"] == "O_ORIGINAL"


# ── `%nome_original`: escopo de CLIPE, não de lote ───────────────────────────

def test_originais_de_responde_SO_o_que_foi_pedido(diario):
    """⭐⭐ O achado do autor, virado teste.

    Ele renomeou 150 itens, trouxe 5 para a tela e pediu "voltar ao nome
    original" — e voltaram os 150. O botão operava sobre o LOTE; o que a mão de
    quem usa esperava era ESTES CLIPES. Como campo, o escopo é o da tela.
    """
    itens = [_item(f"{n:064d}", f"ORIG{n}", f"NOVO{n}") for n in range(150)]
    _gravar("L1", itens)

    pedidos = [f"{n:064d}" for n in (3, 7, 11, 42, 99)]
    r = desfazer.originais_de(pedidos)

    assert set(r) == set(pedidos), "só os pedidos, nunca o lote inteiro"
    assert r[f"{42:064d}"] == "ORIG42"


def test_o_original_e_o_PRIMEIRO_nome_visto_nao_o_mais_recente(diario):
    mob = "a" * 64
    _gravar("L1", [_item(mob, "O_PRIMEIRO", "meio")])
    _gravar("L2", [_item(mob, "meio", "atual")])

    assert desfazer.originais_de([mob])[mob] == "O_PRIMEIRO"


def test_mob_sem_historico_nao_aparece_no_resultado(diario):
    """⚠️ Nunca se inventa um "original" para quem este app nunca renomeou —
    quem preenche o campo com o nome de agora é o `levantar`, e ali isso está
    escrito."""
    _gravar("L1", [_item("a" * 64, "ORIG", "NOVO")])
    r = desfazer.originais_de(["a" * 64, "b" * 64])

    assert "a" * 64 in r
    assert "b" * 64 not in r


def test_pedir_nada_nao_varre_o_historico(diario):
    _gravar("L1", [_item("a" * 64, "ORIG", "NOVO")])
    assert desfazer.originais_de([]) == {}
    assert desfazer.originais_de(None) == {}
