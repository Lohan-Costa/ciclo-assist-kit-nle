"""Spike — o Source na fala e a decupagem na Descrição, pelo CÓDIGO DE PRODUTO, no Premiere.

    python spikes/source_e_descricao_no_premiere.py [--porta 7834]

Os dois spikes anteriores (`o_source_e_a_descricao.py`, `o_source_no_tc.py`) mediram o
Premiere com ExtendScript cru. Este passa pelo que o painel usa: a rota `/busca/carregar`
(com os segundos da fala) e `premiere.sincronizar_descricoes()`. Sem ninguém na frente.

1. um clipe de 25 fps com TC 01:00:00:00, e a entrada dele no banco do Premiere com uma
   decupagem de master;
2. a fala em 4,48 s → a agulha em 4,48 s, LIDA DE VOLTA;
3. a Descrição: escrita; depois um texto "do editor" é respeitado; apagado, volta; e o
   subclipe do mesmo arquivo nunca recebe nada.

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
CAMPO = "Column.PropertyText.Description"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=7834)
    args = ap.parse_args()
    if not base.porta_livre(args.porta) or base.premiere_aberto():
        print("⛔ porta ocupada ou Premiere aberto.")
        return 2
    (TRABALHO / "cache").mkdir(parents=True)
    clipe = TRABALHO / "RELOGIO_1H.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=25:duration=10", "-pix_fmt", "yuv420p",
                    "-timecode", "01:00:00:00", str(clipe)], check=True)

    from cicloassist.midia import identidade as I
    from cicloassist.nle import premiere as P
    from cicloassist.nle.premiere import ponte as PT
    from cicloassist.servico import rotas as R
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

    ITEM = "app.project.rootItem.children[0]"
    XMP = ("if(ExternalObject.AdobeXMPScript===undefined)"
           "ExternalObject.AdobeXMPScript=new ExternalObject('lib:AdobeXMPScript');"
           "var NS='http://ns.adobe.com/premierePrivateProjectMetaData/1.0/';")

    def descricao(item: str = ITEM) -> str:
        return cru("(function(){" + XMP + "var x=new XMPMeta(" + item + ".getProjectMetadata());"
                   f"return x.doesPropertyExist(NS,'{CAMPO}')?String(x.getProperty(NS,'{CAMPO}')):'';}})()")

    def escrever_como_editor(texto: str) -> None:
        cru("(function(){" + XMP + "var it=" + ITEM + ";var x=new XMPMeta(it.getProjectMetadata());"
            f"x.setProperty(NS,'{CAMPO}'," + json.dumps(texto) + ");"
            f"it.setProjectMetadata(x.serialize(),['{CAMPO}']);return 'ok';}})()")

    servidor = subir(args.porta)
    extensao = base.instalar_extensao(args.porta)
    proc = subprocess.Popen([str(base.PREMIERE)])
    t0 = time.monotonic()
    try:
        while not PT.painel_vivo() and time.monotonic() - t0 < 120:
            time.sleep(0.5)
        if not conferir("1. painel vivo", PT.painel_vivo(), f"{time.monotonic() - t0:.0f} s"):
            return 1
        cru(f"String(app.newProject({json.dumps(str(TRABALHO / 't.prproj'))}))")
        cru("(function(){return String(app.project.importFiles(" + json.dumps([str(clipe)])
            + ", true, app.project.rootItem, false));})()")
        # a entrada do banco do Premiere, com uma decupagem de master
        feito = I.aproveitar(clipe, "premiere")
        m = feito.midia
        m.anotar({"trecho": m.nome, "escopo": "midia", "descricao": "Plano de teste: barras e "
                  "relógio; a decupagem que vai para a coluna.", "confianca": "inferido",
                  "fonte": "visual"})
        P.esquecer()

        # 2. a fala → a agulha
        r = R.ROTAS[("POST", "/busca/carregar")][0](Pedido(
            "POST", "/busca/carregar", {},
            json.dumps({"chave": m.chave, "nle": "premiere", "segundos": 4.48}).encode()))
        d = json.loads(r.corpo.decode("utf-8"))
        conferir("2. a fala em 4,48 s põe a agulha em 4,48 s (lido de volta)",
                 d.get("ok") and d.get("posicionado")
                 and abs(float(d.get("posicao_s") or -1) - 4.48) < 0.041,
                 json.dumps(d, ensure_ascii=False))

        # 3. a Descrição
        s1 = P.sincronizar_descricoes()
        conferir("3. a decupagem foi para a coluna", s1.get("escritos") == 1
                 and descricao().startswith("Plano de teste"), f"{s1} · '{descricao()[:40]}'")
        s2 = P.sincronizar_descricoes()
        conferir("   a segunda passada não reescreve", s2.get("escritos") == 0
                 and s2.get("iguais") == 1, str(s2))

        escrever_como_editor("ESCRITO PELO EDITOR")
        m.anotar({"trecho": m.nome, "escopo": "midia", "descricao": "decupagem refeita",
                  "confianca": "inferido", "fonte": "visual"})
        s3 = P.sincronizar_descricoes()
        conferir("   ⛔ o texto do editor é respeitado", descricao() == "ESCRITO PELO EDITOR"
                 and s3.get("do_editor") == 1, f"{s3} · '{descricao()}'")

        # ⚠️ Como se APAGA o campo? Medido na primeira rodada: `setProperty(…, "")` não
        #    apagou (o texto continuou). Tenta-se o vazio e, se não bastar, `deleteProperty`.
        escrever_como_editor("")
        depois_do_vazio = descricao()
        if depois_do_vazio:
            cru("(function(){" + XMP + "var it=" + ITEM + ";var x=new XMPMeta(it.getProjectMetadata());"
                f"x.deleteProperty(NS,'{CAMPO}');"
                f"it.setProjectMetadata(x.serialize(),['{CAMPO}']);return 'ok';}})()")
        conferir("   (medida) como o campo é apagado",
                 descricao() == "", f"setProperty('') deixou '{depois_do_vazio[:30]}'; "
                 f"depois de deleteProperty: '{descricao()[:30]}'")
        s4 = P.sincronizar_descricoes()
        conferir("   apagado pelo editor, volta a ser preenchido",
                 descricao() == "decupagem refeita" and s4.get("escritos") == 1, str(s4))

        T = 254016000000
        cru(f"(function(){{{ITEM}.createSubClip('SUB','{2 * T}','{8 * T}',0,1,1);return 'ok';}})()")
        sub = ("(function(){var r=app.project.rootItem;for(var i=0;i<r.children.numItems;i++)"
               "if(r.children[i].name==='SUB')return r.children[i];return null;})()")
        # o texto do master muda; o subclipe (mesmo arquivo) nunca recebe nada
        m.anotar({"trecho": m.nome, "escopo": "midia", "descricao": "terceira versão",
                  "confianca": "inferido", "fonte": "visual"})
        # ⚠️ Medido na primeira rodada: `createSubClip` COPIA a Descrição do master para o
        #    subclipe. O que se confere é que o sincronizador não MEXE nele.
        antes_sub = descricao(sub)
        s5 = P.sincronizar_descricoes()
        conferir("   ⛔ o sincronizador não mexe no subclipe do mesmo arquivo",
                 descricao(sub) == antes_sub and descricao() == "terceira versão",
                 f"{s5} · subclipe antes '{antes_sub[:30]}' depois '{descricao(sub)[:30]}'")
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
        print(f"extensão removida: {not extensao.exists()} · trabalho em {TRABALHO}")

    criterio = [ok for _, ok, _ in base.resultados]
    return 0 if criterio and all(criterio) else 1


if __name__ == "__main__":
    raise SystemExit(main())
