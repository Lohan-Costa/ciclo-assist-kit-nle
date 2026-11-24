"""Prova da N0: serviço isolado + Chrome por CDP, com mouse REAL."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(prefix="n0_")
os.environ["CICLOASSIST_DADOS"] = TMP
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H
from cicloassist.servico import rotas  # noqa
import olhar_painel as O

PORTA = 7899
H.PORTA = PORTA
srv = H.subir(PORTA)
import threading
if not any(t.is_alive() and "serve" in t.name for t in threading.enumerate()):
    threading.Thread(target=srv.serve_forever, daemon=True).start()

CDP = 9377
perfil = tempfile.mkdtemp(prefix="n0_chrome_")
ch = subprocess.Popen([O.achar_chrome(), "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={perfil}", "--no-first-run", "--window-size=1150,640", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ok = falhou = 0


def conferir(nome, cond, extra=""):
    global ok, falhou
    ok, falhou = ok + bool(cond), falhou + (not cond)
    print(("✅" if cond else "⛔"), nome, extra)


try:
    for _ in range(50):
        try:
            alvo = next(a for a in json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json")) if a["type"] == "page")
            break
        except Exception:
            time.sleep(0.2)
    ws = O.WS(alvo["webSocketDebuggerUrl"])
    ws.chamar("Page.enable"); ws.chamar("Runtime.enable"); ws.chamar("Performance.enable")
    erros = []
    ws.chamar("Emulation.setDeviceMetricsOverride", width=1150, height=640, deviceScaleFactor=1, mobile=False)
    ws.chamar("Page.navigate", url=f"http://127.0.0.1:{PORTA}/oficina")
    A = lambda e: O.avaliar(ws, e)
    for _ in range(50):
        if A("document.querySelectorAll('.node').length"):
            break
        time.sleep(0.1)

    def foto(nome):
        Path(SAIDA, nome + ".png").write_bytes(base64.b64decode(ws.chamar("Page.captureScreenshot", format="png")["data"]))

    def mouse(tipo, x, y, botao="left", cliques=0, botoes=1):
        ws.chamar("Input.dispatchMouseEvent", type=tipo, x=x, y=y, button=botao, clickCount=cliques, buttons=botoes)

    def clique(x, y, n=1):
        mouse("mouseMoved", x, y, "none", 0, 0)
        for i in range(1, n + 1):
            mouse("mousePressed", x, y, "left", i, 1); mouse("mouseReleased", x, y, "left", i, 0)
        time.sleep(0.05)

    def arrastar(x0, y0, x1, y1, passos=20):
        mouse("mouseMoved", x0, y0, "none", 0, 0)
        mouse("mousePressed", x0, y0, "left", 1, 1)
        for i in range(1, passos + 1):
            mouse("mouseMoved", x0 + (x1 - x0) * i / passos, y0 + (y1 - y0) * i / passos, "left", 0, 1)
        mouse("mouseReleased", x1, y1, "left", 1, 0)
        time.sleep(0.05)

    def centro_de(expr):
        return A(f"(function(){{var r=({expr}).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")

    ITEM = "Array.from(document.querySelectorAll('.item')).filter(function(b){return b.textContent.indexOf(%s)>=0})[0]"
    NODE = "Array.from(document.querySelectorAll('.node')).filter(function(b){return b.querySelector('b').textContent.indexOf(%s)>=0})[0]"
    DENTRO = """(function(){var t=document.querySelector('.tela-nodes').getBoundingClientRect();return Array.from(document.querySelectorAll('.node')).every(function(n){var r=n.getBoundingClientRect();return r.left>=t.left&&r.right<=t.right&&r.top>=t.top&&r.bottom<=t.bottom})})()"""

    itens = A("Array.from(document.querySelectorAll('.item')).map(function(b){return b.textContent})")
    print(itens)
    conferir("3 fluxos e 2 agentes na lateral", len(itens) == 5 or len(itens) >= 5, str(len(itens)))
    for titulo, n, fios in (("Conformar", 2, 1), ("no Media Composer", 9, 9), ("no Premiere", 7, 7)):
        clique(*centro_de(ITEM % json.dumps(titulo)), 2)
        time.sleep(0.1)
        conferir(f"{titulo}: abre com duplo clique", titulo in A("document.querySelector('h1').textContent"))
        conferir(f"{titulo}: {n} nodes", A("document.querySelectorAll('.node').length") == n)
        conferir(f"{titulo}: {fios} linhas com curva", A("Array.from(document.querySelectorAll('.plano svg path')).filter(function(p){return p.getAttribute('stroke')!=='transparent'&&/^M[-\\d.]+ [-\\d.]+ C/.test(p.getAttribute('d'))}).length") == fios)
        conferir(f"{titulo}: enquadrado, todos os nodes à vista", A(DENTRO), A("document.querySelector('.nivel').textContent"))
        foto("n0_" + titulo.split()[-1])

    clique(*centro_de(ITEM % json.dumps("no Media Composer")), 2); time.sleep(.1)
    conferir("cabeçalho numa linha só no título mais longo", A("document.querySelector('.cabeca').offsetHeight") < 50, str(A("document.querySelector('.cabeca').offsetHeight")))
    clique(*centro_de(ITEM % json.dumps("no Premiere")), 2); time.sleep(.1)
    # clique simples
    clique(*centro_de(ITEM % json.dumps("Conformar")))
    conferir("clique simples só seleciona", "no Premiere" in A("document.querySelector('h1').textContent") and "selecionado" in A((ITEM % json.dumps("Conformar")) + ".className"))

    # MC: arrastar node
    clique(*centro_de(ITEM % json.dumps("no Media Composer")), 2)
    time.sleep(0.1)
    x0, y0 = centro_de(NODE % json.dumps("Sincronizar"))
    d0 = A("quadro.g.fios.filter(function(f){return f.para==='sync'})[0].caminho.getAttribute('d')")
    arrastar(x0, y0, x0 + 60, y0 - 30)
    x1, y1 = centro_de(NODE % json.dumps("Sincronizar"))
    conferir("arrastar move o node com o mouse", abs(x1 - x0 - 60) < 2 and abs(y1 - y0 + 30) < 2, f"{x1-x0:.1f},{y1-y0:.1f}")
    conferir("a linha acompanha", d0 != A("quadro.g.fios.filter(function(f){return f.para==='sync'})[0].caminho.getAttribute('d')"))
    conferir("arrastar seleciona", "sel" in A((NODE % json.dumps("Sincronizar")) + ".className"))
    conferir("a etiqueta de dado existe", A("document.querySelector('.rotulo').textContent") == "pasta")

    # arrastar o vazio
    t = A("(function(){var r=document.querySelector('.tela-nodes').getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]})()")
    v0 = A("[quadro.g.vista.x,quadro.g.vista.y]")
    arrastar(t[0] + 10, t[1] + 10, t[0] + 90, t[1] + 50)
    v1 = A("[quadro.g.vista.x,quadro.g.vista.y]")
    conferir("arrastar o vazio move o quadro", abs(v1[0] - v0[0] - 80) < 1 and abs(v1[1] - v0[1] - 40) < 1, str([v1[0] - v0[0], v1[1] - v0[1]]))
    clique(t[0] + 10, t[1] + 10)
    conferir("clique no vazio tira a seleção", A("quadro.g.sel") is None)

    # zoom
    n0 = A("document.querySelector('.nivel').textContent")
    clique(*centro_de("document.querySelector('[aria-label=\"Aumentar zoom\"]')"))
    n1 = A("document.querySelector('.nivel').textContent")
    clique(*centro_de("document.querySelector('[aria-label=\"Diminuir zoom\"]')"))
    clique(*centro_de("document.querySelector('[aria-label=\"Diminuir zoom\"]')"))
    n2 = A("document.querySelector('.nivel').textContent")
    conferir("zoom + e −", int(n1[:-1]) == int(n0[:-1]) + 10 and int(n2[:-1]) == int(n0[:-1]) - 10, f"{n0} {n1} {n2}")

    # reabrir volta como o editor deixou
    v = A("JSON.stringify(quadro.g.vista)")
    clique(*centro_de(ITEM % json.dumps("Conformar")), 2); time.sleep(.1)
    clique(*centro_de(ITEM % json.dumps("no Media Composer")), 2); time.sleep(.1)
    conferir("reabrir mantém zoom e posição", v == A("JSON.stringify(quadro.g.vista)"))

    # Propriedades pelo duplo clique
    clique(*centro_de("document.querySelector('.canto.dir .quadrado')"))
    clique(*centro_de(NODE % json.dumps("Importar")), 2)
    time.sleep(.1)
    conferir("duplo clique abre Propriedades", A("document.querySelector('.abas .ativa').textContent") == "Propriedades")
    print(A("document.querySelector('.props').innerText"))
    foto("n0_propriedades")
    conferir("duas ligações em Recebe", "2 ligações" in A("document.querySelector('.cartao-lig .conta').textContent"))
    clique(*centro_de("document.querySelector('.ligacao')"), 2)
    time.sleep(.1)
    conferir("duplo clique no item leva ao node", A("noAberto.id") == "conv" or A("noAberto.id") == "abrir_mc", A("noAberto.id"))

    # do agente
    clique(*centro_de(NODE % json.dumps("Agente de revisão")), 2); time.sleep(.1)
    clique(*centro_de("Array.from(document.querySelectorAll('.props .botao')).filter(function(b){return b.textContent==='Abrir agente'})[0]")); time.sleep(.1)
    conferir("Abrir agente mostra o .md", A("document.querySelectorAll('.editor .linha').length") > 8 and A("document.querySelector('.selo').textContent") == "somente leitura")
    foto("n0_agente")

    # N1: a posição sobrevive ao recarregar; a falha aparece
    def abrir_mc():
        clique(*centro_de(ITEM % json.dumps("no Media Composer")), 2); time.sleep(.15)

    def esperar_nodes():
        for _ in range(40):
            if A("document.querySelectorAll('.node').length"):
                return
            time.sleep(.1)

    FOTO_POS = "JSON.stringify({n:quadro.g.nos.map(function(n){return [n.id,Math.round(n.x),Math.round(n.y)]}),z:quadro.g.vista.z})"
    abrir_mc()
    x0, y0 = centro_de(NODE % json.dumps("Salvar tudo"))
    arrastar(x0, y0, x0 + 40, y0 + 70)
    clique(*centro_de("document.querySelector('[aria-label=\"Diminuir zoom\"]')"))
    time.sleep(.7)
    antes = A(FOTO_POS)
    A("location.reload()"); time.sleep(.5); esperar_nodes(); time.sleep(.1)
    abrir_mc()
    conferir("N1: nodes e zoom voltam depois de recarregar", antes == A(FOTO_POS), A("document.querySelector('.nivel').textContent"))
    t0 = A("(function(){var r=document.querySelector('.tela-nodes').getBoundingClientRect();return [r.left,r.top]})()")
    conferir("N1: linhas desenhadas na posição salva", A("quadro.g.fios.every(function(f){return /^M/.test(f.caminho.getAttribute('d'))})"))
    clique(*centro_de(NODE % json.dumps("Converter para OP-Atom")), 2); time.sleep(.1)
    txt = A("document.querySelector('.props').innerText")
    conferir("N1: Propriedades diz o programa e o que entrega", "Ocupa o DaVinci Resolve" in txt and "Entrega: pasta" in txt, txt[:0])
    A("window.__f=window.fetch;window.fetch=function(u,o){return o?Promise.reject(new Error('x')):window.__f(u,o)}")
    x0, y0 = centro_de(NODE % json.dumps("Salvar tudo"))
    arrastar(x0, y0, x0 - 10, y0 - 10)
    time.sleep(.6)
    conferir("N1: falha ao gravar aparece na tela", "Não consegui" in A("document.querySelector('.andamento').textContent") and not A("document.querySelector('.andamento').hidden"))
    foto("n1_falha")
    A("window.fetch=window.__f")
    arrastar(x0 - 10, y0 - 10, x0, y0)
    time.sleep(.6)
    conferir("N1: o aviso some quando volta a gravar", A("document.querySelector('.andamento').hidden"))

    # alças
    a = centro_de("document.getElementById('alcaLateral')")
    arrastar(a[0], a[1], a[0] + 80, a[1])
    conferir("alça da lateral", abs(A("document.querySelector('.lateral').offsetWidth") - 280) < 3, str(A("document.querySelector('.lateral').offsetWidth")))
    a = centro_de("document.getElementById('alcaDireita')")
    arrastar(a[0], a[1], a[0] - 60, a[1])
    conferir("alça do painel direito", abs(A("document.querySelector('.direita').offsetWidth") - 330) < 3, str(A("document.querySelector('.direita').offsetWidth")))
    a = centro_de("document.getElementById('alcaMetades')")
    h0 = A("document.getElementById('metadeFluxos').offsetHeight")
    arrastar(a[0], a[1], a[0], a[1] - 80)
    conferir("alça entre as metades", abs(A("document.getElementById('metadeFluxos').offsetHeight") - (h0 - 80)) < 3)

    # janela mínima
    ws.chamar("Emulation.setDeviceMetricsOverride", width=900, height=520, deviceScaleFactor=1, mobile=False)
    A("location.reload()"); time.sleep(.8)
    for _ in range(30):
        if A("document.querySelectorAll('.node').length"): break
        time.sleep(.1)
    conferir("a 900x520 sem rolagem e o cabeçalho dentro do centro", A("document.documentElement.scrollWidth<=900&&document.documentElement.scrollHeight<=520&&Array.from(document.querySelectorAll('.cabeca .botao')).every(function(b){return b.getBoundingClientRect().right<=document.getElementById('centro').getBoundingClientRect().right})"))
    conferir("a 900x520 todos os nodes à vista", A(DENTRO), A("document.querySelector('.nivel').textContent"))
    foto("n0_minima")
    ws.chamar("Emulation.setDeviceMetricsOverride", width=1150, height=640, deviceScaleFactor=1, mobile=False)
    A("location.reload()"); time.sleep(.8)
    for _ in range(30):
        if A("document.querySelectorAll('.node').length"): break
        time.sleep(.1)
    time.sleep(.2)

    # custo do arrasto: Performance.getMetrics é tempo de CPU do processo de render
    def metricas():
        return {m["name"]: m["value"] for m in ws.chamar("Performance.getMetrics")["metrics"]}

    def custo(n_nos):
        A(f"""(function(){{var base=dados.fluxos[1];var nos=[],lig=[];for(var i=0;i<{n_nos};i++){{nos.push({{id:'x'+i,tipo:i%5?'passo':'agente',rotulo:'Passo número '+i,detalhe:'detalhe',campos:[]}});if(i)lig.push({{de:'x'+(i-1),para:'x'+i,tipo:'ordem',campo:''}});}}abrir({{titulo:'Prova',nome:'prova',nos:nos,ligacoes:lig}});}})()""")
        time.sleep(.2)
        A("quadro.g.vista.z=1;aplicarVista()")
        x, y = centro_de("quadro.els['x1']")
        ant = metricas()
        t = time.perf_counter()
        A("window.__q=[];(function f(a){window.__q.push(a);window.__r=requestAnimationFrame(f)})(performance.now())")
        arrastar(x, y, x + 200, y + 100, 120)
        dur = time.perf_counter() - t
        q = A("cancelAnimationFrame(window.__r);window.__q")
        dep = metricas()
        cpu = sum(dep[k] - ant[k] for k in ("ScriptDuration", "LayoutDuration", "RecalcStyleDuration"))
        deltas = sorted(b - a for a, b in zip(q[1:], q[2:]))
        print(f"  {n_nos:4d} nodes: {cpu*1000/120:.2f} ms de CPU por movimento (script+layout+estilo) · {dur:.2f} s · quadros {len(deltas)} · mediana {deltas[len(deltas)//2]:.1f} ms · pior {deltas[-1]:.1f} ms")
        return cpu * 1000 / 120

    print("custo do arrasto:")
    for n in (9, 30, 120):
        custo(n)
    A("abrir(dados.fluxos[1])")

    print(f"\n{ok} ok, {falhou} falhas")
finally:
    ch.terminate()
    srv.shutdown()
sys.exit(1 if falhou else 0)
