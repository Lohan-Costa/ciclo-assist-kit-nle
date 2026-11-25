"""Os efeitos de imagem do Premiere (velocidade e Motion, `efeitos.py`) nos planos de uma scene. Entrada (stdin):
{"fps": f, "planos": [{inicio, quadros, clip, in_bl, q, motion, series}, …]}. Roda no python da FilmLight (o que tem a
`flapi`), chamado por `enviar.aplicar_efeitos`; veio do estudo PRODUCAO-C (`estudo/ferramentas/traduzir_prodc.py`,
132 de 133 pontos).

O plano do Baselight acha o da montagem pelo metadado `clip` (o nome do clipitem) e pelo tempo: o conform corta o plano de
cima onde há corte embaixo, e cada pedaço leva o seu trecho. ⛔ O BLG parte do MOLDE, nunca do lido (`get_blg_payload`
devolve a pilha de quem está POR CIMA no 1º quadro). Tudo num delta só; um plano que falha não derruba os outros e sai
como falha, com o motivo.

    "/Library/Application Support/FilmLight/python/3.12-v7-venv/bin/python" efeitos_flapi.py localhost:JOB:SCENE < p.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camadas as CA  # noqa: E402
import efeitos as EF  # noqa: E402

import flapi  # noqa: E402

pedido = json.load(sys.stdin)
fps = float(pedido["fps"])
planos = pedido["planos"]
molde_r = open(EF.MOLDE_RETIME, encoding="latin1").read()
molde_t = open(EF.MOLDE_TRANSFORM, encoding="latin1").read()
pasta = pedido.get("pasta")            # onde guardar o BLG do Ciclo de cada plano (o "atualizar corte" o usa de base)
saida = {"feitos": [], "falhas": [], "sem_par": [], "textos": {}}
c = flapi.Connection("localhost")
c.connect()
s = c.Scene.open_scene(c.Scene.parse_path(sys.argv[1]), set())
s.wait_until_open()
try:
    wf = s.get_scene_settings().get_single("WorkingFormat")
    res_ = s.get_formats().get_format(wf).get_resolution()
    W, H = int(res_["Width"]), int(res_["Height"])
    saida["formato"] = {"nome": wf, "w": W, "h": H}
    s.start_delta("Ciclo Assist: velocidade e Motion da montagem")
    try:
        for info in s.get_shot_ids():
            a, b = int(info.StartFrame), int(info.EndFrame)
            sh = s.get_shot(info.ShotId)
            try:
                clip = sh.get_metadata_strings({"clip"}).get("clip", "")
                p, k0 = EF.achar_plano(planos, a, b, clip)
                if p is None:
                    continue
                onde = {"quadro": a, "clip": clip}
                try:
                    # as faixas com o NOME do Ciclo: o atualizar corte as separa das do colorista (`camadas.py`)
                    texto = CA.marcar(EF.blg(p, k0, b - a, fps, W, H, molde_r, molde_t))
                    res = sh.get_blg_resources()
                    sh.delete_all_layers()
                    sh.apply_blg_payload(EF.gravar(texto), res)
                    if pasta:
                        arq = os.path.join(pasta, f"ciclo_{int(info.ShotId)}.blg.txt")
                        with open(arq, "w", encoding="latin1") as fh:
                            fh.write(texto)
                        saida["textos"][str(int(info.ShotId))] = arq
                    saida["feitos"].append({**onde, "velocidade": bool(p.get("q")), "motion": bool(p.get("motion"))})
                except Exception as e:                       # noqa: BLE001 — um plano não derruba os outros
                    saida["falhas"].append({**onde, "motivo": f"{type(e).__name__}: {e}"[:200]})
            finally:
                sh.release()
        s.end_delta()
    except Exception:
        s.cancel_delta()
        raise
    s.save_scene()
    feitos = {(x["quadro"]) for x in saida["feitos"]}
    saida["sem_par"] = [{"quadro": p["inicio"], "clip": p.get("clip")} for p in planos
                        if not any(p["inicio"] <= q < p["inicio"] + p["quadros"] for q in feitos)]
    print(json.dumps(saida, ensure_ascii=False))
finally:
    s.close_scene()
    c.close()
