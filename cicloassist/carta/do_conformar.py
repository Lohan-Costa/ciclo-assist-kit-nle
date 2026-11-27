"""O CONFORMAR monta no Premiere pelo escritor da Carta (plano `docs/plano/2026-11-26-carta-registro-da-producao.md`,
etapa 1; decisão do autor, 2026-11-26: "nada de marcador a menos que seja impossível a tradução").

O Conformar recebe a timeline (bin ou AAF), lê com o leitor dele e CASA cada clipe com um arquivo desta máquina (o
relink: o online no lugar do offline — a parte que só ele faz). Daqui em diante é a Carta: uma Carta OCULTA por envio
(na pasta de dados do app), uma referência por arquivo casado com o arquivo na forma `original`, o item `sequencia` pelo
MESMO leitor de segmentos (`timeline.trilhas_de_segmentos`) e a importação da Carta (`importar_premiere`): rampa,
congelado, transição e título sem marcador; só a sequência volta ao projeto do editor.

O pedido (a rota `/carta/premiere/do_conformar`):

    {"id": "<id do envio>", "nome": "CORTE", "fps": 23.976…, "tc_inicio_q": 86400, "drop_frame": false,
     "segmentos": [<segmento do leitor do Conformar> + {"arquivo": "<o casado>" | "", "offline": {nb, fps, fps_tc, tc,
                   audio_canais, reel, rotulo} | null}]}

O segmento sem arquivo e sem `offline` (rejeitado, título, vazio) segue a regra do leitor; o com `offline` entra como
MÍDIA OFFLINE no lugar, com o nome e o TC do original (a regra da Carta).
"""

from __future__ import annotations

import os
from pathlib import Path

from . import anexar, projeto, referencias, timeline, vitrine
from .projeto import CartaErro, Projeto


def _taxa(fps: float) -> str:
    from ..avid.take import fracao_da_taxa
    f = fracao_da_taxa(float(fps))
    return f"{f.numerator}/{f.denominator}" if f.denominator != 1 else str(f.numerator)


def carta_oculta(raiz: Path, id_envio: str, fps: float) -> Projeto:
    """A Carta deste envio (uma por envio: o mesmo envio de novo reaproveita a mesma)."""
    pasta = Path(raiz) / "".join(c for c in str(id_envio) if c.isalnum() or c in "-_")[:64]
    if (pasta / projeto.PASTA_INTERNA / "projeto.json").is_file():
        return projeto.abrir(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    return projeto.novo(pasta, f"Conformar {id_envio}", _taxa(fps))


def _ref_do_arquivo(proj: Projeto, arquivo: str) -> str:
    from ..midia import identidade as _id
    ident = referencias.identidade_da_sonda(_id.sondar(arquivo))
    caminho, ref = referencias.criar(proj, proj.ocultas, Path(arquivo).stem, ident,
                                     {"nle": "conformar", "forma": "original", "arquivo": arquivo}, distinta=False)
    vitrine.esconder(proj, caminho, ref, referencias.SUFIXO)
    anexar._vincular(proj, ref["id"], "original", Path(arquivo), "o relink do Conformar", anexar.Conta())
    return ref["id"]


def _ref_offline(proj: Projeto, meta: dict, audio: bool) -> str:
    fps = float(meta.get("fps") or 0) or 24000 / 1001
    rotulo = str(meta.get("rotulo") or meta.get("reel") or "offline")
    ident = {"nome_da_fonte": str(meta.get("reel") or Path(rotulo).stem), "tipo": "audio" if audio else "video",
             "fps": _taxa(fps), "quadros": int(meta.get("nb") or 0) or None, "tc": meta.get("tc") or None}
    if meta.get("audio_canais"):
        ident["canais_de_som"] = [1] * int(meta["audio_canais"])
    ident = {k: v for k, v in ident.items() if v not in (None, "", [])}
    caminho, ref = referencias.criar(proj, proj.ocultas, os.path.basename(rotulo), ident,
                                     {"nle": "conformar", "offline": True, "rotulo": rotulo})
    vitrine.esconder(proj, caminho, ref, referencias.SUFIXO)
    return ref["id"]


def item_do_conformar(proj: Projeto, pedido: dict) -> dict:
    """O item `sequencia` do envio, com as referências criadas na Carta oculta."""
    fps = float(pedido.get("fps") or 25.0)
    segs = list(pedido.get("segmentos") or [])
    if not segs:
        raise CartaErro("a timeline não tem segmentos")
    proj.ocultas.mkdir(parents=True, exist_ok=True)
    por_arquivo: dict[str, str] = {}
    por_offline: dict[str, str] = {}

    def chave(s: dict) -> str:
        arq = s.get("arquivo") or ""
        if arq and os.path.isfile(arq):
            if arq not in por_arquivo:
                por_arquivo[arq] = _ref_do_arquivo(proj, arq)
            return por_arquivo[arq]
        meta = s.get("offline")
        if isinstance(meta, dict) and meta.get("nb"):
            k = str(meta.get("rotulo") or arq or meta.get("reel"))
            if k not in por_offline:
                por_offline[k] = _ref_offline(proj, meta, bool(s.get("is_audio")))
            return por_offline[k]
        return ""

    S = timeline._conformar()
    q = lambda tc: S._tc(tc, fps)  # noqa: E731
    # o clipe sem mídia nem offline (rejeitado) não entra como clipe: o leitor o pula pela falta de mob_id
    for s in segs:
        if not s.get("is_transition") and not s.get("is_gap") and not s.get("is_effect"):
            s["mob_id"] = (s.get("mob_id") or "conformar") if chave(s) else None
    trilhas = timeline.trilhas_de_segmentos(segs, q, chave)
    return {"tipo": "sequencia", "timeline": True, "nome": str(pedido.get("nome") or "timeline"), "fps": _taxa(fps),
            "tc_inicio_q": int(pedido.get("tc_inicio_q") or 0), "drop_frame": bool(pedido.get("drop_frame")),
            "duracao_q": max((c["fim_q"] for t in trilhas for c in t["clipes"]), default=0), "trilhas": trilhas,
            "conformar": {"arquivos": len(por_arquivo), "offline": len(por_offline)}}


def importar(raiz: Path, pedido: dict, chamar, quadro: tuple[int, int] | None = None) -> dict:
    """Do envio do Conformar à sequência no projeto ABERTO do editor, pelo caminho da Carta."""
    from . import importar_premiere
    proj = carta_oculta(raiz, str(pedido.get("id") or "envio"), float(pedido.get("fps") or 25.0))
    item = item_do_conformar(proj, pedido)
    rel = importar_premiere.importar_timeline(proj, item, chamar, quadro=quadro, forma="original")
    rel["carta"] = str(proj.raiz)
    rel["conformar"] = item["conformar"]
    return rel

