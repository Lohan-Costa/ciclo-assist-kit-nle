"""Masters que NÃO casaram com nada nas pastas, mas já estão ONLINE no Media Composer (autor, 2026-10-13).

"Só deve aparecer na bin o que está offline. Se a mídia existir na Avid MediaFiles ou num AMA link feito por fora do
app e estiver online, ela não deve aparecer na _SEQ" — e a lista de mídias diz isso ao editor, em vez de "sem mídia".

Duas fontes, as duas já do RELINKER (nada novo de formato):

1. **Avid MediaFiles** — o índice do MSM (`media/pmr.py`): MobID do master → `.mxf`, sem abrir arquivo (~1 s para 26
   índices nesta máquina). Online = ao menos um arquivo listado existe no disco. Medido 2026-10-13: 87 de 99 masters
   do AAF do PRODUCAO-A estão lá, entre eles a `DJI_0317`, que o casamento dava como "sem mídia".
2. **Link AMA do projeto** — a varredura do reaproveitamento (`avb_bin/ama_do_projeto`): um master AMA com o MESMO
   MobID numa bin do projeto, com o arquivo no disco e a data batendo (`ama.online`). Na rota da bin, o
   `esta_offline is False` do próprio master diz o mesmo.

⚠️ "Não sei" fica de fora do resultado (vale como offline): esconder da _SEQ um clipe que talvez esteja offline
apagaria da vista justamente o que o editor precisa ver — mesma regra do `avb_bin.visibilidade`.
"""

from __future__ import annotations

import logging
import os

from aaf.masters import chave_mob

log = logging.getLogger("delapraca.ja_online")

GERENCIADA = "gerenciada"   # está na Avid MediaFiles
AMA = "ama"                 # um link AMA online no projeto


def classificar(masters, pasta_projeto: str = "", cache: str | None = None, ignorar: tuple[str, ...] = ()) -> dict:
    """`{chave do MobID: GERENCIADA | AMA}` dos `masters` que já estão online. O que não está (ou não se sabe) não entra."""
    pendentes = {chave_mob(getattr(m, "mob_id", "")): m for m in masters or []}
    pendentes.pop("", None)
    achados: dict[str, str] = {}
    if not pendentes:
        return achados

    for k, m in pendentes.items():
        if getattr(m, "esta_offline", None) is False:
            achados[k] = AMA

    try:
        from media import pmr

        indice = pmr.indice_de(pmr.raizes_de_midia())
        for urn, arquivos in indice.por_master.items():
            k = chave_mob(urn)
            if k in pendentes and k not in achados and any(os.path.isfile(a) for a in arquivos):
                achados[k] = GERENCIADA
    except Exception as e:  # noqa: BLE001 — sem o índice, ninguém é dado como online (fica à vista)
        log.warning("não consegui ler o índice da Avid MediaFiles (%s)", e)

    if pasta_projeto and os.path.isdir(pasta_projeto) and len(achados) < len(pendentes):
        try:
            from avb_bin import ama_do_projeto as ama

            for lista in ama.varrer(pasta_projeto, cache, ignorar).values():
                for item in lista:
                    k = chave_mob(item.get("mob_id", ""))
                    if k in pendentes and k not in achados and ama.online(item):
                        achados[k] = AMA
        except Exception as e:  # noqa: BLE001
            log.warning("não consegui varrer os links AMA do projeto (%s)", e)

    log.info("já online sem casamento: %d de %d (%s)", len(achados), len(pendentes),
             ", ".join(sorted(f"{getattr(pendentes[k], 'nome', k)}={v}" for k, v in achados.items()))[:400])
    return achados
