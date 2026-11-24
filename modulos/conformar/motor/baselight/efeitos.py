"""Os efeitos de IMAGEM do Premiere no Baselight: a VELOCIDADE (Retime Time×Time, um keyframe por quadro) e o MOTION
(camada Transform: escala, posição, rotação, flip — parado ou animado). Veio do estudo PRODUCAO-C de 2026-11-21/22
(`estudo/ferramentas/traduzir_PRODC.py`, `blg_retime.py`, `blg_pilha.py`, `blg_transform.py`: 132 de 133 pontos contra a
referência); banco `plugins/baselight/README.md` § Retime Time×Time e § "Retime com fonte de OUTRA taxa".

Só stdlib: roda no python da FilmLight (`efeitos_flapi.py`) e nos testes.

O desenho (as regras medidas no estudo):
  - ⛔ o Baselight toca a fonte de OUTRA taxa em tempo real e o Retime só pousa nessa grade (100 qps: degraus de ~17).
    ⇒ o arquivo de taxa ≠ a da timeline que recebe camada do Ciclo (velocidade, Motion, máscara, fundo de máscara) é
    declarado NA TAXA DA TIMELINE ("nativo": um quadro de fonte por quadro; o `<in>` = o quadro do arquivo) e TODOS os
    planos dele levam a curva — os de 100 % com a do tempo real; o arquivo sem camada nenhuma fica como estava;
  - a curva: quadro de fonte = in + piso(valor × fps), valor = (q + 0,5)/fps (o meio do quadro: o piso nunca cai no
    vizinho); q negativo vai para antes do in (reverso);
  - o BLG parte do MOLDE do Retime (nunca do lido: `get_blg_payload` devolve a pilha de quem está POR CIMA no 1º quadro
    do plano) e o Transform entra numa faixa embaixo da imagem (aplicado DEPOIS dela);
  - o Motion do leitor: escala relativa ao encaixe, posição em milésimos do quadro (+Y para cima); o proxy em letterbox
    (escala X/Y = 0,9375) corrige o Y; flip = escala negativa. No BLG a posição é fração da LARGURA nos dois eixos.

Só o lado do Premiere (a leitura do `.prproj` guarda o quadro EXATO da fonte em `_premiere`, `do_prproj.como_aaf`); o
MC (Timewarp, Resize/Reformat) fica para depois.
"""
from __future__ import annotations

import math
import os
import re
import struct
import xml.etree.ElementTree as ET

AQUI = os.path.dirname(os.path.abspath(__file__))
MOLDE_RETIME = os.path.join(AQUI, "moldes", "retime_tempo.txt")
MOLDE_TRANSFORM = os.path.join(AQUI, "moldes", "transform.txt")


# ── o que cada plano pede ───────────────────────────────────────────────────────────────────────────────────────────
def _motion_params(seg: dict) -> dict:
    return next((e.get("params") or {} for e in seg.get("effects") or [] if e.get("name") == "Motion"), None) or {}


def motion(seg: dict) -> tuple[float, float, float, float, float] | None:
    """(escala X, escala Y, rotação em graus, X e Y do centro em FRAÇÃO do quadro, Y para baixo) do Motion parado, ou
    None quando é o neutro."""
    mo = _motion_params(seg)
    sx, sy = float(mo.get("scale_x", 1.0)), float(mo.get("scale_y", 1.0))
    px, py, rot = float(mo.get("pos_x", 0.0)), float(mo.get("pos_y", 0.0)), float(mo.get("rot_z", 0.0))
    if (abs(sx - 1) < 1e-6 and abs(sy - 1) < 1e-6 and abs(px) < 1e-6 and abs(py) < 1e-6 and abs(rot) < 1e-6
            and not mo.get("flip_x") and not mo.get("flip_y") and not mo.get("kf")):
        return None
    fy = sy / sx if sx and abs(sx / sy - 0.9375) < 0.002 else 1.0      # o proxy 1024×540 em letterbox (1080 ÷ 1012,5)
    fx = -1.0 if mo.get("flip_x") else 1.0                              # flip = escala negativa (PRODC 33 s: espelhado)
    fyy = -1.0 if mo.get("flip_y") else 1.0
    return fx * sx, fyy * sy, rot, 0.5 + px / 1000.0, 0.5 - py / 1000.0 / fy


def series_motion(seg: dict, n: int, mo: tuple, k0: int = 0) -> dict | None:
    """O Motion ANIMADO (`kf` do leitor: chaves (t, valor), t em quadros do plano; linear entre elas, parado fora) → um
    valor por quadro do plano: {sx, sy, rot, x, y} (x, y em fração do quadro). Sem `kf`: None."""
    kf = _motion_params(seg).get("kf") or {}
    if not any(kf.values()):
        return None
    t0 = min(v[0][0] for v in kf.values() if v)

    def serie(nome: str, padrao: float) -> list[float]:
        ch = kf.get(nome) or []
        if not ch:
            return [padrao] * n
        xs = [(t - t0, v) for t, v in ch]
        out = []
        for k in range(k0, k0 + n):
            if k <= xs[0][0]:
                out.append(xs[0][1])
            elif k >= xs[-1][0]:
                out.append(xs[-1][1])
            else:
                j = next(i for i in range(1, len(xs)) if xs[i][0] >= k)
                (ta, va), (tb, vb) = xs[j - 1], xs[j]
                out.append(va + (vb - va) * (k - ta) / (tb - ta))
        return out

    sx0, sy0, rot0, x0, y0 = mo
    sgx, sgy = (-1 if sx0 < 0 else 1), (-1 if sy0 < 0 else 1)
    sx0, sy0 = abs(sx0), abs(sy0)
    fy = sy0 / sx0 if sx0 and abs(sx0 / sy0 - 0.9375) < 0.002 else 1.0
    px = serie("pos_x", x0 - 0.5)
    py = serie("pos_y", (0.5 - y0) * fy)
    return {"sx": [sgx * v for v in serie("zoom", sx0)], "sy": [sgy * v for v in serie("zoom_y", sy0)],
            "rot": serie("rot", rot0), "x": [0.5 + v for v in px], "y": [0.5 - v / fy for v in py]}


def tem_mascara(seg: dict) -> bool:
    return any((e.get("name") or "").startswith("Máscara") and (e.get("params") or {}).get("mascaras")
               for e in seg.get("effects") or [])


def precisa_de_velocidade(seg: dict) -> bool:
    f = seg.get("_premiere") or {}
    return (abs(float(seg.get("relative_speed") or f.get("relativa") or 1.0) - 1.0) > 1e-6
            or bool(seg.get("source_offset_map")) or bool(seg.get("speed_curve")) or bool(seg.get("speed_keyframes")))


def posicao_exata(seg: dict, k: float, fps_original: float, desloc_s: float = 0.0) -> tuple[float, float]:
    """(o quadro do ORIGINAL, sem piso, e o PASSO em quadros do original por quadro) no quadro k do plano — o fundo de
    uma máscara (`GR_SequenceRop`: deslocamento e passo; estudo, 20ª rodada: in 10 passo 2,5 → 10, 12, 15… exato).
    k < 0 (o fundo entra no meio do plano de cima) segue o passo do 1º quadro."""
    f = seg["_premiere"]
    ent, fd, vel = float(f["ent"]), float(f["fps"]), float(f["vel"] or 1.0)
    mapa = seg.get("source_offset_map") or []
    kk = min(max(int(math.floor(k)), 0), len(mapa) - 1) if mapa else k
    passo = (float(mapa[min(kk + 1, len(mapa) - 1)][1]) - float(mapa[kk][1])) if mapa else 1.0 / vel
    q = ent + (float(mapa[kk][1]) + (k - kk) * passo if mapa else k / vel)
    r = fps_original / fd
    return max(q, 0.0) * r + desloc_s * fps_original, passo * r


def quadros_da_fonte(seg: dict, n: int, fps_original: float, desloc_s: float = 0.0) -> list[int]:
    """O quadro do ORIGINAL (desde o início do arquivo) em cada quadro do plano, como a montagem mostra: o quadro do
    arquivo da montagem = piso(início + deslocamento) — `source_offset_map` (rampas) ou k ÷ velocidade —; no original
    de outra taxa, o quadro que cobre o meio daquele; `desloc_s`: o arquivo da montagem é um TRECHO do original."""
    f = seg["_premiere"]
    ent, fd, vel = float(f["ent"]), float(f["fps"]), float(f["vel"] or 1.0)
    mapa = seg.get("source_offset_map") or []
    out = []
    for k in range(n):
        d = float(mapa[min(k, len(mapa) - 1)][1]) if mapa else k / vel
        j = math.floor(ent + d + 1e-9)
        q = j if abs(fps_original - fd) < 0.01 else math.floor((j + 0.5) * fps_original / fd)
        out.append(q + (int(math.floor(desloc_s * fps_original + 0.5)) if desloc_s else 0))
    return out


def _video(seg: dict) -> bool:
    return not (seg.get("is_audio") or seg.get("is_gap") or seg.get("is_transition") or seg.get("is_effect"))


def escondidos(leitura: dict, achar_daily) -> set[int]:
    """Os índices dos planos de vídeo cobertos INTEIROS por trilhas de cima. ⛔ O `bl-conform` os deixa FORA (BL09): não
    se procuram (eram "não achado") nem contam como "não traduzido" (não se vê o efeito deles)."""
    from .entrega import _coberto, _rate, _tc_quadros

    base_tl, _ = _rate(float(leitura["timeline_fps"]))
    df_tl = bool(leitura.get("timeline_drop_frame"))
    pos = {}
    cobre: dict[int, list[tuple[int, int]]] = {}
    for n, seg in enumerate(leitura["segments"]):
        if _video(seg) and achar_daily(seg):
            i = _tc_quadros(seg["timeline_tc_in"], base_tl, df_tl)
            tr = int(seg.get("track") or 1)
            pos[n] = (i, i + int(seg["duration_frames"]), tr)
            cobre.setdefault(tr, []).append(pos[n][:2])
    return {n for n, (i, f, tr) in pos.items()
            if _coberto(i, f, sorted(v for t, lst in cobre.items() if t > tr for v in lst))}


def planejar(leitura: dict, decisao: dict, achar_daily) -> list[dict]:
    """Os planos que levam efeito, na ordem do `do_aaf.escrever` (o clipitem `clipitem-<n>`): {n, inicio, quadros, clip,
    original, nativo, q (quadros do original, um por quadro do plano) ou None, motion, series}. Só os que o xmeml leva
    ONLINE (o daily achado e um original decidido)."""
    from .entrega import _nfc, _rate, _tc_quadros

    fps_tl = float(leitura["timeline_fps"])
    base_tl, _ = _rate(fps_tl)
    df_tl = bool(leitura.get("timeline_drop_frame"))
    por_nfc = {_nfc(k): v for k, v in decisao.items()}
    fora = escondidos(leitura, achar_daily)
    cand = []
    for n, seg in enumerate(leitura["segments"]):
        if n in fora:
            continue
        if (seg.get("is_audio") or seg.get("is_gap") or seg.get("is_transition") or seg.get("is_effect")
                or not seg.get("_premiere")):
            continue
        daily = achar_daily(seg)
        o = por_nfc.get(_nfc(daily or ""))
        if not o:
            continue
        cand.append((n, seg, o))
    # o arquivo "nativo": taxa ≠ a da timeline e algum plano dele com velocidade ou servindo de FUNDO a uma máscara (o
    # deslocamento e o passo do fundo são em quadros do arquivo declarado: `mascaras.troca_do_fundo`)
    fundos = set()
    pos = {n: _tc_quadros(s["timeline_tc_in"], base_tl, df_tl) for n, s, _o in cand}
    for n, s, _o in cand:
        if not tem_mascara(s):
            continue
        for q in range(pos[n], pos[n] + int(s["duration_frames"])):
            baixo = [(int(x.get("track") or 1), ox) for m, x, ox in cand if int(x.get("track") or 1) < int(s.get("track") or 1)
                     and pos[m] <= q < pos[m] + int(x["duration_frames"])]
            if baixo:
                fundos.add(_nfc(max(baixo, key=lambda v: v[0])[1]["caminho"]))
    # ⛔ e com QUALQUER camada nossa (o molde do Retime vai em toda pilha que o Ciclo grava): na taxa real o Retime
    # pousa na grade do Baselight — o C0296 de 100 qps a 100 % com máscara saiu 0,89 contra 0,94 do estudo (nativo)
    nativos = {_nfc(o["caminho"]) for _n, s, o in cand
               if abs(float(o["fps"]) - fps_tl) > 0.01
               and (precisa_de_velocidade(s) or _nfc(o["caminho"]) in fundos or motion(s) or tem_mascara(s))}
    out = []
    for n, seg, o in cand:
        dur = int(seg["duration_frames"])
        nativo = _nfc(o["caminho"]) in nativos
        q = None
        if nativo or (precisa_de_velocidade(seg) and abs(float(o["fps"]) - fps_tl) < 0.01):
            q = quadros_da_fonte(seg, dur, float(o["fps"]), float(o.get("desloc_s") or 0.0))
        mo = motion(seg)
        if q is None and mo is None:
            continue
        out.append({"n": n, "inicio": _tc_quadros(seg["timeline_tc_in"], base_tl, df_tl), "quadros": dur,
                    "clip": seg.get("clip_name"), "original": o["caminho"], "nativo": nativo, "q": q,
                    "motion": mo, "series": series_motion(seg, dur, mo) if mo else None})
    return out


def no_xmeml(xml: str, planos: list[dict]) -> dict:
    """O xmeml JÁ reescrito (`entrega.reescrever`) com os planos de velocidade no quadro exato: o `<file>` nativo declara a
    taxa da TIMELINE (sem `<timecode>` nem `<duration>`, como no estudo — o `<in>` conta quadros do arquivo); cada plano com
    curva entra com `<in>` = o 1º quadro mostrado e `<out>` = in + duração (out − in ≠ duração vira velocidade DO plano, e o
    Retime somaria). Devolve {nativos, planos}."""
    arv = ET.parse(xml)
    raiz = arv.getroot()
    seq = raiz.find(".//sequence")
    rate_tl = seq.find("rate")
    por_n = {f"clipitem-{p['n']}": p for p in planos if p["q"]}
    fid_nativo = set()
    for ci in raiz.iter("clipitem"):
        p = por_n.get(ci.get("id"))
        f = ci.find("file")
        if p and p["nativo"] and f is not None:
            fid_nativo.add(f.get("id"))
    for f in raiz.iter("file"):
        if f.get("id") not in fid_nativo or f.find("pathurl") is None:
            continue
        for r in (f.find("rate"), f.find("media/video/samplecharacteristics/rate")):
            if r is not None:
                r.find("timebase").text, r.find("ntsc").text = rate_tl.findtext("timebase"), rate_tl.findtext("ntsc")
        for tag in ("timecode", "duration"):
            if f.find(tag) is not None:
                f.remove(f.find(tag))
    for ci in raiz.iter("clipitem"):
        p = por_n.get(ci.get("id"))
        if not p:
            continue
        p["in_bl"] = p["q"][0]
        ci.find("in").text = str(p["in_bl"])
        ci.find("out").text = str(p["in_bl"] + int(ci.findtext("end")) - int(ci.findtext("start")))
    with open(xml, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        fh.write(ET.tostring(raiz, encoding="unicode"))
        fh.write("\n")
    return {"nativos": len(fid_nativo), "planos": len(por_n)}


# ── o BLG ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def ler(payload: str) -> str:
    import base64
    import zlib
    b = base64.b64decode(payload.strip())
    return zlib.decompress(b[8:]).decode("latin1")


def gravar(texto: str) -> str:
    import base64
    import zlib
    t = texto.encode("latin1")
    return base64.b64encode(struct.pack("<Q", len(t)) + zlib.compress(t)).decode()


def _n(v: float) -> str:
    s = "%.20g" % float(v)
    return s.rstrip("0").rstrip(".") if "." in s and "e" not in s else s


def curva_de_tempo(quadros: list[int], fps: float, meio: float = 0.5) -> str:
    """O `GM_Bezier1dInterp` do Retime Time×Time: `quadros[k]` = o quadro de fonte (relativo ao in) no quadro k."""
    ch = " ".join(f"{_n(k / fps)} {_n((q + meio) / fps)} 0 0 0 0" for k, q in enumerate(quadros))
    corpo = f"6 0 {len(quadros)} {ch} 0 17 -1 0.0010000000000000000208 0  "
    return f"17:GM_Bezier1dInterp 2:gm 1 0 0 t 0000000000000000 {len(corpo) - 1}:{corpo}"  # conta UM dos dois espaços


def _trocar_objeto(texto: str, oid: int, novo: str) -> str:
    linhas = texto.split("\n")
    for i, ln in enumerate(linhas):
        m = re.match(r'(\s*\(%d\)=")(.*)(",?)$' % oid, ln)
        if m:
            linhas[i] = m.group(1) + novo + m.group(3)
            return "\n".join(linhas)
    raise ValueError(f"objeto {oid} não achado")


def _curva_do_retime(texto: str) -> int:
    ln = next(ln for ln in texto.split("\n") if "GR_RetimeRop" in ln)
    m = re.search(r"gr_retime 2 (\d+) ((?:\d+ )+?)2 (f \S+|o \d+) (f \S+|o \d+)", ln)
    refs = [int(x) for x in m.group(2).split()]
    if not m.group(4).startswith("o "):
        raise ValueError("o molde do retime não tem a curva de tempo")
    return refs[int(m.group(4).split()[1])]


def _constante(v: float) -> str:
    corpo = f"6 0 0 0 0 -1 0.001 {_n(v)} "
    return f"f {struct.pack('>d', float(v)).hex()} {len(corpo)}:{corpo}"


def _chaves(valores: list[float], fps: float) -> str:
    ch = " ".join(f"{_n(k / fps)} {_n(v)} 0 0 0 0" for k, v in enumerate(valores))
    c = f"6 0 {len(valores)} {ch} 0 17 -1 0.0010000000000000000208 0 "
    return f"t 0000000000000000 {len(c)}:{c}"


def _transform(molde: str, series: dict, fps: float) -> str:
    """O molde do Transform com {sx, sy, rot (graus), x, y (fração da LARGURA)} — listas (1 valor = constante)."""
    linhas = molde.split("\n")
    rop = next(ln for ln in linhas if "GR_TransformRop" in ln)
    bez2 = int(rop.split("gr_transform 1 6 ")[1].split()[1])              # o 2º Transform2dInterp
    lb = next(ln for ln in linhas if ln.strip().startswith(f"({bez2})="))
    ids = [int(x) for x in lb.split("3:bez 2 7 ")[1].split()[:7]]
    chaves = ["sx", "sy", "rot", "x", "y", None, None]
    novo = []
    for ln in linhas:
        m = re.match(r"\s*\((\d+)\)=", ln)
        if m and int(m.group(1)) in ids:
            ch = chaves[ids.index(int(m.group(1)))]
            vs = series.get(ch, [0.0]) if ch else [0.0]
            if ch == "rot":
                vs = [math.radians(v) for v in vs]
            ent = _constante(vs[0]) if len({round(v, 9) for v in vs}) == 1 else _chaves(vs, fps)
            ln = re.sub(r"f [0-9a-f]{16} \d+:6 0 0 0 0 -1 0\.001 \S+ ", lambda _m: ent, ln)
        novo.append(ln)
    return "\n".join(novo)


def _com_transform(texto: str, molde_t: str, linha: int = 0, trecho: tuple | None = None) -> str:
    """A faixa de Transform do molde (já preenchido) na pilha de `texto`, na `linha` (0 = embaixo = DEPOIS da imagem;
    numa composição, logo abaixo do FUNDO = só o fundo se transforma); as faixas dessa linha para cima sobem uma.
    `trecho` = (início s, FIM s) relativos ao plano: a faixa só existe nele."""
    try:
        from .blg_estab import _desc, _renumerar, objetos
    except ImportError:                     # no python da FilmLight o módulo roda solto (`efeitos_flapi.py`)
        from blg_estab import _desc, _renumerar, objetos

    om = objetos(molde_t)
    rop = next(i for i, (tp, _, _) in om.items() if tp == "GR_TransformRop")
    faixa = next(i for i, (tp, fl, _) in om.items() if tp == "GM_Strip" and rop in fl)
    leva: list[int] = []
    _desc(om, faixa, leva)
    prox = max(int(x) for x in re.findall(r'^\s*\((\d+)\)=', texto, re.M)) + 1
    mapa = {o: prox + k for k, o in enumerate(leva)}
    novos = [_renumerar(om[o][2], mapa) for o in leva]
    for m in list(re.finditer(r'\((\d+)\)="8:GM_Strip 2:gm (\d+) 1 (\d+) 1 o 0 (\S+) (\S+) (\d+) f f 0 "', texto)):
        if int(m.group(6)) >= linha:
            texto = texto.replace(m.group(0), m.group(0).replace(f"{m.group(5)} {m.group(6)} f f 0",
                                                                 f"{m.group(5)} {int(m.group(6)) + 1} f f 0"))
    dur = re.search(r'8:GM_Strip 2:gm \d+ 1 \d+ 1 o 0 \S+ (\S+) ', texto).group(1)
    novos = [re.sub(r'(8:GM_Strip 2:gm \d+ 1 \d+ 1 o 0 \S+ )\S+ \d+ f f 0', rf'\g<1>{dur} {linha} f f 0', ln)
             for ln in novos]
    if trecho:
        h = lambda v: struct.pack(">d", float(v)).hex()  # noqa: E731
        novos = [re.sub(r'(8:GM_Strip 2:gm \d+ 1 \d+ 1 o 0 )\S+ \S+ ', rf'\g<1>{h(trecho[0])} {h(trecho[1])} ', ln)
                 for ln in novos]
    tl = re.search(r'\((\d+)\)="11:GM_Timeline 2:gm (\d+) (\d+) ([\d ]+?) (0 0 \d+[\d ]*) ",', texto)
    filhos = [int(x) for x in tl.group(4).split()]
    faixas = [f for f in filhos if re.search(rf'\({f}\)="8:GM_Strip', texto)]
    i = max(filhos.index(f) for f in faixas)
    filhos2 = filhos[:i + 1] + [mapa[faixa]] + filhos[i + 1:]
    nf = len(faixas) + 1
    resto = filhos2[nf:]
    est = f"0 0 {nf} {nf} 0 {nf} {nf + 1} {len(resto) - 2} " + " ".join(str(nf + 2 + k) for k in range(len(resto) - 2))
    texto = texto.replace(tl.group(0), f'({tl.group(1)})="11:GM_Timeline 2:gm {tl.group(2)} {len(filhos2)} '
                                       f'{" ".join(map(str, filhos2))} {est} ",')
    fim = texto.find(" ],", texto.find("blg_ObjectStrings"))
    return texto[:fim] + "\n".join(ln if ln.rstrip().endswith(",") else ln + "," for ln in novos) + "\n" + texto[fim:]


def transform_preenchido(molde_t: str, mo: tuple, series: dict | None, fps: float, w: int, h: int) -> str:
    """O molde do Transform com o Motion (`motion` + `series_motion`): fração do QUADRO → fração da LARGURA."""
    s = series or {"sx": [mo[0]], "sy": [mo[1]], "rot": [mo[2]], "x": [mo[3]], "y": [mo[4]]}
    return _transform(molde_t, {"sx": s["sx"], "sy": s["sy"], "rot": s["rot"], "x": list(s["x"]),
                                "y": [v * h / w for v in s["y"]]}, fps)


def trecho(plano: dict, k0: int, n: int) -> dict:
    """O pedaço [k0, k0 + n) do plano (o conform corta o plano de cima onde há corte embaixo: o estudo, LOU_7310 74–80 →
    74–79 + 79–80): os quadros RELATIVOS ao in do clipitem (como o estudo, 132/133) e as séries do Motion."""
    q = plano.get("q")
    s = plano.get("series")
    return {"rel": [x - plano["in_bl"] for x in q[k0:k0 + n]] if q else None,
            "series": {k: v[k0:k0 + n] for k, v in s.items()} if s else None}


def blg(plano: dict, k0: int, n: int, fps: float, w: int, h: int, molde_r: str, molde_t: str) -> str:
    """O texto do BLG do pedaço do plano: o molde do Retime com a curva (a identidade quando não há velocidade) + o
    Transform (fração da LARGURA nos dois eixos) quando há Motion."""
    t = trecho(plano, k0, n)
    texto = _trocar_objeto(molde_r, _curva_do_retime(molde_r), curva_de_tempo(t["rel"] or list(range(n)), fps))
    mo = plano.get("motion")
    if mo:
        texto = _com_transform(texto, transform_preenchido(molde_t, mo, t["series"], fps, w, h))
    return texto


def achar_plano(planos: list[dict], inicio: int, fim: int, clip: str) -> tuple[dict | None, int]:
    """O plano que CONTÉM o plano do Baselight [inicio, fim) com o mesmo nome de clipe; sem o nome, o único que contém."""
    dentro = [p for p in planos if p["inicio"] <= inicio and fim <= p["inicio"] + p["quadros"]]
    pelo_nome = [p for p in dentro if (p.get("clip") or "") == (clip or "")]
    p = pelo_nome[0] if len(pelo_nome) == 1 else (dentro[0] if len(dentro) == 1 and not pelo_nome else None)
    return p, (inicio - p["inicio"]) if p else 0


# ── os títulos ──────────────────────────────────────────────────────────────────────────────────────────────────────
def titulos(leitura: dict) -> list[dict]:
    """Os títulos da montagem (Graphic/Text do Premiere, sem mídia): {inicio, fim, texto, fonte, corpo}. ⭐ Decisão do
    autor (2026-11-23): em geral o texto NÃO vai à cor — cada título vira um marker com o que ele é; trazer o texto para
    a scene (camada Text em modo Composite, estudo `titulos_PRODC.py`) fica como OPÇÃO, para o título narrativo/artístico."""
    from .entrega import _rate, _tc_quadros

    base_tl, _ = _rate(float(leitura["timeline_fps"]))
    df_tl = bool(leitura.get("timeline_drop_frame"))
    out = []
    for seg in leitura["segments"]:
        if seg.get("is_audio") or seg.get("disabled"):
            continue
        t = next(((e.get("params") or {}).get("titulo") for e in seg.get("effects") or []
                  if (e.get("params") or {}).get("titulo")), None)
        if not t:
            continue
        cx = (t.get("caixas") or [{}])
        i = _tc_quadros(seg["timeline_tc_in"], base_tl, df_tl)
        f = cx[0].get("fonte") or {}
        out.append({"inicio": i, "fim": i + int(seg["duration_frames"]), "trilha": int(seg.get("track") or 1),
                    "texto": " / ".join(c.get("texto") or "" for c in cx).strip(),
                    "fonte": " ".join(x for x in (f.get("familia"), f.get("estilo")) if x),
                    "corpo": cx[0].get("corpo_resolve")})
    return out


def marcas_dos_titulos(tits: list[dict], fps: float) -> list[tuple[int, str]]:
    """Um marker por título: o texto, a fonte e o corpo, e até onde ele vai (o colorista recebe a timeline sem texto)."""
    base = round(fps)
    tc = lambda q: f"{q // base // 60:02d}:{q // base % 60:02d}:{q % base:02d}"  # noqa: E731
    return [(t["inicio"], f"título da montagem (o texto não veio para a cor): «{t['texto']}»"
                          + (f" · {t['fonte']}" if t["fonte"] else "") + (f", corpo {t['corpo']:g}" if t["corpo"] else "")
                          + f" · V{t['trilha']}, até {tc(t['fim'])}") for t in tits]


def _tc_ini(seg: dict, leitura: dict) -> int:
    from .entrega import _rate, _tc_quadros
    return _tc_quadros(seg["timeline_tc_in"], _rate(float(leitura["timeline_fps"]))[0], bool(leitura.get("timeline_drop_frame")))
