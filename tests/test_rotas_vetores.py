"""As rotas da aba Vetores — quem entra na fila, e quem a página pode mandar varrer.

⭐ A fila é o coração do que o editor pediu: *"deixa a análise correndo enquanto eu faço
outra coisa"*. O que estes testes travam é **quem entra nela** — porque a resposta errada
custa horas de CPU na máquina de quem está montando.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.midia import acervo as A
from cicloassist.midia import cache as C
from cicloassist.midia import estagios as E
from cicloassist.servico import rotas as R
from cicloassist.servico import tarefas as T
from cicloassist.servico.http import Pedido

IMAGEM = "0x060A2B340101010101010F0013000000C6D91F0BB8ABB1C7ABEE2FFBA70D1E05"
SOM = "0x060A2B340101010101010F0013000000E56E1D13D305BE564AEC678A24E90A70"


@pytest.fixture
def cache_isolado(tmp_path, monkeypatch):
    """⚠️ O cache VERDADEIRO da máquina não pode ser tocado por um teste — ele é o
    trabalho de quem está usando o produto."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    T.esquecer()
    yield tmp_path
    T.parar()
    T.esquecer()


def post(caminho, corpo=None):
    return Pedido("POST", caminho, {},
                  json.dumps(corpo or {}).encode("utf-8"))


def guardar_clipe(raiz, chave, nome, por_tipo, pasta=None):
    # ⚠️ Uma pasta por clipe quando não se diz outra: `guardar` grava POR PASTA, e duas
    #    chamadas na mesma substituiriam a primeira — o teste passaria a medir outra coisa.
    A.guardar(pasta or f"D:/mídia/{nome}",
              [A.Clipe(chave, nome, sum(por_tipo.values(), []),
                       {k: len(v) for k, v in por_tipo.items()},
                       por_tipo=por_tipo, bytes=10)],
              raiz=raiz)


def corpo_de(resposta):
    return json.loads(resposta.corpo.decode("utf-8"))


def test_a_rota_manda_o_preco_das_duas_decupagens(cache_isolado, monkeypatch):
    """⭐⭐ O preço vem MEDIDO do serviço e a tela só multiplica — número de custo copiado
    para o JavaScript envelhece calado. São dois preços diferentes e não intercambiáveis:
    a macro cobra DÓLAR da assinatura, a micro cobra HORAS do Mac.

    ⚠️ E sem o Mac configurado o bloco da micro continua vindo, dizendo `motor: ""` — é
    assim que a tela explica o botão desabilitado em vez de deixá-lo cinza e calado.
    """
    from cicloassist.motor import micro as M
    monkeypatch.setattr("cicloassist.motor.percepcao.endereco", lambda: "")
    d = corpo_de(R.rota_vetores(Pedido("GET", "/vetores", {}, b"", {})))

    assert d["decupagem"]["motor"] == "claude" and d["decupagem"]["custo_por_midia_usd"] > 0
    assert d["micro"]["motor"] == ""
    assert d["micro"]["segundos_por_trecho"] == M.SEGUNDOS_POR_TRECHO
    assert d["micro"]["trechos_por_minuto"] == M.TRECHOS_POR_MINUTO

    monkeypatch.setattr("cicloassist.motor.percepcao.endereco",
                        lambda: "http://192.168.1.4:11434")
    d = corpo_de(R.rota_vetores(Pedido("GET", "/vetores", {}, b"", {})))
    # ⭐ Com o Mac, a MACRO também muda de conta (tempo em vez de dólar) — as duas leem o
    #   mesmo endereço, e uma única leitura é o que garante que elas não se contradigam.
    assert d["decupagem"]["motor"] == "mac" and d["micro"]["motor"] == "mac"


# ── quem entra na fila ───────────────────────────────────────────────────────

def test_sem_acervo_nao_ha_o_que_transcrever(cache_isolado):
    r = R.rota_analisar(post("/vetores/analisar"))
    assert r.status == 400
    assert "não há mídia" in corpo_de(r)["erro"]


def test_so_entra_quem_tem_som(cache_isolado, monkeypatch):
    """⛔ A varredura guarda os arquivos por espécie justamente para isto: uma track de
    vídeo no `amix` faz o ffmpeg falhar inteiro."""
    guardar_clipe(cache_isolado, C.de_umid(IMAGEM), "só imagem", {"video": ["v.mxf"]})

    r = R.rota_analisar(post("/vetores/analisar"))
    assert r.status == 400


def test_midia_com_som_entra_na_fila(cache_isolado, monkeypatch):
    guardar_clipe(cache_isolado, C.de_umid(SOM), "tem som",
                  {"audio": ["a1.mxf", "a2.mxf"]})
    vistos = []
    monkeypatch.setattr(R._analise, "transcrever_master",
                        lambda midia, arquivos, nome, **k: vistos.append(nome))

    r = R.rota_analisar(post("/vetores/analisar"))
    assert corpo_de(r)["na_fila"] == 1
    esperar()
    assert vistos == ["tem som"]


def test_quem_ja_tem_transcricao_em_dia_fica_de_fora(cache_isolado):
    """⭐ Recomeçar não repete: é o que permite parar a fila e voltar amanhã."""
    chave = C.de_umid(SOM)
    guardar_clipe(cache_isolado, chave, "pronta", {"audio": ["a.mxf"]})
    midia = C.Midia(chave, raiz_do_cache=cache_isolado)
    midia.guardar_transcricao([{"texto": "oi"}])
    midia.registrar_gerador(E.TRANSCRICAO, E.assinatura(E.TRANSCRICAO))

    assert R.rota_analisar(post("/vetores/analisar")).status == 400


def test_transcricao_de_receita_velha_volta_para_a_fila(cache_isolado, monkeypatch):
    """⚠️ "A refazer" não é erro: é material feito com outro modelo. Ele entra na fila
    sem o editor precisar pedir nada além de "o que falta"."""
    chave = C.de_umid(SOM)
    guardar_clipe(cache_isolado, chave, "velha", {"audio": ["a.mxf"]})
    midia = C.Midia(chave, raiz_do_cache=cache_isolado)
    midia.guardar_transcricao([{"texto": "oi"}])
    midia.registrar_gerador(E.TRANSCRICAO, {"motor": "faster-whisper", "modelo": "tiny"})
    monkeypatch.setattr(R._analise, "transcrever_master", lambda *a, **k: None)

    assert corpo_de(R.rota_analisar(post("/vetores/analisar")))["na_fila"] == 1
    esperar()


def test_chaves_escolhidas_limitam_a_fila(cache_isolado, monkeypatch):
    guardar_clipe(cache_isolado, C.de_umid(SOM), "a", {"audio": ["a.mxf"]})
    guardar_clipe(cache_isolado, C.de_umid(IMAGEM), "b", {"audio": ["b.mxf"]})
    monkeypatch.setattr(R._analise, "transcrever_master", lambda *a, **k: None)

    r = R.rota_analisar(post("/vetores/analisar", {"chaves": [C.de_umid(SOM)]}))
    assert corpo_de(r)["na_fila"] == 1
    esperar()


def test_refazer_pega_ate_o_que_esta_em_dia(cache_isolado, monkeypatch):
    """⭐ O "re-analisar" do editor. Sem ele, material pronto NUNCA volta à fila — e
    quando a transcrição sai ruim (som baixo, sala barulhenta) não há como pedir de novo
    pela tela.

    ⚠️ É caro, e por isso o interruptor da tela se desarma sozinho a cada disparo.
    """
    chave = C.de_umid(SOM)
    guardar_clipe(cache_isolado, chave, "pronta", {"audio": ["a.mxf"]})
    midia = C.Midia(chave, raiz_do_cache=cache_isolado)
    midia.guardar_transcricao([{"texto": "oi"}])
    midia.registrar_gerador(E.TRANSCRICAO, E.assinatura(E.TRANSCRICAO))

    # sem refazer, não há o que fazer
    assert R.rota_analisar(post("/vetores/analisar")).status == 400

    forcadas = []
    monkeypatch.setattr(R._analise, "transcrever_master",
                        lambda midia, arquivos, nome, **k: forcadas.append(k.get("forcar")))
    r = R.rota_analisar(post("/vetores/analisar", {"refazer": True}))
    assert corpo_de(r)["na_fila"] == 1
    esperar()
    assert forcadas == [True], "o refazer precisa CHEGAR na análise, não só na fila"


def test_uma_midia_quebrada_nao_para_a_fila(cache_isolado, monkeypatch):
    """São horas de trabalho e o editor não está olhando: quem falha vira contagem."""
    guardar_clipe(cache_isolado, C.de_umid(SOM), "a", {"audio": ["a.mxf"]})
    guardar_clipe(cache_isolado, C.de_umid(IMAGEM), "b", {"audio": ["b.mxf"]})

    def falha(midia, arquivos, nome, **k):
        if nome == "a":
            raise R._analise.AnaliseFalhou("sumiu")

    monkeypatch.setattr(R._analise, "transcrever_master", falha)
    R.rota_analisar(post("/vetores/analisar"))
    esperar()

    resumo = T.atual().resumo
    assert resumo["feitas"] == 1 and resumo["falharam"] == 1


def test_uma_tarefa_por_vez_tambem_aqui(cache_isolado, monkeypatch):
    import threading
    solta = threading.Event()
    guardar_clipe(cache_isolado, C.de_umid(SOM), "a", {"audio": ["a.mxf"]})
    monkeypatch.setattr(R._analise, "transcrever_master",
                        lambda *a, **k: solta.wait(2))

    R.rota_analisar(post("/vetores/analisar"))
    segunda = R.rota_analisar(post("/vetores/analisar"))
    assert segunda.status == 409
    solta.set()
    esperar()


# ── o andamento ──────────────────────────────────────────────────────────────

def esperar(ate=3.0):
    import time
    limite = time.time() + ate
    while T.ha_tarefa_viva() and time.time() < limite:
        time.sleep(0.01)
    assert not T.ha_tarefa_viva(), "a tarefa não terminou a tempo"


def test_andamento_sem_tarefa_nao_e_erro(cache_isolado):
    assert corpo_de(R.rota_andamento(None))["tarefa"] is None


def test_parar_no_meio_nao_grava_meia_transcricao(cache_isolado, monkeypatch):
    """⛔⛔ Meia transcrição em cache seria pior que nenhuma: ninguém a refaria, e o
    `transcrever` do turno entregaria uma cena cortada ao meio como se fosse inteira."""
    guardar_clipe(cache_isolado, C.de_umid(SOM), "longa", {"audio": ["a.mxf"]})

    import time

    def demorada(midia, arquivos, nome, aviso=None, **k):
        # Fica pedindo para pintar o progresso, como o ASR faz — é por aí que o pedido de
        # parada chega, e é isso que este teste mede.
        for i in range(2000):
            aviso("ouvindo", i / 2000, "…")
            time.sleep(0.001)
        raise AssertionError("devia ter sido interrompida")

    monkeypatch.setattr(R._analise, "transcrever_master", demorada)
    R.rota_analisar(post("/vetores/analisar"))
    time.sleep(0.1)
    T.parar()
    esperar()

    assert T.atual().estado == "parada"
    assert T.atual().resumo["feitas"] == 0
    assert not C.Midia(C.de_umid(SOM), raiz_do_cache=cache_isolado).tem_transcricao()


# ── a lista de pastas ────────────────────────────────────────────────────────

def test_a_pasta_apontada_pelo_editor_entra_na_lista(cache_isolado, tmp_path,
                                                     monkeypatch):
    """⭐ O gesto é a permissão: o que fica guardado é a escolha dele no seletor do
    Windows, nunca um caminho que a página inventou."""
    from cicloassist.servico import config as _config

    escolhida = tmp_path / "mídia do cliente"
    escolhida.mkdir()
    monkeypatch.setattr(_config, "ler_estado", lambda: {"pastas_de_midia": [str(escolhida)]})

    assert str(escolhida) in R._pastas_de_midia()


def test_pasta_guardada_que_sumiu_nao_aparece(cache_isolado, monkeypatch):
    """Disco desconectado, pasta apagada: listar o que não existe daria um botão que
    falha sozinho."""
    from cicloassist.servico import config as _config

    monkeypatch.setattr(_config, "ler_estado",
                        lambda: {"pastas_de_midia": ["Z:/nunca existiu"]})
    assert "Z:/nunca existiu" not in R._pastas_de_midia()


# ── a fila trabalha no projeto ABERTO ────────────────────────────────────────
#
# ⭐⭐ Decisão do editor em 2026-09-13, depois de a primeira fila no Mac gastar a noite
# decupando mídia de outras produções que estava na mesma `Avid MediaFiles`: o que se
# analisa sem o editor escolher é o material DELE, não o que o disco tem.


def com_projeto(monkeypatch, masters):
    from cicloassist.avid import escopo as _escopo

    _escopo.esquecer()
    monkeypatch.setattr(_escopo, "projeto_aberto", lambda *a, **k: "D:/proj/HOJE")
    monkeypatch.setattr(_escopo._bins, "varrer", lambda p, *a, **k: dict(masters))


def test_a_fila_nao_pega_midia_fora_do_projeto(cache_isolado, monkeypatch):
    dentro, fora = C.de_umid(SOM), C.de_umid(IMAGEM)
    guardar_clipe(cache_isolado, dentro, "da cena", {"audio": ["a.mxf"]})
    guardar_clipe(cache_isolado, fora, "de outra produção", {"audio": ["b.mxf"]})
    com_projeto(monkeypatch, {dentro: {}})
    vistos = []
    monkeypatch.setattr(R._analise, "transcrever_master",
                        lambda midia, arquivos, nome, **k: vistos.append(nome))

    r = R.rota_analisar(post("/vetores/analisar"))
    corpo = corpo_de(r)
    assert corpo["na_fila"] == 1
    assert corpo["fora_do_projeto"] == 1
    esperar()
    assert vistos == ["da cena"]


def test_nada_a_fazer_diz_quantas_ficaram_de_fora(cache_isolado, monkeypatch):
    """⚠️ "não há mídia esperando" com 1 barrada manda o editor caçar um defeito que não
    existe — a frase tem de dizer que ela existe, e por que ficou de fora."""
    guardar_clipe(cache_isolado, C.de_umid(SOM), "de outra produção", {"audio": ["b.mxf"]})
    com_projeto(monkeypatch, {C.de_umid(IMAGEM): {}})

    r = R.rota_analisar(post("/vetores/analisar"))
    assert r.status == 400
    assert "1 de fora" in corpo_de(r)["erro"]


def test_quando_o_editor_escolhe_o_recorte_nao_manda(cache_isolado, monkeypatch):
    """⛔ A tabela filtrada é uma escolha, e o rótulo do botão diz a conta. Um filtro
    escondido por baixo faria o botão mentir."""
    fora = C.de_umid(SOM)
    guardar_clipe(cache_isolado, fora, "de outra produção", {"audio": ["b.mxf"]})
    com_projeto(monkeypatch, {C.de_umid(IMAGEM): {}})
    monkeypatch.setattr(R._analise, "transcrever_master", lambda *a, **k: None)

    r = R.rota_analisar(post("/vetores/analisar", {"chaves": [fora]}))
    assert corpo_de(r)["na_fila"] == 1
