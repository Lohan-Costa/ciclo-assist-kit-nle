"""As regras do cliente do Avid que não precisam do Avid.

Caminho e filtro de lixeira são lógica nossa, não do Media Composer — e são justamente
onde já se pagou caro. Testar aqui é o que impede a regressão silenciosa.
"""

from __future__ import annotations

from cicloassist.avid import mcapi


class MCFalso(mcapi.MediaComposer):
    """Um `MediaComposer` que já sabe qual é o projeto, sem abrir canal nenhum."""

    def __init__(self, raiz: str):
        super().__init__()
        self._projeto = {"caminho": raiz}


# ── lixeira ──────────────────────────────────────────────────────────────────

def test_bin_dentro_de_trash_e_lixeira():
    mc = MCFalso("C:/proj/")
    assert mc.esta_na_lixeira("C:/proj/Trash/D01.avb")
    assert mc.esta_na_lixeira(r"C:\proj\trash\D01.avb")


def test_bin_fora_de_trash_nao_e_lixeira():
    mc = MCFalso("C:/proj/")
    assert not mc.esta_na_lixeira("C:/proj/CENAS/C07.avb")


def test_bin_chamada_trash_nao_e_lixeira():
    """`Trash` precisa ser PASTA no caminho, não o nome do arquivo — senão uma bin que
    o editor batizou de Trash.avb sumiria da lista sem explicação."""
    mc = MCFalso("C:/proj/")
    assert not mc.esta_na_lixeira("C:/proj/CENAS/Trash.avb")


# ── caminho relativo ─────────────────────────────────────────────────────────

def test_absoluto_vira_relativo_a_pasta_do_projeto():
    """A única forma que o GetListOfBinItems aceita, subpasta incluída."""
    mc = MCFalso(r"C:\Users\ed\Avid Projects\MEU")
    rel = mc.caminho_relativo_da_bin(r"C:\Users\ed\Avid Projects\MEU\CENAS\C07.avb")
    assert rel.replace("\\", "/") == "CENAS/C07.avb"


def test_bin_na_raiz_do_projeto_vira_so_o_nome():
    mc = MCFalso(r"C:\proj")
    assert mc.caminho_relativo_da_bin(r"C:\proj\MEU.avb") == "MEU.avb"


def test_caminho_de_fora_do_projeto_fica_como_esta():
    """Sem inventar `..`: um caminho que não pertence ao projeto não tem forma relativa
    válida, e devolver uma faria o MC recusar com a mensagem que aponta o lugar errado."""
    mc = MCFalso(r"C:\proj")
    fora = r"D:\outro\X.avb"
    assert mc.caminho_relativo_da_bin(fora) == fora


def test_caminho_ja_relativo_atravessa():
    mc = MCFalso(r"C:\proj")
    assert mc.caminho_relativo_da_bin("CENAS/C07.avb").replace("\\", "/") == "CENAS/C07.avb"


# ── os dois tetos ────────────────────────────────────────────────────────────

def test_operacao_de_arquivo_tem_teto_muito_maior_que_consulta():
    """Um teto curto demais não devolve erro honesto — devolve decisão errada com
    confiança. Medido em 2026-08-16, com o editor ficando com duas bins."""
    assert mcapi.TEMPO_DE_ARQUIVO_S >= 10 * mcapi.TEMPO_DE_CONSULTA_S


def test_caminho_do_mac_vira_relativo():
    """O `GetBins` do MC do Mac devolve `/Users/.../projeto/MIDIAS/CAM A.avb` (banco)."""
    mc = MCFalso("/Users/ed/Documents/Avid Projects/MEU")
    rel = mc.caminho_relativo_da_bin("/Users/ed/Documents/Avid Projects/MEU/MIDIAS/CAM A.avb")
    assert rel == "MIDIAS/CAM A.avb"


def test_maiusculas_e_acento_decomposto_nao_tiram_a_bin_do_projeto():
    """⛔ MEDIDO no macOS (2026-09-14): o exFAT lista em NFD e o MC grava NFD em parte dos
    caminhos; `os.path.relpath` no Mac também distingue maiúsculas. O "relativo" saía
    absoluto, e o MC respondia "Bin is not open"."""
    import unicodedata

    raiz = "/Volumes/PROJETOS/Avid Projects/Cenação"
    bin_ = unicodedata.normalize("NFD", "/Volumes/projetos/Avid Projects/Cenação/CENAS/C07.avb")
    assert mcapi.relativo_ao_projeto(bin_, raiz).endswith("C07.avb")
    assert mcapi.relativo_ao_projeto("/Volumes/OUTRO/C07.avb", raiz) is None
    assert mcapi.relativo_ao_projeto(raiz, raiz) is None


def test_caminho_de_windows_numa_bin_aberta_no_mac_acha_o_volume(tmp_path):
    """⚠️ MEDIDO (2026-09-14): bins do projeto trazem `D//MIDIAS/x.mov` dentro de
    `MacFileLocator`. Só vira caminho do Mac se existir em UM volume — dois seriam palpite."""
    import os

    import pytest

    from cicloassist.avid import take

    if os.name == "nt":
        pytest.skip("no Windows o caminho com letra já é o certo")
    volumes = tmp_path / "Volumes"
    (volumes / "RAID" / "MIDIAS").mkdir(parents=True)
    (volumes / "RAID" / "MIDIAS" / "x.mov").write_bytes(b"x")
    (volumes / "OUTRO").mkdir()

    def no_mac(caminho):
        return take._no_disco_desta_maquina(caminho, volumes)

    assert no_mac("D:/MIDIAS/x.mov") == str(volumes / "RAID" / "MIDIAS" / "x.mov")
    assert no_mac("D:/MIDIAS/nao.mov") == "D:/MIDIAS/nao.mov"
    (volumes / "OUTRO" / "MIDIAS").mkdir()
    (volumes / "OUTRO" / "MIDIAS" / "x.mov").write_bytes(b"x")
    assert no_mac("D:/MIDIAS/x.mov") == "D:/MIDIAS/x.mov"
