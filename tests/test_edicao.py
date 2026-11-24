"""Editar a timeline do editor: extrair, inserir, abrir gap — e a prova de que só isso mudou.

Conferido no Media Composer em 2026-09-13 (`spikes/extrair_da_timeline.py`,
`spikes/inserir_na_timeline.py`, na `TL EDITADA` com 4.277 objetos): o editor viu a cópia na
Record, com efeitos, dissolves, group clips e volume intactos. Aqui é a estrutura, com
sequências sintéticas — cada teste trava uma regra que, quebrada, não levanta erro nenhum:
só produz uma timeline dessincronizada ou uma prova que aprova o que não devia.
"""

from __future__ import annotations

import avb
import pytest

from cicloassist.avid import edicao as E
from cicloassist.avid import timeline as T

FPS = 24
MOB = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.00000000.00000000.00000000.00000001"
IMAGEM = (("picture", 1),)
AMBOS = (("picture", 1), ("sound", 1))


def sequencia():
    """Imagem: A(0-100) B(100-150) C(150-230). Som: A(0-100) vazio(100-150) C(150-230)."""
    f = avb.file.AVBFile()
    seq = T.montar_timeline(f, "TL", [
        T.Entrada(mob_id=MOB, duracao=100, trilhas=AMBOS, start_time=1000),
        T.Entrada(mob_id=MOB, duracao=50, trilhas=IMAGEM, start_time=2000),
        T.Entrada(mob_id=MOB, duracao=80, trilhas=AMBOS, start_time=3000),
    ], FPS)
    return f, seq


def trilha(seq, kind):
    n = next(i for i, t in enumerate(seq.tracks) if getattr(t.component, "media_kind", "") == kind
             and type(t.component).__name__ == "Sequence")
    return [(type(c).__name__, c.length, getattr(c, "start_time", None))
            for c in E.segmentos(seq)[n] if c.length]


def sem_vazios_colados(seq) -> bool:
    for lista in E.segmentos(seq):
        nomes = [type(c).__name__ for c in lista if c.length]
        if any(a == b == "Filler" for a, b in zip(nomes, nomes[1:])):
            return False
    return True


# ── extrair ──────────────────────────────────────────────────────────────────

def test_extrair_tira_o_trecho_de_todas_as_trilhas_e_mantem_a_sincronia():
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    E.extrair(copia, 100, 150)
    assert trilha(copia, "picture") == [("SourceClip", 100, 1000), ("SourceClip", 80, 3000)]
    # ⭐ O som perde o VAZIO do mesmo trecho: é o que mantém o C colado na própria imagem.
    assert trilha(copia, "sound") == [("SourceClip", 100, 1000), ("SourceClip", 80, 3000)]
    assert copia.length == 180
    assert E.conferir_fidelidade(orig, copia, (100, 150), (100, 100)) == []


def test_extrair_apara_as_pontas_que_o_trecho_morde():
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    E.extrair(copia, 90, 110)
    # A perde 10 da cauda; B perde 10 da cabeça — e o in dele anda 10 frames no take.
    assert trilha(copia, "picture")[:2] == [("SourceClip", 90, 1000), ("SourceClip", 40, 2010)]
    assert trilha(copia, "sound")[:2] == [("SourceClip", 90, 1000), ("Filler", 40, None)]
    assert E.conferir_fidelidade(orig, copia, (90, 110), (90, 90)) == []


def test_extrair_no_meio_de_um_clipe_e_recusado_sem_mexer_em_nada():
    """⛔ Recusa ANTES de mexer: uma extração pela metade dessincroniza a timeline."""
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    antes = E.impressao(copia, {})
    with pytest.raises(E.EdicaoRecusada, match="MEIO de um clipe"):
        E.extrair(copia, 110, 120)
    assert E.impressao(copia, {}) == antes


def test_a_copia_tem_identidade_propria_e_a_original_nao_muda():
    f, orig = sequencia()
    antes = E.impressao(orig, {})
    copia = E.copiar_sequencia(f, orig, "TL v2")
    E.extrair(copia, 100, 150)
    assert str(copia.mob_id) != str(orig.mob_id)
    assert E.impressao(orig, {}) == antes


# ── a prova ──────────────────────────────────────────────────────────────────

def test_a_prova_reprova_mudanca_fora_do_trecho():
    """⭐⭐ A garantia do caminho B: a prova tem de REPROVAR, não só aprovar."""
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    E.extrair(copia, 100, 150)
    n = next(i for i, t in enumerate(copia.tracks)
             if getattr(t.component, "media_kind", "") == "picture")
    clipe_depois = [c for c in E.segmentos(copia)[n] if type(c).__name__ == "SourceClip"][-1]
    clipe_depois.start_time += 1
    problemas = E.conferir_fidelidade(orig, copia, (100, 150), (100, 100))
    assert any("DEPOIS" in p for p in problemas)


def test_a_prova_reprova_clipe_alterado_colado_na_emenda_do_lado_de_antes():
    """⛔⛔ A primeira versão da prova tolerava "um segmento diferente de cada lado" e
    aprovava isto. A folga é só para VAZIO estendido ou colado — nunca para clipe."""
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    E.extrair(copia, 150, 230)
    n = next(i for i, t in enumerate(copia.tracks)
             if getattr(t.component, "media_kind", "") == "picture")
    colado = [c for c in E.segmentos(copia)[n] if type(c).__name__ == "SourceClip"][-1]
    colado.start_time += 1            # o B, que termina exatamente onde o trecho começa
    problemas = E.conferir_fidelidade(orig, copia, (150, 230), (150, 150))
    assert any("ANTES" in p for p in problemas)


def test_a_prova_reprova_comprimento_errado():
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    E.extrair(copia, 100, 150)
    assert E.conferir_fidelidade(orig, copia, (100, 140), (100, 100))


def test_a_impressao_segura_o_objeto_no_memo():
    """⛔ MEDIDO na TL EDITADA: com `id()` sozinho de chave, o pyavb solta e relê objetos, um
    novo herda o `id` de um coletado, e a prova acusou TODOS os mobs da bin como mudados."""
    _, seq = sequencia()
    memo = {}
    E.impressao(seq, memo)
    assert all(isinstance(v, tuple) and v[0] is not None for v in memo.values())


# ── inserir e abrir gap ──────────────────────────────────────────────────────

def test_inserir_num_corte_empurra_tudo_e_poe_vazio_onde_nao_ha_midia():
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    clipe = f.create.SourceClip(FPS, "picture")
    clipe.mob_id = avb.mobid.MobID(MOB)
    clipe.track_id, clipe.start_time, clipe.length = 1, 5000, 48
    n = next(i for i, t in enumerate(copia.tracks)
             if getattr(t.component, "media_kind", "") == "picture")
    E.inserir(copia, 100, 48, {n: clipe})
    assert trilha(copia, "picture")[1] == ("SourceClip", 48, 5000)
    # ⭐ No som, o vazio que já começava ali CRESCE — nada de vazio novo colado nele.
    assert trilha(copia, "sound")[1] == ("Filler", 98, None)
    assert copia.length == 278
    assert sem_vazios_colados(copia)
    assert E.conferir_fidelidade(orig, copia, (100, 100), (100, 148)) == []


def test_abrir_gap_estende_vazio_existente_e_nao_cola_vazios():
    """⚠️ MEDIDO no gap da TL EDITADA: um take terminando onde começa um vazio criava um
    vazio NOVO colado no que já existia."""
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    E.inserir(copia, 150, 48)
    assert trilha(copia, "picture")[2] == ("Filler", 48, None)
    assert trilha(copia, "sound")[1] == ("Filler", 98, None)
    assert sem_vazios_colados(copia)
    assert E.conferir_fidelidade(orig, copia, (150, 150), (150, 198)) == []


def test_inserir_no_meio_de_um_clipe_e_recusado_sem_mexer():
    f, orig = sequencia()
    copia = E.copiar_sequencia(f, orig, "TL v2")
    antes = E.impressao(copia, {})
    with pytest.raises(E.EdicaoRecusada, match="MEIO de um clipe"):
        E.inserir(copia, 120, 48)
    assert E.impressao(copia, {}) == antes


def test_o_que_entra_tem_de_ter_o_tamanho_do_espaco():
    f, orig = sequencia()
    clipe = f.create.SourceClip(FPS, "picture")
    clipe.length = 40
    with pytest.raises(E.EdicaoRecusada, match="40 frames"):
        E.inserir(orig, 100, 48, {9: clipe})
