"""O servidor do módulo Sincronizar (ex-Órbita) — a 7817, em Python, no lugar do `httpserver.rs`.

    python servidor.py [--porta 7817] [--pai <pid>]

Fase 1 do plano `docs/plano/2026-11-06-um-app-so.md` (§4a, a lista de rotas VIVAS; o resto não se porta). Mesmo
contrato do Rust (`DRAMASYNC/src-tauri/src/httpserver.rs`, `d57904e`), conferido rota a rota pelo diferencial
(`tests/diferencial_das_rotas.py`): os mesmos status, os mesmos campos, as mesmas mensagens.

O que muda por dentro:
- o motor é chamado NO MESMO PROCESSO (`motor.py`), sem o sidecar;
- várias threads (`ThreadingHTTPServer`) em vez de uma: a fila de um job por vez é explícita (`trabalhos.reservar`,
  checar e inserir sob a mesma trava) e o long-poll da ponte já não precisa sair do laço;
- o que era do Studio SAIU (`/sync`, `/prproj`, `/dailies`, `/splitresult`, `/open`, `/app/studio`): respondem 410
  com a frase, para quem ainda as chamar (o script do Resolve chama `/open`) saber o porquê em vez de um 404 mudo.

⛔ Rota é caminho EXATO, nunca prefixo (no Rust, `/healthFOO` caía em `/health`, e a ordem virava lógica).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fichas as fichas_de_midia  # noqa: E402
import motor  # noqa: E402
import paginas  # noqa: E402
import ponte  # noqa: E402
import portao  # noqa: E402
import segredo  # noqa: E402
import trabalhos as tb  # noqa: E402

PORTA = 7817
VERSAO = "0.4.0"
log = logging.getLogger("sincronizar")

LINK_DO_AUTOR = "https://www.linkedin.com/in/lohan-costa/"

#: O que era do Studio (aposentado com ele, decisão do autor de 2026-11-06).
#: ⭐ Fase 4 (2026-11-07): a extensão própria do Sincronizar no Premiere (`com.orbita.ponte`) saiu — há UMA ponte, a
#: do Ciclo Assist, que carrega o ExtendScript dos três módulos. As rotas que só ela usava respondem 410 (GET e POST).
PONTE_APOSENTADA = {r: "a ponte do Premiere agora é a do Ciclo Assist (uma extensão só); reinstale as integrações "
                       "pelo app (⚙ › Integrações)"
                    for r in ("/premiere/ponte", "/premiere/ponte.js", "/premiere/host.jsx", "/premiere/pedido",
                              "/premiere/resposta")}

APOSENTADAS = {
    "/sync": "a sincronização sem acompanhamento era do Órbita Studio, aposentado — use /syncmap",
    "/prproj": "o .prproj direto era do Órbita Studio, aposentado — use /syncmap e a montagem pelo painel",
    "/dailies": "o plano de diárias era do Órbita Studio, aposentado",
    "/splitresult": "a divisão do resultado era do Órbita Studio, aposentado",
    "/open": "o Órbita Studio foi aposentado: a conferência é na aba Preparar do Ciclo Assist",
    "/app/studio": "o Órbita Studio foi aposentado: a conferência é na aba Preparar do Ciclo Assist",
}


class Resposta:
    def __init__(self, status: int, corpo: bytes, tipo: str, cabecalhos: list[tuple[str, str]]):
        self.status, self.corpo, self.tipo, self.cabecalhos = status, corpo, tipo, cabecalhos


def _json_bytes(v: Any) -> bytes:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
                      default=str).encode("utf-8")


def json_sem_cors(status: int, corpo: Any) -> Resposta:
    """⛔ Para quem tem `Origin` de página web: o navegador não deixa a página ler o corpo (nem o motivo)."""
    return Resposta(status, _json_bytes(corpo), "application/json", [])


def json_resp(status: int, corpo: Any) -> Resposta:
    # ⛔ NÃO acrescente `x-sincronizar-token` ao Allow-Headers: é o que o navegador autoriza um SITE a mandar.
    return Resposta(status, _json_bytes(corpo), "application/json", [
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Headers", "Content-Type"),
        ("Access-Control-Allow-Methods", "POST, GET, OPTIONS"),
    ])


def pagina(corpo: str, tipo: str) -> Resposta:
    return Resposta(200, corpo.encode("utf-8"), tipo, [
        ("Cache-Control", "no-store"),
        ("X-Frame-Options", "DENY"),
        ("Content-Security-Policy", "frame-ancestors 'none'"),
    ])


def query_param(url: str, chave: str) -> Optional[str]:
    if "?" not in url:
        return None
    for par in url.split("?", 1)[1].split("&"):
        k, _, v = par.partition("=")
        if k == chave:
            return unquote_plus(v, errors="replace")
    return None


def media_composer_no_ar() -> bool:
    for host, fam in (("::1", socket.AF_INET6), ("127.0.0.1", socket.AF_INET)):
        try:
            with socket.socket(fam, socket.SOCK_STREAM) as s:
                s.settimeout(0.15)
                s.connect((host, 9100))
                return True
        except OSError:
            continue
    return False


# ── o pedido ────────────────────────────────────────────────────────────────────────────────────────────────────

class Pedido:
    def __init__(self, metodo: str, url: str, corpo: bytes):
        self.metodo, self.url, self._corpo = metodo, url, corpo
        self.rota = url.split("?", 1)[0]

    def texto(self) -> Optional[str]:
        """O `read_to_string` do Rust: corpo que não é UTF-8 é ilegível."""
        try:
            return self._corpo.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def json_ou_vazio(self) -> Any:
        """O `unwrap_or_else(|_| json!({}))` das rotas que toleram corpo ruim."""
        t = self.texto()
        try:
            return json.loads(t) if t is not None else None
        except ValueError:
            return {}

    def json_estrito(self, de_bytes: bool = False) -> tuple[Any, Optional[Resposta]]:
        """`de_bytes`: as rotas que no Rust liam por `ler_json_com_teto` (`from_slice`) — lá o corpo não-UTF-8 é
        "JSON inválido", não "corpo ilegível". Conferido no diferencial."""
        t = self.texto()
        if t is None:
            return None, json_resp(400, {"error": "JSON inválido: corpo não é UTF-8" if de_bytes
                                         else "corpo ilegível"})
        try:
            return json.loads(t), None
        except ValueError as e:
            return None, json_resp(400, {"error": f"JSON inválido: {e}"})


def _obj(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _texto(d: dict, k: str) -> str:
    v = d.get(k)
    return v if isinstance(v, str) else ""


def _lista(d: dict, k: str) -> Optional[list]:
    v = d.get(k)
    return v if isinstance(v, list) else None


def _ilegivel(p: Pedido) -> Optional[Resposta]:
    return json_resp(400, {"error": "corpo ilegível"}) if p.texto() is None else None


def ocupado() -> Optional[Resposta]:
    return json_resp(409, {"error": "ocupado", "busy": True}) if tb.em_curso() else None


def chamar_motor(comando: str, params: Any) -> Resposta:
    try:
        return json_resp(200, motor.chamar(comando, params))
    except motor.ErroDoMotor as e:
        return json_resp(500, {"error": str(e)})


def job_do_motor(comando: str, params: Any, stage: str) -> Resposta:
    """O `sidecar_job_start`: reserva, roda no fundo, devolve o id."""
    try:
        jid = tb.reservar(stage)
    except tb.Ocupado as o:
        return json_resp(409, {"error": "ocupado", "busy": True, "job_id": o.outro})
    tb.rodar_no_fundo(jid, lambda: motor.chamar(comando, params, tb.sink_na_faixa(jid, 0.0, 1.0)))
    return json_resp(200, {"job_id": jid})


# ── a montagem dos parâmetros (as funções puras do Rust, com os testes portados) ────────────────────────────────

def build_sync_params(entrada: Any) -> Optional[dict]:
    files = []
    for c in _lista(_obj(entrada), "clips") or []:
        if not isinstance(c, dict) or not isinstance(c.get("path"), str):
            continue
        path = c["path"]
        g = c.get("group")
        f: dict = {"path": path, "group_id": g if isinstance(g, str) else path}
        o = c.get("group_order")
        if isinstance(o, int) and not isinstance(o, bool):
            f["group_order"] = o
        if isinstance(c.get("kind"), str):
            f["kind"] = c["kind"]
        if isinstance(c.get("chronology"), str):
            f["chronology"] = c["chronology"]
        files.append(f)
    if not files:
        return None
    e = _obj(entrada)
    m = e.get("method")
    return {"files": files, "sync_method": m if isinstance(m, str) else "hybrid", "fps": e.get("fps")}


def montar_avid_params(entrada: Any) -> Optional[dict]:
    e = _obj(entrada)
    result = e.get("result")
    if not isinstance(result, dict):
        return None
    nome = e.get("name")
    nome = nome if isinstance(nome, str) and nome.strip() else "Sincronizar"
    projeto = json.loads(json.dumps(result))
    projeto["name"] = nome
    gs = projeto.get("groups")
    tc_dado = "start_tc_frames" in e
    if isinstance(gs, list):
        if len(gs) == 1 and isinstance(gs[0], dict):
            gs[0]["name"] = nome
            if tc_dado:
                gs[0]["start_tc_frames"] = e["start_tc_frames"]
        elif tc_dado:
            for g in gs:
                if isinstance(g, dict):
                    g["start_tc_frames"] = e["start_tc_frames"]
    elif tc_dado:
        projeto["start_tc_frames"] = e["start_tc_frames"]
    inc = e.get("include_camera_audio")
    params = {"result": projeto, "options": {"include_camera_audio": inc if isinstance(inc, bool) else False}}
    for chave in ("mob_ids", "mob_lengths"):
        if chave in e:
            params[chave] = e[chave]
    return params


def temp_prproj_path(nome: str) -> str:
    import tempfile
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in nome) or "sincronizar"
    return str(Path(tempfile.gettempdir()) / f"sincronizar_{safe}_{int(time.time() * 1000)}.prproj")


def pasta_do_merged(nome: str) -> str:
    import tempfile
    limpo = "".join(c if (c.isalnum() or c in " -_.") else "_" for c in nome).strip().strip(".") or "ORBITA"
    pasta = Path(tempfile.gettempdir()) / f"sincronizar_merged_{int(time.time() * 1000)}"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"não deu para criar {pasta}: {e}")
    return str(pasta / f"{limpo} MERGED.prproj")


def bins_da_pasta(arvore: list[str], pasta: str) -> list[str]:
    alvo = pasta.strip().replace("\\", "/").strip("/").lower()
    if not alvo:
        return []
    prefixo = alvo + "/"
    return [b for b in arvore if b.lower() == alvo or b.lower().startswith(prefixo)]


def nome_real_da_pasta(bins: list[str], pasta: str) -> str:
    n = len(pasta.replace("\\", "/").strip("/").split("/"))
    if bins:
        s = "/".join(bins[0].split("/")[:n])
        if s:
            return s
    return pasta.strip()


def clipes_das_fontes(fontes_: list) -> tuple[list[dict], list[str]]:
    clips: list[dict] = []
    rotulos: list[str] = []
    for f in fontes_:
        f = _obj(f)
        base = f["label"] if isinstance(f.get("label"), str) else "FONTE"
        rotulo, n = base, 2
        while rotulo in rotulos:
            rotulo, n = f"{base} {n}", n + 1
        som = f.get("kind") == "sound"
        for ordem, a in enumerate(_lista(f, "files") or []):
            if isinstance(a, str):
                c: dict = {"path": a, "group": rotulo, "group_order": ordem}
                if som:
                    c["kind"] = "sound"
                clips.append(c)
        rotulos.append(rotulo)
    return clips, rotulos


def resultado_do_sync(job_id: str) -> tuple[Any, Optional[Resposta]]:
    j = tb.obter(job_id)
    if j is None:
        return None, json_resp(410, {"error": "esse sync não está mais na memória do Sincronizar (o resultado é "
                                              "podado alguns minutos depois de pronto). Sincronize de novo."})
    if j.error is not None:
        return None, json_resp(409, {"error": j.error})
    if not j.done:
        return None, json_resp(409, {"error": "esse sync ainda está rodando"})
    return (j.result if j.result is not None else {}), None


def _nome_do_pedido(e: dict, resultado: Any) -> str:
    n = e.get("nome")
    if isinstance(n, str) and n.strip():
        return n.strip()
    r = _obj(resultado).get("name")
    return r if isinstance(r, str) else "ORBITA"


# ── a /api/v1 (a ponte com o Ciclo Assist) ──────────────────────────────────────────────────────────────────────

def api_info() -> Resposta:
    return json_resp(200, {
        "ok": True, "app": "sincronizar", "version": VERSAO, "busy": tb.em_curso() is not None,
        "paineis": {"premiere": tb.ouvindo("premiere"), "resolve": tb.ouvindo("resolve"),
                    "avid": tb.ouvindo("avid")},
        "nles": {"avid": media_composer_no_ar()},
        "capacidades": ["sincronizar", "montar", "merged", "avid_sincronizar"],
        "motor": "python",
    })


def api_enfileirar_montagem(entrada: Any) -> Resposta:
    e = _obj(entrada)
    job_id = _texto(e, "job_id").strip()
    if not job_id:
        return json_resp(400, {"error": "faltou job_id (o sync que gerou o mapa)"})
    alvo = tb.nle_de(e.get("nle"))
    if not tb.ouvindo(alvo):
        return json_resp(412, {
            "error": f"a ponte do Sincronizar não está respondendo no {alvo} — é ela que monta a sequência. "
                     f"Feche e abra o {alvo} (a ponte sobe com ele) e peça de novo.",
            "painel_ausente": alvo})
    resultado, erro = resultado_do_sync(job_id)
    if erro:
        return erro
    r = _obj(resultado)
    if isinstance(r.get("groups"), list):
        mapa = {"groups": json.loads(json.dumps(r["groups"]))}
    else:
        mapa = {"groups": [json.loads(json.dumps(resultado))]}
    nome = _nome_do_pedido(e, resultado)
    tc = e.get("start_tc_frames")
    for g in mapa["groups"]:
        if not isinstance(g, dict):
            continue
        if not (isinstance(g.get("name"), str) and g["name"]):
            g["name"] = nome
        if isinstance(tc, int) and not isinstance(tc, bool):
            g["start_tc_frames"] = tc
    if not mapa["groups"]:
        return json_resp(409, {"error": "esse sync não produziu diária nenhuma"})
    mid = f"ponte-{tb.proximo_numero()}"
    job: dict = {"id": mid, "name": nome, "map": mapa}
    if isinstance(e.get("labels"), dict):
        job["labels"] = e["labels"]
    tb.registrar_montagem(mid, alvo, nome)
    tb.enfileirar_nle([job], alvo)
    return json_resp(200, {"montagem_id": mid, "nome": nome, "nle": alvo})


def api_enfileirar_merged(entrada: Any, escrever: Callable[[dict], Any]) -> Resposta:
    e = _obj(entrada)
    job_id = _texto(e, "job_id").strip()
    if not job_id:
        return json_resp(400, {"error": "faltou job_id (o sync que gerou o mapa)"})
    if not tb.ouvindo("premiere"):
        return json_resp(412, {
            "error": "a ponte do Sincronizar não está respondendo no Premiere — é ela que importa os merged. "
                     "Feche e abra o Premiere (a ponte sobe com ele) e peça de novo.",
            "painel_ausente": "premiere"})
    resultado, erro = resultado_do_sync(job_id)
    if erro:
        return erro
    nome = _nome_do_pedido(e, resultado)
    try:
        arquivo = pasta_do_merged(nome)
    except RuntimeError as x:
        return json_resp(500, {"error": str(x)})
    params = {"result": resultado,
              "proxies": e["proxies"] if isinstance(e.get("proxies"), dict) else {},
              "raiz": "CENAS", "premiere_alvo": "2023" if e.get("premiere_alvo") == "2023" else "25",
              "output_path": arquivo}
    try:
        escrito = escrever(params)
    except motor.ErroDoMotor as x:
        return json_resp(500, {"error": str(x)})
    escrito = _obj(escrito)
    m = escrito.get("merged")
    if not (isinstance(m, int) and not isinstance(m, bool) and m > 0):
        return json_resp(422, {"error": "esse sync não tem tomada com som E câmera — não há o que fundir",
                               "escrito": escrito})
    caminho = escrito["arquivo"] if isinstance(escrito.get("arquivo"), str) else arquivo
    mid = f"ponte-{tb.proximo_numero()}"
    tb.registrar_montagem(mid, "premiere", nome)
    tb.enfileirar_nle([{"id": mid, "tipo": "merged", "name": nome, "arquivo": caminho}], "premiere")
    r = dict(escrito)
    r["montagem_id"], r["nome"] = mid, nome
    return json_resp(200, r)


def fontes_declaradas(v: Any) -> Optional[list[dict]]:
    """`[{tipo, nome, bins}]` validadas, ou `None` se algo não veio: quem chama é o chat, e o erro volta como frase."""
    if not isinstance(v, list) or not v:
        return None
    saida = []
    for f in v:
        f = _obj(f)
        bins = [b.replace("\\", "/") for b in (_lista(f, "bins") or []) if isinstance(b, str) and b.strip()]
        if f.get("tipo") not in ("camera", "som") or not bins:
            return None
        saida.append({"kind": "sound" if f["tipo"] == "som" else "camera", "label": _texto(f, "nome").strip(), "bins": bins})
    return saida


def fundir_selecoes(fontes_: list[dict], ler_bins: Callable[[list[str]], dict]) -> dict:
    """Lê as bins de cada fonte e as funde numa fonte só: o resultado tem a forma de uma leitura do `avid_selection`.

    ⭐ Duas bins da mesma câmera são UMA câmera; é o que a lista `bins` não sabe dizer (cada bin virava uma fonte)."""
    saida: dict = {"sources": [], "missing": [], "mob_ids": {}, "mob_lengths": {}}
    n_cam = n_som = 0
    for f in fontes_:
        sel = ler_bins(f["bins"])
        arquivos = [a for fonte in (_lista(sel, "sources") or []) for a in (_lista(_obj(fonte), "files") or [])]
        if f["kind"] == "sound":
            n_som += 1
            rotulo = f["label"] or ("SOM DIRETO" if n_som == 1 else f"SOM DIRETO {n_som}")
        else:
            n_cam += 1
            rotulo = f["label"] or "CAM " + chr(64 + n_cam)
        if arquivos:
            saida["sources"].append({"kind": f["kind"], "label": rotulo, "files": arquivos})
        saida["missing"] += _lista(sel, "missing") or []
        for chave in ("mob_ids", "mob_lengths"):
            saida[chave].update(_obj(sel.get(chave)))
        if isinstance(sel.get("name"), str) and not saida.get("name"):
            saida["name"] = sel["name"]
    return saida


def api_avid_sincronizar(entrada: Any) -> Resposta:
    if not media_composer_no_ar():
        return json_resp(412, {"error": "o Media Composer não está aberto (ou está sem projeto): a porta 9100 "
                                        "não respondeu", "nle_ausente": "avid"})
    e = _obj(entrada)
    pasta = _texto(e, "pasta").strip()
    bins_pedidas = [b.replace("\\", "/") for b in (_lista(e, "bins") or []) if isinstance(b, str)]
    fontes_pedidas = fontes_declaradas(e.get("fontes"))
    if e.get("fontes") and fontes_pedidas is None:
        return json_resp(400, {"error": "cada fonte precisa de `tipo` (camera ou som) e das `bins` dela"})
    if not pasta and not bins_pedidas and not fontes_pedidas:
        return json_resp(400, {"error": "diga as fontes (`fontes`), a pasta (`pasta`) ou as bins (`bins`) do Media Composer"})
    metodo = e["metodo"] if isinstance(e.get("metodo"), str) else "hybrid"
    nome = _texto(e, "nome").strip()
    try:
        jid = tb.reservar("lendo as bins do Media Composer…")
    except tb.Ocupado as o:
        return json_resp(409, {"error": "ocupado", "busy": True, "job_id": o.outro})

    def trabalho() -> dict:
        if fontes_pedidas:
            bins = [b for f in fontes_pedidas for b in f["bins"]]
            sel = fundir_selecoes(fontes_pedidas, lambda b: _obj(motor.chamar(
                "avid_selection", {"bins": b}, tb.sink_na_faixa(jid, 0.0, 0.2))))
        else:
            if bins_pedidas:
                bins = bins_pedidas
            else:
                arvore = _obj(motor.chamar("avid_bins", {}))
                todas = [b for b in (_lista(arvore, "bins") or []) if isinstance(b, str)]
                bins = bins_da_pasta(todas, pasta)
                if not bins:
                    raise RuntimeError(f'não há bin na pasta "{pasta}" do projeto aberto no Media Composer')
            sel = _obj(motor.chamar("avid_selection", {"bins": bins}, tb.sink_na_faixa(jid, 0.0, 0.2)))
        fontes_ = _lista(sel, "sources") or []
        if len(fontes_) < 2:
            raise RuntimeError(
                f'as bins de "{pasta if pasta else "o pedido"}" deram {len(fontes_)} fonte(s) com mídia — '
                "o sync precisa de pelo menos duas (câmera e som)")
        clips, _ = clipes_das_fontes(fontes_)
        params = build_sync_params({"clips": clips, "method": metodo})
        if params is None:
            raise RuntimeError("as bins não têm clipe com arquivo")
        mapa = motor.chamar("sync", params, tb.sink_na_faixa(jid, 0.2, 0.9))
        tb.etapa(jid, 0.9, "montando a bin no Media Composer…")
        if nome:
            nome_final = nome
        elif pasta:
            nome_final = f"{nome_real_da_pasta(bins, pasta)} SYNC"
        else:
            nome_final = sel["name"] if isinstance(sel.get("name"), str) else "ORBITA"
        pedido = {"result": mapa, "name": nome_final, "include_camera_audio": True}
        for chave in ("mob_ids", "mob_lengths"):
            if chave in sel:
                pedido[chave] = sel[chave]
        p = montar_avid_params(pedido)
        if p is None:
            raise RuntimeError("o sync não devolveu resultado")
        montagem = motor.chamar("export_avid", p)
        gs = _obj(mapa).get("groups")
        if isinstance(gs, list) and len(gs) == 1 and isinstance(gs[0], dict):
            gs[0]["name"] = nome_final

        def contar(f: dict) -> dict:
            arqs = _lista(f, "files") or []
            c = f.get("clipes")
            return {"label": f.get("label"), "kind": f.get("kind"),
                    "clipes": c if isinstance(c, int) and not isinstance(c, bool) and c >= 0 else len(arqs),
                    "arquivos": len(arqs)}
        return {"mapa": mapa, "fontes": [contar(_obj(f)) for f in fontes_], "bins": bins,
                "faltando": sel.get("missing", []), "montagem": montagem}

    tb.rodar_no_fundo(jid, trabalho)
    return json_resp(200, {"job_id": jid})


def sync_job(entrada: Any) -> Resposta:
    """`/syncmap`: o sync no fundo; o resultado é o mapa (o `JobKind::Map` — o `Prproj` era do Studio)."""
    # ⭐ O take de som monofônico: só o 1º canal entra no sync; os outros voltam ao mapa na posição dele (`fichas.py`).
    pedido = _obj(entrada)
    clips, irmaos = fichas_de_midia.separar_mono(pedido.get("clips") if isinstance(pedido.get("clips"), list) else [])
    params = build_sync_params({**pedido, "clips": clips} if irmaos else entrada)
    if params is None:
        return json_resp(400, {"error": "nenhum clipe"})
    try:
        jid = tb.reservar("iniciando…")
    except tb.Ocupado as o:
        return json_resp(409, {"error": "ocupado", "busy": True, "job_id": o.outro})
    tb.rodar_no_fundo(jid, lambda: fichas_de_midia.devolver_mono(
        motor.chamar("sync", params, tb.sink_na_faixa(jid, 0.0, 0.95)), irmaos))
    return json_resp(200, {"job_id": jid})


# ── abrir pasta e link no sistema ───────────────────────────────────────────────────────────────────────────────

def abrir_no_sistema(alvo: str) -> None:
    """O `opener` do Tauri: `open` no Mac, o shell no Windows. ⛔ Só chega aqui o que NÓS escolhemos (a pasta de
    cache ou de logs, o link do autor) — nunca um caminho do corpo do pedido."""
    if sys.platform == "win32":
        os.startfile(alvo)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", alvo], check=True, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["xdg-open", alvo], check=True)


def abrir_pasta(entrada: Any) -> Resposta:
    which = _obj(entrada).get("which")
    if which not in ("cache", "logs"):
        return json_resp(400, {"error": "pasta desconhecida"})
    b = ocupado()
    if b:
        return b
    try:
        d = _obj(motor.chamar("get_settings", {}))
    except motor.ErroDoMotor as e:
        return json_resp(500, {"error": str(e)})
    path = d.get("logs_dir") if which == "logs" else _obj(d.get("cache")).get("dir")
    if not (isinstance(path, str) and path):
        return json_resp(500, {"error": "caminho indisponível"})
    try:
        abrir_no_sistema(path)
    except (OSError, subprocess.CalledProcessError) as e:
        return json_resp(500, {"error": str(e)})
    return json_resp(200, {"ok": True, "path": path})


# ── o roteador ──────────────────────────────────────────────────────────────────────────────────────────────────

def _premiere_merged_ler(e: dict) -> Resposta:
    reg = e.get("registros")
    if not (isinstance(reg, str) and reg.strip()):
        return json_resp(400, {"error": "faltou a sequência"})
    fps = e.get("fps")
    so = e.get("so_selecionados")
    return chamar_motor("premiere_merged_read", {
        "registros": reg,
        "fps": float(fps) if isinstance(fps, (int, float)) and not isinstance(fps, bool) else 0.0,
        "colunas": e["colunas"] if isinstance(e.get("colunas"), dict) else {},
        "projeto": _texto(e, "projeto"),
        "so_selecionados": so if isinstance(so, bool) else False})


RENOMEAR_PREMIERE = {
    "/premiere/renomear/ler": ("premiere_rename_scan", ("projeto", "itens")),
    "/premiere/renomear/plano": ("premiere_rename_plan", ("levantamento_id", "padrao", "indices", "versao")),
    "/premiere/renomear/desfazer": ("premiere_rename_undo", ("projeto",)),
    "/premiere/renomear/fim": ("premiere_rename_done", ("undo_id", "aplicados", "falhas", "desfeito")),
}


def _exige(e: dict, campo: str, erro: str) -> Optional[str]:
    v = e.get(campo)
    return v if isinstance(v, str) and v else None


#: A espécie pela CATEGORIA da bin em que o mob está (a classificação da própria bin, não um palpite pelas colunas).
_ESPECIES_NA_BIN = (("sequence", ("sequences",)), ("subclip", ("subclips",)), ("group", ("groups",)),
                    ("masterclip", ("masterClips", "linkedMasterClips")))


def especies_do_arrasto(mob_ids: list) -> dict:
    """O arrasto do MC no MAC (`app/src-tauri/src/arrasto_mac.rs`) → os itens com a ESPÉCIE, na forma do payload do
    Windows (`text/x.avid.mc-api-asset-list+json`), para a página seguir pelo MESMO `aoSoltar`.

    No Mac o MC só entrega o XML com os MobIDs; os JSON com o `type` chegam como promessa sem dado (banco,
    avid-panel-sdk/arrastar.md, seção macOS). A espécie sai da API: a bin do mob (`GetBinFromMob`) e, nela, em que
    categoria ele está. Portado do De Lá Pra Cá (`/arrasto/mc`, 2026-10-25) em 2026-11-07. Sem a bin, `type` = "?" e a
    página recusa dizendo que não reconheceu.
    """
    motor.carregar(VERSAO)
    from avid.mcapi import MediaComposer, McApiError  # noqa: E402 — do motor, na raiz dele
    from main import mob_id_plausivel  # noqa: E402

    def hexa(m):
        return "".join(c for c in (m or "").lower() if c in "0123456789abcdef")

    ids = [str(m) for m in mob_ids if mob_id_plausivel(str(m))][:12]
    if not ids:
        return {"ok": False, "erro": "o arrasto do Media Composer não trouxe identidade"}
    itens = []
    try:
        with MediaComposer() as mc:
            if not mc.esta_vivo():
                return {"ok": False, "erro": "o Media Composer não respondeu"}
            for mid in ids:
                especie = "?"
                caminho = mc.bin_do_mob(mid)
                for nome, flags in _ESPECIES_NA_BIN if caminho else ():
                    try:
                        if any(hexa(i.mob_id) == hexa(mid) for i in mc.itens_de(caminho, flags=flags)):
                            especie = nome
                            break
                    except McApiError as e:  # a bin que não responde deixa a espécie em "?"
                        log.debug("bin %r não respondeu (%s): %s", caminho, flags, e)
                        break
                itens.append({"head": "0", "id": mid, "systemID": "mc-api", "systemType": "mediacomposer",
                              "type": especie})
    except McApiError as e:
        return {"ok": False, "erro": str(e)}
    return {"ok": True, "itens": itens}


def rotear(p: Pedido) -> Resposta:  # noqa: C901 — é a tabela de rotas
    m, r = p.metodo, p.rota
    get, post = m == "GET", m == "POST"

    # ── a ponte do Premiere (desde a fase 4, pelo núcleo do Ciclo Assist: `ponte.py`) ──
    if r in PONTE_APOSENTADA:
        return json_resp(410, {"error": PONTE_APOSENTADA[r], "aposentada": True})
    if post and r == "/premiere/chamar":
        v, erro = p.json_estrito(de_bytes=True)
        if erro:
            return erro
        if not ponte.viva():
            return json_resp(409, {"error": "O Premiere não está conectado ao Sincronizar. Ele está aberto? "
                                            "A integração precisa estar instalada e o Premiere aberto depois dela."})
        v = _obj(v)
        try:
            return json_resp(200, {"id": ponte.enfileirar(_texto(v, "funcao"), _lista(v, "args") or [])})
        except ValueError as e:
            return json_resp(400, {"error": str(e)})
    if get and r == "/premiere/resultado":
        q = query_param(p.url, "id")
        res = ponte.resultado(int(q)) if q is not None and q.isdigit() else None
        if res is None:
            return json_resp(404, {"error": "pedido desconhecido (vencido?)"})
        if not res[0]:
            return json_resp(200, {"pronto": False, "viva": ponte.viva()})
        return json_resp(200, {"pronto": True, "r": res[1]})
    if get and r == "/conexao":
        premiere, mc = ponte.viva(), media_composer_no_ar()
        return json_resp(200, {"programa": "premiere" if premiere else ("mc" if mc else None),
                               "premiere": premiere, "mc": mc})
    if post and r == "/app/instalar-premiere":
        # ⭐ Fase 4 (2026-11-07): a ponte do Premiere é a ÚNICA, do Ciclo Assist (`cicloassist/integracoes.py`)
        return json_resp(410, {"error": "a ponte do Premiere agora é a do Ciclo Assist, instalada pelo instalador "
                                        "único do app", "aposentada": True})
    if post and r == "/app/fixar":
        v, erro = p.json_estrito(de_bytes=True)
        if erro:
            return erro
        # A janela do painel era do Órbita; dentro do guarda-chuva ela não existe (o Rust em `--motor` já dava isto).
        return json_resp(404, {"error": "a janela do painel não está aberta"})

    # ── o resto ──
    if get and r == "/health":
        quem = query_param(p.url, "nle")
        if quem is not None:
            tb.marcar_presenca(quem)
        return json_resp(200, {"ok": True, "app": "sincronizar", "version": VERSAO, "busy": tb.em_curso() is not None})
    if get and r == "/nlejob":
        job = tb.pegar_job(query_param(p.url, "nle") or "premiere")
        return json_resp(200, {"job": job} if job is not None else {})
    if post and r == "/nlejob/done":
        if _ilegivel(p):
            return _ilegivel(p)
        e = _obj(p.json_ou_vazio())
        if isinstance(e.get("id"), str):
            ok = e.get("ok")
            tb.montagem_terminou(e["id"], ok if isinstance(ok, bool) else False, _texto(e, "summary"))
        return json_resp(200, {"ok": True})
    if get and r == "/api/v1/info":
        return api_info()
    if get and r == "/api/v1/montagem":
        q = query_param(p.url, "id")
        if q is None:
            return json_resp(400, {"error": "faltou ?id="})
        mt = tb.montagem(q)
        return json_resp(200, mt) if mt else json_resp(404, {"error": "montagem desconhecida"})
    if post and r == "/api/v1/avid/sincronizar":
        v, erro = p.json_estrito(de_bytes=True)
        return erro or api_avid_sincronizar(v)
    if post and r == "/api/v1/nlejob":
        return _ilegivel(p) or api_enfileirar_montagem(p.json_ou_vazio())
    if post and r == "/api/v1/merge":
        if _ilegivel(p):
            return _ilegivel(p)
        e = p.json_ou_vazio()
        return ocupado() or api_enfileirar_merged(e, lambda prm: motor.chamar("premiere_merged_from_sync", prm))
    if get and r == "/prproj/status":
        q = query_param(p.url, "id")
        if q is None:
            return json_resp(400, {"error": "faltou ?id="})
        st = tb.status(q)
        return json_resp(200, st) if st else json_resp(404, {"error": "job desconhecido"})
    if get and r == "/settings":
        b = ocupado()
        if b:
            return b
        try:
            d = _obj(motor.chamar("get_settings", {}))
        except motor.ErroDoMotor as e:
            return json_resp(500, {"error": str(e)})
        c = _obj(d.get("cache"))
        return json_resp(200, {"cache_dir": c.get("dir"), "cache_bytes": c.get("bytes", 0),
                               "cache_files": c.get("files", 0),
                               "cache_is_default": d.get("cache_dir") is None, "logs_dir": d.get("logs_dir")})
    if post and r == "/cache/clear":
        b = ocupado()
        if b:
            return b
        try:
            d = _obj(motor.chamar("cache_clear", {}))
        except motor.ErroDoMotor as e:
            return json_resp(500, {"error": str(e)})
        c = _obj(d.get("cache"))
        return json_resp(200, {"freed_bytes": d.get("bytes", 0), "freed_files": d.get("files", 0),
                               "cache_bytes": c.get("bytes", 0), "cache_files": c.get("files", 0)})
    if post and r == "/folder/open":
        return _ilegivel(p) or abrir_pasta(p.json_ou_vazio())
    if post and r == "/link/open":
        if _ilegivel(p):
            return _ilegivel(p)
        if _obj(p.json_ou_vazio()).get("which") != "author":
            return json_resp(400, {"error": "link desconhecido"})
        try:
            abrir_no_sistema(LINK_DO_AUTOR)
        except (OSError, subprocess.CalledProcessError) as e:
            return json_resp(500, {"error": str(e)})
        return json_resp(200, {"ok": True})
    if post and r in ("/midia/fichas", "/midia/analise"):
        # ⛔ Fora do `ocupado()`: as colunas do card se preenchem também durante um sync (`fichas.py`)
        v, erro = p.json_estrito()
        if erro:
            return erro
        status, corpo = (fichas_de_midia.rota_fichas(_obj(v)) if r == "/midia/fichas"
                         else fichas_de_midia.rota_analise(_obj(v)))
        return json_resp(status, corpo)
    if get and r == portao.ROTA_UI_PAINEL_AVID:
        try:
            return pagina(paginas.ui_do_painel(), "text/html; charset=utf-8")
        except (OSError, RuntimeError) as e:
            return json_sem_cors(500, {"error": str(e)})

    # ── Media Composer ──
    if post and r == "/arrasto/mc":
        if _ilegivel(p):
            return _ilegivel(p)
        return _ou_500(lambda: json_resp(200, especies_do_arrasto(_lista(_obj(p.json_ou_vazio()), "mob_ids") or [])))
    if post and r == "/avid/bins":
        return job_do_motor("avid_bins", {}, "listando as bins…")
    if post and r in ("/avid/mobs", "/avid/renomear/ler"):
        if _ilegivel(p):
            return _ilegivel(p)
        e = _obj(p.json_ou_vazio())
        mobs = _lista(e, "mob_ids")
        if mobs is None:
            return json_resp(400, {"error": "faltou mob_ids"})
        if r == "/avid/mobs":
            return job_do_motor("avid_mobs", {"mob_ids": mobs}, "lendo o que foi arrastado…")
        t = e.get("todas_as_colunas")
        return job_do_motor("avid_rename_scan", {"mob_ids": mobs, "todas_as_colunas": t if isinstance(t, bool)
                                                 else False}, "lendo a bin…")
    if post and r == "/avid/nome/prever":
        b = ocupado() or _ilegivel(p)
        if b:
            return b
        e = _obj(p.json_ou_vazio())
        fichas = _lista(e, "fichas")
        if fichas is None:
            return json_resp(400, {"error": "faltaram fichas"})
        return chamar_motor("avid_name_preview", {"padrao": _texto(e, "padrao"), "fichas": fichas})
    if post and r == "/avid/renomear/aplicar":
        if _ilegivel(p):
            return _ilegivel(p)
        e = _obj(p.json_ou_vazio())
        lev = _exige(e, "levantamento_id", "")
        if lev is None:
            return json_resp(400, {"error": "faltou levantamento_id"})
        return job_do_motor("avid_rename_apply", {"levantamento_id": lev, "padrao": _texto(e, "padrao")},
                            "renomeando…")
    if post and r == "/avid/renomear/desfazer":
        if _ilegivel(p):
            return _ilegivel(p)
        e = _obj(p.json_ou_vazio())
        params = {"undo_id": e["undo_id"]} if isinstance(e.get("undo_id"), str) else {}
        return job_do_motor("avid_rename_undo", params, "desfazendo…")
    if post and r == "/avid/timeline":
        if _ilegivel(p):
            return _ilegivel(p)
        mob = _exige(_obj(p.json_ou_vazio()), "mob_id", "")
        if mob is None:
            return json_resp(400, {"error": "faltou mob_id"})
        return job_do_motor("avid_timeline", {"mob_id": mob}, "achando a bin…")
    if post and r == "/avid/subclipes/ler":
        if _ilegivel(p):
            return _ilegivel(p)
        b = _exige(_obj(p.json_ou_vazio()), "bin", "")
        if b is None:
            return json_resp(400, {"error": "faltou bin"})
        return job_do_motor("avid_subclips_read", {"bin": b}, "lendo as tomadas…")
    if post and r in ("/avid/subclipes/prever", "/avid/subclipes/cena", "/avid/subclipes/remover"):
        b = ocupado() or _ilegivel(p)
        if b:
            return b
        e = _obj(p.json_ou_vazio())
        lei = _exige(e, "leitura_id", "")
        if lei is None:
            return json_resp(400, {"error": "faltou leitura_id"})
        if r == "/avid/subclipes/prever":
            return chamar_motor("avid_subclips_preview", {"leitura_id": lei, "padrao": _texto(e, "padrao")})
        if r == "/avid/subclipes/cena":
            idx = _lista(e, "indices")
            if idx is None:
                return json_resp(400, {"error": "faltaram indices"})
            return chamar_motor("avid_subclips_scene", {"leitura_id": lei, "indices": idx,
                                                        "cena": _texto(e, "cena")})
        params: dict = {"leitura_id": lei}
        if e.get("tudo") is True:
            params["tudo"] = True
        else:
            idx = _lista(e, "indices")
            if idx is None:
                return json_resp(400, {"error": "faltaram indices"})
            params["indices"] = idx
        return chamar_motor("avid_subclips_drop", params)
    if post and r == "/premiere/merged/ler":
        b = ocupado() or _ilegivel(p)
        return b or _premiere_merged_ler(_obj(p.json_ou_vazio()))
    if post and r in RENOMEAR_PREMIERE:
        b = ocupado() or _ilegivel(p)
        if b:
            return b
        e = _obj(p.json_ou_vazio())
        comando, campos = RENOMEAR_PREMIERE[r]
        return chamar_motor(comando, {c: e[c] for c in campos if c in e})
    if post and r == "/premiere/merged/gerar":
        if _ilegivel(p):
            return _ilegivel(p)
        e = _obj(p.json_ou_vazio())
        lei = _exige(e, "leitura_id", "")
        if lei is None:
            return json_resp(400, {"error": "faltou leitura_id"})
        b = _texto(e, "bin")
        return job_do_motor("premiere_merged_write", {
            "leitura_id": lei, "padrao": _texto(e, "padrao"), "bin": b,
            "premiere_alvo": "2023" if _texto(e, "premiere_alvo") == "2023" else "25",
            "output_path": temp_prproj_path(b)}, "escrevendo os merged clips…")
    if post and r == "/avid/subclipes/gerar":
        if _ilegivel(p):
            return _ilegivel(p)
        e = _obj(p.json_ou_vazio())
        lei = _exige(e, "leitura_id", "")
        if lei is None:
            return json_resp(400, {"error": "faltou leitura_id"})
        pc = e.get("por_cena")
        return job_do_motor("avid_subclips_write", {
            "leitura_id": lei, "padrao": _texto(e, "padrao"), "por_cena": pc if isinstance(pc, bool) else False,
            "nome": _texto(e, "nome").strip()}, "escrevendo os subclipes…")
    if get and r == "/avid/renomear/historico":
        return ocupado() or chamar_motor("avid_rename_history", {})
    if post and r == "/avid/selecao":
        if _ilegivel(p):
            return _ilegivel(p)
        e = _obj(p.json_ou_vazio())
        params = {"bins": e["bins"]} if isinstance(e.get("bins"), list) else {}
        return job_do_motor("avid_selection", params, "lendo a seleção…")
    if post and r == "/avid/montar":
        v, erro = p.json_estrito()
        if erro:
            return erro
        params = montar_avid_params(v)
        if params is None:
            return json_resp(400, {"error": "faltou o resultado do sync"})
        return job_do_motor("export_avid", params, "montando a bin…")
    if post and r == "/avid/painel":
        # O painel `avpi://` pedia ao app que se mostrasse (ou que lesse a seleção na janela do Studio). Sem o Studio
        # o pedido é recebido e dito; a Preparar faz a seleção ela mesma.
        v = p.json_ou_vazio()
        acao = _obj(v).get("acao")
        return json_resp(200, {"ok": True, "acao": acao if isinstance(acao, str) else "abrir"})
    if post and r == "/syncmap":
        v, erro = p.json_estrito()
        return erro or sync_job(v)
    if post and r in APOSENTADAS:
        return json_resp(410, {"error": APOSENTADAS[r], "aposentada": True})
    return json_resp(404, {"error": "rota desconhecida"})


def _ou_500(f: Callable[[], Resposta]) -> Resposta:
    try:
        return f()
    except (OSError, RuntimeError) as e:
        return json_resp(500, {"error": str(e)})




# ── o HTTP ──────────────────────────────────────────────────────────────────────────────────────────────────────

class _Atendente(BaseHTTPRequestHandler):
    server_version = "Sincronizar"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # o padrão escreve no stderr a cada pedido
        log.debug("%s " + fmt, self.address_string(), *args)

    def _atender(self) -> None:
        url = self.path
        rota = url.split("?", 1)[0]
        tamanho = self.headers.get("Content-Length")
        try:
            n = int(tamanho) if tamanho is not None else None
        except ValueError:
            n = None
        if self.command == "OPTIONS":
            return self._enviar(json_resp(200, {}))  # preflight CORS (antes do portão, como no Rust)
        recusa = portao.portao(self.headers.get("Host"), self.headers.get("Origin"),
                               self.headers.get("Sec-Fetch-Site"), self.headers.get(segredo.HEADER), n, rota,
                               porta=self.server.server_address[1], token_confere=segredo.confere)
        if recusa:
            st, msg = recusa
            if n:  # o corpo de quem foi barrado não é lido — e a conexão não pode ser reaproveitada com ele
                self.close_connection = True
            r = (json_sem_cors if recusa == portao.ORIGEM_WEB else json_resp)(st, {"error": msg})
            return self._enviar(r)
        corpo = self.rfile.read(n) if n else b""
        try:
            resposta = rotear(Pedido(self.command, url, corpo))
        except Exception:
            log.exception("pânico ao tratar %s %s", self.command, rota)
            resposta = json_resp(500, {"error": "erro interno"})
        self._enviar(resposta)

    def _enviar(self, r: Resposta) -> None:
        try:
            self.send_response(r.status)
            self.send_header("Content-Type", r.tipo)
            self.send_header("Content-Length", str(len(r.corpo)))
            for k, v in r.cabecalhos:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(r.corpo)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = do_POST = do_OPTIONS = _atender

    def do_PUT(self) -> None:
        self._atender()

    do_DELETE = do_PATCH = do_PUT


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    # ⛔ No Windows `allow_reuse_address` deixa um SEGUNDO processo bindar a mesma porta em silêncio (medido no
    # Assist, 2026-09-12: dois serviços na 7824, o velho respondendo). No POSIX ele só reaproveita TIME_WAIT.
    allow_reuse_address = sys.platform != "win32"


def _sair_porque_o_pai_sumiu(pid: int) -> None:
    """⭐ Dito no log antes de sair (revisão de 2026-11-07): o supervisor via "o processo saiu (código 0)" e nada aqui
    contava por quê."""
    log.info("o aplicativo (pid %d) fechou — encerrando o servidor", pid)
    for h in logging.getLogger().handlers + log.handlers:
        try:
            h.flush()
        except Exception:  # noqa: BLE001 — sair é o que importa
            pass
    os._exit(0)


def vigiar_o_pai(pid: int) -> None:
    """`--pai`: encerra quando o app some (matriz de plataforma, "processo órfão"; o `vigia_pai.rs` do Órbita)."""
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return

        def esperar() -> None:
            k32.WaitForSingleObject(ctypes.c_void_p(h), 0xFFFFFFFF)
            _sair_porque_o_pai_sumiu(pid)
    else:
        if os.getppid() != pid:
            _sair_porque_o_pai_sumiu(pid)  # já fomos readotados: o pai morreu antes de olharmos

        def esperar() -> None:
            while os.getppid() == pid:
                time.sleep(2)
            _sair_porque_o_pai_sumiu(pid)
    threading.Thread(target=esperar, name="vigia-do-pai", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="o servidor do Sincronizar (ex-Órbita)")
    ap.add_argument("--porta", type=int, default=PORTA)
    ap.add_argument("--pai", type=int, default=None)
    ap.add_argument("--motor", action="store_true", help="aceito e ignorado (o argumento do Órbita em Rust)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [sincronizar] %(message)s")
    try:
        srv = Servidor(("127.0.0.1", a.porta), _Atendente)
    except OSError as e:
        # ⚠️ Não é aviso de rotina: ALGUÉM está atendendo por nós, e os painéis vão mandar o token para ele.
        print(f"\n[sincronizar] ### A PORTA {a.porta} JÁ ESTÁ OCUPADA — a ponte com os plugins NÃO subiu.\n"
              f"[sincronizar] ### Outro programa atende nela; descubra qual antes de usar os plugins "
              f"(lsof -nP -iTCP:{a.porta} -sTCP:LISTEN). Detalhe: {e}\n", file=sys.stderr)
        return 2
    if not (os.environ.get("SINCRONIZAR_DADOS") or os.environ.get("CICLOASSIST_DADOS")):
        try:
            trazidos = segredo.migrar_da_pasta_antiga()
            if trazidos:
                log.info("da pasta do Órbita (%s) para %s: %s", segredo.pasta_antiga(), segredo.pasta_de_dados(),
                         ", ".join(trazidos))
        except OSError as e:
            log.warning("não consegui trazer os dados da pasta do Órbita: %s", e)
    try:
        onde = segredo.publicar()
        log.info("o token é o ÚNICO do Ciclo Assist: %s", onde)
    except OSError as e:
        log.error("não consegui publicar o token (%s): os plugins não vão entrar", e)
    if a.pai:
        vigiar_o_pai(a.pai)
    motor._ambiente(VERSAO)
    log.info("ffmpeg=%s · ffprobe=%s", os.environ.get("SINC_FFMPEG"), os.environ.get("SINC_FFPROBE"))
    if motor.log_sem_fixado:
        log.warning("sem o ffmpeg FIXADO em %s (%s): caí no do sistema — o sync pode diferir do Órbita",
                    motor.BINARIOS, ", ".join(motor.log_sem_fixado))
    threading.Thread(target=motor.carregar, args=(VERSAO,), name="carregar-motor", daemon=True).start()
    log.info("servidor do Sincronizar em http://127.0.0.1:%d (motor Python, no mesmo processo)", a.porta)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
