"""A conferência DEPOIS do conform: cada plano visível da scene × o esperado — o arquivo, o 1º e o último quadro visível
(a regra antiga do banco: 1º e último quadro visível de cada plano; `protocolos/prproj/relink-e-geometria.md` §10.9).

Lê o `bl-shots <scene> -inputrange -outputrange` (in/out na FONTE, início/fim na scene, arquivo) — ⚠️ não a FLAPI: depois de
um `bl-shots -replace` o `get_sequence_descriptor` continuou devolvendo o arquivo antigo (BL08, 2026-11-22).
Tolerância: UM quadro da timeline, na taxa da fonte (59,94 numa timeline 23,976 = 3 quadros; mesma taxa = 1) — o Baselight
arredonda a fronteira do plano de outra taxa (medido: 118–235 para o esperado 118–237).
"""
from __future__ import annotations

import math
import unicodedata

from .entrega import PREFIXO_OFFLINE


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def ler_bl_shots(texto: str) -> list[dict]:
    """As linhas `in out início fim arquivo` do `bl-shots -inputrange -outputrange` (o fim da scene é INCLUSIVO)."""
    tiras = []
    for linha in texto.splitlines():
        p = linha.split(None, 4)
        if len(p) == 5 and all(x.lstrip("-").isdigit() for x in p[:4]):
            tiras.append({"in": int(p[0]), "out": int(p[1]), "inicio": int(p[2]), "fim": int(p[3]) + 1,
                          "arquivo": p[4].strip().strip('"')})
    return tiras


def conferir(tiras: list[dict], esperados: list[dict], base_da_scene: int = 0) -> list[dict]:
    """Um resultado por plano esperado: `ok` · `sem_midia` (offline: o Baselight mostra) · `offline_de_proposito` ·
    `arquivo_diferente` · `fora_do_ponto` (in ou out além da tolerância). Os três últimos viram marker — nunca calados."""
    por_inicio: dict[int, list[dict]] = {}
    for t in tiras:
        por_inicio.setdefault(t["inicio"] - base_da_scene, []).append(t)
    usadas: set[int] = set()
    res = []
    for e in esperados:
        # várias trilhas podem começar no mesmo quadro: a tira do MESMO arquivo, depois a do mesmo fim; cada uma uma vez
        cand = [t for t in por_inicio.get(e["inicio"], []) if id(t) not in usadas]
        t = (next((x for x in cand if _nfc(x["arquivo"]) == _nfc(e["arquivo"] or "")), None)
             or next((x for x in cand if x["fim"] == e["fim"]), None) or (cand[0] if cand else None))
        if t is not None:
            usadas.add(id(t))
        r = {"inicio": e["inicio"], "fim": e["fim"], "esperado": e["arquivo"], "in_esperado": e["in"],
             "out_esperado": e["out"], "lido": t["arquivo"] if t else None, "in_lido": t["in"] if t else None,
             "out_lido": t["out"] if t else None}
        tol = max(1, math.ceil(e["fps_arquivo"] / e["fps_timeline"] - 1e-9))
        if PREFIXO_OFFLINE in (e["arquivo"] or ""):
            r["estado"] = "offline_de_proposito"
        elif t is None or t["arquivo"].startswith("%C"):
            r["estado"] = "sem_midia"
        elif _nfc(t["arquivo"]) != _nfc(e["arquivo"]):
            r["estado"] = "arquivo_diferente"
        elif e.get("parada"):
            r["estado"] = "ok"                  # imagem parada: o arquivo certo é o plano certo (in/out vêm do nome)
        elif abs(t["in"] - e["in"]) > tol or abs(t["out"] - e["out"]) > tol:
            r["estado"] = "fora_do_ponto"
        else:
            r["estado"] = "ok"
        r["tolerancia"] = tol
        res.append(r)
    return res


def motivo(r: dict) -> str:
    """O texto do marker "[Ciclo]" de um resultado que não é `ok`."""
    e = r["estado"]
    if e == "arquivo_diferente":
        return f"o conform pôs {r['lido']}; o Ciclo decidiu {r['esperado']}"
    if e == "fora_do_ponto":
        return (f"fora do ponto: in {r['in_lido']} × {r['in_esperado']}, out {r['out_lido']} × {r['out_esperado']} "
                f"(tolerância {r['tolerancia']} quadro(s) da fonte)")
    if e == "sem_midia":
        return f"o Baselight não achou {r['esperado']}"
    if e == "offline_de_proposito":
        return "offline de propósito: sem decisão do Ciclo (ambíguo ou sem original) — o editor escolhe e religa"
    return ""


def linhas_de_troca(resultados: list[dict]) -> list[str]:
    """As linhas do `bl-shots <scene> -replace` (stdin) para os planos com `arquivo_diferente`: `in out "lido" "esperado"`
    — a faixa na FONTE limita a troca àquele plano (o mesmo arquivo pode estar certo em outro). Medido BL08: "Replaced 1
    filename" e o render saiu com o arquivo novo, sem reconformar. Os outros estados NÃO se trocam: viram marker."""
    return [f'{r["in_lido"]} {r["out_lido"]} "{r["lido"]}" "{r["esperado"]}"'
            for r in resultados if r["estado"] == "arquivo_diferente"]
