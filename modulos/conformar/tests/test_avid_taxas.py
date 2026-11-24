"""O DRT do Avid fora de 23,976: a taxa do item da MXF gerenciada e a da TIMELINE.

Rodar:

    .venv-win/Scripts/python tests/test_avid_taxas.py

⛔ Medido no laboratório (A01, 2026-10-11, Media Composer 25.6 → Resolve 19.0.0b, Windows): a mesma
sequência de 4 cortes em projetos do Avid a 23,976 / 24 / 25 / 29,97p / 59,94i. Só a 23,976 passava:

1. A forma da MXF gerenciada veio de uma mídia a 23,976 e declarava essa taxa no `<Time>` de TODA
   MXF — a gerenciada de um projeto 24 ficava "could not be decoded" no render.
2. O export do Avid (`sessao_export._gerar`) não passava `timeline_size`, e é ele que liga no
   writer a taxa da timeline (`SequenceSetup`) e o início (`MediaExtents`): a timeline nascia a
   23,976 em qualquer taxa e, a 24, começava em 01:00:03:14 — o 1º corte ficava fora dela.

Com os dois consertos: 172/172 quadros no lugar nas cinco taxas, com a taxa e o TC certos.

Precisa do ffmpeg/ffprobe no PATH (gera a mídia sintética); sem ele, a parte 1 é pulada.
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))

from drp import writer as W  # noqa: E402

casos = 0
falhas: list[str] = []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ok  {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHOU  {nome}: {obtido!r} ≠ {esperado!r}")


def taxa_do_time(item: str) -> float | None:
    """O `FrameRate` (f64 LE) do blob `<Time>` do item do pool."""
    m = re.search(r"<Time>([0-9a-fA-F]+)</Time>", item)
    raw = bytes.fromhex(m.group(1)) if m else b""
    i = raw.find("FrameRate".encode("utf-16-be"))
    if i < 0:
        return None
    i += len("FrameRate".encode("utf-16-be"))
    return struct.unpack("<d", raw[i + 9:i + 17])[0]


def parte_1_writer() -> None:
    print("── 1. MXF gerenciada a 24: o item e a timeline ──")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("  ffmpeg/ffprobe fora do PATH — pulado")
        return
    with tempfile.TemporaryDirectory() as d:
        mxf = os.path.join(d, "B02_24.V1.mxf")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=24",
                        "-t", "2", "-c:v", "mpeg2video", "-pix_fmt", "yuv422p", "-timecode", "01:00:59:15",
                        "-f", "mxf", mxf], check=True, capture_output=True)
        seg = {"track": 1, "duration_frames": 24, "source_start_frames": 0, "source_fps": 24.0,
               "speed_ratio": 1.0, "is_gap": False, "is_transition": False, "effects": [],
               "clip_name": "B02_24", "timeline_tc_in": "00:00:00:00", "is_audio": False}
        mr = [{"segment_index": 0, "matched_path": mxf, "rejected": False}]
        saida = W.build_drt([seg], mr, os.path.join(d, "t.drt"), timeline_fps=24.0,
                            timeline_size=(1920, 1080))
        with zipfile.ZipFile(saida["output"]) as z:
            pool = z.read(next(n for n in z.namelist() if n.endswith("MpFolder.xml"))).decode()
    item = next(b for b in re.findall(r"<Sm2MpVideoClip\b.*?</Sm2MpVideoClip>", pool, re.S)
                if "<Name>B02_24.V1.mxf</Name>" in b)
    ok("⭐ o item da MXF declara 24, não os 23,976 da forma", round(taxa_do_time(item) or 0, 3), 24.0)
    tl = re.search(r"<Sm2MpTimelineClip\b.*?</Sm2MpTimelineClip>", pool, re.S).group(0)
    ext = re.search(r"<MediaExtents>([0-9a-fA-F]+)</MediaExtents>", tl).group(1)
    ok("⭐ a timeline começa em 3600 s (01:00:00:00 a 24), não nos 3603,6 s do esqueleto",
       round(struct.unpack("<dd", bytes.fromhex(ext))[0], 3), 3600.0)


def parte_2_sessao() -> None:
    print("── 2. o export do Avid passa o raster do projeto ──")
    import sessao_export as S
    import avb_bin.segmentos as seg
    import relink_avb

    capturado: dict = {}

    class _MC:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def esta_vivo(self):
            return True

        def projeto(self):
            return {"path": r"C:\Avid Projects\DLPC LAB 24\\", "type": "1080p/24", "width": 1920, "height": 1080}

        def bin_do_mob(self, _mob):
            return __file__                      # um arquivo que existe; a leitura é substituída abaixo

    class _Servico:
        def media_composer(self):
            return _MC()

    leitura = {"segments": [{"track": 1, "is_gap": False, "is_transition": False, "is_audio": False}],
               "timeline_fps": 24.0, "timeline_start_tc": "01:00:00:00", "composition_name": "LAB_CORTES_24",
               "masters": {}, "avisos": []}
    originais = (relink_avb.garantir_bin_no_disco, seg.ler_timeline_de_arquivo, seg.casamentos,
                 S.resolver_midia, seg.montar_midia, W.build_drt)
    try:
        relink_avb.garantir_bin_no_disco = lambda *_a, **_k: True
        seg.ler_timeline_de_arquivo = lambda *_a, **_k: leitura
        seg.casamentos = lambda *_a, **_k: []
        S.resolver_midia = lambda *_a, **_k: {"arquivos": {}, "offline": [], "na_gerenciada": set(),
                                              "indice": type("I", (), {"indices_lidos": 1,
                                                                       "pastas_sem_indice": 0})(),
                                              "gerenciados": {}}
        seg.montar_midia = lambda *_a, **_k: ([{}], [{"matched_path": "x"}], {})

        def _build(*_a, **k):
            capturado.update(k)
            return {"clips": []}
        W.build_drt = _build
        s = S.SessaoExport(_Servico())
        s._preparar("060a2b34-x")
        s._gerar("drt", os.path.join(tempfile.gettempdir(), "t.drt"), "LAB_CORTES_24", "")
    finally:
        (relink_avb.garantir_bin_no_disco, seg.ler_timeline_de_arquivo, seg.casamentos,
         S.resolver_midia, seg.montar_midia, W.build_drt) = originais
    ok("o raster do projeto foi lido do MC", s.raster, (1920, 1080))
    ok("⭐ e vai ao writer como timeline_size", capturado.get("timeline_size"), (1920, 1080))
    ok("com a taxa da sequência", capturado.get("timeline_fps"), 24.0)


def main() -> int:
    parte_1_writer()
    parte_2_sessao()
    print(f"\n{casos - len(falhas)}/{casos} ok")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
