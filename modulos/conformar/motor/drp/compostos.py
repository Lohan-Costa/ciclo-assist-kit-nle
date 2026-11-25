"""NEST do Premiere → Compound Clip do Resolve, DEPOIS do import e do Fusion.

Decisão do autor (2026-10-04): o nest vira Compound Clip 1:1; a sequência multicam continua
achatada (a câmera escolhida). O DRT traz o nest ABERTO em trilhas, como sempre; o compound se
faz pela API, juntando os clipes dele (`Timeline.CreateCompoundClip`). Por que não escrever o
compound no DRT (a forma foi medida — banco `protocolos/drt-drp/estruturas.md`, "Compound Clip"):

  ⚠️ MEDIDO 2026-10-04 (Resolve 21.1.0.14, macOS): a API NÃO alcança clipe DENTRO de um compound
  (`MediaPoolItem.GetTimeline()` do compound devolve None). O insert do interfone do PRODUCAO_B tem
  máscara + Basic 3D no Fusion, que a casca monta pela API: num compound vindo do DRT isso viraria
  "refazer à mão". Já uma composição montada ANTES sobrevive ao `CreateCompoundClip` (o quadro
  antes e depois, correlação 1,0 — timeline `gab_compound_fusion_r21`).

O preço, aceito pelo autor: o Motion do item de fora já vem composto nos clipes de dentro (a
imagem é a mesma), e cada USO do nest vira um compound próprio.

O MESMO caminho está na casca (`aplicarCompostos`, `plugins/resolve/casca/main.js`).
"""
from __future__ import annotations


def _achar(timeline, inicio: int, c: dict):
    for it in timeline.GetItemListInTrack("video", int(c["trilha"])) or []:
        if it.GetStart() - inicio == int(c["quadro"]) and it.GetName() == c["arquivo"]:
            return it
    return None


def aplicar_compostos(timeline, relatorio: dict) -> list[dict]:
    """Junta os clipes de cada nest do relatório num Compound Clip com o nome do nest.

    Um nest com clipe que não se acha fica ABERTO em trilhas (a timeline continua certa) e volta
    com o erro: juntar só parte dele mudaria o que o editor montou. Falha de um não para os outros
    (memória "o trabalho caro não pode morrer no acessório")."""
    grupos = relatorio.get("compostos") or []
    if grupos and not callable(getattr(timeline, "CreateCompoundClip", None)):
        return [{"nome": g["nome"], "ok": False,
                 "erro": "este Resolve não cria Compound Clip pela API — o nest ficou em trilhas"}
                for g in grupos]
    inicio = timeline.GetStartFrame()
    out = []
    for g in grupos:
        base = {"nome": g["nome"], "clipes": len(g["clipes"])}
        itens = [_achar(timeline, inicio, c) for c in g["clipes"]]
        faltam = sum(1 for x in itens if x is None)
        if faltam or not itens:
            out.append({**base, "ok": False,
                        "erro": f"{faltam} de {len(itens)} clipes não encontrados — o nest ficou em trilhas"})
            continue
        try:
            cc = timeline.CreateCompoundClip(itens, {"name": g["nome"]})
        except Exception as e:                       # noqa: BLE001 — registra e segue
            cc, erro = None, f"{type(e).__name__}: {e}"
        else:
            erro = "o Resolve não criou o Compound Clip — o nest ficou em trilhas"
        out.append({**base, "ok": True} if cc else {**base, "ok": False, "erro": erro})
    return out
