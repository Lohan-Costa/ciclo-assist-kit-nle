"""Os dois consertos que o Subclipar trouxe de volta do Assist anterior (2026-09-21).

⭐ Os dois nasceram no PORTE do painel para o Assist anterior — o mesmo código rodando
noutro lugar mostrou o que aqui passava despercebido — e ficaram meses anotados como
dívida do Órbita. Estes testes existem para a dívida não voltar.

⚠️ Nenhum deles abre o Media Composer: o `MediaComposer` é um duplo, e o que se mede
é o que o sidecar faz antes e depois de falar com ele.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import main as M
from avid.takes import Tomada, Trecho


@pytest.fixture
def respostas(monkeypatch):
    """Captura o que o sidecar escreveria no stdout, já desserializado."""
    linhas: list[dict] = []
    monkeypatch.setattr(M, "_write_line", lambda s: linhas.append(json.loads(s)))
    return linhas


def _resposta(linhas: list[dict]) -> dict:
    finais = [l for l in linhas if "event" not in l]
    assert finais, f"o comando não respondeu: {linhas}"
    return finais[-1]


# ── a coluna V/A conta TRILHAS, não trechos ──────────────────────────────────

def _tomada(trechos: tuple[Trecho, ...]) -> Tomada:
    return Tomada(nome="C04_P01_T001", cena="C04", plano="P01", take="T001",
                  edit_rate=29.97, duracao=400, trechos=trechos, origem="sequencia")


def test_a_camera_em_dois_arquivos_conta_UMA_trilha_de_imagem():
    """⛔⛔ O defeito que veio de volta: dois trechos da MESMA trilha de origem
    (a câmera que parou e voltou) saíam como `V2`. A coluna V/A existe justamente
    para denunciar multicâmera — anunciar uma falsa é pior que não ter a coluna."""
    t = _tomada((
        Trecho(mob_id="cam", track_id=1, media_kind="picture", start=0, length=8,
               trilha_de_origem=1),
        Trecho(mob_id="cam", track_id=1, media_kind="picture", start=8, length=392,
               trilha_de_origem=1),
        Trecho(mob_id="som", track_id=1, media_kind="sound", start=0, length=400,
               trilha_de_origem=2),
        Trecho(mob_id="som", track_id=2, media_kind="sound", start=0, length=400,
               trilha_de_origem=3),
    ))
    assert M._tomada_para_tela(t)["trilhas"] == {"picture": 1, "sound": 2}


def test_cameras_DIFERENTES_continuam_contando_duas():
    """A guarda do conserto: o remédio não pode apagar a multicâmera de verdade —
    trilhas de origem diferentes são câmeras diferentes."""
    t = _tomada((
        Trecho(mob_id="camA", track_id=1, media_kind="picture", start=0, length=400,
               trilha_de_origem=1),
        Trecho(mob_id="camB", track_id=1, media_kind="picture", start=0, length=400,
               trilha_de_origem=2),
    ))
    assert M._tomada_para_tela(t)["trilhas"]["picture"] == 2


def test_a_taxa_do_material_viaja_para_a_tela():
    """O painel converte quadros em segundos, e a taxa é a do MATERIAL. Sem ela na
    linha, a tabela dividia por 24 fixo — 25% a mais a 29,97."""
    t = _tomada((Trecho(mob_id="cam", track_id=1, media_kind="picture",
                        start=0, length=400, trilha_de_origem=1),))
    assert M._tomada_para_tela(t)["edit_rate"] == pytest.approx(29.97)


# ── o nome da timeline é RÓTULO: não recusa o arrasto ────────────────────────

MOB = "060a2b340101010501010f1013-000000-66131c7412678306-d35904bf1b65-d319"


class _McDuplo:
    """O mínimo que o `avid_timeline` toca. `falha_em` diz quais chamadas explodem."""

    def __init__(self, falha_em=()):
        self.falha_em = set(falha_em)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def bin_do_mob(self, mob):
        if "bin" in self.falha_em:
            raise M_err("o Media Composer não respondeu")
        return "C:/Proj/D02_SYNC.avb"

    def colunas_do_master(self, mob, todas=False):
        if "colunas" in self.falha_em:
            raise M_err("coluna indisponível")
        return {"Name": "D02 SYNC"}

    def projeto(self):
        if "projeto" in self.falha_em:
            raise M_err("projeto indisponível")
        return {"path": "C:/Proj"}


def M_err(msg):
    from avid.mcapi import McApiError
    return McApiError(msg)


def _timeline(respostas, monkeypatch, falha_em=()):
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda: _McDuplo(falha_em))
    M.handle_command({"id": "1", "command": "avid_timeline", "params": {"mob_id": MOB}})
    return _resposta(respostas)


def test_a_bin_resolvida_volta_com_nome_e_projeto(respostas, monkeypatch):
    r = _timeline(respostas, monkeypatch)
    assert r["ok"] is True
    assert r["data"]["bin"] == "C:/Proj/D02_SYNC.avb"
    assert r["data"]["nome"] == "D02 SYNC"
    assert r["data"]["pasta_projeto"] == "C:/Proj"


def test_a_coluna_Name_que_falha_NAO_derruba_o_arrasto(respostas, monkeypatch):
    """⭐ O que identifica a timeline é o CAMINHO, que já temos. Recusar o arrasto
    porque o enfeite não veio manda o editor depurar o lugar errado."""
    r = _timeline(respostas, monkeypatch, falha_em=("colunas",))
    assert r["ok"] is True, f"o arrasto foi recusado por causa do nome: {r}"
    assert r["data"]["bin"] == "C:/Proj/D02_SYNC.avb"
    assert r["data"]["nome"] == "timeline", "e a tela ganha um rótulo genérico"


def test_a_pasta_do_projeto_que_falha_tambem_nao_derruba(respostas, monkeypatch):
    r = _timeline(respostas, monkeypatch, falha_em=("projeto",))
    assert r["ok"] is True
    assert r["data"]["pasta_projeto"] == ""


def test_a_BIN_que_falha_CONTINUA_sendo_erro(respostas, monkeypatch):
    """⛔ A guarda do conserto: sem a bin não há o que arrastar. Engolir esta falha
    entregaria ao painel um caminho vazio, e o erro apareceria três telas adiante."""
    r = _timeline(respostas, monkeypatch, falha_em=("bin",))
    assert r["ok"] is False
    assert "respondeu" in r["error"]
