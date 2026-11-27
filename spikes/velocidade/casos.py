"""B32 VELOCIDADE — os casos de velocidade, uma vez só, para a verdade (Premiere), a ida (MC) e a volta (Premiere).

Sequência 23,976 a partir de 01:00:00:00. Cada caso é UM clipe A/V (imagem na V1, som na A1/A2) de 96 quadros da
sequência (4 s), com 24 de vazio entre eles; a entrada na mídia é o quadro 48 DELA (na taxa dela). A velocidade vai pelo
QE `setSpeed` (mantém a duração e anda a fonte) — o gesto do Premiere. Mídia do laboratório: a imagem diz o quadro
(`lab.ler.ler_faixas`), o som diz o tom de cada canal e tem uma claque por segundo da mídia (`verdade.json`).
"""
from __future__ import annotations

from pathlib import Path

FAMILIA = Path(__file__).resolve().parents[4]
LAB = FAMILIA / "laboratorio-de-midia"
B30 = LAB / "saida" / "base" / "B30_EDL"
B02 = LAB / "saida" / "base" / "B02_TAXAS"
PASTA = FAMILIA.parent / "MIDIAS DE TESTES" / "9 SAIDAS DOS APPS" / "_CICLO ASSIST" / "2026-11-26 VELOCIDADE B32"
SEQ = "B32 VELOCIDADE"
TICKS = 254016000000
TPF = TICKS * 1001 // 24000            # 23,976
DUR, VAO, ENTRADA = 96, 24, 48         # quadros da sequência; a entrada em quadros da MÍDIA

A = (B30 / "B30_A_MOV-PRORES.mov", 24000 / 1001, (300, 400))
CENA = (B30 / "B30_CENA_AÇÃO_MOV-PRORES.mov", 24000 / 1001, (5400, 5500))
M24 = (B02 / "B02_24_MOV-PRORES.mov", 24.0, (300, 400))
M25 = (B02 / "B02_25_MOV-PRORES.mov", 25.0, (300, 400))
M2997 = (B02 / "B02_2997ND_MOV-PRORES.mov", 30000 / 1001, (300, 400))
M50 = (B02 / "B02_50_MOV-PRORES.mov", 50.0, (300, 400))

# (rótulo, mídia, velocidade (negativa = reverso), manter o tom)
CASOS = [
    ("50%", A, 0.5, True),
    ("200%", A, 2.0, True),
    ("75%", A, 0.75, True),
    ("125%", A, 1.25, True),
    ("25p 100%", M25, 1.0, True),
    ("25p 50%", M25, 0.5, True),
    ("24p 100%", M24, 1.0, True),
    ("29,97 100%", M2997, 1.0, True),
    ("29,97 200%", M2997, 2.0, True),
    ("reverso", A, -1.0, True),
    ("50% tom cai", CENA, 0.5, False),
    ("50p 100%", M50, 1.0, True),
]


def gravacao(i: int) -> int:
    """O quadro da sequência (desde o início) onde o caso `i` começa."""
    return i * (DUR + VAO)


def entrada_ticks(fps: float) -> int:
    return round(ENTRADA * TICKS / fps)
