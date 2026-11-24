"""`o_que_quer_dizer` — o jargão do set e da ilha, consultado termo a termo.

⭐⭐ Pedido do editor (2026-09-22): transformar a planilha em que ele mapeava termos e
expressões audiovisuais num glossário para o Ciclo Assist — *"o audiovisual é muito vivo e
mutável… ir colhendo os significados e onde cada expressão entra ajuda a guiar melhor o
programa"*. Quando ele escreve "manda um AAF pro som", "tira a barriga", "base limpa",
"monstro", o modelo não precisa adivinhar.

## Por que uma ferramenta e não mais um método

⚠️ `consultar_o_metodo` devolve um `.md` INTEIRO, e isso serve para método (é lido de ponta a
ponta). O glossário tem 263 termos: carregá-lo todo para saber o que é "kill de entrada"
gastaria a janela com 262 respostas que ninguém pediu. Aqui entra só o que foi perguntado.

## A colheita

⭐ O que o modelo procurou e o glossário NÃO tinha fica anotado na pasta de dados
(`glossario_pendentes.json`: termo, quantas vezes, quando). É a lista do que o uso real
mostrou que falta — `python tools/importar_glossario.py --pendentes` a imprime, para ir
para a planilha. ⚠️ Não vai para o repo: é da máquina de quem usa.

A fonte é `skills/glossario.json`, FOTO da planilha (`tools/importar_glossario.py`), mais os
grupos de `midia/termos.json` (os termos entre línguas que a busca usa).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from ...midia import intencao as _intencao
from ...midia.decupagem import sem_acento
from ...midia.cache import escrever_atomico
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.glossario")

ARQUIVO = Path(__file__).resolve().parent.parent.parent / "skills" / "glossario.json"
#: Teto de termos por pergunta: a lista vem do modelo, e sem teto uma pergunta traria o
#: glossário inteiro de volta pela porta dos fundos.
MAXIMO = 12
_trava = threading.Lock()


def _entradas() -> list[dict[str, Any]]:
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("glossário ilegível (%s)", e)
        return []
    return [e for e in dados.get("termos") or [] if isinstance(e, dict) and e.get("termo")]


def _chave(texto: str) -> str:
    return sem_acento(" ".join(str(texto or "").replace(".", "").split())).lower()


def procurar(termo: str) -> list[dict[str, Any]]:
    """As entradas que respondem por `termo`: pela forma exata, e senão por começo de forma."""
    alvo = _chave(termo)
    if not alvo:
        return []
    exatas, comeco = [], []
    for e in _entradas():
        formas = [_chave(f) for f in [e["termo"], *(e.get("formas") or []),
                                      *(e.get("sinonimos") or [])]]
        if alvo in formas:
            exatas.append(e)
        elif len(alvo) >= 4 and any(f.startswith(alvo) for f in formas):
            comeco.append(e)
    achadas = exatas or comeco
    for g in _intencao.grupos_de_termos():
        todos = [g["preferido"], *g["tambem"]]
        if alvo in {_chave(t) for t in todos}:
            achadas = achadas + [{"termo": g["preferido"], "formas": todos,
                                  "significado": "", "area": "termos entre línguas",
                                  "preferido": g["preferido"]}]
    return achadas


def _arquivo_de_pendentes() -> Path:
    from ...servico import config as _config
    return _config.pasta() / "glossario_pendentes.json"


def pendentes() -> dict[str, dict[str, Any]]:
    try:
        dados = json.loads(_arquivo_de_pendentes().read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _anotar_pendente(termo: str, motivo: str = "") -> None:
    with _trava:
        dados = pendentes()
        chave = " ".join(str(termo).split())[:80]
        info = dados.get(chave) or {"vezes": 0}
        info["vezes"] = int(info.get("vezes") or 0) + 1
        info["ultima"] = time.strftime("%Y-%m-%d %H:%M")
        if motivo:
            info["motivo"] = motivo
        dados[chave] = info
        try:
            destino = _arquivo_de_pendentes()
            destino.parent.mkdir(parents=True, exist_ok=True)
            escrever_atomico(destino, json.dumps(dados, ensure_ascii=False, indent=1)
                             .encode("utf-8"))
        except OSError as e:
            log.warning("não consegui anotar o termo pendente (%s)", e)


@ferramenta(
    nome="o_que_quer_dizer",
    descricao=(
        "O glossário audiovisual da casa: o que quer dizer um termo, sigla ou gíria do set "
        "e da pós (ex.: AAF, kill de entrada, base limpa, barriga, loc guia, V.O), em que "
        "área ele entra e como se diz na prática. Consulte quando o editor usar um termo "
        "que você não conhece COM CERTEZA — no audiovisual a mesma palavra muda de sentido "
        "de uma equipe para outra. Mande só os termos em dúvida."
    ),
    esquema={
        "type": "object",
        "properties": {
            "termos": {
                "type": "array", "items": {"type": "string"},
                "description": f"Os termos em dúvida (até {MAXIMO}).",
            },
        },
        "required": ["termos"],
    },
    escreve=False,
    nles=AMBOS,
)
def o_que_quer_dizer(termos: list[str]) -> dict[str, object]:
    pedidos = [str(t).strip() for t in (termos or []) if str(t).strip()][:MAXIMO]
    respostas, sem, vazios = {}, [], []
    for t in pedidos:
        achadas = procurar(t)
        if achadas:
            respostas[t] = [{k: v for k, v in e.items() if v not in ("", [], None)}
                            for e in achadas[:3]]
            # ⚠️ MEDIDO na planilha (2026-09-22): 48 dos 263 termos não têm significado —
            #    entre eles "barriga", "kill de entrada", "levantar cena", "sobe som". Achar
            #    só o NOME não é saber: o termo vai para a colheita do mesmo jeito.
            if not any(e.get("significado") or e.get("preferido") for e in achadas):
                vazios.append(t)
                _anotar_pendente(t, "na planilha, sem significado")
        else:
            sem.append(t)
            _anotar_pendente(t, "não está na planilha")
    return {
        "termos": respostas,
        # ⭐ Dito, para o modelo não inventar um sentido e seguir como se soubesse.
        "nao_estao_no_glossario": sem,
        "sem_significado_ainda": vazios,
        "aviso": ("Os termos sem significado ficaram anotados para o editor completar o "
                  "glossário. Se o sentido não estiver claro pelo contexto, pergunte a ele "
                  "em vez de supor.") if (sem or vazios) else "",
        "confianca": "confirmado",
        "fonte": "heuristica",
    }
