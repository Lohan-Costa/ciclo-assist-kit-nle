"""A busca alcança a FALA, e o termo casa no começo da palavra.

⛔⛔ **MEDIDO em 2026-09-20, no acervo do editor, e os dois achados nasceram juntos.**

Ele procurou `Personagem F` e a aba devolveu **4 resultados**, dizendo *"há mais informações com
esse indicador"*. Tinha razão: `personagem f` aparecia em **2** decupagens e em **241 falas de 86
mídias**. A busca cobria a camada menor — **168 decupadas contra 319 transcritas**.

E ao varrer a transcrição o segundo defeito apareceu: a busca era `termo in texto`,
substring puro. Com `cão` sem acento virando `cao`, ela casava **toda palavra terminada em
-ção** (`ação`, `alimentação`, `apresentação`) — "cachorro" devolvia **200 de 332 mídias**.
`sol` casava `absolutamente`; `mar` casava `amar` e `câmara`.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.midia import busca as B
from cicloassist.midia import cache as C
from cicloassist.midia import decupagem as D
from cicloassist.midia import intencao as I

from .test_inventario import IMAGEM, SOM, midia_de_imagem


# ── o começo da palavra ──────────────────────────────────────────────────────

@pytest.mark.parametrize("termo, texto, casa", [
    # ⛔ Os que quebravam a busca, com as palavras reais do acervo
    ("cão", "a alimentação dela", False),
    ("cão", "houve uma alteração", False),
    ("cão", "o cão late", True),
    ("sol", "absolutamente não", False),
    ("sol", "isso resolve", False),
    ("sol", "o sol bate na janela", True),
    ("mar", "vamos amar", False),
    ("mar", "girou a câmara", False),
    ("mar", "o mar está calmo", True),
    # ⭐ E o que TEM de continuar casando: o português flexiona
    ("carro", "dois carros parados", True),
    ("aérea", "vistas aéreas da cidade", True),
    ("conversa", "eles conversam baixo", True),
    ("close", "close de Personagem F", True),
    # o acento não separa os dois lados
    ("consultorio", "no consultório dela", True),
    ("plongee", "leve contra-plongée", True),
])
def test_o_termo_casa_no_comeco_da_palavra(termo, texto, casa):
    assert D.casa_termo(D.sem_acento(texto), termo) is casa


def test_a_regra_vale_para_a_busca_de_decupagem_tambem(tmp_path):
    """⚠️ Uma régua só: `procurar_no_material` (a ferramenta do chat) e a aba Busca têm de
    responder a mesma coisa para a mesma pergunta."""
    m = midia_de_imagem(tmp_path)
    m.anotar({"trecho": "A001", "escopo": "midia",
              "descricao": "a apresentação começou", "confianca": "inferido",
              "fonte": "visual"})
    assert D.procurar(["cão"], raiz=tmp_path) == []
    assert len(D.procurar(["apresenta"], raiz=tmp_path)) == 1


# ── o dicionário de intenção ─────────────────────────────────────────────────

def test_drone_acha_o_que_o_modelo_chamou_de_vista_aerea():
    """⛔⛔ O caso que deu origem ao módulo: `drone` 0 ocorrências no acervo, `aérea` 4."""
    assert "aérea" in I.equivalentes("drone")
    assert "dji" in I.equivalentes("drone"), "os clipes se chamam DJI_0311"
    assert I.alternativas("drone")[0] == "drone", "o digitado vem primeiro"


def test_termo_que_nao_e_intencao_passa_intocado():
    """⚠️ Tem de ser barato e calado: a esmagadora maioria dos termos não é intenção
    nenhuma, e para esses `alternativas` devolve só o que foi digitado."""
    assert I.equivalentes("xyzabc") == ()
    assert I.alternativas("blusa") == ("blusa",)
    assert I.equivalentes("") == () and I.alternativas("") == ()


def test_o_dicionario_de_termos_e_relido_quando_muda(tmp_path, monkeypatch):
    """⭐ O dicionário é ABERTO — o editor pediu para ir completando —, e um arquivo lido só
    na partida não é aberto: ele acrescentaria um grupo, procuraria, nada mudaria, e nada
    na tela diria por quê.

    ⚠️ A conferência tem piso de tempo (`RECONFERIR_S`): `equivalentes` é chamada uma vez
    por (fala × termo), e um `stat` por chamada somaria ~0,1 s numa busca de 0,3 s.
    """
    arquivo = tmp_path / "termos.json"
    arquivo.write_text(json.dumps({"grupos": [
        {"preferido": "claquete", "tambem": ["clapperboard"]}]}), encoding="utf-8")
    monkeypatch.setattr(I, "ARQUIVO_DE_TERMOS", arquivo)
    monkeypatch.setattr(I, "_assinatura", ())
    monkeypatch.setattr(I, "_conferido_em", 0.0)
    # ⚠️ O mapa é global e este teste o REESCREVE: sem isto, o dicionário de mentira
    #   sobreviveria ao teste e os seguintes passariam (ou falhariam) por causa dele.
    monkeypatch.setattr(I, "_POR_TERMO", dict(I._POR_TERMO))

    assert "clapperboard" in I.equivalentes("claquete")
    assert I.equivalentes("badge") == ()

    arquivo.write_text(json.dumps({"grupos": [
        {"preferido": "claquete", "tambem": ["clapperboard", "badge"]}]}), encoding="utf-8")
    monkeypatch.setattr(I, "_conferido_em", 0.0)   # o piso de tempo, vencido

    assert "claquete" in I.equivalentes("badge"), "não releu o dicionário que mudou"


def test_dicionario_que_some_nao_apaga_a_busca(tmp_path, monkeypatch):
    """⛔ Um arquivo ilegível não pode zerar as intenções: sem ele a busca volta a ser
    exata, que é o comportamento de antes — nunca "não achei" por causa do dicionário."""
    antes = I.equivalentes("drone")
    monkeypatch.setattr(I, "ARQUIVO_DE_TERMOS", tmp_path / "nao-existe.json")
    monkeypatch.setattr(I, "_conferido_em", 0.0)
    monkeypatch.setattr(I, "_POR_TERMO", dict(I._POR_TERMO))
    assert I.equivalentes("drone") == antes


def test_o_acento_nao_separa_a_intencao_da_chave():
    """⭐ As chaves são guardadas sem acento, e é assim que são consultadas — quem digita
    "consultório" cai na mesma entrada de quem digita "consultorio"."""
    assert I.equivalentes("consultório") == I.equivalentes("consultorio") != ()
    assert I.equivalentes("CONSULTÓRIO  ") == I.equivalentes("consultorio")


def test_a_expansao_e_DITA(tmp_path):
    """⛔⛔ Busca que se alarga calada é a irmã do filtro calado: o editor lê "13 achados"
    para "drone" sem saber que nenhum tem a palavra que ele escreveu."""
    d = I.expansoes_de(["drone", "consultorio", "xyzabc"])
    assert "drone" in d and "aérea" in d["drone"]
    assert "xyzabc" not in d, "só o que foi de fato acrescentado"


def test_nenhuma_expansao_cobre_o_acervo_inteiro():
    """⛔ MEDIDO: `mar` sozinho casava **36% do acervo** (Pessoa U, marido, marcar) e por
    isso saiu de "praia". Expansão de 3 letras é a que mais engana — ela parece precisa e
    é a mais larga de todas."""
    for termo, palavras in I.INTENCOES.items():
        for p in palavras:
            assert len(D.sem_acento(p)) >= 3, f"{termo} → {p!r} é curto demais"
        assert "mar" not in palavras, f"{termo} → 'mar' cobre um terço do material"


# ── a fala entra na busca ────────────────────────────────────────────────────

@pytest.fixture
def cache_com_fala(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    imagem = midia_de_imagem(tmp_path, nome="C07_P01-T001")
    imagem.anotar({"trecho": "C07_P01-T001", "escopo": "midia",
                   "descricao": "close no consultório", "enquadramento": "close",
                   "confianca": "inferido", "fonte": "visual"})
    som = C.Midia(SOM, raiz_do_cache=tmp_path)
    som.anotar_fonte({"master_de_som": "C07_P01-T001_SOM"})
    som.guardar_transcricao([
        {"inicio": 12.4, "fim": 14.0, "texto": "Boa tarde, Personagem F.", "certeza": 0.91},
        {"inicio": 74.9, "fim": 76.2, "texto": "A Personagem F já chegou?", "certeza": 0.88},
        {"inicio": 130.0, "fim": 131.5, "texto": "Pode entrar.", "certeza": 0.95},
    ])
    return tmp_path


def test_acha_quem_DIZ_a_palavra_e_nao_so_quem_a_mostra(cache_com_fala):
    """⭐⭐ O caso do editor. E nome próprio é o que prova a regra: "Personagem F" vem do roteiro
    ou da claquete, e quem a diz em voz alta é o DIÁLOGO — nunca o rosto."""
    so_imagem = D.procurar(["personagem f"], raiz=cache_com_fala)
    achados = B.procurar(["personagem f"], raiz=cache_com_fala)

    assert so_imagem == [], "a decupagem não menciona Personagem F"
    assert len(achados) == 1
    assert achados[0].quantas_falas == 2
    assert [f["texto"] for f in achados[0].falas] == ["Boa tarde, Personagem F.",
                                                      "A Personagem F já chegou?"]
    assert achados[0].como_dicionario()["achado_por"] == ["fala"]


def test_a_mídia_que_casa_nas_DUAS_camadas_vem_primeiro(cache_com_fala):
    """⭐ É o resultado de que o editor tem mais certeza sem abrir nada."""
    som = C.Midia(SOM, raiz_do_cache=cache_com_fala)
    som.anotar({"trecho": "C07_SOM", "escopo": "midia", "descricao": "só fala",
                "confianca": "inferido", "fonte": "visual"})
    imagem = C.Midia(IMAGEM, raiz_do_cache=cache_com_fala)
    imagem.guardar_transcricao([{"inicio": 1.0, "fim": 2.0, "texto": "consultório!",
                                 "certeza": 0.9}])

    achados = B.procurar(["consultorio"], raiz=cache_com_fala)
    assert achados[0].como_dicionario()["achado_por"] == ["imagem", "fala"]


def test_todos_os_termos_na_MESMA_fala(cache_com_fala):
    """⚠️ Espalhados pela transcrição, "Personagem F entrar" casaria quase toda diária — e o
    editor pediu um MOMENTO."""
    assert B.procurar(["personagem f", "entrar"], raiz=cache_com_fala) == []
    assert len(B.procurar(["personagem f", "tarde"], raiz=cache_com_fala)) == 1


def test_campo_fechado_nao_e_respondido_pela_fala(cache_com_fala):
    """⇒ Quem pede "close" está falando de IMAGEM; devolver um clipe porque alguém disse a
    palavra lá dentro seria responder outra pergunta."""
    som = C.Midia(SOM, raiz_do_cache=cache_com_fala)
    som.guardar_transcricao([{"inicio": 1.0, "fim": 2.0, "texto": "faz um close nela",
                              "certeza": 0.9}])
    achados = B.procurar([], {"enquadramento": "close"}, raiz=cache_com_fala)
    assert [a.midia for a in achados] == ["C07_P01-T001"]


def test_a_fala_traz_o_relogio_e_a_procedencia(cache_com_fala):
    (achado,) = B.procurar(["personagem f"], raiz=cache_com_fala)
    fala = achado.falas[1]
    assert fala["quando"] == "01:14", "mm:ss desde o começo do MASTER"
    assert fala["fonte"] == "transcricao" and fala["confianca"] == "inferido"
    assert fala["medida"] == 0.88, "⚠️ medida vazia seria 'não medido', nunca zero"


def test_o_cartao_nao_leva_mais_que_o_teto_de_falas(cache_com_fala):
    """⚠️ Uma mídia com 30 falas casando empurraria as outras para fora da tela — e a
    resposta a "onde mais?" é justamente as outras."""
    som = C.Midia(SOM, raiz_do_cache=cache_com_fala)
    som.guardar_transcricao([{"inicio": i, "fim": i + 1, "texto": f"Personagem F {i}",
                              "certeza": 0.9} for i in range(30)])
    (achado,) = B.procurar(["personagem f"], raiz=cache_com_fala)
    assert achado.quantas_falas == 30, "o TOTAL é dito"
    assert len(achado.falas) == B.FALAS_POR_MIDIA, "mas só um punhado viaja"


def test_o_relogio():
    assert B.relogio(0) == "00:00"
    assert B.relogio(74.9) == "01:14"
    assert B.relogio(3599) == "59:59"
    assert B.relogio(None) == "00:00"
    assert B.relogio(-5) == "00:00"


def test_o_alcance_conta_as_duas_camadas(cache_com_fala):
    a = B.medir_alcance(raiz=cache_com_fala, no_projeto=423)
    assert (a.decupadas, a.transcritas, a.no_cache, a.no_projeto) == (1, 1, 2, 423)


# ── pela rota, como a tela vê ────────────────────────────────────────────────

def test_a_rota_devolve_a_fala_e_a_expansao(cache_com_fala):
    from cicloassist.servico import rotas as R
    from cicloassist.servico.http import Pedido

    def frase(corpo):
        r = R.ROTAS[("POST", "/busca/frase")][0](
            Pedido("POST", "/busca/frase", {}, json.dumps(corpo).encode("utf-8")))
        return json.loads(r.corpo.decode("utf-8"))

    d = frase({"termos": "personagem f"})
    assert d["ok"] and d["quantos"] == 1
    assert d["achados"][0]["quantas_falas"] == 2
    assert d["achados"][0]["falas"][0]["quando"] == "00:12"
    assert d["expansoes"] == {}, "personagem f não é intenção nenhuma"

    d = frase({"termos": "drone"})
    assert "aérea" in d["expansoes"]["drone"]
