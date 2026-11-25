"""A conferência de `separar_falas` contra transcrições REAIS — o limiar aprova o honesto?

    python spikes/as_falas_conferidas.py ["<bin>.avb"]

Só lê: a bin (pyavb) e as transcrições do cache. Não chama o Media Composer nem o ASR —
take sem transcrição em cache fica de fora.

Quatro pedidos por take, cada um com o veredito que ele TEM de receber:

| pedido | como é montado | tem de |
|---|---|---|
| honesto | cada fala do ASR vira um momento, com o in/out que `transcrever` devolve | passar |
| juntado | duas falas seguidas num trecho só, texto das duas | passar |
| take inteiro | a primeira fala apontando o take do começo ao fim | reprovar |
| tempo trocado | a fala k de um take com o in/out da fala k de OUTRO take | reprovar, se o texto difere |

Sai 0 se todos os vereditos baterem.
"""

from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402

import cicloassist.avid  # noqa: E402,F401
from cicloassist.avid.take import TakeErro, especie, resolver  # noqa: E402
from cicloassist.mcp.ferramentas.fala import formatar_fala  # noqa: E402
from cicloassist.mcp.ferramentas.roteiro import segmentos_no_take  # noqa: E402
from cicloassist.midia import asr as _asr  # noqa: E402
from cicloassist.midia import cache as _cache  # noqa: E402
from cicloassist.plano import falas as PF  # noqa: E402

BIN = Path(r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR\CENAS\C07.avb")


def falas_do_take(bin_: Path, nome: str):
    take = resolver(str(bin_), nome)
    som = take.som
    if som is None or not som.arquivos:
        return take, None
    midia = _cache.Midia(som.mob_id)
    if not midia.tem_transcricao():
        return take, None
    taxa = Fraction(take.fps["num"], take.fps["den"])
    fim_s = float((som.inicio_frames + take.duracao_frames) / taxa)
    dentro = _asr.com_respiro(_asr.recortar(midia.ler_transcricao(), som.inicio_s, fim_s),
                              piso_s=som.inicio_s, teto_s=fim_s)
    return take, [formatar_fala(f, som.inicio_s, taxa) for f in dentro]


def pedido(itens):
    return [{"fala": n, "texto": texto, "confianca": "inferido", "fonte": "transcricao",
             "trechos": [{"take": take, "inicio_no_take_frames": a, "duracao_frames": d}]}
            for n, (take, a, d, texto) in enumerate(itens, 1)]


def main() -> int:
    bin_ = Path(sys.argv[1]) if len(sys.argv) > 1 else BIN
    with avb.open(str(bin_)) as f:
        nomes = [i.mob.name for i in f.content.items
                 if i.user_placed and especie(i.mob) in ("subclipe", "master")]
    segmentos = segmentos_no_take(str(bin_))
    takes = {}
    for nome in nomes:
        try:
            take, falas = falas_do_take(bin_, nome)
        except (TakeErro, _cache.ChaveInvalida) as e:
            print(f"   {nome}: {e}")
            continue
        if falas:
            takes[nome] = (take, falas)
        else:
            print(f"   {nome}: sem transcrição em cache")

    def conferir(itens, duracao):
        return PF.conferir(PF.validar(pedido(itens)), segmentos, lambda _t: duracao)

    erros = 0
    honestos_reprovados = []
    for nome, (take, falas) in takes.items():
        # A fala que atravessa o in-point (a claquete) volta negativa: fica de fora.
        falas = [x for x in falas if x["duracao_frames"] >= 2 and x["inicio_no_take_frames"] >= 0
                 and x["saida_no_take_frames"] <= take.duracao_frames]
        takes[nome] = (take, falas)
        dur = take.duracao_frames

        honesto = conferir([(nome, x["inicio_no_take_frames"], x["duracao_frames"],
                             x["texto"]) for x in falas], dur)
        honestos_reprovados += [f"{nome}: {p}" for p in honesto.problemas]

        juntados = [(nome, a["inicio_no_take_frames"],
                     b["saida_no_take_frames"] - a["inicio_no_take_frames"],
                     f"{a['texto']} {b['texto']}") for a, b in zip(falas[::2], falas[1::2])]
        juntado = conferir(juntados, dur) if juntados else None
        honestos_reprovados += [f"{nome} (juntado): {p}" for p in (juntado.problemas
                                                                   if juntado else [])]

        inteiro = conferir([(nome, 0, dur, falas[0]["texto"])], dur)
        pegou_inteiro = any("engole" in p for p in inteiro.problemas) or len(falas) < 2
        erros += not pegou_inteiro
        print(f"{nome}: {len(falas)} falas · honesto {len(honesto.problemas)} problema(s) · "
              f"juntado {len(juntado.problemas) if juntado else '-'} · "
              f"take inteiro {'REPROVOU' if pegou_inteiro else '⛔ PASSOU'}")

    # O tempo trocado: a fala k de A com o in/out da fala k de B.
    trocas = pegas = 0
    nomes_t = list(takes)
    for a, b in zip(nomes_t, nomes_t[1:]):
        fa, fb = takes[a][1], takes[b][1]
        for x, y in zip(fa, fb):
            if PF.parecenca(x["texto"], y["texto"]) >= PF.PARECENCA_MINIMA:
                continue          # mesmo texto nos dois: trocar não é detectável, nem errado
            trocas += 1
            conf = conferir([(b, y["inicio_no_take_frames"], y["duracao_frames"],
                              x["texto"])], takes[b][0].duracao_frames)
            pegas += bool(conf.problemas)
    print(f"\ntempo trocado entre takes: {pegas} de {trocas} pegos")
    print(f"honestos reprovados: {len(honestos_reprovados)}")
    for p in honestos_reprovados[:15]:
        print("   ⛔", p)
    erros += len(honestos_reprovados) + (trocas - pegas)
    return 0 if erros == 0 and takes else 1


if __name__ == "__main__":
    raise SystemExit(main())
