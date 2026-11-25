"""Título do Premiere → Text do Resolve: fonte, corpo, posição e o zoom do Graphic Group (2026-10-04).

Rodar:

    .venv/bin/python tests/test_titulo_premiere.py        (Windows: .venv-win/Scripts/python)

Conferido pela imagem no Resolve 21.1 (Mac) contra a referência do PRODUCAO_B (2880×1620):

  - claquete "PRODUCAO-B / Rolo Único" em Monaco: a 1ª linha caiu no pixel (corpo e posição);
  - título final "PRODUCAO-B" em Optima Regular, com o Graphic Group crescendo de 80% a 100%:
    ±1 px aos 5 s e aos 10 s do título.

Antes: corpo 7% maior (o fator 1152 do Avid), Optima em NEGRITO (sem a face, o Resolve grava o
peso 63 = DemiBold), ascendente fixa de 0,72 e a escala do grupo só no corpo, não na posição.
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import zstandard  # noqa: E402

from prproj import leitura  # noqa: E402
from titulos import fontes  # noqa: E402
from titulos import resolve as R  # noqa: E402
import casos as C  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado, tol=None):
    global casos
    casos += 1
    certo = (abs(obtido - esperado) <= tol) if tol is not None else obtido == esperado
    if certo:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def _fonte_minima(ps: str, familia: str, face: str, upm: int, asc: int) -> bytes:
    """Um .ttf só com `name`, `head` e `hhea` — o que o índice lê."""
    nomes = [(1, familia), (2, face), (6, ps)]
    area = 6 + 12 * len(nomes)
    regs, dados = b"", b""
    for nid, s in nomes:
        d = s.encode("utf-16-be")
        regs += struct.pack(">6H", 3, 1, 0x409, nid, len(d), len(dados))
        dados += d
    name = struct.pack(">HHH", 0, len(nomes), area) + regs + dados
    head = bytes(18) + struct.pack(">H", upm) + bytes(34)
    hhea = struct.pack(">I", 0x10000) + struct.pack(">hhh", asc, -200, 0) + bytes(26)
    tabs = [(b"head", head), (b"hhea", hhea), (b"name", name)]
    pos = 12 + 16 * len(tabs)
    cab, corpo = struct.pack(">IHHHH", 0x10000, len(tabs), 0, 0, 0), b""
    for tag, d in tabs:
        cab += struct.pack(">4sIII", tag, 0, pos + len(corpo), len(d))
        corpo += d + bytes(-len(d) % 4)
    return cab + corpo


def _fontes():
    print("fontes: PostScript → família, face e ascendente")
    with tempfile.TemporaryDirectory() as d:
        Path(d, "Teste.ttf").write_bytes(_fonte_minima("TesteSans-SemiBold", "Teste Sans", "SemiBold", 1000, 930))
        antes, fontes._INDICE = fontes.pastas_de_fontes, None
        fontes.pastas_de_fontes = lambda: [d]
        try:
            t = fontes.traduzir("TesteSans-SemiBold")
            ok("achada pela tabela name", (t["familia"], t["face"], t["instalada"]),
               ("Teste Sans", "SemiBold", True))
            ok("ascendente da hhea", t["ascendente"], 0.93, 1e-9)
            ok("o nome PostScript não diferencia caixa", fontes.traduzir("testesans-semibold")["familia"],
               "Teste Sans")
        finally:
            fontes.pastas_de_fontes, fontes._INDICE = antes, None
    fontes._INDICE = {}                          # máquina sem fonte nenhuma: a dedução pelo nome
    try:
        t = fontes.traduzir("HelveticaNeueLTPro-BoldItalic")
        ok("não instalada: dedução pelo nome", (t["familia"], t["face"], t["instalada"]),
           ("Helvetica Neue LT", "Bold Italic", False))
        ok("não instalada: sufixo MT sai", fontes.traduzir("ArialMT")["familia"], "Arial")
        ok("não instalada: sem face = Regular", fontes.traduzir("Monaco")["face"], "Regular")
    finally:
        fontes._INDICE = None


def _com_fonte(familia, face, asc, linha=1.2, adobe=False):
    antes = fontes.traduzir
    fontes.traduzir = lambda ps: {"familia": familia, "face": face, "ascendente": asc, "linha": linha,
                                  "adobe": adobe, "instalada": True}
    return antes


def _titulos():
    print("título do Premiere → bloco `titulo`")
    antes = _com_fonte("Monaco", "Regular", 1.0, linha=1.33349609375)
    try:
        # A claquete do PRODUCAO_B (valores lidos do projeto).
        f = {"texto": {"texto": "PRODUCAO-B\nRolo Único", "fonte": "Monaco",
                       "Position": "0.04620361328125:0.4870452880859375", "Scale": "100."}, "t0": 0}
        cx = leitura._titulo_resolve(f, (2880, 1620), [], 254016000000 / 24)["caixas"][0]
        ok("claquete: Size do Resolve = px × 1080 / altura", cx["corpo_resolve"], 66.6667, 1e-3)
        ok("claquete: face Regular explícita (sem ela, peso 63)", cx["fonte"], {"familia": "Monaco", "estilo": "Regular"})
        ok("claquete: topo = linha de base − ascendente × corpo (X)", cx["posicao_resolve"][0], 0.0462036, 1e-6)
        ok("claquete: topo = linha de base − ascendente × corpo (Y)", cx["posicao_resolve"][1],
           1 - (0.4870452880859375 - 100 / 1620), 1e-9)
        ok("claquete: entrelinha = (120% − linha da Monaco) × corpo, em px de 1080", cx["entrelinha"],
           (1.2 - 1.33349609375) * 100 * 1080 / 1620, 1e-3)
        f1 = {"texto": dict(f["texto"], texto="PRODUCAO-B"), "t0": 0}
        ok("uma linha só: sem entrelinha",
           leitura._titulo_resolve(f1, (2880, 1620), [], 1.0)["caixas"][0]["entrelinha"], None)
    finally:
        fontes.traduzir = antes

    antes = _com_fonte("Optima", "Regular", 0.919)
    try:
        tpf = 254016000000 / 24
        f = {"texto": {"texto": "PRODUCAO-B", "fonte": "Optima-Regular",
                       "Position": "0.3222198486328125:0.5309600830078125", "Scale": "266.981170654297"},
             "grupo_escala": "80.", "grupo_posicao": "0.5:0.5", "grupo_ancora": "0.5:0.5",
             "grupo_escala_kf": [(1000 * tpf, 80.0), (1299 * tpf, 100.0)], "t0": 1000 * tpf}
        t = leitura._titulo_resolve(f, (2880, 1620), [], tpf)
        ok("grupo no centro: vira o Zoom animado do clipe", t["transform"]["kf_zoom"], [(0, 0.8), (299, 1.0)])
        ok("grupo no centro: o texto vai sem a escala do grupo", t["caixas"][0]["corpo_resolve"],
           266.981170654297 * 1080 / 1620, 1e-6)
        ok("grupo no centro: posição do texto intacta", t["caixas"][0]["posicao_resolve"][0], 0.3222198, 1e-6)

        f2 = dict(f, grupo_ancora="0.25:0.5", grupo_posicao="0.25:0.5", grupo_escala_kf=[])
        t2 = leitura._titulo_resolve(f2, (2880, 1620), [], tpf)
        ok("âncora fora do centro: sem Transform", t2["transform"], None)
        ok("âncora fora do centro: escala embutida na posição", t2["caixas"][0]["posicao_resolve"][0],
           0.25 + (0.3222198486328125 - 0.25) * 0.8, 1e-9)
    finally:
        fontes.traduzir = antes


#: `Source Text` reais do PRODUCAO_B: "16-4-SERIE-1" em ArialMT corpo 160, e o título final em
#: Optima-Regular com o corpo padrão (o campo não vem).
BLOB_ARIAL_160 = ("SAEAAAAAAABEMyIRDAAAAAAABgAKAAQABgAAAGQAAAAAAF4AHAAQAAwAAAAAAAAAAAAYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                  "AAAAAAAAAAAAAAAAAAAAFgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAABcABwBeAAAAAAAAARQAAAAgAAAAMAAAAAAA"
                  "AQA3M9dBZP///2j///9s////cP///wEAAAAEAAAABwAAAEFyaWFsTVQAAQAAAAwAAAAIAA4ABAAIAAgAAABsAAAAPAAAAAAANgAY"
                  "AAAAFAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwAAAAIAAQANgAAAAIAAAAQAAAAEAAAAAAAgEAAACBD9P////j////8////BAAEAAQAAAAMAAAAMTYtNC1TRVJJRS0xAAAAAA==")
BLOB_OPTIMA_PADRAO = ("UAEAAAAAAABEMyIRDAAAAAAABgAKAAQABgAAAGQAAAAAAF4AJAAQAAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAHAAYAAAAAAAA"
                      "AAAAAAAAAAAAAAAAAAAAFgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAABcABwBeAAAAAAAAARwAAAAoAAAAQAAAAAAA"
                      "AQD4Nv9AyYC6QTxetEJg////ZP///2j///9s////AQAAAAQAAAAOAAAAT3B0aW1hLVJlZ3VsYXIAAAEAAAAMAAAACAAOAAQACAAI"
                      "AAAAaAAAADwAAAAAADYAFAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMAAAACAAEADYAAAACAAAADAAAAAwAAAAAAIBA9P////j////8////BAAEAAQAAAAJAAAARElBIMOaVElMAAAA")


def _corpo():
    print("corpo no blob do Source Text")
    ok("ArialMT 160", leitura._corpo_do_blob(BLOB_ARIAL_160), 160.0)
    ok("corpo padrão: ausente (= 100)", leitura._corpo_do_blob(BLOB_OPTIMA_PADRAO), None)
    ok("blob ilegível: None", leitura._corpo_do_blob("AAAA"), None)
    ok("o texto continua lido", leitura._texto_do_blob(BLOB_ARIAL_160), ("16-4-SERIE-1", "ArialMT"))


#: O texto rico que o Resolve 21.1 gravou no gabarito do autor (2026-10-04): "Basic" / "Title",
#: Open Sans Semibold 96, centralizado, Line Spacing 257.
GABARITO_ENTRELINHA_257 = bytes.fromhex(
    "f70000000bb100000e00000062006100610060006000130000000c0000000100000002000000380400180000000e0000004200610073006900630003"
    "0000000100180000000e0000005400690074006c0065000400000001004f000000160000004f00700065006e002000530061006e0073000000c04214"
    "000000530065006d00690062006f006c00640004008080433f00120000002300660066006600660066006600e8f51e034f000000160000004f007000"
    "65006e002000530061006e0073000000c04214000000530065006d00690062006f006c00640004008080433f00120000002300660066006600660066006600e8f51e03")


def _entrelinha_e_ancora():
    print("entrelinha e Anchor (gabarito do autor)")
    fmt = R.formato("Open Sans", 96.0, "#ffffff", estilo="Semibold", alinhamento="centro", peso=63,
                    entrelinha=257.0)
    ok("Line Spacing 257: byte a byte", R.texto_rico(["Basic", "Title"], fmt), GABARITO_ENTRELINHA_257)
    ok("Anchor: base-centro 1, topo-centro 7 (medidos), topo-esquerda 6",
       (R.ANCORA["base_centro"], R.ANCORA["topo_centro"], R.ANCORA["topo_esquerda"]), (1, 7, 6))
    ok("Anchor: centro-centro é o padrão (4, não gravado)", R.ANCORA["centro_centro"], 4)


def _adobe():
    print("Adobe Fonts")
    with tempfile.TemporaryDirectory() as d:
        Path(d, ".1131.otf").write_bytes(_fonte_minima("PresicavXl-Regular", "Presicav", "ExtraLight", 1000, 900))
        a_pastas, a_adobe, fontes._INDICE = fontes.pastas_de_fontes, fontes.pasta_adobe_fonts, None
        fontes.pastas_de_fontes, fontes.pasta_adobe_fonts = (lambda: [d]), (lambda: d)
        try:
            t = fontes.traduzir("PresicavXl-Regular")
            ok("fonte ativada no Adobe Fonts: família da tabela name, não do nome",
               (t["familia"], t["face"], t["adobe"]), ("Presicav", "ExtraLight", True))
        finally:
            fontes.pastas_de_fontes, fontes.pasta_adobe_fonts, fontes._INDICE = a_pastas, a_adobe, None
    antes = _com_fonte("Gotham", "Book", 0.95, adobe=True)
    try:
        av = []
        leitura._titulo_resolve({"texto": {"texto": "X", "fonte": "Gotham-Book"}, "t0": 0}, (1920, 1080), av)
        ok("fonte do Adobe Fonts avisa", any("Adobe Fonts" in a for a in av), True)
    finally:
        fontes.traduzir = antes


#: O FORMATO do trecho que o Resolve 21.1 gravou em cada variação do gabarito "Gabaritos finais" do
#: autor (2026-10-04): Open Sans Semibold 96, centralizado, peso 63 + a variação.
GABARITO_FORMATOS = {
    "tracking_50": "4f000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c00640004000048423f0012000000230066006600660066006600660068f71e03",
    "tracking_menos_20": "4f000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c006400040000a0c13f0012000000230066006600660066006600660068f71e03",
    "maiusculas": "4c000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c00640001043f00120000002300660066006600660066006600e0f71e03",
    "minusculas": "4c000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c00640002043f00120000002300660066006600660066006600e0f71e03",
    "versalete": "4c000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c00640003043f00120000002300660066006600660066006600e0f71e03",
    "titulo": "4c000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c00640004043f00120000002300660066006600660066006600e0f71e03",
    "sublinhado": "5f000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c006400043f000112000000230066006600660066006600660012000000230066006600660066006600660001e8b71803",
    "sobrelinha": "4c000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c006400043f0001120000002300660066006600660066006600e8d71e03",
    "riscado": "4c000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c006400043f0001120000002300660066006600660066006600e8771e03",
    "sobrescrito": "4c000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c00640004013f00120000002300660066006600660066006600e8f61e03",
    "subscrito": "4c000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c00640004023f00120000002300660066006600660066006600e8f61e03",
    "justificado": "4b000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c006400083f00120000002300660066006600660066006600e8f71e03",
    "contorno_4": "61000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c006400043f0012000000230066006600660066006600660012000000230030003000660066003000300000008040e8f70603",
    "contorno_4_fora": "61000000160000004f00700065006e002000530061006e0073000000c04214000000530065006d00690062006f006c006400043f00120000002300660066006600660066006600120000002300300030006600660030003000000080c0e8f70603",
}


def _formatos_do_gabarito():
    print("formatos do texto rico (gabarito Gabaritos finais, 30 Text)")
    base = dict(estilo="Semibold", alinhamento="centro", peso=63)
    variacoes = {
        "tracking_50": dict(tracking=50.0), "tracking_menos_20": dict(tracking=-20.0),
        "maiusculas": dict(caixa="maiusculas"), "minusculas": dict(caixa="minusculas"),
        "versalete": dict(caixa="versalete"), "titulo": dict(caixa="titulo"),
        "sublinhado": dict(sublinhado=True), "sobrelinha": dict(sobrelinha=True),
        "riscado": dict(riscado=True), "sobrescrito": dict(vertical="sobrescrito"),
        "subscrito": dict(vertical="subscrito"), "justificado": dict(alinhamento="justificado"),
        "contorno_4": dict(cor2="#00ff00", traco=4.0), "contorno_4_fora": dict(cor2="#00ff00", traco=-4.0),
    }
    for nome, kw in variacoes.items():
        ok(f"{nome}: byte a byte", R.formato("Open Sans", 96.0, "#ffffff", **{**base, **kw}).hex(),
           GABARITO_FORMATOS[nome])


def _fundo_e_sombra():
    print("fundo e sombra: Opacity do fundo e cor da sombra")
    tit = {"estilo_lido": True, "fundo": {"cor": [1, 1 / 3, 0], "opacidade": 1.0, "tela_cheia": True},
           "caixas": [{"texto": "X", "cor": [1, 1, 1], "sombra": {"cor": [1, 0, 0], "deslocamento": [0.01, -0.01]}}]}
    efb, _ = R.efeitos_do_texto(tit, 1920, 1080)
    pb = zstandard.ZstdDecompressor().decompress(efb[9:], max_output_size=1 << 20)
    ok("fundo opaco = Opacity 100 (gravado 200; o padrão do Resolve é 50)",
       bytes.fromhex("08221a050a0308c801") in pb, True)
    ok("a cor do fundo vai opaca", bytes.fromhex("01ffffffff5555") in pb, True)
    ok("cor da sombra (p37) vermelha", bytes.fromhex("08251a0f0a0d320b01ffffffff00000000") in pb, True)


def _gerador():
    print("gerador Text com o Transform dentro")
    titulo = {"estilo_lido": True, "fundo": None,
              "transform": {"zoom": 0.8, "pos": (0.0, 0.0), "kf_zoom": [(0, 0.8), (299, 1.0)]},
              "caixas": [{"texto": "PRODUCAO-B", "fonte": {"familia": "Optima", "estilo": "Regular"},
                          "corpo_resolve": 178.0, "cor": [1, 1, 1], "alinhamento": "esquerda",
                          "ancora": "topo_esquerda", "posicao_resolve": (0.32, 0.62)}]}
    efb, _ = R.efeitos_do_texto(titulo, 2880, 1620)
    ok("cabeçalho do texto: zstd (0x81)", efb[8], 0x81)
    pb = zstandard.ZstdDecompressor().decompress(efb[9:], max_output_size=1 << 20)
    sem, _ = R.efeitos_do_texto(dict(titulo, transform=None), 2880, 1620)
    so_texto = zstandard.ZstdDecompressor().decompress(sem[9:], max_output_size=1 << 20)
    ok("os filtros do texto seguem intactos, depois do Transform", pb.endswith(so_texto), True)
    i = 1
    while pb[i] & 0x80:                          # o varint do tamanho do 1º registro
        i += 1
    ok("o 1º registro é o Transform (filtro 0x04)", (pb[0], pb[i + 1:i + 3]), (0x0A, b"\x08\x04"))
    ok("Size gravado = corpo_resolve", struct.pack("<f", 178.0) in pb, True)


def _os2(fs: int, typo: tuple, win: tuple) -> bytes:
    """Os 78 primeiros bytes da OS/2: fsSelection (62), typo asc/desc/gap (68), win asc/desc (74)."""
    b = bytearray(78)
    b[62:64] = struct.pack(">H", fs)
    b[68:74] = struct.pack(">hhh", *typo)
    b[74:78] = struct.pack(">HH", *win)
    return bytes(b)


def _directwrite():
    print("métricas do Windows (DirectWrite), medidas no Resolve 19")
    # Palatino Linotype (pala.ttf): sem USE_TYPO_METRICS → winAscent; base medida 426 = 216 + 1,050 × 200
    asc, linha = fontes._metricas_directwrite(_os2(0x40, (1499, -582, 682), (2150, 613)), 1499, -582, 682, 2048)
    ok("Palatino: ascendente = winAscent", asc, 2150 / 2048, 1e-9)
    ok("Palatino: linha = win + sobra da hhea (medida 1,353)", linha, 1.349, 5e-3)
    # Gabriola: USE_TYPO_METRICS → typo; base medida 354 (typo 0,684 × 200 + 216 = 353), linha 1,700
    asc, linha = fontes._metricas_directwrite(_os2(448, (2800, -1296, 2867), (4880, 2660)), 2800, -1296, 2867, 4096)
    ok("Gabriola (USE_TYPO_METRICS): ascendente = typo", asc, 2800 / 4096, 1e-9)
    ok("Gabriola: linha = typo asc − desc + gap (medida 1,700)", linha, 1.700, 5e-3)


def _alinhamento() -> None:
    """O alinhamento do parágrafo (campo 4 da tabela do documento do Source Text) — projeto do autor com 3 títulos iguais
    (esquerda, centro, direita), Premiere 23.2, 2026-10-10. PULA sem a pasta de testes."""
    print("Alinhamento do título (esquerda / centro / direita)")
    import base64
    from prproj.leitura import Leitor
    from prproj.projeto import Projeto
    raiz = C.amostras()                      # subindo de pasta até a MIDIAS DE TESTES (era D:/ fixo: pulava no Mac)
    caso = raiz / "03 CASOS" / "TITULOS" / "T_ALINHAMENTO_PREMIERE23" / "titulos_alinhamento_23.2.prproj" if raiz else None
    if not caso or not caso.exists():
        print("  — PULA: o caso T_ALINHAMENTO_PREMIERE23 não está nesta máquina")
        return
    caixas = [e["params"]["titulo"]["caixas"][0] for s in Leitor(Projeto(str(caso))).ler("titulo")["segmentos"]
              for e in s.get("effects") or [] if e.get("category") == "title"]
    ok("⭐ os 3 títulos: esquerda, centro, direita — e a âncora do mesmo lado",
       [(c["alinhamento"], c["ancora"]) for c in caixas],
       [("esquerda", "topo_esquerda"), ("centro", "topo_centro"), ("direita", "topo_direita")])
    ok("…a Position é a origem do alinhamento: os três ocupam o mesmo vão (simétricos em volta do meio)",
       round(caixas[0]["posicao_resolve"][0] + caixas[2]["posicao_resolve"][0] - 2 * caixas[1]["posicao_resolve"][0], 2), 0.0)
    ok("blob ilegível → esquerda (como antes)", leitura._alinhamento_do_blob(base64.b64encode(b"x" * 20).decode()), "esquerda")


def main() -> int:
    _alinhamento()
    _directwrite()
    _fontes()
    _titulos()
    _corpo()
    _entrelinha_e_ancora()
    _adobe()
    _formatos_do_gabarito()
    _fundo_e_sombra()
    _gerador()
    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
