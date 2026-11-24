"""As camadas do Ciclo × as do colorista (atualizar corte com efeitos, 2026-11-23). Os BLGs são REAIS (scene "LAB ATUALIZAR
EXP" do PRODUCAO-C, Baselight 7.0.3 Mac): um plano com o CDL do colorista sobre a imagem e um com o Transform do Motion.
A prova inteira (o atualizar × a v2 montada do zero com a mesma cor: 1591 de 1591 quadros iguais) é do laboratório
`estudo/ferramentas/lab_atualizar_efeitos.py`."""
from __future__ import annotations

import sqlite3
import struct
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import camadas as C  # noqa: E402

DADOS = RAIZ / "tests" / "dados" / "baselight"
CDL = (DADOS / "PRODC_plano_cdl.blg.txt").read_text(encoding="latin1")
TRANSFORM = (DADOS / "PRODC_plano_transform.blg.txt").read_text(encoding="latin1")


def test_marcar_poe_o_nome_do_ciclo_e_nao_toca_na_midia():
    m = C.marcar(TRANSFORM)
    fx = C.faixas(m)
    assert [(f["nome"], f["ciclo"], f["midia"]) for f in fx] == [("Ciclo Transform", True, False), ("4", False, True)]
    assert "15:Ciclo Transform " in m
    assert C.marcar(m) == m                                   # de novo não muda nada


def test_o_colorista_sai_sem_as_camadas_do_ciclo():
    col = C.do_blg(C.marcar(TRANSFORM))
    assert col == []
    col = C.do_blg(CDL)
    assert [(x["nome"], x["onde"]) for x in col] == [("Layer:1", "baixo")]
    assert C.impressao(col).startswith("GR_CDLGradeRop:1.2,1,0.8")


def test_juntar_poe_o_colorista_sobre_a_imagem_e_mantem_os_efeitos_da_v2():
    base = C.marcar(TRANSFORM)
    col = C.do_blg(CDL)
    j = C.juntar(base, col, C.deslocar_chaves)
    assert [(f["nome"], f["linha"]) for f in C.faixas(j)] == [("Ciclo Transform", 0), ("Layer:1", 1), ("4", 2)]
    assert C.impressao(C.do_blg(j)) == C.impressao(col)
    assert C.impressao_do_ciclo(j) == C.impressao_do_ciclo(base)


def test_juntar_em_cima_vai_ao_topo():
    base = C.marcar(TRANSFORM)
    col = [{**x, "onde": "cima"} for x in C.do_blg(CDL)]
    j = C.juntar(base, col)
    assert [f["nome"] for f in C.faixas(j)] == ["Layer:1", "Ciclo Transform", "4"]


def test_separar_por_lugar():
    pilha = [{"nome": "A", "ciclo": False}, {"nome": "Ciclo X", "ciclo": True}, {"nome": "B", "ciclo": False},
             {"nome": "Ciclo Y", "ciclo": True}, {"nome": "C", "ciclo": False}, {"midia": True, "ciclo": False}]
    s = {x["nome"]: (x["onde"], bool(x["aviso"])) for x in C.separar(pilha)}
    assert s == {"A": ("cima", False), "B": ("baixo", True), "C": ("baixo", False)}
    # sem camada do Ciclo: tudo logo acima da imagem (a cor age antes do efeito que a v2 trouxer)
    assert [x["onde"] for x in C.separar([{"nome": "A", "ciclo": False}, {"midia": True, "ciclo": False}])] == ["baixo"]


def test_impressao_do_ciclo_le_menos_zero_como_zero():
    """⛔ MEDIDO (PRODC, 2026-11-23): o Baselight relê o −0,0 do Transform como 0 — a conferência dava 35 falsos "não"."""
    base = C.marcar(TRANSFORM)
    assert C.impressao_do_ciclo(base) == C.impressao_do_ciclo(base.replace("f 0000000000000000", "f 8000000000000000"))


def test_deslocar_chaves_refaz_o_comprimento():
    corpo = "6 0 2 0 1 0 0 0 0 0.5 2 0 0 0 0 0 17 -1 0.001 0  "
    e = f"0 t 0000000000000000 {len(corpo) - 1}:{corpo}"
    d = C.deslocar_chaves(e, 0.25)
    n, novo = d.split(" ", 3)[3].split(":", 1)
    assert int(n) == len(novo) - 1 and novo.split()[3] == "0.25" and novo.split()[9] == "0.75"
    assert C.deslocar_chaves("0 f 3ff0000000000000 21:6 0 0 0 0 -1 0.001 1  ", 1.0).startswith("0 f 3ff0")


def _blscene(caminho: Path, fps: float):
    """Um `.blscene` mínimo (o formato do `bl-export`: Object × State): dois planos na mesma trilha (bloco 1, linhas
    1024…) e um na de cima (bloco 0) ao mesmo tempo do 2º — o de baixo tem o CDL do colorista e o Transform do Ciclo."""
    con = sqlite3.connect(caminho)
    con.executescript("create table State(Id integer, Data text); create table Object(Id integer, DeltaId integer, "
                      "Revision integer, TypeId integer, Children text, StateId integer);")
    estados: dict[str, int] = {}

    def st(texto):
        if texto not in estados:
            estados[texto] = len(estados) + 1
            con.execute("insert into State values (?, ?)", (estados[texto], texto))
        return estados[texto]

    def obj(i, tipo, filhos, estado, delta=1):
        con.execute("insert into Object values (?, ?, 1, ?, ?, ?)",
                    (i, delta, st(tipo), "{" + ",".join(map(str, filhos)) + "}", st(estado)))

    h = lambda q: struct.pack(">d", q / fps).hex()  # noqa: E731
    def faixa(i, mold, a, b, linha):
        obj(i, "GM_Strip gm", [mold], f"1 o 0 {h(a)} {h(b)} {linha} f f 0 ")
    # o plano 1 (0–24, bloco 1): só a mídia
    obj(10, "GR_SequenceRop gr_sequence", [], "0 d s9:A001.mov d f0x0p+0 ")
    obj(11, "GR_InsideOutsideRop gr_insideoutside", [10], "2 d Z f 0000000000000000 z 42ca0000 3f800000 ")
    faixa(12, 11, 0, 24, 1024)
    # o plano 2 (24–48, bloco 1): o Transform do Ciclo, o CDL do colorista (com "×" do UTF-8 no rótulo), a mídia
    obj(20, "GR_SequenceRop gr_sequence", [], "0 d s9:B002.mov d s13:(1024×540) ")
    obj(21, "GR_InsideOutsideRop gr_insideoutside", [20], "2 d Z f 0000000000000000 z 42ca0000 3f800000 ")
    faixa(22, 21, 24, 48, 1027)
    obj(23, "GR_TransformRop gr_transform", [], "6 z 15:Ciclo Transform 42c90000 3f19999a 00000000 ")
    faixa(24, 23, 24, 48, 1024)
    obj(25, "GR_CDLGradeRop gr_cdl", [], "f 3ff3333333333333 f 3ff0000000000000 ")
    obj(26, "GR_InsideOutsideRop gr_insideoutside", [25], "2 d Z f 0000000000000000 7:Layer:1 42c80000 3f800000 ")
    faixa(27, 26, 24, 48, 1026)
    # o plano da trilha de cima (24–48, bloco 0)
    obj(30, "GR_SequenceRop gr_sequence", [], "0 d s9:C003.mov d f0x0p+0 ")
    obj(31, "GR_InsideOutsideRop gr_insideoutside", [30], "2 d Z f 0000000000000000 z 42ca0000 3f800000 ")
    faixa(32, 31, 24, 48, 0)
    # uma faixa que SAIU da timeline (versão antiga da scene): fica no arquivo, mas o GM_Timeline não a lista
    obj(40, "GR_CDLGradeRop gr_cdl", [], "f 4000000000000000 f 4000000000000000 ")
    obj(41, "GR_InsideOutsideRop gr_insideoutside", [40], "2 d Z f 0000000000000000 7:Layer:2 42c80000 3f800000 ")
    faixa(42, 41, 0, 48, 1025)
    obj(9, "GM_Timeline gm", [12, 22, 24, 27, 32, 7, 8], "3 0 0 ")
    # a mudança NÃO salva da interface (o delta 2, depois do salvo): o CDL do colorista mexido — não vale
    obj(25, "GR_CDLGradeRop gr_cdl", [], "f 4008000000000000 f 4008000000000000 ", delta=2)
    con.executescript("create table Delta(Id integer, ParentDeltaId integer); insert into Delta values (1, 0), (2, 1);"
                      "create table Reference(Id integer, Name text, DeltaIds text);"
                      "insert into Reference values (1, 'Main', '{1,2,1,2}');")
    con.commit()
    con.close()


def test_do_blscene_acha_a_pilha_de_cada_plano(tmp_path):
    db = tmp_path / "s.blscene"
    _blscene(db, 24.0)
    planos = [{"rec": [0, 24], "arquivo": "/x/A001.mov"}, {"rec": [24, 48], "arquivo": "/x/B002.mov"},
              {"rec": [24, 48], "arquivo": "/x/C003.mov"}, {"rec": [100, 110], "arquivo": "/x/D.mov"}]
    r = C.do_blscene(str(db), planos, 24.0)
    assert r[0] == []
    assert [(x["nome"], x["onde"]) for x in r[1]] == [("Layer:1", "baixo")]          # sem o Transform do Ciclo
    assert r[2] == []                                                                  # o de cima não leva o de baixo
    assert r[3] is None
    # os objetos já na visão de BYTES do BLG (o prefixo conta bytes: "×" = 2)
    assert C.impressao(r[1]) == "GR_CDLGradeRop:1.2,1"


def test_conferida_pela_scene_nao_deixa_o_aviso_de_leitura(monkeypatch):
    """Pela janela (2026-11-23): o TitleCard da trilha de baixo foi conferido pela scene exportada e mesmo assim ficava o
    aviso "a pilha não se lê… a cor ficou a do Multi-Paste" (e um marker a mais). A nota só vale se NÃO confirmar."""
    from baselight import enviar

    def cor():
        return {"planos": [
            {"inicio": 0, "fim": 10, "arquivo": "a.mov", "aviso": "", "conferido": "sim", "cor_esperada": "x"},
            {"inicio": 10, "fim": 20, "arquivo": "b.jpg", "aviso": "", "conferido": "não", "cor_esperada": "y",
             "nota_leitura": "não se lê"}]}
    monkeypatch.setattr(enviar, "exportar_scene", lambda *a: "/x.blscene")
    monkeypatch.setattr(C, "do_blscene", lambda db, planos, fps: [[{"objetos": {}, "raiz": 0, "nome": "L"}]])
    monkeypatch.setattr(C, "impressao", lambda col: "y")
    c = cor()
    assert enviar.conferir_pela_scene("J", "S", c, 24.0, "/tmp") == 1
    assert c["planos"][1]["aviso"] == "" and c["conferidos"] == 2
    monkeypatch.setattr(enviar, "exportar_scene", lambda *a: None)       # sem o export: a nota vira aviso
    c = cor()
    enviar.conferir_pela_scene("J", "S", c, 24.0, "/tmp")
    assert c["planos"][1]["aviso"] == "não se lê"
