"""A string que NÃO EXISTE (tamanho `0xFFFF`) e o pyavb que a regravava como string vazia (B005).

⛔ Medido pelo Ciclo Assist em 2026-09-13 (MC 2025.6, pyavb 1.4.0; banco `protocolos/avb/escrita.md` §string nula):
string de `.avb` é `u16 tamanho + bytes`, e o tamanho `0xFFFF` = o campo não existe. O `read_string` do pyavb devolve
`""` e o `write_string` grava `00 00` (vazio). Com o marcador trocado, o `OpenBin` recusa a BIN INTEIRA com
`FILE_OPEN_FAILURE`. Onde aparece: `WinFileLocator` de WAV linkado com o caminho UTF-8 nulo
(`02 02 00 00 01 02 4c ff ff 03`).

⚠️ Aqui importa porque o relink regrava a bin do EDITOR inteira (`relink_avb.aplicar`: lê a bin de origem e grava a de
trabalho) — uma bin com um só campo nulo saía condenada.

A string nula continua sendo `""` para todo o resto do código (igual, falsa, `str`), só que de uma subclasse que o
writer reconhece. Cópia do `cicloassist/avid/avb_fiel.py`; aplicado ao importar `avb_bin` e `avb_export`.
"""

from __future__ import annotations

from avb.ioctx import AVBIOContext

#: O tamanho que marca "este campo não existe".
NULA = 0xFFFF


class StringNula(str):
    """`""` para quem lê; `0xFFFF` para quem escreve."""


_ler_do_pyavb = AVBIOContext.read_string
_escrever_do_pyavb = AVBIOContext.write_string


def _ler(self, f, encoding="macroman"):
    pos = f.tell()
    if self.read_u16(f) >= NULA:
        return StringNula("")
    f.seek(pos)
    return _ler_do_pyavb(self, f, encoding)


def _escrever(self, f, s, encoding="macroman"):
    if isinstance(s, StringNula):
        self.write_u16(f, NULA)
        return
    _escrever_do_pyavb(self, f, s, encoding)


def aplicar() -> None:
    """Idempotente. Roda ao importar este módulo, antes de qualquer `avb.open`."""
    AVBIOContext.read_string = _ler
    AVBIOContext.write_string = _escrever


aplicar()
