"""Spike — o corte em L e em J chega ao Media Composer de verdade.

    python spikes/corte_em_l_e_j.py           # autora e confere o arquivo
    python spikes/corte_em_l_e_j.py --abrir   # e manda o MC abrir a bin

Exige o **Media Composer aberto** com o projeto de teste: o critério é a sequência abrir
lá, com as trilhas desencontradas, e não "o pyavb aceitou escrever".

## O que forçou este spike

No primeiro teste de campo (2026-09-10) o editor pediu um corte "com alguns cortes em L e
em J, com reações dos atores". Voltaram catorze cortes secos — e, nas viradas, **a mesma
fala tocando duas vezes**, uma em cada take.

Não foi erro de julgamento do modelo: o plano não tinha onde dizer "o som corta antes da
imagem". `Corte` era um bloco único de imagem+som, e `Entrada` também. Tentando imitar um
J esticando o plano anterior, a fala-gancho sobrava nos dois lados do corte.

## O que este spike prova

1. a **imagem** corta exatamente onde o plano mandou;
2. o **som** corta alguns frames antes (J) ou depois (L), no mesmo lugar em todas as
   trilhas de áudio;
3. as duas somas fecham **o mesmo total** — nenhum silêncio tapando buraco no fim;
4. o Media Composer **abre** a bin resultante.

⚠️ O que ele NÃO prova é o resultado artístico: se o corte ficou bom, quem diz é o editor
assistindo. Aqui se prova que a timeline saiu como o plano descreveu.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402

from cicloassist.avid import timeline as T  # noqa: E402
from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer  # noqa: E402
from cicloassist.avid.take import resolver  # noqa: E402
from cicloassist.plano import esquema as _plano  # noqa: E402

BIN_ORIGEM = r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR\CENAS\C07.avb"
NOME_DA_BIN = "_CORTE_L_E_J"

#: O plano, no formato que o modelo escreve. Três cortes e duas transições: uma em J e
#: uma em L, com o mesmo material da cena 7.
#:
#: ⚠️ Os `inicio_no_take` são generosos de propósito: um corte em J recua o som dentro do
#: take, e recuar antes do frame 0 é pedir mídia que não existe.
PLANO = {
    "bin": BIN_ORIGEM,
    "nome": "C07 L E J",
    "cortes": [
        {"take": "C07_P02-T002", "inicio_no_take": 530, "duracao_frames": 240,
         "confianca": "inferido", "fonte": "transcricao",
         "porque": "abre nele, o pedido ganha peso"},
        {"take": "C07_P03-T001", "inicio_no_take": 1038, "duracao_frames": 240,
         "corte_de_som": "antes", "som_frames": 14,
         "confianca": "inferido", "fonte": "transcricao",
         "porque": "corte em J: a fala dele entra sob o rosto dela, antes da imagem"},
        {"take": "C07_P02-T002", "inicio_no_take": 1193, "duracao_frames": 240,
         "corte_de_som": "depois", "som_frames": 9,
         "confianca": "inferido", "fonte": "transcricao",
         "porque": "corte em L: a fala dela segura mais nove frames sob a imagem dele"},
    ],
}


def main() -> int:
    with MediaComposer() as mc:
        if not mc.esta_vivo():
            sys.exit("o Media Composer precisa estar aberto.")
        projeto = mc.projeto()
    taxa = projeto["fps_aprox"]
    raiz = Path(projeto["caminho"])

    plano = _plano.validar(PLANO)
    print(f"projeto ..... {raiz}")
    print(f"taxa ........ {taxa}\n")
    print(_plano.resumir(plano, taxa))
    print()

    entradas = []
    for i, c in enumerate(plano.cortes):
        tk = resolver(BIN_ORIGEM, c.take)
        desloca = c.desloca
        proximo = plano.cortes[i + 1].desloca if i + 1 < len(plano.cortes) else 0
        entradas.append(T.Entrada(
            mob_id=tk.mob_id,
            duracao=c.duracao_frames,
            trilhas=T.trilhas_do_take(tk),
            start_time=c.inicio_no_take,
            duracao_som=c.duracao_frames - desloca + proximo,
            start_som=c.inicio_no_take + desloca,
        ))
        e = entradas[-1]
        print(f"corte ....... {c.take:16} imagem in={e.start_time:<5} dur={e.duracao:<5} "
              f"| som in={e.start_som:<5} dur={e.duracao_som}")

    saida = Path(tempfile.gettempdir()) / f"{NOME_DA_BIN}.avb"
    T.escrever_bin(saida, [(plano.nome, entradas)], taxa, base=BIN_ORIGEM)
    print(f"\nautorado .... {saida} ({saida.stat().st_size:,} bytes)")

    # ── a conferência que importa: as trilhas saíram desencontradas? ─────────
    print("\n  trilha            cortes (duração de cada clipe)          soma")
    somas = {}
    with avb.open(str(saida)) as f:
        for m in f.content.mobs:
            if getattr(m, "name", None) != plano.nome:
                continue
            for tr in m.tracks:
                comp = tr.component
                comps = getattr(comp, "components", None)
                if comps is None or comp.media_kind not in ("picture", "sound"):
                    continue
                fontes = [c.length for c in comps
                          if type(c).__name__ == "SourceClip"]
                soma = sum(getattr(c, "length", 0) or 0 for c in comps)
                somas.setdefault(comp.media_kind, []).append(soma)
                print(f"  {comp.media_kind}{tr.index:<3}          {str(fontes):38} {soma}")

    imagem = somas.get("picture", [0])[0]
    sons = somas.get("sound", [])
    esperado_img = [c.duracao_frames for c in plano.cortes]
    esperado_som = [e.duracao_som for e in entradas]

    with avb.open(str(saida)) as f:
        mob = next(m for m in f.content.mobs if getattr(m, "name", None) == plano.nome)
        por_trilha = {}
        for tr in mob.tracks:
            comps = getattr(tr.component, "components", None)
            if comps is None or tr.component.media_kind not in ("picture", "sound"):
                continue
            por_trilha[(tr.component.media_kind, tr.index)] = [
                c.length for c in comps if type(c).__name__ == "SourceClip"]

    v1 = por_trilha.get(("picture", 1), [])
    trilhas_de_som = [v for (k, _), v in por_trilha.items() if k == "sound"]

    print()
    checagens = [
        ("a imagem corta onde o plano mandou", v1 == esperado_img),
        ("o som corta desencontrado da imagem", all(v == esperado_som
                                                    for v in trilhas_de_som)),
        ("todas as trilhas de som iguais entre si", len({tuple(v) for v in
                                                         trilhas_de_som}) == 1),
        ("imagem e som fecham o mesmo total", all(s == imagem for s in sons)),
        ("nenhuma fala repetida na virada", esperado_som != esperado_img),
    ]
    for rotulo, passou in checagens:
        print(f"  {'✓' if passou else '✗'} {rotulo}")
    tudo = all(p for _, p in checagens)

    if "--abrir" not in sys.argv:
        print("\n(só autorou; rode com --abrir para mandar ao Media Composer)")
        return 0 if tudo else 1

    # ⛔⛔ NUNCA gravar por cima de uma bin que já existe: se o Media Composer a tiver
    #    aberta, ele reescreve do que tem em memória e a bin sai plausível e CORROMPIDA,
    #    sem erro nenhum. Rodar este spike duas vezes é rotina — então ele procura um nome
    #    livre, em vez de mandar quem roda ir apagar bin à mão no meio do diagnóstico.
    nome_da_bin = NOME_DA_BIN
    n = 2
    while (raiz / f"{nome_da_bin}.avb").exists():
        nome_da_bin = f"{NOME_DA_BIN} {n}"
        n += 1
    destino = raiz / f"{nome_da_bin}.avb"
    destino.write_bytes(saida.read_bytes())

    with MediaComposer() as mc:
        # ⚠️ `OpenBin` é operação de ARQUIVO, não consulta: teto de dezenas de segundos.
        mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=f"{nome_da_bin}.avb")
        itens = mc.itens_da_bin(f"{nome_da_bin}.avb", tipos=("AllTypes",))
    print(f"\nOpenBin ..... {nome_da_bin}.avb → {len(itens)} item(ns)")
    # ⚠️ `itens_da_bin` devolve `ItemDeBin`, e o campo é `nome` — em português, como todo
    #    o resto da camada de tradução.
    abriu = any(getattr(i, "nome", None) == plano.nome for i in itens)
    print(f"  {'✓' if abriu else '✗'} a sequência está na bin do editor")
    print(f"\nNo Media Composer: abra '{plano.nome}' e olhe as trilhas nas duas viradas —")
    print("o corte de A1/A2 não coincide com o de V1. É isso que se está provando.")
    return 0 if (tudo and abriu) else 1


if __name__ == "__main__":
    raise SystemExit(main())
