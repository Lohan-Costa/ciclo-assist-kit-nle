"""A BORDA verde-água: o piloto do Ciclo Assist avisa, na tela, que está agindo.

⭐ Pedido do autor (2026-11-01), depois do teste pelo chat: *"como eu não tinha colocado o pin no
programa não sabia o que estava acontecendo, então fiquei com medo de mexer em algo e atrapalhar
o processo… o piloto do Ciclo Assist não faz o overlay igual o nosso, e seria legal ter essa
função nele. Podemos usar o verde-água, que é a cor de destaque do Ciclo Assist, até para
diferenciar o nosso piloto do piloto do Ciclo Assist durante testes."*

Molde: a borda do piloto da família (`piloto/piloto/borda_windows.py`, azul), com três diferenças:
- ⭐ **Verde-água** (`#4cc4b8`, o `--realce` do painel): azul = o piloto da família (o Claude Code),
  verde-água = o piloto do produto.
- ⭐ **Uma THREAD do serviço, não um processo**: o serviço fica de pé o tempo todo (o piloto da
  família roda em comandos curtos, por isso lá ela é outro processo e conversa por arquivo).
- Sem a pausa por toque (por ora): só o aviso e o F12 (que `maos.freio` já confere a cada gesto).

O que se copia, cada um pelo motivo de lá:
- ⛔ Deixa o clique passar e NUNCA pega o foco (`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`): o piloto
  confere a janela da frente antes de cada gesto, e uma borda que pegasse o foco o faria recusar tudo.
- ⭐ FORA DAS FOTOS (`WDA_EXCLUDEFROMCAPTURE`): a borda é para o editor, não para o localizador.
- Quatro faixas finas por monitor — nada cobre o meio da tela.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
from typing import Iterator

from . import tela as _tela  # noqa: F401  (declara o DPI antes de qualquer coordenada)

log = logging.getLogger("cicloassist.piloto.borda")

COR = (0x4C, 0xC4, 0xB8)        # o --realce do painel: verde-água
TINTA = (0x0B, 0x1F, 0x1D)      # o texto da plaquinha, escuro sobre o verde
ESPESSURA = 6
ETIQUETA = (620, 28)
TIQUE_MS = 100
PADRAO = "CICLO ASSIST PILOTANDO  ·  não mexa  ·  F12 para"
#: Apagada por tanto tempo, a thread da borda sai (e uma nova sobe no próximo `acesa`).
APAGADA_S = 30.0

_trava = threading.Lock()
_pilha: list[str] = []          # um texto por `acesa()` aninhado; o de cima é o que aparece
_thread: threading.Thread | None = None


def texto_atual() -> str:
    with _trava:
        return _pilha[-1] if _pilha else ""


@contextlib.contextmanager
def acesa(texto: str = PADRAO) -> Iterator[None]:
    """Durante o bloco a borda verde-água fica na tela com `texto`. Aninha (o de dentro manda)."""
    if sys.platform != "win32":
        yield
        return
    with _trava:
        _pilha.append(texto or PADRAO)
    _subir()
    try:
        yield
    finally:
        with _trava:
            if _pilha:
                _pilha.pop()


def mudar_texto(texto: str) -> None:
    """Troca o texto da borda acesa (o andamento: "indexando… 12 s")."""
    with _trava:
        if _pilha:
            _pilha[-1] = texto


def _subir() -> None:
    global _thread
    with _trava:
        if _thread and _thread.is_alive():
            return
        _thread = threading.Thread(target=_rodar, name="borda-do-piloto", daemon=True)
        _thread.start()


def _rodar() -> None:
    try:
        _Borda().rodar()
    except Exception:  # noqa: BLE001  — a borda é aviso: sem ela o piloto segue
        log.exception("a borda do piloto não subiu")


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _u = ctypes.WinDLL("user32", use_last_error=True)
    _g = ctypes.WinDLL("gdi32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _LRESULT = ctypes.c_ssize_t
    _WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    _MONPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                  ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    _u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _u.DefWindowProcW.restype = _LRESULT
    _u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    _u.CreateWindowExW.restype = wintypes.HWND
    _u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
    _u.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MONPROC, wintypes.LPARAM]
    # ⛔ MEDIDO (2026-11-01): sem os tipos, o handle de 64 bits do pincel estoura ("int too long to
    #   convert") e a borda abre as janelas SEM PINTAR — contar janelas não pega isso.
    _u.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
    _u.BeginPaint.restype = wintypes.HDC
    _u.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
    _u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    _u.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT),
                             wintypes.UINT]
    _u.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
    _u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    _u.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    _u.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _u.DestroyWindow.argtypes = [wintypes.HWND]
    _g.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    _g.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    _g.CreateFontW.restype = wintypes.HFONT
    _g.SelectObject.restype = wintypes.HGDIOBJ
    _g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _g.CreateSolidBrush.restype = wintypes.HBRUSH
    _g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _k.GetModuleHandleW.restype = wintypes.HMODULE

    class _PAINT(ctypes.Structure):
        _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                    ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL),
                    ("rgbReserved", ctypes.c_byte * 32)]

    class _CLASSE(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                    ("hIconSm", wintypes.HICON)]

    _WS_POPUP = 0x80000000
    _WS_EX = 0x08 | 0x80 | 0x08000000 | 0x00080000 | 0x20   # TOPMOST TOOLWINDOW NOACTIVATE LAYERED TRANSPARENT
    _CLASSE_NOME = "CicloAssistBordaDoPiloto"

    def _cor(rgb: tuple[int, int, int]) -> int:
        return rgb[0] | (rgb[1] << 8) | (rgb[2] << 16)

    # ⛔⛔ O CALLBACK É UM SÓ POR PROCESSO (2026-11-04: o serviço CAIU, e a conversa do editor foi junto).
    #   A classe de janela é registrada UMA vez por processo, com o ponteiro do callback daquele momento;
    #   na 2ª subida o `RegisterClassExW` falha ("já registrada") e a classe continua apontando o callback
    #   da PRIMEIRA borda — que morreu com a thread dela (30 s apagada). A primeira mensagem caía em memória
    #   solta: `0xc0000005` no python.exe, módulo "unknown", e o supervisor do app religava o serviço no meio
    #   do turno. MEDIDO no log de eventos: 04:15:59 1º organizar_bins (borda sobe), 04:17:51 o 2º (sobe de
    #   novo), 04:17:52 APPCRASH. ⇒ O callback vive no MÓDULO e nunca é solto; ele repassa à borda da vez.
    _atual: list["_Borda"] = []

    def _janela_do_processo(hwnd, msg, wp, lp):
        borda = _atual[-1] if _atual else None
        if borda is None:
            return _u.DefWindowProcW(hwnd, msg, wp, lp)
        return borda._janela(hwnd, msg, wp, lp)

    _PROC_DO_PROCESSO = _WNDPROC(_janela_do_processo)

    class _Borda:
        def __init__(self) -> None:
            self.inst = _k.GetModuleHandleW(None)
            self.janelas: list[int] = []
            self.etiqueta = 0
            self.texto = ""
            self.visivel = False
            self.tiques = 0
            self.sem_nada_desde = 0.0
            self.fonte = _g.CreateFontW(-17, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 5, 0, "Segoe UI")
            wc = _CLASSE(ctypes.sizeof(_CLASSE), 0, _PROC_DO_PROCESSO, 0, 0, self.inst, None, None, None, None,
                         _CLASSE_NOME, None)
            _u.RegisterClassExW(ctypes.byref(wc))   # já registrada (2ª subida): segue — o callback é o mesmo

        def _monitores(self) -> list[tuple[int, int, int, int]]:
            achados: list[tuple[int, int, int, int]] = []

            def cada(_h, _dc, r, _l):
                achados.append((r.contents.left, r.contents.top, r.contents.right, r.contents.bottom))
                return True
            _u.EnumDisplayMonitors(None, None, _MONPROC(cada), 0)
            return achados

        def _criar(self, x: int, y: int, w: int, h: int) -> int:
            hwnd = _u.CreateWindowExW(_WS_EX, _CLASSE_NOME, "Ciclo Assist — piloto", _WS_POPUP,
                                      x, y, w, h, None, None, self.inst, None)
            _u.SetLayeredWindowAttributes(hwnd, 0, 235, 2)          # LWA_ALPHA
            _u.SetWindowDisplayAffinity(hwnd, 0x11)                 # WDA_EXCLUDEFROMCAPTURE
            return hwnd

        def _montar(self) -> None:
            e = ESPESSURA
            mons = self._monitores() or [(0, 0, 1920, 1080)]
            for (l, t, r, b) in mons:
                for (x, y, w, h) in ((l, t, r - l, e), (l, b - e, r - l, e), (l, t, e, b - t), (r - e, t, e, b - t)):
                    self.janelas.append(self._criar(x, y, w, h))
            l, t, r, _b = next((m for m in mons if m[0] <= 0 < m[2] and m[1] <= 0 < m[3]), mons[0])
            w, h = ETIQUETA
            self.etiqueta = self._criar(l + (r - l - w) // 2, t + e, w, h)
            self.janelas.append(self.etiqueta)

        def _janela(self, hwnd, msg, wp, lp):
            if msg == 0x0014:                                       # WM_ERASEBKGND
                return 1
            if msg == 0x000F:                                       # WM_PAINT
                ps = _PAINT()
                dc = _u.BeginPaint(hwnd, ctypes.byref(ps))
                r = wintypes.RECT()
                _u.GetClientRect(hwnd, ctypes.byref(r))
                pincel = _g.CreateSolidBrush(_cor(COR))
                _u.FillRect(dc, ctypes.byref(r), pincel)
                _g.DeleteObject(pincel)
                if hwnd == self.etiqueta and self.texto:
                    antiga = _g.SelectObject(dc, self.fonte)
                    _g.SetBkMode(dc, 1)
                    _g.SetTextColor(dc, _cor(TINTA))
                    _u.DrawTextW(dc, self.texto, -1, ctypes.byref(r), 0x1 | 0x4 | 0x20)
                    _g.SelectObject(dc, antiga)
                _u.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == 0x0113:                                       # WM_TIMER
                self._tique()
                return 0
            return _u.DefWindowProcW(hwnd, msg, wp, lp)

        def _tique(self) -> None:
            self.tiques += 1
            texto = texto_atual()
            if texto:
                self.sem_nada_desde = 0.0
                if not self.visivel or texto != self.texto:
                    self.texto = texto
                    for h in self.janelas:
                        _u.ShowWindow(h, 4)                         # SW_SHOWNOACTIVATE
                        _u.InvalidateRect(h, None, True)
                    self.visivel = True
                if self.tiques % 10 == 0:                           # outra janela "sempre no topo" não a cobre
                    for h in self.janelas:
                        _u.SetWindowPos(h, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
                return
            if self.visivel:
                for h in self.janelas:
                    _u.ShowWindow(h, 0)
                self.visivel = False
            self.sem_nada_desde = self.sem_nada_desde or time.monotonic()
            if time.monotonic() - self.sem_nada_desde > APAGADA_S:  # meio minuto apagada: a thread sai
                _u.PostQuitMessage(0)

        def rodar(self) -> None:
            _atual.append(self)
            try:
                self._rodar()
            finally:
                _atual.remove(self)

        def _rodar(self) -> None:
            self._montar()
            _u.SetTimer(self.janelas[0], 1, TIQUE_MS, None)
            msg = wintypes.MSG()
            while _u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _u.TranslateMessage(ctypes.byref(msg))
                _u.DispatchMessageW(ctypes.byref(msg))
            for h in self.janelas:
                _u.DestroyWindow(h)
