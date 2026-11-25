"""O índice de subclipes do projeto aberto: que pedaço de que master cada um recorta.

⭐⭐ **Pedido do editor (2026-09-21), vendo a aba Busca responder com masters:** *"em um
trabalho real, os editores trabalham com subclipe ou groupclipe, recorrendo ao bruto só
quando não há esses tipos de arquivos"*. A busca só sabia de masters — o cache é endereçado
pelo UMID do master, e **subclipe não tem entrada nenhuma nele**. Quem sabe de subclipe é a
BIN, e é ela que este módulo lê.

## Medido no projeto do editor (`_ASSIST ANTERIOR`, 2026-09-21)

| | |
|---|---|
| masterclipes visíveis | 1.093 |
| **subclipes** | **150**, cobrindo **108 masters** distintos |
| group clips | 0 |
| listar os 150 (varrer as 37 bins) | **0,4 s** |
| resolver os 150 (master + recorte) | **3,1 s**, 150 de 150 |

⇒ 3,5 s é caro para uma busca e barato para uma sessão: o índice fica guardado e só se
refaz quando uma bin muda. ⭐ A invalidação é pela **assinatura das bins** (nome, mtime,
tamanho), que custa **0 ms** para as 37 — e não por relógio. Relógio erra nos dois sentidos:
refaz o que não mudou e serve o que mudou.

## ⚠️⚠️ O in-point da IMAGEM e o do SOM são diferentes, e é aqui que se erra

Um subclipe sincronizado mistura dois masters, e eles entram em pontos diferentes — medido
no `C04_P01-T002`: **imagem em 0, som em 214 frames**. Testar uma fala (que está no tempo do
master de SOM) contra o offset da imagem dessincroniza em 9 s, em silêncio.

⇒ A janela é guardada **por master**, nunca uma por subclipe. Não existe lugar aqui de onde
alguém possa pegar "o offset do take" — é a mesma regra de `avid/take.py`, e ela existe
porque o modo de falha é mudo.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import avb

from . import bins as _bins
from . import take as _take

log = logging.getLogger("cicloassist.avid.subclipes")

#: O que conta como "o que o editor monta com". ⚠️ `grupo` entra na ORDEM desde já, mas
#: `take.resolver` ainda o recusa (`take.RECUSAS`) — então ele não tem janela, só posição.
ESPECIES_PREFERIDAS = ("subclipe", "grupo")


@dataclass(frozen=True)
class Janela:
    """O pedaço de UM master que um recorte cobre, em segundos do master."""

    inicio_s: float
    fim_s: float

    def cobre(self, quando_s: float | None) -> bool:
        """⚠️ `None` não é "cobre": é "não dá para saber", e quem chama decide o que fazer."""
        if quando_s is None:
            return False
        return self.inicio_s <= float(quando_s) <= self.fim_s


@dataclass
class Recorte:
    """Um subclipe (ou group clip) da bin, com o que ele recorta de cada master."""

    nome: str
    #: A bin, relativa à pasta do projeto — é o que o editor lê e o que as ferramentas pedem.
    bin: str
    especie: str
    duracao_s: float
    fps_aprox: float
    #: ⭐ O MobID do próprio recorte. É por ele que o Source carrega o SUBCLIPE em vez do
    #: master — medido em 2026-09-21: `LoadMobsIntoViewer` aceita o mob de um subclipe.
    mob_id: str = ""
    #: ⭐ Em que timelines VISÍVEIS do projeto este recorte é usado. Pedido do editor.
    timelines: list[str] = field(default_factory=list)
    #: ⚠️ Uma janela POR MASTER. Ver o cabeçalho: imagem e som entram em pontos diferentes.
    janelas: dict[str, Janela] = field(default_factory=dict)

    def cobre(self, chave_do_master: str, quando_s: float | None) -> bool:
        janela = self.janelas.get(chave_do_master)
        return janela is not None and janela.cobre(quando_s)

    def como_dicionario(self) -> dict[str, Any]:
        return {"nome": self.nome, "bin": self.bin, "especie": self.especie,
                "duracao_s": round(self.duracao_s, 2), "timelines": list(self.timelines)}


def _assinatura(pasta: Path) -> tuple:
    """Nome, mtime e tamanho de cada bin — o que diz se o índice ainda vale. 0 ms para 37."""
    marcas = []
    for caminho in _bins.bins_do_projeto(pasta):
        try:
            st = caminho.stat()
            marcas.append((caminho.name, st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    return tuple(sorted(marcas))


_guardado: dict[str, tuple[tuple, dict[str, list[Recorte]]]] = {}
#: Projetos com um build EM ANDAMENTO. ⛔⛔ Sem isto, cada chamada começa o seu: na tela do
#: editor a aba dispara `/busca/recortes` e a busca dispara `/busca/frase`, e os dois
#: entraram em `_montar` ao mesmo tempo. Medido em 2026-09-21, no log dele: **quatro builds
#: em um minuto**, brigando pelo disco — cada um passou de 3,6 s para mais de 30 s, e a
#: busca ficou "procurando…" para sempre.
_construindo: dict[str, threading.Event] = {}
_trava = threading.Lock()


def indice(pasta_do_projeto: Path | str, esperar: float = 0.0,
           recarregar: bool = False) -> dict[str, list[Recorte]]:
    """`{chave do master: [Recorte, …]}` — que recortes existem sobre cada master.

    ⛔⛔ **NÃO BLOQUEIA por padrão, e é o conserto de 2026-09-21.** A versão anterior
    construía dentro da chamada: com a aba e a busca pedindo ao mesmo tempo, dois builds
    corriam juntos, cada um ficava dez vezes mais lento, e o seguinte começava por cima. A
    busca do editor nunca voltava.

    ⇒ Agora: quem chega com o índice velho **recebe o velho na hora** e deixa UM build
    correndo no fundo. `esperar > 0` dá um prazo para esse build — é o que a rota de
    aquecimento usa, porque lá o editor não está olhando o relógio.

    ⭐ Guardado por projeto e invalidado pela assinatura das bins: salvar uma bin no Media
    Composer refaz o índice, e não salvar nada não custa nada.

    ⚠️ Nunca levanta. Projeto inacessível, bin corrompida ou pyavb reclamando viram
    "não há recortes" — a busca continua respondendo por master, que é o comportamento de
    antes da preferência.
    """
    pasta = Path(pasta_do_projeto)
    nome = str(pasta)
    try:
        agora = _assinatura(pasta)
    except Exception:  # noqa: BLE001
        log.debug("não consegui assinar as bins de %s", pasta, exc_info=True)
        return {}

    with _trava:
        anterior = _guardado.get(nome)
        if anterior is not None and anterior[0] == agora and not recarregar:
            return anterior[1]
        # ⭐ UM build por projeto. Quem chega depois espera este, nunca começa outro.
        pronto = _construindo.get(nome)
        eu_construo = pronto is None
        if eu_construo:
            pronto = _construindo[nome] = threading.Event()

    if eu_construo:
        threading.Thread(target=_construir, args=(pasta, nome, agora, pronto),
                         name=f"recortes-{pasta.name}", daemon=True).start()

    if esperar > 0:
        pronto.wait(timeout=esperar)

    with _trava:
        guardado = _guardado.get(nome)
    # ⚠️ O índice VELHO é melhor que nenhum: ele erra só no que mudou desde a última
    #   varredura, e o alternativo é a busca perder a preferência inteira.
    return guardado[1] if guardado else {}


def _construir(pasta: Path, nome: str, assinatura: tuple,
               pronto: threading.Event) -> None:
    """O build, numa thread só, com a vaga devolvida em QUALQUER saída."""
    try:
        montado = _montar(pasta)
        with _trava:
            _guardado[nome] = (assinatura, montado)
    except Exception:  # noqa: BLE001 — build que falha não derruba o serviço
        log.warning("não consegui indexar os recortes de %s", pasta.name, exc_info=True)
    finally:
        # ⛔ No `finally`: uma vaga não devolvida trava o índice para sempre, e o sintoma
        #   é "os subclipes nunca ficam prontos" sem erro nenhum.
        with _trava:
            _construindo.pop(nome, None)
        pronto.set()


def esta_pronto(pasta_do_projeto: Path | str) -> bool:
    """Há índice servível para este projeto? (Mesmo que velho.)"""
    with _trava:
        return str(Path(pasta_do_projeto)) in _guardado


def esquecer() -> None:
    """Descarta o índice guardado. Para os testes e para a troca de projeto."""
    global _timelines_por_mob
    with _trava:
        _guardado.clear()
        _construindo.clear()
        _timelines_por_mob = {}


def _montar(pasta: Path) -> dict[str, list[Recorte]]:
    por_master: dict[str, list[Recorte]] = {}
    # ⭐ O que as timelines usam sai da MESMA varredura de bins: são 80 sequências no
    #   projeto do editor e ~1 s para todas (medido), dentro de uma passada que já acontece.
    usos: dict[str, list[str]] = {}
    tudo: list[tuple[Path, str, str, str, str]] = []

    for caminho in _bins.bins_do_projeto(pasta):
        try:
            relativa = str(caminho.relative_to(pasta))
        except ValueError:
            relativa = caminho.name
        try:
            with avb.open(str(caminho)) as f:
                for hexa, nomes in _timelines_da_bin(f, relativa).items():
                    usos.setdefault(hexa, []).extend(nomes)
                for mob_id, nome, esp in _recortes_visiveis(f):
                    tudo.append((caminho, relativa, mob_id, nome, esp))
        except Exception:  # noqa: BLE001 — bin ilegível não derruba o índice
            log.debug("não consegui ler %s", caminho.name, exc_info=True)

    for caminho, relativa, mob_id, nome, esp in tudo:
        recorte = _resolver(caminho, relativa, mob_id, nome, esp)
        if recorte is None:
            continue
        recorte.timelines = sorted(set(usos.get(_take.hex_do_mob(mob_id)) or []))
        for chave in recorte.janelas:
            por_master.setdefault(chave, []).append(recorte)

    # ⭐ O master também pode ser usado direto numa timeline, sem subclipe no meio.
    global _timelines_por_mob
    _timelines_por_mob = {h: sorted(set(n)) for h, n in usos.items()}
    log.info("índice de recortes: %d master(s) cobertos, %d mob(s) em timeline, em %s",
             len(por_master), len(usos), pasta.name)
    return por_master


#: ⭐ `{hex do mob: [timeline]}` do último índice montado — serve ao MASTER, que não tem
#: `Recorte` para carregar a etiqueta.
_timelines_por_mob: dict[str, list[str]] = {}


def timelines_de(chave_ou_mob: str) -> list[str]:
    """Em que timelines do projeto este mob aparece. `[]` quando em nenhuma."""
    try:
        return list(_timelines_por_mob.get(_take.hex_do_mob(chave_ou_mob)) or [])
    except Exception:  # noqa: BLE001
        return []


def _mobs_usados(componente, fundo: set[str], prof: int = 0) -> None:
    """Os mob_ids que este pedaço de timeline referencia, descendo em efeito e transição.

    ⚠️ Recursivo com teto: um `TrackEffect` guarda trilhas dentro, e uma transição guarda
    os dois lados. Sem descer, um clipe usado só dentro de um efeito ficaria de fora; sem
    teto, uma estrutura cíclica travaria a varredura.
    """
    if prof > 8 or componente is None:
        return
    mob_id = getattr(componente, "mob_id", None)
    if mob_id is not None:
        fundo.add(_take.hex_do_mob(mob_id))

    # ⛔⛔ **`Selector`: só o ramo ESCOLHIDO**, e é literalmente o pedido do editor —
    #    *"conteúdo de timeline só deve entrar o que de fato foi usado na timeline"*.
    #    Um `Selector` guarda o que toca e as ALTERNATIVAS que não tocam (o segmento que
    #    ele desligou, a versão anterior de um trecho). MEDIDO em 2026-09-21 na
    #    `relink.avb`: descendo nos dois ramos, a timeline "usava" 44 subclipes; seguindo
    #    só o escolhido, **39** — e os 5 a mais estavam todos dentro de `Selector`, um
    #    deles com `selected = 0` apontando um **`Filler`** (ou seja: nada toca ali).
    if type(componente).__name__ == "Selector":
        ramos = _ramos(componente)
        escolhido = getattr(componente, "selected", 0)
        try:
            escolhido = int(escolhido)
        except (TypeError, ValueError):
            escolhido = 0
        if 0 <= escolhido < len(ramos):
            _mobs_usados(ramos[escolhido], fundo, prof + 1)
        return

    for filho in _ramos(componente):
        _mobs_usados(filho, fundo, prof + 1)


def _ramos(componente) -> list:
    """Os filhos de um componente, venham em `components` ou em `tracks`."""
    saida = []
    for atributo in ("components", "tracks"):
        filhos = getattr(componente, atributo, None)
        if isinstance(filhos, (list, tuple)):
            saida.extend(getattr(f, "component", f) for f in filhos)
    return saida


def _timelines_da_bin(f, relativa: str) -> dict[str, list[str]]:
    """`{hex do mob: [nome da timeline]}` — o que cada sequência VISÍVEL desta bin usa.

    ⭐⭐ **Pedido do editor (2026-09-21):** *"é importante também ter uma tag dizendo o nome
    da timeline que foi encontrado"*. Ele viu a busca devolver subclipes de uma bin de
    rascunho (`untitled folder/relink.avb`) e quis distinguir o que está montado do que
    está largado.

    ⚠️ E a distinção é real, não suposta: **MEDIDO em 2026-09-21**, aquela bin tem 44
    subclipes VISÍVEIS (`user_placed=True`, não ocultos) e a timeline dela usa **9**.

    ⭐ Custa quase nada: 80 sequências no projeto, **~1 s** para ler todas (14 ms cada,
    0 erros) — e esta função corre dentro da varredura de bins que o índice já faz.
    """
    saida: dict[str, list[str]] = {}
    for mob in f.content.mobs:
        if not getattr(mob, "user_placed", True):
            continue
        try:
            if _take.especie(mob) != "sequencia":
                continue
        except Exception:  # noqa: BLE001
            continue
        nome = str(getattr(mob, "name", "") or "").strip()
        if not nome:
            continue
        usados: set[str] = set()
        try:
            _mobs_usados(mob, usados)
        except Exception:  # noqa: BLE001 — sequência ilegível é 1 de N
            log.debug("não li os usos de %s em %s", nome, relativa, exc_info=True)
            continue
        for hexa in usados:
            saida.setdefault(hexa, []).append(nome)
    return saida


def _recortes_visiveis(f) -> list[tuple[str, str, str]]:
    """`(mob_id, nome, espécie)` dos subclipes e grupos VISÍVEIS da bin.

    ⛔ Só item visível (`user_placed`): a bin de falas leva o fecho OCULTO com os mesmos
    subclipes, e contá-lo faria o mesmo recorte aparecer três vezes (a mesma razão de
    `bins.bins_dos_mobs`).

    ⚠️ Tudo lido dentro do `with`: o pyavb é preguiçoso e um mob guardado para depois dá
    `ValueError: seek of closed file` sem mencionar o `with`.
    """
    achados: list[tuple[str, str, str]] = []
    for mob in f.content.mobs:
        if not getattr(mob, "user_placed", True):
            continue
        try:
            esp = _take.especie(mob)
        except Exception:  # noqa: BLE001 — mob ilegível é 1 de N
            continue
        if esp not in ESPECIES_PREFERIDAS:
            continue
        achados.append((str(mob.mob_id), str(getattr(mob, "name", "") or ""), esp))
    return achados


def _resolver(caminho: Path, relativa: str, mob_id: str, nome: str,
              esp: str) -> Recorte | None:
    """Um recorte com as janelas por master, ou `None` quando não dá para saber.

    ⚠️ Resolve pelo **MobID**, não pelo nome: dois subclipes homônimos na mesma bin não são
    raros (o editor duplica um take e ajusta), e pelo nome o índice apontaria o errado.

    ⚠️ `procurar_arquivos=False` — o índice não precisa saber se a mídia está no disco, e
    procurá-la custaria uma varredura por subclipe.
    """
    try:
        take = _take.resolver(str(caminho), mob_id, procurar_arquivos=False)
    except Exception:  # noqa: BLE001 — group clip é recusado hoje, e isso é esperado
        log.debug("não resolvi o recorte %s de %s", nome, caminho.name, exc_info=True)
        return None

    recorte = Recorte(nome=nome or mob_id[:12], bin=relativa, especie=esp,
                      duracao_s=float(take.duracao_s or 0.0),
                      fps_aprox=float(take.fps_aprox or 0.0), mob_id=mob_id)
    for fonte in (take.imagem, take.som):
        if fonte is None:
            continue
        try:
            chave = _cache_chave(fonte)
        except Exception:  # noqa: BLE001
            continue
        if not chave:
            continue
        inicio = float(getattr(fonte, "inicio_s", 0.0) or 0.0)
        recorte.janelas[chave] = Janela(inicio, inicio + recorte.duracao_s)
    return recorte or None


def _cache_chave(fonte) -> str:
    """A chave de cache do master desta fonte — a mesma que `midia/cache.py` endereça."""
    from ..midia import cache as _cache

    try:
        return _cache.de_umid(str(fonte.chave or fonte.mob_id))
    except _cache.ChaveInvalida:
        return ""
