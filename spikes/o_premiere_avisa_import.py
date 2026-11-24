"""Spike — o Premiere AVISA quando algo é importado? E quanto custa perguntar?

    python spikes/o_premiere_avisa_import.py [--porta 7834]

A pergunta vem da vigia da aba Vetores ("importou no Premiere, processa sozinho"). O banco
(`plugins/premiere-cep/api-extendscript.md`) conhece TRÊS nomes de `app.bind` e diz que a
lista completa é `pendente` — "a pergunta mais valiosa que sobrou". Aqui:

1. registra `app.bind` para uma lista de nomes candidatos, cada um somando num contador
   próprio em `$.global`;
2. importa um arquivo (pela API, `importFiles`) e confere quais contadores andaram;
3. mede o custo de `cicloMidias` (a varredura do projeto) com poucos e com ~60 itens —
   é o plano B: perguntar de tempos em tempos.

⚠️ O import é por SCRIPT, não pelo menu. Um evento que só dispara no import da interface
não apareceria aqui — e isso fica dito no resultado.

Sai 0 se rodou até o fim (a resposta é o relatório, não um veredito).
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
CANDIDATOS = [
    # os três que o banco já conhece (controle: não devem andar num import)
    "onActiveSequenceChanged", "onSequenceActivated", "onSourceClipSelectedInProjectPanel",
    # candidatos a import / mudança de projeto
    "onItemAddedToProjectSuccess", "onItemsAddedToProjectSuccess", "onItemAddedToProject",
    "onProjectChanged", "onProjectItemAdded", "onImportFinished", "onItemImported",
    "onProjectDirty", "onProjectDirtyStateChanged", "onProjectEndDrop",
    "onEncoderJobComplete", "onProjectPanelSelectionChanged",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=7834)
    ap.add_argument("--prazo", type=int, default=120)
    args = ap.parse_args()
    if not base.porta_livre(args.porta) or base.premiere_aberto():
        print("⛔ porta ocupada ou Premiere aberto.")
        return 2

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

    # Material: um arquivo para o import que se observa, e ~60 cópias pequenas para a
    # medida de custo da varredura.
    pasta = TRABALHO / "midia"
    pasta.mkdir(parents=True)
    um = pasta / "IMPORTADO.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=25:duration=2", "-pix_fmt", "yuv420p",
                    str(um)], check=True)
    muitos = []
    for i in range(60):
        c = pasta / f"COPIA_{i:02d}.mp4"
        shutil.copy2(um, c)
        muitos.append(str(c))

    servidor = subir(args.porta)
    extensao = base.instalar_extensao(args.porta)
    proc = subprocess.Popen([str(base.PREMIERE)])
    t0 = time.monotonic()
    relatorio: dict = {}
    try:
        while not PT.painel_vivo() and time.monotonic() - t0 < args.prazo:
            time.sleep(0.5)
        print(f"painel vivo: {PT.painel_vivo()} em {time.monotonic() - t0:.0f} s")
        prproj = TRABALHO / "teste.prproj"
        print("newProject:", cru(f"String(app.newProject({json.dumps(str(prproj))}))"))

        # 1. os binds
        binds = cru(
            "(function(){$.global.cicloVistos={};var r={};var n=" + json.dumps(CANDIDATOS) + ";"
            "for(var i=0;i<n.length;i++){(function(nome){$.global.cicloVistos[nome]=0;"
            "try{r[nome]=String(app.bind(nome,function(){$.global.cicloVistos[nome]++;}));}"
            "catch(e){r[nome]='ERRO '+String(e);}})(n[i]);}"
            "return cicloJ(r);})()")
        relatorio["bind_devolveu"] = json.loads(binds)
        print("app.bind devolveu:", binds)

        # 2. importar e ver quem andou
        print("import:", cru("(function(){return String(app.project.importFiles("
                             + json.dumps([str(um)]) + ", true, app.project.rootItem, false));})()",
                             prazo=60))
        time.sleep(3)
        andou = json.loads(cru("cicloJ($.global.cicloVistos)"))
        relatorio["depois_do_import"] = andou
        print("contadores depois do import:", {k: v for k, v in andou.items() if v})

        # 3. o custo da varredura
        def medir(rotulo: str) -> None:
            vezes = []
            for _ in range(5):
                t = time.perf_counter()
                r = PT.chamar("cicloMidias", prazo=60)
                vezes.append(time.perf_counter() - t)
            relatorio[rotulo] = {"itens": len(r.get("arquivos") or []),
                                 "ms": [round(v * 1000, 1) for v in vezes]}
            print(rotulo, relatorio[rotulo])

        medir("cicloMidias_1_item")
        cru("(function(){var b=app.project.rootItem.createBin('MUITOS');return String("
            "app.project.importFiles(" + json.dumps(muitos) + ", true, b, false));})()",
            prazo=180)
        time.sleep(2)
        andou2 = json.loads(cru("cicloJ($.global.cicloVistos)"))
        relatorio["depois_de_60"] = andou2
        print("contadores depois de 60 imports:", {k: v for k, v in andou2.items() if v})
        medir("cicloMidias_61_itens")
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
        (TRABALHO / "relatorio.json").write_text(json.dumps(relatorio, indent=2), encoding="utf-8")
        print(f"extensão removida: {not extensao.exists()} · relatório em {TRABALHO / 'relatorio.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
