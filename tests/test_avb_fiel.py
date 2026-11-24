"""A string nula do `.avb` sobrevive a uma regravação.

⛔⛔ Sem isto o Media Composer recusa a bin INTEIRA com `FILE_OPEN_FAILURE` — medido em
2026-09-13 na `BIN ORIGEM`, cujos `WinFileLocator` AMA têm o caminho UTF-8 nulo
(`spikes/a_bin_ama_regravada.py`). A recusa só aparece no Media Composer; o pyavb relê o
arquivo estragado sem reclamar, e é por isso que o teste confere os BYTES.
"""

from __future__ import annotations

import io

import avb
from avb.ioctx import AVBIOContext
from avb.misc import WinFileLocator

import cicloassist.avid  # noqa: F401 — aplica o conserto
from cicloassist.avid.avb_fiel import StringNula

#: O chunk medido na `BIN ORIGEM`: caminho vazio (`00 00`) e caminho UTF-8 NULO (`ff ff`).
WINF_DA_BIN_ORIGEM = bytes.fromhex("02 02 00 00 01 02 4c ff ff 03")


def _ler_e_regravar(cru: bytes) -> bytes:
    f = avb.file.AVBFile()
    f.ictx = AVBIOContext("little")
    f.octx = AVBIOContext("little")
    loc = WinFileLocator.__new__(WinFileLocator, root=f)
    f.reading = True
    loc.read(io.BytesIO(cru))
    f.reading = False
    saida = io.BytesIO()
    loc.write(saida)
    return saida.getvalue()


def test_o_locator_da_bin_origem_volta_byte_a_byte():
    assert _ler_e_regravar(WINF_DA_BIN_ORIGEM) == WINF_DA_BIN_ORIGEM


def test_string_nula_le_como_vazia_para_quem_usa():
    """O resto do código não pode perceber: é `""`, é falsa, é `str`."""
    ctx = AVBIOContext("little")
    s = ctx.read_string(io.BytesIO(b"\xff\xff"))
    assert s == "" and not s and isinstance(s, str)
    assert isinstance(s, StringNula)


def test_string_vazia_de_verdade_continua_00_00():
    """⚠️ O caminho principal do mesmo locator É vazio, não nulo — trocar um pelo outro
    no sentido contrário seria o mesmo defeito ao avesso."""
    ctx = AVBIOContext("little")
    lido = ctx.read_string(io.BytesIO(b"\x00\x00"))
    assert not isinstance(lido, StringNula)
    saida = io.BytesIO()
    ctx.write_string(saida, lido)
    assert saida.getvalue() == b"\x00\x00"


def test_string_com_conteudo_nao_muda():
    ctx = AVBIOContext("little")
    saida = io.BytesIO()
    ctx.write_string(saida, ctx.read_string(io.BytesIO(b"\x03\x00abc")))
    assert saida.getvalue() == b"\x03\x00abc"
