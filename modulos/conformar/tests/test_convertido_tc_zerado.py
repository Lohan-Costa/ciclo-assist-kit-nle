"""O convertido de TC ZERADO não vira "original" calado (autor, 2026-10-31).

Rodar:

    .venv-win/Scripts/python tests/test_convertido_tc_zerado.py        (Mac: .venv/bin/python)

A pergunta do autor: "uma TL com vídeo original, teve conversão que errou o TC: arquivos com mesmo nome, extensão
diferente, mesma duração. Temos confiança no relink?" Medido (handoff de 2026-10-31): o `A001_C003.mov` (TC
10:00:00:00) na timeline e o `A001_C003.mp4` de mesma duração ao lado — com TC 00:00:00:00 ou sem TC, o casamento
o dava como o ORIGINAL e a timeline era trocada pelo convertido. O TC só era conferido com os dois ≠ 0, de propósito:
o zero é legítimo (banco `mxf/timecode.md`) e o DJI tem proxy 00:00:00:00 e original sem TC. Agora, projeto com TC
real + candidato zerado/ausente ("depende do disco", autor): o arquivo do projeto no disco FICA e o convertido sai
recusado com o motivo; sem ele (o R04: os 1024×540 convertidos sem TC, o J: dos Sony ausente) o convertido entra, com
a `duvida` (marcador "TC a conferir"); dois assim = empate, do editor. O DJI segue passando.

Os arquivos existem (vazios de verdade, bytes distintos); o ffprobe é fingido (`sondar` trocado).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from prproj import originais as O  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def v(tc, codec="prores", w=3840, h=2160, dur=12.0, fps=23.976):
    return {"ok": True, "w": w, "h": h, "codec": codec, "fps": fps, "dur_s": dur, "tc": tc}


def casar(proxy: str, arquivos: dict, projeto=None, proxy_no_disco=True, raizes=None):
    """`arquivos` = {nome relativo: o que o ffprobe diria}; `proxy` é um deles (ou não, se não está no disco)."""
    with tempfile.TemporaryDirectory() as d:
        reais = {}
        for c, info in arquivos.items():
            p = os.path.join(d, c)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if c != proxy or proxy_no_disco:
                with open(p, "wb") as f:
                    f.write(c.encode() * 1000)
            reais[p] = info
        px = os.path.join(d, proxy)
        indice = {}
        for p in reais:
            indice.setdefault(os.path.splitext(os.path.basename(p))[0].lower(), []).append(p)
        O._SONDA.clear()
        sonda = (lambda c: reais.get(c, {"ok": False}) if (c != px or proxy_no_disco) else {"ok": False})
        with mock.patch.object(O, "sondar", sonda), mock.patch.object(O, "mxf_completo", lambda c: True):
            r = O.casar_um(px, indice, projeto, [os.path.join(d, x) for x in raizes] if raizes else [d])
        rel = lambda x: os.path.relpath(x, d).replace(os.sep, "/") if x else None  # noqa: E731
        r["original"] = rel(r.get("original"))
        r["candidatos"] = [rel(x) for x in r.get("candidatos") or []]
        r["recusados"] = [(rel(c), m) for c, m in r.get("recusados") or []]
        return r


def main() -> int:
    MOV = "A/A001_C003.mov"
    print("── a TL usa o ORIGINAL (.mov, TC 10:00:00:00); o convertido .mp4 de mesma duração ao lado ──")
    r = casar(MOV, {MOV: v("10:00:00:00"), "B/A001_C003.mp4": v("00:00:00:00", codec="h264", w=1920, h=1080)})
    ok("⭐ convertido com TC 00:00:00:00: NÃO troca a TL — fica o .mov", (r["estado"], r["original"]),
       ("proprio", MOV))
    ok("…o .mp4 sai recusado, com o TC zerado e o do projeto no motivo",
       any(c == "B/A001_C003.mp4" and "zerado" in m and "10:00:00:00" in m for c, m in r["recusados"]), True)

    r = casar(MOV, {MOV: v("10:00:00:00"), "B/A001_C003.mp4": v(None, codec="h264", w=1920, h=1080)})
    ok("⭐ convertido SEM TC: idem, fica o .mov", (r["estado"], r["original"]), ("proprio", MOV))
    ok("…o motivo diz ausente", any("ausente" in m for _c, m in r["recusados"]), True)

    r = casar(MOV, {MOV: v("10:00:00:00"), "B/A001_C003.mp4": v(None, codec="h264", w=1920, h=1080)},
              raizes=["B"])
    ok("o .mov fora das pastas indicadas: ainda assim o convertido NÃO entra (sem original, a TL fica no .mov)",
       (r["estado"], r["original"], r.get("duvida")), ("sem_original", None, None))

    r = casar(MOV, {MOV: v("10:00:00:00"), "B/A001_C003.mp4": v("01:00:00:00", codec="h264", w=1920, h=1080)})
    ok("convertido com TC errado ≠ 0: continua recusado, fica o .mov", (r["estado"], r["original"]),
       ("proprio", MOV))

    r = casar(MOV, {MOV: v("10:00:00:00"), "B/A001_C003.mp4": v("00:00:00:00")})
    ok("convertido zerado de MESMO codec e raster: continua 'cópia do proxy', fica o .mov",
       (r["estado"], r["original"]), ("proprio", MOV))

    print("── a conversão para baixo que MANTEVE o TC (o DCI_CORTE do lab B110) ──")
    r = casar(MOV, {MOV: v("10:00:00:00", w=4096, h=2160),
                    "B/A001_C003.mp4": v("10:00:00:00", codec="h264", w=1920, h=1012)})
    ok("⭐ convertido 1920 de TC igual, com o 4K do projeto no disco: fica o .mov", (r["estado"], r["original"]),
       ("proprio", MOV))
    ok("…recusado como conversão, com os dois rasters",
       any("menor que o arquivo do projeto (1920×1012 × 4096×2160)" in m for _c, m in r["recusados"]), True)
    r = casar(MOV, {MOV: v("10:00:00:00", w=4096, h=2160),
                    "B/A001_C003.mp4": v("10:00:00:00", codec="h264", w=1920, h=1012)},
              projeto={"dur_s": 12.0, "tc_quadros": 10 * 3600 * 24, "fps": 23.976, "w": 4096, "h": 2160,
                       "fourcc": "apcn"}, proxy_no_disco=False)
    ok("o mesmo sem o 4K no disco: entra o convertido (a única mídia)", (r["estado"], r["original"]),
       ("original", "B/A001_C003.mp4"))
    AN = "P/A002_C001.mov"
    r = casar(AN, {AN: v("10:00:00:00", w=1920, h=1080), "O/A002_C001.mov": v("10:00:00:00", codec="dnxhd",
                                                                                w=1440, h=1080)})
    ok("anamórfico 1440×1080 com proxy 1920×1080 (menor só numa medida): original, como antes",
       (r["estado"], r["original"]), ("original", "O/A002_C001.mov"))

    print("── o fluxo de proxy de sempre ──")
    PX = "P/A001_C003.mov"
    proxy = v("10:00:00:00", codec="prores", w=1920, h=1080)
    r = casar(PX, {PX: proxy, "O/A001_C003.mxf": v("10:00:00:00", codec="dnxhd")})
    ok("proxy e original de TC igual: original", (r["estado"], r["original"]), ("original", "O/A001_C003.mxf"))

    r = casar(PX, {PX: proxy, "O/A001_C003.mxf": v("10:00:00:00", codec="dnxhd"),
                   "X/A001_C003.mp4": v("00:00:00:00", codec="h264", w=1280, h=720)})
    ok("⭐ um confere o TC e outro é zerado: o que confere vence (sem empate)",
       (r["estado"], r["original"]), ("original", "O/A001_C003.mxf"))
    ok("…e o zerado sai recusado com o motivo",
       any(c == "X/A001_C003.mp4" and "zerado" in m for c, m in r["recusados"]), True)

    print("── o DJI: o zero é do lado do PROJETO ──")
    DJ = "P/DJI_0001.MOV"
    r = casar(DJ, {DJ: v("00:00:00:00", w=1920, h=1080, fps=29.97),
                   "O/DJI_0001.MP4": v(None, codec="hevc", fps=29.97)})
    ok("proxy 00:00:00:00, original sem TC: original (como antes)", (r["estado"], r["original"]),
       ("original", "O/DJI_0001.MP4"))
    r = casar(DJ, {DJ: v(None, w=1920, h=1080, fps=29.97), "O/DJI_0001.MP4": v(None, codec="hevc", fps=29.97)})
    ok("proxy e original sem TC: original", (r["estado"], r["original"]), ("original", "O/DJI_0001.MP4"))

    print("── sem o arquivo do projeto na máquina (o R04: o J: dos Sony ausente) — a prova vem do .prproj ──")
    PROJ = {"dur_s": 12.0, "tc_quadros": 10 * 3600 * 24, "fps": 23.976, "w": 3840, "h": 2160, "fourcc": "apcn"}
    r = casar(MOV, {MOV: v("10:00:00:00"), "B/A001_C003.mp4": v(None, codec="h264", w=1024, h=540)},
              projeto=PROJ, proxy_no_disco=False)
    ok("⭐ o convertido sem TC é a ÚNICA mídia: entra (nenhum segmento se perde)",
       (r["estado"], r["original"], r["conferido_por"]), ("original", "B/A001_C003.mp4", "projeto"))
    ok("…com a dúvida à vista (o marcador 'TC a conferir')", "ausente" in (r.get("duvida") or ""), True)
    r = casar(MOV, {MOV: v("10:00:00:00"), "B/A001_C003.mp4": v("00:00:00:00", codec="h264", w=1024, h=540),
                    "C/A001_C003.mp4": v(None, codec="h264", w=1280, h=720)}, projeto=PROJ, proxy_no_disco=False)
    ok("dois convertidos de TC zerado/ausente, sem o do projeto: empate, do editor", (r["estado"], r["original"]),
       ("ambiguo", None))
    r = casar(MOV, {MOV: v("10:00:00:00"), "B/A001_C003.mp4": v("10:00:00:00", codec="h264", w=1024, h=540)},
              projeto=PROJ, proxy_no_disco=False)
    ok("convertido que manteve o TC: original, sem dúvida", (r["estado"], r.get("duvida")), ("original", None))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
