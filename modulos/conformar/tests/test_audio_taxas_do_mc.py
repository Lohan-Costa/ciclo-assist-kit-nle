"""O áudio INJETADO sai na taxa do PROJETO, igual ao que o Media Composer linka (B001 no AVB, 2026-10-31).

Rodar:

    .venv/bin/python tests/test_audio_taxas_do_mc.py        (Windows: .venv-win/Scripts/python)

⛔ Até 2026-10-31 só o start usava o `fps`: num projeto 25 o master saía a 23,976 com 192 quadros (o MC grava 200), a
fonte de mídia com o Timecode e a duração do MOLDE, e nada avisava. O conserto é `clone_generic._patch_taxa_da_cadeia`
+ a prova `conferir_taxa_do_audio`.

Os GABARITOS (`tests/dados/gabaritos_audio_mc/`) são bins do PRÓPRIO MC (2024.6, Windows): o mesmo WAV de 8 s, 4 canais
24 bits, sem cena, com `time_reference` = 01:00:08:00, linkado por `LinkFile` em projetos 1080p/23.976, 1080p/24,
1080p/25 e 1080i/59.94 (29,97 NDF e DF), o diálogo "Audio Start-Time Options" respondido com a taxa do projeto. O WAV
do teste é gerado aqui com o mesmo número de amostras e o mesmo bext — o conteúdo não entra em nenhum campo comparado.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_bin import audio  # noqa: E402
from avb_export.reader import topen  # noqa: E402
from media import fftools  # noqa: E402

GABARITOS = Path(__file__).resolve().parent / "dados" / "gabaritos_audio_mc"
CASOS = [("2398", 24000 / 1001, False), ("24", 24.0, False), ("25", 25.0, False),
         ("2997ndf", 30000 / 1001, False), ("2997df", 30000 / 1001, True)]

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(rotulo)
        print(f"  ✗ {rotulo}\n      veio     {obtido}\n      esperava {esperado}")


def cadeia(arq: str) -> list:
    """(papel, classe, edit_rate, length, start_time, fps, flags) de cada componente do clipe, em ordem estável."""
    out = []
    with topen(arq) as f:
        for m in f.content.mobs:
            if not (m.name or "").startswith("B06"):
                continue
            pd = m.property_data
            d = pd.get("descriptor")
            papel = "master" if pd.get("mob_type_id") == 2 else type(d).__name__
            out.append((papel, "mob", round(float(pd.get("edit_rate") or 0), 3), pd.get("length")))
            for t in pd.get("tracks") or []:
                c = t.property_data.get("component")
                for x in [c] + (list(c.property_data.get("components") or []) if type(c).__name__ == "Sequence" else []):
                    xp = x.property_data
                    out.append((papel, type(x).__name__, round(float(xp.get("edit_rate") or 0), 3), xp.get("length"),
                                xp.get("start_time"), xp.get("fps"), xp.get("flags")))
    return sorted(out, key=str)


def main() -> int:
    if not GABARITOS.is_dir():   # bins do MC gravadas no SSD: não vão à cópia pública
        print(f"pulou: sem os gabaritos do MC em {GABARITOS} (ficam no repositório privado)")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_taxas_"))
    wav = tmp / "B06_SOM_WAV-BWF.wav"
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=4.0",
                    "-t", "8", "-c:a", "pcm_s24le", "-write_bext", "1", "-metadata", "time_reference=173184000",
                    str(wav)], check=True)
    for rot, fps, drop in CASOS:
        saida = tmp / f"injetado_{rot}.avb"
        with contextlib.redirect_stdout(io.StringIO()):
            r = audio.autorar_masters([str(wav)], str(saida), fps=fps, drop=drop)
        ok(f"{rot}: autorado, nenhum pulado, molde da variante certa", (r["clipes"], r["pulados"], r["variante_trocada"]),
           (1, [], []))
        if r["clipes"]:
            ok(f"{rot}: a cadeia inteira igual à do MC (taxa, duração, start, Timecode e as 48 h da fonte)",
               cadeia(str(saida)), cadeia(str(GABARITOS / f"gabarito_mc_{rot}.avb")))
    print(f"{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
