"""O que circula pelo módulo Preparar: o TAKE, e os trechos de master que o compõem.

⭐ Portado do Assist anterior (`assist_anterior/modulos/preparar/takes.py`) em
2026-09-05, sem mudança de lógica.

⚠️⚠️ **`Take` virou `Tomada` no porte, e a troca não é estética.** O Órbita já
tem `sync.model.Take` — *"um som direto e as câmeras que o filmaram"* —, e o
desta casa é outra coisa: *"o que vira um subclipe"*, com trechos, mob_id e
duração bruta. Dois `Take` no mesmo sidecar é a colisão que ninguém percebe até
um `from ... import Take` no arquivo errado — e aí o erro não é de importação,
é de significado.
⭐ **`Tomada` é a costura do P2a.** O spec não diz que forma tem a "bin sincronizada"
(§5.1), e o spike da Task 1 é quem responde. Tudo que vem depois — autorar o subclipe,
agrupar por cena, mostrar no painel — consome `Tomada` e **não sabe de onde ele veio**.
Se a resposta do spike mudar, muda um leitor; não muda o autor, nem a bin de cena,
nem a interface.

⚠️ A unidade é o **TAKE**, não o plano (resolvido em 2026-08-25). `C4 P1-T002` é um
subclipe; `C4 P1` é um agrupamento de subclipes dentro da bin da cena. O motivo mais
duro é de sincronização: a claquete que dá cena/plano/take é do som, e o pareamento
som↔câmera acontece **por take** — um para um.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Trecho:
    """Um pedaço de um master que entra numa track do subclipe.

    `mob_id`      — o MobID do MASTER, em `str` (é assim que `percurso.por_mob_id`
                    chaveia, e comparar duas representações do mesmo MobID como
                    strings diferentes é o erro clássico da família `remap.py`).
    `track_id`    — o índice DENTRO do master. ⚠️ Sozinho não identifica a track:
                    um master de câmera tem `picture 1` **e** `sound 1`. É por isso
                    que `media_kind` viaja junto, e nunca separado.
    `media_kind`  — `"picture"` ou `"sound"`.
    `start`       — o frame inicial dentro do master (o *in* do subclipe).
    `length`      — a duração em frames.
    `trilha_de_origem`
                  — o índice da trilha da SEQUÊNCIA (ou do subclipe) de onde este
                    trecho veio. ⚠️⚠️ **Não confundir com `track_id`**: `track_id` diz
                    de que canal do MASTER o material vem; `trilha_de_origem` diz em
                    que trilha do MATERIAL DE ORIGEM ele estava — e é ela que decide em
                    que trilha do subclipe ele reaparece. Uma câmera que parou e voltou
                    dá dois trechos com o MESMO `mob_id` e o MESMO `track_id`; só a
                    trilha de origem os reconhece como a mesma câmera.
                    ⚠️ **Zero significa NÃO INFORMADA**, e aí cada trecho ganha trilha
                    própria — o contrato anterior a 2026-08-26.
    `deslocamento`— quantos frames este trecho começa DEPOIS do início do take. ⚠️
                    **Desde o aparo de 2026-08-26 ele já não descreve câmera atrasada**:
                    onde falta imagem, apara-se — na cabeça, na cauda e no meio. O que
                    ainda pode produzi-lo é **multicâmera em revezamento**: uma câmera
                    cobre um pedaço da janela e outra cobre o resto, cada uma na sua
                    trilha, e aí cada trilha tem filler onde a outra estava. Medido na
                    `D02_SYNC.avb` real: **zero** subclipes precisam de filler, contra
                    24 em 25 antes do aparo.
    """

    mob_id: str
    track_id: int
    media_kind: str
    start: int
    length: int
    deslocamento: int = 0
    trilha_de_origem: int = 0


@dataclass(frozen=True)
class Tomada:
    """Uma tomada: um som com claquete e as câmeras que a cobrem.

    `nome`       — o nome do subclipe. `C04_P01_T002` quando a claquete foi lida;
                   o nome do master de som quando não foi (§11: **nunca se inventa**).
    `cena`       — `"C04"`, ou **`None`** para cena não resolvida.
    `descartado` — `True` (`FALSE TAKE`/`TRASH`), `False`, ou **`None` = NÃO
                   AVALIADO**. ⚠️ `None` não é `False`: sem o caminho do arquivo não
                   há como atestar que o take sobreviveu ao descarte (§7).
    `origem`     — de que forma de material este take foi lido: `"sequencia"`,
                   `"grupo"` ou `"subclipe"`. Vai para o relatório do painel, porque
                   procedência é requisito e não enfeite.
    """

    nome: str
    cena: str | None
    plano: str | None
    take: str | None
    edit_rate: float
    duracao: int
    trechos: tuple[Trecho, ...]
    origem: str
    # ⭐ O nome do master de SOM que deu a claquete. Viaja junto por dois motivos:
    # rastreabilidade (`C04_P01_T002` sozinho não diz de que WAV veio) e porque é a
    # chave que casa o take com o arquivo em disco, para avaliar o descarte sem
    # gastar uma chamada de ~500 ms ao Media Composer por master.
    nome_do_som: str = ""
    #: ⭐ O nome do master de VÍDEO que compõe a tomada — a base do nome padrão.
    #:
    #: Decisão do autor, 2026-09-05: *"o nome padrão do subclipe deve ser o nome do
    #: arquivo de vídeo que o compõe, salvo exceções de ser um subclipe formado
    #: apenas pelo áudio"*. O nome do som identificava a TOMADA (era a chave da
    #: claquete), mas quem o editor procura na bin é o clipe de câmera.
    #:
    #: ⚠️ Vazio quando a tomada não tem imagem — e aí o nome cai no som, que é a
    #: exceção que a regra prevê.
    nome_do_video: str = ""
    descartado: bool | None = None
    convencao: str | None = None
    # ⭐⭐ O MobID do PRÓPRIO clipe — o subclipe ou o masterclipe que este take É.
    # Não confundir com `Trecho.mob_id`, que é o do MASTER referenciado: apontar
    # uma timeline para o master traria o arquivo inteiro em vez do recorte.
    #
    # ⚠️ **Vazio quando o take veio de uma SEQUÊNCIA**, e isso é a resposta certa:
    # uma região de timeline não é um objeto da bin, e não há clipe para
    # referenciar. É esta ausência que faz o emissor por referência exigir bin de
    # clipes — e dizê-lo, em vez de cunhar subclipes por baixo do pano.
    mob_id: str = ""
    # ⭐ A sincronização NÃO pareou este material: câmera sem som direto por baixo,
    # ou som direto que nenhuma câmera cobriu. ⚠️ Não é o mesmo que "falta uma
    # trilha": um órfão de imagem sai COM som — o da própria câmera. Só quem leu a
    # timeline sabe disto, e por isso é campo, e não propriedade derivada dos trechos.
    orfao: bool = False
    # ⭐ Só em série: `E03`. Fica fora de `cena` para o nome poder usar um sem o outro, e entra na chave da bin por cena.
    episodio: str | None = None
    # ⭐ A duração da janela de som ANTES do aparo. `duracao_bruta - duracao` é quanto
    # de som ficou de fora por não ter imagem por baixo, e é informação que o editor
    # precisa ver ANTES de abrir a bin: um take que perdeu 88 s de cauda porque a
    # câmera parou cedo continua sendo um take legítimo, mas não é o que ele gravou.
    # ⚠️ Igual a `duracao` quando não houve o que aparar — nunca zero por omissão.
    duracao_bruta: int = 0

    @property
    def aparado(self) -> int:
        """Frames de som que ficaram de fora do subclipe."""
        return max(0, (self.duracao_bruta or self.duracao) - self.duracao)

    @property
    def resolvido(self) -> bool:
        return self.cena is not None


# ─────────────────────────────────────────────────────────────────────────────
# Os leitores: de material no Avid para `Tomada`.
#
# ⭐ A assimetria do achado 1 é o algoritmo inteiro: só o SOM tem claquete. Um take
# não é um intervalo qualquer da timeline — é um segmento de som cujo master LÊ como
# claquete, e as câmeras são o que cruza aquela janela. O leitor não adivinha nada;
# ele pergunta ao `claquete.ler()` e o material se separa sozinho.
# ─────────────────────────────────────────────────────────────────────────────

import re

import registro

from avid.percurso import e_master, e_subclipe, por_mob_id, timeline

from media import identidade as _identidade

from media import claquete as _claquete

log = registro.log(__name__)

# ⭐ O formato que `claquete.nome_de_subclipe` escreve (`C04_P01_T002`). Não é uma
# convenção de claquete de câmera/som — é o NOSSO próprio formato de saída — por isso
# fica aqui, e não em `claquete.CONVENCOES`: registrá-la lá afetaria toda leitura de
# nome de master no projeto, não só a releitura de subclipes já produzidos.
# ⚠️ O `(\.\d+)?` no fim aceita o take FRACIONÁRIO que o batismo de órfão produz
# (`C04_P01_T002.1`). Sem ele, reler uma bin de subclipes perderia a cena justamente
# dos itens que mais precisam de revisão humana.
#
# ⚠️⚠️ O plano reusa `claquete._QUALIFICADOR`, e o acoplamento é DE PROPÓSITO. Desde
# 2026-08-28 o plano pode trazer um qualificador com espaço (`P03 PICUP`, vindo de
# `C11 P3 PICUP/001`), e este regex é quem relê o nome quando a bin de subclipes não
# carrega os masters. Duas cópias da mesma forma divergiriam calado: `claquete` escreve
# um nome que este leitor não reconhece, a releitura devolve `cena=None`, e o pickup cai
# em `NAO RESOLVIDO` numa passagem e na bin da cena na outra — com o MESMO material.
# ⭐ O FORMATO segue sendo nosso, não uma convenção de claquete (por isso continua aqui
# e não em `claquete.CONVENCOES`); o que se compartilha é só a forma do plano.
_NOME_CANONICO = re.compile(
    r"^C(?P<cena>\d+[A-Za-z]?)_P(?P<plano>\d+[A-Za-z]?" + _claquete._QUALIFICADOR +
    r")_T(?P<take>\d+(?:\.\d+)?)$"
)


def _colunas_do_mob(mob) -> dict:
    """As colunas de bin de um mob, do `_USER` dele. `{}` quando não há.

    ⚠️ Container ANINHADO: `mob.attributes` traz `_COLOR_*`, `_GEN`, `_ORG_BIN` e
    `_USER`, e quem lê `mob.attributes` direto conclui, errado, que a bin não tem
    metadado. Medido no banco de NLEs (`metadado-de-canal-do-som-direto`).
    """
    try:
        atributos = getattr(mob, "attributes", None) or {}
        user = atributos.get("_USER") if hasattr(atributos, "get") else None
        return dict(user) if user else {}
    except Exception:  # noqa: BLE001
        return {}


def _de_nome_de_subclipe(nome: str) -> _claquete.Claquete | None:
    """A claquete embutida no NOME do próprio subclipe.

    ⭐ Fecha a ida-e-volta quando a bin de subclipes não carrega os masters
    (`subclipes.autorar(..., base=None)`): não há de onde tirar o nome do WAV para
    perguntar a `claquete.ler()`, mas o nome do subclipe JÁ É a claquete resolvida —
    é só ler de volta o que `nome_de_subclipe` escreveu, sem reinterpretar nada.
    """
    m = _NOME_CANONICO.match(str(nome or "").strip())
    if not m:
        return None
    return _claquete.Claquete(
        cena="C" + m.group("cena"), plano="P" + m.group("plano"),
        take="T" + m.group("take"), convencao="subclipe",
    )


class BinNaoSalva(Exception):
    """A bin tem a sequência sincronizada, mas **nenhum master clip dentro**.

    ⛔⛔ É o estado de uma bin recém-escrita que o Media Composer ainda não SALVOU —
    a que aparece com o asterisco ao lado do nome. Medido em 2026-08-27, comparando a
    bin que o Sincronizar acabara de entregar com a `D02_SYNC.avb` do spike:

        spike : 299 mobs, 50 masters, 198 SourceClips
        recém :   1 mob,   0 masters, 198 SourceClips

    A sequência está inteira e certa; o que falta são os masters, que o Media Composer
    só materializa no `.avb` ao salvar.

    ⚠️⚠️ **Por que isto merece exceção própria, e não um take de nome estranho:** sem
    ela o leitor seguia em frente e entregava os takes com o **UMID cru no lugar do
    nome** (`urn:smpte:umid:060a2b34…`), mais "sem cena" em todos. Nada estava
    quebrado — o leitor era honesto sobre uma bin incompleta —, mas o editor via 50
    linhas ilegíveis e concluía que a função de subclipe tinha quebrado. Foi o que
    aconteceu, e quem descobriu a causa foi ele, salvando a bin à mão.

    ⭐ A mensagem diz **o que fazer**, não o que houve.
    """


class FormaDesconhecida(Exception):
    """A bin não tem nem sequência sincronizada nem subclipe.

    ⚠️ A mensagem diz **o que falta**, e isso é contrato, não cortesia: §5 do spec
    manda que o módulo, não encontrando o que precisa, informe em vez de exigir que
    outra aba tenha sido usada.
    """


def _segmentos(componente, _pos: int = 0) -> list[tuple[int, object]]:
    """`[(posição na track, componente)]` de uma track, em ordem.

    ⚠️ **Não use `percurso.source_clips` aqui.** Ele acha todo `SourceClip` abaixo de
    um componente, mas descarta a POSIÇÃO — e a posição é o que os fillers carregam.
    Sem ela não há como saber que segmento de imagem cruza que janela de som.
    """
    fora: list[tuple[int, object]] = []
    tipo = type(componente).__name__
    if tipo == "Sequence":
        pos = _pos
        for filho in list(getattr(componente, "components", []) or []):
            fora.extend(_segmentos(filho, pos))
            pos += int(getattr(filho, "length", 0) or 0)
        return fora
    if tipo == "SourceClip":
        fora.append((_pos, componente))
    return fora


def _tracks_por_tipo(comp) -> dict[str, list]:
    """As tracks da composição separadas por `media_kind`, na ordem do índice."""
    fora: dict[str, list] = {}
    for track in list(getattr(comp, "tracks", []) or []):
        componente = getattr(track, "component", None)
        if componente is None:
            continue
        kind = str(getattr(componente, "media_kind", "") or "").lower()
        if kind not in ("picture", "sound"):
            continue          # timecode e DescriptiveMetadata não entram
        fora.setdefault(kind, []).append(track)
    for kind in fora:
        fora[kind].sort(key=lambda t: int(getattr(t, "index", 0) or 0))
    return fora


def _tracks_do_mob(mob) -> list:
    """As tracks de um mob. ⚠️ `tracks` é propriedade numas classes do pyavb e MÉTODO
    noutras — iterar sem checar `callable` estoura no meio do percurso."""
    tracks = getattr(mob, "tracks", None)
    if callable(tracks):
        tracks = tracks()
    return list(tracks or [])


def _e_de_camera(mob) -> bool:
    """O master carrega IMAGEM? Então o som que vem dele é som de câmera.

    ⭐⭐ **É o teste estrutural que separa som direto de som de câmera**, e não depende
    de nome, de índice de trilha nem de convenção: o WAV do gravador de campo é um
    master só de som; a câmera é um master com imagem **e** som, porque é o mesmo
    arquivo. Medido em `D02_SYNC.avb` (2026-08-26): 24 masters de som com 5 trilhas de
    som e zero de imagem; 26 de câmera com `picture 1` + `sound 1` + `sound 2`.

    ⚠️⚠️ Sem esta regra, TODO segmento de som virava janela de take — e a bin
    sincronizada põe o som da câmera em trilhas de som. O resultado medido no material
    real foram 26 "takes" que eram clipes de câmera, todos na bin `NAO RESOLVIDO`.

    ⚠️ Master ausente da bin devolve `False`, que é o comportamento anterior a esta
    regra: trocar um defeito visível (take a mais) por um invisível (take a menos)
    seria pior. Quem chama registra o aviso.
    """
    if mob is None:
        return False
    for track in _tracks_do_mob(mob):
        componente = getattr(track, "component", None)
        if str(getattr(componente, "media_kind", "") or "").lower() == "picture":
            return True
    return False


def _sobreposicao_de_imagem(tracks, janela_inicio: int, duracao: int) -> tuple[int, int]:
    """A janela reduzida ao **maior trecho CONTÍNUO** em que imagem e som coexistem.

    ⭐⭐ A regra do autor, dita em 2026-08-26: *"o subclipe só na duração onde vídeo e
    áudio estão presentes; quando qualquer um deles está ausente, aparamos e deixamos
    de fora"*. Vale nas três posições — cabeça, cauda **e meio**.

    ⚠️⚠️ **É por isso que não é a união.** A união mantinha dentro do take um vão sem
    imagem nenhuma: no material real, o `C07_P02_T002` tinha um fragmento de 8 frames,
    22 frames de nada e só então o clipe de verdade. Um subclipe é uma região
    CONTÍNUA — não há como "tirar o meio" dele sem parti-lo em dois. Então o que se
    entrega é o maior pedaço em que as duas mídias estão de fato presentes, e o
    fragmento antes do vão fica de fora, junto com o vão.

    ⚠️ Trechos ENCOSTADOS não são vão: um clipe de câmera que a câmera quebrou em dois
    arquivos (o caso do spanning acima de 4 GB) cobre a região sem buraco, e a região
    continua sendo uma só.

    ⚠️ Empate de comprimento resolve pelo mais CEDO — para que a mesma bin produza
    sempre o mesmo subclipe.

    ⚠️ Sem imagem alguma cruzando a janela, devolve a janela inteira: não há com que
    aparar, e um take de som órfão continua com a duração do som.
    """
    janela_fim = janela_inicio + duracao
    bordas: list[tuple[int, int]] = []
    for track in tracks:
        for posicao, sc in _segmentos(track.component):
            comprimento = int(getattr(sc, "length", 0) or 0)
            ini = max(janela_inicio, posicao)
            fim = min(janela_fim, posicao + comprimento)
            if fim > ini:
                bordas.append((ini, fim))
    if not bordas:
        return janela_inicio, duracao

    # As regiões contínuas: pedaços que se tocam ou se sobrepõem viram uma só.
    bordas.sort()
    regioes: list[list[int]] = [list(bordas[0])]
    for ini, fim in bordas[1:]:
        if ini <= regioes[-1][1]:          # encosta ou invade — mesma região
            regioes[-1][1] = max(regioes[-1][1], fim)
        else:
            regioes.append([ini, fim])

    maior = max(regioes, key=lambda r: r[1] - r[0])
    return maior[0], maior[1] - maior[0]


def takes_da_sequencia(f, comp=None, caminhos: dict | None = None,
                       colunas: dict | None = None) -> list[Tomada]:
    """Os takes de uma timeline sincronizada (a forma `A` do spike).

    Args:
        f: a bin já aberta (use `avb_export.reader.topen`, que tolera o PCMA que
           estoura o pyavb em bins com áudio real).
        comp: a `CompositionMob` da timeline; sem ela, a de mais tracks.
        caminhos: `{nome do master de SOM → caminho do arquivo}`, para avaliar o
           descarte. ⚠️ Ausente, `descartado` fica `None` = **não avaliado**.
        colunas: `{nome do master → {coluna: valor}}` da bin.

    ⭐⭐ **A CENA VEM DA COLUNA, não do nome — decisão do autor, 2026-09-05:**

    > *"O nome e a identidade da cena deve vir da coluna cena dos sons diretos.
    > Tentar resolver pelo nome não é uma boa abordagem, pois tem a variação do
    > técnico de som que coloca a convenção que quiser."*

    ⚠️ Até aqui esta função lia **só** `claquete.ler(nome_do_master)` — e por isso
    ignorava a coluna `Scene` mesmo quando ela estava preenchida. Numa diária real
    do autor (`ORBITA - 24p`), as 52 tomadas saíram sem cena porque o nome
    `25-1T01.WAV` não casa convenção nenhuma; a coluna casaria.

    A precedência (coluna > nome do clipe > nome do master) já morava em
    `media/identidade.py`; o que faltava era esta função consultá-la.
    """
    comp = comp if comp is not None else timeline(f)
    if comp is None:
        return []

    por_id = por_mob_id(f)
    tracks = _tracks_por_tipo(comp)
    caminhos = caminhos or {}
    de_imagem = tracks.get("picture", [])

    def _nome_do_master(mob_id: str) -> str:
        mob = por_id.get(mob_id)
        return str(getattr(mob, "name", "") or "") if e_master(mob) else ""

    # 1) Todo segmento de som, separado por PROCEDÊNCIA. ⚠️⚠️ Esta separação é o
    #    conserto de 2026-08-26: som de câmera NÃO abre janela de take.
    de_som: list[tuple[int, object]] = []
    de_camera: list[tuple[int, object]] = []
    sem_master: set[str] = set()
    for track in tracks.get("sound", []):
        trilha = int(getattr(track, "index", 0) or 0)
        for posicao, sc in _segmentos(track.component):
            mob = por_id.get(str(sc.mob_id))
            if mob is None:
                sem_master.add(str(sc.mob_id))
            destino = de_camera if _e_de_camera(mob) else de_som
            destino.append((posicao, sc, trilha))
    if sem_master:
        log.warning("%d master(s) de som ausentes desta bin — tratados como som "
                    "direto por não haver como classificá-los", len(sem_master))

    # 2) As janelas: um take por (mob de som, posição). Os 5 canais de um WAV são
    #    cortados igual pelo sync, então caem todos na mesma janela.
    janelas: dict[tuple[str, int], list] = {}
    for posicao, sc, trilha in de_som:
        janelas.setdefault((str(sc.mob_id), posicao), []).append((sc, trilha))

    # 3) ⭐ Só o SOM tem claquete. Uma janela cujo master lê como claquete tem cena
    #    resolvida; uma que não lê continua sendo take — só sem cena. ⚠️⚠️ TODA janela
    #    vira Tomada, sempre, sem exceção: uma bin real mistura takes resolvidos e não
    #    resolvidos, e um `or` que só caísse para "todas" no caso all-or-nothing
    #    (rodada 1 de revisão, 2026-08-25) apagava do relatório, calado, exatamente os
    #    takes que o editor mais precisa ver — os que ele vai ter de apontar à mão.
    com_claquete = {chave for chave in janelas
                    if _claquete.ler(_nome_do_master(chave[0])) is not None}
    escolhidas = set(janelas)
    if com_claquete != escolhidas:
        log.info("%d de %d janela(s) de som casaram com convenção conhecida — as "
                 "demais saem como não resolvidas", len(com_claquete), len(janelas))

    achados: list[tuple[int, Tomada]] = []
    # ⭐ O que os takes de fato USARAM da timeline, em frames de imagem. ⚠️ NÃO é a
    # janela bruta do som: quem decide o que sobra é o APARO, e um clipe de câmera pode
    # cruzar a janela e mesmo assim não entrar em take nenhum.
    usado: list[tuple[int, int]] = []
    for (mob_id, posicao) in sorted(escolhidas, key=lambda c: (c[1], c[0])):
        clipes = janelas[(mob_id, posicao)]
        # ⭐ `max`, não `min` nem "o primeiro": defensivo contra um canal cujo sync
        # tenha cortado um frame a menos por arredondamento. Os 5 canais de um WAV
        # sincronizado deveriam sair com o mesmo `length` sempre — se um dia não
        # saírem, o take fica do tamanho do canal mais longo, nunca truncado.
        bruta = max(int(getattr(sc, "length", 0) or 0) for sc, _t in clipes)
        inicio, duracao = _sobreposicao_de_imagem(de_imagem, posicao, bruta)
        recuo = inicio - posicao

        trechos = []
        for sc, trilha in clipes:
            # ⚠️⚠️ Aparar é somar ao `start` DENTRO do master, nunca só encurtar o
            # `length`: encurtar sozinho deixaria o som começando onde começava e o
            # take sairia em sincronia FALSA — sintoma que só o olho do editor pega.
            comprimento = min(int(getattr(sc, "length", 0) or 0) - recuo, duracao)
            if comprimento <= 0:
                continue
            trechos.append(Trecho(
                mob_id=mob_id, track_id=int(getattr(sc, "track_id", 1) or 1),
                media_kind="sound",
                start=int(getattr(sc, "start_time", 0) or 0) + recuo,
                length=comprimento, deslocamento=0, trilha_de_origem=trilha))
        trechos.sort(key=lambda t: t.track_id)
        trechos.extend(_trechos_de_imagem(de_imagem, inicio, duracao))
        # ⚠️⚠️ Registrar o que a IMAGEM deste take cobre na timeline, e não a janela do
        # som. Foi essa distinção que faltava: um clipe de câmera que cruzava a janela
        # bruta deixava de ser órfão mesmo quando o aparo o descartava por inteiro — e
        # aí ele não entrava em take nenhum E não ganhava subclipe. Sumia.
        usado.extend((inicio + t.deslocamento, inicio + t.deslocamento + t.length)
                     for t in trechos if t.media_kind == "picture")

        nome_master = _nome_do_master(mob_id)
        # ⭐ A COLUNA primeiro; o nome só quando ela não responde.
        ident = _identidade.de_clipe(nome_master, nome_master,
                                     (colunas or {}).get(nome_master) or {})
        c = _claquete.ler(nome_master)
        # ⭐ O nome do master de VÍDEO — a base do nome padrão do subclipe.
        # ⚠️ O PRIMEIRO trecho de imagem, na ordem em que a timeline os entrega:
        # num revezamento de duas câmeras, o nome sai da que abre a tomada, que é
        # a que o editor procura na bin.
        nome_video = ""
        for t in trechos:
            if t.media_kind == "picture":
                nome_video = _nome_do_master(t.mob_id)
                if nome_video:
                    break
        achados.append((inicio, Tomada(
            # ⚠️⚠️ `or mob_id`: sem o master na bin, `_nome_do_master` devolve `""` — e
            # o take saía com nome VAZIO, virando um mob sem nome na bin do editor e
            # colapsando o `mapa` do autorar numa entrada só quando faltasse mais de um
            # master. O caso não é hipotético: a própria função registra
            # `sem_master` e loga quando acontece (bin que referencia masters de OUTRA
            # bin). É o mesmo fallback que o caminho do órfão já tinha.
            # ⭐ O nome padrão é o do VÍDEO que compõe a tomada; o som é a
            # exceção, para o subclipe que não tem imagem. Ver `nome_do_video`.
            nome=nome_video or nome_master or mob_id,
            cena=ident.cena,
            plano=ident.plano,
            take=ident.take,
            convencao=ident.convencao,
            episodio=ident.episodio,
            edit_rate=float(getattr(comp, "edit_rate", 0) or 0),
            duracao=duracao,
            duracao_bruta=bruta,
            trechos=tuple(trechos),
            origem="sequencia",
            nome_do_som=nome_master,
            nome_do_video=nome_video,
            descartado=_claquete.e_descartado(caminhos.get(nome_master)),
            orfao=not any(t.media_kind == "picture" for t in trechos),
        )))

    achados.extend(_takes_orfaos_de_imagem(
        de_imagem, de_camera, usado, comp, _nome_do_master, caminhos))
    presumidas = presumir_pela_forma([t for _p, t in achados])
    achados = _batizar_orfaos([(p, t) for (p, _t), t in zip(achados, presumidas)])

    # ⚠️ Ordem de TIMELINE, órfãos incluídos: a bin do editor tem de refletir a
    # diária, não a ordem em que o leitor achou as coisas.
    achados.sort(key=lambda par: (par[0], par[1].nome))
    fora = [take for _pos, take in achados]
    log.info("%d take(s) lidos da sequência %r", len(fora), getattr(comp, "name", ""))
    return fora


def _trechos_de_imagem(tracks, janela_inicio: int, duracao: int) -> list[Trecho]:
    """Os pedaços de câmera que cruzam a janela `[janela_inicio, +duracao)`.

    ⭐ **A conta que importa, e é só soma.** Um segmento de imagem começa em
    `seg_inicio` na timeline e em `sc.start_time` dentro do master. A interseção com a
    janela começa em `max(janela_inicio, seg_inicio)`; o frame correspondente no
    master é `sc.start_time + (interseção_inicio - seg_inicio)`.

    ⚠️ **O trecho NUNCA é empurrado para tapar buraco.** Se a câmera entrou tarde, o
    que se registra é `deslocamento` — e o autor do subclipe o transforma em filler.
    Empurrar dessincronizaria a tomada, e o sintoma (lábio fora do som) só apareceria
    no olho do editor.

    ⚠️⚠️ Desde o aparo de 2026-08-26 a janela já chega aqui reduzida ao maior trecho
    CONTÍNUO com imagem, então dentro dela não há vão nenhum: os segmentos de uma mesma
    trilha se encostam. `deslocamento` sobra para **multicâmera em revezamento** —
    câmeras diferentes cobrindo pedaços diferentes da janela, cada uma na sua trilha.
    """
    janela_fim = janela_inicio + duracao
    fora: list[Trecho] = []
    for track in tracks:
        trilha = int(getattr(track, "index", 0) or 0)
        for posicao, sc in _segmentos(track.component):
            comprimento = int(getattr(sc, "length", 0) or 0)
            inicio = max(janela_inicio, posicao)
            fim = min(janela_fim, posicao + comprimento)
            if fim <= inicio:
                continue          # não cruza esta janela
            fora.append(Trecho(
                mob_id=str(sc.mob_id),
                track_id=int(getattr(sc, "track_id", 1) or 1),
                media_kind="picture",
                start=int(getattr(sc, "start_time", 0) or 0) + (inicio - posicao),
                length=fim - inicio,
                deslocamento=inicio - janela_inicio,
                trilha_de_origem=trilha,
            ))
    return fora


def presumir_pela_forma(tomadas: list[Tomada]) -> list[Tomada]:
    """Separa cena e plano onde a forma da diária autoriza (`identidade.presumir_da_forma`), com a marca de presumida."""
    candidatas = [t.cena for t in tomadas]
    mapa = _identidade.presumir_da_forma(candidatas)
    return [replace(t, cena=mapa[t.cena][0], plano=mapa[t.cena][1], convencao=_identidade.FORMA_DA_DIARIA)
            if t.cena in mapa and t.plano is None and not t.convencao else t for t in tomadas]


def _batizar_orfaos(achados: list[tuple[int, Tomada]]) -> list[tuple[int, Tomada]]:
    """Dá ao órfão o **lugar cronológico** que ele ocupa entre os takes resolvidos.

    ⭐⭐ Regra do autor, 2026-08-26: *"tenho na cena 4 o take 1, take 2, arquivo órfão,
    take 3. O arquivo órfão vai ganhar o subclipe com o nome cena 4 take 2.1"*. Assim o
    clipe **vai para a bin da cena** e **se mantém na ordem cronológica** — e a revisão
    humana acontece onde o editor já está olhando, em vez de numa bin de sobras que ele
    abriria por último ou nunca.

    · órfão **depois** do take `T002` → `T002.1`, `T002.2`, …
    · órfão **antes do primeiro take** → `T000`, e os seguintes `T000.1`, `T000.2`, …
      (*"o primeiro take da diária 2 é um ensaio; podemos chamá-lo de take 0, pois
      cronologicamente vem antes da C4 plano 1 tomada 1"*)

    A âncora é o take resolvido mais próximo **antes** dele; não havendo nenhum, o
    primeiro **depois**. Cena e plano vêm da âncora; só o número do take muda.

    ⚠️⚠️ **Isto é INFERÊNCIA, e o §7 exige que ela se declare.** O nome não veio de
    claquete nenhuma — veio da posição na timeline. Por isso:

    · `convencao` passa a ser **`"posicao"`**, e não o nome de uma convenção de
      claquete: quem ler o relatório vê de onde a cena saiu;
    · `orfao` continua **`True`**, e é ele que o painel usa para marcar a linha;
    · o nome carrega o **ponto decimal**, que nenhuma claquete produz — a própria
      forma do nome diz que aquilo foi presumido.

    ⚠️ Ordena por POSIÇÃO FINAL do take, a de depois do aparo: é a cronologia que o
    editor vai ver na bin, e não a da janela bruta do som.

    ⚠️ **Só órfãos são batizados.** Um take de som cuja claquete não casou convenção
    nenhuma (`NAO RESOLVIDO`) continua sem cena — ali existe uma claquete que alguém
    escreveu, e presumir por cima dela é o que o §11 proíbe.

    ⚠️ Sem take resolvido nenhum na bin não há com que ancorar, e todos ficam como
    estavam — em `ORFAOS`.
    """
    ordenados = sorted(achados, key=lambda par: par[0])
    resolvidos = [(p, t) for p, t in ordenados if t.cena is not None]
    if not resolvidos:
        return achados

    fora: list[tuple[int, Tomada]] = []
    contagem: dict[str, int] = {}
    for posicao, take in ordenados:
        if not (take.orfao and take.cena is None):
            fora.append((posicao, take))
            continue

        anteriores = [t for p, t in resolvidos if p <= posicao]
        if anteriores:
            ancora, base = anteriores[-1], anteriores[-1].take
        else:
            # Nada antes: ancora no primeiro take da diária e vira o "take 0".
            ancora, base = resolvidos[0][1], "T000"

        chave = f"{ancora.cena}_{ancora.plano}_{base}"
        contagem[chave] = contagem.get(chave, 0) + 1
        n = contagem[chave]
        if base == "T000":
            # ⚠️ `T000` não existe como take real, então o primeiro órfão fica com ele
            # inteiro; do segundo em diante entra o sufixo.
            numero = "T000" if n == 1 else f"T000.{n - 1}"
        else:
            numero = f"{base}.{n}"

        c = _claquete.Claquete(cena=ancora.cena, plano=ancora.plano, take=numero,
                               convencao="posicao")
        # ⚠️⚠️ O BATISMO NÃO TOCA MAIS NO NOME — mudou em 2026-09-05, com a regra
        # do autor de que o nome padrão é o do master de VÍDEO. Antes ele escrevia
        # `C04_P01_T000` aqui, e o órfão saía com um nome de convenção enquanto os
        # vizinhos saíam com o nome do arquivo: duas regras de nome na mesma bin.
        #
        # ⭐ O que o batismo dá continua valendo, e é o que importa: cena, plano e
        # take PRESUMIDOS pela posição. Quem quiser o nome de convenção escreve o
        # padrão (`C%cena_P%plano_T%take2`) — e aí ele vale para a bin inteira.
        fora.append((posicao, replace(
            take,
            cena=c.cena, plano=c.plano, take=c.take, convencao=c.convencao, episodio=ancora.episodio,
        )))

    batizados = sum(1 for _p, t in fora if t.convencao == "posicao")
    if batizados:
        log.info("%d órfão(s) receberam lugar por POSIÇÃO na timeline — cena presumida, "
                 "não lida de claquete: %s", batizados,
                 [t.nome for _p, t in fora if t.convencao == "posicao"][:5])
    return fora


def _som_da_propria_camera(de_camera, sc_imagem, inicio: int, fim: int) -> list[Trecho]:
    """Os canais de som DA MESMA câmera que cobrem `[inicio, fim)`.

    ⚠️ O casamento é por `mob_id` e nada mais: pegar "o som que cruza a janela" traria
    o som direto de um take vizinho para dentro de um órfão.
    """
    alvo = str(getattr(sc_imagem, "mob_id", ""))
    fora: list[Trecho] = []
    for posicao, sc, trilha in de_camera:
        if str(getattr(sc, "mob_id", "")) != alvo:
            continue
        comprimento = int(getattr(sc, "length", 0) or 0)
        a = max(inicio, posicao)
        b = min(fim, posicao + comprimento)
        if b <= a:
            continue
        fora.append(Trecho(
            mob_id=alvo, track_id=int(getattr(sc, "track_id", 1) or 1),
            media_kind="sound",
            start=int(getattr(sc, "start_time", 0) or 0) + (a - posicao),
            length=b - a, deslocamento=a - inicio, trilha_de_origem=trilha))
    fora.sort(key=lambda t: t.track_id)
    return fora


def _takes_orfaos_de_imagem(de_imagem, de_camera, usado, comp, nome_do_master,
                            caminhos: dict) -> list[tuple[int, Tomada]]:
    """Um take por clipe de câmera que **nenhum take usou**.

    ⭐ Pedido do autor em 2026-08-26: *"clipes órfãos também são subclipados para poder
    renomear sem mudar o original"*. Um clipe que a sincronização não pareou continua
    sendo material da diária — sumir com ele é o mesmo erro que o §11 proíbe para a
    claquete ilegível: não sobra o que corrigir.

    ⚠️⚠️ **E aqui o som da CÂMERA fica** — é o único que existe. Num take pareado ele
    sai, porque o som direto é melhor e o autor não o quer em dobro; num órfão de
    imagem, tirá-lo entregaria um subclipe mudo de material que tem som.

    ⚠️⚠️ **O critério é USO, não vizinhança** — e essa distinção é o conserto de
    2026-08-26. Antes a pergunta era *"este clipe cruza alguma janela de som?"*, e a
    janela era a **bruta**, de antes do aparo. Um clipe podia cruzá-la e ainda assim
    ser descartado inteiro pelo aparo: não entrava em take nenhum **e** não ganhava
    subclipe de órfão. **Sumia**, sem log e sem rastro.

    No material real era exatamente um item — o fragmento de 8 frames que precede o
    `C07_P02_T002` por 22 frames de vão. Pequeno, mas a inconsistência era de
    princípio: câmera sem sobreposição alguma virava órfão *visível*; câmera cuja
    sobreposição o aparo jogou fora virava *nada*.

    ⭐ Encostar continua não bastando para virar órfão: um clipe que contribui **um
    frame** a um take é material pareado, e sai pareado. O que mudou é que agora isso
    se mede pelo que o take levou, não pelo que ele poderia ter levado.
    """
    fora: list[tuple[int, Tomada]] = []
    for track in de_imagem:
        trilha = int(getattr(track, "index", 0) or 0)
        for posicao, sc in _segmentos(track.component):
            comprimento = int(getattr(sc, "length", 0) or 0)
            fim = posicao + comprimento
            if any(min(fim, b) > max(posicao, a) for a, b in usado):
                continue
            trechos = [Trecho(
                mob_id=str(sc.mob_id),
                track_id=int(getattr(sc, "track_id", 1) or 1),
                media_kind="picture",
                start=int(getattr(sc, "start_time", 0) or 0),
                length=comprimento, deslocamento=0, trilha_de_origem=trilha)]
            trechos.extend(_som_da_propria_camera(de_camera, sc, posicao, fim))
            nome = nome_do_master(str(sc.mob_id))
            # ⚠️ Nome de câmera não é claquete (§11: nunca se inventa) — mas se um dia
            # casar, a cena vem junto e o órfão vai para a bin da CENA, não para
            # `ORFAOS`. Essa regra é do `cenas.agrupar`, não daqui.
            c = _claquete.ler(nome)
            fora.append((posicao, Tomada(
                nome=nome or str(sc.mob_id),
                cena=c.cena if c else None,
                plano=c.plano if c else None,
                take=c.take if c else None,
                convencao=c.convencao if c else None,
                edit_rate=float(getattr(comp, "edit_rate", 0) or 0),
                duracao=comprimento,
                # ⚠️ Um órfão não foi aparado — não havia janela de som com que
                # comparar. Bruta igual à duração, e `aparado` sai zero.
                duracao_bruta=comprimento,
                trechos=tuple(trechos),
                origem="sequencia",
                nome_do_som="",
                descartado=_claquete.e_descartado(caminhos.get(nome)),
                orfao=True,
            )))
    if fora:
        log.info("%d clipe(s) de câmera que nenhum take usou — saem como órfãos: %s",
                 len(fora), [t.nome for _p, t in fora][:5])
    return fora


def _orfao_pela_estrutura(trechos) -> bool:
    """Um subclipe já escrito é órfão? A resposta está na PROCEDÊNCIA das tracks.

    ⭐ `Tomada.orfao` é conhecimento de quem leu a timeline, e um subclipe não guarda
    campo nenhum que o registre. Mas guarda algo melhor: **de que mob cada track veio.**

    · take pareado  — imagem de um master, som de OUTRO. Conjuntos disjuntos.
    · órfão de câmera — imagem e som do MESMO master, porque é o mesmo arquivo.
    · órfão de som   — não há track de imagem nenhuma.

    ⚠️ Vale sem os masters na bin (o modo `base=None`): o `mob_id` está no próprio
    `SourceClip`, não no master. É por isso que a regra é sobre mob_id, e não sobre
    "o master tem imagem" como no lado da sequência.

    ⚠️⚠️ `imagem - som`, e não `imagem & som`: a pergunta é se **TODA** track de imagem
    vem de um mob que também dá som. Com duas câmeras e o som de uma delas — multicam
    com áudio de uma — a interseção diria "órfão" sobre material que a sincronização
    pareou. Medido por mutação em 2026-08-26.

    📌 O ramo `not imagem` é **deliberadamente redundante**: sem imagem, `imagem - som`
    é vazio e a regra geral já devolveria `True`. Fica explícito porque "som sozinho é
    órfão" é uma afirmação do produto, não um efeito colateral de aritmética de
    conjuntos — e mutação nenhuma pode matá-lo (mutante equivalente, registrado).
    """
    imagem = {t.mob_id for t in trechos if t.media_kind == "picture"}
    som = {t.mob_id for t in trechos if t.media_kind == "sound"}
    if not imagem or not som:
        return True
    return not (imagem - som)


def takes_de_subclipes(f, caminhos: dict | None = None,
                       colunas: dict | None = None) -> list[Tomada]:
    """Os takes de uma bin que JÁ contém subclipes — nossos, do AutoSync, ou à mão.

    ⭐ É o que torna a função 5.2 utilizável sozinha. §5 do spec: o que o passo
    seguinte exige não é que o Preparar tenha rodado, é que o **material esteja num
    certo estado**. Quem produziu os subclipes é indiferente.
    """
    caminhos = caminhos or {}
    por_id = por_mob_id(f)
    fora: list[Tomada] = []
    for mob in f.content.mobs:
        if not e_subclipe(mob):
            continue
        nome = str(getattr(mob, "name", "") or "")
        trechos: list[Trecho] = []
        # ⚠️ Vazio quando a bin de subclipes não carrega os masters (o modo `base=None`
        # de `subclipes.autorar`). Aí o descarte fica NÃO AVALIADO, que é a resposta
        # correta — não há de onde tirar o nome do WAV.
        nome_do_som = ""
        for track in list(getattr(mob, "tracks", []) or []):
            componente = getattr(track, "component", None)
            kind = str(getattr(componente, "media_kind", "") or "").lower()
            trilha = int(getattr(track, "index", 0) or 0)
            for posicao, sc in _segmentos(componente):
                trechos.append(Trecho(
                    mob_id=str(sc.mob_id),
                    track_id=int(getattr(sc, "track_id", 1) or 1),
                    media_kind=kind,
                    start=int(getattr(sc, "start_time", 0) or 0),
                    length=int(getattr(sc, "length", 0) or 0),
                    deslocamento=posicao,
                    trilha_de_origem=trilha,
                ))
                if kind == "sound" and not nome_do_som:
                    referido = por_id.get(str(sc.mob_id))
                    if e_master(referido):
                        nome_do_som = str(getattr(referido, "name", "") or "")
        # ⭐⭐ A identidade DEPOIS do laço, porque `nome_do_som` só existe aqui.
        #
        # ⛔ A versão anterior parava no nome do próprio subclipe
        # (`_de_nome_de_subclipe(nome) or _claquete.ler(nome)`) e, quando ele não
        # parseava, entregava os três campos vazios. Medido em 2026-08-29 sobre a
        # `CENAS/C04.avb` do autor: os 16 clipes voltavam com `cena=None`, porque
        # `C04_P06-T003` tem hífen antes do T — enquanto o nome do master,
        # `PROJETO A - 05-04 C4 P6-T003`, resolve inteiro. O nome já estava
        # calculado bem aqui, em `nome_do_som`; faltava usá-lo.
        #
        # ⚠️ E o efeito de não usá-lo era silencioso: `montador._chave_do_take`
        # ordena por cena/plano/take, e com os três vazios a regra do "último take
        # da série" — a regra de escolha do produto — degenera sem erro nenhum.
        # ⭐⭐ As colunas do PRÓPRIO mob, não do dicionário por nome.
        #
        # ⚠️ O dicionário é chaveado por NOME, e desde que o nome padrão passou a
        # ser o do master de vídeo (2026-09-05) dois subclipes da mesma câmera se
        # chamam igual — e um colapsava sobre o outro, herdando a claquete do
        # vizinho em silêncio. O mob está aqui na mão; perguntar a ele é exato.
        #
        # ⭐ E é aqui que a claquete que `subclipes.montar_mob` gravou volta:
        # `Scene`/`Take` no `_USER` do subclipe, as mesmas colunas que o editor vê.
        proprias = _colunas_do_mob(mob) or (colunas or {}).get(nome) or {}
        ident = _identidade.de_clipe(nome, nome_do_som, proprias)
        fora.append(Tomada(
            nome=nome,
            cena=ident.cena,
            plano=ident.plano,
            take=ident.take,
            convencao=ident.convencao,
            edit_rate=float(getattr(mob, "edit_rate", 0) or 0),
            duracao=int(getattr(mob, "length", 0) or 0),
            # ⚠️ Relendo um subclipe não há como saber o que foi aparado ao criá-lo —
            # a janela de som original não está no arquivo. `aparado` sai zero, que é
            # "não sei", e não "nada foi aparado".
            duracao_bruta=int(getattr(mob, "length", 0) or 0),
            trechos=tuple(trechos),
            origem="subclipe",
            nome_do_som=nome_do_som,
            mob_id=str(mob.mob_id),
            descartado=_claquete.e_descartado(caminhos.get(nome_do_som)),
            orfao=_orfao_pela_estrutura(trechos),
        ))
    fora.sort(key=lambda t: t.nome)
    return fora


def takes_de_masters(f, colunas: dict | None = None) -> list[Tomada]:
    """Os takes de uma bin que só tem MASTERCLIPES — a entrada mais crua.

    ⭐ Cada master vira um take cujos trechos são as trilhas dele, inteiras. Não
    há aparo a descobrir, porque não houve sincronização — e é por isso que
    `duracao` e `duracao_bruta` coincidem. Um `duracao_bruta` maior faria o
    painel mostrar *"perdeu N frames de cauda"* sobre material que ninguém aparou.

    ⛔ Sem sincronização não há imagem casada com o som: o take sai com os
    trechos do PRÓPRIO master, e nada mais. Parear câmera com som aqui seria
    refazer, por adivinhação, o trabalho que a sincronização faz medindo.

    ⚠️ `descartado` fica `None` — NÃO AVALIADO, que não é `False` (§7). Sem o
    caminho do arquivo em disco não há como atestar que o take sobreviveu ao
    descarte do técnico de som.
    """
    colunas = colunas or {}
    fora: list[Tomada] = []
    for mob in f.content.mobs:
        if not e_master(mob):
            continue
        nome = str(getattr(mob, "name", "") or "")
        # ⚠️ **Sem nome de master separado, e isto não é omissão.** Aqui o clipe É
        # o master — não há subclipe no meio —, então o degrau do master de
        # `identidade` é inalcançável: o degrau do nome do clipe já viu a mesma
        # string. A primeira versão passava `nome` duas vezes "para deixar a
        # cadeia uniforme", e a mutação mostrou que o segundo argumento era
        # código morto: trocá-lo por `None` não mudava resultado nenhum.
        ident = _identidade.de_clipe(nome, None, colunas.get(nome) or {})
        trechos: list[Trecho] = []
        for track in list(getattr(mob, "tracks", []) or []):
            componente = getattr(track, "component", None)
            kind = str(getattr(componente, "media_kind", "") or "").lower()
            indice = int(getattr(track, "index", 1) or 1)
            trechos.append(Trecho(
                mob_id=str(mob.mob_id),
                track_id=indice,
                media_kind=kind,
                start=0,
                length=int(getattr(componente, "length", 0) or 0),
                deslocamento=0,
                trilha_de_origem=indice))
        duracao = max((t.length for t in trechos), default=0)
        fora.append(Tomada(
            nome=nome, cena=ident.cena, plano=ident.plano, take=ident.take,
            convencao=ident.convencao,
            edit_rate=float(getattr(mob, "edit_rate", 0) or 0),
            duracao=duracao, duracao_bruta=duracao,
            trechos=tuple(trechos), origem="masterclipe",
            nome_do_som=nome, descartado=None, orfao=False,
            mob_id=str(mob.mob_id)))
    fora.sort(key=lambda t: t.nome)
    return fora


def ler(caminho_avb: str, caminhos: dict | None = None,
        colunas: dict | None = None) -> tuple[list[Tomada], str]:
    """`(takes, forma)` a partir de uma `.avb` — **olhando o estado do material**.

    ⭐ A ordem da checagem é uma decisão: subclipe primeiro. Uma bin que já tem
    subclipes está mais adiante no fluxo do que uma que só tem sequência, e refazê-los
    a partir da timeline duplicaria material que o editor já conferiu no checkpoint 1.

    ⚠️ Não encontrando nem um nem outro, **diz o que falta** — nunca "erro".
    """
    from avid.leitura import abrir

    with abrir(str(caminho_avb)) as f:
        de_subclipe = takes_de_subclipes(f, caminhos, colunas)
        if de_subclipe:
            return de_subclipe, "subclipe"
        if timeline(f) is not None:
            # ⛔⛔ A bin tem sequência mas NENHUM master: ela não foi salva.
            #
            # Sem esta checagem o leitor segue e entrega os takes com o UMID cru no
            # lugar do nome — 50 linhas ilegíveis, e o editor concluindo que a função
            # de subclipe quebrou. Ver `BinNaoSalva`.
            #
            # ⚠️ A pergunta é "há master NESTA bin?", não "há master para cada
            # SourceClip": faltar UM master é outro problema (o clipe fora do
            # projeto), e ele já tem tratamento próprio. Zero é o estado do arquivo
            # que o Media Composer ainda não gravou.
            if not any(e_master(m) for m in f.content.mobs):
                raise BinNaoSalva(
                    "esta bin ainda não foi salva no Media Composer — ela está lá "
                    "com um asterisco ao lado do nome. Selecione-a e salve "
                    "(Ctrl+S); só então os clipes de origem entram no arquivo, e é "
                    "deles que saem os nomes dos takes.")
            da_sequencia = takes_da_sequencia(f, caminhos=caminhos, colunas=colunas)
            if da_sequencia:
                return da_sequencia, "sequencia"
        # ⭐⭐ O terceiro degrau, e ele vem POR ÚLTIMO de propósito: uma bin só de
        # masterclipes é a que está mais atrás no fluxo. Preferir subclipe e
        # sequência quando existem é o que evita jogar fora o pareamento
        # som↔câmera que a sincronização produziu — entregando takes sem imagem
        # sobre material que tem imagem.
        #
        # ⚠️ Até 2026-08-29 este estado levantava `FormaDesconhecida`, e a
        # mensagem mandava sincronizar. Deixou de ser erro quando o autor
        # estabeleceu que as etapas do fluxo NÃO são interdependentes: uma lista
        # de masterclipes é entrada legítima, não um estado incompleto.
        de_masters = takes_de_masters(f, colunas)
        if de_masters:
            return de_masters, "masterclipe"
        raise FormaDesconhecida(
            "esta bin não tem sequência sincronizada, nem subclipes por take, nem "
            "masterclipes. Aponte uma bin com clipes dentro — ou salve esta no "
            "Media Composer, se ela estiver com asterisco ao lado do nome."
        )
