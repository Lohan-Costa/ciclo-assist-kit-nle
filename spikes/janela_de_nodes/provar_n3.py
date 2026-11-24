"""Prova da N3: Executar fluxo pela janela, com ramo, pausa, falha e retomada. As operações são simuladas; o executor e a tela, não."""
import base64, dataclasses, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
SAIDA = Path(tempfile.gettempdir()) / "provas_janela_de_nodes"
SAIDA.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(prefix="n3_")
os.environ["CICLOASSIST_DADOS"] = TMP
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.servico import http as H, rotas, fluxo as F, receitas as RX  # noqa
from cicloassist.mcp import ferramentas  # noqa
from cicloassist.mcp.registro import FERRAMENTAS as REG
import olhar_painel as O

# ── as operações simuladas ──
rodadas, falhar_uma = [], {"salvar_tudo"}


def simular(op, saida):
    def fn(**a):
        rodadas.append(op)
        time.sleep(1.2)
        if op in falhar_uma:
            falhar_uma.discard(op)
            return {"erro": "o Media Composer não respondeu (simulado)"}
        return saida
    REG[op] = dataclasses.replace(REG[op], funcao=fn, conferir=None)


simular("abrir_programa", {"programa": "DaVinci Resolve", "projeto": "D01"})
simular("converter_para_proxy", {"pasta": "/saida", "proxies": 3, "problemas": []})
simular("fechar_programa", {"programa": "DaVinci Resolve"})
simular("sincronizar", {"feito": "ok"})
simular("salvar_tudo", {"ok": True})


def revisar(op, args):
    if op in F.PASSOS_REVISADOS:
        time.sleep(1.0)


F._revisar_antes_do_sync = revisar

pasta = RX.pasta_do_editor()
pasta.mkdir(parents=True)
passos = [
    {"id": "abrir", "op": "abrir_programa", "args": {"programa": "resolve", "projeto": "{diaria}"}},
    {"id": "conv", "op": "converter_para_proxy", "args": {"projeto": "{diaria}", "pasta": "/m", "destino": "/d"}},
    {"id": "corrigir", "op": "fechar_programa", "args": {"programa": "resolve"}, "se": {"campo": "conv.problemas", "e": "sim"}},
    {"id": "sync", "op": "sincronizar", "args": {"nome": "{diaria}"}, "depois_de": ["conv"], "se": {"campo": "conv.problemas", "e": "nao"}},
    {"id": "salvar", "op": "salvar_tudo", "args": {}, "depois_de": ["corrigir", "sync"]},
]
texto = RX.texto_de("ramo-de-prova", "prova", {"diaria": {"tipo": "texto", "rotulo": "Nome da diária", "padrao": "D01"}}, passos, "Ramo de prova")
(pasta / "ramo-de-prova.md").write_text(texto, encoding="utf-8")
assert not RX.buscar("ramo-de-prova").problemas, RX.buscar("ramo-de-prova").problemas

PORTA = 7896
H.PORTA = PORTA
srv = H.subir(PORTA)
CDP = 9374
perfil = tempfile.mkdtemp(prefix="n3_chrome_")
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

    def centro_de(expr):
        return A(f"(function(){{var r=({expr}).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")

    TEXTO = "Array.from(document.querySelectorAll('%s')).filter(function(b){return b.textContent.indexOf(%s)>=0})[0]"
    def por_texto(sel, t):
        return TEXTO % (sel, json.dumps(t))
    BOTAO = lambda t: por_texto("button", t)
    def classes():
        return A("(function(){var o={};Object.keys(quadro.els).forEach(function(k){o[k]=['correndo','pronto','falhou','fora'].filter(function(c){return quadro.els[k].classList.contains(c)}).join()});return o})()")
    def faixa():
        return A("(function(){var f=quadro.faixa;return f.hidden?null:f.querySelector('.texto').textContent})()")

    def esperar(cond, prazo=20):
        ini = time.time()
        while time.time() - ini < prazo:
            if A(cond):
                return True
            time.sleep(.1)
        return False

    clique(*centro_de(por_texto(".item", "Ramo de prova")), 2); time.sleep(.2)
    conferir("o ramo aparece: duas linhas tracejadas", A("Array.from(document.querySelectorAll('.plano svg path')).filter(function(p){return p.getAttribute('stroke-dasharray')}).length") == 2)
    conferir("etiquetas da condição", A("Array.from(document.querySelectorAll('.rotulo')).map(function(r){return r.textContent}).sort().join('|')") == "se problemas|se sem problemas", A("Array.from(document.querySelectorAll('.rotulo')).map(function(r){return r.textContent}).join('|')"))
    foto("n3_ramo")
    conferir("o último node do ramo fica à direita de quem vem antes", A("noPorId(quadro.g,'salvar').x>noPorId(quadro.g,'sync').x&&noPorId(quadro.g,'salvar').x>noPorId(quadro.g,'corrigir').x"))
    conferir("os dois ramos saem na mesma coluna", A("noPorId(quadro.g,'corrigir').x===noPorId(quadro.g,'agente_sync').x"))

    # a linha com condição abre o painel
    m = A("(function(){var f=quadro.g.fios.filter(function(x){return x.se&&x.se.e==='sim'})[0],p=f.caminho,l=p.getTotalLength(),m=p.getPointAtLength(l*0.3),v=quadro.g.vista,r=quadro.tela.getBoundingClientRect();return [r.left+v.x+m.x*v.z,r.top+v.y+m.y*v.z]})()")
    clique(m[0], m[1], 2); time.sleep(.1)
    conferir("clique duplo na linha abre a condição", "Só quando" in A("document.querySelector('.props').innerText"), A("document.querySelector('.props h3').textContent"))
    foto("n3_condicao")

    conferir("Executar habilitado com o fluxo salvo", not A(BOTAO("Executar fluxo") + ".disabled"))
    clique(*centro_de(BOTAO("Executar fluxo"))); time.sleep(.15)
    conferir("o formulário pergunta a diária, com o padrão", A("document.querySelector('.form-exec input').value") == "D01")
    foto("n3_form")
    clique(*centro_de(por_texto(".form-exec button", "Executar"))); time.sleep(.2)

    conferir("começou: o primeiro node acende", esperar("quadro.els.abrir.classList.contains('correndo')"), str(classes()))
    conferir("a faixa diz quem roda", "Executando: Abrir programa" in (faixa() or ""), faixa())
    conferir("Executar trava enquanto roda", A(BOTAO("Executar fluxo") + ".disabled"))
    clique(*centro_de(por_texto(".execucao button", "Pausar"))); time.sleep(.2)
    conferir("pausa ao fim do node", "pausa ao fim" in (faixa() or ""), faixa())
    conferir("parou entre nodes", esperar("execucao&&execucao.estado==='pausado'"), faixa())
    c = classes()
    conferir("o primeiro ficou pronto e o segundo não começou", c["abrir"] == "pronto" and c["conv"] == "", str(c))
    foto("n3_pausado")
    n = len(rodadas)
    clique(*centro_de(por_texto(".execucao button", "Retomar"))); time.sleep(.2)
    conferir("retomar anda", esperar("quadro.els.conv.classList.contains('correndo')"), str(classes()))
    conferir("retomar não refez o primeiro", rodadas[:n + 1] == ["abrir_programa", "converter_para_proxy"], str(rodadas))

    conferir("o gerente acende antes do sync", esperar("quadro.els.agente_sync.classList.contains('correndo')"), str(classes()))
    c = classes()
    conferir("o ramo não seguido fica fora", c["corrigir"] == "fora", str(c))
    conferir("durante a revisão o sync ainda não acende", c["sync"] == "", str(c))
    conferir("o sync acende depois", esperar("quadro.els.sync.classList.contains('correndo')"), str(classes()))
    conferir("o gerente fica pronto", "pronto" in classes()["agente_sync"])
    foto("n3_correndo")
    conferir("a falha aparece", esperar("execucao&&execucao.estado==='esperando'"), faixa())
    conferir("o node que falhou acende em erro", classes()["salvar"] == "falhou" and "não respondeu" in faixa(), str(classes()))
    foto("n3_falha")
    clique(*centro_de(por_texto(".execucao button", "Tentar de novo"))); time.sleep(.2)
    conferir("conclui depois de tentar de novo", esperar("execucao&&execucao.estado==='pronto'"), faixa())
    c = classes()
    conferir("estado final dos nodes", c == {"abrir": "pronto", "conv": "pronto", "corrigir": "fora", "agente_sync": "pronto", "sync": "pronto", "salvar": "pronto"}, str(c))
    conferir("a faixa fecha a conta", "4 nodes executados" in faixa() and "1 fora do caminho" in faixa(), faixa())
    conferir("nenhum passo rodou duas vezes (só o que falhou)", rodadas == ["abrir_programa", "converter_para_proxy", "sincronizar", "salvar_tudo", "salvar_tudo"], str(rodadas))
    conferir("Executar volta", not A(BOTAO("Executar fluxo") + ".disabled"))
    foto("n3_pronto")

    # a linha com "Só quando" editada e salva volta igual
    A("location.reload()"); time.sleep(.6)
    for _ in range(40):
        if A("document.querySelectorAll('.node').length"): break
        time.sleep(.1)
    clique(*centro_de(por_texto(".item", "Ramo de prova")), 2); time.sleep(.3)
    conferir("depois de recarregar, a janela mostra o último resultado", "Concluído" in (faixa() or ""), faixa())
    clique(*centro_de(por_texto(".execucao button", "Fechar"))); time.sleep(.1)
    conferir("Fechar limpa os nodes", all(v == "" for v in classes().values()) and faixa() is None)
    print(f"\n{ok} ok, {falhou} falhas")
finally:
    ch.terminate()
    srv.shutdown()
sys.exit(1 if falhou else 0)
