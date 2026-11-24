"""ATUALIZAR CORTE no Baselight: a montagem nova (v2) numa scene NOVA, com a cor que o colorista já fez na scene dele
(proposta do Ciclo Assist `docs/plano/2026-11-22-baselight-no-app.md`, etapa 5; medido no laboratório BL09 e aprovado
pelo autor em 2026-11-22: https://claude.ai/artifact/C3fHr38DkAKLSMV4u3gi3x).

As três decisões do autor:
1. **Plano que o colorista DIVIDIU** (cores diferentes em cada pedaço): o plano da v2 é cortado no MESMO quadro de fonte,
   e cada metade herda a sua cor — um ponto de edição a mais, nenhum quadro muda (`cortes_do_colorista` +
   `dividir_xmeml`, ANTES do conform).
2. **Os markers do colorista** vão para a scene nova no mesmo quadro de FONTE; o de plano retirado vira nota no resumo
   (`mover_marcas`).
3. **A cor vem pelo Multi-Paste do Baselight** (arquivo + TC: 7/7 no BL09; só pelo nome erra calado), e a CONFERÊNCIA do
   Ciclo compara cada plano com o que a comparação dele espera e corrige pela cópia do BLG (`cor_flapi.py`).

Este módulo é PURO (stdlib): roda no Python do app (os testes) e no da FilmLight (`cor_flapi.py` o importa).
"""
from __future__ import annotations

import base64
import copy
import os
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from fractions import Fraction

#: os operadores de cor do BLG e os números deles (doubles em hexadecimal); o resto (ids, a data) não entra
_OP = re.compile(r"\d+:(GR_\w+Rop) ")
_DOUBLE = re.compile(r"\bf ([0-9a-f]{16})\b")
PREFIXO_CICLO = "[Ciclo] "
#: o que está em TODO plano, com ou sem cor (a camada 0: a sequência, o som dela, o transform da imagem; e a moldura de
#: cada camada) — medido no BL09: um plano sem cor tem só estes
_CAMADA_ZERO = {"GR_InsideOutsideRop", "GR_PluginInputRop", "GR_SequenceRop", "GR_AudioSequenceRop",
                "GR_ImageTransformParamsRop"}


def texto_blg(payload: str) -> str:
    """O BLG de `Shot.get_blg_payload()`: base64 → 8 bytes de cabeçalho → zlib → texto (BL09, 7.0.3)."""
    if not payload:
        return ""
    try:
        return zlib.decompress(base64.b64decode(payload)[8:]).decode("utf-8", "replace")
    except (ValueError, zlib.error):
        return payload


def impressao(payload: str) -> str:
    """A impressão digital da COR de um plano: cada linha de operador `GR_…Rop` com os números dela, na ordem — o que
    muda quando a cor muda e não muda quando só o plano (ids, data, scene) muda. Sem operador = "" (sem cor)."""
    linhas = []
    for linha in texto_blg(payload).splitlines():
        m = _OP.search(linha)
        if not m or m.group(1) in _CAMADA_ZERO:
            continue
        linhas.append(m.group(1) + ":" + ",".join(_DOUBLE.findall(linha)))
    return "|".join(linhas)


# ── os KEYFRAMES (cor animada) — medido no BL09, 7.0.3, 2026-11-22 ───────────────────────────────────────────────────
# A curva é um `GM_Bezier1dInterp`: `… t <hex> <n>:6 0 <k> [tempo valor ângulo comprimento ângulo comprimento]×k …  `,
# tempo em SEGUNDOS desde o INÍCIO DO PLANO; `<n>` = o tamanho do corpo − 1 (os dois espaços do fim contam um). O
# Multi-Paste DESLOCA os keyframes pela diferença de fonte (o plano aparado na cabeça em 12: 7 → −5); o
# `apply_blg_payload` NÃO — copia os tempos crus e a animação escorrega sobre a imagem. Quem copia pelo BLG desloca.

_BEZ = re.compile(r'(GM_Bezier1dInterp \S+ \S+ \S+ \S+ t [0-9a-f]{16} )(\d+):(6 0 \d+ [^"]*)"')


def _cru(payload: str) -> str:
    return zlib.decompress(base64.b64decode(payload)[8:]).decode("latin1")


def _gravar(texto: str) -> str:
    import struct

    t = texto.encode("latin1")
    return base64.b64encode(struct.pack("<Q", len(t)) + zlib.compress(t)).decode()


def keyframes(payload: str) -> list[list[float]]:
    """Os tempos (s, desde o início do plano) de cada curva animada do BLG, na ordem."""
    if not payload:
        return []
    out = []
    for m in _BEZ.finditer(_cru(payload)):
        tok = m.group(3).split(" ")
        k = int(tok[2])
        out.append([float(tok[3 + 6 * j]) for j in range(k)])
    return out


def deslocar_keyframes(payload: str, segundos: float) -> str:
    """O BLG com TODOS os keyframes deslocados de `segundos` (o plano da v2 começa em outra fonte). Recusa (ValueError)
    se uma curva não estiver no formato medido — nunca grava um BLG adivinhado."""
    if not payload or abs(segundos) < 1e-9:
        return payload
    texto = _cru(payload)

    def troca(m: re.Match) -> str:
        corpo = m.group(3)
        if int(m.group(2)) != len(corpo) - 1:
            raise ValueError("curva de keyframe fora do formato medido (o tamanho não bate)")
        tok = corpo.split(" ")
        for j in range(int(tok[2])):
            i = 3 + 6 * j
            tok[i] = "%.20g" % (float(tok[i]) + segundos)
        novo = " ".join(tok)
        return f'{m.group(1)}{len(novo) - 1}:{novo}"'

    return _gravar(_BEZ.sub(troca, texto))


def keyframes_iguais(a: list[list[float]], b: list[list[float]], tol: float = 1e-4) -> bool:
    return len(a) == len(b) and all(len(x) == len(y) and all(abs(p - q) <= tol for p, q in zip(x, y))
                                    for x, y in zip(a, b))


# ── o LOOK: uma faixa de cor sobre VÁRIOS planos (decisão do autor, 2026-11-22: vai também ao plano novo e ao take
# trocado que caem dentro dela) — medido no BL09 ("BL09 V1 look"), 7.0.3 ──────────────────────────────────────────────
# No BLG de CADA plano a faixa aparece inteira, do tamanho do plano: o BLG não diz que ela atravessa. O look se reconhece
# pelo CONTEÚDO: a mesma camada (o mesmo operador, com os mesmos números) em planos VIZINHOS da scene do colorista.
# O grafo: `GM_Timeline 2:gm 3 <S+3> <faixas…> 7 8 10 0 0 S S 0 S S+1 1 S+2`; cada `GM_Strip 2:gm 1 1 <moldura> 1 o 0
# <início> <duração> <índice> f f 0` (camadas 0…S−2 de cima para baixo; a mídia por último); a moldura
# `GR_InsideOutsideRop … 7 3 0 <inteiro> <operador> … <n>:Layer:<N>`.

_OBJ = re.compile(r'\n  \((\d+)\)="(.*?)"(?=,\n  \(|,\n \],|\n \])', re.S)
_TL = re.compile(r'(\((\d+)\)="11:GM_Timeline 2:gm 3 )(\d+) ([\d ]+?) 7 8 10 0 0 (\d+) (\d+) 0 (\d+) (\d+) 1 (\d+) "')


def _objetos(texto: str) -> dict[int, str]:
    return {int(m.group(1)): m.group(2) for m in _OBJ.finditer(texto)}


def _chave_da_camada(objetos: dict[int, str], moldura: int) -> tuple[str, str]:
    """(nome "Layer:N", a chave do CONTEÚDO: o operador sem números de objeto) de uma faixa de cor."""
    m = objetos.get(moldura, "")
    nome = re.search(r"\d+:(Layer:\d+)", m)
    partes = m.split()
    try:
        op = int(partes[partes.index("7") + 4]) if "16:gr_insideoutside" in m else -1
    except (ValueError, IndexError):
        op = -1
    texto_op = re.sub(r"\bo \d+\b", "o *", objetos.get(op, ""))
    return (nome.group(1) if nome else ""), texto_op


def camadas(payload: str) -> list[dict]:
    """As faixas de COR do plano (sem a da mídia), de cima para baixo: `{faixa, nome, chave}`."""
    if not payload:
        return []
    texto = _cru(payload)
    obj = _objetos(texto)
    tl = _TL.search(texto)
    if not tl:
        return []
    out = []
    for faixa in (int(x) for x in tl.group(4).split()):
        partes = obj.get(faixa, "").split()
        if len(partes) < 5 or partes[0] != "8:GM_Strip":
            continue
        nome, chave = _chave_da_camada(obj, int(partes[4]))
        if nome:                                  # a da mídia não tem "Layer:N"
            out.append({"faixa": faixa, "nome": nome, "chave": chave})
    return out


def so_camadas(payload: str, chaves: set[str]) -> str:
    """O BLG com SÓ as camadas cujo conteúdo está em `chaves` (e a faixa da mídia): as outras saem do `GM_Timeline` e
    os índices das faixas que ficam são refeitos. Recusa (ValueError) o que não estiver no formato medido."""
    texto = _cru(payload)
    tl = _TL.search(texto)
    if not tl:
        raise ValueError("GM_Timeline fora do formato medido")
    faixas = [int(x) for x in tl.group(4).split()]
    s_ = len(faixas)
    if int(tl.group(3)) != s_ + 3 or [int(tl.group(i)) for i in (5, 6, 7, 8, 9)] != [s_, s_, s_, s_ + 1, s_ + 2]:
        raise ValueError("GM_Timeline fora do formato medido (as contas não batem)")
    obj = _objetos(texto)
    cor = {c["faixa"]: c for c in camadas(payload)}
    ficam = [f for f in faixas if f not in cor or cor[f]["chave"] in chaves]
    if not any(f in cor for f in ficam):
        return ""
    n = len(ficam)
    novo_tl = (f'{tl.group(1)}{n + 3} {" ".join(map(str, ficam))} 7 8 10 0 0 {n} {n} 0 {n} {n + 1} 1 {n + 2} "')
    texto = texto[:tl.start()] + novo_tl + texto[tl.end():]
    # os índices: as camadas que ficam, na ordem, 0…n−2; a mídia por último (n−1)
    ordem = [f for f in ficam if f in cor] + [f for f in ficam if f not in cor]
    for idx, f in enumerate(ordem):
        velho = obj[f]
        partes = velho.split(" ")
        if partes[0] != "8:GM_Strip" or len(partes) < 13:
            raise ValueError("GM_Strip fora do formato medido")
        partes[-5] = str(idx)                      # "… <início> <duração> <índice> f f 0 "
        texto = texto.replace(f'({f})="{velho}"', f'({f})="{" ".join(partes)}"', 1)
    return _gravar(texto)


def looks_da_scene(v1: list[dict]) -> list[set[str]]:
    """Para cada plano da scene do colorista (ordem de `v1`), as chaves das camadas que ele divide com um VIZINHO
    emendado na gravação (o look). `v1[i]["camadas"]` = `camadas(blg)`."""
    por_rec = sorted(range(len(v1)), key=lambda i: v1[i]["rec"][0])
    looks: list[set[str]] = [set() for _ in v1]
    for a, b in zip(por_rec, por_rec[1:]):
        if v1[a]["rec"][1] != v1[b]["rec"][0]:
            continue
        comum = {c["chave"] for c in v1[a].get("camadas", [])} & {c["chave"] for c in v1[b].get("camadas", [])}
        looks[a] |= comum
        looks[b] |= comum
    return looks


def vizinhos_e_substituidos(i: int, v2: list[dict], mapa: list[dict], v1: list[dict]) -> tuple[int | None, int | None,
                                                                                           list[int]]:
    """Para o plano SEM cor `i` da v2 (novo ou take trocado): os planos da v1 dos dois vizinhos dele na v2 (`None` na
    ponta ou se o vizinho também não veio da v1) e os planos da v1 que ele SUBSTITUI — os que ficavam entre esses dois,
    na ordem da v1."""
    por_rec = sorted(range(len(v2)), key=lambda k: v2[k]["rec"][0])
    pos = por_rec.index(i)
    ant = mapa[por_rec[pos - 1]]["v1"] if pos > 0 else None
    pro = mapa[por_rec[pos + 1]]["v1"] if pos + 1 < len(por_rec) else None
    subst: list[int] = []
    if ant is not None and pro is not None:
        a_fim, p_ini = v1[ant]["rec"][1], v1[pro]["rec"][0]
        if a_fim <= p_ini:
            subst = [k for k, o in enumerate(v1) if a_fim <= o["rec"][0] and o["rec"][1] <= p_ini]
    return ant, pro, subst


def look_para(i: int, v2: list[dict], mapa: list[dict], v1: list[dict], looks: list[set[str]]) -> set[str]:
    """O look que vai ao plano SEM cor `i` da v2 (novo ou take trocado): o dos planos da v1 que ele SUBSTITUI (entre os
    vizinhos dele na v2, na ordem da v1) e o que os dois vizinhos dividem."""
    ant, pro, subst = vizinhos_e_substituidos(i, v2, mapa, v1)
    vai: set[str] = set()
    if ant is not None and pro is not None:
        vai |= looks[ant] & looks[pro]
        for k in subst:
            vai |= looks[k]
    return vai


def _nfc(p: str) -> str:
    return unicodedata.normalize("NFC", os.path.normpath(p or ""))


def mesmo_arquivo(a: str, b: str) -> bool:
    """Caminho inteiro (dois A001C003 em cartões diferentes NÃO são o mesmo, BL08 P1), em NFC (o macOS lista em NFD)."""
    return bool(a) and _nfc(a) == _nfc(b)


def _comum(a: tuple, b: tuple) -> int:
    return min(a[1], b[1]) - max(a[0], b[0])


def cortes_do_colorista(v1: list[dict]) -> dict[str, list[int]]:
    """Onde o colorista dividiu um plano: dois planos da scene dele do MESMO arquivo, com a fonte EMENDADA (o fim de um é o
    começo do outro) e cores DIFERENTES. `{arquivo: [quadro de fonte do corte, …]}`. `v1`: `{arquivo, src: (a, b),
    cor}` (b exclusivo)."""
    out: dict[str, set] = {}
    for x in v1:
        for y in v1:
            if x is y or not mesmo_arquivo(x["arquivo"], y["arquivo"]):
                continue
            if x["src"][1] == y["src"][0] and x.get("cor") != y.get("cor"):
                out.setdefault(_nfc(x["arquivo"]), set()).add(int(y["src"][0]))
    return {k: sorted(v) for k, v in out.items()}


def mapear(v2: list[dict], v1: list[dict]) -> list[dict]:
    """Para cada plano da v2, o plano da v1 de onde vem a cor: o MESMO arquivo com trecho de fonte em comum, o de maior
    trecho. Nenhum = plano novo ou take trocado (sem cor). Mais de um com cores diferentes e empate = ninguém (vai ao
    editor com o aviso). `{v1: índice | None, motivo, aviso}` por plano."""
    out = []
    for p in v2:
        cand = [(i, _comum(p["src"], o["src"])) for i, o in enumerate(v1)
                if mesmo_arquivo(p["arquivo"], o["arquivo"]) and _comum(p["src"], o["src"]) > 0]
        cand.sort(key=lambda t: -t[1])
        cores = {v1[i].get("cor") for i, _ in cand}
        if not cand:
            usados = any(mesmo_arquivo(p["arquivo"], o["arquivo"]) for o in v1)
            out.append({"v1": None, "aviso": "", "motivo": "trecho novo deste arquivo" if usados else
                        "arquivo que não está na scene do colorista (plano novo ou take trocado)"})
        elif len(cores) > 1 and len(cand) > 1 and cand[0][1] == cand[1][1]:
            out.append({"v1": None, "motivo": "empate", "aviso": "o plano cobre por igual dois planos do colorista "
                                                                  "com cores diferentes: o colorista decide"})
        else:
            aviso = ("cobre %d planos do colorista com cores diferentes: ficou a do maior trecho" % len(cand)
                     if len(cores) > 1 else "")
            out.append({"v1": cand[0][0], "aviso": aviso, "motivo": "cor da scene do colorista"})
    return out


def levar_grupos(grupos: dict[str, list[int]], mapa: list[dict], v2: list[dict] | None = None,
                 v1: list[dict] | None = None) -> list[dict]:
    """Os GRUPOS do colorista (`{nome: [índice do plano na v1, …]}`) na scene nova, pelo MESMO casamento da cor (`mapear`):
    cada plano da v2 que herdou a cor de um membro entra no grupo; o membro que não chegou (retirado, take trocado) é dito.
    ⭐ Decisão do autor (2026-11-23), a regra do look: o plano SEM cor (novo, take trocado) entra no grupo do plano que
    ele SUBSTITUI, ou do grupo dos DOIS vizinhos (`vizinhos_e_substituidos`; precisa de `v2` e `v1` com `rec`) — `novos`.
    ⛔ MEDIDO (BL09, 7.0.3, 2026-11-22): o produto colava com `PasteGroups=0` e os grupos SUMIAM calados; o Multi-Paste com
    `PasteGroups=1` leva o nome e só os planos que ELE casou (o take trocado sai do grupo, também calado).
    `[{nome, v2: [índice na v2, …], novos: [índice na v2, …], fora: [índice na v1, …]}]`, na ordem dos nomes."""
    viz = {j: vizinhos_e_substituidos(j, v2, mapa, v1) for j, m in enumerate(mapa)
           if m["v1"] is None and v2 is not None and v1 is not None}
    out = []
    for nome in sorted(grupos):
        membros = set(grupos[nome])
        herdaram = [j for j, m in enumerate(mapa) if m["v1"] in membros]
        novos = [j for j, (ant, pro, subst) in viz.items()
                 if membros & set(subst) or (ant in membros and pro in membros)]
        chegaram = {mapa[j]["v1"] for j in herdaram}
        out.append({"nome": nome, "v2": sorted(herdaram + novos), "novos": sorted(novos),
                    "fora": sorted(membros - chegaram)})
    return out


def mover_marcas(marcas: list[dict], v1: list[dict], v2: list[dict]) -> tuple[list[dict], list[dict]]:
    """Os markers do colorista (`{quadro, nota, categoria}`, quadro de GRAVAÇÃO da scene dele) para a scene nova, pelo
    quadro de FONTE: o plano da v1 sob o marker → o quadro de fonte → o plano da v2 com o mesmo arquivo e esse quadro.
    Devolve (movidos com o quadro novo, perdidos com o motivo). Os "[Ciclo] …" não são do colorista: ficam."""
    movidos, perdidos = [], []
    for m in marcas:
        if str(m.get("nota") or "").startswith(PREFIXO_CICLO):
            continue
        o = next((x for x in v1 if x["rec"][0] <= m["quadro"] < x["rec"][1]), None)
        if o is None:
            perdidos.append({**m, "motivo": "fora de qualquer plano da scene do colorista"})
            continue
        fonte = o["src"][0] + (m["quadro"] - o["rec"][0])
        p = next((x for x in v2 if mesmo_arquivo(x["arquivo"], o["arquivo"]) and x["src"][0] <= fonte < x["src"][1]),
                 None)
        if p is None:
            perdidos.append({**m, "motivo": "o trecho do plano saiu da montagem"})
        else:
            movidos.append({**m, "quadro": p["rec"][0] + (fonte - p["src"][0]), "de": m["quadro"]})
    return movidos, perdidos


# ── a divisão no xmeml (decisão 1) ────────────────────────────────────────────────────────────────────────────────────

def _fps(rate: ET.Element | None) -> Fraction:
    if rate is None or not rate.findtext("timebase"):
        return Fraction(25)
    tb = int(rate.findtext("timebase"))
    return Fraction(tb * 1000, 1001) if rate.findtext("ntsc") == "TRUE" else Fraction(tb)


def _caminho(f: ET.Element | None) -> str:
    pu = f.find("pathurl") if f is not None else None
    if pu is None or not pu.text:
        return ""
    return urllib.parse.unquote(pu.text.replace("file://localhost", "").replace("file://", ""))


def dividir_xmeml(entrada: str, saida: str, cortes: dict[str, list[int]]) -> list[dict]:
    """Corta cada clipitem de VÍDEO que atravessa um corte do colorista (no mesmo arquivo), no mesmo quadro de fonte.
    Só divide quando o ponto cai num quadro INTEIRO da timeline (mesma taxa: o caso comum) e o arquivo não é sequência de
    imagens (o número do quadro no nome muda a conta). Devolve o que dividiu; grava `saida` (igual à entrada se nada)."""
    arvore = ET.parse(entrada)
    seq = arvore.getroot().find(".//sequence")
    fps_tl = _fps(seq.find("rate"))
    defs = {f.get("id"): f for f in seq.iter("file") if f.find("pathurl") is not None}
    feitos = []
    ids = {e.get("id") for e in seq.iter("clipitem")}
    for trilha in seq.find("media/video").findall("track"):
        for ci in list(trilha.findall("clipitem")):
            fe = ci.find("file")
            f = defs.get(fe.get("id")) if fe is not None else None
            arq = _caminho(f)
            pontos = cortes.get(_nfc(arq)) if arq else None
            if not pontos or "%" in arq:
                continue
            fps_f = _fps(f.find("rate"))
            for p in reversed(pontos):                     # do fim para o começo: o `ci` original fica com a cabeça
                q = Fraction(p) * fps_tl / fps_f            # o ponto em quadros da timeline, contado do início do arquivo
                if q.denominator != 1:
                    continue
                q = int(q)
                entra, sai = int(ci.findtext("in")), int(ci.findtext("out"))
                if not (entra < q < sai):
                    continue
                corte_tl = int(ci.findtext("start")) + (q - entra)
                novo = copy.deepcopy(ci)
                n = 2
                while f"{ci.get('id')}-c{n}" in ids:
                    n += 1
                novo.set("id", f"{ci.get('id')}-c{n}")
                ids.add(novo.get("id"))
                for link in novo.findall("link"):
                    novo.remove(link)
                nf = novo.find("file")
                if nf is not None:                         # a definição completa fica no original; a cópia referencia
                    for filho in list(nf):
                        nf.remove(filho)
                novo.find("start").text, novo.find("in").text = str(corte_tl), str(q)
                ci.find("end").text, ci.find("out").text = str(corte_tl), str(q)
                filhos = list(trilha)
                trilha.insert(filhos.index(ci) + 1, novo)
                feitos.append({"arquivo": arq, "fonte": p, "quadro_timeline": corte_tl})
    arvore.write(saida, encoding="UTF-8", xml_declaration=True)
    return feitos
