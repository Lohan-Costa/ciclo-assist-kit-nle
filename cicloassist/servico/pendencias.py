"""Pedidos de aprovação que esperam o editor — sem relógio nenhum.

## A inversão que este módulo carrega

O portão **não bloqueia mais**. O Ciclo Assist mostra o que pretende fazer, **encerra o
lado dele da conversa** e fica quieto. O editor decide quando quiser: daqui a um minuto,
depois do almoço, amanhã de manhã. É como funciona qualquer conversa — quem perguntou
para de falar e espera; não existe prazo para a resposta de uma pessoa.

⛔⛔ **Nunca reintroduzir um tempo máximo de espera aqui.** A versão anterior bloqueava a
chamada MCP até o clique, e o editor tinha o prazo do CLI para responder —
**medido em 60 s** (`spikes/portao_espera.py`, 2026-09-10, CLI 2.1.267). Na prática:
quem saísse da mesa perdia o trabalho, e o modelo recebia `"The operation timed out."`,
sem uma palavra sobre permissão — e saía procurando defeito no tamanho do plano, criando
sequências parciais na bin do editor. Esticar o prazo só empurraria o mesmo defeito para
mais longe: o erro era ter prazo.

## Como fica o caminho

```
modelo pede montar_corte
   └→ portão abre uma PENDÊNCIA e responde `deny` na hora
        └→ o modelo diz "mostrei o plano, me avise" e o turno TERMINA
             └→ o cartão fica na tela, a caixa de texto destrava
                  └→ o editor clica (hoje, amanhã)
                       └→ **o serviço executa a ferramenta**, com os argumentos que ele viu
```

⭐ **Quem executa depois do clique somos nós, não o modelo.** Roda exatamente o `input`
que foi desenhado no cartão — não uma segunda geração, que poderia sair diferente do que
o editor leu. E a ação passa a ser consequência direta de um clique humano, nunca de uma
decisão do modelo: é mais estrito que o desenho anterior, não menos (ADR 0003, ADR 0008).

## O que sobrevive a quê

| morre | sobrevive |
|---|---|
| o turno acaba | a pendência fica |
| o painel recarrega | a pendência volta pelo `GET /pendencias` |
| o serviço reinicia | a pendência volta do disco |

⚠️ **O recado da execução vira contexto do próximo turno**, não um turno próprio: o modelo
precisa saber que o corte foi montado — senão ele oferece montar de novo —, mas gastar um
turno da assinatura do editor só para contar isso seria cobrar dele por uma mensagem
interna nossa.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("cicloassist.servico.pendencias")

_trava = threading.Lock()


def arquivo() -> Path:
    """Onde as pendências moram entre reinícios.

    Na pasta de dados do produto: é estado da máquina do editor, não do projeto — uma bin
    não deve ganhar um arquivo nosso por causa de um clique adiado.

    ⚠️ Não `cache.raiz().parent`: com o cache na raiz de um volume do Mac (`/Volumes/RAID`),
    o pai é `/Volumes`, que é do root — `PermissionError` só no log, e os cartões sumiam
    ao reiniciar. No Windows `D:\\` é pai de si mesmo, e por isso ninguém viu.
    """
    from .config import pasta
    return pasta() / "pendencias.json"


@dataclass
class Pendencia:
    """Um pedido mostrado ao editor, esperando o clique dele."""

    id: str
    ferramenta: str          # o nome técnico, sem o prefixo do MCP
    rotulo: str              # o que o editor lê no cartão
    entrada: dict[str, Any]
    criada_em: float
    estado: str = "aberta"   # aberta · feita · recusada · falhou
    resultado: dict[str, Any] = field(default_factory=dict)
    #: O que contar ao modelo no próximo turno. Vazio quando já foi contado.
    recado: str = ""
    #: ⭐ De que conversa veio o pedido — "chat" ou "fluxos" (2026-11-03). O recado volta SÓ para ela:
    #:   a aprovação de um fluxo contada ao chat faria o chat achar que já fez o trabalho.
    conversa: str = "chat"

    @property
    def aberta(self) -> bool:
        return self.estado == "aberta"

    def para_o_painel(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ferramenta": self.rotulo,
            "entrada": self.entrada,
            "criada_em": self.criada_em,
            "estado": self.estado,
        }


#: Tudo que já foi mostrado, por id. Carregado do disco na primeira consulta.
_tudo: dict[str, Pendencia] = {}
_carregado = False


# ── disco ────────────────────────────────────────────────────────────────────


def _carregar() -> None:
    """Lê o disco uma vez. Arquivo corrompido vira 'nenhuma pendência', nunca exceção.

    ⚠️ Mesma regra do cache de mídia: perder uma pendência custa um clique repetido;
    estourar na partida do serviço custa o painel inteiro.
    """
    global _carregado
    if _carregado:
        return
    _carregado = True
    caminho = arquivo()
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        for item in bruto.get("pendencias", []):
            p = Pendencia(**item)
            _tudo[p.id] = p
    except (OSError, ValueError, TypeError):
        if caminho.exists():
            log.warning("pendencias.json ilegível; começando sem nenhuma")


def _gravar() -> None:
    """Guarda só o que ainda importa: o que está aberto, e o recado que falta contar."""
    vivas = [p for p in _tudo.values() if p.aberta or p.recado]
    try:
        caminho = arquivo()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        from ..midia.cache import escrever_atomico
        escrever_atomico(
            caminho,
            json.dumps({"pendencias": [asdict(p) for p in vivas]},
                       ensure_ascii=False, indent=1).encode("utf-8"),
        )
    except (OSError, ValueError) as e:
        # Não poder gravar não pode derrubar o pedido: ele ainda vale nesta sessão.
        log.warning("não consegui gravar as pendências: %s", e)


# ── o que o portão usa ───────────────────────────────────────────────────────


def _assinatura(ferramenta: str, entrada: dict) -> str:
    return ferramenta + "|" + json.dumps(entrada, ensure_ascii=False, sort_keys=True)


def abrir(ferramenta: str, rotulo: str, entrada: dict[str, Any], conversa: str = "") -> Pendencia:
    """Registra um pedido para o editor ver. Devolve a pendência.

    ⭐ **Pedido idêntico não vira cartão novo.** Em campo o modelo repetiu o mesmo
    `montar_corte` quando achou que a primeira tentativa tinha falhado, e o editor ficou
    com dois cartões iguais empilhados, sem saber qual valia. Se a ferramenta e os
    argumentos são os mesmos e o pedido ainda está aberto, ele é o mesmo pedido.
    """
    with _trava:
        _carregar()
        alvo = _assinatura(ferramenta, entrada)
        for p in _tudo.values():
            if p.aberta and _assinatura(p.ferramenta, p.entrada) == alvo:
                log.info("pedido repetido de %s; reusando %s", ferramenta, p.id)
                return p

        if not conversa:
            from . import turno as _turno
            t = _turno.atual()
            conversa = getattr(t, "conversa", "") or "chat"
        p = Pendencia(
            id=uuid.uuid4().hex[:12],
            ferramenta=ferramenta,
            rotulo=rotulo,
            entrada=entrada,
            criada_em=time.time(),
            conversa=conversa,
        )
        _tudo[p.id] = p
        _gravar()
    log.info("pendência %s aberta: %s", p.id, ferramenta)
    return p


def abertas() -> list[Pendencia]:
    with _trava:
        _carregar()
        return sorted((p for p in _tudo.values() if p.aberta), key=lambda p: p.criada_em)


def buscar(id_: str) -> Pendencia | None:
    with _trava:
        _carregar()
        return _tudo.get(id_)


# ── o que está acontecendo enquanto a ação roda ──────────────────────────────
#
# ⭐⭐ **Achado no Assist anterior, 2026-09-19.** A ação aprovada roda FORA do turno
# (ADR 0008), e o `turno.avisar` das ferramentas — que é o que tira o editor do escuro
# durante um trabalho longo — não tinha a quem contar: o cartão dizia "fazendo…" do começo
# ao fim. O primeiro `sincronizar_diaria` de verdade levou minutos assim.
#
# ⇒ Enquanto a ferramenta roda, o relato vem para cá, e o painel pergunta por ele
#   (`GET /andamento`). ⚠️ Vale para TODA ferramenta que já relatava: `montar_corte`,
#   `separar_falas`, `editar_timeline`, `sincronizar`. Nenhuma precisou mudar.

#: Qual pendência a ESTA thread está executando. Thread-local porque o relato nasce lá
#: dentro, longe de quem chamou — e duas execuções ao mesmo tempo não podem se misturar.
_executando = threading.local()

_andamento: dict[str, dict[str, Any]] = {}
#: Lock PRÓPRIO, e não o `_trava` do arquivo: `decidir` segura aquele para gravar o disco,
#: e um relato que esperasse por ele pararia a ferramenta para contar que está andando.
_trava_do_andamento = threading.Lock()


def relatar(etapa: str, fracao: float | None = None, detalhe: str = "") -> None:
    """"Está nisto, e já foi tanto." Sem pendência em execução nesta thread, não faz nada.

    ⚠️ Nunca levanta: é chamado de dentro de laços de trabalho (o ASR conta por segundo de
    áudio), e um erro aqui derrubaria o trabalho por causa do relatório dele.
    """
    desvio = getattr(_executando, "relator", None)
    if desvio is not None:
        # ⭐ Um passo de FLUXO (`servico/fluxo.py`): o relato vai para o estado do fluxo,
        #   que é o que a janela mostra — nenhuma ferramenta precisou mudar.
        try:
            desvio(etapa, fracao, detalhe)
        except Exception:  # pragma: no cover — relatório não derruba trabalho
            log.debug("o relator do fluxo falhou", exc_info=True)
        return
    id_ = getattr(_executando, "pendencia", "")
    if not id_:
        return
    try:
        with _trava_do_andamento:
            anterior = _andamento.get(id_) or {}
            _andamento[id_] = {
                "id": id_,
                "etapa": str(etapa or ""),
                "fracao": None if fracao is None else max(0.0, min(1.0, float(fracao))),
                "detalhe": str(detalhe or ""),
                "desde": anterior.get("desde") or time.time(),
                "em": time.time(),
            }
    except Exception:  # pragma: no cover — relatório não derruba trabalho
        log.debug("não consegui anotar o andamento de %s", etapa, exc_info=True)


class PassoCancelado(Exception):
    """O editor cancelou o fluxo NO MEIO deste passo, num ponto de ESPERA (autor, 2026-11-04)."""


def conferir_cancelamento(oque: str = "") -> None:
    """⭐⭐ Cancelar no meio de um passo longo (autor, 2026-11-04: "se o usuário quiser interromper não
    tem como"). Levanta `PassoCancelado` se o editor pediu.

    ⛔ Só é chamado onde PARAR É SEGURO: nos laços que ESPERAM um programa de fora (o sync do Sincronizar, o
    conform do De Lá Pra Cá) — nunca no `relatar` geral, que também roda no meio de um CloseBin →
    gravar → OpenBin, e parar ali deixaria a bin do editor fechada. Fora de um fluxo, não faz nada."""
    pedido = getattr(_executando, "cancelar", None)
    try:
        sim = bool(pedido()) if pedido is not None else False
    except Exception:  # pragma: no cover — a conferência não derruba trabalho
        sim = False
    if sim:
        raise PassoCancelado(oque)


@contextlib.contextmanager
def relatando_para(relator, cancelar=None):
    """Enquanto dura, o `relatar` DESTA thread vai para `relator` (um passo de fluxo), e
    `conferir_cancelamento` pergunta a `cancelar` se o editor pediu para parar."""
    anterior = getattr(_executando, "relator", None)
    anterior_c = getattr(_executando, "cancelar", None)
    _executando.relator = relator
    _executando.cancelar = cancelar
    try:
        yield
    finally:
        _executando.relator = anterior
        _executando.cancelar = anterior_c


def andamento() -> dict[str, Any]:
    """O que está sendo feito agora, para o cartão mostrar. `{}` quando não há nada."""
    with _trava_do_andamento:
        if not _andamento:
            return {}
        atual = max(_andamento.values(), key=lambda a: a["em"])
        return {**atual, "decorrido": round(time.time() - atual["desde"], 1)}


# ── o clique ─────────────────────────────────────────────────────────────────


def decidir(id_: str, permitido: bool) -> dict[str, Any]:
    """O editor clicou. Executa a ferramenta, se ele deixou.

    ⚠️ **Executa FORA do turno**, na thread que atende o clique — pode demorar (uma bin
    de catorze cortes leva segundos, e o `OpenBin` do Avid leva mais). O painel mostra
    "fazendo…" enquanto isso; é a única coisa acontecendo.
    """
    p = buscar(id_)
    if p is None:
        return {"ok": False, "motivo": "esse pedido não existe mais"}
    if not p.aberta:
        # Clique repetido, ou dois painéis abertos. Não é erro do editor.
        return {"ok": False, "motivo": "esse pedido já foi respondido", "estado": p.estado}

    if not permitido:
        with _trava:
            p.estado = "recusada"
            p.recado = f"O editor recusou: {p.rotulo}."
            _gravar()
        log.info("pendência %s: NÃO", id_)
        return {"ok": True, "estado": "recusada"}

    log.info("pendência %s: sim — executando %s", id_, p.ferramenta)
    _executando.pendencia = id_
    relatar("começando", None, p.rotulo)
    try:
        from ..mcp.registro import FERRAMENTAS
        registrada = FERRAMENTAS.get(p.ferramenta)
        if registrada is None:
            raise KeyError(p.ferramenta)
        resultado = registrada.funcao(**p.entrada)
    except Exception as e:
        # ⛔ A falha é do editor saber, não só do log: ele clicou e tem de ver o que deu.
        log.exception("pendência %s falhou ao executar", id_)
        with _trava:
            p.estado = "falhou"
            p.resultado = {"erro": str(e)}
            p.recado = f"{p.rotulo}: o editor autorizou, mas a execução falhou ({e})."
            _gravar()
        return {"ok": False, "estado": "falhou", "erro": str(e)}
    finally:
        # ⚠️ Nos DOIS caminhos, e antes de a resposta sair: o painel para de perguntar
        #   quando o `/responder` volta, mas um andamento esquecido apareceria no cartão
        #   seguinte como se a ação de antes ainda estivesse rodando.
        _executando.pendencia = ""
        with _trava_do_andamento:
            _andamento.pop(id_, None)

    with _trava:
        p.estado = "feita"
        p.resultado = resultado if isinstance(resultado, dict) else {"resultado": resultado}
        p.recado = _recado_de(p)
        _gravar()
    if (p.conversa or "chat") == "chat":
        # ⭐ F4: a escrita aprovada no cartão do chat fica anotada para "transformar em fluxo".
        from . import historico as _historico
        _historico.anotar_feito(p.ferramenta, dict(p.entrada), resultado)
    return {"ok": True, "estado": "feita", "resultado": p.resultado}


def _recado_de(p: Pendencia) -> str:
    """O que o modelo precisa saber no próximo turno, em uma linha.

    ⚠️ Curto de propósito: isto entra no prompt do editor sem ele ter pedido, e cada
    palavra aqui é token que ele paga.
    """
    r = p.resultado
    if r.get("erro"):
        return f"{p.rotulo}: o editor autorizou, mas falhou — {r['erro']}"
    if p.ferramenta == "montar_corte":
        return (
            f"O editor autorizou e a sequência \"{r.get('sequencia')}\" foi montada na bin "
            f"{r.get('bin')} ({r.get('cortes')} cortes, {r.get('duracao_s')}s). Já está "
            f"feito — não monte de novo."
        )
    if p.ferramenta == "separar_falas":
        return (
            f"O editor autorizou e as falas da {r.get('cena')} foram separadas na bin "
            f"{r.get('bin')}: {r.get('timelines')} timelines, {r.get('trechos')} trechos. "
            f"Já está feito — não separe de novo."
        )
    if p.ferramenta == "editar_timeline":
        return (
            f"O editor autorizou e a cópia \"{r.get('sequencia_nova')}\" foi gravada na bin "
            f"{r.get('bin')}, com a original intacta"
            f"{', e carregada na Record' if r.get('carregada_na_record') else ''}. Já está "
            f"feito — não edite de novo."
        )
    return f"O editor autorizou, e {p.rotulo} foi feito."


# ── o que o próximo turno carrega ────────────────────────────────────────────


def recados(conversa: str = "chat") -> list[str]:
    """Colhe o que aconteceu enquanto o modelo DAQUELA conversa não estava olhando, e marca como contado."""
    with _trava:
        _carregar()
        delas = [p for p in _tudo.values() if p.recado and (p.conversa or "chat") == conversa]
        textos = [p.recado for p in delas]
        for p in delas:
            p.recado = ""
        if textos:
            _gravar()
    return textos


def descartar_recados(conversa: str = "chat") -> int:
    """A conversa recomeçou: os recados ainda não contados eram da anterior. Devolve quantos.

    ⚠️ A pendência continua (o cartão segue na tela e o clique ainda executa); some só o
    recado, que só faz sentido para o fio que viu a chamada ser negada.
    """
    with _trava:
        _carregar()
        n = 0
        for p in _tudo.values():
            if p.recado and (p.conversa or "chat") == conversa:
                p.recado = ""
                n += 1
        if n:
            _gravar()
    return n


def esquecer_tudo() -> None:
    """Só para os testes e para o `--limpar` do serviço."""
    global _carregado
    with _trava:
        _tudo.clear()
        _carregado = True
        try:
            os.unlink(arquivo())
        except OSError:
            pass
