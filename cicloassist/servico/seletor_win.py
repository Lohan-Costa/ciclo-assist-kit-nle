r"""O seletor MODERNO do Windows (o do Explorer: barra de endereço, Acesso rápido), em `ctypes`.

Roda como PROGRAMA, num processo filho do serviço — um diálogo que derruba o processo não pode
derrubar o serviço (que é o painel):

    python -m cicloassist.servico.seletor_win --titulo "A timeline" --arquivos --ext prproj --ext aaf --varios

Imprime um caminho absoluto por linha, em UTF-8, e sai 0. **Cancelar imprime nada** — "o editor
desistiu" e "deu erro" não se confundem.

⭐ Escrito a partir do `dialogo_win.py` do De Lá Pra Cá (medido lá em 2026-08-16, Win 11: o
`IFileOpenDialog` com `FOS_PICKFOLDERS`), com o modo ARQUIVO a mais: `SetFileTypes` com o filtro de
extensões e um segundo par "Todos os arquivos" — um arquivo com extensão inesperada é melhor recusado
DEPOIS, com o motivo, do que invisível no diálogo (a mesma decisão do De Lá Pra Cá).

Pedido do autor (2026-11-01): *"escrever caminho na mão é a pior experiência de usuário possível"*.

⚠️ Índices de VTABLE: errar um não dá erro — chama OUTRO método. `--conferir` monta o diálogo sem
abri-lo e imprime as opções gravadas (o teste de regressão, sem ninguém clicar).
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import POINTER, byref, c_int, c_uint, c_ulong, c_void_p, c_wchar_p

S_OK = 0
E_CANCELADO = 0x800704C7          # HRESULT_FROM_WIN32(ERROR_CANCELLED): resposta, não erro
COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1

FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040  # só caminho de disco (nada de "Este Computador")
FOS_ALLOWMULTISELECT = 0x00000200
FOS_PATHMUSTEXIST = 0x00000800
FOS_FILEMUSTEXIST = 0x00001000
SIGDN_FILESYSPATH = 0x80058000

WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_POPUP = 0x80000000
SW_SHOWNA = 8

#   IUnknown 0..2 · IModalWindow 3 (Show) · IFileDialog 4..26 · IFileOpenDialog 27..28
_RELEASE = 2
_SHOW = 3
_SET_FILE_TYPES = 4
_SET_OPTIONS = 9
_GET_OPTIONS = 10
_SET_TITLE = 17
_SET_OK_LABEL = 18
_GET_RESULTS = 27
_SI_GET_DISPLAY_NAME = 5          # IShellItem
_SIA_GET_COUNT = 7                # IShellItemArray
_SIA_GET_ITEM_AT = 8


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class FILTERSPEC(ctypes.Structure):       # COMDLG_FILTERSPEC
    _fields_ = [("pszName", c_wchar_p), ("pszSpec", c_wchar_p)]


def _ole():
    return ctypes.oledll.ole32


def _guid(texto: str) -> GUID:
    g = GUID()
    _ole().CLSIDFromString(c_wchar_p(texto), byref(g))
    return g


def _metodo(ponteiro, indice, restype, *argtypes):
    vtable = ctypes.cast(ponteiro, POINTER(POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtable[indice])


def _soltar(ponteiro) -> None:
    if ponteiro:
        _metodo(ponteiro, _RELEASE, c_ulong)(ponteiro)


def _dono() -> int:
    """Janela 1x1 no topo, DONA do diálogo: sem ela o diálogo nasce atrás do NLE e o editor acha
    que o botão não fez nada (o mesmo conserto do De Lá Pra Cá)."""
    user32 = ctypes.windll.user32
    hwnd = user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, "STATIC", None, WS_POPUP,
                                  0, 0, 1, 1, None, None, None, None)
    if hwnd:
        user32.ShowWindow(hwnd, SW_SHOWNA)
        user32.SetForegroundWindow(hwnd)
    return hwnd


def _criar():
    _ole().CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    dlg = c_void_p()
    _ole().CoCreateInstance(byref(_guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")), None,
                            CLSCTX_INPROC_SERVER,
                            byref(_guid("{D57C7288-D4AD-4768-BE02-9D969532D960}")), byref(dlg))
    return dlg


def _preparar(dlg, titulo: str, arquivos: bool, varios: bool, extensoes: list[str]):
    opcoes = c_ulong()
    _metodo(dlg, _GET_OPTIONS, c_int, POINTER(c_ulong))(dlg, byref(opcoes))
    extra = FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
    extra |= FOS_FILEMUSTEXIST if arquivos else FOS_PICKFOLDERS
    if varios:
        extra |= FOS_ALLOWMULTISELECT
    # SOMA às opções que vieram (o diálogo traz padrões próprios), nunca substitui.
    _metodo(dlg, _SET_OPTIONS, c_int, c_ulong)(dlg, opcoes.value | extra)
    _metodo(dlg, _SET_TITLE, c_int, c_wchar_p)(dlg, titulo)
    filtros = None
    if arquivos and extensoes:
        padroes = ";".join(f"*.{e.lstrip('.')}" for e in extensoes)
        rotulo = " ".join(e.lstrip(".").upper() for e in extensoes)
        filtros = (FILTERSPEC * 2)(FILTERSPEC(rotulo, padroes), FILTERSPEC("Todos os arquivos", "*.*"))
        _metodo(dlg, _SET_FILE_TYPES, c_int, c_uint, POINTER(FILTERSPEC))(dlg, 2, filtros)
    if not arquivos:
        _metodo(dlg, _SET_OK_LABEL, c_int, c_wchar_p)(dlg, "Usar esta pasta" if not varios else "Usar estas pastas")
    return filtros        # ⚠️ vivo até o Show: o diálogo guarda o ponteiro, não uma cópia


def conferir(arquivos: bool = True, varios: bool = True) -> int:
    dlg = _criar()
    try:
        _guarda = _preparar(dlg, "conferência", arquivos, varios, ["prproj", "aaf"])  # noqa: F841
        opcoes = c_ulong()
        _metodo(dlg, _GET_OPTIONS, c_int, POINTER(c_ulong))(dlg, byref(opcoes))
        return opcoes.value
    finally:
        _soltar(dlg)


def escolher(titulo: str, arquivos: bool, varios: bool, extensoes: list[str]) -> list[str]:
    dlg = _criar()
    hwnd = _dono()
    try:
        _guarda = _preparar(dlg, titulo, arquivos, varios, extensoes)  # noqa: F841
        hr = _metodo(dlg, _SHOW, c_int, c_void_p)(dlg, hwnd or None) & 0xFFFFFFFF
        if hr == E_CANCELADO:
            return []
        if hr != S_OK:
            raise OSError(f"o seletor devolveu 0x{hr:08x}")
        arr = c_void_p()
        _metodo(dlg, _GET_RESULTS, c_int, POINTER(c_void_p))(dlg, byref(arr))
        try:
            n = c_uint()
            _metodo(arr, _SIA_GET_COUNT, c_int, POINTER(c_uint))(arr, byref(n))
            caminhos = []
            for i in range(n.value):
                item = c_void_p()
                _metodo(arr, _SIA_GET_ITEM_AT, c_int, c_uint, POINTER(c_void_p))(arr, i, byref(item))
                try:
                    nome = c_wchar_p()
                    _metodo(item, _SI_GET_DISPLAY_NAME, c_int, c_int, POINTER(c_wchar_p))(
                        item, SIGDN_FILESYSPATH, byref(nome))
                    if nome.value:
                        caminhos.append(nome.value)
                    _ole().CoTaskMemFree(nome)       # alocado pela COM: libera a COM
                finally:
                    _soltar(item)
            return caminhos
        finally:
            _soltar(arr)
    finally:
        _soltar(dlg)
        if hwnd:
            ctypes.windll.user32.DestroyWindow(hwnd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="o seletor nativo do Windows")
    ap.add_argument("--titulo", default="Escolha")
    ap.add_argument("--arquivos", action="store_true", help="arquivos (sem isto: pastas)")
    ap.add_argument("--varios", action="store_true")
    ap.add_argument("--ext", action="append", default=[])
    ap.add_argument("--conferir", action="store_true")
    a = ap.parse_args(argv)
    if sys.platform != "win32":
        print("este seletor só existe no Windows", file=sys.stderr)
        return 2
    if a.conferir:
        print("0x%x" % conferir(a.arquivos, a.varios))
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        caminhos = escolher(a.titulo, a.arquivos, a.varios, a.ext)
    except OSError as e:
        print(f"o seletor falhou: {e}", file=sys.stderr)
        return 1
    for c in caminhos:
        print(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
