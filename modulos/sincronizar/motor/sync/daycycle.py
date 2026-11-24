"""
Sincronizar — o timecode é um CÍRCULO, e a timeline é uma RETA.

O problema, em uma frase: um clipe gravado às 00:01 tem timecode MENOR que o
gravado às 23:57, quatro minutos antes. Toda a cadeia do Órbita tratava o TC como
uma reta desde `00:00:00:00`, então uma captação que atravessa a meia-noite era
cortada ao meio e remontada de trás para a frente — o material pós-meia-noite ia
para o começo da timeline e o pré-meia-noite para 24 h depois dele.

Medido no material real (2026-08-04, `250516_BOLIVIA`, 77 proxies RED): a
sequência entregue tinha **24,31 h**, e acima de 24 h o Premiere bloqueia a
movimentação dos clipes. Ver `sync/model.py::MAX_DAILY_SPAN_TC_HOURS`.

DUAS GRANDEZAS, QUE NUNCA SE FUNDEM
───────────────────────────────────
- **`tc_sec` / `tc_frames`** — a LEITURA CRUA, sempre em 0…24 h. É o que a mídia
  carrega e o que o NLE tem de mostrar como timecode de origem do arquivo. Não
  muda nunca. (Desdobrá-la faria o Premiere exibir `24:01:52:11`, que não existe.)
- **`tc_abs_sec` / `tc_abs_frames`** — `tc_sec + 86400·day_index`. É o eixo em que
  se ORDENA, se PAREIA e se POSICIONA.

QUEM DIZ QUE VIROU: A ORDEM, NÃO A DATA
───────────────────────────────────────
⚠️ Isto contradiz o palpite óbvio, e foi medido. A RED escreve a data no nome do
arquivo (`A002_A034_**0517**QN`), mas ela é a data do RELÓGIO INTERNO da câmera,
que não vira junto com o timecode: no material real, `A033` (TC 23:57) e `A034`
(TC 00:01) têm o MESMO token `0517`. A data serve para separar DIÁRIAS
(ver `sync/dailysplit.py`); para achar a virada, só a ordem de gravação serve.

E a ordem de gravação uma câmera dá de graça: o contador de clipe do nome
(`A001`…`A077`) é monotônico dentro de um cartão. É a `group_order` que o app e o
painel já calculam por ordenação natural.
"""

from __future__ import annotations

#: Um dia de RELÓGIO DE PAREDE, em segundos. É a volta que vale para o som: o
#: `tc_start_sec` de um BWF vem de `TimeReference / sample_rate` — uma contagem de
#: AMOSTRAS desde a meia-noite real —, e amostras não têm nada a ver com frames.
DAY_S = 86400.0


def tc_day_seconds(fps: float) -> float:
    """Uma volta completa do TIMECODE, em segundos REAIS.

    ⚠️ NÃO são 86400 s, e essa é a armadilha de 0,1 % que o `tc_to_real_seconds`
    documenta do outro lado: o timecode conta frames na base NOMINAL (24), mas cada
    frame dura 1/23,976 s. Uma volta inteira são `24·3600·24` frames, que a 23,976
    fps levam **86 486 s** — 86 segundos a mais que um dia de parede.

    Somar 86400 numa virada custou exatamente isso: medido no material real, o
    clipe que atravessa a meia-noite (`A033`) ficou 83 s por cima do seguinte
    (`A034`). Um erro de 86 s numa timeline de sync é 2000 frames — não é
    arredondamento, é o material fora de lugar.
    """
    return max(1, round(fps)) * DAY_S / fps

#: Uma queda de timecode só é VIRADA DE DIA se for grande. Uma queda pequena é um
#: arquivo fora de ordem no nome — e reordenar por TC era justamente o que o motor
#: fazia (e continua fazendo) para consertar isso. 12 h é o ponto onde as duas
#: leituras deixam de competir: nenhuma captação real tem um clipe 12 h anterior ao
#: anterior sem ser um dia novo, e nenhum nome fora de ordem erra por 12 h.
WRAP_MIN_DROP_S = 43200.0

#: Quantas viradas cabem numa diária. UMA — uma captação atravessa a meia-noite uma
#: vez. Duas viradas significam que a entrada tem material de dias diferentes na
#: mesma fonte, e aí quem responde é a separação em diárias, não o desdobramento:
#: desdobrar às cegas produziria uma timeline de 48 h, que é pior que o problema.
MAX_WRAPS = 1

#: Quanto o relógio de parede pode estar longe do timecode e a leitura de DIA ainda
#: valer. Medido no material real: 2404 s (~40 min) em todos os arquivos do gravador
#: — o TC vem de um jam sync e a parede do relógio interno, e eles não coincidem.
#: 6 h dá folga de sobra para essa distância e para um TC ajustado a outro fuso, e
#: ainda fica longe das 12 h em que a resposta viraria cara-ou-coroa.
MAX_WALL_TC_DRIFT_S = 21600.0


def unwrap_along_order(tc_seconds: list[float | None]) -> tuple[list[int], bool]:
    """Desdobra uma sequência de timecodes JÁ NA ORDEM DE GRAVAÇÃO.

    Devolve `(day_index por item, houve_virada)`.

    `None` (arquivo sem TC) não interrompe a contagem nem vira dia: ele herda o dia
    corrente e o próximo TC válido é comparado com o último TC válido. Um buraco na
    leitura não é um buraco no tempo.

    Se passar de `MAX_WRAPS`, DESISTE: devolve tudo em `day_index = 0` e
    `houve_virada = False`. Desdobrar o que não se entende é pior que não desdobrar
    — o resultado seria uma timeline de dois dias, e a rede de segurança de 24 h
    recusaria a diária de qualquer forma, mas sem dizer o porquê certo.
    """
    days = [0] * len(tc_seconds)
    day = 0
    wraps = 0
    prev: float | None = None

    for i, tc in enumerate(tc_seconds):
        if tc is None:
            days[i] = day
            continue
        if prev is not None and tc < prev - WRAP_MIN_DROP_S:
            day += 1
            wraps += 1
            if wraps > MAX_WRAPS:
                return [0] * len(tc_seconds), False
        days[i] = day
        prev = tc

    return days, wraps > 0


def align_to_window(tc_sec: float, lo: float, hi: float) -> int:
    """Em qual DIA este timecode cai, para ficar o mais perto possível de `[lo, hi]`?

    Serve para quem não tem ordem própria nem data: um som direto solto, cujo nome
    não é confiável para ordenar (no material real, `LOCAL-2-005` é o quinto e está
    20 h depois do quarto). A janela `[lo, hi]` é a das câmeras já desdobradas.

    O Δ LIVRE entre dois relógios é problema do `tcmatch`; aqui o Δ é restrito a
    múltiplos de 24 h, e por isso a resposta é única enquanto a janela couber em um
    dia — que é exatamente a invariante que a rede de segurança garante.
    """
    if hi < lo:
        lo, hi = hi, lo
    # O candidato natural: o dia que põe o TC dentro (ou o mais perto possível) da
    # janela. Testa os dois vizinhos porque `round` sozinho erra na borda.
    center = (lo + hi) / 2
    base = round((center - tc_sec) / DAY_S)
    best, best_dist = 0, None
    for k in (base - 1, base, base + 1):
        t = tc_sec + k * DAY_S
        dist = 0.0 if lo <= t <= hi else min(abs(t - lo), abs(t - hi))
        if best_dist is None or dist < best_dist:
            best, best_dist = int(k), dist
    return best


def align_block_to_window(tc_secs: list[float], lo: float, hi: float) -> int:
    """
    Em qual DIA cai este CONJUNTO de arquivos — uma resposta só para todos.

    ## Por que em bloco, e nunca um a um

    `align_to_window` decide por DISTÂNCIA até a janela das câmeras. Quando o
    relógio do gravador está longe do da câmera — e ele pode estar a qualquer
    distância, porque o Δ entre os dois é livre —, essa distância fica quase igual
    para "ficar" e para "voltar um dia", e o desempate vira um fio de navalha que
    passa NO MEIO do conjunto: os arquivos de antes ficam num dia, os de depois
    pulam para o outro.

    Isso não responde "de que dia é este arquivo". Isso PARTE O GRAVADOR AO MEIO, e
    é a única coisa que o material dizia com certeza: um gravador conhece a ordem e
    a distância dos seus próprios arquivos, pelo seu próprio relógio. Medido no
    material real (um gravador 15 h fora do TC das câmeras): 36 WAVs
    partidos em dois blocos a 24 h um do outro, som espalhado por 24h30, 24 câmeras
    sem candidato e o app perguntando se eram duas diárias.

    ## O que se decide aqui, e o que continua livre

    Só a volta INTEIRA de 24 h do conjunto. O Δ livre entre o relógio do gravador e
    o da câmera continua sendo problema do `tcmatch` — e, justamente por ser livre,
    ele ABSORVE a volta que se escolher aqui. Por isso a escolha pode ser a mais
    simples que existe (a que aproxima o conjunto da janela): errar a volta inteira
    não atrapalha o pareamento; partir o conjunto atrapalha.

    Espelha o caminho DATADO, que já move o bloco inteiro de uma vez — ver
    `_unwrap_sounds`.
    """
    if not tc_secs:
        return 0
    if hi < lo:
        lo, hi = hi, lo

    center = (lo + hi) / 2
    meio = sorted(tc_secs)[len(tc_secs) // 2]
    base = round((center - meio) / DAY_S)

    def custo(k: int) -> float:
        total = 0.0
        for tc in tc_secs:
            t = tc + k * DAY_S
            total += 0.0 if lo <= t <= hi else min(abs(t - lo), abs(t - hi))
        return total

    return int(min((base - 1, base, base + 1), key=custo))


def day_from_wall_clock(tc_sec: float, wall_abs_sec: float) -> int | None:
    """Em qual dia este TC cai, dado o RELÓGIO DE PAREDE do mesmo arquivo?

    É a resposta para o som gravado em BWF: o chunk `bext` traz a data e a hora
    reais de gravação (`OriginationDate`/`OriginationTime`) ao lado do timecode
    (`TimeReference`), e as duas são escritas pelo mesmo gravador no mesmo instante.

    ⚠️ A parede NÃO é o timecode. No material real elas estão a ~40 min de distância
    (parede 23:57:02 ↔ TC 23:16:57) porque o TC vem de um jam sync e a parede do
    relógio interno — então a meia-noite do TC e a meia-noite real acontecem em
    momentos DIFERENTES. O que se extrai daqui é só o número de dias inteiros; os
    minutos de diferença são ruído e o `round` os come.

    Devolve `None` quando a diferença que sobra passa de `MAX_WALL_TC_DRIFT_S`: aí a
    resposta é um cara-ou-coroa. O resíduo é sempre ≤ 12 h por construção do `round`,
    e um resíduo PERTO de 12 h é indistinguível do dia vizinho — "offset de +13 h" e
    "offset de −11 h no dia seguinte" produzem a mesma leitura. Admitir que não
    sabemos é melhor que errar o dia por inteiro.
    """
    residual = (wall_abs_sec - tc_sec) - round((wall_abs_sec - tc_sec) / DAY_S) * DAY_S
    if abs(residual) > MAX_WALL_TC_DRIFT_S:
        return None
    return int(round((wall_abs_sec - tc_sec) / DAY_S))
