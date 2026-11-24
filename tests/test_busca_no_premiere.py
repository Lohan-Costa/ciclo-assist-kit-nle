"""A aba Busca dentro do Premiere — o defeito que o primeiro teste real mostrou (2026-09-21).

⛔⛔ **A aba Busca nasceu três dias DEPOIS do porte para o Premiere** (20/09 contra 17/09) e
passou inteira ao largo de `cicloassist/nle/`: ela chamava `avid/escopo.py` direto. Com o
painel dentro do Premiere, o editor viu, num projeto `.prproj` aberto na frente dele:

- resultados recortados pelo `_Assist anterior` — um projeto do **Media Composer**, que estava
  **fechado**, servido pela FOTO da última varredura de bins;
- a contagem em "**masterclipes**", substantivo que o Premiere não tem;
- e o duplo clique respondendo *"o Media Composer não está aberto"*.

O chat já era NLE-ciente desde o porte (`mcp/ferramentas/parecidos.py`, `mapa.py` chamam
`nle.escopo_agora()`). Era só a TELA que falava com o editor errado.

⚠️ O que estes testes NÃO cobrem, e está dito no `CLAUDE.md`: `app.sourceMonitor` na GUI de
verdade. O painel aqui é simulado — quem roda o ExtendScript é o Premiere.
"""

from __future__ import annotations

import json
import re

import pytest

from cicloassist import nle
from cicloassist.avid import escopo as ESC
from cicloassist.midia import identidade as I
from cicloassist.nle import premiere as P
from cicloassist.nle.premiere import ponte as PT
from cicloassist.nle.premiere import recortes as REC
from cicloassist.servico import rotas as R
from cicloassist.servico.http import Pedido


@pytest.fixture(autouse=True)
def limpo(monkeypatch):
    PT.esquecer()
    P.esquecer()
    REC.esquecer()
    I.esquecer()
    yield
    PT.esquecer()
    P.esquecer()
    REC.esquecer()


#: ⚠️ Os comentários deste repo CITAM a armadilha que o código evita ("não use
#: `openFilePath`", "não diga Media Composer"). Um teste que procurasse no arquivo cru
#: acusaria justamente a documentação do conserto — o instrumento medindo a si mesmo.
#: ⚠️ A linha de `//` para na quebra, e não em `.*`: com `re.S` o ponto casa quebra de
#: linha, e o primeiro `//` engoliria o arquivo inteiro — o teste passaria por VAZIO.
#: (Aconteceu ao escrever este arquivo.)
_COMENTARIO = re.compile(r"/\*.*?\*/|(?<!:)//[^\n]*", re.S)


def _sem_comentarios(texto: str) -> str:
    return _COMENTARIO.sub("", texto)


def post(caminho, corpo):
    r = R.ROTAS[("POST", caminho)][0](
        Pedido("POST", caminho, {}, json.dumps(corpo).encode("utf-8")))
    return json.loads(r.corpo.decode("utf-8"))


def get(caminho, consulta=None):
    r = R.ROTAS[("GET", caminho)][0](
        Pedido("GET", caminho, {}, b"", consulta or {}))
    return json.loads(r.corpo.decode("utf-8"))


# ── ler o NLE não pode MEXER no NLE ──────────────────────────────────────────

def test_ler_o_editor_do_pedido_nao_troca_o_editor_do_turno(monkeypatch):
    """⛔⛔ O global é o editor do TURNO, e dele dependem a persona e a lista de
    ferramentas. Uma busca na aba do Premiere virando esse valor no meio de um turno do
    Avid entregaria ao modelo as ferramentas do editor errado."""
    monkeypatch.setattr(nle, "_atual", "avid")
    pedido = Pedido("POST", "/busca/frase", {}, json.dumps({"nle": "premiere"}).encode())
    assert R._nle_da_tela(pedido) == "premiere"
    assert nle.atual() == "avid", "ler não pode definir"


def test_quem_fala_do_turno_continua_definindo(monkeypatch):
    """⭐ `/limpar` e `/conversar/parar` precisam do efeito — é o editor daquela conversa."""
    monkeypatch.setattr(nle, "_atual", "avid")
    pedido = Pedido("POST", "/limpar", {}, json.dumps({"nle": "premiere"}).encode())
    assert R._qual_nle(pedido) == "premiere"
    assert nle.atual() == "premiere"


@pytest.mark.parametrize("pedido", [
    Pedido("GET", "/projeto", {}, b"", {"nle": "premiere"}),        # pela query
    Pedido("POST", "/busca/frase", {}, b'{"nle": "premiere"}'),     # pelo corpo
])
def test_o_editor_chega_pelos_dois_caminhos(pedido):
    assert R._nle_da_tela(pedido) == "premiere"


@pytest.mark.parametrize("pedido", [
    Pedido("GET", "/projeto", {}, b""),                 # painel velho: não declara
    Pedido("POST", "/busca/frase", {}, b"nao e json"),  # corpo torto não pode estourar
    None,                                               # chamada sem pedido nenhum
])
def test_sem_declaracao_e_o_avid_o_de_sempre(pedido):
    assert R._nle_da_tela(pedido) == "avid"


# ── o recorte da busca é do projeto de QUEM PERGUNTOU ────────────────────────

def _projeto_do_premiere(monkeypatch, tmp_path, arquivos=()):
    """Um painel de Premiere simulado, com um projeto e a mídia que ele usa."""
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(I, "sondar", lambda arq: {"umid": ""})

    def chamar(funcao, *args, **k):
        if funcao == "cicloProjeto":
            return {"caminho": str(tmp_path / "CICLO ASSIST TESTE.prproj")}
        if funcao == "cicloMidias":
            return {"arquivos": [str(a) for a in arquivos]}
        return {}

    monkeypatch.setattr(PT, "chamar", chamar)


def test_a_busca_no_premiere_nao_usa_o_recorte_do_avid(monkeypatch, tmp_path):
    """⛔⛔ O defeito do print: resultados do `_Assist anterior` dentro do Premiere.

    ⚠️ Com o Media Composer FECHADO, `escopo.agora()` cai na FOTO da última varredura de
    bins — que é de outro projeto e pode ser de dias atrás. Era isso que a aba mostrava.
    """
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    a = tmp_path / "DJI_0315.mov"
    a.write_bytes(b"a" * 100)
    _projeto_do_premiere(monkeypatch, tmp_path, [a])
    I.impressao(a)  # ⭐ o recorte usa a chave JÁ conhecida, nunca a medida na hora

    foto = ESC.Escopo(chaves=frozenset({"f" * 64}), projeto="D:/X/_Assist anterior",
                      origem="foto", editor="avid")
    monkeypatch.setattr(ESC, "agora", lambda *a, **k: foto)

    d = post("/busca/frase", {"termos": "drone", "nle": "premiere"})
    assert d["ok"] and d["escopo"]["editor"] == "premiere"
    assert d["escopo"]["projeto"] == "CICLO ASSIST TESTE.prproj"
    assert "_Assist anterior" not in json.dumps(d, ensure_ascii=False)


def test_sem_declarar_o_editor_a_busca_continua_do_avid(monkeypatch, tmp_path):
    """⚠️ Painel velho com serviço novo: o comportamento de antes, nunca uma tela vazia."""
    foto = ESC.Escopo(chaves=frozenset({"f" * 64}), projeto="D:/X/_Assist anterior",
                      origem="foto", editor="avid")
    monkeypatch.setattr(ESC, "agora", lambda *a, **k: foto)
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))

    d = post("/busca/frase", {"termos": "drone"})
    assert d["escopo"]["projeto"] == "_Assist anterior" and d["escopo"]["editor"] == "avid"


def test_o_projeto_da_tela_e_o_do_editor_que_perguntou(monkeypatch, tmp_path):
    _projeto_do_premiere(monkeypatch, tmp_path)
    d = get("/projeto", {"nle": "premiere"})
    assert d["nome"] == "CICLO ASSIST TESTE.prproj" and d["editor"] == "premiere"
    # ⛔ E o Avid continua respondendo pelo Avid: o conftest diz que não há MC aberto.
    assert get("/projeto")["projeto"] == ESC.SEM_PROJETO


# ── as palavras de cada editor ───────────────────────────────────────────────

def test_o_aviso_do_recorte_fala_a_lingua_do_editor():
    """⛔ "masterclipe" não existe no Premiere, e "abra a aba Vetores e leia as bins" é
    gesto do Media Composer. O editor lê a frase e vai procurar o que não está lá."""
    ppro = ESC.Escopo(chaves=frozenset({"a" * 64}), projeto="D:/p/X.prproj",
                      origem="projeto", editor="premiere")
    assert "clipe(s)" in ppro.aviso and "masterclipe" not in ppro.aviso
    assert "Media Composer" not in ppro.aviso

    avid = ESC.Escopo(chaves=frozenset({"a" * 64}), projeto="D:/p/PROJ",
                      origem="projeto", editor="avid")
    assert "masterclipe(s)" in avid.aviso and "bins" in avid.aviso

    # ⚠️ Sem recorte nenhum, o conselho também muda: no Premiere não há "ler as bins".
    assert "aba Vetores" not in ESC.Escopo(chaves=None, editor="premiere").aviso
    assert "aba Vetores" in ESC.Escopo(chaves=None, editor="avid").aviso


def test_o_painel_manda_o_editor_em_toda_pergunta_da_busca():
    """⛔⛔ A causa raiz: sem o painel DECLARAR o editor, o serviço não tem como saber."""
    js = (R.DIR_PAINEL / "painel.js").read_text(encoding="utf-8")
    for pedaco in ('"/busca/recortes?nle=" + NLE', '"/projeto?nle=" + NLE',
                   "preferir_subclipes: busPreferir.checked, nle: NLE",
                   'mob: a.mob_do_item || "", nle: NLE',
                   "frame: frame, quantos: 6, nle: NLE"):
        assert pedaco in js, f"a chamada perdeu o editor: {pedaco}"


def test_o_painel_nao_tem_nomenclatura_do_avid_cravada_na_busca():
    """⚠️ Duas cópias das mesmas palavras divergem caladas — daí `PALAVRAS`."""
    js = _sem_comentarios((R.DIR_PAINEL / "painel.js").read_text(encoding="utf-8"))
    # ⭐ As frases exatas que o editor leu dentro do Premiere, e que agora vêm da tabela.
    assert "monitor Source do Media Composer" not in js
    assert '" masterclipes)"' not in js
    assert js.count("PALAVRAS.nle") >= 2 and js.count("PALAVRAS.unidade") >= 2

    # ⚠️ E a aba VETORES continua dizendo "Media Composer" de propósito: ela lê as bins
    #   DELE mesmo dentro do Premiere (a invariante da revisão de 2026-09-17), e a frase
    #   é o que impede o editor de decidir o que analisar em cima do projeto errado.
    assert "(do Media Composer, não deste projeto do Premiere)" in js


# ── o duplo clique dentro do Premiere ────────────────────────────────────────

def test_o_duplo_clique_no_premiere_nao_fala_com_o_media_composer(monkeypatch, tmp_path):
    """⛔⛔ O print do editor: *"o Media Composer não está aberto"*, num Premiere."""
    from cicloassist.midia import cache as C

    raiz = tmp_path / "cache"
    monkeypatch.setenv("CICLOASSIST_CACHE", str(raiz))
    chave = "b" * 64
    C.Midia(chave).pasta.mkdir(parents=True, exist_ok=True)

    arquivo = tmp_path / "DJI_0315.mov"
    arquivo.write_bytes(b"a" * 100)
    _projeto_do_premiere(monkeypatch, tmp_path, [arquivo])

    def nunca(*a, **k):  # pragma: no cover — é o ponto do teste
        raise AssertionError("o Premiere não pode encostar no Media Composer")

    monkeypatch.setattr(R, "_carregar_no_monitor", nunca)
    monkeypatch.setattr(P, "arquivo_da_chave", lambda c: str(arquivo))
    monkeypatch.setattr(P, "carregar_no_source",
                        lambda ref="", arq="", tc="": {"ok": True, "nome": "DJI_0315.mov"})

    d = post("/busca/carregar", {"chave": chave, "nle": "premiere"})
    assert d["ok"] and d["onde"] == "Source" and d["midia"] == "DJI_0315.mov"


def test_no_premiere_o_item_do_recorte_ganha_do_arquivo(monkeypatch, tmp_path):
    """⭐ O id do SUBCLIPE, e não o arquivo do master: carregar o master de um resultado
    que é subclipe põe no Source uma diária inteira no lugar do trecho clicado."""
    from cicloassist.midia import cache as C

    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    chave = "c" * 64
    C.Midia(chave).pasta.mkdir(parents=True, exist_ok=True)

    vistos = {}
    monkeypatch.setattr(P, "carregar_no_source",
                        lambda ref="", arq="", tc="": vistos.update(ref=ref, arq=arq) or {"ok": True})
    monkeypatch.setattr(P, "arquivo_da_chave",
                        lambda c: pytest.fail("não devia procurar o arquivo"))

    post("/busca/carregar", {"chave": chave, "mob": "000fa", "nle": "premiere"})
    assert vistos == {"ref": "000fa", "arq": ""}


def test_record_no_premiere_e_recusado_com_a_frase(monkeypatch, tmp_path):
    """⚠️ O Premiere não tem Record: o equivalente é a sequência, e pôr clipe nela é
    ESCRITA. Virar um Source calado faria o editor achar que clicou errado."""
    from cicloassist.midia import cache as C

    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    chave = "d" * 64
    C.Midia(chave).pasta.mkdir(parents=True, exist_ok=True)

    d = post("/busca/carregar", {"chave": chave, "onde": "Record", "nle": "premiere"})
    assert not d["ok"] and "portão" in d["erro"]


def test_o_host_carrega_sem_importar_nada():
    """⛔ `openFilePath` IMPORTA o arquivo no projeto do editor — isso é escrita, e este
    gesto de propósito não passa pelo portão."""
    jsx = P.__file__.replace("__init__.py", "host.jsx")
    texto = _sem_comentarios(open(jsx, encoding="utf-8").read())
    assert "openProjectItem" in texto
    assert "openFilePath" not in texto


# ── o índice de recortes do Premiere ─────────────────────────────────────────

META = ("<Column.Intrinsic.SubclipStart>01:00:10:00</Column.Intrinsic.SubclipStart>"
        "<Column.Intrinsic.SubclipDuration>00:00:05:00</Column.Intrinsic.SubclipDuration>")


def _item(**extra):
    d = {"nome": "C04_P01-T002", "id": "000fa", "bin": "CENAS/C04", "especie": "clipe",
         "arquivo": "", "metadados": META, "fps": 24.0, "timelines": ["CENA 04 v3"]}
    d.update(extra)
    return d


def test_a_janela_do_subclipe_sai_do_subclipstart(monkeypatch, tmp_path):
    """⛔⛔ `getInPoint()` devolve o MASTER INTEIRO (banco): quem o usar como janela põe
    todo subclipe cobrindo a diária, e aí toda fala "cabe" em todo recorte."""
    arquivo = tmp_path / "C04.mov"
    arquivo.write_bytes(b"a" * 10)
    monkeypatch.setattr(I, "sondar", lambda a: {"tc": "01:00:00:00", "fps": "24000/1001"})
    monkeypatch.setattr(I, "chave_conhecida", lambda a: "e" * 64)

    r = REC._do_item(_item(arquivo=str(arquivo)))
    assert r is not None and r.especie == "subclipe" and r.mob_id == "000fa"
    assert r.timelines == ["CENA 04 v3"]
    janela = r.janelas["e" * 64]
    assert round(janela.inicio_s, 3) == 10.0 and round(janela.fim_s, 3) == 15.0


def test_sem_taxa_o_recorte_entra_sem_janela(monkeypatch, tmp_path):
    """⛔ Chutar 25 fps erraria todo material 23,976 — este acervo inteiro. Melhor um
    subclipe sem janela que uma janela errada, que desloca calada."""
    arquivo = tmp_path / "C04.mov"
    arquivo.write_bytes(b"a" * 10)
    monkeypatch.setattr(I, "sondar", lambda a: {"tc": "01:00:00:00", "fps": ""})
    monkeypatch.setattr(I, "chave_conhecida", lambda a: "e" * 64)

    r = REC._do_item(_item(arquivo=str(arquivo), fps=None))
    assert r is not None and r.janelas == {}


def test_arquivo_que_nao_esta_no_cache_nao_vira_recorte(monkeypatch, tmp_path):
    """⭐ A chave JÁ CONHECIDA: quem nunca foi analisado não está no cache, logo não muda
    busca nenhuma — e medir a impressão de 150 recortes custaria minutos."""
    arquivo = tmp_path / "C04.mov"
    arquivo.write_bytes(b"a" * 10)
    monkeypatch.setattr(I, "sondar", lambda a: {"tc": "", "fps": "24"})
    monkeypatch.setattr(I, "chave_conhecida", lambda a: "")
    assert REC._do_item(_item(arquivo=str(arquivo))) is None


def test_o_indice_do_premiere_nunca_espera_e_faz_um_build_so(monkeypatch):
    """⛔⛔ A mesma trava do Avid, pelo mesmo motivo medido: a aba aquece e a busca pede ao
    mesmo tempo. Lá isso virou quatro builds em um minuto e uma busca que nunca voltou."""
    import threading
    import time

    entrou = threading.Event()
    solte = threading.Event()
    builds = []

    def devagar():
        builds.append(1)
        entrou.set()
        solte.wait(5)
        return {"x": []}

    monkeypatch.setattr(REC, "_montar", devagar)
    assert REC.indice("D:/p/X.prproj") == {}, "a busca NUNCA espera"
    entrou.wait(2)
    assert REC.indice("D:/p/X.prproj") == {}, "e não começa um segundo build"
    solte.set()
    for _ in range(50):
        if REC.esta_pronto("D:/p/X.prproj"):
            break
        time.sleep(0.05)
    assert REC.indice("D:/p/X.prproj") == {"x": []}
    assert len(builds) == 1
    assert not REC._construindo, "a vaga do build ficou pendurada"


def test_o_indice_falhando_nao_derruba_a_busca(monkeypatch):
    """⚠️ Ordem que falha vira "responde por master" — nunca uma tela parada."""
    def estoura():
        raise RuntimeError("o painel fechou no meio")

    monkeypatch.setattr(REC, "_montar", estoura)
    assert REC.indice("D:/p/X.prproj", esperar=2) == {}
    assert not REC._construindo


def test_a_fachada_manda_o_premiere_para_o_indice_certo(monkeypatch, tmp_path):
    """⛔⛔ Indexar as `.avb` do Avid para responder uma busca do Premiere era o mesmo
    defeito de raiz — e ele nem acharia bin nenhuma, porque `.prproj` não é pasta."""
    from cicloassist.avid import subclipes as S

    _projeto_do_premiere(monkeypatch, tmp_path)
    monkeypatch.setattr(S, "indice", lambda *a, **k: pytest.fail("as bins do Avid, não"))
    monkeypatch.setattr(REC, "indice", lambda projeto, **k: {"ok": [projeto]})
    assert nle.recortes_do_projeto(nle="premiere") == {
        "ok": [str(tmp_path / "CICLO ASSIST TESTE.prproj")]}


def test_a_taxa_do_premiere_vem_da_sequencia_aberta(monkeypatch):
    """⭐ O Premiere não tem taxa de PROJETO: quem tem é a sequência (`timebase` em ticks).
    ⛔ Sem sequência aberta, `None` — e a fala fica só com o mm:ss."""
    from fractions import Fraction

    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", lambda *a, **k: {
        "caminho": "D:/p/X.prproj",
        "fps": {"num": "254016000000", "den": "10594584000"}})
    assert nle.taxa_do_projeto("premiere") == Fraction(24000, 1001)

    monkeypatch.setattr(PT, "chamar", lambda *a, **k: {"caminho": "D:/p/X.prproj"})
    assert nle.taxa_do_projeto("premiere") is None
