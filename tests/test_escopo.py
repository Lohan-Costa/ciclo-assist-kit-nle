"""O escopo de busca: só o que está nas bins do projeto ABERTO.

⭐ Decisão do editor em 2026-09-13. O que estes testes travam não é o filtro — é o
comportamento nas bordas, que é onde um filtro de busca faz estrago:

- ⛔ "não sei qual é o projeto" tem de ser SEM FILTRO, nunca "nenhuma mídia": um editor
  com o Media Composer fechado não pode ver o acervo dele sumir;
- ⛔ a foto de uma varredura antiga NÃO vale como projeto aberto — foi exatamente o que
  havia na máquina em 2026-09-13 (foto do `_ASSIST ANTERIOR`, de dois dias antes, com o
  editor trabalhando noutro projeto);
- ⚠️ e toda resposta estreitada diz que foi estreitada, senão "não achei" vira "não
  existe".
"""

from __future__ import annotations

import time

import pytest

from cicloassist.avid import bins as B
from cicloassist.avid import escopo as ESC
from cicloassist.midia import cache as C
from cicloassist.midia import decupagem as D
#: ⭐ A função VERDADEIRA, capturada no import: o `conftest` troca `escopo.projeto_aberto`
#: por "sem projeto" em todo teste, e aqui há dois que precisam exercitar a de verdade.
PROJETO_ABERTO = ESC.projeto_aberto

UMA = C.de_umid("0x060A2B340101010101010F0013000000C6D91F0BB8ABB1C7ABEE2FFBA70D1E05")
OUTRA = C.de_umid("0x060A2B340101010101010F0013000000E56E1D13D305BE564AEC678A24E90A70")


@pytest.fixture
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    ESC.esquecer()
    yield tmp_path
    ESC.esquecer()


def com_projeto(monkeypatch, caminho: str, masters: dict):
    """O Media Composer respondendo `caminho`, e as bins dele contendo `masters`."""
    monkeypatch.setattr(ESC, "projeto_aberto", lambda *a, **k: caminho)
    monkeypatch.setattr(ESC._bins, "varrer", lambda p, *a, **k: dict(masters))


# ── o que "não sei" quer dizer ───────────────────────────────────────────────

def test_sem_lista_tudo_passa():
    """⛔ `chaves=None` é "não filtre", e `frozenset()` seria "o projeto está vazio"."""
    assert ESC.Escopo(chaves=None).cobre("qualquer")
    assert not ESC.Escopo(chaves=frozenset()).cobre("qualquer")
    assert not ESC.Escopo(chaves=None).filtra


def test_sem_projeto_e_sem_varredura_nao_filtra(cache_isolado, monkeypatch):
    monkeypatch.setattr(ESC, "projeto_aberto", lambda *a, **k: ESC.SEM_PROJETO)
    escopo = ESC.agora()
    assert escopo.chaves is None
    assert escopo.cobre(UMA)
    # ⚠️ E o aviso diz que a busca está larga, em vez de deixar parecer recortada.
    assert "TODO o cache" in escopo.aviso


# ── o projeto aberto ganha da foto ───────────────────────────────────────────

def test_le_as_bins_do_projeto_aberto(cache_isolado, monkeypatch):
    com_projeto(monkeypatch, "D:/proj/HOJE", {UMA: {"nome": "C001"}})
    escopo = ESC.agora()
    assert escopo.origem == "projeto"
    assert escopo.cobre(UMA) and not escopo.cobre(OUTRA)
    assert escopo.nome_do_projeto == "HOJE"
    assert "HOJE" in escopo.aviso


def test_a_foto_de_outro_projeto_nao_manda(cache_isolado, monkeypatch):
    """⛔⛔ O defeito que motivou o módulo: a varredura guardada era de OUTRO projeto."""
    B.guardar("D:/proj/ONTEM", {OUTRA: {"nome": "de ontem"}}, raiz=cache_isolado)
    com_projeto(monkeypatch, "D:/proj/HOJE", {UMA: {"nome": "de hoje"}})

    escopo = ESC.agora()
    assert escopo.cobre(UMA)
    assert not escopo.cobre(OUTRA)


def test_a_varredura_do_projeto_fica_guardada(cache_isolado, monkeypatch):
    """⭐ Quem leu as bins para buscar deixa a leitura pronta para a aba Vetores."""
    com_projeto(monkeypatch, "D:/proj/HOJE", {UMA: {"nome": "C001"}})
    ESC.agora()
    guardado = B.ler(cache_isolado)
    assert guardado["projeto"] == "D:/proj/HOJE"
    assert list(guardado["masters"]) == [UMA]


def test_sem_media_composer_cai_para_a_foto_dizendo_que_e_foto(cache_isolado, monkeypatch):
    B.guardar("D:/proj/ONTEM", {OUTRA: {"nome": "de ontem"}}, raiz=cache_isolado)
    monkeypatch.setattr(ESC, "projeto_aberto", lambda *a, **k: ESC.SEM_PROJETO)

    escopo = ESC.agora()
    assert escopo.origem == "foto"
    assert escopo.cobre(OUTRA) and not escopo.cobre(UMA)
    # ⚠️ A procedência muda: isto não é o projeto aberto, é o que se sabia.
    assert escopo.como_dicionario()["confianca"] == "inferido"
    assert "ONTEM" in escopo.aviso and "projeto errado" in escopo.aviso


def test_projeto_aberto_sem_bin_legivel_cai_para_a_foto(cache_isolado, monkeypatch):
    """Projeto novo, ainda sem bin: melhor a foto (que se identifica) que nada."""
    B.guardar("D:/proj/ONTEM", {OUTRA: {}}, raiz=cache_isolado)
    com_projeto(monkeypatch, "D:/proj/VAZIO", {})
    assert ESC.agora().origem == "foto"


# ── o cache de processo ──────────────────────────────────────────────────────

def test_nao_varre_as_bins_duas_vezes_no_mesmo_turno(cache_isolado, monkeypatch):
    """⚠️ O modelo encadeia duas buscas na mesma resposta; 0,4 s por bin vira latência."""
    quantas = []
    monkeypatch.setattr(ESC, "projeto_aberto", lambda *a, **k: "D:/proj/HOJE")
    monkeypatch.setattr(ESC._bins, "varrer",
                        lambda p, *a, **k: quantas.append(p) or {UMA: {}})

    ESC.agora()
    ESC.agora()
    assert len(quantas) == 1

    ESC.esquecer()
    ESC.agora()
    assert len(quantas) == 2


def test_a_lista_vence_quando_o_projeto_muda(cache_isolado, monkeypatch):
    com_projeto(monkeypatch, "D:/proj/HOJE", {UMA: {}})
    assert ESC.agora().cobre(UMA)

    com_projeto(monkeypatch, "D:/proj/AMANHA", {OUTRA: {}})
    escopo = ESC.agora()
    assert escopo.cobre(OUTRA) and not escopo.cobre(UMA)


def test_a_lista_velha_expira(cache_isolado, monkeypatch):
    com_projeto(monkeypatch, "D:/proj/HOJE", {UMA: {}})
    ESC.agora()
    # Uma bin criada depois tem de aparecer na mesma sessão de trabalho.
    monkeypatch.setattr(ESC, "_escopo_em_cache",
                        ESC.Escopo(chaves=frozenset({UMA}), projeto="D:/proj/HOJE",
                                   quando=int(time.time()) - ESC.VALIDADE_S - 1,
                                   origem="projeto"))
    com_projeto(monkeypatch, "D:/proj/HOJE", {UMA: {}, OUTRA: {}})
    assert ESC.agora().cobre(OUTRA)


# ── a busca na decupagem obedece ao recorte ──────────────────────────────────

def anotar(chave: str, descricao: str):
    C.Midia(chave).anotar({"trecho": "T1", "descricao": descricao,
                           "confianca": "inferido", "fonte": "visual"})


def test_procurar_nao_devolve_midia_fora_do_projeto(cache_isolado):
    anotar(UMA, "close noturno no consultório")
    anotar(OUTRA, "close noturno no consultório, de outra produção")

    todos = D.procurar(["close"], limite=10)
    assert len(todos) == 2

    so_do_projeto = D.procurar(["close"], limite=10, chaves=frozenset({UMA}))
    assert [a["chave"] for a in so_do_projeto] == [UMA]


def test_o_tamanho_do_recorte_e_o_do_mesmo_recorte(cache_isolado):
    """⚠️ "3 de 358" com a busca cobrindo 40 é um número que desmente o outro."""
    anotar(UMA, "close")
    anotar(OUTRA, "geral")
    assert D.quantas_decupadas() == (2, 2)
    assert D.quantas_decupadas(chaves=frozenset({UMA})) == (1, 1)


def test_o_media_composer_fechado_so_e_perguntado_uma_vez(cache_isolado, monkeypatch):
    """⛔ MEDIDO em 2026-09-14: com o MC fechado, `projeto_aberto()` leva 2,0 s até o gRPC
    desistir — e isso acontecia a CADA busca. Duas ferramentas no mesmo turno gastavam 4 s
    para descobrir duas vezes a mesma ausência."""
    perguntas = []

    def sem_mc(*a, **k):
        perguntas.append(1)
        return ESC.SEM_PROJETO

    monkeypatch.setattr(ESC, "projeto_aberto", sem_mc)
    ESC.agora()
    ESC.agora()
    assert len(perguntas) == 1


def test_mas_a_ausencia_expira_rapido(cache_isolado, monkeypatch):
    """⚠️ O editor que acabou de abrir o Media Composer não pode esperar cinco minutos
    para a busca achar o projeto dele: a ausência vale meio minuto, não a validade cheia."""
    assert ESC.VALIDADE_SEM_PROJETO_S < ESC.VALIDADE_S

    monkeypatch.setattr(ESC, "projeto_aberto", lambda *a, **k: ESC.SEM_PROJETO)
    ESC.agora()
    monkeypatch.setattr(ESC, "_escopo_em_cache",
                        ESC.Escopo(chaves=None,
                                   lido_em=time.time() - ESC.VALIDADE_SEM_PROJETO_S - 1))
    com_projeto(monkeypatch, "D:/proj/HOJE", {UMA: {}})
    assert ESC.agora().origem == "projeto"


def test_a_ausencia_e_guardada_no_proprio_projeto_aberto(cache_isolado, monkeypatch):
    """⛔⛔ Não bastava guardá-la em `agora()`: o caminho da busca passa por
    `projeto_aberto()` **quatro vezes** (os recortes, se dá para indexar, se estão prontos,
    e a taxa do projeto).

    MEDIDO em 2026-09-22 com o Media Composer fechado: uma busca da aba custava **8,47 s**,
    quatro idas ao gRPC gastando 2 s cada para descobrir a MESMA ausência — contra 0,3–0,4 s
    de uma busca quente. Depois deste conserto: 0,19 s.
    """
    tentativas = []

    class SemMC:
        def __enter__(self):
            tentativas.append(1)
            raise ESC.McApiErro("o Media Composer não respondeu")

        def __exit__(self, *a):
            return False

    # ⚠️ O `conftest` troca `projeto_aberto` por um duplo: aqui queremos a função de verdade.
    monkeypatch.undo()
    ESC.esquecer()
    monkeypatch.setattr(ESC, "MediaComposer", SemMC)

    assert ESC.projeto_aberto() == ESC.SEM_PROJETO
    for _ in range(5):
        assert ESC.projeto_aberto() == ESC.SEM_PROJETO
    assert len(tentativas) == 1, "perguntou de novo ao Media Composer que não está lá"

    # ⚠️ `recarregar=True` continua furando o cache — é como `agora()` nota a troca.
    ESC.projeto_aberto(recarregar=True)
    assert len(tentativas) == 2
    # E vencida a validade, pergunta-se outra vez: quem acabou de abrir o MC não espera.
    monkeypatch.setattr(ESC, "_sem_projeto_ate", time.time() - 1)
    ESC.projeto_aberto()
    assert len(tentativas) == 3


def test_sem_projeto_e_sem_foto_a_busca_fica_no_banco_do_AVID(cache_isolado, monkeypatch):
    """⛔⛔ A regra *"não sei ≠ nenhuma"* existe para que desconhecer o projeto não esconda
    o acervo do editor — ela nunca autorizou mostrar o acervo do OUTRO editor.

    O Premiere já tinha o teto (`_so_o_banco`); o Avid não, e sem bins lidas devolvia
    entradas do banco do Premiere, com o nome de arquivo dele.
    """
    from cicloassist.midia import cache as C

    do_avid = C.Midia("a" * 64, origem="avid", rotulo={"nome": "DA CÂMERA"})
    do_avid.pasta  # noqa: B018
    do_premiere = C.Midia("b" * 64, origem="premiere", rotulo={"nome": "IMPORTADO.mp4"})
    do_premiere.pasta  # noqa: B018

    recorte = ESC.agora()
    assert recorte.origem == "banco"
    assert do_avid.chave in (recorte.chaves or set())
    assert do_premiere.chave not in (recorte.chaves or set())
    assert "Media Composer" in recorte.aviso and "TODO o cache" not in recorte.aviso


def test_banco_vazio_continua_sendo_sem_filtro(cache_isolado):
    """⚠️ No primeiro dia não há entrada nenhuma, e filtrar por um conjunto VAZIO faria a
    busca responder "não achei" sobre um cache que ela nem olhou."""
    recorte = ESC.agora()
    assert recorte.chaves is None and recorte.origem == "nenhum"


def test_a_taxa_do_projeto_nao_paga_grpc_sem_projeto(cache_isolado, monkeypatch):
    """⛔ `nle.taxa_do_projeto` abria o Media Composer DIRETO, sem passar pelo cache de
    ausência — uma ida de 2 s por busca, para uma resposta que é `None` de qualquer jeito.

    ⚠️ E isso vazava para a SUÍTE: o `conftest` isola o MC trocando `escopo.projeto_aberto`,
    e esta função não passava por lá. Com o conserto, a suíte caiu de 67 s para 31 s.
    """
    from cicloassist import nle as N
    from cicloassist.avid import mcapi

    def nao_pode(*a, **k):
        raise AssertionError("foi ao Media Composer sem projeto aberto")

    monkeypatch.setattr(mcapi.MediaComposer, "__enter__", nao_pode)
    assert N.taxa_do_projeto("avid") is None


def test_trocar_de_projeto_e_notado_sem_reiniciar(cache_isolado, monkeypatch):
    """⛔⛔ O cache do projeto não pode ser eterno desde que a BUSCA depende dele: um
    caminho preso faria `procurar_no_material` responder com o material do projeto
    anterior, calado, com o editor olhando as bins do novo."""
    aberto = ["D:/proj/HOJE"]
    perguntas = []

    def qual_projeto(recarregar=False):
        perguntas.append(recarregar)
        return aberto[0]

    monkeypatch.setattr(ESC, "projeto_aberto", qual_projeto)
    monkeypatch.setattr(ESC._bins, "varrer",
                        lambda p, *a, **k: {UMA: {}} if p.endswith("HOJE") else {OUTRA: {}})

    assert ESC.agora().cobre(UMA)

    # O editor fecha um projeto e abre outro; ninguém reinicia o serviço.
    aberto[0] = "D:/proj/OUTRO"
    monkeypatch.setattr(ESC, "_escopo_em_cache",
                        ESC.Escopo(chaves=frozenset({UMA}), projeto="D:/proj/HOJE",
                                   origem="projeto",
                                   lido_em=time.time() - ESC.VALIDADE_S - 1))
    escopo = ESC.agora()
    assert escopo.projeto == "D:/proj/OUTRO"
    assert escopo.cobre(OUTRA) and not escopo.cobre(UMA)
    # ⭐ E a pergunta cara ao Media Composer só acontece quando a lista vence.
    assert perguntas[-1] is True


def test_o_caminho_do_projeto_e_relido_so_quando_se_pede(monkeypatch):
    """O cache existe porque cada consulta custa ~500 ms; `recarregar` é quem o fura."""
    respostas = ["D:/proj/UM", "D:/proj/DOIS"]

    class MCFalso:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def projeto(self):
            return {"caminho": respostas.pop(0)}

    monkeypatch.setattr(ESC, "MediaComposer", MCFalso)
    assert PROJETO_ABERTO() == "D:/proj/UM"
    assert PROJETO_ABERTO() == "D:/proj/UM"          # do cache, sem gRPC
    assert PROJETO_ABERTO(recarregar=True) == "D:/proj/DOIS"


def test_sem_media_composer_a_falha_nao_fica_cacheada(monkeypatch):
    """⚠️ Cachear a FALHA faria o plugin dizer "não há projeto" para sempre a quem abriu o
    Media Composer logo depois; quem cacheia a ausência por pouco tempo é `agora()`."""
    class Recusa:
        def __enter__(self):
            raise ESC.McApiErro("o Media Composer não atendeu")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ESC, "MediaComposer", Recusa)
    assert PROJETO_ABERTO() == ESC.SEM_PROJETO
    assert ESC.em_cache() == ""


def test_select_project_nao_vira_projeto_eterno(monkeypatch):
    """⛔ 2026-11-02: o MC na Select Project (sem caminho) ficava guardado como "sem-projeto" e o
    topo da janela o mostrou com o FLUXO F1B já aberto. A ausência expira; o projeto, não."""
    respostas = ["", "D:/proj/FLUXO F1B"]

    class MCFalso:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def projeto(self):
            return {"caminho": respostas.pop(0)}

    monkeypatch.setattr(ESC, "MediaComposer", MCFalso)
    monkeypatch.setattr(ESC, "_projeto_em_cache", "")
    monkeypatch.setattr(ESC, "_sem_projeto_ate", 0.0)
    assert PROJETO_ABERTO() == ESC.SEM_PROJETO and ESC.em_cache() == ""
    monkeypatch.setattr(ESC, "_sem_projeto_ate", 0.0)           # passaram os 30 s
    assert PROJETO_ABERTO() == "D:/proj/FLUXO F1B"


# ── a rota que o painel usa para notar a troca ───────────────────────────────
#
# ⛔ Não há evento de projeto no Media Composer (banco: o sniffer de 2026-08-07 mapeou os
# eventos do canal `general` e mediu que ampliar o usesApi aos cinco canais não acrescenta
# tipo nenhum), e perguntar custa 0,5–0,75 s. Quem pergunta é um gesto do editor.

def rota_projeto():
    import json

    from cicloassist.servico import rotas as R
    return json.loads(R.rota_projeto(None).corpo.decode("utf-8"))


def test_a_rota_diz_quando_o_projeto_mudou(cache_isolado, monkeypatch):
    aberto = ["D:/proj/HOJE"]
    monkeypatch.setattr(ESC, "projeto_aberto",
                        lambda recarregar=False: aberto[0])
    monkeypatch.setattr(ESC._bins, "varrer",
                        lambda p, *a, **k: {UMA: {}} if p.endswith("HOJE") else {OUTRA: {}})

    ESC.agora()                       # o painel já tinha lido este projeto
    d = rota_projeto()
    assert d["mudou"] is False and d["nome"] == "HOJE"

    aberto[0] = "D:/proj/OUTRO"
    d = rota_projeto()
    assert d["mudou"] is True and d["nome"] == "OUTRO"
    # ⛔ E a lista do projeto anterior cai NA HORA, sem esperar a validade: mantê-la faria
    #    a busca responder com o material do projeto que ele acabou de fechar.
    assert d["escopo"]["masters_no_projeto"] == 1
    assert ESC.agora().cobre(OUTRA) and not ESC.agora().cobre(UMA)


def test_primeira_olhada_nao_conta_como_troca(cache_isolado, monkeypatch):
    """⚠️ Sem projeto conhecido antes, "mudou" seria um recado de troca no primeiro
    carregamento da aba — e o editor não trocou nada."""
    monkeypatch.setattr(ESC, "projeto_aberto", lambda recarregar=False: "D:/proj/HOJE")
    monkeypatch.setattr(ESC._bins, "varrer", lambda p, *a, **k: {UMA: {}})
    assert rota_projeto()["mudou"] is False
