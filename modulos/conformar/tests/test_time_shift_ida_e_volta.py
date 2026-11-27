"""O AudioSuite TIME SHIFT (a velocidade do SOM no MC) lido de volta da bin: não se perde calado no caminho ao Premiere.

Rodar:

    .venv/bin/python tests/test_time_shift_ida_e_volta.py        (Windows: .venv-win/Scripts/python)

Achado em 2026-11-26 (autor: "uma vez renderizado no MC e essa TL levada ao Premiere, o que o Premiere recebe?"): a
leitura da bin tirava o clipe de dentro do Time Shift a 100 %, com o efeito como "não reproduzível" e NENHUM marcador —
o Premiere tocava o DOBRO da fonte a 100 %, calado (medido na `B30 EDL 3` do LAB COR MC). O render do MC NÃO é levado (é
mídia gerenciada; o vínculo continua no original). Agora a velocidade do chunk (`d_c006`) vira a do segmento, como a de
uma imagem a 50 %, e a montagem do Premiere a APLICA (`setSpeed` com o tom mantido; autor: "velocidade é base do
conform" — antes de 2026-11-26 tarde ia um marcador "refazer").

Ida: segmentos com velocidade → `translate` (Time Shift, sem render) → `.avb`; volta: `avb_bin.segmentos` → o plano.
"""
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import avb  # noqa: E402
sys.path.append(str(RAIZ.parents[1]))           # o app: a volta ao Premiere é pela Carta (plano 2026-11-26)
from cicloassist.carta import entrega_prproj as EP, timeline as TL  # noqa: E402
from avb_bin.segmentos import ler_timeline_de_arquivo  # noqa: E402
from avb_export import translate as T  # noqa: E402

FPS = 24000 / 1001
A = "11" * 32
casos = 0
falhas: list[str] = []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    passou = obtido == esperado
    print(f"  {'✓' if passou else '✗'} {nome}" + ("" if passou else f": {obtido!r} ≠ {esperado!r}"))
    if not passou:
        falhas.append(nome)


def seg(track, dur, **kw):
    s = {"track": track, "timeline_tc_in": T._frames_tc(0, FPS), "duration_frames": dur, "clip_name": "a",
         "mob_id": "a", "source_start_frames": 48, "source_fps": FPS, "is_gap": False, "is_transition": False,
         "is_audio": track >= 1000, "is_effect": False, "disabled": False, "effects": [], "source_slot_id": 1}
    s.update(kw)
    return s


def ida_e_volta(vel_premiere, **extra):
    T.ER = FPS
    T.set_remap(None)
    T.set_master_len({})
    T.set_origem("premiere", FPS)
    try:
        tpl = T.capture_templates()
        pic, snd = T.tracks_from_segments(
            [seg(1, 72, is_audio=False), seg(1000, 72, has_motion_effect=vel_premiere != 1.0,
                                             speed_ratio=1 / vel_premiere, **extra)],
            FPS, {}, {"a": A})
        arq = Path(tempfile.mkdtemp(prefix="dlpc_ts_")) / "t.avb"
        with avb.file.AVBFile() as f:
            T.build(f, "T", pic + snd, tpl, 24, 9, "HD 1080p/23.976")
            f.write(str(arq))
    finally:
        T.set_origem(None, None)
    r = ler_timeline_de_arquivo(str(arq), nome="T")
    return [s for s in r["segments"] if s.get("is_audio") and not s.get("is_gap")]


def _clipe_da_carta(s: dict) -> dict:
    """O clipe que a Carta escreve para o Premiere a partir do segmento (o leitor comum, `trilhas_de_segmentos`)."""
    tr = TL.trilhas_de_segmentos([{**s, "mob_id": s.get("mob_id") or "m", "timeline_tc_in": "00:00:00:00"}],
                                 lambda tc: 0, lambda x: "midia")
    return tr[0]["clipes"][0]


def main() -> int:
    som = ida_e_volta(0.5)
    s = som[0] if som else {}
    ok("o som volta com a velocidade do Time Shift (0,5, constante), a fonte do mesmo ponto",
       (s.get("has_motion_effect"), s.get("speed_ratio"), s.get("motion_effect_type"), s.get("source_start_frames"),
        s.get("duration_frames")), (True, 0.5, "constant", 48, 72))
    ok("o mapa da fonte: 72 quadros na timeline andam 36 da fonte", s.get("source_offset_map"), [(0.0, 0.0), (72.0, 36.0)])
    ok("o efeito continua listado (Time Shift)", [e.get("label") for e in s.get("effects") or []], ["Time Shift"])
    c = _clipe_da_carta(s)
    ve = EP.velocidade_do_clipe(c, "24000/1001")
    ok("⭐ no Premiere (pela Carta): a velocidade 0,5 mantendo o tom, sem 'fora' (antes: 100 % calado)",
       (ve.get("vel"), (c.get("velocidade") or {}).get("mantem_tom"), "fora" in ve), (0.5, True, False))
    rv = (ida_e_volta(1.0, reverso_som=True) or [{}])[0]
    ok("o REVERSE da bin volta como som em reverso (o mapa desce: 71 → 0, do mesmo trecho)",
       (rv.get("source_start_frames"), rv.get("source_offset_map")), (48, [(0.0, 71.0), (71.0, 0.0)]))
    vr = EP.velocidade_do_clipe(_clipe_da_carta(rv), "24000/1001")
    ok("…e o Premiere (pela Carta) o recebe ao contrário a 100 %, do quadro mais alto (71 depois do 48)",
       (vr.get("vel"), vr.get("rev"), vr.get("desloc")), (None, True, 71.0))
    s1 = (ida_e_volta(1.0) or [{}])[0]
    ok("a 100 %: sem velocidade, como antes", (s1.get("has_motion_effect"), s1.get("speed_ratio")), (False, 1.0))
    print(f"{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
