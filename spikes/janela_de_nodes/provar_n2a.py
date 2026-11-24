"""Prova da N2a: criar e salvar um fluxo só com o mouse (e o teclado para digitar), serviço isolado, CDP com eventos REAIS."""
import base64, json, os, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(prefix="n2_")
os.environ["CICLOASSIST_DADOS"] = TMP
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H, rotas  # noqa
import olhar_painel as O

PORTA = 7898
H.PORTA = PORTA
srv = H.subir(PORTA)
CDP = 9376
perfil = tempfile.mkdtemp(prefix="n2_chrome_")
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
    ws.chamar("Page.enable"); ws.chamar("Runtime.enable")
    ws.chamar("Emulation.setDeviceMetricsOverride", width=1150, height=640, deviceScaleFactor=1, mobile=False)
    ws.chamar("Page.navigate", url=f"http://127.0.0.1:{PORTA}/oficina")
    A = lambda e: O.avaliar(ws, e)

    def esperar_nodes():
        for _ in range(50):
            if A("document.querySelectorAll('.node').length"):
                return
            time.sleep(.1)
    esperar_nodes()

    def foto(nome):
        Path(SAIDA, nome + ".png").write_bytes(base64.b64decode(ws.chamar("Page.captureScreenshot", format="png")["data"]))

    def mouse(tipo, x, y, botao="left", cliques=0, botoes=1):
        ws.chamar("Input.dispatchMouseEvent", type=tipo, x=x, y=y, button=botao, clickCount=cliques, buttons=botoes)

    def clique(x, y, n=1):
        mouse("mouseMoved", x, y, "none", 0, 0)
        for i in range(1, n + 1):
            mouse("mousePressed", x, y, "left", i, 1); mouse("mouseReleased", x, y, "left", i, 0)
        time.sleep(.08)

    def tecla(key, code, vk):
        ws.chamar("Input.dispatchKeyEvent", type="keyDown", key=key, code=code, windowsVirtualKeyCode=vk)
        ws.chamar("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk)
        time.sleep(.08)

    def digitar(t):
        ws.chamar("Input.insertText", text=t); time.sleep(.05)

    def arrastar(x0, y0, x1, y1, passos=12):
        mouse("mouseMoved", x0, y0, "none", 0, 0)
        mouse("mousePressed", x0, y0, "left", 1, 1)
        for i in range(1, passos + 1):
            mouse("mouseMoved", x0 + (x1 - x0) * i / passos, y0 + (y1 - y0) * i / passos, "left", 0, 1)
        mouse("mouseReleased", x1, y1, "left", 1, 0)
        time.sleep(.08)

    def centro_de(expr):
        return A(f"(function(){{var r=({expr}).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")

    TEXTO = "Array.from(document.querySelectorAll('%s')).filter(function(b){return b.textContent.indexOf(%s)>=0})[0]"
    def por_texto(sel, t):
        return TEXTO % (sel, json.dumps(t))
    NODE = lambda t: por_texto(".node", t)
    BOTAO = lambda t: por_texto("button", t)
    def problemas():
        return A("(function(){var c=document.querySelector('.problemas');return c.hidden?null:c.innerText})()")

    conferir("o Executar node saiu", A(BOTAO("Executar node") + "===undefined") and A(BOTAO("Executar fluxo") + "!==undefined"))
    for rec in ("no Media Composer",):
        clique(*centro_de(por_texto(".item", rec)), 2); time.sleep(.1)
    conferir("primeiro node com a borda de início", "inicio" in A(NODE("Abrir programa") + ".className"))
    conferir("último node com a borda de fim", "fim" in A(NODE("Salvar tudo") + ".className"))
    conferir("só um início e um fim", A("document.querySelectorAll('.node.inicio').length") == 1 and A("document.querySelectorAll('.node.fim').length") == 1)
    conferir("Salvar começa desabilitado", A(BOTAO("Salvar fluxo") + ".disabled"))
    foto("n2_pontas")

    # o agente não apaga
    clique(*centro_de(NODE("Agente de revisão")))
    tecla("Delete", "Delete", 46)
    conferir("Delete no gerente é recusado, e diz por quê", A("document.querySelectorAll('.node').length") == 9 and "sem supervisão" in A("document.querySelector('.andamento').textContent"))
    conferir("recusa não suja o fluxo", A(BOTAO("Salvar fluxo") + ".disabled"))

    # criar do zero
    clique(*centro_de("document.getElementById('criarFluxo')")); time.sleep(.15)
    conferir("Criar abre o nome para digitar", A("document.activeElement.className") == "titulo-input")
    digitar("Abrir e salvar")
    tecla("Enter", "Enter", 13)
    conferir("o nome entra", "Abrir e salvar" in A("document.querySelector('h1').textContent"))

    def adicionar(peca):
        clique(*centro_de("document.querySelector('.canto.esq .quadrado')"))
        clique(*centro_de(BOTAO("Adicionar Node")))
        clique(*centro_de(BOTAO(peca) + "||null") if False else centro_de(por_texto(".menu-mais button", peca)))
        time.sleep(.1)

    adicionar("Abrir programa")
    conferir("o node novo abre as Propriedades", A("document.querySelector('.abas .ativa').textContent") == "Propriedades" and A("document.querySelectorAll('.node').length") == 1)
    adicionar("Salvar tudo")
    conferir("dois nodes", A("document.querySelectorAll('.node').length") == 2)
    # afasta um do outro
    x, y = centro_de(NODE("Salvar tudo"))
    arrastar(x, y, x + 150, y + 90)
    a = NODE("Abrir programa")
    clique(*centro_de(a))

    clique(*centro_de(BOTAO("Conferir"))); time.sleep(.3)
    conferir("Conferir diz que não estão ligados", "um node só no começo" in (problemas() or ""), problemas())

    # puxa a ligação do nó leste
    r = A(f"(function(){{var r=({a}).getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]}})()")
    mouse("mouseMoved", (r[0] + r[2]) / 2, (r[1] + r[3]) / 2, "none", 0, 0); time.sleep(.05)
    conferir("o nó de ligação aparece com seleção + mouse em cima", A(f"getComputedStyle(({a}).querySelector('.porta.e')).opacity") == "1")
    xp, yp = centro_de(f"({a}).querySelector('.porta.e')")
    xd, yd = centro_de(NODE("Salvar tudo"))
    mouse("mouseMoved", xp, yp, "none", 0, 0); time.sleep(.05)
    arrastar(xp, yp, xd, yd)
    conferir("puxar cria a ligação", A("quadro.g.fios.length") == 1 and A("quadro.g.fios[0].de") == "abrir_programa" and A("quadro.g.fios[0].para") == "salvar_tudo", A("JSON.stringify(quadro.g.fios.map(function(f){return [f.de,f.para]}))"))
    conferir("com a ligação, início e fim certos", "inicio" in A(a + ".className") and "fim" in A(NODE("Salvar tudo") + ".className"))
    time.sleep(.1)

    clique(*centro_de(BOTAO("Conferir"))); time.sleep(.3)
    conferir("Conferir pega o que falta preencher", "programa" in (problemas() or "") and "projeto" in (problemas() or ""), problemas())

    # preenche: programa (select) e projeto (perguntar)
    clique(*centro_de(a), 2); time.sleep(.1)
    foto("n2_props")
    print(A("document.querySelector('.props').innerText").replace("\n", " | ")[:400])
    A("""(function(){var s=Array.from(document.querySelectorAll('.props .campo')).filter(function(c){return c.textContent.indexOf('Programa')>=0})[0].querySelector('select.entrada');s.value='resolve';s.dispatchEvent(new Event('change'))})()""")
    time.sleep(.1)
    conferir("o node diz o programa escolhido", "DaVinci Resolve" in A(a + ".textContent"))
    sel = "Array.from(document.querySelectorAll('.props .campo')).filter(function(c){return c.textContent.indexOf('Projeto')>=0})[0]"
    A(f"(function(){{var s=({sel}).querySelector('.campo-topo select');s.value='perguntar';s.dispatchEvent(new Event('change'))}})()")
    time.sleep(.1)
    clique(*centro_de(f"({sel}).querySelector('input.entrada')"))
    A(f"({sel}).querySelector('input.entrada').select()")
    digitar("Nome do projeto")
    tecla("Tab", "Tab", 9)
    conferir("a pergunta vira parâmetro", A("quadro.g.parametros.projeto.rotulo") == "Nome do projeto" and A("JSON.stringify(noPorId(quadro.g,'abrir_programa').d.args)") == '{"programa":"resolve","projeto":"{projeto}"}', A("JSON.stringify(quadro.g.parametros)"))
    # o título usa {diaria}, que não existe como parâmetro: conferir tem de aceitar? título não é validado; salva e a execução pede

    clique(*centro_de(BOTAO("Conferir"))); time.sleep(.3)
    conferir("Conferir aprova", "Tudo certo" in (problemas() or ""), problemas())
    conferir("selo de não salvo", not A("document.querySelector('.selo.sujo').hidden"))
    foto("n2_antes_de_salvar")
    clique(*centro_de(BOTAO("Salvar fluxo"))); time.sleep(.6)

    arq = Path(TMP) / "receitas" / "abrir-e-salvar.md"
    conferir("gravou na pasta do editor", arq.is_file())
    if arq.is_file():
        print(arq.read_text(encoding="utf-8"))
        from cicloassist.servico import receitas as RX
        lida = RX.buscar("abrir-e-salvar")
        conferir("o arquivo é lido como receita, sem problema", lida is not None and not lida.problemas and [p["id"] for p in lida.passos] == ["abrir_programa", "salvar_tudo"], str(lida.problemas if lida else ""))
    conferir("a janela reabriu o fluxo salvo", "Abrir e salvar" in A("document.querySelector('h1').textContent") and A(BOTAO("Salvar fluxo") + ".disabled") and A("document.querySelector('.selo.sujo').hidden"))
    conferir("aparece na lista", A(por_texto(".item", "Abrir e salvar") + "!==undefined"))
    pos_antes = A("JSON.stringify(quadro.g.nos.map(function(n){return [n.id,Math.round(n.x)]}))")
    A("location.reload()"); time.sleep(.5); esperar_nodes()
    clique(*centro_de(por_texto(".item", "Abrir e salvar")), 2); time.sleep(.15)
    conferir("posições do fluxo novo sobrevivem", pos_antes == A("JSON.stringify(quadro.g.nos.map(function(n){return [n.id,Math.round(n.x)]}))"))

    # apagar a linha e o node com o teclado
    meio = A("(function(){var p=quadro.g.fios[0].caminho,l=p.getTotalLength(),m=p.getPointAtLength(l/2),v=quadro.g.vista,r=quadro.tela.getBoundingClientRect();return [r.left+v.x+m.x*v.z,r.top+v.y+m.y*v.z]})()")
    clique(meio[0], meio[1])
    conferir("clique seleciona a linha", A("quadro.g.selFio!==null"))
    tecla("Delete", "Delete", 46)
    conferir("Delete apaga a linha", A("quadro.g.fios.length") == 0 and not A(BOTAO("Salvar fluxo") + ".disabled"))
    clique(*centro_de(NODE("Salvar tudo")))
    tecla("Backspace", "Backspace", 8)
    conferir("Backspace apaga o node", A("document.querySelectorAll('.node').length") == 1)

    # Organizar
    clique(*centro_de(por_texto(".item", "no Premiere")), 2); time.sleep(.15)
    x, y = centro_de(NODE("Sincronizar"))
    arrastar(x, y, x + 120, y - 200)
    x1 = A("noPorId(quadro.g,'sync').x")
    clique(*centro_de("document.querySelector('.canto.esq .quadrado')"))
    clique(*centro_de(por_texto(".menu-mais button", "Organizar"))); time.sleep(.1)
    conferir("Organizar devolve o node ao lugar", A("noPorId(quadro.g,'sync').x") != x1, str(A("noPorId(quadro.g,'sync').x")))
    conferir("Organizar não suja o fluxo", A(BOTAO("Salvar fluxo") + ".disabled"))
    print(f"\n{ok} ok, {falhou} falhas")
finally:
    ch.terminate()
    srv.shutdown()
sys.exit(1 if falhou else 0)
