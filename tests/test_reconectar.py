"""Reconectar: olhar a pasta ANTES de trocar o cache para ela.

⭐ O editor moveu o cache para outro disco e quer reapontar em vez de reprocessar. Como
tudo é endereçado pelo UMID do master, reconectar é literalmente "aponte para lá" — o que
faltava era **saber o que há lá antes de clicar**. Apontar às cegas não falha na hora:
falha em silêncio, reprocessando tudo por semanas.
"""

from __future__ import annotations

import json

from cicloassist.midia import cache as C
from cicloassist.servico import rotas as R
from cicloassist.servico.http import Pedido

UMID = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.64cedc20.1dc80000.060e2b34.7f7f2a80"
OUTRO = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.6505f172.1c710000.060e2b34.7f7f2a80"


def olhar(caminho):
    pedido = Pedido("POST", "/cache/olhar", {},
                    json.dumps({"caminho": str(caminho)}).encode("utf-8"))
    resposta = R.rota_olhar_pasta_de_cache(pedido)
    return resposta.status, json.loads(resposta.corpo.decode("utf-8"))


def cache_com(raiz, *umids):
    for umid in umids:
        midia = C.Midia(umid, raiz_do_cache=raiz)
        midia.guardar_quadro(10, b"\xff\xd8" + b"x" * 500)
    return raiz


# ── os três casos que o editor encontra ──────────────────────────────────────

def test_pasta_com_cache_conta_as_midias(tmp_path):
    """⭐ O caso que o reconectar existe para resolver: o trabalho está lá, e reapontar o
    devolve inteiro."""
    cache_com(tmp_path, UMID, OUTRO)

    status, d = olhar(tmp_path)
    assert status == 200 and d["ok"]
    assert d["existe"] and d["midias"] == 2
    assert d["estranhas"] == 0
    assert d["bytes"] > 0


def test_pasta_que_nao_e_cache_e_denunciada(tmp_path):
    """⚠️ Apontar para "Documentos" é o erro fácil — e ele não falha na hora. Contar o que
    NÃO é nosso é o que permite ao painel dizer "confira se é mesmo a pasta do cache"."""
    (tmp_path / "Fotos").mkdir()
    (tmp_path / "Projetos").mkdir()

    _, d = olhar(tmp_path)
    assert d["midias"] == 0
    assert d["estranhas"] == 2


def test_pasta_que_ainda_nao_existe_nao_e_erro(tmp_path):
    """⭐ É a resposta, não a falha: salvar vai criá-la, e o editor só precisa saber que
    vai começar do zero."""
    status, d = olhar(tmp_path / "ainda nao")
    assert status == 200 and d["ok"]
    assert d["existe"] is False


def test_pasta_vazia_diz_que_nada_se_perde(tmp_path):
    _, d = olhar(tmp_path)
    assert d["existe"] and d["midias"] == 0 and d["estranhas"] == 0


# ── as fronteiras ────────────────────────────────────────────────────────────

def test_caminho_relativo_e_recusado(tmp_path, monkeypatch):
    """Sem a letra do disco, "midia" seria relativo ao diretório de quem subiu o serviço —
    um lugar que o editor não escolheu e não sabe qual é."""
    status, d = olhar("midia")
    assert status == 400 and not d["ok"]


def test_sem_caminho_e_erro_do_cliente():
    pedido = Pedido("POST", "/cache/olhar", {}, b"{}")
    assert R.rota_olhar_pasta_de_cache(pedido).status == 400


def test_olhar_nao_cria_nada(tmp_path):
    """⛔ Olhar é LEITURA. A pasta só passa a existir — e a valer — quando o editor salva;
    uma rota que criasse pasta a cada tecla encheria o disco de pastas vazias."""
    alvo = tmp_path / "nao devo existir"
    olhar(alvo)
    assert not alvo.exists()


def test_olhar_nao_troca_a_configuracao(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "em uso"))
    antes = C.raiz()
    olhar(tmp_path / "outra")
    assert C.raiz() == antes


def test_diz_quando_e_a_pasta_que_ja_esta_em_uso(tmp_path, monkeypatch):
    """Sem isto, o editor olha a própria pasta atual e lê "achei 23 mídias — reapontar
    recupera esse trabalho", como se fosse mudar alguma coisa."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    cache_com(tmp_path, UMID)

    _, d = olhar(tmp_path)
    assert d["atual"] is True


# ── a medição por baixo ──────────────────────────────────────────────────────

def test_a_medida_separa_o_que_e_nosso_do_que_nao_e(tmp_path):
    """A mesma conta serve à tela de configurações e ao reconectar — e ela conta MÍDIA,
    não "qualquer pasta", que era o que fazia a engrenagem dizer 23 takes numa pasta com
    duas pastas nossas e vinte e uma de outra coisa."""
    cache_com(tmp_path, UMID)
    (tmp_path / "sobra").mkdir()

    medida = R._medir_o_cache(tmp_path)
    assert medida["midias"] == 1
    assert medida["estranhas"] == 1
    assert medida["takes"] == medida["midias"]      # o nome antigo continua valendo
