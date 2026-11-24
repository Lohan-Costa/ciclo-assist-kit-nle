"""Fase 3, spike — descobrir o contrato do `--permission-prompt-tool`.

    python spikes/fase3_permissao.py

O que o CLI **manda** para a ferramenta de permissão, e o que ele **espera** de volta,
não está no `--help`. Este spike descobre as duas coisas medindo, em vez de presumir:

1. Registra uma ferramenta de escrita (`escrever_nota`) que NÃO entra na allowlist.
2. Registra `pedir_confirmacao` como `--permission-prompt-tool`.
3. Pede ao Claude que use a ferramenta de escrita.
4. Imprime **exatamente** o que chegou em `pedir_confirmacao`.
5. Roda duas vezes: uma respondendo SIM, outra respondendo NÃO.

⭐ **O critério da fase não é "apareceu o botão" — é o NÃO ser respeitado.** Uma
aprovação que o modelo contorna é pior que não ter aprovação, porque dá a impressão de
controle. Por isso a segunda rodada é a que importa.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.mcp.registro import FERRAMENTAS, Ferramenta  # noqa: E402
# ⚠️ As rotas entram ANTES das substituições abaixo: importar o serviço é o que registra
#    as ferramentas do produto, e trocar uma entrada antes disso seria trocar o que ainda
#    não existe — o registro do produto entraria por cima e o dublê nunca seria chamado.
from cicloassist.servico import rotas  # noqa: E402,F401
from cicloassist.servico.http import subir  # noqa: E402

#: O que a ferramenta de permissão recebeu, para inspeção depois.
RECEBIDO: list[dict] = []

#: A resposta que o "editor" dá nesta rodada.
DECISAO = {"permitir": True}

#: O que a ferramenta de escrita conseguiu fazer, se conseguiu.
ESCRITO: list[str] = []


def escrever_nota(texto: str) -> dict:
    ESCRITO.append(texto)
    return {"ok": True, "gravado": texto}


def pedir_confirmacao(**tudo) -> dict:
    """Registra TUDO o que chegou, e responde conforme a decisão da rodada.

    ⚠️ A forma da resposta é o que este spike existe para confirmar. A hipótese é o
    contrato do SDK: um objeto com `behavior` = `allow`/`deny`, e `updatedInput` no allow.
    Se estiver errado, o CLI dirá — e é isso que queremos ver antes de escrever produto.
    """
    RECEBIDO.append(tudo)
    print(f"\n  ⇢ pedir_confirmacao recebeu:\n    {json.dumps(tudo, ensure_ascii=False)[:600]}\n")

    if DECISAO["permitir"]:
        return {"behavior": "allow", "updatedInput": tudo.get("input", {})}
    return {"behavior": "deny", "message": "O editor recusou esta ação."}


# ⚠️⚠️ **Substituição declarada, não registro novo.** O decorador `@ferramenta` recusa
#    nome repetido de propósito (`registro.py`), e o `pedir_confirmacao` do produto já
#    está registrado quando este módulo importa o serviço. Este spike existe para medir o
#    CONTRATO do CLI com um dublê que mostra o que chegou — então ele troca a entrada do
#    registro na cara, em vez de tentar registrar por cima e morrer na importação.
#
# ⚠️ E o dublê guarda o comportamento ANTIGO (allow/deny na hora, decidido aqui). O portão
#    do produto não espera mais ninguém — ver ADR 0008 e `spikes/portao_sem_relogio.py`.
#    O que este spike ainda prova é o contrato: o que chega, o que o CLI aceita de volta,
#    e que o `deny` é respeitado de verdade.
FERRAMENTAS["escrever_nota"] = Ferramenta(
    nome="escrever_nota",
    descricao=(
        "Grava uma nota de texto no caderno do projeto. Use quando pedirem para anotar "
        "alguma coisa."
    ),
    esquema={
        "type": "object",
        "properties": {"texto": {"type": "string"}},
        "required": ["texto"],
    },
    funcao=escrever_nota,
    escreve=True,
)
FERRAMENTAS["pedir_confirmacao"] = Ferramenta(
    nome="pedir_confirmacao",
    descricao="Pergunta ao editor se uma ação pode acontecer.",
    esquema={"type": "object", "properties": {}, "additionalProperties": True},
    funcao=pedir_confirmacao,
    escreve=False,
)


def rodar(permitir: bool) -> dict:
    DECISAO["permitir"] = permitir
    RECEBIDO.clear()
    ESCRITO.clear()

    cli = shutil.which("claude")
    if not cli:
        sys.exit("claude não encontrado no PATH.")

    servidor = subir(0)   # porta livre: o serviço de verdade costuma estar em 7824
    porta = servidor.server_address[1]
    from cicloassist.servico.rotas import url_do_mcp  # noqa: F811

    try:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "mcp.json"
            config.write_text(
                json.dumps({"mcpServers": {"ciclo": {"type": "http",
                                                     "url": url_do_mcp(porta)}}}),
                encoding="utf-8",
            )
            comando = [
                cli, "-p",
                "Anote no caderno do projeto a frase: o portao funciona.",
                "--output-format", "stream-json", "--verbose",
                "--mcp-config", str(config), "--strict-mcp-config",
                "--restricted",
                # ⛔ Como o produto desde 2026-09-13: nenhuma ferramenta nativa. A pergunta
                #    é se o portão continua de pé sem elas (`o_que_o_restricted_deixa.py`).
                "--tools", "",
                "--model", "haiku",
                "--permission-prompts", "host",
                "--permission-prompt-tool", "mcp__ciclo__pedir_confirmacao",
                # ⚠️ A ferramenta de ESCRITA fica DE FORA da allowlist de propósito: é a
                # ausência dela aqui que faz o CLI perguntar.
                "--allowedTools", "mcp__ciclo__pedir_confirmacao",
            ]

            comeco = time.monotonic()
            proc = subprocess.Popen(
                comando, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            dito, negacoes = [], []
            for linha in proc.stdout:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    ev = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "assistant":
                    for b in ev.get("message", {}).get("content", []):
                        if b.get("type") == "text" and b.get("text"):
                            dito.append(b["text"])
                elif ev.get("type") == "result":
                    negacoes = ev.get("permission_denials", [])
            erro = proc.stderr.read()
            proc.wait()

            return {
                "permitiu": permitir,
                "perguntou": len(RECEBIDO),
                "escreveu": list(ESCRITO),
                "negacoes": negacoes,
                "resposta": " ".join(dito).strip()[:400],
                "erro": erro.strip()[:300],
                "segundos": round(time.monotonic() - comeco, 2),
            }
    finally:
        servidor.shutdown()
        servidor.server_close()


def main() -> int:
    print("=" * 70)
    print("RODADA 1 — o editor diz SIM")
    print("=" * 70)
    sim = rodar(permitir=True)
    print(f"  perguntou ....... {sim['perguntou']}x")
    print(f"  escreveu ........ {sim['escreveu']}")
    print(f"  resposta ........ {sim['resposta'][:200]}")
    print(f"  tempo ........... {sim['segundos']}s")
    if sim["erro"]:
        print(f"  stderr .......... {sim['erro']}")

    print()
    print("=" * 70)
    print("RODADA 2 — o editor diz NÃO   (o teste que importa)")
    print("=" * 70)
    nao = rodar(permitir=False)
    print(f"  perguntou ....... {nao['perguntou']}x")
    print(f"  escreveu ........ {nao['escreveu']}  ← precisa estar VAZIO")
    print(f"  negacoes ........ {nao['negacoes']}")
    print(f"  resposta ........ {nao['resposta'][:200]}")
    if nao["erro"]:
        print(f"  stderr .......... {nao['erro']}")

    print()
    passou = (
        sim["perguntou"] >= 1
        and sim["escreveu"]
        and nao["perguntou"] >= 1
        and not nao["escreveu"]
    )
    print(f"  {'PASSOU ✓' if passou else 'FALHOU ✗'} — "
          f"{'o sim escreve e o NÃO é respeitado' if passou else 'ver acima'}")
    return 0 if passou else 1


if __name__ == "__main__":
    raise SystemExit(main())
