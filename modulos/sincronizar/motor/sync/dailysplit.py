"""
Sincronizar — quantas DIÁRIAS há nesta pasta?

Uma pasta que o editor recebe raramente é uma diária. A do material real
(`250516_BOLIVIA`) tem três: dois clipes da noite anterior, a captação principal
que atravessa a meia-noite, e dois sons gravados na noite SEGUINTE, 20 h depois.
Sincronizadas juntas, elas ocupam 26 h de timeline — e acima de 24 h o Premiere
trava a movimentação dos clipes (ver `model.MAX_DAILY_SPAN_TC_HOURS`).

⭐ QUEM SEPARA É O BURACO, NÃO A DATA
─────────────────────────────────────
Isto foi medido, e contradiz o palpite óbvio. No material real, `SP3-TORE-001.WAV`
tem `OriginationDate 2025-05-16` e está cercado, no tempo, por clipes RED chamados
`0517` — porque o gravador e a câmera viram a data em momentos diferentes.
Agrupar por data colocaria o som e a câmera do MESMO instante em diárias
diferentes: exatamente o bug que este módulo existe para evitar, entrando pela
porta dos fundos.

Então: **corta onde há um vão de horas no eixo do tempo. A data só CORROBORA o
corte e dá o NOME à diária.**

O QUE ESTE MÓDULO NÃO DECIDE
────────────────────────────
Ele PROPÕE. Quem confirma é o usuário, nos dois clientes — e é isso que torna
aceitável ele arriscar um palpite: um palpite legível e reversível vale mais que
uma recusa. Ver `main.py::plan_dailies`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from media.inspector import probe
from media.nameconv import parse_folder_date
from sync import chronology
from sync.daycycle import DAY_S, align_to_window, day_from_wall_clock, unwrap_along_order
from sync.model import MAX_DAILY_SPAN_TC_HOURS

#: O vão que separa duas diárias, em segundos. Seis horas.
#:
#: Grande o bastante para nunca cortar num almoço, numa troca de locação ou numa
#: pausa de madrugada; pequeno o bastante para pegar os vãos do material real
#: (21,9 h e 20,2 h). Entre 6 h e 20 h não há nada neste dataset — a escolha tem
#: muita folga dos dois lados, e não é um número de borda.
DAILY_GAP_S = 6 * 3600.0


@dataclass
class _Item:
    """Um arquivo, com o que se sabe sobre QUANDO ele foi gravado."""
    entry: dict                     # o dict original, devolvido intacto ao `sync`
    path: str
    kind: str                       # "camera" | "sound"
    source: str                     # group_id — a fonte que o usuário declarou
    order: int | None
    tc_sec: float | None
    duration_s: float
    date: str | None                # "AAAA-MM-DD" | "MM-DD" | None
    wall_abs: float | None          # instante real, quando o arquivo o carrega
    day: int = 0                    # voltas de 24 h, preenchido no desdobramento

    @property
    def axis(self) -> float | None:
        """Onde o arquivo cai no eixo comum. `None` = sem relógio."""
        if self.tc_sec is None:
            return None
        return self.tc_sec + self.day * DAY_S


@dataclass
class _Block:
    """Um trecho contíguo de UMA fonte — o que vira (parte de) uma diária."""
    source: str
    kind: str
    name: str
    items: list[_Item] = field(default_factory=list)

    # ⚠️ `None` quando NENHUM arquivo do bloco tem relógio — e isso é comum: uma
    # handcam AVCHD não expõe timecode nenhum, e um iPhone transcodado marca
    # 00:00:00:00. Um bloco assim não tem posição no eixo, e perguntar onde ele
    # começa é uma pergunta sem resposta. Devolver `None` obriga quem chama a
    # tratar o caso; um `min()` sobre lista vazia levantava e derrubava a análise
    # inteira da pasta (medido: 217 arquivos, 5 fontes, duas delas sem TC).
    @property
    def start(self) -> float | None:
        pos = [i.axis for i in self.items if i.axis is not None]
        return min(pos) if pos else None

    @property
    def end(self) -> float | None:
        pos = [i.axis + i.duration_s for i in self.items if i.axis is not None]
        return max(pos) if pos else None


def _wall_clock(meta: dict) -> float | None:
    """O instante real de gravação. Ver `chronology.wall_clock_abs`."""
    return chronology.wall_clock_abs(meta)


def _read(entries: list[dict]) -> list[_Item]:
    """Lê os metadados de tudo. Usa o cache — a mesma leitura serve ao `sync`."""
    items = []
    for e in entries:
        path = e["path"] if isinstance(e, dict) else e
        entry = e if isinstance(e, dict) else {"path": path}
        meta = probe(path)
        # Mesma regra do motor: TEM FPS → CÂMERA, e `kind:"sound"` do usuário manda.
        is_cam = bool(meta.get("fps")) and entry.get("kind") != "sound"
        items.append(_Item(
            entry=entry,
            path=path,
            kind="camera" if is_cam else "sound",
            source=str(entry.get("group_id") or path),
            order=entry.get("group_order"),
            tc_sec=_tc_seconds(meta),
            duration_s=(meta.get("duration_ms") or 0.0) / 1000,
            date=meta.get("bwf_date") or meta.get("name_date"),
            wall_abs=_wall_clock(meta),
        ))
    return items


def _tc_seconds(meta: dict) -> float | None:
    """O TC do arquivo em segundos, seja ele de vídeo (tmcd) ou de som (bext)."""
    if meta.get("tc_start_sec") is not None:
        return float(meta["tc_start_sec"])
    from sync.tcmatch import tc_to_real_seconds
    return tc_to_real_seconds(
        meta.get("tc_start") or "", meta.get("fps") or 24.0,
        bool(meta.get("tc_drop_frame")),
    )


def _clock_stopped(items: list[_Item]) -> bool:
    """O relógio desta fonte está parado? Ver `chronology.clock_stopped` — foi o
    iPhone com 102 arquivos a `00:00:00:00` que pôs 140 numa diária só."""
    return chronology.clock_stopped([i.tc_sec for i in items])


def _unwrap_source(items: list[_Item]) -> None:
    """Desdobra o timecode DENTRO de uma fonte.

    Câmera: pela ORDEM de gravação (o contador de clipe do cartão), que é a única
    coisa monotônica que existe — a data do nome NÃO vira junto com o timecode.

    Som: pelo relógio de parede do próprio arquivo, que dá os dias relativos com
    precisão. Um gravador nomeia por cena e tomada, não por hora: no material real
    o quinto arquivo foi gravado 20 h depois do quarto.
    """
    datados = [i for i in items if i.wall_abs is not None and i.tc_sec is not None]
    if datados:
        dias = {}
        for i in datados:
            k = day_from_wall_clock(i.tc_sec, i.wall_abs)
            if k is not None:
                dias[id(i)] = k
        if dias:
            base = min(dias.values())
            for i in datados:
                if id(i) in dias:
                    i.day = dias[id(i)] - base
            return

    ordenados = sorted(
        items,
        key=lambda i: (i.order if i.order is not None else 0, _natural(i.path)),
    )
    dias, _ = unwrap_along_order([i.tc_sec for i in ordenados])
    for i, d in zip(ordenados, dias):
        i.day = d


def _natural(path: str):
    import re
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", Path(path).name)]


def _cut_into_blocks(items: list[_Item], source: str, kind: str, name: str) -> list[_Block]:
    """Corta uma fonte onde ela tem um VÃO de horas.

    Uma fonte SEM relógio nunca é cortada: sem eixo não há vão que se possa medir,
    e partir um cartão sem evidência é pior que deixá-lo inteiro.
    """
    com_tc = sorted((i for i in items if i.axis is not None), key=lambda i: i.axis)
    sem_tc = [i for i in items if i.axis is None]

    if not com_tc:
        return [_Block(source, kind, name, list(items))]

    blocos: list[_Block] = [_Block(source, kind, name, [com_tc[0]])]
    for anterior, atual in zip(com_tc, com_tc[1:]):
        if atual.axis - (anterior.axis + anterior.duration_s) > DAILY_GAP_S:
            blocos.append(_Block(source, kind, name, []))
        blocos[-1].items.append(atual)

    # Quem não tem relógio acompanha o MAIOR bloco da própria fonte: é o palpite
    # menos arriscado, e o usuário confirma.
    if sem_tc:
        max(blocos, key=lambda b: len(b.items)).items.extend(sem_tc)
    return blocos


def _align_sources(blocos: list[_Block], avisos: list[str]) -> None:
    """Encaixa as fontes umas nas outras, em voltas INTEIRAS de 24 h.

    Cada fonte desdobrou o próprio timecode a partir do SEU primeiro arquivo, então
    o "dia 0" de cada uma é arbitrário. O que se ajusta aqui é só isso — nunca o
    deslocamento livre entre dois relógios, que é medição do `tcmatch` e não desta
    conta.

    ⚠️ O LIMITE HONESTO DESTE PASSO: o timecode de uma câmera contra o de OUTRA não
    vale nada (medido no material antigo: 22 h de distância entre duas câmeras da
    mesma diária). Encaixar por proximidade acerta quando os aparelhos compartilham
    o relógio — que é o caso comum, e é o do material real — e erra quando não. Por
    isso o resultado é uma PROPOSTA que o usuário confirma, e por isso um encaixe
    que precisou de deslocamento entra no registro.
    """
    # Só quem TEM eixo participa: uma fonte sem relógio nenhum não pode ser
    # encaixada em lugar nenhum, e tentar levantava.
    com_eixo = [b for b in blocos if b.start is not None]
    if len(com_eixo) < 2:
        return
    referencia = max(com_eixo, key=lambda b: len(b.items))
    lo, hi = referencia.start, referencia.end

    por_fonte: dict[str, list[_Block]] = {}
    for b in com_eixo:
        por_fonte.setdefault(b.source, []).append(b)

    for fonte, bs in por_fonte.items():
        if fonte == referencia.source:
            continue
        inicio = min(b.start for b in bs)
        desloca = align_to_window(inicio, lo, hi)
        if not desloca:
            continue
        for b in bs:
            for i in b.items:
                i.day += desloca
        avisos.append(
            f'"{bs[0].name}" foi encaixada {desloca:+d} dia(s) para caber na mesma '
            f"captação — confira se é isso mesmo."
        )


def _agglomerate(blocos: list[_Block]) -> list[list[_Block]]:
    """Junta os blocos de fontes DIFERENTES que se tocam no tempo.

    É aqui que a câmera e o som da mesma noite voltam a ser uma diária só — e é
    aqui que a data NÃO manda: eles podem carregar tokens de data diferentes (o
    gravador vira à meia-noite real, a câmera vira no relógio interno dela) e ainda
    assim ser o mesmo trabalho.
    """
    com_eixo = sorted((b for b in blocos if _tem_eixo(b)), key=lambda b: b.start)
    sem_eixo = [b for b in blocos if not _tem_eixo(b)]
    if not com_eixo:
        return [sem_eixo] if sem_eixo else []

    grupos: list[list[_Block]] = [[com_eixo[0]]]
    fim = com_eixo[0].end
    for b in com_eixo[1:]:
        if b.start - fim > DAILY_GAP_S:
            grupos.append([])
            fim = b.end
        else:
            fim = max(fim, b.end)
        grupos[-1].append(b)

    # Fonte sem relógio nenhum acompanha a maior diária — e o registro avisa.
    if sem_eixo:
        max(grupos, key=lambda g: sum(len(b.items) for b in g)).extend(sem_eixo)
    return grupos


def _tem_eixo(b: _Block) -> bool:
    return any(i.axis is not None for i in b.items)


def _hhmm(axis_seconds: float) -> str:
    """A hora do dia que aquela posição do eixo representa, `HH:MM`.

    É o timecode, não o relógio de parede — os dois estão a ~40 min de distância no
    material real. Mas é o que o editor vê na régua da sequência, e é por ele que
    ele reconhece a captação.
    """
    s = int(axis_seconds % DAY_S)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}"


def _nome(grupo: list[_Block], indice: int) -> tuple[str, str | None]:
    """O nome da diária, e a data que o justifica.

    A data VEM dos arquivos e serve para NOMEAR — nunca para cortar. Sem data, a
    pasta que uma pessoa nomeou (`250516_BOLIVIA`) é a segunda melhor pista; sem
    ela, um número de ordem, que ao menos é honesto sobre não saber.
    """
    datas = [i.date for b in grupo for i in b.items if i.date and len(i.date) == 10]
    if datas:
        d = min(datas)
        return d, d
    pasta = next(
        (parse_folder_date(i.path) for b in grupo for i in b.items
         if parse_folder_date(i.path)),
        None,
    )
    if pasta:
        return pasta, pasta
    return f"Diária {indice + 1}", None


def plan_dailies(entries: list[dict]) -> dict:
    """Quantas diárias há nesta lista de arquivos, e quais.

    Devolve `{"dailies": [...], "warnings": [...]}`, onde cada diária já traz
    `files` no formato que o comando `sync` espera em `groups[].files` — a resposta
    confirmada volta sem tradução nenhuma.
    """
    avisos: list[str] = []
    items = _read(entries)
    if not items:
        return {"dailies": [], "warnings": ["nenhum arquivo para analisar"]}

    por_fonte: dict[str, list[_Item]] = {}
    for i in items:
        por_fonte.setdefault(i.source, []).append(i)

    blocos: list[_Block] = []
    for fonte, do_grupo in por_fonte.items():
        # Relógio parado é o mesmo que relógio nenhum: a fonte inteira sai do eixo,
        # e passa a acompanhar a diária onde o resto do material caiu.
        if _clock_stopped(do_grupo):
            for i in do_grupo:
                i.tc_sec = None
        _unwrap_source(do_grupo)
        nome = _nome_da_fonte(do_grupo, fonte)
        blocos.extend(_cut_into_blocks(do_grupo, fonte, do_grupo[0].kind, nome))

    _align_sources(blocos, avisos)
    grupos = _agglomerate(blocos)

    dailies = []
    nomes_usados: dict[str, int] = {}
    for n, grupo in enumerate(grupos):
        nome, data = _nome(grupo, n)
        com_eixo = [b for b in grupo if _tem_eixo(b)]
        span = (max(b.end for b in com_eixo) - min(b.start for b in com_eixo)
                if com_eixo else 0.0)
        inicio = min(b.start for b in com_eixo) if com_eixo else None

        # DUAS DIÁRIAS NO MESMO DIA DE CALENDÁRIO É COISA QUE ACONTECE — no material
        # real, uma capta às 00:39 e outra às 23:06 do mesmo 16 de maio, 22 h
        # depois. O nome tem de distingui-las, e a hora de início é o que distingue.
        if nome in nomes_usados and inicio is not None:
            nome = f"{nome} ({_hhmm(inicio)})"
        nomes_usados[nome] = nomes_usados.get(nome, 0) + 1
        if span > MAX_DAILY_SPAN_TC_HOURS * 3600:
            avisos.append(
                f'"{nome}" ainda ocupa {span / 3600:.1f} h — acima do limite de '
                f"{MAX_DAILY_SPAN_TC_HOURS:.0f} h. Tire o material que não é deste dia."
            )
        fontes = []
        for b in grupo:
            fontes.append({
                "group_id": b.source,
                "name": b.name,
                "kind": b.kind,
                "files": [i.path for i in b.items],
            })
        dailies.append({
            "id": f"daily_{n}",
            "name": nome,
            "date": data,
            "start_tc": _hhmm(inicio) if inicio is not None else None,
            "span_seconds": round(span, 1),
            "file_count": sum(len(b.items) for b in grupo),
            "sources": fontes,
            # Pronto para virar `groups[].files` do comando `sync`.
            "files": [i.entry for b in grupo for i in b.items],
        })

    if len(dailies) > 1:
        avisos.insert(0, f"o material foi separado em {len(dailies)} diárias.")
    return {"dailies": dailies, "warnings": avisos}


def _nome_da_fonte(items: list[_Item], fonte: str) -> str:
    """O nome que o usuário deu à fonte — ou o da pasta, como no motor."""
    nomes = [i.entry.get("source_name") for i in items if i.entry.get("source_name")]
    if nomes:
        return str(nomes[0])
    return Path(fonte).name or fonte
