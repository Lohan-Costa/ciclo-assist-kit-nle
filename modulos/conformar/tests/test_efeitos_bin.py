"""Efeitos de enquadramento lidos da BIN (3D Warp, Resize, PIP, Pan&Scan, FrameFlex) → DRT.

Rodar:

    .venv-win/Scripts/python tests/test_efeitos_bin.py

O De Lá Pra Cá lê a bin (nunca AAF/ExportFile). Os parâmetros saem dela com os nomes do AAF
(o uuid é o AUID do ParameterDef; banco `protocolos/avb/dados/efeitos-na-bin.json`), e a conta
é a medida no RELINKER (`RELINKER/docs/effect-translation.md`). Aqui se confere:

1. as regras, com efeitos de mentira (sem disco): FrameFlex parado, Pan&Scan, identidade,
   FrameFlex animado (não se escreve) e o valor do PRIMEIRO QUADRO de um parâmetro animado;
2. as bins reais dos casos E04 (PIP/Resize/3D Warp) e E06 (FrameFlex), da pasta de testes
   (`DLPC_AMOSTRAS`), de ponta a ponta até o `EffectFiltersBA` do DRT. Sem a pasta: PULADO.
"""

from __future__ import annotations

import os
import re
import struct
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb.parameter_uuids import PARAMETER_UUIDS  # noqa: E402

from avb_bin import efeitos as E  # noqa: E402

from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
AMOSTRAS = Path(raiz_das_amostras())
CASOS = AMOSTRAS / "03 CASOS" / "EFEITOS"
UUID = {nome: u for u, nome in PARAMETER_UUIDS.items()}


def efeito(eid: str, **valores) -> SimpleNamespace:
    """Um TrackEffect de mentira: `nome=valor` ou `nome=[(quadro, valor), …]` (animado)."""
    itens = []
    for nome, v in valores.items():
        pd = {"uuid": UUID[nome]}
        if isinstance(v, list):
            pontos = [SimpleNamespace(property_data={"offset": [q, 1], "value": x}) for q, x in v]
            pd["value"] = 58.3                    # o `value` solto NÃO é o do início (medido)
            pd["control_track"] = SimpleNamespace(property_data={"control_points": pontos})
        else:
            pd["value"] = v
        itens.append(SimpleNamespace(property_data=pd))
    return SimpleNamespace(effect_id=eid, property_data={"param_list": itens})


def doubles(efb_hex: str) -> list:
    """Os doubles do `EffectFiltersBA` do transform (escrito sem compressão, 0x80)."""
    corpo = bytes.fromhex(efb_hex)[9:]
    return [round(struct.unpack("<d", corpo[i + 1:i + 9])[0], 4)
            for i in range(len(corpo) - 9) if corpo[i] == 0x11]


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 60 else f"{repr(obtido)[:57]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    def r3(d):
        return {k: round(v, 3) for k, v in d.items() if isinstance(v, float)}

    print("── 1. as regras, sem disco ──")
    e, modo, _ = E.enquadramento(efeito("EFF2_SBLEND", DVE_POS_ENABLED_U=1.0, DVE_POS_X_U=40.0, DVE_POS_Y_U=32.0,
                                        DVE_SCALE_ENABLED_U=1.0, DVE_SCALE_X_U=120.0, DVE_SCALE_Y_U=120.0))
    ok("3D Warp: posição em milésimos, escala em fator", r3(e["params"]),
       {"pos_x": 40.0, "pos_y": 32.0, "scale_x": 1.2, "scale_y": 1.2})
    ok("…reproduzível, sem modo de reformat", (e["reproducible"], modo), (True, None))
    e, _, _ = E.enquadramento(efeito("EFF2_BLEND_PAN_SCAN", AFX_POS_X_U=150.0, AFX_POS_Y_U=0.0))
    ok("⭐ Pan&Scan: o sinal da posição inverte (move a janela; RELINKER 150 → −0,15)",
       e["params"]["pos_x"], -150.0)
    e, modo, _ = E.enquadramento(efeito(
        "INT_EFF_SPATIAL_ADAPTER", AFX_SPATIAL_REFORMAT=1, AFX_SPATIAL_FRAMING_WID=50.0,
        AFX_SPATIAL_FRAMING_HEI=50.0, AFX_SPATIAL_FRAMING_POSX=15.0, AFX_SPATIAL_FRAMING_POSY=0.0))
    ok("⭐ FrameFlex Size 50 / Position 15 = zoom 2×, −0,30 (o C04 medido no RELINKER)",
       r3(e["params"]), {"scale_x": 2.0, "scale_y": 2.0, "pos_x": -300.0, "pos_y": -0.0})
    ok("…e o modo de reformat volta junto", modo, "pillarbox")
    e, modo, _ = E.enquadramento(efeito("INT_EFF_SPATIAL_ADAPTER", AFX_SPATIAL_REFORMAT=-1))
    ok("FrameFlex só de reformat (sem o escalar WID): nenhum efeito, só o modo", (e, modo),
       (None, "stretch"))
    e, modo, _ = E.enquadramento(efeito("INT_EFF_SPATIAL_ADAPTER", AFX_SPATIAL_REFORMAT=3,
                                        AFX_SPATIAL_FRAMING_WID=100.0, AFX_SPATIAL_FRAMING_HEI=100.0))
    ok("FrameFlex em 100 % e posição 0 = identidade: nada a escrever", (e, modo), (None, "keep_size"))
    e, _, av = E.enquadramento(efeito(
        "INT_EFF_SPATIAL_ADAPTER", AFX_SPATIAL_REFORMAT=3, AFX_SPATIAL_FRAMING_WID=[(46, 100.0)],
        AFX_SPATIAL_FRAMING_HEI=[(0, 56.2), (46, 100.0)]))
    ok("⛔ FrameFlex ANIMADO: não se traduz (zoom distorcido); fica na Carta",
       (e["reproducible"], sorted(e["params"]["keyframes_avid"])),
       (False, ["AFX_SPATIAL_FRAMING_HEI", "AFX_SPATIAL_FRAMING_WID"]))
    ok("…e o aviso diz para ajustar no Resolve", "ajuste no Resolve" in av[0], True)
    e, _, av = E.enquadramento(efeito("EFF2_SBLEND", DVE_POS_ENABLED_U=1.0, DVE_POS_X_U=[(0, 10.0), (24, 90.0)]))
    ok("3D Warp animado: o valor do PRIMEIRO QUADRO (não o `value` solto)", e["params"]["pos_x"], 10.0)
    ok("…com os pontos guardados e o aviso", (e["params"]["animated"], len(av)), (True, 1))
    # ⛔ Laboratório A01 (2026-10-11), medido no render do MC 25.6:
    e, _, _ = E.enquadramento(efeito("EFF2_SBLEND", DVE_POS_X_U=100.0, DVE_POS_Y_U=50.0))
    ok("⭐ 3D Warp SEM o interruptor do grupo (DVE_POS_ENABLED_U): o MC ignora a posição → nada",
       e["params"], {})
    e, _, _ = E.enquadramento(efeito("EFF2_BLEND_RESIZE", AFX_POS_X_U=100.0, AFX_POS_Y_U=50.0))
    ok("⭐ Resize: +Y DESCE no Avid → o neutro (+Y sobe) inverte o Y", r3(e["params"]),
       {"pos_x": 100.0, "pos_y": -50.0})
    e, _, _ = E.enquadramento(efeito("EFF2_BLEND_PIP", AFX_POS_X_U=100.0, AFX_POS_Y_U=50.0))
    ok("⭐ Picture-in-Picture: o Y invertido e a escala PADRÃO de 50 % (o MC não a grava)", r3(e["params"]),
       {"pos_x": 100.0, "pos_y": -50.0, "scale_x": 0.5, "scale_y": 0.5})
    e, _, _ = E.enquadramento(efeito("EFF2_STABILIZE", DVE_POS_X_U=0.1))
    ok("estabilizador não é enquadramento (E07, à parte)", e, None)

    print("\n── 2. as bins reais: E04 e E06 até o DRT ──")
    e04 = CASOS / "E04 PIP RESIZE 3D WARP" / "avid" / "FASE 1 EFEITO.avb"
    e06 = CASOS / "E06 FRAMEFLEX" / "avid" / "TIMELINES.avb"
    if not (e04.is_file() and e06.is_file()):
        print(f"  PULADO — os casos E04/E06 não estão em {CASOS}")
    else:
        from avb_bin import segmentos as S
        from avb_export.reader import topen
        from drp.writer import build_drt

        with topen(str(e04)) as f:
            leitura = S.ler_timeline(f, next(iter(S.sequencias(f))))
        geo = {s["clip_name"]: [x for x in s["effects"] if x["category"] == "geometric"]
               for s in leitura["segments"] if not s["is_audio"] and not s["is_gap"]}
        ok("E04: 3D Warp (40, 32) 120 %", r3(geo["20240531_PANA2756"][0]["params"]),
           {"pos_x": 40.0, "pos_y": 32.0, "scale_x": 1.2, "scale_y": 1.2})
        # ⛔ CORRIGIDO (laboratório A01, 2026-10-11): no esquema AFX (Resize, PIP) +Y DESCE no render do MC; o neutro
        # é +Y sobe → o Y sai INVERTIDO. A expectativa antiga (Y cru, "conferida" em 2026-09-27) era de antes da
        # validação por imagem; a bancada mediu MC × Resolve: sem inverter 0,105, invertendo 0,998.
        ok("E04: Resize (−15, 55) 130 % → Y invertido", r3(geo["20240531_PANA2753"][0]["params"]),
           {"pos_x": -15.0, "pos_y": -55.0, "scale_x": 1.3, "scale_y": 1.3})
        ok("E04: PIP (33, −87) 78 % → Y invertido", r3(geo["20240531_PANA2750"][0]["params"]),
           {"pos_x": 33.0, "pos_y": 87.0, "scale_x": 0.78, "scale_y": 0.78})
        ok("E04: o clipe sem efeito continua sem", geo["20240531_PANA2759"], [])
        ok("E04: não sobra o aviso antigo 'parâmetros ainda não traduzidos'",
           any("não traduzidos" in a["texto"] for a in leitura["avisos"]), False)
        with tempfile.TemporaryDirectory() as tmp:
            segs, casados, metas = S.montar_midia(leitura, {}, tmp, {}, {})
            saida = os.path.join(tmp, "e04.drt")
            build_drt(segs, casados, saida, timeline_name="E04",
                      timeline_fps=float(leitura.get("timeline_fps") or 23.976), offline=metas)
            with zipfile.ZipFile(saida) as z:
                x = z.read(next(n for n in z.namelist() if "SeqContainer" in n)).decode("utf-8")
        # O clipe no DRT se chama como o ARQUIVO, com a extensão (o nome do AMA da bin).
        tf = {os.path.splitext(re.search(r"<Name>(.*?)</Name>", b).group(1))[0]:
              doubles((re.search(r"<EffectFiltersBA>(\w*)</EffectFiltersBA>", b) or [None, ""])[1] or "00" * 9)
              for b in re.findall(r"<Sm2TiVideoClip\b.*?</Sm2TiVideoClip>", x, re.DOTALL)}
        ok("⭐ DRT: 3D Warp → zoom 1,2 e posição 0,04 / 0,032 da tela", tf["20240531_PANA2756"],
           [1.2, 1.2, 0.04, 0.032])
        ok("⭐ DRT: PIP → zoom 0,78 e posição 0,033 / +0,087 (o Y do AFX invertido)", tf["20240531_PANA2750"],
           [0.78, 0.78, 0.033, 0.087])
        ok("DRT: o clipe sem efeito sai sem transform", tf["20240531_PANA2759"], [])

        with topen(str(e06)) as f:
            leituras = {S.ler_timeline(f, sq)["composition_name"]: S.ler_timeline(f, sq)
                        for sq in S.sequencias(f)}
        parado = leituras["TESTE FRAME FLEX SEM MUDAR ATRIBUTOS"]
        modos = [s["reframe_mode"] for s in parado["segments"] if not s["is_audio"] and not s["is_gap"]]
        ok("⭐ E06: os 4 modos de reformat nos 3 aspectos (a ordem da timeline)", modos,
           [None, "pillarbox"] + ["pillarbox", "keep_size", "center_crop", "stretch"] * 3)
        ok("E06: reformat puro não vira efeito (vai como modo) e não gera aviso",
           (sum(1 for s in parado["segments"] for x in s["effects"] if x.get("reproducible")),
            parado["avisos"]), (0, []))
        # ⭐ O modo vira o Scaling POR CLIPE do Resolve (filtro 0x2C, medido no TL ULTRAHD.drt
        # do autor): Pillarbox → Fit 2, Keep Size → Crop 1, Center Crop → Fill 3, Stretch 4.
        with tempfile.TemporaryDirectory() as tmp:
            segs, casados, metas = S.montar_midia(parado, {}, tmp, {}, {})
            saida = os.path.join(tmp, "e06.drt")
            build_drt(segs, casados, saida, timeline_name="E06",
                      timeline_fps=float(parado.get("timeline_fps") or 23.976), offline=metas)
            with zipfile.ZipFile(saida) as z:
                x = z.read(next(n for n in z.namelist() if "SeqContainer" in n)).decode("utf-8")
        escalas = []
        for b in re.findall(r"<Sm2TiVideoClip\b.*?</Sm2TiVideoClip>", x, re.DOTALL):
            h = (re.search(r"<EffectFiltersBA>(\w*)</EffectFiltersBA>", b) or [None, ""])[1] or ""
            m = re.search(r"082c4a004a004a08085c1a040a0220(..)4a004a00", h)
            escalas.append(int(m.group(1), 16) if m else None)
        ok("⭐ E06 no DRT: o Scaling de cada clipe, na ordem da timeline", escalas,
           [None, 2] + [2, 1, 3, 4] * 3)
        mexido = leituras["TESTE FRAME FLEX MUDANDO ATRIBUTOS"]
        ok("E06: os 2 FrameFlex animados ficam na Carta, não no DRT",
           [x["reproducible"] for s in mexido["segments"] for x in s["effects"]
            if x["category"] == "geometric"], [False, False])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
