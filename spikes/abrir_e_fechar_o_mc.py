"""Spike — abrir, criar e fechar o Media Composer pelo `cicloassist.avid.abrir` (o PILOTO opera a tela).

    python spikes/abrir_e_fechar_o_mc.py fechar
    python spikes/abrir_e_fechar_o_mc.py abrir <projeto> [--formato 1080p/25]
    python spikes/abrir_e_fechar_o_mc.py tela          # só a foto e as janelas

⛔ Mexe o mouse. F12 para. Com o editor olhando (regra do piloto). Um passo por chamada, e a foto
da tela no fim de cada um vai para `--fotos` — o veredito é a foto e o título da janela.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["abrir", "fechar", "tela"])
    ap.add_argument("projeto", nargs="?", default="")
    ap.add_argument("--formato", default="")
    ap.add_argument("--fotos", default=str(Path.cwd()))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    from cicloassist import janela
    from cicloassist.avid import abrir as A
    from cicloassist.piloto import tela

    def relatar(etapa, fr, det):
        print(f"   … {etapa} {det}")

    t = time.monotonic()
    codigo = 0
    try:
        if args.acao == "fechar":
            print("✅", A.fechar(relatar))
        elif args.acao == "abrir":
            print("✅", A.abrir(args.projeto, args.formato, relatar))
    except Exception as e:  # noqa: BLE001
        print("❌", type(e).__name__, e)
        codigo = 1
    print(f"{time.monotonic() - t:.1f} s · janelas do MC: {janela.janelas(A.EXE)}")
    foto = Path(args.fotos) / f"mc_{args.acao}_{int(time.time())}.jpg"
    foto.write_bytes(tela.jpeg(tela.fotografar().img, 1366))
    print("foto:", foto)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
