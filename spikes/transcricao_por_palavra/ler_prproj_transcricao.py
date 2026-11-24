import re,sys,struct
b=open(sys.argv[1],'rb').read()
u32=lambda p: struct.unpack_from('<I',b,p)[0]; i32=lambda p: struct.unpack_from('<i',b,p)[0]
u16=lambda p: struct.unpack_from('<H',b,p)[0]
strs={}
for m in re.finditer(rb'[\x20-\x7e\xc0-\xff][\x20-\x7e\x80-\xff]{0,60}\x00',b):
    s=m.group()[:-1]; st=m.start()
    if st>=4 and u32(st-4)==len(s): strs[st-4]=s.decode('utf-8','replace')
def tabela(t):
    vt=t-i32(t)
    if not (0<=vt<len(b)-4): return None
    vl,tl=u16(vt),u16(vt+2)
    if vl<4 or vl>64 or vl%2 or tl<4 or tl>256: return None
    return [u16(vt+4+2*k) for k in range((vl-4)//2)],tl
for so,s in sorted(strs.items()):
    for p in range(0,len(b)-4,4):
        if p+u32(p)==so:
            for t in range(p-60,p+1,4):
                if t<0: continue
                r=tabela(t)
                if r and (p-t) in r[0]:
                    offs,tl=r
                    campos=[]
                    for k,o in enumerate(offs):
                        if not o: campos.append(None); continue
                        q=t+o
                        if q==p: campos.append(f'"{s}"'); continue
                        iv=i32(q); fv=struct.unpack_from('<f',b,q)[0]; dv=struct.unpack_from('<d',b,q)[0] if q+8<=len(b) else None
                        campos.append((iv,round(fv,4),round(dv,4) if dv and abs(dv)<1e7 else None))
                    print(t,campos)
                    break

TICK=254016000000
def palavras():
    res=[]
    for so,s in sorted(strs.items()):
        for p in range(0,len(b)-4,4):
            if p+u32(p)==so:
                for t in range(p-60,p+1,4):
                    if t<0: continue
                    r=tabela(t)
                    if r and len(r[0])>=4 and r[0][2]==p-t:
                        o0,o1=r[0][0],r[0][1]
                        a=struct.unpack_from('<q',b,t+o0)[0]; z=struct.unpack_from('<q',b,t+o1)[0]
                        conf=struct.unpack_from('<f',b,t+r[0][3])[0] if r[0][3] else None
                        res.append((a/TICK,z/TICK,s,conf,t))
                        break
    return res
