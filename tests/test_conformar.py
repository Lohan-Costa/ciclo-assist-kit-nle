"""`conformar_no_resolve`: o De Lá Pra Cá como ferramenta do chat (autor, 2026-10-29)."""

from __future__ import annotations

import pytest

from cicloassist import delapraca as D
from cicloassist.mcp.ferramentas import conformar as F
from cicloassist.servico import arrastados as A


@pytest.fixture(autouse=True)
def _limpo():
    A.esquecer_tudo()
    yield
    A.esquecer_tudo()


@pytest.fixture
def material(tmp_path):
    """O que o editor arrasta: o projeto, a referência e a pasta das mídias."""
    proj = tmp_path / "WSP-DLPC_2.prproj"
    ref = tmp_path / "PRODC_Trailer_v02.mov"
    midia = tmp_path / "MIDIA"
    proj.write_bytes(b"x")
    ref.write_bytes(b"x")
    midia.mkdir()
    for c in (proj, ref, midia):
        A.autorizar(c)
    return {"proj": str(proj), "ref": str(ref), "midia": str(midia)}


def test_cada_arrasto_no_seu_papel(material, tmp_path):
    outro = tmp_path / "roteiro.docx"
    outro.write_bytes(b"x")
    p = F.separar_os_arrastos([material["ref"], material["midia"], material["proj"], str(outro)])
    assert p == {"timeline": [material["proj"]], "referencia": [material["ref"]],
                 "pastas": [material["midia"]], "outros": [str(outro)]}


def test_sem_nome_vai_a_sequencia_de_mais_planos():
    """⭐ MEDIDO no PRODC: o aninhado `transicao-pesoa` (3 planos) vem ao lado do corte (88)."""
    seqs = [{"nome": "transicao-pesoa", "planos": 3, "mob_id": "a"},
            {"nome": "PRODC_CORTE02", "planos": 88, "mob_id": "b"}]
    assert F._escolher_a_sequencia(seqs, "")[0]["nome"] == "PRODC_CORTE02"
    assert F._escolher_a_sequencia(seqs, "transicao-pesoa")[0]["mob_id"] == "a"
    nada, porque = F._escolher_a_sequencia(seqs, "OUTRA")
    assert nada is None and "PRODC_CORTE02" in porque


def test_sem_timeline_arrastada_nem_mostra_o_cartao(tmp_path):
    ref = tmp_path / "r.mov"
    ref.write_bytes(b"x")
    A.autorizar(ref)
    assert "arquivo da timeline" in F._conferir()


def test_caminho_que_nao_foi_arrastado_e_recusado(material):
    assert F._conferir(projeto=r"C:\outro\lugar.prproj")


def test_sem_resolve_a_recusa_e_a_frase_do_dlpc(material, monkeypatch):
    monkeypatch.setattr(D, "saude", lambda: {"ok": True})

    def sem_resolve():
        raise D.DelaPracaFalhou("o servidor de scripts do DaVinci Resolve não está no ar")
    monkeypatch.setattr(D, "resolve_aberto", sem_resolve)
    assert "servidor de scripts" in F._conferir()


def test_tudo_de_pe_passa(material, monkeypatch):
    monkeypatch.setattr(D, "saude", lambda: {"ok": True})
    monkeypatch.setattr(D, "resolve_aberto", lambda: "Projeto")
    assert F._conferir() == ""


def test_a_ferramenta_leva_os_arrastos_e_resume(material, monkeypatch):
    pedidos = {}
    monkeypatch.setattr(D, "abrir", lambda c: {
        "chave": "k", "pastas": ["D:/deduzida"],
        "sequencias": [{"nome": "transicao-pesoa", "planos": 3, "mob_id": "a"},
                       {"nome": "PRODC_CORTE02", "planos": 88, "mob_id": "b"}]})

    def conformar(chave, seq, pastas, referencia="", aceitar_escalas=True, relatar=None):
        pedidos.update(chave=chave, seq=seq, pastas=pastas, referencia=referencia)
        return {"analisar": {"planos": 88, "no_original": 88, "arquivos": 48, "faltam": []},
                "preparar": {"avisos": [f"aviso {i}" for i in range(10)], "offline": 0},
                "importar": {"ok": True, "nome": "PRODC_CORTE02"},
                "fusion": {"criadas": 11},
                "conferencia": {"total": 144, "conferem": 144, "nao_conferem": 0},
                "tempos": {"analisar": 5.0}}
    monkeypatch.setattr(D, "conformar", conformar)

    r = F.conformar_no_resolve()
    assert pedidos == {"chave": "k", "seq": "b", "pastas": [material["midia"]],
                       "referencia": material["ref"]}
    assert r["importou"] and r["timeline_no_resolve"] == "PRODC_CORTE02"
    assert r["outras_sequencias_do_projeto"] == ["transicao-pesoa"]
    assert r["conferencia"] == {"pontos": 144, "conferem": 144, "nao_conferem": 0}
    assert len(r["avisos"]) == F.AVISOS_NA_RESPOSTA and r["avisos_a_mais"] == 2
    assert r["no_resolve"]["fusion"] == 11
    # ⭐ a manchete vem PRIMEIRO e é do código: o "144 de 144" rolava para fora da tela
    assert list(r)[0] == "manchete"
    assert r["manchete"] == "144 de 144 pontos conferem · PRODC_CORTE02 no Resolve · 88 planos, nada faltando"


def test_a_manchete_diz_o_que_falhou():
    m = F._manchete({"conferencia": {"erro": "x"}, "importou": False, "planos": 5,
                     "midias": {"faltam": ["a.mov", "b.mov"]}})
    assert m == "a conferência falhou · a timeline NÃO foi importada · 5 planos, 2 mídia(s) faltando"
    assert F._manchete({"conferencia": "sem vídeo", "importou": True, "sequencia": "S"}).startswith(
        "sem conferência")


def test_sem_pasta_arrastada_vale_a_que_o_dlpc_deduziu(tmp_path, monkeypatch):
    proj = tmp_path / "p.prproj"
    proj.write_bytes(b"x")
    A.autorizar(proj)
    visto = {}
    monkeypatch.setattr(D, "abrir", lambda c: {"chave": "k", "pastas": ["D:/deduzida"],
                                               "sequencias": [{"nome": "S", "planos": 1, "mob_id": "m"}]})
    monkeypatch.setattr(D, "conformar", lambda *a, **k: visto.update(pastas=a[2]) or {"importar": {}})
    r = F.conformar_no_resolve()
    assert visto["pastas"] == ["D:/deduzida"]
    assert r["conferencia"] == "sem vídeo de referência, nada foi conferido"


def test_o_preambulo_aponta_a_ferramenta_quando_chega_uma_timeline(material):
    from cicloassist.servico import rotas
    texto = rotas._preambulo_do_arrasto([{"tipo": "arquivo", "caminho": material["proj"]},
                                         {"tipo": "arquivo", "caminho": material["midia"]}], nle="avid")
    assert "conformar_no_resolve" in texto
    assert f"- a pasta {material['midia']}" in texto
    sem = rotas._preambulo_do_arrasto([{"tipo": "arquivo", "caminho": material["ref"]}], nle="avid")
    assert "conformar_no_resolve" not in sem
