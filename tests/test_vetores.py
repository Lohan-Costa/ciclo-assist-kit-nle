"""O vetor visual e a busca por planos parecidos.

⭐ O motor foi escolhido por medida, não por fama (`spikes/busca_visual.py`, 2026-09-11):
MobileNetV2 em ONNX acerta 99% contra 38% ao acaso, com 14 MB — sem CLIP de 350 MB e sem
torch. O que estes testes travam é o que vem DEPOIS da escolha: onde o vetor mora, o que
acontece quando ele está pela metade, e a regra da busca.

⚠️ Nenhum teste aqui roda o modelo. Baixar 14 MB e executar uma rede numa suíte que
precisa rodar em menos de dois segundos seria trocar o que estes testes protegem por uma
medição que o spike já fez.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import estagios as E
from cicloassist.midia import vetores as V

UM = "0x060A2B340101010101010F0013000000C6D91F0BB8ABB1C7ABEE2FFBA70D1E05"
OUTRO = "0x060A2B340101010101010F0013000000E56E1D13D305BE564AEC678A24E90A70"


def normal(*valores) -> np.ndarray:
    v = np.array(valores, dtype="float32")
    return v / np.linalg.norm(v)


def com_vetores(raiz, umid, vetores, posicoes, receita=None):
    midia = C.Midia(umid, raiz_do_cache=raiz)
    V.guardar(midia, np.vstack(vetores), posicoes)
    midia.registrar_gerador(E.VETORES, receita or E.assinatura(E.VETORES))
    return midia


# ── onde o vetor mora ────────────────────────────────────────────────────────

def test_guardar_e_ler_de_volta(tmp_path):
    midia = com_vetores(tmp_path, UM, [normal(1, 0, 0), normal(0, 1, 0)], [10, 20])

    matriz, posicoes = V.ler(midia)
    assert matriz.shape == (2, 3)
    assert posicoes == [10, 20]
    assert V.quantos(midia) == 2


def test_sem_vetor_nao_e_erro(tmp_path):
    midia = C.Midia(UM, raiz_do_cache=tmp_path)
    assert V.tem(midia) is False
    assert V.ler(midia) == (None, [])
    assert V.quantos(midia) == 0


def test_posicoes_que_nao_batem_com_a_matriz_sao_ignoradas(tmp_path):
    """⚠️ Escrita interrompida entre os dois arquivos: preferir "não tenho" a entregar um
    quadro com a posição de outro — um match cut apontado para o frame errado é pior que
    nenhum resultado."""
    midia = com_vetores(tmp_path, UM, [normal(1, 0, 0), normal(0, 1, 0)], [10, 20])
    (midia.pasta / "vetores.json").write_text(json.dumps({"posicoes": [10]}),
                                              encoding="utf-8")
    assert V.ler(midia) == (None, [])


def test_json_corrompido_vira_vazio(tmp_path):
    midia = com_vetores(tmp_path, UM, [normal(1, 0, 0)], [10])
    (midia.pasta / "vetores.json").write_text("{", encoding="utf-8")
    assert V.ler(midia) == (None, [])
    assert V.quantos(midia) == 0


def test_a_receita_mudou_e_o_vetor_precisa_refazer(tmp_path):
    midia = com_vetores(tmp_path, UM, [normal(1, 0, 0)], [10],
                        receita={"modelo": "outro-qualquer"})
    assert midia.precisa_refazer(E.VETORES, E.assinatura(E.VETORES))


# ── a busca ──────────────────────────────────────────────────────────────────

def test_acha_o_mais_parecido(tmp_path):
    com_vetores(tmp_path, UM, [normal(1, 0, 0), normal(0.9, 0.1, 0)], [10, 20])
    com_vetores(tmp_path, OUTRO, [normal(0, 0, 1)], [5])

    achados = V.procurar(normal(1, 0, 0), raiz=tmp_path)
    assert achados[0]["chave"] == C.de_umid(UM)
    assert achados[0]["parecenca"] > achados[1]["parecenca"]


def test_uma_linha_por_midia_e_o_melhor_quadro(tmp_path):
    """⭐ Sem isto, os doze quadros de um plano tomam a lista inteira e o editor vê um
    resultado só, doze vezes."""
    com_vetores(tmp_path, UM,
                [normal(0.2, 1, 0), normal(1, 0, 0), normal(0.5, 0.5, 0)],
                [10, 20, 30])

    (achado,) = V.procurar(normal(1, 0, 0), raiz=tmp_path)
    assert achado["frame_no_master"] == 20


def test_o_proprio_plano_fica_de_fora(tmp_path):
    """⭐⭐ A regra que o spike descobriu errando: procurar "parecido com este" trazendo o
    próprio de volta faz QUALQUER motor acertar 100%, inclusive um que comparasse o
    tamanho em bytes. Quem pergunta quer saber ONDE MAIS existe algo assim."""
    com_vetores(tmp_path, UM, [normal(1, 0, 0)], [10])
    com_vetores(tmp_path, OUTRO, [normal(0, 1, 0)], [5])

    (achado,) = V.procurar(normal(1, 0, 0), exceto=C.de_umid(UM), raiz=tmp_path)
    assert achado["chave"] == C.de_umid(OUTRO)


def test_a_busca_leva_o_nome_que_o_editor_conhece(tmp_path):
    midia = com_vetores(tmp_path, UM, [normal(1, 0, 0)], [10])
    midia.anotar_fonte({"master": "A001_C003"})

    assert V.procurar(normal(1, 0, 0), raiz=tmp_path)[0]["nome"] == "A001_C003"


def test_cache_sem_vetor_nenhum_devolve_lista_vazia(tmp_path):
    assert V.procurar(normal(1, 0, 0), raiz=tmp_path) == []


def test_pasta_estranha_no_cache_nao_entra_na_busca(tmp_path):
    (tmp_path / "Nova pasta").mkdir()
    assert V.procurar(normal(1, 0, 0), raiz=tmp_path) == []


def test_o_limite_e_respeitado(tmp_path):
    for i, umid in enumerate([UM, OUTRO]):
        com_vetores(tmp_path, umid, [normal(1, i, 0)], [i])
    assert len(V.procurar(normal(1, 0, 0), limite=1, raiz=tmp_path)) == 1


# ── o modelo ─────────────────────────────────────────────────────────────────

def test_o_modelo_nao_mora_dentro_do_cache_de_midia(tmp_path, monkeypatch):
    """⛔ O botão "apagar tudo" do painel apaga a pasta de mídia inteira. O modelo não é
    cache do material do cliente — é peça do produto, e rebaixá-lo custaria 14 MB de
    download a cada limpeza."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "midia"))
    assert C.raiz() not in V.caminho_do_modelo().parents


def test_modelo_pela_metade_nao_conta_como_baixado(tmp_path, monkeypatch):
    """⚠️ Um download interrompido deixaria um arquivo que o onnxruntime tentaria abrir
    para sempre."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "midia"))
    alvo = V.caminho_do_modelo()
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(b"mentira")
    assert V.temos_o_modelo() is False


def test_a_assinatura_diz_o_modelo_e_a_amostragem():
    """É o que a coluna "modelo" da aba mostra, e o que faz o vetor velho cair sozinho
    quando a rede mudar."""
    a = E.assinatura(E.VETORES)
    assert a["modelo"] == "mobilenetv2-12"
    assert a["quadros"] == V.QUANTOS


def test_ferramenta_de_busca_esta_registrada_e_e_de_leitura():
    """⛔ `escreve=False`: procurar não muda nada no projeto do editor, e uma pergunta
    dessas não pode acordar o portão."""
    from cicloassist.mcp import ferramentas  # noqa: F401
    from cicloassist.mcp.registro import FERRAMENTAS

    f = FERRAMENTAS["planos_parecidos"]
    assert f.escreve is False


def test_a_descricao_avisa_o_que_a_busca_nao_e():
    """⚠️ A medição foi em cena fechada. A ferramenta tem de dizer isso ao modelo, senão
    ele afirma ao editor que é a mesma pessoa — com confiança, porque o número é alto."""
    from cicloassist.mcp.registro import FERRAMENTAS

    d = FERRAMENTAS["planos_parecidos"].descricao.lower()
    assert "não é" in d and "reconhecimento de pessoa" in d


def test_busca_sem_modelo_explica_o_que_fazer(monkeypatch, tmp_path):
    """⭐ "Não achei nada" mandaria o modelo tentar de novo. Dizer o que falta manda o
    editor a um botão que resolve."""
    monkeypatch.setattr(V, "temos_o_modelo", lambda: False)
    from cicloassist.mcp.ferramentas import parecidos

    erro = parecidos.planos_parecidos(bin="x", item="y")["erro"]
    assert "aba Vetores" in erro


def test_busca_recusa_imagem_que_nao_foi_arrastada(monkeypatch):
    """⛔⛔ O caminho chega dentro de texto que o MODELO escreve. Sem a lista de
    arrastados, "procure parecido com esta imagem" seria a máquina inteira legível."""
    monkeypatch.setattr(V, "temos_o_modelo", lambda: True)
    from cicloassist.mcp.ferramentas import parecidos

    erro = parecidos.planos_parecidos(imagem=r"C:\Windows\System32\config\SAM")["erro"]
    assert "não tenho permissão" in erro.lower()
