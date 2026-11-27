"""A TIMELINE do editor na Carta Aberta: a sequência do Avid vira um item `sequencia` com `timeline: true` (o desafio
da timeline real, autor 2026-11-13; plano `docs/plano/2026-11-11-carta-aberta.md`).

O mesmo tipo do nest do Premiere (`itens.py`), com o que a timeline do editor tem a mais:

    {"tipo": "sequencia", "timeline": true, "fps": "24000/1001", "tc_inicio_q": 86400, "duracao_q": N,
     "trilhas": [{"tipo": "V"|"A", "k": 1,
                  "clipes": [{"midia": id, "inicio_q", "entrada_q", "fim_q",          # record e fonte, em quadros
                              "canal": 2,                  # som: a trilha do MASTER que o clipe toca (A2)
                              "ganho_db": 4.0,             # o volume do clipe (PanVolumeEffect)
                              "desligado": true,           # o clipe desabilitado (Selector no ramo vazio)
                              "velocidade": {...},         # o MotionEffect, como o Avid o integrou
                              "enquadramento": "stretch",  # o reformat
                              "efeitos": [{nome, categoria, params, traduzivel, rotulo}],
                              "via": "11-01-03",           # (sem `subclipe`) o nome do clipe na timeline
                              "item": id, "entrada_no_item_q": 12}],   # veio do subclipe `item`, entrada no tempo DELE
                  "transicoes": [{"inicio_q", "fim_q", "corte_q", "efeito"}],
                  "sem_clipe": [{"inicio_q", "fim_q", "efeitos"}]}],               # título, matte sem mídia
     "avisos": ["…"]}

⭐ A leitura é a do Conformar (`modulos/conformar/motor/avb_bin/segmentos.py`), que já leu ESTA timeline em produção
(a `PRODA_CORTE.02.Exported.01`: transições, velocidade, Selector, ganho, títulos). Nada de segundo leitor.
⭐⭐ Guardar TUDO (autor, 2026-11-13): o efeito que nenhum NLE de destino traduz entra assim mesmo, com o que a bin diz
dele; quem decide o que dá para levar é a ENTREGA, e ela diz o que ficou de fora.
⭐ O clipe que vem de um SUBCLIPE guarda a camada: `subclipe` (o MobID) + `entrada_no_item_q`, e `itens.do_avid` o troca
por `item` (o `.item.json` oculto do subclipe). `midia`/`entrada_q` (o master) ficam junto: a entrega que não sabe o
item ainda acha a mídia. Medido na timeline ORIGINAL da PRODUCAO-A (`PRODA_CORTE.00.2`): 704 de 866 clipes vêm de 44
subclipes, 35 deles sincronizados (a `PRODA_CORTE.02.Exported.01` era exportada e tinha perdido isso).
"""

from __future__ import annotations

import json
import math
import sys
from fractions import Fraction
from pathlib import Path

#: o "level" do PanVolumeEffect: 2^29 = 0 dB (`modulos/conformar/motor/avb_export/translate.py`, UNITY_GAIN)
UNIDADE_DE_GANHO = 1 << 29


def _conformar():
    raiz = Path(__file__).resolve().parents[2] / "modulos" / "conformar" / "motor"
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from avb_bin import segmentos  # noqa: PLC0415
    return segmentos


def _taxa_texto(edit_rate) -> str:
    from ..avid.take import fracao_da_taxa
    f = fracao_da_taxa(float(edit_rate))
    return f"{f.numerator}/{f.denominator}" if f.denominator != 1 else str(f.numerator)


def _json(v):
    """Os parâmetros do Conformar como JSON puro (tuplas, objetos do pyavb viram texto)."""
    return json.loads(json.dumps(v, default=str))


def ganho_db(level) -> float | None:
    try:
        n = int(level)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return round(20 * math.log10(n / UNIDADE_DE_GANHO), 2)


def _o_marker(ref):
    """O `Marker` de uma referência do `_TMP_CRM` (pode já vir resolvido)."""
    return ref if type(ref).__name__ == "Marker" else getattr(ref, "value", None)


def marcadores(seq) -> list[dict]:
    """Os markers da TIMELINE `seq` (o mob da sequência, pyavb), em quadros do começo dela (a régua do `inicio_q`).

    Banco `protocolos/avb/estruturas.md` "Markers da TIMELINE na bin" (2026-11-15): moram nos SEGMENTOS, atributo
    `_TMP_CRM` → objetos `Marker` (`comp_offset` = quadros desde o início do segmento que o carrega), e MUITOS estão
    aninhados dentro de efeitos (`TrackEffect`/`PanVolumeEffect`/`AudioSuitePluginEffect` → a sequência de entrada):
    na PRODA_CORTE.00.2, 19 de 23. A posição = início do segmento de cima + a posição na sequência aninhada + offset."""
    out: list[dict] = []
    vistos: set[str] = set()

    def anotar(comp, pos: int, trilha: str) -> None:
        a = getattr(comp, "attributes", None)
        for ref in (a.get("_TMP_CRM") if a else None) or []:
            m = _o_marker(ref)
            if m is None:
                continue
            at = dict(getattr(m, "attributes", None) or {})
            ident = str(at.get("_ATN_CRM_ID") or "")
            if ident and ident in vistos:
                continue
            vistos.add(ident)
            out.append({"q": int(pos + int(getattr(m, "comp_offset", 0) or 0)), "trilha": trilha,
                        "comentario": str(at.get("_ATN_CRM_COM") or "").strip(),
                        "cor": str(at.get("_ATN_CRM_COLOR") or ""), "rgb": [int(x) for x in (m.color or [])],
                        "usuario": str(at.get("_ATN_CRM_USER") or ""),
                        "data": " ".join(x for x in (at.get("_ATN_CRM_DATE"), at.get("_ATN_CRM_TIME")) if x),
                        "duracao_q": int(at["_ATN_CRM_LENGTH"]) if str(at.get("_ATN_CRM_LENGTH") or "").isdigit() else 0,
                        "id": ident})

    def andar(comp, pos: int, trilha: str, fundo: int = 0) -> None:
        if comp is None or fundo > 10:
            return
        anotar(comp, pos, trilha)
        tipo = type(comp).__name__
        if tipo == "Sequence":
            p = pos
            for c in comp.components:
                andar(c, p, trilha, fundo + 1)
                p += -int(c.length) if type(c).__name__ == "Transition" else int(c.length)
            return
        for t in getattr(comp, "tracks", None) or []:   # a entrada de um efeito começa onde o efeito começa
            andar(getattr(t, "component", None), pos, trilha, fundo + 1)

    for t in seq.tracks:
        c = t.component
        kind = getattr(c, "media_kind", "")
        if kind not in ("picture", "sound"):
            continue
        andar(c, 0, ("V" if kind == "picture" else "A") + str(t.index))
    return sorted(out, key=lambda m: (m["q"], m["trilha"]))


def do_avid(f, seq, chave) -> tuple[dict, dict[str, dict]]:
    """(o item, {chave do master: o que a BIN diz dele}) da sequência `seq` da bin aberta `f`. `chave(mob_id)` = os 64
    hex do master. ⚠️ Tudo vira dado nosso aqui dentro: o pyavb é preguiçoso (banco `protocolos/avb/README.md`)."""
    S = _conformar()
    r = S.ler_timeline(f, seq)
    fps = float(r["timeline_fps"])
    q = lambda tc: S._tc(tc, fps)  # noqa: E731
    trilhas: dict[tuple[str, int], dict] = {}
    masters: dict[str, dict] = {}
    for mob_id, info in (r.get("masters") or {}).items():
        k = chave(mob_id)
        if k:
            masters[k] = _json(info)
    trilhas = trilhas_de_segmentos(r["segments"], q, lambda s: chave(s["mob_id"]), masters)
    avisos = [a["texto"] + (f" ({a['vezes']}×)" if a.get("vezes", 1) > 1 else "") for a in r.get("avisos") or []]
    item = {"tipo": "sequencia", "timeline": True, "fps": _taxa_texto(seq.edit_rate),
            "tc_inicio_q": int(r["timeline_start_frames"]), "drop_frame": bool(r.get("timeline_drop_frame")),
            "duracao_q": int(getattr(seq, "length", 0) or 0), "trilhas": trilhas}
    try:
        m = marcadores(seq)
    except Exception as e:  # noqa: BLE001 — marker que não se lê não derruba a timeline; é dito
        m, avisos = [], avisos + [f"os markers da timeline não foram lidos ({e})"]
    if m:
        item["marcadores"] = m
    if avisos:
        item["avisos"] = avisos
    return item, masters


def trilhas_de_segmentos(segments: list[dict], q, chave, masters: dict[str, dict] | None = None) -> list[dict]:
    """As trilhas do item `sequencia` a partir dos SEGMENTOS do leitor do Conformar (a bin pela Carta; a bin ou o AAF
    pelo Conformar — plano 2026-11-26, "um leitor, um escritor"). `q(tc)` = o quadro da timeline de um TC;
    `chave(segmento)` = o id da mídia do clipe (a referência da Carta), ou vazio."""
    masters = masters or {}
    trilhas: dict[tuple[str, int], dict] = {}
    for s in segments:
        n = int(s["track"])
        tipo, k = ("A", n - 999) if n >= 1000 else ("V", n)
        tr = trilhas.setdefault((tipo, k), {"tipo": tipo, "k": k, "clipes": [], "transicoes": [], "sem_clipe": []})
        a = q(s["timeline_tc_in"])
        if s.get("is_transition"):
            nome = (s.get("effects") or [{}])[0].get("name", "")
            tr["transicoes"].append({"inicio_q": a, "fim_q": a + int(s["duration_frames"]),
                                     "corte_q": a + int(s.get("cutpoint") or 0), "efeito": nome})
            continue
        if s.get("is_gap") and not s.get("disabled"):
            continue
        if s.get("is_effect") or not s.get("mob_id"):
            if s.get("effects") or s.get("is_effect"):
                tr["sem_clipe"].append({"inicio_q": a, "fim_q": a + int(s["duration_frames"]),
                                        "nome": s.get("clip_name"), "efeitos": _json(s.get("effects") or [])})
            continue
        c: dict = {"midia": chave(s), "inicio_q": a, "entrada_q": int(s["source_start_frames"]),
                   "fim_q": a + int(s["duration_frames"])}
        if s.get("is_audio"):
            c["canal"] = int(s.get("canal_arquivo") or s.get("source_slot_id") or 1)
        if s.get("subclipe_mob_id"):
            # ⭐ a CAMADA do subclipe (plano §4.6): qual, e a entrada no tempo DELE; `itens.do_avid` troca pelo item
            c["subclipe"] = str(s["subclipe_mob_id"])
            c["entrada_no_item_q"] = int(s.get("subclipe_inicio_frames") or 0)
            g = ganho_db(s.get("subclipe_ganho_level"))
            if g:                                  # o ganho de clipe DENTRO do subclipe (ex. +12 dB): toca junto no Avid
                c["ganho_no_item_db"] = g
        if s.get("disabled"):
            c["desligado"] = True
        if s.get("has_motion_effect"):
            c["velocidade"] = _json({"razao": s.get("speed_ratio"), "tipo": s.get("motion_effect_type"),
                                     "classe": s.get("motion_class"), "relativa": s.get("relative_speed"),
                                     "mapa": s.get("source_offset_map"), "curva": s.get("speed_curve"),
                                     "fase": s.get("phase_offset"), "retime": s.get("retime"),
                                     "conform": s.get("conform_ratio")})
            ts = next((e["params"]["time_shift"] for e in s.get("effects") or []
                       if isinstance(e.get("params"), dict) and e["params"].get("time_shift")), None)
            if ts and s.get("is_audio"):
                # ⭐ a velocidade do SOM veio do AudioSuite TIME SHIFT do MC (2026-11-26): Shift 100 % = o tom mantido —
                #   no Premiere, o "Maintain Audio Pitch" (`MaintainAudioPitch`) do clipe
                c["velocidade"]["time_shift"] = True
                c["velocidade"]["mantem_tom"] = abs(float(ts.get("tom") or 1.0) - 1.0) < 1e-6
        if s.get("has_reframe") and s.get("reframe_mode"):
            c["enquadramento"] = s["reframe_mode"]
        efeitos = []
        for e in s.get("effects") or []:
            if e.get("category") == "gain":
                g = ganho_db((e.get("params") or {}).get("level"))
                if g is not None:
                    c["ganho_db"] = g
            efeitos.append(_json({"nome": e.get("name"), "categoria": e.get("category"), "params": e.get("params"),
                                  "traduzivel": bool(e.get("reproducible")), "rotulo": e.get("label")}))
        if efeitos:
            c["efeitos"] = efeitos
        nome_master = (masters.get(c["midia"]) or {}).get("nome")
        if s.get("clip_name") and nome_master and s["clip_name"] != nome_master and not c.get("subclipe"):
            c["via"] = s["clip_name"]
        tr["clipes"].append(c)
    return [trilhas[k] for k in sorted(trilhas, key=lambda x: (x[0] != "V", x[1]))]


def midias_usadas(item: dict) -> list[str]:
    return list(dict.fromkeys(c["midia"] for t in item.get("trilhas", []) for c in t.get("clipes", []) if c.get("midia")))


def identidade_offline(info: dict) -> dict:
    """A identidade de um master SEM forma achada nesta máquina (o AMA de som, por exemplo), pelo que a BIN diz: o
    nome, o TC, a taxa e a duração. ⛔ Plano §4.7: mídia que não se acha entra OFFLINE, com o nome e o TC certos —
    nunca uma parecida no lugar."""
    ident = info.get("identidade") or {}
    out: dict = {"nome_da_fonte": ident.get("reel") or info.get("nome") or "",
                 "tipo": "video" if ident.get("largura") else "audio"}
    fps = ident.get("fps") or info.get("fps")
    if fps:
        from ..avid.take import fracao_da_taxa
        f = fracao_da_taxa(float(fps))
        out["fps"] = f"{f.numerator}/{f.denominator}" if f.denominator != 1 else str(f.numerator)
    if info.get("duracao_frames"):
        out["quadros"] = int(info["duracao_frames"])
        if fps:
            out["duracao_s"] = round(int(info["duracao_frames"]) / float(fps), 3)
    if ident.get("tc_inicio") is not None and ident.get("tc_fps"):
        from ..avid.timeline_do_editor import tc
        out["tc"] = tc(int(ident["tc_inicio"]), int(ident["tc_fps"]))
    return {k: v for k, v in out.items() if v not in (None, "")}


def referencias_offline(proj, chaves: list[str], masters: dict[str, dict]) -> dict[str, str]:
    """Cria (OCULTAS: entram porque a timeline as usa) as referências dos masters sem forma nesta máquina. Devolve
    {chave: nome}. Se o arquivo AMA que a bin aponta existir aqui, ele entra como a forma `original`."""
    from . import anexar, referencias, vitrine
    feitos = {}
    for k in chaves:
        info = masters.get(k)
        if not info:
            continue
        nome = info.get("nome") or k
        proj.ocultas.mkdir(parents=True, exist_ok=True)
        caminho, ref = referencias.criar(proj, proj.ocultas, nome, identidade_offline(info),
                                         {"nle": "avid", "forma": "avid", "master": k, "offline": True,
                                          "caminho_na_bin": info.get("caminho_na_bin") or ""})
        vitrine.esconder(proj, caminho, ref, referencias.SUFIXO)
        bruto = info.get("caminho_na_bin") or ""
        if bruto and Path(bruto).is_file():
            anexar._vincular(proj, ref["id"], "original", Path(bruto), "o caminho AMA da bin", anexar.Conta())
        feitos[k] = nome
    return feitos


def taxa(item: dict) -> Fraction:
    return Fraction(str(item.get("fps") or "25"))
