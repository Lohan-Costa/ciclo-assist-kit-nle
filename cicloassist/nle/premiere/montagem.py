"""Montar uma sequência no Premiere pelo MCP nativo (27.1+) — o executor do `montar_corte` e do
`separar_falas` no Premiere (plano `docs/plano/2026-11-06-mcp-do-premiere.md`, F3).

⛔⛔ **Por que não `insertClipsToSequence`:** MEDIDO na F0 — ele põe UMA trilha de áudio por clipe, e
nem é o 1º canal (WAV 5.0 com um tom por canal → o export só tinha o 2º). Som direto multicanal
perderia as lapelas calado. ⇒ O caminho completo, medido 5 de 5 canais:

    1. uma SEQUÊNCIA-FONTE por pedaço, criada a partir do take (`createSequences` com o clipe:
       todos os canais, cada um na sua trilha, o take inteiro a partir de 0);
    2. a NAVALHA nela (`razorTrackItems`) na entrada e na saída — imagem e som separados, que é o
       que faz o corte em L/J (`trimTrackItems` não está no catálogo: é experimental);
    3. COPIAR o pedaço do meio de cada trilha (`moveOrCopyTrackItems`, `linked: false`) para a
       posição dele na sequência final;
    4. apagar as sequências-fonte, e LER DE VOLTA a sequência final: todo pedaço tem de estar no
       quadro pedido, senão a resposta diz qual não está.

⛔ Tempo mandado ao Premiere: SEMPRE `n/fps + 1 µs`. O 3 pontos arredonda PARA BAIXO (`n/fps` em float
erra 1 em 6 em 23,976 e 29,97 — F0, na imagem); e a NAVALHA não encaixa no som: medido, `(n+½)/fps`
cortou o áudio em 195,5 quadros (precisão de amostra) e a imagem em 201 (para cima). Com +1 µs os
dois caem no quadro exato (195 e 200), e o µs é 0,05 amostra a 48 kHz.

⭐ O tempo de um subclipe ou merged é RELATIVO a ele (F0) — o mesmo referencial do plano
(`inicio_no_take`), então nenhuma conta de offset de master acontece aqui.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from . import mcp_nativo as M

log = logging.getLogger("cicloassist.nle.premiere.montagem")

BIN_DE_TRABALHO = "_Ciclo Assist (temporario)"


class MontagemFalhou(RuntimeError):
    pass


@dataclass
class Pedaco:
    """Um pedaço da timeline, em QUADROS. `item_id` é o do MCP (clipe, subclipe ou merged)."""
    item_id: str
    nome: str
    v_in: int
    v_dur: int
    a_in: int
    a_dur: int
    pos_v: int
    pos_a: int
    tem_video: bool = True
    tem_audio: bool = True


@dataclass
class Resultado:
    sequencia_id: str
    nome: str
    pedacos: int
    itens: int
    conferidos: int
    divergencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


#: O que se soma a `n/fps` para o float não cair um tiquinho ANTES do quadro `n`.
EPSILON_S = 1e-6


def segundos(quadros: int, fps: Fraction) -> float:
    """Quadro → segundos que o Premiere lê como O MESMO quadro, no 3 pontos e na navalha."""
    return float(Fraction(quadros) / fps) + EPSILON_S


def quadros(seg: float, fps: Fraction) -> int:
    return int(round(Fraction(seg).limit_denominator(10**9) * fps))


# ── achar os takes ──────────────────────────────────────────────────────────

def itens_do_projeto(pid: str) -> list[dict[str, Any]]:
    return M.paginar("getProjectItems", {"agentProjectId": pid}, "items")


def achar_take(itens: list[dict[str, Any]], nome: str, bin_: str = "") -> dict[str, Any]:
    """O item de nome `nome`, preferindo o que está na bin `bin_` (caminho "A/B" do projeto).

    ⛔ Nome repetido FORA da bin pedida e nenhum dentro = ambíguo: recusa, nunca escolhe calado.
    """
    candidatos = [i for i in itens if i.get("type") in ("clip", "sequence") and i.get("name") == nome]
    if not candidatos:
        raise MontagemFalhou(f"não achei o take {nome!r} no projeto do Premiere")
    if bin_:
        b = bin_.strip("/")
        dentro = [i for i in candidatos if str(i.get("path", "")).rsplit("/", 1)[0] == b
                  or str(i.get("path", "")).startswith(b + "/")]
        if dentro:
            candidatos = dentro
    if len(candidatos) > 1:
        lugares = ", ".join(str(i.get("path")) for i in candidatos[:4])
        raise MontagemFalhou(f"o take {nome!r} aparece {len(candidatos)} vezes ({lugares}); diga a bin")
    return candidatos[0]


def taxa_do_item(pid: str, item: dict[str, Any]) -> Fraction:
    if item.get("type") == "sequence":
        est = M.chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": item["itemId"], "limit": 0})
        par = M.taxa_exata(est.get("videoFrameRate"))
    else:
        md = M.chamar("getClipMetadata", {"agentProjectId": pid, "itemIds": [item["itemId"]], "fields": ["frameRate"]})
        valor = next((v.get("value") for v in md["results"][0].get("values") or [] if v.get("field") == "frameRate"), None)
        par = M.taxa_exata(valor)
    if not par:
        raise MontagemFalhou(f"o take {item.get('name')!r} não diz a taxa de quadros (é só som?)")
    return Fraction(*par)


def bin_id(pid: str, itens: list[dict[str, Any]], caminho: str, criar: bool = True) -> str | None:
    """O id da bin `caminho` ("A/B"), criando o que faltar."""
    caminho = (caminho or "").strip("/")
    if not caminho:
        return None
    pai = None
    feito = ""
    for parte in caminho.split("/"):
        feito = f"{feito}/{parte}" if feito else parte
        achada = next((i for i in itens if i.get("type") == "bin" and i.get("path") == feito), None)
        if achada:
            pai = achada["itemId"]
            continue
        if not criar:
            return None
        args: dict[str, Any] = {"agentProjectId": pid, "names": [parte]}
        if pai:
            args["parentId"] = pai
        M.chamar("createBins", args)
        itens[:] = itens_do_projeto(pid)
        achada = next((i for i in itens if i.get("type") == "bin" and i.get("path") == feito), None)
        if not achada:
            raise MontagemFalhou(f"não consegui criar a bin {feito!r}")
        pai = achada["itemId"]
    return pai


# ── montar ──────────────────────────────────────────────────────────────────

def _criar_sequencia(pid: str, nome: str, clip_id: str, parent: str | None) -> str:
    pedido: dict[str, Any] = {"name": nome, "clipIds": [clip_id]}
    if parent:
        pedido["parentId"] = parent
    r = M.chamar("createSequences", {"agentProjectId": pid, "sequences": [pedido]})
    ids = r.get("createdSequenceIds") or []
    if not ids:
        raise MontagemFalhou(f"o Premiere não criou a sequência {nome!r}: {str(r)[:300]}")
    return ids[0]


def _estrutura(pid: str, sid: str) -> dict[str, Any]:
    itens = M.paginar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": sid}, "items")
    base = M.chamar("getSequenceStructure", {"agentProjectId": pid, "sequenceId": sid, "limit": 0})
    return {"tracks": base.get("tracks") or [], "items": itens, "fps": base.get("videoFrameRate")}


def _garantir_trilhas(pid: str, sid: str, tipo: str, quantas: int) -> None:
    trilhas = [t for t in _estrutura(pid, sid)["tracks"] if t.get("mediaType") == tipo]
    falta = quantas - len(trilhas)
    if falta > 0:
        M.chamar("addTracksToSequence", {"agentProjectId": pid, "sequenceId": sid, "trackType": tipo, "count": falta})


def montar(nome: str, pedacos: list[Pedaco], bin_da_sequencia: str = "",
           pid: str | None = None, fps_sem_imagem: Fraction | None = None) -> Resultado:
    """Monta `nome` com os `pedacos` e devolve o que foi conferido.

    ⛔ Um pedaço que não confere NÃO é desfeito em silêncio nem escondido: vai em `divergencias`, e
    quem chama decide (o `montar_corte` devolve como erro para o editor ver).
    """
    if not pedacos:
        raise MontagemFalhou("nenhum pedaço para montar")
    p = M.projeto_ativo() if pid is None else {"agentProjectId": pid}
    if not p:
        raise MontagemFalhou("não há projeto aberto no Premiere")
    pid = p["agentProjectId"]
    itens = itens_do_projeto(pid)
    por_id = {i["itemId"]: i for i in itens}
    # A taxa e o formato vêm do 1º pedaço COM IMAGEM (um WAV não tem taxa nem resolução).
    molde = next((pc for pc in pedacos if pc.tem_video), None)
    if molde is None:
        # ⭐ Só som (o WAV do gravador): a sequência nasce VAZIA na taxa que quem chama sabe
        #   (a do take, que o `resolver_take` lê da sequência ativa).
        if not fps_sem_imagem:
            raise MontagemFalhou("nenhum pedaço tem imagem: não sei a taxa nem o formato da sequência")
        fps = Fraction(fps_sem_imagem)
    else:
        fps = taxa_do_item(pid, por_id[molde.item_id])
    temp_bin = bin_id(pid, itens, BIN_DE_TRABALHO)
    destino_bin = bin_id(pid, itens, bin_da_sequencia) if bin_da_sequencia else None
    avisos: list[str] = []

    # A sequência final nasce do 1º take (formato, taxa, resolução e canais casados) e é ESVAZIADA.
    if molde is not None:
        final = _criar_sequencia(pid, nome, molde.item_id, destino_bin)
    else:
        pedido: dict[str, Any] = {"name": nome, "frameRate": round(float(fps), 3)}
        if destino_bin:
            pedido["parentId"] = destino_bin
        r = M.chamar("createSequences", {"agentProjectId": pid, "sequences": [pedido]})
        final = (r.get("createdSequenceIds") or [None])[0]
        if not final:
            raise MontagemFalhou(f"o Premiere não criou a sequência {nome!r}: {str(r)[:300]}")
    vazios = [{"nodeId": x["nodeId"], "deleteLinked": True} for x in _estrutura(pid, final)["items"]]
    if vazios:
        M.chamar("deleteTrackItems", {"agentProjectId": pid, "sequenceId": final, "items": vazios})

    fontes: list[str] = []
    esperado: list[tuple[str, int, int, int, int]] = []   # (tipo, trilha, posição, in, duração)
    deu_certo = False
    try:
        for n, pc in enumerate(pedacos, 1):
            item = por_id.get(pc.item_id)
            if item is None:
                raise MontagemFalhou(f"pedaço {n}: o take sumiu do projeto")
            # ⭐ Take só de som (WAV) não tem taxa de quadros, e não precisa: os quadros dele são os
            #   da sequência. Só imagem com outra taxa é recusada.
            fps_take = fps if (molde is None or pc.item_id == molde.item_id or not pc.tem_video) \
                else taxa_do_item(pid, item)
            if fps_take != fps:
                raise MontagemFalhou(f"pedaço {n} ({pc.nome}): {float(fps_take):.3f} fps numa sequência de "
                                     f"{float(fps):.3f} — misturar taxas ainda não é montado")
            fonte = _criar_sequencia(pid, f"_fonte {n:03d} {pc.nome}"[:80], pc.item_id, temp_bin)
            fontes.append(fonte)
            cortes = []
            if pc.tem_video:
                cortes += [{"time": {"seconds": segundos(q, fps)}, "mediaType": "video"}
                           for q in (pc.v_in, pc.v_in + pc.v_dur) if q > 0]
            if pc.tem_audio:
                cortes += [{"time": {"seconds": segundos(q, fps)}, "mediaType": "audio"}
                           for q in (pc.a_in, pc.a_in + pc.a_dur) if q > 0]
            if cortes:
                M.chamar("razorTrackItems", {"agentProjectId": pid, "sequenceId": fonte, "times": cortes})
            est = _estrutura(pid, fonte)
            copiar = []
            for x in est["items"]:
                tipo, trilha = x["mediaType"], x["trackIndex"]
                ini = quadros(x["startTime"]["seconds"], fps)
                if tipo == "video" and pc.tem_video and ini == pc.v_in:
                    alvo = {"sequenceId": final, "targetVideoTrack": trilha,
                            "targetStartTime": {"seconds": segundos(pc.pos_v, fps)}}
                    esperado.append(("video", trilha, pc.pos_v, pc.v_in, pc.v_dur))
                elif tipo == "audio" and pc.tem_audio and ini == pc.a_in:
                    alvo = {"sequenceId": final, "targetAudioTrack": trilha,
                            "targetStartTime": {"seconds": segundos(pc.pos_a, fps)}}
                    esperado.append(("audio", trilha, pc.pos_a, pc.a_in, pc.a_dur))
                else:
                    continue
                copiar.append({"nodeId": x["nodeId"], "copy": True, "linked": False, "destinations": [alvo]})
            if not copiar:
                raise MontagemFalhou(f"pedaço {n} ({pc.nome}): a navalha não deixou pedaço em "
                                     f"{pc.v_in}/{pc.a_in} — o take tem esse tamanho?")
            trilhas_a = max([c["destinations"][0].get("targetAudioTrack", -1) for c in copiar] + [-1]) + 1
            trilhas_v = max([c["destinations"][0].get("targetVideoTrack", -1) for c in copiar] + [-1]) + 1
            if trilhas_a:
                _garantir_trilhas(pid, final, "audio", trilhas_a)
            if trilhas_v:
                _garantir_trilhas(pid, final, "video", trilhas_v)
            r = M.chamar("moveOrCopyTrackItems", {"agentProjectId": pid, "sequenceId": fonte, "items": copiar})
            if r.get("errorCount"):
                raise MontagemFalhou(f"pedaço {n} ({pc.nome}): o Premiere recusou a cópia: {str(r)[:300]}")
        deu_certo = True
    finally:
        # ⛔ Plano aplicado pela metade deixa o editor com um estado que ninguém pediu: a
        #   sequência final incompleta vai embora junto com as de trabalho.
        if not deu_certo:
            fontes.append(final)
        if fontes:
            try:
                M.chamar("deleteProjectItems", {"agentProjectId": pid, "itemIds": fontes})
                if temp_bin:
                    M.chamar("deleteProjectItems", {"agentProjectId": pid, "itemIds": [temp_bin]})
            except (M.McpFalhou, M.McpIndisponivel) as e:
                avisos.append(f"ficaram sequências de trabalho na bin {BIN_DE_TRABALHO!r}: {e}")

    # ⭐ A prova: ler a sequência final e conferir CADA pedaço, quadro a quadro.
    final_est = _estrutura(pid, final)
    vistos = [(x["mediaType"], x["trackIndex"], quadros(x["startTime"]["seconds"], fps),
               quadros(x["sourceInPoint"]["seconds"], fps), quadros(x["duration"]["seconds"], fps))
              for x in final_est["items"]]
    divergencias = []
    restantes = list(vistos)
    for e in esperado:
        if e in restantes:
            restantes.remove(e)
        else:
            perto = [v for v in restantes if v[0] == e[0] and v[1] == e[1] and abs(v[2] - e[2]) <= 2]
            divergencias.append(f"{e[0]} trilha {e[1] + 1} em {e[2]}: esperava entrada {e[3]} e {e[4]} quadros, "
                                f"veio {perto[0][3:] if perto else 'nada'}")
    for v in restantes:
        divergencias.append(f"sobrou {v[0]} trilha {v[1] + 1} em {v[2]} ({v[4]} quadros)")
    return Resultado(sequencia_id=final, nome=nome, pedacos=len(pedacos), itens=len(vistos),
                     conferidos=len(esperado) - len([d for d in divergencias if d.startswith(("video", "audio"))]),
                     divergencias=divergencias, avisos=avisos)
