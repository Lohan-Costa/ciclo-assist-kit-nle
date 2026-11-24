"""O blob do `Source Text` do Premiere: ler e escrever sem perder campo (`cicloassist/carta/titulo_prproj.py`).

Os blobs de `dados/titulo_source_text.txt` são REAIS: a camada "New Text Layer" do 26.5.2 (Windows) e o Basic Title
com Arial do 23.6 (Mac). O título escrito por este módulo foi reaberto no 26.5.2 e o painel mostrou cada valor; o
Premiere regravou o blob sem diferença (2026-11-20, banco `prproj/titulo-essential-graphics.md`)."""

from pathlib import Path

import pytest

from cicloassist.carta import titulo_prproj as T

_DADOS = Path(__file__).with_name("dados").joinpath("titulo_source_text.txt")
if not _DADOS.is_file():   # os blobs são de produção real e não vão à cópia pública: pula dizendo, não derruba a suíte
    pytest.skip(f"faltam os blobs reais ({_DADOS.name})", allow_module_level=True)
NOVO_265, ARIAL_236 = _DADOS.read_text().split()


@pytest.mark.parametrize("b64", [NOVO_265, ARIAL_236])
def test_ida_e_volta_sem_perder_campo(b64):
    arv = T.ler(b64)
    assert T.ler(T.escrever(arv)) == arv


def test_o_que_se_le_da_camada_do_26():
    doc = T.ler(NOVO_265)["campos"][0][1]["campos"]
    assert doc[1] == ("vecstr", ["LucidaConsole"])              # as fontes: vetor de STRINGS (nome PostScript)
    trecho = doc[0][1][0]["campos"]
    assert trecho[0] == ("str", "New Text Layer")
    assert trecho[1][1]["campos"][6] == ("f32", 4.0)           # o contorno da camada nova nasce com 4


def test_escrever_texto_fonte_corpo_e_cor():
    arv = T.ler(NOVO_265)
    doc = arv["campos"][0][1]["campos"]
    estilo = doc[0][1][0]["campos"][1][1]["campos"]
    doc[0][1][0]["campos"][0] = ("str", "PRODUCAO-A — título")
    doc[1] = ("vecstr", ["ArialMT"])
    estilo[1] = ("f32", 137.0)
    estilo[2] = ("tab", {"_": "tab", "tipo": "cor", "campos": {0: ("u8", 0xC8), 1: ("u8", 0x32), 2: ("u8", 0x14)}})
    b64 = T.escrever(arv)
    relido = T.ler(b64)
    assert relido == arv
    d = relido["campos"][0][1]["campos"]
    assert d[0][1][0]["campos"][0] == ("str", "PRODUCAO-A — título")
    assert d[0][1][0]["campos"][1][1]["campos"][2][1]["campos"][1] == ("u8", 0x32)


def test_cabecalho_errado_e_recusado():
    import base64
    cru = bytearray(base64.b64decode(NOVO_265))
    cru[8] ^= 0xFF
    with pytest.raises(T.TituloErro):
        T.ler(base64.b64encode(bytes(cru)).decode())


def test_titulo_do_avid_nao_herda_o_estilo_do_molde():
    """⛔ A camada nova do Premiere herda o último estilo da sessão: o molde pode vir com fundo, itálico, sombra…"""
    arv = T.ler(NOVO_265)
    doc = arv["campos"][0][1]["campos"]
    est = doc[0][1][0]["campos"][1][1]["campos"]
    est.update({15: ("u8", 1), 12: ("u32", 2), 8: ("f32", 23.0), 5: ("u8", 1)})
    doc.update({18: ("u8", 1), 11: ("u8", 1), 19: ("f32", 45.0)})
    legacy = {"titulador": "Avid Titler+ Legacy", "estilo_lido": False, "fundo": None,
              "caixas": [{"texto": "producao a", "fonte": {"familia": "", "estilo": ""}, "corpo": None, "cor": None,
                          "alinhamento": "centro", "posicao": None, "contorno": None, "sombra": None}]}
    arv, pos, avisos = T.compor_do_avid(arv, legacy, legacy["caixas"][0], 1920, 1080)
    relido = T.ler(T.escrever(arv))
    d = relido["campos"][0][1]["campos"]
    e = d[0][1][0]["campos"][1][1]["campos"]
    assert d[0][1][0]["campos"][0] == ("str", "PRODUCAO-A") and d[1] == ("vecstr", ["ArialMT"])
    assert not {15, 12, 8, 5} & set(e) and not {18, 11, 19} & set(d)
    assert e[1] == ("f32", 90.0) and d[4] == ("u32", 2) and d[5] == ("u32", 1)
    assert pos is None and any("padrão" in a for a in avisos)


def test_o_estilo_do_titler_legacy_da_cruz():
    """O JSON real do Legacy da PRODA_CORTE (CFUserParam c6219ca9…) + a escala (0,85) e a linha de base (0,527761) dos
    params sem nome → o modelo neutro → o blob do Premiere. Medido contra o export do Avid (2026-11-20): Arial 102 px,
    branca, centrada, o pé das maiúsculas em y = 570."""
    import json
    import sys
    raiz = Path(__file__).resolve().parents[1] / "modulos" / "conformar" / "motor"
    sys.path.insert(0, str(raiz))
    from titulos import avid as A
    js = json.loads(Path(__file__).with_name("dados").joinpath("titler_legacy_cruz_estilo.json").read_text(encoding="utf-8"))
    t = A.bloco(A.EID_LEGACY, "Avid Titler+", ["PRODUCAO-A"])
    esc = {A.UUID_ESCALA_LEGACY[0]: 0.85, A.UUID_ESCALA_LEGACY[1]: 0.85, A.UUID_BASE_LEGACY[0]: 0.5277608196355839}
    A.estilo_legacy(t, js, esc, '<variable attribut="vt_res" value="1080"/><variable attribut="FEjust_x" value="1"/>')
    cx = t["caixas"][0]
    assert t["estilo_lido"] and cx["fonte"] == {"familia": "Arial", "estilo": ""}
    assert round(cx["corpo"] * 1080, 1) == 102.0 and cx["cor"] == [1.0, 1.0, 1.0] and cx["alinhamento"] == "centro"
    assert cx["contorno"] is None and t["fundo"] is None
    dx, dy = cx["sombra"]["deslocamento"]
    assert dx > 0 > dy                                   # 135° = sombra para baixo-direita
    arv, pos, _ = T.compor_do_avid(T.ler(NOVO_265), t, cx, 1920, 1080)
    d = arv["campos"][0][1]["campos"]
    assert pos == (0.5, 0.527761)
    assert d[13] == ("f32", 135.0) and round(d[14][1], 2) == 6.0 and d[12] == ("f32", 100.0)
    assert d[0][1][0]["campos"][1][1]["campos"][1] == ("f32", 102.0)
