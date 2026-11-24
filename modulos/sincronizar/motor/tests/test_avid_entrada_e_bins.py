"""
A ENTRADA do Media Composer é a BIN — e só ela.

⭐⭐ Decisão do autor em 2026-08-23 (§1.5 do roadmap, ADR 0021). Havia um segundo
caminho — *ler os clipes MARCADOS nas bins do Avid* —, e ele saiu dos dois clientes:
do painel dentro do MC em 18/08 (DECISIONS 20ª) e da janela do app agora.

Três razões, na ordem em que pesam:

1. **É impreciso.** A seleção do MC atravessa BINS: um clipe esquecido marcado
   noutra bin aberta entrava sem ninguém pedir, e o editor só descobria pelo
   resultado do sync — longe da causa.
2. **App e painel discordavam** sobre o que é "o material selecionado". Mesma
   pergunta, duas respostas conforme a janela: a coisa mais difícil de explicar
   para quem usa.
3. **É caro.** Sem `GetListOfWindows` (o MC 25.6 não tem), descobrir o que está
   marcado obriga a perguntar a TODAS as bins do projeto a ~500 ms cada — para na
   maioria das vezes não achar nada.

⚠️ O que estes testes trancam é a ausência: que `avid_selection` **sem `bins`** não
volte a adivinhar uma seleção, e que devolva a árvore para quem chamou escolher.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from avid.mcapi import MediaComposer


class McFalso:
    """Um Media Composer que registra tudo que lhe perguntaram."""

    def __init__(self, bins=("/p/PROJ/CAM A.avb", "/p/PROJ/DIA 1/CAM B.avb")):
        self._bins = list(bins)
        self.itens_pedidos: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def bins(self, *a, **k):
        return list(self._bins)

    def chave_de_bin(self, caminho):
        # O que a interface vê: relativo ao projeto, sem `.avb` e SEMPRE com `/`
        # — ver `MediaComposer.chave_de_bin`, que normaliza a contrabarra do
        # Windows justamente porque esta string faz ida e volta com a tela.
        return str(Path(caminho).relative_to("/p/PROJ").with_suffix("")).replace("\\", "/")

    def itens_de(self, caminho, *a, **k):
        self.itens_pedidos.append(caminho)
        return []

    def projeto(self, *a, **k):
        return {"path": "/p/PROJ/"}


@pytest.fixture
def capturar(monkeypatch):
    """Troca o canal de saída do sidecar por uma lista."""
    saida: list[tuple[str, dict]] = []
    monkeypatch.setattr(main, "respond", lambda cid, data: saida.append(("ok", data)))
    monkeypatch.setattr(main, "respond_error",
                        lambda cid, msg, detail="": saida.append(("erro", {"msg": msg})))
    monkeypatch.setattr(main, "respond_progress", lambda cid, data: None)
    return saida


class TestAEntradaEaBin:
    def test_o_MediaComposer_NAO_sabe_mais_ler_selecao(self):
        """⛔ A ausência é a decisão. Se alguém reintroduzir `selecao()`, que seja
        por escolha e não por acidente — e que este teste caia primeiro.

        ⚠️ Uma versão "correta" dela continuaria trazendo material que a pessoa não
        pediu: o problema nunca foi técnico."""
        assert not hasattr(MediaComposer, "selecao")

    def test_sem_bins_devolve_a_ARVORE_e_nao_pergunta_clipe_a_ninguem(
            self, monkeypatch, capturar):
        """⭐ O comportamento que substituiu a adivinhação: sem bins escolhidas, a
        resposta é a lista de bins — e NENHUMA bin é consultada por clipes, que é o
        que custava ~500 ms cada."""
        mc = McFalso()
        monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: mc)

        main.handle_command({"id": "1", "command": "avid_selection", "params": {}})

        tipo, data = capturar[-1]
        assert tipo == "ok"
        assert data["sources"] == []
        assert data["bins"] == ["CAM A", "DIA 1/CAM B"]
        assert mc.itens_pedidos == [], (
            "sem bins escolhidas, nenhuma bin pode ser lida — nem para descobrir "
            "o que estaria marcado nela"
        )

    def test_com_bins_le_SO_as_pedidas(self, monkeypatch, capturar):
        """⚠️ A precisão que a seleção marcada não tinha: pediu-se uma bin, lê-se
        uma bin. Nada de outra bin aberta entrar de carona."""
        mc = McFalso()
        monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: mc)

        main.handle_command({"id": "1", "command": "avid_selection",
                             "params": {"bins": ["DIA 1/CAM B"]}})

        assert mc.itens_pedidos == ["/p/PROJ/DIA 1/CAM B.avb"]

    def test_bin_pedida_que_nao_existe_nao_vira_seleção_adivinhada(
            self, monkeypatch, capturar):
        """A chave veio da tela e pode não casar (já casou errado no Windows, por
        causa da contrabarra — ver o comentário em `main.py`). Nesse caso a resposta
        é a árvore de novo, para a pessoa reescolher: nunca "trouxe outra coisa"."""
        mc = McFalso()
        monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: mc)

        main.handle_command({"id": "1", "command": "avid_selection",
                             "params": {"bins": ["BIN QUE NÃO EXISTE"]}})

        tipo, data = capturar[-1]
        assert tipo == "ok" and data["sources"] == []
        assert data["bins"] == ["CAM A", "DIA 1/CAM B"]


class _Item:
    def __init__(self, mob_id, name):
        self.mob_id, self.name = mob_id, name


def test_a_fonte_conta_MASTERS_e_nao_arquivos(monkeypatch, capturar):
    """⭐ Um master OP-Atom de câmera são 3 arquivos (V + A1 + A2). Contar a lista de
    arquivos fazia o Ciclo Assist dizer "12 clipes, só 4 entraram" numa bin de 4
    masters (ensaio M06, 2026-11-01). E o master sem mídia não conta como clipe."""
    mc = McFalso()
    mc.itens_de = lambda caminho, *a, **k: [_Item(f"m{i}", f"T0{i}") for i in range(1, 6)]
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: mc)
    caminhos = {f"m{i}": [f"/mxf/m{i}_V.mxf", f"/mxf/m{i}_A1.mxf", f"/mxf/m{i}_A2.mxf"] for i in range(1, 5)}
    monkeypatch.setattr("avid.masters.resolver_mobs", lambda mc, ids, on_progress=None: {
        "caminhos": caminhos, "so_audio": set(), "colunas": {}, "duracoes": {}})
    monkeypatch.setattr("avid.masters.e_som", lambda mob, caminhos, so_audio: False)

    main.handle_command({"id": "1", "command": "avid_selection", "params": {"bins": ["CAM A"]}})

    tipo, data = capturar[-1]
    assert tipo == "ok"
    (fonte,) = data["sources"]
    assert fonte["clipes"] == 4 and len(fonte["files"]) == 12
    assert data["missing"] == ["T05"]
