"""O timecode de FONTE de um master, e a conta que põe uma fala nele.

⭐⭐ **Pedido do editor (2026-09-21):** *"quando listamos a fala da transcrição, devemos ter
o tc completo do in do trecho"*. A lista dava `01:14` — minuto e segundo desde o começo do
master —, que serve para achar com o olho e não serve para digitar no Avid.

## Onde o TC mora, e é conhecimento do banco

`protocolos/mxf/timecode.md` (medido em 2026-08-14, **3/3 exato**): o TC de fonte está nas
tags de **STREAM** do `ffprobe`, na stream de essência — **não** em `format.tags`.
Conferido na mídia deste editor em 2026-09-21: `15:02:29:00`, `01:31:32:00`, `01:03:47:21`.
**172 ms por arquivo** frio, e por isso fica guardado.

## ⚠️⚠️ A taxa NÃO vem do arquivo de áudio, e é aqui que se erra

MEDIDO: os OP-Atom de som deste acervo têm `time_base = 1/48000` e o acervo não guarda
`fps` para eles. O TC `15:02:29:00` tem campo de quadro, mas o arquivo não declara a que
taxa ele foi escrito — e `:21` é quadro válido tanto a 24 quanto a 25.

⇒ A conta usa a taxa do **PROJETO ABERTO** (medida: `23.976`, non-drop), que é a taxa em
que o Media Composer exibe aquele master na tela do editor. É a única resposta que casa com
o que ele vê.

⚠️ **E por isso o quadro é aproximado**, enquanto o segundo é exato: o campo de quadro do TC
inicial foi escrito pelo gravador, na taxa dele. Para achar uma fala isso não faz diferença
nenhuma; para cortar, faz — e quem corta passa por `transcrever`, que dá o respiro medido.
A tela diz isso no `title` da linha.

⛔ Sem projeto aberto não se inventa taxa: a linha fica sem TC e continua com o `mm:ss`.
Chutar 25 fps erraria todo material 23,976, que é este acervo inteiro.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from fractions import Fraction
from typing import Any

from .. import binarios as _binarios
from . import cache as _cache

log = logging.getLogger("cicloassist.midia.timecode")

#: Onde os TC lidos ficam, ao lado das outras conchas do cache. ⚠️ Um arquivo só para todas
#: as mídias, como a `sondagem.json`: são 11 bytes por mídia, e um por pasta multiplicaria
#: a travessia de diretório por nada.
ARQUIVO = "timecodes.json"

_trava = threading.Lock()
_lido: dict[str, str] | None = None


def _ler_tudo() -> dict[str, str]:
    global _lido
    with _trava:
        if _lido is None:
            caminho = _cache.raiz() / ARQUIVO
            try:
                dados = json.loads(caminho.read_text(encoding="utf-8"))
                _lido = {k: str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                # Cache ilegível vira "não sei", nunca exceção — a regra do módulo de cache.
                _lido = {}
        return _lido


def esquecer() -> None:
    """Descarta o que foi lido. Para os testes e para a troca de pasta de cache."""
    global _lido
    with _trava:
        _lido = None


def _guardar(chave: str, tc: str) -> None:
    dados = _ler_tudo()
    with _trava:
        dados[chave] = tc
        copia = dict(dados)
    try:
        _cache.escrever_atomico(_cache.raiz() / ARQUIVO,
                                json.dumps(copia, ensure_ascii=False, indent=0)
                                .encode("utf-8"))
    except OSError:
        log.debug("não consegui guardar o timecode de %s", chave[:12], exc_info=True)


def do_master(midia: "_cache.Midia") -> str:
    """`"15:02:29:00"` — o TC onde este master começa, ou `""`.

    ⚠️ Guardado para sempre: o TC de fonte de um arquivo não muda. `""` também é guardado —
    material sem TC não pode custar um ffprobe por busca.
    """
    guardados = _ler_tudo()
    if midia.chave in guardados:
        return guardados[midia.chave]

    tc = _perguntar_ao_ffprobe(midia)
    _guardar(midia.chave, tc)
    return tc


def _perguntar_ao_ffprobe(midia: "_cache.Midia") -> str:
    arquivos = midia.manifesto().get("arquivos") or []
    if not arquivos:
        return ""
    try:
        ffprobe = _binarios.achar("ffprobe")
    except Exception:  # noqa: BLE001 — sem ffprobe a linha fica sem TC, e só
        log.debug("sem ffprobe para ler o timecode", exc_info=True)
        return ""

    for caminho in arquivos[:3]:
        try:
            r = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "stream_tags=timecode",
                 "-of", "default=nw=1:nk=1", "file:" + str(caminho)],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            log.debug("ffprobe falhou em %s", caminho, exc_info=True)
            continue
        for linha in (r.stdout or "").split():
            if e_timecode(linha):
                return linha
    return ""


def e_timecode(texto: str) -> bool:
    """`HH:MM:SS:FF` ou `HH:MM:SS;FF` (drop-frame)."""
    partes = str(texto).replace(";", ":").split(":")
    return len(partes) == 4 and all(p.isdigit() and len(p) == 2 for p in partes)


def para_quadros(tc: str, fps: Fraction) -> int | None:
    """`"01:00:00:12"` → quadros. `None` quando não é timecode.

    ⚠️ Conta SEM drop-frame. Sequência 29,97/59,94 nunca passou por aqui, e a tela avisa —
    mesma ressalva de `avid/timeline_do_editor.py`.
    """
    if not e_timecode(tc):
        return None
    h, m, s, f = (int(p) for p in tc.replace(";", ":").split(":"))
    por_segundo = round(float(fps))
    return ((h * 60 + m) * 60 + s) * por_segundo + f


def de_quadros(quadros: int, fps: Fraction) -> str:
    """Quadros → `HH:MM:SS:FF`, dando a volta em 24 h como o Avid dá."""
    por_segundo = max(1, round(float(fps)))
    total = max(0, int(quadros))
    f = total % por_segundo
    s = (total // por_segundo) % 60
    m = (total // (por_segundo * 60)) % 60
    h = (total // (por_segundo * 3600)) % 24
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def somar_segundos(tc: str, segundos: float, fps: Fraction) -> str:
    """O TC deste master mais N segundos — onde a fala começa. `""` sem TC ou sem taxa.

    ⚠️ O QUADRO é aproximado e o SEGUNDO é exato: o campo de quadro do TC inicial foi
    escrito pelo gravador, na taxa dele, e o arquivo de som não declara qual era. Ver o
    cabeçalho do módulo.
    """
    base = para_quadros(tc, fps)
    if base is None:
        return ""
    try:
        adiante = int(round(float(segundos) * float(fps)))
    except (TypeError, ValueError):
        return ""
    return de_quadros(base + max(0, adiante), fps)


def taxa_do_projeto(projeto: dict[str, Any] | None) -> Fraction | None:
    """A taxa em que o Media Composer EXIBE este material, ou `None`.

    ⛔ `None` quando não há projeto aberto, e aí a linha fica sem TC: chutar 25 fps erraria
    todo material 23,976 — que é este acervo inteiro.
    """
    fps = (projeto or {}).get("fps") or {}
    try:
        num, den = int(fps.get("num") or 0), int(fps.get("den") or 0)
    except (TypeError, ValueError):
        return None
    if num <= 0 or den <= 0:
        return None
    return Fraction(num, den)
