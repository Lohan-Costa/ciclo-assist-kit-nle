"""A trava de nomes do `publish.py`: nome de produção ou de cliente não vai ao público em NENHUMA grafia (banco, B104).

Rodar:  .venv/bin/python tests/test_publish_nomes.py        (Windows: .venv-win/Scripts/python)

A lista por string exata deixava passar outra grafia do mesmo nome. Aqui: acento, caixa e separadores (`_`, `-`, `;`)
não escondem o termo; termo curto só vale como palavra inteira ("PRODCX" não é "PRODC"); e a trava reprova o artefato.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import publish  # noqa: E402

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
    b = publish.bloqueados_em
    ok("separador no lugar do espaço", "PRODUCAO-A" in b("producao_a - 05-04.wav"), True)
    ok("acento e caixa", b("PRODUCAO-B"), ["PRODUCAO-B"])
    ok("termo curto colado a separador", b("PRODC_CORTE02"), ["PRODC"])
    ok("termo curto dentro de outra palavra não conta", b("PRODCX tsd"), [])
    ok("texto limpo", b("relink de mídia do Avid"), [])
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "a.py").write_text('CAMINHO = r"D:\\\\PRODUCAO_C\\\\MIDIA"\n', encoding="utf-8")
        try:
            publish.run_name_scan(Path(d))
            saiu = 0
        except SystemExit as e:
            saiu = e.code
        ok("o artefato com nome bloqueado reprova a publicação", saiu, 1)
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
