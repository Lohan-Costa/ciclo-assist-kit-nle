"""Lab: molde por LinkFile numa bin só dele -> clone de cada irmão numa bin nova (cópia, identidade nova) -> OpenBin
-> colunas (Plug-in, Video, Duration, Start, Image Size, Source Path) do clone."""
from boot import *
import json, shutil, time
from avid.acoes import Acoes
from avb_export.clone_generic import clone_generic
from avb_export import reader as avb_read

def rotulo(arq): return os.path.splitext(os.path.basename(arq))[0]
CHAVES = ["Name", "Plug-in", "Video", "Duration", "Start", "FPS", "Image Size", "Format", "Tracks", "Source File", "Source Path", "Proxy Offline"]

def molde(m, a, arq, nome_bin, ja=False):
    proj = m.projeto()["path"]
    if not ja:
        a.criar_bin(nome_bin)
        mob = a.link_file(arq, nome_bin + ".avb")
        a.salvar(os.path.join(proj, nome_bin + ".avb"))
    else:
        mob = None
    return os.path.join(proj, nome_bin + ".avb"), mob

def uid_novo(p):
    """Bin.uid novo nos bytes (banco avb/escrita.md: uid repetido com a bin aberta = FILE_OPEN_FAILURE)."""
    import struct, random
    with avb_read.topen(p) as f:
        uid = f.content.uid
    raw = open(p, "rb").read()
    novo = random.getrandbits(63)
    n = raw.count(struct.pack("<Q", uid))
    open(p, "wb").write(raw.replace(struct.pack("<Q", uid), struct.pack("<Q", novo)))
    return n

def caminho_win(tpl_bin, out, alvo):
    """WinFileLocator (molde linkado no Windows): `path` e `path_utf8` (com \0\0) na forma D//A/B."""
    from avb_export.relink import replace_field
    from avb_bin.audio import forma_avid
    velho = None
    with avb_read.topen(tpl_bin) as f:
        for m in f.content.mobs:
            d = m.property_data.get("descriptor")
            ph = d.property_data.get("physical_media") if d is not None else None
            loc = ph.property_data.get("locator") if ph is not None else None
            if loc is not None and type(loc).__name__ == "WinFileLocator":
                velho = loc.property_data.get("path"); break
    if not velho: return 0
    novo = forma_avid(alvo)
    raw = open(out, "rb").read()
    Z = bytes(2)
    raw, n1 = replace_field(raw, velho.encode("utf-8"), novo.encode("utf-8"))
    raw, n2 = replace_field(raw, Z + velho.encode("utf-8"), Z + novo.encode("utf-8"))
    open(out, "wb").write(raw)
    print("   caminho:", n1, n2, "->", novo)
    return n1 + n2

def clonar(m, tpl_bin, tpl_clip, alvo, nome_bin, fps):
    proj = m.projeto()["path"]
    out = os.path.join(proj, nome_bin + ".avb")
    r = clone_generic(tpl_bin, tpl_clip, alvo, out, kind="video", fps=fps)
    caminho_win(tpl_bin, out, alvo)
    uid_novo(out)
    m.abrir_bin(out)
    time.sleep(1)
    itens = m.itens_da_bin(m.caminho_relativo_da_bin(out), flags=("masterClips",))
    res = []
    for it in itens:
        c = m.colunas_do_master(it.mob_id)
        res.append({k: c.get(k) for k in CHAVES} | {"mob": it.mob_id})
    return r, res

if __name__ == "__main__":
    fam_chave, i_molde, nome = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    alvos = [int(x) for x in sys.argv[4].split(",")]
    fps = float(sys.argv[5])
    g = json.load(open(os.path.join(S, "assinaturas.json"), encoding="utf-8"))
    fam = [l for k, l in g.items() if fam_chave in k][0]
    with pontes.media_composer() as m:
        a = Acoes(m)
        ja = os.path.exists(os.path.join(m.projeto()["path"], nome + "_MOLDE.avb"))
        tb, mob = molde(m, a, fam[i_molde], nome + "_MOLDE", ja=ja)
        if ja: mob = [x.mob_id for x in m.itens_da_bin(m.caminho_relativo_da_bin(tb))][0]
        print("MOLDE", rotulo(fam[i_molde]), json.dumps({k: m.colunas_do_master(mob).get(k) for k in CHAVES}, ensure_ascii=False))
        for j in alvos:
            r, res = clonar(m, tb, rotulo(fam[i_molde]), fam[j], f"{nome}_CLONE_{j}", fps)
            print("CLONE", rotulo(fam[j]), r)
            for x in res: print("   ", json.dumps(x, ensure_ascii=False))
