"""O Motion do Premiere → o efeito geométrico do Avid (`avb_export.translate._geo_premiere`, 2026-10-25).

Rodar:

    .venv/bin/python tests/test_geo_premiere.py        (Windows: .venv-win/Scripts/python)

Medido no MC 25.12 pelo PRODC contra a referência (108 → 133/144): Resize quando cobre e não anima, PIP quando não cobre
ou anima, 3D Warp quando gira ou espelha; posição em milésimos do quadro (+Y desce no Resize/PIP, sobe no 3D Warp);
escala em %; a animação em pontos (quadro do efeito, valor), o 1º no 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_export import translate as T  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def seg(**p):
    return {"effects": [{"name": "Motion", "params": {"scale_x": 1.0, "scale_y": 1.0, "pos_x": 0.0, "pos_y": 0.0,
                                                      "rot_z": 0.0, **p}}]}


def main() -> int:
    ok("Motion neutro: nada", T._geo_premiere(seg()), None)
    ok("sem Motion: nada", T._geo_premiere({"effects": []}), None)
    eid, p, k = T._geo_premiere(seg(scale_x=2.0, scale_y=2.0, pos_y=255.556))
    ok("ampliado e cobre: Resize", eid, "EFF2_BLEND_RESIZE")
    ok("…escala em % e posição em milésimos com +Y para BAIXO",
       (p[T.AFX_SCALE_X], p[T.AFX_SCALE_Y], p[T.AFX_POS_X], p[T.AFX_POS_Y], p[T.AFX_LOCK]), (200.0, 200.0, 0.0, -255.556, 1))
    eid, p, _k = T._geo_premiere(seg(scale_x=1.0, scale_y=1.067))
    ok("escala só no Y (a proporção do arquivo): Resize sem a trava", (eid, p[T.AFX_LOCK], p[T.AFX_SCALE_Y]),
       ("EFF2_BLEND_RESIZE", 0, 106.7))
    eid, _p, _k = T._geo_premiere(seg(scale_x=0.5, scale_y=0.5))
    ok("reduzido (não cobre): PIP, que deixa ver a trilha de baixo", eid, "EFF2_BLEND_PIP")
    eid, _p, _k = T._geo_premiere(seg(scale_x=1.76, scale_y=1.76, pos_x=-500.0))
    ok("deslocado a ponto de mostrar a borda: PIP", eid, "EFF2_BLEND_PIP")
    eid, p, k = T._geo_premiere(seg(scale_x=1.2, scale_y=1.2, kf={"pos_x": [(100, 0.0), (110, -0.25)],
                                                                  "zoom": [(100, 1.2), (110, 1.5)]}))
    ok("animado: PIP, com pontos desde o quadro 0", (eid, k[T.AFX_POS_X]), ("EFF2_BLEND_PIP", [(0, 0.0), (10, -250.0)]))
    ok("…escala uniforme animada: o Y acompanha o X", (k[T.AFX_SCALE_X], k[T.AFX_SCALE_Y]),
       ([(0, 120.0), (10, 150.0)], [(0, 120.0), (10, 150.0)]))
    eid, p, _k = T._geo_premiere(seg(scale_x=1.3, scale_y=1.3, pos_y=107.654, flip_x=True))
    ok("espelhado: 3D Warp com rotação Y de 180°", (eid, p[T.DVE_ROT_Y], p.get(T.DVE_ROT_X)), ("EFF2_SBLEND", 180.0, None))
    ok("…posição do DVE com +Y para CIMA e os interruptores ligados",
       (p[T.DVE_POS_Y], p[T.DVE_POS_ON], p[T.DVE_SCALE_ON], p[T.DVE_ROT_ON]), (107.654, 1, 1, 1))
    eid, p, k = T._geo_premiere(seg(scale_x=2.0, scale_y=2.0, rot_z=-246.428,
                                    kf={"rot": [(5, -246.428), (30, -181.288)]}))
    ok("girado: 3D Warp, rotação com o sinal medido", (eid, p[T.DVE_ROT_Z], k[T.DVE_ROT_Z]),
       ("EFF2_SBLEND", 246.428, [(0, 246.428), (25, 181.288)]))
    # ── máscara de opacidade → AniMatte ──────────────────────────────────────────────────────────────────────
    import struct
    molde = T._ANIMATTE_BZFX()
    ok("o molde do AniMatte (bin do laboratório, 4 vértices) está nos moldes", (len(molde), molde[:4]), (532, b"BZFX"))
    quad = [(-100.0, -50.0, (0, 0), (0, 0), False), (100.0, -50.0, (0, 0), (0, 0), False),
            (100.0, 50.0, (0, 0), (0, 0), False), (-100.0, 50.0, (0, 0), (0, 0), False)]
    b = T._bzfx([(quad, 5.0, 10.0)], molde)
    ok("⭐ 1 forma de 4 vértices = 532 bytes, como o MC grava", len(b), 532)
    ok("…com o Feathering (+31/+39 da forma) e a contagem (+268)",
       (struct.unpack(">2d", b[43:59]), struct.unpack(">I", b[12 + 268:12 + 272])[0]), ((5.0, 10.0), 4))
    ok("…e o 1º vértice (x, y) no registro", struct.unpack(">2d", b[12 + 276 + 10:12 + 276 + 26]), (-100.0, -50.0))
    ok("duas formas: 12 + 2 × (276 + 4 × 62 − 4)", len(T._bzfx([(quad, 0, 0), (quad, 0, 0)], molde)), 12 + 2 * 520)
    # um quadrado no meio da FONTE 1920×1080, sem Motion: x ±(0,25 × 1920) → ±180 na escala de 720; y ±(0,25 × 1080) →
    # ±60,75 na de 243
    m = {"vertices": [[False, [u, v], [u, v], [u, v]] for u, v in ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75))],
         "invertida": False, "suave_px": 12.0, "expansao_px": 0.0, "quadros": []}
    sg = {"fonte_px": (1920, 1080), "duration_frames": 3,
          "effects": [{"name": "Máscara de opacidade (Fusion)", "params": {"mascaras": [m]}}]}
    bl = T._animatte_premiere(sg)
    ok("⭐ um keyframe por quadro, percent_time de 0 a 2^30", [pt for pt, _b in bl], [0, 1 << 29, 1 << 30])
    x, y = struct.unpack(">2d", bl[0][1][12 + 276 + 10:12 + 276 + 26])
    ok("o vértice da fonte vira a unidade do AniMatte (720 × 243, centro 0)", (round(x, 3), round(y, 3)), (-180.0, -60.75))
    sg["effects"].append({"name": "Motion", "params": {"scale_x": 2.0, "scale_y": 2.0, "pos_x": 100.0, "pos_y": 0.0}})
    x, y = struct.unpack(">2d", T._animatte_premiere(sg)[0][1][12 + 276 + 10:12 + 276 + 26])
    ok("…passando pelo Motion (×2 e +100 milésimos em X)", (round(x, 3), round(y, 3)), (-288.0, -121.5))
    ok("sem o tamanho da fonte, a máscara não vai", T._animatte_premiere(dict(sg, fonte_px=None)), None)
    ok("máscara invertida: não vai (⏳)", T._animatte_premiere(
        {**sg, "effects": [{"name": "Máscara de opacidade (Fusion)", "params": {"mascaras": [dict(m, invertida=True)]}}]}),
       None)

    # ── imagem parada: sem o adaptador de taxa (o PGLUE do cartão do PRODC) ────────────────────────────────────
    T.set_origem("premiere", 23.976)
    st = {"clip_name": "TitleCard.psd.jpg", "source_fps": 25.0, "duration_frames": 119, "source_start_frames": 0}
    ok("⭐ JPG com a taxa de 25 declarada: sem adaptador", T._entry_outra_taxa(st, "00" * 32), None)
    T.set_origem(None, None)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
