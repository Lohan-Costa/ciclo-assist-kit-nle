"""Ler um documento como texto — o `.docx` do roteiro.

⭐ Nasceu de um teste de campo em 2026-09-11: o editor arrastou
`PRODUCAO-A CENA 7 roteiro.docx` e levou **"não sei ler este formato"**. É o formato em
que roteiro de cena chega, e sem ele o fluxo que ele queria testar — roteiro + subclipes →
montagem — morria no primeiro gesto.

⛔ E entrou **sem dependência nova**: `.docx` é ZIP com XML dentro, e `zipfile` é stdlib.
`python-docx` traria `lxml` junto.
"""

from __future__ import annotations

import zipfile

import pytest

from cicloassist import documento as D
from cicloassist.servico import arrastados as A

CORPO = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:t>7. INT. CONSULTÓRIO. NOITE</w:t></w:r></w:p>
<w:p/>
<w:p><w:r><w:t>PERSONAGEM-F</w:t></w:r></w:p>
<w:p><w:r><w:t>Antes de surpreender os dois você</w:t></w:r><w:br/>
<w:r><w:t>nunca imaginou?</w:t></w:r></w:p>
<w:p><w:r><w:tab/><w:t>PERSONAGEM-G &amp; o resto</w:t></w:r></w:p>
</w:body></w:document>"""


def docx(tmp_path, corpo=CORPO, nome="roteiro.docx"):
    alvo = tmp_path / nome
    with zipfile.ZipFile(alvo, "w") as z:
        z.writestr("word/document.xml", corpo)
        z.writestr("[Content_Types].xml", "<Types/>")
    return alvo


# ── o roteiro ────────────────────────────────────────────────────────────────

def test_le_o_texto_do_corpo(tmp_path):
    texto = D.ler_docx(docx(tmp_path))
    assert "7. INT. CONSULTÓRIO. NOITE" in texto
    assert "PERSONAGEM-F" in texto


def test_a_QUEBRA_DE_PARAGRAFO_e_preservada(tmp_path):
    """⚠️⚠️ É o ponto inteiro. Sem separar os parágrafos, cabeçalho de cena, nome de
    personagem e diálogo viram uma linha só — e o modelo perde exatamente a estrutura que
    faz um roteiro ser um roteiro."""
    linhas = [l for l in D.ler_docx(docx(tmp_path)).split("\n") if l.strip()]
    assert linhas[0].startswith("7. INT.")
    assert "PERSONAGEM-F" in linhas[1]
    assert linhas[1] != linhas[2]


def test_quebra_de_linha_dentro_do_paragrafo_tambem(tmp_path):
    """Diálogo de roteiro quebra linha dentro do mesmo parágrafo (`<w:br/>`)."""
    texto = D.ler_docx(docx(tmp_path))
    assert "surpreender os dois você\nnunca imaginou?" in texto


def test_entidades_xml_voltam_a_ser_texto(tmp_path):
    """Apóstrofo, travessão e `&` aparecem em qualquer roteiro, e o XML os escapa."""
    assert "PERSONAGEM-G & o resto" in D.ler_docx(docx(tmp_path))


def test_tabulacao_vira_tab(tmp_path):
    assert "\t" in D.ler_docx(docx(tmp_path))


def test_as_etiquetas_do_word_nao_vazam(tmp_path):
    texto = D.ler_docx(docx(tmp_path))
    assert "<w:" not in texto and "xmlns" not in texto


def test_linhas_vazias_demais_sao_aparadas(tmp_path):
    corpo = CORPO.replace("<w:p/>", "<w:p/><w:p/><w:p/><w:p/>")
    assert "\n\n\n" not in D.ler_docx(docx(tmp_path, corpo))


# ── quando não é o que promete ───────────────────────────────────────────────

def test_zip_sem_documento_dentro(tmp_path):
    """⚠️ `.docx` no nome e outra coisa dentro: dizer isso é melhor que devolver texto
    vazio como se o roteiro estivesse em branco."""
    alvo = tmp_path / "mentira.docx"
    with zipfile.ZipFile(alvo, "w") as z:
        z.writestr("qualquer.txt", "nada")

    with pytest.raises(D.DocumentoIlegivel, match="sem corpo"):
        D.ler_docx(alvo)


def test_arquivo_que_nao_e_zip(tmp_path):
    alvo = tmp_path / "nem zip.docx"
    alvo.write_text("isto é texto puro", encoding="utf-8")

    with pytest.raises(D.DocumentoIlegivel):
        D.ler_docx(alvo)


def test_texto_puro_continua_passando_direto(tmp_path):
    alvo = tmp_path / "roteiro.txt"
    alvo.write_text("INT. SALA. DIA", encoding="utf-8")
    assert D.ler(alvo) == "INT. SALA. DIA"


def test_acento_torto_nao_derruba(tmp_path):
    """⚠️ Um roteiro exportado de Windows antigo vem em cp1252, e um acento torto é
    infinitamente melhor que a ferramenta inteira falhando."""
    alvo = tmp_path / "velho.txt"
    alvo.write_bytes("cena à noite".encode("cp1252"))
    assert "cena" in D.ler(alvo)


# ── a fronteira ──────────────────────────────────────────────────────────────

def test_o_docx_entrou_na_lista_do_que_se_le():
    """Sem isto o arrasto rejeita antes mesmo de tentar, e o chip diz "não sei ler este
    formato" — que foi o que o editor viu em campo."""
    assert ".docx" in A.TEXTO


def test_o_doc_antigo_NAO_entrou():
    """⛔ O `.doc` do Word 97 é binário, não ZIP: ler seu formato exigiria engenharia
    reversa que não se paga. Quem tiver um `.doc` salva como `.docx`."""
    assert ".doc" not in A.TEXTO
    assert not D.e_zipado("x.doc")


def test_o_pdf_continua_fora():
    """Exigiria dependência nova — e o editor precisa saber disso no arrasto."""
    assert ".pdf" not in A.TEXTO


def test_a_ferramenta_le_um_docx_arrastado(tmp_path, monkeypatch):
    """O caminho inteiro: o gesto autoriza, e `ler_arquivo` devolve o roteiro."""
    from cicloassist.mcp.ferramentas.arquivos import ler_arquivo

    alvo = docx(tmp_path)
    A.autorizar(alvo)
    try:
        r = ler_arquivo(str(alvo))
        assert "CONSULTÓRIO" in r["texto"]
        assert r["fonte"] == "roteiro"
    finally:
        A.esquecer_tudo()
