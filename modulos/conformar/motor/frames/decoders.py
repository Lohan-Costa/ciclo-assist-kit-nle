"""
Relinker — Despacho de decodificação de frame por formato.

A extração de frame escolhe um BACKEND conforme o formato do arquivo:

  - ffmpeg            → MP4/MOV/MXF/ProRes/DNxHR (tradicionais) e imagens EXR/DPX/TIFF
                        (o ffmpeg lê; EXR ganha um tonemap linear→sRGB aproximado).
  - helper-CLI de SDK → BRAW/R3D/ARRIRAW exigem o SDK do fabricante. Cada um é um
                        binário externo opcional (`relinker-decode-<kind>`) com contrato
                        uniforme, detectado em runtime. Ausente → SdkUnavailable (a UI
                        mostra "precisa do SDK X"; o relink em si NÃO depende disso).

Contrato do helper-CLI (um binário por SDK, construído contra o SDK do fabricante):

    relinker-decode-<kind> --file <path> --frame <N> --out <out.jpg> [--max-width <W>]
        exit 0 + grava <out.jpg>;  exit ≠0 + motivo no stderr.

Detalhes e o helper de BRAW em `helpers/` (ver docs/raw-decoders.md).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Extensões que exigem SDK de fabricante → "kind" do helper.
# (Sony X-OCN é .mxf → detectado por essência em sdk_kind, não por extensão.)
SDK_FORMATS = {
    ".braw": "braw",
    ".r3d":  "r3d",
    ".ari": "arri", ".arx": "arri", ".arriraw": "arri",
    ".crm": "canon", ".rmf": "canon",
}
# Rótulo amigável p/ a UI ("precisa do SDK …").
SDK_LABELS = {
    "braw": "Blackmagic RAW", "r3d": "RED (R3D)", "arri": "ARRI (ARRIRAW)",
    "canon": "Canon Cinema RAW Light", "sony": "Sony X-OCN / RAW",
}
# Página oficial de download do SDK (p/ a UI facilitar a instalação).
SDK_URLS = {
    "braw": "https://www.blackmagicdesign.com/support/family/blackmagic-raw",
    "r3d":  "https://www.red.com/download/r3d-sdk",
    "arri": "https://www.arri.com/en/learn-help/learn-help-camera-system/pre-postproduction/file-formats-data-handling/arriraw",
    "canon": "https://www.usa.canon.com/support/software-and-drivers",
    "sony": "https://www.sony.net/Products/RAWViewer/",
}
# Binário helper esperado por kind.
HELPER_NAMES = {
    "braw": "relinker-decode-braw",
    "r3d":  "relinker-decode-r3d",
    "arri": "relinker-decode-arri",
    "canon": "relinker-decode-canon",
    "sony": "relinker-decode-sony",
}
# Formatos de imagem (frame único ou item de sequência). ffmpeg lê todos; oiiotool (se
# instalado) dá cor correta (ver OIIO_FORMATS / oiiotool_cmd).
IMAGE_FORMATS = {".exr", ".dpx", ".tif", ".tiff", ".jp2", ".j2k", ".hdr", ".psd"}


class SdkUnavailable(Exception):
    """O formato exige um SDK de fabricante cujo helper não está instalado."""
    def __init__(self, kind: str):
        self.kind = kind
        self.label = SDK_LABELS.get(kind, kind)
        self.url = SDK_URLS.get(kind)
        super().__init__(f"Formato requer o SDK: {self.label}")


_XOCN_CACHE: dict = {}   # path -> bool (.mxf é Sony X-OCN?) — probe é caro, memoiza


def _mxf_is_xocn(path) -> bool:
    """Detecta Sony X-OCN dentro de um .mxf (codec via pymediainfo). Cacheado por path.
    X-OCN não tem extensão própria (vem em .mxf), então o dispatch precisa olhar a essência."""
    key = str(path)
    if key in _XOCN_CACHE:
        return _XOCN_CACHE[key]
    found = False
    try:
        from pymediainfo import MediaInfo
        for t in MediaInfo.parse(path).tracks:
            if t.track_type == "Video":
                codec = " ".join(str(x) for x in (getattr(t, "format", None),
                                                  getattr(t, "codec_id", None),
                                                  getattr(t, "commercial_name", None)) if x).upper()
                found = ("X-OCN" in codec) or ("XOCN" in codec) or ("SONY RAW" in codec)
                break
    except Exception:
        found = False
    _XOCN_CACHE[key] = found
    return found


def sdk_kind(path) -> Optional[str]:
    """Kind do SDK exigido ('braw'|'r3d'|'arri'|'canon'|'sony'), senão None.
    Por extensão; .mxf é checado por essência (Sony X-OCN)."""
    ext = Path(path).suffix.lower()
    k = SDK_FORMATS.get(ext)
    if k:
        return k
    if ext == ".mxf" and _mxf_is_xocn(path):
        return "sony"
    return None


def _helper_dirs():
    """Onde procurar os binários helper: junto ao sidecar (bundle), binaries/ e helpers/."""
    dirs = []
    try:
        dirs.append(Path(sys.executable).resolve().parent)        # bundle de produção
    except Exception:
        pass
    base = Path(__file__).resolve().parents[1]                    # src-python/
    dirs.append(base / "helpers" / "bin")                         # dev: helpers compilados
    dirs.append(base.parent / "src-tauri" / "binaries")           # junto ao sidecar
    return dirs


def helper_path(kind: str) -> Optional[str]:
    """Caminho do binário helper do SDK, se presente e executável. Senão None."""
    name = HELPER_NAMES.get(kind)
    if not name:
        return None
    for d in _helper_dirs():
        p = d / name
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which(name)


def helper_available(kind: str) -> bool:
    return helper_path(kind) is not None


def sdk_status() -> dict:
    """Disponibilidade de cada SDK (p/ a UI/diagnóstico): {kind: {label, available, url}}."""
    return {k: {"label": SDK_LABELS[k], "available": helper_available(k), "url": SDK_URLS.get(k)}
            for k in HELPER_NAMES}


# Locais onde a BlackmagicRawAPI.framework pode estar (dev: SDK ou apps BRAW instalados).
# Num app empacotado, o dispatch acha a framework em Contents/Frameworks sozinho.
_BRAW_FRAMEWORK_DIRS = [
    "/Applications/Blackmagic RAW/Blackmagic RAW SDK/Mac/Libraries",
    "/Applications/Blackmagic RAW/Blackmagic RAW Player.app/Contents/Frameworks",
    "/Applications/Blackmagic RAW/Blackmagic RAW Speed Test.app/Contents/Frameworks",
    "/Library/Frameworks",
]


def _braw_libraries() -> Optional[str]:
    """Diretório com a BlackmagicRawAPI.framework (p/ a env BRAW_LIBRARIES em dev)."""
    if os.environ.get("BRAW_LIBRARIES"):
        return os.environ["BRAW_LIBRARIES"]
    for d in _BRAW_FRAMEWORK_DIRS:
        if (Path(d) / "BlackmagicRawAPI.framework").is_dir():
            return d
    return None


def decode_via_helper(kind: str, file: str, frame_number: int, out_path: str,
                      max_width: int = 1280, timeout: int = 180) -> str:
    """Decodifica um frame de um formato de SDK via helper-CLI externo → grava out_path.
    Levanta SdkUnavailable se o helper não estiver instalado."""
    exe = helper_path(kind)
    if not exe:
        raise SdkUnavailable(kind)
    cmd = [exe, "--file", str(file), "--frame", str(int(frame_number)),
           "--out", str(out_path), "--max-width", str(int(max_width))]
    # BRAW em dev: aponta a framework (instalação local). No app empacotado o dispatch
    # acha sozinho em Contents/Frameworks, então isto é só um reforço inofensivo.
    env = None
    if kind == "braw":
        libs = _braw_libraries()
        if libs:
            env = {**os.environ, "BRAW_LIBRARIES": libs}
    try:
        from media import fftools
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env, **fftools.SEM_JANELA)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{HELPER_NAMES[kind]}: timeout ao decodificar frame {frame_number}")
    if r.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(
            f"{HELPER_NAMES[kind]} falhou (frame {frame_number}): "
            f"{(r.stderr or '').strip() or ('código ' + str(r.returncode))}")
    return str(out_path)


def image_vf_prefix(path) -> str:
    """Prefixo de filtro ffmpeg p/ formatos de imagem. EXR é linear/scene-referred →
    aplica uma curva sRGB aproximada p/ visualização. DPX/TIFF já são display-referred."""
    if Path(path).suffix.lower() == ".exr":
        # gamma ~1/2.2 (aprox. sRGB) — suficiente p/ preview/match; não é color-managed.
        return "eq=gamma=0.4545"
    return ""


# ── OpenImageIO (cor correta para formatos de imagem) ─────────────────────────
# Formatos onde o oiiotool dá cor melhor que o ffmpeg (EXR linear→sRGB via OCIO embutido,
# + JPEG2000/HDR/PSD). Opcional: ausente → cai no ffmpeg (sem regressão).
OIIO_FORMATS = {".exr", ".dpx", ".tif", ".tiff", ".jp2", ".j2k", ".hdr", ".psd"}
_OIIOTOOL = None   # cache do caminho do oiiotool (None=não checado, ""=ausente)


def oiiotool_available() -> bool:
    return bool(oiiotool_path())


def oiiotool_path() -> Optional[str]:
    """Caminho do oiiotool (helpers/bin, bundle ou PATH). Cacheado."""
    global _OIIOTOOL
    if _OIIOTOOL is None:
        for d in _helper_dirs():
            p = d / "oiiotool"
            if p.exists() and os.access(p, os.X_OK):
                _OIIOTOOL = str(p)
                break
        else:
            _OIIOTOOL = shutil.which("oiiotool") or ""
    return _OIIOTOOL or None


def oiiotool_cmd(in_path: str, out_path: str, max_width: int) -> list:
    """Comando oiiotool: lê a imagem, converte cor (EXR linear→sRGB; outros passam),
    reduz p/ max_width e grava JPEG 8-bit. OCIO embutido do OIIO cobre linear↔sRGB."""
    exe = oiiotool_path()
    cmd = [exe, str(in_path)]
    if Path(in_path).suffix.lower() == ".exr":
        cmd += ["--colorconvert", "linear", "sRGB"]   # scene-referred → display
    if max_width and max_width > 0:
        cmd += ["--resize", f"{int(max_width)}x0"]     # mantém proporção
    cmd += ["-o:type=uint8", str(out_path)]
    return cmd
