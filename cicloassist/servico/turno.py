"""Um turno de conversa: a fila de eventos que o painel lê enquanto o modelo responde.

## O caminho, e por que ele tem duas pontas

```
claude -p  ──POST /mcp/<segredo>──→  pedir_confirmacao   (thread A)
                                            │ abre a PENDÊNCIA e responde `deny` na hora
                                            │ empurra o cartão na fila
                                            ▼
painel     ←──SSE de /conversar──────  fila de eventos   (thread B)
   │
   └────────POST /responder────────→  pendências: EXECUTA a ferramenta
```

⚠️ **É por isso que o motor não pode ser consumido como gerador direto pela rota SSE.**
Se fosse, não haveria por onde injetar o cartão de aprovação no meio da resposta — ele
chega de outra thread, disparado pelo subprocesso. O motor roda numa thread e escreve
numa fila; a rota drena a fila. O portão escreve na mesma fila.

## ⭐⭐ O turno acaba; o pedido fica (ADR 0008)

Este módulo **não espera o editor** e não tem relógio nenhum. O portão mostra o cartão,
responde `deny` na hora e o turno termina — a caixa de texto destrava e o editor segue
trabalhando. O cartão vive em `servico/pendencias.py`, sobrevive ao turno, ao recarregar
do painel e ao reinício do serviço, e é o clique dele que executa a ação.

⛔ **Nunca voltar a bloquear aqui.** A versão que bloqueava dava ao editor o prazo do CLI
para responder — medido em 60 s. Quem saísse da mesa perdia o trabalho.

## Um turno por vez, e isso é decisão

O painel é `singleton` e bloqueia a caixa de texto enquanto responde, então na prática só
há um turno. Tornar isso explícito importa: **a chamada de `pedir_confirmacao` não diz de
que turno ela é** (o CLI manda `tool_name`, `input` e `tool_use_id`, e nada mais). Com dois
turnos vivos, um cartão poderia ser desenhado no painel errado — e o editor veria um
pedido que não é da conversa que ele está lendo. Recusar o segundo turno é mais honesto
que adivinhar.
"""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from typing import Any, Iterator

log = logging.getLogger("cicloassist.servico.turno")

#: ⭐ O prazo que o CLI dá para uma chamada de ferramenta, em milissegundos — o valor que
#: `motor/claude.py` põe em `MCP_TOOL_TIMEOUT` no ambiente do subprocesso.
#:
#: ⚠️⚠️ **MEDIDO: o padrão de fábrica é 60 s** (`spikes/portao_espera.py`, 2026-09-10, CLI
#: 2.1.267; com a variável em 20000 ele desistiu em 20,0 s exatos, então ela vale).
#:
#: ⛔ **Isto NÃO é o prazo do editor — o editor não tem prazo** (ADR 0008). O portão
#: responde na hora e a pendência espera o clique para sempre. Este número existe só para
#: as ferramentas que de fato trabalham: `transcrever` passa de um minuto num take de
#: quatro, e com o padrão de fábrica ela morria no meio da frase.
PRAZO_DO_CLI_MS = 600_000  # 10 min — teto para o ASR de um take longo

_FIM = object()  # sentinela que fecha o fluxo SSE


class TurnoOcupado(RuntimeError):
    """Já há um turno em andamento. Ver o docstring do módulo."""


class Turno:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.fila: queue.Queue = queue.Queue()
        self._vivo = True
        #: O que o EDITOR escreveu nesta pergunta — sem o preâmbulo dos arrastos. ⭐ É o que
        #: permite a uma ferramenta conferir o que ele DISSE, e não o que o modelo entendeu
        #: (`abrir_programa`: só abre o programa que o editor nomeou, autor 2026-10-29).
        self.texto_do_editor = ""
        #: "chat" ou "fluxos" (2026-11-03): a pendência aberta neste turno volta para esta conversa.
        self.conversa = "chat"
        #: O que está aberto na janela Fluxos e Agentes, para as ferramentas de propor conferirem o node.
        self.janela: dict[str, Any] | None = None
        #: O `historico.Registro` deste turno, quando é do chat: o cartão de perguntas tem de sobreviver a um Reload.
        self.registro = None

    # ── eventos para o painel ────────────────────────────────────────────────

    def emitir(self, tipo: str, dado: dict[str, Any]) -> None:
        self.fila.put((tipo, dado))

    def mostrar_perguntas(self, cartao: dict[str, Any]) -> None:
        """Um cartão com uma caixa de resposta por pergunta. O envio dele é uma mensagem normal do editor."""
        self.emitir("perguntas", cartao)
        if self.registro is not None:
            self.registro.guardar_perguntas(cartao)

    def encerrar(self) -> None:
        """Fecha o fluxo SSE. E **não mexe nos cartões que estão na tela**.

        ⚠️⚠️ Aqui morava o contrário: o turno acabava e as aprovações pendentes eram
        recusadas em bloco, porque havia threads bloqueadas esperando. Agora o pedido
        sobrevive ao turno de propósito — é justamente o que deixa o editor responder
        amanhã (`servico/pendencias.py`).
        """
        self._vivo = False
        self.fila.put(_FIM)

    def eventos(self) -> Iterator[tuple[str, dict]]:
        """Drena a fila até o fim do turno. É o que a rota SSE consome."""
        while True:
            item = self.fila.get()
            if item is _FIM:
                return
            yield item


# ── o turno ativo ────────────────────────────────────────────────────────────

_atual: Turno | None = None
_trava_global = threading.Lock()


def comecar() -> Turno:
    global _atual
    with _trava_global:
        if _atual is not None and _atual._vivo:
            raise TurnoOcupado("já há uma pergunta em andamento")
        _atual = Turno()
        return _atual


def atual() -> Turno | None:
    return _atual


#: O que o EDITOR escreveu em cada turno DESTA conversa (a da janela, `rotas.CONVERSA_DA_JANELA`).
#: ⭐ Num fluxo de vários turnos o pedido está no primeiro ("abra o Resolve… depois o Media
#: Composer") e os seguintes dizem "pode seguir": a regra "só abre o programa que o editor
#: nomeou" (`abrir_programa`) lê a conversa inteira, não só a pergunta da vez. Esquecido junto
#: com a conversa (Limpar, visita nova).
_da_conversa: list[str] = []


def lembrar_da_conversa(texto: str) -> None:
    if texto:
        _da_conversa.append(texto)


def da_conversa() -> list[str]:
    return list(_da_conversa)


def esquecer_a_conversa() -> None:
    _da_conversa.clear()


def avisar(etapa: str, fracao: float | None = None, detalhe: str = "") -> None:
    """"Está acontecendo isto, e já foi tanto." Some se não houver painel escutando.

    ⭐⭐ **É o que tira o editor do escuro.** Transcrever um take de quatro minutos leva
    mais de um minuto, e durante todo esse tempo o painel dizia apenas o nome da
    ferramenta. Uma tela parada por um minuto e meio parece travada — e quem acha que
    travou fecha e reabre, que é a pior coisa a fazer no meio de um turno.

    ⚠️ **Nunca levanta e nunca bloqueia.** Isto é chamado de dentro de um laço de
    transcrição, a cada segundo de áudio: um erro aqui derrubaria o trabalho de verdade
    por causa do relatório dele. Sem turno vivo, simplesmente não há a quem contar.

    `fracao` é 0–1, ou `None` quando não há como saber — e aí o painel mostra movimento
    sem prometer porcentagem, que é diferente de mostrar 0%.
    """
    turno = _atual
    if turno is None or not turno._vivo:
        # ⭐ Sem turno vivo não quer dizer "ninguém escutando": a ação que o editor
        #   aprovou no cartão roda FORA do turno (ADR 0008), e é justamente a mais longa.
        #   O relato vai para a pendência em execução, e o cartão o mostra
        #   (achado no Assist anterior, 2026-09-19).
        from . import pendencias as _pendencias

        _pendencias.relatar(etapa, fracao, detalhe)
        return
    try:
        turno.emitir("progresso", {
            "etapa": etapa,
            "fracao": None if fracao is None else max(0.0, min(1.0, float(fracao))),
            "detalhe": detalhe,
        })
    except Exception:  # pragma: no cover - relatório não derruba trabalho
        log.debug("não consegui emitir progresso de %s", etapa, exc_info=True)


def terminar(turno: Turno) -> None:
    global _atual
    turno.encerrar()
    with _trava_global:
        if _atual is turno:
            _atual = None
