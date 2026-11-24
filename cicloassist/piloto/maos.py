"""Clique e tecla — o mínimo, copiado do `piloto/maos_windows.py` da família.

⛔⛔ **Antes de cada gesto, a janela da frente é conferida** (`ForaDeFoco`). Tecla que cai na
janela errada vira atalho de outro programa — e o Ctrl+S no editor de texto do editor, ou uma
letra no MC, é o pior modo de falha: agir no programa errado, calado (banco: o caminho digitado
que virou Lift na timeline, 2026-10-13).
⛔ **F12 apertado = parar** (`Parado`), o freio da família. Sem borda aqui: os gestos do Assist
são curtos (um clique, uma tecla), e o editor vê a operação no cartão do chat.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from . import tela as _tela  # noqa: F401  (declara o DPI antes de qualquer coordenada)

if sys.platform == "win32":
    _u = ctypes.windll.user32
    _u.GetForegroundWindow.restype = wintypes.HWND
    _u.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    _u.GetAncestor.restype = wintypes.HWND
    # ⚠️ O bit "apertada desde a última consulta" vem SUJO na 1ª consulta de um processo (banco,
    #    piloto `maos_windows.py`): uma leitura descartada aqui, senão a 1ª operação pararia sozinha.
    _u.GetAsyncKeyState(0x7B)


class ForaDeFoco(RuntimeError):
    pass


class Parado(RuntimeError):
    pass


VK_CONTROL, VK_ESC, VK_F12 = 0x11, 0x1B, 0x7B
VK_TAB, VK_RETURN, VK_SPACE = 0x09, 0x0D, 0x20


class _MOUSE(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _TECLA(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", _MOUSE), ("ki", _TECLA), ("pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _enviar(*itens: _INPUT) -> None:
    arr = (_INPUT * len(itens))(*itens)
    _u.SendInput(len(itens), arr, ctypes.sizeof(_INPUT))


def _mouse(x: int, y: int, flags: int) -> _INPUT:
    vx, vy, vw, vh = (_u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    ax = int((x - vx) * 65535 / max(vw - 1, 1))
    ay = int((y - vy) * 65535 / max(vh - 1, 1))
    i = _INPUT(type=0)
    i.u.mi = _MOUSE(ax, ay, 0, flags | 0x8000 | 0x4000, 0, 0)  # ABSOLUTE | VIRTUALDESK
    return i


def _tecla_input(vk: int, solta: bool) -> _INPUT:
    i = _INPUT(type=1)
    i.u.ki = _TECLA(vk, 0, 2 if solta else 0, 0, 0)
    return i


def freio() -> None:
    """Levanta `Parado` se o F12 foi apertado desde a última olhada."""
    if sys.platform == "win32" and _u.GetAsyncKeyState(VK_F12) & 0x8001:
        raise Parado("o F12 foi apertado — parei")


def da_frente() -> int:
    h = _u.GetForegroundWindow()
    return int(_u.GetAncestor(h, 2) or h or 0)  # GA_ROOT


def exigir_frente(hwnd: int) -> None:
    freio()
    if da_frente() != hwnd:
        raise ForaDeFoco("a janela da frente mudou — não vou agir em outro programa")


def clicar(hwnd: int, x: int, y: int) -> None:
    """Clique em (x, y) DE TELA, só com `hwnd` na frente."""
    exigir_frente(hwnd)
    _enviar(_mouse(x, y, 0x0001))                 # MOVE
    time.sleep(0.08)
    _enviar(_mouse(x, y, 0x0002), _mouse(x, y, 0x0004))  # DOWN, UP


def clicar_direito(hwnd: int, x: int, y: int) -> None:
    """Clique com o botão DIREITO em (x, y) de tela (abre menu de contexto), só com `hwnd` na frente."""
    exigir_frente(hwnd)
    _enviar(_mouse(x, y, 0x0001))                 # MOVE
    time.sleep(0.08)
    _enviar(_mouse(x, y, 0x0008), _mouse(x, y, 0x0010))  # RIGHTDOWN, RIGHTUP


def digitar(hwnd: int, texto: str) -> None:
    """Texto pelo teclado como UNICODE (`KEYEVENTF_UNICODE`): independe do layout do teclado,
    que é justamente o que o aviso de idioma do MC denuncia. Confere a frente a cada letra."""
    for c in texto:
        exigir_frente(hwnd)
        aperta, solta = _INPUT(type=1), _INPUT(type=1)
        aperta.u.ki = _TECLA(0, ord(c), 0x0004, 0, 0)
        solta.u.ki = _TECLA(0, ord(c), 0x0004 | 0x0002, 0, 0)
        _enviar(aperta, solta)
        time.sleep(0.02)


def tecla(hwnd: int, vk: int, *mods: int) -> None:
    """Uma tecla com modificadores, só com `hwnd` na frente."""
    exigir_frente(hwnd)
    _enviar(*[_tecla_input(m, False) for m in mods], _tecla_input(vk, False),
            _tecla_input(vk, True), *[_tecla_input(m, True) for m in reversed(mods)])
