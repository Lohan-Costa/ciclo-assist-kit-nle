"""Onde o editor deixou os nodes de cada fluxo (fase N1 do plano `2026-11-08-janela-de-nodes.md`).

⭐ À parte da receita, de propósito: receita antiga abre sem mudar uma linha, e as da casa ficam na pasta do programa.
Arquivo corrompido vira "sem posição" e o programa organiza sozinho: é arrumação de tela, não trabalho do editor.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Any

from . import config as _config

log = logging.getLogger("cicloassist.servico.posicoes_dos_fluxos")

TETO_DE_NODES = 60          # o executor aceita 30 passos, e cada um pode ter um gerente antes
TETO_DO_ID = 64
LIMITE_DO_PLANO = 1_000_000
ZOOM_MINIMO, ZOOM_MAXIMO = 0.3, 2.0

_trava = threading.Lock()


class PosicoesInvalidas(ValueError):
    """O pedido não é uma posição de node. Defeito da página, nunca do editor."""


def arquivo() -> Path:
    return _config.pasta() / "posicoes_dos_fluxos.json"


def _ler_tudo() -> dict[str, Any]:
    try:
        dado = json.loads(arquivo().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("posições dos fluxos ilegíveis, sigo sem elas: %s", e)
        return {}
    fluxos = dado.get("fluxos") if isinstance(dado, dict) else None
    return fluxos if isinstance(fluxos, dict) else {}


def do_fluxo(nome: str) -> dict[str, Any] | None:
    """`{nos: {id: [x, y]}, vista: {x, y, z}}`, ou `None` para organizar sozinho."""
    with _trava:
        salvo = _ler_tudo().get(nome)
    return salvo if isinstance(salvo, dict) and isinstance(salvo.get("nos"), dict) else None


def esquecer(nome: str) -> None:
    """O fluxo foi excluído: um outro criado com o mesmo nome não herda o desenho dele."""
    from ..midia.cache import escrever_atomico

    with _trava:
        tudo = _ler_tudo()
        if tudo.pop(nome, None) is not None:
            escrever_atomico(arquivo(), json.dumps({"fluxos": tudo}, ensure_ascii=False).encode("utf-8"))


def _numero(valor: Any, rotulo: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or abs(valor) > LIMITE_DO_PLANO:
        raise PosicoesInvalidas(f"{rotulo}: número fora do plano")
    return round(float(valor), 1)


def gravar(nome: str, nos: Any, vista: Any) -> None:
    from ..midia.cache import escrever_atomico

    if not isinstance(nos, dict) or not 0 < len(nos) <= TETO_DE_NODES:
        raise PosicoesInvalidas(f"'nos' tem de ser de 1 a {TETO_DE_NODES} nodes")
    limpos: dict[str, list[float]] = {}
    for no, posicao in nos.items():
        if not isinstance(no, str) or not 0 < len(no) <= TETO_DO_ID or not isinstance(posicao, list) or len(posicao) != 2:
            raise PosicoesInvalidas("cada node é {id: [x, y]}")
        limpos[no] = [_numero(posicao[0], "x"), _numero(posicao[1], "y")]
    if not isinstance(vista, dict):
        raise PosicoesInvalidas("falta a 'vista'")
    z = _numero(vista.get("z"), "zoom")
    if not ZOOM_MINIMO <= z <= ZOOM_MAXIMO:
        raise PosicoesInvalidas("zoom fora do intervalo")
    with _trava:
        tudo = _ler_tudo()
        tudo[nome] = {"nos": limpos, "vista": {"x": _numero(vista.get("x"), "x"), "y": _numero(vista.get("y"), "y"), "z": z}}
        destino = arquivo()
        destino.parent.mkdir(parents=True, exist_ok=True)
        escrever_atomico(destino, json.dumps({"fluxos": tudo}, ensure_ascii=False).encode("utf-8"))
