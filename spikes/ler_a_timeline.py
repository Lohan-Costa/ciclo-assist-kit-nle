"""O que há DENTRO de uma timeline montada à mão, trilha por trilha, em timecode de record.

    python spikes/ler_a_timeline.py "<bin>.avb" [nome da sequência] [--trilha V3]

Só lê. É a base do caminho B (editar a timeline do editor preservando tudo que a edição
não toca): antes de mexer, saber o que existe, onde, e o que está pendurado em cada
segmento (efeito, transição, velocidade, group clip).

⚠️ A contabilidade de posição num `Sequence` do AVB: `Filler`, `SourceClip`,
`TrackEffect`, `Selector` etc. SOMAM o próprio `length`; a `TransitionEffect` NÃO soma —
ela se sobrepõe aos dois vizinhos, e a posição volta `length` frames. Quem somar a
transição como um clipe desloca todo o resto da trilha.
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
from cicloassist.avid.take import fracao_da_taxa  # noqa: E402


def tc(frames: int, fps: int) -> str:
    sinal = "-" if frames < 0 else ""
    frames = abs(frames)
    h, r = divmod(frames, fps * 3600)
    m, r = divmod(r, fps * 60)
    s, fr = divmod(r, fps)
    return f"{sinal}{h:02d}:{m:02d}:{s:02d}:{fr:02d}"


def nome_da_fonte(comp, por_id) -> str:
    mob = por_id.get(str(getattr(comp, "mob_id", "")))
    return (mob.name if mob is not None else "?") or "(sem nome)"


def descrever(comp, por_id) -> str:
    tipo = type(comp).__name__
    if tipo == "SourceClip":
        return f"{nome_da_fonte(comp, por_id)!r} src_in={comp.start_time}"
    if tipo == "Filler":
        return "(vazio)"
    if tipo == "TransitionEffect":
        return f"transição {getattr(comp, 'effect_id', '')} corte={getattr(comp, 'cutpoint', '?')}"
    if tipo in ("TrackEffect", "MotionEffect", "PanVolumeEffect"):
        dentro = []
        for t in getattr(comp, "tracks", []) or []:
            c = t.component
            inner = [c] if type(c).__name__ != "Sequence" else list(c.components)
            dentro += [descrever(x, por_id) for x in inner if type(x).__name__ != "Filler"]
        return f"{tipo} {getattr(comp, 'effect_id', '')} sobre [{'; '.join(dentro)}]"
    if tipo == "Selector":
        # ⚠️ No pyavb, `Selector.components` é MÉTODO, não lista.
        opcoes = getattr(comp, "components", None)
        opcoes = list(opcoes() if callable(opcoes) else (opcoes or []))
        sel = getattr(comp, "selected", None)
        esc = descrever(sel, por_id) if sel is not None and hasattr(sel, "length") else sel
        return f"Selector ({len(opcoes)} opções) escolhida: {esc}"
    return tipo


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    so = sys.argv[sys.argv.index("--trilha") + 1] if "--trilha" in sys.argv else None
    if so:
        args = [a for a in args if a != so]
    janela = None
    if "--entre" in sys.argv:
        k = sys.argv.index("--entre")
        janela = (sys.argv[k + 1], sys.argv[k + 2])
        args = [a for a in args if a not in janela]
    caminho = Path(args[0])
    with avb.open(str(caminho)) as f:
        por_id = {str(m.mob_id): m for m in f.content.mobs}
        seqs = [i.mob for i in f.content.items if i.user_placed
                and i.mob.mob_type == "CompositionMob" and i.mob.usage is None]
        seq = next((s for s in seqs if len(args) < 2 or s.name == args[1]), seqs[0])
        fps = int(round(float(fracao_da_taxa(seq.edit_rate))))
        # ⛔ MEDIDO na TL EDITADA (2026-09-13): a sequência tem TRÊS trilhas de timecode —
        #    duas com 86400 @ 24 fps e uma com 90000 @ 25 fps. Pegar a última punha o início
        #    em 01:02:30:00 e todo timecode saía 2 min 30 s adiantado. O início da sequência
        #    é a PRIMEIRA, e o `start` conta na taxa DELA (`fps`), não na do edit_rate.
        inicio = 0
        tcs = [t.component for t in seq.tracks if type(t.component).__name__ == "Timecode"]
        if tcs:
            inicio = round(tcs[0].start * fps / (tcs[0].fps or fps))
        print(f"{seq.name!r} · {fps} fps · início {tc(inicio, fps)} · {seq.length} frames")

        contagem = {"picture": 0, "sound": 0}
        for t in seq.tracks:
            kind = getattr(t.component, "media_kind", "")
            if kind not in contagem:
                continue
            contagem[kind] += 1
            rotulo = ("V" if kind == "picture" else "A") + str(t.index)
            if so and rotulo != so:
                continue
            comps = list(t.component.components) if type(t.component).__name__ == "Sequence" \
                else [t.component]
            print(f"\n── {rotulo} ({len(comps)} componentes)")
            pos = 0
            for k, c in enumerate(comps):
                tipo = type(c).__name__
                if tipo == "TransitionEffect":
                    pos -= c.length
                    if janela and not (janela[0] <= tc(inicio + pos, fps) <= janela[1]):
                        continue
                    print(f"   [{k:3d}] {tc(inicio + pos, fps)}  ~{c.length:>5}  {descrever(c, por_id)}")
                    continue
                if tipo == "Filler" and not c.length:
                    continue
                if janela and not (tc(inicio + pos, fps) < janela[1]
                                   and tc(inicio + pos + c.length, fps) > janela[0]):
                    pos += c.length
                    continue
                print(f"   [{k:3d}] {tc(inicio + pos, fps)}  {c.length:>6}  {descrever(c, por_id)}")
                pos += c.length
            print(f"   fim {tc(inicio + pos, fps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
