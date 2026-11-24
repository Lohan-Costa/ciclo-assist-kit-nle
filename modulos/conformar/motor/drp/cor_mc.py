"""O COLOR CORRECTION do Media Composer → a página Color do Resolve, EDITÁVEL (autor, 2026-11-20: controles editáveis com
LUT de reserva; o Resolve primeiro).

O que vai (o que o laboratório provou na carta B24, Resolve Studio 19.1.4, `laboratorio-de-midia/resultados/B24_COR_MC/
RESOLVE.md`; o CC real da PRODA, Sat 87,5 + curva, erra 0,29–0,45 código de média dentro de 16–235):

    Mas Sat S (%)                      → nó 1 "MC Master": Saturation = S/100
    Curves › Master (Catmull-Rom, t = código/255)
                                       → nó 2 "MC Curva": curva Custom R, G e B com a MESMA lista Bézier (exata: a troca
                                         dos eixos é afim), Lum Mix 0

DOIS nós porque num nó só o Resolve faz a curva ANTES da Sat, e o MC faz HSL → Curvas. O `Body` montado vai num `.drx`
mínimo por `ApplyGradeFromDRX` (o caminho do `drp/estabilizador.py`) — o grade inteiro do clipe é TROCADO, então isto
roda ANTES das LUTs e da estabilização. ⛔ A forma da curva Custom: UM campo 8 com os pontos repetidos no campo 1 (a forma
antiga do banco DERRUBOU o Resolve no `ApplyGradeFromDRX`; banco `drt-drp/estruturas.md`, CORRIGE de 2026-11-20).

`pendente`: o cabeçalho do grafo leva 1920 × 1080 (o medido; a Sat e a curva não dependem do tamanho, a confirmar numa
timeline de outro tamanho); o corte em 16–235 do Resolve × o super-branco do MC (o render corta, o MC guarda).
"""
from __future__ import annotations

import os
import struct


#: ids dos controles (banco `drt-drp/estruturas.md`; conferidos no Body do SetCDL do 19.1.4, 2026-11-20)
SAT = 0x06000005
LUM_MIX = 0x8600000B
CURVA = {"R": 0x86000506, "G": 0x86000507, "B": 0x86000508}
FLAG = {"R": 0x860000BD, "G": 0x860000BE, "B": 0x860000BF}
SENTINELA, ESCALA = -1024.0, 1023.0
#: o eixo da curva Custom: 0–1 da curva = valor C0 + W·u da imagem (banco, 2026-10-11; confirmado na B24)
EIXO_C0, EIXO_W = 0.00649, 1.01792
#: a POWER WINDOW circular (banco `drt-drp/estruturas.md` §POWER WINDOW, 19.1.4, 2026-11-20; escrita e medida pelo pixel):
#: o nó leva uma lista de correctors no campo 9 — tipo 1 = Primaries (a cor), tipo 4 = Window (só a seleção)
JANELA = {"tamanho": 0x08500006, "aspecto": 0x08500004, "pan": 0x0850000B, "tilt": 0x0850000C, "rotacao": 0x08500001,
          "soft": 0x08500005}
JANELA_TIPO, JANELA_INVERTIDA, JANELA_RAIO = 0x88500008, 0x88500009, 288.0     # 288 px = o raio com Size 50 (s = 1)
GAIN = 0x06000020
#: o blob `Curves Master` (o `data` do AVUP) = 16 pares (x, y) em double LE; 256 = 0 e 766 = 1 (banco `avb/color-correction.md`)
CURVA_0, CURVA_1 = 256.0, 766.0


# ── ler o CC do MC (o AAF; os mesmos parâmetros da bin) ───────────────────────────────────────────────────────────────
#: o que o CC grava sempre, ou só para dizer que o grupo está ligado — não é cor
_CONTABILIDADE = {"Relationship Type", "AvidParameterByteOrder", "Modification Date", "MC AVX2 EFFECT VERSION",
                  "AvidEffectID", "HSL Bypass", "HSL Setup Bypass", "HSL Setup Master Bypass", "Curves Bypass",
                  "Curves Master Bypass", "Num Master Curve Keys", "Curves Master", "Mas Sat"}
#: ⛔ sem as TRÊS o MC ignora o HSL inteiro (banco: tirar qualquer uma desliga); a curva, o mesmo padrão (`inferido`)
_LIGA_HSL = ("HSL Bypass", "HSL Setup Bypass", "HSL Setup Master Bypass")
_LIGA_CURVA = ("Curves Bypass", "Curves Master Bypass")


def pontos_do_blob(dados: bytes, n: int) -> list[tuple[float, float]] | None:
    """Os `n` pontos (t, y) em 0–1 da curva Master. Aceita o AVUP inteiro ('PUVA' + cabeçalho de 40 bytes) ou o `data`."""
    b = bytes(dados)
    off = b.find(b"PUVA")
    if off >= 0 and len(b) - off >= 40:
        tam = int.from_bytes(b[off + 36:off + 40], "little")
        b = b[off + 40:off + 40 + tam]
    if len(b) < 256 or not 2 <= n <= 16:
        return None
    v = struct.unpack("<32d", b[:256])
    pts = [((v[2 * i] - CURVA_0) / (CURVA_1 - CURVA_0), (v[2 * i + 1] - CURVA_0) / (CURVA_1 - CURVA_0)) for i in range(n)]
    return sorted(pts) if all(-0.01 <= x <= 1.01 for x, _ in pts) else None


def ler_cc(params: dict) -> dict:
    """`params` = {nome do parâmetro: (valor, animado, bytes crus ou None)} → `{"sat": S ou None, "curva": [(t, y)] ou
    None, "nao": [o que não vai]}`. Só o que sai do padrão é gravado (banco), então todo nome fora da contabilidade é
    um controle mexido que ainda não se traduz."""
    nao = sorted(n for n in params if n not in _CONTABILIDADE)
    animados = sorted(n for n, (_v, anim, _b) in params.items() if anim)
    if animados:
        nao.append("keyframe em " + ", ".join(animados))
    sat = curva = None
    if "Mas Sat" in params and all(n in params for n in _LIGA_HSL):
        try:
            sat = float(params["Mas Sat"][0])
        except (TypeError, ValueError):
            nao.append("Mas Sat ilegível")
        if sat is not None and abs(sat - 100.0) < 1e-9:
            sat = None
    if "Curves Master" in params and all(n in params for n in _LIGA_CURVA):
        try:
            n = int(params.get("Num Master Curve Keys", (0, False, None))[0])
        except (TypeError, ValueError):
            n = 0
        curva = pontos_do_blob(params["Curves Master"][2] or b"", n)
        if curva is None:
            nao.append("curva Master ilegível")
        elif all(abs(x - y) < 1e-6 for x, y in curva):
            curva = None
    return {"sat": sat, "curva": curva, "nao": nao}


# ── o Body ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _campo(f: int, v) -> dict:
    if isinstance(v, int):
        return {"field": f, "wire": 0, "value": v}
    if isinstance(v, float):
        return {"field": f, "wire": 5, "value": struct.pack("<f", v)}
    return {"field": f, "wire": 2, "value": v}


def _msg(*pares) -> list[dict]:
    return [_campo(f, v) for f, v in pares]


def _p_f32(pid: int, v: float) -> dict:
    return _campo(3, _msg((1, pid), (2, _msg((1, float(v))))))


def _p_int(pid: int, n: int) -> dict:
    return _campo(3, _msg((1, pid), (2, _msg((2, int(n))))))


def _p_curva(pid: int, lista: list[tuple[float, float]]) -> dict:
    """`{1: id, 2: {8: {1: ponto, 1: ponto, …}}}` — UM campo 8; ponto `{1: x, 2: y}` em f32 na escala 0–1023, o ZERO
    omitido, a sentinela na frente (lido de uma curva feita na UI do 19.1.4)."""
    pts = [(SENTINELA, SENTINELA)] + [(x * ESCALA, y * ESCALA) for x, y in lista]
    ponto = [_campo(1, [_campo(k, float(v)) for k, v in ((1, x), (2, y)) if v != 0.0]) for x, y in pts]
    return _campo(3, _msg((1, pid), (2, _msg((8, ponto)))))


def _curvas_rgb(lista: list[tuple[float, float]]) -> list[dict]:
    meio = (len(lista) - 4) // 3
    assert len(lista) == 4 + 3 * meio, f"lista Bézier com {len(lista)} pontos (tem de ser 4 + 3k)"
    out = []
    for c in "RGB":
        out += [_p_curva(CURVA[c], lista), _p_int(FLAG[c], 2 * meio)]
    return out + [_p_f32(LUM_MIX, 0.0)]           # sem a Lum Mix 0 as curvas R/G/B preservam a luma (banco)


def _corretor(tipo: int, params: list[dict]) -> tuple:
    return (1, _msg((1, tipo), (3, 1), (6, _msg((2, _msg((1, 1)) + params)))))


def _no(nid: int, params: list[dict], rotulo: str, janela: list[dict] | None = None) -> dict:
    """Um nó; com `janela`, um 2º corrector (tipo 4) com a Power Window — a cor fica no 1º (tipo 1): posta no da janela,
    o Resolve a ignora calado (medido 2026-11-20)."""
    corretores = [_corretor(1, params)] + ([_corretor(4, janela)] if janela else [])
    campos = [(1, nid), (2, nid), (6, rotulo.encode("utf-8")), (4, 190 + 270 * (nid - 1)), (5, 180), (7, 1), (8, 44),
              (9, _msg(*corretores) + _msg((2, bytes.fromhex("0304050612")))),
              (10, bytes.fromhex("0a0a08818080800c12021002"))]
    return _campo(7, _msg(*campos))


def janela_circular(raio_px: float, borda_px: float, aspecto: float = 0.0, pan_px: float = 0.0, tilt_px: float = 0.0,
                    invertida: bool = True) -> list[dict]:
    """Os parâmetros da janela circular (timeline 1920×1080): `raio_px` = o raio a 50 % da borda; `borda_px` = a largura
    de 10 a 90 % (escala com o Size); `aspecto` > 0 estica na vertical (÷ (1 − a)), < 0 na horizontal; Pan/Tilt em px
    (Tilt positivo SOBE). Medido pelo render do quadro branco (`laboratorio-de-midia/lab/resolve_janela.py`)."""
    s = raio_px / JANELA_RAIO
    ps = [_p_f32(JANELA["aspecto"], aspecto), _p_f32(JANELA["soft"], borda_px / s), _p_f32(JANELA["tamanho"], s),
          _p_f32(JANELA["pan"], pan_px), _p_f32(JANELA["tilt"], tilt_px), _p_int(JANELA_TIPO, 2)]
    if invertida:
        ps.append(_p_int(JANELA_INVERTIDA, 2))
    return ps + [_p_f32(0x8850000D, JANELA_RAIO), _p_f32(0x8850000E, 0.0), _p_f32(0x8850000F, 0.0),
                 _campo(3, _msg((1, 0x88500010), (2, _msg((10, _msg((1, 1.0), (5, 1.0), (9, 1.0)))))))]


def body(sat: float | None, curva_bezier: list[tuple[float, float]] | None, vinheta: dict | None = None) -> bytes:
    """O grafo em SÉRIE (entrada → "MC Master" → "MC Curva" → saída), só com os nós que têm o que fazer. Com `vinheta`
    (a Vignette da página Color do Premiere 2027): um nó 1 "Cor" VAZIO na frente — a LUT do clipe entra nele depois
    (`drp.luts`, `SetLUT(1)`) — e o nó "Vinheta" no fim (a janela circular invertida + o Gain), a ordem do Premiere."""
    nos = []
    if vinheta:
        nos.append(_no(1, [], "Cor"))
    if sat is not None:
        nos.append(_no(len(nos) + 1, [_p_f32(SAT, sat / 100.0)], "MC Master"))
    if curva_bezier:
        nos.append(_no(len(nos) + 1, _curvas_rgb(curva_bezier), "MC Curva"))
    if vinheta:
        nos.append(_no(len(nos) + 1, [_p_f32(GAIN, float(vinheta["gain"]))], "Vinheta",
                       janela_circular(vinheta["raio_px"], vinheta["borda_px"], vinheta.get("aspecto", 0.0),
                                       vinheta.get("pan_px", 0.0), vinheta.get("tilt_px", 0.0))))
    n = len(nos)
    if not n:
        raise ValueError("nada a aplicar")
    from tools.inspect_drp import pb_encode     # aqui: quem só LÊ o CC (a Carta) não precisa do lado do Resolve
    res = _msg((1, 1920), (2, 1080), (3, 1.0), (4, 1920), (5, 1080), (6, 1.0), (7, 1920), (8, 1080), (9, 4294967295))
    g = _msg((1, n), (2, 1), (3, res)) + nos
    for k in range(1, n):
        g.append(_campo(8, _msg((1, k), (3, k + 1), (5, 64), (6, 64), (7, k))))
    g.append(_campo(9, _msg((1, 1), (2, 80), (3, _msg((1, 1), (2, 64), (3, 1), (4, 1))))))
    g.append(_campo(10, _msg((1, 2), (2, 64), (3, _msg((1, n + 1), (2, 64), (3, 2), (4, n))))))
    return bytes(pb_encode([_campo(1, g)]))


# ── a curva do MC na curva Custom do Resolve ──────────────────────────────────────────────────────────────────────────
def _tangentes(xs, ys) -> list[float]:
    """Catmull-Rom (secante dos vizinhos); nas pontas, a secante do segmento — a curva do MC."""
    if len(xs) == 2:
        s = (ys[1] - ys[0]) / (xs[1] - xs[0])
        return [s, s]
    return ([(ys[1] - ys[0]) / (xs[1] - xs[0])]
            + [(ys[i + 1] - ys[i - 1]) / (xs[i + 1] - xs[i - 1]) for i in range(1, len(xs) - 1)]
            + [(ys[-1] - ys[-2]) / (xs[-1] - xs[-2])])


def _mc(xs, ys, ms, t: float, j: int | None):
    if j is None:                                  # fora das pontas: plana
        return (ys[0] if t <= xs[0] else ys[-1]), 0.0
    h = xs[j + 1] - xs[j]
    s = (t - xs[j]) / h
    v = ((2 * s**3 - 3 * s**2 + 1) * ys[j] + (s**3 - 2 * s**2 + s) * h * ms[j]
         + (-2 * s**3 + 3 * s**2) * ys[j + 1] + (s**3 - s**2) * h * ms[j + 1])
    d = ((6 * s * s - 6 * s) * ys[j] + (3 * s * s - 4 * s + 1) * h * ms[j]
         + (-6 * s * s + 6 * s) * ys[j + 1] + (3 * s * s - 2 * s) * h * ms[j + 1]) / h
    return v, d


def curva_do_mc(pontos: list[tuple[float, float]], c0: float = EIXO_C0, w: float = EIXO_W) -> list[tuple[float, float]]:
    """A curva Master do MC (t = código/255, Catmull-Rom, plana fora das pontas) como lista Bézier da curva Custom do
    Resolve no eixo dele (v = C0 + W·u, v = (código − 16)/219). Troca AFIM nos dois eixos: cada intervalo entre os nós,
    cortado em u = 0 e 1, é UMA cúbica e vira um trecho Bézier EXATO pelas derivadas de cada lado."""
    P = sorted((float(x), float(y)) for x, y in pontos)
    xs, ys = [x for x, _ in P], [y for _, y in P]
    ms = _tangentes(xs, ys)
    a, b = 219 * w / 255, (16 + 219 * c0) / 255          # t = a·u + b
    k = 255 / 219 / w                                     # dy_u/dy_t

    def yu(y):
        return ((255 * y - 16) / 219 - c0) / w

    quebras = sorted({0.0, 1.0} | {(x - b) / a for x in xs if 0 < (x - b) / a < 1})
    lista: list[tuple[float, float]] = []
    for p, q in zip(quebras, quebras[1:]):
        tm = a * (p + q) / 2 + b
        j = next((i for i in range(len(xs) - 1) if xs[i] <= tm <= xs[i + 1]), None)
        v0, d0 = _mc(xs, ys, ms, a * p + b, j)
        v1, d1 = _mc(xs, ys, ms, a * q + b, j)
        y0, y1, m0, m1 = yu(v0), yu(v1), d0 * a * k, d1 * a * k
        h = q - p
        if not lista:
            lista.append((p, y0))
        lista += [(p + h / 3, y0 + m0 * h / 3), (q - h / 3, y1 - m1 * h / 3), (q, y1)]
    return lista


# ── aplicar depois do import ──────────────────────────────────────────────────────────────────────────────────────────
def _pedido_valido(x: dict) -> bool:
    sat, cv, vh = x.get("sat"), x.get("curva"), x.get("vinheta")
    return (isinstance(x.get("trilha"), int) and 1 <= x["trilha"] <= 999 and isinstance(x.get("quadro"), int)
            and isinstance(x.get("arquivo"), str)
            and (sat is None or (isinstance(sat, (int, float)) and 0 <= sat <= 400))
            and (cv is None or (isinstance(cv, list) and 2 <= len(cv) <= 16
                                and all(isinstance(p, list) and len(p) == 2
                                        and all(isinstance(c, (int, float)) and -0.1 <= c <= 1.1 for c in p) for p in cv)))
            and (vh is None or _vinheta_valida(vh))
            and (sat is not None or cv is not None or vh is not None))


def _vinheta_valida(v) -> bool:
    num = lambda k, a, b: isinstance(v.get(k, 0.0), (int, float)) and a <= v.get(k, 0.0) <= b
    return (isinstance(v, dict) and isinstance(v.get("raio_px"), (int, float)) and 1 <= v["raio_px"] <= 20000
            and isinstance(v.get("borda_px"), (int, float)) and 0 <= v["borda_px"] <= 20000
            and isinstance(v.get("gain"), (int, float)) and 0 <= v["gain"] <= 1
            and num("aspecto", -0.99, 0.99) and num("pan_px", -20000, 20000) and num("tilt_px", -20000, 20000))


def aplicar_cor_mc(timeline, pedidos: list[dict], pasta: str) -> list[dict]:
    """Cada `{trilha, quadro, arquivo, sat?, curva?}` (o writer, `relatorio["cor_mc"]`) nos 2 nós do clipe achado pela
    trilha, pelo quadro (desde o início da timeline) e pelo nome. Um clipe que falha é registrado e os outros seguem."""
    from drp.estabilizador import _aplicar_drx, drx      # o zstd: só o lado do Resolve
    inicio = timeline.GetStartFrame()
    fora = []
    for x in pedidos or []:
        base = {k: x.get(k) for k in ("trilha", "quadro", "arquivo")}
        if not _pedido_valido(x):
            fora.append({**base, "ok": False, "erro": "pedido inválido"})
            continue
        item = next((it for it in timeline.GetItemListInTrack("video", x["trilha"]) or []
                     if it.GetStart() - inicio == x["quadro"] and it.GetName() == x["arquivo"]), None)
        if item is None:
            fora.append({**base, "ok": False, "erro": "clipe não encontrado na timeline"})
            continue
        try:
            corpo = body(x.get("sat"), curva_do_mc([tuple(p) for p in x["curva"]]) if x.get("curva") else None,
                         x.get("vinheta"))
        except (ValueError, ZeroDivisionError, AssertionError) as e:
            fora.append({**base, "ok": False, "erro": f"a cor não se monta ({e})"})
            continue
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, f"cor_mc_{x['trilha']}_{x['quadro']}.drx")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(drx(corpo))
        ok = _aplicar_drx(timeline, item, caminho)
        fora.append({**base, "ok": ok, **({} if ok else {"erro": "o Resolve não aceitou a grade"})})
    return fora
