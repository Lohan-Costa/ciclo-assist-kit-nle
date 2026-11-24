"""`converter_para_opatom` — a operação 3 do ensaio (sem Resolve: a pasta, a conferência, a saída)."""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cicloassist import resolve_opatom as O
from cicloassist.mcp import registro
from cicloassist.mcp.ferramentas import opatom as F

DIA = datetime.date(2026, 11, 1)


def test_pasta_nova_termina_em_zero_e_deixa_o_par_de_som_livre(tmp_path):
    assert O.pasta_nova(tmp_path, DIA).name == "202611010"
    (tmp_path / "202611010").mkdir()
    assert O.pasta_nova(tmp_path, DIA).name == "2026110110"
    (tmp_path / "2026110111").mkdir()            # o SOM de 2026110110 já existe: pula
    assert O.pasta_nova(tmp_path, DIA).name == "2026110120"
    assert O.pasta_nova(tmp_path, DIA).name.isdigit()


def test_videos_da_pasta_pula_pasta_de_trabalho_e_som(tmp_path):
    for f in ["CAM 1/a.mov", "CAM 1/b.MP4", "SOM/x.wav", "_para_consolidar/c.mov", "CAM 1/._a.mov"]:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"")
    assert [p.name for p in O.videos_da_pasta(tmp_path)] == ["a.mov", "b.MP4"]


def test_mistura_de_formatos_e_recusada(monkeypatch):
    fmt = {"a": ("25/1", 1920, 1080), "b": ("24000/1001", 1920, 1080)}
    monkeypatch.setattr(O, "sondar", lambda v: dict(zip(("taxa", "largura", "altura"), fmt[v.stem])))
    motivo, _ = O.conferir_videos([Path("a.mov"), Path("b.mov")])
    assert "misturam" in motivo


def test_formato_conhecido_da_o_codec(monkeypatch):
    monkeypatch.setattr(O, "sondar", lambda v: {"taxa": "25/1", "largura": 1920, "altura": 1080})
    assert O.conferir_videos([Path("a.mov")]) == ("", {"taxa": "25", "largura": 1920, "altura": 1080,
                                                      "codec": "DNxHD1080p36"})


def test_altura_nao_medida_e_recusada(monkeypatch):
    monkeypatch.setattr(O, "sondar", lambda v: {"taxa": "25/1", "largura": 1280, "altura": 720})
    assert "codec" in O.conferir_videos([Path("a.mov")])[0]


def test_nunca_escreve_em_pasta_que_ja_tem_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "sondar", lambda v: {"taxa": "25/1", "largura": 1920, "altura": 1080})
    (tmp_path / "1").mkdir()
    (tmp_path / "1" / "x.mxf").write_bytes(b"")
    with pytest.raises(O.ConversaoFalhou, match="pasta nova"):
        O.converter("P", [Path("a.mov")], tmp_path, destino=tmp_path / "1")


def test_o_preset_que_nao_pegou_para_tudo(monkeypatch, tmp_path):
    """⛔ banco 31/10: LoadRenderPreset True sem aplicar. A frase do filho chega ao modelo como erro."""
    monkeypatch.setattr(O, "sondar", lambda v: {"taxa": "25/1", "largura": 1920, "altura": 1080})
    monkeypatch.setattr(O._resolve, "servidor_no_ar", lambda: True)

    class Proc:
        stdout = iter(['{"etapa": "projeto"}\n', '{"erro": "o preset CICLO-OP-ATOM NÃO foi aplicado"}\n'])
        stderr = iter([])
        def poll(self): return 0
    monkeypatch.setattr(O.subprocess, "Popen", lambda *a, **k: Proc())
    with pytest.raises(O.ConversaoFalhou, match="NÃO foi aplicado"):
        O.converter("P", [Path("a.mov")], tmp_path)


def test_o_filho_compila():
    compile(O._CODIGO, "<filho>", "exec")


def test_o_preset_versionado_existe_e_e_mxf():
    texto = O.PRESET_ARQ.read_text(encoding="utf-8", errors="replace")
    assert "mxf" in texto.lower()


def test_ferramenta_escreve_e_pasta_nao_arrastada_e_recusada(tmp_path, monkeypatch):
    assert registro.FERRAMENTAS["converter_para_opatom"].escreve is True
    monkeypatch.setattr(F._lab, "raiz", lambda inicio=None: None)
    assert "arrast" in F._conferir(projeto="P", pasta=str(tmp_path)).lower()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_conferir_saida_le_o_disco(tmp_path):
    v = tmp_path / "CLIPE_A.mxf"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x180:d=0.2", "-c:v", "mpeg2video",
                    "-metadata", "material_package_name=CLIPE_A", "-f", "mxf_opatom", str(v)], check=True)
    r = O.conferir_saida(tmp_path, ["CLIPE_A.mov"])
    assert r["videos"] == 1 and r["problemas"] == [], r
    assert O.conferir_saida(tmp_path, ["CLIPE_A.mov", "CLIPE_B.mov"])["problemas"]


#: O ffprobe de um `_A01` do Resolve (Studio 19.1.4, 2026-11-01): o stream 0 é `data`.
SOM_DO_RESOLVE = {"streams": [{"index": 0, "codec_type": "data", "tags": {}},
                              {"index": 1, "codec_name": "pcm_s24le", "codec_type": "audio", "bits_per_sample": 24,
                               "bits_per_raw_sample": "24", "tags": {"timecode": "10:00:05:00"}},
                              {"index": 2, "codec_type": "data", "tags": {}}],
                  "format": {"tags": {"material_package_name": "M06_CAM1_T01_MOV-PRORES"}}}


def test_o_som_do_resolve_e_som_mesmo_com_data_na_frente():
    i = O.ler_sonda("x_A01.mxf", SOM_DO_RESOLVE)
    assert (i["tipo"], i["bits"], i["tc"], i["master"]) == ("audio", "24", "10:00:05:00", "M06_CAM1_T01_MOV-PRORES")
