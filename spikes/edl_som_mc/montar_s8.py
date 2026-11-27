"""Spike — S8 da EDL para o som: o group na sequência em TRÊS eventos seguidos (ângulo CAM B), para trocar o do MEIO
para a CAM A pelo gesto do editor (botão direito no segmento da V1 › o ângulo — autor, 2026-11-25). Bin NOVA (grupo com
MobID novo) + `plano_s8.json` com a verdade DEPOIS da troca.

    python spikes/edl_som_mc/montar_s8.py <bin dos masters B31> <bin NOVA de saída> <plano_s8.json>

No grupo (sync no instante 14:00:02:00) o quadro g é CAM A g−48, CAM B g−96, som 1 g.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import avb  # noqa: E402

from cicloassist.avid import timeline as T  # noqa: E402
from montar_casos import (CAMA, CAMB, CANAIS, FONTES, SOM1, _SoAlgumas, _verdade,  # noqa: E402
                          montar_grupo, montar_sequencia)

NOME = "B31 S8 TROCA DE ANGULO"


def main(origem: str, saida: str, plano: str) -> None:
    for p in (saida, plano):
        if Path(p).exists():
            raise SystemExit(f"⛔ {p} já existe: nunca por cima")
    with contextlib.ExitStack() as pilha:
        f = pilha.enter_context(avb.open())
        o = pilha.enter_context(avb.open(origem))
        M = {m.name: m for m in o.content.mobs if getattr(m, "mob_type", "") == "MasterMob"}
        rate = M[CAMA].tracks[0].component.edit_rate
        grupo, _ = montar_grupo(f, "12-1 GRUPO S8 v02", [(_SoAlgumas(M[CAMA], ("picture",)), 48),
                                                     (_SoAlgumas(M[CAMB], ("picture",)), 0),
                                                     (_SoAlgumas(M[SOM1], ("sound",)), 96)], rate, angulo=1)
        ev = [{"dur": 72, "trilhas": {("picture", 1): (grupo, 1, g),
                                      **{("sound", c): (grupo, c, g) for c in range(1, 7)}}} for g in (200, 272, 344)]
        montar_sequencia(f, NOME, ev, rate)
        # a verdade DEPOIS da troca: o do meio na CAM A (g − 48); o som segue o som direto
        verdade = [{"V1": (cam, g - d, None), **{f"A{c}": (SOM1, g, c) for c in range(1, 7)}}
                   for (cam, d), g in zip([(CAMB, 96), (CAMA, 48), (CAMB, 96)], (200, 272, 344))]
        levados = T._levar_fecho(f, o, {m.mob_id for m in M.values()}, set())
        f.write(saida)
    with open(plano, "w", encoding="utf-8") as fh:
        json.dump({"receita": "B31_EDL_SOM", "fps": "23.976", "fontes": FONTES, "canais": CANAIS,
                   "casos": [_verdade(NOME, ev, verdade)]}, fh, ensure_ascii=False, indent=1)
    print(f"✅ {saida}: {NOME} (3 eventos do grupo, ângulo CAM B); {levados} mob(s) de fecho\n✅ {plano}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
