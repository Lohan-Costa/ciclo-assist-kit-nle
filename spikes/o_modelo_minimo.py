"""MEDIDO 2026-11-02 (handoff). Usa `dirigir.req` (HTTP same-origin, ver o handoff). A prova do modelo mínimo: a missão (até o cartão) e o conselho com gabarito. Uso: bancada_modelo.py <modelo> <saida.jsonl>"""
import sys, json, time, copy, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[3] if len(sys.argv) > 3 else ".")
from dirigir import req, B
from cicloassist.servico import config as cfg, fluxo
from cicloassist.motor import conselho

MODELO, SAIDA = sys.argv[1], sys.argv[2]
PASTA = r"%USERPROFILE%\Desktop\MIDIAS SIMULADAS"
PROJETO = "BANCADA MODELO"
ORIGEM = "C:/Users/USUARI~1/AppData/Local/Temp/claude/D--PROGRAMAS-COM-CLAUDE-2-ATIVOS--CICLO-ASSIST/9234319f-407c-4a20-b7c1-789016a692ad/scratchpad/origem_arrasto"
out = open(SAIDA, "w", encoding="utf-8")
def log(**d):
    d["t"] = time.strftime("%H:%M:%S"); out.write(json.dumps(d, ensure_ascii=False) + "\n"); out.flush()

antes = {k: cfg.ler().get(k) for k in ("modelo", "auto")}
log(fase="inicio", modelo=MODELO, config_antes=antes)
nota = {"modelo": MODELO}
try:
    r = req("POST", "/configuracoes", {"modelo": MODELO, "auto": False})
    log(fase="config", resposta=r)
    # ── a MISSÃO ─────────────────────────────────────────────────────────────
    req("POST", "/limpar", {"nle": "avid"})
    req("POST", "/arrastados", {"caminhos": [PASTA]})
    pergunta = (f"Converta no Resolve o material da pasta que anexei, leve para o Media Composer no projeto "
                f"'{PROJETO}' (se não existir, crie em 1080p/25) e faça o sync. A diária é a D01.")
    corpo = {"pergunta": pergunta, "nle": "avid",
             "referencias": [{"tipo": "arquivo", "caminho": PASTA, "nome": "MIDIAS SIMULADAS"}]}
    rq = urllib.request.Request(B + "/conversar", method="POST", data=json.dumps(corpo).encode(),
                                headers={"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"})
    t0 = time.monotonic(); chamadas = []; texto = []; tipo = None; motivo_fim = ""; primeira = None
    with urllib.request.urlopen(rq, timeout=900) as x:
        for linha in x:
            linha = linha.decode("utf-8").rstrip("\n")
            if linha.startswith("event: "):
                tipo = linha[7:]; continue
            if not linha.startswith("data: "):
                continue
            d = json.loads(linha[6:]); s = round(time.monotonic() - t0, 1)
            if tipo == "texto":
                texto.append(d.get("texto") or d.get("delta") or "")
            if tipo == "ferramenta":
                primeira = primeira or s
                chamadas.append((d.get("nome"), json.dumps(d.get("entrada"), ensure_ascii=False, sort_keys=True)))
                log(fase="missao", s=s, ferramenta=d.get("nome"), entrada=d.get("entrada"))
            if tipo == "pendencia" or (tipo == "ferramenta" and d.get("nome") == "executar_fluxo"):
                pass
            if tipo in ("erro", "fim", "cancelado"):
                motivo_fim = f"{tipo}: {json.dumps(d, ensure_ascii=False)[:200]}"; break
            repetida = max((chamadas.count(c) for c in chamadas), default=0)
            if len(chamadas) > 10 or repetida >= 3 or s > 600:
                motivo_fim = f"cortado: {len(chamadas)} chamadas, a mesma {repetida}x, {s} s"
                req("POST", "/conversar/parar", {"nle": "avid"}); break
    dur = round(time.monotonic() - t0, 1)
    pend = req("GET", "/pendencias").get("pendencias") or []
    fluxos = [p for p in pend if "fluxo" in str(p.get("ferramenta", "")).lower() or "executar" in json.dumps(p)[:300]]
    entrada = (fluxos[0].get("entrada") if fluxos else {}) or {}
    par = entrada.get("parametros") or (entrada.get("plano") or {}).get("parametros") or {}
    receita = entrada.get("receita_de") or entrada.get("receita") or ""
    certos = {"receita": receita == "preparar-diaria-no-mc",
              "pasta": str(par.get("pasta", "")).rstrip("\/").lower() == PASTA.lower(),
              "diaria": par.get("diaria") == "D01", "projeto": par.get("projeto") == PROJETO,
              "formato": par.get("formato") == "1080p/25"}
    repetidas = sum(1 for c in set(chamadas) if chamadas.count(c) > 1)
    inventou = sum(1 for n, e in chamadas if n in ("ler_arquivo", "conformar_no_resolve"))
    nota["missao"] = {"cartao": bool(fluxos), "certos": certos, "pontos": sum(certos.values()),
                      "chamadas": len(chamadas), "repetidas": repetidas, "fora_do_caminho": inventou,
                      "primeira_acao_s": primeira, "duracao_s": dur, "fim": motivo_fim,
                      "texto": "".join(texto)[:400]}
    log(fase="missao_fim", **nota["missao"], parametros=par, receita=receita)
    for p in pend:                                   # nada fica esperando o editor
        req("POST", "/responder", {"id": p["id"], "permitido": False})
    # ── o CONSELHO ───────────────────────────────────────────────────────────
    base = fluxo.ler("20261102-124638-6be023")
    CASOS = {  # caso: (passo, motivo, certo, aceitavel, grave)
        "A": (3, "há um aviso do Media Composer na tela e não consegui achar o botão \"Don't warn me again\" — responda a ele e tente de novo",
              {"esperar"}, set(), {"pular", "cancelar"}),
        "B": (1, "o servidor de scripts do Resolve não está no ar", {"esperar", "tentar_de_novo"}, set(), {"pular", "cancelar"}),
        "C": (5, "não há arquivo WAV na pasta origem_arrasto (só vídeos)", {"esperar"}, {"pular"}, {"cancelar"}),
    }
    pts = 0; graves = 0; tempos = []
    for caso, (i, motivo, certo, aceitavel, grave) in CASOS.items():
        for n in range(3):
            f = copy.deepcopy(base); f.estado = "esperando"
            if caso == "C":   # a MIDIAS SIMULADAS TEM 4 .wav (SOM DIRETO): o caso precisa de pasta só de vídeo
                f.parametros = {**f.parametros, "pasta": ORIGEM}
            for k, p in enumerate(f.passos):
                p.estado = "feito" if k < i else ("falhou" if k == i else "a_fazer")
            f.passos[i].motivo, f.passos[i].tentativas = motivo, 1
            t = time.monotonic()
            try:
                c = conselho.aconselhar(f, fluxo.condicoes_da_receita(f), modelo=MODELO); a = c["acao"]
            except Exception as e:
                c, a = {}, f"ERRO: {e}"[:120]
            s = round(time.monotonic() - t, 1); tempos.append(s)
            p_ = 2 if a in certo else (1 if a in aceitavel else 0); pts += p_; graves += a in grave
            log(fase="conselho", caso=caso, n=n, acao=a, pontos=p_, grave=a in grave, s=s,
                explicacao=(c.get("explicacao") or "")[:300])
    nota["conselho"] = {"pontos": pts, "de": 18, "graves": graves, "s_medio": round(sum(tempos) / len(tempos), 1)}
    log(fase="conselho_fim", **nota["conselho"])
finally:
    req("POST", "/configuracoes", {"modelo": antes.get("modelo") or "claude-sonnet-5-5", "auto": bool(antes.get("auto"))})
    log(fase="FIM", nota=nota, config_devolvida={k: cfg.ler().get(k) for k in ("modelo", "auto")})
