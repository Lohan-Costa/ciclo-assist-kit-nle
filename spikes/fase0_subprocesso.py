"""Fase 0 — provar que o subprocesso do Claude responde, e medir quanto custa.

Sem painel, sem MCP, sem Avid. É o elo mais arriscado do produto inteiro: se o
`claude -p` não sobe com a credencial da assinatura do editor, nada do resto existe.

    python spikes/fase0_subprocesso.py "responda apenas: ok"

O que este spike responde, e que nenhum outro teste responde:

1. O CLI sobe no Windows com a assinatura, sem chave de API?  (`apiKeySource`)
2. Quanto tempo até o primeiro token?                          (ttft)
3. As flags de contenção fazem o que dizem?                    (tools / mcp_servers)
4. O processo morre limpo?                                     (returncode)

⚠️ Este arquivo é EVIDÊNCIA, não biblioteca. `cicloassist/motor/claude.py` é a versão de
produção; aqui a leitura é síncrona e o objetivo é imprimir, não integrar.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time

# ⚠️ Windows: o console herda cp1252 e QUALQUER acento ou seta derruba o processo com
# UnicodeEncodeError — no meio da execução, não na partida. Medido em 2026-09-10 na
# primeira rodada deste spike. Vale para todo processo nosso que imprime em português,
# e é por isso que mora aqui em cima e não numa função de setup que alguém esquece de
# chamar. O `errors="replace"` na leitura do subprocesso resolve a outra ponta.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# As quatro flags que nunca saem. Ver ADR 0002 e ADR 0005 — as duas primeiras são
# contenção de segurança, não higiene de configuração.
FLAGS_DE_CONTENCAO = [
    "--restricted",           # sem Bash/PowerShell/REPL/WebFetch na estação do editor
    "--strict-mcp-config",    # sem os MCP servers da conta pessoal do usuário
]

# ⚠️ `--verbose` é EXIGIDO junto de `--output-format stream-json` em modo print.
# Sem ele o CLI recusa a combinação — não é opcional nem é ruído.
FLAGS_DE_STREAM = [
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--verbose",
]


def achar_o_cli() -> str:
    """O caminho do `claude`, ou a explicação de por que não há um.

    No Windows o executável é um shim `.cmd`; o `shutil.which` resolve os dois casos e
    evita depender de `shell=True`, que traria a linha de comando para dentro do parser
    do cmd.exe — onde um caminho de projeto com espaço vira dois argumentos.
    """
    caminho = shutil.which("claude")
    if not caminho:
        sys.exit(
            "claude não encontrado no PATH.\n"
            "O produto depende do Claude Code instalado na máquina do editor (ADR 0001)."
        )
    return caminho


def rodar(pergunta: str) -> int:
    cli = achar_o_cli()
    comando = [cli, "-p", pergunta, *FLAGS_DE_STREAM, *FLAGS_DE_CONTENCAO]

    print(f"→ {cli}")
    print(f"→ flags: {' '.join(FLAGS_DE_STREAM + FLAGS_DE_CONTENCAO)}\n")

    comeco = time.monotonic()
    primeiro_token: float | None = None
    resposta: list[str] = []

    processo = subprocess.Popen(
        comando,
        # ⚠️⚠️ MEDIDO 2026-09-10, e custa 3,2 s se esquecido. Sem fechar o stdin, o CLI
        # espera 3 s por dados que nunca vêm ("no stdin data received in 3s") ANTES de
        # começar o turno: o primeiro token saiu em 4,84 s em vez de 1,6 s. O sintoma
        # engana — parece lentidão de modelo, e sai no stderr, que ninguém lê.
        # Na fase 4, com `--input-format stream-json`, o stdin passa a ser PIPE de
        # verdade e a espera some por outro motivo: aí há dados. Aqui, não há.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,  # linha a linha: sem isto o "tempo real" vira um bloco no fim
    )

    for linha in processo.stdout:
        linha = linha.strip()
        if not linha:
            continue
        try:
            evento = json.loads(linha)
        except json.JSONDecodeError:
            # Não engolir: uma linha que não é JSON no stdout é sintoma, não ruído.
            print(f"  [não-JSON] {linha[:160]}")
            continue

        tipo = evento.get("type")

        if tipo == "system" and evento.get("subtype") == "init":
            ferramentas = evento.get("tools", [])
            servidores = evento.get("mcp_servers", [])
            print(f"  sessão .......... {evento.get('session_id')}")
            print(f"  modelo .......... {evento.get('model')}")
            print(f"  credencial ...... apiKeySource={evento.get('apiKeySource')!r}")
            print(f"  ferramentas ..... {len(ferramentas)}")
            print(f"  mcp servers ..... {len(servidores)} {[s['name'] for s in servidores]}")

            # A prova de que --restricted não é decorativa.
            perigosas = [f for f in ferramentas if f in ("Bash", "PowerShell", "WebFetch")]
            veredito = "REMOVIDAS ✓" if not perigosas else f"AINDA PRESENTES ✗ {perigosas}"
            print(f"  execução ........ {veredito}")
            if servidores:
                print("  ⚠️  MCP de terceiro na sessão apesar de --strict-mcp-config")
            print()

        elif tipo == "rate_limit_event":
            info = evento.get("rate_limit_info", {})
            janelas = info.get("unifiedWindows", {})
            uso = {k: v.get("utilization") for k, v in janelas.items()}
            print(f"  limite .......... {info.get('status')} · uso={uso}\n")

        elif tipo == "stream_event":
            interno = evento.get("event", {})
            if interno.get("type") == "content_block_delta":
                texto = interno.get("delta", {}).get("text", "")
                if texto:
                    if primeiro_token is None:
                        primeiro_token = time.monotonic() - comeco
                    resposta.append(texto)
                    print(texto, end="", flush=True)

        elif tipo == "result":
            total = time.monotonic() - comeco
            print("\n")
            print(f"  primeiro token .. {primeiro_token:.2f} s" if primeiro_token
                  else "  primeiro token .. nenhum")
            print(f"  turno completo .. {total:.2f} s")
            print(f"  erro? ........... {evento.get('is_error')}")
            print(f"  encerramento .... {evento.get('terminal_reason')}")

    erro = processo.stderr.read()
    codigo = processo.wait()
    if erro.strip():
        print(f"\n  stderr:\n{erro}")
    print(f"  returncode ...... {codigo} {'✓ limpo' if codigo == 0 else '✗'}")
    return codigo


if __name__ == "__main__":
    pergunta = sys.argv[1] if len(sys.argv) > 1 else "responda apenas: ok"
    raise SystemExit(rodar(pergunta))
