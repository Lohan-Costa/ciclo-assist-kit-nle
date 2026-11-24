"""Fase 1 (primeira metade) — provar que o Claude alcança o NOSSO servidor MCP.

    python spikes/fase1_mcp.py

Sobe o servidor MCP em 127.0.0.1, escreve o `--mcp-config`, e pede ao Claude o carimbo
sorteado quando o serviço subiu. O carimbo é a prova: o modelo não tem como adivinhar
um valor sorteado do outro lado da ponte.

⚠️ **A segunda metade da fase 1 não está aqui, e não pode estar.** O critério de pronto
é o Claude responder uma pergunta que SÓ O PROJETO ABERTO sabe responder — e isso exige
o Media Composer rodando, com um projeto. Este spike prova o transporte; falta a ponte.
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

from cicloassist.mcp import ferramentas  # noqa: E402,F401  (registra por import)
from cicloassist.mcp.registro import somente_leitura  # noqa: E402
from cicloassist.servico.http import subir  # noqa: E402
from cicloassist.servico.rotas import url_do_mcp  # noqa: E402
from cicloassist.mcp.ferramentas.sonda import CARIMBO  # noqa: E402

PERGUNTA = (
    "Chame a ferramenta carimbo_do_servico e responda APENAS o valor do campo carimbo, "
    "sem nenhuma outra palavra."
)


def main() -> int:
    cli = shutil.which("claude")
    if not cli:
        sys.exit("claude não encontrado no PATH (ADR 0001).")

    servidor = subir()
    porta = servidor.server_address[1]
    print(f"servidor MCP em 127.0.0.1:{porta}")
    print(f"carimbo sorteado: {CARIMBO}\n")

    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "mcp.json"
        config.write_text(
            json.dumps({"mcpServers": {"ciclo": {"type": "http",
                                                 "url": url_do_mcp(porta)}}}),
            encoding="utf-8",
        )

        comando = [
            cli, "-p", PERGUNTA,
            "--output-format", "stream-json", "--include-partial-messages", "--verbose",
            "--mcp-config", str(config),
            "--strict-mcp-config",          # ADR 0002: só as NOSSAS ferramentas
            "--restricted",                 # ADR 0005
            # ADR 0003: leitura entra na allowlist e nunca pergunta.
            "--allowedTools", ",".join(somente_leitura()),
        ]

        comeco = time.monotonic()
        chamadas: list[str] = []
        resposta: list[str] = []
        conectou = None

        processo = subprocess.Popen(
            comando,
            stdin=subprocess.DEVNULL,       # ADR 0001: sem isto, 3 s de espera à toa
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )

        for linha in processo.stdout:
            linha = linha.strip()
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                continue

            tipo = evento.get("type")

            if tipo == "system" and evento.get("subtype") == "init":
                servidores = evento.get("mcp_servers", [])
                nossas = [t for t in evento.get("tools", []) if t.startswith("mcp__")]
                conectou = servidores
                print(f"  mcp servers ..... {servidores}")
                print(f"  ferramentas mcp . {nossas}\n")

            elif tipo == "assistant":
                for bloco in evento.get("message", {}).get("content", []):
                    if bloco.get("type") == "tool_use":
                        chamadas.append(bloco.get("name", "?"))
                        print(f"  → chamou {bloco.get('name')}")
                    elif bloco.get("type") == "text" and bloco.get("text"):
                        resposta.append(bloco["text"])

            elif tipo == "result":
                pass

        erro = processo.stderr.read()
        processo.wait()
        servidor.shutdown()

        dito = " ".join(resposta).strip()
        print(f"\n  resposta ........ {dito!r}")
        print(f"  esperado ........ {CARIMBO!r}")
        print(f"  chamadas ........ {chamadas}")
        print(f"  tempo ........... {time.monotonic() - comeco:.2f} s")
        if erro.strip():
            print(f"  stderr .......... {erro.strip()[:300]}")

        # O veredito é o carimbo, não a chamada: uma chamada que aconteceu mas cujo
        # valor não voltou ao editor é uma ponte que existe e não serve.
        passou = CARIMBO in dito
        print(f"\n  {'PASSOU ✓' if passou else 'FALHOU ✗'}"
              f"  — o Claude {'alcançou' if passou else 'NÃO alcançou'} o nosso servidor")
        if conectou is not None and len(conectou) != 1:
            print("  ⚠️  esperado exatamente 1 servidor MCP (o nosso)")
        return 0 if passou else 1


if __name__ == "__main__":
    raise SystemExit(main())
