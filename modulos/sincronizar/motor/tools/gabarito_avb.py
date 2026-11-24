#!/usr/bin/env python3
"""
gabarito_avb.py — mede o PAREAMENTO do sync contra uma bin sincronizada à mão.

## Por que existe, e por que é irmão do `gabarito.py` e não substituto

O `gabarito.py` lê um XML do Premiere e mede **posição**: onde o editor pôs cada
clipe contra onde o motor põe. É a pergunta certa para o Premiere.

⚠️ **O Media Composer não exporta XML.** Mas exporta a si mesmo: a bin carrega a
sequência inteira, com as tracks e os MobIDs. E o autor (editor) apontou qual é a
pergunta que importa nesse fluxo:

> *"Não se prenda muito à relação do TC entre os arquivos, pois vários eu desloquei
> pra frente ou pra trás para casar com o sync. Observe mais a ORDEM dos arquivos e
> qual vídeo casa com qual áudio."*

Daí a divisão: aquele mede POSIÇÃO a partir de XML; este mede **QUEM CASA COM
QUEM** a partir de uma `.avb`. A posição absoluta numa timeline montada à mão é
arrumação; o pareamento é julgamento.

## ⭐⭐ Por que isto foi escrito (2026-08-22) — a lição que ele institucionaliza

Numa única noite, sem esta régua:

1. propus alargar o `ANCHOR_REACH_S` — **piorou** (erro marcado virou erro
   confiante, com clipes a 5h57 do lugar);
2. propus desfazer o par sem âncora — **piorou muito**: a diária caiu de **34
   tomadas para 23**, e só se descobriu porque o autor abriu o alpha 0.1.20
   instalado e comparou a olho;
3. e depois persegui por duas horas um "defeito" no `C014`/`C016` que **não
   existia** — o gabarito é que estava errado.

Os três eram raciocínios plausíveis. Nenhum sobreviveu a uma medição.

⭐ E a régua provou o que uma boa régua tem de provar: ela **discordou do motor**
(pegando o conserto ruim) **e discordou do gabarito** (quando o gabarito errou).
Um instrumento que só confirma o que se espera não é instrumento.

## O número que mais importa

O mesmo do `gabarito.py`, e vale repetir: **não é o acerto, é a honestidade do
aviso.** Um motor que erra 3 clipes e sinaliza os 3 é utilizável — o editor sabe
onde olhar. Um que erra 1 em silêncio é pior, porque ensina a confiar no que não
dá. Daí a matriz `acertou/errou × sinalizou/calado`, e o destaque no erro CALADO.

⚠️ Um segundo número, fácil de esquecer: **quantos avisos caem em clipe CERTO.**
Aviso demais dilui o aviso — o editor que confere 13 para achar 1 aprende a não
conferir nenhum.

## Uso

    # extrair o gabarito de uma bin sincronizada à mão
    python tools/gabarito_avb.py extrair <bin.avb> <gabarito.json> [nome-da-sequência]

Uma bin pode guardar VÁRIAS diárias sincronizadas à mão (é o formato do
`SYNC MANUAL - GABARITO.avb`); sem o terceiro argumento a ferramenta lista as
que encontrou e para, em vez de escolher por você.

    # medir um resultado de sync contra ele
    python tools/gabarito_avb.py medir <gabarito.json> <resultado.json> [selecao.json]

A `selecao.json` (o payload do `avid_selection`) só é necessária quando a mídia
gerenciada tem nome de HASH: ela traz o `mob_ids` que liga arquivo a masterclipe.

O `<resultado-do-sync.json>` é o payload que o comando `sync` do sidecar devolve.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _limpar(nome: str) -> str:
    """Nome comparável: sem pasta, sem extensão, sem sufixo de canal, em minúsculas.

    ⚠️ **`casefold` não é preciosismo.** O mesmo material aparece como
    `A005_03180050_C001.mp4` no disco e `a005_03180050_C001` como masterclipe do
    Avid. Comparar cru fez **35 de 37 clipes** parecerem erro numa medição desta
    mesma noite — o instrumento acusando o motor de um defeito que era dele. O
    a base de conhecimento interna já avisava (`caminhos-e-storage-producao.md` §1): comparação de
    nome é case-insensitive, sempre.

    O `_A01`/`_A02` do fim é sufixo de CANAL do OP-Atom, não parte do nome.
    """
    return re.sub(r"_A\d+$", "", Path(nome).stem).strip().casefold()


# ── Extração: a bin sincronizada à mão vira gabarito ─────────────────────────

def extrair(bin_path: Path, seq_nome: str | None = None) -> dict:
    """`{nome_do_video: nome_do_som_direto | None}` lido da sequência da bin.

    O empilhamento é a resposta: o som direto de um clipe é o que ocupa o mesmo
    trecho da timeline que ele.

    ⚠️ **O áudio da PRÓPRIA CÂMERA não conta.** Ele aparece nas tracks de som com o
    mesmo nome do vídeo, e contá-lo faria todo clipe parecer sincronizado.
    """
    import avb

    with avb.open(str(bin_path)) as f:
        nomes, mob_de_nome = {}, {}
        for m in f.content.mobs:
            try:
                if getattr(m, "mob_type", "") == "MasterMob":
                    nomes[str(m.mob_id)] = m.name or "(sem nome)"
                    mob_de_nome[_limpar(m.name or "")] = str(m.mob_id)
            except Exception:
                continue

        seqs = [m for m in f.content.mobs if getattr(m, "mob_type", "") == "CompositionMob"]
        if not seqs:
            raise SystemExit(f"{bin_path.name}: nenhuma sequência na bin")

        # ⭐ UMA BIN, VÁRIOS GABARITOS. O autor reuniu as diárias sincronizadas à
        # mão numa bin só (`SYNC MANUAL - GABARITO.avb`), uma sequência por diária.
        # É melhor assim: o conjunto de referência anda junto, e medir contra UMA
        # diária só é o que faz ajustar limiar até ela passar parecer conserto.
        if seq_nome:
            achadas = [m for m in seqs if seq_nome.casefold() in (m.name or "").casefold()]
            if not achadas:
                raise SystemExit(
                    f"{bin_path.name}: nenhuma sequência casa com {seq_nome!r}. "
                    f"Há: {[m.name for m in seqs]}")
            seq = achadas[0]
        elif len(seqs) > 1:
            raise SystemExit(
                f"{bin_path.name} tem {len(seqs)} sequências — diga qual:\n  "
                + "\n  ".join(repr(m.name) for m in seqs))
        else:
            seq = seqs[0]

        def segmentos(track):
            comp = track.component
            fora, pos = [], 0
            for c in getattr(comp, "components", []) or []:
                dur = getattr(c, "length", 0) or 0
                mob = getattr(c, "mob_id", None)
                if mob is not None and type(c).__name__ != "Filler":
                    fora.append((pos, pos + dur, nomes.get(str(mob), str(mob))))
                pos += dur
            return fora

        video, audio = [], []
        for t in seq.tracks:
            mk = getattr(t.component, "media_kind", "?")
            if mk == "picture":
                video += segmentos(t)
            elif mk == "sound":
                audio += segmentos(t)

    # O mesmo som aparece em várias tracks (um canal cada): junta por (nome, início).
    blocos = sorted({(a, b, n) for a, b, n in audio})

    pares: dict[str, str | None] = {}
    for a, b, nv in sorted(video):
        diretos = [n for (x, y, n) in blocos
                   if x < b and y > a and _limpar(n) != _limpar(nv)]
        # Sobrando mais de um, fica o de MAIOR sobreposição — e não o primeiro.
        if len(set(map(_limpar, diretos))) > 1:
            melhor = max(
                ((n, min(b, y) - max(a, x)) for (x, y, n) in blocos
                 if x < b and y > a and _limpar(n) != _limpar(nv)),
                key=lambda kv: kv[1],
            )
            diretos = [melhor[0]]
        pares[_limpar(nv)] = _limpar(diretos[0]) if diretos else None

    # ⭐ O MobID junto do nome. Em mídia gerenciada o ARQUIVO costuma ter nome de
    # hash (`V01.E69CCF0F….mxf`), sem relação com o clipe — e aí casar por nome
    # devolve 0% com cara de motor quebrado (aconteceu no `PRJ/D01`). O MobID é a
    # identidade que atravessa as duas pontas.
    return {"bin": bin_path.name, "sequencia": seq.name, "pares": pares,
            "mob_de_nome": {k: v for k, v in mob_de_nome.items() if k in pares
                            or k in set(filter(None, pares.values()))}}


# ── Medição: o motor contra o gabarito ───────────────────────────────────────

def medir(gabarito: dict, resultado: dict, selecao: dict | None = None) -> int:
    """Imprime a matriz. Devolve o nº de erros CALADOS (o código de saída)."""
    verdade = gabarito["pares"]
    g = resultado["groups"][0]

    # ── Ponte por MobID, para mídia gerenciada com nome de hash ──────────────
    #
    # `selecao` é o payload do `avid_selection`, que traz `mob_ids` = {arquivo:
    # mob_id}. Com ele, o caminho de um `.mxf` chamado `V01.E69CCF0F…` volta a ser
    # o nome do masterclipe, e a comparação funciona. Sem ele, cai no nome do
    # arquivo — que serve quando o Avid nomeia a mídia como o clipe.
    nome_do_arquivo: dict[str, str] = {}
    if selecao and gabarito.get("mob_de_nome"):
        from avid.mcapi import mob_id_para_pyavb
        por_mob = {}
        for nome, mob in gabarito["mob_de_nome"].items():
            # ⚠ Tirar o `urn:smpte:umid:` ANTES: o `mob_id_para_pyavb` filtra
            # dígitos hexadecimais da string inteira, e `smpte`/`umid` contribuem
            # com um `e` e um `d` — 64 dígitos viram 66 e a conversão recusa.
            try:
                por_mob[mob_id_para_pyavb(mob.rsplit(":", 1)[-1])] = nome
            except Exception:
                continue
        for arq, mob in (selecao.get("mob_ids") or {}).items():
            try:
                alvo = por_mob.get(mob_id_para_pyavb(mob))
            except Exception:
                continue
            if alvo:
                nome_do_arquivo[_limpar(arq)] = alvo

    def chave(caminho: str) -> str:
        k = _limpar(caminho)
        return nome_do_arquivo.get(k, k)

    nosso: dict[str, str | None] = {}
    marcado: dict[str, bool] = {}
    for tk in g["takes"]:
        som = chave(tk["sound"]["path"])
        for p in tk["camera_paths"]:
            nosso[chave(p)] = som
    for cg in g["camera_groups"]:
        for c in cg["cameras"]:
            k = chave(c["path"])
            marcado[k] = bool(c.get("flagged"))
            nosso.setdefault(k, None)

    faltando = [v for v in verdade if v not in marcado]
    if faltando:
        print(f"⚠️  {len(faltando)} clipe(s) do gabarito não estão no resultado: "
              f"{faltando[:4]}", file=sys.stderr)

    ok_av = ok_cal = err_av = err_cal = 0
    erros = []
    for v in sorted(verdade):
        esperado, obtido = verdade[v], nosso.get(v)
        avisou = marcado.get(v, False)
        certo = esperado == obtido
        if certo and avisou:
            ok_av += 1
        elif certo:
            ok_cal += 1
        elif avisou:
            err_av += 1
        else:
            err_cal += 1
        if not certo:
            erros.append((v, esperado, obtido, avisou))

    tot = len(verdade)
    acertos = ok_av + ok_cal
    print(f"gabarito: {gabarito.get('sequencia') or gabarito.get('bin', '?')}"
          f"   clipes: {tot}")
    print(f"ACERTOS: {acertos}/{tot}  ({acertos / tot * 100:.0f}%)")
    print()
    print("                    sinalizado    calado")
    print(f"  acertou              {ok_av:5d}     {ok_cal:6d}   <- aviso em clipe certo dilui o aviso")
    print(f"  ERROU                {err_av:5d}     {err_cal:6d}   <- o calado é o veneno")
    if erros:
        print("\nERROS:")
        for v, esp, obt, avisou in erros:
            print(f"  [{'avisado' if avisou else 'CALADO '}] {v[:28]:28s} "
                  f"esperado={str(esp)[:32]:32s} deu={str(obt)[:32]}")
    return err_cal


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("extrair", "medir"):
        print(__doc__)
        return 2
    if sys.argv[1] == "extrair":
        _, _, entrada, saida = sys.argv[:4]
        seq = sys.argv[4] if len(sys.argv) > 4 else None
        gab = extrair(Path(entrada), seq)
        Path(saida).write_text(json.dumps(gab, indent=2, ensure_ascii=False),
                               encoding="utf-8")
        n = sum(1 for v in gab["pares"].values() if v)
        print(f"{len(gab['pares'])} clipes ({n} com som direto) → {saida}")
        return 0
    _, _, gab_path, res_path = sys.argv[:4]
    sel = (json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
           if len(sys.argv) > 4 else None)
    return 1 if medir(json.loads(Path(gab_path).read_text(encoding="utf-8")),
                      json.loads(Path(res_path).read_text(encoding="utf-8")),
                      sel) else 0


if __name__ == "__main__":
    raise SystemExit(main())
