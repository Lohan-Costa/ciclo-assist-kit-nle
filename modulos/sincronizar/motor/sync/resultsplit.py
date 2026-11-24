"""
Sincronizar — partir uma diária JÁ SINCRONIZADA em várias.

⭐ POR QUE DEPOIS DO SYNC, E NÃO ANTES
──────────────────────────────────────
Havia um módulo que dividia ANTES (`sync/dailysplit.py`), olhando só metadado:
timecode, data, vãos. Ele erra por construção, e o erro apareceu no material
real — o som que pertencia à câmera RED foi parar numa diária e a câmera na
outra.

A razão é simples: **antes do sync, o programa não sabe qual som casa com qual
câmera.** Quem descobre isso é a correlação de forma de onda. Cortar antes é
cortar às cegas, e um corte no lugar errado destrói um par que a medição teria
encontrado.

Depois do sync a pergunta é fácil, porque a TOMADA já existe como unidade: um som
e as câmeras que a filmaram, com os offsets medidos. O corte só pode acontecer
ENTRE tomadas — nunca dentro de uma —, e por isso não há como perder um par.

A UNIDADE É ATÔMICA
───────────────────
São três, e nenhuma se parte:
  • uma TOMADA (o som + as câmeras dele);
  • uma câmera ÓRFÃ (rodou sem som — plano MOS, B-roll);
  • um som ÓRFÃO (o gravador rodou sem câmera).

Cada uma ocupa um intervalo na timeline. Ordena-se por início e corta-se onde há
um vão maior que `DAILY_GAP_S`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from sync.model import Daily, MAX_DAILY_SPAN_TC_HOURS

#: O vão que separa duas diárias, em segundos. Seis horas.
#:
#: Grande o bastante para nunca cortar num almoço, numa troca de locação ou numa
#: pausa de madrugada; pequeno o bastante para pegar os vãos do material real
#: (21,9 h e 20,2 h). Entre 6 h e 20 h não há nada naquele dataset — a escolha tem
#: muita folga dos dois lados, e não é um número de borda.
DAILY_GAP_S = 6 * 3600.0


@dataclass
class _Unit:
    """Uma unidade indivisível da timeline. Ver o cabeçalho do módulo."""
    start: int                       # frames
    end: int                         # frames
    paths: list[str] = field(default_factory=list)
    label: str = ""


def _units(daily: Daily) -> list[_Unit]:
    def snd_end(s) -> int:
        return s.timeline_start_frames + ceil(s.duration_ms / 1000 * daily.fps)

    unidades: list[_Unit] = []
    for take in daily.takes:
        inicio = min([take.sound.timeline_start_frames]
                     + [c.timeline_start_frames for c in take.cameras])
        fim = max([snd_end(take.sound)]
                  + [c.timeline_start_frames + c.duration_frames for c in take.cameras])
        unidades.append(_Unit(
            inicio, fim,
            [str(take.sound.path)] + [str(c.path) for c in take.cameras],
            take.name,
        ))
    for cam in daily.orphan_cameras:
        unidades.append(_Unit(
            cam.timeline_start_frames,
            cam.timeline_start_frames + cam.duration_frames,
            [str(cam.path)], cam.path.stem,
        ))
    for snd in daily.orphan_sounds:
        unidades.append(_Unit(
            snd.timeline_start_frames, snd_end(snd), [str(snd.path)], snd.path.stem,
        ))
    return sorted(unidades, key=lambda u: u.start)


def split_daily_result(daily: Daily) -> list[dict]:
    """As partes em que esta diária sincronizada se divide.

    Devolve UMA parte quando não há o que dividir — quem chama não precisa de um
    caso especial, e "não dividir" é sempre uma resposta válida.

    Cada parte traz `paths` (os arquivos dela), o span e a hora de início na régua,
    para a tela poder mostrar a proposta em vez de só executá-la.
    """
    unidades = _units(daily)
    if not unidades:
        return []

    partes: list[list[_Unit]] = [[unidades[0]]]
    fim = unidades[0].end
    for u in unidades[1:]:
        if (u.start - fim) / daily.fps > DAILY_GAP_S:
            partes.append([])
            fim = u.end
        else:
            fim = max(fim, u.end)
        partes[-1].append(u)

    # A régua da sequência entregue começa em `start_tc_frames`; as posições já
    # estão normalizadas a partir dela (ver `Daily.normalize_origin`).
    base = daily.start_tc_frames
    fps = daily.fps
    saida = []
    for i, parte in enumerate(partes):
        inicio = min(u.start for u in parte)
        termino = max(u.end for u in parte)
        paths: list[str] = []
        vistos: set[str] = set()
        for u in parte:
            for p in u.paths:
                if p not in vistos:
                    vistos.add(p)
                    paths.append(p)
        saida.append({
            "index": i,
            # O nome vem de FORA (a UI sabe o idioma; ver CLAUDE.md). Aqui vai só
            # o que identifica a parte: a hora em que ela começa na régua.
            "start_tc": _hhmm((base + inicio) / fps),
            "span_seconds": round((termino - inicio) / fps, 1),
            "file_count": len(paths),
            "take_count": len(parte),
            "paths": paths,
            "first": parte[0].label,
            "last": parte[-1].label,
        })
    return saida


def span_hours(daily: Daily) -> float:
    """Quanto a diária ocupa, em horas de timecode. Ver `MAX_DAILY_SPAN_TC_HOURS`."""
    nominal = max(1, round(daily.fps))
    return daily.span_frames / (3600 * nominal)


def needs_split(daily: Daily) -> bool:
    """Esta diária tem de ser dividida para ser entregue?

    Só o limite do NLE conta aqui. Um vão de horas SEM estourar 24 h é informação
    (a tela pode oferecer a divisão), mas não é um impedimento: uma diária com uma
    pausa longa continua sendo uma diária.
    """
    return span_hours(daily) > MAX_DAILY_SPAN_TC_HOURS


def _hhmm(seconds: float) -> str:
    s = int(seconds % 86400)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}"
