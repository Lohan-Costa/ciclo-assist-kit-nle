"""O aviso "vou ficar mudo" ao supervisor do Ciclo Assist (2026-11-23).

⛔ Toda chamada da API do Resolve que ESPERA o Resolve segura o GIL pelo tempo todo (`fusionscript.so`,
`RemoteObject::DoCommand` → `WaitPkt`; banco `plugins/resolve-scripting/api-scripting.md`): o servidor HTTP inteiro
para, a fila da porta enche, e o supervisor do app (`app/src-tauri/src/supervisor.rs`) — que só vê a porta muda e o
processo vivo — religava o motor no meio do conform (PRODC, 80 planos, "importando no Resolve": três vezes, o conform
morto e a API do Resolve presa depois).

Antes de chamar o Resolve, o motor grava em `CICLOASSIST_OCUPADO` (o app passa o caminho ao subir o motor) até quando
pode ficar mudo e por quê; o supervisor espera esse prazo em vez de religar. Ninguém renova o aviso DURANTE a chamada
(o GIL está preso): o prazo é o teto da chamada inteira. Fora do app (os testes, o De Lá Pra Cá sozinho) não há
variável e nada acontece.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager

#: Teto de uma chamada ao Resolve. Passou disso mudo, o supervisor volta a contar a tolerância dele e religa.
PRAZO_PADRAO = 15 * 60

_trava = threading.Lock()
_abertos: dict[int, tuple[float, str]] = {}  # um por chamada viva: (até, motivo)
_seq = [0]


def _gravar() -> None:
    caminho = os.environ.get("CICLOASSIST_OCUPADO")
    if not caminho:
        return
    try:
        if not _abertos:
            os.remove(caminho)
            return
        ate, motivo = max(_abertos.values())
        tmp = caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ate": int(ate), "motivo": motivo, "pid": os.getpid()}, f, ensure_ascii=False)
        os.replace(tmp, caminho)
    except OSError:
        pass  # o aviso é ajuda ao supervisor; falhar nele nunca derruba a chamada


@contextmanager
def mudo(motivo: str, segundos: float = PRAZO_PADRAO):
    """Enquanto o bloco roda, o supervisor sabe que a porta pode não atender (até `segundos`)."""
    with _trava:
        _seq[0] += 1
        chave = _seq[0]
        _abertos[chave] = (time.time() + segundos, motivo)
        _gravar()
    try:
        yield
    finally:
        with _trava:
            _abertos.pop(chave, None)
            _gravar()
