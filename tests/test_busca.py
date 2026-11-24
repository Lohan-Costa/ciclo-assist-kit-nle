"""A aba Busca: procurar SEM gastar um turno do modelo.

⭐⭐ **As duas buscas já existiam; o que faltava era o editor alcançá-las.** Até aqui
`procurar_no_material` e `planos_parecidos` eram só ferramentas MCP: para achar um plano, o
editor escrevia uma pergunta e pagava um turno. O motor é o mesmo (`midia/decupagem.py` e
`midia/vetores.py`); o que estas rotas acrescentam é o editor perguntando direto.

⇒ O que estes testes trancam não é o motor (que tem os seus), e sim as três promessas que
a TELA faz e o chat não precisava fazer:

1. o tamanho do que a busca alcança vem SEMPRE junto — sem modelo para dizer a frase,
   "não achei" se lê como "meu material não tem isso";
2. o recorte do projeto aberto vale aqui como vale lá, e é dito em voz alta;
3. a chave vem na URL, e URL é entrada não confiável: sem `cache.e_chave`, uma tag `<img>`
   leria a máquina do editor por dentro.
"""

from __future__ import annotations

import json

import pytest

from cicloassist.avid import escopo as E
from cicloassist.midia import cache as C
from cicloassist.midia import vetores as V
from cicloassist.servico import rotas as R
from cicloassist.servico.http import Pedido

from .test_inventario import IMAGEM, midia_de_imagem


def chamar(metodo, caminho, corpo=None, consulta=None):
    pedido = Pedido(metodo, caminho, {},
                    json.dumps(corpo).encode("utf-8") if corpo is not None else b"",
                    consulta or {})
    return R.ROTAS[(metodo, caminho)][0](pedido)


def json_de(resposta):
    return json.loads(resposta.corpo.decode("utf-8"))


@pytest.fixture
def cache_com_decupagem(tmp_path, monkeypatch):
    """Duas mídias decupadas e uma que ninguém olhou — é a proporção que a frase conta."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    m = midia_de_imagem(tmp_path, nome="C07_P01-T001")
    m.anotar({
        "trecho": "C07_P01-T001", "escopo": "midia",
        "descricao": "close de Personagem F no consultório, blusa vermelha de babados",
        "enquadramento": "close", "momento": "noite", "local": "interior",
        "inicio_frames": 1000,
        "confianca": "inferido", "fonte": "visual",
    })
    outra = C.Midia(
        "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.11111111.1dc80000."
        "060e2b34.7f7f2a80", raiz_do_cache=tmp_path)
    outra.anotar_fonte({"master": "C07_P02-T004"})
    outra.anotar({"trecho": "C07_P02-T004", "escopo": "midia",
                  "descricao": "plano geral da rua, dia", "enquadramento": "geral",
                  "momento": "dia", "local": "exterior", "inicio_frames": 40,
                  "confianca": "inferido", "fonte": "visual"})
    nunca_olhada = C.Midia(
        "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.22222222.1dc80000."
        "060e2b34.7f7f2a80", raiz_do_cache=tmp_path)
    nunca_olhada.anotar_fonte({"master": "C07_P03-T001"})
    return tmp_path


# ── a busca por frase ────────────────────────────────────────────────────────

def test_a_frase_acha_pelo_texto_da_decupagem(cache_com_decupagem):
    d = json_de(chamar("POST", "/busca/frase", {"termos": "consultório"}))
    assert d["ok"] and d["quantos"] == 1
    assert d["achados"][0]["take"] == "C07_P01-T001"
    assert "consultório" in d["achados"][0]["trecho_da_descricao"]


def test_a_aba_recebe_a_descricao_inteira_para_a_setinha(cache_com_decupagem):
    """⭐ Pedido do editor (2026-09-22): o trecho em volta do termo continua o padrão, e a
    descrição inteira vai junto para a setinha do cartão abrir. ⚠️ Só na ABA: o `formatar`
    do chat continua mandando só o trecho (ver `test_decupagem.test_o_trecho_devolvido_e_curto`)."""
    d = json_de(chamar("POST", "/busca/frase", {"termos": "consultório"}))
    achado = d["achados"][0]
    assert achado["descricao"].startswith(achado["trecho_da_descricao"].strip("…")[:20])
    assert len(achado["descricao"]) >= len(achado["trecho_da_descricao"].strip("…"))


def test_os_campos_fechados_filtram(cache_com_decupagem):
    """⛔ Prosa não filtra — é por isso que a nota tem cinco campos fechados."""
    d = json_de(chamar("POST", "/busca/frase", {"momento": "noite"}))
    assert [a["take"] for a in d["achados"]] == ["C07_P01-T001"]
    d = json_de(chamar("POST", "/busca/frase", {"local": "exterior"}))
    assert [a["take"] for a in d["achados"]] == ["C07_P02-T004"]


def test_o_sinonimo_do_vocabulario_vale_aqui_tambem(cache_com_decupagem):
    d = json_de(chamar("POST", "/busca/frase", {"enquadramento": "primeiro plano"}))
    assert d["ok"] and [a["take"] for a in d["achados"]] == ["C07_P01-T001"]


def test_valor_inventado_volta_com_a_lista_e_status_200(cache_com_decupagem):
    """⚠️ 200, e não 4xx: a tela mostra a frase (que diz os valores aceitos). Um 4xx viraria
    "não consegui falar com o serviço" — o sintoma errado, que manda depurar a rede."""
    r = chamar("POST", "/busca/frase", {"enquadramento": "xis"})
    assert r.status == 200
    d = json_de(r)
    assert d["ok"] is False
    assert "close" in d["erro"], "a recusa tem de trazer a lista, que é o que resolve"


def test_pedido_vazio_diz_o_que_fazer(cache_com_decupagem):
    d = json_de(chamar("POST", "/busca/frase", {}))
    assert d["ok"] is False and "procurar" in d["erro"]


def test_o_tamanho_do_que_a_busca_alcanca_vem_SEMPRE(cache_com_decupagem):
    """⚠️⚠️ A promessa central da aba. Sem estes números, "0 achados" se lê como "meu
    material não tem isso" — e o editor acredita. Vale inclusive quando ACHOU.

    ⛔⛔ E são QUATRO, não dois: vendo "168 de 323 mídias decupadas" o editor perguntou
    *"168 seriam as mídias do projeto e 323 o total do banco?"* (2026-09-20). Rótulo que
    gera essa pergunta é rótulo que falhou — faltava separar as camadas e dizer o tamanho
    do projeto."""
    achou = json_de(chamar("POST", "/busca/frase", {"termos": "consultório"}))
    nada = json_de(chamar("POST", "/busca/frase", {"termos": "helicóptero"}))
    for d in (achou, nada):
        assert d["alcance"]["decupadas"] == 2, d
        assert d["alcance"]["no_cache"] == 3, "a que ninguém olhou conta no total"
        assert "transcritas" in d["alcance"], "a camada de fala tem o tamanho dela"


def test_decupadas_conta_DECUPAGEM_e_nao_arquivo(cache_com_decupagem):
    """⛔ MEDIDO em 2026-09-20: 4 das 172 "decupadas" do cache real eram `notas.json`
    VAZIOS (os que o `tools/consertar_quadros.py` esvaziou). A tela prometia material que
    a busca não tinha."""
    from cicloassist.midia import busca as B

    vazia = C.Midia("f" * 64, raiz_do_cache=cache_com_decupagem)
    vazia.anotar_fonte({"master": "sem nota nenhuma"})
    (vazia.pasta / "notas.json").write_text("[]", encoding="utf-8")

    a = B.medir_alcance(raiz=cache_com_decupagem)
    assert a.no_cache == 4
    assert a.decupadas == 2, "o arquivo vazio não é uma decupagem"


def test_a_busca_respeita_o_recorte_do_projeto(cache_com_decupagem, monkeypatch):
    """⭐⭐ O mesmo recorte da ferramenta. O cache atravessa projetos DE PROPÓSITO, e
    material de outra produção é resposta errada que parece certa."""
    so_a_primeira = E.Escopo(chaves=frozenset({C.de_umid(IMAGEM)}), projeto="C07",
                             origem="projeto")
    monkeypatch.setattr(R._escopo, "agora", lambda *a, **k: so_a_primeira)

    d = json_de(chamar("POST", "/busca/frase", {"termos": "plano"}))
    assert d["quantos"] == 0, "a segunda mídia está fora do recorte"
    assert d["alcance"]["decupadas"] == 1 and d["alcance"]["no_cache"] == 1, (
        "o tamanho dito é o do MESMO recorte, senão a frase mente")
    assert d["escopo"]["projeto"] == "C07"


def test_o_recorte_e_dito_em_voz_alta(cache_com_decupagem):
    """⚠️ Filtro calado é pior que filtro nenhum."""
    d = json_de(chamar("POST", "/busca/frase", {"termos": "consultório"}))
    assert isinstance(d["aviso"], str)
    assert d["escopo"], "a resposta sem escopo deixaria a tela sem o que dizer"


# ── planos parecidos ─────────────────────────────────────────────────────────

def test_parecidos_sem_o_modelo_diz_o_que_falta(cache_com_decupagem, monkeypatch):
    """⭐ "Não achei nada" mandaria o editor procurar no material; o que resolve é o botão
    da aba Vetores, e a frase o diz."""
    monkeypatch.setattr(R._vetores, "temos_o_modelo", lambda: False)
    d = json_de(chamar("POST", "/busca/parecidos", {"chave": C.de_umid(IMAGEM)}))
    assert d["ok"] is False and "Vetores" in d["erro"]


def test_parecidos_recusa_chave_que_nao_e_chave(cache_com_decupagem, monkeypatch):
    monkeypatch.setattr(R._vetores, "temos_o_modelo", lambda: True)
    for torta in ("../../etc/passwd", "", "ABC", "x" * 64):
        d = json_de(chamar("POST", "/busca/parecidos", {"chave": torta}))
        assert d["ok"] is False, torta


def test_parecidos_sem_quadro_no_cache_manda_analisar(cache_com_decupagem, monkeypatch):
    monkeypatch.setattr(R._vetores, "temos_o_modelo", lambda: True)
    vazia = C.de_umid("urn:smpte:umid:060a2b34.01010105.01010d43.13000000.22222222."
                      "1dc80000.060e2b34.7f7f2a80")
    d = json_de(chamar("POST", "/busca/parecidos", {"chave": vazia}))
    assert d["ok"] is False and "Vetores" in d["erro"]


def test_parecidos_exclui_o_proprio_plano(cache_com_decupagem, monkeypatch):
    """⭐⭐ Trazer o próprio plano de volta faz QUALQUER motor acertar 100%, inclusive um
    que comparasse o tamanho em bytes — foi o erro da primeira versão do spike (banco:
    `transversal/busca-visual-no-acervo.md`)."""
    chave = C.de_umid(IMAGEM)
    visto = {}
    monkeypatch.setattr(R._vetores, "temos_o_modelo", lambda: True)
    monkeypatch.setattr(R._vetores, "de_jpeg", lambda jpeg: [0.0])

    def espiao(alvo, limite=8, exceto="", raiz=None, chaves=None, exceto_frame=None):
        visto["exceto"] = exceto
        visto["chaves"] = chaves
        # ⭐ Em material montado, o quadro de origem faz sair só o PLANO dele (2026-09-22).
        visto["exceto_frame"] = exceto_frame
        return [{"chave": "b" * 64, "nome": "outro", "frame_no_master": 12,
                 "parecenca": 0.91}]

    monkeypatch.setattr(R._vetores, "procurar", espiao)
    d = json_de(chamar("POST", "/busca/parecidos", {"chave": chave}))

    assert visto["exceto"] == chave, "o próprio plano tem de sair da busca"
    assert d["parecidos"][0]["confianca"] == "inferido", "procedência em todo item"
    assert d["parecidos"][0]["medida"] == 0.91, "⚠️ medida vazia seria 'não medido'"


def test_o_quadro_de_referencia_e_o_do_MEIO_quando_ninguem_pede_um(cache_com_decupagem):
    """⚠️ E não o primeiro: o primeiro quadro de um master é claquete com frequência
    demais para representar o plano."""
    chave = C.de_umid(IMAGEM)
    jpeg, devolvida, erro = R._quadro_de_referencia(chave, None)
    assert not erro and devolvida == chave and jpeg
    guardados = C.Midia(chave).quadros_guardados()
    assert guardados == [1000, 1001, 1002]
    assert jpeg == C.Midia(chave).caminho_do_quadro(1001).read_bytes()


def test_o_quadro_de_referencia_cai_no_mais_proximo(cache_com_decupagem):
    """A posição vem de outra busca e pode não ser um dos quadros amostrados DESTA mídia."""
    jpeg, _, erro = R._quadro_de_referencia(C.de_umid(IMAGEM), 99999)
    assert not erro and jpeg


# ── o quadro que a tela mostra ───────────────────────────────────────────────

def test_o_quadro_sai_como_jpeg_e_cacheavel(cache_com_decupagem):
    r = chamar("GET", "/busca/quadro", consulta={"chave": C.de_umid(IMAGEM),
                                                 "frame": "1000"})
    assert r.status == 200 and r.tipo == "image/jpeg"
    assert r.corpo == b"\xff\xd8fake"
    # ⚠️ O quadro de uma posição do master nunca muda: sem isto, rolar a lista rebusca tudo.
    assert "immutable" in r.extras.get("Cache-Control", "")


def test_o_quadro_recusa_caminho_disfarcado_de_chave(cache_com_decupagem):
    """⛔⛔ A chave chega na URL, e URL é entrada não confiável como qualquer outra. Sem
    `cache.e_chave`, uma tag `<img>` leria a máquina do editor por dentro."""
    for torta in ("../../../Windows/win.ini", "..", "", "a/b", "A" * 64):
        r = chamar("GET", "/busca/quadro", consulta={"chave": torta, "frame": "0"})
        assert r.status == 400, torta


def test_o_quadro_que_nao_esta_no_cache_e_404_e_nao_extrai_nada(cache_com_decupagem):
    """⚠️ Extrair aqui faria a tela de resultados disparar dezenas de ffmpeg enquanto o
    editor rola a lista."""
    r = chamar("GET", "/busca/quadro", consulta={"chave": C.de_umid(IMAGEM),
                                                 "frame": "777777"})
    assert r.status == 404


def test_quadro_nao_numerico_e_400(cache_com_decupagem):
    r = chamar("GET", "/busca/quadro", consulta={"chave": C.de_umid(IMAGEM),
                                                 "frame": "meio"})
    assert r.status == 400


# ── o vocabulário ────────────────────────────────────────────────────────────

def test_o_vocabulario_vem_do_servico_e_nao_de_uma_copia_no_JS():
    """⛔ `midia/decupagem.py` é quem define os campos fechados. Dois literais iguais em
    dois arquivos divergem calados — a tela ofereceria um valor que nota nenhuma usa."""
    from cicloassist.midia import decupagem as D

    d = json_de(chamar("GET", "/busca/vocabulario"))
    servidos = {c["campo"]: c["valores"] for c in d["campos"]}
    assert servidos == {campo: list(valores) for campo, valores in D.CAMPOS.items()}


# ── a query string, que é o que faz a miniatura existir ──────────────────────

def test_a_query_string_chega_a_rota():
    """⚠️ `ROTAS` é caminho EXATO — `/busca/quadro?chave=…` e `/busca/quadro` são a mesma
    rota, e é `Pedido.consulta` que carrega o resto. Sem isto a miniatura não teria como
    dizer de que mídia é."""
    from urllib.parse import parse_qs, urlparse

    caminho = "/busca/quadro?chave=" + "a" * 64 + "&frame=12&frame=99"
    consulta = {n: v[0] for n, v in
                parse_qs(urlparse(caminho).query, keep_blank_values=True).items()}
    assert consulta == {"chave": "a" * 64, "frame": "12"}, (
        "repetido é ambiguidade; ficar com 'o último' faria a rota mudar de resposta "
        "conforme a ordem")
    assert urlparse(caminho).path == "/busca/quadro"


def test_pedido_sem_consulta_continua_valendo():
    """Todas as rotas de antes constroem o `Pedido` com quatro campos."""
    p = Pedido("GET", "/saude", {})
    assert p.consulta == {}


# ── a busca de parecença de ponta a ponta ────────────────────────────────────

def test_parecidos_le_os_npy_do_cache_e_devolve_uma_linha_por_midia(cache_com_decupagem,
                                                                    monkeypatch):
    """⭐ Aqui a `vetores.procurar` é a de verdade: lê os `.npy` do cache, multiplica a
    matriz e ordena. Só o CODIFICADOR fica de fora — o `.onnx` mora na pasta de dados, que
    a suíte isola de propósito (`conftest`), e o produto o baixa na primeira análise.

    ⭐⭐ E uma linha por MÍDIA, a do melhor quadro: sem isso, os doze quadros de um plano
    tomam a lista inteira e o editor vê um resultado só, doze vezes.
    """
    import numpy as np

    chave = C.de_umid(IMAGEM)
    monkeypatch.setattr(R._vetores, "temos_o_modelo", lambda: True)
    # O alvo aponta para a primeira dimensão; a vizinha tem dois quadros, e o SEGUNDO é o
    # parecido — é ele que a resposta tem de trazer.
    alvo = np.zeros(1000, dtype="float32"); alvo[0] = 1.0
    monkeypatch.setattr(R._vetores, "de_jpeg", lambda jpeg: alvo)

    vizinha = C.Midia("b" * 64, raiz_do_cache=cache_com_decupagem)
    vizinha.anotar_fonte({"master": "vizinha"})
    quadros = np.zeros((2, 1000), dtype="float32")
    quadros[0][1] = 1.0
    quadros[1][0] = 1.0
    V.guardar(vizinha, quadros, [7, 99])

    d = json_de(chamar("POST", "/busca/parecidos", {"chave": chave, "frame": 1000}))

    assert d["ok"], d
    assert len(d["parecidos"]) == 1, "uma linha por mídia, não uma por quadro"
    (p,) = d["parecidos"]
    assert p["chave"] == "b" * 64 and p["frame_no_master"] == 99
    assert p["parecenca"] == 1.0 and p["medida"] == 1.0
    assert all(x["chave"] != chave for x in d["parecidos"]), (
        "o próprio plano tem de ficar fora — ver `busca-visual-no-acervo.md`")


def test_parecidos_nao_sai_do_recorte_do_projeto(cache_com_decupagem, monkeypatch):
    """⚠️ Um match cut proposto com material de outra produção é pior que nenhum: a
    parecença é verdadeira e o plano não existe para este editor."""
    import numpy as np

    monkeypatch.setattr(R._vetores, "temos_o_modelo", lambda: True)
    monkeypatch.setattr(R._vetores, "de_jpeg",
                        lambda jpeg: np.zeros(1000, dtype="float32"))
    monkeypatch.setattr(R._escopo, "agora",
                        lambda *a, **k: E.Escopo(chaves=frozenset(), projeto="C07",
                                                 origem="projeto"))

    vizinha = C.Midia("b" * 64, raiz_do_cache=cache_com_decupagem)
    vizinha.anotar_fonte({"master": "vizinha"})
    V.guardar(vizinha, np.zeros((1, 1000), dtype="float32"), [7])

    d = json_de(chamar("POST", "/busca/parecidos", {"chave": C.de_umid(IMAGEM),
                                                    "frame": 1000}))
    assert d["ok"] and d["quantos"] == 0, "projeto vazio é recorte, não 'sem filtro'"


# ── a miniatura, que é o que faz esta busca ser VISUAL ───────────────────────

def test_sem_frame_o_quadro_e_o_representativo_da_midia(cache_com_decupagem):
    """⭐⭐ A nota de escopo `midia` descreve o material INTEIRO e não tem `inicio_frames`
    (medido no cache real: `None` em todas). Exigindo uma posição, a primeira tela com o
    acervo de verdade saiu SEM miniatura nenhuma — numa aba cujo ponto é olhar."""
    r = chamar("GET", "/busca/quadro", consulta={"chave": C.de_umid(IMAGEM)})
    assert r.status == 200 and r.tipo == "image/jpeg"


def test_com_perto_o_quadro_cai_no_guardado_mais_proximo(cache_com_decupagem):
    """A nota de TAKE aponta um frame do master que quase nunca é um dos 12 amostrados."""
    r = chamar("GET", "/busca/quadro",
               consulta={"chave": C.de_umid(IMAGEM), "frame": "1500", "perto": "1"})
    assert r.status == 200


def test_sem_perto_a_posicao_continua_EXATA(cache_com_decupagem):
    """⛔⛔ E é por isso que `perto` é explícito. A lista de parecidos pede posições que
    `vetores.procurar` devolveu; um "mais próximo" calado ali mostraria um quadro dizendo
    ser outro — e o editor corta pelo que viu."""
    r = chamar("GET", "/busca/quadro",
               consulta={"chave": C.de_umid(IMAGEM), "frame": "1500"})
    assert r.status == 404


def test_o_painel_pede_aproximado_na_lista_e_exato_nos_parecidos():
    """⚠️ O contrato dos dois lados, sem DOM: a miniatura do achado usa `perto=1`; a do
    parecido usa a posição que o vetor devolveu, e nunca `perto`."""
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "cicloassist" / "painel"
          / "painel.js").read_text(encoding="utf-8")
    achado = js[js.index("function cartaoDoAchado"):js.index("function procurarParecidos")]
    parecidos = js[js.index("function listaDeParecidos"):]
    assert "perto=1" in achado, "a miniatura do achado tem de aceitar o quadro mais próximo"
    assert "perto" not in parecidos, "o parecido aponta a posição que o vetor devolveu"
    assert "frame_no_master" in parecidos


# ── os termos entre línguas (`midia/termos.json`) ────────────────────────────

def test_claquete_acha_clapperboard_e_vice_versa():
    """⛔ MEDIDO (2026-09-22): a decupagem escreveu `clapperboard` em 39 notas e `claquete`
    em 2 — e o editor, procurando "claquete", não achou nada. O grupo vale nos DOIS
    sentidos."""
    from cicloassist.midia import intencao as IN
    assert "clapperboard" in IN.alternativas("claquete")
    assert "claquete" in IN.alternativas("Clapperboard")
    assert "claquete" in IN.alternativas("slate")


def test_a_decupagem_passa_a_escrever_em_portugues_sem_proibir_portugues():
    """⭐ O PREFERIDO de cada grupo vira instrução — nos dois motores (Claude e Mac). ⛔ E
    `evitar` não é `tambem`: "lapela" é português legítimo e não pode ser proibida."""
    from cicloassist.motor import decupador as D
    from cicloassist.motor import percepcao as PC
    assert "claquete (não clapperboard" in D.PERSONA
    assert "claquete (não clapperboard" in PC.persona_plana()
    assert "não lapela" not in D.PERSONA and "{IDIOMA}" not in D.PERSONA


def test_todo_grupo_do_dicionario_e_valido():
    """⚠️ É DADO editado à mão: grupo sem preferido, ou `evitar` fora de `tambem`, é erro de
    digitação que a busca não acusaria."""
    from cicloassist.midia import intencao as IN
    grupos = IN.grupos_de_termos()
    assert grupos, "termos.json ilegível vira lista vazia calada"
    for g in grupos:
        assert g["preferido"] and g["tambem"]
        assert set(g["evitar"]) <= set(g["tambem"]), g["preferido"]
