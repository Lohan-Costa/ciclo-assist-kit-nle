"""Abrir espaço na tela: a janela do Ciclo Assist sai da frente enquanto o piloto opera outro programa.

⛔⛔ MEDIDO pelo autor (2026-11-01, teste pelo chat): com a janela do app FIXADA no topo (o pino,
`set_always_on_top`), a borda direita da Select Project do Media Composer ficou coberta — e com
ela os botões Create e Quit. O localizador fez o certo (não clicou no que não via) e a operação
parou; o modelo pediu ao editor para mover a janela. Pedido do autor: *"dar autonomia pro app se
despinar quando ele precisar de um print limpo"*.

O que faz, só no Windows e só nas janelas do NOSSO app (o PID do `--pai` ou o executável do
`--app`): tira do topo (`HWND_NOTOPMOST`) e manda para o FUNDO da pilha (`HWND_BOTTOM`) sem
ativar; no fim — inclusive com erro —, devolve: fixada volta a `HWND_TOPMOST`, solta volta à
frente (`HWND_TOP`), as duas SEM roubar o foco.

⚠️ Só `HWND_NOTOPMOST` não basta: ele põe a janela no topo da faixa NÃO fixada, ainda por cima
do programa. Daí o fundo.
⚠️ O estado do pino no app (o ícone) não muda: o pino é do editor; o piloto só pede licença.
Sem `--pai` nem `--app` (a bancada, o spike), não há janela nossa e nada acontece.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import Iterator

log = logging.getLogger("cicloassist.piloto.espaco")

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _u = ctypes.WinDLL("user32", use_last_error=True)
    _ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u.IsWindowVisible.argtypes = [wintypes.HWND]
    _u.IsIconic.argtypes = [wintypes.HWND]
    _u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

_TOPMOST, _NOTOPMOST, _TOP, _BOTTOM = -1, -2, 0, 1
_SEM_MEXER = 0x0001 | 0x0002 | 0x0010      # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
_WS_EX_TOPMOST = 0x00000008


def _nossas() -> list[tuple[int, bool]]:
    """As janelas visíveis do nosso app, e se cada uma está fixada no topo."""
    from .. import janela as _janela
    from ..servico import aplicativo as _app

    pid, exe = _app.pai(), _app.nome_do_exe().lower()
    if not pid and not exe:
        return []
    achadas: list[tuple[int, bool]] = []

    def cada(hwnd, _):
        if not _u.IsWindowVisible(hwnd):
            return True
        dono = wintypes.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if (pid and dono.value == pid) or (exe and _janela.exe_da_janela(hwnd).lower() == exe):
            fixada = bool(_u.GetWindowLongW(hwnd, -20) & _WS_EX_TOPMOST)   # GWL_EXSTYLE
            achadas.append((int(hwnd), fixada))
        return True

    _u.EnumWindows(_ENUM(cada), 0)
    return achadas


FRASE_CORTADA = ("a janela do Ciclo Assist está com parte fora da tela (numa faixa sem monitor, ou além da "
                 "borda) — não mexo no seu layout, e sem ela inteira você não acompanha o fluxo: traga a janela "
                 "para dentro de um monitor e retome")


def janela_do_app_cortada() -> str:
    """A frase para o editor se alguma janela do app (visível, não minimizada) sai dos monitores; senão "".

    ⭐ Decisão do autor (2026-11-02): o layout é do editor — não se move a janela, para e diz."""
    if sys.platform != "win32":
        return ""
    from . import tela as _tela

    for hwnd, _fixada in _nossas():
        if _u.IsIconic(wintypes.HWND(hwnd)):
            continue                     # minimizada (−32000): escolha do editor, não corte
        r = wintypes.RECT()
        _u.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
        if (r.right - r.left) < 100 or (r.bottom - r.top) < 100:
            continue                     # as janelinhas auxiliares do Tauri (18×18)
        if _tela.parte_fora((r.left, r.top, r.right, r.bottom)) > 0:
            return FRASE_CORTADA
    return ""


@contextlib.contextmanager
def tela_livre(texto: str = "") -> Iterator[list[tuple[int, bool]]]:
    """Durante o bloco, as janelas do app ficam atrás de tudo e a BORDA verde-água avisa que o
    piloto está agindo (`piloto/borda`); depois, voltam como estavam."""
    if sys.platform != "win32":
        yield []
        return
    from . import borda as _borda
    with _borda.acesa(texto or _borda.PADRAO), _tela_livre() as janelas:
        yield janelas


@contextlib.contextmanager
def _tela_livre() -> Iterator[list[tuple[int, bool]]]:
    janelas = _nossas()
    for h, _f in janelas:
        _u.SetWindowPos(h, _NOTOPMOST, 0, 0, 0, 0, _SEM_MEXER)
        _u.SetWindowPos(h, _BOTTOM, 0, 0, 0, 0, _SEM_MEXER)
    if janelas:
        log.info("piloto: %d janela(s) do app fora da frente (%d fixada[s])",
                 len(janelas), sum(f for _h, f in janelas))
    try:
        yield janelas
    finally:
        for h, fixada in janelas:
            _u.SetWindowPos(h, _TOPMOST if fixada else _TOP, 0, 0, 0, 0, _SEM_MEXER)


# ── à vista: o fluxo inteiro com a janela na frente (plano, "sempre à vista", autor 2026-10-31) ──

#: Quantos fluxos seguram a janela agora (reentrante: o executor pode aninhar).
_a_vista = 0
_trava_a_vista = __import__("threading").Lock()


def _por_na_frente() -> None:
    for h, _f in _nossas():
        _u.SetWindowPos(h, _TOPMOST, 0, 0, 0, 0, _SEM_MEXER)


def reafirmar() -> None:
    """Põe de novo a janela na frente, se um fluxo a está segurando (depois de um passo que abriu
    um programa: o programa novo nasce na frente de tudo que não é fixado)."""
    if sys.platform == "win32" and _a_vista:
        _por_na_frente()


@contextlib.contextmanager
def a_vista() -> Iterator[None]:
    """Durante o bloco (um fluxo rodando) a janela do app fica FIXADA no topo, sem roubar o foco —
    o editor vê o andamento e os botões Pausar/Cancelar o tempo todo. Passo pilotado continua
    tirando-a da frente (`tela_livre`), que a devolve fixada porque é assim que a encontrou.

    No fim: fica fixada só se o EDITOR a fixou (o pino; ou se ele apertou o pino no meio do fluxo,
    o que ele escolheu por último — `aplicativo.pino()`); senão volta a solta, ainda na frente.
    ⚠️ Fixar em vez de só trazer à frente: o `SetForegroundWindow` de quem não tem o foco é
    recusado pelo Windows (matriz de plataforma), e `HWND_TOPMOST` sem ativar não é.
    """
    global _a_vista
    if sys.platform != "win32":
        yield
        return
    from ..servico import aplicativo as _app

    with _trava_a_vista:
        _a_vista += 1
        primeiro = _a_vista == 1
        if primeiro:
            _app.lembrar_pino_inicial(any(f for _h, f in _nossas()))
    try:
        _por_na_frente()
        yield
    finally:
        with _trava_a_vista:
            _a_vista -= 1
            ultimo = _a_vista == 0
        if ultimo:
            fixar = _app.pino()
            for h, _f in _nossas():
                _u.SetWindowPos(h, _TOPMOST if fixar else _NOTOPMOST, 0, 0, 0, 0, _SEM_MEXER)
