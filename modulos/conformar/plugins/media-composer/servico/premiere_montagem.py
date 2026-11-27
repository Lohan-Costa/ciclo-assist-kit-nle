"""O MODO PREMIERE do Conformar (Avid → Premiere): o ENVIO para o escritor da Carta (plano
`docs/plano/2026-11-26-carta-registro-da-producao.md`, etapa 1; decisão do autor: "nada de marcador a menos que seja
impossível a tradução").

O Conformar lê a timeline (bin ou AAF) e CASA cada clipe com um arquivo desta máquina; daqui vai o envio — os segmentos
do leitor, cada um com o arquivo casado ou o rótulo do offline — que o núcleo monta pela Carta
(`cicloassist/carta/do_conformar.py`, rota `/nucleo/conformar/premiere`). ⛔ A montagem antiga pelo ExtendScript
(`plano` → `dlpcMontar`, com rampa, congelado, transição e título como marcador) SAIU em 2026-11-26, depois das provas
B34, B32, B30, B33 e PRODUCAO-A pelo caminho novo.
"""

from __future__ import annotations

import os


def envio_para_a_carta(segs: list[dict], casados: list[dict], fps: float, nome: str, id_envio: str,
                       inicio: int | None = None, drop: bool = False, metas: dict | None = None) -> dict:
    """O pedido de `/nucleo/conformar/premiere` (`cicloassist/carta/do_conformar.py`): os SEGMENTOS do leitor, cada um
    com o arquivo que o relink CASOU (`arquivo`) ou, sem arquivo aqui, o rótulo do offline (`offline`, dos `metas`).
    O rejeitado vai sem nenhum dos dois (o leitor da Carta o deixa de fora, e é dito)."""
    import copy
    por_seg = {c.get("segment_index"): c for c in casados if isinstance(c, dict)}
    out = []
    for i, s in enumerate(segs):
        x = copy.deepcopy(s)
        c = por_seg.get(i) or {}
        arquivo = c.get("matched_path") or ""
        sem_midia = c.get("offline") or c.get("rejected") or not arquivo or not os.path.isfile(arquivo)
        x["arquivo"] = "" if sem_midia else arquivo
        meta = (metas or {}).get(arquivo) if sem_midia and c.get("offline") and not c.get("rejected") else None
        x["offline"] = {**meta, "rotulo": arquivo} if meta else None
        if c.get("source_offset_correction"):
            x["source_start_frames"] = int(x.get("source_start_frames") or 0) + int(c["source_offset_correction"])
        out.append(x)
    return {"id": id_envio, "nome": nome, "fps": fps,
            "tc_inicio_q": int(inicio) if inicio is not None and int(inicio) >= 0 else 3600 * round(fps),
            "drop_frame": drop, "segmentos": out}
