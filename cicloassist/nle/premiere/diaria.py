"""Importar a diária no Premiere: o proxy como ORIGINAL, ou a ALTA com o proxy anexado (P2).

Plano `docs/plano/2026-11-07-premiere-proxy-e-merged.md`. O editor escolhe o modo a cada pedido (decisão do
autor, §4: perguntar sempre). O som direto entra sempre como original — `canProxy()` é falso em áudio.

⛔⛔ **O par é conferido AQUI, antes de anexar** (`resolve_proxy.conferir_par`): o `attachProxy` do Premiere
só confere o número de canais e aceita calado outra proporção, outro TC e até outro material (P0.2). Par
reprovado = a alta entra SEM proxy, e a resposta diz por quê — nunca um proxy errado no lugar.

As bins espelham a diária: uma por subpasta, debaixo da bin da diária (`D01/CAM A`, `D01/SOM`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ... import resolve_proxy as _px
from ... import resolve_opatom as _op
from . import ponte

MODOS = ("original", "proxy_anexado")
SONS = {".wav", ".aif", ".aiff", ".bwf"}


def sons_da_diaria(diaria: Path) -> list[Path]:
    return _op.videos_da_pasta(diaria, SONS)


def _bin_de(raiz_bin: str, base: Path, arquivo: Path) -> str:
    rel = arquivo.parent.relative_to(base).parts if arquivo.parent != base else ()
    return "/".join([raiz_bin, *rel]) if raiz_bin else "/".join(rel)


def planejar(modo: str, diaria: Path, proxies: Path, bin: str, *, sondar=None) -> dict[str, Any]:
    """O que vai entrar, de onde, em que bin, e com que proxy. Não toca no Premiere.

    Devolve {itens: [{arquivo, bin, proxy, tipo}], sem_proxy: [{arquivo, motivo}], problemas: [...]}."""
    sondar = sondar or _px.sondar
    if modo not in MODOS:
        return {"itens": [], "sem_proxy": [], "problemas": [f"modo {modo!r}: use 'original' ou 'proxy_anexado'"]}
    itens, sem_proxy, problemas = [], [], []
    originais = _px.videos_da_pasta(diaria)
    if modo == "original":
        prox = {p.stem.lower(): p for p in proxies.glob("*.mov") if not p.name.startswith("._")}
        for o in originais:
            p = prox.get(o.stem.lower())
            if p is None:
                problemas.append(f"{o.name}: não há proxy em {proxies}")
                continue
            itens.append({"arquivo": str(p), "bin": _bin_de(bin, diaria, o), "proxy": "", "tipo": "video"})
    else:
        for o in originais:
            p = proxies / (o.stem + ".mov")
            motivo = ""
            if not p.exists():
                motivo = "não há proxy com esse nome"
            else:
                pp = _px.conferir_par(sondar(o), sondar(p))
                if pp:
                    motivo = "o proxy não confere: " + "; ".join(pp)
            if motivo:
                sem_proxy.append({"arquivo": o.name, "motivo": motivo})
            itens.append({"arquivo": str(o), "bin": _bin_de(bin, diaria, o),
                          "proxy": "" if motivo else str(p), "tipo": "video"})
    for s in sons_da_diaria(diaria):
        itens.append({"arquivo": str(s), "bin": _bin_de(bin, diaria, s), "proxy": "", "tipo": "som"})
    if not any(i["tipo"] == "video" for i in itens) and not problemas:
        problemas.append(f"não há vídeo para importar em {diaria}")
    return {"itens": itens, "sem_proxy": sem_proxy, "problemas": problemas}


def texto_do_plano(itens: list[dict]) -> str:
    """O plano em texto tabulado para o `cicloImportar` (⛔ nunca código)."""
    for i in itens:
        for c in (i["arquivo"], i["proxy"], i["bin"]):
            if "\t" in c or "\n" in c:
                raise ValueError(f"caminho com tabulação ou quebra de linha: {c!r}")
    linhas, atual = [], None
    for i in sorted(itens, key=lambda x: (x["bin"], x["arquivo"])):
        if i["bin"] != atual:
            linhas.append(f"bin\t{i['bin']}")
            atual = i["bin"]
        linhas.append(f"arq\t{i['arquivo']}\t{i['proxy']}")
    return "\n".join(linhas)


def importar(plano: dict[str, Any]) -> dict[str, Any]:
    """Executa o plano pela ponte e resume. Funciona em todas as versões (o `attachProxy` é ExtendScript)."""
    feito = ponte.chamar("cicloImportar", texto_do_plano(plano["itens"]), prazo=900)
    if feito.get("erro"):
        return {"erro": feito["erro"]}
    feitos = feito.get("feitos") or []
    falhas = [f for f in feitos if f.get("erro")]
    pedidos = [f for f in feitos if f.get("proxy_pedido")]
    return {"importados": sum(1 for f in feitos if not f.get("erro") and not f.get("ja_estava")),
            "ja_estavam": sum(1 for f in feitos if f.get("ja_estava")),
            "com_proxy": sum(1 for f in pedidos if f.get("anexou")),
            "proxy_pedidos": len(pedidos),
            "sem_proxy": plano.get("sem_proxy") or [],
            "bins": sorted({f.get("bin") or "(raiz)" for f in feitos}),
            "falharam": [{"arquivo": Path(f["arquivo"]).name, "erro": f["erro"]} for f in falhas],
            "detalhe": feitos}
