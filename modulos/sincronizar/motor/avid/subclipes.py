"""Autorar o subclipe do Avid: a operação INVERSA do achatamento que o relink faz.

⭐ Portado do Assist anterior (`assist_anterior/modulos/preparar/subclipes.py`) em
2026-09-05. A única mudança de lógica está em `_mob_id` — ver o aviso lá.

## A estrutura, documentada pelo seu inverso

`motores/delapraca/avb_bin/denest.py` desfaz subclipes e escreve a cadeia inteira:

    timeline:  SourceClip → subclipe (track_id=T, start=S)
    subclipe:  track T    → SourceClip → master (track_id=t, start=s)
    achatado:  SourceClip → master, track_id=t, start = S + s

⭐ Criar é montar isso ao contrário — e o projeto já atravessou essa estrutura em
escala real: **738 repontamentos / 44 subclipes** numa timeline de produção, número
que a rota AAF havia registrado no mesmo material por um caminho independente. Não é
terreno novo.

## O que é um subclipe, em pyavb

Uma `CompositionMob` com `usage_code = 2` (relida, `mob.usage == "subclip"`), cujas
tracks carregam um `SourceClip` apontando ao MASTER com o `track_id`, o `start_time` e
o `length` do recorte.

⚠️ **Um subclipe pode misturar masters.** É a forma que o AutoSync do Avid produz: V
vem da câmera, A vem do som. Um take sincronizado é exatamente isso, e por isso as
tracks deste módulo não têm de vir todas da mesma mob.

## Três armadilhas do pyavb, todas medidas em 2026-08-25

1. ⚠️⚠️ `f.create.Composition("nome", "CompositionMob")` **ignora o argumento `nome`**
   — o `__init__` faz `self.name = mob_type`. Sempre atribuir `.name` depois.
2. ⚠️ `TrackGroup.__init__` usa `edit_rate=25`. Atribuir sempre o do take.
3. ⚠️⚠️ `track_id` sozinho não identifica track (um master de câmera tem
   `picture 1` **e** `sound 1`). Aqui isso vira uma regra de escrita: o `media_kind`
   da `Track` e o do `SourceClip` dentro dela são o mesmo, sempre.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import avb

import registro
from avb.mobid import MobID

log = registro.log(__name__)

# `usage_code` do subclipe. O pyavb traduz para a string 'subclip' na leitura, e é o
# que `avb_bin.percurso.e_subclipe` procura.
USAGE_SUBCLIPE = 2


def _mob_id(bruto) -> MobID:
    """`str` (ou MobID) → `MobID` do pyavb, **reconhecendo as duas formas**.

    ⚠️ Duas representações do mesmo MobID que comparem como strings diferentes são o
    erro clássico desta família. Por isso a conversão acontece num lugar só: aqui.

    ⛔⛔ **E as duas formas exigem construtores DIFERENTES.** Medido em 2026-09-05:

        MobID(str(MobID))              → preserva     ✅  (a forma da BIN, via pyavb)
        MobID("<64 hex bytes_le>")     → DIVERGE      ⛔  (a forma do gRPC/writer)

    O segundo caso é o perigoso: os dois são 64 dígitos hexadecimais, o construtor
    **aceita sem levantar**, e o subclipe sai apontando para um master que não
    existe — abre na bin, tem a cara certa e não tem mídia. Falso-verde perfeito.

    O caminho de hoje (a timeline arrastada) carrega a forma da bin e estaria certo
    com o construtor ingênuo. Reconhecer as duas é o que impede o falso-verde no dia
    em que o `mob_id` chegar do outro lado — `avid/masters.py` devolve `bytes_le.hex()`,
    e ele é a fonte do caminho "subclipar o resultado do sync em memória".
    """
    if isinstance(bruto, MobID):
        return bruto
    texto = str(bruto).strip()
    # A forma do writer/gRPC: 64 hexadecimais puros, sem pontuação nem prefixo.
    #
    # ⚠️ Quem decide se é hex é o próprio `fromhex`, e não uma lista de dígitos
    # escrita à mão: além de ser a mesma regra que o construtor usa depois, um
    # alfabeto hexadecimal literal aqui dispara o detector de segredos do
    # pre-commit (aconteceu, e abortou o commit) — e uma exceção no `.talismanrc`
    # para uma linha que dá para escrever melhor é dívida sem troco.
    if len(texto) == 64:
        try:
            return MobID(bytes_le=bytes.fromhex(texto))
        except ValueError:
            pass
    return MobID(texto)


def agrupar_por_trilha(trechos) -> list[list]:
    """Os trechos repartidos em TRILHAS do subclipe, na ordem em que aparecem.

    ⭐⭐ **Dois pedaços da mesma trilha de origem voltam à mesma trilha**, com o vão
    entre eles virando filler. Uma trilha por trecho apresentaria uma câmera que parou
    e voltou como **duas câmeras** — no material real, um fragmento de 8 frames
    (partida em falso) seguido do clipe de verdade saía como `V1` e `V2`.

    ⚠️ `track_id` NÃO serve para agrupar: os dois pedaços têm o mesmo `track_id` e o
    mesmo `mob_id`. Só a trilha de origem os reconhece como a mesma câmera — e só ela
    separa duas câmeras que por acaso usem o mesmo canal.

    ⚠️⚠️ `trilha_de_origem == 0` é **não informada**, e aí cada trecho ganha trilha
    própria. Não é zelo: `Tomada`s montados à mão (as fixtures da suíte, e qualquer
    chamador que não tenha lido uma timeline) não preenchem o campo — e agrupar por
    zero empilharia os cinco canais de som numa trilha só, sem erro nenhum.
    """
    grupos: list[list] = []
    onde: dict[tuple[str, int], int] = {}
    for trecho in trechos:
        chave = (trecho.media_kind, trecho.trilha_de_origem)
        if trecho.trilha_de_origem and chave in onde:
            grupos[onde[chave]].append(trecho)
            continue
        onde[chave] = len(grupos)
        grupos.append([trecho])
    return grupos


def _componente_da_track(f, take, trechos):
    """O componente de UMA track: `SourceClip` nu, ou `Sequence` com fillers.

    `trechos` são os pedaços de uma trilha de origem só — mais de um quando a câmera
    parou e voltou dentro da janela do take.

    ⭐ **A forma simples é a preferida**, e não por economia: o subclipe do AutoSync
    tem `SourceClip` nu nas tracks, e quanto mais perto disso o nosso ficar, menos
    superfície há para o Media Composer discordar.

    ⚠️ A `Sequence` só entra quando ela é a única resposta honesta: falta material
    em alguma ponta desta trilha, e empurrar o `SourceClip` para tapar o buraco
    dessincronizaria a tomada. Desde o aparo de 2026-08-26 o leitor entrega a janela já
    reduzida ao maior trecho contínuo com imagem, então o que resta é **multicâmera em
    revezamento** — uma câmera cobre parte da janela, outra cobre o resto, e cada
    trilha tem filler onde a outra estava. Medido na `D02_SYNC.avb`: **zero** subclipes
    precisam de filler, contra 24 em 25 antes.
    """
    trechos = sorted(trechos, key=lambda t: t.deslocamento)
    kind = trechos[0].media_kind

    def _clipe(trecho):
        sc = f.create.SourceClip(take.edit_rate, trecho.media_kind)
        sc.mob_id = _mob_id(trecho.mob_id)
        sc.track_id = trecho.track_id
        sc.start_time = trecho.start
        sc.length = trecho.length
        return sc

    def _filler(comprimento):
        fl = f.create.Filler(take.edit_rate, kind)
        fl.length = comprimento
        return fl

    fim = max(t.deslocamento + t.length for t in trechos)
    sobra = take.duracao - fim
    if len(trechos) == 1 and trechos[0].deslocamento <= 0 and sobra <= 0:
        return _clipe(trechos[0]), False

    seq = f.create.Sequence(take.edit_rate, kind)
    # ⚠️ O filler de cabeça entra SEMPRE, ainda que de comprimento zero — é a forma
    # que o Media Composer escreve, e a que já foi aceita por ele nesta bin.
    seq.components = [_filler(max(0, trechos[0].deslocamento))]
    posicao = max(0, trechos[0].deslocamento)
    for trecho in trechos:
        if trecho.deslocamento > posicao:
            seq.components.append(_filler(trecho.deslocamento - posicao))
            posicao = trecho.deslocamento
        seq.components.append(_clipe(trecho))
        posicao += trecho.length
    if sobra > 0:
        seq.components.append(_filler(sobra))
    return seq, True


def montar_mob(f, take):
    """A `CompositionMob` de um take, já acrescentada ao conteúdo de `f`.

    Devolve `(mob, precisou_de_filler)`.
    """
    if not take.trechos:
        raise ValueError(
            f"take {take.nome!r} não tem trecho nenhum — um subclipe sem track é um "
            f"item morto na bin do editor"
        )

    mob = f.create.Composition(take.nome, "CompositionMob")
    # ⚠️ O construtor IGNORA o nome. Sem esta linha a bin sai com clipes homônimos.
    mob.name = take.nome
    mob.usage_code = USAGE_SUBCLIPE
    mob.edit_rate = take.edit_rate
    mob.media_kind_id = 0
    mob.length = take.duracao
    mob.mc_mode = 0
    mob.num_scalars = 0
    mob.param_list = None
    mob.tracks = []

    # ⭐⭐ O SUBCLIPE CARREGA A PRÓPRIA CLAQUETE, nas colunas `Scene`/`Take` do
    # `_USER` — as mesmas que o Media Composer mostra na bin e que
    # `nomear.contexto_da_bin` já sabe ler.
    #
    # ⚠️⚠️ Sem isto, a identidade se perdia na ida-e-volta. Até 2026-09-05 ela
    # sobrevivia por acidente: o nome do subclipe ERA a claquete (`C04_P01_T002`),
    # e a releitura a extraía de volta do nome. Quando o nome padrão passou a ser
    # o do master de VÍDEO (decisão do autor), esse caminho morreu — e uma bin de
    # subclipes relida voltava sem cena nenhuma.
    #
    # ⭐ Guardar no metadado é melhor que depender do nome de qualquer forma: o
    # editor pode renomear o subclipe à vontade sem perder de que tomada ele veio.
    if take.cena or take.take:
        try:
            user = f.create.Attributes()
            if take.cena:
                user["Scene"] = str(take.cena)
            if take.plano:
                # ⚠️ O plano vai junto da cena, como o técnico escreve — a coluna
                # `Scene` do Avid não tem campo separado para ele, e no material
                # real ela traz os dois (`25-6`). Ver `media/identidade.py`.
                user["Scene"] = f"{take.cena} {take.plano}".strip()
            if take.take:
                # ⚠️ Só os dígitos: a coluna `Take` do Avid guarda `003`, não
                # `T003` — é assim que `media/identidade.py` a lê de volta.
                # ⛔ Mas o PONTO fica: o órfão batizado pela posição é `T001.1`, e o
                # ponto é a marca de "presumido". Sem ele a coluna dizia `0011` — um
                # take 11 que não existe (pilotado no Renomear, MC 24.6, 2026-10-21).
                user["Take"] = (re.sub(r"[^\d.]", "", str(take.take)).strip(".")
                                or str(take.take))
            atributos = f.create.Attributes()
            atributos["_USER"] = user
            mob.attributes = atributos
        except Exception as e:  # noqa: BLE001
            # ⚠️ Acabamento, não o trabalho: um subclipe sem metadado ainda é um
            # subclipe válido, e derrubar a bin por causa dele seria trocar a
            # diária por uma coluna.
            log.info("não deu para gravar a claquete no subclipe %s: %s",
                     take.nome, e)

    indice = {"picture": 0, "sound": 0}
    com_filler = False
    for grupo in agrupar_por_trilha(take.trechos):
        componente, usou_filler = _componente_da_track(f, take, grupo)
        com_filler = com_filler or usou_filler
        # ⚠️ O índice da track do SUBCLIPE é sequencial POR TIPO DE MÍDIA, e não o
        # `track_id` do master nem a `trilha_de_origem`. São três coisas diferentes:
        # `track_id` diz de que canal do master o material vem; `trilha_de_origem`
        # diz de que trilha da sequência ele veio; o índice diz em que trilha do
        # subclipe ele aparece.
        kind = grupo[0].media_kind
        indice[kind] = indice.get(kind, 0) + 1
        track = f.create.Track()
        track.index = indice[kind]
        track.component = componente
        track.lock_number = 0
        mob.tracks.append(track)

    f.content.add_mob(mob).user_placed = True
    return mob, com_filler


def autorar(takes, saida: str, base: str | None = None) -> dict:
    """Escreve uma `.avb` com um subclipe por take. Não fala com o Media Composer.

    Args:
        takes: os `Tomada` a materializar.
        saida: o caminho da `.avb` a escrever.
        base: uma `.avb` existente sobre a qual escrever — tipicamente a bin que já
            contém os masters, o que torna o resultado autossuficiente. Com `None`,
            sai só o subclipe e o MC resolve o master por MobID no banco de mídia
            (a mesma escolha que o Órbita faz no modo só-timeline).

    Returns:
        `{"saida", "subclipes", "com_filler", "mapa"}` — `mapa` é
        `{nome do subclipe → str(mob_id)}`, que é a ponte para a Task 5.

    ⭐ Cada chamada gera MobIDs novos. O Media Composer serve mob por MobID a partir
    da SESSÃO, não do arquivo: duas bins com o mesmo MobID no mesmo boot e a primeira
    carregada ganha (medido em `avb_bin/audio.py`).
    """
    # ⚠️⚠️⚠️ GRAVAR SOBRE A PRÓPRIA BASE DESTRÓI A BIN, e a checagem vem antes de
    # tudo por isso. O `topen` do pyavb é PREGUIÇOSO — mantém o handle e resolve objeto
    # por offset, sob demanda. Gravar no MESMO caminho faz o writer ler offsets de um
    # arquivo que ele acabou de truncar.
    #
    # Medido em 2026-08-26, e o resultado é total: a bin foi de **3 922 bytes para
    # 119** e deixou de abrir. O erro que aparece é `unpack requires a buffer of 8
    # bytes` — a mesma assinatura que o banco de NLEs registra para esta armadilha
    # (`protocolos/avb/escrita.md`, § o `topen` é preguiçoso), lá com o preço de
    # "bin corrompida + Media Composer fechando sozinho ao abri-la".
    #
    # ⚠️ Nenhum chamador de hoje faz isso. Mas a saída conhecida para o **D9** é
    # justamente *"passe `base` = a bin que contém os masters"*, e o campo que o painel
    # ganharia para isso deixa o editor a um erro de digitação de perder os masters.
    # Comparar por `resolve()` porque o mesmo arquivo tem muitas grafias: relativa,
    # absoluta, maiúsculas no Windows, barras trocadas.
    if base and Path(saida).resolve() == Path(base).resolve():
        raise ValueError(
            f"a bin de saída e a bin base são o mesmo arquivo ({saida!r}). Gravar "
            f"sobre a base destrói a bin: o leitor do pyavb é preguiçoso e passaria a "
            f"ler offsets de um arquivo já truncado. Escolha outro caminho de saída."
        )

    takes = list(takes)
    if not takes:
        log.info("nenhum take para autorar — nada escrito")
        return {"saida": saida, "subclipes": 0, "com_filler": 0, "mapa": {}}

    Path(saida).parent.mkdir(parents=True, exist_ok=True)

    if base:
        from avid.leitura import abrir
        contexto = abrir(str(base))
    else:
        contexto = avb.open()

    mapa: dict[str, str] = {}
    com_filler = 0
    with contexto as f:
        for take in takes:
            mob, usou = montar_mob(f, take)
            mapa[take.nome] = str(mob.mob_id)
            com_filler += 1 if usou else 0
        # ⚠️ `uid` novo em TODA gravação — regra 1 de `avb_bin/__init__.py`, medida:
        # sem isso o MC recusa a bin com `FILE_OPEN_FAILURE` enquanto houver uma de
        # mesmo uid aberta.
        f.content.uid = random.getrandbits(63)
        f.write(str(saida))

    resultado = {"saida": saida, "subclipes": len(takes), "com_filler": com_filler,
                 "mapa": mapa}
    log.info("subclipes autorados: %d (%d com filler)", len(takes), com_filler)
    return resultado
