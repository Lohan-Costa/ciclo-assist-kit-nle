"""
O nome do arquivo não pode virar código.

Estes testes guardam um bug que tinha DUAS caras e uma raiz só: o `re.sub` trata o
terceiro argumento como TEMPLATE, então `\\1`, `\\g<0>` e escapes de barra invertida
eram reinterpretados DEPOIS do escape de XML.

  1. Todo caminho do Windows começa por `C:\\Users\\…` → `re.error: bad escape \\U`,
     e o export de DRT falhava SEMPRE no Windows (invisível para quem testa no macOS).
  2. Um arquivo chamado `A\\g<0>B.mov` reinjetava as tags que o escape tinha
     acabado de neutralizar — o nome de um arquivo emendando XML no documento.
"""

import pytest

from drt.writer import _set_field, _xml_escape


def test_caminho_do_windows_nao_explode():
    """A cara nº 1: era `re.error: bad escape \\U` em toda exportação no Windows."""
    caminho = r"C:\Users\editor\Documents\PROJETO\A001_C002.mov"
    out = _set_field("<MediaFilePath>antigo</MediaFilePath>", "MediaFilePath",
                     _xml_escape(caminho))
    assert out == f"<MediaFilePath>{caminho}</MediaFilePath>"


@pytest.mark.parametrize("nome", [
    r"A\g<0>B",          # referência ao casamento inteiro
    r"A\1B",             # referência a grupo
    r"tomada\nova",      # `\n` de caminho do Windows, não quebra de linha
    r"C:\temp\x",
])
def test_nome_hostil_entra_literal(nome):
    """A cara nº 2: nada dentro do valor pode ser interpretado."""
    out = _set_field("<Name>antigo</Name>", "Name", _xml_escape(nome))
    assert out == f"<Name>{_xml_escape(nome)}</Name>"
    # e o que o escape neutralizou continua neutralizado
    assert "<Name>" + nome.replace("<", "&lt;") not in out or "&lt;" in out or "<" not in nome


def test_escape_cobre_aspas():
    """Aspas importam quando o valor cai num atributo — escapar é mais barato que
    mapear todos os pontos de uso."""
    assert _xml_escape('a"b\'c<d>&e') == "a&quot;b&apos;c&lt;d&gt;&amp;e"


def test_tag_vazia_tambem_expande_com_valor_literal():
    out = _set_field("<Name/>", "Name", _xml_escape(r"C:\x\y"))
    assert out == r"<Name>C:\x\y</Name>"
