"""Digitar no Media Composer — o "copiar a seleção" do botão Coletar do Magic Link.

⚠️⚠️ **ÚLTIMO RECURSO, escolhido depois de medir a API** (banco,
`plugins/avid-panel-sdk/copia-da-timeline.md`, MC 2025.6): a API não lê a seleção da timeline, e
o `DoCommand(6224 "Copy to Clipboard")` **não copiou** quando disparado com o painel em foco.
O roteiro que funcionou é o do editor, digitado:

    Ctrl+0   (Cmd+0 no Mac)   foca a timeline
    Ctrl+C   (Cmd+C no Mac)   copia o que está selecionado

⭐ Para o editor não há "copiar": o botão é um coletor do que estiver selecionado (regra do
autor). O mesmo roteiro — `Ctrl+0` antes de tudo — é o do Promo Entrega (`teclado.py` de lá), de
onde veio a armadilha do `SendInput`.

⛔ **Tecla só vai se a janela em primeiro plano for do Media Composer.** A tecla vai para quem
está na frente: um `Ctrl+C` que caia noutro programa copia outra coisa, e um `Ctrl+0` num
navegador muda o zoom. O clique no botão do painel já traz o MC para a frente (o painel é janela
dele) — conferir é barato e evita o pior modo de falha: agir no programa errado em silêncio.

⭐ Na JANELA DO APP (desenho de app único, 2026-10-21) o clique é no app, e o MC não está na frente:
`copiar_selecao(trazer_mc=True)` o traz antes (no Mac, pelo System Events — a mesma Acessibilidade das
teclas) e confere de novo. No Windows ⏳: o `SetForegroundWindow` tem restrições de quem pode roubar o foco.

Plataforma (banco, `transversal/matriz-de-plataforma.md` §F "digitar atalho no NLE"):
- Windows: `SendInput` — **medido** (2026-09-24).
- macOS: `osascript` + System Events — exige a permissão de **Acessibilidade**; o processo do MC 25.12
  se chama `AvidMediaComposer` (sem espaços; medido 2026-10-25 — o nome antigo daqui nunca casava).
"""

from __future__ import annotations

import logging
import subprocess
import time

from plataforma import E_MACOS, E_WINDOWS

log = logging.getLogger("delapraca.teclado")

VK_CONTROL, VK_0, VK_C = 0x11, 0x30, 0x43
_KEYEVENTF_KEYUP = 0x0002
_INPUT_KEYBOARD = 1

#: Nome do processo do Media Composer em cada sistema.
PROCESSO_MC_WIN = "AvidMediaComposer.exe"
PROCESSO_MC_MAC = "AvidMediaComposer"


class TecladoIndisponivel(RuntimeError):
    """Não deu para digitar — o texto diz por quê, para o editor."""


def disponivel() -> bool:
    return E_WINDOWS or E_MACOS


# ── Windows ─────────────────────────────────────────────────────────────────────────────

def _estruturas():
    """As `struct` do `SendInput`.

    ⚠️⚠️ `MOUSEINPUT` tem de ser declarada mesmo sem uso: o `INPUT` carrega uma UNIÃO, e
    declarando só a parte de teclado ela fica com 24 bytes em vez de 32 (x64) — o `SendInput`
    **devolve 0 sem erro e sem tecla nenhuma** (Promo Entrega, medido).
    """
    import ctypes
    import ctypes.wintypes as w

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                    ("time", w.DWORD), ("dwExtraInfo", PUL)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                    ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", PUL)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]

    class UNIAO(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", w.DWORD), ("u", UNIAO)]

    return INPUT, KEYBDINPUT


def _atalho_win(*vks) -> bool:
    """Aperta as teclas na ordem e solta na ordem inversa. `False` se o Windows recusou."""
    import ctypes

    INPUT, KEYBDINPUT = _estruturas()
    eventos = [(v, False) for v in vks] + [(v, True) for v in reversed(vks)]
    pacote = (INPUT * len(eventos))()
    for i, (vk, solta) in enumerate(eventos):
        pacote[i].type = _INPUT_KEYBOARD
        pacote[i].ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=_KEYEVENTF_KEYUP if solta else 0,
                                  time=0, dwExtraInfo=None)
    return ctypes.windll.user32.SendInput(len(pacote), pacote, ctypes.sizeof(INPUT)) == len(eventos)


def _primeiro_plano_win() -> str:
    """O nome do executável da janela em primeiro plano (`""` se não der)."""
    import ctypes
    import ctypes.wintypes as w

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    pid = w.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    # Consulta de nome sem abrir o processo inteiro: PROCESS_QUERY_LIMITED_INFORMATION.
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        tam = w.DWORD(len(buf))
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tam)):
            return buf.value.replace("/", "\\").rsplit("\\", 1)[-1]
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


# ── macOS (pendente de medição) ────────────────────────────────────────────────────────

def _osascript(*linhas: str) -> subprocess.CompletedProcess:
    """Roda AppleScript por `-e` fixos: nenhum texto variável entra no script."""
    argv = ["osascript"]
    for linha in linhas:
        argv += ["-e", linha]
    return subprocess.run(argv, capture_output=True, text=True, timeout=10)


def _primeiro_plano_mac() -> str:
    r = _osascript('tell application "System Events" to get name of first application '
                   'process whose frontmost is true')
    return (r.stdout or "").strip()


def _atalho_mac(tecla: str) -> bool:
    """`tecla` é "0" ou "c" — constantes deste módulo, nunca texto de fora."""
    assert tecla in ("0", "c")
    r = _osascript(f'tell application "System Events" to keystroke "{tecla}" using command down')
    if r.returncode != 0:
        # ⚠️ Sem Acessibilidade o System Events recusa (erro 1002/-1719) — o texto do erro
        # vem traduzido; o que decide é o código de saída.
        log.warning("osascript recusou (%s): %s", r.returncode, (r.stderr or "").strip())
    return r.returncode == 0


def _trazer_mc_mac() -> bool:
    """O MC para a frente — o nome do processo é constante deste módulo, nunca texto de fora."""
    r = _osascript(f'tell application "System Events" to set frontmost of process "{PROCESSO_MC_MAC}" to true')
    if r.returncode != 0:
        log.warning("osascript não trouxe o MC (%s): %s", r.returncode, (r.stderr or "").strip())
    return r.returncode == 0


# ── a ação ──────────────────────────────────────────────────────────────────────────────

def em_primeiro_plano() -> str:
    """Quem está na frente agora — para o painel dizer a verdade quando não for o MC."""
    try:
        return _primeiro_plano_win() if E_WINDOWS else _primeiro_plano_mac() if E_MACOS else ""
    except Exception:  # noqa: BLE001
        log.debug("não consegui saber a janela da frente", exc_info=True)
        return ""


def copiar_selecao(pausa: float = 0.3, trazer_mc: bool = False) -> None:
    """Foca a timeline e copia a seleção do editor. Levanta `TecladoIndisponivel` com o motivo.

    ⚠️ Não diz se ALGO foi copiado: sem seleção, o Avid mantém a cópia anterior (medido). Quem
    chama compara com a última coleta (`carta_aberta.insert.impressao_digital`).
    """
    if not disponivel():
        raise TecladoIndisponivel("coletar a seleção ainda não funciona neste sistema")
    alvo = PROCESSO_MC_WIN if E_WINDOWS else PROCESSO_MC_MAC
    if trazer_mc and E_MACOS and alvo.lower() not in em_primeiro_plano().lower():
        if not _trazer_mc_mac():
            raise TecladoIndisponivel("não consegui trazer o Media Composer para a frente — dê ao De Lá Pra Cá "
                                      "a permissão de Acessibilidade (Ajustes › Privacidade e Segurança)")
        time.sleep(0.6)    # a janela troca depois de o System Events responder
    frente = em_primeiro_plano()
    if alvo.lower() not in frente.lower():
        raise TecladoIndisponivel("o Media Composer não está na frente — clique na timeline e "
                                  "aperte Coletar de novo")
    if E_WINDOWS:
        if not _atalho_win(VK_CONTROL, VK_0):
            raise TecladoIndisponivel("o Windows recusou o atalho de focar a timeline")
        time.sleep(pausa)
        if not _atalho_win(VK_CONTROL, VK_C):
            raise TecladoIndisponivel("o Windows recusou o atalho de copiar")
    else:
        if not (_atalho_mac("0") and (time.sleep(pausa) or True) and _atalho_mac("c")):
            raise TecladoIndisponivel("o macOS recusou o atalho — dê ao De Lá Pra Cá a "
                                      "permissão de Acessibilidade (Ajustes › Privacidade)")
    time.sleep(pausa)
