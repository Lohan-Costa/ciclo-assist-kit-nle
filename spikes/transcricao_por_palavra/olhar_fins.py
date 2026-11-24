import json,sys
import numpy as np
from cicloassist.midia import voz, falantes
W,S,SP=sys.argv[1:4]
envs={c:np.asarray(e,np.float32) for c,e in falantes.envelopes([W],voz.JANELA_S).items()}
lap=[3,4]; M=voz.mascaras(envs,lap)
n=min(len(envs[c]) for c in lap)
su={c:np.convolve(envs[c][:n].astype(float),np.ones(3)/3,mode="same") for c in lap}
lim={c:np.percentile(su[c],20)*10**(1.0) for c in lap}
np.save(SP+"/su3.npy",su[3]); np.save(SP+"/su4.npy",su[4])
json.dump({"lim":{str(c):float(lim[c]) for c in lap},"ref":{str(c):float(np.percentile(su[c],95)) for c in lap}},open(SP+"/lim.json","w"))
R=json.load(open(SP+"/partes.json")); C=json.load(open(S+"/bordas_para_ouvir_L1_CHAVE.json"))["bordas"]
nn=lambda s:s.lower().strip(".,?!… ")
for r in R: r["l1"]=r["voz_fim"] if r["voz_fim"] is not None else (r["ctc_fim"]+.06 if r["ctc_fim"] else r["whisper_fim"])
for b in C:
    if b["tipo"]!="FIM" or b["n"]==1: continue
    k=min((i for i,r in enumerate(R) if nn(r["palavra"])==nn(b["palavra"])),key=lambda i:abs(R[i]["l1"]-b["nosso_s"]))
    r=R[k]; prox=R[k+1] if k+1<len(R) else None
    P=b["premiere_s"]; t0=P-0.15; t1=max(r["l1"],P)+0.2
    print(f"\n{b['n']:02d} {b['palavra']} premiere {P:.2f} ctc {r['ctc_fim']:.2f} L1 {r['l1']:.2f} | próxima '{prox['palavra']}' ctc_ini {prox['ctc_ini']}")
    for c in lap:
        row=""
        for t in np.arange(t0,t1,0.05):
            i=int(round(t/0.01)); db=10*np.log10(su[c][i:i+5].mean()/lim[c])
            row+=("█" if M[c][i] else "·")+f"{db:+3.0f}"[-3:]+" "
        print(f" lap{c}: {row}")
    print("        "+" ".join(f"{t-P:+.2f}"[:5].rjust(4) for t in np.arange(t0,t1,0.05)))
