"""O diferencial das ROTAS: o mesmo pedido ao Órbita em Rust (7817, no ar) e ao servidor Python (outra porta).

    python diferencial_das_rotas.py [porta do python, padrão 7827]

Sobe o servidor Python nesta porta com a pasta de dados num tmp (⛔ nunca publicar o token por cima do do Rust:
os painéis abertos passariam a ser recusados), manda a cada um a MESMA lista de pedidos — o portão, os erros de
cada rota, as leituras que não mexem em nada, as páginas servidas — e compara status e corpo (JSON comparado como
objeto; HTML byte a byte). Sai 0 se tudo bate.

⛔ Fica de fora o que MEXE no estado do Órbita vivo: `/nlejob` (tira trabalho da fila do painel), `/premiere/pedido`
(roubaria a expressão da ponte), `/premiere/chamar`, `/cache/clear`, as escritas no MC. Essas o diferencial cobre
pelo comportamento, nos testes; e de ponta a ponta, na P6 e no sync do MC com o motor Python.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parents[1]
RUST = 7817


def token_do_rust() -> str:
    base = (Path(os.environ["APPDATA"]) if sys.platform == "win32"
            else Path.home() / "Library" / "Application Support")
    return (base / "Orbita" / "plugin-token").read_text().strip()


def pedir(porta, metodo, rota, corpo=None, token=None, cab=None):
    h = dict(cab or {})
    if token:
        h["X-Sincronizar-Token"] = token
    if "Host" not in h:
        h["Host"] = f"127.0.0.1:{porta}"
    dados = corpo if isinstance(corpo, bytes) or corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{porta}{rota}", data=dados, method=metodo, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def normal(st, tipo, corpo):
    if "json" in tipo:
        v = json.loads(corpo)
        if isinstance(v, dict):
            v.pop("elapsed_ms", None)
            v.pop("motor", None)  # só o Python diz qual é o motor
            e = v.get("error")
            if isinstance(e, str) and e.startswith("JSON inválido:"):
                v["error"] = "JSON inválido: …"  # o detalhe é do parser de cada linguagem (serde × json)
        return st, v
    return st, corpo


def casos(porta_py):
    """(nome, método, rota, corpo, com_token, cabeçalhos extras). A origem própria é a da porta de cada um."""
    c = []
    # o portão
    c += [("sem token", "GET", "/health", None, False, {}),
          ("origem web", "GET", "/health", None, False, {"Origin": "https://site.example"}),
          ("avpi no health", "GET", "/health", None, False, {"Origin": "avpi://"}),
          ("avpi em rota pesada", "POST", "/sources", {"paths": []}, False, {"Origin": "avpi://"}),
          ("host de fora", "GET", "/health", None, True, {"Host": "localhost.evil.example:7817"}),
          ("same-origin", "GET", "/health", None, False, {"Sec-Fetch-Site": "same-origin"}),
          ("cross-site", "GET", "/health", None, False, {"Sec-Fetch-Site": "cross-site"}),
          ("preflight", "OPTIONS", "/sources", None, False, {}),
          ("prefixo", "GET", "/healthFOO", None, True, {})]
    # leituras
    c += [("health", "GET", "/health", None, True, {}),
          ("settings", "GET", "/settings", None, True, {}),
          ("conexao", "GET", "/conexao", None, True, {}),
          ("historico", "GET", "/avid/renomear/historico", None, True, {}),
          ("status sem id", "GET", "/prproj/status", None, True, {}),
          ("status desconhecido", "GET", "/prproj/status?id=job_0_0", None, True, {}),
          ("montagem sem id", "GET", "/api/v1/montagem", None, True, {}),
          ("montagem desconhecida", "GET", "/api/v1/montagem?id=ponte-0", None, True, {}),
          ("resultado desconhecido", "GET", "/premiere/resultado?id=999999", None, True, {}),
          ("resultado sem id", "GET", "/premiere/resultado", None, True, {})]
    # os erros de cada rota, com corpo vazio, JSON quebrado e não-UTF-8
    rotas = ["/avid/mobs", "/avid/renomear/ler", "/avid/nome/prever", "/avid/renomear/aplicar", "/avid/timeline",
             "/avid/subclipes/ler", "/avid/subclipes/prever", "/avid/subclipes/cena", "/avid/subclipes/remover",
             "/avid/subclipes/gerar", "/premiere/merged/ler", "/premiere/merged/gerar", "/avid/montar", "/syncmap",
             "/folder/open", "/link/open", "/sources", "/api/v1/nlejob", "/api/v1/merge", "/premiere/resposta",
             "/app/fixar", "/avid/painel", "/nlejob/done"]
    for r in rotas:
        c += [(f"{r} vazio", "POST", r, {}, True, {}),
              (f"{r} não-utf8", "POST", r, b"\xff\xfe", True, {})]
    c += [("subclipes/cena sem indices", "POST", "/avid/subclipes/cena", {"leitura_id": "x"}, True, {}),
          ("subclipes/remover sem indices", "POST", "/avid/subclipes/remover", {"leitura_id": "x"}, True, {}),
          ("folder estranha", "POST", "/folder/open", {"which": "/etc"}, True, {}),
          ("link estranho", "POST", "/link/open", {"which": "file:///etc/passwd"}, True, {}),
          ("nlejob sem painel", "POST", "/api/v1/nlejob", {"job_id": "x", "nle": "resolve"}, True, {}),
          ("merge sem job", "POST", "/api/v1/merge", {}, True, {}),
          ("resposta desconhecida", "POST", "/premiere/resposta", {"id": 999999, "r": "x"}, True, {}),
          ("sources", "POST", "/sources",
           {"paths": ["/x/A001_C001.mov", "/x/A001_C002.mov", "/x/T01.WAV", "/x/DJI_0001.MP4"]}, True, {}),
          ("prever nome sem fichas", "POST", "/avid/nome/prever", {"padrao": "x"}, True, {})]
    # as páginas
    c += [("ui do painel", "GET", "/avid/panel?casca=app&embutido=1", None, False, {}),
          ("ponte html", "GET", "/premiere/ponte", None, False, {}),
          ("ponte js", "GET", "/premiere/ponte.js", None, True, {}),
          ("host.jsx", "GET", "/premiere/host.jsx", None, True, {}),
          ("host.jsx sem token", "GET", "/premiere/host.jsx", None, False, {})]
    return c


def main() -> int:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 7827
    dados = tempfile.mkdtemp(prefix="sincronizar-diferencial-")
    env = dict(os.environ, SINCRONIZAR_DADOS=dados)
    env.setdefault("PYTHONPYCACHEPREFIX", tempfile.gettempdir() + "/pyc")
    proc = subprocess.Popen([sys.executable, str(AQUI / "servidor.py"), "--porta", str(porta)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        tok_py = None
        for _ in range(100):
            p = Path(dados) / "plugin-token"
            if p.is_file() and p.read_text():
                tok_py = p.read_text().strip()
                break
            time.sleep(0.1)
        if not tok_py:
            print("o servidor Python não subiu:", proc.stderr.read(2000) if proc.poll() is not None else "")
            return 2
        tok_rust = token_do_rust()
        iguais, difs = 0, []
        for nome, met, rota, corpo, com_tok, cab in casos(porta):
            def um(p, tok):
                cc = {k: v.replace("7817", str(p)) for k, v in cab.items()}
                return normal(*pedir(p, met, rota, corpo, tok if com_tok else None, cc))
            r, py = um(RUST, tok_rust), um(porta, tok_py)
            if r == py:
                iguais += 1
            else:
                difs.append((nome, r, py))
        for nome, r, py in difs:
            ver = lambda x: (x[0], x[1] if not isinstance(x[1], bytes) else f"<{len(x[1])} bytes>")  # noqa: E731
            print(f"DIFERENTE — {nome}\n   rust:   {str(ver(r))[:400]}\n   python: {str(ver(py))[:400]}")
        print(f"{iguais + len(difs)} pedidos · iguais: {iguais} · diferentes: {len(difs)}")
        return 0 if not difs else 1
    finally:
        proc.terminate()
        proc.wait(5)


if __name__ == "__main__":
    sys.exit(main())
