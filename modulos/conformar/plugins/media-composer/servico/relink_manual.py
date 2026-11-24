"""Relink MANUAL: o editor diz qual arquivo vai no lugar de um master (autor, 2026-10-13).

"A palavra do editor se sobrepõe a qualquer regra automática, impedindo apenas se for impossível o relink." Nome
diferente, caracteres corrompidos, TC diferente, empate, uma convertida no lugar do original: tudo passa. A recusa é
só para o que o Avid não consegue fazer com aquele arquivo naquele lugar:

- o arquivo é mais curto que o trecho que a timeline usa dele (2:00 pedidos, 1:00 no arquivo);
- tipo trocado: na timeline o master dá imagem e o arquivo não tem vídeo, ou é só som e o arquivo não tem áudio;
- a timeline usa um canal de som que o arquivo não tem (usa A3, o arquivo tem 2).

O que não se sabe (o trecho usado atravessando um subclipe do AAF, os canais de um BRAW) NÃO recusa: o relink segue e,
se o MC recusar o arquivo, ele aparece em "Ficaram de fora" com o motivo do MC.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("delapraca.relink_manual")

# Até quantos frames a menos se aceita: o frame de guarda que o próprio Avid declara (o mesmo `TOLERANCIA_FRAMES` da
# injeção de áudio, `avb_bin/audio.py`). Além disso o arquivo não cobre o trecho.
TOLERANCIA_FRAMES = 2


def sondar(arquivo: str) -> dict:
    """`{tem_video, tem_audio, canais, duracao_s, codec}` do arquivo. Campo `None` = não deu para saber.

    ffprobe primeiro (vídeo comum e todo áudio); o que ele não abre — os RAW de câmera (BRAW, R3D…) — vai pelo
    leitor do indexador, que sabe a duração e a imagem, mas não os canais.
    """
    from media import fftools

    s = {"tem_video": None, "tem_audio": None, "canais": None, "duracao_s": None, "codec": ""}
    try:
        saida = subprocess.run(
            [fftools.ffprobe_exe(), "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,codec_name,channels,duration", "-of", "json", arquivo],
            capture_output=True, timeout=60, **fftools.SEM_JANELA)
        dados = json.loads(saida.stdout.decode("utf-8", "replace") or "{}")
    except Exception as e:  # noqa: BLE001
        log.info("ffprobe não leu %s: %s", arquivo, e)
        dados = {}
    streams = dados.get("streams") or []
    if streams:
        # imagem parada embutida (capa de mp3) não é vídeo
        video = [x for x in streams if x.get("codec_type") == "video" and x.get("codec_name") not in ("mjpeg", "png")]
        audio = [x for x in streams if x.get("codec_type") == "audio"]
        s["tem_video"] = bool(video)
        s["tem_audio"] = bool(audio)
        s["canais"] = sum(int(x.get("channels") or 0) for x in audio) if audio else 0
        s["codec"] = (video[0] if video else audio[0] if audio else {}).get("codec_name") or ""
        dur = (dados.get("format") or {}).get("duration")
        try:
            s["duracao_s"] = float(dur) if dur not in (None, "N/A") else None
        except ValueError:
            s["duracao_s"] = None
        return s
    try:
        from media.indexer import index_folder

        f = (index_folder([arquivo]).get("files") or [{}])[0]
        if f.get("duration_ms"):
            s["duracao_s"] = float(f["duration_ms"]) / 1000.0
        if f.get("width"):
            s["tem_video"] = True
        s["codec"] = f.get("codec_label") or f.get("codec") or ""
    except Exception as e:  # noqa: BLE001
        log.info("o indexador não leu %s: %s", arquivo, e)
    return s


def _tempo(segundos: float) -> str:
    s = max(0, int(round(segundos)))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def validar(master: dict, sonda: dict) -> tuple[bool, str]:
    """`(aceito, texto)`. Aceito: o texto diz o que foi conferido. Recusado: diz por que e o que fazer.

    `master` é a linha de `/trabalho/masters` (`usa_imagem`, `e_audio`, `canais_som`, `uso_frames`, `edit_rate`).
    """
    usa_imagem = bool(master.get("usa_imagem"))
    so_som = not usa_imagem and bool(master.get("e_audio"))
    if usa_imagem and sonda.get("tem_video") is False:
        return False, ("na timeline esta mídia é imagem e o arquivo escolhido não tem vídeo. "
                       "Escolha um arquivo de vídeo.")
    if so_som and sonda.get("tem_audio") is False:
        return False, "na timeline esta mídia é som e o arquivo escolhido não tem áudio. Escolha um arquivo de áudio."
    canais_usados = int(master.get("canais_som") or 0)
    canais = sonda.get("canais")
    if canais_usados and canais is not None and canais < canais_usados:
        return False, (f"a timeline usa o canal {canais_usados} desta mídia e o arquivo tem "
                       f"{canais} {'canal' if canais == 1 else 'canais'}. Escolha um arquivo com os canais todos.")
    uso, taxa, dur = master.get("uso_frames"), master.get("edit_rate"), sonda.get("duracao_s")
    if uso and taxa and dur is not None:
        pedido = float(uso) / float(taxa)
        falta_frames = (pedido - dur) * float(taxa)
        if falta_frames > TOLERANCIA_FRAMES:
            return False, (f"a timeline usa {_tempo(pedido)} desta mídia e o arquivo tem {_tempo(dur)}. "
                           "O Avid não consegue relinkar um trecho que o arquivo não tem. Escolha outro arquivo.")
        return True, f"a timeline usa {_tempo(pedido)} desta mídia; o arquivo tem {_tempo(dur)}"
    if dur is not None:
        return True, f"o arquivo tem {_tempo(dur)} (o trecho usado não pôde ser medido: confira na timeline)"
    return True, "não consegui medir o arquivo: se o Media Composer recusar, ele aparece em “Ficaram de fora”"


def e_midia(arquivo: str) -> bool:
    from media.indexer import VIDEO_EXTENSIONS

    return Path(arquivo).suffix.lower() in VIDEO_EXTENSIONS
