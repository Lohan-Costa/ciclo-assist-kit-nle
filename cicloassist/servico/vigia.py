"""A vigia do Premiere: o que o editor importar é processado sozinho (2026-09-22).

Pedido do editor: *"um botão toggle de watchfolder — se o usuário importar algo no Premiere,
automaticamente o processamento dispara"*. Não é uma pasta vigiada: é o PROJETO vigiado.
Arquivo que cai na pasta e ninguém importa não é material do editor.

## Como ela sabe que algo foi importado

MEDIDO no Premiere 23.2 (`spikes/o_premiere_avisa_import.py`, banco
`plugins/premiere-cep/api-extendscript.md`): `app.bind("onItemsAddedToProjectSuccess")`
dispara no import — agrupado, não um por item. O `host.jsx` soma esses avisos num contador
(`cicloVigia`), e esta thread lê o contador a cada `PULSO_S` (~3 ms pela ponte). Só quando
ele ANDA a vigia percorre o projeto (~0,5 ms por item).

⚠️ **E uma varredura de segurança a cada `SEGURANCA_S`, de propósito.** Import pelo menu ou
por arrasto na janela de projeto não foi medido, e outra extensão pode registrar o mesmo
evento e tomar o lugar do nosso (também não medido). Sem a segurança, os dois casos seriam
"a vigia está ligada e não fez nada" — o pior sintoma possível para um interruptor.

## O que ela faz, e o que NÃO faz

- ⭐ Só o que chegou DEPOIS de ligar. Ao ligar (e ao trocar de projeto) ela fotografa os
  arquivos do projeto como já vistos: ligar a vigia num projeto de 200 clipes não pode
  virar horas de transcrição que ninguém pediu. O que já estava lá tem os botões da aba.
- ⭐ Vetores primeiro (segundos por clipe), transcrição depois (~1 min por take): o plano
  fica procurável logo.
- ⛔⛔ **Nunca decupa.** A decupagem gasta a ASSINATURA do editor, e o produto promete o
  preço antes do clique. Trabalho pago que começa sozinho é exatamente o que ele não pode ser.
- ⛔ Uma tentativa por arquivo e estágio: o que falhou não volta a cada pulso.
- ⚠️ Uma tarefa por vez continua sendo a regra (`servico/tarefas.py`): com uma tarefa
  correndo (inclusive uma que o editor mandou), a vigia espera a vez.
- ⭐ O cruzamento com o banco do Avid acontece aqui do mesmo jeito que no botão: a fila do
  Premiere chama `identidade.aproveitar()` antes de processar.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .. import nle as _nle
from ..midia import cache as _cache
from ..midia import estagios as _estagios
from ..midia import inventario as _inventario
from . import config as _config
from . import tarefas as _tarefas

log = logging.getLogger("cicloassist.servico.vigia")

#: De quanto em quanto se lê o contador de imports. ~3 ms cada, medido.
PULSO_S = 3.0
#: A varredura de segurança, para o import que não dispara o evento.
SEGURANCA_S = 60.0

#: ⛔⛔ **Quanto da PONTE a vigia pode ocupar.** MEDIDO em 2026-09-23, no Premiere do
#: editor: `cicloVigia` — que o banco registra em **3 ms** e que aqui só lê um contador —
#: levou **5,20 s e 5,03 s** dentro do Premiere. Não é o trabalho dela: é o Premiere não
#: atendendo o `evalScript`. E a ponte é fila de UM pedido por vez, a MESMA do chat: com
#: um pulso fixo de 3 s e chamadas de 5 s, a fila nunca esvazia — um pedido do painel
#: esperou **12,94 s** só para entrar.
#:
#: ⇒ O pulso passa a sair da MEDIÇÃO do pulso anterior: a vigia nunca toma mais que esta
#: fração da ponte. Com o Premiere saudável (3 ms) o freio não existe e ela continua em
#: `PULSO_S`; com o Premiere ocupado ela recua sozinha.
#: ⭐ E recuar é a resposta CERTA, não um mal menor: Premiere ocupado é exatamente quando
#: processar o que acabou de ser importado importa menos que não atrapalhar.
OCUPACAO_MAXIMA = 0.10


def _proximo_pulso(gasto: float) -> float:
    """Quanto esperar depois de um passo que custou `gasto`."""
    return max(PULSO_S, gasto * (1.0 / OCUPACAO_MAXIMA - 1.0))
#: A ordem dos estágios: o que é rápido primeiro. ⛔ A decupagem não entra — ver o topo.
ESTAGIOS = (_estagios.VETORES, _estagios.TRANSCRICAO)
CHAVE_DO_ESTADO = "vigia_premiere"


class _Vigia:
    def __init__(self) -> None:
        self.trava = threading.Lock()
        self.acordar = threading.Event()
        self.thread: threading.Thread | None = None
        self.zerar()

    def zerar(self) -> None:
        #: O projeto da fotografia, e os arquivos que já estavam lá.
        self.projeto = ""
        self.vistos: set[str] = set()
        #: Chegaram depois de ligar e ainda têm estágio por fazer.
        self.pendentes: dict[str, str] = {}   # arquivo → nome
        self.tentados: set[tuple[str, str]] = set()
        self.contador: Any = None
        self.ultima_varredura = 0.0
        self.chegaram = 0
        self.processadas = 0
        self.erro = ""


_v = _Vigia()


def ligada() -> bool:
    return bool(_config.ler_estado().get(CHAVE_DO_ESTADO))


def ligar(sim: bool) -> None:
    """⭐ Ligar zera a fotografia: o que já está no projeto AGORA é o "já visto"."""
    _config.gravar_estado({CHAVE_DO_ESTADO: bool(sim)})
    with _v.trava:
        _v.zerar()
    iniciar()
    _v.acordar.set()


def estado() -> dict[str, Any]:
    with _v.trava:
        return {
            "ligada": ligada(),
            "projeto": _v.projeto,
            "chegaram": _v.chegaram,
            "pendentes": sorted(_v.pendentes.values()),
            "processadas": _v.processadas,
            "erro": _v.erro,
        }


def iniciar() -> None:
    """Sobe a thread uma vez (idempotente). Desligada, ela só dorme."""
    with _v.trava:
        if _v.thread is not None and _v.thread.is_alive():
            return
        _v.thread = threading.Thread(target=_laco, name="vigia-premiere", daemon=True)
        _v.thread.start()


def _laco() -> None:
    from ..nle.premiere import ponte as _ponte

    # ⭐⭐ Esta thread é trabalho de FUNDO, e a ponte precisa saber: os pedidos dela cedem
    #   a vez a qualquer coisa que o editor tenha pedido (`ponte.marcar_de_fundo`).
    _ponte.marcar_de_fundo()
    espera = PULSO_S
    while True:
        _v.acordar.wait(espera)
        acordado = _v.acordar.is_set()
        _v.acordar.clear()
        if not ligada():
            espera = PULSO_S
            continue
        comeco = time.monotonic()
        try:
            passo()
        except Exception as e:  # noqa: BLE001 — a vigia não pode morrer calada
            log.exception("a vigia tropeçou")
            with _v.trava:
                _v.erro = str(e)
        gasto = time.monotonic() - comeco
        antes, espera = espera, _proximo_pulso(gasto)
        # ⚠️ Dito UMA vez por mudança de patamar: a cada pulso encheria o log, e o que
        #   interessa é o editor (ou eu, lendo depois) saber que ela recuou e por quê.
        if espera > PULSO_S and abs(espera - antes) > 1.0:
            log.info("vigia: o passo levou %.2f s; próximo pulso em %.0f s "
                     "(o Premiere está ocupado)", gasto, espera)
        elif espera == PULSO_S and antes > PULSO_S:
            log.info("vigia: o Premiere respondeu rápido de novo (%.2f s); voltando ao "
                     "pulso de %.0f s", gasto, PULSO_S)
        if acordado:
            # Acordada por `ligar()`: o editor mexeu no interruptor, não é hora de recuar.
            espera = PULSO_S


def passo() -> None:
    """Um pulso: olhar se algo chegou, e mandar processar se a fila estiver livre.

    ⚠️ Público para os testes: a thread só chama isto num laço.
    """
    from ..nle import premiere as _premiere
    from ..nle.premiere import ponte as _ponte

    # ⭐ Pelo MCP nativo (Premiere 27.1+) a vigia não depende do painel CEP vivo.
    if not _premiere.alcancavel():
        return
    try:
        contador = _premiere.contador_da_vigia()
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou,
            _premiere.mcp_nativo.McpIndisponivel, _premiere.mcp_nativo.McpFalhou) as e:
        # ⚠️ `host.jsx` velho (sem `cicloVigia`): sobra a varredura de segurança.
        log.debug("sem contador de imports (%s)", e)
        contador = None
    agora = time.time()
    with _v.trava:
        andou = contador is not None and contador != _v.contador
        _v.contador = contador
        # ⛔⛔ A PRIMEIRA olhada é imediata (ligar o interruptor tem de fazer algo na hora),
        #    mas só a primeira. Enquanto a condição era "ainda não sei o projeto", uma
        #    leitura que FALHA — projeto ilegível, ponte no prazo — deixava `projeto` vazio
        #    e a vigia varria a cada `PULSO_S`, para sempre. E a ponte do Premiere é fila de
        #    um pedido por vez, a MESMA do chat: o sintoma seria o painel lento sem motivo.
        #    ⭐ `ultima_varredura` é marcada mesmo na falha, então o relógio de segurança
        #    passa a mandar depois da primeira tentativa.
        primeira = not _v.projeto and not _v.ultima_varredura
        precisa = andou or primeira or agora - _v.ultima_varredura >= SEGURANCA_S
    if precisa:
        _varrer(_premiere)
    _despachar(_premiere)


def _varrer(_premiere) -> None:
    projeto, clipes, erro = _premiere.clipes_do_projeto(forcar=True)
    arquivos = {c["arquivo_premiere"]: c.get("nome") or "" for c in clipes.values()
                if c.get("arquivo_premiere")}
    with _v.trava:
        _v.ultima_varredura = time.time()
        _v.erro = erro
        if erro and not clipes:
            return
        if projeto != _v.projeto:
            # ⭐ Projeto novo (ou a primeira olhada depois de ligar): fotografa, não processa.
            _v.projeto = projeto
            _v.vistos = set(arquivos)
            _v.pendentes.clear()
            _v.tentados.clear()
            log.info("vigia: %s com %d arquivo(s) já vistos", projeto, len(arquivos))
            return
        novos = {a: n for a, n in arquivos.items() if a not in _v.vistos}
        if novos:
            log.info("vigia: %d arquivo(s) importado(s): %s", len(novos),
                     ", ".join(list(novos.values())[:5]))
            _v.vistos |= set(novos)
            _v.pendentes.update(novos)
            _v.chegaram += len(novos)


def _falta(chave: str, clipe: dict, estagio: str) -> bool:
    if clipe.get("provisoria"):
        return True
    from . import rotas
    try:
        return rotas._falta(_cache.Midia(chave), estagio)
    except _cache.ChaveInvalida:
        return False


def _despachar(_premiere) -> None:
    with _v.trava:
        if not _v.pendentes:
            return
    if _tarefas.ha_tarefa_viva():
        return   # ⚠️ uma tarefa por vez; a vigia espera a vez
    _, clipes, _ = _premiere.clipes_do_projeto()
    por_arquivo = {c.get("arquivo_premiere"): (k, c) for k, c in clipes.items()}

    with _v.trava:
        pendentes = dict(_v.pendentes)
    for estagio in ESTAGIOS:
        alvos = []
        for arquivo in pendentes:
            achado = por_arquivo.get(arquivo)
            if achado is None or (arquivo, estagio) in _v.tentados:
                continue
            chave, clipe = achado
            if _inventario.pode_analisar(clipe, estagio) and _falta(chave, clipe, estagio):
                alvos.append((arquivo, chave))
        if not alvos:
            continue
        from . import rotas
        resposta = rotas.analisar({"estagio": estagio, "chaves": [c for _, c in alvos],
                                   "motivo": "vigia"}, _nle.PREMIERE)
        with _v.trava:
            _v.tentados |= {(a, estagio) for a, _ in alvos}
            if resposta.status == 200:
                _v.processadas += len(alvos)
        log.info("vigia: %s em %d arquivo(s) (%d)", estagio, len(alvos), resposta.status)
        return

    # Nada mais a fazer para ninguém: quem sobrou já está pronto (ou já foi tentado).
    with _v.trava:
        for arquivo in pendentes:
            if all((arquivo, e) in _v.tentados or arquivo not in por_arquivo
                   or not _inventario.pode_analisar(por_arquivo[arquivo][1], e)
                   or not _falta(*por_arquivo[arquivo], e) for e in ESTAGIOS):
                _v.pendentes.pop(arquivo, None)


def esquecer() -> None:
    """Para os testes."""
    with _v.trava:
        _v.zerar()
