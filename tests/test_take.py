"""A camada de tradução, na parte que não precisa de Avid nem de mídia.

A travessia do `.avb` é exercitada pelo spike (`spikes/fase5_take.py`, contra material
real). Aqui ficam as regras puras — claquete, taxa, ordenação de canais — que são onde os
erros silenciosos moram.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from cicloassist.avid import take as T


# ── a claquete ───────────────────────────────────────────────────────────────

def test_le_a_claquete_do_som():
    """O formato do técnico de som: separado por espaço."""
    assert T.ler_claquete("PRODUCAO-A - 05-04 C7 P2-T004") == {
        "cena": "C7", "plano": "P2", "take": "T004",
    }


def test_le_o_nome_do_subclipe_com_underscore():
    """⚠️⚠️ A REGRESSÃO QUE ESTE TESTE TRAVA: `_` é caractere de PALAVRA, então `\\b`
    não dispara entre `C07` e `_P02`. Com `\\b` o padrão casava no nome do som (separado
    por espaço) e falhava no nome do subclipe — 9 de 10 takes passavam e o décimo caía em
    "não reconhecido" sem explicação nenhuma."""
    assert T.ler_claquete("C07_P02-T001.1") == {
        "cena": "C07", "plano": "P02", "take": "T001",
    }
    assert T.ler_claquete("C07_P01-T001")["plano"] == "P01"


def test_le_minusculo_e_outros_separadores():
    assert T.ler_claquete("c4 p1-t002")["cena"] == "C4"


def test_nome_de_camera_nao_vira_claquete():
    """`a003_03170838_C002` tem um `C002` — mas não tem plano nem take. Ler cena daí
    inventaria procedência que não existe."""
    assert T.ler_claquete("a003_03170838_C002")["cena"] is None


def test_nome_nao_reconhecido_nao_e_erro():
    """Design de 25/08, Camada 1: cada produção nomeia diferente, e nome fora da
    convenção é um take a marcar à mão, não uma falha."""
    assert T.ler_claquete("qualquer coisa") == {"cena": None, "plano": None, "take": None}


# ── taxa de quadros ──────────────────────────────────────────────────────────

def test_taxa_vira_fracao_exata():
    assert T.fracao_da_taxa(23.976) == Fraction(24000, 1001)
    assert T.fracao_da_taxa(29.97) == Fraction(30000, 1001)
    assert T.fracao_da_taxa(25) == Fraction(25, 1)


def test_fracao_nao_e_o_decimal_convertido():
    """⚠️ `Fraction(23.976)` dá 3374389/140741 — correto e inútil. Não é a taxa que o
    material usa, e o erro só aparece depois de milhares de frames."""
    assert T.fracao_da_taxa(23.976) != Fraction(23.976).limit_denominator(1000000)


def test_segundos_saem_como_float_serializavel():
    """A conta fica racional até o fim; o valor que atravessa a ponte é float. Uma
    Fraction aqui derruba o `json.dumps` do resultado da ferramenta."""
    s = T.para_segundos(5430, Fraction(24000, 1001))
    assert isinstance(s, float)
    assert abs(s - 226.476) < 0.001


# ── OP-Atom: um arquivo por track ────────────────────────────────────────────

def test_video_vem_antes_dos_canais_e_os_canais_em_ordem():
    """Os `_A01.._A05` são os canais 1 a 5. Entregá-los embaralhados faria a consumidora
    misturar quem fala com quem."""
    bagunca = [Path(x) for x in ("CLIP_A03.mxf", "CLIP.mxf", "CLIP_A01.mxf", "CLIP_A02.mxf")]
    assert [p.name for p in T.ordenar_por_track(bagunca)] == [
        "CLIP.mxf", "CLIP_A01.mxf", "CLIP_A02.mxf", "CLIP_A03.mxf",
    ]


def test_canais_de_dois_digitos_ordenam_por_numero_nao_por_texto():
    """`_A10` depois de `_A9`, não antes. Ordenação de texto poria `A10` entre `A1` e
    `A2`, e o canal 10 viraria o segundo."""
    bagunca = [Path(f"CLIP_A{n:02d}.mxf") for n in (10, 2, 1)]
    assert [p.name for p in T.ordenar_por_track(bagunca)] == [
        "CLIP_A01.mxf", "CLIP_A02.mxf", "CLIP_A10.mxf",
    ]


def test_sufixo_de_audio_reconhece_so_o_padrao_do_opatom():
    assert T.SUFIXO_DE_AUDIO.search("CLIP_A01")
    assert not T.SUFIXO_DE_AUDIO.search("CLIP_A1")       # o Avid escreve dois dígitos
    assert not T.SUFIXO_DE_AUDIO.search("a003_03170859_C005")
