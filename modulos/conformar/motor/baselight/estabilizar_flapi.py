"""O Stabilize do MC nos planos de uma scene: o tracker nativo com o rastreio do MC + o Transform (`blg_estab.py`).
Entrada (stdin): {"fps": f, "planos": [{inicio, quadros, p_x, p_y, zoom, filtro, pos, w, h, clip}, …]}.
Roda no python da FilmLight (o que tem a `flapi`), chamado por `enviar.estabilizar`; veio do laboratório de 2026-11-23
(`estudo/ferramentas/estab_nativo.py`, PRODUCAO-A C011/C013, igual ao render do MC).

⛔ Plano que JÁ tem tracker não é tocado (o do colorista, trazido pelo Multi-Paste do "atualizar corte"): o Filtering que
ele ajustou não se sobrescreve. Cada plano gravado é conferido na volta (`blg_estab.conferir`); o que não confere sai
como falha, com o motivo — nunca calado.

    "/Library/Application Support/FilmLight/python/3.12-v7-venv/bin/python" estabilizar_flapi.py localhost:JOB:SCENE < p.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blg_estab as B  # noqa: E402
import camadas as CA  # noqa: E402

import flapi  # noqa: E402

pedido = json.load(sys.stdin)
fps = float(pedido["fps"])
molde = CA.marcar(open(B.MOLDE, encoding="latin1").read())   # o Transform e o Tracker com o nome do Ciclo
saida = {"feitos": [], "ja_tinha": [], "falhas": []}
c = flapi.Connection("localhost")
c.connect()
s = c.Scene.open_scene(c.Scene.parse_path(sys.argv[1]), set())
s.wait_until_open()
try:
    # o rastreio vai em px do formato de TRABALHO da scene (não do raster do xmeml)
    wf = s.get_scene_settings().get_single("WorkingFormat")
    res_ = s.get_formats().get_format(wf).get_resolution()
    W, H = int(res_["Width"]), int(res_["Height"])
    saida["formato"] = {"nome": wf, "w": W, "h": H}
    ids = s.get_shot_ids()
    s.start_delta("Ciclo Assist: o Stabilize do MC (tracker nativo)")
    try:
        for p in pedido["planos"]:
            p = B.no_formato(p, W, H)
            onde = {"quadro": p["inicio"], "clip": p.get("clip")}
            cand = [i for i in ids if int(i.StartFrame) == int(p["inicio"])
                    and int(i.EndFrame) - int(i.StartFrame) == int(p["quadros"])]
            if len(cand) != 1:
                saida["falhas"].append({**onde, "motivo": "o plano não está na scene com o início e a duração da "
                                                          f"montagem ({len(cand)} candidatos)"})
                continue
            sh = s.get_shot(cand[0].ShotId)
            try:
                texto = B.ler(sh.get_blg_payload())
                if B.tem_tracker(texto):
                    saida["ja_tinha"].append(onde)
                    continue
                res = sh.get_blg_resources()
                novo = B.montar(texto, molde, p, fps)
                sh.delete_all_layers()
                sh.apply_blg_payload(B.gravar(novo), res)
                if B.conferir(B.ler(sh.get_blg_payload()), p, fps):
                    saida["feitos"].append(onde)
                else:
                    saida["falhas"].append({**onde, "motivo": "o Baselight não guardou o estabilizador como gravado"})
            except Exception as e:                       # noqa: BLE001 — um plano não derruba os outros
                saida["falhas"].append({**onde, "motivo": f"{type(e).__name__}: {e}"[:200]})
            finally:
                sh.release()
        s.end_delta()
    except Exception:
        s.cancel_delta()
        raise
    s.save_scene()
    print(json.dumps(saida, ensure_ascii=False))
finally:
    s.close_scene()
    c.close()
