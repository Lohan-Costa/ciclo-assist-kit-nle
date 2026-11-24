"""O servidor HTTP local do plugin do Media Composer.

Stdlib de propósito (`ThreadingHTTPServer`): menos dependência para o PyInstaller
empacotar, e SSE sai da stdlib sem framework nenhum.

⚠️ **A rota é o caminho EXATO, nunca um prefixo.** Lição do Órbita: com roteamento por
prefixo, `/healthFOO` e `/health../x` caem em `/health`, e a ORDEM das rotas vira parte
da lógica — uma rota passa a poder engolir outra conforme o registro muda. Comparar o
caminho exato apaga a classe inteira de problema.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .portao import CABECALHO_TOKEN, PORTA, ROTA_UI, portao

log = logging.getLogger("delapraca.api")

# Onde mora a UI que este servidor entrega ao painel.
DIR_UI = Path(__file__).resolve().parent.parent / "ui"

# {(metodo, rota) -> handler(ctx) -> (status, corpo)}
_ROTAS: dict[tuple[str, str], callable] = {}


def rota(metodo: str, caminho: str):
    """Registra um handler. O caminho é comparado por igualdade, não por prefixo."""

    def registrar(fn):
        _ROTAS[(metodo.upper(), caminho)] = fn
        return fn

    return registrar


class Contexto:
    """O que um handler recebe: a requisição já lida e validada."""

    __slots__ = ("metodo", "rota", "query", "corpo", "servico")

    def __init__(self, metodo, rota, query, corpo, servico):
        self.metodo = metodo
        self.rota = rota
        self.query = query
        self.corpo = corpo
        self.servico = servico

    def json(self) -> dict:
        """O corpo como JSON, ou `{}`. Corpo malformado é `{}`, não exceção — quem
        precisa de um campo valida o campo."""
        if not self.corpo:
            return {}
        try:
            valor = json.loads(self.corpo)
        except (ValueError, UnicodeDecodeError):
            return {}
        return valor if isinstance(valor, dict) else {}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DeLaPraCa"
    sys_version = ""  # não anunciar a versão do Python

    # ── plumbing ────────────────────────────────────────────────────────────

    def log_message(self, formato, *args):  # noqa: N802 (assinatura da stdlib)
        log.debug("%s %s", self.address_string(), formato % args)

    def _responder(self, status: int, corpo: bytes, tipo: str, *, cors: bool = True):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        # Sem `Access-Control-Allow-Origin: *`, nunca. O painel é same-origin depois de
        # carregado; o loader `avpi://` recebe a origem exata que apresentou.
        if cors:
            origem = self.headers.get("Origin")
            if origem and origem.strip().lower() == "avpi://":
                self.send_header("Access-Control-Allow-Origin", "avpi://")
        # Nada aqui deve ser cacheado: o painel fica aberto por horas e o estado muda.
        self.send_header("Cache-Control", "no-store")
        # Higiene de navegador para uma superfície que roda numa webview.
        self.send_header("X-Content-Type-Options", "nosniff")
        # Guia de Desenvolvimento Seguro §5.
        #
        # ⚠️⚠️ `sameorigin`, **não** `deny`, e a razão é de risco assimétrico. O painel
        # chega aqui por um `location.replace` do loader `avpi://`, e **não temos como
        # afirmar** que a webview do Media Composer hospeda esse documento no topo — se
        # ela o emoldurar, `deny` faz o navegador RECUSAR a página e o editor recebe um
        # painel EM BRANCO, sem mensagem: o loader já navegou e não tem como reportar.
        #
        # Do outro lado da balança, clickjacking num serviço de loopback que já exige
        # `Origin`/`Sec-Fetch-Site` (ADR 0007) é ganho marginal. Entre um risco marginal
        # e uma interface morta, escolhe-se o risco — e anota-se o que falta medir.
        #
        # ⭐ `frame-ancestors` cobre o caso de verdade: em Chromium ele PRECEDE o
        # `X-Frame-Options`, e `avpi:` deixa passar exatamente a moldura que seria
        # legítima (a do próprio painel), sem abrir para http(s) nenhum.
        self.send_header("X-Frame-Options", "sameorigin")
        # ⚠️ CSP restritiva porque a UI é 100% local e não busca NADA de fora: sem isto,
        # uma injeção que escapasse do `escapar()` teria para onde exfiltrar. `'self'`
        # cobre os três arquivos servidos; `img-src data:` só para os ícones embutidos.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'self' avpi:; "
            "base-uri 'none'; form-action 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, status: int, valor, *, cors: bool = True):
        corpo = json.dumps(valor, ensure_ascii=False).encode("utf-8")
        self._responder(status, corpo, "application/json; charset=utf-8", cors=cors)

    # ── o ciclo de uma requisição ───────────────────────────────────────────

    def do_OPTIONS(self):  # noqa: N802
        self._responder(204, b"", "text/plain")

    def do_GET(self):  # noqa: N802
        self._atender("GET")

    def do_POST(self):  # noqa: N802
        self._atender("POST")

    def _atender(self, metodo: str):
        url = urlparse(self.path)
        caminho = url.path

        tamanho = self.headers.get("Content-Length")
        corpo_len = int(tamanho) if (tamanho or "").isdigit() else None

        # O portão vem antes de ler o corpo: quem não se identificou não merece que a
        # gente sequer gaste memória com o que mandou.
        recusa = portao(
            host=self.headers.get("Host"),
            origin=self.headers.get("Origin"),
            sec_fetch_site=self.headers.get("Sec-Fetch-Site"),
            corpo_len=corpo_len,
            rota=caminho,
            token=self.headers.get(CABECALHO_TOKEN),
            token_esperado=getattr(self.server.servico, "token", None),
            porta=self.server.server_port,     # a porta REAL do socket (ficha B033: não a constante)
        )
        if recusa:
            motivo, status = recusa
            log.info("recusado %s %s: %s", metodo, caminho, motivo)
            # Uma página web não lê nem o motivo da recusa.
            self._json(status, {"erro": motivo}, cors=(motivo != "origem não permitida"))
            return

        corpo = self.rfile.read(corpo_len) if corpo_len else b""

        handler = _ROTAS.get((metodo, caminho))
        if handler is None:
            self._json(404, {"erro": "rota desconhecida"})
            return

        ctx = Contexto(metodo, caminho, url.query, corpo, self.server.servico)
        try:
            resultado = handler(ctx)
        except Exception as e:  # noqa: BLE001 — um handler nunca derruba o servidor
            log.exception("erro em %s %s", metodo, caminho)
            self._json(500, {"erro": f"{type(e).__name__}: {e}"})
            return

        # Um handler devolve:
        #   ("sse", fn)          → fluxo de eventos, fn() devolve o estado a cada tique
        #   (status, bytes, tipo) → arquivo
        #   (status, valor)      → JSON
        if resultado and resultado[0] == "sse":
            self._sse(resultado[1])
        elif len(resultado) == 3:
            status, dados, tipo = resultado
            self._responder(status, dados, tipo)
        else:
            status, valor = resultado
            self._json(status, valor)

    def _sse(self, ler_estado, intervalo: float = 0.4, teto_s: float = 600.0):
        """Server-Sent Events, da stdlib.

        Cada evento carrega o estado **inteiro**, não um delta: um cliente que se
        reconecta reencontra a situação sem precisar de histórico.

        `Content-Length` não existe aqui, então o keep-alive do HTTP/1.1 não serve —
        a conexão fecha no fim, e é isso que diz ao `EventSource` que acabou.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        limite = time.monotonic() + teto_s
        anterior = None
        try:
            while time.monotonic() < limite:
                estado = ler_estado()
                # Só emite quando algo muda de verdade.
                # ⚠️ `decorrido` fica FORA da comparação: ele muda a cada tique, e com
                # ele dentro o "só quando muda" nunca se aplicava — o painel recebia um
                # evento a cada 0,4 s mesmo parado, e o relógio ficava sendo o único
                # motivo. O tempo viaja de carona no próximo evento de verdade.
                chave = {k: v for k, v in estado.items() if k != "decorrido"}
                if chave != anterior:
                    anterior = chave
                    corpo = json.dumps(estado, ensure_ascii=False)
                    self.wfile.write(f"data: {corpo}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    if estado.get("fase") in ("feito", "erro") and not estado.get("ocupada"):
                        break
                time.sleep(intervalo)
        except (BrokenPipeError, ConnectionResetError):
            # O painel fechou ou navegou. Não é erro: o trabalho segue rodando, e a
            # próxima conexão reencontra o estado.
            log.debug("cliente SSE desconectou")


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True

    # ⚠️⚠️ **`SO_REUSEADDR` não quer dizer a mesma coisa nos dois sistemas**, e o padrão
    # do `http.server` (`True`) é a escolha ERRADA no Windows.
    #
    # No Windows, com a opção ligada, um SEGUNDO `bind()` numa porta VIVA é aceito em
    # silêncio: o processo novo anuncia que subiu, e quem continua respondendo é o
    # velho. Desligada, o bind é recusado com `WinError 10048` — que é o que queremos,
    # porque é um erro que se lê. No POSIX o segundo bind é recusado de qualquer jeito,
    # e manter a opção ligada lá evita a espera do `TIME_WAIT` a cada reinício, que num
    # serviço de bancada é reinício o tempo todo.
    #
    # ⭐ Aqui isso não é hipótese: até 2026-09-16 o *Assist anterior* servia esta MESMA
    # porta 7823 (hoje ele está na 7830). Com a opção ligada, subir os dois deixava o
    # painel conversando com o serviço errado, sem nada na tela acusando. O mesmo
    # conserto já está no Ciclo Assist e no Assist anterior; este era o que faltava.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, endereco, handler, servico):
        self.servico = servico
        super().__init__(endereco, handler)

    def handle_error(self, request, client_address):
        """Cliente que sumiu não é defeito — e no Windows ele GRITA.

        ⚠️ **Diferença de sistema operacional, não do nosso código.** Quando o outro
        lado fecha uma conexão *keep-alive*, o POSIX devolve leitura vazia (EOF) e o
        `socketserver` segue calado; o Windows levanta
        `ConnectionResetError [WinError 10054]`, que sobe até o `handle_error` padrão e
        **despeja um traceback completo no stderr**.

        Isso acontece a cada conexão encerrada — e o painel bate `/health` de 4 em 4
        segundos. Sem este método o log vira uma parede de tracebacks idênticos, e o
        primeiro efeito prático é que um erro DE VERDADE passa despercebido no meio.
        """
        import sys
        excecao = sys.exc_info()[1]
        if isinstance(excecao, (ConnectionResetError, BrokenPipeError,
                                ConnectionAbortedError)):
            log.debug("cliente %s desconectou (%s)", client_address[0],
                      type(excecao).__name__)
            return
        super().handle_error(request, client_address)

    def server_bind(self):
        """⚠️ Sem `getfqdn()`. É por isso que este método existe.

        O `server_bind` do `HTTPServer` chama `socket.getfqdn(host)` só para preencher
        `server_name`, e isso é uma **resolução DNS reversa**. Numa máquina sem DNS
        respondendo — a estação de edição numa rede de produção é exatamente esse caso
        — ela espera o timeout do resolvedor: **medido em 35 segundos** nesta máquina,
        antes de o servidor aceitar a primeira conexão.

        O sintoma engana: o processo sobe, o log diz que está vivo, e o painel fica
        "procurando o serviço" por meio minuto. Como `server_name` só serve para montar
        URLs absolutas que nunca emitimos, o valor literal resolve.
        """
        import socketserver

        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def servir_arquivo_da_ui(nome: str) -> tuple[int, bytes, str]:
    """Entrega um arquivo de `ui/`, e só de lá.

    `Path.resolve()` nos dois lados + `is_relative_to` fecha o caminho: `../`,
    caminho absoluto e symlink apontando para fora não escapam do diretório.
    """
    alvo = (DIR_UI / nome).resolve()
    if not alvo.is_relative_to(DIR_UI.resolve()) or not alvo.is_file():
        return 404, b'{"erro":"nao encontrado"}', "application/json; charset=utf-8"
    tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
    if tipo.startswith(("text/", "application/javascript")):
        tipo += "; charset=utf-8"
    return 200, alvo.read_bytes(), tipo


def iniciar(servico, porta: int = PORTA) -> tuple[_Servidor, threading.Thread]:
    """Sobe o servidor em `127.0.0.1`. Nunca em `0.0.0.0` — o bind é a primeira tranca,
    e é a única que não depende de nós acertarmos o resto."""
    from . import rotas  # noqa: F401 — o import é o que registra as rotas

    servidor = _Servidor(("127.0.0.1", porta), _Handler, servico)
    thread = threading.Thread(target=servidor.serve_forever, name="http", daemon=True)
    thread.start()
    log.info("servidor no ar em http://127.0.0.1:%d (UI em %s)", porta, ROTA_UI)
    return servidor, thread
