"""Os valores binários do `.prproj` guardados por HASH, e o texto das cartelas (2026-10-04).

Rodar:

    .venv/bin/python tests/test_prproj_binario.py        (Windows: .venv-win/Scripts/python)

O autor importou a timeline final do PRODB e as cartelas (os "Graphics" do Premiere, que viram
Text do Resolve) não vieram. Duas causas, medidas no `FINALIZACAOPRODB_FINALIZACAO_PARA
RESOLVE.prproj` (Premiere 26.0.2):

  1. O Premiere grava um blob igual UMA vez; as outras ocorrências vêm vazias, só com o
     `BinaryHash` — o crédito final duplicado de outra sequência ficava sem texto (326 vazios no
     projeto, todos com o conteúdo em outro lugar). Vale também para a máscara.
  2. A claquete do rolo ("PRODUCAO-B\\rRolo Único") tem quebra de linha, e o `isprintable` a recusava:
     sobrava o nome da fonte ("Monaco") como texto.

Um projeto mínimo é montado aqui (gzip + XML), sem depender do HD.
"""

from __future__ import annotations

import base64
import gzip
import os
import struct
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from prproj.leitura import _texto_do_blob  # noqa: E402
from prproj.projeto import Projeto  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def _blob(*strings: str) -> str:
    """Strings com prefixo u32 LE de tamanho, separadas por lixo binário (a forma do Source Text)."""
    b = b"\x48\x01\x00\x00" + b"\x00" * 12
    for s in strings:
        d = s.encode("utf-8")
        b += struct.pack("<I", len(d)) + d + b"\x00\x00\x00"
    return base64.b64encode(b).decode()


def main() -> int:
    print("── o texto da cartela ──")
    ok("título simples, fonte PostScript com hífen", _texto_do_blob(_blob("Optima-Regular", "créditos finais")),
       ("créditos finais", "Optima-Regular"))
    ok("⛔ claquete com quebra de linha e fonte SEM hífen (Monaco): o texto, não a fonte",
       _texto_do_blob(_blob("Monaco", "PRODUCAO-B\rRolo Único ")), ("PRODUCAO-B\nRolo Único ", "Monaco"))
    ok("texto de uma palavra só continua sendo o texto (a fonte vem antes)",
       _texto_do_blob(_blob("Optima-Regular", "DIA")), ("DIA", "Optima-Regular"))

    print("── o valor guardado por BinaryHash ──")
    b64 = _blob("Optima-Regular", "créditos finais")
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<PremiereData Version="3">
\t<Param ObjectID="1" ClassID="x" Version="1">
\t\t<Name>Source Text</Name>
\t\t<StartKeyframeValue Encoding="base64" BinaryHash="aaaa-1">{b64}</StartKeyframeValue>
\t</Param>
\t<Param ObjectID="2" ClassID="x" Version="1">
\t\t<Name>Source Text</Name>
\t\t<StartKeyframeValue Encoding="base64" BinaryHash="aaaa-1"/>
\t</Param>
\t<Param ObjectID="3" ClassID="x" Version="1">
\t\t<Name>Source Text</Name>
\t\t<StartKeyframeValue Encoding="base64" BinaryHash="sem-dono"/>
\t</Param>
</PremiereData>
"""
    with tempfile.TemporaryDirectory() as tmp:
        arq = os.path.join(tmp, "x.prproj")
        with gzip.open(arq, "wb") as f:
            f.write(xml.encode("utf-8"))
        p = Projeto(arq)
        ok("o valor no próprio parâmetro", p.valor_inicial(p.obj("1")) == b64, True)
        ok("⛔ o valor VAZIO, só com o hash: achado onde o Premiere o guardou",
           _texto_do_blob(p.valor_inicial(p.obj("2")) or ""), ("créditos finais", "Optima-Regular"))
        ok("hash sem conteúdo em lugar nenhum: None (não inventa)", p.valor_inicial(p.obj("3")), None)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
