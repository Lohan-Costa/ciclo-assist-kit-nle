"""Spike — a vigia do Premiere de ponta a ponta: importou, processou sozinho.

    python spikes/vigia_no_premiere.py [--porta 7834]

Sem ninguém na frente (receita de `spikes/o_painel_no_premiere.py`), com a THREAD de
verdade (`servico/vigia.iniciar`) e o EVENTO de verdade (`onItemsAddedToProjectSuccess`):

1. um projeto descartável com um arquivo JÁ importado (`ANTIGO.mp4`);
2. liga a vigia — ela fotografa o projeto e não processa o antigo;
3. importa `NOVO.mp4` pelo script e mede quanto tempo até a fila começar sozinha;
4. confere que o novo ficou com vetor e o antigo continua sem nada.

Sai 0 se tudo passou.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "spikes"))

import o_painel_no_premiere as base  # noqa: E402

TRABALHO = base.TRABALHO
conferir = base.conferir


def gerar(nome: str, cor: str) -> Path:
    destino = TRABALHO / nome
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={cor}:size=640x360:rate=25:duration=4", "-pix_fmt", "yuv420p",
                    str(destino)], check=True)
    return destino


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=7834)
    ap.add_argument("--prazo", type=int, default=120)
    args = ap.parse_args()
    if not base.porta_livre(args.porta) or base.premiere_aberto():
        print("⛔ porta ocupada ou Premiere aberto.")
        return 2

    (TRABALHO / "cache").mkdir(parents=True)
    modelos = TRABALHO / "dados" / "modelos"
    modelos.mkdir(parents=True)
    shutil.copy2(base.CACHE_REAL.parent / "modelos" / "mobilenetv2-12.onnx", modelos)
    antigo, novo = gerar("ANTIGO.mp4", "red"), gerar("NOVO.mp4", "blue")

    from cicloassist.midia import cache as C
    from cicloassist.nle.premiere import ponte as PT
    from cicloassist.servico import rotas as R
    from cicloassist.servico import tarefas as T
    from cicloassist.servico import vigia as V
    from cicloassist.servico.http import Pedido, subir

    def cru(expr: str, prazo: float = 60) -> str:
        pedido = PT._Pedido(id=f"cru{time.monotonic_ns()}", expr=expr)
        with PT._trava:
            PT._fila.append(pedido)
            PT._esperando[pedido.id] = pedido
            PT._trava.notify_all()
        if not pedido.pronto.wait(prazo):
            raise TimeoutError(expr[:80])
        return pedido.resposta or ""

    def linhas() -> dict:
        r = R.rota_vetores(Pedido("GET", "/vetores", {}, b"", {"nle": "premiere"}))
        return {l["nome"]: l for l in json.loads(r.corpo.decode("utf-8"))["midias"]}

    servidor = subir(args.porta)
    extensao = base.instalar_extensao(args.porta)
    proc = subprocess.Popen([str(base.PREMIERE)])
    t0 = time.monotonic()
    try:
        while not PT.painel_vivo() and time.monotonic() - t0 < args.prazo:
            time.sleep(0.5)
        if not conferir("1. painel vivo", PT.painel_vivo(), f"{time.monotonic() - t0:.0f} s"):
            return 1
        cru(f"String(app.newProject({json.dumps(str(TRABALHO / 'teste.prproj'))}))")
        cru("(function(){return String(app.project.importFiles("
            + json.dumps([str(antigo)]) + ", true, app.project.rootItem, false));})()")

        # 2. ligar: fotografa, não processa
        V.ligar(True)
        time.sleep(V.PULSO_S * 2 + 1)
        e = V.estado()
        conferir("2. ligada, o antigo fotografado e não processado",
                 e["ligada"] and e["projeto"].endswith("teste.prproj") and e["chegaram"] == 0
                 and T.atual() is None, json.dumps(e, ensure_ascii=False))

        # 3. importar e esperar a fila começar sozinha
        t_import = time.monotonic()
        cru("(function(){return String(app.project.importFiles("
            + json.dumps([str(novo)]) + ", true, app.project.rootItem, false));})()")
        comecou = None
        while time.monotonic() - t_import < 30:
            if T.atual() is not None:
                comecou = time.monotonic() - t_import
                break
            time.sleep(0.1)
        conferir("3. a fila começou sozinha depois do import", comecou is not None,
                 f"{comecou:.1f} s depois do import" if comecou else "não começou em 30 s")
        while T.ha_tarefa_viva() and time.monotonic() - t_import < 120:
            time.sleep(0.2)
        t = T.atual()
        conferir("   e disse de onde veio", bool(t and t.resumo.get("vigia")),
                 json.dumps(t.resumo if t else {}, ensure_ascii=False))

        # 4. o resultado
        time.sleep(V.PULSO_S + 1)   # o pulso seguinte encerra as pendências
        por_nome = linhas()
        conferir("4. o NOVO tem vetor", por_nome.get("NOVO.mp4", {}).get("vetor", {}).get("tem"),
                 json.dumps({k: v["vetor"]["tem"] for k, v in por_nome.items()}))
        conferir("   o ANTIGO continua sem nada",
                 not por_nome.get("ANTIGO.mp4", {}).get("vetor", {}).get("tem"))
        conferir("   só uma entrada nova no banco do Premiere",
                 len(C.chaves_da_origem("premiere")) >= 1
                 and not any(l["vetor"]["tem"] for n, l in por_nome.items() if n != "NOVO.mp4"))
        conferir("   nada pendente", V.estado()["pendentes"] == [],
                 json.dumps(V.estado(), ensure_ascii=False))
    finally:
        V.ligar(False)
        try:
            cru("(function(){app.project.closeDocument(0,0);app.quit();return 'ok';})()", prazo=15)
        except Exception as ex:  # noqa: BLE001
            print(f"(fechar falhou: {ex})")
        try:
            proc.wait(timeout=40)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        time.sleep(2)
        shutil.rmtree(extensao, ignore_errors=True)
        servidor.shutdown()
        print(f"extensão removida: {not extensao.exists()} · trabalho em {TRABALHO}")

    criterio = [ok for _, ok, _ in base.resultados]
    return 0 if criterio and all(criterio) else 1


if __name__ == "__main__":
    raise SystemExit(main())
