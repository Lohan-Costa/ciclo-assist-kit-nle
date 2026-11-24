"""A política de nome da bin entregue — travada por regressão.

Duas bins **não podem ter o mesmo nome** num projeto do Avid. Isso é restrição dele, mas
o remédio nunca pode ser recusar o trabalho ou sobrescrever a bin de alguém: o relink é
a etapa cara (LinkFile arquivo a arquivo, áudio autorado), e perdê-lo por causa de um
rótulo seria o pior desfecho possível.

São duas políticas, de propósito:

* **nome DIGITADO** — o editor quer aquele nome. O número só aparece se já houver um
  igual, e aí é desempate: `CORTE`, depois `CORTE 2`.
* **nome AUTOMÁTICO** (campo em branco) — vale o nome do PROJETO, e o número é parte do
  nome desde a primeira vez: `PRODUCAO-A 1`, `PRODUCAO-A 2`. Uma bin chamada só
  `PRODUCAO-A` no meio de uma série pareceria a bin do projeto, não uma entrega.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVICO = RAIZ / "plugins" / "media-composer" / "servico"
sys.path.insert(0, str(SERVICO))
sys.path.insert(0, str(RAIZ / "motor"))

from avid.acoes import Acoes  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo: str, obtido, esperado) -> None:
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<46} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    # `nome_de_bin_livre` só olha o disco — não fala com o Media Composer.
    acoes = Acoes(None)

    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)

        def livre(base, auto=False):
            return acoes.nome_de_bin_livre(str(pasta), base, sempre_numerar=auto)

        print("── nome DIGITADO pelo editor ────────────────────────────────")
        ok("livre: fica o nome pelado", livre("CORTE"), "CORTE")
        (pasta / "CORTE.avb").touch()
        ok("já existe: vira “CORTE 2”", livre("CORTE"), "CORTE 2")
        (pasta / "CORTE 2.avb").touch()
        (pasta / "CORTE 3.avb").touch()
        ok("pula os ocupados em sequência", livre("CORTE"), "CORTE 4")
        ok("outro nome não é afetado", livre("MONTAGEM"), "MONTAGEM")

        print("\n── nome AUTOMÁTICO (campo em branco → nome do projeto) ──────")
        ok("⭐ numera desde a primeira vez", livre("PRODUCAO-A", auto=True), "PRODUCAO-A 1")
        (pasta / "PRODUCAO-A 1.avb").touch()
        ok("segunda entrega", livre("PRODUCAO-A", auto=True), "PRODUCAO-A 2")
        # ⚠️ O caso que separa as duas políticas: mesmo com o nome pelado LIVRE, o
        # automático não o usa. Se usasse, uma série ficaria "PRODUCAO-A 1", "PRODUCAO-A",
        # "PRODUCAO-A 2" — e a do meio pareceria a bin do projeto.
        ok("⭐ nunca devolve o nome pelado", livre("PRODUCAO-A", auto=True), "PRODUCAO-A 2")
        ok("o mesmo nome, digitado, PODE ficar pelado", livre("PRODUCAO-A"), "PRODUCAO-A")

        print("\n── a entrega organizada é uma PASTA (só ela na raiz) ─────────")
        (pasta / "ORG 1").mkdir()
        ok("⭐ pasta ocupa o nome (2026-10-13)", livre("ORG", auto=True), "ORG 2")
        (pasta / "PASTA").mkdir()
        ok("pasta ocupa o nome digitado", livre("PASTA"), "PASTA 2")

        print("\n── a entrega mora AO LADO da bin de origem (subpasta) — revisão 2026-10-28 ─")
        sub = pasta / "PRODC PRPROJ 9"
        (sub / "LAB 1").mkdir(parents=True)               # a 1ª entrega, ao lado da bin do editor
        ok("só a raiz: repetiria o “LAB 1” (o defeito)", livre("LAB", auto=True), "LAB 1")
        ok("⭐ olhando a subpasta também: “LAB 2”",
           acoes.nome_de_bin_livre(str(pasta), "LAB", sempre_numerar=True, tambem=(str(sub),)), "LAB 2")

        print("\n── o nome vira arquivo, então precisa ser um nome de arquivo ─")
        from api.rotas import _nome_de_arquivo
        ok("tira o que o disco não aceita", _nome_de_arquivo('CORTE: v2 <final>/'),
           "CORTE v2 final")
        ok("acento fica (é letra, não símbolo)", _nome_de_arquivo("GRAVAÇÕES"), "GRAVAÇÕES")
        ok("vazio tem um padrão, não estoura", _nome_de_arquivo(""), "RELINK")
        ok("só símbolos também", _nome_de_arquivo("///"), "RELINK")
        ok("⭐ “..” não sobe de pasta", _nome_de_arquivo(".."), "RELINK")
        ok("pontos nas pontas saem", _nome_de_arquivo(".CORTE."), "CORTE")
        ok("corta em 60 caracteres", len(_nome_de_arquivo("A" * 200)), 60)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
