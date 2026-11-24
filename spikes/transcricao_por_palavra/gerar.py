"""Áudio sintético com o gabarito de cada palavra: cada palavra é falada à parte pelo `say`, aparada pela energia e colada.
Dentro da frase as palavras encostam (vão 0) ou têm vão pequeno; entre frases, pausas variadas."""
import subprocess, sys, json, numpy as np, os
S=sys.argv[1]; R=48000
FR={'pt':('Eddy (Português (Brasil))',[
 "Eu acho melhor que a gente se apresente","A carta já explica tudo pode ler","Não duvido","Mas é importante entender o que te trouxe aqui pessoalmente",
 "Sobe comigo","Agora","A câmera está pronta para gravar","Quem chegou primeiro ficou com a sala","Ela não respondeu nada","Vamos repetir a cena do começo"]),
 'en':('Eddy (Inglês (EUA))',[
 "I think we should introduce ourselves","The letter already explains everything you can read it","I do not doubt it","But it is important to understand what brought you here in person",
 "Come up with me","Now","The camera is ready to record","Whoever arrived first kept the room","She did not answer anything","Let us repeat the scene from the start"])}
VAOS_FRASE=[0.25,1.5,0.4,2.0,0.3,0.8,3.0,0.5,1.0]
VAOS_PALAVRA=[0.0,0.0,0.06,0.0,0.15,0.0]   # padrão que se repete dentro da frase
def palavra(voz,txt):
    a=f'{S}/sint/_w.aiff'; subprocess.run(['say','-v',voz,'-o',a,txt],check=True)
    raw=subprocess.run(['ffmpeg','-v','error','-i',a,'-ac','1','-ar',str(R),'-f','f32le','-'],capture_output=True,check=True).stdout
    x=np.frombuffer(raw,np.float32); e=np.convolve(x**2,np.ones(240)/240,'same')
    on=np.where(e>1e-5)[0]; return x[on[0]:on[-1]+1]
for lg,(voz,frases) in FR.items():
    out=[np.zeros(int(R*1.0),np.float32)]; gab=[]; t=1.0; k=0
    for i,f in enumerate(frases):
        for j,w in enumerate(f.split()):
            if j: g=VAOS_PALAVRA[k%len(VAOS_PALAVRA)]; k+=1; out.append(np.zeros(int(R*g),np.float32)); t+=int(R*g)/R
            x=palavra(voz,w); gab.append({'palavra':w,'t':t,'fim':t+len(x)/R,'frase':i}); out.append(x); t+=len(x)/R
        g=VAOS_FRASE[i] if i<len(VAOS_FRASE) else 1.0; out.append(np.zeros(int(R*g),np.float32)); t+=int(R*g)/R
    y=np.concatenate(out); y=y/np.abs(y).max()*0.5
    wav=f'{S}/sint/sintetico_{lg}.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','f32le','-ar',str(R),'-ac','1','-i','-','-c:a','pcm_s24le',wav],input=y.tobytes(),check=True)
    json.dump(gab,open(f'{S}/sint/gabarito_{lg}.json','w'),ensure_ascii=False,indent=1)
    print(lg,len(gab),'palavras',round(t,1),'s')
