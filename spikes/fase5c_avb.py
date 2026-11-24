"""Fase 5c, spike 2 — a `.avb` autorada abre no Media Composer?

    python spikes/fase5c_avb.py           # autora e inspeciona, NÃO toca no MC
    python spikes/fase5c_avb.py --abrir   # autora e manda o MC abrir a bin

Substitui o `fase5c_aaf.py`, que provou que a rota de import não serve (masters de
esboço são descartados em silêncio) — e que foi descartada de vez por depender de
**preset**, que é configuração do usuário.

⭐ O risco mudou de natureza: já não é *"o MC aceita o que autoramos?"* — o idioma tem
round-trip em produção. É *"portamos sem reintroduzir defeito já pago?"*.

Três coisas que este spike prova, e que só um MC de verdade responde:

1. a bin abre, e a timeline aparece nela (`user_placed`);
2. a timeline TOCA — se o trail `Filler` faltar, o MC recusa com
   `Assertion failed: CompIsFiller(last)`;
3. o corte parcial cai no frame certo (a terceira entrada é um recorte, não o take
   inteiro).
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

BIN_ORIGEM = r"%USERPROFILE%\Documents\Avid Projects\_Assist anterior\CENAS\C07.avb"
#: ⚠️ Bin NOVA, e não a `_TESTE_CICLO` do spike 1. Aquela está ABERTA no Media
#: Composer, e gravar por baixo de uma bin aberta é o caminho para uma bin plausível
#: e corrompida — o banco registra que o MC reescreve do que tem em memória, sem
#: levantar erro nenhum.
NOME_DA_BIN = "_CORTE_ZERO"

#: `(take, start_time DENTRO do take, duração)`. O terceiro é recorte parcial de
#: propósito: é o que distingue "enfileirou clipes" de "cortou onde mandei".
CORTES = [
    ("C07_P02-T004", 0, 240),
    ("C07_P03-T001", 0, 240),
    ("C07_P02-T002", 480, 120),   # começa 20 s dentro do take
]


def main() -> int:
    with MediaComposer() as mc:
        if not mc.esta_vivo():
            sys.exit("o Media Composer precisa estar aberto.")
        projeto = mc.projeto()
    taxa = projeto["fps_aprox"]
    raiz = Path(projeto["caminho"])

    print(f"projeto ..... {raiz}")
    print(f"taxa ........ {taxa}\n")

    entradas = []
    for nome, inicio, dur in CORTES:
        tk = resolver(BIN_ORIGEM, nome)
        trilhas = T.trilhas_do_take(tk)
        entradas.append(T.Entrada(
            # ⭐ O MobID do SUBCLIPE, não o do master: é o que o editor vê na bin, e é
            #    o que faz o matchframe cair no take.
            mob_id=tk.mob_id,
            duracao=dur,
            trilhas=trilhas,
            start_time=inicio,
        ))
        img = sum(1 for k, _ in trilhas if k == "picture")
        som = sum(1 for k, _ in trilhas if k == "sound")
        print(f"corte ....... {nome:16} in={inicio:<5} dur={dur:<5} "
              f"trilhas: {img}V {som}A")

    saida = Path(tempfile.gettempdir()) / f"{NOME_DA_BIN}.avb"
    T.escrever_bin(saida, [("C07 CORTE ZERO", entradas)], taxa, base=BIN_ORIGEM)
    print(f"\nautorado .... {saida} ({saida.stat().st_size:,} bytes)")

    # ── conferir a estrutura antes de mostrar ao MC ──────────────────────────
    with avb.open(str(saida)) as f:
        for m in f.content.mobs:
            print(f"\n  {getattr(m,'usage',None) or type(m).__name__}: {m.name!r}")
            print(f"     length={m.length}  edit_rate={m.edit_rate}  tracks={len(m.tracks)}")
            for tr in m.tracks:
                comp = tr.component
                comps = getattr(comp, "components", None)
                if comps is None:
                    print(f"     track {tr.index} {comp.media_kind:20} {type(comp).__name__}")
                    continue
                ultimo = type(comps[-1]).__name__
                soma = sum(getattr(c, "length", 0) or 0 for c in comps)
                marca = "✓" if ultimo == "Filler" else "✗ SEM TRAIL FILLER"
                print(f"     track {tr.index} {comp.media_kind:20} "
                      f"{len(comps)} comp, soma={soma}, último={ultimo} {marca}")

    if "--abrir" not in sys.argv:
        print("\n(só autorou; rode com --abrir para mandar ao Media Composer)")
        return 0

    # ⚠️ A bin vai para a PASTA DO PROJETO — é lá que o MC procura.
    destino = raiz / f"{NOME_DA_BIN}.avb"
    if destino.exists():
        # ⛔⛔ Se o Media Composer tiver esta bin ABERTA, gravar por baixo produz uma bin
        #    plausível e CORROMPIDA — ele reescreve do que tem em memória, sem levantar
        #    erro nenhum. Recusar é a única resposta segura; quem quiser repetir fecha a
        #    bin no MC e apaga o arquivo.
        sys.exit(
            f"{destino.name} já existe. Se o Media Composer a tiver aberta, gravar por "
            f"baixo corrompe.\nFeche-a no MC e apague o arquivo antes de repetir."
        )
    destino.write_bytes(saida.read_bytes())
    print(f"\ncopiada ..... {destino}")

    with MediaComposer() as mc:
        # ⚠️ `OpenBin` é operação de ARQUIVO, não consulta: teto de dezenas de segundos.
        #    E o caminho é RELATIVO à pasta do projeto — absoluto é recusado com
        #    "Bin is not open"/"Directory not found", que apontam o lugar errado.
        mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=f"{NOME_DA_BIN}.avb")
        print(f"OpenBin ..... pedido para {NOME_DA_BIN}.avb")
        itens = mc.itens_da_bin(f"{NOME_DA_BIN}.avb", tipos=("AllTypes",))
        print(f"itens na bin: {len(itens)}")
        for i in itens:
            print(f"   {i.nome}")

    print(f"\nNo Media Composer: a bin {NOME_DA_BIN} tem a timeline 'C07 CORTE ZERO'.")
    print("Abra e toque — se o trail Filler faltasse, ela nem abriria.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
