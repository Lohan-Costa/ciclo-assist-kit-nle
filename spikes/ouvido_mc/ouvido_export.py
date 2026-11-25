"""Exporta pelo MC (preset do lab DLPC_LAB_DNXLB: MXF, som mono por trilha) as sequências de teste do LAB COR MC."""
import json, sys, time
from pathlib import Path
sys.path[:0] = ['plugins/media-composer/servico', 'motor']
P = "/Volumes/SSD/PROGRAMAS COM CLAUDE/piloto"
sys.path.insert(0, P)
from piloto import olhos
from avid.mcapi import MediaComposer
from avid.acoes import Acoes
LAB = Path("/Volumes/SSD/PROGRAMAS COM CLAUDE/laboratorio-de-midia/lab/bancadas/avid/presets/DLPC_LAB_DNXLB.xml")
PROJ = Path("/Volumes/SSD/MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/PROJETO/LAB COR MC")
SAI = Path(sys.argv[1]); SAI.mkdir(parents=True, exist_ok=True)
FOTOS = sys.argv[2]
ALVOS = sys.argv[3:]
with MediaComposer(timeout=60) as mc:
    a = Acoes(mc)
    assert "LAB COR MC" in mc.projeto()["path"]
    lista = list(mc._chamar("GetListOfExportSettings").body.setting_names)
    if "DLPC_LAB_DNXLB" not in lista:
        mc._chamar("LoadSetting", _timeout=60, unique_id="DLPC_LAB_DNXLB", xml_setting=LAB.read_text(encoding="utf-8"))
        print("preset instalado", flush=True)
    res = {}
    for alvo in ALVOS:
        b = PROJ / alvo / f"{alvo}_SEQ.avb"
        seqs = mc.itens_de(str(b), flags=("sequences",))
        print(alvo, [s.name for s in seqs], flush=True)
        s = seqs[0]
        t = time.time()
        arq = a.export_file(s.mob_id, str(SAI), alvo.replace(" ", "_"), preset="DLPC_LAB_DNXLB", espera_s=300)
        dlg = [w["titulo"] for w in olhos.janelas("AvidMediaComposer") if w["titulo"] not in ("Bins.1",) and not w["titulo"].startswith("Avid Media Composer  -")]
        print("  ->", arq, f"{time.time()-t:.1f}s", "janelas:", dlg, flush=True)
        if dlg:
            print("  FOTO", olhos.foto_da_tela(FOTOS, "export_dialogo")); break
        res[alvo] = {"seq": s.name, "arquivo": arq}
    print(json.dumps(res, ensure_ascii=False))
