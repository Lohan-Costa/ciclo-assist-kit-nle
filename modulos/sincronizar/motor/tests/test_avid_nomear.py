"""O padrão de nome dos SUBCLIPES — a aba Subclipes ganhando o motor da Renomear.

⭐ A costura aqui é outra: na aba Renomear os campos vêm das colunas ao vivo do Media
Composer; aqui vêm do `Tomada` que o leitor já produziu e das colunas dos masters da
própria `.avb`. O motor de nome é o mesmo, e é isso que este arquivo mede.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from dataclasses import replace

from avid import nomear as N
from avid.takes import Tomada, Trecho


def _take(nome="C04_P01_T002", cena="C04", plano="P01", take="T002",
          nome_do_som="PROJETO A - 05-04 C4 P1-T002", **kw):
    base = dict(nome=nome, cena=cena, plano=plano, take=take, edit_rate=23.976,
                duracao=1200, trechos=(), origem="sequencia",
                nome_do_som=nome_do_som, convencao="rotulada", duracao_bruta=1300)
    base.update(kw)
    return Tomada(**base)


# ── a ficha de um take ───────────────────────────────────────────────────────

def test_a_ficha_traz_o_que_o_take_ja_sabe():
    f = N.ficha(_take(), {})
    assert f["cena"] == "04" and f["plano"] == "01" and f["take"] == "002"
    assert f["nomedoaudio"] == "PROJETO A - 05-04 C4 P1-T002"
    assert f["origem"] == "sequencia"


def test_a_cena_vai_SEM_o_prefixo():
    """⭐ Mesma regra da aba Renomear: `%cena` vale `04`, não `C04`. Quem põe o `C` é o
    padrão que o editor escreve, e devolver `C04` faria `C%cena` render `CC04`."""
    f = N.ficha(_take(cena="C04", plano="P01", take="T002"), {})
    assert (f["cena"], f["plano"], f["take"]) == ("04", "01", "002")


def test_take2_preenche_e_nunca_trunca():
    assert N.ficha(_take(take="T7"), {})["take2"] == "07"
    assert N.ficha(_take(take="T007"), {})["take2"] == "007"
    assert N.ficha(_take(take="T100"), {})["take2"] == "100"


def test_o_take_FRACIONARIO_do_orfao_sobrevive():
    r"""⚠️⚠️ `T002.1` é o take de um ÓRFÃO batizado pela posição (`_batizar_orfaos`), e
    o ponto é o que o distingue do take 002 real.

    Achado rodando sobre a `_D02_SYNC.avb`: `re.sub(r"\D", "", "002.1")` dava `"0021"`,
    então `%take2` transformava o órfão do take 2 num take 21 — que pode existir, e aí
    dois subclipes diferentes disputam o mesmo nome. Arrancar o ponto é perder
    justamente a marca de que aquilo precisa de revisão humana.
    """
    assert N.ficha(_take(take="T002.1"), {})["take"] == "002.1"
    assert N.ficha(_take(take="T002.1"), {})["take2"] == "002.1"
    assert N.ficha(_take(take="T7.1"), {})["take2"] == "07.1"


def test_o_take_sem_claquete_tem_os_campos_VAZIOS_e_nao_ausentes():
    """⚠️⚠️ Chave ausente é erro do padrão; chave presente e vazia é fato do material.
    Um take sem claquete (o `AMB` da D04, todo o Projeto C) tem de trazer `%cena` vazio, não
    faltando — senão o mesmo padrão bloquearia num take e passaria no vizinho, dentro
    da MESMA bin."""
    f = N.ficha(_take(nome="AMB-T001", cena=None, plano=None, take=None,
                      convencao=None), {})
    assert f["cena"] == "" and f["plano"] == "" and f["take"] == ""
    assert f["nome"] == "AMB-T001"


def test_o_nome_do_take_e_o_campo_NOME():
    """⭐⭐ `%nome` é o nome que o app daria sozinho — a claquete quando ela resolveu,
    o nome do master quando não. É ele que faz o padrão padrão (`%nome`) reproduzir o
    comportamento de hoje EXATAMENTE, inclusive o fallback do §11."""
    assert N.ficha(_take(), {})["nome"] == "C04_P01_T002"
    assert N.ficha(_take(nome="a005_C003", cena=None), {})["nome"] == "a005_C003"


def test_a_ficha_traz_as_COLUNAS_do_master_de_som():
    """⭐ É o que faz Projeto B funcionar na aba Subclipes: lá a claquete não resolve
    (`24-1` não tem rótulo), mas `Scene` e `Tomada` estão na bin, separados."""
    colunas = {"24-1T01.WAV": {"Scene": "24-1", "Take": "01",
                               "Production": "MAE_DO_OURO"}}
    f = N.ficha(_take(nome="24-1T01.WAV", cena=None, plano=None, take=None,
                      nome_do_som="24-1T01.WAV"), colunas)
    assert f["scene"] == "24-1"
    assert f["production"] == "MAE_DO_OURO"


def test_a_coluna_MEDIDA_ganha_do_campo_do_take():
    """⚠️ Precedência declarada: uma coluna do Avid vale mais que o que derivamos. Se a
    bin tem `Scene`, `%scene` é ela — não uma reconstrução nossa."""
    colunas = {"som.wav": {"Scene": "DA COLUNA"}}
    f = N.ficha(_take(nome_do_som="som.wav"), colunas)
    assert f["scene"] == "DA COLUNA"


def test_o_nome_do_video_sai_dos_trechos_de_imagem():
    """⚠️ O subclipe tem DUAS origens, e foi o autor quem apontou a ambiguidade:
    `%nomedoaudio` e `%nomedovideo` existem para que `%nome` nunca precise adivinhar
    de qual delas se está falando."""
    t = _take(trechos=(
        Trecho(mob_id="MOBV", track_id=1, media_kind="picture", start=0, length=10,
               trilha_de_origem=1),
        Trecho(mob_id="MOBA", track_id=1, media_kind="sound", start=0, length=10,
               trilha_de_origem=1)))
    f = N.ficha(t, {}, nomes_por_mob={"MOBV": "a005_C003", "MOBA": "som.wav"})
    assert f["nomedevideo"] == "a005_C003"


def test_take_orfao_de_video_tem_o_campo_vazio():
    f = N.ficha(_take(orfao=True), {}, nomes_por_mob={})
    assert f["nomedevideo"] == ""


# ── todos os takes com as mesmas chaves ──────────────────────────────────────

def test_TODAS_as_fichas_da_bin_tem_as_mesmas_chaves():
    """⚠️⚠️ O contrato de sempre, aqui no ponto em que ele decide: sem isto o mesmo
    padrão bloquearia num take e passaria no outro, na MESMA bin."""
    colunas = {"a.wav": {"Production": "X"}, "b.wav": {"Soundroll": "SD01"}}
    fs = N.fichas([_take(nome_do_som="a.wav"), _take(nome_do_som="b.wav")], colunas)
    assert set(fs[0]) == set(fs[1])
    assert fs[0]["production"] == "X" and fs[1]["production"] == ""


def test_fichas_de_lista_vazia_nao_estoura():
    assert N.fichas([], {}) == []


# ── aplicar o padrão ─────────────────────────────────────────────────────────

def test_o_padrao_PADRAO_reproduz_o_comportamento_de_hoje():
    """⭐⭐ O contrato que torna esta mudança segura: quem não mexer em nada continua
    tendo exatamente os nomes que tinha antes de o padrão existir — inclusive o
    fallback do §11 para o take sem claquete."""
    takes = [_take(), _take(nome="a005_C003", cena=None, plano=None, take=None)]
    fora = N.aplicar(takes, N.PADRAO, {})
    assert [t.nome for t in fora] == ["C04_P01_T002", "a005_C003"]


def test_um_padrao_proprio_renomeia_os_takes():
    fora = N.aplicar([_take()], "CENA%cena-TOM%plano-T%take2", {})
    assert fora[0].nome == "CENA04-TOM01-T002"


def test_aplicar_NAO_toca_no_resto_do_take():
    """⚠️ Só o nome muda. Cena, trechos e a marca de órfão decidem a BIN em que o take
    cai e o que o subclipe aponta — trocá-los aqui seria renomear mudando o material."""
    antes = _take(orfao=True)
    depois = N.aplicar([antes], "%nome_X", {})[0]
    assert depois.cena == antes.cena
    assert depois.trechos == antes.trechos
    assert depois.orfao is True
    assert depois.nome == "C04_P01_T002_X"


def test_padrao_vazio_ou_None_cai_no_PADRAO():
    """O painel pode mandar vazio — e vazio quer dizer 'do jeito de sempre', nunca
    'clipe sem nome'."""
    for p in ("", "   ", None):
        assert N.aplicar([_take()], p, {})[0].nome == "C04_P01_T002"


def test_padrao_com_campo_inexistente_LEVANTA():
    """⚠️⚠️ Recusa, e não nome truncado. A rota valida antes; esta guarda existe para
    o caso de alguém chamar direto — e para que um `%xyz` nunca vire uma bin inteira
    de subclipes com o nome pela metade."""
    from nomes.template import PadraoInvalido

    with pytest.raises(PadraoInvalido):
        N.aplicar([_take()], "C%xyz", {})


def test_padrao_que_nao_casa_CAI_NO_NOME_DE_ORIGEM(caplog):
    """⭐⭐ Decisão do autor, 2026-09-05 — e ela INVERTE o que valia antes.

    > *"Caso um dos padrões escolhidos gere um clipe que não tem match, eles
    > seguem com o nome original do vídeo e áudio. Eles não devem vir com o nome
    > vazio."*

    ⚠️ Diverge da aba Renomear de propósito: lá, vazio bloqueia o lote inteiro,
    porque o editor escreve por cima de nomes que já existem e meia aplicação
    deixa a bin em dois estados. Aqui os subclipes estão sendo CRIADOS, e recusar
    tudo por causa de um take sem claquete impediria os cinquenta que têm.
    """
    import logging

    com_video = _take(cena=None, plano=None, take=None, nome="antigo")
    com_video = replace(com_video, nome_do_video="A_0001C002_260629")
    with caplog.at_level(logging.INFO):
        fora = N.aplicar([com_video], "%cena", {})

    assert fora[0].nome == "A_0001C002_260629", "o nome do VÍDEO é o de origem"
    # ⚠️ E não em silêncio: quem gerou 50 subclipes precisa saber que 3 não
    # casaram o padrão que ele escreveu.
    assert any("não casaram o padrão" in r.getMessage() for r in caplog.records)


def test_sem_video_o_nome_de_origem_e_o_do_SOM():
    """A exceção que a regra prevê, literal: *"salvo exceções de ser um subclipe
    formado apenas pelo áudio"*."""
    so_audio = _take(cena=None, plano=None, take=None, nome="antigo",
                     nome_do_som="25-1T01.WAV")
    fora = N.aplicar([so_audio], "%cena", {})
    assert fora[0].nome == "25-1T01.WAV"


# ── as duas lacunas que a mutação cobrou ─────────────────────────────────────

def test_a_coluna_MEDIDA_ganha_do_campo_do_take_NO_CAMPO_QUE_COLIDE():
    """⚠️⚠️ A precedência só se mede numa chave que EXISTA nos dois lados.

    O primeiro teste desta regra usava `Scene`, que o `Tomada` não tem — então não havia
    colisão nenhuma e ele sobrevivia ao mutante que inverte a ordem. Era decoração.
    `take` é a chave que colide de verdade: o `_USER` do master traz a coluna `Take`, e a `Tomada`
    do nosso dataclass traz o que a claquete leu.

    ⭐ E a coluna ganha de propósito: é o que o técnico de som escreveu no gravador,
    contra o que nós reconstruímos lendo um nome.
    """
    colunas = {"som.wav": {"Take": "99"}}
    f = N.ficha(_take(take="T002", nome_do_som="som.wav"), colunas)
    assert f["take"] == "99", "o campo do take passou por cima da coluna medida"


def test_a_CENA_e_a_excecao_e_ganha_da_coluna_homonima():
    """⭐⭐ A exceção declarada, e a razão dela.

    `cena` é o único campo que o editor CORRIGE na tela. Se uma coluna chamada `Cena`
    ganhasse dele, a tela mostraria a correção e a bin receberia a coluna crua — calado.

    Regra do autor, 2026-09-06: *"`%cena` = valor indicado no painel refletindo possível
    alteração manual e o presumido. `%scene` = valor da coluna Scene como ele é"*.
    """
    colunas = {"som.wav": {"Cena": "77", "Scene": "25-1"}}
    f = N.ficha(_take(cena="25", nome_do_som="som.wav"), colunas)
    assert f["cena"] == "25", "a coluna passou por cima da cena posta à mão"
    # ⚠️ E a coluna NÃO se perde — ela continua acessível pelo nome dela.
    assert f["scene"] == "25-1"


# ── prever, que é a MESMA resposta que aplicar escreve ───────────────────────

def test_prever_e_aplicar_dao_O_MESMO_NOME():
    """⭐⭐ A razão de `prever` existir.

    O preview do Subclipar vinha de `nomes/preview.py` e a escrita de `aplicar` — duas
    implementações da mesma pergunta, e a que divergia era a do PREVIEW contra a do
    APLICAR. Este teste tranca a fonte única: se um dia alguém reintroduzir a regra do
    fallback só num dos lados, ele reprova.
    """
    takes = [_take(nome="a", cena="25"), _take(nome="b", cena=None, plano=None,
                                               take=None, nome_do_som="b.wav")]
    padrao = "C%{cena}"
    previsto = N.prever(takes, padrao, {})
    aplicados = N.aplicar(takes, padrao, {})
    assert [l["nome"] for l in previsto["linhas"]] == [t.nome for t in aplicados]


def test_prever_NAO_bloqueia_por_nome_vazio():
    """⛔⛔ O defeito que escondia a lista inteira, achado pelo autor em 2026-09-06:

    > *"a tag `%nome_do_audio` sozinho não mostra como seria o nome do subclipe, mas
    > adicionando um simples 'a' ele funciona."*

    Um take sem áudio renderiza vazio com `%nomedoaudio`. No motor genérico isso
    **bloqueia** — e a tela, que só desenha as linhas quando não está bloqueada, sumia
    com a prévia toda. Aqui vazio não impede nada: cai no nome de origem.
    """
    takes = [_take(nome="tem", nome_do_som="som.wav"),
             _take(nome="nao_tem", nome_do_som=None)]
    previsto = N.prever(takes, "%nomedoaudio", {})
    assert previsto["bloqueado"] is False
    assert len(previsto["linhas"]) == 2, "a prévia não pode sumir por causa de um item"
    assert previsto["linhas"][0]["nome"] == "som.wav"
    assert previsto["linhas"][1]["de_origem"] is True
    assert previsto["linhas"][1]["nome"], "e quem caiu no fallback tem nome"


def test_prever_DECLARA_quem_caiu_no_nome_de_origem():
    """⚠️ Sem `de_origem`, esse take aparece com um nome de outra forma no meio da lista
    e o editor não tem como saber que ali o padrão não pegou."""
    takes = [_take(nome="com", cena="25"), _take(nome="sem", cena=None)]
    linhas = N.prever(takes, "%{cena}", {})["linhas"]
    assert linhas[0]["de_origem"] is False
    assert linhas[1]["de_origem"] is True


def test_prever_BLOQUEIA_no_campo_desconhecido():
    """⛔ Esse sim: `render` recusa de qualquer jeito, então deixar o botão vivo seria
    prometer uma escrita que vai falhar."""
    previsto = N.prever([_take()], "%naoexiste", {})
    assert previsto["bloqueado"] is True
    assert previsto["invalidos"] and previsto["linhas"] == []


def test_prever_reflete_a_cena_POSTA_A_MAO():
    """⛔⛔ O defeito de 2026-09-06, na sua origem.

    > *"o preview no painel mostra que os subclipes serão feitos com o plano mantido.
    > 25-1 25-2 e etc... mas quando chega na bin, ele gera só com o nome informado na
    > cena, 25 (puro)."*

    A tela desenhava com fichas velhas. Aqui as fichas são recalculadas do take, então
    a correção aparece na mesma resposta que a escrita vai usar.
    """
    take = _take(nome="x", cena="25-1", nome_do_som="som.wav")
    colunas = {"som.wav": {"Scene": "25-1"}}
    assert N.prever([take], "C%{cena}", colunas)["linhas"][0]["nome"] == "C25-1"
    corrigido = replace(take, cena="25", convencao="manual")
    assert N.prever([corrigido], "C%{cena}", colunas)["linhas"][0]["nome"] == "C25"


def test_contexto_da_bin_LE_as_colunas_do_arquivo(tmp_path):
    """⚠️ A leitura do `_USER` não tinha teste nenhum — só se passavam dicionários
    prontos. O mutante que devolvia `{}` para toda coluna sobrevivia inteiro, e o
    sintoma seria `%scene` vazio em toda bin, calado.
    """
    import random

    import avb

    from conftest import _attrs, _master

    caminho = tmp_path / "com_colunas.avb"
    with avb.open() as f:
        m = _master(f, "24-1T01.WAV", [(1, "sound", 100)])
        # ⚠️ O `_USER` é um Attributes DENTRO do Attributes do mob — é assim que o Avid
        # guarda as colunas de bin, e foi assim que o spike as encontrou.
        m.attributes = _attrs(
            f, _USER=_attrs(f, Scene="24-1", Tomada="01", Production="MAE_DO_OURO"))
        f.content.uid = random.getrandbits(63)
        f.write(str(caminho))

    colunas, mobs = N.contexto_da_bin(str(caminho))
    assert colunas["24-1T01.WAV"]["Scene"] == "24-1"
    assert colunas["24-1T01.WAV"]["Production"] == "MAE_DO_OURO"
    assert list(mobs.values()) == ["24-1T01.WAV"], "o mapa mob→nome ficou vazio"


def test_contexto_de_um_arquivo_que_nao_existe_nao_estoura():
    """⚠️ Sem as colunas o padrão ainda funciona com o que o `Tomada` sabe — perder o
    trabalho inteiro por causa de um enriquecimento seria trocar tudo por nada."""
    assert N.contexto_da_bin("nao_existe.avb") == ({}, {})


def test_padrao_com_LETRAS_FIXAS_e_todos_os_campos_vazios_cai_no_nome_de_origem():
    """⛔⛔ Ciclo Assist, 2026-11-01: `C%{cena}_P%{plano}_T%{take2}` num material sem
    cena/plano/take rendia `C_P_T` — não vazio, então passava, e os quatro subclipes
    saíram com o MESMO nome."""
    t = replace(_take(cena=None, plano=None, take=None, nome="antigo"),
                nome_do_video="M06_CAM1_T01_MOV-PRORES")
    fora = N.aplicar([t], "C%{cena}_P%{plano}_T%{take2}", {})
    assert fora[0].nome == "M06_CAM1_T01_MOV-PRORES"


def test_vazio_PARCIAL_continua_rendendo_o_padrao():
    """⚠️ Cena sem plano (`C10_P_T001`) é decisão pendente do autor — não muda aqui."""
    t = _take(cena="C10", plano=None, take="T001")
    fora = N.aplicar([t], "C%{cena}_P%{plano}_T%{take2}", {})
    assert fora[0].nome.startswith("C10_P_T")
