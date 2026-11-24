"""Prova do node Confirmar na memória. Parte 1: agente e gravação simulados, cartão, erro, Não gravar e o clique. Parte 2: o agente de verdade numa diária real, com o arquivo da memória conferido."""
import base64, dataclasses, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(prefix="n4b_")
os.environ["CICLOASSIST_DADOS"] = TMP
os.environ["CICLOASSIST_CLAUDE_CONFIG"] = str(Path(os.environ["LOCALAPPDATA"]) / "CicloAssist" / "claude")
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H, rotas, fluxo as F, receitas as RX, arrastados as AR  # noqa
from cicloassist.mcp import ferramentas  # noqa
from cicloassist.mcp.registro import FERRAMENTAS as REG
import olhar_painel as O

DIARIA = r"D:\AUDIOS ANALISAR\24Y07M18"
AR.autorizar(DIARIA)
OP, GRAVAR = "entender_metadados_da_diaria", "gravar_na_memoria_da_producao"
real, real_gravar = REG[OP], REG[GRAVAR]
gravadas, resposta_da_gravacao = [], {"erro": "Estas regras não passaram na conferência:\n#-#T#: 2 arquivos não casam"}
APROVADA = {"forma": "#-#T#", "molde": "{cena}-{plano}T{take}", "aprovada": True, "exemplo": "18-1T01_1.WAV → 18 · 1 · 01", "arquivos": 31}


def simulado(pasta="", bin="", programa="", respostas=None):
    return {"producao": {"memoria": None, "projeto_aberto": "D01", "no_ixml": ["FILME"], "memorias_existentes": []}, "regras_aprovadas": [APROVADA, {"forma": "#X#", "molde": "{cena}X{take}", "aprovada": False}], "regras_reprovadas": [], "perguntas": []}


def gravar(**k):
    gravadas.append(k)
    return resposta_da_gravacao


REG[OP] = dataclasses.replace(real, funcao=simulado)
REG[GRAVAR] = dataclasses.replace(real_gravar, funcao=gravar)
REG["salvar_tudo"] = dataclasses.replace(REG["salvar_tudo"], funcao=lambda: {"ok": True}, conferir=None)

pasta = RX.pasta_do_editor()
pasta.mkdir(parents=True)
passos = [
    {"id": "m", "op": OP, "args": {"pasta": "{pasta}", "respostas": "{p.respostas}"}},
    {"id": "p", "op": "perguntar_ao_editor", "args": {"perguntas": "{m.perguntas}"}, "se": {"campo": "m.perguntas", "e": "sim"}, "volta": {"para": "m", "teto": 1}},
    {"id": "c", "op": "confirmar_na_memoria", "args": {"regras": "{m.regras_aprovadas}", "producao": "{m.producao}", "pasta": "{pasta}", "respostas": "{p.respostas}"}, "depois_de": ["m"], "se": {"campo": "m.perguntas", "e": "nao"}},
    {"id": "s", "op": "salvar_tudo", "args": {}},
]
spec = {"pasta": {"tipo": "pasta", "rotulo": "A pasta do som"}}
(pasta / "memoria-da-diaria.md").write_text(RX.texto_de("memoria-da-diaria", "prova", spec, passos, "Memoria da diaria"), encoding="utf-8")
assert not RX.buscar("memoria-da-diaria").problemas, RX.buscar("memoria-da-diaria").problemas

PORTA, CDP = 7894, 9376
H.PORTA = PORTA
rotas.url_do_mcp.__defaults__ = (PORTA, "chat")
srv = H.subir(PORTA)
ch = subprocess.Popen([O.achar_chrome(), "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={tempfile.mkdtemp(prefix='n4b_chrome_')}", "--no-first-run", "--window-size=1150,640", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    def esperar(cond, prazo=30):
        ini = time.time()
        while time.time() - ini < prazo:
            if A(cond):
                return True
            time.sleep(.15)
        return False

    def executar():
        clique(*centro_de(por_texto("button", "Executar fluxo"))); time.sleep(.15)
        A(f"formExec.valores.pasta={json.dumps(DIARIA)};desenharDireita()"); time.sleep(.1)
        clique(*centro_de(por_texto(".form-exec button", "Executar"))); time.sleep(.2)

    CARTAO = "execucao&&execucao.estado==='perguntando'&&!!document.querySelector('.regra-conf')"
    TEXTO_CARTAO = "document.querySelector('.form-exec').innerText"

    clique(*centro_de(por_texto(".item", "Memoria da diaria")), 2); time.sleep(.2)
    conferir("o node aparece com a marca de quem espera o editor", "duvida" in A(por_texto(".node", "Confirmar") + ".className"), A(por_texto(".node", "Confirmar") + ".innerText"))
    foto("n4b_nodes")

    # parte 1: simulado
    executar()
    conferir("o fluxo para no cartão", esperar(CARTAO), A("execucao&&execucao.estado"))
    t = A(TEXTO_CARTAO)
    conferir("o cartão mostra a regra, o molde e o exemplo", "#-#T#" in t and "{cena}-{plano}T{take}" in t and "18-1T01_1.WAV" in t, t[:120].replace("\n", " "))
    conferir("a regra reprovada não aparece", "#X#" not in t)
    conferir("sem produção, o cartão pergunta o nome e sugere", "De que produção" in t and A(por_texto(".chips button", "FILME") + "!==undefined"))
    conferir("nada foi gravado antes do clique", gravadas == [])
    foto("n4b_cartao")

    clique(*centro_de(por_texto(".form-exec button", "Gravar na memória"))); time.sleep(.4)
    conferir("sem nome não grava e diz", "De que produção" in A(TEXTO_CARTAO) and "Diga de que produção" in A(TEXTO_CARTAO) and gravadas == [])

    clique(*centro_de(por_texto(".chips button", "FILME"))); time.sleep(.1)
    conferir("o atalho preenche o nome", A("document.querySelector('[aria-label=\"Nome da produção\"]').value") == "FILME")
    conferir("oferece o apelido do projeto, desligado", "D01" in A(TEXTO_CARTAO) and A("document.querySelector('.marca-conf input').checked") is False)
    clique(*centro_de("document.querySelector('.marca-conf input')")); time.sleep(.05)

    clique(*centro_de(por_texto(".form-exec button", "Gravar na memória"))); time.sleep(.5)
    conferir("a conferência que reprova deixa o cartão com o motivo", "não passaram na conferência" in A(TEXTO_CARTAO) and A("execucao.estado") == "perguntando")
    foto("n4b_reprovou")

    resposta_da_gravacao = {"producao": "FILME", "regras": 1, "arquivo": "x.md", "manchete": "ok"}
    clique(*centro_de(por_texto(".form-exec button", "Gravar na memória"))); time.sleep(.3)
    conferir("o clique grava e o fluxo segue até o fim", esperar("execucao&&execucao.estado==='pronto'"), A("execucao&&execucao.estado"))
    conferir("gravou só a aprovada, com o apelido marcado", gravadas[-1]["regras"] == [{"forma": APROVADA["forma"], "molde": APROVADA["molde"]}] and gravadas[-1]["producao"] == "FILME" and gravadas[-1]["apelidos"] == ["D01"], str(gravadas[-1]))
    clique(*centro_de(por_texto(".execucao button", "Fechar"))); time.sleep(.2)

    n = len(gravadas)
    executar()
    esperar(CARTAO)
    conferir("o cartão da execução seguinte não herda o nome digitado", A("document.querySelector('[aria-label=\"Nome da produção\"]').value") == "", A("document.querySelector('[aria-label=\"Nome da produção\"]').value"))
    clique(*centro_de(por_texto(".form-exec button", "Não gravar"))); time.sleep(.3)
    conferir("Não gravar segue sem gravar", esperar("execucao&&execucao.estado==='pronto'") and len(gravadas) == n and A("execucao.passos[2].saida.gravou") is False)
    clique(*centro_de(por_texto(".execucao button", "Fechar"))); time.sleep(.2)

    # parte 2: o agente e a gravação de verdade, nos arquivos reais
    print("— parte 2: de verdade —", flush=True)
    REG[OP], REG[GRAVAR] = real, real_gravar
    executar()
    ini = time.time()
    fim = esperar("execucao&&execucao.estado!=='correndo'", 150)
    print(f"  1ª rodada em {time.time()-ini:.0f} s:", A("execucao.estado"), flush=True)
    conferir("o agente real rodou até uma decisão", fim)
    if A("execucao.passos[1].estado==='perguntando'"):
        perguntas = A("execucao.passos[1].saida.perguntas")
        print("  perguntas:", [p["texto"] for p in perguntas], flush=True)
        conferir("as perguntas guardam o trecho do nome", all(p.get("sobre") for p in perguntas))
        for i in range(A("document.querySelectorAll('.perg').length")):
            clique(*centro_de(f"document.querySelectorAll('.perg textarea')[{i}]")); ws.chamar("Input.insertText", text="não sei"); time.sleep(.03)
        clique(*centro_de(por_texto(".form-exec button", "Responder"))); time.sleep(.3)
        ini = time.time()
        fim = esperar("execucao&&execucao.estado!=='correndo'", 150)
        print(f"  com as respostas, {time.time()-ini:.0f} s:", A("execucao.estado"), "|", A("execucao.passos[execucao.atual]?execucao.passos[execucao.atual].id:''"), flush=True)
    if A(f"!!({CARTAO})"):
        t = A(TEXTO_CARTAO)
        print("  cartão real:", t[:500].replace("\n", " | "), flush=True)
        foto("n4b_real")
        conferir("o editor vê o que vai gravar", "Só o seu clique grava" in t)
        tinha_nome = A("!!document.querySelector('[aria-label=\"Nome da produção\"]')")
        if tinha_nome:
            clique(*centro_de("document.querySelector('[aria-label=\"Nome da produção\"]')")); ws.chamar("Input.insertText", text="PROVA N4B"); time.sleep(.05)
        clique(*centro_de(por_texto(".form-exec button", "Gravar na memória"))); time.sleep(.5)
        conferir("a gravação real passou pela conferência", esperar("execucao&&execucao.passos[2].estado==='feito'", 40), A(TEXTO_CARTAO + "||''") if A("!!document.querySelector('.form-exec')") else A("JSON.stringify(execucao.passos[2].saida)"))
        memorias = list(Path(TMP, "producoes").rglob("memoria.md"))
        conferir("o arquivo da memória existe, com o nome digitado", len(memorias) == 1 and memorias[0].parent.name == "PROVA N4B", str(memorias))
        if memorias:
            print("  memoria.md:", memorias[0].read_text(encoding="utf-8")[:400].replace("\n", " | "), flush=True)
    else:
        print("  ⚠️ não chegou ao cartão real:", A("JSON.stringify(execucao.passos.map(function(p){return [p.id,p.estado,p.motivo]}))"), flush=True)
    print(f"\n{ok} ok, {falhou} falhas")
finally:
    ch.terminate()
    srv.shutdown()
sys.exit(1 if falhou else 0)
