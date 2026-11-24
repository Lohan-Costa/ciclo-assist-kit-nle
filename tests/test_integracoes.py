"""O instalador único (fase 4, passo 3): tira as integrações antigas para uma cópia e instala a ponte única."""
import os
import sys

import pytest

from cicloassist import integracoes as I


@pytest.fixture
def maquina(tmp_path, monkeypatch):
    cep, avpi, wip = tmp_path / "cep", tmp_path / "avpi", tmp_path / "wip"
    scripts = [tmp_path / "scripts" / d for d in ("Utility", "Views")]
    for p in (cep, avpi, wip, *scripts):
        p.mkdir(parents=True)
    monkeypatch.setattr(I, "pasta_cep", lambda: cep)
    monkeypatch.setattr(I, "pasta_avpi", lambda: avpi)
    monkeypatch.setattr(I, "pasta_resolve_paineis", lambda: wip)
    monkeypatch.setattr(I, "pastas_resolve_scripts", lambda: scripts)
    for nome in ("com.orbita.ponte", "com.ciclomedia.delapraca.ppro", "com.ciclomedia.cicloassist.ponte",
                 "Chat Video Pro"):
        (cep / nome).mkdir()
        (cep / nome / "index.html").write_text("x", encoding="utf-8")
    (avpi / "com.ciclomedia.delapraca.mc.avpi").write_text("x", encoding="utf-8")
    (avpi / "avid-huddle.avpi").write_text("x", encoding="utf-8")
    (wip / "com.ciclomedia.delapraca").mkdir()
    for s in scripts:
        (s / "orbita_sync.lua").write_text("x", encoding="utf-8")
    return tmp_path


def test_tira_so_o_que_e_nosso_e_guarda_copia(maquina):
    copia = maquina / "copia"
    feitos = I.desinstalar_antigas(copia)
    tirados = sorted(os.path.basename(f["tirado"]) for f in feitos)
    assert tirados == ["com.ciclomedia.delapraca", "com.ciclomedia.delapraca.mc.avpi",
                       "com.ciclomedia.delapraca.ppro", "com.orbita.ponte", "orbita_sync.lua", "orbita_sync.lua"]
    assert (maquina / "cep" / "com.ciclomedia.cicloassist.ponte").is_dir(), "a ponte única fica"
    assert (maquina / "cep" / "Chat Video Pro").is_dir() and (maquina / "avpi" / "avid-huddle.avpi").is_file()
    assert (copia / "premiere" / "com.orbita.ponte" / "index.html").is_file(), "move, nunca apaga"
    assert (copia / "resolve" / "Utility__orbita_sync.lua").is_file() and (copia / "resolve" / "Views__orbita_sync.lua").is_file()
    assert I.desinstalar_antigas(copia) == [], "idempotente"


def test_uma_antiga_presa_nao_derruba_as_outras(maquina, monkeypatch):
    """⛔ Revisão de 2026-11-07: sem permissão para mover uma (o `.avpi` em `/Library` no Mac, `%PROGRAMDATA%` no
    Windows), a exceção derrubava o instalador e a ponte do Premiere nunca era instalada."""
    original = I.shutil.move

    def mover(origem, destino):
        if origem.endswith(".avpi"):
            raise PermissionError(13, "Permission denied", origem)
        return original(origem, destino)

    monkeypatch.setattr(I.shutil, "move", mover)
    feitos = I.desinstalar_antigas(maquina / "copia")
    presas = [f for f in feitos if "falha" in f]
    assert [os.path.basename(f["tirado"]) for f in presas] == ["com.ciclomedia.delapraca.mc.avpi"]
    assert "Permission denied" in presas[0]["falha"]
    assert len(feitos) == 6 and not (maquina / "cep" / "com.orbita.ponte").exists(), "as outras saíram"


@pytest.mark.skipif(sys.platform == "win32", reason="atalho exige privilégio no Windows")
def test_atalho_so_perde_o_atalho(maquina, tmp_path):
    alvo = tmp_path / "de-outro-projeto"
    alvo.mkdir()
    (maquina / "cep" / "com.orbita.sonda").symlink_to(alvo)
    feitos = [f for f in I.desinstalar_antigas(tmp_path / "copia") if f["tirado"].endswith("sonda")]
    assert feitos and feitos[0]["atalho_para"] == str(alvo)
    assert alvo.is_dir() and not (maquina / "cep" / "com.orbita.sonda").exists()


def test_a_ponte_unica_e_copiada_sem_debug(tmp_path):
    destino = I.instalar_ponte(tmp_path)
    assert destino.name == "com.ciclomedia.cicloassist.ponte" and (destino / "CSXS" / "manifest.xml").is_file()
    assert not (destino / ".debug").exists() and not destino.is_symlink()


# ── a seção Integrações da janela de configurações (2026-11-07) ──────────────────────────────────────────────────

def test_a_situacao_da_ponte_compara_o_conteudo(tmp_path):
    assert I.situacao_da_ponte(tmp_path) == "ausente"
    destino = I.instalar_ponte(tmp_path)
    assert I.situacao_da_ponte(tmp_path) == "instalada"
    (destino / "._index.html").write_text("sombra do exFAT", encoding="utf-8")
    assert I.situacao_da_ponte(tmp_path) == "instalada", "a sombra `._` não é diferença"
    (destino / "index.html").write_text("de outra versão", encoding="utf-8")
    assert I.situacao_da_ponte(tmp_path) == "desatualizada"


def test_o_estado_lista_as_antigas_e_a_ponte(maquina, monkeypatch):
    monkeypatch.setattr(I, "modo_depuracao_ligado", lambda: True)
    e = I.estado()
    assert e["ponte"]["situacao"] == "desatualizada", "a ponte do `maquina` tem outro conteúdo"
    assert e["ponte"]["modo_depuracao"] is True
    assert {a["nle"] for a in e["antigas"]} == {"premiere", "media_composer", "resolve"}


def test_as_rotas_das_integracoes(maquina, monkeypatch, tmp_path):
    import json

    from cicloassist.servico import rotas as R
    from cicloassist.servico.http import ROTAS, Pedido

    monkeypatch.setattr(I, "modo_depuracao_ligado", lambda: True)
    monkeypatch.setattr(I, "ligar_modo_depuracao", lambda: [])
    assert ROTAS[("GET", "/integracoes")][1] is False, "a página é navegação de topo"
    assert ROTAS[("POST", "/integracoes/instalar")][1] and ROTAS[("POST", "/integracoes/tirar-antigas")][1], \
        "quem AGE passa pelo porteiro"
    assert b"Integra" in R.rota_integracoes_pagina(Pedido("GET", "/integracoes", {}, b"")).corpo

    r = json.loads(R.rota_integracoes_instalar(Pedido("POST", "/integracoes/instalar", {}, b"{}")).corpo)
    assert r["ok"] and r["estado"]["ponte"]["situacao"] == "instalada"

    r = json.loads(R.rota_integracoes_tirar_antigas(Pedido("POST", "/integracoes/tirar-antigas", {}, b"{}")).corpo)
    assert r["ok"] and len(r["tirados"]) == 6 and r["estado"]["antigas"] == []
    assert r["copia"].startswith(str(tmp_path)), "a cópia vai para a pasta de dados (a do teste)"
