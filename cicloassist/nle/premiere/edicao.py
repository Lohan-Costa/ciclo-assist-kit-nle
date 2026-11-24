"""Ler e editar a timeline DO EDITOR no Premiere, pelo MCP nativo (F4 do plano 2026-11-06).

O mesmo contrato do Avid (`avid/edicao.py`, caminho B do editor): a edição acontece numa CÓPIA da
sequência, na mesma bin; a original fica intacta; e a cópia só fica se a PROVA passar — todo
pedaço que a edição não toca reaparece na cópia, mesmo clipe, mesma entrada, mesma duração, no
lugar esperado. Senão a cópia é apagada e a resposta diz o que divergiu.

⚠️ `trimTrackItems` não está no catálogo (experimental): extrair = navalha nas duas pontas +
apagar o meio + puxar o que vem depois (`moveOrCopyTrackItems` com `timeOffset`). Tempo sempre
`n/fps + 1 µs` (`montagem.segundos`).

⭐ Nas versões SEM o MCP (2025/2026) a mesma coisa vai pela ponte CEP: `edicao_cep.py` (F7), com a
MESMA validação e a MESMA prova daqui; `M.via("edicao")` escolhe.

⚠️ Não medido / fora: efeitos e transições NÃO entram na prova (o MCP lê com uma chamada por item);
uma transição atravessada pela navalha não é recusada antes — a leitura avisa.
"""

from __future__ import annotations

import logging
import math
from fractions import Fraction
from typing import Any

from ...midia import timecode as _tc
from . import mcp_nativo as M
from . import montagem as G

log = logging.getLogger("cicloassist.nle.premiere.edicao")

TIPOS = ("extrair", "abrir_espaco", "inserir")


class EdicaoRecusada(RuntimeError):
    pass


def _rotulo(tipo: str, indice: int) -> str:
    return f"{'V' if tipo == 'video' else 'A'}{indice + 1}"


def _indice(rotulo: str) -> tuple[str, int]:
    r = (rotulo or "").strip().upper()
    if len(r) < 2 or r[0] not in "VA" or not r[1:].isdigit():
        raise EdicaoRecusada(f"trilha {rotulo!r}: use V1, V2… ou A1, A2…")
    return ("video" if r[0] == "V" else "audio"), int(r[1:]) - 1


def achar_sequencia(ref: str, pid: str | None = None) -> tuple[str, dict[str, Any]]:
    """`(pid, item)` da sequência pelo id ou pelo nome (sem merged)."""
    pid = pid or (M.projeto_ativo() or {}).get("agentProjectId")
    if not pid:
        raise EdicaoRecusada("não há projeto aberto no Premiere")
    seqs = [i for i in G.itens_do_projeto(pid) if i.get("type") == "sequence"]
    achadas = [i for i in seqs if i["itemId"] == ref] or [i for i in seqs if i.get("name") == ref]
    if not achadas:
        raise EdicaoRecusada(f"não achei a sequência {ref!r} no projeto do Premiere")
    if len(achadas) > 1:
        raise EdicaoRecusada(f"há {len(achadas)} sequências chamadas {ref!r}; use o id (o_que_esta_na_tela)")
    return pid, achadas[0]


def _pedacos(pid: str, sid: str, fps: Fraction) -> list[dict[str, Any]]:
    out = []
    for x in G._estrutura(pid, sid)["items"]:
        out.append({"tipo": x["mediaType"], "trilha": x["trackIndex"], "clipe": x.get("clipName", ""),
                    "ini": G.quadros(x["startTime"]["seconds"], fps), "dur": G.quadros(x["duration"]["seconds"], fps),
                    "src": G.quadros(x["sourceInPoint"]["seconds"], fps), "node": x["nodeId"]})
    return out


def ler(ref: str, de: str = "", ate: str = "", trilhas: list[str] | None = None) -> dict[str, Any]:
    if M.via("edicao") != "mcp":
        from . import edicao_cep
        return edicao_cep.ler(ref, de, ate, trilhas)
    pid, item = achar_sequencia(ref)
    est = M.chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": item["itemId"], "limit": 0})
    par = M.taxa_exata(est.get("videoFrameRate"))
    if not par:
        raise EdicaoRecusada("a sequência não diz a taxa de quadros")
    fps = Fraction(*par)
    return leitura(item.get("name"), item["itemId"], fps,
                   G.quadros(est.get("duration", {}).get("seconds", 0), fps),
                   _pedacos(pid, item["itemId"], fps), de, ate, trilhas)


def leitura(nome: Any, sid: str, fps: Fraction, total: int, pedacos: list[dict[str, Any]],
            de: str = "", ate: str = "", trilhas: list[str] | None = None) -> dict[str, Any]:
    """A resposta do `ler_timeline` — a MESMA forma nas duas vias (MCP e ponte CEP)."""
    q_de = _tc.para_quadros(de, fps) if de else 0
    q_ate = _tc.para_quadros(ate, fps) if ate else None
    so = {t.upper() for t in trilhas or []}
    por_trilha: dict[str, list] = {}
    for p in sorted(pedacos, key=lambda p: (p["tipo"] != "video", p["trilha"], p["ini"])):
        rot = _rotulo(p["tipo"], p["trilha"])
        if so and rot not in so:
            continue
        if p["ini"] + p["dur"] <= q_de or (q_ate is not None and p["ini"] >= q_ate):
            continue
        por_trilha.setdefault(rot, []).append({
            "de": _tc.de_quadros(p["ini"], fps), "ate": _tc.de_quadros(p["ini"] + p["dur"], fps),
            # ⭐ Os quadros JÁ contados: pelo chat (2026-11-07) o modelo subtraía os timecodes como se o
            #   último campo fosse decimal e acusava "10 frames, mas ocupa 15" num clipe certo.
            "de_quadro": p["ini"], "ate_quadro": p["ini"] + p["dur"],
            "clipe": p["clipe"], "in_no_clipe": p["src"], "duracao_frames": p["dur"]})
    return {"sequencia": nome, "id": sid, "fps": round(float(fps), 3),
            "duracao": _tc.de_quadros(total, fps),
            "trilhas": [{"trilha": k, "clipes": v} for k, v in por_trilha.items()],
            "aviso": (f"timecode HH:MM:SS:QQ a partir de 00:00:00:00 da sequência, QQ = quadro (0 a "
                      f"{math.ceil(fps) - 1}); de_quadro/ate_quadro e duracao_frames já estão contados — não "
                      "subtraia timecodes; efeitos e transições não aparecem nesta leitura")}


def _validar(ops: list[dict[str, Any]], fps: Fraction) -> list[dict[str, Any]]:
    if not ops:
        raise EdicaoRecusada("diga as operações")
    saida = []
    for n, op in enumerate(ops, 1):
        tipo = str(op.get("tipo") or "")
        if tipo not in TIPOS:
            raise EdicaoRecusada(f"operação {n}: tipo tem de ser {', '.join(TIPOS)}")
        o = {"tipo": tipo, "n": n}
        if tipo == "extrair":
            a, b = _tc.para_quadros(str(op.get("de") or ""), fps), _tc.para_quadros(str(op.get("ate") or ""), fps)
            if a is None or b is None or b <= a:
                raise EdicaoRecusada(f"operação {n}: extrair precisa de 'de' antes de 'ate', em HH:MM:SS:FF")
            o.update(pos=a, dur=b - a)
        else:
            em = _tc.para_quadros(str(op.get("em") or ""), fps)
            dur = op.get("duracao_frames")
            if em is None or not isinstance(dur, int) or dur <= 0:
                raise EdicaoRecusada(f"operação {n}: {tipo} precisa de 'em' (HH:MM:SS:FF) e duracao_frames > 0")
            o.update(pos=em, dur=dur)
            if tipo == "inserir":
                if not op.get("clipe"):
                    raise EdicaoRecusada(f"operação {n}: inserir precisa do clipe")
                o.update(clipe=str(op["clipe"]), in_no_clipe=int(op.get("in_no_clipe") or 0),
                         imagem_em=op.get("imagem_em") or "", som_em=list(op.get("som_em") or []))
                if o["imagem_em"]:
                    _indice(o["imagem_em"])
                for t in o["som_em"]:
                    _indice(t)
        saida.append(o)
    return saida


def conferir(ref: str, operacoes: list[dict[str, Any]]) -> str:
    """A conferência ANTES do cartão: forma das operações e o que a sequência tem. Vazio = ok."""
    if M.via("edicao") != "mcp":
        from . import edicao_cep
        return edicao_cep.conferir(ref, operacoes)
    try:
        pid, item = achar_sequencia(ref)
        est = M.chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": item["itemId"], "limit": 0})
        fps = Fraction(*M.taxa_exata(est.get("videoFrameRate")))
        ops = _validar(operacoes, fps)
        total = G.quadros(est.get("duration", {}).get("seconds", 0), fps)
        for o in ops:
            if o["pos"] > total:
                return f"operação {o['n']}: o ponto passa do fim da sequência ({_tc.de_quadros(total, fps)})"
            if o["tipo"] == "inserir":
                G.achar_take(G.itens_do_projeto(pid), o["clipe"])
    except (EdicaoRecusada, G.MontagemFalhou) as e:
        return str(e)
    except (M.McpIndisponivel, M.McpFalhou) as e:
        log.warning("conferência da edição sem Premiere (%s); deixo o cartão aparecer", e)
    return ""


def _empurrar(pid: str, sid: str, fps: Fraction, a_partir: int, deslocamento: int) -> None:
    """Move tudo que começa em `a_partir` ou depois por `deslocamento` quadros (do fim para o começo)."""
    alvo = [p for p in _pedacos(pid, sid, fps) if p["ini"] >= a_partir]
    alvo.sort(key=lambda p: p["ini"], reverse=deslocamento > 0)
    if not alvo:
        return
    itens = [{"nodeId": p["node"], "copy": False, "linked": False,
              "destinations": [{"timeOffset": {"seconds": float(Fraction(deslocamento) / fps)}}]} for p in alvo]
    r = M.chamar("moveOrCopyTrackItems", {"agentProjectId": pid, "sequenceId": sid, "items": itens})
    if r.get("errorCount"):
        raise EdicaoRecusada(f"o Premiere recusou empurrar a timeline: {str(r)[:300]}")


def _navalha(pid: str, sid: str, fps: Fraction, quadro: int) -> None:
    if quadro > 0:
        M.chamar("razorTrackItems", {"agentProjectId": pid, "sequenceId": sid,
                                     "times": [{"time": {"seconds": G.segundos(quadro, fps)}}]})


def editar(ref: str, operacoes: list[dict[str, Any]], nome_da_copia: str = "") -> dict[str, Any]:
    if M.via("edicao") != "mcp":
        from . import edicao_cep
        return edicao_cep.editar(ref, operacoes, nome_da_copia)
    pid, item = achar_sequencia(ref)
    base = M.chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": item["itemId"], "limit": 0})
    fps = Fraction(*M.taxa_exata(base.get("videoFrameRate")))
    ops = _validar(operacoes, fps)
    original = _pedacos(pid, item["itemId"], fps)
    nome = nome_da_copia or f"{item.get('name')} - editada"
    M.chamar("moveOrCopyProjectItems", {"agentProjectId": pid, "items": [
        {"itemId": item["itemId"], "copy": True, "name": nome}]})
    copia = next((i for i in G.itens_do_projeto(pid) if i.get("type") == "sequence" and i.get("name") == nome
                  and i["itemId"] != item["itemId"]), None)
    if not copia:
        raise EdicaoRecusada(f"o Premiere não criou a cópia {nome!r}")
    sid = copia["itemId"]
    deu_certo = False
    try:
        # ⭐ Da ÚLTIMA posição para a primeira: os timecodes são da timeline ORIGINAL, e assim uma
        #   operação nunca mexe no lugar de outra que ainda vai acontecer.
        for o in sorted(ops, key=lambda o: o["pos"], reverse=True):
            if o["tipo"] == "extrair":
                _navalha(pid, sid, fps, o["pos"])
                _navalha(pid, sid, fps, o["pos"] + o["dur"])
                dentro = [p for p in _pedacos(pid, sid, fps)
                          if p["ini"] >= o["pos"] and p["ini"] + p["dur"] <= o["pos"] + o["dur"]]
                if dentro:
                    M.chamar("deleteTrackItems", {"agentProjectId": pid, "sequenceId": sid, "ripple": False,
                                                  "items": [{"nodeId": p["node"], "deleteLinked": False} for p in dentro]})
                _empurrar(pid, sid, fps, o["pos"] + o["dur"], -o["dur"])
            else:
                _navalha(pid, sid, fps, o["pos"])
                _empurrar(pid, sid, fps, o["pos"], o["dur"])
                if o["tipo"] == "inserir":
                    _inserir(pid, sid, fps, o)
        # ⭐ A PROVA
        divergencias, conferidos = _provar(original, _pedacos(pid, sid, fps), ops)
        deu_certo = not divergencias
    finally:
        if not deu_certo:
            try:
                M.chamar("deleteProjectItems", {"agentProjectId": pid, "itemIds": [sid]})
            except (M.McpFalhou, M.McpIndisponivel):
                pass
    if divergencias:
        raise EdicaoRecusada("a cópia NÃO passou na prova e foi apagada: " + "; ".join(divergencias[:6]))
    return resposta(nome, sid, len(ops), item.get("name"), conferidos)


def resposta(nome: str, sid: str, n_ops: int, original: Any, conferidos: int) -> dict[str, Any]:
    return {"ok": True, "copia": nome, "id": sid, "operacoes": n_ops, "original": original,
            # ⛔ Só o que a prova CONFERIU: pedaço cortado pela edição não conta como conferido.
            "prova": (f"{conferidos} pedaço(s) que a edição não toca, conferidos na cópia" if conferidos else
                      "todos os pedaços da original foram tocados pela edição: não sobrou o que provar; "
                      "confira a cópia no play")}


def _inserir(pid: str, sid: str, fps: Fraction, o: dict[str, Any]) -> None:
    itens = G.itens_do_projeto(pid)
    take = G.achar_take(itens, o["clipe"])
    fonte = G._criar_sequencia(pid, f"_fonte inserir {o['n']}", take["itemId"], None)
    try:
        M.chamar("razorTrackItems", {"agentProjectId": pid, "sequenceId": fonte, "times": [
            {"time": {"seconds": G.segundos(q, fps)}} for q in (o["in_no_clipe"], o["in_no_clipe"] + o["dur"]) if q > 0]})
        copiar = []
        for x in G._estrutura(pid, fonte)["items"]:
            if G.quadros(x["startTime"]["seconds"], fps) != o["in_no_clipe"]:
                continue
            tipo, k = x["mediaType"], x["trackIndex"]
            if tipo == "video" and o["imagem_em"]:
                alvo = {"targetVideoTrack": _indice(o["imagem_em"])[1]}
            elif tipo == "audio" and k < len(o["som_em"]):
                alvo = {"targetAudioTrack": _indice(o["som_em"][k])[1]}
            else:
                continue
            alvo.update(sequenceId=sid, targetStartTime={"seconds": G.segundos(o["pos"], fps)})
            copiar.append({"nodeId": x["nodeId"], "copy": True, "linked": False, "destinations": [alvo]})
        if not copiar:
            raise EdicaoRecusada(f"operação {o['n']}: nada do clipe {o['clipe']!r} entrou (diga imagem_em/som_em)")
        precisa_a = max([c["destinations"][0].get("targetAudioTrack", -1) for c in copiar] + [-1]) + 1
        precisa_v = max([c["destinations"][0].get("targetVideoTrack", -1) for c in copiar] + [-1]) + 1
        if precisa_a:
            G._garantir_trilhas(pid, sid, "audio", precisa_a)
        if precisa_v:
            G._garantir_trilhas(pid, sid, "video", precisa_v)
        M.chamar("moveOrCopyTrackItems", {"agentProjectId": pid, "sequenceId": fonte, "items": copiar})
    finally:
        M.chamar("deleteProjectItems", {"agentProjectId": pid, "itemIds": [fonte]})


def _provar(original: list[dict], copia: list[dict], ops: list[dict]) -> tuple[list[str], int]:
    """Todo pedaço da original INTEIRO fora das regiões editadas reaparece, deslocado do que as
    operações ANTES dele somaram (abrir/inserir empurram, extrair puxa)."""
    def deslocamento(q: int) -> int | None:
        d = 0
        for o in ops:
            if o["tipo"] == "extrair":
                if q >= o["pos"] + o["dur"]:
                    d -= o["dur"]
                elif q + 0 > o["pos"]:
                    return None   # dentro do extraído
            elif q >= o["pos"]:
                d += o["dur"]
        return d

    def toca(p: dict) -> bool:
        a, b = p["ini"], p["ini"] + p["dur"]
        for o in ops:
            if o["tipo"] == "extrair" and a < o["pos"] + o["dur"] and b > o["pos"]:
                return True
            if o["tipo"] != "extrair" and a < o["pos"] < b:
                return True   # a navalha cortou este pedaço em dois
        return False

    sobra = [(p["tipo"], p["trilha"], p["clipe"], p["ini"], p["src"], p["dur"]) for p in copia]
    falhas: list[str] = []
    conferidos = 0
    for p in original:
        if toca(p):
            continue
        d = deslocamento(p["ini"])
        if d is None:
            continue
        esperado = (p["tipo"], p["trilha"], p["clipe"], p["ini"] + d, p["src"], p["dur"])
        if esperado in sobra:
            sobra.remove(esperado)
            conferidos += 1
        else:
            falhas.append(f"{_rotulo(p['tipo'], p['trilha'])} {p['clipe']} (em {p['ini']}) não está em {p['ini'] + d}")
    return falhas, conferidos
