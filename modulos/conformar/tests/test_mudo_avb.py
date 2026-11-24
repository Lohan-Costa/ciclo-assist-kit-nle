"""O clipe DESLIGADO entra desligado no Avid, como o Mute Clips do MC (decisão do autor, 2026-10-29).

Rodar:

    .venv/bin/python tests/test_mudo_avb.py        (Windows: .venv-win/Scripts/python)

Antes, o escritor da bin trocava o plano desligado por VAZIO (`translate._seg_to_entry_base`) e nada contava: no R04 os 2
áudios desligados do Premiere sumiam calados (medido no MC 24.6, Windows). A forma certa é a que o próprio MC grava no
Mute Clips, lida nas bins reais do PRODUCAO-A: `Selector` com o ramo 0 = Filler e o ramo 1 = o clipe com os efeitos
dele, `selected 0`, `is_ganged`, `_DISABLE_CLIP_FLAG 1`, `_AAF_SELECTED 0`; no vídeo a trilha do Filler leva um TrackRef
de fundo com `relative_scope 1`. Aqui: segmentos → `translate.tracks_from_segments` + `build` num `.avb`, relido.
"""
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
A, B = "11" * 32, "22" * 32


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    passou = obtido == esperado
    print(f"  {'✓' if passou else '✗'} {nome}" + ("" if passou else f": {obtido!r} ≠ {esperado!r}"))
    if not passou:
        falhas.append(nome)


def seg(track, ini, dur, nome, **kw):
    s = {"track": track, "timeline_tc_in": T._frames_tc(ini, FPS), "duration_frames": dur, "clip_name": nome,
         "mob_id": nome, "source_start_frames": kw.pop("src", 0), "source_fps": FPS, "is_gap": False,
         "is_transition": False, "is_audio": track >= 1000, "is_effect": False, "disabled": False, "effects": []}
    s.update(kw)
    return s


def montar(segs):
    """{(tipo, índice): [componentes]} do .avb escrito e relido."""
    T.ER = FPS
    T.set_remap(None)
    T.set_master_len({})
    T.set_origem("premiere", FPS)
    try:
        tpl = T.capture_templates()
        pic, snd = T.tracks_from_segments(segs, FPS, {}, {"a": A, "b": B})
        arq = Path(tempfile.mkdtemp(prefix="dlpc_mudo_")) / "t.avb"
        with avb.file.AVBFile() as f:
            T.build(f, "T", pic + snd, tpl, 24, 9, "HD 1080p/23.976")
            f.write(str(arq))
    finally:
        T.set_origem(None, None)
    with avb.open(str(arq)) as f:
        comp = next(m for m in f.content.mobs if m.name == "T")
        return {(t.media_kind, t.index): [_resumo(c) for c in t.component.components if c.length]
                for t in comp.tracks if t.media_kind in ("picture", "sound")}


def _resumo(c):
    n = type(c).__name__
    if n == "Selector":
        a = c.attributes or {}
        ramos = []
        for tk in c.tracks:
            x = tk.component
            fp = tk.property_data.get("filler_proxy")
            ramos.append((type(x).__name__, x.length, fp.relative_scope if fp is not None else None,
                          _resumo(x) if type(x).__name__ != "Filler" else None))
        return ("MUDO", c.length, c.selected, c.is_ganged, a.get("_DISABLE_CLIP_FLAG"), a.get("_AAF_SELECTED"), ramos)
    if n == "SourceClip":
        return ("clip", c.length, c.start_time)
    if n == "PanVolumeEffect":
        return ("ganho", c.length, [_resumo(tk.component) for tk in c.tracks if tk.component is not None])
    return (n, c.length)


def video():
    print("vídeo desligado")
    r = montar([seg(1, 0, 24, "a"), seg(1, 24, 24, "b", src=10, disabled=True), seg(1, 48, 24, "a", src=48)])
    v1 = r[("picture", 1)]
    ok("o plano desligado continua no lugar (não vira vazio)", [x[:2] for x in v1],
       [("clip", 24), ("MUDO", 24), ("clip", 24)])
    ok("a forma do Mute Clips: selected 0, ganged, as duas marcas", v1[1][2:6], (0, True, 1, 0))
    ok("ramo 0 = vazio com o fundo (scope 1); ramo 1 = o clipe com a entrada certa", v1[1][6],
       [("Filler", 24, 1, None), ("SourceClip", 24, None, ("clip", 24, 10))])


def som():
    print("som desligado (com ganho)")
    ganho = {"name": "Audio Gain", "category": "gain", "reproducible": True, "params": {"level_num": 2 ** 30}}
    r = montar([seg(1, 0, 48, "a"),
                seg(1000, 0, 24, "a", source_slot_id=1, disabled=True, effects=[ganho]),
                seg(1000, 24, 24, "b", source_slot_id=1)])
    a1 = r[("sound", 1)]
    ok("o som desligado fica no lugar", [x[:2] for x in a1], [("MUDO", 24), ("clip", 24)])
    ok("o ganho vai DENTRO do ramo desligado; o ramo 0 do som não leva fundo", a1[0][6],
       [("Filler", 24, None, None), ("PanVolumeEffect", 24, None, ("ganho", 24, [("clip", 24, 0)]))])


def nada_a_calar():
    print("desligado sem mídia")
    r = montar([seg(1, 0, 24, "a"), seg(1, 24, 24, "zzz", disabled=True), seg(1, 48, 24, "b")])
    ok("o que não casou continua vazio (não há o que desligar)", [x[:2] for x in r[("picture", 1)]],
       [("clip", 24), ("Filler", 24), ("clip", 24)])


if __name__ == "__main__":
    video()
    som()
    nada_a_calar()
    print(f"\n{casos - len(falhas)}/{casos} casos")
    sys.exit(1 if falhas else 0)
