"""SEQUÊNCIA de imagens como um clipe só (laboratório BL08, P10, 2026-11-22):

    .venv/bin/python tests/test_sequencia_de_imagens.py        (Windows: .venv-win/Scripts/python)

- o casador compara o NOME-BASE da sequência (`A003C001.1641600.dpx` → `A003C001`), e o índice com dicas de nome não a
  descarta;
- a entrega escreve a sequência na sintaxe FilmLight (`A003C001.%.7F.dpx`: com um quadro só, o Baselight a conformou como
  imagem PARADA), com a taxa da montagem (o DPX não tem; o ffprobe inventa 25), a duração em quadros e o 1º número como TC;
- o esperado da conferência soma o número do 1º quadro (o Baselight conta o ponto pelo nome do arquivo).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import entrega as E  # noqa: E402
from media import matcher as M  # noqa: E402


def test_sequencia():
    with tempfile.TemporaryDirectory() as d:
        pasta = os.path.join(d, "A003C001")
        os.makedirs(pasta)
        for n in range(1641600, 1641610):
            open(os.path.join(pasta, f"A003C001.{n:07d}.dpx"), "wb").close()
        q = os.path.join(pasta, "A003C001.1641600.dpx")
        base, primeiro, n, padrao = E.quadro_de_sequencia(q)
        assert (primeiro, n, os.path.basename(padrao)) == (1641600, 10, "A003C001.%.7F.dpx")
        assert E.quadro_de_sequencia(padrao)[1:3] == (1641600, 10)
        assert E.quadro_de_sequencia(os.path.join(d, "A001C003.mov")) is None
        o = E.descrever(q, {"fps": 25.0, "tc": None, "w": 1920, "h": 1080}, fps_sequencia=24000 / 1001)
        assert os.path.basename(o["caminho"]) == "A003C001.%.7F.dpx" and o["quadros"] == 10 and o["timebase"] == 24
        assert o["tc"] == "19:00:00:00" and o["ntsc"] == "TRUE", o
        f = {"filename": "A003C001.1641600.dpx", "sequence": {"base": "A003C001"}}
        assert M._nome_do_arquivo(f) == "A003C001"
        assert M._nome_do_arquivo({"filename": "A001C003.mov"}) == "A001C003"


if __name__ == "__main__":
    test_sequencia()
    print("ok test_sequencia")
    sys.exit(0)
