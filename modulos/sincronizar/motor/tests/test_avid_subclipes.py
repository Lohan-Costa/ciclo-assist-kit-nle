"""A autoria do subclipe, conferida por LEITURA DE VOLTA.

⚠️⚠️ Escrever a bin e afirmar "não estourou" é o teste vazio que mordeu este projeto
seis vezes (§12 do spec). Todo teste aqui reabre o arquivo com o mesmo leitor que o
relink usa em produção (`avb_export.reader.topen`) e afirma sobre a ESTRUTURA.

⭐ E a leitura de volta usa `avb_bin.percurso` — o percurso que já existe, com as três
armadilhas medidas dentro dele. Um teste que escrevesse o próprio percurso poderia
concordar com um autor errado pelo mesmo motivo que o autor errou.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from avid.percurso import (e_master, e_subclipe, por_mob_id, source_clips,
                              track_de)
from avid.leitura import abrir

from avid import subclipes
from avid.takes import Tomada, Trecho
from conftest import NOME_DE_CAMERA


def test_escreve_um_subclipe_por_take(tmp_path, takes_de_exemplo):
    saida = tmp_path / "SUBCLIPES.avb"
    r = subclipes.autorar(takes_de_exemplo, str(saida))

    assert r["subclipes"] == 3
    assert saida.exists()

    with abrir(str(saida)) as f:
        achados = [m for m in f.content.mobs if e_subclipe(m)]
    assert len(achados) == 3, "a bin relida não tem um subclipe por take"


def test_o_subclipe_fica_visivel_na_bin(tmp_path, takes_de_exemplo):
    """🟠 `user_placed=False` (revisão de mutação, rodada 1, 2026-08-25) passava sem
    erro nos 49 testes anteriores — e é exatamente a falha que este arquivo existe
    para pegar: o subclipe escreve, a estrutura interna sai certa, e ele nasce
    INVISÍVEL na bin do editor porque ninguém "colocou" o item na lista de exibição.

    `user_placed` mora no `BinItem` que `f.content.add_mob(...)` devolve — não no
    mob — por isso a conferência é em `f.content.items`, não em `f.content.mobs`."""
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo, str(saida))

    with abrir(str(saida)) as f:
        vistos = 0
        for item in f.content.items:
            if not e_subclipe(item.mob):
                continue
            assert item.user_placed is True, (
                f"{item.mob.name} nasceu invisível na bin (user_placed=False)")
            vistos += 1
    assert vistos == 3, "guarda de vacuidade: os 3 subclipes deviam estar em items"


def test_o_subclipe_tem_usage_de_subclipe(tmp_path, takes_de_exemplo):
    """⭐ `usage_code = 2` é o que faz o Avid — e o nosso próprio `denest.py` — chamar
    isto de subclipe. Sem ele o mob é uma composição comum e o achatamento do relink
    passaria por ela sem a reconhecer."""
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo, str(saida))

    with abrir(str(saida)) as f:
        for m in f.content.mobs:
            if not e_subclipe(m):
                continue
            assert m.usage_code == 2
            assert str(m.usage) == "subclip"


def test_o_nome_sobrevive_a_gravacao(tmp_path, takes_de_exemplo):
    """⚠️⚠️ `f.create.Composition("nome", ...)` IGNORA o argumento: o `__init__` do
    pyavb faz `self.name = mob_type`, e o mob nasce chamado "CompositionMob". Sem a
    atribuição explícita no autor, a bin sairia com três clipes homônimos e nenhum
    erro. Medido em 2026-08-25."""
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo, str(saida))

    with abrir(str(saida)) as f:
        nomes = sorted(m.name for m in f.content.mobs if e_subclipe(m))
    assert nomes == ["C04_P01_T001", "C04_P01_T002", "C07_P03_T001"]
    assert "CompositionMob" not in nomes


def test_o_edit_rate_e_o_do_take_e_nao_o_padrao_do_pyavb(tmp_path, takes_de_exemplo):
    """⚠️ `TrackGroup.__init__` usa `edit_rate=25`. Num projeto a 23,976 isso sai
    errado e calado — a duração declarada deixa de bater com a mídia."""
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo, str(saida))

    with abrir(str(saida)) as f:
        for m in f.content.mobs:
            if e_subclipe(m):
                assert round(float(m.edit_rate), 3) == 23.976
                for t in m.tracks:
                    assert round(float(t.component.edit_rate), 3) == 23.976


def test_cada_track_aponta_para_o_master_certo(tmp_path, takes_de_exemplo,
                                              bin_de_masters):
    """A cadeia inteira, relida: subclipe → track → SourceClip → MasterMob — e o
    MASTER CERTO, não qualquer master.

    ⚠️ DESVIO do brief (2026-08-25): a versão original não passava `base`. Sem ele a
    saída é só o subclipe — o próprio `autorar` documenta isso ("sai só o subclipe e
    o MC resolve o master pelo banco de mídia") — e então `por_mob_id(f)` no arquivo
    de SAÍDA nunca acha o master, porque ele de fato não está lá. Medido: a bin escrita
    sem `base` contém só as 3 `CompositionMob`, nenhum master. Este teste só pode
    conferir a cadeia inteira DENTRO do arquivo relido usando `base=bin_de_masters`,
    como o teste irmão `test_a_bin_carrega_os_masters_quando_ha_bin_base` já faz.

    🔴 Reforço (revisão de mutação, rodada 1, 2026-08-25): a versão anterior conferia
    só QUE o destino era ALGUM master, nunca QUAL. Uma mutação que repontava todo
    `SourceClip` de som para o master de CÂMERA — inclusive `track_id` 3/4/5, que esse
    master nem tem — passava sem erro. Agora confere o `.name` do master resolvido
    contra o que o `Trecho` deveria produzir: câmera para `picture`, o som do próprio
    take para `sound`.
    """
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo, str(saida), base=str(bin_de_masters))

    por_nome_take = {t.nome: t for t in takes_de_exemplo}

    with abrir(str(saida)) as f:
        por_id = por_mob_id(f)
        vistos = 0
        for m in f.content.mobs:
            if not e_subclipe(m):
                continue
            take = por_nome_take[m.name]
            for t in m.tracks:
                kind = str(t.component.media_kind)
                esperado_nome = NOME_DE_CAMERA if kind == "picture" else take.nome_do_som
                for sc in source_clips(t.component):
                    destino = por_id.get(str(sc.mob_id))
                    assert destino is not None, "SourceClip aponta para mob ausente"
                    assert e_master(destino), "SourceClip do subclipe não vai a master"
                    assert destino.name == esperado_nome, (
                        f"{m.name}/{kind}: apontou para {destino.name!r}, "
                        f"esperado {esperado_nome!r}")
                    vistos += 1
    assert vistos >= 18, ("guarda de vacuidade: 3 takes x 6 trilhas = 18 SourceClips "
                          f"esperados, e o percurso achou {vistos}")


def test_som_nao_cai_na_trilha_de_imagem(tmp_path, takes_de_exemplo):
    """⚠️⚠️⚠️ A armadilha central do AVB, e a razão de `track_de` existir: um master
    de câmera tem `picture index=1` **E** `sound index=1` (medido em `D02_CAM A.avb`).
    Casar só pelo índice põe um SourceClip de som na trilha de imagem — e isso não
    levanta erro nenhum: vira mídia errada, ou offline, calado.

    A fixture reproduz essa mob de propósito. Este teste confere que, no subclipe
    escrito, o `media_kind` da track e o do componente dela concordam sempre."""
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo, str(saida))

    with abrir(str(saida)) as f:
        conferidas = 0
        for m in f.content.mobs:
            if not e_subclipe(m):
                continue
            # A track de imagem existe e é achável por índice E tipo.
            assert track_de(m, 1, "picture") is not None
            for t in m.tracks:
                kind = str(t.component.media_kind)
                for sc in source_clips(t.component):
                    assert str(sc.media_kind) == kind, (
                        f"track {t.index} é {kind} e carrega um SourceClip "
                        f"{sc.media_kind}")
                    conferidas += 1
    assert conferidas >= 18, "guarda de vacuidade: nenhuma trilha foi conferida"


def test_o_indice_da_track_e_SEQUENCIAL_e_nao_o_track_id_do_master(tmp_path,
                                                                    takes_de_exemplo):
    """⚠️⚠️ Duas numerações que é fácil confundir, e a fixture existe para separá-las:
    os canais do master são `[1, 2, 3, 5, 4]` — **fora de ordem de propósito** — e as
    trilhas do subclipe têm de sair `1, 2, 3, 4, 5`, contíguas, na ordem em que os
    trechos entraram.

    ⭐ Este teste fecha a Finding 5 da revisão da Task 3, que ficou parqueada em
    2026-08-25: o mutante `track.index = <track_id do master>` sobrevivia à suíte
    inteira, porque nenhum teste lia `Track.index` além da primeira trilha de cada
    mídia. Com canais contíguos as duas regras dão o mesmo resultado — é por isso que
    a fixture desordena.
    """
    from conftest import CANAIS_DE_SOM

    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo[:1], str(saida))

    with abrir(str(saida)) as f:
        m = [x for x in f.content.mobs if e_subclipe(x)][0]
        som = [t for t in m.tracks if str(t.component.media_kind) == "sound"]

        indices = [t.index for t in som]
        assert indices == [1, 2, 3, 4, 5], \
            f"as trilhas do subclipe saíram {indices} — o índice virou o track_id"

        # ⭐ E a trilha N carrega o canal N-ésimo NA ORDEM DOS TRECHOS, que é a ordem
        # em que o take os declarou. Afirmar por conteúdo, não só por contagem.
        canais = [next(iter(source_clips(t.component))).track_id for t in som]
        assert canais == CANAIS_DE_SOM, \
            f"a trilha certa está carregando o canal errado: {canais}"


def test_o_recorte_e_o_do_take(tmp_path, takes_de_exemplo):
    """`start_time` e `length` de cada SourceClip têm de ser os do `Trecho`. É o que
    faz o subclipe recortar o pedaço certo do master, e é a metade inversa do que o
    `denest.achatar` soma quando desfaz.

    🟠 Reforço (revisão de mutação, rodada 1, 2026-08-25): também confere o `length`
    do MOB do subclipe (não só das tracks). `mob.length = 0` passava sem erro nos 49
    testes anteriores — nenhum deles olhava para essa propriedade."""
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo, str(saida))

    esperado = {}
    for take in takes_de_exemplo:
        for tr in take.trechos:
            esperado[(take.nome, tr.media_kind, tr.track_id)] = (tr.start, tr.length)
    duracao_esperada = {take.nome: take.duracao for take in takes_de_exemplo}

    with abrir(str(saida)) as f:
        visto = {}
        duracao_vista = {}
        for m in f.content.mobs:
            if not e_subclipe(m):
                continue
            duracao_vista[m.name] = m.length
            for t in m.tracks:
                for sc in source_clips(t.component):
                    chave = (m.name, str(t.component.media_kind), sc.track_id)
                    visto[chave] = (sc.start_time, sc.length)

    assert visto == esperado
    assert duracao_vista == duracao_esperada, "o length do MOB não é o do take"


def test_camera_que_entra_tarde_ganha_filler_e_nao_desloca_o_som(tmp_path,
                                                                takes_de_exemplo):
    """⚠️ A câmera nem sempre cobre o take inteiro. A resposta é filler na cabeça da
    track de imagem — e NUNCA empurrar o SourceClip, que dessincronizaria o take.

    A forma simples (SourceClip nu) continua sendo a preferida: só quem tem
    `deslocamento > 0` vira `Sequence`. O relatório conta quantos precisaram."""
    take = takes_de_exemplo[0]
    tarde = Tomada(
        nome="C04_P01_T009",
        cena=take.cena, plano=take.plano, take="T009", convencao=take.convencao,
        edit_rate=take.edit_rate, duracao=take.duracao, origem="sequencia",
        descartado=False,
        trechos=tuple(
            Trecho(
                mob_id=tr.mob_id, track_id=tr.track_id, media_kind=tr.media_kind,
                start=tr.start,
                # só a IMAGEM entra tarde; o som cobre o take inteiro
                length=tr.length - 40 if tr.media_kind == "picture" else tr.length,
                deslocamento=40 if tr.media_kind == "picture" else 0,
            )
            for tr in take.trechos
        ),
    )

    saida = tmp_path / "TARDE.avb"
    r = subclipes.autorar([tarde], str(saida))
    assert r["com_filler"] == 1

    with abrir(str(saida)) as f:
        m = [x for x in f.content.mobs if e_subclipe(x)][0]
        picture = track_de(m, 1, "picture")
        assert type(picture.component).__name__ == "Sequence", \
            "a track que precisa de filler tem de virar Sequence"
        cabeca = list(picture.component.components)[0]
        assert type(cabeca).__name__ == "Filler"
        assert cabeca.length == 40

        som = track_de(m, 1, "sound")
        assert type(som.component).__name__ == "SourceClip", \
            "a track que NÃO precisa de filler tem de ficar na forma simples"


def _take_com_imagem(base, pedacos, duracao):
    """`base` com a imagem trocada por `pedacos` = [(deslocamento, length, trilha)]."""
    som = [t for t in base.trechos if t.media_kind == "sound"]
    imagem = [t for t in base.trechos if t.media_kind == "picture"][0]
    novos = tuple(
        Trecho(mob_id=imagem.mob_id, track_id=1, media_kind="picture",
               start=0, length=comprimento, deslocamento=desl,
               trilha_de_origem=trilha)
        for desl, comprimento, trilha in pedacos
    )
    return Tomada(
        nome="C04_P01_T009", cena=base.cena, plano=base.plano, take="T009",
        convencao=base.convencao, edit_rate=base.edit_rate, duracao=duracao,
        origem="sequencia", descartado=False, trechos=novos + tuple(som))


def _tracks_de(mob, kind):
    return [t for t in mob.tracks if str(t.component.media_kind) == kind]


def test_dois_pedacos_da_MESMA_trilha_viram_UMA_track(tmp_path, takes_de_exemplo):
    """⭐⭐ O conserto do `C07_P02_T002`, pedido pelo autor em 2026-08-26.

    Uma câmera que PAROU E VOLTOU dentro da janela do take produz dois pedaços na
    mesma trilha da sequência. Uma track por trecho os apresentaria como **V1 e V2** —
    e o editor leria "duas câmeras" sobre uma câmera só. No material real isso é um
    fragmento de 8 frames (partida em falso) seguido do clipe de verdade.

    A trilha de origem é quem decide: dois pedaços da mesma trilha voltam à MESMA
    trilha do subclipe, e o vão entre eles vira filler.
    """
    take = _take_com_imagem(takes_de_exemplo[0],
                            [(0, 50, 1), (100, 750, 1)], duracao=850)
    saida = tmp_path / "PARTIDA.avb"
    subclipes.autorar([take], str(saida))

    with abrir(str(saida)) as f:
        m = [x for x in f.content.mobs if e_subclipe(x)][0]
        imagem = _tracks_de(m, "picture")
        assert len(imagem) == 1, \
            f"a mesma câmera saiu em {len(imagem)} trilhas — o editor leria multicâmera"
        partes = [(type(c).__name__, c.length)
                  for c in list(imagem[0].component.components)]
        assert partes == [("Filler", 0), ("SourceClip", 50),
                          ("Filler", 50), ("SourceClip", 750)]
        # ⚠️ E o som não foi arrastado junto: continua uma trilha por canal.
        assert len(_tracks_de(m, "sound")) == 5


def test_os_pedacos_saem_em_ordem_ainda_que_cheguem_fora(tmp_path, takes_de_exemplo):
    """⚠️ A ordem da `Sequence` é a ordem do TEMPO, não a ordem em que os trechos
    chegaram. Hoje o leitor os entrega em ordem de timeline, mas nada no tipo `Tomada`
    obriga isso — e uma `Sequence` fora de ordem produziria filler de comprimento
    NEGATIVO, ou material trocado de lugar, sem estourar aqui.
    """
    take = _take_com_imagem(takes_de_exemplo[0],
                            [(100, 750, 1), (0, 50, 1)], duracao=850)
    saida = tmp_path / "FORA DE ORDEM.avb"
    subclipes.autorar([take], str(saida))

    with abrir(str(saida)) as f:
        m = [x for x in f.content.mobs if e_subclipe(x)][0]
        imagem = _tracks_de(m, "picture")[0]
        partes = [(type(c).__name__, c.length)
                  for c in list(imagem.component.components)]
        assert partes == [("Filler", 0), ("SourceClip", 50),
                          ("Filler", 50), ("SourceClip", 750)]


def test_pedacos_de_trilhas_DIFERENTES_continuam_em_tracks_diferentes(
        tmp_path, takes_de_exemplo):
    """⚠️ A outra metade, e é o que impede o conserto de virar fusão cega: duas
    CÂMERAS de verdade — trilhas de origem diferentes — continuam em trilhas
    diferentes do subclipe, mesmo tendo o mesmo `mob_id` e o mesmo `track_id`."""
    take = _take_com_imagem(takes_de_exemplo[0],
                            [(0, 50, 1), (100, 750, 2)], duracao=850)
    saida = tmp_path / "DUAS TRILHAS.avb"
    subclipes.autorar([take], str(saida))

    with abrir(str(saida)) as f:
        m = [x for x in f.content.mobs if e_subclipe(x)][0]
        assert len(_tracks_de(m, "picture")) == 2


def test_trilha_de_origem_nao_informada_mantem_uma_track_por_trecho(
        tmp_path, takes_de_exemplo):
    """⚠️⚠️ `trilha_de_origem = 0` significa **não informada**, e o contrato anterior
    a 2026-08-26 vale inteiro: cada trecho ganha trilha própria.

    Isto não é zelo: os cinco canais de som de `takes_de_exemplo` são montados à mão
    sem o campo. Se zero agrupasse, eles virariam UMA trilha de som — cinco canais
    empilhados num só, sem erro nenhum."""
    saida = tmp_path / "SEM CAMPO.avb"
    subclipes.autorar(takes_de_exemplo, str(saida))

    with abrir(str(saida)) as f:
        m = [x for x in f.content.mobs if e_subclipe(x)][0]
        assert len(_tracks_de(m, "sound")) == 5
        assert len(_tracks_de(m, "picture")) == 1


def test_take_sem_trecho_nenhum_e_recusado(tmp_path, takes_de_exemplo):
    """Um subclipe sem tracks é um item morto na bin do editor. Melhor recusar e
    contar do que entregar."""
    vazio = Tomada(nome="C04_P01_T099", cena="C04", plano="P01", take="T099",
                 edit_rate=23.976, duracao=0, trechos=(), origem="sequencia")
    with pytest.raises(ValueError):
        subclipes.autorar([vazio], str(tmp_path / "VAZIO.avb"))


def test_gravar_sobre_a_PROPRIA_base_e_recusado(tmp_path, bin_de_masters,
                                                takes_de_exemplo):
    """⚠️⚠️⚠️ Gravar sobre a base DESTRÓI a bin, e o `autorar` recusa antes de abrir
    qualquer coisa.

    O `topen` do pyavb é preguiçoso: mantém o handle e resolve objeto por offset, sob
    demanda. Gravar no mesmo caminho faz o writer ler offsets de um arquivo que ele
    acabou de truncar. **Medido em 2026-08-26: a bin foi de 3 922 bytes para 119 e
    deixou de abrir**, com `unpack requires a buffer of 8 bytes` — a mesma assinatura
    que o banco de NLEs registra para esta armadilha.

    ⚠️ Nenhum chamador de hoje faz isso. Mas a saída conhecida para o **D9** é
    justamente *"passe `base` = a bin que contém os masters"*, e o campo que o painel
    ganharia para isso deixa o editor a um erro de digitação de perder os masters.
    """
    tamanho_antes = bin_de_masters.stat().st_size

    with pytest.raises(ValueError) as e:
        subclipes.autorar(takes_de_exemplo, str(bin_de_masters),
                          base=str(bin_de_masters))

    assert "mesmo arquivo" in str(e.value)
    assert bin_de_masters.stat().st_size == tamanho_antes, \
        "a bin foi tocada apesar da recusa"


def test_o_guard_da_base_nao_se_engana_com_a_GRAFIA_do_caminho(tmp_path,
                                                               bin_de_masters,
                                                               takes_de_exemplo):
    """⚠️ O mesmo arquivo tem muitas grafias — relativa, absoluta, com `..` no meio,
    e no Windows também maiúsculas e barras trocadas. Comparar as strings cruas
    deixaria o guard passar exatamente onde ele mais precisa segurar."""
    torto = str(bin_de_masters.parent / "." / ".." / bin_de_masters.parent.name
                / bin_de_masters.name)

    with pytest.raises(ValueError):
        subclipes.autorar(takes_de_exemplo, torto, base=str(bin_de_masters))


def test_base_diferente_da_saida_continua_funcionando(tmp_path, bin_de_masters,
                                                      takes_de_exemplo):
    """Guarda de não-afrouxamento: o modo `base=` é o que torna a bin autossuficiente,
    e o guard não pode tê-lo quebrado."""
    saida = tmp_path / "COM MASTERS.avb"
    r = subclipes.autorar(takes_de_exemplo, str(saida), base=str(bin_de_masters))
    assert r["subclipes"] == len(takes_de_exemplo)
    assert saida.exists()


def test_lista_vazia_nao_escreve_arquivo(tmp_path):
    """⚠️ Guarda de vacuidade do lado do produtor: zero takes tem de ser um resultado
    explícito, não uma bin vazia que o editor abre e não entende."""
    saida = tmp_path / "NADA.avb"
    r = subclipes.autorar([], str(saida))
    assert r["subclipes"] == 0
    assert not saida.exists()


def test_a_bin_carrega_os_masters_quando_ha_bin_base(tmp_path, takes_de_exemplo,
                                                     bin_de_masters):
    """Com `base`, o subclipe é escrito DENTRO da bin que já contém os masters — e o
    resultado é autossuficiente. Sem `base`, sai só o subclipe e o MC resolve o
    master por MobID no banco de mídia (a mesma escolha que o Órbita faz)."""
    saida = tmp_path / "COM BASE.avb"
    subclipes.autorar(takes_de_exemplo, str(saida), base=str(bin_de_masters))

    with abrir(str(saida)) as f:
        assert sum(1 for m in f.content.mobs if e_master(m)) == 4
        assert sum(1 for m in f.content.mobs if e_subclipe(m)) == 3


def test_cada_gravacao_tem_uid_novo(tmp_path, takes_de_exemplo):
    """⚠️ Regra 1 de `avb_bin/__init__.py`, medida: sem `uid` novo o MC recusa a bin
    com `FILE_OPEN_FAILURE` enquanto houver uma de mesmo uid aberta."""
    a = tmp_path / "A.avb"
    b = tmp_path / "B.avb"
    subclipes.autorar(takes_de_exemplo, str(a))
    subclipes.autorar(takes_de_exemplo, str(b))

    with abrir(str(a)) as fa, abrir(str(b)) as fb:
        assert fa.content.uid != fb.content.uid


def test_mobs_id_novos_a_cada_autoria(tmp_path, takes_de_exemplo):
    """⭐ Cada autoria gera MobIDs novos, e isso não é detalhe: o Media Composer serve
    mob por MobID a partir da SESSÃO, não do arquivo — duas bins com o mesmo MobID no
    mesmo boot e a primeira carregada ganha (medido no `avb_bin/audio.py`)."""
    a = subclipes.autorar(takes_de_exemplo, str(tmp_path / "A.avb"))
    b = subclipes.autorar(takes_de_exemplo, str(tmp_path / "B.avb"))
    assert set(a["mapa"]) == set(b["mapa"])
    assert not (set(a["mapa"].values()) & set(b["mapa"].values()))


def test_a_coluna_Take_guarda_o_ponto_do_orfao_batizado(tmp_path, takes_de_exemplo):
    """⛔ `T001.1` (órfão batizado pela posição) virava `0011` na coluna — um take 11 que não existe.
    Pilotado no MC 24.6 em 2026-10-21: o Renomear com `T%take2` deu `C07_P02_T0011`."""
    from dataclasses import replace
    takes = [replace(takes_de_exemplo[0], take="T001.1"), *takes_de_exemplo[1:]]
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes, str(saida))

    with abrir(str(saida)) as f:
        colunas = {m.name: m.attributes["_USER"]["Take"]
                   for m in f.content.mobs if e_subclipe(m)}
    assert sorted(colunas.values()) == ["001", "001.1", "002"]
