"""Nest de outro programa → Collapse do Avid no escritor da bin (pedido do autor, 2026-10-13; decisão de 2026-10-12: um
Collapse por ocorrência).

Rodar:

    .venv/bin/python tests/test_nest_collapse.py        (Windows: .venv-win/Scripts/python)

Segmentos como os do leitor do `.prproj` (marca `composto`) → `translate.tracks_from_segments` + `build` num `.avb` em
memória: um Submaster por ocorrência, na trilha mais baixa, com as trilhas internas na forma medida no laboratório (B21:
uma camada = uma interna que olha embaixo; várias = fundo + uma por camada), a velocidade DENTRO, o som fora, e o nest
cuja mídia não casou vira vazio (o export do MC recusa um Collapse vazio). Também a velocidade CONSTANTE do `.prproj`,
que chega só no `speed_ratio` recíproco.
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
A, B = "11" * 32, "22" * 32          # hex dos masters (o name2h devolve o hex final)


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    passou = obtido == esperado
    print(f"  {'✓' if passou else '✗'} {nome}" + ("" if passou else f": {obtido!r} ≠ {esperado!r}"))
    if not passou:
        falhas.append(nome)


def seg(track, ini, dur, nome, composto=None, **kw):
    s = {"track": track, "timeline_tc_in": T._frames_tc(ini, FPS), "duration_frames": dur, "clip_name": nome,
         "mob_id": nome, "source_start_frames": kw.pop("src", 0), "source_fps": FPS, "is_gap": False,
         "is_transition": False, "is_audio": track >= 1000, "is_effect": False, "disabled": False, "effects": []}
    if composto:
        s["composto"] = {"id": composto, "nome": "NEST_" + composto}
    s.update(kw)
    return s


def montar(segs):
    """(componentes da V1, V2, …) do .avb escrito e relido."""
    T.ER = FPS
    T.set_remap(None)
    T.set_master_len({})
    T.set_origem("premiere", FPS)
    try:
        tpl = T.capture_templates()
        pic, snd = T.tracks_from_segments(segs, FPS, {}, {"a": A, "b": B})
        arq = Path(tempfile.mkdtemp(prefix="dlpc_nest_")) / "t.avb"
        with avb.file.AVBFile() as f:
            T.build(f, "T", pic + snd, tpl, 24, 9, "HD 1080p/23.976")
            f.write(str(arq))
    finally:
        T.set_origem(None, None)
    with avb.open(str(arq)) as f:
        comp = next(m for m in f.content.mobs if m.name == "T")
        out = {}
        for t in comp.tracks:
            if t.media_kind in ("picture", "sound"):
                out[(t.media_kind, t.index)] = [_resumo(c) for c in t.component.components if c.length or
                                                getattr(c, "effect_id", None)]
        return out


def _resumo(c):
    n = type(c).__name__
    if n == "TrackEffect" and c.effect_id == "EFF_SUBMASTER":
        return ("COLLAPSE", c.length, [(tk.index, tk.filler_proxy.relative_scope,
                                        [_resumo(x) for x in tk.component.components if x.length])
                                       for tk in c.tracks])
    if n == "SourceClip":
        return ("clip", c.length, c.start_time)
    if n == "MotionEffect":
        return ("vel", c.length)
    return (n, c.length)


def uma_camada():
    print("nest de uma camada (o B16)")
    r = montar([seg(1, 0, 48, "a"),
                seg(2, 12, 12, "b", "n1", src=6),
                seg(2, 24, 12, "b", "n1", src=30)])
    v2 = r[("picture", 2)]
    ok("V2: vazio até o nest, um Collapse de 24, vazio até o fim",
       [x[:2] for x in v2], [("Filler", 12), ("COLLAPSE", 24), ("Filler", 12)])
    ok("uma trilha interna, olha embaixo, os dois clipes no lugar",
       v2[1][2], [(1, 1, [("clip", 12, 6), ("clip", 12, 30)])])
    ok("V1 intacta", r[("picture", 1)], [("clip", 48, 0)])


def varias_camadas():
    print("nest de duas camadas (V2 e V3 do leitor)")
    r = montar([seg(1, 0, 24, "a"),
                seg(2, 0, 24, "b", "n2"),
                seg(3, 6, 12, "a", "n2", src=100)])
    ok("o Collapse fica na trilha MAIS BAIXA", r[("picture", 2)][0][:2], ("COLLAPSE", 24))
    ok("fundo + uma interna por camada (índices 1, 2, 3; só o fundo olha embaixo)",
       r[("picture", 2)][0][2],
       [(1, 1, [("Filler", 24)]), (2, 0, [("clip", 24, 0)]), (3, 0, [("Filler", 6), ("clip", 12, 100), ("Filler", 6)])])
    ok("a V3 fica (vazia) — as de cima não descem", r[("picture", 3)], [("Filler", 24)])


def velocidade_e_som():
    print("velocidade dentro, som fora, nest sem mídia")
    r = montar([seg(1, 0, 36, "a"),
                seg(2, 0, 12, "b", "n3", has_motion_effect=True, motion_effect_type="constant",
                    speed_ratio=0.21428572158424247),
                seg(2, 12, 12, "zzz", "n4"),                      # mídia que não casou
                seg(1000, 0, 12, "a", "n3", source_slot_id=1)])
    v2 = r[("picture", 2)]
    ok("a velocidade constante do .prproj (speed_ratio recíproco) vai DENTRO do Collapse",
       v2[0][2], [(1, 1, [("vel", 12)])])
    ok("o nest cuja mídia não casou vira vazio, não um Collapse vazio", [x[:2] for x in v2][1:],
       [("Filler", 24)])
    ok("o som do nest fica como trilha comum", r[("sound", 1)], [("clip", 12, 0), ("Filler", 24)])
    T.set_origem("premiere", FPS)
    sp = T._motion_entry_from_seg(dict(seg(2, 0, 12, "b"), motion_effect_type="constant",
                                       speed_ratio=0.25), A)
    ok("speed_ratio 0,25 = 4 quadros da fonte por quadro", (sp[1][1][0]["speed"], sp[2][2]), (4.0, 48))
    T.set_origem(None, None)
    ok("fora do Premiere o speed_ratio sozinho não vira velocidade",
       T._motion_entry_from_seg(dict(seg(2, 0, 12, "b"), speed_ratio=0.25), A), None)


def outra_taxa():
    print("fonte de outra taxa (100 qps numa timeline de 23,976): o adaptador do Avid")
    T.ER = FPS
    T.set_origem("premiere", FPS)
    a = T._entry_outra_taxa(dict(seg(2, 0, 12, "b", src=4), source_fps=100.0), A)
    ok("tempo real: adaptador, a trilha de dentro em quadros da fonte (12 → 51)", a[:2] + (a[2][1:],), ("adapter", 100.0, (4, 51)))
    r = T._entry_outra_taxa(dict(seg(2, 0, 3, "b"), source_fps=100.0, has_motion_effect=True,
                                 motion_effect_type="ramp", source_offset_map=[(0, 0.0), (1, 16.68), (2, 37.54)]), A)
    ok("com velocidade: gráfico de posição em quadros da fonte, com a taxa", (r[0], r[1][0], r[1][1], r[1][4]),
       ("motion", "pos", [0.0, 16.68, 37.54], 100.0))
    ok("mesma taxa: não é caso de adaptador", T._entry_outra_taxa(seg(2, 0, 12, "b"), A), None)
    # a fase do Premiere (PRODC, LOU_7231 a 60 qps num nest, 2026-10-18): o mapa começa em −0,36 — não é ré. Antes caía no
    # motion genérico (início em quadros da fonte numa trilha a 23,976) e o MC 24.6 recusava a sequência inteira
    fase = T._entry_outra_taxa(dict(seg(2, 0, 3, "b", src=2768), source_fps=60.0, has_motion_effect=True,
                                    motion_effect_type="ramp",
                                    source_offset_map=[(0, -0.36), (1, 2.17), (2, 4.69)]), A)
    ok("fase negativa: o clipe de dentro começa no quadro do piso (2767) e as posições vão junto",
       (fase[0], fase[1][0], [round(p, 2) for p in fase[1][1]], fase[1][4], fase[2][1]),
       ("motion", "pos", [0.64, 3.17, 5.69], 60.0, 2767))
    ok("andar para trás continua sendo ré (não medido)",
       T._entry_outra_taxa(dict(seg(2, 0, 3, "b", src=50), source_fps=60.0, has_motion_effect=True,
                                motion_effect_type="ramp", source_offset_map=[(0, 4.0), (1, 2.0), (2, 0.0)]), A), None)
    T.set_origem(None, None)
    ok("fora do Premiere: não mexe", T._entry_outra_taxa(dict(seg(2, 0, 12, "b"), source_fps=100.0), A), None)
    tpl = T.capture_templates()
    T.set_origem("premiere", FPS)
    with avb.file.AVBFile() as f:
        me = T._build_one(f, a, "picture", tpl)
        sq = me.tracks[0].component
        sc = next(x for x in sq.components if type(x).__name__ == "SourceClip")
        ok("o adaptador como o MC grava: [240, 1001], Both Fields, dentro a 100 qps",
           (me.speed_ratio, dict(me.attributes)["_MIXMATCH_MOTIONADAPTER"], dict(me.attributes)["_SFX_RENDER"],
            sq.edit_rate, sc.edit_rate, sc.start_time, sc.length), ([240, 1001], 2, 2, 100.0, 100.0, 4, 51))
        mp = T._build_one(f, r, "picture", tpl)
        ok("o gráfico de posição sobre outra taxa vai PROMOVIDO (4), dentro a 100 qps",
           (dict(mp.attributes)["_MIXMATCH_MOTIONADAPTER"], mp.tracks[0].component.edit_rate), (4, 100.0))
    T.set_origem(None, None)


def main() -> int:
    uma_camada()
    varias_camadas()
    velocidade_e_som()
    outra_taxa()
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
