"""A string que NÃO EXISTE (tamanho 0xFFFF) sobrevive à regravação da bin pelo pyavb (banco, B005; 2026-10-28).

Rodar:  .venv/bin/python tests/test_avb_string_nula.py        (Windows: .venv-win/Scripts/python)

O pyavb lê o 0xFFFF como "" e grava 00 00: "não existe" vira "vazio", e o MC recusou a bin inteira (FILE_OPEN_FAILURE,
Ciclo Assist 2026-09-13, WinFileLocator de WAV com o caminho UTF-8 nulo). O relink regrava a bin do editor inteira.
Os moldes versionados não têm campo nulo: a nula é plantada num MacFileLocator; o caso comum (o nome de TODO parâmetro
de efeito, `ParameterItem.name`, medido em 30 bins do Mac) entra quando houver uma bin dessas versionada.
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import avb  # noqa: E402
import avb_bin  # noqa: E402,F401 — o pacote aplica o conserto ao ser importado (é o que o serviço faz)
from avb.ioctx import AVBIOContext  # noqa: E402
from avb_fiel import StringNula  # noqa: E402

MOLDE = RAIZ / "motor" / "avb_export" / "templates" / "audio_1_24bit_1ch.avb"
casos, falhas = 0, []


def conferir(nome: str, ok: bool, detalhe: str = "") -> None:
    global casos
    casos += 1
    print(f"{'  ok  ' if ok else ' FALHA'} {nome}" + (f"  ({detalhe})" if detalhe and not ok else ""))
    if not ok:
        falhas.append(nome)


def localizadores(f) -> list:
    return [o for i in range(1, len(f.object_positions))
            if type(o := f.read_object(i)).__name__.endswith("FileLocator")]


# ── 1) bytes: a nula volta 0xFFFF, o vazio volta 00 00 ─────────────────────────────────────────────────────────────
ctx = AVBIOContext(byte_order="little")
for valor, bytes_esperados in ((StringNula(""), b"\xff\xff"), ("", b"\x00\x00")):
    buf = io.BytesIO()
    ctx.write_string(buf, valor)
    conferir(f"grava {type(valor).__name__} como {bytes_esperados.hex()}", buf.getvalue() == bytes_esperados,
             buf.getvalue().hex())
    buf.seek(0)
    lido = ctx.read_string(buf)
    conferir(f"relê {bytes_esperados.hex()} como {type(valor).__name__}",
             lido == "" and isinstance(lido, StringNula) == isinstance(valor, StringNula), type(lido).__name__)
conferir("a nula é \"\" para o resto do código", StringNula("") == "" and not StringNula("") and str(StringNula("")) == "")

# ── 2) a bin inteira: nula plantada → gravada → relida nula → regravada igual, byte a byte ──────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    a, b = Path(tmp) / "a.avb", Path(tmp) / "b.avb"
    with avb.open(str(MOLDE)) as f:
        loc = localizadores(f)[0]
        loc.path_posix = StringNula("")
        f.write(str(a))
    with avb.open(str(a)) as f:
        lido = localizadores(f)[0].path_posix
        conferir("a nula plantada volta nula da bin gravada", isinstance(lido, StringNula), repr(type(lido)))
        f.write(str(b))
    conferir("regravar a bin sem mudar nada mantém os bytes", a.read_bytes() == b.read_bytes())
    conferir("o 0xFFFF está no arquivo", b"\xff\xff" in a.read_bytes())

print(f"\n{casos - len(falhas)}/{casos} casos")
sys.exit(1 if falhas else 0)
