"""O xmeml (FCP7, o que a Carta Aberta escreve com `entrega_premiere.xml_da_timeline`) LIDO só no que o casamento e a
entrega ao Baselight precisam — etapa 3 da proposta `docs/plano/2026-11-22-baselight-no-app.md` (a Carta Aberta e o
"Conformar com De Lá Pra Cá").

⭐ Não é um leitor geral de xmeml: o arquivo vai ao Baselight COMO ESTÁ, reescrito só no `<file>` (`entrega.reescrever`).
Daqui sai a lista de planos de vídeo (o arquivo de cada um) para o casador do Premiere (`prproj.originais.casar`, que só
lê `media_ref.local_path`) e a tela "antes de montar" (`resumir`). O `<in>` da Carta já conta na taxa da TIMELINE desde o
início do arquivo (o mesmo critério do AAF do MC): `source_fps` = a taxa da timeline.
"""
from __future__ import annotations

import os
import urllib.parse
import xml.etree.ElementTree as ET
from fractions import Fraction


def _fps(rate: ET.Element | None, padrao: float = 25.0) -> float:
    if rate is None or not rate.findtext("timebase"):
        return padrao
    tb = int(rate.findtext("timebase"))
    return float(Fraction(tb * 1000, 1001)) if rate.findtext("ntsc") == "TRUE" else float(tb)


def _caminho(f: ET.Element) -> str | None:
    pu = f.find("pathurl")
    if pu is None or not pu.text:
        return None
    return urllib.parse.unquote(pu.text.replace("file://localhost", "").replace("file://", ""))


def _tc(q: int, base: int) -> str:
    s, f = divmod(max(0, q), base)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def e_xmeml(caminho: str) -> bool:
    try:
        with open(caminho, "rb") as fh:
            cabeca = fh.read(4096).decode("utf-8", "replace")
    except OSError:
        return False
    return "<xmeml" in cabeca


def ler(caminho: str) -> dict:
    """`{nome, fps, largura, altura, inicio, segmentos}` — a forma da leitura do `.prproj` (só vídeo)."""
    raiz = ET.parse(caminho).getroot()
    seq = raiz.find(".//sequence")
    if seq is None:
        raise ValueError("o xmeml não tem sequência")
    fps = _fps(seq.find("rate"))
    base = round(fps)
    fmt = seq.find("media/video/format/samplecharacteristics")
    arquivos: dict[str, str | None] = {}
    for f in seq.iter("file"):
        if f.get("id") and f.find("pathurl") is not None:
            arquivos[f.get("id")] = _caminho(f)
    segs = []
    for k, trilha in enumerate(seq.findall("media/video/track"), start=1):
        for ci in trilha.findall("clipitem"):
            fe = ci.find("file")
            caminho_arq = arquivos.get(fe.get("id")) if fe is not None else None
            if not caminho_arq:
                continue
            ini, fim, entra = int(ci.findtext("start")), int(ci.findtext("end")), int(ci.findtext("in") or 0)
            segs.append({"track": k, "timeline_tc_in": _tc(ini, base), "duration_frames": fim - ini,
                         "source_start_frames": entra, "source_fps": fps, "relative_speed": 1.0,
                         "clip_name": ci.findtext("name") or os.path.basename(caminho_arq),
                         "disabled": ci.findtext("enabled") == "FALSE", "is_audio": False,
                         "media_ref": {"local_path": caminho_arq}})
    return {"nome": seq.findtext("name") or os.path.basename(caminho), "fps": fps,
            "largura": int(fmt.findtext("width") or 1920) if fmt is not None else 1920,
            "altura": int(fmt.findtext("height") or 1080) if fmt is not None else 1080,
            "inicio": 0, "segmentos": segs}


def arquivos(caminho: str) -> list[str]:
    """Os arquivos de VÍDEO distintos do xmeml (o "Importar timeline" sem casar: cada um descrito como é)."""
    return sorted({s["media_ref"]["local_path"] for s in ler(caminho)["segmentos"]})
