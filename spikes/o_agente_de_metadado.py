"""A0: o agente de metadado nos três materiais, sem interface (só leitura dos WAV; uma chamada ao modelo por material)."""
import collections, json, re, struct, sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\PROGRAMAS COM CLAUDE\2 ATIVOS\_CICLO ASSIST")
from cicloassist.motor import conselho as C
from cicloassist.motor.claude import achar_o_cli, ambiente_do_modelo
from cicloassist.servico import config as cfg
import subprocess

MATERIAIS = {
    "PRODUCAO-A": Path(r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\MIDIAS\CONVERTIDOS\D02_230405\02_SOM-DIRETO\SD02"),
    "PRODUCAO_B": Path(r"D:\AUDIOS ANALISAR\24Y07M18"),
    "DIARIA_03": Path(r"D:\AUDIOS ANALISAR\Diaria 03 - 24_07_24\SOM"),
}

INSTRUCAO = """\
Você é o agente de metadado de um assistente de montagem. Recebe o resumo dos arquivos de som de uma diária: as FORMAS dos nomes
(cada número virou #), com contagem e amostras, e os campos SCENE e TAKE de dois blocos de metadado (bext e iXML), que podem diferir.

Tarefa: dizer como ler episódio, cena, plano e take de cada forma, e perguntar o que não dá para saber.

Regras:
- Proponha REGRAS por forma, nunca valores por arquivo.
- Cada regra é uma expressão regular em Python, aplicada ao nome do arquivo sem extensão, com grupos nomeados entre: episodio, cena, plano, take. Só inclua o grupo que você consegue justificar.
- Só trate como certo o que tem rótulo escrito no nome ou no metadado. O que é inferência pela posição dos números tem "certeza": "presumida".
- Parte do nome cujo significado você não conhece NÃO é interpretada: ela vira pergunta ao editor.
- Uma forma sem leitura segura fica de fora da lista de regras e vira pergunta.

Responda SOMENTE com um objeto JSON com os campos `regras` (lista de objetos com `forma`, `regex`, `certeza` e `por_que`), `perguntas` (lista de textos) e `fora` (lista de formas sem regra)."""

def chunks(p):
    o = {}
    with open(p, "rb") as f:
        f.seek(12)
        while True:
            h = f.read(8)
            if len(h) < 8:
                return o
            n, t = h[:4], struct.unpack("<I", h[4:])[0]
            if n in (b"iXML", b"bext"):
                o[n] = f.read(t)
                f.seek(t & 1, 1)
            else:
                f.seek(t + (t & 1), 1)

def tag(x, n):
    m = re.search(rf"<{n}>(.*?)</{n}>", x, re.S)
    return m.group(1).strip() if m else None

def forma(s):
    return re.sub(r"\d+", "#", s)

def coletar(pasta):
    linhas = []
    for p in sorted(pasta.glob("*.[wW][aA][vV]")):
        if p.name.startswith("._"):
            continue
        c = chunks(p)
        x = c.get(b"iXML", b"").decode("utf-8", "replace")
        d = dict(re.findall(r"[a-zA-Z]?([A-Z_0-9]+)=([^\r\n]*)", c.get(b"bext", b"")[:256].decode("latin-1").split("\0")[0]))
        linhas.append({"stem": p.stem, "ix_scene": tag(x, "SCENE"), "ix_take": tag(x, "TAKE"), "bx_scene": d.get("SCENE"), "bx_take": d.get("TAKE")})
    return linhas

def resumo(linhas):
    g = collections.defaultdict(list)
    for l in linhas:
        g[forma(l["stem"])].append(l)
    return [{"forma": k, "quantos": len(v), "amostras": [{"nome": a["stem"], "iXML_SCENE": a["ix_scene"], "iXML_TAKE": a["ix_take"],
             "bext_SCENE": a["bx_scene"], "bext_TAKE": a["bx_take"]} for a in v[:3]]} for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))]

def conferir(linhas, regras):
    cobertos, contrad = 0, []
    for l in linhas:
        for r in regras:
            try:
                m = re.search(r["regex"], l["stem"])
            except re.error as e:
                print("   regex inválida:", r["regex"], e)
                continue
            if m:
                cobertos += 1
                gd = m.groupdict()
                t = gd.get("take")
                if t and l["ix_take"] and int(re.sub(r"\D", "", t) or -1) != int(re.sub(r"\D", "", l["ix_take"]) or -2):
                    contrad.append((l["stem"], t, l["ix_take"]))
                break
    return cobertos, contrad

modelo = cfg.modelo_guardado()
nome_m, amb = ambiente_do_modelo(modelo)
for nome, pasta in MATERIAIS.items():
    linhas = coletar(pasta)
    r = resumo(linhas)
    pedido = f"Diária: {nome}\nFormas:\n{json.dumps(r, ensure_ascii=False)}"
    cmd = [achar_o_cli(), "-p", pedido, "--system-prompt", INSTRUCAO, "--output-format", "stream-json", "--verbose", "--strict-mcp-config", "--restricted", "--tools", ""]
    if nome_m:
        cmd += ["--model", nome_m]
    t0 = time.monotonic()
    s = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=180, env=amb)
    texto, uso = "", {}
    for ln in s.stdout.splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if ev.get("type") == "result":
            texto, uso = str(ev.get("result") or ""), ev.get("usage") or {}
    print("=" * 80)
    print(nome, "|", len(linhas), "WAV |", len(r), "formas |", round(time.monotonic() - t0, 1), "s | modelo", nome_m, "| tokens", uso.get("input_tokens"), uso.get("cache_creation_input_tokens"), uso.get("cache_read_input_tokens"), uso.get("output_tokens"))
    print("formas:", [(f["forma"], f["quantos"]) for f in r][:12])
    try:
        d = C._json(texto)
    except Exception as e:
        print("resposta ilegível:", e, texto[:400])
        continue
    for x in d.get("regras", []):
        print("  REGRA", x.get("forma"), "|", x.get("regex"), "|", x.get("certeza"), "|", str(x.get("por_que"))[:150])
    print("  PERGUNTAS:", d.get("perguntas"))
    print("  FORA:", d.get("fora"))
    cob, con = conferir(linhas, d.get("regras", []))
    print(f"  CONFERÊNCIA: cobre {cob} de {len(linhas)}; contradiz o TAKE do iXML em {len(con)} {con[:3]}")
