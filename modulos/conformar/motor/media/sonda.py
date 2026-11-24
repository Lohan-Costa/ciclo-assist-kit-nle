"""UMA leitura do ffprobe por arquivo, para todas as perguntas que o motor faz a ele (2026-10-04).

Antes, o caminho Premiere → Resolve abria cada arquivo QUATRO vezes no ffprobe, em três etapas:
o casamento com o original (`prproj.originais.sondar`: raster, codec, duração, TC), a leitura da
mídia e o pool do DRT (`drp.writer._media_meta`: taxa, quadros, TC — e de novo, no som, quando não
há vídeo; `_formato_meta`: tag do codec, raster, codec do som; `_audio_meta`: amostragem, canais,
amostras, `time_reference`). Cada abertura é um processo novo e uma ida ao disco.

Aqui sai a resposta CRUA (o JSON do ffprobe com os campos de todos), uma por arquivo; cada
pergunta tira dela o que precisa, com as mesmas regras de antes (o `-select_streams v:0` vira o
1º stream de vídeo, o `a:0` o 1º de áudio).

⚠️ Estouro de tempo NÃO vai para o cache e SOBE (`subprocess.TimeoutExpired`): disco lento não é
arquivo ilegível — quem chama decide (refazer sozinho, avisar). Outra falha (arquivo que o ffprobe
não lê) fica no cache como `{}`.
"""
from __future__ import annotations

import json
import subprocess
import threading

from media import fftools
from media.fftools import SEM_JANELA

#: Os campos das quatro perguntas, num pedido só.
CAMPOS = ("stream=index,codec_type,codec_name,codec_tag_string,width,height,r_frame_rate,avg_frame_rate,time_base,nb_frames,"
          "duration,sample_rate,channels,duration_ts:stream_tags=timecode,reel_name"
          ":format=duration:format_tags=timecode,time_reference,reel_name,tape_name")

#: Limite de uma leitura. Medido 2026-10-04: com o disco frio, um ARRIRAW passou de 40 s com 4
#: leituras simultâneas num HD USB.
LIMITE_S = 60

_CACHE: dict[str, dict] = {}
_TRAVA = threading.Lock()
#: Quantas leituras de verdade (processos do ffprobe) — para o perfil e o teste.
leituras = 0


def ler(caminho: str) -> dict:
    """O JSON do ffprobe (`{"streams": [...], "format": {...}}`) do arquivo; `{}` se ele não lê.
    Lança `subprocess.TimeoutExpired` sem guardar nada."""
    global leituras
    if caminho in _CACHE:
        return _CACHE[caminho]
    with _TRAVA:
        leituras += 1
    try:
        out = subprocess.run([fftools.ffprobe_exe(), "-v", "error", "-show_entries", CAMPOS, "-of", "json",
                              caminho], capture_output=True, text=True, timeout=LIMITE_S, **SEM_JANELA)
        j = json.loads(out.stdout or "{}")
        if not isinstance(j, dict):
            j = {}
    except subprocess.TimeoutExpired:
        raise
    except (OSError, ValueError, subprocess.SubprocessError):
        j = {}
    _CACHE[caminho] = j
    return j


def primeiro(j: dict, tipo: str) -> dict:
    """O 1º stream de `tipo` ("video" ou "audio") — o `-select_streams v:0`/`a:0` de antes."""
    return next((s for s in j.get("streams") or [] if s.get("codec_type") == tipo), {})


def _razao(txt) -> float | None:
    num, _, den = str(txt or "").partition("/")
    try:
        n, d = float(num), float(den or 1)
    except ValueError:
        return None
    return n / d if n > 0 and d > 0 else None


def taxa_variavel(caminho: str) -> tuple[float, float] | None:
    """`(taxa do cabeçalho, taxa média)` quando o vídeo tem taxa VARIÁVEL (a média difere do
    cabeçalho em mais de 0,1%), senão None. ⛔ Medido 2026-10-05 (Resolve 19, sintéticos com o
    número do quadro em código de barras): com taxa variável o Resolve conta o arquivo pela taxa
    do cabeçalho e não garante o quadro exato — irregular, chegou a 17 quadros de diferença."""
    v = primeiro(ler(caminho), "video")
    r, a = _razao(v.get("r_frame_rate")), _razao(v.get("avg_frame_rate"))
    # Taxa variável = quadros FALTANDO na grade do cabeçalho: a média fica ABAIXO dele. A média
    # ACIMA (o dobro, no MXF de vídeo do Avid: 11,988 no cabeçalho, 23,976 de média) é detalhe do
    # formato, não buraco — medido em 636 arquivos de 2026-10-05, só o vídeo de celular cai aqui.
    if r and a and a < r * (1 - 1e-3):
        return r, a
    return None


def esquecer(caminho: str) -> None:
    _CACHE.pop(caminho, None)
