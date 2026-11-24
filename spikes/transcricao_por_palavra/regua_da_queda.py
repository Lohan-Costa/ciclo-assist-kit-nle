import json,sys
import numpy as np
S,SP=sys.argv[1:3]
su={3:np.load(SP+"/su3.npy"),4:np.load(SP+"/su4.npy")}
db={c:10*np.log10(np.maximum(v,1e-12)) for c,v in su.items()}
R=json.load(open(SP+"/partes.json")); C=json.load(open(S+"/bordas_para_ouvir_L1_CHAVE.json"))["bordas"]
V={v["n"]:v["resposta"] for v in json.load(open(S+"/vereditos_L1.json"))["vereditos"]}
nn=lambda s:s.lower().strip(".,?!… ")
for r in R: r["l1"]=r["voz_fim"] if r["voz_fim"] is not None else (r["ctc_fim"]+.06 if r["ctc_fim"] else r["whisper_fim"])
casos=[]
for b in C:
    if b["tipo"]!="FIM" or not V.get(b["n"]): continue
    k=min((i for i,r in enumerate(R) if nn(r["palavra"])==nn(b["palavra"])),key=lambda i:abs(R[i]["l1"]-b["nosso_s"]))
    a=V[b["n"]]; ganhou=b["A"] if a=="A" else ("premiere" if b["A"]=="nosso" else "nosso")
    casos.append((b,R[k],R[k+1],ganhou))
def regra(r,prox,D,seg=0.05,teto=0.6):
    a,z=int(round(r["ctc_ini"]/0.01)),int(round(r["ctc_fim"]/0.01))
    c=max(db,key=lambda c:db[c][a:z+1].max())           # a lapela de quem fala: a mais forte NA palavra
    pico=db[c][max(a,z-30):z+1].max()                    # o pico do fim da palavra (últimos 300 ms)
    lim=int(round(min(r["ctc_fim"]+teto,(prox["ctc_ini"] or 1e9)-0.03)/0.01))
    i=z; w=int(seg/0.01)
    while i<lim and not np.all(db[c][i:i+w]<pico-D): i+=1
    return max(i*0.01, r["ctc_fim"]+0.06), c
for D in (10,12,15,18,20):
    ok=0; lin=[]
    for b,r,prox,g in casos:
        e,c=regra(r,prox,D); P,L=b["premiere_s"],b["nosso_s"]
        perto="premiere" if abs(e-P)<abs(e-L) else "nosso"
        ok+=perto==g; lin.append(f"{b['palavra'][:9]:9}{1000*(e-P):+5.0f}{'✓' if perto==g else '✗'}")
    print(f"D={D:2d}: {ok}/{len(casos)}  "+" ".join(lin))
