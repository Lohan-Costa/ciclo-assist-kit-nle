"""O validador do plano — e o que ele recusa é mais importante que o que aceita.

⛔ **A recusa é ATÔMICA:** item malformado derruba o plano inteiro. Um plano aplicado pela
metade deixa o projeto do editor num estado que ninguém pediu e que ele desfaz à mão.

⚠️ **E a mensagem tem de dizer QUAL item e O QUÊ.** Um "plano inválido" sozinho manda o
editor procurar no escuro e manda o modelo tentar de novo sem saber o que corrigir — por
isso os testes conferem o TEXTO, não só a exceção.
"""

from __future__ import annotations

import pytest

from cicloassist.plano import esquema as E


def corte(**muda):
    base = {
        "take": "C07_P02-T004",
        "duracao_frames": 240,
        "confianca": "hipotese",
        "fonte": "heuristica",
        "porque": "último take da série",
    }
    base.update(muda)
    return {k: v for k, v in base.items() if v is not ...}


def plano(cortes=None, **muda):
    base = {"bin": "CENAS/C07.avb", "nome": "C07 CORTE ZERO",
            "cortes": cortes if cortes is not None else [corte()]}
    base.update(muda)
    return base


# ── o que passa ──────────────────────────────────────────────────────────────

def test_plano_minimo_passa():
    p = E.validar(plano())
    assert p.nome == "C07 CORTE ZERO"
    assert p.cortes[0].inicio_no_take == 0
    assert p.duracao_frames == 240


def test_numero_como_texto_e_aceito():
    """⚠️ O modelo manda número como texto com alguma frequência. Recusar isso seria rigor
    sem ganho — o valor é inequívoco."""
    p = E.validar(plano([corte(duracao_frames="240", inicio_no_take="12")]))
    assert p.cortes[0].duracao_frames == 240
    assert p.cortes[0].inicio_no_take == 12


def test_float_redondo_passa():
    assert E.validar(plano([corte(duracao_frames=240.0)])).cortes[0].duracao_frames == 240


# ── o que é recusado, e por quê ──────────────────────────────────────────────

def test_fracionario_e_recusado_como_erro_de_unidade():
    """⭐ Frames são inteiros. Um fracionário é sintoma de SEGUNDO no lugar de frame, e
    aceitar arredondando esconderia o engano — um corte de 10,5 s viraria 10 frames."""
    with pytest.raises(E.PlanoInvalido, match="segundo no lugar de frame"):
        E.validar(plano([corte(duracao_frames=10.5)]))


def test_duracao_minuscula_e_recusada():
    with pytest.raises(E.PlanoInvalido, match="não é corte"):
        E.validar(plano([corte(duracao_frames=1)]))


def test_sem_procedencia_derruba_o_plano():
    """⛔ Item sem procedência é bug, não item."""
    for falta in ("confianca", "fonte"):
        with pytest.raises(E.PlanoInvalido, match="sem procedência"):
            E.validar(plano([corte(**{falta: ""})]))


def test_vocabulario_fechado_e_a_mensagem_lista_os_validos():
    """A mensagem precisa ensinar o que usar — senão o modelo tenta outro palpite."""
    with pytest.raises(E.PlanoInvalido, match="confirmado, inferido, hipotese"):
        E.validar(plano([corte(confianca="talvez")]))
    with pytest.raises(E.PlanoInvalido, match="claquete"):
        E.validar(plano([corte(fonte="chute")]))


def test_sem_porque_e_recusado():
    """⭐ `hipotese/heuristica` diz o GRAU da incerteza, não o MOTIVO da escolha. O editor
    aprova corte a corte e decide pelo motivo — foi lendo "o take foi abortado, tem um
    homem gritando" que a escolha certa apareceu na fase 5b."""
    with pytest.raises(E.PlanoInvalido, match="por que este take"):
        E.validar(plano([corte(porque="   ")]))


def test_sem_take_e_recusado():
    with pytest.raises(E.PlanoInvalido, match="sem take"):
        E.validar(plano([corte(take="")]))


def test_inicio_negativo_e_recusado():
    with pytest.raises(E.PlanoInvalido, match="negativo"):
        E.validar(plano([corte(inicio_no_take=-5)]))


def test_plano_vazio_e_recusado():
    with pytest.raises(E.PlanoInvalido, match="item morto"):
        E.validar(plano([]))


def test_plano_sem_bin_ou_nome_e_recusado():
    with pytest.raises(E.PlanoInvalido, match="sem `bin`"):
        E.validar(plano(bin=""))
    with pytest.raises(E.PlanoInvalido, match="sem `nome`"):
        E.validar(plano(nome=""))


def test_nome_com_caractere_de_caminho_e_recusado():
    """O nome vira nome de mob e aparece na bin. Sanear em silêncio entregaria ao editor
    um nome que ele não pediu."""
    with pytest.raises(E.PlanoInvalido, match="caractere proibido"):
        E.validar(plano(nome="CENAS/C07"))


# ── a mensagem aponta o item certo ───────────────────────────────────────────

def test_a_mensagem_diz_qual_corte_falhou():
    """Num plano de 20 cortes, "plano inválido" é inútil."""
    cortes = [corte(), corte(take="C07_P03-T001"), corte(take="C07_P01-T002", confianca="x")]
    with pytest.raises(E.PlanoInvalido, match=r"corte 3 \(C07_P01-T002\)"):
        E.validar(plano(cortes))


def test_a_recusa_e_atomica():
    """Um item ruim no meio derruba TUDO — não sobra meio plano para aplicar."""
    cortes = [corte(), corte(duracao_frames=0), corte()]
    with pytest.raises(E.PlanoInvalido):
        E.validar(plano(cortes))


# ── o resumo que o editor lê ─────────────────────────────────────────────────

def test_resumo_traz_o_porque_de_cada_corte():
    p = E.validar(plano([
        corte(porque="último take da série"),
        corte(take="C07_P03-T001", inicio_no_take=480, porque="a única com a fala inteira"),
    ]))
    texto = E.resumir(p, 23.976)
    assert "último take da série" in texto
    assert "a única com a fala inteira" in texto
    assert "do início" in texto          # inicio 0 vira prosa, não "0.0s"
    assert "20.0s" in texto              # 480 frames a 23.976


# ── corte em L e em J: fica com o editor ─────────────────────────────────────
#
# ⛔ Decisão do autor (2026-11-06, estendida a todos os NLEs em 2026-11-07): o produto entrega o
#    corte seco, e onde o som troca é escolha de quem monta. O plano com L/J é RECUSADO com a frase.

def test_sem_dizer_nada_o_corte_e_seco():
    p = E.validar(plano())
    assert p.cortes[0].corte_de_som == "junto"
    assert p.cortes[0].desloca == 0


@pytest.mark.parametrize("muda", [
    {"corte_de_som": "antes", "som_frames": 14},
    {"corte_de_som": "depois", "som_frames": 9},
    {"corte_de_som": "depois"},
    {"corte_de_som": "junto", "som_frames": 12},
    {"corte_de_som": "em L", "som_frames": 10},
])
def test_corte_em_l_ou_j_e_recusado_e_fica_com_o_editor(muda):
    with pytest.raises(E.PlanoInvalido) as e:
        E.validar(plano([corte(), corte(inicio_no_take=500, **muda)]))
    assert "L/J" in str(e.value) and "editor" in str(e.value)


def test_corte_seco_explicito_passa():
    p = E.validar(plano([corte(), corte(corte_de_som="junto", som_frames=0)]))
    assert [c.desloca for c in p.cortes] == [0, 0]
