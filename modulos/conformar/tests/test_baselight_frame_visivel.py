"""A entrega ao Baselight corrige ANTES de mandar e a conferência olha o 1º E o último quadro visível (autor, 2026-11-22).

Rodar:

    .venv/bin/python tests/test_baselight_frame_visivel.py        (Windows: .venv-win/Scripts/python)

- `baselight.entrega.reescrever`: o `<file>` do daily vira o ORIGINAL decidido (taxa, TC, duração, raster); sem decisão
  = offline de propósito. `esperado`: in/out NO ARQUIVO pela ponte pelo original (segundos desde o início × taxa dele).
- `baselight.conferencia`: `bl-shots` × esperado → ok / arquivo_diferente / fora_do_ponto / sem_midia / offline.
Os números vêm do laboratório BL08 (P3: daily 23,976 de um original 59,94; o Baselight leu 118–235 com a taxa certa e
47–94 com a do daily).
"""
from __future__ import annotations

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import conferencia as C  # noqa: E402
from baselight import entrega as E  # noqa: E402

XMEML = """<?xml version="1.0" encoding="UTF-8"?><xmeml version="4"><sequence><name>T</name>
<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate><media><video><track>
<clipitem id="c1"><name>B001C005.mov</name><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>
<start>0</start><end>48</end><in>47</in><out>95</out><file id="f1"><name>B001C005.mov</name>
<pathurl>file://localhost/proxies/B001C005.mov</pathurl><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>
<duration>240</duration><timecode><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate><string>12:00:00:00</string>
<frame>1036800</frame><displayformat>NDF</displayformat></timecode><media><video><samplecharacteristics>
<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate><width>960</width><height>540</height></samplecharacteristics>
</video></media></file></clipitem>
<clipitem id="c2"><name>A001C004.mov</name><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>
<start>48</start><end>96</end><in>47</in><out>95</out><file id="f2"><name>A001C004.mov</name>
<pathurl>file://localhost/proxies/A001C004.mov</pathurl><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>
<duration>360</duration><timecode><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate><string>11:00:00:00</string>
<frame>950400</frame><displayformat>NDF</displayformat></timecode><media><video><samplecharacteristics>
<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate><width>960</width><height>540</height></samplecharacteristics>
</video></media></file></clipitem></track></video></media></sequence></xmeml>"""

ORIGINAL = {"caminho": "/originais/B001C005.mov", "fps": 60000 / 1001, "timebase": 60, "ntsc": "TRUE",
            "tc": "12:00:00:00", "tc_quadros": 2592000, "df": False, "quadros": 600, "w": 1920, "h": 1080}


def _reescrito(d: str) -> str:
    ent, sai = os.path.join(d, "a.xml"), os.path.join(d, "b.xml")
    Path(ent).write_text(XMEML, encoding="utf-8")
    feitos = E.reescrever(ent, sai, {"/proxies/B001C005.mov": ORIGINAL, "/proxies/A001C004.mov": None}, "/offline")
    assert feitos == {"/proxies/B001C005.mov": "/originais/B001C005.mov", "/proxies/A001C004.mov": "offline"}, feitos
    return sai


def test_reescrever_e_esperado():
    with tempfile.TemporaryDirectory() as d:
        esp = E.esperado(_reescrito(d))
    p3, p2 = esp
    assert p3["arquivo"] == "/originais/B001C005.mov"
    assert abs(p3["fps_arquivo"] - 59.94) < 0.01
    assert (p3["in"], p3["out"]) == (118, 237), p3           # 47/23,976 s × 59,94 = 117,5 → 118; 48 quadros = 120
    assert C.PREFIXO_OFFLINE in p2["arquivo"]


def test_conferir_os_estados():
    with tempfile.TemporaryDirectory() as d:
        esp = E.esperado(_reescrito(d))
    certo = C.ler_bl_shots("118\t235\t0\t47\t/originais/B001C005.mov\n47\t94\t48\t95\t%C/LAB/%R/%.7F.dpx\n")
    r = C.conferir(certo, esp)
    assert [x["estado"] for x in r] == ["ok", "offline_de_proposito"], r          # 235 × 237: dentro de 3 quadros
    taxa_do_daily = C.ler_bl_shots("47\t94\t0\t47\t/originais/B001C005.mov\n")
    r = C.conferir(taxa_do_daily, esp)
    assert r[0]["estado"] == "fora_do_ponto" and "fora do ponto" in C.motivo(r[0]), r   # o erro calado do A, agora DITO
    trocado = C.conferir(C.ler_bl_shots("118\t235\t0\t47\t/backup/OUTRO/B001C005.mov\n"), esp)
    assert trocado[0]["estado"] == "arquivo_diferente"
    assert C.linhas_de_troca(trocado) == ['118 235 "/backup/OUTRO/B001C005.mov" "/originais/B001C005.mov"']
    assert C.conferir([], esp)[0]["estado"] == "sem_midia"


def test_mesma_taxa_tolerancia_um_quadro():
    esp = [{"inicio": 0, "fim": 48, "arquivo": "/o/X.mov", "in": 71, "out": 118, "fps_arquivo": 24000 / 1001,
            "fps_timeline": 24000 / 1001}]
    assert C.conferir(C.ler_bl_shots("72\t119\t0\t47\t/o/X.mov"), esp)[0]["estado"] == "ok"
    assert C.conferir(C.ler_bl_shots("73\t120\t0\t47\t/o/X.mov"), esp)[0]["estado"] == "fora_do_ponto"


def _clip(cid: str, nome: str, ini: int, fim: int, entra: int) -> str:
    r = "<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>"
    return (f'<clipitem id="{cid}"><name>{nome}</name>{r}<start>{ini}</start><end>{fim}</end><in>{entra}</in>'
            f'<out>{entra + fim - ini}</out><file id="f{nome}"><name>{nome}</name><pathurl>file://localhost/o/{nome}'
            f'</pathurl>{r}<duration>480</duration></file></clipitem>')


def test_multitrilha_o_escondido_nao_e_esperado():
    """BL09 multitrilha (7.0.3, 2026-11-22): o bl-conform deixa FORA o plano coberto inteiro pela trilha de cima; o
    parcialmente coberto entra inteiro. Esperar o escondido casava com o de cima no mesmo início e o `-replace` trocava a
    imagem do plano VISÍVEL."""
    r = "<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>"
    xml = (f'<?xml version="1.0"?><xmeml version="4"><sequence><name>MT</name>{r}<media><video>'
           f'<track>{_clip("a", "S2.mov", 0, 48, 24)}{_clip("b", "S5.mov", 48, 96, 30)}</track>'
           f'<track>{_clip("c", "IN.mov", 24, 48, 200)}{_clip("d", "S5x.mov", 48, 96, 0)}</track>'
           f'</video></media></sequence></xmeml>')
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "mt.xml")
        Path(p).write_text(xml, encoding="utf-8")
        esp = E.esperado(p)
    assert [(os.path.basename(e["arquivo"]), e["inicio"]) for e in esp] == [("S2.mov", 0), ("IN.mov", 24),
                                                                            ("S5x.mov", 48)]
    # o que o Baselight fez: as três tiras; e duas trilhas começando no MESMO quadro casam pelo arquivo
    tiras = C.ler_bl_shots("24\t71\t0\t47\t/o/S2.mov\n200\t223\t24\t47\t/o/IN.mov\n0\t47\t48\t95\t/o/S5x.mov\n")
    assert [x["estado"] for x in C.conferir(tiras, esp)] == ["ok", "ok", "ok"]
    esp2 = [{**esp[2], "inicio": 48}, {**esp[2], "arquivo": "/o/OUTRO.mov", "inicio": 48, "fim": 60, "out": 11}]
    tiras2 = C.ler_bl_shots("0\t11\t48\t59\t/o/OUTRO.mov\n0\t47\t48\t95\t/o/S5x.mov\n")
    assert [x["estado"] for x in C.conferir(tiras2, esp2)] == ["ok", "ok"]
    assert E._coberto(10, 20, [(0, 12), (12, 25)]) and not E._coberto(10, 20, [(0, 12), (13, 25)])


def test_trecho_desloca_so_o_plano_dele():
    """O render da cor (`/r/S3_COR.mov`, trecho do original a partir de 60 quadros) e um plano que usa o MESMO original
    direto: só o do render se desloca; a nota vai ao plano dele."""
    r = "<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>"
    xml = (f'<?xml version="1.0"?><xmeml version="4"><sequence><name>R</name>{r}<media><video><track>'
           + _clip("a", "S3_COR.mov", 0, 40, 4).replace("/o/S3_COR.mov", "/r/S3_COR.mov")
           + _clip("b", "C001C003.mov", 40, 88, 150) + '</track></video></media></sequence></xmeml>')
    o = {"caminho": "/o/C001C003.mov", "fps": 24000 / 1001, "timebase": 24, "ntsc": "TRUE", "tc": "17:00:00:00",
         "tc_quadros": 1468800, "df": False, "quadros": 240, "w": 1920, "h": 1080}
    decisao = {"/r/S3_COR.mov": {**o, "desloc_s": 60 * 1001 / 24000, "nota": "um trecho do original"},
               "/o/C001C003.mov": o}
    with tempfile.TemporaryDirectory() as d:
        ent, sai = os.path.join(d, "a.xml"), os.path.join(d, "b.xml")
        Path(ent).write_text(xml, encoding="utf-8")
        E.reescrever(ent, sai, decisao, "/offline")
        cis = ET.parse(sai).getroot().findall(".//clipitem")
        assert [(c.findtext("in"), c.findtext("out")) for c in cis] == [("64", "104"), ("150", "198")]
        assert E.notas_dos_trechos(ent, decisao) == [(0, "um trecho do original")]


if __name__ == "__main__":
    for t in (test_reescrever_e_esperado, test_conferir_os_estados, test_mesma_taxa_tolerancia_um_quadro,
              test_multitrilha_o_escondido_nao_e_esperado, test_trecho_desloca_so_o_plano_dele):
        t()
        print("ok", t.__name__)
    sys.exit(0)
