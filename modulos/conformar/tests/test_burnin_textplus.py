"""Burn-in do Premiere ("Metadata & Timecode Burn-in") → Text+ do Resolve (2026-10-08).

Rodar:

    .venv/bin/python tests/test_burnin_textplus.py        (Windows: .venv-win/Scripts/python)

O critério forte foi o da imagem, no Resolve 21.1 (Mac): o Text+ gerado mostra o TC da timeline
quadro a quadro (01:00:41:16 / 01:00:52:02 / 01:00:54:03 nos quadros 1000 / 1250 / 1299) e, sobre o
PRODB, cai no lugar do burn-in da referência. Aqui fica o que não precisa do Resolve: o formato
do `CompositionBA` (a forma comprimida, sem a qual o título sai preto), a conta da posição e do
tamanho e o clipe "Fusion Title" no DRT.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp.writer import build_drt  # noqa: E402
from titulos import textplus  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def main() -> int:
    print("── o CompositionBA ──")
    cab = textplus._CABECALHO.format(fim=119, w=2880, h=1620, fps="24")
    tools = textplus.tools_tc(size=0.05, centro=(0.9, 0.95), inicio=86400, fps=24, fim=119,
                              quadro=(2880, 1620), fundo_opacidade=0.4)
    c2, t2 = textplus.ler_composicao(textplus.composicao_ba(cab, tools))
    ok("ida e volta: o cabeçalho e o bloco Tools voltam iguais", (c2, t2), (cab, tools))
    ok("forma comprimida (sem ela o Resolve importa e o título sai preto)", "Compressed = true" in c2, True)
    ok("o nó de saída é MediaOut (não Saver)", "MediaOut1 = MediaOut {" in t2, True)
    ok("o TC vem do modificador TimeCode, com o início em quadros",
       ('StyledText = Input { SourceOp = "TimeCode1", Source = "Time", }' in t2,
        "StartOffset = Input { Value = 86400, }" in t2), (True, True))
    ok("a caixa de fundo preta com a opacidade do Premiere",
       all(x in t2 for x in ("Enabled4 = Input { Value = 1, }", "Opacity4 = Input { Value = 0.4, }",
                             "Red4 = Input { Value = 0, }")), True)

    print("── a conta (o burn-in do PRODB, quadro 2880×1620) ──")
    tam, (cx, cy) = textplus.geometria((0.8168055415153503, 0.0756789967417717), 17.0, 100.0, (2880, 1620))
    # medido na referência: dígitos de 65 px, caixa dos dígitos x 2360–2828, y 41–105 (de cima); o
    # Text+ desenha 1 px acima da conta, então a conta mira 74
    ok("Size do Text+ ≈ 0,0524 (dígitos de 65 px)", round(tam, 4), 0.0524)
    ok("centro X na caixa dos dígitos medida (2594 px ± 2)", abs(cx * 2880 - 2594) <= 2, True)
    ok("centro Y: 74 px de cima ± 1 (o Text+ sai 1 px acima: 73, o da referência)", abs((1 - cy) * 1620 - 74) <= 1, True)

    print("── o clipe no DRT ──")
    seg = {"timeline_tc_in": "00:00:10:00", "timeline_tc_out": "00:00:15:00", "duration_frames": 120,
           "source_start_frames": 0, "source_fps": 24.0, "clip_name": "Graphic", "track": 1,
           "is_gap": False, "is_transition": False, "is_effect": True, "is_audio": False,
           "speed_ratio": 1.0, "conform_ratio": 1.0, "relative_speed": 1.0, "motion_class": "native",
           "disabled": False, "media_ref": None,
           "effects": [{"name": "Metadata & Timecode Burn-in (Text+)", "category": "burnin", "reproducible": True,
                        "params": {"size": 17.0, "opacidade": 0.4,
                                   "linhas": [{"linha": 1, "metadado": 4, "posicao": [0.8168, 0.0757], "size": 100.0}]}}]}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.drt")
        res = build_drt([seg], [], p, timeline_name="x", timeline_fps=24.0, timeline_start_frames=86400,
                        timeline_size=(2880, 1620))
        with zipfile.ZipFile(p) as z:
            txt = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if "SeqContainer" in n)
    clipe = re.search(r"<Sm2TiVideoClip\b(?:(?!</Sm2TiVideoClip>).)*?<PrettyType>Fusion Title</PrettyType>.*?</Sm2TiVideoClip>",
                      txt, re.S)
    ok("um Text+ (Fusion Title) entrou", (res.get("burnins"), bool(clipe)), (1, True))
    if clipe:
        b = clipe.group(0)
        ok("no trecho do burn-in: Start = 01:00:10:00 (86400 + 240) e a duração",
           (re.search(r"<Start>(\d+)</Start>", b).group(1), re.search(r"<Duration>(\d+)</Duration>", b).group(1)),
           ("86640", "120"))
        _c, t = textplus.ler_composicao(re.search(r"<CompositionBA>([0-9a-f]+)</CompositionBA>", b).group(1))
        ok("o TC começa no Start do clipe (o TC da timeline no 1º quadro)", "StartOffset = Input { Value = 86640, }" in t, True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
