"""Pegar a janela do Ciclo Assist TRAVADA no ato — e guardar onde ela parou.

⭐ Por que existe (2026-10-29, `docs/plano/2026-10-29-preferencias-e-a-janela-travada.md`): a
janela do app ficou "não respondendo" (`IsHungAppWindow`) depois de um conform, e nada
registrou o momento — o Windows não gravou evento, os logs do serviço e do De Lá Pra Cá
ficaram mudos, e três tentativas de reproduzir falharam. Sem saber ONDE a thread da janela
estava presa, a causa é palpite.

O serviço já vigia o app pelo `--pai` (`aplicativo.vigiar`). Este vigia faz a outra pergunta:
o app está VIVO, mas a janela dele RESPONDE? A cada `INTERVALO_S` um `WM_NULL` com prazo
(`SendMessageTimeout` + `SMTO_ABORTIFHUNG` — a mesma régua do Windows para "não respondendo").
Presa por mais de `LIMITE_S`, o vigia grava um **minidump** do processo (`MiniDumpWriteDump`,
com as pilhas de todas as threads) em `logs/travamentos/` e diz no log. Voltou a responder,
diz quanto tempo ficou presa. Um dump por episódio.

⚠️ Só Windows: é onde o travamento foi visto, e as chamadas são da `user32`/`dbghelp`.
No Mac o vigia não liga (`pendente` na matriz de plataforma).
⚠️ O vigia NUNCA mexe na janela: `WM_NULL` não faz nada; o dump só lê a memória do processo.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger("cicloassist.travamento")

#: De quanto em quanto tempo pergunta à janela (um `WM_NULL`: custo nenhum).
INTERVALO_S = 5.0

#: Com a janela já sem responder, pergunta de novo neste ritmo — para o dump sair perto do limite,
#: e não um intervalo inteiro depois.
RECHECAR_S = 2.0

#: Quanto a janela pode ficar sem responder antes de virar travamento. ⛔ Era 15 s (2026-10-30):
#: quem vê a janela congelada a mata em ~10 s, e o dump nunca saía. O Windows marca "não
#: respondendo" aos 5 s; 8 s ainda separa a pausa curta do preso. Um alarme falso custa ~1 MB.
LIMITE_S = 8.0

#: Quantos dumps (com o `.exe`/`.pdb` de cada um) ficam guardados; os mais velhos saem.
MANTER = 10

#: O prazo de cada pergunta.
PRAZO_DA_PERGUNTA_MS = 3000

#: A classe da janela principal do Tauri (o piloto a vê assim: `Tauri Window`).
CLASSE_DA_JANELA = "Tauri Window"


def pasta_dos_dumps() -> Path:
    from .diario import pasta
    return pasta() / "travamentos"


# ── as chamadas do Windows ────────────────────────────────────────────────────────────────────

def _janelas_do_processo(pid: int) -> list[int]:
    """As janelas principais (`Tauri Window`) do processo `pid`."""
    from ctypes import wintypes as W
    u = ctypes.windll.user32
    achadas: list[int] = []
    PROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

    def cada(h, _):
        dono = W.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(dono))
        if dono.value == pid:
            classe = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(h, classe, 64)
            if classe.value == CLASSE_DA_JANELA:
                achadas.append(int(h))
        return True

    u.EnumWindows(PROC(cada), 0)
    return achadas


def responde(hwnd: int, prazo_ms: int = PRAZO_DA_PERGUNTA_MS) -> bool:
    """A janela processou um `WM_NULL` dentro do prazo?"""
    from ctypes import wintypes as W
    u = ctypes.windll.user32
    u.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT,
                                      ctypes.POINTER(ctypes.c_size_t)]
    u.SendMessageTimeoutW.restype = ctypes.c_size_t
    resultado = ctypes.c_size_t()
    SMTO_ABORTIFHUNG = 0x0002
    return bool(u.SendMessageTimeoutW(hwnd, 0, 0, 0, SMTO_ABORTIFHUNG, prazo_ms,
                                      ctypes.byref(resultado)))


def gravar_dump(pid: int, destino: Path) -> Path:
    """Um minidump do processo `pid`, com as pilhas das threads. Levanta `OSError` se falhar."""
    from ctypes import wintypes as W
    k = ctypes.windll.kernel32
    dbg = ctypes.windll.dbghelp
    k.OpenProcess.restype = W.HANDLE
    k.CreateFileW.restype = W.HANDLE
    dbg.MiniDumpWriteDump.argtypes = [W.HANDLE, W.DWORD, W.HANDLE, ctypes.c_int,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    PROCESS_QUERY_INFORMATION, PROCESS_VM_READ, PROCESS_DUP_HANDLE = 0x0400, 0x0010, 0x0040
    # Normal + dados das threads + handles + módulos descarregados + info de memória: as pilhas e
    # o suficiente para ler onde cada thread está, em poucos MB (o dump COMPLETO teria centenas).
    TIPO = 0x0000 | 0x0004 | 0x0020 | 0x0100 | 0x0800 | 0x1000
    destino.parent.mkdir(parents=True, exist_ok=True)
    processo = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_DUP_HANDLE,
                             False, pid)
    if not processo:
        raise OSError(f"não consegui abrir o processo {pid} (erro {k.GetLastError()})")
    try:
        GENERIC_WRITE, CREATE_ALWAYS = 0x40000000, 2
        arquivo = k.CreateFileW(str(destino), GENERIC_WRITE, 0, None, CREATE_ALWAYS, 0x80, None)
        if not arquivo or arquivo == W.HANDLE(-1).value:
            raise OSError(f"não consegui criar {destino} (erro {k.GetLastError()})")
        try:
            if not dbg.MiniDumpWriteDump(processo, pid, arquivo, TIPO, None, None, None):
                raise OSError(f"MiniDumpWriteDump falhou (erro {k.GetLastError()})")
        finally:
            k.CloseHandle(arquivo)
    finally:
        k.CloseHandle(processo)
    return destino


def _guardar_os_simbolos(dump: Path) -> None:
    """Copia o `.exe` e o `.pdb` do app que estava rodando para a pasta do dump.

    ⛔ MEDIDO (2026-10-30): o dump lido com o `.pdb` de uma build mais nova mostra só
    `cicloassist+0x1ef190`, sem o nome da função — e no desenvolvimento a build muda o tempo
    todo (`abrir.ps1` recompila a cada abertura). Guardados ao lado, o dump se lê sempre.
    """
    import shutil

    from . import aplicativo

    exe = aplicativo._exe   # o --app, conferido no arranque
    if not exe:
        return
    destino = dump.with_suffix("")
    destino.mkdir(exist_ok=True)
    for origem in (Path(exe), Path(exe).with_suffix(".pdb")):
        try:
            shutil.copy2(origem, destino / origem.name)
        except OSError as e:
            log.warning("não guardei %s junto do dump: %s", origem.name, e)


def _lido(dump: Path) -> Path:
    return dump.with_suffix(".lido")


def marcar_lido(dump: Path) -> None:
    """O dump foi lido (por `tools/ler_travamento.py`): sai do aviso do painel."""
    _lido(dump).write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")


def nao_lidos(pasta: Path | None = None) -> list[dict]:
    """Os travamentos que ninguém leu ainda, do mais velho ao mais novo: `{arquivo, quando}`.

    ⭐ Por que existe (2026-10-30): o dump ia para uma pasta e ficava lá. Se o editor só fechasse
    o app travado e seguisse o dia, o travamento seguinte também não chegaria a ninguém — e é
    um defeito que reproduz raramente. O painel mostra esta lista ao abrir.
    """
    pasta = pasta or pasta_dos_dumps()
    try:
        dumps = [p for p in pasta.glob("*.dmp") if not _lido(p).exists()]
    except OSError:
        return []
    return [{"arquivo": p.name, "quando": p.stat().st_mtime}
            for p in sorted(dumps, key=lambda p: p.stat().st_mtime)]


def podar(pasta: Path | None = None, manter: int = MANTER) -> list[Path]:
    """Deixa só os `manter` dumps mais recentes (com a pasta de símbolos e a marca de lido)."""
    import shutil
    pasta = pasta or pasta_dos_dumps()
    dumps = sorted(pasta.glob("*.dmp"), key=lambda p: p.stat().st_mtime, reverse=True)
    saiu = []
    for velho in dumps[manter:]:
        for coisa in (velho, _lido(velho)):
            coisa.unlink(missing_ok=True)
        shutil.rmtree(velho.with_suffix(""), ignore_errors=True)
        saiu.append(velho)
    return saiu


# ── o vigia ───────────────────────────────────────────────────────────────────────────────────

class Vigia:
    """A conta de um episódio: quando a janela parou de responder e se o dump já saiu.

    Separado das chamadas do Windows para ser testado sem janela nenhuma.
    """

    def __init__(self, pid: int, limite_s: float = LIMITE_S,
                 achar: Callable[[int], list[int]] = _janelas_do_processo,
                 perguntar: Callable[[int], bool] = responde,
                 despejar: Callable[[int, Path], Path] = gravar_dump,
                 agora: Callable[[], float] = time.monotonic) -> None:
        self.pid, self.limite_s = pid, limite_s
        self._achar, self._perguntar, self._despejar, self._agora = achar, perguntar, despejar, agora
        self.presa_desde: float | None = None
        self.despejou = False
        self.dumps: list[Path] = []

    def olhar(self) -> str:
        """Uma passada. Devolve o que viu: sem_janela · ok · lenta · travada · voltou."""
        janelas = self._achar(self.pid)
        if not janelas:
            return "sem_janela"
        perguntou_em = self._agora()          # a janela já não respondia quando a pergunta SAIU
        if all(self._perguntar(h) for h in janelas):
            if self.presa_desde is not None:
                presa = self._agora() - self.presa_desde
                log.warning("a janela do app (pid %d) voltou a responder depois de %.0f s presa%s",
                            self.pid, presa, " — o dump está em " + str(self.dumps[-1])
                            if self.despejou and self.dumps else "")
                self.presa_desde, self.despejou = None, False
                return "voltou"
            return "ok"
        agora = self._agora()
        if self.presa_desde is None:
            self.presa_desde = perguntou_em
            log.warning("a janela do app (pid %d) não respondeu em %d ms", self.pid, PRAZO_DA_PERGUNTA_MS)
            return "lenta"
        if agora - self.presa_desde < self.limite_s or self.despejou:
            return "travada" if self.despejou else "lenta"
        self.despejou = True
        nome = time.strftime("%Y%m%d-%H%M%S") + f"_cicloassist_{self.pid}.dmp"
        try:
            caminho = self._despejar(self.pid, pasta_dos_dumps() / nome)
            self.dumps.append(caminho)
            _guardar_os_simbolos(caminho)
            for velho in podar():
                log.info("dump antigo removido (guardo os %d mais recentes): %s", MANTER, velho.name)
            log.error("⛔ a janela do app (pid %d) está TRAVADA há %.0f s — minidump em %s",
                      self.pid, agora - self.presa_desde, caminho)
        except OSError as e:
            log.error("⛔ a janela do app (pid %d) está TRAVADA há %.0f s, e o dump falhou: %s",
                      self.pid, agora - self.presa_desde, e)
        return "travada"


def vigiar(pid: int, parar: threading.Event, intervalo_s: float = INTERVALO_S) -> threading.Thread | None:
    """Liga o vigia da janela do app `pid` numa thread. Fora do Windows, não liga."""
    if sys.platform != "win32":
        return None
    vigia = Vigia(pid)

    def laco() -> None:
        while not parar.wait(RECHECAR_S if vigia.presa_desde is not None else intervalo_s):
            try:
                vigia.olhar()
            except Exception:  # noqa: BLE001 — o vigia nunca derruba o serviço
                log.exception("o vigia da janela falhou numa passada")

    t = threading.Thread(target=laco, name="vigia-da-janela", daemon=True)
    t.start()
    log.info("vigiando se a janela do app (pid %d) responde, a cada %.0f s", pid, intervalo_s)
    return t
