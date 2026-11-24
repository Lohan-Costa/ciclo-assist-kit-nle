"""A TRILHA DE NOTAS em Text+ (decisões do autor, 2026-10-23; laboratório `tools/bancada_resolve/lab_notas_textplus/`,
lab v3, medido no Resolve Studio 19.1.4.11 Win11).

Antes: um Text por nota e uma trilha nova a cada sobreposição. Agora (VARIANTE B): UMA trilha; as notas que se tocam no
tempo viram UM clipe Text+ (Fusion), cada nota uma camada que liga e desliga no quadro exato (o Blend do Merge) e que
SOBE quando a de cima acaba (os espaços fecham: um Transform com Center em degraus).

Desenho de cada nota (lab v3):
- linha 1 = a CABEÇA: trilha (azul) · nome do segmento (cor pelo TIPO de clipe; VERMELHO só se a mídia está OFFLINE —
  autor, 2026-10-24: "o vermelho já é naturalmente associado a mídia offline"; o sinal fica na descrição) · TC source
  in > out (cinza);
- linhas 2… = o corpo (efeitos), com o vermelho de destaque onde a nota pede;
- COLUNAS: nada embaixo do rótulo da trilha — o nome e o corpo começam na mesma coluna. Fonte proporcional: a coluna
  vem da LARGURA medida da fonte (`_LARGURA`, Open Sans Semibold), não de espaços;
- cada LINHA (e cada rótulo) é um Text+ no X da sua coluna; a cor por trecho vai no Character Level Styling.

⛔ O Text+ não tem fonte reserva: caractere fora da fonte sai como quadradinho. SÓ caracteres comuns (autor,
2026-10-23): `_texto_seguro` troca os conhecidos (seta, sinal de vezes, travessão) e tira o resto.
"""
from __future__ import annotations

import struct

from titulos import textplus as TP

#: Geometria (fração do quadro; Y do Fusion de BAIXO para cima). Corpo 0,035 ≈ 40 px num quadro de 1080.
SIZE, LINHA, FOLGA = 0.035, 0.05, 0.035
X, TOPO = 80 / 1920, 0.967
#: px da fonte num quadro de 1920 de largura por unidade de Size do Text+ (calibrado pela imagem no lab v3).
_PX_POR_SIZE = 39 / 0.035

#: Cores (RGB 0–1). Tipos de clipe e paleta aprovados pelo autor (lab v3); os sinais seguem a cor do aviso na
#: timeline (memória "marcar na timeline, cor local": refazer vermelho, conferir amarelo).
COR = {
    "branco": (1.0, 1.0, 1.0),
    "trilha": (0.36, 0.78, 1.0),
    "subtrilha": (0.66, 0.89, 1.0),
    "tc": (0.65, 0.65, 0.65),
    "destaque": (1.0, 0.33, 0.33),
    "video": (1.0, 1.0, 1.0), "composto": (0.73, 0.55, 1.0), "titulo": (0.42, 0.89, 0.54),
    "multicam": (1.0, 0.64, 0.30), "ajuste": (1.0, 0.48, 0.85), "rampa": (1.0, 0.85, 0.30),
    "distorcao": (1.0, 0.25, 0.25), "refazer": (1.0, 0.42, 0.25), "conferir": (1.0, 0.85, 0.30),
    "offline": (1.0, 0.25, 0.25),
}

#: Largura de cada caractere da Open Sans Semibold, em milésimos do corpo (medida pela fonte em 2026-10-23). Os
#: caracteres são os ASCII visíveis e o Latin-1 (160–255): o que a nota pode ter.
_CARACTERES = "".join(map(chr, [*range(32, 127), *range(160, 256)]))
_LARGURA = dict(zip(_CARACTERES, map(int, (
    "260 276 436 646 571 862 740 243 317 317 548 571 267 322 275 390 571 571 571 571 571 571 571 571 571 571 275 "
    "278 571 571 571 453 898 661 660 634 734 558 532 726 751 305 299 639 542 923 783 787 615 787 639 550 566 742 "
    "622 946 622 592 575 330 390 330 537 429 592 580 623 495 623 576 363 556 635 279 279 572 279 956 635 611 623 "
    "623 431 487 393 635 535 817 551 536 478 386 551 371 571 260 276 571 571 571 571 551 501 592 832 368 556 571 "
    "322 832 500 428 571 363 363 592 639 655 275 216 363 381 556 830 830 830 453 661 661 661 661 661 661 912 634 "
    "558 558 558 558 305 305 305 305 731 783 787 787 787 787 787 571 787 742 742 742 742 592 619 666 580 580 580 "
    "580 580 580 887 495 576 576 576 576 279 279 279 279 607 635 611 611 611 611 611 571 611 635 635 635 635 536 "
    "623 536").split())))
#: O que se troca antes de tirar: o que o motor de notas já escreveu um dia.
_TROCA = {"→": ">", "←": "<", "×": "x", "—": "-", "–": "-", "‖": "||", "…": "..."}


def _texto_seguro(t: str) -> str:
    t = "".join(_TROCA.get(c, c) for c in str(t))
    return "".join(c for c in t if c in _LARGURA)


def largura(texto: str) -> float:
    """Largura do texto no Text+ (corpo `SIZE`), em fração da LARGURA do quadro."""
    return sum(_LARGURA.get(c, 571) for c in texto) / 1000 * SIZE * _PX_POR_SIZE / 1920


def camadas(n: dict, nivel: int = 0) -> list[dict]:
    """As linhas de uma nota no formato do desenho: `{nivel, rotulo, trechos=[(texto, chave de COR)]}`.

    A cabeça vem de `n["cabeca_info"]` (o `notas.das_notas` a escreve); sem ela (nota montada noutro lugar), todas as
    linhas entram como corpo. No corpo, o destaque é `True` (vermelho), `False`/`None` (branco) ou uma chave de COR.
    A nota de um COMPOUND (`aninhar`) traz os `filhos`: cada um entra embaixo, um nível para dentro, com o rótulo da
    trilha de dentro (V2.1, V2.2…)."""
    info = n.get("cabeca_info")
    pula = int(n.get("cabeca") or 0) if info else 0
    fora = []
    if info:
        # o nome na cor do TIPO; vermelho é a mídia offline (autor, 2026-10-24) — o sinal (Stretch…) vai no corpo
        cor_nome = "offline" if info.get("offline") else info.get("tipo") or "video"
        trechos = [(info.get("nome") or "", cor_nome)]
        if info.get("src"):
            trechos += [("  ", "branco"), (f"{info['src'][0]} > {info['src'][1]}", "tc")]
        fora.append({"nivel": nivel, "rotulo": n.get("rotulo") or info.get("trilha") or None, "trechos": trechos})
    for linha in (n.get("linhas") or [])[pula:]:
        fora.append({"nivel": nivel, "rotulo": None, "trechos": [
            (t, d if isinstance(d, str) and d in COR else ("destaque" if d is True else "branco")) for t, d in linha]})
    for l in fora:
        l["rotulo"] = _texto_seguro(l["rotulo"]) if l["rotulo"] else None
        l["trechos"] = [(_texto_seguro(t), c) for t, c in l["trechos"] if _texto_seguro(t)]
    for f in n.get("filhos") or []:
        fora += camadas(f, nivel + 1)
    return fora


_FORCA = ("distorcao", "refazer", "conferir")


def aninhar(notas: list[dict], segmentos: list) -> list[dict]:
    """As notas dos clipes de DENTRO de um compound (segmentos com `composto = {id, nome}`, o nest do Premiere)
    viram UMA nota do compound por trecho de tempo: a cabeça "V<trilha> · <nome do nest>" e, embaixo, cada clipe de
    dentro com nota, recuado, rótulo V<trilha>.<k> (formato v2, autor 2026-10-23). A trilha de fora é a mais BAIXA do
    grupo — onde o Resolve deixa o Compound Clip (banco, resolve-scripting/api-scripting.md); `k` conta as trilhas de
    dentro de baixo para cima. Só a trilha de notas usa isto: marcadores e cor local continuam por clipe."""
    def seg(i):
        return segmentos[i] if isinstance(i, int) and 0 <= i < len(segmentos or []) else None

    por: dict = {}
    fora = []
    for n in notas:
        s = seg(n.get("segmento")) or {}
        c = s.get("composto")
        if c and c.get("id") is not None and not s.get("is_audio"):
            por.setdefault(c["id"], (c, []))[1].append((n, s))
        else:
            fora.append(n)
    for cid, (c, lista) in por.items():
        trilhas = sorted({int(s.get("track") or 0) for s in segmentos or []
                          if s and (s.get("composto") or {}).get("id") == cid and not s.get("is_audio")
                          and not s.get("is_gap") and not s.get("is_transition")})
        base = trilhas[0]
        k = {t: j + 1 for j, t in enumerate(trilhas)}
        cortes = sorted({int(n["inicio"]) for n, _s in lista} | {int(n["inicio"]) + max(1, int(n["dur"])) for n, _s in lista})
        ordem = min(n.get("ordem", n["inicio"]) for n, _s in lista)
        anterior = None
        for a, b in zip(cortes, cortes[1:]):
            ativos = sorted(((n, s) for n, s in lista if int(n["inicio"]) <= a < int(n["inicio"]) + max(1, int(n["dur"]))),
                            key=lambda x: (int(x[1].get("track") or 0), int(x[0]["inicio"])))
            if not ativos:
                anterior = None
                continue
            chave = [id(n) for n, _s in ativos]
            if anterior is not None and anterior["_chave"] == chave and anterior["inicio"] + anterior["dur"] == a:
                anterior["dur"] = b - anterior["inicio"]          # o mesmo conjunto: só estende
                continue
            # o de dentro é o clipe dele: o tipo "composto" (que `notas._tipo` dá a quem mora num nest) vira vídeo
            filhos = [{**n, "rotulo": f"V{base}.{k.get(int(s.get('track') or 0), 1)}",
                       "cabeca_info": {**(n.get("cabeca_info") or {}),
                                       "tipo": "video" if (n.get("cabeca_info") or {}).get("tipo") in (None, "composto")
                                       else n["cabeca_info"]["tipo"]}} for n, s in ativos]
            cor = next((x for x in _FORCA if any(f.get("cor") == x for f in filhos)), None)
            info = {"trilha": f"V{base}", "nome": c.get("nome") or "Compound Clip", "tipo": "composto", "src": None}
            linhas = [[(f"V{base} {info['nome']}", False)],
                      [(f"Compound Clip · {len(trilhas)} trilha{'s' if len(trilhas) != 1 else ''} dentro", False)]]
            anterior = {"inicio": a, "dur": b - a, "cor": cor, "grupo": "efeito", "segmento": None, "ordem": ordem,
                        "cabeca": 1, "cabeca_info": info, "linhas": linhas, "filhos": filhos, "_chave": chave,
                        "nome": " | ".join("".join(t for t, _d in l) for l in linhas)}
            fora.append(anterior)
    for n in fora:
        n.pop("_chave", None)
    return fora


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _colunas(linhas: list[dict]) -> tuple[dict, dict]:
    """X do rótulo e X do conteúdo por nível: o conteúdo começa depois do MAIOR rótulo do nível (+ um espaço); o
    rótulo do nível de dentro começa na coluna do conteúdo de fora."""
    xr, xc = {}, {}
    for nivel in sorted({l["nivel"] for l in linhas}):
        xr[nivel] = X if nivel == 0 else xc.get(nivel - 1, X)
        rotulos = [largura(l["rotulo"] + " ") for l in linhas if l["nivel"] == nivel and l["rotulo"]]
        xc[nivel] = xr[nivel] + (max(rotulos) if rotulos else 0)
    return xr, xc


def _altura(linhas: list) -> float:
    return len(linhas) * LINHA + FOLGA


def _degraus(chaves: list) -> str:
    return ", ".join(f"[{t}] = {{ {TP._n(v)}, Flags = {{ StepIn = true }} }}" for t, v in chaves)


def _texto(k: int, x: float, y: float, trechos: list, fim: int, quadro: tuple[int, int]) -> list[str]:
    """Um Text+ de uma linha; a cor por trecho no Character Level Styling (índices do 1º ao ÚLTIMO caractere)."""
    w, h = quadro
    texto = "".join(t for t, _c in trechos)
    arr, pos = [], 0
    for t, c in trechos:
        rgb = COR.get(c, COR["branco"])
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
    txt = (f'T{k} = TextPlus {{ Inputs = {{ GlobalOut = Input {{ Value = {fim}, }}, '
           f'Width = Input {{ Value = {w}, }}, Height = Input {{ Value = {h}, }}, UseFrameFormatSettings = Input {{ Value = 1, }}, '
           + fonte +
           f'Font = Input {{ Value = "Open Sans", }}, Style = Input {{ Value = "Semibold", }}, Size = Input {{ Value = {TP._n(SIZE)}, }}, '
           f'Center = Input {{ Value = {{ {TP._n(x)}, {TP._n(y)} }}, }}, '
           f'VerticalTopCenterBottom = Input {{ Value = -1, }}, HorizontalLeftCenterRight = Input {{ Value = -1, }}, '
           f'VerticalJustificationNew = Input {{ Value = 3, }}, HorizontalJustificationNew = Input {{ Value = 0, }}, }}, }}')
    return [p for p in (cls, txt) if p]


def _ordem(n: dict) -> tuple:
    """Quem fica em cima: a nota do segmento que começou antes (os pedaços de um segmento cortado nos keyframes
    guardam o lugar dele), depois a trilha mais baixa."""
    trilha = str((n.get("cabeca_info") or {}).get("trilha") or "")
    num = int("".join(c for c in trilha.split(".")[0] if c.isdigit()) or 0)
    return (n.get("ordem", n["inicio"]), num, n["inicio"])


def clipe(grupo: list[dict], fps: float, quadro: tuple[int, int], offset: int) -> str:
    """O `Sm2TiVideoClip` (DbIds por trocar) de um GRUPO de notas que se tocam no tempo."""
    ini = min(int(n["inicio"]) for n in grupo)
    fim_tl = max(int(n["inicio"]) + max(1, int(n["dur"])) for n in grupo)
    dur = fim_tl - ini
    w, h = quadro
    linhas_de = [camadas(n) for n in grupo]
    cortes = sorted({ini, fim_tl} | {int(n["inicio"]) for n in grupo}
                    | {int(n["inicio"]) + max(1, int(n["dur"])) for n in grupo})
    ordem = sorted(range(len(grupo)), key=lambda i: _ordem(grupo[i]))
    dy = {i: [] for i in ordem}
    vis = {i: [] for i in ordem}
    for a in cortes[:-1]:
        topo = TOPO
        for i in ordem:
            n = grupo[i]
            ativa = int(n["inicio"]) <= a < int(n["inicio"]) + max(1, int(n["dur"]))
            vis[i].append((a - ini, 1 if ativa else 0))
            if ativa:
                dy[i].append((a - ini, 0.5 + (topo - TOPO)))        # Center do Transform: 0,5 = no lugar
                topo -= _altura(linhas_de[i])
    partes = [f'Background1 = Background {{ Inputs = {{ GlobalOut = Input {{ Value = {dur - 1}, }}, '
              f'Width = Input {{ Value = {w}, }}, Height = Input {{ Value = {h}, }}, UseFrameFormatSettings = Input {{ Value = 1, }}, '
              f'TopLeftAlpha = Input {{ Value = 0, }}, TopLeftRed = Input {{ Value = 0, }}, TopLeftGreen = Input {{ Value = 0, }}, '
              f'TopLeftBlue = Input {{ Value = 0, }}, }}, }}']
    fundo, k = "Background1", 0
    for j, i in enumerate(ordem, 1):
        linhas = linhas_de[i]
        if not linhas:
            continue
        xr, xc = _colunas(linhas)
        base = None
        for li, l in enumerate(linhas):
            y = TOPO - li * LINHA                      # a nota desenhada no TOPO; o Transform a desce
            pedacos = []
            if l["rotulo"]:
                pedacos.append((xr[l["nivel"]], [(l["rotulo"], "trilha" if l["nivel"] == 0 else "subtrilha")]))
            if l["trechos"]:
                pedacos.append((xc[l["nivel"]], l["trechos"]))
            for x, trechos in pedacos:
                k += 1
                partes += _texto(k, x, y, trechos, dur - 1, quadro)
                if base is None:
                    base = f"T{k}"
                else:
                    partes.append(f'L{k} = Merge {{ Inputs = {{ Background = Input {{ SourceOp = "{base}", Source = "Output", }}, '
                                  f'Foreground = Input {{ SourceOp = "T{k}", Source = "Output", }}, }}, }}')
                    base = f"L{k}"
        if base is None:
            continue
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
    cab = TP._CABECALHO.format(fim=dur - 1, w=w, h=h, fps=TP._n(fps))
    # o NOME do clipe é o que a timeline mostra: o texto corrido das notas, de cima para baixo
    nome = " || ".join(" | ".join(((l["rotulo"] + " ") if l["rotulo"] else "") + "".join(t for t, _c in l["trechos"])
                                  for l in linhas_de[i]) for i in ordem)
    b = TP._FORMA
    b = b.replace("<Name>Fusion Title</Name>", f"<Name>{_xml(nome[:250])}</Name>")
    b = b.replace("<Start>0</Start>", f"<Start>{ini + offset}</Start>")
    b = b.replace("<Duration>1</Duration>", f"<Duration>{dur}</Duration>")
    b = b.replace("<CompositionBA></CompositionBA>", f"<CompositionBA>{TP.composicao_ba(cab, tools)}</CompositionBA>")
    b = b.replace("<MediaFrameRate></MediaFrameRate>",
                  f"<MediaFrameRate>{(struct.pack('<d', float(fps)) + bytes(8)).hex()}</MediaFrameRate>")
    b = b.replace("<MediaTimemapBA></MediaTimemapBA>",
                  f"<MediaTimemapBA>02{struct.pack('>d', (dur - 1) / float(fps)).hex()}</MediaTimemapBA>")
    return b


def _xml(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def grupos(notas: list[dict]) -> list[list[dict]]:
    """As notas que se TOCAM no tempo, juntas (variante B): cada grupo vira um clipe."""
    fora, fim = [], -1
    for n in sorted(notas, key=lambda n: int(n["inicio"])):
        if not fora or int(n["inicio"]) >= fim:
            fora.append([])
            fim = -1
        fora[-1].append(n)
        fim = max(fim, int(n["inicio"]) + max(1, int(n["dur"])))
    return fora
