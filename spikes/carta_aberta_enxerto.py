"""Spike — levar sequências NOSSAS (multicâmera, merged) a um projeto do Premiere SEM duplicar a mídia do editor.

    python spikes/carta_aberta_enxerto.py <projeto do editor, salvo .prproj> <o nosso .prproj> <saída .prproj>

⛔ MEDIDO (2026-11-12, Premiere 26.0.2 Mac): `importFiles([prproj])` e `importSequences(prproj, ids)` de um arquivo NOSSO
duplicam a mídia — e duplicam mesmo com os UIDs de `Media`, `MasterClip` e `ClipProjectItem` iguais aos do editor.
✅ Importando de uma CÓPIA DO PROJETO DO EDITOR a sequência usa o item que ele já tem (banco, `api-extendscript.md`,
De Lá Pra Cá). ⇒ O enxerto: parte da cópia do projeto do editor e ACRESCENTA os nossos objetos, com toda referência à
nossa mídia crua trocada pelos objetos DELE (MasterClip, VideoMediaSource, AudioMediaSource, Markers), casados pelo
NOME do arquivo. Os nossos objetos de mídia crua ficam de fora; os internos do merged (a cópia própria da câmera) ficam.

- ObjectID (numérico, local ao arquivo) dos nossos é renumerado acima do maior do editor; ObjectUID não muda.
- ⚠️ O som direto: o nosso escritor faz uma fonte POR CANAL (§7.1 do banco `prproj/escrita.md`), o projeto do editor
  tem UMA fonte com os N canais — as duas fontes nossas vão para a dele. ⬜ conferir os canais (A1 = L, A2 = R).
- A bin nossa (com a multicâmera e o merged) entra na raiz da cópia; quem importa é `importSequences(saída, [uids])`.
"""

from __future__ import annotations

import gzip
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

INFRA = {"Project", "ProjectSettings", "RootProjectItem"}


def _ler(p: str) -> ET.Element:
    t = gzip.open(p, "rt", encoding="utf-8").read() if p.endswith(".prproj") else open(p, encoding="utf-8").read()
    return ET.fromstring(t)


def _refs(el):
    for e in el.iter():
        for a in ("ObjectRef", "ObjectURef"):
            if e.get(a):
                yield e, a, e.get(a)


def _idx(r):
    por = {}
    for e in r:
        k = e.get("ObjectID") or e.get("ObjectUID")
        if k:
            por[k] = e
    return por


def _arquivo(media: ET.Element) -> str:
    return (media.findtext("ActualMediaFilePath") or media.findtext("FilePath") or "").split("/")[-1].lower()


def _mapa_de_midia(r, por) -> dict[str, dict]:
    """Por arquivo: o MasterClip de BIN (o que um ClipProjectItem aponta), as fontes de vídeo/áudio e os Markers dele."""
    out: dict[str, dict] = {}
    for cpi in r.iter("ClipProjectItem"):
        if not cpi.get("ObjectUID"):
            continue
        mc_ref = cpi.find(".//MasterClip")
        mc = por.get(mc_ref.get("ObjectURef")) if mc_ref is not None else None
        if mc is None:
            continue
        info = {"mc": mc.get("ObjectUID"), "cpi": cpi.get("ObjectUID"), "vms": [], "ams": [], "markers": []}
        arq = None
        for c in mc.iter("Clip"):
            clip = por.get(c.get("ObjectRef") or "")
            if clip is None:
                continue
            src = clip.find(".//Source")
            fonte = por.get(src.get("ObjectRef")) if src is not None else None
            if fonte is None or fonte.tag not in ("VideoMediaSource", "AudioMediaSource"):
                continue
            med = fonte.find(".//Media")
            if med is not None and por.get(med.get("ObjectURef")) is not None:
                arq = _arquivo(por[med.get("ObjectURef")])
            info["vms" if fonte.tag == "VideoMediaSource" else "ams"].append(fonte.get("ObjectID"))
            for e, _a, v in _refs(clip):
                if por.get(v) is not None and por[v].tag == "Markers":
                    info["markers"].append(v)
        if arq:
            out.setdefault(arq, info)
    return out


def _fecho(por, raizes) -> set[str]:
    vistos, fila = set(), list(raizes)
    while fila:
        k = fila.pop()
        if k in vistos or k not in por:
            continue
        vistos.add(k)
        fila += [v for _e, _a, v in _refs(por[k])]
    return vistos


def enxertar(editor: str, nosso: str, saida: str) -> dict:
    E, N = _ler(editor), _ler(nosso)
    pe, pn = _idx(E), _idx(N)
    me, mn = _mapa_de_midia(E, pe), _mapa_de_midia(N, pn)
    troca: dict[str, str] = {}
    #: ⛔⛔ MEDIDO (WAV de canais distintos, 2026-11-12): o canal mora no `SecondaryContent` (`Content` + `ChannelIndex`).
    #:   O nosso escritor faz UMA fonte por canal (todas com `ChannelIndex 0`); o editor, UMA fonte com os N canais. Juntar
    #:   as nossas na dele SEM somar o índice pôs o canal ESQUERDO nas duas trilhas da multicâmera (A2 = L). ⇒ a fonte
    #:   nossa de ordem i que cai na fonte do editor de ordem j pede o canal (i − j) dela.
    canal_extra: dict[str, int] = {}
    faltam = []
    for arq, n in mn.items():
        e = me.get(arq)
        if not e:
            faltam.append(arq)
            continue
        troca[n["mc"]] = e["mc"]
        for k in ("vms", "ams", "markers"):
            for i, x in enumerate(n[k]):
                if e[k]:
                    j = min(i, len(e[k]) - 1)
                    troca[x] = e[k][j]
                    if k == "ams":
                        canal_extra[x] = i - j
    if faltam:
        raise SystemExit(f"⛔ o projeto do editor não tem: {faltam} — importe a mídia antes")
    # o que é NOSSO e não entra: a infraestrutura, a raiz, a mídia crua (os MasterClips de bin e o fecho deles)
    fora = set(_fecho(pn, [n["mc"] for n in mn.values()]) | {n["cpi"] for n in mn.values()})
    fora |= {k for k, e in pn.items() if e.tag in INFRA}
    fora |= {e.get("ObjectID") for e in N if e.get("ObjectID") and int(e.get("ObjectID")) < 50}
    maior = max(int(k) for k in (e.get("ObjectID") for e in E) if k)
    novo_oid = {}
    for e in N:
        k = e.get("ObjectID")
        if k and k not in fora:
            novo_oid[k] = str(int(k) + maior + 1)
    # ⛔ Só objetos COM identidade: o `<Project ObjectRef="1"/>` de topo do nosso arquivo é uma referência, não um
    #   objeto — entrando, a cópia teria dois "projetos", e o `importSequences` devolveu true sem trazer nada.
    entram = [e for e in N if (e.get("ObjectID") or e.get("ObjectUID")) and
              (e.get("ObjectID") or e.get("ObjectUID")) not in fora]
    # ⛔ A bin nossa perde as linhas da mídia crua que ficou de fora (a mídia é a do editor, na bin dele).
    for b in (e for e in entram if e.tag == "BinProjectItem"):
        itens_b = b.find(".//Items")
        if itens_b is not None:
            for it in list(itens_b):
                if it.get("ObjectURef") in fora:
                    itens_b.remove(it)
            for i, it in enumerate(itens_b):
                it.set("Index", str(i))
    pendentes = set()
    for e in entram:
        if e.tag == "SecondaryContent":
            c = e.find("Content")
            extra = canal_extra.get(c.get("ObjectRef")) if c is not None else None
            if extra:
                ci = e.find("ChannelIndex")
                ci.text = str(int(ci.text or 0) + extra)
        if e.get("ObjectID"):
            e.set("ObjectID", novo_oid[e.get("ObjectID")])
        for el, a, v in list(_refs(e)):
            if v in troca:
                el.set(a, troca[v])
            elif a == "ObjectRef" and v in novo_oid:
                el.set(a, novo_oid[v])
            elif v in fora:
                pendentes.add((pn[v].tag, v))
    # a bin nossa entra na raiz da cópia
    bins = [e for e in entram if e.tag == "BinProjectItem"]
    raiz = next(e for e in E if e.tag == "RootProjectItem")
    itens = raiz.find(".//Items")
    for b in bins:
        ET.SubElement(itens, "Item", {"Index": str(len(itens)), "ObjectURef": b.get("ObjectUID")})
    for e in entram:
        E.append(e)
    Path(saida).write_bytes(b"")
    with gzip.open(saida, "wt", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(E, encoding="unicode"))
    return {"trocas": len(troca), "nossos": len(entram), "fora": len(fora), "pendentes": sorted(pendentes)}


if __name__ == "__main__":
    print(enxertar(*sys.argv[1:4]))
