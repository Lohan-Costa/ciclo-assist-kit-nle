"""WAV float 32 ESTÉREO tem modelo de injeção no MC (2026-10-13).

Rodar:

    .venv/bin/python tests/test_modelo_audio_float_2ch.py        (Windows: .venv-win/Scripts/python)

O SFX `535944__marksayer…wav` do curta PRODUCAO-A (WAV float 32, 2 canais) ficava de fora do relink: "sem modelo".
O modelo `audio_10_32bit_2ch.avb` veio de uma bin do MC 25.6 no Windows com esse arquivo linkado
(`tools/neutralizar_modelo_audio.py`: locator WINF reescrito como FILE, identidade do projeto tirada). Comparado campo a
campo com a bin do MC: formato, taxa, samples, `_AMD_SOURCE_LENGTH`, data do arquivo e caminho `G//…` iguais.

O arquivo do teste é gerado aqui (ffmpeg), pequeno.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_bin import audio  # noqa: E402
from avb_export import media_bin as MB  # noqa: E402
from avb_export.reader import topen  # noqa: E402
from media import fftools  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_float2_"))
    wav = tmp / "sfx_float32_estereo.wav"
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=2",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le", str(wav)], check=True, **fftools.SEM_JANELA)

    ok("chave do arquivo", MB._probe_key(str(wav)), ("audio", 10, 32, 2))
    ok("modelo embarcado", ("audio", 10, 32, 2) in MB.load_bundled_templates(), True)

    saida = tmp / "injetado.avb"
    r = audio.autorar_masters([str(wav)], str(saida), fps=24.0)
    ok("sem 'sem modelo'", r["sem_template"], [])
    ok("um clipe", r["clipes"], 1)

    with topen(str(saida)) as f:
        pcma = next(m for m in f.content.mobs
                    if type(m.property_data.get("descriptor")).__name__ == "PCMADescriptor")
        d = pcma.property_data["descriptor"].property_data
        loc = d["physical_media"].property_data["locator"].property_data
        ok("nome do clipe", pcma.property_data.get("name"), wav.name)
        ok("formato", (d["coding_format"], d["quantization_bits"], d["channels"], d["block_align"]), (10, 32, 2, 8))
        ok("samples", (d["length"], d["sample_rate"]), (96000, 48000.0))
        ok("caminho na forma do Avid", loc.get("path_posix"), audio.forma_avid(str(wav)))
        ok("projeto neutro", pcma.property_data["attributes"].get("_PJ"), "TEMPLATE")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
