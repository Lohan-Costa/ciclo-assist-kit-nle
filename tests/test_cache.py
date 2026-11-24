"""O cache de mídia — a regra da chave, e as tolerâncias que impedem o pior.

⭐ A regra que estes testes travam, herdada de um módulo que rodou em produção: **o cache
é endereçado pelo UMID do MASTER, não do subclipe.** Processou uma vez, e qualquer clipe
que use aquele material acha pronto — masterclipe, subclipe, groupclipe (multicam), e
subclipe criado DEPOIS.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import frames as F

MASTER = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.64cedc20.1dc80000.060e2b34.7f7f2a80"
SUBCLIPE = "urn:smpte:umid:060a2b34.01010105.01010f20.13000000.f3e412f7.7de745ca.8c35f58a.b55d78f6"


# ── a chave ──────────────────────────────────────────────────────────────────

def test_umid_vira_64_hex():
    chave = C.de_umid(MASTER)
    assert len(chave) == 64
    assert chave.startswith("060a2b340101010501010d43")


def test_master_e_subclipe_dao_chaves_diferentes():
    """⭐ O ponto do módulo. Se as duas coincidissem, o cache seria por recorte e cada
    subclipe reprocessaria a mesma mídia."""
    assert C.de_umid(MASTER) != C.de_umid(SUBCLIPE)


def test_chave_e_sempre_minuscula():
    """⚠️ Sem isto o mesmo material ganha dois diretórios, e o cache PARECERIA funcionar
    enquanto nunca acertasse — falha sem erro, só lentidão que ninguém explica."""
    assert C.de_umid(MASTER.upper()) == C.de_umid(MASTER)


def test_umid_torto_e_recusado_antes_de_virar_caminho():
    """⛔ A chave vira NOME DE DIRETÓRIO, e o `.avb` traz strings que não escolhemos."""
    for ruim in ("", "urn:smpte:umid:../../etc/passwd", "060a2b34", "z" * 64, None, 42):
        with pytest.raises(C.ChaveInvalida):
            C.de_umid(ruim)  # type: ignore[arg-type]


def test_prefixo_sai_antes_do_filtro_de_hex():
    """⚠️ O `e` de `smpte` e o `d` de `umid` são hexadecimais válidos. Filtrar antes de
    tirar o prefixo daria 66 dígitos — irmão de um erro que a família `remap.py` já pagou
    e que está registrado no banco."""
    assert len(C.de_umid(MASTER)) == 64


# ── o armazenamento ──────────────────────────────────────────────────────────

def test_quadro_e_nomeado_pela_posicao_no_master(tmp_path):
    """⭐ É esta escolha que faz dois subclipes vizinhos compartilharem a sobreposição."""
    m = C.Midia(MASTER, tmp_path)
    assert m.caminho_do_quadro(1357).name == "00001357.jpg"


def test_guarda_e_acha(tmp_path):
    m = C.Midia(MASTER, tmp_path)
    assert not m.tem_quadro(100)
    m.guardar_quadro(100, b"jpeg-falso")
    assert m.tem_quadro(100)
    assert m.quadros_guardados() == [100]


def test_quadro_de_tamanho_zero_nao_conta_como_presente(tmp_path):
    """Resto de uma extração que morreu no meio. Tratá-lo como presente entregaria uma
    imagem vazia ao modelo, que a descreveria como pôde."""
    m = C.Midia(MASTER, tmp_path)
    m.guardar_quadro(7, b"")
    assert not m.tem_quadro(7)


def test_dois_masters_nao_colidem(tmp_path):
    a = C.Midia(MASTER, tmp_path)
    b = C.Midia(SUBCLIPE, tmp_path)
    a.guardar_quadro(1, b"a")
    b.guardar_quadro(1, b"b")
    assert a.caminho_do_quadro(1).read_bytes() == b"a"
    assert b.caminho_do_quadro(1).read_bytes() == b"b"


def test_json_corrompido_vira_cache_vazio_e_nao_excecao(tmp_path):
    """⚠️ Cache corrompido não pode derrubar o produto. Reprocessar custa segundos;
    estourar custa a conversa do editor."""
    m = C.Midia(MASTER, tmp_path)
    m.anotar_fonte({"master": "X"})
    m.arquivo("midia.json").write_text("{isto não é json", encoding="utf-8")
    assert m.ler_fonte() == {}


def test_fonte_acumula_em_vez_de_substituir(tmp_path):
    m = C.Midia(MASTER, tmp_path)
    m.anotar_fonte({"master": "X"})
    m.anotar_fonte({"fps": {"num": 24000, "den": 1001}})
    assert m.ler_fonte()["master"] == "X"


# ── a assinatura do gerador ──────────────────────────────────────────────────

def test_assinatura_nova_pede_refazer(tmp_path):
    """⭐ É o que permite melhorar o produto sem invalidar tudo à mão: mudou a largura do
    quadro, o que está guardado deixa de servir sozinho."""
    m = C.Midia(MASTER, tmp_path)
    assert m.precisa_refazer("quadros", {"largura": 768})
    m.registrar_gerador("quadros", {"largura": 768})
    assert not m.precisa_refazer("quadros", {"largura": 768})
    assert m.precisa_refazer("quadros", {"largura": 1024})


def test_limpar_estagio_joga_os_quadros_fora(tmp_path):
    m = C.Midia(MASTER, tmp_path)
    m.guardar_quadro(1, b"x")
    m.limpar_estagio("quadros")
    assert m.quadros_guardados() == []


# ── escrita atômica ──────────────────────────────────────────────────────────

def test_escrita_nao_deixa_temporario_para_tras(tmp_path):
    alvo = tmp_path / "sub" / "a.json"
    C.escrever_atomico(alvo, json.dumps({"a": 1}).encode())
    assert alvo.is_file()
    assert not list(tmp_path.rglob("*.tmp"))


# ── a amostragem de quadros ──────────────────────────────────────────────────

def test_nao_amostra_as_pontas():
    """⚠️ O primeiro quadro de um take costuma ser claquete ou resto do plano anterior, e
    o último pega o corte. Amostrar as pontas faz o modelo descrever o que o take NÃO é —
    com confiança, porque a imagem é real."""
    p = F.distribuir(0, 100, 3)
    assert p == [25, 50, 75]
    assert 0 not in p and 100 not in p


def test_um_quadro_so_vem_do_meio():
    assert F.distribuir(0, 100, 1) == [50]


def test_amostragem_respeita_o_inicio_no_master():
    """O intervalo é contado a partir de onde a IMAGEM entra, que não é onde o som
    entra."""
    assert F.distribuir(234, 100, 1) == [284]


def test_pedido_impossivel_devolve_vazio_em_vez_de_estourar():
    assert F.distribuir(0, 0, 3) == []
    assert F.distribuir(0, 100, 0) == []
