"""
A COLUNA `Drive` QUANDO O STORAGE NÃO TEM LETRA DE UNIDADE — o §1.3a do roadmap.

Por que existe: `raiz_do_drive` sabia ler `RÓTULO (D:)`, letra crua e `/Volumes/<x>`
do Mac, e **não sabia ler UNC**. Numa produção com Nexis a mídia gerenciada mora em
`\\\\SERVIDOR\\<projeto>\\avid mediafiles\\mxf\\…` — medido em um ambiente de produção real e
registrado na base de conhecimento interna §2.1.

⛔ **A falha era CALADA e da pior espécie:** sem ramo para UNC a função devolvia
`None`, `pastas_de_midia_do_avid` pulava o master sem erro nenhum, e o app dizia
"clipes não encontrados no disco" — com a mídia inteira ali. É a mesma classe de erro
que custou a sessão de 15/08 (`MEU-VOLUME (D:)` virando `MEU-VOLUME:\\`), e por isso
os casos abaixo cobrem também as formas ANTIGAS: o ramo novo não pode ter comido
nenhuma delas.

⚠️ O que estes testes NÃO afirmam: que a coluna `Drive` do MC realmente traz um UNC
no Nexis. Isso é `pendente` — depende do teste de campo (ver as notas internas de campo). O que eles afirmam é que, **se** vier, ele é entendido em vez de ignorado.
"""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avid.masters import raiz_do_drive

NEXIS = r"\\SERVIDOR-NEXIS\projeto_exemplo"


def win(drive: str, unidades=None):
    return raiz_do_drive(drive, "Windows", unidades if unidades is not None else {})


def mac(drive: str):
    return raiz_do_drive(drive, "Darwin", {})


# ── o ramo novo ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bruto", [
    NEXIS,                                  # como o Windows escreve
    "//SERVIDOR-NEXIS/projeto_exemplo",            # como o AAF do ambiente real escreve
    NEXIS + "\\",                           # com barra sobrando no fim
    f"projeto_exemplo ({NEXIS})",              # por analogia com `RÓTULO (D:)`
])
def test_unc_vira_raiz_no_windows(bruto):
    assert PureWindowsPath(win(bruto)) == PureWindowsPath(NEXIS)


def test_share_ANINHADO_e_preservado():
    """⚠️ Reduzir a servidor+share seria um erro MEDIDO: em produção `P:` aponta para
    `\\\\servidor-ingest\\ingest\\projeto_exemplo` — servidor, share **e subpasta**. Cortar a
    subpasta faria a busca começar numa raiz que contém os projetos de todo mundo."""
    aninhado = r"\\servidor-ingest\ingest\projeto_exemplo"
    assert PureWindowsPath(win(aninhado)) == PureWindowsPath(aninhado)


def test_no_mac_o_mesmo_share_e_um_volume_montado_por_nome():
    """O macOS monta `\\\\srv\\share` em `/Volumes/<share>` — o UNC não existe como
    caminho ali. O SERVIDOR não entra: quem nomeia o ponto de montagem é o share."""
    assert PurePosixPath(mac(NEXIS)) == PurePosixPath("/Volumes/projeto_exemplo")
    assert PurePosixPath(mac(r"\\servidor-ingest\ingest\projeto_exemplo")) == \
        PurePosixPath("/Volumes/ingest")


def test_servidor_sem_share_nao_e_raiz_de_nada():
    """`\\\\srv` sozinho não aponta para volume nenhum — devolver `Path('\\\\\\\\srv')`
    faria a busca varrer a raiz do servidor inteiro."""
    assert win(r"\\srv") is None
    assert mac(r"\\srv") is None


# ── e o que já funcionava CONTINUA funcionando ───────────────────────────────

def test_as_formas_antigas_seguem_intactas():
    assert PureWindowsPath(win("MEU-VOLUME (D:)")) == PureWindowsPath("D:\\")
    assert PureWindowsPath(win("V-001 (E:)")) == PureWindowsPath("E:\\")
    assert PureWindowsPath(win("D")) == PureWindowsPath("D:\\")
    assert PureWindowsPath(win("D:")) == PureWindowsPath("D:\\")
    assert PurePosixPath(mac("MEU-VOLUME (D:)")) == PurePosixPath("/Volumes/MEU-VOLUME")
    assert win("") is None and mac("") is None


def test_rotulo_sem_letra_ainda_cai_na_busca_por_volume_montado():
    """O plano B de `raiz_do_drive` — e o ramo UNC não pode tê-lo interceptado."""
    montados = {"nexis-workspace": Path("Z:\\")}
    assert PureWindowsPath(win("NEXIS-Workspace", montados)) == PureWindowsPath("Z:\\")
    assert win("volume-que-nao-existe", montados) is None
