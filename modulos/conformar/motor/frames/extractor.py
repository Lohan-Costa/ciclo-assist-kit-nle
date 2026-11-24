"""
Relinker — Módulo Frames: Extrator
Extrai um frame de um arquivo de vídeo em um timecode específico
usando ffmpeg-python. Retorna o frame como imagem temporária.

Dependência: ffmpeg-python
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("relinker.frames.extractor")


def timecode_to_seconds(timecode: str, fps: float) -> float:
    """
    Converte timecode HH:MM:SS:FF para segundos de SEEK no arquivo.

    O TC é non-drop com contagem NOMINAL de frames (round(fps)) — a mesma
    convenção do parser (frames_to_tc) e do frontend. O tempo real de seek é
    o nº de frames nominal dividido pela taxa REAL (ex.: 23.976), senão o campo
    de segundos (contado a 24) e o seek (a 23.976) divergem e o frame extraído
    drifta proporcionalmente ao tempo (bug visível em clipes com TC alto).
    """
    tc = timecode.replace(";", ":")
    parts = tc.split(":")
    if len(parts) != 4:
        raise ValueError(f"Timecode inválido: {timecode}")

    hh, mm, ss, ff = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    fps_int = round(fps) or 1
    total_frames = ((hh * 60 + mm) * 60 + ss) * fps_int + ff
    return total_frames / (fps if fps else fps_int)


def timecode_to_frames(timecode: str, fps: float) -> int:
    """TC HH:MM:SS:FF → índice de frame (nominal, non-drop). Usado p/ endereçar o
    frame nos decoders de SDK (BRAW/R3D/ARRIRAW), que pedem nº de frame, não segundos."""
    tc = timecode.replace(";", ":")
    parts = tc.split(":")
    if len(parts) != 4:
        raise ValueError(f"Timecode inválido: {timecode}")
    hh, mm, ss, ff = (int(p) for p in parts)
    fps_int = round(fps) or 1
    return ((hh * 60 + mm) * 60 + ss) * fps_int + ff


def frame_key(file_path: str, timecode: str, fps: float, accurate: bool, vf):
    """Tupla de identidade de um frame no cache (mesma usada por extract_frame e pelo
    probe). Inclui tamanho+mtime → invalida se a mídia mudar."""
    from frames.cache import file_signature
    p = Path(file_path)
    return (str(p.resolve()), file_signature(str(p)),
            timecode, f"{fps:.6f}", int(bool(accurate)), vf or "")


def extract_frame(file_path: str, timecode: str, fps: float = 25.0, accurate: bool = True,
                  vf: Optional[str] = None, cache_dir: Optional[str] = None,
                  cache_label: Optional[str] = None, sequence: Optional[dict] = None) -> dict:
    """
    Extrai um frame do arquivo de vídeo no timecode especificado.

    vf: cadeia de filtros ffmpeg aplicada ANTES do downscale (ex.: reprodução de
    efeito geométrico — scale/crop do 3DWarp — no frame do candidato para alinhar
    com o ref_video, que tem o efeito queimado).

    cache_dir: se informado, memoiza o PNG numa pasta de cache (chave determinística
    por arquivo+TC+fps+vf). Voltar ao mesmo ponto reaproveita o frame sem re-extrair
    (cache hit é instantâneo, lê só o header PNG). Sem cache_dir, usa tempfile (que
    o caller deve apagar em sucesso). As buscas de snap (accurate=False, descartáveis)
    NÃO passam cache_dir de propósito.

    cache_label: rótulo legível p/ o nome do arquivo de cache (`<nome> <TC>.png`).

    Retorna:
        {
            "frame_path": str,    # caminho para o PNG (cache ou temporário)
            "timecode": str,
            "seconds": float,
            "width": int,
            "height": int,
            "cached": bool        # True se veio do cache (não foi re-extraído)
        }
    """
    import ffmpeg
    import bench
    import time as _time
    from frames.cache import resolve_cache_file, image_dimensions
    from frames.decoders import (sdk_kind, decode_via_helper, image_vf_prefix,
                                 IMAGE_FORMATS, oiiotool_available, oiiotool_cmd)

    _bench_t = _time.perf_counter()   # benchmark opt-in (no-op se desligado)

    # Sequência de imagem (1 arquivo = 1 frame): troca o arquivo pelo do frame pedido e
    # decodifica como still (TC 0). frame_index é 0-based a partir do 1º frame da seq.
    if sequence:
        from frames.sequence import resolve_frame_file
        file_path = resolve_frame_file(sequence, timecode_to_frames(timecode, fps))
        timecode = "00:00:00:00"

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de vídeo não encontrado: {file_path}")

    seconds = timecode_to_seconds(timecode, fps)
    # Frames exibidos/cacheados (accurate) saem JPEG ~1280px — ~8-10× mais leves que
    # PNG full-res e encode mais rápido; nítidos na tela. As buscas de snap
    # (accurate=False, descartáveis) seguem PNG 360px.
    ext = "jpg" if accurate else "png"

    # Cache: chave de identidade determinística (inclui tamanho+mtime → invalida se a
    # mídia mudar); o NOME do arquivo vem do cache_label (legível).
    frame_path = None
    if cache_dir:
        try:
            cp = resolve_cache_file(
                cache_dir, frame_key(file_path, timecode, fps, accurate, vf),
                label=cache_label, ext=ext)
            if cp.exists():
                w, h = image_dimensions(str(cp))
                if w and h:
                    log.info("Frame em cache: %s (%s TC=%s)", cp.name, path.name, timecode)
                    bench.record("frame", (_time.perf_counter() - _bench_t) * 1000.0,
                                 file=path.name, decoder="cache", cached=True,
                                 accurate=accurate)
                    return {"frame_path": str(cp), "timecode": timecode, "seconds": seconds,
                            "width": w, "height": h, "cached": True}
            frame_path = str(cp)   # miss (ou arquivo parcial) → (re)gera neste caminho
        except OSError as e:
            log.warning("cache_dir inutilizável (%s); usando tempfile", e)
            frame_path = None

    log.info("Extraindo frame de %s em TC=%s (%.3fs)", path.name, timecode, seconds)

    if frame_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False)
        tmp.close()
        frame_path = tmp.name

    # BRAW/R3D/ARRIRAW: o ffmpeg não decodifica → helper-CLI do SDK do fabricante
    # (ausente → SdkUnavailable, que a UI mostra como "precisa do SDK X"). Endereça por
    # nº de frame (não segundos). vf (efeito geométrico) não se aplica a RAW de câmera.
    kind = sdk_kind(path)

    success = False
    is_image = path.suffix.lower() in IMAGE_FORMATS
    done = False
    _dec = "ffmpeg"   # decoder usado (p/ benchmark): sdk:<kind> | oiio | ffmpeg
    try:
        if kind:
            decode_via_helper(kind, str(path), timecode_to_frames(timecode, fps),
                              frame_path, max_width=(1280 if accurate else 360))
            done = True
            _dec = "sdk:" + kind
        elif is_image and accurate and oiiotool_available():
            # OpenImageIO: cor correta (EXR linear→sRGB via OCIO) + downscale + JPEG.
            # Imagem = 1 frame (still, ou item de sequência já resolvido) → sem seek.
            # Best-effort: se o oiiotool falhar, cai no ffmpeg abaixo (não quebra o preview).
            import subprocess

            from media import fftools
            try:
                r = subprocess.run(oiiotool_cmd(str(path), frame_path, 1280),
                                   capture_output=True, text=True, timeout=120,
                                   **fftools.SEM_JANELA)
                if r.returncode == 0 and Path(frame_path).exists():
                    done = True
                    _dec = "oiio"
                else:
                    log.warning("oiiotool falhou em '%s' (%s) — fallback ffmpeg",
                                path.name, (r.stderr or '').strip()[:200])
            except Exception as e:
                log.warning("oiiotool erro em '%s' (%s) — fallback ffmpeg", path.name, e)
        if not done:
            # ffmpeg: tradicionais + imagem (EXR/DPX/TIFF). accurate=True (preview):
            # seek frame-accurate p/ Long-GOP (input-seek ~3s antes + output-seek), saída
            # JPEG q3 ≤1280px. accurate=False (match visual): só input-seek, PNG 360px.
            img_pre = image_vf_prefix(path)                  # EXR linear→sRGB (aprox.)
            vf_chain = ",".join(p for p in (img_pre, vf) if p)
            vf_chain = (vf_chain + ",") if vf_chain else ""
            if accurate:
                pre = max(0.0, seconds - 3.0)
                out = ffmpeg.input(str(path), ss=pre).output(
                    frame_path, ss=seconds - pre, vframes=1, format="image2",
                    vcodec="mjpeg", vf=vf_chain + "scale='min(1280,iw)':-2",
                    **{"qscale:v": 3})
            else:
                out = ffmpeg.input(str(path), ss=seconds).output(
                    frame_path, vframes=1, format="image2", vcodec="png",
                    vf=vf_chain + "scale=360:-2")
            try:
                out.overwrite_output().run(quiet=True)
            except ffmpeg.Error as e:
                raise RuntimeError(
                    f"ffmpeg falhou ao extrair frame de '{path.name}' em {timecode}: "
                    f"{e.stderr.decode() if e.stderr else str(e)}"
                )

        # Dimensões do frame extraído (lê o header, sem subprocess de ffprobe).
        width, height = image_dimensions(frame_path)

        log.info("Frame extraído: %s (%dx%d)", frame_path, width or 0, height or 0)
        success = True
        bench.record("frame", (_time.perf_counter() - _bench_t) * 1000.0,
                     file=path.name, decoder=_dec, cached=False, accurate=accurate)
        return {
            "frame_path": frame_path,
            "timecode": timecode,
            "seconds": seconds,
            "width": width,
            "height": height,
            "cached": False
        }
    finally:
        # Em erro, remove o tmp para não vazar (caller é responsável pelo cleanup em sucesso)
        if not success:
            try:
                Path(frame_path).unlink(missing_ok=True)
            except OSError:
                pass
