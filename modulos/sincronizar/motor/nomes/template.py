"""`padrão + campos → texto`. O motor de wildcard, puro e sem I/O.

A sintaxe é a mínima que resolve o problema, e isso é decisão registrada (2026-08-28):

    %campo    o valor do campo
    %{campo}  o mesmo valor, com a tag FECHADA
    %%        um `%` literal
    resto     literal

**Sem modificadores.** Onde a coluna crua não serve, quem resolve é um *campo derivado*
já pronto (`%cena`, `%plano`, `%take2`), calculado em `campos.py`. O trabalho fica no
motor, não na cabeça do editor.

## ⭐⭐ A tag FECHADA, e por que ela precisou existir

**Achado pelo autor usando, 2026-09-06:** ele escreveu `C%cenaP%plano` e o motor leu
`%cenap` — um campo que não existe. Nenhuma regra de recuo salva esse caso: `cenaP` não
tem `_`, e adivinhar onde o campo termina no meio de um literal colado é chute. O que o
autor pediu foi o gesto certo:

> *"podemos criar um sistema de fechar a tag quando o usuário confirmar. […] para ficar
> uma visualização melhor no campo, podemos usar um formato que o Davinci Resolve faz
> com caixinhas delimitando a tag"*

Então `%{cena}` **delimita**: o campo é o que está entre as chaves, ponto. Não há recuo,
não há adivinhação, e `C%{cena}P%{plano}-T%{take}` funciona porque não existe pergunta a
responder. O painel insere esta forma sempre que o editor confirma uma sugestão ou
clica num card — o `%campo` solto continua valendo para quem digita, e para os padrões
que já existem.

⚠️ Uma tag ABERTA (`%{cena` sem `}`) é **desconhecida**, não um campo pela metade: ela
consome só o `%{` mais o identificador, para que o resto do padrão continue analisável e
o editor veja em vermelho exatamente a tag que ficou aberta.

## ⚠️⚠️ O recuo, que é o coração do desenho

`_` é caractere válido de nome de campo — precisa ser, porque as colunas do Avid
normalizam `Shoot Date` → `shoot_date`. Só que o exemplo do próprio autor é
`C%scene-P%shoot_T%take`, onde `_T` é literal. Um casamento guloso leria `shoot_t`,
não acharia campo nenhum, e as duas saídas óbvias são ruins:

- **acusar erro** — recusa um padrão que o autor quer, e que é o formato natural;
- **render vazio** — produz um lote inteiro de nomes truncados, plausíveis, que só o
  olho pega clipe por clipe. É o falso-verde deste projeto com outra roupa.

Então o token **recua**: procura o maior campo do catálogo que seja prefixo do token
guloso **e que termine num `_`**, e devolve o resto como literal. `shoot_t` → campo
`shoot` + literal `_T`.

⚠️ A fronteira em `_` não é detalhe. Sem ela, `%scenex` recuaria para `scene` + `x` —
mas `scenex` é erro de digitação, não composição. Com ela, `%scenex` é **desconhecido**
e o painel pinta de vermelho, que é o que o autor pediu.

⚠️ E recuar é uma decisão do motor sobre o que o editor escreveu. Decisão calada é o que
este projeto não aceita: `Token.cauda` carrega o que virou literal, para o painel poder
mostrar.

## O que levanta e o que não

⭐ **Chave AUSENTE do dicionário é erro; chave PRESENTE e vazia é fato do material.**
`render` levanta no primeiro caso e devolve vazio no segundo — e é essa distinção que
faz a ferramenta servir ao Projeto C, onde não há cena nenhuma e travar todo padrão com
`%cena` a tornaria inútil justamente no produto que mais precisa dela.

⚠️ Quem bloqueia o *nome vazio* NÃO é este módulo: é o consumidor, que é quem sabe que
um clipe não pode se chamar nada. Um padrão que rende vazio é legítimo para outra função
futura, e misturar as duas coisas travaria ela sem motivo.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: A forma que um campo pode ter para ser DIGITÁVEL num padrão. `normalizar` garante
#: esta forma, e o parser só reconhece esta forma — se as duas divergissem, existiria
#: campo no catálogo que nenhum `%` alcança, e o editor veria um campo que nunca casa.
CAMPO_VALIDO = re.compile(r"[a-z_][a-z0-9_]*")

_TOKEN_GULOSO = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: `%{cena}` — a tag fechada. ⚠️ Só `}` fecha, e o que está dentro tem de ser um nome
#: de campo inteiro: `%{ }`, `%{}` e `%{25}` são desconhecidos, não literais. Aceitar
#: qualquer coisa entre chaves faria a tag fechada mentir sobre o que ela delimita.
_FECHADO = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: A tag ABERTA, para o token parar no identificador e não engolir o resto do padrão.
_ABERTO = re.compile(r"\{[A-Za-z0-9_]*")


class PadraoInvalido(ValueError):
    """O padrão tem `%` que não resolve para campo nenhum.

    ⚠️ Levantada por `render`, nunca por `analisar`/`validar` — o painel precisa
    analisar um padrão pela metade a cada tecla digitada, e um padrão pela metade é
    normal, não excepcional.
    """

    def __init__(self, tokens):
        self.tokens = list(tokens)
        ruins = ", ".join(repr(t.bruto) for t in self.tokens)
        super().__init__(f"campo(s) que não existem no catálogo: {ruins}")


@dataclass(frozen=True)
class Token:
    """Um `%…` encontrado no padrão, já resolvido (ou não) contra o catálogo.

    `inicio`/`fim` — as posições NO PADRÃO ORIGINAL, para o painel pintar de vermelho
                     exatamente o pedaço que o editor digitou.
    `bruto`        — o texto como ele escreveu, com o `%`.
    `campo`        — o campo do catálogo que casou, ou **`None`** = desconhecido.
    `cauda`        — o que sobrou como literal depois do recuo (`"_T"`), ou `""`.
    """

    inicio: int
    fim: int
    bruto: str
    campo: str | None
    cauda: str = ""


def normalizar(nome: str) -> str:
    """Nome de coluna do Avid → nome de campo digitável.

    `"Shoot Date"` → `"shoot_date"`, `"TRK1"` → `"trk1"`, `"Áudio Nº"` → `"audio_no"`.

    ⚠️ Uma coluna custom pode se chamar qualquer coisa — o editor a criou na bin. Se a
    normalização deixasse passar `-`, `%` ou acento, o campo existiria no catálogo e
    seria **indigitável**: o parser pararia antes dele. Por isso a saída é sempre
    `CAMPO_VALIDO`, e há teste que prova.
    """
    # ⭐ NFKD antes de descartar: `Á` vira `A` + acento (que sai), e `º` vira `o`. Sem
    # isto `"Áudio"` viraria `"_udio"` — legal, mas irreconhecível para quem digita.
    cru = unicodedata.normalize("NFKD", str(nome or "").strip())
    cru = "".join(c for c in cru if not unicodedata.combining(c)).lower()
    saida = re.sub(r"[^a-z0-9]+", "_", cru).strip("_")
    if not saida:
        return "_"
    # ⚠️ Campo não pode COMEÇAR com dígito, senão `CAMPO_VALIDO` o rejeita e ele fica
    # indigitável. Uma coluna chamada `50% OK` é esquisita, mas é do editor.
    if saida[0].isdigit():
        saida = "_" + saida
    return saida


def _catalogo(campos) -> set[str]:
    """As chaves disponíveis, aceitando dict ou qualquer iterável de nomes."""
    if hasattr(campos, "keys"):
        return set(campos.keys())
    return set(campos or ())


def _recuar(token: str, catalogo: set[str]) -> tuple[str | None, str]:
    """`("shoot", "_t")` para `token="shoot_t"` — ou `(None, "")` se nada casar.

    ⚠️ A fronteira é o `_`, e só ele. Ver o topo do módulo.
    """
    if token in catalogo:
        return token, ""
    # Do maior prefixo para o menor: `a_b_c` → `a_b`, `a`.
    corte = len(token)
    while True:
        corte = token.rfind("_", 0, corte)
        if corte <= 0:
            return None, ""
        prefixo = token[:corte]
        if prefixo in catalogo:
            return prefixo, token[corte:]


def _varrer(padrao: str, campos) -> list:
    """O padrão em pedaços: `("lit", texto)` e `("campo", Token)`, em ordem.

    ⭐ Um varredor só, usado por `render`, `analisar` e `validar`. Três varreduras
    independentes divergiriam — e a que divergisse seria a do preview contra a do
    aplicar, que é o pior lugar possível.
    """
    catalogo = _catalogo(campos)
    padrao = str(padrao or "")
    fora: list = []
    literal: list[str] = []
    i = 0
    n = len(padrao)

    def _fechar_literal():
        if literal:
            fora.append(("lit", "".join(literal)))
            literal.clear()

    while i < n:
        if padrao[i] != "%":
            literal.append(padrao[i])
            i += 1
            continue
        # `%%` — a válvula de escape. Consome os dois e emite UM literal.
        if i + 1 < n and padrao[i + 1] == "%":
            literal.append("%")
            i += 2
            continue
        # ⭐ `%{campo}` — a tag FECHADA vem ANTES do casamento guloso, e tem de vir:
        # ela é a forma sem ambiguidade, e quem a escreveu já disse onde o campo
        # termina. Nada de recuo aqui — não há o que recuar.
        if i + 1 < n and padrao[i + 1] == "{":
            fechado = _FECHADO.match(padrao, i + 1)
            if fechado:
                nome = fechado.group(1).lower()
                _fechar_literal()
                fora.append(("campo", Token(
                    inicio=i, fim=fechado.end(),
                    bruto=padrao[i:fechado.end()],
                    campo=nome if nome in catalogo else None,
                    cauda="",
                )))
                i = fechado.end()
                continue
            # Tag ABERTA: consome `%{` mais o que parece nome, e para. O resto do
            # padrão continua sendo analisado — quem digita fecha a tag depois.
            aberto = _ABERTO.match(padrao, i + 1)
            fim = aberto.end() if aberto else i + 2
            _fechar_literal()
            fora.append(("campo", Token(i, fim, padrao[i:fim], None, "")))
            i = fim
            continue
        m = _TOKEN_GULOSO.match(padrao, i + 1)
        if not m:
            # `%` no fim, ou seguido de algo que não abre nome de campo (`%-`, `%1`).
            # ⚠️ É o caso que o autor pediu para bloquear explicitamente.
            _fechar_literal()
            fora.append(("campo", Token(i, i + 1, "%", None, "")))
            i += 1
            continue
        guloso = m.group(0)
        fim = m.end()
        campo, cauda = _recuar(guloso.lower(), catalogo)
        _fechar_literal()
        # ⭐ `bruto` é só o que o token de fato consumiu. Com recuo, a cauda volta a ser
        # literal e NÃO entra no `bruto` — senão o painel pintaria de vermelho um
        # pedaço que está correto.
        #
        # ⚠️ Sem `if campo`: quando nada resolve, `_recuar` devolve cauda vazia, então
        # `consumido == len(guloso)` e o token guloso INTEIRO fica vermelho — que é o
        # certo (não há como saber onde o campo terminaria). Um condicional aqui seria
        # código morto, e a mutação provou: o mutante que o removia sobreviveu.
        consumido = len(guloso) - len(cauda)
        fora.append(("campo", Token(
            inicio=i, fim=i + 1 + consumido,
            bruto="%" + guloso[:consumido],
            campo=campo, cauda=guloso[consumido:],
        )))
        if cauda:
            literal.append(guloso[consumido:])
        i = fim

    _fechar_literal()
    return fora


def analisar(padrao: str, campos) -> list[Token]:
    """Todos os `%…` do padrão, resolvidos contra o catálogo, em ordem.

    Nunca levanta: o painel chama isto a cada tecla, e meio padrão é normal.
    """
    return [t for tipo, t in _varrer(padrao, campos) if tipo == "campo"]


def validar(padrao: str, campos) -> list[Token]:
    """Só os tokens que NÃO resolveram — o que o painel pinta de vermelho e o que
    bloqueia o botão de aplicar."""
    return [t for t in analisar(padrao, campos) if t.campo is None]


def campos_usados(padrao: str, campos) -> list[str]:
    """Os campos que o padrão de fato consome, na ordem, sem repetir a resolução."""
    return [t.campo for t in analisar(padrao, campos) if t.campo]


def render(padrao: str, campos: dict) -> str:
    """O texto final. Levanta `PadraoInvalido` se algum `%` não resolver.

    ⚠️⚠️ Recusar, e não render vazio: um `%xyz` esquecido produziria um lote de nomes
    truncados e plausíveis, que só o olho pega clipe por clipe. Ver o topo do módulo.
    """
    pedacos = _varrer(padrao, campos)
    ruins = [t for tipo, t in pedacos if tipo == "campo" and t.campo is None]
    if ruins:
        raise PadraoInvalido(ruins)
    fora: list[str] = []
    for tipo, valor in pedacos:
        if tipo == "lit":
            fora.append(valor)
        else:
            # ⭐ `""` só para `None` — o fato do material (coluna que este clipe não
            # tem). A chave ausente já foi barrada acima, então o `get` não esconde
            # nada.
            #
            # ⚠️⚠️ **`or ""` aqui seria um bug**, e a mutação foi quem o achou: `0 or ""`
            # é `""`, então um campo cujo valor é zero — take 0, duração 0, um contador
            # — sumiria do nome sem deixar rastro. É exatamente o falso-verde deste
            # projeto: nome plausível, dado perdido, ninguém avisado.
            bruto = campos.get(valor.campo)
            fora.append("" if bruto is None else str(bruto))
    return "".join(fora)
