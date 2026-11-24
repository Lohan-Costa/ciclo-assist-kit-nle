"""Fixtures de `.avb` sintética — o que torna o P2a testável sem o Media Composer.

⭐ **Por que sintética e não a bin real.** `$PROJETO\\O PRODUCAO-A\\D02\\D02_SOM.avb`
existe nesta máquina e não existe em nenhuma outra. Um teste que dependa dela vira um
`skipif` — e um `skipif` que sempre pula é a forma mais educada de falso-verde que há.
A fixture fabrica a mesma ESTRUTURA (não a mesma mídia) em memória, e por isso roda
em qualquer lugar. O material real entra na Task 8, como verificação, nunca como
cobertura.

⚠️ **A fixture reproduz de propósito a armadilha do `track_id`.** O master de câmera
tem `picture index=1` **e** `sound index=1` — medido em `D02_CAM A.avb`. É a forma
exata que faz um leitor descuidado pôr som na trilha de imagem sem erro nenhum.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ⛔ A suíte NÃO escreve na pasta real do usuário (2026-11-07: o `sincronizar.log` dela aparecia em
# `…/CicloAssist/sincronizar/logs`, e antes em `…/Orbita/logs`). `appsettings.app_data_dir` obedece a esta variável.
os.environ.setdefault("SINCRONIZAR_DADOS", tempfile.mkdtemp(prefix="sincronizar-testes-"))

# ⚠️ Antes de qualquer import de `avid`/`media`/`nomes`: o pytest do Órbita
# roda a partir de `src-python/`, e é este insert que põe os pacotes no path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import random
from pathlib import Path

import pytest

import avb
from avb.mobid import MobID

from avid.takes import Tomada, Trecho

ER = 23.976            # o projeto de *PRODUCAO-A* — nunca o 25 padrão do pyavb
MAXLEN = 2147483647


def _attrs(f, **kv):
    a = f.create.Attributes()
    for chave, valor in kv.items():
        a[chave] = valor
    return a


def _filler(f, comprimento: int, kind: str):
    fl = f.create.Filler(ER, kind)
    fl.length = comprimento
    return fl


def _trackref(f, kind: str):
    tr = f.create.TrackRef(ER, kind)
    tr.length = MAXLEN
    tr.relative_scope = 0
    tr.relative_track = -1
    return tr


def _master(f, nome: str, trilhas: list[tuple[int, str, int]]):
    """Um MasterMob com as trilhas pedidas. `trilhas` é `[(index, kind, duração)]`.

    ⚠️ `f.create.Composition(nome, ...)` IGNORA o argumento `nome` — o `__init__` do
    pyavb faz `self.name = mob_type`. Sem a atribuição explícita abaixo, todo master
    da fixture se chamaria "MasterMob" e os testes de claquete casariam nada.
    """
    m = f.create.Composition(nome, "MasterMob")
    m.name = nome
    m.usage_code = 7                      # 'mastermob', como o MC grava
    m.edit_rate = ER
    m.media_kind_id = 0
    m.length = max(c for _i, _k, c in trilhas)
    m.mc_mode = 0
    m.num_scalars = 0
    m.param_list = None
    m.tracks = []
    for index, kind, comprimento in trilhas:
        sc = f.create.SourceClip(ER, kind)
        sc.mob_id = MobID.new()           # o SourceMob de folha não importa aqui
        sc.track_id = 1
        sc.start_time = 0
        sc.length = comprimento
        t = f.create.Track()
        t.index = index
        t.component = sc
        t.lock_number = 0
        m.tracks.append(t)
    f.content.add_mob(m).user_placed = True
    return m


def _sequencia(f, kind: str, itens, total: int):
    """A Sequence de uma track: filler de cabeça, gaps, clipes, filler de cauda.

    `itens` é `[(inicio_na_timeline, duração, mob_id, canal, inicio_no_master)]`.
    """
    seq = f.create.Sequence(ER, kind)
    seq.components = []
    pos = 0
    if not itens or itens[0][0] > 0:
        seq.components.append(_filler(f, 0, kind))
    for inicio, dur, mob_id, canal, origem in itens:
        if inicio > pos:
            seq.components.append(_filler(f, inicio - pos, kind))
            pos = inicio
        sc = f.create.SourceClip(ER, kind)
        sc.mob_id = mob_id
        sc.track_id = canal
        sc.start_time = origem
        sc.length = dur
        seq.components.append(sc)
        pos = inicio + dur
    seq.components.append(_filler(f, max(0, total - pos), kind))
    return seq


# ── O material sintético: dois planos da cena 4, um da cena 7 ────────────────
# Nomes na convenção medida em `D02_SOM.avb`; câmeras na convenção da Blackmagic
# medida em `D02_CAM A.avb`.
NOMES_DE_SOM = [
    "PROJETO A - 05-04 C4 P1-T001",
    "PROJETO A - 05-04 C4 P1-T002",
    "PROJETO A - 05-04 C7 P3-T001",
]
NOME_DE_CAMERA = "a004_03170908_C001"
NOME_DA_SEGUNDA_CAMERA = "a002_03170657_C001"

# (inicio na timeline, duração) de cada take de som. O buraco entre eles é real:
# o técnico para de gravar entre takes.
JANELAS = [(100, 1000), (1500, 1200), (3000, 900)]
TOTAL = 4200

# ⚠️ Fora de ordem de propósito (revisão de mutação, rodada 1, 2026-08-25): o canal 4
# vem depois do 5. Com `range(1, 6)` a posição da track no SUBCLIPE (sequencial,
# 1..5) sempre coincidia com o `track_id` do MASTER (também 1..5) — e um autor que
# confundisse os dois (a distinção que `subclipes.montar_mob` documenta: índice da
# track é sequencial POR TIPO DE MÍDIA; `track_id` é o canal de origem no master)
# passaria despercebido, porque as duas regras davam o mesmo resultado.
CANAIS_DE_SOM = [1, 2, 3, 5, 4]

# ⚠️ Margem de propósito (revisão de mutação, rodada 1): a câmera cobre um pouco mais
# do que a janela do som — plausível (a câmera roda contínuo, o som liga por take) — e
# fecha o mutante `sc.length = take.duracao`, que passava despercebido enquanto o
# `Trecho` de imagem e o `Tomada.duracao` usavam a MESMA variável `dur`.
MARGEM_DE_CAMERA = 15


def _escrever(caminho: Path, com_timeline: bool) -> Path:
    with avb.open() as f:
        soms = [_master(f, nome, [(i, "sound", 2000) for i in range(1, 6)])
                for nome in NOMES_DE_SOM]
        # ⚠️ A ARMADILHA, de propósito: picture 1 E sound 1 na mesma mob.
        camera = _master(f, NOME_DE_CAMERA,
                         [(1, "picture", TOTAL), (1, "sound", TOTAL), (2, "sound", TOTAL)])

        if com_timeline:
            linhas = [("picture", [(0, TOTAL, camera.mob_id, 1, 0)])]
            for canal in range(1, 6):
                linhas.append(("sound", [
                    (inicio, dur, som.mob_id, canal, 20 * n)
                    for n, ((inicio, dur), som) in enumerate(zip(JANELAS, soms))
                ]))

            comp = f.create.Composition("D02 SYNC", "CompositionMob")
            comp.name = "D02 SYNC"
            comp.usage_code = 0
            comp.edit_rate = ER
            comp.media_kind_id = 0
            comp.length = TOTAL
            comp.mc_mode = 0
            comp.num_scalars = 0
            comp.param_list = None
            comp.attributes = _attrs(f, _VERSION=2)
            comp.tracks = []
            idx = {"picture": 0, "sound": 0}
            for kind, itens in linhas:
                idx[kind] += 1
                t = f.create.Track()
                t.index = idx[kind]
                t.component = _sequencia(f, kind, itens, TOTAL)
                t.lock_number = 0
                t.filler_proxy = _trackref(f, kind)
                comp.tracks.append(t)
            f.content.add_mob(comp).user_placed = True

        # ⚠️ `uid` novo em TODA gravação — sem isso o MC recusa com FILE_OPEN_FAILURE
        # enquanto houver bin de mesmo uid aberta (regra 1 de `avb_bin/__init__.py`).
        f.content.uid = random.getrandbits(63)
        f.write(str(caminho))
    return caminho


@pytest.fixture
def bin_de_masters(tmp_path) -> Path:
    """Uma bin só com masters: 3 de som (5 trilhas cada) e 1 de câmera."""
    return _escrever(tmp_path / "masters.avb", com_timeline=False)


@pytest.fixture
def bin_sincronizada(tmp_path) -> Path:
    """Os mesmos masters MAIS a timeline sincronizada — a forma `A` do spike."""
    return _escrever(tmp_path / "D02 SYNC.avb", com_timeline=True)


@pytest.fixture
def takes_de_exemplo(bin_de_masters) -> list[Tomada]:
    """Três `Tomada` montados à mão a partir dos masters da fixture.

    ⭐ Montados à mão de propósito: a Task 3 exercita o AUTOR de subclipe sem
    depender do LEITOR (Task 4). Se o leitor estiver errado, é o teste dele que fica
    vermelho — não o do autor.
    """
    from avid.leitura import abrir
    from avid.percurso import e_master

    from media import claquete as C

    with abrir(str(bin_de_masters)) as f:
        por_nome = {m.name: str(m.mob_id) for m in f.content.mobs if e_master(m)}

    fora = []
    for n, (nome, (_inicio, dur)) in enumerate(zip(NOMES_DE_SOM, JANELAS)):
        trechos = [Trecho(mob_id=por_nome[NOME_DE_CAMERA], track_id=1,
                          media_kind="picture", start=100 * n,
                          length=dur + MARGEM_DE_CAMERA, deslocamento=0)]
        trechos += [Trecho(mob_id=por_nome[nome], track_id=canal,
                           media_kind="sound", start=20 * n, length=dur,
                           deslocamento=0)
                    for canal in CANAIS_DE_SOM]
        c = C.ler(nome)
        fora.append(Tomada(
            nome=C.nome_de_subclipe(c),
            cena=c.cena, plano=c.plano, take=c.take, convencao=c.convencao,
            edit_rate=ER, duracao=dur, trechos=tuple(trechos),
            origem="sequencia", nome_do_som=nome, descartado=False,
        ))
    return fora


def _escrever_variacao(caminho: Path, *, nomes_de_som=None, atraso_da_camera=0,
                       com_camera=True, fim_da_camera=None,
                       com_som_de_camera=False, camera_orfa=None,
                       camera_partida=None, segunda_camera=None,
                       atraso_do_som_da_camera=0,
                       imagem_aparada_na_cabeca=0) -> Path:
    """Uma bin sincronizada com UMA variação isolada.

    ⭐ Uma variação por função, e nunca duas na mesma bin: quando o teste fica
    vermelho, a bin diz qual condição o causou. Uma fixture que varia três coisas de
    uma vez transforma toda falha em investigação.

    ⚠️ `com_som_de_camera` é a exceção justificada a essa regra, e ela vem do material
    real: em `D02_SYNC.avb` o som da câmera está SEMPRE lá, em duas trilhas de som
    (idx 6 e 7) além das cinco do som direto. Testar órfão de imagem sem ele seria
    testar uma bin que a sincronização não produz.
    """
    nomes = list(nomes_de_som or NOMES_DE_SOM)
    with avb.open() as f:
        soms = [_master(f, nome, [(i, "sound", 2000) for i in range(1, 6)])
                for nome in nomes]
        linhas = []
        if com_camera:
            camera = _master(
                f, NOME_DE_CAMERA,
                [(1, "picture", TOTAL), (1, "sound", TOTAL), (2, "sound", TOTAL)])
            # A câmera entra `atraso_da_camera` frames depois do início do 1º take.
            inicio = JANELAS[0][0] + atraso_da_camera
            fim = TOTAL if fim_da_camera is None else fim_da_camera
            if camera_partida is not None:
                # Vários pedaços da MESMA câmera. ⚠️⚠️ Cada um com o SEU offset no
                # master, medido a partir do primeiro: um clipe de câmera cortado em
                # dois entra na timeline em duas posições e em dois pontos do arquivo.
                # Com todos em `start_time = 0` — como esta fixture nascia — posição
                # na timeline e offset no master ficam INDISTINGUÍVEIS, e um leitor
                # que confunda os dois passa despercebido. Medido em 2026-08-26: a
                # mutação `deslocamento=0` sobrevivia à conferência de sincronia
                # inteira por causa disto.
                base = camera_partida[0][0]
                segmentos_de_camera = [
                    (i, d, camera.mob_id, 1, i - base) for i, d in camera_partida]
            else:
                segmentos_de_camera = [
                    (inicio, fim - inicio, camera.mob_id, 1, 0)]
            if camera_orfa is not None:
                # ⚠️ ANTES do segmento normal, e a lista tem de sair em ordem de
                # timeline: `_sequencia` monta filler por diferença e um item fora de
                # ordem produziria filler negativo, calado.
                orfa_ini, orfa_dur = camera_orfa
                segmentos_de_camera.insert(
                    0, (orfa_ini, orfa_dur, camera.mob_id, 1, 0))
            if imagem_aparada_na_cabeca:
                # ⚠️ SÓ a imagem se move: entra mais tarde na timeline E mais adiante
                # dentro do master, que é o que um trim de cabeça na trilha de vídeo
                # produz. O som da câmera fica onde estava — e passa a COMEÇAR ANTES
                # da imagem dela, que é o único jeito de `a - posicao` sair diferente
                # de zero em `_som_da_propria_camera`.
                n = imagem_aparada_na_cabeca
                linhas.append(("picture", [
                    (ini + n, max(0, dur - n), mob_id, canal, origem + n)
                    for ini, dur, mob_id, canal, origem in segmentos_de_camera
                ]))
            else:
                linhas.append(("picture", segmentos_de_camera))
        for canal in range(1, 6):
            linhas.append(("sound", [
                (ini, dur, som.mob_id, canal, 20 * n)
                for n, ((ini, dur), som) in enumerate(zip(JANELAS, soms))
            ]))
        if com_camera and com_som_de_camera:
            # As duas trilhas de som da CÂMERA, nas mesmas posições da imagem — a
            # forma medida em `D02_SYNC.avb`.
            # ⚠️ `atraso_do_som_da_camera` desloca SÓ o som da câmera em relação à
            # imagem dela. Não é o caso normal (é o mesmo arquivo, entra junto), mas
            # acontece quando alguém apara o áudio na sequência — e é a única forma de
            # o `deslocamento` do som de um órfão sair diferente de zero.
            for canal in (1, 2):
                linhas.append(("sound", [
                    (ini + atraso_do_som_da_camera,
                     max(0, dur - atraso_do_som_da_camera),
                     mob_id, canal, origem + atraso_do_som_da_camera)
                    for ini, dur, mob_id, _c, origem in segmentos_de_camera
                ]))
        if com_camera and segunda_camera is not None:
            # ⚠️ Uma câmera B, em trilha própria de imagem e com som próprio. Ela
            # existe para provar que o som de um órfão vem da PRÓPRIA câmera.
            b_ini, b_dur = segunda_camera
            camera_b = _master(
                f, NOME_DA_SEGUNDA_CAMERA,
                [(1, "picture", TOTAL), (1, "sound", TOTAL), (2, "sound", TOTAL)])
            linhas.append(("picture", [(b_ini, b_dur, camera_b.mob_id, 1, 0)]))
            for canal in (1, 2):
                linhas.append(("sound", [(b_ini, b_dur, camera_b.mob_id, canal, 0)]))

        comp = f.create.Composition("VARIACAO", "CompositionMob")
        comp.name = "VARIACAO"
        comp.usage_code = 0
        comp.edit_rate = ER
        comp.media_kind_id = 0
        comp.length = TOTAL
        comp.mc_mode = 0
        comp.num_scalars = 0
        comp.param_list = None
        comp.attributes = _attrs(f, _VERSION=2)
        comp.tracks = []
        idx = {"picture": 0, "sound": 0}
        for kind, itens in linhas:
            idx[kind] += 1
            t = f.create.Track()
            t.index = idx[kind]
            t.component = _sequencia(f, kind, itens, TOTAL)
            t.lock_number = 0
            t.filler_proxy = _trackref(f, kind)
            comp.tracks.append(t)
        f.content.add_mob(comp).user_placed = True
        f.content.uid = random.getrandbits(63)
        f.write(str(caminho))
    return caminho


def escrever_com_camera_atrasada(caminho: Path, atraso: int) -> Path:
    """A câmera entra `atraso` frames depois do começo do primeiro take de som."""
    return _escrever_variacao(caminho, atraso_da_camera=atraso)


def escrever_sem_camera(caminho: Path) -> Path:
    """Só som — a câmera parou antes, o técnico seguiu gravando."""
    return _escrever_variacao(caminho, com_camera=False)


def escrever_com_som_sem_claquete(caminho: Path) -> Path:
    """Sons cujo nome não casa com convenção nenhuma. ⚠️ NÃO é erro (§11)."""
    return _escrever_variacao(
        caminho, nomes_de_som=["GRAVACAO 001", "GRAVACAO 002", "GRAVACAO 003"])


def escrever_com_uma_claquete_ilegivel(caminho: Path) -> Path:
    """Duas janelas com claquete boa, uma com nome que não casa convenção nenhuma.

    ⚠️⚠️ O caso do meio-termo (revisão de mutação, rodada 1, 2026-08-25): uma bin real
    mistura take resolvido e não resolvido na MESMA sequência. `com_claquete or
    set(janelas)` só falha no all-or-nothing — e esta é a fixture que prova que o meio
    é o caso real, não um extremo teórico."""
    return _escrever_variacao(
        caminho, nomes_de_som=[NOMES_DE_SOM[0], "GRAVACAO 002", NOMES_DE_SOM[2]])


def escrever_com_som_de_camera(caminho: Path) -> Path:
    """A forma REAL: som direto em 5 trilhas MAIS o som da câmera em 2.

    ⚠️⚠️ É a bin que a sincronização de verdade produz, e é a que expôs o defeito de
    2026-08-26: um leitor que trate TODO segmento de som como janela de take fabrica
    um take por clipe de câmera. No material real isso encheu a bin `NAO RESOLVIDO`
    com 26 clipes de câmera que nunca foram takes.
    """
    return _escrever_variacao(caminho, com_som_de_camera=True)


def escrever_com_camera_orfa_de_imagem_aparada(caminho: Path) -> Path:
    """Câmera órfã cuja IMAGEM foi aparada na cabeça, e cujo som não.

    ⚠️⚠️ O som da câmera passa a **começar antes** da imagem dela. É a única forma em
    que `_som_da_propria_camera` precisa somar `a - posicao` ao `start` — em todo o
    resto do material esse termo é zero, e a linha que o calcula seria código
    defensivo que teste nenhum alcança.

    Realista? É o que sobra quando alguém apara a trilha de vídeo na sequência e
    esquece a de áudio. A sincronização não produz isto; uma mão humana produz.
    """
    return _escrever_variacao(caminho, com_som_de_camera=True,
                              camera_orfa=(0, 90), imagem_aparada_na_cabeca=20)


def escrever_com_camera_orfa_de_som_aparado(caminho: Path) -> Path:
    """Câmera órfã cujo SOM entra depois da imagem dela.

    ⚠️ Não é a forma que a sincronização produz — imagem e som da câmera são o mesmo
    arquivo e entram juntos. Acontece quando alguém apara o áudio na sequência à mão, e
    é o **único** caso em que o `deslocamento` do som de um órfão sai diferente de
    zero. Sem esta fixture, a linha que o calcula (`deslocamento = a - inicio` em
    `_som_da_propria_camera`) é código defensivo que teste nenhum alcança — e código
    defensivo não exercitado é exatamente o que o §12 do spec chama de decoração.
    """
    return _escrever_variacao(caminho, com_som_de_camera=True,
                              camera_orfa=(0, 90), atraso_do_som_da_camera=20)


def escrever_com_camera_orfa(caminho: Path, inicio: int = 0,
                             duracao: int = 90) -> Path:
    """Um clipe de câmera que nenhuma janela de som cobre — e com o som da câmera.

    ⭐ O caso do material real: `a001_03170214_C001` roda de 0 a 11620 e o som direto
    só começa em 60226. O editor ainda quer o subclipe, para renomear sem tocar no
    master; e nele o som da CÂMERA é o único que existe, então fica.
    """
    assert inicio + duracao <= JANELAS[0][0],         "a câmera órfã tem de caber ANTES da primeira janela de som"
    return _escrever_variacao(caminho, com_som_de_camera=True,
                              camera_orfa=(inicio, duracao))


def escrever_com_camera_que_acaba_cedo(caminho: Path, corte: int = 30) -> Path:
    """A câmera para `corte` frames ANTES do fim da primeira janela de som.

    ⚠️ Os takes 2 e 3 ficam sem imagem nenhuma nesta bin — é consequência, não alvo.
    Quem afirma é sempre o take 0.
    """
    return _escrever_variacao(
        caminho, fim_da_camera=JANELAS[0][0] + JANELAS[0][1] - corte)


def escrever_com_camera_partida(caminho: Path) -> Path:
    """DUAS câmeras dentro da MESMA janela de som, com um vão entre elas.

    ⭐⭐ O caso do material real, medido em `D02_SYNC.avb`: o take `C7 P2-T002` cobre
    549922–555586, e cruzando essa janela há dois pedaços de câmera — um fragmento de
    8 frames (uma partida em falso) e o clipe de verdade, com 22 frames de vão entre
    eles.

    ⚠️⚠️ É a fixture que decide UNIÃO contra INTERSEÇÃO no aparo. Sem ela, as duas
    contas dão o mesmo resultado em todo material sintético — e a interseção, aqui,
    daria uma janela de comprimento NEGATIVO.
    """
    ini, dur = JANELAS[0]
    return _escrever_variacao(
        caminho, com_som_de_camera=True,
        camera_partida=[(ini + 50, 50), (ini + 150, 750)])


def escrever_com_duas_cameras(caminho: Path) -> Path:
    """Uma câmera órfã, e uma SEGUNDA câmera cujo som cobre a janela dela.

    ⚠️⚠️ A armadilha que esta fixture arma: montar o som do órfão pegando "o som de
    câmera que cruza a janela" traria os canais da câmera B para dentro do subclipe da
    câmera A. O casamento tem de ser por `mob_id`, e é só isso que separa as duas.
    """
    return _escrever_variacao(
        caminho, com_som_de_camera=True,
        camera_orfa=(0, 90),
        segunda_camera=(50, TOTAL - 50))


def escrever_com_camera_em_dois_arquivos(caminho: Path) -> Path:
    """Dois pedaços de câmera ENCOSTADOS dentro da mesma janela de som.

    ⭐ O caso do *spanning*: a câmera quebra a gravação em dois arquivos ao passar de
    4 GB, e os dois entram na timeline colados, sem um frame de vão.

    ⚠️⚠️ É o oposto de `escrever_com_camera_partida`, e a diferença é a regra inteira:
    **encostado não é vão.** Com vão, o aparo fica com o maior lado e deixa o resto de
    fora; encostados, a região é uma só e os dois pedaços ficam — na MESMA trilha do
    subclipe, sem filler entre eles.
    """
    ini, _dur = JANELAS[0]
    return _escrever_variacao(
        caminho, com_som_de_camera=True,
        camera_partida=[(ini + 50, 400), (ini + 450, 400)])


def escrever_sem_o_master_de_som(caminho: Path) -> Path:
    """Uma timeline que referencia um master de som que **não está na bin**.

    ⚠️ Não é bin quebrada: é a forma "bin com só a timeline", que o banco de NLEs
    registra e que o próprio `takes_da_sequencia` prevê — ele junta esses `mob_id` em
    `sem_master` e loga. O que faltava era o take resultante ter nome.
    """
    from avb.mobid import MobID

    fantasma = MobID.new()
    with avb.open() as f:
        camera = _master(f, NOME_DE_CAMERA,
                         [(1, "picture", TOTAL), (1, "sound", TOTAL)])
        comp = f.create.Composition("SEM MASTER", "CompositionMob")
        comp.name = "SEM MASTER"
        comp.usage_code = 0
        comp.edit_rate = ER
        comp.media_kind_id = 0
        comp.length = TOTAL
        comp.mc_mode = 0
        comp.num_scalars = 0
        comp.param_list = None
        comp.attributes = _attrs(f, _VERSION=2)
        comp.tracks = []
        linhas = [("picture", [(100, 1000, camera.mob_id, 1, 0)]),
                  ("sound", [(100, 1000, fantasma, 1, 0)])]
        for kind, itens in linhas:
            t = f.create.Track()
            t.index = 1
            t.component = _sequencia(f, kind, itens, TOTAL)
            t.lock_number = 0
            t.filler_proxy = _trackref(f, kind)
            comp.tracks.append(t)
        f.content.add_mob(comp).user_placed = True
        f.content.uid = random.getrandbits(63)
        f.write(str(caminho))
    return caminho


def escrever_com_orfaos_entre_takes(caminho: Path) -> Path:
    """Câmera cobrindo cada janela de som, MAIS dois pedaços soltos no vão do meio.

    ⭐ É o cenário que o autor descreveu em 2026-08-26: *"tenho na cena 4 o take 1,
    take 2, arquivo órfão, take 3"*. Aqui há dois órfãos seguidos, para provar também
    a numeração `.1` / `.2`.

    ⚠️ Os pedaços soltos caem no buraco entre a primeira e a segunda janela de som
    (1100–1500), então nenhum take os usa — e é por isso que são órfãos.
    """
    pedacos = [(ini, dur) for ini, dur in JANELAS]
    pedacos.insert(1, (1150, 100))
    pedacos.insert(2, (1300, 100))
    return _escrever_variacao(caminho, com_som_de_camera=True,
                              camera_partida=sorted(pedacos))


def _escrever_sem_masters(caminho: Path) -> Path:
    """Uma bin com a SEQUÊNCIA sincronizada e **nenhum master dentro**.

    ⛔⛔ É o estado real de uma bin que o Media Composer ainda não SALVOU — a que
    aparece com o asterisco ao lado do nome. Medido em 2026-08-27, comparando a bin
    recém-entregue pelo Sincronizar com a `D02_SYNC.avb` do spike:

        spike : 299 mobs, 50 masters, 198 SourceClips
        recém :   1 mob,   0 masters, 198 SourceClips

    A sequência está inteira e certa; os masters é que só entram no arquivo quando o
    editor salva. Ver `takes.BinNaoSalva`.

    ⚠️ Os `SourceClip` apontam para mob_ids que NÃO existem nesta bin — de propósito.
    É exatamente o que o leitor encontra, e o que o fazia entregar takes com o UMID
    cru no lugar do nome.
    """
    with avb.open() as f:
        # Os masters são criados só para render os mob_ids, e NÃO entram na bin.
        with avb.open() as descartavel:
            soms = [_master(descartavel, nome, [(i, "sound", 2000) for i in range(1, 6)])
                    for nome in NOMES_DE_SOM]
            camera = _master(descartavel, NOME_DE_CAMERA,
                             [(1, "picture", TOTAL), (1, "sound", TOTAL)])
            ids_de_som = [s.mob_id for s in soms]
            id_da_camera = camera.mob_id

        linhas = [("picture", [(0, TOTAL, id_da_camera, 1, 0)])]
        for canal in range(1, 6):
            linhas.append(("sound", [
                (inicio, dur, mob_id, canal, 20 * n)
                for n, ((inicio, dur), mob_id) in enumerate(zip(JANELAS, ids_de_som))
            ]))

        comp = f.create.Composition("D02 SYNC", "CompositionMob")
        comp.name = "D02 SYNC"
        comp.usage_code = 0
        comp.edit_rate = ER
        comp.media_kind_id = 0
        comp.length = TOTAL
        comp.mc_mode = 0
        comp.num_scalars = 0
        comp.param_list = None
        comp.attributes = _attrs(f, _VERSION=2)
        comp.tracks = []
        idx = {"picture": 0, "sound": 0}
        for kind, itens in linhas:
            idx[kind] += 1
            t = f.create.Track()
            t.index = idx[kind]
            t.component = _sequencia(f, kind, itens, TOTAL)
            t.lock_number = 0
            t.filler_proxy = _trackref(f, kind)
            comp.tracks.append(t)
        f.content.add_mob(comp).user_placed = True

        f.content.uid = random.getrandbits(63)
        f.write(str(caminho))
    return caminho


@pytest.fixture
def bin_nao_salva(tmp_path) -> Path:
    """A sequência sincronizada sem os masters — a bin com asterisco no MC."""
    return _escrever_sem_masters(tmp_path / "RECEM ENTREGUE.avb")
