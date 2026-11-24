#!/usr/bin/env python3
"""
medir_getmobinfo.py — o `GetMobInfo` é o gargalo agora. Este mede antes de consertar.

## Por que existe

Depois que a busca de mídia caiu de 80 s para ~1 s (§1.4 do roadmap), o custo passou
a ser a fase A: **760 ms por master, 38 s numa diária de 50**. É o próximo alvo
técnico — e a tentação óbvia é paralelizar, como se fez com o `ffprobe`.

⚠️⚠️ **Só que ali a tentação foi medida e a intuição errou por 5×** (o "6,93× com 8
trabalhadores" virou 1,39× na varredura fria real — DECISIONS 33ª). E aqui há um fato
medido que empurra para o lado contrário: **qualquer diálogo modal do Media Composer
trava a API inteira** (medição interna), o que sugere
que o serviço é atendido na thread da interface. Se for, chamadas concorrentes
**enfileiram** e paralelizar não rende nada — ou rende negativo.

Este script não conserta nada. Ele responde a uma pergunta só, com número:

    **N chamadas em série custam mais que N chamadas concorrentes?**

## Uso

    python tools/medir_getmobinfo.py "<BIN>" [--n 20] [--trabalhadores 1,2,4,8]

⚠️ **Precisa do Media Composer ABERTO** no projeto. Sem argumento de bin, lista as do
projeto aberto e para.

⭐ **A primeira rodada é DESCARTADA**, e não é cerimônia: a primeira chamada a uma bin
recém-aberta paga o `OpenBin` (efeito visível, e ~500 ms que não são do `GetMobInfo`).
Medir com esse custo dentro compararia coisas diferentes — é a mesma disciplina do
protocolo de benchmark do roadmap interno.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def mobs_da_bin(mc, chave: str, n: int) -> list[str]:
    mapa = {mc.chave_de_bin(b): b for b in mc.bins()}
    if chave not in mapa:
        raise SystemExit(f"Bin não encontrada: {chave!r}\n"
                         "Rode sem argumento para ver as bins do projeto aberto.")
    itens = [i.mob_id for i in mc.itens_de(mapa[chave]) if i.mob_id]
    if not itens:
        raise SystemExit(f"A bin {chave!r} não tem master clips.")
    return itens[:n]


def em_serie(mc, mobs: list[str]) -> float:
    t0 = time.perf_counter()
    for m in mobs:
        mc.colunas_do_master(m)
    return time.perf_counter() - t0


def concorrente(mc, mobs: list[str], trabalhadores: int) -> float:
    """⚠️ UM canal gRPC para todos, que é o desenho real do app.

    Abrir um canal por thread mediria outra coisa — e esconderia justamente o efeito
    que se procura, que é o servidor serializar.
    """
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=trabalhadores) as pool:
        list(pool.map(mc.colunas_do_master, mobs))
    return time.perf_counter() - t0


def main() -> int:
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    import registro
    registro.configurar("medir_getmobinfo")

    args = sys.argv[1:]
    n, trabs = 20, [1, 2, 4, 8]
    for flag in ("--n", "--trabalhadores"):
        if flag in args:
            i = args.index(flag)
            valor = args[i + 1]
            args = args[:i] + args[i + 2:]
            if flag == "--n":
                n = int(valor)
            else:
                trabs = [int(x) for x in valor.split(",")]

    from avid.mcapi import MediaComposer

    if not args:
        with MediaComposer() as mc:
            print("Bins do projeto aberto:")
            for b in sorted((mc.chave_de_bin(x) for x in mc.bins()), key=str.casefold):
                print("  ", b)
        return 0

    with MediaComposer() as mc:
        mobs = mobs_da_bin(mc, args[0], n)
        print(f"{len(mobs)} master(s) da bin {args[0]!r}\n")

        # Aquecimento descartado: tira o `OpenBin` e o que mais for de primeira vez.
        print("aquecendo (descartado)…", flush=True)
        em_serie(mc, mobs[:3])

        base = em_serie(mc, mobs)
        por_master = 1000 * base / len(mobs)
        print(f"\n  em SÉRIE           {base:7.2f} s   ({por_master:6.0f} ms por master)")

        for t in trabs:
            if t == 1:
                continue
            dt = concorrente(mc, mobs, t)
            print(f"  {t:2d} trabalhadores   {dt:7.2f} s   "
                  f"({1000 * dt / len(mobs):6.0f} ms por master)   {base / dt:4.2f}×")

        print(f"\nNuma diária de 50 masters, a série custa ~{50 * por_master / 1000:.0f} s.")
        print("⚠️ Se o ganho ficar perto de 1,00×, o serviço serializa e paralelizar é")
        print("   trabalho jogado fora — anote o número no o roadmap interno e siga.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
