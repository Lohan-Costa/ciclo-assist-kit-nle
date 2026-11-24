"""Os atalhos de prompt: o módulo, as rotas e o menu ☰ do compositor.

Plano: `docs/plano/2026-09-14-menu-do-compositor.md`. O `conftest` isola
`CICLOASSIST_DADOS` no tmp, então nada aqui toca a pasta real do editor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import sys

import pytest

from cicloassist.servico import atalhos
from cicloassist.servico import rotas
from cicloassist.servico.http import Pedido

PAINEL = Path(__file__).resolve().parents[1] / "cicloassist" / "painel"


# ── o módulo ─────────────────────────────────────────────────────────────────


def test_ida_e_volta_pelo_disco():
    atalhos.salvar("Separe as falas da cena 7.", apelido="Separar falas")
    lista = atalhos.ler()
    assert [(a["apelido"], a["texto"]) for a in lista] == [
        ("Separar falas", "Separe as falas da cena 7.")]
    assert json.loads(atalhos.arquivo().read_text(encoding="utf-8"))["atalhos"][0]["id"]


def test_lista_cheia_recusa_com_o_numero_e_nao_descarta_nenhum():
    for n in range(atalhos.TETO_DE_ATALHOS):
        atalhos.salvar(f"pedido {n}")
    with pytest.raises(atalhos.AtalhoRecusado, match=str(atalhos.TETO_DE_ATALHOS)):
        atalhos.salvar("um a mais")
    assert len(atalhos.ler()) == atalhos.TETO_DE_ATALHOS
    assert atalhos.ler()[0]["texto"] == "pedido 0"


def test_texto_vazio_ou_grande_demais_e_recusado():
    with pytest.raises(atalhos.AtalhoRecusado):
        atalhos.salvar("   ")
    with pytest.raises(atalhos.AtalhoRecusado, match=str(atalhos.TETO_DO_TEXTO)):
        atalhos.salvar("x" * (atalhos.TETO_DO_TEXTO + 1))
    assert atalhos.ler() == []


def test_apelido_vazio_nasce_da_primeira_linha_numa_linha_so():
    atalhos.salvar("Sincronize a diária D02\npelo Sincronizar, no método híbrido, e monte tudo")
    apelido = atalhos.ler()[0]["apelido"]
    assert "\n" not in apelido
    assert apelido.startswith("Sincronize a diária D02 pelo")
    assert len(apelido) <= atalhos.TETO_DO_APELIDO


def test_apelido_repetido_ganha_sufixo():
    atalhos.salvar("um", apelido="Falas")
    atalhos.salvar("dois", apelido="falas")
    assert [a["apelido"] for a in atalhos.ler()] == ["Falas", "falas (2)"]


@pytest.mark.parametrize("conteudo", ['"texto solto"', "[1, 2, 3]", '{"atalhos": [{"apelido": "x"}]}',
                                      "{nem é json"])
def test_arquivo_ilegivel_vira_lista_vazia(conteudo):
    atalhos.arquivo().parent.mkdir(parents=True, exist_ok=True)
    atalhos.arquivo().write_text(conteudo, encoding="utf-8")
    assert atalhos.ler() == []


@pytest.mark.skipif(sys.platform != "win32", reason="caminho D:\\ de propósito; no Mac o Path não separa por barra invertida")
def test_o_atalho_nao_guarda_caminho_nenhum():
    atalhos.salvar("leia isto", arquivo_de_origem=r"D:\PROJETOS\segredo\prompt-falas.md", de="arquivo")
    assert atalhos.ler()[0]["arquivo"] == "prompt-falas.md"
    assert "PROJETOS" not in atalhos.arquivo().read_text(encoding="utf-8")


def test_tirar_tira_so_aquele():
    atalhos.salvar("um", apelido="A")
    atalhos.salvar("dois", apelido="B")
    alvo = atalhos.ler()[0]["id"]
    assert [a["apelido"] for a in atalhos.tirar(alvo)] == ["B"]
    assert [a["apelido"] for a in atalhos.tirar("nao-existe")] == ["B"]


def test_editado_a_mao_continua_valendo():
    """O arquivo é do editor: lista crua e campos faltando não derrubam nada."""
    atalhos.arquivo().parent.mkdir(parents=True, exist_ok=True)
    atalhos.arquivo().write_text('[{"texto": "pedido escrito à mão"}]', encoding="utf-8")
    [a] = atalhos.ler()
    assert a["apelido"] == "pedido escrito à mão" and a["id"]


# ── as rotas ─────────────────────────────────────────────────────────────────


def _post(caminho: str, corpo: dict) -> Pedido:
    return Pedido("POST", caminho, {}, json.dumps(corpo).encode("utf-8"))


def test_as_rotas_devolvem_a_lista_relida():
    r = rotas.rota_salvar_atalho(_post("/atalhos/salvar", {"texto": "Separe as falas", "apelido": "Falas"}))
    d = json.loads(r.corpo)
    assert r.status == 200 and d["ok"] and d["atalhos"][0]["apelido"] == "Falas"
    assert d["teto"] == atalhos.TETO_DE_ATALHOS

    d = json.loads(rotas.rota_atalhos(Pedido("GET", "/atalhos", {})).corpo)
    assert [a["apelido"] for a in d["atalhos"]] == ["Falas"]

    d = json.loads(rotas.rota_tirar_atalho(_post("/atalhos/tirar", {"id": d["atalhos"][0]["id"]})).corpo)
    assert d["atalhos"] == []


def test_a_rota_recusa_vazio_com_400_e_a_frase():
    r = rotas.rota_salvar_atalho(_post("/atalhos/salvar", {"texto": ""}))
    d = json.loads(r.corpo)
    assert r.status == 400 and d["ok"] is False and d["erro"] and d["atalhos"] == []


def test_o_painel_confere_as_rotas_na_partida():
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    for r in ("atalhos", "atalhos/salvar", "atalhos/tirar"):
        assert f'"{r}"' in js.split("function conferirOServico")[0]


# ── a interface ──────────────────────────────────────────────────────────────


def _html() -> str:
    return (PAINEL / "index.html").read_text(encoding="utf-8")


def test_o_botao_fica_entre_os_anexos_e_a_caixa_de_texto():
    html = _html()
    form = html[html.index('<form class="compositor"'):html.index("</form>")]
    assert form.index('id="anexos"') < form.index('id="abrirMenu"') < form.index('id="entrada"')
    botao = re.search(r'<button[^>]*id="abrirMenu"[^>]*>', form).group(0)
    for attr in ('type="button"', 'aria-haspopup="menu"', 'aria-expanded="false"', 'aria-controls="menuPop"'):
        assert attr in botao


def test_o_menu_fica_fora_do_form():
    """Um form com um campo de texto submete no Enter: o apelido enviaria a pergunta."""
    html = _html()
    assert html.index("</form>") < html.index('id="menuPop"')


def test_todo_botao_do_compositor_que_nao_envia_e_type_button():
    html = _html()
    form = html[html.index('<form class="compositor"'):html.index("</form>")]
    for b in re.findall(r"<button[^>]*>", form):
        assert 'type="button"' in b or 'id="enviar"' in b, b


def test_o_menu_abre_para_cima_e_por_cima():
    css = (PAINEL / "painel.css").read_text(encoding="utf-8")
    regra = re.search(r"\.menu-pop \{[^}]*\}", css).group(0)
    assert "position: fixed" in regra
    assert int(re.search(r"z-index:\s*(\d+)", regra).group(1)) > 3
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    pos = js[js.index("function posicionarOMenu"):js.index("function textoParaSalvar")]
    assert "style.bottom" in pos and "style.top" not in pos


def test_o_atalho_preenche_e_nao_envia():
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    usar = js[js.index("function usarAtalho"):js.index("function posicionarOMenu")]
    assert "entrada.value" in usar
    assert "perguntar(" not in usar and "enviarAgora(" not in usar


def test_salvar_nao_leva_anexo():
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    salvar = js[js.index("function salvarAForma"):]
    salvar = salvar[:salvar.index("\n}\n")]
    for proibido in ("referencias", "mob_id", "caminho"):
        assert proibido not in salvar


def test_o_menu_fecha_com_escape_e_com_clique_fora():
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert re.search(r'e\.key === "Escape" && !menuPop\.hidden', js)
    assert "menuPop.contains(e.target)" in js


def test_o_painel_nao_usa_dialogo_nativo():
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    codigo = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    codigo = re.sub(r"(?m)^\s*//.*$", "", codigo)
    assert not re.search(r"(?<![\w.])(window\.)?(confirm|alert|prompt)\(", codigo)
