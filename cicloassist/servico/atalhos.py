"""Os atalhos de prompt do editor: texto que ele escreveu, guardado por apelido.

Plano: `docs/plano/2026-09-14-menu-do-compositor.md` §2. Parte do trabalho é previsível —
"separe as falas da cena…", "sincronize a diária…" — e era redigitada toda vez. E numa
apresentação, a frase redigitada na hora é a frase que sai diferente: o atalho é o mesmo
pedido, palavra por palavra.

⭐ **Arquivo próprio (`atalhos.json`), ao lado do `config.json`.** O `config.json` tem lista
fechada de chaves e `ler()` descarta o resto (um `atalhos` lá sumiria calado); o
`estado.json` é memória interna do produto. Atalho é texto do EDITOR: ele vai querer
abrir, editar à mão e levar para a outra máquina — exportar é copiar o arquivo.

⛔ **Lista cheia RECUSA com o número; nunca descarta o mais velho em silêncio.** Perder
texto que o editor escreveu é a falha que este repo trata como inaceitável.

⛔ **Atalho não guarda caminho de disco.** `arquivo` é só o NOME (`Path(x).name`): um
caminho aqui seria uma lista durável de caminhos fora de `arrastados` (ADR 0005), e um
atalho que aponta arquivo de outra máquina é pior que nenhum.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import config as _config

log = logging.getLogger("cicloassist.servico.atalhos")

TETO_DE_ATALHOS = 12      # "para não virar algo gigante"
TETO_DO_TEXTO = 8000      # caracteres — acima disso é documento, e documento se ARRASTA
TETO_DO_APELIDO = 40      # o que cabe em 400 px
PROCEDENCIAS = ("pergunta", "arquivo", "digitado")

_trava = threading.Lock()


class AtalhoRecusado(ValueError):
    """O pedido não vira atalho, e a mensagem diz por quê (com o número)."""


def arquivo() -> Path:
    return _config.pasta() / "atalhos.json"


def _item_valido(bruto: Any) -> dict[str, Any] | None:
    if not isinstance(bruto, dict):
        return None
    texto = bruto.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        return None
    apelido = bruto.get("apelido")
    item = {
        "id": str(bruto.get("id") or uuid.uuid4().hex[:8]),
        "apelido": (apelido.strip()[:TETO_DO_APELIDO] if isinstance(apelido, str) and apelido.strip()
                    else apelido_da_primeira_linha(texto)),
        "texto": texto[:TETO_DO_TEXTO],
        "criado_em": bruto["criado_em"] if isinstance(bruto.get("criado_em"), int) else 0,
        "de": bruto.get("de") if bruto.get("de") in PROCEDENCIAS else "digitado",
    }
    if isinstance(bruto.get("arquivo"), str) and bruto["arquivo"].strip():
        item["arquivo"] = Path(bruto["arquivo"]).name
    return item


def ler() -> list[dict[str, Any]]:
    """A lista, na ordem em que foi criada. Ilegível vira lista vazia, nunca exceção."""
    try:
        bruto = json.loads(arquivo().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    itens = bruto.get("atalhos") if isinstance(bruto, dict) else bruto
    if not isinstance(itens, list):
        return []
    lista = [i for i in (_item_valido(b) for b in itens) if i]
    return lista[:TETO_DE_ATALHOS]


def _gravar(lista: list[dict[str, Any]]) -> None:
    from ..midia.cache import escrever_atomico
    destino = arquivo()
    destino.parent.mkdir(parents=True, exist_ok=True)
    escrever_atomico(destino, json.dumps({"atalhos": lista}, ensure_ascii=False,
                                         indent=1).encode("utf-8"))


def apelido_da_primeira_linha(texto: str) -> str:
    linha = " ".join(texto.strip().split())
    if len(linha) <= TETO_DO_APELIDO:
        return linha
    return linha[:TETO_DO_APELIDO - 1].rstrip() + "…"


def _sem_repetir(apelido: str, existentes: set[str]) -> str:
    """Dois itens com o mesmo nome tornam o menu inútil: o repetido ganha " (2)"."""
    if apelido.casefold() not in existentes:
        return apelido
    n = 2
    while True:
        sufixo = f" ({n})"
        candidato = apelido[:TETO_DO_APELIDO - len(sufixo)].rstrip() + sufixo
        if candidato.casefold() not in existentes:
            return candidato
        n += 1


def salvar(texto: str, apelido: str = "", de: str = "digitado",
           arquivo_de_origem: str = "") -> list[dict[str, Any]]:
    """Acrescenta um atalho e devolve a lista RELIDA do disco.

    ⚠️ Relida, e não a que temos na mão: uma gravação que falhou tem de aparecer como
    atalho ausente, nunca como "ok".
    """
    texto = (texto or "").strip()
    if not texto:
        raise AtalhoRecusado("o atalho precisa de um texto")
    if len(texto) > TETO_DO_TEXTO:
        raise AtalhoRecusado(
            f"o texto tem {len(texto)} caracteres, e o teto de um atalho é {TETO_DO_TEXTO}; "
            f"texto desse tamanho é documento — arraste-o para a conversa")
    with _trava:
        lista = ler()
        if len(lista) >= TETO_DE_ATALHOS:
            raise AtalhoRecusado(
                f"você já tem {len(lista)} atalhos (o teto é {TETO_DE_ATALHOS}); "
                f"tire um antes de salvar outro")
        apelido = (apelido or "").strip()[:TETO_DO_APELIDO] or apelido_da_primeira_linha(texto)
        apelido = _sem_repetir(apelido, {i["apelido"].casefold() for i in lista})
        item: dict[str, Any] = {"id": uuid.uuid4().hex[:8], "apelido": apelido, "texto": texto,
                                "criado_em": int(time.time()),
                                "de": de if de in PROCEDENCIAS else "digitado"}
        if arquivo_de_origem:
            item["arquivo"] = Path(arquivo_de_origem).name
        lista.append(item)
        _gravar(lista)
        log.info("atalho salvo: %s (%d no total)", apelido, len(lista))
    return ler()


def tirar(id_: str) -> list[dict[str, Any]]:
    """Tira só aquele. Id que não existe não é erro: a lista volta como está."""
    with _trava:
        lista = ler()
        restantes = [i for i in lista if i["id"] != str(id_)]
        if len(restantes) != len(lista):
            _gravar(restantes)
            log.info("atalho tirado: %s", id_)
    return ler()
