"""Prova da exclusão e das melhorias da janela Fluxos e Agentes, com eventos reais de mouse e teclado num Chrome sem janela. Não abre programa nenhum e não gasta IA; os dados são de uma pasta temporária."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
os.environ["CICLOASSIST_DADOS"] = tempfile.mkdtemp(prefix="excluir_")
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H, rotas, receitas as RX  # noqa: E402,F401
from cicloassist.mcp import ferramentas  # noqa: E402,F401
import olhar_painel as O  # noqa: E402

pasta = RX.pasta_do_editor()
pasta.mkdir(parents=True)
PASSOS = [{"id": "a", "op": "salvar_tudo", "args": {}}]
for nome, titulo in (("fluxo-a", "Fluxo A"), ("fluxo-b", "Fluxo B"), ("fluxo-c", "Fluxo C"), ("copia", RX.buscar("preparar-diaria-no-mc").titulo)):
    (pasta / f"{nome}.md").write_text(RX.texto_de(nome, "x", {}, PASSOS, titulo), encoding="utf-8")

PORTA, CDP = 7894, 9379
H.PORTA = PORTA
srv = H.subir(PORTA)
ch = subprocess.Popen([O.achar_chrome(), "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={tempfile.mkdtemp(prefix='excluir_chrome_')}", "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ok = falhou = 0


def conferir(nome, cond, extra=""):
    global ok, falhou
    ok, falhou = ok + bool(cond), falhou + (not cond)
    print(("✅" if cond else "⛔"), nome, extra, flush=True)


try:
    for _ in range(50):
        try:
            alvo = next(a for a in json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json")) if a["type"] == "page")
            break
        except Exception:  # noqa: BLE001
            time.sleep(.2)
    ws = O.WS(alvo["webSocketDebuggerUrl"])
    ws.chamar("Page.enable"); ws.chamar("Runtime.enable")
    A = lambda e: O.avaliar(ws, e)
    ws.chamar("Emulation.setDeviceMetricsOverride", width=1150, height=640, deviceScaleFactor=1, mobile=False)
    ws.chamar("Page.navigate", url=f"http://127.0.0.1:{PORTA}/oficina")
    time.sleep(1.3)

    def foto(nome):
        Path(SAIDA, nome + ".png").write_bytes(base64.b64decode(ws.chamar("Page.captureScreenshot", format="png")["data"]))

    def mover(x, y, botao="none", botoes=0):
        ws.chamar("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button=botao, clickCount=0, buttons=botoes)

    def clique(x, y, n=1):
        mover(x, y)
        for i in range(1, n + 1):
            ws.chamar("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=i, buttons=1)
            ws.chamar("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=i, buttons=0)
        time.sleep(.12)

    def meio(expr):
        return A(f"(function(){{var e=({expr});e.scrollIntoView({{block:'center'}});var r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")

    def em(expr, n=1):
        clique(*meio(expr), n)

    def tecla(key, vk):
        ws.chamar("Input.dispatchKeyEvent", type="keyDown", key=key, code=key, windowsVirtualKeyCode=vk)
        ws.chamar("Input.dispatchKeyEvent", type="keyUp", key=key, code=key, windowsVirtualKeyCode=vk)
        time.sleep(.2)

    def item(t):
        return "Array.from(document.querySelectorAll('.item')).filter(function(b){return b.textContent.indexOf(%s)>=0})[0]" % json.dumps(t)

    def bt(t):
        return "Array.from(document.querySelectorAll('.conf-janela button')).filter(function(b){return b.textContent===%s})[0]" % json.dumps(t)

    def do_menu(t):
        return "Array.from(document.querySelectorAll('.menu-mais button')).filter(function(b){return b.textContent===%s})[0]" % json.dumps(t)

    LIXO = "document.querySelector('.botao.lixeira')"
    janela = lambda: A("(function(){var j=document.querySelector('.conf-janela');return j?j.innerText:''})()")
    existe = lambda n: (pasta / f"{n}.md").exists()
    lista = lambda: A("Array.from(document.querySelectorAll('#listaFluxos .item')).map(function(b){return b.textContent})")

    conferir("fluxos de mesmo título se distinguem na lista", any("do programa" in x for x in lista()) and any(x.endswith("seu") for x in lista()), str(lista()))

    em(item("Fluxo A"), 2)
    em(LIXO)
    t = janela()
    foto("excluir_confirmacao")
    conferir("a lixeira pergunta, com Sim e Cancelar", "Fluxo A" in t and "Sim" in t and "Cancelar" in t, t.replace("\n", " | "))
    conferir("o foco nasce no Cancelar", A("document.activeElement.textContent") == "Cancelar")
    tecla("Escape", 27)
    conferir("Esc fecha sem excluir", janela() == "" and existe("fluxo-a"))
    em(LIXO); em(bt("Cancelar"))
    conferir("Cancelar não exclui", janela() == "" and existe("fluxo-a"))
    em(LIXO); em(bt("Sim")); time.sleep(.4)
    conferir("Sim exclui o arquivo e tira da lista", not existe("fluxo-a") and not any("Fluxo A" in x for x in lista()))
    conferir("outro fluxo fica aberto no lugar", bool(A("!!aberto && aberto.nome !== 'fluxo-a'")))

    em(item("Fluxo B"))
    tecla("Delete", 46)
    conferir("Delete na lista pergunta", "Fluxo B" in janela(), janela().replace("\n", " | "))
    tecla("Delete", 46)
    conferir("Delete de novo, com a janela aberta, não exclui", existe("fluxo-b") and "Fluxo B" in janela())
    em(bt("Sim")); time.sleep(.4)
    conferir("Delete + Sim exclui", not existe("fluxo-b"))

    em(item("Fluxo C"))
    tecla("Backspace", 8)
    conferir("Backspace na lista pergunta", "Fluxo C" in janela())
    em(bt("Cancelar"))

    em(item("Conformar"))
    tecla("Delete", 46)
    conferir("fluxo do programa avisa que dá para restaurar", "restaurar" in janela(), janela().replace("\n", " | "))
    em(bt("Sim")); time.sleep(.4)
    r = A("document.getElementById('restaurarFluxos').textContent")
    conferir("sai da lista e aparece Restaurar", not any("Conformar" in x for x in lista()) and r == "Restaurar fluxos do programa (1)", r)
    em("document.getElementById('restaurarFluxos')"); time.sleep(.5)
    conferir("Restaurar traz de volta", any("Conformar" in x for x in lista()) and bool(A("document.getElementById('restaurarFluxos').hidden")))

    em(item("Agente do piloto"))
    tecla("Delete", 46)
    t = janela()
    foto("excluir_agente")
    conferir("agente do programa explica e não oferece Sim", "não pode ser excluído" in t and "Entendi" in t and "Sim" not in t, t.replace("\n", " | "))
    em(bt("Entendi"))

    em(item("Fluxo C"), 2); time.sleep(.3)
    em("document.querySelector('.node')")
    tecla("Delete", 46)
    conferir("com o clique no quadro, Delete é sobre o node", janela() == "" and A("quadro.g.nos.length") == 0 and existe("fluxo-c"))

    em("document.getElementById('criarFluxo')")
    ws.chamar("Input.insertText", text="Nome do editor")
    tecla("Enter", 13)
    for peca in ("Abrir programa", "Salvar tudo", "Fechar programa"):
        em("document.querySelector('[aria-label=\"Adicionar\"]')")
        em(do_menu("Adicionar Node"))
        em(do_menu(peca))
    d = A("(function(){var n=quadro.g.nos;return [n[1].x-(n[0].x+n[0].l),n[2].x-(n[1].x+n[1].l),n[1].y-n[0].y]})()")
    foto("nodes_lado_a_lado")
    conferir("o node novo nasce ao lado do último, sem cobrir", d[0] > 0 and d[1] > 0 and d[2] == 0, str(d))

    A("(function(){quadro.g.sel=quadro.g.nos[0].id;marcarSel()})()")
    ids = A("quadro.g.nos.map(function(n){return n.id})")
    no, dest = (f"document.querySelector('.node[data-id=\"{i}\"]')" for i in ids[:2])
    mover(*meio(no))
    time.sleep(.1)
    xp, yp = A(f"(function(){{var r=({no}).querySelector('.porta.e').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")
    xd, yd = meio(dest)
    mover(xp, yp)
    ws.chamar("Input.dispatchMouseEvent", type="mousePressed", x=xp, y=yp, button="left", clickCount=1, buttons=1)
    for i in range(1, 11):
        mover(xp + (xd - xp) * i / 10, yp + (yd - yp) * i / 10, "left", 1)
    ws.chamar("Input.dispatchMouseEvent", type="mouseReleased", x=xd, y=yd, button="left", clickCount=1, buttons=0)
    time.sleep(.2)
    conferir("a ligação pega sem usar Organizar", A("quadro.g.fios.length") == 1)

    em("document.getElementById('criarFluxo')")
    ws.chamar("Input.insertText", text="Benchmark do editor")
    tecla("Enter", 13)
    A("aceitarFluxo({d:{titulo:'Título do modelo',novo:true,parametros:{},nos:[],ligacoes:[],resumo:'r'},fluxo:aberto})")
    time.sleep(.2)
    conferir("o nome digitado sobrevive à proposta do chat", A("aberto.titulo") == "Benchmark do editor", str(A("aberto.titulo")))
finally:
    ch.terminate()
    srv.shutdown()
print(f"{ok} ok, {falhou} falharam", flush=True)
sys.exit(1 if falhou else 0)
