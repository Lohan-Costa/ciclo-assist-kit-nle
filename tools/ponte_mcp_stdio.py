"""A ponte de um cliente MCP de STDIO (o app do Claude) para o MCP HTTP do Ciclo Assist (pedido do autor, 2026-11-20).

No `claude_desktop_config.json` do app do Claude:

    "mcpServers": {"edicao": {"command": "<…>\\.venv-win\\Scripts\\python.exe",
                              "args": ["<…>\\tools\\ponte_mcp_stdio.py", "--so", "abrir_programa,converter_para_opatom,…"]}}

O serviço tem de estar no ar SEM a janela (`tools/servico_sem_janela.py iniciar`); o endereço (com o segredo) é lido
de `<dados>/mcp_externo.json` a CADA pedido, então reiniciar o serviço não pede reiniciar o app do Claude.

- Uma linha JSON-RPC por vez na entrada, uma resposta por linha na saída (o transporte stdio do MCP). Notificação
  (sem `id`) não tem resposta.
- ⭐ Ferramenta longa (abrir o Media Composer ~1 min, o sync, o import): passados 45 s a ponte responde "ainda
  rodando" com um código, e `aguardar_operacao` (da ponte) entrega o resultado — o app do Claude desiste de uma
  chamada em ~1 min (medido em 2026-11-19), e progresso não segurava o prazo.
- ⛔ `pedir_confirmacao` nunca aparece: é o portão do `claude -p` do Ciclo Assist; aqui quem confirma é o próprio app
  do Claude ("Permitir"). `--so` restringe a lista ao que a sessão precisa.
- ⛔ Nada de stdout que não seja protocolo: um `print` solto quebra o cliente. O que não for resposta vai ao stderr.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ESCONDIDAS = {"pedir_confirmacao"}
PRAZO_S = 1800          # uma ferramenta do ensaio leva minutos; mais de meia hora é travamento

_saida = threading.Lock()


def _arquivo() -> Path:
    base = os.environ.get("CICLOASSIST_DADOS")
    if base:
        return Path(base) / "mcp_externo.json"
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "CicloAssist" / "mcp_externo.json"
    return Path.home() / "Library" / "Application Support" / "CicloAssist" / "mcp_externo.json"


def _url() -> str | None:
    try:
        return json.loads(_arquivo().read_text(encoding="utf-8")).get("url")
    except (OSError, ValueError):
        return None


def _escrever(msg: dict) -> None:
    linha = json.dumps(msg, ensure_ascii=False)
    with _saida:
        sys.stdout.write(linha + "\n")
        sys.stdout.flush()


def _log(texto: str) -> None:
    print(f"[ponte] {texto}", file=sys.stderr, flush=True)


FORA_DO_AR = ("O serviço de edição não está no ar. Peça ao operador para rodar "
              "`tools/servico_sem_janela.py iniciar` e tente de novo.")


def _post(msg: dict) -> dict | list | None:
    url = _url()
    if not url:
        raise ConnectionError(FORA_DO_AR)
    req = urllib.request.Request(url, data=json.dumps(msg).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=PRAZO_S) as r:
            corpo = r.read()
            return json.loads(corpo) if corpo else None
    except urllib.error.HTTPError as e:
        corpo = e.read()
        try:
            return json.loads(corpo)
        except ValueError:
            raise ConnectionError(f"o serviço respondeu {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise ConnectionError(f"{FORA_DO_AR} ({e})") from None


def _filtrar(resposta: dict, so: set[str] | None) -> dict:
    tools = ((resposta or {}).get("result") or {}).get("tools")
    if isinstance(tools, list):
        resposta["result"]["tools"] = [t for t in tools if t.get("name") not in ESCONDIDAS
                                       and (so is None or t.get("name") in so)]
    return resposta


#: ⛔⛔ MEDIDO (2026-11-19, app do Claude 5.11492, modo agente): o cliente desiste de uma ferramenta em ~1 min, e os
#:   `notifications/progress` não seguraram o prazo. Abrir o Media Composer leva ~1 min (6 min com um aviso na tela):
#:   o Claude leu "timeout" de uma abertura que terminou bem, e saiu tentando ler as bins de um MC ainda abrindo.
#:   ⇒ Passados `LIMITE_S`, a ponte RESPONDE "ainda rodando" e segue esperando o serviço por trás; o resultado sai por
#:   `aguardar_operacao` (ferramenta DA PONTE). A operação nunca é repetida nem cortada no meio.
LIMITE_S = float(os.environ.get("CICLOASSIST_PONTE_LIMITE_S") or 45.0)
AGUARDAR = "aguardar_operacao"
_FERRAMENTA_AGUARDAR = {
    "name": AGUARDAR,
    "description": ("Espera uma operação que ainda está rodando na máquina (abrir um programa, importar, sincronizar) e "
                    "devolve o resultado dela quando terminar. Use quando uma ferramenta responder que continua rodando: "
                    "passe o `operacao` que ela deu. Pode voltar 'ainda rodando' de novo; então chame outra vez. Nunca "
                    "repita a operação original enquanto ela roda."),
    "inputSchema": {"type": "object", "properties": {"operacao": {"type": "string", "description": "O código que a "
                    "ferramenta devolveu (ex.: op1)."}}, "required": ["operacao"]},
}
_operacoes: dict[str, dict] = {}
_ops_trava = threading.Lock()


def _texto(id_, texto: str, erro: bool = False) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": texto}], "isError": erro}}


def _rodando(op: str, nome: str, desde: float) -> str:
    return (f"⏳ {nome} continua rodando na máquina ({time.time() - desde:.0f} s até agora) — não deu erro, só demora "
            f"(abrir o Media Composer leva de 1 a 6 minutos). NÃO chame {nome} de novo: chame {AGUARDAR} com "
            f"operacao=\"{op}\" para receber o resultado.")


def _chamar_servico(msg: dict) -> dict:
    try:
        r = _post(msg)
    except ConnectionError as e:
        return _texto(msg.get("id"), str(e), True)
    return r if isinstance(r, dict) else _texto(msg.get("id"), "o serviço não respondeu nada", True)


def _aguardar(id_, argumentos: dict) -> dict:
    op = str((argumentos or {}).get("operacao") or "")
    with _ops_trava:
        o = _operacoes.get(op)
    if not o:
        return _texto(id_, f"não há operação '{op}' em andamento (ela pode já ter sido entregue).", True)
    if not o["feito"].wait(LIMITE_S):
        return _texto(id_, _rodando(op, o["nome"], o["desde"]))
    with _ops_trava:
        _operacoes.pop(op, None)
    r = dict(o["resposta"])
    r["id"] = id_
    _log(f"{o['nome']} entregue por {AGUARDAR} ({time.time() - o['desde']:.1f} s no total)")
    return r


def _atender(msg: dict, so: set[str] | None) -> None:
    metodo, id_ = msg.get("method"), msg.get("id")
    tem_id = "id" in msg
    params = msg.get("params") or {}
    if metodo == "tools/call":
        nome = params.get("name")
        if nome == AGUARDAR:
            _escrever(_aguardar(id_, params.get("arguments") or {}))
            return
        if nome in ESCONDIDAS or (so is not None and nome not in so):
            _escrever(_texto(id_, f"{nome} não está disponível aqui.", True))
            return
        desde = time.time()
        o = {"nome": nome, "desde": desde, "feito": threading.Event(), "resposta": None}

        def trabalhar():
            o["resposta"] = _chamar_servico(msg)
            _log(f"{nome} em {time.time() - desde:.1f} s")
            o["feito"].set()
        threading.Thread(target=trabalhar, daemon=True).start()
        if o["feito"].wait(LIMITE_S):
            _escrever(o["resposta"])
            return
        with _ops_trava:
            op = f"op{len(_operacoes) + 1}-{int(desde) % 100000}"
            _operacoes[op] = o
        _log(f"{nome} passou de {LIMITE_S:.0f} s: respondido como {op}, ainda rodando")
        _escrever(_texto(id_, _rodando(op, nome, desde)))
        return
    try:
        r = _post(msg)
    except ConnectionError as e:
        if not tem_id:
            return
        r = {"jsonrpc": "2.0", "id": id_, "error": {"code": -32000, "message": str(e)}}
    if r is None or not tem_id:
        return
    if metodo == "tools/list" and isinstance(r, dict):
        r = _filtrar(r, so)
        if isinstance((r.get("result") or {}).get("tools"), list):
            r["result"]["tools"].append(_FERRAMENTA_AGUARDAR)
    if metodo == "initialize" and isinstance(r, dict) and isinstance((r.get("result") or {}).get("serverInfo"), dict):
        r["result"]["serverInfo"]["name"] = NOME     # o nome que o cliente mostra é o da configuração, não o nosso
    _escrever(r)


NOME = "edicao"


def main(argv: list[str]) -> int:
    global NOME
    if "--nome" in argv:
        NOME = argv[argv.index("--nome") + 1]
    so = None
    if "--so" in argv:
        so = {n.strip() for n in argv[argv.index("--so") + 1].split(",") if n.strip()}
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    _log(f"pronta ({'todas as ferramentas' if so is None else f'{len(so)} ferramentas'}); serviço: "
         f"{'no ar' if _url() else 'FORA (rode servico_sem_janela.py iniciar)'}")
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            msg = json.loads(linha)
        except ValueError:
            _escrever({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}})
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            # Uma thread por pedido: o cliente pode mandar `ping` ou cancelar enquanto uma ferramenta longa roda.
            threading.Thread(target=_atender, args=(m, so), daemon=True).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
