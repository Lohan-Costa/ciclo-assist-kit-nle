"""As camadas DO CICLO × as do COLORISTA na pilha de um plano do Baselight (atualizar corte com efeitos; proposta do
handoff de 2026-11-23, noite 4, aprovada pelo autor: "concordo com a abordagem").

O problema medido (PRODC, 2026-11-23): o Multi-Paste colava a pilha INTEIRA do colorista por cima da pilha da v2 — o
Retime/Transform/composição do Ciclo da v1 por cima dos da v2 (efeitos DOBRADOS) — e a conferência corrigia copiando o
BLG inteiro da v1 (efeitos VELHOS: a v2 mudou a velocidade, o Motion, a máscara). E o plano mascarado (multi-input) não
se lê pela FLAPI ("Allow Multi-Input BLGs"): o atualizar parava inteiro.

O desenho:
  - toda faixa que o Ciclo grava leva o NOME com o prefixo `TAG` ("Ciclo Transform", "Ciclo Layer:1 Comp:Over",
    "Ciclo Shape", "Ciclo Tracker"…) — `marcar`, aplicado ao texto que SÓ tem faixas do Ciclo (o molde, o BLG montado);
  - as faixas do COLORISTA de cada plano da v1 vêm do `.blscene` exportado da scene dele (`bl-export`, só leitura): ali
    o plano mascarado se lê, e o plano de uma trilha de baixo é o DELE (o `get_blg_payload` devolve a pilha de quem está
    por cima no 1º quadro) — `do_blscene`;
  - na v2 a pilha é refeita: as faixas do Ciclo DA V2 (o BLG que os efeitos/máscaras gravaram) + as do colorista, no
    mesmo lugar relativo (`juntar`): as que estavam ACIMA de todas as do Ciclo vão para o topo; as outras, logo acima da
    imagem (a cor age na imagem do plano, antes do Motion/composição da montagem — a janela do colorista acompanha a
    imagem). A faixa da MÍDIA (a imagem, o Retime da v2) é sempre a da v2.

Só stdlib: roda no python da FilmLight (`cor_flapi.py`) e nos testes. ⚠️ O texto do BLG é BYTES em latin1 (os prefixos
`<n>:` contam bytes): o que vem do SQLite (texto UTF-8) passa por `_bytes` antes.
"""
from __future__ import annotations

import re
import struct

#: o prefixo do nome das faixas que o Ciclo grava (a interface mostra o nome da camada)
TAG = "Ciclo "

_OBJ = re.compile(r'\n([ \t]*)\((\d+)\)="(.*?)"(?=,\n[ \t]*\(|,\n \],|\n \])', re.S)
_TL = re.compile(r'\((\d+)\)="11:GM_Timeline 2:gm (\d+) (\d+) ([\d ]+?) (0 0 \d+[\d ]*) "')
_NOME_SEGUIDO = re.compile(r" [0-9a-f]{8} ")


# ── os objetos do BLG ────────────────────────────────────────────────────────────────────────────────────────────────
def objetos(texto: str) -> dict[int, dict]:
    """{id: {tipo, sub, rev, filhos, estado, ini, fim}} — `estado` cru (como está no texto: escapes e as quebras de
    linha `\\n" "` do BLG); `ini`/`fim` = onde o corpo começa e acaba no texto."""
    out = {}
    # só a lista dos objetos: o BLG traz outras seções com `(n)="…"` (a interface dos operadores, `rop_type=…`)
    ini = texto.find("blg_ObjectStrings")
    ini = 0 if ini < 0 else ini
    fim = texto.find("\n ],", ini)
    for m in _OBJ.finditer(texto, ini, len(texto) if fim < 0 else fim + 4):
        corpo = m.group(3)
        tl, _, resto = corpo.partition(":")
        tipo, resto = resto[:int(tl)], resto[int(tl) + 1:]
        sl, _, resto = resto.partition(":")
        sub, resto = resto[:int(sl)], resto[int(sl) + 1:]
        toks = resto.split(" ")
        n = int(toks[1])
        out[int(m.group(2))] = {"tipo": tipo, "sub": sub, "rev": toks[0], "filhos": [int(x) for x in toks[2:2 + n]],
                                "estado": " ".join(toks[2 + n:]), "ini": m.start(3), "fim": m.end(3)}
    return out


def _corpo(o: dict, filhos: list[int] | None = None) -> str:
    fl = o["filhos"] if filhos is None else filhos
    return (f'{len(o["tipo"].encode("latin1"))}:{o["tipo"]} {len(o["sub"].encode("latin1"))}:{o["sub"]} {o["rev"]} '
            f'{len(fl)} ' + "".join(f"{f} " for f in fl) + o["estado"])


def _descendentes(objs: dict, raiz: int, vistos: list[int]) -> list[int]:
    if raiz == 0 or raiz in vistos or raiz not in objs:
        return vistos
    vistos.append(raiz)
    for f in objs[raiz]["filhos"]:
        _descendentes(objs, f, vistos)
    return vistos


def _faixa(o: dict) -> tuple[str, str, int] | None:
    """(início, duração ou fim, linha) do estado de um GM_Strip (`1 o 0 <a> <b> <linha> f f 0`)."""
    p = o["estado"].split()
    if o["tipo"] != "GM_Strip" or len(p) < 6:
        return None
    return p[3], p[4], int(p[5])


def _com_linha(estado: str, a: str, b: str, linha: int) -> str:
    p = estado.split(" ")
    p[3], p[4], p[5] = a, b, str(linha)
    return " ".join(p)


def nome(objs: dict, moldura: int) -> str:
    """O nome da camada (o que a interface mostra): a 1ª string `<n>:<texto>` do estado da moldura que vem seguida dos
    números da cor do rótulo (`42ca0000 …`) — contada pelo PREFIXO (o nome pode ter espaço: "Layer:1 Comp:Over")."""
    o = objs.get(moldura)
    if not o:
        return ""
    e = o["estado"]
    for m in re.finditer(r"(?:^| )(\d+):", e):
        n = int(m.group(1))
        nm = e[m.end():m.end() + n]
        if _NOME_SEGUIDO.match(e, m.end() + n) and len(nm.encode("latin1")) == n:
            return nm
    return ""


def faixas(texto: str) -> list[dict]:
    """As faixas do plano, de CIMA para baixo (a linha 0 é a de cima; a mídia é a última): `{id, moldura, linha, nome,
    ciclo, midia}`."""
    objs = objetos(texto)
    tl = _TL.search(texto)
    if not tl:
        return []
    out = []
    for f in (int(x) for x in tl.group(4).split()):
        o = objs.get(f)
        if not o or o["tipo"] != "GM_Strip":
            continue
        a, b, lin = _faixa(o)
        nm = nome(objs, o["filhos"][0])
        out.append({"id": f, "moldura": o["filhos"][0], "linha": lin, "nome": nm, "ciclo": nm.startswith(TAG)})
    out.sort(key=lambda x: x["linha"])
    for x in out:
        x["midia"] = x is out[-1]
    return out


# ── a marca do Ciclo ─────────────────────────────────────────────────────────────────────────────────────────────────
def _renomear(objs: dict, texto: str, moldura: int) -> tuple[str, int]:
    """O texto com o nome da camada `moldura` prefixado por `TAG` (o prefixo de comprimento refeito)."""
    o = objs[moldura]
    nm = nome(objs, moldura)
    if not nm or nm.startswith(TAG):
        return texto, 0
    velho = f"{len(nm.encode('latin1'))}:{nm} "
    novo = f"{len((TAG + nm).encode('latin1'))}:{TAG}{nm} "
    corpo = texto[o["ini"]:o["fim"]]
    i = corpo.find(velho)
    corpo = corpo[:i] + novo + corpo[i + len(velho):]
    return texto[:o["ini"]] + corpo + texto[o["fim"]:], len(novo) - len(velho)


def marcar(texto: str) -> str:
    """Todas as faixas do texto (menos a da mídia) com o nome do Ciclo. ⛔ Só para texto em que TODA camada é do Ciclo
    (o molde, o BLG que os efeitos/máscaras montam) — nunca para a pilha de um plano que já tem as do colorista."""
    for fx in faixas(texto):
        if fx["midia"] or fx["ciclo"]:
            continue
        texto, _ = _renomear(objetos(texto), texto, fx["moldura"])
    return texto


def tem_tracker_do_colorista(texto: str) -> bool:
    """Um `GR_TrackerRop` numa faixa que NÃO é do Ciclo (o do colorista: o estabilizador do Ciclo não se reescreve)."""
    objs = objetos(texto)
    for fx in faixas(texto):
        if fx["ciclo"]:
            continue
        if any(objs[i]["tipo"] == "GR_TrackerRop" for i in _descendentes(objs, fx["moldura"], [])):
            return True
    return False


# ── as faixas do colorista ──────────────────────────────────────────────────────────────────────────────────────────
def separar(lista: list[dict]) -> list[dict]:
    """De uma pilha (de cima para baixo, a mídia por último): as faixas do COLORISTA com `onde` — "cima" (acima de TODAS
    as do Ciclo, numa pilha que tem alguma) ou "baixo" (o resto: logo acima da imagem) — e o `aviso` da que estava ENTRE
    camadas do Ciclo."""
    camadas = [x for x in lista if not x.get("midia")]
    do_ciclo = [k for k, x in enumerate(camadas) if x["ciclo"]]
    out = []
    for k, x in enumerate(camadas):
        if x["ciclo"]:
            continue
        if do_ciclo and k < do_ciclo[0]:
            out.append({**x, "onde": "cima", "aviso": ""})
        elif do_ciclo and k < do_ciclo[-1]:
            out.append({**x, "onde": "baixo", "aviso": f"a camada “{x['nome']}” do colorista estava ENTRE camadas do "
                                                       "Ciclo (efeito/máscara da montagem): foi para logo acima da "
                                                       "imagem — o colorista confere"})
        else:
            out.append({**x, "onde": "baixo", "aviso": ""})
    return out


def _bytes(s: str) -> str:
    """Texto do SQLite (UTF-8) → a visão de BYTES do BLG (latin1): o prefixo `s11:(1024×540)` conta bytes."""
    return s.encode("utf-8").decode("latin1")


def _escapar(estado: str) -> str:
    """O estado do `.blscene` (texto puro) no formato do BLG (aspas e barras escapadas, a quebra de linha `\\n" "`)."""
    return estado.replace("\\", "\\\\").replace('"', '\\"').replace("\n", '\\n"\n"')


def _hx(v: str) -> float:
    return struct.unpack(">d", bytes.fromhex(v))[0]


def _deltas_salvos(con) -> set[int] | None:
    """Os deltas do estado SALVO da scene: o 1º de `Reference.DeltaIds` da "Main" e os pais dele. ⛔ MEDIDO (BL09 "V1
    dividida", 7.0.3, 2026-11-23): o `.blscene` leva também a mudança NÃO salva da interface (delta "Change to CDLGrade"
    depois do salvo; `Main` = {4,5,4,5}, o `@readable` = {4,4,4,4}) — a FLAPI só-leitura e o render veem o salvo."""
    try:
        ref = con.execute("select DeltaIds from Reference where Name='Main'").fetchone()
        pais = dict(con.execute("select Id, ParentDeltaId from Delta").fetchall())
    except Exception:                       # noqa: BLE001 — sem as tabelas (um .blscene de outro formato): tudo vale
        return None
    if not ref:
        return None
    try:
        d = int(ref[0].strip("{}").split(",")[0])
    except ValueError:
        return None
    out = set()
    while d and d not in out:
        out.add(d)
        d = pais.get(d)
    return out


def do_blscene(db: str, planos: list[dict], fps: float) -> list[dict]:
    """As faixas do COLORISTA de cada plano da scene exportada (`bl-export`): para cada `{rec: [a, b), arquivo}` (b
    exclusivo, em quadros), a lista de `{nome, onde, aviso, objetos: {id: obj}, raiz, desloc}` (objetos no formato de
    `objetos`; `desloc` = s a somar às chaves para valerem desde o início do PLANO — a faixa que começa antes dele).

    A faixa do plano: no bloco de linhas da trilha dele (1024 por trilha), a da MÍDIA com o mesmo tempo (e o mesmo
    arquivo no `GR_SequenceRop`, quando duas trilhas cortam juntas); as faixas do mesmo bloco que cobrem o plano são a
    pilha dele."""
    import os
    import sqlite3

    con = sqlite3.connect(db)
    q = """select o.Id, o.Revision, t.Data, o.Children, s.Data, o.DeltaId from Object o join State t on t.Id=o.TypeId
           join State s on s.Id=o.StateId order by o.DeltaId"""
    objs: dict[int, dict] = {}
    try:
        validos = _deltas_salvos(con)
        for oid, rev, tipo, filhos, estado, delta in con.execute(q):
            if validos is not None and delta not in validos:
                continue
            tp, _, sub = tipo.partition(" ")
            fl = [int(x) for x in filhos.strip("{}").split(",") if x != ""] if filhos else []
            objs[oid] = {"tipo": _bytes(tp), "sub": _bytes(sub), "rev": str(rev), "filhos": fl,
                         "estado": _escapar(_bytes(estado))}
    finally:
        con.close()
    # ⛔ MEDIDO (BL09 "V1 dividida", 2026-11-23): o `.blscene` guarda também as faixas que SAÍRAM da timeline (versões
    #    antigas da scene) — só valem as que o `GM_Timeline` (a versão final) lista
    vivas = {f for o in objs.values() if o["tipo"] == "GM_Timeline" for f in o["filhos"]}
    strips = []
    for i, o in objs.items():
        f = _faixa(o) if o["tipo"] == "GM_Strip" and o["filhos"] and i in vivas else None
        if f is None:
            continue
        try:
            a, b = _hx(f[0]), _hx(f[1])
        except ValueError:
            continue
        strips.append({"id": i, "a": a, "b": b, "linha": f[2], "bloco": f[2] // 1024, "moldura": o["filhos"][0]})

    def seq_de(moldura: int) -> str:
        for d in _descendentes(objs, moldura, []):
            if objs[d]["tipo"] == "GR_SequenceRop":
                return objs[d]["estado"]
        return ""

    tol = 0.25 / fps
    out = []
    for p in planos:
        a, b = p["rec"][0] / fps, p["rec"][1] / fps
        blocos = {}
        for s in strips:
            if abs(s["a"] - a) < tol and abs(s["b"] - b) < tol:
                blocos.setdefault(s["bloco"], []).append(s)
        cand = []
        for bl, ss in blocos.items():
            midia = max((s for s in strips if s["bloco"] == bl and s["a"] < b - tol and s["b"] > a + tol),
                        key=lambda s: s["linha"], default=None)
            if midia is None or not (abs(midia["a"] - a) < tol and abs(midia["b"] - b) < tol):
                continue
            cand.append((bl, midia))
        if len(cand) > 1 and p.get("arquivo"):
            base = _bytes(os.path.basename(p["arquivo"]))
            so = [c for c in cand if base and base in seq_de(c[1]["moldura"])]
            cand = so or cand
        if len(cand) != 1:
            out.append(None)
            continue
        bl, midia = cand[0]
        pilha = sorted((s for s in strips if s["bloco"] == bl and s["a"] < b - tol and s["b"] > a + tol
                        and s["linha"] < midia["linha"]), key=lambda s: s["linha"])
        lista = [{"id": s["id"], "moldura": s["moldura"], "linha": s["linha"], "nome": nome(objs, s["moldura"]),
                  "a": s["a"], "b": s["b"]} for s in pilha]
        for x in lista:
            x["ciclo"] = x["nome"].startswith(TAG)
        col = separar(lista + [{"midia": True}])
        for x in col:
            ids = _descendentes(objs, x["moldura"], [])
            x["objetos"] = {i: objs[i] for i in ids}
            x["raiz"] = x["moldura"]
            x["desloc"] = x["a"] - a
            if x["a"] > a + tol or x["b"] < b - tol:
                x["aviso"] = ((x["aviso"] + " — ") if x["aviso"] else "") + (
                    f"a camada “{x['nome']}” do colorista cobre só um TRECHO do plano: no BLG ela vai ao plano inteiro")
        out.append(col)
    return out


def do_blg(texto: str) -> list[dict]:
    """As faixas do colorista de um BLG lido (`get_blg_payload`) — o mesmo formato de `do_blscene`."""
    objs = objetos(texto)
    col = separar(faixas(texto))
    for x in col:
        x["objetos"] = {i: objs[i] for i in _descendentes(objs, x["moldura"], [])}
        x["raiz"] = x["moldura"]
        x["desloc"] = 0.0
    return col


# ── a pilha da v2: as do Ciclo + as do colorista ─────────────────────────────────────────────────────────────────────
def juntar(base: str, colorista: list[dict], deslocar=None, mais: float = 0.0) -> str:
    """O BLG `base` (a pilha da v2: a mídia e as faixas do Ciclo) com as faixas do `colorista` (`do_blscene`/`do_blg`):
    as "cima" no topo, as "baixo" logo acima da mídia, cada grupo na ordem em que estava. Ids novos; todas as faixas com
    a duração das da base. `deslocar(estado_de_um_GM_Bezier1dInterp, s)` move as chaves (cor animada) do `desloc` de
    cada faixa + `mais` (o plano da v2 começa noutra fonte: o Multi-Paste desloca, o BLG copiado não — BL09)."""
    if not colorista:
        return base
    objs = objetos(base)
    lista = faixas(base)
    if not lista:
        raise ValueError("o BLG da v2 não tem a pilha no formato medido (GM_Timeline)")
    dur = _faixa(objs[lista[0]["id"]])[1]
    prox = max(objs) + 1
    novos: list[str] = []
    cima, baixo = [], []
    recuo = re.search(r"\n([ \t]*)\(\d+\)=\"", base).group(1)
    for x in colorista:
        mapa = {}
        for i in x["objetos"]:
            mapa[i] = prox
            prox += 1
        for i, o in x["objetos"].items():
            est = o["estado"]
            d = (x.get("desloc") or 0.0) + mais
            if deslocar and o["tipo"] == "GM_Bezier1dInterp" and abs(d) > 1e-9:
                est = deslocar(est, d)
            novos.append(f'{recuo}({mapa[i]})="' + _corpo({**o, "estado": est},
                                                          [mapa.get(f, 0) if f else 0 for f in o["filhos"]]) + '"')
        sid = prox
        prox += 1
        (cima if x["onde"] == "cima" else baixo).append((sid, mapa[x["raiz"]]))
    ordem = [("novo", s) for s in cima] + [("velho", f) for f in lista if not f["midia"]] + \
            [("novo", s) for s in baixo] + [("velho", lista[-1])]
    texto = base
    # as faixas antigas: a linha nova (de baixo para cima no texto não importa: os corpos mudam de tamanho igual a cada
    # troca, então se relê o objeto a cada vez)
    for lin, (tipo, x) in enumerate(ordem):
        if tipo != "velho":
            continue
        o = objetos(texto)[x["id"]]
        a, b, _ = _faixa(o)
        corpo = _corpo({**o, "estado": _com_linha(o["estado"], a, b, lin)})
        texto = texto[:o["ini"]] + corpo + texto[o["fim"]:]
    a0 = _faixa(objetos(texto)[lista[0]["id"]])[0]
    faixas_novas = []
    for lin, (tipo, x) in enumerate(ordem):
        if tipo != "novo":
            continue
        sid, mold = x
        faixas_novas.append(sid)
        novos.append(f'{recuo}({sid})="8:GM_Strip 2:gm 1 1 {mold} 1 o 0 {a0} {dur} {lin} f f 0 "')
    tl = _TL.search(texto)
    filhos = [int(v) for v in tl.group(4).split()]
    velhas = [f["id"] for f in lista]
    i = max(filhos.index(f) for f in velhas)
    filhos2 = filhos[:i + 1] + faixas_novas + filhos[i + 1:]
    nf = len(velhas) + len(faixas_novas)
    resto = filhos2[nf:]
    est = f"0 0 {nf} {nf} 0 {nf} {nf + 1} {len(resto) - 2} " + " ".join(str(nf + 2 + k) for k in range(len(resto) - 2))
    texto = texto.replace(tl.group(0), f'({tl.group(1)})="11:GM_Timeline 2:gm {tl.group(2)} {len(filhos2)} '
                                       f'{" ".join(map(str, filhos2))} {est} "', 1)
    fim = texto.find(" ],", texto.find("blg_ObjectStrings"))
    antes = texto[:fim].rstrip("\n")
    if not antes.endswith(","):
        antes += ","
    return antes + "\n" + ",\n".join(novos) + "\n" + texto[fim:]


# ── a impressão da COR (só as faixas do colorista) ──────────────────────────────────────────────────────────────────
_OP = re.compile(r"^\d+:(GR_\w+Rop) ")
_DOUBLE = re.compile(r"\bf ([0-9a-f]{16})\b")
_BEZ = re.compile(r"^0 t [0-9a-f]{16} (\d+):(6 0 (\d+) .*)$", re.S)


def _ids_do_colorista(col: list[dict]) -> list[tuple[str, dict]]:
    out = []
    for x in col:
        for i in sorted(x["objetos"]):
            out.append((x["onde"], x["objetos"][i]))
    return out


def impressao(col: list[dict] | None) -> str:
    """A impressão digital da cor do COLORISTA (as faixas dele, na ordem, com os números de cada operador) — o que muda
    quando a cor muda e não muda com os efeitos do Ciclo (a v2 tem os dela) nem com ids/data. Sem faixa = ""."""
    if not col:
        return ""
    partes = []
    for x in col:                       # sem o `onde`: na v2 sem camada do Ciclo "cima" e "baixo" são o mesmo lugar
        linhas = []
        for i in _descendentes(x["objetos"], x["raiz"], []):
            o = x["objetos"][i]
            if o["tipo"].startswith("GR_") and o["tipo"].endswith("Rop") and o["tipo"] != "GR_InsideOutsideRop":
                linhas.append(o["tipo"] + ":" + ",".join(_num(x) for x in _DOUBLE.findall(o["estado"])))
        partes.append(";".join(linhas))
    return "|".join(partes)


def keyframes(col: list[dict] | None) -> list[list[float]]:
    """Os tempos (s, desde o início do PLANO) das curvas animadas das faixas do colorista, na ordem."""
    out = []
    for x in col or []:
        for i in _descendentes(x["objetos"], x["raiz"], []):
            o = x["objetos"][i]
            if o["tipo"] != "GM_Bezier1dInterp":
                continue
            m = re.match(r"0 t [0-9a-f]{16} \d+:6 0 (\d+) (.*)", o["estado"], re.S)
            if not m or int(m.group(1)) == 0:
                continue
            tok = m.group(2).split(" ")
            out.append([float(tok[6 * j]) + (x.get("desloc") or 0.0) for j in range(int(m.group(1)))])
    return out


def deslocar_chaves(estado: str, segundos: float) -> str:
    """O estado de um `GM_Bezier1dInterp` com as chaves deslocadas de `segundos` (o comprimento `<n>:` refeito; ele
    conta o corpo menos um — os dois espaços do fim contam um, medido no BL09). Curva parada: igual."""
    m = re.match(r"(0 t [0-9a-f]{16} )(\d+):(6 0 (\d+) .*)$", estado, re.S)
    if not m or int(m.group(4)) == 0 or abs(segundos) < 1e-12:
        return estado
    corpo = m.group(3)
    folga = len(corpo) - int(m.group(2))
    tok = corpo.split(" ")
    for j in range(int(m.group(4))):
        k = 3 + 6 * j
        tok[k] = "%.20g" % (float(tok[k]) + segundos)
    novo = " ".join(tok)
    return f"{m.group(1)}{len(novo) - folga}:{novo}"


#: o que está em TODO plano (a mídia e a moldura): o conteúdo deles é do arquivo, não do efeito (o BLG montado do molde
#: leva a mídia do molde e o Baselight mantém a do plano — medido no BL09)
_DO_ARQUIVO = {"GR_InsideOutsideRop", "GR_PluginInputRop", "GR_SequenceRop", "GR_AudioSequenceRop",
               "GR_ImageTransformParamsRop"}


def _num(hexa: str) -> str:
    """O double em hexadecimal como número (−0 = 0: o Baselight relê o −0,0 do Transform como 0 — PRODC, 2026-11-23)."""
    return "%.9g" % (_hx(hexa) + 0.0)


def _numeros_da_curva(estado: str) -> str:
    m = re.match(r"0 ([ft]) ([0-9a-f]{16}) \d+:6 0 (\d+) (.*)", estado, re.S)
    if not m:
        return ""
    if m.group(1) == "f" or int(m.group(3)) == 0:
        return _num(m.group(2))
    tok = m.group(4).split(" ")
    return ",".join("%.6f/%.6f" % (float(tok[6 * j]), float(tok[6 * j + 1])) for j in range(int(m.group(3))))


def impressao_do_ciclo(texto: str) -> str:
    """A impressão das faixas do CICLO e da faixa da MÍDIA (o Retime, a curva de tempo, o Transform, a composição), com
    os números das curvas (6 casas: o Baselight reescreve o texto dos números). O que é do arquivo fica de fora."""
    objs = objetos(texto)
    partes = []
    for fx in faixas(texto):
        if not (fx["ciclo"] or fx["midia"]):
            continue
        linhas = [fx["nome"] if fx["ciclo"] else "midia"]
        for i in _descendentes(objs, fx["moldura"], []):
            o = objs[i]
            if o["tipo"] == "GM_Bezier1dInterp":
                linhas.append(_numeros_da_curva(o["estado"]))
            elif o["tipo"].startswith("GR_") and o["tipo"].endswith("Rop") and o["tipo"] not in _DO_ARQUIVO:
                linhas.append(o["tipo"] + ":" + ",".join(_num(x) for x in _DOUBLE.findall(o["estado"])))
        partes.append(";".join(linhas))
    return "|".join(partes)
