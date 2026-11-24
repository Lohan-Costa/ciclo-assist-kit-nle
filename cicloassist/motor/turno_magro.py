"""O TURNO MAGRO: uma pergunta, uma resposta, sem ferramenta e sem histórico. A peça comum dos agentes conselheiros.

Nasceu no `motor/conselho.py`, onde foi medido: o turno da conversa custou 116 mil tokens para pular um passo; magro, ~2 mil
(2026-11-01). Quem chama diz a instrução e o pedido, e recebe o texto: o que fazer com ele é de quem chamou.

- `--system-prompt` próprio, `--strict-mcp-config` sem servidor, `--restricted` e `--tools ""`: nenhuma ferramenta, nenhuma conversa.
  ⛔ O `--restricted` sozinho deixa Write/Edit/Read (medido, `CLAUDE.md`).
- Modelo local vai direto ao Ollama do Mac, com o raciocínio desligado (`_pela_ollama`).
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from ..servico import config as _config
from .claude import MotorIndisponivel, achar_o_cli, ambiente_do_modelo

log = logging.getLogger("cicloassist.motor.turno_magro")

PRAZO_S = 120.0


class TurnoFalhou(RuntimeError):
    """Sem IA disponível, sem resposta, ou resposta que não dá para ler."""


@dataclass(frozen=True)
class Resposta:
    texto: str
    uso: dict[str, Any] = field(default_factory=dict)
    segundos: float = 0.0


def _pela_ollama(pedido: str, modelo: str, instrucao: str, prazo: float) -> tuple[str, dict[str, Any]]:
    """Um modelo LOCAL direto no Ollama do Mac, com o raciocínio DESLIGADO.

    ⛔⛔ MEDIDO (2026-11-02, Qwen3.5 4B): pelo `claude -p` o modelo pensa sempre (550–620 tokens de saída, 22–33 s); direto com
    `think: false`: 79 tokens, 3,9 s. Sem ferramenta, não há por que passar pelo CLI."""
    import urllib.request

    from . import percepcao as _percepcao
    url = _percepcao.endereco()
    if not url:
        raise TurnoFalhou("o modelo roda no Mac, e o endereço do Mac não está configurado")
    corpo = {"model": modelo.removeprefix(_config.LOCAL), "stream": False, "think": False, "format": "json",
             "keep_alive": "30m",
             "messages": [{"role": "system", "content": instrucao}, {"role": "user", "content": pedido}]}
    pedido_http = urllib.request.Request(url.rstrip("/") + "/api/chat", method="POST",
                                         data=json.dumps(corpo).encode())
    try:
        with urllib.request.urlopen(pedido_http, timeout=prazo) as r:
            d = json.loads(r.read())
    except (OSError, ValueError) as e:
        raise TurnoFalhou(f"o Ollama do Mac não respondeu: {e}") from e
    texto = str((d.get("message") or {}).get("content") or "")
    entrada, saida = int(d.get("prompt_eval_count") or 0), int(d.get("eval_count") or 0)
    return texto, {"entrada": entrada, "saida": saida, "tokens": entrada + saida, "modelo": corpo["model"],
                   "custo_usd": 0.0}


def _uso(evento: dict) -> dict[str, Any]:
    from .decupador import _uso_do_result
    return _uso_do_result(evento)


def chamar(instrucao: str, pedido: str, modelo: str | None = None, prazo: float = PRAZO_S) -> Resposta:
    """Um turno, sem ferramenta. `TurnoFalhou` se não houver como responder."""
    modelo = _config.modelo_guardado() if modelo is None else modelo
    comeco = time.monotonic()
    if _config.e_local(modelo):
        texto, uso = _pela_ollama(pedido, modelo, instrucao, prazo)
        return Resposta(texto, uso, round(time.monotonic() - comeco, 1))
    try:
        nome_do_modelo, ambiente = ambiente_do_modelo(modelo)
        cli = achar_o_cli()
    except MotorIndisponivel as e:
        raise TurnoFalhou(str(e)) from e
    comando = [cli, "-p", pedido,
               "--system-prompt", instrucao,
               "--output-format", "stream-json", "--verbose",
               "--strict-mcp-config",
               "--restricted",
               "--tools", ""]
    if nome_do_modelo:
        comando += ["--model", nome_do_modelo]
    try:
        # ⭐ `run` (communicate) lê stdout e stderr juntos: sem o buffer cheio que trava o CLI.
        r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, timeout=prazo, env=ambiente,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise TurnoFalhou(f"o modelo não respondeu em {prazo:.0f} s") from None
    texto, uso, veio = "", {}, False
    for linha in r.stdout.splitlines():
        try:
            evento = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if evento.get("type") == "result":
            veio, uso = True, _uso(evento)
            texto = str(evento.get("result") or "")
    if not veio:
        motivo = " | ".join(r.stderr.strip().splitlines()[-5:]) or f"saiu com código {r.returncode}"
        raise TurnoFalhou(f"o Claude encerrou sem responder: {motivo[-400:]}")
    return Resposta(texto, uso, round(time.monotonic() - comeco, 1))


def objeto_json(texto: str) -> dict[str, Any]:
    """O objeto JSON de uma resposta, com ou sem cerca. Texto de modelo é entrada não confiável."""
    bruto = (texto or "").strip()
    cerca = re.search(r"```(?:json)?\s*(.+?)```", bruto, re.S)
    if cerca:
        bruto = cerca.group(1).strip()
    abre, fim = bruto.find("{"), bruto.rfind("}")
    if abre < 0 or fim < abre:
        raise TurnoFalhou("o modelo não respondeu em JSON")
    try:
        dados = json.loads(bruto[abre:fim + 1])
    except json.JSONDecodeError as e:
        raise TurnoFalhou(f"JSON inválido na resposta: {e}") from None
    if not isinstance(dados, dict):
        raise TurnoFalhou("a resposta não veio como objeto JSON")
    return dados
