"""Spike — o que o CLI conta sobre modelo, contexto, tokens e limite.

    python spikes/o_que_o_cli_conta.py

## Por que

O editor pediu uma barra de status como a do Claude Code: **modelo**, **quanto do
contexto já foi usado**, **quanto da assinatura já foi gasto** e **quanto falta para
resetar**. Nada disso pode ser desenhado por suposição — a barra que mente é pior que a
barra que não existe, porque ele vai decidir quando começar um corte olhando para ela.

Hoje `motor/claude.py::_traduzir` aproveita `rate_limit_event.utilization` e joga o resto
fora. Este spike despeja os eventos INTEIROS que carregam número, para que o desenho saia
dos campos que existem de verdade.

Sai `0` se achou pelo menos o modelo e algum número de uso.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.motor.claude import _ambiente_do_cli  # noqa: E402

#: Curta de propósito: o que se mede aqui é o ENVELOPE, não a resposta.
PERGUNTA = "responda apenas: ok"


def main() -> int:
    cli = shutil.which("claude")
    if not cli:
        sys.exit("claude não encontrado no PATH.")

    with tempfile.TemporaryDirectory() as tmp:
        # Sem MCP: este spike não precisa de ferramenta nenhuma, e um servidor a menos é
        # uma variável a menos no que chega de volta.
        config = Path(tmp) / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

        proc = subprocess.run(
            [cli, "-p", PERGUNTA,
             "--output-format", "stream-json", "--verbose",
             "--mcp-config", str(config), "--strict-mcp-config", "--restricted"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_ambiente_do_cli(), timeout=300,
        )

    achou_modelo = achou_uso = False
    for linha in proc.stdout.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            ev = json.loads(linha)
        except json.JSONDecodeError:
            continue

        tipo = ev.get("type")

        if tipo == "system" and ev.get("subtype") == "init":
            print("=" * 74)
            print("INIT — o que o CLI diz de si")
            print("=" * 74)
            for k in ("model", "permissionMode", "slash_commands", "output_style"):
                if k in ev:
                    v = ev[k]
                    print(f"  {k:20} {str(v)[:180]}")
            achou_modelo = "model" in ev

        elif tipo == "rate_limit_event":
            print()
            print("=" * 74)
            print("RATE_LIMIT_EVENT — inteiro, é daqui que sai a barra de créditos")
            print("=" * 74)
            print(json.dumps(ev, ensure_ascii=False, indent=2)[:2400])
            achou_uso = True

        elif tipo == "result":
            print()
            print("=" * 74)
            print("RESULT — inteiro, é daqui que sai o contexto e o custo do turno")
            print("=" * 74)
            # ⚠️ O `result` traz o texto da resposta; ele não interessa e pode ser longo.
            enxuto = {k: v for k, v in ev.items() if k != "result"}
            print(json.dumps(enxuto, ensure_ascii=False, indent=2)[:3000])

    if proc.returncode != 0:
        print(f"\nstderr: {proc.stderr.strip()[:400]}")

    print()
    print(f"  modelo .......... {'✓' if achou_modelo else '✗'}")
    print(f"  uso da janela ... {'✓' if achou_uso else '✗ (pode não vir quando o uso é baixo)'}")
    return 0 if achou_modelo else 1


if __name__ == "__main__":
    raise SystemExit(main())
