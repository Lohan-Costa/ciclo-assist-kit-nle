"""A conferência sobre a timeline COMO ELA ESTÁ no Resolve (autor, 2026-10-19).

Rodar:

    .venv-win/Scripts/python tests/test_conferencia_timeline.py

Sem Resolve: a leitura (`resolve_externo.ler_timeline`) é um dicionário sintético.
- A referência posta à mão na trilha mais alta, do início ao fim, é ACHADA (a regra de ofício), também com a trilha
  desligada e com a trilha de notas (textos) acima dela.
- Sem a regra, vale o vídeo que entrou DEPOIS da entrega (um arquivo fora da mídia do DRT); dois novos = o editor indica.
- O take que o editor tirou da timeline não vira ponto; o desligado também não.
- A referência que divide a trilha com outros clipes é recusada (a conferência desliga a trilha dela).
- O plano tem o mapa da referência (onde ela começa na timeline e a entrada no arquivo).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import conferencia_timeline as CT  # noqa: E402

INI = 86400          # 01:00:00:00 a 24 q/s


def item(trilha, start, dur, arquivo, tipo="video", **k):
    return {"tipo": tipo, "trilha": trilha, "start": INI + start, "dur": dur, "fonte_in": k.pop("fonte_in", 0),
            "nome": arquivo.rsplit("\\", 1)[-1] if arquivo else "Text", "arquivo": arquivo, **k}


def leitura(itens, transicoes=()):
    return {"ok": True, "nome": "CORTE", "uid": "u", "inicio": INI, "fps": 24.0, "nominal": 24,
            "largura": 1920, "altura": 1080, "itens": list(itens), "transicoes": list(transicoes)}


FILME = [item(1, 0, 48, r"D:\M\A.mov"), item(1, 48, 48, r"D:\M\B.mov"), item(1, 96, 48, r"D:\M\C.mov")]
REF = r"D:\REF\corte.mov"


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {obtido!r}"[:150])
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── 1. a regra de ofício ──")
    c = CT.contexto(leitura(FILME + [item(2, 0, 144, REF, desligado=True)]))
    ok("a referência da trilha mais alta, do início ao fim, é achada", (c["ok"], c.get("como")),
       (True, "achada na timeline"))
    ok("a trilha dela vai para o plano", c["contexto"]["trilha_referencia"], 2)
    ok("os pontos são só do filme (2 por plano)", len(c["contexto"]["pontos"]), 6)
    ok("nenhum ponto na referência", {p["trilha"] for p in c["contexto"]["pontos"]}, {1})
    notas = [item(3, 0, 48, "", desligado=True), item(3, 48, 96, "", desligado=True)]
    c = CT.contexto(leitura(FILME + [item(2, 0, 144, REF, desligado=True)] + notas))
    ok("⭐ a trilha de notas acima (textos) não esconde a referência", (c["ok"], c.get("trilha_referencia")), (True, 2))

    print("\n── 2. o que entrou depois da entrega ──")
    meio = item(2, 10, 100, REF, fonte_in=240)
    entregues = {r"D:\M\A.mov", r"D:\M\B.mov", r"D:\M\C.mov"}
    ok("sem a regra e sem a entrega, não acha", CT.contexto(leitura(FILME + [meio]))["sem_referencia"], True)
    c = CT.contexto(leitura(FILME + [meio]), entregues)
    ok("⭐ o vídeo fora da mídia do DRT é a referência", (c["ok"], c.get("como")), (True, "entrou depois da entrega"))
    ok("o mapa: onde ela começa na timeline e a entrada no arquivo",
       (c["contexto"]["ref_na_timeline"], c["contexto"]["ref_entrada"]), (10, 240))
    outro = item(3, 0, 50, r"D:\REF\outro.mov")
    c = CT.contexto(leitura(FILME + [meio, outro]), entregues)
    ok("dois vídeos novos: o editor indica qual", (c["ok"], c.get("sem_referencia"), "indique" in c["erro"]),
       (False, True, True))
    c = CT.contexto(leitura(FILME + [meio, outro]), entregues, arquivo=REF.lower())
    ok("indicado pelo painel (caixa de letra não importa)", (c["ok"], c.get("como"), c.get("trilha_referencia")),
       (True, "indicada", 2))
    ok("indicado e ausente da timeline: diz", CT.contexto(leitura(FILME), entregues, arquivo=REF)["erro"],
       "o vídeo indicado não está na timeline")

    print("\n── 3. a timeline arrumada pelo editor ──")
    sem_b = [FILME[0], FILME[2], item(2, 0, 144, REF)]
    c = CT.contexto(leitura(sem_b))
    ok("o take tirado não vira ponto", sorted({p["arquivo"] for p in c["contexto"]["pontos"]}), ["A.mov", "C.mov"])
    desl = [FILME[0], {**FILME[1], "desligado": True}, FILME[2], item(2, 0, 144, REF)]
    c = CT.contexto(leitura(desl))
    ok("o clipe desligado também não", sorted({p["arquivo"] for p in c["contexto"]["pontos"]}), ["A.mov", "C.mov"])
    cobre = FILME + [item(2, 0, 144, REF), item(1, 200, 10, r"D:\M\D.mov")]
    c = CT.contexto(leitura(cobre))
    ok("plano depois do fim da referência: ela não é mais do início ao fim", c["ok"], False)
    trans = [{"trilha": "V1", "start": INI + 44, "dur": 8, "nome": "Cross Dissolve"}]
    c = CT.contexto(leitura(FILME + [item(2, 0, 144, REF)], trans))
    q = sorted(p["quadro"] for p in c["contexto"]["pontos"])
    ok("a transição do DRT afasta os pontos do corte", (47 in q, 48 in q, 42 in q, 53 in q), (False, False, True, True))

    print("\n── 3b. o clipe composto (timeline aninhada, sem arquivo; medido 2026-10-19) ──")
    comp = [item(1, 0, 72, "", composto=True), item(1, 72, 72, "", composto=True), item(2, 0, 144, REF)]
    c = CT.contexto(leitura(comp))
    ok("⭐ composto é plano do filme: tem pontos", (c["ok"], len(c["contexto"]["pontos"])), (True, 4))
    c = CT.contexto(leitura([item(1, 0, 144, "", composto=True)]), entregues)
    ok("composto nunca vira 'vídeo novo' (a referência)", c.get("sem_referencia"), True)
    curta = [item(1, 0, 175, r"D:\M\A.mov"), item(2, 0, 172, REF)]
    ok("referência 3 quadros mais curta (render do Avid) ainda vale", CT.contexto(leitura(curta))["ok"], True)

    print("\n── 4. a trilha da referência é só dela ──")
    junto = FILME + [item(2, 0, 144, REF), item(2, 144, 20, r"D:\M\E.mov")]
    c = CT.contexto(leitura(junto), entregues | {r"D:\M\E.mov"}, arquivo=REF)
    ok("dividindo a trilha: recusa e diz o que fazer", (c["ok"], "trilha só dela" in c.get("erro", "")), (False, True))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
