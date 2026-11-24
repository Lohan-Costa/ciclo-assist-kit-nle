"""O instalador único do Ciclo Assist (fase 4): tira as integrações antigas (com cópia) e instala a ponte única.

    python tools/integracoes.py              # mostra o que sairia
    python tools/integracoes.py --fazer      # faz: cópia em <dados do Ciclo Assist>/integracoes-antigas/<data>

⚠️ Feche o Premiere, o Media Composer e o Resolve antes (eles só releem as pastas no arranque).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cicloassist import integracoes as I  # noqa: E402
from cicloassist.servico import config  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fazer", action="store_true")
    a = ap.parse_args()
    antigas = I.antigas()
    for x in antigas:
        print(f"  sai  [{x.nle}] {x.caminho}{'  (atalho)' if x.caminho.is_symlink() else ''}")
    if not a.fazer:
        print(f"\n{len(antigas)} integração(ões) antiga(s). Rode com --fazer para tirar (com cópia) e instalar a ponte.")
        return 0
    copia = config.pasta() / "integracoes-antigas" / time.strftime("%Y-%m-%d_%H%M%S")
    # ⭐ A ponte PRIMEIRO (revisão de 2026-11-07): uma antiga que não sai não pode deixar o Premiere sem ponte.
    ponte = I.instalar_ponte()
    falhas = I.ligar_modo_depuracao()
    feitos = I.desinstalar_antigas(copia)
    presas = [f for f in feitos if "falha" in f]
    print(json.dumps({"tirados": feitos, "copia": str(copia), "ponte": str(ponte), "falhas": falhas},
                     ensure_ascii=False, indent=1))
    for f in presas:
        print(f"\n⚠️ não consegui tirar {f['tirado']}: {f['falha']}")
    if presas:
        print("   Feche o programa que usa a pasta (ou rode como administrador) e rode de novo.")
    print("\nFeche e abra o Premiere (e o MC/Resolve, se estavam abertos).")
    return 2 if presas else 0  # 2: a ponte entrou e sobrou alguma antiga (o instalar.ps1 avisa, não aborta)


if __name__ == "__main__":
    raise SystemExit(main())
