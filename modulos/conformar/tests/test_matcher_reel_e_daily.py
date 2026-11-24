"""O casador do AAF/MC (`media/matcher`) com as regras do autor de 2026-11-22, as mesmas do casador do Premiere:

    .venv/bin/python tests/test_matcher_reel_e_daily.py        (Windows: .venv-win/Scripts/python)

- REEL é critério: sem original com o nome do plano, o reel do DAILY acha o original (BL08, P4). O MC 25.12 não leva o
  `reel_name` do QuickTime para o AAF — o reel vem do arquivo do daily (`media/confirmacao.reel_do_arquivo`).
- Reel degenerado ("1" do BRAW, só dígitos) não casa nada (B040).
- EMPATE: o quadro do daily × o de cada candidato; um bate e o outro não → ele, `verified`, com as notas. Dois parecidos →
  continua sem caminho, para o editor.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from media import confirmacao as C  # noqa: E402
from media import matcher as M  # noqa: E402


def _arquivo(d, nome, dado=b"x"):
    p = os.path.join(d, nome)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(dado)
    return p


def _seg(clip, daily, dur=10.0):
    return {"clip_name": clip, "mob_id": "", "is_audio": False,
            "media_ref": {"mob_name": clip, "local_path": daily, "source_duration_secs": dur,
                          "source_fps": 24.0}}


def _file(p, dur=10.0):
    return {"path": p, "filename": os.path.basename(p), "duration_secs": dur}


def test_reel_e_criterio():
    with tempfile.TemporaryDirectory() as d:
        daily = _arquivo(d, "DAILIES/CENA12_T3.mov")
        orig = _arquivo(d, "ORIG/B001C007.mov")
        outro = _arquivo(d, "ORIG/B001C008.mov")
        with mock.patch.object(C, "reel_do_arquivo", lambda c: "B001C007" if c == daily else None):
            r = M._match_one(0, _seg("CENA12_T3", daily), [_file(orig), _file(outro)], None, dict(M.DEFAULT_OPTIONS))
        assert r.matched_path == orig and r.match_method == "reel", r.to_dict()
        with mock.patch.object(C, "reel_do_arquivo", lambda c: "1"):        # B040: reel degenerado não casa
            r = M._match_one(0, _seg("CENA12_T3", daily), [_file(orig)], None, dict(M.DEFAULT_OPTIONS))
        assert r.match_method != "reel", r.to_dict()


def test_empate_confirmado_pelo_daily():
    with tempfile.TemporaryDirectory() as d:
        daily = _arquivo(d, "DAILIES/A001C004.mov")
        a = _arquivo(d, "DIA01/A001C004.mov", b"a")
        b = _arquivo(d, "DIA02/A001C004.mov", b"b")
        quadros = {daily: bytes([100] * 6912), a: bytes([100] * 6912), b: bytes([160] * 6912)}
        # o casador chama sem `quadro`: troca-se o padrão (o leitor de quadro do ffmpeg) pelos quadros do teste
        with mock.patch.object(C.confirmar_pela_imagem, "__defaults__", (lambda c, t: quadros[c],)):
            r = M._match_one(0, _seg("A001C004", daily), [_file(a), _file(b)], None, dict(M.DEFAULT_OPTIONS))
        assert r.matched_path == a and r.verified and r.imagem[a] == 1.0, r.to_dict()
        quadros[b] = bytes([101] * 6912)                                    # os dois parecidos com o daily
        with mock.patch.object(C.confirmar_pela_imagem, "__defaults__", (lambda c, t: quadros[c],)):
            r = M._match_one(0, _seg("A001C004", daily), [_file(a), _file(b)], None, dict(M.DEFAULT_OPTIONS))
        assert r.matched_path is None and r.ambiguous, r.to_dict()


if __name__ == "__main__":
    for t in (test_reel_e_criterio, test_empate_confirmado_pelo_daily):
        t()
        print("ok", t.__name__)
    sys.exit(0)
