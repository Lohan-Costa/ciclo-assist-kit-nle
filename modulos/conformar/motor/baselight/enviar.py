"""A cadeia do conform no Baselight, do xmeml já decidido ao resumo (proposta do Ciclo Assist
`docs/plano/2026-11-22-baselight-no-app.md`, etapa 2) — o caminho C do laboratório BL08 (14 certos, 4 alertas, 0
errados no Premiere; 16 ok + 1 offline no MC), agora no produto:

    entrega.reescrever  → o xmeml com o ORIGINAL decidido em cada `<file>` (o ambíguo e o sem original vão OFFLINE)
    bl-conform          → uma scene NOVA no job da PRODUÇÃO (nunca sobrescreve: "… · import 02")
    bl-shots            → a conferência: arquivo + 1º e último quadro visível de cada plano
    bl-shots -replace   → o que o Baselight trocou por conta própria volta ao original decidido, só naquele plano
    FLAPI (markers)     → o que não se corrige vira marker "[Ciclo] …" (o toggle do painel)

Decisões do autor (2026-11-22): um job por produção (job = projeto, scene = timeline); nunca sobrescrever e sem "V02" (a
versão confundiria com uma versão da montagem): a nova importação leva " · import 02"; entrega com alerta > erro calado.

Plataforma: o Baselight roda no macOS (e no Linux, que não é alvo da família); no Windows não há Baselight — `bin_dir()`
devolve `None` e `disponivel()` diz por quê. Os serviços do Baselight (`flapid`, o banco) ficam no ar com a INTERFACE
fechada: conform, conferência e markers andam sem ela (medido no Mac mini, 7.0.3); o RENDER não (fica "Queued").
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

from . import conferencia as C
from . import entrega as E

HOST = "localhost"
#: o python da FilmLight, com a `flapi` (o instalador do Baselight o põe aqui no Mac)
PY_FL_MAC = "/Library/Application Support/FilmLight/python/*-venv/bin/python"
MARCAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "marcar_flapi.py")
COR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cor_flapi.py")
ESTAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estabilizar_flapi.py")
EFEITOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "efeitos_flapi.py")
MASCARAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mascaras_flapi.py")
TITULOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "titulos_flapi.py")
#: o sufixo da scene provisória quando os títulos vêm (o bl-import cria a da entrega; a provisória é apagada — autor)
SUFIXO_PROVISORIA = " · provisória do Ciclo"
#: o prazo de UM plano mascarado (abrir, apply, salvar): no estudo, 0,2–0,3 s cada mais a abertura
PRAZO_MASCARA = 120
#: o marker do plano estabilizado (o colorista precisa saber por que o Motion está em 0)
MARCA_ESTAB = ("estabilização do MC traduzida: tracker nativo com o rastreio do MC (Motion 0) e o movimento lento "
               "nos keyframes de posição do Transform — subir o Motion devolve o lento duas vezes")
#: o sufixo da importação repetida (autor, 2026-11-22: "import 02", nunca "V02")
SUFIXO_IMPORT = " · import {:02d}"
#: o nome de job/scene: o Baselight aceita espaço e "·" (medido 7.0.3); ":" separa host:job:scene e "/" vira pasta
_PROIBIDO = re.compile(r"[:/\\\x00-\x1f]")


class ColoristaNaoSalvou(RuntimeError):
    """A scene do colorista está aberta no Baselight com mudança NÃO SALVA: de fora não se lê (medido, 7.0.3)."""

    def __init__(self, scene: str):
        super().__init__(f"a scene “{scene}” tem mudanças não salvas no Baselight: peça ao colorista para salvar "
                         "(Scene › Save, ⌘S) e tente de novo — nada foi criado")
        self.scene = scene


class BaselightIndisponivel(RuntimeError):
    """Sem Baselight nesta máquina (Windows, ou não instalado): o painel mostra a frase."""


def _versao(caminho: str) -> tuple[int, ...]:
    m = re.search(r"Baselight-([0-9.]+)\.app", caminho)
    return tuple(int(x) for x in m.group(1).split(".") if x) if m else ()


def bin_dir() -> str | None:
    """A pasta `Contents/bin` do Baselight mais novo instalado (`bl-conform`, `bl-shots`…), ou `None`."""
    if sys.platform != "darwin":
        return None
    achados = glob.glob("/Applications/Baselight/*/Baselight-*.app/Contents/bin/bl-conform")
    return os.path.dirname(max(achados, key=_versao)) if achados else None


#: o processo da INTERFACE (o nome do .app traz a versão) — o mesmo critério de `cicloassist/baselight.py` (etapa 1)
_INTERFACE = r"Baselight-[0-9.]+\.app/Contents/MacOS/Baselight$"


def interface_aberta() -> dict:
    """`{versao}` se a interface do Baselight está aberta nesta máquina, senão `{}` (os serviços não contam)."""
    if sys.platform != "darwin":
        return {}
    try:
        r = subprocess.run(["pgrep", "-fl", _INTERFACE], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return {}
    linha = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    m = re.search(r"Baselight-([0-9]+\.[0-9]+\.[0-9]+)", linha)
    return {"versao": m.group(1)} if m else {}


def python_flapi() -> str | None:
    achados = sorted(glob.glob(PY_FL_MAC))
    return achados[-1] if achados else None


def disponivel() -> tuple[bool, str]:
    if sys.platform == "win32":
        return False, "o Baselight não roda no Windows: o conform no Baselight é feito no Mac"
    if not bin_dir():
        return False, "o Baselight não está instalado nesta máquina (/Applications/Baselight)"
    return True, ""


def _bl(ferramenta: str, *args: str, entrada: str | None = None, prazo: float = 300) -> subprocess.CompletedProcess:
    b = bin_dir()
    if not b:
        raise BaselightIndisponivel(disponivel()[1])
    return subprocess.run([os.path.join(b, ferramenta), *args], input=entrada, capture_output=True, text=True,
                          timeout=prazo)


def limpar_nome(nome: str) -> str:
    """Um nome que o Baselight aceita como job ou scene (o `:` separaria host:job:scene)."""
    n = _PROIBIDO.sub(" ", nome or "").strip()
    return re.sub(r"\s+", " ", n)[:100] or "Ciclo Assist"


def jobs() -> list[str]:
    r = _bl("bl-lsjobs", HOST, prazo=60)
    return sorted(linha.split(":", 1)[1] for linha in r.stdout.splitlines() if linha.startswith(HOST + ":"))


def scenes(job: str) -> list[str]:
    r = _bl("bl-lsscenes", f"{HOST}:{job}", prazo=60)
    pre = f"{HOST}:{job}:"
    return [linha[len(pre):] for linha in r.stdout.splitlines() if linha.startswith(pre)]


#: o job de sistema do Baselight (as galerias): as scenes dele ficam com lock de escrita o tempo todo e não são o trabalho
GALERIA = "baselight_gallery"


def ler_locks(texto: str, job: str) -> dict[str, str]:
    """{scene: "Read"|"Write"} das linhas do `bl-lsscenes -k -q host:job` (sem lock = "-")."""
    pre = f"{HOST}:{job}:"
    out = {}
    for linha in texto.splitlines():
        if not linha.startswith(pre):
            continue
        nome_e_lock = linha[len(pre):].rstrip()
        partes = nome_e_lock.rsplit(None, 1)
        if len(partes) == 2 and partes[1] in ("Read", "Write"):
            out[partes[0].strip()] = partes[1]
    return out


def job_aberto() -> dict | None:
    """O job em que o colorista está trabalhando: o que tem uma scene ABERTA na interface — `{job, scene, lock}` — ou
    `None` (nenhuma scene aberta). MEDIDO (7.0.3, Mac, 2026-11-22): a scene aberta na interface, mesmo só para leitura,
    aparece com lock no `bl-lsscenes -k` ("Read" ou "Write") e o perde ao fechar (⌘W). ⛔ A FLAPI de fora NÃO diz:
    `Application.get()` é a do serviço (`flapid`) e responde "nenhuma scene aberta" com uma aberta na interface; e o lock
    da galeria com o nome do job fica preso ao último job aberto, mesmo trocando no Job Manager.
    ⭐ Com VÁRIAS scenes abertas (a interface guarda as abertas antes; medido 22/11: uma "Read" de uma hora antes e a do
    colorista "Write"), vale a de ESCRITA — é nela que o colorista trabalha; só leitura, só se não houver outra."""
    leitura = None
    for job in jobs():
        if job == GALERIA:
            continue
        r = _bl("bl-lsscenes", "-k", "-q", f"{HOST}:{job}", prazo=60)
        for scene, lock in ler_locks(r.stdout, job).items():
            if lock == "Write":
                return {"job": job, "scene": scene, "lock": lock}
            leitura = leitura or {"job": job, "scene": scene, "lock": lock}
    return leitura


def garantir_job(job: str) -> bool:
    """Cria o job se ele não existe. Devolve se criou."""
    if job in jobs():
        return False
    r = _bl("bl-mkjob", f"{HOST}:{job}", prazo=60)
    if job not in jobs():
        raise RuntimeError(f"o Baselight não criou o job “{job}”: {(r.stdout + r.stderr).strip()[-300:]}")
    return True


def nome_livre(base: str, existentes: list[str]) -> str:
    """`base`, ou `base · import 02`, `… · import 03`… — o primeiro que não existe no job (nunca sobrescreve)."""
    base = limpar_nome(base)
    tem = set(existentes)
    if base not in tem:
        return base
    n = 2
    while base + SUFIXO_IMPORT.format(n) in tem:
        n += 1
    return base + SUFIXO_IMPORT.format(n)


def _fps(fps: float) -> str:
    return f"{fps:.3f}".rstrip("0").rstrip(".") if abs(fps - round(fps)) > 0.01 else str(round(fps))


def conformar(xml: str, job: str, scene: str, fps: float, pastas: list[str]) -> str:
    """`bl-conform` do xmeml numa scene NOVA (`scene` não pode existir: sem `--delscene`, o Baselight poria as faixas
    novas por baixo das de uma scene existente). As mesmas opções do caminho C do BL08: espaço de VÍDEO (a montagem, não
    o log da câmera: memória do autor), `--multiples` e o filtro pelo nome do arquivo."""
    if scene in scenes(job):
        raise RuntimeError(f"a scene “{scene}” já existe no job “{job}”: o Ciclo não sobrescreve")
    args = ["--edlname", xml, "--destscene", f"{HOST}:{job}:{scene}", "--fps", _fps(fps), "--space", "Video_Full",
            "--multiples", "--Filter", "Filename",
            # ⛔ MEDIDO (BL09 V2B, 7.0.3, 2026-11-22): sem isto o bl-conform escolhe o 1º passo que dá 100 % — numa timeline
            # CURTA (todo arquivo mais longo que ela) o passo por tempo de GRAVAÇÃO casa também, e cada plano entra com a
            # fonte = a posição na timeline (in 0, 48, 96…), 5 de 5 fora do ponto. O xmeml da montagem é tempo de FONTE.
            "--TimeType", "Source"]
    for p in pastas:
        args += ["--src", f"dir={p}"]
    r = _bl("bl-conform", *args, prazo=1800)
    log = (r.stdout + r.stderr).strip()
    if scene not in scenes(job):
        raise RuntimeError("o Baselight não conformou: " + (log.splitlines()[-1] if log else f"código {r.returncode}"))
    return log


def ler(job: str, scene: str) -> list[dict]:
    r = _bl("bl-shots", f"{HOST}:{job}:{scene}", "-inputrange", "-outputrange", prazo=300)
    return C.ler_bl_shots(r.stdout)


def trocar(job: str, scene: str, linhas: list[str]) -> str:
    r = _bl("bl-shots", f"{HOST}:{job}:{scene}", "-replace", "-undomessage", "Ciclo Assist: casamento",
            entrada="\n".join(linhas) + "\n", prazo=600)
    return (r.stdout + r.stderr).strip()


def marcar(job: str, scene: str, marcas: list[tuple[int, str]]) -> dict:
    """Os markers "[Ciclo] …" na scene (troca os nossos, deixa os do colorista) — pela FLAPI, no python da FilmLight."""
    py = python_flapi()
    if not py:
        raise BaselightIndisponivel("o python da FilmLight (com a flapi) não está instalado")
    r = subprocess.run([py, MARCAR, f"{HOST}:{job}:{scene}"], input=json.dumps(marcas, ensure_ascii=False),
                       capture_output=True, text=True, timeout=300)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError("os markers não entraram: " + (r.stderr or r.stdout).strip()[-300:]) from None


def estabilizar(job: str, scene: str, planos: list[dict], fps: float) -> dict:
    """O Stabilize do MC nos planos da scene (`estabilizar_flapi.py`, no python da FilmLight). Devolve
    {feitos, ja_tinha, falhas} — cada um com {quadro, clip[, motivo]}."""
    py = python_flapi()
    if not py:
        raise BaselightIndisponivel("o python da FilmLight (com a flapi) não está instalado")
    r = subprocess.run([py, ESTAB, f"{HOST}:{job}:{scene}"], input=json.dumps({"fps": fps, "planos": planos}),
                       capture_output=True, text=True, timeout=600)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError("a estabilização não entrou: " + (r.stderr or r.stdout).strip()[-300:]) from None


def aplicar_efeitos(job: str, scene: str, planos: list[dict], fps: float, pasta: str | None = None) -> dict:
    """A velocidade e o Motion do Premiere nos planos da scene (`efeitos_flapi.py`, no python da FilmLight). Devolve
    {feitos, falhas, sem_par, formato, textos} — cada um com {quadro, clip[, motivo]}; `textos` = {ShotId: o BLG gravado}
    (em `pasta`, quando dada)."""
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    py = python_flapi()
    if not py:
        raise BaselightIndisponivel("o python da FilmLight (com a flapi) não está instalado")
    r = subprocess.run([py, EFEITOS, f"{HOST}:{job}:{scene}"],
                       input=json.dumps({"fps": fps, "planos": planos, "pasta": pasta}),
                       capture_output=True, text=True, timeout=1200)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError("os efeitos não entraram: " + (r.stderr or r.stdout).strip()[-300:]) from None


def aplicar_mascaras(job: str, scene: str, plano: dict, planos_ef: list[dict], fps: float, pasta: str) -> dict:
    """As máscaras de opacidade do Premiere (`mascaras.py`): lista os planos da scene, exporta a scene (`bl-export`: o
    `GR_SequenceRop` de cada fundo), monta a composição de cada pedaço mascarado e a grava num processo curto por plano.
    Devolve {feitos, falhas, pulados}. ⛔ Um plano que passa do prazo PARA a etapa (a scene pode ficar "Write Locked"
    com o cliente morto) e o resto sai como falha, com o motivo."""
    from . import efeitos as EF
    from . import mascaras as M

    py = python_flapi()
    if not py:
        raise BaselightIndisponivel("o python da FilmLight (com a flapi) não está instalado")
    cena = f"{HOST}:{job}:{scene}"
    r = subprocess.run([py, MASCARAS, "listar", cena], capture_output=True, text=True, timeout=300)
    try:
        lst = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError("as máscaras não entraram (a lista dos planos): " + (r.stderr or r.stdout).strip()[-300:]) from None
    os.makedirs(pasta, exist_ok=True)
    db = os.path.join(pasta, "scene.blscene")
    if os.path.exists(db):
        os.remove(db)
    _bl("bl-export", cena, db, prazo=600)
    if not os.path.isfile(db):
        raise RuntimeError("as máscaras não entraram: o bl-export não exportou a scene")
    objs = M.objetos_finais(db)
    w, h = lst["formato"]["w"], lst["formato"]["h"]
    ctx = {"molde": M.molde(), "molde_t": open(EF.MOLDE_TRANSFORM, encoding="latin1").read(), "w": w, "h": h, "fps": fps}
    molde_r = open(EF.MOLDE_RETIME, encoding="latin1").read()
    out: dict = {"feitos": [], "falhas": [], "pulados": []}
    parado = None
    for pd in M.pedacos(plano, lst["shots"], planos_ef):
        s, seg, ef = pd["shot"], pd["seg"], pd["ef"]
        onde = {"quadro": s["a"], "clip": s["clip"]}
        if parado:
            out["falhas"].append({**onde, "motivo": parado})
            continue
        try:
            frente = EF.blg(ef, s["a"] - ef["inicio"], s["b"] - s["a"], fps, w, h, molde_r, ctx["molde_t"])
            texto, info = M.composicao(seg, s["a"], s["b"], plano["vid"], objs, frente, ctx)
        except Exception as e:                           # noqa: BLE001 — um plano não derruba os outros
            out["falhas"].append({**onde, "motivo": f"{type(e).__name__}: {e}"[:200]})
            continue
        if texto is None:
            out["pulados"].append({**onde, **info})
            continue
        from . import camadas as CA
        texto = CA.marcar(texto)                         # as faixas com o NOME do Ciclo (o atualizar corte as separa)
        arq = os.path.join(pasta, f"plano_{s['n']:03d}.blg.txt")
        with open(arq, "w", encoding="latin1") as fh:
            fh.write(texto)
        try:
            g = subprocess.run([py, MASCARAS, "gravar1", cena, str(s["n"]), str(s["shot_id"]), arq],
                               capture_output=True, text=True, timeout=PRAZO_MASCARA)
        except subprocess.TimeoutExpired:
            parado = f"o plano do quadro {s['a']} passou de {PRAZO_MASCARA} s no Baselight — a etapa parou ali"
            out["falhas"].append({**onde, "motivo": parado})
            continue
        if g.returncode != 0:
            out["falhas"].append({**onde, "motivo": (g.stderr or g.stdout).strip()[-200:]})
        else:
            out["feitos"].append({**onde, **info})
            out.setdefault("textos", {})[str(s["shot_id"])] = arq
    return out


def trazer_titulos(job: str, provisoria: str, final: str, tits: list[dict], prs: list[list[int]], fps: float,
                   pasta: str) -> dict:
    """A OPÇÃO de trazer os títulos (`titulos.py`): as faixas na provisória → `bl-export` → a camada Text em cada uma,
    a scene renomeada → `bl-import` como `final` → a provisória APAGADA (autor, 2026-11-23). Devolve {titulos, pretos}."""
    from . import titulos as TT

    py = python_flapi()
    if not py:
        raise BaselightIndisponivel("o python da FilmLight (com a flapi) não está instalado")
    cena = f"{HOST}:{job}:{provisoria}"
    r = subprocess.run([py, TITULOS, cena], input=json.dumps({"duracoes": [t["b"] - t["a"] for t in tits],
                                                              "pretos": [b - a for a, b in prs]}),
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError("as faixas dos títulos não entraram: " + (r.stderr or r.stdout).strip()[-300:])
    os.makedirs(pasta, exist_ok=True)
    db = os.path.join(pasta, "titulos.blscene")
    if os.path.exists(db):
        os.remove(db)
    _bl("bl-export", cena, db, prazo=600)
    if not os.path.isfile(db):
        raise RuntimeError("o bl-export não exportou a scene dos títulos")
    w, h = _formato(cena, py)
    feito = TT.montar(db, final, tits, prs, fps, w, h)
    imp = _bl("bl-import", f"{HOST}:{job}", db, prazo=900)
    if final not in scenes(job):
        raise RuntimeError("o bl-import não criou a scene com os títulos: " + (imp.stderr or imp.stdout).strip()[-300:])
    _bl("bl-delete", cena, prazo=300)
    return {**feito, "provisoria_apagada": provisoria not in scenes(job)}


def _formato(cena: str, py: str) -> tuple[int, int]:
    r = subprocess.run([py, MASCARAS, "listar", cena], capture_output=True, text=True, timeout=300)
    f = json.loads(r.stdout.strip().splitlines()[-1])["formato"]
    return int(f["w"]), int(f["h"])


def marcas_dos_efeitos(ef: dict) -> list[tuple[int, str]]:
    """Só o que NÃO entrou vira marker (o traduzido está nas camadas Retime/Transform do plano, à vista do colorista)."""
    return ([(x["quadro"], f"velocidade/Motion da montagem NÃO aplicados: {x['motivo']}") for x in ef.get("falhas", [])]
            + [(x["quadro"], "velocidade/Motion da montagem NÃO aplicados: o plano não foi achado na scene")
               for x in ef.get("sem_par", [])])


def marcas_da_estabilizacao(est: dict, fora: list[dict]) -> list[tuple[int, str]]:
    """Os markers: o traduzido (o porquê do Motion 0), o que falhou e o que não se traduz (refazer no Baselight)."""
    m = [(x["quadro"], MARCA_ESTAB) for x in est.get("feitos", [])]
    m += [(x["quadro"], "estabilização do MC NÃO aplicada: " + x["motivo"]) for x in est.get("falhas", [])]
    m += [(x["quadro"], "o plano já tinha tracker (o do colorista): a estabilização do MC não foi reescrita")
          for x in est.get("ja_tinha", [])]
    m += [(x["inicio"], "estabilizado no Avid de um jeito que não se traduz (velocidade, Region Stabilize, vários "
                        "pontos): refazer no Baselight") for x in fora]
    return m


def _juntar(marcas: list[tuple[int, str]], novas: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Um marker por quadro: a nota nova entra depois da que já está lá."""
    por = dict(marcas)
    ordem = [q for q, _ in marcas]
    for q, n in novas:
        if q in por:
            por[q] = por[q] + " · " + n
        else:
            por[q] = n
            ordem.append(q)
    return [(q, por[q]) for q in ordem]


def _cor_flapi(pedido: dict, prazo: float = 900) -> dict:
    py = python_flapi()
    if not py:
        raise BaselightIndisponivel("o python da FilmLight (com a flapi) não está instalado")
    r = subprocess.run([py, COR], input=json.dumps(pedido, ensure_ascii=False), capture_output=True, text=True,
                       timeout=prazo)
    try:
        saida = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError("a cor da scene do colorista não veio: " + (r.stderr or r.stdout).strip()[-400:]) from None
    if saida.get("erro") == "nao_salva":
        raise ColoristaNaoSalvou(pedido["colorista"].split(":")[-1])
    if saida.get("erro"):
        raise RuntimeError("o Baselight não abriu a scene do colorista: " + str(saida.get("detalhe") or "")[-300:])
    return saida


def exportar_scene(job: str, scene: str, pasta: str) -> str | None:
    """A scene exportada (`bl-export`, só leitura) — de onde vêm as camadas do colorista em cada plano, inclusive o
    mascarado (multi-input não se lê pela FLAPI) e o da trilha de baixo (`camadas.do_blscene`). None se não exportou
    (a leitura cai no BLG de cada plano, como antes)."""
    os.makedirs(pasta, exist_ok=True)
    db = os.path.join(pasta, "scene.blscene")
    if os.path.exists(db):
        os.remove(db)
    try:
        _bl("bl-export", f"{HOST}:{job}:{scene}", db, prazo=600)
    except Exception:                                   # noqa: BLE001 — sem o export a leitura segue pelo BLG
        return None
    return db if os.path.isfile(db) else None


def conferir_pela_scene(job: str, scene: str, cor: dict, fps: float, pasta: str) -> int:
    """A conferência dos planos que a FLAPI não relê (o mascarado — multi-input — e o da trilha de baixo): a scene nova
    exportada (`bl-export`), as camadas do colorista de cada um (`camadas.do_blscene`) × as esperadas. Atualiza o
    `conferido` e as contas de `cor`; devolve quantos conferiu assim."""
    from . import camadas as CA

    falta = [p for p in cor.get("planos", []) if p.get("conferido") != "sim"]
    db = exportar_scene(job, scene, os.path.join(pasta, "nova")) if falta else None
    if not db:
        for p in falta:
            if p.get("nota_leitura"):
                p["aviso"] = (p["aviso"] + " — " if p.get("aviso") else "") + p["nota_leitura"]
        return 0
    cols = CA.do_blscene(db, [{"rec": [p["inicio"], p["fim"]], "arquivo": p["arquivo"]} for p in falta], fps)
    feitos = 0
    for p, col in zip(falta, cols):
        if col is not None and CA.impressao(col) == p.get("cor_esperada", ""):
            p["conferido"] = "sim (pela scene exportada)"
            feitos += 1
        elif col is not None:
            p["conferido"] = "não (pela scene exportada)"
    for p in cor["planos"]:                              # a nota de leitura só fica no plano que NÃO se confirmou
        if p.get("nota_leitura") and not str(p.get("conferido", "")).startswith("sim"):
            p["aviso"] = (p["aviso"] + " — " if p.get("aviso") else "") + p["nota_leitura"]
    cor["conferidos"] = sum(1 for p in cor["planos"] if str(p.get("conferido", "")).startswith("sim"))
    cor["nao_relidos"] = sum(1 for p in cor["planos"] if not str(p.get("conferido", "")).startswith(("sim", "não")))
    return feitos


def ler_colorista(job: str, scene: str, blscene: str | None = None) -> list[dict]:
    """Os planos da scene do colorista (arquivo, fonte, gravação, a impressão da cor) — para os cortes dele."""
    return _cor_flapi({"colorista": f"{HOST}:{job}:{scene}", "so_ler": True, "blscene": blscene}, prazo=300)["v1"]


def levar_a_cor(job: str, nova: str, colorista: str, blscene: str | None = None,
                ciclo: dict[str, str] | None = None) -> dict:
    """Multi-Paste + a conferência do Ciclo + os markers do colorista (`cor_flapi.py`; decisões do autor, 2026-11-22).
    `ciclo` = {ShotId da nova: o BLG que o Ciclo gravou nele} (efeitos, máscaras): a base de cada plano, sobre a qual
    vão SÓ as camadas do colorista (`camadas.py`)."""
    return _cor_flapi({"nova": f"{HOST}:{job}:{nova}", "colorista": f"{HOST}:{job}:{colorista}",
                       "blscene": blscene, "ciclo": ciclo or {}})


def _contar(res: list[dict]) -> dict:
    cont: dict[str, int] = {}
    for x in res:
        cont[x["estado"]] = cont.get(x["estado"], 0) + 1
    return cont


def conferir_e_corrigir(job: str, scene: str, esperados: list[dict]) -> dict:
    """A conferência depois do conform; o que o Baselight trocou volta ao decidido (`bl-shots -replace`, só a faixa do
    plano) e a conferência roda de novo. Devolve `{resultados, trocados, log_troca}`."""
    res = C.conferir(ler(job, scene), esperados)
    trocas = C.linhas_de_troca(res)
    log = ""
    if trocas:
        log = trocar(job, scene, trocas)
        res = C.conferir(ler(job, scene), esperados)
    return {"resultados": res, "trocados": len(trocas), "log_troca": log}


def enviar(xml_reescrito: str, job: str, base_scene: str, fps: float, pastas: list[str], markers: bool = True,
           andamento=None, atualizar: str | None = None, notas: list[tuple[int, str]] | None = None,
           estabilizar_planos: list[dict] | None = None, estabilizacao_fora: list[dict] | None = None,
           efeitos_planos: list[dict] | None = None, mascaras_plano: dict | None = None,
           pasta_trabalho: str | None = None, titulos: list[dict] | None = None,
           pretos_dos_titulos: list[list[int]] | None = None) -> dict:
    """A cadeia inteira, do xmeml JÁ reescrito (`entrega.reescrever`) ao resumo do painel.

    `atualizar`: a scene do COLORISTA (no mesmo job) cuja cor vai para a scene nova — o "atualizar corte" (etapa 5;
    `atualizar.py`): os planos que ele dividiu são divididos na v2 no mesmo quadro de fonte ANTES do conform; depois da
    conferência, o Multi-Paste + a conferência da cor + os markers dele pela fonte.

    `estabilizar_planos` (`do_aaf.estabilizados`): o Stabilize do MC vira o tracker nativo DEPOIS da cor (o plano que o
    Multi-Paste trouxe com tracker é do colorista e não se reescreve); `estabilizacao_fora`: os que não se traduzem —
    os dois viram marker.

    `efeitos_planos` (`efeitos.planejar`, já gravados no xmeml por `efeitos.no_xmeml`): a velocidade e o Motion do
    Premiere, ANTES da cor (o BLG deles parte do molde e apaga as camadas do plano)."""
    from . import atualizar as A

    ok, porque = disponivel()
    if not ok:
        raise BaselightIndisponivel(porque)
    avisar = andamento or (lambda *_a, **_k: None)
    job = limpar_nome(job)
    avisar("job", f"o job da produção no Baselight: {job}")
    criado = garantir_job(job)
    divididos: list[dict] = []
    blscene_colorista = None
    if atualizar:
        if atualizar not in scenes(job):
            raise RuntimeError(f"a scene do colorista “{atualizar}” não está no job “{job}”")
        avisar("colorista", f"lendo a scene do colorista: {atualizar}")
        import tempfile
        trabalho = os.path.join(pasta_trabalho or tempfile.gettempdir(), "atualizar-" + re.sub(r"\W", "_", atualizar))
        blscene_colorista = exportar_scene(job, atualizar, trabalho)
        cortes = A.cortes_do_colorista(ler_colorista(job, atualizar, blscene_colorista))
        if cortes:
            dividido = os.path.splitext(xml_reescrito)[0] + ".dividido.xml"
            divididos = A.dividir_xmeml(xml_reescrito, dividido, cortes)
            if divididos:
                avisar("colorista", f"{len(divididos)} plano(s) cortado(s) onde o colorista dividiu")
                xml_reescrito = dividido
    scene = nome_livre(base_scene, scenes(job))
    final = scene
    if titulos:                    # com os títulos o bl-import cria a scene da entrega; o conform vai numa provisória
        scene = nome_livre(scene + SUFIXO_PROVISORIA, scenes(job))
    esperados = E.esperado(xml_reescrito)
    avisar("conform", f"conformando {len(esperados)} planos na scene “{scene}” (bl-conform)")
    log = conformar(xml_reescrito, job, scene, fps, pastas)
    avisar("conferencia", "conferindo cada plano: o arquivo, o 1º e o último quadro visível")
    c = conferir_e_corrigir(job, scene, esperados)
    res = c["resultados"]
    problemas = [x for x in res if x["estado"] != "ok"]
    marcas = [(x["inicio"], C.motivo(x)) for x in problemas]
    # as notas de quem montou o xmeml (o trecho do original: o render da cor voltando) — no plano que não tem outra
    marcas = _juntar(marcas, list(notas or []))         # no mesmo quadro, juntas (o título não some por outro marker)
    ef = None
    if efeitos_planos:
        avisar("efeitos", f"levando a velocidade e o Motion da montagem a {len(efeitos_planos)} plano(s)")
        import tempfile
        ef = aplicar_efeitos(job, scene, efeitos_planos, fps,
                             os.path.join(pasta_trabalho or tempfile.gettempdir(), "efeitos-" + re.sub(r"\W", "_", scene)))
        ja = {q for q, _ in marcas}
        marcas += [(q, n) for q, n in marcas_dos_efeitos(ef) if q not in ja]
    mk = None
    if mascaras_plano and mascaras_plano.get("mascarados"):
        avisar("mascaras", f"montando as máscaras de opacidade de {len(mascaras_plano['mascarados'])} plano(s)")
        import tempfile
        mk = aplicar_mascaras(job, scene, mascaras_plano, efeitos_planos or [], fps,
                              os.path.join(pasta_trabalho or tempfile.gettempdir(), "mascaras-" + re.sub(r"\W", "_", scene)))
        ja = {q for q, _ in marcas}
        marcas += [(x["quadro"], f"máscara da montagem NÃO aplicada: {x['motivo']}") for x in mk["falhas"]
                   if x["quadro"] not in ja]
        marcas += [(x["quadro"], f"máscara da montagem: {x['aviso']}") for x in mk["feitos"]
                   if x.get("aviso") and x["quadro"] not in ja]
    cor = None
    if atualizar:
        avisar("cor", f"levando a cor da scene “{atualizar}” (Multi-Paste) e conferindo plano a plano")
        ciclo = {**(ef or {}).get("textos", {}), **(mk or {}).get("textos", {})}     # a máscara vence (é a pilha final)
        cor = levar_a_cor(job, scene, atualizar, blscene_colorista, ciclo)
        cor["pela_scene"] = conferir_pela_scene(job, scene, cor, fps, trabalho)
        ja = {q for q, _ in marcas}
        for p in cor["planos"]:
            if p["inicio"] in ja:
                continue
            if p["estado"] in ("sem cor", "limpa"):
                marcas.append((p["inicio"], f"sem cor da scene do colorista: {p['motivo']}"
                                            + (f" — {p['aviso']}" if p["aviso"] else "")))
            elif p["estado"] == "só o look":
                marcas.append((p["inicio"], f"só o look da cena (a faixa sobre vários planos): {p['motivo']} — a cor "
                                            "do plano é do colorista"))
            elif p["aviso"]:
                marcas.append((p["inicio"], p["aviso"]))
    est = None
    if estabilizar_planos:
        avisar("estabilizacao", f"traduzindo a estabilização do MC em {len(estabilizar_planos)} plano(s) (tracker nativo)")
        est = estabilizar(job, scene, estabilizar_planos, fps)
    if est or estabilizacao_fora:
        marcas = _juntar(marcas, marcas_da_estabilizacao(est or {}, estabilizacao_fora or []))
    marcados = None
    if markers and marcas:
        avisar("markers", f"marcando {len(marcas)} plano(s) na scene")
        marcados = marcar(job, scene, marcas)
    tt = None
    if titulos:
        avisar("titulos", f"trazendo {len(titulos)} título(s) para a scene (camada Text)")
        import tempfile
        try:
            tt = trazer_titulos(job, scene, final, titulos, pretos_dos_titulos or [], fps,
                                os.path.join(pasta_trabalho or tempfile.gettempdir(), "titulos-" + re.sub(r"\W", "_", final)))
            scene = final
        except Exception as e:                           # noqa: BLE001 — a entrega fica, sem os títulos, e diz
            tt = {"erro": f"{type(e).__name__}: {e}"[:300]}
    return {"job": job, "job_criado": criado, "scene": scene, "planos": len(res), "contagem": _contar(res),
            **({"titulos": tt} if tt else {}),
            "trocados": c["trocados"], "markers": (marcados or {}).get("markers", 0),
            "problemas": [{"quadro": x["inicio"], "estado": x["estado"], "motivo": C.motivo(x),
                           "arquivo": os.path.basename(x.get("esperado") or "")} for x in problemas],
            "conform": (log.splitlines()[-1] if log else ""),
            "estabilizacao": {"traduzidos": len((est or {}).get("feitos", [])),
                              "falhas": (est or {}).get("falhas", []), "do_colorista": len((est or {}).get("ja_tinha", [])),
                              "nao_traduzidos": len(estabilizacao_fora or [])},
            "efeitos": {"traduzidos": len((ef or {}).get("feitos", [])), "falhas": (ef or {}).get("falhas", []),
                        "sem_par": (ef or {}).get("sem_par", []),
                        "velocidade": sum(1 for x in (ef or {}).get("feitos", []) if x.get("velocidade")),
                        "motion": sum(1 for x in (ef or {}).get("feitos", []) if x.get("motion"))},
            "mascaras": {"traduzidas": len((mk or {}).get("feitos", [])), "falhas": (mk or {}).get("falhas", []),
                         "puladas": (mk or {}).get("pulados", [])},
            **({"atualizar": {"colorista": atualizar, "divididos": divididos, **cor}} if atualizar else {})}


def _sondar(caminho: str) -> dict:
    from prproj.originais import sondar

    try:
        return sondar(caminho) or {}
    except OSError:
        return {}


def decisao_como_esta(xml: str) -> dict[str, dict | None]:
    """O "Importar timeline" da Carta Aberta (etapa 3; autor: "a Carta não é conform — as mídias apontadas na Carta são as
    da timeline que chega"): cada arquivo do xmeml descrito COMO É (a taxa, o TC e a duração dele — a Carta declara a da
    timeline), sem casar com original nenhum; o que não está nesta máquina vai offline de propósito."""
    from . import xmeml

    fps = xmeml.ler(xml)["fps"]
    return {c: (E.descrever(c, _sondar(E.como_o_disco_lista(c)), fps_sequencia=fps) if os.path.isfile(c) else None)
            for c in xmeml.arquivos(xml)}


def entregar_xmeml(xml: str, decisao: dict, job: str, base_scene: str, pastas: list[str], pasta_trabalho: str,
                   markers: bool = True, andamento=None, atualizar: str | None = None) -> dict:
    """Um xmeml pronto (o da Carta) → reescrito com `decisao` → `enviar`. Devolve o resumo de `enviar` + a conta."""
    import uuid

    from . import xmeml

    os.makedirs(pasta_trabalho, exist_ok=True)
    final = os.path.join(pasta_trabalho, f"{uuid.uuid4().hex}.baselight.xml")
    feitos = E.reescrever(xml, final, decisao, os.path.join(pasta_trabalho, "baselight-offline"))
    r = enviar(final, job, base_scene, xmeml.ler(xml)["fps"], pastas or sorted({os.path.dirname(c) for c in decisao}),
               markers=markers, andamento=andamento, atualizar=atualizar, notas=E.notas_dos_trechos(xml, decisao))
    r["offline_de_proposito"] = sum(1 for v in feitos.values() if v == "offline")
    r["xmeml"] = final
    return r
