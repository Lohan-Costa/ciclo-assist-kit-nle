"""As MÁSCARAS de opacidade do Premiere no Baselight: a composição na pilha do plano de cima (Background Replacement +
Shape). Veio do estudo PRODUCAO-C (`estudo/ferramentas/mascaras_prodc.py`, `blg_composicao.py`,
`aplicar_composicao.py`, rodadas 20–24: os trechos mascarados com mínimo ≥ 0,87 quadro a quadro); banco
`plugins/baselight/README.md` § "A MÁSCARA de opacidade = composição na PILHA" e seguintes.

Só stdlib (o `.blscene` exportado é um SQLite). Por plano mascarado:
  - frente = a pilha do próprio plano (o Retime/Motion dele, `efeitos.blg`), a composição por cima;
  - fundo  = o `GR_SequenceRop` do plano de BAIXO (da scene exportada pelo `bl-export`), com o deslocamento (s) e o
    passo (quadros por quadro) do quadro certo; o arquivo dele vai NATIVO (`efeitos.planejar`); o Motion do fundo numa
    camada Transform logo ABAIXO do fundo (só o fundo se transforma);
  - shape  = o contorno do leitor (fração da FONTE, quadro a quadro) levado ao QUADRO pelo Motion do plano, recuado b·F
    para dentro (a suavidade do Baselight sai para fora; modo vídeo × frente DENTRO), invertida, um keyframe por quadro
    em todos os pontos (⛔ só os pontos que não são o 1º animados deixam a curva parada);
  - máscara sobre máscara: a composição do fundo DENTRO do ramo do fundo (até 3 níveis); fundo que troca no meio: uma
    composição por TRECHO, com a shape virando uma caixa gigante fora dele (⛔ o BLG não guarda tempo por faixa); nada
    embaixo = fundo PRETO (o do Premiere).
⚠️ O modo da suavidade é o do espaço de trabalho de VÍDEO (o `bl-conform --space Video_Full` do Ciclo).
⛔ Multi-input não se relê pela FLAPI e muitas composições num processo PARAM o `end_delta`: um processo curto por plano
(`mascaras_flapi.py gravar1`).
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import struct

from . import efeitos as EF

MOLDE_COMPOSICAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moldes", "composicao.json")
#: a tradução da suavidade Premiere → Baselight no espaço de VÍDEO com a frente DENTRO (minimax, estudo `modos.json`)
MODO = {"a": 1.736, "b": 0.87}
INVERTER = ("Z 3 f f t", "Z 3 t f t")


# ── os objetos ──────────────────────────────────────────────────────────────────────────────────────────────────────
def objetos_finais(db: str) -> dict[int, tuple]:
    """{id: (tipo, sub, revisão, [filhos], estado)} no ÚLTIMO delta de cada objeto do `.blscene` (`bl-export`).
    ⛔ O SQLite devolve TEXTO (UTF-8) e o BLG é BYTES (latin1): os prefixos `s11:` contam BYTES — levado como texto,
    "(1024×540)" fica com o comprimento errado e o `end_delta` da FLAPI para para sempre (estudo, 23ª rodada)."""
    con = sqlite3.connect(db)
    q = """select o.Id, o.DeltaId, o.Revision, t.Data, o.Children, s.Data from Object o
           join State t on t.Id=o.TypeId join State s on s.Id=o.StateId order by o.DeltaId"""
    out = {}
    b = lambda x: x.encode("utf-8").decode("latin1")  # noqa: E731
    try:
        for oid, _d, rev, tipo, filhos, estado in con.execute(q):
            tp, _, sub = tipo.partition(" ")
            fl = [int(x) for x in filhos.strip("{}").split(",") if x != ""] if filhos else []
            out[oid] = (b(tp), b(sub), rev, fl, b(estado))
    finally:
        con.close()
    return out


def molde() -> dict:
    d = json.load(open(MOLDE_COMPOSICAO, encoding="utf-8"))
    return {"raizes": d["raizes"], "seq": d["seq"], "cd": d["cd"], "raio": d["raio"],
            "objetos": {int(k): (v[0], v[1], v[2], list(v[3]), v[4]) for k, v in d["objetos"].items()}}


def _descendentes(objs: dict, raiz: int, vistos: list[int]) -> list[int]:
    if raiz == 0 or raiz in vistos:
        return vistos
    vistos.append(raiz)
    for f in objs[raiz][3]:
        _descendentes(objs, f, vistos)
    return vistos


def _linha(oid: int, tp: str, sub: str, rev, filhos: list[int], estado: str) -> str:
    corpo = f"{len(tp)}:{tp} {len(sub)}:{sub} {rev} {len(filhos)} {' '.join(str(f) for f in filhos)} {estado}"
    corpo = corpo.replace("\\", "\\\\").replace('"', '\\"')
    return f'  ({oid})="' + corpo.replace("\n", '\\n"\n"') + '",'


def montar(simples: str, mo: dict, ajustes: dict | None = None, trocar: dict | None = None, base: int = 0) -> str:
    """A composição do molde (fundo, shape, camada) na pilha de `simples`. `ajustes` = {id do molde: f(estado)};
    `trocar` = {id: (tipo, sub, rev, filhos, estado)} no lugar dos do molde (o SequenceRop/ConformData do fundo).
    `base`: a linha da camada (fundo base+2, shape base+1); só as faixas da linha `base` para cima sobem 3 — com base > 0
    a composição entra DENTRO do ramo do fundo de outra (máscara sobre máscara)."""
    objs = dict(mo["objetos"])
    objs.update(trocar or {})
    ajustes = ajustes or {}
    texto = simples
    prox = max(int(x) for x in re.findall(r"^\s*\((\d+)\)=", texto, re.M)) + 1
    novos, mapa = [], {}
    for papel in ("fundo", "shape", "camada"):
        for o in _descendentes(objs, mo["raizes"][papel], []):
            if o not in mapa:
                mapa[o] = prox
                prox += 1
    for o, n in mapa.items():
        tp, sub, rev, fl, est = objs[o]
        if o in ajustes:
            est = ajustes[o](est)
        novos.append(_linha(n, tp, sub, rev, [mapa.get(f, 0) if f else 0 for f in fl], est))
    velhas = list(re.finditer(r'\((\d+)\)="8:GM_Strip 2:gm (\d+) 1 (\d+) 1 o 0 (\S+) (\S+) (\d+) f f 0 "', texto))
    dur = velhas[0].group(5)
    for m in velhas:
        lin = int(m.group(6))
        if lin >= base:
            texto = texto.replace(m.group(0), m.group(0).replace(f"{m.group(5)} {lin} f f 0", f"{m.group(5)} {lin + 3} f f 0"))
    ids_velhos = [int(m.group(1)) for m in velhas]
    faixas = []
    for papel, lin in (("fundo", base + 2), ("shape", base + 1), ("camada", base)):
        faixas.append(prox)
        novos.append(f'  ({prox})="8:GM_Strip 2:gm 1 1 {mapa[mo["raizes"][papel]]} 1 o 0 0000000000000000 {dur} {lin} f f 0 ",')
        prox += 1
    tl = re.search(r'\((\d+)\)="11:GM_Timeline 2:gm (\d+) (\d+) ([\d ]+?) (0 0 \d+[\d ]*) ",', texto)
    filhos = [int(x) for x in tl.group(4).split()]
    i = max(filhos.index(f) for f in ids_velhos)
    filhos2 = filhos[:i + 1] + faixas + filhos[i + 1:]
    nf = len(ids_velhos) + len(faixas)
    resto = filhos2[nf:]
    est = f"0 0 {nf} {nf} 0 {nf} {nf + 1} {len(resto) - 2} " + " ".join(str(nf + 2 + k) for k in range(len(resto) - 2))
    texto = texto.replace(tl.group(0), f'({tl.group(1)})="11:GM_Timeline 2:gm {tl.group(2)} {len(filhos2)} '
                                       f'{" ".join(map(str, filhos2))} {est} ",')
    fim = texto.find(" ],", texto.find("blg_ObjectStrings"))
    return texto[:fim] + "\n".join(novos) + "\n" + texto[fim:]


def _constante(v: float):
    txt = ("%.17g" % v).rstrip("0").rstrip(".") if "." in "%.17g" % v else "%.17g" % v
    corpo = f"6 0 0 0 0 -1 0.001 {txt} "
    return lambda e: re.sub(r"^0 f [0-9a-f]{16} \d+:6 0 0 0 0 -1 0\.001 \S+ ",
                            f"0 f {struct.pack('>d', v).hex()} {len(corpo)}:{corpo}", e, count=1)


# ── a shape ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def mascara_de(seg: dict) -> tuple[dict | None, list | None]:
    ef = next((e.get("params") or {} for e in seg.get("effects") or [] if (e.get("name") or "").startswith("Máscara")
               and (e.get("params") or {}).get("mascaras")), None)
    return (ef["mascaras"][0], ef.get("fonte_px")) if ef else (None, None)


def motion_no_quadro(seg: dict, k: int, w: int, h: int) -> tuple:
    """(sx, sy, rot, pos_x px, pos_y px (y para baixo), flip_x, fy) do Motion no quadro k do plano."""
    p = next((e.get("params") or {} for e in seg.get("effects") or [] if e.get("name") == "Motion"), {})
    kf = p.get("kf") or {}
    sx, sy = p.get("scale_x", 1.0), p.get("scale_y", 1.0)
    fy = sy / sx if sx and abs(sx / sy - 0.9375) < 0.002 else 1.0
    px, py, rot = p.get("pos_x", 0.0) / 1000, p.get("pos_y", 0.0) / 1000, p.get("rot_z", 0.0)
    if any(kf.values()):
        t0 = min(v[0][0] for v in kf.values() if v)

        def em(nome, padrao):
            ch = kf.get(nome) or []
            if not ch:
                return padrao
            xs = [(t - t0, v) for t, v in ch]
            if k <= xs[0][0]:
                return xs[0][1]
            if k >= xs[-1][0]:
                return xs[-1][1]
            j = next(i for i in range(1, len(xs)) if xs[i][0] >= k)
            (ta, va), (tb, vb) = xs[j - 1], xs[j]
            return va + (vb - va) * (k - ta) / (tb - ta)
        sx, sy, rot = em("zoom", sx), em("zoom_y", sy), em("rot", rot)
        px, py = em("pos_x", px), em("pos_y", py)
    return sx, sy, rot, px * w, -py * h / fy, bool(p.get("flip_x")), fy


def ao_quadro(x: float, y: float, fonte: list, mo: tuple, w: int, h: int) -> tuple[float, float]:
    """Fração da FONTE → px do QUADRO (y para baixo): encaixe + escala + rotação + posição."""
    fw, fh = fonte
    enc = min(w / fw, h / fh)
    sx, sy, rot, px, py, flip, _ = mo
    if flip:
        x = 1 - x
    dx, dy = (x - 0.5) * fw * enc * sx, (y - 0.5) * fh * enc * sy
    t = math.radians(rot)
    dx, dy = dx * math.cos(t) + dy * math.sin(t), -dx * math.sin(t) + dy * math.cos(t)
    return w / 2 + dx + px, h / 2 + dy + py


def recuar(pts: list, d: float) -> list:
    """Desloca os vértices `d` px para DENTRO (miter pelo bissetor; as alças acompanham o vértice)."""
    n = len(pts)
    area = sum(pts[i][0][0] * pts[(i + 1) % n][0][1] - pts[(i + 1) % n][0][0] * pts[i][0][1] for i in range(n)) / 2
    sinal = 1 if area > 0 else -1
    out = []
    for i in range(n):
        (ax, ay), (bx, by), (cx, cy) = pts[i - 1][0], pts[i][0], pts[(i + 1) % n][0]

        def normal(ux, uy, vx, vy):
            ex, ey = vx - ux, vy - uy
            ln = math.hypot(ex, ey) or 1
            return -ey / ln * sinal, ex / ln * sinal
        n1, n2 = normal(ax, ay, bx, by), normal(bx, by, cx, cy)
        mx, my = n1[0] + n2[0], n1[1] + n2[1]
        lm = math.hypot(mx, my) or 1
        mx, my = mx / lm, my / lm
        cosm = max(0.35, mx * n1[0] + my * n1[1])
        ox, oy = mx * d / cosm, my * d / cosm
        (vx, vy), (ix, iy), (sx_, sy_) = pts[i]
        out.append(((vx + ox, vy + oy), (ix + ox, iy + oy), (sx_ + ox, sy_ + oy)))
    return out


def pontos_bl(pts: list, w: int) -> list[float]:
    """[(vértice, alça de entrada, alça de saída)] em px → 6 valores por ponto (fração da LARGURA; ângulos em rad)."""
    out = []
    for (vx, vy), (ix, iy), (ox, oy) in pts:
        out += [vx / w, vy / w, math.atan2(iy - vy, ix - vx), math.hypot(ix - vx, iy - vy) / w,
                math.atan2(oy - vy, ox - vx), math.hypot(ox - vx, oy - vy) / w]
    return out


def trocar_curva_shape(texto: str, series: list[list[float]], fps: float) -> str:
    """A curva da shape recém-montada (a ÚLTIMA `BEZ_Bezier2dInterp`) com N pontos (6N séries, um valor por quadro)."""
    m = list(re.finditer(r'\((\d+)\)="18:BEZ_Bezier2dInterp 3:bez (\d+) (\d+) (\d+) ([\d ]+?) (\d+ \d+ o 0 z [o\d ]+) ",',
                         texto))[-1]
    cid, rev, ntrans = m.group(1), m.group(2), m.group(4)
    prox = max(int(x) for x in re.findall(r'^\s*\((\d+)\)=', texto, re.M)) + 1
    novos, ids = [], []
    for k, vs in enumerate(series):
        ent = EF._constante(vs[0]) if len({round(v, 9) for v in vs}) == 1 else EF._chaves(vs, fps)
        novos.append(f'  ({prox + k})="17:GM_Bezier1dInterp 2:gm 1 0 0 {ent} ",')
        ids.append(prox + k)
    n = len(series) // 6
    est = f"{n} {6 * n + 2} o 0 z " + " ".join(f"o {i}" for i in range(1, 6 * n + 1))
    texto = texto.replace(m.group(0), f'({cid})="18:BEZ_Bezier2dInterp 3:bez {rev} {1 + 6 * n} {ntrans} '
                                       f'{" ".join(map(str, ids))} {est} ",')
    fim = texto.find(" ],", texto.find("blg_ObjectStrings"))
    return texto[:fim] + "\n".join(novos) + "\n" + texto[fim:]


def caixa_gigante(npts: int, w: int, h: int) -> list:
    """`npts` pontos numa caixa muito maior que o quadro (alças nulas): com a shape invertida a frente cobre tudo — o
    "desligado" de um trecho (o BLG não guarda tempo por faixa)."""
    x0, y0, x1, y1 = -3 * w, -3 * h, 4 * w, 4 * h
    per = 2 * ((x1 - x0) + (y1 - y0))
    pts = []
    for i in range(npts):
        d = per * i / npts
        for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
            lado = abs(bx - ax) + abs(by - ay)
            if d <= lado:
                f = d / lado
                v = (ax + (bx - ax) * f, ay + (by - ay) * f)
                break
            d -= lado
        pts.append((v, v, v))
    return pts


def serie_da_shape(seg: dict, k0: int, n: int, ativo: tuple | None, w: int, h: int) -> tuple[list, float]:
    """A curva da máscara de `seg` no QUADRO (6 séries por ponto) e a suavidade F em px; fora de `ativo` (quadros do
    plano), a caixa gigante."""
    mk, fonte = mascara_de(seg)
    fonte = fonte or [w, h]
    qd = mk.get("quadros") or [{"vertices": mk["vertices"]}]
    series, F = None, 0.0
    for k in range(n):
        if ativo and not (ativo[0] <= k < ativo[1]):
            vals = pontos_bl(caixa_gigante(len(qd[0]["vertices"]), w, h), w)
        else:
            kk = min(max(k0 + k, 0), len(qd) - 1)
            mo = motion_no_quadro(seg, k0 + k, w, h)
            pts = [(ao_quadro(*v[1], fonte, mo, w, h), ao_quadro(*v[2], fonte, mo, w, h), ao_quadro(*v[3], fonte, mo, w, h))
                   for v in qd[kk]["vertices"]]
            esc = abs(mo[0]) * min(w / fonte[0], h / fonte[1])
            F, E = mk["suave_px"] * esc, mk.get("expansao_px", 0) * esc
            vals = pontos_bl(recuar(pts, MODO["b"] * F - E), w)
        series = [[v] for v in vals] if series is None else [sv + [v] for sv, v in zip(series, vals)]
    return series, F


# ── o fundo ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _em(vid: list[dict], seg: dict, q: int) -> dict | None:
    em = [x for x in vid if x["track"] < seg["track"] and x["ini"] <= q < x["ini"] + x["duration_frames"]]
    return max(em, key=lambda x: x["track"]) if em else None


def trechos_de(seg: dict, a: int, b: int, vid: list[dict]) -> list[tuple]:
    """[(início, fim, o clipe mais alto embaixo ou None)] — os trechos do plano em que o fundo é o mesmo."""
    out: list[list] = []
    for q in range(a, b):
        topo = _em(vid, seg, q)
        if out and out[-1][2] is topo:
            out[-1][1] = q + 1
        else:
            out.append([q, q + 1, topo])
    return [tuple(r) for r in out]


def fundo_de(seg: dict, a: int, b: int, vid: list[dict]) -> tuple[dict | None, int]:
    """O clipe MAIS ALTO embaixo de `seg` na maior parte de [a, b) e em quantos quadros."""
    conta: dict[int, list] = {}
    for q in range(a, b):
        topo = _em(vid, seg, q)
        if topo is not None:
            conta.setdefault(id(topo), [topo, 0])[1] += 1
    if not conta:
        return None, 0
    return tuple(max(conta.values(), key=lambda v: v[1]))


def troca_do_fundo(L: dict, kl: int, objs: dict, mo: dict, fps: float) -> tuple[dict | None, str]:
    """O SequenceRop + ConformData do clipe L (do `.blscene` exportado) com o deslocamento (s, o meio do quadro: o
    Baselight trunca) e o passo do quadro kl de L."""
    arq = os.path.basename(L["original"])
    arq_b = arq.encode("utf-8").decode("latin1")
    sq = next((i for i, v in objs.items() if v[0] == "GR_SequenceRop" and arq_b in v[4]), None)
    if sq is None:
        return None, arq
    cd = objs[sq][3][0]
    q0, passo = EF.posicao_exata(L, kl, L["fps_original"], L.get("desloc_s") or 0.0)
    est = re.sub(r" d f\S+ d f\S+ ", f" d f{((math.floor(q0 + 1e-9) + 0.5) / fps).hex()} d f{float(passo).hex()} ",
                 objs[sq][4], count=1)
    return {mo["seq"]: (objs[sq][0], objs[sq][1], objs[sq][2], [mo["cd"]], est), mo["cd"]: objs[cd]}, arq


#: o Transform de escala ~0 abaixo do fundo: o que sobra é PRETO (nada embaixo, como no Premiere)
PRETO = (0.0001, 0.0001, 0.0, 0.5, 0.5)


def _cadeia(texto, frente, kf, a, b, r0, r1, L, objs, vid, trecho, info, ctx, niveis=3):
    mo, w, h, fps, molde_t = ctx["molde"], ctx["w"], ctx["h"], ctx["fps"], ctx["molde_t"]
    base = 0
    for nivel in range(niveis):
        preto = L is None
        lr = L if not preto else next((x for x in vid if x["track"] < frente["track"]), None)
        if lr is None:
            info["avisos"].append("nada embaixo para o fundo preto")
            return texto
        trocar, arq = troca_do_fundo(lr, a - lr["ini"], objs, mo, fps)
        if trocar is None:
            info["avisos"].append(f"o fundo {arq} não está na scene exportada")
            return texto
        series, F = serie_da_shape(frente, kf, b - a, trecho, w, h)
        aj = {mo["raio"]: _constante(MODO["a"] * F / w), mo["raizes"]["shape"]: lambda e: e.replace(*INVERTER, 1)}
        texto = montar(texto, mo, aj, trocar, base=base)
        texto = trocar_curva_shape(texto, series, fps)
        mo_l = PRETO if preto else EF.motion(L)
        if mo_l is not None:                               # logo abaixo do fundo: só o fundo se transforma
            ser = None if preto else EF.series_motion(L, b - a, mo_l, a - L["ini"])
            texto = EF._com_transform(texto, EF.transform_preenchido(molde_t, mo_l, ser, fps, w, h), linha=base + 2)
        info["fundos"].append("PRETO" if preto else arq)
        if preto or mascara_de(L)[0] is None:
            return texto
        frente, kf, base = L, a - L["ini"], base + 2
        L, nq = fundo_de(frente, r0, r1, vid)
        if nq < r1 - r0:
            info["avisos"].append(f"nível {nivel + 2}: o fundo em {nq} de {r1 - r0} quadros")
    return texto


def composicao(seg: dict, a: int, b: int, vid: list[dict], objs: dict, frente: str, ctx: dict) -> tuple[str | None, dict]:
    """O texto do BLG do pedaço [a, b) do plano mascarado `seg` (a frente já com o Retime/Motion dele: `frente`), ou
    (None, {motivo})."""
    tr = trechos_de(seg, a, b, vid)
    if all(L is None for _, _, L in tr):
        return None, {"motivo": "nada embaixo"}
    info: dict = {"fundos": [], "avisos": []}
    texto = frente
    for r0, r1, L in tr:
        trecho = None if len(tr) == 1 else (r0 - a, r1 - a)
        texto = _cadeia(texto, seg, a - seg["ini"], a, b, r0, r1, L, objs, vid, trecho, info, ctx)
    return texto, {"fundo": " <- ".join(info["fundos"]), "aviso": "; ".join(info["avisos"]),
                   "trechos": [(r0, r1, L["clip_name"] if L else "PRETO") for r0, r1, L in tr]}


# ── o plano ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def planejar(leitura: dict, decisao: dict, achar_daily) -> dict:
    """{vid, mascarados}: `vid` = os planos de vídeo ONLINE (o fundo de alguém), cada um com o início, o original, a taxa
    dele e o deslocamento do trecho; `mascarados` = os com máscara. A mesma ordem/filtro do `efeitos.planejar`."""
    from .entrega import _nfc, _rate, _tc_quadros

    fps_tl = float(leitura["timeline_fps"])
    base_tl, _ = _rate(fps_tl)
    df_tl = bool(leitura.get("timeline_drop_frame"))
    por_nfc = {_nfc(k): v for k, v in decisao.items()}
    vid = []
    for n, seg in enumerate(leitura["segments"]):
        if not EF._video(seg) or not seg.get("_premiere") or seg.get("disabled"):
            continue
        o = por_nfc.get(_nfc(achar_daily(seg) or ""))
        if not o:
            continue
        vid.append({**seg, "n": n, "track": int(seg.get("track") or 1),
                    "ini": _tc_quadros(seg["timeline_tc_in"], base_tl, df_tl), "original": o["caminho"],
                    "fps_original": float(o["fps"]), "desloc_s": float(o.get("desloc_s") or 0.0)})
    return {"vid": vid, "mascarados": [x for x in vid if mascara_de(x)[0] is not None]}


def pedacos(plano: dict, shots: list[dict], planos_ef: list[dict]) -> list[dict]:
    """Os planos do Baselight ({n, shot_id, a, b, clip}) de cada mascarado, com o plano de efeitos dele (ou a identidade)."""
    ef_por_n = {p["n"]: p for p in planos_ef}
    out = []
    for m in plano["mascarados"]:
        for s in shots:
            if m["ini"] <= s["a"] and s["b"] <= m["ini"] + int(m["duration_frames"]) and (s.get("clip") or "") == (m.get("clip_name") or ""):
                out.append({"seg": m, "shot": s, "ef": ef_por_n.get(m["n"]) or {"q": None, "motion": None,
                                                                               "inicio": m["ini"]}})
    return out
