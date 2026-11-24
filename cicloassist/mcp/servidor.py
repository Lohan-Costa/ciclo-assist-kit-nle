"""O protocolo MCP: JSON-RPC 2.0 traduzido em chamadas às nossas ferramentas.

⚠️ **Aqui não há HTTP.** Este módulo é uma função pura de mensagem para resposta; quem
serve é `servico/rotas.py`, na rota `/mcp/<segredo>` do mesmo servidor que serve o painel
e orquestra o Claude (ADR 0002 e ADR 0005).

A separação não é estética: é o que permite testar o protocolo inteiro sem abrir socket,
sem porta ocupada e sem processo pendurado quando um teste falha.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any

from .. import nle as _nle
from .registro import FERRAMENTAS, do_nle

log = logging.getLogger("cicloassist.mcp")

# A versão do protocolo que implementamos. O cliente manda a dele no `initialize`;
# devolvemos a nossa e ele decide.
PROTOCOLO = "2025-06-18"

NOME = "ciclo"
VERSAO = "0.1.0"

#: ⭐ O que um modelo LOCAL vê (bancada do modelo mínimo, 2026-11-02): com as ~40 ferramentas o
#: Qwen 8B confundiu converter com `conformar_no_resolve` e inventou caminhos, e nenhum dos três
#: locais achou a receita. A missão de fluxo precisa só disto — mais o portão (`pedir_confirmacao`).
#: ⚠️ Em avaliação: um modelo local que passar na prova ganha as outras ferramentas uma a uma, medidas.
ESSENCIAIS_DO_LOCAL = frozenset({"listar_receitas", "executar_fluxo", "continuar_fluxo",
                                 "estado_do_projeto", "pedir_confirmacao"})


#: ⭐⭐ O que o CHAT não dispara (decisão do autor, 2026-11-03, `docs/plano/2026-11-03-chat-e-fluxos.md`):
#: o chat é o pedido imediato, com o editor olhando, feito ferramenta a ferramenta; o FLUXO (receita,
#: executor no fundo, o editor podendo sair da ilha) é da aba Fluxos. Com `executar_fluxo` à vista e a
#: descrição dele mandando "não chame as operações uma a uma", o chat procurava receita para tudo, e
#: pedido que nenhuma receita cobria ficava sem saída. ⚠️ `listar_receitas` FICA: é leitura, e serve
#: para o chat SUGERIR o fluxo pronto (o autor: "pode sugerir"), nunca para rodá-lo.
#: ⛔ `gerar_midia_de_teste` é do PILOTO (o laboratório de desenvolvimento), não do produto (autor,
#: 2026-11-03): no teste da D01 o chat a chamou sem ninguém pedir, ao reconhecer a mídia sintética pelo
#: nome. Fica registrada para o executor, as receitas do laboratório e os spikes.
FORA_DO_CHAT = frozenset({"executar_fluxo", "continuar_fluxo", "gerar_midia_de_teste", "propor_fluxo", "propor_mudanca_no_node", "perguntar_ao_editor", "confirmar_na_memoria"})


#: ⭐⭐ O que a conversa da aba FLUXOS vê (2026-11-03): as ferramentas de fluxo e de receita, e as de
#: LEITURA que servem para preencher um plano. ⛔ Nenhuma escrita solta: ali quem executa é o executor,
#: pelo plano que o editor aprovou num cartão só.
DOS_FLUXOS = frozenset({
    "listar_receitas", "executar_fluxo", "continuar_fluxo", "salvar_receita", "pedir_confirmacao",
    "estado_do_projeto", "listar_bins", "listar_itens_da_bin",
    "projeto_do_premiere", "listar_bins_do_premiere", "arvore_do_premiere",
    "ler_arquivo", "o_que_quer_dizer",
})

#: ⭐ O chat da janela Fluxos e Agentes: só propor e consultar. Quem grava é o botão Salvar, e quem executa é o editor.
DA_OFICINA = frozenset({"listar_receitas", "propor_fluxo", "propor_mudanca_no_node", "o_que_quer_dizer", "pedir_confirmacao"})

_papel = threading.local()


@contextmanager
def com_papel(papel: str):
    """O papel da conversa que fez ESTE pedido MCP — dito pelo endereço (`rotas.url_do_mcp`)."""
    antes = getattr(_papel, "valor", "chat")
    _papel.valor = papel
    try:
        yield
    finally:
        _papel.valor = antes


def papel() -> str:
    return getattr(_papel, "valor", "chat")


def _cabe_no_papel(nome: str, qual: str) -> bool:
    if qual == "oficina":
        return nome in DA_OFICINA
    return nome in DOS_FLUXOS if qual == "fluxos" else nome not in FORA_DO_CHAT


def visiveis(qual: str | None = None) -> list:
    """As ferramentas que o modelo do turno VÊ: as do editor no papel da conversa, e só as essenciais
    para um modelo local."""
    from ..servico import config as _config
    qual = qual or papel()
    lista = [f for f in do_nle(_nle.atual()) if _cabe_no_papel(f.nome, qual)]
    if _config.e_local(_config.modelo_guardado()):
        lista = [f for f in lista if f.nome in ESSENCIAIS_DO_LOCAL]
    return lista


#: Quantas vezes a MESMA chamada (nome + argumentos) pode se repetir num turno antes de a
#: resposta virar um aviso.
#:
#: ⛔⛔ MEDIDO em campo (2026-09-17, Premiere, pedido de tirar clipes das pastas de cartão):
#: o modelo chamou `listar_itens_do_premiere` com `apenas_selecionados` em onze bins, recebeu
#: `quantidade: 0` em todas — nada estava selecionado —, e repetiu a MESMA volta quatro
#: vezes: 46 chamadas, 20 minutos, nenhuma linha de resposta ao editor. A resposta certa já
#: é melhor (a ferramenta agora explica o zero), mas a rede tem de existir para qualquer
#: ferramenta: repetir uma pergunta cuja resposta não mudou não é trabalho, é laço.
REPETICOES_ATE_AVISAR = 3

#: Sem turno do Ciclo Assist (um cliente MCP de fora), as repetições contam dentro desta janela.
JANELA_SEM_TURNO_S = 120

_repeticoes: dict[tuple[str, str], int] = {}
_turno_das_repeticoes: str = ""


def _e_laco(nome: str, argumentos: dict[str, Any]) -> bool:
    """Esta chamada já veio igual demais neste turno?"""
    global _turno_das_repeticoes
    from ..servico import turno as _turno

    atual = _turno.atual()
    # ⛔ MEDIDO (2026-11-19, o app do Claude pela ponte `tools/ponte_mcp_stdio.py`): sem turno do Ciclo Assist a marca era
    #   sempre "", a conta nunca zerava e, depois de 3 chamadas iguais NA SESSÃO INTEIRA, a leitura ficava recusada
    #   até reiniciar o serviço (`estado_do_projeto`, que o modelo repete esperando o MC abrir). Sem turno, a conta
    #   vale por janela de tempo.
    marca = getattr(atual, "id", "") if atual else f"sem-turno-{int(time.monotonic() // JANELA_SEM_TURNO_S)}"
    if marca != _turno_das_repeticoes:
        _repeticoes.clear()
        _turno_das_repeticoes = marca
    # ⛔⛔ O argumento INTEIRO, por hash — nunca um prefixo. Com `[:2000]`, três pedidos
    #   DIFERENTES de `separar_falas` (12,7 mil caracteres cada, corrigidos um a um depois
    #   da conferência) chegaram ao `pedir_confirmacao` com o mesmo começo e viraram "o mesmo
    #   pela 3ª vez" (2026-10-22, ensaio da C07): o modelo, barrado, passou a CORTAR falas.
    texto = json.dumps(argumentos, ensure_ascii=False, sort_keys=True)
    chave = (str(nome), hashlib.sha256(texto.encode("utf-8")).hexdigest())
    _repeticoes[chave] = _repeticoes.get(chave, 0) + 1
    return _repeticoes[chave] >= REPETICOES_ATE_AVISAR


def _erro(id_: Any, codigo: int, mensagem: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": codigo, "message": mensagem}}


def _ok(id_: Any, resultado: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": resultado}


def responder(mensagem: dict[str, Any]) -> dict[str, Any] | None:
    """Traduz uma mensagem JSON-RPC do MCP na resposta, ou `None` se for notificação.

    ⚠️ Notificação (mensagem **sem `id`**) não tem resposta — devolver uma quebra o
    cliente. É a regra do JSON-RPC que mais se esquece.
    """
    metodo = mensagem.get("method")
    id_ = mensagem.get("id")
    tem_id = "id" in mensagem

    if metodo == "initialize":
        return _ok(id_, {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": NOME, "version": VERSAO},
        })

    if metodo in ("notifications/initialized", "notifications/cancelled"):
        return None

    if metodo == "ping":
        return _ok(id_, {})

    if metodo == "tools/list":
        return _ok(id_, {"tools": [f.como_mcp() for f in visiveis()]})

    if metodo == "tools/call":
        params = mensagem.get("params") or {}
        nome = params.get("name")
        argumentos = params.get("arguments") or {}
        ferramenta = FERRAMENTAS.get(nome)
        if ferramenta is not None and _nle.atual() not in ferramenta.nles:
            # ⚠️ Fio retomado de uma conversa do outro editor pode lembrar o nome.
            return _ok(id_, {
                "content": [{"type": "text", "text":
                             f"{nome} não existe numa conversa do {_nle.nome()}."}],
                "isError": True,
            })
        if ferramenta is not None and not _cabe_no_papel(nome, papel()):
            # ⚠️ Fio de antes de 2026-11-03 pode lembrar o nome.
            texto = (f"{nome} não existe no chat: fluxos rodam na aba Fluxos. Faça o pedido aqui passo "
                     "a passo com as ferramentas, ou sugira ao editor o fluxo pronto."
                     if papel() == "chat" else
                     f"{nome} não existe na aba Fluxos: aqui você monta o plano e o executor o roda "
                     "(executar_fluxo). Uma ação solta, imediata, é pedido para a aba Assistir.")
            return _ok(id_, {"content": [{"type": "text", "text": texto}], "isError": True})
        if ferramenta is None:
            return _erro(id_, -32602, f"ferramenta desconhecida: {nome!r}")
        if not ferramenta.escreve and _e_laco(nome, argumentos):
            # ⛔ Só leitura: repetir uma ESCRITA é outro assunto (o portão já a segura), e
            #   um lote legítimo pode repetir a mesma escrita com argumentos iguais.
            log.warning("laço: %s chamada %d vezes com os mesmos argumentos neste turno",
                        nome, REPETICOES_ATE_AVISAR)
            return _ok(id_, {
                "content": [{"type": "text", "text":
                             f"Você já chamou {nome} com estes mesmos argumentos "
                             f"{REPETICOES_ATE_AVISAR} vezes neste turno, e a resposta não "
                             f"mudou — ela não vai mudar sozinha. Pare de repetir: use o que "
                             f"já recebeu, tente outro caminho, ou diga ao editor o que está "
                             f"faltando e por quê."}],
                "isError": True,
            })
        try:
            conteudo = ferramenta.funcao(**argumentos)
        except TypeError as e:
            # ⭐ Argumento errado é erro de CHAMADA, e o modelo se corrige sozinho se
            # souber o que faltou — por isso volta como `isError` no resultado, não como
            # erro de protocolo. Erro de protocolo o modelo não vê; ele só vê a falha.
            return _ok(id_, {
                "content": [{"type": "text", "text": f"argumentos inválidos: {e}"}],
                "isError": True,
            })
        except Exception as e:
            log.exception("ferramenta %s falhou", nome)
            return _ok(id_, {
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                "isError": True,
            })
        if ferramenta.escreve and papel() == "chat":
            # ⭐ F4: a escrita que o chat fez (pelo automático) fica anotada para "transformar em fluxo".
            from ..servico import historico as _historico
            _historico.anotar_feito(nome, dict(argumentos), conteudo)
        return _ok(id_, {"content": normalizar(conteudo), "isError": False})

    if not tem_id:
        return None
    return _erro(id_, -32601, f"método não suportado: {metodo!r}")


def normalizar(resultado: Any) -> list[dict[str, Any]]:
    """Põe o retorno de uma ferramenta na forma de conteúdo do MCP.

    ⭐ O caso que importa para este produto é o de IMAGEM: a identificação visual devolve
    frames, e eles voltam como `{"type": "image", ...}` no resultado da ferramenta. É
    assim que o Claude vira o modelo de visão do produto sem existir modelo de visão
    local — e por isso um bloco já formado atravessa intacto em vez de virar JSON.
    """
    if isinstance(resultado, list) and all(
        isinstance(i, dict) and "type" in i for i in resultado
    ):
        return resultado
    if isinstance(resultado, dict) and "type" in resultado:
        return [resultado]
    if isinstance(resultado, str):
        return [{"type": "text", "text": resultado}]
    return [{"type": "text", "text": json.dumps(resultado, ensure_ascii=False, indent=2)}]
