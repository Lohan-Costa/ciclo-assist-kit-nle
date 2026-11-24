"""Ler um DOCUMENTO como texto — hoje `.docx`, e o resto é leitura direta.

⭐ Nasceu de um teste de campo em 2026-09-11: o editor arrastou
`PRODUCAO-A CENA 7 roteiro.docx` para o chat e levou **"não sei ler este formato"**. É o
formato em que roteiro de cena chega no Brasil — Final Draft é minoria fora do cinema
grande —, e sem ele o fluxo inteiro que ele queria testar (roteiro + subclipes → montagem)
morre no primeiro gesto.

## ⛔ Sem dependência nova

`.docx` é um ZIP com `word/document.xml` dentro. `zipfile` e `re` são da stdlib, e a
alternativa (`python-docx`) traria `lxml` junto — peso de empacotamento para ler um XML de
estrutura conhecida.

⚠️ E o que se lê é o CORPO: cabeçalho, rodapé, notas e comentários ficam de fora. Num
roteiro isso é o certo — o cabeçalho é número de página.

## ⚠️ A quebra de parágrafo é o que importa num roteiro

`</w:p>` vira `\\n`. Sem isso, cabeçalho de cena, nome de personagem e diálogo viram uma
linha só — e o modelo perde exatamente a estrutura que faz um roteiro ser um roteiro.
"""

from __future__ import annotations

import html
import logging
import re
import zipfile
from pathlib import Path

log = logging.getLogger("cicloassist.documento")

#: ⚠️ O `.doc` antigo (binário do Word 97) NÃO está aqui: ele não é ZIP, e ler seu formato
#: exigiria engenharia reversa que não se paga. Quem tiver um `.doc` salva como `.docx`.
ZIPADOS = {".docx"}

_ENTRE_TAGS = re.compile(r">[ \t]*[\r\n]\s*<")
_PARAGRAFO = re.compile(r"</w:p\s*>", re.I)
_QUEBRA = re.compile(r"<w:br\b[^>]*/?>", re.I)
_TABULACAO = re.compile(r"<w:tab\b[^>]*/?>", re.I)
_ETIQUETA = re.compile(r"<[^>]+>")
_LINHAS_VAZIAS = re.compile(r"\n{3,}")


class DocumentoIlegivel(RuntimeError):
    """O arquivo não abriu como o formato que a extensão promete."""


def e_zipado(caminho: str | Path) -> bool:
    return Path(caminho).suffix.lower() in ZIPADOS


def ler_docx(caminho: str | Path) -> str:
    """O texto do corpo de um `.docx`, com os parágrafos preservados."""
    alvo = Path(caminho)
    try:
        with zipfile.ZipFile(alvo) as z:
            bruto = z.read("word/document.xml").decode("utf-8", errors="replace")
    except KeyError as e:
        # ⚠️ ZIP que abre mas não tem o documento: é `.docx` no nome e outra coisa por
        #    dentro. Dizer isso é melhor que devolver texto vazio como se o roteiro
        #    estivesse em branco.
        raise DocumentoIlegivel(
            f"{alvo.name} é um .docx sem corpo de documento dentro"
        ) from e
    except (zipfile.BadZipFile, OSError) as e:
        raise DocumentoIlegivel(f"não consegui abrir {alvo.name}: {e}") from e

    # ⚠️ Espaço em branco ENTRE tags é formatação do XML, não texto. Um `.docx` gravado
    #    com indentação viraria um roteiro cheio de linhas em branco no meio das falas.
    #    ⛔ Só o que contém QUEBRA DE LINHA é apagado: `<w:t xml:space="preserve"> </w:t>`
    #    guarda um espaço que é conteúdo de verdade, e comê-lo colaria as palavras.
    texto = _ENTRE_TAGS.sub("><", bruto)
    texto = _TABULACAO.sub("\t", texto)
    texto = _QUEBRA.sub("\n", texto)
    texto = _PARAGRAFO.sub("\n", texto)
    texto = _ETIQUETA.sub("", texto)
    # `&amp;`, `&#39;` e afins: o XML escapa, e o roteiro tem apóstrofo e travessão.
    texto = html.unescape(texto)
    texto = _LINHAS_VAZIAS.sub("\n\n", texto)

    linhas = [linha.rstrip() for linha in texto.split("\n")]
    return "\n".join(linhas).strip()


def ler(caminho: str | Path) -> str:
    """O texto de um arquivo, seja ele zipado ou texto puro.

    ⚠️ `errors="replace"` no texto puro: um roteiro exportado de Windows antigo vem em
    cp1252, e um acento torto é infinitamente melhor que a ferramenta inteira falhando.
    """
    alvo = Path(caminho)
    if e_zipado(alvo):
        return ler_docx(alvo)
    try:
        return alvo.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise DocumentoIlegivel(f"não consegui abrir {alvo.name}: {e}") from e
