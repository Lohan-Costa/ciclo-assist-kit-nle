"""O que o editor arrastou chega ao modelo como material, e não como pergunta.

⛔⛔ MEDIDO em 2026-09-15, nas sessões do editor com o Haiku separando as falas da C07: com
o roteiro e os dez subclipes anexados, o modelo pedia para arrastar o roteiro de novo e
perguntava em que bin estavam os subclipes. O editor leu isso como o modelo ignorando o
anexo, e acertar numa rodada e errar na outra como inconsistência do modelo. Eram quatro
defeitos nossos, e cada teste daqui trava um:

1. o MobID do arrasto e o da bin são os mesmos 64 hex, grafados diferente;
2. o arrasto não diz a bin, e toda ferramenta de mídia pede a bin;
3. o primeiro turno da visita apagava a autorização do roteiro recém-arrastado;
4. `listar_itens_da_bin`, sem tipos, respondia "0 itens" numa bin de subclipes.
"""

from __future__ import annotations

from pathlib import Path

import avb
import pytest

from cicloassist.avid import bins as B
from cicloassist.avid import take as TK
from cicloassist.avid import timeline as T
from cicloassist.mcp.ferramentas import avid as FA
from cicloassist.motor import sessao as S
from cicloassist.servico import arrastados as A
from cicloassist.servico import presenca as P
from cicloassist.servico import rotas as R

FPS = 23.976
FORA = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.00000000.00000000.00000000.000000ff"

# As duas grafias, copiadas da C07 real: a do arquivo e a que o arrasto do Avid entrega.
DO_ARQUIVO = ("urn:smpte:umid:060a2b34.01010105.01010f20.13000000."
              "a9b99375.81c0448d.bc9639bd.e525ea79")
DO_ARRASTO = "060a2b340101010501010f2013-000000-a9b9937581c0448d-bc9639bde525-ea79"


def _grafia_do_arrasto(mob_id: str) -> str:
    h = TK.hex_do_mob(mob_id)
    return f"{h[:26]}-{h[26:32]}-{h[32:48]}-{h[48:60]}-{h[60:]}"


@pytest.fixture
def projeto(tmp_path):
    """`CENAS/C07.avb` com o TAKE à vista, e uma bin de falas com o MESMO take oculto."""
    cenas = tmp_path / "CENAS"
    cenas.mkdir()
    c07 = cenas / "C07.avb"
    with avb.open() as f:
        master = T.montar_timeline(
            f, "MASTER", [T.Entrada(mob_id=FORA, duracao=500, trilhas=(("picture", 1),))], FPS)
        take = T.montar_timeline(
            f, "C07_P01-T001", [T.Entrada(mob_id=str(master.mob_id), duracao=400,
                                          trilhas=(("picture", 1),))], FPS)
        f.write(str(c07))
    with avb.open(str(c07)) as f:
        take_id = next(str(i.mob.mob_id) for i in f.content.items
                       if i.mob.name == "C07_P01-T001")

    falas = tmp_path / "FALAS"
    falas.mkdir()
    T.escrever_bin(falas / "C07 FALAS.avb",
                   [("C07_FALA01", [T.Entrada(mob_id=take_id, duracao=48,
                                              trilhas=(("picture", 1),))])],
                   FPS, base=c07)
    return tmp_path, take_id


# ── 1. as duas grafias do MobID ──────────────────────────────────────────────

def test_as_duas_grafias_sao_o_mesmo_mob():
    assert TK.hex_do_mob(DO_ARQUIVO) == TK.hex_do_mob(DO_ARRASTO)
    assert len(TK.hex_do_mob(DO_ARRASTO)) == 64


def test_o_take_arrastado_e_achado_pelo_mobid_do_arrasto(projeto):
    """⛔ A regressão: "não achei '060a2b34…' em C07.avb", com o clipe lá dentro."""
    raiz, take_id = projeto
    with avb.open(str(raiz / "CENAS" / "C07.avb")) as f:
        achado = TK._achar(list(f.content.mobs), _grafia_do_arrasto(take_id))
        assert achado is not None and achado.name == "C07_P01-T001"


def test_a_bin_sem_extensao_e_a_mesma_bin(projeto):
    """O modelo escreve `CENAS/C07`, como o editor fala — e era a bin certa."""
    raiz, _ = projeto
    # O take do teste é uma composição, e o `resolver` a recusa por ESPÉCIE — depois de
    # ter aberto a bin e achado o item, que é o que interessa aqui.
    with pytest.raises(TK.TakeErro, match="C07_P01-T001"):
        TK.resolver(str(raiz / "CENAS" / "C07"), "C07_P01-T001")
    with pytest.raises(TK.TakeErro, match="não achei a bin"):
        TK.resolver(str(raiz / "CENAS" / "C08"), "C07_P01-T001")
    assert TK.com_extensao_de_bin("C07 v1.2") == "C07 v1.2.avb"
    assert TK.com_extensao_de_bin("CENAS/C07.AVB") == "CENAS/C07.AVB"


# ── 2. a bin de cada item arrastado ──────────────────────────────────────────

def test_a_bin_do_arrasto_ignora_o_fecho_oculto(projeto):
    """⛔ A bin de falas leva o take OCULTO: contado, a resposta viraria "diga qual"."""
    raiz, take_id = projeto
    onde = B.bins_dos_mobs(raiz, [_grafia_do_arrasto(take_id)])
    assert onde == {TK.hex_do_mob(take_id): [str(Path("CENAS") / "C07.avb")]}


def test_o_preambulo_diz_a_bin_e_que_aquilo_ja_e_o_material(projeto, monkeypatch):
    raiz, take_id = projeto
    monkeypatch.setattr(R._escopo, "projeto_aberto", lambda *a, **k: str(raiz))
    texto = R._preambulo_do_arrasto([
        {"tipo": "avid", "especie": "subclip", "nome": "C07_P01-T001",
         "mob_id": _grafia_do_arrasto(take_id)},
    ])
    assert f"da bin {Path('CENAS') / 'C07.avb'}" in texto
    assert "Não procure em outras bins" in texto
    # ⛔ Numa conversa do Avid, nada de ferramenta do Premiere no preâmbulo.
    assert "resolver_take" in texto and "resolver_item_do_premiere" not in texto


def test_sem_media_composer_o_preambulo_sai_sem_a_bin(monkeypatch):
    monkeypatch.setattr(R._escopo, "projeto_aberto", lambda *a, **k: R._escopo.SEM_PROJETO)
    texto = R._preambulo_do_arrasto([
        {"tipo": "avid", "especie": "subclip", "nome": "X", "mob_id": DO_ARRASTO},
    ])
    assert "subclip X do Avid" in texto


# ── 3. o anexo sobrevive à visita nova ───────────────────────────────────────

def test_o_primeiro_turno_da_visita_nao_desautoriza_o_anexo(tmp_path, monkeypatch):
    """⛔ MEDIDO: o preâmbulo autorizava, a visita nova esquecia, e `ler_arquivo` pedia
    para arrastar o roteiro que estava anexado."""
    roteiro = tmp_path / "roteiro.txt"
    roteiro.write_text("PERSONAGEM-F\nOi.", encoding="utf-8")
    velho = tmp_path / "de ontem.txt"
    velho.write_text("x", encoding="utf-8")
    monkeypatch.setattr(S, "recomecar", lambda caminho: True)
    monkeypatch.setattr(R._sessao, "recomecar", lambda caminho: True)
    P.esquecer()
    R._visita_do_fio.clear()
    A.esquecer_tudo()
    try:
        A.autorizar(str(velho))
        A.autorizar(str(roteiro))
        P.bater()
        assert R._conversa_desta_visita([str(roteiro)]) is True
        assert A.autorizado(str(roteiro))
        # O que era de antes continua indo embora com a visita.
        assert not A.autorizado(str(velho))
    finally:
        P.esquecer()
        R._visita_do_fio.clear()
        A.esquecer_tudo()


# ── 4. a bin de subclipes não volta vazia ────────────────────────────────────

def test_listar_sem_tipos_inclui_subclipes():
    assert "subclips" in FA.TIPOS_PADRAO
    assert "masterClips" in FA.TIPOS_PADRAO


def test_o_item_do_premiere_chega_com_a_bin_e_o_id(monkeypatch):
    """P5 do Premiere: o drop lê a SELEÇÃO, e ela já traz a bin — nada de adivinhar."""
    monkeypatch.setattr(R._nle, "_atual", "premiere")
    texto = R._preambulo_do_arrasto([
        {"tipo": "premiere", "especie": "merged", "nome": "C07_P02-T002",
         "bin": "CENAS/C07", "id": "000f4a1"},
    ])
    assert "merged C07_P02-T002, da bin CENAS/C07 do Premiere (id 000f4a1)" in texto
    assert "resolver_item_do_premiere" in texto and "resolver_take" not in texto
    # ⛔ MEDIDO com o Qwen: sem isto ele respondia "você não anexou nada" e usava o anexo.
    assert "você RECEBEU" in texto and "nunca diga que não veio anexo" in texto


def test_o_preambulo_segue_o_editor_DESTA_pergunta_e_nao_o_do_turno_anterior(monkeypatch):
    """⚠️ O preâmbulo é montado antes de o turno declarar o editor. Sem receber qual é, a
    primeira pergunta no Premiere depois de uma no Avid saía com as ferramentas do Avid."""
    monkeypatch.setattr(R._nle, "_atual", "avid")
    item = [{"tipo": "premiere", "especie": "clipe", "nome": "A001.mp4", "bin": "D02", "id": "9"}]
    assert "resolver_item_do_premiere" in R._preambulo_do_arrasto(item, "premiere")
    assert "resolver_take" not in R._preambulo_do_arrasto(item, "premiere")
