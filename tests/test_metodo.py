"""O método do ofício — a nossa "skill", e por que ela não é a do CLI.

⭐⭐ MEDIDO em 2026-09-12 (`spikes/o_cli_carrega_skill.py`): **`--restricted` bloqueia as
skills do Claude Code**. Sem a flag a skill de teste carrega; com ela, em nenhuma das três
variantes. E `--restricted` é o ADR 0005 — sem ela a caixa de chat é um shell na estação do
cliente. Ver `docs/adr/0010-o-metodo-do-oficio.md`.

⇒ O ofício mora em `.md` versionado no repo e chega por ferramenta de leitura.
"""

from __future__ import annotations

from pathlib import Path

from cicloassist.mcp import ferramentas  # noqa: F401  (registra)
from cicloassist.mcp.ferramentas import metodo as M
from cicloassist.mcp.registro import FERRAMENTAS


# ── o que existe ─────────────────────────────────────────────────────────────

def test_todo_assunto_tem_arquivo():
    """⚠️ Faltar o arquivo é defeito de EMPACOTAMENTO, e ele não apareceria em
    desenvolvimento — só na máquina de quem instalou. Este teste é o que segura isso."""
    for assunto in M.ASSUNTOS:
        alvo = M.PASTA / f"{assunto}.md"
        assert alvo.is_file(), f"o método {assunto} não está em {alvo}"
        assert alvo.read_text(encoding="utf-8").strip()


def test_todo_arquivo_tem_assunto():
    """O contrário também: um `.md` na pasta que ninguém declara é um método que o modelo
    nunca vai ler."""
    for arquivo in M.PASTA.glob("*.md"):
        assert arquivo.stem in M.ASSUNTOS, f"{arquivo.name} não está em ASSUNTOS"


def test_o_metodo_volta_inteiro():
    r = M.consultar_o_metodo("montar-por-roteiro")
    assert "quando:" in r["metodo"]
    assert r["confianca"] == "confirmado"


def test_o_assunto_aceita_maiuscula_e_espaco():
    assert "metodo" in M.consultar_o_metodo("  Montar-Por-Roteiro ")


# ── a fronteira ──────────────────────────────────────────────────────────────

def test_assunto_inventado_devolve_a_lista():
    """⭐ Dizer o que existe é melhor que dizer "não": sem a lista, o modelo tenta outro
    nome e gasta outro turno."""
    erro = M.consultar_o_metodo("como ganhar na loteria")["erro"]
    assert "montar-por-roteiro" in erro


def test_nome_com_caminho_e_recusado():
    """⛔⛔ O assunto vira NOME DE ARQUIVO. Sem a lista fechada, um nome inventado pelo
    modelo leria qualquer `.md` do disco — e o nome chega dentro de texto que ele mesmo
    escreve (ADR 0005)."""
    for hostil in ("../../CLAUDE", "..\\..\\segredo", "/etc/passwd", "montar-por-roteiro/../x"):
        assert "erro" in M.consultar_o_metodo(hostil)


def test_e_ferramenta_de_LEITURA():
    """Consultar o método não muda nada no projeto — e uma consulta não pode acordar o
    portão no meio do trabalho."""
    assert FERRAMENTAS["consultar_o_metodo"].escreve is False


# ── o que faz a ferramenta valer a pena ──────────────────────────────────────

def test_a_descricao_diz_QUANDO_e_e_curta():
    """⭐⭐ A descrição vai em TODO turno; o corpo, só quando serve. Se a descrição crescer
    até o tamanho do método, a economia some — que é o motivo inteiro de isto existir."""
    d = FERRAMENTAS["consultar_o_metodo"].descricao
    corpo = (M.PASTA / "montar-por-roteiro.md").read_text(encoding="utf-8")
    assert len(d) < 600, "a descrição está virando o método"
    assert len(corpo) > 3 * len(d), "o método está pequeno demais para valer a chamada"
    assert "montar" in d.lower()


def test_o_metodo_carrega_o_que_foi_MEDIDO():
    """⚠️ Um método sem número é opinião. O que está aqui saiu de medição em material
    real, e o texto diz onde."""
    corpo = (M.PASTA / "montar-por-roteiro.md").read_text(encoding="utf-8")
    assert "MEDIDO" in corpo
    assert "230 ms" in corpo
    assert "entrada_do_corte" in corpo and "saida_do_corte" in corpo


def test_o_metodo_tem_o_que_NUNCA_fazer():
    """⭐ É a parte que mais salva, e a que o modelo não deduz sozinho — foi o que o estudo
    das skills do Jumper mostrou."""
    corpo = (M.PASTA / "montar-por-roteiro.md").read_text(encoding="utf-8")
    assert corpo.lower().count("nunca") >= 2


def test_a_persona_manda_consultar():
    """⚠️⚠️ O preço de não usar a skill do CLI é o DISPARO: a dele carrega sozinha pela
    descrição, a nossa depende de o modelo lembrar. A persona é o que lembra."""
    from cicloassist.motor.claude import PERSONA

    assert "consultar_o_metodo" in PERSONA


def test_a_persona_nao_carrega_mais_a_regra_de_corte():
    """⭐ O ponto de mudar: a regra de montagem saiu da persona, que vai em todo turno,
    para o método, que vai quando serve."""
    from cicloassist.motor.claude import PERSONA

    assert "entrada_do_corte" not in PERSONA
    # 2200 → 2700 em 2026-10-31: entrou o parágrafo do ASSUNTO (o chat é do trabalho;
    # o editor paga cada resposta). O teto continua sendo contra a regra de ofício
    # voltar para cá — ~500 caracteres são ~130 tokens por turno.
    # 2700 → 2900 em 2026-11-03: o parágrafo do pedido de várias etapas (o chat faz passo a
    #   passo; o fluxo é da aba Fluxos — `docs/plano/2026-11-03-chat-e-fluxos.md`).
    assert len(PERSONA) < 2900


def test_a_persona_limita_o_assunto_ao_trabalho():
    """⭐ Autor, 2026-10-31: "como fazer um bolo" não é do chat; um erro do Media
    Composer é, e aí o modelo ajuda com o que sabe e OFERECE consertar se uma
    ferramenta alcançar. A recusa é curta e diz com o que pode ajudar."""
    from cicloassist.motor.claude import PERSONA, persona

    baixa = PERSONA.lower()
    assert "pós-produção" in baixa
    assert "recuse" in baixa and "ofereça" in baixa
    # O Premiere troca nomes de programa na persona; o parágrafo tem de sobreviver.
    assert "Seu assunto é o trabalho" in persona("premiere")
