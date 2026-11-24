"""A regra dos nomes frouxos — o que o Avid quebra e o que precisamos casar.

Casos construídos a partir de material real. Rodar:

    PYTHONPATH=motor .venv/bin/python tests/test_nomes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))

from avid.mcapi import McApiError, mob_id_para_api, mob_id_valido  # noqa: E402
from media.matcher import _has_significant_token_overlap, _normalize_name  # noqa: E402
from media.matcher_masters import _chave_uid  # noqa: E402

# (nome no AAF, nome no disco, deve casar por nome EXATO normalizado)
NOMES = [
    # ── sufixos que o Avid empilha ──────────────────────────────────────────
    ("A001_03170334_C004.new.01", "A001_03170334_C004.mp4", True),
    ("04 Dark Drone.wav.new.01", "04 Dark Drone.wav", True),
    # `.Exported` é sufixo do Avid e `.02`/`.01` são contadores de versão: os três
    # caem, e a sequence exportada casa com o arquivo de origem. É o desejado.
    ("SEQ01_CORTE.02.Exported.01", "SEQ01_CORTE.mov", True),
    ("clipe.sync", "clipe.mxf", True),
    ("clipe.cds.03", "clipe.mov", True),
    ("clipe.copy", "clipe.mp4", True),
    ("clipe.sub", "clipe.mp4", True),
    ("clipe.grp", "clipe.mp4", True),

    # ── separadores trocados: o caso do nome por timecode ───────────────────
    # O Avid grava `17;25;16` e o AAF traz `17_25_16`. Sem normalizar, a mídia
    # entra offline — foi o que deixou 29 trilhas de fora numa medição.
    ("17_25_16 Cordas.wav", "17;25;16 Cordas.wav", True),
    ("00_12_12 Piano e Cordas.wav", "00;12;12 Piano e Cordas.wav", True),
    ("09_36_23 Cordas Trompa_02.wav", "09;36;23 Cordas Trompa_02.wav", True),
    ("CAM_A", "CAM-A", True),
    ("CAM.A", "CAM A", True),

    # ── caixa e acento ──────────────────────────────────────────────────────
    ("a001_03170334_c004", "A001_03170334_C004.mp4", True),
    ("Câmera_Principal", "Camera Principal", True),
    ("COLISÃO ACIDENTE", "COLISAO ACIDENTE", True),

    # ── o que NÃO pode casar ────────────────────────────────────────────────
    ("A004_03170917_C003", "A002_03170813_C004.mp4", False),
    ("23_19_13 Cordas Trompa Oboé.wav", "09;36;23 Cordas Trompa_02.wav", False),
    ("24_23_20 CB.wav", "24_23_21 CB.wav", False),
]

# (nome A, nome B, tokens longos em comum?) — o guard contra falso positivo
OVERLAP = [
    ("a004 03170917 c003", "a002 03170813 c004", False),
    ("a004 03170917 c003", "a004 03170917 c003", True),
    ("cam a", "cam a", True),
    ("cam a exterior", "exterior cam a", True),
]

# (valor de entrada, hex esperado) — a normalização de UMID
UIDS = [
    ("urn:smpte:umid:060a2b34.01010105.01010f10.13000000."
     "1a8edcf3.1260a306.7860d011.e5e7034e",
     "060a2b340101010501010f10130000001a8edcf31260a3067860d011e5e7034e"),
    ("0x060A2B340101010501010F10130000001A8EDCF31260A3067860D011E5E7034E",
     "060a2b340101010501010f10130000001a8edcf31260a3067860d011e5e7034e"),
    ("060a2b340101010501010f1013-000000-1a8edcf31260a306-7860d011-e5e7034e",
     "060a2b340101010501010f10130000001a8edcf31260a3067860d011e5e7034e"),
    ("", ""),
    ("não é um umid", ""),
]

# (valor, é MobID válido?) — o mesmo MobID chega com AGRUPAMENTO DE HÍFEN DIFERENTE
# conforme a superfície que o entrega, e por isso a validação conta hexadecimais em vez
# de casar a pontuação. Um validador que crave os hifens recusa MobID legítimo, e o
# sintoma é o pior possível: "o clipe que arrastei não é reconhecido", sem nada errado
# com o clipe. Ver `avid/mcapi.py` e o caso do ESION no banco de NLEs.
_HEX = "060a2b340101010501010f10130000001a8edcf31260a3067860d011e5e7034e"
MOBIDS = [
    # agrupamento da API / `ffprobe`  (26-6-16-8-8)
    ("060a2b340101010501010f1013-000000-1a8edcf31260a306-7860d011-e5e7034e", True),
    # agrupamento do payload de ARRASTO (26-6-16-12-4) — o que o ESION exige
    ("060a2b340101010501010f1013-000000-1a8edcf31260a306-7860d011e5e7-034e", True),
    (_HEX, True),                       # sem pontuação nenhuma
    ("0x" + _HEX.upper(), True),         # o prefixo do `ffprobe`, e em maiúsculas
    (f"  {_HEX}  ", True),               # espaço em volta
    (_HEX[:-1], False),                  # 63 dígitos
    (_HEX + "a", False),                 # 65 dígitos
    ("", False),
    (None, False),
    # ⚠️ Não basta CONTAR hexadecimais: estes têm 64 e não são MobID.
    ("g0" * 32, False),
    ("urn:smpte:umid:" + _HEX, False),   # a forma URN não é a que a API entrega
]

# Toda forma "de fora" → a ÚNICA que o `GetBinFromMob` acha (26-6-16-12-4); as outras devolvem None calado (B011).
_PERGUNTA = "060a2b340101010501010f1013-000000-1a8edcf31260a306-7860d011e5e7-034e"
PERGUNTAS = [
    (_PERGUNTA, _PERGUNTA),
    ("060a2b340101010501010f1013-000000-1a8edcf31260a306-7860d011-e5e7034e", _PERGUNTA),  # o do `ffprobe`
    (_HEX, _PERGUNTA),
    ("0x" + _HEX.upper(), _PERGUNTA),
    (_PERGUNTA.upper(), _PERGUNTA),
    # ⚠️ o `e` de `smpte` e o `d` de `umid` passariam no filtro: o prefixo sai antes
    ("urn:smpte:umid:060a2b34.01010105.01010f10.13000000.1a8edcf3.1260a306.7860d011.e5e7034e", _PERGUNTA),
    (_HEX[:-1], None),                   # 63 dígitos: erro, nunca uma pergunta torta
]


def main() -> int:
    falhas = []

    print("── normalização de nome ─────────────────────────────────────")
    for aaf, disco, deve in NOMES:
        na, nd = _normalize_name(aaf), _normalize_name(disco)
        casou = na == nd
        ok = casou == deve
        print(f"{'  ok  ' if ok else ' FALHA'} {aaf[:34]:34} {'==' if casou else '!='} {disco[:30]}")
        if not ok:
            falhas.append(f"{aaf!r} x {disco!r}: {na!r} vs {nd!r}")

    print("\n── guard de tokens (anti falso positivo) ────────────────────")
    for a, b, deve in OVERLAP:
        tem = _has_significant_token_overlap(a, b)
        ok = tem == deve
        print(f"{'  ok  ' if ok else ' FALHA'} {a[:26]:26} x {b[:26]:26} -> {tem}")
        if not ok:
            falhas.append(f"overlap {a!r} x {b!r}: esperava {deve}")

    print("\n── normalização de UMID ─────────────────────────────────────")
    for entrada, esperado in UIDS:
        obtido = _chave_uid(entrada)
        ok = obtido == esperado
        rotulo = (entrada[:44] + "…") if len(entrada) > 44 else (entrada or "(vazio)")
        print(f"{'  ok  ' if ok else ' FALHA'} {rotulo}")
        if not ok:
            falhas.append(f"uid {entrada!r}: {obtido!r} != {esperado!r}")

    print("\n── MobID: conta hexadecimais, NÃO casa hífen ────────────────")
    for entrada, deve in MOBIDS:
        obtido = mob_id_valido(entrada)
        ok = obtido == deve
        rotulo = (str(entrada)[:44] + "…") if entrada and len(str(entrada)) > 44 else repr(entrada)
        print(f"{'  ok  ' if ok else ' FALHA'} {rotulo:48} -> {obtido}")
        if not ok:
            falhas.append(f"mob_id_valido({entrada!r}): {obtido} != {deve}")

    print("\n── MobID: a pergunta ao GetBinFromMob sai em 26-6-16-12-4 ───")
    for entrada, deve in PERGUNTAS:
        try:
            obtido = mob_id_para_api(entrada)
        except McApiError:
            obtido = None
        ok = obtido == deve
        print(f"{'  ok  ' if ok else ' FALHA'} {entrada[:44] + '…':48} -> {obtido}")
        if not ok:
            falhas.append(f"mob_id_para_api({entrada!r}): {obtido} != {deve}")

    total = len(NOMES) + len(OVERLAP) + len(UIDS) + len(MOBIDS) + len(PERGUNTAS)
    print(f"\n{total - len(falhas)}/{total} casos")
    for f in falhas:
        print("  !", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
