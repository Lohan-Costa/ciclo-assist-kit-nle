"""O xmeml da montagem do MC, gerado da LEITURA do AAF, para o lado do MC passar pela MESMA entrega do Premiere
(`entrega.reescrever` → Baselight → `conferencia.conferir`) — em vez do AAF religado (laboratório BL08, 2026-11-22).

Por quê: o AAF religado deixa o Baselight converter a posição na fonte do jeito dele, e no BL08 ele errou o P3 (−107
quadros) e o P7 (o plano de 29,97 começou no quadro 287, o MC no 359) — erros do Baselight, provados pelo vid ref do MC.
Pelo xmeml, o `<file>` declara o original de verdade e a posição segue a ponte pelo original.

⭐ O AAF do MC já conta o início na fonte (`source_start_frames`) na taxa da TIMELINE desde o início do arquivo do daily
(medido no BL08: o plano de 29,97 vem com 287 = 11,97 s, o quadro 359 do arquivo) — o mesmo critério do `<in>` do xmeml.
⛔ Só imagem, só corte seco: efeito de velocidade, reenquadramento e transição não são traduzidos aqui (o plano sai com a
marca `nao_traduzido` no retorno, para a conferência e o editor verem).
"""
from __future__ import annotations

import os
import urllib.parse
import xml.etree.ElementTree as ET

from .entrega import _rate, _tc_quadros, como_o_disco_lista


def _sub(pai: ET.Element, tag: str, texto=None, **attrs) -> ET.Element:
    e = ET.SubElement(pai, tag, attrs)
    if texto is not None:
        e.text = str(texto)
    return e


def _rate_el(pai: ET.Element, fps: float) -> None:
    base, ntsc = _rate(fps)
    r = _sub(pai, "rate")
    _sub(r, "timebase", base)
    _sub(r, "ntsc", ntsc)


def _file_el(pai: ET.Element, fid: str, caminho: str, sonda: dict, fps_tl: float) -> None:
    fps = float(sonda.get("fps") or fps_tl)
    base, _ = _rate(fps)
    tc = sonda.get("tc") or "00:00:00:00"
    f = _sub(pai, "file", id=fid)
    _sub(f, "name", os.path.basename(caminho))
    _sub(f, "pathurl", "file://localhost" + urllib.parse.quote(como_o_disco_lista(caminho)))
    _rate_el(f, fps)
    if sonda.get("dur_s"):
        _sub(f, "duration", int(round(float(sonda["dur_s"]) * fps)))
    t = _sub(f, "timecode")
    _rate_el(t, fps)
    _sub(t, "string", tc)
    _sub(t, "frame", _tc_quadros(tc, base, ";" in tc))
    _sub(t, "displayformat", "DF" if ";" in tc else "NDF")
    v = _sub(_sub(f, "media"), "video")
    sc = _sub(v, "samplecharacteristics")
    _rate_el(sc, fps)
    _sub(sc, "width", sonda.get("w") or 1920)
    _sub(sc, "height", sonda.get("h") or 1080)


def escrever(leitura: dict, saida: str, sondar, achar_daily, raster: tuple[int, int] | None = None) -> dict:
    """`leitura` = `aaf.parser.parse_aaf(...)`; `sondar(caminho)` = `prproj.originais.sondar`; `achar_daily(seg)` = o
    arquivo do daily nesta máquina (`media.matcher._daily_do_segmento`). Devolve {planos, sem_daily, nao_traduzido}."""
    fps_tl = float(leitura["timeline_fps"])
    base_tl, _ = _rate(fps_tl)
    df_tl = bool(leitura.get("timeline_drop_frame"))
    raiz = ET.Element("xmeml", version="4")
    seq = _sub(raiz, "sequence", id="sequence-1")
    _sub(seq, "name", leitura.get("composition_name") or "MC")
    _rate_el(seq, fps_tl)
    tc = _sub(seq, "timecode")
    _rate_el(tc, fps_tl)
    _sub(tc, "string", leitura.get("timeline_start_tc") or "01:00:00:00")
    _sub(tc, "frame", leitura.get("timeline_start_frames") or 0)
    _sub(tc, "displayformat", "DF" if df_tl else "NDF")
    video = _sub(_sub(seq, "media"), "video")
    trilhas: dict[int, ET.Element] = {}
    ids: dict[str, str] = {}
    ret = {"planos": 0, "sem_daily": [], "nao_traduzido": []}
    fim_seq = 0
    primeiro_daily: list[str] = []
    for n, seg in enumerate(leitura["segments"]):
        if seg.get("is_audio") or seg.get("is_gap") or seg.get("is_transition") or seg.get("is_effect"):
            continue
        tr = int(seg.get("track") or 1)
        if tr not in trilhas:
            for k in range(1, tr + 1):
                if k not in trilhas:
                    trilhas[k] = _sub(video, "track")
        ini = _tc_quadros(seg["timeline_tc_in"], base_tl, df_tl)
        fim = ini + int(seg["duration_frames"])
        fim_seq = max(fim_seq, fim)
        if seg.get("has_motion_effect") or seg.get("has_reframe") or (seg.get("speed_ratio") or 1.0) != 1.0:
            ret["nao_traduzido"].append({"plano": n, "clip": seg.get("clip_name"), "tl": seg["timeline_tc_in"]})
        daily = achar_daily(seg)
        if not daily:
            ret["sem_daily"].append({"plano": n, "clip": seg.get("clip_name"), "tl": seg["timeline_tc_in"]})
            continue
        ci = _sub(trilhas[tr], "clipitem", id=f"clipitem-{n}")
        _sub(ci, "name", seg.get("clip_name") or os.path.basename(daily))
        _sub(ci, "enabled", "TRUE")
        dur_fonte = (seg.get("media_ref") or {}).get("source_duration_frames")
        if dur_fonte:
            _sub(ci, "duration", int(dur_fonte))
        _rate_el(ci, fps_tl)
        _sub(ci, "start", ini)
        _sub(ci, "end", fim)
        entra = int(seg.get("source_start_frames") or 0)
        _sub(ci, "in", entra)
        _sub(ci, "out", entra + int(seg["duration_frames"]))
        chave = os.path.normcase(daily)
        primeiro_daily[:] = primeiro_daily or [daily]
        if chave in ids:
            _sub(ci, "file", id=ids[chave])
        else:
            ids[chave] = f"file-{len(ids) + 1}"
            _file_el(ci, ids[chave], daily, sondar(daily), fps_tl)
        ret["planos"] += 1
    _sub(seq, "duration", fim_seq)
    # ⛔ o `bl-conform` 7.0.3 recusa o xmeml sem `media/video/format` ("Element 'format' not found", e1624). O raster da
    # montagem não vem na leitura do AAF: vale o do 1º daily (o do projeto do MC, no offline).
    w, h = raster or next(((sondar(d).get("w"), sondar(d).get("h")) for d in primeiro_daily), (1920, 1080))
    fmt = ET.Element("format")
    sc = _sub(fmt, "samplecharacteristics")
    _rate_el(sc, fps_tl)
    _sub(sc, "width", w or 1920)
    _sub(sc, "height", h or 1080)
    _sub(sc, "pixelaspectratio", "square")
    _sub(sc, "fielddominance", "none")
    video.insert(0, fmt)
    ET.indent(raiz)
    with open(saida, "w", encoding="utf-8") as fh:        # o cabeçalho do xmeml do Premiere, que o bl-conform lê
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        fh.write(ET.tostring(raiz, encoding="unicode"))
        fh.write("\n")
    return ret


def raster(xml: str) -> tuple[int, int]:
    """O raster da sequência do xmeml (o `media/video/format` que o `escrever` põe): o da scene que o `bl-conform` cria."""
    sc = ET.parse(xml).getroot().find("./sequence/media/video/format/samplecharacteristics")
    if sc is None:
        return 1920, 1080
    return int(sc.findtext("width") or 1920), int(sc.findtext("height") or 1080)


def estabilizados(leitura: dict, achar_daily, w: int, h: int) -> list[dict]:
    """Os planos com o Stabilize do MC que viram o tracker nativo no Baselight (`blg_estab`; laboratório de 2026-11-23,
    PRODUCAO-A C011/C013, igual ao render do MC). A mesma regra do Resolve (`estabilizacao.traduzivel`: o tracker lido
    e sem velocidade). Só os planos que o `escrever` pôs no xmeml (os mesmos filtros e o daily achado); o início é o
    `<start>` do plano, o quadro em que o Baselight o põe. O rastreio vai em px do raster da scene."""
    from estabilizacao import dados_do_segmento, traduzivel

    fps_tl = float(leitura["timeline_fps"])
    base_tl, _ = _rate(fps_tl)
    df_tl = bool(leitura.get("timeline_drop_frame"))
    out = []
    for seg in leitura["segments"]:
        if seg.get("is_audio") or seg.get("is_gap") or seg.get("is_transition") or seg.get("is_effect"):
            continue
        if not traduzivel(seg) or not achar_daily(seg):
            continue
        d = dados_do_segmento(seg)
        n = int(seg["duration_frames"])
        if len(d["x"]) < n or len(d["y"]) < n:
            continue                       # rastreio mais curto que o plano: não se inventa ponto
        out.append({"inicio": _tc_quadros(seg["timeline_tc_in"], base_tl, df_tl), "quadros": n,
                    "clip": seg.get("clip_name"), "p_x": [float(x) * w for x in d["x"][:n]],
                    "p_y": [float(y) * h for y in d["y"][:n]], "zoom": float(d["zoom"]), "filtro": float(d["filtro"]),
                    "pos": [float(v) for v in d["pos"]], "w": w, "h": h})
    return out


def estabilizacao_fora(leitura: dict) -> list[dict]:
    """Os planos com um Stabilize que NÃO se traduz (velocidade, Region Stabilize, vários pontos, tracker ilegível) —
    para o `nao_traduzido` e o marker, nunca calado (antes, o plano ia ao Baselight sem estabilização e sem aviso)."""
    from estabilizacao import traduzivel

    base_tl, _ = _rate(float(leitura["timeline_fps"]))
    df_tl = bool(leitura.get("timeline_drop_frame"))
    return [{"clip": s.get("clip_name"), "tl": s["timeline_tc_in"],
             "inicio": _tc_quadros(s["timeline_tc_in"], base_tl, df_tl)} for s in leitura["segments"]
            if not (s.get("is_audio") or s.get("is_gap") or s.get("is_transition"))
            and any("STABIL" in (e.get("name") or "").upper() for e in (s.get("effects") or []))
            and not traduzivel(s)]
