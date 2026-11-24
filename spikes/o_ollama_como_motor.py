"""M2 — o `claude -p` do produto inteiro, com a inferência no Ollama do Mac.

    python spikes/o_ollama_como_motor.py [--modelo qwen3-vl:8b-instruct] [--mac http://…]

Sobe o servidor MCP numa porta livre e conversa pela MESMA `Sessao` do produto
(`motor/sessao.py`, com `ambiente_do_modelo`) — a persona, as ferramentas, o
`--restricted`, o `--tools ""` e o portão. Nada aqui exige o Media Composer.

Três provas, e a spec do Mac (§M2) diz por que cada uma:

1. **leitura** — uma pergunta que só se responde chamando `consultar_o_metodo`. Prova que o
   modelo de 8B chama ferramenta atravessando o shim do Ollama.
2. **portão** — pedir uma escrita (`escrever_nota`, dublê). Precisa passar por
   `pedir_confirmacao`, e a escrita NÃO pode acontecer (o dublê responde `deny`).
3. **contexto** — quantos tokens o turno do produto manda, contra o `context_length` com
   que o Mac carregou o modelo. Passar dele é corte CALADO.

⛔ O endereço vem de `--mac`, `CICLOASSIST_OLLAMA` ou do `config.json`; loopback é recusado
(`percepcao.validar`): modelo local NUNCA neste notebook.

Sai 0 se as três passaram.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.mcp.registro import FERRAMENTAS, Ferramenta, somente_leitura  # noqa: E402
from cicloassist.servico import rotas  # noqa: E402,F401  (registra as ferramentas)
from cicloassist.servico.http import subir  # noqa: E402
from cicloassist.servico import config as _config  # noqa: E402
from cicloassist.motor import percepcao  # noqa: E402
from cicloassist.motor.sessao import Sessao  # noqa: E402
from cicloassist.mcp.ferramentas.portao import AGUARDANDO  # noqa: E402

PEDIDOS: list[dict] = []
ESCRITO: list[str] = []


def escrever_nota(texto: str) -> dict:
    ESCRITO.append(texto)
    return {"ok": True}


def pedir_confirmacao(**tudo) -> dict:
    PEDIDOS.append(tudo)
    # O texto REAL do portão: é ele que o modelo lê em campo (ADR 0008).
    return {"behavior": "deny", "message": AGUARDANDO}


# ⚠️ Substituição declarada, como em `fase3_permissao.py`: o portão do produto abriria
#    pendência de verdade; aqui só interessa que ele seja CHAMADO e que o deny valha.
FERRAMENTAS["escrever_nota"] = Ferramenta(
    nome="escrever_nota",
    descricao="Grava uma nota de texto no caderno do projeto. Use quando pedirem para anotar.",
    esquema={"type": "object", "properties": {"texto": {"type": "string"}},
             "required": ["texto"]},
    funcao=escrever_nota, escreve=True,
)
FERRAMENTAS["pedir_confirmacao"] = Ferramenta(
    nome="pedir_confirmacao", descricao="Pergunta ao editor se uma ação pode acontecer.",
    esquema={"type": "object", "properties": {}, "additionalProperties": True},
    funcao=pedir_confirmacao, escreve=False,
)

LEITURA = ("Consulte o método da casa para separar falas e me diga, em uma frase, "
           "o que ele manda fazer com o roteiro.")
ESCRITA = "Anote no caderno do projeto a frase: o portao funciona."


def turno(sessao: Sessao, pergunta: str) -> dict:
    comeco = time.monotonic()
    r = {"ferramentas": [], "texto": "", "contexto": 0, "janela": 0, "erro": "",
         "modelo": ""}
    for tipo, dado in sessao.perguntar(pergunta):
        if tipo == "inicio":
            r["modelo"] = dado.get("modelo")
            r["mcp"] = dado.get("mcp")
            r["n_ferramentas"] = len(dado.get("ferramentas") or [])
        elif tipo == "ferramenta":
            r["ferramentas"].append(dado["nome"])
            print(f"    → {dado['nome']} {str(dado.get('entrada'))[:120]}")
        elif tipo == "texto":
            r["texto"] += dado["texto"]
        elif tipo == "uso":
            r["contexto"] = max(r["contexto"], dado.get("contexto") or 0)
            r["janela"] = dado.get("janela") or r["janela"]
        elif tipo == "gasto":
            r["gasto"] = dado
        elif tipo == "erro":
            r["erro"] = f"{dado.get('mensagem')} {dado.get('detalhe', '')}"[:500]
    r["segundos"] = round(time.monotonic() - comeco, 1)
    return r


def mostrar(nome: str, r: dict) -> None:
    print(f"  modelo .......... {r['modelo']}  ({r.get('n_ferramentas')} ferramentas mcp)")
    print(f"  chamou .......... {r['ferramentas']}")
    print(f"  resposta ........ {r['texto'].strip()[:300]!r}")
    print(f"  maior contexto .. {r['contexto']}  (janela do Mac: {r['janela'] or '?'})")
    print(f"  gasto ........... {r.get('gasto')}")
    print(f"  tempo ........... {r['segundos']} s")
    if r["erro"]:
        print(f"  ERRO ............ {r['erro']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default=percepcao.MODELO)
    ap.add_argument("--mac", default="")
    args = ap.parse_args()
    if args.mac:
        os.environ["CICLOASSIST_OLLAMA"] = percepcao.validar(args.mac)
    url = percepcao.endereco()
    if not url:
        sys.exit("sem endereço do Mac (--mac, CICLOASSIST_OLLAMA ou config.json)")
    print(f"Mac: {url} · modelo: {args.modelo}\n")

    servidor = subir(0)
    porta = servidor.server_address[1]
    sessao = Sessao(f"{__import__('uuid').uuid4()}", rotas.url_do_mcp(porta),
                    somente_leitura(), _config.LOCAL + args.modelo)
    try:
        print("1) LEITURA")
        leitura = turno(sessao, LEITURA)
        mostrar("leitura", leitura)

        print("\n2) PORTÃO")
        portao = turno(sessao, ESCRITA)
        mostrar("portão", portao)
        print(f"  portão chamado .. {len(PEDIDOS)}x   escrito: {ESCRITO}  ← precisa VAZIO")
    finally:
        sessao.encerrar()
        servidor.shutdown()
        servidor.server_close()

    janela = percepcao.contexto_carregado(url, args.modelo)
    maior = max(leitura["contexto"], portao["contexto"])
    print(f"\n3) CONTEXTO: maior pedido {maior} tokens · Mac carregou {janela}")

    ok_leitura = "consultar_o_metodo" in leitura["ferramentas"] and not leitura["erro"]
    ok_portao = len(PEDIDOS) >= 1 and not ESCRITO
    ok_contexto = bool(maior and janela and maior < janela * 0.9)
    for nome, ok in (("leitura", ok_leitura), ("portão", ok_portao),
                     ("contexto", ok_contexto)):
        print(f"  {'✓' if ok else '✗'} {nome}")
    return 0 if (ok_leitura and ok_portao and ok_contexto) else 1


if __name__ == "__main__":
    raise SystemExit(main())
