"""A trilha de notas (Sinais do Import, aprovado pelo autor em 2026-09-27).

Rodar:

    .venv-win/Scripts/python tests/test_notas.py

Confere as regras do autor sem disco:
- keyframe LINEAR: `efeito · parâmetro · linear · N keyframes > [in]-[out] ([cadeia])`, com o in-out
  DESTE intervalo em vermelho (e o N); com só dois keyframes, sem parênteses; espera antes e depois;
- keyframe NÃO linear (autor, 2026-10-23): o tipo da curva e só o 1º e o último valor, sem cortar;
- RAMPA: só a velocidade do 1º e do último instante (acabou o Text por quadro);
- estabilizador, cor e efeito desconhecido: a nota e a cor sugerida;
- a cabeça (formato v2): trilha, nome, tipo do clipe e TC source;
- o writer: UMA trilha nova de Text+ (variante B), desligada; as notas que se tocam num clipe só, cada uma
  uma camada; só caracteres comuns.
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

import notas as N  # noqa: E402


def seg(tc_in="00:00:10:00", dur=120, track=1, efeitos=None, **extra):
    base = {"timeline_tc_in": tc_in, "duration_frames": dur, "track": track, "is_audio": False,
            "is_gap": False, "is_transition": False, "disabled": False, "effects": efeitos or [],
            "clip_name": "A001", "mob_id": "m1", "source_start_frames": 0, "source_fps": 24.0}
    base.update(extra)
    return base


def texto(nota) -> list[str]:
    """Cada linha da DESCRIÇÃO como texto, com o destaque entre « » — sem a linha de cabeça
    ("V01 <clipe>", 2026-10-06), que tem o seu próprio caso (`cabeca`)."""
    return ["".join(f"«{t}»" if d else t for t, d in linha) for linha in nota["linhas"][1:]]


def cabeca(nota) -> str:
    return "".join(t for t, _d in nota["linhas"][0])


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 62 else f"{repr(obtido)[:59]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<62} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    def notas(*segmentos, masters=None):
        return N.das_notas({"timeline_fps": 24, "segments": list(segmentos), "masters": masters or {}})

    print("── 1. keyframes: [in]-[out] ([cadeia com o intervalo em vermelho]) ──")
    ff = {"name": "INT_EFF_SPATIAL_ADAPTER", "category": "geometric", "reproducible": False,
          "params": {"animated": True, "interp_avid": {"AFX_SPATIAL_FRAMING_WID": "Linear"},
                     "keyframes_avid": {"AFX_SPATIAL_FRAMING_WID": [(0, 56), (40, 75), (120, 100)]}}}
    ns = notas(seg(efeitos=[ff]))
    ok("três keyframes = duas notas, cortadas no quadro 40", [(n["inicio"], n["dur"]) for n in ns],
       [(240, 40), (280, 80)])
    ok("⭐ segmento 01: 56%-75% («56%-75%»-100%), o nº de keyframes em vermelho", texto(ns[0])[0],
       "FrameFlex · tamanho X · linear · «3» keyframes > 56%-75% («56%-75%»-100%)")
    ok("⭐ segmento 02: 75%-100% (56%-«75%-100%»)", texto(ns[1])[0],
       "FrameFlex · tamanho X · linear · «3» keyframes > 75%-100% (56%-«75%-100%»)")
    ok("FrameFlex animado não se traduz: cor 'refazer'", ns[0]["cor"], "refazer")
    dois = {**ff, "params": {**ff["params"], "keyframes_avid": {"AFX_SPATIAL_FRAMING_WID": [(0, 56), (120, 100)]}}}
    ok("⭐ só dois keyframes: 56%-100%, sem parênteses", texto(notas(seg(efeitos=[dois]))[0])[0],
       "FrameFlex · tamanho X · linear · «2» keyframes > 56%-100%")
    espera = {**ff, "params": {**ff["params"], "keyframes_avid": {"AFX_SPATIAL_FRAMING_WID": [(30, 56), (90, 100)]}}}
    ok("antes do 1º keyframe: 'parado em', e depois do último também",
       [texto(n)[0].split("keyframes > ")[1] for n in notas(seg(efeitos=[espera]))],
       ["parado em 56%", "56%-100%", "parado em 100%"])
    curva = {**ff, "params": {**ff["params"], "interp_avid": {"AFX_SPATIAL_FRAMING_WID": "Bezier"}}}
    ns = notas(seg(efeitos=[curva]))
    ok("⭐ NÃO linear: uma nota só, sem cortar nos keyframes", [(n["inicio"], n["dur"]) for n in ns], [(240, 120)])
    ok("⭐ …o tipo da curva e só o 1º e o último valor", texto(ns[0])[0],
       "FrameFlex · tamanho X · bezier · «3» keyframes > 56% > 100%")
    neg = {**ff, "params": {**ff["params"], "keyframes_avid": {"AFX_SPATIAL_FRAMING_WID": [(0, 0), (60, -15), (120, -30)]}}}
    ok("⭐ valor negativo separa com '>', nunca com seta", texto(notas(seg(efeitos=[neg]))[0])[0],
       "FrameFlex · tamanho X · linear · «3» keyframes > 0% > -15% («0% > -15%» > -30%)")
    junto = {**ff, "params": {**ff["params"], "keyframes_avid": {"AFX_SPATIAL_FRAMING_WID": [(0, 56), (40, 60), (43, 70), (120, 100)]}}}
    ok("keyframes a menos de 6 quadros se juntam (sem nota de 3 quadros)",
       [n["dur"] for n in notas(seg(efeitos=[junto]))], [40, 80])
    warp = {"name": "EFF2_SBLEND", "category": "geometric", "reproducible": True,
            "params": {"animated": True, "pos_x": 10, "keyframes_avid": {"DVE_POS_X_U": [(0, 10), (120, 90)]}}}
    ok("3D Warp animado (traduzido no 1º quadro): cor 'conferir'", notas(seg(efeitos=[warp]))[0]["cor"], "conferir")

    print("\n── 2. o que não anima ──")
    est = {"name": "EFF2_STABILIZE", "category": "other", "reproducible": False,
           "params": {"zoom_pct": 104.28, "auto_zoom": True, "rastreado": True}}
    n = notas(seg(efeitos=[est]))[0]
    ok("⭐ estabilizador: a nota e o zoom", texto(n), ["ESTABILIZADO NO AVID · Stabilize · zoom 104,3%"])
    ok("…cor 'refazer'", n["cor"], "refazer")
    cor = {"name": "EFF2_RGB_COLOR_CORRECTION", "category": "color", "reproducible": False, "params": {}}
    ok("cor: 'conferir'", (texto(notas(seg(efeitos=[cor]))[0]), notas(seg(efeitos=[cor]))[0]["cor"]),
       (["COR NO AVID · Color Correction"], "conferir"))
    tc = {"name": "169317AB-ACAA-416F-84CE-249BFE0B09ED", "category": "other", "reproducible": False,
          "params": {}, "label": "Timecode Burn-In"}
    ok("plugin: o nome que ele declara na bin", texto(notas(seg(efeitos=[tc]))[0]),
       ["EFEITO NÃO TRADUZIDO · Timecode Burn-In"])
    g = {"name": "EFF2_SBLEND", "category": "geometric", "reproducible": True,
         "params": {"pos_x": 40.0, "pos_y": 32.0, "scale_x": 1.2, "scale_y": 1.2}}
    n = notas(seg(efeitos=[g]))[0]
    ok("traduzido: a nota com os números, sem cor", (texto(n), n["cor"]),
       (["3D WARP · posição 40, 32 · escala 120%"], None))
    ok("clipe sem efeito: nenhuma nota", notas(seg()), [])
    # A 1ª linha diz de QUEM é a nota (autor, 2026-10-06: clipes sobrepostos davam notas iguais).
    v1 = notas(seg(efeitos=[g], clip_name="C0001.MP4", track=1))[0]
    v4 = notas(seg(efeitos=[g], clip_name="C0003.MP4", track=4))[0]
    ok("⭐ a cabeça: 'V1 <nome do clipe>' e 'V4 …'", (cabeca(v1), cabeca(v4)), ("V1 C0001.MP4", "V4 C0003.MP4"))
    ok("…e o nome do clipe na timeline começa por ela", v4["nome"].startswith("V4 C0003.MP4 | 3D WARP"), True)
    ok("⭐ cabeca_info: trilha, nome e tipo (sem TC da mídia, sem TC source)",
       v4["cabeca_info"], {"trilha": "V4", "nome": "C0003.MP4", "tipo": "video", "src": None})
    avid = notas(seg(efeitos=[g], source_start_frames=48), masters={"m1": {"identidade": {"tc_inicio": 24 * 3600, "tc_fps": 24}}})
    ok("⭐ TC source in > out pelo master do Avid (TC de início + entrada; 120 quadros)",
       avid[0]["cabeca_info"]["src"], ("01:00:02:00", "01:00:07:00"))
    pr = notas(seg(efeitos=[g], source_start_frames=24, prproj={"midia": {"tc_quadros": 25 * 10, "fps": 25}}))
    ok("…e pelo Media do projeto do Premiere (25 q/s)", pr[0]["cabeca_info"]["src"], ("00:00:10:24", "00:00:15:19"))
    tit = {"name": "Titler", "category": "title", "params": {}}
    ok("tipo do clipe: título, ajuste, composto",
       [notas(seg(efeitos=[g, tit]))[0]["cabeca_info"]["tipo"], notas(seg(efeitos=[g], ajuste={"x": 1}))[0]["cabeca_info"]["tipo"],
        notas(seg(efeitos=[g], composto={"id": 1}))[0]["cabeca_info"]["tipo"]], ["titulo", "ajuste", "composto"])
    # O Motion do Premiere vem em todo clipe (2026-10-06): neutro não é nota; mexido, é.
    mot = lambda **p: {"name": "Motion", "category": "geometric", "reproducible": True,  # noqa: E731
                       "params": {"pos_x": 0.0, "pos_y": 0.0, "scale_x": 1.0, "scale_y": 1.0, **p}}
    ok("⭐ Premiere: o Motion NEUTRO não vira nota", notas(seg(efeitos=[mot()])), [])
    ok("…o Motion com escala vira", texto(notas(seg(efeitos=[mot(scale_x=1.06, scale_y=1.06)]))[0]),
       ["MOTION · posição 0, 0 · escala 106%"])
    g0 = {"name": "EFF2_SBLEND", "category": "geometric", "reproducible": True,
          "params": {"pos_x": 0.0, "pos_y": 0.0, "scale_x": 1.0, "scale_y": 1.0}}
    ok("…e no Avid o efeito neutro continua nota (o editor o pôs)", len(notas(seg(efeitos=[g0]))), 1)
    ok("clipe desligado: nenhuma nota", notas(seg(efeitos=[est], disabled=True)), [])
    # O que o app TRADUZ do Premiere (PRODC, 2026-10-23): saía "EFEITO NÃO TRADUZIDO" e o nome em vermelho de refazer.
    pr = lambda nome, cat: {"name": nome, "category": cat, "reproducible": True, "params": {}}  # noqa: E731
    n = notas(seg(efeitos=[pr("Lumetri (LUT no nó)", "lut"), pr("Máscara de opacidade (Fusion)", "fusion"),
                           pr("Black & White", "cor"), pr("Adjustment Clip", "ajuste")]))[0]
    ok("⭐ Premiere traduzido: a nota registra 'traduzido', o nome como veio, SEM cor",
       (texto(n), n["cor"]),
       (["Lumetri (LUT no nó) · traduzido", "Máscara de opacidade (Fusion) · traduzido", "Black & White · traduzido"], None))
    ok("…e o que o app NÃO reproduz continua 'não traduzido' + refazer",
       notas(seg(efeitos=[{**pr("Plugin X", "other"), "reproducible": False}]))[0]["cor"], "refazer")
    ok("⭐ velocidade que arredonda para 100% (0,99999; 0,998) não é nota",
       [notas(seg(motion_class="conform+creative", relative_speed=r)) for r in (0.9999999999999916, 0.9976899402917085)], [[], []])

    print("\n── 2b. Stretch e velocidade (o teste do autor com a PRODA, 2026-09-27) ──")
    praia = {"m1": {"identidade": {"largura": 2048, "altura": 1080}}}
    n = notas(seg(reframe_mode="stretch"), masters=praia)[0]
    ok("⭐ Stretch: a 1ª linha da descrição (o nome do marcador) é o alerta, em vermelho",
       n["linhas"][n["cabeca"]],
       [("STRETCH: POSSÍVEL DISTORÇÃO DA IMAGEM", True)])
    ok("…com o raster da mídia e o que fazer", texto(n)[1],
       "Reformat Stretch no Avid · mídia 2048x1080 (1,9:1): conferir e avisar a produção")
    ok("⭐ …e o sinal próprio, 'distorcao'", n["cor"], "distorcao")
    ok("os outros modos NÃO avisam (Pillarbox, Crop, Keep Size)",
       [notas(seg(reframe_mode=m), masters=praia) for m in ("pillarbox", "center_crop", "keep_size")], [[], [], []])
    lenta = seg(motion_class="creative", speed_ratio=79 / 68, relative_speed=79 / 68)
    ok("⭐ velocidade: o % como o Avid mostra (79/68 → 86%), cor 'conferir'",
       (texto(notas(lenta)[0]), notas(lenta)[0]["cor"]), (["VELOCIDADE 86% (câmera lenta)"], "conferir"))
    ok("acelerado (262/209 → 125%)",
       texto(notas(seg(motion_class="creative", relative_speed=209 / 262))[0]), ["VELOCIDADE 125% (acelerado)"])
    ok("conformação de fps NÃO é velocidade do editor", notas(seg(motion_class="conform", relative_speed=1.0)), [])
    ok("freeze", texto(notas(seg(motion_class="freeze"))[0]), ["FREEZE FRAME"])
    n = notas(seg(reframe_mode="stretch", motion_class="creative", relative_speed=79 / 68, efeitos=[est]),
              masters=praia)[0]
    ok("⭐ Stretch + velocidade + estabilizador: o Stretch no topo e manda na cor",
       (texto(n)[0], texto(n)[2], texto(n)[3], n["cor"]),
       ("«STRETCH: POSSÍVEL DISTORÇÃO DA IMAGEM»", "VELOCIDADE 86% (câmera lenta)",
        "ESTABILIZADO NO AVID · Stabilize · zoom 104,3%", "distorcao"))

    print("\n── 3. rampa: só o 1º e o último valor (autor, 2026-10-23) ──")
    rampa = seg(dur=4, motion_class="ramp", motion_effect_type="ramp", source_start_frames=10,
                source_offset_map=[(0, 0), (1, 2), (2, 3), (3, 3.5), (4, 3.75)])
    ns = notas(rampa, masters={"m1": {"identidade": {"tc_inicio": 24 * 3600, "tc_fps": 24}}})
    ok("⭐ UMA nota no segmento inteiro (acabou o Text por quadro)", [(n["inicio"], n["dur"]) for n in ns], [(240, 4)])
    ok("⭐ a velocidade do 1º e do último instante, 'RAMPA' na cor da rampa",
       ns[0]["linhas"][1], [("RAMPA DE VELOCIDADE", "rampa"), (" · 200% > 25%", False)])

    print("\n── 4. o writer: UMA trilha de Text+, desligada; as notas que se tocam num clipe só ──")
    from drp import notas_textplus as NT
    from drp.writer import build_drt
    from titulos.textplus import ler_composicao

    def escrever(lista):
        with tempfile.TemporaryDirectory() as d:
            saida = os.path.join(d, "t.drt")
            r = build_drt([], [], saida, timeline_name="T", timeline_fps=24.0, notas=lista)
            with zipfile.ZipFile(saida) as z:
                x = z.read(next(n for n in z.namelist() if "SeqContainer" in n)).decode("utf-8")
        vtv = re.search(r"<VideoTrackVec>.*?</VideoTrackVec>", x, re.DOTALL).group(0)
        faixas = [t for t in re.findall(r"<Sm2TiTrack\b.*?</Sm2TiTrack>", vtv, re.DOTALL) if "<CompositionBA>" in t]
        return r, faixas

    a = N._nota(240, 48, [[("NOTA A", False)]], "refazer")
    b = N._nota(260, 48, [[("NOTA B", False)]], None)          # sobrepõe A
    c = N._nota(400, 24, [[("NOTA C ", False), ("vermelho", True)]], None)   # sozinha, depois
    r, faixas = escrever([a, b, c])
    ok("três notas escritas", r["notas"], 3)
    ok("⭐ UMA trilha de notas (variante B: nada de trilha nova por sobreposição)", len(faixas), 1)
    clipes = re.findall(r"<Sm2TiVideoClip\b.*?</Sm2TiVideoClip>", faixas[0], re.DOTALL)
    ok("⭐ A e B (que se tocam) num clipe só; C noutro", [re.search(r"<Name>([^<]*)", k).group(1) for k in clipes],
       ["NOTA A || NOTA B", "NOTA C vermelho"])
    ok("…o clipe do grupo vai do início de A ao fim de B (240 a 308)",
       [(int(re.search(r"<Start>(\d+)", k).group(1)), int(re.search(r"<Duration>(\d+)", k).group(1))) for k in clipes][0][1], 68)
    ok("⭐ a TRILHA de notas desligada (não sai no render)", re.search(r"<Flags>(\d+)</Flags>", faixas[0]).group(1), "2")
    _cab, tools = ler_composicao(re.search(r"<CompositionBA>(\w+)<", clipes[0]).group(1))
    ok("⭐ cada nota é uma camada que liga e desliga (Blend em degraus) e sobe quando a de cima acaba",
       ("M1Blend" in tools or "M2Blend" in tools, "N2CY = BezierSpline" in tools), (True, True))
    _cab, tools_c = ler_composicao(re.search(r"<CompositionBA>(\w+)<", clipes[1]).group(1))
    ok("o trecho em vermelho no Character Level Styling (R=1, G e B=0,33)", "{ 2402, 7, 14, Value = 0.33 }" in tools_c, True)

    # A nota de verdade (das_notas): cabeça com trilha, nome na cor do SINAL e TC source; colunas.
    est = {"name": "EFF2_STABILIZE", "category": "other", "reproducible": False, "params": {"zoom_pct": 112}}
    nota = notas(seg(efeitos=[est], clip_name="A001C003", source_start_frames=48),
                 masters={"m1": {"identidade": {"tc_inicio": 24 * 3600, "tc_fps": 24}}})[0]
    cam = NT.camadas(nota)
    ok("⭐ cabeça: rótulo da trilha, nome na cor do TIPO mesmo com sinal (o vermelho é do offline), TC em cinza",
       (cam[0]["rotulo"], cam[0]["trechos"]),
       ("V1", [("A001C003", "video"), ("  ", "branco"), ("01:00:02:00 > 01:00:07:00", "tc")]))
    ok("…o corpo sem rótulo (nada embaixo do rótulo da trilha)", [l["rotulo"] for l in cam[1:]], [None])
    xr, xc = NT._colunas(cam)
    ok("⭐ COLUNAS: o nome e o corpo começam depois do rótulo 'V1 ' (medido pela fonte)",
       (round(xr[0], 4), round(xc[0] - xr[0], 4)), (round(80 / 1920, 4), round(NT.largura("V1 "), 4)))
    sem_sinal = NT.camadas({**nota, "cor": None})
    ok("sem sinal, o nome na cor do TIPO do clipe", sem_sinal[0]["trechos"][0][1], "video")
    ok("⭐ só caracteres comuns: seta, vezes e travessão viram '>', 'x', '-'",
       NT._texto_seguro("0 → -15 · 2048×1080 — ok ‖ ✓"), "0 > -15 · 2048x1080 - ok || ")

    # O COMPOUND (nest do Premiere, autor 2026-10-23): os clipes de dentro entram recuados na nota do compound.
    comp = {"id": "2:100", "nome": "ABERTURA_CMP"}
    dentro = [seg(tc_in="00:00:10:00", dur=48, track=2, efeitos=[est], clip_name="A003C001", composto=comp),
              seg(tc_in="00:00:10:00", dur=48, track=3, efeitos=[g], clip_name="LOGO", composto=comp),
              seg(tc_in="00:00:10:00", dur=48, track=1, efeitos=[g], clip_name="FORA")]
    ns = notas(*dentro)
    aninhadas = NT.aninhar(ns, dentro)
    cn = next(n for n in aninhadas if n.get("filhos"))
    ok("⭐ uma nota do compound + a de fora; os de dentro não ficam soltos", len(aninhadas), 2)
    ok("⭐ cabeça do compound na trilha mais BAIXA do grupo (onde o Resolve o deixa), cor de composto",
       (cn["cabeca_info"]["trilha"], cn["cabeca_info"]["nome"], cn["cabeca_info"]["tipo"]), ("V2", "ABERTURA_CMP", "composto"))
    cam = NT.camadas(cn)
    ok("⭐ os de dentro recuados: V2.1 e V2.2, nível 1, de baixo para cima",
       [(l["nivel"], l["rotulo"]) for l in cam if l["rotulo"]], [(0, "V2"), (1, "V2.1"), (1, "V2.2")])
    ok("…o de dentro com sinal também fica na cor do tipo (o sinal vai no corpo dele)",
       (cam[0]["trechos"][0][1], next(l for l in cam if l["rotulo"] == "V2.1")["trechos"][0][1]), ("composto", "video"))
    xr, xc = NT._colunas(cam)
    ok("⭐ COLUNAS: o rótulo de dentro começa na coluna do nome de fora", round(xr[1], 6), round(xc[0], 6))
    # TC source em TODO segmento (autor, 2026-10-23): o .prproj sem o TC do arquivo → o TC que o pool recebe do arquivo.
    from drp.writer import _com_nome_do_arquivo
    sem = notas(seg(efeitos=[g], source_start_frames=10702, dur=17, source_fps=100.0, clip_name="LOU_7310.mov"))
    ok("sem o TC da mídia, a leitura não inventa", sem[0]["cabeca_info"]["src"], None)
    s0 = seg(efeitos=[g], source_start_frames=10702, dur=17, source_fps=100.0)
    com = _com_nome_do_arquivo(sem, {0: "LOU_7310.mov"}, {0: (100.0, "18:38:38:18")}, [s0])
    ok("⭐ o writer completa pelo TC do ARQUIVO (100 q/s, conferido no pool do Resolve: 18:40:25:20)",
       com[0]["cabeca_info"]["src"], ("18:40:25:20", "18:40:25:37"))
    ok("⭐ o nome do arquivo na cabeça vai SEM a extensão (autor, 2026-10-24)", com[0]["cabeca_info"]["nome"], "LOU_7310")
    ok("…arquivo sem TC conta de 00:00:00:00, como o Resolve",
       _com_nome_do_arquivo(sem, {}, {0: (25.0, None)}, [s0])[0]["cabeca_info"]["src"][0], "00:07:08:02")
    ok("…e o offline (arquivo não lido) fica sem TC", _com_nome_do_arquivo(sem, {}, {0: (None, None)}, [s0])[0]["cabeca_info"]["src"], None)
    s_off = {**s0, "media_ref": {"local_path": r"D:\\MIDIA\\LOU_7310.mov"}}
    off = _com_nome_do_arquivo(sem, {}, {0: (None, None)}, [s_off])
    ok("⭐ mídia OFFLINE: o nome na cabeça sai VERMELHO (autor, 2026-10-24)",
       NT.camadas(off[0])[0]["trechos"][0][1], "offline")
    # o .prproj sem os originais: o casamento devolve o caminho que o projeto declara, que NÃO está no disco (PRODC no
    # Mac, 2026-10-24: 79 vídeos offline no Resolve e o nome saía branco)
    aus = _com_nome_do_arquivo(sem, {0: "LOU_7310.mov"}, {0: (None, None)}, [s0], ausentes={0})
    ok("⭐ arquivo casado AUSENTE do disco: o nome também sai VERMELHO", NT.camadas(aus[0])[0]["trechos"][0][1], "offline")
    ok("…e a achada não", NT.camadas(_com_nome_do_arquivo(sem, {0: "LOU_7310.mov"}, {}, [s_off])[0])[0]["trechos"][0][1],
       "video")
    ok("…o de dentro SEM sinal é vídeo (branco), não 'composto' (lilás)",
       next(l for l in cam if l["rotulo"] == "V2.2")["trechos"][0][1], "video")
    ok("…e os marcadores continuam por clipe (a lista dos Sinais não muda)", [n["segmento"] for n in ns], [0, 1, 2])
    _r, faixas = escrever([nota])
    _cab, tools = ler_composicao(re.search(r"<CompositionBA>(\w+)<", faixas[0]).group(1))
    ok("⭐ no Text+: o rótulo 'V1' e a linha da cabeça como Text+ separados (colunas)",
       ('Value = "V1"' in tools, 'Value = "A001C003  01:00:02:00 > 01:00:07:00"' in tools), (True, True))
    ok("…e nenhum caractere fora da fonte na composição inteira",
       all(c in NT._LARGURA or c in "\\{}" or ord(c) < 32 or c.isascii() for c in tools), True)

    print("\n── 5. marcador de timeline e cor LOCAL (a PRODA real) ──")
    from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
    cruz = Path(raiz_das_amostras()) \
        / "02 PROJETOS AVID" / "PRODUCAO-A" / "03_OC_EDIT VALENDO.avb"
    if not cruz.is_file():
        print(f"  PULADO — {cruz} não está neste disco")
    else:
        from avb_bin import segmentos as S
        from avb_export.reader import topen
        from drp import sinais as SN
        from drp.ba_mapa import ler_mapa
        import zstandard
        with topen(str(cruz)) as f:
            leitura = S.ler_timeline(f, next(iter(S.sequencias(f))))
        lista = N.das_notas(leitura)
        with tempfile.TemporaryDirectory() as d:
            segs, casados, metas = S.montar_midia(leitura, {}, d, {}, {})
            saida = os.path.join(d, "t.drt")
            r = build_drt(segs, casados, saida, timeline_name="T", timeline_fps=23.976,
                          offline=metas, sinais=lista, marcar=True, colorir=True)
            with zipfile.ZipFile(saida) as z:
                px = z.read("project.xml").decode("utf-8")
                seq = z.read(next(n for n in z.namelist() if "SeqContainer" in n)).decode("utf-8")
                pool = z.read(next(n for n in z.namelist() if n.endswith("Master/MpFolder.xml"))).decode("utf-8")
        esperado = len({n["inicio"] for n in lista if n["cor"] or n.get("marcar")})
        # 7 cores + 9 Stretch (os takes da praia) + 2 velocidades, e um segmento da praia tem Stretch E
        # velocidade (00:00:26:03): 17 segmentos. O Resolve guarda UM marcador por quadro (727ff23): dois
        # Stretch em V1 e V2 começam juntos em 00:09:07:09 (medido no Windows, 2026-10-03) e viram um
        # marcador só — 16. Os 2 estabilizadores: a estabilização vai PRONTA ao Resolve e a nota fica sem cor,
        # como as outras traduções, mas o MARCADOR de conferir volta (autor, 2026-10-24) — 18, sem pintar o clipe.
        ok("um marcador por QUADRO que pede atenção (17 segmentos + 2 estabilizações em 18 quadros)",
           (r["marcadores"], esperado), (18, 18))
        ok("⭐ e a cor local nos mesmos 17 segmentos", r["segmentos_coloridos"], 17)
        ok("⭐ os 2 estabilizadores vão no plano do estabilizador do Resolve (pela BIN)",
           [(x["trilha"], len(x["u"])) for x in r["estabilizar"]], [(1, 393), (2, 203)])
        praias = [n for n in lista if n["cor"] == "distorcao"]
        ok("⭐ os 9 Stretch são todos takes da praia",
           (len(praias), all("Praia" in leitura["segments"][n["segmento"]]["clip_name"]
                             or "Paraia" in leitura["segments"][n["segmento"]]["clip_name"] for n in praias)),
           (9, True))
        # O `BlobData` da cor local termina no protobuf `campo 5 = cor` (0x28, Pink = 10).
        cores = re.findall(r"<Sm2TiItemLockableBlob\b.*?<FieldsBlob>(\w+)</FieldsBlob>", px, re.DOTALL)
        ok("…pintados de Pink (a cor que nenhum outro sinal usa)",
           sum(fb.endswith("80%02x%02x" % (0x28, SN.COR_DE_CLIPE["Pink"])) for fb in cores), 9)
        donos = re.findall(r"<Sm2TiItemLockableBlob\b.*?<BlobOwner>([^<]+)</BlobOwner>", px, re.DOTALL)
        clipes = set(re.findall(r'<Sm2TiVideoClip DbId="([^"]+)"', seq))
        ok("⭐ cada cor aponta para um clipe de VÍDEO que existe na timeline", all(d in clipes for d in donos), True)
        fb = re.search(r"<Sm2SequenceLockableBlob\b.*?<FieldsBlob>(\w+)</FieldsBlob>.*?<BlobOwner>([^<]+)",
                       px, re.DOTALL)
        ok("o bloco dos marcadores é da Sm2Sequence", fb.group(2) in pool, True)
        _v, itens, _r = ler_mapa(bytes.fromhex(fb.group(1)))
        dados = zstandard.ZstdDecompressor().decompress(itens[0][1][2][9:], max_output_size=1 << 20)
        ok("⭐ a estabilização traduzida vira marcador (e a antiga 'ESTABILIZADO NO AVID' não)",
           ("ESTABILIZAÇÃO TRADUZIDA".encode("utf-8") in dados, b"ESTABILIZADO NO AVID" in dados, b"DLPC" in dados),
           (True, False, True))
        estab = [n for n in lista if n.get("marcar")]
        ok("⭐ …na cor de CONFERIR, e a nota e o clipe sem cor",
           (len({n["segmento"] for n in estab}), {n["marcar"] for n in estab}, {n["cor"] for n in estab}),
           (2, {"conferir"}, {None}))
        # Fuchsia = 512 → varint 0x80 0x04 (o Resolve pula o 256).
        ok("⭐ o Stretch vira marcador FUCHSIA com o alerta no nome",
           ("STRETCH: POSSÍVEL DISTORÇÃO".encode("utf-8") in dados, b"\x08\x80\x04" in dados), (True, True))
        ok("a velocidade vira marcador com o % do Avid", b"VELOCIDADE 86% (c" in dados, True)
        ok("…e os marcadores herdados do esqueleto (os 23 da PRODA de 2025) não voltam",
           px.count("<Sm2SequenceLockableBlob"), 1)
        # A cabeça da nota com o nome do ARQUIVO do clipe, não o do subclipe (autor, 2026-10-23: subclipe e multicam
        # se desfazem na viagem). O 1º plano da PRODA é o subclipe "11_Praia-Personagem F Parada…" do B001_03150131_C011.
        from titulos.textplus import ler_composicao
        with tempfile.TemporaryDirectory() as d:
            segs, casados, metas = S.montar_midia(leitura, {}, d, {}, {})
            saida = os.path.join(d, "t.drt")
            build_drt(segs, casados, saida, timeline_name="T", timeline_fps=23.976, offline=metas, notas=lista)
            with zipfile.ZipFile(saida) as z:
                seq = z.read(next(n for n in z.namelist() if "SeqContainer" in n)).decode("utf-8")
        tp = [k for k in re.findall(r"<Sm2TiVideoClip\b.*?</Sm2TiVideoClip>", seq, re.DOTALL) if "<CompositionBA>" in k]
        _h, tools = ler_composicao(re.search(r"<CompositionBA>(\w+)<", tp[0]).group(1))
        ok("⭐ a cabeça com o nome do ARQUIVO, não o do subclipe",
           ("B001_03150131_C011  01:32:06:17 > 01:32:17:18" in tools, "11_Praia" in tools), (True, False))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
