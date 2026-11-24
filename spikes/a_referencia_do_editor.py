"""Ler a sequência de REFERÊNCIA que o editor montou à mão: drop-frame e matte key na timeline.

    python spikes/a_referencia_do_editor.py "<bin>.avb"

Só lê, numa cópia. Responde as duas perguntas que o banco marca como NÃO medidas
(`protocolos/avb/fontes.md`, 2026-09-13 noite):

1. **Drop-frame:** que `flags` o `Timecode` de uma sequência DF criada pelo Media Composer
   tem, e se o `start` é contagem DF (`01;00;00;00` = 107892) ou non-drop (108000).
2. **Matte key na timeline:** como o MC grava o clipe de matte key editado numa trilha —
   o `TrackEffect` inteiro, as trilhas dele, para que mob cada `SourceClip` aponta, os
   `start_time`/`length` e os `keyframes`. É a estrutura que o produto vai COPIAR para
   montar cobertura na V2, em vez de inventar.

Método da casa (banco, `escrita.md`): gerar a peça no MC, salvar, e ler o que ele gravou.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402

import cicloassist.avid  # noqa: E402,F401
from cicloassist.avid.take import especie, fracao_da_taxa  # noqa: E402


def campos(o) -> dict:
    return {k: (repr(v)[:70]) for k, v in o.property_data.items()
            if not hasattr(v, "property_data") and not isinstance(v, list)
            and k not in ("left_bob", "right_bob")}


def mostrar(o, por_id, prof=0, limite=6) -> None:
    if prof > limite or not hasattr(o, "property_data"):
        return
    tipo = type(o).__name__
    extra = ""
    if tipo == "SourceClip":
        alvo = por_id.get(str(o.mob_id))
        extra = (f"  → {getattr(alvo, 'name', None)!r} ({getattr(alvo, 'mob_type', '?')} "
                 f"usage={getattr(alvo, 'usage', None)})")
    print("  " * prof + f"{tipo} {campos(o)}{extra}")
    for k, v in o.property_data.items():
        if hasattr(v, "property_data"):
            print("  " * prof + f"  .{k}:")
            mostrar(v, por_id, prof + 2, limite)
        elif isinstance(v, list):
            for x in v:
                if hasattr(x, "property_data"):
                    print("  " * prof + f"  .{k}[]:")
                    mostrar(x, por_id, prof + 2, limite)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    copia = Path(tempfile.mkdtemp(prefix="referencia-")) / Path(sys.argv[1]).name
    shutil.copy2(sys.argv[1], copia)
    with avb.open(str(copia)) as f:
        por_id = {str(m.mob_id): m for m in f.content.mobs}
        seqs = [i.mob for i in f.content.items
                if i.user_placed and especie(i.mob) == "sequencia"]
        print(f"{len(seqs)} sequência(s) em {Path(sys.argv[1]).name}\n")
        for seq in seqs:
            taxa = float(fracao_da_taxa(seq.edit_rate))
            print(f"══ {seq.name!r} · edit_rate {taxa:.3f} · {seq.length} frames")
            for t in seq.tracks:
                c = t.component
                if type(c).__name__ == "Timecode":
                    print(f"   Timecode: fps={c.fps} flags={c.flags} start={c.start} "
                          f"(start/fps = {c.start / (c.fps or 1) / 3600:.4f} h)")
            for t in seq.tracks:
                c = t.component
                if type(c).__name__ != "Sequence":
                    continue
                for comp in c.components:
                    if type(comp).__name__ in ("TrackEffect",) and "MATTE" in str(
                            getattr(comp, "effect_id", "")):
                        print(f"\n   ▶ matte key na trilha {c.media_kind} {t.index}:")
                        mostrar(comp, por_id, 2)
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
