"""O plano de cortes, e a validação que o recusa INTEIRO.

⛔ **Item malformado recusa o plano inteiro, nunca só o item.** Mesma disciplina do
`allow_pickle=False` do Decupador: entrada malformada não passa "quase certa". Um plano
aplicado pela metade deixa o projeto do editor num estado que ninguém pediu, e que ele vai
ter de desfazer à mão.

⚠️ **E a mensagem diz QUAL item e O QUE falta.** Um "plano inválido" sozinho manda o editor
procurar no escuro — e, pior, manda o modelo tentar de novo sem saber o que corrigir.

O desenho está em `docs/spec/2026-09-10-corte-zero.md` §5.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, field

#: O vocabulário de procedência, o mesmo do produto inteiro (ver CLAUDE.md).
CONFIANCAS = ("confirmado", "inferido", "hipotese")
FONTES = ("claquete", "roteiro", "transcricao", "visual", "heuristica")

#: Um corte de menos de 2 frames não é corte — é engano de unidade (segundos no lugar de
#: frames costuma produzir exatamente isso).
DURACAO_MINIMA = 2

#: ⭐⭐ Onde o som corta, em relação ao corte de IMAGEM que começa este plano.
#:
#: | valor | o que acontece | como o editor chama |
#: |---|---|---|
#: | `junto` | imagem e som cortam no mesmo frame | corte seco |
#: | `antes` | o som deste plano entra ANTES da imagem dele | **corte em J** |
#: | `depois` | o som do plano ANTERIOR continua por baixo da imagem deste | **corte em L** |
#:
#: ⚠️ **Palavra, e não sinal, de propósito.** A versão com um número negativo/positivo é
#: mais curta e tem um modo de falha silencioso: sinal trocado vira um L onde se pediu um
#: J, e nada acusa — o editor só descobre assistindo.
CORTES_DE_SOM = ("junto", "antes", "depois")


class PlanoInvalido(ValueError):
    """Plano recusado. Nunca vira exceção genérica: quem chamou precisa poder distinguir
    'plano malformado' de 'erro ao ler o projeto'."""


#: ⭐ L/J é característica do agente Editor do fluxo de edição de cena (autor, 2026-11-09). Fica numa marca da THREAD, e
#: não num parâmetro de `montar_corte`: o que é parâmetro da ferramenta o modelo do chat pode mandar.
_agente_editor = threading.local()


@contextlib.contextmanager
def com_lj_do_agente_editor():
    """Só dentro deste bloco um plano pode trazer L/J. O chat continua no corte seco (autor, 2026-11-06 e 07)."""
    _agente_editor.ativo = True
    try:
        yield
    finally:
        _agente_editor.ativo = False


@dataclass
class Corte:
    take: str
    duracao_frames: int
    inicio_no_take: int = 0
    fala: str | None = None
    confianca: str = ""
    fonte: str = ""
    medida: float | None = None
    porque: str = ""
    #: Ver `CORTES_DE_SOM`. `junto` + 0 é o corte seco.
    corte_de_som: str = "junto"
    som_frames: int = 0

    @property
    def desloca(self) -> int:
        """Quantos frames o corte de SOM sai do lugar do corte de imagem.

        Negativo puxa o som para trás (J: ele entra antes), positivo empurra para frente
        (L: o plano anterior segura o som mais um pouco). É a forma com que a timeline
        trabalha — o vocabulário do editor vira número **aqui**, num lugar só.
        """
        if self.corte_de_som == "antes":
            return -self.som_frames
        if self.corte_de_som == "depois":
            return self.som_frames
        return 0


@dataclass
class CoberturaPedida:
    """Uma arte com alpha (clipe de matte key da bin) por cima da imagem.

    ⭐ Ancorada num CORTE, e não num frame da sequência: o modelo sabe "a cartela entra sobre
    o corte 3", e somar durações de cabeça para achar o frame é a conta que já pôs o
    timestamp de um take em outro.
    """

    arte: str
    sobre_o_corte: int
    deslocamento_frames: int = 0
    duracao_frames: int | None = None
    inicio_na_arte: int = 0
    trilha: int = 2
    porque: str = ""
    confianca: str = ""
    fonte: str = ""


@dataclass
class Plano:
    bin: str
    nome: str
    cortes: list[Corte] = field(default_factory=list)
    coberturas: list[CoberturaPedida] = field(default_factory=list)

    @property
    def duracao_frames(self) -> int:
        return sum(c.duracao_frames for c in self.cortes)

    def inicio_do_corte(self, numero: int) -> int:
        """Onde o corte `numero` (a partir de 1) começa na sequência, em frames."""
        return sum(c.duracao_frames for c in self.cortes[:numero - 1])


def _inteiro(valor, onde: str, campo: str) -> int:
    """Aceita `3` e `"3"`, recusa `3.5` e `"três"`.

    ⚠️ O modelo manda número como texto com alguma frequência, e recusar isso seria
    rigor sem ganho. Já um FRACIONÁRIO é sintoma de unidade errada — segundos onde se
    esperava frames —, e aceitar arredondando esconderia o engano.
    """
    if isinstance(valor, bool) or valor is None:
        raise PlanoInvalido(f"{onde}: {campo} não é um número ({valor!r})")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        if valor != int(valor):
            raise PlanoInvalido(
                f"{onde}: {campo} veio fracionário ({valor}). Frames são inteiros — "
                f"isto costuma ser segundo no lugar de frame."
            )
        return int(valor)
    try:
        return int(str(valor).strip())
    except ValueError:
        raise PlanoInvalido(f"{onde}: {campo} não é um número ({valor!r})") from None


def _validar_corte(bruto: dict, posicao: int) -> Corte:
    onde = f"corte {posicao}"
    if not isinstance(bruto, dict):
        raise PlanoInvalido(f"{onde}: esperava um objeto, veio {type(bruto).__name__}")

    take = str(bruto.get("take") or "").strip()
    if not take:
        raise PlanoInvalido(f"{onde}: sem take — todo corte precisa dizer de onde sai")
    onde = f"corte {posicao} ({take})"

    duracao = _inteiro(bruto.get("duracao_frames"), onde, "duracao_frames")
    if duracao < DURACAO_MINIMA:
        raise PlanoInvalido(
            f"{onde}: duração de {duracao} frame(s). Menos de {DURACAO_MINIMA} não é "
            f"corte — confira se a unidade é frame, e não segundo."
        )

    inicio = _inteiro(bruto.get("inicio_no_take", 0), onde, "inicio_no_take")
    if inicio < 0:
        raise PlanoInvalido(f"{onde}: inicio_no_take negativo ({inicio})")

    # ⛔ Procedência: item sem ela é bug, não item — e por isso o plano inteiro cai.
    confianca = str(bruto.get("confianca") or "").strip()
    fonte = str(bruto.get("fonte") or "").strip()
    if not confianca or not fonte:
        raise PlanoInvalido(
            f"{onde}: item sem procedência. Todo corte precisa de `confianca` "
            f"({'/'.join(CONFIANCAS)}) e `fonte` ({'/'.join(FONTES)})."
        )
    if confianca not in CONFIANCAS:
        raise PlanoInvalido(
            f"{onde}: confiança {confianca!r} fora do vocabulário. Use uma de: "
            f"{', '.join(CONFIANCAS)}"
        )
    if fonte not in FONTES:
        raise PlanoInvalido(
            f"{onde}: fonte {fonte!r} fora do vocabulário. Use uma de: {', '.join(FONTES)}"
        )

    porque = str(bruto.get("porque") or "").strip()
    if not porque:
        # ⭐ O `porque` não é enfeite: o editor aprova corte a corte, e `hipotese/heuristica`
        #    diz o GRAU da incerteza, não o MOTIVO da escolha. Foi lendo o motivo — "o take
        #    foi abortado, tem um homem gritando" — que a escolha certa apareceu na fase 5b.
        raise PlanoInvalido(
            f"{onde}: sem `porque`. O editor aprova corte a corte e precisa saber por que "
            f"este take, e não outro."
        )

    # ⛔⛔ Corte em L/J fica com o EDITOR (autor, 2026-11-06 e 2026-11-07, em todos os NLEs): "existe uma
    #    subjetividade nessa escolha que é melhor ficar com o editor". O produto entrega o corte seco; quem
    #    decide onde o som troca é quem monta. A maquinaria de L/J (o `desloca`, a timeline do Avid) fica de
    #    pé e sem caminho de entrada — voltar atrás é tirar esta recusa.
    corte_de_som = str(bruto.get("corte_de_som") or "junto").strip().lower()
    som_frames = _inteiro(bruto.get("som_frames", 0), onde, "som_frames")
    if (corte_de_som != "junto" or som_frames) and not getattr(_agente_editor, "ativo", False):
        raise PlanoInvalido(
            f"{onde}: corte em L/J (corte_de_som {corte_de_som!r}, som_frames={som_frames}) não é feito "
            f"pelo Ciclo Assist — a escolha de onde o som troca fica com o editor. Mande o corte seco "
            f"(sem corte_de_som nem som_frames) e diga ao editor onde você sugere o L/J, se sugerir."
        )

    medida = bruto.get("medida")
    if medida is not None:
        try:
            medida = float(medida)
        except (TypeError, ValueError):
            raise PlanoInvalido(f"{onde}: medida não é um número ({medida!r})") from None

    return Corte(
        take=take,
        duracao_frames=duracao,
        inicio_no_take=inicio,
        fala=(str(bruto.get("fala")).strip() or None) if bruto.get("fala") else None,
        confianca=confianca,
        fonte=fonte,
        medida=medida,
        porque=porque,
        corte_de_som=corte_de_som,
        som_frames=som_frames,
    )


def validar(bruto: dict) -> Plano:
    """Um plano cru → `Plano`, ou `PlanoInvalido` dizendo onde e o quê."""
    if not isinstance(bruto, dict):
        raise PlanoInvalido(f"o plano precisa ser um objeto, veio {type(bruto).__name__}")

    bin_ = str(bruto.get("bin") or "").strip()
    if not bin_:
        raise PlanoInvalido("plano sem `bin` — não sei de onde vêm os takes")

    nome = str(bruto.get("nome") or "").strip()
    if not nome:
        raise PlanoInvalido("plano sem `nome` — a sequência precisa de um na bin do editor")
    # O nome vira nome de mob e aparece na bin; barra e dois-pontos confundem o Avid e
    # quem lê. Recusar é melhor que sanear em silêncio, porque o editor pediu um nome.
    if any(c in nome for c in '\\/:*?"<>|'):
        raise PlanoInvalido(f"nome de sequência com caractere proibido: {nome!r}")

    cortes_brutos = bruto.get("cortes")
    if not isinstance(cortes_brutos, list) or not cortes_brutos:
        raise PlanoInvalido(
            "plano sem cortes — uma sequência vazia é item morto na bin do editor"
        )

    cortes = [_validar_corte(c, i + 1) for i, c in enumerate(cortes_brutos)]
    _validar_o_som_entre_cortes(cortes)
    plano = Plano(bin=bin_, nome=nome, cortes=cortes)
    coberturas = bruto.get("coberturas") or []
    if not isinstance(coberturas, list):
        raise PlanoInvalido("coberturas precisa ser uma lista")
    plano.coberturas = [_validar_cobertura(c, i + 1, plano) for i, c in enumerate(coberturas)]
    return plano


def _validar_cobertura(bruto, posicao: int, plano: Plano) -> CoberturaPedida:
    onde = f"cobertura {posicao}"
    if not isinstance(bruto, dict):
        raise PlanoInvalido(f"{onde}: esperava um objeto, veio {type(bruto).__name__}")
    arte = str(bruto.get("arte") or "").strip()
    if not arte:
        raise PlanoInvalido(f"{onde}: sem arte — diga o clipe de matte key da bin")
    onde = f"cobertura {posicao} ({arte})"
    corte = _inteiro(bruto.get("sobre_o_corte"), onde, "sobre_o_corte")
    if not 1 <= corte <= len(plano.cortes):
        raise PlanoInvalido(f"{onde}: sobre_o_corte={corte}, e o plano tem os cortes 1 a "
                            f"{len(plano.cortes)}")
    deslocamento = _inteiro(bruto.get("deslocamento_frames", 0), onde, "deslocamento_frames")
    if deslocamento < 0:
        raise PlanoInvalido(f"{onde}: deslocamento_frames negativo ({deslocamento})")
    if plano.inicio_do_corte(corte) + deslocamento >= plano.duracao_frames:
        raise PlanoInvalido(f"{onde}: começaria depois do fim da sequência")
    duracao = bruto.get("duracao_frames")
    if duracao is not None:
        duracao = _inteiro(duracao, onde, "duracao_frames")
        if duracao < DURACAO_MINIMA:
            raise PlanoInvalido(f"{onde}: duração de {duracao} frame(s)")
    inicio = _inteiro(bruto.get("inicio_na_arte", 0), onde, "inicio_na_arte")
    if inicio < 0:
        raise PlanoInvalido(f"{onde}: inicio_na_arte negativo ({inicio})")
    trilha_bruta = str(bruto.get("trilha") or "V2").strip().upper().lstrip("V")
    trilha = _inteiro(trilha_bruta, onde, "trilha")
    if trilha < 2:
        raise PlanoInvalido(f"{onde}: a V1 é da imagem dos cortes; a arte vai na V2 ou acima")
    confianca = str(bruto.get("confianca") or "").strip()
    fonte = str(bruto.get("fonte") or "").strip()
    if confianca not in CONFIANCAS or fonte not in FONTES:
        raise PlanoInvalido(f"{onde}: item sem procedência válida — confianca "
                            f"({'/'.join(CONFIANCAS)}) e fonte ({'/'.join(FONTES)})")
    porque = str(bruto.get("porque") or "").strip()
    if not porque:
        raise PlanoInvalido(f"{onde}: sem `porque` — o editor precisa saber por que a arte "
                            f"entra ali (a linha do roteiro, por exemplo)")
    return CoberturaPedida(arte, corte, deslocamento, duracao, inicio, trilha, porque,
                           confianca, fonte)


def _validar_o_som_entre_cortes(cortes: list[Corte]) -> None:
    """O corte em L/J é uma TRANSIÇÃO: ele só existe entre dois planos.

    ⭐ Cada corte carrega o deslocamento do som **no começo dele**, e a duração de som
    sai disso por telescópio:

    ```
    duração do som do corte i = duração da imagem - desloca(i) + desloca(i+1)
    ```

    Os deslocamentos se cancelam ao somar, então a trilha de som fecha exatamente o mesmo
    comprimento da de imagem — sem buraco e sem sobra — desde que o primeiro corte não
    desloque nada. É o que este validador garante.
    """
    if cortes and cortes[0].desloca:
        raise PlanoInvalido(
            f"corte 1 ({cortes[0].take}): corte_de_som {cortes[0].corte_de_som!r} no "
            f"PRIMEIRO corte. L e J são transições entre dois planos — não há plano "
            f"anterior de onde o som venha, ou para onde ele fique."
        )

    # ⚠️⚠️ **Duas passadas, e a ordem é a mensagem.** Numa passada só, um avanço grande
    #    demais estoura primeiro no plano VIZINHO — "não sobra som nenhum neste plano" —
    #    e manda o modelo consertar o corte errado. A causa está sempre no corte que
    #    declarou o avanço, então ela é conferida antes de qualquer consequência.
    for i, c in enumerate(cortes):
        onde = f"corte {i + 1} ({c.take})"
        d = c.desloca
        if not d:
            continue

        # ⛔ O som não pode comer o plano inteiro: um avanço maior que o plano vizinho
        #    faria a fala atravessar DOIS cortes, e aí o que sai na timeline não é o que
        #    o editor leu no cartão.
        if i and abs(d) >= cortes[i - 1].duracao_frames:
            raise PlanoInvalido(
                f"{onde}: o som se desloca {abs(d)} frames, mas o plano anterior tem "
                f"só {cortes[i - 1].duracao_frames}. O avanço tem de caber no vizinho."
            )
        if abs(d) >= c.duracao_frames:
            raise PlanoInvalido(
                f"{onde}: o som se desloca {abs(d)} frames num plano de "
                f"{c.duracao_frames}. O avanço tem de caber no próprio plano."
            )

        # ⚠️ Pedir som antes do frame 0 do take é pedir mídia que não existe: o Avid
        #    aceita e mostra silêncio, sem erro nenhum.
        if c.inicio_no_take + d < 0:
            raise PlanoInvalido(
                f"{onde}: o som precisaria começar {abs(c.inicio_no_take + d)} frames "
                f"ANTES do início do take. Comece o corte mais para a frente, ou diminua "
                f"o avanço do som."
            )

    # A conta final, com os dois lados já conferidos. Chegar aqui com sobra negativa é
    # avanço somado dos dois vizinhos — legítimo de checar, e raro de ver.
    for i, c in enumerate(cortes):
        proximo = cortes[i + 1].desloca if i + 1 < len(cortes) else 0
        if c.duracao_frames - c.desloca + proximo < 1:
            raise PlanoInvalido(
                f"corte {i + 1} ({c.take}): com os avanços de som dos dois lados, não "
                f"sobra som nenhum neste plano."
            )


def resumir(plano: Plano, fps: float) -> str:
    """O plano em uma linha por corte — é o que o editor lê no portão."""
    linhas = [f"{plano.nome} — {len(plano.cortes)} cortes, "
              f"{plano.duracao_frames / fps:.1f}s"]
    for i, c in enumerate(plano.cortes, 1):
        trecho = f"{c.inicio_no_take / fps:.1f}s" if c.inicio_no_take else "do início"
        # ⭐ O L/J entra no resumo porque ele muda o que o editor VAI VER, e não aparece
        #   em nenhum outro número da linha: dois planos com a mesma duração de imagem
        #   cortam diferente conforme o som troque antes, junto ou depois.
        som = ""
        if c.corte_de_som == "antes":
            som = f", som {c.som_frames}f antes (J)"
        elif c.corte_de_som == "depois":
            som = f", som segura {c.som_frames}f (L)"
        linhas.append(
            f"{i}. {c.take} ({trecho}, {c.duracao_frames / fps:.1f}s{som}) "
            f"[{c.confianca}/{c.fonte}] {c.porque}"
        )
    for cob in plano.coberturas:
        dur = f", {cob.duracao_frames / fps:.1f}s" if cob.duracao_frames else ""
        linhas.append(f"V{cob.trilha}: {cob.arte} sobre o corte {cob.sobre_o_corte}"
                      f"{f' +{cob.deslocamento_frames}f' if cob.deslocamento_frames else ''}"
                      f"{dur} [{cob.confianca}/{cob.fonte}] {cob.porque}")
    return "\n".join(linhas)
