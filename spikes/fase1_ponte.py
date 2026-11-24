"""Fase 1 (segunda metade) — o Claude responde o que só o projeto aberto sabe.

    python spikes/fase1_ponte.py

Exige o **Media Composer aberto com um projeto**. Sem isso o spike não roda, e não
adianta simular: o critério da fase é exatamente a ponte com o app vivo.

## Por que a pergunta é esta

O gabarito é calculado por nós, direto do Media Composer, **antes** de perguntar. Depois
comparamos. Um teste que aceitasse qualquer resposta plausível passaria com o modelo
inventando nomes de subclipe — e nomes de subclipe são exatamente o tipo de coisa que um
modelo inventa bem.
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

from cicloassist.avid.mcapi import McApiErro, MediaComposer  # noqa: E402
from cicloassist.mcp import ferramentas  # noqa: E402,F401  (registra por import)
from cicloassist.mcp.registro import somente_leitura  # noqa: E402
from cicloassist.servico.http import subir  # noqa: E402
from cicloassist.servico.rotas import url_do_mcp  # noqa: E402

BIN_ALVO = "C07.avb"

PERGUNTA = (
    "No projeto aberto do Avid, encontre a bin chamada C07 (não a C07_FALAS) e liste "
    "TODOS os itens dentro dela, incluindo masterclipes e subclipes. Responda apenas "
    "com os nomes, um por linha, sem numeração e sem comentário."
)


def gabarito() -> tuple[list[str], dict]:
    """A verdade, lida por nós direto do Media Composer."""
    with MediaComposer() as mc:
        projeto = mc.projeto()
        candidatas = [b for b in mc.bins() if b.endswith(BIN_ALVO)]
        if not candidatas:
            sys.exit(f"não achei uma bin {BIN_ALVO} no projeto aberto.")
        relativa = mc.caminho_relativo_da_bin(candidatas[0])
        itens = mc.itens_da_bin(relativa, tipos=("masterClips", "subclips"))
        return sorted(i.nome for i in itens), projeto


def main() -> int:
    cli = shutil.which("claude")
    if not cli:
        sys.exit("claude não encontrado no PATH (ADR 0001).")

    try:
        esperados, projeto = gabarito()
    except McApiErro as e:
        sys.exit(f"o Media Composer precisa estar aberto com um projeto.\n  {e}")

    print(f"projeto ......... {projeto['caminho']}")
    print(f"formato ......... {projeto['tipo']} @ {projeto['fps_aprox']}")
    print(f"gabarito ........ {len(esperados)} itens em {BIN_ALVO}")
    for nome in esperados:
        print(f"                  {nome}")
    print()

    servidor = subir()
    porta = servidor.server_address[1]

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
            "--mcp-config", str(config), "--strict-mcp-config",
            "--restricted",
            "--allowedTools", ",".join(somente_leitura()),
        ]

        comeco = time.monotonic()
        chamadas: list[str] = []
        dito: list[str] = []

        processo = subprocess.Popen(
            comando,
            stdin=subprocess.DEVNULL,
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
            if evento.get("type") != "assistant":
                continue
            for bloco in evento.get("message", {}).get("content", []):
                if bloco.get("type") == "tool_use":
                    chamadas.append(bloco.get("name", "?"))
                    print(f"  → {bloco.get('name')}  {json.dumps(bloco.get('input', {}), ensure_ascii=False)[:110]}")
                elif bloco.get("type") == "text" and bloco.get("text"):
                    dito.append(bloco["text"])

        erro = processo.stderr.read()
        processo.wait()
        servidor.shutdown()

        resposta = "\n".join(dito).strip()
        print(f"\n--- resposta do Claude ---\n{resposta}\n---")

        # O veredito é por CONJUNTO, não por texto: a ordem e a formatação são dele.
        # O que não pode é faltar nome nem sobrar nome inventado.
        ditos = {l.strip().strip("-*• ") for l in resposta.splitlines() if l.strip()}
        faltaram = [n for n in esperados if n not in ditos]
        inventados = [d for d in ditos if d not in esperados]

        nossas = [c for c in chamadas if c.startswith("mcp__ciclo__")]
        print(f"\n  chamadas nossas . {nossas}")
        print(f"  tempo ........... {time.monotonic() - comeco:.2f} s")
        print(f"  faltaram ........ {faltaram or 'nenhum'}")
        print(f"  inventados ...... {inventados or 'nenhum'}")
        if erro.strip():
            print(f"  stderr .......... {erro.strip()[:200]}")

        passou = not faltaram and not inventados and bool(nossas)
        print(f"\n  {'PASSOU ✓' if passou else 'FALHOU ✗'} — o Claude "
              f"{'leu' if passou else 'NÃO leu'} o projeto aberto")
        return 0 if passou else 1


if __name__ == "__main__":
    raise SystemExit(main())
