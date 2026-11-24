"""O nome técnico de uma ferramenta → o que ela está fazendo, em português de editor.

⭐⭐ **É a diferença entre "acompanhar" e "assistir a um log rolar".** O painel mostrava
`transcrever · CENAS/C07.avb · C07_P02-T002` — verdadeiro, e ilegível para quem edita. O
editor pediu linhas como as do Claude Code: um verbo, um alvo, e nada de nome de função.

```
ler_o_que_ja_sabemos + {bin, item}   →   "Confere o que já sabe de C07_P02-T002"
transcrever          + {bin, item}   →   "Ouve o take C07_P02-T002"
montar_corte         + {nome, cortes}→   "Monta “C07 v3” — 14 cortes"
```

⚠️ **Mora no serviço, e não no painel.** Mesma razão do `portao.NOMES`: o vocabulário que
o editor lê é decisão de produto, não de apresentação — e o painel tem a regra de não
carregar lógica de domínio (ver CLAUDE.md). Uma ferramenta nova ganha a frase dela aqui,
num lugar só.

⚠️ Ferramenta sem frase própria **não some da tela**: vira o nome com os sublinhados
trocados por espaço. Degradar é legível; esconder é o editor perguntando "e aí, morreu?".
"""

from __future__ import annotations

from pathlib import Path

from typing import Any


def _alvo(entrada: dict[str, Any]) -> str:
    """O que a chamada está tocando, na ordem em que o editor reconheceria."""
    for chave in ("item", "take", "nome", "bin", "caminho"):
        valor = entrada.get(chave)
        if isinstance(valor, str) and valor.strip():
            # A bin vem com caminho; o editor reconhece pelo fim dele.
            if chave in ("bin", "caminho"):
                return valor.replace("\\", "/").rstrip("/").split("/")[-1]
            return valor
    return ""


def resumir(nome: str, entrada: dict[str, Any] | None) -> str:
    """Uma linha que o editor lê sem traduzir. Nunca vazia."""
    entrada = entrada or {}
    curto = nome.removeprefix("mcp__ciclo__")
    alvo = _alvo(entrada)

    if curto == "estado_do_projeto":
        return "Vê o projeto aberto"
    if curto == "listar_bins":
        return "Lista as bins do projeto"
    if curto == "listar_itens_da_bin":
        return f"Abre a bin {alvo}" if alvo else "Abre uma bin"
    if curto == "resolver_take":
        return f"Localiza o take {alvo}" if alvo else "Localiza um take"
    if curto == "ler_o_que_ja_sabemos":
        return f"Confere o que já sabe de {alvo}" if alvo else "Confere o que já sabe"
    if curto == "ver_frames":
        quantos = entrada.get("quantos")
        quadros = f"{quantos} quadros" if isinstance(quantos, int) else "os quadros"
        return f"Vê {quadros} de {alvo}" if alvo else f"Vê {quadros}"
    if curto == "transcrever":
        return f"Ouve o take {alvo}" if alvo else "Ouve o take"
    if curto == "anotar_o_que_vi":
        return f"Anota o que viu em {alvo}" if alvo else "Anota o que viu"
    if curto == "montar_corte":
        cortes = entrada.get("cortes")
        quantos = len(cortes) if isinstance(cortes, list) else 0
        nome_da_sequencia = str(entrada.get("nome") or "").strip()
        pedaco = f" — {quantos} cortes" if quantos else ""
        return (f"Monta “{nome_da_sequencia}”{pedaco}" if nome_da_sequencia
                else f"Monta o corte{pedaco}")

    if curto == "separar_falas":
        falas = entrada.get("falas")
        quantas = len({f.get("fala") for f in falas if isinstance(f, dict)}) \
            if isinstance(falas, list) else 0
        cena = str(entrada.get("cena") or "").strip()
        pedaco = f" — {quantas} {'fala' if quantas == 1 else 'falas'}" if quantas else ""
        # ⭐ O que ficou de fora e para onde vai estão no cartão, e não só na resposta: é
        #   antes de aprovar que o editor precisa saber que a bin não terá tudo (2026-09-15).
        de_fora = entrada.get("deixadas_de_fora")
        if isinstance(de_fora, list) and de_fora:
            pedaco += f", {len(de_fora)} {'item' if len(de_fora) == 1 else 'itens'} de fora"
        destino = str(entrada.get("acrescentar_em") or "").strip()
        if destino:
            pedaco += f", em {Path(destino).stem}"
        return f"Separa as falas da cena {cena}{pedaco}" if cena else f"Separa as falas{pedaco}"
    if curto in ("ler_timeline", "conferir_a_edicao", "editar_timeline"):
        seq = str(entrada.get("sequencia") or "").strip()
        # O MobID que veio do monitor não diz nada ao editor; o nome, sim.
        seq = "" if len(seq) > 40 and " " not in seq else seq
        ops = entrada.get("operacoes")
        conta = f" — {len(ops)} {'edição' if len(ops) == 1 else 'edições'}" \
            if isinstance(ops, list) and ops else ""
        verbo = {"ler_timeline": "Lê a timeline", "conferir_a_edicao": "Confere a edição em",
                 "editar_timeline": "Edita uma cópia de"}[curto]
        if curto == "ler_timeline":
            return f"{verbo} {seq}" if seq else verbo
        return f"{verbo} “{seq}”{conta}" if seq else f"{verbo} a timeline{conta}"

    # Ferramenta que ainda não ganhou frase: o nome legível já diz mais que o técnico.
    legivel = curto.replace("_", " ")
    return f"{legivel} · {alvo}" if alvo else legivel
