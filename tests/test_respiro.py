"""O respiro do corte — por que o ponto de corte não é o tempo do ASR.

⭐⭐ Parecer de campo, 2026-09-11: *"a primeira fala do Personagem G é colada na entrada, quase
cortando a primeira sílaba; e 'sobe comigo' vira 'sobe co…'"*.

MEDIDO (`spikes/o_respiro_do_corte.py`), som direto real, nas falas que ele apontou:

```
voz ANTES do que o ASR diz    mediana   10 ms   pior  300 ms
voz DEPOIS do que o ASR diz   mediana  230 ms   pior  350 ms   ← 5,5 frames a 24 fps
```

⇒ **São dois problemas diferentes.** A cauda cortada é erro de MEDIDA (o ASR fecha cedo).
A entrada colada NÃO é: o ASR acerta o ataque com 10 ms, e cortar rente é escolha de
montagem ruim — não sobra ar, e a sílaba parece decepada estando inteira.
"""

from __future__ import annotations

from cicloassist.midia import asr as A


def fala(inicio, fim, texto="x"):
    return {"inicio": inicio, "fim": fim, "texto": texto}


# ── o que o respiro faz ──────────────────────────────────────────────────────

def test_abre_antes_e_depois():
    (f,) = A.com_respiro([fala(10.0, 12.0)], piso_s=0, teto_s=60)
    assert f["corte_inicio"] < 10.0
    assert f["corte_fim"] > 12.0


def test_a_cauda_ganha_mais_que_a_entrada():
    """⭐ Assimétrico de propósito, e a medida é que manda: o ASR acerta o ataque (10 ms)
    e erra o fim (230 ms). Um respiro simétrico consertaria metade do problema e roubaria
    tempo do vizinho na outra."""
    assert A.RESPIRO_DEPOIS_S > A.RESPIRO_ANTES_S


def test_o_dado_cru_continua_la():
    """`inicio` e `fim` são o que o reconhecedor mediu. Sobrescrevê-los apagaria a
    diferença entre o que foi MEDIDO e o que foi DECIDIDO."""
    (f,) = A.com_respiro([fala(10.0, 12.0)], piso_s=0, teto_s=60)
    assert f["inicio"] == 10.0 and f["fim"] == 12.0


# ── os limites, que é onde ele erraria feio ──────────────────────────────────

def test_nao_invade_a_fala_seguinte():
    """⛔ Trazer a cauda do outro ator para dentro do corte é pior que cortar rente: o
    editor ouve a voz errada entrando no fim do plano."""
    a, b = A.com_respiro([fala(10.0, 12.0), fala(12.2, 14.0)], piso_s=0, teto_s=60)
    assert a["corte_fim"] <= 12.2 - A.VAO_MINIMO_S + 1e-9
    assert b["corte_inicio"] >= 12.0 + A.VAO_MINIMO_S - 1e-9


def test_com_falas_MUITO_coladas_nao_corta_dentro_da_palavra():
    """⚠️ Se o vão pedido não cabe, o respiro vira ZERO — nunca negativo. Sem esta trava,
    duas falas a 20 ms de distância empurrariam o início para DENTRO da própria fala, e o
    corte decepava a palavra de verdade."""
    a, b = A.com_respiro([fala(10.0, 12.0), fala(12.02, 13.0)], piso_s=0, teto_s=60)
    assert a["corte_fim"] >= 12.0
    assert b["corte_inicio"] <= 12.02


def test_nao_passa_do_comeco_do_take():
    (f,) = A.com_respiro([fala(0.05, 2.0)], piso_s=0.0, teto_s=60)
    assert f["corte_inicio"] >= 0.0


def test_nao_passa_do_fim_do_take():
    (f,) = A.com_respiro([fala(58.0, 59.9)], piso_s=0, teto_s=60.0)
    assert f["corte_fim"] <= 60.0


def test_a_janela_do_take_limita_a_primeira_e_a_ultima():
    """A primeira fala não pode abrir antes do in-point do subclipe, nem a última depois
    do out — senão o corte pede material que o take não tem."""
    falas = A.com_respiro([fala(10.0, 11.0), fala(20.0, 21.0)], piso_s=9.95, teto_s=21.1)
    assert falas[0]["corte_inicio"] >= 9.95
    assert falas[-1]["corte_fim"] <= 21.1


def test_lista_vazia_nao_estoura():
    assert A.com_respiro([], piso_s=0, teto_s=10) == []


# ── o que a ferramenta entrega ───────────────────────────────────────────────

def test_a_ferramenta_diz_QUAL_campo_usar():
    """⚠️⚠️ O modelo lê a resposta, não o nosso código. Sem dizer em palavras qual campo é
    o ponto de corte, ele usa `inicio_no_take` — que foi exatamente o que fez o editor
    ouvir a última sílaba sumir."""
    from cicloassist.mcp.registro import FERRAMENTAS
    from cicloassist.mcp import ferramentas  # noqa: F401

    d = FERRAMENTAS["transcrever"].descricao
    assert "entrada_do_corte" in d and "saida_do_corte" in d
    # ⭐ E os frames, desde 2026-09-12: são eles que vão direto para `montar_corte`, e um
    #   campo que o modelo não sabe que existe é um campo que ele recalcula errado.
    assert "inicio_no_take_frames" in d and "duracao_frames" in d


def test_o_respiro_cabe_num_corte_curto():
    """⚠️ Uma fala de meio segundo entre outras duas não pode virar um corte de dois
    segundos por causa do respiro."""
    falas = A.com_respiro(
        [fala(10.0, 10.5), fala(10.8, 11.3), fala(11.6, 12.0)], piso_s=0, teto_s=60)
    duracoes = [f["corte_fim"] - f["corte_inicio"] for f in falas]
    assert all(d < 1.0 for d in duracoes), duracoes


# ── juntar falas coladas ─────────────────────────────────────────────────────

def test_o_vao_ate_a_proxima_e_devolvido():
    """⭐ Duas falas seguidas do mesmo take separadas por pouco devem virar UM corte: a
    pausa é atuação, e a ambiência que some no meio denuncia o corte. Quem decide é quem
    monta — o dado é nosso.

    Corroborado por fora: as skills do Jumper mandam *"if consecutive selected segments
    from the same source have only a short gap, use one continuous source clip"*.
    """
    a, b = A.com_respiro([fala(10.0, 11.0), fala(11.4, 12.0)], piso_s=0, teto_s=60)
    assert a["vao_ate_a_proxima"] == 0.4
    assert b["vao_ate_a_proxima"] is None      # a última não tem próxima


def test_o_limite_de_juntar_e_de_ofício_e_esta_escrito():
    assert 0.5 <= A.VAO_DE_JUNTAR_S <= 2.0


def test_a_resposta_ensina_a_juntar_e_a_nao_emendar():
    """⚠️⚠️ A regra vai na RESPOSTA, não só na descrição da ferramenta: é no momento de
    usar o dado que ela precisa estar na frente do modelo."""
    from cicloassist.mcp.ferramentas.fala import COMO_CORTAR

    baixa = COMO_CORTAR.lower()
    assert "vao_ate_a_proxima" in baixa
    assert "contínuo" in baixa
    assert "nunca emende" in baixa


# ── a borda que o ASR não mediu ──────────────────────────────────────────────

def test_a_borda_ENCADEADA_nao_rouba_o_respiro():
    """⛔⛔ MEDIDO em 2026-09-12: 169 de 715 bordas do cache (23,6%) são exatamente
    0,000 s — o faster-whisper encadeia os segmentos. Acreditar nelas zerava o respiro de
    176 de 727 falas, e era assim que "Sobe comigo." virava "sobe co…" na tela."""
    falas = A.com_respiro([fala(10.0, 12.0), fala(12.0, 14.0)], piso_s=0, teto_s=60)
    assert falas[0]["corte_fim"] == 12.0 + A.RESPIRO_DEPOIS_S


def test_o_silencio_MEDIDO_continua_protegendo_o_vizinho():
    """⛔ Quando houve silêncio de verdade, o respiro segue sem invadir: trazer a cauda do
    outro ator para dentro do corte é pior que cortar rente."""
    falas = A.com_respiro([fala(10.0, 12.0), fala(12.2, 14.0)], piso_s=0, teto_s=60)
    assert falas[0]["corte_fim"] == 12.2 - A.VAO_MINIMO_S


def test_a_ultima_fala_nao_depende_de_vizinho():
    falas = A.com_respiro([fala(10.0, 12.0)], piso_s=0, teto_s=60)
    assert falas[0]["corte_fim"] == 12.0 + A.RESPIRO_DEPOIS_S
