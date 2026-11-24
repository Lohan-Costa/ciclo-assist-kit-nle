"""O canal do NÚCLEO: este módulo fala com o Media Composer PELO CICLO ASSIST, nunca direto.

⭐ Fase 4 do plano um app só, passo 4 (`docs/plano/2026-11-06-um-app-so.md` §4e; decisão do autor, 2026-11-07): só o
Assist abre conexão com o MC (`[::1]:9100`). Este objeto tem a FORMA de um `grpc.Channel` — `unary_unary`,
`unary_stream`, `stream_stream`, `close` — e é o que `MediaComposer.__enter__` guarda em `self._canal`. O pedido sai
serializado pelo serializador de sempre, vai a `POST /nucleo/avid/chamar` na 7824 com o token do Ciclo Assist, e a
resposta volta em bytes, lida pelo desserializador de sempre. Nada mais no `mcapi.py` muda.

⭐ O que se ganha: a pausa de 3 s depois de `LoadMobsIntoViewer` (carregar → consultar → fechar colados derruba o MC,
5 de 5 — banco) mora no Assist e vale para o app INTEIRO; antes valia dentro de cada processo, e o Sincronizar não a
tinha.

⚠️ ESTE ARQUIVO É O MESMO em `modulos/sincronizar/motor/avid/` e `modulos/conformar/plugins/media-composer/servico/avid/`
— um teste do Assist confere byte a byte. Mudou um, copie no outro.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ⛔⛔ Antes de QUALQUER `import grpc` (revisão de 2026-11-07, medido): com os "fork handlers" do gRPC ligados (o padrão
#    do grpcio 1.83), um subprocesso aberto (ffmpeg, ffprobe, `claude -p`, o app) enquanto canais de gRPC abrem e
#    fecham para o MC prende o fork por ~62 s SEGURANDO O GIL: o processo inteiro para, a porta não atende, e o
#    supervisor do app o mata ("parou de responder… processo vivo"). Reproduzido 3 de 3 (e no código real do Assist
#    contra o MC); com `0`, 0 de 3 em 40 mil forks. Nenhum filho nosso usa gRPC, então não há o que perder.
import os as _os

_os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")

import grpc

PORTA_DO_NUCLEO = 7824
HEADER = "X-Ciclo-Token"
#: A frase de quando o Assist não responde — dita no lugar de "o Media Composer está aberto?".
ASSIST_FORA = "O Ciclo Assist não está no ar — é ele que fala com o Media Composer."


class ErroDoNucleo(grpc.RpcError):
    """O erro do MC (ou do caminho até ele) com a cara de um erro do gRPC: o `_traduzir` de cada módulo segue igual.
    `frase`, quando houver, é o que dizer em vez da frase padrão do código."""

    def __init__(self, codigo: str, detalhe: str = "", frase: str = "") -> None:
        super().__init__(detalhe or codigo)
        self._codigo = getattr(grpc.StatusCode, codigo, grpc.StatusCode.UNKNOWN)
        self._detalhe = detalhe
        self.frase = frase

    def code(self):
        return self._codigo

    def details(self) -> str:
        return self._detalhe


class _TokenRecusado(Exception):
    """O núcleo respondeu 401: o token lido era de um Assist anterior (ele sorteia um a cada arranque)."""


def pasta_do_ciclo() -> Path:
    """A pasta de dados do Ciclo Assist (a do `plugin-token`) — a mesma conta de `cicloassist/servico/config.py`."""
    explicita = os.environ.get("CICLOASSIST_DADOS")
    if explicita:
        return Path(explicita)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "CicloAssist"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CicloAssist"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "cicloassist"


class CanalDoNucleo:
    """Um `grpc.Channel` de mentira que entrega cada chamada ao núcleo do Ciclo Assist. `modulo` vai no pedido."""

    def __init__(self, modulo: str) -> None:
        self.modulo = modulo

    def _pedir(self, rota: str, tipo: str, pedido: bytes, prazo: float) -> list[bytes]:
        # ⭐ 401 é reler o token e repetir UMA vez (revisão de 2026-11-07): o Assist sorteia um token a cada arranque, e
        #    um Assist religado entre a leitura do token e o envio fazia o editor ler "recusou (401)" — com a chamada
        #    seguinte funcionando. 401 quer dizer que o pedido NÃO foi executado: repetir não faz nada duas vezes.
        for tentativa in (1, 2):
            try:
                return self._pedir_uma_vez(rota, tipo, pedido, prazo)
            except _TokenRecusado as e:
                if tentativa == 2:
                    raise ErroDoNucleo("INTERNAL", f"o Ciclo Assist recusou o pedido ao Media Composer (401): {e}") \
                        from None
        raise AssertionError("inalcançável")

    def _pedir_uma_vez(self, rota: str, tipo: str, pedido: bytes, prazo: float) -> list[bytes]:
        try:
            token = (pasta_do_ciclo() / "plugin-token").read_text(encoding="utf-8").strip()
        except OSError:
            raise ErroDoNucleo("UNAVAILABLE", "sem o plugin-token do Ciclo Assist", ASSIST_FORA) from None
        corpo = json.dumps({"modulo": self.modulo, "rota": rota, "tipo": tipo, "prazo": prazo,
                            "pedido": base64.b64encode(pedido).decode("ascii")}).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{PORTA_DO_NUCLEO}/nucleo/avid/chamar", data=corpo,
                                     method="POST", headers={"Content-Type": "application/json", HEADER: token})
        try:
            # o prazo do MC mais folga: quem decide que estourou é o MC (DEADLINE_EXCEEDED), não o HTTP
            with urllib.request.urlopen(req, timeout=prazo + 15) as r:
                resposta = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                erro = json.loads(e.read() or b"{}").get("erro") or ""
            except ValueError:
                erro = ""
            if e.code == 401:
                raise _TokenRecusado(erro) from None
            raise ErroDoNucleo("INTERNAL", f"o Ciclo Assist recusou o pedido ao Media Composer ({e.code}): {erro}") \
                from None
        except (OSError, ValueError):
            raise ErroDoNucleo("UNAVAILABLE", "o Ciclo Assist não respondeu", ASSIST_FORA) from None
        if not resposta.get("ok"):
            raise ErroDoNucleo(str(resposta.get("codigo") or "UNKNOWN"), str(resposta.get("detalhe") or ""))
        return [base64.b64decode(b) for b in resposta.get("r") or []]

    def unary_unary(self, rota, request_serializer, response_deserializer):
        def chamar(req, timeout=None):
            return response_deserializer(self._pedir(rota, "unario", request_serializer(req), timeout or 20.0)[0])
        return chamar

    def unary_stream(self, rota, request_serializer, response_deserializer):
        def chamar(req, timeout=None):
            return iter([response_deserializer(b)
                         for b in self._pedir(rota, "fluxo", request_serializer(req), timeout or 20.0)])
        return chamar

    def stream_stream(self, rota, request_serializer, response_deserializer):
        """Só a reflection do servidor (o `rpcs()` do Conformar): um pedido, a primeira resposta."""
        def chamar(pedidos, timeout=None):
            primeiro = next(iter(pedidos))
            return iter([response_deserializer(b)
                         for b in self._pedir(rota, "reflexao", request_serializer(primeiro), timeout or 20.0)])
        return chamar

    def close(self) -> None:
        pass
