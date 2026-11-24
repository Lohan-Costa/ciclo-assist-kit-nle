"""A decupagem em lote — o único trabalho do produto que gasta a assinatura do editor.

⭐⭐ E por isso o que estes testes travam é diferente do resto: não é "funciona", é **não
mente e não estraga**. Uma decupagem gravada na mídia errada seria plausível e invisível;
um JSON mal lido joga fora um turno que custou dinheiro.

## O preço, MEDIDO em 2026-09-11 (mídia real, Haiku 4.5, 6 quadros)

```
1 mídia por turno    42.205 tokens · US$ 0,0254 · ~20 s por mídia
3 mídias por turno   16.818 tokens · US$ 0,0153 · ~10 s por mídia
```

⭐ O custo é do TURNO, não do conteúdo: ~40 mil tokens são o piso do `claude -p` (prompt
de sistema e maquinaria do CLI) e só ~2,5 mil são os quadros e a resposta. Nosso catálogo
inteiro de ferramentas é 3,4 mil. É daí que sai `POR_TURNO`.
"""

from __future__ import annotations

import pytest

from cicloassist.motor import decupador as D

A = "a" * 64
B = "b" * 64


# ── ler a resposta do modelo ─────────────────────────────────────────────────

def test_json_puro():
    assert D._json_da_resposta('{"x": 1}') == {"x": 1}


def test_json_em_cerca_de_codigo():
    """O prompt pede JSON puro e o modelo quase sempre obedece — mas "quase sempre" numa
    fila de trezentas mídias são dezenas de turnos perdidos."""
    assert D._json_da_resposta('```json\n{"x": 1}\n```') == {"x": 1}


def test_json_com_prosa_em_volta():
    assert D._json_da_resposta('Claro! {"x": 1} Espero ter ajudado.') == {"x": 1}


def test_resposta_sem_json_e_falha():
    with pytest.raises(D.DecupagemFalhou):
        D._json_da_resposta("não consegui ver os quadros")


def test_dois_json_colados_nao_viram_lixo():
    """⚠️⚠️ O CLI manda a resposta nos blocos `assistant` E de novo no `result`. Concatenar
    os dois produz `{...}{...}` — MEDIDO em 2026-09-11: **2 de 3 mídias falharam assim**
    na primeira rodada, com "Extra data", numa resposta perfeita. O conserto está em ler
    só um dos dois; este teste garante que, se os dois vierem colados, ainda sai algo em
    vez de exceção."""
    com_dois = '{"descricao": "primeira"}\n{"descricao": "primeira"}'
    with pytest.raises(D.DecupagemFalhou):
        D._json_da_resposta(com_dois)


# ── montar as notas ──────────────────────────────────────────────────────────

def test_uma_midia_aceita_resposta_plana():
    """⭐ Com uma mídia só, o modelo responde os campos direto. Recusar isso perderia o
    turno inteiro por causa de uma casca."""
    notas, _ = D.notas_da_resposta({"descricao": "um homem sentado"}, [A])
    assert notas[A]["descricao"] == "um homem sentado"


def test_lote_vem_com_chave_por_midia():
    notas, _ = D.notas_da_resposta(
        {A: {"descricao": "um"}, B: {"descricao": "dois"}}, [A, B])
    assert set(notas) == {A, B}


def test_chave_que_ninguem_pediu_e_DESCARTADA():
    """⛔⛔ Gravaria decupagem em cima da mídia errada, e ninguém descobriria — a descrição
    seria plausível e a busca apontaria o plano errado para sempre."""
    notas, avisos = D.notas_da_resposta(
        {A: {"descricao": "certa"}, "c" * 64: {"descricao": "intrusa"}}, [A])
    assert set(notas) == {A}
    assert any("não foi pedida" in a for a in avisos)


def test_midia_sem_resposta_vira_aviso_e_nao_erro():
    """Um lote em que o modelo esqueceu uma: as outras valem, e a esquecida volta para a
    fila na próxima rodada — porque ela continua sem nota."""
    notas, avisos = D.notas_da_resposta({A: {"descricao": "só esta"}}, [A, B])
    assert set(notas) == {A}
    assert any("sem resposta" in a for a in avisos)


def test_lote_inteiro_sem_descricao_e_falha():
    with pytest.raises(D.DecupagemFalhou):
        D.notas_da_resposta({A: {"etiquetas": ["x"]}}, [A])


def test_campo_fora_do_vocabulario_e_descartado_mas_a_prosa_fica():
    """⚠️ Descarta o CAMPO, não a decupagem: a prosa continua valendo e a busca por texto
    ainda acha. Gravar "plano bonito" em `enquadramento` sujaria o filtro para sempre."""
    notas, avisos = D.notas_da_resposta(
        {A: {"descricao": "vale", "enquadramento": "plano bonito", "momento": "noite"}},
        [A])
    assert "enquadramento" not in notas[A]
    assert notas[A]["momento"] == "noite"
    assert notas[A]["descricao"] == "vale"
    assert any("enquadramento" in a for a in avisos)


def test_sinonimo_do_modelo_e_normalizado():
    notas, _ = D.notas_da_resposta(
        {A: {"descricao": "x", "enquadramento": "primeiro plano", "camera": "fixa"}}, [A])
    assert notas[A]["enquadramento"] == "close"
    assert notas[A]["camera"] == "parada"


def test_etiquetas_tem_teto():
    """Uma lista de cem etiquetas é ruído: ela não ajuda a achar e engorda toda leitura
    do cache."""
    notas, _ = D.notas_da_resposta(
        {A: {"descricao": "x", "etiquetas": [f"e{i}" for i in range(50)]}}, [A])
    assert len(notas[A]["etiquetas"]) == 20


# ── o gasto ──────────────────────────────────────────────────────────────────

def test_o_uso_soma_as_quatro_contagens():
    """⭐ O cache CONTA: ele não é cobrado igual, mas atravessa a janela igual — e é o que
    faz a conta bater com o que o editor vê na assinatura dele."""
    uso = D._uso_do_result({
        "modelUsage": {"claude-haiku-4-5": {
            "inputTokens": 1000, "cacheReadInputTokens": 30000,
            "cacheCreationInputTokens": 5000, "outputTokens": 1500}},
        "total_cost_usd": 0.025,
    })
    assert uso["tokens"] == 37500
    assert uso["custo_usd"] == 0.025
    assert uso["modelo"] == "claude-haiku-4-5"


def test_turno_sem_uso_nao_estoura():
    assert D._uso_do_result({})["tokens"] == 0


def test_o_preco_publicado_veio_da_medicao():
    """⚠️ Estes números vão para a TELA, antes do clique. Se alguém mexer neles sem medir
    de novo, o editor decide com base em ficção."""
    assert 10_000 <= D.TOKENS_POR_MIDIA <= 25_000
    assert 0.005 <= D.CUSTO_POR_MIDIA_USD <= 0.05
    assert D.POR_TURNO >= 2, "uma mídia por turno paga o piso do CLI uma vez por mídia"


def test_lote_vazio_nao_chama_o_modelo():
    """⛔ Um turno vazio custaria os 40 mil tokens de piso para decupar nada."""
    assert D.decupar([], "http://127.0.0.1:1/mcp")["notas"] == {}


# ── a persona ────────────────────────────────────────────────────────────────

def test_a_persona_proibe_inventar_nome():
    """⚠️ "Personagem F" vem do roteiro ou da claquete, nunca do rosto. Aqui não há roteiro
    nenhum — então nome é invenção, e invenção numa decupagem contamina a busca."""
    baixa = D.PERSONA.lower()
    assert "não invente nome" in baixa


def test_a_persona_pede_expressao_e_nao_diagnostico_de_emocao():
    baixa = D.PERSONA.lower()
    assert "expressão" in baixa and "sentimento" in baixa


def test_a_persona_cabe_no_orcamento():
    """⚠️ Ela é multiplicada por CADA turno da fila. Num acervo de trezentas mídias, cada
    mil caracteres a mais aqui são cem mil tokens no total.

    ⚠️ Subiu de 2000 para 2200 em 2026-09-22, com a leitura da claquete e a regra de idioma
    (pedidos do editor). A conta: ~600 tokens num turno cujo PISO medido é ~40 mil (1,5%).
    O teto continua existindo para a próxima frase ter de pagar o lugar dela.

    ⚠️ E de 2200 para 2500 em 2026-09-23, quando a instrução da claquete pagou o lugar dela
    com medição: a AUSÊNCIA dita como caso comum, o LUGAR do valor em vez do valor, e a
    estrutura JSON inteira (sem ela, os campos não são respondidos). São ~225 caracteres,
    ~60 tokens — 0,15% do piso do turno — e valeram o eco do prompt caindo de 7 para 0 em
    8 mídias (`spikes/o_exemplo_que_o_modelo_copia.py`)."""
    assert len(D.PERSONA) < 2500


def test_cli_que_morre_na_partida_diz_o_motivo(monkeypatch, tmp_path):
    """⛔ MEDIDO no macOS (2026-09-14): com o CLI saindo na partida, cada lote falhava como
    "não respondeu em JSON" — o motivo ("unknown option") ficava no stderr sem leitor.
    Aqui o "CLI" é um script que recusa as flags e sai."""
    import stat
    import sys

    falso = tmp_path / "claude-velho"
    # ⚠️ /bin/sh, não `#!{sys.executable}`: a venv do projeto mora em "PROGRAMAS COM CLAUDE", e shebang
    #   com espaço não executa (FileNotFoundError — medido 2026-11-05 com a .venv do Mac).
    falso.write_text(
        "#!/bin/sh\necho \"error: unknown option '--restricted'\" >&2\nexit 1\n",
        encoding="utf-8")
    falso.chmod(falso.stat().st_mode | stat.S_IEXEC)
    if sys.platform == "win32":
        pytest.skip("script com shebang não executa no Windows")
    monkeypatch.setattr(D, "achar_o_cli", lambda: str(falso))
    with pytest.raises(D.DecupagemFalhou, match="unknown option"):
        D.decupar([("a" * 64, "C001")], url_do_mcp="http://127.0.0.1:1/mcp/x")
