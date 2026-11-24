"""A sonda do Media Composer no `/conexao` (achado de 2026-10-24, Mac, MC 25.12).

Rodar:

    .venv/bin/python tests/test_conexao_mc.py

Com um diálogo MODAL no MC ("Leave the application?") ou o MC abrindo um projeto, o `GetAppInfo` não responde. Com o
prazo padrão de 20 s, o `/conexao` levava 20 s, a página ficava "procurando o De Lá Pra Cá…" e, no fim, o painel trocava
para o Premiere. Aqui, com um MC falso:
- fechado / sem a API (`McApiIndisponivel`) → `None` (vale o próximo programa, como antes);
- ocupado (não respondeu no prazo) → continua sendo o MC, `ocupado`, com o último conhecido, e a próxima pergunta dentro
  da carência responde NA HORA, sem perguntar ao MC de novo;
- a sonda usa o prazo curto, não os 20 s.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

from api import rotas  # noqa: E402
from avid.mcapi import McApiError, McApiIndisponivel  # noqa: E402

casos, falhas = 0, []


def ok(rotulo: str, obtido, esperado) -> None:
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


class MCFalso:
    def __init__(self, comportamento: str):
        self.comportamento, self.timeout, self.perguntas = comportamento, 20.0, []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def info(self):
        self.perguntas.append(self.timeout)
        if self.comportamento == "fechado":
            raise McApiIndisponivel("não está atendendo")
        if self.comportamento == "ocupado":
            raise McApiError("GetAppInfo não respondeu no prazo")
        return {"version": "2025.12.0.58863.0"}

    def projeto(self):
        return {"path": "/Users/x/Documents/Avid Projects/LAB/"}


def ctx_com(mc: MCFalso):
    return SimpleNamespace(servico=SimpleNamespace(media_composer=lambda: mc))


def main() -> int:
    rotas._MC_CONHECIDO.update(versao="", projeto="", ocupado_ate=0.0)
    mc = MCFalso("fechado")
    ok("MC sem a API → None (vale o próximo programa)", rotas._conexao_mc(ctx_com(mc)), None)
    ok("…e a sonda usa o prazo curto", mc.perguntas, [rotas.PRAZO_SONDA_MC_S])

    mc = MCFalso("vivo")
    ok("MC atendendo → o MC, a versão e o projeto", rotas._conexao_mc(ctx_com(mc)),
       {"programa": "mc", "versao": "2025.12.0.58863.0", "projeto": "LAB"})

    mc = MCFalso("ocupado")
    ok("⭐ MC ocupado (diálogo modal) → continua o MC, ocupado, com o último conhecido",
       rotas._conexao_mc(ctx_com(mc)),
       {"programa": "mc", "versao": "2025.12.0.58863.0", "projeto": "LAB", "ocupado": True})
    outro = MCFalso("ocupado")
    r = rotas._conexao_mc(ctx_com(outro))
    ok("⭐ …e dentro da carência responde na hora, sem perguntar ao MC", (r.get("ocupado"), outro.perguntas),
       (True, []))
    rotas._MC_CONHECIDO["ocupado_ate"] = 0.0
    mc = MCFalso("vivo")
    ok("passada a carência, pergunta de novo", rotas._conexao_mc(ctx_com(mc)).get("ocupado"), None)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
