"""Prova da marca do piloto nos nodes: o node diz, as Propriedades explicam, trocar o programa muda a marca, e o preço conta. Nada roda de verdade."""
import base64, dataclasses, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
os.environ["CICLOASSIST_DADOS"] = tempfile.mkdtemp(prefix="piloto_")
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H, rotas, receitas as RX  # noqa
from cicloassist.mcp import ferramentas  # noqa
from cicloassist.mcp.registro import FERRAMENTAS as REG
import olhar_painel as O

# ⛔ Nenhuma operação de verdade: a prova abre o formulário de executar, e um clique errado não pode abrir o Media Composer.
for op in ("abrir_programa", "fechar_programa", "importar_masters_opatom", "sincronizar", "salvar_tudo"):
    REG[op] = dataclasses.replace(REG[op], funcao=lambda **a: {"erro": "simulado"}, conferir=None)

pasta = RX.pasta_do_editor()
pasta.mkdir(parents=True)
passos = [
    {"id": "abrir", "op": "abrir_programa", "args": {"programa": "media_composer", "projeto": "{diaria}"}},
    {"id": "masters", "op": "importar_masters_opatom", "args": {"pasta": "/m", "bin": "B"}},
    {"id": "sync", "op": "sincronizar", "args": {"nome": "{diaria}", "subclipes": "por_cena", "sem_supervisao": True}},
    {"id": "salvar", "op": "salvar_tudo", "args": {}},
    {"id": "fechar", "op": "fechar_programa", "args": {"programa": "media_composer"}},
    {"id": "premiere", "op": "abrir_programa", "args": {"programa": "premiere", "projeto": "{diaria}"}},
]
texto = RX.texto_de("marca-do-piloto", "prova", {"diaria": {"tipo": "texto", "rotulo": "Nome da diária", "padrao": "D01"}}, passos, "Marca do piloto")
(pasta / "marca-do-piloto.md").write_text(texto, encoding="utf-8")
assert not RX.buscar("marca-do-piloto").problemas, RX.buscar("marca-do-piloto").problemas

PORTA, CDP = 7897, 9375
H.PORTA = PORTA
srv = H.subir(PORTA)
ch = subprocess.Popen([O.achar_chrome(), "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={tempfile.mkdtemp(prefix='piloto_chrome_')}", "--no-first-run", "--window-size=1150,640", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    def clique(x, y, n=1):
        ws.chamar("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button="none", clickCount=0, buttons=0)
        for i in range(1, n + 1):
            ws.chamar("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=i, buttons=1)
            ws.chamar("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=i, buttons=0)
        time.sleep(.08)

    def centro_de(expr):
        return A(f"(function(){{var e=({expr});e.scrollIntoView({{block:'center'}});var r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")

    def por_texto(sel, t):
        return "Array.from(document.querySelectorAll('%s')).filter(function(b){return b.textContent.indexOf(%s)>=0})[0]" % (sel, json.dumps(t))

    def linha(i):
        return A(f"(quadro.els[{json.dumps(i)}].querySelector('small')||{{}}).innerText||''")

    def no(i):
        return f"quadro.els[{json.dumps(i)}]"

    clique(*centro_de(por_texto(".item", "Marca do piloto")), 2); time.sleep(.3)
    foto("piloto_nodes")
    conferir("abrir no MC diz piloto", linha("abrir") == "Media Composer · piloto", linha("abrir"))
    conferir("sync por cena no MC diz piloto", "piloto" in linha("sync") and "se for" not in linha("sync"), linha("sync"))
    conferir("salvar diz piloto", linha("salvar") == "piloto", linha("salvar"))
    conferir("fechar no MC diz piloto", "piloto" in linha("fechar"), linha("fechar"))
    conferir("importar diz só que muda o foco", linha("masters") == "muda o foco", linha("masters"))
    conferir("abrir no Premiere não diz piloto", linha("premiere") == "Premiere", linha("premiere"))
    # ⚠️ Pelo texto, não por `scrollWidth` do node: as portas ficam de propósito para fora da caixa.
    conferir("a marca cabe no node", A("Object.keys(quadro.els).every(function(k){var e=quadro.els[k],c=e.getBoundingClientRect(),s=e.querySelector('small');if(!s||s.hidden){return true}var r=s.getBoundingClientRect();return r.right<=c.right&&r.left>=c.left&&r.bottom<=c.bottom})"))
    # ⚠️ Antes de mexer em campo: fluxo sujo desabilita o Executar.
    clique(*centro_de(por_texto("button", "Executar fluxo"))); time.sleep(.3)
    conferir("o preço antes do clique conta o piloto", "O piloto opera a tela em até 4 nodes" in A("document.body.innerText"), A("(quadro.g.fluxo.ia||{}).texto||''"))
    foto("piloto_preco")
    conferir("a marca tem a cor do piloto", A(f"getComputedStyle({no('salvar')}.querySelector('.marca-piloto')).color") == "rgb(76, 196, 184)", A(f"getComputedStyle({no('salvar')}.querySelector('.marca-piloto')).color"))

    clique(*centro_de(no("abrir")), 2); time.sleep(.2)
    props = A("document.querySelector('.props').innerText")
    conferir("Propriedades explica o que o piloto faz", "escolhe ou cria o projeto" in props)
    conferir("Propriedades mostra o agente do piloto", "Abrir agente do piloto" in props and "botão seguro" in props)
    foto("piloto_propriedades")

    # ⭐ Teclado real no select: a marca acompanha o programa, sem recarregar.
    seletor = "Array.from(document.querySelectorAll('.props select')).filter(function(s){return Array.from(s.options).some(function(o){return o.text==='Media Composer'})})[0]"
    A(f"{seletor}.focus()")

    def tecla(nome, codigo):
        ws.chamar("Input.dispatchKeyEvent", type="rawKeyDown", key=nome, code=nome, windowsVirtualKeyCode=codigo)
        ws.chamar("Input.dispatchKeyEvent", type="keyUp", key=nome, code=nome, windowsVirtualKeyCode=codigo)
        time.sleep(.1)

    antes = A(f"{seletor}.value")
    tecla("ArrowUp", 38)
    if A(f"{seletor}.value") == antes:
        tecla("ArrowDown", 40)
    if A(f"{seletor}.value") == antes:
        # ⚠️ No Mac a seta ABRE o menu nativo do select em vez de trocar o valor (medido, Chrome e WebKit).
        # A busca pela primeira letra troca sem abrir: é o teclado real do Mac.
        letra = A(f"Array.from({seletor}.options).filter(function(o){{return o.value && o.value!=={seletor}.value}})[0].text[0]")
        ws.chamar("Input.dispatchKeyEvent", type="keyDown", key=letra, text=letra, code="Key" + letra.upper())
        ws.chamar("Input.dispatchKeyEvent", type="keyUp", key=letra, code="Key" + letra.upper())
        time.sleep(.1)
    novo = A(f"{seletor}.options[{seletor}.selectedIndex].text")
    conferir("o programa mudou pelo teclado", novo != "Media Composer", novo)
    conferir("a marca some ao sair do Media Composer", linha("abrir") == novo, linha("abrir"))
    foto("piloto_trocou_programa")
finally:
    ch.terminate()
    srv.shutdown()

print(f"{ok} de {ok + falhou}", flush=True)
sys.exit(1 if falhou else 0)
