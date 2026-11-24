"""Os campos do nome de arquivo da aba *Daqui Pra Lá*, e o nome que o disco aceita.

A gramática é a do Órbita (`template.py`, vendorizado): `%campo`, `%{campo}`, `%%`. Aqui
mora só o CATÁLOGO do export e a limpeza final — o nome renderizado vira nome de arquivo,
nunca caminho.
"""

from __future__ import annotations

import re
from datetime import datetime

from . import template

#: `(campo, rótulo para o editor)`. A ordem é a dos botões no painel.
CAMPOS = (
    ("sequencia", "nome da sequência"),
    ("data", "data AAMMDD"),
    ("hora", "hora HHMM"),
    ("projeto", "nome do projeto"),
    ("tipo", "COR ou VFX"),
)

#: Os campos que só fazem sentido num INSERT do Magic Link (fora dele, somem do painel).
SO_INSERT = frozenset({"tipo"})


def valores(sequencia: str, projeto: str = "", agora: datetime | None = None,
            tipo: str = "") -> dict:
    """Os valores de cada campo NESTE momento. `agora` existe para o teste congelar o relógio.

    `tipo` é `COR`/`VFX` num insert do Magic Link. ⭐ O programa NÃO decide o nome do envio: o
    editor o compõe com estes campos (nomes são convenção da equipe — autor, 2026-09-25).
    """
    t = agora or datetime.now()
    return {
        "sequencia": sequencia or "",
        "data": t.strftime("%y%m%d"),
        "hora": t.strftime("%H%M"),
        "projeto": projeto or "",
        "tipo": (tipo or "").upper(),
    }


def literal(texto: str) -> str:
    """Um texto para PRÉ-PREENCHER o campo de nome sem virar padrão por acidente.

    ⚠️ Uma sequência chamada `CORTE 50%` pré-preenchida crua faria o `%` virar tag
    desconhecida e o botão de exportar travaria sem o editor ter escrito nada.
    """
    return (texto or "").replace("%", "%%")


#: Proibidos no Windows (`<>:"/\\|?*` e controle) e `:` no macOS — banco,
#: `transversal/matriz-de-plataforma.md` §C "caracteres proibidos". A barra está aqui
#: também porque ela faria o NOME virar CAMINHO.
_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVADOS = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
               *(f"lpt{i}" for i in range(1, 10))}


def nome_de_arquivo(texto: str) -> str:
    """O texto renderizado → um nome que os dois sistemas aceitam, ou `""` se não sobrar nada.

    ⚠️ Espaço e ponto no FIM do nome o Windows descarta calado e o Mac grava como
    `U+F028`/`U+F029` — o arquivo sai com nome diferente do que o painel mostrou
    (banco, matriz §C "nome com espaço/ponto no fim").
    """
    limpo = _PROIBIDOS.sub("_", texto or "").strip().rstrip(". ")
    if limpo.split(".")[0].lower() in _RESERVADOS:
        limpo = "_" + limpo
    return limpo[:150]


def analisar(padrao: str, campos: dict) -> dict:
    """O que o painel desenha a cada tecla: nome final (ou erro) e os tokens ruins."""
    ruins = template.validar(padrao, campos)
    if ruins:
        return {"nome": "", "erro": "campo que não existe: " + ", ".join(t.bruto for t in ruins),
                "ruins": [{"inicio": t.inicio, "fim": t.fim, "bruto": t.bruto} for t in ruins]}
    nome = nome_de_arquivo(template.render(padrao, campos))
    if not nome:
        return {"nome": "", "erro": "o nome ficou vazio", "ruins": []}
    return {"nome": nome, "erro": "", "ruins": []}
