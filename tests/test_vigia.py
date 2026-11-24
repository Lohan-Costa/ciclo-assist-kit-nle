"""A vigia do Premiere — importou, processa sozinho (2026-09-22).

O que estes testes travam é o que faria a vigia ser pior que nenhuma:

- ligar NÃO processa o que já estava no projeto (seriam horas que ninguém pediu);
- o que chega depois é mandado para a fila, vetores antes da fala;
- ⛔ nunca a decupagem (gasta a assinatura; preço antes do clique);
- uma tentativa por arquivo e estágio (nada de repetir a cada pulso o que falhou);
- com uma tarefa correndo, espera a vez;
- `host.jsx` velho (sem o contador) ainda é pego pela varredura de segurança.

⚠️ O que NÃO cobrem: o evento de verdade no Premiere — medido em
`spikes/o_premiere_avisa_import.py`, e a vigia inteira em `spikes/vigia_no_premiere.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cicloassist.midia import identidade as I
from cicloassist.nle import premiere as P
from cicloassist.nle.premiere import ponte as PT
from cicloassist.servico import rotas as R
from cicloassist.servico import tarefas as T
from cicloassist.servico import vigia as V
from cicloassist.servico.http import Pedido, Resposta

SONDAS = {
    ".mp4": {"umid": "", "tipo": "video", "fps": "25", "duracao_s": 5.0, "canais_de_som": []},
    ".wav": {"umid": "", "tipo": "audio", "duracao_s": 60.0, "canais_de_som": [2]},
    ".mov": {"umid": "", "tipo": "video", "fps": "25", "duracao_s": 5.0, "canais_de_som": [2]},
}


class Premiere:
    """Um Premiere simulado: o projeto, os arquivos e o contador de imports."""

    def __init__(self, tmp_path, com_contador=True):
        self.tmp = tmp_path
        self.itens: list[dict] = []
        self.importados = 0
        self.com_contador = com_contador

    def importar(self, nome, evento=True):
        a = self.tmp / nome
        a.write_bytes(b"x" * 32)
        self.itens.append({"arquivo": str(a), "nome": nome, "bins": ["B"]})
        if evento:
            self.importados += 1
        return str(a)

    def chamar(self, funcao, *args, **k):
        if funcao == "cicloProjeto":
            return {"caminho": str(self.tmp / "p.prproj")}
        if funcao == "cicloMidias":
            return {"arquivos": [i["arquivo"] for i in self.itens], "itens": list(self.itens)}
        if funcao == "cicloVigia":
            if not self.com_contador:
                raise PT.ExtendScriptFalhou("cicloVigia is not a function")
            return self.importados
        return {}


@pytest.fixture
def premiere(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    pp = Premiere(tmp_path)
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", pp.chamar)
    monkeypatch.setattr(I, "sondar", lambda a: dict(SONDAS.get(Path(a).suffix.lower(),
                                                                {"umid": ""})))
    # ⚠️ Sem a thread de verdade: ela chamaria `passo()` junto com o teste.
    monkeypatch.setattr(V, "iniciar", lambda: None)
    pedidos = []

    def analisar(corpo, nle):
        pedidos.append((corpo["estagio"], sorted(corpo["chaves"]), corpo.get("motivo"), nle))
        return Resposta.de_json({"ok": True}, 200)

    monkeypatch.setattr(R, "analisar", analisar)
    pp.pedidos = pedidos
    P.esquecer()
    V.esquecer()
    T.esquecer()
    yield pp
    P.esquecer()
    V.esquecer()


def _chave(arquivo):
    return P.chave_provisoria(arquivo)


def test_ligar_nao_processa_o_que_ja_estava_no_projeto(premiere, monkeypatch):
    # ⚠️ Varredura a CADA pulso: sem isto o segundo `passo` nem olharia o projeto, e o
    #    teste passaria mesmo com a fotografia quebrada (medido por mutação).
    monkeypatch.setattr(V, "SEGURANCA_S", 0.0)
    premiere.importar("ANTIGO.mp4")
    V.ligar(True)
    V.passo()
    V.passo()
    assert premiere.pedidos == []
    assert V.estado()["ligada"] and V.estado()["chegaram"] == 0


def test_o_que_chega_depois_vai_para_a_fila_vetores_antes_da_fala(premiere):
    premiere.importar("ANTIGO.mp4")
    V.ligar(True)
    V.passo()
    novo = premiere.importar("CAMERA.mov")   # imagem E som
    V.passo()
    assert premiere.pedidos == [("vetores", [_chave(novo)], "vigia", "premiere")]
    assert V.estado()["chegaram"] == 1 and V.estado()["pendentes"] == ["CAMERA.mov"]

    V.passo()   # a fala, no pulso seguinte
    assert premiere.pedidos[-1] == ("transcricao", [_chave(novo)], "vigia", "premiere")

    V.passo()   # e acabou: nada de repetir, e nada de decupar
    assert [p[0] for p in premiere.pedidos] == ["vetores", "transcricao"]
    assert V.estado()["pendentes"] == []


def test_som_puro_nao_pede_vetor(premiere):
    V.ligar(True)
    V.passo()
    novo = premiere.importar("SOM.wav")
    V.passo()
    assert premiere.pedidos == [("transcricao", [_chave(novo)], "vigia", "premiere")]


def test_com_uma_tarefa_correndo_a_vigia_espera(premiere, monkeypatch):
    V.ligar(True)
    V.passo()
    premiere.importar("CAMERA.mp4")
    monkeypatch.setattr(T, "ha_tarefa_viva", lambda: True)
    V.passo()
    assert premiere.pedidos == [] and V.estado()["pendentes"] == ["CAMERA.mp4"]
    monkeypatch.setattr(T, "ha_tarefa_viva", lambda: False)
    V.passo()
    assert [p[0] for p in premiere.pedidos] == ["vetores"]


def test_desligada_nao_pergunta_nada(premiere):
    premiere.importar("ANTIGO.mp4")
    V.ligar(False)
    assert not V.estado()["ligada"]


def test_leitura_que_falha_nao_vira_varredura_a_cada_pulso(premiere, monkeypatch):
    """⛔⛔ A ponte do Premiere é fila de UM pedido por vez, e é a MESMA do chat.

    Enquanto a condição da varredura era "ainda não sei o projeto", uma leitura que FALHA
    deixava o projeto vazio e a vigia lia o projeto inteiro a cada `PULSO_S` — para sempre,
    atrás de cada pergunta do editor. O sintoma seria "o painel ficou lento", sem erro
    nenhum apontando para cá. Depois da primeira tentativa, quem manda é o relógio de
    segurança.
    """
    chamadas = []

    def falhar(forcar=False):
        chamadas.append(forcar)
        return "", {}, "o projeto não respondeu"

    monkeypatch.setattr(P, "clipes_do_projeto", falhar)
    V.ligar(True)
    V.passo()
    V.passo()
    V.passo()

    assert chamadas == [True], "uma tentativa, não uma por pulso"
    assert V.estado()["erro"] and V.estado()["projeto"] == ""


def test_sem_evento_a_varredura_de_seguranca_pega(premiere, monkeypatch):
    """⚠️ Import pelo menu não foi medido, e outra extensão pode tomar o evento: sem a
    varredura de segurança, a vigia ligada ficaria calada."""
    V.ligar(True)
    V.passo()
    premiere.importar("CAMERA.mp4", evento=False)
    V.passo()
    assert premiere.pedidos == [], "antes do prazo de segurança, só o evento acorda"
    monkeypatch.setattr(V, "SEGURANCA_S", 0.0)
    V.passo()
    assert [p[0] for p in premiere.pedidos] == ["vetores"]


def test_host_jsx_velho_sem_contador_ainda_funciona(premiere, monkeypatch):
    premiere.com_contador = False
    monkeypatch.setattr(V, "SEGURANCA_S", 0.0)
    V.ligar(True)
    V.passo()
    premiere.importar("CAMERA.mp4")
    V.passo()
    assert [p[0] for p in premiere.pedidos] == ["vetores"]


def test_trocar_de_projeto_fotografa_de_novo(premiere, monkeypatch):
    V.ligar(True)
    V.passo()
    outro = premiere.tmp / "outro"
    outro.mkdir()
    chamar = premiere.chamar

    def noutro(funcao, *a, **k):
        if funcao == "cicloProjeto":
            return {"caminho": str(outro / "q.prproj")}
        return chamar(funcao, *a, **k)

    monkeypatch.setattr(PT, "chamar", noutro)
    premiere.importar("DO_OUTRO_PROJETO.mp4")
    P.esquecer()
    V.passo()
    assert premiere.pedidos == [], "o projeto que ele acabou de abrir não é importação"


def test_a_rota_liga_grava_e_a_lista_diz(premiere):
    r = R.rota_ligar_vigia(Pedido("POST", "/vetores/vigia", {},
                                  json.dumps({"ligada": True}).encode("utf-8")))
    assert json.loads(r.corpo.decode("utf-8"))["ligada"]
    # ⭐ A escolha fica gravada: reiniciar o serviço não desliga calado.
    from cicloassist.servico import config
    assert config.ler_estado()["vigia_premiere"] is True
    d = json.loads(R.rota_vetores(Pedido("GET", "/vetores", {}, b"", {"nle": "premiere"}))
                   .corpo.decode("utf-8"))
    assert d["vigia"]["ligada"]


def test_a_fila_da_vigia_diz_de_onde_veio(premiere, monkeypatch):
    """⭐ Trabalho que ninguém clicou tem de dizer de onde veio (o resumo leva `vigia`)."""
    import time
    monkeypatch.undo()   # a analisar de verdade
    # ⛔ O `undo` desfaz também o isolamento do conftest: sem isto o teste fala com o MCP REAL do
    #   Premiere da máquina (medido no Mac mini, 2026-11-06 — leu o projeto aberto e devolveu 400).
    monkeypatch.setenv("CICLOASSIST_PREMIERE_MCP", "http://127.0.0.1:9/premiere/mcp")
    monkeypatch.setenv("CICLOASSIST_PREMIERE_VIA", "cep")
    monkeypatch.setenv("CICLOASSIST_CACHE", str(premiere.tmp / "cache"))
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", premiere.chamar)
    monkeypatch.setattr(I, "sondar", lambda a: dict(SONDAS[Path(a).suffix.lower()]))
    from cicloassist.midia import cache as C
    monkeypatch.setattr(I, "aproveitar", lambda arquivo, origem, rotulo=None, **k:
                        I.Aproveitamento(midia=C.Midia("e" * 64, origem=origem,
                                                       rotulo=rotulo)))
    monkeypatch.setattr(R._analise, "transcrever_master", lambda *a, **k: None)
    novo = premiere.importar("SOM.wav")
    P.esquecer()
    r = R.analisar({"estagio": "transcricao", "chaves": [_chave(novo)], "motivo": "vigia"},
                   "premiere")
    assert r.status == 200
    limite = time.time() + 3
    while T.ha_tarefa_viva() and time.time() < limite:
        time.sleep(0.01)
    assert T.atual().resumo["vigia"] is True
    assert "importada" in T.atual().alvo


def test_o_host_registra_o_evento_medido():
    """⛔ O nome do evento é o MEDIDO. `app.bind` aceita qualquer nome e devolve `true`, então
    um nome errado aqui não daria erro nenhum — a vigia só nunca acordaria pelo evento."""
    host = P.HOST_JSX.read_text(encoding="utf-8")
    assert 'app.bind("onItemsAddedToProjectSuccess"' in host
