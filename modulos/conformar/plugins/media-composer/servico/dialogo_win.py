r"""O seletor de pasta MODERNO do Windows, em Python puro (`ctypes`, sem dependência).

(Docstring CRUA, com o prefixo `r` — ela cita caminhos do Windows, e sem isso o
`D:\GRAVAÇÕES` abaixo vira `SyntaxWarning: invalid escape sequence '\G'`.)

Roda como PROGRAMA, não como biblioteca:

    python dialogo_win.py --titulo "Onde estão as mídias originais"

Imprime um caminho absoluto por linha, em UTF-8, e sai com 0. **Cancelar imprime
nada** — é o mesmo contrato do `escolher.py`, que faz "o editor desistiu" e "deu erro"
não se confundirem.

## Por que existe

O `FolderBrowserDialog` do WinForms — que é o que o serviço abria até aqui — é o
`SHBrowseForFolder`: uma ÁRVORE, sem barra de endereço, sem "Acesso rápido" e **sem
onde colar um caminho**. Chegar a uma diária na rede exige abrir pasta por pasta, o que
o editor descreveu, com razão, como torturante.

O diálogo moderno (o mesmo do Explorer, com barra de endereço e colagem) é o
`IFileOpenDialog` com a opção `FOS_PICKFOLDERS`. É o que o **RELINKER** já entrega —
lá de graça, porque é Tauri e o crate `rfd` faz isso
(`RELINKER/src-tauri/src/lib.rs:125`, `pick_folder`).

## ⚠️ A conclusão anterior estava certa para o PowerShell, e errada para o Python

Ficou registrado no banco de NLEs que "no PowerShell 5.1 não há diálogo de pasta moderno
sem COM na unha", depois de duas tentativas frustradas: declarar `IFileOpenDialog` em
PowerShell (estourou `NullReferenceException` ao ler os resultados) e o truque do
`OpenFileDialog` com validação desligada (devolve duas formas de caminho conforme o
gesto, e entregava a pasta MÃE).

**O que muda aqui é a linguagem, não a interface COM.** Em `ctypes` a vtable se indexa
direto e o marshalling é nosso, então o trecho que quebrava por inspeção passa a ser
depurável. Medido em 2026-08-16, MC 25.6 / Windows 11, com o Python do `.venv-win`:

    CoCreateInstance  -> S_OK
    GetOptions        -> S_OK, padrão 0x1808
    SetOptions        -> S_OK, pedindo 0x1a68
    GetOptions        -> 0x1a68  (FOS_PICKFOLDERS e FOS_ALLOWMULTISELECT gravados)

⭐ **E ganha de graça o que o antigo não fazia: várias pastas de uma vez**
(`FOS_ALLOWMULTISELECT`). O painel já acumula pastas e a rota já devolve lista, então o
editor pode marcar as diárias todas numa passada.

## ⚠️ Processo à parte, sempre

Um diálogo modal aberto DENTRO do serviço travaria o servidor HTTP, e o painel — que
bate `/health` a cada 4 s — daria o Media Composer por desconectado enquanto o editor
procura a pasta com calma. Ver `escolher.py`.

⭐ E rodar em Python em vez de PowerShell mata duas armadilhas registradas no banco de
uma vez: o `.ps1` sem BOM que morre com `Missing closing '}'` por causa de um acento, e
o `[Console]::OutputEncoding` — sem o qual `D:\GRAVAÇÕES\...` volta na codepage ANSI,
corrompido e sem levantar erro (o caminho só "não existe", e o app diz "pasta vazia").
Aqui a saída é UTF-8 por construção.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import POINTER, byref, c_int, c_uint, c_ulong, c_void_p, c_wchar_p

ole32 = ctypes.oledll.ole32
user32 = ctypes.windll.user32

S_OK = 0
# `Show` devolve isto quando o usuário cancela. NÃO é erro — é resposta.
# HRESULT_FROM_WIN32(ERROR_CANCELLED)
E_CANCELADO = 0x800704C7

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1

# Opções do IFileDialog. `FORCEFILESYSTEM` é o que garante que o resultado tenha
# caminho de disco: sem ele o editor pode escolher uma pasta VIRTUAL da shell (uma
# biblioteca, "Este Computador"), e aí `SIGDN_FILESYSPATH` falha — a pasta existe na
# tela e não existe para o `os.scandir`.
FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040
FOS_ALLOWMULTISELECT = 0x00000200
FOS_PATHMUSTEXIST = 0x00000800

SIGDN_FILESYSPATH = 0x80058000

# Janela dona: 1x1, topo, fora da barra de tarefas. Ver `_dono()`.
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_POPUP = 0x80000000
SW_SHOWNA = 8  # mostra SEM roubar o foco de quem já o tem


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(texto: str) -> GUID:
    g = GUID()
    ole32.CLSIDFromString(c_wchar_p(texto), byref(g))
    return g


CLSID_FileOpenDialog = _guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")
IID_IFileOpenDialog = _guid("{D57C7288-D4AD-4768-BE02-9D969532D960}")

# ⭐ O diálogo de SALVAR — a superfície nativa para "dê um nome e escolha onde".
# Nome em cima, navegação com barra de endereço e Acesso rápido embaixo, numa janela só.
# É o que evita partir o gesto em duas superfícies (um campo nosso + um seletor), que foi
# o erro de leitura de requisito que este projeto já pagou uma vez.
CLSID_FileSaveDialog = _guid("{C0B4E2F3-BA21-4773-8DBA-335EC946EB8B}")
IID_IFileSaveDialog = _guid("{84BCCD23-5FDE-4CDB-AEA4-AF64B83D78AB}")

# ⚠️ Índices da VTABLE, e a ordem é herança acumulada — errar um índice não dá erro de
# compilação nenhum: chama-se OUTRO método, com outra assinatura, e o processo morre com
# violação de acesso ou (pior) devolve lixo. Contagem:
#
#   IUnknown         0..2    QueryInterface, AddRef, Release
#   IModalWindow     3       Show
#   IFileDialog      4..26   SetFileTypes … SetFilter
#   IFileOpenDialog  27..28  GetResults, GetSelectedItems
_RELEASE = 2
_SHOW = 3
_SET_OPTIONS = 9
_GET_OPTIONS = 10
_SET_FOLDER = 12
_SET_FILE_NAME = 15
_SET_TITLE = 17
_SET_OK_LABEL = 18
_GET_RESULT = 20
_GET_RESULTS = 27
# IShellItem
_SI_GET_DISPLAY_NAME = 5
# IShellItemArray
_SIA_GET_COUNT = 7
_SIA_GET_ITEM_AT = 8


def _metodo(ponteiro, indice, restype, *argtypes):
    """Um método da vtable de um ponteiro COM cru, pronto para chamar."""
    vtable = ctypes.cast(ponteiro, POINTER(POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtable[indice])


def _soltar(ponteiro) -> None:
    if ponteiro:
        _metodo(ponteiro, _RELEASE, c_ulong)(ponteiro)


def _dono() -> int:
    """Uma janela 1x1 no topo, para ser DONA do diálogo.

    ⚠️ Sem dono, o diálogo nasce ATRÁS da janela do Media Composer e o editor conclui
    que o botão não fez nada — a mesma armadilha que a versão em PowerShell já tratava
    com um formulário invisível `TopMost`. Aqui é a mesma correção em `ctypes`.

    `SW_SHOWNA` (mostra sem ativar) mais `SetForegroundWindow` logo em seguida: a janela
    precisa existir e estar no topo ANTES de virar dona, senão não adianta.

    Usa a classe pré-registrada `STATIC` para não ter de registrar classe nenhuma.
    """
    hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW, "STATIC", None, WS_POPUP,
        0, 0, 1, 1, None, None, None, None)
    if hwnd:
        user32.ShowWindow(hwnd, SW_SHOWNA)
        user32.SetForegroundWindow(hwnd)
    return hwnd


def conferir() -> int:
    """Monta o diálogo SEM abri-lo e devolve as opções que ficaram gravadas.

    ⭐ É o que torna esta interface COM **testável por regressão**, sem ninguém clicar:
    se um índice de vtable sair do lugar (numa atualização do Windows, ou por edição
    distraída), isto quebra na bancada em vez de quebrar na mão do editor. Ver
    `tests/test_dialogo_win.py`.
    """
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    dlg = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_FileOpenDialog), None, CLSCTX_INPROC_SERVER,
                           byref(IID_IFileOpenDialog), byref(dlg))
    try:
        _preparar(dlg, "conferência")
        opcoes = c_ulong()
        _metodo(dlg, _GET_OPTIONS, c_int, POINTER(c_ulong))(dlg, byref(opcoes))
        return opcoes.value
    finally:
        _soltar(dlg)


def conferir_salvar() -> int:
    """O mesmo de `conferir`, para o diálogo de SALVAR: monta e lê de volta, sem abrir.

    Existe pelo mesmo motivo: um índice de vtable errado não dá erro de escrita — chama
    outro método e o processo morre, ou devolve lixo. E o `IFileSaveDialog` herda a
    vtable inteira do `IFileDialog`, então um deslocamento aqui passaria despercebido no
    teste do outro.
    """
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    dlg = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_FileSaveDialog), None, CLSCTX_INPROC_SERVER,
                           byref(IID_IFileSaveDialog), byref(dlg))
    try:
        opcoes = c_ulong()
        _metodo(dlg, _GET_OPTIONS, c_int, POINTER(c_ulong))(dlg, byref(opcoes))
        _metodo(dlg, _SET_OPTIONS, c_int, c_ulong)(
            dlg, opcoes.value | FOS_FORCEFILESYSTEM | FOS_OVERWRITEPROMPT)
        _metodo(dlg, _SET_FILE_NAME, c_int, c_wchar_p)(dlg, "conferência")
        _metodo(dlg, _SET_TITLE, c_int, c_wchar_p)(dlg, "conferência")
        conferido = c_ulong()
        _metodo(dlg, _GET_OPTIONS, c_int, POINTER(c_ulong))(dlg, byref(conferido))
        return conferido.value
    finally:
        _soltar(dlg)


def _preparar(dlg, titulo: str) -> None:
    opcoes = c_ulong()
    _metodo(dlg, _GET_OPTIONS, c_int, POINTER(c_ulong))(dlg, byref(opcoes))
    # SOMA às opções que já vieram, não substitui: o diálogo traz padrões próprios
    # (0x1808 nesta máquina) e apagá-los muda comportamento que não pedimos.
    _metodo(dlg, _SET_OPTIONS, c_int, c_ulong)(
        dlg, opcoes.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM
        | FOS_PATHMUSTEXIST | FOS_ALLOWMULTISELECT)
    _metodo(dlg, _SET_TITLE, c_int, c_wchar_p)(dlg, titulo)
    _metodo(dlg, _SET_OK_LABEL, c_int, c_wchar_p)(dlg, "Usar estas pastas")


def escolher_pastas(titulo: str) -> list[str]:
    """Abre o diálogo e devolve as pastas escolhidas. Lista vazia = cancelou."""
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    dlg = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_FileOpenDialog), None, CLSCTX_INPROC_SERVER,
                           byref(IID_IFileOpenDialog), byref(dlg))

    hwnd = _dono()
    try:
        _preparar(dlg, titulo)

        hr = _metodo(dlg, _SHOW, c_int, c_void_p)(dlg, hwnd or None) & 0xFFFFFFFF
        if hr == E_CANCELADO:
            return []
        if hr != S_OK:
            raise OSError(f"o seletor devolveu 0x{hr:08x}")

        arr = c_void_p()
        _metodo(dlg, _GET_RESULTS, c_int, POINTER(c_void_p))(dlg, byref(arr))
        try:
            quantas = c_uint()
            _metodo(arr, _SIA_GET_COUNT, c_int, POINTER(c_uint))(arr, byref(quantas))
            caminhos = []
            for i in range(quantas.value):
                item = c_void_p()
                _metodo(arr, _SIA_GET_ITEM_AT, c_int, c_uint, POINTER(c_void_p))(
                    arr, i, byref(item))
                try:
                    nome = c_wchar_p()
                    _metodo(item, _SI_GET_DISPLAY_NAME, c_int, c_int,
                            POINTER(c_wchar_p))(item, SIGDN_FILESYSPATH, byref(nome))
                    if nome.value:
                        caminhos.append(nome.value)
                    # ⚠️ Quem libera a string é o CHAMADOR, com CoTaskMemFree — não o
                    # `free` do Python. O ponteiro veio do alocador da COM.
                    ole32.CoTaskMemFree(nome)
                finally:
                    _soltar(item)
            return caminhos
        finally:
            _soltar(arr)
    finally:
        _soltar(dlg)
        if hwnd:
            user32.DestroyWindow(hwnd)


FOS_OVERWRITEPROMPT = 0x00000002


def nomear_e_salvar(titulo: str, sugestao: str = "") -> str | None:
    """O diálogo *Salvar como*: o editor digita um NOME e escolhe ONDE. `None` = cancelou.

    ⭐ Devolve o caminho que ele compôs — **não cria nada**. Quem chama decide o que
    fazer com o nome e o lugar; aqui só se coleta a intenção, numa janela que o editor
    já usa todo dia.

    ⚠️ **Sem filtro de tipo e sem extensão automática**, de propósito: o que se está
    nomeando é um BANCO, não um arquivo. Pôr `.json` no campo faria o editor batizar o
    banco de "NOVELA X.json" — o nome vazaria a nossa implementação para dentro do
    vocabulário dele.

    ⚠️ `FOS_OVERWRITEPROMPT` fica LIGADO: se ele apontar para algo que já existe, quem
    avisa é o Windows, com a caixa que ele conhece — não uma mensagem nossa depois.
    """
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    dlg = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_FileSaveDialog), None, CLSCTX_INPROC_SERVER,
                           byref(IID_IFileSaveDialog), byref(dlg))
    hwnd = _dono()
    try:
        opcoes = c_ulong()
        _metodo(dlg, _GET_OPTIONS, c_int, POINTER(c_ulong))(dlg, byref(opcoes))
        _metodo(dlg, _SET_OPTIONS, c_int, c_ulong)(
            dlg, opcoes.value | FOS_FORCEFILESYSTEM | FOS_OVERWRITEPROMPT)
        _metodo(dlg, _SET_TITLE, c_int, c_wchar_p)(dlg, titulo)
        _metodo(dlg, _SET_OK_LABEL, c_int, c_wchar_p)(dlg, "Criar")
        if sugestao:
            _metodo(dlg, _SET_FILE_NAME, c_int, c_wchar_p)(dlg, sugestao)

        hr = _metodo(dlg, _SHOW, c_int, c_void_p)(dlg, hwnd or None) & 0xFFFFFFFF
        if hr == E_CANCELADO:
            return None
        if hr != S_OK:
            raise OSError(f"o seletor devolveu 0x{hr:08x}")

        item = c_void_p()
        _metodo(dlg, _GET_RESULT, c_int, POINTER(c_void_p))(dlg, byref(item))
        try:
            nome = c_wchar_p()
            _metodo(item, _SI_GET_DISPLAY_NAME, c_int, c_int, POINTER(c_wchar_p))(
                item, SIGDN_FILESYSPATH, byref(nome))
            caminho = nome.value
            ole32.CoTaskMemFree(nome)
            return caminho or None
        finally:
            _soltar(item)
    finally:
        _soltar(dlg)
        if hwnd:
            user32.DestroyWindow(hwnd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="seletores nativos do Windows")
    ap.add_argument("--titulo", default="Onde estão as mídias originais")
    ap.add_argument("--conferir", action="store_true",
                    help="monta o diálogo sem abrir e imprime as opções (bancada)")
    ap.add_argument("--salvar", action="store_true",
                    help="abre o diálogo de SALVAR (nome + local) em vez do de pasta")
    ap.add_argument("--sugestao", default="", help="nome sugerido no diálogo de salvar")
    args = ap.parse_args(argv)

    if sys.platform != "win32":
        print("este seletor só existe no Windows", file=sys.stderr)
        return 2

    if args.conferir:
        print("0x%x" % conferir())
        return 0

    # UTF-8 na saída, sempre: um caminho com acento é a regra neste ramo, não a exceção.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:  # Python < 3.7 — não acontece aqui, mas não custa
        pass

    try:
        if args.salvar:
            escolhido = nomear_e_salvar(args.titulo, args.sugestao)
            caminhos = [escolhido] if escolhido else []
        else:
            caminhos = escolher_pastas(args.titulo)
    except OSError as e:
        # ⚠️ Falar alto. Um seletor que falha calado vira "cliquei e não aconteceu nada",
        # e quem depura vai procurar no painel um defeito que está na plataforma.
        print(f"o seletor moderno falhou: {e}", file=sys.stderr)
        return 1

    for c in caminhos:
        print(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
