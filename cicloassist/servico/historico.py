"""O que a tela do CHAT mostrava, para redesenhá-la quando a página recomeça (2026-11-04).

⛔⛔ **Nasceu de uma queda.** O serviço caiu no meio de um `organizar_bins`, o supervisor o
religou e a conversa passou a sobreviver (`presenca.retomar`) — mas o app recarrega a página do
motor ao religar, e a tela voltava com o aviso "esta conversa continua de antes" sobre um chat
VAZIO, com as sugestões de boas-vindas. O editor não via o que tinha pedido, o que o modelo
respondeu nem em que ferramenta o turno parou: "continue" era um tiro no escuro. Vale também
para o Reload do painel, que sempre apagou a tela com o fio vivo.

⭐ Um turno = uma entrada: a pergunta do editor (o que ele DIGITOU, sem o preâmbulo do arrasto
nem recados), as ferramentas na ordem (a linha `resumo` que o painel já mostra), o texto da
resposta e como acabou. ⭐ A entrada é gravada ao COMEÇAR e a cada ferramenta — o turno que
morre com o processo fica `correndo` no disco, e quem lê depois sabe que ele foi interrompido.

⭐ E as ESCRITAS que deram certo (`anotar_feito`), a matéria-prima do "transformar em fluxo" (F4).

⚠️ Só o chat (a aba Fluxos tem o quadro, que já se redesenha). Na pasta de dados, ao lado do
`estado.json`: é o mesmo texto que o CLI já guarda na transcrição dele. Esquecido junto com a
conversa (Limpar, visita nova) — e quem lê só o mostra quando o fio continua (`rotas._fio`).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

log = logging.getLogger("cicloassist.servico.historico")

#: Turnos guardados. A tela é para reconhecer onde se estava, não para reler o dia.
TETO_DE_TURNOS = 30
#: Caracteres por texto (pergunta ou resposta). Resposta de chat é curta; isto só segura o raro.
TETO_DE_TEXTO = 12_000
#: Ferramentas por turno.
TETO_DE_FERRAMENTAS = 40
#: Escritas guardadas para o "transformar em fluxo" (o executor aceita até 30 passos).
TETO_DE_FEITOS = 30
#: Gravar o texto que chega aos pedaços no máximo a cada N segundos (as ferramentas gravam na hora).
RESPIRO_S = 2.0

_trava = threading.Lock()


def _arquivo():
    from .config import pasta
    return pasta() / "conversa.json"


def _ler_tudo() -> dict:
    try:
        dado = json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dado if isinstance(dado, dict) else {}


def _lista(dado: dict, chave: str) -> list[dict]:
    return [t for t in (dado.get(chave) or []) if isinstance(t, dict)]


def ler() -> list[dict]:
    """Os turnos guardados, do mais antigo ao mais novo. Arquivo ruim é lista vazia, nunca exceção."""
    return _lista(_ler_tudo(), "turnos")


def _gravar(turnos: list[dict] | None = None, feitos: list[dict] | None = None) -> None:
    """⚠️ Chamar com a `_trava` na mão: lê o que não muda e regrava o arquivo inteiro."""
    try:
        atual = _ler_tudo()
        dado = {"turnos": (turnos if turnos is not None else _lista(atual, "turnos"))[-TETO_DE_TURNOS:],
                "feitos": (feitos if feitos is not None else _lista(atual, "feitos"))[-TETO_DE_FEITOS:]}
        destino = _arquivo()
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")
        tmp.replace(destino)
    except Exception:  # noqa: BLE001 — guardar a tela nunca derruba um turno
        log.debug("não consegui gravar a conversa", exc_info=True)


# ── F4: o que o chat FEZ, para virar fluxo ────────────────────────────────────


def anotar_feito(op: str, args: dict, resultado: Any) -> None:
    """⭐ Uma ESCRITA que rodou e deu certo nesta conversa do chat — pelo automático (MCP) ou pelo
    clique no cartão (pendência). É a matéria-prima do "transformar em fluxo" (F4): a sequência de
    ferramentas com os argumentos, e o resultado (os campos de texto) para ligar um passo ao seguinte.
    ⚠️ Resultado com `ok: false` ou `erro` não é feito: a falha não entra numa receita."""
    if isinstance(resultado, dict) and (resultado.get("ok") is False or resultado.get("erro")):
        return
    saida = {k: v for k, v in resultado.items() if isinstance(v, (str, int, float, bool))}         if isinstance(resultado, dict) else {}
    with _trava:
        feitos = _lista(_ler_tudo(), "feitos")
        feitos.append({"op": op, "args": args, "saida": saida, "em": time.time()})
        _gravar(feitos=feitos)


def feitos() -> list[dict]:
    return _lista(_ler_tudo(), "feitos")


def esquecer() -> None:
    with _trava:
        try:
            _arquivo().unlink()
        except OSError:
            pass


class Registro:
    """O turno em andamento, gravado enquanto acontece."""

    def __init__(self, turno_id: str, pergunta: str) -> None:
        self.dado: dict = {"id": turno_id, "editor": (pergunta or "")[:TETO_DE_TEXTO],
                           "ferramentas": [], "resposta": "", "erro": "",
                           "estado": "correndo", "em": time.time()}
        self._gravado_em = 0.0
        self._depois_de_ferramenta = False
        self.gravar()

    def gravar(self) -> None:
        with _trava:
            turnos = [t for t in ler() if t.get("id") != self.dado["id"]]
            turnos.append(dict(self.dado))
            _gravar(turnos=turnos)
        self._gravado_em = time.monotonic()

    def evento(self, tipo: str, dado: dict) -> None:
        """Um evento do motor (os mesmos que vão ao painel)."""
        if tipo == "texto":
            # ⚠️ A mesma emenda do painel: texto depois de ferramenta é parágrafo novo.
            atual = self.dado["resposta"]
            if self._depois_de_ferramenta and atual and not atual[-1:].isspace():
                atual += "\n\n"
            self._depois_de_ferramenta = False
            self.dado["resposta"] = (atual + str(dado.get("texto") or ""))[:TETO_DE_TEXTO]
            if time.monotonic() - self._gravado_em >= RESPIRO_S:
                self.gravar()
        elif tipo == "ferramenta":
            self._depois_de_ferramenta = True
            if len(self.dado["ferramentas"]) < TETO_DE_FERRAMENTAS:
                self.dado["ferramentas"].append(str(dado.get("resumo") or dado.get("nome") or "")[:300])
            self.gravar()
        elif tipo == "erro":
            self.dado["erro"] = str(dado.get("mensagem") or "")[:2000]
        elif tipo == "cancelado":
            self.dado["estado"] = "interrompido"

    def guardar_perguntas(self, cartao: dict) -> None:
        """⭐ O modelo não repete as perguntas em texto: sem isto, um Reload apagaria a única cópia delas."""
        self.dado["perguntas"] = cartao
        self.gravar()

    def terminar(self) -> None:
        if self.dado["estado"] == "correndo":
            self.dado["estado"] = "erro" if self.dado["erro"] else "pronto"
        self.gravar()


def para_a_tela(vivo: str = "") -> list[dict]:
    """Os turnos como o painel os desenha. ⭐ Um `correndo` que não é o turno vivo (`vivo`) morreu com
    o processo: vira `caiu`, e a tela diz que o serviço caiu ali."""
    saida = []
    for t in ler():
        t = dict(t)
        if t.get("estado") == "correndo" and t.get("id") != vivo:
            t["estado"] = "caiu"
        saida.append(t)
    return saida
