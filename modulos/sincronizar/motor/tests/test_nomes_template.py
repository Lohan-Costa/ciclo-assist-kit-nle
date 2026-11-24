"""O motor de template: `padrão + campos → texto`.

⭐ Este módulo não sabe o que é Avid, o que é claquete nem o que é Preparar. É essa
ignorância que faz dele o pedaço reusável — o Renomear é só o primeiro consumidor.

⚠️⚠️ O caso que decide o desenho inteiro é `%shoot_T%take`, que veio do exemplo do
próprio autor. `_` é caractere válido de nome de campo (as colunas do Avid normalizam
`Shoot Date` → `shoot_date`), então um casamento guloso engoliria `shoot_t` e o `_T`
literal sumiria — silenciosamente, com um nome plausível na tela. Ver
`test_o_token_RECUA_ate_o_campo_que_existe`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from nomes import template as T

# O catálogo de um clipe de Projeto B, medido em `SOM DIRETO.avb`.
CAMPOS_PRODF = {
    "name": "24-1T01.WAV",
    "scene": "24-1",
    "take": "01",
    "tapeid": "24-1T01.WAV",
    "shoot_date": "2026-06-29 12:08:52",
    "production": "MAE_DO_OURO",
    "trk3": "BOOM 1",
    "circled": "no",
    # os derivados
    "cena": "24",
    "plano": "01",
    "take2": "01",
}


# ── o básico ─────────────────────────────────────────────────────────────────

def test_texto_sem_wildcard_sai_igual():
    assert T.render("SEM NADA AQUI", CAMPOS_PRODF) == "SEM NADA AQUI"


def test_um_campo_e_substituido():
    assert T.render("%scene", CAMPOS_PRODF) == "24-1"


def test_campos_e_literais_se_misturam():
    assert T.render("C%cena_P%plano_T%take2", CAMPOS_PRODF) == "C24_P01_T01"


def test_dois_por_cento_viram_um_literal():
    """`%%` é a válvula de escape. Sem ela não há como pôr um `%` no nome."""
    assert T.render("100%% BOM", CAMPOS_PRODF) == "100% BOM"


def test_dois_por_cento_seguido_de_palavra_NAO_vira_campo():
    """⚠️ `%%scene` é o `%` literal e a palavra `scene`, não o campo."""
    assert T.render("%%scene", CAMPOS_PRODF) == "%scene"


def test_o_mesmo_campo_pode_repetir():
    assert T.render("%take-%take", CAMPOS_PRODF) == "01-01"


def test_campos_colados_sem_separador():
    assert T.render("%cena%take2", CAMPOS_PRODF) == "2401"


def test_acentuacao_no_literal_sobrevive():
    assert T.render("CENA %cena — ÁUDIO", CAMPOS_PRODF) == "CENA 24 — ÁUDIO"


# ── ⚠️⚠️ o recuo: o coração do desenho ───────────────────────────────────────

def test_o_token_RECUA_ate_o_campo_que_existe():
    """⚠️⚠️ `%shoot_T%take` — o exemplo do autor, e a armadilha.

    `_` é caractere de nome de campo, então o casamento guloso lê `shoot_t`, que não
    existe. Em vez de acusar erro (o autor QUER que isto funcione) ou de engolir calado,
    o token recua até o maior campo do catálogo que seja prefixo — `shoot` — e o que
    sobra (`_T`) vira literal.
    """
    campos = dict(CAMPOS_PRODF, shoot="01")
    assert T.render("C%scene-P%shoot_T%take", campos) == "C24-1-P01_T01"


def test_o_campo_exato_ganha_de_qualquer_recuo():
    """Com `shoot` e `shoot_date` no catálogo, `%shoot_date` é `shoot_date` — e não
    `shoot` seguido do literal `_date`. Recuar aqui daria a data errada."""
    campos = dict(CAMPOS_PRODF, shoot="01")
    assert T.render("%shoot_date", campos) == "2026-06-29 12:08:52"


def test_o_recuo_prefere_o_campo_MAIS_LONGO():
    """⚠️⚠️ A DIREÇÃO do laço de recuo, e ela precisa de um token que NÃO esteja no
    catálogo — senão o atalho do casamento exato responde e o laço nunca roda.

    Este teste nasceu de mutação: o primeiro que se escreveu para esta regra usava
    `%shoot_date`, que está no catálogo, e por isso **sobreviveu ao mutante que
    invertia o laço**. Era decoração. `%shoot_date_x` não está no catálogo e tem DUAS
    fronteiras válidas — `shoot_date` e `shoot` —, então só ele mede a direção.
    """
    campos = dict(CAMPOS_PRODF, shoot="01")
    tokens = T.analisar("%shoot_date_x", campos)
    assert tokens[0].campo == "shoot_date", "recuou longe demais"
    assert tokens[0].cauda == "_x"
    assert T.render("%shoot_date_x", campos) == "2026-06-29 12:08:52_x"


def test_o_recuo_fica_VISIVEL_na_analise():
    """⚠️ Recuar é uma decisão do motor sobre o que o editor digitou, e decisão calada
    é o que este projeto não aceita. `analisar` devolve a cauda que virou literal para
    o painel poder mostrá-la."""
    campos = dict(CAMPOS_PRODF, shoot="01")
    tokens = T.analisar("%shoot_T", campos)
    assert len(tokens) == 1
    assert tokens[0].campo == "shoot"
    assert tokens[0].cauda == "_T", "o painel precisa saber o que virou literal"
    # ⚠️⚠️ O intervalo tem de PARAR no campo, e não no fim do token guloso — senão o
    # painel destaca o `_T` junto, dizendo ao editor que o literal dele faz parte do
    # campo. Achado por mutação: sem esta linha, o mutante que ignora o recuo no `fim`
    # sobrevive.
    assert (tokens[0].inicio, tokens[0].fim) == (0, len("%shoot"))
    assert tokens[0].bruto == "%shoot"


def test_sem_recuo_possivel_o_campo_e_DESCONHECIDO():
    """`%xyz` não é prefixo de campo nenhum: erro, não literal."""
    tokens = T.analisar("%xyz", CAMPOS_PRODF)
    assert tokens[0].campo is None
    assert tokens[0].bruto == "%xyz"


def test_o_caso_QUE_NENHUM_RECUO_SALVA():
    """⛔ `C%cenaP%plano` — achado pelo autor usando, 2026-09-06.

    `cenaP` não tem `_`, então não há fronteira para recuar, e adivinhar onde o campo
    termina no meio de um literal colado seria chute. Este teste fixa o comportamento
    que MOTIVOU a tag fechada: o token guloso engole o `P` e o campo não existe.
    """
    campos = {"cena": "25", "plano": "6"}
    tokens = T.analisar("C%cenaP%plano", campos)
    assert tokens[0].bruto == "%cenaP"
    assert tokens[0].campo is None, "não há como saber que o `P` era literal"
    with pytest.raises(T.PadraoInvalido):
        T.render("C%cenaP%plano", campos)


# ── a tag FECHADA ────────────────────────────────────────────────────────────

def test_a_tag_fechada_resolve_o_campo_COLADO_no_literal():
    """⭐⭐ O motivo de a forma existir: `%{cena}` diz onde o campo termina, então não
    sobra pergunta para o motor responder."""
    campos = {"cena": "25", "plano": "6", "take": "01"}
    assert T.render("C%{cena}P%{plano}-T%{take}", campos) == "C25P6-T01"


def test_a_tag_fechada_NAO_recua():
    """⚠️ Recuo é para quem digitou sem delimitar. Quem fechou a tag já disse onde o
    campo acaba — recuar aqui seria o motor discordando de uma declaração explícita, e
    `%{shoot_t}` viraria `%shoot` + `_t` sem ninguém pedir."""
    campos = dict(CAMPOS_PRODF, shoot="01")
    tokens = T.analisar("%{shoot_t}", campos)
    assert tokens[0].campo is None
    assert tokens[0].cauda == "", "a tag fechada não devolve cauda ao literal"


def test_a_tag_fechada_marca_o_intervalo_INTEIRO_com_as_chaves():
    """⚠️ O painel pinta pelo intervalo. Se ele parasse no nome, a caixinha sairia sem
    as bordas — e o editor veria uma tag pela metade."""
    tokens = T.analisar("C%{cena}P", {"cena": "25"})
    assert (tokens[0].inicio, tokens[0].fim) == (1, 1 + len("%{cena}"))
    assert tokens[0].bruto == "%{cena}"


def test_a_tag_ABERTA_e_desconhecida_e_para_no_identificador():
    """⚠️⚠️ Consome só `%{nome`, não o resto do padrão.

    Enquanto o editor digita, meio padrão é o estado normal. Se a tag aberta engolisse
    tudo o que vem depois, o vermelho cobriria um padrão inteiro que está correto — e o
    autocomplete perderia o token onde a mão está.
    """
    tokens = T.analisar("%{cena", {"cena": "25"})
    assert tokens[0].campo is None and tokens[0].bruto == "%{cena"
    tokens = T.analisar("%{ce x%{plano}", {"cena": "25", "plano": "6"})
    assert tokens[0].bruto == "%{ce"
    assert tokens[1].campo == "plano", "o resto do padrão continua analisável"


def test_a_tag_fechada_VAZIA_e_desconhecida():
    """`%{}` não é campo nenhum, e fingir que é literal esconderia um engano."""
    tokens = T.analisar("%{}", CAMPOS_PRODF)
    assert tokens and tokens[0].campo is None


def test_a_tag_fechada_nao_distingue_maiuscula():
    assert T.render("%{SCENE}", CAMPOS_PRODF) == "24-1"


def test_o_escape_ganha_da_tag_fechada():
    """⚠️ `%%{cena}` é um `%` literal seguido de `{cena}` — quem escapou o `%` está
    escrevendo texto, não abrindo tag."""
    assert T.render("%%{cena}", CAMPOS_PRODF) == "%{cena}"
    assert T.analisar("%%{cena}", CAMPOS_PRODF) == []


def test_as_duas_formas_convivem_no_mesmo_padrao():
    """⚠️ O `%campo` solto não some: os padrões que já existem continuam valendo, e
    quem digita rápido não é obrigado a fechar."""
    campos = {"cena": "25", "take": "01"}
    assert T.render("%cena-T%{take}", campos) == "25-T01"
    assert T.campos_usados("%cena-T%{take}", campos) == ["cena", "take"]


def test_o_recuo_so_acontece_na_fronteira_do_UNDERSCORE():
    """⚠️⚠️ A regra que impede o recuo de virar adivinhação.

    `scene` existe e `scenex` começa com ele — mas `scenex` é **erro de digitação**, não
    composição. Sem a fronteira em `_`, o motor devolveria `24-1` + literal `x` e o
    editor levaria um lote inteiro com um `x` pendurado, sem nunca ver vermelho.
    """
    tokens = T.analisar("%scenex", CAMPOS_PRODF)
    assert tokens[0].campo is None, "recuou onde não havia fronteira"
    with pytest.raises(T.PadraoInvalido):
        T.render("%scenex", CAMPOS_PRODF)


# ── o que bloqueia e o que só avisa ──────────────────────────────────────────

def test_campo_desconhecido_LEVANTA_em_vez_de_render_vazio():
    """⚠️⚠️ Render nunca inventa. Um campo que não existe é erro do padrão, e render
    tem de recusar — se devolvesse vazio, um `%xyz` esquecido produziria um lote de
    nomes truncados que só o olho pegaria, clipe por clipe."""
    with pytest.raises(T.PadraoInvalido):
        T.render("C%xyz_T%take", CAMPOS_PRODF)


def test_campo_CONHECIDO_e_vazio_renderiza_vazio_sem_levantar():
    """⭐ A distinção do §11, aqui: chave AUSENTE é erro; chave PRESENTE e vazia é
    fato do material. No Projeto C não há cena, e travar todo padrão com `%cena` tornaria a
    ferramenta inútil justamente no produto que mais precisa dela."""
    campos = dict(CAMPOS_PRODF, cena="")
    assert T.render("C%cena_T%take", campos) == "C_T01"


def test_valor_ZERO_nao_some_do_nome():
    """⚠️⚠️ `0` é valor, não ausência.

    Achado por mutação: `str(v) or ""` transforma `0` em `""`, e um take 0, uma duração
    0 ou um contador zerado desapareceriam do nome sem deixar rastro — nome plausível,
    dado perdido, ninguém avisado. Só `None` vira vazio.
    """
    campos = dict(CAMPOS_PRODF, contador=0, vazio=None)
    assert T.render("T%contador", campos) == "T0"
    assert T.render("T%vazio", campos) == "T"


def test_validar_aponta_ONDE_o_campo_invalido_esta():
    """O painel pinta de vermelho, então precisa das posições, não de um booleano.

    ⚠️⚠️ O vermelho cobre o token GULOSO INTEIRO — `%xyz_T`, e não só `%xyz`. Quando
    o campo resolve, a fronteira é conhecida e a cauda volta a ser literal (ver
    `test_o_recuo_fica_VISIVEL_na_analise`); quando NÃO resolve, não há como saber onde
    o campo terminaria. Pintar só `%xyz` insinuaria que `xyz` é um nome completo e que
    o problema é outro — e mandaria o editor procurar no lugar errado.
    """
    ruins = T.validar("C%cena_%xyz_T%take", CAMPOS_PRODF)
    assert len(ruins) == 1
    assert ruins[0].bruto == "%xyz_T"
    assert ruins[0].inicio == len("C%cena_")
    assert ruins[0].fim == len("C%cena_%xyz_T")
    assert ruins[0].campo is None


def test_validar_com_tudo_certo_devolve_lista_vazia():
    assert T.validar("C%cena_P%plano", CAMPOS_PRODF) == []


def test_por_cento_solto_no_fim_e_invalido():
    """⚠️ O autor pediu explicitamente: `%` sem valor compatível bloqueia."""
    ruins = T.validar("NOME%", CAMPOS_PRODF)
    assert len(ruins) == 1
    assert ruins[0].campo is None


def test_por_cento_seguido_de_nao_letra_e_invalido():
    for padrao in ("%-x", "% ", "%1abc"):
        ruins = T.validar(padrao, CAMPOS_PRODF)
        assert ruins, f"{padrao!r} deveria ser recusado e não foi"


# ── nomes de campo ───────────────────────────────────────────────────────────

def test_o_campo_nao_distingue_maiuscula():
    assert T.render("%SCENE", CAMPOS_PRODF) == "24-1"
    assert T.render("%Cena", CAMPOS_PRODF) == "24"


def test_normalizar_traduz_coluna_do_avid_para_campo():
    """⭐ É este contrato que faz `campos.py` e o template se entenderem: a coluna do
    Avid tem espaço e maiúscula, o wildcard não pode ter nem um nem outro."""
    assert T.normalizar("Shoot Date") == "shoot_date"
    assert T.normalizar("Soundroll TC Rate") == "soundroll_tc_rate"
    assert T.normalizar("TRK1") == "trk1"
    assert T.normalizar("Scene") == "scene"
    assert T.normalizar("  Name  ") == "name"


def test_normalizar_TRANSLITERA_em_vez_de_descartar_o_acento():
    """⭐ `Áudio` vira `audio`, não `_udio`.

    Descartar o acento como caractere inválido produziria um campo tecnicamente
    digitável e humanamente irreconhecível — e uma coluna custom em português é o caso
    comum, não o exótico. O `Nº` da mesma coluna vira `no` pela mesma passagem.
    """
    assert T.normalizar("Áudio Nº") == "audio_no"
    assert T.normalizar("Cenário") == "cenario"
    assert T.normalizar("Ação") == "acao"


def test_normalizar_nao_deixa_o_campo_virar_algo_que_o_padrao_nao_alcanca():
    """⚠️ Uma coluna custom pode ter qualquer caractere. Se a normalização deixasse
    passar um `-` ou um `%`, o campo existiria no catálogo e seria INDIGITÁVEL: o
    parser pararia antes dele e o editor veria um campo que nunca casa."""
    for cru in ("Nome-Original", "Cena/Plano", "50% OK", "Áudio Nº"):
        campo = T.normalizar(cru)
        assert T.CAMPO_VALIDO.fullmatch(campo), f"{cru!r} → {campo!r} é indigitável"


# ── o que o painel precisa saber ─────────────────────────────────────────────

def test_campos_usados_lista_na_ordem_em_que_aparecem():
    assert T.campos_usados("C%cena_P%plano_T%take2", CAMPOS_PRODF) == [
        "cena", "plano", "take2"]


def test_padrao_vazio_produz_nome_vazio_sem_levantar():
    """⚠️ Render não é quem bloqueia o nome vazio — quem bloqueia é o consumidor, que
    é quem sabe que um clipe não pode se chamar nada. Misturar as duas coisas faria o
    motor recusar um padrão legítimo de outra função futura."""
    assert T.render("", CAMPOS_PRODF) == ""
