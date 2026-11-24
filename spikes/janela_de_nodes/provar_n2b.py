"""Prova da N2b: o chat da janela com turnos REAIS do modelo. Dados temporários; só a conta vem do app."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(prefix="n2b_")
os.environ["CICLOASSIST_DADOS"] = TMP
os.environ["CICLOASSIST_CLAUDE_CONFIG"] = str(Path(os.environ["LOCALAPPDATA"]) / "CicloAssist" / "claude")
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H, rotas  # noqa
import olhar_painel as O

PORTA = 7897
H.PORTA = PORTA
rotas.url_do_mcp.__defaults__ = (PORTA, "chat")
srv = H.subir(PORTA)
CDP = 9375
perfil = tempfile.mkdtemp(prefix="n2b_chrome_")
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

    def centro_de(expr):
        return A(f"(function(){{var r=({expr}).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")

    TEXTO = "Array.from(document.querySelectorAll('%s')).filter(function(b){return b.textContent.indexOf(%s)>=0})[0]"
    def por_texto(sel, t):
        return TEXTO % (sel, json.dumps(t))
    NODE = lambda t: por_texto(".node", t)
    BOTAO = lambda t: por_texto("button", t)

    def falar(texto, prazo=240):
        clique(*centro_de("document.getElementById('mensagem')"))
        ws.chamar("Input.insertText", text=texto); time.sleep(.05)
        tecla("Enter", "Enter", 13)
        ini = time.time()
        while time.time() - ini < prazo:
            time.sleep(2)
            if not A("ocupado"):
                break
            print(f"  … {time.time()-ini:.0f} s", A("atividade"), flush=True)
        print(f"  turno em {time.time()-ini:.0f} s")
        print("  " + A("mensagens.slice(-3).map(function(m){return m.de+': '+(m.proposta?textoDaProposta(m.proposta):m.texto)}).join(' || ')")[:900], flush=True)

    # 1. um fluxo só pelo chat
    falar("Crie um fluxo novo, chamado Abrir e salvar no Media Composer: abre o Media Composer, perguntando o projeto, e depois salva tudo.")
    foto("n2b_proposta")
    conferir("chegou uma proposta de fluxo", A("mensagens.some(function(m){return m.proposta&&m.proposta.tipo==='proposta_fluxo'})"))
    conferir("sem nada gravado antes de aceitar", not (Path(TMP) / "receitas").exists() or not list((Path(TMP) / "receitas").iterdir()))
    clique(*centro_de(BOTAO("Aceitar"))); time.sleep(.2)
    conferir("aceitar desenha o fluxo", A("document.querySelectorAll('.node').length") == 2, A("document.querySelector('h1').textContent"))
    conferir("fica não salvo", not A(BOTAO("Salvar fluxo") + ".disabled"))
    conferir("a mensagem diz o nome do fluxo", "Abrir e salvar" in A("textoDaProposta(mensagens.filter(function(m){return m.proposta})[0].proposta)"))
    foto("n2b_aceito")
    clique(*centro_de(BOTAO("Conferir"))); time.sleep(.3)
    conferir("Conferir aprova", "Tudo certo" in A("document.querySelector('.problemas').innerText"), A("document.querySelector('.problemas').innerText"))
    clique(*centro_de(BOTAO("Salvar fluxo"))); time.sleep(.6)
    arquivos = list((Path(TMP) / "receitas").glob("*.md"))
    conferir("salvo só pelo chat e o botão", len(arquivos) == 1, [a.name for a in arquivos])
    if arquivos:
        print(arquivos[0].read_text(encoding="utf-8"))

    # 2. o que a operação não deixa: tem de dizer que não dá
    clique(*centro_de(por_texto(".item", "no Premiere")), 2); time.sleep(.2)
    clique(*centro_de(NODE("Converter para proxy")), 2); time.sleep(.1)
    A(BOTAO("Ajustar no chat") + ".scrollIntoView()"); time.sleep(.05)
    clique(*centro_de(BOTAO("Ajustar no chat"))); time.sleep(.1)
    conferir("a marca do node aparece", "node: Converter para proxy" in A("document.querySelector('.chip-no').textContent"))
    n = A("mensagens.length")
    falar("Troque o codec para ProRes 422 LT e a altura para 720.")
    conferir("recusa em vez de fingir: nenhuma proposta nova", not A(f"mensagens.slice({n}).some(function(m){{return m.proposta}})"))

    # 3. mudança num node
    clique(*centro_de(NODE("Importar no Premiere")), 2); time.sleep(.1)
    A(BOTAO("Ajustar no chat") + ".scrollIntoView()"); time.sleep(.05)
    clique(*centro_de(BOTAO("Ajustar no chat"))); time.sleep(.1)
    falar("Neste node, a bin deve ser sempre o texto RUSHES, fixo.")
    foto("n2b_node")
    conferir("chegou proposta do node", A("mensagens.some(function(m){return m.proposta&&m.proposta.tipo==='proposta_node'})"))
    txt = A("textoDaProposta(mensagens.filter(function(m){return m.proposta&&m.proposta.tipo==='proposta_node'})[0].proposta)")
    conferir("diz o nome do node", "Importar no Premiere" in txt, txt)
    clique(*centro_de(BOTAO("Aceitar"))); time.sleep(.2)
    conferir("aceitar muda o argumento e fica não salvo", A("noPorId(quadro.g,'importar').d.args.bin") == "RUSHES" and not A(BOTAO("Salvar fluxo") + ".disabled"))
    conferir("o arquivo da casa não mudou", 'receitas' and "RUSHES" not in (RAIZ / "cicloassist/receitas/preparar-diaria-no-premiere.md").read_text(encoding="utf-8"))
    print(f"\n{ok} ok, {falhou} falhas")
finally:
    ch.terminate()
    srv.shutdown()
sys.exit(1 if falhou else 0)
