"""Testes pilotados como um usuário: criar e rodar fluxos com a tela e os programas de verdade, medindo passos, tempos e o consumo de IA DO PRODUTO.

  python spikes/pilotar_como_usuario.py criar_pelo_chat   # do zero, pelo chat da janela, e roda
  python spikes/pilotar_como_usuario.py receita_da_casa   # o benchmark: a mesma tarefa pela receita da casa, pelo menu do chat
  python spikes/pilotar_como_usuario.py <cenário de erro> # ver CENARIOS no fim

⭐ O consumo vem de um medidor posto nas três portas por onde o produto chama um modelo: `localizador.perguntar`, `turno_magro.chamar` e o fim de turno do chat.
O que esta sessão de desenvolvimento gasta não passa por elas.
⚠️ Roda um serviço paralelo (porta 7892) sobre os dados reais, com o Chrome no lugar da janela nativa. O diálogo do sistema para escolher pasta é substituído: o clique no botão é real, a pasta vem daqui.
⚠️ Os Programas são os de verdade: o Media Composer e o Resolve abrem. Freio: F12.
"""
import base64, json, os, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ), str(RAIZ / "tools")]
sys.stdout.reconfigure(encoding="utf-8")
SAIDA = Path(tempfile.gettempdir()) / "bench_noite"
SAIDA.mkdir(exist_ok=True)

from cicloassist.servico import http as H, rotas, fluxo as F, receitas as RX, seletor as SEL  # noqa: E402
from cicloassist.mcp import ferramentas  # noqa: E402,F401
from cicloassist.motor import turno_magro as T, sessao as S  # noqa: E402
from cicloassist.motor.decupador import _uso_do_result  # noqa: E402
from cicloassist.piloto import localizador as L, tela  # noqa: E402
from cicloassist.avid import abrir as MC  # noqa: E402
from cicloassist import resolve as RES  # noqa: E402
import olhar_painel as O  # noqa: E402

PASTA = r"%USERPROFILE%\Desktop\MIDIAS SIMULADAS"
PORTA, CDP = 7892, 9378
PRAZO_DA_EXECUCAO = 1200
# ⭐ Rodada nova = diária nova: repetir o nome cairia em projeto do Resolve e bin que já existem, e a medida deixaria de ser comparável.
DIARIA_DO_CHAT = os.environ.get("BENCH_DIARIA", "N1")
DIARIA_DA_CASA = os.environ.get("BENCH_DIARIA", "N2")

registro = {"cenario": "", "inicio": time.strftime("%Y-%m-%d %H:%M:%S"), "etapas": [], "ia": [], "observacoes": [], "cliques": 0, "teclas": 0}
etapa_atual = ["preparo"]
_trava = threading.Lock()


def passo_atual():
    try:
        f = F.em_aberto()
        return f.passos[f.atual].id if f and f.atual < len(f.passos) else ""
    except Exception:  # noqa: BLE001
        return ""


def anotar_ia(tipo, **k):
    with _trava:
        registro["ia"].append({"tipo": tipo, "etapa": etapa_atual[0], "passo": passo_atual(), "quando": time.strftime("%H:%M:%S"), **k})


_perguntar, _chamar, _traduzir = L.perguntar, T.chamar, S._traduzir


def perguntar(jpg, texto, modelo="", sistema=""):
    r, s, c = _perguntar(jpg, texto, modelo, sistema)
    anotar_ia("agente do piloto" if sistema else "piloto (olhar a tela)", custo_usd=round(c, 5), segundos=round(s, 1))
    return r, s, c


def chamar(instrucao, pedido, modelo=None, prazo=T.PRAZO_S):
    r = _chamar(instrucao, pedido, modelo, prazo)
    i = instrucao.lower()
    nome = "gerente do sync" if "revisor" in i else "conselho do fluxo" if "falhou" in i or "conselho" in i else "agente de metadado" if "metadado" in i or "som direto" in i else "turno magro"
    anotar_ia(nome, segundos=r.segundos, **{k: v for k, v in (r.uso or {}).items() if isinstance(v, (int, float, str))})
    return r


def traduzir(evento):
    if isinstance(evento, dict) and evento.get("type") == "result":
        u = _uso_do_result(evento)
        anotar_ia("chat", **{**{k: v for k, v in (u or {}).items() if isinstance(v, (int, float, str))},
                             "custo_usd": evento.get("total_cost_usd"), "segundos": round((evento.get("duration_ms") or 0) / 1000, 1)})
    yield from _traduzir(evento)


L.perguntar, T.chamar, S._traduzir = perguntar, chamar, traduzir
SEL.escolher = lambda tipo="arquivo", *a, **k: [PASTA]


def obs(texto):
    registro["observacoes"].append(texto)
    print("  OBS:", texto, flush=True)


def gravar():
    (SAIDA / f"{registro['cenario']}.json").write_text(json.dumps(registro, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


class Etapa:
    def __init__(self, nome):
        self.nome = nome

    def __enter__(self):
        etapa_atual[0] = self.nome
        self.t = time.monotonic()
        print(f"— {self.nome}", flush=True)
        return self

    def __exit__(self, tipo, valor, _tb):
        registro["etapas"].append({"etapa": self.nome, "segundos": round(time.monotonic() - self.t, 1), "ok": tipo is None, **({"erro": str(valor)[:300]} if tipo else {})})
        gravar()
        return False


class Tela:
    def __init__(self):
        self.ch = subprocess.Popen([O.achar_chrome(), "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={tempfile.mkdtemp(prefix='bench_chrome_')}",
                                    "--no-first-run", "--window-size=1150,640", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                alvo = next(a for a in json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json")) if a["type"] == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(.2)
        self.ws = O.WS(alvo["webSocketDebuggerUrl"])
        self.ws.chamar("Page.enable"); self.ws.chamar("Runtime.enable")

    def a(self, e):
        return O.avaliar(self.ws, e)

    def ir(self, w, h, url):
        self.ws.chamar("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
        self.ws.chamar("Page.navigate", url=f"http://127.0.0.1:{PORTA}{url}")
        time.sleep(1.3)

    def foto(self, nome):
        Path(SAIDA, f"{registro['cenario']}_{nome}.png").write_bytes(base64.b64decode(self.ws.chamar("Page.captureScreenshot", format="png")["data"]))

    def clique(self, x, y, n=1):
        registro["cliques"] += n
        self.ws.chamar("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button="none", clickCount=0, buttons=0)
        for i in range(1, n + 1):
            self.ws.chamar("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=i, buttons=1)
            self.ws.chamar("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=i, buttons=0)
        time.sleep(.1)

    def em(self, expr, n=1):
        x, y = self.a(f"(function(){{var e=({expr});e.scrollIntoView({{block:'center'}});var r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")
        self.clique(x, y, n)

    @staticmethod
    def txt(sel, t):
        return "Array.from(document.querySelectorAll('%s')).filter(function(b){return b.textContent.indexOf(%s)>=0&&b.offsetParent})[0]" % (sel, json.dumps(t))

    def escrever(self, texto):
        registro["teclas"] += len(texto)
        self.ws.chamar("Input.insertText", text=texto)
        time.sleep(.1)

    def tecla(self, key, code, vk, texto=None):
        k = {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk}
        if texto:
            k["text"] = texto
        self.ws.chamar("Input.dispatchKeyEvent", **k)
        self.ws.chamar("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk)
        time.sleep(.1)

    def esperar(self, cond, prazo=30):
        ini = time.time()
        while time.time() - ini < prazo:
            if self.a(cond):
                return True
            time.sleep(.2)
        return False

    def fim(self):
        self.ch.terminate()


def foto_da_maquina(nome):
    f = tela.fotografar()
    (SAIDA / f"{registro['cenario']}_{nome}.jpg").write_bytes(tela.jpeg(f.img, 1400))


def programas_fechados():
    """O ponto de partida do benchmark. O Windows não roda MC e Resolve juntos sem risco, e o histórico partiu de tudo fechado."""
    etapa_atual[0] = "preparo (fora da conta)"
    aberto = F.em_aberto()
    if aberto is not None:
        F.pedir("cancelar")
    if MC.aberto():
        MC.fechar()
    try:
        RES.fechar()
    except Exception as e:  # noqa: BLE001
        print("  resolve:", e, flush=True)


def acompanhar(t, f_id=None, prazo=PRAZO_DA_EXECUCAO):
    """Até o fluxo parar. Devolve o fluxo, e guarda o tempo de cada node."""
    ini, antes = time.time(), None
    while time.time() - ini < prazo:
        f = F.em_aberto() or (F.ler(f_id) if f_id else None)
        if f is None:
            f = next((F.ler(p.stem) for p in sorted(F.pasta().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:1]), None)
        if f is not None:
            f_id = f.id
            agora = (f.estado, f.atual)
            if agora != antes:
                antes = agora
                print(f"   {time.strftime('%H:%M:%S')} {f.estado} · passo {f.atual + 1}/{len(f.passos)} {(f.passos[f.atual].id if f.atual < len(f.passos) else '')}", flush=True)
            if f.estado not in ("correndo",):
                break
        time.sleep(1.0)
    f = F.ler(f_id)
    registro["fluxo"] = {"id": f.id, "nome": f.nome, "estado": f.estado, "origem": f.origem, "parametros": {k: v for k, v in f.parametros.items()},
                         "passos": [{"id": p.id, "op": p.op, "estado": p.estado, "segundos": p.segundos, "tentativas": p.tentativas, "motivo": p.motivo, "avisos": p.avisos,
                                     "resumo": {k: v for k, v in (p.saida or {}).items() if k in ("segundos", "custo_usd", "agente_do_piloto", "feito", "salvou", "nota", "manchete", "erro")}} for p in f.passos]}
    gravar()
    return f


def subir():
    # ⭐ O app de verdade aberto ao lado: é a janela dele que o produto usa para tirar o foco do MC e para sair da frente do piloto.
    exe = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process cicloassist -ErrorAction SilentlyContinue | Select-Object -First 1).Path"], capture_output=True, text=True).stdout.strip()
    if exe and "--sem-app" not in sys.argv:
        from cicloassist.servico import aplicativo as _app
        _app.apresentar(exe)
        registro["janela_do_app"] = exe
    H.PORTA = PORTA
    rotas.url_do_mcp.__defaults__ = (PORTA, "chat")
    return H.subir(PORTA)


def executar_na_janela(t):
    """O formulário de Executar: a pasta pelo botão, o resto preenchido; o preço é lido antes do clique."""
    t.em(t.txt("button", "Executar fluxo"))
    time.sleep(.3)
    ps = t.a("quadro.g.parametros")
    registro["preco_na_tela"] = t.a("(function(){var n=document.querySelector('.form-exec');return n?n.innerText:''})()")
    for k, spec in ps.items():
        if spec.get("tipo") in ("pasta", "arquivo"):
            t.em(t.txt(".form-exec button", "Escolher"))
            time.sleep(.3)
    valores = {}
    for k, spec in ps.items():
        n = k.lower()
        if spec.get("tipo") in ("pasta", "arquivo") or spec.get("padrao") not in (None, ""):
            continue
        valores[k] = "BENCH NOITE" if "proj" in n else DIARIA_DO_CHAT if "diar" in n or "nome" in n else "BENCH"
    if "diaria" in {k.lower() for k in ps}:
        valores["diaria"] = DIARIA_DO_CHAT
    t.a(f"Object.assign(formExec.valores,{json.dumps(valores)});desenharDireita()")
    time.sleep(.2)
    t.foto("formulario")
    t.em(t.txt(".form-exec button", "Executar"))


PEDIDO = ("Quero um fluxo para preparar uma diária: pegar uma pasta com os vídeos e os WAV, converter os vídeos em OP-Atom no DaVinci Resolve, fechar o Resolve, "
          "abrir ou criar o projeto no Media Composer, importar a câmera e o som direto, sincronizar com subclipes por cena e salvar tudo.")


def criar_pelo_chat():
    programas_fechados()
    t = Tela()
    try:
        with Etapa("abrir a janela e começar um fluxo novo"):
            t.ir(1150, 640, "/oficina")
            t.esperar("document.getElementById('criarFluxo')!==null")
            t.a("fetch('/limpar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversa:'oficina'})}).then(function(){return 1})")
            time.sleep(1)
            t.em("document.getElementById('criarFluxo')")
            time.sleep(.2)
            t.escrever("Benchmark da noite")
            t.tecla("Enter", "Enter", 13, "\r")
        with Etapa("pedir o fluxo ao chat (IA)"):
            t.em("document.querySelector('.compositor textarea')")
            t.escrever(PEDIDO)
            t.tecla("Enter", "Enter", 13, "\r")
            veio = t.esperar("!!document.querySelector('.proposta:not(.decidida)')", 300)
            registro["proposta"] = t.a("(function(){var n=document.querySelector('.proposta');return n?n.innerText:''})()")
            t.foto("proposta")
            if not veio:
                raise RuntimeError("o chat não propôs: " + str(t.a("document.querySelector('.direita')?document.querySelector('.direita').innerText:document.body.innerText"))[:400])
        with Etapa("aceitar, conferir e salvar"):
            t.em(t.txt(".proposta button", "Aceitar"))
            time.sleep(.5)
            registro["nodes"] = t.a("quadro.g.nos.map(function(n){return n.d.rotulo+(n.d.detalhe?' ('+n.d.detalhe+')':'')})")
            t.foto("nodes_aceitos")
            t.em(t.txt("button", "Conferir"))
            time.sleep(.5)
            registro["conferir"] = t.a("(function(){var c=document.querySelector('.problemas');return c&&!c.hidden?c.innerText:''})()")
            t.em(t.txt("button", "Salvar fluxo"))
            if not t.esperar("!quadro.g.sujo&&!!quadro.g.fluxo.nome", 15):
                raise RuntimeError("não salvou: " + str(t.a("document.body.innerText"))[:300])
            registro["nome_do_fluxo"] = t.a("quadro.g.fluxo.nome")
        with Etapa("executar o fluxo inteiro"):
            executar_na_janela(t)
            time.sleep(1.5)
            f = acompanhar(t)
            t.foto("fim")
            if f.estado != "pronto":
                foto_da_maquina("parou")
                obs(f"o fluxo parou em {f.estado}: " + "; ".join(f"{p.id}: {p.motivo}" for p in f.passos if p.motivo))
    finally:
        t.fim()


def receita_da_casa():
    programas_fechados()
    t = Tela()
    try:
        with Etapa("achar o fluxo no menu do chat e preencher"):
            t.ir(560, 760, "/painel?casca=app")
            t.em("document.getElementById('abrirMenu')")
            time.sleep(.5)
            if not t.esperar(t.txt("#menuFluxos button", "Preparar a diária") + "!==undefined", 6):
                raise RuntimeError("o fluxo não está no menu")
            registro["menu"] = t.a("Array.from(document.querySelectorAll('#menuFluxos button')).map(function(b){return b.textContent})")
            t.em(t.txt("#menuFluxos button", "Preparar a diária no Media Composer"))
            time.sleep(.3)
            registro["preco_na_tela"] = t.a("document.querySelector('.receita-forma').innerText")
            t.em(t.txt(".receita-forma button", "Escolher a pasta"))
            time.sleep(.4)
            t.a("(function(){var c=Array.from(document.querySelectorAll('.receita-campo'));c.forEach(function(x){var r=x.querySelector('.rot').textContent,i=x.querySelector('input');if(!i){return}if(r.indexOf('Nome da di')>=0){i.value='" + DIARIA_DA_CASA + "'}if(r.indexOf('Projeto')>=0){i.value='BENCH NOITE'}})})()")
            t.foto("formulario")
        with Etapa("executar o fluxo inteiro"):
            t.em(t.txt(".receita-forma button", "Executar"))
            time.sleep(1.5)
            f = acompanhar(t)
            time.sleep(1.2)
            t.foto("fim")
            if f.estado != "pronto":
                foto_da_maquina("parou")
                obs(f"o fluxo parou em {f.estado}: " + "; ".join(f"{p.id}: {p.motivo}" for p in f.passos if p.motivo))
    finally:
        t.fim()


def nodes_na_mao():
    """Do zero só com o mouse, sem IA nenhuma: três nodes, as ligações puxadas à mão, Propriedades, e roda de verdade."""
    programas_fechados()
    t = Tela()
    try:
        with Etapa("criar o fluxo e pôr os nodes"):
            t.ir(1150, 640, "/oficina")
            t.esperar("document.getElementById('criarFluxo')!==null")
            t.em("document.getElementById('criarFluxo')")
            time.sleep(.2)
            t.escrever("Abrir salvar e fechar")
            t.tecla("Enter", "Enter", 13, "\r")
            for peca in ("Abrir programa", "Salvar tudo", "Fechar programa"):
                t.em("document.querySelector('[aria-label=\"Adicionar\"]')")
                time.sleep(.1)
                t.em(t.txt("button", "Adicionar Node"))
                time.sleep(.1)
                t.em(t.txt("button", peca))
                time.sleep(.2)
            registro["nodes"] = t.a("quadro.g.nos.map(function(n){return n.d.rotulo})")
            t.foto("nodes_como_nascem")
            registro["distancia_entre_nodes_ao_nascer"] = t.a("(function(){var n=quadro.g.nos;return [n[1].x-n[0].x,n[1].y-n[0].y,n[0].l]})()")
            obs(f"os nodes novos nascem a {registro['distancia_entre_nodes_ao_nascer'][:2]} px um do outro, cobrindo o anterior (largura {registro['distancia_entre_nodes_ao_nascer'][2]})")
            t.em("document.querySelector('[aria-label=\"Adicionar\"]')")
            time.sleep(.1)
            t.em(t.txt("button", "Organizar"))
            time.sleep(.3)
            t.foto("nodes_organizados")
        with Etapa("ligar os nodes puxando as alças"):
            pares = [("Abrir programa", "Salvar tudo"), ("Salvar tudo", "Fechar programa")]
            for de, para in pares:
                origem, destino = t.txt(".node", de), t.txt(".node", para)
                t.em(origem)
                r = t.a(f"(function(){{var r=({origem}).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")
                t.ws.chamar("Input.dispatchMouseEvent", type="mouseMoved", x=r[0], y=r[1], button="none", clickCount=0, buttons=0)
                time.sleep(.1)
                xp, yp = t.a(f"(function(){{var r=({origem}).querySelector('.porta.e').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")
                xd, yd = t.a(f"(function(){{var r=({destino}).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")
                t.ws.chamar("Input.dispatchMouseEvent", type="mouseMoved", x=xp, y=yp, button="none", clickCount=0, buttons=0)
                t.ws.chamar("Input.dispatchMouseEvent", type="mousePressed", x=xp, y=yp, button="left", clickCount=1, buttons=1)
                for i in range(1, 11):
                    t.ws.chamar("Input.dispatchMouseEvent", type="mouseMoved", x=xp + (xd - xp) * i / 10, y=yp + (yd - yp) * i / 10, button="left", clickCount=0, buttons=1)
                t.ws.chamar("Input.dispatchMouseEvent", type="mouseReleased", x=xd, y=yd, button="left", clickCount=1, buttons=0)
                registro["cliques"] += 2
                time.sleep(.2)
            registro["ligacoes"] = t.a("quadro.g.fios.length")
        with Etapa("preencher as Propriedades"):
            for node, projeto in (("Abrir programa", True), ("Fechar programa", False)):
                t.em(t.txt(".node", node), 2)
                time.sleep(.2)
                t.a("(function(){var s=Array.from(document.querySelectorAll('.props select')).filter(function(x){return Array.from(x.options).some(function(o){return o.value==='media_composer'})})[0];s.value='media_composer';s.dispatchEvent(new Event('change',{bubbles:true}))})()")
                time.sleep(.2)
                if projeto:
                    registro["propriedades"] = t.a("document.querySelector('.props').innerText")
                    t.em("Array.from(document.querySelectorAll('.props input.entrada')).filter(function(i){return i.offsetParent})[0]")
                    t.escrever("BENCH NOITE")
                    t.tecla("Tab", "Tab", 9)
                    time.sleep(.2)
            t.foto("propriedades")
        with Etapa("conferir e salvar"):
            t.em(t.txt("button", "Conferir"))
            time.sleep(.5)
            registro["conferir"] = t.a("(function(){var c=document.querySelector('.problemas');return c&&!c.hidden?c.innerText:''})()")
            print("  conferir:", registro["conferir"], flush=True)
            t.em(t.txt("button", "Salvar fluxo"))
            if not t.esperar("!quadro.g.sujo&&!!quadro.g.fluxo.nome", 15):
                raise RuntimeError("não salvou: " + str(registro["conferir"]))
            registro["nome_do_fluxo"] = t.a("quadro.g.fluxo.nome")
        with Etapa("executar"):
            executar_na_janela(t)
            time.sleep(1.5)
            f = acompanhar(t)
            t.foto("fim")
            if f.estado != "pronto":
                foto_da_maquina("parou")
                obs(f"o fluxo parou em {f.estado}: " + "; ".join(f"{p.id}: {p.motivo}" for p in f.passos if p.motivo))
    finally:
        t.fim()


class ReceitaTemporaria:
    def __init__(self, nome, passos, titulo):
        self.arq, self.texto = RX.pasta_do_editor() / f"{nome}.md", RX.texto_de(nome, "Cenário do teste pilotado.", {}, passos, titulo)
        self.titulo = titulo

    def __enter__(self):
        self.arq.parent.mkdir(parents=True, exist_ok=True)
        self.arq.write_text(self.texto, encoding="utf-8")
        return self

    def __exit__(self, *_):
        self.arq.unlink(missing_ok=True)


def mais_novo():
    return next((x.stem for x in sorted(F.pasta().glob("*.json"), key=lambda y: y.stat().st_mtime, reverse=True)[:1]), "")


def garantir_modal(*args, tentativas=4):
    """O preparo insiste até o diálogo existir: o clique no menu File falha de vez em quando, e um cenário sem o diálogo não prova nada."""
    from cicloassist.avid import socorro as SC
    for _ in range(tentativas):
        spike(*args)
        time.sleep(1)
        m = SC._modal()
        if m and "Avid" in m[2] and m[2] != "AvidMediaComposer":
            print("  diálogo na tela:", m[2], m[1], flush=True)
            return True
    obs("o preparo não conseguiu pôr o diálogo na tela")
    return False


def rodar_pelo_menu(t, titulo):
    aberto = F.em_aberto()
    if aberto is not None:
        F.pedir("cancelar")
    antes = mais_novo()
    t.ir(560, 760, "/painel?casca=app")
    t.em("document.getElementById('abrirMenu')")
    time.sleep(.5)
    t.esperar(t.txt("#menuFluxos button", titulo) + "!==undefined", 6)
    t.em(t.txt("#menuFluxos button", titulo))
    time.sleep(.3)
    t.em(t.txt(".receita-forma button", "Executar"))
    fim, ini_clique = time.time() + 75, time.time()
    while time.time() < fim and mais_novo() == antes:
        time.sleep(.1)
    registro["segundos_do_clique_ate_comecar"] = round(time.time() - ini_clique, 1)
    if mais_novo() == antes:
        registro["recusado_ao_comecar"] = t.a("(function(){var n=document.querySelector('.receita-forma');return n?n.innerText:''})()")
        obs("o fluxo não começou: " + str(registro["recusado_ao_comecar"])[-300:])
        t.foto("nao_comecou")
    return mais_novo()


def spike(*args):
    r = subprocess.run([sys.executable, str(RAIZ / "spikes" / "o_agente_do_piloto.py"), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=400)
    print(f"  [spike {args[0]}] saiu {r.returncode}", (r.stdout or "")[-160:].replace("\n", " "), (r.stderr or "")[-200:], flush=True)


def pausar_e_retomar():
    programas_fechados()
    t = Tela()
    passos = [{"id": "abrir", "op": "abrir_programa", "args": {"programa": "resolve", "projeto": "BENCH PAUSA"}}, {"id": "fechar", "op": "fechar_programa", "args": {"programa": "resolve"}}]
    with ReceitaTemporaria("bench-pausa", passos, "Bench pausa"):
        try:
            with Etapa("rodar e pedir Pausar no meio do 1º passo"):
                rodar_pelo_menu(t, "Bench pausa")
                t.esperar(t.txt("#fluxosQuadro button", "Pausar") + "!==undefined", 10)
                t.em(t.txt("#fluxosQuadro button", "Pausar"))
                f = acompanhar(t)
                registro["pausou_em"] = {"estado": f.estado, "passo": f.atual, "feitos": [p.id for p in f.passos if p.estado == "feito"]}
                t.foto("pausado")
            with Etapa("retomar até o fim"):
                t.esperar(t.txt("#fluxosQuadro button", "Retomar") + "!==undefined", 15)
                t.em(t.txt("#fluxosQuadro button", "Retomar"))
                time.sleep(1.5)
                f = acompanhar(t)
                if f.estado != "pronto":
                    obs(f"parou em {f.estado}")
        finally:
            t.fim()


def pasta_errada():
    """O erro mais comum de quem usa: a pasta não tem a mídia. O que a tela diz, e quanto de IA o erro custa."""
    programas_fechados()
    vazia = tempfile.mkdtemp(prefix="pasta_sem_midia_")
    SEL.escolher = lambda *a, **k: [vazia]
    t = Tela()
    try:
        with Etapa("rodar o fluxo da casa numa pasta vazia"):
            t.ir(560, 760, "/painel?casca=app")
            t.em("document.getElementById('abrirMenu')")
            time.sleep(.5)
            t.esperar(t.txt("#menuFluxos button", "Preparar a diária") + "!==undefined", 6)
            t.em(t.txt("#menuFluxos button", "Preparar a diária no Media Composer"))
            time.sleep(.3)
            t.em(t.txt(".receita-forma button", "Escolher a pasta"))
            time.sleep(.4)
            t.a("(function(){Array.from(document.querySelectorAll('.receita-campo')).forEach(function(x){var r=x.querySelector('.rot').textContent,i=x.querySelector('input');if(i&&r.indexOf('Projeto')>=0){i.value='BENCH NOITE'}})})()")
            t.em(t.txt(".receita-forma button", "Executar"))
            time.sleep(1.5)
            f = acompanhar(t)
            registro["mensagem_na_tela"] = [p.motivo for p in f.passos if p.motivo]
        with Etapa("ver a recomendação da IA e cancelar"):
            time.sleep(25)      # o painel pede o conselho sozinho
            registro["conversa_depois_da_falha"] = t.a("document.getElementById('conversa').innerText")[-500:]
            t.foto("falha")
            t.em(t.txt("#fluxosQuadro button", "Cancelar"))
            time.sleep(1)
    finally:
        t.fim()
        programas_fechados()


def dialogo_seguro_no_fluxo():
    programas_fechados()
    t = Tela()
    passos = [{"id": "abrir", "op": "abrir_programa", "args": {"programa": "media_composer", "projeto": "BENCH NOITE"}}]
    with ReceitaTemporaria("bench-dialogo", passos, "Bench dialogo"):
        try:
            with Etapa("preparar: aviso desconhecido na tela do MC (fora da conta)"):
                etapa_atual[0] = "preparo (fora da conta)"
                spike("arrancar")
                garantir_modal("duplicar", "BENCH NOITE", "1080p/25")
            with Etapa("o fluxo abre o projeto com o aviso no caminho"):
                f = acompanhar(t, rodar_pelo_menu(t, "Bench dialogo"))
                t.foto("fim")
                if f.estado != "pronto":
                    obs(f"parou em {f.estado}: " + "; ".join(p.motivo for p in f.passos if p.motivo))
        finally:
            t.fim()


def dialogo_recusado_no_fluxo():
    t = Tela()
    passos = [{"id": "salvar", "op": "salvar_tudo", "args": {}}]
    with ReceitaTemporaria("bench-recusa", passos, "Bench recusa"):
        try:
            with Etapa("preparar: a pergunta de sair na tela do MC (fora da conta)"):
                etapa_atual[0] = "preparo (fora da conta)"
                garantir_modal("pedir_sair")
            with Etapa("o fluxo tenta salvar com a pergunta no caminho"):
                f = acompanhar(t, rodar_pelo_menu(t, "Bench recusa"))
                registro["mensagem_na_tela"] = [p.motivo for p in f.passos if p.motivo]
            with Etapa("esperar o conselho, tirar a pergunta e tentar de novo"):
                time.sleep(25)
                registro["conversa_depois_da_falha"] = t.a("document.getElementById('conversa').innerText")[-600:]
                t.foto("falha")
                etapa_atual[0] = "preparo (fora da conta)"
                spike("cancelar")
                etapa_atual[0] = "esperar o conselho, tirar a pergunta e tentar de novo"
                t.em(t.txt("#fluxosQuadro button", "Tentar de novo"))
                time.sleep(1.5)
                f = acompanhar(t)
                if f.estado != "pronto":
                    obs(f"parou em {f.estado}: " + "; ".join(p.motivo for p in f.passos if p.motivo))
        finally:
            t.fim()


CENARIOS = {"criar_pelo_chat": criar_pelo_chat, "receita_da_casa": receita_da_casa, "nodes_na_mao": nodes_na_mao, "pausar_e_retomar": pausar_e_retomar,
            "pasta_errada": pasta_errada, "dialogo_seguro_no_fluxo": dialogo_seguro_no_fluxo, "dialogo_recusado_no_fluxo": dialogo_recusado_no_fluxo}

if __name__ == "__main__":
    registro["cenario"] = sys.argv[1]
    srv = subir()
    try:
        CENARIOS[sys.argv[1]]()
    except Exception as e:  # noqa: BLE001
        obs(f"o roteiro parou: {e.__class__.__name__}: {e}")
        foto_da_maquina("erro_do_roteiro")
    finally:
        registro["fim"] = time.strftime("%Y-%m-%d %H:%M:%S")
        gravar()
        srv.shutdown()
    print(json.dumps({"etapas": registro["etapas"], "ia_chamadas": len(registro["ia"]), "cliques": registro["cliques"]}, ensure_ascii=False), flush=True)
