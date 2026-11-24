"""`criar_merged`: o sync e os merged num pedido só, com o proxy CONFERIDO (P4, 2026-11-06).

Contra o Sincronizar de mentira de `test_sincronizar.py` — o contrato do lado de lá é
`DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md` §9.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cicloassist.mcp.ferramentas import merged as M
from cicloassist.mcp.ferramentas import sincronizar as FO
from tests.test_sincronizar import _sinc_inteiro, sinc, premiere_falso  # noqa: F401 — as fixtures


def _com_merged(**mudar):
    r = _sinc_inteiro(**{
        "/api/v1/info": {"ok": True, "version": "0.4.0", "busy": False,
                         "paineis": {"premiere": True}, "capacidades": ["sincronizar", "montar", "merged"]},
        "/api/v1/merge": {"montagem_id": "ponte-3", "nome": "D02", "merged": 2, "com_proxy": 1,
                          "bins": {"NAO RESOLVIDO": 2}, "raiz": "CENAS", "sem_proxy": [], "proxy_ausente": []},
        "/api/v1/montagem": {"estado": "feito", "nome": "D02", "resumo": "ok|merged=2|novos=3|bins=NAO RESOLVIDO"},
    })
    r.update(mudar)
    return r


@pytest.fixture(autouse=True)
def sem_premiere_de_verdade(monkeypatch):
    monkeypatch.setattr(M._premiere, "estado", lambda: {"versao": "25.6.5"})


def test_sincroniza_pede_os_merged_e_diz_onde_estao(sinc, tmp_path, monkeypatch):
    px = tmp_path / "PROXY"
    px.mkdir()
    (px / "A001.mov").write_bytes(b"x")      # A002 não tem proxy
    monkeypatch.setattr(M._px, "sondar", lambda p: {"taxa": 24})
    monkeypatch.setattr(M._px, "conferir_par", lambda o, p: [])
    monkeypatch.setattr(M, "_alcanca", lambda p: True)
    falso = sinc(**_com_merged())

    r = M.criar_merged(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}], proxies=str(px))

    pedido = dict(falso.pedidos)["/api/v1/merge"]
    # ⭐ Vai o JOB do sync, não o mapa — e só o par que conferiu.
    assert pedido["job_id"] == "j9" and pedido["nome"] == "D02" and pedido["premiere_alvo"] == "25"
    assert pedido["proxies"] == {r"D:\D02\CAM A\A001.mp4": str(px / "A001.mov")}
    assert [s["arquivo"] for s in r["sem_proxy"]] == ["A002.mp4"]
    assert r["bins"] == {"CENAS/NAO RESOLVIDO": 2}
    assert "2 merged" in r["feito"] and "CENAS" in r["agora"]
    # ⛔⛔ Nunca a fila do painel dele, e nunca a montagem de sequência.
    assert "/nlejob" not in falso.rotas() and "/api/v1/nlejob" not in falso.rotas()


def test_o_par_que_nao_confere_nao_vai(sinc, tmp_path, monkeypatch):
    px = tmp_path / "PROXY"
    px.mkdir()
    for n in ("A001", "A002"):
        (px / f"{n}.mov").write_bytes(b"x")
    monkeypatch.setattr(M._px, "sondar", lambda p: {"nome": str(p).replace("\\", "/").rsplit("/", 1)[-1]})
    monkeypatch.setattr(M._px, "conferir_par",
                        lambda o, p: ["TC 01:00:00:00 (original 02:00:00:00)"] if o["nome"] == "A002.mp4" else [])
    monkeypatch.setattr(M, "_alcanca", lambda p: True)
    falso = sinc(**_com_merged())
    r = M.criar_merged(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}], proxies=str(px))
    assert list(dict(falso.pedidos)["/api/v1/merge"]["proxies"]) == [r"D:\D02\CAM A\A001.mp4"]
    assert "TC" in r["sem_proxy"][0]["motivo"]


def test_a_conferencia_barra_antes_do_cartao(sinc):
    sinc(**_com_merged(**{"/api/v1/info": {"ok": True, "busy": False, "paineis": {"premiere": True},
                                             "capacidades": ["sincronizar", "montar"]}}))
    assert "Atualize o Sincronizar" in M._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])
    sinc(**_com_merged(**{"/api/v1/info": {"ok": True, "busy": False, "paineis": {"premiere": False},
                                             "capacidades": ["merged"]}}))
    assert "aba Preparar" in M._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])
    sinc(**_com_merged())
    assert M._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}]) == ""
    assert "não é a pasta dos proxies" in M._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}], proxies="/nao/existe")


def test_o_painel_que_fecha_no_meio_diz_o_que_falta(sinc):
    sinc(**_com_merged(**{"/api/v1/merge": (412, {"error": "painel"})}))
    r = M.criar_merged(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])
    assert "aba Preparar" in r["falta"] and r["diarias"][0]["takes_sincronizados"] == 2


def test_importacao_que_falha_traz_o_motivo_do_painel(sinc):
    sinc(**_com_merged(**{"/api/v1/montagem": {"estado": "erro", "resumo": "erro|nenhum projeto aberto"}}))
    r = M.criar_merged(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])
    assert r["erro_da_importacao"] == "erro|nenhum projeto aberto"


def test_premiere_2023_pede_o_arquivo_do_2023(monkeypatch):
    monkeypatch.setattr(M._premiere, "estado", lambda: {"versao": "23.2.0"})
    assert M._alvo_do_premiere() == "2023"
    monkeypatch.setattr(M._premiere, "estado", lambda: {"versao": ""})
    assert M._alvo_do_premiere() == "25"


def test_a_ferramenta_passa_pelo_portao_e_e_so_do_premiere():
    from cicloassist.mcp.registro import FERRAMENTAS
    f = FERRAMENTAS["criar_merged"]
    assert f.escreve and set(f.nles) == {"premiere"} and f.conferir is not None
