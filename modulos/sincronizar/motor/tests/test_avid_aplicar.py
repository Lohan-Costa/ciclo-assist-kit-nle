"""O `aplicar` — a única parte da aba Renomear que ESCREVE no projeto do editor.

⚠️ Nada aqui abre o Media Composer: o cliente é substituído por um duplo que
registra o que foi chamado. O que estes testes medem é justamente o que um teste
de integração esconderia — quantas chamadas saíram, em que ordem, e quais NÃO
saíram.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from avid import renomear as R
from avid.mcapi import McApiError

BIN_A = r"C:\Proj\CAM A.avb"
BIN_B = r"C:\Proj\SOM.avb"


class _McFalso:
    """Registra tudo o que o `aplicar` pede ao Media Composer."""

    def __init__(self, falhar_em=()):
        self.renomeados = []      # [(mob_id, nome)]
        self.abertas = []         # bins ativadas
        self.salvamentos = 0
        self.colunas_criadas = 0  # ⛔ tem de continuar ZERO
        self._falhar_em = set(falhar_em)

    def renomear_item(self, mob_id, nome):
        if mob_id in self._falhar_em:
            raise McApiError("Unable to modify column data.")
        self.renomeados.append((mob_id, nome))

    def abrir_bin(self, caminho):
        self.abertas.append(caminho)

    def salvar_bin_ativa(self):
        self.salvamentos += 1
        return True

    # Se o `aplicar` um dia chamar isto, o teste abaixo denuncia.
    def criar_coluna(self, *a, **k):                      # pragma: no cover
        self.colunas_criadas += 1
        return True


def _plano(*trios):
    return [{"mob_id": m, "bin": b, "nome_atual": a, "nome_novo": n}
            for m, b, a, n in trios]


def test_so_o_que_MUDA_vai_ao_Media_Composer():
    """⚠️ Num lote de 50 em que 3 mudam, 47 escritas seriam gRPC jogado fora — e
    sujariam a bin sem motivo."""
    mc = _McFalso()
    r = R.aplicar(mc, _plano(("a", BIN_A, "X", "X"),
                             ("b", BIN_A, "Y", "Y2"),
                             ("c", BIN_A, "Z", "Z")),
                  confirmar=False)

    assert [n for _, n in mc.renomeados] == ["Y2"]
    assert r["aplicados"] == 1
    assert r["inalterados"] == 2


def test_UM_Save_Bin_por_bin_tocada_e_nao_por_item():
    """⚠️ Salvar a cada item faria o Media Composer gravar o arquivo N vezes."""
    mc = _McFalso()
    R.aplicar(mc, _plano(("a", BIN_A, "1", "1n"),
                         ("b", BIN_A, "2", "2n"),
                         ("c", BIN_A, "3", "3n")),
              confirmar=False)

    assert mc.salvamentos == 1
    assert mc.abertas == [BIN_A]


def test_DUAS_bins_recebem_DOIS_salvamentos():
    """⚠️⚠️ A divergência deliberada contra o Assist anterior: lá o arrasto vem de
    uma bin só e um Save Bin basta. Aqui o editor pode arrastar de bins
    diferentes sem perceber, e salvar só a última deixaria a outra com o
    asterisco no nome — com a confirmação falhando para ela."""
    mc = _McFalso()
    R.aplicar(mc, _plano(("a", BIN_A, "1", "1n"),
                         ("b", BIN_B, "2", "2n")),
              confirmar=False)

    assert mc.salvamentos == 2
    assert mc.abertas == [BIN_A, BIN_B]


def test_uma_falha_nao_derruba_o_resto_e_e_reportada_POR_ITEM():
    """⚠️ Sumir do relatório seria pior que falhar: a bin fica em dois estados, e
    a lista é o único jeito de o editor saber onde parou."""
    mc = _McFalso(falhar_em={"b"})
    r = R.aplicar(mc, _plano(("a", BIN_A, "1", "1n"),
                             ("b", BIN_A, "2", "2n"),
                             ("c", BIN_A, "3", "3n")),
                  confirmar=False)

    assert r["aplicados"] == 2
    assert [f["mob_id"] for f in r["falhas"]] == ["b"]
    assert r["falhas"][0]["nome_novo"] == "2n"


def test_plano_vazio_nao_escreve_NADA():
    mc = _McFalso()
    r = R.aplicar(mc, [], confirmar=False)
    assert (mc.renomeados, mc.salvamentos, mc.abertas) == ([], 0, [])
    assert r == {"aplicados": 0, "inalterados": 0, "falhas": [],
                 "confirmado": False, "erro": ""}


def test_a_bin_do_editor_NAO_GANHA_COLUNA_NENHUMA():
    """⛔⛔ A decisão do autor, virada teste.

    `CreateCustomColumn` cria uma coluna NOVA a cada chamada — nove homônimas na
    bin de teste, medido — e o MCAPI não tem rpc de apagar coluna. O desfazer
    mora fora da bin, e este teste é o que impede alguém de "melhorar" o aplicar
    guardando o nome antigo ali dentro."""
    mc = _McFalso()
    R.aplicar(mc, _plano(("a", BIN_A, "1", "1n")), confirmar=False)
    assert mc.colunas_criadas == 0


def test_o_progresso_e_chamado_POR_ITEM_e_fecha_no_total():
    mc = _McFalso()
    vistos = []
    R.aplicar(mc, _plano(("a", BIN_A, "1", "1n"), ("b", BIN_A, "2", "2n")),
              progresso=lambda f, t, n: vistos.append((f, t)), confirmar=False)

    assert vistos[0] == (0, 2)
    assert vistos[-1] == (2, 2), "a barra fecha no fim, em vez de parar em 1/2"


# ── a confirmação, que é onde mora a mentira mais fácil ──────────────────────

def test_confirmar_ESPERA_o_disco_porque_o_Save_Bin_e_ASSINCRONO():
    """⚠️⚠️ `salvar_bin_ativa()` devolve True quando o DoCommand é ACEITO, não
    quando a bin está no disco. A primeira medição do spike concluiu "não
    persiste" lendo o arquivo cedo demais — e estava errada."""
    mc = _McFalso()
    tentativas = {"n": 0}

    def disco_lento(_bin):
        tentativas["n"] += 1
        return ["1n"] if tentativas["n"] >= 3 else ["1"]

    r = R.aplicar(mc, _plano(("a", BIN_A, "1", "1n")),
                  leitor_do_disco=disco_lento, espera=0)
    assert r["confirmado"] is True
    assert tentativas["n"] == 3


def test_confirmar_DESISTE_e_avisa_em_vez_de_mentir():
    """`confirmado: False` é resposta legítima: o rename ACONTECEU na sessão; o
    que não se conseguiu foi provar que chegou ao arquivo."""
    mc = _McFalso()
    r = R.aplicar(mc, _plano(("a", BIN_A, "1", "1n")),
                  leitor_do_disco=lambda _b: ["1"], tentativas=2, espera=0)

    assert r["aplicados"] == 1, "o rename aconteceu"
    assert r["confirmado"] is False, "e a tela vai ter de pedir para salvar à mão"


def test_um_leitor_que_ESTOURA_nao_derruba_o_aplicar():
    """⚠️ A bin pode estar sendo gravada agora. Falhar a LEITURA não é falhar o
    renomeamento."""
    mc = _McFalso()

    def explode(_bin):
        raise OSError("a bin está sendo gravada")

    r = R.aplicar(mc, _plano(("a", BIN_A, "1", "1n")),
                  leitor_do_disco=explode, tentativas=2, espera=0)
    assert r["aplicados"] == 1 and r["confirmado"] is False


def test_a_confirmacao_exige_TODAS_as_bins():
    """⚠️ Dar `confirmado: True` com uma bin ainda por gravar é a mentira exata
    que a releitura existe para impedir."""
    mc = _McFalso()

    def so_a_primeira_gravou(caminho):
        return ["1n"] if caminho == BIN_A else ["2"]

    r = R.aplicar(mc, _plano(("a", BIN_A, "1", "1n"), ("b", BIN_B, "2", "2n")),
                  leitor_do_disco=so_a_primeira_gravou, tentativas=2, espera=0)
    assert r["confirmado"] is False


def test_a_bin_de_um_item_que_FALHOU_nao_entra_na_confirmacao():
    """Se o único item de uma bin falhou, não há nome novo para procurar lá —
    exigi-lo daria `confirmado: False` para sempre."""
    mc = _McFalso(falhar_em={"b"})
    r = R.aplicar(mc, _plano(("a", BIN_A, "1", "1n"), ("b", BIN_B, "2", "2n")),
                  leitor_do_disco=lambda _b: ["1n"], tentativas=2, espera=0)

    assert r["confirmado"] is True
    assert BIN_B not in mc.abertas, "e nem se salva a bin em que nada mudou"


class _Mc246(_McFalso):
    """O MC 24.6: sem `DoCommand`, o Save Bin é recusado — e o `CloseBin` grava."""

    def __init__(self, **k):
        super().__init__(**k)
        self.fechadas = []

    def salvar_bin_ativa(self):
        self.salvamentos += 1
        return False

    def gravar_bin_fechando(self, caminho):
        self.fechadas.append(caminho)


def test_sem_DoCommand_a_bin_e_gravada_fechando_e_reabrindo():
    """⭐ No 24.6 o nome novo ficava só na sessão: o Save Bin é `DoCommand`, que não existe lá."""
    mc = _Mc246()
    R.aplicar(mc, _plano(("a", BIN_A, "1", "1n"),
                         ("b", BIN_B, "2", "2n"),
                         ("c", BIN_A, "3", "3n")),
              confirmar=False)
    assert mc.fechadas == [BIN_A, BIN_B]


def test_com_DoCommand_nao_fecha_bin_nenhuma():
    """O fechar-e-reabrir é o PLANO B: com o Save Bin aceito, a bin do editor não pisca."""
    mc = _McFalso()
    mc.gravar_bin_fechando = lambda c: pytest.fail("fechou a bin com o Save Bin aceito")
    R.aplicar(mc, _plano(("a", BIN_A, "1", "1n")), confirmar=False)
    assert mc.salvamentos == 1
