"""A RELAÇÃO entre as formas (plano 2026-11-26, etapa 2): o manifesto da conversão, a transformação, a impressão.

"O original X ganhou a cópia Y com a transformação Z" (autor): quem converte grava `ciclo-conversao.json`; a Carta o lê ao
anexar e registra o fato `relacao`; o par cuja impressão não confere com o manifesto NÃO entra (o manifesto é dica forte,
não verdade cega)."""
from __future__ import annotations

import json
from pathlib import Path

from cicloassist.carta import anexar, diario, projeto, referencias, relacoes


def test_transformacao_pela_sonda_dos_dois():
    o = {"taxa": "24000/1001", "largura": 3840, "altura": 2160, "tc": "01:00:00:00", "quadros": 240, "canais": 2}
    p = {"taxa": "24000/1001", "largura": 1920, "altura": 1080, "tc": "01:00:00:00", "quadros": 240, "canais": 2}
    t = relacoes.transformacao(o, p)
    assert t["enquadramento"] == {"tipo": "escala", "fator": 0.5, "area": None}
    assert (t["taxa"], t["tc_desloc_q"], t["trecho"], t["canais"]) == ("igual", 0, None, "iguais")
    # 2K DCI (1,896) num 1920×1080 (1,778): o quadro do convertido é MENOS largo — letterbox
    lb = relacoes.transformacao({**o, "largura": 2048, "altura": 1080}, {**p, "largura": 1920, "altura": 1080})
    assert lb["enquadramento"]["tipo"] == "letterbox"
    outro = relacoes.transformacao(o, {**p, "taxa": "25", "tc": "00:00:00:00", "quadros": 250, "canais": 4})
    assert outro["taxa"] == {"de": "24000/1001", "para": "25"} and outro["tc"]["para"] == "00:00:00:00"
    assert outro["trecho"] == {"quadros_original": 240, "quadros_convertido": 250} and outro["canais"] == {"de": 2, "para": 4}


def test_manifesto_grava_relativo_e_le(tmp_path):
    conv = tmp_path / "PROXY" / "A001.mov"
    conv.parent.mkdir()
    conv.write_bytes(b"p" * 100)
    m = relacoes.escrever_manifesto(conv.parent, [{"original": {"arquivo": "/orig/A001.mov", "largura": 3840, "altura": 2160},
                                                   "convertido": {"arquivo": str(conv), "largura": 1920, "altura": 1080}}],
                                    "teste")
    d = json.loads(m.read_text(encoding="utf-8"))
    assert d["formato"] == relacoes.FORMATO and d["feito_por"] == "teste"
    assert d["pares"][0]["convertido"]["arquivo"] == "A001.mov"           # relativo: a pasta pode mudar de lugar
    assert d["pares"][0]["transformacao"]["enquadramento"]["fator"] == 0.5
    relacoes.escrever_manifesto(conv.parent, [{"original": {"arquivo": "/orig/A001.mov"}, "convertido": {"arquivo": str(conv)}}],
                                "teste")
    assert len(relacoes.ler_manifesto(conv.parent)["pares"]) == 1            # o mesmo convertido não repete


def test_anexar_le_o_manifesto_e_registra_a_relacao_com_a_impressao(tmp_path):
    from cicloassist.midia import identidade as _id
    raiz = tmp_path / "CARTA"
    raiz.mkdir()
    proj = projeto.novo(raiz, "T", "24000/1001")
    orig = tmp_path / "ORIG" / "A001.mov"
    orig.parent.mkdir()
    orig.write_bytes(b"o" * 1000)
    _, ref = referencias.criar(proj, "", "A001", {"nome_da_fonte": "A001", "tipo": "video"}, {"nle": "teste"})
    anexar._vincular(proj, ref["id"], "original", orig, "teste", anexar.Conta())
    f = diario.formas(proj)[ref["id"]][0]
    assert f["impressao"] == _id.impressao(orig)                            # a forma leva a impressão do arquivo
    pasta = tmp_path / "PROXY"
    pasta.mkdir()
    conv = pasta / "A001_proxy.mov"                                          # outro nome: a identidade não casaria
    conv.write_bytes(b"p" * 500)
    relacoes.escrever_manifesto(pasta, [{"original": {"arquivo": str(orig), "largura": 3840, "altura": 2160,
                                                      "impressao": _id.impressao(orig)},
                                         "convertido": {"arquivo": str(conv), "largura": 1920, "altura": 1080,
                                                        "impressao": _id.impressao(conv)}}], "resolve_proxy")
    conta = anexar.Conta()
    feitos = relacoes.registrar_do_manifesto(proj, pasta, "trabalho", conta)
    assert feitos == ["A001_proxy.mov"]
    trab = [x for x in diario.formas(proj)[ref["id"]] if x["forma"] == "trabalho"]
    assert len(trab) == 1 and "manifesto" in trab[0]["por"]                 # o convertido entrou PELO manifesto
    rel = relacoes.relacoes(proj)[ref["id"]][0]
    assert rel["forma"] == "trabalho" and rel["transformacao"]["enquadramento"]["tipo"] == "escala"
    assert rel["por"] == "manifesto:resolve_proxy" and rel["impressao"]["convertido"] == _id.impressao(conv)
    assert relacoes.registrar_do_manifesto(proj, pasta, "trabalho") == []   # de novo: nada repete


def test_impressao_que_nao_confere_nao_entra(tmp_path):
    raiz = tmp_path / "CARTA"
    raiz.mkdir()
    proj = projeto.novo(raiz, "T", "24000/1001")
    orig = tmp_path / "A.mov"
    orig.write_bytes(b"o" * 10)
    _, ref = referencias.criar(proj, "", "A", {"nome_da_fonte": "A", "tipo": "video"}, {"nle": "teste"})
    anexar._vincular(proj, ref["id"], "original", orig, "teste", anexar.Conta())
    pasta = tmp_path / "P"
    pasta.mkdir()
    conv = pasta / "A.mov"
    conv.write_bytes(b"OUTRO ARQUIVO")
    relacoes.escrever_manifesto(pasta, [{"original": {"arquivo": str(orig)},
                                         "convertido": {"arquivo": str(conv), "impressao": "0" * 64}}], "x")
    conta = anexar.Conta()
    assert relacoes.registrar_do_manifesto(proj, pasta, "trabalho", conta) == []
    assert any("impressão não confere" in s for s in conta.sem_par)
    assert ref["id"] not in relacoes.relacoes(proj)
