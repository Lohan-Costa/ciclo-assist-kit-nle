"""Títulos Avid → Resolve (Carta 1.2): o título chega como título, não como buraco.

Rodar:

    .venv-win/Scripts/python tests/test_titulos.py

O critério forte é o do Resolve: o texto rico que o writer monta a partir do MODELO NEUTRO
(o bloco `titulo` da Carta) tem de ser, byte a byte, o que o Resolve 19 gravou quando o autor
fez a mesma variação à mão (`TEXT MAPEAMENTO corrigido.drt`, 2026-09-27). As referências estão
aqui dentro para o teste não depender do disco `S:`.

Com a pasta de testes no disco (`DLPC_AMOSTRAS`, caso `T01 TITLER PLUS 19 VARIACOES`), as
19 variações do Titler+ também passam pelo leitor da bin; sem ela, essa parte é PULADA.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import zstandard  # noqa: E402

from titulos import avid, mqp  # noqa: E402
from titulos import resolve as R  # noqa: E402

#: A pasta de testes (organizada em 2026-09-27; `LEIA-ME.md` na raiz dela). Viaja entre as
#: máquinas: a variável `DLPC_AMOSTRAS` aponta a raiz; sem ela, o lugar de sempre no Windows.
from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
AMOSTRAS = Path(raiz_das_amostras())
EXEMPLOS = AMOSTRAS / "03 CASOS" / "TITULOS" / "T01 TITLER PLUS 19 VARIACOES" / "avid" / "TITLE EXEMPLOS.avb"

#: O texto rico (parâmetro 15) que o Resolve 19 gravou em cada variação.
RESOLVE = {
    "T01 BASE": "760000000bb100000a0000006200610060000f00000008000000010000003804001e000000140000005400300031002000420041005300450002000000010037000000160000004f00700065006e002000530061006e0073000000c042043f00120000002300660066006600660066006600ecf71e03",
    "LINHA": "d90000000bb100000e00000062006100610060006000130000000c000000010000000200000038040020000000160000004c0049004e0048004100200055004d00200003000000010022000000180000004c0049004e0048004100200044004f004900530004000000010037000000160000004f00700065006e002000530061006e0073000000c042043f00120000002300660066006600660066006600ecf71e0337000000160000004f00700065006e002000530061006e0073000000c042043f00120000002300660066006600660066006600ecf71e03",
    "T10 BOLD": "820000000bb100000a0000006200610060000f00000008000000010000003804001e00000014000000540031003000200042004f004c00440002000000010043000000160000004f00700065006e002000530061006e0073000000c0420c00000042006f006c006400044b00120000002300660066006600660066006600e8f71e03",
    "T11 ITALICO": "8b0000000bb100000a0000006200610060000f0000000800000001000000380400240000001a00000054003100310020004900540041004c00490043004f0002000000010046000000160000004f00700065006e002000530061006e0073000000c042100000004900740061006c00690063000401120000002300660066006600660066006600e8ef1e03",
    "T12 VERMELHO": "900000000bb100000a0000006200610060000f0000000800000001000000380400260000001c00000054003100320020005600450052004d0045004c0048004f0002000000010049000000160000004f00700065006e002000530061006e0073000000c042043f00120000002300660066003000300030003000120000002300660066003000300030003000ecf71603",
    "T18 BORDA": "8e0000000bb100000a0000006200610060000f00000008000000010000003804002000000016000000540031003800200042004f005200440041000200000001004d000000160000004f00700065006e002000530061006e0073000000c042043f00120000002300660066006600660066006600120000002300300030006600660030003000000000c1ecf70603",
    "DIREITA": "d70000000bb100000e00000062006100610060006000130000000c0000000100000002000000380400240000001a00000041004c0049004e00480041004d0045004e0054004f000300000001001c00000012000000440049005200450049005400410004000000010037000000160000004f00700065006e002000530061006e0073000000c042023f00120000002300660066006600660066006600ecf71e0337000000160000004f00700065006e002000530061006e0073000000c042023f00120000002300660066006600660066006600ecf71e03",
    "T09 ARIAL REGULAR": "840000000bb100000a0000006200610060000f0000000800000001000000380400240000001a000000540030003900200046004f004e00540045002d0042000200000001003f0000000e00000041007200690061006c000000c0421200000052006500670075006c006100720004120000002300660066006600660066006600e8ff1e03",
}


# ── protobuf de leitura (só para conferir o que o writer escreveu) ──────────────────────────

def _varint(b: bytes, i: int):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def _pb(b: bytes) -> list:
    i, fora = 0, []
    while i < len(b):
        k, i = _varint(b, i)
        f, w = k >> 3, k & 7
        if w == 0:
            v, i = _varint(b, i)
        elif w == 1:
            v, i = b[i:i + 8], i + 8
        elif w == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        else:
            raise ValueError(w)
        fora.append((f, v))
    return fora


def _filtros(efb: bytes) -> dict:
    corpo = zstandard.ZstdDecompressor().decompress(efb[9:], max_output_size=1 << 22)
    return {_pb(v)[0][1]: [x for f, x in _pb(v) if f == 9] for _f, v in _pb(corpo)}


def _rico(efb: bytes) -> str:
    p15 = _filtros(efb)[48][0]
    return dict(_pb(dict(_pb(dict(_pb(p15))[3]))[1]))[8].hex()


def titulo(texto, **caixa) -> dict:
    base = {"texto": texto, "fonte": {"familia": "Open Sans", "estilo": ""}, "corpo": 0.0833333,
            "cor": [1, 1, 1], "alinhamento": "centro", "posicao": {"x": 0, "y": -0.02946},
            "contorno": None, "sombra": None}
    base.update(caixa)
    return {"titulador": "Avid Titler+", "estilo_lido": True, "caixas": [base], "fundo": None}


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

    print("── 1. o texto rico, do modelo neutro ao byte do Resolve ──")
    feitos = {
        "T01 BASE": titulo("T01 BASE"),
        "LINHA": titulo("LINHA UM \nLINHA DOIS"),
        "T10 BOLD": titulo("T10 BOLD", fonte={"familia": "Open Sans", "estilo": "Bold"}),
        "T11 ITALICO": titulo("T11 ITALICO", fonte={"familia": "Open Sans", "estilo": "Italic"}),
        "T12 VERMELHO": titulo("T12 VERMELHO", cor=[1, 0, 0]),
        "T18 BORDA": titulo("T18 BORDA", contorno={"cor": [0, 1, 0], "espessura": 8}),
        "DIREITA": titulo("ALINHAMENTO\nDIREITA", alinhamento="direita"),
        "T09 ARIAL REGULAR": titulo("T09 FONTE-B", fonte={"familia": "Arial", "estilo": "Regular"}),
    }
    for nome, t in feitos.items():
        efb, _avisos = R.efeitos_do_texto(t)
        ok(f"⭐ {nome}: idêntico ao que o Resolve gravou", _rico(efb), RESOLVE[nome])

    # Duas cores na MESMA linha ("Basic " branco + "Title" #ff557f, feito pelo autor no Resolve,
    # `text com duas cores.drt`): cada trecho com o seu formato; `04 01` = continua na linha.
    duas = ("db0000000bb100000e00000062006100610060006000130000000c00000001000000020000003804001a"
            "00000010000000420061007300690063002000030000000401180000000e0000005400690074006c0065"
            "0004000000010037000000160000004f00700065006e002000530061006e0073000000c042043f001200"
            "00002300660066006600660066006600ecf71e0349000000160000004f00700065006e00200053006100"
            "6e0073000000c042043f00120000002300660066003500350037006600120000002300660066003500350"
            "037006600ecf71603")
    ok("⭐ duas cores na mesma linha: idêntico ao que o Resolve gravou", R.texto_rico_trechos([
        ("Basic ", R.formato("Open Sans", 96.0, "#ffffff", peso=63), False),
        ("Title", R.formato("Open Sans", 96.0, "#ff557f", peso=63, cor2="#ff557f"), True)]).hex(), duas)

    print("\n── 2. o resto do Text: posição, sombra, contorno, caixa ──")
    efb, _ = R.efeitos_do_texto(titulo("X", posicao={"x": -0.607333, "y": 0.415667}))
    import struct
    xy = struct.unpack(">dd", _filtros(efb)[48][3][-16:])
    ok("posição do T14 (canto sup. esq.) → fração do Resolve", tuple(round(v, 3) for v in xy),
       (0.158, 0.945))
    efb, _ = R.efeitos_do_texto(titulo("X"))
    ok("posição padrão do Avid = centro do Resolve (posição vazia)", _filtros(efb)[48][3], b"")
    ok("sem contorno, sem filtro 56", 56 in _filtros(efb), False)
    efb, _ = R.efeitos_do_texto(titulo("X", contorno={"cor": [0, 1, 0], "espessura": 8}))
    ok("⭐ contorno verde 16 = o filtro 56 do Resolve (T18)", [p.hex() for p in _filtros(efb)[56]],
       ["08171a0f0a0d320b01ffff0000ffff00000000", "08181a040a02081022040a0208024800",
        "08ac011a040a022801"])
    efb, av = R.efeitos_do_texto(titulo("X", sombra={"cor": [0, 1, 0], "deslocamento": [0.01, -0.01]}))
    ok("sombra: deslocamento no filtro 16, posição 1", _filtros(efb)[16][1][:8].hex(), "08261a140a123a10")
    ok("…e o aviso de que a cor ficou no padrão", any("sombra" in a for a in av), True)
    t = titulo("X")
    t["fundo"] = {"cor": [0.251, 0.251, 0.251], "opacidade": 1.0, "tela_cheia": True}
    efb, _ = R.efeitos_do_texto(t)
    ok("fundo em tela cheia → caixa 1,0 × 1,0 (decisão do autor)",
       [p[-8:] for p in (_filtros(efb)[54][3], _filtros(efb)[54][4])], [struct.pack("<d", 1.0)] * 2)
    leg = {"titulador": "Avid Titler+ Legacy", "estilo_lido": False,
           "caixas": [{"texto": "producao a", "fonte": {"familia": "", "estilo": ""}, "corpo": None,
                       "cor": None, "alinhamento": "centro", "posicao": None}], "fundo": None}
    efb, av = R.efeitos_do_texto(leg)
    ok("⭐ Legacy: o texto entra, com o estilo padrão do Resolve",
       bytes.fromhex(_rico(efb)).count("PRODUCAO-A".encode("utf-16-le")), 1)
    ok("…e o aviso diz isso", av, ["Avid Titler+ Legacy: texto trazido; o estilo ficou no padrão do Resolve"])

    print("\n── 3. o lado do Avid: MQP e fonte ──")
    ok("'{Open Sans Bold}' → família + face", avid.fonte("{Open Sans Bold}"),
       {"familia": "Open Sans", "estilo": "Bold"})
    ok("'Courier' → sem face", avid.fonte("Courier"), {"familia": "Courier", "estilo": ""})
    ok("'{Open Sans Bold Italic}' → a face composta", avid.fonte("{Open Sans Bold Italic}")["estilo"],
       "Bold Italic")
    sintetico = ("Version = x\nPropCache = {\n"
                 "\tText.Font.Name = {\n\t\tValue = {Open Sans}\n\t}\n\n"
                 "\tTransform.Position.Y = {\n\t\tValue = 0\n\t}\n\n"
                 "\tText.Font.Name = {\n\t\tValue = Courier\n\t}\n\n"
                 "\tTransform.Position.Y = {\n\t\tValue = 0.25\n\t}\n\n"
                 "\tList = {\n\t\tProp = 3:Text.Font.Name\n\t}\n\n"
                 "\tList = {\n\t\tProp = 4:Transform.Position.Y\n\t}\n\n"
                 "}\nScene = {\n\tLayer = {\n\t\tFlow = {\n\t\t\tPropList = 2\n"
                 "\t\t\tJustify = Right\n"
                 "\t\t\tCharacter = {\n\t\t\t\tPropList = 1\n\t\t\t\tCode = A\n\t\t\t}\n"
                 "\t\t\tCharacter = {\n\t\t\t\tPropList = 1\n\t\t\t\tCode = { }\n\t\t\t}\n"
                 "\t\t\tCharacter = {\n\t\t\t\tPropList = 1\n\t\t\t\tCode = 0xA\n\t\t\t}\n"
                 "\t\t\tCharacter = {\n\t\t\t\tPropList = 1\n\t\t\t\tCode = B\n\t\t\t}\n"
                 "\t\t}\n\t}\n}\n")
    m = mqp.ler(sintetico)
    cx = m.caixas[0]
    ok("a caixa aponta a sua lista (posição sobreposta)", m.valor(cx["lista"], "Transform.Position.Y"), "0.25")
    ok("o caractere aponta a dele (fonte sobreposta)", m.valor(1, "Text.Font.Name"), "Courier")
    ok("sem lista, vale o padrão", m.valor(0, "Text.Font.Name"), "{Open Sans}")
    ok("⭐ o texto pelos Code: '{ }' = espaço, '0xA' = nova linha", mqp.texto_da_caixa(cx), "A \nB")
    ok("o alinhamento da caixa", cx["justify"], "Right")

    print("\n── 4. as 19 variações do Titler+ na bin de exemplo ──")
    if not EXEMPLOS.is_file():
        print(f"  PULADO — {EXEMPLOS} não está neste disco")
    else:
        import avb
        tmp = Path(tempfile.mkdtemp()) / "t.avb"
        shutil.copy(EXEMPLOS, tmp)
        lidos = {}
        with avb.open(str(tmp)) as f:
            for i in range(len(f.object_positions)):
                try:
                    o = f.read_object(i)
                except Exception:  # noqa: BLE001
                    continue
                if type(o).__name__ == "TrackEffect" and avid.e_titulo(o):
                    t = avid.ler(o)
                    lidos.setdefault(t["caixas"][0]["texto"], t)
        c = lambda nome: lidos[nome]["caixas"][0]  # noqa: E731
        ok("19 títulos distintos", len(lidos), 19)
        ok("T12: vermelho", c("T12 VERMELHO")["cor"], [1.0, 0.0, 0.0])
        ok("T10: face Bold", c("T10 BOLD")["fonte"], {"familia": "Open Sans", "estilo": "Bold"})
        ok("T08: corpo grande (fração da altura)", c("T08 CORPO-G")["corpo"], 0.166667)
        ok("T14: canto superior esquerdo", c("T14 CANTO-SE")["posicao"], {"x": -0.607333, "y": 0.415667})
        ok("T16: alinhado à esquerda, em duas linhas", (c("T16\nALINH-ESQ")["alinhamento"]), "esquerda")
        ok("T17: sombra verde", c("T17 SOMBRA")["sombra"]["cor"], [0.0, 1.0, 0.0])
        ok("T18: contorno amarelo, 7,5", c("T18 BORDA")["contorno"], {"cor": [1.0, 1.0, 0.0], "espessura": 7.5})
        ok("T19: fundo em tela cheia", lidos["T19 CAIXA"]["fundo"]["tela_cheia"], True)
        ok("RODAPE: duas caixas (TOPO e RODAPE)", [x["texto"] for x in lidos["TOPO"]["caixas"]],
           ["TOPO", "RODAPE"])
        ok("o estilo cru vai junto (sem perdas)", len(lidos["T01 BASE"]["avid"]["mqp"]) > 40000, True)

        # ⭐ O MESMO título pelo AAF (U03 do autor no Mac, 2026-10-01: pelo AAF o título sumia calado).
        aaf_t01 = EXEMPLOS.parent / "TL - TITLE PLUS.aaf"
        if aaf_t01.is_file():
            from aaf.parser import parse_aaf
            pelo_aaf = parse_aaf(str(aaf_t01))
            blocos = [e["params"]["titulo"] for sg in pelo_aaf["segments"] for e in sg.get("effects") or []
                      if e.get("category") == "title" and (e.get("params") or {}).get("titulo")]
            sem_avid = lambda t: {k: v for k, v in t.items() if k != "avid"}  # noqa: E731
            pela_bin = {sem_avid(t)["caixas"][0]["texto"]: sem_avid(t) for t in lidos.values()}
            ok("⭐ pelo AAF: os 19 títulos têm o bloco `titulo`", len(blocos), 19)
            ok("o MQP sem caixas cai para o texto lido (o título não some)",
               [c["texto"] for c in avid.do_aaf("Avid Titler+", ["PRODUCAO-A"], "Sem = { Nada = 1 }")["caixas"]],
               ["PRODUCAO-A"])
            ok("o titulador é o nome da operação do AAF", avid.do_aaf("Avid Title Tool", ["X"])["titulador"],
               "Avid Title Tool")
            ok("⭐ …IGUAIS aos da bin (texto, fonte, corpo, cor, posição, sombra, contorno, fundo)",
               [t["caixas"][0]["texto"] for t in blocos if sem_avid(t) != pela_bin.get(t["caixas"][0]["texto"])], [])

    print("\n── 5. o writer do DRT: o Text na trilha e no quadro do título ──")
    from drp.writer import build_drt
    seg = {"timeline_tc_in": "00:00:30:15", "timeline_tc_out": "00:00:41:20", "duration_frames": 269,
           "source_start_frames": 0, "source_fps": 23.976, "clip_name": avid.EID_LEGACY, "track": 3,
           "mob_id": None, "is_gap": False, "is_transition": False, "is_effect": True, "is_audio": False,
           "disabled": False, "effects": [{"name": avid.EID_LEGACY, "category": "title",
                                           "reproducible": True, "params": {"titulo": leg}}]}
    desligado = {**seg, "disabled": True, "timeline_tc_in": "00:01:00:00"}
    with tempfile.TemporaryDirectory() as d:
        saida = os.path.join(d, "t.drt")
        r = build_drt([seg, desligado], [], saida, timeline_name="T", timeline_fps=23.976)
        ok("um título escrito (o desligado fica de fora, como o vídeo)", r["titulos"], 1)
        sem_texto = {**seg, "timeline_tc_in": "00:02:00:00", "effects": [{"name": "Avid Titler+ Legacy",
                     "label": "Avid Titler+ Legacy", "category": "title", "params": {}}]}
        r2 = build_drt([sem_texto], [], os.path.join(d, "t2.drt"), timeline_name="T", timeline_fps=23.976)
        ok("⛔ título sem texto legível: não entra, mas AVISA (antes sumia calado)",
           (r2["titulos"], any("sem texto legível" in a for a in r2.get("avisos") or [])), (0, True))
        ok("o aviso do Legacy volta ao serviço", len(r["avisos"]), 1)
        with zipfile.ZipFile(saida) as z:
            x = z.read(next(n for n in z.namelist() if "SeqContainer" in n)).decode("utf-8")
        vtv = re.search(r"<VideoTrackVec>.*?</VideoTrackVec>", x, re.DOTALL).group(0)
        trilhas = re.findall(r"<Sm2TiTrack\b.*?</Sm2TiTrack>", vtv, re.DOTALL)
        gerador = re.search(r"<Sm2TiGenerator\b.*?</Sm2TiGenerator>", trilhas[-1], re.DOTALL).group(0)
        ok("⭐ na V3, em 00:00:30:15 (86400 + 735)", re.search(r"<Start>(\d+)", gerador).group(1), "87135")
        ok("com a duração do Avid", re.search(r"<Duration>(\d+)", gerador).group(1), "269")
        efb = bytes.fromhex(re.search(r"<EffectFiltersBA>(\w+)<", gerador).group(1))
        ok("o texto dentro do gerador", "PRODUCAO-A".encode("utf-16-le") in bytes.fromhex(_rico(efb)), True)

        # A V3 da PRODA como a bin a lê: vazio, dissolve de 40 (cutpoint 10), título, dissolve
        # de 40 (cutpoint 30), vazio. No Avid é fade de entrada e de saída do título.
        def trans(tc_in, tc_out, corte):
            return {**seg, "timeline_tc_in": tc_in, "timeline_tc_out": tc_out, "duration_frames": 40,
                    "is_effect": False, "is_transition": True, "cutpoint": corte,
                    "clip_name": "(transition)", "effects": [{"name": "EFF2_BLEND_DISSOLVE",
                                                             "category": "transition"}]}
        vazio = {**seg, "is_effect": False, "is_gap": True, "effects": [], "clip_name": "(gap)"}
        v3 = [{**vazio, "timeline_tc_in": "00:00:00:00", "duration_frames": 775},
              trans("00:00:30:15", "00:00:32:07", 10), seg, trans("00:00:40:04", "00:00:41:20", 30),
              {**vazio, "timeline_tc_in": "00:00:40:04", "duration_frames": 8587}]
        r = build_drt(v3, [], saida, timeline_name="T", timeline_fps=23.976)
        with zipfile.ZipFile(saida) as z:
            x = z.read(next(n for n in z.namelist() if "SeqContainer" in n)).decode("utf-8")
        vtv = re.search(r"<VideoTrackVec>.*?</VideoTrackVec>", x, re.DOTALL).group(0)
        trilha = re.findall(r"<Sm2TiTrack\b.*?</Sm2TiTrack>", vtv, re.DOTALL)[-1]
        itens = re.findall(r"<(Sm2TiGenerator|Sm2TiTransition)\b.*?<Start>(\d+)</Start>", trilha, re.DOTALL)
        ok("⭐ fade de entrada, título, fade de saída (a ordem na V3)",
           [k for k, _ in itens], ["Sm2TiTransition", "Sm2TiGenerator", "Sm2TiTransition"])
        ok("o fade de entrada começa com o título; o de saída termina com ele",
           [int(st) for _, st in itens], [87135, 87135, 87135 + 269 - 40])
        ok("o título NÃO encolhe por causa dos fades", re.search(
            r"<Sm2TiGenerator\b.*?<Duration>(\d+)", trilha, re.DOTALL).group(1), "269")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
