"""
Relinker — Instrumentação de benchmark / cronometragem.

Mede o tempo das ações do sidecar (scan de mídia, match de segmentos, extração de
frame, parse, relink, export…) para testes de desempenho. **Opt-in**: desligado por
padrão; ligado pela toggle das Configurações (comando `set_benchmark`). Quando
desligado, `record`/`span` são praticamente no-ops (custo desprezível — algumas
chamadas de `perf_counter` — e evitam ruído no log).

Saída: uma linha JSON por medição em
`~/Library/Application Support/<App>/logs/bench_YYYYMMDD_HHMMSS.jsonl`
(e também ecoada no log principal com a tag [BENCH]). JSONL é trivial de agregar
(ex.: `jq -s 'group_by(.event) | map({event:.[0].event, n:length, total:(map(.ms)|add)})'`).
"""

import json
import time
import logging
import threading
from pathlib import Path

log = logging.getLogger("relinker.bench")

_enabled = False
_log_dir = None
_fh = None
_lock = threading.Lock()


def configure(log_dir) -> None:
    """Define a pasta onde o arquivo de benchmark será criado (no 1º enable)."""
    global _log_dir
    _log_dir = log_dir


def set_enabled(on: bool) -> None:
    """Liga/desliga a medição em runtime (comando `set_benchmark`).
    Abre o arquivo .jsonl preguiçosamente no primeiro enable."""
    global _enabled, _fh
    on = bool(on)
    with _lock:
        if on and _fh is None and _log_dir is not None:
            try:
                Path(_log_dir).mkdir(parents=True, exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                _fh = open(Path(_log_dir) / f"bench_{ts}.jsonl", "a", encoding="utf-8")
            except OSError as e:
                log.warning("Não foi possível abrir o arquivo de benchmark: %s", e)
        _enabled = on
    log.info("Benchmark %s", "LIGADO" if on else "desligado")


def enabled() -> bool:
    return _enabled


def record(event: str, elapsed_ms: float, **fields) -> None:
    """Registra uma medição (no-op se desligado)."""
    if not _enabled:
        return
    rec = {"t": round(time.time(), 3), "event": event,
           "ms": round(float(elapsed_ms), 2), **fields}
    try:
        line = json.dumps(rec, ensure_ascii=False)
    except (TypeError, ValueError):
        line = json.dumps({"event": event, "ms": round(float(elapsed_ms), 2)})
    with _lock:
        if _fh is not None:
            try:
                _fh.write(line + "\n")
                _fh.flush()
            except OSError:
                pass
    log.info("[BENCH] %s", line)


class span:
    """Context manager: mede o bloco e registra ao sair. Use `.set(**campos)` para
    anexar campos conhecidos só durante a execução (ex.: o decoder usado).

        with bench.span("frame", file=name) as b:
            ...
            b.set(decoder="ffmpeg", cached=False)
    """
    __slots__ = ("event", "fields", "_t")

    def __init__(self, event: str, **fields):
        self.event = event
        self.fields = fields
        self._t = 0.0

    def set(self, **fields):
        self.fields.update(fields)
        return self

    def __enter__(self):
        self._t = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        if _enabled:
            record(self.event, (time.perf_counter() - self._t) * 1000.0,
                   ok=(exc_type is None), **self.fields)
        return False
