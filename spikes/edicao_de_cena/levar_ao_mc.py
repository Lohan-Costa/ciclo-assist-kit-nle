"""Leva ao Media Composer o resultado do fluxo no papel: a bin de falas do agente de Diálogo e o corte do agente Editor, com L/J.

    python spikes/edicao_de_cena/levar_ao_mc.py "<pasta da saída>"

Exige o projeto PRODUCAO-A_CURTA aberto. Só cria bins NOVAS; a sequência é carregada na Record.
Plano: `docs/plano/2026-11-09-edicao-de-cena.md`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA.parents[1]))
sys.path.insert(0, str(PASTA))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import avb  # noqa: E402

import no_papel as P  # noqa: E402  (o mesmo módulo do fluxo: BIN, ROTEIRO, takes)
from cicloassist.avid.mcapi import MediaComposer, mob_id_da_api  # noqa: E402
from cicloassist.mcp.ferramentas import corte as _corte, falas as _ferr_falas  # noqa: E402
from cicloassist.plano import esquema as _esquema  # noqa: E402
from cicloassist.servico import arrastados as _arrastados  # noqa: E402

NOME = "C07 CORTE AGENTES"


def falas_por_segmento(dialogo: dict, takes: dict) -> list[dict]:
    """Os momentos de volta ao endereço que `separar_falas` aceita (ela recusa quadros)."""
    saida = []
    for m in dialogo["momentos"]:
        trechos = []
        for t in m["trechos"]:
            ini, fim = int(t["inicio_no_take_frames"]), int(t["inicio_no_take_frames"]) + int(t["duracao_frames"])
            segs = takes[t["take"]]
            de = next(int(s["segmento"]) for s in segs if int(s["inicio_no_take_frames"]) == ini)
            ate = next(int(s["segmento"]) for s in segs if int(s["saida_no_take_frames"]) == fim)
            trechos.append({"take": t["take"], "do_segmento": de, **({"ate_o_segmento": ate} if ate != de else {})})
        saida.append({"fala": m["fala"], "variante": m["variante"], "texto": m["texto"], "personagem": m.get("personagem") or "",
                      "trechos": trechos, "confianca": "inferido", "fonte": "transcricao"})
    return saida


def main() -> int:
    pasta = Path(sys.argv[1])
    takes = P.carregar_takes()
    dialogo = json.loads((pasta / "3_dialogo.json").read_text(encoding="utf-8"))
    final = json.loads((pasta / "corte_final.json").read_text(encoding="utf-8"))

    nome = sys.argv[sys.argv.index("--nome") + 1] if "--nome" in sys.argv else NOME
    so_o_corte = "--so-corte" in sys.argv   # a bin de falas já existe; e no 24.6 carregar pela API cai no Source (abrir pela bin)
    if not so_o_corte:
        _arrastados.autorizar(P.ROTEIRO)
        de_fora = [{k: v for k, v in d.items() if v not in (None, "")} for d in dialogo["deixadas_de_fora"]]
        r = _ferr_falas.separar_falas(P.BIN, "7", falas_por_segmento(dialogo, takes), de_fora, P.ROTEIRO)
        print("FALAS:", json.dumps({k: v for k, v in r.items() if k != "nomes"}, ensure_ascii=False)[:600])

    cortes = [{"take": p["take"], "duracao_frames": p["img_dur"], "inicio_no_take": p["img_ini"], "confianca": "inferido", "fonte": "transcricao",
               "porque": p["porque"][:300], "corte_de_som": p["corte_de_som"], "som_frames": p["som_frames"]} for p in final["planos"]]
    with _esquema.com_lj_do_agente_editor():
        r = _corte.montar_corte(P.BIN, nome, cortes)
    print("CORTE:", json.dumps({k: v for k, v in r.items() if k != "resumo"}, ensure_ascii=False)[:900])
    if not r.get("ok"):
        return 2
    if so_o_corte:
        return 0

    with MediaComposer() as mc:
        raiz = Path(mc.projeto()["caminho"])
    with avb.open(str(raiz / r["bin"])) as f:
        mob = next(i.mob for i in f.content.items if i.user_placed and str(i.mob.name) == NOME)
        mob_id = str(mob.mob_id)
    with MediaComposer() as mc:
        mc._chamar("LoadMobsIntoViewer", mob_ids=[mob_id_da_api(mob_id)], view_type=mc._enum("LoadMobsIntoViewer", "view_type", "Record"))
    print("carregada na Record:", mob_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
