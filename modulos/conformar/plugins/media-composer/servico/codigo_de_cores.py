"""O código de cores dos Sinais do Import, guardado NESTA máquina (Ajustes do painel).

Aprovado pelo autor em 2026-09-27 (organograma "Código de cores editável"): quem recebe é quem lê
as cores, e cada sala de cor tem o seu costume, por isso o código mora na pasta de dados da
máquina (`plataforma.pasta_dados()`, a mesma do `receptor.json`) e não no canal do Magic Link.
Quem confere nomes e completa o que faltar é `drp.sinais.validar_codigo`: um arquivo velho ou
mexido à mão volta ao de fábrica, nunca derruba o Trazer.
"""

from __future__ import annotations

import json
import os

import plataforma
from drp import sinais

ARQUIVO = "codigo_de_cores.json"


def ler() -> dict:
    try:
        d = json.loads((plataforma.pasta_dados() / ARQUIVO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    return sinais.validar_codigo(d)


def gravar(d) -> dict:
    """Confere, grava (troca atômica, como os canais) e devolve o que ficou valendo."""
    codigo = sinais.validar_codigo(d)
    pasta = plataforma.pasta_dados()
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / ARQUIVO
    tmp = alvo.with_name(f"{ARQUIVO}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(codigo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, alvo)
    return codigo


def estado(codigo: dict | None = None) -> dict:
    """O que a tela de Ajustes precisa: o código, o de fábrica, as tabelas e os avisos."""
    codigo = codigo or ler()
    return {"codigo": codigo, "fabrica": sinais.de_fabrica(),
            "categorias": sinais.CATEGORIAS,
            "tabelas": {"marcador": list(sinais.COR_DE_MARCADOR), "clipe": list(sinais.COR_DE_CLIPE)},
            "avisos": sinais.repeticoes(codigo)}
