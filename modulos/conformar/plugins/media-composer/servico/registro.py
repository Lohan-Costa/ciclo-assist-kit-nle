"""O log do motor: um arquivo só, com rotação e um cabeçalho de ambiente a cada execução.

Organograma de cache e logs aprovado pelo autor em 2026-10-05 (decisão 4), portado do Órbita
(`DRAMASYNC/src-python/registro.py`).

Até a v0.1.76 era um arquivo POR DIA (`logs/delapraca-AAAAMMDD.log`), sem dizer em que máquina
rodou. Dois custos, os mesmos que o Órbita pagou: achar o arquivo certo dependia de acertar o dia,
e o arquivo achado não respondia "aqui, por quê" — nem versão, nem SO, nem NLE, nem onde estavam
o ffprobe e o cache. Agora é `Logs/delapraca.log`, e cada execução começa por um cabeçalho: achar
a execução certa é procurar o cabeçalho mais próximo do horário. Os arquivos antigos, por dia,
ficam onde estão (no Windows, `logs` e `Logs` são a mesma pasta).

⚠️ A rotação FALHA CALADA no Windows: com o arquivo aberto por outro processo (duas instâncias,
um editor de texto), o `os.rename` do rollover levanta `PermissionError`. Perder o log por causa
da manutenção dele seria o contrário do objetivo: o arquivo passa do teto e segue.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path

import plataforma

#: 4 MB × (1 + 4 guardados) ≈ 20 MB no disco (o "≈ 20 MB" do organograma).
TETO_BYTES = 4 * 1024 * 1024
GUARDADOS = 4
#: ⚠️ Nome FIXO: não volte a pôr a data aqui (ver a docstring).
NOME = "delapraca.log"
FORMATO = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_configurado: Path | None = None


class _RotativoTolerante(logging.handlers.RotatingFileHandler):
    """`RotatingFileHandler` que continua escrevendo quando o rollover não dá (ver a docstring)."""

    def doRollover(self) -> None:  # noqa: N802 — nome da stdlib
        try:
            super().doRollover()
        except OSError:
            # `super()` fecha o stream antes de renomear: sem reabrir, toda linha seguinte viraria
            # `ValueError: I/O operation on closed file`, e o log morreria calado.
            if self.stream is None:
                try:
                    self.stream = self._open()
                except OSError:
                    pass


def caminho(pasta: Path | None = None) -> Path:
    return Path(pasta or plataforma.pasta_logs()) / NOME


def configurar(origem: str, versao: str, pasta: Path | None = None) -> Path:
    """Liga o arquivo e escreve o cabeçalho. Idempotente. Levanta `OSError` se não deu para criar
    a pasta — quem chama segue só no terminal."""
    global _configurado
    if _configurado is not None:
        return _configurado
    alvo = caminho(pasta)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    h = _RotativoTolerante(alvo, maxBytes=TETO_BYTES, backupCount=GUARDADOS, encoding="utf-8")
    h.setFormatter(logging.Formatter(FORMATO))
    raiz = logging.getLogger()
    raiz.addHandler(h)
    raiz.setLevel(min(raiz.level, logging.INFO))       # o padrão da raiz (WARNING) calaria o cabeçalho
    _configurado = alvo
    for linha in cabecalho(origem, versao):
        logging.getLogger("delapraca").info(linha)
    return alvo


def _ffprobe() -> str:
    """O ffprobe que o motor USA (`fftools`: o embarcado no motor montado, o PATH no desenvolvimento)."""
    try:
        from media import fftools

        return fftools.ffprobe() or "(NÃO encontrado)"
    except Exception:  # noqa: BLE001 — o cabeçalho nunca derruba o arranque
        return shutil.which("ffprobe") or "(NÃO encontrado)"


def cabecalho(origem: str, versao: str) -> list[str]:
    """As linhas de ambiente. O critério é o relato de campo: cada uma responde uma pergunta que
    já custou uma ida e volta — versão e SO dizem QUAL De Lá Pra Cá; a origem diz para qual NLE
    (o MC, o receptor do Resolve, a bancada); o ffprobe porque "timeline offline" já foi ffprobe
    fora do PATH (macOS, 2026-10-04); e o cache porque ele é configurável."""
    import cache

    try:
        pasta_cache = cache.raiz()
    except Exception:  # noqa: BLE001 — o cabeçalho nunca derruba o arranque
        pasta_cache = "?"
    return [
        "=" * 72,
        f"De Lá Pra Cá {versao} — nova execução ({origem}) em "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  SO: {platform.system()} {platform.release()} ({platform.machine()}) · "
        f"Python {platform.python_version()} · PID {os.getpid()}"
        f"{' · empacotado' if getattr(sys, 'frozen', False) else ''}",
        f"  ffprobe={_ffprobe()}",
        f"  dados={plataforma.pasta_dados()} · cache={pasta_cache}",
        "=" * 72,
    ]
