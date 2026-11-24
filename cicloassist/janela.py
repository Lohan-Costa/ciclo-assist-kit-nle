"""Pôr a janela de um programa em foco a partir do SERVIÇO — e devolvê-lo depois.

Para que existe: o Media Composer só indexa uma pasta nova de `Avid MediaFiles\\MXF` quando
GANHA O FOCO (banco, `protocolos/msm/README.md`; às vezes só no 2º ciclo, ~20 s). Sem isto a
operação de importar masters dependeria de um clique do editor no MC.

⛔ **O Windows não deixa um processo em segundo plano roubar o foco** (proteção de primeiro
plano): o `SetForegroundWindow` devolve sucesso e nada acontece. Um ALT solto antes libera —
é o mesmo truque do piloto (`piloto/maos_windows.py::frente`), medido lá.

⬜ macOS: `pendente` (seria `open -a` ou System Events). As funções devolvem False e quem
chama diz o gesto ao editor.
"""

from __future__ import annotations

import sys
import time

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    # ⛔ Ciente de DPI ANTES de qualquer retângulo: sem isso, a 125 % o GetWindowRect devolve
    #   coordenadas VIRTUALIZADAS (MEDIDO 2026-11-02: a principal maximizada saiu 1536×816 em vez
    #   de 1920×1020) — e quem mistura com a foto ou o clique do piloto erra calado.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:  # já declarado
        pass
    _u = ctypes.WinDLL("user32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _u.GetForegroundWindow.restype = wintypes.HWND
    _u.SetForegroundWindow.argtypes = [wintypes.HWND]
    _u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.IsIconic.argtypes = [wintypes.HWND]
    _u.IsWindowVisible.argtypes = [wintypes.HWND]
    _u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _u.FindWindowW.restype = wintypes.HWND
    _ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _k.OpenProcess.restype = wintypes.HANDLE
    _k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                              ctypes.POINTER(wintypes.DWORD)]


def _exe_da_janela(hwnd) -> str:
    pid = wintypes.DWORD()
    _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = _k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        return buf.value.rsplit("\\", 1)[-1] if _k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        _k.CloseHandle(h)


def janela_principal(exe: str, titulo: str = "") -> int | None:
    """A MAIOR janela visível do processo `exe` (ex.: "AvidMediaComposer.exe").

    `titulo`: a principal é a maior das que têm o título COMEÇANDO assim (sem nenhuma, a maior
    de todas). ⛔⛔ MEDIDO (2026-11-02, MC 2024.6, layout padrão de DOIS monitores): o MC põe
    Composer e Timeline numa 2ª janela de topo no outro monitor, chamada "AvidMediaComposer"
    (sem espaços) e 12 px MAIOR que a principal ("Avid Media Composer  - projeto") — pela área,
    o menu File, as bins e o Ctrl+S iam para a janela errada."""
    escolhida = escolher_principal(janelas(exe), titulo)
    return escolhida


def escolher_principal(achadas: list[tuple[int, str, tuple[int, int, int, int]]],
                       titulo: str = "") -> int | None:
    """A regra de `janela_principal`, pura (para teste)."""
    def area(r):
        return (r[2] - r[0]) * (r[3] - r[1])
    com = [a for a in achadas if titulo and a[1].startswith(titulo)]
    pool = com or achadas
    return max(pool, key=lambda a: area(a[2]))[0] if pool else None


def do_painel(exe: str, titulo: str) -> int | None:
    """A janela de um painel FLUTUANTE, pelo título exato ("Timeline", "Bins", "Composer"…).

    ⭐⭐ MEDIDO (2026-11-02, MC 2024.6, layout livre do autor): cada painel solto vira uma janela
    de topo com o NOME DO PAINEL no título — o sinal de graça e sempre certo de onde ele está,
    em qualquer monitor e de qualquer tamanho. Encaixado numa janela (layout padrão), ele não
    tem janela própria: `None`, e quem chama procura nas janelas grandes.

    ⛔ E o MC NUMERA o painel ao reabrir: MEDIDO (2026-11-02) — o "Bins" do layout voltou como
    "Bins.1" no projeto seguinte, noutro lugar e tamanho. Vale o título ou o título + ".N"."""
    import re

    padrao = re.compile(rf"{re.escape(titulo)}(\.\d+)?")
    return next((h for h, t, _r in janelas(exe) if padrao.fullmatch(t.strip())), None)


def ao_topo(hwnd: int) -> bool:
    """Põe a janela no TOPO DA PILHA (sem mover, sem redimensionar, sem ativar).

    ⛔⛔ MEDIDO (2026-11-02, MC 2024.6): o aviso de teclado era a janela da FRENTE (o foco) e
    tinha 8 janelas visíveis ACIMA dele na pilha, a principal do MC entre elas — escondido, a
    foto não o via e o "Don't warn me again" não existia. Foco ≠ pilha."""
    if sys.platform != "win32":
        return False
    _u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    return bool(_u.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0010))      # NOSIZE | NOMOVE | NOACTIVATE


def travada(hwnd: int) -> bool:
    """A janela não atende mensagens há ~5 s ("Not Responding" no título que o Windows desenha)."""
    return sys.platform == "win32" and bool(hwnd) and bool(_u.IsHungAppWindow(wintypes.HWND(hwnd)))


def habilitada(hwnd: int) -> bool:
    """A janela aceita entrada? (um modal DESABILITA as outras janelas do processo)."""
    return sys.platform == "win32" and bool(_u.IsWindowEnabled(wintypes.HWND(hwnd)))


def e_popup(hwnd: int) -> bool:
    """Menu ou lista suspensa do Qt (classe `…QWindowPopup…`) — NUNCA um aviso.

    ⛔⛔ MEDIDO (2026-11-02, MC 2024.6): o menu File aberto é uma janela de topo com o título
    "AvidMediaComposer" — o MESMO do aviso de teclado —, pequena e habilitada (classe
    `Qt51512QWindowPopupDropShadowSaveBits`, `WS_EX_TOOLWINDOW|TOPMOST`). Contado como aviso, o
    abrir tentava trazê-lo à frente e o item Exit "não existia"."""
    if sys.platform != "win32":
        return False
    buf = ctypes.create_unicode_buffer(256)
    _u.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return "Popup" in buf.value


def pequena(ret: tuple[int, int, int, int], area_do_monitor: int = 1920 * 1080) -> bool:
    """Um aviso/barra de progresso, e não uma janela de trabalho: menos de 1/4 do monitor.

    MEDIDO (2026-11-02, MC 2024.6): aviso de teclado 518×190, barra de carregar 402×125; a
    janela do Composer/Timeline no 2º monitor, 1920×1032 — o MESMO título dos dois primeiros."""
    return (ret[2] - ret[0]) * (ret[3] - ret[1]) < area_do_monitor / 4


def _area_do_monitor(ret) -> int:
    class _MI(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("rc", ctypes.c_long * 4), ("work", ctypes.c_long * 4),
                    ("flags", ctypes.c_uint32)]
    r = wintypes.RECT(*ret)
    _u.MonitorFromRect.restype = ctypes.c_void_p
    _u.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), ctypes.c_uint32]
    m = _MI()
    m.cb = ctypes.sizeof(_MI)
    h = _u.MonitorFromRect(ctypes.byref(r), 2)
    if not h or not _u.GetMonitorInfoW(ctypes.c_void_p(h), ctypes.byref(m)):
        return 1920 * 1080
    return (m.rc[2] - m.rc[0]) * (m.rc[3] - m.rc[1])


def aviso(ret: tuple[int, int, int, int]) -> bool:
    """`pequena` contra o monitor REAL onde a janela está."""
    return sys.platform == "win32" and pequena(ret, _area_do_monitor(ret))


def existe_aviso(titulo: str, exe: str = "") -> bool:
    """Há um AVISO visível com este título — janela pequena (`aviso`)? Ver `janela_principal`:
    no layout de dois monitores do MC, uma janela de trabalho tem o título dos avisos.

    ⛔ Visível, e por varredura — nunca `FindWindowW`: o MC 2024.6 mantém uma janela OCULTA com
    o título "AvidMediaComposer" o tempo todo (medido 2026-11-01, projeto aberto, nenhum aviso
    na tela), e o `FindWindowW` a acha."""
    if sys.platform != "win32":
        return False
    if exe:
        return any(t == titulo and aviso(r) and not e_popup(h) for h, t, r in janelas(exe))
    achadas: list[tuple[int, int, int, int]] = []

    def cada(hwnd, _):
        if _u.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            _u.GetWindowTextW(hwnd, buf, 256)
            if buf.value == titulo and not e_popup(hwnd):
                r = wintypes.RECT()
                _u.GetWindowRect(hwnd, ctypes.byref(r))
                achadas.append((r.left, r.top, r.right, r.bottom))
        return True

    _u.EnumWindows(_ENUM(cada), 0)
    return any(aviso(r) for r in achadas)


def janelas(exe: str) -> list[tuple[int, str, tuple[int, int, int, int]]]:
    """As janelas VISÍVEIS do processo `exe`: (hwnd, título, retângulo de tela)."""
    if sys.platform != "win32":
        return []
    achadas: list[tuple[int, str, tuple[int, int, int, int]]] = []

    def cada(hwnd, _):
        if _u.IsWindowVisible(hwnd) and _exe_da_janela(hwnd).lower() == exe.lower():
            r = wintypes.RECT()
            _u.GetWindowRect(hwnd, ctypes.byref(r))
            buf = ctypes.create_unicode_buffer(256)
            _u.GetWindowTextW(hwnd, buf, 256)
            achadas.append((int(hwnd), buf.value, (r.left, r.top, r.right, r.bottom)))
        return True

    _u.EnumWindows(_ENUM(cada), 0)
    return achadas


def exe_da_janela(hwnd: int) -> str:
    return _exe_da_janela(hwnd) if sys.platform == "win32" and hwnd else ""


def da_frente() -> int | None:
    return _u.GetForegroundWindow() if sys.platform == "win32" else None


def focar(hwnd: int | None, tentativas: int = 5) -> bool:
    """Põe `hwnd` em primeiro plano e devolve se ele FICOU lá."""
    if sys.platform != "win32" or not hwnd:
        return False
    for _ in range(tentativas):
        _u.keybd_event(0x12, 0, 0, 0)        # ALT solto: libera o SetForegroundWindow
        _u.keybd_event(0x12, 0, 2, 0)
        _u.ShowWindow(hwnd, 9 if _u.IsIconic(hwnd) else 5)   # só restaura a minimizada
        _u.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        if _u.GetForegroundWindow() == hwnd:
            return True
    return False
