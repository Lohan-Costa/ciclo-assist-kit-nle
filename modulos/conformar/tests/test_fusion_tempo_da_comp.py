"""A máscara animada no tempo da composição (2026-11-24, Resolve Studio 21.1, Mac).

No 19 o tempo da composição de clipe é o quadro da FONTE (`COMPN_GlobalStart` 0); no 21.1 ele começa no In do clipe
(`GlobalStart` = −quadro da fonte do In). Com os keyframes no quadro da fonte, o contorno do LOU_7237 (477…) caía fora
da composição (0–122) e o plano sumia — medido pela imagem contra a referência do PRODC: 0,0 → 0,94 (quadro 560).
Sem Resolve: um TimelineItem falso que devolve o que recebeu no `ImportFusionComp`.
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "motor"))

from drp import fusion_clipe as FC  # noqa: E402

QUAD = [{"linear": True, "x": -0.5, "y": 0.5}, {"linear": True, "x": 0.5, "y": 0.5},
        {"linear": True, "x": 0.5, "y": -0.5}, {"linear": True, "x": -0.5, "y": -0.5}]


def _plano(quadros):
    poly = {"id": "Polygon1", "tipo": "PolylineMask", "largura": 1920, "altura": 1080, "suave": 0.0, "inverter": False,
            "pontos": QUAD, "quadros": quadros, "pontos_quadros": [QUAD for _ in quadros]}
    return {"nos": [poly], "ligacoes": [["MediaIn1", "EffectMask", "Polygon1"]]}


class _Comp:
    def __init__(self, inicio):
        self.inicio = inicio

    def GetAttrs(self):  # noqa: N802 — a API do Resolve
        return {"COMPN_GlobalStart": self.inicio}


class _Item:
    """O que o Resolve faz com `ImportFusionComp`: no clipe sem composição cria; com uma, substitui a ativa (21.1)."""

    def __init__(self, inicio):
        self.inicio, self.textos = inicio, []

    def GetFusionCompNameList(self):  # noqa: N802
        return [f"Composition {i + 1}" for i in range(min(len(self.textos), 1))]

    def ImportFusionComp(self, arq):  # noqa: N802
        self.textos.append(Path(arq).read_text(encoding="utf-8"))
        return True

    def ExportFusionComp(self, arq, indice):  # noqa: N802
        Path(arq).write_text(self.textos[-1].replace("MediaIn1 = Loader {", "MediaIn1 = Loader { -- MEDIA_PATH", 1),
                             encoding="utf-8")
        return True

    def GetFusionCompByIndex(self, indice):  # noqa: N802
        return _Comp(self.inicio)


def _chaves(texto):
    return [int(x) for x in re.findall(r"\[(-?\d+)\] = \{ \d+, Flags", texto)]


def test_resolve_21_leva_o_contorno_ao_tempo_da_composicao():
    item = _Item(-478.0)
    r = FC.executar(item, _plano([477, 480, 482]))
    assert r["ok"], r
    assert _chaves(item.textos[-1]) == [-1, 2, 4], "o 1º keyframe é o quadro da fonte 477 = o −1 da composição"


def test_resolve_19_fica_no_quadro_da_fonte():
    item = _Item(0.0)
    r = FC.executar(item, _plano([1105, 1109]))
    assert r["ok"], r
    assert len(item.textos) == 1, "sem deslocamento, nada a remontar"
    assert _chaves(item.textos[-1]) == [1105, 1109]


def test_mascara_parada_nao_remonta():
    item = _Item(-478.0)
    pl = _plano([477])
    pl["nos"][0].pop("quadros")
    pl["nos"][0].pop("pontos_quadros")
    assert FC.executar(item, pl)["ok"]
    assert len(item.textos) == 1


def test_no_tempo_da_comp_da_inteiros():
    pl = FC.no_tempo_da_comp(_plano([477, 480]), -478.0)
    assert pl["nos"][0]["quadros"] == [-1, 2]
    assert all(isinstance(q, int) for q in pl["nos"][0]["quadros"])
