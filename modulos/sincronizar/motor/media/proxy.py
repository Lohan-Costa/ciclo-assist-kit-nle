"""
Sincronizar — proxy de vídeo para o monitor: transcodifica um TRECHO curto de uma mídia
que o WebView não decodifica (ProRes, MXF…) para um H.264 leve que o `<video>` toca
frame-exato.

POR QUE EXISTE: o monitor de sync precisa de exatidão AO FRAME (a claquete tem que
bater no ponto do pico do som). O `<video>` do WebView dá isso nativamente, mas não
decodifica ProRes no Windows. Em vez de um player nativo (VLC — que MENTE no seek
pausado, cai no keyframe anterior), geramos um proxy do trecho e o tocamos no
próprio `<video>`. Como o uso real é PULAR pra pontos de sync (não assistir tudo),
um trecho de ~10 s basta; e o custo vira cache, não decode em tempo real.

REGRA CRÍTICA — o proxy é ALL-INTRA (`-g 1`): cada frame é keyframe, então o seek
pausado no `<video>` é exato. Um proxy long-GOP re-introduziria a mentira do VLC.

TETO EM FULL HD: o monitor é pequeno; mídia acima de FHD nunca é transcodificada em
resolução nativa. "full" já é FHD-capped (respeitando o aspect ratio); ½ e ¼ são
relativos a esse teto. Mantém o custo previsível independente da câmera.

O áudio NÃO entra aqui (`-an`): quem toca o som é o `transport.ts`, exato à amostra.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from . import cachedir, fftools, safepath

#: Tetos por nível de resolução (largura, altura), respeitando o aspect ratio.
#: "full" é FHD-capped, não a resolução do arquivo; ½ e ¼ são relativos a ele.
RES_CAPS: dict[str, tuple[int, int]] = {
    "full": (1920, 1080),
    "half": (960, 540),
    "quarter": (480, 270),
}
DEFAULT_RES = "half"


def _cap(resolution: str) -> tuple[int, int]:
    return RES_CAPS.get(resolution, RES_CAPS[DEFAULT_RES])


def scale_filter(resolution: str) -> str:
    """Filtro `-vf` que cabe no teto do nível SEM esticar, preserva o aspect ratio,
    e garante dimensões pares (o H.264 exige). A vírgula dentro de `min()` é
    escapada (`\\,`) porque no filtergraph a vírgula separa filtros."""
    w, h = _cap(resolution)
    return (
        f"scale=w='min({w}\\,iw)':h='min({h}\\,ih)'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2"
    )


def zscale_filter(resolution: str) -> str:
    """FALLBACK do `scale_filter` — mesma geometria (cabe no teto sem esticar,
    aspect ratio preservado, dimensões pares), mas com o scaler `zscale` (libzimg).

    POR QUE EXISTE: o swscale (o filtro `scale`) RECUSA certos inputs — visto na
    prática com ProRes 4444 XQ 12-bit 4:4:4 cujos metadados de cor vêm
    NÃO-ESPECIFICADOS (`prim:reserved trc:reserved`, matrix lida como GBR sobre
    pixels YUV). Ele aborta com "Unsupported input (Operation not supported)" e o
    proxy nunca sai — o monitor caía em "não foi possível exibir este formato". O
    zscale converte esse mesmo frame respeitando o colorspace REAL (não força
    bt709, que mis-etiquetaria mídia bt601/bt2020). libzimg está nos DOIS builds
    embarcados (martin-riedl no macOS, BtbN no Windows — ver fetch_ffmpeg.py).

    `format=yuv420p` vem DEPOIS do zscale de propósito: aí o frame já tem
    colorspace definido pelo zscale, e a conversão de subamostragem passa (o mesmo
    `format` ANTES, ainda em swscale, morreria com o input original)."""
    w, h = _cap(resolution)
    # fator de escala ≤1 (nunca amplia) que cabe no teto WxH preservando o aspect;
    # `trunc(...*iw/2)*2` garante largura/altura pares. `\\,` escapa a vírgula do
    # `min()` (no filtergraph a vírgula separa filtros).
    s = f"min(1\\,min({w}/iw\\,{h}/ih))"
    return f"zscale=w='trunc({s}*iw/2)*2':h='trunc({s}*ih/2)*2',format=yuv420p"


def _cache_root() -> Path:
    return cachedir.sub("proxy")


def _run_progress(cmd, duration_s, on_progress, on_spawn):
    """Roda o ffmpeg lendo `-progress` do stdout e emitindo a fração [0..1]
    (`out_time_us` / duração). Devolve `(returncode, stderr_tail)`.

    Emite o PID via `on_spawn` assim que o processo nasce — é por ele que o
    `preview_cancel` (Rust, FORA do mutex serial do sidecar, que fica preso durante
    o transcode) mata o ffmpeg. `-v error` mantém o stderr minúsculo, então lê-lo
    depois do loop de progresso não corre risco de encher o buffer do pipe."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace"
    )
    if on_spawn:
        try:
            on_spawn(proc.pid)
        except Exception:
            pass
    if proc.stdout is not None:
        for line in proc.stdout:
            if not (duration_s and on_progress):
                continue
            line = line.strip()
            if line.startswith("out_time_us="):
                val = line.split("=", 1)[1]
                if val and val != "N/A":
                    try:
                        frac = (int(val) / 1_000_000.0) / duration_s
                    except ValueError:
                        continue
                    try:
                        on_progress(max(0.0, min(1.0, frac)))
                    except Exception:
                        pass
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    proc.wait()
    return proc.returncode, (stderr or "")[-500:]


def _transcode_progress(
    build_cmd, resolution, tmp, out, path, duration_s, chroma, on_progress, on_spawn,
    label="prévia",
):
    """Roda o ffmpeg via Popen, emitindo o PID por `on_spawn` (é por ele que o
    `preview_cancel` do Rust mata o transcode, FORA do mutex serial) e a fração por
    `on_progress` (barra 0-100%; `None` = sem barra, ex.: a janela do monitor).
    Escolhe o scaler pelo croma: 4:4:4 (ProRes 4444) o swscale RECUSA — vai DIRETO de
    zscale (um processo só: cancelamento sem ambiguidade). Os demais tentam swscale e
    caem no zscale. `label` é só para a mensagem de erro (prévia/proxy)."""
    is_444 = (chroma or "").startswith("4:4:4")
    scalers = (
        [zscale_filter(resolution)]
        if is_444
        else [scale_filter(resolution), zscale_filter(resolution)]
    )
    last_err = ""
    for vf in scalers:
        rc, last_err = _run_progress(build_cmd(vf), duration_s, on_progress, on_spawn)
        if rc == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(out)
            cachedir.maybe_enforce()
            return out
        # Morto por sinal (POSIX: rc<0) = cancelado pelo preview_cancel — NÃO cair no
        # fallback (senão um ffmpeg novo rodaria solto). No Windows o taskkill não dá
        # rc<0, mas o caso pesado (4:4:4) já é um scaler só, sem fallback pra vazar.
        if rc is not None and rc < 0:
            break
    try:
        tmp.unlink()
    except OSError:
        pass
    raise RuntimeError(f"ffmpeg falhou ao gerar {label} de '{path}': {last_err}")


def _file_for(path: Path, start: float, dur: float, resolution: str) -> Path | None:
    """Chave = caminho+tamanho+mtime+janela+resolução (mesmo esquema do probecache):
    se a mídia OU a janela OU a resolução mudam, o proxy não vale."""
    try:
        st = path.stat()
    except OSError:
        return None
    raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{start:.3f}|{dur:.3f}|{resolution}"
    return _cache_root() / f"{hashlib.sha1(raw.encode('utf-8')).hexdigest()}.mp4"


def window(
    path: str | Path,
    start: float,
    dur: float,
    resolution: str = DEFAULT_RES,
    *,
    chroma: str | None = None,
    on_spawn=None,
) -> Path:
    """Proxy H.264 all-intra do trecho `[start, start+dur)`, cacheado. Devolve o
    caminho do .mp4. O trecho começa em t=0 no proxy (o frontend mapeia a posição
    da timeline para o tempo-local do proxy).

    `on_spawn(pid)` emite o PID do ffmpeg — é por ele que o monitor MATA uma janela
    obsoleta (a agulha andou para outro ponto/clipe), liberando o sidecar serial na
    hora para a janela do momento atual (o "furar fila")."""
    path = Path(path)
    out = _file_for(path, start, dur, resolution)
    if out is None:
        raise RuntimeError(f"arquivo não encontrado: {Path(path).name}")
    if out.is_file():
        cachedir.touch(out)  # LRU por último USO
        return out

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mp4")

    def build(vf: str) -> list[str]:
        return [
            fftools.ffmpeg(), "-v", "error", "-y",
            "-ss", f"{max(0.0, start):.6f}",  # antes do -i: busca rápida e exata
            "-i", safepath.ff_input(path),
            "-t", f"{dur:.6f}",
            "-an",                             # o som vem do transporte, não daqui
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast",
            "-g", "1",                         # ALL-INTRA — seek pausado exato no <video>
            "-pix_fmt", "yuv420p",             # compatível com o <video> do WebView
            "-movflags", "+faststart",
            str(tmp),
        ]

    # A janela não tem barra (o still cobre a espera) → sem `-progress`/duração; só o
    # PID (para cancelar). `chroma` faz 4:4:4 ir direto de zscale (um PID só → kill
    # limpo, sem a tentativa swscale que falharia).
    return _transcode_progress(
        build, resolution, tmp, out, path, None, chroma, None, on_spawn, label="proxy"
    )


def _preview_file_for(path: Path, resolution: str) -> Path | None:
    try:
        st = path.stat()
    except OSError:
        return None
    raw = f"preview|{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{resolution}"
    return _cache_root() / f"{hashlib.sha1(raw.encode('utf-8')).hexdigest()}.mp4"


def preview(
    path: str | Path,
    resolution: str = DEFAULT_RES,
    *,
    duration_s: float | None = None,
    chroma: str | None = None,
    on_progress=None,
    on_spawn=None,
) -> Path:
    """Proxy do CLIPE INTEIRO, COM áudio, para a prévia do bin (duplo-clique num
    arquivo: "olhar com som", tocado no `<video controls>` nativo).

    Diferente do `window()`: (1) clipe inteiro, não uma janela — a prévia tem barra
    de seek do arquivo todo; (2) COM áudio (aqui o som É do clipe, ao contrário do
    monitor, mudo); (3) GOP NORMAL, não all-intra — a prévia é visualização casual,
    não sync-check ao frame, e all-intra num clipe longo incharia o cache.

    Um clipe pesado (ProRes 4444 4K) só decodifica por SOFTWARE — ~1 min de
    transcode. Por isso a prévia é OBSERVÁVEL e CANCELÁVEL: `on_progress(fração)`
    alimenta a barra 0-100%, `on_spawn(pid)` dá o PID pro `preview_cancel` (Rust)
    abortar. `duration_s`/`chroma` vêm do frontend (probe já em mãos)."""
    path = Path(path)
    out = _preview_file_for(path, resolution)
    if out is None:
        raise RuntimeError(f"arquivo não encontrado: {Path(path).name}")
    if out.is_file():
        cachedir.touch(out)
        if on_progress:
            on_progress(1.0)
        return out

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mp4")

    def build(vf: str) -> list[str]:
        return [
            fftools.ffmpeg(), "-v", "error", "-nostats", "-progress", "pipe:1", "-y",
            "-i", safepath.ff_input(path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",   # a prévia TEM som (o do próprio clipe)
            "-movflags", "+faststart",
            str(tmp),
        ]

    return _transcode_progress(
        build, resolution, tmp, out, path, duration_s, chroma, on_progress, on_spawn
    )


def _preview_hls_paths(path: str | Path, resolution: str) -> dict | None:
    """Caminhos do HLS da prévia (play PROGRESSIVO): a playlist e o padrão dos
    segmentos, ACHATADOS em `proxy/` com prefixo de hash — assim o LRU
    (`cachedir._entries`, que NÃO recursa em subpastas) conta e despeja os `.ts`.
    Chave `preview_hls|...`, distinta do proxy `.mp4` (`preview|...`)."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None
    raw = f"preview_hls|{p.resolve()}|{st.st_size}|{int(st.st_mtime)}|{resolution}"
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    root = _cache_root()
    return {
        "hash": h,
        "playlist": root / f"{h}.m3u8",
        "segment_pattern": root / f"{h}_%05d.ts",
    }


def _cleanup_hls(h: str) -> None:
    """Apaga a playlist e todos os segmentos de um HLS (parcial órfão ou abortado)."""
    root = _cache_root()
    for f in root.glob(f"{h}_*.ts"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        (root / f"{h}.m3u8").unlink()
    except OSError:
        pass


def preview_hls_plan(path: str | Path, resolution: str = DEFAULT_RES) -> dict:
    """Planeja o HLS da prévia SEM transcodificar: devolve os caminhos (que o Rust
    vai escrever) e se já está CACHEADO (playlist completa, com `#EXT-X-ENDLIST`).

    Um HLS PARCIAL órfão (de um run abortado/morto) é LIMPO aqui, para o transcode
    recomeçar do zero — retomar um HLS a meio é complexo e não vale a pena para uma
    prévia. O diretório de cache é dono do Python; o Rust só executa o ffmpeg nestes
    caminhos."""
    paths = _preview_hls_paths(path, resolution)
    if paths is None:
        raise RuntimeError(f"arquivo não encontrado: {Path(path).name}")
    playlist: Path = paths["playlist"]
    playlist.parent.mkdir(parents=True, exist_ok=True)

    cached = False
    if playlist.is_file():
        try:
            text = playlist.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if "#EXT-X-ENDLIST" in text:
            cached = True
            cachedir.touch(playlist)  # LRU por último USO
        else:
            _cleanup_hls(paths["hash"])  # parcial órfão → recomeça limpo

    return {
        "playlist": str(playlist),
        "segment_pattern": str(paths["segment_pattern"]),
        "cached": cached,
    }


def preview_hls_cleanup(path: str | Path, resolution: str = DEFAULT_RES) -> None:
    """Limpa o HLS parcial de uma prévia abortada (o app chama ao abortar). Um
    parcial órfão também seria limpo no próximo `preview_hls_plan`, mas limpar já
    evita segurar espaço de cache à toa."""
    paths = _preview_hls_paths(path, resolution)
    if paths is None:
        return
    # Só limpa se estiver INCOMPLETO — nunca apagar um cache completo por engano.
    playlist: Path = paths["playlist"]
    if playlist.is_file():
        try:
            if "#EXT-X-ENDLIST" in playlist.read_text(encoding="utf-8", errors="replace"):
                return
        except OSError:
            pass
    _cleanup_hls(paths["hash"])
