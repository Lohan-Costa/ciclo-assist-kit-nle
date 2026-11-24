"""O agrupamento por cena e a escrita de uma bin por cena.

⚠️ Todo teste de escrita aqui **reabre** a bin e conta subclipes. Um teste que só
confira o dicionário devolvido por `escrever()` estaria conferindo a intenção do
código, não o arquivo que o editor vai abrir.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataclasses import replace

import pytest

from avid.percurso import e_subclipe
from avid.leitura import abrir

from avid import cenas
from avid.takes import Tomada


def _com(original: Tomada, **campos) -> Tomada:
    return replace(original, **campos)


def test_agrupa_por_cena_da_claquete(takes_de_exemplo):
    grupos = cenas.agrupar(takes_de_exemplo)
    assert set(grupos) == {"C04", "C07"}
    assert len(grupos["C04"]) == 2
    assert len(grupos["C07"]) == 1


def test_dentro_da_cena_a_ordem_e_plano_depois_take(takes_de_exemplo):
    """⭐ A bin do Avid ordena lexicograficamente, e é por isso que `P01`/`T002` têm
    dois dígitos (§10). Este teste é o que garante que a ordenação de dentro do nosso
    agrupamento concorda com a que o editor vai ver na tela."""
    base = takes_de_exemplo[0]
    fora_de_ordem = [
        _com(base, nome="C04_P10_T001", plano="P10", take="T001"),
        _com(base, nome="C04_P02_T003", plano="P02", take="T003"),
        _com(base, nome="C04_P02_T001", plano="P02", take="T001"),
    ]
    grupos = cenas.agrupar(fora_de_ordem)
    assert [t.nome for t in grupos["C04"]] == \
        ["C04_P02_T001", "C04_P02_T003", "C04_P10_T001"]


def test_take_sem_cena_vai_para_a_bin_de_NAO_RESOLVIDO(takes_de_exemplo):
    """⚠️ §11: claquete ilegível não é erro. O take não some — ele fica visível numa
    bin própria, para o editor apontar à mão."""
    orfao = _com(takes_de_exemplo[0], nome="GRAVACAO 001", cena=None, plano=None,
                 take=None, convencao=None)
    grupos = cenas.agrupar([orfao])
    assert set(grupos) == {cenas.BIN_NAO_RESOLVIDO}


def test_o_orfao_de_imagem_vai_para_a_bin_ORFAOS(takes_de_exemplo):
    """⭐ A bin nova de 2026-08-26, e ela existe porque `NAO RESOLVIDO` estava
    misturando duas coisas de causas diferentes:

    · **NAO RESOLVIDO** — havia claquete, e ela não casou convenção nenhuma. O
      conserto é humano: o editor lê o nome e aponta a cena.
    · **ORFAOS** — a sincronização não pareou este material. Não há claquete que
      pudesse ter sido lida; é um clipe de câmera que rodou sem som direto por baixo.
      O conserto, se houver, é outro: sincronizar de novo, ou aceitar.

    ⚠️ Foi essa mistura que o autor não entendeu ao abrir a bin no Avid — e com razão:
    os 26 itens lá dentro não eram claquete ilegível nenhuma.
    """
    orfao = _com(takes_de_exemplo[0], nome="a001_03170214_C001", cena=None,
                 plano=None, take=None, convencao=None, orfao=True)
    grupos = cenas.agrupar([orfao])
    assert set(grupos) == {cenas.BIN_ORFAOS}


def test_o_take_com_cena_e_sem_camera_FICA_na_bin_da_cena(takes_de_exemplo):
    """⚠️⚠️ Um take de som com claquete boa, que nenhuma câmera cobriu, É órfão — e
    mesmo assim pertence à SUA CENA. Roteá-lo por `orfao` antes de por `cena` o
    esconderia da cena onde o editor vai procurá-lo, que é exatamente o dano que a
    bin `NAO RESOLVIDO` já causava."""
    so_som = _com(takes_de_exemplo[0], orfao=True)
    assert so_som.cena == "C04"
    grupos = cenas.agrupar([so_som])
    assert set(grupos) == {"C04"}


def test_o_descarte_vence_o_orfao(takes_de_exemplo):
    """A precedência declarada: descarte primeiro, cena depois, órfão só então."""
    descartado = _com(takes_de_exemplo[0], cena=None, plano=None, take=None,
                      convencao=None, orfao=True, descartado=True)
    grupos = cenas.agrupar([descartado])
    assert set(grupos) == {cenas.BIN_DESCARTE}


def test_uma_bin_por_causa_e_nao_uma_bin_so(takes_de_exemplo):
    """⚠️ Guarda de não-fusão: com um take de cada tipo saem TRÊS bins distintas, e é
    por nome. Um `agrupar` que jogasse órfão e não resolvido na mesma chave passaria
    em qualquer teste que só contasse itens."""
    base = takes_de_exemplo[0]
    grupos = cenas.agrupar([
        base,
        _com(base, nome="GRAVACAO 001", cena=None, plano=None, take=None,
             convencao=None),
        _com(base, nome="a001_03170214_C001", cena=None, plano=None, take=None,
             convencao=None, orfao=True),
    ])
    assert set(grupos) == {"C04", cenas.BIN_NAO_RESOLVIDO, cenas.BIN_ORFAOS}
    assert [t.nome for t in grupos[cenas.BIN_ORFAOS]] == ["a001_03170214_C001"]
    assert [t.nome for t in grupos[cenas.BIN_NAO_RESOLVIDO]] == ["GRAVACAO 001"]


def test_take_descartado_nao_entra_na_bin_da_cena(takes_de_exemplo):
    """⭐ O descarte do som é `confirmado`, não heurística (§6/Camada 3). Um take em
    `FALSE TAKE` sai da bin da cena — mas não é apagado: vai para a de descarte, onde
    o editor o encontra se discordar."""
    descartado = _com(takes_de_exemplo[0], descartado=True)
    grupos = cenas.agrupar([descartado, takes_de_exemplo[1]])
    assert set(grupos) == {cenas.BIN_DESCARTE, "C04"}
    assert [t.nome for t in grupos[cenas.BIN_DESCARTE]] == [descartado.nome]


def test_descarte_NAO_AVALIADO_fica_na_bin_da_cena(takes_de_exemplo):
    """⚠️⚠️ `None` não é `True`. Um take cujo descarte não foi avaliado continua na
    cena — tirá-lo dali seria tratar "não sei" como "está no lixo", que é a mesma
    inversão que o §7 proíbe na direção contrária."""
    nao_avaliado = _com(takes_de_exemplo[0], descartado=None)
    grupos = cenas.agrupar([nao_avaliado])
    assert set(grupos) == {"C04"}


def test_escreve_uma_bin_por_cena(tmp_path, takes_de_exemplo):
    r = cenas.escrever(takes_de_exemplo, str(tmp_path))

    assert r["total"] == 3
    nomes = {b["cena"] for b in r["bins"]}
    assert nomes == {"C04", "C07"}

    for bin_escrita in r["bins"]:
        with abrir(bin_escrita["caminho"]) as f:
            achados = [m.name for m in f.content.mobs if e_subclipe(m)]
        assert len(achados) == bin_escrita["takes"], (
            f"{bin_escrita['cena']}: o relatório diz {bin_escrita['takes']} take(s) "
            f"e a bin relida tem {len(achados)}")

    with abrir(dict((b["cena"], b["caminho"]) for b in r["bins"])["C04"]) as f:
        assert sorted(m.name for m in f.content.mobs if e_subclipe(m)) == \
            ["C04_P01_T001", "C04_P01_T002"]


def test_o_arquivo_da_cena_se_chama_pela_cena(tmp_path, takes_de_exemplo):
    from pathlib import Path

    r = cenas.escrever(takes_de_exemplo, str(tmp_path))
    arquivos = {Path(b["caminho"]).name for b in r["bins"]}
    assert arquivos == {"C04.avb", "C07.avb"}


def test_segunda_rodada_nao_sobrescreve_a_primeira(tmp_path, takes_de_exemplo):
    """⚠️⚠️ Medido e caro: `OpenBin` numa bin JÁ ABERTA devolve `Completed` e **não
    relê o disco** — o MC continua servindo a cópia em memória. Sobrescrever `C04.avb`
    depois do checkpoint 2 destruiria as correções do editor E o MC nem mostraria a
    versão nova. Nome novo, sempre."""
    from pathlib import Path

    primeira = cenas.escrever(takes_de_exemplo, str(tmp_path))
    segunda = cenas.escrever(takes_de_exemplo, str(tmp_path))

    caminhos_1 = {b["caminho"] for b in primeira["bins"]}
    caminhos_2 = {b["caminho"] for b in segunda["bins"]}
    assert not (caminhos_1 & caminhos_2)
    assert "C04 2.avb" in {Path(c).name for c in caminhos_2}
    # E a primeira continua lá, intacta.
    for caminho in caminhos_1:
        assert Path(caminho).exists()


def test_caminho_de_bin_livre(tmp_path):
    assert cenas.caminho_de_bin_livre(str(tmp_path), "C04").endswith("C04.avb")
    (tmp_path / "C04.avb").write_bytes(b"")
    assert cenas.caminho_de_bin_livre(str(tmp_path), "C04").endswith("C04 2.avb")
    (tmp_path / "C04 2.avb").write_bytes(b"")
    assert cenas.caminho_de_bin_livre(str(tmp_path), "C04").endswith("C04 3.avb")


def test_lista_vazia_nao_escreve_bin_nenhuma(tmp_path):
    """⚠️⚠️ Guarda de vacuidade do produtor: zero takes é um resultado explícito, e
    não um punhado de bins vazias que o editor abre sem entender."""
    from pathlib import Path

    pasta = Path(tmp_path) / "CENAS"
    r = cenas.escrever([], str(pasta))
    assert r["total"] == 0
    assert r["bins"] == []
    assert r["orfaos"] == 0
    # ⚠️ E a pasta NEM É CRIADA. Sem a guarda de saída antecipada o `mkdir` roda
    # assim mesmo, e o editor ganha uma pasta `CENAS` vazia no projeto para informar
    # um não-evento. Mutação (2026-08-26): remover a guarda deixava tudo verde —
    # o relatório sai idêntico pelo caminho geral, só a pasta sobrava.
    assert not pasta.exists(), "criou a pasta de cenas para não escrever nada nela"


def test_o_progresso_e_chamado_uma_vez_por_bin_e_fecha_no_total(tmp_path,
                                                                takes_de_exemplo):
    """⭐ É este callback que move a barra do painel — `Sessao._progresso_de_cena` o
    repassa para `estado.feito/total`. Sem ele o editor vê "organizando…" parado até o
    fim, e uma tarefa que parece travada é uma tarefa que ele mata no meio.

    ⚠️ A última chamada fecha em `feito == total`: sem ela a barra congela em 2/3 com
    o trabalho já pronto. Mutação (2026-08-26): apagar as chamadas deixava a suíte
    inteira verde — nenhum teste olhava o callback.
    """
    chamadas = []
    cenas.escrever(takes_de_exemplo, str(tmp_path / "CENAS"),
                   progresso=lambda feito, total, nome: chamadas.append(
                       (feito, total, nome)))

    assert chamadas, "o callback de progresso nunca foi chamado"
    totais = {t for _f, t, _n in chamadas}
    assert totais == {2}, f"o total mudou no meio do caminho: {totais}"
    assert [f for f, _t, _n in chamadas] == [0, 1, 2], \
        "o progresso tem de andar 0→1→2, uma vez por bin mais o fechamento"
    assert [n for _f, _t, n in chamadas] == ["C04", "C07", ""], \
        "cada chamada nomeia a bin que está sendo escrita; a última fecha com vazio"


def test_o_relatorio_conta_o_que_saiu_da_cena(tmp_path, takes_de_exemplo):
    """O painel mostra estes dois números no checkpoint 2. Sem eles, um take que caiu
    em `NAO RESOLVIDO` desapareceria da vista do editor."""
    orfao = _com(takes_de_exemplo[0], nome="GRAVACAO 001", cena=None, plano=None,
                 take=None, convencao=None)
    descartado = _com(takes_de_exemplo[1], descartado=True)

    r = cenas.escrever([orfao, descartado, takes_de_exemplo[2]], str(tmp_path))
    assert r["nao_resolvidos"] == 1
    assert r["descartados"] == 1
    assert r["total"] == 3


def test_a_bin_de_cena_e_autossuficiente_quando_ha_base(tmp_path, takes_de_exemplo,
                                                        bin_de_masters):
    """Com `base`, cada bin de cena leva os masters junto. ⚠️ É a saída conhecida se
    a Task 8 descobrir que o MC não resolve subclipe cujo master mora noutra bin."""
    from avid.percurso import e_master

    r = cenas.escrever(takes_de_exemplo, str(tmp_path), base=str(bin_de_masters))
    for bin_escrita in r["bins"]:
        with abrir(bin_escrita["caminho"]) as f:
            assert sum(1 for m in f.content.mobs if e_master(m)) == 4
