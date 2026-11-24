"""A fronteira de arquivo: nada sai de fora de `ui/`.

Hoje as rotas estáticas são literais no código (`/static/painel.js`), então não há
nome de arquivo vindo da requisição — a superfície não existe ainda. O teste está aqui
porque ela vai existir, e no dia em que existir a defesa já tem que estar de pé e
provada.

    PYTHONPATH=plugins/media-composer/servico .venv/bin/python tests/test_arquivos.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins/media-composer/servico"))

from api.servidor import servir_arquivo_da_ui  # noqa: E402

# (nome pedido, deve entregar)
CASOS = [
    ("painel.html", True),
    ("painel.css", True),
    ("painel.js", True),
    ("nao-existe.txt", False),
    # Escapar por cima
    ("../main.py", False),
    ("../../../../etc/passwd", False),
    ("..%2Fmain.py", False),
    # Caminho absoluto
    ("/etc/passwd", False),
    ("/etc/hosts", False),
    # O diretório em si não é arquivo
    (".", False),
    ("", False),
    # Nome hostil: nada aqui é interpretado, só procurado
    ('"; rm -rf /', False),
    ("painel.html\n../main.py", False),
    ("-rf", False),
]


def main() -> int:
    falhas = []
    for nome, deve_entregar in CASOS:
        try:
            status, corpo, _tipo = servir_arquivo_da_ui(nome)
            entregou = status == 200
        except Exception as e:  # noqa: BLE001
            # Levantar também é falha: o handler devolveria 500 e vazaria o traceback.
            print(f" FALHA {nome!r}: levantou {type(e).__name__}: {e}")
            falhas.append(f"{nome!r} levantou {type(e).__name__}")
            continue

        ok = entregou == deve_entregar
        print(f"{'  ok  ' if ok else ' FALHA'} {nome!r} -> {status}")
        if not ok:
            falhas.append(f"{nome!r}: esperava {'entregar' if deve_entregar else 'recusar'}")

    print(f"\n{len(CASOS) - len(falhas)}/{len(CASOS)} casos")
    for f in falhas:
        print("  !", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
