"""Fase 5c, spike 1 — o AAF abre no MC com os masters CERTOS?

    python spikes/fase5c_aaf.py            # só autora e inspeciona, NÃO importa
    python spikes/fase5c_aaf.py --importar # autora e importa numa bin de teste

⭐ **É o elo mais arriscado da fase inteira, e por isso vem antes de tudo.** Nada do
plano, do validador ou da interface vale se o import criar masterclipes OFFLINE em vez de
reusar os que já estão na bin.

O que este spike responde, e nenhum outro teste responde:

1. O `ImportFile` aceita um AAF que autoramos, sem diálogo modal?
2. Os masters são **reusados** ou o MC cria cópias offline?
3. O corte cai no frame certo?

⚠️ **Importa numa bin PRÓPRIA** (`_TESTE_CICLO.avb`). Nada toca nas bins do editor, e
apagar a bin desfaz o experimento inteiro.

⛔ **Aponta para MASTERS, nunca para subclipes.** Reimportar um AAF cujos subclipes já
existem no projeto abre o modal *"Sub clip conflict found"* — e **modal trava a API
inteira**. Como o `resolver_take` já resolve subclipe → master + offset, ficamos do lado
certo de graça. Ver `docs/spec/2026-09-10-corte-zero.md` §3.
"""

from __future__ import annotations

import sys
import tempfile
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import aaf2  # noqa: E402
from aaf2.mobid import MobID  # noqa: E402

from cicloassist.avid.mcapi import MediaComposer  # noqa: E402
from cicloassist.avid.take import resolver  # noqa: E402

BIN = r"%USERPROFILE%\Documents\Avid Projects\_Assist anterior\CENAS\C07.avb"
BIN_DE_TESTE = "_TESTE_CICLO.avb"

#: Dois trechos curtos, de takes DIFERENTES: é o que prova que a emenda cai no lugar e que
#: dois masters distintos são reusados. Um corte só não distinguiria "funcionou" de
#: "importou qualquer coisa".
CORTES = [
    ("C07_P02-T004", 240),   # 10 s
    ("C07_P03-T001", 240),
]


def autorar(caminho: Path, cortes: list[tuple[str, int, str, int]], taxa: Fraction) -> None:
    """Escreve o AAF: uma composição de topo com uma track de imagem em corte seco."""
    total = sum(c[1] for c in cortes)
    rate = f"{taxa.numerator}/{taxa.denominator}"

    with aaf2.open(str(caminho), "w") as f:
        # Um MasterMob por master referenciado, com o MobID que JÁ EXISTE no projeto.
        # ⭐ É por este MobID que o Media Composer casa com o master dele em vez de criar
        #    um offline (automatch confirmado no banco, 2026-08-10).
        masters: dict[str, object] = {}
        for _, dur, mob_urn, _inicio in cortes:
            if mob_urn in masters:
                continue
            m = f.create.MasterMob()
            m.name = f"ref {mob_urn[-8:]}"
            m.mob_id = MobID(mob_urn)
            f.content.mobs.append(m)
            masters[mob_urn] = m

        comp = f.create.CompositionMob()
        # ⚠️⚠️ O construtor IGNORA o nome; atribuir depois, sempre. Regra paga pelo
        #     `translate.py` em produção (via pyavb, conferida aqui para o pyaaf2).
        comp.name = "CORTE ZERO - teste"
        comp.usage = "Usage_TopLevel"
        f.content.mobs.append(comp)

        sequencia = f.create.Sequence(media_kind="picture")
        for _nome, dur, mob_urn, inicio in cortes:
            sc = f.create.SourceClip(media_kind="picture")
            sc.mob_id = MobID(mob_urn)
            sc.slot_id = 1          # a slot de imagem do master
            sc.start = inicio       # ⭐ o offset DO MASTER (o subclipe não entra aqui)
            sc.length = dur
            sequencia.components.append(sc)

        # ⚠️⚠️ **`Sequence.length` NÃO se calcula sozinho no pyaaf2** — medido em
        #     2026-09-10: com dois SourceClips de 240 frames dentro, `seq.length`
        #     continua **0**. Tem de ser atribuído.
        #
        #     E isto é exatamente a armadilha que a regra 1 do `translate.py` descreve:
        #     uma track cujo comprimento não cobre o comp faz o MC estourar ao navegar
        #     além do fim (`PMM_INSUFFICIENT_MEDIA` + assertion
        #     `GetVideoFrameOffset < GetGlobalDuration`). O defeito nasceria em silêncio,
        #     porque o arquivo é gravado sem reclamar.
        sequencia.length = total

        slot = f.create.TimelineMobSlot(slot_id=1, edit_rate=rate)
        slot.name = "V1"
        slot.segment = sequencia
        comp.slots.append(slot)

        # ⛔⛔ Regra 1: toda track abrange a duração INTEIRA do comp. Aqui a sequência de
        #     imagem é a única e cobre tudo; quando entrar som mais curto, ele precisa de
        #     `Filler` de rabo. A conferência fica para não voltar a confiar no implícito.
        soma = sum(c.length for c in sequencia.components)
        assert sequencia.length == total == soma, (
            f"track não cobre o comp: length={sequencia.length}, soma={soma}, total={total}"
        )


def inspecionar(caminho: Path) -> None:
    with aaf2.open(str(caminho), "r") as f:
        mobs = list(f.content.mobs)
        print(f"  mobs no arquivo .. {len(mobs)}")
        for m in mobs:
            tipo = type(m).__name__
            print(f"    {tipo:16} {str(m.name)[:34]:36} {m.mob_id}")
            for s in m.slots:
                seg = s.segment
                n = len(getattr(seg, "components", []) or [])
                print(f"       slot {s.slot_id} {getattr(seg,'media_kind','?'):8} "
                      f"len={seg.length} componentes={n}")


def main() -> int:
    with MediaComposer() as mc:
        if not mc.esta_vivo():
            sys.exit("o Media Composer precisa estar aberto.")
        projeto = mc.projeto()

    taxa = Fraction(projeto["fps"]["num"], projeto["fps"]["den"])
    print(f"projeto ..... {projeto['caminho']}")
    print(f"taxa ........ {taxa} ({projeto['fps_aprox']})\n")

    cortes = []
    for nome, dur in CORTES:
        tk = resolver(BIN, nome)
        img = tk.imagem
        cortes.append((nome, dur, img.mob_id, img.inicio_frames))
        print(f"corte ....... {nome}: master {img.master} "
              f"@ {img.inicio_frames}, {dur} frames")
    print()

    saida = Path(tempfile.gettempdir()) / "ciclo_corte_zero.aaf"
    autorar(saida, cortes, taxa)
    print(f"autorado .... {saida} ({saida.stat().st_size:,} bytes)\n")
    inspecionar(saida)

    if "--importar" not in sys.argv:
        print("\n(só autorou; rode com --importar para mandar ao Media Composer)")
        return 0

    print(f"\nimportando na bin {BIN_DE_TESTE}…")
    with MediaComposer() as mc:
        # ⚠️ **A bin de destino precisa EXISTIR.** Medido: `ImportFile` para uma bin
        #    inexistente devolve `{"ErrorMessage": "Bin not found. Bin: …"}` — e a
        #    mensagem é honesta, mas só depois de o arquivo já estar autorado.
        #
        # ⚠️ `folder_path` é RELATIVO à pasta do projeto; `''` e `'.'` são a raiz.
        #    Caminho ABSOLUTO é recusado com "Directory not found", que manda conferir
        #    se a pasta existe quando o problema é a FORMA do caminho (banco, 2026-08-10).
        try:
            mc._chamar("CreateBin", folder_path="", bin_name=BIN_DE_TESTE.removesuffix(".avb"))
            print(f"  bin {BIN_DE_TESTE} criada")
        except Exception as e:
            print(f"  (CreateBin: {e})  — talvez já exista, seguindo")

        # ⚠️ `ImportFile` é operação de ARQUIVO: teto de segundos a dezenas, nunca o de
        #    consulta. Um teto curto não devolve erro honesto, devolve decisão errada.
        from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S
        r = mc._chamar(
            "ImportFile",
            _timeout=TEMPO_DE_ARQUIVO_S,
            file_path=str(saida),
            destination_bin=BIN_DE_TESTE,
        )
        print("  resposta:", r.header.task_id if r.header.task_id else "(sem task_id)")
    print("\nConfira no Media Composer: a bin _TESTE_CICLO deve ter 1 sequência.")
    print("Apagar a bin desfaz o experimento inteiro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
