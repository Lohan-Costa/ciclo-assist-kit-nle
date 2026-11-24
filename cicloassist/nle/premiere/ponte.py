"""A ponte serviço → painel → ExtendScript → serviço.

No Premiere não há API externa: `app.project` só existe dentro do painel CEP. O serviço
deixa o pedido numa fila; o painel (a página servida, que tem `__adobe_cep__`) segura um
long-poll em `GET /premiere/pedido`, roda `evalScript` e devolve em `POST
/premiere/resposta`. MEDIDO no Premiere 23.2 (2026-09-17, `spikes/o_premiere_por_dentro.py`):
**2,5–4,9 ms** por volta — contra ~500 ms de uma chamada gRPC do Media Composer.

⛔ **O texto que vai para o `evalScript` é montado AQUI, nunca pelo modelo.** `chamar()`
recebe o nome de uma função do nosso `host.jsx` e argumentos que viram literais JSON —
que em ES3 são literais válidos. Texto livre do modelo virando ExtendScript seria um shell
no Premiere do editor (ADR 0005).

⚠️ **Sem painel aberto não há ponte**, e isso tem de ser dito, não esperado: o CEP só roda
enquanto o painel existe. `painel_vivo()` olha a última batida; sem ela, `chamar()` recusa
na hora com a frase que o editor entende.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("cicloassist.nle.premiere.ponte")

#: Quanto o painel segura o long-poll antes de voltar vazio e perguntar de novo.
ESPERA_DO_PAINEL_S = 20.0
#: Sem batida do painel há mais que isto, ele não está aberto. Uma batida por long-poll
#: (≤ 20 s) mais folga para o estrangulamento de timer de página escondida.
PAINEL_VIVO_S = 45.0
#: O prazo de uma chamada, contado de quando o PAINEL a levou.
PRAZO_S = 30.0
#: De quanto em quanto tempo a espera reconfere (painel vivo? prazo estourado?).
PASSO_DA_ESPERA_S = 0.25
#: A partir de quanto uma chamada vira linha de log. ⚠️ Uma por chamada encheria o log: a
#: vigia sozinha faz uma por minuto, e o painel faz várias por abertura de aba.
LENTO_S = 1.0

_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PremiereIndisponivel(RuntimeError):
    """A ponte do Ciclo Assist no Premiere (invisível, desde a fase 4) não está no ar, ou não respondeu."""


class ExtendScriptFalhou(RuntimeError):
    """A função rodou e lançou, ou devolveu o que não é JSON."""


#: ⭐⭐ Quem é trabalho de FUNDO é a THREAD, não a chamada. A vigia e a sincronização de
#: descrições nascem em threads próprias e passam por várias camadas antes de chegar aqui
#: (`clipes_do_projeto`, `escopo_agora`…): levar um parâmetro por toda essa corrente
#: significaria mudar assinatura em cada uma, e esquecer uma delas é um pedido de fundo se
#: passando por gesto do editor.
_quem_sou = threading.local()


def marcar_de_fundo() -> None:
    """Esta thread é trabalho de fundo: os pedidos dela cedem a vez a quem o editor pediu."""
    _quem_sou.de_fundo = True


def sou_de_fundo() -> bool:
    return bool(getattr(_quem_sou, "de_fundo", False))


@dataclass
class _Pedido:
    id: str
    expr: str
    #: Trabalho de fundo cede a vez: um pedido do editor entra NA FRENTE dele na fila.
    de_fundo: bool = False
    pronto: threading.Event = field(default_factory=threading.Event)
    resposta: str | None = None
    #: Quando o painel LEVOU o pedido. ⛔ O prazo conta daqui, não de quando ele entrou na
    #: fila: o painel roda um pedido por vez, e uma leitura longa (a mídia toda do projeto)
    #: faria a chamada seguinte morrer dizendo "o Premiere não respondeu" — sobre um
    #: Premiere que nem tinha recebido o pedido ainda.
    entregue_em: float = 0.0


_fila: list[_Pedido] = []
_esperando: dict[str, _Pedido] = {}
_trava = threading.Condition()
_contador = itertools.count(1)
_ultima_batida = float("-inf")


def expressao(funcao: str, *args: Any) -> str:
    """`funcao("a", 1)` com cada argumento como literal JSON. Nome fora do padrão é recusado."""
    if not _NOME.match(funcao):
        raise ValueError(f"nome de função inválido: {funcao!r}")
    return f"{funcao}({', '.join(json.dumps(a, ensure_ascii=True) for a in args)})"


def enfileirar(pedido: "_Pedido", fila: list | None = None) -> None:
    """Põe o pedido na fila, no LUGAR dele.

    ⭐⭐ O gesto do editor passa NA FRENTE do trabalho de fundo. MEDIDO em 2026-09-23: um
    pedido do painel esperou **12,94 s na fila** atrás dos pulsos da vigia — e esta é a
    MESMA fila do chat. Trabalho que ninguém pediu não pode ser o motivo de uma pergunta
    esperar.

    ⚠️ Entre iguais, a ordem de chegada manda: um pedido de fundo não é ultrapassado por
    outro de fundo, e o editor que pergunta duas coisas as recebe na ordem em que pediu.
    ⚠️ E isto só reordena o que ainda NÃO foi entregue: o que o Premiere já está rodando
    não dá para interromper, e tentar seria o pior dos mundos.
    """
    alvo = _fila if fila is None else fila
    if pedido.de_fundo:
        alvo.append(pedido)
        return
    lugar = next((i for i, p in enumerate(alvo) if p.de_fundo), len(alvo))
    alvo.insert(lugar, pedido)


def painel_vivo() -> bool:
    with _trava:
        return time.monotonic() - _ultima_batida < PAINEL_VIVO_S


def bateu_desde(instante: float) -> bool:
    """Houve batida do painel DEPOIS de `instante` (relógio `time.monotonic`)?

    ⛔⛔ MEDIDO em 2026-11-01 (`spikes/abrir_e_fechar_o_premiere.py`): fechado o Premiere e
    reaberto em seguida, o long-poll da ponte MORTA continuava esperando aqui (até
    `ESPERA_DO_PAINEL_S`) e levou o primeiro pedido da ponte nova — que ficou 180 s sem
    resposta. `painel_vivo()` dizia sim pela batida velha. Quem acabou de LANÇAR o Premiere
    espera uma batida nova E que a espera de um long-poll morto tenha vencido.
    """
    with _trava:
        return _ultima_batida > instante


def chamar(funcao: str, *args: Any, prazo: float = PRAZO_S) -> Any:
    """Roda `funcao(*args)` do `host.jsx` no Premiere e devolve o JSON que ela produziu."""
    return _ler(funcao, chamar_cru(funcao, *args, prazo=prazo))


def chamar_cru(funcao: str, *args: Any, prazo: float = PRAZO_S) -> str:
    """O mesmo, devolvendo o TEXTO que a função produziu, sem ler como JSON — o que os módulos pedem pelo núcleo
    (`/nucleo/premiere/chamar`): as funções `sinc*`/`dlpc*` devolvem texto (`ok|…`, `err|…`, uma versão)."""
    if not painel_vivo():
        raise PremiereIndisponivel(
            "A ponte do Ciclo Assist no Premiere não respondeu (ela é invisível e sobe sozinha com o "
            "Premiere). Peça ao editor para fechar e abrir o Premiere; se não voltar, ⚙ › Integrações › "
            "instalar a ponte.")
    pedido = _Pedido(id=str(next(_contador)), expr=expressao(funcao, *args),
                     de_fundo=sou_de_fundo())
    entrou_em = time.monotonic()
    with _trava:
        enfileirar(pedido)
        _esperando[pedido.id] = pedido
        _trava.notify_all()
    try:
        while not pedido.pronto.wait(PASSO_DA_ESPERA_S):
            if not pedido.entregue_em:
                # Ainda na fila, atrás de outro pedido. Só desiste se o painel sumir.
                if not painel_vivo():
                    raise PremiereIndisponivel(
                        "A ponte do Ciclo Assist parou de responder no Premiere (ele foi fechado, "
                        "ou a ponte recarregou). Peça de novo; se repetir, feche e abra o Premiere.")
                continue
            if time.monotonic() - pedido.entregue_em > prazo:
                raise PremiereIndisponivel(
                    f"O Premiere não respondeu em {prazo:.0f} s. Ele pode estar com um "
                    "diálogo aberto ou ocupado (renderizando, importando).")
    finally:
        with _trava:
            _esperando.pop(pedido.id, None)
            if pedido in _fila:
                _fila.remove(pedido)
        # ⭐ ESPERA na fila contra EXECUÇÃO no Premiere, e a distinção é o diagnóstico
        #   inteiro (2026-09-23): a ponte atende um pedido por vez, e o painel, a vigia e a
        #   sincronização de descrições disputam a mesma fila. "O painel está lento" pode
        #   ser o Premiere demorando — ou pode ser este pedido esperando a vez.
        #   ⚠️ Só o que passa de `LENTO_S`: uma linha por chamada encheria o log.
        fim = time.monotonic()
        na_fila = (pedido.entregue_em or fim) - entrou_em
        if fim - entrou_em >= LENTO_S:
            log.info("ponte %s em %.2f s — na fila: %.2f · no Premiere: %.2f",
                     funcao, fim - entrou_em, na_fila,
                     fim - (pedido.entregue_em or fim))
    return pedido.resposta or ""


def _ler(funcao: str, texto: str) -> Any:
    # ⚠️ Exceção no ExtendScript chega como TEXTO ("EvalScript error."), não como erro.
    if texto.startswith("EvalScript error"):
        raise ExtendScriptFalhou(
            f"{funcao} falhou dentro do Premiere ({texto}). O host.jsx carregou? "
            "Um Reload no painel recarrega.")
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ExtendScriptFalhou(f"{funcao} devolveu o que não é JSON: {texto[:200]!r}") from e
    if isinstance(dados, dict) and dados.get("erro"):
        raise ExtendScriptFalhou(str(dados["erro"]))
    return dados


# ── o lado do painel ─────────────────────────────────────────────────────────


def proximo(espera: float = ESPERA_DO_PAINEL_S) -> dict[str, str]:
    """O próximo pedido para o painel, ou `{}` depois de `espera` sem nenhum."""
    global _ultima_batida
    limite = time.monotonic() + espera
    with _trava:
        _ultima_batida = time.monotonic()
        while not _fila:
            resta = limite - time.monotonic()
            if resta <= 0:
                return {}
            _trava.wait(resta)
        pedido = _fila.pop(0)
        _ultima_batida = time.monotonic()
        pedido.entregue_em = _ultima_batida
        return {"id": pedido.id, "expr": pedido.expr}


def responder(id_: str, resposta: Any) -> bool:
    """O painel devolveu. Devolve se havia alguém esperando (atrasado não tem)."""
    global _ultima_batida
    with _trava:
        _ultima_batida = time.monotonic()
        pedido = _esperando.get(str(id_))
    if pedido is None:
        log.info("resposta %s chegou sem ninguém esperando (prazo vencido?)", id_)
        return False
    pedido.resposta = resposta if isinstance(resposta, str) else json.dumps(resposta)
    pedido.pronto.set()
    return True


def esquecer() -> None:
    """Estado limpo (testes)."""
    global _ultima_batida
    with _trava:
        _fila.clear()
        _esperando.clear()
        _ultima_batida = float("-inf")
