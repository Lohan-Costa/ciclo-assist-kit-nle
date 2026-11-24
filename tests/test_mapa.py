"""O mapa de corte — a escrituração do roteiro, sem Avid e sem modelo.

⛔⛔ O teste que dá sentido ao módulo é `test_o_mapa_da_C07_APROVAVA_a_montagem_ruim`:
ele guarda o achado de 2026-09-12 de que ordem e repetição NO PAPEL não bastam.
"""

from __future__ import annotations

from cicloassist.plano import mapa as M

ROTEIRO = """7. INT. CONSULTÓRIO. NOITE

PERSONAGEM-F

Antes de surpreender os dois você
nunca imaginou que pudesse estar
acontecendo alguma coisa entre eles?

PERSONAGEM-G

Sinceramente? Não! Por isso que o caso
do apartamento é complicado.

Além disso, ficou abandonado. Sobe comigo!

PERSONAGEM-F
O que você está pedindo só se faz em
circunstâncias muito particulares.
"""


def corte(falas, take="C07_P02-T002", inicio=100, duracao=200):
    return M.Atribuicao(falas=falas, take=take, inicio_no_take_frames=inicio,
                        duracao_frames=duracao, porque="porque sim")


# ── o roteiro vira estrutura ─────────────────────────────────────────────────

def test_o_cabecalho_de_cena_nao_vira_personagem():
    """⚠️ "7. INT. CONSULTÓRIO. NOITE" é caixa alta igual a "PERSONAGEM-F". Sem a peneira, a
    rubrica virava a fala 1 e todo o resto andava um número."""
    r = M.estruturar(ROTEIRO)
    assert r[0].personagem == "PERSONAGEM-F"
    assert "CONSULTÓRIO" not in r[0].texto


def test_cada_paragrafo_e_uma_fala():
    """⭐ É no parágrafo que o editor corta. Juntar a fala inteira numa só esconderia o
    ponto de corte que o modelo precisa escolher."""
    r = M.estruturar(ROTEIRO)
    assert len(r) == 4
    assert [f.personagem for f in r] == ["PERSONAGEM-F", "PERSONAGEM-G", "PERSONAGEM-G", "PERSONAGEM-F"]
    assert r[2].texto.startswith("Além disso")


def test_o_personagem_sem_linha_em_branco_ainda_e_reconhecido():
    """No roteiro real, "PERSONAGEM-F" vem colada na fala anterior em alguns pontos."""
    r = M.estruturar("PERSONAGEM-G\nNão sei, não sei…\nPERSONAGEM-F\nToda terapia implica.")
    assert len(r) == 2 and r[1].personagem == "PERSONAGEM-F"


def test_roteiro_vazio_nao_estoura():
    assert M.estruturar("") == []


# ── a escrituração ───────────────────────────────────────────────────────────

def test_a_ordem_do_roteiro_manda():
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([1], take="A"), corte([3], take="B"),
                          corte([2], take="C")])
    assert not conf.fecha
    assert any("volta para a fala 2" in p for p in conf.problemas)


def test_fala_repetida_depois_de_outra_e_recusada():
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([1], take="A"), corte([2], take="B"),
                          corte([1], take="C")])
    assert not conf.fecha
    assert any("fala repetida" in p for p in conf.problemas)


def test_uma_fala_longa_em_DOIS_angulos_passa():
    """⭐ 1→N não é repetição: é a mesma fala continuada, e cobrir um monólogo com dois
    ângulos é montagem normal. Os cortes só precisam vir colados."""
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([1], take="A"), corte([1], take="B"), corte([2])])
    assert conf.fecha, conf.problemas


def test_duas_falas_num_corte_so_passa():
    """⭐ N→1: duas falas seguidas do mesmo take com vão curto viram UM corte."""
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([2, 3], take="A"), corte([4], take="B")])
    assert conf.fecha, conf.problemas


def test_fala_sacrificada_e_legitima_mas_contada():
    """1→0 é decisão editorial — não é erro, mas o editor precisa saber."""
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([1], take="A"), corte([4], take="B")])
    assert conf.fecha
    assert conf.sacrificadas == [2, 3]
    assert "2, 3" in M.relatar(r, conf)


def test_fala_que_nao_existe_no_roteiro():
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([99])])
    assert any("não existe no roteiro" in p for p in conf.problemas)


def test_segundo_no_lugar_de_frame():
    """⚠️ `duracao_frames: 3` é quase sempre "3 segundos" escrito errado."""
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([1], duracao=1)])
    assert any("segundo no lugar de frame" in p for p in conf.problemas)


def test_mapa_vazio_nao_fecha():
    assert not M.conferir(M.estruturar(ROTEIRO), []).fecha


# ── a âncora no material ─────────────────────────────────────────────────────

def test_o_mapa_da_C07_APROVAVA_a_montagem_ruim():
    """⛔⛔ O achado de 2026-09-12. A montagem que o editor chamou de "horrível" tinha as
    falas declaradas em ordem perfeita, 15 de 16, sem repetição. Ordem e repetição NO
    PAPEL não pegam o defeito — quem pega é a âncora no material."""
    roteiro = [M.Fala(n, "X", f"fala {n}") for n in range(1, 17)]
    ordem = [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
    # Alternando os ângulos, como o mapa real fazia: ordem e repetição não têm o que
    # reclamar, e mesmo assim os cortes apontavam o tempo de outro take.
    conf = M.conferir(roteiro, [corte([n], take=f"T{k % 4}", inicio=500 + k * 400)
                                for k, n in enumerate(ordem)])
    assert conf.fecha, "a escrituração sozinha aprova — é por isso que ela não basta"


def test_a_parecenca_separa_take_certo_de_take_errado():
    """MEDIDO no material da C07: take certo 100%, com improviso real 90%, take errado 9%.
    O piso de 30% fica num abismo, não numa borda."""
    escrito = "Sinceramente? Não! Por isso que o caso do apartamento é complicado."
    assert M.parecenca(escrito, "Sinceramente, não. Por isso que o caso do apartamento "
                                "é tão complicado.") > 0.9
    assert M.parecenca(escrito, "Toda terapia implica em alguns critérios.") < 0.2


def test_o_improviso_do_ator_NAO_reprova():
    """⚠️ Medido: 4 de 6 falas divergiram do roteiro e 7 de 11 tomadas tiveram improviso.
    Piso alto recusaria material bom — e o material manda no texto."""
    assert M.parecenca(
        "Eu me concentro na história pessoal de cada paciente mas não posso "
        "flexibilizar demais.",
        "Aqui eu me concentro na história pessoal de cada personagem. Mas eu não posso "
        "flexibilizar demais.") >= M.PARECENCA_MINIMA


def test_a_ancora_pega_o_timestamp_do_take_errado():
    """⛔ O defeito real da C07: fala certa declarada, tempo de outro take."""
    r = M.estruturar(ROTEIRO)

    def falado(take, inicio, duracao):
        return "Toda terapia implica em alguns critérios, não dá para acelerar."

    problemas = M.ancorar(r, [corte([1])], falado)
    assert problemas and "parecença" in problemas[0]


def test_a_ancora_aceita_o_take_certo():
    r = M.estruturar(ROTEIRO)

    def falado(take, inicio, duracao):
        return ("Antes de surpreender os dois, você nunca imaginou que pudesse estar "
                "acontecendo alguma coisa entre eles?")

    assert M.ancorar(r, [corte([1])], falado) == []


def test_transcricao_indisponivel_vira_aviso_e_nao_excecao():
    """⚠️ Take sem transcrição não invalida o mapa — mas o editor tem de saber que aquele
    corte não foi conferido."""
    r = M.estruturar(ROTEIRO)

    def falado(take, inicio, duracao):
        raise RuntimeError("sem cache")

    problemas = M.ancorar(r, [corte([1])], falado)
    assert len(problemas) == 1 and "não consegui conferir" in problemas[0]


# ── o buraco que o Haiku achou ───────────────────────────────────────────────
#
# ⛔⛔ MEDIDO em 2026-09-12: o checker da primeira versão conferia ordem, repetição e a
# âncora no material — e APROVAVA um mapa de 16 cortes saídos de um take só. Um plano
# aberto que cobre a cena inteira satisfaz "a fala está mesmo aqui" para todas as falas.
# Os números abaixo são os do transcript real.

HAIKU_INICIO = [485, 694, 986, 1199, 1405, 1878, 2195, 2310,
                2613, 2613, 3081, 3513, 3647, 4028, 4320, 4603]
HAIKU_DURACAO = [194, 278, 173, 209, 435, 319, 85, 165,
                 93, 391, 344, 144, 383, 294, 274, 181]


def dezesseis(take_de):
    r = [M.Fala(n, "X", f"fala {n}") for n in range(1, 17)]
    cortes = [M.Atribuicao(falas=[k + 1], take=take_de(k),
                           inicio_no_take_frames=HAIKU_INICIO[k],
                           duracao_frames=HAIKU_DURACAO[k], porque="x")
              for k in range(16)]
    return r, cortes


def test_o_mapa_degenerado_do_HAIKU_passa_a_REPROVAR():
    """⛔⛔ O teste de regressão desta rodada. Este mapa foi APROVADO em campo e virou uma
    sequência que o editor descreveu como "não editou nada"."""
    r, cortes = dezesseis(lambda k: "C07_P01-T001")
    conf = M.conferir(r, cortes)
    assert not conf.fecha
    assert any("não é montagem" in p for p in conf.problemas)
    assert conf.planos_usados == ["C07_P01-T001"]


def test_alternar_angulos_continua_aprovando():
    """⭐ O conserto não pode recusar montagem de verdade."""
    takes = ["C07_P01-T002", "C07_P02-T003", "C07_P03-T001",
             "C07_P02-T004", "C07_P03-T003"]
    r = [M.Fala(n, "X", f"fala {n}") for n in range(1, 17)]
    cortes = [M.Atribuicao(falas=[k + 1], take=takes[k % 5],
                           inicio_no_take_frames=500 + k * 300, duracao_frames=200,
                           porque="x") for k in range(16)]
    conf = M.conferir(r, cortes)
    assert conf.fecha, conf.problemas
    assert len(conf.planos_usados) == 5


def test_plano_sequencia_de_UM_corte_e_legitimo():
    """⚠️ Uma cena de plano-sequência existe, e o conserto não pode bloqueá-la: ela se
    monta com UM corte, não com dezesseis emendas invisíveis."""
    r = [M.Fala(n, "X", f"fala {n}") for n in range(1, 17)]
    conf = M.conferir(r, [M.Atribuicao(falas=list(range(1, 17)), take="T",
                                       inicio_no_take_frames=0, duracao_frames=5000,
                                       porque="plano-sequência")])
    assert conf.fecha, conf.problemas


def test_corte_do_mesmo_take_seguido_e_jump_cut():
    """⭐ A regra não é cota de cobertura — ritmo é ofício. É que cortar de um plano para
    ele mesmo é jump cut, e o método já mandava juntar falas seguidas num corte só."""
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([1], take="A", inicio=0),
                          corte([2], take="A", inicio=900),
                          corte([4], take="B")])
    assert not conf.fecha
    assert any("jump cut" in p for p in conf.problemas)


def test_dois_cortes_no_MESMO_trecho_sao_material_repetido():
    """⛔ Medido no mapa do Haiku: os cortes 9 e 10 começavam os dois no frame 2613."""
    r = M.estruturar(ROTEIRO)
    conf = M.conferir(r, [corte([1], take="A", inicio=2613, duracao=93),
                          corte([2], take="B"),
                          corte([3], take="A", inicio=2613, duracao=391)])
    assert not conf.fecha
    assert any("MESMO trecho" in p for p in conf.problemas)


def test_a_reprova_e_CURTA():
    """⚠️ Cada linha de problema é contexto que o editor paga, num turno que já deu
    errado. A primeira versão devolvia 21 linhas para o mapa do Haiku."""
    r, cortes = dezesseis(lambda k: "C07_P01-T001")
    conf = M.conferir(r, cortes)
    assert len(conf.problemas) <= 3, conf.problemas
