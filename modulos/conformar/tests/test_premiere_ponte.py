"""O Premiere pela ponte ÚNICA do Ciclo Assist (fase 4 do plano um app só, 2026-11-07; era a ponte própria de 2026-10-19).

Rodar:

    .venv-win/Scripts/python tests/test_premiere_ponte.py

Sem Premiere:
- a página da ponte própria saiu: o portão não a trata mais como página (sem `Origin`, recusada);
- a fila: sem ponte viva, `chamar` recusa na hora; com ela, o pedido sai como `funcao(literais JSON)` e a resposta
  volta como JSON; nome de função fora do padrão é recusado (o ExtendScript nunca chega pronto de fora).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import premiere_ponte as P  # noqa: E402
from api.portao import Recusa, portao  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<64} -> {obtido!r}"[:150])
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── 1. a ponte própria saiu ──")
    h = "127.0.0.1:7823"
    ok("⛔ /premiere/ponte não é mais página (sem Origin, recusada)",
       portao(h, None, "cross-site", None, "/premiere/ponte"), Recusa.SEM_CREDENCIAL)

    print("\n── 3. a fila (pelo NÚCLEO do Ciclo Assist desde a fase 4 — aqui de mentira: nunca o Premiere de verdade) ──")
    P.esquecer()
    viva, vistos = [False], []

    def nucleo_falso(metodo, rota, corpo=None, prazo=5.0):
        if rota == "/nucleo/premiere/viva":
            return {"viva": viva[0]}
        vistos.append(P.expressao(corpo["funcao"], *corpo["args"]) if corpo["modulo"] == "conformar" else "?")
        return {"ok": True, "r": '{"versao":"23.2.0","projeto":null}'}

    nucleo_de_verdade, P._nucleo, P._viva_cache = P._nucleo, nucleo_falso, (float("-inf"), False)
    try:
        P.chamar("dlpcEstado")
        ok("sem ponte viva, recusa na hora", "não recusou", "PremiereIndisponivel")
    except P.PremiereIndisponivel:
        ok("sem ponte viva, recusa na hora", "PremiereIndisponivel", "PremiereIndisponivel")
    try:
        P.expressao("x); app.quit(); (", 1)
        ok("⛔ nome de função fora do padrão", "aceitou", "ValueError")
    except ValueError:
        ok("⛔ nome de função fora do padrão", "ValueError", "ValueError")
    ok("os argumentos viram literais JSON", P.expressao("dlpcAbrirProjeto", 'C:\\a "b".prproj'),
       'dlpcAbrirProjeto("C:\\\\a \\"b\\".prproj")')

    viva[0], P._viva_cache = True, (float("-inf"), False)   # a ponte única bateu
    r = P.chamar("dlpcEstado", prazo=5)
    ok("o pedido sai pelo nome", vistos, ["dlpcEstado()"])
    ok("a resposta volta como JSON", r, {"versao": "23.2.0", "projeto": None})
    P._nucleo, P._viva_cache = nucleo_de_verdade, (float("-inf"), False)
    P.esquecer()

    print("\n── 4. o arrasto de uma sequência do Premiere (o XML do dynamiclinksourcelist) ──")
    from types import SimpleNamespace

    from api import rotas
    xml1 = ("<LiveLinkSourceList ver ='1.0'><BetaPrime>0</BetaPrime><Source><ProjectPath>C:\\x\\p.prproj</ProjectPath>"
            "<ID>0f6bcd99-5e43-41fc-8134-1b17fb2c307f</ID></Source></LiveLinkSourceList>")

    def ctx(corpo):
        return SimpleNamespace(json=lambda: corpo)

    # ⛔ "sem ponte" de verdade: com o Premiere aberto na máquina, a ponte do Ciclo Assist RESPONDE (visto em 2026-11-07)
    viva_de_verdade = P.ponte_viva
    P.ponte_viva = lambda: False
    try:
        st, r = rotas.arrasto_nle(ctx({"tipo": "premiere", "dados": xml1}))
    finally:
        P.ponte_viva = viva_de_verdade
    ok("uma sequência: o .prproj e o sequenceID", (st, r["ok"], r["prproj"], r["id"]),
       (200, True, "C:\\x\\p.prproj", "0f6bcd99-5e43-41fc-8134-1b17fb2c307f"))
    ok("sem ponte, o nome fica vazio e o motivo vem", (r["nome"], bool(r.get("aviso"))), ("", True))
    xml2 = xml1.replace("</Source>", "</Source><Source><ProjectPath>C:\\x\\p.prproj</ProjectPath><ID>b</ID></Source>", 1)
    ok("⛔ duas sequências: uma por vez", rotas.arrasto_nle(ctx({"tipo": "premiere", "dados": xml2}))[1]["ok"], False)
    ok("⛔ um clipe (sem dynamiclink) é recusado com o motivo",
       "SEQUÊNCIA" in rotas.arrasto_nle(ctx({"tipo": "premiere_item"}))[1]["erro"], True)
    ok("⛔ XML quebrado não derruba", rotas.arrasto_nle(ctx({"tipo": "premiere", "dados": "<x"}))[1]["ok"], False)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
