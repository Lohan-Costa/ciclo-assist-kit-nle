"""Os títulos da montagem no Baselight (`baselight/titulos.py`; a OPÇÃO do autor, 2026-11-23). Pelo produto no PRODUCAO-C: 130 → 132 de 133 (o que sobra é o espaçamento entre letras do "THE", que o Text do Baselight não tem); a scene
provisória apagada; os markers vêm junto no bl-import.

    .venv/bin/python tests/test_baselight_titulos.py
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import efeitos as EF  # noqa: E402
from baselight import titulos as TT  # noqa: E402

TL = 24000 / 1001
TIT = {"name": "Text", "params": {"titulo": {"caixas": [{"texto": "HOW", "corpo": 0.185, "corpo_resolve": 200.0,
       "cor": [1, 1, 1], "alinhamento": "centro", "posicao_resolve": [0.5, 0.57],
       "fonte": {"familia": "Fonte Que Nao Existe", "estilo": "Semibold"}}]}}}


def _leitura():
    return {"timeline_fps": TL, "segments": [{"track": 3, "timeline_tc_in": "00:00:08:04", "duration_frames": 4,
                                              "effects": [TIT]}]}


def test_detalhar_e_a_fonte_ausente():
    lt = _leitura()
    t, = TT.detalhar(EF.titulos(lt), lt)
    assert (t["a"], t["b"], t["corpo_h"], t["alinhamento"]) == (196, 200, 0.185, "centro")
    assert t["arquivo_fonte"] is None
    (q, nota), = TT.marcas([t])
    assert q == 196 and "«HOW»" in nota and "NÃO instalada" in nota and "espaçamento entre letras" in nota


def test_candidatos_do_nome_postscript():
    assert TT._candidatos("Acumin Pro ExtraCondensed", "Semibold")[0] == "AcuminProExtraCond-Semibold"
    assert "ArialMT" in TT._candidatos("Arial", "Regular")


def test_pretos_so_onde_nao_ha_video():
    tits = [{"a": 10, "b": 16}, {"a": 20, "b": 22}]
    assert TT.pretos(tits, lambda q: 12 <= q < 14) == [[10, 12], [14, 16], [20, 22]]


def test_string_do_blscene_conta_bytes():
    assert TT._s("THAT’S") == "s8:THAT’S"


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_") and callable(f):
            f()
            print("ok", nome)
