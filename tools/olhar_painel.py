"""Olhar o painel funcionando, sem o Media Composer — Chrome headless dirigido por CDP.

    python tools/olhar_painel.py                      # a aba Vetores, print e estado
    python tools/olhar_painel.py --aba busca --termo claquete
    python tools/olhar_painel.py --aba vetores --saida D:/tmp/painel.png

⭐⭐ **Por que isto existe.** A suíte alcança `node --check` e o casamento de texto entre
`painel.js` e `index.html` — e o modo de falha de um painel é *"a tela não faz nada"* e
*"o layout quebra em 400 px"*. Nenhum dos dois aparece em teste de texto.

Ele se pagou em TODAS as rodadas em que foi usado, e sempre pelo mesmo tipo de defeito:
a tela saindo **sem miniatura nenhuma**, os planos parecidos abrindo **ao lado** do texto
(faltava `flex-wrap`), o texto descendo para baixo da miniatura a 400 px (`flex-basis:
auto`), e — em 2026-09-22 — o preço anunciando **20 min para um trabalho de 3 horas**,
porque a régua de tempo do Claude estava sendo aplicada ao Mac. Esse último tinha teste,
aritmética certa e número plausível: só o print pega.

⚠️⚠️ **Isto NÃO substitui o Media Composer.** O QtWebEngine não é o Chrome, e defeitos
medidos lá — o Reload trazendo a página antiga, o clique sintético que não chega à webview —
não aparecem aqui. O veredito é *"o layout e a lógica estão de pé"*, nunca *"funciona no
produto"*.

⚠️ Precisa do serviço no ar (`.\\dev.ps1` ou `python -m cicloassist.servico`). O cache que
ele lê é o REAL desta máquina — a leitura não escreve nada, mas os números do print são os
do editor.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

#: ⚠️ Chrome não é pré-requisito do produto: é ferramenta de desenvolvimento, e por isso a
#: ausência dele é uma frase, não um traceback.
CHROMES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
PORTA_CDP = 9333
PAINEL = "http://127.0.0.1:7824/painel"
#: ⛔ O painel vive em ~400 px dentro do Media Composer. `--window-size` inclui a MOLDURA:
#: sem `setDeviceMetricsOverride` o print sai a 504 e o defeito de layout não aparece.
LARGURA = 400


def achar_chrome() -> str | None:
    return next((c for c in CHROMES if Path(c).is_file()), None)


class WS:
    """Cliente WebSocket mínimo (RFC 6455): handshake, frame mascarado, texto.

    ⭐ Sessenta linhas em vez de uma dependência: o venv do produto não tem cliente
    WebSocket, e uma ferramenta de desenvolvimento não justifica uma no `requirements`.
    """

    def __init__(self, url: str, prazo: float = 240.0) -> None:
        resto = url.split("://", 1)[1]
        hostporta, caminho = resto.split("/", 1)
        host, porta = hostporta.split(":")
        # ⚠️ Generoso: a aba Vetores lê o cache inteiro (centenas de mídias) e o
        #   `awaitPromise` segura a resposta o tempo todo.
        self.sock = socket.create_connection((host, int(porta)), timeout=prazo)
        chave = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /{caminho} HTTP/1.1\r\nHost: {hostporta}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {chave}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
        dados = b""
        while b"\r\n\r\n" not in dados:
            dados += self.sock.recv(4096)
        self.resto = dados.split(b"\r\n\r\n", 1)[1]
        self.n = 0

    def _ler(self, quantos: int) -> bytes:
        while len(self.resto) < quantos:
            pedaco = self.sock.recv(65536)
            if not pedaco:
                raise ConnectionError("o Chrome fechou a conexão")
            self.resto += pedaco
        saida, self.resto = self.resto[:quantos], self.resto[quantos:]
        return saida

    def enviar(self, texto: str) -> None:
        corpo = texto.encode()
        cabeca = bytearray([0x81])
        n = len(corpo)
        if n < 126:
            cabeca.append(0x80 | n)
        elif n < 65536:
            cabeca.append(0x80 | 126)
            cabeca += struct.pack(">H", n)
        else:
            cabeca.append(0x80 | 127)
            cabeca += struct.pack(">Q", n)
        mascara = os.urandom(4)
        cabeca += mascara
        self.sock.sendall(bytes(cabeca)
                          + bytes(b ^ mascara[i % 4] for i, b in enumerate(corpo)))

    def receber(self) -> dict:
        while True:
            b0, b1 = self._ler(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._ler(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._ler(8))[0]
            corpo = self._ler(n)
            if (b0 & 0x0F) == 1:            # texto; ping/pong e binário não interessam
                return json.loads(corpo.decode())

    def chamar(self, metodo: str, **params) -> dict:
        self.n += 1
        self.enviar(json.dumps({"id": self.n, "method": metodo, "params": params}))
        while True:
            msg = self.receber()
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{metodo}: {msg['error']}")
                return msg.get("result") or {}


def avaliar(ws: WS, expressao: str, esperar: bool = False):
    """Roda JavaScript na página. ⭐ Com `esperar`, uma `Promise` deixa clicar DEPOIS de a
    busca responder — é o que permite medir a tela pronta, e não a tela a meio caminho."""
    r = ws.chamar("Runtime.evaluate", expression=expressao, returnByValue=True,
                  awaitPromise=esperar)
    saida = r.get("result") or {}
    if saida.get("subtype") == "error":
        raise RuntimeError(saida.get("description"))
    return saida.get("value")


#: ⭐ Ler o DOM no fim conta o resultado sem depender de olho: "21 cartões, 0 títulos
#: repetidos, 21 miniaturas" é uma asserção. O print fica para o que só o olho pega.
ESTADO_DA_TELA = """
  (function () {
    function txt(id) { var e = document.getElementById(id);
      return e && !e.hidden ? e.textContent.trim() : ""; }
    var cartoes = document.querySelectorAll(".bus-achado");
    var titulos = Array.prototype.map.call(cartoes, function (c) {
      var t = c.querySelector(".bus-titulo"); return t ? t.textContent.trim() : ""; });
    return {
      larguraDoCorpo: document.body.scrollWidth,
      vetResumo: txt("vetResumo"),
      vetLinhas: document.querySelectorAll("#vetores tr").length,
      precoDecupagem: txt("precoDecupagem"),
      precoMicro: txt("precoMicro"),
      densidade: (document.getElementById("densidade") || {}).value || "",
      busResumo: txt("busResumo"),
      busExpansao: txt("busExpansao"),
      busEscopo: txt("busEscopo"),
      busCartoes: cartoes.length,
      busTitulosRepetidos: titulos.length - new Set(titulos).size,
      busMiniaturas: document.querySelectorAll(".bus-achado img").length,
      busSetinhas: document.querySelectorAll(".bus-achado .bus-seta").length,
      busFalas: document.querySelectorAll(".bus-fala").length,
      busClaquetes: document.querySelectorAll(".bus-claquete").length,
      busClaquetesDuvidosas: document.querySelectorAll(".bus-claquete.duvidosa").length
    };
  })()
"""


def esperar_por(ws: WS, seletor: str, prazo_ms: int = 90000) -> int:
    return avaliar(ws, f"""
      new Promise(function (ok) {{
        var t0 = Date.now();
        var relogio = setInterval(function () {{
          var n = document.querySelectorAll({seletor!r}).length;
          if (n || Date.now() - t0 > {prazo_ms}) {{ clearInterval(relogio); ok(n); }}
        }}, 500);
      }})
    """, esperar=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    p.add_argument("--aba", default="vetores", choices=("vetores", "busca", "conversa", "fluxos"))
    p.add_argument("--receita", default="", help="na aba Fluxos: abre o formulário da receita com isto no título")
    p.add_argument("--termo", default="claquete", help="o que procurar, na aba Busca")
    p.add_argument("--saida", default="", help="onde gravar o print (.png)")
    p.add_argument("--painel", default=PAINEL)
    # ⭐ O painel decide de que editor ele é pelo `window.__adobe_cep__` (o do Premiere).
    #   Injetá-lo antes dos scripts é o que deixa VER a tela do Premiere sem o Premiere —
    #   feito à mão por CDP em 2026-09-21, e agora é uma opção em vez de um script solto.
    p.add_argument("--premiere", action="store_true",
                   help="fingir o Premiere (banco e palavras dele), em vez do Avid")
    args = p.parse_args()

    chrome_exe = achar_chrome()
    if not chrome_exe:
        print("não achei o Chrome — ele é ferramenta de desenvolvimento, não do produto.")
        return 2
    try:
        with urllib.request.urlopen(args.painel.replace("/painel", "/saude"), timeout=5):
            pass
    except OSError:
        print("o serviço não está no ar: rode `.\\dev.ps1` ou "
              "`python -m cicloassist.servico` antes.")
        return 2

    saida = Path(args.saida or f"painel-{args.aba}.png").resolve()
    perfil = saida.parent / "_perfil-chrome"
    chrome = subprocess.Popen([
        chrome_exe, "--headless=new", f"--remote-debugging-port={PORTA_CDP}",
        f"--user-data-dir={perfil}", "--no-first-run", "--no-default-browser-check",
        "--disable-gpu", "about:blank"])
    try:
        alvo = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{PORTA_CDP}/json/list", timeout=2) as r:
                    abas = json.loads(r.read())
                alvo = next((a for a in abas if a.get("type") == "page"), None)
                if alvo:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        if not alvo:
            print("o Chrome não abriu a porta de depuração")
            return 1

        ws = WS(alvo["webSocketDebuggerUrl"])
        ws.chamar("Page.enable")
        ws.chamar("Runtime.enable")
        ws.chamar("Emulation.setDeviceMetricsOverride", width=LARGURA, height=900,
                  deviceScaleFactor=1, mobile=False)
        if args.premiere:
            # ⚠️ Um stub, não uma ponte: `evalScript` responde vazio, que é o que o painel
            #   trata como "o host não sabe" — nunca um projeto inventado.
            ws.chamar("Page.addScriptToEvaluateOnNewDocument", source=(
                "window.__adobe_cep__ = {"
                "  evalScript: function (s, cb) { if (cb) { cb(''); } },"
                "  getSystemPath: function () { return ''; },"
                "  addEventListener: function () {}"
                "};"))
        ws.chamar("Page.navigate", url=args.painel)
        time.sleep(3.0)

        avaliar(ws, f"document.querySelector('[data-tela=\"{args.aba}\"]').click()")
        time.sleep(1.0)
        if args.aba == "vetores":
            print("linhas na tabela:", esperar_por(ws, "#vetores tr"))
        elif args.aba == "busca":
            avaliar(ws, f"""
              (function () {{
                document.getElementById("busFrase").value = {args.termo!r};
                document.getElementById("busProcurar").click();
              }})()
            """)
            print(f"achados para {args.termo!r}:", esperar_por(ws, ".bus-achado"))
        elif args.aba == "fluxos":
            print("receitas:", esperar_por(ws, ".fluxo-receita", 15000))
            if args.receita:
                avaliar(ws, f"""
                  (function () {{
                    var c = Array.prototype.filter.call(document.querySelectorAll(".fluxo-receita"),
                      function (e) {{ return e.textContent.indexOf({args.receita!r}) >= 0; }})[0];
                    if (c) {{ c.querySelector("button").click(); }}
                  }})()
                """)
                print("formulário:", esperar_por(ws, "#fluxosConversa .receita-forma", 5000))

        for chave, valor in (avaliar(ws, ESTADO_DA_TELA) or {}).items():
            if valor not in ("", 0):
                print(f"  {chave}: {valor}")

        tiro = ws.chamar("Page.captureScreenshot", captureBeyondViewport=True)
        saida.write_bytes(base64.b64decode(tiro["data"]))
        print(f"print em {saida}")
        # ⚠️ O aviso fica no FIM, que é onde ele é lido: um ✅ aqui não é o produto.
        print("⚠️ o QtWebEngine não é o Chrome: isto é 'o layout está de pé', "
              "nunca 'funciona no Media Composer'.")
        return 0
    finally:
        chrome.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
