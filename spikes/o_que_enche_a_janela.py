"""Spike — para onde foi o crédito de uma sessão: ferramenta por ferramenta.

    python spikes/o_que_enche_a_janela.py                  # a sessão mais recente
    python spikes/o_que_enche_a_janela.py 705dc703         # por prefixo de id
    python spikes/o_que_enche_a_janela.py C:\\...\\x.jsonl   # por caminho

## Por que

Em 2026-09-12 o editor montou a cena C07 e disse que "o custo da sessão dentro do app está
muito grande". O modelo de dentro do app escreveu um pós-mortem apontando as transcrições
de 60 KB como o maior gasto. **Estava errado** — e não havia como saber, porque
`mcp/servidor.py` não mede nada: nem bytes, nem duração, nem quantas vezes cada ferramenta
foi chamada. A pergunta "qual ferramenta encheu a janela" era inrespondível.

Este spike responde lendo o transcript que o CLI já grava em
`~/.claude/projects/<projeto>/<id>.jsonl`. Ele não instrumenta nada e não custa turno:
é arqueologia sobre o que já aconteceu.

⚠️⚠️ **O CLI grava a MESMA mensagem várias vezes** (medido: 3,0× nesta sessão — cada bloco
de conteúdo vira uma linha, repetindo o `usage` inteiro). Somar sem deduplicar por
`message.id` triplica a conta. Foi assim que a primeira leitura desta sessão devolveu
34 milhões de tokens onde havia 11.

⚠️ **Não existe campo de custo no transcript** — nem `total_cost_usd`, nem evento `result`;
esses só existem no stream ao vivo. Então o dólar aqui é DERIVADO de uma tabela de preço
pública, e vem marcado como derivado. Numa assinatura ele nem é a moeda certa: o que
esgota é a janela de 5 h, e essa o transcript não carrega — está na barra do painel.

Sai `0` se conseguiu ler a sessão e somar pelo menos uma chamada de API.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: Preço de tabela por milhão de tokens, para DERIVAR uma ordem de grandeza.
#: ⚠️ Não é o que o editor paga: ele está numa assinatura. Serve para ranquear onde o
#: gasto se concentra, não para dizer quanto custou.
PRECO_POR_MTOK = {
    "entrada": 3.00,
    "cache_escrito": 3.75,
    "cache_lido": 0.30,
    "saida": 15.00,
}

#: O CLI persiste em arquivo qualquer resposta grande demais e devolve ISTO no lugar.
#: ⛔ O texto do erro NÃO diz de que chamada ele é — só o caminho de um arquivo com nome
#: de timestamp. Com chamadas em paralelo, o modelo perde o mapeamento e remonta na mão.
MARCAS_DE_ESTOURO = ("exceeds maximum allowed tokens", "<persisted-output>")


def raiz_dos_projetos() -> Path:
    return Path.home() / ".claude" / "projects"


def achar_sessao(alvo: str) -> Path:
    """O `.jsonl` da sessão: por caminho, por prefixo de id, ou a mais recente."""
    if alvo:
        direto = Path(alvo)
        if direto.is_file():
            return direto
        achados = list(raiz_dos_projetos().rglob(f"{alvo}*.jsonl"))
        if achados:
            # ⚠️ O MESMO id pode existir em mais de uma pasta de projeto — o CLI
            #    indexa por cwd, e o serviço já rodou de pastas diferentes. Ordem
            #    alfabética escolheria a errada em silêncio; a maior é a que tem a
            #    sessão de verdade.
            return max(achados, key=lambda p: p.stat().st_size)
        sys.exit(f"não achei sessão para {alvo!r} em {raiz_dos_projetos()}")
    todas = list(raiz_dos_projetos().rglob("*.jsonl"))
    if not todas:
        sys.exit(f"nenhuma sessão em {raiz_dos_projetos()}")
    return max(todas, key=lambda p: p.stat().st_mtime)


def ler(caminho: Path) -> list[dict]:
    linhas = []
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            linhas.append(json.loads(linha))
        except json.JSONDecodeError:
            continue  # linha truncada no fim do arquivo é normal: a sessão pode estar viva
    return linhas


def blocos(linhas: list[dict], tipo: str):
    """Todo bloco de conteúdo do tipo pedido, já sem a repetição do CLI."""
    vistos = set()
    for linha in linhas:
        msg = linha.get("message") or {}
        conteudo = msg.get("content")
        if not isinstance(conteudo, list):
            continue
        for bloco in conteudo:
            if not isinstance(bloco, dict) or bloco.get("type") != tipo:
                continue
            chave = bloco.get("id") or bloco.get("tool_use_id")
            if chave in vistos:
                continue
            vistos.add(chave)
            yield linha, bloco


def texto_do_resultado(bloco: dict) -> str:
    conteudo = bloco.get("content")
    if isinstance(conteudo, str):
        return conteudo
    return json.dumps(conteudo, ensure_ascii=False)


def por_dia(linhas: list[dict]) -> dict[str, list[dict]]:
    agrupado: dict[str, list[dict]] = collections.defaultdict(list)
    for linha in linhas:
        agrupado[(linha.get("timestamp") or "?")[:10]].append(linha)
    return agrupado


def somar_api(linhas: list[dict]) -> tuple[dict[str, int], list[int], int, int]:
    """Tokens por tipo, deduplicados por `message.id`.

    ⚠️⚠️ A deduplicação é o coração deste spike. Sem ela a conta sai 3× maior.
    """
    total = collections.Counter()
    contextos: list[int] = []
    vistos: set[str] = set()
    brutas = 0
    for linha in linhas:
        if linha.get("type") != "assistant":
            continue
        msg = linha.get("message") or {}
        uso = msg.get("usage") or {}
        if not uso:
            continue
        brutas += 1
        ident = msg.get("id")
        if ident in vistos:
            continue
        vistos.add(ident)
        entrada = uso.get("input_tokens") or 0
        escrito = uso.get("cache_creation_input_tokens") or 0
        lido = uso.get("cache_read_input_tokens") or 0
        total["entrada"] += entrada
        total["cache_escrito"] += escrito
        total["cache_lido"] += lido
        total["saida"] += uso.get("output_tokens") or 0
        # O que atravessou a janela nesta ida ao modelo. O cache não é cobrado igual,
        # mas ocupa contexto igual.
        contextos.append(entrada + escrito + lido)
    return dict(total), contextos, len(vistos), brutas


def relatar(linhas: list[dict], titulo: str) -> bool:
    tokens, contextos, chamadas, brutas = somar_api(linhas)
    if not chamadas:
        return False

    print()
    print("=" * 74)
    print(titulo)
    print("=" * 74)

    eco = brutas / chamadas if chamadas else 1.0
    print(f"\n  {chamadas} chamadas de API  "
          f"(o CLI gravou {brutas} linhas — eco de {eco:.1f}×, deduplicado)")

    print("\n  TOKENS")
    for campo in ("entrada", "cache_escrito", "cache_lido", "saida"):
        print(f"    {campo:16} {tokens.get(campo, 0):14,}")

    derivado = sum(tokens.get(k, 0) * v for k, v in PRECO_POR_MTOK.items()) / 1e6
    print(f"\n  DERIVADO de preço de tabela (⚠️ não é o que a assinatura cobra): "
          f"US$ {derivado:.2f}")
    for campo, preco in sorted(PRECO_POR_MTOK.items(),
                               key=lambda kv: -tokens.get(kv[0], 0) * kv[1]):
        parte = tokens.get(campo, 0) * preco / 1e6
        if parte:
            print(f"    {campo:16} US$ {parte:6.2f}   ({100 * parte / derivado:4.1f}%)")

    if contextos:
        print(f"\n  JANELA DE CONTEXTO")
        print(f"    no começo        {contextos[0]:14,} tokens")
        print(f"    no fim           {contextos[-1]:14,} tokens")
        print(f"    cresceu          {contextos[-1] - contextos[0]:14,} tokens")
        if contextos[0] > 50_000:
            print(f"    ⚠️ a sessão ABRIU com {contextos[0]:,} tokens — conversa retomada "
                  f"sem /clear")

    # ── ferramentas ────────────────────────────────────────────────────────────────
    nomes: dict[str, str] = {}
    entradas = collections.Counter()
    paralelos = []
    for linha, bloco in blocos(linhas, "tool_use"):
        nomes[bloco["id"]] = bloco.get("name") or "?"
        entradas[bloco.get("name") or "?"] += len(
            json.dumps(bloco.get("input") or {}, ensure_ascii=False))

    # Quantas tool_use saíram na MESMA mensagem = quantas o modelo disparou em paralelo.
    por_msg = collections.defaultdict(set)
    for linha, bloco in blocos(linhas, "tool_use"):
        por_msg[(linha.get("message") or {}).get("id")].add(bloco["id"])
    maior = max((len(v) for v in por_msg.values()), default=0)

    saidas = collections.defaultdict(list)
    estouros = collections.Counter()
    for _, bloco in blocos(linhas, "tool_result"):
        nome = nomes.get(bloco.get("tool_use_id"), "?")
        texto = texto_do_resultado(bloco)
        saidas[nome].append(len(texto))
        if any(m in texto[:400] for m in MARCAS_DE_ESTOURO):
            estouros[nome] += 1

    if saidas:
        print("\n  O QUE CADA FERRAMENTA DEVOLVEU AO MODELO")
        print(f"    {'ferramenta':32} {'n':>3} {'total':>10} {'maior':>9} {'estourou':>9}")
        total_saida = 0
        for nome, tamanhos in sorted(saidas.items(), key=lambda kv: -sum(kv[1])):
            total_saida += sum(tamanhos)
            furo = estouros.get(nome, 0)
            print(f"    {nome[:32]:32} {len(tamanhos):3} {sum(tamanhos):10,} "
                  f"{max(tamanhos):9,} {(str(furo) if furo else '-'):>9}")
        print(f"    {'TOTAL':32} {'':3} {total_saida:10,} "
              f"(~{total_saida // 4:,} tokens)")
        lido = tokens.get("cache_lido", 0) + tokens.get("cache_escrito", 0)
        if lido:
            print(f"\n    ⇒ a saída de ferramenta é {100 * (total_saida // 4) / lido:.1f}% "
                  f"do que foi lido de contexto.")
            print(f"      O que custa não é o payload — é o contexto que ele deixa para "
                  f"trás,")
            print(f"      recobrado em cada uma das {chamadas} idas ao modelo.")

    if maior > 1:
        print(f"\n  ⚠️ até {maior} ferramentas foram disparadas EM PARALELO num só bloco.")
        if estouros:
            print(f"     Com estouro junto, o modelo perde de vista qual arquivo é de "
                  f"qual chamada:")
            print(f"     o texto do erro só traz um caminho com nome de timestamp.")

    return True


def main() -> int:
    alvo = sys.argv[1] if len(sys.argv) > 1 else ""
    caminho = achar_sessao(alvo)
    linhas = ler(caminho)

    print(f"sessão: {caminho}")
    print(f"        {len(linhas):,} linhas")

    dias = por_dia(linhas)
    print(f"        linhas por dia: "
          f"{ {d: len(v) for d, v in sorted(dias.items())} }")

    houve = relatar(linhas, "A SESSÃO INTEIRA")
    if len(dias) > 1:
        for dia, doa in sorted(dias.items()):
            if dia != "?":
                relatar(doa, f"SÓ {dia}")

    if not houve:
        print("\nnenhuma chamada de API com `usage` nesta sessão.")
        return 1

    print()
    print("⚠️ A janela de 5 h da assinatura NÃO está no transcript — ela chega no")
    print("   `rate_limit_event` do stream ao vivo e só aparece na barra do painel.")
    print("   Numa assinatura é ELA que esgota, não o dólar derivado acima.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
