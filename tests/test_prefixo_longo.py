"""O Premiere 26.5 no Windows grava `ActualMediaFilePath` com o prefixo de caminho longo (medido 2026-11-18)."""

from cicloassist.carta.entrega_prproj import _norm, sem_prefixo_longo


def test_prefixo_longo_sai():
    assert sem_prefixo_longo(r"\\?\D:\Avid MediaFiles\x.mxf") == r"D:\Avid MediaFiles\x.mxf"
    assert sem_prefixo_longo(r"\\?\UNC\srv\share\x.mxf") == r"\\srv\share\x.mxf"
    assert sem_prefixo_longo("/Volumes/a/x.mxf") == "/Volumes/a/x.mxf"


def test_o_mesmo_arquivo_com_e_sem_prefixo_casa():
    assert _norm(r"\\?\D:\Avid MediaFiles\X.mxf") == _norm(r"D:\Avid MediaFiles\X.mxf") == "d:/avid mediafiles/x.mxf"
