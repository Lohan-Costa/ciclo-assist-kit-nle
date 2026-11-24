"""
avid/caminhos.py — traduzir um caminho escrito por OUTRA estação.

## O problema (§1.3b do roadmap)

As colunas `Source Path`/`Source File` de um master guardam onde o ORIGINAL estava
**na máquina que importou**. Um projeto ingerido num Mac grava
`/Volumes/INGEST/PROJETO/…`; aberto no Windows, esse caminho não existe. Hoje o
`arquivo_do_master` devolve `None` e o app cai para a mídia gerenciada —
**perdendo o original, calado**, com ele ali, montado com outra letra.

## ⛔ O que este módulo NÃO faz, e por quê

Ele **não procura o arquivo**. Não varre raízes atrás de um nome parecido, não
compara sufixos de caminho, não tenta "achar onde deve estar". Toda tradução aqui
usa uma informação que **o próprio caminho carrega** — o nome do volume — e só
devolve o resultado se ele **existir no disco**.

A tentação é grande e o projeto já sabe o preço: escrever uma regra sofisticada
antes de medir a entrada foi o erro que quase cimentou o bug de escopo da
`Avid MediaFiles` (DECISIONS 26ª). Achar por semelhança de caminho é a categoria de
regra que acerta nos testes e entrega **o arquivo errado** em produção — e como o
sync não levanta erro nenhum com o arquivo errado, ninguém saberia.

⚠️ **A forma real de `Source Path` no Nexis é `pendente`** — ver as notas internas de campo, que pede exatamente esse dado ao teste de campo. Quando ele chegar, é aqui que
o ramo novo entra, e é a instrumentação do `mcapi.arquivo_do_master` que vai ter
mostrado a grafia.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import registro

log = registro.log(__name__)

#: `/Volumes/<VOL>/resto` — como o macOS monta qualquer volume que não seja o de
#: boot. É a forma que interessa porque **ela carrega o nome do volume**, que é a
#: única ponte honesta entre duas máquinas.
_EM_VOLUMES = re.compile(r"^/Volumes/([^/]+)(?:/(.*))?$", re.I)

#: `/Macintosh HD/Volumes/…` — o volume de BOOT aparecendo como prefixo de um
#: caminho que já é absoluto. Medido no AAF real do ambiente de produção (forma D
#: das notas internas de campo). O caminho com esse prefixo não existe nem no Mac que
#: o escreveu: tirá-lo é restaurar o caminho canônico, não adivinhar.
_PREFIXO_DE_BOOT = re.compile(r"^/[^/]+(/Volumes/.*)$", re.I)


def normalizar(caminho: str) -> str:
    """Tira o prefixo do volume de boot, se houver. Não toca em mais nada."""
    m = _PREFIXO_DE_BOOT.match(caminho.replace("\\", "/"))
    return m.group(1) if m else caminho


def volumes_montados() -> dict[str, Path]:
    """`{nome do volume em minúsculas: raiz}` — o que está montado NESTA máquina.

    Existe como função própria, e não como um `if` no meio do `traduzir`, porque é o
    único ponto do módulo que depende do sistema operacional. Um teste que precise
    fingir um volume montado troca esta e vale nos dois SOs — a alternativa (checar
    `platform.system()` lá dentro) daria um teste que passa no Windows e falha no
    Mac, que é o defeito que a constituição do projeto proíbe.
    """
    import platform

    sistema = platform.system()
    if sistema == "Windows":
        from .masters import unidades_por_rotulo

        return unidades_por_rotulo()
    if sistema == "Darwin":
        # No macOS o nome do volume É o ponto de montagem. A enumeração cobre o caso
        # de o mesmo share estar montado com a caixa diferente da que o caminho traz.
        try:
            return {q.name.casefold(): q for q in Path("/Volumes").iterdir()}
        except OSError:
            return {}
    return {}


def traduzir(caminho: str, unidades: dict[str, Path] | None = None) -> Path | None:
    """Um caminho de outra estação → o mesmo arquivo NESTA. `None` se não der.

    Só uma tradução, e ela é literal: **o volume nomeado no caminho, procurado
    entre os volumes montados aqui**. `/Volumes/INGEST/A/x.mov` vira `P:\\A\\x.mov`
    se — e só se — existe um volume rotulado `INGEST` montado nesta máquina e o
    arquivo está lá dentro, no mesmo lugar relativo.

    ⭐ Não é palpite de estrutura: é o MESMO volume, montado de outro jeito. O
    `.exists()` no fim é o que separa isso de adivinhação — sem ele, devolveríamos
    um caminho plausível, e um caminho plausível que aponta para o arquivo errado é
    pior que um `None` honesto.

    ⚠️ Devolve `None` também quando o caminho já é desta máquina: quem chama já
    testou a existência antes, e refazer o teste aqui seria duplicar a regra.
    """
    cru = normalizar((caminho or "").strip())
    if not cru:
        return None

    m = _EM_VOLUMES.match(cru.replace("\\", "/"))
    if m is None:
        return None
    volume, resto = m.group(1), m.group(2) or ""

    if unidades is None:
        unidades = volumes_montados()

    raiz = unidades.get(volume.casefold())
    if raiz is None:
        log.debug("Volume «%s» não está montado aqui — sem tradução para «%s»",
                  volume, cru)
        return None

    partes = PurePosixPath(resto).parts if resto else ()

    # ⛔⛔ A CONTENÇÃO, e ela vem ANTES de qualquer toque no disco.
    #
    # Sem isto o módulo fazia o oposto do que a docstring promete, e foi provado
    # executando: `Source Path = /Volumes/INGEST///atacante/share/x.mov` tem
    # `PurePosixPath(...).parts == ('//', 'atacante', 'share', 'x.mov')`, e o `//`
    # é uma **âncora de raiz** — o `Path(raiz, *partes)` DESCARTA a raiz do volume
    # e devolve `\\atacante\share\x.mov`. Mesma coisa com `C:` no meio.
    #
    # ⚠️ E o estrago não era só devolver o caminho errado: a linha de baixo era um
    # `.exists()`, e no Windows um `.exists()` sobre UNC **abre sessão SMB com o
    # host** — vazamento de credencial disparado por ler um projeto de terceiro.
    # *Perguntar "existe?" não é gratuito quando o caminho é de rede.*
    for p in partes:
        if p == ".." or p.startswith(("/", "\\")) or ":" in p:
            log.warning("Caminho traduzido cairia FORA do volume «%s» (parte %r) "
                        "— recusado sem tocar no disco", volume, p)
            return None

    alvo = Path(raiz, *partes)
    # Segunda tranca, para o que a primeira não previu: o resultado tem de estar
    # DENTRO da raiz. `strict=False` porque o alvo pode legitimamente não existir.
    try:
        alvo.resolve(strict=False).relative_to(Path(raiz).resolve(strict=False))
    except ValueError:
        log.warning("Caminho traduzido cairia FORA do volume «%s» — recusado", volume)
        return None

    if not alvo.exists():
        log.debug("Volume «%s» é «%s», mas «%s» não existe lá dentro",
                  volume, raiz, resto)
        return None

    # ⭐ Uma tradução bem-sucedida é EXATAMENTE o que o log precisava dizer e não
    # dizia: sem esta linha, o original recuperado e o transcode usado por falta
    # dele produzem a mesma timeline e o mesmo silêncio.
    log.info("Caminho traduzido: «%s» -> «%s» (volume «%s» montado em «%s»)",
             caminho, alvo, volume, raiz)
    return alvo
