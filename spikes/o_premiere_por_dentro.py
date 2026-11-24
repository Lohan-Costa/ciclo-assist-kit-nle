"""Spike — o Premiere 23.2 por dentro, sem ninguém na frente: P0(a), P0(b) e P0(c).

    python spikes/o_premiere_por_dentro.py [--premiere "C:\\...\\Adobe Premiere Pro.exe"]

Instala a extensão INVISÍVEL `spikes/premiere_sonda/` (arranque automático), abre o
Premiere, deixa a sonda criar um projeto descartável no scratch, e colhe o relato por HTTP
em 127.0.0.1:7899. No fim fecha o Premiere e DESINSTALA a sonda — deixada lá, ela rodaria
toda vez que o editor abrisse o Premiere.

As perguntas (plano `docs/plano/2026-09-17-premiere.md`):

(a) a página servida por HTTP enxerga o `__adobe_cep__`? em iframe? navegando a janela?
    e que `Origin`/`Sec-Fetch-Site` chegam ao serviço de cada jeito?
(b) `getMediaPath` / `hasProxy` / `getProxyPath` com proxy anexado; OP-Atom importado;
    subclipe; timecode de início.
(c) quanto custa a ida e volta serviço → painel → ExtendScript → serviço.

Sai 0 se o relato chegou inteiro (as três etapas), independentemente das respostas.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

AQUI = Path(__file__).resolve().parent
EXTENSAO = AQUI / "premiere_sonda"
ID = "com.ciclomedia.assist.sonda"
PORTA = 7899
PREMIERE = Path(r"C:\Program Files\Adobe\Adobe Premiere Pro 2023\Adobe Premiere Pro.exe")

ORIGINAL = Path(r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODE\MIDIA MULTCAM"
                r"\CAM B\20240531_PANA2774.mov")
ARQUIVOS = [
    ORIGINAL,
    Path(r"D:\Avid MediaFiles\MXF\PRODE\V01.E69CCE70_1A1641A164487V.mxf"),
    Path(r"D:\Avid MediaFiles\MXF\PRODE\A01.E69CCE71_1A1641A164AC2A.mxf"),
    Path(r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\MIDIAS\CONVERTIDOS\D02_230405\01_CAMERAS"
         r"\CAM_A_Blackmagic-4k\A01\A001_03170214_C001.mp4"),
    Path(r"D:\Avid MediaFiles\MXF\0200230405\a001_03170214_C001.mxf"),
    Path(r"D:\MIDIAS DE TESTES\1 PRODUCOES\CANAL-K COPA\XDCAM50\A001_03170256_C002.mxf"),
    Path(r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-G\250516_BOLIVIA\250516_SOM\05-16-25\SP3-TORE-001.WAV"),
]

relatos: list[dict] = []
cabecalhos: list[dict] = []
pedidos: "queue.Queue[dict]" = queue.Queue()
respostas: dict[str, tuple[float, str]] = {}
enviados: dict[str, float] = {}
acabou = threading.Event()
config: dict = {}

IFRAME = """<!doctype html><meta charset=utf-8><script>
(async function(){
  var r = {cep: typeof window.__adobe_cep__, origem: location.href};
  try { r.pai = typeof parent.__adobe_cep__; } catch (e) { r.pai = '!' + e; }
  var t0 = performance.now();
  var resp = await new Promise(function(ok){
    window.addEventListener('message', function(ev){ if (ev.data && ev.data.id === 1) ok(ev.data.r); });
    parent.postMessage({id: 1, expr: 'app.version'}, '*');
    setTimeout(function(){ ok('!sem resposta em 5 s'); }, 5000);
  });
  r.ponte = resp; r.ponte_ms = performance.now() - t0;
  await fetch('/relato', {method:'POST', headers:{'Content-Type':'application/json'},
                          body: JSON.stringify({etapa:'iframe', dados:r})});
  await fetch('/eco-iframe');
  parent.postMessage({fim: true}, '*');
})();
</script>"""

PAGINA = """<!doctype html><meta charset=utf-8><script>
(async function(){
  var cep = window.__adobe_cep__;
  var r = {cep: typeof cep, origem: location.href};
  if (cep) {
    r.versao = await new Promise(function(ok){
      try { cep.evalScript('app.version', ok); } catch (e) { ok('!' + e); }
      setTimeout(function(){ ok('!sem resposta em 5 s'); }, 5000);
    });
    try { r.host = JSON.parse(cep.getHostEnvironment()).appVersion; } catch (e) { r.host = '!' + e; }
  }
  await fetch('/relato', {method:'POST', headers:{'Content-Type':'application/json'},
                          body: JSON.stringify({etapa:'pagina', dados:r})});
  await fetch('/eco-pagina');
  if (cep) {
    var s = await new Promise(function(ok){ cep.evalScript('sondaSair()', ok); setTimeout(ok, 5000); });
    await fetch('/relato', {method:'POST', body: JSON.stringify({etapa:'sair', dados:s})}).catch(function(){});
  }
  await fetch('/fim', {method:'POST'}).catch(function(){});
})();
</script>"""


class Receptor(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silêncio: o relato é o que importa
        pass

    def _anotar(self):
        h = self.headers
        cabecalhos.append({
            "metodo": self.command, "caminho": self.path,
            "Origin": h.get("Origin"), "Sec-Fetch-Site": h.get("Sec-Fetch-Site"),
            "Sec-Fetch-Mode": h.get("Sec-Fetch-Mode"), "Referer": h.get("Referer"),
        })

    def _responder(self, codigo: int, corpo: bytes, tipo: str = "application/json"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_OPTIONS(self):
        self._anotar()
        self._responder(204, b"")

    def do_GET(self):
        self._anotar()
        if self.path == "/config":
            self._responder(200, json.dumps(config).encode())
        elif self.path == "/pedido":
            try:
                p = pedidos.get(timeout=30)
            except queue.Empty:
                p = {}
            if p.get("id"):
                enviados[p["id"]] = time.perf_counter()
            self._responder(200, json.dumps(p).encode())
        elif self.path == "/iframe":
            self._responder(200, IFRAME.encode(), "text/html; charset=utf-8")
        elif self.path == "/pagina":
            self._responder(200, PAGINA.encode(), "text/html; charset=utf-8")
        else:
            self._responder(200, b"{}")

    def do_POST(self):
        self._anotar()
        corpo = self._corpo()
        if self.path == "/relato":
            try:
                relatos.append(json.loads(corpo))
            except json.JSONDecodeError:
                relatos.append({"etapa": "?", "bruto": corpo.decode("utf-8", "replace")})
            print(f"  · relato {relatos[-1].get('etapa')}", flush=True)
        elif self.path == "/resposta":
            d = json.loads(corpo)
            respostas[d["id"]] = (time.perf_counter(), d.get("r"))
        elif self.path == "/fim":
            acabou.set()
        self._responder(200, b"{}")


def criar_proxy(destino: Path) -> Path:
    """Um proxy como o Premiere espera: mesmos quadros, TC e canais, janela menor."""
    if destino.exists():
        return destino
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", str(ORIGINAL),
        "-map", "0:v:0", "-map", "0:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-vf", "scale=640:-2",
        "-c:a", "aac", "-b:a", "96k", "-timecode", "23:16:47:11", str(destino),
    ], check=True, timeout=600)
    return destino


def pasta_extensoes() -> Path:
    return Path(os.environ["APPDATA"]) / "Adobe" / "CEP" / "extensions"


def matar(proc: subprocess.Popen) -> None:
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--premiere", type=Path, default=PREMIERE)
    ap.add_argument("--prazo", type=int, default=600)
    args = ap.parse_args()

    trabalho = Path(tempfile.mkdtemp(prefix="sonda_premiere_"))
    proxy = criar_proxy(trabalho / "20240531_PANA2774_Proxy.mov")
    config.update({
        "projeto": str(trabalho / "sonda.prproj"),
        "arquivos": [str(a) for a in ARQUIVOS if a.exists()],
        "item_com_proxy": ORIGINAL.name,
        "proxy": str(proxy),
    })
    for i in range(10):
        expr = "app.version" if i % 2 == 0 else "sondaSelecao()"
        pedidos.put({"id": str(i), "expr": expr})
    pedidos.put({})  # fim da fila

    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Receptor)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    destino = pasta_extensoes() / ID
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(EXTENSAO, destino)
    print(f"sonda instalada em {destino}")

    proc = None
    t0 = time.perf_counter()
    try:
        proc = subprocess.Popen([str(args.premiere)])
        print(f"Premiere aberto (pid {proc.pid}); esperando o relato até {args.prazo} s…")
        acabou.wait(timeout=args.prazo)
        print(f"relato {'completo' if acabou.is_set() else 'INCOMPLETO'} em "
              f"{time.perf_counter() - t0:.0f} s")
        try:
            proc.wait(timeout=30)
            print("o Premiere saiu sozinho (app.quit)")
        except subprocess.TimeoutExpired:
            print("o Premiere não saiu: encerrando o processo")
            matar(proc)
    finally:
        if proc and proc.poll() is None:
            matar(proc)
        time.sleep(3)
        shutil.rmtree(destino, ignore_errors=True)
        print(f"sonda desinstalada: {not destino.exists()}")
        servidor.shutdown()

    ida_e_volta = {k: round((respostas[k][0] - enviados[k]) * 1000, 1)
                   for k in respostas if k in enviados}
    saida = {"relatos": relatos, "cabecalhos": cabecalhos,
             "ida_e_volta_ms": ida_e_volta,
             "respostas": {k: v[1] for k, v in respostas.items()},
             "trabalho": str(trabalho)}
    arquivo = trabalho / "relato.json"
    arquivo.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"relato em {arquivo}")
    print(json.dumps(saida, ensure_ascii=False, indent=1)[:20000])
    etapas = {r.get("etapa") for r in relatos}
    return 0 if {"importar", "iframe", "pagina"} <= etapas else 1


if __name__ == "__main__":
    raise SystemExit(main())
