"""`importar_no_premiere` — a P2 da diária no Premiere (sem Premiere: o plano, o par, o texto, a ferramenta)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cicloassist.mcp import registro
from cicloassist.mcp.ferramentas import diaria_premiere as F
from cicloassist.nle.premiere import diaria as D

BOA = {"taxa": "24000/1001", "largura": 1920, "altura": 1080, "quadros": 312, "tc": "00:20:50:00",
       "codec": "prores", "perfil": "Proxy", "canais": 2}


@pytest.fixture
def diaria(tmp_path):
    for f in ["D01/CAM A/A001.mov", "D01/CAM A/A002.mov", "D01/SOM/T01.WAV", "D01/_lixo/x.mov",
              "px/A001.mov", "px/A002.mov"]:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"")
    return tmp_path


def test_anexado_confere_o_par_e_quem_nao_confere_entra_sem_proxy(diaria):
    sondas = {"A001": BOA, "A002": {**BOA, "quadros": 99}}
    plano = D.planejar("proxy_anexado", diaria / "D01", diaria / "px", "D01",
                       sondar=lambda p: sondas.get(p.stem) if p.parent.name == "px" else BOA)
    por = {Path(i["arquivo"]).name: i for i in plano["itens"]}
    assert Path(por["A001.mov"]["proxy"]).as_posix().endswith("px/A001.mov") and por["A001.mov"]["bin"] == "D01/CAM A"
    assert por["A002.mov"]["proxy"] == ""                       # ⛔ o par não conferiu: sem proxy
    assert "quadros" in plano["sem_proxy"][0]["motivo"]
    assert por["T01.WAV"] == {"arquivo": str(diaria / "D01/SOM/T01.WAV"), "bin": "D01/SOM", "proxy": "", "tipo": "som"}
    assert "x.mov" not in por                                   # pasta de trabalho fica de fora


def test_original_importa_o_proxy_como_midia_na_bin_do_original(diaria):
    plano = D.planejar("original", diaria / "D01", diaria / "px", "D01", sondar=lambda p: BOA)
    v = [i for i in plano["itens"] if i["tipo"] == "video"]
    assert {Path(i["arquivo"]).parent.name for i in v} == {"px"} and {i["bin"] for i in v} == {"D01/CAM A"}
    assert all(i["proxy"] == "" for i in plano["itens"])


def test_original_sem_proxy_e_problema(diaria):
    (diaria / "px/A002.mov").unlink()
    plano = D.planejar("original", diaria / "D01", diaria / "px", "D01", sondar=lambda p: BOA)
    assert "A002.mov" in plano["problemas"][0]


def test_modo_inventado_e_recusado(diaria):
    assert D.planejar("os dois", diaria / "D01", diaria / "px", "D01")["problemas"]


def test_texto_do_plano_agrupa_por_bin_e_nao_aceita_tab():
    itens = [{"arquivo": "/a/1.mov", "bin": "D/A", "proxy": "/p/1.mov", "tipo": "video"},
             {"arquivo": "/a/2.wav", "bin": "D/S", "proxy": "", "tipo": "som"}]
    assert D.texto_do_plano(itens) == "bin\tD/A\narq\t/a/1.mov\t/p/1.mov\nbin\tD/S\narq\t/a/2.wav\t"
    with pytest.raises(ValueError):
        D.texto_do_plano([{"arquivo": "/a/1\t.mov", "bin": "D", "proxy": "", "tipo": "video"}])


def test_importar_resume_o_que_o_premiere_disse(monkeypatch):
    feitos = [{"arquivo": "/a/1.mov", "bin": "D/A", "proxy_pedido": "/p/1.mov", "anexou": True},
              {"arquivo": "/a/2.mov", "bin": "D/A", "proxy_pedido": "/p/2.mov", "anexou": False, "erro": "recusou"},
              {"arquivo": "/a/3.wav", "bin": "D/S", "ja_estava": True}]
    monkeypatch.setattr(D.ponte, "chamar", lambda f, t, prazo=0: {"feitos": feitos})
    r = D.importar({"itens": [{"arquivo": "/a/1.mov", "bin": "D/A", "proxy": "/p/1.mov", "tipo": "video"}]})
    assert (r["importados"], r["ja_estavam"], r["com_proxy"], r["proxy_pedidos"]) == (1, 1, 1, 2)
    assert r["falharam"] == [{"arquivo": "2.mov", "erro": "recusou"}]


def test_ferramenta_e_do_premiere_escreve_e_manda_perguntar_o_modo(diaria, monkeypatch):
    f = registro.FERRAMENTAS["importar_no_premiere"]
    assert f.escreve and f.nles == ("premiere",)
    assert "Pergunte" in F._conferir(modo="", diaria=str(diaria / "D01"), proxies=str(diaria / "px"))
    monkeypatch.setattr(F._arrastados, "autorizado", lambda p: False)
    monkeypatch.setattr(F._lab, "na_saida", lambda p: False)
    assert F._conferir(modo="original", diaria=str(diaria / "D01"), proxies=str(diaria / "px"))


def test_o_host_jsx_tem_a_funcao_e_nao_monta_codigo():
    jsx = Path(D.__file__).with_name("host.jsx").read_text(encoding="utf-8")
    assert "function cicloImportar(plano)" in jsx and "attachProxy(prox, 0)" in jsx


def test_a_arvore_da_ponte_traz_o_arquivo_como_a_do_mcp():
    """⛔ Sem o `arquivo`, o sincronizar juntava ZERO arquivos no 2025/2026 (achado na P3,
    2026-11-07: "o Sincronizar não reconheceu nenhuma fonte")."""
    jsx = Path(D.__file__).with_name("host.jsx").read_text(encoding="utf-8")
    corpo = jsx[jsx.index("function cicloArvore()"):]
    corpo = corpo[:corpo.index("\n}")]
    assert "cicloResumo(it, caminho, null)" in corpo


def test_sincronizar_junta_os_arquivos_das_sub_bins(monkeypatch):
    from cicloassist.mcp.ferramentas import sincronizar as FO
    monkeypatch.setattr(FO._premiere, "arvore", lambda: [
        {"nome": "CAM B", "especie": "bin", "bin": "D01"},
        {"nome": "a.mov", "especie": "clipe", "bin": "D01/CAM B", "arquivo": "/m/a.mov"},
        {"nome": "t.WAV", "especie": "clipe", "bin": "D01/SOM", "arquivo": "/m/t.WAV"},
        {"nome": "x.mov", "especie": "clipe", "bin": "OUTRA", "arquivo": "/m/x.mov"}])
    assert FO._arquivos_da_bin("D01") == ["/m/a.mov", "/m/t.WAV"]


def test_sincronizar_deixa_o_offline_de_fora_e_diz(monkeypatch, tmp_path):
    """⛔ P6 (2026-11-07): 12 itens offline na bin derrubavam o sync inteiro com "arquivo não encontrado"."""
    from cicloassist.mcp.ferramentas import sincronizar as FO
    bom = tmp_path / "A001.mov"; bom.write_bytes(b"")
    monkeypatch.setattr(FO, "_no_avid", lambda: False)
    monkeypatch.setattr(FO._premiere, "arvore", lambda: [
        {"nome": "A001.mov", "especie": "clipe", "bin": "D", "arquivo": str(bom)},
        {"nome": "SUMIU.mov", "especie": "clipe", "bin": "D", "arquivo": str(tmp_path / "SUMIU.mov")}])
    fontes = [{"tipo": "camera", "bins": ["D"]}, {"tipo": "som", "arquivos": [str(tmp_path / "S.wav")]}]
    (tmp_path / "S.wav").write_bytes(b"")
    achado = FO.fontes_do_pedido(fontes)
    assert achado["fontes"][0]["files"] == [str(bom)] and len(achado["offline"]) == 1
    monkeypatch.setattr(FO._premiere, "arvore", lambda: [
        {"nome": "SUMIU.mov", "especie": "clipe", "bin": "D", "arquivo": str(tmp_path / "SUMIU.mov")}])
    assert "OFFLINE" in FO.sincronizar(fontes=[{"tipo": "camera", "bins": ["D"]}])["erro"]
