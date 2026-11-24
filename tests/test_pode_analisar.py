"""O botão só conta o que a FILA consegue pegar — uma conta só, dos dois lados.

⛔⛔ MEDIDO na máquina do autor em 2026-09-20, com o cache real: das **106** mídias "sem
transcrição" nas bins do projeto, **100 não tinham arquivo** — música importada de outra
pasta e mídia AMA de um volume que ninguém varreu. A fila as pulava em silêncio
(`if not arquivos: continue`), e a tela contava todas: *"mesmo clicando nas opções elas não
são processadas"*. No caso da decupagem, o PREÇO mostrado antes do clique saía inflado
junto — e o preço antes do clique é a promessa central desta aba.

⇒ `inventario.pode_analisar` responde "a fila pega?", a rota de análise a usa para montar
a fila, e a linha da tabela a carrega (`pode`) para o rótulo do botão não prometer mais do
que será feito.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.midia import acervo as A
from cicloassist.midia import cache as C
from cicloassist.midia import estagios as E
from cicloassist.midia import inventario as I
from cicloassist.servico import rotas as R
from cicloassist.servico import tarefas as T
from cicloassist.servico.http import Pedido

SOM = "0x060A2B340101010101010F0013000000E56E1D13D305BE564AEC678A24E90A70"
IMAGEM = "0x060A2B340101010101010F0013000000C6D91F0BB8ABB1C7ABEE2FFBA70D1E05"


# ── a conta, sozinha ─────────────────────────────────────────────────────────

def test_sem_arquivo_da_especie_certa_a_fila_nao_pega():
    """As 100 do caso real: estão numa bin, aparecem na tabela, e não há o que ler."""
    so_na_bin = {"nome": "Piano e Cordas.wav", "por_tipo": {}, "fps": 23.976}
    assert I.pode_analisar(so_na_bin, E.TRANSCRICAO) is False
    assert I.pode_analisar(so_na_bin, E.VETORES) is False
    assert I.pode_analisar(so_na_bin, I.DECUPAGEM) is False


def test_som_serve_para_transcrever_e_nao_para_ver():
    clipe = {"por_tipo": {"audio": ["a1.mxf", "a2.mxf"]}}
    assert I.pode_analisar(clipe, E.TRANSCRICAO) is True
    assert I.pode_analisar(clipe, E.VETORES) is False
    assert I.pode_analisar(clipe, I.DECUPAGEM) is False


def test_imagem_sem_taxa_nao_serve_para_imagem():
    """⚠️ Sem `fps` não há como converter tempo em POSIÇÃO de quadro, e chutar 25
    erraria o quadro em todo material 23,976."""
    sem_taxa = {"por_tipo": {"video": ["v.mxf"]}}
    com_taxa = {"por_tipo": {"video": ["v.mxf"]}, "fps": 23.976}
    assert I.pode_analisar(sem_taxa, E.VETORES) is False
    assert I.pode_analisar(com_taxa, E.VETORES) is True
    assert I.pode_analisar(com_taxa, I.DECUPAGEM) is True


# ── a linha da tabela carrega a resposta ─────────────────────────────────────

def test_a_linha_diz_o_que_a_fila_pega(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    chave = C.de_umid(SOM)
    midia = C.Midia(chave, raiz_do_cache=tmp_path)
    midia.anotar_fonte({"master_de_som": "sem arquivo"})

    linha = I.de_uma(midia, {"nome": "sem arquivo", "por_tipo": {}, "bins": ["X.avb"]})
    d = linha.como_dicionario()
    assert d["pode"] == {E.TRANSCRICAO: False, E.VETORES: False, I.DECUPAGEM: False,
                         I.MICRO: False}

    com_som = I.de_uma(midia, {"nome": "tem som", "por_tipo": {"audio": ["a.mxf"]}})
    assert com_som.como_dicionario()["pode"][E.TRANSCRICAO] is True


# ── e a fila obedece à mesma conta ───────────────────────────────────────────

@pytest.fixture
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    T.esquecer()
    yield tmp_path
    T.parar()
    T.esquecer()


def test_a_fila_recusa_o_que_a_conta_recusa(cache_isolado):
    """⭐ O mesmo clipe do primeiro teste, agora pela rota: se a tela contasse e a fila
    pulasse, o editor clicaria e nada aconteceria — que foi o relato."""
    A.guardar("D:/mídia/música",
              [A.Clipe(C.de_umid(SOM), "Piano e Cordas.wav", [], {"audio": 2},
                       por_tipo={}, bytes=10)],
              raiz=cache_isolado)

    r = R.rota_analisar(Pedido("POST", "/vetores/analisar", {},
                               json.dumps({}).encode("utf-8")))
    assert r.status == 400
    assert "não há mídia" in json.loads(r.corpo.decode("utf-8"))["erro"]
