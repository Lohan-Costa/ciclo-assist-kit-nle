"""A decupagem: o vocabulário do que o modelo vê, e a busca sobre o que ele escreveu.

⭐ A decupagem é a camada RICA do produto — enquadramento, figurino, cenário, luz, câmera,
o que a pessoa faz, e até a função do plano na cena. O vetor visual responde "parecido com
este quadro"; só ela responde *"onde tem close noturno no consultório?"*.

⛔ E ela precisa de campos fechados porque **prosa não filtra**: `close`, `plano fechado` e
`primeiro plano` são a mesma coisa na boca de quem monta, e três strings diferentes para
quem procura.
"""

from __future__ import annotations

import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import decupagem as D

UMA = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.64cedc20.1dc80000.060e2b34.7f7f2a80"
OUTRA = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.6505f172.1c710000.060e2b34.7f7f2a80"


def anotar(raiz, umid, **nota):
    midia = C.Midia(umid, raiz_do_cache=raiz)
    midia.anotar_fonte({"master": nota.pop("master", "A001_C003")})
    midia.anotar({"confianca": "inferido", "fonte": "visual", **nota})
    return midia


# ── o vocabulário ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("escrito,esperado", [
    ("close", "close"),
    ("CLOSE", "close"),
    ("primeiro plano", "close"),
    ("plano fechado", "close"),
    ("PP", "close"),
    ("plano geral", "geral"),
    ("wide", "geral"),
    ("super close", "detalhe"),
    ("médio", "médio"),
    ("medio", "médio"),
])
def test_sinonimos_do_enquadramento_caem_no_mesmo_termo(escrito, esperado):
    """⭐ Sem isto, cada anotação gastaria um turno do editor levando recusa por sinônimo —
    e todos estes são o mesmo plano com outro nome na boca de quem monta."""
    assert D.normalizar("enquadramento", escrito, D.ENQUADRAMENTOS) == esperado


@pytest.mark.parametrize("escrito,esperado", [
    ("plongee", "plongée"),
    ("contra-plongee", "contra-plongée"),
    ("contra plongée", "contra-plongée"),
])
def test_acento_nao_atrapalha(escrito, esperado):
    assert D.normalizar("angulo", escrito, D.ANGULOS) == esperado


@pytest.mark.parametrize("escrito,esperado", [
    ("fixa", "parada"), ("tripé", "parada"), ("handheld", "mão"), ("dolly", "travelling"),
])
def test_o_que_a_camera_faz(escrito, esperado):
    assert D.normalizar("camera", escrito, D.CAMERAS) == esperado


def test_valor_inventado_e_recusado_com_a_lista_na_mensagem():
    """⛔ Um campo fechado que aceita qualquer coisa não filtra nada — e o editor só
    descobriria isso quando a busca não achasse o que ele sabe que existe."""
    with pytest.raises(D.ValorForaDoVocabulario) as erro:
        D.normalizar("enquadramento", "plano bonito", D.ENQUADRAMENTOS)
    assert "close" in str(erro.value) and "geral" in str(erro.value)


def test_vazio_continua_vazio():
    """O campo é opcional: não preencher é diferente de preencher errado."""
    assert D.normalizar("camera", "", D.CAMERAS) == ""
    assert D.normalizar_campos({"camera": "", "local": "interior"}) == {"local": "interior"}


def test_a_lista_de_enquadramento_e_curta_de_proposito():
    """⚠️ Cada termo a mais é um termo que o modelo escolhe errado. Se alguém dobrar esta
    lista, que seja com medida na mão."""
    assert len(D.ENQUADRAMENTOS) <= 8


# ── a busca ──────────────────────────────────────────────────────────────────

def test_acha_pelo_texto_da_descricao(tmp_path):
    anotar(tmp_path, UMA, trecho="C07_P03-T001",
           descricao="Close de Personagem F no consultório, abajur aceso ao fundo.")

    (achado,) = D.procurar(["abajur"], raiz=tmp_path)
    assert achado["take"] == "C07_P03-T001"
    assert "abajur" in achado["trecho_da_descricao"]


def test_acha_pela_etiqueta(tmp_path):
    anotar(tmp_path, UMA, trecho="T1", descricao="uma mulher sentada",
           etiquetas=["blusa vermelha", "escuta"])

    assert len(D.procurar(["escuta"], raiz=tmp_path)) == 1


def test_acento_nao_atrapalha_a_busca(tmp_path):
    """⚠️ Quem digita "consultorio" tem de achar "consultório" — ninguém acentua enquanto
    monta."""
    anotar(tmp_path, UMA, trecho="T1", descricao="Sentada no consultório dela, à noite.")

    assert len(D.procurar(["consultorio"], raiz=tmp_path)) == 1


def test_os_termos_SOMAM(tmp_path):
    """⭐ E, não OU. Quem procura "close consultório" quer as duas coisas juntas; devolver
    o que tem qualquer uma entregaria o acervo inteiro."""
    anotar(tmp_path, UMA, trecho="T1", descricao="Close de Personagem F no consultório.")
    anotar(tmp_path, OUTRA, trecho="T2", descricao="Plano geral do consultório vazio.")

    assert len(D.procurar(["consultorio"], raiz=tmp_path)) == 2
    (so_um,) = D.procurar(["consultorio", "close"], raiz=tmp_path)
    assert so_um["take"] == "T1"


def test_filtra_pelo_campo_fechado(tmp_path):
    anotar(tmp_path, UMA, trecho="T1", descricao="ela", enquadramento="close",
           momento="noite")
    anotar(tmp_path, OUTRA, trecho="T2", descricao="a rua", enquadramento="geral",
           momento="dia")

    (achado,) = D.procurar(campos={"enquadramento": "close"}, raiz=tmp_path)
    assert achado["take"] == "T1"
    assert achado["momento"] == "noite"


def test_nota_SEM_o_campo_cai_para_o_texto(tmp_path):
    """⭐⭐ Os campos nasceram em 2026-09-11, e toda decupagem escrita antes diz "Close de
    Personagem F" na prosa sem ter `enquadramento`. Um filtro que exigisse o campo devolveria
    ZERO no dia em que nasceu — com o material descrito bem ali."""
    anotar(tmp_path, UMA, trecho="antiga",
           descricao="Close de Personagem F, blusa vermelha, noite.")

    assert len(D.procurar(campos={"enquadramento": "close"}, raiz=tmp_path)) == 1
    assert len(D.procurar(campos={"enquadramento": "geral"}, raiz=tmp_path)) == 0


def test_o_campo_gravado_GANHA_do_texto(tmp_path):
    """⚠️ E o contrário também: uma nota que DIZ `enquadramento: geral` não pode ser
    devolvida como close só porque a palavra "close" aparece na frase ("mais aberto que o
    close do T001")."""
    anotar(tmp_path, UMA, trecho="T1", enquadramento="geral",
           descricao="Mais aberto que o close do T001.")

    assert D.procurar(campos={"enquadramento": "close"}, raiz=tmp_path) == []
    assert len(D.procurar(campos={"enquadramento": "geral"}, raiz=tmp_path)) == 1


def test_sem_nada_no_cache_nao_estoura(tmp_path):
    assert D.procurar(["qualquer coisa"], raiz=tmp_path) == []


def test_midia_sem_nota_nao_entra(tmp_path):
    C.Midia(UMA, raiz_do_cache=tmp_path).guardar_quadro(1, b"\xff\xd8x")
    assert D.procurar(["x"], raiz=tmp_path) == []


def test_o_resultado_leva_procedencia_e_posicao(tmp_path):
    """Item sem procedência é bug, não item — e sem `inicio_frames` o take achado não vira
    corte nenhum."""
    anotar(tmp_path, UMA, trecho="T1", descricao="close", cena="C7", plano="P3",
           inicio_frames=120, duracao_frames=5267)

    (achado,) = D.procurar(["close"], raiz=tmp_path)
    assert achado["confianca"] == "inferido" and achado["fonte"] == "visual"
    assert achado["inicio_frames"] == 120 and achado["duracao_frames"] == 5267
    assert achado["cena"] == "C7" and achado["plano"] == "P3"


def test_o_trecho_devolvido_e_curto(tmp_path):
    """⚠️ A descrição de um take completo tem parágrafos. Devolver todas inteiras encheria
    a resposta do modelo com mil palavras que ninguém pediu."""
    anotar(tmp_path, UMA, trecho="T1", descricao="palavra " * 300 + "abajur")

    (achado,) = D.procurar(["abajur"], raiz=tmp_path)
    assert len(achado["trecho_da_descricao"]) < 200


def test_quantas_decupadas_conta_o_alcance_da_busca(tmp_path):
    """⭐ Vai junto de toda resposta: sem isto, "não achei" se confunde com "não existe"."""
    anotar(tmp_path, UMA, trecho="T1", descricao="x")
    C.Midia(OUTRA, raiz_do_cache=tmp_path).guardar_quadro(1, b"\xff\xd8x")

    assert D.quantas_decupadas(tmp_path) == (1, 2)


def test_uma_peca_em_trechos_nao_ocupa_a_lista_inteira(tmp_path):
    """⭐⭐ Uma peça montada decupada em trechos tem uma nota por PLANO — 600 numa peça de
    meia hora. Sem teto, ela preencheria sozinha a resposta e empurraria para fora
    justamente o que responde *"onde MAIS?"*. É a mesma régua de `planos_parecidos`.

    ⛔ E o que ficou de fora é CONTADO: sem a frase, o modelo leria "achei 3 nesta peça"
    como "só há 3", e contaria isso ao editor com a confiança de quem varreu tudo.
    """
    peca = C.Midia(UMA, raiz_do_cache=tmp_path)
    peca.anotar_fonte({"master": "PROMO"})
    for i in range(9):
        peca.anotar({"trecho": f"PROMO · trecho {i * 100}", "escopo": "trecho",
                     "inicio_frames": i * 100, "descricao": "uma porta se abre",
                     "confianca": "inferido", "fonte": "visual"})
    anotar(tmp_path, OUTRA, trecho="OUTRO TAKE", master="B002_C001",
           descricao="alguém na porta")

    cortes: dict[str, int] = {}
    achados = D.procurar(["porta"], raiz=tmp_path, contador=cortes)

    da_peca = [a for a in achados if a["midia"] == "PROMO"]
    assert len(da_peca) == D.NOTAS_POR_MIDIA
    assert cortes["por_midia"] == 9 - D.NOTAS_POR_MIDIA
    # ⭐ E a outra mídia continua na lista: o teto é por mídia, não da resposta.
    assert any(a["midia"] != "PROMO" for a in achados)
    # ⚠️ Em ordem de tempo dentro da mídia — cortando, o que fica é o começo do material.
    assert [a["inicio_frames"] for a in da_peca] == [0, 100, 200]


# ── a ferramenta ─────────────────────────────────────────────────────────────

def test_a_busca_e_de_leitura_e_esta_registrada():
    from cicloassist.mcp import ferramentas  # noqa: F401
    from cicloassist.mcp.registro import FERRAMENTAS

    assert FERRAMENTAS["procurar_no_material"].escreve is False


def test_a_ferramenta_exige_o_que_procurar():
    from cicloassist.mcp.ferramentas.mapa import procurar_no_material

    assert "erro" in procurar_no_material()


def test_a_ferramenta_recusa_campo_fora_do_vocabulario():
    from cicloassist.mcp.ferramentas.mapa import procurar_no_material

    r = procurar_no_material(enquadramento="plano bonito")
    assert "erro" in r and "close" in r["erro"]


def test_a_descricao_da_ferramenta_avisa_do_alcance():
    """⚠️⚠️ O modelo PRECISA dizer ao editor que a busca só cobre o que foi decupado.
    Sem esse aviso, "não achei" vira "seu material não tem isso" — e o editor acredita."""
    from cicloassist.mcp.registro import FERRAMENTAS

    d = FERRAMENTAS["procurar_no_material"].descricao.lower()
    assert "já olhou" in d or "já foi decupado" in d
    assert "decupadas" in d or "decupado" in d


def test_anotar_recusa_enquadramento_inventado():
    """A anotação inteira volta como erro, com a lista — é um turno a mais e um campo
    limpo, contra um campo sujo para sempre."""
    from cicloassist.mcp.ferramentas.mapa import anotar_o_que_vi

    r = anotar_o_que_vi(bin="x.avb", item="y", descricao="z",
                        enquadramento="plano bonito")
    assert "erro" in r and "detalhe" in r["erro"]
