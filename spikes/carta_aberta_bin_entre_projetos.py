"""Spike — Carta Aberta C0(b): uma bin ESCRITA POR NÓS, com os masters de OUTRO projeto, entra online?

    python spikes/carta_aberta_bin_entre_projetos.py <bin de origem .avb> <bin nova .avb> [--tudo]

Copia os masters VISÍVEIS da bin de origem (de um projeto A) para uma bin NOVA (pyavb, UID novo), com o fecho deles
oculto (os mobs de arquivo), e grava onde se pedir — a pasta de um projeto B. Depois, no MC com o projeto B aberto:
abrir a bin e carregar um master no Source (offline = "Media Offline" em vermelho).

A regra que o banco prevê (`protocolos/avb/escrita.md`, "Regra de identidade do automatch"): mídia gerenciada casa pelo
mob_id do master contra o `msmMMOB.mdb` da pasta `Avid MediaFiles/MXF/<n>` — que é da PASTA, não do projeto.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import avb  # noqa: E402

import cicloassist.avid  # noqa: E402,F401  (o conserto da string nula do pyavb)
from cicloassist.avid.timeline import _levar_fecho  # noqa: E402


#: `--tudo`: todo item VISÍVEL (group clip, subclipe, sequência), não só masters — o fecho vem junto, oculto.
TUDO = "--tudo" in sys.argv


def copiar_masters(origem: Path, saida: Path) -> list[str]:
    if saida.exists():
        raise SystemExit(f"já existe: {saida} (nunca sobrescrever)")
    nomes = []
    with avb.open() as f, avb.open(str(origem)) as o:
        # ⚠️ o master que o MC cria tem `usage = mastermob`; o que o nosso `som_gerenciado` escreve, `usage = None` —
        #    os dois têm `mob_type = MasterMob`.
        visiveis = [i.mob for i in o.content.items
                    if i.user_placed and (TUDO or getattr(i.mob, "mob_type", None) == "MasterMob")]
        for m in visiveis:
            f.content.add_mob(m.copy(f))
            nomes.append(m.name)
        ocultos = _levar_fecho(f, o, {str(m.mob_id) for m in visiveis}, {str(m.mob_id) for m in visiveis})
        f.write(str(saida))
    print(f"{len(nomes)} master(s) visíveis + {ocultos} mob(s) de fecho → {saida}")
    return nomes


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if a != "--tudo"]
    for n in copiar_masters(Path(args[0]), Path(args[1])):
        print("  ", n)
