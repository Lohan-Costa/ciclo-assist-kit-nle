"""LAB v3 (2026-10-23): o formato v2 + o pedido do autor sobre ele:
- as subtrilhas (dentro de Compound/multicam: V2.1, V1.2…) num azul MAIS CLARO;
- COLUNAS: nenhum texto embaixo do rótulo da trilha — o nome e as linhas de efeito começam na mesma coluna; o rótulo
  de dentro (V2.1) começa na coluna do nome de fora. Fonte proporcional: a coluna vem da LARGURA medida do rótulo
  (OpenSans-Semibold.ttf, 39 px por Size 0,035 num quadro de 1920 — calibrado pela imagem), não de espaços;
- sem "→" (o Text+ não tem o glifo): ">".
Desenho: cada LINHA é um Text+ no X da sua coluna; as linhas de uma nota se juntam e um Transform (Center por degrau)
move a nota inteira quando a de cima acaba; o Blend do Merge liga/desliga a nota.
Uso: python lab_notas_v3.py <pasta de saída>"""
import os
import struct
import sys

from PIL import ImageFont

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))  # modulos/conformar
sys.path.insert(0, os.path.join(RAIZ, "motor"))
from drp import writer as W  # noqa: E402
from titulos import textplus as TP  # noqa: E402

SAIDA = sys.argv[1]
QUADRO = (1920, 1080)
SIZE, LINHA, FOLGA = 0.035, 0.05, 0.035
X, TOPO = 80 / 1920, 0.967
PX_POR_SIZE = 39 / 0.035                 # px da fonte (quadro de 1920) por unidade de Size do Text+
FONTE = ImageFont.truetype(r"C:\Windows\Fonts\OpenSans-Semibold.ttf", 100)

COR = {
    "branco": (1.0, 1.0, 1.0),
    "trilha": (0.36, 0.78, 1.0),
    "subtrilha": (0.66, 0.89, 1.0),       # azul mais claro: V2.1, V1.2…
    "tc": (0.65, 0.65, 0.65),
    "destaque": (1.0, 0.33, 0.33),
    "video": (1.0, 1.0, 1.0), "composto": (0.73, 0.55, 1.0), "titulo": (0.42, 0.89, 0.54),
    "multicam": (1.0, 0.64, 0.30), "ajuste": (1.0, 0.48, 0.85), "rampa": (1.0, 0.85, 0.30),
}
B, R = "branco", "destaque"


def largura(texto):
    """Largura em fração do quadro do texto no Text+ (Size SIZE)."""
    return FONTE.getlength(texto) / 100 * SIZE * PX_POR_SIZE / QUADRO[0]


def clipe(nivel, trilha, nome, tipo, src=None, efeitos=()):
    """Uma cabeça (trilha · nome · TC source) e as linhas de efeito, num nível (0 = a timeline, 1 = dentro)."""
    cab = [(nome, tipo)] + ([("  ", B), (f"{src[0]} > {src[1]}", "tc")] if src else [])
    return [{"nivel": nivel, "rotulo": trilha, "trechos": cab}] + \
           [{"nivel": nivel, "rotulo": None, "trechos": list(e)} for e in efeitos]


def nota(inicio, dur, *partes, ordem=None):
    linhas = [l for p in partes for l in p]
    return {"inicio": inicio, "dur": dur, "linhas": linhas, "ordem": inicio if ordem is None else ordem}


O = 240
WARP1 = [("3D Warp · escala X · linear · ", B), ("3", R), (" keyframes > 56%-75% (", B), ("56%-75%", R), ("-100%)", B)]
WARP2 = [("3D Warp · escala X · linear · ", B), ("3", R), (" keyframes > 75%-100% (56%-", B), ("75%-100%", R), (")", B)]
NOTAS = [
    nota(O + 0, 48, clipe(0, "V1", "A001C003", "video", ("14:02:10:04", "14:02:14:04"), [WARP1])),
    nota(O + 48, 48, clipe(0, "V1", "A001C003", "video", ("14:02:10:04", "14:02:14:04"), [WARP2]), ordem=O),
    nota(O + 24, 48, clipe(0, "V2", "INSERT_CEL", "video", ("09:11:00:12", "09:11:02:12"),
                           [[("ESTABILIZADO NO AVID · Stabilize · zoom 112% — refazer", B)]])),
    nota(O + 48, 96, clipe(0, "V3", "GC_ENTREVISTADA", "titulo", None,
                           [[("Titler+ · refeito como Text · conferir fonte e posição", B)]])),
    nota(O + 120, 72,
         clipe(0, "V2", "ABERTURA_CMP", "composto", ("01:00:00:00", "01:00:03:00"), [[("Compound Clip · 3 trilhas dentro", B)]]),
         clipe(1, "V2.1", "A003C001", "video", ("11:04:00:10", "11:04:03:10"), [[("Resize · escala 110%", B)]]),
         clipe(1, "V2.2", "LOGO_CLIENTE", "video", ("00:00:00:00", "00:00:03:00"),
               [[("3D Warp · posição X · linear · ", B), ("2", R), (" keyframes > -40 > 0", B)]]),
         clipe(1, "V2.3", "GC_ABERTURA", "titulo", None, [[("Titler+ · refeito como Text · conferir", B)]])),
    nota(O + 144, 72, clipe(0, "V4", "AJUSTE_LUT", "ajuste", None, [[("Camada de ajuste · LUT Rec709_v2.cube", B)]])),
    nota(O + 260, 60,
         clipe(0, "V1", "MC_ENTREVISTA", "multicam", ("10:20:30:00", "10:20:32:12"), [[("Multicam · 4 ângulos · ativo: ângulo 2", B)]]),
         clipe(1, "V1.2", "CAM_B_0042", "video", ("10:20:30:00", "10:20:32:12"), [[("Color Correction · conferir", B)]])),
    nota(O + 260, 60, clipe(0, "V2", "A002C001", "video", ("15:00:01:00", "15:00:03:12"),
                            [[("RAMPA", "rampa"), (" · 100% > 35% (1º e último keyframe)", B)]])),
]


def _esc(t):
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _colunas(n):
    """X do rótulo e X do conteúdo por nível: o conteúdo começa depois do MAIOR rótulo do nível (+ espaço);
    o rótulo do nível de dentro começa na coluna do conteúdo de fora."""
    xr, xc = {}, {}
    for nivel in sorted({l["nivel"] for l in n["linhas"]}):
        xr[nivel] = X if nivel == 0 else xc[nivel - 1]
        maior = max(largura(l["rotulo"] + " ") for l in n["linhas"] if l["nivel"] == nivel and l["rotulo"])
        xc[nivel] = xr[nivel] + maior
    return xr, xc


def _altura(n):
    return len(n["linhas"]) * LINHA + FOLGA


def _degraus(chaves):
    return ", ".join(f"[{t}] = {{ {TP._n(v)}, Flags = {{ StepIn = true }} }}" for t, v in chaves)


def _texto(k, x, y, texto, trechos, dur, w, h):
    """Um Text+ de uma linha; a cor por trecho no Character Level Styling (fim INCLUSO)."""
    arr, pos = [], 0
    for t, c in trechos:
        rgb = COR[c]
        if t and rgb != (1.0, 1.0, 1.0):
            arr += [f"{{ {cod}, {pos}, {pos + len(t) - 1}, Value = {TP._n(v)} }}"
                    for cod, v in zip((2401, 2402, 2403), rgb) if v != 1.0]
        pos += len(t)
    if arr:
        cls = (f'CLS{k} = StyledTextCLS {{ Inputs = {{ Text = Input {{ Value = "{_esc(texto)}", }}, '
               f'CharacterLevelStyling = Input {{ Value = StyledText {{ Array = {{ {", ".join(arr)} }}, Value = "" }}, }}, }}, }}')
        fonte = f'StyledText = Input {{ SourceOp = "CLS{k}", Source = "StyledText", }}, '
    else:
        cls, fonte = None, f'StyledText = Input {{ Value = "{_esc(texto)}", }}, '
    txt = (f'T{k} = TextPlus {{ Inputs = {{ GlobalOut = Input {{ Value = {dur - 1}, }}, '
           f'Width = Input {{ Value = {w}, }}, Height = Input {{ Value = {h}, }}, UseFrameFormatSettings = Input {{ Value = 1, }}, '
           + fonte +
           f'Font = Input {{ Value = "Open Sans", }}, Style = Input {{ Value = "Semibold", }}, Size = Input {{ Value = {TP._n(SIZE)}, }}, '
           f'Center = Input {{ Value = {{ {TP._n(x)}, {TP._n(y)} }}, }}, '
           f'VerticalTopCenterBottom = Input {{ Value = -1, }}, HorizontalLeftCenterRight = Input {{ Value = -1, }}, '
           f'VerticalJustificationNew = Input {{ Value = 3, }}, HorizontalJustificationNew = Input {{ Value = 0, }}, }}, }}')
    return [p for p in (cls, txt) if p]


def _clipe(ini, fim, grupo):
    dur = fim - ini
    w, h = QUADRO
    cortes = sorted({ini, fim} | {n["inicio"] for n in grupo} | {n["inicio"] + n["dur"] for n in grupo})
    ordem = sorted(range(len(grupo)), key=lambda i: (grupo[i]["ordem"], i))
    dy = {i: [] for i in ordem}
    vis = {i: [] for i in ordem}
    for a in cortes[:-1]:
        topo = TOPO
        for i in ordem:
            n = grupo[i]
            ativa = n["inicio"] <= a < n["inicio"] + n["dur"]
            vis[i].append((a - ini, 1 if ativa else 0))
            if ativa:
                dy[i].append((a - ini, 0.5 + (topo - TOPO)))      # Center do Transform: 0,5 = no lugar
                topo -= _altura(grupo[i])
    partes = [f'Background1 = Background {{ Inputs = {{ GlobalOut = Input {{ Value = {dur - 1}, }}, '
              f'Width = Input {{ Value = {w}, }}, Height = Input {{ Value = {h}, }}, UseFrameFormatSettings = Input {{ Value = 1, }}, '
              f'TopLeftAlpha = Input {{ Value = 0, }}, TopLeftRed = Input {{ Value = 0, }}, TopLeftGreen = Input {{ Value = 0, }}, '
              f'TopLeftBlue = Input {{ Value = 0, }}, }}, }}']
    fundo, k = "Background1", 0
    for j, i in enumerate(ordem, 1):
        n = grupo[i]
        xr, xc = _colunas(n)
        base = None
        for li, l in enumerate(n["linhas"]):
            y = TOPO - li * LINHA                      # a nota desenhada no TOPO; o Transform a desce
            pedacos = []
            if l["rotulo"]:
                pedacos.append((xr[l["nivel"]], l["rotulo"], [(l["rotulo"], "trilha" if l["nivel"] == 0 else "subtrilha")]))
            pedacos.append((xc[l["nivel"]], "".join(t for t, _c in l["trechos"]), l["trechos"]))
            for x, texto, trechos in pedacos:
                k += 1
                partes += _texto(k, x, y, texto, trechos, dur, w, h)
                if base is None:
                    base = f"T{k}"
                else:
                    partes.append(f'L{k} = Merge {{ Inputs = {{ Background = Input {{ SourceOp = "{base}", Source = "Output", }}, '
                                  f'Foreground = Input {{ SourceOp = "T{k}", Source = "Output", }}, }}, }}')
                    base = f"L{k}"
        partes.append(f'N{j}CY = BezierSpline {{ KeyFrames = {{ {_degraus(dy[i])} }} }}')
        partes.append(f'N{j}C = XYPath {{ ShowKeyPoints = false, DrawMode = "ModifyOnly", Inputs = {{ X = Input {{ Value = 0.5, }}, '
                      f'Y = Input {{ SourceOp = "N{j}CY", Source = "Value", }}, }}, }}')
        partes.append(f'N{j} = Transform {{ Inputs = {{ Center = Input {{ SourceOp = "N{j}C", Source = "Value", }}, '
                      f'Input = Input {{ SourceOp = "{base}", Source = "Output", }}, }}, }}')
        blend = ""
        if any(v == 0 for _t, v in vis[i]):
            partes.append(f"M{j}Blend = BezierSpline {{ KeyFrames = {{ {_degraus(vis[i])} }} }}")
            blend = f'Blend = Input {{ SourceOp = "M{j}Blend", Source = "Value", }}, '
        partes.append(f'M{j} = Merge {{ Inputs = {{ {blend}Background = Input {{ SourceOp = "{fundo}", Source = "Output", }}, '
                      f'Foreground = Input {{ SourceOp = "N{j}", Source = "Output", }}, }}, }}')
        fundo = f"M{j}"
    partes.append(f'MediaOut1 = MediaOut {{ Inputs = {{ Index = Input {{ Value = "0", }}, '
                  f'Input = Input {{ SourceOp = "{fundo}", Source = "Output", }} }}, }}')
    tools = "{ " + ", ".join(partes) + " }"
    cab = TP._CABECALHO.format(fim=dur - 1, w=w, h=h, fps="24")
    nome = " ‖ ".join(" | ".join(((l["rotulo"] + " ") if l["rotulo"] else "") + "".join(t for t, _c in l["trechos"])
                                 for l in grupo[i]["linhas"]) for i in ordem)
    b = TP._FORMA
    b = b.replace("<Name>Fusion Title</Name>", f"<Name>{W._xml_escape(nome[:250])}</Name>")
    b = b.replace("<Start>0</Start>", f"<Start>{ini + W._TIMELINE_OFFSET_FRAMES}</Start>")
    b = b.replace("<Duration>1</Duration>", f"<Duration>{dur}</Duration>")
    b = b.replace("<CompositionBA></CompositionBA>", f"<CompositionBA>{TP.composicao_ba(cab, tools)}</CompositionBA>")
    b = b.replace("<MediaFrameRate></MediaFrameRate>", f"<MediaFrameRate>{(struct.pack('<d', 24.0) + bytes(8)).hex()}</MediaFrameRate>")
    b = b.replace("<MediaTimemapBA></MediaTimemapBA>", f"<MediaTimemapBA>02{struct.pack('>d', (dur - 1) / 24.0).hex()}</MediaTimemapBA>")
    return W._uniquify(b)


def notas_v3(notas, by_track):
    lane = by_track.setdefault(max(by_track or {0: None}) + 1, [])
    grupos, fim = [], -1
    for n in sorted(notas, key=lambda n: n["inicio"]):
        if not grupos or n["inicio"] >= fim:
            grupos.append([])
            fim = -1
        grupos[-1].append(n)
        fim = max(fim, n["inicio"] + n["dur"])
    for g in grupos:
        lane.append(_clipe(min(n["inicio"] for n in g), max(n["inicio"] + n["dur"] for n in g), g))
    return {max(by_track)}


os.makedirs(SAIDA, exist_ok=True)
original = W._notas_na_timeline
W._notas_na_timeline = notas_v3
r = W.build_drt([], [], os.path.join(SAIDA, "NOTAS_V3.drt"), timeline_name="NOTAS V3", timeline_fps=24.0,
                notas=[dict(n, nome="x", grupo="efeito") for n in NOTAS])
W._notas_na_timeline = original
print("notas", r.get("notas"))
