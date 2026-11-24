"""O laboratório de mídia da família, visto daqui: gerar um caso sintético por uma RECEITA.

Operação 1 do ensaio (`docs/plano/2026-10-31-operacoes-do-ensaio.md`). O laboratório
(`laboratorio-de-midia/`, ao lado do banco) gera a mídia por receita JSON e escreve, ao lado
dela, um `verdade.json` que diz em que instante da cena cada arquivo começa — é o gabarito
contra o qual o sync e os subclipes são conferidos depois.

⭐ **Quem é chamado é o gerador DELE** (`python -m lab.multicam <receita>`), num processo
filho: a receita e a física da cena são assunto do laboratório, e uma segunda cópia aqui
divergiria calada.

⛔⛔ **A receita é um NOME de caso, nunca um caminho** (ADR 0005): o modelo escreve o pedido,
e "gere a partir deste arquivo" seria ler a máquina por uma frase. Só vale o que está em
`receitas/multicam/`.

⛔⛔ **Gerar de novo NUNCA escreve por cima.** Os arquivos de um caso viram masters no Resolve
e no Media Composer (o M06 de 31/10 está linkado nos dois); regravá-los mudaria a mídia de um
projeto aberto por baixo dele. Pronto e mais novo que a receita = reaproveitado; `refazer`
gera numa pasta NOVA, com data e hora no nome.

⚠️ **O Python do laboratório não é necessariamente o nosso:** num Assist empacotado
(PyInstaller) `sys.executable` é o próprio app, e `[sys.executable, "-m", …]` subiria outro
serviço (banco, `matriz-de-plataforma.md`, linha do PyInstaller). Aí se procura um Python no
PATH. O gerador só usa a biblioteca padrão e o ffmpeg.
"""

from __future__ import annotations

import collections
import datetime
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger("cicloassist.laboratorio")

#: O nome da pasta do laboratório na raiz da família.
PASTA = "laboratorio-de-midia"

#: Sem uma linha do gerador por este tempo, ele é dado como travado e morto. É de PARADA,
#: não de duração: ele avisa a cada arquivo, e um ProRes 1080p de 30 s leva segundos.
SILENCIO_MAXIMO_S = 600


class LaboratorioIndisponivel(RuntimeError):
    """O laboratório não está ao alcance, ou a geração falhou — a frase vai ao modelo."""


def raiz(inicio: Path | None = None) -> Path | None:
    """A pasta do laboratório, achada SUBINDO de pasta (o app mora um ou dois níveis abaixo da
    raiz da família — `CLAUDE.md` da família), ou `None`."""
    aqui = (inicio or Path(__file__)).resolve()
    for p in [aqui, *aqui.parents]:
        candidato = p / PASTA
        if (candidato / "lab" / "multicam.py").is_file():
            return candidato
    return None


def _exigir_raiz() -> Path:
    r = raiz()
    if r is None:
        raise LaboratorioIndisponivel(
            f"Não achei a pasta '{PASTA}' subindo a partir do Ciclo Assist — o laboratório só "
            "existe na máquina de desenvolvimento, dentro do SSD da família.")
    return r


def na_saida(pasta: str | Path) -> bool:
    """A pasta está dentro da saída do laboratório? (é nossa: as ferramentas a aceitam sem arrasto)."""
    r = raiz()
    if r is None:
        return False
    try:
        Path(pasta).resolve().relative_to((r / "saida").resolve())
        return True
    except ValueError:
        return False


def receitas() -> dict[str, dict]:
    """{caso: {pergunta, fontes, arquivos, segundos}} das receitas multicam."""
    r = raiz()
    if r is None:
        return {}
    saida: dict[str, dict] = {}
    for arq in sorted((r / "receitas" / "multicam").glob("*.json")):
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fontes = d.get("fontes") or []
        saida[arq.stem] = {
            "pergunta": d.get("pergunta", ""),
            "fontes": [f.get("nome", "?") for f in fontes],
            "arquivos": sum(len(f.get("tomadas") or []) for f in fontes),
            "segundos": (d.get("cena") or {}).get("segundos"),
            "caminho": str(arq),
        }
    return saida


def pasta_padrao(caso: str) -> Path:
    return _exigir_raiz() / "saida" / "multicam" / caso


def pronto(caso: str, pasta: Path | None = None) -> bool:
    """A pasta tem um `verdade.json` mais novo que a receita (gerado depois da última mudança)."""
    rec = receitas().get(caso)
    verdade = (pasta or pasta_padrao(caso)) / "verdade.json"
    if not rec or not verdade.is_file():
        return False
    return verdade.stat().st_mtime >= Path(rec["caminho"]).stat().st_mtime


def _python() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    for nome in ("python3", "python", "py"):
        achado = shutil.which(nome)
        if achado:
            return achado
    raise LaboratorioIndisponivel("Não achei um Python nesta máquina para rodar o gerador do laboratório.")


def resumo(pasta: Path) -> dict[str, object]:
    """O que a `verdade.json` diz, enxuto para o modelo: um item por arquivo."""
    d = json.loads((pasta / "verdade.json").read_text(encoding="utf-8"))
    arquivos = [{
        "arquivo": a["arquivo"], "fonte": a["fonte"], "tomada": a["tomada"],
        "inicio_na_cena_s": a["inicio_na_cena_s"], "tc": a.get("tc"),
    } for a in d.get("arquivos", [])]
    return {"caso": d.get("caso"), "pasta": str(pasta), "gerado_em": d.get("gerado_em"),
            "cena_s": (d.get("cena") or {}).get("segundos"), "arquivos": arquivos}


def gerar(caso: str, *, refazer: bool = False,
          relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, object]:
    """Gera (ou reaproveita) o caso. Devolve o resumo da verdade e `como` (reaproveitado|gerado)."""
    relatar = relatar or (lambda *_: None)
    rec = receitas().get(caso)
    if rec is None:
        raise LaboratorioIndisponivel(f"Não há receita '{caso}'. Receitas: {', '.join(receitas()) or 'nenhuma'}.")
    lab = _exigir_raiz()
    pasta = pasta_padrao(caso)
    if not refazer and pronto(caso, pasta):
        return {**resumo(pasta), "como": "reaproveitado"}
    if pasta.exists() and any(pasta.iterdir()):
        # ⛔ nunca por cima: a pasta pode estar linkada num projeto aberto
        pasta = pasta.with_name(f"{caso}_{datetime.datetime.now():%Y%m%d-%H%M%S}")

    total = max(int(rec["arquivos"]), 1)
    ambiente = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    cmd = [_python(), "-m", "lab.multicam", rec["caminho"], "--saida", str(pasta)]
    log.info("laboratório: %s", cmd)
    inicio = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=lab, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=ambiente, text=True, encoding="utf-8",
                            errors="replace")
    fim_do_erro: collections.deque[str] = collections.deque(maxlen=30)
    # ⛔ o stderr DRENADO numa thread: sem ninguém lendo, o buffer enche e o filho para (CLAUDE.md)
    dreno = threading.Thread(target=lambda: fim_do_erro.extend(proc.stderr), daemon=True)
    dreno.start()
    ultima = [time.monotonic()]
    feitos = [0]

    def ler() -> None:
        for linha in proc.stdout:
            ultima[0] = time.monotonic()
            linha = linha.strip()
            if linha.startswith("gerando ") and not linha.endswith("_cena.wav)"):
                relatar(f"gerando a mídia de {caso}", min(feitos[0] / total, 0.99), linha[8:])
                feitos[0] += 1
            elif linha:
                relatar(f"gerando a mídia de {caso}", None, linha)

    leitor = threading.Thread(target=ler, daemon=True)
    leitor.start()
    while proc.poll() is None:
        if time.monotonic() - ultima[0] > SILENCIO_MAXIMO_S:
            proc.kill()
            raise LaboratorioIndisponivel(
                f"O gerador ficou {SILENCIO_MAXIMO_S // 60} min sem avisar nada e foi parado. "
                f"A pasta pela metade ficou em {pasta}.")
        time.sleep(0.5)
    leitor.join(2)
    dreno.join(2)
    if proc.returncode != 0 or not (pasta / "verdade.json").is_file():
        raise LaboratorioIndisponivel(
            f"O gerador saiu com {proc.returncode}: " + (" ".join(fim_do_erro)[-800:] or "sem mensagem"))
    return {**resumo(pasta), "como": "gerado", "segundos": round(time.monotonic() - inicio, 1)}
