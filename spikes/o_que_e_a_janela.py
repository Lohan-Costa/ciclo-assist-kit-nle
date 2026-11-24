"""Spike — o `result` do CLI soma o turno INTEIRO, e isso não é a janela de contexto.

    python spikes/o_que_e_a_janela.py      (exige o serviço no ar)

## O que motivou

Em campo, 2026-09-11, a barra do painel mostrou **186%**, **284%** e **200%** de janela de
contexto — com Haiku e com Sonnet. Uma janela não pode passar de 100%: ou o denominador
está errado, ou o numerador não é o que a gente pensa.

## A hipótese

`result.modelUsage[<modelo>]` traz `inputTokens + cacheReadInputTokens +
cacheCreationInputTokens` **somados sobre TODAS as requisições do turno**. Um turno com dez
chamadas de ferramenta faz onze requisições, e cada uma reenvia a conversa inteira — então
a soma é múltipla da janela, por desenho. Ela é a conta do GASTO, não da ocupação.

⇒ A ocupação da janela é o `input` da ÚLTIMA requisição, que chega nos eventos ao vivo
(`message_start`), não no `result`.

Este spike mede as duas coisas no mesmo turno e imprime lado a lado.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.motor.claude import achar_o_cli  # noqa: E402
from cicloassist.servico import rotas  # noqa: E402,F401  (registra as rotas)

#: Uma pergunta que OBRIGA várias chamadas de ferramenta — é onde o defeito aparece.
PERGUNTA = ("Liste as bins do projeto e, para a bin da cena C07, liste os itens. "
            "Depois diga em que formato o projeto está. Responda em uma linha.")


def main() -> int:
    cli = achar_o_cli()
    url = rotas.url_do_mcp()
    print(f"MCP em {url}\n⚠️ O serviço precisa estar no ar NESTE processo? Não — este "
          f"spike sobe o seu próprio segredo, então rode-o sozinho.\n")

    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "mcp.json"
        config.write_text(
            json.dumps({"mcpServers": {"ciclo": {"type": "http", "url": url}}}),
            encoding="utf-8")

        comando = [
            cli, "-p", PERGUNTA,
            "--output-format", "stream-json", "--include-partial-messages", "--verbose",
            "--mcp-config", str(config), "--strict-mcp-config", "--restricted",
        ]
        processo = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
            bufsize=1)

        ao_vivo: list[int] = []
        janela = 0
        soma_do_result = 0
        for linha in processo.stdout:
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                continue

            if evento.get("type") == "stream_event":
                interno = evento.get("event", {})
                if interno.get("type") == "message_start":
                    u = (interno.get("message") or {}).get("usage") or {}
                    contexto = ((u.get("input_tokens") or 0)
                                + (u.get("cache_read_input_tokens") or 0)
                                + (u.get("cache_creation_input_tokens") or 0))
                    if contexto:
                        ao_vivo.append(contexto)
                        print(f"  requisição {len(ao_vivo)}: {contexto:>8,} de contexto")

            elif evento.get("type") == "result":
                for modelo, u in (evento.get("modelUsage") or {}).items():
                    janela = u.get("contextWindow") or 0
                    soma_do_result = ((u.get("inputTokens") or 0)
                                      + (u.get("cacheReadInputTokens") or 0)
                                      + (u.get("cacheCreationInputTokens") or 0))
                    print(f"\nmodelo: {modelo}  janela: {janela:,}")

        processo.wait(timeout=120)

    if not janela or not ao_vivo:
        print("⚠️ não deu para medir (turno sem uso relatado)")
        return 1

    ultimo = ao_vivo[-1]
    maior = max(ao_vivo)
    print(f"\n{'requisições no turno':<28}{len(ao_vivo)}")
    print(f"{'soma do result':<28}{soma_do_result:>10,}  → {soma_do_result / janela:.0%} "
          f"da janela  {'⛔ PASSA DE 100%' if soma_do_result > janela else ''}")
    print(f"{'maior requisição':<28}{maior:>10,}  → {maior / janela:.0%} da janela")
    print(f"{'última requisição':<28}{ultimo:>10,}  → {ultimo / janela:.0%} da janela  "
          f"← ⭐ é ESTA a ocupação")

    if soma_do_result > janela:
        print("\n⇒ CONFIRMADO: a soma do `result` não é a ocupação da janela. Ela é o "
              "gasto do turno — cada chamada de ferramenta reenvia a conversa inteira.")
    else:
        print("\n⇒ Neste turno a soma coube na janela (poucas ferramentas). Repita com "
              "uma pergunta que chame mais ferramentas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
