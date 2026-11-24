"""Prova da janela de nodes no WEBKIT (o motor da janela do app no Mac): Safari por WebDriver.

O Chrome do Mac não é o WKWebView do Tauri. As dúvidas da N0 eram do WebKit: `svg` com `overflow: visible`,
`setPointerCapture` no arrasto, e o `fetch` em fluxo do chat. O mouse vem das AÇÕES do WebDriver, que o Safari
entrega pelo caminho de evento do próprio WebKit (não é `dispatchEvent` sintético).

Exige, uma vez: Safari › Ajustes › Avançado › "Mostrar recursos para desenvolvedores web", e na aba Desenvolvedor
"Permitir automação remota". Uso: `.venv/bin/python spikes/janela_de_nodes/provar_webkit.py` — sai 0 se passou.
"""
import base64, json, os, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ)]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
os.environ["CICLOASSIST_DADOS"] = tempfile.mkdtemp(prefix="webkit_")
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H
from cicloassist.servico import rotas  # noqa

PORTA, WD = 7892, 4457
H.PORTA = PORTA
srv = H.subir(PORTA)
threading.Thread(target=srv.serve_forever, daemon=True).start()
driver = subprocess.Popen(["/usr/bin/safaridriver", "--port", str(WD)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ok = falhou = 0


def conferir(nome, cond, extra=""):
    global ok, falhou
    ok, falhou = ok + bool(cond), falhou + (not cond)
    print(("✅" if cond else "⛔"), nome, extra)


def wd(metodo, caminho, corpo=None):
    req = urllib.request.Request(f"http://127.0.0.1:{WD}{caminho}", method=metodo,
                                 data=None if corpo is None else json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))["value"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode()[:400])


sessao = None
try:
    for _ in range(50):
        try:
            sessao = wd("POST", "/session", {"capabilities": {"alwaysMatch": {"browserName": "safari"}}})["sessionId"]
            break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)
    S = f"/session/{sessao}"
    wd("POST", S + "/window/rect", {"x": 40, "y": 40, "width": 1150, "height": 720})
    wd("POST", S + "/url", {"url": f"http://127.0.0.1:{PORTA}/oficina"})

    def A(expr):
        return wd("POST", S + "/execute/sync", {"script": f"return ({expr});", "args": []})

    for _ in range(50):
        if A("document.querySelectorAll('.node').length"):
            break
        time.sleep(0.1)
    print("motor:", A("navigator.userAgent"))
    print("janela útil:", A("[innerWidth, innerHeight]"))

    def foto(nome):
        Path(SAIDA, nome + ".png").write_bytes(base64.b64decode(wd("GET", S + "/screenshot")))

    def acoes(passos):
        wd("POST", S + "/actions", {"actions": [{"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": passos}]})
        wd("DELETE", S + "/actions")

    def ir(x, y, ms=0):
        return {"type": "pointerMove", "x": int(round(x)), "y": int(round(y)), "origin": "viewport", "duration": ms}

    BAIXO, CIMA = {"type": "pointerDown", "button": 0}, {"type": "pointerUp", "button": 0}

    def clique(x, y, n=1):
        acoes([ir(x, y)] + [BAIXO, CIMA] * n)
        if n == 2:
            # ⛔ MEDIDO (Safari 18.6): o safaridriver NUNCA gera `dblclick` — dois cliques seguidos chegam com
            # `detail` 1 e 1. Limite do instrumento, não do WebKit: o duplo clique de verdade se confere na janela do
            # app com o mouse do sistema. Aqui só se completa o gesto, no elemento sob o ponto.
            A(f"(function(){{var e=document.elementFromPoint({x},{y});e.dispatchEvent(new MouseEvent('dblclick',{{bubbles:true,clientX:{x},clientY:{y},detail:2}}))}})()")
        time.sleep(0.1)

    def arrastar(x0, y0, x1, y1, passos=15):
        acoes([ir(x0, y0), BAIXO] + [ir(x0 + (x1 - x0) * i / passos, y0 + (y1 - y0) * i / passos, 10) for i in range(1, passos + 1)] + [CIMA])
        time.sleep(0.1)

    def centro_de(expr):
        return A(f"(function(){{var r=({expr}).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")

    ITEM = "Array.from(document.querySelectorAll('.item')).filter(function(b){return b.textContent.indexOf(%s)>=0})[0]"
    NODE = "Array.from(document.querySelectorAll('.node')).filter(function(b){return b.querySelector('b').textContent.indexOf(%s)>=0})[0]"
    DENTRO = """(function(){var t=document.querySelector('.tela-nodes').getBoundingClientRect();return Array.from(document.querySelectorAll('.node')).every(function(n){var r=n.getBoundingClientRect();return r.left>=t.left&&r.right<=t.right&&r.top>=t.top&&r.bottom<=t.bottom})})()"""

    conferir("3 fluxos e 3 agentes na lateral", A("document.querySelectorAll('.item').length") >= 5, str(A("document.querySelectorAll('.item').length")))
    for titulo, n, fios in (("Conformar", 2, 1), ("no Media Composer", 9, 9), ("no Premiere", 7, 7)):
        clique(*centro_de(ITEM % json.dumps(titulo)), 2)
        time.sleep(0.2)
        conferir(f"{titulo}: abre com duplo clique", titulo in A("document.querySelector('h1').textContent"))
        conferir(f"{titulo}: {n} nodes", A("document.querySelectorAll('.node').length") == n)
        conferir(f"{titulo}: {fios} linhas com curva", A("Array.from(document.querySelectorAll('.plano svg path')).filter(function(p){return p.getAttribute('stroke')!=='transparent'&&/^M[-\\d.]+ [-\\d.]+ C/.test(p.getAttribute('d'))}).length") == fios)
        conferir(f"{titulo}: enquadrado, todos os nodes à vista", A(DENTRO), A("document.querySelector('.nivel').textContent"))
        foto("webkit_" + titulo.split()[-1])

    clique(*centro_de(ITEM % json.dumps("no Media Composer")), 2); time.sleep(.2)
    conferir("cabeçalho numa linha só no título mais longo", A("document.querySelector('.cabeca').offsetHeight") < 50, str(A("document.querySelector('.cabeca').offsetHeight")))

    # ⭐ svg com overflow visible: as linhas que saem da caixa do svg têm de aparecer. elementFromPoint no meio de uma
    # curva que passa fora da caixa do <svg> diz se o WebKit a desenha e a deixa clicável.
    caixa = A("(function(){var r=document.querySelector('.plano svg').getBoundingClientRect();return [r.width,r.height]})()")
    fora = A("""(function(){var s=document.querySelector('.plano svg'),r=s.getBoundingClientRect(),achou=0,total=0;
      quadro.g.fios.forEach(function(f){var p=f.caminho,L=p.getTotalLength();for(var i=1;i<10;i++){var q=p.getPointAtLength(L*i/10),m=p.getScreenCTM(),
      x=q.x*m.a+q.y*m.c+m.e,y=q.x*m.b+q.y*m.d+m.f;if(x<r.left||x>r.right||y<r.top||y>r.bottom){total++;}}});return [total, getComputedStyle(s).overflow]})()""")
    conferir("svg: overflow visible no WebKit", fora[1] == "visible", f"caixa {caixa}, pontos de linha fora da caixa: {fora[0]}")

    # arrastar node: pointer capture
    x0, y0 = centro_de(NODE % json.dumps("Sincronizar"))
    d0 = A("quadro.g.fios.filter(function(f){return f.para==='sync'})[0].caminho.getAttribute('d')")
    arrastar(x0, y0, x0 + 60, y0 - 30)
    x1, y1 = centro_de(NODE % json.dumps("Sincronizar"))
    conferir("arrastar move o node com o mouse", abs(x1 - x0 - 60) < 3 and abs(y1 - y0 + 30) < 3, f"{x1-x0:.1f},{y1-y0:.1f}")
    conferir("a linha acompanha", d0 != A("quadro.g.fios.filter(function(f){return f.para==='sync'})[0].caminho.getAttribute('d')"))
    conferir("arrastar seleciona", "sel" in A((NODE % json.dumps("Sincronizar")) + ".className"))
    # o mouse sai do node no meio do arrasto (rápido): com pointer capture o node continua indo
    x0, y0 = x1, y1
    acoes([ir(x0, y0), BAIXO, ir(x0 + 150, y0 + 90, 5), CIMA]); time.sleep(.1)
    x1, y1 = centro_de(NODE % json.dumps("Sincronizar"))
    conferir("arrasto rápido (mouse sai do node) ainda leva o node", abs(x1 - x0 - 150) < 3 and abs(y1 - y0 - 90) < 3, f"{x1-x0:.1f},{y1-y0:.1f}")
    acoes([ir(x1, y1), BAIXO, ir(x1 - 150, y1 - 90, 5), CIMA]); time.sleep(.1)

    # arrastar o vazio
    t = A("(function(){var r=document.querySelector('.tela-nodes').getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]})()")
    v0 = A("[quadro.g.vista.x,quadro.g.vista.y]")
    arrastar(t[0] + 10, t[1] + 10, t[0] + 90, t[1] + 50)
    v1 = A("[quadro.g.vista.x,quadro.g.vista.y]")
    conferir("arrastar o vazio move o quadro", abs(v1[0] - v0[0] - 80) < 2 and abs(v1[1] - v0[1] - 40) < 2, str([v1[0] - v0[0], v1[1] - v0[1]]))
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

    # Propriedades pelo duplo clique
    clique(*centro_de(NODE % json.dumps("Importar")), 2)
    time.sleep(.2)
    conferir("duplo clique no node abre Propriedades", A("document.querySelector('.abas .ativa').textContent") == "Propriedades")
    foto("webkit_propriedades")
    seletor = "Array.from(document.querySelectorAll('.props select'))[0]"
    conferir("Propriedades tem os campos", A("document.querySelectorAll('.props select, .props input').length") > 0)

    # alças (também pointer capture)
    a = centro_de("document.getElementById('alcaLateral')")
    w0 = A("document.querySelector('.lateral').offsetWidth")
    arrastar(a[0], a[1], a[0] + 80, a[1])
    conferir("alça da lateral", abs(A("document.querySelector('.lateral').offsetWidth") - w0 - 80) < 3, str(A("document.querySelector('.lateral').offsetWidth")))

    # o chat da janela: o `fetch` em fluxo (sem turno de modelo: só a leitura do corpo em pedaços)
    leitura = A("""(function(){window.__fl=null;fetch('/oficina/dados').then(function(r){if(!r.body||!r.body.getReader){window.__fl='sem getReader';return}
      var l=r.body.getReader(),n=0;(function p(){l.read().then(function(x){if(x.done){window.__fl='ok '+n;return}n+=x.value.length;p()})})()}).catch(function(e){window.__fl='erro '+e})})()""")
    for _ in range(30):
        if A("window.__fl"):
            break
        time.sleep(.1)
    conferir("fetch lê o corpo em fluxo (ReadableStream)", str(A("window.__fl")).startswith("ok"), str(A("window.__fl")))

    # janela mínima
    wd("POST", S + "/window/rect", {"width": 900, "height": 600})
    A("location.reload()"); time.sleep(1)
    for _ in range(30):
        if A("document.querySelectorAll('.node').length"):
            break
        time.sleep(.1)
    print("janela útil:", A("[innerWidth, innerHeight]"))
    conferir("estreita: sem rolagem e o cabeçalho dentro do centro", A("document.documentElement.scrollWidth<=innerWidth&&document.documentElement.scrollHeight<=innerHeight&&Array.from(document.querySelectorAll('.cabeca .botao')).every(function(b){return b.getBoundingClientRect().right<=document.getElementById('centro').getBoundingClientRect().right})"))
    conferir("estreita: todos os nodes à vista", A(DENTRO), A("document.querySelector('.nivel').textContent"))
    foto("webkit_estreita")
finally:
    if sessao:
        try:
            wd("DELETE", f"/session/{sessao}")
        except Exception:
            pass
    driver.terminate()
    srv.shutdown()

print(f"\n{ok} ok, {falhou} falhas · fotos em {SAIDA}")
sys.exit(1 if falhou else 0)
