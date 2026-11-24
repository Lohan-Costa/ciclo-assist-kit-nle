"""O diário da Carta Aberta: fatos que só se ACRESCENTAM, um arquivo por máquina (plano §4.5).

⛔ Sem trava de arquivo: em SMB ela não é confiável (banco `transversal/banco-de-midias-compartilhado.md` §4) e um
`.lock` órfão trava todo mundo. Cada máquina escreve SÓ no seu `.carta/registro/<máquina>.jsonl`; o estado é a soma
dos diários, e desfazer também é uma linha (`tirar`), nunca apagar a de antes.

Um fato `forma` diz onde UMA forma de UMA mídia está NESTA máquina:

    {"fato": "forma", "id": "…", "midia": "<id da .ref.json>", "forma": "avid|trabalho|original",
     "arquivo": "/Volumes/SSD/…/x.mp4", "volume": "SSD", "relativo": "…/x.mp4",
     "por": "nome+taxa+tc+quadros", "medida": null, "maquina": "MAQUINA-1", "ts": "…"}
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from pathlib import Path

from .projeto import Projeto, maquina


def _arquivo(proj: Projeto, quem: str | None = None) -> Path:
    return proj.registro / f"{quem or maquina()}.jsonl"


def _abrir_para_acrescentar(caminho: Path) -> int:
    """Um descritor em que TODA escrita vai para o fim, de forma atômica.

    ⛔⛔ No Windows o `os.O_APPEND` NÃO serve: o CRT da Microsoft o EMULA (busca o fim, depois escreve — dois passos),
    e dois processos anexando ao mesmo tempo escrevem um por cima do outro. MEDIDO (2026-11-12, Windows 11):
    2 × 300 linhas → 592. ⇒ `CreateFileW` com `FILE_APPEND_DATA` e SEM `FILE_WRITE_DATA`: aí é o KERNEL que põe cada
    escrita no fim (o equivalente do `O_APPEND` do POSIX). Sem trava — o desenho proíbe trava (docstring do módulo)."""
    if os.name != "nt":
        return os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    import ctypes
    import msvcrt
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    FILE_APPEND_DATA, SYNCHRONIZE = 0x0004, 0x00100000
    COMPARTILHAR = 0x1 | 0x2 | 0x4                     # leitura, escrita e apagar: o leitor e a outra escrita seguem
    OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL = 4, 0x80
    h = k32.CreateFileW(str(caminho), FILE_APPEND_DATA | SYNCHRONIZE, COMPARTILHAR, None,
                        OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, None)
    if h in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    return msvcrt.open_osfhandle(h, os.O_WRONLY)


def acrescentar(proj: Projeto, fato: dict, quem: str | None = None) -> dict:
    """Acrescenta UMA linha ao diário desta máquina e devolve o fato completo (com `id`, `maquina`, `ts`).

    ⭐ Uma linha = UM `os.write` num descritor de append ATÔMICO (`_abrir_para_acrescentar`): no mesmo sistema, escritas concorrentes não se misturam
    (o teste com dois processos confere); pela rede, cada máquina tem o seu arquivo e o problema nem existe."""
    completo = {"id": uuid.uuid4().hex, **fato, "maquina": quem or maquina(),
                "ts": datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")}
    linha = (json.dumps(completo, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    proj.registro.mkdir(parents=True, exist_ok=True)
    fd = _abrir_para_acrescentar(_arquivo(proj, quem))
    try:
        os.write(fd, linha)
    finally:
        os.close(fd)
    return completo


def fatos(proj: Projeto) -> list[dict]:
    """Todos os fatos de todos os diários, em ordem de `ts`. Leitura DEFENSIVA: linha que não parseia (pode estar
    sendo escrita agora, ou veio cortada pela rede) é pulada, nunca derruba a leitura."""
    out = []
    for arq in sorted(proj.registro.glob("*.jsonl")):
        if arq.name.startswith("._"):
            continue
        try:
            texto = arq.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for linha in texto.splitlines():
            try:
                f = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if isinstance(f, dict) and f.get("fato"):
                out.append(f)
    out.sort(key=lambda f: f.get("ts", ""))   # estável: no empate, a ordem do arquivo (a de escrita) fica
    return out


def formas(proj: Projeto) -> dict[str, list[dict]]:
    """`{id da mídia: [fatos "forma" VIVOS]}` — tirados os que um `tirar` posterior desfez. Dois vínculos para a
    mesma forma com arquivos diferentes ficam OS DOIS (empate é do editor, plano §4.5)."""
    # ⛔ Um `tirar` vale para o vínculo que ele NOMEIA, em qualquer ordem: no mesmo milissegundo a ordenação por hora
    #    o punha às vezes ANTES do vínculo, e o vínculo "ressuscitava" (achado pelo teste, 1 em 3). Religar é um
    #    vínculo NOVO (outro `id`), então "tirado é tirado" não perde nada.
    todos = fatos(proj)
    tirados = {f.get("vinculo") for f in todos if f["fato"] == "tirar"}
    out: dict[str, list[dict]] = {}
    for f in todos:
        if f["fato"] != "forma" or not f.get("midia") or f["id"] in tirados:
            continue
        out.setdefault(f["midia"], []).append(f)
    return out
