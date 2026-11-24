"""O mapa de corte — a escrituração que o roteiro manda e o modelo não faz de cabeça.

⛔⛔ **Proposta do editor em 2026-09-12, e ela troca um princípio.** Até aqui, "não repita
fala" e "siga a ordem do roteiro" eram PROSA: estavam escritas em
`skills/montar-por-roteiro.md` §1 e §2, o modelo consultou o método 16 s depois do turno
abrir, leu as duas regras, e entregou uma cena com fala repetida e diálogo fora de ordem.
Regra que ninguém confere não é regra, é conselho.

Aqui a ordem deixa de ser conselho. O laço é sobre as FALAS DO ROTEIRO, e o serviço guarda
o que já foi atribuído — o modelo julga o casamento ("Sinceramente? Não!" é a mesma fala
que "Sinceramente, não."), que é semântica e é para ele; o código conta, que é
escrituração e nunca foi para ele.

⭐ Mesmo desenho da decupagem em lote: **o modelo responde, o serviço grava validando.**

## A regra de ordem, e por que ela não é "cada fala uma vez"

Três coisas que parecem erro e não são, todas medidas no material da C07:

- **N→1** — duas falas seguidas do mesmo take com vão curto viram UM corte. A pausa é
  atuação, e a ambiência que some no meio denuncia a emenda (`montar-por-roteiro.md` §3).
- **1→N** — uma fala longa coberta por dois ângulos. Não é fala repetida: é a mesma fala
  continuada.
- **1→0** — fala sacrificada. Legítima, desde que DITA.

⇒ Por isso a regra é: a sequência de números de fala tem de ser **não-decrescente**, e as
ocorrências de cada número têm de ser **contíguas**. Voltar a uma fala depois de ter
passado para outra é o defeito — e é exatamente o que o editor viu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class MapaInvalido(ValueError):
    """O mapa não fecha com o roteiro. A mensagem diz o que consertar, corte a corte."""


# ── o roteiro vira estrutura ─────────────────────────────────────────────────

#: Um nome de personagem é curto, sozinho na linha e em CAIXA ALTA. Um limite generoso
#: porque cabeçalho de cena também é caixa alta — e é o comprimento que os separa.
MAX_NOME = 28

#: ⚠️ O cabeçalho de cena é caixa alta igual ao nome do personagem ("7. INT. CONSULTÓRIO.
#: NOITE"). Sem esta peneira, "INT. CONSULTÓRIO. NOITE" viraria um personagem com uma
#: fala — e a fala 1 da cena passaria a ser a rubrica.
CABECALHO = re.compile(r"^\s*(\d+[\.\)]\s*)?(INT|EXT|INT\./EXT)\b", re.I)


@dataclass(frozen=True)
class Fala:
    """Uma fala do roteiro, no lugar dela na ordem."""

    n: int
    personagem: str
    texto: str

    def resumo(self, quanto: int = 60) -> str:
        corte = self.texto[:quanto]
        return f"{self.n}. {self.personagem}: {corte}{'…' if len(self.texto) > quanto else ''}"


def _e_nome(linha: str) -> bool:
    nu = linha.strip()
    if not nu or len(nu) > MAX_NOME or CABECALHO.match(nu):
        return False
    if nu != nu.upper():
        return False
    # Precisa ter letra: uma linha de "---" ou "(PAUSA)" não é personagem.
    if not any(c.isalpha() for c in nu):
        return False
    # Rubrica entre parênteses não é quem fala.
    return not (nu.startswith("(") and nu.endswith(")"))


def estruturar(texto: str) -> list[Fala]:
    """O texto do roteiro vira a lista ordenada de falas.

    ⭐ A granularidade é o PARÁGRAFO, não a personagem: uma fala longa separada por linha
    em branco é onde o editor corta, e o modelo precisa poder atribuir cada pedaço a um
    plano diferente. Juntar tudo numa fala só esconderia justamente o ponto de corte.
    """
    falas: list[Fala] = []
    personagem = ""
    paragrafo: list[str] = []

    def fechar() -> None:
        nonlocal paragrafo
        corpo = " ".join(paragrafo).strip()
        if corpo and personagem:
            falas.append(Fala(len(falas) + 1, personagem, corpo))
        paragrafo = []

    for linha in (texto or "").splitlines():
        nu = linha.strip()
        if not nu:
            fechar()
            continue
        if CABECALHO.match(nu):
            fechar()
            personagem = ""
            continue
        if _e_nome(nu):
            fechar()
            personagem = nu
            continue
        paragrafo.append(nu)
    fechar()
    return falas


# ── a escrituração ───────────────────────────────────────────────────────────


@dataclass
class Atribuicao:
    """Um corte do mapa: que falas do roteiro ele carrega, e de onde."""

    falas: list[int]
    take: str
    inicio_no_take_frames: int
    duracao_frames: int
    porque: str
    corte_de_som: str = "junto"
    som_frames: int = 0


@dataclass
class Conferencia:
    """O que a escrituração achou. Vazia de problemas é mapa aprovado."""

    problemas: list[str] = field(default_factory=list)
    cobertas: list[int] = field(default_factory=list)
    sacrificadas: list[int] = field(default_factory=list)
    #: Os takes que o mapa usa. ⭐ Vai na resposta para o editor VER a cobertura — um
    #: mapa de quinze cortes num plano só se denuncia nesta linha antes de qualquer
    #: conferência.
    planos_usados: list[str] = field(default_factory=list)

    @property
    def fecha(self) -> bool:
        return not self.problemas


def conferir(roteiro: list[Fala], atribuicoes: list[Atribuicao]) -> Conferencia:
    """A regra de ordem, aplicada. Não julga o casamento — julga a escrituração."""
    conf = Conferencia()
    validos = {f.n for f in roteiro}
    if not atribuicoes:
        conf.problemas.append("o mapa está vazio: nenhum corte foi atribuído.")
        return conf

    #: A sequência achatada, na ordem em que os cortes entram na timeline.
    sequencia: list[tuple[int, int]] = []  # (n da fala, índice do corte)
    for i, a in enumerate(atribuicoes, 1):
        if not a.falas:
            conf.problemas.append(
                f"corte {i} ({a.take}): não diz que fala do roteiro ele carrega. Se for "
                f"material sem fala (respiro, reação), diga isso em `porque` e use a "
                f"fala que ele cobre.")
            continue
        for n in a.falas:
            if n not in validos:
                conf.problemas.append(
                    f"corte {i} ({a.take}): fala {n} não existe no roteiro "
                    f"(ele vai de 1 a {len(roteiro)}).")
                continue
            sequencia.append((n, i))
        if a.duracao_frames < 2:
            conf.problemas.append(
                f"corte {i} ({a.take}): duracao_frames={a.duracao_frames}. "
                f"Isso parece segundo no lugar de frame.")

    numeros = [n for n, _ in sequencia]

    # ⛔ A ordem: não-decrescente. Um número menor depois de um maior é o diálogo fora da
    #    ordem do roteiro — o sintoma que o editor nomeou.
    for k in range(1, len(numeros)):
        if numeros[k] < numeros[k - 1]:
            corte = sequencia[k][1]
            conf.problemas.append(
                f"corte {corte}: volta para a fala {numeros[k]} depois de já ter chegado "
                f"na {numeros[k - 1]}. O roteiro manda na ordem.")

    # ⛔ Contíguas: 1→N (uma fala longa em dois ângulos) é legítimo e vem colado. Voltar
    #    à mesma fala depois de outra é fala repetida.
    onde: dict[int, list[int]] = {}
    for pos, (n, _) in enumerate(sequencia):
        onde.setdefault(n, []).append(pos)
    for n, posicoes in onde.items():
        if posicoes[-1] - posicoes[0] + 1 != len(posicoes):
            cortes = sorted({sequencia[p][1] for p in posicoes})
            conf.problemas.append(
                f"a fala {n} aparece nos cortes {cortes} com outra fala no meio: isso é "
                f"fala repetida. Para cobrir uma fala longa com dois ângulos, os cortes "
                f"têm de vir colados.")

    conf.problemas.extend(_emendas_no_mesmo_take(atribuicoes))
    conf.planos_usados = sorted({a.take for a in atribuicoes if a.take})
    conf.cobertas = sorted(onde)
    conf.sacrificadas = sorted(validos - set(onde))
    return conf


def _emendas_no_mesmo_take(atribuicoes: list[Atribuicao]) -> list[str]:
    """Corte que vai de um take para ELE MESMO — e material usado duas vezes.

    ⛔⛔ **MEDIDO em 2026-09-12, e é uma regressão que este módulo criou.** A primeira
    versão conferia ordem, repetição de fala e a âncora no material. Um modelo fraco
    (Haiku 4.5) mandou 16 cortes em 5 takes, levou duas reprovações legítimas da âncora,
    e então **colapsou os 16 cortes no `C07_P01-T001`** — o plano aberto que contém a cena
    inteira, onde TODA fala bate 100%. O mapa foi aprovado.

    ⇒ Eu validava *"a fala está mesmo aqui"*, e um master de cena inteira satisfaz isso
    para todas elas. Tinha transformado "não aponte material errado" em "aponte tudo para
    o take que sempre passa".

    ⭐ A regra que fecha isso não é cota de cobertura — ritmo é ofício e é do editor. É que
    **cortar de um plano para ele mesmo é jump cut**: o que sai são dezesseis emendas
    invisíveis, ou seja, o take tocado do começo ao fim com as pausas tiradas. O método já
    dizia metade disso (`montar-por-roteiro.md` §3: duas falas seguidas do mesmo take com
    vão curto viram UM corte); aqui a outra metade passa a ser conferida.
    """
    problemas: list[str] = []

    # ⚠️ Compacto de propósito. A primeira versão emitia uma linha por par e o mapa
    #    degenerado voltava com VINTE E UMA — e cada linha dessas é contexto que o editor
    #    paga, num turno que já deu errado.
    emendas = [i for i in range(1, len(atribuicoes))
               if atribuicoes[i].take and atribuicoes[i - 1].take == atribuicoes[i].take]
    if emendas:
        takes = {a.take for a in atribuicoes if a.take}
        pares = ", ".join(f"{i}→{i + 1}" for i in emendas[:8])
        resto = "…" if len(emendas) > 8 else ""
        if len(takes) == 1 and len(atribuicoes) > 2:
            problemas.append(
                f"os {len(atribuicoes)} cortes saem todos do {atribuicoes[0].take}, um "
                f"atrás do outro. Isso não é montagem: é o take tocado de ponta a ponta "
                f"com as pausas tiradas, e cada emenda é um jump cut. Se este é mesmo o "
                f"único plano com a cena, monte UM corte só; senão, alterne os ângulos "
                f"que você transcreveu.")
        else:
            problemas.append(
                f"cortes vizinhos do MESMO take ({pares}{resto}): cortar de um plano para "
                f"ele mesmo é jump cut. Se as falas são seguidas, use UM corte cobrindo "
                f"as duas; se quer trocar de ângulo, escolha outro take.")

    # ⛔ Material usado duas vezes. Dois cortes do mesmo take cujos intervalos se cruzam
    #   põem o mesmo trecho na tela de novo — MEDIDO no mesmo mapa: os cortes 9 e 10
    #   começavam no frame 2613 os dois. Nem o `plano/esquema.py` nem a âncora pegavam.
    cruzados: list[str] = []
    for i, a in enumerate(atribuicoes, 1):
        for j, b in enumerate(atribuicoes[i:], i + 1):
            if not a.take or a.take != b.take:
                continue
            fim_a = a.inicio_no_take_frames + a.duracao_frames
            fim_b = b.inicio_no_take_frames + b.duracao_frames
            if a.inicio_no_take_frames < fim_b and b.inicio_no_take_frames < fim_a:
                cruzados.append(f"{i} e {j}")
    if cruzados:
        problemas.append(
            f"cortes que pegam o MESMO trecho do mesmo take ({'; '.join(cruzados[:8])}"
            f"{'…' if len(cruzados) > 8 else ''}): esse material entra duas vezes na "
            f"sequência.")
    return problemas


def relatar(roteiro: list[Fala], conf: Conferencia) -> str:
    """O que dizer ao modelo — o mesmo texto, aprovado ou não."""
    linhas = [f"{len(conf.cobertas)} de {len(roteiro)} falas do roteiro estão no mapa, "
              f"em {len(conf.planos_usados)} plano(s)."]
    if conf.sacrificadas:
        # ⚠️ Não é erro: sacrificar fala é decisão editorial legítima. Mas tem de ser
        #    DITA, senão o editor descobre no play.
        quais = ", ".join(str(n) for n in conf.sacrificadas[:12])
        resto = "…" if len(conf.sacrificadas) > 12 else ""
        linhas.append(
            f"Ficaram de fora as falas {quais}{resto} — diga ao editor quais e por quê, "
            f"ou inclua-as.")
    if conf.problemas:
        linhas.append("O mapa NÃO fecha:")
        linhas.extend(f"  - {p}" for p in conf.problemas)
    return "\n".join(linhas)


# ── a âncora: o que o mapa DIZ contra o que o take FALA ──────────────────────
#
# ⛔⛔ **MEDIDO em 2026-09-12, e é o achado que salva este módulo.** A escrituração acima,
# rodada contra os 15 cortes da C07 que o editor chamou de "horrível", **APROVA o mapa**:
# as falas declaradas estavam em ordem perfeita, 15 de 16, sem repetição nenhuma.
#
# O defeito não estava no que o modelo DISSE — estava no que ele APONTOU. Ele declarou a
# fala certa e escreveu o timestamp de outro take ("Sinceramente, não." está em 18,12 s no
# P02-T002 e em 26,72 s no P02-T003; ele usou 18,12 no P02-T003). Na tela isso vira fala
# repetida e diálogo fora de ordem, enquanto o mapa parece impecável.
#
# ⇒ Ordem e repetição no papel não bastam. O que fecha o buraco é confrontar o texto
#   declarado com o que a transcrição diz NAQUELE take NAQUELE intervalo — os dois textos
#   já estão na casa, e a conta é determinística.

#: ⚠️ Generoso de propósito. O ator NÃO diz o que está escrito: medido em material real,
#: 4 de 6 falas divergiram do roteiro e 7 de 11 tomadas tiveram improviso. Um piso alto
#: recusaria material bom. Take errado, porém, dá quase zero — é um abismo, não uma borda.
PARECENCA_MINIMA = 0.30

#: Palavra de uma ou duas letras concorda por acaso ("de", "o", "a", "que" já tem 3 mas
#: passa) e inflaria a parecença entre quaisquer duas frases em português.
MENOR_PALAVRA = 3


def _palavras(texto: str) -> set[str]:
    import unicodedata

    cru = unicodedata.normalize("NFKD", (texto or "").casefold())
    cru = "".join(c for c in cru if not unicodedata.combining(c))
    return {p for p in re.split(r"[^a-z0-9]+", cru) if len(p) >= MENOR_PALAVRA}


def parecenca(do_roteiro: str, do_take: str) -> float:
    """Quanto da fala do roteiro reaparece no que foi dito. 0 a 1.

    Não é distância de edição: é quanto do ROTEIRO foi encontrado. Improviso a mais não
    penaliza — o material manda no texto (`montar-por-roteiro.md` §1); o que interessa é
    se estamos olhando o trecho certo.
    """
    esperado = _palavras(do_roteiro)
    if not esperado:
        return 1.0
    return len(esperado & _palavras(do_take)) / len(esperado)


def ancorar(roteiro: list[Fala], atribuicoes: list[Atribuicao], falado) -> list[str]:
    """Confere cada corte contra a transcrição. `falado(take, inicio, duracao) -> str`.

    Devolve os problemas. Lista vazia é mapa ancorado no material de verdade.
    """
    por_n = {f.n: f for f in roteiro}
    problemas: list[str] = []
    for i, a in enumerate(atribuicoes, 1):
        esperado = " ".join(por_n[n].texto for n in a.falas if n in por_n)
        if not esperado:
            continue
        try:
            dito = falado(a.take, a.inicio_no_take_frames, a.duracao_frames)
        except Exception as e:  # noqa: BLE001 — transcrição indisponível não invalida o mapa
            problemas.append(f"corte {i} ({a.take}): não consegui conferir contra o "
                             f"material ({e}).")
            continue
        if dito is None:
            continue
        p = parecenca(esperado, dito)
        if p < PARECENCA_MINIMA:
            quais = ", ".join(str(n) for n in a.falas)
            problemas.append(
                f"corte {i}: você diz que aqui está a fala {quais} "
                f"({por_n[a.falas[0]].personagem}: \"{esperado[:48]}…\"), mas o "
                f"{a.take} nesse trecho fala \"{(dito or '')[:64]}…\" "
                f"(parecença {p:.0%}). Confira o take e o tempo — é assim que o "
                f"timestamp de um take entra em outro.")
    return problemas
