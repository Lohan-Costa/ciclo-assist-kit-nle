import sqlite3,sys,subprocess,struct,json,re,unicodedata,difflib
import numpy as np
S=sys.argv[1]
def varint(b,i):
    r=s=0
    while True:
        x=b[i]; i+=1; r|=(x&0x7f)<<s; s+=7
        if x<0x80: return r,i
def campos(b):
    i=0; out={}
    while i<len(b):
        k,i=varint(b,i); f,w=k>>3,k&7
        if w==0: v,i=varint(b,i)
        elif w==5: v=struct.unpack('<f',b[i:i+4])[0]; i+=4
        elif w==1: v=struct.unpack('<d',b[i:i+8])[0]; i+=8
        else: n,i=varint(b,i); v=b[i:i+n]; i+=n
        out.setdefault(f,[]).append(v)
    return out
def do_resolve(marca):
    c=sqlite3.connect(S+'/Project2.db')
    for (v,) in c.execute('select FieldsBlob from BtLockableBlob where FieldsBlob is not null'):
        k=v.find(bytes.fromhex('28b52ffd'))
        if k<0: continue
        d=subprocess.run(['zstd','-d','-c'],input=v[k:],capture_output=True).stdout
        if marca.encode() in d and d.count(b'\n')<400 and b'Cortou' not in d:
            W=[campos(x) for x in campos(d).get(6,[])]
            return [(w.get(1,[0.0])[0],w.get(2,[0.0])[0],w.get(3,[b""])[0].decode()) for w in W]
norm=lambda w: re.sub(r'[^\w]','',unicodedata.normalize('NFC',w.lower()))
def avaliar(nome,lista,gab):
    L=[(norm(t),a,b,t) for a,b,t in lista if norm(t)]
    G=[(norm(g['palavra']),g['t'],g['fim'],g['frase']) for g in gab]
    sm=difflib.SequenceMatcher(None,[x[0] for x in L],[x[0] for x in G],autojunk=False)
    P=[(L[b.a+i],G[b.b+i]) for b in sm.get_matching_blocks() for i in range(b.size)]
    di=np.array([a[1]-g[1] for a,g in P]); df=np.array([a[2]-g[2] for a,g in P])
    # fim de frase: ultima palavra de cada frase
    ult={}; pri={}
    for a,g in P:
        ult[g[3]]=(a,g); pri.setdefault(g[3],(a,g))
    dff=np.array([a[2]-g[2] for a,g in ult.values()]); dif=np.array([a[1]-g[1] for a,g in pri.values()])
    q=1001/24000
    print(f'\n{nome}: casadas {len(P)}/{len(G)}')
    print(f'  inicio: mediana {np.median(di)*1000:+.0f} ms | dentro de 1 quadro {np.mean(abs(di)<=q)*100:.0f}% | |p90| {np.percentile(abs(di),90)*1000:.0f} ms')
    print(f'  fim:    mediana {np.median(df)*1000:+.0f} ms | dentro de 1 quadro {np.mean(abs(df)<=q)*100:.0f}% | |p90| {np.percentile(abs(df),90)*1000:.0f} ms')
    print(f'  1a palavra da frase: inicio mediana {np.median(dif)*1000:+.0f} ms, antes da voz >1q: {(dif<-q).sum()}, depois da voz >1q (corta o ataque): {(dif>q).sum()} de {len(dif)}')
    print(f'  ult palavra da frase: fim mediana {np.median(dff)*1000:+.0f} ms, corta a voz >1q: {(dff<-q).sum()}, engole silencio >1q: {(dff>q).sum()} de {len(dff)}')
    cola=sum(1 for x,y in zip(L,L[1:]) if abs(y[1]-x[2])<1e-4); print(f'  palavras coladas na seguinte: {cola}/{len(L)-1}')
    return P
gpt=json.load(open(S+'/sint/gabarito_pt.json')); gen=json.load(open(S+'/sint/gabarito_en.json'))
OFF=0.0
rpt=do_resolve('gravar'); ren=do_resolve('ourselves')
print('resolve pt entradas',len(rpt),'silencios',sum(t.strip()=='(...)' for *_,t in rpt),'| en',len(ren))
avaliar('RESOLVE pt',[x for x in rpt if x[2].strip()!='(...)'],gpt)
avaliar('RESOLVE en',[x for x in ren if x[2].strip()!='(...)'],gen)
n=json.load(open(S+'/sint/nosso_pt.json'))
avaliar('NOSSO pt (faster-whisper small)',[(w['t'],w['fim'],w['palavra']) for f in n['falas'] for w in f['palavras']],gpt)
json.dump({'rpt':rpt,'ren':ren},open(S+'/sint/resolve_sint.json','w'),ensure_ascii=False)
