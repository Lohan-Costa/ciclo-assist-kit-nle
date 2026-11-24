import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modulos", "conformar", "motor"))
from avb_export.reader import topen

P = r"%USERPROFILE%\Documents\Avid Projects\CICLO ENSAIO 25"

def comps(c, ind=4):
    pd = c.property_data
    nome = type(c).__name__
    extra = {k: pd.get(k) for k in ("edit_rate", "length", "start_time", "track_id", "media_kind_id") if k in pd}
    alvo = str(pd.get("mob_id", ""))[-24:] if "mob_id" in pd else ""
    print(" " * ind + f"{nome} {extra} {alvo}")
    for x in pd.get("components") or []:
        comps(x, ind + 2)
    for k in ("input_segments",):
        for x in pd.get(k) or []:
            comps(x, ind + 2)

for b in ("CICLO ENSAIO 25.avb", "CICLO ENSAIO 25 CAM.avb", "CICLO ENSAIO 25 SOM.avb"):
    print("=====", b)
    with topen(os.path.join(P, b)) as f:
        for m in f.content.mobs:
            pd = m.property_data
            if pd.get("mob_type_id") == 3:
                continue
            print(f"MOB tipo={pd.get('mob_type_id')} usage={pd.get('usage_code')} {m.name!r} id=..{str(m.mob_id)[-24:]}")
            for t in pd.get("tracks") or []:
                tp = t.property_data
                c = tp.get("component")
                print(f"  track idx={tp.get('index')} kind={getattr(c, 'media_kind', None)}")
                if c is not None:
                    comps(c)
