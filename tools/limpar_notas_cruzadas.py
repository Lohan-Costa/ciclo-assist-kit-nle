"""Tira das entradas COPIADAS de outro banco as notas de subclipe/multicam que vieram junto.

    python tools/limpar_notas_cruzadas.py            # só mostra o que faria
    python tools/limpar_notas_cruzadas.py --fazer    # limpa

⭐⭐ **Por que isto existe** (decisão do editor, 2026-09-22): *"o cruzamento dos bancos deve
ser só dos masters, e não dos subclipes/multicam — são elementos que cada software fará
diferente e não coexistirão em outra plataforma"*.

Até o conserto de `Midia.copiar_de`, a cópia levava o `notas.json` INTEIRO: as notas de take
escritas numa conversa do Media Composer (`trecho: C07_P03-T001`, o nome de um SUBCLIPE do
Avid) chegavam ao banco do Premiere, e a busca de lá mostrava esse nome como título. A nota
do material inteiro vinha com o `trecho` = nome do master na bin do Avid.

O que este script faz, só nas entradas com `aproveitado_de` no manifesto:

- ⛔ remove a nota que NÃO é do master e é IDÊNTICA a uma nota da entrada de onde veio
  (a nota de take que o próprio editor escreveu no Premiere não é tocada: ela não existe
  do outro lado);
- ⭐ na nota do master copiada, troca o `trecho` pelo nome desta entrada e marca `copiada_de`.

⚠️ Nada é apagado fora do `notas.json` — quadros, vetores e fala são do master e ficam.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.midia import cache as C  # noqa: E402


def _igual(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == \
        json.dumps(b, sort_keys=True, ensure_ascii=False)


def _chave(n: dict, nome: str) -> str:
    """Como o `trecho` desta nota se chama NESTE banco.

    ⚠️ A nota de TRECHO (a decupagem micro) tem uma chave por posição — a mesma de
    `motor.micro.chave_do_trecho`. Renomeá-la para o nome da mídia, como se fosse a nota
    do material inteiro, colapsaria todas as notas de trecho numa chave só.
    """
    if n.get("escopo") == "trecho" and n.get("inicio_frames") is not None:
        return f"{nome} · trecho {n['inicio_frames']}"
    return nome


def plano(m: C.Midia) -> tuple[list[dict], int, int] | None:
    """(notas novas, removidas, renomeadas), ou None se nada muda."""
    de = (m.manifesto().get("aproveitado_de") or {})
    if not de.get("chave"):
        return None
    par = C.Midia(str(de["chave"]))
    do_par = par.ler_notas() if par.existe else []
    nome = m.nome or m.chave[:12]
    novas, removidas, renomeadas = [], 0, 0
    for n in m.ler_notas():
        veio = any(_igual(n, p) for p in do_par)
        # ⭐ Nota do MASTER (material inteiro ou trecho) atravessa e fica; o que não é do
        #   master e veio do par é nota de SUBCLIPE, e essa é que não coexiste entre NLEs.
        if n.get("escopo") not in C.Midia.ESCOPOS_DO_MASTER:
            if veio:
                removidas += 1
                continue
            novas.append(n)
            continue
        alvo = _chave(n, nome)
        if n.get("trecho") != alvo and (veio or n.get("copiada_de")):
            novas.append({**n, "trecho": alvo,
                          "copiada_de": n.get("copiada_de") or de.get("origem") or ""})
            renomeadas += 1
            continue
        novas.append(n)
    if not removidas and not renomeadas:
        return None
    return novas, removidas, renomeadas


def main() -> int:
    fazer = "--fazer" in sys.argv
    print(f"cache: {C.raiz()}\n")
    achados = []
    for m in C.todas():
        p = plano(m)
        if p:
            achados.append((m, *p))
    if not achados:
        print("nenhuma nota de subclipe copiada: os bancos já estão limpos.")
        return 0
    total_r = sum(a[2] for a in achados)
    total_n = sum(a[3] for a in achados)
    print(f"{len(achados)} entrada(s): {total_r} nota(s) de subclipe/multicam a remover, "
          f"{total_n} nota(s) do master a renomear\n")
    for m, _, r, n in achados[:40]:
        print(f"  [{m.origem:8s}] {m.nome[:40]:40s}  -{r} de take, {n} renomeada(s)")
    if len(achados) > 40:
        print(f"  … e mais {len(achados) - 40}")
    if not fazer:
        print("\n(nada foi tocado — rode com --fazer para limpar)")
        return 0
    for m, novas, _, _ in achados:
        C.escrever_atomico(m.pasta / "notas.json",
                           json.dumps({"notas": novas}, ensure_ascii=False, indent=1)
                           .encode("utf-8"))
    print(f"\n{len(achados)} entrada(s) limpas. Quadros, vetores e fala não foram tocados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
