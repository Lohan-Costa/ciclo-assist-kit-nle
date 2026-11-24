"""Prova da N4. Parte 1: agente simulado, Perguntar, volta puxada à mão e teto. Parte 2: o agente de metadado de verdade, numa diária real (só lê)."""
import base64, dataclasses, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(prefix="n4_")
os.environ["CICLOASSIST_DADOS"] = TMP
os.environ["CICLOASSIST_CLAUDE_CONFIG"] = str(Path(os.environ["LOCALAPPDATA"]) / "CicloAssist" / "claude")
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H, rotas, fluxo as F, receitas as RX, arrastados as AR  # noqa
from cicloassist.mcp import ferramentas  # noqa
from cicloassist.mcp.registro import FERRAMENTAS as REG
import olhar_painel as O

DIARIA = r"D:\AUDIOS ANALISAR\24Y07M18"
AR.autorizar(DIARIA)
OP = "entender_metadados_da_diaria"
real = REG[OP]
rodadas = []


def simulado(pasta="", bin="", programa="", respostas=None):
    rodadas.append(respostas)
    time.sleep(.6)
    return {"producao": {}, "regras_aprovadas": [], "regras_reprovadas": [], "perguntas": [{"sobre": "T", "texto": "O que quer dizer T nos nomes?", "opcoes": ["Take", "Tomada"]}]}


REG[OP] = dataclasses.replace(real, funcao=simulado)
REG["salvar_tudo"] = dataclasses.replace(REG["salvar_tudo"], funcao=lambda: {"ok": True}, conferir=None)

pasta = RX.pasta_do_editor()
pasta.mkdir(parents=True)
passos = [
    {"id": "m", "op": OP, "args": {"pasta": "{pasta}", "respostas": "{p.respostas}"}},
    {"id": "p", "op": "perguntar_ao_editor", "args": {"perguntas": "{m.perguntas}"}, "se": {"campo": "m.perguntas", "e": "sim"}, "volta": {"para": "m", "teto": 1}},
    {"id": "s", "op": "salvar_tudo", "args": {}, "depois_de": ["m"], "se": {"campo": "m.perguntas", "e": "nao"}},
]
spec = {"pasta": {"tipo": "pasta", "rotulo": "A pasta do som"}}
(pasta / "metadado-com-volta.md").write_text(RX.texto_de("metadado-com-volta", "prova", spec, passos, "Metadado com volta"), encoding="utf-8")
assert not RX.buscar("metadado-com-volta").problemas, RX.buscar("metadado-com-volta").problemas

PORTA = 7895
H.PORTA = PORTA
rotas.url_do_mcp.__defaults__ = (PORTA, "chat")
srv = H.subir(PORTA)
CDP = 9373
perfil = tempfile.mkdtemp(prefix="n4_chrome_")
ch = subprocess.Popen([O.achar_chrome(), "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={perfil}", "--no-first-run", "--window-size=1150,640", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        except Exception:
            time.sleep(0.2)
    ws = O.WS(alvo["webSocketDebuggerUrl"])
    ws.chamar("Page.enable"); ws.chamar("Runtime.enable")
    ws.chamar("Emulation.setDeviceMetricsOverride", width=1150, height=640, deviceScaleFactor=1, mobile=False)
    ws.chamar("Page.navigate", url=f"http://127.0.0.1:{PORTA}/oficina")
    A = lambda e: O.avaliar(ws, e)
    for _ in range(50):
        if A("document.querySelectorAll('.node').length"):
            break
        time.sleep(.1)

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
    BOTAO = lambda t: por_texto("button", t)
    NODE = lambda t: por_texto(".node", t)
    def faixa():
        return A("(function(){var f=quadro.faixa;return f.hidden?null:f.querySelector('.texto').textContent})()")

    def esperar(cond, prazo=30):
        ini = time.time()
        while time.time() - ini < prazo:
            if A(cond):
                return True
            time.sleep(.15)
        return False

    def problemas():
        return A("(function(){var c=document.querySelector('.problemas');return c.hidden?null:c.innerText})()")

    def executar():
        clique(*centro_de(BOTAO("Executar fluxo"))); time.sleep(.15)
        A(f"formExec.valores.pasta={json.dumps(DIARIA)};desenharDireita()"); time.sleep(.1)

    clique(*centro_de(por_texto(".item", "Metadado com volta")), 2); time.sleep(.2)
    conferir("o agente tem a marca de IA e a pergunta a dela", "agente" in A(NODE("Entender") + ".className") and "duvida" in A(NODE("Perguntar") + ".className"))
    conferir("a volta aparece com o teto", A("Array.from(document.querySelectorAll('.rotulo')).some(function(r){return r.textContent.indexOf('volta, até 1x')>=0})"))
    conferir("o último node não é o de pergunta, que volta", "fim" not in A(NODE("Perguntar") + ".className") and "fim" in A(NODE("Salvar tudo") + ".className"), A(NODE("Salvar tudo") + ".className"))
    foto("n4_volta")

    # refaz a volta com o mouse
    meio = A("(function(){var p=quadro.g.fios.filter(function(f){return f.volta})[0].caminho,l=p.getTotalLength(),m=p.getPointAtLength(l/2),v=quadro.g.vista,r=quadro.tela.getBoundingClientRect();return [r.left+v.x+m.x*v.z,r.top+v.y+m.y*v.z]})()")
    clique(meio[0], meio[1]); tecla("Delete", "Delete", 46); time.sleep(.1)
    conferir("apagou a volta", A("quadro.g.fios.filter(function(f){return f.volta}).length") == 0)
    a = NODE("Perguntar")
    clique(*centro_de(a))
    r = A(f"(function(){{var r=({a}).getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]}})()")
    mouse("mouseMoved", (r[0] + r[2]) / 2, (r[1] + r[3]) / 2, "none", 0, 0); time.sleep(.05)
    xp, yp = centro_de(f"({a}).querySelector('.porta.s')")
    xd, yd = centro_de(NODE("Entender"))
    mouse("mouseMoved", xp, yp, "none", 0, 0); time.sleep(.05)
    arrastar(xp, yp, xd, yd); time.sleep(.1)
    conferir("puxar para trás vira volta", A("quadro.g.fios.filter(function(f){return f.volta}).length") == 1, A("JSON.stringify(quadro.g.fios.filter(function(f){return f.volta}).map(function(f){return [f.de,f.para,f.teto]}))"))
    meio = A("(function(){var p=quadro.g.fios.filter(function(f){return f.volta})[0].caminho,l=p.getTotalLength(),m=p.getPointAtLength(l/2),v=quadro.g.vista,r=quadro.tela.getBoundingClientRect();return [r.left+v.x+m.x*v.z,r.top+v.y+m.y*v.z]})()")
    clique(meio[0], meio[1], 2); time.sleep(.1)
    conferir("o painel da linha oferece o teto", "Voltar no máximo" in A("document.querySelector('.props').innerText"))
    foto("n4_teto")
    A("(function(){var s=document.querySelector('[aria-label=\"Voltar no máximo\"]');s.value='1';s.dispatchEvent(new Event('change'))})()"); time.sleep(.1)
    clique(*centro_de(BOTAO("Conferir"))); time.sleep(.3)
    conferir("Conferir aprova a volta", "Tudo certo" in (problemas() or ""), problemas())
    clique(*centro_de(BOTAO("Salvar fluxo"))); time.sleep(.7)
    lida = RX.buscar("metadado-com-volta")
    conferir("a volta salva é a mesma do plano", lida and lida.passos[1].get("volta") == {"para": "m", "teto": 1} and [p["id"] for p in lida.passos] == ["m", "p", "s"], str(lida.passos[1].get("volta") if lida else ""))

    # 1. simulado: pergunta, resposta, volta, teto
    clique(*centro_de(por_texto(".item", "Metadado com volta")), 2); time.sleep(.2)
    executar()
    txt = A("document.querySelector('.form-exec').innerText")
    conferir("o preço vem antes", "Usa IA em até 2 chamadas" in txt and "10 mil tokens" in txt, txt[-140:].replace("\n", " "))
    foto("n4_preco")
    clique(*centro_de(por_texto(".form-exec button", "Executar"))); time.sleep(.2)
    conferir("o fluxo para e pergunta", esperar("execucao&&execucao.estado==='perguntando'&&!!document.querySelector('.perg')"), faixa())
    txt = A("document.querySelector('.form-exec').innerText")
    conferir("a pergunta aparece, com as opções", "O que quer dizer T" in txt and "Tomada" in txt and "não sei" in txt)
    foto("n4_pergunta")
    clique(*centro_de(por_texto(".chips button", "Tomada")))
    clique(*centro_de(por_texto(".form-exec button", "Responder"))); time.sleep(.2)
    conferir("volta ao agente e pergunta de novo", esperar("execucao&&execucao.estado==='perguntando'&&execucao.voltas.p===1"), faixa())
    conferir("o agente recebeu a resposta", rodadas[-1] == [{"pergunta": "O que quer dizer T nos nomes?", "resposta": "Tomada"}], str(rodadas))
    clique(*centro_de(por_texto(".chips button", "não sei")))
    clique(*centro_de(por_texto(".form-exec button", "Responder"))); time.sleep(.2)
    conferir("para no teto e diz", esperar("execucao&&execucao.estado==='esperando'"), faixa())
    conferir("no teto não oferece tentar de novo", A(por_texto(".execucao button", "Tentar de novo") + "===undefined") and A(por_texto(".execucao button", "Pular") + "!==undefined"))
    foto("n4_no_teto")
    clique(*centro_de(por_texto(".execucao button", "Cancelar"))); time.sleep(.3)
    conferir("cancelou", esperar("execucao&&execucao.estado==='cancelado'"), faixa())

    # 2. o agente de verdade
    print("— parte 2: o agente de metadado de verdade —", flush=True)
    REG[OP] = real
    clique(*centro_de(por_texto(".execucao button", "Fechar"))); time.sleep(.1)
    executar()
    clique(*centro_de(por_texto(".form-exec button", "Executar"))); time.sleep(.2)
    ini = time.time()
    fim = esperar("execucao&&execucao.estado!=='correndo'", 150)
    print(f"  primeira rodada em {time.time()-ini:.0f} s; estado:", A("execucao.estado"), "|", faixa(), flush=True)
    conferir("o agente real rodou até uma decisão", fim)
    if A("execucao.estado") == "perguntando":
        perguntas = A("execucao.passos[execucao.atual].saida.perguntas.map(function(p){return p.texto})")
        print("  perguntas reais:", perguntas, flush=True)
        foto("n4_real")
        conferir("o agente real perguntou", len(perguntas) > 0)
        n = A("document.querySelectorAll('.perg').length")
        for i in range(n):
            area = f"document.querySelectorAll('.perg textarea')[{i}]"
            A(area + ".scrollIntoView()"); time.sleep(.03)
            clique(*centro_de(area)); ws.chamar("Input.insertText", text="não sei"); time.sleep(.03)
        A(por_texto(".form-exec button", "Responder") + ".scrollIntoView()"); time.sleep(.05)
        clique(*centro_de(por_texto(".form-exec button", "Responder"))); time.sleep(.3)
        ini = time.time()
        fim = esperar("execucao&&execucao.estado!=='correndo'", 150)
        print(f"  com as respostas, {time.time()-ini:.0f} s; estado:", A("execucao.estado"), "|", faixa(), flush=True)
        conferir("a volta rodou com o agente real", fim and A("execucao.voltas.p") == 1)
        conferir("termina num estado decidido", A("['pronto','perguntando','esperando'].indexOf(execucao.estado)>=0"), A("execucao.estado"))
        print("  saída do agente:", json.dumps(A("execucao.passos[0].saida.uso||null")), flush=True)
    print(f"\n{ok} ok, {falhou} falhas")
finally:
    ch.terminate()
    srv.shutdown()
sys.exit(1 if falhou else 0)
