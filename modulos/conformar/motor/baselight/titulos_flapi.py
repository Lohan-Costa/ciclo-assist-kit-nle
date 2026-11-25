"""As faixas de texto dos títulos (marcadas `CICLO_TITULO_<i>`) e os pretos numa scene — o passo 1 de `titulos.py`.
Entrada (stdin): {"duracoes": [quadros…], "pretos": [quadros…]}. Roda no python da FilmLight, chamado por
`enviar.trazer_titulos`; veio do estudo (`titulos_prodc.py inserir`). O tempo e a linha de cada faixa quem dá é o `montar`.
"""
import json
import sys

import flapi

p = json.load(sys.stdin)
c = flapi.Connection("localhost")
c.connect()
s = c.Scene.open_scene(c.Scene.parse_path(sys.argv[1]), set())
s.wait_until_open()
try:
    base = s.get_shot(s.get_shot_ids()[0].ShotId)
    s.start_delta("Ciclo Assist: os títulos (faixas)")
    for i, d in enumerate(p["duracoes"]):
        s.insert_text(f"CICLO_TITULO_{i}", float(d), "above", base, flapi.ROP_TEXT_ALIGN_CENTER)
    for d in p["pretos"]:
        s.insert_blank(0.0, 0.0, 0.0, float(d), "above", base)
    s.end_delta()
    s.save_scene()
    print(json.dumps({"titulos": len(p["duracoes"]), "pretos": len(p["pretos"])}))
finally:
    s.close_scene()
    c.close()
