"""Master com UMA trilha de som habilitada: cópia da _MIDIAS (Bin.uid e MobID do master novos) — exporta e mede."""
import os, random, sys
from pathlib import Path
sys.path[:0] = ['plugins/media-composer/servico', 'motor']
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ouvido_trilha_lib import tons
from avb_export.reader import topen
from avb.mobid import MobID
from avid.mcapi import MediaComposer
from avid.acoes import Acoes
PROJ = Path("/Volumes/SSD/MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/PROJETO/LAB COR MC")
SAI, alvo, master = sys.argv[1], sys.argv[2], sys.argv[3]
PASTA = PROJ / "OUVIDO v01"
with MediaComposer(timeout=60) as mc:
    a = Acoes(mc)
    for n in [int(v) for v in sys.argv[4:]]:
        dest = PASTA / f"{alvo} M {master[4:8]} A{n}.avb"
        if dest.exists():
            print("JA_EXISTE", dest); continue
        with topen(str(PROJ / alvo / f"{alvo}_MIDIAS.avb")) as f:
            m = next(x for x in f.content.mobs if x.property_data.get("mob_type_id") == 2 and x.name == master)
            for t in m.tracks:
                if getattr(t.component, "media_kind", "") == "sound":
                    t.session_attr["_ENBLSTATE"] = 1 if t.index == n else 0
            novo = f"{master} A{n}"
            m.name = novo
            m.mob_id = MobID(bytes_le=bytes(m.mob_id.bytes_le[:16]) + os.urandom(16))
            f.content.uid = random.getrandbits(63)
            f.write(str(dest))
        mc.abrir_bin(str(dest))
        s = [x for x in mc.itens_de(str(dest), flags=("masterClips",)) if x.name == novo][0]
        arq = a.export_file(s.mob_id, SAI, f"M_{master[4:8]}_A{n}", preset="DLPC_LAB_DNXLB", espera_s=120)
        mc.fechar_bin(str(dest))
        print(f"{master} trilha {n}:", [(q, pk) for q, pk in tons(arq) if pk][:3], flush=True)
