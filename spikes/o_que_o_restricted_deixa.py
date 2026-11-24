"""Com `--restricted`, que ferramentas do PRÓPRIO CLI sobram — e o automático libera quais?

    python spikes/o_que_o_restricted_deixa.py

⛔ O ADR 0009 promete que o automático "muda quem responde ao portão, não quem passa por
ele". Mas o `pedir_confirmacao` respondia `allow` para QUALQUER `tool_name` — e o portão
não recebe só as nossas ferramentas: recebe toda ferramenta que não está na allowlist,
incluindo as do CLI. O ADR 0005 diz que o `--restricted` tira Bash, PowerShell, REPL e
WebFetch, e não diz o que FICA.

⭐ Custa zero turno: o CLI anuncia a lista no evento `system/init`, que sai antes do
primeiro pedido ao modelo. O spike lê essa linha e mata o processo.

Com as mesmas flags do `motor/claude.py`, menos o que depende do serviço no ar (o MCP
aponta um endereço morto — a lista do CLI não depende dele).

## O QUE ISTO MEDIU (2026-09-13, CLI 2.1.270)

| flags | nativas que o modelo vê |
|---|---|
| nenhuma | 36 |
| `--restricted` | ⛔ **29** — tirou só Bash, PowerShell, WebFetch, LSP, Monitor, CronCreate e RemoteTrigger; ficaram `Write`, `Edit`, `NotebookEdit`, `Read`, `Glob`, `Grep`, `Task`, `WebSearch`, `SendMessage` e outras |
| `--restricted --tools ""` (MCP no ar) | ✅ **0** — e as 18 nossas continuam |

E o `pedir_confirmacao` não aparece para o modelo: quem o chama é o CLI. O portão sem as
nativas foi conferido por `spikes/fase3_permissao.py` (o sim grava, o não é respeitado).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ferramentas(restrito: bool, nativas: str | None = None,
                url_mcp: str = "http://127.0.0.1:9/mcp/morto") -> tuple[list[str], str]:
    """A lista do `system/init`. `nativas` vai para `--tools` (`""` = nenhuma)."""
    cli = shutil.which("claude")
    if not cli:
        sys.exit("o CLI `claude` não está no PATH")
    config = Path(tempfile.gettempdir()) / "cicloassist-spike-mcp.json"
    config.write_text(json.dumps({"mcpServers": {"ciclo": {
        "type": "http", "url": url_mcp}}}), encoding="utf-8")
    comando = [
        cli, "-p", "responda apenas: ok",
        "--model", "haiku",
        "--output-format", "stream-json", "--verbose",
        "--mcp-config", str(config), "--strict-mcp-config",
        "--permission-prompts", "host",
        "--permission-prompt-tool", "mcp__ciclo__pedir_confirmacao",
    ]
    if restrito:
        comando.append("--restricted")
    if nativas is not None:
        comando += ["--tools", nativas]
    p = subprocess.Popen(comando, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace")
    versao = ""
    try:
        for linha in p.stdout:
            try:
                ev = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "system" and ev.get("subtype") == "init":
                versao = str(ev.get("claude_code_version") or "")
                return sorted(ev.get("tools") or []), versao
        return [], versao
    finally:
        # ⭐ Mata no init: nenhum turno do modelo é pago para ler a lista.
        p.kill()
        p.wait()


def main() -> int:
    sem, versao = ferramentas(restrito=False)
    com, _ = ferramentas(restrito=True)
    print(f"CLI {versao}")
    print(f"\nsem --restricted ({len(sem)}): {', '.join(sem)}")
    print(f"\ncom --restricted ({len(com)}): {', '.join(com)}")
    print(f"\no --restricted tirou: {', '.join(sorted(set(sem) - set(com))) or '(nada)'}")
    do_cli = [t for t in com if not t.startswith("mcp__")]
    print(f"\n⛔ sobram do PRÓPRIO CLI, e passam pelo portão: {', '.join(do_cli) or '(nenhuma)'}")

    # ⭐ O conserto medido: `--tools ""`, com o NOSSO MCP no ar — as nossas ferramentas
    #   têm de continuar na lista quando as nativas somem.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from cicloassist.mcp import ferramentas as _registra  # noqa: F401
    from cicloassist.servico.http import subir
    from cicloassist.servico.rotas import url_do_mcp
    servidor = subir()
    try:
        vivo, _ = ferramentas(restrito=True, nativas="",
                              url_mcp=url_do_mcp(servidor.server_address[1]))
    finally:
        servidor.shutdown()
    nossas = [t for t in vivo if t.startswith("mcp__ciclo__")]
    outras = [t for t in vivo if not t.startswith("mcp__ciclo__")]
    print(f'\ncom --restricted --tools "" e o MCP no ar: {len(vivo)} ferramentas')
    print(f"   nossas ({len(nossas)}): "
          f"{', '.join(t.removeprefix('mcp__ciclo__') for t in nossas)}")
    print(f"   do CLI ({len(outras)}): {', '.join(outras) or '(nenhuma)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
