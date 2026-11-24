"""LAB v2 (2026-10-23): o formato novo da nota, decidido pelo autor sobre a variante B.
- B: um Text+ por grupo de notas que se tocam; cada nota é uma camada que liga/desliga por degrau no Blend;
- os espaços FECHAM: cada nota fica logo abaixo da anterior ativa (Y por degrau, modificador XYPath);
- linha 1 = trilha (cor própria) · nome do segmento (cor pelo TIPO de clipe) · TC source in > out (cinza);
- linha 2 em diante = os efeitos; o nº de keyframes e o intervalo atual em vermelho;
- rampa: só o 1º e o último valor;
- mais folga entre as notas.
Uso: python lab_notas_v2.py <pasta de saída>"""
import os
import struct
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))  # modulos/conformar
sys.path.insert(0, os.path.join(RAIZ, "motor"))
from drp import writer as W  # noqa: E402
from titulos import textplus as TP  # noqa: E402

SAIDA = sys.argv[1]
SIZE, LINHA, FOLGA = 0.035, 0.05, 0.035      # FOLGA: entre uma nota e a seguinte (antes: 0)
X, TOPO = 80 / 1920, 0.967
QUADRO = (1920, 1080)

#: a paleta (proposta para o autor aprovar)
COR = {
    "branco": (1.0, 1.0, 1.0),
    "trilha": (0.36, 0.78, 1.0),          # azul-claro: V1, V2…
    "tc": (0.65, 0.65, 0.65),             # #A5A5A5, o piso de contraste do app
    "destaque": (1.0, 0.33, 0.33),        # vermelho: nº de keyframes e "estamos aqui"
    # tipo do clipe
    "video": (1.0, 1.0, 1.0),
    "composto": (0.73, 0.55, 1.0),        # lilás
    "titulo": (0.42, 0.89, 0.54),         # verde
    "multicam": (1.0, 0.64, 0.30),        # laranja
    "ajuste": (1.0, 0.48, 0.85),          # rosa
    "rampa": (1.0, 0.85, 0.30),           # amarelo (a palavra RAMPA)
}


def cabeca(trilha, nome, tipo, src_in, src_out):
    tc = [("  ", "branco"), (f"{src_in} > {src_out}", "tc")] if src_in != "—" else []   # sem source: sem TC
    return [(trilha, "trilha"), (" ", "branco"), (nome, tipo)] + tc


TAB = [("      ", "branco")]           # o recuo do que está DENTRO de um Compound/multicam


def dentro(linha):
    return TAB + list(linha)


def nota(inicio, dur, cab, *linhas, seg_inicio=None):
    """`seg_inicio`: o início do SEGMENTO — a nota cortada num keyframe guarda o lugar da primeira."""
    return {"inicio": inicio, "dur": dur, "linhas": [cab] + [list(l) for l in linhas],
            "ordem": inicio if seg_inicio is None else seg_inicio}


B, R = "branco", "destaque"
O = 240                                  # o DRT sem mídia começa no quadro 86: tudo depois disso
NOTAS = [
    # 3D Warp com 3 keyframes, cortada nos keyframes: duas notas em sequência
    nota(O + 0, 48, cabeca("V1", "A001C003", "video", "14:02:10:04", "14:02:14:04"),
         [("3D Warp · escala X · linear · ", B), ("3", R), (" keyframes > 56%-75% (", B), ("56%-75%", R), ("-100%)", B)]),
    nota(O + 48, 48, cabeca("V1", "A001C003", "video", "14:02:10:04", "14:02:14:04"),
         [("3D Warp · escala X · linear · ", B), ("3", R), (" keyframes > 75%-100% (56%-", B), ("75%-100%", R), (")", B)],
         seg_inicio=O + 0),
    nota(O + 24, 48, cabeca("V2", "INSERT_CEL", "video", "09:11:00:12", "09:11:02:12"),
         [("ESTABILIZADO NO AVID · Stabilize · zoom 112% — refazer", B)]),
    nota(O + 48, 96, cabeca("V3", "GC_ENTREVISTADA", "titulo", "—", "—"),
         [("Titler+ · refeito como Text · conferir fonte e posição", B)]),
    nota(O + 120, 72, cabeca("V2", "ABERTURA_CMP", "composto", "01:00:00:00", "01:00:03:00"),
         [("Compound Clip · 3 trilhas dentro", B)],
         dentro(cabeca("V2.1", "A003C001", "video", "11:04:00:10", "11:04:03:10")),
         dentro([("Resize · escala 110%", B)]),
         dentro(cabeca("V2.2", "LOGO_CLIENTE", "video", "00:00:00:00", "00:00:03:00")),
         dentro([("3D Warp · posição X · linear · ", B), ("2", R), (" keyframes > -40 → 0", B)]),
         dentro(cabeca("V2.3", "GC_ABERTURA", "titulo", "—", "—")),
         dentro([("Titler+ · refeito como Text · conferir", B)])),
    nota(O + 144, 72, cabeca("V4", "AJUSTE_LUT", "ajuste", "—", "—"),
         [("Camada de ajuste · LUT Rec709_v2.cube", B)]),
    nota(O + 260, 60, cabeca("V1", "MC_ENTREVISTA", "multicam", "10:20:30:00", "10:20:32:12"),
         [("Multicam · 4 ângulos · ativo: ângulo 2", B)],
         dentro(cabeca("V1.2", "CAM_B_0042", "video", "10:20:30:00", "10:20:32:12")),
         dentro([("Color Correction · conferir", B)])),
    nota(O + 260, 60, cabeca("V2", "A002C001", "video", "15:00:01:00", "15:00:03:12"),
         [("RAMPA", "rampa"), (" · 100% > 35% (1º e último keyframe)", B)]),
]


def _esc(t):
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _texto(n):
    return "\n".join("".join(t for t, _c in l) for l in n["linhas"])


def _cls(n):
    """As entradas do Character Level Styling: cada trecho que não é branco ganha o seu RGB."""
    arr, pos = [], 0
    for li, linha in enumerate(n["linhas"]):
        if li:
            pos += 1
        for t, c in linha:
            rgb = COR[c]
            if t and rgb != (1.0, 1.0, 1.0):
                for codigo, v in zip((2401, 2402, 2403), rgb):
                    if v != 1.0:
                        arr.append(f"{{ {codigo}, {pos}, {pos + len(t) - 1}, Value = {TP._n(v)} }}")
            pos += len(t)
    return arr


def _altura(n):
    return len(n["linhas"]) * LINHA + FOLGA


def _degraus(chaves):
    return ", ".join(f"[{t}] = {{ {TP._n(v)}, Flags = {{ StepIn = true }} }}" for t, v in chaves)


def _clipe(ini, fim, notas_do_grupo):
    dur = fim - ini
    cortes = sorted({ini, fim} | {n["inicio"] for n in notas_do_grupo} | {n["inicio"] + n["dur"] for n in notas_do_grupo})
    ordem = sorted(range(len(notas_do_grupo)), key=lambda i: (notas_do_grupo[i]["ordem"], i))
    ys = {i: [] for i in ordem}           # chaves de Y por camada
    vis = {i: [] for i in ordem}          # chaves do Blend
    for a in cortes[:-1]:
        topo = TOPO
        for i in ordem:
            n = notas_do_grupo[i]
            ativa = n["inicio"] <= a < n["inicio"] + n["dur"]
            vis[i].append((a - ini, 1 if ativa else 0))
            if ativa:
                ys[i].append((a - ini, topo))
                topo -= _altura(n)
    w, h = QUADRO
    partes = [f'Background1 = Background {{ Inputs = {{ GlobalOut = Input {{ Value = {dur - 1}, }}, '
              f'Width = Input {{ Value = {w}, }}, Height = Input {{ Value = {h}, }}, '
              f'UseFrameFormatSettings = Input {{ Value = 1, }}, TopLeftAlpha = Input {{ Value = 0, }}, '
              f'TopLeftRed = Input {{ Value = 0, }}, TopLeftGreen = Input {{ Value = 0, }}, TopLeftBlue = Input {{ Value = 0, }}, }}, }}']
    fundo = "Background1"
    for k, i in enumerate(ordem, 1):
        n = notas_do_grupo[i]
        arr = _cls(n)
        partes.append(f'CLS{k} = StyledTextCLS {{ Inputs = {{ Text = Input {{ Value = "{_esc(_texto(n))}", }}, '
                      f'CharacterLevelStyling = Input {{ Value = StyledText {{ Array = {{ {", ".join(arr)} }}, Value = "" }}, }}, }}, }}')
        # Y por degrau (a nota sobe quando a de cima acaba); X fixo
        partes.append(f'Text{k}CY = BezierSpline {{ KeyFrames = {{ {_degraus(ys[i])} }} }}')
        partes.append(f'Text{k}C = XYPath {{ ShowKeyPoints = false, DrawMode = "ModifyOnly", Inputs = {{ '
                      f'X = Input {{ Value = {TP._n(X)}, }}, Y = Input {{ SourceOp = "Text{k}CY", Source = "Value", }}, }}, }}')
        partes.append(
            f'Text{k} = TextPlus {{ Inputs = {{ GlobalOut = Input {{ Value = {dur - 1}, }}, '
            f'Width = Input {{ Value = {w}, }}, Height = Input {{ Value = {h}, }}, UseFrameFormatSettings = Input {{ Value = 1, }}, '
            f'StyledText = Input {{ SourceOp = "CLS{k}", Source = "StyledText", }}, '
            f'Font = Input {{ Value = "Open Sans", }}, Style = Input {{ Value = "Semibold", }}, '
            f'Size = Input {{ Value = {TP._n(SIZE)}, }}, '
            f'Center = Input {{ SourceOp = "Text{k}C", Source = "Value", }}, '
            f'VerticalTopCenterBottom = Input {{ Value = -1, }}, HorizontalLeftCenterRight = Input {{ Value = -1, }}, '
            f'VerticalJustificationNew = Input {{ Value = 3, }}, HorizontalJustificationNew = Input {{ Value = 0, }}, }}, }}')
        blend = ""
        if any(v == 0 for _t, v in vis[i]):
            partes.append(f"Merge{k}Blend = BezierSpline {{ KeyFrames = {{ {_degraus(vis[i])} }} }}")
            blend = f'Blend = Input {{ SourceOp = "Merge{k}Blend", Source = "Value", }}, '
        partes.append(f'Merge{k} = Merge {{ Inputs = {{ {blend}Background = Input {{ SourceOp = "{fundo}", Source = "Output", }}, '
                      f'Foreground = Input {{ SourceOp = "Text{k}", Source = "Output", }}, }}, }}')
        fundo = f"Merge{k}"
    partes.append(f'MediaOut1 = MediaOut {{ Inputs = {{ Index = Input {{ Value = "0", }}, '
                  f'Input = Input {{ SourceOp = "{fundo}", Source = "Output", }} }}, }}')
    tools = "{ " + ", ".join(partes) + " }"
    cab = TP._CABECALHO.format(fim=dur - 1, w=w, h=h, fps="24")
    nome = " ‖ ".join(_texto(n).replace("\n", " | ") for n in (notas_do_grupo[i] for i in ordem))
    b = TP._FORMA
    b = b.replace("<Name>Fusion Title</Name>", f"<Name>{W._xml_escape(nome[:250])}</Name>")
    b = b.replace("<Start>0</Start>", f"<Start>{ini + W._TIMELINE_OFFSET_FRAMES}</Start>")
    b = b.replace("<Duration>1</Duration>", f"<Duration>{dur}</Duration>")
    b = b.replace("<CompositionBA></CompositionBA>", f"<CompositionBA>{TP.composicao_ba(cab, tools)}</CompositionBA>")
    b = b.replace("<MediaFrameRate></MediaFrameRate>", f"<MediaFrameRate>{(struct.pack('<d', 24.0) + bytes(8)).hex()}</MediaFrameRate>")
    b = b.replace("<MediaTimemapBA></MediaTimemapBA>", f"<MediaTimemapBA>02{struct.pack('>d', (dur - 1) / 24.0).hex()}</MediaTimemapBA>")
    return W._uniquify(b)


def notas_b2(notas, by_track):
    lane = by_track.setdefault(max(by_track or {0: None}) + 1, [])
    ordem = sorted(notas, key=lambda n: n["inicio"])
    grupos, fim = [], -1
    for n in ordem:
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
W._notas_na_timeline = notas_b2
r = W.build_drt([], [], os.path.join(SAIDA, "NOTAS_V2.drt"), timeline_name="NOTAS V2", timeline_fps=24.0,
                notas=[dict(n, nome="x", grupo="efeito") for n in NOTAS])
W._notas_na_timeline = original
print("notas", r.get("notas"))
