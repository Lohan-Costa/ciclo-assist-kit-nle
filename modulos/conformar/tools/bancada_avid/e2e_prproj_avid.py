"""Bancada da rota Premiere → Avid pelo .prproj (`servico/prproj_avid.py`), contra um Media Composer ABERTO.

Rodar (o MC com um projeto aberto; a API na 9100):

    .venv/bin/python tools/bancada_avid/e2e_prproj_avid.py <projeto.prproj> <sequência> <nome da entrega> <pasta>...

Ex. (PRODC, R04): ... "…/R04 PRODUCAO-C/P2P/WSP_EDITOR_MIDIA_MOVIDA.prproj" PRODC_CORTE02 "PRODC PRPROJ 1" "…/ISOLADO/MIDIA"

A entrega vai para a pasta do projeto aberto (`<nome>/<nome>_MIDIAS` e `_SEQ`), a _SEQ abre e a timeline vai ao Record.
O resumo sai em JSON no fim. A pasta de trabalho fica no temporário do sistema (o que o MC precisa ler NÃO vai lá: o
TCC do macOS não deixa o processo dele escrever em /private/tmp — `relink.exportar_aaf`).
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    prproj, seq, nome, pastas = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from avid.mcapi import MediaComposer
    from prproj_avid import montar
    from tools.prproj_para_drt import analisar

    t0 = time.time()
    analise = analisar(prproj, seq, pastas)
    print(f"lido em {time.time() - t0:.1f}s: {len(analise['leitura']['segmentos'])} segmentos", flush=True)

    def progresso(etapa, feito=0, total=0, detalhe=""):
        print(f"  [{time.time() - t0:6.1f}s] {etapa} {feito}/{total} {detalhe}", flush=True)

    with MediaComposer(timeout=60) as mc:
        projeto = (mc.projeto() or {}).get("path")
        if not projeto:
            print("o Media Composer não tem projeto aberto")
            return 1
        trabalho = tempfile.mkdtemp(prefix="dlpc_prproj_avid_")
        r = montar(mc, analise, projeto, trabalho, nome, seq, progresso)
    print(json.dumps(r, indent=1, ensure_ascii=False, default=str))
    print(f"total {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
