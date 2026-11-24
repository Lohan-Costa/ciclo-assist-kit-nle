"""A timeline autorada — e o corte em L/J, que é onde imagem e som deixam de andar juntas.

⭐ **O que estes testes protegem é o alinhamento.** Uma sequência com as trilhas
escorregadas abre no Avid sem erro nenhum: o editor só descobre assistindo, e o sintoma
— "o áudio está fora de sincronia" — não aponta para cá. Por isso as somas por trilha são
conferidas componente a componente, e não pela duração total do mob.

O caminho até o arquivo é coberto pelo `spikes/fase5c_avb.py`, que exige o Media Composer
aberto. Aqui é a estrutura, que não exige nada.
"""

from __future__ import annotations

import avb
import pytest

from cicloassist.avid import timeline as T

#: Um take de câmera + som: uma trilha de imagem e duas de som.
TRILHAS = (("picture", 1), ("sound", 1), ("sound", 2))

MOB = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.00000000.00000000.00000000.00000001"


def entrada(duracao, start=0, **kw):
    return T.Entrada(mob_id=MOB, duracao=duracao, trilhas=TRILHAS, start_time=start, **kw)


def montar(entradas, fps=23.976):
    """Monta num arquivo em memória e devolve o mob de composição."""
    f = avb.file.AVBFile()
    return T.montar_timeline(f, "TESTE", entradas, fps)


def trilha(comp, media_kind, indice=1):
    """Os componentes de uma trilha, sem o filler de cabeça nem o de rabo."""
    for track in comp.tracks:
        seq = track.component
        if getattr(seq, "media_kind", None) == media_kind and track.index == indice:
            if not isinstance(seq, avb.components.Sequence):
                continue
            return list(seq.components)[1:-1]
    raise AssertionError(f"trilha {media_kind}{indice} não existe")


def fontes(comp, media_kind, indice=1):
    return [c for c in trilha(comp, media_kind, indice)
            if isinstance(c, avb.components.SourceClip)]


# ── o corte seco, que não pode ter mudado ────────────────────────────────────

def test_sem_ljs_imagem_e_som_andam_juntos():
    comp = montar([entrada(100), entrada(200), entrada(150)])
    imagem = [c.length for c in fontes(comp, "picture")]
    som = [c.length for c in fontes(comp, "sound")]
    assert imagem == [100, 200, 150]
    assert som == imagem


def test_o_in_dentro_do_take_vale_para_as_duas_trilhas():
    comp = montar([entrada(100, start=500)])
    assert fontes(comp, "picture")[0].start_time == 500
    assert fontes(comp, "sound")[0].start_time == 500


# ── corte em J: o som entra antes da imagem ──────────────────────────────────

def test_J_alonga_o_som_do_plano_que_entra_e_encurta_o_anterior():
    """O corte 2 entra com o som 14 frames antes da imagem.

    ⇒ o plano 1 fica com 14 frames de som a menos, e o plano 2 com 14 a mais — a imagem
    dos dois não muda um frame.
    """
    comp = montar([
        entrada(100, duracao_som=100 - 14),            # perdeu o fim do som
        entrada(200, start=500, duracao_som=200 + 14, start_som=500 - 14),
    ])
    assert [c.length for c in fontes(comp, "picture")] == [100, 200]
    assert [c.length for c in fontes(comp, "sound")] == [86, 214]
    # ⭐ E o som do plano 2 vem de 14 frames ANTES no material dele: é a fala que puxa o
    #   corte, não um pedaço de silêncio esticado.
    assert fontes(comp, "sound")[1].start_time == 486
    assert fontes(comp, "picture")[1].start_time == 500


def test_L_segura_o_som_do_plano_que_sai():
    comp = montar([
        entrada(100, duracao_som=100 + 9),             # o som dele continua mais um pouco
        entrada(200, start=500, duracao_som=200 - 9, start_som=500 + 9),
    ])
    assert [c.length for c in fontes(comp, "picture")] == [100, 200]
    assert [c.length for c in fontes(comp, "sound")] == [109, 191]
    assert fontes(comp, "sound")[1].start_time == 509


def test_a_soma_do_som_fecha_a_da_imagem():
    """⛔ O teste que pega o escorregamento. Se as somas divergirem, o filler de rabo tapa
    a diferença com silêncio e a sequência abre no Avid parecendo certa."""
    comp = montar([
        entrada(300, duracao_som=300 - 12),
        entrada(200, start=500, duracao_som=200 + 12 + 8, start_som=488),
        entrada(150, start=500, duracao_som=150 - 8, start_som=508),
    ])
    imagem = sum(c.length for c in fontes(comp, "picture"))
    som = sum(c.length for c in fontes(comp, "sound"))
    assert imagem == som == 650
    assert comp.length == 650


def test_as_duas_trilhas_de_som_recebem_o_mesmo_desencontro():
    """O take tem duas trilhas de som; o L/J vale para as duas, ou uma delas dessincroniza."""
    comp = montar([
        entrada(100, duracao_som=86),
        entrada(200, start=500, duracao_som=214, start_som=486),
    ])
    for i in (1, 2):
        assert [c.length for c in fontes(comp, "sound", i)] == [86, 214]
        assert fontes(comp, "sound", i)[1].start_time == 486


# ── o take sem som direto, que é o caso de borda da bin C07 ──────────────────

def test_take_sem_som_ganha_filler_do_tamanho_do_SOM_e_nao_da_imagem():
    """⚠️⚠️ O buraco tem o tamanho da trilha dele.

    `C07_P02-T001.1` não tem som direto. Se o filler que o substitui usasse a duração da
    IMAGEM, ele reintroduziria o escorregamento pela porta dos fundos — justamente no take
    que já é o caso de borda do acervo.
    """
    so_imagem = T.Entrada(mob_id=MOB, duracao=100, trilhas=(("picture", 1),),
                          duracao_som=100 - 14)
    comp = montar([
        so_imagem,
        entrada(200, start=500, duracao_som=214, start_som=486),
    ])
    componentes = trilha(comp, "sound")
    assert isinstance(componentes[0], avb.components.Filler)
    assert componentes[0].length == 86       # não 100
    assert sum(c.length for c in componentes) == 300


# ── o que não pode acontecer em silêncio ─────────────────────────────────────

def test_timeline_sem_entrada_nenhuma_e_recusada():
    with pytest.raises(ValueError):
        montar([])
