"""Atualizar corte no Baselight (etapa 5; decisões do autor de 2026-11-22), a lógica pura de `motor/baselight/atualizar.py`
— o que o laboratório BL09 mediu, sem o Baselight:

    .venv/bin/python -m pytest tests/test_baselight_atualizar.py        (Windows: .venv-win/Scripts/python)

- a impressão da cor ignora a camada 0 (todo plano tem) e muda quando a cor muda;
- o corte do colorista é a fonte EMENDADA com cores diferentes; o xmeml da v2 é cortado no mesmo quadro de fonte;
- o casamento v2 × v1 é pelo arquivo INTEIRO e trecho em comum (o trecho novo de um arquivo usado não herda);
- os markers do colorista vão pela fonte; o de trecho que saiu volta como perdido; os "[Ciclo]" não são dele.
"""
from __future__ import annotations

import base64
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import atualizar as A  # noqa: E402


def _blg(*linhas: str) -> str:
    texto = "blg := [struct\n" + "\n".join(f'  ({i})="{l}",' for i, l in enumerate(linhas)) + "\n]"
    return base64.b64encode(b"\0" * 8 + zlib.compress(texto.encode())).decode()


ZERO = ["15:GR_AudioSequenceRop 3:gr 2 f 407b800000000000 f 3ff0000000000000 ",
        "26:GR_ImageTransformParamsRop 3:gr 1 ", "17:GR_PluginInputRop t 3 f f 0: "]
CDL = "14:GR_CDLGradeRop 7:gr_misc 12 1 0 13 f 3ff051eb851eb852 f 3ff0000000000000 "


def test_impressao():
    assert A.impressao(_blg(*ZERO)) == ""                         # sem cor: só a camada 0
    com = A.impressao(_blg(*ZERO, CDL))
    assert com.startswith("GR_CDLGradeRop:3ff051eb851eb852")
    assert com == A.impressao(_blg(*ZERO[::-1], CDL))              # a camada 0 em outra ordem não muda a cor
    assert com != A.impressao(_blg(*ZERO, CDL.replace("3ff051eb", "3ff0a3d7")))


ARQ = "/m/B001C008.mov"


def test_cortes_do_colorista():
    v1 = [{"arquivo": ARQ, "src": (100, 124), "cor": "a"}, {"arquivo": ARQ, "src": (124, 148), "cor": "b"},
          {"arquivo": "/m/X.mov", "src": (0, 10), "cor": "c"}, {"arquivo": "/m/X.mov", "src": (10, 20), "cor": "c"}]
    assert A.cortes_do_colorista(v1) == {ARQ: [124]}               # mesma cor emendada não é corte do colorista


def test_mapear():
    v1 = [{"arquivo": ARQ, "src": (100, 148), "cor": "a"}, {"arquivo": "/m/A006C001.mov", "src": (30, 78), "cor": "b"},
          {"arquivo": "/cartao_b/B001C008.mov", "src": (0, 300), "cor": "z"}]
    v2 = [{"arquivo": ARQ, "src": (112, 142)},                          # aparado
          {"arquivo": "/m/A006C001.mov", "src": (200, 236)},            # trecho novo do arquivo de um plano retirado
          {"arquivo": "/m/C001C004.mov", "src": (60, 108)}]             # take trocado
    m = A.mapear(v2, v1)
    assert m[0]["v1"] == 0                                              # o outro B001C008 (outro cartão) não conta
    assert m[1]["v1"] is None and m[1]["motivo"] == "trecho novo deste arquivo"
    assert m[2]["v1"] is None and "take trocado" in m[2]["motivo"]


def test_mapear_empate_vai_ao_colorista():
    v1 = [{"arquivo": ARQ, "src": (100, 124), "cor": "a"}, {"arquivo": ARQ, "src": (124, 148), "cor": "b"}]
    assert A.mapear([{"arquivo": ARQ, "src": (112, 136)}], v1)[0]["v1"] is None
    m = A.mapear([{"arquivo": ARQ, "src": (112, 142)}], v1)[0]
    assert m["v1"] == 1 and m["aviso"]                                  # o maior trecho, com o aviso


def test_mover_marcas():
    v1 = [{"arquivo": ARQ, "src": (100, 148), "rec": (144, 192)}, {"arquivo": "/m/S7.mov", "src": (120, 168), "rec": (288, 336)}]
    v2 = [{"arquivo": "/m/S7.mov", "src": (120, 168), "rec": (84, 132)}, {"arquivo": ARQ, "src": (112, 142), "rec": (228, 258)}]
    marcas = [{"quadro": 300, "nota": "segurar o preto", "categoria": "x"},
              {"quadro": 154, "nota": "conferir o céu", "categoria": "x"},     # fonte 110: aparada fora
              {"quadro": 170, "nota": "[Ciclo] nosso", "categoria": "x"}]
    movidos, perdidos = A.mover_marcas(marcas, v1, v2)
    assert [(m["quadro"], m["de"]) for m in movidos] == [(96, 300)]
    assert [p["nota"] for p in perdidos] == ["conferir o céu"]


XML = """<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4"><sequence id="s"><duration>78</duration><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>
<media><video><track>
<clipitem id="c1"><start>0</start><end>48</end><in>48</in><out>96</out><file id="f1"><pathurl>file://localhost/m/B001C007.mov</pathurl><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate></file><link><linkclipref>c1</linkclipref></link></clipitem>
<clipitem id="c2"><start>48</start><end>78</end><in>112</in><out>142</out><file id="f2"><pathurl>file://localhost/m/B001C008.mov</pathurl><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate></file></clipitem>
</track></video></media></sequence></xmeml>
"""


def test_dividir_xmeml():
    with tempfile.TemporaryDirectory() as d:
        ent, sai = os.path.join(d, "v2.xml"), os.path.join(d, "v2d.xml")
        Path(ent).write_text(XML, encoding="utf-8")
        feitos = A.dividir_xmeml(ent, sai, {ARQ: [124], "/m/B001C007.mov": [200]})   # 200 fica fora do plano
        assert feitos == [{"arquivo": ARQ, "fonte": 124, "quadro_timeline": 60}]
        itens = ET.parse(sai).getroot().find(".//track").findall("clipitem")
        q = [(i.get("id"), i.findtext("start"), i.findtext("end"), i.findtext("in"), i.findtext("out")) for i in itens]
        assert q == [("c1", "0", "48", "48", "96"), ("c2", "48", "60", "112", "124"), ("c2-c2", "60", "78", "124", "142")]
        copia = itens[2].find("file")
        assert copia.get("id") == "f2" and len(copia) == 0                  # a cópia só referencia a definição



def test_scene_do_colorista_nao_salva(monkeypatch):
    """Mudança NÃO SALVA na scene aberta: a leitura de fora é recusada (medido, 7.0.3) → erro claro, antes de criar nada."""
    import json as _json
    import subprocess

    from baselight import enviar

    class R:
        stdout = _json.dumps({"erro": "nao_salva", "detalhe": "Scene must be opened read/write to recover or discard "
                                                             "autosave data"}) + "\n"
        stderr = ""

    monkeypatch.setattr(enviar, "python_flapi", lambda: "/py")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    try:
        enviar.ler_colorista("JOB", "C07 cor")
    except enviar.ColoristaNaoSalvou as e:
        assert "C07 cor" in str(e) and "⌘S" in str(e)
    else:
        raise AssertionError("devia recusar")


#: a curva do Slope R do S4 da "BL09 V1 look" (keyframes no quadro 7 e 41 do plano, 23,976), copiada do BLG real
_CURVA = ('17:GM_Bezier1dInterp 2:gm 1 0 0 t 3ff0a3d70a3d70a4 287:6 0 2 0.29195862529195792945 1.0400000000000000355 '
          '3.141592653589793116 0.70904237570904271593 0 0.70904237570904271593 1.7100433767100433613 '
          '1.3266666679999998824 3.141592653589793116 0.70904237570904271593 0 0.70904237570904271593 0 2 -1 '
          '0.0010000000000000000208 1.0400000000000000355  ')


def _blg_cru(*linhas: str) -> str:
    import struct

    t = ("blg := [struct\n" + "\n".join(f'  ({i})="{l}",' for i, l in enumerate(linhas)) + "\n]").encode("latin1")
    return base64.b64encode(struct.pack("<Q", len(t)) + zlib.compress(t)).decode()


def test_keyframes_presos_a_fonte():
    """O plano da v2 começa 12 quadros depois na fonte: os keyframes vão de 7/41 para −5/29 (o que o Multi-Paste faz,
    medido; o `apply_blg_payload` copiava cru)."""
    fps = 24000 / 1001
    p = _blg_cru(*ZERO, _CURVA)
    assert [[round(t * fps, 3) for t in c] for c in A.keyframes(p)] == [[7.0, 41.0]]
    d = A.deslocar_keyframes(p, -12 / fps)
    assert [[round(t * fps, 3) for t in c] for c in A.keyframes(d)] == [[-5.0, 29.0]]
    corpo = A._BEZ.search(A._cru(d))
    assert int(corpo.group(2)) == len(corpo.group(3)) - 1           # o tamanho refeito no formato medido
    assert A.impressao(d) == A.impressao(p)                         # os VALORES não mudam
    assert A.keyframes_iguais(A.keyframes(d), [[t - 12 / fps for t in A.keyframes(p)[0]]])


def test_keyframes_formato_desconhecido_recusa():
    errado = _CURVA.replace("287:", "300:")
    try:
        A.deslocar_keyframes(_blg_cru(errado), 0.5)
    except ValueError:
        pass
    else:
        raise AssertionError("devia recusar a curva fora do formato")


# ── o LOOK (decisão do autor, 2026-11-22): a faixa sobre vários planos vai ao plano novo / take trocado dentro dela ──

LOOK = "15:GR_BaseGradeRop 12:gr_BaseGrade 14 1 0 40 f 3fe0000000000000 "


def _blg_camadas(*ops: str) -> str:
    """Um BLG no formato medido (BL09): a mídia (faixa 9) + uma camada por operador, de cima para baixo."""
    import struct

    objs, faixas, n = {9: "8:GM_Strip 2:gm 1 1 8 1 o 0 0000000000000000 40000419a0290042 {i} f f 0 ",
                       8: "19:GR_InsideOutsideRop 16:gr_insideoutside 7 4 0 6 7 32 2 d Z 1:2 "}, [], 10
    for k, op in enumerate(ops):
        objs[n], objs[n + 1] = "10:GM_Integer 16:gr_insideoutside 1 0 4 ", op
        objs[n + 2] = (f"19:GR_InsideOutsideRop 16:gr_insideoutside 7 3 0 {n} {n + 1} 2 d Z f 0000000000000000 "
                       f"7:Layer:{len(ops) - k} 42c80000 ")
        objs[n + 3] = "8:GM_Strip 2:gm 1 1 %d 1 o 0 0000000000000000 40000419a0290042 {i} f f 0 " % (n + 2)
        faixas.append(n + 3)
        n += 4
    faixas.append(9)
    for idx, f in enumerate(faixas):
        objs[f] = objs[f].replace("{i}", str(idx))
    s_ = len(faixas)
    objs[1] = f"11:GM_Timeline 2:gm 3 {s_ + 3} {' '.join(map(str, faixas))} 7 8 10 0 0 {s_} {s_} 0 {s_} {s_ + 1} 1 {s_ + 2} "
    corpo = ",\n".join(f'  ({k})="{v}"' for k, v in sorted(objs.items()))
    t = ("blg := [struct\n blg_ObjectStrings=[struct\n" + corpo + ",\n ],\n]").encode("latin1")
    return base64.b64encode(struct.pack("<Q", len(t)) + zlib.compress(t)).decode()


def test_so_o_look():
    p = _blg_camadas(LOOK, CDL)                           # Layer:2 = o look, Layer:1 = a cor do plano
    cam = A.camadas(p)
    assert [c["nome"] for c in cam] == ["Layer:2", "Layer:1"]
    so = A.so_camadas(p, {cam[0]["chave"]})
    assert [c["nome"] for c in A.camadas(so)] == ["Layer:2"]
    tl = re.search(r'GM_Timeline 2:gm 3 ([^"]*)"', A._cru(so)).group(1)
    assert tl.split()[:3] == ["5", str(cam[0]["faixa"]), "9"] and tl.endswith(" 7 8 10 0 0 2 2 0 2 3 1 4 ")
    assert A.so_camadas(p, {"nenhuma"}) == ""             # sem o look: nada a aplicar


def test_look_vai_ao_plano_novo_e_ao_take_trocado():
    look, s2, s3, s4 = (A.camadas(_blg_camadas(LOOK, CDL))[0]["chave"], "s2", "s3", "s4")
    v1 = [{"rec": (0, 48), "camadas": [{"chave": "s1"}]},
          {"rec": (48, 96), "camadas": [{"chave": look}, {"chave": s2}]},
          {"rec": (96, 144), "camadas": [{"chave": look}, {"chave": s3}]},
          {"rec": (144, 192), "camadas": [{"chave": s4}]}]
    looks = A.looks_da_scene(v1)
    assert looks == [set(), {look}, {look}, set()]
    # plano NOVO entre o S2 e o S3 (os dois com o look)
    v2 = [{"rec": (0, 48)}, {"rec": (48, 96)}, {"rec": (96, 132)}, {"rec": (132, 180)}]
    mapa = [{"v1": 0}, {"v1": 1}, {"v1": None}, {"v1": 2}]
    assert A.look_para(2, v2, mapa, v1, looks) == {look}
    # TAKE TROCADO no lugar do S3 (entre o S2, com o look, e o S4, sem)
    mapa = [{"v1": 0}, {"v1": 1}, {"v1": None}, {"v1": 3}]
    assert A.look_para(2, v2, mapa, v1, looks) == {look}
    # plano novo no INÍCIO, longe do look: nada
    mapa = [{"v1": None}, {"v1": 0}, {"v1": 1}, {"v1": 2}]
    assert A.look_para(0, v2, mapa, v1, looks) == set()


def test_grupos_pelo_casamento_da_cor():
    """BL09 (2026-11-22): o grupo vai aos planos da v2 que herdaram a cor de um membro; o retirado e o take trocado
    ficam de fora e são ditos (o Multi-Paste com PasteGroups=0 os perdia todos, calado)."""
    grupos = {"SALA": [1, 6, 2], "NOITE": [3, 4], "VAZIO": [5]}
    # v2: N1 novo, S1, S7 movido, S2, S3 trocado (None), S4 aparado, S6
    mapa = [{"v1": None}, {"v1": 0}, {"v1": 6}, {"v1": 1}, {"v1": None}, {"v1": 3}, {"v1": 5}]
    g = {x["nome"]: x for x in A.levar_grupos(grupos, mapa)}
    assert list(g) == ["NOITE", "SALA", "VAZIO"]
    assert g["SALA"]["v2"] == [2, 3] and g["SALA"]["fora"] == [2]
    assert g["NOITE"]["v2"] == [5] and g["NOITE"]["fora"] == [4]
    assert g["VAZIO"]["v2"] == [6] and g["VAZIO"]["fora"] == []
    # ⭐ autor (2026-11-23): o take trocado entra no grupo do plano que ele substitui (a regra do look); o novo no início,
    # sem vizinho antes, não entra em nada
    v1 = [{"rec": (k * 48, k * 48 + 48)} for k in range(7)]
    v2 = [{"rec": (k * 40, k * 40 + 40)} for k in range(7)]
    grupos = {"SALA": [1, 6, 2], "NOITE": [3, 4], "PAR": [3, 5]}
    g = {x["nome"]: x for x in A.levar_grupos(grupos, mapa, v2, v1)}
    assert g["SALA"]["v2"] == [2, 3, 4] and g["SALA"]["novos"] == [4]          # o S3 trocado (índice 4 na v2)
    assert g["NOITE"]["novos"] == [] and g["PAR"]["novos"] == []
    # plano novo ENTRE dois do mesmo grupo
    mapa2 = [{"v1": 3}, {"v1": None}, {"v1": 5}]
    g = {x["nome"]: x for x in A.levar_grupos({"PAR": [3, 5]}, mapa2, v2[:3], v1)}
    assert g["PAR"]["novos"] == [1]

if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
