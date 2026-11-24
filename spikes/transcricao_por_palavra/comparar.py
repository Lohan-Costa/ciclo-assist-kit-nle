import json, sys, re, subprocess, unicodedata, difflib
import numpy as np
S=sys.argv[1]; WAV=sys.argv[2]
r=json.load(open(f'{S}/resolve.json',encoding='utf-8')); n=json.load(open(f'{S}/{sys.argv[3]}',encoding='utf-8'))
FPS=24000/1001; NOM=24
def tc(s):
    h,m,se,f=map(int,s.split(':')); return (h*3600+m*60+se)*NOM+f
base=tc(r['start_tc'])
def norm(w): return re.sub(r'[^\w]','',unicodedata.normalize('NFC',w.lower()))
R=[]
for s in r['t']['segments']:
    for w in s['words']:
        if w['text'].strip()=='(...)': continue
        R.append((norm(w['text']),(tc(w['start'])-base)/FPS,(tc(w['end'])-base)/FPS,w['text'].strip()))
N=[(norm(w['palavra']),w['t'],w['fim'],w['palavra']) for f in n['falas'] for w in f['palavras']]
# energia por canal
info=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',WAV],capture_output=True).stdout)
ch=int(info['streams'][0]['channels'])
raw=subprocess.run(['ffmpeg','-v','error','-i',WAV,'-ar','16000','-f','s16le','-'],capture_output=True).stdout
a=np.frombuffer(raw,np.int16).reshape(-1,ch).astype(np.float32)/32768
p=160; k=len(a)//p
e=np.square(a[:k*p]).reshape(k,p,ch).mean(1)
db=10*np.log10(np.maximum(e,1e-12))
piso=np.percentile(db,20,axis=0); print('piso dB por canal',np.round(piso,1),'p95',np.round(np.percentile(db,95,axis=0),1))
vozc=(db>piso+15)&(db>=db.max(1,keepdims=True)-3)
voz=vozc.any(1)
def canal(t0,t1):
    i0,i1=int(t0*100),max(int(t0*100)+1,int(t1*100)); return int(np.argmax(db[i0:i1].mean(0)-piso))
def frac_voz(t0,t1):
    i0,i1=int(t0*100),max(int(t0*100)+1,int(t1*100)); return float(voz[i0:i1].mean())
def borda_real(t, lado, c=None):
    # procura a borda de voz real mais proxima (inicio: primeira janela com voz a partir de t-0.5; fim: ultima com voz ate t+0.5)
    i=int(t*100); v=vozc[:,c]
    # anda a partir da borda do ASR: para fora enquanto houver voz (com tolerancia de 120 ms), para dentro enquanto nao houver
    if lado=='fim':
        j=i
        if v[j-1]:
            gap=0
            while j<min(len(v)-1,i+60) and gap<12: gap=0 if v[j] else gap+1; j+=1
            return (j-gap)/100
        while j>i-50 and not v[j-1]: j-=1
        return j/100
    else:
        j=i
        if v[j]:
            gap=0
            while j>max(0,i-60) and gap<12: gap=0 if v[j-1] else gap+1; j-=1
            return (j+gap)/100
        while j<i+50 and not v[j]: j+=1
        return j/100
    if lado=='ini':
        j=i-50
        while j<i+50 and not voz[max(j,0)]: j+=1
        return j/100
    j=i+50
    while j>i-50 and not voz[min(j,len(voz)-1)]: j-=1
    return (j+1)/100
sm=difflib.SequenceMatcher(None,[x[0] for x in R],[x[0] for x in N],autojunk=False)
pares=[(R[b.a+i],N[b.b+i]) for b in sm.get_matching_blocks() for i in range(b.size)]
print('palavras resolve',len(R),'nosso',len(N),'casadas',len(pares))
def est(nome,v):
    v=np.array(v); print(f'  {nome}: mediana {np.median(v)*1000:+.0f} ms | |p90| {np.percentile(np.abs(v),90)*1000:.0f} ms')
est('inicio resolve-nosso',[a[1]-b[1] for a,b in pares]); est('fim resolve-nosso',[a[2]-b[2] for a,b in pares])
for nome,L in (('resolve',R),('nosso',N)):
    cola=sum(1 for x,y in zip(L,L[1:]) if abs(y[1]-x[2])<0.001)
    dur=np.array([x[2]-x[1] for x in L])
    # bordas de FRASE (palavra seguida de pausa >=0.3 s pela propria lista)
    fins=[x for x,y in zip(L,L[1:]) if y[1]-x[2]>=0.3]+[L[-1]]
    inis=[L[0]]+[y for x,y in zip(L,L[1:]) if y[1]-x[2]>=0.3]
    dfim=np.array([x[2]-borda_real(x[2],'fim',canal(x[1],x[2])) for x in fins]); dini=np.array([x[1]-borda_real(x[1],'ini',canal(x[1],x[2])) for x in inis])
    print(f'{nome}: coladas {cola}/{len(L)-1} ({100*cola/(len(L)-1):.0f}%) | dur mediana {np.median(dur):.2f}s, >0.8s: {(dur>0.8).sum()}')
    print(f'  inicio de frase - borda real: mediana {np.median(dini)*1000:+.0f} ms, |p90| {np.percentile(np.abs(dini),90)*1000:.0f} ms (n={len(dini)})')
    print(f'  fim de frase - borda real:    mediana {np.median(dfim)*1000:+.0f} ms, |p90| {np.percentile(np.abs(dfim),90)*1000:.0f} ms; cortaria voz >1 quadro (42ms): {(dfim<-0.042).sum()}; inicio depois da voz >1q: {(dini>0.042).sum()}')
    lac=[(x[3],y[3],round(y[1]-x[2],2)) for x,y in zip(L,L[1:]) if y[1]-x[2]>=0.3 and frac_voz(x[2],y[1])>0.6]
    print(f'  "silencio" com voz dentro (>60%): {len(lac)}', lac[:4])
