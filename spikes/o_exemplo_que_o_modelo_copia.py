"""O exemplo da instrução vira resposta: quanto, e o que o conserta.

⛔⛔ MEDIDO no cache real em 2026-09-23: **30 de 50 mídias com micro feita** devolveram a
cena/plano/take do EXEMPLO da instrução (`X07 · 31 · 8 · 5`) como se as tivesse lido. O
banco (`transversal/ia-embarcada-nos-nles.md` §3c) já registrava *"o modelo local copia o
exemplo"*, e por isso o exemplo deixou de ser uma claquete do acervo — mas `31 · 8 · 5`
continua sendo um valor **plausível**, e a cópia continua indistinguível de leitura.

A conferência do rolo pega parte: `A009_…` contra o rolo lido. Ela **não pega** o caso em
que o modelo lê o rolo certo e copia o resto — medido, **8 notas de 4 mídias** ficaram com
`31 · 8 · 5` marcadas como fato.

⭐⭐ **A PRIMEIRA RODADA (2026-09-23, 8 mídias, qwen3-vl:8b) mudou o diagnóstico.** Olhando
os quadros da cabeça COM OS OLHOS: as 4 mídias que "copiaram o exemplo" **não têm claquete
nenhuma** (plano de sala, ninguém com prancheta), e as 4 que leram certo têm a claquete de
"PRODUCAO-A" enchendo o quadro. ⇒ O defeito não é ler mal: é **inventar na AUSÊNCIA**, e
o que ele inventa é o que está escrito na instrução. Com claquete na tela, 4 de 4 certas.

Medido, com o exemplo impreenchível (`‹cena›`): as cópias de `31 · 8 · 5` caíram de 3 para
**0** e nenhum `‹…›` voltou — mas o modelo passou a copiar **o outro literal da instrução**,
a frase `"01-2"/"12A" = cena 01 plano 2`, devolvendo `rolo ["01-2"] · cena 01 · plano 2` em
3 das 4. ⇒ Ele copia QUALQUER valor literal do prompt, não só o do bloco de exemplo.

    python spikes/o_exemplo_que_o_modelo_copia.py                    # hoje x sem-exemplo
    python spikes/o_exemplo_que_o_modelo_copia.py --variantes hoje,lugar
    python spikes/o_exemplo_que_o_modelo_copia.py --quantas 2

Sai `0` se a variante nova inventar menos e não estragar as claquetes que já liam certo.
⚠️ Exige o Mac configurado (`CICLOASSIST_OLLAMA` ou o `config.json`): ~95 s por pedido —
8 mídias × 2 variantes passam de meia hora.
⛔ **Em segundo plano, rode com `python -u`**: sem isso a saída fica no buffer até o fim, e
uma rodada interrompida no meio não deixa NADA — aconteceu em 2026-09-23, com 16 pedidos
perdidos que o Mac já tinha respondido.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.midia import cache as _cache                       # noqa: E402
from cicloassist.motor import decupador as _dec                     # noqa: E402
from cicloassist.motor import percepcao as _perc                    # noqa: E402

#: O exemplo de hoje, e o valor que ele põe na boca do modelo.
EXEMPLO_DE_HOJE = ("31", "8", "5")

#: ⭐ Variante "lugar": o mesmo texto, com o LUGAR do valor em vez do valor. Um `‹…›` não é
#: número de cena nenhum — copiá-lo é uma resposta que se denuncia.
#: ⚠️ MEDIDO: acaba com o eco de `31 · 8 · 5`, e o modelo passa a copiar o `"01-2"` da
#: frase seguinte. Um prompt sem exemplo nenhum é o que a variante `sem-exemplo` testa.
CLAQUETE_LUGAR = (
    'Quadros CABEÇA = começo do take, maiores. Havendo claquete, leia: "claquete": '
    '{"rolo": ["‹rolo›"], "cena": "‹cena›", "plano": "‹plano›", "take": "‹tomada›", '
    '"serie": false, "marcas": [], "texto": "como está"} — cada ‹…› é o LUGAR do que você '
    'ler, nunca a resposta. Rolo = câmera+cartão, pode ser mais '
    'de um; tomada = take; "01-2"/"12A" = cena 01 plano 2; marcas = PICKUP, MOS… escritas '
    'nela. Pequena ou borrada: {"legivel": false}. Sem claquete, omita. Nunca chute.'
)

#: ⭐⭐ Variante "sem-exemplo": nenhum valor literal para copiar, e a AUSÊNCIA dita como o
#: caso comum — que é o que os quadros mostram (a maioria das mídias não tem claquete, e é
#: exatamente aí que ele inventava). A ordem também muda: primeiro COPIAR o que está
#: escrito, depois tirar os campos dali.
CLAQUETE_SEM_EXEMPLO = (
    'Quadros CABEÇA = começo do take, maiores. A maioria das mídias NÃO tem claquete: só '
    'responda "claquete" se VIR no quadro uma prancheta escrita — não vendo, omita o campo '
    'inteiro, e isso é o normal. Vendo uma: "claquete": {"texto": copie o que está escrito, '
    'e dele tire "rolo" (lista), "cena", "plano", "take", "serie" (true/false) e "marcas" '
    '(PICKUP, MOS…)} — todo valor sai do que você leu no quadro, nunca deste texto. Rolo = '
    'câmera+cartão, pode ser mais de um; tomada = take; cena e plano podem vir juntos num '
    'campo só, separe-os. Pequena ou borrada: {"legivel": false}. Nunca chute.'
)

#: ⛔⛔ E a `sem-exemplo` REPROVOU, por uma causa que o banco já tinha medido: **campo fora
#: da estrutura JSON não é respondido**. Tirando os campos do objeto e pondo em prosa
#: ("copie o texto e dele tire rolo, cena…"), as 4 claquetes legíveis voltaram VAZIAS — e
#: não por não ver: numa delas o `texto` veio com a claquete INTEIRA e certa (produção,
#: `A01 ROLO 4 CENA 2 PLANO 2 TOMADA`, o cameraman e a data) e nenhum campo preenchido.
#:
#: ⭐⭐ Variante "lugar-limpo": a ESTRUTURA de hoje (que faz os campos serem respondidos),
#: com o LUGAR do valor em vez do valor, **nenhum literal na prosa** (o `"01-2"/"12A"` saiu,
#: que foi o que a `lugar` passou a copiar) e a AUSÊNCIA dita como o caso comum — que é o
#: que os quadros mostram. O `texto` pede transcrição, e ela provou funcionar acima.
CLAQUETE_LUGAR_LIMPO = (
    'Quadros CABEÇA = começo do take, maiores. A maioria das mídias NÃO tem claquete: só '
    'responda "claquete" se VIR no quadro uma prancheta escrita — não vendo uma, omita o '
    'campo inteiro, e isso é o normal. Vendo uma: "claquete": {"texto": "copie aqui o que '
    'está escrito", "rolo": ["‹rolo›"], "cena": "‹cena›", "plano": "‹plano›", "take": '
    '"‹tomada›", "serie": false, "marcas": []} — cada ‹…› é o LUGAR do que você leu no '
    'quadro, nunca a resposta. Rolo = câmera+cartão, pode ser mais de um; tomada = take; '
    'cena e plano podem vir juntos num campo só, separe-os; marcas = PICKUP, MOS… escritas '
    'nela. Pequena ou borrada: {"legivel": false}. Nunca chute.'
)

VARIANTES = {"hoje": None, "lugar": CLAQUETE_LUGAR, "sem-exemplo": CLAQUETE_SEM_EXEMPLO,
             "lugar-limpo": CLAQUETE_LUGAR_LIMPO}


def _claquetes_do_cache() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(suspeitas, controles) — `(chave, nome)` de mídias com claquete lida.

    Suspeita = a nota trouxe o valor do exemplo. Controle = a leitura foi conferida contra
    o nome do arquivo e bateu.
    """
    suspeitas: list[tuple[str, str]] = []
    controles: list[tuple[str, str]] = []
    for midia in _cache.todas():
        nome = midia.manifesto().get("nome") or midia.chave[:12]
        for n in midia.ler_notas():
            q = n.get("claquete") or {}
            if not isinstance(q, dict) or not q.get("legivel"):
                continue
            if (q.get("cena"), q.get("plano"), q.get("take")) == EXEMPLO_DE_HOJE:
                suspeitas.append((midia.chave, nome))
            elif q.get("conferido"):
                controles.append((midia.chave, nome))
            break
    return suspeitas, controles


def _ler(url: str, chave: str, variante: str) -> dict:
    """Um pedido ao Mac com a variante pedida. Devolve a claquete crua da resposta."""
    from cicloassist.mcp.ferramentas.midia import quadros_da_cabeca, quadros_de

    jpegs, posicoes, clipe = quadros_de(chave, _dec.QUADROS)
    cabeca, segundos = quadros_da_cabeca(chave)
    corpo = _perc.corpo_do_pedido(jpegs, posicoes, clipe, chave, _perc.MODELO,
                                  cabeca, segundos)
    troca = VARIANTES[variante]
    if troca:
        sistema = corpo["messages"][0]["content"]
        assert _dec.CLAQUETE in sistema, "a PERSONA mudou; reveja este spike"
        corpo["messages"][0]["content"] = sistema.replace(_dec.CLAQUETE, troca)
    resposta = _perc.pedir(url, "/api/chat", corpo, timeout=_perc.PRAZO_S)
    dados = _dec._json_da_resposta((resposta.get("message") or {}).get("content") or "")
    if len(dados) == 1 and "descricao" not in dados:
        dados = next(iter(dados.values()))
    q = dados.get("claquete")
    return q if isinstance(q, dict) else {}


def _campos(q: dict) -> tuple[str, str, str]:
    """cena/plano/take como texto — `take` aceita o `tomada` que o modelo às vezes usa."""
    return (str(q.get("cena") or ""), str(q.get("plano") or ""),
            str(q.get("take") or q.get("tomada") or ""))


def _resumo(q: dict) -> str:
    if not q:
        return "sem claquete (omitiu)"
    if q.get("legivel") is False:
        return "ilegível (dito)"
    c, pl, t = _campos(q)
    return f"rolo {q.get('rolo')} · cena {c} · plano {pl} · take {t}"


def _inventou(q: dict) -> str:
    """O que nesta resposta veio do PROMPT em vez do quadro — "" se nada.

    ⚠️ Só pega o eco literal. Um chute genérico (`01 · 01 · 01`, medido) passa por aqui
    limpo, e é por isso que a conferência do produto não vive deste critério.
    """
    if not q:
        return ""
    valores = [*_campos(q), *[str(r) for r in (q.get("rolo") or [])], str(q.get("texto") or "")]
    if tuple(_campos(q)) == EXEMPLO_DE_HOJE:
        return "o exemplo 31·8·5"
    if any("‹" in v for v in valores):
        return "o LUGAR do valor (‹…›)"
    if any(v in ("01-2", "12A", "X07") for v in valores):
        return "um literal da instrução"
    if str(q.get("texto") or "") == "como está":
        return 'o texto "como está"'
    return ""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quantas", type=int, default=4,
                   help="quantas suspeitas e quantos controles (padrão 4 de cada)")
    p.add_argument("--variantes", default="hoje,sem-exemplo",
                   help=f"quais medir, separadas por vírgula: {', '.join(VARIANTES)}")
    args = p.parse_args()
    variantes = [v.strip() for v in args.variantes.split(",") if v.strip()]
    for v in variantes:
        if v not in VARIANTES:
            print(f"⛔ variante desconhecida: {v} (há {', '.join(VARIANTES)})")
            return 2

    url = _perc.endereco()
    if not url:
        print("⛔ sem o endereço do Mac (CICLOASSIST_OLLAMA ou config.json)")
        return 2
    _perc.conferir(url)
    print(f"Mac: {url} · {_perc.MODELO} · variantes: {', '.join(variantes)}\n")

    suspeitas, controles = _claquetes_do_cache()
    alvos = [(c, n, "chutou") for c, n in suspeitas[:args.quantas]]
    alvos += [(c, n, "leu") for c, n in controles[:args.quantas]]
    if not alvos:
        print("⛔ o cache não tem claquete lida para medir")
        return 2
    print(f"{len(alvos)} mídia(s): {sum(1 for a in alvos if a[2] == 'chutou')} que copiaram "
          f"o exemplo e {sum(1 for a in alvos if a[2] == 'leu')} que liam certo\n")

    ecos = dict.fromkeys(variantes, 0)
    inventou_sem_claquete = dict.fromkeys(variantes, 0)
    perdeu_leitura = dict.fromkeys(variantes, 0)
    for chave, nome, era in alvos:
        lido = {}
        for v in variantes:
            comeco = time.monotonic()
            try:
                q = _ler(url, chave, v)
            except Exception as e:                       # noqa: BLE001 — é medição
                print(f"  {nome:34.34} [{v}] falhou ({e})")
                q = {}
            lido[v] = q
            if _inventou(q):
                ecos[v] += 1
            # ⭐ O que interessa de verdade na mídia SEM claquete: ele respondeu alguma?
            if era == "chutou" and q and q.get("legivel") is not False:
                inventou_sem_claquete[v] += 1
            print(f"  {nome:34.34} [{v:11.11}] {time.monotonic() - comeco:5.0f}s  "
                  f"{_resumo(q)}" + (f"   ⇠ {_inventou(q)}" if _inventou(q) else ""))
        if era == "leu":
            # ⚠️ O controle compara cena/plano/take, e nada mais: a primeira versão deste
            #    spike exigia a chave `legivel` — que o MODELO não escreve — e acusou os 4
            #    controles de terem mudado quando os 4 estavam idênticos.
            base = _campos(lido[variantes[0]])
            for v in variantes[1:]:
                if _campos(lido[v]) != base:
                    perdeu_leitura[v] += 1
                    print(f"       ↳ ⚠️ [{v}] a leitura mudou: {base} → {_campos(lido[v])}")
        print()

    print("por variante — eco do prompt · inventou onde não há claquete · leitura perdida")
    for v in variantes:
        print(f"  {v:11.11}  {ecos[v]:>2} · {inventou_sem_claquete[v]:>2} · "
              f"{perdeu_leitura[v]:>2}")
    base = variantes[0]
    melhor = [v for v in variantes[1:]
              if inventou_sem_claquete[v] < inventou_sem_claquete[base]
              and perdeu_leitura[v] == 0]
    print("✅ " + ", ".join(melhor) + ": inventa menos sem perder leitura" if melhor else
          "⛔ nenhuma variante inventou menos sem perder leitura")
    return 0 if melhor else 1


if __name__ == "__main__":
    raise SystemExit(main())
