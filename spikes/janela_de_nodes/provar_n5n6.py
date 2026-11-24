"""Prova da N5 e da N6 com mouse real. N5: rodar um fluxo pelo menu do chat, responder e confirmar sem abrir a janela. N6: exportar e importar. As operações são simuladas."""
import base64, dataclasses, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(prefix="n5_")
os.environ["CICLOASSIST_DADOS"] = TMP
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H, rotas, receitas as RX, seletor as SEL  # noqa
from cicloassist.mcp import ferramentas  # noqa
from cicloassist.mcp.registro import FERRAMENTAS as REG
import olhar_painel as O

OP, GRAVAR = "entender_metadados_da_diaria", "gravar_na_memoria_da_producao"
rodadas, gravadas = [], []
APROVADA = {"forma": "#-#T#", "molde": "{cena}-{plano}T{take}", "aprovada": True, "exemplo": "18-1T01_1.WAV → 18 · 1 · 01", "arquivos": 31}


def agente(pasta="", bin="", programa="", respostas=None):
    rodadas.append(respostas)
    return {"producao": {"memoria": None, "projeto_aberto": "", "no_ixml": ["FILME"], "memorias_existentes": []}, "regras_aprovadas": [APROVADA],
            "perguntas": [] if respostas else [{"sobre": "T", "texto": "O que quer dizer T nos nomes?", "opcoes": ["Take", "Tomada"]}]}


def gravar(**k):
    gravadas.append(k)
    return {"producao": k["producao"], "regras": 1, "arquivo": "x.md", "manchete": "ok"}


REG[OP] = dataclasses.replace(REG[OP], funcao=agente)
REG[GRAVAR] = dataclasses.replace(REG[GRAVAR], funcao=gravar)
REG["salvar_tudo"] = dataclasses.replace(REG["salvar_tudo"], funcao=lambda: {"salvou": True}, conferir=None)
passos = [
    {"id": "m", "op": OP, "args": {"pasta": "/d", "respostas": "{p.respostas}"}},
    {"id": "p", "op": "perguntar_ao_editor", "args": {"perguntas": "{m.perguntas}"}, "se": {"campo": "m.perguntas", "e": "sim"}, "volta": {"para": "m", "teto": 1}},
    {"id": "c", "op": "confirmar_na_memoria", "args": {"regras": "{m.regras_aprovadas}", "producao": "{m.producao}", "pasta": "/d"}, "depois_de": ["m"], "se": {"campo": "m.perguntas", "e": "nao"}},
    {"id": "s", "op": "salvar_tudo", "args": {}},
]
pasta = RX.pasta_do_editor()
pasta.mkdir(parents=True)
(pasta / "fluxo-do-menu.md").write_text(RX.texto_de("fluxo-do-menu", "Prova do menu.", {"diaria": {"tipo": "texto", "rotulo": "Nome da diária", "padrao": "D01"}}, passos, "Fluxo do menu"), encoding="utf-8")
assert not RX.buscar("fluxo-do-menu").problemas, RX.buscar("fluxo-do-menu").problemas

PORTA, CDP = 7893, 9377
H.PORTA = PORTA
rotas.url_do_mcp.__defaults__ = (PORTA, "chat")
srv = H.subir(PORTA)
ch = subprocess.Popen([O.achar_chrome(), "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={tempfile.mkdtemp(prefix='n5_chrome_')}", "--no-first-run", "--window-size=560,760", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    A = lambda e: O.avaliar(ws, e)

    def ir(w, h, url):
        ws.chamar("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
        ws.chamar("Page.navigate", url=f"http://127.0.0.1:{PORTA}{url}")
        time.sleep(1.2)

    def foto(nome):
        Path(SAIDA, nome + ".png").write_bytes(base64.b64decode(ws.chamar("Page.captureScreenshot", format="png")["data"]))

    def clique(x, y, n=1):
        ws.chamar("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button="none", clickCount=0, buttons=0)
        for i in range(1, n + 1):
            ws.chamar("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=i, buttons=1)
            ws.chamar("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=i, buttons=0)
        time.sleep(.1)

    def centro_de(expr):
        return A(f"(function(){{var e=({expr});e.scrollIntoView({{block:'center'}});var r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")

    def por_texto(sel, t):
        return "Array.from(document.querySelectorAll('%s')).filter(function(b){return b.textContent.indexOf(%s)>=0&&b.offsetParent})[0]" % (sel, json.dumps(t))

    def esperar(cond, prazo=20):
        ini = time.time()
        while time.time() - ini < prazo:
            if A(cond):
                return True
            time.sleep(.15)
        return False

    ir(560, 760, "/painel?casca=app")
    conferir("a aba Fluxos saiu", A("Array.from(document.querySelectorAll('.aba')).map(function(b){return b.textContent}).join()").find("Fluxos") < 0)
    clique(*centro_de("document.getElementById('abrirMenu')")); time.sleep(.5)
    conferir("o fluxo aparece no menu do chat", esperar(por_texto("#menuFluxos button", "Fluxo do menu") + "!==undefined", 5))
    foto("n5_menu")
    clique(*centro_de(por_texto("#menuFluxos button", "Fluxo do menu"))); time.sleep(.3)
    t = A("document.querySelector('.receita-forma').innerText")
    conferir("o formulário mostra o que vai rodar e o preço", "entender os metadados" in t and "salvar tudo" in t and "Usa IA" in t, t[:220].replace("\n", " | "))
    foto("n5_formulario")
    clique(*centro_de(por_texto(".receita-forma button", "Executar"))); time.sleep(.3)
    conferir("o quadro sobe acima da conversa e pergunta", esperar("!!document.querySelector('.fluxo-pergunta textarea')"), A("document.querySelector('#fluxosQuadro').innerText")[:100])
    foto("n5_pergunta")
    clique(*centro_de("document.querySelector('.fluxo-pergunta textarea')")); ws.chamar("Input.insertText", text="Take do editor"); time.sleep(11)
    conferir("o que ele digita sobrevive à leitura de 10 s", A("document.querySelector('.fluxo-pergunta textarea').value") == "Take do editor")
    clique(*centro_de(por_texto(".fluxo-pergunta button", "Responder"))); time.sleep(.3)
    conferir("volta ao agente com a resposta e chega à confirmação", esperar("!!document.querySelector('.fluxo-regra')"), str(rodadas))
    conferir("o agente recebeu a resposta", rodadas[-1] and rodadas[-1][0]["resposta"] == "Take do editor")
    conferir("nada gravado antes do clique", gravadas == [])
    foto("n5_confirmar")
    clique(*centro_de(por_texto(".fluxo-pergunta button", "Gravar na memória"))); time.sleep(.4)
    conferir("sem nome diz o que falta", "Diga de que produção" in A("document.querySelector('.fluxo-pergunta').innerText"))
    clique(*centro_de(por_texto(".fluxo-chips button", "FILME"))); time.sleep(.1)
    clique(*centro_de(por_texto(".fluxo-pergunta button", "Gravar na memória"))); time.sleep(.3)
    conferir("grava e termina, sem abrir a janela", esperar("document.querySelector('#fluxosQuadro').innerText.indexOf('pronto')>=0") and gravadas and gravadas[-1]["producao"] == "FILME", A("document.querySelector('#fluxosQuadro').innerText")[:120])
    foto("n5_pronto")

    # N6
    escolhida = Path(tempfile.mkdtemp(prefix="n6_"))
    SEL.escolher = lambda tipo="arquivo", *a, **k: [str(escolhida)] if tipo == "pasta" else [str(escolhida / "fluxo-do-menu.md")]
    ir(1150, 640, "/oficina")
    esperar("document.querySelectorAll('.item').length>0")
    clique(*centro_de(por_texto(".item", "Fluxo do menu")), 2); time.sleep(.3)
    clique(*centro_de(por_texto("button", "Compartilhar"))); time.sleep(.5)
    conferir("Compartilhar grava o arquivo", (escolhida / "fluxo-do-menu.md").exists(), str(list(escolhida.iterdir())))
    (RX.pasta_do_editor() / "fluxo-do-menu.md").unlink()
    ir(1150, 640, "/oficina")
    esperar("document.querySelector('#importarFluxo')!==null")
    conferir("sem ele, o fluxo sumiu da lista", A(por_texto(".item", "Fluxo do menu") + "===undefined"))
    clique(*centro_de("document.getElementById('importarFluxo')"))
    conferir("Importar devolve o fluxo aberto, com os nodes", esperar(por_texto(".node", "Confirmar") + "!==undefined", 8), A("quadro&&quadro.g.fluxo.nome"))
    foto("n6_importado")
    conferir("importado não rodou nada", A("!execucao||execucao.estado==='pronto'"))
    print(f"\n{ok} ok, {falhou} falhas")
finally:
    ch.terminate()
    srv.shutdown()
sys.exit(1 if falhou else 0)
