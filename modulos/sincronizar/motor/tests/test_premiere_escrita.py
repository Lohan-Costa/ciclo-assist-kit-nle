"""`premiere/escrita.py`: das `Tomada` da aba de merged para o `.prproj` só-merged."""

from __future__ import annotations

import gzip
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as M
from premiere import escrita
from premiere.tomadas import ler_registros, pares
from prproj.validate import validate

FPS = 25.0


def _probe(caminho):
    if caminho.endswith(".mov"):
        return {"duration_ms": 20000, "fps": 25, "tc_start": "10:00:00:00",
                "total_audio_channels": 2}
    if caminho.endswith("quebrado.wav"):
        return {}
    return {"duration_ms": 60000, "sample_rate": 48000, "channels": 4}


def _linha(kind, track, start, dur, path, in_point=0.0):
    return "\t".join([kind, str(track), "0", str(start), str(in_point), str(dur), "0", path])


def _tomadas(tmp_path, *extra):
    cam, som = str(tmp_path / "A001.mov"), str(tmp_path / "C4 P1-T002.wav")
    texto = "\n".join([
        # câmera de 20 s, colocada 30 s depois do início do som, usando do 2º ao 12º s
        _linha("V", 0, 32, 10, cam, in_point=2),
        _linha("A", 0, 0, 38, som), _linha("A", 1, 0, 38, som),
        *extra,
    ])
    return [p.tomada for p in pares(ler_registros(texto), FPS)[0]]


def test_montar_reconstroi_sync_e_aparo(tmp_path):
    daily, aparos, ignoradas = escrita.montar(_tomadas(tmp_path), FPS, probe=_probe)
    assert ignoradas == []
    cam = daily.takes[0].cameras[0]
    # frame 0 da câmera cai no segundo 30 do som
    assert cam.sync_offset_frames == 30 * 25
    assert cam.duration_frames == 20 * 25
    assert cam.alternate_start_ticks == 10 * 3600 * 25 * round(254016000000 / 25)
    assert daily.takes[0].sound.channels == 4
    # a câmera vai de 2 s a 12 s no arquivo; o som acaba em 38 s da timeline → 8 s
    assert aparos[0].entrada == pytest.approx(2)
    assert aparos[0].saida == pytest.approx(8)


def test_tomada_com_midia_ilegivel_fica_de_fora(tmp_path):
    ruim = str(tmp_path / "quebrado.wav")
    extra = (_linha("V", 1, 100, 5, str(tmp_path / "B001.mov")), _linha("A", 0, 100, 5, ruim))
    daily, aparos, ignoradas = escrita.montar(_tomadas(tmp_path, *extra), FPS, probe=_probe)
    assert len(daily.takes) == 1
    assert ignoradas == ["B001.mov"]


def test_escrever_da_o_nome_da_tela_a_linha_da_bin(tmp_path):
    tomadas = _tomadas(tmp_path)
    from dataclasses import replace
    tomadas = [replace(tomadas[0], nome="C04_T002")]
    saida = tmp_path / "m.prproj"
    r = escrita.escrever(tomadas, FPS, saida, "D01 MERGED", alvo="2023", probe=_probe)

    assert r["bin"] == "D01 MERGED"
    assert r["aparos"] == [{"nome": "C04_T002", "chega_como": "A001.mov - Merged",
                            "in": pytest.approx(2), "out": pytest.approx(8)}]
    raiz = ET.fromstring(gzip.open(saida, "rt", encoding="utf-8").read().split("?>", 1)[1])
    nomes = [i.findtext("./ProjectItem/Name") for i in raiz.iter("ClipProjectItem")]
    assert nomes == ["C04_T002"]
    assert [b.findtext("./ProjectItem/Name") for b in raiz.iter("BinProjectItem")] == ["D01 MERGED"]
    assert raiz.find("Project").get("Version") == "41"
    assert validate(saida) == []


def test_sem_nada_escrevivel_recusa(tmp_path):
    with pytest.raises(ValueError):
        escrita.escrever([], FPS, tmp_path / "x.prproj", "B", probe=_probe)


# ── pelo despachante ─────────────────────────────────────────────────────────

@pytest.fixture
def respostas(monkeypatch):
    linhas: list[dict] = []
    monkeypatch.setattr(M, "_write_line", lambda s: linhas.append(json.loads(s)))
    monkeypatch.setattr("media.inspector.probe", _probe)
    return linhas


def _final(linhas):
    return [l for l in linhas if "event" not in l][-1]


def test_comando_escreve_com_o_padrao_da_tela(respostas, tmp_path):
    cam, som = str(tmp_path / "A001.mov"), str(tmp_path / "C4 P1-T002.wav")
    registros = "\n".join([_linha("V", 0, 32, 10, cam, in_point=2), _linha("A", 0, 0, 38, som)])
    M.handle_command({"id": "L", "command": "premiere_merged_read",
                      "params": {"registros": registros, "fps": FPS}})
    saida = tmp_path / "out.prproj"
    M.handle_command({"id": "W", "command": "premiere_merged_write",
                      "params": {"leitura_id": "L", "padrao": "C%{cena}_%{nomedevideo}",
                                 "output_path": str(saida), "bin": "SEQ MERGED"}})
    r = _final(respostas)
    assert r["ok"], r
    assert r["data"]["aparos"][0]["nome"] == "C04_A001.mov"
    assert saida.exists()


def test_comando_recusa_leitura_do_avid_e_caminho_ruim(respostas, tmp_path):
    M._ULTIMAS_TOMADAS = {"id": "AV", "nle": "avid", "tomadas": [1], "colunas": {},
                          "nomes": {}, "bin": "x"}
    M.handle_command({"id": "W", "command": "premiere_merged_write",
                      "params": {"leitura_id": "AV", "output_path": str(tmp_path / "a.prproj")}})
    assert _final(respostas)["ok"] is False

    cam, som = str(tmp_path / "A001.mov"), str(tmp_path / "C4 P1-T002.wav")
    M.handle_command({"id": "L", "command": "premiere_merged_read",
                      "params": {"registros": "\n".join([_linha("V", 0, 0, 5, cam),
                                                          _linha("A", 0, 0, 5, som)]),
                                 "fps": FPS}})
    M.handle_command({"id": "W2", "command": "premiere_merged_write",
                      "params": {"leitura_id": "L", "output_path": "relativo.txt"}})
    assert _final(respostas)["ok"] is False


# ── o frame a mais (2026-09-17) ──────────────────────────────────────────────

def test_duracao_usa_a_contagem_real_de_frames():
    """CAM0001.mov da Projeto C: 1236 frames, 51552 ms. O `ceil` antigo dava 1237 — o frame
    preto que o autor viu no fim do merged."""
    from sync.model import duration_frames as _duration_frames
    assert _duration_frames(51552.0, 23.976, 1236, 23.976) == 1236
    # sem a contagem, a folga do ceil também acerta este caso
    assert _duration_frames(51552.0, 23.976) == 1236
    # e um clipe de fração real de frame ainda arredonda para cima
    assert _duration_frames(51570.0, 23.976) == 1237
    # arquivo em outro fps: a contagem dele não vale para o projeto
    assert _duration_frames(10000.0, 25.0, 300, 30.0) == 250


def test_o_aparo_nao_passa_do_fim_real_da_camera(tmp_path):
    """Sequência exportada com o frame a mais: o item é 1 frame mais longo que o arquivo."""
    cam, som = str(tmp_path / "A001.mov"), str(tmp_path / "C4 P1-T002.wav")
    texto = "\n".join([_linha("V", 0, 0, 20.04, cam),   # 501 frames a 25 fps
                       _linha("A", 0, 0, 60, som)])
    tomadas = [p.tomada for p in pares(ler_registros(texto), FPS)[0]]
    probe = lambda c: dict(_probe(c), frame_count=500) if c.endswith(".mov") else _probe(c)
    _d, aparos, _i = escrita.montar(tomadas, FPS, probe=probe)
    assert aparos[0].saida == pytest.approx(500 / FPS)
