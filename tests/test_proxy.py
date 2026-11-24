"""`converter_para_proxy` — a P1 da diária no Premiere (sem Resolve: tamanhos, grupos, destino, o par)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cicloassist import resolve_proxy as P
from cicloassist.mcp import registro
from cicloassist.mcp.ferramentas import proxy as F

BASE = {"taxa": "24000/1001", "largura": 1920, "altura": 1080, "quadros": 312, "tc": "00:20:50:00",
        "codec": "prores", "perfil": "Proxy", "canais": 2}


def sonda(**muda):
    return {**BASE, **muda}


@pytest.mark.parametrize("w,h,esperado", [(1920, 1080, (1920, 1080)), (3840, 2160, (1920, 1080)),
                                          (4096, 2160, (2048, 1080)), (4128, 2176, (2048, 1080)),
                                          (1280, 720, (1920, 1080)), (6144, 2592, (2560, 1080))])
def test_proxy_e_1080_na_proporcao_do_original(w, h, esperado):
    assert P.tamanho_do_proxy(w, h) == esperado


def test_grupos_por_proporcao_numa_taxa_so():
    vs = [Path("a.mov"), Path("b.braw"), Path("c.mov")]
    sondas = {vs[0]: sonda(), vs[1]: sonda(largura=4096, altura=2160), vs[2]: sonda(largura=3840, altura=2160)}
    motivo, plano = P.conferir_videos(vs, sondas)
    assert motivo == ""
    assert plano["taxa"] == "23.976"
    assert [(g["largura"], [v.name for v in g["videos"]]) for g in plano["grupos"]] == [
        (1920, ["a.mov", "c.mov"]), (2048, ["b.braw"])]


def test_mistura_de_taxas_e_recusada():
    vs = [Path("a.mov"), Path("b.mov")]
    motivo, _ = P.conferir_videos(vs, {vs[0]: sonda(), vs[1]: sonda(taxa="25/1")})
    assert "misturam taxas" in motivo


def test_dois_clipes_com_o_mesmo_nome_sao_recusados():
    """O proxy é <nome>.mov: dois A001_C003 de cartões diferentes escreveriam um por cima do outro."""
    vs = [Path("CAM A/A001_C003.mov"), Path("CAM B/A001_C003.mp4")]
    motivo, _ = P.conferir_videos(vs, {v: sonda() for v in vs})
    assert "mesmo nome" in motivo


def test_destino_nunca_por_cima_e_nunca_ao_lado_do_original(tmp_path):
    orig = tmp_path / "CAM A"; orig.mkdir(); v = orig / "A001.mov"; v.write_bytes(b"")
    assert P.conferir_destino(tmp_path / "nova", [v]) == ""               # ainda não existe: ok
    assert "próprios originais" in P.conferir_destino(orig, [v])
    (tmp_path / "px").mkdir(); (tmp_path / "px" / "A001.mov").write_bytes(b"")
    assert "já há proxy" in P.conferir_destino(tmp_path / "px", [v])


def test_o_par_certo_passa_mesmo_com_o_estereo_virando_dois_mono():
    """Medido na P0: o estéreo sai em 2 pistas mono; o Premiere aceita. Conta-se o TOTAL de canais."""
    assert P.conferir_par(sonda(), sonda()) == []


@pytest.mark.parametrize("muda,pega", [
    ({"canais": 4}, "canais"), ({"quadros": 192}, "quadros"), ({"tc": "02:00:00:00"}, "TC"),
    ({"taxa": "25/1"}, "taxa"), ({"largura": 2048}, "esperado"), ({"perfil": "HQ"}, "ProRes Proxy"),
])
def test_o_que_o_premiere_aceitaria_calado_e_pego_aqui(muda, pega):
    """⛔ P0.2: o attachProxy aceita outra duração, outro TC e outra proporção sem reclamar."""
    original = sonda(codec="h264", perfil="High", canais=muda.get("canais_orig", 2))
    proxy = sonda(**muda)
    assert any(pega in p for p in P.conferir_par(original, proxy))


def test_conferir_saida_diz_o_que_nao_caiu(tmp_path, monkeypatch):
    v1, v2 = Path("/x/A.mov"), Path("/x/B.mov")
    (tmp_path / "A.mov").write_bytes(b"")
    monkeypatch.setattr(P, "sondar", lambda p: sonda())
    r = P.conferir_saida(tmp_path, [v1, v2], {v1: sonda(codec="h264"), v2: sonda()})
    assert r["proxies"] == 1
    assert "não caiu" in r["problemas"][0]


def test_converter_manda_um_grupo_por_proporcao_em_mov(tmp_path, monkeypatch):
    vs = [Path("/x/a.mov"), Path("/x/b.braw")]
    sondas = {vs[0]: sonda(), vs[1]: sonda(largura=4096, altura=2160)}
    monkeypatch.setattr(P, "sondar", lambda p: sondas.get(p) or sonda())
    visto = {}

    def rodar(pedido, relatar):
        visto.update(pedido)
        return {"status": "Complete", "segundos": 3.0, "grupos": [{"timeline": g["timeline"]} for g in pedido["grupos"]]}
    monkeypatch.setattr(P._op, "_rodar", rodar)
    monkeypatch.setattr(P, "conferir_saida", lambda d, v, s: {"pares": [], "problemas": [], "proxies": 2})
    r = P.converter("PRJ", vs, tmp_path / "px")
    assert visto["formato_saida"] == "mov" and visto["codec"] == "ProRes422P"
    assert visto["preset"] == P._op.PRESET          # ⛔ pelo preset, nunca só pela API (P0.1)
    assert [(g["largura"], g["altura"]) for g in visto["grupos"]] == [(1920, 1080), (2048, 1080)]
    assert r["grupos"] == [{"tamanho": "1920x1080", "clipes": 1}, {"tamanho": "2048x1080", "clipes": 1}]


def test_ferramenta_escreve_e_pede_o_destino(tmp_path, monkeypatch):
    f = registro.FERRAMENTAS["converter_para_proxy"]
    assert f.escreve and "premiere" in f.nles
    monkeypatch.setattr(F._arrastados, "autorizado", lambda p: True)
    assert "destino" in F._conferir(projeto="P", pasta=str(tmp_path), destino="")
    assert "caminho inteiro" in F._conferir(projeto="P", pasta=str(tmp_path), destino="px")


def test_ferramenta_recusa_pasta_nao_arrastada(tmp_path, monkeypatch):
    monkeypatch.setattr(F._arrastados, "autorizado", lambda p: False)
    monkeypatch.setattr(F._lab, "na_saida", lambda p: False)
    assert F._conferir(projeto="P", pasta=str(tmp_path), destino=str(tmp_path / "px"))
