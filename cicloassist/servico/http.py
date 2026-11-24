"""O serviço local: um servidor HTTP que acumula os três papéis do produto.

Ele serve o painel, expõe as ferramentas MCP e orquestra o subprocesso do Claude. Os
três num processo só, de propósito — é o que faz o servidor MCP ter a ponte gRPC com o
Media Composer já viva quando o modelo chama uma ferramenta (ADR 0002).

Stdlib: `ThreadingHTTPServer`. Menos dependência para o PyInstaller empacotar, e SSE sai
daqui sem framework nenhum.

## O roteamento

⚠️ **A rota é o caminho EXATO, nunca um prefixo.** Com roteamento por prefixo, `/saudeX`
e `/saude/../x` caem em `/saude`, e a ORDEM do registro vira parte da lógica — uma rota
passa a poder engolir outra conforme o registro muda. Comparar por igualdade apaga a
classe inteira de problema. A única exceção é `/static/`, que é servida por um handler
que valida o caminho ele mesmo.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, unquote, urlparse

from . import presenca as _presenca

log = logging.getLogger("cicloassist.servico")

# ⚠️ 7824, e NÃO 7823. O Assist anterior e o De Lá Pra Cá usaram a mesma 7823, e o painel
# antigo de um conversava com o serviço do outro — falha invisível, porque tudo responde,
# só que o app errado. Um produto, uma porta.
PORTA = 7824

# Onde mora a interface que este serviço entrega ao painel.
DIR_PAINEL = Path(__file__).resolve().parent.parent / "painel"

#: Sorteado a cada arranque. Vai no caminho da rota do MCP e é entregue SÓ ao
#: subprocesso do Claude, dentro do `--mcp-config`. Ver ADR 0005, defesa 4.
#: ⭐ `CICLOASSIST_SEGREDO_MCP` (2026-11-20): o serviço SEM JANELA (`tools/servico_sem_janela.py`) sorteia o segredo
#: ele mesmo e o entrega à ponte de um cliente MCP de fora (o app do Claude, `tools/ponte_mcp_stdio.py`), num
#: arquivo só do usuário. Curto demais é ignorado: um segredo fraco abriria as ferramentas de escrita a qualquer
#: processo da máquina.
_SEGREDO_DE_FORA = os.environ.get("CICLOASSIST_SEGREDO_MCP", "")
SEGREDO_DO_MCP = (_SEGREDO_DE_FORA if len(_SEGREDO_DE_FORA) >= 32 and _SEGREDO_DE_FORA.replace("-", "").replace(
    "_", "").isalnum() else secrets.token_urlsafe(24))


class CorpoInvalido(ValueError):
    """O corpo do pedido não é JSON UTF-8. É erro do CLIENTE, não do serviço."""


@dataclass
class Pedido:
    metodo: str
    caminho: str
    cabecalhos: dict[str, str]
    corpo: bytes = b""
    #: ⭐ A query string, já decodificada — `?chave=abc&frame=12` vira
    #: `{"chave": "abc", "frame": "12"}`. Só o PRIMEIRO valor de cada nome: repetido é
    #: ambiguidade, e uma rota que escolhesse "o último" é uma rota que muda de resposta
    #: conforme a ordem.
    #: ⚠️ Nunca entra no casamento de rota — `ROTAS` é caminho EXATO, e por isso `/quadro`
    #: e `/quadro?x=1` são a mesma rota (o `urlparse` já separou os dois).
    consulta: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        """O corpo como JSON, ou `CorpoInvalido` com o motivo.

        ⚠️ **Decodifica UTF-8 explicitamente, e é por isso que existe.** O `json.loads`
        sobre bytes adivinha a codificação e levanta `UnicodeDecodeError` — que **não é**
        `JSONDecodeError` e por isso escapa do `except` óbvio de quem chama. Medido em
        2026-09-10 com um cliente que mandou cp1252: a rota estourou e o serviço
        respondeu `500 falha interna`, escondendo um erro que é do cliente.

        O painel manda UTF-8 sempre (`JSON.stringify` + `fetch`), então isto é defesa de
        fronteira, não caminho normal — e fronteira que responde 500 para entrada torta
        é fronteira que mente sobre de quem é a culpa.
        """
        if not self.corpo:
            return None
        try:
            texto = self.corpo.decode("utf-8")
        except UnicodeDecodeError as e:
            raise CorpoInvalido(f"o corpo não está em UTF-8: {e}") from None
        try:
            return json.loads(texto)
        except json.JSONDecodeError as e:
            raise CorpoInvalido(f"JSON inválido: {e}") from None

    def cabecalho(self, nome: str) -> str:
        return self.cabecalhos.get(nome.lower(), "")


@dataclass
class Resposta:
    status: int = 200
    corpo: bytes = b""
    tipo: str = "application/json"
    extras: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def de_json(dado: Any, status: int = 200) -> "Resposta":
        return Resposta(status, json.dumps(dado, ensure_ascii=False).encode("utf-8"))


@dataclass
class Fluxo:
    """Resposta SSE: um gerador de eventos `(tipo, dado)` pintados ao vivo."""

    eventos: Iterator[tuple[str, Any]]


Manipulador = Callable[[Pedido], Resposta | Fluxo]

#: {(metodo, caminho) -> (handler, exige_painel)}
ROTAS: dict[tuple[str, str], tuple[Manipulador, bool]] = {}


def rota(metodo: str, caminho: str, *, exige_painel: bool = True):
    """Registra um handler.

    `exige_painel` liga o porteiro do ADR 0005: só passa quem vem da nossa própria
    página (`Sec-Fetch-Site: same-origin`) ou do loader dentro do `.avpi`
    (`Origin: avpi://`). Fica `False` só no que precisa ser alcançável antes disso —
    a navegação que carrega o painel, e o `/saude` que o loader consulta de fora.
    """

    def registrar(fn: Manipulador) -> Manipulador:
        chave = (metodo.upper(), caminho)
        if chave in ROTAS:
            anterior = ROTAS[chave][0]
            raise ValueError(
                f"rota {metodo.upper()} {caminho} já registrada por "
                f"{anterior.__module__}.{anterior.__qualname__}"
            )
        ROTAS[chave] = (fn, exige_painel)
        return fn

    return registrar


#: A origem do loader dentro do `.avpi`. **Medida, não suposta:** o painel roda em
#: QtWebEngine e manda literalmente `avpi://` — não `avpi://<id-do-plugin>`, não `null`,
#: não ausente (banco, 2026-08-08).
ORIGEM_DO_LOADER = "avpi://"

#: Teto do corpo de um pedido. O maior legítimo é um anexo pelo conteúdo
#: (`arrastados.TETO_DE_ANEXO`, 25 MB) — 32 MB deixa margem para o envelope.
MAX_CORPO = 32 * 1024 * 1024


def cors_para(pedido: Pedido) -> dict[str, str]:
    """Os cabeçalhos de CORS devidos a este pedido — ou nenhum.

    ⚠️⚠️ **Sem isto, o loader diz "o serviço não está rodando" com o serviço rodando.**
    Medido em 2026-09-10, dentro do Media Composer: o `fetch` do loader ABRE a conexão
    (o TCP aparece em TIME_WAIT do lado do serviço), o servidor responde 200, e o
    navegador **recusa entregar a resposta à página** por faltar
    `Access-Control-Allow-Origin`. O `catch` do loader não distingue "não conectei" de
    "conectei e não pude ler" — e a mensagem manda procurar o serviço, que está lá.

    ⛔ **Nunca `*`.** A página do painel é same-origin depois de carregada e não precisa
    de CORS; quem precisa é só o loader, e ele recebe de volta a origem exata que
    apresentou. Um `*` abriria o serviço para qualquer página aberta no navegador do
    editor.
    """
    origem = pedido.cabecalho("origin").strip().lower()
    if origem == ORIGEM_DO_LOADER:
        return {"Access-Control-Allow-Origin": ORIGEM_DO_LOADER}
    return {}


def veio_do_painel(pedido: Pedido) -> bool:
    """Este pedido nasceu dentro do Media Composer?

    ⚠️⚠️ **`Sec-Fetch-Site`, não `Origin`** — e a diferença já custou uma depuração
    inteira, medida pelo banco em 2026-08-09. Com o painel servido pelo próprio serviço
    (ADR 0007), um `GET` same-origin **não manda `Origin`**: o navegador só o envia em
    CORS e em POST. Quem olhar o `Origin` vê o painel CARREGAR, os POSTs funcionarem e
    todo `GET` voltar 401 — o sintoma manda depurar o lugar errado.

    Os dois cabeçalhos aceitos aqui são *forbidden headers*: nenhuma página web consegue
    defini-los. Um site qualquer chamando `127.0.0.1` chega com `cross-site`.
    """
    if pedido.cabecalho("sec-fetch-site") == "same-origin":
        return True
    # O loader mora dentro do `.avpi` e é a única peça que faz chamada cross-origin de
    # verdade — dela o `Origin: avpi://` chega normalmente.
    return pedido.cabecalho("origin").strip().lower() == ORIGEM_DO_LOADER


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cicloassist"

    def log_message(self, formato: str, *args: Any) -> None:
        log.debug("%s - %s", self.address_string(), formato % args)

    # ── entrada ──────────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        self._atender("GET")

    def do_POST(self) -> None:
        self._atender("POST")

    def do_DELETE(self) -> None:
        self._atender("DELETE")

    def _atender(self, metodo: str) -> None:
        caminho = unquote(urlparse(self.path).path)
        cabecalhos = {k.lower(): v for k, v in self.headers.items()}
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > MAX_CORPO:
            # ⛔ O corpo é lido INTEIRO na memória antes de a rota existir: sem teto, um
            #    pedido de 4 GB derruba o serviço antes de qualquer validação.
            log.warning("recusado %s %s: corpo de %d bytes", metodo, caminho, tamanho)
            self._responder(Resposta(413, b'{"erro":"corpo grande demais"}'))
            return
        corpo = self.rfile.read(tamanho) if tamanho else b""
        consulta = {n: v[0] for n, v in
                    parse_qs(urlparse(self.path).query, keep_blank_values=True).items()}
        pedido = Pedido(metodo, caminho, cabecalhos, corpo, consulta)

        registro = ROTAS.get((metodo, caminho))
        if registro is None:
            if metodo == "GET" and caminho.startswith("/static/"):
                self._servir_estatico(caminho)
                return
            self._responder(Resposta(404, b'{"erro":"rota desconhecida"}'))
            return

        manipulador, exige_painel = registro
        if exige_painel and veio_do_painel(pedido):
            # ⭐ Toda fala do painel é presença: é o que separa "o editor está aqui" de
            #   "o Media Composer foi fechado" sem perguntar nada a ninguém
            #   (`servico/presenca.py`).
            _presenca.bater()
        if exige_painel and not veio_do_painel(pedido):
            log.warning("recusado %s %s: não veio do painel", metodo, caminho)
            self._responder(
                Resposta(403, b'{"erro":"esta rota so atende o painel do Media Composer"}')
            )
            return

        try:
            resultado = manipulador(pedido)
        except CorpoInvalido as e:
            # Entrada torta é 400, nunca 500: a diferença diz de quem é a culpa, e um
            # 500 manda procurar defeito no serviço quando o problema veio de fora.
            log.warning("%s %s recusado: %s", metodo, caminho, e)
            self._responder(Resposta.de_json({"erro": str(e)}, 400))
            return
        except Exception:
            log.exception("rota %s %s falhou", metodo, caminho)
            self._responder(Resposta(500, b'{"erro":"falha interna"}'))
            return

        if isinstance(resultado, Fluxo):
            self._transmitir(resultado)
        else:
            resultado.extras.update(cors_para(pedido))
            self._responder(resultado)

    # ── saída ────────────────────────────────────────────────────────────────

    def _responder(self, r: Resposta) -> None:
        self.send_response(r.status)
        if r.corpo:
            self.send_header("Content-Type", r.tipo)
        self.send_header("Content-Length", str(len(r.corpo)))
        for k, v in r.extras.items():
            self.send_header(k, v)
        self.end_headers()
        if r.corpo:
            self.wfile.write(r.corpo)

    def _transmitir(self, fluxo: Fluxo) -> None:
        """SSE sem framework.

        `Connection: close` e sem `Content-Length`: o tamanho não é conhecido de
        antemão, e fechar no fim delimita a resposta sem precisar de chunked.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        # ⚠️ Sem isto, um proxy ou a própria webview podem segurar o buffer e a
        # resposta chega toda de uma vez — que é exatamente o que a fase 2 nega.
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        try:
            for tipo, dado in fluxo.eventos:
                pedaco = (
                    f"event: {tipo}\n"
                    f"data: {json.dumps(dado, ensure_ascii=False)}\n\n"
                ).encode("utf-8")
                self.wfile.write(pedaco)
                self.wfile.flush()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # O editor fechou o painel no meio da resposta. É rotina.
            log.debug("painel desligou no meio do fluxo")

    def _servir_estatico(self, caminho: str) -> None:
        relativo = caminho[len("/static/"):]
        alvo = (DIR_PAINEL / relativo).resolve()
        # ⚠️ O `resolve()` acima transforma `../` em caminho real; esta checagem é o
        # que impede servir qualquer arquivo do disco a partir da rota estática.
        if not alvo.is_file() or DIR_PAINEL.resolve() not in alvo.parents:
            self._responder(Resposta(404, b'{"erro":"arquivo desconhecido"}'))
            return
        tipo, _ = mimetypes.guess_type(str(alvo))
        # ⚠️⚠️ `no-store` pelo mesmo motivo do `/painel` (ver a rota, e a ressalva de que
        # o conserto ainda não foi visto funcionando): a webview do Media Composer é
        # livre para guardar o CSS e o JavaScript. O pior caso é o pior de todos — HTML
        # novo com JavaScript velho —, porque a tela aparece mudada e se comporta como a
        # de antes.
        self._responder(
            Resposta(200, alvo.read_bytes(), tipo or "application/octet-stream",
                     {"Cache-Control": "no-store"})
        )

    def handle_one_request(self) -> None:
        """Igual ao da stdlib, menos o traceback quando o cliente fecha na cara.

        ⚠️ **Medido em 2026-09-10, Windows.** O CLI do Claude encerra a conexão assim que
        termina o turno, e o `ThreadingHTTPServer` cospe um `ConnectionResetError`
        (WinError 10054) por isso — em stderr, fora do logging, numa thread. Não é
        defeito: é o fim normal de uma conversa.

        Engolir importa mais do que parece. Num serviço que fica de pé o dia inteiro, um
        traceback por turno treina o operador a ignorar o log — e aí o traceback que
        importava passa junto. Isto silencia SÓ queda de conexão.
        """
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True
            log.debug("cliente fechou a conexão")


class PortaOcupada(OSError):
    """Já há um serviço de pé. ⚠️ Erro alto de propósito: ver `subir()`.

    ⭐ **`OSError` de propósito.** O `__main__` já tratava porta ocupada com uma mensagem
    boa — *"Já há um Ciclo Assist rodando? Feche-o antes de abrir outro."* — e o comentário
    dele já dizia o porquê: *"subir um segundo seria pior que recusar: o painel acharia um
    dos dois, sem dizer qual."* A intenção estava certa desde sempre; o que a anulava era o
    `allow_reuse_address` deixando o bind PASSAR no Windows, então o `OSError` nunca
    acontecia. Herdando dele, o tratamento que já existe volta a valer sem mudar uma linha
    do entry point."""


class _Servidor(ThreadingHTTPServer):
    """O `ThreadingHTTPServer` com a regra de porta de cada sistema. Ver `subir()`.

    ⚠️ Subclasse, e não o atributo da classe da stdlib: mudar lá valia para todo servidor
    HTTP do processo.
    """

    # ⛔⛔ Windows: `SO_REUSEADDR` deixa um SEGUNDO processo bindar a porta viva.
    # ⭐ POSIX: não deixa — só reaproveita a porta em TIME_WAIT. MEDIDO no macOS
    #    (2026-09-14): dois serviços vivos continuam recusados com a opção ligada; com ela
    #    DESLIGADA, cada resposta SSE (`Connection: close`) deixava TIME_WAIT, e reiniciar
    #    logo depois de um turno dizia "já existe um Ciclo Assist" por até ~30 s, sem
    #    processo nenhum escutando.
    allow_reuse_address = os.name != "nt"


def subir(porta: int = PORTA) -> ThreadingHTTPServer:
    """Sobe o serviço numa thread e devolve a instância, já servindo.

    ⚠️ `127.0.0.1` literal, nunca `0.0.0.0`: este serviço dispara ações no projeto do
    editor e não tem por que ser alcançável da rede.
    """
    from . import rotas  # noqa: F401  (registra as rotas por efeito de import)
    from . import rotas_carta  # noqa: F401  (a Carta Aberta)

    # ⛔⛔ **MEDIDO em 2026-09-12, e é o defeito que faz "reinicie o serviço" não
    #    resolver.** `HTTPServer` traz `allow_reuse_address = 1`, e no WINDOWS isso não
    #    significa "reaproveitar um socket em TIME_WAIT" como no Unix: significa que um
    #    segundo processo **binda a mesma porta com sucesso** enquanto o primeiro ainda
    #    está servindo. Aconteceu aqui: um serviço de 15:32 e outro de 17:26 escutando a
    #    7824, o novo dizendo "serviço em http://127.0.0.1:7824" no log, e o VELHO
    #    respondendo a todos os pedidos. A tela nova pedia rotas que o processo de trás
    #    não tinha, e o sintoma era idêntico ao de um painel desatualizado.
    #
    # ⇒ Falhar alto é melhor que subir mudo. Com isto o segundo processo morre dizendo
    #   o que fazer, em vez de fingir que assumiu. (No POSIX a regra é outra: `_Servidor`.)
    try:
        servidor = _Servidor(("127.0.0.1", porta), Handler)
    except OSError as e:
        raise PortaOcupada(
            f"já existe um Ciclo Assist na porta {porta}. Feche o serviço anterior "
            f"antes de subir este — enquanto ele estiver de pé, é ele que responde."
        ) from e
    servidor.daemon_threads = True
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    log.info("serviço em http://127.0.0.1:%d", porta)
    return servidor
