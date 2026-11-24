"""O agente do piloto no Media Composer: acha a janela do problema e põe na frente (a decisão mora em `piloto/auxilio.py`).

⛔ Um modal DESABILITA as outras janelas do processo (medido, `avid/abrir.py`): quem aceita o foco é ele. Painel solto do layout livre também é
janela pequena e habilitada, e por isso só conta como modal com a principal desabilitada, ou com o título dos avisos do MC.
"""

from __future__ import annotations

from typing import Any, Callable

from .. import janela as _janela
from ..piloto import auxilio as _auxilio
from ..piloto import maos, tela

PROGRAMA = "Media Composer"


def _modal() -> tuple[int, tuple[int, int, int, int], str] | None:
    from . import abrir as _a  # noqa: PLC0415 — o abrir importa este módulo

    janelas = _janela.janelas(_a.EXE)
    principal = _janela.escolher_principal(janelas, "Avid Media Composer")
    livre = bool(principal) and _janela.habilitada(principal)
    return next(((h, r, t) for h, t, r in janelas
                 if h != principal and t.strip() != _a.SELECT_PROJECT and _janela.aviso(r) and _janela.habilitada(h) and not _janela.e_popup(h)
                 and (t == _a.AVISO or not livre)), None)


def inesperada() -> bool:
    """Um modal do MC que não é o aviso conhecido? ⭐ MEDIDO (2026-11-08, MC 2024.6): o aviso de projeto repetido se chama "Avid Media Composer", 389×117, e bloqueia as outras janelas."""
    from . import abrir as _a  # noqa: PLC0415

    modal = _modal()
    return bool(modal) and modal[2] != _a.AVISO


def _olhar() -> _auxilio.Olhar:
    from . import abrir as _a  # noqa: PLC0415

    modal = _modal()
    if modal:
        _janela.ao_topo(modal[0])
        if not _janela.focar(modal[0]):
            raise maos.ForaDeFoco("o Windows não deixou pôr o aviso do Media Composer na frente")
    else:
        _a._frente_do_mc()
    hwnd = maos.da_frente()
    if _janela.exe_da_janela(hwnd).lower() != _a.EXE.lower():
        raise maos.ForaDeFoco("outra janela tomou a frente do Media Composer")
    return _auxilio.Olhar(hwnd, tela.monitor_da_janela(modal[0] if modal else _a._de_trabalho()), modal[1] if modal else None)


def com_agente(objetivo: str, tentar: Callable[[], Any], falha: type[Exception], relatar=None) -> Any:
    return _auxilio.com_socorro(PROGRAMA, objetivo, tentar, falha, _olhar, relatar)
