"""O áudio de um master: dos arquivos OP-Atom para um WAV que o ASR entende.

⚠️ **OP-Atom guarda um canal por ARQUIVO.** Um som direto de 5 canais são cinco `.mxf`, e
nenhum deles é "o áudio do take" — cada um é uma pista. Juntar é trabalho nosso, e é aqui.

⭐ O WAV sai em **16 kHz mono**, que é o que o Whisper consome nativamente. Entregar 48 kHz
estéreo faria a biblioteca reamostrar por dentro, gastando tempo e memória para chegar no
mesmo lugar.
"""

from __future__ import annotations

import logging
import subprocess
from fractions import Fraction
from pathlib import Path

from .. import binarios as _binarios

log = logging.getLogger("cicloassist.midia.audio")

TAXA_DO_ASR = 16000

#: Vai na assinatura do gerador: mudou aqui, a transcrição guardada deixa de servir.
ASSINATURA_MIXAGEM = {"taxa": TAXA_DO_ASR, "canais": 1, "modo": "mixagem"}


class FfmpegAusente(RuntimeError):
    """O ffmpeg não está instalado. É pré-requisito do produto."""


class ExtracaoFalhou(RuntimeError):
    pass


def achar_ffmpeg() -> str:
    caminho = _binarios.achar("ffmpeg")
    if not caminho:
        raise FfmpegAusente(
            f"O ffmpeg não foi encontrado nesta máquina (procurei {_binarios.onde_procurei()}). "
            "Ele é necessário para o Ciclo Assist ouvir o material."
        )
    return caminho


def mixar(arquivos: list[str | Path], destino: Path) -> Path:
    """Junta os canais OP-Atom num WAV mono 16 kHz.

    ⚠️ **`amix` normaliza por padrão e isso ARRUINA a transcrição.** Com `normalize=1`, o
    ffmpeg divide cada entrada pelo número de entradas — um som de 5 canais em que só a
    lapela do ator tem voz sai com um quinto do volume, e o Whisper devolve silêncio ou
    texto picado. `normalize=0` soma as pistas; o `dynaudnorm` depois recupera o nível de
    forma controlada.

    ⚠️ E os canais VAZIOS não são inofensivos: som direto costuma ter pistas de reserva
    gravadas em ruído de fundo. Somadas sem normalização, elas viram chiado — por isso o
    `dynaudnorm`, e não um ganho fixo.
    """
    ffmpeg = achar_ffmpeg()
    entradas: list[str] = []
    for a in arquivos:
        entradas += ["-i", str(a)]

    n = len(arquivos)
    pistas = _pistas_de_audio(arquivos[0]) if n == 1 else 1
    if n == 1 and pistas > 1:
        # ⛔⛔ Arquivo AMA com várias pistas num arquivo só. MEDIDO em 2026-09-13: o `.mov`
        #    do RED tem QUATRO streams de áudio mono, e sem `-map` o ffmpeg pega só a
        #    primeira. Ali as pistas 3 e 4 eram silêncio e passaria por acaso; num
        #    documentário com a lapela na pista 3 da câmera, a fala do entrevistado some
        #    da transcrição sem erro nenhum. Mesma regra dos canais OP-Atom: soma de tudo.
        rotulos = "".join(f"[0:a:{i}]" for i in range(pistas))
        filtro = (
            f"{rotulos}amix=inputs={pistas}:duration=longest:normalize=0,"
            f"aresample={TAXA_DO_ASR},dynaudnorm"
        )
    elif n == 1:
        filtro = "aresample=" + str(TAXA_DO_ASR) + ",dynaudnorm"
    else:
        filtro = (
            f"amix=inputs={n}:duration=longest:normalize=0,"
            f"aresample={TAXA_DO_ASR},dynaudnorm"
        )

    destino.parent.mkdir(parents=True, exist_ok=True)
    comando = [
        ffmpeg, "-v", "error", "-y",
        *entradas,
        "-filter_complex", filtro,
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(destino),
    ]
    r = subprocess.run(comando, capture_output=True, timeout=900)
    if r.returncode != 0 or not destino.is_file():
        erro = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise ExtracaoFalhou(f"não consegui montar o áudio: {erro[:400]}")
    log.info("áudio pronto: %s (%d canal(is))", destino.name, n)
    return destino


def _pistas_de_audio(arquivo: str | Path) -> int:
    """Quantos streams de áudio o arquivo tem. OP-Atom tem um; um `.mov` AMA pode ter vários.

    Sem `ffprobe`, ou se ele falhar, responde 1 — que é o comportamento de antes, e não
    impede de transcrever a primeira pista.
    """
    ffprobe = _binarios.achar("ffprobe")
    if not ffprobe:
        # ⚠️ Não calado: com o ffmpeg achado e o ffprobe não, um `.mov` de quatro pistas
        #    viraria transcrição só da primeira sem ninguém saber por quê.
        log.warning("ffprobe ausente: %s vai ser ouvido só pela primeira pista", arquivo)
        return 1
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(arquivo)],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return 1
    return max(1, len([l for l in r.stdout.split() if l.strip()]))


def segundos_do_frame(frame: int, taxa: Fraction) -> float:
    """⚠️ Racional até o fim. Em 4 minutos, arredondar 23,976 desloca a fala."""
    return float(frame / taxa)
