"""O SOM com velocidade mudada no Premiere entra no Avid com a velocidade (o AudioSuite TIME SHIFT), não a 100 % calado.

Rodar:

    .venv/bin/python tests/test_velocidade_do_som_avb.py        (Windows: .venv-win/Scripts/python)

Achado na EDL da B30 (2026-11-25): o Premiere põe `M2 … 012.0` no som do clipe a 50 %, e o MC não punha nada — o
escritor da bin só fazia o efeito de velocidade na IMAGEM. A 1ª tentativa (o Audio Warp, `EFF_TIMEWARP.AUDIO_TIME_WARP`)
o MC tocou a 100 % — é o adaptador de taxa mista. O gesto do editor é o AudioSuite TIME SHIFT (autor, 2026-11-26; medido
de ouvido a 50 % depois do render): clipe de dentro com a MESMA duração e o mesmo ponto de entrada; a velocidade no
`d_c006` do chunk; sem render (`precomputed=None`). Segmentos → `translate.tracks_from_segments` + `build` num `.avb`,
relido.
"""
import struct
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import avb  # noqa: E402
from avb_export import translate as T  # noqa: E402

casos = 0
falhas: list[str] = []
FPS = 24000 / 1001
A = "11" * 32


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    passou = obtido == esperado
    print(f"  {'✓' if passou else '✗'} {nome}" + ("" if passou else f": {obtido!r} ≠ {esperado!r}"))
    if not passou:
        falhas.append(nome)


def seg(track, ini, dur, **kw):
    s = {"track": track, "timeline_tc_in": T._frames_tc(ini, FPS), "duration_frames": dur, "clip_name": "a",
         "mob_id": "a", "source_start_frames": 48, "source_fps": FPS, "is_gap": False, "is_transition": False,
         "is_audio": track >= 1000, "is_effect": False, "disabled": False, "effects": [], "source_slot_id": 1}
    s.update(kw)
    return s


def _vel(ch, alvo=b"d_c006"):
    i = 4
    while i < len(ch):
        tag = ch[i:i + 6]; i += 8
        if tag[:1] == b"d":
            if tag == alvo:
                return struct.unpack(">d", ch[i:i + 8])[0]
            i += 8
        else:
            i += 4


def montar(segs):
    T.ER = FPS
    T.set_remap(None)
    T.set_master_len({})
    T.set_origem("premiere", FPS)
    try:
        tpl = T.capture_templates()
        pic, snd = T.tracks_from_segments(segs, FPS, {}, {"a": A})
        arq = Path(tempfile.mkdtemp(prefix="dlpc_vel_som_")) / "t.avb"
        with avb.file.AVBFile() as f:
            T.build(f, "T", pic + snd, tpl, 24, 9, "HD 1080p/23.976")
            f.write(str(arq))
    finally:
        T.set_origem(None, None)
    out = {}
    with avb.open(str(arq)) as f:
        comp = next(m for m in f.content.mobs if m.name == "T")
        for t in comp.tracks:
            if t.media_kind != "sound":
                continue
            for c in t.component.components:
                if type(c).__name__ == "AudioSuitePluginEffect" and c.attributes["_EFFECT_PLUGIN_NAME"] == "Reverse":
                    dentro = c.tracks[0].component
                    dentro = next(x for x in getattr(dentro, "components", [dentro]) if x.length)
                    out[t.index] = ("Reverse", c.length, c.precomputed, dentro.length, dentro.start_time)
                elif type(c).__name__ == "AudioSuitePluginEffect":
                    dentro = c.tracks[0].component
                    dentro = next(x for x in getattr(dentro, "components", [dentro]) if x.length)
                    ch = bytes(c.plugins[0].chunks[0].data)
                    todos = bytes(c.attributes["_AUDIO_SUITE_EFFECT_0_ALL_CHUNKS"])
                    out[t.index] = (c.attributes["_EFFECT_PLUGIN_NAME"], c.length, c.precomputed,
                                    type(dentro).__name__, dentro.length, dentro.start_time,
                                    _vel(ch), todos.endswith(ch), round(_vel(ch, b"d_c005"), 6))
                elif type(c).__name__ == "SourceClip" and c.length:
                    out[t.index] = ("clip", c.length, c.start_time)
    return out


def main() -> int:
    vel = seg(1000, 0, 72, has_motion_effect=True, speed_ratio=2.0, relative_speed=2.0)
    r = montar([seg(1, 0, 72, is_audio=False), vel])
    ok("50 %: Time Shift sem render, 72 de fonte do mesmo ponto, velocidade 0,5 no chunk e no atributo do painel",
       r.get(1), ("Time Shift", 72, None, "SourceClip", 72, 48, 0.5, True, 1.0))
    r = montar([seg(1, 0, 72, is_audio=False), seg(1000, 0, 72, has_motion_effect=True, speed_ratio=2.0, mantem_tom=False)])
    ok("50 % SEM manter o tom (o Premiere como fita): o Shift = 0,5 também", r.get(1)[6:9] if r.get(1) else None,
       (0.5, True, 0.5))
    r = montar([seg(1, 0, 72, is_audio=False), seg(1000, 0, 72, has_motion_effect=True, speed_ratio=0.5)])
    ok("200 %: velocidade 2,0 (⬜ não medido no MC)", r.get(1)[4:7] if r.get(1) else None, (72, 48, 2.0))
    r = montar([seg(1, 0, 72, is_audio=False), seg(1000, 0, 72, reverso_som=True)])
    ok("o som em REVERSO: o AudioSuite Reverse sem render sobre o trecho para a frente (72 do 48)", r.get(1),
       ("Reverse", 72, None, 72, 48))
    r = montar([seg(1, 0, 72, is_audio=False), seg(1000, 0, 72)])
    ok("a 100 %: clipe simples, como antes", r.get(1), ("clip", 72, 48))
    print(f"{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
