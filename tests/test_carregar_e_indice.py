"""Os dois defeitos que o primeiro uso com subclipes revelou (2026-09-21).

**1. ⛔⛔ Clicar duas vezes no mesmo clipe dizia que a mídia podia estar offline.**
MEDIDO com uma variável só, no Media Composer do editor: carregar A → **OK**; A de novo →
**FALHA**; carregar B → OK; A de novo → **OK**. O MC recusa o mob que JÁ é o do viewer, e a
mensagem dele (`Some mobs was skipped.`) é a MESMA de "a bin está fechada" — a frase que
significa erro num caso significa *sucesso* no outro.

**2. ⛔⛔ A busca ficava "procurando…" para sempre.** O índice de subclipes era construído
DENTRO da chamada: a aba (que aquece) e a busca entravam nele ao mesmo tempo, cada build
deixava o outro dez vezes mais lento, e o seguinte começava por cima. No log dele:
**quatro builds em um minuto**, e a busca nunca voltou.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from cicloassist.avid import subclipes as S
from cicloassist.servico import rotas as R
from cicloassist.servico.http import Pedido

CHAVE = "a" * 64


def chamar(caminho, corpo):
    r = R.ROTAS[("POST", caminho)][0](
        Pedido("POST", caminho, {}, json.dumps(corpo).encode("utf-8")))
    return json.loads(r.corpo.decode("utf-8"))


# ── 1. o clipe que já está no Source ─────────────────────────────────────────

@pytest.fixture
def midia_no_cache(tmp_path, monkeypatch):
    from cicloassist.midia import cache as C

    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    m = C.Midia(CHAVE, raiz_do_cache=tmp_path)
    m.anotar_fonte({"master": "C07_P01-T001"})
    return m


def test_carga_recusada_com_o_mob_JA_no_monitor_e_sucesso(midia_no_cache, monkeypatch):
    """⭐⭐ O defeito que o editor viu: o segundo duplo clique no mesmo clipe respondia
    *"não consegui carregar … a mídia pode estar offline"*."""
    monkeypatch.setattr(R, "_carregar_no_monitor", lambda chave, onde: False)
    monkeypatch.setattr(R, "_ja_esta_no_monitor", lambda chave: True)
    # ⛔ Se a rota perguntasse a bin antes de perguntar o monitor, abriria uma bin na tela
    #   do editor para "carregar" o que já estava carregado.
    monkeypatch.setattr(R, "_bin_do_mob", lambda chave: pytest.fail(
        "foi procurar a bin de um clipe que já estava no monitor"))

    d = chamar("/busca/carregar", {"chave": CHAVE})
    assert d["ok"] is True and d["ja_estava"] is True
    assert "erro" not in d


def test_carga_recusada_e_mob_FORA_do_monitor_segue_para_a_bin(midia_no_cache, monkeypatch):
    """⚠️ A outra causa da MESMA mensagem do MC continua valendo: bin fechada."""
    tentativas = []

    def _falha_sempre(chave, onde):
        tentativas.append(onde)
        return False

    monkeypatch.setattr(R, "_carregar_no_monitor", _falha_sempre)
    monkeypatch.setattr(R, "_ja_esta_no_monitor", lambda chave: False)
    monkeypatch.setattr(R, "_bin_do_mob", lambda chave: "CENAS/C07.avb")

    class _MC:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def _chamar(self, metodo, **kw):
            return None

    monkeypatch.setattr(R._mcapi, "MediaComposer", _MC)
    monkeypatch.setattr(R._escopo, "projeto_aberto", lambda *a, **k: "D:/proj")

    d = chamar("/busca/carregar", {"chave": CHAVE})
    assert d["ok"] is False and "CENAS/C07.avb" in d["erro"]
    assert len(tentativas) == 2, "tentou, abriu a bin, e tentou de novo"


def test_a_carga_que_funciona_de_primeira_nao_pergunta_nada(midia_no_cache, monkeypatch):
    """⚠️ `GetViewerMobs` custa ~1,1 s mais a pausa de 3 s do monitor. O caminho normal —
    um clipe novo — não pode pagar isso."""
    def _nao_devia(chave):
        pytest.fail("perguntou o monitor num carregamento que deu certo")

    monkeypatch.setattr(R, "_carregar_no_monitor", lambda chave, onde: True)
    monkeypatch.setattr(R, "_ja_esta_no_monitor", _nao_devia)

    d = chamar("/busca/carregar", {"chave": CHAVE})
    assert d["ok"] is True and d.get("ja_estava") is not True


# ── 2. o índice que não pode travar a busca ──────────────────────────────────

@pytest.fixture(autouse=True)
def indice_limpo():
    S.esquecer()
    yield
    S.esquecer()


def test_um_build_por_projeto_mesmo_com_varios_pedindo(tmp_path, monkeypatch):
    """⛔⛔ O defeito: a aba e a busca entravam no build ao mesmo tempo, e cada um deixava
    o outro dez vezes mais lento. Quatro builds em um minuto no log do editor."""
    builds = []

    def _montar_devagar(pasta):
        builds.append(time.monotonic())
        time.sleep(0.4)
        return {"chave": []}

    monkeypatch.setattr(S, "_montar", _montar_devagar)
    monkeypatch.setattr(S, "_assinatura", lambda pasta: ("marca",))

    fios = [threading.Thread(target=lambda: S.indice(tmp_path)) for _ in range(6)]
    for f in fios:
        f.start()
    for f in fios:
        f.join(timeout=5)

    time.sleep(0.8)
    assert len(builds) == 1, f"seis pedidos, {len(builds)} builds"


def test_a_busca_NAO_espera_o_indice(tmp_path, monkeypatch):
    """⛔⛔ `esperar=0` é o conserto: quem pede com o índice frio recebe `{}` na hora e o
    build corre no fundo. O editor ficou com "procurando…" para sempre sem isto."""
    monkeypatch.setattr(S, "_montar", lambda pasta: time.sleep(3) or {"x": []})
    monkeypatch.setattr(S, "_assinatura", lambda pasta: ("marca",))

    t0 = time.monotonic()
    saida = S.indice(tmp_path)
    gasto = time.monotonic() - t0

    assert saida == {}, "sem índice ainda, e isso é uma resposta"
    assert gasto < 0.5, f"a busca esperou {gasto:.1f}s pelo índice"
    assert S.esta_pronto(tmp_path) is False


def test_o_aquecimento_PODE_esperar(tmp_path, monkeypatch):
    """⭐ A rota que roda ao abrir a aba espera, porque ali ninguém olha o relógio."""
    monkeypatch.setattr(S, "_montar", lambda pasta: {"x": []})
    monkeypatch.setattr(S, "_assinatura", lambda pasta: ("marca",))

    saida = S.indice(tmp_path, esperar=10)
    assert saida == {"x": []} and S.esta_pronto(tmp_path) is True


def test_o_indice_VELHO_e_servido_enquanto_o_novo_monta(tmp_path, monkeypatch):
    """⚠️ Índice velho erra só no que mudou desde a última varredura; o alternativo é a
    busca perder a preferência inteira enquanto a bin é relida."""
    monkeypatch.setattr(S, "_montar", lambda pasta: {"velho": []})
    monkeypatch.setattr(S, "_assinatura", lambda pasta: ("marca-1",))
    assert S.indice(tmp_path, esperar=10) == {"velho": []}

    monkeypatch.setattr(S, "_montar", lambda pasta: time.sleep(3) or {"novo": []})
    monkeypatch.setattr(S, "_assinatura", lambda pasta: ("marca-2",))
    assert S.indice(tmp_path) == {"velho": []}, "o velho serve enquanto o novo não vem"


def test_build_que_explode_devolve_a_vaga(tmp_path, monkeypatch):
    """⛔ A vaga sai no `finally`: não devolvida, o índice trava para sempre e o sintoma é
    "os subclipes nunca ficam prontos", sem erro nenhum."""
    def _explode(pasta):
        raise RuntimeError("bin corrompida")

    monkeypatch.setattr(S, "_montar", _explode)
    monkeypatch.setattr(S, "_assinatura", lambda pasta: ("marca",))

    assert S.indice(tmp_path, esperar=5) == {}
    with S._trava:
        assert not S._construindo, "a vaga do build ficou pendurada"

    monkeypatch.setattr(S, "_montar", lambda pasta: {"deu certo": []})
    assert S.indice(tmp_path, esperar=5) == {"deu certo": []}


def test_a_busca_diz_quando_a_preferencia_ainda_nao_valeu(tmp_path, monkeypatch):
    """⚠️ Pedir a preferência e não ter índice é um resultado DIFERENTE de não pedir: a
    lista sai só com masters, e sem dizer parece que o projeto não tem subclipe nenhum."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    # ⚠️ `**_` porque quem chama passa o EDITOR da pergunta (`nle=`) desde 2026-09-21:
    #   a aba Busca dentro do Premiere não pode indexar as bins do Media Composer.
    monkeypatch.setattr(R, "_recortes_do_projeto", lambda **_: {})
    monkeypatch.setattr(R._nle, "recortes_prontos", lambda *_a, **_k: False)

    d = chamar("/busca/frase", {"termos": "personagem f"})
    assert d["preferir_subclipes"] is True
    assert d["recortes_prontos"] is False
