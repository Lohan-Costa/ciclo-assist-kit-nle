"""A pasta indicada pelo editor: Avid MediaFiles (só MXF/UME), desconectada ou de link (autor, 2026-10-25).

Rodar:

    .venv/bin/python tests/test_tipo_da_pasta.py        (Windows: .venv-win/Scripts/python)

`media/pmr.tipo_da_pasta` e a cópia dela no painel (`tipoDaPasta`, conferida pelo node, quando houver) dão a MESMA
resposta: a Avid MediaFiles e o que está em MXF/UME é mídia gerenciada (nunca link); outra pasta dentro dela
(`MXF-desconectar`) fica fora; o resto é pasta de link. Pela forma do caminho, sem caixa nem barra.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from media.pmr import tipo_da_pasta  # noqa: E402

CASOS = [
    ("/Volumes/SSD/Avid MediaFiles", "avid"),
    ("/Volumes/SSD/Avid Mediafiles/MXF/1", "avid"),
    ("/Volumes/X/AVID MEDIAFILES/UME/2/", "avid"),
    ("D:\\Avid MediaFiles\\MXF", "avid"),
    ("/Volumes/X/Avid MediaFiles/MXF-desconectar", "fora"),
    ("E:\\Avid MediaFiles\\MXF-PRODA\\1", "fora"),
    ("/Volumes/X/R04/ISOLADO/MIDIA", "link"),
    ("/Volumes/X/Avid MediaFiles copia/MXF", "link"),
    ("", "link"),
]

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def main() -> int:
    for c, esperado in CASOS:
        ok(f"motor: {c or '(vazio)'} → {esperado}", tipo_da_pasta(c), esperado)
    node = shutil.which("node")
    if node:
        js = (RAIZ / "plugins" / "media-composer" / "servico" / "ui" / "painel.js").read_text(encoding="utf-8")
        m = re.search(r"function tipoDaPasta\(p\) \{.*?\n\}", js, re.S)
        ok("o painel tem a mesma regra (tipoDaPasta)", bool(m), True)
        if m:
            prog = m.group(0) + "\nconsole.log(JSON.stringify(" + json.dumps([c for c, _ in CASOS]) + ".map(tipoDaPasta)));"
            r = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=30)
            ok("…e dá as mesmas respostas", json.loads(r.stdout or "[]"), [e for _c, e in CASOS])
    else:
        print("  (sem node: a cópia do painel não foi conferida)")
    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
