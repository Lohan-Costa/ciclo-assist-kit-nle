"""Os leitores de take: da bin sincronizada para `Tomada`.

⭐ O que estes testes provam é a ARITMÉTICA do recorte, e ela é a metade inversa do
que `avb_bin/denest.py` soma quando desfaz um subclipe. Errar aqui não estoura — dá um
subclipe que aponta para o pedaço errado do master, e o editor descobre no olho.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from avid.leitura import abrir

from avid import takes as T

from conftest import JANELAS, NOME_DE_CAMERA, NOMES_DE_SOM, TOTAL


def test_le_um_take_por_segmento_de_som(bin_sincronizada):
    lidos, forma = T.ler(str(bin_sincronizada))
    assert forma == "sequencia"
    assert len(lidos) == len(JANELAS) == 3, \
        "a fixture tem 3 janelas de som; um take por janela"


def test_os_takes_saem_em_ordem_de_timeline(bin_sincronizada):
    """⚠️ A ordem se afere pelo SOM, não pelo nome do take.

    Desde 2026-09-05 o nome padrão é o do master de VÍDEO (decisão do autor), e
    nesta fixture uma câmera só cobre as três janelas — os três saem com o mesmo
    nome. No material real isso não acontece (medido na diária do autor: 52 de 52
    nomes distintos, porque a câmera corta entre tomadas), mas a fixture continua
    representando um caso legítimo: a câmera que roda contínuo.
    """
    lidos, _ = T.ler(str(bin_sincronizada))
    assert [t.nome_do_som for t in lidos] == NOMES_DE_SOM
    # ⭐ E o nome de saída é o do vídeo, que é o que muda aqui.
    assert all(t.nome == NOME_DE_CAMERA for t in lidos)


def test_a_claquete_vem_do_SOM_e_nao_da_camera(bin_sincronizada):
    """⚠️⚠️ O achado 1 do spec, virado teste: a câmera (`a004_03170908_C001`) não tem
    claquete nenhuma, e um leitor que tirasse cena do nome dela produziria a cena
    "C01" a partir do número de clipe da Blackmagic."""
    lidos, _ = T.ler(str(bin_sincronizada))
    assert {t.cena for t in lidos} == {"C04", "C07"}
    # ⭐ `rotulada` é a gramática única desde 2026-08-28 — antes eram duas convenções
    # por forma de nome (`projeto_a`, `projeto_a-ixml`). Nomear a procedência aqui é
    # de propósito: o teste prova de QUAL leitor a cena veio, não só que ela existe.
    assert all(t.convencao == "rotulada" for t in lidos)


def test_cada_take_tem_as_cinco_trilhas_de_som_e_a_de_imagem(bin_sincronizada):
    lidos, _ = T.ler(str(bin_sincronizada))
    for t in lidos:
        sons = [x for x in t.trechos if x.media_kind == "sound"]
        imagens = [x for x in t.trechos if x.media_kind == "picture"]
        assert len(sons) == 5, f"{t.nome}: esperava 5 canais de som, achei {len(sons)}"
        assert len(imagens) == 1, f"{t.nome}: esperava 1 câmera, achei {len(imagens)}"
        assert sorted(x.track_id for x in sons) == [1, 2, 3, 4, 5]


def test_o_recorte_do_som_e_o_do_segmento(bin_sincronizada):
    """`start` do trecho = `start_time` do SourceClip na timeline. Sem soma nenhuma:
    o segmento da timeline já aponta direto para o master (a sequência do Órbita não
    tem subclipe no meio)."""
    lidos, _ = T.ler(str(bin_sincronizada))
    for n, take in enumerate(lidos):
        _inicio, dur = JANELAS[n]
        assert take.duracao == dur
        for trecho in take.trechos:
            if trecho.media_kind == "sound":
                assert trecho.start == 20 * n
                assert trecho.length == dur
                assert trecho.deslocamento == 0


def test_o_recorte_da_camera_e_a_INTERSECAO_com_a_janela(bin_sincronizada):
    """⭐ A conta que importa. A câmera roda de 0 a TOTAL; o take de som ocupa
    [inicio, inicio+dur). O trecho de imagem tem de começar no frame da câmera que
    corresponde ao início do som — `sc.start_time + (janela_inicio - seg_inicio)` — e
    durar o que a interseção durar.

    A fixture põe a câmera começando em 0 na timeline com `start_time = 0`, então o
    frame esperado é o próprio início da janela."""
    lidos, _ = T.ler(str(bin_sincronizada))
    for n, take in enumerate(lidos):
        inicio, dur = JANELAS[n]
        imagem = [x for x in take.trechos if x.media_kind == "picture"][0]
        assert imagem.start == inicio
        assert imagem.length == dur
        assert imagem.deslocamento == 0


def test_a_camera_atrasada_APARA_a_cabeca_do_take(tmp_path):
    """⭐⭐ A regra pedida pelo autor em 2026-08-26: **o subclipe existe só onde imagem
    e som se sobrepõem**. A câmera que entrou 40 frames tarde não ganha mais filler na
    cabeça — os 40 frames de som sozinho são APARADOS.

    ⚠️ Aparar é recuar o `start` do som DENTRO do master, nunca empurrar a imagem: o
    take continua sincronizado porque as duas mídias andaram o mesmo tanto. Um leitor
    que só encurtasse `length` sem somar ao `start` daria um take em sincronia falsa —
    e o sintoma (lábio fora do som) só aparece no olho do editor.
    """
    from conftest import escrever_com_camera_atrasada

    caminho = escrever_com_camera_atrasada(tmp_path / "ATRASADA.avb", atraso=40)
    lidos, _ = T.ler(str(caminho))
    take = lidos[0]
    _inicio, dur = JANELAS[0]

    assert take.duracao == dur - 40, "a cabeça de som sozinho não foi aparada"
    imagem = [x for x in take.trechos if x.media_kind == "picture"][0]
    assert imagem.deslocamento == 0, "não há mais buraco a tapar — logo, filler nenhum"
    assert imagem.length == dur - 40
    for som in [x for x in take.trechos if x.media_kind == "sound"]:
        assert som.start == 40, "o som tem de entrar 40 frames adiante DENTRO do master"
        assert som.length == dur - 40


def test_a_camera_que_acaba_cedo_APARA_a_cauda_do_take(tmp_path):
    """A outra ponta da mesma regra: a câmera que parou antes do fim do som."""
    from conftest import escrever_com_camera_que_acaba_cedo

    caminho = escrever_com_camera_que_acaba_cedo(tmp_path / "CEDO.avb", corte=30)
    lidos, _ = T.ler(str(caminho))
    take = lidos[0]
    _inicio, dur = JANELAS[0]

    assert take.duracao == dur - 30
    for som in [x for x in take.trechos if x.media_kind == "sound"]:
        assert som.start == 0, "a CABEÇA não foi tocada — só a cauda sobrava"
        assert som.length == dur - 30


def test_o_VAO_no_meio_fica_de_FORA_do_take(tmp_path):
    """⭐⭐ A regra do autor vale nas TRÊS posições — cabeça, cauda **e meio**:
    *"quando qualquer um deles está ausente, aparamos e deixamos de fora"*.

    A fixture põe dois pedaços de câmera na mesma janela de som com um vão de 100
    frames entre eles — a forma do `C7 P2-T002` no material real, onde um fragmento de
    8 frames precede o clipe de verdade por 22 frames de nada.

    ⚠️ Um subclipe é uma região CONTÍNUA: não há como tirar o meio dele sem parti-lo
    em dois. Então o que se entrega é o **maior pedaço** em que as duas mídias estão
    presentes — e o fragmento antes do vão fica de fora, junto com o vão.

    ⚠️⚠️ A conta anterior era a UNIÃO, e ela mantinha o vão dentro do take, como
    filler. Ficava um subclipe com um buraco preto no meio.

    ⭐ E o que o aparo joga fora **não desaparece**: vira um órfão do tamanho dele.
    Antes de 2026-08-26 esse pedaço sumia — não entrava em take nenhum e não era
    reconhecido como órfão, porque o critério era "cruza alguma janela de som?" em vez
    de "algum take usou?".
    """
    from conftest import NOME_DE_CAMERA, escrever_com_camera_partida

    caminho = escrever_com_camera_partida(tmp_path / "PARTIDA.avb")
    lidos, _ = T.ler(str(caminho))
    # ⚠️ Indexado pelo SOM: desde 2026-09-05 o nome de saída é o do master de
    # VÍDEO, e nesta fixture uma câmera só cobre as três janelas.
    por_nome = {t.nome_do_som: t for t in lidos}
    take = por_nome[NOMES_DE_SOM[0]]

    # ⭐ Por NOME, e não por índice: desde o conserto do órfão-que-some (2026-08-26) o
    # fragmento descartado vira um take próprio, e ele vem ANTES na timeline.
    # ⭐ Desde o batismo por posição (2026-08-26) o órfão não se chama mais pelo nome
    # da câmera: ele herda cena e plano do take que o precede. Aqui ele vem ANTES do
    # primeiro take resolvido, então vira o "take 0".
    fragmento = next(t for t in lidos if t.convencao == "posicao")
    assert fragmento.orfao is True
    assert (fragmento.cena, fragmento.plano, fragmento.take) == ("C04", "P01", "T000")
    assert fragmento.duracao == 50, (
        "o pedaço que o aparo jogou fora tem de virar um órfão do tamanho dele — "
        "senão some da bin sem log e sem rastro")

    # A câmera cobre [inicio+50, inicio+100) e [inicio+150, inicio+900): o segundo
    # pedaço é o maior, e é o único que entra no take.
    assert take.duracao == 750
    for som in [x for x in take.trechos if x.media_kind == "sound"]:
        assert som.start == 150, "o som entra onde o trecho contínuo começa"
        assert som.length == 750

    imagem = [x for x in take.trechos if x.media_kind == "picture"]
    assert [(x.deslocamento, x.length) for x in imagem] == [(0, 750)], \
        "o fragmento de 50 frames e o vão de 100 ficaram de fora"


def test_o_leitor_declara_a_trilha_de_origem_de_cada_trecho(tmp_path):
    """⭐ O campo que o autor do subclipe usa para não apresentar uma câmera como
    duas. ⚠️ `track_id` NÃO serve para isso: os dois pedaços da câmera partida têm o
    mesmo `track_id` (1) e o mesmo `mob_id` — o que os une é a trilha da SEQUÊNCIA de
    onde vieram."""
    from conftest import escrever_com_camera_em_dois_arquivos

    caminho = escrever_com_camera_em_dois_arquivos(tmp_path / "SPANNING.avb")
    take = T.ler(str(caminho))[0][0]

    imagem = [x for x in take.trechos if x.media_kind == "picture"]
    assert len(imagem) == 2, "os dois arquivos encostados ficam os dois no take"
    assert {x.trilha_de_origem for x in imagem} == {1}, \
        "os dois pedaços vieram da mesma trilha de imagem da sequência"

    som = [x for x in take.trechos if x.media_kind == "sound"]
    assert sorted(x.trilha_de_origem for x in som) == [1, 2, 3, 4, 5], \
        "cada canal do som direto vem de uma trilha própria — e tem de continuar assim"


def test_os_dois_arquivos_encostados_NAO_viram_orfao(tmp_path):
    """⚠️⚠️ O critério de órfão é "algum take usou?", e ele tem de enxergar o take
    inteiro — inclusive o segundo pedaço, que entra com `deslocamento > 0`.

    Uma marcação que ignorasse o deslocamento cobriria só o começo do take: o segundo
    arquivo da câmera pareceria não usado e viraria um órfão ESPÚRIO, duplicando na
    bin `ORFAOS` material que já está dentro do take. Mutação (2026-08-26): trocar
    `inicio + t.deslocamento` por `inicio` sobrevivia à suíte inteira sem isto.
    """
    from conftest import NOME_DE_CAMERA, escrever_com_camera_em_dois_arquivos

    caminho = escrever_com_camera_em_dois_arquivos(tmp_path / "SPANNING.avb")
    lidos, _ = T.ler(str(caminho))

    # ⚠️ Pelo CAMPO `orfao`, não pelo nome. Desde 2026-09-05 o nome padrão do take
    # é o do master de VÍDEO — então um take legítimo daquela câmera e um órfão
    # espúrio dela passam a ter o MESMO nome, e distinguir por ele é confundir o
    # que este teste existe para separar.
    orfaos_de_camera = [t for t in lidos if t.orfao and t.nome_do_video == NOME_DE_CAMERA]
    assert not orfaos_de_camera, (
        "a câmera virou órfã apesar de os dois pedaços dela estarem no take: "
        + repr([(t.nome, t.duracao) for t in orfaos_de_camera]))


def test_a_camera_em_dois_arquivos_vira_UMA_trilha_no_subclipe_escrito(tmp_path):
    """A ida e volta completa: ler a sequência, autorar, reabrir a bin e contar as
    trilhas de imagem. Dois arquivos encostados da mesma câmera são UMA câmera, e
    apresentá-los como `V1` e `V2` diria multicâmera sobre material que não é."""
    from avid.percurso import e_subclipe

    from avid import subclipes

    from conftest import escrever_com_camera_em_dois_arquivos

    caminho = escrever_com_camera_em_dois_arquivos(tmp_path / "SPANNING.avb")
    lidos, _ = T.ler(str(caminho))
    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(lidos[:1], str(saida))

    with abrir(str(saida)) as f:
        m = [x for x in f.content.mobs if e_subclipe(x)][0]
        imagem = [t for t in m.tracks if str(t.component.media_kind) == "picture"]
        assert len(imagem) == 1, f"saiu com {len(imagem)} trilhas de imagem"
        partes = [(type(c).__name__, c.length)
                  for c in list(imagem[0].component.components)]
        assert partes == [("Filler", 0), ("SourceClip", 400), ("SourceClip", 400)], \
            "encostados: os dois na mesma trilha, colados, SEM filler entre eles"


def test_o_som_do_orfao_vem_da_PROPRIA_camera_e_nao_da_vizinha(tmp_path):
    """⚠️⚠️ Com duas câmeras rodando, o som da câmera B cobre a janela da câmera A.
    Montar o som do órfão pegando *"o som de câmera que cruza a janela"* poria os
    canais de B dentro do subclipe de A — e o editor ouviria a outra câmera, sem que
    nada estourasse.

    O casamento é por `mob_id`, e é só isso que separa as duas.
    """
    from conftest import NOME_DE_CAMERA, escrever_com_duas_cameras

    caminho = escrever_com_duas_cameras(tmp_path / "DUAS.avb")
    lidos, _ = T.ler(str(caminho))
    # ⭐ O órfão agora é batizado por posição — procurá-lo pelo nome da câmera deixou
    # de valer. O que o identifica é a `convencao`.
    orfao = next(t for t in lidos if t.convencao == "posicao")

    imagem = [x for x in orfao.trechos if x.media_kind == "picture"]
    som = [x for x in orfao.trechos if x.media_kind == "sound"]
    assert len(som) == 2, f"o órfão saiu com {len(som)} trilhas de som, não 2"
    assert {x.mob_id for x in som} == {imagem[0].mob_id}, \
        "entrou som de outra câmera no subclipe do órfão"


def test_o_take_declara_QUANTO_de_som_ficou_de_fora(tmp_path):
    """⭐ O aparo é a regra do autor, mas o que ele apara varia muito — na diária 2
    medimos de 98 a 299 frames de cabeça, e um take em que a câmera parou cedo perdeu
    2 106 frames (88 s) de cauda.

    ⚠️ Um take que perdeu a maior parte de si continua sendo legítimo e continua **não
    sendo o que o técnico gravou**. O número tem de estar no relatório antes de o
    editor abrir a bin — senão a única forma de descobrir é ouvindo o subclipe e
    sentindo falta.
    """
    from conftest import escrever_com_camera_atrasada

    caminho = escrever_com_camera_atrasada(tmp_path / "ATRASADA.avb", atraso=40)
    take = T.ler(str(caminho))[0][0]
    _inicio, dur = JANELAS[0]

    assert take.duracao_bruta == dur, "a bruta é a janela de som, antes do aparo"
    assert take.duracao == dur - 40
    assert take.aparado == 40


def test_take_sem_nada_a_aparar_declara_zero(bin_sincronizada):
    """⚠️ Zero de propósito, não zero por omissão: a fixture põe a câmera cobrindo a
    timeline inteira, então não há o que aparar em take nenhum."""
    lidos, _ = T.ler(str(bin_sincronizada))
    assert [t.aparado for t in lidos] == [0, 0, 0]
    assert [t.duracao_bruta for t in lidos] == [t.duracao for t in lidos]


def test_o_orfao_nao_reporta_aparo(tmp_path):
    """⚠️⚠️ Um órfão não foi aparado — não havia janela de som com que comparar.
    Reportar aparo aqui seria inventar um número: o `duracao_bruta` de um órfão é o
    próprio segmento, e é a resposta honesta."""
    from conftest import escrever_com_camera_orfa

    caminho = escrever_com_camera_orfa(tmp_path / "ORFA.avb", inicio=0, duracao=90)
    orfao = T.ler(str(caminho))[0][0]
    assert orfao.orfao is True
    assert orfao.duracao_bruta == 90
    assert orfao.aparado == 0


def test_o_som_da_CAMERA_nao_abre_take(tmp_path):
    """⚠️⚠️ O defeito medido no material real em 2026-08-26. A bin sincronizada traz o
    som da câmera em trilhas de som (idx 6 e 7 na D02_SYNC), e o leitor tratava TODO
    segmento de som como janela de take — fabricando um take por clipe de câmera.
    Resultado: 26 clipes de câmera na bin `NAO RESOLVIDO`, nenhum deles um take.

    A janela de um take vem do SOM DIRETO, e o que distingue os dois é estrutural: o
    master do som direto não tem trilha de imagem; o da câmera tem.
    """
    from conftest import escrever_com_som_de_camera

    caminho = escrever_com_som_de_camera(tmp_path / "COM SOM DE CAMERA.avb")
    lidos, _ = T.ler(str(caminho))
    assert [t.take for t in lidos] == ["T001", "T002", "T001"]


def test_o_take_nao_leva_o_som_da_camera_junto(tmp_path):
    """§ do autor, 2026-08-26: *"só precisamos incluir o áudio do som direto"*. O take
    sai com as CINCO trilhas do WAV, e não com sete."""
    from conftest import NOME_DE_CAMERA, escrever_com_som_de_camera

    caminho = escrever_com_som_de_camera(tmp_path / "COM SOM DE CAMERA.avb")
    with abrir(str(caminho)) as f:
        from avid.percurso import e_master
        da_camera = {str(m.mob_id) for m in f.content.mobs
                     if e_master(m) and m.name == NOME_DE_CAMERA}

    lidos, _ = T.ler(str(caminho))
    for take in lidos:
        sons = [x for x in take.trechos if x.media_kind == "sound"]
        assert len(sons) == 5, f"{take.nome} saiu com {len(sons)} trilhas de som"
        assert not (da_camera & {x.mob_id for x in sons}),             f"{take.nome} levou som da câmera junto"


def test_camera_orfa_vira_take_para_poder_ser_renomeada(tmp_path):
    """⭐ Pedido do autor, 2026-08-26: *"clipes órfãos também são subclipados para
    poder renomear sem mudar o original"*. No material real é o
    `a001_03170214_C001`, que roda de 0 a 11620 com o som direto só começando em
    60226.

    ⚠️ E ele entra em ORDEM DE TIMELINE, antes do primeiro take de som — a bin do
    editor tem de refletir a diária, não a ordem em que o leitor achou as coisas."""
    from conftest import NOME_DE_CAMERA, escrever_com_camera_orfa

    caminho = escrever_com_camera_orfa(tmp_path / "ORFA.avb", inicio=0, duracao=90)
    lidos, _ = T.ler(str(caminho))
    # ⭐ Em ordem de timeline, e o órfão vem PRIMEIRO — com o lugar que a POSIÇÃO
    # lhe dá: ele precede o primeiro take resolvido, logo é o "take 0" do plano.
    #
    # ⚠️ Aferido pelos CAMPOS, não pelo nome: desde 2026-09-05 o batismo dá cena,
    # plano e take, e o NOME segue a regra única (o do master de vídeo). Antes o
    # órfão saía com nome de convenção enquanto os vizinhos saíam com o nome do
    # arquivo — duas regras de nome na mesma bin.
    assert [(t.cena, t.plano, t.take) for t in lidos] == [
        ("C04", "P01", "T000"), ("C04", "P01", "T001"),
        ("C04", "P01", "T002"), ("C07", "P03", "T001")]
    assert lidos[0].convencao == "posicao", "e a cena dele é PRESUMIDA"


def test_o_orfao_de_imagem_PRESERVA_o_som_da_camera(tmp_path):
    """⭐ *"se for um vídeo órfão o som de câmera deve ser preservado"* — e é a única
    escolha honesta: não há som direto ali. Descartá-lo entregaria um subclipe mudo de
    um material que tem som."""
    from conftest import escrever_com_camera_orfa

    caminho = escrever_com_camera_orfa(tmp_path / "ORFA.avb", inicio=0, duracao=90)
    orfao = T.ler(str(caminho))[0][0]

    imagem = [x for x in orfao.trechos if x.media_kind == "picture"]
    som = [x for x in orfao.trechos if x.media_kind == "sound"]
    assert len(imagem) == 1 and imagem[0].length == 90
    assert {x.track_id for x in som} == {1, 2}, "os dois canais da câmera"
    assert {x.mob_id for x in som} == {imagem[0].mob_id},         "o som do órfão tem de vir da PRÓPRIA câmera, não de outro master"
    assert all(x.length == 90 and x.deslocamento == 0 for x in som)
    orfao_marcado = orfao
    # ⚠️ E cada canal declara de QUE TRILHA da sequência veio — na fixture, as duas
    # trilhas de som da câmera são a 6 e a 7, depois das cinco do som direto. Sem
    # isso, uma câmera que parasse e voltasse teria o som repartido em duas trilhas do
    # subclipe, que é exatamente o defeito que o agrupamento por trilha conserta.
    assert sorted(x.trilha_de_origem for x in som) == [6, 7]
    assert orfao_marcado.orfao is True
    # ⚠️⚠️ A cena dele é PRESUMIDA, e o campo `convencao` é o que diz isso. O §11
    # continua valendo: nada foi inventado sobre a CLAQUETE — que não existe aqui. O
    # que se afirma é a POSIÇÃO na timeline, que é fato medido. A distinção mora no
    # campo, e é ela que o painel mostra ao editor.
    assert orfao_marcado.cena == "C04"
    assert orfao_marcado.convencao == "posicao", (
        "a cena presumida está se passando por lida de claquete")


# ── o batismo do órfão: o lugar cronológico dele ─────────────────────────────
#
# ⭐⭐ Regra do autor, 2026-08-26: *"tenho na cena 4 o take 1, take 2, arquivo órfão,
# take 3. O arquivo órfão vai ganhar o subclipe com o nome cena 4 take 2.1. Porque
# assim o clipe vai para a bin da Cena 4 e na organização ele se mantém na ordem
# cronológica, ficando a cargo do editor/assistente fazer a revisão humana."*
#
# ⚠️ É INFERÊNCIA, e ela se declara: `convencao == "posicao"`, `orfao` segue `True`, e
# o ponto decimal no nome é uma forma que nenhuma claquete produz.


def test_o_orfao_ENTRE_takes_herda_o_take_anterior(tmp_path):
    """`T001` → o órfão logo depois vira `T001.1`, e o seguinte `T001.2`."""
    from conftest import escrever_com_orfaos_entre_takes

    caminho = escrever_com_orfaos_entre_takes(tmp_path / "ENTRE.avb")
    lidos, _ = T.ler(str(caminho))
    batizados = [t for t in lidos if t.convencao == "posicao"]

    assert [t.take for t in batizados] == ["T001.1", "T001.2"]
    assert all(t.orfao is True for t in batizados)
    assert all(t.cena == "C04" and t.plano == "P01" for t in batizados)


def test_o_orfao_batizado_ORDENA_entre_os_takes_certos(tmp_path):
    """⭐ O ponto da regra inteira: o clipe cai na bin da cena **e** fica no lugar
    cronológico. A bin do Avid ordena por string, e é por isso que `T001.1` tem de
    ficar entre `T001` e `T002` — não no fim da lista."""
    from avid import cenas

    from conftest import escrever_com_orfaos_entre_takes

    caminho = escrever_com_orfaos_entre_takes(tmp_path / "ENTRE.avb")
    lidos, _ = T.ler(str(caminho))
    grupos = cenas.agrupar(lidos)

    assert "ORFAOS" not in grupos, "o órfão batizado tem de ir para a bin da CENA"
    # ⚠️ Pela TRIPLA, não pelo nome: o batismo dá cena/plano/take, e o nome de
    # saída segue a regra única (o do master de vídeo).
    assert [t.take for t in grupos["C04"]] == ["T001", "T001.1", "T001.2", "T002"]


def test_o_orfao_ANTES_de_tudo_vira_o_take_ZERO(tmp_path):
    """*"o primeiro take da diária 2 é um take ensaio. Podemos chamá-lo de take 0,
    pois cronologicamente ele deve vir antes da C4 plano 1 tomada 1."*

    ⚠️ Não havendo take algum antes dele, a âncora é o PRIMEIRO take da diária — é de
    lá que vêm a cena e o plano."""
    from conftest import escrever_com_camera_orfa

    caminho = escrever_com_camera_orfa(tmp_path / "ORFA.avb", inicio=0, duracao=90)
    lidos, _ = T.ler(str(caminho))
    ensaio = lidos[0]

    assert (ensaio.cena, ensaio.plano, ensaio.take) == ("C04", "P01", "T000")
    assert (ensaio.cena, ensaio.plano, ensaio.take) == ("C04", "P01", "T000")
    assert ensaio.convencao == "posicao"
    assert ensaio.orfao is True


def test_o_take_NAO_RESOLVIDO_nao_e_batizado(tmp_path):
    """⚠️⚠️ Só órfão é batizado. Um take de som cuja claquete não casou convenção
    nenhuma continua **sem cena** — ali existe uma claquete que alguém escreveu, e
    presumir por cima dela é exatamente o que o §11 proíbe. O órfão é outro caso: não
    há claquete nenhuma para contradizer."""
    from conftest import escrever_com_uma_claquete_ilegivel

    caminho = escrever_com_uma_claquete_ilegivel(tmp_path / "MISTA.avb")
    lidos, _ = T.ler(str(caminho))
    # ⚠️ Indexado pelo SOM: desde 2026-09-05 o nome de saída é o do master de
    # VÍDEO, e nesta fixture uma câmera só cobre as três janelas.
    por_nome = {t.nome_do_som: t for t in lidos}

    assert "GRAVACAO 002" in por_nome, "o take não resolvido sumiu do relatório"
    assert por_nome["GRAVACAO 002"].cena is None
    assert por_nome["GRAVACAO 002"].convencao is None


def test_sem_take_resolvido_nenhum_o_orfao_fica_em_ORFAOS(tmp_path, takes_de_exemplo):
    """⚠️ Não havendo com que ancorar, não se inventa âncora: o órfão fica como estava
    e vai para `ORFAOS`. É o caso de uma bin só de câmera."""
    from dataclasses import replace

    from avid import cenas
    from avid.takes import _batizar_orfaos

    orfao = replace(takes_de_exemplo[0], nome="a001_0317", cena=None, plano=None,
                    take=None, convencao=None, orfao=True)
    fora = _batizar_orfaos([(0, orfao)])

    assert [t.nome for _p, t in fora] == ["a001_0317"]
    assert set(cenas.agrupar([t for _p, t in fora])) == {cenas.BIN_ORFAOS}


def test_take_de_som_sem_camera_tambem_e_orfao(tmp_path):
    """A outra metade da mesma ideia: som que a câmera não cobriu."""
    from conftest import escrever_sem_camera

    caminho = escrever_sem_camera(tmp_path / "SO SOM.avb")
    lidos, _ = T.ler(str(caminho))
    assert all(t.orfao is True for t in lidos)
    # ⚠️ E sem imagem com que aparar, a duração é a do som inteiro.
    assert [t.duracao for t in lidos] == [dur for _i, dur in JANELAS]


def test_take_pareado_NAO_e_orfao(bin_sincronizada):
    lidos, _ = T.ler(str(bin_sincronizada))
    assert all(t.orfao is False for t in lidos)


def test_take_sem_camera_nenhuma_continua_sendo_take(tmp_path):
    """Som sem imagem é material legítimo (câmera parou antes, som seguiu). O take
    sai só com as trilhas de som — não é erro e não some do relatório."""
    from conftest import escrever_sem_camera

    caminho = escrever_sem_camera(tmp_path / "SO SOM.avb")
    lidos, _ = T.ler(str(caminho))
    assert len(lidos) == 3
    assert all(not [x for x in t.trechos if x.media_kind == "picture"] for t in lidos)


def test_nome_fora_de_convencao_vira_take_NAO_RESOLVIDO(tmp_path):
    """⚠️ §11 do spec: claquete ilegível **não** é erro. O take existe, `cena` é
    `None`, o nome é o do master, e o editor aponta à mão. **Nunca se inventa.**"""
    from conftest import escrever_com_som_sem_claquete

    caminho = escrever_com_som_sem_claquete(tmp_path / "SEM CLAQUETE.avb")
    lidos, _ = T.ler(str(caminho))
    assert lidos, "material sem claquete não pode DESAPARECER do relatório"
    assert all(t.cena is None for t in lidos)
    assert all(t.resolvido is False for t in lidos)
    assert all(t.convencao is None for t in lidos)
    # ⚠️ O nome de saída é o do VÍDEO; quem identifica a tomada é o som.
    assert lidos[0].nome_do_som == "GRAVACAO 001"


def test_bin_mista_nao_perde_o_take_nao_resolvido(tmp_path):
    """⚠️⚠️ CRÍTICO (rodada 1 de revisão, 2026-08-25): numa bin real, take resolvido e
    não resolvido convivem na MESMA sequência. `com_claquete or set(janelas)` só falha
    no all-or-nothing; o caso do meio — dois takes bons, um com claquete ilegível — é
    o realista, e é ele que apagava o take não resolvido do relatório, calado."""
    from conftest import escrever_com_uma_claquete_ilegivel

    caminho = escrever_com_uma_claquete_ilegivel(tmp_path / "MISTA.avb")
    lidos, _ = T.ler(str(caminho))
    assert len(lidos) == 3, "as três janelas têm de sair — a ilegível não pode sumir"

    # ⚠️ Indexado pelo SOM: desde 2026-09-05 o nome de saída é o do master de
    # VÍDEO, e nesta fixture uma câmera só cobre as três janelas.
    por_nome = {t.nome_do_som: t for t in lidos}
    assert set(por_nome) == {NOMES_DE_SOM[0], "GRAVACAO 002", NOMES_DE_SOM[2]}
    ilegivel = por_nome["GRAVACAO 002"]
    assert ilegivel.cena is None
    assert ilegivel.resolvido is False
    assert ilegivel.convencao is None


def test_descarte_nao_avaliado_e_None_e_nao_False(bin_sincronizada):
    """⚠️⚠️ Sem o mapa de caminhos não há como saber se o take estava em `FALSE TAKE`.
    A resposta é **não avaliado**, e ela não pode passar por "não descartado" — é o
    mesmo `medida` vazia do §7: vazio significa não medido, jamais zero."""
    lidos, _ = T.ler(str(bin_sincronizada))
    assert all(t.descartado is None for t in lidos)


def test_descarte_com_mapa_de_caminhos(bin_sincronizada, tmp_path):
    """Com o caminho em mãos, o take de `FALSE TAKE` sai marcado.

    ⭐ O mapa é chaveado pelo NOME do master de som — o único identificador que a bin
    e o disco compartilham. Chaveá-lo por MobID obrigaria a perguntar o caminho de
    cada master ao Media Composer, a ~500 ms por chamada."""
    descartado = tmp_path / "FALSE TAKE" / (NOMES_DE_SOM[1] + ".WAV")
    normal = tmp_path / "SD02" / (NOMES_DE_SOM[0] + ".WAV")
    for alvo in (descartado, normal):
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(b"")

    caminhos = {NOMES_DE_SOM[0]: str(normal), NOMES_DE_SOM[1]: str(descartado)}
    lidos, _ = T.ler(str(bin_sincronizada), caminhos=caminhos)
    # ⚠️ Indexado pelo SOM: desde 2026-09-05 o nome de saída é o do master de
    # VÍDEO, e nesta fixture uma câmera só cobre as três janelas.
    por_take = {t.nome_do_som: t for t in lidos}
    assert por_take[NOMES_DE_SOM[0]].descartado is False
    assert por_take[NOMES_DE_SOM[1]].descartado is True
    # ⚠️ O terceiro não estava no mapa: continua NÃO AVALIADO.
    assert por_take[NOMES_DE_SOM[2]].descartado is None


def test_bin_de_subclipes_e_lida_de_volta(tmp_path, takes_de_exemplo):
    """⭐ A ida e a volta fecham. Autorar 3 takes e reler a bin devolve 3 takes com o
    mesmo nome, a mesma cena e o mesmo recorte — e `forma` diz `"subclipe"`, que é
    como a Task 5 sabe que o material JÁ está preparado.

    Isto é a tradução direta de "verificar o ESTADO DO MATERIAL, nunca se o Preparar
    rodou" (§5 do spec)."""
    from avid import subclipes

    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(takes_de_exemplo, str(saida))

    relidos, forma = T.ler(str(saida))
    assert forma == "subclipe"
    assert [t.nome for t in relidos] == [t.nome for t in takes_de_exemplo]
    assert [t.cena for t in relidos] == [t.cena for t in takes_de_exemplo]
    for antes, depois in zip(takes_de_exemplo, relidos):
        assert {(x.media_kind, x.track_id, x.start, x.length) for x in depois.trechos} \
            == {(x.media_kind, x.track_id, x.start, x.length) for x in antes.trechos}


def test_o_subclipe_com_QUALIFICADOR_no_plano_sobrevive_a_ida_e_volta(tmp_path):
    """⚠️⚠️ A consequência de guardar `PICUP`/`SERIE` dentro do plano (2026-08-28).

    O nome canônico do subclipe passa a ter ESPAÇO no meio — `C11_P03 PICUP_T001` —, e
    `_NOME_CANONICO` é quem relê esse nome quando a bin de subclipes não carrega os
    masters (`autorar(..., base=None)`). Um regex de plano sem espaço faz a releitura
    devolver `cena=None` justamente nos pickups: eles cairiam em `NAO RESOLVIDO` numa
    passagem e na bin da cena na outra, com o MESMO material.

    ⭐ Não é hipótese: os nomes abaixo são os da diária 3, medidos em `D03 SOM.avb`.
    """
    from avid import nomear, subclipes

    from conftest import _escrever_variacao

    caminho = _escrever_variacao(tmp_path / "D03.avb", nomes_de_som=[
        "PROJETO A - 05-04 C11 P1/001",
        "PROJETO A - 05-04 C11 P3 PICUP/001",
        "PROJETO A - 05-04 FOLLY C9 P1 SERIE/011",
    ])
    da_sequencia, forma = T.ler(str(caminho))
    assert forma == "sequencia"
    # ⚠️ A identidade, não o nome: o nome de saída é o do master de vídeo.
    assert [(t.cena, t.plano, t.take) for t in da_sequencia] == [
        ("C11", "P01", "T001"), ("C11", "P03 PICUP", "T001"),
        ("C09", "P01 SERIE", "T011")]

    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(da_sequencia, str(saida))
    # ⚠️ Com as COLUNAS, como o comando do sidecar faz: é delas que a claquete
    # volta agora. A bin de subclipes não traz os masters de som dentro, então
    # `nome_do_som` vem vazio e o nome de saída é o do vídeo — o que atravessa
    # a ida e volta é o metadado que o subclipe passou a carregar
    # (`Scene`/`Take` no `_USER`, ver `subclipes.montar_mob`).
    colunas, _nomes = nomear.contexto_da_bin(str(saida))
    relidos, forma = T.ler(str(saida), colunas=colunas)

    assert forma == "subclipe"
    por_id = {(t.cena, t.plano, t.take) for t in relidos}
    assert ("C11", "P03 PICUP", "T001") in por_id, \
        "o pickup perdeu a identidade na releitura da bin de subclipes"
    assert ("C09", "P01 SERIE", "T011") in por_id, \
        "a série perdeu a cena na releitura da bin de subclipes"
    assert ("C11", "P01", "T001") in por_id


def test_o_orfao_sobrevive_a_ida_e_volta_pela_bin_de_subclipes(tmp_path):
    """⭐⭐ §5 do spec: *o que importa é o ESTADO DO MATERIAL, não quem o produziu*. Se
    o editor apontar `criar bins por cena` para a bin de SUBCLIPES em vez da
    sincronizada, o órfão tem de continuar órfão — senão ele cairia em `NAO RESOLVIDO`
    numa passagem e em `ORFAOS` na outra, com o mesmo material.

    ⚠️ E a marca não vem de campo guardado: vem da estrutura. Imagem e som do MESMO
    mob é câmera consigo mesma; de mobs diferentes é take pareado.
    """
    from avid import subclipes

    from conftest import NOME_DE_CAMERA, escrever_com_camera_orfa

    caminho = escrever_com_camera_orfa(tmp_path / "ORFA.avb", inicio=0, duracao=90)
    da_sequencia, _ = T.ler(str(caminho))

    saida = tmp_path / "SUBCLIPES.avb"
    subclipes.autorar(da_sequencia, str(saida))
    relidos, forma = T.ler(str(saida))

    assert forma == "subclipe"
    # ⚠️⚠️ A releitura de uma bin SÓ DE SUBCLIPES não tem os masters dentro,
    # então `nome_do_som` volta vazio e — desde que o nome padrão passou a ser
    # o do VÍDEO (2026-09-05) — todos os subclipes desta fixture se chamam
    # igual (uma câmera para as três janelas). O que este teste prova é o que
    # importa e não depende de nome: a MARCA de órfão atravessa a ida e volta.
    assert sum(1 for t in relidos if t.orfao) == 1, \
        "o órfão de câmera perdeu a marca na releitura"
    assert sum(1 for t in relidos if not t.orfao) == 3, \
        "um take pareado foi marcado órfão na releitura"


def test_multicam_com_som_de_uma_camera_NAO_e_orfao(tmp_path, takes_de_exemplo):
    """⚠️⚠️ Duas câmeras na imagem e o som vindo de uma delas — material que a
    sincronização PAREOU, e que uma regra de interseção (`imagem & som`) chamaria de
    órfão. A pergunta certa é se TODA track de imagem vem de um mob que também dá som.

    ⭐ Este teste existe porque a mutação `not (imagem - som)` → `bool(imagem & som)`
    sobreviveu à suíte inteira em 2026-08-26.
    """
    from dataclasses import replace

    from avid import subclipes
    from avid.takes import Trecho

    base = takes_de_exemplo[0]
    imagem = [x for x in base.trechos if x.media_kind == "picture"][0]
    som = [x for x in base.trechos if x.media_kind == "sound"][0]
    # A câmera B empresta o mob do SOM só para ter um mob_id diferente do da câmera A;
    # o que importa aqui é a topologia dos conjuntos, não que mídia existe.
    segunda_camera = Trecho(mob_id=som.mob_id, track_id=1, media_kind="picture",
                            start=0, length=imagem.length, deslocamento=0)
    multicam = replace(base, trechos=(imagem, segunda_camera, som))

    saida = tmp_path / "MULTICAM.avb"
    subclipes.autorar([multicam], str(saida))
    relido = T.ler(str(saida))[0][0]

    assert relido.orfao is False, \
        "a câmera A não dá som nenhum — o take está pareado, não órfão"


def test_subclipe_so_de_som_e_lido_como_orfao(tmp_path, takes_de_exemplo):
    """A outra metade: um subclipe sem track de imagem nenhuma."""
    from dataclasses import replace

    from avid import subclipes

    so_som = replace(
        takes_de_exemplo[0],
        trechos=tuple(x for x in takes_de_exemplo[0].trechos
                      if x.media_kind == "sound"))
    saida = tmp_path / "SO SOM.avb"
    subclipes.autorar([so_som], str(saida))

    relido = T.ler(str(saida))[0][0]
    assert relido.orfao is True


def test_take_sem_o_master_na_bin_ainda_assim_TEM_NOME(tmp_path):
    """⚠️⚠️ Sem o master, `_nome_do_master` devolve `""` — e o take saía com nome
    VAZIO. O preço: um mob **sem nome** na bin do editor, e o `mapa` do autorar
    colapsando numa entrada só quando faltasse mais de um master.

    Não é hipotético: o próprio leitor junta esses `mob_id` em `sem_master` e loga
    (`"%d master(s) de som ausentes desta bin"`), porque a forma "bin com só a
    timeline" existe e está registrada no banco de NLEs.

    ⭐ O caminho do órfão já tinha o fallback (`nome or str(mob_id)`); este não.
    Achado em revisão em 2026-08-26.
    """
    from conftest import escrever_sem_o_master_de_som

    caminho = escrever_sem_o_master_de_som(tmp_path / "SEM MASTER.avb")
    lidos, _ = T.ler(str(caminho))

    assert lidos, "a bin não produziu take nenhum"
    for take in lidos:
        assert take.nome.strip(), (
            "take sem nome — vira um item anônimo na bin do editor e colide no mapa")


def test_nomes_vazios_nao_colapsam_o_mapa_do_autorar(tmp_path):
    """⚠️ A consequência que o nome vazio tinha no autor: `mapa[nome]` com dois takes
    sem nome guardaria um só, e a Task 5 usa esse mapa."""
    from avid import subclipes

    from conftest import escrever_sem_o_master_de_som

    caminho = escrever_sem_o_master_de_som(tmp_path / "SEM MASTER.avb")
    lidos, _ = T.ler(str(caminho))
    r = subclipes.autorar(lidos, str(tmp_path / "SUB.avb"))
    assert len(r["mapa"]) == len(lidos)
    assert "" not in r["mapa"]


def test_bin_VAZIA_diz_o_QUE_FALTA(tmp_path):
    """⚠️ §5 do spec: não encontrando o que precisa, o módulo **diz o que falta** em
    vez de exigir que outra aba seja usada. A mensagem é parte do contrato.

    ⚠️⚠️ **A entrada deste teste mudou em 2026-08-29, e o contrato não.** Ele usava
    `bin_de_masters`, e isso codificava uma premissa que o autor cortou: que uma bin
    só de masterclipes é estado incompleto. Não é — é entrada legítima, porque as
    etapas do fluxo (sincronizar, subclipar, organizar, trabalhar a cena) **não são
    interdependentes**. O que continua sendo forma desconhecida é a bin sem clipe
    nenhum, e é ela que este teste passa a usar.
    """
    import avb

    caminho = tmp_path / "vazia.avb"
    with avb.open() as f:
        f.content.uid = 3
        f.write(str(caminho))

    with pytest.raises(T.FormaDesconhecida) as e:
        T.ler(str(caminho))

    mensagem = str(e.value).lower()
    assert "subclipe" in mensagem
    assert "masterclipe" in mensagem, "a mensagem tem de listar as TRÊS formas"


# ── a bin que o Media Composer ainda não salvou ───────────────────────────────

def test_bin_sem_masters_e_RECUSADA_em_vez_de_dar_takes_com_UMID(bin_nao_salva):
    """⛔⛔ Uma bin recém-entregue pelo Sincronizar não tem os masters: o Media
    Composer só os materializa no `.avb` ao SALVAR, e até lá ela aparece com o
    asterisco ao lado do nome.

    Sem esta recusa o leitor seguia em frente e entregava os takes com o **UMID cru no
    lugar do nome** — `urn:smpte:umid:060a2b34…` —, mais "sem cena" em todos. Nada
    estava tecnicamente errado: o leitor era honesto sobre uma bin incompleta. Mas o
    editor via 50 linhas ilegíveis e concluía que a função de subclipe tinha quebrado.

    ⭐ Medido na bin real (2026-08-27): antes de salvar, 1 mob e 0 masters; depois de
    salvar, 299 mobs e 50 masters — e a leitura passou a dar 26 takes com nome
    (`C04_P01_T000`) e cena. Os 198 `SourceClip` eram os mesmos nos dois.

    ⚠️ A mensagem tem de dizer O QUE FAZER. "Bin inválida" mandaria o editor procurar
    defeito no material.
    """
    with pytest.raises(T.BinNaoSalva) as erro:
        T.ler(str(bin_nao_salva))

    msg = str(erro.value)
    assert "salv" in msg.lower(), f"a mensagem não diz para salvar: {msg!r}"
    assert "asterisco" in msg.lower(), (
        "a mensagem não menciona o asterisco — é o sinal que o editor vê na tela, e "
        f"o que liga a mensagem ao que ele está olhando: {msg!r}")


def test_a_bin_SALVA_continua_sendo_lida_normalmente(bin_sincronizada):
    """⚠️ Guarda ampla demais também é defeito. A recusa acima não pode alcançar a
    bin boa — que é o caso comum, e tem masters dentro."""
    takes, forma = T.ler(str(bin_sincronizada))

    assert forma == "sequencia"
    assert takes, "a bin com masters deixou de ser lida"
    assert not [t for t in takes if str(t.nome).startswith("urn:smpte:umid:")], (
        "take com UMID no lugar do nome numa bin que TEM masters")


def test_a_recusa_olha_a_BIN_e_nao_cada_SourceClip(bin_sincronizada):
    """⚠️ A pergunta é "há master NESTA bin?", não "há master para cada clipe".

    Faltar UM master é outro problema — o clipe que não está no projeto —, e ele já
    tem tratamento próprio (o take sai marcado, não a bin inteira recusada). Confundir
    os dois faria uma diária com um clipe fora do projeto ser recusada por inteiro.
    """
    import inspect

    fonte = inspect.getsource(T.ler)
    assert "any(e_master(m) for m in f.content.mobs)" in fonte, (
        "a checagem deixou de ser 'existe ALGUM master na bin' — se ela passou a "
        "exigir um master por SourceClip, uma diária com um clipe fora do projeto "
        "passa a ser recusada inteira")
