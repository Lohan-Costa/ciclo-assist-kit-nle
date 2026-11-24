"""Spike — duas perguntas do editor no Premiere 23.2 (2026-09-22), sem ninguém na frente:

    python spikes/o_source_e_a_descricao.py [--porta 7834]

1. **Dá para pôr o monitor Source num timecode?** (no Media Composer não dá: `SetPosition` não
   existe no 2025.6). O banco só sabe que o Quickture tem uma função
   `setPlayheadPositionInSourceMonitor` — não COMO. Aqui: o que `app.sourceMonitor` e o QE
   (`qe.source`, `qe.source.player`) expõem, por REFLEXÃO, e cada candidato testado com a
   posição lida de volta.
2. **Onde mora a coluna "Descrição" do painel de projeto?** Os campos do metadado de
   projeto do item, as colunas do painel (`getProjectPanelMetadata`), e uma escrita lida de
   volta — no item e no `.prproj` salvo (o arquivo é gzip de XML).

Sai 0 se rodou; a resposta é o relatório (`relatorio.json` na pasta de trabalho).
"""

from __future__ import annotations

import argparse
import gzip
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
TICKS = 254016000000

#: `(rótulo, expressão)` — cada uma tenta pôr o Source em 4 s de um clipe de 10 s a 25 fps.
#: ⚠️ Rodadas em ORDEM, e a posição é zerada (voltando a 0) antes de cada uma.
TENTATIVAS = [
    ("sourceMonitor.setPosition(segundos)", "app.sourceMonitor.setPosition(4)"),
    ("sourceMonitor.setPosition(ticks)", f"app.sourceMonitor.setPosition('{4 * TICKS}')"),
    ("qe.source.player.scrubTo(tc)", "qe.source.player.scrubTo('00:00:04:00')"),
    ("qe.source.player.startScrubbing/scrubTo/endScrubbing",
     "(function(){var p=qe.source.player;p.startScrubbing();p.scrubTo('00:00:04:00');"
     "p.endScrubbing();return 'ok';})()"),
    ("qe.source.player.setPosition(tc)", "qe.source.player.setPosition('00:00:04:00')"),
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

    def tentar(expr: str) -> str:
        return cru("(function(){try{var r=(" + expr + ");return 'OK '+String(r);}"
                   "catch(e){return 'ERRO '+String(e);}})()")

    clipe = TRABALHO / "RELOGIO.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:rate=25:duration=10", "-pix_fmt", "yuv420p",
                    str(clipe)], check=True)

    servidor = subir(args.porta)
    extensao = base.instalar_extensao(args.porta)
    proc = subprocess.Popen([str(base.PREMIERE)])
    t0 = time.monotonic()
    rel: dict = {}
    prproj = TRABALHO / "teste.prproj"
    try:
        while not PT.painel_vivo() and time.monotonic() - t0 < args.prazo:
            time.sleep(0.5)
        print(f"painel vivo: {PT.painel_vivo()} em {time.monotonic() - t0:.0f} s")
        cru(f"String(app.newProject({json.dumps(str(prproj))}))")
        cru("(function(){return String(app.project.importFiles(" + json.dumps([str(clipe)])
            + ", true, app.project.rootItem, false));})()")
        item = "app.project.rootItem.children[0]"

        # ── 1. o monitor Source ──────────────────────────────────────────
        rel["reflect_sourceMonitor"] = tentar(
            "(function(){var m=app.sourceMonitor.reflect.methods,o=[];"
            "for(var i=0;i<m.length;i++)o.push(m[i].name);return o.join(',');})()")
        print("app.sourceMonitor:", rel["reflect_sourceMonitor"])
        rel["enableQE"] = tentar("app.enableQE()")
        for alvo in ("qe.source", "qe.source.player"):
            rel["reflect_" + alvo] = tentar(
                "(function(){var m=" + alvo + ".reflect.methods,o=[];"
                "for(var i=0;i<m.length;i++)o.push(m[i].name);"
                "var p=" + alvo + ".reflect.properties;for(var j=0;j<p.length;j++)o.push('.'+p[j].name);"
                "return o.join(',');})()")
            print(alvo + ":", rel["reflect_" + alvo])

        rel["openProjectItem"] = tentar(f"app.sourceMonitor.openProjectItem({item})")
        print("openProjectItem:", rel["openProjectItem"])
        time.sleep(1)
        posicao = ("(function(){var o={};"
                   "try{var t=app.sourceMonitor.getPosition();o.sm=String(t.seconds);}catch(e){o.sm='ERRO '+e;}"
                   "try{var q=qe.source.player.getPosition();o.qe=String(q.timecode||q);}catch(e){o.qe='ERRO '+e;}"
                   "return cicloJ(o);})()")
        rel["posicao_inicial"] = cru(posicao)
        print("posição inicial:", rel["posicao_inicial"])
        rel["tentativas"] = {}
        for rotulo, expr in TENTATIVAS:
            # volta ao zero pelo mesmo caminho que abriu (fechar e abrir de novo)
            tentar("app.sourceMonitor.closeAllClips()")
            tentar(f"app.sourceMonitor.openProjectItem({item})")
            time.sleep(0.5)
            antes = cru(posicao)
            r = tentar(expr)
            time.sleep(0.8)
            depois = cru(posicao)
            rel["tentativas"][rotulo] = {"resposta": r, "antes": antes, "depois": depois}
            print(f"  {rotulo}: {r} | antes {antes} → depois {depois}")

        # ── 2. a Descrição ───────────────────────────────────────────────
        rel["colunas_do_painel"] = tentar("app.project.getProjectPanelMetadata()")
        colunas = rel["colunas_do_painel"]
        rel["colunas_com_descr"] = sorted({
            p for p in __import__("re").findall(r"[A-Za-z.]*[Dd]escri[a-z.]*", colunas)})
        print("colunas com 'descri':", rel["colunas_com_descr"])
        rel["metadados_antes"] = tentar(f"{item}.getProjectMetadata()")
        texto = "Descrição do Ciclo Assist: close de Personagem F, praia ao fundo"
        rel["escrever"] = tentar(
            "(function(){var it=" + item + ";"
            "if(ExternalObject.AdobeXMPScript===undefined)"
            "ExternalObject.AdobeXMPScript=new ExternalObject('lib:AdobeXMPScript');"
            "var ns='http://ns.adobe.com/premierePrivateProjectMetaData/1.0/';"
            "var x=new XMPMeta(it.getProjectMetadata());"
            "x.setProperty(ns,'Column.PropertyText.Description'," + json.dumps(texto) + ");"
            "it.setProjectMetadata(x.serialize(),['Column.PropertyText.Description']);"
            "var y=new XMPMeta(it.getProjectMetadata());"
            "return String(y.getProperty(ns,'Column.PropertyText.Description'));})()")
        print("escrever Column.PropertyText.Description:", rel["escrever"])
        rel["xmp_do_arquivo_dc_description"] = tentar(
            "(function(){if(ExternalObject.AdobeXMPScript===undefined)"
            "ExternalObject.AdobeXMPScript=new ExternalObject('lib:AdobeXMPScript');"
            "var x=new XMPMeta(" + item + ".getXMPMetadata());"
            "return String(x.getProperty(XMPConst.NS_DC,'description'));})()")
        rel["salvar"] = tentar("app.project.save()")
        time.sleep(2)
        try:
            bruto = gzip.decompress(prproj.read_bytes()).decode("utf-8", "replace")
            i = bruto.find("close de Personagem F")
            rel["no_prproj"] = bruto[max(0, i - 300):i + 80] if i >= 0 else "(não achei o texto)"
        except OSError as e:
            rel["no_prproj"] = f"ERRO {e}"
        print("no .prproj:", rel["no_prproj"][-380:])
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
        (TRABALHO / "relatorio.json").write_text(json.dumps(rel, indent=1, ensure_ascii=False),
                                                 encoding="utf-8")
        print(f"extensão removida: {not extensao.exists()} · {TRABALHO / 'relatorio.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
