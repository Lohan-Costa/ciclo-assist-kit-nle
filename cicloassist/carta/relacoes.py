"""A RELAÇÃO entre as formas de uma mídia: "o original X ganhou a cópia Y, com a transformação Z" (plano
`docs/plano/2026-11-26-carta-registro-da-producao.md`, etapa 2; a ideia do autor, 2026-11-26).

Quem converte grava um MANIFESTO ao lado dos convertidos (`ciclo-conversao.json`) — sem precisar saber em que Carta eles
vão entrar. A Carta o lê sozinha quando a pasta dos convertidos é anexada (`anexar`) e registra, no diário, um fato
`relacao` por par. O mesmo formato serve para o JSON feito à mão (a conversão feita fora: o laboratório, o DIT).

    {"formato": "ciclo-conversao/1", "feito_por": "resolve_proxy", "quando": "…",
     "pares": [{"original":   {"arquivo": "/…/A001C003.mov", "impressao": "…", "tc": "…", "taxa": "24000/1001",
                               "quadros": 240, "largura": 3840, "altura": 2160, "canais": 2},
                "convertido": {"arquivo": "A001C003.mov",            # relativo à pasta do manifesto (ou absoluto)
                               "impressao": "…", …os mesmos campos…},
                "transformacao": {"tc_desloc_q": 0, "taxa": "igual" | {"de": "25", "para": "24000/1001"},
                                  "enquadramento": {"tipo": "escala" | "letterbox" | "pillarbox" | "corte",
                                                    "fator": 0.5, "area": [x, y, l, a] | null},
                                  "trecho": null | {"inicio_q": 10, "fim_q": 200},
                                  "canais": "iguais" | [[1, 1], [2, 2]]}}]}

⛔ O manifesto é DICA forte, não verdade cega (a regra da família: "o caminho é dica, a identidade é a verdade"): o par só
é registrado se o arquivo convertido existe e a impressão dele confere com a do manifesto (quando o manifesto a traz).
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from . import diario, referencias
from .projeto import Projeto

FORMATO = "ciclo-conversao/1"
ARQUIVO = "ciclo-conversao.json"


def _taxa_texto(t) -> str | None:
    return str(t) if t else None


def transformacao(original: dict, convertido: dict) -> dict:
    """A transformação de um par, pelas sondas dos dois (taxa, tamanho, TC, quadros, canais)."""
    from fractions import Fraction
    t: dict = {"tc_desloc_q": 0, "taxa": "igual", "enquadramento": None, "trecho": None, "canais": "iguais"}
    if (original.get("taxa") or None) != (convertido.get("taxa") or None):
        t["taxa"] = {"de": _taxa_texto(original.get("taxa")), "para": _taxa_texto(convertido.get("taxa"))}
    lo, ao, lc, ac = (original.get("largura"), original.get("altura"), convertido.get("largura"), convertido.get("altura"))
    if lo and ao and lc and ac and (lo, ao) != (lc, ac):
        po, pc = Fraction(int(lo), int(ao)), Fraction(int(lc), int(ac))
        tipo = "escala" if abs(float(po - pc)) < 0.01 else ("letterbox" if po > pc else "pillarbox")
        t["enquadramento"] = {"tipo": tipo, "fator": round(int(ac) / int(ao), 6) if tipo != "pillarbox"
                              else round(int(lc) / int(lo), 6), "area": None}
    if (original.get("tc") or "") != (convertido.get("tc") or "") and original.get("tc") and convertido.get("tc"):
        t["tc_desloc_q"] = None                          # TC diferente: o deslocamento exato fica para quem sabe a taxa
        t["tc"] = {"de": original.get("tc"), "para": convertido.get("tc")}
    if original.get("quadros") and convertido.get("quadros") and original["quadros"] != convertido["quadros"]:
        t["trecho"] = {"quadros_original": original["quadros"], "quadros_convertido": convertido["quadros"]}
    if (original.get("canais") or 0) != (convertido.get("canais") or 0):
        t["canais"] = {"de": original.get("canais"), "para": convertido.get("canais")}
    return t


def escrever_manifesto(pasta: str | Path, pares: list[dict], feito_por: str) -> Path:
    """Grava (ou acrescenta a) `ciclo-conversao.json` na pasta dos convertidos. `pares`: [{original, convertido,
    transformacao?}] com as sondas; a transformação sai das sondas quando não vier."""
    destino = Path(pasta) / ARQUIVO
    atual = ler_manifesto(pasta) or {"formato": FORMATO, "pares": []}
    vistos = {(p["convertido"].get("arquivo")) for p in atual["pares"]}
    for p in pares:
        conv = dict(p["convertido"])
        try:
            conv["arquivo"] = os.path.relpath(conv["arquivo"], str(pasta))
        except ValueError:                       # outro volume (Windows): fica o absoluto
            pass
        if conv["arquivo"] in vistos:
            continue
        atual["pares"].append({"original": p["original"], "convertido": conv,
                               "transformacao": p.get("transformacao") or transformacao(p["original"], p["convertido"])})
    atual.update(feito_por=feito_por, quando=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    tmp = destino.with_suffix(".json.parcial")
    tmp.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, destino)
    return destino


def ler_manifesto(pasta: str | Path) -> dict | None:
    p = Path(pasta) / ARQUIVO
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("formato") != FORMATO or not isinstance(d.get("pares"), list):
        return None
    return d


def _absoluto(pasta: Path, arquivo: str) -> Path:
    a = Path(arquivo)
    return a if a.is_absolute() else (pasta / a)


def relacoes(proj: Projeto) -> dict[str, list[dict]]:
    """`{id da mídia: [fatos "relacao"]}` do diário."""
    out: dict[str, list[dict]] = {}
    for f in diario.fatos(proj):
        if f.get("fato") == "relacao" and f.get("midia"):
            out.setdefault(f["midia"], []).append(f)
    return out


def registrar_do_manifesto(proj: Projeto, pasta: str | Path, forma: str, conta=None) -> list[str]:
    """Lê o manifesto de `pasta` e registra a relação de cada par cuja mídia a Carta conhece (o convertido JÁ vinculado
    pela identidade, ou o original vinculado — aí o convertido entra pela forma `forma`, "pelo manifesto"). Devolve os
    nomes registrados; o par que não confere fica de fora (dito em `conta.sem_par`, quando houver conta)."""
    from ..midia import identidade as _id
    from . import anexar as _anexar
    pasta = Path(pasta)
    m = ler_manifesto(pasta)
    if not m:
        return []
    formas = diario.formas(proj)
    ja = {(f.get("midia"), f.get("forma"), _anexar._nfc(f.get("arquivo") or "")) for fs in relacoes(proj).values() for f in fs}
    por_arquivo: dict[str, str] = {}
    for midia, fs in formas.items():
        for f in fs:
            por_arquivo[_anexar._nfc(os.path.abspath(f.get("arquivo") or ""))] = midia
    feitos = []
    for par in m["pares"]:
        conv = _absoluto(pasta, str((par.get("convertido") or {}).get("arquivo") or ""))
        orig = str((par.get("original") or {}).get("arquivo") or "")
        if not conv.is_file():
            continue
        imp = (par.get("convertido") or {}).get("impressao")
        if imp and _id.impressao(conv) != imp:
            if conta is not None:
                conta.sem_par.append(f"{conv.name}: a impressão não confere com o manifesto (outro arquivo no lugar)")
            continue
        chave_c = _anexar._nfc(os.path.abspath(str(conv)))
        midia = por_arquivo.get(chave_c)
        if midia is None and orig:
            midia = por_arquivo.get(_anexar._nfc(os.path.abspath(orig)))
            if midia is not None:
                _anexar._vincular(proj, midia, forma, conv, f"o manifesto da conversão ({m.get('feito_por')})",
                                  conta or _anexar.Conta())
        if midia is None or (midia, forma, chave_c) in ja:
            continue
        lugar = referencias.onde(conv)
        diario.acrescentar(proj, {"fato": "relacao", "midia": midia, "forma": forma, "de": "original", **lugar,
                                  "original": orig, "transformacao": par.get("transformacao") or {},
                                  "impressao": {"original": (par.get("original") or {}).get("impressao"),
                                                "convertido": imp},
                                  "por": f"manifesto:{m.get('feito_por') or '?'}"})
        feitos.append(conv.name)
    return feitos
