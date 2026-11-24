"""Spike — o lado AVID do teste G01 da Carta Aberta: escreve, numa bin NOVA, os três objetos que viajam VIVOS.

    python spikes/carta_aberta_avid_g01.py <bin de saída>

- `G01-GRUPO-SOM`: group clip das 3 câmeras + o som direto (ângulo de som), pontos de sincronia no instante 10:00:12:00;
- `G01_CAM2.sync.01`: subclipe SINCRONIZADO — imagem da CAM 2 desde o início, som direto desde o quadro 240
  (a forma lida num `.sync.01` do MC: `usage 2`, cada trilha um `SourceClip` direto no master, início POR trilha);
- `G01_CAM3.sub.01`: subclipe simples, quadros 200–399 da CAM 3 (imagem e som da câmera).

Masters: as bins `CARTA ABERTA G01 MASTERS` e `CARTA ABERTA G01 SOM` do projeto de ensaio (laboratório, receita
`MIDIAS DE TESTES/3 CONJUNTOS DOS APPS/_CICLO ASSIST/carta_aberta/G01_GRUPO_23976.json`). O fecho vai oculto.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import avb  # noqa: E402
from avb.mobid import MobID  # noqa: E402

from cicloassist.avid import timeline as T  # noqa: E402
from carta_aberta_group_clip import _comp, montar_grupo  # noqa: E402

PROJETO = Path("~/Documents/Avid Projects/producao-a-ENSAIO")
CAM = "G01_CAM{}_T01_MOV-PRORES"
SOM = "G01_SOMDIRETO_T01_WAV-BWF.wav"
#: quadro de cada fonte no instante 10:00:12:00 da cena (o verdade.json: CAM 1 às :05, CAM 2 às :12, CAM 3 às :08,
#: o som às :02 — em quadros de TC a 23,976)
SINCRONIA = {CAM.format(1): 168, CAM.format(2): 0, CAM.format(3): 96, SOM: 240}


def montar_subclipe(f, nome: str, partes: list[tuple], comprimento: int, edit_rate: float):
    """`partes` = [(master, espécie, índice no master, início)] — UMA trilha do subclipe cada, na ordem.
    A forma de um subclipe do MC (`usage 2`): trilha com `SourceClip` DIRETO, sem `Sequence`; o início é POR trilha
    (é o que faz o sincronizado: imagem de um master, som de outro, cada um no seu ponto)."""
    sub = _comp(f, nome, edit_rate, 2, comprimento)
    sub.attributes = T._atributos(f, _SAVED_AAF_AUDIO_RATE_NUM=24000, _SAVED_AAF_AUDIO_RATE_DEN=1001,
                                  _IN=0, _OUT=comprimento, _START=0, _END=comprimento)
    contagem = {"picture": 0, "sound": 0}
    for master, kind, indice, inicio in partes:
        contagem[kind] += 1
        sc = f.create.SourceClip(edit_rate, kind)
        sc.mob_id = MobID(str(master.mob_id))
        sc.track_id = indice
        sc.start_time = inicio
        sc.length = comprimento
        tr = f.create.Track()
        tr.index = contagem[kind]
        tr.component = sc
        tr.lock_number = 0
        if kind == "picture":
            tr.filler_proxy = T._referencia_de_track(f, edit_rate, "picture")
            tr.session_attr = T._atributos(f, _MONSTATE=1, _ENBLSTATE=1)
        else:
            tr.session_attr = T._atributos(f, _MONSTATE=2, _ENBLSTATE=1)
            tr.attributes = T._atributos(f, AudioMixerCompSolo=0, AudioMixerCompMute=0)
        sub.tracks.append(tr)
    f.content.add_mob(sub).user_placed = True
    return sub


def _trilhas(m, kind):
    return [t.index for t in m.tracks if t.component.media_kind == kind]


def _comprimento(m):
    return max(t.component.length for t in m.tracks if t.component.media_kind in ("picture", "sound"))


def main(saida: str) -> None:
    if Path(saida).exists():
        raise SystemExit(f"⛔ {saida} já existe: nunca por cima")
    with contextlib.ExitStack() as p:
        f = p.enter_context(avb.open())
        origens = [p.enter_context(avb.open(str(PROJETO / f"{n}.avb")))
                   for n in ("CARTA ABERTA G01 MASTERS", "CARTA ABERTA G01 SOM")]
        masters = {m.name: m for o in origens for m in o.content.mobs if getattr(m, "mob_type", "") == "MasterMob"}
        rate = masters[CAM.format(1)].tracks[0].component.edit_rate

        grupo, _ = montar_grupo(f, "G01-GRUPO-SOM", [(masters[n], s) for n, s in SINCRONIA.items()], rate)

        cam2, som = masters[CAM.format(2)], masters[SOM]
        desl = SINCRONIA[SOM] - SINCRONIA[CAM.format(2)]
        n = min(_comprimento(cam2), _comprimento(som) - desl)
        sync = montar_subclipe(f, "G01_CAM2.sync.01",
                               [(cam2, "picture", 1, 0)] + [(som, "sound", i, desl) for i in _trilhas(som, "sound")],
                               n, rate)

        cam3 = masters[CAM.format(3)]
        sub = montar_subclipe(f, "G01_CAM3.sub.01",
                              [(cam3, "picture", 1, 200)] + [(cam3, "sound", i, 200) for i in _trilhas(cam3, "sound")],
                              200, rate)

        ids = {m.mob_id for m in masters.values()}
        levados = 0
        ja = set()
        for o in origens:
            levados += T._levar_fecho(f, o, {i for i in ids if str(i) in {str(x.mob_id) for x in o.content.mobs}}, ja)
            ja |= {str(x.mob_id) for x in o.content.mobs}
        f.write(saida)
    print(f"✅ {saida}: {grupo.name} ({grupo.length}), {sync.name} ({sync.length}, som desde {desl}), "
          f"{sub.name} (200 desde o 200); {levados} mob(s) de fecho")


if __name__ == "__main__":
    main(sys.argv[1])
