"""A TRILHA DE NOTAS: o que o Avid tinha e o Resolve não recebe como está, escrito na timeline.

Aprovado pelo autor em 2026-09-27 (organograma "Sinais do Import"). Uma trilha nova, acima de todas,
com um Text por segmento que tem algo a dizer; os clipes vão DESLIGADOS (não saem no render). Este
módulo só DECIDE o que cada nota diz e onde fica; quem escreve é o `drp/writer.py`.

Uma nota é `{"inicio", "dur", "linhas", "cor", "nome"}`:
- `inicio`/`dur` em quadros da TIMELINE (o início conta do começo da sequência);
- `linhas`: lista de linhas, cada uma uma lista de trechos `(texto, destaque)`; o destaque é o
  vermelho de "estamos aqui" (o Text do Resolve aceita cores diferentes na mesma linha);
- `cor`: o sinal sugerido (`distorcao`, `refazer`, `conferir` ou `None`), para a cor local do
  segmento e o marcador;
- `nome`: o texto corrido — vira o NOME do clipe, que é o que aparece na timeline;
- `segmento`: o índice do segmento na leitura (o writer pinta o clipe dele e põe o marcador);
- `grupo`: `efeito` (o "rampa" do Text por quadro acabou em 2026-10-23);
- `cabeca_info` e `ordem`: a cabeça estruturada e o lugar da nota (formato v2, abaixo).

Formato de keyframe (regra do autor): `[in]-[out] ([cadeia completa])`, com o in e o out deste
intervalo em vermelho dentro dos parênteses. A nota é cortada nos quadros dos keyframes.

⭐ Formato v2 (autor, 2026-10-23; desenho em `drp/notas_textplus.py`): a nota leva a CABEÇA estruturada
(`cabeca_info`: trilha, nome, tipo do clipe, TC source in/out) e a `ordem` (o início do segmento: os pedaços
de um segmento cortado guardam o lugar dele). Keyframe LINEAR corta a nota e mostra a cadeia; NÃO LINEAR mostra
o tipo da curva e só o 1º e o último valor, sem cortar. A RAMPA também: só a velocidade do 1º e do último
instante (acabou o Text por quadro). SÓ caracteres comuns: nada de seta nem sinal especial (o Text+ não tem
fonte reserva).
"""

from __future__ import annotations

#: Nome como o Media Composer mostra.
NOME_DO_EFEITO = {
    "EFF2_SBLEND": "3D Warp", "EFF2_BLEND_RESIZE": "Resize", "EFF2_BLEND_PIP": "Picture-in-Picture",
    "INT_EFF_SPATIAL_ADAPTER": "FrameFlex", "EFF2_STABILIZE": "Stabilize",
    "EFF2_RGB_COLOR_CORRECTION": "Color Correction", "EFF2_BLEND_MATTE_KEY": "Matte Key",
    "EFF2_LUTSFX": "LUT", "EFF2_BLEND_PAN_SCAN": "Pan & Scan",
}
#: Parâmetro do AAF → (nome na nota, unidade) — os números como o editor os vê no Avid.
PARAMETRO = {
    "DVE_POS_X_U": ("posição X", ""), "DVE_POS_Y_U": ("posição Y", ""),
    "DVE_SCALE_X_U": ("escala X", "%"), "DVE_SCALE_Y_U": ("escala Y", "%"),
    "DVE_ROT_Z_U": ("rotação", "°"), "DVE_FG_KEY_OPACITY_U": ("opacidade", "%"),
    "DVE_CROP_LEFT_U": ("crop esq.", ""), "DVE_CROP_RIGHT_U": ("crop dir.", ""),
    "DVE_CROP_TOP_U": ("crop topo", ""), "DVE_CROP_BOTTOM_U": ("crop base", ""),
    "AFX_POS_X_U": ("posição X", ""), "AFX_POS_Y_U": ("posição Y", ""),
    "AFX_SCALE_X_U": ("escala X", "%"), "AFX_SCALE_Y_U": ("escala Y", "%"),
    "AFX_SPATIAL_FRAMING_WID": ("tamanho X", "%"), "AFX_SPATIAL_FRAMING_HEI": ("tamanho Y", "%"),
    "AFX_SPATIAL_FRAMING_POSX": ("posição X", ""), "AFX_SPATIAL_FRAMING_POSY": ("posição Y", ""),
}
#: Efeitos que não são imagem (não geram nota).
_SEM_NOTA = ("EFF_SKIP_FOR_SIGNATURE", "Audio Pan Volume")
#: Keyframes mais próximos que isto se juntam num pedaço só: nota de 2 quadros ninguém lê.
MIN_QUADROS = 6
MAX_PARAMETROS = 3


def _nome(eid: str, label: str = "") -> str:
    """O nome como o editor o conhece: a tabela, o nome que o plugin declara na bin, ou o id. Só o ID do Avid
    (`EFF2_…`, maiúsculas e sublinhado) vira "Title Case"; um nome que já é de gente (o do Premiere, "Máscara de
    opacidade (Fusion)") fica como veio (2026-10-23: saía "Máscara De Opacidade")."""
    if NOME_DO_EFEITO.get(eid) or label:
        return NOME_DO_EFEITO.get(eid) or label
    if eid != eid.upper() or " " in eid:
        return eid
    return eid.replace("EFF2_", "").replace("EFF_", "").replace("_", " ").title()


def _num(v: float, unidade: str = "") -> str:
    t = f"{v:.1f}".rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-6 else str(int(round(v)))
    return t.replace(".", ",") + unidade


def _cadeia(pontos: list, i: int, unidade: str) -> list:
    """`[in]-[out] ([cadeia com in-out em vermelho])` para o par de keyframes i, i+1. Com só dois
    keyframes a cadeia É o intervalo: fica `[in]-[out]`, sem parênteses (regra do autor)."""
    vals = [_num(v, unidade) for _q, v in pontos]
    # O hífen do autor (`56%-75%`); com valor NEGATIVO ele fica ambíguo (`0--15--30`), e aí a
    # separação vira `>` (`0 > -15`) — seta não: o Text+ não tem o glifo.
    sep = " > " if any(v < 0 for _q, v in pontos) else "-"
    if len(vals) == 2:
        return [(f"{vals[0]}{sep}{vals[1]}", False)]
    tre = [(f"{vals[i]}{sep}{vals[i + 1]} (", False)]
    if i:
        tre.append((sep.join(vals[:i]) + sep, False))
    tre.append((f"{vals[i]}{sep}{vals[i + 1]}", True))
    if i + 2 < len(vals):
        tre.append((sep + sep.join(vals[i + 2:]), False))
    tre.append((")", False))
    return tre


def _linear(interp: str) -> bool:
    """Sem tipo declarado conta como linear (o caminho de antes)."""
    return not interp or interp.strip().lower() == "linear"


def _linha_animada(efeito: str, nome: str, unidade: str, interp: str, pontos: list, a: float) -> list:
    """A linha de um parâmetro animado no pedaço que começa no quadro `a` do segmento (formato v2:
    `3D Warp · escala X · linear · 3 keyframes > 56%-75% (56%-75%-100%)`, o nº de keyframes em vermelho).
    Curva NÃO linear: o tipo e só o 1º e o último valor (autor, 2026-10-23)."""
    tipo = (interp or "linear").strip().lower()
    rotulo = [(f"{efeito} · {nome} · {tipo} · ", False), (str(len(pontos)), True),
              (f" keyframe{'s' if len(pontos) != 1 else ''} > ", False)]
    if not _linear(interp):
        return rotulo + [(f"{_num(pontos[0][1], unidade)} > {_num(pontos[-1][1], unidade)}", False)]
    if a < pontos[0][0]:
        return rotulo + [(f"parado em {_num(pontos[0][1], unidade)}", False)]
    for i in range(len(pontos) - 1):
        if pontos[i][0] <= a < pontos[i + 1][0]:
            return rotulo + _cadeia(pontos, i, unidade)
    return rotulo + [(f"parado em {_num(pontos[-1][1], unidade)}", False)]


def _cortes(dur: int, pontos_por_param: list) -> list[int]:
    """Os quadros onde a nota é cortada: os keyframes dentro do segmento, sem pedaços curtos."""
    qs = sorted({0, dur} | {int(round(q)) for pts in pontos_por_param for q, _v in pts if 0 < q < dur})
    fora = [qs[0]]
    for q in qs[1:]:
        if q - fora[-1] >= MIN_QUADROS or q == dur:
            fora.append(q)
    if len(fora) > 2 and fora[-1] - fora[-2] < MIN_QUADROS:
        del fora[-2]
    return fora


def _neutro(p: dict) -> bool:
    """Posição 0, escala 100% nos dois eixos, sem rotação, crop, flip nem keyframe."""
    perto = lambda v, alvo: abs(float(v or 0) - alvo) < 1e-6  # noqa: E731
    sx = p.get("scale_x", 1.0)
    return (perto(p.get("pos_x"), 0) and perto(p.get("pos_y"), 0) and perto(sx, 1.0)
            and perto(p.get("scale_y", sx), 1.0) and perto(p.get("rot_z"), 0)
            and not (p.get("crop_frac") or p.get("flip_x") or p.get("flip_y") or p.get("kf")))


def _estaticas(efeitos: list, estabilizacao_traduzida: bool = False) -> tuple[list, str | None]:
    """As linhas dos efeitos que NÃO animam e a cor mais forte que eles pedem. `estabilizacao_traduzida`: o Stabilize
    vai pronto ao estabilizador do Resolve (`estabilizacao.traduzivel`) — a nota registra, sem cor (autor, 2026-10-24)."""
    linhas, cor = [], None
    for e in efeitos:
        eid, cat, p = e.get("name") or "", e.get("category"), e.get("params") or {}
        if eid in _SEM_NOTA or cat in ("title", "transition", "gain") or p.get("animated"):
            continue
        nome = _nome(eid, e.get("label") or "")
        if "STABIL" in eid.upper():
            z = p.get("zoom_pct")
            rotulo = "ESTABILIZAÇÃO TRADUZIDA" if estabilizacao_traduzida else "ESTABILIZADO NO AVID"
            linhas.append([(f"{rotulo} · {nome}" + (f" · zoom {_num(z, '%')}" if z else ""), False)])
            if not estabilizacao_traduzida:
                cor = "refazer"
        elif cat == "color":
            linhas.append([(f"COR NO AVID · {nome}", False)])
            cor = cor or "conferir"
        elif cat == "geometric" and e.get("reproducible"):
            # O Motion do Premiere vem em TODO clipe (é intrínseco): neutro, não é nota — no DU todas as
            # 20 notas eram "MOTION · posição 0, 0 · escala 100%" (2026-10-06). No Avid o efeito
            # geométrico só existe se o editor o pôs, então lá a nota fica.
            if eid == "Motion" and _neutro(p):
                continue
            partes = []
            if "pos_x" in p or "pos_y" in p:
                partes.append(f"posição {_num(p.get('pos_x', 0))}, {_num(p.get('pos_y', 0))}")
            if "scale_x" in p:
                sx, sy = p["scale_x"] * 100, p.get("scale_y", p["scale_x"]) * 100
                partes.append(f"escala {_num(sx, '%')}" if abs(sx - sy) < 1e-6
                              else f"escala {_num(sx, '%')} x {_num(sy, '%')}")
            if p.get("rot_z"):
                partes.append(f"rotação {_num(p['rot_z'], '°')}")
            linhas.append([(" · ".join([nome.upper()] + partes), False)])     # traduzido: sem cor
        elif cat == "geometric" or cat == "ajuste":
            continue            # a camada de ajuste É o clipe (a cor do tipo na cabeça já o diz)
        elif e.get("reproducible"):
            # O que o app TRADUZ (LUT no nó, máscara e blur no Fusion, preto e branco no nó de cor — as categorias
            # do Premiere): a nota registra, sem cor. Antes caía em "EFEITO NÃO TRADUZIDO" e pintava de refazer o
            # que veio pronto (PRODC, 2026-10-23). O "conferir" de cada um é do marcador, não daqui.
            linhas.append([(f"{nome} · traduzido", False)])
        else:
            linhas.append([(f"EFEITO NÃO TRADUZIDO · {nome}", False)])
            cor = "refazer"
    return linhas, cor


#: Do sinal mais forte para o mais fraco. A DISTORÇÃO vem antes de tudo (autor, 2026-09-27): é o
#: erro que o colorista não pode deixar passar, e quem resolve é a produção, não ele.
_FORCA = ("distorcao", "refazer", "conferir")


def _mais_forte(a, b):
    return next((c for c in _FORCA if c in (a, b)), a or b)


def _proporcao(w: int, h: int) -> str:
    return _num(round(w / h, 2)) + ":1"


def _stretch(s: dict, master: dict) -> list:
    """O Reformat STRETCH do FrameFlex: a mídia é esticada até o quadro da timeline, sem guardar a
    proporção. Com raster diferente, a imagem DISTORCE (os takes da praia da PRODA, 2048×1080 numa
    timeline HD). Só o Stretch avisa: Pillarbox, Crop e Keep Size não deformam (regra do autor)."""
    if s.get("reframe_mode") != "stretch":
        return []
    ident = (master or {}).get("identidade") or {}
    w, h = int(ident.get("largura") or 0), int(ident.get("altura") or 0)
    midia = f" · mídia {w}x{h} ({_proporcao(w, h)})" if w and h else ""
    return [[("STRETCH: POSSÍVEL DISTORÇÃO DA IMAGEM", True)],
             [(f"Reformat Stretch no Avid{midia}: conferir e avisar a produção", False)]]


def _pct_avid(tl_por_fonte: float) -> str:
    """O `speed_ratio` é timeline ÷ fonte (banco `protocolos/avb/estruturas.md`); o Avid mostra o
    inverso, em %: 1,1617 → 86% (câmera lenta)."""
    return _num(round(100 / tl_por_fonte), "%") if tl_por_fonte else "?"


def _velocidade(s: dict) -> list:
    """A velocidade que o EDITOR mudou. A conformação de fps (`conform`) não é decisão de edição e
    não avisa; a rampa ganha um resumo aqui, além do plano B de um Text por quadro."""
    classe = s.get("motion_class") or ""
    if classe == "freeze":
        return [[("FREEZE FRAME", False)]]
    if classe == "ramp":
        # só a velocidade do 1º e do último instante (autor, 2026-10-23): nada de valor por quadro
        mapa = sorted((float(t), float(v)) for t, v in (s.get("source_offset_map") or []))
        vels = [(v1 - v0) / (t1 - t0) * 100 for (t0, v0), (t1, v1) in zip(mapa, mapa[1:]) if t1 > t0]
        faixa = f" · {_num(round(vels[0]), '%')} > {_num(round(vels[-1]), '%')}" if vels else ""
        return [[("RAMPA DE VELOCIDADE", "rampa"), (faixa, False)]]
    if classe == "reverse":
        return [[(f"VELOCIDADE REVERSA · {_pct_avid(float(s.get('relative_speed') or 1))}", False)]]
    if classe in ("creative", "conform+creative"):
        rel = float(s.get("relative_speed") or s.get("speed_ratio") or 1)
        if round(100 / rel) == 100:
            return []           # 0,99999 ou 0,998 é 100%: não é velocidade do editor (PRODC, 2026-10-23)
        jeito = "câmera lenta" if rel > 1 else "acelerado"
        return [[(f"VELOCIDADE {_pct_avid(rel)} ({jeito})", False)]]
    return []


def _tc(frames: int, fps: int) -> str:
    fps = max(1, fps)
    f = int(frames)
    return f"{f // (3600 * fps) % 24:02d}:{f // (60 * fps) % 60:02d}:{f // fps % 60:02d}:{f % fps:02d}"


def _tc_para_quadros(tc: str, nominal: int) -> int:
    """`HH:MM:SS:QQ` (ou `;` do drop-frame) → quadros no nominal."""
    h, m, s, f = (int(x) for x in str(tc).replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * max(1, int(nominal)) + f


def _quadros(tc: str, fps: float) -> int:
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * round(fps) + f


def das_notas(resultado: dict) -> list[dict]:
    """As notas de uma timeline (o `resultado` da Carta / da leitura da bin)."""
    fps = float(resultado.get("timeline_fps") or 24)
    masters = resultado.get("masters") or {}
    notas = []
    for i, s in enumerate(resultado.get("segments") or []):
        if not s or s.get("is_audio") or s.get("is_gap") or s.get("is_transition") or s.get("disabled"):
            continue
        inicio, dur = _quadros(s["timeline_tc_in"], fps), int(s.get("duration_frames") or 0)
        if dur <= 0:
            continue
        master = masters.get(s.get("mob_id") or "") or {}
        antes = len(notas)
        try:
            _notas_do_segmento(notas, s, i, inicio, dur, master)
        finally:
            # A 1ª linha diz DE QUEM é a nota (autor, 2026-10-06): com clipes sobrepostos, a nota da V1 e
            # a da V4 eram iguais. "V1 <nome do clipe>"; a descrição começa na linha de baixo. O Text+
            # (formato v2) desenha a cabeça pela `cabeca_info`: trilha · nome na cor do tipo · TC source.
            info = {"trilha": f"V{int(s.get('track') or 0)}", "nome": s.get("clip_name") or "",
                    "tipo": _tipo(s), "src": _src(s, dur, master)}
            cabeca = [(f"{info['trilha']} {info['nome']}".rstrip(), False)]
            for n in notas[antes:]:
                n["linhas"] = [cabeca] + n["linhas"]
                n["cabeca"] = 1     # quantas linhas são de cabeça: o NOME do marcador é a 1ª da descrição
                n["cabeca_info"] = info
                n["ordem"] = inicio
                n["nome"] = " | ".join("".join(t for t, _d in linha) for linha in n["linhas"])
    return notas


def _tipo(s: dict) -> str:
    """O TIPO do clipe, que dá a cor do nome na cabeça (paleta do lab v3)."""
    if s.get("ajuste"):
        return "ajuste"
    if s.get("multicam"):
        return "multicam"
    if s.get("composto"):
        return "composto"
    if any(e.get("category") == "title" for e in s.get("effects") or []):
        return "titulo"
    return "video"


def _src(s: dict, dur: int, master: dict) -> tuple[str, str] | None:
    """O TC source in > out do segmento (para o editor saber se está no quadro certo): o TC de início da
    mídia + o ponto de entrada. Avid: a identidade do master; Premiere: o `Media` do projeto. Sem o TC
    de início da mídia, nada (um TC errado engana mais que nenhum)."""
    ident = (master or {}).get("identidade") or {}
    midia = (s.get("prproj") or {}).get("midia") or {}
    if ident.get("tc_inicio") is not None:
        base, tc_fps = int(ident["tc_inicio"]), int(ident.get("tc_fps") or round(float(s.get("source_fps") or 24)))
    elif midia.get("tc_quadros") is not None:
        base, tc_fps = int(midia["tc_quadros"]), int(round(float(midia.get("fps") or s.get("source_fps") or 24)))
    else:
        return None
    ini = base + int(s.get("source_start_frames") or 0)
    mapa = s.get("source_offset_map") or []
    if mapa:
        fonte = int(round(max(float(v) for _t, v in mapa)))
    else:
        r = float(s.get("speed_ratio") or 1) or 1
        fonte = int(round(dur / r)) if s.get("motion_class") != "freeze" else 1
    return _tc(ini, tc_fps), _tc(ini + max(1, fonte), tc_fps)


def _notas_do_segmento(notas: list, s: dict, i: int, inicio: int, dur: int, master: dict) -> None:
    """As notas de UM segmento (acrescenta em `notas`); a linha de cabeça vem do `das_notas`."""
    from estabilizacao import traduzivel

    efeitos = s.get("effects") or []
    estab = traduzivel(s)
    linhas_fixas, cor = _estaticas(efeitos, estab)
    # A estabilização traduzida não pinta o clipe, mas ganha o MARCADOR de conferir (autor, 2026-10-24): quem navega
    # pelos marcadores, ou não liga a trilha de notas, precisa ver; pode haver diferença em outras situações.
    marcar = "conferir" if estab and any("STABIL" in (e.get("name") or "").upper() for e in efeitos) else None
    # O Stretch vai no TOPO: a 1ª linha é o nome do marcador, o que o colorista lê primeiro.
    esticado, veloz = _stretch(s, master), _velocidade(s)
    if veloz:
        linhas_fixas, cor = veloz + linhas_fixas, _mais_forte(cor, "conferir")
    if esticado:
        linhas_fixas, cor = esticado + linhas_fixas, "distorcao"
    animados = [e for e in efeitos if (e.get("params") or {}).get("animated")]
    if not animados:
        if linhas_fixas:
            notas.append(_nota(inicio, dur, linhas_fixas, cor, i, marcar))
        return
    params = []   # (efeito, nome, unidade, interp, pontos)
    for e in animados:
        p = e["params"]
        for n, pts in sorted((p.get("keyframes_avid") or {}).items()):
            if len(pts) >= 1 and n in PARAMETRO:
                params.append((_nome(e["name"], e.get("label") or ""), *PARAMETRO[n],
                               (p.get("interp_avid") or {}).get(n, ""),
                               sorted((float(q), float(v)) for q, v in pts)))
        cor = _mais_forte(cor, "refazer" if not e.get("reproducible") else "conferir")
    # só a curva LINEAR corta a nota: a não linear mostra o 1º e o último valor o segmento inteiro
    cortes = _cortes(dur, [x[4] for x in params if _linear(x[3])])
    for a, b in zip(cortes, cortes[1:]):
        linhas = [_linha_animada(ef, nome, uni, interp, pts, a)
                  for ef, nome, uni, interp, pts in params[:MAX_PARAMETROS]]
        if len(params) > MAX_PARAMETROS:
            linhas.append([(f"+{len(params) - MAX_PARAMETROS} parâmetros", False)])
        notas.append(_nota(inicio + a, b - a, linhas + linhas_fixas, cor, i, marcar))


def _nota(inicio: int, dur: int, linhas: list, cor, segmento: int | None = None, marcar=None) -> dict:
    """`cor` pinta o clipe E marca; `marcar` só marca (a nota e o clipe ficam sem cor)."""
    return {"inicio": inicio, "dur": dur, "linhas": linhas, "cor": cor, "grupo": "efeito",
            "segmento": segmento, "marcar": marcar,
            "nome": " | ".join("".join(t for t, _d in linha) for linha in linhas)}
