"""A decupagem no Mac — o servidor de percepção na rede.

⚠️ **O que se protege aqui é para onde vão os quadros do cliente, e o que volta deles.**
Um endereço aceito por engano manda material para fora da casa, ou para este notebook (tela
azul). E uma resposta aceita sem a validação grava decupagem plausível na mídia errada.
Nenhum teste fala com o Mac de verdade: `pedir` é trocado por uma resposta escrita aqui.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.midia import acervo as A
from cicloassist.midia import cache as C
from cicloassist.motor import decupador as D
from cicloassist.motor import percepcao as P
from cicloassist.servico import config as K
from cicloassist.servico import rotas as R
from cicloassist.servico import tarefas as T
from cicloassist.servico.http import Pedido

IMAGEM = "0x060A2B340101010101010F0013000000C6D91F0BB8ABB1C7ABEE2FFBA70D1E05"
SOM = "0x060A2B340101010101010F0013000000E56E1D13D305BE564AEC678A24E90A70"

RESPOSTA = {"descricao": "Uma mulher de blusa vermelha fala ao telefone.",
            "etiquetas": ["telefone"], "enquadramento": "primeiro plano",
            "local": "interior", "momento": "noite", "camera": "drone"}


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("CICLOASSIST_OLLAMA", raising=False)
    T.esquecer()
    yield tmp_path / "cache"
    T.parar()
    T.esquecer()


# ── para onde os quadros podem ir ────────────────────────────────────────────

@pytest.mark.parametrize("bruto, esperado", [
    ("192.168.1.4", "http://192.168.1.4:11434"),
    ("http://192.168.1.4:11434/", "http://192.168.1.4:11434"),
    ("10.0.0.7:8080", "http://10.0.0.7:8080"),
    ("http://mac-mini.local:11434", "http://mac-mini.local:11434"),
])
def test_rede_local_e_aceita(bruto, esperado):
    assert P.validar(bruto) == esperado


@pytest.mark.parametrize("bruto", [
    "127.0.0.1:11434", "http://localhost:11434", "0.0.0.0", "[::1]:11434",
])
def test_este_notebook_e_recusado(bruto):
    """⛔⛔ Telas azuis repetidas com modelo local ao lado do Media Composer."""
    with pytest.raises(ValueError, match="próprio notebook"):
        P.validar(bruto)


@pytest.mark.parametrize("bruto", ["8.8.8.8", "http://ollama.exemplo.com", "ftp://192.168.1.4"])
def test_fora_da_rede_local_e_recusado(bruto):
    """⛔ O Ollama não tem senha, e os quadros são do cliente."""
    with pytest.raises(ValueError):
        P.validar(bruto)


def test_sem_endereco_a_decupagem_fica_no_claude():
    assert P.endereco() == ""


def test_o_ambiente_ganha_da_config(monkeypatch):
    K.gravar({"ollama": "http://192.168.1.4:11434"})
    assert P.endereco() == "http://192.168.1.4:11434"
    monkeypatch.setenv("CICLOASSIST_OLLAMA", "http://192.168.1.9:11434")
    assert P.endereco() == "http://192.168.1.9:11434"


def test_config_com_endereco_ruim_vira_vazio_e_nao_excecao():
    K.gravar({"ollama": "http://127.0.0.1:11434"})     # gravado por fora da rota
    assert P.endereco() == ""


def test_a_rota_de_configuracoes_recusa_o_notebook():
    r = R.rota_gravar_configuracoes(
        Pedido("POST", "/configuracoes", {}, json.dumps({"ollama": "localhost"}).encode()))
    assert r.status == 400
    assert "ollama" not in K.ler()


def test_a_rota_de_configuracoes_grava_normalizado():
    R.rota_gravar_configuracoes(
        Pedido("POST", "/configuracoes", {}, json.dumps({"ollama": "192.168.1.4"}).encode()))
    assert K.ler()["ollama"] == "http://192.168.1.4:11434"


def _escolher(modelo):
    return R.rota_gravar_configuracoes(
        Pedido("POST", "/configuracoes", {}, json.dumps({"modelo": modelo}).encode()))


def test_o_modelo_do_mac_so_e_oferecido_com_o_mac(monkeypatch):
    """Sem endereço, a opção seria um erro esperando o primeiro clique."""
    ids = lambda: [m["id"] for m in json.loads(  # noqa: E731
        R.rota_configuracoes(Pedido("GET", "/configuracoes", {}, b"")).corpo)["modelos"]]
    local = K.MODELOS_LOCAIS[0]["id"]
    assert local not in ids()
    assert _escolher(local).status == 400 and "modelo" not in K.ler()
    monkeypatch.setenv("CICLOASSIST_OLLAMA", "192.168.1.4")
    assert local in ids()
    assert _escolher(local).status == 200 and K.ler()["modelo"] == local


def test_a_fila_pelo_claude_nunca_manda_o_modelo_do_mac():
    """⛔ `ollama:…` no `--model` de um CLI falando com a Anthropic."""
    K.gravar({"modelo": K.MODELOS_LOCAIS[0]["id"]})
    assert R._modelo_do_claude() == K.PADRAO


# ── o pedido e a resposta ────────────────────────────────────────────────────

def test_persona_plana_sem_placeholder_e_um_objeto_so():
    """⛔ MEDIDO: o VLM copiou `<chave da mídia>` e respondeu um objeto por quadro."""
    p = P.persona_plana()
    assert "<chave da mídia>" not in p
    assert "UM ÚNICO objeto" in p
    assert "Quando vierem várias mídias" not in p
    assert "contra-plongée" in p                     # o vocabulário continua lá


def test_o_corpo_leva_contexto_temperatura_e_as_imagens():
    corpo = P.corpo_do_pedido([b"a", b"b"], [0, 24], {"fps": "24000/1001", "nome": "C001",
                                                      "duracao_s": 10}, "k")
    assert corpo["options"] == {"temperature": 0, "num_ctx": P.CONTEXTO}
    assert corpo["stream"] is False
    usuario = corpo["messages"][1]
    assert usuario["images"] == ["YQ==", "Yg=="]
    assert "C001" in usuario["content"] and "1.0" in usuario["content"]


def test_modelo_que_nao_ve_e_recusado(monkeypatch):
    monkeypatch.setattr(P, "pedir", lambda *a, **k: {"capabilities": ["completion", "tools"]})
    with pytest.raises(P.MacIndisponivel, match="não vê"):
        P.conferir("http://192.168.1.4:11434")


def _falso_quadros(monkeypatch):
    from cicloassist.mcp.ferramentas import midia as M
    monkeypatch.setattr(M, "quadros_de",
                        lambda chave, q: ([b"x"] * q, list(range(q)), {"fps": "25"}))


def test_a_resposta_passa_pela_mesma_validacao(monkeypatch):
    """⭐ Sinônimo normalizado, valor inventado descartado com aviso — igual ao Claude."""
    _falso_quadros(monkeypatch)
    monkeypatch.setattr(P, "pedir", lambda *a, **k: {
        "message": {"content": json.dumps(RESPOSTA)},
        "prompt_eval_count": 6229, "eval_count": 180})
    feito = P.decupar("http://192.168.1.4:11434", "chave")
    nota = feito["notas"]["chave"]
    assert nota["enquadramento"] == "close"
    assert "camera" not in nota
    assert any("drone" in a for a in feito["avisos"])
    assert feito["uso"]["tokens"] == 6409 and "custo_usd" not in feito["uso"]


def test_mac_fora_do_ar_e_mac_indisponivel(monkeypatch):
    import urllib.error
    _falso_quadros(monkeypatch)

    def cai(*a, **k):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(P, "pedir", cai)
    with pytest.raises(P.MacIndisponivel):
        P.decupar("http://192.168.1.4:11434", "chave")


# ── a fila ───────────────────────────────────────────────────────────────────

def _duas_imagens(raiz):
    for umid, nome in ((IMAGEM, "C001"), (SOM, "C002")):
        A.guardar(f"D:/mídia/{nome}",
                  [A.Clipe(C.de_umid(umid), nome, [f"{nome}.mxf"], {"video": 1},
                           fps="25", duracao_s=10, por_tipo={"video": [f"{nome}.mxf"]},
                           bytes=10)],
                  raiz=raiz)


def _esperar():
    import time
    limite = time.time() + 3
    while T.ha_tarefa_viva() and time.time() < limite:
        time.sleep(0.01)
    assert not T.ha_tarefa_viva()


def _analisar():
    return R.rota_analisar(Pedido("POST", "/vetores/analisar", {},
                                  json.dumps({"estagio": "decupagem"}).encode()))


def test_com_o_mac_configurado_a_fila_vai_para_ele(isolado, monkeypatch):
    """⭐ Uma mídia por pedido, nada de `claude -p`, e a nota diz QUEM olhou."""
    _duas_imagens(isolado)
    K.gravar({"ollama": "http://192.168.1.4:11434"})
    monkeypatch.setattr(P, "conferir", lambda url, modelo=P.MODELO: ["vision"])
    pedidas = []

    def no_mac(url, chave, **k):
        pedidas.append(chave)
        return {"notas": {chave: {"descricao": "um plano", "etiquetas": []}},
                "avisos": [], "uso": {"modelo": P.MODELO, "tokens": 10, "local": True},
                "segundos": 1}
    monkeypatch.setattr(P, "decupar", no_mac)
    monkeypatch.setattr(D, "decupar", lambda *a, **k: pytest.fail("foi para o Claude"))

    assert _analisar().status == 200
    _esperar()
    assert len(pedidas) == 2
    nota = C.Midia(pedidas[0]).ler_notas()[0]
    assert nota["modelo"] == P.MODELO and nota["escopo"] == "midia"
    assert T.atual().resumo["feitas"] == 2


def test_mac_que_para_de_responder_encerra_a_fila(isolado, monkeypatch):
    """⚠️ Mac dormindo não pode virar a noite inteira esperando prazo de cada mídia."""
    for i in range(5):
        umid = IMAGEM[:-2] + f"{i:02X}"
        A.guardar(f"D:/mídia/{i}",
                  [A.Clipe(C.de_umid(umid), f"C{i}", ["x.mxf"], {"video": 1}, fps="25",
                           duracao_s=10, por_tipo={"video": ["x.mxf"]}, bytes=10)],
                  raiz=isolado)
    K.gravar({"ollama": "http://192.168.1.4:11434"})
    monkeypatch.setattr(P, "conferir", lambda url, modelo=P.MODELO: ["vision"])
    tentativas = []

    def cai(url, chave, **k):
        tentativas.append(chave)
        raise P.MacIndisponivel("o Mac não respondeu")
    monkeypatch.setattr(P, "decupar", cai)

    _analisar()
    _esperar()
    assert len(tentativas) == P.FALHAS_SEGUIDAS
    assert T.atual().estado == "erro" and "Mac" in T.atual().erro


def test_a_tela_recebe_o_preco_do_mac(isolado):
    K.gravar({"ollama": "http://192.168.1.4:11434"})
    corpo = json.loads(R.rota_vetores(None).corpo.decode("utf-8"))
    assert corpo["decupagem"]["motor"] == "mac"
    assert corpo["decupagem"]["custo_por_midia_usd"] == 0


# ── o que a revisão de 2026-09-13 achou ──────────────────────────────────────

def test_ipv6_privado_sai_com_colchetes():
    assert P.validar("http://[fd00::5]:11434") == "http://[fd00::5]:11434"


def test_porta_que_nao_e_numero_e_recusada_em_portugues():
    with pytest.raises(ValueError, match="porta"):
        P.validar("192.168.1.4:abc")


def test_resposta_que_nao_e_json_e_mac_indisponivel(monkeypatch):
    """⛔ Um JSONDecodeError escapava de tudo e derrubava a fila."""
    import io

    class Resposta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(P.urllib.request, "urlopen",
                        lambda *a, **k: Resposta(b"<html>roteador</html>"))
    with pytest.raises(P.MacIndisponivel, match="não é o Ollama"):
        P.pedir("http://192.168.1.4:11434", "/api/tags")


def test_midia_que_o_ffmpeg_nao_le_nao_derruba_a_fila(isolado, monkeypatch):
    """⛔⛔ `ExtracaoFalhou` não era capturada: a primeira mídia ilegível encerrava a noite."""
    from cicloassist.midia import frames as F

    _duas_imagens(isolado)
    K.gravar({"ollama": "http://192.168.1.4:11434"})
    monkeypatch.setattr(P, "conferir", lambda url, modelo=P.MODELO: ["vision"])
    feitas = []

    def meio_a_meio(url, chave, **k):
        if not feitas and not getattr(meio_a_meio, "falhou", False):
            meio_a_meio.falhou = True
            raise F.ExtracaoFalhou("não consegui extrair o quadro 10 de x.mxf")
        feitas.append(chave)
        return {"notas": {chave: {"descricao": "um plano", "etiquetas": []}},
                "avisos": [], "uso": {"modelo": P.MODELO, "tokens": 1}, "segundos": 1}
    monkeypatch.setattr(P, "decupar", meio_a_meio)

    _analisar()
    _esperar()
    assert T.atual().estado == "pronta"
    assert T.atual().resumo["feitas"] == 1 and T.atual().resumo["falharam"] == 1


def test_quadros_extraidos_levam_a_receita(isolado, monkeypatch):
    """⛔ Sem a receita, o inventário marcava "a refazer" em toda mídia decupada no Mac."""
    from cicloassist.mcp.ferramentas import midia as M
    from cicloassist.midia import frames as F
    from cicloassist.midia import inventario as I

    _duas_imagens(isolado)
    chave = C.de_umid(IMAGEM)
    monkeypatch.setattr(F, "extrair", lambda *a, **k: b"\xff\xd8jpeg")
    M.quadros_de(chave, 6)

    midia = C.Midia(chave)
    assert midia.ler_gerador("quadros") == dict(F.ASSINATURA)
    linha = next(l for l in I.listar(clipes=A.ler(raiz=isolado).get("clipes"))
                 if l.chave == midia.chave)
    assert linha.visual.tem and linha.visual.atualizado


def test_receita_antiga_nao_e_carimbada_por_cima(isolado, monkeypatch):
    """⚠️ Se já há OUTRA receita, os quadros velhos continuam sendo dela."""
    from cicloassist.mcp.ferramentas import midia as M
    from cicloassist.midia import frames as F

    _duas_imagens(isolado)
    chave = C.de_umid(IMAGEM)
    C.Midia(chave).registrar_gerador("quadros", {"largura": 1})
    monkeypatch.setattr(F, "extrair", lambda *a, **k: b"\xff\xd8jpeg")
    M.quadros_de(chave, 6)
    assert C.Midia(chave).ler_gerador("quadros") == {"largura": 1}
