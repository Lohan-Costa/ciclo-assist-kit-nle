"""O leitor de claquete: nome do SOM → cena · plano · take.

⚠️ **Só o som tem claquete.** O achado 1 do spec mede isto no material de *PRODUCAO-A*: `A001_03170214_C001.mp4` traz rolo, timecode e número de clipe — nada
mais —, enquanto `PROJETO A - 05-04 C4 P1-T002.WAV` traz cena, plano e take. Toda
atribuição de cena neste módulo passa por aqui, e por aqui só passa nome de som.

⭐⭐ **Uma GRAMÁTICA só, e um VOCABULÁRIO que cresce.** No produto real cada produção
nomeia diferente, e o spec (§6) nomeia esta como a peça que mais vai variar — mas o que
varia é a PALAVRA, não a estrutura: `C4 P1-T001` e `CENA15P2-T001` são a mesma coisa com
outro rótulo. Acrescentar um rótulo é `registrar_rotulo_de_cena("TOMADA")`; uma forma
genuinamente outra é `registrar_convencao(...)`. **Nos dois casos, sem editar regex.**

⚠️ Antes de 2026-08-28 havia uma expressão regular por forma de nome encontrada, e a
terceira já estava a caminho. Ver o bloco do vocabulário abaixo.

⚠️ **Nome que não casa com nenhuma convenção NÃO é erro.** É cena não resolvida
(§11): `ler()` devolve `None`, o subclipe sai mesmo assim com o nome do master, e o
editor aponta à mão. **Nunca se inventa uma cena.**
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# As pastas que o técnico de som usa para marcar descarte. ⚠️ Estão VAZIAS no material
# de *PRODUCAO-A* — a existência delas é que prova que a marcação negativa faz parte
# do fluxo (§6/Camada 3 do spec). Só estes dois nomes entram aqui porque só estes dois
# foram MEDIDOS; acrescentar variantes plausíveis seria adivinhar.
#: `FALSETAKES`, sem espaço: a de um Sound Devices real (Diária 03, medida em 2026-11-08).
PASTAS_DE_DESCARTE = frozenset({"FALSE TAKE", "FALSETAKES", "TRASH"})


@dataclass(frozen=True)
class Claquete:
    """O que a claquete do som informa, já normalizado.

    `cena`, `plano` e `take` saem daqui **prontos para virar nome** — com o prefixo e
    os dois dígitos. Quem consome nunca reformata: se dois lugares formatassem, um
    deles ficaria para trás.
    """

    cena: str        # "C04"
    plano: str       # "P01"
    take: str        # "T002"
    convencao: str   # qual entrada de CONVENCOES produziu esta leitura
    episodio: str = ""  # "E03", quando o nome traz (`E3C2P1T01`); vazio nos filmes


def dois_digitos(bruto: str) -> str:
    """`"4"` → `"04"`; `"4A"` → `"04A"`; `"002"` → `"002"`.

    ⭐ Existe porque bin do Avid ordena lexicograficamente, e `C10` antes de `C4` é
    confusão gratuita na tela do editor (§10 do spec). O sufixo alfabético sobrevive:
    cena dividida no set vira `C4A`, e `C04A` continua ordenando junto de `C04`.
    """
    m = re.match(r"^(\d+)(.*)$", bruto.strip())
    if not m:
        return bruto.strip()
    numero, resto = m.group(1), m.group(2)
    return numero.zfill(2) + resto.upper()


# ⭐ O QUALIFICADOR entre plano e take — `P3 PICUP`, `P1 SERIE` — fica DENTRO do
# plano, e isso é decisão do autor (2026-08-28), não comodidade de regex.
# ⚠️⚠️ Descartá-lo faria `C11 P3/001` e `C11 P3 PICUP/001` — tomadas DIFERENTES —
# virarem o mesmo `C11_P03_T001`, e uma sobrescreveria a outra na bin, calada. O preço
# aceito é um espaço no meio do nome do subclipe; `dois_digitos` preserva o sufixo.
# ⚠️ O `*?` é preguiçoso por LEGIBILIDADE, não por necessidade — e a distinção foi
# MEDIDA, não suposta. O mutante que o troca por `*` guloso SOBREVIVEU à suíte
# (2026-08-28), e o fuzz diferencial que se rodou em seguida explica por quê: 105.043
# nomes gerados, ZERO divergências entre as duas formas. A razão é estrutural —
# `[A-Za-z0-9]+` não atravessa `-`, `/` nem `_`, então o separador termina a expansão
# do qualificador nos dois sentidos, e as duas convergem sempre no mesmo casamento.
# ⭐ Não escreva teste para essa diferença: não existe uma.
_QUALIFICADOR = r"(?:\s+[A-Za-z0-9]+)*?"

# ═══════════════════════════════════════════════════════════════════════════════
# ⭐⭐ O VOCABULÁRIO — a peça que cresce. A gramática é UMA SÓ.
#
# Isto nasceu de uma correção de enquadramento do autor (2026-08-28): *"parece que
# estamos resolvendo problemas pontuais ao invés de considerar que isso são exemplos e
# que o mundo real vão ser outros padrões de nomes"*. Ele estava certo — havia duas
# expressões regulares quase idênticas, uma por forma de nome encontrada, e a terceira
# já estava a caminho.
#
# O que as quatro diárias de *PRODUCAO-A* mostram é que a estrutura NÃO varia:
# é sempre `<rótulo de cena><número> <rótulo de plano><número> <take>`. O que varia é
# a PALAVRA — `C4 P1-T001` na D02, `CENA15P2-T001` na D04. Então a palavra é dado, e
# acrescentá-la é editar uma lista, não escrever uma regex.
#
# ⚠️ `_alternativa` ordena do mais longo para o mais curto, e isso é LEGIBILIDADE, não
# carga — a distinção foi medida, não suposta. O mutante que inverte a ordem SOBREVIVEU
# (2026-08-28): a alternância do Python retrocede, então `C` casa em `CENA15`, exige
# dígito, encontra o `E`, volta e tenta `CENA`. O resultado é o mesmo nos dois sentidos.
# ⭐ Não escreva teste para a ordem: não existe diferença. O que precisa de teste é o
# vocabulário CONTER a palavra, e disso o mutante G8 morreu.
#
# ⚠️⚠️ E o que NÃO entra aqui: número sem rótulo. `PROJETO A - CENA-PRAIA 03-04`
# é uma DATA, e `24-1` de *Projeto B* é cena-plano de verdade — mas nada no nome o
# prova. Decisão do autor no mesmo dia: **não se deriva sem rótulo**; nesses casos o
# template usa a coluna `Scene` crua, que está sempre certa. Ver `nomes/`.
# ═══════════════════════════════════════════════════════════════════════════════

# ⚠️ `SCENE`, `SHOT` e `SH` entraram por decisão do autor (2026-11-08), sem material real que os use ainda: ele vai trazer
# áudios de outras produções para medir. Os três campos continuam obrigatórios, e o `_` entre cena e plano segue fora.
ROTULOS_DE_CENA = ["C", "CENA", "SC", "ESC", "SCENE"]
ROTULOS_DE_PLANO = ["P", "PLANO", "TOM", "SHOT", "SH"]
#: Só `E`, a única forma medida (`E3C2P1T01`, 2026-11-08). Vem colado à cena; os três campos seguem obrigatórios.
ROTULOS_DE_EPISODIO = ["E"]
#: ⚠️ A barra do iXML (`C11 P1/001`) NÃO precisa de rótulo — ver `_montar_gramatica`.
ROTULOS_DE_TAKE = ["T", "TK", "TAKE"]


def _alternativa(rotulos) -> str:
    """`(?:CENA|ESC|SC|C)` — do MAIS LONGO para o mais curto. Ver o bloco acima."""
    unicos = sorted(set(r.strip().upper() for r in rotulos if r and r.strip()),
                    key=lambda r: (-len(r), r))
    return "|".join(re.escape(r) for r in unicos)


def _montar_gramatica() -> re.Pattern:
    r"""A gramática única: rótulo+cena, rótulo+plano, separador+take.

    ⭐ **Os TRÊS campos são obrigatórios, e é isso que protege o material de câmera.**
    `a005_03180108_C003` tem um `C003` que uma regra de cena sozinha leria como cena 3 —
    e criaria uma bin inteira a partir de um número de clipe da Blackmagic. Exigindo
    plano e take depois, ele não casa, e nem `A_0001C001_...` de *Projeto B*, nem
    `20260101_CAM0001` do Projeto C.

    ⚠️ Entre cena e plano só `\s*`, nunca `_` — e a razão é conservadora: sublinhado
    ali não aparece em nenhum dos três produtos medidos, e aceitar separador que não se
    viu amplia a superfície de falso positivo sem material que a justifique.

    ⚠️⚠️ **Correção de 2026-08-28.** Este parágrafo afirmava que o `\s*` era o que
    impedia a gramática de capturar `ESC9_TOM3_2` antes de uma convenção registrada
    pelo usuário. Era FALSO: o mutante que troca `\s*` por `[\s_]*` sobreviveu à suíte,
    e medindo se vê que quem protege ali é a exigência de TAKE — `..._2` não tem rótulo
    de take nem barra. A afirmação foi corrigida, e a regra ganhou teste próprio.

    ⚠️ O take aceita dígito nu **só depois da barra** — a forma que o Media Composer
    escreve a partir do iXML. Depois de hífen, sublinhado ou espaço o rótulo é
    obrigatório, senão `CENA-PRAIA 03-04` leria `-04` como número de take.
    """
    return re.compile(
        # ⭐ O episódio antes da cena; sem ele, a fronteira de palavra de sempre. O sufixo da cena aceita duas letras
        # (`C9ct`, cujo sentido ninguém confirmou: fica escrito como está, e nada aqui o interpreta).
        r"(?:\b(?:" + _alternativa(ROTULOS_DE_EPISODIO) + r")(?P<episodio>\d+)|\b)"
        r"(?:" + _alternativa(ROTULOS_DE_CENA) + r")\s*(?P<cena>\d+[A-Za-z]{0,2})"
        r"\s*(?:" + _alternativa(ROTULOS_DE_PLANO) + r")\s*"
        r"(?P<plano>\d+[A-Za-z]?" + _QUALIFICADOR + r")"
        r"(?:[\s\-_]*(?:" + _alternativa(ROTULOS_DE_TAKE) + r")\s*|\s*/\s*)"
        r"(?P<take>\d+)\b",
        re.IGNORECASE,
    )


# ⚠️ ORDEM É PRECEDÊNCIA: a primeira convenção que casa vence. A gramática de rótulos
# vem primeiro justamente para que uma convenção nova e frouxa, registrada depois, não
# capture material que já tinha dono.
CONVENCOES: list[tuple[str, re.Pattern]] = [
    ("rotulada", _montar_gramatica()),
]


def recompilar() -> None:
    """Refaz a gramática depois de mexer nos vocabulários.

    ⚠️ Chamada por `registrar_rotulo_*`. Existe separada porque os vocabulários são
    listas públicas: quem editar `ROTULOS_DE_CENA` na mão precisa de um jeito de
    fechar a conta — e um vocabulário editado sem recompilar é uma mudança que não
    acontece, calada.
    """
    CONVENCOES[0] = ("rotulada", _montar_gramatica())


def registrar_rotulo_de_cena(rotulo: str) -> None:
    """`registrar_rotulo_de_cena("TOMADA")` e pronto — sem tocar em regex."""
    ROTULOS_DE_CENA.append(rotulo)
    recompilar()


def registrar_rotulo_de_plano(rotulo: str) -> None:
    ROTULOS_DE_PLANO.append(rotulo)
    recompilar()


def registrar_rotulo_de_take(rotulo: str) -> None:
    ROTULOS_DE_TAKE.append(rotulo)
    recompilar()


def registrar_convencao(nome: str, padrao: str) -> None:
    """Acrescenta uma convenção ao fim da lista.

    O padrão precisa dos três grupos nomeados `cena`, `plano` e `take`. Falta de
    algum estoura aqui, na hora de registrar — e não lá adiante, com um `KeyError`
    dentro de uma varredura de 24 takes.
    """
    compilado = re.compile(padrao, re.IGNORECASE)
    faltando = {"cena", "plano", "take"} - set(compilado.groupindex)
    if faltando:
        raise ValueError(
            f"convenção {nome!r} sem os grupos nomeados {sorted(faltando)}"
        )
    CONVENCOES.append((nome, compilado))


def ler(nome: str) -> Claquete | None:
    """A claquete de um nome de som — ou `None` se nenhuma convenção casar.

    Aceita nome de master (sem extensão) e nome de arquivo (com), porque as duas
    formas circulam: a bin traz uma, o disco traz a outra.

    ⚠️ **`None` é resposta legítima, não falha.** Ver o topo do módulo.
    """
    if not nome:
        return None
    nome = str(nome)
    if not nome.strip():
        return None
    limpo = Path(nome.strip()).stem if "." in nome else nome.strip()
    for rotulo, padrao in CONVENCOES:
        m = padrao.search(limpo)
        if not m:
            continue
        return Claquete(
            cena="C" + dois_digitos(m.group("cena")),
            plano="P" + dois_digitos(m.group("plano")),
            take="T" + dois_digitos(m.group("take")),
            convencao=rotulo,
            episodio=("E" + dois_digitos(m.groupdict()["episodio"])) if m.groupdict().get("episodio") else "",
        )
    return None


def nome_de_subclipe(c: Claquete) -> str:
    """`C04_P01_T002` — o nome que vai para a bin.

    ⭐ O nome carrega tudo de propósito (§10 do spec): é o que faz a bin sobreviver a
    exportar, arquivar e reabrir noutro projeto. Metadado se perde na travessia; nome
    não.
    """
    return f"{c.cena}_{c.plano}_{c.take}"


def e_descartado(caminho) -> bool | None:
    """O arquivo está numa pasta de descarte do técnico de som?

    ⚠️⚠️ **`None` significa NÃO AVALIADO, e nunca "não descartado".** Mesma disciplina
    do campo `medida` do §7: vazio é *não medido*, jamais *zero*. Um take cujo caminho
    de arquivo não se conhece — mídia gerenciada sem coluna lida, por exemplo — não
    pode receber atestado de que sobreviveu ao descarte.
    """
    if not caminho:
        return None
    partes = {p.strip().upper() for p in Path(str(caminho)).parts}
    return bool(partes & PASTAS_DE_DESCARTE)
