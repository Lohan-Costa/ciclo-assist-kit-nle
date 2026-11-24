"""A página Color do Premiere 2027 no leitor do `.prproj` (`motor/prproj/pagina_cor.py`, 2026-11-20).

O risco que isto fecha: o `CompoundComponent` da página Color não tem `MatchName`, e o `None` está no `_NAO_EFEITO` —
a grade passava CALADA. Um projeto sintético mínimo (a forma medida no 27.0.0, `LAB COR 27 PAGINA`):
contêiner → nível Clip → camada Adjustment → Color And Contrast + Color Shift.

    python -m pytest modulos/conformar/tests/test_pagina_cor.py
"""
from __future__ import annotations

import gzip
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from prproj import pagina_cor as PC  # noqa: E402
from prproj.leitura import Motion, lut_composta  # noqa: E402
from prproj.projeto import Projeto  # noqa: E402

_BAL = "AAAAAAAAAAAAAAAAAADgPwAAAAAAAAAA"          # a roda Balance neutra (o blob medido)


def _obj(tag, oid, corpo, classe=""):
    cl = f' ClassID="{classe}"' if classe else ""
    return f'\n\t<{tag} ObjectID="{oid}"{cl} Version="1">{corpo}\n\t</{tag}>'


def _param(oid, pid, nome, valor, blob=False):
    v = (f'<StartKeyframeValue Encoding="base64">{valor}</StartKeyframeValue>' if blob
         else f"<StartKeyframe>-91445760000000000,{valor},0,0,0,0,0,0</StartKeyframe>")
    return _obj("VideoComponentParam", oid, f"<ParameterID>{pid}</ParameterID><Name>{nome}</Name>{v}")


def _cadeia(oid, filhos):
    comps = "".join(f'<Component Index="{i}" ObjectRef="{f}"/>' for i, f in enumerate(filhos))
    return _obj("VideoComponentChain", oid, f"<ComponentChain><Components>{comps}</Components></ComponentChain>")


def _compound(oid, tipo, cadeia, nome=""):
    corpo = (f'<ComponentOwner Version="1"><Components ObjectRef="{cadeia}"/></ComponentOwner>'
             f"<Component Version=\"7\"><ID>1</ID><InstanceName>{nome}</InstanceName></Component>"
             f"<CompoundComponentType>{tipo}</CompoundComponentType>")
    return _obj("CompoundComponent", oid, corpo, PC.COMPOUND)


def _efeito(oid, mn, params):
    refs = "".join(f'<Param Index="{i}" ObjectRef="{p}"/>' for i, p in enumerate(params))
    return _obj("VideoFilterComponent", oid, f"<Component><Params>{refs}</Params><MatchName>{mn}</MatchName></Component>")


def _projeto(tmp_path, exposure="1.", temperatura="0.", sat_shift="false", zona_exposure="0."):
    xml = '<?xml version="1.0"?>\n<PremiereData Version="3">'
    xml += _obj("VideoClipTrackItem", 1, '<ClipTrackItem><ComponentOwner><Components ObjectRef="2"/></ComponentOwner>'
                '</ClipTrackItem>')
    xml += _cadeia(2, [10])
    xml += _compound(10, PC.CONTEINER, 11) + _cadeia(11, [12])
    xml += _compound(12, PC.NIVEL_CLIP, 13) + _cadeia(13, [14])
    xml += _compound(14, PC.CAMADA_AJUSTE, 15, "Adjust 1") + _cadeia(15, [20, 30])
    xml += _efeito(20, "AE.ADBE Color And Contrast", [21, 22, 23, 24, 25])
    xml += _param(21, 2, "Exposure", exposure) + _param(22, 7, "Temperature", temperatura)
    xml += _param(23, 9, "Balance", _BAL, blob=True) + _param(24, 11, "Highlights", "false")
    xml += _param(25, 14, "Exposure", zona_exposure)
    xml += _efeito(30, "AE.ADBE Color Shift", [31])
    xml += _param(31, 2, "Sat Shift", sat_shift)
    xml += "\n</PremiereData>\n"
    arq = tmp_path / "pagina.prproj"
    with gzip.open(arq, "wb") as fh:
        fh.write(xml.encode("utf-8"))
    p = Projeto(str(arq))
    return p, p.obj("1")


def test_a_grade_da_pagina_color_nao_passa_calada(tmp_path):
    p, item = _projeto(tmp_path, exposure="1.", temperatura="30.")
    mo = Motion(p, item)
    assert mo.efeitos == []
    assert len(mo.cor) == 1
    assert mo.cor[0]["pagina_cor"] == [{"Exposure": 1.0, "Temperature": 30.0}]
    assert mo.cor[0]["nao"] == []


def test_o_que_nao_traduz_vira_aviso(tmp_path):
    p, item = _projeto(tmp_path, exposure="0.", sat_shift="true", zona_exposure="0.5")
    mo = Motion(p, item)
    assert mo.cor[0]["pagina_cor"] == []
    assert "página Color: Color Shift" in mo.cor[0]["nao"]
    assert "página Color: zona Highlights" in mo.cor[0]["nao"]


def test_camada_neutra_nao_gera_nada(tmp_path):
    p, item = _projeto(tmp_path, exposure="0.")
    assert Motion(p, item).cor == []


def test_pivot_sem_contrast_nao_conta():
    """A camada nova do "+" nasce com Pivot 0 (a 1ª com −3): com o Contrast em 1 o Pivot não age."""
    assert PC.funcao({"Pivot": 0.0})(0.3, 0.5, 0.7) == (0.3, 0.5, 0.7)


def test_o_modelo():
    # Exposure 1 = ganho 2 na luz LINEAR (v²): o cinza 0,5 vai a √0,5
    r, g, b = PC.funcao({"Exposure": 1.0})(0.5, 0.5, 0.5)
    assert abs(r - 0.5 ** 0.5) < 1e-12 and r == g == b
    # neutro é identidade; Temperature preserva o cinza (Bradford mantém o Y) só aproximadamente, mas esquenta
    assert PC.funcao({})(0.3, 0.6, 0.9) == (0.3, 0.6, 0.9)
    r, g, b = PC.funcao({"Temperature": 50.0})(0.5, 0.5, 0.5)
    assert r > g > b
    # a matriz da tabela medida pelo Frida (Temperature 25), a lei reproduz com erro pequeno
    m = PC.matriz_temperatura_tint(25.0, 0.0)
    medida = (1.03311, 0.04904, 0.00789, -0.00234, 0.98867, 0.00272, -0.00357, -0.01259, 0.85937)
    assert max(abs(a - b) for a, b in zip([x for linha in m for x in linha], medida)) < 0.01


def test_a_lut_leva_a_etapa():
    cubo = lut_composta([{"pagina_cor": {"Saturation": 0.0}}], n=3)
    linhas = [ln for ln in cubo.splitlines() if ln and ln[0].isdigit()]
    assert len(linhas) == 27
    r, g, b = map(float, linhas[1].split())            # o vermelho 0,5 puro, saturação 0 → cinza
    assert abs(r - g) < 1e-6 and abs(g - b) < 1e-6


def test_a_cor_sai_na_ordem_do_render(tmp_path):
    """O Premiere renderiza a cadeia do ÚLTIMO índice do arquivo para o primeiro (medido 2026-11-20, duas Lumetris na
    carta B24): a 1ª camada do arquivo é a ÚLTIMA aplicada."""
    def camada(base, exposure):
        return (_compound(base, PC.CONTEINER, base + 1) + _cadeia(base + 1, [base + 2])
                + _compound(base + 2, PC.NIVEL_CLIP, base + 3) + _cadeia(base + 3, [base + 4])
                + _compound(base + 4, PC.CAMADA_AJUSTE, base + 5, "Adjust 1") + _cadeia(base + 5, [base + 6])
                + _efeito(base + 6, "AE.ADBE Color And Contrast", [base + 7]) + _param(base + 7, 2, "Exposure", exposure))
    xml = '<?xml version="1.0"?>\n<PremiereData Version="3">'
    xml += _obj("VideoClipTrackItem", 1, '<ClipTrackItem><ComponentOwner><Components ObjectRef="2"/></ComponentOwner>'
                '</ClipTrackItem>')
    xml += _cadeia(2, [10, 30]) + camada(10, "1.") + camada(30, "2.") + "\n</PremiereData>\n"
    arq = (tmp_path or Path(".")) / "ordem.prproj"
    with gzip.open(arq, "wb") as fh:
        fh.write(xml.encode("utf-8"))
    p = Projeto(str(arq))
    assert [c["pagina_cor"] for c in Motion(p, p.obj("1")).cor] == [[{"Exposure": 2.0}], [{"Exposure": 1.0}]]


def test_dentro_da_pagina_a_ordem_e_a_do_arquivo(tmp_path=None):
    """DENTRO da página Color o arquivo está na ordem do render (o contrário da cadeia do clipe): duas camadas no nível
    Clip, Exposure e Contrast trocados — na ordem do arquivo 0,09 código, na inversa 22,9 (Premiere 27.0.0, 2026-11-20,
    `laboratorio-de-midia/lab/premiere27_ordem_camadas.py`); Clip × Grupo, o mesmo."""
    xml = '<?xml version="1.0"?>' + chr(10) + '<PremiereData Version="3">'
    xml += _obj("VideoClipTrackItem", 1, '<ClipTrackItem><ComponentOwner><Components ObjectRef="2"/></ComponentOwner>'
                '</ClipTrackItem>')
    xml += _cadeia(2, [10]) + _compound(10, PC.CONTEINER, 11) + _cadeia(11, [12])
    xml += _compound(12, PC.NIVEL_CLIP, 13) + _cadeia(13, [14, 24])
    for base, (nome, valor) in ((14, ("Exposure", "1.")), (24, ("Contrast", "0.5"))):
        pid = 2 if nome == "Exposure" else 4
        xml += (_compound(base, PC.CAMADA_AJUSTE, base + 1, f"Adjust {1 if base == 14 else 2}") + _cadeia(base + 1, [base + 2])
                + _efeito(base + 2, "AE.ADBE Color And Contrast", [base + 3]) + _param(base + 3, pid, nome, valor))
    xml += chr(10) + "</PremiereData>" + chr(10)
    arq = Path(tmp_path or tempfile.mkdtemp(prefix="pagina_cor_")) / "camadas.prproj"
    with gzip.open(arq, "wb") as fh:
        fh.write(xml.encode("utf-8"))
    p = Projeto(str(arq))
    assert Motion(p, p.obj("1")).cor[0]["pagina_cor"] == [{"Exposure": 1.0}, {"Contrast": 0.5}]


def test_a_arvore_do_nivel_sequence(tmp_path=None):
    """O nível Sequence (pilotado no 27): 65543 → 65540 "Sequence Style 1" (VAZIA = neutra) + 65538 "Sequence Adjust 1"."""
    xml = '<?xml version="1.0"?>' + chr(10) + '<PremiereData Version="3">'
    xml += _compound(10, PC.CONTEINER_SEQ, 11) + _cadeia(11, [12, 14])
    xml += _compound(12, PC.ESTILO, 13, "Sequence Style 1") + _cadeia(13, [])
    xml += (_compound(14, PC.CAMADA_AJUSTE, 15, "Sequence Adjust 1") + _cadeia(15, [16])
            + _efeito(16, "AE.ADBE Color And Contrast", [17]) + _param(17, 2, "Exposure", "1.5"))
    xml += chr(10) + "</PremiereData>" + chr(10)
    arq = Path(tmp_path or tempfile.mkdtemp(prefix="pagina_cor_")) / "seq.prproj"
    with gzip.open(arq, "wb") as fh:
        fh.write(xml.encode("utf-8"))
    p = Projeto(str(arq))
    assert PC.ler_pagina_cor(p, p.obj("10")) == {"pagina_cor": [{"Exposure": 1.5}], "nao": [], "vinheta": []}


def test_a_grade_da_sequencia_vai_depois_da_do_clipe():
    """Decisão do autor (2026-11-20): a grade do nível Sequence vai na LUT de cada clipe, DEPOIS da do clipe (Clip →
    Sequence, medido pelo pixel: a conta composta bate o render do Premiere 27 com 0,08–0,10 código). Usa o projeto do
    laboratório quando ele está no disco."""
    lab = RAIZ.parents[3] / "laboratorio-de-midia" / "saida" / "bancadas" / "premiere-27.0.0" / "B24_COR_MC"
    arq = lab / "LAB COR 27 SEQ ORDEM.prproj"
    if not arq.exists():
        print("    (pulado: o projeto do laboratório não está no disco)")
        return
    from prproj.leitura import Leitor
    segs = Leitor(Projeto(str(arq))).ler("COR")["segmentos"][:2]
    etapas = [[e for x in s["effects"] if x["category"] == "lut" for e in x["params"]["etapas"]] for s in segs]
    seq = {"pagina_cor": {"Contrast": 0.5, "Pivot": 0.0}}
    assert etapas[0] == [seq]                                          # só a sequência
    assert etapas[1] == [{"pagina_cor": {"Exposure": 1.0}}, seq]       # o clipe, DEPOIS a sequência

def test_a_camada_lut_da_pagina():
    """A camada LUT da página Color (pilotado no 27): `AE.ADBE LUT Transform` com a tabela no "LUT Blob" — um ITX3 com o
    tamanho no byte 4 (o da Lumetri o tem no 24). Usa o projeto do laboratório quando ele está no disco."""
    arq = (RAIZ.parents[3] / "laboratorio-de-midia" / "saida" / "bancadas" / "premiere-27.0.0" / "B24_COR_MC"
           / "LAB COR 27 SEQ LUT UI.prproj")
    if not arq.exists():
        print("    (pulado: o projeto do laboratório não está no disco)")
        return
    from prproj.leitura import Leitor, _amostrador_itx3
    s = Leitor(Projeto(str(arq))).ler("COR")["segmentos"][0]
    etapas = [e for x in s["effects"] if x["category"] == "lut" for e in x["params"]["etapas"]]
    assert list(etapas[-1]) == ["itx3_b64", "intensidade"]          # a LUT DEPOIS da Adjust da sequência
    r, g, b = _amostrador_itx3(etapas[-1]["itx3_b64"], 100.0)(0.5, 0.5, 0.5)
    assert b > r and g > r                                           # "SL BLUE COLD": o cinza esfria


if __name__ == "__main__":
    import tempfile
    for nome, fn in list(globals().items()):
        if nome.startswith("test_"):
            fn(*([Path(tempfile.mkdtemp(prefix="pagina_cor_"))] if fn.__code__.co_argcount else []))
            print(f"  ✓ {nome}")
    sys.exit(0)


def test_a_style_e_um_conteiner_de_efeitos(tmp_path=None):
    """A Style (65540): escolher o módulo "Color / Contrast" grava nela um `AE.ADBE Color And Contrast` comum, que
    RENDERIZA como o da camada Adjustment e na ordem do arquivo (27.0.0, `lab/premiere27_style.py`: 0,09 código ×
    22,9 na inversa). Antes ela virava só o aviso "(Style/LUT?)". Módulo de efeito desconhecido = aviso pelo nome."""
    xml = '<?xml version="1.0"?>' + chr(10) + '<PremiereData Version="3">'
    xml += _compound(10, PC.CONTEINER_SEQ, 11) + _cadeia(11, [12, 14])
    xml += _compound(12, PC.ESTILO, 13, "Sequence Style 1") + _cadeia(13, [16, 18])
    xml += _efeito(16, "AE.ADBE Color And Contrast", [17]) + _param(17, 2, "Exposure", "1.")
    xml += _efeito(18, "AE.ADBE Film Color", [])
    xml += (_compound(14, PC.CAMADA_AJUSTE, 15, "Sequence Adjust 1") + _cadeia(15, [19])
            + _efeito(19, "AE.ADBE Color And Contrast", [20]) + _param(20, 4, "Contrast", "0.5"))
    xml += chr(10) + "</PremiereData>" + chr(10)
    arq = Path(tmp_path or tempfile.mkdtemp(prefix="pagina_cor_")) / "style.prproj"
    with gzip.open(arq, "wb") as fh:
        fh.write(xml.encode("utf-8"))
    p = Projeto(str(arq))
    assert PC.ler_pagina_cor(p, p.obj("10")) == {"pagina_cor": [{"Exposure": 1.0}, {"Contrast": 0.5}],
                                                 "nao": ["página Color: AE.ADBE Film Color"], "vinheta": []}


def test_a_style_do_laboratorio():
    """O projeto medido pelo pixel (`LAB COR 27 STYLE PIXEL`): Style Exposure +1 → Adjust Contrast 0,5 / Pivot 0, na
    sequência. Usa o projeto do laboratório quando ele está no disco."""
    arq = (RAIZ.parents[3] / "laboratorio-de-midia" / "saida" / "bancadas" / "premiere-27.0.0" / "B24_COR_MC"
           / "LAB COR 27 STYLE PIXEL.prproj")
    if not arq.exists():
        print("    (pulado: o projeto do laboratório não está no disco)")
        return
    from prproj.leitura import Leitor
    segs = Leitor(Projeto(str(arq))).ler("COR")["segmentos"][:2]
    etapas = [[e for x in s["effects"] if x["category"] == "lut" for e in x["params"]["etapas"]] for s in segs]
    seq = [{"pagina_cor": {"Exposure": 1.0}}, {"pagina_cor": {"Contrast": 0.5, "Pivot": 0.0}}]
    assert etapas[0] == seq
    assert etapas[1] == [{"pagina_cor": {"Exposure": 1.0}}] + seq


def test_o_contrast_kit_neutro_nao_avisa(tmp_path=None):
    """O módulo Contrast Kit (`AE.ADBE Contrast`) recém-escolhido é neutro: não gera aviso; mexido, avisa pelo nome."""
    for valor, nao in (("0.", []), ("0.3", ["página Color: Contrast Kit"])):
        xml = '<?xml version="1.0"?>' + chr(10) + '<PremiereData Version="3">'
        xml += _compound(10, PC.CONTEINER_SEQ, 11) + _cadeia(11, [12])
        xml += _compound(12, PC.ESTILO, 13, "Sequence Style 1") + _cadeia(13, [16])
        xml += _efeito(16, "AE.ADBE Contrast", [17, 18]) + _param(17, 1, "Contrast", valor) + _param(18, 2, "Midpoint", "0.5")
        xml += chr(10) + "</PremiereData>" + chr(10)
        arq = Path(tmp_path or tempfile.mkdtemp(prefix="pagina_cor_")) / f"kit{valor}.prproj"
        with gzip.open(arq, "wb") as fh:
            fh.write(xml.encode("utf-8"))
        p = Projeto(str(arq))
        assert PC.ler_pagina_cor(p, p.obj("10")) == {"pagina_cor": [], "nao": nao, "vinheta": []}


def test_os_modulos_da_style_do_laboratorio():
    """Os 9 módulos escolhidos de uma vez (`LAB COR 27 STYLE C`): Flare, Midtones, Variable Vibrance e Contrast Kit
    nascem neutros (sem aviso); o Film Color padrão é TRADUZIDO (a LUT do estoque); a Vignette avisa."""
    arq = (RAIZ.parents[3] / "laboratorio-de-midia" / "saida" / "bancadas" / "premiere-27.0.0" / "B24_COR_MC"
           / "LAB COR 27 STYLE C.prproj")
    if not arq.exists():
        print("    (pulado: o projeto do laboratório não está no disco)")
        return
    from prproj.leitura import Leitor
    av = " ".join(a["texto"] for a in Leitor(Projeto(str(arq))).ler("COR")["avisos"])
    assert "Vignette" in av
    for neutro in ("Flare", "Midtones", "Variable Vibrance", "Contrast Kit", "Film Color"):
        assert neutro not in av, neutro


def _film(tmp_path, forca="1."):
    import base64
    import struct as st
    n = 2
    itx3 = b"ITX3" + st.pack("<II", n, 3) + b"\0" * 28 + st.pack(f"<{n ** 3 * 3}f", *([0.5] * n ** 3 * 3))
    xml = '<?xml version="1.0"?>' + chr(10) + '<PremiereData Version="3">'
    xml += _compound(10, PC.CONTEINER_SEQ, 11) + _cadeia(11, [12])
    xml += _compound(12, PC.ESTILO, 13, "Sequence Style 1") + _cadeia(13, [16])
    xml += _efeito(16, "AE.ADBE Color Film", [17, 18, 19])
    xml += _param(17, 3, "Global Strength", forca) + _param(18, 8, "Highlight Balance", _BAL, blob=True)
    xml += _param(19, 18, " ", base64.b64encode(itx3).decode(), blob=True)
    xml += chr(10) + "</PremiereData>" + chr(10)
    arq = Path(tmp_path or tempfile.mkdtemp(prefix="pagina_cor_")) / f"film{forca}.prproj"
    with gzip.open(arq, "wb") as fh:
        fh.write(xml.encode("utf-8"))
    p = Projeto(str(arq))
    return PC.ler_pagina_cor(p, p.obj("10"))


def test_o_film_color_padrao_e_o_estoque_embutido(tmp_path=None):
    """O Film Color padrão = a LUT do estoque que vai EMBUTIDA no projeto (param 18, ITX3); com um ajuste além do
    estoque (aqui a força 0,5), aviso — o kernel que modula a LUT ainda não está portado."""
    r = _film(tmp_path)
    assert [list(e) for e in r["pagina_cor"]] == [["lut"]] and r["nao"] == []
    assert r["pagina_cor"][0]["lut"]["itx3_b64"].startswith("SVRYM")
    assert _film(tmp_path, "0.5") == {"pagina_cor": [], "nao": ["página Color: Film Color com ajustes além do estoque"], "vinheta": []}


def test_o_film_color_do_laboratorio_pelo_pixel():
    """`LAB COR 27 FILM PIXEL` (o Film Color padrão, Fuji ETERNA 250 / Fuji 3510, sozinho na Style da sequência): a LUT
    que o Conformar compõe (41³, alinhada à de 21³) bate o render do Premiere 27 medido (< 0,35 código de média)."""
    lab = RAIZ.parents[3] / "laboratorio-de-midia"
    pasta = lab / "saida" / "bancadas" / "premiere-27.0.0" / "B24_COR_MC"
    arq, med = pasta / "LAB COR 27 FILM PIXEL.prproj", pasta / "LAB COR 27 FILM PIXEL_medidas.json"
    if not (arq.exists() and med.exists()):
        print("    (pulado: o projeto do laboratório não está no disco)")
        return
    import json
    from prproj.leitura import Leitor
    sys.path.insert(0, str(lab))
    from lab import cor_b24_modelo as M
    seg = Leitor(Projeto(str(arq))).ler("COR")["segmentos"][0]
    etapas = [e for x in seg["effects"] if x["category"] == "lut" for e in x["params"]["etapas"]]
    linhas = [l.split() for l in lut_composta(etapas).splitlines() if l[:1].isdigit()]
    n = round(len(linhas) ** (1 / 3))
    assert n == 41
    tab = [[float(c) for c in l] for l in linhas]

    def amostra(v):
        p = [min(max(c, 0.0), 1.0) * (n - 1) for c in v]
        q = [min(int(x), n - 2) for x in p]
        t = [x - y for x, y in zip(p, q)]
        out = [0.0] * 3
        for dr in (0, 1):
            for dg in (0, 1):
                for db in (0, 1):
                    w = (t[0] if dr else 1 - t[0]) * (t[1] if dg else 1 - t[1]) * (t[2] if db else 1 - t[2])
                    c = tab[((q[2] + db) * n + q[1] + dg) * n + q[0] + dr]
                    out = [o + w * x for o, x in zip(out, c)]
        return out
    medida = json.load(open(med, encoding="utf-8"))["medida"]
    base = json.load(open(pasta / "LAB COR 27 CAMADAS_medidas.json", encoding="utf-8"))["medidas"][0]
    erros = []
    for x in (k for k in base if not k.startswith("_")):
        v = [(c - 16) / 219 for c in M.para_rgb(*base[x])]
        q = M.de_rgb(*[16 + 219 * c for c in amostra(v)])
        if all(16 <= c <= 235 for c in M.para_rgb(*q)):
            erros.append(max(abs(a - b) for a, b in zip([M.cortar(c) for c in q], medida[x])))
    assert sum(erros) / len(erros) < 0.35, sum(erros) / len(erros)


def test_a_vinheta_padrao_vira_a_janela():
    """A Vignette (`AE.Impact_Vignette_FX`) na forma padrão → o pedido da janela (`vinheta`), e os avisos do que a janela
    não faz (o desfoque, a aberração); com um controle de forma mexido → aviso, sem janela."""
    def proj(width):
        xml = '<?xml version="1.0"?>' + chr(10) + '<PremiereData Version="3">'
        xml += _compound(10, PC.CONTEINER_SEQ, 11) + _cadeia(11, [12])
        xml += _compound(12, PC.ESTILO, 13, "Sequence Style 1") + _cadeia(13, [16])
        vals = {2: "100.", 3: width, 4: "80.", 5: "100.", 8: "100.", 9: "50.", 10: "20.", 11: "20.", 12: "100.",
                14: "100.", 16: "18374686479671623680"}
        refs = list(range(20, 20 + len(vals)))
        xml += _efeito(16, "AE.Impact_Vignette_FX", refs + [40])
        for r, (pid, v) in zip(refs, vals.items()):
            xml += _param(r, pid, f"p{pid}", v)
        xml += _obj("VideoComponentParam", 40, "<ParameterID>7</ParameterID><Name>Center</Name>"
                    "<StartKeyframe>-91445760000000000,0.5:0.5,0,0,0,0,0,0</StartKeyframe>")
        xml += chr(10) + "</PremiereData>" + chr(10)
        arq = Path(tempfile.mkdtemp(prefix="pagina_cor_")) / "vinheta.prproj"
        with gzip.open(arq, "wb") as fh:
            fh.write(xml.encode("utf-8"))
        p = Projeto(str(arq))
        return PC.ler_pagina_cor(p, p.obj("10"))
    r = proj("80.")
    assert r["vinheta"] == [PC.VINHETA_JANELA] and r["pagina_cor"] == []
    assert r["nao"] == ["página Color: Vignette — o desfoque da borda (Softness)", "página Color: Vignette — a aberração cromática"]
    r = proj("60.")
    assert r["vinheta"] == [] and r["nao"] == ["página Color: Vignette com ajustes (só a padrão se traduz)"]
