"""A aba Renomear do Premiere — o par de `avid/renomear.py`, com outra costura.

⭐ **A máquina é a mesma:** `nomes/` (gramática, catálogo, preview), os derivadores de
claquete do `avid/renomear.py` e o journal do `avid/desfazer.py`. O que muda:

| | Avid | Premiere |
|---|---|---|
| de onde vêm os itens | arrasto da bin (MobID) | seleção da bin (`nodeId`) |
| colunas | `GetMobInfo` | `getProjectColumnsMetadata()` (JSON) + o XMP do arquivo |
| quem escreve | o sidecar, por gRPC | o PAINEL, por ExtendScript (`item.name = x`) |
| chave do journal | MobID | `premiere:<projeto>|<nodeId>` |

## As medições que sustentam isto (Premiere 23.2, 2026-09-16/17)

- `item.name = x` grava, e o **`nodeId` não muda** com o rename (sonda §6).
- O `nodeId` é o `<ID>` do `Node` gravado no `.prproj` (`000f4241` = 1000001): ele
  **sobrevive a fechar e reabrir** o projeto. Mas um item IMPORTADO de outro projeto
  ganha id novo, e dois projetos podem ter o mesmo id — daí o projeto na chave.
- As colunas do Premiere não trazem o TAKE: ele mora no XMP do arquivo, no `bext`
  (`TAKE=001`) e em `xmpDM:shotNumber`.

⚠️ **O Premiere não confirma a gravação em disco** — o rename vale na sessão, e o projeto
fica sujo até o editor salvar. O journal marca `confirmado: False` por isso, e a tela diz.
"""

from __future__ import annotations

import json
import re

import registro

from avid.renomear import DERIVADORES
from nomes import campos as _campos

log = registro.log(__name__)

#: Colunas do Premiere que não servem de campo: flags, estado da interface, e as de
#: tempo que o `getProjectColumnsMetadata` entrega em TICKS (ilegíveis num nome).
_RUIDO = {
    "Capture Settings", "Status", "Good", "Hide", "Label", "Media Start", "Media End",
    "Media Duration", "Video In Point", "Video Out Point", "Video Duration",
    "Audio In Point", "Audio Out Point", "Audio Duration", "Subclip Start",
    "Subclip End", "Subclip Duration", "Video Info", "Audio Info", "Video Usage",
    "Audio Usage", "Offline Properties", "Proxy",
}

#: Os campos derivados que o painel oferece mesmo quando o material não os tem.
_CAMPOS_DE_CLAQUETE = ("cena", "plano", "take", "take2")

_BEXT = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")


def chave(projeto: str, node_id: str) -> str:
    """A chave do item no journal — única entre projetos."""
    return f"premiere:{projeto}|{node_id}"


def _bext(texto: str) -> dict:
    """`SCENE=…\\r\\nTAKE=001\\r\\n…` → `{"SCENE": …, "TAKE": "001"}`."""
    fora: dict = {}
    for linha in re.split(r"[\r\n|]+", str(texto or "")):
        m = _BEXT.match(linha)
        if m and m.group(2):
            fora.setdefault(m.group(1).upper(), m.group(2))
    return fora


def colunas_do_item(item: dict) -> dict:
    """As colunas de UM item, como o editor as vê — mais o TAKE do arquivo.

    ⚠️ A ordem é a da confiança: coluna do Premiere primeiro; o que o gravador de som
    escreveu no arquivo (`bext`) só preenche o que a coluna não traz.
    """
    colunas: dict = {}
    try:
        lista = json.loads(item.get("colunas_json") or "[]")
    except ValueError:
        lista = []
    for c in lista if isinstance(lista, list) else []:
        if not isinstance(c, dict):
            continue
        nome = str(c.get("ColumnName") or "").strip()
        valor = c.get("ColumnValue")
        if not nome or nome in _RUIDO:
            continue
        # ⚠️ Coluna VAZIA fica (como campo vazio): o autor, 2026-09-17 — um metadado sem
        # informação não pode tirar o campo do catálogo e travar o padrão. O Premiere
        # devolve ~20 colunas, não as 191 do Avid; não há o que filtrar por tamanho.
        colunas.setdefault(nome, "" if valor is None else str(valor))

    xmp = item.get("xmp") or {}
    bext = _bext(xmp.get("bext") or "")
    take = bext.get("TAKE") or xmp.get("take") or ""
    # ⚠️ "não traz" = ausente OU vazia: a coluna vazia agora fica na lista.
    def falta(nome):
        return not str(colunas.get(nome) or "").strip()

    if take and falta("Take"):
        colunas["Take"] = take
    if falta("Scene") and (xmp.get("scene") or bext.get("SCENE")):
        colunas["Scene"] = xmp.get("scene") or bext.get("SCENE")
    if bext.get("TAPE") and falta("Tape"):
        colunas["Tape"] = bext["TAPE"]
    if bext.get("CIRCLED") and falta("Circled"):
        colunas["Circled"] = bext["CIRCLED"]
    colunas.setdefault("Name", str(item.get("nome") or ""))
    return colunas


def levantar(projeto: str, itens: list[dict]) -> dict:
    """O que o painel recebe ao ler a seleção — o mesmo formato do Avid.

    Returns:
        `{"itens": [{mob_id, node_id, nome, tipos, campos}], "catalogo": [...]}`.
    """
    from avid import desfazer as _desfazer

    itens = [i for i in (itens or []) if isinstance(i, dict) and i.get("node_id")]
    brutas = [colunas_do_item(i) for i in itens]

    rotulos: dict = {}
    for b in brutas:
        for k, r in _campos.rotulos(b).items():
            rotulos.setdefault(k, r)
    fichas = _campos.completar([_campos.de_colunas(b) for b in brutas])
    fichas = [_campos.derivar(f, DERIVADORES) for f in fichas]
    # ⭐ Os campos da claquete existem SEMPRE, vazios quando o material não os tem —
    # sem isso, `%{cena}` num material sem cena era "campo desconhecido" e travava o lote
    # (visto pelo autor na Projeto C, 2026-09-17).
    for f in fichas:
        for campo in _CAMPOS_DE_CLAQUETE:
            f.setdefault(campo, "")
    fichas = _campos.completar(fichas)

    chaves = [chave(projeto, str(i["node_id"])) for i in itens]
    originais = _desfazer.originais_de(chaves)
    fora = []
    for item, ficha, k in zip(itens, fichas, chaves):
        ficha["nome_original"] = originais.get(k) or str(item.get("nome") or "")
        fora.append({
            "mob_id": k,
            "node_id": str(item["node_id"]),
            "nome": str(item.get("nome") or ""),
            "tipos": [str(item.get("tipo") or "")],
            "campos": {c: v for c, v in ficha.items() if not c.startswith("_")},
        })

    catalogo = [{"nome": c.nome, "rotulo": c.rotulo, "procedencia": c.procedencia,
                 "exemplo": c.exemplo}
                for c in _campos.catalogo(fichas, rotulos=rotulos,
                                          procedencias={"nome_original": _campos.HISTORICO})]
    log.info("renomear (Premiere): %d item(ns) lidos", len(fora))
    return {"itens": fora, "catalogo": catalogo}


def node_de(chave_do_journal: str) -> str:
    """`premiere:<projeto>|<nodeId>` → `<nodeId>`."""
    return str(chave_do_journal or "").rsplit("|", 1)[-1]
