#!/usr/bin/env python3
"""video_descriptor.py — autora o descriptor CDCI de um master de VÍDEO AMA genérico.

PROBLEMA: clonar 1 template de vídeo em todas as câmeras corrompe (avc_sps_patcher r_crop_req)
quando as DIMENSÕES diferem (ex: A009 1920x1080 vs B001 DCI-2K 2048x1080). A geometria do
descriptor CDCI é POR CLIPE.

SOLUÇÃO (validada por diff contra descriptors reais aceitos pelo MC): todo o CDCI é boilerplate
CONSTANTE por classe de codec (subsampling, GUuIDs Rec.709/AVC, container handler, refs de cor...)
EXCETO um punhado de campos derivados da GEOMETRIA, que se autoram do ffprobe:

  stored/sampled/display_width = width
  aspect_ratio                 = DAR reduzido
  valid_box/essence_box/source_box : caixas [ [x,d],[y,d],[w,d],[h,d] ] em UNIDADE 5/6 px;
        componentes de LARGURA X=-(width*5/6)/2 e W=width*5/6 (Y e H são idênticos entre clipes
        de MESMA altura -> mantidos do skeleton; valid/essence usam display, source usa stored).
  stored_height = ceil16(display_h)   (1080->1088 = macrobloco H.264; MC tolera 1080 e 1088)
  _SD_AVC_SUB_DESCRIPTOR.ATN_AVCLevel/Profile = ffprobe level/profile
  edit_rate=fps, length=nb_frames, _CONTAINER_HANDLER_GUID = por extensão

PROVA: autorar o CDCI 2048 a partir do skeleton 1920 + ffprobe saiu GEOMETRIA-IDÊNTICA ao B001
real -> como o real é aceito pelo MC, o autorado (idêntico) também é. 1 skeleton por classe de
ALTURA cobre qualquer largura; alturas múltiplas de 16 (2160/720) não têm crop e são computáveis.
"""
import json, os, subprocess
from fractions import Fraction
from media import fftools  # noqa: E402 — binários embarcados (versao-instalada-embarca-tudo)
from media.opatom import _video_rate  # noqa: E402 — a taxa por votação, nunca um campo cru (B074)

# _CONTAINER_HANDLER_GUID por extensão (plugin AMA que decodifica o arquivo em runtime).
CONTAINER_HANDLER = {
    ".mov": "73dc063c76024c4cba3f3f47120cd1e9", ".mp4": "73dc063c76024c4cba3f3f47120cd1e9",
    ".m4v": "73dc063c76024c4cba3f3f47120cd1e9",
    ".wav": "3711d3cc62d049d7b0ae c118101d1a16".replace(" ", ""),
    ".aif": "3711d3cc62d049d7b0aec118101d1a16", ".aiff": "3711d3cc62d049d7b0aec118101d1a16",
    ".mp3": "6229779f27ce4d6cb0aec118101d1a16",
    ".png": "d945322d5e774c4bb0aec118101d1a16",
}
_AVC_PROFILE = {"High": 100, "Main": 77, "Baseline": 66, "Constrained Baseline": 66,
                "High 10": 110, "High 4:2:2": 122, "High 4:4:4": 244}
_UNIT = Fraction(5, 6)   # 1 px = 5/6 unidade de caixa (empírico, constante p/ H.264 Avid)


def _ceil16(n):
    return ((int(n) + 15) // 16) * 16


def probe_video(path):
    """ffprobe -> dict {W,H,dar:[n,d],level,profile,nb_frames,fps:(num,den),codec}. DAR do stream,
    fallback p/ reduce(W,H) quando ausente/indefinido (SAR 1:1)."""
    o = subprocess.check_output([
        fftools.ffprobe_exe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,display_aspect_ratio,profile,level,nb_frames,r_frame_rate,avg_frame_rate,time_base,"
        "codec_name",
        "-of", "json", path])
    s = json.loads(o)["streams"][0]
    W, H = int(s["width"]), int(s["height"])
    dar = s.get("display_aspect_ratio", "")
    if dar and ":" in dar and "0" not in dar.split(":"):
        dn, dd = (int(x) for x in dar.split(":"))
    else:
        fr = Fraction(W, H); dn, dd = fr.numerator, fr.denominator
    num, den = _video_rate(s)   # por votação (B074): o `r_frame_rate` do MXF do Avid é a metade
    if not num or not den:
        raise ValueError(f"taxa de quadros ilegível: {path}")
    nb = int(s["nb_frames"]) if str(s.get("nb_frames", "")).isdigit() else None
    return {"W": W, "H": H, "dar": [dn, dd], "level": int(s.get("level", 0) or 0),
            "profile": _AVC_PROFILE.get(s.get("profile"), 100), "nb_frames": nb,
            "fps": (num, den), "codec": s.get("codec_name")}


def _frac(x):
    x = Fraction(x)
    return [x.numerator, x.denominator]


def patch_cdci_geometry(descriptor, meta, ext=None):
    """Muta o property_data de um CDCIDescriptor pyavb (clonado de um SKELETON da mesma classe de
    ALTURA) p/ a geometria do arquivo (meta = probe_video). Retorna o descriptor. Só toca nos campos
    derivados da geometria/rate/AVC/container — todo o resto (boilerplate do skeleton) fica intacto."""
    pd = descriptor.property_data
    W, H = meta["W"], meta["H"]
    Wb = W * _UNIT; Xb = -Wb / 2
    pd["stored_width"] = W; pd["sampled_width"] = W; pd["display_width"] = W
    pd["stored_height"] = _ceil16(H); pd["sampled_height"] = H; pd["display_height"] = H
    pd["aspect_ratio"] = list(meta["dar"])
    for bk in ("valid_box", "essence_box", "source_box"):
        b = [list(p) for p in pd[bk]]         # mantém Y (idx1) e H (idx3) do skeleton (mesma altura)
        b[0] = _frac(Xb); b[2] = _frac(Wb)    # troca só X e W (derivados da largura)
        pd[bk] = b
    if meta.get("fps"):
        n, d = meta["fps"]; pd["edit_rate"] = round(n / d, 3)
    if meta.get("nb_frames"):
        pd["length"] = meta["nb_frames"]
    # AVC sub-descriptor (level/profile) dentro de attributes
    attrs = pd.get("attributes")
    if attrs is not None:
        sub = attrs.get("_SD_AVC_SUB_DESCRIPTOR")
        if sub is not None:
            if meta.get("level"):
                sub["ATN_AVCLevel"] = meta["level"]
            sub["ATN_AVCProfile"] = meta["profile"]
        if ext:
            h = CONTAINER_HANDLER.get(ext.lower())
            if h:
                attrs["_CONTAINER_HANDLER_GUID"] = bytearray(bytes.fromhex(h))
    return descriptor


def compute_boxes(W, H):
    """Caixas de geometria a partir do zero (p/ quando NÃO há skeleton da mesma altura). Alturas
    múltiplas de 16 não têm crop (source==valid); 1080 (não-múltiplo) tem o skeleton como fonte de
    verdade — aqui usamos aproximação centrada (MC tolera). Retorna {valid_box,essence_box,source_box}."""
    Wb = W * _UNIT; Xb = -Wb / 2
    Hv = H * _UNIT; Yv = -Hv / 2                       # display (valid/essence)
    Hs = _ceil16(H) * _UNIT; Ys = -Hs / 2              # stored (source); centrado (aprox p/ 1080)
    valid = [_frac(Xb), _frac(Yv), _frac(Wb), _frac(Hv)]
    source = [_frac(Xb), _frac(Ys), _frac(Wb), _frac(Hs)]
    return {"valid_box": valid, "essence_box": list(valid), "source_box": source}


if __name__ == "__main__":
    import sys
    print(json.dumps(probe_video(sys.argv[1]), indent=2))
