"""A ponte com o Premiere — desde a fase 4 (2026-11-07), pelo NÚCLEO do Ciclo Assist.

⭐ Era o porte do `ponte_premiere.rs` do ex-Órbita: uma extensão invisível SÓ do Sincronizar (`com.orbita.ponte`) buscava
pedidos por long-poll aqui. Hoje há UMA extensão no Premiere, a do Assist, que carrega o ExtendScript dos três módulos
(`cicloassist/nle/premiere::host_jsx_inteiro`); este servidor pede a ela por `POST /nucleo/premiere/chamar` (na 7824,
com o token do núcleo) e guarda o resultado para quem pediu buscar em `/premiere/resultado?id=` — a INTERFACE da
página da Preparar não mudou.
⛔ A expressão é conferida AQUI (só função `sinc*`), e o núcleo confere de novo pelo prefixo do módulo; cada argumento
vira literal JSON. Texto livre virando ExtendScript seria um shell no Premiere do editor.
⚠️ Falha (Premiere fechado, núcleo fora) volta como `err|<motivo>` — a convenção das funções `sinc*`, que a página
já trata como falha e mostra.
"""
from __future__ import annotations

import json
import re
import threading
import time
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

#: a porta e o arquivo do token do núcleo (o Assist): `cicloassist/servico/nucleo.py`
PORTA_DO_NUCLEO = 7824
TOKEN_DO_NUCLEO = "plugin-token"  # o token ÚNICO do Ciclo Assist
HEADER_DO_NUCLEO = "X-Ciclo-Token"
#: o prazo de uma chamada no Premiere (uma montagem de sequência leva minutos)
PRAZO = 600.0
GUARDA_DO_RESULTADO = 300.0
#: quanto vale a última resposta do `viva()` (a Preparar pergunta a cada batida)
VIVA_CACHE = 2.0
_NOME = re.compile(r"sinc[A-Za-z0-9_]*\Z")

_cv = threading.Condition()
_resultados: dict[int, tuple[float, Optional[str]]] = {}
_proximo_id = 0
_viva: tuple[float, bool] = (float("-inf"), False)


def _zerar() -> None:
    """Só para os testes."""
    global _proximo_id, _viva
    with _cv:
        _resultados.clear()
        _proximo_id = 0
        _viva = (float("-inf"), False)


def pasta_do_ciclo() -> Path:
    """A pasta de dados do Ciclo Assist, onde o núcleo publica o token: `CICLOASSIST_DADOS`, senão a mãe da do módulo."""
    import segredo
    explicita = os.environ.get("CICLOASSIST_DADOS")
    return Path(explicita) if explicita else segredo.pasta_de_dados().parent


def _nucleo(metodo: str, rota: str, corpo: Optional[dict] = None, prazo: float = 5.0) -> dict:
    """Uma chamada ao núcleo. Levanta `RuntimeError` com a frase para o editor."""
    try:
        tok = (pasta_do_ciclo() / TOKEN_DO_NUCLEO).read_text(encoding="utf-8").strip()
    except OSError:
        raise RuntimeError("o Ciclo Assist não está no ar (sem o token do núcleo) — é ele que fala com o Premiere")
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORTA_DO_NUCLEO}{rota}", data=dados, method=metodo,
                                 headers={"Content-Type": "application/json", HEADER_DO_NUCLEO: tok})
    try:
        with urllib.request.urlopen(req, timeout=prazo) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            erro = json.loads(e.read() or b"{}").get("erro")
        except ValueError:
            erro = None
        raise RuntimeError(erro or f"o núcleo recusou ({e.code})")
    except (OSError, ValueError) as e:
        raise RuntimeError(f"não consegui falar com o Ciclo Assist: {e}")


def viva() -> bool:
    """A ponte do Premiere bateu há pouco? (pergunta ao núcleo; guardado `VIVA_CACHE` s)"""
    global _viva
    agora = time.monotonic()
    with _cv:
        if agora - _viva[0] < VIVA_CACHE:
            return _viva[1]
    try:
        v = bool(_nucleo("GET", "/nucleo/premiere/viva", prazo=2.0).get("viva"))
    except RuntimeError:
        v = False
    with _cv:
        _viva = (time.monotonic(), v)
    return v


def literal(v: Any) -> str:
    """JSON compacto, chaves em ordem, todo não-ASCII em `\\uXXXX` (o `evalScript` do CEP perde acento em algumas
    versões). ⚠️ Desde a fase 4 quem monta a expressão que vai ao Premiere é o núcleo; este serve à conferência."""
    return json.dumps(v, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def expressao(funcao: str, args: list) -> str:
    if not _NOME.match(funcao or ""):
        raise ValueError(f"função recusada: {json.dumps(funcao, ensure_ascii=False)}")
    return f"{funcao}({', '.join(literal(a) for a in args)})"


def _chamar_no_nucleo(funcao: str, args: list) -> str:
    r = _nucleo("POST", "/nucleo/premiere/chamar",
                {"modulo": "sincronizar", "funcao": funcao, "args": args, "prazo": PRAZO}, prazo=PRAZO + 30)
    texto = r.get("r")
    return texto if isinstance(texto, str) else json.dumps(texto, ensure_ascii=False)


def enfileirar(funcao: str, args: list) -> int:
    """Manda ao núcleo NO FUNDO e devolve o id para quem pediu buscar o resultado (a interface de antes)."""
    global _proximo_id
    expressao(funcao, args)  # recusa aqui, antes de qualquer rede
    with _cv:
        agora = time.monotonic()
        for k in [k for k, (t, _) in _resultados.items() if agora - t >= GUARDA_DO_RESULTADO + PRAZO]:
            del _resultados[k]
        _proximo_id += 1
        i = _proximo_id
        _resultados[i] = (agora, None)

    def rodar() -> None:
        try:
            texto = _chamar_no_nucleo(funcao, list(args))
        except RuntimeError as e:
            texto = f"err|{e}"
        with _cv:
            if i in _resultados:
                _resultados[i] = (_resultados[i][0], texto)
            _cv.notify_all()

    threading.Thread(target=rodar, name=f"ponte-{funcao}", daemon=True).start()
    return i


def resultado(i: int):
    """`None` = desconhecido (vencido?); `(False, None)` = ainda não; `(True, texto)` = pronto (e sai da memória)."""
    with _cv:
        r = _resultados.get(i)
        if r is None:
            return None
        if r[1] is None:
            return (False, None)
        del _resultados[i]
        return (True, r[1])
