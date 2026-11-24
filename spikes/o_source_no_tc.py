"""Spike — `qe.source.player.scrubTo` quer o TC do CLIPE ou o tempo desde o início?

    python spikes/o_source_no_tc.py [--porta 7834]

`spikes/o_source_e_a_descricao.py` mediu que `qe.source.player.scrubTo('00:00:04:00')` põe o
Source em 4 s — num clipe cujo TC começa em ZERO, onde as duas leituras dão o mesmo número.
Aqui, clipes que começam em `01:00:00:00` (25 e 23,976 fps): cada forma de escrever o alvo,
com a posição lida de volta em segundos (`app.sourceMonitor.getPosition`) e em TC (QE).

Sai 0 se rodou; a resposta é o relatório.
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
CLIPES = {"TC1H_25.mp4": ("25", "01:00:00:00"), "TC1H_23976.mov": ("24000/1001", "01:00:00:00")}
ALVOS = ["01:00:04:00", "00:00:04:00", "01:00:04:12", "4"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=7834)
    args = ap.parse_args()
    if not base.porta_livre(args.porta) or base.premiere_aberto():
        print("⛔ porta ocupada ou Premiere aberto.")
        return 2
    from cicloassist.midia import identidade as I
    from cicloassist.nle.premiere import ponte as PT
    from cicloassist.servico.http import subir

    def cru(expr: str, prazo: float = 60) -> str:
        pedido = PT._Pedido(id=f"cru{time.monotonic_ns()}", expr=expr)
        with PT._trava:
            PT._fila.append(pedido)
            PT._esperando[pedido.id] = pedido
            PT._trava.notify_all()
        if not pedido.pronto.wait(prazo):
            raise TimeoutError(expr[:80])
        return pedido.resposta or ""

    arquivos = []
    for nome, (taxa, tc) in CLIPES.items():
        a = TRABALHO / nome
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc2=size=320x180:rate={taxa}:duration=10", "-pix_fmt", "yuv420p",
                        "-timecode", tc, str(a)], check=True)
        print(nome, "TC no arquivo (ffprobe):", I.sondar(a).get("tc"))
        arquivos.append(str(a))

    servidor = subir(args.porta)
    extensao = base.instalar_extensao(args.porta)
    proc = subprocess.Popen([str(base.PREMIERE)])
    t0 = time.monotonic()
    rel: dict = {}
    try:
        while not PT.painel_vivo() and time.monotonic() - t0 < 120:
            time.sleep(0.5)
        cru(f"String(app.newProject({json.dumps(str(TRABALHO / 't.prproj'))}))")
        cru("(function(){return String(app.project.importFiles(" + json.dumps(arquivos)
            + ", true, app.project.rootItem, false));})()")
        cru("String(app.enableQE())")
        posicao = ("(function(){var o={};"
                   "try{o.s=String(app.sourceMonitor.getPosition().seconds);}catch(e){o.s='ERRO '+e;}"
                   "try{var q=qe.source.player.getPosition();o.tc=String(q.timecode||q);}catch(e){o.tc='ERRO '+e;}"
                   "return cicloJ(o);})()")
        for i, nome in enumerate(CLIPES):
            item = f"app.project.rootItem.children[{i}]"
            rel[nome] = {"nome_do_item": cru(f"String({item}.name)")}
            # O que o PREMIERE acha que é o início do clipe — sem isto, "o Source mostra
            # 00:00:00:00" pode ser só o Premiere não ter lido o TC que o ffmpeg gravou.
            rel[nome]["media_start"] = cru(
                "(function(){var m=String(" + item + ".getProjectMetadata());"
                "var x=/MediaStart>([^<]*)</.exec(m);var o={meta:x?x[1]:'(sem)'};"
                "try{o.startTime=String(" + item + ".startTime().seconds);}catch(e){o.startTime='ERRO '+e;}"
                "return cicloJ(o);})()")
            print(f"  {nome}: início segundo o Premiere = {rel[nome]['media_start']}")
            for alvo in ALVOS:
                cru(f"(function(){{app.sourceMonitor.openProjectItem({item});"
                    "qe.source.player.scrubTo('00:00:00:00');return 'ok';})()")
                time.sleep(0.4)
                antes = cru(posicao)
                r = cru("(function(){try{return 'OK '+String(qe.source.player.scrubTo("
                        + json.dumps(alvo) + "));}catch(e){return 'ERRO '+e;}})()")
                time.sleep(0.6)
                depois = cru(posicao)
                rel[nome][alvo] = {"r": r, "antes": antes, "depois": depois}
                print(f"  {nome} scrubTo({alvo!r}): {r} | antes {antes} → depois {depois}")
        # ── o SUBCLIPE: o zero é o dele ou o do master? ──────────────────
        # `createSubClip(nome, in, out, hardBoundaries, takeVideo, takeAudio)`, em ticks
        # como TEXTO; ⚠️ ele nasce na RAIZ (banco). 2 s a 8 s do clipe de 25 fps.
        T = 254016000000
        for hard in (0, 1):
            nome_sub = f"SUB_HARD{hard}"
            cru("(function(){var it=app.project.rootItem.children[0];"
                f"it.createSubClip('{nome_sub}','{2 * T}','{8 * T}',{hard},1,1);return 'ok';}})()")
            achar = ("(function(){var r=app.project.rootItem;for(var i=0;i<r.children.numItems;i++)"
                     f"if(r.children[i].name==='{nome_sub}')return r.children[i];return null;}})()")
            rel[nome_sub] = {}
            for alvo in ("00:00:00:00", "00:00:03:00"):
                cru("(function(){app.sourceMonitor.openProjectItem(" + achar + ");"
                    "qe.source.player.scrubTo(" + json.dumps(alvo) + ");return 'ok';})()")
                time.sleep(0.6)
                rel[nome_sub][alvo] = cru(posicao)
                print(f"  {nome_sub} scrubTo({alvo!r}) → {rel[nome_sub][alvo]}")
    finally:
        try:
            cru("(function(){app.project.closeDocument(0,0);app.quit();return 'ok';})()", prazo=15)
        except Exception as e:  # noqa: BLE001
            print(f"(fechar falhou: {e})")
        try:
            proc.wait(timeout=40)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        time.sleep(2)
        shutil.rmtree(extensao, ignore_errors=True)
        servidor.shutdown()
        (TRABALHO / "relatorio.json").write_text(json.dumps(rel, indent=1), encoding="utf-8")
        print(f"extensão removida: {not extensao.exists()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
