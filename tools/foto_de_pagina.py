"""Fotos de uma página do app (qualquer painel, qualquer porta) num Chrome headless, seguindo um ROTEIRO — para o
relatório e para ver o layout sem abrir a janela do app nem mexer no mouse (o `olhar_painel.py` faz o mesmo só para a
aba do Assist; daqui reusa o cliente CDP dele).

    python tools/foto_de_pagina.py <roteiro.json> <pasta das fotos>

Roteiro: `{"url": "http://127.0.0.1:7823/painel?nle=baselight&casca=app", "largura": 460, "altura": 900,
           "passos": [{"js": "…", "espera": 2, "ate": "seletor CSS visível", "prazo": 60, "foto": "01-painel.png"}]}`
Cada passo: roda o `js` (opcional, com `await`), espera `espera` s e/ou até `ate` existir e estar visível, e fotografa a
página inteira em `foto` (opcional). A saída diz cada foto gravada e o texto de `#dizer`/`.aviso` visíveis.

⚠️ É o Chrome, não a webview do app (WKWebView no Mac, WebView2 no Windows): o veredito é "o layout e a lógica estão de
pé", e a foto é a do Chrome. Precisa do serviço da página no ar.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from olhar_painel import PORTA_CDP, WS, achar_chrome, avaliar  # noqa: E402

VISIVEL = ("(function(s){var e=document.querySelector(s);if(!e)return false;var r=e.getBoundingClientRect();"
           "return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden';})")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    roteiro = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    pasta = Path(sys.argv[2]).resolve()
    pasta.mkdir(parents=True, exist_ok=True)
    chrome_exe = achar_chrome()
    if not chrome_exe:
        print("não achei o Chrome")
        return 2
    perfil = Path("/tmp" if sys.platform != "win32" else ".") / "_perfil-chrome-foto"
    chrome = subprocess.Popen([chrome_exe, "--headless=new", f"--remote-debugging-port={PORTA_CDP}",
                               f"--user-data-dir={perfil}", "--no-first-run", "--no-default-browser-check",
                               "--disable-gpu", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        alvo = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORTA_CDP}/json/list", timeout=2) as r:
                    alvo = next((a for a in json.loads(r.read()) if a.get("type") == "page"), None)
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
        ws.chamar("Emulation.setDeviceMetricsOverride", width=int(roteiro.get("largura", 460)),
                  height=int(roteiro.get("altura", 900)), deviceScaleFactor=2, mobile=False)
        ws.chamar("Page.navigate", url=roteiro["url"])
        time.sleep(3.0)
        for n, p in enumerate(roteiro.get("passos") or [], 1):
            if p.get("js"):
                r = avaliar(ws, "(async () => { " + p["js"] + " })()", esperar=True)
                if r not in (None, ""):
                    print(f"  passo {n}: {str(r)[:300]}")
            if p.get("espera"):
                time.sleep(float(p["espera"]))
            if p.get("ate"):
                fim = time.time() + float(p.get("prazo", 60))
                while time.time() < fim and not avaliar(ws, f"{VISIVEL}({json.dumps(p['ate'])})"):
                    time.sleep(0.5)
                time.sleep(0.5)
            if p.get("foto"):
                tiro = ws.chamar("Page.captureScreenshot", captureBeyondViewport=True)
                destino = pasta / p["foto"]
                destino.write_bytes(base64.b64decode(tiro["data"]))
                dito = avaliar(ws, "Array.from(document.querySelectorAll('#dizer, .aviso, .previa-ok'))"
                                   ".filter(e => e.offsetParent).map(e => e.textContent.trim()).join(' | ')")
                print(f"foto: {destino}" + (f"  — {str(dito)[:200]}" if dito else ""))
        return 0
    finally:
        chrome.terminate()


if __name__ == "__main__":
    sys.exit(main())
