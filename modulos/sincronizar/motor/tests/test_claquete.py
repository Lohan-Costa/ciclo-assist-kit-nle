"""O leitor de claquete — cena · plano · take a partir do nome do SOM.

⚠️ A câmera não tem claquete; só o som tem (achado 1 do spec). Metade dos casos
abaixo existe para provar que um nome de CÂMERA não é lido como cena por acidente:
`A001_03170214_C001` tem um `C001` que um regex frouxo casaria como "cena 1", e o
sintoma seria uma bin de cena inteira nascida de um engano de rolo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from media import claquete

# (nome, cena, plano, take) — os quatro campos, ou None quando não deve casar.
CASOS_QUE_CASAM = [
    # ── o material real da diária 2, medido em D02_SOM.avb ───────────────────
    ("PROJETO A - 05-04 C4 P1-T001", "C04", "P01", "T001"),
    ("PROJETO A - 05-04 C4 P1-T002", "C04", "P01", "T002"),
    ("PROJETO A - 05-04 C4 P4-T005", "C04", "P04", "T005"),
    ("PROJETO A - 05-04 C7 P3-T003", "C07", "P03", "T003"),
    # com extensão, que é como o arquivo chega do disco
    ("PROJETO A - 05-04 C4 P2-T001.WAV", "C04", "P02", "T001"),
    ("PROJETO A - 05-04 C4 P2-T001.wav", "C04", "P02", "T001"),
    # ⭐ dois dígitos: é o que faz a bin ordenar C04 antes de C10 (§10 do spec)
    ("PROJETO C10 P2-T001", "C10", "P02", "T001"),
    ("PROJETO C4 P12-T001", "C04", "P12", "T001"),
    # cena com letra — acontece quando a produção divide uma cena no set
    ("PROJETO C4A P1-T001", "C04A", "P01", "T001"),

    # ── ⭐ o material real da diária 3, medido em `D03 SOM.avb` ───────────────
    # ⚠️⚠️ Os WAVs no disco chamam `... C11 P1-T001.WAV`, IGUAL aos da D02 — mas o
    # Avid nomeou estes masters pelo iXML, `<SCENE>` + "/" + `<TAKE>`. É o MESMO
    # gravador e a MESMA produção; o que muda é quem escreveu o nome. Um leitor que
    # só conhecesse a forma de arquivo daria a diária inteira como não resolvida,
    # que foi exatamente o que aconteceu em 2026-08-27: 38 takes, 38 sem cena.
    ("PROJETO A - 05-04 C11 P1/001", "C11", "P01", "T001"),
    ("PROJETO A - 05-04 C14 P2/006", "C14", "P02", "T006"),
    # ⭐ O qualificador entre plano e take SOBREVIVE dentro do plano, e é decisão do
    # autor (2026-08-28): um pickup e um P3 comum do mesmo take teriam virado o mesmo
    # nome de subclipe se o qualificador fosse descartado — colisão silenciosa.
    ("PROJETO A - 05-04 C11 P3 PICUP/001", "C11", "P03 PICUP", "T001"),
    ("PROJETO A - 05-04 FOLLY C9 P1 SERIE/011", "C09", "P01 SERIE", "T011"),
    # ⚠️ O qualificador quebrava a convenção de ARQUIVO também — defeito independente
    # do separador, que a D02 escondia por não ter pickup nem série.
    ("PROJETO A - 05-04 C11 P3 PICUP-T001", "C11", "P03 PICUP", "T001"),
    ("PROJETO A - 05-04 FOLLY C9 P1 SERIE-T011", "C09", "P01 SERIE", "T011"),

    # ── ⭐⭐ o ROTULO é vocabulário, não código ────────────────────────────────
    # A diária 4 de *PRODUCAO-A* escreve a cena por extenso e sem separador —
    # `CENA15P2-T001`, medido em `D04_SOM.avb`. Não é uma convenção nova de produção:
    # é o MESMO `<cena><plano><take>`, com outra palavra no lugar do `C`. Uma entrada
    # nova em `CONVENCOES` para cada palavra é a acumulação que o autor recusou em
    # 2026-08-28; o que muda é a LISTA DE RÓTULOS, e a gramática é uma só.
    ("CENA15P2-T001", "C15", "P02", "T001"),
    ("CENA17P2-T006", "C17", "P02", "T006"),
    # o vocabulário completo, cada rótulo provado
    ("PROJETO SC7 P2-T001", "C07", "P02", "T001"),
    ("PROJETO ESC7 P2-T001", "C07", "P02", "T001"),
    ("PROJETO C7 PLANO2-T001", "C07", "P02", "T001"),
    ("PROJETO C7 TOM2-T001", "C07", "P02", "T001"),
    ("PROJETO C7 P2 TAKE001", "C07", "P02", "T001"),
    ("PROJETO C7 P2 TK001", "C07", "P02", "T001"),
    # separadores do take: hífen, sublinhado, espaço e a barra do iXML
    ("PROJETO C7 P2_T003", "C07", "P02", "T003"),
    ("PROJETO C7 P2 T003", "C07", "P02", "T003"),
]

CASOS_QUE_NAO_CASAM = [
    # ⚠️⚠️ O caso que mais importa: nome de CÂMERA. `C001` é o número do clipe da
    # Blackmagic, não uma cena. Um leitor que o casasse criaria a bin "C01" a partir
    # de material sem claquete nenhuma — inferência disfarçada de dado.
    "A001_03170214_C001",
    "A001_03170214_C001.mp4",
    "a004_03170908_C001",
    # sem take
    "PROJETO C4 P1",
    # ⚠️ Nem com a convenção do iXML: o "/" precisa de DÍGITOS depois. Sem isto, um
    # caminho POSIX (`.../C4 P1/qualquer`) leria a pasta seguinte como número de take.
    "PROJETO C4 P1/",
    "PROJETO C4 P1/TOMADAS",

    # ⚠️⚠️ O material real que NÃO pode virar cena, e cada um por um motivo diferente.
    # ⭐ A proteção é a gramática exigir os TRÊS campos: um `C` com número que não
    # tenha plano E take depois não é claquete nenhuma. Sem isso, `a005_..._C003`
    # criaria a bin "C03" a partir de um número de clipe da Blackmagic.
    "a005_03180108_C003",                    # câmera, PRODUCAO-A D03
    "A_0001C001_260101_100000_h1DF4",        # câmera, Projeto B
    "20260101_CAM0001.new.01",              # câmera, Projeto C (doc)
    "20260101_SOM0034_Tr12.WAV.new.01",     # som, Projeto C — não há cena e não deve haver
    "DJI_0310",                              # drone, PRODUCAO-A D04
    # ⚠️ Som selvagem: `03-04` é DATA. Número sem rótulo nunca vira cena.
    "PROJETO A - CENA-PRAIA 03-04-T001",
    "AMB-T001",                              # ambiente, PRODUCAO-A D04
    # ⚠️ Projeto B: `24-1` É cena-plano, mas sem rótulo que o prove. Decisão do
    # autor em 2026-08-28: **não se deriva**. O template usa `%scene`, que é a coluna
    # crua e está sempre certa. Ler o hífen aqui seria inventar.
    "24-1T01.WAV",
    "17WT02.WAV",
    # sem plano
    "PROJETO C4 T001",
    # vazio e lixo
    "",
    "   ",
    "sem nada aqui",
]


@pytest.mark.parametrize("nome,cena,plano,take", CASOS_QUE_CASAM,
                         ids=[c[0] for c in CASOS_QUE_CASAM])
def test_le_a_claquete(nome, cena, plano, take):
    c = claquete.ler(nome)
    assert c is not None, f"{nome!r} deveria casar e não casou"
    assert (c.cena, c.plano, c.take) == (cena, plano, take)
    assert c.convencao, "toda leitura tem de dizer QUAL convenção a produziu"


@pytest.mark.parametrize("nome", CASOS_QUE_NAO_CASAM, ids=CASOS_QUE_NAO_CASAM)
def test_nome_fora_de_convencao_devolve_none(nome):
    """⚠️ Nome que não casa NÃO é erro — é cena não resolvida (§11 do spec). O
    leitor devolve `None` e quem chama decide; ele nunca inventa uma cena."""
    assert claquete.ler(nome) is None


def test_nome_de_subclipe():
    c = claquete.ler("PROJETO A - 05-04 C4 P1-T002")
    assert claquete.nome_de_subclipe(c) == "C04_P01_T002"


def test_o_ROTULO_novo_entra_na_lista_e_nao_no_codigo():
    """⭐⭐ O contrato que responde à crítica de 2026-08-28: *"estamos resolvendo
    problemas pontuais"*.

    Uma produção que escreva `TOMADA 7` em vez de `C7` não deve exigir uma expressão
    regular nova — deve exigir uma PALAVRA. Se este teste precisar de mudança em
    `claquete.py` além da lista, a generalização não aconteceu.
    """
    antes = list(claquete.ROTULOS_DE_CENA)
    try:
        claquete.registrar_rotulo_de_cena("TOMADA")
        c = claquete.ler("PROJETO TOMADA7 P2-T001")
        assert c is not None, "o rótulo novo não passou a ser reconhecido"
        assert (c.cena, c.plano, c.take) == ("C07", "P02", "T001")
    finally:
        claquete.ROTULOS_DE_CENA[:] = antes
        claquete.recompilar()


def test_o_rotulo_precisa_de_FRONTEIRA_antes():
    """⚠️⚠️ `ABC4 P1-T001` não é cena 4 — o `C` está no meio de uma palavra.

    Sem o `\\b`, um código de projeto (`ABC4`), um rolo (`SDC2`) ou qualquer sigla
    terminada em letra + número viraria cena. Achado por mutação: o mutante que remove
    a fronteira sobrevivia porque o material real é protegido por OUTRA regra (o `_`
    antes do `C` em `a005_..._C003` também não é fronteira), e a regra da fronteira
    ficava sem prova nenhuma.
    """
    assert claquete.ler("ABC4 P1-T001") is None
    assert claquete.ler("PROJETOC4 P1-T001") is None
    # ⭐ E com a fronteira presente, casa — senão o teste acima passaria por engano.
    assert claquete.ler("ABC C4 P1-T001") is not None


def test_take_com_digito_nu_so_depois_da_BARRA():
    """⚠️⚠️ Depois de hífen, sublinhado ou espaço o rótulo de take é OBRIGATÓRIO.

    A barra é a exceção medida: é como o Media Composer escreve a partir do iXML
    (`C11 P1/001`). Aceitar dígito nu depois de hífen também faria `05-04` — uma DATA,
    e o material da D01 é cheio delas — virar número de take.

    Achado por mutação: o mutante que torna o rótulo opcional sobrevivia sem isto.
    """
    assert claquete.ler("PROJETO C4 P1/002") is not None      # a barra, medida
    assert claquete.ler("PROJETO C4 P1-002") is None          # hífen exige rótulo
    assert claquete.ler("PROJETO C4 P1_002") is None
    assert claquete.ler("PROJETO C4 P1 002") is None
    assert claquete.ler("PROJETO C4 P1 05-04") is None        # a data da D01


def test_entre_cena_e_plano_so_ESPACO_ou_nada():
    """⚠️ `C4_P1-T001` NÃO casa, e a razão é conservadora: sublinhado entre cena e
    plano não aparece em nenhum dos três produtos medidos. Aceitar separador que não
    se viu é ampliar a superfície de falso positivo sem material que a justifique.

    ⭐ Quem precisar dessa forma tem caminho: `registrar_convencao(...)`.

    ⚠️ Correção de 2026-08-28: o docstring de `_montar_gramatica` afirmava que este
    `\\s*` era o que protegia `ESC9_TOM3_2` de ser capturado antes de uma convenção
    registrada. **Era falso** — quem protege ali é a exigência de take. A mutação
    mostrou, e a afirmação foi corrigida em vez de o teste ser ajustado para ela.
    """
    assert claquete.ler("PROJETO C4_P1-T001") is None
    assert claquete.ler("PROJETO C4 P1-T001") is not None
    assert claquete.ler("CENA15P2-T001") is not None          # colado também vale


def test_o_rotulo_MAIS_LONGO_ganha():
    """⚠️ `C` é prefixo de `CENA`. Numa alternância ingênua o `C` casaria primeiro,
    exigiria dígito, encontraria o `E` de `CENA` e a leitura inteira falharia."""
    c = claquete.ler("CENA15P2-T001")
    assert c is not None and c.cena == "C15"


def test_as_duas_formas_do_mesmo_take_dao_o_mesmo_nome_de_subclipe():
    """⭐⭐ O contrato que faz a D03 valer o conserto: o nome do ARQUIVO e o nome que o
    Avid monta do iXML descrevem a MESMA tomada, e têm de produzir o MESMO subclipe.

    Se divergirem, a mesma diária reimportada com outra preferência de nomeação sai
    com duas bins de cena para o mesmo material — e o editor não tem como saber qual
    das duas é a boa.
    """
    for arquivo, ixml in [
        ("PROJETO A - 05-04 C11 P1-T001", "PROJETO A - 05-04 C11 P1/001"),
        ("PROJETO A - 05-04 C11 P3 PICUP-T001",
         "PROJETO A - 05-04 C11 P3 PICUP/001"),
    ]:
        a, b = claquete.ler(arquivo), claquete.ler(ixml)
        assert a is not None and b is not None
        assert claquete.nome_de_subclipe(a) == claquete.nome_de_subclipe(b)


def test_o_qualificador_separa_o_pickup_do_plano_comum():
    """⚠️⚠️ A colisão que a decisão de 2026-08-28 existe para impedir. `C11 P3/001` e
    `C11 P3 PICUP/001` são tomadas DIFERENTES; se o qualificador fosse descartado, as
    duas virariam `C11_P03_T001` e uma sobrescreveria a outra na bin."""
    comum = claquete.ler("PROJETO A - 05-04 C11 P3/001")
    pickup = claquete.ler("PROJETO A - 05-04 C11 P3 PICUP/001")
    assert comum is not None and pickup is not None
    assert claquete.nome_de_subclipe(comum) != claquete.nome_de_subclipe(pickup)


def test_dois_digitos():
    assert claquete.dois_digitos("4") == "04"
    assert claquete.dois_digitos("04") == "04"
    assert claquete.dois_digitos("12") == "12"
    assert claquete.dois_digitos("002") == "002"   # já tem mais que dois: preserva
    assert claquete.dois_digitos("4A") == "04A"    # sufixo sobrevive ao zero à esquerda


def test_convencao_registrada_passa_a_ser_tentada():
    """⚠️ A peça que mais vai variar no produto real é esta (§6 do spec). Registrar
    uma convenção não pode exigir editar `claquete.py`."""
    antes = len(claquete.CONVENCOES)
    try:
        claquete.registrar_convencao("teste", r"ESC(?P<cena>\d+)_TOM(?P<take>\d+)_(?P<plano>\d+)")
        c = claquete.ler("ESC9_TOM3_2")
        assert c is not None
        assert (c.cena, c.plano, c.take) == ("C09", "P02", "T03")
        assert c.convencao == "teste"
    finally:
        del claquete.CONVENCOES[antes:]


def test_a_convencao_do_projeto_a_ganha_de_uma_registrada_depois():
    """A ordem da lista é a ordem de tentativa, e a primeira que casa vence. Sem isso,
    uma convenção nova e frouxa capturaria material da convenção conhecida."""
    antes = len(claquete.CONVENCOES)
    try:
        claquete.registrar_convencao("frouxa", r"C(?P<cena>\d+).*P(?P<plano>\d+).*T(?P<take>\d+)")
        c = claquete.ler("PROJETO A - 05-04 C4 P1-T002")
        assert c.convencao != "frouxa"
    finally:
        del claquete.CONVENCOES[antes:]


# ── descarte do som: FALSE TAKE / TRASH ──────────────────────────────────────

def test_descarte_reconhece_as_duas_pastas(tmp_path):
    """⚠️ As pastas existem no material real e estão VAZIAS (§12 do spec). Sem esta
    fixture sintética, o ramo de descarte é código que nunca rodou."""
    for pasta in ("FALSE TAKE", "TRASH"):
        alvo = tmp_path / pasta / "PROJETO A - 05-04 C4 P1-T003.WAV"
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(b"")
        assert claquete.e_descartado(alvo) is True, f"{pasta} não foi reconhecida"


def test_descarte_e_insensivel_a_caixa(tmp_path):
    alvo = tmp_path / "False Take" / "x.WAV"
    alvo.parent.mkdir(parents=True)
    alvo.write_bytes(b"")
    assert claquete.e_descartado(alvo) is True


def test_arquivo_fora_das_pastas_nao_e_descartado(tmp_path):
    alvo = tmp_path / "SD02" / "PROJETO A - 05-04 C4 P1-T002.WAV"
    alvo.parent.mkdir(parents=True)
    alvo.write_bytes(b"")
    assert claquete.e_descartado(alvo) is False


def test_sem_caminho_o_descarte_e_NAO_AVALIADO_e_nao_falso():
    """⚠️⚠️ `None` não é `False`, e a diferença é a do §7 do spec: campo vazio
    significa **não medido**, nunca "zero". Um take cujo caminho não se conhece não
    pode receber atestado de que não foi descartado."""
    assert claquete.e_descartado(None) is None
    assert claquete.e_descartado("") is None


def test_ler_aceita_path_object():
    """A função deve coercir `pathlib.Path` para string, como já faz com int.

    Tarefas 3 e 4 leem nomes de estruturas AVB onde um `Path` é fácil de acontecer.
    Uma `Path` não é erro — é só um envelope diferente no mesmo nome."""
    c = claquete.ler(Path("PROJETO A - 05-04 C4 P1-T002.WAV"))
    assert c is not None
    assert (c.cena, c.plano, c.take) == ("C04", "P01", "T002")


def test_ler_aceita_int():
    """A função deve coercir `int` para string, retornando `None` quando não casa.

    Um int não tem nenhuma chance de casar com a convenção, mas não deve crashear."""
    assert claquete.ler(12345) is None
    assert claquete.ler(0) is None


def test_registrar_convencao_rejeita_grupos_faltando():
    """Padrão sem os grupos nomeados requeridos deve falhar na hora de registrar,
    não lá adiante quando uma varredura de takes bater nele."""
    with pytest.raises(ValueError, match="sem os grupos nomeados"):
        claquete.registrar_convencao("ruim", r"C(?P<cena>\d+)_P(?P<plano>\d+)")

    # Falta take
    with pytest.raises(ValueError, match="take"):
        claquete.registrar_convencao("incompleto", r"C(?P<cena>\d+)_P(?P<plano>\d+)_(?P<outro>\d+)")


def test_rotulos_em_ingles():
    c = claquete.ler("Scene 4 Shot 2 Take 3.wav")
    assert (c.cena, c.plano, c.take) == ("C04", "P02", "T03")
    d = claquete.ler("SC12 SH3 TK5.wav")
    assert (d.cena, d.plano, d.take) == ("C12", "P03", "T05")


def test_o_padrao_de_serie_guarda_o_episodio_e_o_sufixo_como_esta():
    c = claquete.ler("E3C2P1T01.WAV")
    assert (c.episodio, c.cena, c.plano, c.take) == ("E03", "C02", "P01", "T01")
    d = claquete.ler("E5C9ctP3T01.WAV")
    assert (d.episodio, d.cena, d.plano) == ("E05", "C09CT", "P03")


def test_o_episodio_nao_abre_a_porta_para_nome_de_camera():
    assert claquete.ler("A001_03170436_C009.mp4") is None
    assert claquete.ler("E3C2P1.WAV") is None             # sem take não casa


def test_falsetakes_e_descarte(tmp_path):
    assert claquete.e_descartado(tmp_path / "SOM" / "FALSETAKES" / "x.WAV") is True
