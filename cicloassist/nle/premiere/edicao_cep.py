"""Ler e editar a timeline DO EDITOR no Premiere SEM o MCP nativo (2025/2026) — pela ponte CEP.

F7 do plano `docs/plano/2026-11-06-mcp-do-premiere.md`. O mesmo contrato da via MCP (`edicao.py`): a
edição acontece numa CÓPIA, na mesma bin da original; a original fica intacta; e a cópia só fica se
a MESMA prova passar (`edicao._provar`). A validação também é a mesma (`edicao._validar`).

O trabalho todo vai numa chamada só (`cicloEditar` do `host.jsx`, plano em TEXTO tabulado — nunca
código): clonar, navalha do QE, tirar, empurrar, inserir. Medido no 26.0.2 (2026-11-07): navalha no
quadro; `remove`/`move` agem só no item (o vinculado fica); `overwriteClip` na trilha k põe imagem
em V(k) e som a partir de A(k) — o "acompanhante" que não foi pedido é tirado.

⚠️ Diferença da via MCP: `som_em` tem de ser trilhas SEGUIDAS (A3, A4, A5…) — o ExtendScript não
leva um canal para uma trilha qualquer. Recusado antes do cartão, com a frase.
"""

from __future__ import annotations

import logging
from fractions import Fraction
from typing import Any

from . import edicao as E
from . import ponte

log = logging.getLogger("cicloassist.nle.premiere.edicao_cep")

TICKS = 254016000000


def _fps(ticks_do_quadro: str) -> Fraction:
    t = int(ticks_do_quadro or 0)
    if t <= 0:
        raise E.EdicaoRecusada("a sequência não diz a taxa de quadros")
    return Fraction(TICKS, t)


def _q(ticks: str, fps: Fraction) -> int:
    return int(round(Fraction(int(ticks), TICKS) * fps))


def _t(quadro: int, fps: Fraction) -> str:
    """O quadro em TICKS inteiros (exato: 25 fps = 10.160.640.000 por quadro; 23,976 = 10.594.584.000)."""
    t = Fraction(quadro) * TICKS / fps
    return str(int(t) if t.denominator == 1 else round(t))


def _campo(texto: str) -> str:
    return str(texto).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


class SemPonte(E.EdicaoRecusada):
    """A ponte não respondeu — não é o pedido que está errado."""


def _chamar(funcao: str, *args: Any, prazo: float = 120) -> dict[str, Any]:
    try:
        r = ponte.chamar(funcao, *args, prazo=prazo)
    except ponte.PremiereIndisponivel as e:
        raise SemPonte(f"o Premiere não está ligado ao Ciclo Assist: {e}") from e
    except ponte.ExtendScriptFalhou as e:
        raise E.EdicaoRecusada(f"o Premiere recusou: {e}") from e
    if not isinstance(r, dict):
        raise E.EdicaoRecusada(f"o Premiere respondeu o que não se esperava: {str(r)[:200]}")
    if r.get("erro"):
        raise E.EdicaoRecusada(str(r["erro"]))
    return r


def _pedacos(itens: list[dict[str, Any]], fps: Fraction) -> list[dict[str, Any]]:
    return [{"tipo": x["tipo"], "trilha": int(x["trilha"]), "clipe": x.get("clipe", ""),
             "ini": _q(x["ini"], fps), "dur": _q(x["dur"], fps), "src": _q(x["inp"], fps), "node": x["node"]}
            for x in itens]


def _fora_da_grade(itens: list[dict[str, Any]], fps: Fraction) -> list[str]:
    """Itens cujo início não cai num quadro da sequência (em ticks, sem arredondar)."""
    por_quadro = Fraction(TICKS) / fps
    return [f"{x['tipo']} {int(x['trilha']) + 1} {x.get('clipe', '')}" for x in itens
            if (Fraction(int(x["ini"])) / por_quadro).denominator != 1]


def _sequencia(ref: str) -> tuple[dict[str, Any], Fraction]:
    r = _chamar("cicloLerSequencia", str(ref))
    return r, _fps(r.get("quadro"))


def ler(ref: str, de: str = "", ate: str = "", trilhas: list[str] | None = None) -> dict[str, Any]:
    r, fps = _sequencia(ref)
    return E.leitura(r.get("sequencia"), r.get("id", ""), fps, _q(r.get("fim") or "0", fps),
                     _pedacos(r.get("itens") or [], fps), de, ate, trilhas)


def _trilhas_do_inserir(o: dict[str, Any]) -> tuple[int, int, int]:
    """(v, a, n): índice da trilha de imagem (-1 = sem), da 1ª de som (-1 = sem) e quantas de som."""
    v = E._indice(o["imagem_em"])[1] if o["imagem_em"] else -1
    som = [E._indice(t) for t in o["som_em"]]
    if any(tipo != "audio" for tipo, _ in som):
        raise E.EdicaoRecusada(f"operação {o['n']}: som_em leva trilhas de som (A1, A2…)")
    if o["imagem_em"] and E._indice(o["imagem_em"])[0] != "video":
        raise E.EdicaoRecusada(f"operação {o['n']}: imagem_em leva uma trilha de imagem (V1, V2…)")
    idx = [k for _, k in som]
    if idx and idx != list(range(idx[0], idx[0] + len(idx))):
        raise E.EdicaoRecusada(
            f"operação {o['n']}: nesta versão do Premiere o som do clipe entra em trilhas SEGUIDAS "
            f"(ex.: A3, A4, A5); peça som_em em sequência, a partir da primeira")
    if v < 0 and not idx:
        raise E.EdicaoRecusada(f"operação {o['n']}: diga imagem_em e/ou som_em")
    return v, (idx[0] if idx else -1), len(idx)


def conferir(ref: str, operacoes: list[dict[str, Any]]) -> str:
    """A conferência ANTES do cartão. Vazio = ok."""
    try:
        r, fps = _sequencia(ref)
        ops = E._validar(operacoes, fps)
        total = _q(r.get("fim") or "0", fps)
        for o in ops:
            if o["pos"] > total:
                return f"operação {o['n']}: o ponto passa do fim da sequência ({E._tc.de_quadros(total, fps)})"
            if o["tipo"] == "inserir":
                _trilhas_do_inserir(o)
                if not _chamar("cicloTemClipe", o["clipe"]).get("ok"):
                    return f"operação {o['n']}: não achei o clipe {o['clipe']!r} no projeto do Premiere"
    except SemPonte as e:
        # ⛔ Conferência que quebra NÃO barra: o cartão aparece e a ferramenta confere de novo.
        log.warning("conferência da edição sem a ponte (%s); deixo o cartão aparecer", e)
    except E.EdicaoRecusada as e:
        return str(e)
    return ""


def editar(ref: str, operacoes: list[dict[str, Any]], nome_da_copia: str = "") -> dict[str, Any]:
    r, fps = _sequencia(ref)
    ops = E._validar(operacoes, fps)
    original = _pedacos(r.get("itens") or [], fps)
    nome = nome_da_copia or f"{r.get('sequencia')} - editada"
    linhas = [f"seq\t{_campo(r.get('id') or ref)}\t{_campo(nome)}"]
    # ⭐ Da ÚLTIMA posição para a primeira: os timecodes são da timeline ORIGINAL.
    for o in sorted(ops, key=lambda o: o["pos"], reverse=True):
        if o["tipo"] == "extrair":
            linhas.append(f"x\t{_t(o['pos'], fps)}\t{_t(o['pos'] + o['dur'], fps)}")
        elif o["tipo"] == "abrir_espaco":
            linhas.append(f"e\t{_t(o['pos'], fps)}\t{_t(o['dur'], fps)}")
        else:
            v, a, n = _trilhas_do_inserir(o)
            linhas.append("\t".join(["i", _t(o["pos"], fps), _t(o["dur"], fps), _campo(o["clipe"]),
                                     _t(o["in_no_clipe"], fps), _t(o["in_no_clipe"] + o["dur"], fps),
                                     str(v), str(a), str(n)]))
    feito = _chamar("cicloEditar", "\n".join(linhas), prazo=300)
    sid = str(feito.get("id") or "")
    divergencias, conferidos = E._provar(original, _pedacos(feito.get("itens") or [], fps), ops)
    # ⛔⛔ A prova acima ARREDONDA para quadros, e um item 1 tick depois do quadro passava nela com o
    #   Premiere mostrando o quadro errado (medido, 2026-11-07). Fora da grade é divergência.
    fora_antes = len(_fora_da_grade(r.get("itens") or [], fps))
    fora = _fora_da_grade(feito.get("itens") or [], fps)
    if len(fora) > fora_antes:
        divergencias.append(f"{len(fora) - fora_antes} item(ns) fora da grade de quadros na cópia "
                            f"(ex.: {fora[0]})")
    if divergencias:
        try:
            _chamar("cicloApagarSequencia", sid, str(feito.get("anterior") or ""))
        except E.EdicaoRecusada as e:
            log.warning("a cópia %s não passou na prova e NÃO foi apagada: %s", sid, e)
            raise E.EdicaoRecusada(f"a cópia NÃO passou na prova e não consegui apagá-la ({e}); apague "
                                   f"{nome!r} à mão: " + "; ".join(divergencias[:6])) from e
        raise E.EdicaoRecusada("a cópia NÃO passou na prova e foi apagada: " + "; ".join(divergencias[:6]))
    return E.resposta(str(feito.get("copia") or nome), sid, len(ops), r.get("sequencia"), conferidos)


def tela() -> dict[str, Any]:
    """`cicloTela`: a sequência ativa e o Source, com a agulha — o que o `o_que_esta_na_tela` precisa."""
    return _chamar("cicloTela")
