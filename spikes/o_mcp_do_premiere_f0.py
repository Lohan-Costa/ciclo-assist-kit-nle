"""F0 do plano `docs/plano/2026-11-06-mcp-do-premiere.md`: o que falta medir no MCP do Premiere.

    piloto/.venv/bin/python spikes/o_mcp_do_premiere_f0.py --token-arquivo ~/ciclo_mcp/prefs_user.json \
        --midia <pasta com sint_23976.mov, sint_25.mov, sint_2997df.mov> --saida <pasta> [--wav <WAV multicanal>]

Os clipes sintéticos trazem o número do quadro em 12 barras binárias (bit k aceso na faixa k), então o
quadro que ENTROU na timeline é lido na imagem do `renderFrame`, não na resposta do servidor.
Precisa do Pillow (o venv do piloto tem). Mexe no projeto ABERTO: use um descartável.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import threading
import time
import urllib.request
from fractions import Fraction
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from o_mcp_do_premiere import Mcp  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
TAXAS = {"sint_23976.mov": Fraction(24000, 1001), "sint_25.mov": Fraction(25), "sint_2997df.mov": Fraction(30000, 1001)}


def quadro_da_imagem(png: bytes) -> int:
    im = Image.open(io.BytesIO(png)).convert("L")
    w, h = im.size
    n = 0
    for k in range(12):
        if im.getpixel((int((k + 0.5) * w / 12), h // 2)) > 128:
            n |= 1 << k
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://[::1]:3000/premiere/mcp")
    ap.add_argument("--token-arquivo", default="", help="sem ele, conecta SEM senha (máquina de desenvolvimento)")
    ap.add_argument("--midia", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--wav", default="")
    ap.add_argument("--servico", default="http://127.0.0.1:7824")
    a = ap.parse_args()
    saida = Path(a.saida).expanduser(); saida.mkdir(parents=True, exist_ok=True)
    token = json.loads(Path(a.token_arquivo).expanduser().read_text())["accessToken"] if a.token_arquivo else ""
    m = Mcp(a.url, token); m.iniciar()
    rel: dict = {}

    def chamar(nome, args=None):
        corpo, dt = m.chamar(nome, args)
        if isinstance(corpo, dict) and ("_erro" in corpo or "_erro_rpc" in corpo):
            print(f"⛔ {nome}: {json.dumps(corpo, ensure_ascii=False)[:400]}")
        return corpo, dt

    pid = chamar("getOpenProjects")[0]["projects"][0]["agentProjectId"]
    itens = lambda: chamar("getProjectItems", {"agentProjectId": pid})[0]["items"]  # noqa: E731

    # ── A. importar os sintéticos numa bin própria ─────────────────────────────────────────────────
    caminhos = [str(Path(a.midia) / n) for n in TAXAS] + ([a.wav] if a.wav else [])
    bin_ = chamar("createBins", {"agentProjectId": pid, "names": ["F0 MCP"]})[0]
    (saida / "createBins.json").write_text(json.dumps(bin_, ensure_ascii=False, indent=1))
    bid = next((i["itemId"] for i in itens() if i["type"] == "bin" and i["name"] == "F0 MCP"), None)
    imp, dt = chamar("importFiles", {"agentProjectId": pid, "filePaths": caminhos, **({"targetBinId": bid} if bid else {})})
    (saida / "importFiles.json").write_text(json.dumps(imp, ensure_ascii=False, indent=1))
    print(f"importFiles {dt*1000:.0f} ms")
    por_nome = {}
    for i in itens():
        if i["type"] == "clip" and i["name"] in set(Path(c).name for c in caminhos):
            por_nome.setdefault(i["name"], i["itemId"])
    print("importados:", list(por_nome))

    md, _ = chamar("getClipMetadata", {"agentProjectId": pid, "itemIds": list(por_nome.values()),
                                         "fields": ["start", "end", "duration", "frameRate", "inPoint", "outPoint", "audioChannels"]})
    (saida / "metadados.json").write_text(json.dumps(md, ensure_ascii=False, indent=1))

    # ── A2. renderFrame no CLIPE: o tempo é do início do clipe? o quadro é o certo? ───────────────────
    rel["render_clipe"] = []
    for nome, fps in TAXAS.items():
        iid = por_nome.get(nome)
        if not iid:
            continue
        for n in (0, 48, 121):
            corpo, _ = chamar("renderFrame", {"agentProjectId": pid, "itemId": iid,
                                              "time": {"seconds": float(Fraction(n) / fps)}, "width": 384})
            png = base64.b64decode(corpo["_imagens"][0]["data"])
            rel["render_clipe"].append({"clipe": nome, "pedido": n, "na_imagem": quadro_da_imagem(png)})
    print("renderFrame no clipe:", rel["render_clipe"])

    # ── A3. inserção de 3 pontos: três formas de mandar o tempo, e o quadro conferido NA IMAGEM ──────
    formas = {"exato": lambda n, f: float(Fraction(n) / f),
              "exato+1us": lambda n, f: float(Fraction(n) / f) + 1e-6,
              "meio_quadro": lambda n, f: float((Fraction(n) + Fraction(1, 2)) / f)}
    rel["insercao"] = []
    for nome, fps in TAXAS.items():
        iid = por_nome.get(nome)
        if not iid:
            continue
        seq_nome = f"F0 SEQ {nome[5:-4]}"
        cs, _ = chamar("createSequences", {"agentProjectId": pid, "sequences": [{"name": seq_nome, "clipIds": [iid]}]})
        sid = (cs.get("createdSequenceIds") or [None])[0]
        if not sid:
            print("⛔ sem sequência", nome, cs); continue
        est, _ = chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": sid, "limit": 0})
        rel.setdefault("sequencias", {})[nome] = {k: v for k, v in est.items() if k != "items"}
        for forma, conta in formas.items():
            for n in (1, 47, 48, 100, 121, 250):
                ini, fim = conta(n, fps), conta(n + 12, fps)
                r, dt = chamar("insertClipsToSequence", {"agentProjectId": pid, "sequenceId": sid, "clips": [
                    {"itemId": iid, "startTime": "append", "sourceInPoint": {"seconds": ini},
                     "sourceOutPoint": {"seconds": fim}, "tracks": [{"trackType": "video", "trackIndex": 0}]}]})
                try:
                    it = r["results"][0]["insertedItems"][0]
                except (KeyError, IndexError, TypeError):
                    rel["insercao"].append({"clipe": nome, "forma": forma, "n": n, "erro": str(r)[:300]}); continue
                s_in = it["sourceInPoint"]["seconds"]; t0 = it["startTime"]["seconds"]; dur = it["duration"]["seconds"]
                # o quadro da TIMELINE logo depois do início do pedaço inserido
                corpo, _ = chamar("renderFrame", {"agentProjectId": pid, "itemId": sid,
                                                  "time": {"seconds": t0 + float(Fraction(1, 4) / fps)}, "width": 384})
                visto = quadro_da_imagem(base64.b64decode(corpo["_imagens"][0]["data"]))
                rel["insercao"].append({"clipe": nome, "forma": forma, "n": n,
                                        "in_devolvido_quadros": round(s_in * fps, 3), "duracao_quadros": round(dur * fps, 3),
                                        "visto_na_imagem": visto, "ms": round(dt * 1000)})
    certos = {}
    for r in rel["insercao"]:
        if "visto_na_imagem" in r:
            certos.setdefault((r["clipe"], r["forma"]), []).append(r["visto_na_imagem"] == r["n"])
    for (c, f), v in certos.items():
        print(f"inserção {c:16s} {f:12s} quadro certo {sum(v)}/{len(v)}")

    # ── B. subclipe: a janela devolvida, e o que entra na timeline ───────────────────────────────────
    if "sint_25.mov" in por_nome:
        iid = por_nome["sint_25.mov"]
        sc, _ = chamar("createSubClips", {"agentProjectId": pid, "clips": [
            {"itemId": iid, "name": "F0 SUB 50-100", "inPoint": {"seconds": 2.0}, "outPoint": {"seconds": 4.0}}]})
        (saida / "createSubClips.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1))
        sub = next((i["itemId"] for i in itens() if i["name"] == "F0 SUB 50-100"), None)
        rel["subclipe"] = {"criado": bool(sub)}
        if sub:
            md, _ = chamar("getClipMetadata", {"agentProjectId": pid, "itemIds": [sub],
                                                 "fields": ["start", "end", "duration", "inPoint", "outPoint", "filePath"]})
            io_, _ = chamar("getInOutPoints", {"agentProjectId": pid, "itemIds": [sub]})
            rel["subclipe"].update({"metadados": md, "inout": io_})
            cs, _ = chamar("createSequences", {"agentProjectId": pid, "sequences": [{"name": "F0 SEQ SUB", "clipIds": [sub]}]})
            sid = (cs.get("createdSequenceIds") or [None])[0]
            if sid:
                est, _ = chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": sid})
                rel["subclipe"]["na_timeline"] = [{k: x.get(k) for k in ("mediaType", "startTime", "endTime", "sourceInPoint", "sourceOutPoint")}
                                                  for x in est.get("items", [])]
                corpo, _ = chamar("renderFrame", {"agentProjectId": pid, "itemId": sid, "time": {"seconds": 0.01}, "width": 384})
                rel["subclipe"]["primeiro_quadro_visto"] = quadro_da_imagem(base64.b64decode(corpo["_imagens"][0]["data"]))
                corpo, _ = chamar("renderFrame", {"agentProjectId": pid, "itemId": sub, "time": {"seconds": 0.01}, "width": 384})
                rel["subclipe"]["render_do_subclipe_t0"] = quadro_da_imagem(base64.b64decode(corpo["_imagens"][0]["data"]))
        print("subclipe:", json.dumps(rel.get("subclipe"), ensure_ascii=False)[:900])

    # ── C. WAV multicanal: em quantas trilhas cai ───────────────────────────────────────────────────
    wav = Path(a.wav).name if a.wav else ""
    if wav and wav in por_nome:
        cs, _ = chamar("createSequences", {"agentProjectId": pid, "sequences": [{"name": "F0 SEQ WAV", "clipIds": [por_nome[wav]]}]})
        sid = (cs.get("createdSequenceIds") or [None])[0]
        est, _ = chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": sid})
        rel["wav_seq_nova"] = {"trilhas": est.get("tracks"), "itens": [(x.get("mediaType"), x.get("trackIndex")) for x in est.get("items", [])]}
        seq25 = next((i["itemId"] for i in itens() if i["name"] == "F0 SEQ 25"), None)
        if seq25:
            r, _ = chamar("insertClipsToSequence", {"agentProjectId": pid, "sequenceId": seq25, "clips": [
                {"itemId": por_nome[wav], "startTime": "append", "sourceInPoint": {"seconds": 10}, "sourceOutPoint": {"seconds": 12}}]})
            rel["wav_em_seq_de_video"] = [(x.get("mediaType"), x.get("trackIndex")) for x in r.get("results", [{}])[0].get("insertedItems", [])] \
                if isinstance(r, dict) else str(r)[:300]
        print("WAV:", json.dumps({k: rel.get(k) for k in ("wav_seq_nova", "wav_em_seq_de_video")}, ensure_ascii=False)[:900])

    # ── D. concorrência: o MCP sozinho, em paralelo, e junto com a ponte CEP (pelo serviço) ─────────
    def lat(n=20):
        v = []
        for _ in range(n):
            _, dt = m.chamar("getProjectItems", {"agentProjectId": pid}); v.append(dt * 1000)
        return sorted(v)
    sozinho = lat()
    paralelos: list[float] = []

    def outro():
        m2 = Mcp(a.url, token); m2.iniciar()
        for _ in range(20):
            _, dt = m2.chamar("getProjectItems", {"agentProjectId": pid}); paralelos.append(dt * 1000)
    ts = [threading.Thread(target=outro) for _ in range(4)]
    t = time.perf_counter(); [x.start() for x in ts]; [x.join() for x in ts]; total_par = time.perf_counter() - t

    def cep():
        req = urllib.request.Request(a.servico + "/vetores?nle=premiere", headers={"Sec-Fetch-Site": "same-origin"})
        t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                r.read(); return time.perf_counter() - t, r.status
        except Exception as e:  # noqa: BLE001
            return time.perf_counter() - t, str(e)[:120]
    cep_so = cep()
    resultado_cep: list = []
    th = threading.Thread(target=lambda: resultado_cep.append(cep())); th.start()
    durante = lat(20); th.join()
    rel["concorrencia"] = {"mcp_sozinho_ms_mediana": sozinho[len(sozinho) // 2], "mcp_sozinho_ms_max": sozinho[-1],
                           "4_sessoes_x20_s": round(total_par, 2), "paralelo_ms_mediana": sorted(paralelos)[len(paralelos) // 2],
                           "paralelo_ms_max": max(paralelos), "cep_vetores_sozinho_s": cep_so, "cep_vetores_com_mcp_s": resultado_cep,
                           "mcp_durante_cep_ms_mediana": durante[len(durante) // 2], "mcp_durante_cep_ms_max": durante[-1]}
    print("concorrência:", json.dumps(rel["concorrencia"], ensure_ascii=False))

    (saida / "relatorio_f0.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1, default=float))
    print("relatório:", saida / "relatorio_f0.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
