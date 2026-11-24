"""A string que NÃO EXISTE, e o pyavb que a regravava como string vazia.

⛔⛔ **MEDIDO em 2026-09-13** (`spikes/a_bin_ama_regravada.py`, MC 2025.6, pyavb 1.4.0):

Uma string de `.avb` é `u16 tamanho + bytes`, e o tamanho `0xFFFF` quer dizer que o campo
não existe. O pyavb lê esse marcador como `""` e grava de volta `00 00`, que é string
vazia. É pouca diferença para o pyavb e muita para o Media Composer: com o marcador
trocado, `OpenBin` recusa a **bin inteira** com `FILE_OPEN_FAILURE`.

Onde estava: no `WinFileLocator` de material AMA cujo caminho UTF-8 é nulo
(`02 02 00 00 01 02 4c ff ff 03`). A `BIN ORIGEM` tem dois, e isso já tinha condenado toda
bin derivada dela em 2026-09-12. A prova, com uma variável de cada vez:

| a mesma bin, regravada pelo pyavb | `OpenBin` |
|---|---|
| como o pyavb grava | ⛔ `FILE_OPEN_FAILURE` |
| com o `0xFFFF` preservado | ✅ abre |
| com o `0xFFFF` preservado e uma timeline nova | ✅ abre |

⚠️ **A conclusão anterior estava errada** ("mob AMA com `WinFileLocator` condena a bin").
Duas bins AMA do editor, de BRAW, MOV e WAV linkados, com 20 `WinFileLocator` de caminho
preenchido, regravam e abrem **sem** este conserto. O problema nunca foi o AMA, e sim o
campo nulo.

⭐ O conserto preserva a distinção sem mudar o que o resto do código vê: a string nula
continua sendo `""` (igual, falsa, `str`), só que de uma subclasse que o writer reconhece.
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
    """Idempotente. Roda ao importar `cicloassist.avid`, antes de qualquer `avb.open`."""
    AVBIOContext.read_string = _ler
    AVBIOContext.write_string = _escrever


aplicar()
