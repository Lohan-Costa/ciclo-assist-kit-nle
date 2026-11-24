"""Os `._*` que o macOS deixa no exFAT não são frames nem bins (triagem da matriz de plataforma, 2026-11-08)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_bin import ama_do_projeto as A  # noqa: E402
from frames import cache as C  # noqa: E402


def main() -> int:
    falhas: list[str] = []

    def ok(rotulo, obtido, esperado):
        print(f"  {'ok  ' if obtido == esperado else 'FALHA'} {rotulo:<52} -> {obtido!r}")
        if obtido != esperado:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for nome in ("a.jpg", "._a.jpg", "b.png", "._b.png", "indice.json"):
            (d / nome).write_bytes(b"x")
        ok("frames do cache sem as sombras", sorted(f.name for f in C._cache_images(tmp)), ["a.jpg", "b.png"])

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for nome in ("X.avb", "._X.avb"):
            (d / nome).write_bytes(b"x")
        lidas: list[str] = []
        original = A.da_bin
        A.da_bin = lambda b: lidas.append(Path(b).name) or {}
        try:
            A.varrer(tmp)
        finally:
            A.da_bin = original
        ok("varredura AMA só lê a bin de verdade", lidas, ["X.avb"])

    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
