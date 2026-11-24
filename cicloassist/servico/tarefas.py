"""Trabalho que acontece FORA de um turno do modelo.

Até aqui tudo que o produto fazia era dentro de uma pergunta: o editor perguntava, o
modelo chamava uma ferramenta, e a ferramenta processava enquanto ele esperava. A aba
Vetores pede o contrário — ⭐ *"deixa a análise correndo enquanto eu faço outra coisa, e
quando o chat precisar já está tudo mapeado"*.

## Uma tarefa por vez, e isso é decisão, não simplificação

⚠️ O que roda aqui **disputa a máquina com o turno**: uma varredura são mil e setecentos
`ffprobe`, e uma transcrição é o mesmo ASR que o `transcrever` usa. Duas tarefas em
paralelo não terminam mais cedo — terminam as duas devagar, e o editor, que está
conversando ao mesmo tempo, sente as duas coisas travando.

É o mesmo raciocínio do "um turno por vez" do `servico/turno.py`, por um motivo
diferente: lá é porque o cartão de aprovação não sabe de que turno é; aqui é CPU.

## O que o painel precisa saber, e o que ele nunca precisa perguntar

A tarefa publica `fracao` e `texto` — os mesmos dois campos que `turno.avisar()` já usa
para pintar a barra de progresso. A tela consulta `GET /vetores/andamento` enquanto há
tarefa viva e para de consultar quando acaba.

⭐ **Cancelar aproveita o que já foi feito.** A varredura devolve o parcial e grava a
sondagem; a próxima começa de onde esta parou. Quem cancela está com pressa, não
arrependido.

⛔ **Nada aqui derruba o serviço.** Uma tarefa que estoura vira `estado="erro"` com a
mensagem — o editor precisa saber que a análise dele não aconteceu, e o painel precisa
continuar respondendo.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

log = logging.getLogger("cicloassist.servico.tarefas")

_trava = threading.Lock()


@dataclass
class Tarefa:
    """Uma unidade de trabalho de fundo, e tudo que a tela mostra dela."""

    id: str
    #: `varredura` hoje; é o campo que a tela usa para escolher a frase.
    tipo: str
    #: O que está sendo trabalhado — a pasta, o nome da mídia.
    alvo: str = ""
    #: `correndo` · `pronta` · `parada` · `erro`
    estado: str = "correndo"
    fracao: float = 0.0
    texto: str = ""
    comecou: float = field(default_factory=time.time)
    terminou: float = 0.0
    erro: str = ""
    #: O que a tarefa produziu, em números — vai inteiro para a tela.
    resumo: dict[str, Any] = field(default_factory=dict)

    @property
    def viva(self) -> bool:
        return self.estado == "correndo"

    def como_dicionario(self) -> dict[str, Any]:
        d = asdict(self)
        d["viva"] = self.viva
        d["segundos"] = round((self.terminou or time.time()) - self.comecou, 1)
        return d


class TarefaEmCurso(RuntimeError):
    """Já há uma tarefa viva. Quem chamou decide o que dizer ao editor."""


#: A tarefa atual — viva ou a última que terminou. ⭐ Guardar a que terminou é o que
#: permite ao painel abrir DEPOIS e ainda ver o resultado: sem isso, quem trocasse de aba
#: no meio voltaria para uma tela que não sabe que houve varredura.
_atual: Tarefa | None = None
_parar = threading.Event()
_thread: threading.Thread | None = None


def atual() -> Tarefa | None:
    with _trava:
        return _atual


def ha_tarefa_viva() -> bool:
    t = atual()
    return t is not None and t.viva


def parar() -> bool:
    """Pede para a tarefa viva terminar. Devolve se havia o que parar.

    ⚠️ Pede, não mata: a thread confere o sinal entre os passos e sai com o parcial na
    mão. Matar no meio deixaria a sondagem pela metade e o índice a reconstruir.
    """
    if not ha_tarefa_viva():
        return False
    _parar.set()
    log.info("tarefa: parada pedida")
    return True


def _terminar(tarefa: Tarefa, estado: str, erro: str = "") -> None:
    with _trava:
        tarefa.estado = estado
        tarefa.erro = erro
        tarefa.terminou = time.time()
        if estado == "pronta":
            tarefa.fracao = 1.0


def comecar(
    tipo: str,
    alvo: str,
    trabalho: Callable[[Callable[[float, str], None], threading.Event], dict[str, Any]],
) -> Tarefa:
    """Põe `trabalho` para correr numa thread e devolve a tarefa que o representa.

    `trabalho(aviso, parar)` recebe o relator de progresso e o sinal de parada, e devolve
    o resumo que vai para a tela.
    """
    global _atual, _thread

    with _trava:
        if _atual is not None and _atual.viva:
            raise TarefaEmCurso(_atual.tipo)
        tarefa = _atual = Tarefa(uuid.uuid4().hex[:12], tipo, alvo)
        _parar.clear()

    def avisar(fracao: float, texto: str) -> None:
        # Sem trava: são duas escritas de campo simples, e o pior caso de uma leitura no
        # meio é a tela mostrar uma porcentagem de um instante atrás.
        tarefa.fracao = max(0.0, min(1.0, float(fracao)))
        tarefa.texto = texto

    def correr() -> None:
        log.info("tarefa %s: %s começou (%s)", tarefa.id, tipo, alvo)
        try:
            resumo = trabalho(avisar, _parar)
        except Exception as e:                    # noqa: BLE001 — ver o cabeçalho
            # ⛔ Qualquer exceção vira estado de tarefa. Uma varredura que estoura não
            #   pode derrubar a thread e deixar o painel esperando para sempre por um
            #   andamento que nunca mais muda.
            log.exception("tarefa %s falhou", tarefa.id)
            _terminar(tarefa, "erro", str(e) or e.__class__.__name__)
            return
        tarefa.resumo = resumo or {}
        _terminar(tarefa, "parada" if _parar.is_set() else "pronta")
        log.info("tarefa %s: %s (%s)", tarefa.id, tarefa.estado, tarefa.resumo)

    _thread = threading.Thread(target=correr, name=f"tarefa-{tipo}", daemon=True)
    _thread.start()
    return tarefa


def esquecer() -> None:
    """Joga fora a tarefa guardada. Só os testes usam — o painel vive com a última."""
    global _atual
    with _trava:
        _atual = None
    _parar.clear()
