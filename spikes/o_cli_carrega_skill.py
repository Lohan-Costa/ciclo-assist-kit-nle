"""Spike — o `claude -p` do produto carrega uma SKILL nossa?

    python spikes/o_cli_carrega_skill.py

## Por que isto vem antes de escrever qualquer skill

O ofício de montagem hoje mora todo na PERSONA — uma string só, que cresce a cada regra e
é enviada em todo turno, sobre qualquer assunto. O formato `SKILL.md` resolve isso
(carrega por condição, e não sempre), e o estudo do Jumper mostra que é assim que um
produto de pós-produção sério empacota conhecimento.

⚠️ Mas o nosso `claude -p` não é um Claude Code qualquer: ele roda com `--restricted`,
`--strict-mcp-config` e `--allowedTools` limitado às NOSSAS ferramentas. Três perguntas
precisam de resposta ANTES de escrever a primeira skill, e nenhuma delas se responde por
leitura de documentação:

1. o CLI acha skill no diretório de trabalho que a gente escolher?
2. `--restricted` deixa?
3. com `--allowedTools` só das nossas, a ferramenta `Skill` ainda pode ser chamada?

A skill de teste manda o modelo terminar a resposta com uma palavra improvável. Se a
palavra aparecer, a skill foi lida.
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

SENHA = "JABUTICABA"

SKILL = f"""---
name: teste-do-ciclo
description: >
  MUST be loaded when the user asks anything at all, including a greeting.
  It defines how every answer must end.
---

Termine TODA resposta com a palavra {SENHA} em maiúsculas, sozinha na última linha.
Não explique por quê.
"""


def rodar(cli: str, pasta: Path, *extras: str, restrito: bool = True) -> tuple[bool, str]:
    comando = [cli, "-p", "Diga apenas: oi.", "--output-format", "json"]
    if restrito:
        comando.append("--restricted")
    comando += list(extras)
    r = subprocess.run(comando, cwd=str(pasta), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180,
                       stdin=subprocess.DEVNULL)
    texto = r.stdout or ""
    try:
        texto = json.loads(texto).get("result") or texto
    except json.JSONDecodeError:
        pass
    return SENHA in texto, texto.strip().replace("\n", " ")[:90]


def main() -> int:
    cli = achar_o_cli()

    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)
        alvo = pasta / ".claude" / "skills" / "teste-do-ciclo"
        alvo.mkdir(parents=True)
        (alvo / "SKILL.md").write_text(SKILL, encoding="utf-8")
        print(f"skill em {alvo}\n")

        casos = [
            ("cwd com a skill, --restricted", (), True),
            ("+ --allowedTools só das nossas", ("--allowedTools", "mcp__ciclo__transcrever"), True),
            ("+ --setting-sources project", ("--setting-sources", "project"), True),
            ("sem --restricted", (), False),
            ("⛔ controle: pasta SEM skill", ("--add-dir", str(pasta)), True),
        ]

        print(f"{'caso':<38}{'leu?':<7}resposta")
        print("-" * 78)
        for rotulo, extras, restrito in casos:
            onde = pasta
            if rotulo.startswith("⛔"):
                onde = Path(tmp).parent          # uma pasta qualquer, sem .claude
            try:
                leu, amostra = rodar(cli, onde, *extras, restrito=restrito)
            except subprocess.TimeoutExpired:
                leu, amostra = False, "(estourou o prazo)"
            print(f"{rotulo:<38}{'SIM' if leu else 'não':<7}{amostra}")

    print("\n⇒ 'SIM' na primeira linha quer dizer que dá para embarcar skills do produto "
          "sem abrir mão do --restricted. 'não' em todas quer dizer que o ofício continua "
          "na persona, e a decisão muda.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
