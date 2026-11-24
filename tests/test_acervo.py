"""A varredura do acervo — agrupar arquivos OP-Atom em clipes, sem o Media Composer.

⭐ A regra que estes testes travam: **o clipe é o `material_package_umid`, não o nome do
arquivo.** O Avid grava uma track por arquivo, com nome ilegível; listar arquivos daria
três linhas para o que o editor chama de um clipe só. Confirmado no banco
(`protocolos/mxf/README.md`) e medido aqui em 2026-09-11 sobre 1.747 arquivos = 358
clipes.
"""

from __future__ import annotations

import json

from cicloassist.midia import acervo as A
from cicloassist.midia import cache as C

UMID_V = "0x060A2B340101010101010F0013000000C6D91F0BB8ABB1C7ABEE2FFBA70D1E05"
UMID_A = "0x060A2B340101010101010F0013000000E56E1D13D305BE564AEC678A24E90A70"


def escrever(pasta, nome, conteudo=b"x" * 10):
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / nome
    alvo.write_bytes(conteudo)
    return alvo


# ── o que entra na varredura ─────────────────────────────────────────────────

def test_applesdouble_ficam_de_fora(tmp_path):
    """⭐ MEDIDO: **343 de 1.747** arquivos desta máquina são `._*` de 4 KB, a sombra que o
    macOS deixa ao copiar. Cada um custava um ffprobe que falhava — um quinto da varredura
    gasto em nada."""
    escrever(tmp_path, "bom.mxf")
    escrever(tmp_path, "._bom.mxf")
    escrever(tmp_path, "outro.MXF")
    escrever(tmp_path, "naoemxf.txt")

    nomes = sorted(p.name for p in A.arquivos_de(tmp_path))
    assert nomes == ["bom.mxf", "outro.MXF"]


def test_varredura_desce_nas_subpastas(tmp_path):
    """`Avid MediaFiles/MXF/<n>/` — a mídia nunca está na pasta de cima."""
    escrever(tmp_path / "MXF" / "1", "a.mxf")
    escrever(tmp_path / "MXF" / "2", "b.mxf")
    assert len(A.arquivos_de(tmp_path)) == 2


# ── o agrupamento ────────────────────────────────────────────────────────────

def test_tracks_do_mesmo_umid_viram_UM_clipe(tmp_path, monkeypatch):
    """⭐⭐ O ponto do módulo: três arquivos de nome ilegível, um clipe com nome de bin."""
    v = escrever(tmp_path, "XIZBLA_V1.mxf")
    a1 = escrever(tmp_path, "XIZBLA_A01.mxf")
    a2 = escrever(tmp_path, "XIZBLA_A02.mxf")
    sondas = {
        v: {"chave": C.de_umid(UMID_V), "nome": "A001_C003", "tipos": {"video": 1}},
        a1: {"chave": C.de_umid(UMID_V), "nome": "A001_C003", "tipos": {"audio": 1}},
        a2: {"chave": C.de_umid(UMID_V), "nome": "A001_C003", "tipos": {"audio": 1}},
    }
    monkeypatch.setattr(A, "_sondar", lambda arq: sondas.get(arq))

    (clipe,) = A.varrer(tmp_path, sondagem=A.Sondagem(tmp_path / "cache"))
    assert clipe.nome == "A001_C003"
    assert len(clipe.arquivos) == 3
    assert clipe.tracks == {"video": 1, "audio": 2}
    assert clipe.tem_imagem and clipe.tem_som


def test_umids_diferentes_sao_clipes_diferentes(tmp_path, monkeypatch):
    a = escrever(tmp_path, "a.mxf")
    b = escrever(tmp_path, "b.mxf")
    sondas = {
        a: {"chave": C.de_umid(UMID_V), "nome": "imagem", "tipos": {"video": 1}},
        b: {"chave": C.de_umid(UMID_A), "nome": "som", "tipos": {"audio": 2}},
    }
    monkeypatch.setattr(A, "_sondar", lambda arq: sondas.get(arq))

    clipes = A.varrer(tmp_path, sondagem=A.Sondagem(tmp_path / "cache"))
    assert len(clipes) == 2
    assert {c.nome for c in clipes} == {"imagem", "som"}


def test_arquivo_que_nao_e_opatom_e_ignorado(tmp_path, monkeypatch):
    """`.mxf` de câmera, ou de outro fluxo: sem MasterMob não há chave, e sem chave não há
    cache que case."""
    escrever(tmp_path, "camera.mxf")
    monkeypatch.setattr(A, "_sondar", lambda arq: None)
    assert A.varrer(tmp_path, sondagem=A.Sondagem(tmp_path / "cache")) == []


def test_parar_devolve_o_parcial(tmp_path, monkeypatch):
    """⭐ Quem cancela está com pressa, não arrependido: o que já foi agrupado volta, e a
    sondagem fica gravada para a próxima começar de onde esta parou."""
    import threading

    for i in range(5):
        escrever(tmp_path, f"{i}.mxf")
    parar = threading.Event()
    vistos = []

    def sonda(arq):
        vistos.append(arq)
        if len(vistos) == 2:
            parar.set()
        return {"chave": C.de_umid(UMID_V), "nome": "x", "tipos": {"video": 1}}

    monkeypatch.setattr(A, "_sondar", sonda)
    clipes = A.varrer(tmp_path, parar=parar, sondagem=A.Sondagem(tmp_path / "cache"))

    assert len(vistos) == 2
    assert len(clipes) == 1 and len(clipes[0].arquivos) == 2


# ── a sondagem que evita o segundo ffprobe ───────────────────────────────────

def test_segunda_varredura_nao_sonda_de_novo(tmp_path, monkeypatch):
    """⭐ MEDIDO: 58 s na primeira passada, 10 s na segunda, no mesmo acervo de 1.747
    arquivos. É o que torna a aba utilizável."""
    escrever(tmp_path, "a.mxf")
    quantas = []

    def sonda(arq):
        quantas.append(arq)
        return {"chave": C.de_umid(UMID_V), "nome": "x", "tipos": {"video": 1}}

    monkeypatch.setattr(A, "_sondar", sonda)
    raiz = tmp_path / "cache"
    A.varrer(tmp_path, sondagem=A.Sondagem(raiz))
    A.varrer(tmp_path, sondagem=A.Sondagem(raiz))
    assert len(quantas) == 1


def test_arquivo_trocado_e_sondado_de_novo(tmp_path, monkeypatch):
    """⚠️ Invalidada por tamanho + data: um arquivo reescrito no lugar do outro não pode
    passar por aquele que estava lá."""
    alvo = escrever(tmp_path, "a.mxf")
    quantas = []

    def sonda(arq):
        quantas.append(arq)
        return {"chave": C.de_umid(UMID_V), "nome": "x", "tipos": {"video": 1}}

    monkeypatch.setattr(A, "_sondar", sonda)
    raiz = tmp_path / "cache"
    A.varrer(tmp_path, sondagem=A.Sondagem(raiz))

    alvo.write_bytes(b"y" * 999)
    A.varrer(tmp_path, sondagem=A.Sondagem(raiz))
    assert len(quantas) == 2


def test_sondagem_corrompida_nao_derruba(tmp_path):
    raiz = tmp_path / "cache"
    raiz.mkdir()
    (raiz / "sondagem.json").write_text("{isso não é json", encoding="utf-8")
    assert A.Sondagem(raiz).de(tmp_path / "a.mxf") is None


# ── o resultado guardado ─────────────────────────────────────────────────────

def test_guardar_e_ler_por_pasta(tmp_path):
    clipe = A.Clipe(C.de_umid(UMID_V), "A001_C003", ["a.mxf"], {"video": 1}, bytes=100)
    A.guardar("D:/um", [clipe], raiz=tmp_path)

    lido = A.ler(raiz=tmp_path)
    assert lido["pastas"]["D:/um"]["clipes"] == 1
    assert lido["clipes"][clipe.chave]["nome"] == "A001_C003"


def test_varrer_outra_pasta_nao_apaga_a_primeira(tmp_path):
    A.guardar("D:/um", [A.Clipe(C.de_umid(UMID_V), "um", ["a.mxf"], {"video": 1}, bytes=1)],
              raiz=tmp_path)
    A.guardar("D:/dois", [A.Clipe(C.de_umid(UMID_A), "dois", ["b.mxf"], {"audio": 1}, bytes=2)],
              raiz=tmp_path)

    lido = A.ler(raiz=tmp_path)
    assert set(lido["pastas"]) == {"D:/um", "D:/dois"}
    assert len(lido["clipes"]) == 2


def test_mesma_midia_em_duas_pastas_soma_os_arquivos(tmp_path):
    """⚠️ Uma cópia, um consolidate: o mesmo master em duas pastas varridas. A segunda
    ocorrência SOMA — senão a tela diria três tracks onde há seis."""
    chave = C.de_umid(UMID_V)
    A.guardar("D:/um", [A.Clipe(chave, "x", ["a.mxf"], {"video": 1}, por_tipo={"video": ["a.mxf"]}, bytes=10)], raiz=tmp_path)
    A.guardar("E:/dois", [A.Clipe(chave, "x", ["b.mxf"], {"video": 1}, por_tipo={"video": ["b.mxf"]}, bytes=10)], raiz=tmp_path)

    clipe = A.ler(raiz=tmp_path)["clipes"][chave]
    assert len(clipe["arquivos"]) == 2
    assert clipe["tracks"]["video"] == 2
    assert clipe["bytes"] == 20


def test_acervo_corrompido_vira_vazio(tmp_path):
    (tmp_path / "acervo.json").write_text("[]", encoding="utf-8")
    assert A.ler(raiz=tmp_path) == {"pastas": {}, "clipes": {}}


# ── a chave, que é a mesma do cache ──────────────────────────────────────────

def test_o_umid_do_ffprobe_e_a_chave_do_cache():
    """⭐⭐ É isto que faz a varredura CRUZAR com o que a conversa já processou, em vez de
    ser uma segunda lista. O `ffprobe` escreve `0x060A2B34…`; o Avid, `urn:smpte:umid:…`
    com pontos. Medido: as 15 mídias do cache desta máquina foram todas reencontradas na
    varredura."""
    do_ffprobe = C.de_umid(UMID_V)
    do_avid = C.de_umid(
        "urn:smpte:umid:060a2b34.01010101.01010f00.13000000."
        "c6d91f0b.b8abb1c7.abee2ffb.a70d1e05"
    )
    assert do_ffprobe == do_avid


def test_varredura_grava_json_legivel(tmp_path):
    """A pasta é do editor: o que a gente escreve nela tem de abrir num editor de texto."""
    A.guardar("D:/um", [A.Clipe(C.de_umid(UMID_V), "acentuação", [], {}, bytes=0)],
              raiz=tmp_path)
    bruto = (tmp_path / "acervo.json").read_text(encoding="utf-8")
    assert "acentuação" in bruto
    assert json.loads(bruto)


def test_pastas_ocultas_nao_entram_na_varredura(tmp_path):
    """⛔ MEDIDO num disco do editor (2026-09-14): `Avid MediaFiles/.sync/Archive/` tinha 955
    `.mxf` do Resilio Sync com o MESMO UMID dos originais — tracks em dobro no clipe."""
    (tmp_path / "MXF" / "1").mkdir(parents=True)
    (tmp_path / "MXF" / "1" / "A.mxf").write_bytes(b"x")
    (tmp_path / ".sync" / "Archive").mkdir(parents=True)
    (tmp_path / ".sync" / "Archive" / "A.mxf").write_bytes(b"x")
    assert [p.name for p in A.arquivos_de(tmp_path)] == ["A.mxf"]
    assert ".sync" not in str(A.arquivos_de(tmp_path)[0])


def test_avid_mediafiles_mora_DENTRO_de_cada_volume(tmp_path):
    """⛔ No Mac, `/Volumes` é a pasta dos volumes: procurar `/Volumes/Avid MediaFiles`
    nunca achava nada. As raízes são os volumes, e o mesmo disco por dois caminhos (o
    `/Volumes/Macintosh HD` que aponta para `/`) entra uma vez só."""
    import os

    import pytest

    disco = tmp_path / "RAID"
    (disco / "Avid MediaFiles").mkdir(parents=True)
    (tmp_path / "vazio").mkdir()
    atalho = tmp_path / "atalho"
    try:
        os.symlink(disco, atalho)
    except (OSError, NotImplementedError):
        pytest.skip("sem permissão de criar atalho nesta máquina")
    achadas = A.pastas_de_midia([disco, tmp_path / "vazio", atalho])
    assert achadas == [disco / "Avid MediaFiles"]
