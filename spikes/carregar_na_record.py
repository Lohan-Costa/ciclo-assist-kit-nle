"""A sequência carrega SOZINHA na Record? E em que monitor cai cada coisa?

    python spikes/carregar_na_record.py        (exige MC aberto)

A missão do editor (2026-09-13): editar uma timeline já montada, entregar a cópia
modificada, a original intacta, e **carregar a cópia sozinha**. A escrita da bin está
medida e conferida na tela; o que nunca foi chamado é o `LoadMobsIntoViewer` com
`view_type`. O banco diz "carregar clipe no viewer: confirmado" — sem dizer em qual.

⭐ Não precisa de olho: o `GetViewerMobs` responde o que está em cada monitor, com o
`view_type`. O spike carrega e pergunta.

O que se quer saber, uma coisa por medição:
1. A forma do MobID que a API aceita — a mesma do `GetListOfBinItems`, ou a do pyavb?
2. Sequência com `Record` cai na Record?
3. Master com `Source` cai na Source?
4. Com a bin FECHADA, o carregar acha o mob?
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402

from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer  # noqa: E402

PROJETO = Path(r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR")
#: ⛔ SOMENTE LEITURA — fixture do editor.
BIN = PROJETO / "BIN COM SEQUENCIA AMA LINK.avb"
BIN_DE_MIDIA = PROJETO / "BIN COM MIDIA AMA LINK.avb"
SEQUENCIA = "TL com AMA"


def nos_monitores(mc) -> list[tuple[str, str, int]]:
    r = mc._chamar("GetViewerMobs")
    tipo = r.body.DESCRIPTOR.fields_by_name["mobs"].message_type.fields_by_name["view_type"]
    nomes = {v.number: v.name for v in tipo.enum_type.values}
    return [(m.mob_id, nomes.get(m.view_type, str(m.view_type)), m.current_frame)
            for m in r.body.mobs]


def carregar(mc, mob_id: str, monitor: str) -> str:
    try:
        mc._chamar("LoadMobsIntoViewer", _timeout=60, mob_ids=[mob_id],
                   view_type=mc._enum("LoadMobsIntoViewer", "view_type", monitor))
        return "aceitou"
    except Exception as e:      # noqa: BLE001 — é o que se quer medir
        return f"recusou: {str(e)[:120]}"


def main() -> int:
    with avb.open(str(BIN)) as f:
        pelo_pyavb = {m.name: str(m.mob_id) for m in f.content.mobs
                      if m.mob_type in ("CompositionMob", "MasterMob")}

    with MediaComposer() as mc:
        if not mc.esta_vivo():
            sys.exit("o Media Composer não está aberto")
        rel = mc.caminho_relativo_da_bin(str(BIN))

        print("antes ........", nos_monitores(mc))

        mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        itens = {i.nome: i.mob_id for i in mc.itens_da_bin(rel, tipos=("AllTypes",))}
        seq_api = itens.get(SEQUENCIA)
        print("\n1. MobID da sequência")
        print(f"   pela API ... {seq_api}")
        print(f"   pelo pyavb . {pelo_pyavb.get(SEQUENCIA)}")

        # ⚠️ Ordem importa: "Some mobs was skipped" também sai quando o mob JÁ ESTÁ no
        #    monitor. Por isso a forma do pyavb é testada com a Record vazia, ANTES.
        em_record = [m for m in nos_monitores(mc) if m[1] == "Record"]
        print(f"\n2. forma do PYAVB → Record (Record vazia: {not em_record}) ... "
              f"{carregar(mc, pelo_pyavb[SEQUENCIA], 'Record')}")
        print(f"3. forma da API  → Record ... {carregar(mc, seq_api, 'Record')}")
        print("   monitores ..........", nos_monitores(mc))
        print(f"4. a MESMA de novo → Record ... {carregar(mc, seq_api, 'Record')}")

        # ⚠️ A bin da sequência só MOSTRA a timeline: os masters dela viajam ocultos, e o
        #    `GetListOfBinItems` lista só o que está à vista. O master vem da bin de mídia.
        rel_midia = mc.caminho_relativo_da_bin(str(BIN_DE_MIDIA))
        mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel_midia)
        masters = {i.nome: i.mob_id for i in mc.itens_da_bin(rel_midia)}
        na_source = {m[0] for m in nos_monitores(mc) if m[1] == "Source"}
        outro = next(n for n in sorted(masters) if masters[n] not in na_source)
        print(f"\n5. master {outro!r} (não está na Source) → Source ... "
              f"{carregar(mc, masters[outro], 'Source')}")
        print("   monitores ..........", nos_monitores(mc))
        print(f"6. o mesmo de novo → Source ... {carregar(mc, masters[outro], 'Source')}")

        try:
            mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        except Exception as e:      # noqa: BLE001
            print("CloseBin:", e)
        print("\n7. bin da sequência FECHADA; monitores:", nos_monitores(mc))
        print(f"8. sequência → Record com a bin fechada ... {carregar(mc, seq_api, 'Record')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
