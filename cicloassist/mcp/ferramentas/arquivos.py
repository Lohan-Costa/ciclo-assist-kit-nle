"""`ler_arquivo` e `ver_imagem` — o que o editor arrastou para dentro do chat.

⛔⛔ **Nenhuma das duas abre um caminho qualquer.** Elas só alcançam o que o editor
ARRASTOU nesta sessão (`servico/arrastados.py`). O caminho chega aqui dentro de texto
escrito pelo modelo, e é exatamente essa a superfície que o ADR 0005 descreve: sem a
lista, "leia este arquivo" seria acesso ao disco do cliente por uma frase.

⭐ **O gesto do editor é a autorização.** Ele arrastou o roteiro da cena, então o roteiro
da cena pode ser lido — e nada além dele.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from ... import documento as _documento
from ...servico import arrastados as _arrastados
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.arquivos")


@ferramenta(
    nome="ler_arquivo",
    descricao=(
        "Lê o texto de um arquivo que o editor arrastou para o chat — roteiro, decupagem, "
        "lista de takes, legenda. Use quando ele arrastar um arquivo e a pergunta "
        "depender do que está escrito nele. Só funciona com o que ele arrastou."
    ),
    esquema={
        "type": "object",
        "properties": {
            "caminho": {
                "type": "string",
                "description": "O caminho exato que veio do arrasto.",
            },
        },
        "required": ["caminho"],
    },
    escreve=False,
    nles=AMBOS,
)
def ler_arquivo(caminho: str) -> dict[str, object]:
    if not _arrastados.autorizado(caminho):
        return {"erro": _arrastados.recusa(caminho)}

    p = Path(caminho)
    if not p.is_file():
        return {"erro": f"{p.name} não é um arquivo que eu consiga abrir."}
    if p.suffix.lower() not in _arrastados.TEXTO:
        return {
            "erro": (
                f"não sei ler {p.suffix or 'este formato'} como texto. Formatos que eu "
                f"leio: {', '.join(sorted(_arrastados.TEXTO))}. Se for um PDF, peça ao "
                f"editor uma versão em texto."
            )
        }
    if p.stat().st_size > _arrastados.TETO_DE_TEXTO:
        return {"erro": f"{p.name} é grande demais para eu ler de uma vez."}

    try:
        texto = _documento.ler(p)
    except _documento.DocumentoIlegivel as e:
        return {"erro": str(e)}

    log.info("lido: %s (%d caracteres)", p.name, len(texto))
    return {
        "arquivo": p.name,
        "caminho": str(p),
        "caracteres": len(texto),
        "texto": texto,
        "confianca": "confirmado",
        "fonte": ("roteiro" if p.suffix.lower() in (".fdx", ".txt", ".md", ".docx")
                  else "heuristica"),
    }


@ferramenta(
    nome="ver_imagem",
    descricao=(
        "Olha uma imagem que o editor arrastou para o chat — uma foto de referência, um "
        "still de um plano, um quadro de outro filme. Use para comparar com o material "
        "do projeto: achar o personagem, procurar um enquadramento parecido, um match "
        "cut. Só funciona com o que ele arrastou."
    ),
    esquema={
        "type": "object",
        "properties": {
            "caminho": {
                "type": "string",
                "description": "O caminho exato que veio do arrasto.",
            },
        },
        "required": ["caminho"],
    },
    escreve=False,
    nles=AMBOS,
)
def ver_imagem(caminho: str) -> list[dict]:
    """⚠️ Devolve blocos do protocolo, como `ver_frames`: o texto ANTES da imagem.

    Sem a linha de texto o modelo recebe uma foto solta e não sabe de onde ela veio nem
    por que está olhando para ela.
    """
    if not _arrastados.autorizado(caminho):
        return [{"type": "text", "text": _arrastados.recusa(caminho)}]

    p = Path(caminho)
    if not p.is_file() or p.suffix.lower() not in _arrastados.IMAGEM:
        return [{"type": "text",
                 "text": f"{p.name} não é uma imagem que eu consiga abrir."}]
    # O mesmo teto do texto: uma foto de celular tem 3-8 MB e passa; um TIFF de scanner
    # estouraria a mensagem inteira.
    if p.stat().st_size > _arrastados.TETO_DE_TEXTO * 4:
        return [{"type": "text", "text": f"{p.name} é grande demais para eu olhar."}]

    try:
        dados = p.read_bytes()
    except OSError as e:
        return [{"type": "text", "text": f"não consegui abrir {p.name}: {e}"}]

    tipos = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".gif": "image/gif", ".webp": "image/webp"}
    log.info("imagem vista: %s (%d bytes)", p.name, len(dados))
    return [
        {"type": "text",
         "text": f"A imagem {p.name}, que o editor arrastou para o chat."},
        {"type": "image",
         "data": base64.b64encode(dados).decode("ascii"),
         "mimeType": tipos[p.suffix.lower()]},
    ]
