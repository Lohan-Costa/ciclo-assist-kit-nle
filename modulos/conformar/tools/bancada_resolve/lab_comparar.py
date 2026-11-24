"""Clona todos os irmãos de uma família a partir do molde (índice 0) e compara com a bin golden (LinkFile do MC)."""
from boot import *
import json, time
from avid.acoes import Acoes
import lab_clonar as L
fam_chave, nome, golden_bin, fps = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
def desc_lens(binp, nome):
    """Tudo o que tem COMPRIMENTO no clipe (pyavb): descritores e os componentes de cada trilha de cada mob,
    por papel (master / classe do descritor) — o que a coluna da bin não mostra."""
    from avb_export import reader as R
    out = {}
    def comps(c, d=0):
        if c is None or d > 6: return []
        pd = c.property_data
        r = [(type(c).__name__, pd.get("length"), pd.get("start_time"))] if "length" in pd else []
        for x in pd.get("components", []) or []: r += comps(x, d + 1)
        return r
    with R.topen(binp) as f:
        for m in f.content.mobs:
            if m.property_data.get("name") != nome: continue
            d = m.property_data.get("descriptor")
            papel = type(d).__name__ if d is not None else "master"
            if d is not None:
                for x in [d] + list(d.property_data.get("descriptors") or []):
                    if x.property_data.get("length") is not None: out[type(x).__name__ + ".len"] = x.property_data.get("length")
            for t in m.property_data.get("tracks", []) or []:
                out[f"{papel}.t{t.property_data.get('index')}"] = comps(t.property_data.get("component"))
    return out
IGNORA = {"Creation Date", "Modified Date"}
g = json.load(open(os.path.join(S, "assinaturas.json"), encoding="utf-8"))
fam = [l for k, l in g.items() if fam_chave in k][0]
with pontes.media_composer() as m:
    a = Acoes(m)
    proj = m.projeto()["path"]
    gb = os.path.join(proj, golden_bin + ".avb")
    gold = {}
    for it in m.itens_da_bin(m.caminho_relativo_da_bin(gb)):
        c = m.colunas_do_master(it.mob_id); gold[c.get("Name")] = c
    tb, mob = L.molde(m, a, fam[0], nome + "_MOLDE")
    tpl = L.rotulo(fam[0])
    tot = ok = 0
    for j in range(1, len(fam)):
        out = os.path.join(proj, f"{nome}_CLONE_{j}.avb")
        t = time.time()
        r = L.clone_generic(tb, tpl, fam[j], out, kind="video", fps=fps, mesma_geometria=True)
        pass
        m.abrir_bin(out)
        its = m.itens_da_bin(m.caminho_relativo_da_bin(out))
        c = m.colunas_do_master(its[0].mob_id)
        gc = gold.get(L.rotulo(fam[j]), {})
        dif = {k: (gc.get(k), c.get(k)) for k in set(gc) | set(c) if k not in IGNORA and gc.get(k) != c.get(k)}
        dl = desc_lens(out, L.rotulo(fam[j])); dg = desc_lens(gb, L.rotulo(fam[j]))
        for k in set(dl) | set(dg):
            if k.endswith(".t1") and k.startswith("TapeDescriptor"): continue
            if dl.get(k) != dg.get(k): dif["_" + k] = (dg.get(k), dl.get(k))
        tot += 1; ok += not dif
        print(j, L.rotulo(fam[j]), "IGUAL" if not dif else "DIFERE", round(time.time() - t, 2), "s", json.dumps(dif, ensure_ascii=False))
    print(f"{ok}/{tot} iguais ao LinkFile")
