"""O servidor MCP NATIVO do Premiere (27.1+) — a segunda via, ao lado da ponte CEP.

Plano: `docs/plano/2026-11-06-mcp-do-premiere.md`. Banco: `transversal/ia-embarcada-nos-nles.md` §3f.

⭐⭐ **Princípio do autor (2026-11-06):** a via mais nova quando o Premiere aberto a tiver; a
conhecida (CEP) quando não. A escolha é por OPERAÇÃO e por CAPACIDADE — o `tools/list` do
servidor —, nunca pelo número da versão: `via(operacao)` diz "mcp" só se o servidor responde E
tem todas as ações que a operação usa.

⛔ O modelo NUNCA vê as ações daqui. Isto é motor do Ciclo Assist, não catálogo do chat.

Medido (Mac, 27.1.0 b7): leituras em 1–9 ms, 613 itens em 24 ms; concorrência com a ponte CEP
sem interferência; escuta só em `[::1]` (IPv6 de loopback). Protocolo MCP Streamable HTTP
2025-06-18: POST, resposta em SSE (`data: {...}`), sessão em `mcp-session-id`.

**A senha:** no desenvolvimento ela está DESLIGADA (decisão do autor, 2026-11-06). Como produto a
fonte do token está em aberto (plano §8); por ora só `CICLOASSIST_PREMIERE_MCP_TOKEN`. ⛔ O token
nunca vai para log, resposta ou tela.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("cicloassist.nle.premiere.mcp")

URL_PADRAO = "http://[::1]:3000/premiere/mcp"
PROTOCOLO = "2025-06-18"
PRAZO_S = 30.0
#: Quanto tempo vale a resposta "o servidor está / não está aí". Curto: o editor abre e fecha o
#: Premiere, e a CEP continua sendo a reserva enquanto o MCP não responde.
VALIDADE_DA_SONDA_S = 10.0
#: Quanto vale o "não está aí". ⛔ MEDIDO no Windows (2026-11-08): uma porta local fechada leva 2,04 s para recusar,
#: mais que o `PRAZO_DA_SONDA_S`; com a validade de 10 s e o painel perguntando a cada 15 s, TODO `/conexao` pagava
#: 1,5 s por um servidor que só existe no Beta. Mais longa sem custo: enquanto não responde, a CEP atende.
VALIDADE_DA_AUSENCIA_S = 60.0
#: A sonda é barata quando o servidor existe (~2 ms) e tem de ser barata quando não existe:
#: porta fechada recusa na hora, mas um prazo curto protege de uma pilha de rede lenta.
PRAZO_DA_SONDA_S = 1.5

#: As ações de cada operação do Ciclo Assist. Faltou UMA, a operação fica na CEP.
OPERACOES: dict[str, frozenset[str]] = {
    "projeto": frozenset({"getOpenProjects", "getEditingContext", "getSequenceStructure"}),
    "midias": frozenset({"getOpenProjects", "getProjectItems", "getClipMetadata"}),
    # ⭐ F2: a árvore do projeto e o organizar — JUNTOS, porque os ids que o modelo lê na árvore
    #   são os que ele manda no organizar (os do MCP não são os `nodeId` da CEP).
    "itens": frozenset({"getOpenProjects", "getProjectItems", "getClipMetadata", "getEditingContext",
                        "getSequenceStructure", "createBins", "moveOrCopyProjectItems",
                        "renameProjectItems", "deleteProjectItems"}),
    # ⭐ F3: montar uma sequência (montar_corte, separar_falas). Sem estas ações
    #   pelo MCP, a ponte CEP (`montagem_cep.py`, F6).
    "montagem": frozenset({"getOpenProjects", "getProjectItems", "getClipMetadata", "getSequenceStructure",
                           "createSequences", "deleteTrackItems", "razorTrackItems", "moveOrCopyTrackItems",
                           "addTracksToSequence", "deleteProjectItems", "createBins"}),
    # ⭐ F4/F7: ler e editar a timeline do editor; sem estas, a ponte CEP (`edicao_cep.py`).
    "edicao": frozenset({"getOpenProjects", "getProjectItems", "getSequenceStructure", "moveOrCopyProjectItems",
                         "razorTrackItems", "deleteTrackItems", "moveOrCopyTrackItems", "createSequences",
                         "addTracksToSequence", "deleteProjectItems"}),
    "tela": frozenset({"getEditingContext"}),
}

#: As taxas do Premiere chegam como float (23.976): a fração EXATA sai daqui, nunca de um
#: arredondamento — 23,976 tratado como 23976/1000 erra o TC em ~3,6 s por hora.
TAXAS_NTSC = {23.976: (24000, 1001), 29.97: (30000, 1001), 47.952: (48000, 1001),
              59.94: (60000, 1001), 119.88: (120000, 1001)}


class McpIndisponivel(RuntimeError):
    """O servidor não responde (Premiere fechado, versão sem MCP, servidor desligado)."""


class McpFalhou(RuntimeError):
    """O servidor respondeu com erro — a ação existe e recusou o pedido."""


def url() -> str:
    return os.environ.get("CICLOASSIST_PREMIERE_MCP") or URL_PADRAO


def _token() -> str:
    return os.environ.get("CICLOASSIST_PREMIERE_MCP_TOKEN", "")


def via_forcada() -> str:
    """`CICLOASSIST_PREMIERE_VIA` = `cep` | `mcp` | `auto` (padrão). Para testar uma via contra a outra."""
    v = (os.environ.get("CICLOASSIST_PREMIERE_VIA") or "auto").strip().lower()
    return v if v in ("cep", "mcp") else "auto"


def taxa_exata(fps: Any) -> tuple[int, int] | None:
    """`23.976` → `(24000, 1001)`; `25` → `(25, 1)`; nada útil → `None`."""
    try:
        f = float(fps)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    for nominal, par in TAXAS_NTSC.items():
        if abs(f - nominal) < 0.01:
            return par
    if abs(f - round(f)) < 1e-6:
        return int(round(f)), 1
    from fractions import Fraction
    q = Fraction(f).limit_denominator(1001)
    return q.numerator, q.denominator


class _Sessao:
    """Uma sessão MCP. Recriada quando o servidor a esquece (Premiere reaberto)."""

    def __init__(self, endereco: str, token: str):
        self.endereco, self.token = endereco, token
        self.id: str | None = None
        self._n = 0
        self._trava = threading.Lock()

    def _post(self, corpo: dict[str, Any], prazo: float) -> dict[str, Any] | None:
        cab = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": PROTOCOLO}
        if self.token:
            cab["Authorization"] = f"Bearer {self.token}"
        if self.id:
            cab["mcp-session-id"] = self.id
        pedido = urllib.request.Request(self.endereco, json.dumps(corpo).encode("utf-8"), cab, method="POST")
        try:
            with urllib.request.urlopen(pedido, timeout=prazo) as r:
                self.id = self.id or r.headers.get("mcp-session-id")
                texto = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise McpIndisponivel(f"o servidor MCP do Premiere pediu senha (HTTP {e.code})") from e
            if e.code in (400, 404) and self.id:
                # ⚠️ Sessão que o servidor não conhece mais (Premiere reaberto): recomeçar.
                self.id = None
                raise _SessaoPerdida() from e
            raise McpIndisponivel(f"o servidor MCP do Premiere respondeu HTTP {e.code}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise McpIndisponivel(f"o servidor MCP do Premiere não respondeu ({e})") from e
        for linha in texto.splitlines():
            if linha.startswith("data: ") and '"jsonrpc"' in linha:
                return json.loads(linha[6:])
        return json.loads(texto) if texto.strip().startswith("{") else None

    def iniciar(self, prazo: float) -> dict[str, Any]:
        self.id = None
        r = self._post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": PROTOCOLO, "capabilities": {},
            "clientInfo": {"name": "ciclo-assist", "version": "1"}}}, prazo)
        if not r or "result" not in r:
            raise McpIndisponivel(f"o servidor MCP do Premiere não iniciou a sessão: {r}")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, prazo)
        return r["result"]

    def rpc(self, metodo: str, params: dict[str, Any], prazo: float) -> dict[str, Any]:
        with self._trava:
            self._n += 1
            n = self._n
        corpo = {"jsonrpc": "2.0", "id": n, "method": metodo, "params": params}
        try:
            r = self._post(corpo, prazo)
        except _SessaoPerdida:
            self.iniciar(prazo)
            r = self._post(corpo, prazo)
        if not r:
            raise McpFalhou(f"{metodo}: resposta vazia")
        if "error" in r:
            raise McpFalhou(f"{metodo}: {r['error'].get('message') or r['error']}")
        return r["result"]


class _SessaoPerdida(Exception):
    pass


class _Estado:
    def __init__(self) -> None:
        self.trava = threading.Lock()
        self.sessao: _Sessao | None = None
        self.acoes: frozenset[str] = frozenset()
        self.servidor: dict[str, Any] = {}
        self.sondado_em = 0.0
        self.erro = ""


_e = _Estado()


def esquecer() -> None:
    """Esquece a sessão e o catálogo (Premiere fechado/reaberto, ou nos testes)."""
    with _e.trava:
        _e.sessao, _e.acoes, _e.servidor, _e.sondado_em, _e.erro = None, frozenset(), {}, 0.0, ""


def _sondar() -> None:
    """Abre a sessão e lê o catálogo. Chamada com a trava segura."""
    sessao = _Sessao(url(), _token())
    try:
        info = sessao.iniciar(PRAZO_DA_SONDA_S)
        lista = sessao.rpc("tools/list", {}, PRAZO_DA_SONDA_S * 4)
    except (McpIndisponivel, McpFalhou) as e:
        _e.sessao, _e.acoes, _e.servidor, _e.erro = None, frozenset(), {}, str(e)
        return
    _e.sessao = sessao
    _e.acoes = frozenset(t.get("name", "") for t in lista.get("tools") or [])
    _e.servidor = dict(info.get("serverInfo") or {})
    _e.erro = ""
    log.info("MCP do Premiere: %s %s, %d ações", _e.servidor.get("name", "?"),
             _e.servidor.get("version", "?"), len(_e.acoes))


def acoes() -> frozenset[str]:
    """As ações que o servidor oferece agora (vazio = sem servidor). Sonda a cada 10 s; sem servidor, a cada 60 s."""
    with _e.trava:
        validade = VALIDADE_DA_SONDA_S if _e.acoes else VALIDADE_DA_AUSENCIA_S
        if time.monotonic() - _e.sondado_em >= validade:
            _e.sondado_em = time.monotonic()
            _sondar()
        return _e.acoes


def disponivel() -> bool:
    return bool(acoes())


def via(operacao: str) -> str:
    """`"mcp"` se o servidor está aí E tem todas as ações da operação; senão `"cep"`."""
    forcada = via_forcada()
    if forcada == "cep":
        return "cep"
    precisa = OPERACOES.get(operacao)
    if precisa is None:
        return "cep"
    if forcada == "mcp":
        return "mcp"
    return "mcp" if precisa <= acoes() else "cep"


def situacao() -> dict[str, Any]:
    """Para o `/conexao` e os logs: o servidor, quantas ações, e a via de cada operação."""
    a = acoes()
    vias = {op: via(op) for op in OPERACOES}   # ⛔ fora da trava: `via` sonda, e a trava não é reentrante
    with _e.trava:
        return {"disponivel": bool(a), "servidor": dict(_e.servidor), "acoes": len(a),
                "erro": _e.erro, "forcada": via_forcada(), "vias": vias}


def chamar(acao: str, argumentos: dict[str, Any] | None = None, prazo: float = PRAZO_S) -> Any:
    """Chama uma ação e devolve o `structuredContent` (ou o JSON do texto).

    ⛔ `McpIndisponivel` derruba a sessão (a próxima chamada sonda de novo), e quem chama cai
    para a CEP. `McpFalhou` é a ação recusando — a via está boa, o pedido é que não.
    """
    with _e.trava:
        sessao = _e.sessao
    if sessao is None:
        if not disponivel():
            raise McpIndisponivel(_e.erro or "o servidor MCP do Premiere não está ligado")
        with _e.trava:
            sessao = _e.sessao
        if sessao is None:
            raise McpIndisponivel("o servidor MCP do Premiere não está ligado")
    try:
        r = sessao.rpc("tools/call", {"name": acao, "arguments": argumentos or {}}, prazo)
    except McpIndisponivel:
        with _e.trava:
            _e.sessao, _e.acoes, _e.sondado_em = None, frozenset(), 0.0
        raise
    corpo = r.get("structuredContent")
    if corpo is None:
        textos = [c.get("text", "") for c in r.get("content") or [] if c.get("type") == "text"]
        try:
            corpo = json.loads(textos[0]) if textos else {}
        except ValueError:
            corpo = {"texto": textos[0]}
    if r.get("isError"):
        raise McpFalhou(f"{acao}: {json.dumps(corpo, ensure_ascii=False)[:300]}")
    return corpo


def quadro(item_id: str, segundos: float, largura: int = 768, pid: str | None = None) -> bytes:
    """O PNG de um quadro (`renderFrame`) de um clipe ou da sequência COMPOSTA, no tempo dado.

    ⛔ O tempo arredonda para BAIXO no quadro (F0): quem pede o quadro `n` manda `n/fps + 1 µs`.
    """
    import base64
    with _e.trava:
        sessao = _e.sessao
    if sessao is None:
        if not disponivel():
            raise McpIndisponivel(_e.erro or "o servidor MCP do Premiere não está ligado")
        with _e.trava:
            sessao = _e.sessao
    pid = pid or (projeto_ativo() or {}).get("agentProjectId")
    r = sessao.rpc("tools/call", {"name": "renderFrame", "arguments": {
        "agentProjectId": pid, "itemId": item_id, "time": {"seconds": segundos}, "width": largura}}, PRAZO_S)
    if r.get("isError"):
        raise McpFalhou(f"renderFrame: {str(r.get('content'))[:300]}")
    for c in r.get("content") or []:
        if c.get("type") == "image":
            return base64.b64decode(c["data"])
    raise McpFalhou("renderFrame não devolveu imagem")


def paginar(acao: str, argumentos: dict[str, Any], chave: str, prazo: float = PRAZO_S) -> list[Any]:
    """Junta as páginas (`hasMore`/`nextCursor`) de uma leitura numa lista só."""
    tudo: list[Any] = []
    cursor = None
    for _ in range(10_000):
        args = dict(argumentos)
        if cursor:
            args["cursor"] = cursor
        r = chamar(acao, args, prazo)
        tudo.extend(r.get(chave) or [])
        cursor = r.get("nextCursor")
        if not r.get("hasMore") or not cursor:
            return tudo
    raise McpFalhou(f"{acao}: paginação sem fim")


# ── as leituras ─────────────────────────────────────────────────────────────

def projeto_ativo() -> dict[str, Any] | None:
    """O projeto ATIVO do Premiere: `{agentProjectId, name, path, isActive}`, ou `None`."""
    from ...caminhos import sem_prefixo_longo
    # ⛔ no Windows o `path` vem `\\?\D:\…` (27.1 Beta, 2026-11-18) e a ponte CEP diz `D:\…`: o mesmo projeto seria
    #   dois para quem compara (a chave da conversa, a troca de via)
    projetos = [{**p, "path": sem_prefixo_longo(p["path"])} if p.get("path") else p
                for p in chamar("getOpenProjects").get("projects") or []]
    return next((p for p in projetos if p.get("isActive")), projetos[0] if len(projetos) == 1 else None)


def estado() -> dict[str, Any]:
    """O mesmo formato do `cicloProjeto` do `host.jsx`: caminho, nome, sequência ativa e fps.

    ⚠️ `versao` fica vazia: o servidor MCP não diz a versão do Premiere (o `serverInfo` é a dele).
    """
    p = projeto_ativo()
    if not p:
        return {"versao": "", "caminho": "", "nome": "", "sequencia_ativa": None, "fps": None}
    r: dict[str, Any] = {"versao": "", "caminho": str(p.get("path") or ""),
                         "nome": str(p.get("name") or ""), "sequencia_ativa": None, "fps": None}
    ctx = chamar("getEditingContext") or {}
    monitor = ctx.get("programMonitor") or ctx.get("timeline") or {}
    sid = monitor.get("sequenceId")
    if sid and monitor.get("agentProjectId", p["agentProjectId"]) == p["agentProjectId"]:
        r["sequencia_ativa"] = {"nome": str(monitor.get("name") or ""), "id": str(sid)}
        est = chamar("getSequenceStructure", {"agentProjectId": p["agentProjectId"],
                                              "sequenceId": sid, "limit": 0})
        par = taxa_exata(est.get("videoFrameRate"))
        if par:
            r["fps"] = {"num": str(par[0]), "den": str(par[1])}
    return r


def midias() -> dict[str, Any]:
    """O mesmo formato do `cicloMidias`: `{arquivos: [...], itens: [{arquivo, nome, bins}]}`.

    Um arquivo por linha, com TODAS as bins em que aparece (o master e os subclipes dele são o
    mesmo arquivo). Merged clip e sequência vêm como `type: sequence` e não têm arquivo — ficam
    de fora, como na CEP.
    """
    p = projeto_ativo()
    if not p:
        return {"arquivos": [], "itens": []}
    pid = p["agentProjectId"]
    itens = paginar("getProjectItems", {"agentProjectId": pid}, "items")
    clipes = [i for i in itens if i.get("type") == "clip"]
    caminhos: dict[str, str] = {}
    for i in range(0, len(clipes), 200):
        lote = [c["itemId"] for c in clipes[i:i + 200]]
        for r in paginar("getClipMetadata", {"agentProjectId": pid, "itemIds": lote,
                                             "fields": ["filePath"]}, "results"):
            valor = next((v.get("value") for v in r.get("values") or [] if v.get("field") == "filePath"), None)
            if valor:
                caminhos[r.get("itemId", "")] = str(valor)
    vistos: dict[str, dict[str, Any]] = {}
    ordem: list[str] = []
    for c in clipes:
        arquivo = caminhos.get(c["itemId"])
        if not arquivo:
            continue
        caminho = str(c.get("path") or "")
        bin_ = caminho.rsplit("/", 1)[0] if "/" in caminho else ""
        if arquivo not in vistos:
            vistos[arquivo] = {"arquivo": arquivo, "nome": str(c.get("name") or ""), "bins": []}
            ordem.append(arquivo)
        if bin_ not in vistos[arquivo]["bins"]:
            vistos[arquivo]["bins"].append(bin_)
    return {"arquivos": ordem, "itens": [vistos[a] for a in ordem]}


def assinatura_dos_itens() -> str:
    """Muda quando algo entra ou sai do projeto — a vigia compara isto a cada pulso (~1 ms)."""
    p = projeto_ativo()
    if not p:
        return ""
    itens = paginar("getProjectItems", {"agentProjectId": p["agentProjectId"]}, "items")
    ids = sorted(i.get("itemId", "") for i in itens if i.get("type") == "clip")
    return f"{p.get('path', '')}|{len(ids)}|{hash(tuple(ids))}"


# ── F2: a árvore do projeto, com ids do MCP ───────────────────────────────────

def _mae(caminho: str) -> str:
    return caminho.rsplit("/", 1)[0] if "/" in caminho else ""


def _e_merged(pid: str, item: dict[str, Any]) -> bool:
    """Merged clip vem como `type: sequence` (F0). O que o separa de uma timeline: TODO pedaço
    dele leva o nome dele mesmo (medido no `PRODE_SO_MERGED_2023`)."""
    try:
        est = chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": item["itemId"], "limit": 8})
    except McpFalhou:
        return False
    pedacos = est.get("items") or []
    return bool(pedacos) and all(x.get("clipName") == item.get("name") for x in pedacos)


def arvore() -> list[dict[str, Any]]:
    """O formato do `cicloArvore` — nome, id, espécie, bin — mais o `arquivo` dos clipes."""
    p = projeto_ativo()
    if not p:
        return []
    pid = p["agentProjectId"]
    itens = paginar("getProjectItems", {"agentProjectId": pid}, "items")
    clipes = [i["itemId"] for i in itens if i.get("type") == "clip"]
    arquivos: dict[str, str] = {}
    for k in range(0, len(clipes), 200):
        for r in paginar("getClipMetadata", {"agentProjectId": pid, "itemIds": clipes[k:k + 200],
                                             "fields": ["filePath"]}, "results"):
            v = next((x.get("value") for x in r.get("values") or [] if x.get("field") == "filePath"), None)
            if v:
                arquivos[r.get("itemId", "")] = str(v)
    saida = []
    for i in itens:
        tipo = i.get("type")
        if tipo == "bin":
            especie = "bin"
        elif tipo == "clip":
            especie = "clipe" if i["itemId"] in arquivos else "outro"
        else:
            especie = "merged" if _e_merged(pid, i) else "sequencia"
        d = {"nome": str(i.get("name") or ""), "id": i["itemId"], "especie": especie,
             "bin": _mae(str(i.get("path") or ""))}
        if i["itemId"] in arquivos:
            d["arquivo"] = arquivos[i["itemId"]]
        saida.append(d)
    return saida


def selecionados() -> set[str]:
    sel = (chamar("getEditingContext") or {}).get("projectPanelSelection") or []
    return {str(x.get("itemId")) for x in sel}


def bins() -> list[dict[str, Any]]:
    a = arvore()
    filhos: dict[str, int] = {}
    for i in a:
        filhos[i["bin"]] = filhos.get(i["bin"], 0) + 1
    return [{"caminho": f"{i['bin']}/{i['nome']}" if i["bin"] else i["nome"], "id": i["id"],
             "itens": filhos.get(f"{i['bin']}/{i['nome']}" if i["bin"] else i["nome"], 0)}
            for i in a if i["especie"] == "bin"]


def itens(caminho_da_bin: str = "", so_selecionados: bool = False) -> dict[str, Any]:
    """O formato do `cicloItens`. A bin vem pelo caminho ("A/B") ou pelo id."""
    a = arvore()
    alvo = caminho_da_bin or ""
    if alvo:
        por_id = next((i for i in a if i["id"] == alvo and i["especie"] == "bin"), None)
        if por_id:
            alvo = f"{por_id['bin']}/{por_id['nome']}" if por_id["bin"] else por_id["nome"]
        elif not any(i["especie"] == "bin" and (f"{i['bin']}/{i['nome']}" if i["bin"] else i["nome"]) == alvo
                     for i in a):
            raise McpFalhou(f"não achei a bin {caminho_da_bin}")
    sel = selecionados()
    saida = []
    for i in a:
        if i["bin"] != alvo:
            continue
        d = dict(i)
        if i["id"] in sel:
            d["selecionado"] = True
        if not so_selecionados or d.get("selecionado"):
            saida.append(d)
    return {"bin": alvo, "itens": saida}


def selecao() -> list[dict[str, Any]]:
    sel = selecionados()
    return [dict(i, selecionado=True) for i in arvore() if i["id"] in sel] if sel else []


def caminho_do_item(ref: str) -> str:
    """Um id do MCP → o caminho "BIN/NOME" que a CEP (`cicloAchar`) entende; vazio se não for id."""
    if not ref or "/" in ref:
        return ""
    try:
        p = projeto_ativo()
        if not p:
            return ""
        for i in paginar("getProjectItems", {"agentProjectId": p["agentProjectId"]}, "items"):
            if i.get("itemId") == ref:
                return str(i.get("path") or i.get("name") or "")
    except (McpIndisponivel, McpFalhou):
        return ""
    return ""


def organizar(operacoes: list[dict[str, Any]]) -> dict[str, Any]:
    """O plano do `organizar_o_projeto`, operação a operação, pelo MCP — o formato do `cicloOrganizar`.

    ⭐ Cada operação é UM passo do Desfazer nativo (as ações são atômicas). As referências valem
    como na CEP: id, caminho "A/B" ou nome — nessa ordem.
    """
    p = projeto_ativo()
    if not p:
        raise McpFalhou("não há projeto aberto no Premiere")
    pid = p["agentProjectId"]

    def ler() -> list[dict[str, Any]]:
        return paginar("getProjectItems", {"agentProjectId": pid}, "items")

    def achar(ref: str, so_bin: bool = False) -> dict[str, Any] | None:
        lista = ler()
        if so_bin:
            lista = [i for i in lista if i.get("type") == "bin"]
        return (next((i for i in lista if i["itemId"] == ref), None)
                or next((i for i in lista if i.get("path") == ref), None)
                or next((i for i in lista if i.get("name") == ref and i.get("type") != "bin"), None)
                or (next((i for i in lista if i.get("name") == ref), None) if so_bin else None))

    feitos = []
    for op in operacoes:
        acao = str(op.get("acao") or "")
        r: dict[str, Any] = {"acao": acao}
        try:
            if acao == "criar_bin":
                dentro = str(op.get("dentro_de") or "")
                mae = achar(dentro, so_bin=True) if dentro else None
                if dentro and not mae:
                    r["erro"] = f"não achei a bin {dentro}"
                else:
                    args: dict[str, Any] = {"agentProjectId": pid, "names": [str(op.get("nome") or "")]}
                    if mae:
                        args["parentId"] = mae["itemId"]
                    chamar("createBins", args)
                    r.update(nome=op.get("nome"), dentro_de=dentro or "(raiz)")
            elif acao == "mover":
                item, para = achar(str(op.get("item") or "")), str(op.get("para") or "")
                destino = achar(para, so_bin=True) if para else None
                if not item:
                    r["erro"] = f"não achei o item {op.get('item')}"
                elif para and not destino:
                    r["erro"] = f"não achei a bin {para}"
                else:
                    # ⚠️ Mover para a RAIZ: o `parentId` é obrigatório no MCP; a raiz não tem id na
                    #   árvore, e por isso fica recusado com a frase em vez de adivinhado.
                    if not destino:
                        r["erro"] = "mover para a raiz do projeto ainda não é feito por esta via"
                    else:
                        chamar("moveOrCopyProjectItems", {"agentProjectId": pid, "items": [
                            {"itemId": item["itemId"], "parentId": destino["itemId"]}]})
                        r.update(nome=item.get("name"), de=_mae(str(item.get("path") or "")) or "(raiz)", para=para)
            elif acao == "renomear":
                item = achar(str(op.get("item") or ""))
                if not item:
                    r["erro"] = f"não achei o item {op.get('item')}"
                else:
                    chamar("renameProjectItems", {"agentProjectId": pid, "items": [
                        {"itemId": item["itemId"], "name": str(op.get("nome") or "")}]})
                    novo = next((i for i in ler() if i["itemId"] == item["itemId"]), {})
                    r.update(de=item.get("name"), para=op.get("nome"), ficou=novo.get("name"))
            elif acao == "apagar_bin_vazia":
                alvo = achar(str(op.get("item") or ""), so_bin=True)
                if not alvo:
                    r["erro"] = f"não achei a bin {op.get('item')}"
                else:
                    filhos = [i for i in ler() if _mae(str(i.get("path") or "")) == alvo.get("path")]
                    if filhos:
                        r["erro"] = f"a bin {alvo.get('path')} não está vazia ({len(filhos)})"
                    else:
                        chamar("deleteProjectItems", {"agentProjectId": pid, "itemIds": [alvo["itemId"]]})
                        r["nome"] = alvo.get("name")
            else:
                r["erro"] = f"ação desconhecida: {acao}"
        except McpFalhou as e:
            r["erro"] = str(e)
        feitos.append(r)
    return {"feitos": feitos}
