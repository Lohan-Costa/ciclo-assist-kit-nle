"""Spike — EDL para o som, lado MC (plano `docs/plano/2026-11-25-edl-para-o-som.md`): escreve por pyavb, numa bin NOVA,
os casos S1, S6, S7, S10 e S11 sobre a B31 linkada, e grava o `plano.json` — a VERDADE de cada evento (fonte, arquivo,
tape, quadro e TC de origem, canal do ARQUIVO por trilha) que o conferidor compara com a EDL exportada.

    python spikes/edl_som_mc/montar_casos.py <bin dos masters B31> <bin NOVA de saída> <plano.json>

Os casos (23,976; TC da receita: CAM A 14:00:00:00, CAM B 14:00:02:00, som 1 13:59:58:00; CAM A2 15:00:00:00,
som 2 14:59:59:00 — o instante da cena no quadro `a` da CAM A é o `a − 48` da CAM B e o `a + 48` do som 1):

- S1 SUBCLIPE: dois subclipes (CAM A 120–479, CAM B 200–439) usados de dentro (o In do evento ≠ o do master);
- S6 AUTOSYNC: subclipes sincronizados (`.sync.01`: imagem da câmera + os 6 canais do som direto, início POR trilha);
- S7 GROUP: CAM A e CAM B só imagem + o som 1 só som (a regra do autor: o group leva só o som direto), sync por TC,
  ângulo CAM B no grupo, um evento na sequência;
- S10 POLIFÔNICO EM POUCOS CANAIS: A1/A2 da sequência tocam os canais 3/5 e depois 4/6 do WAV de 6;
- S11 MESMO SOUND ROLL: dois takes do mesmo rolo (`26Y11M25`) em seguida — o reel não distingue, só o TC.

Os subclipes, o sincronizado e o grupo vão VISÍVEIS (são o que o editor tem na bin); os masters, ocultos (o fecho).
Nunca grava por cima.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "spikes"))

import avb  # noqa: E402
from avb.mobid import MobID  # noqa: E402

from cicloassist.avid import timeline as T  # noqa: E402
from carta_aberta_group_clip import _comp, montar_grupo  # noqa: E402
from carta_aberta_avid_g01 import montar_subclipe  # noqa: E402

FPS = 24  # o TC nominal de 23,976
CAMA, CAMB, CAMA2 = "A001C003_MOV-PRORES", "B001C007_MOV-PRORES", "A001C004_MOV-PRORES"
SOM1, SOM2 = "12/1", "12/2"
#: o que a receita diz de cada master (o conferidor acha o arquivo pelo reel; a tape é o sound roll do iXML)
FONTES = {
    CAMA: {"arquivo": "A001C003_MOV-PRORES.mov", "tape": None, "tc": "14:00:00:00"},
    CAMB: {"arquivo": "B001C007_MOV-PRORES.mov", "tape": None, "tc": "14:00:02:00"},
    CAMA2: {"arquivo": "A001C004_MOV-PRORES.mov", "tape": None, "tc": "15:00:00:00"},
    SOM1: {"arquivo": "26Y11M25_T001_WAV-BWF.wav", "tape": "26Y11M25", "tc": "13:59:58:00"},
    SOM2: {"arquivo": "26Y11M25_T002_WAV-BWF.wav", "tape": "26Y11M25", "tc": "14:59:59:00"},
}
CANAIS = {1: "MIX L", 2: "MIX R", 3: "BOOM", 4: "LAPELA ANA", 5: "LAPELA BETO", 6: "AMBIENTE"}
INICIO_DA_SEQUENCIA = "01:00:00:00"
#: `--so-audio` (autor, 2026-11-25): a MESMA montagem sem nenhum segmento de vídeo — o AAF do Premiere com merged clip
#: só sai certo sem vídeo na timeline; a pergunta é se a EDL (e o que vai anexado ao som) também muda.
SO_AUDIO = False


def _q(tc: str) -> int:
    h, m, s, f = (int(x) for x in tc.split(":"))
    return ((h * 60 + m) * 60 + s) * FPS + f


def _tc(q: int) -> str:
    f = q % FPS
    s = q // FPS
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


class _SoAlgumas:
    """Um master visto só com algumas trilhas (o group só com o som direto): o `montar_grupo` lê `tracks`/`mob_id`."""

    def __init__(self, master, kinds):
        self.mob_id = master.mob_id
        self.name = master.name
        self.tracks = [t for t in master.tracks if t.component.media_kind in kinds]


def _segmento_de_grupo(f, edit_rate, kind, grupo, trilha: int, inicio: int, dur: int):
    """O group NA TIMELINE como o MC o grava (medido 2026-11-25, MC 25.12 Mac, o grupo arrastado para a timeline pelo
    autor): NÃO um `SourceClip` apontando o grupo, e sim uma CÓPIA do `Selector` da trilha do grupo — mesmo `selected`
    e `is_ganged`, um ramo por ângulo apontando o mob de ALINHAMENTO (`.grp`), aparado no trecho do segmento. Com o
    `SourceClip` no grupo a imagem toca certa, mas o MC não vê um group: sem o (g) no nome e sem a lista de ângulos."""
    modelo = next(t.component for t in grupo.tracks if t.component.media_kind == kind and t.index == trilha)
    sel = f.create.Selector(edit_rate, kind)
    sel.length = dur
    sel.mc_mode = 0
    sel.num_scalars = 0
    sel.is_ganged = modelo.is_ganged
    sel.selected = modelo.selected
    sel.tracks = []
    for ramo in modelo.tracks:
        sc = f.create.SourceClip(edit_rate, kind)
        sc.mob_id = MobID(str(ramo.component.mob_id))
        sc.track_id = ramo.component.track_id
        sc.start_time = inicio
        sc.length = dur
        a = f.create.Track()
        a.component = sc
        a.lock_number = 0
        sel.tracks.append(a)
    return sel


def montar_sequencia(f, nome: str, eventos: list[dict], edit_rate) -> object:
    """`eventos` = [{"dur": n, "trilhas": {("picture"|"sound", índice na sequência): (mob, trilha no mob, início)}}],
    um atrás do outro. Trilha da sequência e trilha do clipe são LIVRES (é o que o S10 precisa)."""
    if SO_AUDIO:
        nome += " SO AUDIO"
        eventos = [{**e, "trilhas": {k: v for k, v in e["trilhas"].items() if k[0] != "picture"}} for e in eventos]
    total = sum(e["dur"] for e in eventos)
    presentes = sorted({k for e in eventos for k in e["trilhas"]}, key=lambda k: (k[0] != "picture", k[1]))
    comp = _comp(f, nome, edit_rate, 0, total)
    comp.attributes = T._atributos(f, _VERSION=2)
    comp.session_attrs = T._atributos(f, _VIS_START=0, _VIS_END=T.MAXIMO)
    for kind, indice in presentes:
        seq = f.create.Sequence(edit_rate, kind)
        seq.components = [T._filler(f, edit_rate, 0, kind)]
        for e in eventos:
            alvo = e["trilhas"].get((kind, indice))
            if alvo is None:
                seq.components.append(T._filler(f, edit_rate, e["dur"], kind))
                continue
            mob, trilha, inicio = alvo
            if getattr(mob, "usage_code", None) == 4:
                seq.components.append(_segmento_de_grupo(f, edit_rate, kind, mob, trilha, inicio, e["dur"]))
                continue
            sc = f.create.SourceClip(edit_rate, kind)
            sc.mob_id = MobID(str(mob.mob_id))
            sc.track_id = trilha
            sc.start_time = inicio
            sc.length = e["dur"]
            seq.components.append(sc)
        seq.components.append(T._trail_filler(f, edit_rate, kind, seq.components, total))
        tr = f.create.Track()
        tr.index = indice
        tr.component = seq
        tr.lock_number = 0
        tr.filler_proxy = T._referencia_de_track(f, edit_rate, kind)
        if kind == "sound":
            tr.session_attr = T._atributos(f, _MONSTATE=2, _ENBLSTATE=1)
            tr.attributes = T._atributos(f, AudioMixerCompSolo=0, AudioMixerCompMute=0)
        else:
            tr.session_attr = T._atributos(f, _ENBLSTATE=1, _MONSTATE=1)
        comp.tracks.append(tr)
    if not any(k[0] == "picture" for k in presentes):
        # a convenção do Avid (cicloassist.avid.timeline): sequência só de som ganha uma V1 VAZIA
        seq = f.create.Sequence(edit_rate, "picture")
        seq.components = [T._filler(f, edit_rate, total, "picture")]
        tr = f.create.Track()
        tr.index = 1
        tr.component = seq
        tr.lock_number = 0
        tr.filler_proxy = T._referencia_de_track(f, edit_rate, "picture")
        tr.session_attr = T._atributos(f, _ENBLSTATE=1, _MONSTATE=1)
        comp.tracks.insert(0, tr)
    tc = f.create.Timecode(edit_rate, "timecode")
    tc.length = total
    tc.flags = 0
    tc.fps = FPS
    tc.start = _q(INICIO_DA_SEQUENCIA)
    tct = f.create.Track()
    tct.index = 1
    tct.component = tc
    tct.lock_number = 0
    tct.session_attr = T._atributos(f, _ENBLSTATE=0)
    comp.tracks.append(tct)
    f.content.add_mob(comp).user_placed = True
    return comp


def _verdade(nome_seq: str, eventos: list[dict], verdade_ev: list[dict]) -> dict:
    """A verdade de cada evento: por trilha da sequência, a fonte, o quadro e o TC de origem e o canal do arquivo."""
    if SO_AUDIO:
        nome_seq += " SO AUDIO"
        verdade_ev = [{k: v for k, v in t.items() if not k.startswith("V")} for t in verdade_ev]
    rec = _q(INICIO_DA_SEQUENCIA)
    out = []
    for e, v in zip(eventos, verdade_ev):
        trilhas = {}
        for rotulo, (fonte, quadro, canal) in v.items():
            ini = _q(FONTES[fonte]["tc"]) + quadro
            trilhas[rotulo] = {"fonte": fonte, **{k: FONTES[fonte][k] for k in ("arquivo", "tape")},
                               "quadro": quadro, "src_in": _tc(ini), "src_out": _tc(ini + e["dur"]),
                               "canal_do_arquivo": canal, "microfone": CANAIS.get(canal) if canal else None}
        out.append({"rec_in": _tc(rec), "rec_out": _tc(rec + e["dur"]), "dur": e["dur"], "trilhas": trilhas})
        rec += e["dur"]
    return {"sequencia": nome_seq, "eventos": out}


def main(origem: str, saida: str, plano: str) -> None:
    for p in (saida, plano):
        if Path(p).exists():
            raise SystemExit(f"⛔ {p} já existe: nunca por cima")
    casos = []
    with contextlib.ExitStack() as pilha:
        f = pilha.enter_context(avb.open())
        o = pilha.enter_context(avb.open(origem))
        M = {m.name: m for m in o.content.mobs if getattr(m, "mob_type", "") == "MasterMob"}
        faltam = [n for n in FONTES if n not in M]
        if faltam:
            raise SystemExit(f"⛔ masters ausentes na bin: {faltam}")
        rate = M[CAMA].tracks[0].component.edit_rate

        def som(mob, inicio, canais, de=1):
            return {("sound", de + i): (mob, c, inicio) for i, c in enumerate(canais)}

        # S1 — subclipes usados de dentro
        sub_a = montar_subclipe(f, "A001C003.sub.01", [(M[CAMA], "picture", 1, 120), (M[CAMA], "sound", 1, 120),
                                                       (M[CAMA], "sound", 2, 120)], 360, rate)
        sub_b = montar_subclipe(f, "B001C007.sub.01", [(M[CAMB], "picture", 1, 200), (M[CAMB], "sound", 1, 200),
                                                       (M[CAMB], "sound", 2, 200)], 240, rate)
        ev = [{"dur": 96, "trilhas": {("picture", 1): (sub_a, 1, 24), **som(sub_a, 24, [1, 2])}},
              {"dur": 72, "trilhas": {("picture", 1): (sub_b, 1, 48), **som(sub_b, 48, [1, 2])}}]
        montar_sequencia(f, "B31 S1 SUBCLIPE", ev, rate)
        casos.append(_verdade("B31 S1 SUBCLIPE", ev, [
            {"V1": (CAMA, 144, None), "A1": (CAMA, 144, 1), "A2": (CAMA, 144, 2)},
            {"V1": (CAMB, 248, None), "A1": (CAMB, 248, 1), "A2": (CAMB, 248, 2)}]))

        # S6 — AutoSync: imagem da câmera + os 6 canais do som direto
        sync1 = montar_subclipe(f, "A001C003.sync.01", [(M[CAMA], "picture", 1, 0)] +
                                [(M[SOM1], "sound", c, 48) for c in range(1, 7)], 719 - 48, rate)
        sync2 = montar_subclipe(f, "A001C004.sync.01", [(M[CAMA2], "picture", 1, 0)] +
                                [(M[SOM2], "sound", c, 24) for c in range(1, 7)], 719 - 24, rate)
        ev = [{"dur": 120, "trilhas": {("picture", 1): (sync1, 1, 72), **som(sync1, 72, range(1, 7))}},
              {"dur": 96, "trilhas": {("picture", 1): (sync2, 1, 96), **som(sync2, 96, range(1, 7))}}]
        montar_sequencia(f, "B31 S6 AUTOSYNC", ev, rate)
        casos.append(_verdade("B31 S6 AUTOSYNC", ev, [
            {"V1": (CAMA, 72, None), **{f"A{c}": (SOM1, 120, c) for c in range(1, 7)}},
            {"V1": (CAMA2, 96, None), **{f"A{c}": (SOM2, 120, c) for c in range(1, 7)}}]))

        # S7 — group: CAM A e CAM B só imagem, o som 1 só som; sync no instante 14:00:02:00 (CAM A 48, CAM B 0,
        # som 96) → no grupo, quadro g = CAM A g−48, CAM B g−96, som g. Ângulo CAM B (o 2º).
        grupo, _ = montar_grupo(f, "12-1 GRUPO", [(_SoAlgumas(M[CAMA], ("picture",)), 48),
                                                  (_SoAlgumas(M[CAMB], ("picture",)), 0),
                                                  (_SoAlgumas(M[SOM1], ("sound",)), 96)], rate, angulo=1)
        ev = [{"dur": 144, "trilhas": {("picture", 1): (grupo, 1, 200), **som(grupo, 200, range(1, 7))}}]
        montar_sequencia(f, "B31 S7 GROUP", ev, rate)
        casos.append(_verdade("B31 S7 GROUP", ev, [
            {"V1": (CAMB, 104, None), **{f"A{c}": (SOM1, 200, c) for c in range(1, 7)}}]))

        # S10 — o WAV de 6 usado em 2 canais: A1/A2 = BOOM/LAPELA BETO (3/5), depois LAPELA ANA/AMBIENTE (4/6)
        ev = [{"dur": 96, "trilhas": {("picture", 1): (M[CAMA], 1, 240), **som(M[SOM1], 288, [3, 5])}},
              {"dur": 72, "trilhas": {("picture", 1): (M[CAMB], 1, 288), **som(M[SOM1], 384, [4, 6])}}]
        montar_sequencia(f, "B31 S10 POUCOS CANAIS", ev, rate)
        casos.append(_verdade("B31 S10 POUCOS CANAIS", ev, [
            {"V1": (CAMA, 240, None), "A1": (SOM1, 288, 3), "A2": (SOM1, 288, 5)},
            {"V1": (CAMB, 288, None), "A1": (SOM1, 384, 4), "A2": (SOM1, 384, 6)}]))

        # S11 — dois takes do MESMO sound roll em seguida (MIX L/R)
        ev = [{"dur": 72, "trilhas": {("picture", 1): (M[CAMA], 1, 100), **som(M[SOM1], 148, [1, 2])}},
              {"dur": 72, "trilhas": {("picture", 1): (M[CAMA2], 1, 100), **som(M[SOM2], 124, [1, 2])}}]
        montar_sequencia(f, "B31 S11 MESMO ROLO", ev, rate)
        casos.append(_verdade("B31 S11 MESMO ROLO", ev, [
            {"V1": (CAMA, 100, None), "A1": (SOM1, 148, 1), "A2": (SOM1, 148, 2)},
            {"V1": (CAMA2, 100, None), "A1": (SOM2, 124, 1), "A2": (SOM2, 124, 2)}]))

        levados = T._levar_fecho(f, o, {m.mob_id for m in M.values()}, set())
        f.write(saida)
    with open(plano, "w", encoding="utf-8") as fh:
        json.dump({"receita": "B31_EDL_SOM", "fps": "23.976", "fontes": FONTES, "canais": CANAIS, "casos": casos},
                  fh, ensure_ascii=False, indent=1)
    print(f"✅ {saida}: {len(casos)} sequências + 2 subclipes + 2 sincronizados + 1 grupo; {levados} mob(s) de fecho")
    print(f"✅ {plano}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--so-audio"]
    SO_AUDIO = len(args) != len(sys.argv) - 1
    if len(args) != 3:
        raise SystemExit(__doc__)
    main(*args)
