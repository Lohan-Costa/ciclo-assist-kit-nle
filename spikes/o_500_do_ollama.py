"""A `500 unexpected end of JSON input` do Ollama — capturar e reproduzir.

    python spikes/o_500_do_ollama.py capturar            # a FORMA do pedido que o CLI manda
    python spikes/o_500_do_ollama.py repetir <sessao.jsonl> --ate <timestamp> [--vezes 3]

Medido em 2026-09-16 (separar falas da C07, Qwen3-VL no Mac): o Ollama gerava ~4 min e
respondia 500 `unexpected end of JSON input`; o CLI repetia, e a 3ª volta passou.

**capturar** sobe um intermediário em 127.0.0.1 que só REPASSA para o Mac e grava o corpo
de cada pedido e a resposta crua (nenhum modelo roda aqui). O CLI do produto (a mesma
`Sessao`) faz uma pergunta curta através dele: sai o pedido exato — system, tools,
max_tokens, cabeçalhos.

**repetir** pega esse pedido capturado, troca as `messages` pelas da conversa gravada até
`--ate` (a volta que falhou), manda direto ao Mac N vezes, e grava a resposta CRUA de cada
uma, com o tempo de cada evento. É isso que diz se a 500 vem antes do primeiro byte, no
meio do stream, ou no fim — e o que o modelo escreveu até ali.

A saída vai para `--pasta` (padrão: a pasta temporária do sistema).
"""

from __future__ import annotations

import argparse
import http.client
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.motor import percepcao  # noqa: E402


def _repassar(mac: str, pasta: Path):
    alvo = urllib.parse.urlsplit(mac)
    contador = {"n": 0}

    class Intermediario(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def _tudo(self):
            contador["n"] += 1
            n = contador["n"]
            corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            (pasta / f"pedido_{n:02d}.json").write_bytes(corpo)
            (pasta / f"cabecalhos_{n:02d}.json").write_text(
                json.dumps(dict(self.headers), indent=1), encoding="utf-8")
            con = http.client.HTTPConnection(alvo.hostname, alvo.port or 11434, timeout=900)
            cab = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length")}
            con.request(self.command, self.path, body=corpo or None, headers=cab)
            r = con.getresponse()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in ("transfer-encoding", "content-length", "connection"):
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            with open(pasta / f"resposta_{n:02d}.txt", "wb") as f:
                f.write(f"{self.command} {self.path} -> {r.status}\n".encode())
                while True:
                    pedaco = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                    if not pedaco:
                        break
                    f.write(pedaco)
                    self.wfile.write(pedaco)
                    self.wfile.flush()
            con.close()

        do_GET = do_POST = do_HEAD = _tudo

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Intermediario)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def capturar(mac: str, pasta: Path) -> int:
    from cicloassist.mcp.registro import somente_leitura
    from cicloassist.servico import rotas
    from cicloassist.servico.http import subir
    from cicloassist.servico import config as _config
    from cicloassist.motor.sessao import Sessao

    inter = _repassar(mac, pasta)
    proxy = f"http://127.0.0.1:{inter.server_address[1]}"
    # ⚠️ Só aqui: o produto recusa loopback de propósito; o intermediário não roda modelo.
    percepcao.endereco = lambda: proxy
    servidor = subir(0)
    s = Sessao(str(__import__("uuid").uuid4()),
               rotas.url_do_mcp(servidor.server_address[1]), somente_leitura(),
               _config.LOCAL + percepcao.MODELO)
    try:
        for tipo, dado in s.perguntar("responda apenas: ok"):
            if tipo in ("texto", "erro"):
                print(tipo, dado)
    finally:
        s.encerrar()
        servidor.shutdown()
        inter.shutdown()
    print("capturado em", pasta)
    return 0


def mensagens_da_sessao(jsonl: Path, ate: str, anexos: bool = True) -> list[dict]:
    """As mensagens da API reconstruídas do transcript, até `ate` (exclusivo).

    ⚠️ O transcript grava um bloco por linha; linhas seguidas do mesmo papel viram UMA
    mensagem, que é como o CLI as manda.
    """
    msgs: list[dict] = []
    for linha in jsonl.read_text(encoding="utf-8").splitlines():
        e = json.loads(linha)
        if e.get("timestamp") and e["timestamp"] >= ate:
            break
        # ⚠️ Os anexos (`<system-reminder>`) viram texto na mensagem do usuário — e com o
        #    modelo quase determinístico, deixá-los de fora muda a escolha dele.
        if e.get("type") == "attachment" and e.get("rendered") and anexos:
            blocos = [{"type": "text", "text": r["content"]} for r in e["rendered"]]
            if msgs and msgs[-1]["role"] == "user":
                msgs[-1]["content"] += blocos
            else:
                msgs.append({"role": "user", "content": blocos})
            continue
        if e.get("type") not in ("user", "assistant") or e.get("isMeta"):
            continue
        m = e.get("message") or {}
        conteudo = m.get("content")
        if isinstance(conteudo, str):
            conteudo = [{"type": "text", "text": conteudo}]
        conteudo = [b for b in (conteudo or []) if b.get("type") != "thinking"]
        if not conteudo:
            continue
        if msgs and msgs[-1]["role"] == m["role"]:
            msgs[-1]["content"] += conteudo
        else:
            msgs.append({"role": m["role"], "content": list(conteudo)})
    return msgs


def repetir(mac: str, pasta: Path, jsonl: Path, ate: str, vezes: int,
            molde: Path, forcar: str = "") -> int:
    corpo = json.loads(molde.read_text(encoding="utf-8"))
    if forcar:
        corpo["tool_choice"] = {"type": "tool", "name": forcar}
    # ⚠️ O CLI 2.1.273 põe uma mensagem de papel `system` (o ambiente) logo depois da
    #    primeira do usuário (beta `mid-conversation-system`); o transcript não a grava.
    sistema = [m for m in corpo["messages"] if m["role"] == "system"]
    msgs = mensagens_da_sessao(jsonl, ate)
    corpo["messages"] = msgs[:1] + sistema + msgs[1:]
    print(f"{len(corpo['messages'])} mensagens; última: {corpo['messages'][-1]['role']}; "
          f"max_tokens={corpo.get('max_tokens')}; stream={corpo.get('stream')}; "
          f"{len(corpo.get('tools') or [])} ferramentas; {len(json.dumps(corpo))} bytes")
    (pasta / "repetido.json").write_text(json.dumps(corpo, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    alvo = urllib.parse.urlsplit(mac)
    for i in range(1, vezes + 1):
        comeco = time.monotonic()
        con = http.client.HTTPConnection(alvo.hostname, alvo.port or 11434, timeout=900)
        con.request("POST", "/v1/messages", body=json.dumps(corpo).encode(),
                    headers={"Content-Type": "application/json", "x-api-key": "ollama",
                             "anthropic-version": "2023-06-01"})
        r = con.getresponse()
        t_cab = time.monotonic() - comeco
        saida = pasta / f"repeticao{'_' + forcar.split('__')[-1] if forcar else ''}_{i:02d}.txt"
        tipos: dict[str, int] = {}
        primeiro = None
        with open(saida, "w", encoding="utf-8") as f:
            f.write(f"status {r.status} em {t_cab:.1f}s\n")
            for linha in r:
                agora = time.monotonic() - comeco
                texto = linha.decode("utf-8", "replace")
                f.write(f"[{agora:7.1f}] {texto}")
                if texto.startswith("event: "):
                    ev = texto[7:].strip()
                    tipos[ev] = tipos.get(ev, 0) + 1
                    if primeiro is None and ev == "content_block_delta":
                        primeiro = agora
        total = time.monotonic() - comeco
        print(f"#{i}: status {r.status} (cabeçalho em {t_cab:.1f}s), fim {total:.1f}s, "
              f"1º delta {primeiro and round(primeiro, 1)}s, eventos {tipos} → {saida.name}")
        con.close()
    return 0


def _com_espacos(obj) -> str:
    """O `marshalWithSpaces` do Ollama: `json.Marshal` do Go (acento cru, `<>&` escapados),
    com espaço depois de `:` e `,` fora de string."""
    t = json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))
    return (t.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _propriedade(p: dict) -> dict:
    """`api.ToolProperty`: só os campos do struct, na ordem dele — o resto o Go descarta."""
    out: dict = {}
    if p.get("anyOf"):
        out["anyOf"] = [_propriedade(x) for x in p["anyOf"]]
    if p.get("type"):
        out["type"] = p["type"]
    if p.get("items") is not None:
        out["items"] = p["items"]
    if p.get("description"):
        out["description"] = p["description"]
    if p.get("enum"):
        out["enum"] = p["enum"]
    if p.get("properties") is not None:
        out["properties"] = {k: _propriedade(v) for k, v in p["properties"].items()}
    if p.get("required"):
        out["required"] = p["required"]
    return out


def _ollama(corpo: dict) -> list[dict]:
    """`anthropic.FromMessagesRequest`: o pedido Anthropic nas mensagens do Ollama.

    Fiel ao código do Ollama (main, 2026-09-16): o system é a CONCATENAÇÃO dos blocos, sem
    separador; numa mensagem do usuário os `tool_result` viram mensagens `tool` ANTES do
    texto que vinha junto (os `<system-reminder>`), e os textos se juntam sem separador.
    """
    def texto(c) -> str:
        if isinstance(c, str):
            return c
        return "".join(b.get("text", "") for b in c or [] if b.get("type") == "text")

    msgs = []
    sistema = texto(corpo.get("system") or "")
    if sistema:
        msgs.append({"role": "system", "content": sistema})
    for m in corpo["messages"]:
        blocos = m["content"] if isinstance(m["content"], list) else [
            {"type": "text", "text": m["content"]}]
        conteudo = "".join(b.get("text", "") for b in blocos if b.get("type") == "text")
        chamadas = [{"name": b["name"], "arguments": b["input"]}
                    for b in blocos if b.get("type") == "tool_use"]
        resultados = [{"role": "tool", "content": texto(b.get("content"))}
                      for b in blocos if b.get("type") == "tool_result"]
        if m["role"] == "user":
            msgs += resultados
        if conteudo or chamadas:
            msgs.append({"role": m["role"], "content": conteudo, "tool_calls": chamadas})
        if m["role"] != "user":
            msgs += resultados
    return msgs


def _ferramenta(t: dict) -> dict:
    esquema = t.get("input_schema") or {}
    params = {"type": esquema.get("type", "object")}
    if esquema.get("$defs") is not None:
        params["$defs"] = esquema["$defs"]
    if esquema.get("items") is not None:
        params["items"] = esquema["items"]
    if esquema.get("required"):
        params["required"] = esquema["required"]
    params["properties"] = {k: _propriedade(v)
                            for k, v in (esquema.get("properties") or {}).items()}
    return {"type": "function", "function": {
        "name": t["name"], "description": t.get("description", ""), "parameters": params}}


def _qwen(corpo: dict) -> str:
    """`Qwen3VLRenderer.Render` (instruct, sem think) sobre `_ollama(corpo)`.

    ⚠️ Os bytes do JSON das ferramentas podem diferir (ordem de campo do Go); a
    estrutura, os marcadores e a ordem das mensagens são os do Ollama.
    """
    msgs = _ollama(corpo)
    out = []
    tools = corpo.get("tools") or []
    out.append("<|im_start|>system\n")
    if msgs and msgs[0]["role"] == "system":
        out.append(msgs[0]["content"] + "\n\n")
    out.append("# Tools\n\nYou may call one or more functions to assist with the user query."
               "\n\nYou are provided with function signatures within <tools></tools> XML "
               "tags:\n<tools>")
    for t in tools:
        out.append("\n" + _com_espacos(_ferramenta(t)))
    out.append("\n</tools>\n\nFor each function call, return a json object with function "
               "name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n"
               '{"name": <function-name>, "arguments": <args-json-object>}\n'
               "</tool_call><|im_end|>\n")
    for i, m in enumerate(msgs):
        if m["role"] == "user" or (m["role"] == "system" and i != 0):
            out.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n")
        elif m["role"] == "assistant":
            out.append("<|im_start|>assistant\n" + m["content"])
            for k, c in enumerate(m["tool_calls"]):
                if k > 0 or m["content"]:
                    out.append("\n")
                out.append('<tool_call>\n{"name": "' + c["name"] + '", "arguments": '
                           # `map[string]any` no Go: chaves em ordem alfabética.
                           + _com_espacos(json.loads(json.dumps(c["arguments"],
                                                                sort_keys=True)))
                           + "}\n</tool_call>")
            out.append("<|im_end|>\n")
        elif m["role"] == "tool":
            if i == 0 or msgs[i - 1]["role"] != "tool":
                out.append("<|im_start|>user")
            out.append("\n<tool_response>\n" + m["content"] + "\n</tool_response>")
            if i == len(msgs) - 1 or msgs[i + 1]["role"] != "tool":
                out.append("<|im_end|>\n")
    out.append("<|im_start|>assistant\n")
    return "".join(out)

def cru(mac: str, pasta: Path, repetido: Path, vezes: int) -> int:
    """Gera SEM o parser do Ollama e confere se o `<tool_call>` é JSON válido."""
    import re
    corpo = json.loads(repetido.read_text(encoding="utf-8"))
    prompt = _qwen(corpo)
    (pasta / "prompt_qwen.txt").write_text(prompt, encoding="utf-8")
    alvo = urllib.parse.urlsplit(mac)
    for i in range(1, vezes + 1):
        comeco = time.monotonic()
        con = http.client.HTTPConnection(alvo.hostname, alvo.port or 11434, timeout=1800)
        con.request("POST", "/api/generate", body=json.dumps({
            "model": corpo["model"], "prompt": prompt, "raw": True, "stream": True,
            "options": {"num_ctx": 40960, "temperature": 1, "top_p": 0.95, "top_k": 20},
        }).encode(), headers={"Content-Type": "application/json"})
        r = con.getresponse()
        gerado, fim = [], {}
        saida = open(pasta / f"cru_{i:02d}.txt", "w", encoding="utf-8")
        for linha in r:
            ev = json.loads(linha)
            pedaco = ev.get("response", "")
            gerado.append(pedaco)
            saida.write(pedaco)
            saida.flush()
            if len(gerado) % 500 == 0:
                print(f"   {len(gerado)} pedaços em {time.monotonic() - comeco:.0f} s",
                      flush=True)
            if ev.get("done"):
                fim = ev
        saida.close()
        con.close()
        texto_ = "".join(gerado)
        chamadas = re.findall(r"<tool_call>(.*?)(?:</tool_call>|$)", texto_, re.S)
        veredito = []
        for c in chamadas:
            try:
                j = json.loads(c)
                veredito.append(f"ok {j.get('name')} ({len(c)} chars)")
            except ValueError as e:
                veredito.append(f"INVÁLIDO ({len(c)} chars): {e}")
        print(f"#{i}: {time.monotonic() - comeco:.0f} s · done_reason={fim.get('done_reason')} "
              f"· prompt {fim.get('prompt_eval_count')} tok · gerados {fim.get('eval_count')} tok "
              f"em {(fim.get('eval_duration') or 0) / 1e9:.0f} s · {len(texto_)} chars · "
              f"chamadas: {veredito or 'nenhuma'}", flush=True)
        print("   fim do texto:", repr(texto_[-300:]), flush=True)
    return 0

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=("capturar", "repetir", "cru"))
    ap.add_argument("jsonl", nargs="?")
    ap.add_argument("--ate", default="")
    ap.add_argument("--vezes", type=int, default=3)
    ap.add_argument("--molde", default="")
    ap.add_argument("--mac", default="")
    ap.add_argument("--forcar", default="",
                    help="tool_choice: obriga esta ferramenta (ex.: mcp__ciclo__separar_falas)")
    ap.add_argument("--pasta", default=str(Path(tempfile.gettempdir()) / "o_500_do_ollama"))
    a = ap.parse_args()
    mac = percepcao.validar(a.mac) if a.mac else percepcao.endereco()
    if not mac:
        sys.exit("sem endereço do Mac")
    pasta = Path(a.pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    if a.modo == "capturar":
        return capturar(mac, pasta)
    if a.modo == "cru":
        return cru(mac, pasta, Path(a.jsonl), a.vezes)
    molde = Path(a.molde) if a.molde else pasta / "pedido_01.json"
    return repetir(mac, pasta, Path(a.jsonl), a.ate, a.vezes, molde, a.forcar)


if __name__ == "__main__":
    raise SystemExit(main())
