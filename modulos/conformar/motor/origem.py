"""origem.py — quem escreveu um arquivo de intercâmbio (AAF, xmeml, FCPXML, OTIO, EDL), e a marca do De Lá Pra Cá.

O Receber precisa disto antes de traduzir: o caminho Avid → Avid (relinkar a timeline que já está no MC) só vale para o
que saiu do Avid. Os nativos (AVB, PRPROJ, DRT/DRP) já dizem de onde vêm; estes, não.

Medido em 2026-10-12 (banco: `transversal/assinatura-de-origem.md`, um export de cada: MC 25.6/25.12, Premiere 23.2,
Resolve 19.0):

- AAF: `Header.IdentificationList` — a ÚLTIMA entrada é quem gravou por último, a primeira quem criou. Casa-se o
  `CompanyName`, que é estável (o MC põe a versão dentro do `ProductName`).
- xmeml: `authoringApp="PremierePro"` / `TL.SQ` / `MZ.` = Premiere (v4); v5 sem nada disso = Resolve.
- OTIO: o namespace `Resolve_OTIO` nos metadados = Resolve.
- ⚠️ o sufixo " (Resolve)" no nome da sequência é PISTA, não prova: o nome viaja de um NLE para o outro.
- Sem marca (EDL, ou quem não se identifica) = "desconhecida", nunca um palpite.

⛔ O pyaaf2 em `rw` NÃO acrescenta Identification ao salvar: o AAF tratado pelo app continuava dizendo "Avid Media
Composer". Decisão do autor (2026-10-12): o app acrescenta a dele (`marcar_aaf`), preservando a do Avid.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path

EMPRESA = "Ciclo Media"
PRODUTO = "De Lá Pra Cá"
#: o ProductID do De Lá Pra Cá no AAF — fixo (é o que identifica o produto entre versões)
PRODUTO_ID = "5d1a9c0e-2f4b-4c71-9a3e-de1a9ac0ca01"
#: a chave dos metadados que o app grava no OTIO (a mesma ideia do `Resolve_OTIO`)
CHAVE_OTIO = "DeLaPraCa"

_EMPRESAS = {"avid technology": "avid", "adobe": "premiere", "blackmagic": "resolve", "ciclo media": "dlpc"}


def versao_do_app() -> str:
    """A versão do build (arquivo `VERSION` da raiz; montado, ele viaja na raiz do pacote)."""
    raiz = (Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[1])
    try:
        return (raiz / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _nle_da_empresa(empresa: str) -> str | None:
    e = (empresa or "").lower()
    return next((v for k, v in _EMPRESAS.items() if k in e), None)


def _resultado(formato: str, nle: str | None, **extra) -> dict:
    return {"formato": formato, "nle": nle or "desconhecida", "versao": None, "plataforma": None,
            "tratado_pelo_dlpc": False, "cadeia": [], "pistas": [], **extra}


# ── AAF ─────────────────────────────────────────────────────────────────────────────────────────

def _identificacoes(f) -> list[dict]:
    out = []
    for i in f.header["IdentificationList"].value or []:
        d = {}
        for k in ("CompanyName", "ProductName", "ProductVersionString", "Platform"):
            try:
                if k in i and i[k].value is not None:
                    d[k] = str(i[k].value)
            except Exception:                   # noqa: BLE001 — propriedade ilegível não derruba a leitura
                pass
        try:
            v = i["ProductVersion"].value if "ProductVersion" in i else None
            if v:
                d["versao"] = ".".join(str(v.get(c, 0)) for c in ("major", "minor", "tertiary"))
        except Exception:                       # noqa: BLE001
            pass
        out.append(d)
    return out


def _de_aaf(caminho: str) -> dict:
    import aaf2
    with aaf2.open(caminho, "r") as f:
        cadeia = _identificacoes(f)
    nles = [_nle_da_empresa(c.get("CompanyName", "")) for c in cadeia]
    # quem fez o CONTEÚDO é o último que não é o próprio app: o DLPC só trata (relink, achatar, remapear)
    autor = next((i for i in range(len(nles) - 1, -1, -1) if nles[i] not in (None, "dlpc")), None)
    r = _resultado("aaf", nles[autor] if autor is not None else None, cadeia=cadeia,
                   tratado_pelo_dlpc="dlpc" in nles)
    if autor is not None:
        c = cadeia[autor]
        r["versao"] = c.get("ProductVersionString") if re.match(r"\d", c.get("ProductVersionString", "")) else (
            _versao_no_nome(c.get("ProductName", "")) or c.get("versao"))
        r["plataforma"] = c.get("Platform")
        r["pistas"].append(f"IdentificationList[{autor}]: {c.get('CompanyName')} / {c.get('ProductName')}")
    return r


def _versao_no_nome(nome: str) -> str | None:
    m = re.search(r"(\d+\.\d+(?:\.\d+)*)", nome or "")
    return m.group(1) if m else None


def marcar_aaf(f) -> bool:
    """Acrescenta a Identification do De Lá Pra Cá a um AAF aberto em `rw`, PRESERVANDO as que já existem (a do NLE
    que criou continua a primeira). Chamar uma vez por gravação. É acessório: falhou, registra e devolve False — o
    relink/achatamento já feito não morre por causa da marca."""
    try:
        _marcar(f)
        return True
    except Exception as e:                      # noqa: BLE001
        logging.getLogger(__name__).warning("AAF sem a marca do De Lá Pra Cá: %s", e)
        return False


def _marcar(f) -> None:
    agora = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)    # o Date dos três NLEs é UTC
    v = (versao_do_app().split(".") + ["0", "0", "0"])[:3]
    i = f.create.Identification()
    i["CompanyName"].value = EMPRESA
    i["ProductName"].value = PRODUTO
    i["ProductVersionString"].value = versao_do_app()
    try:
        i["ProductVersion"].value = {"major": int(v[0]), "minor": int(v[1]), "tertiary": int(v[2]),
                                     "patchLevel": 0, "type": "VersionReleased"}
    except (ValueError, KeyError):
        pass
    from aaf2.auid import AUID
    i["ProductID"].value = AUID(PRODUTO_ID)
    i["Date"].value = agora
    i["Platform"].value = f"pyaaf2 ({sys.platform})"
    i["GenerationAUID"].value = uuid.uuid4()
    f.header["IdentificationList"].append(i)
    try:
        f.header["LastModified"].value = agora
    except Exception:                           # noqa: BLE001 — o carimbo é acessório; a Identification já entrou
        pass


# ── texto: xmeml, FCPXML, EDL ───────────────────────────────────────────────────────────────────

def _de_xml(caminho: str, cabeca: str) -> dict:
    m = re.search(r"<(xmeml|fcpxml)\b[^>]*\bversion=\"([\d.]+)\"", cabeca)
    formato = m.group(1) if m else "xml"
    r = _resultado(formato, None, versao_formato=m.group(2) if m else None)
    try:
        with open(caminho, encoding="utf-8", errors="replace") as fh:
            texto = fh.read()
    except OSError:
        texto = cabeca
    if 'authoringApp="PremierePro"' in texto or re.search(r"\b(TL\.SQ|MZ\.)\w*=", texto):
        r["nle"] = "premiere"
        r["pistas"].append('atributos do Premiere (authoringApp="PremierePro" / TL.SQ / MZ.)')
    elif formato in ("xmeml", "fcpxml"):
        if re.search(r"<name>[^<]* \(Resolve\)</name>|name=\"[^\"]* \(Resolve\)\"", texto):
            r["pistas"].append('sufixo " (Resolve)" no nome (pista: o nome viaja)')
        if formato == "xmeml" and r["versao_formato"] == "5":
            r["nle"] = "resolve"
            r["pistas"].append("xmeml v5 sem atributos do Premiere")
        elif formato == "fcpxml" and r["pistas"]:
            r["nle"] = "resolve"
    return r


def _de_otio(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as fh:
        d = json.load(fh)
    meta = d.get("metadata") or {}
    r = _resultado("otio", None)
    if CHAVE_OTIO in meta:
        r["tratado_pelo_dlpc"] = True
        dl = meta[CHAVE_OTIO] if isinstance(meta[CHAVE_OTIO], dict) else {}
        r["cadeia"].append({"CompanyName": EMPRESA, "ProductName": PRODUTO, "versao": dl.get("versao")})
        origem = dl.get("origem")
        if origem:
            r["nle"] = origem
            r["pistas"].append(f"{CHAVE_OTIO}.origem")
    if "Resolve_OTIO" in meta and r["nle"] == "desconhecida":
        r["nle"] = "resolve"
        r["versao_formato"] = (meta["Resolve_OTIO"] or {}).get("Resolve OTIO Meta Version")
        r["pistas"].append("metadata.Resolve_OTIO")
    return r


def origem(caminho: str | os.PathLike) -> dict:
    """{formato, nle ('avid'|'premiere'|'resolve'|'desconhecida'), versao, plataforma, tratado_pelo_dlpc, cadeia,
    pistas} de um arquivo de intercâmbio. O FCPXML 1.10+ do Resolve é uma PASTA com `Info.fcpxml` dentro."""
    p = Path(caminho)
    if p.is_dir():
        info = p / "Info.fcpxml"
        if not info.is_file():
            return _resultado("pasta", None)
        p = info
    ext = p.suffix.lower()
    if ext == ".aaf":
        return _de_aaf(str(p))
    if ext == ".otio":
        return _de_otio(str(p))
    if ext == ".edl":
        return _resultado("edl", None)
    with open(p, "rb") as fh:
        cabeca = fh.read(4096).decode("utf-8", "replace")
    if ext in (".xml", ".fcpxml") or cabeca.lstrip("﻿").startswith("<?xml"):
        return _de_xml(str(p), cabeca)
    return _resultado(ext.lstrip(".") or "?", None)
