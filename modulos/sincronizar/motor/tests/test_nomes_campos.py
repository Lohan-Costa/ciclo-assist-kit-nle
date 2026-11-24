"""O catálogo de campos: colunas cruas → o dicionário que o template consome.

⭐ Como `template`, este módulo não sabe o que é Avid nem o que é claquete. Ele recebe
dicionários e devolve dicionários; quem lê a bin e quem deriva cena/plano são
adaptadores de fora. É o que permite a mesma máquina servir ao Renomear hoje e ao nome
de entrega depois.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nomes import campos as C

# As colunas cruas de um master de Projeto B, como o Avid as nomeia.
COLUNAS_PRODF = {
    "Name": "24-1T01.WAV",
    "Scene": "24-1",
    "Take": "01",
    "Shoot Date": "2026-06-29 12:08:52",
    "Production": "MAE_DO_OURO",
    "TRK3": "BOOM 1",
    "Circled": "no",
}

# As de um som do Projeto C — o doc, onde não há cena nem take e não deve haver.
COLUNAS_PRODE = {
    "Name": "20260101_SOM0034_Tr12.WAV.new.01",
    "TapeID": "20260101_SOM0034_Tr12.WAV",
    "Shoot Date": "2024-05-31 10:02:15",
    "Soundroll TC Rate": "25",
}


# ── colunas cruas → campos digitáveis ────────────────────────────────────────

def test_a_coluna_vira_campo_digitavel():
    f = C.de_colunas(COLUNAS_PRODF)
    assert f["scene"] == "24-1"
    assert f["shoot_date"] == "2026-06-29 12:08:52"
    assert f["trk3"] == "BOOM 1"


def test_toda_chave_produzida_e_alcancavel_por_um_wildcard():
    """⚠️⚠️ O contrato entre os dois módulos. Se `campos` produzisse uma chave que o
    parser de `template` não sabe ler, existiria campo no catálogo que nenhum `%`
    alcança — e o editor veria, no autocomplete, um campo que nunca casa."""
    from nomes import template as T

    for colunas in (COLUNAS_PRODF, COLUNAS_PRODE,
                    {"Nome-Original": "x", "50% OK": "y", "Áudio Nº": "z"}):
        for chave in C.de_colunas(colunas):
            assert T.CAMPO_VALIDO.fullmatch(chave), f"{chave!r} é indigitável"


def test_duas_colunas_que_normalizam_igual_NAO_somem_caladas():
    """⚠️⚠️ `Shoot Date` e `Shoot-Date` viram os dois `shoot_date`. Uma bin com coluna
    custom pode ter as duas, e a segunda desapareceria sem aviso — o editor veria um
    valor e não saberia de qual coluna. Colisão é reportada, não resolvida no escuro."""
    colisoes = {}
    f = C.de_colunas({"Shoot Date": "A", "Shoot-Date": "B"}, colisoes=colisoes)
    assert f["shoot_date"] == "A", "a primeira coluna ganha"
    assert "shoot_date" in colisoes
    assert colisoes["shoot_date"] == ["Shoot Date", "Shoot-Date"]


def test_coluna_sem_nome_e_ignorada():
    assert C.de_colunas({"": "x", "  ": "y", "Scene": "4"}) == {"scene": "4"}


# ── precedência entre fontes ─────────────────────────────────────────────────

def test_a_PRIMEIRA_fonte_ganha():
    """⭐ A ordem declara a confiança: coluna medida antes de campo do mob, campo do
    mob antes de derivado. Um derivado nunca apaga o que foi medido."""
    assert C.juntar({"scene": "24-1"}, {"scene": "OUTRO", "take": "01"}) == {
        "scene": "24-1", "take": "01"}


def test_o_derivado_nao_sobrescreve_o_medido():
    """⚠️⚠️ Uma bin pode ter coluna custom chamada `Cena`, em português, preenchida à
    mão pelo assistente. Ela é MEDIDA e vale mais que qualquer palpite nosso."""
    ficha = C.de_colunas({"Cena": "C99"})
    fora = C.derivar(ficha, [lambda f: {"cena": "C04", "plano": "P01"}])
    assert fora["cena"] == "C99", "o derivado apagou uma coluna medida"
    assert fora["plano"] == "P01", "o derivado que não colide tem de entrar"


def test_o_derivado_PREENCHE_a_chave_medida_que_veio_vazia():
    """⭐ Coluna presente e vazia é ausência de VALOR, não de campo. Se o Avid trouxe
    `Cena` em branco e a claquete sabe a resposta, a resposta entra — senão o material
    ficaria sem cena tendo como sabê-la."""
    ficha = C.de_colunas({"Cena": ""})
    fora = C.derivar(ficha, [lambda f: {"cena": "C04"}])
    assert fora["cena"] == "C04"


def test_o_derivado_ve_a_ficha_ja_montada():
    """O derivador precisa ler `%scene` para poder derivar `%cena` — é assim que a
    claquete lê a coluna do Avid em vez de reparsear o nome."""
    vistos = {}
    C.derivar(C.de_colunas(COLUNAS_PRODF), [lambda f: vistos.update(f) or {}])
    assert vistos["scene"] == "24-1"


def test_derivador_que_devolve_None_nao_derruba_a_ficha():
    """⚠️ `None` é a resposta honesta de quem não soube derivar (§11). Tratá-la como
    erro faria uma bin sem claquete estourar em vez de sair sem cena."""
    fora = C.derivar({"name": "x"}, [lambda f: None, lambda f: {"cena": "C04"}])
    assert fora["name"] == "x"
    assert fora["cena"] == "C04"
    # ⭐ A marca de procedência viaja na própria ficha (ver `derivar`), e o `_` na
    # frente é o que a mantém fora do autocomplete.
    assert fora["_derivados"] == ("cena",)


def test_a_marca_de_procedencia_nao_aparece_como_campo():
    """⚠️ `_derivados` é digitável (`template.CAMPO_VALIDO` aceita `_` inicial), então
    sem a exclusão explícita ela apareceria no autocomplete como se fosse coluna do
    Avid — e `%_derivados` renderizaria uma tupla dentro do nome do clipe."""
    ficha = C.derivar(C.de_colunas({"Scene": "4"}), [lambda f: {"cena": "C04"}])
    assert "_derivados" not in [c.nome for c in C.catalogo([ficha])]


# ── a união preenchida: o contrato com o template ────────────────────────────

def test_completar_da_a_TODOS_a_mesma_lista_de_chaves():
    """⚠️⚠️ É isto que faz a distinção do `template` funcionar: chave AUSENTE é erro do
    padrão; chave PRESENTE e vazia é fato do material. Sem completar, `%production`
    levantaria no clipe do Projeto C e renderizaria no de Projeto B — o mesmo padrão
    bloqueando num clipe e passando no outro, dentro do mesmo arrasto."""
    fichas = C.completar([C.de_colunas(COLUNAS_PRODF),
                          C.de_colunas(COLUNAS_PRODE)])
    assert {k for k in fichas[0]} == {k for k in fichas[1]}
    assert fichas[1]["production"] == "", "faltou preencher com vazio"
    assert fichas[0]["production"] == "MAE_DO_OURO"


def test_completar_de_lista_vazia_nao_estoura():
    assert C.completar([]) == []


# ── o catálogo e o autocomplete ──────────────────────────────────────────────

def test_o_catalogo_traz_o_ROTULO_do_avid_junto():
    """⭐ O editor conhece a coluna como `Shoot Date`, não como `shoot_date`. O
    autocomplete tem de mostrar as duas coisas, senão ele não reconhece o que achou."""
    cat = {c.nome: c for c in C.catalogo([C.de_colunas(COLUNAS_PRODF)],
                                         rotulos=C.rotulos(COLUNAS_PRODF))}
    assert cat["shoot_date"].rotulo == "Shoot Date"
    assert cat["scene"].rotulo == "Scene"


def test_o_exemplo_do_catalogo_pula_os_vazios():
    """⚠️ Um exemplo vazio não ensina nada. Se QUALQUER clipe do arrasto tem valor
    naquela coluna, é esse que o autocomplete mostra."""
    cat = {c.nome: c for c in C.catalogo(C.completar([
        C.de_colunas({"Scene": "", "Take": "01"}),
        C.de_colunas({"Scene": "24-1", "Take": "02"}),
    ]))}
    assert cat["scene"].exemplo == "24-1"


def test_o_exemplo_pula_None_e_espacos_em_branco_tambem():
    """⚠️⚠️ Achado por mutação. Com `""` a guarda parece supérflua — a atribuição
    vazia não trava nada, porque `not exemplos[chave]` volta a disparar no item
    seguinte. Com **`None`** ela é indispensável: `str(None)` é `"None"`, que é
    TRUTHY, e o autocomplete passaria a ensinar que aquela coluna vale `"None"`.

    ⭐ E `None` chega mesmo: um `GetMobInfo` que não trouxe a coluna, um `_USER`
    ausente, um derivador que devolveu chave sem valor.
    """
    cat = {c.nome: c for c in C.catalogo(C.completar([
        C.de_colunas({"Scene": None, "Take": "   "}),
        C.de_colunas({"Scene": "24-1", "Take": "02"}),
    ]))}
    assert cat["scene"].exemplo == "24-1", "gravou 'None' como exemplo"
    assert cat["take"].exemplo == "02", "gravou espaços em branco como exemplo"


def test_o_catalogo_declara_a_PROCEDENCIA():
    """⭐ Mesma disciplina do `presumida` que o painel já mostra: o editor precisa
    saber se `%cena` foi lido de uma coluna ou calculado por nós."""
    ficha = C.derivar(C.de_colunas({"Scene": "4"}), [lambda f: {"cena": "C04"}])
    cat = {c.nome: c for c in C.catalogo([ficha])}
    assert cat["scene"].procedencia == C.MEDIDO
    assert cat["cena"].procedencia == C.DERIVADO


def test_sugerir_completa_pelo_prefixo():
    cat = C.catalogo([C.de_colunas(COLUNAS_PRODF)])
    nomes = [c.nome for c in C.sugerir(cat, "s")]
    assert "scene" in nomes and "shoot_date" in nomes
    assert "take" not in nomes


def test_sugerir_respeita_o_limite_pedido():
    """O autocomplete do painel mostra ~5. Devolver trinta empurraria a caixa de texto
    para fora de uma janela que já é estreita."""
    cat = C.catalogo([C.de_colunas({f"Col {i}": "x" for i in range(30)})])
    assert len(C.sugerir(cat, "col", limite=5)) == 5


def test_sugerir_poe_o_casamento_EXATO_na_frente():
    """⚠️ Com `take` e `take2` no catálogo, quem digitou `%take` quer `take` — e ele
    não pode aparecer embaixo por ordem alfabética."""
    cat = C.catalogo([{"take": "01", "take2": "01", "takeid": "x"}])
    assert C.sugerir(cat, "take")[0].nome == "take"


def test_sugerir_sem_prefixo_devolve_o_comeco_do_catalogo():
    """Digitar só `%` já mostra o que existe — é como o editor descobre as colunas."""
    cat = C.catalogo([C.de_colunas(COLUNAS_PRODF)])
    assert len(C.sugerir(cat, "", limite=5)) == 5


def test_sugerir_nao_distingue_maiuscula():
    cat = C.catalogo([C.de_colunas(COLUNAS_PRODF)])
    assert [c.nome for c in C.sugerir(cat, "SC")] == [c.nome for c in C.sugerir(cat, "sc")]
