"""O motor do Sincronizar chamado NO MESMO PROCESSO — o `sidecar.rs` do Órbita, sem o processo filho.

O motor (`modulos/sincronizar/motor/main.py`, o `src-python` do Órbita com o histórico) fala um protocolo de linhas
JSON: `handle_command({"id", "command", "params"})` responde escrevendo, por `_write_line`, `{"id","ok","data"}`,
`{"id","ok":false,"error","detail"}` ou eventos `{"id","event":"progress","data"}`. Aqui o `_write_line` dele é
trocado por um que entrega a linha a quem chamou — o motor não muda uma linha, e a suíte dele (940) continua valendo.

⭐ UM comando por vez, como no sidecar (o `Mutex` do `call_with_progress`): o motor nunca foi escrito para ser
chamado de duas threads, e é essa fila que faz o `waiting` do job existir ("esperando a vez" ≠ "travado").
⚠️ O que o sidecar tinha e isto não tem: o prazo de 300 s por comando (uma thread não se mata). Em troca não há mais
"o sidecar morreu e ninguém religou" — se o motor derrubar o processo, quem religa é o supervisor do app.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

MOTOR = Path(__file__).resolve().parent.parent / "motor"

_trava = threading.Lock()
_contador = 0
_contador_trava = threading.Lock()
#: id do comando → callback das linhas dele (só o comando em curso; a trava garante um por vez).
_ouvintes: dict[str, Callable[[dict], None]] = {}
_main = None
_carga = threading.Lock()
#: os binários para os quais não havia o fixado (o servidor diz no log que caiu no do sistema)
log_sem_fixado: list[str] = []


class ErroDoMotor(Exception):
    """O motor respondeu `ok: false` — a mensagem é a que o Rust montava (`erro` ou `erro: detalhe`)."""


BINARIOS = MOTOR.parent / "binarios"
_TRIPLE = {"darwin": "aarch64-apple-darwin", "win32": "x86_64-pc-windows-msvc"}


def fixado(nome: str) -> Optional[str]:
    """O ffmpeg/ffprobe FIXADO do motor (8.1.2, os do Órbita, `motor/fetch_ffmpeg.py` com o SHA-256), em
    `modulos/sincronizar/binarios/<nome>-<triple>`.

    ⛔⛔ MEDIDO (2026-11-07, PRODE 20240531, 162 clipes): com o ffmpeg 8.1.1 do Homebrew no lugar do 8.1.2 que o Rust
    entregava ao sidecar, uma câmera saiu com `confidence` 2,9539 em vez de 2,9546 — o Rust é determinístico
    (duas rodadas iguais). O offset bateu, mas a régua do sync é o decodificador: outro ffmpeg, outro número."""
    triple = _TRIPLE.get(sys.platform)
    if not triple:
        return None
    p = BINARIOS / f"{nome}-{triple}{'.exe' if sys.platform == 'win32' else ''}"
    return str(p) if p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK)) else None


def _achar(nome: str) -> Optional[str]:
    """ffmpeg/ffprobe: o FIXADO primeiro, depois o do sistema. ⛔ Lançado pelo app (Finder/launchd) o PATH é
    `/usr/bin:/bin:…` — sem os lugares de sempre, "ffmpeg não encontrado" com ele instalado (matriz de plataforma,
    PATH do serviço; o mesmo do `binarios.py`)."""
    achado = fixado(nome)
    if achado:
        return achado
    log_sem_fixado.append(nome)
    achado = shutil.which(nome)
    if achado:
        return achado
    if sys.platform != "win32":
        for d in ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin")):
            p = Path(d) / nome
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


def _ambiente(versao: str) -> None:
    """O que o Rust passava ao sidecar por variável de ambiente (`sidecar.rs::start`)."""
    os.environ.setdefault("SINC_VERSION", versao)
    for var, nome in (("SINC_FFMPEG", "ffmpeg"), ("SINC_FFPROBE", "ffprobe")):
        if not os.environ.get(var):
            p = _achar(nome)
            if p:
                os.environ[var] = p


def _entregar(linha: str) -> None:
    try:
        msg = json.loads(linha)
    except ValueError:
        return
    ouvinte = _ouvintes.get(str(msg.get("id")))
    if ouvinte is not None:
        ouvinte(msg)


def carregar(versao: str = "0.4.0") -> None:
    """Importa o motor (uma vez). Ele é uma RAIZ Python própria (importa `media`, `avid`, `sync` pelo nome de topo)."""
    global _main
    with _carga:  # o servidor carrega no fundo ao subir, e o primeiro pedido pode chegar antes de acabar
        if _main is not None:
            return
        _ambiente(versao)
        if str(MOTOR) not in sys.path:
            sys.path.insert(0, str(MOTOR))
        import main as m  # noqa: E402 — o `main.py` do motor
        m._write_line = _entregar
        _main = m


def chamar(comando: str, params: Any = None, ao_progresso: Callable[[Any], None] | None = None) -> Any:
    """Roda um comando do motor e devolve o `data`; `ErroDoMotor` se ele respondeu erro."""
    global _contador
    carregar()
    with _contador_trava:
        _contador += 1
        cid = f"py-{_contador}"
    final: dict = {}

    def ouvir(msg: dict) -> None:
        if msg.get("event") == "progress":
            if ao_progresso is not None:
                try:
                    ao_progresso(msg.get("data"))
                except Exception:  # um sink quebrado não derruba o comando
                    pass
            return
        final.update(msg)

    with _trava:
        _ouvintes[cid] = ouvir
        try:
            _main.handle_command({"id": cid, "command": comando, "params": params if params is not None else {}})
        except Exception:
            # o `main()` do motor fazia isto no laço; aqui quem chama é o servidor
            _main.log.exception("Erro inesperado no comando %s", comando)
            raise ErroDoMotor("Erro interno inesperado")
        finally:
            _ouvintes.pop(cid, None)
    if not final:
        raise ErroDoMotor(f"o motor não respondeu ao comando '{comando}'")
    if final.get("ok") is True:
        return final.get("data")
    if final.get("ok") is False:
        erro = final.get("error") or "Erro desconhecido"
        detalhe = final.get("detail") or ""
        raise ErroDoMotor(f"{erro}: {detalhe}" if detalhe else erro)
    raise ErroDoMotor(f"Resposta sem campo 'ok': {json.dumps(final, ensure_ascii=False)[:200]}")
