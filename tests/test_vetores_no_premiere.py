"""A aba Vetores dentro do Premiere — lista e processa a mídia do projeto dele (2026-09-22).

⛔⛔ Até aqui a aba era do Avid mesmo dentro do Premiere, e dizia isso na tela: a lista saía
da `Avid MediaFiles` e das bins do Media Composer, e nenhuma das duas conhece um `.mp4` na
pasta do editor. Material que só existe no Premiere não aparecia e não podia ser enfileirado
— e o gesto que o editor descreveu (*"importo a mídia no Premiere e peço para processar, é
aí que o cruzamento acontece"*) não tinha onde acontecer.

O que estes testes travam:

- a terceira fonte (`premiere.clipes_do_projeto`) no formato da varredura do acervo;
- cada editor lista o SEU banco, nos dois sentidos;
- a fila do Premiere cruza os bancos por `identidade.aproveitar()` ANTES de processar, e
  o que a cópia resolveu não é processado de novo.

⚠️ O que NÃO cobrem: o `host.jsx` rodando no Premiere de verdade (o painel é simulado).
"""

from __future__ import annotations

import json
import time

import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import estagios as E
from cicloassist.midia import identidade as I
from cicloassist.nle import premiere as P
from cicloassist.nle.premiere import ponte as PT
from cicloassist.servico import rotas as R
from cicloassist.servico import tarefas as T
from cicloassist.servico.http import Pedido


@pytest.fixture(autouse=True)
def limpo(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    PT.esquecer()
    P.esquecer()
    I.esquecer()
    T.esquecer()
    yield
    T.parar()
    T.esquecer()
    PT.esquecer()
    P.esquecer()


SONDAS = {
    "DJI_0315.mp4": {"umid": "", "tipo": "video", "fps": "24000/1001", "duracao_s": 12.0,
                     "canais_de_som": []},
    "C14 P1-T010.WAV": {"umid": "", "tipo": "audio", "duracao_s": 146.1,
                        "canais_de_som": [5]},
    "B001_C003.mp4": {"umid": "", "tipo": "video", "fps": "25", "duracao_s": 20.0,
                      "canais_de_som": [2]},
}


def _projeto(monkeypatch, tmp_path, itens, com_itens=True):
    """Um painel de Premiere simulado: o projeto e os arquivos que ele usa."""
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(I, "sondar", lambda arq: dict(SONDAS.get(
        __import__("pathlib").Path(arq).name, {"umid": ""})))

    def chamar(funcao, *args, **k):
        if funcao == "cicloProjeto":
            return {"caminho": str(tmp_path / "CICLO ASSIST TESTE.prproj")}
        if funcao == "cicloMidias":
            r = {"arquivos": [i["arquivo"] for i in itens]}
            if com_itens:
                r["itens"] = itens
            return r
        return {}

    monkeypatch.setattr(PT, "chamar", chamar)


def _arquivo(tmp_path, nome):
    a = tmp_path / nome
    a.write_bytes(b"x" * 64)
    return str(a)


def _corpo(resposta):
    return json.loads(resposta.corpo.decode("utf-8"))


def _vetores(nle="premiere"):
    return _corpo(R.rota_vetores(Pedido("GET", "/vetores", {}, b"", {"nle": nle})))


def _analisar(corpo):
    return R.rota_analisar(Pedido("POST", "/vetores/analisar", {},
                                  json.dumps(corpo).encode("utf-8")))


def _esperar(ate=3.0):
    limite = time.time() + ate
    while T.ha_tarefa_viva() and time.time() < limite:
        time.sleep(0.01)
    assert not T.ha_tarefa_viva(), "a tarefa não terminou a tempo"


# ── a terceira fonte ─────────────────────────────────────────────────────────

def test_o_arquivo_novo_do_projeto_vira_linha_de_falta(monkeypatch, tmp_path):
    """⭐⭐ O defeito que abre o caso: o `.mp4` do Premiere não era linha nenhuma."""
    a = _arquivo(tmp_path, "DJI_0315.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": a, "nome": "Drone 1", "bins": ["DIA 1"]}])

    projeto, clipes, erro = P.clipes_do_projeto()
    assert not erro and projeto.endswith(".prproj")
    (chave, clipe), = clipes.items()
    assert C.e_chave(chave) and clipe["provisoria"]
    assert clipe["nome"] == "Drone 1" and clipe["bins"] == ["DIA 1"]
    # ⭐ O MESMO formato da varredura do acervo: é o que deixa o inventário e a fila
    #   não saberem de NLE.
    assert clipe["por_tipo"] == {"video": [a]} and clipe["fps"] == "24000/1001"

    # ⛔⛔ E a chave da linha não é pasta: listar não cria nada no cache.
    assert C.todas() == []


def test_a_linha_provisoria_nao_e_a_impressao_do_conteudo(monkeypatch, tmp_path):
    """⛔ Montar a lista não lê 8 MB de cada arquivo (~1,6 GB num projeto de 200 clipes)."""
    a = _arquivo(tmp_path, "DJI_0315.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": a, "nome": "x", "bins": [""]}])
    lidos = []
    monkeypatch.setattr(I, "impressao", lambda arq: lidos.append(arq) or "f" * 64)

    _, clipes, _ = P.clipes_do_projeto()
    assert lidos == []
    # A raiz do projeto tem nome — bin vazia na tabela quer dizer "ninguém leu as bins".
    assert list(clipes.values())[0]["bins"] == [P.RAIZ]


def test_o_som_e_a_diaria_de_camera_tem_as_especies_certas(monkeypatch, tmp_path):
    som = _arquivo(tmp_path, "C14 P1-T010.WAV")
    diaria = _arquivo(tmp_path, "B001_C003.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": som, "nome": "som", "bins": ["S"]},
                                     {"arquivo": diaria, "nome": "cam", "bins": ["C"]}])
    por_nome = {c["nome"]: c for c in P.clipes_do_projeto()[1].values()}
    # ⚠️ Pista não é canal: o WAV é UMA pista de cinco canais.
    assert por_nome["som"]["tracks"] == {"audio": 1} and "video" not in por_nome["som"]["por_tipo"]
    assert por_nome["cam"]["tracks"] == {"video": 1, "audio": 1}


def test_arquivo_ja_neste_banco_e_a_entrada_dele(monkeypatch, tmp_path):
    """⭐ A linha junta o que o cache sabe com o que o projeto diz."""
    a = _arquivo(tmp_path, "DJI_0315.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": a, "nome": "Drone 1", "bins": ["DIA 1"]}])
    chave = I.impressao(a)
    m = C.Midia(chave, origem="premiere", rotulo={"nome": "DJI_0315"})
    m.pasta  # noqa: B018
    m.guardar_transcricao([{"texto": "ola", "inicio": 0.0, "fim": 1.0}])

    (linha_chave, clipe), = P.clipes_do_projeto()[1].items()
    assert linha_chave == chave and not clipe.get("provisoria")

    linha, = [l for l in _vetores()["midias"] if l["chave"] == chave]
    assert linha["fala"]["tem"] and linha["bins"] == ["DIA 1"]


def test_chave_conhecida_do_OUTRO_banco_nao_vira_a_linha(monkeypatch, tmp_path):
    """⛔⛔ A linha que usasse a chave da entrada do Avid faria a fila olhar o trabalho de
    lá e responder "já está pronto" — sem entrada nenhuma no banco do Premiere."""
    a = _arquivo(tmp_path, "DJI_0315.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": a, "nome": "x", "bins": ["B"]}])
    chave = I.impressao(a)
    C.Midia(chave, origem="avid", rotulo={"nome": "DA BIN DO AVID"}).pasta  # noqa: B018

    (linha_chave, clipe), = P.clipes_do_projeto()[1].items()
    assert linha_chave != chave and clipe["provisoria"]


def test_host_jsx_velho_so_com_os_caminhos_ainda_lista(monkeypatch, tmp_path):
    """⚠️ Serviço novo com painel sem Reload: o `cicloMidias` antigo não traz `itens`."""
    a = _arquivo(tmp_path, "DJI_0315.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": a}], com_itens=False)
    (clipe,) = P.clipes_do_projeto()[1].values()
    assert clipe["nome"] == "DJI_0315"


def test_arquivo_offline_fica_na_tabela_sem_poder_ser_processado(monkeypatch, tmp_path):
    ausente = str(tmp_path / "sumiu.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": ausente, "nome": "sumiu", "bins": ["B"]}])
    linha, = _vetores()["midias"]
    assert linha["nome"] == "sumiu" and not linha["no_acervo"]
    assert linha["pode"] == {"transcricao": False, "vetores": False, "decupagem": False,
                            "micro": False}


# ── cada editor lista o SEU banco ────────────────────────────────────────────

def test_a_aba_no_premiere_nao_lista_o_banco_do_avid(monkeypatch, tmp_path):
    a = _arquivo(tmp_path, "DJI_0315.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": a, "nome": "Drone 1", "bins": ["DIA 1"]}])
    C.Midia("a" * 64, origem="avid",
            rotulo={"nome": "C07_P01 DO AVID",
                    "arquivos": ["D:/Avid MediaFiles/MXF/1/x.mxf"]}).pasta  # noqa: B018

    d = _vetores()
    texto = json.dumps(d, ensure_ascii=False)
    assert "DO AVID" not in texto and "Avid MediaFiles/MXF" not in texto
    assert [l["nome"] for l in d["midias"]] == ["Drone 1"]
    assert d["projeto"]["editor"] == "premiere" and d["projeto"]["masters"] == 1
    # ⛔ Nem como opção de varredura: medido no spike de 2026-09-22, a lista das
    #    `Avid MediaFiles` era o único rastro do Avid na resposta do Premiere.
    assert d["pastas"] == []


def test_a_aba_no_avid_nao_lista_o_banco_do_premiere(monkeypatch, tmp_path):
    C.Midia("b" * 64, origem="premiere", rotulo={"nome": "DO PREMIERE"}).pasta  # noqa: B018
    C.Midia("a" * 64, origem="avid", rotulo={"nome": "DO AVID"}).pasta  # noqa: B018
    d = _vetores("avid")
    assert [l["nome"] for l in d["midias"]] == ["DO AVID"]
    assert d["projeto"]["editor"] == "avid"


def test_premiere_sem_painel_diz_por_que_a_lista_esta_vazia(monkeypatch, tmp_path):
    monkeypatch.setattr(PT, "painel_vivo", lambda: False)
    d = _vetores()
    assert d["midias"] == [] and "não há projeto aberto" in d["projeto"]["erro"]
    r = _analisar({"estagio": "transcricao", "nle": "premiere"})
    assert r.status == 400 and "Premiere" in _corpo(r)["erro"]


# ── a fila: o cruzamento acontece AO PROCESSAR ───────────────────────────────

def test_a_fila_aproveita_antes_de_processar(monkeypatch, tmp_path):
    """⭐⭐ O gesto do editor: mandar processar é o que cruza os bancos. O que a cópia
    resolveu não passa pelo ASR; o que não tinha par é transcrito, na entrada NOVA."""
    pronto = _arquivo(tmp_path, "C14 P1-T010.WAV")
    novo = _arquivo(tmp_path, "B001_C003.mp4")
    _projeto(monkeypatch, tmp_path, [
        {"arquivo": pronto, "nome": "som do take", "bins": ["S"]},
        {"arquivo": novo, "nome": "camera", "bins": ["C"]}])

    def aproveitar(arquivo, origem, rotulo=None, **k):
        assert origem == "premiere"
        chave = ("c" if "WAV" in str(arquivo) else "d") * 64
        m = C.Midia(chave, origem="premiere", rotulo=rotulo)
        m.pasta  # noqa: B018
        if "WAV" in str(arquivo):
            m.guardar_transcricao([{"texto": "ola", "inicio": 0.0, "fim": 1.0}])
            m.registrar_gerador(E.TRANSCRICAO, E.assinatura(E.TRANSCRICAO))
            return I.Aproveitamento(midia=m, medida=1.0, copiados=["transcricao.json"])
        return I.Aproveitamento(midia=m)

    monkeypatch.setattr(I, "aproveitar", aproveitar)
    transcritas = []
    monkeypatch.setattr(R._analise, "transcrever_master",
                        lambda midia, arquivos, nome, **k: transcritas.append(
                            (midia.chave, arquivos, nome)))

    r = _analisar({"estagio": "transcricao", "nle": "premiere"})
    assert r.status == 200, _corpo(r)
    assert _corpo(r)["na_fila"] == 2
    _esperar()

    assert transcritas == [("d" * 64, [novo], "camera")]
    resumo = T.atual().resumo
    assert resumo["feitas"] == 1 and resumo["aproveitadas"] == 1 and not resumo["falharam"]


def test_a_fila_do_premiere_ignora_o_recorte_do_avid(monkeypatch, tmp_path):
    """⛔ No Premiere a lista JÁ É o projeto: o recorte do Avid (outro projeto, ou a foto
    de dias atrás) esvaziaria a fila com a frase "fora do projeto"."""
    from cicloassist.avid import escopo as ESC
    novo = _arquivo(tmp_path, "C14 P1-T010.WAV")
    _projeto(monkeypatch, tmp_path, [{"arquivo": novo, "nome": "som", "bins": ["S"]}])
    monkeypatch.setattr(ESC, "agora", lambda *a, **k: ESC.Escopo(
        chaves=frozenset({"f" * 64}), projeto="D:/X/_ASSIST ANTERIOR", origem="foto"))
    monkeypatch.setattr(I, "aproveitar", lambda arquivo, origem, rotulo=None, **k:
                        I.Aproveitamento(midia=C.Midia("e" * 64, origem=origem,
                                                       rotulo=rotulo)))
    monkeypatch.setattr(R._analise, "transcrever_master", lambda *a, **k: None)

    r = _analisar({"estagio": "transcricao", "nle": "premiere"})
    corpo = _corpo(r)
    assert r.status == 200 and corpo["fora_do_projeto"] == 0 and corpo["na_fila"] == 1
    _esperar()


def test_o_filtro_da_tela_manda_com_chaves_de_linha(monkeypatch, tmp_path):
    """⭐ A tela filtra pelas chaves que ELA recebeu — que, antes de processar, são as da
    linha. A fila tem de reconhecê-las."""
    a = _arquivo(tmp_path, "C14 P1-T010.WAV")
    b = _arquivo(tmp_path, "B001_C003.mp4")
    _projeto(monkeypatch, tmp_path, [{"arquivo": a, "nome": "som", "bins": ["S"]},
                                     {"arquivo": b, "nome": "cam", "bins": ["C"]}])
    so_o_som = P.chave_provisoria(a)
    monkeypatch.setattr(I, "aproveitar", lambda arquivo, origem, rotulo=None, **k:
                        I.Aproveitamento(midia=C.Midia("e" * 64, origem=origem,
                                                       rotulo=rotulo)))
    nomes = []
    monkeypatch.setattr(R._analise, "transcrever_master",
                        lambda midia, arquivos, nome, **k: nomes.append(nome))

    r = _analisar({"estagio": "transcricao", "nle": "premiere", "chaves": [so_o_som]})
    assert _corpo(r)["na_fila"] == 1
    _esperar()
    assert nomes == ["som"]


def test_o_painel_declara_o_editor_na_aba_vetores():
    """⛔ Sem o `nle`, o serviço não tem como saber que a tela é do Premiere — a causa raiz
    do defeito da aba Busca, que não pode se repetir aqui."""
    from pathlib import Path
    js = (Path(R.__file__).parent.parent / "painel" / "painel.js").read_text(encoding="utf-8")
    assert 'fetch("/vetores?nle=" + NLE' in js
    assert "pedido.nle = NLE;" in js
