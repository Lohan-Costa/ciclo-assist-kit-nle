"""Uma bin por cena — a segunda das duas funções novas do Preparar (§5.2 do spec).

⭐ Portado do Assist anterior (`modulos/preparar/cenas.py`) em 2026-09-05.

⚠️ **A cena aqui é a da CLAQUETE, não a do roteiro.** A conciliação com o roteiro é
trabalho da Camada 1 e acontece depois, dentro da bin já existente. A bin nasce da
fonte que TEM o dado — o som — e não espera o roteiro para existir. É isso que faz o
fluxo sobreviver ao material sem roteiro (§9), que é a maior parte da produção real.

⭐ **É esta bin que sustenta o resto do produto.** O checkpoint 2 acontece sobre ela:
o editor confere, arrasta o take que caiu na cena errada, e a partir daí *a cena é
fato, não inferência*. A parte mais frágil da Camada 1 evapora porque este arquivo
existe.

## As três bins que não são cena

`NAO RESOLVIDO` — **havia claquete, e ela não casou com convenção nenhuma.**
⚠️ **Não é erro** (§11): o take fica visível, com o nome do master, para o editor
apontar à mão. Sumir com ele seria pior que errar a cena — não haveria o que corrigir.

`ORFAOS` — **a sincronização não pareou este material**: um clipe de câmera que rodou
sem som direto por baixo. ⚠️⚠️ Não é o mesmo caso que o de cima, e foi por misturar os
dois que a bin `NAO RESOLVIDO` saiu com 26 clipes de câmera na primeira rodada dentro
do Avid (2026-08-26) — nenhum deles uma claquete ilegível. As causas são diferentes e
os consertos também: um se resolve lendo o nome, o outro sincronizando de novo.

⭐ Um take de som COM claquete que nenhuma câmera cobriu também é órfão — e mesmo
assim vai para a **bin da sua cena**. A precedência é `descarte` → `cena` → `órfão` →
`não resolvido`, e ela é assim porque esconder da cena um take que tem cena é o mesmo
dano, com outro nome.

`DESCARTE` — take que o técnico de som marcou em `FALSE TAKE`/`TRASH`. É `confirmado`,
não heurística. ⚠️ E `descartado is None` (**não avaliado**) **fica na cena**: tratar
"não sei" como "está no lixo" é a mesma inversão que o §7 proíbe na outra direção.
"""

from __future__ import annotations

import registro

from pathlib import Path

from avid import subclipes as _subclipes

log = registro.log(__name__)

BIN_NAO_RESOLVIDO = "NAO RESOLVIDO"
BIN_ORFAOS = "ORFAOS"
BIN_DESCARTE = "DESCARTE"


def agrupar(takes) -> dict[str, list]:
    """`{nome da bin → takes}`, cada lista já ordenada por plano e depois take.

    ⭐ A ordenação é por STRING e isso é de propósito: `plano` e `take` já saem de
    `claquete.py` com dois dígitos, então a ordem lexicográfica é a numérica — a mesma
    que o editor vai ver na bin do Avid. Ordenar por número aqui e por string lá
    faria as duas listas divergirem justamente onde importa (`P10` contra `P2`).
    """
    grupos: dict[str, list] = {}
    for take in takes:
        # ⚠️ A ORDEM É A REGRA. `cena` antes de `orfao`: um take de som com claquete
        # boa que nenhuma câmera cobriu é órfão, e ainda assim pertence à sua cena —
        # roteá-lo por `orfao` o esconderia justamente de onde o editor vai procurar.
        if take.descartado is True:
            chave = BIN_DESCARTE
        elif take.cena is not None:
            # ⭐ Em série a cena só é única dentro do episódio: E3 C02 e E5 C02 são bins diferentes.
            chave = f"{take.episodio} {take.cena}" if getattr(take, "episodio", None) else take.cena
        elif getattr(take, "orfao", False):
            chave = BIN_ORFAOS
        else:
            chave = BIN_NAO_RESOLVIDO
        grupos.setdefault(chave, []).append(take)

    for chave in grupos:
        grupos[chave].sort(key=lambda t: (t.plano or "", t.take or "", t.nome))
    return grupos


def caminho_de_bin_livre(pasta, base: str) -> str:
    """Um caminho de `.avb` que ainda não existe: `C04.avb`, `C04 2.avb`, …

    ⚠️⚠️ **NUNCA sobrescreva uma bin que o Media Composer possa ter aberta.** Medido:
    `OpenBin` numa bin JÁ ABERTA devolve `Completed` e **não relê o disco** — o MC
    continua servindo a cópia em memória. Depois do checkpoint 2 isso é duplamente
    caro: além de o MC mostrar a versão velha, a sobrescrita teria destruído as
    correções que o editor acabou de fazer.
    """
    pasta = Path(pasta)
    alvo = pasta / f"{base}.avb"
    n = 2
    while alvo.exists():
        alvo = pasta / f"{base} {n}.avb"
        n += 1
    return str(alvo)


def escrever(takes, pasta, base: str | None = None, progresso=None) -> dict:
    """Escreve uma `.avb` por cena. Não fala com o Media Composer.

    Args:
        takes: os `Tomada` a distribuir.
        pasta: onde escrever. Tipicamente `<projeto do Avid>/CENAS`.
        base: uma `.avb` com os masters, para que cada bin de cena saia
            autossuficiente. Com `None`, sai só o subclipe e o MC resolve o master
            por MobID no banco de mídia.
        progresso: `callable(feito, total, nome)`.

    Returns:
        `{"bins": [{"cena", "caminho", "takes"}], "total", "nao_resolvidos",
        "orfaos", "descartados"}`.
    """
    takes = list(takes)
    if not takes:
        log.info("nenhum take — nenhuma bin de cena escrita")
        return {"bins": [], "total": 0, "nao_resolvidos": 0, "orfaos": 0,
                "descartados": 0}

    Path(pasta).mkdir(parents=True, exist_ok=True)
    grupos = agrupar(takes)

    escritas = []
    total = len(grupos)
    for n, chave in enumerate(sorted(grupos), start=1):
        if progresso:
            progresso(n - 1, total, chave)
        caminho = caminho_de_bin_livre(pasta, chave)
        _subclipes.autorar(grupos[chave], caminho, base=base)
        escritas.append({"cena": chave, "caminho": caminho,
                         "takes": len(grupos[chave])})
    if progresso:
        progresso(total, total, "")

    resultado = {
        "bins": escritas,
        "total": len(takes),
        "nao_resolvidos": len(grupos.get(BIN_NAO_RESOLVIDO, [])),
        "orfaos": len(grupos.get(BIN_ORFAOS, [])),
        "descartados": len(grupos.get(BIN_DESCARTE, [])),
    }
    log.info("bins de cena escritas: %d (%d take(s))", len(escritas), len(takes))
    return resultado
