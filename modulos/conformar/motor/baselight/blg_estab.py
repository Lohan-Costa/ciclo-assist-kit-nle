"""O Stabilize do MC no TRACKER NATIVO do Baselight, igual ao render do MC — as contas no texto do BLG (Baselight 7.0.3;
laboratório de 2026-11-23, banco `plugins/baselight/README.md` § "O Stabilize do Media Composer no Baselight").

Só stdlib: roda no python da FilmLight (`estabilizar_flapi.py`) e nos testes. O desenho (decisão do autor, 2026-11-23:
o tracker nativo, "compensa"):
  - o tracker nativo (faixa Tracker + Transform com Stabilise ligado) recebe o RASTREIO do MC, ponto por quadro;
  - Filtering Shake 0 · **Motion 0** · Threshold 0,7: o Baselight trava a imagem no quadro 0 — exato e previsível
    (−(p − p₀), medido 0,16 px). ⛔ O Motion 1 devolve o lento por um filtro que não é o do MC e que não se prevê pelo
    rastreio (filtro linear ajustado no C013 erra 0,8–1,5 px no teste cruzado);
  - o Transform leva a escala Z fixa (o Auto-Zoom do MC) e a posição POR QUADRO = o lento do MC + o deslocamento d
    (`posicoes`). ⭐ O tracker do Baselight desloca DEPOIS da escala (px de tela, não × Z): daí o termo (Z − 1).
Medido × o vid ref (PRODUCAO-A): C011 0,01/0,01 px, C013 0,22/0,04 px — os números do render do próprio MC.
"""
from __future__ import annotations

import base64
import math
import os
import re
import struct
import zlib

MOLDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moldes", "estabilizador_nativo.txt")
#: o Filtering que o Ciclo grava (Shake/Noise, Motion, Threshold)
FILTERING = (0.0, 0.0, 0.7)


# ── o payload ───────────────────────────────────────────────────────────────────────────────────────────────────────
def ler(payload: str) -> str:
    b = base64.b64decode(payload.strip())
    return zlib.decompress(b[8:]).decode("latin1")


def gravar(texto: str) -> str:
    t = texto.encode("latin1")
    return base64.b64encode(struct.pack("<Q", len(t)) + zlib.compress(t)).decode()


# ── a conta ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def gauss_nearest(v: list[float], sigma: float) -> list[float]:
    """O Gauss do MC com a borda "nearest" (o mesmo do `motor/estabilizacao._gauss_nearest`)."""
    if sigma <= 0:
        return list(v)
    r = int(math.ceil(4 * sigma))
    k = [math.exp(-0.5 * (j / sigma) ** 2) for j in range(-r, r + 1)]
    s = sum(k)
    n = len(v)
    return [sum(k[j + r] * v[min(max(i + j, 0), n - 1)] for j in range(-r, r + 1)) / s for i in range(n)]


def posicoes(p_x: list[float], p_y: list[float], zoom: float, filtro: float, pos: list[float],
             w: int, h: int) -> tuple[list[float], list[float]]:
    """A posição do Transform por quadro (px, Y para baixo), com o tracker travado no quadro 0:
    X(k) = W/2 + Z·(G(pₓ)(k) − pₓ(0)) − (Z − 1)·(pₓ(k) − pₓ(0)) − dₓ·W·Z  (Y igual, com H).
    `p_x/p_y` = o rastreio do MC em px; `pos` = o deslocamento do MC (milésimos); G = Gauss σ = 30·filtro."""
    z = float(zoom)
    sig = 30.0 * float(filtro)
    gx, gy = gauss_nearest(p_x, sig), gauss_nearest(p_y, sig)
    dx, dy = -pos[0] / 1000.0 / z, pos[1] / 1000.0 / z
    x0, y0 = p_x[0], p_y[0]
    xs = [w / 2 + z * (g - x0) - (z - 1) * (q - x0) - dx * w * z for g, q in zip(gx, p_x)]
    ys = [h / 2 + z * (g - y0) - (z - 1) * (q - y0) - dy * h * z for g, q in zip(gy, p_y)]
    return xs, ys


def no_formato(plano: dict, w: int, h: int) -> dict:
    """O plano no formato de TRABALHO da scene: o rastreio e as posições são px dele. ⛔ O raster do xmeml (o do 1º
    arquivo: 4128×2176 num BRAW da PRODUCAO-A) NÃO é o da scene (HD 1920×1080): com ele o movimento foi 2,15× maior e o
    plano saiu pior que sem estabilizar (medido pela janela do app, 2026-11-23)."""
    if (int(plano["w"]), int(plano["h"])) == (int(w), int(h)):
        return plano
    fx, fy = w / float(plano["w"]), h / float(plano["h"])
    return {**plano, "p_x": [v * fx for v in plano["p_x"]], "p_y": [v * fy for v in plano["p_y"]], "w": int(w), "h": int(h)}


# ── os objetos do BLG ───────────────────────────────────────────────────────────────────────────────────────────────
def objetos(texto: str) -> dict[int, tuple[str, list[int], str]]:
    """{id: (tipo, filhos, a linha inteira)} — filhos lidos do cabeçalho `<n>:<tipo> <n>:<sub> rev N ids…`."""
    out = {}
    for m in re.finditer(r'^\s*\((\d+)\)="(.*?)",\s*$', texto, re.M | re.S):
        corpo = m.group(2)
        tl = int(corpo.split(":", 1)[0])
        tipo = corpo.split(":", 1)[1][:tl]
        resto = corpo.split(":", 1)[1][tl + 1:]
        sl = int(resto.split(":", 1)[0])
        resto = resto.split(":", 1)[1][sl + 1:]
        toks = resto.split(" ")
        n = int(toks[1])
        out[int(m.group(1))] = (tipo, [int(x) for x in toks[2:2 + n]], m.group(0))
    return out


def _desc(objs: dict, raiz: int, vistos: list[int]) -> None:
    if raiz == 0 or raiz in vistos or raiz not in objs:
        return
    vistos.append(raiz)
    for f in objs[raiz][1]:
        _desc(objs, f, vistos)


def _renumerar(linha: str, mapa: dict[int, int]) -> str:
    m = re.match(r'(\s*)\((\d+)\)="(\d+:)(.*)', linha, re.S)
    ind, oid, pre, resto = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    tl = int(pre[:-1])
    tipo = resto[:tl]
    resto = resto[tl + 1:]
    sl = int(resto.split(":", 1)[0])
    sub = resto.split(":", 1)[1][:sl]
    resto = resto.split(":", 1)[1][sl + 1:]
    toks = resto.split(" ")
    n = int(toks[1])
    toks[2:2 + n] = [str(mapa.get(int(x), int(x))) if x != "0" else "0" for x in toks[2:2 + n]]
    return f'{ind}({mapa[oid]})="{pre}{tipo} {sl}:{sub} ' + " ".join(toks)


def tem_tracker(texto: str) -> bool:
    return "GR_TrackerRop" in texto


def enxertar(texto: str, molde: str) -> str:
    """As faixas Transform + Tracker do molde no BLG do plano: ids novos, a duração do plano; as faixas do plano sobem
    (imagem em cima, Tracker 1, Transform 0 — como a interface faz). Fora dos objetos o BLG só difere no offset e na
    duração, que já são os do plano."""
    om = objetos(molde)
    faixas = sorted(i for i, (tp, fl, _) in om.items() if tp == "GM_Strip"
                    and any(om.get(f, ("",))[0] in ("GR_TransformRop", "GR_TrackerRop") for f in fl))
    leva: list[int] = []
    for f in faixas:
        _desc(om, f, leva)
    prox = max(int(x) for x in re.findall(r'^\s*\((\d+)\)=', texto, re.M)) + 1
    mapa = {o: prox + k for k, o in enumerate(leva)}
    recuo = re.search(r'^([ \t]*)\(\d+\)="', texto, re.M).group(1)          # o recuo das linhas do próprio BLG
    novos = [recuo + _renumerar(om[o][2], mapa).strip() for o in leva]
    dur = re.search(r'8:GM_Strip 2:gm \d+ 1 \d+ 1 o 0 \S+ (\S+) ', texto).group(1)
    novos = [re.sub(r'(8:GM_Strip 2:gm \d+ 1 \d+ 1 o 0 \S+ )\S+ ', rf'\g<1>{dur} ', ln) for ln in novos]
    sobe = len(faixas)
    for m in list(re.finditer(r'\((\d+)\)="8:GM_Strip 2:gm (\d+) 1 (\d+) 1 o 0 (\S+) (\S+) (\d+) f f 0 "', texto)):
        texto = texto.replace(m.group(0), m.group(0).replace(f"{m.group(5)} {m.group(6)} f f 0",
                                                             f"{m.group(5)} {int(m.group(6)) + sobe} f f 0"))
    tl = re.search(r'\((\d+)\)="11:GM_Timeline 2:gm (\d+) (\d+) ([\d ]+?) (0 0 \d+[\d ]*) ",', texto)
    filhos = [int(x) for x in tl.group(4).split()]
    antigas = [f for f in filhos if re.search(rf'\({f}\)="8:GM_Strip', texto)]
    i = max(filhos.index(f) for f in antigas)
    filhos2 = filhos[:i + 1] + [mapa[f] for f in faixas] + filhos[i + 1:]
    n = len(antigas) + len(faixas)
    resto = filhos2[n:]
    est = f"0 0 {n} {n} 0 {n} {n + 1} {len(resto) - 2} " + " ".join(str(n + 2 + k) for k in range(len(resto) - 2))
    texto = texto.replace(tl.group(0), f'({tl.group(1)})="11:GM_Timeline 2:gm {tl.group(2)} {len(filhos2)} '
                                       f'{" ".join(map(str, filhos2))} {est} ",')
    fim = texto.find(" ],", texto.find("blg_ObjectStrings"))
    return texto[:fim] + "\n".join(ln if ln.rstrip().endswith(",") else ln + "," for ln in novos) + "\n" + texto[fim:]


def _h(v: float) -> str:
    return struct.pack(">d", float(v)).hex()


def rastreio(texto: str, px: list[float], py: list[float], fps: float, w: int = 1920) -> str:
    """O `TRACK_TrackOutputInterp` com o rastreio do MC: o cabeçalho de 18 campos (o ponto de referência nas posições
    9/10 = o do quadro 0), `0 <N>` e um registro de 14 campos por quadro 1..n−1 (tempo k/fps, X, Y, X e Y do anterior,
    dX, dY, `t`, dX/2, dY/2 — `inferido` da amostra —, 4 de erro = 0) e o terminador."""
    m = re.search(r'(\(\d+\)="23:TRACK_TrackOutputInterp 5:track )(.*?)(",)', texto, re.S)
    tok = m.group(2).split()
    assert tok[7] == "1" and tok[18] == "0" and len(tok[9]) == 16 == len(tok[10]), tok[:20]
    cab = tok[:18]
    cab[9], cab[10] = _h(px[0]), _h(py[0])
    # ⭐ os campos 5/6 = 1/LARGURA do formato de trabalho (a amostra HD tem 1/1920): o Baselight normaliza o ponto por
    # eles — numa scene UHD com 1/1920 o tracker deslocou o DOBRO (o resto = −(p − p₀), medido 2026-11-23)
    cab[5] = cab[6] = _h(1.0 / w)
    regs: list[str] = []
    for k in range(1, len(px)):
        dx, dy = px[k] - px[k - 1], py[k] - py[k - 1]
        regs += [_h(k / fps), _h(px[k]), _h(py[k]), _h(px[k - 1]), _h(py[k - 1]), _h(dx), _h(dy), "t",
                 _h(dx / 2), _h(dy / 2), _h(0), _h(0), _h(0), _h(0)]
    fim = [_h(-1)] + [_h(0)] * 6 + ["t"] + [_h(0)] * 6
    corpo = " ".join(cab + ["0", str(len(px))] + regs + fim) + " "
    return texto[:m.start()] + m.group(1) + corpo + m.group(3) + texto[m.end():]


def _num(v: float) -> str:
    s = "%.20g" % float(v)
    return s.rstrip("0").rstrip(".") if "." in s and "e" not in s else s


def constante(v: float) -> str:
    corpo = f"6 0 0 0 0 -1 0.001 {_num(v)} "              # o tamanho conta o espaço do fim
    return f"f {_h(v)} {len(corpo)}:{corpo}"


def chaves(valores: list[float], fps: float) -> str:
    """Uma chave por quadro do plano (tangentes zeradas = linear) — o formato do Retime/da shape."""
    ch = " ".join(f"{_num(k / fps)} {_num(v)} 0 0 0 0" for k, v in enumerate(valores))
    c = f"6 0 {len(valores)} {ch} 0 17 -1 0.0010000000000000000208 0 "
    return f"t 0000000000000000 {len(c)}:{c}"


def curva(texto: str, oid: int, entrada: str) -> str:
    """Troca a curva INTEIRA do `GM_Bezier1dInterp` `oid`, constante (`f <hex> N:…`) ou animada (`t <hex> N:…`): o N diz
    o tamanho do corpo. ⛔ Uma regex de constante não pega a animada: a 2ª passada não mudava nada, calada."""
    m = re.search(r'\(%d\)="17:GM_Bezier1dInterp 2:gm 1 0 0 ([ft]) [0-9a-f]{16} (\d+):' % oid, texto)
    if not m:
        raise ValueError(f"a curva {oid} não está no formato conhecido")
    return texto[:m.start(1)] + entrada + texto[m.end() + int(m.group(2)):]


def _ids_transform(texto: str) -> tuple[int, int, int, int]:
    m = re.search(r'BEZ_Transform2dInterp 3:bez 2 8 (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) ', texto)
    if not m:
        raise ValueError("o Transform com o tracker não está no plano")
    _, isx, isy, _, ix, iy = (int(g) for g in m.groups())
    return isx, isy, ix, iy


def montar(texto: str, molde: str, plano: dict, fps: float) -> str:
    """O BLG do plano com o estabilizador do MC. `plano`: {p_x, p_y (px), zoom, filtro, pos, w, h}."""
    if not tem_tracker(texto):
        texto = enxertar(texto, molde)
    texto = rastreio(texto, plano["p_x"], plano["p_y"], fps, int(plano["w"]))
    core = re.search(r'TRACK_Transform2dInterpCore 5:track 1 4 (\d+) (\d+) (\d+) ', texto)
    for oid, v in zip(core.groups(), FILTERING):
        texto = curva(texto, int(oid), constante(v))
    w = int(plano["w"])
    xs, ys = posicoes(plano["p_x"], plano["p_y"], plano["zoom"], plano["filtro"], plano["pos"], w, int(plano["h"]))
    isx, isy, ix, iy = _ids_transform(texto)
    z = float(plano["zoom"])
    for oid, ent in ((isx, constante(z)), (isy, constante(z)),          # a posição no BLG é px / LARGURA nos dois eixos
                     (ix, chaves([v / w for v in xs], fps)), (iy, chaves([v / w for v in ys], fps))):
        texto = curva(texto, oid, ent)
    return texto


def conferir(texto: str, plano: dict, fps: float) -> bool:
    """O que voltou do Baselight é o que foi gravado: o tracker, o Motion 0, a escala e a 1ª e a última posição."""
    if not tem_tracker(texto):
        return False
    w = int(plano["w"])
    xs, ys = posicoes(plano["p_x"], plano["p_y"], plano["zoom"], plano["filtro"], plano["pos"], w, int(plano["h"]))
    isx, _isy, ix, iy = _ids_transform(texto)

    def valores(oid: int) -> list[float]:
        m = re.search(r'\(%d\)="17:GM_Bezier1dInterp 2:gm 1 0 0 ([ft]) ([0-9a-f]{16}) (\d+):(6 0 (\d+) )' % oid, texto)
        if m.group(1) == "f":
            return [struct.unpack(">d", bytes.fromhex(m.group(2)))[0]]
        n = int(m.group(5))
        toks = texto[m.end(4):m.end(4) + int(m.group(3))].split()
        return [float(toks[6 * k + 1]) for k in range(n)]

    vx, vy = valores(ix), valores(iy)
    core = re.search(r'TRACK_Transform2dInterpCore 5:track 1 4 (\d+) (\d+) (\d+) ', texto)
    return (len(vx) == len(xs) and abs(vx[0] - xs[0] / w) < 1e-9 and abs(vx[-1] - xs[-1] / w) < 1e-9
            and abs(vy[-1] - ys[-1] / w) < 1e-9 and abs(valores(isx)[0] - float(plano["zoom"])) < 1e-9
            and abs(valores(int(core.group(2)))[0]) < 1e-12)
