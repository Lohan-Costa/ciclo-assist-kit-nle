"""Spike — quanto da transcrição era ruído, medido no cache real.

    python spikes/a_transcricao_magra.py

## Por que

Em 2026-09-12, montando a C07, **12 de 14 transcrições estouraram o limite de saída do
CLI**. O modelo recebia `Error: result (61.559 characters) exceeds maximum allowed tokens`
mais um caminho de arquivo, via as duas primeiras falas de cinquenta, e remontava o resto
com 13 Greps — de onde saiu o erro de aplicar o timestamp de um take em outro.

A causa era o array de palavras: o ASR marca o tempo de CADA palavra, e isso saía em toda
transcrição, sempre, sem parâmetro que desligasse. Este spike mede quanto disso era ruído
— usando o cache que já está no disco e a função de produção
(`mcp/ferramentas/fala.formatar_fala`), não uma maquete.

⚠️ O limite exato do CLI não é publicado. MEDIDO por bracketing na sessão real: uma
resposta de 20.201 chars passou inteira e uma de 55.844 estourou. O alvo aqui é ficar
com folga abaixo da borda de baixo.

Sai `0` se achou cache e se o formato padrão couber com folga.
"""

from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.mcp.ferramentas.fala import (  # noqa: E402
    ORCAMENTO_CHARS, formatar_fala, paginar)
from cicloassist.midia import asr as _asr  # noqa: E402
from cicloassist.midia import cache as _cache  # noqa: E402

#: A menor resposta que sabemos ter ESTOURADO, e a maior que sabemos ter passado.
PASSOU_CHARS = 20_201
ESTOUROU_CHARS = 55_844

#: A taxa do material da C07. Não muda o veredito — muda só a coluna de frames.
TAXA = Fraction(24000, 1001)


def antes(f: dict, inicio_s: float) -> dict:
    """O formato que existia até 2026-09-12, para a comparação ser honesta."""
    return {
        "inicio_no_take": round(float(f["inicio"]) - inicio_s, 2),
        "fim_no_take": round(float(f["fim"]) - inicio_s, 2),
        "entrada_do_corte": round(float(f["corte_inicio"]) - inicio_s, 2),
        "saida_do_corte": round(float(f["corte_fim"]) - inicio_s, 2),
        "vao_ate_a_proxima": f.get("vao_ate_a_proxima"),
        "inicio_no_master": f["inicio"],
        "texto": f["texto"],
        "certeza": f.get("certeza"),
        "palavras": [
            {"palavra": w.get("palavra"),
             "inicio_no_take": round(float(w.get("t", 0)) - inicio_s, 2),
             "fim_no_take": round(float(w.get("fim", 0)) - inicio_s, 2)}
            for w in (f.get("palavras") or [])
        ],
    }


def tamanho(falas: list[dict]) -> int:
    """Como o servidor MCP serializa de verdade (`servidor.normalizar`)."""
    return len(json.dumps(falas, ensure_ascii=False, indent=2))


def main() -> int:
    raiz = _cache.raiz()
    print(f"cache: {raiz}")
    if not raiz.is_dir():
        sys.exit("não há cache nesta máquina — rode uma transcrição antes.")

    midias = []
    for arquivo in sorted(raiz.glob("*/transcricao.json")):
        try:
            falas = (json.loads(arquivo.read_text(encoding="utf-8")) or {}).get("falas")
        except (OSError, json.JSONDecodeError):
            continue
        if falas:
            midias.append((arquivo.parent.name, falas))
    if not midias:
        sys.exit("nenhuma transcrição não-vazia no cache.")

    # As maiores primeiro: são elas que estouravam.
    midias.sort(key=lambda kv: -len(kv[1]))
    midias = midias[:8]

    print(f"{len(midias)} mídia(s) com fala, as maiores primeiro\n")
    print(f"  {'falas':>5}  {'ANTES':>9}  {'agora':>9} {'pág':>5}  {'+palavras':>9}"
          f"   o que ANTES fazia")
    print("  " + "-" * 70)

    soma = {"antes": 0, "agora": 0, "palavra": 0}
    pior_pagina = 0
    estourava = 0
    for _, falas in midias:
        com = _asr.com_respiro(falas, piso_s=0.0, teto_s=10**9)
        t_antes = tamanho([antes(f, 0.0) for f in com])

        # ⭐ O que VIAJA hoje é a primeira página, não a lista inteira.
        todas = [formatar_fala(f, 0.0, TAXA) for f in com]
        pagina, proxima = paginar(todas, 0)
        t_agora = tamanho(pagina)

        com_palavra = [formatar_fala(f, 0.0, TAXA, por_palavra=True) for f in com]
        t_palavra = tamanho(paginar(com_palavra, 0)[0])

        soma["antes"] += t_antes
        soma["agora"] += t_agora
        soma["palavra"] += t_palavra
        pior_pagina = max(pior_pagina, t_agora, t_palavra)

        if t_antes > ESTOUROU_CHARS:
            veredito = "ESTOURAVA"
            estourava += 1
        elif t_antes > PASSOU_CHARS:
            veredito = "zona de risco"
        else:
            veredito = "já cabia"
        paginas = f"{len(pagina)}/{len(com)}" if proxima else "tudo"
        print(f"  {len(com):5}  {t_antes:9,}  {t_agora:9,} {paginas:>5}  {t_palavra:9,}"
              f"   {veredito}")

    print("  " + "-" * 70)
    print(f"\n  {estourava} de {len(midias)} mídias ESTOURAVAM o limite do CLI antes.")
    print(f"\n  a maior resposta que viaja hoje: {pior_pagina:,} chars")
    print(f"    orçamento da paginação ................ {ORCAMENTO_CHARS:,}")
    print(f"    passou inteira na sessão real ......... até {PASSOU_CHARS:,}")
    print(f"    estourou na sessão real ............... a partir de {ESTOUROU_CHARS:,}")

    # Uma mídia de porte de TAKE, para a comparação de economia ser honesta: a de 257
    # falas é um master inteiro, e nenhum take tem esse tamanho.
    porte_de_take = [(len(_asr.com_respiro(f, piso_s=0.0, teto_s=10**9)), f)
                     for _, f in midias]
    porte_de_take = [(n, f) for n, f in porte_de_take if n <= 80]
    if porte_de_take:
        a = sum(tamanho([antes(x, 0.0) for x in _asr.com_respiro(f, 0.0, 10**9)])
                for _, f in porte_de_take)
        d = sum(tamanho([formatar_fala(x, 0.0, TAXA)
                         for x in _asr.com_respiro(f, 0.0, 10**9)])
                for _, f in porte_de_take)
        print(f"\n  em {len(porte_de_take)} mídias de porte de TAKE (≤80 falas):")
        print(f"    antes  {a:8,} chars  (~{a // 4:7,} tokens)")
        print(f"    agora  {d:8,} chars  (~{d // 4:7,} tokens)   {100 * d / a:.0f}% do "
              f"que era")

    folgado = pior_pagina <= ORCAMENTO_CHARS
    print(f"\n  {'✓' if folgado else '✗'} nada que viaja passa do orçamento")
    print(f"  ⚠️ o cache NÃO foi reprocessado: o ASR segue medindo por palavra e a"
          f" ASSINATURA não mudou.")
    return 0 if folgado else 1


if __name__ == "__main__":
    raise SystemExit(main())
