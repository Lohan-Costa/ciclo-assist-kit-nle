"""Tira dos filtros a cena/plano/take que o modelo CHUTOU ao ler a claquete.

    python tools/limpar_claquete_chutada.py            # só mostra o que faria
    python tools/limpar_claquete_chutada.py --fazer    # limpa

⛔⛔ **O que aconteceu** (medido no cache real em 2026-09-23): **30 de 50 mídias com
decupagem micro feita** devolveram a cena/plano/take do EXEMPLO da instrução
(`31 · 8 · 5`) como se as tivessem lido na claquete, e **44 notas** ficaram com a leitura
em `hipotese` — as 44 com os três campos no TOPO da nota, que é onde a busca filtra e
ordena, sem marca de dúvida nenhuma.

Eram duas falhas somadas, as duas já consertadas no produto:

- a promoção para o topo acontecia em `decupador._uma_nota`, ANTES da conferência — que
  depois marcava a dúvida só dentro do objeto `claquete`, onde nenhum filtro olha;
- `micro._subir_claquete` levava a leitura para a nota MACRO checando só `legivel`, ou
  seja, subia justamente a que a conferência tinha reprovado.

⭐⭐ **O critério desta limpeza é a função do PRODUTO** (`decupador.conferir_a_claquete`),
rodada de novo sobre o que está gravado. Não há régua à parte aqui: o que ela reprova
hoje é o que a fila reprovaria hoje.

⚠️ E por isso ela é idempotente de verdade — a lição que o `consertar_quadros.py` custou:
*ferramenta de conserto único parece idempotente e não é*, quando o critério dela é uma
propriedade do ARQUIVO e o defeito era do código. Aqui o critério é o estado da NOTA, e
depois de limpa ela não volta a ser encontrada.

⛔ **Nada é apagado.** A claquete fica com o número lido e o aviso do que não confere — ela
é o registro do que o modelo viu, e o editor decide. O que sai é o FATO: os campos de topo.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.midia import cache as C          # noqa: E402
from cicloassist.motor import decupador as D      # noqa: E402


def nomes_da_midia(m: C.Midia) -> list[str]:
    """Os nomes que a conferência do rolo consulta — os MESMOS da fila e da micro."""
    manifesto = m.manifesto()
    arquivos = [Path(a).stem for a in (manifesto.get("arquivos") or [])]
    return [m.nome or "", *arquivos]


def plano(m: C.Midia) -> tuple[list[dict], int, int, int] | None:
    """(notas novas, reprovadas agora, campos tirados, campos promovidos), ou None.

    ⚠️ Os promovidos são contados e DITOS: rodar a conferência de hoje sobre uma nota
    antiga também pode ACRESCENTAR um campo que ela aprova, e uma ferramenta de limpeza
    que grava um campo novo sem dizer é a mesma mudança calada que se está consertando.
    """
    nomes = nomes_da_midia(m)
    novas: list[dict] = []
    reprovadas = tirados = promovidos = 0
    mudou = False
    for nota in m.ler_notas():
        antes = copy.deepcopy(nota)
        depois = D.conferir_a_claquete(copy.deepcopy(nota), nomes)
        if depois != antes:
            mudou = True
            if (depois.get("claquete") or {}).get("confianca") == "hipotese" \
                    and (antes.get("claquete") or {}).get("confianca") != "hipotese":
                reprovadas += 1
            tirados += sum(1 for c in D._DO_TOPO if c in antes and c not in depois)
            promovidos += sum(1 for c in D._DO_TOPO if c not in antes and c in depois)
        novas.append(depois)
    return (novas, reprovadas, tirados, promovidos) if mudou else None


def main() -> int:
    fazer = "--fazer" in sys.argv
    print(f"cache: {C.raiz()}")
    exemplo = D._valores_do_exemplo()
    print(f"o exemplo da instrução hoje: {' · '.join(exemplo) if exemplo else '(nenhum)'}\n")

    achados = []
    for m in C.todas():
        p = plano(m)
        if p:
            achados.append((m, *p))
    if not achados:
        print("nenhuma claquete chutada nos filtros: o cache já está em dia.")
        return 0

    notas = sum(a[2] for a in achados)
    campos = sum(a[3] for a in achados)
    promovidos = sum(a[4] for a in achados)
    print(f"{len(achados)} mídia(s): {notas} leitura(s) a marcar como hipótese e "
          f"{campos} campo(s) de topo a tirar dos filtros"
          + (f" (e {promovidos} a acrescentar, de leitura que confere)"
             if promovidos else "") + "\n")
    for m, _, r, t, p in achados[:40]:
        print(f"  [{m.origem:8s}] {(m.nome or m.chave[:12])[:40]:40s}  "
              f"{r} reprovada(s), -{t} campo(s)" + (f", +{p}" if p else ""))
    if len(achados) > 40:
        print(f"  … e mais {len(achados) - 40}")
    if not fazer:
        print("\n(nada foi tocado — rode com --fazer para limpar)")
        return 0

    for m, novas, *_ in achados:
        C.escrever_atomico(m.pasta / "notas.json",
                           json.dumps({"notas": novas}, ensure_ascii=False, indent=1)
                           .encode("utf-8"))
    print(f"\n{len(achados)} mídia(s) limpas. A claquete lida continua em cada nota, com o "
          f"aviso — o que saiu foi o número dos filtros.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
