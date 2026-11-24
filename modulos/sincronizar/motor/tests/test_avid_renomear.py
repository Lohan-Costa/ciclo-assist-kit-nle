"""A aba Renomear: do arrasto ao levantamento.

⭐ O que este módulo faz é ADAPTAR — o Media Composer de um lado, `nomes/` do outro. As regras de nome não moram aqui (moram em `nomes/template.py`), e a leitura
de coluna não mora aqui (mora no `avid/mcapi.py`). O que mora aqui é a costura, e é ela que
estes testes medem.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from avid import renomear as R


class _McFalso:
    """O mínimo que `renomear` chama do Media Composer.

    ⚠️ `por_tipo` imita a sobreposição REAL medida no spike de 2026-08-28: um `.wav`
    AMA responde tanto a `masterClips` quanto a `linkedMasterClips`. Um falso que
    devolvesse tipos disjuntos testaria um Avid que não existe.
    """

    def __init__(self, por_tipo=None, colunas=None, projeto=r"C:\Proj"):
        self._por_tipo = por_tipo or {}
        self._colunas = colunas or {}
        self._projeto = projeto
        self.pedidos = []

    def projeto(self, recarregar=False):
        return {"path": self._projeto}

    def caminho_relativo_da_bin(self, absoluto):
        return "BIN.avb"

    def itens_da_bin(self, rel, flags=("masterClips",), apenas_selecionados=False):
        return list(self._por_tipo.get(flags[0], []))

    def colunas_do_master(self, mob_id, todas=False):
        self.pedidos.append((mob_id, todas))
        return dict(self._colunas.get(mob_id, {}))

    def bin_do_mob(self, mob_id):
        return r"C:\Proj\BIN.avb"


class _Item:
    def __init__(self, nome, mob):
        self.name, self.mob_id, self.selected = nome, mob, False


# ── os derivadores ───────────────────────────────────────────────────────────

def test_take2_PREENCHE_e_nunca_trunca():
    """⚠️⚠️ O defeito que o script de demonstração da Fase 2 expôs: `011` virava `11`.

    `%take2` é *pelo menos dois dígitos*, não *exatamente dois*. Truncar faz take 100
    virar `00` e colidir com o take 0 — dois subclipes diferentes com o mesmo nome, e
    o editor sem nada na tela que denuncie.
    """
    assert R.derivador_de_take2({"take": "1"})["take2"] == "01"
    assert R.derivador_de_take2({"take": "01"})["take2"] == "01"
    assert R.derivador_de_take2({"take": "011"})["take2"] == "011"
    assert R.derivador_de_take2({"take": "100"})["take2"] == "100"
    assert R.derivador_de_take2({"take": "T007"})["take2"] == "007"


def test_take2_sem_take_devolve_None():
    """§11: quem não soube derivar diz que não soube. Não inventa `00`."""
    assert R.derivador_de_take2({"name": "x"}) is None
    assert R.derivador_de_take2({"take": ""}) is None
    assert R.derivador_de_take2({"take": "sem digito"}) is None


def test_a_claquete_le_a_COLUNA_antes_do_nome():
    """⭐ A ordem é a da confiança: `Scene` é o que o técnico de som escreveu; o nome do
    clipe é o que o Avid montou depois, e pode ter sido renomeado por qualquer um.

    ⚠️⚠️ E as colunas precisam ser RECOMPOSTAS. A gramática exige cena, plano e take
    juntos — é ela que protege o material de câmera —, mas a coluna `Scene` não traz o
    take: ele mora em `Take`. Sem recompor, `ler(scene)` nunca casa e o derivador cai
    calado para o nome, que é justamente a fonte menos confiável. Achado escrevendo
    este teste, não depois.
    """
    d = R.derivador_de_claquete({"scene": "C4 P1", "name": "LIXO C9 P9-T009",
                                 "take": "002"})
    assert (d["cena"], d["plano"]) == ("04", "01")


def test_a_claquete_recompoe_a_D03_como_o_gravador_escreveu():
    """O caso real, medido em `D03 SOM.avb`: `Scene` + `-T` + `Take` reconstrói
    exatamente o nome do WAV original — e é ele que a gramática sabe ler."""
    d = R.derivador_de_claquete({
        "scene": "PROJETO A - 05-04 FOLLY C9 P1 SERIE", "take": "011",
        "name": "PROJETO A - 05-04 FOLLY C9 P1 SERIE/011"})
    assert (d["cena"], d["plano"], d["take"]) == ("09", "01 SERIE", "11")


def test_a_claquete_cai_para_o_nome_quando_nao_ha_coluna():
    """O caso do PRODUCAO-A D02/D04: o Resolve apagou as colunas, sobrou o nome."""
    d = R.derivador_de_claquete({"scene": "", "name": "CENA15P2-T001"})
    assert (d["cena"], d["plano"], d["take"]) == ("15", "02", "1")


def test_a_claquete_devolve_None_no_material_que_nao_tem_cena():
    """⚠️ Projeto B (`24-1`, sem rótulo), o ambiente da D04 e o doc do Projeto C. Decisão
    do autor em 2026-08-28: sem rótulo, sem derivado."""
    for ficha in ({"scene": "24-1", "name": "24-1T01.WAV"},
                  {"scene": "", "name": "AMB-T001"},
                  {"scene": "", "name": "20260101_SOM0034_Tr12.WAV.new.01"},
                  {"scene": "", "name": ""}):
        assert R.derivador_de_claquete(ficha) is None, ficha


def test_a_claquete_devolve_a_cena_SEM_o_prefixo():
    """⭐ `%cena` vale `04`, não `C04` — quem põe o `C` é o padrão que o editor
    escreve (`C%cena`). Devolver `C04` faria `C%cena` render `CC04`, e o editor
    descobriria isso olhando o preview em vez de o motor evitar."""
    d = R.derivador_de_claquete({"scene": "", "name": "PROJETO A C4 P1-T002"})
    assert d["cena"] == "04" and d["plano"] == "01"


# ── tipos: a união das flags ─────────────────────────────────────────────────

def test_o_tipo_de_um_item_e_a_UNIAO_das_flags():
    """⚠️⚠️ Medido no spike: um `.wav` AMA responde a `masterClips` E a
    `linkedMasterClips`. Tratar tipo como valor único faria o mesmo clipe aparecer
    duas vezes na lista da aba."""
    mc = _McFalso(por_tipo={
        "masterClips": [_Item("som.wav", "MOB1"), _Item("cam.mov", "MOB2")],
        "linkedMasterClips": [_Item("som.wav", "MOB1")],
        "subclips": [_Item("sub", "MOB3")],
    })
    tipos = R.tipos_por_mob(mc, "BIN.avb")
    assert tipos["MOB1"] == ["masterClips", "linkedMasterClips"]
    assert tipos["MOB2"] == ["masterClips"]
    assert tipos["MOB3"] == ["subclips"]


def test_uma_flag_que_o_MC_recusa_nao_derruba_as_outras():
    """⚠️ Uma versão do Media Composer sem alguma flag responde `UNIMPLEMENTED`. Perder
    a lista inteira por causa de `stereoscopicClips` seria trocar tudo por nada."""
    from avid.mcapi import McApiNaoImplementado

    class _McCapenga(_McFalso):
        def itens_da_bin(self, rel, flags=("masterClips",), apenas_selecionados=False):
            if flags[0] == "groups":
                raise McApiNaoImplementado("groups não existe nesta versão")
            return super().itens_da_bin(rel, flags, apenas_selecionados)

    mc = _McCapenga(por_tipo={"masterClips": [_Item("a", "MOB1")]})
    assert R.tipos_por_mob(mc, "BIN.avb")["MOB1"] == ["masterClips"]


# ── o levantamento que o painel recebe ───────────────────────────────────────

def test_levantar_devolve_item_ficha_e_catalogo():
    mc = _McFalso(
        por_tipo={"masterClips": [_Item("24-1T01.WAV", "MOB1")]},
        colunas={"MOB1": {"Name": "24-1T01.WAV", "Scene": "24-1", "Take": "01"}},
    )
    r = R.levantar(mc, ["MOB1"])
    item = r["itens"][0]
    assert item["nome"] == "24-1T01.WAV"
    assert item["mob_id"] == "MOB1"
    assert item["tipos"] == ["masterClips"]
    assert item["campos"]["scene"] == "24-1"
    assert {c["nome"] for c in r["catalogo"]} >= {"name", "scene", "take"}


def test_levantar_pede_so_as_colunas_VISIVEIS_por_padrao():
    """⚠️⚠️ Medido no spike: `only_visible_columns=False` devolve 191 colunas. Cento e
    noventa e um campos num autocomplete é inutilizável, e o padrão tem de ser as ~31
    que o editor de fato vê na bin."""
    mc = _McFalso(por_tipo={"masterClips": [_Item("a", "MOB1")]},
                  colunas={"MOB1": {"Name": "a"}})
    R.levantar(mc, ["MOB1"])
    assert mc.pedidos == [("MOB1", False)], "pediu as 191 colunas sem precisar"
    R.levantar(mc, ["MOB1"], todas_as_colunas=True)
    assert mc.pedidos[-1] == ("MOB1", True)


def test_TODOS_os_itens_recebem_as_mesmas_chaves():
    """⚠️⚠️ O contrato de `nomes.campos.completar`, aqui no ponto em que ele importa:
    sem isto o mesmo padrão bloqueia num clipe do arrasto e passa no outro."""
    mc = _McFalso(
        por_tipo={"masterClips": [_Item("a", "MOB1"), _Item("b", "MOB2")]},
        colunas={"MOB1": {"Name": "a", "Production": "MDO"},
                 "MOB2": {"Name": "b", "Soundroll": "SD01"}},
    )
    r = R.levantar(mc, ["MOB1", "MOB2"])
    a, b = (i["campos"] for i in r["itens"])
    assert set(a) == set(b)
    assert b["production"] == "" and a["production"] == "MDO"


def test_o_item_sem_colunas_nao_derruba_o_arrasto():
    """Um efeito ou uma sequência podem não responder coluna nenhuma. Ele entra na
    lista mesmo assim — o autor pediu a aba SEM FILTRO."""
    mc = _McFalso(por_tipo={"effects": [_Item("Resize", "MOB9")]}, colunas={})
    r = R.levantar(mc, ["MOB9"])
    assert r["itens"][0]["tipos"] == ["effects"]
    assert r["itens"][0]["nome"] == "Resize"


def test_o_nome_vem_do_MC_e_nao_do_arrasto():
    """⚠️ O payload do arrasto traz MobID; o nome que o editor vê é o da bin, e pode
    ter mudado desde que ele arrastou."""
    mc = _McFalso(por_tipo={"masterClips": [_Item("NOME NOVO", "MOB1")]},
                  colunas={"MOB1": {"Name": "NOME NOVO"}})
    assert R.levantar(mc, ["MOB1"])["itens"][0]["nome"] == "NOME NOVO"


def test_mob_que_nao_esta_na_bin_e_ignorado_com_aviso():
    """Arrastar de duas bins diferentes: só a bin do primeiro é varrida."""
    mc = _McFalso(por_tipo={"masterClips": [_Item("a", "MOB1")]},
                  colunas={"MOB1": {"Name": "a"}})
    r = R.levantar(mc, ["MOB1", "MOB_DE_OUTRA_BIN"])
    assert [i["mob_id"] for i in r["itens"]] == ["MOB1"]
    assert r["ignorados"] == ["MOB_DE_OUTRA_BIN"]


def test_levantar_sem_mob_nenhum_nao_estoura():
    assert R.levantar(_McFalso(), [])["itens"] == []


# ⚠️ Os testes do PREVIEW não moram aqui: eles medem o núcleo e foram para
# `test_nomes_preview.py`. `R.prever` continua sendo o reexport que a rota chama.
