"""As máscaras do Premiere (`mascaras.py`) numa scene, pela FLAPI. Roda no python da FilmLight, chamado por
`enviar.aplicar_mascaras`; veio do estudo PRODUCAO-C (`estudo/ferramentas/mascaras_PRODC.py gerar/gravar1`).

    efeitos… mascaras_flapi.py listar  localhost:JOB:SCENE            → JSON {formato, shots: [{n, shot_id, a, b, clip}]}
    efeitos… mascaras_flapi.py gravar1 localhost:JOB:SCENE n shot_id plano.blg.txt

⛔ UM plano por processo (abrir, delta, apply, salvar, fechar): 11 composições num processo só PARARAM o `end_delta`/
`save_scene` (estudo, 22ª rodada); um processo curto por plano nunca travou. Quem chama dá o prazo.
"""
import base64
import json
import struct
import sys
import zlib

import flapi

modo, cena = sys.argv[1], sys.argv[2]
c = flapi.Connection("localhost")
c.connect()
if modo == "listar":
    s = c.Scene.open_scene(c.Scene.parse_path(cena), {flapi.OPENFLAG_READ_ONLY})
    s.wait_until_open()
    try:
        wf = s.get_scene_settings().get_single("WorkingFormat")
        r = s.get_formats().get_format(wf).get_resolution()
        shots = []
        for n, info in enumerate(s.get_shot_ids(), 1):
            sh = s.get_shot(info.ShotId)
            try:
                clip = sh.get_metadata_strings({"clip"}).get("clip", "")
            finally:
                sh.release()
            shots.append({"n": n, "shot_id": int(info.ShotId), "a": int(info.StartFrame), "b": int(info.EndFrame),
                          "clip": clip})
        print(json.dumps({"formato": {"nome": wf, "w": int(r["Width"]), "h": int(r["Height"])}, "shots": shots},
                         ensure_ascii=False))
    finally:
        s.close_scene()
        c.close()
elif modo == "gravar1":
    n, shot_id, arq = int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    texto = open(arq, encoding="latin1").read().encode("latin1")
    s = c.Scene.open_scene(c.Scene.parse_path(cena), set())
    s.wait_until_open()
    try:
        info = s.get_shot_ids()[n - 1]
        if int(info.ShotId) != shot_id:
            raise SystemExit(f"o plano {n} mudou de ShotId ({info.ShotId} ≠ {shot_id})")
        sh = s.get_shot(info.ShotId)
        s.start_delta(f"Ciclo Assist: a máscara da montagem (plano {n})")
        res = sh.get_blg_resources()
        sh.delete_all_layers()
        sh.apply_blg_payload(base64.b64encode(struct.pack("<Q", len(texto)) + zlib.compress(texto)).decode(), res)
        s.end_delta()
        s.save_scene()
        print(json.dumps({"gravado": n}))
    finally:
        s.close_scene()
        c.close()
