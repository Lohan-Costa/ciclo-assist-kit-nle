"""Vídeo → ProRes Proxy 1080 pelo DaVinci Resolve Studio: o proxy do Premiere (P1).

Plano: `docs/plano/2026-11-07-premiere-proxy-e-merged.md`. O mesmo motor do OP-Atom
(`resolve_opatom._rodar`: processo filho, a dança do preset NOSSO, a fila do editor intocada), com três
diferenças, todas medidas na P0 (Studio 21.1, macOS, 2026-11-07; banco
`plugins/resolve-scripting/api-scripting.md`, "Render ProRes Proxy"):

- ⛔ **Pelo preset, nunca só pela API.** Só com `SetCurrentRenderFormatAndCodec` + `SetRenderSettings` o nome
  sai com sufixo (`…_00030000.mov`) e **4 pistas mono viram 2 canais** — e o Premiere RECUSA proxy com outro
  número de canais. O preset do OP-Atom traz o nome da origem e "canais iguais aos da origem"; carregado e
  CONFERIDO (mxf, modo 0), só então o codec vira `mov`/`ProRes422P`.
- ⛔ **Uma timeline do tamanho do proxy por PROPORÇÃO.** DCI 4096×2160 numa timeline 1920×1080 sai com tarja.
  O proxy é 1080 fixo (decisão do autor): largura = 1080 × a proporção, par.
- ⛔⛔ **A conferência do par é NOSSA.** O `attachProxy` do Premiere só confere o número de canais e aceita
  calado outra proporção e até OUTRO MATERIAL (P0.2). Cada proxy é comparado ao seu original — taxa, nº de
  quadros, TC, canais, proporção — e o que não bate vai em `problemas` e não segue como proxy.

O destino é o que o EDITOR disse (decisão do autor: perguntar no pedido) — sem padrão.
"""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import resolve_opatom as _op

#: O que o Resolve lê e vale a pena converter. RAW de câmera entra (é o caso de uso do proxy).
VIDEOS = _op.VIDEOS | {".braw", ".r3d"}

ALTURA = 1080
CODEC = "ProRes422P"
ConversaoFalhou = _op.ConversaoFalhou


def videos_da_pasta(pasta: str | Path) -> list[Path]:
    return _op.videos_da_pasta(pasta, VIDEOS)


def tamanho_do_proxy(largura: int, altura: int) -> tuple[int, int]:
    """1080 de altura e a mesma proporção, largura par (4096×2160 → 2048×1080; 3840×2160 → 1920×1080)."""
    return int(round(largura * ALTURA / altura / 2)) * 2, ALTURA


def _taxa(fr: str | None) -> float:
    try:
        n, d = (fr or "0/1").split("/")
        return int(n) / int(d)
    except (ValueError, ZeroDivisionError):
        return 0.0


def sondar(arquivo: Path) -> dict[str, Any]:
    """O que importa para comparar original e proxy: taxa, tamanho, quadros, TC, canais, codec."""
    from .binarios import achar
    p = subprocess.run([achar("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,profile,r_frame_rate,width,height,nb_frames,channels"
                        ":stream_tags=timecode:format=duration:format_tags=timecode",
                        "-of", "json", str(arquivo)],
                       capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=60)
    d = json.loads(p.stdout or "{}")
    sts = d.get("streams") or []
    v = next((s for s in sts if s.get("codec_type") == "video"), {})
    tc = next((s.get("tags", {}).get("timecode") for s in sts if (s.get("tags") or {}).get("timecode")), None)
    tc = tc or (d.get("format") or {}).get("tags", {}).get("timecode")
    quadros = int(v["nb_frames"]) if str(v.get("nb_frames", "")).isdigit() else None
    if quadros is None and v.get("r_frame_rate"):
        try:
            quadros = round(float((d.get("format") or {}).get("duration")) * _taxa(v["r_frame_rate"]))
        except (TypeError, ValueError):
            quadros = None
    return {"taxa": v.get("r_frame_rate"), "largura": v.get("width"), "altura": v.get("height"),
            "quadros": quadros, "tc": tc, "codec": v.get("codec_name"), "perfil": v.get("profile"),
            "canais": sum(int(s.get("channels") or 0) for s in sts if s.get("codec_type") == "audio")}


def conferir_videos(videos: list[Path], sondas: dict[Path, dict] | None = None) -> tuple[str, dict[str, Any]]:
    """("", plano) quando os vídeos podem ir; senão (motivo, {}). O plano agrupa por tamanho do proxy."""
    if not videos:
        return "não há vídeo (.mov, .mp4, .mxf, .braw, .r3d) nessa pasta", {}
    nomes: dict[str, Path] = {}
    for v in videos:
        if v.stem.lower() in nomes:
            return (f"dois vídeos com o mesmo nome ({nomes[v.stem.lower()].name} e {v.name}) — o proxy de um "
                    "escreveria por cima do outro"), {}
        nomes[v.stem.lower()] = v
    sondas = sondas if sondas is not None else {v: sondar(v) for v in videos}
    sem = [v.name for v in videos if not sondas[v].get("largura") or not sondas[v].get("taxa")]
    if sem:
        return f"não consegui ler o vídeo de: {', '.join(sem[:4])}", {}
    taxas = {sondas[v]["taxa"] for v in videos}
    if len(taxas) > 1:
        lista = "; ".join(f"{v.name}: {sondas[v]['taxa']}" for v in videos[:6])
        return f"os vídeos misturam taxas ({lista}) — converta uma taxa por vez", {}
    taxa = taxas.pop()
    if taxa not in _op.TAXAS:
        return f"taxa {taxa} ainda não medida aqui", {}
    grupos: dict[tuple[int, int], list[Path]] = {}
    for v in videos:
        grupos.setdefault(tamanho_do_proxy(sondas[v]["largura"], sondas[v]["altura"]), []).append(v)
    return "", {"taxa": _op.TAXAS[taxa],
                "grupos": [{"largura": w, "altura": h, "videos": vs} for (w, h), vs in grupos.items()],
                "sondas": sondas}


def destino_do(destino: Path, video: Path) -> Path:
    return destino / (video.stem + ".mov")


def conferir_destino(destino: Path, videos: list[Path]) -> str:
    """"" quando dá para gravar; senão o motivo. Nunca por cima de um arquivo que já está lá."""
    if destino.exists() and not destino.is_dir():
        return f"{destino} é um arquivo, não uma pasta"
    if any(v.parent.resolve() == destino.resolve() for v in videos if destino.exists()):
        return f"{destino} é a pasta dos próprios originais — o proxy tem o mesmo nome e iria para o lado dele"
    ja = [destino_do(destino, v).name for v in videos if destino_do(destino, v).exists()]
    if ja:
        return f"já há proxy com esse nome em {destino}: {', '.join(ja[:4])} — escolha outra pasta"
    return ""


def conferir_par(original: dict, proxy: dict) -> list[str]:
    """O que o Premiere aceitaria calado e não devia: tudo o que difere entre o original e o proxy."""
    p = []
    if proxy.get("codec") != "prores" or "proxy" not in str(proxy.get("perfil") or "").lower():
        p.append(f"não é ProRes Proxy ({proxy.get('codec')} {proxy.get('perfil')})")
    if proxy.get("taxa") != original.get("taxa"):
        p.append(f"taxa {proxy.get('taxa')} (original {original.get('taxa')})")
    if proxy.get("quadros") != original.get("quadros"):
        p.append(f"{proxy.get('quadros')} quadros (original {original.get('quadros')})")
    if (proxy.get("tc") or "") != (original.get("tc") or ""):
        p.append(f"TC {proxy.get('tc')} (original {original.get('tc')})")
    if proxy.get("canais") != original.get("canais"):
        p.append(f"{proxy.get('canais')} canais de som (original {original.get('canais')}) — o Premiere recusa")
    esperado = tamanho_do_proxy(original["largura"], original["altura"]) if original.get("largura") else None
    if esperado and (proxy.get("largura"), proxy.get("altura")) != esperado:
        p.append(f"{proxy.get('largura')}x{proxy.get('altura')} (esperado {esperado[0]}x{esperado[1]})")
    return p


def conferir_saida(destino: Path, videos: list[Path], sondas: dict[Path, dict]) -> dict[str, Any]:
    pares, problemas = [], []
    for v in videos:
        alvo = destino_do(destino, v)
        if not alvo.exists():
            pares.append({"original": str(v), "proxy": "", "ok": False, "problemas": ["o proxy não caiu no disco"]})
        else:
            pp = conferir_par(sondas[v], sondar(alvo))
            pares.append({"original": str(v), "proxy": str(alvo), "ok": not pp, "problemas": pp})
        if pares[-1]["problemas"]:
            problemas.append(f"{v.name}: " + "; ".join(pares[-1]["problemas"]))
    return {"pares": pares, "problemas": problemas, "proxies": sum(1 for x in pares if x["ok"])}


def gravar_manifesto(destino: Path, pares: list[dict], sondas: dict[Path, dict]) -> str:
    """⭐ O MANIFESTO da conversão (plano 2026-11-26, etapa 2): "o original X virou o proxy Y, com estas características"
    — `ciclo-conversao.json` ao lado dos proxies; a Carta o lê ao anexar a pasta (`carta/relacoes.py`). Só os pares que
    passaram na conferência. Devolve o caminho, ou "" (sem par bom, ou sem como gravar: o proxy segue, é só o registro)."""
    from .carta import relacoes
    from .midia import identidade as _id
    bons = []
    for p in pares:
        if not p.get("ok"):
            continue
        o, c = Path(p["original"]), Path(p["proxy"])
        so = dict(sondas.get(o) or sondar(o))
        sc = sondar(c)
        so.update(arquivo=str(o), impressao=_id.impressao(o))
        sc.update(arquivo=str(c), impressao=_id.impressao(c))
        bons.append({"original": so, "convertido": sc})
    if not bons:
        return ""
    try:
        return str(relacoes.escrever_manifesto(destino, bons, "resolve_proxy"))
    except OSError:
        return ""


def converter(projeto: str, videos: list[Path], destino: Path, *,
              relatar: Callable[[str, float | None, str], None] | None = None,
              prazo_s: float = 3600) -> dict[str, Any]:
    """Renderiza um ProRes Proxy 1080 de cada vídeo em `destino` e confere cada par."""
    relatar = relatar or (lambda *_: None)
    motivo, plano = conferir_videos(videos)
    if motivo:
        raise ConversaoFalhou(motivo)
    motivo = conferir_destino(destino, videos)
    if motivo:
        raise ConversaoFalhou(motivo)
    agora = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
    grupos = [{"videos": [str(v) for v in g["videos"]], "largura": g["largura"], "altura": g["altura"],
               "timeline": f"PROXY {agora} {g['largura']}x{g['altura']}"} for g in plano["grupos"]]
    pedido = {"projeto": projeto, "videos": [str(v) for v in videos], "destino": str(destino),
              "codec": CODEC, "formato_saida": "mov", "taxa": plano["taxa"],
              "largura": grupos[0]["largura"], "altura": ALTURA, "grupos": grupos,
              "preset": _op.PRESET, "preset_arq": str(_op.PRESET_ARQ), "timeline": grupos[0]["timeline"],
              "prazo": prazo_s, "rotulo": "ProRes Proxy"}
    r = _op._rodar(pedido, relatar)
    if r.get("status") != "Complete":
        raise ConversaoFalhou(f"o render terminou como '{r.get('status')}' (pasta {destino})")
    saida = conferir_saida(destino, videos, plano["sondas"])
    saida["manifesto"] = gravar_manifesto(destino, saida["pares"], plano["sondas"])
    return {"pasta": str(destino), "taxa": plano["taxa"], "segundos": r.get("segundos"),
            "grupos": [{"tamanho": f"{g['largura']}x{g['altura']}", "clipes": len(g["videos"])} for g in grupos],
            "timelines_no_resolve": [g["timeline"] for g in r.get("grupos") or []], **saida}
