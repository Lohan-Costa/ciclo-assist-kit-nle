"""Os markers da timeline do Avid na Carta e no Premiere (autor, 2026-11-15: "completar a troca"; banco
`protocolos/avb/estruturas.md` "Markers da TIMELINE na bin": `_TMP_CRM` → `Marker`, muitos ANINHADOS em efeitos)."""

from cicloassist.carta import importar_premiere as IP
from cicloassist.carta import timeline as T


class Marker:
    def __init__(self, off, com, cor="Red", ident=None):
        self.comp_offset = off
        self.color = [0, 0, 0]
        self.attributes = {"_ATN_CRM_COM": com, "_ATN_CRM_COLOR": cor, "_ATN_CRM_USER": "nina",
                           "_ATN_CRM_DATE": "10/12/2023", "_ATN_CRM_TIME": "15:21", "_ATN_CRM_ID": ident or com}


class Ref:                                   # a referência ainda não resolvida (`.value`)
    def __init__(self, m):
        self.value = m


class Seg:
    def __init__(self, n, marcadores=(), filhos=()):
        self.length = n
        self.attributes = {"_TMP_CRM": list(marcadores)} if marcadores else None
        self.tracks = [Trilha(f) for f in filhos]


class Transition(Seg):
    pass


class Sequence:
    def __init__(self, comps, kind="picture"):
        self.components = comps
        self.media_kind = kind
        self.attributes = None
        self.length = sum(c.length for c in comps)


class Trilha:
    def __init__(self, comp, index=1):
        self.component = comp
        self.index = index


class Mob:
    def __init__(self, trilhas):
        self.tracks = trilhas


def test_le_os_de_cima_e_os_aninhados_com_a_posicao_na_timeline():
    efeito = Seg(50, filhos=[Sequence([Seg(10), Seg(40, [Ref(Marker(5, "aninhado", "Green"))])])])
    v1 = Sequence([Seg(100), Seg(60, [Marker(7, "em cima")]), Transition(10), efeito])
    a3 = Sequence([Seg(30, [Ref(Marker(0, "som", "Blue"))])], kind="sound")
    ms = T.marcadores(Mob([Trilha(v1), Trilha(a3, 3), Trilha(Sequence([Seg(9)], "DescriptiveMetadata"))]))
    assert [(m["trilha"], m["q"], m["comentario"], m["cor"]) for m in ms] == [
        ("A3", 0, "som", "Blue"),
        ("V1", 107, "em cima", "Red"),
        ("V1", 150 + 10 + 5, "aninhado", "Green"),      # 100 + 60 − a transição de 10, + 10 dentro do efeito, + 5
    ]
    assert ms[1]["usuario"] == "nina" and ms[1]["data"] == "10/12/2023 15:21"


def test_o_mesmo_marker_duas_vezes_entra_uma():
    m = Marker(1, "repetido", ident="X")
    v1 = Sequence([Seg(10, [m, Ref(m)])])
    assert len(T.marcadores(Mob([Trilha(v1)]))) == 1


def test_o_plano_vai_em_segundos_com_a_cor_do_premiere_e_diz_o_preto():
    plano, sem_par = IP.plano_de_marcadores({"fps": "24000/1001", "marcadores": [
        {"q": 24, "trilha": "V1", "comentario": "tem\tque vir", "cor": "Black", "usuario": "nina", "data": "d"},
        {"q": 0, "trilha": "A6", "comentario": "", "cor": "Green"}]})
    l1, l2 = plano.strip("\n").split("\n")
    assert l1.split("\t") == ["1.001000", "0.000000", "5", "tem que vir", "Avid · V1 · nina · d"]
    assert l2.split("\t")[2] == "0" and sem_par == ["Black"]


def test_sem_marcadores_nao_ha_plano():
    assert IP.plano_de_marcadores({"fps": "25"}) == ("", [])
