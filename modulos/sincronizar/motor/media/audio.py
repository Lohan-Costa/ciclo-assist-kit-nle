"""
Sincronizar — extração de PCM mono para cross-correlação de waveform.

Usa ffmpeg para converter qualquer mídia (MOV, WAV, MP4 …) para PCM 32-bit float
mono a 8 kHz. A taxa baixa reduz a memória e a CPU sem perder precisão de sync
(resolução de 1/8000 s ≈ 0,125 ms, muito abaixo de um frame a 24fps ≈ 41 ms).

LER O ARQUIVO INTEIRO É CARO, E QUASE SEMPRE DESNECESSÁRIO
──────────────────────────────────────────────────────────
O áudio de uma câmera vive INTERLEAVADO com o vídeo. Para pegar 47 s de áudio de
um MXF ProRes, o ffmpeg atravessa os 2,4 GB do arquivo — 9 s num disco rápido. Uma
diária de Alexa (42 clipes, 202 GB) levava 18 MINUTOS só nisto.

`extract_pcm_window` lê só o trecho pedido. O custo é proporcional à JANELA, não ao
arquivo (medido, a frio: 5 s → 1,0 s; 10 s → 2,0 s; 20 s → 4,1 s; inteiro → 11,7 s).
Quando o timecode já diz onde o clipe cai, uma janela basta para CONFERIR — e é o
que o engine faz. Ver `sync/waveform.confirm_offset`.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import fftools, safepath

PCM_RATE = 8000   # Hz — resolução suficiente para sync; muda só aqui se precisar


def _run(cmd: list[str], path: str) -> np.ndarray:
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        # O stderr do ffmpeg e o caminho absoluto vão para o LOG (do dono da
        # máquina), não para a exceção — ela sobe até o cliente HTTP, e ali o
        # caminho entrega o nome de usuário e confirma o que existe no disco.
        logging.getLogger(__name__).error(
            "ffmpeg falhou em %s: %s", path, result.stderr.decode(errors="replace")[-2000:]
        )
        raise RuntimeError("não consegui ler o áudio deste arquivo")
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def extract_pcm(path: str | Path, channel: int = 0) -> np.ndarray:
    """
    Extrai o canal `channel` (0-based) de `path` como array float32 mono a PCM_RATE Hz.

    Lê o arquivo INTEIRO — caro em mídia de câmera (ver o cabeçalho do módulo).
    Preferir `extract_pcm_window` sempre que se souber onde olhar.
    """
    path = str(Path(path))
    return _run([
        fftools.ffmpeg(), "-v", "error",
        "-i", safepath.ff_input(path),
        "-af", f"pan=mono|c0=c{int(channel)}",
        "-ar", str(PCM_RATE), "-ac", "1",
        "-f", "f32le", "-vn",
        "pipe:1",
    ], path)


def extract_pcm_window(
    path: str | Path, start_s: float, dur_s: float, channel: int = 0
) -> np.ndarray:
    """
    O mesmo, mas só de `[start_s, start_s + dur_s)`.

    `-ss` ANTES do `-i` é busca rápida — e, no ffmpeg moderno, **exata à amostra**
    (medido contra a extração integral: deslocamento zero, correlação 1,0000, em
    MXF/ProRes, mp4/AAC e WAV). Isso é load-bearing: se a janela não começasse na
    amostra pedida, o offset medido nela estaria errado pelo mesmo tanto.

    Perto do fim do arquivo o ffmpeg simplesmente devolve menos amostras — quem
    chama confere o tamanho.
    """
    path = str(Path(path))
    if dur_s <= 0:
        return np.zeros(0, dtype=np.float32)
    return _run([
        fftools.ffmpeg(), "-v", "error",
        "-ss", f"{max(0.0, start_s):.6f}",
        "-t", f"{dur_s:.6f}",
        "-i", safepath.ff_input(path),
        "-af", f"pan=mono|c0=c{int(channel)}",
        "-ar", str(PCM_RATE), "-ac", "1",
        "-f", "f32le", "-vn",
        "pipe:1",
    ], path)


def peak_abs(pcm: np.ndarray) -> float:
    """
    Pico absoluto do sinal — 0.0 quando não há amostra nenhuma.

    Existe para que `np.max` nunca veja uma array VAZIA. O numpy, nesse caso, não
    devolve zero: ele levanta

        ValueError: zero-size array to reduction operation maximum which has no identity

    que é uma mensagem verdadeira e completamente inútil para um editor lendo a tela
    do app. Ver `normalize` logo abaixo para o caso real que produziu isso.
    """
    return float(np.max(np.abs(pcm))) if pcm.size else 0.0


def normalize(pcm: np.ndarray) -> np.ndarray:
    """
    Normaliza para pico 1.0; retorna array de zeros se silêncio, e a própria array
    vazia se não houver amostra nenhuma.

    ⚠️ O CASO REAL QUE ISTO GUARDA: um gravador de campo que começa e para a
    gravação no mesmo instante deixa em disco um WAV de **44 bytes** — só o
    cabeçalho, com o chunk `data` de tamanho zero. É um arquivo válido, o probe lê
    o sample rate e os canais direitinho, e ele passava por todos os filtros. Só que
    a extração devolve ZERO amostras, e o `np.max` sobre isso derrubava o sync
    INTEIRO com a mensagem do numpy — o usuário via "zero-size array to reduction
    operation maximum which has no identity" e não tinha como saber que o problema
    era um arquivo de som vazio no meio de uma pasta com dezenas.
    (Visto em material real: `hl-2024-10-25/08-37-20.wav`, 44 bytes.)
    """
    peak = peak_abs(pcm)
    if peak < 1e-9:
        return np.zeros_like(pcm)
    return pcm / peak
