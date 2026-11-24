"""Bin golden: LinkFile de toda a família (a verdade do MC), com pausa anti-rajada."""
from boot import *
import json, time
from avid.acoes import Acoes
fam_chave, nome = sys.argv[1], sys.argv[2]
g = json.load(open(os.path.join(S, "assinaturas.json"), encoding="utf-8"))
fam = [l for k, l in g.items() if fam_chave in k][0]
with pontes.media_composer() as m:
    a = Acoes(m)
    a.criar_bin(nome)
    for arq in fam:
        time.sleep(3)
        try: a.link_file(arq, nome + ".avb"); print("OK ", os.path.basename(arq))
        except Exception as e: print("NÃO", os.path.basename(arq), str(e)[-80:].replace("\n", " "))
    b = os.path.join(m.projeto()["path"], nome + ".avb")
    a.salvar(b)
    print(len(m.itens_da_bin(m.caminho_relativo_da_bin(b))), "masters na golden")
