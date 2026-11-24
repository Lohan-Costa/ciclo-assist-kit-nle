"""Montar uma sequência no Premiere SEM o MCP nativo (2025/2026) — pela ponte CEP (`cicloMontar`).

F6 do plano `docs/plano/2026-11-06-mcp-do-premiere.md` (§14). O princípio do autor: o fluxo novo vale nas
versões antigas quando for COMPLETO — e o ExtendScript é (medido no 25.6.5 e no 26.0.2): quadro exato com
`n/fps + 1 µs` e o som multicanal inteiro.

O que NÃO entra aqui, por decisão do autor (2026-11-06): corte em L/J — "existe uma subjetividade nessa
escolha que é melhor ficar com o editor". Pedaço com imagem e som desencontrados é recusado.

⭐ A mesma prova da via MCP: a sequência é LIDA DE VOLTA (ticks) e cada pedaço tem de estar no quadro
pedido; o que não confere vai em `divergencias`.
"""

from __future__ import annotations

from fractions import Fraction

from . import ponte
from .montagem import MontagemFalhou, Pedaco, Resultado, segundos

TICKS = 254016000000


def _q(ticks: str, fps: Fraction) -> int:
    return int(round(Fraction(int(ticks), TICKS) * fps))


def _campo(texto: str) -> str:
    return str(texto).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def montar(nome: str, pedacos: list[Pedaco], fps: Fraction, bin_da_sequencia: str = "") -> Resultado:
    """`pedacos[i].item_id` aqui é a REFERÊNCIA que a CEP entende (nodeId, caminho "BIN/NOME" ou nome)."""
    if not pedacos:
        raise MontagemFalhou("nenhum pedaço para montar")
    for n, pc in enumerate(pedacos, 1):
        if pc.tem_video and pc.tem_audio and (pc.a_in != pc.v_in or pc.a_dur != pc.v_dur or pc.pos_a != pc.pos_v):
            raise MontagemFalhou(f"pedaço {n} ({pc.nome}): imagem e som desencontrados (corte em L/J) não são "
                                 "montados nesta versão do Premiere — a escolha fica com o editor")
    linhas = [f"seq\t{_campo(nome)}\t{_campo(bin_da_sequencia)}"]
    for pc in pedacos:
        ini, dur, pos = (pc.v_in, pc.v_dur, pc.pos_v) if pc.tem_video else (pc.a_in, pc.a_dur, pc.pos_a)
        linhas.append(f"p\t{_campo(pc.item_id)}\t{segundos(ini, fps):.7f}\t{segundos(ini + dur, fps):.7f}"
                      f"\t{segundos(pos, fps):.7f}\t{'1' if pc.tem_video else '0'}")
    try:
        r = ponte.chamar("cicloMontar", "\n".join(linhas), prazo=300)
    except (ponte.PremiereIndisponivel, ponte.ExtendScriptFalhou) as e:
        raise MontagemFalhou(str(e)) from e
    if not isinstance(r, dict) or r.get("erro"):
        raise MontagemFalhou(str((r or {}).get("erro") if isinstance(r, dict) else r))

    vistos = [(x["tipo"], int(x["trilha"]), _q(x["ini"], fps), _q(x["inp"], fps), _q(x["dur"], fps))
              for x in r.get("itens") or []]
    divergencias = []
    conferidos = 0
    for n, pc in enumerate(pedacos, 1):
        tipo = "v" if pc.tem_video else "a"
        ini, dur, pos = (pc.v_in, pc.v_dur, pc.pos_v) if pc.tem_video else (pc.a_in, pc.a_dur, pc.pos_a)
        deste = [v for v in vistos if v[2] == pos]
        principal = [v for v in deste if v[0] == tipo and v[1] == 0]
        if not principal or (principal[0][3], principal[0][4]) != (ini, dur):
            divergencias.append(f"pedaço {n} ({pc.nome}) em {pos}: esperava entrada {ini} e {dur} quadros, "
                                f"veio {principal[0][3:] if principal else 'nada'}")
            continue
        # O som que veio junto (todas as trilhas do clipe) tem de casar com a imagem
        tortos = [v for v in deste if (v[3], v[4]) != (ini, dur)]
        if tortos:
            divergencias.append(f"pedaço {n} ({pc.nome}): {len(tortos)} trilha(s) fora do quadro: {tortos[:3]}")
            continue
        conferidos += len(deste)
    return Resultado(sequencia_id=str(r.get("id") or ""), nome=str(r.get("sequencia") or nome),
                     pedacos=len(pedacos), itens=len(vistos), conferidos=conferidos,
                     divergencias=divergencias, avisos=[])
