"""Os comandos do sidecar da aba de merged do Premiere, pelo despachante.

⭐ O que se prova aqui é a COSTURA: a leitura do Premiere fica guardada no mesmo
lugar da do Avid, e `avid_subclips_preview`/`_scene`/`_drop` a servem sem saber de
onde ela veio. E que o escritor do Avid recusa uma lista do Premiere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import main as M


@pytest.fixture
def respostas(monkeypatch):
    linhas: list[dict] = []
    monkeypatch.setattr(M, "_write_line", lambda s: linhas.append(json.loads(s)))
    return linhas


def _final(linhas):
    finais = [l for l in linhas if "event" not in l]
    assert finais, linhas
    return finais[-1]


def _linha(kind, track, start, dur, path, in_point=0.0):
    return "\t".join([kind, str(track), "0", str(start), str(in_point), str(dur), "0", path])


REGISTROS = "\n".join([
    _linha("V", 0, 0, 10, "/d/A001.mov"),
    _linha("V", 1, 5, 10, "/d/B001.mov"),
    _linha("V", 0, 100, 10, "/d/A002.mov"),          # órfã
    _linha("A", 0, 0, 20, "/d/C4 P1-T002.wav"),
    _linha("A", 1, 0, 20, "/d/C4 P1-T002.wav"),
])


def _ler(respostas):
    M.handle_command({"id": "L1", "command": "premiere_merged_read",
                      "params": {"registros": REGISTROS, "fps": 25}})
    return _final(respostas)


def test_ler_devolve_as_tomadas_o_resumo_e_o_catalogo(respostas):
    r = _ler(respostas)
    assert r["ok"] is True
    d = r["data"]
    assert d["leitura_id"] == "L1"
    assert [t["nome"] for t in d["tomadas"]] == ["A001.mov", "B001.mov", "A002.mov"]
    assert d["tomadas"][1]["aparado"] == 0
    assert d["resumo"]["orfaos_de_camera"] == 1
    assert any(c["nome"] == "cena" for c in d["catalogo"])


def test_preview_cena_e_remover_do_avid_servem_a_leitura_do_premiere(respostas):
    _ler(respostas)

    M.handle_command({"id": "P", "command": "avid_subclips_preview",
                      "params": {"leitura_id": "L1", "padrao": "C%{cena}_%{nomedevideo}"}})
    assert [l["nome"] for l in _final(respostas)["data"]["linhas"]] == [
        "C04_A001.mov", "C04_B001.mov", "C04_A002.mov"]   # A002 é solta: a cena vem da vizinha

    M.handle_command({"id": "S", "command": "avid_subclips_scene",
                      "params": {"leitura_id": "L1", "indices": [1], "cena": "9"}})
    M.handle_command({"id": "P2", "command": "avid_subclips_preview",
                      "params": {"leitura_id": "L1", "padrao": "C%{cena}"}})
    assert [l["nome"] for l in _final(respostas)["data"]["linhas"]] == ["C04", "C9", "C04"]

    M.handle_command({"id": "D", "command": "avid_subclips_drop",
                      "params": {"leitura_id": "L1", "indices": [0]}})
    assert [t["nome"] for t in _final(respostas)["data"]["tomadas"]] == ["B001.mov", "A002.mov"]


def test_o_escritor_do_avid_recusa_uma_lista_do_premiere(respostas):
    _ler(respostas)
    M.handle_command({"id": "W", "command": "avid_subclips_write",
                      "params": {"leitura_id": "L1", "padrao": ""}})
    r = _final(respostas)
    assert r["ok"] is False
    assert "Premiere" in r["error"]


@pytest.mark.parametrize("params", [
    {"registros": "", "fps": 25},
    {"registros": REGISTROS, "fps": 0},
    {"registros": REGISTROS, "fps": "x"},
    {"registros": None, "fps": 25},
])
def test_entrada_ruim_e_recusada(respostas, params):
    M.handle_command({"id": "X", "command": "premiere_merged_read", "params": params})
    assert _final(respostas)["ok"] is False
