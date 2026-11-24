"""Um subclipe é UMA linha, com o timecode da fala e a timeline onde é usado.

⛔⛔ **MEDIDO em 2026-09-21, no projeto do editor: 140 dos 150 recortes têm DOIS masters**
— imagem e som. A busca emitia um achado por *(master, recorte)*, e o mesmo `C04_P06-T002`
saía duas vezes na tela: uma com as falas (do master de som, **sem miniatura**) e outra com
o quadro e a decupagem. Ele viu e descreveu exatamente assim: *"a lista retornou o mesmo
subclipe separando como se fosse só o áudio primeiro, e depois o mesmo subclipe com o
vídeo"*.

⇒ A regra *"uma linha é um MASTER"* vale na aba **Vetores**, onde a pergunta é "o que falta
processar" e o master é a unidade de processamento. Aqui a unidade é o que o editor arrasta.
"""

from __future__ import annotations

import json
from fractions import Fraction

import pytest

from cicloassist.avid import subclipes as S
from cicloassist.midia import busca as B
from cicloassist.midia import cache as C
from cicloassist.midia import timecode as T

from .test_inventario import IMAGEM, SOM, midia_de_imagem


def recorte(nome, janelas, bin="CENAS/C07.avb", mob="urn:x", timelines=()):
    r = S.Recorte(nome=nome, bin=bin, especie="subclipe", duracao_s=600.0,
                  fps_aprox=23.976, mob_id=mob, timelines=list(timelines))
    for chave, (ini, fim) in janelas.items():
        r.janelas[chave] = S.Janela(ini, fim)
    return r


@pytest.fixture
def take_sincronizado(tmp_path, monkeypatch):
    """O caso real: um subclipe sobre DOIS masters — imagem da câmera, som do gravador."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    T.esquecer()
    imagem = midia_de_imagem(tmp_path, nome="a001_C003")
    imagem.anotar({"trecho": "a001_C003", "escopo": "midia",
                   "descricao": "close de Personagem F no consultório",
                   "confianca": "inferido", "fonte": "visual"})
    som = C.Midia(SOM, raiz_do_cache=tmp_path)
    som.anotar_fonte({"master_de_som": "C7 P1-T002"})
    som.guardar_transcricao([
        {"inicio": 12.4, "fim": 14.0, "texto": "Boa tarde, Personagem F.", "certeza": 0.9},
        {"inicio": 74.9, "fim": 76.0, "texto": "A Personagem F chegou?", "certeza": 0.9},
    ])
    return tmp_path


def test_o_subclipe_de_dois_masters_e_UMA_linha(take_sincronizado):
    """⭐⭐ O defeito que o editor viu: a mesma linha duas vezes, uma só com som."""
    janelas = {C.de_umid(IMAGEM): (0.0, 600.0), C.de_umid(SOM): (0.0, 600.0)}
    um = recorte("C07_P01-T002", janelas)

    achados = B.procurar(["personagem f"], raiz=take_sincronizado,
                         recortes={k: [um] for k in janelas})
    do_recorte = [a for a in achados if a.item]

    assert len(do_recorte) == 1, "o mesmo subclipe saiu mais de uma vez"
    (linha,) = do_recorte
    # ⭐ A imagem manda no que se OLHA, o som traz o que se OUVE.
    assert linha.nota is not None, "perdeu a decupagem, que vem do master de imagem"
    assert linha.chave == C.de_umid(IMAGEM), "a miniatura tem de vir do master de imagem"
    assert linha.quantas_falas == 2, "perdeu as falas, que vêm do master de som"
    assert linha.como_dicionario()["achado_por"] == ["imagem", "fala"]


def test_os_dois_masters_continuam_na_lista(take_sincronizado):
    """⛔ Preferência não é exclusão: cada master segue tendo a linha dele, atrás."""
    janelas = {C.de_umid(IMAGEM): (0.0, 600.0), C.de_umid(SOM): (0.0, 600.0)}
    achados = B.procurar(["personagem f"], raiz=take_sincronizado,
                         recortes={k: [recorte("C07_P01-T002", janelas)] for k in janelas})
    masters = {a.chave for a in achados if not a.item}
    assert masters == set(janelas), "um master sumiu da lista"


def test_a_juncao_nao_mente_sobre_ter_herdado(take_sincronizado):
    """⚠️ `herdado` quer dizer "não pude conferir o tempo". Se o som confirmou a fala DENTRO
    da janela, o recorte não herdou nada — e a tela não pode dizer que herdou."""
    janelas = {C.de_umid(IMAGEM): (0.0, 600.0), C.de_umid(SOM): (0.0, 600.0)}
    (linha,) = [a for a in B.procurar(["personagem f"], raiz=take_sincronizado,
                                      recortes={k: [recorte("X", janelas)] for k in janelas})
                if a.item]
    assert linha.herdado is False


def test_o_recorte_leva_o_proprio_mob_e_as_timelines(take_sincronizado):
    """⭐ O mob é o que faz o Source carregar o SUBCLIPE, e não o master dele."""
    janelas = {C.de_umid(IMAGEM): (0.0, 600.0)}
    um = recorte("C07_P01-T002", janelas, mob="urn:smpte:umid:abc",
                 timelines=["CENA 7 MONTADA"])
    (linha,) = [a for a in B.procurar(["personagem f"], raiz=take_sincronizado,
                                      recortes={C.de_umid(IMAGEM): [um]}) if a.item]
    d = linha.como_dicionario()
    assert d["mob_do_item"] == "urn:smpte:umid:abc"
    assert d["timelines"] == ["CENA 7 MONTADA"]


# ── o timecode completo da fala ──────────────────────────────────────────────

def test_a_conta_do_timecode():
    """⭐ Conferido contra a mídia real em 2026-09-21: `15:02:29:00` + 4,82 s a 23,976
    dá `15:02:33:20`."""
    fps = Fraction(24000, 1001)
    assert T.somar_segundos("15:02:29:00", 4.82, fps) == "15:02:33:20"
    assert T.somar_segundos("00:00:00:00", 0, fps) == "00:00:00:00"
    assert T.para_quadros("01:00:00:12", fps) == 24 * 3600 + 12
    assert T.de_quadros(24 * 3600 + 12, fps) == "01:00:00:12"
    # ⚠️ Dá a volta em 24 h, como o Avid dá.
    assert T.de_quadros(24 * 3600 * 24, fps) == "00:00:00:00"


def test_sem_timecode_ou_sem_taxa_nao_se_inventa_nada():
    """⛔ O arquivo de som não declara taxa (medido: `time_base = 1/48000`), e chutar 25
    fps erraria todo material 23,976 — que é este acervo inteiro."""
    fps = Fraction(24000, 1001)
    assert T.somar_segundos("", 10, fps) == ""
    assert T.somar_segundos("não é tc", 10, fps) == ""
    assert T.para_quadros("1:2:3", fps) is None
    assert T.taxa_do_projeto(None) is None
    assert T.taxa_do_projeto({"fps": {"num": 0, "den": 1}}) is None
    assert T.taxa_do_projeto({"fps": {"num": 24000, "den": 1001}}) == fps


def test_o_timecode_entra_DEPOIS_do_corte(take_sincronizado, monkeypatch):
    """⛔⛔ MEDIDO: dentro da busca isto custava **17,4 s** — um `ffprobe` por master (172 ms
    frio) para as 86 mídias que "personagem f" casa, a fim de mostrar 40. Depois do corte: 3,4 s."""
    lidos = []

    def _espiao(midia):
        lidos.append(midia.chave)
        return "10:00:00:00"

    monkeypatch.setattr(B._timecode, "do_master", _espiao)

    achados = B.procurar(["personagem f"], raiz=take_sincronizado)
    assert not lidos, "a busca leu timecode de quem nem vai aparecer"
    assert all(f.get("tc", "") == "" for a in achados for f in a.falas)

    # ⚠️ Só quem TEM fala paga o ffprobe: uma linha achada pela imagem não tem TC a somar.
    com_fala = [a for a in achados if a.falas]
    B.carimbar_o_timecode(com_fala[:1], Fraction(24000, 1001))
    assert len(lidos) == 1
    assert com_fala[0].falas[0]["tc"] == "10:00:12:09"  # 12,4 s x 23,976 = 297 quadros


def test_o_tc_da_fala_sai_do_master_do_SOM_na_linha_fundida(take_sincronizado, monkeypatch):
    """⛔⛔ Numa linha fundida a chave do achado é a da IMAGEM — é ela que endereça a
    miniatura —, e a fala veio do SOM.

    MEDIDO no projeto do editor em 2026-09-22: **59 de 59** pares imagem+som têm TC de
    fonte DIFERENTE, e a diferença é de HORAS (a câmera em `03:14:14:17`, o gravador em
    `11:42:00:00` — TC de rolo contra hora do dia). Carimbando pelo master do achado, o TC
    da fala saía 8 h e meia fora — e é um número para o editor DIGITAR no Avid.
    """
    monkeypatch.setattr(B._timecode, "do_master", lambda m: (
        "03:14:14:17" if m.chave == C.de_umid(IMAGEM) else "11:42:00:00"))
    janelas = {C.de_umid(IMAGEM): (0.0, 600.0), C.de_umid(SOM): (0.0, 600.0)}
    achados = B.procurar(["personagem f"], raiz=take_sincronizado,
                         recortes={k: [recorte("C07_P01-T002", janelas)] for k in janelas})
    (linha,) = [a for a in achados if a.item]
    assert linha.chave == C.de_umid(IMAGEM), "a miniatura continua vindo da imagem"

    B.carimbar_o_timecode([linha], Fraction(24000, 1001))

    # 11:42:00:00 + 12,4 s a 23,976 = 297 quadros = 12:09
    assert linha.falas[0]["tc"] == "11:42:12:09"
    assert not linha.falas[0]["tc"].startswith("03:"), "carimbou com o TC da imagem"


def test_sem_taxa_a_fala_fica_com_o_relogio(take_sincronizado):
    achados = B.procurar(["personagem f"], raiz=take_sincronizado)
    B.carimbar_o_timecode(achados, None)
    (com_fala,) = [a for a in achados if a.falas]
    assert com_fala.falas[0]["quando"] == "00:12"
    assert com_fala.falas[0].get("tc", "") == ""


# ── o que a tela promete ─────────────────────────────────────────────────────

def test_a_linha_da_fala_e_clicavel_e_manda_o_mob_do_recorte():
    """⛔⛔ `SetPosition` NÃO existe nesta build (medido: `McApiNaoImplementado`), então o
    clique carrega o ITEM que contém a fala e o timecode vai escrito ao lado. E manda o mob
    do RECORTE: carregar o master de um resultado que é subclipe põe no Source a diária
    inteira no lugar do trecho que o editor clicou."""
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "cicloassist" / "painel"
          / "painel.js").read_text(encoding="utf-8")
    falas = js[js.index("function blocoDeFalas"):js.index("function carregarNoSource")]

    assert 'linha = document.createElement("button")' in falas, "a fala deixou de ser clicável"
    assert "carregarNoSource(a, cartao" in falas
    # ⭐ No Premiere a linha manda os segundos da fala (lá dá para posicionar: 2026-09-22);
    #   no Avid, `undefined` — nada muda para o Media Composer.
    # ⭐ `NO_PREMIERE`, não `CEP`: na janela do app não há `__adobe_cep__` e a agulha ainda vai à fala.
    assert "NO_PREMIERE ? f.inicio : undefined" in falas
    assert "f.tc || f.quando" in falas, "a linha precisa cair no relógio quando não há TC"
    assert 'mob: a.mob_do_item || ""' in js, "o clique voltou a carregar o master"
