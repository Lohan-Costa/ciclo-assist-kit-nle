"""O Source no ponto da fala, e a decupagem na coluna "Descrição" — no Premiere (2026-09-22).

Os dois nasceram de pedidos do editor e de medições no Premiere 23.2
(`spikes/o_source_e_a_descricao.py`, `spikes/o_source_no_tc.py`, banco
`plugins/premiere-cep/api-extendscript.md`):

- ⛔⛔ o `scrubTo` quer TEMPO DESDE O INÍCIO DO CLIPE, não o TC dele — e não limita: 3604 s
  foi aceito num clipe de 10 s. Os testes travam a conta e o teto;
- ⛔⛔ a Descrição nunca é escrita por cima do texto do editor: só vazia, ou com o texto
  que NÓS gravamos da última vez.

⚠️ O que NÃO cobrem: o Premiere de verdade (o painel é simulado aqui).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import identidade as I
from cicloassist.nle import premiere as P
from cicloassist.nle.premiere import ponte as PT
from cicloassist.servico import rotas as R
from cicloassist.servico.http import Pedido


@pytest.fixture(autouse=True)
def limpo(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    P.esquecer()
    I.esquecer()
    yield
    P.esquecer()


def _sonda(monkeypatch, **sonda):
    monkeypatch.setattr(I, "sondar", lambda a: dict(sonda))


# ── o Source no ponto ────────────────────────────────────────────────────────

@pytest.mark.parametrize("fps, segundos, esperado", [
    ("25", 4.0, "00:00:04:00"),
    ("25", 4.48, "00:00:04:12"),
    # ⭐ Medido: a 23,976 os quadros vão na base 24 — 00:00:04:00 é 4,004 s.
    ("24000/1001", 4.004, "00:00:04:00"),
    # ⭐ 01:00:00:00 a 23,976 são 3603,6 s REAIS (o `startTime` medido) — e em float a
    #   conta dava 86399,99… quadros, um a menos.
    ("24000/1001", 3603.6, "01:00:00:00"),
    ("24000/1001", 3601.0, "00:59:57:09"),
])
def test_o_tc_do_source_e_tempo_desde_o_inicio(monkeypatch, fps, segundos, esperado):
    _sonda(monkeypatch, fps=fps, duracao_s=7200.0, tc="01:00:00:00")
    # ⛔⛔ O TC do ARQUIVO (01:00:00:00) não entra na conta: medido, `scrubTo('01:00:04:00')`
    #    vai para 3604 s.
    assert P.tc_no_source("x.mp4", segundos) == esperado


def test_o_premiere_nao_limita_entao_limitamos(monkeypatch):
    """⛔ 3604 s foi ACEITO num clipe de 10 s, sem erro. O teto é o último quadro."""
    _sonda(monkeypatch, fps="25", duracao_s=10.0, quadros=250)
    assert P.tc_no_source("x.mp4", 3604) == "00:00:09:24"
    assert P.tc_no_source("x.mp4", -5) == "00:00:00:00"


def test_som_puro_vai_pelo_segundo_inteiro(monkeypatch):
    """⚠️ O campo de quadro de um clipe de áudio no Source não foi medido; o segundo não
    depende dele."""
    _sonda(monkeypatch, tipo="audio", duracao_s=146.1)
    assert P.tc_no_source("x.wav", 65.9) == "00:01:05:00"


def _painel_vivo(monkeypatch, tmp_path):
    chave = "b" * 64
    C.Midia(chave).pasta.mkdir(parents=True, exist_ok=True)
    arquivo = tmp_path / "A001.mp4"
    arquivo.write_bytes(b"a" * 10)
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(P, "arquivo_da_chave", lambda c: str(arquivo))
    _sonda(monkeypatch, fps="25", duracao_s=60.0)
    return chave


def _carregar(corpo):
    r = R.ROTAS[("POST", "/busca/carregar")][0](
        Pedido("POST", "/busca/carregar", {}, json.dumps(corpo).encode("utf-8")))
    return json.loads(r.corpo.decode("utf-8"))


def test_a_fala_clicada_leva_a_agulha_e_diz_onde_parou(monkeypatch, tmp_path):
    chave = _painel_vivo(monkeypatch, tmp_path)
    pedidos = []
    monkeypatch.setattr(P, "carregar_no_source", lambda ref="", arq="", tc="": pedidos.append(
        (ref, tc)) or {"ok": True, "nome": "A001.mp4", "posicionado": True, "posicao_s": 12.48})

    d = _carregar({"chave": chave, "nle": "premiere", "segundos": 12.5})
    assert pedidos == [("", "00:00:12:12")]
    # ⭐ O que a agulha FEZ, lido de volta — não o que foi pedido.
    assert d["posicionado"] and d["posicao_s"] == 12.48 and d["tc_pedido"] == "00:00:12:12"


def test_no_subclipe_do_premiere_abre_sem_posicionar(monkeypatch, tmp_path):
    """⚠️ No subclipe, o zero do `scrubTo` (o dele ou o do master?) não foi medido: errar
    ali poria a agulha no lugar errado sem erro nenhum. Abre, e a tela diz."""
    chave = _painel_vivo(monkeypatch, tmp_path)
    pedidos = []
    monkeypatch.setattr(P, "carregar_no_source", lambda ref="", arq="", tc="": pedidos.append(
        (ref, tc)) or {"ok": True, "nome": "SUB"})
    d = _carregar({"chave": chave, "mob": "000fa", "nle": "premiere", "segundos": 12.5})
    assert pedidos == [("000fa", "")] and d["sem_posicao"] == "subclipe"


def test_o_duplo_clique_sem_fala_nao_posiciona(monkeypatch, tmp_path):
    chave = _painel_vivo(monkeypatch, tmp_path)
    pedidos = []
    monkeypatch.setattr(P, "carregar_no_source", lambda ref="", arq="", tc="": pedidos.append(
        tc) or {"ok": True})
    d = _carregar({"chave": chave, "nle": "premiere"})
    assert pedidos == [""] and "tc_pedido" not in d


# ── a Descrição ──────────────────────────────────────────────────────────────

def _entrada(chave, descricao, nome="A001.mp4", origem="premiere"):
    m = C.Midia(chave, origem=origem, rotulo={"nome": nome})
    m.pasta  # noqa: B018
    if descricao:
        m.anotar({"trecho": nome, "escopo": "midia", "descricao": descricao,
                  "confianca": "inferido", "fonte": "visual"})
    return m


def test_a_descricao_vai_para_a_coluna_e_o_que_gravamos_fica_anotado(monkeypatch):
    m = _entrada("a" * 64, "close de Personagem F na praia")
    # ⛔ Nota de TAKE não é descrição do clipe inteiro.
    m.anotar({"trecho": "C07_P03-T001", "descricao": "um pedaço", "inicio_frames": 10})
    sem = _entrada("b" * 64, "")
    clipes = {m.chave: {"arquivo_premiere": "D:/x/A001.mp4"},
              sem.chave: {"arquivo_premiere": "D:/x/B.mp4"},
              "c" * 64: {"arquivo_premiere": "D:/x/NOVO.mp4", "provisoria": True}}
    planos = []

    def chamar(funcao, plano, **k):
        assert funcao == "cicloDescrever"
        planos.append(plano)
        return {"escritos": ["D:/x/A001.mp4"], "do_editor": [], "iguais": 0}

    monkeypatch.setattr(PT, "chamar", chamar)
    r = P.sincronizar_descricoes(clipes)

    assert planos == [[{"arquivo": "D:/x/A001.mp4", "esperado": "",
                        "novo": "close de Personagem F na praia"}]]
    assert r["escritos"] == 1
    assert m.manifesto()[P.CAMPO_DA_DESCRICAO] == "close de Personagem F na praia"


def test_texto_do_editor_nao_vira_o_esperado(monkeypatch):
    """⛔⛔ O host recusou (o campo tem texto dele): nada é anotado, e a próxima rodada
    continua mandando o `esperado` antigo — o texto dele nunca é sobrescrito."""
    m = _entrada("a" * 64, "decupagem nova")
    m.marcar_no_manifesto(P.CAMPO_DA_DESCRICAO, "decupagem velha")
    planos = []
    monkeypatch.setattr(PT, "chamar", lambda f, plano, **k: planos.append(plano) or {
        "escritos": [], "do_editor": ["D:/x/A001.mp4"], "iguais": 0})
    r = P.sincronizar_descricoes({m.chave: {"arquivo_premiere": "D:/x/A001.mp4"}})
    assert planos[0][0]["esperado"] == "decupagem velha"
    assert r["do_editor"] == 1
    assert m.manifesto()[P.CAMPO_DA_DESCRICAO] == "decupagem velha"


def test_o_host_faz_compare_and_set_no_campo_medido():
    """⛔ O campo é o MEDIDO (`Column.PropertyText.Description`), e o host só escreve com o
    campo vazio ou igual ao esperado. Sem comentários: o texto deles cita as regras."""
    import re
    host = re.sub(r"/\*.*?\*/|(?<!:)//[^\n]*", "", P.HOST_JSX.read_text(encoding="utf-8"),
                  flags=re.S)
    corpo = host[host.index("function cicloDescrever"):]
    corpo = corpo[:corpo.index("\nfunction ") if "\nfunction " in corpo else len(corpo)]
    assert '"Column.PropertyText.Description"' in corpo
    assert 'atual !== "" && atual !== p.esperado' in corpo
    assert "setProjectMetadata(x.serialize(), [CAMPO])" in corpo
    assert "SubclipStart" in corpo, "subclipe é do editor"


# ── o duplo clique leva ao PONTO do achado ───────────────────────────────────

def test_o_duplo_clique_vai_ao_quadro_do_achado_e_nao_onde_o_editor_parou(monkeypatch, tmp_path):
    """⭐ Pedido do editor (2026-09-22): voltando a um clipe pela busca, o Source ficava
    onde ele tinha parado — o Premiere lembra a posição por clipe (medido)."""
    chave = _painel_vivo(monkeypatch, tmp_path)
    pedidos = []
    monkeypatch.setattr(P, "carregar_no_source", lambda ref="", arq="", tc="": pedidos.append(
        tc) or {"ok": True, "posicionado": True, "posicao_s": 0.0})
    _carregar({"chave": chave, "nle": "premiere", "quadro": 0})
    _carregar({"chave": chave, "nle": "premiere", "quadro": 112})   # 4,48 s a 25 fps
    assert pedidos == ["00:00:00:00", "00:00:04:12"]


def test_o_painel_manda_o_quadro_e_cala_o_sucesso():
    js = (Path(R.__file__).parent.parent / "painel" / "painel.js").read_text(encoding="utf-8")
    assert "function abrirNoPonto" in js and "a.inicio_frames : 0" in js
    # ⭐ O "no Source" verde-água saiu (pedido do editor): sucesso é calado.
    assert "if (!avisos.length) { recado.remove(); return; }" in js
