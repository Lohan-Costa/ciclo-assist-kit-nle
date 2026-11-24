"""Os subclipes do PREMIERE, na mesma forma que a busca já consome do Avid.

⭐⭐ **Preferir subclipes é ORDEM, não exclusão** (pedido do editor, 2026-09-21): é com o
recorte que ele monta, e o bruto é a saída quando não há recorte. A regra é do produto, não
do Avid — então ela vale nos dois editores, e o que muda é só de onde sai a janela.

| | Avid (`avid/subclipes.py`) | Premiere (aqui) |
|---|---|---|
| o que é um recorte | mob de `usage_code` de subclipe na `.avb` | item com `Column.Intrinsic.SubclipStart` |
| a janela | o `SourceClip` de cada master | `SubclipStart`/`SubclipDuration` menos o TC do ARQUIVO |
| em que timeline é usado | os ramos escolhidos do `Selector` | `track.clips` de cada sequência |
| o que invalida o índice | nome, mtime e tamanho de cada bin | o `.prproj` mudou, ou o prazo venceu |

⛔⛔ **O `getInPoint()` do Premiere devolve o MASTER INTEIRO** (banco,
`plugins/premiere-cep/subclipe-e-merged-clip.md`). Quem o usar como janela põe todo
subclipe cobrindo a diária inteira — e aí toda fala "cabe" em todo recorte, que é
exatamente o degenerado que o checker do mapa de corte já pagou uma vez para aprender.

⚠️⚠️ **A janela é POR MASTER, e isto é a armadilha herdada do Avid.** Um merged clip mistura
dois masters com in-points diferentes (medido no Avid: imagem em 0, som em 214 frames).
Conferir uma fala — que está no tempo do master de SOM — contra o offset da imagem
dessincroniza em segundos, calado. Não existe aqui "o offset do take".

⚠️ **NÃO MEDIDO na GUI do Premiere** (2026-09-21): quanto custa `getProjectMetadata()` item
a item num projeto grande. O host devolve `olhados` justamente para o custo aparecer no log
em vez de virar "a aba Busca ficou lenta".
"""

from __future__ import annotations

import logging
import threading
import time
from fractions import Fraction
from pathlib import Path

from ...avid.subclipes import Janela, Recorte
from ...midia import identidade as _identidade
from . import ponte

log = logging.getLogger("cicloassist.nle.premiere.recortes")

#: Por quanto tempo o índice é reaproveitado sem perguntar de novo ao Premiere.
#:
#: ⛔ Aqui NÃO há assinatura de arquivo que sirva sozinha: criar um subclipe não grava o
#: `.prproj` (o editor pode passar a tarde sem salvar), então um índice preso ao mtime
#: ficaria velho justamente enquanto ele trabalha. O prazo é a rede — curto o bastante para
#: o subclipe de agora aparecer na busca de daqui a pouco, longo o bastante para uma rajada
#: de buscas não reler o projeto inteiro.
VALIDADE_S = 120.0

#: Espécies que o Premiere entrega e que contam como recorte. ⚠️ `multicam` entra na ORDEM
#: desde já; `take.resolver` ainda não o monta, então ele vale como posição, não como janela.
ESPECIES = ("clipe", "merged", "multicam")


def _taxa(fps) -> Fraction:
    """A taxa do item → `Fraction`, ou `Fraction(0)` quando não se sabe.

    ⛔ **Zero, nunca um padrão.** Chutar 25 fps erraria TODO material 23,976 — que é o
    acervo inteiro desta casa — e o erro sairia como uma janela de subclipe deslocada,
    calada. Sem taxa o recorte entra na ordem sem janela, e a fala não é conferida contra
    ele: melhor um subclipe sem janela que uma janela errada.

    ⚠️ O ffprobe devolve a taxa como fração em texto (`"24000/1001"`); o Premiere, como
    número. Os dois entram aqui.
    """
    texto = str(fps or "").strip()
    if not texto:
        return Fraction(0)
    try:
        valor = Fraction(texto)
    except (ValueError, ZeroDivisionError):
        try:
            valor = Fraction(float(texto))
        except (TypeError, ValueError):
            return Fraction(0)
    return valor.limit_denominator(100000) if valor > 0 else Fraction(0)


_guardado: dict[str, tuple[float, dict[str, list[Recorte]]]] = {}
#: ⛔⛔ Uma vaga de build por projeto — a MESMA trava do Avid, e pelo mesmo motivo medido:
#: a aba aquece o índice e a busca o pede ao mesmo tempo. Lá isso virou quatro builds em um
#: minuto e uma busca que nunca voltava; aqui cada build é uma ida à ponte que atravessa o
#: painel, então dois em paralelo disputam o ExtendScript, que roda UM pedido por vez.
_construindo: dict[str, threading.Event] = {}
_trava = threading.Lock()


def indice(projeto: str, esperar: float = 0.0,
           recarregar: bool = False) -> dict[str, list[Recorte]]:
    """`{chave do master: [Recorte, …]}`. Mesmo contrato do `avid/subclipes.indice`.

    ⛔ **Não bloqueia por padrão.** Quem chega com o índice velho recebe o velho na hora e
    deixa UM build correndo no fundo; `esperar > 0` é o aquecimento da aba, onde ninguém
    está olhando o relógio. ⚠️ Nunca levanta: sem índice a busca responde por master.
    """
    nome = str(projeto or "")
    if not nome:
        return {}

    with _trava:
        anterior = _guardado.get(nome)
        if anterior is not None and not recarregar and time.time() - anterior[0] < VALIDADE_S:
            return anterior[1]
        pronto = _construindo.get(nome)
        eu_construo = pronto is None
        if eu_construo:
            pronto = _construindo[nome] = threading.Event()

    if eu_construo:
        threading.Thread(target=_construir, args=(nome, pronto),
                         name=f"recortes-ppro-{Path(nome).stem}", daemon=True).start()

    if esperar > 0:
        pronto.wait(timeout=esperar)

    with _trava:
        guardado = _guardado.get(nome)
    # ⚠️ O índice VELHO é melhor que nenhum: ele erra só no que mudou.
    return guardado[1] if guardado else {}


def _construir(nome: str, pronto: threading.Event) -> None:
    try:
        montado = _montar()
        with _trava:
            _guardado[nome] = (time.time(), montado)
    except Exception:  # noqa: BLE001 — build que falha não derruba o serviço
        log.warning("não consegui indexar os recortes de %s", Path(nome).name, exc_info=True)
    finally:
        # ⛔ No `finally`: vaga não devolvida trava o índice para sempre, e o sintoma é
        #   "os subclipes nunca ficam prontos", sem erro nenhum.
        with _trava:
            _construindo.pop(nome, None)
        pronto.set()


def esta_pronto(projeto: str) -> bool:
    with _trava:
        return str(projeto or "") in _guardado


def esquecer() -> None:
    with _trava:
        _guardado.clear()
        _construindo.clear()


def _montar() -> dict[str, list[Recorte]]:
    """Pergunta o projeto ao Premiere e traduz cada item em `Recorte`."""
    comecou = time.time()
    resposta = ponte.chamar("cicloRecortes", prazo=120) or {}
    itens = resposta.get("itens") or []
    por_master: dict[str, list[Recorte]] = {}
    sem_janela = 0

    for d in itens:
        recorte = _do_item(d)
        if recorte is None:
            continue
        if not recorte.janelas:
            sem_janela += 1
        for chave in recorte.janelas or ():
            por_master.setdefault(chave, []).append(recorte)

    log.info("recortes do Premiere: %d de %d itens olhados, %d master(s), %d sem janela, %.1f s",
             len(itens), int(resposta.get("olhados") or 0), len(por_master), sem_janela,
             time.time() - comecou)
    return por_master


def _do_item(d: dict) -> Recorte | None:
    """Um item do `cicloRecortes` → `Recorte`, ou `None` se não der para situá-lo."""
    arquivo = str(d.get("arquivo") or "")
    if not arquivo or not Path(arquivo).is_file():
        return None
    try:
        sonda = _identidade.sondar(arquivo)
        # ⭐ A chave JÁ CONHECIDA, nunca a impressão medida na hora: um índice de 150
        #   recortes pagaria 150 decodificações de um minuto cada. E não custa acerto —
        #   arquivo cuja impressão ninguém calculou nunca foi analisado, logo não está no
        #   cache e não entra em busca nenhuma (a mesma conta do `escopo_agora`).
        chave = _identidade.chave_conhecida(arquivo)
    except _identidade.IdentidadeErro:
        log.debug("não consegui identificar %s", arquivo, exc_info=True)
        return None
    if not chave:
        return None

    taxa = _taxa(d.get("fps")) or _taxa(sonda.get("fps"))
    duracao_s = 0.0
    janelas: dict[str, Janela] = {}
    from . import recorte_do_subclipe  # tardio: o pacote importa este módulo

    if taxa:
        pedaco = recorte_do_subclipe(str(d.get("metadados") or ""),
                                     str(sonda.get("tc") or ""), taxa)
        if pedaco is not None:
            inicio, duracao = pedaco
            duracao_s = duracao / float(taxa)
            janelas[chave] = Janela(inicio_s=inicio / float(taxa),
                                    fim_s=(inicio + duracao) / float(taxa))

    return Recorte(
        nome=str(d.get("nome") or ""),
        bin=str(d.get("bin") or ""),
        especie="subclipe" if d.get("especie") == "clipe" else str(d.get("especie") or ""),
        duracao_s=duracao_s,
        fps_aprox=float(taxa) if taxa else 0.0,
        # ⭐ O id do item, que é o que `cicloCarregarNoSource` resolve — o equivalente do
        #   MobID do subclipe no Avid, e o que põe o RECORTE no Source em vez da diária.
        mob_id=str(d.get("id") or ""),
        timelines=[str(t) for t in (d.get("timelines") or [])],
        janelas=janelas,
    )
