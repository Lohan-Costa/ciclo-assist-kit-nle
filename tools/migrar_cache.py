"""Migra o cache para pastas de nome legível.

    python tools/migrar_cache.py            # só mostra o plano, não toca em nada
    python tools/migrar_cache.py --fazer    # migra (com o serviço PARADO)

As pastas antigas vão para `_antes_da_migracao/` dentro do cache; apague quando conferir.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.midia import cache as C  # noqa: E402
from cicloassist.midia import migracao as M  # noqa: E402


def servico_no_ar() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:7824/saude", timeout=2)
        return True
    except OSError:
        return False


def main() -> int:
    plano = M.planejar()
    print(f"cache: {C.raiz()}")
    print(f"{len(plano)} pasta(s) a migrar\n")
    for item in plano:
        print(f"  {item['chave'][:16]}…  →  {item['nova'].name}")
    if "--fazer" not in sys.argv:
        print("\n(só o plano. Para migrar: --fazer, com o serviço parado)")
        return 0
    if servico_no_ar():
        print("\n⛔ o serviço está no ar em 127.0.0.1:7824 — pare-o antes de migrar.")
        return 1
    r = M.migrar()
    print(f"\nmigradas: {len(r['feitas'])} · falhas: {len(r['falhas'])}")
    for f in r["falhas"]:
        print("   ⛔", f)
    return 0 if not r["falhas"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
