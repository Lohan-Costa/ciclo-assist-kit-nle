"""De colunas cruas ao dicionário que o template consome.

⭐⭐ **Como `template`, este módulo não sabe o que é Avid, nem claquete, nem a aba que o chama.**
Ele recebe dicionários e devolve dicionários. Quem lê a bin (`GetMobInfo`, `_USER` da
`.avb`) e quem sabe derivar cena/plano são adaptadores de fora, injetados. É o que
permite a mesma máquina servir ao Renomear hoje e ao nome de entrega depois — e é uma
correção deliberada ao plano de 2026-08-28, que punha a leitura do Avid aqui dentro.

## As três coisas que este módulo garante

1. **Toda chave produzida é digitável.** `normalizar` é o mesmo de `template`, então
   não existe campo no catálogo que nenhum `%` alcança. Há teste que prova o contrato
   nos dois sentidos.

2. **Precedência declarada, e derivado nunca apaga medido.** A ordem das fontes é a
   ordem da confiança: coluna do Avid > campo do mob > derivado nosso. ⚠️ Mas coluna
   PRESENTE E VAZIA é ausência de *valor*, não de campo — aí o derivado entra, senão o
   material ficaria sem cena tendo como sabê-la.

3. **Todos os itens do mesmo arrasto têm as MESMAS chaves** (`completar`). É isto que
   faz a distinção de `template` valer: chave ausente é erro do padrão, chave presente
   e vazia é fato do material. Sem completar, `%production` bloquearia no clipe do Projeto C
   e passaria no de Projeto B — o mesmo padrão com duas respostas dentro do mesmo
   arrasto, que é o pior jeito de uma ferramenta perder a confiança de quem usa.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import template as _template

log = logging.getLogger("sincronizar.nomes.campos")

#: Veio de uma coluna do NLE ou de um atributo do próprio mob — **fato**.
MEDIDO = "medido"
#: Foi calculado por nós a partir de outro campo — **palpite fundamentado**.
#: ⚠️ O painel mostra a diferença, pela mesma razão que já mostra "presumida" numa cena
#: batizada por posição: procedência é requisito do produto, não enfeite.
DERIVADO = "derivado"
#: Veio do que ESTE APP já fez com o item — o histórico dele, não o material.
#:
#: ⭐⭐ É uma terceira natureza, e não um caso de `DERIVADO`: um campo derivado se
#: recalcula a partir do que está na tela, e este só existe porque houve uma ação
#: nossa antes. Se o histórico sumir, ele some junto — o que nenhum campo medido
#: nem derivado faz. Por isso ele se pinta diferente: o editor precisa saber que
#: aquele valor tem uma origem que não está no material.
HISTORICO = "historico"


@dataclass(frozen=True)
class Campo:
    """Uma entrada do catálogo — o que o autocomplete mostra.

    `nome`    — o que se digita depois do `%` (`shoot_date`).
    `rotulo`  — como o Avid chama (`Shoot Date`). ⭐ O editor conhece a coluna por este
                nome; mostrar só o normalizado o faria não reconhecer o que achou.
    `exemplo` — um valor real, para ele confirmar que é a coluna certa.
    """

    nome: str
    rotulo: str
    procedencia: str
    exemplo: str = ""


def de_colunas(colunas: dict, *, colisoes: dict | None = None) -> dict:
    """`{coluna do Avid: valor}` → `{campo digitável: valor}`.

    Args:
        colunas: como o NLE as entrega, com espaço e maiúscula.
        colisoes: se dado, recebe `{campo: [colunas que caíram nele]}`.

    ⚠️⚠️ Duas colunas podem normalizar para a mesma chave (`Shoot Date` e `Shoot-Date`
    viram ambas `shoot_date`) — e uma bin com coluna custom pode ter as duas. A
    primeira ganha, mas a segunda **não some calada**: sai no log e no `colisoes`, para
    o painel poder avisar. Escolher no escuro qual valor o editor vê é o tipo de decisão
    que só aparece quando o nome sai errado em lote.
    """
    fora: dict = {}
    vistos: dict[str, list[str]] = {}
    for rotulo, valor in (colunas or {}).items():
        if not str(rotulo or "").strip():
            continue
        chave = _template.normalizar(rotulo)
        vistos.setdefault(chave, []).append(str(rotulo))
        if chave in fora:
            continue
        fora[chave] = valor
    for chave, quais in vistos.items():
        if len(quais) > 1:
            log.warning("colunas %s caem no mesmo campo %%%s — vale a primeira",
                        quais, chave)
            if colisoes is not None:
                colisoes[chave] = quais
    return fora


def rotulos(colunas: dict) -> dict:
    """`{campo digitável: nome original da coluna}` — para o catálogo mostrar os dois."""
    fora: dict = {}
    for rotulo in (colunas or {}):
        if not str(rotulo or "").strip():
            continue
        fora.setdefault(_template.normalizar(rotulo), str(rotulo))
    return fora


def juntar(*fontes: dict) -> dict:
    """As fontes fundidas, **a primeira que traz a chave ganha**.

    ⭐ A ordem da chamada É a declaração de confiança. Não há resolução esperta aqui de
    propósito: quem chama sabe o que mediu e o que supôs.
    """
    fora: dict = {}
    for fonte in fontes:
        for chave, valor in (fonte or {}).items():
            fora.setdefault(chave, valor)
    return fora


def _vazio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def derivar(ficha: dict, derivadores) -> dict:
    """A ficha acrescida do que os derivadores souberem calcular.

    Cada derivador é `callable(ficha) -> dict | None`, e recebe a ficha **já montada** —
    é assim que a claquete lê a coluna `Scene` do Avid em vez de reparsear o nome.

    ⚠️ `None` é resposta legítima: quem não soube derivar diz que não soube (§11).
    Tratá-la como erro faria uma bin sem claquete estourar em vez de sair sem cena.

    ⚠️⚠️ Um derivado **nunca apaga um valor medido** — uma coluna custom `Cena`
    preenchida à mão pelo assistente vale mais que qualquer palpite nosso. Mas preenche
    a chave medida que veio VAZIA: coluna em branco é ausência de valor, não de campo.
    """
    fora = dict(ficha or {})
    # ⭐ A marca da procedência viaja NA FICHA, e não num registro paralelo: a ficha é
    # o que o painel recebe, e um segundo dicionário para "de onde veio cada campo"
    # seria a primeira coisa a ficar para trás quando alguém filtrasse ou copiasse.
    # ⚠️ Chave com `_` na frente: `catalogo` a pula, e `template.CAMPO_VALIDO` aceita
    # `_` inicial — então ela é digitável e por isso NÃO pode aparecer no autocomplete
    # como se fosse coluna.
    marcados = list(fora.get("_derivados") or ())
    for derivador in (derivadores or ()):
        novos = derivador(fora)
        if not novos:
            continue
        for chave, valor in novos.items():
            if _vazio(fora.get(chave)):
                fora[chave] = valor
                if chave not in marcados:
                    marcados.append(chave)
    fora["_derivados"] = tuple(marcados)
    return fora


def completar(fichas) -> list[dict]:
    """Todas as fichas com a UNIÃO das chaves, o que faltava preenchido com `""`.

    ⚠️⚠️ Ver o item 3 do topo do módulo. Sem isto o mesmo padrão bloqueia num clipe e
    passa no outro, dentro do mesmo arrasto.
    """
    fichas = [dict(f or {}) for f in (fichas or [])]
    if not fichas:
        return []
    uniao: list[str] = []
    for f in fichas:
        for chave in f:
            if chave not in uniao:
                uniao.append(chave)
    for f in fichas:
        for chave in uniao:
            f.setdefault(chave, "")
    return fichas


def catalogo(fichas, rotulos: dict | None = None,
             procedencias: dict | None = None) -> list[Campo]:
    """Os campos disponíveis no arrasto, com rótulo, procedência e um exemplo.

    Args:
        fichas: as fichas dos itens (idealmente já passadas por `completar`).
        rotulos: `{campo: nome da coluna no Avid}`. Sem isto o rótulo é o próprio campo.
        procedencias: `{campo: MEDIDO | DERIVADO}`. Sem entrada, um campo é `DERIVADO`
            se `derivar` o criou — ver `derivar`, que marca em `_PROCEDENCIA`.

    ⚠️ O exemplo pula os vazios: se QUALQUER item do arrasto tem valor naquela coluna,
    é esse que o autocomplete mostra. Um exemplo vazio não ensina nada.
    """
    fichas = [f for f in (fichas or []) if f]
    rotulos = rotulos or {}
    procedencias = procedencias or {}
    ordem: list[str] = []
    exemplos: dict[str, str] = {}
    for f in fichas:
        for chave, valor in f.items():
            if chave.startswith("_"):
                continue
            if chave not in ordem:
                ordem.append(chave)
                exemplos[chave] = ""
            if not exemplos[chave] and not _vazio(valor):
                exemplos[chave] = str(valor)
    derivados = set()
    for f in fichas:
        derivados |= set(f.get("_derivados") or ())
    return [Campo(
        nome=chave,
        rotulo=rotulos.get(chave, chave),
        procedencia=procedencias.get(
            chave, DERIVADO if chave in derivados else MEDIDO),
        exemplo=exemplos[chave],
    ) for chave in ordem]


def sugerir(campos, prefixo: str = "", limite: int = 5) -> list[Campo]:
    """O autocomplete: os campos que começam por `prefixo`, o exato na frente.

    ⚠️ Prefixo vazio devolve o começo do catálogo — digitar só `%` é como o editor
    descobre que colunas aquela bin tem.

    ⚠️ O casamento EXATO vem primeiro: com `take` e `take2` no catálogo, quem digitou
    `%take` quer `take`, e ele não pode aparecer embaixo por ordem alfabética.

    ⭐ E é o `len` sozinho que garante isso, sem chave especial: todo candidato começa
    pelo prefixo, então o exato é necessariamente o mais curto. Houve aqui um
    `c.nome != p` na frente da ordenação; a mutação mostrou que ele era **código
    morto** — o mutante que o removia sobreviveu, e a razão é estrutural, não sorte.
    """
    p = str(prefixo or "").strip().lower()
    achados = [c for c in campos if c.nome.startswith(p)]
    achados.sort(key=lambda c: (len(c.nome), c.nome))
    return achados[:max(0, int(limite))]
