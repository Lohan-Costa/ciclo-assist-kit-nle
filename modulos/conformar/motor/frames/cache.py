"""
Relinker — Cache de frames de preview.

Memoiza os PNGs extraídos pelo ffmpeg: voltar ao mesmo ponto (mesmo arquivo,
TC, fps, efeito) reaproveita o frame já gerado em vez de re-extrair. Isso também
resolve o vazamento antigo (cada navegação criava um PNG temporário órfão).

A chave de identidade inclui tamanho + mtime do arquivo de mídia, então o cache se
invalida sozinho se a mídia mudar no disco. O NOME do arquivo, porém, é legível —
`<nome da mídia> <TC>.png` (ex.: `A001 01113114.png`), com `_1`, `_2`… em colisão.
O mapa chave→nome fica num `_index.json` na pasta do cache.

A pasta do cache é decidida pelo frontend (default `<Documentos>/<NomeDoApp>/cache/
frames`, configurável) e chega como `cache_dir` nos comandos extract_*; o rótulo
legível chega como `cache_label`.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Tuple

# Nome do app vindo do Rust (tauri.conf productName) via env — fonte única, sem
# hardcode. Usado como fallback p/ logs/cache quando o frontend não passa caminho.
APP_NAME = os.environ.get("RELINKER_APP_NAME", "Relinker")

_INDEX_NAME = "_index.json"

# Manifesto em memória por cache_dir: {"map": {key_hash: filename}, "used": set}.
# O sidecar processa comandos sequencialmente → sem concorrência. Carregado uma vez,
# salvo só quando uma entrada nova é criada (cache miss já é a operação cara).
_MANIFESTS: dict = {}


def file_signature(path: str) -> str:
    """Identidade do arquivo que invalida o cache se a mídia mudar: tamanho:mtime_ns."""
    try:
        st = os.stat(path)
        return f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return "0:0"


def _key_hash(parts) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _sanitize(label: str) -> str:
    """Nome de arquivo seguro: troca separadores/proibidos por '_', limita o tamanho."""
    bad = set('/\\:*?"<>|\n\r\t')
    s = "".join("_" if c in bad else c for c in label).strip()
    return s[:120] or "frame"


def _index_path(cache_dir: str) -> Path:
    return Path(cache_dir) / _INDEX_NAME


def _manifest(cache_dir: str) -> dict:
    m = _MANIFESTS.get(cache_dir)
    if m is None:
        m = _load_manifest(cache_dir)
        _MANIFESTS[cache_dir] = m
    return m


def _load_manifest(cache_dir: str) -> dict:
    mapping = {}
    ip = _index_path(cache_dir)
    if ip.is_file():
        try:
            data = json.loads(ip.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                mapping = {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError):
            mapping = {}
    used = set(mapping.values())
    # Semeia com frames já presentes → robustez se o índice se perder (não sobrescreve).
    for f in _cache_images(cache_dir):
        used.add(f.name)
    return {"map": mapping, "used": used}


def _save_manifest(cache_dir: str, m: dict) -> None:
    try:
        _index_path(cache_dir).write_text(
            json.dumps(m["map"], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def resolve_cache_file(cache_dir: str, key_parts, label: Optional[str] = None,
                       ext: str = "png") -> Path:
    """Caminho de cache (legível) para esta chave de identidade.

    Reaproveita o nome já mapeado p/ a chave (cache hit). Numa entrada nova, deriva
    o nome de `label` (`<nome> <TC>.<ext>`), com `_N` se já existir um nome igual de
    outra chave. Cria a pasta. Levanta OSError se não der p/ criar (caller cai no temp).
    """
    d = Path(cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    kh = _key_hash(key_parts)
    m = _manifest(cache_dir)
    fname = m["map"].get(kh)
    if fname:
        return d / fname
    base = _sanitize(label) if label else kh[:12]
    fname = f"{base}.{ext}"
    if fname in m["used"]:
        i = 1
        while f"{base}_{i}.{ext}" in m["used"]:
            i += 1
        fname = f"{base}_{i}.{ext}"
    m["map"][kh] = fname
    m["used"].add(fname)
    _save_manifest(cache_dir, m)
    return d / fname


def cached_file(cache_dir: str, key_parts, ext: str = "png") -> Optional[Path]:
    """Caminho do frame se JÁ existir no cache (somente leitura — NÃO cria entrada).
    Usado para sondar o que já foi gerado sem extrair."""
    if not cache_dir:
        return None
    fname = _manifest(cache_dir)["map"].get(_key_hash(key_parts))
    if fname:
        p = Path(cache_dir) / fname
        if p.exists():
            return p
    return None


# ── Cache do resultado do SNAP ────────────────────────────────────────────────
# O snap (matchTemplate) é determinístico mas caro (extrai vários frames de busca).
# Guardamos o TC resolvido por chave (clipe+ref+tcs+vf+janela) p/ não re-snapar — ao
# revisitar/pré-cachear o mesmo clipe, vai direto ao frame final (que está em cache).
_SNAP_NAME = "_snap.json"
_SNAPS: dict = {}


def _snap_path(cache_dir: str) -> Path:
    return Path(cache_dir) / _SNAP_NAME


def _snaps(cache_dir: str) -> dict:
    m = _SNAPS.get(cache_dir)
    if m is None:
        m = {}
        sp = _snap_path(cache_dir)
        if sp.is_file():
            try:
                d = json.loads(sp.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    m = {str(k): str(v) for k, v in d.items()}
            except (OSError, ValueError):
                m = {}
        _SNAPS[cache_dir] = m
    return m


def snap_get(cache_dir: Optional[str], snap_key) -> Optional[str]:
    if not cache_dir:
        return None
    return _snaps(cache_dir).get(_key_hash(snap_key))


def snap_put(cache_dir: Optional[str], snap_key, value: str) -> None:
    if not cache_dir:
        return
    m = _snaps(cache_dir)
    m[_key_hash(snap_key)] = str(value)
    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        _snap_path(cache_dir).write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def image_dimensions(path: str) -> Tuple[Optional[int], Optional[int]]:
    """Lê (largura, altura) de um PNG ou JPEG sem subprocess — cache hit instantâneo."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None, None
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":                       # JPEG: acha o marcador SOF
        i, n = 2, len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            mk = data[i + 1]
            if 0xC0 <= mk <= 0xCF and mk not in (0xC4, 0xC8, 0xCC):
                h = int.from_bytes(data[i + 5:i + 7], "big")
                w = int.from_bytes(data[i + 7:i + 9], "big")
                return w, h
            if mk in (0xD8, 0xD9) or 0xD0 <= mk <= 0xD7:
                i += 2
                continue
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None, None


def _cache_images(cache_dir: str):
    """Itera os arquivos de frame (jpg/png) da pasta de cache."""
    d = Path(cache_dir)
    if d.is_dir():
        for f in d.iterdir():
            # Os `._*` do exFAT têm a mesma extensão e não são frames: inflavam a contagem do cache.
            if f.suffix.lower() in (".jpg", ".jpeg", ".png") and not f.name.startswith("._"):
                yield f


def cache_stats(cache_dir: Optional[str]) -> dict:
    """Tamanho total (bytes) e nº de frames no cache. Tolerante a pasta ausente."""
    total = 0
    count = 0
    if cache_dir:
        for f in _cache_images(cache_dir):
            try:
                total += f.stat().st_size
                count += 1
            except OSError:
                pass
    return {"bytes": total, "count": count, "cache_dir": cache_dir}


def clear_cache(cache_dir: Optional[str]) -> dict:
    """Apaga todos os frames do cache + o índice. Retorna quantos foram removidos."""
    removed = 0
    if cache_dir:
        for f in _cache_images(cache_dir):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
        for extra in (_index_path(cache_dir), _snap_path(cache_dir)):
            try:
                extra.unlink(missing_ok=True)
            except OSError:
                pass
        _MANIFESTS.pop(cache_dir, None)
        _SNAPS.pop(cache_dir, None)
    return {"removed": removed, "cache_dir": cache_dir}
