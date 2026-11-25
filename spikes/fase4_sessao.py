"""Fase 4, spike — um processo VIVO aguenta vários turnos, e a sessão volta?

    python spikes/fase4_sessao.py

Três perguntas que o `--help` não responde e que decidem o desenho:

1. Qual é o formato exato de uma mensagem no `--input-format stream-json`?
2. O processo sobrevive entre turnos, e o segundo turno **lembra** do primeiro?
3. `--resume` num processo NOVO recupera o fio de uma sessão encerrada?

⭐ A terceira é a que vale o produto: o editor fecha o Media Composer hoje e reabre amanhã.
Se o `--resume` não trouxer o fio, a fase 4 vira só "processo vivo enquanto a janela está
aberta", que é bem menos.

⚠️ Sem MCP e sem Avid de propósito — aqui se mede o transporte, não a integração.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = ["--output-format", "stream-json", "--verbose", "--restricted",
        "--strict-mcp-config"]


def subir(sessao: str, retomar: bool = False) -> subprocess.Popen:
    cli = shutil.which("claude")
    if not cli:
        sys.exit("claude não encontrado no PATH.")
    comando = [cli, "-p", *BASE, "--input-format", "stream-json"]
    # ⚠️ `--resume` e `--session-id` são EXCLUDENTES: o resume já diz qual sessão é.
    comando += ["--resume", sessao] if retomar else ["--session-id", sessao]
    return subprocess.Popen(
        comando,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )


def perguntar(proc: subprocess.Popen, texto: str) -> tuple[str, float]:
    """Escreve um turno no stdin e lê até o `result`. Devolve (resposta, segundos)."""
    mensagem = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": texto}]},
    }
    comeco = time.monotonic()
    proc.stdin.write(json.dumps(mensagem, ensure_ascii=False) + "\n")
    proc.stdin.flush()

    partes = []
    for linha in proc.stdout:
        linha = linha.strip()
        if not linha:
            continue
        try:
            evento = json.loads(linha)
        except json.JSONDecodeError:
            continue
        tipo = evento.get("type")
        if tipo == "assistant":
            for b in evento.get("message", {}).get("content", []):
                if b.get("type") == "text" and b.get("text"):
                    partes.append(b["text"])
        elif tipo == "result":
            # ⭐ O `result` fecha o TURNO, não o processo — é a diferença que a fase 4
            #    inteira explora.
            return " ".join(partes).strip(), round(time.monotonic() - comeco, 2)
    return " ".join(partes).strip(), round(time.monotonic() - comeco, 2)


def main() -> int:
    # ⭐ A sessão é derivada do caminho do projeto, de forma determinística: abrir o mesmo
    #    projeto amanhã dá o mesmo id, sem guardar mapa nenhum em lugar nenhum.
    projeto = r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR"
    sessao = str(uuid.uuid5(uuid.NAMESPACE_URL, "cicloassist:" + projeto.lower()))
    print(f"projeto ..... {projeto}")
    print(f"sessão ...... {sessao}  (derivada, não sorteada)\n")

    print("=" * 68)
    print("PROCESSO VIVO — dois turnos no mesmo processo")
    print("=" * 68)
    proc = subir(sessao)
    try:
        r1, t1 = perguntar(proc, "Guarde este número: 4718. Responda apenas 'anotado'.")
        print(f"  turno 1 ({t1}s): {r1[:90]}")
        r2, t2 = perguntar(proc, "Qual era o número? Responda só o número.")
        print(f"  turno 2 ({t2}s): {r2[:90]}")
        lembrou = "4718" in r2
        print(f"  lembrou no mesmo processo: {'SIM ✓' if lembrou else 'NÃO ✗'}")
        print(f"  ⭐ 2º turno foi {t1/max(t2,0.01):.1f}x mais rápido (sem subir processo)")
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
        print(f"  processo encerrou: returncode={proc.returncode}")

    print()
    print("=" * 68)
    print("RESUME — processo NOVO, mesma sessão")
    print("=" * 68)
    proc2 = subir(sessao, retomar=True)
    try:
        r3, t3 = perguntar(proc2, "Qual era o número que pedi para guardar? Só o número.")
        print(f"  turno 3 ({t3}s): {r3[:90]}")
        retomou = "4718" in r3
        print(f"  recuperou o fio: {'SIM ✓' if retomou else 'NÃO ✗'}")
    finally:
        erro = ""
        try:
            proc2.stdin.close()
            proc2.wait(timeout=30)
            erro = proc2.stderr.read()
        except Exception:
            proc2.kill()
        if erro.strip():
            print(f"  stderr: {erro.strip()[:300]}")

    passou = lembrou and retomou
    print(f"\n  {'PASSOU ✓' if passou else 'FALHOU ✗'} — "
          f"{'processo vivo lembra E o resume traz o fio de volta' if passou else 'ver acima'}")
    return 0 if passou else 1


if __name__ == "__main__":
    raise SystemExit(main())
