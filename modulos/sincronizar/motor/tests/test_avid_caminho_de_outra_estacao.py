"""
CAMINHO ESCRITO POR OUTRA ESTAÇÃO — o §1.3b do roadmap.

`Source Path`/`Source File` guardam onde o ORIGINAL estava na máquina que importou.
Um projeto ingerido no Mac grava `/Volumes/INGEST/…`; aberto no Windows, o caminho
não existe, e o app caía para a mídia gerenciada **perdendo o original, calado** —
com ele ali, montado com outra letra.

⛔ **O que estes testes guardam com mais força é o que a tradução NÃO faz.** Ela não
procura o arquivo: não varre raízes, não compara sufixos, não acha "por semelhança".
Toda tradução usa o nome do volume que o próprio caminho carrega, e só devolve o que
existe no disco. Um acerto por semelhança devolveria o ARQUIVO ERRADO, e o sync não
levanta erro nenhum com o arquivo errado — ninguém saberia.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avid import caminhos


# ── o prefixo do volume de boot (forma D do corpus medido) ───────────────────

def test_tira_o_prefixo_do_volume_de_boot():
    """`/Macintosh HD/Volumes/X/…` não existe nem no Mac que o escreveu."""
    assert caminhos.normalizar("/Macintosh HD/Volumes/INGEST/P/x.mov") == \
        "/Volumes/INGEST/P/x.mov"
    # E um nome de volume de boot qualquer, não só o padrão da Apple.
    assert caminhos.normalizar("/SSD do Zé/Volumes/INGEST/x.mov") == \
        "/Volumes/INGEST/x.mov"


def test_nao_mexe_em_caminho_que_ja_esta_certo():
    for bruto in ("/Volumes/INGEST/x.mov", r"D:\MIDIA\x.mov", "x.mov", ""):
        assert caminhos.normalizar(bruto) == bruto


# ── a tradução, e ela exige que o arquivo ESTEJA lá ──────────────────────────

def test_traduz_pelo_nome_do_volume_quando_o_arquivo_esta_la(tmp_path):
    """`/Volumes/INGEST/A/x.mov` vira `<raiz do volume INGEST>/A/x.mov`."""
    raiz = tmp_path / "montado"
    (raiz / "A").mkdir(parents=True)
    (raiz / "A" / "x.mov").write_bytes(b"")

    achado = caminhos.traduzir("/Volumes/INGEST/A/x.mov", {"ingest": raiz})
    assert achado == raiz / "A" / "x.mov"


def test_o_volume_de_boot_e_a_traducao_compoem(tmp_path):
    """A forma que o corpus real traz de fato: prefixo de boot E outra montagem."""
    raiz = tmp_path / "montado"
    (raiz / "PROJ").mkdir(parents=True)
    (raiz / "PROJ" / "y.mov").write_bytes(b"")

    achado = caminhos.traduzir("/Macintosh HD/Volumes/INGEST/PROJ/y.mov",
                               {"ingest": raiz})
    assert achado == raiz / "PROJ" / "y.mov"


def test_volume_montado_mas_arquivo_ausente_NAO_inventa(tmp_path):
    """⛔ O `.exists()` é o que separa tradução de adivinhação. Sem ele
    devolveríamos um caminho plausível — e um caminho plausível que aponta para o
    lugar errado é pior que um `None` honesto."""
    raiz = tmp_path / "montado"
    raiz.mkdir()
    assert caminhos.traduzir("/Volumes/INGEST/A/x.mov", {"ingest": raiz}) is None


def test_volume_que_nao_esta_montado_aqui():
    assert caminhos.traduzir("/Volumes/INGEST/A/x.mov", {}) is None


def test_NAO_procura_o_arquivo_em_raiz_nenhuma(tmp_path):
    """⛔⛔ O teste mais importante do arquivo.

    O arquivo EXISTE, com o mesmo nome e a mesma cauda de caminho, sob um volume
    montado — mas com OUTRO nome de volume. Uma busca por semelhança acharia isto e
    devolveria o arquivo de outro projeto. A tradução não acha, e é o certo.
    """
    outro = tmp_path / "outro_storage"
    (outro / "A").mkdir(parents=True)
    (outro / "A" / "x.mov").write_bytes(b"")

    assert caminhos.traduzir("/Volumes/INGEST/A/x.mov", {"backup": outro}) is None


def test_caminho_do_windows_nao_e_traduzido():
    """Uma letra de outra estação não diz para onde ela apontava — não há ponte, e
    inventar uma seria escolher um volume por conta própria."""
    assert caminhos.traduzir(r"P:\PROJ\x.mov", {"ingest": Path("D:\\")}) is None
    assert caminhos.traduzir("", {}) is None


# ── ⛔ A CONTENÇÃO (auditoria de 2026-08-23) ─────────────────────────────────
#
# Os quatro testes abaixo guardam o furo que a auditoria PROVOU executando: a
# docstring do módulo prometia contenção e o código não a tinha. `Source Path` é
# texto livre de um `.avb` que pode ter sido autorado noutra produtora.
#
# ⚠️ O que torna isto sério não é o caminho errado — é que a linha seguinte era um
# `.exists()`, e no Windows um `.exists()` sobre UNC **abre sessão SMB com o host**.
# Ler o projeto de um terceiro bastava para a máquina do editor bater num servidor
# escolhido por ele. *Perguntar "existe?" não é gratuito quando o caminho é de rede.*

def test_barra_dupla_NAO_vira_UNC_de_atacante(tmp_path):
    r"""⛔ O caso que a auditoria provou: `PurePosixPath('//a/b').parts` começa com
    `'//'`, que é ÂNCORA DE RAIZ — o `Path(raiz, *partes)` descartava a raiz do
    volume e devolvia `\\atacante\share\x.mov`."""
    raiz = tmp_path / "montado"
    raiz.mkdir()
    assert caminhos.traduzir("/Volumes/INGEST///atacante/share/x.mov",
                             {"ingest": raiz}) is None


def test_letra_de_drive_no_meio_NAO_reancora(tmp_path):
    raiz = tmp_path / "montado"
    raiz.mkdir()
    assert caminhos.traduzir("/Volumes/INGEST/C:/Windows/win.ini",
                             {"ingest": raiz}) is None


def test_ponto_ponto_NAO_sobe_do_volume(tmp_path):
    raiz = tmp_path / "montado"
    (raiz / "sub").mkdir(parents=True)
    (tmp_path / "fora.mov").write_bytes(b"")
    assert caminhos.traduzir("/Volumes/INGEST/sub/../../fora.mov",
                             {"ingest": raiz}) is None


def test_o_caminho_legitimo_continua_passando(tmp_path):
    """A contenção não pode ter comido o caso normal — é o que ela existe para servir."""
    raiz = tmp_path / "montado"
    (raiz / "A").mkdir(parents=True)
    (raiz / "A" / "x.mov").write_bytes(b"")
    assert caminhos.traduzir("/Volumes/INGEST/A/x.mov", {"ingest": raiz}) == \
        raiz / "A" / "x.mov"
