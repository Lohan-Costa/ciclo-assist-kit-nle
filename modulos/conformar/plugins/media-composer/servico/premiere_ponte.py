"""O Premiere controlado pelo app: as funções `dlpc*` do `premiere_host.jsx`, rodadas pela ponte ÚNICA do Ciclo Assist.

⭐ Fase 4 do plano um app só (2026-11-07): no Premiere fica UMA extensão invisível, a do Ciclo Assist, que carrega o
ExtendScript dos três módulos. Este serviço não tem mais ponte própria (`plugins/premiere/cep/` e as rotas
`/premiere/ponte`·`pedido`·`resposta` saíram): `chamar()` pede ao NÚCLEO (`POST /nucleo/premiere/chamar` na 7824).

⛔ **O texto que vai para o `evalScript` é montado no núcleo a partir do NOME e dos argumentos** — `expressao()` recusa
aqui o nome fora do padrão, antes da rede. Texto livre virando ExtendScript seria um shell no Premiere do editor.

⚠️ **Sem a ponte viva não há Premiere**, e isso é dito na hora (`ponte_viva()`), não esperado.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

log = logging.getLogger("delapraca.premiere_ponte")

#: O prazo de uma chamada, contado de quando a ponte a levou (o núcleo conta).
PRAZO_S = 30.0
#: A partir de quanto uma chamada vira linha de log. ⚠️ Uma por chamada encheria o log: a
#: vigia sozinha faz uma por minuto, e o painel faz várias por abertura de aba.
LENTO_S = 1.0

_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PremiereIndisponivel(RuntimeError):
    """A ponte do Premiere não está conectada, ou o Premiere não respondeu."""


class ExtendScriptFalhou(RuntimeError):
    """A função rodou e lançou, ou devolveu o que não é JSON."""


#: ⭐⭐ Quem é trabalho de FUNDO é a THREAD, não a chamada. A vigia e a sincronização de
#: descrições nascem em threads próprias e passam por várias camadas antes de chegar aqui
#: (`clipes_do_projeto`, `escopo_agora`…): levar um parâmetro por toda essa corrente
#: significaria mudar assinatura em cada uma, e esquecer uma delas é um pedido de fundo se
#: passando por gesto do editor.
_quem_sou = threading.local()


def marcar_de_fundo() -> None:
    """Esta thread é trabalho de fundo: os pedidos dela cedem a vez a quem o editor pediu."""
    _quem_sou.de_fundo = True


def sou_de_fundo() -> bool:
    return bool(getattr(_quem_sou, "de_fundo", False))


def expressao(funcao: str, *args: Any) -> str:
    """`funcao("a", 1)` com cada argumento como literal JSON. Nome fora do padrão é recusado."""
    if not _NOME.match(funcao):
        raise ValueError(f"nome de função inválido: {funcao!r}")
    return f"{funcao}({', '.join(json.dumps(a, ensure_ascii=True) for a in args)})"


#: ⭐ Fase 4 do plano um app só (2026-11-07): UMA extensão no Premiere, a do Ciclo Assist, que carrega o ExtendScript
#: dos três módulos (`cicloassist/nle/premiere::host_jsx_inteiro`). Este serviço não tem mais ponte própria
#: (`com.ciclomedia.delapraca.ppro` saiu): `chamar()` pede ao NÚCLEO (`POST /nucleo/premiere/chamar` na 7824, com o
#: token do núcleo), que só aceita funções `dlpc*` deste módulo, na MESMA fila do chat (gesto × fundo vale lá).
PORTA_DO_NUCLEO = 7824
_viva_cache: tuple[float, bool] = (float("-inf"), False)


def _pasta_do_ciclo():
    import os
    import sys
    from pathlib import Path
    explicita = os.environ.get("CICLOASSIST_DADOS")
    if explicita:
        return Path(explicita)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "CicloAssist"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CicloAssist"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "cicloassist"


def _nucleo(metodo: str, rota: str, corpo: dict | None = None, prazo: float = 5.0) -> dict:
    import urllib.error
    import urllib.request
    try:
        tok = (_pasta_do_ciclo() / "plugin-token").read_text(encoding="utf-8").strip()
    except OSError:
        raise PremiereIndisponivel("O Ciclo Assist não está no ar — é ele que fala com o Premiere.")
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORTA_DO_NUCLEO}{rota}", data=dados, method=metodo,
                                 headers={"Content-Type": "application/json", "X-Ciclo-Token": tok})
    try:
        with urllib.request.urlopen(req, timeout=prazo) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            erro = json.loads(e.read() or b"{}").get("erro")
        except ValueError:
            erro = None
        raise PremiereIndisponivel(erro or f"o Ciclo Assist recusou o pedido ao Premiere ({e.code})")
    except (OSError, ValueError) as e:
        raise PremiereIndisponivel(f"Não consegui falar com o Ciclo Assist: {e}")


def ponte_viva() -> bool:
    global _viva_cache
    agora = time.monotonic()
    if agora - _viva_cache[0] < 2.0:
        return _viva_cache[1]
    try:
        v = bool(_nucleo("GET", "/nucleo/premiere/viva", prazo=2.0).get("viva"))
    except PremiereIndisponivel:
        v = False
    _viva_cache = (time.monotonic(), v)
    return v


def chamar(funcao: str, *args: Any, prazo: float = PRAZO_S) -> Any:
    """Roda `funcao(*args)` do `premiere_host.jsx` no Premiere (pelo núcleo) e devolve o JSON que ela produziu."""
    expressao(funcao, *args)  # o nome recusado aqui, antes da rede
    if not ponte_viva():
        raise PremiereIndisponivel(
            "O Premiere não está conectado ao Ciclo Assist. Ele está aberto? A integração do Premiere "
            "precisa estar instalada (⚙ › Integrações) e o Premiere aberto DEPOIS dela.")
    t0 = time.monotonic()
    r = _nucleo("POST", "/nucleo/premiere/chamar",
                {"modulo": "conformar", "funcao": funcao, "args": list(args), "prazo": prazo,
                 "de_fundo": sou_de_fundo()}, prazo=prazo + 60)
    if time.monotonic() - t0 >= LENTO_S:
        log.info("ponte %s em %.2f s (pelo núcleo)", funcao, time.monotonic() - t0)
    texto = r.get("r")
    return _ler(funcao, texto if isinstance(texto, str) else json.dumps(texto))


def _ler(funcao: str, texto: str) -> Any:
    # ⚠️ Exceção no ExtendScript chega como TEXTO ("EvalScript error."), não como erro.
    if texto.startswith("EvalScript error"):
        raise ExtendScriptFalhou(
            f"{funcao} falhou dentro do Premiere ({texto}). O premiere_host.jsx carregou? "
            "Reabrir o Premiere recarrega.")
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ExtendScriptFalhou(f"{funcao} devolveu o que não é JSON: {texto[:200]!r}") from e
    if isinstance(dados, dict) and dados.get("erro"):
        raise ExtendScriptFalhou(str(dados["erro"]))
    return dados


def esquecer() -> None:
    """Estado limpo (testes)."""
    global _viva_cache
    _viva_cache = (float("-inf"), False)
