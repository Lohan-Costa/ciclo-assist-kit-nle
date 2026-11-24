"""
Sincronizar — o log do sidecar: um arquivo só, com rotação e cabeçalho de ambiente.

⛔ **POR QUE ESTE MÓDULO EXISTE, e é uma história de campo.**

Até 2026-08-23 o log era um `logging.basicConfig` no `main.py` que abria um arquivo
NOVO por execução (`sincronizar_<AAAAMMDD_HHMMSS>.log`). Duas consequências, as duas
descobertas quando um relato de campo precisou ser lido:

1. **achar o arquivo certo dependia de sorte** — a pasta enche, nada é apagado, e
   quem traz o relato precisa acertar o horário do teste no nome do arquivo;
2. **o arquivo achado não dizia em que máquina rodou** — nem versão, nem SO, nem
   onde estavam o ffmpeg e a pasta de cache. Um log sem ambiente responde "o que
   aconteceu" e não responde "aqui, por quê".

Agora é **um** `sincronizar.log` com rotação, e cada execução começa por um cabeçalho de
ambiente. Achar a execução certa virou procurar o cabeçalho mais próximo do horário,
dentro de um arquivo que sempre tem o mesmo nome.

⚠️ **A rotação FALHA CALADA de propósito no Windows.** Dois processos podem ter o
arquivo aberto ao mesmo tempo (o sidecar do app e um `tools/regua.py` rodando à
parte), e o `os.rename` do rollover levanta `PermissionError` quando isso acontece.
Derrubar o sidecar — ou pior, perder a linha que estava sendo escrita — por causa de
manutenção de arquivo de log seria desproporcional: o log serve ao diagnóstico, não
o contrário. Quando o rollover não dá, o arquivo simplesmente passa do teto.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

#: Teto por arquivo e quantos guardar. 4 MB × 5 arquivos ≈ 20 MB de log no disco.
#:
#: O número saiu do custo real de uma sessão: o instrumento da resolução de mídia
#: (`avid/`, `media/`) escreve algumas dezenas de linhas por comando, e uma diária
#: grande com varredura completa fica na casa das centenas. 4 MB guarda muitas
#: execuções; e cinco arquivos cobrem "aconteceu ontem e eu só fui olhar hoje".
TETO_BYTES = 4 * 1024 * 1024
GUARDADOS = 4

#: O nome fixo. ⚠️ **Não volte a pôr timestamp aqui** — ver a docstring do módulo.
NOME_DO_ARQUIVO = "sincronizar.log"

_configurado = False


class _RotativoTolerante(logging.handlers.RotatingFileHandler):
    """`RotatingFileHandler` que não derruba nada quando o rollover não dá.

    Ver a docstring do módulo: no Windows o arquivo pode estar aberto por outro
    processo, e aí o `os.rename` levanta. O comportamento escolhido é **continuar
    escrevendo no arquivo atual** — passar do teto é o preço, e é barato.
    """

    def doRollover(self) -> None:  # noqa: N802 (nome vem da stdlib)
        try:
            super().doRollover()
        except OSError:
            # `super()` fecha o stream antes de tentar renomear; se não reabrirmos,
            # toda linha seguinte desta execução vira `ValueError: I/O operation on
            # closed file` — e o log morre em silêncio, que é o oposto do objetivo.
            if self.stream is None:
                try:
                    self.stream = self._open()
                except OSError:
                    pass


def caminho_do_arquivo(dir_logs: Path | None = None) -> Path:
    if dir_logs is None:
        import appsettings

        dir_logs = appsettings.logs_dir()
    return Path(dir_logs) / NOME_DO_ARQUIVO


def configurar(origem: str = "sidecar", dir_logs: Path | None = None,
               nivel: int = logging.INFO) -> Path:
    """Liga o log no arquivo e escreve o cabeçalho de ambiente. Devolve o caminho.

    `origem` diz **quem** abriu esta execução (`sidecar`, `regua`, …). Um mesmo
    `sincronizar.log` recebe as duas coisas, e sem isso não há como saber se aquela
    varredura veio do app ou de uma ferramenta de linha de comando.

    Idempotente: chamar duas vezes não duplica handler nem cabeçalho.
    """
    global _configurado
    alvo = caminho_do_arquivo(dir_logs)
    if _configurado:
        return alvo

    alvo.parent.mkdir(parents=True, exist_ok=True)
    handler = _RotativoTolerante(
        alvo, maxBytes=TETO_BYTES, backupCount=GUARDADOS, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    raiz.addHandler(handler)
    _configurado = True

    for linha in cabecalho(origem):
        raiz.info(linha)
    return alvo


def cabecalho(origem: str) -> list[str]:
    """As linhas de ambiente que abrem cada execução.

    ⭐ **O critério do que entra aqui é o relato de campo**, não a curiosidade: cada
    linha responde a uma pergunta que já custou uma ida e volta com quem testou.
    Versão e SO dizem *qual* Órbita; `frozen` separa app instalado de dev (os dois
    resolvem caminho de jeitos diferentes); ffmpeg/ffprobe porque "não achou mídia"
    já foi ffprobe ausente; e o `cwd` porque caminho relativo em ferramenta de linha
    de comando depende dele.
    """
    import appsettings

    versao = os.environ.get("SINC_VERSION") or "?"
    congelado = "sim" if getattr(sys, "frozen", False) else "não (dev)"
    return [
        "=" * 72,
        f"Sincronizar {versao} — nova execução ({origem}) em "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  SO: {platform.system()} {platform.release()} ({platform.machine()}) · "
        f"Python {platform.python_version()} · empacotado: {congelado} · PID {os.getpid()}",
        f"  ffmpeg={os.environ.get('SINC_FFMPEG') or '(PATH)'} · "
        f"ffprobe={os.environ.get('SINC_FFPROBE') or '(PATH)'}",
        f"  dados={appsettings.app_data_dir()} · cwd={Path.cwd()}",
        "=" * 72,
    ]


def log(nome: str) -> logging.Logger:
    """O logger de um módulo. Use `registro.log(__name__)`.

    Todos pendem de `sincronizar.`, então um dia dá para baixar o nível de um subsistema
    só (`logging.getLogger("sincronizar.avid").setLevel(DEBUG)`) sem inundar o resto.

    ⚠️ Chamar isto num módulo NÃO liga o log — quem liga é o `configurar()`, uma vez,
    em quem tem o processo (`main.py`, `tools/regua.py`). Um módulo importado por um
    teste escreve para lugar nenhum, e é o que se quer: `pytest` não deve encostar em
    `%APPDATA%`.
    """
    if nome == "__main__":
        return logging.getLogger("sincronizar.main")
    return logging.getLogger(nome if nome.startswith("sincronizar") else f"sincronizar.{nome}")
