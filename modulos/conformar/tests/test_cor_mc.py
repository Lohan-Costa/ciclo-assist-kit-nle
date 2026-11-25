"""O Color Correction do Avid → os 2 nós do Resolve (`motor/drp/cor_mc.py`, 2026-11-20).

    python tests/test_cor_mc.py        (ou pelo pytest)

- o CC que só tem Sat e curva Master se traduz; outro controle mexido (Gain, Hue…) ou keyframe NÃO (fica a nota);
- ⛔ sem as três bandeiras do HSL o MC ignora a Sat — então ela não vai (banco `avb/color-correction.md`);
- o blob da curva sai do AVUP inteiro (o AAF) ou só dos 256 bytes (a bin);
- o grafo: 1 nó ou 2 em série, na ordem Sat → curva; a curva com a forma que o Resolve aceita (UM campo 8);
- a aplicação acha o clipe pela trilha, pelo quadro e pelo nome, e manda o `.drx`.
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp import cor_mc as C  # noqa: E402
from tools.inspect_drp import pb_decode  # noqa: E402

LIGA = {n: (1, False, None) for n in C._LIGA_HSL + C._LIGA_CURVA}
PRODA = [(0.0, 0.0), (0.308107, 0.333824), (0.565271, 0.725999), (1.0, 1.0)]


def _blob(pontos, avup=False):
    xs = []
    for x, y in pontos:
        xs += [256 + 510 * x, 256 + 510 * y]
    dados = struct.pack("<32d", *(xs + [0.0] * (32 - len(xs))))
    if not avup:
        return dados
    return b"PUVA" + (292).to_bytes(4, "little") + b"II\x01\x00\x00\x00II" + bytes(16) + \
        (260).to_bytes(4, "little") + (256).to_bytes(4, "little") + dados


def _cc(**extra):
    p = dict(LIGA)
    p["Num Master Curve Keys"] = (4, False, None)
    p["Curves Master"] = (None, False, _blob(PRODA, avup=True))
    p["Mas Sat"] = (87.5, False, None)
    p.update(extra)
    return p


def test_o_cc_da_proda_se_traduz():
    cc = C.ler_cc(_cc())
    assert cc["nao"] == [] and cc["sat"] == 87.5
    assert max(abs(a - b) for p, q in zip(cc["curva"], PRODA) for a, b in zip(p, q)) < 1e-9


def test_a_bin_traz_so_os_256_bytes():
    assert C.pontos_do_blob(_blob(PRODA), 4) == C.pontos_do_blob(_blob(PRODA, avup=True), 4)


def test_sem_as_bandeiras_do_hsl_a_sat_nao_vale():
    p = _cc()
    del p["HSL Setup Bypass"]
    assert C.ler_cc(p)["sat"] is None


def test_outro_controle_ou_keyframe_nao_se_traduz():
    assert C.ler_cc(_cc(**{"Mas Gain": (120.0, False, None)}))["nao"] == ["Mas Gain"]
    assert C.ler_cc(_cc(**{"Mas Sat": (87.5, True, None)}))["nao"] == ["keyframe em Mas Sat"]


def test_neutro_nao_gera_nada():
    cc = C.ler_cc(_cc(**{"Mas Sat": (100.0, False, None),
                         "Curves Master": (None, False, _blob([(0, 0), (1, 1)])),
                         "Num Master Curve Keys": (2, False, None)}))
    assert cc["sat"] is None and cc["curva"] is None


def _nos(corpo):
    g = pb_decode(corpo)[0]["value"]
    return [x for x in g if x["field"] == 7], [x for x in g if x["field"] == 8]


def test_o_grafo():
    nos, ligacoes = _nos(C.body(87.5, C.curva_do_mc(PRODA)))
    rotulos = [next(c["value"] for c in n["value"] if c["field"] == 6) for n in nos]
    assert rotulos == [b"MC Master", b"MC Curva"] and len(ligacoes) == 1
    nos, ligacoes = _nos(C.body(None, C.curva_do_mc(PRODA)))
    assert len(nos) == 1 and not ligacoes
    # a curva Bézier: 4 + 3k pontos, começa em u = 0 e acaba em u = 1
    b = C.curva_do_mc(PRODA)
    assert (len(b) - 4) % 3 == 0 and b[0][0] == 0.0 and b[-1][0] == 1.0


class _Item:
    def __init__(self, nome, inicio):
        self.nome, self.inicio, self.drx = nome, inicio, None

    def GetName(self):
        return self.nome

    def GetStart(self):
        return self.inicio

    def GetNodeGraph(self):
        item = self

        class G:
            def ApplyGradeFromDRX(self, caminho, modo):
                item.drx = Path(caminho).read_text(encoding="utf-8")
                return True
        return G()


class _Timeline:
    def __init__(self, itens):
        self.itens = itens

    def GetStartFrame(self):
        return 86400

    def GetItemListInTrack(self, tipo, trilha):
        return self.itens if trilha == 1 else []


def test_aplicar(tmp_path=None):
    pasta = tmp_path or Path(tempfile.mkdtemp(prefix="cor_mc_"))
    a, b = _Item("A.mov", 86400 + 10), _Item("B.mov", 86400 + 50)
    fora = C.aplicar_cor_mc(_Timeline([a, b]), [
        {"trilha": 1, "quadro": 10, "arquivo": "A.mov", "sat": 87.5, "curva": [list(p) for p in PRODA]},
        {"trilha": 1, "quadro": 50, "arquivo": "OUTRO.mov", "sat": 50.0, "curva": None},
        {"trilha": 1, "quadro": 50, "arquivo": "B.mov", "sat": None, "curva": None}], str(pasta))
    assert [x["ok"] for x in fora] == [True, False, False]
    assert fora[1]["erro"] == "clipe não encontrado na timeline" and fora[2]["erro"] == "pedido inválido"
    assert "<Body>81" in a.drx and b.drx is None


def test_a_vinheta_vira_o_no_com_a_janela():
    """A Vignette da página Color (2027): nó 1 "Cor" VAZIO (a LUT entra nele depois) → nó "Vinheta" com DOIS correctors:
    tipo 1 (Primaries, o Gain) e tipo 4 (Window, a janela circular invertida). A cor no corrector da janela o Resolve
    ignora calado (medido 2026-11-20)."""
    nos, ligacoes = _nos(C.body(None, None, {"raio_px": 1136.0, "borda_px": 360.0, "gain": 0.0}))
    rotulos = [next(c["value"] for c in n["value"] if c["field"] == 6) for n in nos]
    assert rotulos == [b"Cor", b"Vinheta"] and len(ligacoes) == 1
    dec = lambda v: v if isinstance(v, list) else pb_decode(bytes(v))
    campo9 = next(c["value"] for c in nos[1]["value"] if c["field"] == 9)
    corretores = [x for x in dec(campo9) if x["field"] == 1]
    tipos = [next(c["value"] for c in dec(x["value"]) if c["field"] == 1) for x in corretores]
    assert tipos == [1, 4]

    def ids(msg):                      # todo id de parâmetro (campo 1 de cada `3:`) dentro do corrector
        out = []
        for c in dec(msg):
            if c["wire"] == 2:
                sub = dec(c["value"]) if not isinstance(c["value"], (bytes, bytearray)) or len(c["value"]) else []
                if c["field"] == 3:
                    out += [x["value"] for x in sub if x["field"] == 1]
                out += ids(c["value"]) if isinstance(c["value"], list) else []
        return out
    achados = ids(corretores[1]["value"])
    for pid in (C.JANELA["tamanho"], C.JANELA_TIPO, C.JANELA_INVERTIDA):
        assert pid in achados, hex(pid)
    # com a cor do Avid junto: Cor → MC Master → Vinheta
    nos, _ = _nos(C.body(87.5, None, {"raio_px": 1136.0, "borda_px": 360.0, "gain": 0.0}))
    assert [next(c["value"] for c in n["value"] if c["field"] == 6) for n in nos] == [b"Cor", b"MC Master", b"Vinheta"]


def test_o_pedido_so_com_vinheta_vale(tmp_path=None):
    pasta = tmp_path or Path(tempfile.mkdtemp(prefix="cor_mc_"))
    a = _Item("A.mov", 86400 + 10)
    fora = C.aplicar_cor_mc(_Timeline([a]), [
        {"trilha": 1, "quadro": 10, "arquivo": "A.mov", "vinheta": {"raio_px": 1136.0, "borda_px": 360.0, "gain": 0.0}},
        {"trilha": 1, "quadro": 10, "arquivo": "A.mov", "vinheta": {"raio_px": 1136.0, "borda_px": 360.0, "gain": 2.0}}],
        str(pasta))
    assert [x["ok"] for x in fora] == [True, False] and "<Body>81" in a.drx


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_"):
            fn()
            print(f"  ✓ {nome}")
    sys.exit(0)
