"""`gerar_midia_de_teste` — a operação 1 do ensaio (docs/plano/2026-10-31-operacoes-do-ensaio.md)."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from cicloassist import laboratorio as L
from cicloassist.mcp import registro
from cicloassist.mcp.ferramentas import laboratorio as F

TEM_LAB = L.raiz() is not None


def _lab_falso(tmp_path: Path, caso: str = "X01_TESTE", tomadas=((1, 2), (3, 4))) -> Path:
    lab = tmp_path / "familia" / L.PASTA
    (lab / "lab").mkdir(parents=True)
    (lab / "lab" / "multicam.py").write_text("", encoding="utf-8")
    (lab / "receitas" / "multicam").mkdir(parents=True)
    (lab / "receitas" / "multicam" / f"{caso}.json").write_text(json.dumps({
        "caso": caso, "pergunta": "p", "cena": {"segundos": 10},
        "fontes": [{"nome": "CAM 1", "tomadas": [list(t) for t in tomadas]}]}), encoding="utf-8")
    return lab


def test_acha_o_laboratorio_subindo_de_pasta(tmp_path):
    lab = _lab_falso(tmp_path)
    fundo = tmp_path / "familia" / "2 ATIVOS" / "app" / "pacote"
    fundo.mkdir(parents=True)
    assert L.raiz(fundo / "x.py") == lab.resolve()
    assert L.raiz(tmp_path / "x.py") is None


def test_a_ferramenta_escreve_e_vale_nos_dois_editores():
    f = registro.FERRAMENTAS["gerar_midia_de_teste"]
    assert f.escreve is True
    assert "premiere" in f.nles and "avid" in f.nles


def test_receita_e_nome_nunca_caminho(tmp_path, monkeypatch):
    """⛔ ADR 0005: um caminho escrito pelo modelo não vira receita."""
    lab = _lab_falso(tmp_path)
    monkeypatch.setattr(L, "raiz", lambda inicio=None: lab)
    assert F._conferir(receita="X01_TESTE") == ""
    recusa = F._conferir(receita=str(lab / "receitas" / "multicam" / "X01_TESTE.json"))
    assert "Não há a receita" in recusa and "X01_TESTE (2 arquivos: CAM 1)" in recusa


def test_sem_laboratorio_diz(monkeypatch):
    monkeypatch.setattr(L, "raiz", lambda inicio=None: None)
    assert "não está nesta máquina" in F._conferir(receita="M06_4TOMADAS")


def test_pronto_e_reaproveitado_sem_rodar_nada(tmp_path, monkeypatch):
    lab = _lab_falso(tmp_path)
    monkeypatch.setattr(L, "raiz", lambda inicio=None: lab)
    pasta = lab / "saida" / "multicam" / "X01_TESTE"
    pasta.mkdir(parents=True)
    (pasta / "verdade.json").write_text(json.dumps({"caso": "X01_TESTE", "arquivos": [
        {"arquivo": "CAM 1/a.mov", "fonte": "CAM 1", "tomada": 1, "inicio_na_cena_s": 1.0, "tc": None}]}),
        encoding="utf-8")
    monkeypatch.setattr(L.subprocess, "Popen", lambda *a, **k: pytest.fail("não devia gerar"))
    r = L.gerar("X01_TESTE")
    assert r["como"] == "reaproveitado" and len(r["arquivos"]) == 1


def test_receita_mais_nova_que_a_verdade_nao_esta_pronta(tmp_path, monkeypatch):
    lab = _lab_falso(tmp_path)
    monkeypatch.setattr(L, "raiz", lambda inicio=None: lab)
    pasta = lab / "saida" / "multicam" / "X01_TESTE"
    pasta.mkdir(parents=True)
    (pasta / "verdade.json").write_text("{}", encoding="utf-8")
    velho = time.time() - 3600
    os.utime(pasta / "verdade.json", (velho, velho))
    assert L.pronto("X01_TESTE") is False


@pytest.mark.skipif(not TEM_LAB or not shutil.which("ffmpeg"), reason="sem o laboratório ou o ffmpeg")
def test_gera_de_verdade_e_nunca_por_cima(tmp_path, monkeypatch):
    """O gerador do laboratório, ponta a ponta, numa cópia da raiz com a saída no tmp. A
    segunda geração com refazer cai numa pasta NOVA."""
    real = L.raiz()
    lab = tmp_path / L.PASTA
    shutil.copytree(real / "lab", lab / "lab", ignore=shutil.ignore_patterns("__pycache__", "windows", "moldes"))
    (lab / "receitas" / "multicam").mkdir(parents=True)
    rec = {"caso": "X02_CURTO", "pergunta": "p", "cena": {"segundos": 4, "relogio": "10:00:00:00", "semente": 3},
           "raster": [320, 180], "perfil_video": "mov-h264",
           "fontes": [{"nome": "CAM 1", "camera": 1, "fps": "25", "tc": "relogio", "tomadas": [[0.5, 2.5]]},
                      {"nome": "SOM DIRETO", "som": True, "canais": 1, "tc": "relogio", "tomadas": [[0, 3]]}]}
    (lab / "receitas" / "multicam" / "X02_CURTO.json").write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setattr(L, "raiz", lambda inicio=None: lab)
    avisos = []
    r = L.gerar("X02_CURTO", relatar=lambda *a: avisos.append(a))
    assert r["como"] == "gerado" and len(r["arquivos"]) == 2, r
    assert any(a[1] is not None for a in avisos)
    assert L.gerar("X02_CURTO")["como"] == "reaproveitado"
    r2 = L.gerar("X02_CURTO", refazer=True)
    assert r2["pasta"] != r["pasta"] and Path(r["pasta"], "verdade.json").is_file()
