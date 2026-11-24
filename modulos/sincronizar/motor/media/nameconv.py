"""
Sincronizar — a DATA que a câmera escreve no nome do arquivo.

Por que isto existe: a maior parte do material de câmera chega ao editor
TRANSCODADO, e o transcode apaga toda data de dentro do container. No material
real, os proxies RED de uma captação de maio de 2025 dizem `creation_time
2026-07-09` — a data em que o proxy foi feito. Não dá para confiar nela, e a
decisão do projeto é usar só metadado que sobrevive à cópia e ao transcode.

O nome do arquivo sobrevive. E as câmeras profissionais escrevem a data nele.

⚠️ O QUE ESTA DATA SERVE E O QUE NÃO SERVE
──────────────────────────────────────────
SERVE para separar DIÁRIAS (`sync/dailysplit.py`): dois clipes com tokens de data
diferentes, e um buraco entre eles, são dois dias de trabalho.

NÃO SERVE para achar a virada da meia-noite. Medido no material real: a RED grava
a data do RELÓGIO INTERNO da câmera, que NÃO vira junto com o timecode —
`A002_A033_0517…` (TC 23:57) e `A002_A034_0517…` (TC 00:01) carregam o mesmo
token `0517`. Quem acha a virada é a ORDEM (ver `sync/daycycle.py`).

O parser é DELIBERADAMENTE conservador: na dúvida devolve `None`. Uma data errada
é pior que data nenhuma — sem data, a separação cai no buraco no eixo do tempo,
que é o sinal forte; com data errada, ela corta onde não devia.
"""

from __future__ import annotations

import re
from pathlib import Path

#: A janela em que um ano de 2 dígitos é interpretado. `25` → 2025.
_CENTURY = 2000


def _valid(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def parse_name_date(path: Path | str) -> tuple[str | None, str | None, str | None]:
    """A data (e a hora, quando houver) que o NOME ou o CAMINHO carregam.

    Devolve `(data, hora, fonte)`:
      - `data` — `"AAAA-MM-DD"` quando o ano é conhecido, ou `"MM-DD"` quando a
        convenção não o escreve (é o caso da RED). **A data parcial é marcada como
        parcial de propósito** — inventar o ano a partir do relógio do computador
        seria adivinhar sobre material de arquivo.
      - `hora` — `"HH:MM:SS"`, só nas convenções que a escrevem.
      - `fonte` — `"path"` (a data está numa pasta ancestral), `"filename"`, ou
        `None`.

    A ordem das convenções é a da CONFIANÇA, não a da frequência: uma data com ano
    completo vence uma parcial, e uma escrita pelo aparelho vence uma escrita por
    quem organizou a pasta.
    """
    p = Path(path)
    stem = p.stem

    # 1. Gravador de campo que organiza por dia e por hora: a pasta é a data e o
    #    arquivo é o horário. (Hollyland: `hl-2025-05-16/23-57-29.wav`.) É a mais
    #    completa que existe — data E hora, ambas do aparelho.
    for parent in p.parents:
        m = re.search(r"(?:^|[^0-9])(\d{4})-(\d{2})-(\d{2})$", parent.name)
        if not m:
            continue
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        if not _valid(mo, d):
            continue
        hm = re.fullmatch(r"(\d{2})-(\d{2})-(\d{2})", stem)
        hora = None
        if hm and int(hm[1]) < 24 and int(hm[2]) < 60 and int(hm[3]) < 60:
            hora = f"{hm[1]}:{hm[2]}:{hm[3]}"
        return f"{y:04d}-{mo:02d}-{d:02d}", hora, "path"

    # 2. ARRI ALEXA e afins: `A001C001_250516_R1AB` — ano de 2 dígitos, entre `_`.
    #    Exige as duas bordas para não confundir com um contador de 6 dígitos.
    m = re.search(r"_(\d{2})(\d{2})(\d{2})_", stem)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        if _valid(mo, d):
            return f"{_CENTURY + y:04d}-{mo:02d}-{d:02d}", None, "filename"

    # 3. RED: `A002_A034_0517QN` — MMDD seguido de 2 caracteres alfanuméricos de
    #    unicidade, no FIM do nome. Sem ano: a câmera não o escreve.
    m = re.fullmatch(r".*_(\d{2})(\d{2})[A-Z0-9]{2}", stem)
    if m:
        mo, d = int(m[1]), int(m[2])
        if _valid(mo, d):
            return f"{mo:02d}-{d:02d}", None, "filename"

    return None, None, None


def parse_folder_date(path: Path | str) -> str | None:
    """A data que QUEM ORGANIZOU a pasta escreveu — `250516_BOLIVIA`, `250516_SOM`.

    Pista FRACA, e separada da outra de propósito: quem nomeia a pasta é uma pessoa,
    depois da filmagem, e uma pasta chamada `250516_BOLIVIA` contém legitimamente
    material da madrugada do dia 17. **Serve para dar NOME a uma diária, nunca para
    decidir onde ela começa e termina.**
    """
    p = Path(path)
    for part in (p.name, *(a.name for a in p.parents)):
        m = re.match(r"^(\d{2})(\d{2})(\d{2})(?:[_\-.]|$)", part)
        if not m:
            continue
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        if _valid(mo, d):
            return f"{_CENTURY + y:04d}-{mo:02d}-{d:02d}"
    return None
