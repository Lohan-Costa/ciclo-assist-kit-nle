"""O servidor MCP nativo do Premiere (27.1+): o que cada ação devolve e quanto custa.

Banco: transversal/ia-embarcada-nos-nles.md §3f. O servidor "user" precisa estar ligado
(Preferências ▸ Agents, ou o override da beta feature `PPro.MCP.EnableMCPServer`).

    python spikes/o_mcp_do_premiere.py --saida <pasta>    [--token-arquivo …, se o servidor pedir senha]

Mede no projeto ABERTO (use um descartável): leitura, quadro, busca, transcrição e uma
escrita (sequência nova + inserção de 3 pontos). Sai 0 se todas as etapas responderam.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


class Mcp:
    """Cliente MCP Streamable HTTP mínimo (stdlib), uma sessão."""

    def __init__(self, url: str, token: str):
        self.url, self.token, self.sessao, self._id = url, token, None, 0

    def _post(self, corpo: dict, prazo: float = 120) -> dict | None:
        cab = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": "2025-06-18"}
        if self.token:  # ⭐ na máquina de desenvolvimento a autenticação está desligada (plano §8)
            cab["Authorization"] = f"Bearer {self.token}"
        if self.sessao:
            cab["mcp-session-id"] = self.sessao
        req = urllib.request.Request(self.url, json.dumps(corpo).encode(), cab, method="POST")
        with urllib.request.urlopen(req, timeout=prazo) as r:
            self.sessao = self.sessao or r.headers.get("mcp-session-id")
            texto = r.read().decode("utf-8")
        for linha in texto.splitlines():  # SSE: a resposta vem numa linha "data: {...}"
            if linha.startswith("data: ") and '"jsonrpc"' in linha:
                return json.loads(linha[6:])
        return json.loads(texto) if texto.strip().startswith("{") else None

    def iniciar(self) -> dict:
        r = self._post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "ciclo-assist-spike", "version": "0.1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return r["result"]

    def chamar(self, nome: str, argumentos: dict | None = None, prazo: float = 120) -> tuple[dict, float]:
        self._id += 1
        t = time.perf_counter()
        r = self._post({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                        "params": {"name": nome, "arguments": argumentos or {}}}, prazo)
        dt = time.perf_counter() - t
        if "error" in r:
            return {"_erro_rpc": r["error"]}, dt
        res = r["result"]
        corpo = res.get("structuredContent")
        if corpo is None:
            textos = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
            try:
                corpo = json.loads(textos[0]) if textos else {}
            except (ValueError, IndexError):
                corpo = {"_texto": textos}
        if res.get("isError"):
            corpo = {"_erro": corpo}
        imagens = [c for c in res.get("content", []) if c.get("type") == "image"]
        if imagens:
            corpo = dict(corpo) if isinstance(corpo, dict) else {"_corpo": corpo}
            corpo["_imagens"] = imagens
        return corpo, dt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://[::1]:3000/premiere/mcp")
    ap.add_argument("--token-arquivo", default="", help="sem ele, conecta SEM senha (máquina de desenvolvimento)")
    ap.add_argument("--saida", required=True)
    ap.add_argument("--sem-escrita", action="store_true")
    a = ap.parse_args()
    saida = Path(a.saida).expanduser(); saida.mkdir(parents=True, exist_ok=True)
    token = json.loads(Path(a.token_arquivo).expanduser().read_text())["accessToken"] if a.token_arquivo else ""
    m = Mcp(a.url, token)
    tabela: list[tuple[str, float, str]] = []

    def etapa(rotulo, nome, args=None, prazo=120):
        corpo, dt = m.chamar(nome, args, prazo)
        guardado = {k: v for k, v in corpo.items() if k != "_imagens"} if isinstance(corpo, dict) else corpo
        (saida / f"{len(tabela):02d}_{rotulo}.json").write_text(json.dumps(guardado, ensure_ascii=False, indent=1))
        ok = not (isinstance(corpo, dict) and ("_erro" in corpo or "_erro_rpc" in corpo))
        tabela.append((rotulo, dt, "ok" if ok else "ERRO"))
        print(f"{'✅' if ok else '⛔'} {rotulo:34s} {dt*1000:8.0f} ms  {json.dumps(guardado, ensure_ascii=False)[:220]}")
        return corpo

    info = m.iniciar(); print("servidor:", info["serverInfo"])
    projetos = etapa("getOpenProjects", "getOpenProjects")["projects"]
    pid = next(p for p in projetos if p.get("isActive"))["agentProjectId"]
    etapa("getEditingContext", "getEditingContext")
    itens = etapa("getProjectItems", "getProjectItems", {"agentProjectId": pid}).get("items", [])
    clipes = [i for i in itens if i["type"] == "clip"]
    video = next((i for i in clipes if i["name"].lower().endswith((".mp4", ".mov", ".mxf"))), None)
    som = next((i for i in clipes if i["name"].lower().endswith(".wav") and "falante" not in i["name"]
                and "Aprimorado" not in i["name"]), None)
    seq = next((i for i in itens if i["type"] == "sequence"), None)
    print("vídeo:", video and video["name"], "| som:", som and som["name"], "| seq:", seq and seq["name"])

    ids = [i["itemId"] for i in (video, som) if i]
    etapa("getClipMetadata", "getClipMetadata", {"agentProjectId": pid, "itemIds": ids, "fields": [
        "duration", "start", "frameRate", "width", "height", "codec", "audioChannels", "sampleRate", "filePath"]})
    etapa("getClipMetadata.discover", "getClipMetadata", {"agentProjectId": pid, "itemIds": ids[:1], "mode": "discover"})
    if seq:
        etapa("getSequenceStructure", "getSequenceStructure", {"agentProjectId": pid, "sequenceId": seq["itemId"]})

    if video:
        for w in (640, 1568):
            corpo = etapa(f"renderFrame.{w}", "renderFrame", {"agentProjectId": pid, "itemId": video["itemId"],
                                                             "time": {"seconds": 19.72}, "width": w})
            for n, img in enumerate(corpo.get("_imagens", []) if isinstance(corpo, dict) else []):
                png = base64.b64decode(img["data"])
                (saida / f"quadro_{w}_{n}.png").write_bytes(png)
                print(f"   PNG {len(png)//1024} KB")

    for termo in ("Personagem F", "terapeuta", "claquete", "clapperboard", "mulher sentada"):
        etapa(f"universalSearch.{termo}", "universalSearch", {"query": {"TEXT": {"text": termo}}})

    if som:
        etapa("getTranscript.antes", "getTranscript", {"agentProjectId": pid, "itemId": som["itemId"], "type": "transcript"})
        criado = etapa("createTranscript", "createTranscript", {"agentProjectId": pid, "itemId": som["itemId"],
                                                               "language": "pt-br", "diarization": "channel"})
        pg = isinstance(criado, dict) and (criado.get("progressTrackingId") or criado.get("progressID"))
        t0 = time.perf_counter()
        while pg and time.perf_counter() - t0 < 600:
            c, _ = m.chamar("getProgress", {"progressID": pg})
            estado = json.dumps(c, ensure_ascii=False)
            if any(k in estado.lower() for k in ('"complete', 'done', 'finished', 'succeeded', 'failed', 'error')):
                break
            time.sleep(3)
        if pg:
            tabela.append(("createTranscript→pronto (espera)", time.perf_counter() - t0, estado[:60]))
            print(f"   transcrição: {time.perf_counter()-t0:.1f} s → {estado[:200]}")
        etapa("getTranscript.segments", "getTranscript", {"agentProjectId": pid, "itemId": som["itemId"],
                                                          "type": "transcript", "limit": 20})
        etapa("getTranscript.words", "getTranscript", {"agentProjectId": pid, "itemId": som["itemId"],
                                                       "type": "transcript", "detail": "words", "limit": 40})
        etapa("universalSearch.Personagem F.depois", "universalSearch", {"query": {"TEXT": {"text": "Personagem F"}}})

    etapa("executeMCPScript", "executeMCPScript", {"script":
        "const p = await callMCPTool('getOpenProjects', {});"
        "const id = p.projects[0].agentProjectId;"
        "const it = await callMCPTool('getProjectItems', {agentProjectId: id});"
        "return {projeto: id, itens: it.items.length};"})

    if not a.sem_escrita and video:
        nova = etapa("createSequences", "createSequences", {"agentProjectId": pid, "sequences": [
            {"name": "SEQ MCP TESTE", "clipIds": [video["itemId"]]}]})
        sid = None
        texto = json.dumps(nova)
        for i in m.chamar("getProjectItems", {"agentProjectId": pid})[0]["items"]:
            if i["type"] == "sequence" and i["name"] == "SEQ MCP TESTE":
                sid = i["itemId"]
        if sid:
            etapa("insertClipsToSequence.3pontos", "insertClipsToSequence", {"agentProjectId": pid, "sequenceId": sid,
                  "clips": [{"itemId": video["itemId"], "startTime": "append",
                             "sourceInPoint": {"seconds": 2}, "sourceOutPoint": {"seconds": 8}}]})
            etapa("getSequenceStructure.nova", "getSequenceStructure", {"agentProjectId": pid, "sequenceId": sid})
        else:
            print("⛔ sequência nova não achada:", texto[:300])

    print("\n| ação | ms | estado |\n|---|---:|---|")
    for r, dt, est in tabela:
        print(f"| {r} | {dt*1000:.0f} | {est} |")
    return 0 if all(e == "ok" for _, _, e in tabela if not e.startswith("{")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
