"""Um vetor por PLANO — `planos_parecidos` dentro de material montado (F4, 2026-09-22).

⭐ Sem isto, uma peça de 600 planos é representada pelos 12 quadros espalhados da
amostragem: quase nenhum plano tem vetor, e "onde mais tem um plano assim?" não alcança
material de arquivo.

O que estes testes travam:

- o agrupamento é por PLANO, não por trecho (a micro junta até 8 planos por trecho);
- a resposta traz até `PLANOS_POR_MIDIA` momentos DIFERENTES da mesma peça — a regra antiga
  de uma linha por mídia existe por causa de quadros vizinhos iguais, não de planos;
- apontando um quadro de uma peça, sai só o PLANO de origem, não a peça inteira;
- ⛔ a receita dos vetores NÃO muda: mudá-la invalidaria o cache inteiro (332 mídias).
"""

from __future__ import annotations

import json
from fractions import Fraction

import numpy as np
import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import cortes as K
from cicloassist.midia import vetores as V

TAXA = Fraction(25)


def _com_planos(midia, planos_por_trecho=(([0, 50, 100], 150), ([150, 200], 250))):
    trechos = [{"inicio": p[0], "fim": fim, "entrada": "corte", "planos": p}
               for p, fim in planos_por_trecho]
    C.escrever_atomico(midia.pasta / K.ARQUIVO, json.dumps(
        {"quadros": 250, "bruto": False, "fronteiras": [], "trechos": trechos}).encode("utf-8"))
    midia.registrar_gerador("cortes", K.ASSINATURA)
    return trechos


def _vetor(n: int, dim: int = 8):
    v = np.zeros(dim, dtype="float32")
    v[n % dim] = 1.0
    return v


@pytest.fixture
def midia(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    m = C.Midia("a" * 64, rotulo={"nome": "PEÇA"})
    m.pasta  # noqa: B018
    return m


def test_agrupa_por_plano_e_nao_por_trecho(midia):
    _com_planos(midia)
    # cinco planos em dois trechos
    assert set(V._por_plano(midia, [25, 75, 125, 175, 225]).values()) == {0, 1, 2, 3, 4}


def test_a_peca_devolve_varios_momentos_e_o_take_um_so(midia, tmp_path):
    _com_planos(midia)
    V.guardar(midia, np.asarray([_vetor(i) for i in range(5)]), [25, 75, 125, 175, 225])
    take = C.Midia("b" * 64, rotulo={"nome": "TAKE"})
    take.pasta  # noqa: B018
    V.guardar(take, np.asarray([_vetor(0)] * 4), [10, 20, 30, 40])

    achados = V.procurar(_vetor(0), limite=10)
    da_peca = [a for a in achados if a["nome"] == "PEÇA"]
    do_take = [a for a in achados if a["nome"] == "TAKE"]
    assert len(da_peca) <= V.PLANOS_POR_MIDIA and len(da_peca) > 1
    assert da_peca[0]["de_planos"] == 5 and da_peca[0]["plano"] == 1
    # ⭐ O take (sem planos detectados) continua com UMA linha, a do melhor quadro.
    assert len(do_take) == 1 and "plano" not in do_take[0]


def test_apontando_um_quadro_sai_so_o_plano_de_origem(midia):
    _com_planos(midia)
    V.guardar(midia, np.asarray([_vetor(0) for _ in range(5)]), [25, 75, 125, 175, 225])
    achados = V.procurar(_vetor(0), limite=10, exceto=midia.chave, exceto_frame=75)
    assert achados and all(a["frame_no_master"] != 75 for a in achados)
    # ⚠️ Sem o quadro de origem (o caminho antigo), a mídia inteira continua fora.
    assert V.procurar(_vetor(0), limite=10, exceto=midia.chave) == []


def test_acrescenta_sem_mudar_a_receita(midia, monkeypatch):
    trechos = _com_planos(midia)
    V.guardar(midia, np.asarray([_vetor(9)]), [25])          # um vetor já existente
    midia.registrar_gerador("vetores", V.ASSINATURA)
    monkeypatch.setattr(V, "de_jpeg", lambda jpeg: _vetor(1))
    monkeypatch.setattr(V._frames, "extrair_varios",
                        lambda v, pos, taxa, **k: {p: b"\xff\xd8x" for p in pos})

    r = V.vetorizar_planos(midia, "x.mp4", TAXA, trechos, "PEÇA")

    matriz, posicoes = V.ler(midia)
    # ⚠️ O quadro 25 já estava coberto (o plano 0): não é vetorizado de novo.
    assert r["acrescentados"] == 4 and posicoes[0] == 25 and len(posicoes) == 5
    assert posicoes == sorted(posicoes)
    # ⛔ A receita é a mesma: nada do cache existente vira "a refazer".
    assert not midia.precisa_refazer("vetores", V.ASSINATURA)
