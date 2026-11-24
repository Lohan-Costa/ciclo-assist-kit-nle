"""Spike — o som GERENCIADO com os metadados do BWF como o MC faz, contra a bin que o próprio MC gravou.

    python spikes/som_com_metadados_do_bwf.py [--projeto "CICLO TESTE RAPIDO"] [--bin "LAB BWF"]

Abre o MC no projeto (piloto — mexe o mouse; F12 para), gera os OP-Atom dos 11 WAV variados do laboratório
(`laboratorio-de-midia/saida/bancadas/avid/nomes_audio`), importa pela `som_gerenciado.montar` e compara a bin
gravada com `nomes_audio_bin_mc2512.avb` (o link do MC): nome de cada master e as colunas do `_USER`. A importação já
confere online e offsets. Sai 0 se tudo bateu.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

LAB = RAIZ.parents[1] / "laboratorio-de-midia" / "saida" / "bancadas" / "avid"


def masters(bin_avb: Path) -> dict[str, tuple[dict, list]]:
    import avb
    from cicloassist.avid.importar_opatom import _fontes_de
    fora = {}
    with avb.open(str(bin_avb)) as f:
        por = {str(m.mob_id): m for m in f.content.mobs}
        for m in f.content.mobs:
            if m.property_data.get("mob_type_id") == 2:
                a = m.property_data.get("attributes")
                user = dict(a["_USER"]) if a is not None and "_USER" in a else {}
                try:
                    fitas = sorted(x.name for x in _fontes_de(m, por)
                                   if "Tape" in type(x.property_data.get("descriptor")).__name__)
                except ValueError:      # ⚠️ o pyavb daqui não lê o PCMA da bin do MC 25.12 Mac
                    fitas = ["?"]
                fora[unicodedata.normalize("NFC", m.name)] = (user, fitas)
    return fora


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projeto", default="CICLO TESTE RAPIDO")
    ap.add_argument("--bin", default="LAB BWF")
    ap.add_argument("--so-comparar", default="", help="a .avb já importada: só compara")
    args = ap.parse_args()

    if args.so_comparar:
        caminho = Path(args.so_comparar)
    else:
        from cicloassist.avid import abrir as A
        from cicloassist.avid import som_gerenciado as SG
        from cicloassist.avid.mcapi import MediaComposer

        def relatar(etapa, fr, det):
            print(f"   … {etapa} {det}")

        print("MC:", A.abrir(args.projeto, "1080p/25", relatar)["como"])
        with MediaComposer() as m:
            r = SG.montar(m, LAB / "nomes_audio", args.bin, Path(r"D:\Avid MediaFiles\MXF"), relatar=relatar)
        print("importado:", {k: r[k] for k in ("bin", "mxf", "online", "indexar_s", "importar_s",
                                               "com_metadados_do_bwf") if k in r})
        caminho = Path(r["bin_caminho"])
    nossos = masters(caminho)
    do_mc = masters(LAB / "nomes_audio_bin_mc2512.avb")
    falhas = []
    for nome, (user_mc, fitas_mc) in sorted(do_mc.items()):
        if nome not in nossos:
            falhas.append(f"FALTA o master '{nome}'")
            continue
        user, fitas = nossos[nome]
        a, b = dict(user), dict(user_mc)
        if "LAB_V04" in nome:                       # sem bext: a data do arquivo na máquina que importou
            a.pop("Shoot Date", None), b.pop("Shoot Date", None)
        print(("✅" if a == b else "❌"), nome, "| fita:", fitas, "(MC:", fitas_mc, ")")
        if a != b:
            falhas.append(f"{nome}: _USER {a} ≠ MC {b}")
    sobra = set(nossos) - set(do_mc)
    if sobra:
        falhas.append(f"masters a mais: {sorted(sobra)}")
    print("FALHAS:", falhas or "nenhuma")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
