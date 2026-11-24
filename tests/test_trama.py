"""`o_que_acontece` — a trama do take no chat (F4 da decupagem micro, 2026-09-22).

O que estes testes travam:

- a linha sai no TEMPO DO TAKE, com o offset de cada master (⛔ o do som não é o da imagem:
  medido na C07, imagem em 0 e som em 234 quadros);
- só o que encosta na janela do take entra (um subclipe de 30 s num master de 10 min);
- as falas caem DENTRO do trecho em que são ditas, com o `segmento` que `transcrever`
  numera — e é esse número que `separar_falas` aceita;
- sem a micro feita, a resposta diz o GESTO que falta em vez de vir vazia;
- a resposta tem TETO (o mesmo do `transcrever`) e diz por onde continuar.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from cicloassist.avid.take import Fonte, Take
from cicloassist.midia import cache as C
from cicloassist.midia import cortes as K
from cicloassist.mcp.ferramentas import trama as TR

CHAVE_V = "a" * 64
CHAVE_A = "b" * 64
TAXA = Fraction(24000, 1001)


def _fonte(chave, inicio, master="M"):
    return Fonte(master=master, mob_id=chave, arquivos=["x.mxf"], inicio_frames=inicio,
                 inicio_s=float(inicio / TAXA), tracks=1, chave=chave, tipo_da_chave="umid")


def _take(inicio_imagem=0, inicio_som=234, duracao=720):
    return Take(nome="C07_P01-T001", bin="C07.avb", mob_id="urn:x", cena="C7", plano="P1",
                take="T1", fonte_da_claquete="claquete",
                fps={"num": 24000, "den": 1001}, fps_aprox=23.976,
                duracao_frames=duracao, duracao_s=float(duracao / TAXA),
                imagem=_fonte(CHAVE_V, inicio_imagem), som=_fonte(CHAVE_A, inicio_som),
                confianca="confirmado", fonte="claquete")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    v = C.Midia(CHAVE_V, rotulo={"nome": "M"})
    v.pasta  # noqa: B018
    a = C.Midia(CHAVE_A, rotulo={"nome": "M som"})
    a.pasta  # noqa: B018
    return v, a


def _com_trechos(v, trechos, notas=True):
    C.escrever_atomico(v.pasta / K.ARQUIVO, __import__("json").dumps(
        {"quadros": 2000, "bruto": True, "fronteiras": [],
         "trechos": trechos}).encode("utf-8"))
    v.registrar_gerador("cortes", K.ASSINATURA)
    if notas:
        for t in trechos:
            v.anotar({"trecho": f"M · trecho {t['inicio']}", "escopo": "trecho",
                      "inicio_frames": t["inicio"], "duracao_frames": t["fim"] - t["inicio"],
                      "inicio_s": t["inicio"] / float(TAXA), "fim_s": t["fim"] / float(TAXA),
                      "descricao": f"acontece algo em {t['inicio']}",
                      "confianca": "inferido", "fonte": "visual"})


def test_a_linha_sai_no_tempo_do_take_com_o_offset_de_cada_master(cache, monkeypatch):
    v, a = cache
    # O take entra no quadro 240 da IMAGEM e no 480 do SOM — offsets diferentes.
    _com_trechos(v, [{"inicio": 0, "fim": 240, "entrada": "inicio", "planos": [0]},
                     {"inicio": 240, "fim": 600, "entrada": "mudanca", "planos": [240]},
                     {"inicio": 600, "fim": 960, "entrada": "mudanca", "planos": [600]}])
    a.guardar_transcricao([{"inicio": 30.0, "fim": 31.0, "texto": "no take", "certeza": 0.9}])
    take = _take(inicio_imagem=240, inicio_som=480, duracao=720)
    monkeypatch.setattr(TR._nle, "resolver_take", lambda bin, item: take)

    r = TR.o_que_acontece(bin="C07.avb", item="C07_P01-T001")

    # ⛔ O trecho que termina ANTES da entrada do take não entra.
    assert [t["em"] for t in r["linha"]] == ["00:00", "00:15"]
    assert r["linha"][0]["entrada"] == "mudanca" and r["linha"][0]["descricao"]
    # A fala em 30 s do master do SOM é 30 − 20 = 10 s no take (o som entra em 480 quadros).
    dito = [f for t in r["linha"] for f in t.get("diz", [])]
    assert dito and dito[0]["em"] == "00:10" and dito[0]["segmento"] == 1


def test_sem_micro_a_resposta_diz_o_gesto_que_falta(cache, monkeypatch):
    v, a = cache
    a.guardar_transcricao([{"inicio": 1.0, "fim": 2.0, "texto": "oi", "certeza": 0.9}])
    monkeypatch.setattr(TR._nle, "resolver_take", lambda bin, item: _take(inicio_som=0))
    r = TR.o_que_acontece(bin="b", item="i")
    assert "Decupar em trechos" in r["sem_trechos"]
    assert r["linha"] and r["linha"][0]["diz"] == "oi"


def test_trecho_sem_nota_e_contado_e_dito(cache, monkeypatch):
    v, _ = cache
    _com_trechos(v, [{"inicio": 0, "fim": 480, "entrada": "inicio", "planos": [0]}],
                 notas=False)
    monkeypatch.setattr(TR._nle, "resolver_take", lambda bin, item: _take(inicio_som=0))
    r = TR.o_que_acontece(bin="b", item="i")
    assert r["trechos_sem_decupagem"] == 1 and "Decupar em trechos" in r["aviso"]


def test_a_resposta_tem_teto_e_diz_por_onde_continuar(cache, monkeypatch):
    v, _ = cache
    trechos = [{"inicio": i * 240, "fim": (i + 1) * 240, "entrada": "mudanca",
                "planos": [i * 240]} for i in range(200)]
    _com_trechos(v, trechos, notas=False)
    monkeypatch.setattr(TR._nle, "resolver_take", lambda bin, item: _take(duracao=48000))
    r = TR.o_que_acontece(bin="b", item="i")
    assert r["proximo"] and len(r["linha"]) < 200 and "a_partir=" in r["aviso_pagina"]
    r2 = TR.o_que_acontece(bin="b", item="i", a_partir=r["proximo"])
    assert r2["linha"][0]["em"] != r["linha"][0]["em"]
    # ⚠️⚠️ E a resposta DIZ de quantos é a página. O campo existia e era descartado por um
    #   `pop` logo depois de ser posto: uma página de 8 trechos de um take que tem 200 se
    #   lia como o take inteiro, e o modelo contaria a trama achando que viu o fim.
    assert r["trechos_no_take"] == 200 and r["mostrando"] == len(r["linha"])


def test_a_conta_das_falas_de_fora_usa_os_segundos_e_nao_o_relogio(cache, monkeypatch):
    """⚠️ `dentro` contava por segundos e `fora` comparava o relógio `MM:SS`: uma fala na
    fronteira era dentro por arredondamento e fora pela conta, e os dois números não
    fechavam com nada."""
    v, a = cache
    _com_trechos(v, [{"inicio": 0, "fim": 240, "entrada": "inicio", "planos": [0]}])
    a.guardar_transcricao([
        {"inicio": 2.0, "fim": 3.0, "texto": "dentro", "certeza": 0.9},
        # ⚠️ Depois do fim do trecho (240 quadros = 10,01 s) COM FOLGA: a fala se localiza
        #    pela entrada do corte, que tem o respiro medido antes da primeira palavra.
        {"inicio": 12.0, "fim": 13.0, "texto": "logo depois", "certeza": 0.9},
    ])
    monkeypatch.setattr(TR._nle, "resolver_take", lambda bin, item: _take(inicio_som=0))

    r = TR.o_que_acontece(bin="b", item="i")

    assert r["falas_no_take"] == 2
    assert r["falas_fora_dos_trechos"] == 1
    assert [f["texto"] for f in r["linha"][0]["diz"]] == ["dentro"]


def test_a_macro_e_a_claquete_vao_junto(cache, monkeypatch):
    v, _ = cache
    _com_trechos(v, [{"inicio": 0, "fim": 480, "entrada": "inicio", "planos": [0]}])
    v.anotar({"trecho": "M", "escopo": "midia", "descricao": "o material inteiro",
              "cena": "11", "claquete": {"legivel": True, "rolo": ["A05"], "cena": "11"},
              "confianca": "inferido", "fonte": "visual"})
    monkeypatch.setattr(TR._nle, "resolver_take", lambda bin, item: _take(inicio_som=0))
    r = TR.o_que_acontece(bin="b", item="i")
    assert r["do_material_inteiro"]["descricao"] == "o material inteiro"
    assert r["claquete_diz"] == {"cena": "11"}
