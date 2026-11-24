"""`notas.json` como LISTA crua não pode derrubar a aba Vetores.

⛔⛔ **O defeito era NOSSO, e a conta veio de fora.** O `tools/consertar_quadros.py`
regravou `notas.json` como a lista crua (`[...]`) em 2026-09-17, em vez do
`{"notas": [...]}` que `Midia.anotar` grava. `ler_notas` fazia `.get` na lista, e um único
arquivo desses derrubava o inventário INTEIRO com 500: a aba mostrava "0 mídias" com o
disco cheio.

Achado pelo autor no Media Composer em 19/09 — **do lado do Assist anterior**, que compartilha
este cache (17 de 172 lá). Reproduzido aqui em 20/09: **4 das 332 mídias** derrubavam
`ler_notas`.

⇒ Dois consertos, e os dois precisam existir: o LEITOR aceita os dois formatos (os arquivos
já gravados não são tocados) e o GRAVADOR volta a gravar o formato de sempre.
"""

from __future__ import annotations

import json
import time

from cicloassist.midia import inventario as I

from .test_inventario import midia_de_imagem


def test_a_lista_crua_e_lida_como_as_notas(tmp_path):
    m = midia_de_imagem(tmp_path)
    nota = {"trecho": "A001_C003", "escopo": "midia", "descricao": "close"}
    (m.pasta / "notas.json").write_text(json.dumps([nota]), encoding="utf-8")
    assert m.ler_notas() == [nota]


def test_o_inventario_sobrevive_a_notas_em_lista_vazia(tmp_path):
    m = midia_de_imagem(tmp_path, quadros=2)
    (m.pasta / "notas.json").write_text("[]", encoding="utf-8")
    (linha,) = I.listar(tmp_path)
    assert linha.visual.quantos == 2


def test_o_formato_de_sempre_continua_valendo(tmp_path):
    m = midia_de_imagem(tmp_path)
    m.anotar({"trecho": "A001_C003", "escopo": "midia", "descricao": "plano geral"})
    assert [n["descricao"] for n in m.ler_notas()] == ["plano geral"]


def test_lixo_dentro_da_lista_nao_vira_nota(tmp_path):
    """⚠️ Cache corrompido vira "não tenho isso", nunca exceção — aqui também."""
    m = midia_de_imagem(tmp_path)
    (m.pasta / "notas.json").write_text(json.dumps([{"trecho": "a"}, "x", 7, None]),
                                        encoding="utf-8")
    assert m.ler_notas() == [{"trecho": "a"}]


def test_o_consertar_quadros_grava_o_formato_que_ler_notas_espera(tmp_path, monkeypatch):
    """⭐ O GRAVADOR, que é a causa. Sem este teste o conserto do leitor esconderia o
    defeito, e a próxima rodada da ferramenta reintroduziria arquivos quebrados."""
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from tools import consertar_quadros as CQ

    m = midia_de_imagem(tmp_path)
    m.anotar({"trecho": "A001_C003", "escopo": "midia", "descricao": "close"})
    m.anotar({"trecho": "A001_C003 10-20", "escopo": "take", "descricao": "a fala"})

    # ⚠️ Corte no futuro: aqui o que se mede é o FORMATO do que ele grava.
    CQ.consertar(m, fazer=True, corte=time.time() + 60, desde="2999-01-01")

    cru = json.loads((m.pasta / "notas.json").read_text(encoding="utf-8"))
    assert isinstance(cru, dict) and "notas" in cru, (
        "gravar a lista crua é o que quebrou 4 mídias do cache real")
    assert [n["escopo"] for n in m.ler_notas()] == ["take"]


def test_o_consertar_quadros_nao_joga_fora_o_que_veio_DEPOIS_do_conserto(tmp_path):
    """⛔⛔ A ferramenta é de conserto ÚNICO, e parecia idempotente sem ser.

    `frames.extrair_varios` decodifica em ordem nesses arquivos desde 17/09, mas a mídia
    continua sendo "de busca não confiável" para sempre. Rodando de novo, ela jogava fora
    quadros corretos e mandava para `notas_suspeitas.json` decupagens **certas e pagas com
    a assinatura do editor**. MEDIDO nesta máquina em 2026-09-22: as mesmas 17 mídias,
    agora com 234 quadros bons e 13 decupagens boas.
    """
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from tools import consertar_quadros as CQ

    m = midia_de_imagem(tmp_path)
    m.anotar({"trecho": "A001_C003", "escopo": "midia", "descricao": "close",
              "quando": "2026-09-20T10:00:00"})

    # O corte é ANTES de tudo que existe aqui: nada é velho.
    conta = CQ.consertar(m, fazer=True, corte=0.0, desde="2026-09-17")

    assert conta == {"quadros": 0, "notas": 0}
    assert m.quadros_guardados(), "apagou quadros que já estavam certos"
    assert [n["escopo"] for n in m.ler_notas()] == ["midia"], "levou uma decupagem paga"
    assert not (m.pasta / "notas_suspeitas.json").exists()
