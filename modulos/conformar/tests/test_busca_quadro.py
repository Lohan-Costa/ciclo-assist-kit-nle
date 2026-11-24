"""A conferência pela imagem não confia no `-ss` onde a busca mente (banco, B053; 2026-10-28).

Rodar:  .venv/bin/python tests/test_busca_quadro.py        (Windows: .venv-win/Scripts/python)

MEDIDO num V01.mxf MPEG-2 gerenciado do Avid (cabeçalho 11,988, média 23,976): o `-ss` no instante do quadro N entregou
o quadro N/2. Com a busca suspeita (cabeçalho ≠ média), `conferir_conform._cinza` decodifica EM ORDEM pelo índice na
taxa votada — no mesmo MXF, o quadro pedido saiu exato (diferença 0,00). Aqui: a decisão, com os streams medidos.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from tools import conferir_conform as C  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def taxa(stream: dict):
    C._BUSCA.clear()
    with mock.patch("media.sonda.ler", return_value={"streams": [{"codec_type": "video", **stream}]}):
        t = C._taxa_se_a_busca_mente("/x/a")
    return round(t, 3) if t else t


def main() -> int:
    ok("MXF MPEG-2 do Avid (11,988 no cabeçalho, 23,976 de média): busca suspeita, em ordem a 23,976",
       taxa({"r_frame_rate": "12000/1001", "avg_frame_rate": "24000/1001", "time_base": "1001/24000"}), 23.976)
    ok("MOV normal (cabeçalho = média): o -ss de sempre", taxa({"r_frame_rate": "24/1", "avg_frame_rate": "24/1"}), None)
    ok("sem leitura: o -ss de sempre", taxa({}), None)
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
