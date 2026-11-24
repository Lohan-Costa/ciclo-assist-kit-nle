"""
Sincronizar — em que ordem o material foi gravado, e em quem dá para confiar.

## Por que este módulo existe

A pergunta "qual é a cronologia desta fonte?" era respondida em três lugares, com
três cópias da mesma regra: `engine._tc_usable`, `engine._wall_clock_abs`,
`dailysplit._wall_clock` e `dailysplit._clock_stopped`. Duas delas eram idênticas
byte a byte; as outras duas, a mesma ideia escrita duas vezes. Regra duplicada é
regra que diverge — e esta decide onde cada clipe pousa na timeline.

## O que o app aprendeu sobre relógios (não re-descobrir)

Nenhum metadado temporal é confiável por si. O histórico do projeto, medido em
material real:

* **Timecode** é o melhor — QUANDO ANDA. O drone grava `00:00:00:00` nos 8 arquivos;
  o iPhone, em 102 transcodados. Um "relógio" parado empilha a fonte na origem e
  vira âncora falsa (pôs 140 arquivos numa diária só). Daí `tc_usable`/`clock_stopped`.
* **Nome de arquivo** serve para CÂMERA (o contador de cartão é monotônico) e é
  **ativamente errado para SOM**: o nome de um gravador segue cena e tomada, não o
  relógio — `LOCAL-2-005` foi gravado 20 h depois do `-004`.
* **Relógio de parede do BWF** (`bext`) é "o metadado de data mais confiável do
  ecossistema", e sobrevive a cópia. Mas exige data COMPLETA: a RED escreve `05-17`
  sem ano, e mês/dia sozinho não atravessa a virada do ano.
* **Data de criação do container** (`recorded_at`) foi testada e REJEITADA: o relógio
  interno da Panasonic é não-monotônico, e em material de PROXY o campo traz a data
  do transcode. Não é uma base oferecida aqui, de propósito.

A conclusão que organiza este módulo: **não existe uma base certa para todo mundo.**
Existe a base certa para AQUELA fonte — e dá para medir qual é.
"""

from __future__ import annotations

import re
from datetime import datetime

#: As bases de cronologia que o app oferece. O tipo da fonte filtra quais valem:
#: câmera nunca ordena por `bwf` (não tem), som nunca ordena por `name` (mente).
BASES_CAMERA = ("name", "timecode", "free")
BASES_SOM = ("bwf", "timecode", "free")


def wall_clock_abs(meta: dict) -> float | None:
    """
    O instante REAL de gravação, em segundos desde a época — ou `None`.

    Só de metadado que sobrevive a cópia e a transcode: o chunk `bext` do BWF
    (`bwf_date` + `bwf_time`, escritos pelo gravador) ou uma data COMPLETA no
    caminho (`name_date` + `name_time`).

    ⚠️ Data PARCIAL não serve: a RED escreve `05-17` sem ano, e mês/dia sozinho não
    ordena nada que atravesse a virada do ano. Melhor devolver `None` e cair na
    janela das câmeras do que fingir uma reta do tempo.
    """
    date = meta.get("bwf_date") or meta.get("name_date")
    time = meta.get("bwf_time") or meta.get("name_time")
    if not date or not time or len(str(date)) != 10:
        return None
    try:
        d = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return d.timestamp() if d.tzinfo else (d - datetime(1970, 1, 1)).total_seconds()


def clock_stopped(tc_secs: list[float | None]) -> bool:
    """
    O relógio desta fonte está PARADO?

    Com mais de um arquivo, um único valor de TC é relógio parado — o caso do drone
    e do iPhone descritos no cabeçalho. É a pergunta mínima, e a que pega o desastre.
    """
    distintos = {t for t in tc_secs if t is not None}
    return len(tc_secs) > 1 and len(distintos) <= 1


#: Folga, em frames, para dizer que o TC de um clipe começa onde o anterior acabou.
#: Dois frames absorvem o arredondamento de duração (ms → frames) sem deixar passar
#: um intervalo real: a menor pausa de operador entre duas tomadas é de segundos.
_REC_RUN_TOL_FRAMES = 2


def rec_run(tc_frames: list[int | None], duration_frames: list[int | None]) -> bool:
    """
    Este timecode é **REC-RUN** — só anda enquanto a câmera grava?

    ## O que isso significa, e por que é diferente de "o relógio anda"

    Um TC *free-run* marca a HORA: o intervalo entre dois clipes é o tempo real que
    passou entre eles, pausa do operador incluída. Um TC *rec-run* marca o METRO DE
    FITA: cada clipe começa exatamente onde o anterior terminou, e o tempo em que a
    câmera esteve parada **simplesmente não é registrado**.

    Os dois passam em `tc_usable` — todo clipe tem TC, e os TCs são distintos e
    monotônicos. A diferença só aparece quando se pergunta uma DISTÂNCIA.

    ## Por que o motor precisa saber (medido no material MULTCAM)

    `_travar_cronologia` trava os clipes de uma câmera confiável numa corrente, com
    as distâncias que o relógio manda. Num rec-run isso COLA todas as tomadas umas
    nas outras e destrói as posições que a forma de onda já tinha acertado: numa
    Panasonic real, os dez intervalos de TC batiam com a duração do clipe anterior
    ao frame, e travar a corrente embaralhou a câmera inteira (11 clipes fora de
    ordem, 10 sinalizados) onde antes havia ordem perfeita e nenhum aviso.

    ## O que continua valendo num rec-run

    A ORDEM. Um TC rec-run é monotônico e ordena a câmera corretamente — ele só não
    sabe as distâncias. Por isso esta função não derruba a base `timecode`; ela é
    consultada por quem precisa medir espaço entre clipes.
    """
    pares = [
        (tc_frames[i], tc_frames[i + 1], duration_frames[i])
        for i in range(len(tc_frames) - 1)
    ]
    pares = [(a, b, d) for a, b, d in pares
             if a is not None and b is not None and d]
    # Um par só é coincidência: duas tomadas seguidas sem pausa acontecem. A
    # afirmação "esta câmera é rec-run" precisa do padrão, não de um caso.
    if len(pares) < 2:
        return False
    return all(abs((b - a) - d) <= _REC_RUN_TOL_FRAMES for a, b, d in pares)


def _natural_key(nome: str):
    """
    Ordena nomes tratando corridas de dígitos como número (`PANA2` < `PANA10`).

    Compara sempre `(0, número)` ou `(1, texto)` para nunca cruzar `int` com `str` —
    as duas cópias antigas desta função levantavam `TypeError` quando dois nomes
    tinham estrutura diferente (`A001.mov` vs `001A.mov`).
    """
    partes = re.split(r"(\d+)", nome)
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in partes]


def _monotonico(valores: list[float | None]) -> bool:
    """A sequência só avança? (`None` em qualquer posição = não dá para dizer.)"""
    if not valores or any(v is None for v in valores):
        return False
    return all(a <= b for a, b in zip(valores, valores[1:]))


def evaluate(kind: str, arquivos: list[dict]) -> dict:
    """
    Em qual base de cronologia dá para confiar NESTA fonte?

    `arquivos` é uma lista de `{"nome", "tc_sec", "tc_frames", "meta"}` na ordem em
    que o usuário montou a fonte. Devolve a base proposta e, para cada uma, se
    serve e **por quê** — o "por quê" é o que a interface mostra, porque uma
    recomendação sem motivo é um palpite com cara de autoridade.

    ⚠️ SÓ METADADO. Nada aqui lê áudio: é para poder rodar assim que a árvore de
    mídia termina de indexar, sem custo perceptível.
    """
    e_som = kind == "sound"
    nomes = [a["nome"] for a in arquivos]
    tc_secs = [a.get("tc_sec") for a in arquivos]
    tc_frames = [a.get("tc_frames") for a in arquivos]
    paredes = [wall_clock_abs(a.get("meta") or {}) for a in arquivos]

    opcoes: list[dict] = []

    # ── timecode ─────────────────────────────────────────────────────────────
    if not arquivos:
        tc_ok, tc_por, tc_detalhe = False, "sem_arquivos", ""
    elif any(t is None for t in tc_secs):
        faltam = sum(1 for t in tc_secs if t is None)
        tc_ok, tc_por = False, "sem_tc"
        tc_detalhe = f"{faltam} de {len(arquivos)} sem timecode"
    elif clock_stopped(tc_secs):
        tc_ok, tc_por = False, "relogio_parado"
        tc_detalhe = "todos os arquivos com o mesmo timecode"
    else:
        tc_ok = tc_usable(tc_secs, tc_frames)
        tc_por = None if tc_ok else "timecodes_repetidos"
        tc_detalhe = "o relógio anda" if tc_ok else "timecodes repetidos"
    opcoes.append({"basis": "timecode", "ok": tc_ok, "why": tc_por,
                   "detail": tc_detalhe})

    # ── nome do arquivo (só CÂMERA — para som o nome é a cena, não o relógio) ──
    if not e_som:
        distintos = len(set(nomes)) == len(nomes)
        tem_numero = all(any(ch.isdigit() for ch in n) for n in nomes)
        nome_ok = bool(nomes) and distintos and tem_numero
        por_nome = sorted(nomes, key=_natural_key)
        detalhe = ""
        if nome_ok and tc_ok:
            # O sinal mais útil da tela: as duas autoridades concordam?
            por_tc = [n for _, n in sorted(zip(tc_secs, nomes))]
            detalhe = ("concorda com o timecode" if por_nome == por_tc
                       else "DISCORDA do timecode")
        opcoes.append({
            "basis": "name", "ok": nome_ok,
            "why": None if nome_ok else ("nomes_repetidos" if not distintos else "sem_numeracao"),
            "detail": detalhe,
        })

    # ── relógio de parede do BWF (só SOM) ────────────────────────────────────
    if e_som:
        faltam = sum(1 for p in paredes if p is None)
        bwf_ok = bool(paredes) and faltam == 0
        opcoes.append({
            "basis": "bwf", "ok": bwf_ok,
            "why": None if bwf_ok else ("data_parcial" if faltam < len(paredes) else "sem_bwf"),
            "detail": ("em ordem" if bwf_ok and _monotonico(paredes)
                       else f"{faltam} sem data completa" if faltam else "fora de ordem"),
        })

    opcoes.append({"basis": "free", "ok": True, "why": None,
                   "detail": "sem ordem assumida"})

    return {"proposed": _melhor(opcoes, e_som), "options": opcoes}


def _melhor(opcoes: list[dict], e_som: bool) -> str:
    """
    A base proposta: a primeira da preferência que SERVE.

    Câmera: `timecode` > `name`. O relógio, quando anda, sabe as horas — o nome só
    sabe a ordem. Som: `bwf` > `timecode`; o `bext` é o metadado de data mais
    confiável do ecossistema, e muitos gravadores não escrevem TC nenhum.
    `free` é o último recurso, nunca uma proposta.
    """
    prefere = ("bwf", "timecode") if e_som else ("timecode", "name")
    servem = {o["basis"] for o in opcoes if o["ok"]}
    for base in prefere:
        if base in servem:
            return base
    return "free"


def propose(kind: str, arquivos: list[dict]) -> str:
    """A base que o motor usa quando o usuário não escolheu. Mesma função da tela —
    é o que impede a interface de propor uma coisa e o motor fazer outra."""
    return evaluate(kind, arquivos)["proposed"]


def tc_usable(tc_secs: list[float | None], tc_frames: list[int | None]) -> bool:
    """
    O timecode desta fonte serve como RELÓGIO DO DIA?

    Duas exigências, e as duas são o mínimo indispensável: **todo** clipe tem TC, e
    os TCs são **distintos**. Uma fonte que falhe aqui ainda sincroniza pela forma de
    onda — o que ela não pode é fingir que sabe as horas.
    """
    if not tc_secs or any(t is None for t in tc_secs):
        return False
    return len(set(tc_frames)) == len(tc_frames)
