"""A ALAVANCA contra o merged repetido ao reimportar (2026-11-15, Premiere 26.0.2 Mac).

O `importSequences` do 26.0.2 não reconhece um merged que o projeto já tem: o merged do projeto ABERTO tem uma
transcrição VAZIA na impressão, e o que chega pelo Dynamic Link não (banco `plugins/premiere-cep/subclipe-e-merged-clip.md`).
Este spike pega uma SAÍDA já escrita pela Carta, põe um `TranscriptClip` vazio em cada merged
(`merged_prproj.transcricao_vazia`), grava ao lado e reimporta no projeto ATIVO do Premiere pela bancada
(`/carta/premiere/importar_sequencias`), contando os merged antes e depois.

    python spikes/merged_com_transcricao_vazia.py <saida.prproj> <uid da sequência> [--sem-alavanca]

Sai 0 se o número de merged do projeto não cresceu.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cicloassist.carta import entrega_prproj as ep  # noqa: E402
from cicloassist.carta import merged_prproj as mp  # noqa: E402


def _post(rota: str, corpo: dict) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:7824{rota}", json.dumps(corpo).encode(),
                                 {"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"})
    with urllib.request.urlopen(req, timeout=700) as r:
        return json.loads(r.read())


def main() -> int:
    origem, uid = sys.argv[1], sys.argv[2]
    sem = "--sem-alavanca" in sys.argv
    R = ep._ler_prproj(origem)
    por = {(e.get("ObjectID") or e.get("ObjectUID")): e for e in R}
    merged = mp.os_merged(R, por)
    saida = Path(origem).with_name(Path(origem).stem + (" CONTROLE" if sem else " TRANSCRICAO VAZIA") + ".prproj")
    n = 0
    if not sem:
        ids = mp._Ids(R)
        for _cpi, mc in merged:
            n += bool(mp.transcricao_vazia(R, por, mc, ids))
    ep._gravar_prproj(R, str(saida))
    print(f"{len(merged)} merged no arquivo, {n} com a transcrição vazia → {saida.name}")
    ativo = _post("/carta/premiere/projetos", {"acao": "listar"}).get("ativo")
    print("projeto ativo:", ativo)
    r = _post("/carta/premiere/importar_sequencias", {"prproj": str(saida), "uids": [uid]})
    print(json.dumps({k: r.get(k) for k in ("ok", "erro", "motivo", "antes", "depois", "novas")}, ensure_ascii=False))
    a, d = (r.get("antes") or {}), (r.get("depois") or {})
    if not r.get("ok") or r.get("erro"):
        return 2
    print("merged:", a.get("merged"), "→", d.get("merged"))
    return 0 if a.get("merged") is not None and d.get("merged") == a.get("merged") else 1


if __name__ == "__main__":
    sys.exit(main())
