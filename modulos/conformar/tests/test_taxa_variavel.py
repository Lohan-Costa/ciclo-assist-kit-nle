"""Vídeo de TAXA VARIÁVEL no caminho Premiere → Resolve (2026-10-05).

Rodar:

    .venv/bin/python tests/test_taxa_variavel.py        (Windows: .venv-win/Scripts/python)

⛔ O insert de celular do interfone (PRODB, 01:22:49:07) entrava 27 quadros adiantado no Resolve.
O arquivo tem 1.387 quadros e 25 q/s no cabeçalho, com quadros faltando (média 24,0); o Premiere o
conta a 24,0118 q/s, o Resolve a 25. O DRT mandava a entrada na conta do Premiere.

Medido no Resolve 19 com vídeos sintéticos que levam o número do quadro em código de barras
(`04 SINTETICOS/GERADORES/gerar_taxas.py`): o Resolve mostra floor(In × taxa do CABEÇALHO / taxa da
timeline) — exato com taxa fixa (23,976, 25, 29,97, 59,94: 64 medições); com taxa variável, de 0 a
17 quadros fora. Daí: a entrada pela taxa do cabeçalho, e um marcador "conferir" no plano.

Os vídeos do teste são gerados aqui (ffmpeg), pequenos: o teste não depende de mídia de projeto.
"""

from __future__ import annotations

import binascii
import os
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp.writer import build_drt  # noqa: E402
from media import fftools, sonda  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def gerar(destino: str, variavel: bool) -> None:
    """4 s a 25 q/s; a variável perde 1 quadro a cada 25 (como o celular: média 24)."""
    vf = ["select='not(eq(mod(n\\,25)\\,1))'"] if variavel else []
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=25:d=4",
                    *(["-vf", ",".join(vf), "-fps_mode", "passthrough"] if vf else []),
                    "-c:v", "libx264", "-preset", "ultrafast", destino], check=True, **fftools.SEM_JANELA)


def entrada_no_drt(arquivo: str, quadro_premiere: int, fps_premiere: float, kf: dict | None = None):
    """O `In` do clipe no DRT; com `kf` (keyframes da leitura), `(In, quadros dos keyframes)`."""
    efeitos = [{"name": "Motion", "category": "geometric", "reproducible": True,
                "params": {"pos_x": 0.0, "pos_y": 0.0, "kf": kf}}] if kf else []
    seg = {"timeline_tc_in": "00:00:00:00", "timeline_tc_out": "00:00:01:00", "duration_frames": 24,
           "source_start_frames": quadro_premiere, "source_fps": fps_premiere, "clip_name": os.path.basename(arquivo),
           "track": 1, "is_gap": False, "is_transition": False, "is_effect": False, "is_audio": False,
           "speed_ratio": 24.0 / fps_premiere, "conform_ratio": 24.0 / fps_premiere, "relative_speed": 1.0,
           "motion_class": "conform", "effects": efeitos, "disabled": False,
           "media_ref": {"local_path": arquivo, "descriptor_type": "prproj", "source_fps": fps_premiere}}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.drt")
        build_drt([seg], [{"segment_index": 0, "matched_path": arquivo}], p, timeline_name="x",
                  timeline_fps=24.0, timeline_start_frames=0, timeline_size=(1920, 1080))
        with zipfile.ZipFile(p) as z:
            txt = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
    m = re.search(r"<Sm2TiVideoClip\b.*?<In>(\d+)(?:\|[0-9a-f]+)?</In>", txt, re.S)
    entrada = int(m.group(1)) if m else 0
    if not kf:
        return entrada
    efb = binascii.unhexlify(re.search(r"<EffectFiltersBA>([0-9a-fA-F]+)</EffectFiltersBA>", txt).group(1))
    # registro de keyframe de posição: [u32 quadro][u16 0][u16 0x0C][f64 valor]
    quadros = [struct.unpack("<I", efb[k:k + 4])[0] for k in range(len(efb) - 16)
               if efb[k + 4:k + 8] == b"\x00\x00\x0c\x00"]
    return entrada, quadros


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        fixa, variavel = os.path.join(d, "fixa.mp4"), os.path.join(d, "variavel.mp4")
        gerar(fixa, False)
        gerar(variavel, True)

        print("── o detector ──")
        ok("taxa fixa: não é variável", sonda.taxa_variavel(fixa), None)
        t = sonda.taxa_variavel(variavel)
        ok("quadros faltando: variável, com o cabeçalho (25) e a média (~24)",
           (t is not None, round(t[0]) if t else None, round(t[1]) if t else None), (True, 25, 24))

        print("── a entrada no DRT ──")
        # O Premiere conta o variável pela média dele: 96 quadros em 4 s = 24 q/s. Quadro 48 do arquivo.
        ok("variável: a entrada vai pela taxa do CABEÇALHO (48 × 24/25 = 46), não pela do Premiere (48)",
           entrada_no_drt(variavel, 48, 24.0), 46)
        ok("fixa a 25, o Premiere também em 25: a regra de antes (48 × 24/25 = 46)",
           entrada_no_drt(fixa, 48, 25.0), 46)

        print("── os keyframes andam junto com a entrada ──")
        # ⛔ 2026-10-08 (PRODB, 01:22:49): o rastreamento do insert ficou na conta do Premiere
        # (677) e a entrada foi a 650 — o insert parado por 27 quadros. A leitura conta o keyframe
        # como entrada dela (fonte × speed_ratio) + quadro dentro do plano.
        kf = {"pos_x": [(48, 0.1), (60, 0.2), (71, 0.15)], "pos_y": [(48, 0.0), (60, 0.05), (71, 0.0)]}
        ok("variável: entrada 46 e keyframes 46/58/69 (cada um nos mesmos quadros do plano)",
           entrada_no_drt(variavel, 48, 24.0, kf), (46, [46, 58, 69, 46, 58, 69]))
        kf25 = {"pos_x": [(46, 0.1), (58, 0.2)]}
        ok("fixa: os keyframes ficam onde a leitura pôs (sem deslocamento)",
           entrada_no_drt(fixa, 48, 25.0, kf25), (46, [46, 58]))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
