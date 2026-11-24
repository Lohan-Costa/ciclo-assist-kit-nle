"""Spike — a divisão por cena com a cena SÓ no metadado do BWF, de ponta a ponta (piloto: mexe o mouse; F12 para).

    python spikes/cena_so_no_metadado.py --som "<pasta com os WAV do M06>" --camera "<pasta MXF da câmera>"

Copia os WAV para um temporário escrevendo no bext `sSCENE`/`sTAKE`/`sTAPE` num formato que o NOME não entenderia
(cena "10" e "12A"), com os nomes dos arquivos SEM claquete. Importa câmera e som no projeto aberto do MC, sincroniza
pelo Sincronizar com uma bin por cena e lista a pasta CENAS. Se as bins saírem "10" e "12A", a cena veio da COLUNA.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

#: take → (cena, take) — o formato de set mais comum: cena numérica, com letra.
CENAS = {"T01": ("10", "1"), "T02": ("10", "2"), "T03": ("10", "3"), "T04": ("12A", "1")}


def escrever_cena(wav: Path, cena: str, take: str, rolo: str = "SR01") -> None:
    dados = bytearray(wav.read_bytes())
    i = 12
    while i + 8 <= len(dados):
        cid, n = bytes(dados[i:i + 4]), struct.unpack("<I", dados[i + 4:i + 8])[0]
        if cid == b"bext":
            desc = f"sSCENE={cena}\r\nsTAKE={take}\r\nsTAPE={rolo}\r\nsFILENAME={wav.name}\r\n".encode("latin-1")
            dados[i + 8:i + 8 + 256] = desc.ljust(256, b"\x00")
            wav.write_bytes(bytes(dados))
            return
        i += 8 + n + (n & 1)
    raise SystemExit(f"{wav.name} não tem bext")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--som", required=True)
    ap.add_argument("--camera", required=True)
    ap.add_argument("--nome", default="E2E")
    args = ap.parse_args()

    from cicloassist import nle
    from cicloassist.avid import importar_opatom as IMP
    from cicloassist.avid import som_gerenciado as SG
    from cicloassist.avid.mcapi import MediaComposer
    from cicloassist.mcp.ferramentas import sincronizar as FO
    from cicloassist.midia import bwf

    tmp = Path(tempfile.mkdtemp(prefix="cena_metadado_"))
    for w in sorted(Path(args.som).glob("*.wav")):
        chave = next(k for k in CENAS if k in w.name)
        destino = tmp / w.name
        shutil.copy2(w, destino)
        escrever_cena(destino, *CENAS[chave])
        print("WAV:", w.name, "→ master", bwf.como_o_avid(str(destino))["nome"])

    def relatar(etapa, fr, det):
        pass

    with MediaComposer() as m:
        cam = IMP.importar(m, args.camera, f"{args.nome} CAM", relatar=relatar)
        print("câmera:", cam["masters"])
        som = SG.montar(m, tmp, f"{args.nome} SOM", Path(r"D:\Avid MediaFiles\MXF"), relatar=relatar)
        print("som:", som["masters"], "| metadados:", som.get("com_metadados_do_bwf"))
    nle.definir(nle.AVID)
    recusa = FO._conferir(bins=[f"{args.nome} CAM", f"{args.nome} SOM"], subclipes="por_cena")
    if recusa:
        print("❌ conferência:", recusa)
        return 1
    r = FO.sincronizar(bins=[f"{args.nome} CAM", f"{args.nome} SOM"], nome=args.nome,
                                    subclipes="por_cena")
    print("sync:", {k: r.get(k) for k in ("erro", "sequencia", "diarias", "subclipes", "subclipes_falharam",
                                         "painel_de_bins")})
    return 0 if not r.get("erro") else 1


if __name__ == "__main__":
    raise SystemExit(main())
