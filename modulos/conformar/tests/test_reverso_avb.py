"""O REVERSO escrito na bin do Avid pelo gráfico de POSIÇÃO (`avb_export/translate.py::_reverso_por_posicao`).

## Por que este teste existe

2026-11-21, laboratório BL04 (Baselight; MC 25.12 Mac): o reverso escrito pela velocidade constante NEGATIVA
(`EFF_ADV_MOTION_CTL`) tocou PARA FRENTE (300 → 347) — o MC renderiza pelo MAPA (p1), e o escritor levava o mapa de
0 a +|v|·n. E o AAF que o MC exportava daquele plano dizia 300 → 253: o Baselight receberia um plano trocado sem
ninguém perceber. Agora o reverso vai quadro a quadro pela posição (o molde provado com "ré de 2", 48/48).

Convenção do segmento neutro: `source_start_frames` = o 1º quadro MOSTRADO, descendo.
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "plugins" / "media-composer" / "servico")]
logging.disable(logging.WARNING)

from avb_export import translate as T  # noqa: E402

F = 24000 / 1001


def _seg(**k):
    s = {"duration_frames": 48, "source_start_frames": 300, "source_fps": F, "has_motion_effect": True,
         "motion_effect_type": "reverse", "speed_ratio": 1.0, "speed_keyframes": [], "source_offset_map": [],
         "retime": None, "clip_name": "A001C001"}
    s.update(k)
    return s


def _quadros(e):
    """O quadro da fonte que o MC mostra em cada quadro: in do clipe de dentro + piso(posição)."""
    _kind, (_tag, pos, _kfs, _render), (_h, inicio, _n), _dur, _ = e
    return [inicio + math.floor(p + 1e-6) for p in pos]


def test_reverso_premiere_100():
    T.set_origem("premiere", F)
    try:
        e = T._motion_entry_from_seg(_seg(), "00" * 32)
    finally:
        T.set_origem(None, None)
    assert e[1][0] == "pos"
    assert _quadros(e) == list(range(300, 252, -1))          # 300, 299, …, 253
    assert e[2][1] == 253                                      # o clipe de dentro começa no mais BAIXO
    assert len(e[1][2]) == 48                                  # um keyframe por quadro


def test_reverso_premiere_200():
    T.set_origem("premiere", F)
    try:
        e = T._motion_entry_from_seg(_seg(speed_ratio=0.5, duration_frames=24), "00" * 32)   # recíproco: 200 %
    finally:
        T.set_origem(None, None)
    assert _quadros(e) == list(range(300, 252, -2))


def test_reverso_pelo_mapa_do_avid():
    # o AAF do Avid traz o mapa já integrado, relativo ao in do clipe de dentro (o quadro mais baixo)
    T.set_origem("avid", F)
    try:
        e = T._motion_entry_from_seg(_seg(source_start_frames=253, source_offset_map=[(0.0, 47.0), (48.0, -1.0)]),
                                     "00" * 32)
    finally:
        T.set_origem(None, None)
    assert _quadros(e) == list(range(300, 252, -1))


def test_reverso_antes_do_arquivo_cai_no_caminho_antigo():
    T.set_origem("premiere", F)
    try:
        e = T._motion_entry_from_seg(_seg(source_start_frames=10), "00" * 32)
    finally:
        T.set_origem(None, None)
    assert e[1][0] != "pos"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
