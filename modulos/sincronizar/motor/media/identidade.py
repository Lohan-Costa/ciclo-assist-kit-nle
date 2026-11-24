"""De onde sai a identidade de tomada de um clipe.

A ordem, decidida pelo autor em 2026-08-29:

1. **coluna do Avid** — o técnico de som escreveu no set. Declaração, não derivação;
2. **nome do clipe** — o que o editor vê e pode ter renomeado de propósito;
3. **nome do master** — o arquivo que o gravador escreveu, que carrega a claquete
   por construção;
4. ⛔ **nada** — o clipe entra SEM POSIÇÃO na série. Não é erro.

⭐ Por que o degrau 3 existe, medido em 2026-08-29 sobre a `CENAS/C04.avb`:
`claquete.ler("C04_P06-T003")` devolve `None` (o nome do subclipe tem hífen antes
do T), mas `claquete.ler("PROJETO A - 05-04 C4 P6-T003")` resolve inteiro. E o
leitor de subclipes já calcula esse nome.

⚠️ Por que o degrau 4 não é erro: um clipe sem claquete ainda pode conter a fala.
O que ele não pode é **vencer a corrida do "mais tardio"** — a mesma regra que
`montador._grupo_numerico` aplica ao rótulo ilegível, mandando-o ao grupo BAIXO em
vez de descartá-lo. Inventar posição aqui seria fabricar uma cronologia que
ninguém mediu.

⚠️ Nada aqui abre arquivo.

⭐ Portado do Assist anterior (`assist_anterior/clipes/identidade.py`) em 2026-09-05.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass

from media import claquete as _claquete
from media import memoria_da_producao as _memoria

#: De onde a identidade veio. ⚠️ Sempre preenchido — é o que permite ao plano
#: DECLARAR "este clipe entrou sem posição" em vez de o editor descobrir por um
#: take na ordem errada.
COLUNA = "coluna"
NOME_DO_CLIPE = "nome_do_clipe"
NOME_DO_MASTER = "nome_do_master"
SEM_POSICAO = "sem_posicao"
#: A regra veio da memória da produção: o editor disse, então vence a coluna e a claquete, e o painel não marca como presumida.
MEMORIA = "memoria"

#: As colunas de cena e de tomada, nas grafias que aparecem numa bin do Avid.
_COLUNAS_DE_CENA = ("Scene", "scene", "Cena", "cena")
_COLUNAS_DE_TAKE = ("Take", "take", "Tomada", "tomada")


@dataclass(frozen=True)
class Identidade:
    """⚠️ Campos `None`, nunca `""`: vazio compara e ordena, `None` obriga quem
    usa a decidir o que fazer com a ausência.

    ⭐⭐ `convencao` e `origem` são coisas DIFERENTES, e as duas viajam:

    - `origem` é deste módulo — qual degrau resolveu (coluna, nome, master, nada);
    - `convencao` é da `claquete` — QUAL gramática casou (`rotulada`, `posicao`,
      `subclipe`, uma registrada pelo usuário).

    ⛔ A segunda não pode ser substituída pela primeira: `avid/takes.py` e o
    painel leem `convencao == "posicao"` para mostrar *"cena presumida"* ao
    editor, e trocar o vocabulário apagaria esse aviso da tela.
    """

    cena: str | None
    plano: str | None
    take: str | None
    origem: str
    convencao: str | None = None
    episodio: str | None = None


_SEM = Identidade(None, None, None, SEM_POSICAO)


def _primeira(d: dict, chaves) -> str:
    for k in chaves:
        v = str((d or {}).get(k) or "").strip()
        if v:
            return v
    return ""


def _take_canonico(bruto: str) -> str:
    """`"7"` → `"T007"`.

    ⚠️ TRÊS dígitos no take e DOIS na cena, e a assimetria é da convenção do §10,
    não descuido: a claquete escreve `C04` e `T003`, e é assim que
    `claquete.ler` devolve — misturar as larguras faria a identidade vinda de
    coluna não comparar com a vinda de nome.

    ⚠️ `claquete.dois_digitos` não serve aqui: ele não tem largura configurável.
    """
    digitos = re.sub(r"\D", "", bruto)
    return "T" + (digitos.zfill(3) if digitos else bruto.strip())


def _da_coluna(colunas: dict) -> Identidade | None:
    """⚠️ Exige cena E tomada. Meia coluna daria cena certa com take vazio, e o
    montador ordenaria por um campo que ninguém preencheu."""
    cena = _primeira(colunas, _COLUNAS_DE_CENA)
    take = _primeira(colunas, _COLUNAS_DE_TAKE)
    if not (cena and take):
        return None
    # ⭐⭐ A gramática SEPARA o que a coluna traz junto — quando reconhece.
    #
    # No material real a coluna vem `25-6` ou `C11 P03 PICUP`: cena e plano no
    # mesmo campo, porque a coluna `Scene` do Avid não tem lugar para o plano.
    # Recompondo `Scene` + `-T` + `Take` e passando pela claquete, um material em
    # convenção conhecida sai com os três campos separados.
    #
    # ⚠️ E quando ela NÃO reconhece, o valor cru da coluna prevalece — nunca se
    # inventa uma separação. É a diferença entre ler a convenção do técnico e
    # impor a nossa.
    separada = _claquete.ler(f"{cena}-T{take}")
    if separada is not None:
        # ⛔ O `.1` do órfão batizado pela posição (`001.1`) a claquete toma por extensão
        # de arquivo e corta — e o órfão voltava com a identidade do take real anterior.
        m = re.search(r"\.(\d+)\s*$", str(take))
        return Identidade(cena=separada.cena, plano=separada.plano,
                          take=separada.take + (f".{m.group(1)}" if m else ""), origem=COLUNA,
                          convencao=separada.convencao, episodio=separada.episodio or None)

    return Identidade(
        # ⭐⭐ A cena sai COMO ESTÁ NA COLUNA, sem prefixo nosso.
        #
        # Prefixar com `C` e normalizar para dois dígitos foi a regra até
        # 2026-09-05, e ela **inventava** sobre o que o técnico escreveu: numa
        # diária real do autor a coluna traz `25-6` (cena 25, plano 6, na
        # convenção dele) e saía `C25-6`; um `C09` da coluna virava `CC09`.
        #
        # ⚠️ A decisão do autor é a razão: *"a identidade da cena deve vir da
        # coluna dos sons diretos — tem a variação do técnico de som, que coloca
        # a convenção que quiser"*. Se a convenção é dele, normalizá-la é
        # sobrescrevê-la.
        cena=cena,
        # ⚠️ A coluna não traz PLANO. Sai `None`, e não se inventa: a regra do
        # montador pesa plano antes de take, e um plano fabricado mudaria a
        # escolha da tomada por um dado que ninguém preencheu.
        plano=None,
        take=_take_canonico(take),
        origem=COLUNA)


def _de_nome(nome: str, origem: str) -> Identidade | None:
    from avid import takes as _takes

    bruto = str(nome or "").strip()
    if not bruto:
        return None
    c = _takes._de_nome_de_subclipe(bruto) or _claquete.ler(bruto)
    if c is None:
        return None
    return Identidade(cena=c.cena, plano=c.plano, take=c.take, origem=origem,
                      convencao=c.convencao, episodio=c.episodio or None)


#: A marca de quem saiu daqui: o painel a mostra como "presumida", igual à cena presumida pela posição.
FORMA_DA_DIARIA = "forma_da_diaria"
_NUMERO_NUMERO = re.compile(r"^(\d+[A-Za-z]?)-(\d+)$")
#: PRODB, medido em 2026-11-08: 33 de 43 (77%). "Todas" nunca valeria: uma diária real tem `18-EXTRA` e `17B-18-1`.
_FATIA_MINIMA = 2 / 3
_MINIMO_DE_TOMADAS = 3


def presumir_da_forma(cenas: list) -> dict[str, tuple[str, str]]:
    """`{"18-1": ("C18", "P01")}`: a cena sem rótulo que a DIÁRIA autoriza ler como cena-plano.

    ⚠️ Sozinho, `18-1` não prova nada (a decisão do autor de 2026-08-28: não se deriva sem rótulo). A exceção dele (2026-11-08) é
    presumir, marcado, quando a maior parte da diária tem essa forma. O que não tem a forma fica como está. `cenas`: uma por tomada."""
    validas = [str(c) for c in cenas if c]
    casam = [c for c in validas if _NUMERO_NUMERO.match(c)]
    if len(casam) < _MINIMO_DE_TOMADAS or len(casam) / len(validas) < _FATIA_MINIMA:
        return {}
    saida: dict[str, tuple[str, str]] = {}
    for c in casam:
        m = _NUMERO_NUMERO.match(c)
        saida[c] = ("C" + _claquete.dois_digitos(m.group(1)), "P" + _claquete.dois_digitos(m.group(2)))
    return saida


#: As regras da produção da leitura em curso. Um comando do motor por vez (`servidor/motor.py`), e `com_regras` sempre limpa.
_regras_em_uso: tuple = ()


@contextmanager
def com_regras(regras):
    """Durante o bloco, `de_clipe` consulta as regras da memória da produção antes de tudo."""
    global _regras_em_uso
    anteriores, _regras_em_uso = _regras_em_uso, tuple(regras or ())
    try:
        yield
    finally:
        _regras_em_uso = anteriores


def _da_memoria(nome: str | None) -> Identidade | None:
    d = _memoria.aplicar(_regras_em_uso, nome or "")
    if d is None:
        return None
    return Identidade(cena=d["cena"], plano=d["plano"], take=d["take"], origem=MEMORIA, convencao=MEMORIA, episodio=d["episodio"])


def de_clipe(nome_do_clipe: str, nome_do_master: str | None = None,
             colunas: dict | None = None) -> Identidade:
    """A identidade deste clipe, e **de onde ela veio**. Nunca levanta."""
    return (_da_memoria(nome_do_clipe)
            or _da_memoria(nome_do_master)
            or _da_coluna(colunas or {})
            or _de_nome(nome_do_clipe, NOME_DO_CLIPE)
            or _de_nome(nome_do_master or "", NOME_DO_MASTER)
            or _SEM)
