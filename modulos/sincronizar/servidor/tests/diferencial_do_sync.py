"""O diferencial do SYNC: a mesma diária real sincronizada pelo Órbita em Rust (7817) e pelo servidor Python.

    python diferencial_do_sync.py <pasta da diária> [porta do python, padrão 7827]

Cada subpasta da diária é uma fonte (como a Preparar manda: rótulo = nome da pasta, `group_order` = a ordem natural),
o som é quem `/sources` diz que é. Os dois recebem o MESMO `/syncmap`, um depois do outro (o motor faz um por vez e
o cache de forma de onda é o mesmo — o segundo só é mais rápido), e os mapas são comparados inteiros. Sai 0 se iguais.

O motor é o mesmo código nos dois lados (o `src-python` do Órbita entrou com o histórico): o que este diferencial
confere é o ENCANAMENTO — os parâmetros montados, a fila, o progresso, o resultado guardado e devolvido.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diferencial_das_rotas import AQUI, RUST, pedir, token_do_rust  # noqa: E402


def iguais(a, b, caminho="", difs=None):
    """Igualdade estrutural; float com tolerância relativa de 1e-6. ⚠️ MEDIDO (2026-11-07, PRODE MIDIA MULTCAM): a
    `confidence` sai diferente na 9ª casa entre duas rodadas — ruído de ponto flutuante do motor, não do
    encanamento. Offsets, takes e grupos têm de bater EXATOS (inteiros e textos não têm tolerância)."""
    difs = [] if difs is None else difs
    if isinstance(a, float) or isinstance(b, float):
        if not (isinstance(a, (int, float)) and isinstance(b, (int, float))) or abs(a - b) > 1e-6 * max(1, abs(a)):
            difs.append((caminho, a, b))
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            iguais(a.get(k, "<falta>"), b.get(k, "<falta>"), f"{caminho}.{k}", difs)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            iguais(x, y, f"{caminho}[{i}]", difs)
    elif a != b:
        difs.append((caminho, a, b))
    return difs


def esperar(porta, tok, jid, rotulo):
    t0, ultimo = time.time(), ""
    while True:
        st, _, b = pedir(porta, "GET", f"/prproj/status?id={jid}", token=tok)
        s = json.loads(b)
        msg = f"{rotulo}: {s['state']} {s['fraction']:.2f} {s['stage']}"
        if msg != ultimo:
            print(f"  {time.time() - t0:6.1f}s {msg}", flush=True)
            ultimo = msg
        if s["state"] in ("done", "error"):
            return s, time.time() - t0
        time.sleep(1)


def main() -> int:
    diaria = Path(sys.argv[1])
    porta = int(sys.argv[2]) if len(sys.argv) > 2 else 7827
    import fontes as F
    arquivos = {}
    for d, subs, fs in os.walk(diaria):  # cada pasta com mídia é uma fonte (AUDIO/H6, AUDIO/RODE…)
        subs[:] = sorted(x for x in subs if not x.startswith("."))
        m = sorted((str(Path(d) / f) for f in fs if not f.startswith(".") and F.e_midia(f)),
                   key=lambda c: F.chave_natural(Path(c).name))
        if m:
            arquivos[Path(d)] = m
    pastas = list(arquivos)
    todos = [f for fs in arquivos.values() for f in fs]
    dados = tempfile.mkdtemp(prefix="sincronizar-diferencial-")
    env = dict(os.environ, SINCRONIZAR_DADOS=dados)
    proc = subprocess.Popen([sys.executable, str(AQUI / "servidor.py"), "--porta", str(porta)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            p = Path(dados) / "plugin-token"
            if p.is_file() and p.read_text():
                break
            time.sleep(0.1)
        tok_py, tok_rust = (Path(dados) / "plugin-token").read_text().strip(), token_do_rust()
        _, _, b = pedir(RUST, "POST", "/sources", {"paths": todos}, tok_rust)
        sons = {f for g in json.loads(b)["groups"] if g["kind"] == "sound" for f in g["files"]}
        clips = [{"path": f, "group": str(p.relative_to(diaria)).strip(), "group_order": i, **({"kind": "sound"} if f in sons else {})}
                 for p, fs in arquivos.items() for i, f in enumerate(fs)]
        pedido = {"clips": clips, "method": "hybrid"}
        print(f"{len(clips)} clipes em {len(pastas)} fontes ({len(sons)} de som)")
        res = {}
        for rotulo, pt, tok in (("rust", RUST, tok_rust), ("python", porta, tok_py)):
            st, _, b = pedir(pt, "POST", "/syncmap", pedido, tok)
            if st != 200:
                print(rotulo, "recusou:", st, b[:300])
                return 2
            s, dt = esperar(pt, tok, json.loads(b)["job_id"], rotulo)
            res[rotulo] = s
            print(f"{rotulo}: {s['state']} em {dt:.1f} s", s.get("error") or "")
        r, p = res["rust"], res["python"]
        difs = iguais({k: r[k] for k in ("state", "result", "error")}, {k: p[k] for k in ("state", "result", "error")})
        for d in difs[:10]:
            print("  DIF", d)
        if not difs:
            g = (r["result"] or {}).get("groups") or [r["result"]]
            print(f"IGUAIS — {len(g)} diária(s); estado {r['state']}")
            return 0
        Path(tempfile.gettempdir(), "sync_rust.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
        Path(tempfile.gettempdir(), "sync_python.json").write_text(json.dumps(p, indent=1, ensure_ascii=False))
        print("DIFERENTES — os dois mapas em", tempfile.gettempdir())
        return 1
    finally:
        proc.terminate()
        proc.wait(5)


if __name__ == "__main__":
    sys.exit(main())
