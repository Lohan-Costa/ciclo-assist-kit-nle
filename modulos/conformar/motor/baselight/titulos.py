"""TRAZER os títulos da montagem para a scene (a OPÇÃO do autor, 2026-11-23: "em geral o texto não é enviado, mas caso
seja um elemento narrativo ou artístico, ele pode ser necessário"). Veio do estudo PRODUCAO-C
(`estudo/ferramentas/titulos_PRODC.py`, rodadas 25–28: 132 de 133 com os títulos); banco `plugins/baselight/README.md`.

Medido (7.0.3 Mac): a API só cria o texto como FONTE (sobre preto, ou matte: as letras não aparecem); DENTRO de uma
camada de grade (operador Text) ele é COMPOSITE e desenha sobre a imagem. A API não cria essa camada ⇒
  1. `titulos_flapi.py inserir`: uma faixa de texto por título (marcada `CICLO_TITULO_<i>`) + um preto onde não há vídeo
     embaixo (buraco sob camada sai XADREZ);
  2. `bl-export` da scene (um SQLite);
  3. `montar`: cada faixa de texto passa a ter a camada-modelo (`moldes/titulo.json`) com o texto, a fonte, o corpo, a cor,
     o alinhamento e a posição, no tempo do título e na linha 0 (por cima de tudo); os pretos na linha da V1;
  4. `bl-import` como a scene da ENTREGA; a provisória é apagada (autor: "a provisória pode ser apagada").
⛔ Armadilhas pagas no estudo: objeto novo no delta antigo = "Database corrupt" (⇒ um DELTA NOVO, o ramo Main aponta para
ele); `Revision` é a versão do FORMATO do objeto, não um contador; duas faixas na mesma linha e no mesmo tempo DERRUBAM o
flapid (o Blank que o conform do MC deixa no tempo do título sobe uma linha); a linha da V1 depende do nº de trilhas; a
string do `.blscene` conta BYTES UTF-8 (não a visão latin1 do BLG).
⚠️ Limites: a fonte tem de estar nesta máquina (a do Creative Cloud pelo caminho dela; sem ela, a Liberation do
Baselight, e o marker diz); o espaçamento entre letras (tracking) do Premiere não existe no Text do Baselight.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import struct

MOLDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moldes", "titulo.json")
M_TEXTO, M_COR, M_ALINHA, M_FONTE, M_BLOCO, M_MODO, M_X, M_Y = 547, 548, 549, 551, 554, 555, 534, 535
#: calibração contra a referência (estudo): tamanho do Baselight por px de corpo; o centro abaixo do topo
K_TAMANHO, K_Y = 0.71, 0.53
PASTAS_FONTE = [os.path.expanduser("~/Library/Application Support/Adobe/CoreSync/plugins/livetype/.r"),
                os.path.expanduser("~/Library/Fonts"), "/Library/Fonts", "/System/Library/Fonts/Supplemental",
                "/System/Library/Fonts"]
SEM_FONTE = "LiberationSans-Regular"


# ── a fonte ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _nome_ps(caminho: str) -> str | None:
    """O nome PostScript (name ID 6) de um .otf/.ttf, lido da tabela `name`."""
    b = open(caminho, "rb").read()
    for i in range(struct.unpack(">H", b[4:6])[0]):
        tag, _cs, off, _ln = struct.unpack(">4sIII", b[12 + 16 * i:28 + 16 * i])
        if tag == b"name":
            cnt, so = struct.unpack(">HH", b[off + 2:off + 6])
            for j in range(cnt):
                pid, _e, _l, nid, ln, o = struct.unpack(">HHHHHH", b[off + 6 + 12 * j:off + 18 + 12 * j])
                if nid == 6:
                    s = b[off + so + o:off + so + o + ln]
                    return s.decode("utf-16-be", "replace") if pid in (0, 3) else s.decode("latin1")
    return None


def _candidatos(familia: str, estilo: str) -> list[str]:
    f = familia.replace(" ", "")
    e = (estilo or "Regular").replace(" ", "")
    abrev = f.replace("ExtraCondensed", "ExtraCond").replace("Condensed", "Cond")
    return [f"{abrev}-{e}", f"{f}-{e}", f + ("MT" if e == "Regular" else ""), f]


def arquivo_da_fonte(familia: str, estilo: str, pastas: list[str] | None = None) -> str | None:
    """O CAMINHO do arquivo da fonte (o Baselight aceita o caminho no campo da fonte). ⛔ A do Creative Cloud não se
    copia (termos da Adobe): aponta-se para onde ela está."""
    alvo = _candidatos(familia, estilo)
    achados: dict[str, str] = {}
    for pasta in pastas or PASTAS_FONTE:
        if not os.path.isdir(pasta):
            continue
        for f in os.listdir(pasta):
            if f.lower().endswith((".otf", ".ttf")):
                try:
                    ps = _nome_ps(os.path.join(pasta, f))
                except (OSError, struct.error):
                    continue
                if ps in alvo:
                    achados.setdefault(ps, os.path.join(pasta, f))
    return next((achados[a] for a in alvo if a in achados), None)


# ── o que vai ───────────────────────────────────────────────────────────────────────────────────────────────────────
def detalhar(tits: list[dict], leitura: dict) -> list[dict]:
    """Os títulos de `efeitos.titulos` com o estilo da 1ª caixa (cor, alinhamento, posição, corpo em fração da altura) e
    o arquivo da fonte."""
    por_ini = {}
    from .entrega import _rate, _tc_quadros
    base, _ = _rate(float(leitura["timeline_fps"]))
    df = bool(leitura.get("timeline_drop_frame"))
    for seg in leitura["segments"]:
        t = next(((e.get("params") or {}).get("titulo") for e in seg.get("effects") or []
                  if (e.get("params") or {}).get("titulo")), None)
        if t and not seg.get("disabled"):
            por_ini[(_tc_quadros(seg["timeline_tc_in"], base, df), int(seg.get("track") or 1))] = t["caixas"][0]
    out = []
    for t in tits:
        cx = por_ini[(t["inicio"], t["trilha"])]
        f = cx.get("fonte") or {}
        out.append({**t, "a": t["inicio"], "b": t["fim"], "corpo_h": float(cx.get("corpo") or 0.05),
                    "cor": cx.get("cor") or [1, 1, 1], "alinhamento": cx.get("alinhamento") or "centro",
                    "pos": cx.get("posicao_resolve") or [0.5, 0.5],
                    "arquivo_fonte": arquivo_da_fonte(f.get("familia") or "", f.get("estilo") or "Regular")})
    return out


def pretos(tits: list[dict], ocupado) -> list[list[int]]:
    """Os trechos dos títulos SEM vídeo embaixo (`ocupado(q)`): um preto em cada (o buraco sob a camada sai xadrez)."""
    livres = sorted({q for t in tits for q in range(t["a"], t["b"]) if not ocupado(q)})
    out: list[list[int]] = []
    for q in livres:
        if out and out[-1][1] == q:
            out[-1][1] = q + 1
        else:
            out.append([q, q + 1])
    return out


# ── a scene exportada ───────────────────────────────────────────────────────────────────────────────────────────────
def _hx(v: float) -> str:
    return "%016x" % struct.unpack(">Q", struct.pack(">d", v))[0]


def _fh(v: float) -> str:
    return re.sub(r"\.0+p", "p", float(v).hex()).replace("0x1.0p", "0x1p")


def _s(texto: str) -> str:
    return f"s{len(texto.encode('utf-8'))}:" + texto


def _constante(est: str, v: float) -> str:
    corpo = f"6 0 0 0 0 -1 0.001 {('%.17g' % v)} "
    return re.sub(r"^0 f [0-9a-f]{16} \d+:6 0 0 0 0 -1 0\.001 \S+ ", f"0 f {_hx(v)} {len(corpo)}:{corpo}", est, count=1)


def _objetos(con) -> dict:
    q = """select o.Id, o.DeltaId, o.Revision, t.Data, o.Children, s.Data, o.rowid from Object o
           join State t on t.Id=o.TypeId join State s on s.Id=o.StateId order by o.DeltaId"""
    out = {}
    for oid, d, rev, tipo, ch, est, rid in con.execute(q):
        out[oid] = dict(delta=d, rev=rev, tipo=tipo, filhos=[int(x) for x in (ch or "{}").strip("{}").split(",") if x],
                        est=est, rowid=rid)
    return out


def _estado(con, dado: str) -> int:
    sid = con.execute("select max(Id) from State").fetchone()[0] + 1
    con.execute("insert into State(Id, Data, DataHash) values (?, ?, 0)", (sid, dado))
    return sid


def _tipo(con, tipo: str) -> int:
    r = con.execute("select Id from State where Data=? limit 1", (tipo,)).fetchone()
    return r[0] if r else _estado(con, tipo)


def _revisao(con, oid: int, v: dict, filhos: str | None, est: str, nd: int) -> None:
    tipo, ch = con.execute("select TypeId, Children from Object where rowid=?", (v["rowid"],)).fetchone()
    con.execute("insert into Object(Id, DeltaId, Revision, TypeId, Children, StateId) values (?,?,?,?,?,?)",
                (oid, nd, v["rev"], tipo, filhos if filhos is not None else ch, _estado(con, est)))


def _tempo(est: str, fps: float) -> tuple[int, int, int]:
    tk = est.split()
    f = lambda h: struct.unpack(">d", bytes.fromhex(h))[0] * fps  # noqa: E731
    return round(f(tk[3])), round(f(tk[4])), int(tk[5])


def _livre(faixas: dict, linha: int, a: int, b: int, fps: float, fora=()) -> bool:
    return not any(k not in fora and ln == linha and x < b and a < y
                   for k, v in faixas.items() for (x, y, ln) in [_tempo(v["est"], fps)])


class TituloNaoCabe(RuntimeError):
    """A linha do título está ocupada: gravar derrubaria o flapid (duas faixas na mesma linha e no mesmo tempo)."""


def _linha_do_titulo(con, O: dict, faixas: dict, t: dict, nd: int, fps: float) -> int:
    for k, v in faixas.items():
        x, y, ln = _tempo(v["est"], fps)
        if (x, y) == (t["a"], t["b"]) and any(O[f]["tipo"].startswith("GR_Blank") for f in v["filhos"] if f in O):
            if not _livre(faixas, ln + 1, x, y, fps, fora={k}):
                raise TituloNaoCabe(f"a linha {ln + 1} não está livre em {x}–{y}")
            tk = v["est"].split()
            tk[5] = str(ln + 1)
            _revisao(con, k, v, None, " ".join(tk) + " ", nd)
            v["est"] = " ".join(tk) + " "
            return ln
    if not _livre(faixas, 0, t["a"], t["b"], fps):
        raise TituloNaoCabe(f"a linha 0 está ocupada em {t['a']}–{t['b']}")
    return 0


def montar(db: str, nova: str, tits: list[dict], prs: list[list[int]], fps: float, w: int, h: int) -> dict:
    """Edita o `.blscene` exportado (com as faixas `CICLO_TITULO_<i>` e os pretos já inseridos) num DELTA NOVO: cada
    texto vira a camada-modelo; a scene passa a se chamar `nova`. Devolve {titulos, pretos}."""
    md = json.load(open(MOLDE, encoding="utf-8"))
    M = {int(k): v for k, v in md["objetos"].items()}
    arvore = list(md["ordem"])
    con = sqlite3.connect(db)
    try:
        O = _objetos(con)
        con.execute("update Directory set Name=? where IsFolder=0", (nova,))
        delta = max(v["delta"] for v in O.values())
        ult = con.execute("select * from Delta where Id=?", (delta,)).fetchone()
        nd = delta + 1
        con.execute("insert into Delta(Id, ParentDeltaId, NameId, SelPreId, SelPostId, WhoId, BuildId, CreationTime, "
                    "Flags, CheckHash) values (?,?,?,?,?,?,?,?,?,NULL)",
                    (nd, delta, _estado(con, "titulos (Ciclo Assist)"), ult[3], ult[4], ult[5], ult[6], ult[7] + 1, 0))
        con.execute("update Reference set DeltaIds=? where Name='Main'", ("{" + ",".join([str(nd)] * 4) + "}",))
        prox = max(O) + 1
        faixas = {i: v for i, v in O.items() if v["tipo"].startswith("GM_Strip")}
        feitos = 0
        for i, t in enumerate(tits):
            marca = _s(f"CICLO_TITULO_{i}")
            txt = next(k for k, v in O.items() if v["tipo"].startswith("GM_InterpDiscrete") and v["est"].strip().endswith(marca))
            rop = next(k for k, v in O.items() if txt in v["filhos"] and v["tipo"].startswith("GRMT_BlockInterp"))
            mrop = next(k for k, v in O.items() if v["tipo"].startswith("GR_MatteText3Rop") and rop in v["filhos"])
            fx = next(k for k, v in faixas.items() if mrop in v["filhos"])
            mapa = {m: prox + j for j, m in enumerate(arvore)}
            prox += len(arvore)
            corpo_px = t["corpo_h"] * h
            cx = w / 2 if t["alinhamento"] == "centro" else t["pos"][0] * w
            cy = h * (1 - t["pos"][1]) + K_Y * corpo_px
            edita = {
                M_TEXTO: lambda e, t=t: re.sub(r"s\d+:.*$", _s(t["texto"]) + " ", e.rstrip()),
                M_COR: lambda e, t=t: "0 f 0 a3 " + " ".join("f" + _fh(c) for c in t["cor"]) + " ",
                M_ALINHA: lambda e, t=t: "0 f 0 i1 " if t["alinhamento"] == "centro" else e,
                M_FONTE: lambda e, t=t: "0 f 0 " + _s(t["arquivo_fonte"] or SEM_FONTE) + " ",
                M_X: lambda e, cx=cx: _constante(e, (cx - w / 2) / w),
                M_Y: lambda e, cy=cy: _constante(e, (cy - h / 2) / w),
                M_MODO: lambda e: "0 f 0 i1 ",
            }
            for m in arvore:
                v = M[m]
                est = edita[m](v["est"]) if m in edita else v["est"]
                if m == M_BLOCO:
                    est = re.sub(r"(o 7 )[0-9a-f]{16}", lambda g, tam=corpo_px * K_TAMANHO: g.group(1) + _hx(tam), est,
                                 count=1)
                filhos = "{" + ",".join(str(mapa.get(f, 0)) for f in v["filhos"]) + "}"
                con.execute("insert into Object(Id, DeltaId, Revision, TypeId, Children, StateId) values (?,?,?,?,?,?)",
                            (mapa[m], nd, v["rev"], _tipo(con, v["tipo"]), filhos, _estado(con, est)))
            linha = _linha_do_titulo(con, O, faixas, t, nd, fps)
            tk = faixas[fx]["est"].split()
            tk[3], tk[4], tk[5] = _hx(t["a"] / fps), _hx(t["b"] / fps), str(linha)
            _revisao(con, fx, faixas[fx], "{" + str(mapa[md["raiz"]]) + "}", " ".join(tk) + " ", nd)
            feitos += 1
        brancos = [k for k, v in faixas.items() if v["delta"] == delta
                   and any(O[f]["tipo"].startswith("GR_Blank") for f in v["filhos"] if f in O)]
        nossas = set(brancos) | {k for k, v in faixas.items()
                                 if any(O[f]["tipo"].startswith("GR_MatteText3Rop") for f in v["filhos"] if f in O)}
        # a linha da V1 = o bloco MAIS ALTO entre as faixas do conform (1024 por trilha)
        v1 = max(int(v["est"].split()[5]) for k, v in faixas.items() if k not in nossas) // 1024 * 1024
        movidos = 0
        for (a, b), k in zip(prs, sorted(brancos)):
            if not _livre(faixas, v1, a, b, fps, fora={k}):
                continue
            tk = faixas[k]["est"].split()
            tk[3], tk[4], tk[5] = _hx(a / fps), _hx(b / fps), str(v1)
            _revisao(con, k, faixas[k], None, " ".join(tk) + " ", nd)
            movidos += 1
        con.commit()
    finally:
        con.close()
    return {"titulos": feitos, "pretos": movidos}


def marcas(tits: list[dict]) -> list[tuple[int, str]]:
    """O marker do título TRAZIDO: o que é e a fonte (achada ou não)."""
    out = []
    for t in tits:
        f = (f"fonte {t['fonte']}" + ("" if t["arquivo_fonte"] else " NÃO instalada nesta máquina — saiu na Liberation Sans")
             if t["fonte"] else "")
        out.append((t["a"], f"título da montagem trazido (camada Text): «{t['texto']}»" + (f" · {f}" if f else "")
                    + " · o espaçamento entre letras do Premiere não existe no Text do Baselight"))
    return out
