"""
Relinker — Módulo Media: Indexador de Mídias
Aceita uma lista de paths heterogênea: cada path pode ser uma pasta
(varrida recursivamente) ou um arquivo de mídia individual. Extrai
metadados técnicos via pymediainfo.

Dependências: pymediainfo
"""

import os
import logging
import unicodedata
from pathlib import Path

log = logging.getLogger("relinker.media.indexer")

# Extensões de container de vídeo/áudio reconhecidas
# Extensões de mídia aceitas (vídeo + áudio + imagem). Tudo o que não for isso —
# e, principalmente, os AppleDouble do macOS (._nome) — é ignorado no índice.
VIDEO_EXTENSIONS = {
    # vídeo
    ".mxf", ".mov", ".mp4", ".avi", ".mkv",
    ".mts", ".m2ts", ".r3d", ".braw", ".m4v", ".mpg", ".mpeg", ".m2v",
    ".crm", ".rmf", ".ari", ".arx",                # cine-RAW de câmera (SDK)
    # áudio
    ".wav", ".wave", ".bwf", ".aif", ".aiff", ".aifc",
    ".mp3", ".m4a", ".aac", ".flac", ".ogg",
    # imagem (stills/sequências)
    ".dpx", ".exr", ".tif", ".tiff", ".jpg", ".jpeg",
    ".png", ".tga", ".bmp", ".gif", ".psd",
    ".jp2", ".j2k", ".hdr",                         # imagem extra (OpenImageIO)
}


def index_folder(paths, progress=None, name_hints=None, exclude_paths=None) -> dict:
    """
    Indexa uma lista de paths (pastas e/ou arquivos individuais).

    Args:
        paths: lista de caminhos absolutos. Cada item pode ser pasta
               (varrida recursivamente) ou arquivo (processado direto).
        progress: callback opcional `fn(dict)` chamado durante a varredura e a
               leitura de metadados, para feedback ao usuário (e para manter o
               canal sidecar vivo em árvores grandes — cada evento reseta o
               timeout do lado Rust). Payloads:
                 {"phase":"scan", "scanned":int, "found":int, "current":str}
                 {"phase":"meta", "i":int, "total":int, "current":str, "indexed":int}
        name_hints: lista opcional de nomes do AAF (clip_name/mob_name/alternates).
               Quando fornecida, **só lê metadado (pymediainfo) dos arquivos cujo nome
               bate com algum hint** — o resto é descartado do índice. Isso evita abrir
               cada arquivo da rede (custo dominante) no scan rápido; o "Scan completo"
               (sem hints) lê tudo para casar por UID/visual quem sobrou. As etapas de
               path/nome não usam metadado, então o índice rápido resolve o caso comum.
        exclude_paths: lista opcional de caminhos já casados — pulados na varredura (não
               lê metadado, não entra no índice). Usado no "Scan completo" para **pular
               os arquivos já encontrados** e só procurar os que ainda faltam.

    Retorna:
        {
            "files": [ { path, filename, extension, size_bytes, ... }, ... ],
            "total_files": int
        }
    """
    # Aceita também string única por compatibilidade (legacy single-path)
    if isinstance(paths, str):
        paths = [paths]
    if not paths:
        return {"files": [], "total_files": 0}

    def _emit(payload):
        if progress is None:
            return
        try:
            progress(payload)
        except Exception:
            pass

    import bench
    import control
    import time as _time

    accept_name = _build_hint_filter(name_hints)   # None = sem filtro (lê tudo)
    exclude = set(exclude_paths or ())              # caminhos já casados → pular

    seen: set[str] = set()
    candidates: list[Path] = []   # caminhos de mídia válidos, SEM metadata ainda
    scanned = 0                   # total de entradas varridas (qualquer arquivo)
    _scan_t = _time.perf_counter()

    for raw in paths:
        p = Path(raw)
        if not p.exists():
            log.warning("Caminho não encontrado, ignorando: %s", raw)
            continue

        if p.is_dir():
            log.info("Indexando pasta: %s", p)
            for entry in _iter_entries(p):
                scanned += 1
                _collect(entry, seen, candidates, accept_name, exclude)
                # Feedback periódico durante a varredura (a cada ~200 entradas):
                # mostra progresso mesmo atravessando muitas pastas sem mídia.
                if scanned % 200 == 0:
                    control.check()   # ponto de cancelamento
                    _emit({"phase": "scan", "scanned": scanned,
                           "found": len(candidates), "current": entry.name})
        elif p.is_file():
            scanned += 1
            _collect(p, seen, candidates, accept_name, exclude)
        else:
            log.warning("Caminho não é pasta nem arquivo, ignorando: %s", raw)

    _emit({"phase": "scan", "scanned": scanned, "found": len(candidates), "current": ""})
    bench.record("index.scan", (_time.perf_counter() - _scan_t) * 1000.0,
                 scanned=scanned, media=len(candidates), roots=len(paths))

    # Agrupa sequências de imagem ANTES de ler metadata: só o representativo de cada
    # sequência (e os avulsos) passa pelo pymediainfo (uma seq de N frames lê 1, não N).
    groups, singles = _group_sequence_paths(candidates)
    work: list[tuple] = [(fp, None) for fp in singles] + [(g["rep_path"], g) for g in groups]
    total = len(work)
    files: list[dict] = []
    _meta_t = _time.perf_counter()
    for i, (fp, g) in enumerate(work, 1):
        control.check()   # ponto de cancelamento (entre arquivos)
        _emit({"phase": "meta", "i": i, "total": total,
               "current": fp.name, "indexed": len(files)})
        info = _safe_meta(fp)
        if info is not None:
            if g is not None:
                info["sequence"] = g["sequence"]
            files.append(info)
    _emit({"phase": "meta", "i": total, "total": total, "current": "", "indexed": len(files)})
    bench.record("index.meta", (_time.perf_counter() - _meta_t) * 1000.0,
                 files=len(files), seqs=len(groups), total=total)

    log.info("Indexação concluída: %d entrada(s) (%d sequência(s)), %d varrida(s)",
             len(files), len(groups), scanned)
    return {"files": files, "total_files": len(files)}


def _strict_name_key(name: str) -> str:
    """Chave de comparação ESTRITA de nome para o scan rápido. Tolera **só caixa**
    (a001 == A001), a extensão e os sufixos do Avid (.sync/.new/.NN) — que existem no
    nome do AAF mas não no arquivo em disco. **Separadores e acentos são preservados**
    (`audio_clip` != `audio;clip`). Forma Unicode normalizada (NFC) para o mesmo nome
    não divergir entre NFD do macOS e NFC. Reusa `_strip_avid_suffixes` do matcher."""
    from media.matcher import _strip_avid_suffixes
    s = _strip_avid_suffixes(name or "")
    s = unicodedata.normalize("NFC", s)
    return s.strip().lower()


def _build_hint_filter(name_hints):
    """Predicado `accept(stem) -> bool` do scan rápido a partir dos nomes do AAF.
    Retorna None quando não há hints (sem filtro → lê tudo, que é o "Scan completo").

    Aceita por **duas** chaves, e basta uma bater:

    - **estrita** (`_strict_name_key`): tolera caixa, extensão e sufixo Avid, e
      preserva separadores e acentos;
    - **frouxa** (`_normalize_name`, a mesma do matcher): separadores viram espaço e
      acentos caem.

    ⚠️ **ADAPTAÇÃO em relação ao RELINKER** (ver VENDOR.md). Lá o filtro era só estrito,
    com o argumento de que variações de separador ficariam para o botão "Scan completo".
    Medido neste acervo, o argumento não se sustenta: o Avid grava nomes por timecode e o
    **mesmo item** aparece como `17;25;16 Cordas.wav` no disco e `17_25_16 Cordas.wav` no
    AAF. Com o filtro estrito o índice via 89 de 378 arquivos, e **29 trilhas e efeitos
    sonoros não resolviam** — não por ambiguidade, mas por nunca terem entrado no índice.
    O caso mais comum do acervo ficava fora do caminho rápido.

    A chave frouxa admite mais arquivos e lê mais metadados. É o preço certo: um índice
    que não contém o arquivo produz "nenhum candidato", que é indistinguível de "esse
    arquivo não existe" para quem lê o relatório.
    """
    if not name_hints:
        return None
    from media.matcher import _normalize_name

    estritas = {k for k in (_strict_name_key(h) for h in name_hints) if k}
    frouxas = {k for k in (_normalize_name(h) for h in name_hints) if k}
    if not (estritas or frouxas):
        return None

    import re as _re

    def aceitar(stem: str) -> bool:
        if _strict_name_key(stem) in estritas or _normalize_name(stem) in frouxas:
            return True
        # quadro de SEQUÊNCIA de imagens (`A003C001.1641600`): vale o nome-base (laboratório BL08, P10)
        base = _re.sub(r"[._-]?\d{3,}$", "", stem)
        return base != stem and (_strict_name_key(base) in estritas or _normalize_name(base) in frouxas)

    return aceitar


def _iter_entries(root: Path):
    """Varre `root` recursivamente com `os.scandir`, yieldando os `os.DirEntry` de
    arquivo (não-diretório). **Resiliente a entradas que somem/erram no meio** —
    comum em volumes de rede e com apps que escrevem/apagam temporários (ex.: os
    `.PRV` de preview do Premiere). Um erro num item ou subpasta é logado e
    ignorado, nunca abortando a varredura inteira (era o caso do `rglob`, que
    estourava `FileNotFoundError` ao statar um arquivo que sumiu).

    Não segue symlinks de diretório (evita loops e stats caros pela rede)."""
    stack: list[str] = [str(root)]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError as e:
            log.warning("Sem acesso ao diretório %s: %s — ignorado", d, e)
            continue
        with it:
            while True:
                try:
                    entry = next(it)
                except StopIteration:
                    break
                except OSError as e:
                    # Entrada sumiu/erro no meio do scandir (rede). Segue os demais.
                    log.warning("Erro lendo entrada em %s: %s — ignorado", d, e)
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                except OSError:
                    continue
                yield entry


def _collect(entry, seen: set, out: list, accept_name=None, exclude=None) -> None:
    """Filtro barato (extensão/._/dupe/nome/excluídos) — coleta o caminho SEM ler
    metadata. Aceita um `os.DirEntry` (varredura) ou um `Path` (arquivo avulso).
    `accept_name(stem)` (opcional): filtro por nome do AAF (scan rápido) — só passam
    os arquivos cujo nome bate com um clipe, evitando o pymediainfo dos demais.
    `exclude` (set, opcional): caminhos já casados a pular (Scan completo)."""
    name = entry.name
    if name.startswith("._"):
        return
    raw_path = entry.path if hasattr(entry, "path") else str(entry)
    if exclude and raw_path in exclude:
        return
    stem, dotext = os.path.splitext(name)
    if dotext.lower() not in VIDEO_EXTENSIONS:
        return
    if accept_name is not None and not accept_name(stem):
        return
    fp = Path(entry.path) if hasattr(entry, "path") else entry
    # Dedupe por caminho resolvido (symlinks → mesmo arquivo). resolve() pode falhar
    # se o alvo sumiu na rede; nesse caso cai no caminho cru.
    try:
        a = str(fp.resolve())
    except OSError:
        a = str(fp)
    if a in seen:
        return
    seen.add(a)
    out.append(fp)


def _safe_meta(fp: Path):
    """_extract_metadata tolerante a erro (None em falha)."""
    try:
        info = _extract_metadata(fp)
        log.info("Indexado: %s", fp.name)
        return info
    except Exception as e:
        log.warning("Falha ao extrair metadados de %s: %s — ignorado", fp.name, e)
        return None


# Extensões que praticamente SÓ aparecem como sequência de cinema (1 arquivo = 1 frame).
# .jpg/.png/.tga ficam de fora de propósito (geralmente são stills avulsos, não sequência).
_SEQUENCE_EXTS = {".exr", ".dpx", ".tif", ".tiff", ".jp2", ".j2k", ".hdr", ".ari", ".arx"}


def _group_sequence_paths(candidates: list):
    """Agrupa caminhos numa sequência por (pasta, base, separador, ext, padding).
    Retorna (groups, singles): groups = [{rep_path, sequence}], singles = [Path]."""
    from frames.sequence import parse_sequence_name
    buckets: dict = {}
    singles: list = []
    for fp in candidates:
        ext = fp.suffix.lower()
        parsed = parse_sequence_name(fp.stem) if ext in _SEQUENCE_EXTS else None
        if not parsed:
            singles.append(fp)
            continue
        base, sep, num, pad = parsed
        buckets.setdefault((str(fp.parent), base, sep, ext, pad), []).append((int(num), fp))
    groups = []
    for (d, base, sep, ext, pad), members in buckets.items():
        members.sort(key=lambda x: x[0])
        nums = [n for n, _ in members]
        span = nums[-1] - nums[0] + 1
        # Só é sequência se for DENSA (frames ~contíguos). Esparso = clipes/stills
        # separados que por acaso compartilham prefixo (ex.: SCENE_010, SCENE_020 →
        # NÃO é uma sequência de 11 frames). Senão cada arquivo fica avulso.
        if len(members) < 2 or len(members) < 0.5 * span:
            for _, fp in members:
                singles.append(fp)
            continue
        groups.append({
            "rep_path": members[0][1],     # 1º frame = representativo (path do match)
            "sequence": {"dir": d, "base": base, "sep": sep, "ext": ext, "pad": pad,
                         "first": nums[0], "last": nums[-1], "count": len(members)},
        })
    return groups, singles


# Cache de metadados por arquivo (path → (mtime, size, metadata)). Persiste no
# processo sidecar — re-indexar a mesma pasta (ex.: re-match ao adicionar fontes)
# reaproveita os arquivos já lidos; só os novos/alterados passam por pymediainfo.
_META_CACHE: dict[str, tuple] = {}


def _codec_label(vt) -> str | None:
    """Nome amigável do codec (ex.: 'XDCAM HD422', 'ProRes 422 HQ', 'H.264').

    Preferência: o "Commercial name" do MediaInfo (já vem pronto, ex. 'XDCAM HD422',
    'Apple ProRes 422 HQ', 'AVC'); senão monta a partir de format + profile. O
    codec_id cru (UL SMPTE como '0D01030102046001-…') não serve para exibir.
    """
    if vt is None:
        return None
    commercial = getattr(vt, "commercial_name", None) or getattr(vt, "format_commercial", None)
    if commercial:
        c = str(commercial).strip()
        if c.startswith("Apple "):
            c = c[len("Apple "):]
        # "XDCAM HD422" é 1:1 com o que o mercado chama de "XDCAM 50" (4:2:2, 50 Mbps).
        # Liberdade poética só para esse caso; HD/EX (outras taxas) ficam como vêm.
        if c.upper() == "XDCAM HD422":
            return "XDCAM 50"
        return c

    fmt  = getattr(vt, "format", None)
    prof = getattr(vt, "format_profile", None)
    if fmt:
        f = str(fmt).strip()
        fu = f.upper()
        if fu == "AVC":
            return "H.264"
        if fu == "HEVC":
            return "H.265"
        if "PRORES" in fu:
            return f"ProRes {prof}".strip() if prof else "ProRes"
        return f"{f} {prof}".strip() if prof else f
    return getattr(vt, "codec_id", None)


def _extract_metadata(file_path: Path) -> dict:
    """Extrai metadados técnicos de um arquivo via pymediainfo (com cache)."""
    from pymediainfo import MediaInfo

    abs_str = str(file_path)
    st = None
    try:
        st = file_path.stat()
        cached = _META_CACHE.get(abs_str)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            return dict(cached[2])   # cópia defensiva
    except OSError:
        pass

    media_info = MediaInfo.parse(str(file_path))
    video_track = next(
        (t for t in media_info.tracks if t.track_type == "Video"),
        None
    )
    general_track = next(
        (t for t in media_info.tracks if t.track_type == "General"),
        None
    )

    stat = st or file_path.stat()

    info = {
        "path": str(file_path),
        "filename": file_path.name,
        "extension": file_path.suffix.lower(),
        "size_bytes": stat.st_size,
        "duration_ms": float(video_track.duration) if video_track and video_track.duration else None,
        "frame_rate": float(video_track.frame_rate) if video_track and video_track.frame_rate else None,
        "width": int(video_track.width) if video_track and video_track.width else None,
        "height": int(video_track.height) if video_track and video_track.height else None,
        "codec": video_track.codec_id if video_track else None,
        "codec_label": _codec_label(video_track),
        "uid": getattr(video_track, "unique_id", None),
        "tc_start": getattr(general_track, "time_code_of_first_frame", None),
        "camera_roll": getattr(general_track, "com_apple_quicktime_reelname", None),
        "created_at": getattr(general_track, "file_creation_date", None),
    }
    try:
        _META_CACHE[abs_str] = (stat.st_mtime, stat.st_size, dict(info))
    except Exception:
        pass
    return info
