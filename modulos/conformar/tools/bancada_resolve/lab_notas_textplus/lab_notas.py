"""LAB: trilha de notas em Text+ com várias camadas (2026-10-23). Gera três DRTs só de notas:
ATUAL (Text empilhado em trilhas), A (Text+ fatiado onde o conjunto de notas muda), B (um Text+ por grupo de
notas que se tocam, cada camada liga/desliga por keyframe de degrau no Blend do Merge).
Uso: python lab_notas.py <pasta de saída> [size] [linha]"""
import os
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))  # modulos/conformar
sys.path.insert(0, os.path.join(RAIZ, "motor"))
import notas as N  # noqa: E402
from drp import writer as W  # noqa: E402
from titulos import textplus as TP  # noqa: E402

SAIDA = sys.argv[1]
SIZE = float(sys.argv[2]) if len(sys.argv) > 2 else 0.035
LINHA = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
X, TOPO = 80 / 1920, 0.967
QUADRO = (1920, 1080)

V = True
NOTAS = [
    N._nota(0, 96, [[("V1 A001C003 · 3D Warp · escala X · linear", False)],
                    [("56%-75% (", False), ("56%-75%", V), ("-100%)", False)]], "conferir"),
    N._nota(24, 48, [[("V2 INSERT_CEL · Stabilize — refazer no Resolve", False)]], "refazer"),
    N._nota(48, 96, [[("V3 GRAFISMO · Matte Key", False)], [("chave de luminância: conferir", False)],
                     [("terceira linha da nota", False)]], "conferir"),
    N._nota(120, 48, [[("V1 A001C004 · Resize · escala 120%", False)]], None),
    N._nota(200, 48, [[("V1 A002C001 · sozinha (sem sobreposição)", False)]], None),
]


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _vagas(notas):
    """A vaga (faixa vertical) de cada nota: a mesma regra das trilhas de hoje — a 1ª vaga livre no tempo;
    cada vaga começa abaixo das linhas da de cima."""
    vagas = []                                   # [fim, linhas]
    onde = {}
    for i, n in sorted(enumerate(notas), key=lambda x: x[1]["inicio"]):
        k = next((j for j, v in enumerate(vagas) if v[0] <= n["inicio"]), None)
        if k is None:
            vagas.append([0, 0])
            k = len(vagas) - 1
        vagas[k][0] = n["inicio"] + n["dur"]
        vagas[k][1] = max(vagas[k][1], len(n["linhas"]))
        onde[i] = k
    topo, y = TOPO, []
    for _f, linhas in vagas:
        y.append(topo)
        topo -= linhas * LINHA
    return {i: y[k] for i, k in onde.items()}


def _texto(n):
    return "\n".join("".join(t for t, _d in linha) for linha in n["linhas"])


def _tools(camadas, fim, w, h):
    """camadas: [(nota, y, chaves_do_blend ou None)]. Background transparente → Merge por camada → MediaOut."""
    partes = [f'Background1 = Background {{ Inputs = {{ GlobalOut = Input {{ Value = {fim}, }}, '
              f'Width = Input {{ Value = {w}, }}, Height = Input {{ Value = {h}, }}, '
              f'UseFrameFormatSettings = Input {{ Value = 1, }}, TopLeftAlpha = Input {{ Value = 0, }}, '
              f'TopLeftRed = Input {{ Value = 0, }}, TopLeftGreen = Input {{ Value = 0, }}, '
              f'TopLeftBlue = Input {{ Value = 0, }}, }}, }}']
    fundo = "Background1"
    for k, (n, y, chaves) in enumerate(camadas, 1):
        # o "estamos aqui" em vermelho: modificador Character Level Styling (StyledTextCLS),
        # { código, início, fim, Value = v } — 2402/2403 = verde/azul do trecho (medido 2026-10-23, 19.1.4)
        trechos, pos = [], 0
        for li, linha in enumerate(n["linhas"]):
            if li:
                pos += 1                               # o "\n"
            for t, destaque in linha:
                if destaque:
                    trechos.append((pos, pos + len(t) - 1))      # o fim é INCLUSO
                pos += len(t)
        if trechos:
            arr = ", ".join(f"{{ {c}, {a}, {b}, Value = 0.33 }}" for a, b in trechos for c in (2402, 2403))
            partes.append(f'CLS{k} = StyledTextCLS {{ Inputs = {{ Text = Input {{ Value = "{_esc(_texto(n))}", }}, '
                          f'CharacterLevelStyling = Input {{ Value = StyledText {{ Array = {{ {arr} }}, Value = "" }}, }}, }}, }}')
            fonte_txt = f'StyledText = Input {{ SourceOp = "CLS{k}", Source = "StyledText", }}, '
        else:
            fonte_txt = f'StyledText = Input {{ Value = "{_esc(_texto(n))}", }}, '
        partes.append(
            f'Text{k} = TextPlus {{ Inputs = {{ GlobalOut = Input {{ Value = {fim}, }}, '
            f'Width = Input {{ Value = {w}, }}, Height = Input {{ Value = {h}, }}, '
            f'UseFrameFormatSettings = Input {{ Value = 1, }}, '
            + fonte_txt +
            f'Font = Input {{ Value = "Open Sans", }}, Style = Input {{ Value = "Semibold", }}, '
            f'Size = Input {{ Value = {TP._n(SIZE)}, }}, '
            f'Center = Input {{ Value = {{ {TP._n(X)}, {TP._n(y)} }}, }}, '
            f'VerticalTopCenterBottom = Input {{ Value = -1, }}, HorizontalLeftCenterRight = Input {{ Value = -1, }}, '
            f'VerticalJustificationNew = Input {{ Value = 3, }}, HorizontalJustificationNew = Input {{ Value = 0, }}, '
            f'}}, }}')
        blend = ""
        if chaves:
            kf = ", ".join(f"[{t}] = {{ {v}, Flags = {{ StepIn = true }} }}" for t, v in chaves)
            partes.append(f"Merge{k}Blend = BezierSpline {{ KeyFrames = {{ {kf} }} }}")
            blend = f'Blend = Input {{ SourceOp = "Merge{k}Blend", Source = "Value", }}, '
        partes.append(f'Merge{k} = Merge {{ Inputs = {{ {blend}'
                      f'Background = Input {{ SourceOp = "{fundo}", Source = "Output", }}, '
                      f'Foreground = Input {{ SourceOp = "Text{k}", Source = "Output", }}, }}, }}')
        fundo = f"Merge{k}"
    partes.append(f'MediaOut1 = MediaOut {{ Inputs = {{ Index = Input {{ Value = "0", }}, '
                  f'Input = Input {{ SourceOp = "{fundo}", Source = "Output", }} }}, }}')
    return "{ " + ", ".join(partes) + " }"


def _clipe(start, dur, camadas, nome):
    fim = max(0, dur - 1)
    w, h = QUADRO
    cab = TP._CABECALHO.format(fim=fim, w=w, h=h, fps="24")
    tools = _tools(camadas, fim, w, h)
    import struct
    b = TP._FORMA
    b = b.replace("<Name>Fusion Title</Name>", f"<Name>{W._xml_escape(nome[:250])}</Name>")
    b = b.replace("<Start>0</Start>", f"<Start>{int(start)}</Start>")
    b = b.replace("<Duration>1</Duration>", f"<Duration>{int(dur)}</Duration>")
    b = b.replace("<CompositionBA></CompositionBA>", f"<CompositionBA>{TP.composicao_ba(cab, tools)}</CompositionBA>")
    b = b.replace("<MediaFrameRate></MediaFrameRate>",
                  f"<MediaFrameRate>{(struct.pack('<d', 24.0) + bytes(8)).hex()}</MediaFrameRate>")
    b = b.replace("<MediaTimemapBA></MediaTimemapBA>",
                  f"<MediaTimemapBA>02{struct.pack('>d', fim / 24.0).hex()}</MediaTimemapBA>")
    return W._uniquify(b)


def _grupos(notas):
    """Notas que se tocam no tempo formam um grupo (a união)."""
    ordem = sorted(range(len(notas)), key=lambda i: notas[i]["inicio"])
    grupos, fim = [], -1
    for i in ordem:
        n = notas[i]
        if not grupos or n["inicio"] >= fim:
            grupos.append([])
        grupos[-1].append(i)
        fim = max(fim, n["inicio"] + n["dur"]) if len(grupos[-1]) > 1 else n["inicio"] + n["dur"]
    return grupos


def variante_a(notas, by_track):
    y = _vagas(notas)
    cortes = sorted({n["inicio"] for n in notas} | {n["inicio"] + n["dur"] for n in notas})
    lane = by_track.setdefault(max(by_track or {0: None}) + 1, [])
    for a, b in zip(cortes, cortes[1:]):
        ativas = [i for i, n in enumerate(notas) if n["inicio"] <= a and n["inicio"] + n["dur"] >= b]
        if not ativas:
            continue
        ativas.sort(key=lambda i: -y[i])
        camadas = [(notas[i], y[i], None) for i in ativas]
        lane.append(_clipe(a + W._TIMELINE_OFFSET_FRAMES, b - a, camadas, " ‖ ".join(notas[i]["nome"] for i in ativas)))
    return {max(by_track)}


def variante_b(notas, by_track):
    y = _vagas(notas)
    lane = by_track.setdefault(max(by_track or {0: None}) + 1, [])
    for g in _grupos(notas):
        ini = min(notas[i]["inicio"] for i in g)
        fim = max(notas[i]["inicio"] + notas[i]["dur"] for i in g)
        camadas = []
        for i in sorted(g, key=lambda i: -y[i]):
            n = notas[i]
            a, b = n["inicio"] - ini, n["inicio"] + n["dur"] - ini
            chaves = None if (a == 0 and b == fim - ini) else \
                [(0, 0 if a > 0 else 1)] + ([(a, 1)] if a > 0 else []) + ([(b, 0)] if b < fim - ini else [])
            camadas.append((n, y[i], chaves))
        lane.append(_clipe(ini + W._TIMELINE_OFFSET_FRAMES, fim - ini, camadas, " ‖ ".join(notas[i]["nome"] for i in g)))
    return {max(by_track)}


for _n in NOTAS:
    _n["inicio"] += 240
os.makedirs(SAIDA, exist_ok=True)
original = W._notas_na_timeline
for nome, fn in (("ATUAL", original), ("A_FATIADO", variante_a), ("B_UNIAO", variante_b)):
    W._notas_na_timeline = fn
    r = W.build_drt([], [], os.path.join(SAIDA, f"NOTAS_{nome}.drt"), timeline_name=f"NOTAS {nome}",
                    timeline_fps=24.0, notas=[dict(n) for n in NOTAS])
    print(nome, r.get("notas"), os.path.getsize(os.path.join(SAIDA, f"NOTAS_{nome}.drt")))
W._notas_na_timeline = original
